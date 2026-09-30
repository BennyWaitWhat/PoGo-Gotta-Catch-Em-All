#!/system/bin/sh
# =============================================================================
#  selftest.sh  —  READ-ONLY sanity self-test for the on-device PoGo catcher.
#
#  PURPOSE
#    Run this ON THE PHONE, via root, AFTER a deploy (install_ondevice_catcher
#    .FULL.sh has staged the files) but typically BEFORE / instead of trusting
#    the catcher blind. It answers, with evidence, the four questions that
#    decide whether autonomous catching can possibly work:
#
#      1. Does catch.js exist, and is it syntactically valid JavaScript?
#         (node -c if available; else qjs; else a self-contained structural
#          checker: balanced braces/parens/brackets + presence of the exact
#          load-bearing constructs this specific catch.js must contain.)
#      2. Do the gadget mode-config JSONs parse, and are they the RIGHT shape?
#         (script config -> type:"script" + path -> catch.js + runtime:"qjs";
#          listen config -> type:"listen" + port 27047. python3/jq if present;
#          else a self-contained brace/quote/key checker.)
#      3. Do all the paths the system depends on actually exist on the device?
#         (gadget dir, libgadget.so, both named configs, the live config,
#          catch.js, pogo-catch.sh; PoGo package installed.)
#      4. WOULD PoGo load script mode right now? i.e. is the LIVE config
#         (libgadget.config.so) currently type:"script" pointing at an existing
#         catch.js — and is the gadget binary a Frida version that actually
#         EXECUTES gadget script mode (16.x = yes; 17.x = parsed-but-not-run,
#         the #1 deploy risk) ? Plus: is the ON/OFF marker present (catching
#         armed) or absent (idle)?
#
#  CONTRACT
#    * 100% READ-ONLY. This script never writes, moves, deletes, force-stops,
#      relaunches, swaps a config, attaches Frida, or touches the toggle marker.
#      The ONLY thing it writes is one tiny tempfile under $TMPDIR (Termux's own
#      private tmp), used to test JS syntax with node/qjs; it is removed on exit.
#      It does NOT write anything into the gadget dir or run anything against
#      PoGo's process. Safe to run while the desktop catcher is attached.
#    * Self-contained: needs only toybox/busybox + root (su). node, qjs, python3,
#      and jq are all OPTIONAL — used when found, with a pure-shell fallback for
#      each so the test is fully functional on a bare Termux.
#    * Exit code: 0 = all critical checks passed (autonomous catching is wired
#      and, per the live config, would arm on next PoGo launch when toggled ON).
#      1 = at least one CRITICAL check failed (FAIL). 2 = bad usage.
#      WARN-level findings (e.g. Frida 17.x, live config in listen mode, marker
#      absent) do NOT fail the run on their own — they are reported loudly and,
#      where they block autonomy, summarised at the end.
#
#  USAGE  (from Termux)
#      su -c 'sh /data/local/tmp/re.zyg.fri/selftest.sh'
#    or, if you keep it in the repo-mirror dir on /sdcard:
#      su -c 'sh /sdcard/ondevice_toggle/selftest.sh'
#    Flags:
#      -q   quiet: only the section verdicts + final summary (no per-line PASS)
#      -h   help
#
#  Ported/grounded against the real artifacts (do not drift from these):
#    - catch.js                         (the self-contained catcher under test)
#    - configswap_toggle/pogo-catch.sh  (config-swap toggle; same paths/JSON)
#    - DEPLOY_commands.md               (the path + JSON contract)
#    - pogo_il2cpp.py JS_PREAMBLE       (the liveness exports catch.js ports)
#    - scripts/game_write/catch_loop_fast.py (the IL2CPP/catch logic catch.js ports)
# =============================================================================

# NB: deliberately NOT `set -e` — this is a diagnostic; we want EVERY check to
# run and report, not abort on the first non-zero. We track failures explicitly.
set -u

# ----------------------------- configuration ---------------------------------
DIR=/data/local/tmp/re.zyg.fri
CATCH_JS="$DIR/catch.js"
LIVE_CFG="$DIR/libgadget.config.so"        # the config the gadget actually reads
SCRIPT_CFG="$DIR/config.script.so"         # canonical SCRIPT-mode config
LISTEN_CFG="$DIR/config.listen.so"         # canonical LISTEN-mode config
GADGET_SO="$DIR/libgadget.so"              # the (renamed) frida gadget binary
TOGGLE_SH="$DIR/pogo-catch.sh"             # config-swap toggle (optional on device)
MARKER="$DIR/catch.on"                     # presence == catching ON
LOGF="$DIR/catch.log"                      # catcher's own logcat-mirror file
HBF="$DIR/catch.hb"                        # heartbeat (written ~1/s by manage())
PKG=com.nianticlabs.pokemongo

# Where node/qjs may drop a tempfile for the -c syntax test. Prefer Termux's
# private tmp (always app-writable); fall back to $DIR only for the read.
TMPDIR_SELF="${TMPDIR:-/data/data/com.termux/files/usr/tmp}"
[ -d "$TMPDIR_SELF" ] || TMPDIR_SELF="/data/local/tmp"
TMPJS=""

QUIET=0
for a in "$@"; do
  case "$a" in
    -q) QUIET=1 ;;
    -h|--help)
      sed -n '2,60p' "$0" 2>/dev/null | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "selftest: unknown arg: $a (use -h)"; exit 2 ;;
  esac
done

# ------------------------------- output helpers ------------------------------
# Colorless by default (logcat / file redirect friendly). Counters drive exit.
NPASS=0; NWARN=0; NFAIL=0
SUMMARY=""        # accumulates one-line headlines for the footer

_p()  { [ "$QUIET" -eq 1 ] || printf '  [PASS] %s\n' "$*"; NPASS=$((NPASS+1)); }
_w()  { printf '  [WARN] %s\n' "$*"; NWARN=$((NWARN+1)); SUMMARY="$SUMMARY
  WARN: $*"; }
_f()  { printf '  [FAIL] %s\n' "$*"; NFAIL=$((NFAIL+1)); SUMMARY="$SUMMARY
  FAIL: $*"; }
_i()  { [ "$QUIET" -eq 1 ] || printf '  ---- %s\n' "$*"; }
_sec(){ printf '\n=== %s ===\n' "$*"; }

cleanup() { [ -n "$TMPJS" ] && rm -f "$TMPJS" 2>/dev/null; }
trap cleanup EXIT INT TERM

# We must read files under $DIR (root-owned, app-owned). This script is intended
# to be invoked under `su -c`, so we are already root; but to be robust when run
# as a plain user, route every privileged read through `priv`. If we ARE root,
# `su -c` is unnecessary overhead — detect and call directly.
AM_ROOT=0
if [ "$(id -u 2>/dev/null)" = "0" ]; then AM_ROOT=1; fi
SU=""
if [ "$AM_ROOT" -eq 0 ]; then
  if command -v su >/dev/null 2>&1; then SU="su"; fi
fi

# priv "CMD STRING"  — run a read-only shell-command STRING, as root if needed.
# Every caller passes ONE string that is a complete shell command (e.g.
# '[ -d "/path" ]', 'cat "/path"', 'pm path com.x'). We always interpret it via
# a shell so the quoting/redirection inside the string is honored:
#   * already root (or no `su`): eval it in this shell.
#   * non-root with `su`: hand the same string to `su -c` (root shell parses it).
# These strings are built only from our own fixed paths/commands (no untrusted
# input), so eval/su -c is safe here.
priv() {
  if [ "$AM_ROOT" -eq 1 ] || [ -z "$SU" ]; then
    eval "$*"
  else
    su -c "$*"
  fi
}
# p_test PATH FLAG  -> echoes yes/no for `test -FLAG PATH` as root (read-only).
p_test() {
  if priv "[ -$2 \"$1\" ]" >/dev/null 2>&1; then echo yes; else echo no; fi
}
# p_cat PATH -> stdout of the file as root (read-only).
p_cat() { priv "cat \"$1\"" 2>/dev/null; }
# p_size PATH -> byte count as root, or empty.
p_size() { priv "wc -c < \"$1\"" 2>/dev/null | tr -d ' '; }

# ----------------------- generic structural JS/JSON utils --------------------
# count_in_file FILE CHAR  -> number of times CHAR occurs in FILE.
# Implemented with `tr -cd` (complement-delete: keep ONLY CHAR, drop everything
# else) piped to `wc -c`. This is the robust counting primitive: it never
# touches any byte other than CHAR, so it cannot mis-delete adjacent characters
# the way `tr -d CHAR` can on some toybox/busybox/MSYS builds (where `}` next to
# a newline over-counts). Works identically on toybox, busybox, and dash.
# Reads the file as root via p_cat. CHAR must be a single literal character.
count_in_file() {
  _cif_file=$1; _cif_ch=$2
  p_cat "$_cif_file" | tr -cd "$_cif_ch" | wc -c | tr -d ' '
}

# brace_balanced FILE  -> echoes "ok" if {} [] () counts match AND the number of
# unescaped double-quotes is even. This is a heuristic (it does not parse string
# contents), but for machine-generated config/js it reliably catches truncation,
# a dropped brace, or a botched edit. Returns non-ok with a reason otherwise.
brace_balanced() {
  _file=$1
  # emptiness / unreadability guard
  if [ "$(p_size "$_file")" = "0" ] || [ -z "$(p_cat "$_file" | head -c 1)" ]; then
    echo "empty-or-unreadable"; return
  fi
  _ob=$(count_in_file "$_file" '{'); _cb=$(count_in_file "$_file" '}')
  _op=$(count_in_file "$_file" '('); _cp=$(count_in_file "$_file" ')')
  _osb=$(count_in_file "$_file" '['); _csb=$(count_in_file "$_file" ']')
  _q=$(count_in_file "$_file" '"')
  if [ "$_ob" != "$_cb" ]; then echo "brace-mismatch {=$_ob }=$_cb"; return; fi
  if [ "$_op" != "$_cp" ]; then echo "paren-mismatch (=$_op )=$_cp"; return; fi
  if [ "$_osb" != "$_csb" ]; then echo "bracket-mismatch [=$_osb ]=$_csb"; return; fi
  if [ $((_q % 2)) -ne 0 ]; then echo "odd-quote-count $_q"; return; fi
  echo "ok"
}

# has_str FILE NEEDLE  -> 0 if NEEDLE (fixed string) appears in FILE, else 1.
# grep -F is fixed-string; works on toybox/busybox grep.
has_str() { p_cat "$1" | grep -qF -- "$2"; }

# =============================================================================
echo "########################################################################"
echo "#  on-device PoGo catcher — READ-ONLY self-test"
echo "#  $(date 2>/dev/null || echo '(no date)')    host uid=$(id -u 2>/dev/null) root=$AM_ROOT"
echo "#  gadget dir: $DIR"
echo "########################################################################"

# Quick capability probe (informational; drives which validator path we take).
# IMPORTANT: a tool is only treated as "available" if it actually RUNS a trivial
# job, not merely if it's on PATH. This guards against a half-installed / stub
# interpreter (e.g. a Windows python launcher, or a Termux python that errors on
# start) being trusted to judge JSON — which would otherwise turn an
# interpreter-startup failure into a false "JSON invalid" verdict. When a tool
# can't even run the trivial probe we leave its HAVE_* at 0 and fall back to the
# self-contained structural checks.
HAVE_NODE=0; command -v node >/dev/null 2>&1 && node -e '0' >/dev/null 2>&1 && HAVE_NODE=1
HAVE_QJS=0;  command -v qjs  >/dev/null 2>&1 && HAVE_QJS=1
HAVE_JQ=0;   command -v jq   >/dev/null 2>&1 && printf '{}' | jq -e . >/dev/null 2>&1 && HAVE_JQ=1
# Pick a working python (python3 preferred) that can actually import json.
PYBIN=""
for _cand in python3 python; do
  if command -v "$_cand" >/dev/null 2>&1 \
     && printf '{}' | "$_cand" -c 'import sys,json; json.load(sys.stdin)' >/dev/null 2>&1; then
    PYBIN="$_cand"; break
  fi
done
HAVE_PY=0; [ -n "$PYBIN" ] && HAVE_PY=1

if [ "$AM_ROOT" -eq 0 ] && [ -z "$SU" ]; then
  echo
  echo "FATAL: not root and no 'su' available — cannot read $DIR (app/root-owned)."
  echo "       Re-run as: su -c 'sh $0'"
  exit 1
fi

_i "validators present: node=$HAVE_NODE qjs=$HAVE_QJS python=$HAVE_PY jq=$HAVE_JQ"


# =============================================================================
# SECTION 1 — PATHS: everything the system depends on exists
# =============================================================================
_sec "1. PATHS & PACKAGE"

if [ "$(p_test "$DIR" d)" = yes ]; then _p "gadget dir exists: $DIR"
else _f "gadget dir MISSING: $DIR  (nothing is deployed)"; fi

if [ "$(p_test "$GADGET_SO" f)" = yes ]; then
  _gsz=$(p_size "$GADGET_SO")
  _p "gadget binary exists: libgadget.so (${_gsz:-?} bytes)"
else
  _f "libgadget.so MISSING — no Frida gadget => no in-process catcher at all"
fi

if [ "$(p_test "$CATCH_JS" f)" = yes ]; then
  _csz=$(p_size "$CATCH_JS")
  _p "catch.js exists (${_csz:-?} bytes)"
  # sanity: a real catch.js is tens of KB; a near-empty file means a bad copy.
  if [ -n "$_csz" ] && [ "$_csz" -lt 4000 ]; then
    _w "catch.js is only ${_csz} bytes — suspiciously small (truncated copy?)"
  fi
else
  _f "catch.js MISSING at $CATCH_JS — script mode has nothing to run"
fi

if [ "$(p_test "$LIVE_CFG" f)" = yes ]; then _p "live gadget config exists: libgadget.config.so"
else _f "live config MISSING: $LIVE_CFG — gadget has no config to read"; fi

if [ "$(p_test "$SCRIPT_CFG" f)" = yes ]; then _p "canonical SCRIPT config staged: config.script.so"
else _w "config.script.so NOT staged — 'switch to autonomous' has no canonical source (toggle has an embedded fallback, but staging is expected)"; fi

if [ "$(p_test "$LISTEN_CFG" f)" = yes ]; then _p "canonical LISTEN config staged: config.listen.so (restore source-of-truth)"
else _w "config.listen.so NOT staged — restore-to-desktop relies on this; stage it (DEPLOY STEP 1)"; fi

if [ "$(p_test "$TOGGLE_SH" f)" = yes ]; then _p "config-swap toggle present: pogo-catch.sh"
else _i "pogo-catch.sh not in gadget dir (OK — the marker-file home button doesn't need it; only the panic/desktop button does)"; fi

# PoGo installed?  pm path is read-only.
if priv "pm path $PKG" >/dev/null 2>&1; then
  _p "PoGo package installed: $PKG"
else
  _w "PoGo package $PKG not found via 'pm path' (modded build may register differently; verify manually)"
fi


# =============================================================================
# SECTION 2 — catch.js IS VALID JAVASCRIPT
#   Three-tier: node -c  >  qjs (eval in a sandbox)  >  structural checker.
#   The structural checker is tuned to THIS catch.js: it requires the exact
#   load-bearing constructs (so a wrong/blank file fails even if braces balance).
# =============================================================================
_sec "2. catch.js — JAVASCRIPT VALIDITY"

if [ "$(p_test "$CATCH_JS" f)" != yes ]; then
  _f "skip JS validation — catch.js missing"
else
  # We need the bytes in a Termux-writable tmp so node/qjs can read them even if
  # they run without root. Copy via root read -> user-writable temp (READ of the
  # gadget dir only; we never write the gadget dir).
  TMPJS="$TMPDIR_SELF/.selftest_catch.$$.js"
  p_cat "$CATCH_JS" > "$TMPJS" 2>/dev/null
  if [ ! -s "$TMPJS" ]; then
    _f "could not stage a readable copy of catch.js for syntax check (perm?)"
  else
    VALIDATED=0
    # ---- tier 1: node --check (true parser, best signal) --------------------
    if [ "$HAVE_NODE" -eq 1 ]; then
      if NODE_ERR=$(node --check "$TMPJS" 2>&1); then
        _p "node --check: catch.js parses as valid JS"
        VALIDATED=1
      else
        _f "node --check: catch.js has a SYNTAX ERROR:"
        printf '        %s\n' "$NODE_ERR" | head -5
        VALIDATED=1   # we got a definitive answer (negative); don't run fallback
      fi
    fi
    # ---- tier 2: qjs (the gadget's OWN engine — most faithful) --------------
    # Only if node didn't already give a verdict. We compile WITHOUT executing
    # by wrapping in a Function() so no hooks/Interceptor side effects fire.
    if [ "$VALIDATED" -eq 0 ] && [ "$HAVE_QJS" -eq 1 ]; then
      QCHK="$TMPDIR_SELF/.selftest_qjs.$$.js"
      {
        printf '%s\n' "try{"
        printf '%s\n' "  var src = std.loadFile(scriptArgs[1]);"
        printf '%s\n' "  new Function(src);"        # parse-only, never run
        printf '%s\n' "  std.out.puts('QJS_OK\\n');"
        printf '%s\n' "}catch(e){ std.err.puts('QJS_ERR '+e+'\\n'); std.exit(3); }"
      } > "$QCHK"
      if QOUT=$(qjs --std "$QCHK" "$TMPJS" 2>&1); then
        if printf '%s' "$QOUT" | grep -q QJS_OK; then
          _p "qjs (gadget engine) parses catch.js as valid JS"
          VALIDATED=1
        fi
      fi
      rm -f "$QCHK" 2>/dev/null
      if [ "$VALIDATED" -eq 0 ]; then
        _w "qjs present but parse-probe inconclusive ($(printf '%s' "$QOUT" | head -1)); using structural check"
      fi
    fi
    # ---- tier 3: structural checker (no JS engine needed) -------------------
    if [ "$VALIDATED" -eq 0 ]; then
      _i "no JS engine available — using self-contained structural validation"
      BR=$(brace_balanced "$CATCH_JS")
      if [ "$BR" = ok ]; then
        _p "structure: braces/parens/brackets balanced, quotes even"
      else
        _f "structure: catch.js looks malformed ($BR) — likely truncated/corrupt"
      fi
      # Presence of the exact load-bearing constructs that MUST be in this file.
      # (If a blank/placeholder file slipped in, braces could still 'balance' but
      #  these will be absent.)  Strings chosen from the real catch.js.
      _need_ok=1
      check_need() {  # $1 = human label, $2 = fixed needle
        if has_str "$CATCH_JS" "$2"; then _p "contains $1"
        else _f "MISSING $1  (expected literal: $2)"; _need_ok=0; fi
      }
      check_need "rpc.exports.init entrypoint"      "rpc.exports"
      check_need "self-start init() handler"        "init: function"
      check_need "LateUpdate per-frame pump hook"   "CameraFollowingGround"
      check_need "encounter opener"                 "SendEncounterRequest"
      check_need "throw via TryCapture"             "TryCapture"
      check_need "IL2CPP export binding"            "il2cpp_domain_get"
      check_need "liveness singleton finder"        "il2cpp_unity_liveness_allocate_struct"
      check_need "GC stop-world guard"              "il2cpp_stop_gc_world"
      check_need "toggle marker path"               "catch.on"
      check_need "timer-free bootstrap (clock_gettime)" "clock_gettime"
      if [ "$_need_ok" -eq 1 ]; then
        _i "all load-bearing constructs present (structural validity high-confidence)"
      fi
    fi
  fi
fi


# =============================================================================
# SECTION 3 — catch.js INTERNAL CONSISTENCY with the deployed paths/config
#   (engine-independent; pure text assertions. Catches the classic mismatch
#    bugs: catch.js hard-coding a different dir than the gadget config points to,
#    or the legendary list / rate constants getting clobbered by a bad edit.)
# =============================================================================
_sec "3. catch.js — INTERNAL CONSISTENCY"

if [ "$(p_test "$CATCH_JS" f)" = yes ]; then
  # 3a. The toggle/log paths catch.js POLLS must equal the deploy dir.
  if has_str "$CATCH_JS" "$MARKER"; then
    _p "catch.js polls the correct marker path ($MARKER)"
  else
    _f "catch.js does NOT reference $MARKER — its TOGGLE_FILE differs from the home button's target (toggle will never take effect)"
  fi
  # 3b. The legendary skip-list must still be present and plausibly long.
  if has_str "$CATCH_JS" "LEGENDARY_DEX"; then
    # count comma-separated entries on the LEGENDARY_DEX line, best-effort.
    LL=$(p_cat "$CATCH_JS" | grep -F "LEGENDARY_DEX" | head -1 | tr -cd ',' | wc -c | tr -d ' ')
    if [ -n "$LL" ] && [ "$LL" -ge 80 ]; then
      _p "legendary skip-list present (~$((LL+1)) dex entries) — legendaries will be skipped"
    else
      _w "LEGENDARY_DEX present but short (~$((LL+1)) entries) — verify legendaries are still excluded"
    fi
  else
    _f "LEGENDARY_DEX list MISSING — catch.js would auto-throw at legendaries (DO NOT run ON until fixed)"
  fi
  # 3c. Catch-quality constants (reticle Excellent band + rate) intact.
  if has_str "$CATCH_JS" "0.02"; then
    _p "Excellent-reticle throw constant (0.02..0.12 band) present"
  else
    _w "reticle constant 0.02 not found — catch quality may differ from spec"
  fi
  if has_str "$CATCH_JS" "RATE_PER_MIN"; then _p "rate config (RATE_PER_MIN) present"
  else _w "RATE_PER_MIN not found — open-rate pacing may be wrong"; fi
  # 3d. Hot-reload safety: dispose() must detach hooks (else double-pump on edit).
  if has_str "$CATCH_JS" "detachAll"; then _p "dispose() detaches hooks (hot-reload safe)"
  else _w "no Interceptor.detachAll found — a catch.js hot-edit could double-attach the pump"; fi
else
  _i "skip (catch.js missing)"
fi


# =============================================================================
# SECTION 4 — GADGET CONFIG JSON: parses AND correct shape
#   Validates all three configs that exist. Preferred: python3/jq (true JSON
#   parse). Fallback: brace/quote balance + required key/value substrings.
# =============================================================================
_sec "4. GADGET CONFIG JSON"

# json_parse_ok FILE  -> 0 if the file is valid JSON (python/jq), 2 if no parser
# (caller then uses the structural fallback). Reads file as root.
json_parse_ok() {
  _jf=$1
  if [ "$HAVE_PY" -eq 1 ]; then
    p_cat "$_jf" | "$PYBIN" -c 'import sys,json; json.load(sys.stdin)' >/dev/null 2>&1
    return $?
  fi
  if [ "$HAVE_JQ" -eq 1 ]; then
    p_cat "$_jf" | jq -e . >/dev/null 2>&1
    return $?
  fi
  return 2
}

# validate_cfg LABEL FILE  MUST_TYPE  [extra fixed-string needles...]
#   - confirms the file parses (or structurally balances)
#   - confirms it declares the expected interaction.type
#   - confirms each extra needle is present (e.g. the catch.js path, port).
validate_cfg() {
  _lbl=$1; _file=$2; _type=$3; shift 3
  if [ "$(p_test "$_file" f)" != yes ]; then
    _i "$_lbl: not present (skipped)"; return
  fi
  json_parse_ok "$_file"; _rc=$?
  case "$_rc" in
    0) _p "$_lbl: valid JSON (parser-verified)";;
    2)
       BR=$(brace_balanced "$_file")
       if [ "$BR" = ok ]; then _p "$_lbl: structurally balanced (no JSON parser available)"
       else _f "$_lbl: malformed JSON ($BR)"; return; fi
       ;;
    *) _f "$_lbl: JSON does NOT parse (parser rejected it)"; return;;
  esac
  # type check (substring is sufficient and parser-independent)
  if has_str "$_file" "\"type\":\"$_type\"" || has_str "$_file" "\"type\": \"$_type\""; then
    _p "$_lbl: interaction.type == \"$_type\" (correct)"
  else
    _f "$_lbl: interaction.type is NOT \"$_type\" — wrong mode for this config"
  fi
  for _need in "$@"; do
    if has_str "$_file" "$_need"; then _p "$_lbl: contains required '$_need'"
    else _f "$_lbl: MISSING required '$_need'"; fi
  done
}

validate_cfg "config.script.so" "$SCRIPT_CFG" "script" \
  "/data/local/tmp/re.zyg.fri/catch.js" '"runtime":"qjs"'
# NB: runtime may be spaced ("runtime": "qjs"); accept both forms.
if [ "$(p_test "$SCRIPT_CFG" f)" = yes ] \
   && ! has_str "$SCRIPT_CFG" '"runtime":"qjs"' \
   && has_str "$SCRIPT_CFG" '"runtime": "qjs"'; then
  _p "config.script.so: runtime qjs (spaced form) present"
fi

validate_cfg "config.listen.so" "$LISTEN_CFG" "listen" \
  '27047' '127.0.0.1'

# The LIVE config can be EITHER mode; validate whichever it currently is.
if [ "$(p_test "$LIVE_CFG" f)" = yes ]; then
  json_parse_ok "$LIVE_CFG"; LRC=$?
  case "$LRC" in
    0) _p "libgadget.config.so (live): valid JSON";;
    2) BRL=$(brace_balanced "$LIVE_CFG")
       if [ "$BRL" = ok ]; then _p "libgadget.config.so (live): structurally balanced"
       else _f "libgadget.config.so (live): malformed ($BRL)"; fi ;;
    *) _f "libgadget.config.so (live): JSON does NOT parse";;
  esac
fi


# =============================================================================
# SECTION 5 — WOULD PoGo LOAD SCRIPT MODE RIGHT NOW?
#   This is the headline question. Derive the live mode from the live config
#   (exactly as pogo-catch.sh current_state() does), then gate on:
#     (a) live type == script
#     (b) the script path it names actually exists
#     (c) the gadget binary is a Frida version that EXECUTES script mode
#     (d) report the ON/OFF marker (catching armed vs idle) and heartbeat.
# =============================================================================
_sec "5. WOULD PoGo LOAD SCRIPT MODE?  (the headline)"

LIVE_MODE=UNKNOWN
LIVE_TXT=""
if [ "$(p_test "$LIVE_CFG" f)" = yes ]; then
  LIVE_TXT=$(p_cat "$LIVE_CFG")
  # mirror pogo-catch.sh: grep for "type"...: ..."script"/"listen" (spacing-tolerant)
  if printf '%s' "$LIVE_TXT" | grep -Eq '"type"[[:space:]]*:[[:space:]]*"script"'; then LIVE_MODE=SCRIPT
  elif printf '%s' "$LIVE_TXT" | grep -Eq '"type"[[:space:]]*:[[:space:]]*"listen"'; then LIVE_MODE=LISTEN
  fi
fi
_i "live config mode (derived): $LIVE_MODE"

WOULD_LOAD=1   # assume yes; knock down on any blocker
if [ "$LIVE_MODE" = SCRIPT ]; then
  _p "live gadget mode is SCRIPT — PoGo would auto-run a script on next launch"
  # which script path does the live config name? extract the path value.
  LIVE_PATH=$(printf '%s' "$LIVE_TXT" | grep -Eo '"path"[[:space:]]*:[[:space:]]*"[^"]+"' | head -1 | sed -E 's/.*"path"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/')
  if [ -z "$LIVE_PATH" ]; then
    _f "live SCRIPT config has no \"path\" — gadget has nothing to load"; WOULD_LOAD=0
  else
    _i "live config script path: $LIVE_PATH"
    if [ "$LIVE_PATH" != "$CATCH_JS" ]; then
      _w "live config points at $LIVE_PATH (not the expected $CATCH_JS) — make sure that's the intended script"
    fi
    if [ "$(p_test "$LIVE_PATH" f)" = yes ]; then
      _p "the named script exists on disk ($LIVE_PATH)"
    else
      _f "the named script DOES NOT EXIST ($LIVE_PATH) — gadget would fail to load it"; WOULD_LOAD=0
    fi
  fi
elif [ "$LIVE_MODE" = LISTEN ]; then
  _w "live gadget mode is LISTEN (:27047) — PoGo would NOT auto-run catch.js; it waits for a desktop Frida to attach. To go autonomous: cp config.script.so libgadget.config.so + relaunch (DEPLOY STEP 2)."
  WOULD_LOAD=0
else
  _f "live gadget mode is UNKNOWN (live config is neither script nor listen) — fix libgadget.config.so before launching"
  WOULD_LOAD=0
fi

# ---- (c) Frida gadget VERSION gate: 16.x runs script mode, 17.x does not -----
# The gadget .so is renamed, so the version isn't in the filename — dig it out of
# the binary's embedded version strings (same technique as pogo-catch.sh).
GV=""
if [ "$(p_test "$GADGET_SO" f)" = yes ]; then
  if command -v strings >/dev/null 2>&1; then
    GV=$(priv "strings \"$GADGET_SO\"" 2>/dev/null | grep -Eo '[0-9]+\.[0-9]+\.[0-9]+' | sort -uV | tail -n1)
  else
    # toybox may lack `strings`; fall back to grep -a over the binary for an
    # x.y.z token near a 'frida' marker. Best-effort.
    GV=$(priv "grep -ao '[0-9][0-9]*\\.[0-9][0-9]*\\.[0-9][0-9]*' \"$GADGET_SO\"" 2>/dev/null | sort -uV | tail -n1)
  fi
fi
if [ -n "$GV" ]; then
  _i "gadget version (best-effort from binary strings): $GV"
  GMAJ=${GV%%.*}
  case "$GMAJ" in
    16) _p "gadget major is 16 — gadget SCRIPT mode is known to EXECUTE (good)";;
    1[789]|2[0-9])
        _w "gadget major is $GMAJ (Frida 17+). Frida 17.x parses but does NOT execute gadget script mode on Android (frida #3526/#3558/#3616/#3645) — catch.js may load silently and never run. If catch.log/catch.hb stay empty after an ON launch, swap libgadget.so for a 16.7.19 arm64 gadget (see gadget16/ + DEPLOY recovery). SMOKE-TEST script execution before trusting the catcher."
        ;;
    *)  _w "gadget major is $GMAJ — unverified for script-mode execution; smoke-test first";;
  esac
else
  _w "could not read a version from libgadget.so — cannot confirm it executes script mode. SMOKE-TEST (a 3-line logging script) before trusting the catcher."
fi

# ---- (d) ON/OFF marker + heartbeat (catching armed? recently alive?) --------
if [ "$(p_test "$MARKER" f)" = yes ]; then
  _i "toggle marker PRESENT ($MARKER) => catching would be ARMED (ON) once the script is running"
else
  _i "toggle marker ABSENT => catching is OFF/idle (safe default; tap the home button or 'touch catch.on' to arm)"
fi
if [ "$(p_test "$HBF" f)" = yes ]; then
  HBTXT=$(p_cat "$HBF" | head -1)
  HBTS=$(printf '%s' "$HBTXT" | cut -d'|' -f1 | tr -cd '0-9')
  NOWS=$(date +%s 2>/dev/null)
  if [ -n "$HBTS" ] && [ -n "$NOWS" ] && [ "$NOWS" -ge "$HBTS" ] 2>/dev/null; then
    AGE=$((NOWS - HBTS))
    if [ "$AGE" -le 120 ]; then
      _p "heartbeat fresh (${AGE}s old) — the in-process catcher IS running right now: $HBTXT"
    else
      _i "heartbeat is stale (${AGE}s old) — catcher not currently pumping (PoGo closed, or wedged). Last: $HBTXT"
    fi
  else
    _i "heartbeat file present but unparseable timestamp: $HBTXT"
  fi
else
  _i "no heartbeat file yet (catch.hb) — expected until catch.js has run at least once in script mode"
fi

# Is PoGo even running? (read-only pidof)
PPID_=$(priv "pidof $PKG" 2>/dev/null | tr -d ' ')
if [ -n "$PPID_" ]; then _i "PoGo is running (pid $PPID_)"
else _i "PoGo is not currently running (start it to load the gadget config)"; fi


# =============================================================================
# FINAL SUMMARY + EXIT
# =============================================================================
_sec "SUMMARY"
echo "  checks: $NPASS passed, $NWARN warnings, $NFAIL failed"

# Headline verdict on autonomy readiness.
if [ "$NFAIL" -eq 0 ]; then
  if [ "$WOULD_LOAD" -eq 1 ]; then
    echo "  VERDICT: READY — files valid; live config is SCRIPT mode pointing at an existing catch.js."
    if [ -n "$GV" ] && { [ "${GV%%.*}" -ge 17 ] 2>/dev/null; }; then
      echo "           CAVEAT: gadget is Frida ${GV} (17+). SMOKE-TEST that script mode executes; be ready to swap in a 16.x gadget."
    fi
    if [ "$(p_test "$MARKER" f)" = yes ]; then
      echo "           Marker is ON — catching would be active on the next pump."
    else
      echo "           Marker is OFF — tap the home button (or 'touch catch.on') to start catching."
    fi
  else
    echo "  VERDICT: STAGED OK but NOT autonomous right now — live gadget mode is $LIVE_MODE."
    echo "           To go autonomous: cp config.script.so -> libgadget.config.so, force-stop + relaunch PoGo (DEPLOY STEP 2)."
  fi
else
  echo "  VERDICT: NOT READY — $NFAIL critical check(s) failed. Fix these before launching ON:"
fi

# Replay the WARN/FAIL headlines collected along the way.
if [ -n "$SUMMARY" ]; then
  echo "  ----------------------------------------------------------------"
  printf '%s\n' "$SUMMARY" | sed '/^$/d'
fi

echo
echo "  (read-only test — nothing on the device was modified)"

# Exit non-zero ONLY on hard failures, so this can gate an installer/CI step.
[ "$NFAIL" -eq 0 ] && exit 0 || exit 1

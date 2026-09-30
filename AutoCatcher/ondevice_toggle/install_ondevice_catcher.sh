#!/data/data/com.termux/files/usr/bin/bash
# =============================================================================
#  install_ondevice_catcher.sh
#  ONE-SHOT, fully on-device installer for the autonomous PoGo auto-catcher.
#  Run ONCE inside Termux. Needs root (su). NO desktop / ADB / Tailscale / PC.
#
#  What it does (all on the phone):
#    1. Writes /data/local/tmp/re.zyg.fri/catch.js          (the self-contained catcher)
#    2. Switches the ZygiskFrida gadget into SCRIPT MODE     (backs up the old config)
#       by writing /data/local/tmp/re.zyg.fri/libgadget.config.so
#    3. Ensures the gadget targets com.nianticlabs.pokemongo (config.json)
#    4. Installs the home-screen toggle scripts to ~/.shortcuts/
#    5. Sets all file permissions so the PoGo (app-uid) process can read them
#       and so Termux:Widget will show the shortcuts.
#    6. Leaves catching OFF (marker absent) — you turn it on from the home button.
#
#  AFTER running this you must (one time): force-stop & relaunch PoGo so the
#  gadget re-reads the new script-mode config. Then tap the home-screen toggle.
#
#  HOW TO GET THIS SCRIPT ONTO THE PHONE (no PC):
#    Option A (paste): in Termux run:  nano ~/install_ondevice_catcher.sh
#      paste this whole file, save (Ctrl-O, Enter), exit (Ctrl-X), then:
#         bash ~/install_ondevice_catcher.sh
#    Option B (curl, if you host it):  curl -L <url> -o ~/inst.sh && bash ~/inst.sh
#    Option C (share): save to Termux storage via the Android share sheet, then
#      bash /storage/emulated/0/Download/install_ondevice_catcher.sh
# =============================================================================
set -eu

DIR=/data/local/tmp/re.zyg.fri
JS=$DIR/catch.js
GCFG=$DIR/libgadget.config.so
ZCFG=$DIR/config.json
MARK=$DIR/catch.on
PKG=com.nianticlabs.pokemongo
SH=${HOME}/.shortcuts

say(){ printf '\033[1;36m[install]\033[0m %s\n' "$*"; }
die(){ printf '\033[1;31m[install] ERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# ---- 0. sanity: root + gadget dir present ----------------------------------
command -v su >/dev/null 2>&1 || die "su not found — root (Magisk) required."
su -c "id" >/dev/null 2>&1 || die "root denied — grant Termux su in Magisk, then re-run."
su -c "[ -d $DIR ]" || die "$DIR missing — is ZygiskFrida installed? Expected the gadget dir."
su -c "[ -f $DIR/libgadget.so ]" || die "$DIR/libgadget.so missing — gadget not present."
say "root OK, gadget dir present."

# ---- 1. write catch.js to a Termux temp, then move into place as root -------
TMPJS="$(mktemp "${TMPDIR:-/data/data/com.termux/files/usr/tmp}/catch.XXXXXX.js")"
say "writing catch.js (self-contained catcher) ..."
cat > "$TMPJS" <<'CATCH_JS_EOF'
__CATCH_JS_PLACEHOLDER__
CATCH_JS_EOF
# Guard against an empty/un-inlined paste: the real catch.js defines this marker
# function name; if it's absent, the body wasn't embedded.
if ! grep -q 'function livenessFind' "$TMPJS"; then
  die "catch.js body was not embedded. Use install_ondevice_catcher.FULL.sh (catch.js inlined), not the template."
fi
su -c "cp '$TMPJS' '$JS' && chmod 644 '$JS'"
rm -f "$TMPJS"
say "catch.js installed -> $JS"

# ---- 2. back up current gadget config, write SCRIPT-MODE config ------------
say "switching gadget to SCRIPT mode (backing up current config) ..."
su -c "[ -f '$GCFG' ] && cp -n '$GCFG' '$GCFG.listen.bak' || true"
TMPG="$(mktemp "${TMPDIR:-/data/data/com.termux/files/usr/tmp}/gcfg.XXXXXX")"
cat > "$TMPG" <<'GADGET_CFG_EOF'
{
  "interaction": {
    "type": "script",
    "path": "/data/local/tmp/re.zyg.fri/catch.js",
    "on_change": "reload"
  },
  "runtime": "qjs"
}
GADGET_CFG_EOF
# NOTE: runtime is "qjs". The gadget ships ONLY QuickJS by default; forcing "v8"
# can fail to load the script (V8 disabled in the gadget). catch.js is qjs-clean.
# "on_load" is omitted: it is a LISTEN-interaction key, not a SCRIPT key, and the
# ZygiskFrida config.json start_up_delay_ms already biases load to after app start.
su -c "cp '$TMPG' '$GCFG' && chmod 644 '$GCFG'"
rm -f "$TMPG"
say "gadget script-mode config installed -> $GCFG"
say "  (old listen-mode config saved as $GCFG.listen.bak)"

# ---- 3. ensure ZygiskFrida config.json targets PoGo ------------------------
# If config.json is missing, seed it from the example and point it at PoGo.
# If present, verify it mentions the PoGo package; warn (don't clobber) if not.
if su -c "[ -f '$ZCFG' ]"; then
  if su -c "grep -q '$PKG' '$ZCFG'"; then
    say "config.json already targets $PKG."
  else
    say "WARNING: $ZCFG exists but does not mention $PKG."
    say "         Edit it so a target app_name = $PKG with injected_libraries -> $DIR/libgadget.so"
  fi
else
  if su -c "[ -f '$ZCFG.example' ]"; then
    say "seeding config.json from example, targeting $PKG ..."
    su -c "cp '$ZCFG.example' '$ZCFG' && sed -i 's/com.example.package/$PKG/' '$ZCFG' && chmod 644 '$ZCFG'"
  else
    say "writing a minimal config.json targeting $PKG ..."
    TMPZ="$(mktemp "${TMPDIR:-/data/data/com.termux/files/usr/tmp}/zcfg.XXXXXX")"
    cat > "$TMPZ" <<ZCFG_EOF
{
  "targets": [
    {
      "app_name": "$PKG",
      "enabled": true,
      "start_up_delay_ms": 0,
      "injected_libraries": [
        { "path": "$DIR/libgadget.so" }
      ]
    }
  ]
}
ZCFG_EOF
    su -c "cp '$TMPZ' '$ZCFG' && chmod 644 '$ZCFG'"
    rm -f "$TMPZ"
  fi
fi

# ---- 4. permissions on the whole gadget dir (so the app-uid can read) ------
# ZygiskFrida fixes perms on (re)install, but we set sane perms now so the
# gadget + script + (later) marker are world-readable to the PoGo process.
su -c "chmod 644 '$JS' '$GCFG' 2>/dev/null; chmod 755 '$DIR'; chmod 644 '$DIR/libgadget.so' 2>/dev/null; true"
# SELinux: /data/local/tmp is typically labelled so app domains can read it
# (the existing listen-mode setup already worked from here). If the gadget
# can't read catch.js, see TROUBLESHOOTING in the README (restorecon / reinstall).
say "permissions set on $DIR."

# ---- 5. install home-screen toggle scripts into ~/.shortcuts ---------------
say "installing toggle shortcuts to $SH ..."
mkdir -p "$SH"
chmod 700 "$SH"

write_shortcut(){ # $1 = name, then stdin = body
  local name="$1"; local path="$SH/$name"
  cat > "$path"
  chmod 700 "$path"
  say "  shortcut: $path"
}

write_shortcut pogo-catch-toggle <<'SC_TOGGLE_EOF'
#!/data/data/com.termux/files/usr/bin/sh
# Home-screen ON/OFF button. Flips the marker catch.js polls (~1s latency).
MARK=/data/local/tmp/re.zyg.fri/catch.on
if su -c "[ -f $MARK ]"; then
  su -c "rm -f $MARK"; STATE="OFF"
else
  su -c "touch $MARK && chmod 666 $MARK"; STATE="ON"
fi
echo "PoGo auto-catch: $STATE"
command -v termux-toast >/dev/null 2>&1 && termux-toast -g middle "PoGo auto-catch: $STATE"
SC_TOGGLE_EOF

write_shortcut pogo-catch-on <<'SC_ON_EOF'
#!/data/data/com.termux/files/usr/bin/sh
MARK=/data/local/tmp/re.zyg.fri/catch.on
su -c "touch $MARK && chmod 666 $MARK"
echo "PoGo auto-catch: ON"
command -v termux-toast >/dev/null 2>&1 && termux-toast -g middle "PoGo auto-catch: ON"
SC_ON_EOF

write_shortcut pogo-catch-off <<'SC_OFF_EOF'
#!/data/data/com.termux/files/usr/bin/sh
MARK=/data/local/tmp/re.zyg.fri/catch.on
su -c "rm -f $MARK"
echo "PoGo auto-catch: OFF"
command -v termux-toast >/dev/null 2>&1 && termux-toast -g middle "PoGo auto-catch: OFF"
SC_OFF_EOF

write_shortcut pogo-catch-status <<'SC_STATUS_EOF'
#!/data/data/com.termux/files/usr/bin/sh
MARK=/data/local/tmp/re.zyg.fri/catch.on
LOG=/data/local/tmp/re.zyg.fri/catch.log
if su -c "[ -f $MARK ]"; then echo "PoGo auto-catch: ON"; else echo "PoGo auto-catch: OFF"; fi
echo "---- last 25 log lines ----"
su -c "[ -f $LOG ] && tail -n 25 $LOG || echo '(no log yet — launch PoGo at least once)'"
SC_STATUS_EOF

# ---- 6. leave catching OFF (remove any stale marker) -----------------------
su -c "rm -f '$MARK'"
say "catching left OFF (no marker). Turn it on from the home-screen button."

cat <<'DONE_EOF'

============================================================================
 DONE. Final steps (one time):
   1) Add the home-screen button:
        - Long-press home screen -> Widgets -> Termux:Widget -> drag out
        - Pick the 'pogo-catch-toggle' script
        (Termux:Widget must be installed. If not: install from F-Droid, then
         in Termux run: am start -n com.termux.widget/.TermuxWidgetActivity ;
         or just re-open the Widgets tray.)
   2) Restart PoGo so the gadget loads script mode:
        su -c 'am force-stop com.nianticlabs.pokemongo'
        monkey -p com.nianticlabs.pokemongo -c android.intent.category.LAUNCHER 1
   3) Once PoGo is on the map, tap the toggle (or run ~/.shortcuts/pogo-catch-on).
   4) Watch it work (on-device): ~/.shortcuts/pogo-catch-status
        or: su -c 'tail -f /data/local/tmp/re.zyg.fri/catch.log'
        or: logcat -s frida-catch

 TO REVERT to the desktop/listen workflow:
        su -c 'cp /data/local/tmp/re.zyg.fri/libgadget.config.so.listen.bak \
                  /data/local/tmp/re.zyg.fri/libgadget.config.so'
        then restart PoGo.
============================================================================
DONE_EOF

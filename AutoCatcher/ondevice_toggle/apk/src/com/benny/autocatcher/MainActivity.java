package com.benny.autocatcher;

import android.app.Activity;
import android.os.Bundle;
import android.os.Handler;
import android.view.Gravity;
import android.view.View;
import android.widget.CompoundButton;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Switch;
import android.widget.TextView;
import android.graphics.Color;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.util.ArrayList;

/**
 * PoGo Auto -- the on-phone control page.
 *
 * Every feature is one FeatureRow: a title, a plain-English line saying what it actually does, a
 * switch, and a live status line. Adding the next emulated feature is a single addFeature(...) call
 * rather than another hand-built block, which is why this replaced the old fixed two-switch layout.
 *
 * TWO HARD CONSTRAINTS, both learned the expensive way:
 *  1. This app's SELinux domain cannot use a shell. Toybox binaries (ls/tail/test) and shell
 *     operators return EMPTY, and Termux's home is 0700 to us. So all state is read with plain Java
 *     File I/O from world-readable files in /data/local/tmp, never by shelling out.
 *  2. The app cannot CREATE files in /data/local/tmp (owner=shell). Every flag file must already
 *     exist, root-created and chmod 666. Writes go through catcher_ctl.sh via the Termux
 *     RunCommandService intent, which owns the flags and keeps the host process alive while ANY
 *     feature is on.
 * A toggle is never trusted after firing: applyToggle verifies the flag actually changed and
 * retries, because a held lock in catcher_ctl.sh once swallowed taps and left switches showing ON
 * while the backend stayed OFF.
 */
public class MainActivity extends Activity {

    static final String HOME = "/data/data/com.termux/files/home/pogo";
    static final String CTL  = HOME + "/catcher_ctl.sh";

    static final String CATCHFLAG   = "/data/local/tmp/pogo_catch.on";
    static final String SPINFLAG    = "/data/local/tmp/pogo_spin.on";
    static final String PERFECTFLAG = "/data/local/tmp/pogo_perfect.on";
    static final String TAPFLAG     = "/data/local/tmp/pogo_tap.on";
    static final String STATE       = "/data/local/tmp/pogo_state.txt";
    static final String STATUS_REWARD = "/data/local/tmp/pogo_rewards.txt";
    // Transfer-on-Catch config. A JSON file rather than a flag because it holds several
    // values; the catcher re-reads it every report, so edits take effect live with no
    // restart. Root pre-creates it 666 -- this app can WRITE an existing world-writable
    // file but cannot CREATE one in /data/local/tmp.
    static final String TOCFILE     = "/data/local/tmp/pogo_toc.json";

    /** One toggleable feature: switch + status line + the control verbs that back it. */
    private class FeatureRow {
        Switch sw;
        TextView status;
        String flag, onVerb, offVerb, onText;
        CompoundButton.OnCheckedChangeListener listener;
    }

    private ArrayList<FeatureRow> rows = new ArrayList<FeatureRow>();
    private android.widget.Button rewardBtn;
    private TextView stats, rewardStatus;
    private Handler handler = new Handler();
    private Runnable ticker;

    static String intent(String arg) {
        return "am startservice --user 0 -n com.termux/com.termux.app.RunCommandService "
             + "-a com.termux.RUN_COMMAND "
             + "--es com.termux.RUN_COMMAND_PATH " + CTL + " "
             + "--esa com.termux.RUN_COMMAND_ARGUMENTS " + arg + " "
             + "--ez com.termux.RUN_COMMAND_BACKGROUND true";
    }

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);

        ScrollView scroller = new ScrollView(this);
        scroller.setBackgroundColor(Color.parseColor("#0e1116"));
        scroller.setFillViewport(true);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(18), dp(24), dp(18), dp(36));

        TextView title = new TextView(this);
        title.setText("PoGo Auto");
        title.setTextColor(Color.parseColor("#ffcb05"));
        title.setTextSize(30);
        root.addView(title);

        TextView sub = new TextView(this);
        sub.setText("Toggles apply immediately - no restart needed.");
        sub.setTextColor(Color.parseColor("#6b7a8d"));
        sub.setTextSize(13);
        sub.setPadding(0, dp(2), 0, 0);
        root.addView(sub);

        root.addView(section("CATCHING"));
        addFeature(root, "Auto-Catch",
                "Throws at Pokemon in range on its own.",
                CATCHFLAG, "catch-on", "catch-off", "catching nearby Pokemon");
        addFeature(root, "Perfect Throw",
                "Every throw scores Excellent + curveball - including the ones you throw by hand.",
                PERFECTFLAG, "perfect-on", "perfect-off", "Excellent + curve on every throw");

        addFeature(root, "Tap to Move",
                "Tap a spot on the map to move there, so you can reach things that are out of range.",
                TAPFLAG, "tap-on", "tap-off", "tap the map to move");

        root.addView(section("TRANSFER ON CATCH"));
        root.addView(desc("Tags junk the moment you catch it, so less piles up for the cull. "
                + "Copied from Pokemod: keeps anything at or above your IV threshold, plus "
                + "shiny, shadow, lucky, legendary, costume, location-card, XXL and "
                + "special-ball catches. It only TAGS - it never releases anything."));
        tocSwitchRow(root);
        tocIvRow(root);
        tocDryRow(root);

        root.addView(section("POKESTOPS"));
        addFeature(root, "Auto-Spin",
                "Spins stops as you pass them. Skips ones already spun or cooling down.",
                SPINFLAG, "spin-on", "spin-off", "spinning stops in range");

        root.addView(section("ONE-OFF ACTIONS"));
        TextView rewardDesc = desc("Clears stacked Field Research reward encounters that piled up "
                + "while your box was full.");
        root.addView(rewardDesc);
        rewardBtn = new android.widget.Button(this);
        rewardBtn.setText("CATCH REWARDS NOW");
        rewardBtn.setTextSize(15);
        LinearLayout.LayoutParams blp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        blp.setMargins(0, dp(10), 0, dp(4));
        root.addView(rewardBtn, blp);
        rewardStatus = statusView();
        root.addView(rewardStatus);
        rewardBtn.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                rewardBtn.setEnabled(false);
                rewardStatus.setText("running...");
                rewardStatus.setTextColor(Color.parseColor("#e3b341"));
                new Thread(new Runnable() {
                    public void run() {
                        shell(intent("rewards"));
                        try { Thread.sleep(4000); } catch (Exception e) { }
                        final String s = readFile(STATUS_REWARD);
                        runOnUiThread(new Runnable() {
                            public void run() {
                                showReward(s);
                                rewardBtn.setEnabled(true);
                            }
                        });
                    }
                }).start();
            }
        });

        root.addView(section("LIVE STATUS"));
        stats = new TextView(this);
        stats.setTextColor(Color.parseColor("#9aa7b8"));
        stats.setTextSize(15);
        stats.setText("waiting for catcher...");
        root.addView(stats);

        scroller.addView(root);
        setContentView(scroller);

        ticker = new Runnable() {
            public void run() {
                refresh();
                handler.postDelayed(this, 4000);   // keep the UI honest with reality
            }
        };
    }

    /** Build one feature block and register it for refresh. */
    private void addFeature(LinearLayout parent, String name, String description,
                            String flag, String onVerb, String offVerb, String onText) {
        final FeatureRow r = new FeatureRow();
        r.flag = flag; r.onVerb = onVerb; r.offVerb = offVerb; r.onText = onText;

        LinearLayout head = new LinearLayout(this);
        head.setOrientation(LinearLayout.HORIZONTAL);
        head.setGravity(Gravity.CENTER_VERTICAL);

        TextView t = new TextView(this);
        t.setText(name);
        t.setTextColor(Color.parseColor("#e6edf3"));
        t.setTextSize(19);
        LinearLayout.LayoutParams tlp = new LinearLayout.LayoutParams(
                0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f);
        head.addView(t, tlp);

        r.sw = new Switch(this);
        r.sw.setScaleX(1.25f);
        r.sw.setScaleY(1.25f);
        head.addView(r.sw);

        LinearLayout.LayoutParams hlp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        hlp.setMargins(0, dp(18), 0, 0);
        parent.addView(head, hlp);

        parent.addView(desc(description));
        r.status = statusView();
        parent.addView(r.status);

        r.listener = new CompoundButton.OnCheckedChangeListener() {
            public void onCheckedChanged(CompoundButton bv, boolean on) {
                applyToggle(r.flag, on ? r.onVerb : r.offVerb, on);
                setStatus(r, on);
            }
        };
        r.sw.setOnCheckedChangeListener(r.listener);
        rows.add(r);
    }


    // ---- Transfer-on-Catch settings -------------------------------------------------------
    private TextView tocState, tocIvLabel;
    private Switch tocSw, tocDrySw;

    private String tocRead() {
        String s = readFile(TOCFILE);
        return s.length() == 0 ? "\"enabled\":0}" : s;
    }

    /** Minimal int scrape - avoids pulling in a JSON parser for three fields. */
    private int tocGetInt(String key, int dflt) {
        try {
            String s = tocRead();
            int i = s.indexOf("\"" + key + "\"");
            if (i < 0) return dflt;
            int c = s.indexOf(':', i);
            int e = c + 1;
            while (e < s.length() && "-0123456789".indexOf(s.charAt(e)) >= 0) e++;
            return Integer.parseInt(s.substring(c + 1, e).trim());
        } catch (Exception ex) { return dflt; }
    }

    /** Rewrite the whole file. Fields not exposed in the UI keep sane defaults. */
    private void tocWrite(int enabled, int dry, int minIv) {
        String json = "{" + q("enabled") + ":" + enabled
                + "," + q("dry") + ":" + dry
                + "," + q("minIvPercent") + ":" + minIv
                + "," + q("transferShiny") + ":0"
                + "," + q("transferShadow") + ":0"
                + "," + q("transferBG") + ":0"
                + "," + q("xxlKeep") + ":[5]"
                + "," + q("ignoreSpecies") + ":[]}";
        try {
            java.io.FileWriter w = new java.io.FileWriter(TOCFILE, false);
            w.write(json); w.close();
        } catch (Exception e) {
            android.util.Log.e("AutoCatcher", "toc write failed: " + e);
        }
        refreshToc();
    }

    private String q(String k) { return "\"" + k + "\""; }

    private void tocSwitchRow(LinearLayout parent) {
        LinearLayout head = new LinearLayout(this);
        head.setOrientation(LinearLayout.HORIZONTAL);
        head.setGravity(Gravity.CENTER_VERTICAL);
        TextView t = new TextView(this);
        t.setText("Transfer on Catch");
        t.setTextColor(Color.parseColor("#e6edf3"));
        t.setTextSize(19);
        head.addView(t, new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f));
        tocSw = new Switch(this);
        tocSw.setScaleX(1.25f); tocSw.setScaleY(1.25f);
        head.addView(tocSw);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        lp.setMargins(0, dp(18), 0, 0);
        parent.addView(head, lp);
        tocState = statusView();
        parent.addView(tocState);
        tocSw.setOnCheckedChangeListener(new CompoundButton.OnCheckedChangeListener() {
            public void onCheckedChanged(CompoundButton b, boolean on) {
                tocWrite(on ? 1 : 0, tocGetInt("dry", 1), tocGetInt("minIvPercent", 80));
            }
        });
    }

    /** IV threshold: anything at or ABOVE this is KEPT. Pokemod's own default is 100 (keep only
     *  hundos). Stepper buttons rather than a text field - a keyboard is unreliable here. */
    private void tocIvRow(LinearLayout parent) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);
        tocIvLabel = new TextView(this);
        tocIvLabel.setTextColor(Color.parseColor("#e6edf3"));
        tocIvLabel.setTextSize(16);
        row.addView(tocIvLabel, new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f));
        row.addView(tocIvBtn("-5", -5));
        row.addView(tocIvBtn("+5", 5));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        lp.setMargins(0, dp(10), 0, 0);
        parent.addView(row, lp);
    }

    private android.widget.Button tocIvBtn(String label, final int delta) {
        android.widget.Button b = new android.widget.Button(this);
        b.setText(label);
        b.setTextSize(16);
        b.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                int iv = tocGetInt("minIvPercent", 80) + delta;
                if (iv < 0) iv = 0;
                if (iv > 100) iv = 100;
                tocWrite(tocGetInt("enabled", 0), tocGetInt("dry", 1), iv);
            }
        });
        return b;
    }

    /** Dry run: decisions are logged but no tag is written. Leave ON until the log looks right. */
    private void tocDryRow(LinearLayout parent) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);
        TextView t = new TextView(this);
        t.setText("Dry run (log only, no tags)");
        t.setTextColor(Color.parseColor("#6b7a8d"));
        t.setTextSize(14);
        row.addView(t, new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f));
        tocDrySw = new Switch(this);
        row.addView(tocDrySw);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        lp.setMargins(0, dp(8), 0, 0);
        parent.addView(row, lp);
        tocDrySw.setOnCheckedChangeListener(new CompoundButton.OnCheckedChangeListener() {
            public void onCheckedChanged(CompoundButton b, boolean on) {
                tocWrite(tocGetInt("enabled", 0), on ? 1 : 0, tocGetInt("minIvPercent", 80));
            }
        });
    }

    private void refreshToc() {
        if (tocSw == null) return;
        final int en = tocGetInt("enabled", 0);
        final int dry = tocGetInt("dry", 1);
        final int iv = tocGetInt("minIvPercent", 80);
        runOnUiThread(new Runnable() {
            public void run() {
                tocSw.setOnCheckedChangeListener(null);
                tocSw.setChecked(en == 1);
                tocSw.setOnCheckedChangeListener(new CompoundButton.OnCheckedChangeListener() {
                    public void onCheckedChanged(CompoundButton b, boolean on) {
                        tocWrite(on ? 1 : 0, tocGetInt("dry", 1), tocGetInt("minIvPercent", 80));
                    }
                });
                tocDrySw.setChecked(dry == 1);
                tocIvLabel.setText("Keep IV " + iv + "% and above");
                if (en != 1) {
                    tocState.setText("OFF");
                    tocState.setTextColor(Color.parseColor("#9aa7b8"));
                } else if (dry == 1) {
                    tocState.setText("ON  -  DRY RUN, logging only");
                    tocState.setTextColor(Color.parseColor("#e3b341"));
                } else {
                    tocState.setText("ON  -  tagging below " + iv + "%");
                    tocState.setTextColor(Color.parseColor("#3ad29f"));
                }
            }
        });
    }

    private TextView section(String t) {
        TextView v = new TextView(this);
        v.setText(t);
        v.setTextColor(Color.parseColor("#ffcb05"));
        v.setTextSize(12);
        v.setPadding(0, dp(26), 0, dp(2));
        return v;
    }

    /** The plain-English line under a feature name -- what it does, not what it is called. */
    private TextView desc(String t) {
        TextView v = new TextView(this);
        v.setText(t);
        v.setTextColor(Color.parseColor("#6b7a8d"));
        v.setTextSize(13);
        return v;
    }

    private TextView statusView() {
        TextView v = new TextView(this);
        v.setTextColor(Color.parseColor("#9aa7b8"));
        v.setTextSize(14);
        v.setPadding(0, dp(3), 0, 0);
        return v;
    }

    private void setStatus(FeatureRow r, boolean on) {
        r.status.setText(on ? "ON  -  " + r.onText : "OFF");
        r.status.setTextColor(on ? Color.parseColor("#3ad29f") : Color.parseColor("#9aa7b8"));
    }

    @Override
    protected void onResume() {
        super.onResume();
        refresh();
        handler.postDelayed(ticker, 4000);
    }

    @Override
    protected void onPause() {
        super.onPause();
        handler.removeCallbacks(ticker);
    }

    private void refresh() {
        new Thread(new Runnable() {
            public void run() {
                // Read the flag files directly. NOT pgrep: `pgrep -f catch_phone.py` self-matches
                // its own cmdline and reports a process that is not there.
                final boolean[] on = new boolean[rows.size()];
                for (int i = 0; i < rows.size(); i++) on[i] = flagOn(rows.get(i).flag);
                final String line = lastSummary();
                final String rw = readFile(STATUS_REWARD);
                runOnUiThread(new Runnable() {
                    public void run() {
                        for (int i = 0; i < rows.size(); i++) {
                            FeatureRow r = rows.get(i);
                            r.sw.setOnCheckedChangeListener(null);   // avoid re-firing the verb
                            r.sw.setChecked(on[i]);
                            setStatus(r, on[i]);
                            r.sw.setOnCheckedChangeListener(r.listener);
                        }
                        stats.setText(line);
                        refreshToc();
                        showReward(rw);
                    }
                });
            }
        }).start();
    }

    /** Colour-code the reward run so a stuck or failed pass is obvious instead of silent. */
    private void showReward(String s) {
        if (s == null || s.length() == 0) { rewardStatus.setText(""); return; }
        rewardStatus.setText(s);
        String l = s.toLowerCase();
        if (l.startsWith("done") || l.contains("caught")) {
            rewardStatus.setTextColor(Color.parseColor("#3ad29f"));
        } else if (l.contains("err") || l.contains("fail")) {
            rewardStatus.setTextColor(Color.parseColor("#f85149"));
        } else {
            rewardStatus.setTextColor(Color.parseColor("#e3b341"));
        }
    }

    private int dp(int v) {
        return (int) (v * getResources().getDisplayMetrics().density);
    }

    /** Fire the control verb, then VERIFY the flag actually changed and retry -- a toggle must never
     *  be silently lost. */
    private void applyToggle(final String flagPath, final String verb, final boolean want) {
        new Thread(new Runnable() {
            public void run() {
                for (int attempt = 0; attempt < 3; attempt++) {
                    shell(intent(verb));
                    for (int i = 0; i < 12; i++) {          // up to ~6s for the flag to settle
                        try { Thread.sleep(500); } catch (Exception e) { }
                        if (flagOn(flagPath) == want) {
                            android.util.Log.i("AutoCatcher", "toggle " + verb + " confirmed");
                            return;
                        }
                    }
                    android.util.Log.w("AutoCatcher", "toggle " + verb + " did not take, retrying");
                }
                runOnUiThread(new Runnable() { public void run() { refresh(); } });   // show truth
            }
        }).start();
    }

    private String shell(String cmd) {
        try {
            // feed the command over stdin: avoids arg-splitting differences between su builds
            Process p = Runtime.getRuntime().exec(new String[]{"su"});
            java.io.OutputStream os = p.getOutputStream();
            os.write((cmd + "\nexit\n").getBytes("UTF-8"));
            os.flush();
            os.close();
            BufferedReader r = new BufferedReader(new InputStreamReader(p.getInputStream()));
            String line, last = "";
            while ((line = r.readLine()) != null) {
                if (line.trim().length() > 0) last = line.trim();
            }
            p.waitFor();
            android.util.Log.i("AutoCatcher", "cmd=[" + cmd + "] out=[" + last + "]");
            return last;
        } catch (Exception e) {
            android.util.Log.e("AutoCatcher", "shell fail: " + e);
            return "";
        }
    }

    /** Plain Java file read -- the app domain CAN read /data/local/tmp without any shell. */
    private boolean flagOn(String path) {
        return readFile(path).equals("1");
    }

    private String readFile(String path) {
        try {
            java.io.File f = new java.io.File(path);
            if (!f.exists()) return "";
            BufferedReader r = new BufferedReader(new java.io.FileReader(f));
            StringBuilder sb = new StringBuilder();
            String line;
            while ((line = r.readLine()) != null) sb.append(line);
            r.close();
            return sb.toString().trim();
        } catch (Exception e) {
            return "";
        }
    }

    /** Live counters the catcher publishes to STATE. */
    private String lastSummary() {
        String s = readFile(STATE);
        if (s.length() == 0) return "waiting for catcher...";
        String caught = between(s, "caught=", " ");
        String fled = between(s, "fled=", " ");
        String spins = between(s, "spins=", " ");
        String xp = between(s, "xp=", " ");
        String items = between(s, "items=", " ");
        String ready = between(s, "ready=", " ");
        StringBuilder sb = new StringBuilder();
        if (caught != null) sb.append("caught ").append(caught);
        if (fled != null) sb.append("  fled ").append(fled);
        if (spins != null) sb.append("\nspins ").append(spins);
        if (xp != null) sb.append("  +").append(xp).append(" XP");
        if (items != null) sb.append("  ").append(items).append(" items");
        if (ready != null) sb.append("  (").append(ready).append(" ready)");
        return sb.length() > 0 ? sb.toString() : s;
    }

    private String between(String s, String start, String end) {
        int i = s.indexOf(start);
        if (i < 0) return null;
        i += start.length();
        int j = s.indexOf(end, i);
        if (j < 0) j = s.length();
        String v = s.substring(i, j).trim();
        return v.length() > 0 ? v : null;
    }
}

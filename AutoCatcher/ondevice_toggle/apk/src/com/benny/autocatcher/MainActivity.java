package com.benny.autocatcher;

import android.app.Activity;
import android.app.Instrumentation;
import android.app.NotificationManager;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.content.res.ColorStateList;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RectF;
import android.graphics.Typeface;
import android.graphics.drawable.ColorDrawable;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.RippleDrawable;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.text.SpannableStringBuilder;
import android.text.Spanned;
import android.text.TextUtils;
import android.text.style.ForegroundColorSpan;
import android.text.style.StyleSpan;
import android.util.DisplayMetrics;
import android.util.Log;
import android.view.ContextThemeWrapper;
import android.view.Gravity;
import android.view.HapticFeedbackConstants;
import android.view.View;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Space;
import android.widget.TextView;
import java.io.BufferedReader;
import java.io.File;
import java.io.FileOutputStream;
import java.io.FileReader;
import java.io.FileWriter;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.util.ArrayList;
import java.util.Locale;

/**
 * PoGo Auto 1.5 -- the on-phone control page (Benny 2026-11-18: "fix the autocatcher app while youre at it the ui
 * sucks ass" + "a gym battle toggle ... on my autoctcher app").
 * Since 1.4 the same state is also in the notification shade, with Catch / Spin / Gym buttons and alerts, so it can be
 * used without leaving the game: StatusService.java (the notification) and Alerts.java (when an alert is due).
 * 1.5: one tap of Catch Rewards is one reward run. The button stays off while a run is in flight and shows the run's
 * own line (Logic.reward); two runs at once crashed the game on 2026-11-18.
 *
 * The page answers "is it working?" first (the header and one status card), then shows every switch as a big tile you
 * tap anywhere, a Berries picker, Transfer on Catch, and the two one-off actions. Three classes live in this file:
 *   Logic    -- every decision behind the screen (what a status means, when the PC counts as silent). No Android class
 *               in it, so a plain JVM can check it.
 *   Screen   -- builds the views, reads the phone's files every 4 s and sends the taps. It needs only a themed Context,
 *               which is what lets RenderProbe draw it off screen.
 *   MainActivity (+ RenderProbe) -- the window around a Screen, and the off-screen picture of it.
 *
 * TWO HARD CONSTRAINTS, both learned the expensive way:
 *  1. This app's SELinux domain cannot use a shell. Toybox binaries (ls/tail/test) and shell
 *     operators return EMPTY, and Termux's home is 0700 to us. So all state is read with plain Java
 *     File I/O from world-readable files in /data/local/tmp, never by shelling out.
 *  2. The app cannot CREATE files in /data/local/tmp (owner=shell). Every flag file must already
 *     exist, root-created and chmod 666. Writes go through catcher_ctl.sh via the Termux
 *     RunCommandService intent (sent as root), which owns the flags and keeps the host process alive
 *     while a catcher feature is on.
 * A tap is never trusted after firing: Screen.send verifies the flag file actually holds the new value and
 * retries, because a held lock in catcher_ctl.sh once swallowed taps and left switches showing ON
 * while the backend stayed OFF. The tile shows the new state at once; the 4 s refresh shows the truth.
 */
public class MainActivity extends Activity implements Screen.Host {
    private static final String POST = "android.permission.POST_NOTIFICATIONS";

    private Screen screen;
    private SharedPreferences prefs;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        prefs = getSharedPreferences(StatusService.PREFS, MODE_PRIVATE);
        try {
            getWindow().setBackgroundDrawable(new ColorDrawable(Screen.BG));
            getWindow().setStatusBarColor(Screen.BG);
            getWindow().setNavigationBarColor(Screen.BG);
        } catch (Throwable t) {
            Log.w(Screen.TAG, "window colours: " + t);
        }
        try {
            screen = new Screen(this, this);
            setContentView(screen.root);
            askOnce();
        } catch (Throwable t) {   // never a bare crash on open: say what broke, on the screen and in logcat
            Log.e(Screen.TAG, "building the screen failed", t);
            screen = null;
            TextView v = new TextView(this);
            v.setText("PoGo Auto could not draw its screen:\n\n" + Log.getStackTraceString(t));
            v.setTextColor(Color.WHITE);
            v.setTextSize(12);
            v.setPadding(48, 160, 48, 48);
            setContentView(v);
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (screen != null) screen.start();
    }

    @Override
    protected void onPause() {
        super.onPause();
        if (screen != null) screen.stop();
    }

    /** Android 13+: notifications need a yes. Asked ONCE, the first time the app is opened. After that the Alerts tile
     *  says when they are not allowed, and a tap on it asks again (askNotifications). */
    private void askOnce() {
        try {
            if (Build.VERSION.SDK_INT >= 33 && !prefs.getBoolean(StatusService.K_ASKED, false)
                    && checkSelfPermission(POST) != PackageManager.PERMISSION_GRANTED) {
                prefs.edit().putBoolean(StatusService.K_ASKED, true).apply();
                requestPermissions(new String[]{POST}, 1);
            }
        } catch (Throwable t) {
            Log.w(Screen.TAG, "asking for notifications: " + t);
        }
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(code, permissions, results);
        if (screen != null) screen.refresh();
    }

    // ---- Screen.Host ----------------------------------------------------------------------------------------------

    /** The permission is there AND the app's notifications are not switched off in the phone's settings. */
    public boolean notificationsAllowed() {
        try {
            NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
            return nm == null || nm.areNotificationsEnabled();
        } catch (Throwable t) {
            return true;
        }
    }

    /** Ask again while Android still lets an app ask (never asked, or refused once); after that only the phone's own
     *  notification settings for this app can allow them, so open those. */
    public void askNotifications() {
        try {
            if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(POST) != PackageManager.PERMISSION_GRANTED
                    && (!prefs.getBoolean(StatusService.K_ASKED, false) || shouldShowRequestPermissionRationale(POST))) {
                prefs.edit().putBoolean(StatusService.K_ASKED, true).apply();
                requestPermissions(new String[]{POST}, 1);
                return;
            }
            Intent i = Build.VERSION.SDK_INT >= 26
                    ? new Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, getPackageName())
                    : new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, android.net.Uri.parse("package:" + getPackageName()));
            startActivity(i);
        } catch (Throwable t) {
            Log.w(Screen.TAG, "opening the notification settings: " + t);
        }
    }

    public void startStatus() {
        StatusService.ensure(this);
    }

    /**
     * Draws this app's screen OFF screen and saves it as two PNG files, so it can be looked at without opening the app
     * (opening it takes the foreground from the game):
     *     adb shell am instrument -w 'com.benny.autocatcher/.MainActivity$RenderProbe'
     * It starts no activity, sends no input and writes nothing outside the app's own files folder
     * (/data/data/com.benny.autocatcher/files): render_top.png is the first screenful, render_full.png is everything,
     * as if scrolled out. It reads the same /data/local/tmp files the real screen reads, so the picture shows the
     * phone's real state. `-e help 1` draws it with the "What each switch does" fold-out open; `-e demo 1` to `4`
     * draws a made-up state instead (see demo()).
     */
    public static class RenderProbe extends Instrumentation {
        private boolean openHelp;
        private int demo;

        @Override
        public void onCreate(Bundle args) {
            super.onCreate(args);
            openHelp = args != null && "1".equals(args.getString("help"));
            try {
                demo = args == null || args.getString("demo") == null ? 0 : Integer.parseInt(args.getString("demo"));
            } catch (NumberFormatException e) {
                demo = 0;
            }
            start();
        }

        @Override
        public void onStart() {
            final Bundle out = new Bundle();
            try {
                runOnMainSync(new Runnable() {
                    public void run() {
                        try {
                            out.putString("render", render(getTargetContext(), openHelp, demo));
                        } catch (Throwable t) {
                            out.putString("error", Log.getStackTraceString(t));
                        }
                    }
                });
            } catch (Throwable t) {
                out.putString("error", Log.getStackTraceString(t));
            }
            finish(out.containsKey("error") ? Activity.RESULT_CANCELED : Activity.RESULT_OK, out);
        }

        static String render(Context app, boolean openHelp, int demo) throws Exception {
            Context themed = new ContextThemeWrapper(app, android.R.style.Theme_Material_NoActionBar);
            Screen s = new Screen(themed, host(app, demo));
            if (openHelp) s.showHelp(true);
            if (demo > 0) s.apply(demo(s.read(), demo));
            DisplayMetrics m = themed.getResources().getDisplayMetrics();
            int w = m.widthPixels, h = m.heightPixels;
            s.root.measure(View.MeasureSpec.makeMeasureSpec(w, View.MeasureSpec.EXACTLY),
                           View.MeasureSpec.makeMeasureSpec(h, View.MeasureSpec.EXACTLY));
            s.root.layout(0, 0, w, h);
            File dir = app.getFilesDir();
            save(s.root, w, h, new File(dir, "render_top.png"));
            int full = Math.max(1, Math.min(s.content.getHeight(), 12000));
            save(s.content, w, full, new File(dir, "render_full.png"));
            return w + "x" + h + " px, density " + m.density + ", font scale "
                    + themed.getResources().getConfiguration().fontScale + ", content " + s.content.getHeight()
                    + " px tall, saved in " + dir;
        }

        /** The picture's stand-in for the window. It answers the one question the screen asks while it is drawn -- are
         *  notifications allowed? -- with the phone's real answer (demo 1: yes, demo 2: no) and does nothing else: the
         *  screen is never started here, so it starts no service and asks for nothing. */
        static Screen.Host host(final Context app, final int demo) {
            return new Screen.Host() {
                public boolean notificationsAllowed() {
                    if (demo == 1 || demo == 2) return demo == 1;
                    NotificationManager nm = (NotificationManager) app.getSystemService(Context.NOTIFICATION_SERVICE);
                    return nm == null || nm.areNotificationsEnabled();
                }

                public void askNotifications() {
                }

                public void startStatus() {
                }
            };
        }

        /** A made-up reading of the phone, for a picture of states the phone is not in right now. Nothing is written:
         *  it only replaces what the screen was told it read. 1 = everything on, a blocking why, few balls, the gym
         *  runner answering, High stardust 700+ with the catcher doing it, a levels file and an old stardust list,
         *  Transfer on Catch set up, notifications allowed; 2 = switched on but neither the catcher nor the gym runner
         *  answers, no levels file, notifications not allowed; 3 = the phone's real state, but High stardust switched
         *  to All (with a levels file) while the catcher does not report it and gives a long reason; 4 = the real state with a custom number in
         *  the switch file. The species in LEVELS are a sample for the picture, not the game's list. */
        static final String LEVELS = "base=100 species=1024 batch=sample\n1 476\n500 133\n"
                + "700 20 Audino, Chimecho, Cloyster, Combee, Delibird, Garbodor, Meowth, Minior, Paras, Parasect, Persian, "
                + "Sableye, Shellder, Shroomish, Staryu, Starmie, Trubbish, Vespiquen, Breloom, Foongus\n"
                + "1000 5 Audino, Cloyster, Shellder, Chimecho, Minior\n";

        static Screen.Snap demo(Screen.Snap s, int kind) {
            long now = s.now;
            if (kind == 3) {
                s.flags[0] = "1";
                s.flags[6] = "1";
                s.levels = LEVELS;
                if (s.state.length() > 0 && !s.state.contains(" why=")) {   // a long reason: it must wrap, never be cut
                    s.state += " why=catching everything for now: the shiny and weather reads cannot be trusted yet on "
                            + "this game version, so High stardust only is not applied (a sample text for the picture)";
                    s.stateMs = now - 3000;
                }
            } else if (kind == 4) {
                s.flags[6] = "250";
                s.levels = LEVELS;
            } else if (kind == 1) {
                s.flags = new String[]{"1", "1", "1", "1", "1", "1", "700"};   // catch, spin, perfect, tap, gym, berries, dust
                s.state = "caught=1234 fled=56 spins=789 xp=1234567 items=4321 ready=0 cooling=3 rate=0.0 up=7200 "
                        + "dust=1250000 balls=12/3/4 pinap=0 razz=0 sp=1 only=700 dustchk=100 why=out of balls: 12 Poke, "
                        + "3 Great, 4 Ultra left (it saves the last 15/5/5 for you)";
                s.levels = LEVELS;
                s.stateMs = now - 3000;
                s.gym = "15:31:07 battling Avalon Park: defender 2 of 6 is down";
                s.gymMs = now - 5000;
                s.cull = "running since 15:02";
                s.cullMs = now - 20000;
                s.reward = "running... (started 15:30:25)";
                s.rewardMs = now - 42000;
                s.tocExists = true;
                s.toc = Logic.tocJson(1, 1, 85);
            } else {
                s.flags = new String[]{"1", "0", "0", "0", "1", "razz", "1000"};
                s.levels = "";
                s.apples = "0";
                s.state = "caught=57 fled=3 spins=12 xp=8400 items=40 ready=2 cooling=1";   // an older catcher: no extra keys
                s.stateMs = now - 5 * 60000;
                s.gym = "";
                s.gymMs = 0;
                s.cull = "STOPPED 15:02: the game is not running -- open it and tap again";
                s.cullMs = now - 60000;
                s.reward = "FAILED: open Field Research (Today) in PoGo, then tap again @ 15:02:11";
                s.rewardMs = now - 60000;
            }
            return s;
        }

        static void save(View v, int w, int h, File f) throws Exception {
            Bitmap b = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888);
            Canvas c = new Canvas(b);
            c.drawColor(Screen.BG);
            v.draw(c);
            FileOutputStream o = new FileOutputStream(f);
            try {
                b.compress(Bitmap.CompressFormat.PNG, 100, o);
            } finally {
                o.close();
            }
            b.recycle();
        }
    }
}

/** Every decision behind the screen. No Android class in here, so a plain JVM can run it (the checks do). */
final class Logic {
    static final int DIM = 0, GOOD = 1, WAIT = 2, BAD = 3;   // the tone of a line: grey, green, amber, red
    static final long STATE_STALE_MS = 90000L;       // the catcher rewrites its state line every ~10 s while it runs
    static final long STARTING_MS = 45000L;          // after you switch a catcher feature on: its first report is due
    static final long GYM_STALE_MS = 60000L;         // the PC's gym listener must have written within this
    static final long CULL_LATE_MS = 45000L, CULL_STALE_MS = 15 * 60 * 1000L;
    // Catch Rewards: the phone's script answers a tap within a second (20 s when another verb holds its lock); a run
    // that died never says done; and a run that has just said done needs ~8 s more to hand the game back to the catcher.
    static final long REWARD_LATE_MS = 30000L, REWARD_STALE_MS = 15 * 60 * 1000L, REWARD_END_MS = 12000L;
    static final int LOW_BALLS = 20;                 // Poke + Great + Ultra at or under this: the balls line turns amber

    private Logic() { }

    /** A switch file: "1" is on, anything else is off (the catcher's flag()). */
    static String flagNorm(String text) {
        return "1".equals(text == null ? "" : text.trim()) ? "1" : "0";
    }

    /** The berries file the way catch_loop_fast.berry_mode reads it: 1 / pinap / razz, anything else = none ("0"). */
    static String berryNorm(String text) {
        String t = text == null ? "" : text.trim().toLowerCase(Locale.US);
        return (t.equals("1") || t.equals("pinap") || t.equals("razz")) ? t : "0";
    }

    // ---- the catcher's state line -----------------------------------------------------------------------------------
    // "caught=.. fled=.. spins=.. xp=.. items=.. ready=.. cooling=..[ rate=.. dust=.. up=.. balls=P/G/U pinap=.. razz=..
    //  sp=0|1][ why=<the rest of the line>]". Everything after cooling= is optional: an older catcher sends none of it.

    /** The key=value part (everything before why=). */
    static String counters(String state) {
        if (state.startsWith("why=")) return "";
        int w = state.indexOf(" why=");
        return w >= 0 ? state.substring(0, w) : state;
    }

    /** why= (always last, spaces allowed) = why nothing is being caught. 2026-10-30: the toggle read ON with no catches
     *  for 2.5 h while the ball bag was empty, and nothing on the screen said so. */
    static String why(String state) {
        if (state.startsWith("why=")) return state.substring(4).trim();
        int w = state.indexOf(" why=");
        return w >= 0 ? state.substring(w + 5).trim() : "";
    }

    /** One key's value out of the counters, or null when the key is not there (or empty). Whole keys only: sp= is never
     *  found inside spins=. */
    static String val(String counters, String key) {
        String k = key + "=";
        int n = counters.length(), i = 0;
        while (i < n) {
            int j = counters.indexOf(' ', i);
            if (j < 0) j = n;
            if (j - i > k.length() && counters.startsWith(k, i)) return counters.substring(i + k.length(), j);
            i = j + 1;
        }
        return null;
    }

    static long longOf(String s, long dflt) {
        if (s == null) return dflt;
        try {
            return Long.parseLong(s.trim());
        } catch (NumberFormatException e) {
            return dflt;
        }
    }

    /** 89600 -> 89,600. Anything that is not a whole number comes back as it is; nothing at all is a dash. */
    static String num(String raw) {
        if (raw == null) return "-";
        try {
            return String.format(Locale.US, "%,d", Long.parseLong(raw.trim()));
        } catch (NumberFormatException e) {
            return raw;
        }
    }

    /** 850 -> 850, 9458 -> 9.4K, 1234567 -> 1.2M. Cut off, never rounded up: a rate must not read higher than it is. */
    static String compact(double v) {
        if (v < 1000) return String.valueOf((long) Math.floor(v));
        if (v < 1000000) return String.format(Locale.US, "%.1fK", Math.floor(v / 100.0) / 10.0);
        return String.format(Locale.US, "%.1fM", Math.floor(v / 100000.0) / 10.0);
    }

    static String ago(long ms) {
        long s = Math.max(0, ms / 1000);
        if (s < 90) return s + " s";
        if (s < 5400) return (s + 30) / 60 + " min";
        return (s + 1800) / 3600 + " h";
    }

    /** The words beside the big caught number: "caught", or "caught - 13.8/min" when the catcher sends rate=. */
    static String caughtWords(String state) {
        String rate = val(counters(state), "rate");
        return rate == null ? "caught" : "caught - " + rate + "/min";
    }

    /** "657 caught - 13.8/min": the one-line summary (the notification uses it too). */
    static String summary(String state) {
        return num(val(counters(state), "caught")) + " " + caughtWords(state);
    }

    /** "+74,725 stardust - 9.4K/min" from dust= (and up=, the run's seconds, for the per-minute part). "" when the
     *  catcher sends no dust=. The per-minute part waits for half a minute of run: 2 catches in 5 s is not a rate. */
    static String dustLine(String state) {
        String c = counters(state);
        long d = longOf(val(c, "dust"), -1);
        if (d < 0) return "";
        String s = "+" + num(String.valueOf(d)) + " stardust";
        long up = longOf(val(c, "up"), -1);
        if (up >= 30 && d > 0) s += " - " + compact(d / (up / 60.0)) + "/min";
        return s;
    }

    /** {"Balls 2,280 / 6 / 6" (Poke / Great / Ultra), tone}: amber at LOW_BALLS or fewer in all. null when the catcher
     *  sends no balls=. */
    static String[] balls(String state) {
        String b = val(counters(state), "balls");
        if (b == null) return null;
        String[] p = b.split("/");
        if (p.length != 3) return new String[]{"Balls " + b, "" + DIM};
        long sum = 0;
        StringBuilder sb = new StringBuilder("Balls ");
        for (int i = 0; i < 3; i++) {
            long n = longOf(p[i], -1);
            if (n < 0) return new String[]{"Balls " + b, "" + DIM};
            sum += n;
            sb.append(i > 0 ? " / " : "").append(num(p[i]));
        }
        return new String[]{sb.toString(), "" + (sum <= LOW_BALLS ? WAIT : DIM)};
    }

    /** "202 Pinap, 10 Razz left" from pinap= / razz= ("" when the catcher sends neither). */
    static String berryStock(String state) {
        String c = counters(state);
        String pinap = val(c, "pinap"), razz = val(c, "razz");
        StringBuilder sb = new StringBuilder();
        if (pinap != null) sb.append(num(pinap)).append(" Pinap");
        if (razz != null) sb.append(sb.length() > 0 ? ", " : "").append(num(razz)).append(" Razz");
        return sb.length() > 0 ? sb.append(" left").toString() : "";
    }

    /** The tone of the stock note: amber when a berry the picker asks for has run out (nothing would be fed). */
    static int berryStockTone(String mode, String state) {
        String c = counters(state);
        long pinap = longOf(val(c, "pinap"), -1), razz = longOf(val(c, "razz"), -1);
        boolean wantsPinap = mode.equals("pinap") || mode.equals("1"), wantsRazz = mode.equals("razz") || mode.equals("1");
        return (wantsPinap && pinap == 0) || (wantsRazz && razz == 0) ? WAIT : DIM;
    }

    // ---- High stardust only (pogo_dust.on). 0 = catch everything; 1 = everything that pays more than a normal catch
    //      (a higher-paying species, or anything weather-boosted: +25%); N >= 2 = only catches worth N+ stardust, a
    //      weather boost counted. Every shiny is always caught. ------------------------------------------------------

    /** Digits and nothing else, at least one. */
    static boolean digits(String t) {
        if (t == null || t.length() == 0) return false;
        for (int i = 0; i < t.length(); i++) if (t.charAt(i) < '0' || t.charAt(i) > '9') return false;
        return true;
    }

    /** The switch file: a whole number. No file, 0 or anything that is not a whole number = everything ("0"). */
    static String dustNorm(String text) {
        String t = text == null ? "" : text.trim();
        return digits(t) && t.length() <= 7 ? String.valueOf(Integer.parseInt(t)) : "0";
    }

    /** only=N in the state line: what the catcher itself reports. 1 = only high-stardust species, N >= 2 = only species
     *  worth N+ stardust (always with every shiny). 0 = it does not say so: the mode is off, or this catcher does not
     *  know it. */
    static long only(String state) {
        return Math.max(0, longOf(val(counters(state), "only"), 0));
    }

    /** The Auto-Catch tile's words while it is on: what the catcher itself reports it catches. */
    static String catchLine(String state, boolean reporting) {
        long n = reporting ? only(state) : 0;
        if (n == 1) return "only high-stardust Pokemon and shinies";
        return n >= 2 ? "only " + num(String.valueOf(n)) + "+ stardust and shinies" : "catching nearby";
    }

    /** One level of the catcher's pogo_dust_levels.txt: {count, names ("" when the file gives none)}, or null when the
     *  file has no good line for it. The file: line 1 "base=100 species=1024 batch=<id>", then one line per level 1, 500,
     *  700 and 1000: "<N> <count>", followed by one space and the names joined with ", " only when there are 25 or
     *  fewer. Lines that do not fit are skipped. */
    static String[] dustLevel(String levels, String n) {
        if (levels == null) return null;
        String[] lines = levels.split("\n");
        for (int i = 0; i < lines.length; i++) {
            String l = lines[i].trim();
            if (!l.startsWith(n + " ")) continue;
            String rest = l.substring(n.length() + 1).trim();
            int sp = rest.indexOf(' ');
            String count = sp < 0 ? rest : rest.substring(0, sp);
            if (!digits(count) || count.length() > 6) continue;
            return new String[]{count, sp < 0 ? "" : rest.substring(sp + 1).trim()};
        }
        return null;
    }

    /** base= from the first line of the levels file (what a normal catch pays), or "" when it is not there. */
    static String dustBase(String levels) {
        if (levels == null || levels.length() == 0) return "";
        String b = val(levels.split("\n")[0].trim(), "base");
        return b != null && longOf(b, -1) > 0 ? b : "";
    }

    /** The hint under the High stardust row for what the switch file holds. The counts and the names come from the
     *  catcher's levels file, never from text in this app: the species change with the game. Without that file (it is
     *  not there until a catcher that writes it runs) the hint has no numbers. A weather-boosted spawn pays +25% and
     *  counts as high stardust (Benny 2026-11-18: "yes include weather boosted too"), so every hint says so. */
    static String dustHint(String value, String levels) {
        if (value.equals("0")) return "catching every Pokemon";
        if (!(value.equals("1") || value.equals("500") || value.equals("700") || value.equals("1000")))
            return "custom: " + num(value) + "+";
        String[] lv = dustLevel(levels, value);
        if (value.equals("1")) {
            if (lv == null) return "only what pays more than a normal catch, weather-boosted included, plus every shiny";
            String base = dustBase(levels);
            return "only what pays more than the normal " + (base.length() > 0 ? num(base) + " " : "") + "stardust: "
                    + num(lv[0]) + " species and anything weather-boosted, plus every shiny";
        }
        if (lv == null) return "only catches worth " + num(value) + "+ stardust, plus every shiny";
        return "only catches worth " + num(value) + "+ stardust: " + num(lv[0]) + " species"
                + (lv[1].length() > 0 ? ": " + lv[1] : "") + " (weather boost counts), plus every shiny";
    }

    /** dustchk=<hours> in the state line: how long ago the catcher last checked its stardust list. Above 72 hours the
     *  row says so ("" otherwise, when the key is not there, or when nobody is reporting). */
    static String dustStale(String state, boolean reporting) {
        long h = reporting ? longOf(val(counters(state), "dustchk"), -1) : -1;
        return h > 72 ? "stardust list not checked for " + (h / 24) + " days" : "";
    }

    /** The switch asks for a mode, Auto-Catch is on and the catcher is reporting, but its line does not say only=<the
     *  same number>: the running catcher is not doing it (an older catcher does not know the switch). "" = nothing to
     *  warn about. Not within 30 s of a tap: the catcher rewrites its line every ~10 s. */
    static String dustWarn(String value, boolean catchOn, String state, long stateAgeMs, long tapAgoMs) {
        long n = longOf(value, 0);
        if (n < 1 || !catchOn) return "";
        if (state.length() == 0 || stateAgeMs < 0 || stateAgeMs > STATE_STALE_MS) return "";   // nobody is reporting
        if (tapAgoMs >= 0 && tapAgoMs <= 30000) return "";
        long doing = only(state);
        if (doing == n) return "";
        if (doing == 0) return "The running catcher is not doing this yet: it still catches everything.";
        return "The running catcher reports another setting: "
                + (doing == 1 ? "all high-stardust species" : num(String.valueOf(doing)) + "+") + ".";
    }

    /** sp=: 1 = the last catch paid with a Star Piece, 0 = without one, -1 = the catcher did not say. */
    static int starPiece(String state) {
        String v = val(counters(state), "sp");
        return "1".equals(v) ? 1 : "0".equals(v) ? 0 : -1;
    }

    /** {the words beside the header dot, tone, the line under the status card ("" = none)}.
     *  anyOn = a switch that keeps the catcher alive is on; ageMs = how old the state file is (below 0: there is
     *  none); sinceOnTapMs = how long ago a catcher switch was switched on from this screen (below 0: not in this
     *  session). */
    static String[] status(boolean anyOn, String state, long ageMs, long sinceOnTapMs) {
        if (!anyOn) return new String[]{"catcher off", "" + DIM, ""};
        boolean silent = ageMs < 0 || state.length() == 0 || ageMs > STATE_STALE_MS;
        if (silent && sinceOnTapMs >= 0 && sinceOnTapMs <= STARTING_MS)
            return new String[]{"catcher starting", "" + WAIT, "Waiting for the catcher's first report..."};
        if (ageMs < 0 || state.length() == 0)
            return new String[]{"catcher not reporting", "" + BAD, "No report from the catcher yet. Is the game open?"};
        if (ageMs > STATE_STALE_MS)
            return new String[]{"catcher not reporting", "" + BAD,
                                "No update from the catcher for " + ago(ageMs) + ". Is the game open?"};
        String why = why(state);
        if (why.length() > 0) return new String[]{"catcher waiting", "" + WAIT, cap(why)};
        return new String[]{"catcher running", "" + GOOD, ""};
    }

    /** Capital first letter: the catcher's reasons start small ("out of balls: ..."). */
    static String cap(String s) {
        return s == null || s.length() == 0 ? "" : Character.toUpperCase(s.charAt(0)) + s.substring(1);
    }

    // ---- the notification and its alerts (app 1.4) -----------------------------------------------------------------

    /** The ongoing notification: {its title, the line under it, the text when it is pulled open}. The title is the
     *  catcher's own summary while it reports ("620 caught - 13.3/min - Star Piece OFF"), else what is wrong ("Catcher
     *  not reporting"). The lines, most urgent first: the why= problem, the gym runner's line while Gym is on (or when
     *  it STOPPED), the high-stardust mode, the stardust and the balls.
     *  sinceOnTapMs / gymTapAgoMs = how long ago Catch or Spin / Gym was switched on from the notification (below 0:
     *  it was not): until the catcher or the gym runner had time to answer, they read "starting", as on the screen. */
    static String[] shade(boolean anyOn, String state, long ageMs, long sinceOnTapMs,
                          boolean gymOn, String gym, long gymAgeMs, long gymTapAgoMs) {
        String[] st = status(anyOn, state, ageMs, sinceOnTapMs);
        boolean reporting = st[0].equals("catcher running") || st[0].equals("catcher waiting");
        String title = cap(st[0]);
        StringBuilder big = new StringBuilder(st[2]);
        if (gymOn || (gymAgeMs >= 0 && gymAgeMs <= GYM_STALE_MS && gymStopped(gym))) {
            String g = gym(gymOn, gym, gymAgeMs, gymTapAgoMs)[0];
            big.append(big.length() > 0 ? "\n" : "").append("Gym: ").append(g.length() > 0 ? g : "off");
        }
        if (reporting) {
            title = summary(state);
            int sp = starPiece(state);
            if (sp >= 0) title += sp == 1 ? " - Star Piece ON" : " - Star Piece OFF";
            long only = only(state);
            if (only >= 1)
                big.append(big.length() > 0 ? "\n" : "")
                   .append(only == 1 ? "High stardust only" : "Only " + num(String.valueOf(only)) + "+ stardust")
                   .append(", plus every shiny");
            String d = dustLine(state);
            String[] b = balls(state);
            String more = d + (d.length() > 0 && b != null ? " - " : "") + (b != null ? b[0] : "");
            if (more.length() > 0) big.append(big.length() > 0 ? "\n" : "").append(more);
        }
        String all = big.toString();
        int nl = all.indexOf('\n');
        return new String[]{title, nl < 0 ? all : all.substring(0, nl), all};
    }

    /** why= without a leading Star Piece note: catch_loop_fast.starpiece_why puts "the Star Piece ran out at HH:MM:
     *  catches pay a third less stardust" first, and the catching reason, when there is one, after "; ". */
    static String whyCore(String why) {
        if (!why.toLowerCase(Locale.US).startsWith("the star piece ran out")) return why;
        int i = why.indexOf("; ");
        return i >= 0 ? why.substring(i + 2).trim() : "";
    }

    /** The Star Piece note at the head of a why= ("" when it has none). */
    static String whyStar(String why) {
        if (!why.toLowerCase(Locale.US).startsWith("the star piece ran out")) return "";
        int i = why.indexOf("; ");
        return i >= 0 ? why.substring(0, i) : why;
    }

    /** The kind of a why= that STOPS the catching ("" = it does not, or it is routine). The texts are the catcher's:
     *  catch_loop_fast.balls_why(), the holds of its JS, why_idle() and the state() calls of its attach loop.
     *  NOT alerts, on purpose: "no Pokemon in range" / "no Pokemon worth a ball", "paused: Pokemon GO is not showing its
     *  map" (every menu he opens), "spins are being refused" (every teleport cooldown), "PoGo is not open",
     *  "starting: ...", "can't reach the game" (it retries). */
    static String alertKind(String why) {
        String w = whyCore(why).toLowerCase(Locale.US);
        if (w.length() == 0) return "";
        if (w.contains("storage is full")) return "storage";
        if (w.startsWith("out of balls") || w.startsWith("out of poke balls") || w.startsWith("keeping the last")
                || w.startsWith("holding the last")) return "balls";
        if (w.contains("every throw is fleeing")) return "flee";
        if (w.startsWith("the game is not answering")) return "silent";
        if (w.contains("can't hook this game version")) return "version";
        if (w.startsWith("safety pause")) return "safety";
        if (w.contains("daily spin limit")) return "spinlimit";
        return "";
    }

    static String alertTitle(String kind) {
        if (kind.equals("storage")) return "Catching stopped: storage is full";
        if (kind.equals("balls")) return "Catching stopped: no balls to throw";
        if (kind.equals("flee")) return "Catching paused: every throw flees";
        if (kind.equals("silent")) return "Catching stopped: the game is not answering";
        if (kind.equals("version")) return "The catcher cannot run on this game version";
        if (kind.equals("safety")) return "The catcher is in a safety pause";
        if (kind.equals("spinlimit")) return "The daily spin limit is reached";
        if (kind.equals("star")) return "The Star Piece ran out";
        if (kind.equals("gym")) return "Gym Battle stopped";
        return "PoGo Auto";
    }

    /** How long a reason must be gone before its return is a NEW stop worth another alert. The catcher's holds lapse
     *  and come back (a full storage is a 60 s hold, re-armed by the next refused catch -- which can take minutes where
     *  few Pokemon are around), so a short gap is the same state. Storage is the shortest: once he has made room, the
     *  next fill-up is news. Balls is long: around the ball floor every spun stop makes "out of balls" go and come
     *  back. */
    static long alertQuietMs(String kind) {
        if (kind.equals("storage")) return 5 * 60000L;
        if (kind.equals("silent")) return 5 * 60000L;
        if (kind.equals("version")) return 60 * 60000L;
        if (kind.equals("spinlimit")) return 6 * 3600000L;
        return 15 * 60000L;   // balls, flee, safety
    }

    /** A status line without its leading clock time ("15:31:07 STOPPED: ..." -> "STOPPED: ..."). */
    static String afterTime(String line) {
        return line == null ? "" : line.trim().replaceFirst("^\\d{1,2}:\\d{2}(:\\d{2})?\\s+", "");
    }

    /** The gym runner says it stopped: its line reads STOPPED right after the clock time. Nothing else is red. */
    static boolean gymStopped(String line) {
        return afterTime(line).startsWith("STOPPED");
    }

    /** The line of the Gym Battle tile after ON / off: {text, tone}. The gym runner runs on the phone (the switch
     *  starts its supervisor, run_gym.sh) and writes ONE status line. statusAgeMs below 0 = no status file; tapAgoMs
     *  below 0 = not switched on from this screen. A line older than GYM_STALE_MS is never shown as if it were live:
     *  switched on it then reads "not answering", switched off it reads nothing. */
    static String[] gym(boolean on, String status, long statusAgeMs, long tapAgoMs) {
        boolean fresh = status.length() > 0 && statusAgeMs >= 0 && statusAgeMs <= GYM_STALE_MS;
        if (fresh) return new String[]{status, "" + (gymStopped(status) ? BAD : on ? GOOD : DIM)};
        if (!on) return new String[]{"", "" + DIM};
        if (tapAgoMs >= 0 && tapAgoMs <= GYM_STALE_MS) return new String[]{"starting the gym runner...", "" + WAIT};
        return new String[]{"the gym runner is not answering", "" + BAD};
    }

    /** The PC's cull status line: {text, tone, "1" when the button may be tapped}. A tap the PC has not answered yet
     *  says so; the button stays off while a cull is queued or running, so one tap is one cull (the rules of app 1.2).
     *  statusMs = the status file's last-modified time (0: none); tapMs = when Cull Now was tapped (0: not here). */
    static String[] cull(String s, long statusMs, long tapMs, long now) {
        if (tapMs > 0 && statusMs < tapMs - 2000) {   // the PC has not written since the tap
            boolean late = now - tapMs > CULL_LATE_MS;
            return new String[]{late ? "the PC has not picked it up -- is it on and is the listener running?"
                                     : "sent -- waiting for the PC...", "" + (late ? BAD : WAIT), late ? "1" : "0"};
        }
        String l = s == null ? "" : s.toLowerCase(Locale.US);
        boolean inFlight = l.startsWith("queued") || l.startsWith("running");
        boolean stale = statusMs > 0 && now - statusMs > CULL_STALE_MS;   // a PC that died mid-pass never says done
        boolean busy = inFlight && !stale;
        String text = (s == null || s.length() == 0) ? "" : (inFlight && stale ? s + " (no update for 15+ min)" : s);
        int tone = l.startsWith("done") ? GOOD : l.startsWith("stopped") ? BAD : busy ? WAIT : DIM;
        return new String[]{text, "" + tone, busy ? "0" : "1"};
    }

    /** The Catch Rewards line: {text, tone, "1" when the button may be tapped}. One tap is one reward run -- two at
     *  once crashed the game (2026-11-18) -- so the button is off from the tap until the phone's script has answered,
     *  while its line reads queued / running (15 minutes at most: a run that died never says done), and for the few
     *  seconds a run that has just finished still needs to hand the game back to the catcher (catcher_ctl.sh throws a
     *  tap away until then). statusMs = the status file's last-modified time (0: none); tapMs = when Catch Rewards was
     *  tapped on this screen (0: not here). */
    static String[] reward(String s, long statusMs, long tapMs, long now) {
        if (tapMs > 0 && statusMs < tapMs - 2000) {   // the script has not written since the tap
            boolean late = now - tapMs > REWARD_LATE_MS;
            return new String[]{late ? "no answer from the phone -- tap again" : "sent -- starting...",
                                "" + (late ? BAD : WAIT), late ? "1" : "0"};
        }
        if (s == null || s.length() == 0) return new String[]{"", "" + DIM, "1"};
        String l = s.toLowerCase(Locale.US);
        long age = statusMs > 0 ? now - statusMs : -1;
        if (l.startsWith("queued") || l.startsWith("running")) {
            if (age > REWARD_STALE_MS) return new String[]{s + " (no update for 15+ min)", "" + BAD, "1"};
            return new String[]{age >= 0 ? s + " - " + ago(age) : s, "" + WAIT, "0"};
        }
        // "Gym Battle is ..." is catcher_ctl.sh saying why it started no run: nothing to wait for.
        boolean ending = !l.startsWith("gym battle") && age >= 0 && age < REWARD_END_MS;
        return new String[]{ending ? s + " - finishing..." : s, "" + rewardTone(s), ending ? "0" : "1"};
    }

    /** Colour-code the reward run so a stuck or failed pass is obvious instead of silent. */
    static int rewardTone(String s) {
        String l = s.toLowerCase(Locale.US);
        if (l.startsWith("done") || l.contains("caught")) return GOOD;
        if (l.contains("err") || l.contains("fail")) return BAD;
        return WAIT;
    }

    /** Minimal int scrape of the Transfer-on-Catch JSON -- avoids pulling in a JSON parser for three fields. */
    static int tocInt(String json, String key, int dflt) {
        try {
            int i = json.indexOf("\"" + key + "\"");
            if (i < 0) return dflt;
            int c = json.indexOf(':', i) + 1;
            while (c < json.length() && json.charAt(c) == ' ') c++;   // python's json.dumps puts a space there
            int e = c;
            while (e < json.length() && "-0123456789".indexOf(json.charAt(e)) >= 0) e++;
            return Integer.parseInt(json.substring(c, e));
        } catch (Exception ex) {
            return dflt;
        }
    }

    /** The whole Transfer-on-Catch file. Fields the screen does not show keep sane defaults. */
    static String tocJson(int enabled, int dry, int minIv) {
        return "{\"enabled\":" + enabled + ",\"dry\":" + dry + ",\"minIvPercent\":" + minIv
                + ",\"transferShiny\":0,\"transferShadow\":0,\"transferBG\":0,\"xxlKeep\":[5],\"ignoreSpecies\":[]}";
    }
}

/** The whole screen. Builds the views, reads the phone's files every 4 s, sends the taps. */
final class Screen {
    static final String TAG = "AutoCatcher";
    static final String VERSION = "1.5";

    /** What the screen needs from the window it lives in (RenderProbe, which draws it off screen, passes a stand-in
     *  that only answers the question). */
    interface Host {
        boolean notificationsAllowed();

        void askNotifications();

        void startStatus();
    }

    // The palette of the sketch Benny approved (2026-11-18).
    static final int BG = 0xff0e1116, CARD = 0xff171c24, CARD_ON = 0xff12301f, LINE = 0xff262d38,
                     TEXT = 0xffe6edf3, DIMC = 0xff7d8a9b, FAINT = 0xff3a4350, YELLOW = 0xffffcb05, GREEN = 0xff3ad29f,
                     AMBER = 0xffe3b341, RED = 0xfff85149, BLUE = 0xff1f6feb, INK = 0xff0e1116,
                     AMBER_FILL = 0xff2a2412;

    static final String HOME = "/data/data/com.termux/files/home/pogo";
    static final String CTL = HOME + "/catcher_ctl.sh";
    static final String T = "/data/local/tmp/";
    static final String CATCHFLAG = T + "pogo_catch.on", SPINFLAG = T + "pogo_spin.on",
                        PERFECTFLAG = T + "pogo_perfect.on", TAPFLAG = T + "pogo_tap.on",
                        APPLEFLAG = T + "pogo_apples.on";
    // Gym Battle: the switch writes this flag through catcher_ctl.sh. gym-on also starts the phone's gym supervisor
    // (run_gym.sh); gym-off only writes the flag and the supervisor stops by itself. The gym runner writes ONE status
    // line, which the tile shows.
    static final String GYMFLAG = T + "pogo_gym.on", GYM_STATUS = T + "pogo_gym_status.txt";
    // High stardust only: a whole number. 0 (or no file) = everything; 1 = everything that pays more than a normal
    // catch (weather-boosted counts); N = only catches worth N+ stardust. Every shiny is always caught. The catcher
    // reads it; catcher_ctl.sh dust-off / dust-on / dust-<N> write it. What each step means today (how many species,
    // which ones) is in a file the catcher writes, DUST_LEVELS: the species change with the game, so no list is baked
    // into this app.
    static final String DUSTFLAG = T + "pogo_dust.on", DUST_LEVELS = T + "pogo_dust_levels.txt";
    // Berries: 1 = Pinap + Razz, pinap, razz, anything else = none. The catcher reads it every second.
    static final String BERRYFLAG = T + "pogo_berries.on";
    static final String STATE = T + "pogo_state.txt";
    static final String STATUS_REWARD = T + "pogo_rewards.txt";
    // Transfer-on-Catch config. A JSON file rather than a flag because it holds several values. This app can WRITE an
    // existing world-writable file but cannot CREATE one in /data/local/tmp, so the card is live only when root has
    // made the file; without it the card is greyed out and says so, instead of showing a switch that does nothing.
    static final String TOCFILE = T + "pogo_toc.json";
    // CULL NOW (Benny 2026-11-05): the cull runs on the PC (pogo_extract/cull_button.py). A tap writes one request line
    // as root; the PC picks it up within ~15 s and writes its progress to CULL_STATUS (queued / running / done / STOPPED).
    static final String CULL_REQ = T + "pogo_cull.req", CULL_STATUS = T + "pogo_cull_status.txt";

    private static final int MATCH = LinearLayout.LayoutParams.MATCH_PARENT, WRAP = LinearLayout.LayoutParams.WRAP_CONTENT;

    /** One flag file: what the screen shows for it, and a tap that is still being applied. */
    private static final class Flag {
        static final int SWITCH = 0, BERRIES = 1, NUMBER = 2;   // the file holds 1 / 0, a berry mode, a whole number
        final String path;
        final int kind;
        String file = "0";       // what the file held at the last read (normalised)
        String shown = "0";      // what the screen shows: a tap in flight outranks the file
        String want;             // a tap in flight: the value it asked for (null = none)
        String lastWant = "";    // the value the last tap asked for
        long wantUntil;          // a tap whose sender never came back stops counting here
        volatile int gen;        // a newer tap makes an older one stop retrying
        boolean failed;          // the last tap never took

        Flag(String path, int kind) {
            this.path = path;
            this.kind = kind;
        }

        String norm(String text) {
            return kind == BERRIES ? Logic.berryNorm(text) : kind == NUMBER ? Logic.dustNorm(text) : Logic.flagNorm(text);
        }

        boolean applying() {
            return want != null && !file.equals(want);
        }
    }

    /** A small on / off switch drawn by hand, so it looks the same on every Android. Whatever holds it takes the tap. */
    private static final class Toggle extends View {
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final RectF track = new RectF();
        private boolean on;

        Toggle(Context c) {
            super(c);
        }

        void set(boolean v) {
            if (v != on) {
                on = v;
                invalidate();
            }
        }

        @Override
        protected void onDraw(Canvas c) {
            float w = getWidth(), h = getHeight();
            track.set(0, 0, w, h);
            paint.setColor(on ? GREEN : 0xff2b3340);
            c.drawRoundRect(track, h / 2f, h / 2f, paint);
            paint.setColor(on ? 0xffffffff : DIMC);
            c.drawCircle(on ? w - h / 2f : h / 2f, h / 2f, h / 2f - h * 0.15f, paint);
        }
    }

    /** One switch tile. */
    private static final class Tile {
        Flag flag;
        String onVerb, offVerb, onText, offText;
        LinearLayout box;
        Toggle toggle;
        TextView status;
        int painted = -1;
    }

    /** One read of everything the screen shows. */
    static final class Snap {
        long now;
        String[] flags;
        String state = "", gym = "", reward = "", cull = "", toc = "", apples = "", levels = "";
        long stateMs, gymMs, cullMs, rewardMs;
        boolean tocExists;
    }

    final Context ctx;
    final ScrollView root;          // what the Activity shows
    final LinearLayout content;     // everything inside it (RenderProbe draws this in full)
    private final Host host;        // the window around this screen
    private final SharedPreferences prefs;
    private boolean active;         // between start() and stop(): the screen is in front
    private boolean wasAllowed = true;
    private long statusAskedMs;
    private final float density;
    private final Typeface medium = Typeface.create("sans-serif-medium", Typeface.NORMAL);
    private final Handler main = new Handler(Looper.getMainLooper());
    private final Runnable ticker = new Runnable() {
        public void run() {
            refresh();
            main.postDelayed(this, 4000);   // keep the screen honest with reality
        }
    };

    private final Flag catchF = new Flag(CATCHFLAG, Flag.SWITCH), spinF = new Flag(SPINFLAG, Flag.SWITCH),
                       perfectF = new Flag(PERFECTFLAG, Flag.SWITCH), tapF = new Flag(TAPFLAG, Flag.SWITCH),
                       gymF = new Flag(GYMFLAG, Flag.SWITCH), berryF = new Flag(BERRYFLAG, Flag.BERRIES),
                       dustF = new Flag(DUSTFLAG, Flag.NUMBER);
    private final Flag[] flags = {catchF, spinF, perfectF, tapF, gymF, berryF, dustF};
    private final ArrayList<Tile> tiles = new ArrayList<Tile>();
    private Tile catchTile, gymTile, alertsTile;

    private GradientDrawable headDot;
    private TextView headWords, bigNum, bigWords, sFled, sSpins, sXp, sItems, dustText, spChip, ballsText, whyLine;
    private LinearLayout numbers, extraRow;
    private int spPainted = -2;
    private Bar berryBar, dustBar;
    private TextView berryStock, dustHint, dustWarn;
    private LinearLayout tocRow1, tocRow2;
    private Toggle tocToggle;
    private TextView tocIv, tocDry, tocNote;
    private int tocDryPainted = -1;
    private TextView rewardBtn, cullBtn, rewardStatus, cullStatus;
    private TextView helpOpen, helpBody;

    private Snap last;
    private long gymTapMs = 0, cullTapMs = 0, catcherOnTapMs = 0, dustTapMs = 0, rewardTapMs = 0;

    Screen(Context c, Host h) {
        ctx = c;
        host = h;
        prefs = c.getSharedPreferences(StatusService.PREFS, Context.MODE_PRIVATE);
        density = c.getResources().getDisplayMetrics().density;

        root = new ScrollView(c);
        root.setBackgroundColor(BG);
        root.setFitsSystemWindows(true);          // clear the status / navigation bars when the window runs under them
        root.setVerticalScrollBarEnabled(false);

        content = new LinearLayout(c);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(dp(16), dp(8), dp(16), dp(24));

        content.addView(header(), lp(MATCH, WRAP, 0, 0));
        content.addView(statusCard(), lp(MATCH, WRAP, 10, 0));
        whyLine = text("", 14.5f, AMBER, true);      // why nothing is caught: right under the card, wraps, never cut off
        whyLine.setVisibility(View.GONE);
        LinearLayout.LayoutParams wl = lp(MATCH, WRAP, 10, 0);
        wl.setMargins(dp(4), dp(10), dp(4), 0);
        content.addView(whyLine, wl);

        catchTile = tile("Auto-Catch", catchF, "catch-on", "catch-off", "catching nearby", "", 2);
        Tile tSpin = tile("Auto-Spin", spinF, "spin-on", "spin-off", "spinning stops", "", 2);
        Tile tPerfect = tile("Perfect Throw", perfectF, "perfect-on", "perfect-off", "Excellent + curve", "", 2);
        Tile tTap = tile("Tap to Move", tapF, "tap-on", "tap-off", "tap the map to move", "", 2);
        content.addView(tileRow(catchTile, tSpin), lp(MATCH, WRAP, 14, 0));
        content.addView(tileRow(tPerfect, tTap), lp(MATCH, WRAP, 10, 0));
        gymTile = tile("Gym Battle", gymF, "gym-on", "gym-off", "", "", 3);
        content.addView(gymTile.box, lp(MATCH, WRAP, 10, 0));

        // High stardust only (Benny 2026-11-18: "a catch mode that only catches high stardust pokemon (+ shinies)",
        // "inclusive of EVERY higher than avg stardust pokemon for that mode")
        content.addView(section("HIGH STARDUST ONLY", null), sectionLp());
        dustBar = new Bar(dustF, new String[][]{{"Off", "0", "dust-off"}, {"All", "1", "dust-on"},
                                                {"500+", "500", "dust-500"}, {"700+", "700", "dust-700"},
                                                {"1,000+", "1000", "dust-1000"}});
        content.addView(dustBar.view, lp(MATCH, WRAP, 0, 0));
        content.addView(dustBar.note, noteLp());
        dustHint = text("", 12, DIMC, false);        // what the lit step means today (from the catcher's levels file)
        content.addView(dustHint, noteLp());
        dustWarn = text("", 12, AMBER, false);       // an old stardust list; the catcher reporting another setting
        dustWarn.setVisibility(View.GONE);
        content.addView(dustWarn, noteLp());

        berryStock = text("", 12, DIMC, false);
        berryStock.setSingleLine(true);
        content.addView(section("BERRIES", berryStock), sectionLp());
        berryBar = new Bar(berryF, new String[][]{{"Off", "0", "berries-off"}, {"Pinap", "pinap", "berries-pinap"},
                                                  {"Razz", "razz", "berries-razz"}, {"Both", "1", "berries-on"}});
        content.addView(berryBar.view, lp(MATCH, WRAP, 0, 0));
        content.addView(berryBar.note, noteLp());

        content.addView(section("TRANSFER ON CATCH", null), sectionLp());
        content.addView(tocCard(), lp(MATCH, WRAP, 0, 0));

        content.addView(section("ACTIONS", null), sectionLp());
        content.addView(actions(), lp(MATCH, WRAP, 0, 0));

        // App 1.4: the alerts of the status notification (StatusService) can be switched off here.
        content.addView(section("NOTIFICATIONS", null), sectionLp());
        alertsTile = plainTile("Alerts", 4);
        alertsTile.box.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                tick(v);
                onAlerts();
            }
        });
        content.addView(alertsTile.box, lp(MATCH, WRAP, 0, 0));

        content.addView(help(), lp(MATCH, WRAP, 12, 0));

        root.addView(content, new ScrollView.LayoutParams(ScrollView.LayoutParams.MATCH_PARENT,
                                                          ScrollView.LayoutParams.WRAP_CONTENT));
        Snap first;
        try {
            first = read();          // a dozen tiny files: the first frame already shows the truth
        } catch (Throwable t) {
            Log.w(TAG, "first read failed: " + t);
            first = empty();
        }
        apply(first);
    }

    // ---- life cycle -----------------------------------------------------------------------------------------------

    void start() {
        stop();
        active = true;
        refresh();
        main.postDelayed(ticker, 4000);
    }

    void stop() {
        active = false;
        main.removeCallbacks(ticker);
    }

    /** Read the files off the main thread, then paint. NOT pgrep: `pgrep -f catch_phone.py` self-matches its own
     *  cmdline and reports a process that is not there -- the flag files are the truth. */
    void refresh() {
        new Thread(new Runnable() {
            public void run() {
                final Snap s;
                try {
                    s = read();
                } catch (Throwable t) {
                    Log.w(TAG, "read failed: " + t);
                    return;
                }
                main.post(new Runnable() {
                    public void run() {
                        apply(s);
                    }
                });
            }
        }, "ac-refresh").start();
    }

    private Snap empty() {
        Snap s = new Snap();
        s.now = System.currentTimeMillis();
        s.flags = new String[flags.length];
        for (int i = 0; i < flags.length; i++) s.flags[i] = "";
        return s;
    }

    Snap read() {
        Snap s = empty();
        for (int i = 0; i < flags.length; i++) s.flags[i] = readFile(flags[i].path);
        s.apples = readFile(APPLEFLAG);
        s.levels = readText(DUST_LEVELS);
        s.state = readFile(STATE);
        s.stateMs = new File(STATE).lastModified();          // 0 when missing
        s.gym = readFile(GYM_STATUS);
        s.gymMs = new File(GYM_STATUS).lastModified();
        s.reward = readFile(STATUS_REWARD);
        s.rewardMs = new File(STATUS_REWARD).lastModified();
        s.cull = readFile(CULL_STATUS);
        s.cullMs = new File(CULL_STATUS).lastModified();
        s.tocExists = new File(TOCFILE).exists();
        s.toc = s.tocExists ? readFile(TOCFILE) : "";
        return s;
    }

    // ---- painting -------------------------------------------------------------------------------------------------

    void apply(Snap s) {
        last = s;
        try {
            for (int i = 0; i < flags.length; i++) {
                Flag f = flags[i];
                f.file = f.norm(s.flags[i]);
                if (f.want != null && s.now > f.wantUntil) {   // its sender never came back (root or Termux hung)
                    f.want = null;
                    f.failed = true;
                }
                if (f.failed && f.file.equals(f.lastWant)) f.failed = false;   // it did take after all
                f.shown = f.want != null ? f.want : f.file;
            }
            paintStatus(s);
            for (int i = 0; i < tiles.size(); i++) paintTile(tiles.get(i), s);
            paintDust(s);
            paintBerries(s);
            paintToc(s);
            paintReward(s);
            paintCull(s);
            paintAlerts();
            startStatus(s);
        } catch (Throwable t) {
            Log.e(TAG, "painting failed", t);
        }
    }

    /** Paint again from the last read -- a tap shows at once, before the next read. */
    private void repaint() {
        if (last != null) apply(last);
    }

    private void paintStatus(Snap s) {
        // Apples has no switch on this screen, but it keeps the catcher alive like the other four.
        boolean anyOn = catchF.shown.equals("1") || spinF.shown.equals("1") || perfectF.shown.equals("1")
                || tapF.shown.equals("1") || Logic.flagNorm(s.apples).equals("1");
        long ageMs = s.stateMs > 0 ? Math.max(0, s.now - s.stateMs) : -1;
        long sinceTap = catcherOnTapMs > 0 ? Math.max(0, s.now - catcherOnTapMs) : -1;
        String[] st = Logic.status(anyOn, s.state, ageMs, sinceTap);
        int tone = Integer.parseInt(st[1]);
        headWords.setText(st[0]);
        headWords.setTextColor(color(tone));
        headDot.setColor(tone == Logic.DIM ? FAINT : color(tone));
        if (st[2].length() > 0) {
            whyLine.setText(st[2]);
            whyLine.setTextColor(color(tone));
            whyLine.setVisibility(View.VISIBLE);
        } else {
            whyLine.setVisibility(View.GONE);
        }

        // The numbers of a run that is not reporting are not live numbers: they stay, greyed.
        boolean live = tone == Logic.GOOD || (tone == Logic.WAIT && !st[0].equals("catcher starting"));
        numbers.setAlpha(live ? 1f : 0.4f);
        String cs = Logic.counters(s.state);
        bigNum.setText(Logic.num(Logic.val(cs, "caught")));
        bigWords.setText(Logic.caughtWords(s.state));
        sFled.setText(Logic.num(Logic.val(cs, "fled")));
        sSpins.setText(Logic.num(Logic.val(cs, "spins")));
        sXp.setText(Logic.num(Logic.val(cs, "xp")));
        sItems.setText(Logic.num(Logic.val(cs, "items")));

        // What the newer catcher adds (every part only when its key is there): stardust, the Star Piece, the balls.
        String dust = Logic.dustLine(s.state);
        int star = Logic.starPiece(s.state);
        if (dust.length() == 0 && star < 0) {
            extraRow.setVisibility(View.GONE);
        } else {
            extraRow.setVisibility(View.VISIBLE);
            dustText.setText(dust);
            if (star < 0) {
                spChip.setVisibility(View.GONE);
            } else {
                spChip.setVisibility(View.VISIBLE);
                if (spPainted != star) {
                    spPainted = star;
                    spChip.setText(star == 1 ? "Star Piece ON" : "Star Piece OFF");
                    spChip.setTextColor(star == 1 ? GREEN : AMBER);
                    spChip.setBackground(outlined(star == 1 ? CARD_ON : AMBER_FILL, star == 1 ? GREEN : AMBER, 12));
                }
            }
        }
        String[] balls = Logic.balls(s.state);
        if (balls == null) {
            ballsText.setVisibility(View.GONE);
        } else {
            boolean low = Integer.parseInt(balls[1]) == Logic.WAIT;
            ballsText.setVisibility(View.VISIBLE);
            ballsText.setText(balls[0]);
            ballsText.setTextColor(low ? AMBER : TEXT);
            ballsText.setTypeface(low ? Typeface.DEFAULT_BOLD : Typeface.DEFAULT);
        }
    }

    private void paintTile(Tile t, Snap s) {
        Flag f = t.flag;
        boolean on = f.shown.equals("1");
        if (t.painted != (on ? 1 : 0)) {
            t.painted = on ? 1 : 0;
            t.box.setBackground(on ? tappable(CARD_ON, GREEN, 16, 1.5f) : tappable(CARD, LINE, 16, 1f));
            t.toggle.set(on);
        }
        String rest;
        int restColor = on ? GREEN : DIMC;
        if (f.applying()) {
            rest = "applying...";
            restColor = AMBER;
        } else if (f.failed) {
            rest = "did not take -- tap again";
            restColor = RED;
        } else if (t == gymTile) {
            long gAge = s.gymMs > 0 ? Math.max(0, s.now - s.gymMs) : -1;
            long tapAgo = gymTapMs > 0 ? Math.max(0, s.now - gymTapMs) : -1;
            String[] g = Logic.gym(on, s.gym, gAge, tapAgo);
            rest = g[0];
            restColor = color(Integer.parseInt(g[1]));
        } else if (t == catchTile && on) {   // what the catcher itself reports: everything, or high stardust only
            long ageMs = s.stateMs > 0 ? Math.max(0, s.now - s.stateMs) : -1;
            rest = Logic.catchLine(s.state, ageMs >= 0 && ageMs <= Logic.STATE_STALE_MS);
        } else {
            rest = on ? t.onText : t.offText;
        }
        t.status.setText(two(on ? "ON" : "off", on ? GREEN : DIMC, rest, restColor));
    }

    private void paintBerries(Snap s) {
        berryBar.paint();
        line(berryStock, Logic.berryStock(s.state), color(Logic.berryStockTone(berryF.shown, s.state)));
    }

    private void paintDust(Snap s) {
        dustBar.paint();
        dustHint.setText(Logic.dustHint(dustF.shown, s.levels));
        long ageMs = s.stateMs > 0 ? Math.max(0, s.now - s.stateMs) : -1;
        long tapAgo = dustTapMs > 0 ? Math.max(0, s.now - dustTapMs) : -1;
        // Two things worth an amber line: the catcher's stardust list is old; the switch (the file) says one thing and
        // the running catcher reports another.
        String old = Logic.dustStale(s.state, ageMs >= 0 && ageMs <= Logic.STATE_STALE_MS);
        String warn = dustF.want != null ? ""
                : Logic.dustWarn(dustF.file, catchF.shown.equals("1"), s.state, ageMs, tapAgo);
        String both = old.length() > 0 && warn.length() > 0 ? old + "\n" + warn : old + warn;
        dustWarn.setText(both);
        dustWarn.setVisibility(both.length() > 0 ? View.VISIBLE : View.GONE);
    }

    private void paintToc(Snap s) {
        boolean setUp = s.tocExists;
        int en = setUp ? Logic.tocInt(s.toc, "enabled", 0) : 0, dry = setUp ? Logic.tocInt(s.toc, "dry", 1) : 1,
            iv = setUp ? Logic.tocInt(s.toc, "minIvPercent", 80) : 80;
        tocToggle.set(en == 1);
        tocIv.setText("Keep IV " + iv + "%+");
        if (tocDryPainted != dry) {
            tocDryPainted = dry;
            tocDry.setText(dry == 1 ? "Dry run: on" : "Dry run: off");
            tocDry.setTextColor(dry == 1 ? AMBER : DIMC);
            tocDry.setBackground(tappable(dry == 1 ? AMBER_FILL : Color.TRANSPARENT, dry == 1 ? AMBER : LINE, 14, 1f));
        }
        // Not set up = no settings file on the phone: nothing reads the card, so it must not look like it works. It
        // folds down to the one line that says so.
        tocRow1.setVisibility(setUp ? View.VISIBLE : View.GONE);
        tocRow2.setVisibility(setUp ? View.VISIBLE : View.GONE);
        tocNote.setVisibility(setUp ? View.GONE : View.VISIBLE);
    }

    private void paintAlerts() {
        boolean on = prefs.getBoolean(StatusService.K_ALERTS, true);
        boolean allowed = host == null || host.notificationsAllowed();
        // Without the phone's yes nothing can show -- no alert and no status in the shade -- so the tile is not drawn
        // as ON then, whatever the switch is set to: it is amber and a tap asks for the yes.
        int look = !allowed ? 2 : on ? 1 : 0;
        if (alertsTile.painted != look) {
            alertsTile.painted = look;
            alertsTile.box.setBackground(look == 1 ? tappable(CARD_ON, GREEN, 16, 1.5f)
                                       : look == 2 ? tappable(CARD, AMBER, 16, 1.5f) : tappable(CARD, LINE, 16, 1f));
            alertsTile.toggle.set(look == 1);
        }
        if (look == 2)
            alertsTile.status.setText(two("NOT ALLOWED YET", AMBER,
                    "Android has to allow this app's notifications first. Tap here to allow them.", AMBER));
        else if (look == 1)
            alertsTile.status.setText(two("ON", GREEN,
                    "a banner with sound when catching stops, the Star Piece runs out or the gym run stops", GREEN));
        else
            alertsTile.status.setText(two("off", DIMC, "no banner, no sound. The status in the notification shade stays.", DIMC));
    }

    /** While a switch is on and this screen is in front, the status notification's service runs (it stops itself two
     *  minutes after the last switch went off). Asked at most every 10 s; an off-screen picture never starts it.
     *  A running service is asked once more right after notifications were allowed: Android dropped what it posted
     *  until then, and it posts again only when its words change. */
    private void startStatus(Snap s) {
        if (!active || host == null) return;
        boolean allowed = host.notificationsAllowed();
        boolean justAllowed = allowed && !wasAllowed;
        wasAllowed = allowed;
        if (StatusService.running) {
            if (justAllowed) host.startStatus();
            return;
        }
        boolean on = catchF.shown.equals("1") || spinF.shown.equals("1") || perfectF.shown.equals("1")
                || tapF.shown.equals("1") || gymF.shown.equals("1");
        if (!on || s.now - statusAskedMs < 10000) return;
        statusAskedMs = s.now;
        host.startStatus();
    }

    private void paintReward(Snap s) {
        String[] r = Logic.reward(s.reward, s.rewardMs, rewardTapMs, s.now);
        enable(rewardBtn, r[2].equals("1"));
        line(rewardStatus, r[0], color(Integer.parseInt(r[1])));
    }

    private void paintCull(Snap s) {
        String[] c = Logic.cull(s.cull, s.cullMs, cullTapMs, s.now);
        enable(cullBtn, c[2].equals("1"));
        line(cullStatus, c[0], color(Integer.parseInt(c[1])));
    }

    // ---- taps -----------------------------------------------------------------------------------------------------

    /** Fire the control verb, then VERIFY the flag file holds the new value and retry -- a tap must never be silently
     *  lost. The screen shows the new value at once; if it never takes, the tile says so. */
    private void send(final Flag f, final String verb, final String want) {
        final int gen = ++f.gen;
        f.want = want;
        f.lastWant = want;
        f.wantUntil = System.currentTimeMillis() + 30000;
        f.failed = false;
        repaint();
        new Thread(new Runnable() {
            public void run() {
                boolean ok = false;
                for (int attempt = 0; attempt < 3 && !ok && f.gen == gen; attempt++) {
                    shell(intent(verb));
                    for (int i = 0; i < 12 && !ok && f.gen == gen; i++) {   // up to ~6 s for the flag to settle
                        sleep(500);
                        ok = f.norm(readFile(f.path)).equals(want);
                    }
                    if (ok) Log.i(TAG, "toggle " + verb + " confirmed");
                    else if (f.gen == gen) Log.w(TAG, "toggle " + verb + " did not take, retrying");
                }
                final boolean took = ok;
                main.post(new Runnable() {
                    public void run() {
                        if (f.gen == gen) {
                            f.want = null;
                            f.failed = !took;
                        }
                        refresh();   // show truth
                    }
                });
            }
        }, "ac-toggle").start();
    }

    private void onTile(Tile t) {
        boolean turnOn = !t.flag.shown.equals("1");
        long now = System.currentTimeMillis();
        if (t == gymTile) {
            if (turnOn) gymTapMs = now;
        } else if (turnOn) {
            catcherOnTapMs = now;
        }
        send(t.flag, turnOn ? t.onVerb : t.offVerb, turnOn ? "1" : "0");
    }

    private void onAlerts() {
        if (host != null && !host.notificationsAllowed()) {   // first things first: without a yes nothing shows at all
            host.askNotifications();
            return;
        }
        boolean on = prefs.getBoolean(StatusService.K_ALERTS, true);
        prefs.edit().putBoolean(StatusService.K_ALERTS, !on).apply();
        repaint();
    }

    /** One tap = one reward run. The button goes off here and stays off for as long as Logic.reward says a run is in
     *  flight; until 1.4 it came back after 4 s, a second tap started a second reward catcher on the same game, and
     *  the game crashed (2026-11-18 16:06). */
    private void onReward() {
        enable(rewardBtn, false);
        rewardTapMs = System.currentTimeMillis();
        line(rewardStatus, "sent -- starting...", AMBER);
        new Thread(new Runnable() {
            public void run() {
                shell(intent("rewards"));
                main.post(new Runnable() {
                    public void run() {
                        refresh();
                    }
                });
            }
        }, "ac-rewards").start();
    }

    private void onCull() {
        enable(cullBtn, false);
        cullTapMs = System.currentTimeMillis();
        line(cullStatus, "sent -- waiting for the PC...", AMBER);
        new Thread(new Runnable() {
            public void run() {
                shell("echo \"requested $(date +%s) $(date +%H:%M:%S)\" > " + CULL_REQ
                        + " && chmod 666 " + CULL_REQ + " && chcon u:object_r:shell_data_file:s0 " + CULL_REQ);
                main.post(new Runnable() {
                    public void run() {
                        refresh();
                    }
                });
            }
        }, "ac-cull").start();
    }

    /** Rewrite the whole Transfer-on-Catch file (it exists and is world-writable, or the card is greyed out). */
    private void tocWrite(int enabled, int dry, int minIv) {
        try {
            FileWriter w = new FileWriter(TOCFILE, false);
            w.write(Logic.tocJson(enabled, dry, minIv));
            w.close();
        } catch (Exception e) {
            Log.e(TAG, "toc write failed: " + e);
        }
        refresh();
    }

    private int tocNow(String key, int dflt) {
        return Logic.tocInt(readFile(TOCFILE), key, dflt);
    }

    void showHelp(boolean show) {
        helpBody.setVisibility(show ? View.VISIBLE : View.GONE);
        helpOpen.setText(show ? "hide" : "show");
    }

    // ---- building -------------------------------------------------------------------------------------------------

    private View header() {
        LinearLayout h = row();
        h.addView(text("PoGo Auto", 22, YELLOW, true), new LinearLayout.LayoutParams(0, WRAP, 1f));
        headDot = oval(FAINT);
        View dot = new View(ctx);
        dot.setBackground(headDot);
        LinearLayout.LayoutParams dl = new LinearLayout.LayoutParams(dp(9), dp(9));
        dl.setMargins(dp(8), 0, dp(7), 0);
        h.addView(dot, dl);
        headWords = text("", 12.5f, DIMC, false);
        headWords.setSingleLine(true);
        h.addView(headWords);
        return h;
    }

    private View statusCard() {
        LinearLayout card = box(CARD, LINE, 18, 14);
        numbers = new LinearLayout(ctx);
        numbers.setOrientation(LinearLayout.VERTICAL);

        // one huge number, the word beside it on the same baseline
        LinearLayout top = new LinearLayout(ctx);
        top.setOrientation(LinearLayout.HORIZONTAL);
        bigNum = text("-", 40, TEXT, true);
        bigNum.setSingleLine(true);
        bigNum.setIncludeFontPadding(false);
        top.addView(bigNum);
        bigWords = text("caught", 15, DIMC, false);
        bigWords.setSingleLine(true);
        bigWords.setEllipsize(TextUtils.TruncateAt.END);
        LinearLayout.LayoutParams bw = new LinearLayout.LayoutParams(0, WRAP, 1f);
        bw.setMargins(dp(9), 0, 0, 0);
        top.addView(bigWords, bw);
        numbers.addView(top);

        View rule = new View(ctx);
        rule.setBackgroundColor(LINE);
        LinearLayout.LayoutParams rl = new LinearLayout.LayoutParams(MATCH, Math.max(1, dp(1)));
        rl.setMargins(0, dp(9), 0, dp(9));
        numbers.addView(rule, rl);

        // four small stats; XP gets the widest column: with even columns a 7-digit XP ran into the ITEMS number
        LinearLayout stats = new LinearLayout(ctx);
        stats.setOrientation(LinearLayout.HORIZONTAL);
        stats.setBaselineAligned(false);
        sFled = stat(stats, "FLED", 0.8f);
        sSpins = stat(stats, "SPINS", 0.9f);
        sXp = stat(stats, "XP", 1.35f);
        sItems = stat(stats, "ITEMS", 0.95f);
        numbers.addView(stats);

        // stardust + the Star Piece chip (only when the catcher sends them)
        extraRow = row();
        dustText = text("", 13, TEXT, false);
        dustText.setSingleLine(true);
        dustText.setEllipsize(TextUtils.TruncateAt.END);
        extraRow.addView(dustText, new LinearLayout.LayoutParams(0, WRAP, 1f));
        spChip = text("", 11.5f, GREEN, true);
        spChip.setSingleLine(true);
        spChip.setPadding(dp(9), dp(4), dp(9), dp(4));
        LinearLayout.LayoutParams cl = new LinearLayout.LayoutParams(WRAP, WRAP);
        cl.setMargins(dp(8), 0, 0, 0);
        extraRow.addView(spChip, cl);
        extraRow.setVisibility(View.GONE);
        numbers.addView(extraRow, lp(MATCH, WRAP, 10, 0));

        ballsText = text("", 13, TEXT, false);
        ballsText.setSingleLine(true);
        ballsText.setEllipsize(TextUtils.TruncateAt.END);
        ballsText.setVisibility(View.GONE);
        numbers.addView(ballsText, lp(MATCH, WRAP, 6, 0));

        card.addView(numbers);
        return card;
    }

    private TextView stat(LinearLayout parent, String label, float weight) {
        LinearLayout cell = new LinearLayout(ctx);
        cell.setOrientation(LinearLayout.VERTICAL);
        TextView n = text("-", 16, TEXT, true);
        n.setSingleLine(true);
        cell.addView(n);
        TextView l = text(label, 10.5f, DIMC, false);
        l.setLetterSpacing(0.08f);
        l.setSingleLine(true);
        cell.addView(l, lp(MATCH, WRAP, 1, 0));
        parent.addView(cell, new LinearLayout.LayoutParams(0, WRAP, weight));
        return n;
    }

    /** A section label in small yellow caps, with an optional small note at its right end. */
    private View section(String name, TextView note) {
        LinearLayout r = row();
        TextView v = text(name, 11, YELLOW, true);
        v.setLetterSpacing(0.1f);
        v.setSingleLine(true);
        r.addView(v, new LinearLayout.LayoutParams(0, WRAP, 1f));
        if (note != null) r.addView(note);
        return r;
    }

    private LinearLayout.LayoutParams sectionLp() {
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(MATCH, WRAP);
        p.setMargins(dp(2), dp(14), dp(2), dp(7));
        return p;
    }

    /** One switch tile: tap anywhere on it. statusLines = how many lines its status may take before it is cut. */
    private Tile tile(String name, Flag f, String onVerb, String offVerb, String onText, String offText, int statusLines) {
        final Tile t = plainTile(name, statusLines);
        t.flag = f;
        t.onVerb = onVerb;
        t.offVerb = offVerb;
        t.onText = onText;
        t.offText = offText;
        t.box.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                tick(v);
                onTile(t);
            }
        });
        tiles.add(t);
        return t;
    }

    /** The views of a switch tile: its name top-left, a switch top-right, one status line at the bottom. Whoever makes
     *  it gives it its tap. */
    private Tile plainTile(String name, int statusLines) {
        Tile t = new Tile();
        t.box = new LinearLayout(ctx);
        t.box.setOrientation(LinearLayout.VERTICAL);
        t.box.setPadding(dp(12), dp(10), dp(12), dp(10));
        t.box.setMinimumHeight(dp(70));
        t.box.setClickable(true);

        LinearLayout top = new LinearLayout(ctx);
        top.setOrientation(LinearLayout.HORIZONTAL);
        top.setGravity(Gravity.TOP);
        TextView title = text(name, 14.5f, TEXT, false);
        title.setTypeface(medium);
        title.setMaxLines(2);                    // a name too wide for its tile wraps; it is never cut off
        top.addView(title, new LinearLayout.LayoutParams(0, WRAP, 1f));
        t.toggle = new Toggle(ctx);
        LinearLayout.LayoutParams tl = new LinearLayout.LayoutParams(dp(40), dp(23));
        tl.setMargins(dp(8), 0, 0, 0);
        top.addView(t.toggle, tl);
        t.box.addView(top);

        // Pushes the status line to the bottom of the tile. A Space, not a plain View: offered room it may or may not
        // use (an AT_MOST height), a View takes all of it and the tile would grow as tall as the screen.
        t.box.addView(new Space(ctx), new LinearLayout.LayoutParams(MATCH, 0, 1f));

        t.status = text("", 12, DIMC, false);
        t.status.setMaxLines(statusLines);
        t.status.setEllipsize(TextUtils.TruncateAt.END);
        t.box.addView(t.status, lp(MATCH, WRAP, 6, 0));
        return t;
    }

    /** Two tiles side by side, the same height. */
    private LinearLayout tileRow(Tile a, Tile b) {
        LinearLayout r = new LinearLayout(ctx);
        r.setOrientation(LinearLayout.HORIZONTAL);
        r.setBaselineAligned(false);
        LinearLayout.LayoutParams la = new LinearLayout.LayoutParams(0, MATCH, 1f);
        la.setMargins(0, 0, dp(5), 0);
        r.addView(a.box, la);
        LinearLayout.LayoutParams lb = new LinearLayout.LayoutParams(0, MATCH, 1f);
        lb.setMargins(dp(5), 0, 0, 0);
        r.addView(b.box, lb);
        return r;
    }

    /** A segmented bar bound to one flag file (Berries, High stardust only): one rounded bar, equal segments, the chosen one
     *  filled yellow. It shows what the file really holds, so a value that is none of the segments lights none. Under
     *  it sits a note that only shows while a tap is being applied or when it did not take. */
    private final class Bar {
        final Flag flag;
        final LinearLayout view;
        final TextView note;
        private final TextView[] btns;
        private final String[] vals;
        private String painted;

        Bar(Flag f, String[][] opts) {   // {the segment's label, the file value it stands for, its control verb}
            flag = f;
            view = new LinearLayout(ctx);
            view.setOrientation(LinearLayout.HORIZONTAL);
            view.setPadding(dp(4), dp(4), dp(4), dp(4));
            view.setBackground(rounded(CARD, LINE, 14, 1f));
            btns = new TextView[opts.length];
            vals = new String[opts.length];
            for (int i = 0; i < opts.length; i++) {
                final String val = opts[i][1], verb = opts[i][2];
                TextView b = centred(text(opts[i][0], 14, DIMC, true));
                b.setClickable(true);
                b.setOnClickListener(new View.OnClickListener() {
                    public void onClick(View v) {
                        if (flag.want == null && flag.shown.equals(val)) return;   // already there
                        tick(v);
                        if (flag == dustF) dustTapMs = System.currentTimeMillis();
                        send(flag, verb, val);
                    }
                });
                view.addView(b, new LinearLayout.LayoutParams(0, dp(40), 1f));
                btns[i] = b;
                vals[i] = val;
            }
            note = text("", 12, AMBER, false);
            note.setVisibility(View.GONE);
        }

        void paint() {
            String sel = flag.shown;
            if (!sel.equals(painted)) {
                painted = sel;
                for (int i = 0; i < btns.length; i++) {
                    boolean on = vals[i].equals(sel);
                    btns[i].setBackground(on ? rounded(YELLOW, 0, 10, 0f) : tappable(Color.TRANSPARENT, 0, 10, 0f));
                    btns[i].setTextColor(on ? INK : DIMC);
                }
            }
            if (flag.applying()) {
                line(note, "applying...", AMBER);
                note.setVisibility(View.VISIBLE);
            } else if (flag.failed) {
                line(note, "did not take -- tap again", RED);
                note.setVisibility(View.VISIBLE);
            } else {
                note.setVisibility(View.GONE);
            }
        }
    }

    /** Where a small note sits under a bar. */
    private LinearLayout.LayoutParams noteLp() {
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(MATCH, WRAP);
        p.setMargins(dp(3), dp(6), dp(3), 0);
        return p;
    }

    private View tocCard() {
        LinearLayout card = box(CARD, LINE, 16, 12);

        tocRow1 = row();
        TextView name = text("Tag junk as I catch it", 14.5f, TEXT, false);
        name.setTypeface(medium);
        name.setMaxLines(2);
        tocRow1.addView(name, new LinearLayout.LayoutParams(0, WRAP, 1f));
        tocToggle = new Toggle(ctx);
        LinearLayout.LayoutParams tl = new LinearLayout.LayoutParams(dp(40), dp(23));
        tl.setMargins(dp(8), 0, 0, 0);
        tocRow1.addView(tocToggle, tl);
        tocRow1.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                tocWrite(tocNow("enabled", 0) == 1 ? 0 : 1, tocNow("dry", 1), tocNow("minIvPercent", 80));
            }
        });
        card.addView(tocRow1);

        // IV threshold: anything at or ABOVE this is KEPT. Stepper buttons rather than a text field -- no keyboard here.
        tocRow2 = row();
        tocIv = text("Keep IV 80%+", 14, TEXT, false);
        tocIv.setSingleLine(true);
        tocIv.setEllipsize(TextUtils.TruncateAt.END);
        tocRow2.addView(tocIv, new LinearLayout.LayoutParams(0, WRAP, 1f));
        tocRow2.addView(stepBtn("-", -5), stepLp(0));
        tocRow2.addView(stepBtn("+", 5), stepLp(8));
        // Dry run: decisions are logged but no tag is written. Leave ON until the log looks right.
        tocDry = centred(text("Dry run: on", 12, AMBER, true));
        tocDry.setPadding(dp(11), 0, dp(11), 0);
        tocDry.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                tocWrite(tocNow("enabled", 0), tocNow("dry", 1) == 1 ? 0 : 1, tocNow("minIvPercent", 80));
            }
        });
        LinearLayout.LayoutParams dl = new LinearLayout.LayoutParams(WRAP, dp(40));
        dl.setMargins(dp(10), 0, 0, 0);
        tocRow2.addView(tocDry, dl);
        card.addView(tocRow2, lp(MATCH, WRAP, 10, 0));

        tocNote = text("Not set up on this phone -- nothing is tagged.", 12.5f, DIMC, false);
        tocNote.setVisibility(View.GONE);
        card.addView(tocNote);
        return card;
    }

    private LinearLayout.LayoutParams stepLp(int leftDp) {
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(dp(44), dp(40));
        p.setMargins(dp(leftDp), 0, 0, 0);
        return p;
    }

    private TextView stepBtn(String label, final int delta) {
        TextView b = centred(text(label, 17, TEXT, true));
        b.setIncludeFontPadding(false);
        b.setBackground(tappable(0xff1f2630, LINE, 12, 1f));
        b.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                int iv = tocNow("minIvPercent", 80) + delta;
                if (iv < 0) iv = 0;
                if (iv > 100) iv = 100;
                tocWrite(tocNow("enabled", 0), tocNow("dry", 1), iv);
            }
        });
        return b;
    }

    /** Catch Rewards | Cull Now, side by side, each with its last result in a small line under it. */
    private View actions() {
        LinearLayout r = new LinearLayout(ctx);
        r.setOrientation(LinearLayout.HORIZONTAL);
        r.setBaselineAligned(false);

        rewardBtn = button("Catch Rewards");
        rewardBtn.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                tick(v);
                onReward();
            }
        });
        rewardStatus = small();
        LinearLayout.LayoutParams la = new LinearLayout.LayoutParams(0, WRAP, 1f);
        la.setMargins(0, 0, dp(5), 0);
        r.addView(action(rewardBtn, rewardStatus), la);

        cullBtn = button("Cull Now");
        cullBtn.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                tick(v);
                onCull();
            }
        });
        cullStatus = small();
        LinearLayout.LayoutParams lb = new LinearLayout.LayoutParams(0, WRAP, 1f);
        lb.setMargins(dp(5), 0, 0, 0);
        r.addView(action(cullBtn, cullStatus), lb);
        return r;
    }

    private View action(TextView button, TextView status) {
        LinearLayout col = new LinearLayout(ctx);
        col.setOrientation(LinearLayout.VERTICAL);
        col.addView(button, new LinearLayout.LayoutParams(MATCH, dp(48)));
        LinearLayout.LayoutParams sl = lp(MATCH, WRAP, 6, 0);
        sl.setMargins(dp(3), dp(6), dp(3), 0);
        col.addView(status, sl);
        return col;
    }

    private TextView button(String label) {
        TextView b = centred(text(label, 14.5f, 0xffffffff, true));
        b.setBackground(tappable(BLUE, 0, 12, 0f));
        b.setClickable(true);
        return b;
    }

    private TextView small() {
        TextView v = text("", 12, DIMC, false);
        v.setMaxLines(6);
        v.setEllipsize(TextUtils.TruncateAt.END);
        return v;
    }

    /** The long descriptions, out of the way: one line that folds them out. */
    private View help() {
        LinearLayout col = new LinearLayout(ctx);
        col.setOrientation(LinearLayout.VERTICAL);

        LinearLayout bar = row();
        bar.setPadding(dp(2), dp(10), dp(2), dp(10));
        bar.addView(text("What each switch does", 13, DIMC, true), new LinearLayout.LayoutParams(0, WRAP, 1f));
        helpOpen = text("show", 12.5f, YELLOW, false);
        bar.addView(helpOpen);
        bar.setClickable(true);
        bar.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                showHelp(helpBody.getVisibility() != View.VISIBLE);
            }
        });
        col.addView(bar);

        final String[][] items = {
            {"Auto-Catch", "Throws at Pokemon in range on its own."},
            {"Auto-Spin", "Spins stops as you pass them. Skips ones already spun or cooling down."},
            {"Perfect Throw", "Every throw scores Excellent + curveball, including the ones you throw by hand."},
            {"Tap to Move", "Tap a spot on the map to move there, so you can reach things that are out of range."},
            {"Gym Battle", "A gym you open is battled until it is empty, then a shiny Gyarados goes in. An empty gym or a red gym with room gets one straight away. It never moves you to a gym. Runs on the phone."},
            {"High stardust only", "Catches only what pays more than a normal catch - evolved forms, bonus species and anything weather-boosted - plus every shiny. The list updates itself."},
            {"Berries", "What is fed before the throw. Pinap: a Pinap on every Pokemon. Razz: a Razz on the hard ones only. Both: Razz on the hard ones, Pinap on the rest. Never a Golden Razz or a Silver Pinap."},
            {"Transfer on Catch", "Tags junk the moment you catch it, so less piles up for the cull. It only tags; it never releases anything."},
            {"Catch Rewards", "Clears stacked Field Research reward encounters that piled up while your box was full. One run at a time: the button stays off until the run is done, and the catcher pauses for it. Switch Gym Battle off first."},
            {"Cull Now", "Asks the PC to run one cull. It only tags the Transfer pile; you release by hand. The PC must be on."},
            {"In the notification shade", "While a switch is on, a notification shows the catch count and has Catch, Spin and Gym buttons, so you can flip them without leaving the game. It stays for 30 minutes after the last switch went off, so Catch on is still one pull-down away."},
            {"Alerts", "A banner with sound when catching stops (storage full, no balls...), when the Star Piece runs out, or when the gym run stops. Once per change, never again while nothing changes."},
        };
        SpannableStringBuilder sb = new SpannableStringBuilder();
        for (int i = 0; i < items.length; i++) {
            int a = sb.length();
            sb.append(items[i][0]);
            sb.setSpan(new ForegroundColorSpan(TEXT), a, sb.length(), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
            sb.setSpan(new StyleSpan(Typeface.BOLD), a, sb.length(), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
            sb.append("\n").append(items[i][1]).append("\n\n");
        }
        sb.append("PoGo Auto " + VERSION);
        helpBody = text("", 12.5f, DIMC, false);
        helpBody.setText(sb);
        helpBody.setLineSpacing(dp(2), 1f);
        helpBody.setVisibility(View.GONE);
        LinearLayout.LayoutParams bl = lp(MATCH, WRAP, 2, 0);
        bl.setMargins(dp(2), dp(2), dp(2), 0);
        col.addView(helpBody, bl);
        return col;
    }

    // ---- small view helpers ---------------------------------------------------------------------------------------

    private int dp(float v) {
        return (int) (v * density + 0.5f);
    }

    /** Text sizes are sp: they follow the phone's font-size setting (1.15 on his phone), so no text sits in a box of a
     *  fixed pixel height unless the box is far taller than a line (the buttons). */
    private TextView text(String s, float sp, int color, boolean bold) {
        TextView v = new TextView(ctx);
        v.setText(s);
        v.setTextSize(sp);
        v.setTextColor(color);
        if (bold) v.setTypeface(Typeface.DEFAULT_BOLD);
        return v;
    }

    /** A one-line label centred in its box (a button, a pill, a segment). setMaxLines(1), NEVER setSingleLine: a
     *  single-line TextView is laid out a million pixels wide and only scrolled into place just before it is drawn in
     *  a window, so drawn off screen (RenderProbe) a centred one shows nothing -- 2026-11-18: the first picture had
     *  every button, stepper and berry segment blank. */
    private TextView centred(TextView v) {
        v.setGravity(Gravity.CENTER);
        v.setMaxLines(1);
        v.setEllipsize(TextUtils.TruncateAt.END);
        return v;
    }

    private void line(TextView v, String s, int color) {
        v.setText(s);
        v.setTextColor(color);
    }

    /** "ON - catching nearby": a bold coloured word, then " - " and the rest in its own colour. */
    private CharSequence two(String word, int wordColor, String rest, int restColor) {
        SpannableStringBuilder sb = new SpannableStringBuilder(word);
        sb.setSpan(new ForegroundColorSpan(wordColor), 0, sb.length(), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
        sb.setSpan(new StyleSpan(Typeface.BOLD), 0, sb.length(), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
        if (rest != null && rest.length() > 0) {
            int a = sb.length();
            sb.append(" - ").append(rest);
            sb.setSpan(new ForegroundColorSpan(restColor), a, sb.length(), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
        }
        return sb;
    }

    private int color(int tone) {
        return tone == Logic.GOOD ? GREEN : tone == Logic.WAIT ? AMBER : tone == Logic.BAD ? RED : DIMC;
    }

    private LinearLayout row() {
        LinearLayout r = new LinearLayout(ctx);
        r.setOrientation(LinearLayout.HORIZONTAL);
        r.setGravity(Gravity.CENTER_VERTICAL);
        return r;
    }

    private LinearLayout box(int fill, int stroke, float radiusDp, int padDp) {
        LinearLayout b = new LinearLayout(ctx);
        b.setOrientation(LinearLayout.VERTICAL);
        b.setPadding(dp(padDp), dp(padDp), dp(padDp), dp(padDp));
        b.setBackground(rounded(fill, stroke, radiusDp, 1f));
        return b;
    }

    private LinearLayout.LayoutParams lp(int w, int h, int topDp, int bottomDp) {
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(w, h);
        p.setMargins(0, dp(topDp), 0, dp(bottomDp));
        return p;
    }

    private GradientDrawable oval(int color) {
        GradientDrawable g = new GradientDrawable();
        g.setShape(GradientDrawable.OVAL);
        g.setColor(color);
        return g;
    }

    /** A rounded rectangle; strokeDp 0 = no outline. */
    private GradientDrawable rounded(int fill, int stroke, float radiusDp, float strokeDp) {
        GradientDrawable g = new GradientDrawable();
        g.setColor(fill);
        g.setCornerRadius(dp(radiusDp));
        if (strokeDp > 0) g.setStroke(Math.max(1, dp(strokeDp)), stroke);
        return g;
    }

    private GradientDrawable outlined(int fill, int stroke, float radiusDp) {
        return rounded(fill, stroke, radiusDp, 1f);
    }

    /** A rounded background that ripples when touched. */
    private Drawable tappable(int fill, int stroke, float radiusDp, float strokeDp) {
        GradientDrawable mask = new GradientDrawable();
        mask.setColor(Color.WHITE);
        mask.setCornerRadius(dp(radiusDp));
        return new RippleDrawable(ColorStateList.valueOf(0x33ffffff), rounded(fill, stroke, radiusDp, strokeDp), mask);
    }

    /** A tap you can feel (it follows the phone's own touch-feedback setting). */
    private void tick(View v) {
        try {
            v.performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY);
        } catch (Throwable t) {
            // no vibrator: nothing to feel
        }
    }

    private void enable(TextView b, boolean on) {
        b.setEnabled(on);
        b.setAlpha(on ? 1f : 0.45f);
    }

    // ---- the phone ------------------------------------------------------------------------------------------------

    /** One control verb, run by Termux as itself: catcher_ctl.sh owns the flag files. */
    static String intent(String arg) {
        return "am startservice --user 0 -n com.termux/com.termux.app.RunCommandService "
             + "-a com.termux.RUN_COMMAND "
             + "--es com.termux.RUN_COMMAND_PATH " + CTL + " "
             + "--esa com.termux.RUN_COMMAND_ARGUMENTS " + arg + " "
             + "--ez com.termux.RUN_COMMAND_BACKGROUND true";
    }

    static String shell(String cmd) {
        try {
            // feed the command over stdin: avoids arg-splitting differences between su builds
            Process p = Runtime.getRuntime().exec(new String[]{"su"});
            OutputStream os = p.getOutputStream();
            os.write((cmd + "\nexit\n").getBytes("UTF-8"));
            os.flush();
            os.close();
            BufferedReader r = new BufferedReader(new InputStreamReader(p.getInputStream()));
            String line, lastLine = "";
            while ((line = r.readLine()) != null) {
                if (line.trim().length() > 0) lastLine = line.trim();
            }
            p.waitFor();
            Log.i(TAG, "cmd=[" + cmd + "] out=[" + lastLine + "]");
            return lastLine;
        } catch (Exception e) {
            Log.e(TAG, "shell fail: " + e);
            return "";
        }
    }

    /** A small text file with its line breaks kept (readFile joins the lines into one). "" when it is not there. */
    static String readText(String path) {
        try {
            File f = new File(path);
            if (!f.exists()) return "";
            BufferedReader r = new BufferedReader(new FileReader(f));
            StringBuilder sb = new StringBuilder();
            String line;
            while ((line = r.readLine()) != null && sb.length() < 20000) sb.append(line).append('\n');
            r.close();
            return sb.toString();
        } catch (Exception e) {
            return "";
        }
    }

    /** Plain Java file read -- the app domain CAN read /data/local/tmp without any shell. */
    static String readFile(String path) {
        try {
            File f = new File(path);
            if (!f.exists()) return "";
            BufferedReader r = new BufferedReader(new FileReader(f));
            StringBuilder sb = new StringBuilder();
            String line;
            while ((line = r.readLine()) != null) sb.append(line);
            r.close();
            return sb.toString().trim();
        } catch (Exception e) {
            return "";
        }
    }

    static void sleep(long ms) {
        try {
            Thread.sleep(ms);
        } catch (InterruptedException e) {
            // carry on
        }
    }
}

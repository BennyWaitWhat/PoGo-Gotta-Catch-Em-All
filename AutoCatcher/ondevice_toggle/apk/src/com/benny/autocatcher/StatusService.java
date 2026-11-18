package com.benny.autocatcher;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.ServiceInfo;
import android.graphics.drawable.Icon;
import android.os.Build;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.IBinder;
import android.util.Log;
import java.io.File;
import java.util.HashMap;
import java.util.List;

/**
 * App 1.4: the catcher in the notification shade, so it can be read and switched without leaving the game.
 *
 * ONE ongoing notification (channel "Status", silent): the catch count, the rate and the Star Piece as its title
 * ("620 caught - 13.3/min - Star Piece OFF"), the why= problem as its line, and three buttons that flip Catch, Spin and
 * Gym. A button's label is what a tap will do ("Catch off"); it runs the same catcher_ctl.sh verb as the app's tile and
 * is verified the same way (the flag file must hold the new value).
 *
 * ALERTS (channel "Alerts", heads-up with sound), one per change and never repeated while the state holds: why= turning
 * into a reason that stops the catching, the Star Piece running out, the gym runner's line reading STOPPED. Alerts.java
 * decides when; the "Alerts" switch in the app (SharedPreferences) turns the posts off.
 *
 * It is a foreground service of type specialUse (the manifest says what for). The Activity starts it while a switch is
 * on; it stops itself after Catch, Spin, Perfect Throw, Tap to Move and Gym have all been off for 30 minutes (2 until
 * app 1.4: with everything off, "Catch on" was gone from the shade before he wanted it back). Without the
 * notification permission (Android 13+) it still runs, but nothing shows until notifications are allowed in the app.
 *
 * It reads the same world-readable files as the screen, every 5 s, with plain Java file I/O (this app cannot use a
 * shell for reads -- see MainActivity). No wake lock: with the phone asleep it sleeps too.
 */
public class StatusService extends Service {
    static final String TAG = Screen.TAG;
    static final String CH_STATUS = "status", CH_ALERTS = "alerts";
    static final int ID_STATUS = 1, ID_ALERT0 = 100;
    static final String PREFS = "autocatcher", K_ALERTS = "alerts", K_ALERT_STATE = "alert_state",
                        K_ASKED = "asked_notifications";
    static final long POLL_MS = 5000L, OFF_STOP_MS = 30 * 60000L;
    static final String ACTION_FLIP = "com.benny.autocatcher.FLIP";   // followed by ":<catch|spin|gym>:<1|0>"
    private static final String[] KINDS = {"storage", "balls", "flee", "silent", "version", "safety", "spinlimit",
                                           "star", "gym"};            // an alert's notification id = ID_ALERT0 + its place here

    /** True while the service lives (same process as the Activity, which asks before starting it again). */
    static volatile boolean running;

    /** One reading of the phone's files. */
    private static final class Reading {
        long now, stateAgeMs, gymAgeMs;
        boolean catchOn, spinOn, perfectOn, tapOn, gymOn, applesOn;
        String state = "", gym = "";
    }

    private NotificationManager nm;
    private SharedPreferences prefs;
    private HandlerThread thread;
    private Handler worker;
    private Alerts alerts;
    private final HashMap<String, String> pending = new HashMap<String, String>();   // a button tap being applied: name -> the value asked for
    private final HashMap<String, Integer> taps = new HashMap<String, Integer>();    // name -> the number of its newest tap (an older one gives up)
    private volatile String note = "";       // "Catch off did not take -- tap again", shown as the line for a while
    private volatile long noteUntil;
    private volatile long catcherOnTapMs, gymOnTapMs;   // when a button switched Catch or Spin / Gym on (0: none)
    private String lastSig = "";
    private long offSince, savedMs;
    private boolean stopping;

    /** Start it (from the Activity, which is in front then). Starting it twice is harmless. */
    static void ensure(Context c) {
        try {
            Intent i = new Intent(c, StatusService.class);
            if (Build.VERSION.SDK_INT >= 26) c.startForegroundService(i);
            else c.startService(i);
        } catch (Throwable t) {
            Log.w(TAG, "status service not started: " + t);
        }
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public void onCreate() {
        super.onCreate();
        nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        alerts = Alerts.load(prefs.getString(K_ALERT_STATE, ""));
        channels();
        thread = new HandlerThread("ac-status");
        thread.start();
        worker = new Handler(thread.getLooper());
        worker.postDelayed(poll, POLL_MS);
        running = true;
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        // Within 5 s of startForegroundService there must be a startForeground: do it first, from one quick reading.
        Notification first;
        String said;
        try {
            Reading r = read();
            first = build(r);
            String[] w = words(r);
            said = w[0] + " | " + w[1] + " | buttons: Catch " + (r.catchOn ? "off" : "on") + ", Spin "
                    + (r.spinOn ? "off" : "on") + ", Gym " + (r.gymOn ? "off" : "on");
        } catch (Throwable t) {
            Log.e(TAG, "status: first notification failed", t);
            first = plain("PoGo Auto", "");
            said = "(a bare notification: building the real one failed)";
        }
        if (!foreground(first)) {   // not allowed right now (a restart while the app is in the background): no half-alive service
            stopSelf();
            return START_NOT_STICKY;
        }
        // One line per start, so what the shade shows can be read with logcat (dumpsys has no notification text for an
        // app whose notifications are not allowed yet).
        Log.i(TAG, "status: in the shade: " + said + (nm.areNotificationsEnabled() ? "" : " -- HIDDEN: notifications are not allowed for this app yet"));
        String a = intent == null ? null : intent.getAction();
        if (a != null && a.startsWith(ACTION_FLIP + ":")) {
            String[] p = a.substring(ACTION_FLIP.length() + 1).split(":");
            if (p.length == 2 && (p[1].equals("1") || p[1].equals("0"))) flip(p[0], p[1]);
        }
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        running = false;
        stopping = true;
        try {
            worker.removeCallbacksAndMessages(null);
            thread.quitSafely();
            synchronized (alerts) {
                prefs.edit().putString(K_ALERT_STATE, alerts.save()).apply();
            }
        } catch (Throwable t) {
            Log.w(TAG, "status: stop: " + t);
        }
        super.onDestroy();
    }

    private boolean foreground(Notification n) {
        try {
            if (Build.VERSION.SDK_INT >= 34) startForeground(ID_STATUS, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
            else startForeground(ID_STATUS, n);
            return true;
        } catch (Throwable t) {
            Log.e(TAG, "status: startForeground refused: " + t);
            return false;
        }
    }

    private void channels() {
        if (Build.VERSION.SDK_INT < 26) return;
        NotificationChannel s = new NotificationChannel(CH_STATUS, "Status", NotificationManager.IMPORTANCE_LOW);
        s.setDescription("The catch count and the Catch / Spin / Gym buttons while a switch is on");
        s.setShowBadge(false);
        nm.createNotificationChannel(s);
        NotificationChannel a = new NotificationChannel(CH_ALERTS, "Alerts", NotificationManager.IMPORTANCE_HIGH);
        a.setDescription("Catching stopped, the Star Piece ran out, the gym run stopped");
        a.enableVibration(true);
        nm.createNotificationChannel(a);
    }

    // ---- the loop -------------------------------------------------------------------------------------------------

    private final Runnable poll = new Runnable() {
        public void run() {
            if (stopping) return;
            try {
                tick(true);
            } catch (Throwable t) {
                Log.e(TAG, "status: tick failed", t);
            }
            if (!stopping) worker.postDelayed(this, POLL_MS);
        }
    };

    /** The notification again, now (after a button tap). */
    private final Runnable push = new Runnable() {
        public void run() {
            if (stopping) return;
            try {
                tick(false);
            } catch (Throwable t) {
                Log.e(TAG, "status: push failed", t);
            }
        }
    };

    private void tick(boolean full) {
        Reading r = read();
        if (full) {
            // It lives while a switch is on, and 30 minutes longer.
            if (r.catchOn || r.spinOn || r.perfectOn || r.tapOn || r.gymOn) {
                offSince = 0;
            } else if (offSince == 0) {
                offSince = r.now;
            } else if (r.now - offSince >= OFF_STOP_MS) {
                Log.i(TAG, "status: every switch off for 30 minutes, stopping");
                stopping = true;
                if (Build.VERSION.SDK_INT >= 24) stopForeground(STOP_FOREGROUND_REMOVE);
                else stopForeground(true);
                stopSelf();
                return;
            }
        }
        if (note.length() > 0 && r.now > noteUntil) note = "";
        String sig = signature(r);
        if (!sig.equals(lastSig)) {            // post only what changed: the state line moves every ~10 s
            nm.notify(ID_STATUS, build(r));
            lastSig = sig;
        }
        if (full) alerts(r);
    }

    private Reading read() {
        Reading r = new Reading();
        r.now = System.currentTimeMillis();
        r.catchOn = on(Screen.CATCHFLAG, "catch");
        r.spinOn = on(Screen.SPINFLAG, "spin");
        r.perfectOn = on(Screen.PERFECTFLAG, null);
        r.tapOn = on(Screen.TAPFLAG, null);
        r.gymOn = on(Screen.GYMFLAG, "gym");
        r.applesOn = on(Screen.APPLEFLAG, null);
        r.state = Screen.readFile(Screen.STATE);
        long ms = new File(Screen.STATE).lastModified();
        r.stateAgeMs = ms > 0 ? Math.max(0, r.now - ms) : -1;
        r.gym = Screen.readFile(Screen.GYM_STATUS);
        ms = new File(Screen.GYM_STATUS).lastModified();
        r.gymAgeMs = ms > 0 ? Math.max(0, r.now - ms) : -1;
        return r;
    }

    /** A switch file, or the value a button tap is still applying to it. */
    private boolean on(String path, String name) {
        if (name != null) {
            synchronized (pending) {
                String want = pending.get(name);
                if (want != null) return want.equals("1");
            }
        }
        return Logic.flagNorm(Screen.readFile(path)).equals("1");
    }

    // ---- the notifications ------------------------------------------------------------------------------------------

    private String[] words(Reading r) {
        // Apples has no switch in the app, but it keeps the catcher alive like the other four (see Screen.paintStatus).
        boolean anyOn = r.catchOn || r.spinOn || r.perfectOn || r.tapOn || r.applesOn;
        long c = catcherOnTapMs, g = gymOnTapMs;
        String[] w = Logic.shade(anyOn, r.state, r.stateAgeMs, c > 0 ? Math.max(0, r.now - c) : -1,
                                 r.gymOn, r.gym, r.gymAgeMs, g > 0 ? Math.max(0, r.now - g) : -1);
        String n = note;
        if (n.length() > 0) {
            w[2] = w[2].length() > 0 ? n + "\n" + w[2] : n;
            w[1] = n;
        }
        return w;
    }

    private String signature(Reading r) {
        String[] w = words(r);
        return w[0] + "|" + w[1] + "|" + w[2] + "|" + r.catchOn + r.spinOn + r.gymOn;
    }

    private Notification.Builder builder(String channel) {
        return Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(this, channel) : new Notification.Builder(this);
    }

    private Notification plain(String title, String text) {
        return builder(CH_STATUS).setSmallIcon(R.drawable.ic_stat).setContentTitle(title).setContentText(text)
                .setOngoing(true).setOnlyAlertOnce(true).setShowWhen(false).setContentIntent(openApp()).build();
    }

    private Notification build(Reading r) {
        String[] w = words(r);
        Notification.Builder b = builder(CH_STATUS);
        b.setSmallIcon(R.drawable.ic_stat)
         .setContentTitle(w[0])
         .setContentText(w[1])
         .setOngoing(true)
         .setOnlyAlertOnce(true)
         .setShowWhen(false)
         .setColor(Screen.YELLOW)
         .setCategory(Notification.CATEGORY_STATUS)
         .setVisibility(Notification.VISIBILITY_PUBLIC)
         .setContentIntent(openApp());
        if (w[2].length() > 0) b.setStyle(new Notification.BigTextStyle().bigText(w[2]));
        if (Build.VERSION.SDK_INT < 26) b.setPriority(Notification.PRIORITY_LOW);
        if (Build.VERSION.SDK_INT >= 31) b.setForegroundServiceBehavior(Notification.FOREGROUND_SERVICE_IMMEDIATE);
        // A button says what a tap will do.
        b.addAction(action("Catch " + (r.catchOn ? "off" : "on"), "catch", r.catchOn ? "0" : "1"));
        b.addAction(action("Spin " + (r.spinOn ? "off" : "on"), "spin", r.spinOn ? "0" : "1"));
        b.addAction(action("Gym " + (r.gymOn ? "off" : "on"), "gym", r.gymOn ? "0" : "1"));
        return b.build();
    }

    private Notification.Action action(String label, String name, String want) {
        // The wanted value is part of the action, so "Catch off" can never deliver an older "Catch on".
        Intent i = new Intent(this, StatusService.class).setAction(ACTION_FLIP + ":" + name + ":" + want);
        int flags = PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE;
        PendingIntent pi = Build.VERSION.SDK_INT >= 26 ? PendingIntent.getForegroundService(this, 0, i, flags)
                                                       : PendingIntent.getService(this, 0, i, flags);
        return new Notification.Action.Builder((Icon) null, label, pi).build();
    }

    private PendingIntent openApp() {
        Intent i = getPackageManager().getLaunchIntentForPackage(getPackageName());
        if (i == null) i = new Intent(this, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        return PendingIntent.getActivity(this, 0, i, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }

    private void alerts(Reading r) {
        List<String[]> events;
        synchronized (alerts) {
            events = alerts.step(r.now, r.state, r.stateAgeMs, r.gym, r.gymAgeMs);
        }
        boolean enabled = prefs.getBoolean(K_ALERTS, true);
        for (int i = 0; i < events.size(); i++) {
            String[] e = events.get(i);
            int id = ID_ALERT0 + place(e[1]);
            if (!e[0].equals("post")) {
                nm.cancel(id);
            } else if (enabled) {      // switched off: the change still counts as seen, so nothing is owed later
                Notification.Builder b = builder(CH_ALERTS);
                b.setSmallIcon(R.drawable.ic_stat)
                 .setContentTitle(e[2])
                 .setContentText(e[3])
                 .setStyle(new Notification.BigTextStyle().bigText(e[3]))
                 .setAutoCancel(true)
                 .setColor(Screen.AMBER)
                 .setCategory(Notification.CATEGORY_ERROR)
                 .setVisibility(Notification.VISIBILITY_PUBLIC)
                 .setContentIntent(openApp());
                if (Build.VERSION.SDK_INT < 26) b.setPriority(Notification.PRIORITY_HIGH).setDefaults(Notification.DEFAULT_ALL);
                nm.notify(id, b.build());
                Log.i(TAG, "alert " + e[1] + ": " + e[3]);
            }
        }
        if (events.size() > 0 || r.now - savedMs > 60000) {   // kept across restarts, so a restart repeats no alert
            synchronized (alerts) {
                prefs.edit().putString(K_ALERT_STATE, alerts.save()).apply();
            }
            savedMs = r.now;
        }
    }

    private static int place(String kind) {
        for (int i = 0; i < KINDS.length; i++) if (KINDS[i].equals(kind)) return i;
        return KINDS.length;
    }

    // ---- a button tap -----------------------------------------------------------------------------------------------

    /** Catch / Spin / Gym from the notification: the same verb as the app's tile, verified the same way. */
    private void flip(final String name, final String want) {
        final String path, verb, label;
        if (name.equals("catch")) {
            path = Screen.CATCHFLAG;
            verb = want.equals("1") ? "catch-on" : "catch-off";
            label = "Catch";
        } else if (name.equals("spin")) {
            path = Screen.SPINFLAG;
            verb = want.equals("1") ? "spin-on" : "spin-off";
            label = "Spin";
        } else if (name.equals("gym")) {
            path = Screen.GYMFLAG;
            verb = want.equals("1") ? "gym-on" : "gym-off";
            label = "Gym";
        } else {
            return;
        }
        final int tap;
        synchronized (pending) {
            Integer last = taps.get(name);
            tap = last == null ? 1 : last + 1;
            taps.put(name, tap);
            pending.put(name, want);
        }
        if (want.equals("1")) {                  // "starting" instead of "not reporting" until it had time to answer
            if (name.equals("gym")) gymOnTapMs = System.currentTimeMillis();
            else catcherOnTapMs = System.currentTimeMillis();
        }
        note = "";
        worker.post(push);                       // the button shows its new label at once
        new Thread(new Runnable() {
            public void run() {
                // Like a tile's tap on the screen: fire the verb, VERIFY the switch file, retry -- three tries of about
                // six seconds. A newer tap on the same button ends this one, so two quick taps cannot fight.
                boolean ok = false;
                for (int attempt = 0; attempt < 3 && !ok && newest(name, tap); attempt++) {
                    Screen.shell(Screen.intent(verb));
                    for (int i = 0; i < 12 && !ok && newest(name, tap); i++) {
                        Screen.sleep(500);
                        ok = Logic.flagNorm(Screen.readFile(path)).equals(want);
                    }
                }
                if (!newest(name, tap)) return;  // a newer tap took over; it reports
                synchronized (pending) {
                    pending.remove(name);
                }
                if (!ok) {
                    note = label + (want.equals("1") ? " on" : " off") + " did not take -- tap again";
                    noteUntil = System.currentTimeMillis() + 30000;
                }
                Log.i(TAG, "notification " + verb + (ok ? " confirmed" : " did not take"));
                if (!stopping) worker.post(push);
            }
        }, "ac-flip").start();
    }

    private boolean newest(String name, int tap) {
        synchronized (pending) {
            Integer last = taps.get(name);
            return last != null && last == tap;
        }
    }
}

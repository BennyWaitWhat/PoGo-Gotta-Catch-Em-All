package com.benny.autocatcher;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * When a heads-up alert is due (app 1.4). No Android class in here, so a plain JVM can check it; StatusService feeds
 * it one reading of the phone's files every few seconds and posts what comes back.
 *
 * Three things alert, each ONCE per change and never again while the state holds:
 *   1. why= turning into a reason that stops the catching: storage full, no balls, ... (Logic.alertKind names them;
 *      "no Pokemon in range" and the other routine reasons are not alerts);
 *   2. the Star Piece running out: sp= going 1 -> 0;
 *   3. the gym runner's line reading STOPPED.
 *
 * "While the state holds" needs care for (1): the catcher's holds lapse and come back (storage full is a 60 s hold that
 * is re-armed by the next refused catch, so why= is empty for one report in between). A reason therefore counts as gone
 * only after it has been absent for its quiet time (Logic.alertQuietMs); until then its return is the same state.
 */
final class Alerts {
    final Map<String, Long> lastSeen = new HashMap<String, Long>();   // why kind -> when it was last there
    final Set<String> shown = new HashSet<String>();                  // kinds whose alert may still be in the shade
    int lastSp = -1;                                                  // the last sp= the catcher reported
    long lastSpMs;                                                    // ... and when
    String lastGymStop = "";                                          // the STOPPED line already alerted, digits out

    /** An sp= older than this is forgotten: a Star Piece that was on yesterday did not "run out" today. */
    static final long SP_FORGET_MS = 6 * 3600000L;

    /** One reading in, the events out: {"post", kind, title, text} or {"cancel", kind}.
     *  stateAgeMs / gymAgeMs = how old each file is (below 0: there is none). */
    List<String[]> step(long now, String state, long stateAgeMs, String gym, long gymAgeMs) {
        List<String[]> out = new ArrayList<String[]>();
        boolean reporting = state != null && state.length() > 0 && stateAgeMs >= 0 && stateAgeMs <= Logic.STATE_STALE_MS;
        if (reporting) {   // an old state line says nothing about now: no alert from it, and nothing is taken down
            String why = Logic.why(state);
            String kind = Logic.alertKind(why);
            if (kind.length() > 0) {
                Long seen = lastSeen.get(kind);
                if (seen == null || now - seen > Logic.alertQuietMs(kind))
                    out.add(new String[]{"post", kind, Logic.alertTitle(kind), Logic.cap(Logic.whyCore(why))});
                lastSeen.put(kind, now);
                shown.add(kind);
            }
            for (String k : new ArrayList<String>(shown)) {   // a reason that is gone: its alert leaves the shade
                if (k.equals("star") || k.equals("gym") || k.equals(kind)) continue;
                Long seen = lastSeen.get(k);
                if (seen == null || now - seen > Math.min(Logic.alertQuietMs(k), 3 * 60000L)) {
                    out.add(new String[]{"cancel", k});
                    shown.remove(k);
                }
            }
            int sp = Logic.starPiece(state);
            if (sp >= 0 && lastSpMs > 0 && now - lastSpMs > SP_FORGET_MS) lastSp = -1;
            if (sp == 0 && lastSp == 1) {
                String note = Logic.whyStar(why);
                out.add(new String[]{"post", "star", Logic.alertTitle("star"),
                                     note.length() > 0 ? Logic.cap(note) : "The last catch paid without a Star Piece."});
                shown.add("star");
            }
            if (sp == 1 && shown.remove("star")) out.add(new String[]{"cancel", "star"});
            if (sp >= 0) {
                lastSp = sp;
                lastSpMs = now;
            }
        }
        boolean fresh = gym != null && gym.length() > 0 && gymAgeMs >= 0 && gymAgeMs <= Logic.GYM_STALE_MS;
        if (fresh) {   // an old gym line is not shown anywhere either
            if (Logic.gymStopped(gym)) {
                String key = gym.replaceAll("[0-9]", "").trim();   // the same stop with a newer clock time is the same stop
                if (!key.equals(lastGymStop)) {
                    out.add(new String[]{"post", "gym", Logic.alertTitle("gym"), Logic.afterTime(gym)});
                    lastGymStop = key;
                    shown.add("gym");
                }
            } else if (lastGymStop.length() > 0) {          // it runs again: the next stop is a new one
                lastGymStop = "";
                if (shown.remove("gym")) out.add(new String[]{"cancel", "gym"});
            }
        }
        return out;
    }

    /** As text, one "key=value" per line, so the service can keep it across its own restarts (an alert must not repeat
     *  because of one). No line break at the end: Android's preferences file adds indentation after one. */
    String save() {
        StringBuilder sb = new StringBuilder();
        sb.append("sp=").append(lastSp);
        sb.append("\nspms=").append(lastSpMs);
        sb.append("\ngym=").append(lastGymStop.replace('\n', ' '));
        for (Map.Entry<String, Long> e : lastSeen.entrySet())
            sb.append("\nseen.").append(e.getKey()).append('=').append(e.getValue());
        for (String k : shown) sb.append("\nshown.").append(k).append("=1");
        return sb.toString();
    }

    static Alerts load(String text) {
        Alerts a = new Alerts();
        if (text == null) return a;
        String[] lines = text.split("\n");
        for (int i = 0; i < lines.length; i++) {
            int eq = lines[i].indexOf('=');
            if (eq <= 0) continue;
            String k = lines[i].substring(0, eq), v = lines[i].substring(eq + 1);
            try {
                if (k.equals("sp")) a.lastSp = Integer.parseInt(v.trim());
                else if (k.equals("spms")) a.lastSpMs = Long.parseLong(v.trim());
                else if (k.equals("gym")) a.lastGymStop = v.trim();
                else if (k.startsWith("seen.")) a.lastSeen.put(k.substring(5), Long.parseLong(v.trim()));
                else if (k.startsWith("shown.")) a.shown.add(k.substring(6).trim());
            } catch (NumberFormatException e) {
                // a line that does not parse is as good as not there
            }
        }
        return a;
    }
}

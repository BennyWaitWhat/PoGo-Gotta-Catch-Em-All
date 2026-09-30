#!/system/bin/sh
# Watch PoGo state every 10s; print PID, oom_score_adj, cpuset cgroup, freezer state, mem pressure
PKG=com.nianticlabs.pokemongo
START_PID=$(pidof $PKG)
echo "T=0s PID=$START_PID"
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30; do
    sleep 10
    P=$(pidof $PKG)
    if [ -z "$P" ]; then
        echo "T=$((i*10))s PID=DEAD (was $START_PID)"
        break
    fi
    if [ "$P" != "$START_PID" ]; then
        echo "T=$((i*10))s PID=CHANGED $START_PID -> $P"
        START_PID=$P
    fi
    OOM=$(cat /proc/$P/oom_score_adj 2>/dev/null)
    CG=$(grep cpuset /proc/$P/cgroup 2>/dev/null | sed 's|.*:cpuset:||')
    FROZ=$(cat /sys/fs/cgroup/uid_10468/pid_$P/cgroup.freeze 2>/dev/null)
    echo "T=$((i*10))s PID=$P oom=$OOM cpuset=$CG freeze=$FROZ"
done

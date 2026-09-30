#!/system/bin/sh
# Continuously pin PoGo oom_score_adj to -1000 (kernel-immune from LMK)
PKG=com.nianticlabs.pokemongo
while true; do
    P=$(pidof $PKG)
    if [ -n "$P" ]; then
        echo -1000 > /proc/$P/oom_score_adj 2>/dev/null
    fi
    sleep 2
done

#!/system/bin/sh
# Dump SMALL writable anon regions (under 50MB) from PoGo for offline grep
PID=$(pidof com.nianticlabs.pokemongo)
[ -z "$PID" ] && { echo "PoGo not running"; exit 1; }
echo "PID=$PID"

OUT=/sdcard/pogo_anon_dump
rm -rf "$OUT"
mkdir -p "$OUT"

cat /proc/$PID/maps | awk '$2 ~ /rw/ && $6 == "" || $6 ~ /\[anon/' | head -100 > $OUT/_regions.txt
n=0
total=0
while read line; do
    rng=$(echo "$line" | awk '{print $1}')
    perms=$(echo "$line" | awk '{print $2}')
    label=$(echo "$line" | awk '{for(i=6;i<=NF;i++) printf "%s ",$i; print ""}' | tr -d '[]:/ ' | cut -c1-30)
    [ -z "$label" ] && label="anon$n"
    a=$(echo "$rng" | cut -d- -f1)
    b=$(echo "$rng" | cut -d- -f2)
    # decimal sizes
    start=$((0x$a))
    end=$((0x$b))
    size=$((end - start))
    [ $size -gt 52428800 ] && continue   # skip > 50MB
    [ $size -lt 4096 ] && continue
    n=$((n+1))
    f="$OUT/${n}_${label}_${a}_${size}.bin"
    dd if=/proc/$PID/mem bs=4096 skip=$((start/4096)) count=$((size/4096)) of="$f" 2>/dev/null
    if [ -s "$f" ]; then
        total=$((total + size))
    else
        rm -f "$f"
    fi
    [ $n -gt 80 ] && break
done < $OUT/_regions.txt

echo "Dumped $n regions, ~$((total/1048576)) MB"
ls -la "$OUT" | head -10

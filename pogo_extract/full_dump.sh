#!/system/bin/sh
# Dump ALL writable anon regions for tag search
PID=$(pidof com.nianticlabs.pokemongo)
[ -z "$PID" ] && { echo "PoGo not running"; exit 1; }
echo "PID=$PID"

OUT=/sdcard/pogo_full_dump
rm -rf "$OUT"
mkdir -p "$OUT"

# All writable regions (rw, no file backing OR named anon)
grep -E '^[0-9a-f]+-[0-9a-f]+ rw' /proc/$PID/maps > $OUT/_regions.txt
N=$(wc -l < $OUT/_regions.txt)
echo "Total rw regions: $N"

n=0
total=0
while read line; do
  rng=$(echo "$line" | awk '{print $1}')
  a=$(echo "$rng" | cut -d- -f1)
  b=$(echo "$rng" | cut -d- -f2)
  start=$((0x$a))
  end=$((0x$b))
  size=$((end - start))
  [ $size -lt 4096 ] && continue
  [ $size -gt 268435456 ] && continue   # skip > 256MB to avoid OOM
  n=$((n+1))
  f="$OUT/${n}_${a}_${size}.bin"
  dd if=/proc/$PID/mem bs=4096 skip=$((start/4096)) count=$((size/4096)) of="$f" 2>/dev/null
  if [ -s "$f" ]; then
    total=$((total + size))
  else
    rm -f "$f"
  fi
done < $OUT/_regions.txt

echo "Dumped $n regions, ~$((total/1048576)) MB total"

#!/system/bin/sh
PID=$(pidof com.nianticlabs.pokemongo)
[ -z "$PID" ] && { echo "PoGo not running"; exit 1; }
echo "PID=$PID"

# Use 'strings -el' to extract UTF-16-LE strings from each rw region
# Then grep for tag names (existing + the test we tried to add)
# Include readable (rw and r--p) regions
grep -E '^[0-9a-f]+-[0-9a-f]+ r' /proc/$PID/maps > /tmp/_regions.txt
N=0
HITS=0
while read line; do
  rng=$(echo "$line" | awk '{print $1}')
  a=$(echo "$rng" | cut -d- -f1)
  b=$(echo "$rng" | cut -d- -f2)
  start=$(printf "%d" 0x$a)
  end=$(printf "%d" 0x$b)
  size=$((end - start))
  [ $size -lt 4096 ] && continue
  [ $size -gt 268435456 ] && continue
  N=$((N + 1))
  # Stream dd to strings to grep
  RESULT=$(dd if=/proc/$PID/mem bs=4096 skip=$((start/4096)) count=$((size/4096)) 2>/dev/null \
    | strings -el 2>/dev/null \
    | grep -E '^(TX-TEST|AUTO-TX|TeamEevee|Hundos|Nundos|MegaHundos|Shinyyy|Mega|Trade|G-MAX|Trade to Osiris|HUUUGE|Location Card|UL|0-15-15|U)$')
  if [ -n "$RESULT" ]; then
    echo "REGION 0x$a (size $size):"
    echo "$RESULT" | sort -u
    HITS=$((HITS + 1))
  fi
done < /tmp/_regions.txt

echo "---"
echo "Scanned $N regions, $HITS regions had tag hits"

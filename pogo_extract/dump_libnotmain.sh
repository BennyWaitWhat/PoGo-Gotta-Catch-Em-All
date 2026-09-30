#!/system/bin/sh
# Dump libnotmain.so memory regions atomically.
# Find PID, find region, dump -- all in one breath so PID can't go stale between steps.

PID=$(pidof com.nianticlabs.pokemongo)
if [ -z "$PID" ]; then
  echo "ERR: PoGo not running"
  exit 1
fi
echo "PID=$PID"

MAPS=$(grep notmain /proc/$PID/maps 2>/dev/null)
if [ -z "$MAPS" ]; then
  echo "ERR: libnotmain.so not loaded into PID $PID"
  exit 2
fi
echo "MAPS:"
echo "$MAPS"

# Parse each region. format: "START-END perm offset dev inode path"
echo "$MAPS" | while read line; do
  RANGE=$(echo "$line" | awk '{print $1}')
  PERM=$(echo "$line" | awk '{print $2}')
  START_HEX=$(echo "$RANGE" | cut -d- -f1)
  END_HEX=$(echo "$RANGE" | cut -d- -f2)
  START_DEC=$(printf "%d" 0x$START_HEX)
  END_DEC=$(printf "%d" 0x$END_HEX)
  LEN=$((END_DEC - START_DEC))
  case "$PERM" in
    r-xp) NAME=text ;;
    r--p) NAME=rodata ;;
    rw-p) NAME=data ;;
    *) NAME=other ;;
  esac
  OUT=/sdcard/lnm_${NAME}.bin
  echo "Dumping $NAME: 0x$START_HEX..0x$END_HEX ($LEN bytes) to $OUT"
  dd if=/proc/$PID/mem of=$OUT bs=4096 iflag=skip_bytes,count_bytes skip=$START_DEC count=$LEN 2>&1 | tail -1
  ls -la $OUT
done
echo "DONE"

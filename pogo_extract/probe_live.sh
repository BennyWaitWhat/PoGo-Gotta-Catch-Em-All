#!/system/bin/sh
# Read-only probe of live PoGo state. Pushed to phone, run as root.
PID=$(pidof com.nianticlabs.pokemongo)
[ -z "$PID" ] && { echo "PoGo not running"; exit 1; }
echo "PID=$PID"

# 1. List rw heap regions
echo "--- regions ---"
grep -E "rw-p .* (\\[anon:|\\[heap\\])" /proc/$PID/maps | head -30

# 2. Probe specific small region for printable strings via dd from /proc/PID/mem
echo "--- scan small dalvik space ---"
# Pull pgorelease URL search via /sdcard handoff
mkdir -p /sdcard/pogo_probe
echo "Memory size: $(grep -c rw-p /proc/$PID/maps) writable regions"

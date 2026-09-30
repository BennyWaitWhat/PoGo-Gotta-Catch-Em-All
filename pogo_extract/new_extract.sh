#!/bin/bash
# Fresh full extraction for new PID
PID=29663
ADB="adb -s 100.98.158.56:5555"
mkdir -p pogo_dump2 pogo_anon2

# Get fresh maps
$ADB shell "su -c 'cat /proc/$PID/maps'" > pogo_maps2.txt

echo "Maps lines: $(wc -l < pogo_maps2.txt)"

# Filter to RW, non-stack, non-shared anon mappings
grep -E '^[0-9a-f]+-[0-9a-f]+ rw-p' pogo_maps2.txt | head -100

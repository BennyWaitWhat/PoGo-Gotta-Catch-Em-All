#!/bin/bash
# Dump ALL rw-p anonymous regions for fresh PID
PID=29663
ADB="adb -s 100.98.158.56:5555"
mkdir -p pogo_dump3

# Filter rw-p, anon (no path or anon:something), exclude stack and gpu/dalvik
grep -E '^[0-9a-f]+-[0-9a-f]+ rw-p' pogo_maps2.txt | \
  awk '{
    if (NF == 5) print $1, "(unnamed)"      # anon, no name
    else if ($6 ~ /^\[anon:scudo/) print $1, "scudo"
    else if ($6 ~ /^\[anon:libc_malloc/) print $1, "libc_malloc"
    else if ($6 ~ /^\[anon:dalvik/) next
    else if ($6 ~ /^\[anon:.bss\]$/) next
    else if ($6 ~ /^\[stack/) next
    else if ($6 ~ /^\[anon:.*\]$/) print $1, $6
    else if ($6 ~ /\.so$/) next
    else if ($6 ~ /\.apk$/) next
    else if ($6 ~ /\.dex$/) next
    else if ($6 ~ /\.oat$/) next
    else if ($6 ~ /\.art$/) next
    else if ($6 ~ /\.ttf$/) next
    else if ($6 ~ /font/) next
    else print $1, $6
  }' | head -300 > regions_to_dump.txt
wc -l regions_to_dump.txt
head -20 regions_to_dump.txt
echo "---"

# Dump each region
i=0
total_size=0
while read -r addr label; do
  start_hex=$(echo "$addr" | cut -d- -f1)
  end_hex=$(echo "$addr" | cut -d- -f2)
  start_dec=$((16#$start_hex))
  end_dec=$((16#$end_hex))
  size=$((end_dec - start_dec))
  if [ $size -lt 65536 ]; then continue; fi  # Skip < 64KB
  if [ $size -gt 268435456 ]; then continue; fi  # Skip > 256MB

  count=$((size / 4096))
  skip=$((start_dec / 4096))

  out_name="r$(printf %03d $i)_0x${start_hex}.bin.gz"

  $ADB shell "su -c 'dd if=/proc/$PID/mem bs=4096 skip=$skip count=$count status=none 2>/dev/null | gzip > /data/local/tmp/_dump.bin.gz'" 2>/dev/null
  $ADB pull /data/local/tmp/_dump.bin.gz pogo_dump3/$out_name 2>/dev/null > /dev/null
  $ADB shell "rm /data/local/tmp/_dump.bin.gz" 2>/dev/null > /dev/null

  i=$((i+1))
  total_size=$((total_size + size))
  if [ $((i % 10)) -eq 0 ]; then
    echo "  [$i] dumped $out_name (size=${size}, total=${total_size})"
  fi
done < regions_to_dump.txt
echo "Total: $i regions, ${total_size} bytes"

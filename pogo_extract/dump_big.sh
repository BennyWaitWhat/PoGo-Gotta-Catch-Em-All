#!/bin/bash
# Dump all big rw-p anon regions in parallel batches
PID=29663
ADB="adb -s 100.98.158.56:5555"
mkdir -p pogo_dump3
rm -f pogo_dump3/*.bin.gz

# Get list of regions: addr_range size name
awk '{
  if ($2 != "rw-p") next
  n = split($1, a, "-")
  if (n != 2) next
  start = strtonum("0x" a[1])
  end = strtonum("0x" a[2])
  size = end - start
  if (size < 65536) next
  if (size > 268435456) next  # cap 256MB
  bad = 0
  if (NF >= 6) {
    name = $6
    if (name ~ /\.so$|\.apk$|\.dex$|\.oat$|\.art$|\.ttf$|\.vdex$|font|dalvik|^\[stack|^\[anon:\.bss|\.profil/) bad = 1
  }
  if (bad) next
  print $1
}' pogo_maps2.txt > regions_big.txt

echo "Regions to dump: $(wc -l < regions_big.txt)"

i=0
while IFS= read -r addr; do
  start_hex=$(echo "$addr" | cut -d- -f1)
  end_hex=$(echo "$addr" | cut -d- -f2)
  start_dec=$((16#$start_hex))
  end_dec=$((16#$end_hex))
  size=$((end_dec - start_dec))
  count=$((size / 4096))
  skip=$((start_dec / 4096))
  out_name="r$(printf %03d $i)_0x${start_hex}.bin.gz"

  $ADB shell "su -c 'dd if=/proc/$PID/mem bs=4096 skip=$skip count=$count status=none 2>/dev/null | gzip > /data/local/tmp/_dump.bin.gz; chmod 644 /data/local/tmp/_dump.bin.gz'" >/dev/null 2>&1
  $ADB pull /data/local/tmp/_dump.bin.gz pogo_dump3/$out_name >/dev/null 2>&1
  $ADB shell "rm -f /data/local/tmp/_dump.bin.gz" >/dev/null 2>&1

  if [ -f pogo_dump3/$out_name ]; then
    fsize=$(stat -c%s pogo_dump3/$out_name 2>/dev/null || stat -f%z pogo_dump3/$out_name 2>/dev/null)
    echo "[$i] $out_name uncompressed=$size compressed=$fsize"
  else
    echo "[$i] $out_name FAILED"
  fi
  i=$((i+1))
done < regions_big.txt
echo "Done. Dumped $i regions."
ls pogo_dump3/ | wc -l
du -sh pogo_dump3/

#!/system/bin/sh
PID=$1
echo "Scanning PID $PID memory for tag names..."
for tag in "TX-TEST" "AUTO-TX" "TeamEevee" "Hundos" "Nundos" "MegaHundos" "Shinyyy"; do
  N=$(grep -aoE "${tag}" /proc/$PID/mem 2>/dev/null | wc -l)
  printf "%-15s %s occurrences\n" "$tag" "$N"
done

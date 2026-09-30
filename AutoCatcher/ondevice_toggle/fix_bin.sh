PREFIX=/data/data/com.termux/files/usr
n=0; c=0; s=0
for f in "$PREFIX"/bin/*; do
  [ -L "$f" ] || continue
  real=$(readlink -f "$f" 2>/dev/null)
  if [ ! -f "$real" ]; then s=$((s+1)); continue; fi
  rm -f "$f"
  if ln "$real" "$f" 2>/dev/null; then
    n=$((n+1))
  elif cp -L "$real" "$f" 2>/dev/null; then
    chown 10762:10762 "$f"; chmod 0700 "$f"; c=$((c+1))
  fi
done
echo "hardlinked=$n copied=$c skipped=$s"
ls -l "$PREFIX"/bin/clang "$PREFIX"/bin/python 2>&1

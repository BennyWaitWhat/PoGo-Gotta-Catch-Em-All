PREFIX=/data/data/com.termux/files/usr
APPLIBS=/data/data/com.termux/files/home/applibs
rm -rf "$APPLIBS"; mkdir -p "$APPLIBS"
n=0
for f in "$PREFIX"/lib/*.so*; do
  [ -L "$f" ] || continue
  if cp -L "$f" "$APPLIBS/$(basename "$f")" 2>/dev/null; then n=$((n+1)); fi
done
chown -R 10762:10762 "$APPLIBS" 2>/dev/null
chmod -R 0755 "$APPLIBS"
echo "copied $n dereferenced libs into applibs"
ls "$APPLIBS" | grep -iE 'expat|c\+\+|ffi|python' 2>/dev/null
echo "total files: $(ls "$APPLIBS" | wc -l)"

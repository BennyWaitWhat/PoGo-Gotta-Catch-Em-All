PREFIX=/data/data/com.termux/files/usr
fix() {
  for f in "$1"/*; do
    if [ -L "$f" ]; then
      real=$(readlink -f "$f" 2>/dev/null)
      if [ -f "$real" ]; then
        rm -f "$f"
        ln "$real" "$f" 2>/dev/null || { cp -L "$real" "$f"; chown 10762:10762 "$f"; chmod 0755 "$f"; }
      fi
    elif [ -d "$f" ]; then
      fix "$f"
    fi
  done
}
fix "$PREFIX/libexec"
echo "=== libexec/termux-api now ==="
ls -l "$PREFIX/libexec/termux-api" 2>/dev/null

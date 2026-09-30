PREFIX=/data/data/com.termux/files/usr
HOME=/data/data/com.termux/files/home
export PATH=$PREFIX/bin:/system/bin
SRC=/data/local/tmp/pogo
DST=$HOME/pogo
rm -rf "$DST"
mkdir -p "$DST/system/scripts/game_write"
mkdir -p "$DST/system/analysis/pokemod"
cp "$SRC/pogo_il2cpp.py" "$DST/pogo_il2cpp.py"
cp "$SRC/system/scripts/game_write/catch_loop_fast.py" "$DST/system/scripts/game_write/catch_loop_fast.py"
cp "$SRC/system/scripts/game_write/catch_phone.py" "$DST/system/scripts/game_write/catch_phone.py"
cp "$SRC/system/analysis/pokemod/last_stardust.json" "$DST/system/analysis/pokemod/last_stardust.json" 2>/dev/null
echo "=== files in ~/pogo ==="
find "$DST" -type f

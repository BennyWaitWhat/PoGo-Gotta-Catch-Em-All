export PREFIX=/data/data/com.termux/files/usr
export LD_LIBRARY_PATH=$PREFIX/lib
LOG=/data/data/com.termux/files/home/fixtest.log
{
echo "ctx: $(id)"
cd "$PREFIX/lib"
ln -sf libexpat.so.1.12.1 libexpat.so.1; echo "ln libexpat rc=$?"
echo "readlink libexpat.so.1 (in-app) = $(readlink libexpat.so.1 2>&1)"
cd "$PREFIX/bin"
ln -sf python3.13 python; ln -sf python3.13 python3
echo "readlink python (in-app) = $(readlink python 2>&1)"
echo "=== import xmlrpc (needs pyexpat -> libexpat.so.1) ==="
"$PREFIX/bin/python3.13" -c "import xmlrpc.client; print('XMLRPC_OK')" 2>&1
echo "=== python via recreated symlink ==="
python --version 2>&1
} > "$LOG" 2>&1

export PREFIX=/data/data/com.termux/files/usr
export PATH=$PREFIX/bin:/system/bin
echo "=== libexpat files in lib ==="
ls -l "$PREFIX"/lib/libexpat* 2>&1
echo "=== dpkg expat ==="
dpkg -l 2>/dev/null | grep -i expat
echo "=== what soname does pyexpat want ==="
( readelf -d "$PREFIX"/lib/python3.13/lib-dynload/pyexpat.cpython-313-aarch64-linux-android.so 2>/dev/null || objdump -p "$PREFIX"/lib/python3.13/lib-dynload/pyexpat.cpython-313-aarch64-linux-android.so 2>/dev/null ) | grep -i 'NEEDED\|expat'
echo "=== deps section of build log ==="
sed -n '/pkg deps/,/deps rc/p' /data/data/com.termux/files/home/frida_build.log 2>/dev/null | grep -iE 'expat|Setting up|Unpacking|rc=|Unable|[Ee]rror|newest|Get:' | tail -30

export PATH=/data/data/com.termux/files/usr/bin:/system/bin
L=/data/data/com.termux/files/usr/var/lib/apt/lists
echo "=== Packages list files present ==="
ls "$L" | grep -i package
echo "=== any 'frida' anywhere in lists ==="
grep -ril frida "$L" 2>/dev/null
echo "=== Package: names containing frida ==="
grep -rhi '^Package:' "$L" 2>/dev/null | grep -i frida
echo "=== full frida stanzas (name/version/depends/filename) ==="
for f in "$L"/*Packages*; do
  awk 'BEGIN{RS="";} /[Ff]rida/{print; print "--------"}' "$f"
done 2>/dev/null | grep -iE '^Package:|^Version:|^Depends:|^Filename:|^Description:|----' | head -60

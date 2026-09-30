export PATH=/data/data/com.termux/files/usr/bin:/system/bin
tr -d '\r' < /data/local/tmp/install_frida2.sh > /data/data/com.termux/files/home/install_frida2.sh
chmod 755 /data/data/com.termux/files/home/install_frida2.sh
echo "=== staged build script ==="
ls -l /data/data/com.termux/files/home/install_frida2.sh
wc -l /data/data/com.termux/files/home/install_frida2.sh
head -3 /data/data/com.termux/files/home/install_frida2.sh

export PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export LD_LIBRARY_PATH=$HOME/applibs:$PREFIX/lib
export PATH=$PREFIX/bin:/system/bin
"$PREFIX/bin/python3.13" /data/local/tmp/phone_frida_test.py > "$HOME/app_connect_test.log" 2>&1
echo "exit=$?" >> "$HOME/app_connect_test.log"

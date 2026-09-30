export PATH=/data/data/com.termux/files/usr/bin:/system/bin
HOME=/data/data/com.termux/files/home
mkdir -p "$HOME/.termux"
printf 'allow-external-apps=true\n' > "$HOME/.termux/termux.properties"
tr -d '\r' < /data/local/tmp/install_frida.sh > "$HOME/install_frida.sh"
chmod 755 "$HOME/install_frida.sh"
echo "=== staged ==="
ls -l "$HOME/install_frida.sh" "$HOME/.termux/termux.properties"
echo "=== shebang ==="
head -1 "$HOME/install_frida.sh"

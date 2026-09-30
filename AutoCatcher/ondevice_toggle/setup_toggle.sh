PREFIX=/data/data/com.termux/files/usr
HOME=/data/data/com.termux/files/home
export PATH=$PREFIX/bin:/system/bin
cp /data/local/tmp/catcher_ctl.sh "$HOME/pogo/catcher_ctl.sh"
cp /data/local/tmp/run_catch.sh "$HOME/pogo/run_catch.sh"
chmod 755 "$HOME/pogo/catcher_ctl.sh" "$HOME/pogo/run_catch.sh"
mkdir -p "$HOME/.termux/boot"
cp /data/local/tmp/10-catcher-toggle.sh "$HOME/.termux/boot/10-catcher-toggle.sh"
chmod 755 "$HOME/.termux/boot/10-catcher-toggle.sh"
echo "=== deployed ==="
ls -l "$HOME/pogo/catcher_ctl.sh" "$HOME/pogo/run_catch.sh" "$HOME/.termux/boot/10-catcher-toggle.sh"

export PATH=/data/data/com.termux/files/usr/bin:/system/bin
LOG=/data/data/com.termux/files/home/noti_test.log
{
echo "=== post_on exact (with --ongoing) ==="
termux-notification --id 9911 --ongoing --alert-once --title "Auto-Catcher: ON" --content "Catching. Tap TURN OFF." --button1 "TURN OFF" --button1-action "/data/data/com.termux/files/home/pogo/catcher_ctl.sh stop"
echo "rc_ongoing=$?"
} > "$LOG" 2>&1

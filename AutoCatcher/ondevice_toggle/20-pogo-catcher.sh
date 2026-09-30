#!/data/data/com.termux/files/usr/bin/bash
# Termux:Boot -- after a reboot, bring the catcher back ONLY if one of your toggles was left on.
# `reconcile` starts nothing when every toggle is off, and its lock makes a second boot broadcast a no-op.
export HOME=/data/data/com.termux/files/home
exec /data/data/com.termux/files/usr/bin/bash "$HOME/pogo/catcher_ctl.sh" reconcile

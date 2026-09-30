#!/data/data/com.termux/files/usr/bin/bash
export PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH=$PREFIX/bin:$PREFIX/bin/applets:/system/bin
export LD_LIBRARY_PATH=$PREFIX/lib
LOG=$HOME/frida_install.log
: > "$LOG"
echo "=== install start ===" >> "$LOG"
echo "id: $(id)" >> "$LOG"
yes | pkg update -y >> "$LOG" 2>&1
echo "--- pkg update rc=$? ---" >> "$LOG"
yes | pkg install -y tur-repo >> "$LOG" 2>&1
echo "--- tur-repo rc=$? ---" >> "$LOG"
yes | apt update -y >> "$LOG" 2>&1
echo "--- apt update(TUR) rc=$? ---" >> "$LOG"
yes | pkg install -y frida-tools >> "$LOG" 2>&1
echo "--- frida-tools rc=$? ---" >> "$LOG"
python -c "import frida; print('FRIDA_OK', frida.__version__)" >> "$LOG" 2>&1
echo "--- import rc=$? ---" >> "$LOG"
echo "=== install end ===" >> "$LOG"

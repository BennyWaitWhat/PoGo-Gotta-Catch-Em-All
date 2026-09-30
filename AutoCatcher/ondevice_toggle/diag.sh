export PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH=$PREFIX/bin:$PREFIX/bin/applets:/system/bin
export LD_LIBRARY_PATH=$PREFIX/lib
LOG=$HOME/diag.log
{
echo "=== ctx id: $(id 2>/dev/null) ==="
echo "PATH=$PATH"
echo "--- ls python* ---"
ls -l "$PREFIX"/bin/python* 2>&1
echo "--- python3.13 absolute ---"
"$PREFIX"/bin/python3.13 --version 2>&1; echo "rc=$?"
echo "--- python3 absolute ---"
"$PREFIX"/bin/python3 --version 2>&1; echo "rc=$?"
echo "--- python via PATH ---"
python --version 2>&1; echo "rc=$?"
echo "--- command -v ---"
command -v python python3 python3.13 2>&1
} > "$LOG" 2>&1
cat "$LOG"

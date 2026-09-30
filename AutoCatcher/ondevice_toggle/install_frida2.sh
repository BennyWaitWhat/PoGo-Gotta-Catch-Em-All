#!/data/data/com.termux/files/usr/bin/bash
export PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH=$PREFIX/bin:$PREFIX/bin/applets:/system/bin
export LD_LIBRARY_PATH=$HOME/applibs:$PREFIX/lib
LOG=$HOME/frida_build.log
: > "$LOG"
exec >> "$LOG" 2>&1
echo "=== build start ==="
id
PY="$PREFIX/bin/python3.13"
echo "PY=$PY"
echo ">>> repair python symlinks in-context (app domain)"
( cd "$PREFIX/bin" && ln -sf python3.13 python && ln -sf python3.13 python3 && ln -sf python3.13-config python-config && ln -sf python3.13-config python3-config ) 2>&1
"$PY" --version
echo "--- py rc=$? ---"
FRIDA_VERSION=17.9.11
DARCH=arm64
echo ">>> pkg deps"
yes | pkg install -y git clang make pkg-config binutils libffi libexpat openssl curl tar xz-utils
echo "--- deps rc=$? ---"
echo ">>> pip bootstrap"
"$PY" -m pip install --upgrade setuptools wheel
echo "--- pip bootstrap rc=$? ---"
cd "$HOME"
if [ -f "$HOME/devkit/frida-core.h" ]; then
  echo ">>> devkit already present, skip download"
else
  DEVKIT_URL="https://github.com/frida/frida/releases/download/$FRIDA_VERSION/frida-core-devkit-$FRIDA_VERSION-android-$DARCH.tar.xz"
  echo ">>> download devkit $DEVKIT_URL"
  curl -L --fail -o devkit.tar.xz "$DEVKIT_URL"
  echo "--- curl rc=$? size=$(stat -c %s devkit.tar.xz 2>/dev/null) ---"
  rm -rf "$HOME/devkit"; mkdir -p "$HOME/devkit"
  tar -xf devkit.tar.xz -C "$HOME/devkit"
  rm -f devkit.tar.xz
fi
echo "--- devkit contents ---"
ls -l "$HOME/devkit" | head
echo ">>> clone frida-python fork"
rm -rf "$HOME/frida-python-android"
git clone --depth 1 https://github.com/AbhiTheModder/frida-python frida-python-android
echo "--- clone rc=$? ---"
cd "$HOME/frida-python-android"
echo ">>> build+install frida binding"
FRIDA_VERSION="$FRIDA_VERSION" FRIDA_CORE_DEVKIT="$HOME/devkit" "$PY" -m pip install --force-reinstall --no-build-isolation .
echo "--- pip build rc=$? ---"
cd "$HOME"
rm -rf "$HOME/frida-python-android"
echo ">>> verify import"
"$PY" -c "import frida; print('FRIDA_OK', frida.__version__)"
echo "--- import rc=$? ---"
echo "=== build end ==="

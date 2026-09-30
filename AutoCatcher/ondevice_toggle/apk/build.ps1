$ErrorActionPreference = "Stop"
# Build from this script's own folder (the source moved from pogo_extract to AutoCatcher/ondevice_toggle/apk; the old
# hard-coded pogo_extract path no longer exists and broke every build). SDK: ANDROID_SDK_ROOT, else the default location.
$here = $PSScriptRoot
$sdk = if ($env:ANDROID_SDK_ROOT) { $env:ANDROID_SDK_ROOT } else { "$env:LOCALAPPDATA\Android\Sdk" }
$bt  = "$sdk\build-tools\35.0.0"
$androidJar = "$sdk\platforms\android-36\android.jar"
$aapt2 = "$bt\aapt2.exe"; $zipalign = "$bt\zipalign.exe"; $apksigner = "$bt\apksigner.bat"; $d8 = "$bt\d8.bat"
$build = "$here\build"
Remove-Item $build -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force "$build","$build\gen","$build\classes","$build\dex" | Out-Null

Write-Output "[1/8] aapt2 compile"
& $aapt2 compile --dir "$here\res" -o "$build\res.zip"; if($LASTEXITCODE){throw "aapt2 compile failed"}
Write-Output "[2/8] aapt2 link"
& $aapt2 link -o "$build\base.apk" -I $androidJar --manifest "$here\AndroidManifest.xml" --java "$build\gen" --min-sdk-version 24 --target-sdk-version 34 "$build\res.zip"; if($LASTEXITCODE){throw "aapt2 link failed"}
Write-Output "[3/8] javac"
$srcs = @("$here\src\com\benny\autocatcher\MainActivity.java","$build\gen\com\benny\autocatcher\R.java")
& javac -encoding UTF-8 -source 8 -target 8 -classpath $androidJar -d "$build\classes" $srcs 2>&1 | Where-Object { $_ -notmatch 'bootstrap class path|warning: \[options\]|1 warning' }
if($LASTEXITCODE){throw "javac failed"}
Write-Output "[4/8] d8"
$classFiles = (Get-ChildItem "$build\classes" -Recurse -Filter *.class | ForEach-Object { $_.FullName })
& $d8 --release --lib $androidJar --output "$build\dex" @classFiles; if($LASTEXITCODE){throw "d8 failed"}
Write-Output "[5/8] add classes.dex"
Copy-Item "$build\base.apk" "$build\unsigned.apk" -Force
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::Open("$build\unsigned.apk","Update")
try { [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip,"$build\dex\classes.dex","classes.dex") | Out-Null } finally { $zip.Dispose() }
Write-Output "[6/8] zipalign"
& $zipalign -f 4 "$build\unsigned.apk" "$build\aligned.apk"; if($LASTEXITCODE){throw "zipalign failed"}
Write-Output "[7/8] keystore"
$ks = "$here\debug.keystore"
if(-not (Test-Path $ks)){ & keytool -genkeypair -keystore $ks -storepass android -keypass android -alias ak -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=AutoCatcher" 2>&1 | Out-Null }
Write-Output "[8/8] apksigner"
& $apksigner sign --ks $ks --ks-pass pass:android --key-pass pass:android --min-sdk-version 24 --out "$here\AutoCatcher.apk" "$build\aligned.apk"; if($LASTEXITCODE){throw "apksigner failed"}
$f = Get-Item "$here\AutoCatcher.apk"
Write-Output ("BUILT " + $f.FullName + "  size=" + $f.Length)
Write-Output ("SHA256 " + (Get-FileHash $f.FullName -Algorithm SHA256).Hash)
& $apksigner verify --print-certs "$here\AutoCatcher.apk" 2>&1 | Select-Object -First 2

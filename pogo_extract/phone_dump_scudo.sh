#!/system/bin/sh
PID=$1
DEST=/data/local/tmp/pogo_dump
mkdir -p $DEST
rm -f $DEST/*.gz $DEST/dump.log
{
echo "[0] 0x77e6a9a000 23330816"
dd if=/proc/$PID/mem bs=4096 skip=125725338 count=5696 2>/dev/null | gzip > $DEST/r000_0x77e6a9a000.bin.gz
echo "[1] 0x7756a55000 13107200"
dd if=/proc/$PID/mem bs=4096 skip=125135445 count=3200 2>/dev/null | gzip > $DEST/r001_0x7756a55000.bin.gz
echo "[2] 0x7716a9c000 9437184"
dd if=/proc/$PID/mem bs=4096 skip=124873372 count=2304 2>/dev/null | gzip > $DEST/r002_0x7716a9c000.bin.gz
echo "[3] 0x7806a5a000 8650752"
dd if=/proc/$PID/mem bs=4096 skip=125856346 count=2112 2>/dev/null | gzip > $DEST/r003_0x7806a5a000.bin.gz
echo "[4] 0x7866a58000 8650752"
dd if=/proc/$PID/mem bs=4096 skip=126249560 count=2112 2>/dev/null | gzip > $DEST/r004_0x7866a58000.bin.gz
echo "[5] 0x7826a58000 7340032"
dd if=/proc/$PID/mem bs=4096 skip=125987416 count=1792 2>/dev/null | gzip > $DEST/r005_0x7826a58000.bin.gz
echo "[6] 0x7836a50000 7340032"
dd if=/proc/$PID/mem bs=4096 skip=126052944 count=1792 2>/dev/null | gzip > $DEST/r006_0x7836a50000.bin.gz
echo "[7] 0x7846a56000 6815744"
dd if=/proc/$PID/mem bs=4096 skip=126118486 count=1664 2>/dev/null | gzip > $DEST/r007_0x7846a56000.bin.gz
echo "[8] 0x7726a91000 6291456"
dd if=/proc/$PID/mem bs=4096 skip=124938897 count=1536 2>/dev/null | gzip > $DEST/r008_0x7726a91000.bin.gz
echo "[9] 0x76e6a50000 5505024"
dd if=/proc/$PID/mem bs=4096 skip=124676688 count=1344 2>/dev/null | gzip > $DEST/r009_0x76e6a50000.bin.gz
echo "[10] 0x76b6a50000 5242880"
dd if=/proc/$PID/mem bs=4096 skip=124480080 count=1280 2>/dev/null | gzip > $DEST/r010_0x76b6a50000.bin.gz
echo "[11] 0x77b6a51000 5242880"
dd if=/proc/$PID/mem bs=4096 skip=125528657 count=1280 2>/dev/null | gzip > $DEST/r011_0x77b6a51000.bin.gz
echo "[12] 0x7856a94000 4456448"
dd if=/proc/$PID/mem bs=4096 skip=126184084 count=1088 2>/dev/null | gzip > $DEST/r012_0x7856a94000.bin.gz
echo "[13] 0x7776a91000 4194304"
dd if=/proc/$PID/mem bs=4096 skip=125266577 count=1024 2>/dev/null | gzip > $DEST/r013_0x7776a91000.bin.gz
echo "[14] 0x7736a4f000 3407872"
dd if=/proc/$PID/mem bs=4096 skip=125004367 count=832 2>/dev/null | gzip > $DEST/r014_0x7736a4f000.bin.gz
echo "[15] 0x7816a9d000 3145728"
dd if=/proc/$PID/mem bs=4096 skip=125921949 count=768 2>/dev/null | gzip > $DEST/r015_0x7816a9d000.bin.gz
echo "[16] 0x7786b1d000 2621440"
dd if=/proc/$PID/mem bs=4096 skip=125332253 count=640 2>/dev/null | gzip > $DEST/r016_0x7786b1d000.bin.gz
echo "[17] 0x7796a5d000 2359296"
dd if=/proc/$PID/mem bs=4096 skip=125397597 count=576 2>/dev/null | gzip > $DEST/r017_0x7796a5d000.bin.gz
echo "[18] 0x77a6ad4000 2097152"
dd if=/proc/$PID/mem bs=4096 skip=125463252 count=512 2>/dev/null | gzip > $DEST/r018_0x77a6ad4000.bin.gz
echo "[19] 0x7876a58000 2097152"
dd if=/proc/$PID/mem bs=4096 skip=126315096 count=512 2>/dev/null | gzip > $DEST/r019_0x7876a58000.bin.gz
echo "[20] 0x7886a59000 1835008"
dd if=/proc/$PID/mem bs=4096 skip=126380633 count=448 2>/dev/null | gzip > $DEST/r020_0x7886a59000.bin.gz
echo "[21] 0x76c6a53000 1310720"
dd if=/proc/$PID/mem bs=4096 skip=124545619 count=320 2>/dev/null | gzip > $DEST/r021_0x76c6a53000.bin.gz
echo "[22] 0x77c6a55000 1310720"
dd if=/proc/$PID/mem bs=4096 skip=125594197 count=320 2>/dev/null | gzip > $DEST/r022_0x77c6a55000.bin.gz
echo "[23] 0x77d6a57000 1310720"
dd if=/proc/$PID/mem bs=4096 skip=125659735 count=320 2>/dev/null | gzip > $DEST/r023_0x77d6a57000.bin.gz
echo "[24] 0x76d6a53000 1048576"
dd if=/proc/$PID/mem bs=4096 skip=124611155 count=256 2>/dev/null | gzip > $DEST/r024_0x76d6a53000.bin.gz
echo "[25] 0x7746a55000 1048576"
dd if=/proc/$PID/mem bs=4096 skip=125069909 count=256 2>/dev/null | gzip > $DEST/r025_0x7746a55000.bin.gz
echo "[26] 0x7786a1d000 1048576"
dd if=/proc/$PID/mem bs=4096 skip=125331997 count=256 2>/dev/null | gzip > $DEST/r026_0x7786a1d000.bin.gz
echo "[27] 0x76f6a4f000 786432"
dd if=/proc/$PID/mem bs=4096 skip=124742223 count=192 2>/dev/null | gzip > $DEST/r027_0x76f6a4f000.bin.gz
echo "[28] 0x77a6a14000 786432"
dd if=/proc/$PID/mem bs=4096 skip=125463060 count=192 2>/dev/null | gzip > $DEST/r028_0x77a6a14000.bin.gz
echo "[29] 0x76a6a5d000 524288"
dd if=/proc/$PID/mem bs=4096 skip=124414557 count=128 2>/dev/null | gzip > $DEST/r029_0x76a6a5d000.bin.gz
echo "[30] 0x7706a52000 524288"
dd if=/proc/$PID/mem bs=4096 skip=124807762 count=128 2>/dev/null | gzip > $DEST/r030_0x7706a52000.bin.gz
echo "[31] 0x7716a1c000 524288"
dd if=/proc/$PID/mem bs=4096 skip=124873244 count=128 2>/dev/null | gzip > $DEST/r031_0x7716a1c000.bin.gz
echo "[32] 0x7726a11000 524288"
dd if=/proc/$PID/mem bs=4096 skip=124938769 count=128 2>/dev/null | gzip > $DEST/r032_0x7726a11000.bin.gz
echo "[33] 0x7766a55000 524288"
dd if=/proc/$PID/mem bs=4096 skip=125200981 count=128 2>/dev/null | gzip > $DEST/r033_0x7766a55000.bin.gz
echo "[34] 0x7776a11000 524288"
dd if=/proc/$PID/mem bs=4096 skip=125266449 count=128 2>/dev/null | gzip > $DEST/r034_0x7776a11000.bin.gz
echo "[35] 0x77e6a1a000 524288"
dd if=/proc/$PID/mem bs=4096 skip=125725210 count=128 2>/dev/null | gzip > $DEST/r035_0x77e6a1a000.bin.gz
echo "[36] 0x7816a1d000 524288"
dd if=/proc/$PID/mem bs=4096 skip=125921821 count=128 2>/dev/null | gzip > $DEST/r036_0x7816a1d000.bin.gz
echo "[37] 0x7856a14000 524288"
dd if=/proc/$PID/mem bs=4096 skip=126183956 count=128 2>/dev/null | gzip > $DEST/r037_0x7856a14000.bin.gz
echo "[38] 0x7896a17000 524288"
dd if=/proc/$PID/mem bs=4096 skip=126446103 count=128 2>/dev/null | gzip > $DEST/r038_0x7896a17000.bin.gz
echo "[39] 0x7696a0e000 262144"
dd if=/proc/$PID/mem bs=4096 skip=124348942 count=64 2>/dev/null | gzip > $DEST/r039_0x7696a0e000.bin.gz
echo "[40] 0x7696a4e000 262144"
dd if=/proc/$PID/mem bs=4096 skip=124349006 count=64 2>/dev/null | gzip > $DEST/r040_0x7696a4e000.bin.gz
echo "[41] 0x76a6a1d000 262144"
dd if=/proc/$PID/mem bs=4096 skip=124414493 count=64 2>/dev/null | gzip > $DEST/r041_0x76a6a1d000.bin.gz
echo "[42] 0x76b6a10000 262144"
dd if=/proc/$PID/mem bs=4096 skip=124480016 count=64 2>/dev/null | gzip > $DEST/r042_0x76b6a10000.bin.gz
echo "[43] 0x76c6a13000 262144"
dd if=/proc/$PID/mem bs=4096 skip=124545555 count=64 2>/dev/null | gzip > $DEST/r043_0x76c6a13000.bin.gz
echo "[44] 0x76d6a13000 262144"
dd if=/proc/$PID/mem bs=4096 skip=124611091 count=64 2>/dev/null | gzip > $DEST/r044_0x76d6a13000.bin.gz
echo "[45] 0x76e6a10000 262144"
dd if=/proc/$PID/mem bs=4096 skip=124676624 count=64 2>/dev/null | gzip > $DEST/r045_0x76e6a10000.bin.gz
echo "[46] 0x76f6a0f000 262144"
dd if=/proc/$PID/mem bs=4096 skip=124742159 count=64 2>/dev/null | gzip > $DEST/r046_0x76f6a0f000.bin.gz
echo "[47] 0x7706a12000 262144"
dd if=/proc/$PID/mem bs=4096 skip=124807698 count=64 2>/dev/null | gzip > $DEST/r047_0x7706a12000.bin.gz
echo "[48] 0x7736a0f000 262144"
dd if=/proc/$PID/mem bs=4096 skip=125004303 count=64 2>/dev/null | gzip > $DEST/r048_0x7736a0f000.bin.gz
echo "[49] 0x7746a15000 262144"
dd if=/proc/$PID/mem bs=4096 skip=125069845 count=64 2>/dev/null | gzip > $DEST/r049_0x7746a15000.bin.gz
echo "[50] 0x7756a15000 262144"
dd if=/proc/$PID/mem bs=4096 skip=125135381 count=64 2>/dev/null | gzip > $DEST/r050_0x7756a15000.bin.gz
echo "[51] 0x7766a15000 262144"
dd if=/proc/$PID/mem bs=4096 skip=125200917 count=64 2>/dev/null | gzip > $DEST/r051_0x7766a15000.bin.gz
echo "[52] 0x7796a1d000 262144"
dd if=/proc/$PID/mem bs=4096 skip=125397533 count=64 2>/dev/null | gzip > $DEST/r052_0x7796a1d000.bin.gz
echo "[53] 0x77b6a11000 262144"
dd if=/proc/$PID/mem bs=4096 skip=125528593 count=64 2>/dev/null | gzip > $DEST/r053_0x77b6a11000.bin.gz
echo "[54] 0x77c6a15000 262144"
dd if=/proc/$PID/mem bs=4096 skip=125594133 count=64 2>/dev/null | gzip > $DEST/r054_0x77c6a15000.bin.gz
echo "[55] 0x77d6a17000 262144"
dd if=/proc/$PID/mem bs=4096 skip=125659671 count=64 2>/dev/null | gzip > $DEST/r055_0x77d6a17000.bin.gz
echo "[56] 0x77f6a11000 262144"
dd if=/proc/$PID/mem bs=4096 skip=125790737 count=64 2>/dev/null | gzip > $DEST/r056_0x77f6a11000.bin.gz
echo "[57] 0x77f6a51000 262144"
dd if=/proc/$PID/mem bs=4096 skip=125790801 count=64 2>/dev/null | gzip > $DEST/r057_0x77f6a51000.bin.gz
echo "[58] 0x7806a1a000 262144"
dd if=/proc/$PID/mem bs=4096 skip=125856282 count=64 2>/dev/null | gzip > $DEST/r058_0x7806a1a000.bin.gz
echo "[59] 0x7826a18000 262144"
dd if=/proc/$PID/mem bs=4096 skip=125987352 count=64 2>/dev/null | gzip > $DEST/r059_0x7826a18000.bin.gz
echo "[60] 0x7836a10000 262144"
dd if=/proc/$PID/mem bs=4096 skip=126052880 count=64 2>/dev/null | gzip > $DEST/r060_0x7836a10000.bin.gz
echo "[61] 0x7846a16000 262144"
dd if=/proc/$PID/mem bs=4096 skip=126118422 count=64 2>/dev/null | gzip > $DEST/r061_0x7846a16000.bin.gz
echo "[62] 0x7866a18000 262144"
dd if=/proc/$PID/mem bs=4096 skip=126249496 count=64 2>/dev/null | gzip > $DEST/r062_0x7866a18000.bin.gz
echo "[63] 0x7876a18000 262144"
dd if=/proc/$PID/mem bs=4096 skip=126315032 count=64 2>/dev/null | gzip > $DEST/r063_0x7876a18000.bin.gz
echo "[64] 0x7886a19000 262144"
dd if=/proc/$PID/mem bs=4096 skip=126380569 count=64 2>/dev/null | gzip > $DEST/r064_0x7886a19000.bin.gz
echo "[65] 0x7896a97000 262144"
dd if=/proc/$PID/mem bs=4096 skip=126446231 count=64 2>/dev/null | gzip > $DEST/r065_0x7896a97000.bin.gz
} 2>&1 | tee $DEST/dump.log
ls -la $DEST | head

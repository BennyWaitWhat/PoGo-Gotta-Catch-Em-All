#!/system/bin/sh
PID=$1
DEST=/data/local/tmp/pogo_anon
mkdir -p $DEST
rm -f $DEST/*.gz $DEST/dump.log
{
echo "[0/40] 0x726e8000 10895360"
dd if=/proc/$PID/mem bs=4096 skip=468712 count=2660 2>/dev/null | gzip > $DEST/a000_0x726e8000.bin.gz
echo "[1/40] 0x72f0000000 16777216"
dd if=/proc/$PID/mem bs=4096 skip=120520704 count=4096 2>/dev/null | gzip > $DEST/a001_0x72f0000000.bin.gz
echo "[2/40] 0x7346ea5000 16777216"
dd if=/proc/$PID/mem bs=4096 skip=120876709 count=4096 2>/dev/null | gzip > $DEST/a002_0x7346ea5000.bin.gz
echo "[3/40] 0x7350000000 4194304"
dd if=/proc/$PID/mem bs=4096 skip=120913920 count=1024 2>/dev/null | gzip > $DEST/a003_0x7350000000.bin.gz
echo "[4/40] 0x7360000000 2097152"
dd if=/proc/$PID/mem bs=4096 skip=120979456 count=512 2>/dev/null | gzip > $DEST/a004_0x7360000000.bin.gz
echo "[5/40] 0x737a000000 50331648"
dd if=/proc/$PID/mem bs=4096 skip=121085952 count=8192 2>/dev/null | gzip > $DEST/a005_0x737a000000.bin.gz
echo "[6/40] 0x737f000000 16781312"
dd if=/proc/$PID/mem bs=4096 skip=121106432 count=4097 2>/dev/null | gzip > $DEST/a006_0x737f000000.bin.gz
echo "[7/40] 0x73a15a3000 16781312"
dd if=/proc/$PID/mem bs=4096 skip=121247139 count=4097 2>/dev/null | gzip > $DEST/a007_0x73a15a3000.bin.gz
echo "[8/40] 0x73b04c0000 1048576"
dd if=/proc/$PID/mem bs=4096 skip=121308352 count=256 2>/dev/null | gzip > $DEST/a008_0x73b04c0000.bin.gz
echo "[9/40] 0x73be6e9000 16777216"
dd if=/proc/$PID/mem bs=4096 skip=121366249 count=4096 2>/dev/null | gzip > $DEST/a009_0x73be6e9000.bin.gz
echo "[10/40] 0x73c16e9000 64249856"
dd if=/proc/$PID/mem bs=4096 skip=121378537 count=8192 2>/dev/null | gzip > $DEST/a010_0x73c16e9000.bin.gz
echo "[11/40] 0x73c742f000 12763136"
dd if=/proc/$PID/mem bs=4096 skip=121402415 count=3116 2>/dev/null | gzip > $DEST/a011_0x73c742f000.bin.gz
echo "[12/40] 0x73d0239000 21372928"
dd if=/proc/$PID/mem bs=4096 skip=121438777 count=5218 2>/dev/null | gzip > $DEST/a012_0x73d0239000.bin.gz
echo "[13/40] 0x73d179f000 3805184"
dd if=/proc/$PID/mem bs=4096 skip=121444255 count=929 2>/dev/null | gzip > $DEST/a013_0x73d179f000.bin.gz
echo "[14/40] 0x73d1d48000 2850816"
dd if=/proc/$PID/mem bs=4096 skip=121445704 count=696 2>/dev/null | gzip > $DEST/a014_0x73d1d48000.bin.gz
echo "[15/40] 0x73e0000000 2097152"
dd if=/proc/$PID/mem bs=4096 skip=121503744 count=512 2>/dev/null | gzip > $DEST/a015_0x73e0000000.bin.gz
echo "[16/40] 0x73f01f9000 2236416"
dd if=/proc/$PID/mem bs=4096 skip=121569785 count=546 2>/dev/null | gzip > $DEST/a016_0x73f01f9000.bin.gz
echo "[17/40] 0x73f5663000 3379200"
dd if=/proc/$PID/mem bs=4096 skip=121591395 count=825 2>/dev/null | gzip > $DEST/a017_0x73f5663000.bin.gz
echo "[18/40] 0x7410000000 7114752"
dd if=/proc/$PID/mem bs=4096 skip=121700352 count=1737 2>/dev/null | gzip > $DEST/a018_0x7410000000.bin.gz
echo "[19/40] 0x7430200000 16777216"
dd if=/proc/$PID/mem bs=4096 skip=121831936 count=4096 2>/dev/null | gzip > $DEST/a019_0x7430200000.bin.gz
echo "[20/40] 0x7431600000 18874368"
dd if=/proc/$PID/mem bs=4096 skip=121837056 count=4608 2>/dev/null | gzip > $DEST/a020_0x7431600000.bin.gz
echo "[21/40] 0x7450000000 33562624"
dd if=/proc/$PID/mem bs=4096 skip=121962496 count=8192 2>/dev/null | gzip > $DEST/a021_0x7450000000.bin.gz
echo "[22/40] 0x7460000000 33554432"
dd if=/proc/$PID/mem bs=4096 skip=122028032 count=8192 2>/dev/null | gzip > $DEST/a022_0x7460000000.bin.gz
echo "[23/40] 0x747def2000 16777216"
dd if=/proc/$PID/mem bs=4096 skip=122150642 count=4096 2>/dev/null | gzip > $DEST/a023_0x747def2000.bin.gz
echo "[24/40] 0x7490100000 2097152"
dd if=/proc/$PID/mem bs=4096 skip=122224896 count=512 2>/dev/null | gzip > $DEST/a024_0x7490100000.bin.gz
echo "[25/40] 0x7490500000 63963136"
dd if=/proc/$PID/mem bs=4096 skip=122225920 count=8192 2>/dev/null | gzip > $DEST/a025_0x7490500000.bin.gz
echo "[26/40] 0x74b0000000 8454144"
dd if=/proc/$PID/mem bs=4096 skip=122355712 count=2064 2>/dev/null | gzip > $DEST/a026_0x74b0000000.bin.gz
echo "[27/40] 0x74c0000000 16777216"
dd if=/proc/$PID/mem bs=4096 skip=122421248 count=4096 2>/dev/null | gzip > $DEST/a027_0x74c0000000.bin.gz
echo "[28/40] 0x74d0000000 79691776"
dd if=/proc/$PID/mem bs=4096 skip=122486784 count=8192 2>/dev/null | gzip > $DEST/a028_0x74d0000000.bin.gz
echo "[29/40] 0x74e0000000 33554432"
dd if=/proc/$PID/mem bs=4096 skip=122552320 count=8192 2>/dev/null | gzip > $DEST/a029_0x74e0000000.bin.gz
echo "[30/40] 0x7500000000 4194304"
dd if=/proc/$PID/mem bs=4096 skip=122683392 count=1024 2>/dev/null | gzip > $DEST/a030_0x7500000000.bin.gz
echo "[31/40] 0x752dbf1000 8159232"
dd if=/proc/$PID/mem bs=4096 skip=122870769 count=1992 2>/dev/null | gzip > $DEST/a031_0x752dbf1000.bin.gz
echo "[32/40] 0x752e3b9000 2383872"
dd if=/proc/$PID/mem bs=4096 skip=122872761 count=582 2>/dev/null | gzip > $DEST/a032_0x752e3b9000.bin.gz
echo "[33/40] 0x7530000000 1048576"
dd if=/proc/$PID/mem bs=4096 skip=122880000 count=256 2>/dev/null | gzip > $DEST/a033_0x7530000000.bin.gz
echo "[34/40] 0x7660acb000 67108864"
dd if=/proc/$PID/mem bs=4096 skip=124127947 count=8192 2>/dev/null | gzip > $DEST/a034_0x7660acb000.bin.gz
echo "[35/40] 0x767f174000 1048576"
dd if=/proc/$PID/mem bs=4096 skip=124252532 count=256 2>/dev/null | gzip > $DEST/a035_0x767f174000.bin.gz
echo "[36/40] 0x767f4b9000 2359296"
dd if=/proc/$PID/mem bs=4096 skip=124253369 count=576 2>/dev/null | gzip > $DEST/a036_0x767f4b9000.bin.gz
echo "[37/40] 0x7688dfb000 4960256"
dd if=/proc/$PID/mem bs=4096 skip=124292603 count=1211 2>/dev/null | gzip > $DEST/a037_0x7688dfb000.bin.gz
echo "[38/40] 0x793109e000 2236416"
dd if=/proc/$PID/mem bs=4096 skip=127078558 count=546 2>/dev/null | gzip > $DEST/a038_0x793109e000.bin.gz
echo "[39/40] 0x7fe4a6f000 8384512"
dd if=/proc/$PID/mem bs=4096 skip=134105711 count=2047 2>/dev/null | gzip > $DEST/a039_0x7fe4a6f000.bin.gz
} 2>&1 | tee $DEST/dump.log
du -sh $DEST
ls $DEST | wc -l

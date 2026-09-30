import os
os.chdir(r"C:/Users/Blanco/Desktop/Claude Operations/Phone Maintenance/pogo_extract/system/analysis/tagsets")
for f in ['3_Legacy_Moves.txt', '6_Transfer.txt']:
    raw = open(f, 'rb').read()
    has_cr = b"\r" in raw
    txt = raw.decode('utf-8')
    lines = txt.split('\n')
    nonempty = [l for l in lines if l.strip()]
    stripped_diff = [l for l in nonempty if l != l.strip()]
    lens = sorted(set(len(l.strip()) for l in nonempty))
    uniq = len(set(l.strip() for l in nonempty))
    print(f)
    print('  raw split lines:', len(lines), '| nonempty:', len(nonempty),
          '| unique:', uniq, '| stripped-lengths:', lens,
          '| ws-anomalies:', len(stripped_diff), '| has CR:', has_cr)

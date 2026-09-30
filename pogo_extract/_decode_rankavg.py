import json, math
GT = r"C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance\pokegenie_work\extracted\scan_data.json"
GM = r"C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance\pogo_extract\pvpoke_gamemaster.json"
d = json.load(open(GT, encoding="utf-8"))
gm = json.load(open(GM, encoding="utf-8"))
byid={p["speciesId"]:p for p in gm["pokemon"]}
bydex={}
for p in gm["pokemon"]: bydex.setdefault(p["dex"],p)

STD = {1.0:0.094,1.5:0.135137432,2.0:0.16639787,2.5:0.192650919,3.0:0.21573247,3.5:0.236572661,4.0:0.25572005,4.5:0.273530381,5.0:0.29024988,5.5:0.306057377,6.0:0.3210876,6.5:0.335445036,7.0:0.34921268,7.5:0.362457751,8.0:0.37523559,8.5:0.387592406,9.0:0.39956728,9.5:0.411193551,10.0:0.42250001,10.5:0.432926419,11.0:0.44310755,11.5:0.453059958,12.0:0.46279839,12.5:0.472336083,13.0:0.48168495,13.5:0.490855813,14.0:0.49985844,14.5:0.508701765,15.0:0.51739395,15.5:0.525942511,16.0:0.53435433,16.5:0.542635767,17.0:0.55079269,17.5:0.558830576,18.0:0.56675452,18.5:0.574629862,19.0:0.58227891,19.5:0.589887917,20.0:0.59740001,20.5:0.604818814,21.0:0.61215729,21.5:0.619399365,22.0:0.62656713,22.5:0.633644533,23.0:0.64065295,23.5:0.647576426,24.0:0.65443563,24.5:0.661214806,25.0:0.667934,25.5:0.674577537,26.0:0.68116492,26.5:0.687680648,27.0:0.69414365,27.5:0.700538673,28.0:0.70688421,28.5:0.713164996,29.0:0.71939909,29.5:0.725563749,30.0:0.7317,30.5:0.734741009,31.0:0.73776948,31.5:0.740796879,32.0:0.74378943,32.5:0.746781211,33.0:0.74976104,33.5:0.752729087,34.0:0.75568551,34.5:0.758632576,35.0:0.76156384,35.5:0.764484794,36.0:0.76739717,36.5:0.770297266,37.0:0.7731865,37.5:0.776064962,38.0:0.77893275,38.5:0.781779565,39.0:0.78463697,39.5:0.787473578,40.0:0.79030001,40.5:0.792803968,41.0:0.79530001,41.5:0.797803,42.0:0.8003,42.5:0.802799,43.0:0.8053,43.5:0.807799,44.0:0.81030,44.5:0.812799,45.0:0.81530,45.5:0.817799,46.0:0.82030,46.5:0.822799,47.0:0.82530,47.5:0.827799,48.0:0.83030,48.5:0.832799,49.0:0.83530,49.5:0.837799,50.0:0.84030}
LEVELS=[round(1.0+0.5*i,1) for i in range(99)]

def cp(b,iv,l):
    a=b["atk"]+iv[0];d=b["def"]+iv[1];s=b["hp"]+iv[2];m=STD[l]
    return max(10,int(a*math.sqrt(d)*math.sqrt(s)*m*m/10))
def sp(b,iv,l,sh):
    m=STD[l];a=(b["atk"]+iv[0])*m;de=(b["def"]+iv[1])*m;st=(b["hp"]+iv[2])*m
    if sh:a*=1.2;de/=1.2
    return a*de*int(st)
def best(b,iv,cap,sh):
    bp=0;bl=None
    for l in LEVELS:
        if cp(b,iv,l)>cap:break
        v=sp(b,iv,l,sh)
        if v>=bp:bp=v;bl=l
    return bp,bl
def ceil_minmax(b,cap,sh):
    mx=0;mn=1e99
    for ai in range(16):
        for di in range(16):
            for si in range(16):
                v,_=best(b,(ai,di,si),cap,sh)
                if v>mx:mx=v
                if v<mn:mn=v
    return mx,mn

# Reproduce GT Charizard 15/15/15 (dex6) GL rankAvg=0.593406 maxCP=1486
b=bydex[6]["baseStats"]
iv=(15,15,15)
v,l=best(b,iv,1500,False)
mx,mn=ceil_minmax(b,1500,False)
print("Charizard GL 15/15/15: myprod",round(v),"bestL",l,"maxCP",cp(b,iv,l))
print("  ceil(max prod over IVs)=",round(mx)," floor(min)=",round(mn))
print("  rank vs max  =", v/mx)
print("  rank (max-v)/(max-min) inverted? =", (mx-v)/(mx-mn))
print("  rank (v-min)/(max-min) =", (v-min(v,mn))/(mx-mn) if mx>mn else 0)
print("  GT rankAvg target = 0.5934065934065934  (=> 54/91? )", 54/91, 108/182)
# prodLower in GT = 9515 ; scaled product. 9515/10000 = 0.9515 = DB gl_pct. So 'prodLower' encodes rank-vs-ceiling*10000
print("  v/mx*10000 =", round(v/mx*10000), " (GT prodLower=9515)")
# So rankAvg must be the ORDINAL rank fraction among all 4096 IV combos (1 - (#better)/4095)?
# Compute ordinal: fraction of IV combos with strictly greater product
allprod=[]
for ai in range(16):
    for di in range(16):
        for si in range(16):
            pv,_=best(b,(ai,di,si),1500,False)
            allprod.append(pv)
allprod.sort()
import bisect
# rankAvg likely = (count <= v)/4096  (percentile of this IV among all)
le=bisect.bisect_right(allprod,v)
lt=bisect.bisect_left(allprod,v)
print("  percentile (count<=v)/4096 =", le/4096, " (count<v)/4096 =", lt/4096)
print("  ordinal-from-top: 1 - (#strictly better)/4095 =", 1-(4096-le)/4095)
print("  (le)/4096 vs target 0.5934 ; (le-1)/4095 =", (le-1)/4095)

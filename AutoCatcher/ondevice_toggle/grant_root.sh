magisk --sqlite "REPLACE INTO policies (uid,policy,until,logging,notification) VALUES ($1,2,0,0,0)"
echo "grant rc=$?"
magisk --sqlite "SELECT uid,policy FROM policies"

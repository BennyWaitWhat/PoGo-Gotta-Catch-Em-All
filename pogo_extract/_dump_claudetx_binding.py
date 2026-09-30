"""Dump CLAUDE_TX binding to find its UID/proto list."""
import frida, subprocess, sqlite3, json
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)
SVC = '0x7275723100'

bulk = sess.create_script(open('bulk_tag.js','r',encoding='utf-8').read())
bulk.load(); bulk.exports_sync.init_status()

ftid = bulk.exports_sync.find_tag_id_by_name(SVC, 'CLAUDE_TX')
print(f"CLAUDE_TX tag info: idx={ftid.get('idx')} tagProto={ftid.get('tagProtoAddr')}")
chk = bulk.exports_sync.get_pokemon_for_tag(SVC, ftid['idx'])
print(json.dumps(chk, indent=2, default=str)[:3000])
sess.detach()

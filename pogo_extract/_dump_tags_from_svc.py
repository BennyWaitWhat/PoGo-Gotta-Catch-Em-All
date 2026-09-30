"""Enumerate tags from svc 0x76a4615980 and find JUMBO."""
import frida, subprocess
subprocess.run(['adb','-s','100.98.158.56:5555','forward','tcp:27047','tcp:27047'], capture_output=True)
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)
SVC = '0x76a4615980'
sc = sess.create_script(open('bulk_tag.js','r',encoding='utf-8').read())
sc.load(); print(sc.exports_sync.init_status())
print("Looking for JUMBO...")
r = sc.exports_sync.find_tag_id_by_name(SVC, 'JUMBO')
print(f"  result: {r}")
# Try other names
for name in ['Hundos','Nundos','JUMBO','CLAUDE_TX','Background','0-15-15']:
    r = sc.exports_sync.find_tag_id_by_name(SVC, name)
    print(f"  {name}: ok={r.get('ok')} idx={r.get('idx')} tagProto={r.get('tagProtoAddr')}")
sess.detach()

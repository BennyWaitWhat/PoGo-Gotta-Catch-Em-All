import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'system', 'scripts'))
import pogo_il2cpp as pg
sess, pid = pg.get_session()
src = open('nickname_extra.js').read()
script = sess.create_script(src)
def on_msg(m, d):
    if m.get('type') == 'send':
        p = m['payload']
        if p.get('type') == 'methods':
            print('\n===', p['label'], '(', p.get('image'), ') ===')
            for meth in p['data']:
                print('  ', meth['sig'])
        elif p.get('type') == 'msg':
            print(p['msg'])
    elif m.get('type') == 'error':
        print('[ERR]', m.get('description'))
script.on('message', on_msg)
script.load()
time.sleep(6)
try: sess.detach()
except Exception: pass

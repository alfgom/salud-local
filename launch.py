#!/usr/bin/env python3
"""One process supervisor; a dedicated offline Ollama child and loopback web server."""
import atexit
import fcntl
import http.client
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser

BASE=Path(__file__).resolve().parent
os.chdir(BASE)
os.umask(0o077)
PROFILE='''(version 1)
(allow default)
(deny network*)
(allow network-bind (local ip "localhost:*"))
(allow network-inbound (local ip "localhost:*"))
(allow network-outbound (remote ip "localhost:*"))
'''
if sys.platform=='darwin' and os.environ.get('SALUD_SANDBOX')!='1':
    env=os.environ.copy(); env['SALUD_SANDBOX']='1'
    os.execve('/usr/bin/sandbox-exec',['sandbox-exec','-p',PROFILE,sys.executable,str(BASE/'launch.py'),*sys.argv[1:]],env)
root=Path(os.environ.get('SALUD_DATA',str(Path.home()/'Library'/'Application Support'/'SaludLocal')))
root.mkdir(parents=True,exist_ok=True,mode=0o700)
lock=open(root/'process.lock','w')
try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
except BlockingIOError:
    if '--no-browser' not in sys.argv: webbrowser.open('http://127.0.0.1:8765')
    sys.exit(0)
# Refuse to trust another server on the private model port.
for port in (8765,11435):
    probe=socket.socket()
    probe.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
    try: probe.bind(('127.0.0.1',port))
    except OSError:
        print(f'El puerto local {port} está ocupado. Cierra la otra instancia y vuelve a abrir Salud Local.'); sys.exit(1)
    finally: probe.close()
ollama=shutil.which('ollama') or '/usr/local/bin/ollama'
child=None
if Path(ollama).exists():
    env=os.environ.copy()
    env.update({'OLLAMA_HOST':'127.0.0.1:11435','OLLAMA_NO_CLOUD':'1','OLLAMA_MAX_LOADED_MODELS':'1','OLLAMA_NUM_PARALLEL':'1','OLLAMA_CONTEXT_LENGTH':'8192','OLLAMA_KEEP_ALIVE':'0','OLLAMA_DEBUG':'0'})
    for name in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy','OLLAMA_ORIGINS'): env.pop(name,None)
    child=subprocess.Popen([ollama,'serve'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

def cleanup():
    if child and child.poll() is None:
        child.terminate()
        try: child.wait(timeout=8)
        except subprocess.TimeoutExpired: child.kill()
atexit.register(cleanup)

def open_ready():
    # The web server needs no network beyond loopback; browser opened by system service.
    time.sleep(1.5)
    webbrowser.open('http://127.0.0.1:8765')
if '--no-browser' not in sys.argv: threading.Thread(target=open_ready,daemon=True).start()
from app.security import install
install()
import uvicorn
print('Salud Local · http://127.0.0.1:8765 · solo en este equipo',flush=True)
uvicorn.run('app.main:app',host='127.0.0.1',port=8765,access_log=False,log_level='critical',server_header=False)

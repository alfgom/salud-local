"""Bounded subprocess supervision; no plaintext temporary upload files."""
import base64
import json
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path

BASE=Path(__file__).resolve().parent.parent
PARSER_LOCK=threading.Lock()

def extract(name,content):
    if not PARSER_LOCK.acquire(blocking=False): raise ValueError('Ya hay una extracción activa')
    try: return _extract(name,content)
    finally: PARSER_LOCK.release()

def _extract(name,content):
    proc=subprocess.Popen([sys.executable,'-m','app.extract_worker'],cwd=BASE,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,start_new_session=True)
    finished=threading.Event(); exceeded=threading.Event()
    def kill():
        try: os.killpg(proc.pid,signal.SIGKILL)
        except ProcessLookupError: pass
    def monitor():
        while not finished.wait(.3):
            try:
                result=subprocess.run(['/bin/ps','-o','rss=','-p',str(proc.pid)],capture_output=True,text=True,timeout=2)
                if int(result.stdout.strip() or '0')>1_000_000:
                    exceeded.set();kill();return
            except (ValueError,OSError,subprocess.SubprocessError): pass
    threading.Thread(target=monitor,daemon=True).start()
    try:
        out,_=proc.communicate(json.dumps({'name':name,'data':base64.b64encode(content).decode()}).encode(),timeout=65)
        if proc.returncode or exceeded.is_set() or len(out)>8_000_000: raise ValueError('Parser limitado')
        result=json.loads(out)
        if 'error' in result: raise ValueError('Extracción rechazada')
        return result
    except subprocess.TimeoutExpired:
        kill();proc.communicate();raise ValueError('Tiempo máximo de extracción')
    finally: finished.set()

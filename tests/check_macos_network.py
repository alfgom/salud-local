"""Explicit integration check: launch Python and native curl in the same macOS policy."""
import subprocess
import sys
PROFILE='''(version 1)(allow default)(deny network*)(allow network-bind (local ip "localhost:*"))(allow network-inbound (local ip "localhost:*"))(allow network-outbound (remote ip "localhost:*"))'''
if sys.platform!='darwin':raise SystemExit('Esta comprobación requiere macOS')
code='''import socket,subprocess
try:
    socket.create_connection(('1.1.1.1',443),timeout=2)
except PermissionError:
    print('TCP externo: bloqueado por macOS')
else: raise AssertionError('TCP externo permitido')
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
try: s.sendto(b'network-isolation-test',('1.1.1.1',53))
except PermissionError: print('UDP externo: bloqueado por macOS')
else: raise AssertionError('UDP externo permitido')
r=subprocess.run(['/usr/bin/curl','--noproxy','*','--connect-timeout','2','http://1.1.1.1'],capture_output=True)
assert r.returncode!=0
assert b'Operation not permitted' in r.stderr or b"Couldn't connect" in r.stderr or b'Failed to connect' in r.stderr
print('Proceso nativo hijo: conexión externa bloqueada')
s.close()
'''
r=subprocess.run(['/usr/bin/sandbox-exec','-p',PROFILE,sys.executable,'-c',code],capture_output=True,text=True)
print(r.stdout,end='')
if r.returncode:print(r.stderr);raise SystemExit(r.returncode)

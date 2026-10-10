#!/usr/bin/env python3
"""Scan only Git's publication tree, never the working directory or private data."""
import hashlib
import json
import re
import subprocess
import sys


def git(*args):
    return subprocess.check_output(['git', *args], stderr=subprocess.DEVNULL)


def check_entries(entries, read):
    errors = []
    manifest = json.loads(read('public-files.json'))
    allowed = set(manifest['files']) | {'public-files.json'}
    fixtures = manifest['synthetic_sha256']
    patterns = [
        rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
        rb'gh[pousr]_[A-Za-z0-9]{30,}',
        rb'github_pat_[A-Za-z0-9_]{30,}',
        rb'AKIA[0-9A-Z]{16}',
        rb'sk-(?:proj-)?[A-Za-z0-9_-]{32,}',
        rb'/' + rb'Users' + rb'/[^/\s]+/',
    ]
    for name, mode in entries:
        if name not in allowed:
            errors.append('Archivo fuera de la lista pública: ' + name)
            continue
        if mode not in ('100644', '100755'):
            errors.append('Enlace o submódulo no permitido: ' + name)
            continue
        if any(part.lower() in {'datos_privados','local-data','originals','backups','00_inbox','01_originales','02_procesados','03_perfil','04_linea_temporal','05_consultas_externas','06_informes_para_medico','99_logs','.venv'} for part in name.split('/')):
            errors.append('Ruta privada prohibida: ' + name)
            continue
        if name.lower().endswith(('.bin','.sqlite','.sqlite3','.db','.zip','.pem','.key','.log')) or name.split('/')[-1] in ('key.json','.env'):
            errors.append('Formato privado prohibido: ' + name)
            continue
        blob = read(name)
        if len(blob) > 2_000_000:
            errors.append('Archivo inesperadamente grande: ' + name)
        if name.startswith('examples/'):
            if hashlib.sha256(blob).hexdigest() != fixtures.get(name):
                errors.append('Ejemplo sintético modificado: revisa su procedencia y su huella: ' + name)
        elif b'\0' in blob:
            errors.append('Binario fuera de los ejemplos aprobados: ' + name)
        for pattern in patterns:
            if re.search(pattern,blob):
                errors.append('Posible secreto o ruta personal: ' + name)
    missing = allowed - {n for n, _ in entries}
    if missing:
        errors.append('Faltan archivos del manifiesto: ' + ', '.join(sorted(missing)))
    return errors


def check_index():
    entries = []
    for row in git('ls-files','--stage','-z').decode().split('\0'):
        if row:
            info,name=row.split('\t',1)
            mode,_,stage=info.split()
            if stage!='0': raise ValueError('Conflicto sin resolver')
            entries.append((name,mode))
    return check_entries(entries,lambda name:git('show',':'+name))


def check_revision(rev):
    entries=[]
    for row in git('ls-tree','-rz',rev).decode().split('\0'):
        if row:
            info,name=row.split('\t',1)
            mode,_,_=info.split()
            entries.append((name,mode))
    return check_entries(entries,lambda name:git('show',rev+':'+name))


def main():
    try:
        errors=check_index()
        if '--history' in sys.argv:
            for rev in git('rev-list','--all').decode().splitlines():
                errors.extend(check_revision(rev))
        if errors:
            print('\n'.join(dict.fromkeys(errors)))
            return 1
        print('Publicación comprobada: solo archivos autorizados y ejemplos sintéticos con huellas verificadas.')
        return 0
    except (subprocess.CalledProcessError,ValueError,KeyError):
        print('No se pudo comprobar la publicación. Revisa el manifiesto y el índice de Git.')
        return 1

if __name__=='__main__':
    raise SystemExit(main())

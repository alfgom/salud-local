import hashlib
import json
from scripts.check_publication import check_entries


def fixture(files, synthetic=None):
    manifest={'files':list(files),'synthetic_sha256':synthetic or {}}
    blobs={**files,'public-files.json':json.dumps(manifest).encode()}
    entries=[(name,'100644') for name in blobs]
    return blobs,entries


def test_publication_accepts_approved_code_and_fixture():
    data=b'SYNTHETIC ONLY'
    blobs,entries=fixture({'app.py':b'print("hello")','examples/test.csv':data},{'examples/test.csv':hashlib.sha256(data).hexdigest()})
    assert check_entries(entries,blobs.__getitem__)==[]


def test_unapproved_file_is_not_read():
    blobs,entries=fixture({'app.py':b'pass'})
    errors=check_entries(entries+[('private.pdf','100644')],blobs.__getitem__)
    assert any('fuera de la lista' in e for e in errors)


def test_private_format_is_denied_even_if_manifest_allows_it():
    blobs,entries=fixture({'vault.bin':b'ciphertext'})
    assert any('Formato privado' in e for e in check_entries(entries,blobs.__getitem__))


def test_synthetic_fixture_changes_are_detected():
    blobs,entries=fixture({'examples/test.csv':b'changed'},{'examples/test.csv':hashlib.sha256(b'original synthetic').hexdigest()})
    assert any('sintético modificado' in e for e in check_entries(entries,blobs.__getitem__))


def test_token_patterns_and_symlinks_are_denied():
    blobs,entries=fixture({'app.py':('ghp_'+'A'*36).encode()})
    assert any('Posible secreto' in e for e in check_entries(entries,blobs.__getitem__))
    assert any('Enlace' in e for e in check_entries([('app.py','120000'),('public-files.json','100644')],blobs.__getitem__))

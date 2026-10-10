import io,json,subprocess,sys,time,zipfile
from pathlib import Path
import pytest
from cryptography.fernet import InvalidToken
from fastapi.testclient import TestClient
from app.analytics import normalize,calculate
from app.store import Store
from app.rag import vector,search

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('SALUD_DATA',str(tmp_path/'initial'))
    from app import main
    main.store.lock();fresh=Store(tmp_path/'profile')
    monkeypatch.setattr(main,'store',fresh);monkeypatch.setattr(main,'ROOT',fresh.root)
    main.SESSIONS.clear();main.JOBS.clear();main.FAILURES.clear();main.LAST_ACTIVE=time.monotonic()
    with TestClient(main.app,base_url='http://127.0.0.1:8765',headers={'X-Salud-Local':'1'}) as c:
        assert c.get('/api/status').status_code==200
        yield c,main
    fresh.lock()

def upload(c,rows,name='data.json'):
    return c.post('/api/import',files={'file':(name,json.dumps(rows).encode(),'application/json')})

def demo(c):
    response=c.post('/api/demo',json={});assert response.status_code==200,response.text
    doc=response.json()['id'];e=c.get('/api/documents/'+doc).json()['extraction']
    response=c.post('/api/documents/'+doc+'/confirm',json=e);assert response.status_code==200,response.text
    return doc

def job(c,path,body):
    response=c.post(path,json=body);assert response.status_code==200,response.text
    for _ in range(100):
        state=c.get('/api/jobs/'+response.json()['job_id']).json()
        if state['status']!='running':return state
        time.sleep(.02)
    pytest.fail('Trabajo no termina')

@pytest.mark.parametrize('patch,issue',[
 ({'date':'03/04/2026'},'Fecha'),({'date':'2026-02-30'},'Fecha'),({'date':'2099-01-01'},'Fecha'),
 ({'metric':'weight','value':780,'unit':'kg'},'Valor'),({'value':'NaN'},'Valor'),({'unit':'g/L'},'Unidad'),({'metric':'inventado'},'Indicador')])
def test_validation(patch,issue):
    row={'date':'2026-01-01','metric':'glucose','value':100,'unit':'mg/dL'}|patch
    assert any(issue in e for e in normalize(row)['issues'])

def test_conversion():
    r=normalize({'date':'2026-01-01','metric':'Glucosa','value':'5,5','unit':'mmol/L'})
    assert r['value']==pytest.approx(99.1001);assert r['unit']=='mg/dL';assert not r['issues'];assert 'Conversión' in r['note']

def test_trends_same_day_and_zero():
    rows=[{'id':str(i),'date':d,'metric':'steps','value':v,'source':'doc'} for i,(d,v) in enumerate([('2026-01-01',0),('2026-02-01',10),('2026-02-01',20)])]
    t=calculate(rows)[0];assert t['latest']==15;assert t['percent'] is None;assert len(t['series'])==2
    rows[0]['value']=5;assert calculate(rows)[0]['percent']==200

def test_outliers():
    rows=[{'id':str(i),'date':f'2026-01-{i+1:02d}','metric':'glucose','value':v,'source':'doc'} for i,v in enumerate([99,100,101,99,102,400])]
    assert calculate(rows)[0]['outliers']==['2026-01-06']

def test_encrypted_vault_password(tmp_path):
    s=Store(tmp_path/'vault');s.set_setting('secret','SYNTHETIC_SECRET_123');s.original('abc',b'SYNTHETIC_DOCUMENT');s.save()
    assert b'SYNTHETIC_SECRET' not in (s.root/'vault.bin').read_bytes();assert b'SYNTHETIC_DOCUMENT' not in (s.root/'originals/abc.bin').read_bytes()
    s.set_password('test-password-local-only');s.lock();assert 'plain' not in json.loads((s.root/'key.json').read_text())
    with pytest.raises(InvalidToken):s.unlock('wrong')
    s.unlock('test-password-local-only');assert s.setting('secret')=='SYNTHETIC_SECRET_123';assert s.original('abc')==b'SYNTHETIC_DOCUMENT';s.lock()

def test_end_to_end_review_traceability(client):
    c,m=client;doc=demo(c);data=c.get('/api/data').json();assert len(data['observations'])==36;assert all(r['source']==doc for r in data['observations'])
    first=job(c,'/api/reviews',{'use_ai':False});assert first['status']=='done'
    p=c.get('/api/reviews/'+first['result_id']).json()['payload'];assert {s['area'] for s in p['sections']}==set(m.AREAS);assert p['source_ids']==[doc];assert p['ai'] is None
    second=job(c,'/api/reviews',{'use_ai':False});p=c.get('/api/reviews/'+second['result_id']).json()['payload'];assert 'No hay cambios' in p['changes'][0]
    result=job(c,'/api/chat',{'use_ai':False,'question':'colesterol LDL'});assert result['status']=='done';assert c.get('/api/chats').json()[0]['payload']['evidence']
    assert c.get('/api/documents/'+doc+'/original').content==Path('examples/ejemplo-sintetico.json').read_bytes()

def test_review_required_duplicates_and_invalid(client):
    c,m=client;rows=[{'date':'03/04/2026','metric':'glucose','value':100,'unit':'mg/dL'}]
    r=upload(c,rows);assert r.status_code==200;id=r.json()['id'];assert not c.get('/api/data').json()['observations']
    e=c.get('/api/documents/'+id).json()['extraction'];assert c.post('/api/documents/'+id+'/confirm',json=e).status_code==422
    e['observations'][0]['date']='2026-04-03';e['observations'].append(e['observations'][0].copy())
    r=c.post('/api/documents/'+id+'/confirm',json=e);assert r.json()=={'added':1,'duplicates':1}
    assert upload(c,rows).status_code==409;assert c.post('/api/documents/'+id+'/confirm',json=e).status_code==409

def test_host_csrf_csp_lock_timeout(client):
    c,m=client
    assert c.get('/api/data',headers={'Host':'evil.example'}).status_code==403
    assert c.post('/api/settings',json={},headers={'Origin':'https://evil.example'}).status_code==403
    assert c.post('/api/settings',json={},headers={'X-Salud-Local':''}).status_code==403
    assert "default-src 'none'" in c.get('/').headers['Content-Security-Policy'];assert c.get('/').headers['Cache-Control']=='no-store'
    assert c.post('/api/settings',json={'password':'long-test-password','timeout':1}).status_code==200
    c.post('/api/lock',json={});assert c.get('/api/data').status_code==401
    assert c.post('/api/unlock',json={'password':'wrong'}).status_code==401
    assert c.post('/api/unlock',json={'password':'long-test-password'}).status_code==200
    assert c.get('/api/data').status_code==200;m.LAST_ACTIVE-=61;assert c.get('/api/data').status_code==401

def test_export_erase_restore(client):
    c,m=client;doc=demo(c);backup=c.get('/api/export').content
    archive=zipfile.ZipFile(io.BytesIO(backup));assert 'originals/'+doc+'.bin' in archive.namelist()
    assert c.post('/api/erase',json={'confirmation':'bad'}).status_code==400
    assert c.post('/api/erase',json={'confirmation':'BORRAR TODO'}).status_code==200
    c.get('/api/status');assert not c.get('/api/data').json()['documents'];assert not list((m.ROOT/'originals').glob('*.bin'))
    r=c.post('/api/restore',files={'file':('backup.zip',backup,'application/zip')});assert r.status_code==200,r.text
    c.get('/api/status');assert len(c.get('/api/data').json()['observations'])==36

def test_upload_malicious_and_zip_traversal(client):
    c,m=client
    for name,content,mime,code in [('x.pdf',b'<script>bad</script>','application/pdf',422),('x.csv',b'PKevil','text/csv',415),('x.json',b'{}','image/png',415),('x.exe',b'xxx','application/octet-stream',415),('x.csv',b'x'*(11*1024*1024),'text/csv',413)]:
        assert c.post('/api/import',files={'file':(name,content,mime)}).status_code==code
    r=upload(c,[],name='../../safe.json');assert r.status_code==200;assert c.get('/api/documents/'+r.json()['id']).json()['name']=='safe.json'
    c.post('/api/erase',json={'confirmation':'BORRAR TODO'});c.get('/api/status');b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z:z.writestr('../outside',b'evil');z.writestr('key.json','{}');z.writestr('vault.bin','bad')
    assert c.post('/api/restore',files={'file':('x.zip',b.getvalue(),'application/zip')}).status_code==422;assert not (m.ROOT.parent/'outside').exists()

def test_delete_removes_derived_history(client):
    c,m=client;doc=demo(c);job(c,'/api/reviews',{'use_ai':False});c.delete('/api/documents/'+doc)
    assert not c.get('/api/data').json()['reviews'];assert not m.store.rows('SELECT * FROM chunks');assert not list((m.ROOT/'originals').glob('*.bin'))

def test_rag_literal_source():
    text='colesterol LDL medido en ayunas';rows=[{'id':'c','source':'d','locator':'Página 2','text':text,'vector':json.dumps(vector(text))}]
    result=search(rows,'colesterol LDL');assert result[0]['text']==text;assert result[0]['source']=='d';assert search(rows,'')==[]

def test_egress_guard_actual_socket_calls():
    code='''from app.security import install
import socket
install()
for host,port in [('1.1.1.1',443),('example.com',443),('127.0.0.1',11434),('::1',11435)]:
    try: socket.create_connection((host,port),timeout=.1)
    except PermissionError: pass
    else: raise AssertionError('egress was not denied')
try: socket.getaddrinfo('example.com',443)
except PermissionError: pass
else: raise AssertionError('DNS permitted')
try:
    s=socket.socket();s.bind(('0.0.0.0',0))
except PermissionError: pass
else: raise AssertionError('wildcard bind permitted')
print('blocked')'''
    p=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True);assert p.returncode==0,p.stderr;assert p.stdout.strip()=='blocked'

def test_llm_sequence(monkeypatch):
    from app import llm
    order=[];monkeypatch.setattr(llm,'generate',lambda model,context,role,previous:(order.append(model) or {'INTERPRETACIÓN':[]}))
    result=llm.pipeline({'baseline':'a','critic':'b','synthesis':'c','sequential':True},{},lambda _:None)
    assert order==['a','b','c'];assert len(result['runs'])==3

def test_llm_rejects_unknown_source(monkeypatch):
    from app import llm
    monkeypatch.setattr(llm,'models',lambda:['test'])
    monkeypatch.setattr(llm,'request',lambda path,*args,**kw: {} if path=='/api/show' else {'message':{'content':json.dumps({'INTERPRETACIÓN':[{'text':'bad','sources':['invented']}]})}})
    with pytest.raises(RuntimeError,match='fuente inexistente'):llm.generate('test',{'source_ids':['real']})

def test_ui_has_no_remote_assets():
    import re
    for path in Path('app/static').iterdir():assert not re.search(r'https?://(?!127\.0\.0\.1)',path.read_text())
    js=Path('app/static/app.js').read_text();assert 'localStorage' not in js and 'sessionStorage' not in js

def test_backup_password_and_corruption_do_not_replace_profile(client):
    c,m=client;demo(c);c.post('/api/settings',json={'password':'backup-test-password'});backup=c.get('/api/export').content
    c.post('/api/erase',json={'confirmation':'BORRAR TODO'});c.get('/api/status')
    before=(m.ROOT/'key.json').read_bytes()
    assert c.post('/api/restore',files={'file':('copy.zip',backup,'application/zip')},data={'password':'wrong'}).status_code==422
    assert (m.ROOT/'key.json').read_bytes()==before
    assert c.post('/api/restore',files={'file':('copy.zip',backup,'application/zip')},data={'password':'backup-test-password'}).status_code==200
    assert c.get('/api/status').json()['locked']
    c.post('/api/unlock',json={'password':'backup-test-password'});assert len(c.get('/api/data').json()['observations'])==36

def test_strict_iso_date():
    assert normalize({'date':'20260101','metric':'ldl','value':100,'unit':'mg/dL'})['issues']

def test_pdf_and_image_extraction(client):
    c,m=client
    for name,mime in [('analitica-sintetica.pdf','application/pdf'),('analitica-sintetica.png','image/png')]:
        r=c.post('/api/import',files={'file':(name,(Path('examples')/name).read_bytes(),mime)})
        assert r.status_code==200,r.text
        doc=c.get('/api/documents/'+r.json()['id']).json()
        assert doc['extraction']['observations'],doc['text']
        assert any(row['metric']=='glucose' for row in doc['extraction']['observations'])
        assert not c.get('/api/data').json()['observations']

def test_no_plaintext_upload_spooling_and_no_telemetry(client):
    from starlette.formparsers import MultiPartParser
    c,m=client
    assert MultiPartParser.spool_max_size>m.MAX_FILE
    assert all(m.app._telemetry[k] is False for k in ('tracing','metrics','logs','auto_configure'))

def test_diagnostics_failure_privacy_and_retention(client,monkeypatch):
    c,m=client
    from app import parser
    secret='SYNTHETIC_PRIVATE_FAILURE'
    def fail(*args): raise ValueError(secret)
    monkeypatch.setattr(parser,'extract',fail)
    for _ in range(52):
        response=c.post('/api/import',files={'file':(secret+'.pdf',b'%PDF-SYNTHETIC','application/pdf')})
        assert response.status_code==422 and secret not in response.text
    response=c.get('/api/diagnostics')
    assert len(response.json()['events'])==50
    assert secret not in response.text
    assert response.json()['events'][0]['error']=='extraction_failed'
    assert 'salud-local-diagnostico.json' in response.headers['content-disposition']
    assert response.headers['cache-control']=='no-store'
    assert b'extraction_failed' not in (m.ROOT/'vault.bin').read_bytes()
    assert c.delete('/api/diagnostics').status_code==200
    assert c.get('/api/diagnostics').json()['events']==[]

def test_diagnostic_download_reextract_confirm_delete(client):
    c,m=client
    rows=[{'date':'2025-07-09','metric':'glucose','value':97.3,'unit':'mg/dL','note':'SYNTHETIC_PRIVATE_NOTE'}]
    doc=upload(c,rows,'SYNTHETIC_PRIVATE_NAME.json').json()['id']
    response=c.get('/api/documents/'+doc+'/diagnostics')
    assert response.json()['events'][0]['counts']['proposals']==1
    for secret in ('SYNTHETIC_PRIVATE','2025-07-09','97.3','glucose',doc): assert secret not in response.text
    assert c.post('/api/documents/'+doc+'/reextract',json={}).status_code==200
    assert not c.get('/api/data').json()['observations']
    assert len(c.get('/api/diagnostics').json()['events'])==2
    e=c.get('/api/documents/'+doc).json()['extraction']
    assert c.post('/api/documents/'+doc+'/confirm',json=e).status_code==200
    assert c.post('/api/documents/'+doc+'/reextract',json={}).status_code==409
    assert c.delete('/api/documents/'+doc).status_code==200
    assert c.get('/api/diagnostics').json()['events']==[]
    assert c.get('/api/documents/'+doc+'/diagnostics').status_code==404

def test_old_documents_and_trace_deletion(client):
    c,m=client
    doc=upload(c,[]).json()['id']
    assert c.delete('/api/diagnostics').status_code==200
    assert c.get('/api/documents/'+doc+'/diagnostics').json()['events'][0]['error']=='diagnostics_unavailable'
    assert c.get('/api/documents/'+doc).status_code==200
    assert c.post('/api/documents/'+doc+'/reextract',json={}).status_code==200
    assert c.get('/api/documents/'+doc+'/diagnostics').json()['events'][0]['error']=='none'
    assert c.post('/api/erase',json={'confirmation':'BORRAR TODO'}).status_code==200
    c.get('/api/status')
    assert c.get('/api/diagnostics').json()['events']==[]

def test_diagnostics_require_authenticated_session(client):
    c,m=client
    doc=upload(c,[]).json()['id']
    c.cookies.clear()
    for path in ('/api/diagnostics','/api/documents/'+doc+'/diagnostics'):
        assert c.get(path).status_code==401
    assert c.delete('/api/diagnostics').status_code==401
    assert c.post('/api/documents/'+doc+'/reextract',json={}).status_code==401

def test_pdf_columns_date_and_qualifier_end_to_end(client):
    # Entirely invented PDF, built in RAM. Separate text objects mimic tabular columns.
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
    c,m=client
    writer=PdfWriter();page=writer.add_blank_page(width=600,height=800)
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
    stream=DecodedStreamObject();stream.set_data(b'BT /F1 12 Tf 1 0 0 1 30 730 Tm (Fecha muestra: 22/08/2025) Tj ET\n'
        b'BT /F1 12 Tf 1 0 0 1 30 680 Tm (Glucosa \\(suero/plasma\\)) Tj ET\n'
        b'BT /F1 12 Tf 1 0 0 1 300 680 Tm (97,3) Tj ET\n'
        b'BT /F1 12 Tf 1 0 0 1 370 680 Tm (mg/dL) Tj ET\n'
        b'BT /F1 12 Tf 1 0 0 1 450 680 Tm ([60 - 120]) Tj ET\n'
        b'BT /F1 12 Tf 1 0 0 1 30 650 Tm (Ferritina) Tj ET\n'
        b'BT /F1 12 Tf 1 0 0 1 300 650 Tm (105) Tj ET\n'
        b'BT /F1 12 Tf 1 0 0 1 370 650 Tm (ng/mL) Tj ET\n'
        b'BT /F1 12 Tf 1 0 0 1 30 620 Tm (Leucocitos) Tj ET\n'
        b'BT /F1 12 Tf 1 0 0 1 300 620 Tm (6,7) Tj ET\n'
        b'BT /F1 12 Tf 1 0 0 1 370 620 Tm (x10^3/mm3) Tj ET')
    page[NameObject('/Contents')]=writer._add_object(stream)
    buffer=io.BytesIO();writer.write(buffer)
    response=c.post('/api/import',files={'file':('synthetic-columns.pdf',buffer.getvalue(),'application/pdf')})
    assert response.status_code==200,response.text
    doc=c.get('/api/documents/'+response.json()['id']).json()
    row=doc['extraction']['observations'][0]
    assert row['date']=='2025-08-22' and row['value']==97.3 and row['unit']=='mg/dL'
    assert row['locator']=='Página 1' and not row['issues']
    other={r['metric']:r for r in doc['extraction']['observations']}
    assert other['ferritin']['value']==105 and other['ferritin']['unit']=='ng/mL'
    assert other['leukocytes']['value']==6.7 and other['leukocytes']['unit']=='10^3/µL'
    assert doc['status']=='pending' and not c.get('/api/data').json()['observations']
    report=c.get('/api/documents/'+doc['id']+'/diagnostics').json()['events'][0]
    assert report['counts']['qualified_labels']==1 and report['counts']['date_recognized']==1

def test_added_series_in_review_and_original_traces(client):
    c,m=client
    rows=[{'date':d,'metric':metric,'value':value,'unit':unit} for d in ('2025-07-09','2025-08-22')
          for metric,value,unit in [('creatinine',1.03,'mg/dL'),('ferritin',105,'ng/mL'),('ast',27,'U/L'),('psa',1.24,'ng/mL')]]
    doc=upload(c,rows).json()['id']
    extraction=c.get('/api/documents/'+doc).json()['extraction']
    assert not c.get('/api/data').json()['observations']
    assert c.post('/api/documents/'+doc+'/confirm',json=extraction).status_code==200
    state=job(c,'/api/reviews',{'use_ai':False})
    assert state['status']=='done'
    review=c.get('/api/reviews/'+state['result_id']).json()['payload']
    areas={section['area']:section['items'] for section in review['sections']}
    for area in ('Función renal','Hematología','Función hepática','Otros resultados de laboratorio'):
        assert any(item['type']=='DATO' and item['sources']==[doc] for item in areas[area])
    assert all(trend['sources']==[doc] and trend['percent']==0 for trend in review['trends'])

def test_censored_result_can_be_confirmed_as_literal_without_numeric_trend(client):
    c,m=client
    rows=[{'date':'2025-08-22','metric':'ferritin','value':'≤2,7','unit':'ng/mL','locator':'Página 2'},
          {'date':'2025-08-22','metric':'glucose','value':97.3,'unit':'mg/dL'}]
    doc=upload(c,rows).json()['id']
    extraction=c.get('/api/documents/'+doc).json()['extraction']
    assert c.post('/api/documents/'+doc+'/confirm',json=extraction).status_code==422
    row=extraction['observations'][0]
    response=c.post('/api/literal-proposal',json={'row':row})
    assert response.status_code==200
    record=response.json()
    data=c.get('/api/data').json()
    assert not data['observations'] and not data['records']
    extraction['observations']=extraction['observations'][1:]
    extraction['records'].append(record)
    assert c.post('/api/documents/'+doc+'/confirm',json=extraction).status_code==200
    data=c.get('/api/data').json()
    assert len(data['observations'])==1 and data['observations'][0]['metric']=='glucose'
    assert data['records'][0]['source']==doc and data['records'][0]['kind']=='lab_result'
    assert '≤2,7' in data['records'][0]['detail']
    assert all(t['metric']!='ferritin' for t in data['trends'])
    state=job(c,'/api/reviews',{'use_ai':False});assert state['status']=='done'
    review=c.get('/api/reviews/'+state['result_id']).json()['payload']
    lab=next(s for s in review['sections'] if s['area']=='Otros resultados de laboratorio')
    assert any(i['type']=='EVIDENCIA' and '≤2,7' in i['text'] and i['sources']==[doc] for i in lab['items'])
    report=c.get('/api/documents/'+doc+'/diagnostics')
    assert '≤2,7' not in report.text and 'ferritin' not in report.text
    assert report.json()['events'][0]['counts']['validation_comparator']==1
    assert report.json()['events'][0]['counts']['validation_numeric']==0
    assert c.delete('/api/documents/'+doc).status_code==200
    data=c.get('/api/data').json();assert not data['records'] and not data['reviews']

def test_literal_proposal_endpoint_validation_and_auth(client):
    c,m=client
    row={'date':'2025-08-22','metric':'ferritin','value':'105','unit':'ng/mL'}
    assert c.post('/api/literal-proposal',json={'row':row}).status_code==422
    assert c.post('/api/literal-proposal',json={'row':[]}).status_code==400
    c.cookies.clear()
    assert c.post('/api/literal-proposal',json={'row':row|{'value':'≤2,7'}}).status_code==401

def test_password_rotation_invalidates_other_sessions(client):
    c,m=client
    other=TestClient(m.app,base_url='http://127.0.0.1:8765',headers={'X-Salud-Local':'1'})
    other.get('/api/status');assert other.get('/api/data').status_code==200
    c.post('/api/settings',json={'password':'long-password-for-testing'})
    assert c.get('/api/data').status_code==200;assert other.get('/api/data').status_code==401

def test_model_numeric_claims_are_omitted(client,monkeypatch):
    from app import llm
    c,m=client
    monkeypatch.setattr(llm,'models',lambda:['test'])
    generated={'INTERPRETACIÓN':[{'text':'Reducción de 24 puntos porcentuales (-16.9%).','sources':['real']},{'text':'Los datos no incluyen el contexto de ayuno.','sources':['real']}]}
    monkeypatch.setattr(llm,'request',lambda path,*args,**kw: {} if path=='/api/show' else {'message':{'content':json.dumps(generated)}})
    result=llm.generate('test',{'source_ids':['real']})
    assert len(result['INTERPRETACIÓN'])==1
    assert 'ayuno' in result['INTERPRETACIÓN'][0]['text']
    assert any('omitido' in i['text'] for i in result['INCERTIDUMBRE'])
    doc=demo(c);t=next(t for t in c.get('/api/data').json()['trends'] if t['metric']=='ldl')
    assert t['delta']==-24 and t['unit']=='mg/dL';assert t['percent']==pytest.approx(-16.9014084507)

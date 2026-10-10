import base64
import datetime as dt
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from .store import Store
from .analytics import METRICS, normalize, calculate, literal_record
from . import rag, llm, diagnostics

BASE=Path(__file__).resolve().parent.parent
ROOT=Path(os.environ.get('SALUD_DATA',str(Path.home()/'Library'/'Application Support'/'SaludLocal'))).resolve()
store=Store(ROOT)
app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None,telemetry={'tracing':False,'metrics':False,'logs':False,'operation_spans':False,'auto_configure':False})
SESSIONS={}; LAST_ACTIVE=time.monotonic(); FAILURES=[]; JOBS={}; JOB_LOCK=threading.Lock()
MAX_FILE=10*1024*1024
# Multipart files stay in RAM until encrypted; never spill plaintext to /tmp.
from starlette.formparsers import MultiPartParser
MultiPartParser.spool_max_size=MAX_FILE+100000
ORIGIN='http://127.0.0.1:8765'

def uid(): return uuid.uuid4().hex

def now(): return dt.datetime.now(dt.timezone.utc).isoformat()

def session(response):
    token=secrets.token_urlsafe(32); SESSIONS[token]=True
    while len(SESSIONS)>32: SESSIONS.pop(next(iter(SESSIONS)))
    response.set_cookie('salud_session',token,httponly=True,samesite='strict',path='/')
    return response

def busy(): return any(j['status']=='running' for j in JOBS.values())

def require_idle():
    if busy(): raise HTTPException(409,'Hay un análisis activo. Espera a que termine antes de bloquear o borrar.')

def idle_lock_worker():
    while True:
        time.sleep(5)
        with store.mutex:
            if store.db and store.protected and not busy() and time.monotonic()-LAST_ACTIVE>store.setting('timeout',15)*60:
                SESSIONS.clear(); store.lock()

# Lock even when every browser tab has been closed and no HTTP requests arrive.
threading.Thread(target=idle_lock_worker,daemon=True).start()

@app.middleware('http')
async def secure(request:Request, call_next):
    global LAST_ACTIVE
    if request.headers.get('host')!='127.0.0.1:8765': return Response('Host no permitido',403)
    origin=request.headers.get('origin')
    if origin and origin!=ORIGIN: return Response('Origen no permitido',403)
    if request.headers.get('sec-fetch-site')=='cross-site': return Response('Acceso entre sitios bloqueado',403)
    if request.method not in ('GET','HEAD'):
        if request.headers.get('x-salud-local')!='1': return Response('Protección CSRF',403)
        try:
            size=int(request.headers.get('content-length','0'))
        except ValueError: return Response('Tamaño inválido',400)
        if size>MAX_FILE+100000: return Response('Máximo 10 MB',413)
        received=0; body=[]
        async for chunk in request.stream():
            received+=len(chunk)
            if received>MAX_FILE+100000: return Response('Máximo 10 MB',413)
            body.append(chunk)
        request._body=b''.join(body)
    path=request.url.path
    public=path in ('/api/status','/api/unlock') or not path.startswith('/api/')
    with store.mutex:
        timeout=store.setting('timeout',15) if store.db else 15
        if store.protected and time.monotonic()-LAST_ACTIVE>timeout*60 and not busy():
            SESSIONS.clear(); store.lock()
        if not public:
            if not store.db or request.cookies.get('salud_session') not in SESSIONS:
                return JSONResponse({'detail':'Aplicación bloqueada'},401)
            # Polling is not user activity; long jobs do not keep a session alive indefinitely.
            if not path.startswith('/api/jobs'): LAST_ACTIVE=time.monotonic()
    try:
        response=await call_next(request)
    except Exception:
        response=JSONResponse({'detail':'Operación no completada. Revisa el formato o vuelve a intentarlo.'},500)
    response.headers.update({'Content-Security-Policy':"default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; font-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'; object-src 'none'",'X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','Cache-Control':'no-store','X-Frame-Options':'DENY','Permissions-Policy':'camera=(), microphone=(), geolocation=()'})
    return response

@app.get('/api/status')
def status(request:Request):
    valid=store.db is not None and request.cookies.get('salud_session') in SESSIONS
    response=JSONResponse({'locked':store.protected and not valid,'protected':store.protected,'product':'Salud Local'})
    if not store.protected and not valid: session(response)
    return response

@app.post('/api/unlock')
def unlock(body:dict):
    global LAST_ACTIVE
    t=time.monotonic()
    FAILURES[:]=[f for f in FAILURES if t-f<300]
    if len(FAILURES)>=5: raise HTTPException(429,'Espera cinco minutos antes de volver a intentarlo')
    try: store.unlock(str(body.get('password',''))[:1024])
    except Exception:
        FAILURES.append(t); raise HTTPException(401,'Contraseña incorrecta o bóveda no disponible')
    LAST_ACTIVE=t; FAILURES.clear()
    return session(JSONResponse({'ok':True}))

@app.post('/api/lock')
def lock():
    with store.mutex:
        require_idle()
        if not store.protected: raise HTTPException(400,'Configura una contraseña para bloquear')
        store.lock(); SESSIONS.clear(); JOBS.clear()
    return {'ok':True}

@app.get('/api/data')
def data():
    with store.mutex:
        obs=store.rows('SELECT * FROM observations ORDER BY date DESC')
        docs=store.rows('SELECT id,name,mime,created,status,synthetic FROM documents ORDER BY created DESC')
        return {'observations':obs,'documents':docs,'records':store.rows('SELECT * FROM records ORDER BY date DESC'), 'trends':calculate(obs),'metrics':METRICS,
          'reviews':[{'id':r['id'],'created':r['created']} for r in store.rows('SELECT id,created FROM reviews ORDER BY created DESC')],
          'onboarded':store.setting('onboarded',False),
          'active_job':next(({'id':id,**j} for id,j in JOBS.items() if j['status']=='running'),None)}

@app.get('/api/settings')
def settings():
    with store.mutex:
        return {'models':store.setting('models',{'baseline':'qwen3.5:9b','critic':'','synthesis':'qwen3.5:9b','sequential':False}),
          'timeout':store.setting('timeout',15),'protected':store.protected,'data_path':str(ROOT),
          'network_guard':os.environ.get('SALUD_SANDBOX')=='1','ollama_url':'http://127.0.0.1:11435','ocr':bool(shutil.which('tesseract')),
          'rag':'Vectores léxicos locales de 512 dimensiones; búsqueda por similitud, sin embeddings externos.'}

@app.get('/api/models')
def models(): return {'models':llm.models()}

@app.post('/api/settings')
def set_settings(body:dict):
    with store.mutex:
        require_idle()
        if 'password' in body:
            password=str(body['password'])
            if not 12<=len(password)<=1024: raise HTTPException(400,'La contraseña debe tener al menos 12 caracteres')
            store.set_password(password)
        if 'timeout' in body:
            value=int(body['timeout'])
            if not 1<=value<=120: raise HTTPException(400,'Timeout entre 1 y 120 minutos')
            store.set_setting('timeout',value)
        if 'models' in body:
            conf=body['models']
            if not isinstance(conf,dict): raise HTTPException(400,'Configuración inválida')
            clean={k:str(conf.get(k,''))[:100] for k in ('baseline','critic','synthesis')}
            if any('cloud' in m.lower() or not re.fullmatch(r'[\w.:/\-]*',m) for m in clean.values()): raise HTTPException(400,'Modelo no permitido')
            clean['sequential']=bool(conf.get('sequential')); store.set_setting('models',clean)
        if 'onboarded' in body: store.set_setting('onboarded',True)
        store.save()
        if 'password' in body:
            SESSIONS.clear()
            return session(JSONResponse({'ok':True}))
    return {'ok':True}

def remember_diagnostic(payload, source=None):
    # Caller holds the vault mutex. Retain a bounded encrypted technical history.
    store.db.execute('INSERT INTO diagnostics(source,payload) VALUES (?,?)',(source,json.dumps(diagnostics.clean(payload))))
    store.db.execute('DELETE FROM diagnostics WHERE sequence NOT IN (SELECT sequence FROM diagnostics ORDER BY sequence DESC LIMIT 50)')

def extract_proposals(name, content, import_key, source=None):
    ext=Path(name).suffix.lower().lstrip('.')
    try:
        from .parser import extract
        parsed=extract(name,content)
        candidates=[normalize(r) for r in parsed['candidates']]
    except Exception as exc:
        from .parser import ExtractionError
        code=exc.code if isinstance(exc,ExtractionError) else 'extraction_failed'
        with store.mutex:
            if store.db and store.key==import_key and (not source or store.rows('SELECT id FROM documents WHERE id=?',(source,))):
                remember_diagnostic(diagnostics.report(ext,error=code),source);store.save()
        raise HTTPException(422,'No se pudo extraer con seguridad. Descarga el diagnóstico técnico en Privacidad. Máximo 40 páginas, 8 escaneadas, 20 megapíxeles o 2000 filas. Comprueba el archivo.') from None
    return {'observations':candidates,'records':parsed['records'],'notices':parsed['notices'],
        'pages':parsed['pages'],'diagnostic':diagnostics.report(ext,parsed,candidates)}

def ingest(filename, mime, content, synthetic=False):
    ext=Path(filename).suffix.lower()
    allowed={'.pdf':{'application/pdf'},'.csv':{'text/csv','application/vnd.ms-excel','text/plain'},'.json':{'application/json','text/plain'},'.png':{'image/png'},'.jpg':{'image/jpeg'},'.jpeg':{'image/jpeg'}}
    if ext not in allowed or mime not in allowed[ext]|{'application/octet-stream'}: raise HTTPException(415,'Usa PDF, CSV, JSON, PNG o JPEG con un tipo compatible')
    if not content or len(content)>MAX_FILE: raise HTTPException(413,'Archivo vacío o mayor de 10 MB')
    if content.startswith(b'PK'): raise HTTPException(415,'No se aceptan ZIP ni documentos ofimáticos comprimidos')
    safe=re.sub(r'[^\w.() -]','_',filename.replace('\\','/').split('/')[-1])[:120]
    digest=hashlib.sha256(content).hexdigest()
    with store.mutex:
        import_key=store.key
        exists=store.rows('SELECT id FROM documents WHERE sha=?',(digest,))
        if exists: raise HTTPException(409,'Este documento ya está importado')
    pending=extract_proposals(safe,content,import_key)
    doc_id=uid()
    with store.mutex:
        if not store.db or store.key!=import_key: raise HTTPException(401,'Perfil cambiado o sesión bloqueada; vuelve a importar')
        if store.rows('SELECT id FROM documents WHERE sha=?',(digest,)): raise HTTPException(409,'Documento duplicado')
        store.original(doc_id,content)
        store.db.execute('INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?)',(doc_id,safe,digest,mime,'\n'.join(p['text'] for p in pending['pages']),now(),'pending',json.dumps(pending),int(synthetic)))
        remember_diagnostic(pending['diagnostic'],doc_id)
        store.save()
    return {'id':doc_id}

@app.post('/api/import')
async def import_file(file:UploadFile=File(...)):
    # Run CPU/document processing in a thread; upload parsing is bounded by middleware.
    from starlette.concurrency import run_in_threadpool
    content=await file.read(MAX_FILE+1)
    return await run_in_threadpool(ingest,file.filename or 'archivo',file.content_type or '',content)

@app.get('/api/documents/{doc_id}')
def document(doc_id:str):
    with store.mutex:
        rows=store.rows('SELECT * FROM documents WHERE id=?',(doc_id,))
        if not rows: raise HTTPException(404,'Documento no encontrado')
        doc=rows[0]; doc['extraction']=json.loads(doc.pop('candidates')); return doc

@app.get('/api/documents/{doc_id}/original')
def original(doc_id:str):
    with store.mutex:
        docs=store.rows('SELECT name FROM documents WHERE id=?',(doc_id,))
        if not docs: raise HTTPException(404,'Documento no encontrado')
        # Always download: never render active originals in our origin.
        from urllib.parse import quote
        return Response(store.original(doc_id),media_type='application/octet-stream',headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(docs[0]['name'])})

def diagnostic_response(events):
    return JSONResponse(diagnostics.download(events),headers={'Content-Disposition':'attachment; filename="salud-local-diagnostico.json"'})

@app.get('/api/diagnostics')
def diagnostic_history():
    with store.mutex:
        return diagnostic_response([json.loads(row['payload']) for row in store.rows('SELECT payload FROM diagnostics ORDER BY sequence DESC LIMIT 50')])

@app.get('/api/documents/{doc_id}/diagnostics')
def document_diagnostic(doc_id:str):
    with store.mutex:
        rows=store.rows('SELECT candidates FROM documents WHERE id=?',(doc_id,))
        if not rows: raise HTTPException(404,'Documento no encontrado')
        payload=json.loads(rows[0]['candidates']).get('diagnostic',{'error':'diagnostics_unavailable'})
        return diagnostic_response([payload])

@app.delete('/api/diagnostics')
def clear_diagnostics():
    with store.mutex:
        require_idle()
        store.db.execute('DELETE FROM diagnostics')
        for row in store.rows('SELECT id,candidates FROM documents'):
            payload=json.loads(row['candidates']);payload.pop('diagnostic',None)
            store.db.execute('UPDATE documents SET candidates=? WHERE id=?',(json.dumps(payload),row['id']))
        store.save()
    return {'ok':True}

@app.post('/api/documents/{doc_id}/reextract')
def reextract(doc_id:str):
    with store.mutex:
        rows=store.rows('SELECT name,status,candidates FROM documents WHERE id=?',(doc_id,))
        if not rows: raise HTTPException(404,'Documento no encontrado')
        snapshot=rows[0]
        if snapshot['status']!='pending': raise HTTPException(409,'Solo se pueden volver a extraer documentos pendientes')
        import_key=store.key;content=store.original(doc_id)
    pending=extract_proposals(snapshot['name'],content,import_key,doc_id)
    with store.mutex:
        if not store.db or store.key!=import_key: raise HTTPException(401,'Perfil cambiado o sesión bloqueada')
        current=store.rows('SELECT status,candidates FROM documents WHERE id=?',(doc_id,))
        if not current or current[0]['status']!='pending' or current[0]['candidates']!=snapshot['candidates']:
            raise HTTPException(409,'El documento ha cambiado; vuelve a abrir la revisión')
        store.db.execute('UPDATE documents SET text=?,candidates=? WHERE id=?',('\n'.join(p['text'] for p in pending['pages']),json.dumps(pending),doc_id))
        remember_diagnostic(pending['diagnostic'],doc_id);store.save()
    return {'ok':True}

@app.post('/api/literal-proposal')
def prepare_literal(body:dict):
    row=body.get('row')
    if not isinstance(row,dict): raise HTTPException(400,'Propuesta inválida')
    try: return literal_record(row)
    except ValueError as exc: raise HTTPException(422,str(exc)) from None

@app.post('/api/documents/{doc_id}/confirm')
def confirm(doc_id:str,body:dict):
    raw=body.get('observations',[]); records=body.get('records',[])
    if not isinstance(raw,list) or len(raw)>2000 or not isinstance(records,list) or len(records)>200: raise HTTPException(400,'Demasiadas entradas')
    normalized=[normalize(r) for r in raw]
    if any(r['issues'] for r in normalized): raise HTTPException(422,{'message':'Corrige las filas antes de confirmar','rows':normalized})
    clean_records=[]
    for r in records:
        if r.get('kind') not in ('medication','condition','note','prevention','lab_result') or not r.get('title'): raise HTTPException(422,'Registro: elige medication, condition, note, prevention o lab_result y un título')
        try:
            date=dt.date.fromisoformat(r.get('date',''))
            if date>dt.date.today() or date.year<1900: raise ValueError()
        except ValueError: raise HTTPException(422,'Fecha de registro inválida')
        clean_records.append({k:str(r.get(k,''))[:2000] for k in ('kind','title','date','detail')})
    with store.mutex:
        docs=store.rows('SELECT * FROM documents WHERE id=?',(doc_id,))
        if not docs: raise HTTPException(404,'Documento no encontrado')
        if docs[0]['status']!='pending': raise HTTPException(409,'Documento ya revisado')
        added=duplicates=0
        for row in normalized:
            cursor=store.db.execute('INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?,?,?,?)',(uid(),row['date'],row['metric'],row['value'],row['unit'],doc_id,row['locator'],row['note']))
            added+=cursor.rowcount; duplicates+=1-cursor.rowcount
        for r in clean_records:
            store.db.execute('INSERT INTO records VALUES (?,?,?,?,?,?)',(uid(),r['kind'],r['title'],r['date'],r['detail'],doc_id))
        extract=json.loads(docs[0]['candidates'])
        for chunk in rag.chunks(extract['pages']):
            store.db.execute('INSERT INTO chunks VALUES (?,?,?,?,?)',(uid(),doc_id,chunk['locator'],chunk['text'],json.dumps(chunk['vector'])))
        # Keep both raw proposal and reviewed payload for auditability.
        extract['confirmed']={'observations':normalized,'records':clean_records,'at':now()}
        store.db.execute('UPDATE documents SET status=?,candidates=? WHERE id=?',('confirmed',json.dumps(extract),doc_id)); store.save()
    return {'added':added,'duplicates':duplicates}

@app.post('/api/demo')
def demo():
    with store.mutex:
        if store.rows('SELECT id FROM documents'): raise HTTPException(409,'Carga la demostración solo en un perfil vacío para no mezclarla con datos reales')
    return ingest('ejemplo-sintetico.json','application/json',(BASE/'examples'/'ejemplo-sintetico.json').read_bytes(),True)

@app.delete('/api/documents/{doc_id}')
def delete_doc(doc_id:str):
    with store.mutex:
        require_idle()
        if not store.rows('SELECT id FROM documents WHERE id=?',(doc_id,)): raise HTTPException(404,'Documento no encontrado')
        for table in ('observations','records','chunks'): store.db.execute(f'DELETE FROM {table} WHERE source=?',(doc_id,))
        store.db.execute('DELETE FROM documents WHERE id=?',(doc_id,))
        store.db.execute('DELETE FROM diagnostics WHERE source=?',(doc_id,))
        # Derived histories can contain deleted data; remove them rather than leave stale evidence.
        store.db.execute('DELETE FROM reviews'); store.db.execute('DELETE FROM chats'); JOBS.clear(); store.save()
        (ROOT/'originals'/(doc_id+'.bin')).unlink(missing_ok=True)
    return {'ok':True}

def context(query):
    obs=store.rows('SELECT * FROM observations ORDER BY date')
    trends=calculate(obs)
    sources=store.rows('SELECT id,name,synthetic FROM documents WHERE status="confirmed"')
    return {'trends':trends,'records':store.rows('SELECT * FROM records'),
      'evidence':rag.search(store.rows('SELECT * FROM chunks'),query,6),'source_ids':[s['id'] for s in sources],
      'sources':sources,'observations':obs}

def llm_context(ctx,question):
    # Fixed input budget: aggregate longitudinal history and disclose omissions.
    trends=[{k:v for k,v in t.items() if k not in ('series','formula')} for t in ctx['trends']]
    return {'pregunta':question,'trends':trends,'records':ctx['records'][:20],'evidence':ctx['evidence'][:4],
      'source_ids':ctx['source_ids'],'limitaciones':'Contexto acotado: tendencias agregadas, hasta 20 registros y 4 fragmentos. Puede omitir información. Sin guías clínicas externas.'}

AREAS=['Resumen general','Cardiovascular','Metabólico','Hematología','Función renal','Función hepática','Otros resultados de laboratorio','Sueño','Actividad física','Medicación','Prevención','Temas a vigilar','Información faltante','Preguntas para la próxima consulta']

def deterministic_review(ctx,previous):
    sections=[]
    for area in AREAS:
        relevant=[t for t in ctx['trends'] if t['area']==area]
        items=[]
        if area=='Resumen general':
            items=[{'type':'DATO','text':f"{len(ctx['observations'])} medidas confirmadas en {len(ctx['sources'])} documentos. Esta cobertura no permite afirmar que el estado de salud sea normal.",'sources':ctx['source_ids']}]
        for t in relevant:
            items.append({'type':'CÁLCULO' if len(t['series'][-1]['ids'])>1 else 'DATO','text':f"{t['label']}: último valor diario {t['latest']:.2f} {t['unit']} ({t['series'][-1]['date']}).",'sources':t['sources']})
            if t['percent'] is not None:
                items.append({'type':'CÁLCULO','text':f"{t['label']}: cambio {t['percent']:+.1f}% desde {t['series'][0]['date']} hasta {t['series'][-1]['date']}. {t['formula']}",'sources':t['sources']})
        if area in ('Medicación','Prevención'):
            kind='medication' if area=='Medicación' else 'prevention'
            items=[{'type':'DATO','text':r['title']+' · '+r['detail']+' · Registrado '+r['date']+'; vigencia no verificada.','sources':[r['source']]} for r in ctx['records'] if r['kind']==kind]
        if area=='Otros resultados de laboratorio':
            items.extend({'type':'EVIDENCIA','text':r['title']+' · '+r['detail']+' · Registrado '+r['date'],
                          'sources':[r['source']]} for r in ctx['records'] if r['kind']=='lab_result')
        if area=='Temas a vigilar':
            items=[{'type':'CÁLCULO','text':f"{t['label']}: valores atípicos estadísticos en {', '.join(t['outliers'])}; no son alertas clínicas.",'sources':t['sources']} for t in ctx['trends'] if t['outliers']]
        if area=='Información faltante':
            items=[{'type':'INCERTIDUMBRE','text':'No se verifican antecedentes familiares, edad, síntomas, ayuno, contexto de las medidas, vacunación ni la lista completa de medicación. No hay guías clínicas incorporadas.','sources':[]}]
        if area=='Preguntas para la próxima consulta':
            items=[{'type':'RECOMENDACIÓN PARA CONSULTAR','text':'¿Son comparables mis mediciones y qué contexto falta? ¿Qué seguimiento y prevención corresponden a mis antecedentes? ¿Está actualizada mi lista de medicación?','sources':[]}]
        if not items: items=[{'type':'INCERTIDUMBRE','text':'Información insuficiente para valorar esta área. Ausencia de registros no equivale a ausencia de problemas.','sources':[]}]
        sections.append({'area':area,'items':items})
    old={t['metric']:t for t in previous.get('trends',[])} if previous else {}
    changes=[]
    for t in ctx['trends']:
        prior=old.get(t['metric'])
        if not prior: changes.append(f"{t['label']}: nueva serie desde la revisión anterior." if previous else f"{t['label']}: primera revisión, sin comparación previa.")
        elif prior['series']!=t['series']: changes.append(f"{t['label']}: serie actualizada; último valor {prior['latest']:.2f} → {t['latest']:.2f} {t['unit']}.")
    if previous and not changes: changes=['No hay cambios en las series desde la revisión anterior.']
    return {'sections':sections,'changes':changes,'trends':ctx['trends'],'evidence':ctx['evidence'],'source_ids':ctx['source_ids'],'ai':None,'synthetic':any(s['synthetic'] for s in ctx['sources']),
      'limitations':'Análisis descriptivo sin diagnóstico. No evalúa urgencias, riesgo clínico, interacciones farmacológicas ni adecuación de tratamientos. Los valores atípicos no son alertas médicas.'}

def start_job(kind,body):
    with JOB_LOCK,store.mutex:
        require_idle()
        if not store.rows('SELECT id FROM documents WHERE status="confirmed"'): raise HTTPException(400,'Confirma primero al menos un documento')
        question=str(body.get('question',''))[:1500] if kind=='chat' else 'salud cardiovascular metabólico hematología renal hepática laboratorio sueño actividad medicación prevención antecedentes'
        if kind=='chat' and not question.strip(): raise HTTPException(400,'Escribe una pregunta')
        ctx=context(question); config=store.setting('models',{'baseline':'qwen3.5:9b'})
        prior=store.rows('SELECT payload FROM reviews ORDER BY created DESC LIMIT 1')
        previous=json.loads(prior[0]['payload']) if prior else None
        job_id=uid(); JOBS[job_id]={'status':'running','progress':'Preparando datos confirmados','kind':kind}
        # Bound technical job history.
        for old in list(JOBS)[:-20]:
            if JOBS[old]['status']!='running': JOBS.pop(old,None)
    def work():
        try:
            result=deterministic_review(ctx,previous) if kind=='review' else {'question':question,'evidence':ctx['evidence'],'trends':ctx['trends'],'ai':None,'notice':'Respuesta descriptiva basada en registros; activa IA local para interpretación.'}
            if body.get('use_ai',True):
                result['ai']=llm.pipeline(config,llm_context(ctx,question),lambda msg:JOBS[job_id].update(progress=msg))
            rid=uid(); created=now()
            with store.mutex:
                if kind=='review': store.db.execute('INSERT INTO reviews VALUES (?,?,?)',(rid,created,json.dumps(result)))
                else: store.db.execute('INSERT INTO chats VALUES (?,?,?,?)',(rid,created,question,json.dumps(result)))
                store.save()
            JOBS[job_id].update(status='done',progress='Completado',result_id=rid)
        except Exception as exc:
            # No raw model output or document content in error logs/UI.
            message=str(exc) if isinstance(exc,RuntimeError) else 'No se pudo completar el análisis local. Comprueba Ollama o genera la revisión sin IA.'
            JOBS[job_id].update(status='error',progress=message[:250])
    threading.Thread(target=work,daemon=True).start()
    return {'job_id':job_id}

@app.post('/api/reviews')
def review(body:dict): return start_job('review',body)

@app.post('/api/chat')
def chat(body:dict): return start_job('chat',body)

@app.get('/api/jobs/{job_id}')
def job(job_id:str):
    if job_id not in JOBS: raise HTTPException(404,'Trabajo no encontrado')
    return JOBS[job_id]

@app.get('/api/reviews/{review_id}')
def get_review(review_id:str):
    with store.mutex:
        rows=store.rows('SELECT * FROM reviews WHERE id=?',(review_id,))
        if not rows: raise HTTPException(404,'Revisión no encontrada')
        return rows[0]|{'payload':json.loads(rows[0]['payload'])}

@app.get('/api/chats')
def chats():
    with store.mutex: return [r|{'payload':json.loads(r['payload'])} for r in store.rows('SELECT * FROM chats ORDER BY created DESC LIMIT 30')]

@app.get('/api/export')
def export():
    with store.mutex:
        require_idle(); store.save()
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w',zipfile.ZIP_STORED) as archive:
            for name in ('key.json','vault.bin'): archive.writestr(name,(ROOT/name).read_bytes())
            for path in (ROOT/'originals').glob('*.bin'): archive.writestr('originals/'+path.name,path.read_bytes())
            archive.writestr('FORMAT.txt','Salud Local backup v1. Encrypted vault and originals. key.json is password-wrapped only if you configured a password. Restore from the UI. No passwords included.\n')
        return Response(buffer.getvalue(),media_type='application/zip',headers={'Content-Disposition':'attachment; filename="salud-local-backup.zip"'})

@app.post('/api/restore')
async def restore(file:UploadFile=File(...), password:str=Form('')):
    content=await file.read(MAX_FILE+1)
    if len(content)>MAX_FILE: raise HTTPException(413,'Copia mayor de 10 MB: usa la restauración manual documentada')
    with store.mutex:
        require_idle()
        if store.rows('SELECT id FROM documents'): raise HTTPException(409,'Restaura en un perfil vacío')
        try:
            archive=zipfile.ZipFile(io.BytesIO(content))
            infos=archive.infolist()
            names=[i.filename for i in infos]
            if len(infos)>1000 or len(names)!=len(set(names)) or sum(i.file_size for i in infos)>50*1024*1024: raise ValueError()
            if not {'key.json','vault.bin'}.issubset(names): raise ValueError()
            if any(not re.fullmatch(r'(key\.json|vault\.bin|FORMAT\.txt|originals/[a-f0-9]{32}\.bin)',n) for n in names): raise ValueError()
            if any(i.compress_size and i.file_size/i.compress_size>50 for i in infos): raise ValueError()
            blobs={n:archive.read(n) for n in names if n!='FORMAT.txt'}
            cfg=json.loads(blobs['key.json'])
            if set(cfg) not in ({'plain'},{'salt','wrapped'}): raise ValueError()
            if 'salt' in cfg and len(base64.b64decode(cfg['salt'],validate=True))!=16: raise ValueError()
        except Exception: raise HTTPException(422,'Copia inválida o fuera de los límites de seguridad')
        from .store import atomic
        import tempfile
        # Authenticate and validate the entire copy before touching the live profile.
        try:
            with tempfile.TemporaryDirectory(prefix='.restore-',dir=ROOT) as staging:
                stage=Path(staging); (stage/'originals').mkdir(mode=0o700)
                for n,blob in blobs.items(): atomic(stage/n,blob)
                candidate=Store(stage)
                try:
                    candidate.unlock(password)
                    documents=candidate.rows('SELECT id FROM documents')
                    expected={'originals/'+d['id']+'.bin' for d in documents}
                    if any(not re.fullmatch(r'[a-f0-9]{32}',d['id']) for d in documents): raise ValueError()
                    if expected!={n for n in blobs if n.startswith('originals/')}: raise ValueError()
                    for d in documents: candidate.original(d['id'])
                    for row in candidate.rows('SELECT * FROM observations'):
                        if normalize(row)['issues'] or row['source'] not in {d['id'] for d in documents}: raise ValueError()
                finally: candidate.lock()
        except Exception: raise HTTPException(422,'Copia dañada, incompatible o contraseña incorrecta. El perfil actual no se ha modificado.')
        store.lock(); SESSIONS.clear(); JOBS.clear()
        for old in (ROOT/'originals').glob('*.bin'): old.unlink()
        for n,blob in blobs.items(): atomic(ROOT/n,blob)
        if not store.protected:
            try: store.unlock('')
            except Exception: raise HTTPException(422,'La copia no se puede abrir. Conserva la copia original y revisa recuperación en README.')
    return {'ok':True}

@app.post('/api/erase')
def erase(body:dict):
    if body.get('confirmation')!='BORRAR TODO': raise HTTPException(400,'Escribe BORRAR TODO')
    with store.mutex:
        require_idle(); store.lock(); SESSIONS.clear(); JOBS.clear()
        # Only known application files, never recursively delete user-selected paths.
        for p in (ROOT/'originals').glob('*.bin'): p.unlink()
        for name in ('vault.bin','vault.tmp','key.json','key.tmp'): (ROOT/name).unlink(missing_ok=True)
        fresh=Store(ROOT); store.db=fresh.db; store.key=fresh.key; store.fernet=fresh.fernet
    return {'ok':True}

@app.post('/api/shutdown')
def shutdown():
    with store.mutex:
        require_idle(); store.lock(); SESSIONS.clear()
    import signal
    threading.Timer(1,lambda:os.kill(os.getpid(),signal.SIGINT)).start()
    return {'ok':True}

app.mount('/static',StaticFiles(directory=BASE/'app'/'static'),name='static')
@app.get('/')
def index(): return FileResponse(BASE/'app'/'static'/'index.html')

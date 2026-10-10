"""Disposable document parser. Never runs document content. Bounded CPU/output/pages."""
import base64
import csv
import io
import json
import os
import re
import resource
import shutil
import subprocess
import sys
import warnings

resource.setrlimit(resource.RLIMIT_CPU, (40, 45))
resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
# macOS RLIMIT_AS is unreliable; data-segment bound plus strict page/pixel limits.
soft, hard = resource.getrlimit(resource.RLIMIT_DATA)
limit = min(1500*1024*1024, hard) if hard != resource.RLIM_INFINITY else 1500*1024*1024
try:
    resource.setrlimit(resource.RLIMIT_DATA, (limit, limit))
except (ValueError, OSError):
    pass  # Darwin can reject RLIMIT_DATA; parent also watches RSS.
warnings.simplefilter('error')
from app.analytics import ALIASES
from app.security import install
install()

def ocr(image):
    from PIL import Image
    image.thumbnail((2200,2200))
    buffer = io.BytesIO(); image.convert('RGB').save(buffer,format='PNG')
    exe = shutil.which('tesseract')
    if not exe: return ''
    result = subprocess.run([exe,'stdin','stdout','-l','eng'],input=buffer.getvalue(),stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=25)
    if result.returncode: raise ValueError('OCR no disponible')
    return result.stdout.decode('utf-8')[:120000]

def extract(name, data):
    ext = name.rsplit('.',1)[-1].lower()
    pages=[]; candidates=[]; records=[]; notices=[]
    if ext in ('csv','json'):
        text=data.decode('utf-8-sig')
        if len(text)>2_000_000: raise ValueError('Texto demasiado grande')
        if ext=='csv':
            dialect=csv.Sniffer().sniff(text[:4096],delimiters=',;\t')
            rows=list(csv.DictReader(io.StringIO(text),dialect=dialect))
        else:
            obj=json.loads(text)
            rows=obj if isinstance(obj,list) else obj.get('observations',[])
            records=[] if isinstance(obj,list) else obj.get('records',[])
        if not isinstance(rows,list) or len(rows)>2000 or not isinstance(records,list) or len(records)>200: raise ValueError('Máximo 2000 medidas y 200 registros')
        for i,row in enumerate(rows):
            if not isinstance(row,dict): raise ValueError('Se esperan objetos por fila')
            candidates.append({k:str(row.get(k,''))[:1000] for k in ('date','metric','value','unit','note')} | {'locator':f'Fila {i+2}'})
        for r in records:
            if not isinstance(r,dict): raise ValueError('Registro inválido')
        records=[{k:str(r.get(k,''))[:2000] for k in ('kind','title','date','detail')} for r in records]
        pages=[{'locator':'Contenido importado','text':text}]
    elif ext=='pdf':
        if not data.startswith(b'%PDF-'): raise ValueError('Firma PDF inválida')
        from pypdf import PdfReader
        reader=PdfReader(io.BytesIO(data),strict=True)
        if reader.is_encrypted: raise ValueError('PDF protegido: exporta una copia sin contraseña')
        if len(reader.pages)>40: raise ValueError('Máximo 40 páginas por PDF')
        scanned=0
        for i,page in enumerate(reader.pages):
            stream=page.get_contents()
            if stream and len(stream.get_data())>8_000_000: raise ValueError('Página demasiado compleja')
            text=page.extract_text() or ''
            if len(text.strip())<15:
                scanned+=1
                if scanned>8: raise ValueError('Máximo 8 páginas escaneadas por documento')
                import pypdfium2 as pdfium
                doc=pdfium.PdfDocument(data)
                p=doc[i]
                w,h=p.get_size()
                bmp=p.render(scale=min(2,2200/max(w,h)))
                text=ocr(bmp.to_pil())
                bmp.close(); p.close(); doc.close()
            pages.append({'locator':f'Página {i+1}','text':text[:120000]})
        notices.append('Extracción PDF orientativa: comprueba la página original. No se ejecuta contenido embebido.')
        if scanned: notices.append('OCR local en inglés; verifica especialmente decimales, signos y acentos.')
    elif ext in ('png','jpg','jpeg'):
        if not (data.startswith(b'\x89PNG\r\n\x1a\n') or data.startswith(b'\xff\xd8\xff')): raise ValueError('Firma de imagen inválida')
        from PIL import Image
        Image.MAX_IMAGE_PIXELS=20_000_000
        image=Image.open(io.BytesIO(data)); image.load()
        pages=[{'locator':'Imagen · OCR','text':ocr(image)}]
        notices.append('OCR local en inglés: toda la extracción requiere revisión visual.')
    else: raise ValueError('Formato no permitido')
    if sum(len(p['text']) for p in pages)>1_000_000: raise ValueError('Documento demasiado extenso')
    if ext not in ('csv','json'):
        for page in pages:
            dates=re.findall(r'\b\d{4}-\d{2}-\d{2}\b',page['text'])
            date=dates[0] if len(set(dates))==1 else ''
            for line in page['text'].splitlines():
                for alias in sorted(ALIASES,key=len,reverse=True):
                    m=re.match(r'\s*'+re.escape(alias)+r'\s*[:;\s]\s*([<>]?\s*\d+(?:[.,]\d+)?)\s*(mg/d[lL]|mmol/[lL]|mmHg|kg|%|h|pasos|lpm)',line,re.I)
                    if m:
                        candidates.append({'date':date,'metric':ALIASES[alias],'value':m[1],'unit':m[2], 'locator':page['locator'],'note':'Propuesta automática; cotejada por usuario al confirmar.'}); break
        if not candidates: notices.append('No se detectaron medidas reconocibles. Puedes añadirlas manualmente y conservar el documento como evidencia.')
    return {'pages':pages,'candidates':candidates,'records':records,'notices':notices}

if __name__=='__main__':
    try:
        request=json.loads(sys.stdin.buffer.read(16_000_000))
        result=extract(request['name'],base64.b64decode(request['data']))
        sys.stdout.write(json.dumps(result,ensure_ascii=False))
    except Exception:
        sys.stdout.write(json.dumps({'error':'No se pudo procesar el archivo con los límites de seguridad. Comprueba formato, páginas, tamaño o contraseña.'}))
        sys.exit(1)

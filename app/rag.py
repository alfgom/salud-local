"""Auditable offline lexical vector retrieval. No model downloads; no remote embeddings."""
import hashlib
import math
import re
from collections import Counter

DIM = 512
STOP = set('de la el los las un una y o en del que para con por a es se mi me al como qué cuál'.split())

def vector(text):
    counts = Counter(t for t in re.findall(r'[\wáéíóúñ]+',text.lower()) if len(t)>2 and t not in STOP)
    v = [0.0]*DIM
    for token, count in counts.items():
        i = int.from_bytes(hashlib.sha256(token.encode()).digest()[:4], 'little') % DIM
        v[i] += 1+math.log(count)
    norm = math.sqrt(sum(x*x for x in v)) or 1
    return [x/norm for x in v]

def chunks(pages):
    for page in pages:
        text = page['text']
        for offset in range(0, len(text), 900):
            content = text[offset:offset+1100]
            yield {'text':content,'locator':page['locator']+f' · caracteres {offset+1}–{offset+len(content)}','vector':vector(content)}

def search(rows, query, limit=5):
    import json
    q = vector(query)
    ranked = []
    for r in rows:
        score = sum(a*b for a,b in zip(q,json.loads(r['vector'])))
        if score > .025:
            ranked.append({k:v for k,v in r.items() if k!='vector'} | {'score':round(score,4)})
    return sorted(ranked, key=lambda x:-x['score'])[:limit]

import datetime as dt
import math
import re
import statistics
from collections import defaultdict

# These are validation envelopes, NOT clinical reference intervals or targets.
METRICS = {
 'glucose': ('Glucosa', 'mg/dL', 5, 1500, 'Metabólico'),
 'hba1c': ('HbA1c', '%', 1, 30, 'Metabólico'),
 'ldl': ('Colesterol LDL', 'mg/dL', 1, 1000, 'Cardiovascular'),
 'hdl': ('Colesterol HDL', 'mg/dL', 1, 300, 'Cardiovascular'),
 'triglycerides': ('Triglicéridos', 'mg/dL', 1, 5000, 'Cardiovascular'),
 'weight': ('Peso', 'kg', 1, 600, 'Metabólico'),
 'systolic': ('Presión sistólica', 'mmHg', 30, 350, 'Cardiovascular'),
 'diastolic': ('Presión diastólica', 'mmHg', 10, 250, 'Cardiovascular'),
 'sleep': ('Sueño', 'h', 0, 24, 'Sueño'),
 'steps': ('Pasos', 'pasos', 0, 150000, 'Actividad física'),
 'heart_rate': ('Frecuencia cardiaca', 'lpm', 10, 300, 'Cardiovascular')
}
ALIASES = {k:k for k in METRICS}
ALIASES.update({v[0].lower(): k for k,v in METRICS.items()})
ALIASES.update({'glucosa basal':'glucose','hemoglobina glicosilada':'hba1c','colesterol ldl':'ldl','colesterol hdl':'hdl','peso':'weight','sueno':'sleep','sueño':'sleep','pasos':'steps','ta sistolica':'systolic'})

def normalize(row):
    errors = []
    metric = ALIASES.get(str(row.get('metric', '')).strip().lower(), str(row.get('metric','')).strip().lower())
    date = str(row.get('date','')).strip()
    try:
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', date): raise ValueError()
        parsed = dt.date.fromisoformat(date)
        if parsed > dt.date.today() or parsed.year < 1900:
            errors.append('Fecha futura o anterior a 1900')
    except (ValueError, TypeError):
        errors.append('Fecha ambigua: usa AAAA-MM-DD')
    try:
        value = float(str(row.get('value','')).replace(',', '.'))
        if not math.isfinite(value): raise ValueError()
    except (ValueError, TypeError):
        value = None; errors.append('Valor numérico inválido')
    unit = str(row.get('unit','')).strip()
    note = str(row.get('note',''))[:1000]
    if metric not in METRICS:
        errors.append('Indicador no reconocido: selecciona uno del catálogo')
    else:
        canonical = METRICS[metric][1]
        if unit.lower() == canonical.lower(): unit = canonical
        if unit.lower() == 'mmol/l' and metric in ('glucose','ldl','hdl','triglycerides') and value is not None:
            factor = 18.0182 if metric == 'glucose' else (88.57 if metric == 'triglycerides' else 38.67)
            note += f' Conversión desde {value} mmol/L × {factor}.'
            value = round(value * factor, 4); unit = canonical
        if unit != canonical: errors.append(f'Unidad incompatible; se requiere {canonical}')
        if value is not None and not METRICS[metric][2] <= value <= METRICS[metric][3]:
            errors.append('Valor fuera de la envolvente de validación: comprueba origen/unidad')
    return {'date':date, 'metric':metric, 'value':value, 'unit':unit, 'note':note,
            'locator':str(row.get('locator','Entrada manual'))[:150], 'issues':errors}

def calculate(rows):
    groups = defaultdict(list)
    for r in rows: groups[r['metric']].append(r)
    result = []
    for metric, points in groups.items():
        points.sort(key=lambda x:(x['date'], x['id']))
        # Same-day measurements are represented by their mean, never an arbitrary last row.
        days = defaultdict(list)
        for p in points: days[p['date']].append(p)
        series = [{'date':d,'value':statistics.mean(p['value'] for p in ps),'ids':[p['id'] for p in ps]} for d,ps in sorted(days.items())]
        first, last = series[0], series[-1]
        delta = last['value']-first['value']
        pct = delta / first['value'] * 100 if first['value'] != 0 and len(series)>1 else None
        vals = [p['value'] for p in series]
        median = statistics.median(vals)
        mad = statistics.median(abs(v-median) for v in vals)
        outliers = [p['date'] for p in series if len(vals)>=5 and mad>0 and abs(p['value']-median)/(1.4826*mad)>3.5]
        result.append({'metric':metric,'label':METRICS[metric][0],'area':METRICS[metric][4],'unit':METRICS[metric][1],
          'series':series,'latest':last['value'],'delta':delta if len(series)>1 else None,'percent':pct,
          'count':len(points),'outliers':outliers,'sources':list(dict.fromkeys(p['source'] for p in points)),
          'formula':'(media del último día − media del primer día) / media del primer día × 100. No equivale a mejoría o empeoramiento clínico.'})
    return sorted(result, key=lambda t:list(METRICS).index(t['metric']))

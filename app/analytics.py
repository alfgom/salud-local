import datetime as dt
import math
import re
import statistics
import unicodedata
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
# Broad technical bounds for additional lab series, never laboratory reference ranges.
# Specimen-specific urine results deliberately remain outside these blood-series aliases.
LAB_METRICS = {
 'total_cholesterol': ('Colesterol total', 'mg/dL', 'Cardiovascular'),
 'creatinine': ('Creatinina', 'mg/dL', 'Función renal'),
 'uric_acid': ('Urato', 'mg/dL', 'Función renal'),
 'ast': ('Aspartato aminotransferasa (AST/GOT)', 'U/L', 'Función hepática'),
 'alt': ('Alanina aminotransferasa (ALT/GPT)', 'U/L', 'Función hepática'),
 'ggt': ('Gamma-glutamil transferasa (GGT)', 'U/L', 'Función hepática'),
 'iron': ('Hierro', 'µg/dL', 'Hematología'),
 'ferritin': ('Ferritina', 'ng/mL', 'Hematología'),
 'cea': ('Antígeno Carcinoembrionario (CEA)', 'ng/mL', 'Otros resultados de laboratorio'),
 'psa': ('PSA (Antígeno prostático específico)', 'ng/mL', 'Otros resultados de laboratorio'),
 'erythrocytes': ('Hematíes', '10^6/µL', 'Hematología'),
 'hemoglobin': ('Hemoglobina', 'g/dL', 'Hematología'),
 'hematocrit': ('Hematocrito', '%', 'Hematología'),
 'mcv': ('Volumen corpuscular medio (VCM)', 'fL', 'Hematología'),
 'mch': ('Hemoglobina corpuscular media (HCM)', 'pg', 'Hematología'),
 'mchc': ('Conc. de hgb. corpuscular media (CHCM)', 'g/dL', 'Hematología'),
 'rdw': ('Índice de anisocitosis (RDW)', '%', 'Hematología'),
 'leukocytes': ('Leucocitos', '10^3/µL', 'Hematología'),
 'neutrophils_pct': ('Neutrófilos %', '%', 'Hematología'),
 'lymphocytes_pct': ('Linfocitos %', '%', 'Hematología'),
 'monocytes_pct': ('Monocitos %', '%', 'Hematología'),
 'eosinophils_pct': ('Eosinófilos %', '%', 'Hematología'),
 'basophils_pct': ('Basófilos %', '%', 'Hematología'),
 'neutrophils_abs': ('Neutrófilos', '10^3/µL', 'Hematología'),
 'lymphocytes_abs': ('Linfocitos', '10^3/µL', 'Hematología'),
 'monocytes_abs': ('Monocitos', '10^3/µL', 'Hematología'),
 'eosinophils_abs': ('Eosinófilos', '10^3/µL', 'Hematología'),
 'basophils_abs': ('Basófilos', '10^3/µL', 'Hematología'),
 'platelets': ('Plaquetas', '10^3/µL', 'Hematología'),
 'mpv': ('Volumen plaquetario medio (VPM)', 'fL', 'Hematología'),
}
for key, (label, unit, area) in LAB_METRICS.items():
    METRICS[key] = (label, unit, 0, 100 if unit == '%' else 1_000_000, area)
ALIASES = {k:k for k in METRICS}
ALIASES.update({v[0].lower(): k for k,v in METRICS.items()})
ALIASES.update({'glucosa basal':'glucose','hemoglobina glicosilada':'hba1c','colesterol ldl':'ldl','colesterol hdl':'hdl','peso':'weight','sueno':'sleep','sueño':'sleep','pasos':'steps','ta sistolica':'systolic'})
ALIASES.update({'colesterol':'total_cholesterol', 'ácido úrico':'uric_acid', 'acido urico':'uric_acid',
    'ast':'ast', 'got':'ast', 'ast (got)':'ast', 'alt':'alt', 'gpt':'alt', 'alt (gpt)':'alt',
    'ggt':'ggt', 'gamma glutamil transferasa (ggt)':'ggt', 'psa':'psa', 'cea':'cea',
    'eritrocitos':'erythrocytes', 'hematíes':'erythrocytes', 'hematies':'erythrocytes',
    'vcm':'mcv', 'hcm':'mch', 'chcm':'mchc', 'rdw':'rdw', 'vpm':'mpv',
    'concentración de hemoglobina corpuscular media (chcm)':'mchc'})
for key in ('neutrophils', 'lymphocytes', 'monocytes', 'eosinophils', 'basophils'):
    label = METRICS[key+'_abs'][0].lower()
    ALIASES[label+' (%)'] = key+'_pct'

def unit_key(unit):
    text = unicodedata.normalize('NFKD', str(unit)).lower().replace('μ','u').replace('µ','u').replace('×','x')
    return re.sub(r'\s+', '', text)

def canonical_unit(unit, canonical):
    key = unit_key(unit)
    if key == unit_key(canonical): return canonical
    if canonical in ('10^3/µL', '10^6/µL'):
        exponent = canonical[3]
        if key in {f'{prefix}10{power}/{volume}' for prefix in ('', 'x')
                   for power in (exponent, '^'+exponent, '**'+exponent)
                   for volume in ('mm3', 'mm^3', 'ul')}:
            return canonical
    return str(unit).strip()

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
    raw_value = str(row.get('value','')).strip()
    try:
        value = float(raw_value.replace(',', '.'))
        if not math.isfinite(value): raise ValueError()
    except (ValueError, TypeError):
        value = None; errors.append('Valor numérico inválido')
    unit = str(row.get('unit','')).strip()
    note = str(row.get('note',''))[:1000]
    comparator = bool(re.fullmatch(r'[<>≤≥]\s*\d+(?:[.,]\d+)?', raw_value))
    if comparator:
        note += f' Resultado acotado del documento: {raw_value}; no es un valor exacto.'
    if metric not in METRICS:
        errors.append('Indicador no reconocido: selecciona uno del catálogo')
    else:
        canonical = METRICS[metric][1]
        unit = canonical_unit(unit, canonical)
        if unit.lower() == 'mmol/l' and metric in ('glucose','ldl','hdl','triglycerides') and value is not None:
            factor = 18.0182 if metric == 'glucose' else (88.57 if metric == 'triglycerides' else 38.67)
            note += f' Conversión desde {value} mmol/L × {factor}.'
            value = round(value * factor, 4); unit = canonical
        if unit != canonical: errors.append(f'Unidad incompatible; se requiere {canonical}')
        if value is not None and not METRICS[metric][2] <= value <= METRICS[metric][3]:
            errors.append('Valor fuera de la envolvente de validación: comprueba origen/unidad')
    return {'date':date, 'metric':metric, 'value':value, 'unit':unit, 'note':note,
            **({'raw_value':raw_value} if comparator else {}),
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

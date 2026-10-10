"""Conservative text proposals. No clinical inference or silent date guessing."""
import datetime as dt
import re
import unicodedata
from .analytics import ALIASES, METRICS, canonical_unit

VERSION = '3'
DATE = re.compile(r'\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4})\b')
SAMPLE = re.compile(r'fecha\s+(?:de\s+)?(?:la\s+)?(?:muestra|extraccion|toma|analisis)')

def fold(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', text.lower()) if not unicodedata.combining(c))

def parsed_date(token, explicit):
    try:
        if '/' in token:
            day, month, year = map(int, token.split('/'))
            # Spanish sample-date labels establish DD/MM; unlabeled ambiguous dates stay blank.
            if day <= 12 and month <= 12 and day != month and not explicit:
                return '', 'ambiguous'
            date = dt.date(year, month, day)
        else:
            date = dt.date.fromisoformat(token)
        if date.year < 1900 or date > dt.date.today(): return '', 'invalid'
        return date.isoformat(), 'recognized'
    except ValueError:
        return '', 'invalid'

def dates_in(text):
    preferred = []; fallback = []
    for line in fold(text).splitlines():
        sample = SAMPLE.search(line)
        explicit = bool(sample)
        if not explicit and re.search(r'nacimiento|birth|validacion|impresion', line): continue
        for token in DATE.findall(line[sample.end():] if sample else line):
            (preferred if explicit else fallback).append(parsed_date(token, explicit))
    return preferred, fallback

def resolve(entries):
    if not entries: return '', 'missing'
    if any(not date for date, _ in entries):
        return '', 'ambiguous' if any(code == 'ambiguous' for _, code in entries) else 'invalid'
    unique = {date for date, _ in entries}
    return (next(iter(unique)), 'recognized') if len(unique) == 1 else ('', 'conflicting')

def propose(pages):
    candidates = []
    counts = {key: 0 for key in ('pages', 'date_recognized', 'date_missing', 'date_ambiguous',
              'date_invalid', 'date_conflicting', 'numeric_lines', 'unmapped_numeric_lines',
              'known_label_unmatched', 'qualified_labels', 'comparators', 'unknown_numeric_label',
              'specimen_excluded', 'qualitative_results', 'label_unparsed', 'unit_unrecognized')}
    counts['catalog_size'] = len(METRICS)
    page_dates = [dates_in(p['text']) for p in pages]
    preferred = [entry for explicit, _ in page_dates for entry in explicit]
    document_date = resolve(preferred or [entry for _, fallback in page_dates for entry in fallback])
    patterns = []
    for alias in sorted(ALIASES, key=len, reverse=True):
        label = r'^\s*' + re.escape(fold(alias)) + r'(?=$|[\s:;(])'
        patterns.append((ALIASES[alias], re.compile(label), re.compile(label +
            r'(?:\s*(\((?:suero(?:\s*/\s*plasma)?|plasma)\)))?(?:\s*[:;]\s*|\s+)'
            r'([<>≤≥]?\s*\d+(?:[.,]\d+)?)(?![\d.,])\s*\*?\s*(.*)$')))
    urine = False
    for page, (explicit, fallback) in zip(pages, page_dates):
        # A unique sample date applies across pages. Conflicting sample headers never select one.
        date, state = document_date if preferred else resolve(fallback)
        if state == 'missing' and document_date[1] == 'recognized': date, state = document_date
        counts['pages'] += 1; counts['date_' + state] += 1
        for raw in page['text'].splitlines():
            line = fold(raw)
            if re.search(r'analisis de orina|bioquimica en orina|sedimento', line): urine = True
            elif re.match(r'\s*(bioquimica|hematologia|metabolismo |pruebas de funcion)', line): urine = False
            numeric = bool(re.match(r'\s*[a-z].*?\s+[<>≤≥]?\s*\d+(?:[.,]\d+)?(?:\s|$)', line)) and not DATE.search(line)
            if numeric: counts['numeric_lines'] += 1
            matched = False; known = False; reason = 'label_unparsed'
            for metric, label, pattern in patterns:
                if not label.match(line): continue
                known = True
                m = pattern.match(line)
                if re.search(r'\b(?:negativo|negativa|positivo|positiva|ausente|presente)\b', line):
                    reason = 'qualitative_results'; continue
                if urine:
                    reason = 'specimen_excluded'; continue
                if not m: continue
                # Keep the unit as written before a bracketed reference range. Never infer a missing unit.
                unit = re.split(r'\[|\s{2,}', m[3].strip(), maxsplit=1)[0].strip()
                canonical = METRICS[metric][1]
                normalized_unit = canonical_unit(unit, canonical)
                if normalized_unit != canonical and not (unit == 'mmol/l' and metric in ('glucose','ldl','hdl','triglycerides')):
                    counts['unit_unrecognized'] += 1
                note = 'Propuesta automática; pendiente de contraste con el original.'
                if unit != normalized_unit: note += f' Unidad literal del documento: {unit}.'
                if '/' in ' '.join(DATE.findall(page['text'])): note += ' Fecha propuesta en formato día/mes/año.'
                candidates.append({'date': date, 'metric': metric, 'value': m[2],
                    'unit': unit, 'locator': page['locator'], 'note': note})
                counts['qualified_labels'] += bool(m[1])
                counts['comparators'] += bool(re.match(r'[<>≤≥]', m[2]))
                matched = True; break
            if known and not matched:
                counts['known_label_unmatched'] += 1; counts[reason] += 1
            if numeric and not matched: counts['unmapped_numeric_lines'] += 1
            if numeric and not known: counts['unknown_numeric_label'] += 1
    return candidates, counts

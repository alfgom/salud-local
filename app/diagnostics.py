"""Shareable technical reports built from an allowlist, never from redacted clinical text."""
from .lab_parser import VERSION

COUNT_KEYS = frozenset(('pages', 'ocr_pages', 'proposals', 'date_recognized', 'date_missing',
    'date_ambiguous', 'date_invalid', 'date_conflicting', 'numeric_lines', 'unmapped_numeric_lines',
    'known_label_unmatched', 'qualified_labels', 'comparators', 'validation_date',
    'validation_unit', 'validation_value', 'validation_metric'))
FORMATS = frozenset(('pdf', 'csv', 'json', 'png', 'jpeg'))
ERRORS = frozenset(('none', 'extraction_failed', 'parser_busy', 'parser_timeout', 'parser_memory',
    'parser_output', 'diagnostics_unavailable'))

def clean(raw):
    """Only fixed enums and bounded integer counters cross the export boundary."""
    raw = raw if isinstance(raw, dict) else {}
    counts = raw.get('counts', {})
    counts = counts if isinstance(counts, dict) else {}
    version = raw.get('parser_version')
    fmt = raw.get('format'); error = raw.get('error')
    return {'schema': 1, 'component': 'document_extraction',
        'parser_version': version if version in ('1', VERSION) else 'unknown',
        'format': fmt if isinstance(fmt, str) and fmt in FORMATS else 'unknown',
        'error': error if isinstance(error, str) and error in ERRORS else 'extraction_failed',
        'counts': {key: min(max(value, 0), 1_000_000) for key, value in counts.items()
                   if key in COUNT_KEYS and type(value) is int}}

def report(ext, parsed=None, rows=(), error='none'):
    counts = dict((parsed or {}).get('technical_counts', {}))
    counts['pages'] = len((parsed or {}).get('pages', []))
    counts['proposals'] = len(rows)
    for key, prefix in (('date', 'Fecha'), ('unit', 'Unidad'), ('value', 'Valor'), ('metric', 'Indicador')):
        counts['validation_' + key] = sum(any(issue.startswith(prefix) for issue in row.get('issues', [])) for row in rows)
    return clean({'parser_version': VERSION, 'format': 'jpeg' if ext == 'jpg' else ext,
                  'error': error, 'counts': counts})

def download(events):
    return {'schema': 1, 'application': 'Salud Local',
        'scope': 'Technical enums and counters only; no clinical content or identifiers.',
        'events': [clean(event) for event in events[:50]]}

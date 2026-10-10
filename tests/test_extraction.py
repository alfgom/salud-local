"""Invented text only. Do not replace these cases with personal reports."""
import json
import pytest
from app.lab_parser import propose
from app.analytics import normalize, METRICS, literal_record
from app import diagnostics

def pages(*texts):
    return [{'locator': f'Página {i+1}', 'text': text} for i, text in enumerate(texts)]

def test_sample_date_qualifiers_and_reference_columns():
    rows, counts = propose(pages('Hematología\nPeso 72 kg',
        'Fecha muestra: 22/08/2025\nBioquímica\nGlucosa (suero/plasma) 97,3 * mg/dL [ 60 - 120 ]\n'
        'Colesterol HDL 53 mg/dL [ > 35 ]\nColesterol total 193 mg/dL [ < 210 ]\n'
        'Etiqueta sintética fuera del catálogo 29 mg/dL'))
    assert len(rows) == 4
    assert all(row['date'] == '2025-08-22' for row in rows)
    assert normalize(rows[1])['value'] == 97.3
    assert rows[1]['locator'] == 'Página 2'
    assert counts['qualified_labels'] == 1
    assert counts['unmapped_numeric_lines'] == 1
    assert counts['unknown_numeric_label'] == 1
    assert all(not normalize(row)['issues'] for row in rows)

@pytest.mark.parametrize('header, expected', [
    ('Fecha muestra: 05/06/2025', '2025-06-05'),
    ('2025-07-09', '2025-07-09'),
    ('Fecha: 05/06/2025', ''),
    ('Fecha muestra: 31/02/2025', ''),
    ('Fecha muestra: 01/01/2099', ''),
    ('Fecha nacimiento: 2025-01-01', ''),
    ('Fecha nacimiento: 1980-01-01 Fecha muestra: 2025-07-09', '2025-07-09'),
    ('', ''),
    ('Fecha muestra: 2025-06-05\nFecha muestra: 2025-07-09', ''),
])
def test_conservative_dates(header, expected):
    rows, _ = propose(pages(header+'\nGlucosa 97 mg/dL'))
    assert rows[0]['date'] == expected

def test_conflicting_sample_headers_apply_to_every_page():
    rows, counts = propose(pages('Fecha muestra: 2025-06-05\nPeso 72 kg',
        'Fecha muestra: 2025-07-09\nGlucosa 97 mg/dL'))
    assert all(row['date'] == '' for row in rows)
    assert counts['date_conflicting'] == 2

@pytest.mark.parametrize('label', ['Glucosa:97 mg/dL', 'Glucosa; 97 mg/dL', 'Glucosa (suero/plasma):97 mg/dL'])
def test_label_separators(label):
    rows, _ = propose(pages('2025-07-09\n'+label))
    assert rows[0]['value'] == '97'

def test_urine_and_unknown_qualifiers_are_never_serum_glucose():
    rows, counts = propose(pages('2025-07-09\nGlucosa (orina) 7 mg/dL\nAnálisis de Orina\n'
        'Glucosa NEGATIVO\nGlucosa 7 mg/dL\nBioquímica\nGlucosa (plasma) 97 mg/dL'))
    assert len(rows) == 1
    assert rows[0]['value'] == '97'
    assert counts['known_label_unmatched'] == 3

def test_inequality_requires_manual_review_never_becomes_exact_value():
    rows, counts = propose(pages('2025-07-09\nGlucosa <7 mg/dL'))
    assert rows[0]['value'] == '<7'
    assert normalize(rows[0])['value'] is None
    assert any(issue.startswith('Valor') for issue in normalize(rows[0])['issues'])
    assert counts['comparators'] == 1

def test_technical_export_uses_allowlist_not_text_redaction():
    private = 'SYNTHETIC_PRIVATE_MARKER'
    raw = {'format': 'pdf', 'error': 'none', 'parser_version': '2', 'patient': private,
        'date': '2025-07-09', 'value': 97.3, 'model': private, 'text': private,
        'filename': private, 'path': private, 'sha': private, 'exception': private,
        'counts': {'pages': 3, 'proposals': 4, 'private': private, 'validation_value': 2}}
    result = diagnostics.download([raw])
    text = json.dumps(result)
    assert private not in text and '2025-07-09' not in text and '97.3' not in text
    assert result['events'][0]['counts'] == {'pages': 3, 'proposals': 4, 'validation_value': 2}
    raw.update(format={'bad': private}, error=[private], parser_version=private)
    raw['counts'] = {'pages': private, 'proposals': True, 'ocr_pages': -2, 'date_missing': 10**50}
    cleaned = diagnostics.clean(raw)
    assert cleaned['counts'] == {'ocr_pages': 0, 'date_missing': 1_000_000}
    assert private not in json.dumps(cleaned)
    assert len(diagnostics.download([{}]*100)['events']) == 50

def test_extended_lab_table_and_separate_percentage_absolute_series():
    rows, counts = propose(pages('Fecha muestra: 22/08/2025\nHematología\n'
        'Hematíes 5,12 x10⁶/mm³ [ 3 - 7 ]\nHemoglobina 13,8 g/dL\n'
        'Volumen corpuscular medio (VCM) 87 fL\nHemoglobina corpuscular media (HCM) 29 pg\n'
        'Conc. de hgb. corpuscular media (CHCM) 33 g/dL\nÍndice de anisocitosis (RDW) 12 %\n'
        'Leucocitos 6,7 x10³/mm³\nNeutrófilos % 58,4 %\nNeutrófilos 3,9 x10³/mm³\n'
        'Plaquetas 234 x10³/mm³\nBioquímica\nCreatinina 1,03 mg/dL\nUrato 4,9 mg/dL\n'
        'Aspartato aminotransferasa (AST/GOT) 27 U/L\nAlanina aminotransferasa (ALT/GPT) 33 U/L\n'
        'Gamma-glutamil transferasa (GGT) 39 U/L\nHierro 93 µg/dL\nFerritina 105 ng/mL\n'
        'PSA (Antígeno prostático específico) 1,24 ng/mL\nAntígeno Carcinoembrionario (CEA) ≤0,8 ng/mL'))
    assert len(rows) == 19
    normalized = {r['metric']: normalize(r) for r in rows}
    assert normalized['erythrocytes']['unit'] == '10^6/µL'
    assert normalized['leukocytes']['unit'] == '10^3/µL'
    assert normalized['neutrophils_pct']['value'] == 58.4
    assert normalized['neutrophils_abs']['value'] == 3.9
    assert normalized['iron']['unit'] == 'µg/dL'
    assert normalized['cea']['raw_value'] == '≤0,8' and normalized['cea']['value'] is None
    assert all(not r['issues'] for metric, r in normalized.items() if metric != 'cea')
    assert normalized['cea']['issues']
    assert counts['unmapped_numeric_lines'] == 0 and counts['comparators'] == 1
    assert counts['catalog_size'] == len(METRICS)

@pytest.mark.parametrize('unit', ['x10³/mm³', 'x10^3/mm3', '×10³/mm³', '10^3/µL', '10^3/μL', 'x10 3/mm3'])
def test_equivalent_count_unit_spellings(unit):
    row = normalize({'date':'2025-08-22','metric':'leukocytes','value':6.7,'unit':unit})
    assert row['unit'] == '10^3/µL' and row['value'] == 6.7 and not row['issues']

def test_incompatible_exponent_and_missing_unit_are_not_inferred():
    rows, counts = propose(pages('2025-08-22\nLeucocitos 6,7 x10^6/mm3\nFerritina 105 [ 15 - 300 ]'))
    assert len(rows) == 2
    assert rows[1]['unit'] == ''
    assert all(any(issue.startswith('Unidad') for issue in normalize(row)['issues']) for row in rows)
    assert counts['unit_unrecognized'] == 2

def test_reasons_distinguish_partial_coverage_without_names():
    _, counts = propose(pages('2025-08-22\nEtiqueta inventada 29 mg/dL\n'
        'Glucosa (otro espécimen) 92 mg/dL\nAnálisis de Orina\n'
        'Leucocitos NEGATIVO\nHematíes 3 x10^6/mm3\nBioquímica\nFerritina 105'))
    assert counts['unknown_numeric_label'] == 1
    assert counts['label_unparsed'] == 1
    assert counts['specimen_excluded'] == 1
    assert counts['qualitative_results'] == 1
    assert counts['unit_unrecognized'] == 1
    exported = json.dumps(diagnostics.download([{'error':'none','parser_version':'3','format':'pdf','counts':counts}]))
    for private in ('Glucosa', 'Leucocitos', 'Hematíes', 'Ferritina', '2025-08-22', 'NEGATIVO'):
        assert private not in exported

def test_legacy_report_version_remains_shareable():
    assert diagnostics.clean({'parser_version':'2','error':'none','format':'pdf'})['parser_version'] == '2'
    assert diagnostics.clean({'parser_version':'3','error':'none','format':'pdf'})['parser_version'] == '3'

def test_comparators_have_separate_technical_validation_counts():
    rows=[normalize({'date':'2025-08-22','metric':'ferritin','value':value,'unit':'ng/mL'})
          for value in ('≤2,7','bad synthetic number','105')]
    diagnostic=diagnostics.report('pdf',rows=rows)
    assert diagnostic['counts']['validation_value']==2
    assert diagnostic['counts']['validation_comparator']==1
    assert diagnostic['counts']['validation_numeric']==1
    assert 'Valor acotado' in rows[0]['issues'][0]
    assert rows[0]['raw_value']=='≤2,7' and rows[0]['value'] is None
    assert '2,7' not in json.dumps(diagnostic)

def test_unknown_numeric_context_counts_do_not_identify_results():
    _, counts=propose(pages('2025-08-22\nEtiqueta ficticia 12 mg/dL\n'
        'Análisis de Orina\nOtra etiqueta ficticia 23\nHematología\nTercera etiqueta ficticia 34 mg/dL'))
    assert counts['unknown_numeric_label']==3
    assert counts['unknown_numeric_in_urine']==1
    assert counts['unknown_numeric_outside_urine']==2

def test_literal_record_preserves_constraint_and_current_edits():
    row={'date':'2025-08-22','metric':'ferritin','value':None,'raw_value':'≤2,7','unit':'ng/mL','locator':'Página 2'}
    record=literal_record(row)
    assert record['kind']=='lab_result' and record['date']=='2025-08-22'
    assert '≤2,7 ng/mL' in record['detail'] and 'Página 2' in record['detail']
    assert '≤3,9' in literal_record(row|{'value':'≤3,9'})['detail']
    with pytest.raises(ValueError): literal_record(row|{'value':'105'})
    with pytest.raises(ValueError): literal_record(row|{'date':'05/06/2025'})
    with pytest.raises(ValueError): literal_record(row|{'metric':'unknown-synthetic-marker'})

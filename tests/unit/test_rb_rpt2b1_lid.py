"""PAN LID suggestion metadata only; format observed in owner-supplied files; values not copied.

Public structural evidence: DNV, Primer on PAN and OND Files, module-level
LIDLoss beside VRevDiode, before the IAM sub-object:
https://3f01987ab2c43f1e1a1e-5dee5c72ef4d5ad7dd4b61ef3ab73822.ssl.cf1.rackcdn.com/3349821-2943854-001.pdf
All input values below are synthetic.
"""
import pytest
from components.pan import map_pan,parse_pan_text


def mapped(value):
    return map_pan(parse_pan_text(f'PVObject_=pvModule\n  LIDLoss={value}\nEnd of PVObject_\n'))


def test_lid_is_optional_fraction_with_raw_percent_provenance():
    result=mapped('2.75')
    assert result.values_by_canonical_path['quality.lid_loss_fraction']==.0275
    row=next(r for r in result.mapped_fields if r['canonical_path']=='quality.lid_loss_fraction')
    assert row['source_path']==['PVObject_','LIDLoss']
    assert row['source_value']=='2.75' and row['source_unit']=='%' and row['canonical_unit']=='fraction'
    assert not any(f['key']=='LIDLoss' for f in result.unmapped_fields)
    assert mapped('0').values_by_canonical_path['quality.lid_loss_fraction']==0
    assert mapped('99.9').values_by_canonical_path['quality.lid_loss_fraction']==pytest.approx(.999)


@pytest.mark.parametrize('value',['-1','100','101','NaN','Inf','-Inf','bad',''])
def test_invalid_lid_keeps_raw_evidence_and_warning_without_mapping(value):
    result=mapped(value)
    assert 'quality.lid_loss_fraction' not in result.values_by_canonical_path
    assert any(f['key']=='LIDLoss' for f in result.unmapped_fields)
    assert any('LIDLoss' in warning for warning in result.warnings)

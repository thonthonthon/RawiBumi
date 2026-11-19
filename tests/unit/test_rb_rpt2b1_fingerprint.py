import pytest
"""Report site details are outside both scientific identity and undo."""
from tests.unit._availability import missing_commit
from copy import deepcopy
import subprocess
import sys
from types import ModuleType
from apps.api.history import design_fingerprint,projection
from tests.unit.test_rb_fix_s2_honest_preflight import Project


def test_old_fingerprint_identity_metadata_and_real_inputs(tmp_path):
    if reason := missing_commit('8ad7e14'):
        pytest.skip(reason)
    bundle=Project(tmp_path,18,weather=False).bundle()
    baseline=ModuleType('apps.api._rpt2b1_history_baseline');baseline.__package__='apps.api'
    sys.modules[baseline.__name__]=baseline
    try:
        exec(subprocess.check_output(['git','show','8ad7e14:apps/api/history.py']),baseline.__dict__)
        expected=baseline.design_fingerprint(bundle)
        expected_projection=baseline.projection(bundle)
    finally:sys.modules.pop(baseline.__name__,None)
    before=deepcopy(bundle);undo=projection(bundle)
    assert design_fingerprint(bundle)==expected
    assert undo==expected_projection
    for key,value in [('address',{'text':'Synthetic','source':'user'}),('installation',{'installationType':'hybrid','bessEnergyKwh':10,'bessPowerKw':2})]:
        changed=deepcopy(bundle);changed['project']['site'][key]=value
        assert design_fingerprint(changed)==expected
        assert projection(changed)==undo
    changed=deepcopy(bundle);changed['scene']['pv_fields'][0]['tilt_deg']+=1
    assert design_fingerprint(changed)!=expected
    assert bundle==before

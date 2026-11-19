import pytest
from tests.unit.test_phase7_csv_export import persisted
from tests.unit.test_rb_rpt1_free_csv import package
from tests.unit.test_rb_rpt2b1_snapshot import snapshot_case

@pytest.mark.parametrize('value',[9007199254740992,-9007199254740992])
def test_snapshot_refuses_unsafe_integer_before_node(snapshot_case,value):
    case=snapshot_case(summary_change=lambda summary:summary['data_quality_summary'].update(unsafe=value))
    with pytest.raises(ValueError,match='safe integer'):
        case.study.report_snapshot(case.project_id,case.run_id)

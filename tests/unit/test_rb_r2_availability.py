"""Availability guards only distinguish missing development dependencies."""
from types import SimpleNamespace
import pytest
from tests.unit import _availability as availability


@pytest.mark.parametrize('worktree,commit',[(False,False),(True,False),(True,True)])
def test_git_and_commit_skip_reasons(monkeypatch,tmp_path,worktree,commit):
    calls=[]
    def run(command,**kwargs):
        calls.append(command)
        if 'rev-parse' in command:
            return SimpleNamespace(returncode=0 if worktree else 128,stdout='true\n' if worktree else '')
        return SimpleNamespace(returncode=0 if commit else 128)
    monkeypatch.setattr(availability.subprocess,'run',run)
    reason=availability.missing_commit('273cd92',tmp_path)
    assert bool(reason)==(not worktree or not commit)
    if not worktree:
        assert 'git work tree' in reason and not any('cat-file' in call for call in calls)
    elif not commit:
        assert 'needs commit 273cd92' in reason
    else:
        assert calls[-1][-1]=='273cd92^{commit}'


def test_private_path_skip_only_when_missing(tmp_path):
    assert availability.missing_private_path('.ai/evidence.json',tmp_path)=='needs private file .ai/evidence.json'
    (tmp_path/'.ai').mkdir()
    (tmp_path/'.ai/evidence.json').write_text('existing evidence')
    assert availability.missing_private_path('.ai/evidence.json',tmp_path) is None


@pytest.mark.parametrize('missing',[False,True])
def test_collection_guard_matches_only_the_private_task_node(monkeypatch,tmp_path,missing):
    from tests.unit import conftest as hooks
    node='tests/unit/test_rb_post3d_08p2e2_r2e_memory.py::test_authorization_and_stage_refusal'
    items=[SimpleNamespace(nodeid=name,markers=[]) for name in [node,node+'[other]',
        'tests/unit/test_rb_post3d_08p2e2_r2e_memory.py::test_experiment_and_source_safety_invariants']]
    for item in items:
        item.add_marker=item.markers.append
    if missing:
        monkeypatch.setattr(hooks,'missing_private_path',lambda path: 'needs private file '+path)
    else:
        (tmp_path/'.ai').mkdir()
        (tmp_path/'.ai/TASK.md').write_text('available task')
        monkeypatch.setattr(hooks,'missing_private_path',lambda path: availability.missing_private_path(path,tmp_path))
    hooks.pytest_collection_modifyitems(items)
    assert len(items[0].markers)==int(missing)
    if missing:
        assert items[0].markers[0].name=='skip'
        assert items[0].markers[0].kwargs['reason']=='needs private file .ai/TASK.md'
    assert all(not item.markers for item in items[1:])

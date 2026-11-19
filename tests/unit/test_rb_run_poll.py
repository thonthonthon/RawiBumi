"""A run longer than RAWIBUMI_SIMULATE_WAIT_SECONDS answers 202 with a job that is polled to the same record or error;
unset, the run answers directly as before. (Moved unchanged from the BETA1 server tests.)"""
import time

import pytest

from tests.unit.test_rb_fix_s2_honest_preflight import Project


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("RAWIBUMI_SIMULATE_WAIT_SECONDS", "0")
    return Project(tmp_path, 20, weather=True, strings=True)


def test_a_long_run_answers_202_and_the_job_gives_the_same_record(project, monkeypatch):
    study = project.app.state.study_service
    def slow(project_id, config=None):
        time.sleep(0.3)
        return {"simulation_run_id": "run-x", "status": "completed", "summary_result": {}}
    monkeypatch.setattr(study, "run_study", slow)
    started = project.client.post(project.url + "/simulate", json={})
    assert started.status_code == 202 and started.json()["status"] == "running"
    job = project.url + "/simulate/jobs/" + started.json()["job_id"]
    for _ in range(50):
        polled = project.client.get(job)
        if polled.status_code != 202:
            break
        time.sleep(0.05)
    assert polled.status_code == 200 and polled.json()["simulation_run_id"] == "run-x"
    assert project.client.get(job).status_code == 404  # collected once


def test_a_failed_long_run_gives_the_same_error_as_the_synchronous_route(project, monkeypatch):
    study = project.app.state.study_service
    def failing(project_id, config=None):
        time.sleep(0.1)
        raise ValueError("simulation execution preflight failed: test reason")
    monkeypatch.setattr(study, "run_study", failing)
    job = project.url + "/simulate/jobs/" + project.client.post(project.url + "/simulate", json={}).json()["job_id"]
    for _ in range(50):
        polled = project.client.get(job)
        if polled.status_code != 202:
            break
        time.sleep(0.05)
    assert polled.status_code == 422 and "test reason" in polled.text


def test_without_a_wait_limit_the_run_answers_directly_as_before(tmp_path, monkeypatch):
    monkeypatch.delenv("RAWIBUMI_SIMULATE_WAIT_SECONDS", raising=False)
    project = Project(tmp_path, 20, weather=True, strings=True)
    monkeypatch.setattr(project.app.state.study_service, "run_study",
                        lambda project_id, config=None: {"simulation_run_id": "run-y", "status": "completed"})
    response = project.client.post(project.url + "/simulate", json={})
    assert response.status_code == 200 and response.json()["simulation_run_id"] == "run-y"

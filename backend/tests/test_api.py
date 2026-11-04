import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.persistence import Store
from backend.app.reporting import safe_csv
from backend.app.samples import sample


def project(client, name="Test project"):
    response = client.post("/api/v1/projects", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def model(client, pid, key="operations"):
    s = sample(key)
    response = client.post(f"/api/v1/projects/{pid}/models", json={"name": s["name"], "xml": s["xml"]})
    assert response.status_code == 201, response.text
    return response.json(), s["config"]


def start(client, pid, model_id, config, mode="optimize"):
    response = client.post(
        f"/api/v1/projects/{pid}/runs", json={"model_id": model_id, "mode": mode, "config": config}
    )
    assert response.status_code == 202, response.text
    return response.json()


def complete(client, rid):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/runs/{rid}")
        assert response.status_code == 200, response.text
        run = response.json()
        if run["state"] not in ("running", "queued"):
            assert run["state"] == "succeeded", run
            return run
        time.sleep(0.03)
    pytest.fail("Run exceeded integration-test time budget.")


def test_full_journey_and_run_artifacts(client):
    p = project(client)
    m, c = model(client, p["id"])
    validation = client.post(f"/api/v1/models/{m['id']}/validate").json()
    assert validation["structural"] == "valid"
    assert validation["verification"]["status"] == "no_counterexample"
    assert client.get("/api/v1/health").json()["storage_schema"] == 1
    r = complete(client, start(client, p["id"], m["id"], c)["id"])
    assert r["result"]["baseline"]["metrics"]["makespan"] == 13
    assert r["result"]["optimization"]["selected"]["metrics"]["makespan"] == 11
    for name in ("original.bpmn", "schedule.csv", "results.json", "report.pdf", "bundle.zip"):
        artifact = client.get(f"/api/v1/runs/{r['id']}/artifacts/{name}")
        assert artifact.status_code == 200
        if name == "original.bpmn":
            assert artifact.content.decode() == m["xml"]
        elif name == "report.pdf":
            assert artifact.content.startswith(b"%PDF")
        elif name == "results.json":
            assert artifact.json()["run_id"] == r["id"]
        elif name == "bundle.zip":
            assert artifact.content.startswith(b"PK")
        else:
            assert "baseline" in artifact.text and "selected" in artifact.text
    assert client.get("/download-report").status_code == 410


def test_history_independent_after_restart(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        ids = []
        for name, key in [("First", "order"), ("Second", "operations")]:
            p = project(client, name)
            m, c = model(client, p["id"], key)
            r = complete(client, start(client, p["id"], m["id"], c)["id"])
            ids.append((p["id"], m, r))
    with TestClient(create_app(tmp_path)) as client:
        assert len(client.get("/api/v1/projects").json()) == 2
        for pid, m, r in ids:
            assert client.get(f"/api/v1/projects/{pid}/runs").json()[0]["id"] == r["id"]
            assert client.get(f"/api/v1/runs/{r['id']}/artifacts/original.bpmn").text == m["xml"]
            assert client.get(f"/api/v1/runs/{r['id']}/artifacts/results.json").json()["model_id"] == m["id"]
        assert ids[0][2]["id"] != ids[1][2]["id"]
        assert (
            client.get(f"/api/v1/runs/{ids[0][2]['id']}/artifacts/report.pdf").content
            != client.get(f"/api/v1/runs/{ids[1][2]['id']}/artifacts/report.pdf").content
        )


def test_capacity_comparison_and_scenario_persistence(client):
    p = project(client)
    m, c = model(client, p["id"], "order")
    left = complete(client, start(client, p["id"], m["id"], c, "simulate")["id"])
    c["resources"][0]["capacity"] = 1
    saved = client.post(f"/api/v1/projects/{p['id']}/scenarios", json={"name": "One operator", "config": c})
    assert saved.status_code == 201
    assert client.get(f"/api/v1/projects/{p['id']}/scenarios").json()[0]["config"] == c
    right = complete(client, start(client, p["id"], m["id"], c, "simulate")["id"])
    comparison = client.get(f"/api/v1/compare?left={left['id']}&right={right['id']}").json()
    assert comparison["comparison_scope"] == "capacity scenario"
    assert comparison["warning"]
    assert left["result"]["baseline"]["metrics"]["makespan"] == 9
    assert right["result"]["baseline"]["metrics"]["makespan"] == 13


def test_version_immutability_and_project_ownership(client):
    p = project(client)
    m, c = model(client, p["id"])
    p2 = project(client, "Other")
    response = client.post(f"/api/v1/projects/{p2['id']}/runs", json={"model_id": m["id"], "config": c})
    assert response.status_code == 404
    changed = m["xml"].replace("Prepare labels", "Changed labels")
    new = client.post(
        f"/api/v1/projects/{p['id']}/models", json={"name": "Edited version", "xml": changed}
    ).json()
    assert new["id"] != m["id"]
    assert client.get(f"/api/v1/models/{m['id']}").json()["xml"] == m["xml"]
    assert len(client.get(f"/api/v1/projects/{p['id']}/models").json()) == 2


@pytest.mark.parametrize(
    "filename,content,status",
    [
        ("bad.txt", b"plain text", 422),
        ("model.bpmn", b"<broken>", 422),
        ("model.xml", b"\xff\xff", 422),
        ("xxe.xml", b'<!DOCTYPE a [<!ENTITY x SYSTEM "file:///secrets">]><definitions/>', 422),
        ("big.xml", b"x" * 1_000_001, 413),
    ],
)
def test_upload_bounds_and_content(client, filename, content, status):
    p = project(client)
    assert (
        client.post(f"/api/v1/projects/{p['id']}/upload", files={"file": (filename, content)}).status_code
        == status
    )


def test_origin_body_and_security_headers(client):
    response = client.post(
        "/api/v1/projects", json={"name": "unwanted"}, headers={"origin": "https://evil.example"}
    )
    assert response.status_code == 403
    assert not client.get("/api/v1/projects").json()
    assert client.post("/api/v1/projects", content=b"x" * 1_100_001).status_code == 413
    response = client.get("/api/v1/health")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "script-src 'self'" in response.headers["content-security-policy"]
    assert "access-control-allow-origin" not in response.headers
    assert client.get("/api/v1/health", headers={"host": "evil.example"}).status_code == 400


def test_malicious_labels_are_data_and_csv_safe(client):
    p = project(client, "<script>alert(1)</script>")
    m, c = model(client, p["id"])
    assert client.get("/api/v1/projects").json()[0]["name"] == "<script>alert(1)</script>"
    assert safe_csv('=HYPERLINK("evil")').startswith("'")
    assert safe_csv("  +SUM(1,2)").startswith("'")
    assert client.get("/api/v1/runs/unknown/artifacts/../../secret").status_code == 404


def test_run_deletion_hides_downloads_and_retains_files(client):
    p = project(client)
    m, c = model(client, p["id"])
    r = complete(client, start(client, p["id"], m["id"], c)["id"])
    directory = client.app.state.store.run_dir(p["id"], r["id"])
    assert client.delete(f"/api/v1/runs/{r['id']}").status_code == 200
    assert client.get(f"/api/v1/runs/{r['id']}/artifacts/report.pdf").status_code == 404
    assert (directory / "report.pdf").exists()


def test_cancel_is_sticky_and_restart_marks_interrupted(tmp_path):
    store = Store(tmp_path)
    pid = "a" * 32
    mid = "b" * 32
    rid = "c" * 32
    store.insert("projects", {"id": pid, "name": "p", "created": "now"})
    store.insert(
        "models",
        {
            "id": mid,
            "project_id": pid,
            "name": "m",
            "created": "now",
            "xml": "x",
            "ir": {},
            "diagnostics": [],
        },
    )
    store.insert(
        "runs",
        {
            "id": rid,
            "project_id": pid,
            "model_id": mid,
            "created": "now",
            "updated": "now",
            "state": "running",
            "stage": "simulation",
            "mode": "simulate",
            "config": {},
        },
    )
    Store(tmp_path)
    assert store.get("runs", rid)["state"] == "failed"
    store.update_run(rid, state="canceled", stage="canceled")
    store.update_run(rid, state="succeeded", stage="complete", result={})
    assert store.get("runs", rid)["state"] == "canceled"
    with sqlite3.connect(tmp_path / "studio.sqlite3") as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1


def test_missing_key_does_not_affect_samples(client, monkeypatch):
    monkeypatch.delenv("AI_API_KEY", raising=False)
    monkeypatch.delenv("MAKEREND_API_KEY", raising=False)
    monkeypatch.setenv("AI_MODEL", "test-model")
    response = client.post("/api/v1/generation/extract", json={"prompt": "Review request"})
    assert response.status_code == 503
    assert len(client.get("/api/v1/samples").json()) == 3


def test_invalid_requests_do_not_echo_inputs(client):
    response = client.post("/api/v1/projects", json={"name": "secret-value", "secret": "do-not-echo"})
    assert response.status_code == 422
    assert "do-not-echo" not in response.text


def test_job_queue_is_bounded(client):
    p = project(client)
    m, c = model(client, p["id"])
    jobs = client.app.state.jobs
    try:
        assert all(jobs.reserve() for _ in range(8))
        response = client.post(f"/api/v1/projects/{p['id']}/runs", json={"model_id": m["id"], "config": c})
        assert response.status_code == 429
        assert client.get(f"/api/v1/projects/{p['id']}/runs").json() == []
    finally:
        for _ in range(8):
            jobs.capacity.release()


def test_running_cancel_never_accepts_results(client, monkeypatch):
    from threading import Event
    from backend.app import jobs as job_module

    actual_simulate = job_module.simulate
    entered, release = Event(), Event()

    def pause(workflow, config):
        entered.set()
        assert release.wait(5)
        return actual_simulate(workflow, config)

    monkeypatch.setattr(job_module, "simulate", pause)
    p = project(client)
    m, c = model(client, p["id"])
    r = start(client, p["id"], m["id"], c, "simulate")
    try:
        assert entered.wait(5)
        response = client.post(f"/api/v1/runs/{r['id']}/cancel")
        assert response.status_code == 200
        assert response.json()["state"] == "canceled"
    finally:
        release.set()
    client.app.state.jobs.shutdown()
    completed = client.get(f"/api/v1/runs/{r['id']}").json()
    assert completed["state"] == "canceled"
    assert completed["result"] is None
    assert client.get(f"/api/v1/runs/{r['id']}/artifacts/report.pdf").status_code == 404


def test_api_documentation_has_no_external_runtime(client):
    response = client.get("/docs")
    assert response.status_code == 200
    assert "/openapi.json" in response.text
    assert "https://" not in response.text

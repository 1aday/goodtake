import json

import pytest
from fastapi.testclient import TestClient

from goodtake.server import create_app

HEADERS = {"X-Goodtake": "1"}


@pytest.fixture
def client(store):
    with TestClient(create_app(store, testing=True, run_worker=False)) as client:
        yield client


def test_foreign_origins_and_dns_rebinding_are_rejected(client):
    assert client.post("/api/sample").status_code == 403
    assert (
        client.post("/api/sample", headers={**HEADERS, "Origin": "https://attacker.example"}).status_code
        == 403
    )
    assert client.get("/api/status", headers={"Host": "attacker.example"}).status_code == 400
    assert client.get("/api/status").status_code == 200


def test_settings_never_return_keys_or_store_them_with_projects(client, store, project):
    body = {"settings": store.settings().model_dump(), "openai_key": "sk-test-private-not-for-projects"}
    response = client.put("/api/settings", headers=HEADERS, json=body)
    assert response.status_code == 200
    assert response.json()["providers"]["openai"]
    assert "sk-test" not in json.dumps(response.json())
    assert "sk-test" not in client.get("/api/projects").text
    assert (store.root / "keys.json").stat().st_mode & 0o777 == 0o600


def test_editing_a_checked_clip_invalidates_download_and_approval(client, store, project, clip):
    store.change(
        project["id"],
        lambda p: p["clips"][0].update(status="checked", report={"pass": True}, render_directory="old"),
    )
    body = {key: clip[key] for key in ["title", "start", "end", "takeaway", "reason", "post", "style"]}
    body["title"] = "A new unverified title"
    response = client.put(f"/api/projects/{project['id']}/clips/{clip['id']}", headers=HEADERS, json=body)
    assert response.status_code == 200
    saved = store.get(project["id"])["clips"][0]
    assert saved["status"] == "draft" and "report" not in saved and "render_directory" not in saved
    assert (
        client.post(f"/api/projects/{project['id']}/clips/{clip['id']}/approve", headers=HEADERS).status_code
        == 422
    )
    assert client.get(f"/api/projects/{project['id']}/clips/{clip['id']}/assets/clip.mp4").status_code == 404


def test_unchanged_save_preserves_a_checked_export(client, store, project, clip):
    store.change(
        project["id"],
        lambda p: p["clips"][0].update(status="checked", report={"pass": True}, render_directory="saved"),
    )
    body = {key: clip[key] for key in ["title", "start", "end", "takeaway", "reason", "post", "style"]}
    response = client.put(f"/api/projects/{project['id']}/clips/{clip['id']}", headers=HEADERS, json=body)
    assert response.json()["clips"][0]["status"] == "checked"


def test_brand_changes_invalidate_all_export_checks(client, store, project, clip):
    store.change(project["id"], lambda p: p["clips"][0].update(status="ready", report={"pass": True}))
    brand = {**project["brand"], "show": "A different show"}
    response = client.put(
        f"/api/projects/{project['id']}", headers=HEADERS, json={"title": project["title"], "brand": brand}
    )
    assert response.json()["clips"][0]["status"] == "draft"


def test_ranges_and_nonfinite_numbers_are_rejected(client, project):
    path = f"/api/projects/{project['id']}/clips"
    assert (
        client.post(path, headers=HEADERS, json={"title": "Too long", "start": 0, "end": 181}).status_code
        == 422
    )
    assert (
        client.post(
            path, headers=HEADERS, json={"title": "Beyond source", "start": 290, "end": 320}
        ).status_code
        == 422
    )
    assert (
        client.post(
            path,
            headers={**HEADERS, "Content-Type": "application/json"},
            content='{"title":"Nonfinite input","start":0,"end":NaN}',
        ).status_code
        == 422
    )


def test_project_edits_are_locked_while_production_owns_the_plan(client, store, project, clip):
    store.enqueue(project["id"], "render", clip["id"])
    assert (
        client.delete(f"/api/projects/{project['id']}/clips/{clip['id']}", headers=HEADERS).status_code == 409
    )


def test_failed_checks_cannot_be_approved_or_enter_a_kit(client, store, project, clip):
    store.change(project["id"], lambda p: p["clips"][0].update(status="needs_review", report={"pass": False}))
    assert (
        client.post(f"/api/projects/{project['id']}/clips/{clip['id']}/approve", headers=HEADERS).status_code
        == 422
    )
    assert client.get(f"/api/projects/{project['id']}/kit").status_code == 422


def test_media_routes_have_a_closed_asset_allowlist(client, project, clip):
    path = f"/api/projects/{project['id']}/clips/{clip['id']}/assets/keys.json"
    assert client.get(path).status_code == 404
    assert "source_file" not in client.get(f"/api/projects/{project['id']}").json()


def test_provider_is_required_before_paying_for_automatic_selection(client, project):
    response = client.post(f"/api/projects/{project['id']}/jobs/analyze", headers=HEADERS)
    assert response.status_code == 422 and "OpenAI" in response.json()["detail"]


def test_transcript_replacement_removes_stale_check_reports(client, store, project, clip):
    store.change(project["id"], lambda p: p["clips"][0].update(status="checked", report={"pass": True}))
    data = {"words": [{"text": "A", "start": 0, "end": 1}, {"text": "thought", "start": 1, "end": 2}]}
    response = client.post(
        f"/api/projects/{project['id']}/transcript",
        headers=HEADERS,
        files={"file": ("words.json", json.dumps(data), "application/json")},
    )
    assert response.status_code == 200
    assert response.json()["clips"][0]["status"] == "draft"
    assert "report" not in response.json()["clips"][0]

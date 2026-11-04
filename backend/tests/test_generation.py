import json
import urllib.error
from unittest.mock import patch

import pytest

from backend.app import nlp_generator as gen
from backend.app.samples import sample


class Response:
    def __init__(self, content):
        self.content = content

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, n):
        return self.content[:n]


def response(data):
    return Response(json.dumps({"choices": [{"message": {"content": json.dumps(data)}}]}).encode())


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("AI_API_KEY", "test-secret")
    monkeypatch.setenv("AI_MODEL", "model-configured-by-user")
    monkeypatch.setenv("AI_BASE_URL", "https://provider.example/v1")


def test_extraction_review_then_accept(configured, client):
    ir = sample("order")["ir"]
    with patch("urllib.request.OpenerDirector.open", return_value=response(ir)) as call:
        extracted = client.post("/api/v1/generation/extract", json={"prompt": "Stated requirements"})
    assert extracted.status_code == 200, extracted.text
    data = extracted.json()
    assert data["review_required"] is True
    assert data["ir"] == ir
    request = call.call_args.args[0]
    payload = json.loads(request.data)
    assert request.full_url == "https://provider.example/v1/chat/completions"
    assert payload["model"] == "model-configured-by-user"
    assert "test-secret" not in extracted.text
    p = client.post("/api/v1/projects", json={"name": "AI review"}).json()
    assert (
        client.post(
            f"/api/v1/projects/{p['id']}/generation/accept", json={"ir": ir, "review_confirmed": False}
        ).status_code
        == 422
    )
    accepted = client.post(
        f"/api/v1/projects/{p['id']}/generation/accept", json={"ir": ir, "review_confirmed": True}
    )
    assert accepted.status_code == 201, accepted.text


def test_ambiguity_is_draft_only(configured, client):
    ir = sample("order")["ir"]
    ir["ambiguities"] = ["Is invoicing parallel or sequential?"]
    with patch("urllib.request.OpenerDirector.open", return_value=response(ir)):
        data = gen.extract("Ambiguous description")
    assert data["xml_preview"] is None
    assert any(d["code"] == "review_required" for d in data["diagnostics"])
    p = client.post("/api/v1/projects", json={"name": "AI"}).json()
    assert (
        client.post(
            f"/api/v1/projects/{p['id']}/generation/accept", json={"ir": ir, "review_confirmed": True}
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    "raw", [b"not json", b'{"choices":[]}', b'{"choices":[{"message":{"content":"<xml/>"}}]}', b"x" * 300001]
)
def test_malformed_provider_response_is_not_replaced(configured, raw):
    with (
        patch("urllib.request.OpenerDirector.open", return_value=Response(raw)),
        pytest.raises(gen.ProviderError),
    ):
        gen.extract("Review application")


@pytest.mark.parametrize("code", [401, 404, 429, 500])
def test_provider_http_failures_are_sanitized(configured, code):
    with patch(
        "urllib.request.OpenerDirector.open",
        side_effect=urllib.error.HTTPError("https://provider.example", code, "secret raw error", None, None),
    ):
        with pytest.raises(gen.ProviderError, match=f"HTTP {code}") as exc:
            gen.extract("Review")
    assert "secret raw error" not in str(exc.value)


def test_timeout(configured):
    with (
        patch("urllib.request.OpenerDirector.open", side_effect=TimeoutError),
        pytest.raises(gen.ProviderError, match="timed out"),
    ):
        gen.extract("Review")


def test_makerend_compatibility_and_no_default_model(monkeypatch):
    monkeypatch.delenv("AI_API_KEY", raising=False)
    monkeypatch.delenv("AI_MODEL", raising=False)
    monkeypatch.delenv("AI_BASE_URL", raising=False)
    monkeypatch.setenv("MAKEREND_API_KEY", "test")
    monkeypatch.setenv("MAKEREND_MODEL", "user-model")
    assert gen.provider_config()[:2] == ("test", "user-model")
    monkeypatch.delenv("MAKEREND_MODEL")
    assert not gen.status()["configured"]


def test_http_remote_and_redirects_are_rejected(monkeypatch):
    monkeypatch.setenv("AI_BASE_URL", "http://remote.example/v1")
    with pytest.raises(gen.ProviderError, match="HTTPS"):
        gen.provider_config()
    assert gen.NoRedirect().redirect_request(None, None, 302, "", None, "https://other.example") is None


def test_unknown_timing_and_extracted_provenance_round_trip(configured):
    ir = sample("order")["ir"]
    for node in ir["nodes"]:
        node["provenance"] = "ai_extracted"
        if node["kind"] in ("userTask", "serviceTask"):
            node["duration"], node["role"] = None, None
    with patch("urllib.request.OpenerDirector.open", return_value=response(ir)):
        draft = gen.extract("Named activities but no timing or staffing facts")
    assert draft["ir"]["nodes"] == ir["nodes"]
    from backend.app.bpmn import parse

    restored, _ = parse(draft["xml_preview"])
    assert restored.assumptions == ir["assumptions"]
    assert all(node.duration is None for node in restored.nodes)

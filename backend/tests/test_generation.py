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


def test_invalid_schema_is_repaired_once_with_original_requirements(configured):
    ir = sample("order")["ir"]
    broken = {**ir, "nodes": "not an array"}
    with patch("urllib.request.OpenerDirector.open", side_effect=[response(broken), response(ir)]) as call:
        result = gen.extract("Prepare invoice and inventory in parallel, then dispatch.")
    assert call.call_count == 2
    assert result["extraction_attempts"] == 2
    assert result["ir"] == ir
    payload = json.loads(call.call_args.args[0].data)
    assert payload["messages"][1]["content"] == "Prepare invoice and inventory in parallel, then dispatch."
    assert "Preserve the original" in payload["messages"][-1]["content"]
    assert "test-secret" not in payload["messages"][-1]["content"]


def test_invalid_topology_is_repaired_without_fabricated_fallback(configured):
    ir = sample("order")["ir"]
    broken = json.loads(json.dumps(ir))
    broken["edges"][0]["target"] = "missing"
    with patch("urllib.request.OpenerDirector.open", side_effect=[response(broken), response(ir)]):
        result = gen.extract("Stated process")
    assert result["extraction_attempts"] == 2
    assert not result["diagnostics"]


def test_repair_does_not_clear_material_ambiguity(configured):
    ir = sample("order")["ir"]
    ir["ambiguities"] = ["A retry loop was requested; cyclic execution is not supported."]
    with patch("urllib.request.OpenerDirector.open", return_value=response(ir)) as call:
        result = gen.extract("Retry inventory until available.")
    assert call.call_count == 1
    assert result["ir"] is None
    assert result["clarification_questions"] == ir["ambiguities"]
    assert result["xml_preview"] is None


@pytest.mark.parametrize("wrapper", ["fenced", "text_blocks"])
def test_common_provider_content_formats(configured, wrapper):
    ir = sample("order")["ir"]
    content = (
        "```json\n" + json.dumps(ir) + "\n```"
        if wrapper == "fenced"
        else [{"type": "text", "text": json.dumps(ir)}]
    )
    raw = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
    with patch("urllib.request.OpenerDirector.open", return_value=Response(raw)):
        assert gen.extract("Stated process")["ir"] == ir


def test_explicit_time_unit_survives_generated_xml(configured):
    ir = sample("order")["ir"]
    ir["time_unit"] = "minutes"
    with patch("urllib.request.OpenerDirector.open", return_value=response(ir)):
        result = gen.extract("Durations in minutes")
    from backend.app.bpmn import parse

    assert parse(result["xml_preview"])[0].time_unit == "minutes"


def test_long_description_is_supported_by_api(configured, client):
    ir = sample("order")["ir"]
    with patch("urllib.request.OpenerDirector.open", return_value=response(ir)):
        result = client.post("/api/v1/generation/extract", json={"prompt": "Process requirements. " * 1000})
    assert result.status_code == 200, result.text


def test_oversized_description_rejected_before_provider_call(configured):
    with patch("urllib.request.OpenerDirector.open") as call, pytest.raises(ValueError):
        gen.extract("x" * 60_001)
    call.assert_not_called()


def test_truncated_provider_output_has_actionable_error(configured):
    raw = json.dumps({"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]}).encode()
    with patch("urllib.request.OpenerDirector.open", return_value=Response(raw)) as call:
        with pytest.raises(gen.ProviderError, match="truncated"):
            gen.extract("Large description")
    assert call.call_count == 1


def test_provider_response_budget_is_enforced_before_repair(configured):
    with patch(
        "urllib.request.OpenerDirector.open", return_value=Response(b"x" * (gen.MAX_PROVIDER_BYTES + 1))
    ) as call:
        with pytest.raises(gen.ProviderError, match="size limit"):
            gen.extract("Process description")
    assert call.call_count == 1


def test_generation_concurrency_has_a_clear_busy_response(configured):
    assert gen.GENERATION_SLOTS.acquire(blocking=False)
    assert gen.GENERATION_SLOTS.acquire(blocking=False)
    try:
        with pytest.raises(gen.ProviderError, match="already running") as error:
            gen.extract("Process description")
        assert error.value.status == 429
    finally:
        gen.GENERATION_SLOTS.release()
        gen.GENERATION_SLOTS.release()


def test_vague_prompt_can_request_clarification_without_invented_work(configured, client):
    questions = {
        "clarification_questions": ["What steps should the process contain?", "What starts and completes it?"]
    }
    with patch("urllib.request.OpenerDirector.open", return_value=response(questions)) as call:
        result = client.post("/api/v1/generation/extract", json={"prompt": "make a good process"})
    assert result.status_code == 200, result.text
    assert result.json()["ir"] is None
    assert result.json()["clarification_questions"] == questions["clarification_questions"]
    assert result.json()["xml_preview"] is None
    assert call.call_count == 1


def test_two_invalid_schema_responses_stop_without_saving(configured):
    with patch("urllib.request.OpenerDirector.open", return_value=response({"nodes": "bad"})) as call:
        with pytest.raises(gen.ProviderError, match="one repair attempt"):
            gen.extract("Stated requirements")
    assert call.call_count == 2


def test_unrepaired_topology_returns_reviewable_diagnostics(configured):
    ir = sample("order")["ir"]
    ir["edges"][0]["target"] = "missing"
    with patch("urllib.request.OpenerDirector.open", return_value=response(ir)) as call:
        result = gen.extract("Stated requirements")
    assert call.call_count == 2
    assert result["xml_preview"] is None
    assert any(d["code"] == "dangling_flow" for d in result["diagnostics"])


def test_ai_gateway_deadlock_is_repaired_before_offering_xml(configured):
    ir = sample("loan")["ir"]
    bad = json.loads(json.dumps(ir))
    next(n for n in bad["nodes"] if n["id"] == "merge")["kind"] = "parallelGateway"
    with patch("urllib.request.OpenerDirector.open", side_effect=[response(bad), response(ir)]) as call:
        result = gen.extract("Approve or decline after review.")
    assert call.call_count == 2
    assert result["verification"]["status"] == "no_counterexample"
    assert result["xml_preview"] is not None


def test_unspecified_xor_conditions_do_not_trigger_ai_repair_or_block_review(configured, client):
    ir = sample("loan")["ir"]
    for edge in ir["edges"]:
        edge["condition"], edge["is_default"] = None, False
    with patch("urllib.request.OpenerDirector.open", return_value=response(ir)) as call:
        result = gen.extract("Review and follow one of the two explicitly selected routes.")
    assert call.call_count == 1
    assert result["xml_preview"] is not None
    assert result["ir"] == ir
    assert result["diagnostics"] and all(d["severity"] == "warning" for d in result["diagnostics"])
    p = client.post("/api/v1/projects", json={"name": "Explicit routes"}).json()
    accepted = client.post(
        f"/api/v1/projects/{p['id']}/generation/accept", json={"ir": ir, "review_confirmed": True}
    )
    assert accepted.status_code == 201, accepted.text

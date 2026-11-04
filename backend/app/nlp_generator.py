"""Optional structured extraction; no fabricated fallback and no direct AI XML."""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from pydantic import ValidationError

from .bpmn import parse, serialize, validate
from .domain import DomainError, Workflow

MAX_PROVIDER_BYTES = 300_000


class ProviderError(RuntimeError):
    def __init__(self, message, status=503):
        super().__init__(message)
        self.status = status


def provider_config():
    key = os.getenv("AI_API_KEY") or os.getenv("MAKEREND_API_KEY", "")
    model = os.getenv("AI_MODEL") or os.getenv("MAKEREND_MODEL", "")
    base = os.getenv("AI_BASE_URL") or os.getenv("MAKEREND_BASE_URL", "https://makerend.com/v1")
    parsed = urllib.parse.urlsplit(base)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ProviderError("Set a valid provider base URL in the backend environment.")
    if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ProviderError("Remote providers require HTTPS; HTTP is allowed only for a local model server.")
    return key.strip(), model.strip(), base.rstrip("/")


def status():
    try:
        key, model, base = provider_config()
        local = urllib.parse.urlsplit(base).hostname in ("localhost", "127.0.0.1", "::1")
        return {
            "configured": bool(model and (key or local)),
            "model": model or None,
            "destination": urllib.parse.urlsplit(base).netloc,
            "notice": "Only the submitted description and the extraction schema are sent to this provider. Review confidential information before sending.",
        }
    except ProviderError:
        return {
            "configured": False,
            "model": None,
            "destination": None,
            "notice": "Provider configuration is invalid.",
        }


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Do not forward server-side credentials to another origin.
        return None


def extract(prompt: str) -> dict:
    if not prompt.strip() or len(prompt) > 12_000:
        raise DomainError("Use a process description between 1 and 12,000 characters.")
    key, model, base = provider_config()
    local = urllib.parse.urlsplit(base).hostname in ("localhost", "127.0.0.1", "::1")
    if not model or (not key and not local) or key == "your_makerend_api_key":
        raise ProviderError(
            "Optional AI is not configured. Set AI_MODEL and AI_API_KEY (or MAKEREND_MODEL / MAKEREND_API_KEY). Import and samples work without AI."
        )
    system = (
        "Extract the described business process into JSON matching the supplied Workflow schema. "
        "Return JSON only, no XML. Use XML-compatible unique IDs. Include exactly one plain start and end. "
        "Tasks need explicit gateways for branching. Do not invent tasks, roles, durations, units, conditions, "
        "probabilities or parallelism. Duration/role must be null when unstated. Set provenance ai_extracted "
        "only for stated facts. List all material ambiguities in ambiguities; list assumptions separately. "
        "XOR sequence flows need stated condition labels, or a default. If logic is unclear, record an ambiguity. "
        "Supported nodes: startEvent,endEvent,task,userTask,serviceTask,parallelGateway,exclusiveGateway. "
        "Schema: " + json.dumps(Workflow.model_json_schema())
    )
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
    }
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(
        base + "/chat/completions", data=json.dumps(payload).encode(), headers=headers
    )
    try:
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=25) as response:
            raw = response.read(MAX_PROVIDER_BYTES + 1)
        if len(raw) > MAX_PROVIDER_BYTES:
            raise ProviderError("Provider response exceeded the size limit.", 502)
        content = json.loads(raw)["choices"][0]["message"]["content"]
        extracted = json.loads(content)
        workflow = Workflow.model_validate(extracted)
    except urllib.error.HTTPError as exc:
        raise ProviderError(
            f"Provider returned HTTP {exc.code}. Check credentials, model name and endpoint; no fallback model was generated.",
            502,
        ) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ProviderError(
            "Provider was unreachable or timed out. Retry or import a BPMN file.", 504
        ) from exc
    except (ValueError, TypeError, KeyError, IndexError, ValidationError) as exc:
        raise ProviderError(
            "Provider returned invalid structured workflow data. No model was saved; clarify the description and retry.",
            502,
        ) from exc
    diagnostics = validate(workflow)
    # Return a draft even when material ambiguity prevents acceptance.
    xml = None
    if not diagnostics:
        xml = serialize(workflow)
        round_trip, _ = parse(xml)
        if [n.model_dump() for n in round_trip.nodes] != [n.model_dump() for n in workflow.nodes]:
            raise ProviderError("Generated model failed semantic round-trip validation.", 502)
    return {
        "ir": workflow.model_dump(),
        "diagnostics": [d.model_dump() for d in diagnostics],
        "xml_preview": xml,
        "review_required": True,
        "provider": status(),
    }

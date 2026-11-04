"""Same-origin local API, immutable model versions, bounded jobs and run exports."""

import logging
import os
from html import escape
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import bpmn, nlp_generator
from .domain import DomainError, Scenario, Workflow
from .jobs import Jobs
from .persistence import Store, new_id, now
from .reporting import ARTIFACTS
from .samples import sample
from .verification import verify

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / "backend" / ".env", override=False)
log = logging.getLogger(__name__)


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ProjectBody(Body):
    name: str = Field(min_length=1, max_length=120)


class ImportBody(Body):
    name: str = Field(default="Imported model", min_length=1, max_length=120)
    xml: str = Field(min_length=1, max_length=1_000_000)


class RunBody(Body):
    model_id: str = Field(min_length=32, max_length=32)
    mode: Literal["simulate", "optimize"] = "simulate"
    config: Scenario


class ScenarioBody(Body):
    name: str = Field(min_length=1, max_length=120)
    config: Scenario


class ExtractBody(Body):
    prompt: str = Field(min_length=1, max_length=12_000)


class AcceptBody(Body):
    ir: Workflow
    review_confirmed: Literal[True]


def create_app(data_dir: Path | None = None):
    @asynccontextmanager
    async def lifespan(app):
        store = Store(data_dir or Path(os.getenv("OPTIMODEL_DATA_DIR", str(ROOT / "data"))))
        app.state.store, app.state.jobs = store, Jobs(store)
        yield
        app.state.jobs.shutdown()

    app = FastAPI(title="OptiModel Studio", version="3.0.0", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"])

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        origin = request.headers.get("origin")
        allowed_origins = {
            str(request.base_url).rstrip("/"),
            "http://127.0.0.1:8000",
            "http://localhost:8000",
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        }
        if request.method not in ("GET", "HEAD", "OPTIONS") and origin and origin not in allowed_origins:
            return JSONResponse(
                status_code=403,
                content={
                    "error": {
                        "code": "origin",
                        "message": "This local API accepts writes only from the Studio origin.",
                    }
                },
            )
        # Bound the stream even when Content-Length is absent or dishonest.
        if request.method in ("POST", "PUT", "PATCH"):
            limit = 1_100_000
            length = request.headers.get("content-length", "0")
            try:
                if int(length) > limit or int(length) < 0:
                    raise ValueError()
            except ValueError:
                return JSONResponse(
                    status_code=413,
                    content={"error": {"code": "body_limit", "message": "Request exceeds the 1.1 MB limit."}},
                )
            chunks, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    return JSONResponse(
                        status_code=413,
                        content={
                            "error": {"code": "body_limit", "message": "Request exceeds the 1.1 MB limit."}
                        },
                    )
                chunks.append(chunk)
            request._body = b"".join(chunks)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self' data:; img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
        )
        response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api/") else "no-cache"
        return response

    @app.exception_handler(DomainError)
    async def domain_error(request, exc):
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "model_invalid",
                    "message": str(exc),
                    "diagnostics": [d.model_dump() for d in exc.diagnostics],
                }
            },
        )

    @app.exception_handler(ValidationError)
    @app.exception_handler(RequestValidationError)
    async def input_error(request, exc):
        # Never echo input values (which might include secrets or huge model text).
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_request",
                    "message": "Invalid request fields.",
                    "diagnostics": [{"message": e["msg"], "path": list(e["loc"])} for e in exc.errors()[:20]],
                }
            },
        )

    @app.exception_handler(nlp_generator.ProviderError)
    async def provider_error(request, exc):
        return JSONResponse(
            status_code=exc.status, content={"error": {"code": "provider", "message": str(exc)}}
        )

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return JSONResponse(
            status_code=exc.status_code, content={"error": {"code": "http_error", "message": str(exc.detail)}}
        )

    @app.exception_handler(Exception)
    async def internal_error(request, exc):
        log.error("Local API failure (%s)", type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content={
                "error": {"code": "internal", "message": "Local operation failed. No result was accepted."}
            },
        )

    def store():
        return app.state.store

    def get(table, ident):
        record = store().get(table, ident)
        if record is None:
            raise HTTPException(404, "Record not found.")
        if table in ("models", "runs", "scenarios") and not store().get("projects", record["project_id"]):
            raise HTTPException(404, "Project not found.")
        return record

    def import_model(project_id, body):
        get("projects", project_id)
        workflow, diagnostics = bpmn.parse(body.xml)
        diagnostics.extend(bpmn.schema_check(body.xml))
        record = store().insert(
            "models",
            {
                "id": new_id(),
                "project_id": project_id,
                "name": body.name,
                "created": now(),
                "xml": body.xml,
                "ir": workflow.model_dump(),
                "diagnostics": [d.model_dump() for d in diagnostics],
            },
        )
        return display_model(record)

    def display_model(record):
        return {
            **record,
            "display_xml": record["xml"]
            if "BPMNShape" in record["xml"]
            else bpmn.serialize(Workflow.model_validate(record["ir"])),
        }

    @app.get("/api/v1/health")
    def health():
        return {"status": "ok", "version": "3.0.0", "storage_schema": 1, "provider": nlp_generator.status()}

    @app.get("/docs", response_class=HTMLResponse, include_in_schema=False)
    def offline_docs():
        rows = "".join(
            f"<tr><td>{escape(method.upper())}</td><td><code>{escape(path)}</code></td><td>{escape(operation.get('summary', ''))}</td></tr>"
            for path, operations in app.openapi()["paths"].items()
            for method, operation in operations.items()
        )
        return (
            '<!doctype html><html lang="en"><meta charset="utf-8"><title>OptiModel local API</title><style>body{font:15px system-ui;background:#F5F4EF;color:#1D2725;max-width:1100px;margin:40px auto;padding:20px}table{border-collapse:collapse;width:100%}td,th{padding:12px;border-bottom:1px solid #ccc;text-align:left}a{color:#315E68}</style><h1>OptiModel Studio / Local API</h1><p>Version 1 contract. No account or external connection is required.</p><p><a href="/">Open Studio</a> · <a href="/openapi.json">Complete OpenAPI schemas (JSON)</a> · <a href="/api/v1/health">Local health and provider configuration status</a></p><table><tr><th>Method</th><th>Route</th><th>Operation</th></tr>'
            + rows
            + "</table></html>"
        )

    @app.get("/api/v1/samples")
    def samples():
        return [sample(k) for k in ("order", "loan", "operations")]

    @app.get("/api/v1/projects")
    def projects():
        return store().list("projects")

    @app.post("/api/v1/projects", status_code=201)
    def create_project(body: ProjectBody):
        if not body.name.strip():
            raise DomainError("Project name cannot be blank.")
        return store().insert("projects", {"id": new_id(), "name": body.name.strip(), "created": now()})

    @app.patch("/api/v1/projects/{project_id}")
    def rename_project(project_id: str, body: ProjectBody):
        get("projects", project_id)
        if not body.name.strip():
            raise DomainError("Project name cannot be blank.")
        store().project_name(project_id, body.name.strip())
        return get("projects", project_id)

    @app.delete("/api/v1/projects/{project_id}")
    def delete_project(project_id: str):
        get("projects", project_id)
        if any(r["state"] in ("queued", "running") for r in store().list("runs", project_id)):
            raise HTTPException(409, "Cancel or finish active runs first.")
        store().delete_project(project_id)
        return {
            "deleted": True,
            "retention": "Local data is retained on disk; project and downloads are hidden.",
        }

    @app.get("/api/v1/projects/{project_id}/models")
    def models(project_id: str):
        get("projects", project_id)
        return [display_model(record) for record in store().list("models", project_id)]

    @app.post("/api/v1/projects/{project_id}/models", status_code=201)
    def model_import(project_id: str, body: ImportBody):
        return import_model(project_id, body)

    @app.post("/api/v1/projects/{project_id}/upload", status_code=201)
    async def upload(project_id: str, file: UploadFile = File(...)):
        if not file.filename or not file.filename.lower().endswith((".bpmn", ".xml")):
            raise DomainError("Upload a .bpmn or .xml file.")
        raw = await file.read(bpmn.MAX_XML + 1)
        if len(raw) > bpmn.MAX_XML:
            raise HTTPException(413, "BPMN exceeds 1 MB.")
        try:
            xml = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise DomainError("Use UTF-8 encoded BPMN XML.") from exc
        return import_model(project_id, ImportBody(name=Path(file.filename).name[:120], xml=xml))

    @app.get("/api/v1/models/{model_id}")
    def model(model_id: str):
        return display_model(get("models", model_id))

    @app.post("/api/v1/models/{model_id}/validate")
    def validate_model(model_id: str):
        record = get("models", model_id)
        workflow, _ = bpmn.parse(record["xml"])
        return {
            "structural": "valid",
            "supported": True,
            "diagnostics": record["diagnostics"],
            "verification": verify(workflow),
            "display_xml": record["xml"] if "BPMNShape" in record["xml"] else bpmn.serialize(workflow),
        }

    @app.get("/api/v1/projects/{project_id}/scenarios")
    def scenarios(project_id: str):
        get("projects", project_id)
        return store().list("scenarios", project_id)

    @app.post("/api/v1/projects/{project_id}/scenarios", status_code=201)
    def save_scenario(project_id: str, body: ScenarioBody):
        get("projects", project_id)
        return store().insert(
            "scenarios",
            {
                "id": new_id(),
                "project_id": project_id,
                "name": body.name,
                "created": now(),
                "config": body.config.model_dump(),
            },
        )

    @app.post("/api/v1/projects/{project_id}/runs", status_code=202)
    def start_run(project_id: str, body: RunBody):
        get("projects", project_id)
        record = get("models", body.model_id)
        if record["project_id"] != project_id:
            raise HTTPException(404, "Model does not belong to this project.")
        from .simulation import choose_routes, settings

        workflow = Workflow.model_validate(record["ir"])
        settings(workflow, body.config)
        choose_routes(workflow, body.config)
        if not app.state.jobs.reserve():
            raise HTTPException(429, "Local job queue is full (8 jobs). Wait for a run to finish.")
        ident = new_id()
        try:
            run = store().insert(
                "runs",
                {
                    "id": ident,
                    "project_id": project_id,
                    "model_id": body.model_id,
                    "created": now(),
                    "updated": now(),
                    "state": "queued",
                    "stage": "queued",
                    "mode": body.mode,
                    "config": body.config.model_dump(),
                },
            )
        except Exception:
            app.state.jobs.capacity.release()
            raise
        app.state.jobs.submit(ident)
        return run

    @app.get("/api/v1/projects/{project_id}/runs")
    def history(project_id: str):
        get("projects", project_id)
        return store().list("runs", project_id)

    @app.get("/api/v1/runs/{run_id}")
    def run(run_id: str):
        return get("runs", run_id)

    @app.post("/api/v1/runs/{run_id}/cancel")
    def cancel(run_id: str):
        record = get("runs", run_id)
        if record["state"] not in ("queued", "running"):
            raise HTTPException(409, "Only queued or running jobs can be canceled.")
        store().update_run(run_id, state="canceled", stage="canceled")
        return get("runs", run_id)

    @app.delete("/api/v1/runs/{run_id}")
    def delete_run(run_id: str):
        record = get("runs", run_id)
        if record["state"] in ("queued", "running"):
            raise HTTPException(409, "Cancel active runs before removing them.")
        store().update_run(run_id, deleted=1)
        return {"deleted": True, "retention": "Artifacts retained on local disk; downloads hidden."}

    @app.get("/api/v1/compare")
    def compare(left: str, right: str):
        a, b = get("runs", left), get("runs", right)
        if a["state"] != "succeeded" or b["state"] != "succeeded":
            raise HTTPException(409, "Compare completed runs.")
        same_model = a["model_id"] == b["model_id"]
        same = same_model and a["config"] == b["config"]
        only_capacity = same_model and {k: v for k, v in a["config"].items() if k != "resources"} == {
            k: v for k, v in b["config"].items() if k != "resources"
        }
        return {
            "left": a,
            "right": b,
            "comparison_scope": "identical assumptions"
            if same
            else "capacity scenario"
            if only_capacity
            else "different assumptions or models",
            "warning": None
            if same
            else "Changes in assumptions are not evidence of a fixed-resource optimization gain.",
        }

    @app.get("/api/v1/runs/{run_id}/artifacts/{name}")
    def artifact(run_id: str, name: str):
        record = get("runs", run_id)
        if name not in ARTIFACTS or record["state"] != "succeeded":
            raise HTTPException(404, "Artifact not available for this run.")
        path = store().run_dir(record["project_id"], run_id) / name
        if not path.is_file():
            raise HTTPException(404, "Artifact file is missing from local storage.")
        return FileResponse(path, media_type=ARTIFACTS[name], filename=f"{run_id[:8]}-{name}")

    @app.post("/api/v1/generation/extract")
    def extraction(body: ExtractBody):
        return nlp_generator.extract(body.prompt)

    @app.post("/api/v1/projects/{project_id}/generation/accept", status_code=201)
    def accept(project_id: str, body: AcceptBody):
        bpmn.require_valid(body.ir)
        xml = bpmn.serialize(body.ir)
        return import_model(project_id, ImportBody(name=body.ir.name[:120], xml=xml))

    # Old shared-artifact endpoints are intentionally retired; never silently return another run.
    @app.api_route("/{legacy}", methods=["GET", "POST"], include_in_schema=False)
    def legacy_route(legacy: str):
        if legacy in {
            "analyze",
            "prompt-to-workflow",
            "generate-xml-only",
            "convert-to-petri-net",
            "view-report",
            "download-report",
            "download-optimized-bpmn",
        }:
            raise HTTPException(
                410, "Legacy API retired. Use /api/v1 projects and run-specific artifacts. See /docs."
            )
        if legacy == "" and not (ROOT / "frontend" / "dist").exists():
            return JSONResponse(
                status_code=503,
                content={
                    "message": "Build the frontend: cd frontend; npm ci; npm run build. Then restart the server."
                },
            )
        dist = ROOT / "frontend" / "dist"
        if legacy in ("", "index.html") and (dist / "index.html").exists():
            return FileResponse(dist / "index.html")
        raise HTTPException(404, "Not found.")

    @app.get("/")
    def index():
        path = ROOT / "frontend" / "dist" / "index.html"
        if not path.exists():
            return JSONResponse(
                status_code=503,
                content={"message": "Build the frontend with npm ci and npm run build in frontend/."},
            )
        return FileResponse(path)

    dist = ROOT / "frontend" / "dist"
    if (dist / "assets").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")
    return app


app = create_app()

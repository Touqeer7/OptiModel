"""Canonical models. Durations are facts only when explicitly supplied."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

NodeKind = Literal[
    "startEvent", "endEvent", "task", "userTask", "serviceTask", "parallelGateway", "exclusiveGateway"
]
TASK_KINDS = {"task", "userTask", "serviceTask"}


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Diagnostic(Model):
    code: str
    message: str
    element_id: str | None = None
    severity: Literal["error", "warning", "info"] = "error"


class DomainError(ValueError):
    def __init__(self, message: str, diagnostics: list[Diagnostic] | None = None):
        super().__init__(message)
        self.diagnostics = diagnostics or [Diagnostic(code="invalid_input", message=message)]


class Node(Model):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(default="", max_length=500)
    kind: NodeKind
    duration: float | None = Field(default=None, gt=0, le=1_000_000)
    role: str | None = Field(default=None, min_length=1, max_length=100)
    provenance: Literal["source", "user", "example", "unknown", "ai_extracted"] = "unknown"


class Edge(Model):
    id: str = Field(min_length=1, max_length=100)
    source: str = Field(min_length=1, max_length=100)
    target: str = Field(min_length=1, max_length=100)
    name: str = Field(default="", max_length=500)
    condition: str | None = Field(default=None, max_length=1000)
    is_default: bool = False


class Workflow(Model):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(default="Untitled process", max_length=500)
    nodes: list[Node] = Field(min_length=3, max_length=200)
    edges: list[Edge] = Field(min_length=2, max_length=400)
    assumptions: list[str] = Field(default_factory=list, max_length=100)
    ambiguities: list[str] = Field(default_factory=list, max_length=100)


class Resource(Model):
    role: str = Field(min_length=1, max_length=100)
    capacity: int = Field(ge=1, le=32)
    cost_per_unit: float | None = Field(default=None, ge=0, le=1_000_000)


class TaskSetting(Model):
    duration: float = Field(gt=0, le=1_000_000)
    role: str = Field(min_length=1, max_length=100)
    provenance: Literal["user", "example", "source", "ai_extracted"] = "user"


class Scenario(Model):
    unit: Literal["time units", "minutes", "hours", "days"] = "time units"
    seed: int = Field(default=42, ge=0, le=2_147_483_647)
    resources: list[Resource] = Field(min_length=1, max_length=20)
    tasks: dict[str, TaskSetting] = Field(default_factory=dict, max_length=200)
    routes: dict[str, str] = Field(default_factory=dict, max_length=100)
    probabilities: dict[str, dict[str, float]] = Field(default_factory=dict, max_length=100)
    solver_seconds: float = Field(default=5, ge=0.01, le=15)

    @field_validator("resources")
    @classmethod
    def unique_roles(cls, resources):
        if len({r.role for r in resources}) != len(resources):
            raise ValueError("Resource roles must be unique.")
        if sum(r.capacity for r in resources) > 64:
            raise ValueError("At most 64 resource slots are supported.")
        return resources

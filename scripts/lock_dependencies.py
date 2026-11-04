"""Refresh the runtime lock from an already installed, verified development environment."""

from importlib.metadata import distribution
from pathlib import Path

from packaging.markers import default_environment
from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = [
    "fastapi",
    "uvicorn",
    "pydantic",
    "lxml",
    "networkx",
    "reportlab",
    "python-multipart",
    "ortools",
    "python-dotenv",
]


def main():
    todo, seen = list(RUNTIME), {}
    env = default_environment()
    env["extra"] = ""
    while todo:
        package = distribution(todo.pop())
        name = package.metadata["Name"]
        if name in seen:
            continue
        seen[name] = package.version
        for raw in package.requires or []:
            requirement = Requirement(raw)
            if requirement.marker is None or requirement.marker.evaluate(env):
                todo.append(requirement.name)
    text = "# Python 3.12+. Resolved on Python 3.14.3, Windows x64. See docs/validation-and-benchmarks.md.\n"
    text += "".join(
        f"{name}=={version}\n" for name, version in sorted(seen.items(), key=lambda x: x[0].lower())
    )
    (ROOT / "backend" / "requirements.lock").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()

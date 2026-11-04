"""Export the same transparent examples used by the offline UI."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.samples import sample  # noqa: E402

if __name__ == "__main__":
    output = ROOT / "examples"
    output.mkdir(exist_ok=True)
    for key in ("order", "loan", "operations"):
        data = sample(key)
        (output / f"{key}.bpmn").write_text(data["xml"], encoding="utf-8")
        (output / f"{key}.scenario.json").write_text(
            json.dumps(data["config"], indent=2) + "\n", encoding="utf-8"
        )

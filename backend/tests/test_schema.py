import copy
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.schema import SCHEMA_PATH, AnalysisResult, analysis_json_schema

FIXTURES = SCHEMA_PATH.parent / "fixtures"
VALID = sorted((FIXTURES / "valid").glob("*.json"))
INVALID_CASES = json.loads((FIXTURES / "invalid-cases.json").read_text())


def load(path: Path) -> Any:
    return json.loads(path.read_text())


@pytest.mark.parametrize("path", VALID, ids=lambda p: p.name)
def test_valid_fixture_passes_and_round_trips(path: Path) -> None:
    data = load(path)
    result = AnalysisResult.model_validate_json(path.read_text())
    assert json.loads(result.model_dump_json()) == data


@pytest.mark.parametrize("case", INVALID_CASES, ids=lambda c: c["name"])
def test_invalid_case_fails(case: dict[str, Any]) -> None:
    data = copy.deepcopy(load(FIXTURES / "valid" / "umowa.json"))
    *parents, last = case["path"]
    target = data
    for key in parents:
        target = target[key]
    if case.get("delete"):
        del target[last]
    else:
        target[last] = case["value"]
    with pytest.raises(ValidationError):
        AnalysisResult.model_validate_json(json.dumps(data))


def test_committed_json_schema_matches_models() -> None:
    # Compared as data, not text, so formatters may reflow the committed file.
    assert load(SCHEMA_PATH) == analysis_json_schema(), (
        "schema/analysis.schema.json is stale; run `uv run python -m app.schema`"
    )

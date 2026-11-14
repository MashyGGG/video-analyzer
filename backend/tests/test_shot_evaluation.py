import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "eval_shot_boundaries.py"
spec = importlib.util.spec_from_file_location("shot_evaluation", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_one_to_one_matching_and_errors():
    result = module.evaluate([{"id": "one", "split": "holdout", "reference_ms": [1000, 2000],
                               "predicted_ms": [700, 1200, 2300]}])
    assert result["matched_cuts"] == 2
    assert result["precision"] == pytest.approx(2 / 3)
    assert result["recall"] == 1
    assert result["f1"] == pytest.approx(0.8)
    assert result["median_error_ms"] == 300


def test_missing_cuts_and_empty_case():
    no_matches = module.evaluate([{"id": "one", "split": "holdout", "reference_ms": [1000],
                                   "predicted_ms": [1301]}])
    assert no_matches["f1"] == 0 and no_matches["matched_cuts"] == 0
    no_cuts = module.evaluate([{"id": "two", "split": "holdout", "reference_ms": [], "predicted_ms": []}])
    assert no_cuts["f1"] is None


@pytest.mark.parametrize("videos", [
    [{"id": "one", "split": "dev", "reference_ms": [], "predicted_ms": []}],
    [{"id": "one", "split": "holdout", "reference_ms": [1000, 1000], "predicted_ms": []}],
    [{"id": "one", "split": "holdout", "reference_ms": [1.0], "predicted_ms": []}],
])
def test_invalid_holdout_data_is_rejected(videos):
    with pytest.raises(ValueError):
        module.evaluate(videos)

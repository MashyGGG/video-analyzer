"""Evaluate physical cut predictions against labeled cuts, using one-to-one matching."""

import argparse
import json
import math
import statistics
from pathlib import Path


def evaluate(videos: list[dict], tolerance_ms: int = 300) -> dict:
    if tolerance_ms < 0 or not videos:
        raise ValueError("Invalid tolerance or empty dataset")
    identifiers: set[str] = set()
    errors: list[int] = []
    predicted_count = reference_count = 0
    for video in videos:
        identifier = video["id"]
        if not isinstance(identifier, str) or not identifier or identifier in identifiers:
            raise ValueError("Video IDs must be non-empty and unique across splits")
        identifiers.add(identifier)
        if video["split"] != "holdout":
            raise ValueError("Evaluation requires a separate holdout set")
        reference, predicted = video["reference_ms"], video["predicted_ms"]
        for values in (reference, predicted):
            if not isinstance(values, list) or len(values) > 30000 or any(type(x) is not int or x < 0 for x in values):
                raise ValueError("Cut times must be non-negative integer milliseconds")
            if values != sorted(set(values)):
                raise ValueError("Cut times must be strictly increasing")
        reference_count += len(reference)
        predicted_count += len(predicted)
        i = j = 0
        while i < len(reference) and j < len(predicted):
            distance = predicted[j] - reference[i]
            if abs(distance) <= tolerance_ms:
                errors.append(abs(distance))
                i += 1
                j += 1
            elif distance < -tolerance_ms:
                j += 1
            else:
                i += 1
    matched = len(errors)
    precision = matched / predicted_count if predicted_count else None
    recall = matched / reference_count if reference_count else None
    f1 = (2 * matched / (predicted_count + reference_count)) if predicted_count + reference_count else None
    errors.sort()
    return {"videos": len(videos), "tolerance_ms": tolerance_ms, "reference_cuts": reference_count,
            "predicted_cuts": predicted_count, "matched_cuts": matched, "precision": precision,
            "recall": recall, "f1": f1, "median_error_ms": statistics.median(errors) if errors else None,
            "p90_error_ms": errors[math.ceil(len(errors) * 0.9) - 1] if errors else None,
            "matching": "sorted earliest one-to-one"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Refusing to overwrite evaluation evidence")
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    result = evaluate(dataset["videos"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

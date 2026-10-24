"""Pre-label the test set: run the pipeline on eval/testset/<n>.jpg and write <n>.truth.json.

    python -m eval.prelabel            # pages without a truth file
    python -m eval.prelabel --force    # overwrite unreviewed truth files
    python -m eval.prelabel --mock     # no model: mock twin (for wiring tests)
    python -m eval.prelabel --only 3 7

LESS-style loop: the model's reading is the pseudo-label; Henry corrects it at /label.
Reviewed files (`"reviewed": true`) are never overwritten, even with --force.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from app import telemetry
from eval import truth as T

ROOT = Path(__file__).resolve().parent.parent


def predict(image: Path, mock: bool = False) -> dict:
    """Page twin for one photo. Mock twin when asked for, or when T3 is not importable."""
    rel = T.rel(image)
    if not mock:
        try:
            from transcribe import build_page_twin
        except Exception as exc:  # noqa: BLE001 - half-written module
            print(f"  transcribe unavailable ({type(exc).__name__}: {exc}); using mock", file=sys.stderr)
        else:
            t0 = time.perf_counter()
            with telemetry.timed("eval.prelabel", image=rel):
                twin = build_page_twin(rel, None)
            twin.setdefault("latency_ms", {})
            if twin["latency_ms"].get("snapshot_to_twin") is None:
                twin["latency_ms"]["snapshot_to_twin"] = round((time.perf_counter() - t0) * 1000.0, 1)
            return twin
    from app.pipeline import mock_twin

    twin = mock_twin(source="upload", original_path=rel)
    twin["_fallback"] = "prelabel --mock"
    return twin


def prelabel_page(name: str, force: bool = False, mock: bool = False, testset_dir: Path | None = None) -> Path | None:
    image = T.image_path(name, testset_dir)
    if image is None:
        return None
    existing = T.load_truth(name, testset_dir)
    if existing is not None and (existing.get("reviewed") or not force):
        return None
    twin = predict(image, mock=mock)
    return T.save_truth(name, T.truth_from_twin(twin, T.rel(image)), testset_dir)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--force", action="store_true", help="overwrite unreviewed truth files")
    p.add_argument("--mock", action="store_true", help="use the mock twin instead of the model")
    p.add_argument("--only", nargs="*", default=None, help="page names (stems) to process")
    p.add_argument("--testset", default=str(T.TESTSET_DIR))
    a = p.parse_args(argv)
    testset = Path(a.testset)
    names = a.only or T.page_names(testset)
    if not names:
        print(f"no photos in {testset}; put eval/testset/<n>.jpg there first")
        return 1
    done = 0
    for name in names:
        out = prelabel_page(name, force=a.force, mock=a.mock, testset_dir=testset)
        print(f"{name}: {'wrote ' + out.name if out else 'skipped (exists/reviewed/missing)'}")
        done += bool(out)
    print(f"{done}/{len(names)} pre-labelled; correct them at http://localhost:8000/label")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

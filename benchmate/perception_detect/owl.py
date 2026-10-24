"""OWLv2 zero-shot detection (Tier B). Model loads lazily once; weights cached by Hugging Face.

    python -m perception_detect.owl --download          # fetch weights ahead of the demo
    python -m perception_detect.owl photo.jpg           # print detections + latency
"""
from __future__ import annotations

import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._telemetry import timed
from .config import OWL_MODEL_ID, OWL_QUERIES, OWL_SCORE_THRESHOLD

_lock = threading.Lock()
_model: Any = None
_processor: Any = None
_device: str | None = None


@dataclass(frozen=True)
class Detection:
    bbox: tuple[float, float, float, float]   # [x, y, w, h] in the pixels of the image given
    score: float
    label: str                                # the text query that fired


def weights_cached(model_id: str = OWL_MODEL_ID) -> bool:
    """True when the weights are already on disk, so loading will not start a download."""
    try:
        from huggingface_hub import try_to_load_from_cache

        hit = try_to_load_from_cache(model_id, "model.safetensors")
        return isinstance(hit, str) and Path(hit).is_file()
    except Exception:
        return False


def pick_device() -> str:
    import torch

    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def load(model_id: str = OWL_MODEL_ID) -> tuple[Any, Any, str]:
    """Load (once) and return (processor, model, device)."""
    global _model, _processor, _device
    with _lock:
        if _model is None:
            with timed("owl.load", model=model_id) as info:
                import torch
                from transformers import Owlv2ForObjectDetection, Owlv2Processor

                _device = pick_device()
                _processor = Owlv2Processor.from_pretrained(model_id)
                _model = Owlv2ForObjectDetection.from_pretrained(model_id).to(_device).eval()
                info["device"] = _device
                torch.set_grad_enabled(False)
        return _processor, _model, _device  # type: ignore[return-value]


def warmup() -> bool:
    """Load the model (T5 may call this at server start). False if it cannot be loaded."""
    try:
        load()
        return True
    except Exception:
        return False


def detect(image: Any, queries: tuple[str, ...] = OWL_QUERIES,
           threshold: float = OWL_SCORE_THRESHOLD) -> list[Detection]:
    """Run OWLv2 on one image (path or HxWx3 BGR ndarray). Boxes are in that image's pixels."""
    import numpy as np
    import torch
    from PIL import Image, ImageOps

    if isinstance(image, (str, Path)):
        pil = ImageOps.exif_transpose(Image.open(image)).convert("RGB")   # match cv2's EXIF handling
    else:
        pil = Image.fromarray(np.ascontiguousarray(image[..., ::-1]))  # BGR -> RGB
    processor, model, device = load()
    with timed("owl.detect", w=pil.width, h=pil.height) as info:
        inputs = processor(text=[list(queries)], images=pil, return_tensors="pt").to(device)
        with torch.no_grad():
            outputs = model(**inputs)
        # OWLv2 pads the image to a square (bottom/right); boxes come back in that padded frame,
        # so the target size is the padded square and the original image is its top-left corner.
        side = max(pil.width, pil.height)
        results = processor.post_process_grounded_object_detection(
            outputs, threshold=threshold, target_sizes=torch.tensor([[side, side]]),
            text_labels=[list(queries)])[0]
        dets = []
        labels = results.get("text_labels") or [queries[int(i)] for i in results["labels"]]
        for box, score, label in zip(results["boxes"].tolist(), results["scores"].tolist(), labels):
            x0, y0, x1, y1 = box
            x0, y0 = max(0.0, x0), max(0.0, y0)
            x1, y1 = min(float(pil.width), x1), min(float(pil.height), y1)
            if x1 - x0 < 2 or y1 - y0 < 2:
                continue
            dets.append(Detection((x0, y0, x1 - x0, y1 - y0), float(score), str(label)))
        info["n"] = len(dets)
    return dets


def main(argv: list[str]) -> int:
    if "--download" in argv:
        load()
        print("weights ready:", OWL_MODEL_ID)
        return 0
    if not argv:
        print(__doc__)
        return 2
    import time

    t0 = time.perf_counter()
    dets = detect(argv[0])
    print(f"{len(dets)} detections in {(time.perf_counter() - t0) * 1000:.0f} ms (incl. load)")
    for d in dets:
        print(f"  {d.score:.2f} {d.label:<45} {[round(v) for v in d.bbox]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

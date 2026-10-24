"""Step 3: label reading - crop geometry and strict JSON parsing, with a fake client (no network)."""
from types import SimpleNamespace

import numpy as np
import pytest

from perception_detect import ocr


@pytest.fixture
def photo(tmp_path):
    import cv2

    img = np.full((400, 600, 3), 200, np.uint8)
    cv2.putText(img, "GY-BME280", (230, 210), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
    p = tmp_path / "frame.jpg"
    cv2.imwrite(str(p), img)
    return p


class FakeClient:
    def __init__(self, reply, stop_reason="end_turn"):
        self.reply, self.stop_reason, self.calls = reply, stop_reason, []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(stop_reason=self.stop_reason,
                               content=[SimpleNamespace(type="text", text=self.reply)])


def test_crop_pads_and_upscales_small_boxes(photo):
    import cv2

    jpeg = ocr.crop_component(str(photo), [220, 180, 160, 50])
    img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    h, w = img.shape[:2]
    assert (w, h) == (2 * 224, 2 * 70)           # 160*1.4 x 50*1.4, then 2x because < 256 px
    assert ocr.crop_component(str(photo), [10000, 10000, 5, 5]) is None
    assert ocr.crop_component(str(photo.with_name("nope.jpg")), [0, 0, 5, 5]) is None


def test_read_label_sends_image_and_parses_json(photo, monkeypatch):
    monkeypatch.setenv("BM_MODEL", "test-model")
    client = FakeClient('Sure: {"text": "GY-BME280", "legible": true}')
    assert ocr.read_label(str(photo), [220, 180, 160, 50], client) == {"text": "GY-BME280", "legible": True}
    kw = client.calls[0]
    assert kw["model"] == "test-model"
    content = kw["messages"][0]["content"]
    assert content[0]["type"] == "image" and content[0]["source"]["media_type"] == "image/jpeg"
    assert "do not guess" in content[1]["text"]


def test_read_label_returns_none_when_not_legible_or_bad(photo):
    assert ocr.read_label(str(photo), [220, 180, 160, 50], FakeClient('{"text": "", "legible": true}')) is None
    assert ocr.read_label(str(photo), [220, 180, 160, 50], FakeClient('{"text": "x", "legible": false}')) is None
    assert ocr.read_label(str(photo), [220, 180, 160, 50], FakeClient("I can't tell")) is None
    assert ocr.read_label(str(photo), [220, 180, 160, 50], FakeClient("{}", stop_reason="refusal")) is None


def test_read_label_without_api_key_is_none(photo, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert ocr.read_label(str(photo), [220, 180, 160, 50]) is None


@pytest.mark.parametrize("raw,expected", [
    ('{"text": "ESP32", "legible": true}', {"text": "ESP32", "legible": True}),
    ('```json\n{"text": "ESP32", "legible": "yes"}\n```', {"text": "ESP32", "legible": True}),
    ("[1,2]", None), ("", None), ('{"text": 5}', {"text": "5", "legible": False}),
])
def test_parse_label_json(raw, expected):
    assert ocr.parse_label_json(raw) == expected

"""Prompt prefix stability, dynamic sub-questions, image preparation, example bank."""
import copy
import json

from reasoning import images, prompt_builder
from reasoning.examples import load_examples, render_examples
from reasoning.profiles import load_profiles

import reasoning


def test_system_prefix_is_stable_and_cached(twin_swapped):
    profiles = load_profiles()
    a = prompt_builder.system_blocks(twin_swapped, profiles)
    b = prompt_builder.system_blocks(twin_swapped, profiles)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert a[-1]["cache_control"] == {"type": "ephemeral"}
    assert all("cache_control" not in blk for blk in a[:-1])
    assert "esp32-devkitc" in a[2]["text"] and "bme280" in a[2]["text"]
    assert "Example" in a[3]["text"]


def test_user_content_without_image_and_with_subquestions(twin_swapped, serial_swapped):
    twin = copy.deepcopy(twin_swapped)
    twin["wires"][4]["confidence"] = 0.4  # yellow SDA wire -> dynamic sub-question
    rules = reasoning.answer("why?", twin, serial_swapped, "nope.jpg")
    blocks, hits = prompt_builder.user_content("why?", twin, serial_swapped, "nope.jpg", rules, load_profiles())
    text = "\n".join(b["text"] for b in blocks if b["type"] == "text")
    assert "bme280_1.SDA" in text and "## Question\nwhy?" in text
    assert "no image available" in text
    assert "Which board pin is the sensor's SDA wire connected to?" in text
    assert "yellow wire w_yellow_1" in text
    assert isinstance(hits, list)


def test_images_downscale_and_tiles(tmp_path, twin_swapped):
    from PIL import Image
    p = tmp_path / "frame.jpg"
    Image.new("RGB", (2400, 1600), (200, 180, 160)).save(p)
    block = images.full_frame_block(str(p))
    assert block["type"] == "image" and block["source"]["media_type"] == "image/jpeg"
    import base64, io
    img = Image.open(io.BytesIO(base64.b64decode(block["source"]["data"])))
    assert max(img.size) <= images.MAX_LONG_SIDE
    twin = copy.deepcopy(twin_swapped)
    twin["wires"][4]["confidence"] = 0.4
    twin["wires"][4]["end_b"]["pixel"] = [1200, 800]
    tiles = images.tile_blocks(str(p), twin, 0.6)
    assert len(tiles) == 1 and tiles[0][0] == "w_yellow_1"
    assert images.full_frame_block("does_not_exist.jpg") is None
    assert images.tile_blocks("does_not_exist.jpg", twin, 0.6) == []


def test_example_bank_covers_required_cases():
    names = {e["name"] for e in load_examples()}
    assert {"ok board", "sda scl swapped", "vin on 5v", "missing ground", "unknown part", "low confidence wire"} <= names
    rendered = render_examples()
    assert "SDA and SCL are swapped" in rendered and "Correct output" in rendered

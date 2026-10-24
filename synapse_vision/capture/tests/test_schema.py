"""T1 outputs plug into page_twin.schema.json: `image` and `quality` sub-objects must validate."""
import jsonschema

from capture.page import detect_and_dewarp, tile


def _sub_schema(schema: dict, key: str) -> dict:
    return {"$schema": schema["$schema"], "$defs": schema.get("$defs", {}), **schema["properties"][key]}


def test_detect_and_dewarp_output_validates(schema, synth_photo):
    out = detect_and_dewarp(synth_photo["path"])
    jsonschema.validate(out["quality"], _sub_schema(schema, "quality"))
    image = {"original_path": synth_photo["path"], "dewarped_path": out["dewarped_path"],
             "width": out["width"], "height": out["height"], "homography": out["homography"]}
    jsonschema.validate(image, _sub_schema(schema, "image"))
    assert set(out) >= {"dewarped_path", "width", "height", "homography", "quality"}
    assert set(out["quality"]) >= {"ok", "issues", "blur_score", "glare_fraction"}


def test_tile_bboxes_are_schema_bboxes(schema, synth_photo):
    out = detect_and_dewarp(synth_photo["path"])
    tiles = tile(out["dewarped_path"], max_tiles=4)
    assert 1 <= len(tiles) <= 4
    bbox_schema = {"$schema": schema["$schema"], "$defs": schema["$defs"], **schema["$defs"]["bbox"]}
    for t in tiles:
        jsonschema.validate(t["bbox"], bbox_schema)
        assert set(t) >= {"path", "bbox"}


def test_detect_and_dewarp_never_raises_on_garbage(tmp_path):
    bad = tmp_path / "not_an_image.jpg"
    bad.write_bytes(b"definitely not a jpeg")
    out = detect_and_dewarp(str(bad))
    assert out["quality"]["ok"] is False
    assert "no_page" in out["quality"]["issues"]

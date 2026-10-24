import pytest

from perception_detect import normalize_part
from perception_detect.normalize import best_match


@pytest.mark.parametrize("text", ["GY-BME280", "bme 280", "BME280 3.3", "GYBMEP", "bme280", "GY-BME280 v1"])
def test_known_aliases_map_to_bme280(text):
    assert normalize_part(text) == "bme280"


@pytest.mark.parametrize("text", ["ESP32-WROOM-32", "esp32 devkit v1", "ESP32 DEVKIT V1", "ESP32-DEVKITC-32E"])
def test_known_aliases_map_to_an_esp32_profile(text):
    """T4 may split the ESP32 into several profiles (devkitc, devkit-v1, ...); any esp32 profile is right."""
    assert (normalize_part(text) or "").startswith("esp32")


@pytest.mark.parametrize("text", ["HC-SR04", "", "   ", "random garbage", "ATMEGA328P"])
def test_unknown_returns_none(text):
    assert normalize_part(text) is None


def test_near_miss_part_number_stays_below_threshold():
    """A one-letter-different part number must not match unless T4 lists it as an alias on purpose."""
    from perception_detect.normalize import alias_table, canon
    aliases = {canon(a) for a, _ in alias_table()}
    if "BMP280" in aliases:
        pytest.skip("T4 made BMP280 an alias of the sensor profile (real module is a BMP280)")
    pid, s = best_match("BMP280")
    assert pid == "bme280" and s < 85

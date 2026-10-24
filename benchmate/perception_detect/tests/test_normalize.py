import pytest

from perception_detect import normalize_part


@pytest.mark.parametrize("text", ["GY-BME280", "bme 280", "BME280 3.3", "GYBMEP", "bme280"])
def test_known_aliases_map_to_bme280(text):
    assert normalize_part(text) == "bme280"


@pytest.mark.parametrize("text", ["ESP32-WROOM-32", "esp32 devkit v1", "ESP32 DEVKIT V1"])
def test_known_aliases_map_to_esp32(text):
    assert normalize_part(text) == "esp32-devkitc"


@pytest.mark.parametrize("text", ["HC-SR04", "", "   ", "random garbage"])
def test_unknown_returns_none(text):
    assert normalize_part(text) is None

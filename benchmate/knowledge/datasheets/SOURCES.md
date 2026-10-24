# Datasheet sources (downloaded 2026-10-23 by T4)

| File | Part | Source URL | Notes |
|---|---|---|---|
| `bme280.pdf` | Bosch BME280 (humidity/pressure/temperature) | https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bme280-ds002.pdf | Official Bosch Sensortec datasheet BST-BME280-DS002 |
| `bmp280.pdf` | Bosch BMP280 (pressure/temperature) | https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bmp280-ds001.pdf | Fallback if the borrowed sensor is a BMP280 |
| `esp32-wroom-32.pdf` | ESP32-WROOM-32 module (the module on a DevKitC) | https://www.espressif.com/sites/default/files/documentation/esp32-wroom-32_datasheet_en.pdf | Official Espressif module datasheet (pin definitions) |
| `esp32.pdf` | ESP32 series SoC | https://www.espressif.com/sites/default/files/documentation/esp32_datasheet_en.pdf | Official Espressif SoC datasheet (GPIO/peripheral mux) |
| `esp32-devkitc-v4.pdf` | ESP32-DevKitC V4 board | https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32/esp-dev-kits-en-master-esp32.pdf | Pages 6-13 (labels 3-10) of Espressif's esp-dev-kits manual, carved out by `knowledge/tools/extract_devkitc_chapter.py`; the 33 MB full manual is not kept in the repo |
| `esp32-devkitc-user-guide.html` | ESP32-DevKitC board | https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32/esp32-devkitc/user_guide.html | Same content as HTML (header tables J2/J3) |
| `esp32-wroom-32e.pdf` | ESP32-WROOM-32E module (on DevKitC V4 boards) | https://www.espressif.com/sites/default/files/documentation/esp32-wroom-32e_esp32-wroom-32ue_datasheet_en.pdf | Official Espressif module datasheet |
| `arduino-uno.pdf` | Arduino Uno R3 | https://docs.arduino.cc/resources/datasheets/A000066-datasheet.pdf | Official Arduino datasheet, used only if the team gets an Uno |
| `arduino-uno-pinout.pdf` | Arduino Uno R3 pinout | https://docs.arduino.cc/resources/pinouts/A000066-full-pinout.pdf | Official pinout sheet |

Default I2C pins on ESP32 (GPIO21 = SDA, GPIO22 = SCL) are the Arduino-ESP32 core's default `Wire` pins, not a datasheet fact; the SoC datasheet maps I2C via the GPIO matrix to any pin.

# Hardware

## Must have (the demo does not exist without these)

| Item | Why | Notes |
|---|---|---|
| Camera looking straight down | Everything starts here | A phone beats a laptop webcam: better sensor, and a laptop camera cannot look down at the desk. iPhone + Mac: Continuity Camera shows up as a normal camera in OpenCV. Android: DroidCam or similar. A USB webcam also works. |
| Mount for that camera | A fixed mount is what makes calibration and the test set valid | Phone clamp / gooseneck holder, or tape the phone to a desk-lamp arm. Lens 30–40 cm above the board, parallel to it. |
| Light | Lighting matters more than resolution | Desk lamp or small LED panel from above-front. Avoid overhead fluorescent flicker and screen glare. |
| Solderless breadboard (830 holes) | The grid is what turns pixels into holes | |
| Microcontroller + USB *data* cable | Serial output is the second evidence source | ESP32 DevKit preferred. Arduino Uno works too (I2C on A4 = SDA, A5 = SCL; has both 5V and 3.3V pins, which makes the 5V scenario natural). Add a profile for whichever you get. |
| One I2C sensor that is 3.3 V-only | Scenario 1 needs a part that 5V would damage | Bare BME280/BMP280 breakout. Many "GY-" boards have a regulator and accept 5V — check before building scenario 1. |
| Jumper wires in at least 4 clearly different colors | Wire detection is color segmentation | Red, yellow, green, blue, orange work best. Avoid white (invisible on a white board), black (looks like holes and the ESP32), and two shades of one color. |
| 4 printed ArUco markers (`markers/aruco_sheet_print_me.png`) | Automatic board calibration | Print at about 2 cm, tape at the board corners: id 0 top-left, 1 top-right, 2 bottom-right, 3 bottom-left. |

Resolution check: at 1080p framing a 17 cm breadboard you get about 25 px per hole pitch (2.54 mm); at 720p about 16 px. Both are enough.

## Should have

- A second, pre-wired backup board for each failure state (5V, SDA/SCL swapped). Demo insurance.
- Matte single-color mat under the board (plain paper works) so wire colors stand out.
- Spare sensor, spare jumpers.

## Compute and accounts

- Laptops: everything runs on a normal laptop. OWLv2 zero-shot runs on CPU in a few seconds per tile; fine because analysis is event-triggered, not per frame. Apple Silicon can use `mps`.
- If you reach Tier C (YOLO training): Google Colab GPU, or a Mac with `mps`.
- Anthropic API key with credits for every terminal (`ANTHROPIC_API_KEY`).

## If you only have the camera

Go to the hackathon hardware lending area at the start and ask for: breadboard, ESP32 or Arduino Uno, one I2C sensor, jumper wire kit, USB cable. Design the demo around what you can actually borrow, then update `knowledge/profiles/` to match.

If no microcontroller is available at all, the serial evidence path drops out but the vision path still works: demo scenario 1 (wrong power rail) with a battery pack and an LED + resistor circuit, and change the profile checks accordingly.

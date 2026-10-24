# Camera setup

## Raspberry Pi camera (preferred for the demo)
1. Raspberry Pi OS Bookworm, camera module connected, `sudo apt install -y python3-picamera2`.
2. Copy `pi_snapshot_server.py` to the Pi, run `python3 pi_snapshot_server.py`.
3. From the laptop open `http://<pi-hostname>.local:8080/snapshot.jpg`. Put that URL in `config/vision.yaml` (`capture.pi_url`) and set `capture.source: pi`.
4. Pi and laptop must be on the same network. Hackathon Wi-Fi often blocks device-to-device traffic: if the URL won't load, connect both to a phone hotspot.

## Mount and light
- Lens 35–45 cm above the paper, pointing straight down; the whole sheet plus a 2–3 cm margin in frame.
- Desk lamp from the front-side, angled so its reflection is not in the camera's view (glare kills pencil).
- Dark desk mat or a sheet of dark paper under the page: makes page detection trivial.
- Clip the page flat. Fallback: tape the 4 ArUco markers (`markers/`) at the mat corners.

## Webcam/phone fallback
Set `capture.source: webcam`; find the index with `python -m capture.source --list`.

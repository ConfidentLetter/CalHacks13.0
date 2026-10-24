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

## What T1 found on Henry's Mac (H+1)
`python -m capture.source --list` → webcam indices 0 and 1 open at 1920×1080 but return **black frames** (virtual/inactive devices, e.g. Continuity Camera placeholders); **index 2 is the real built-in camera** (1920×1080). Index 3–5 and the Pi URL were not available. The probe now prints `BLACK frame` next to such devices. So for the laptop camera set `capture.webcam_index: 2`. A phone via Continuity Camera will take a different index once it is active — rerun `--list`.

First `get_snapshot("webcam")` takes ~2 s (open + exposure settle + 5 warm-up frames); later ones reuse the open camera (~50 ms). `wait_for_stable` polls 640×480 previews at 5 fps and fires one full-res snapshot after the scene changed and then stayed still for `capture.stable_seconds`.

## Debug output
Every `detect_and_dewarp` call writes `runtime/debug/page_<snapshot>.png`: original with the detected quad (green; orange = ArUco mat), the dewarped page, and the quality numbers. Open it when a photo is rejected.

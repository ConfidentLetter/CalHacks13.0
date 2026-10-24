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

## macOS Desk View (overhead) camera through ffmpeg — `avf:<device>` (H+11)
macOS "Desk View" virtual cameras (`MacBook Air桌上视角相机`, `“<name>”的桌上视角相机` for a Continuity iPhone) are
listed by ffmpeg's AVFoundation backend but **not** by OpenCV's `VideoCapture` indices, so they have their own source:

```
python -m capture.avf                                  # list video devices: avf:0 MacBook Air相机 … avf:3 MacBook Air桌上视角相机
python -m capture.source --snap --source avf                           # device from config capture.avf_device
python -m capture.source --snap --source "avf:MacBook Air桌上视角"   # or an explicit name substring / index
SV_SOURCE="avf:MacBook Air桌上视角" python -m capture.source --wait 20  # stability trigger on the Desk View stream
```

- **Address devices by name, not index.** ffmpeg renumbers paired iPhones between runs (the two iPhone entries swapped
  indices between two listings minutes apart); the MacBook entries also move when a phone connects. A substring must
  match exactly one device (`avf:桌上视角` alone is ambiguous when an iPhone is paired → the error lists the candidates).
- For the whole pipeline (T4 server / T5 bridge) set `capture.source: avf` (device = `capture.avf_device`, ffmpeg =
  `capture.avf_ffmpeg`) in `config/vision.yaml`, or export `SV_SOURCE=avf` for the server process.
- Implementation (`capture/avf.py`): one long-lived `ffmpeg -f avfoundation -framerate 30 -video_size <largest mode>
  -i <index> -vf fps=5 -f rawvideo -pix_fmt bgr24 -` process; frames are read from the pipe by a thread, previews and
  snapshots both come from it (device opened once, no second client). Desk View delivers 1920×1440 at 30 fps.
- Measured on this MacBook Air: first `get_snapshot` 2.5 s (ffmpeg start 0.7 s + 1.5 s exposure warm-up: frame mean
  rises 81 → 96 and is flat after ~1.4 s), later snapshots 70 ms; `wait_for_stable` polls at the stream's 5 fps.
- ffmpeg is found via env `SV_FFMPEG`, `capture.avf_ffmpeg`, `PATH`, then `/opt/homebrew/bin/ffmpeg`. Optional keys with
  defaults in code: `capture.avf_fps` 5, `capture.avf_warmup_s` 1.5, `capture.avf_frame_timeout_s` 5,
  `capture.avf_device_framerate` 30, `capture.avf_pixel_format` uyvy422.
- Lifecycle: `capture.source._avf()` owns one stream per process; it is reopened automatically if ffmpeg dies and
  **stopped after `capture.avf_idle_stop_s` (30 s) with no reader** (verified live: killed after the window, next call
  reopened it in 2.6 s). `capture.source.release_cameras()` stops it explicitly (every CLI run ends with that).
- `capture.source.latest_frame()` returns the frame currently in memory in ~0.3 ms (for T5's MJPEG grabber);
  `live_frame()` / `get_snapshot()` wait for a frame newer than the last one served (≤ 200 ms at 5 fps).
- Sample Desk View frame from this Mac: `runtime/snapshots/20261024_144603_302.jpg` (1920×1440, a white cloth and no paper in view →
  `no_page`, which is correct). Desk View is macOS's own top-down warp: the paper must lie close to the laptop base;
  the far part of the frame is stretched hard.

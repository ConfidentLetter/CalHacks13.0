# Contract changes

- H0: initial contracts.
- H0++: profiles use structured checks (kind/pin/target_role); detect_wires takes exclude_boxes; added hole_to_pixel, register, list_profiles, recent_reads, refine, POST /read, status message.
- H0+: calibrate() auto-detects ArUco ids 0-3; new WebSocket message `register` for click-to-register components.
- H+2 (Henry): `diagnosis.schema.json` — `findings[].evidence.datasheet[].page` now accepts `integer | string`. T4's `search()` returns string page labels; T3 should pass the label through unchanged instead of int-coercing, T5 renders it as text.

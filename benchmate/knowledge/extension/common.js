// Shared defaults for the BenchMate Study Mode extension (loaded by popup/options; duplicated in background.js
// because MV3 service workers cannot use classic <script> includes).
const BM_DEFAULT_ALLOWLIST = [
  "bosch-sensortec.com", "espressif.com", "docs.espressif.com", "arduino.cc", "docs.arduino.cc",
  "adafruit.com", "learn.adafruit.com", "sparkfun.com", "learn.sparkfun.com", "ti.com", "st.com",
  "microchip.com", "nxp.com", "analog.com", "wikipedia.org", "randomnerdtutorials.com", "localhost"
];
const BM_DEFAULT_ENDPOINT = "http://localhost:8000/read";

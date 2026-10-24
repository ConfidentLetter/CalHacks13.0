const toggle = document.getElementById("toggle");
const status = document.getElementById("status");

function render(on) {
  toggle.checked = !!on;
  status.textContent = on
    ? "On. Reads of allow-listed pages are sent to BenchMate on localhost."
    : "Off. Nothing is recorded.";
}
chrome.storage.sync.get("studyMode").then(({ studyMode }) => render(studyMode));
toggle.addEventListener("change", () => {
  chrome.storage.sync.set({ studyMode: toggle.checked });
  render(toggle.checked);
});
document.getElementById("options").addEventListener("click", (e) => {
  e.preventDefault();
  chrome.runtime.openOptionsPage();
});

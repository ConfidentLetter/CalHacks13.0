const ta = document.getElementById("allowlist");
const ep = document.getElementById("endpoint");
const saved = document.getElementById("saved");

function load() {
  chrome.storage.sync.get(["allowlist", "endpoint"]).then(({ allowlist, endpoint }) => {
    ta.value = (allowlist || BM_DEFAULT_ALLOWLIST).join("\n");
    ep.value = endpoint || BM_DEFAULT_ENDPOINT;
  });
}
function parseDomains(text) {
  return [...new Set(text.split(/\r?\n/).map((s) => s.trim().toLowerCase()).filter((s) => /^[a-z0-9.-]+$/.test(s)))];
}
document.getElementById("save").addEventListener("click", () => {
  let endpoint = ep.value.trim() || BM_DEFAULT_ENDPOINT;
  try {
    const u = new URL(endpoint);
    if (!["localhost", "127.0.0.1"].includes(u.hostname)) endpoint = BM_DEFAULT_ENDPOINT;
  } catch { endpoint = BM_DEFAULT_ENDPOINT; }
  chrome.storage.sync.set({ allowlist: parseDomains(ta.value), endpoint }).then(() => {
    saved.textContent = "Saved";
    setTimeout(() => (saved.textContent = ""), 1500);
    load();
  });
});
document.getElementById("reset").addEventListener("click", () => {
  chrome.storage.sync.set({ allowlist: BM_DEFAULT_ALLOWLIST, endpoint: BM_DEFAULT_ENDPOINT }).then(load);
});
load();

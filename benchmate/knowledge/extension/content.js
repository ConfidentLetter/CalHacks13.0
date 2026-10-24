// BenchMate Study Mode — content script. Does nothing on its own: it answers the service worker's request for
// the page text (first 20k characters of document.body.innerText) and reports tab visibility. No network calls.
const BM_MAX_TEXT = 20000;

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg && msg.type === "bm-get-text") {
    const body = document.body ? document.body.innerText || "" : "";
    const title = document.title || "";
    sendResponse({ text: (title ? title + "\n" : "") + body.slice(0, BM_MAX_TEXT) });
  }
  return false;
});

document.addEventListener("visibilitychange", () => {
  try {
    chrome.runtime.sendMessage({ type: "bm-visibility", hidden: document.visibilityState !== "visible" });
  } catch { /* extension reloaded */ }
});

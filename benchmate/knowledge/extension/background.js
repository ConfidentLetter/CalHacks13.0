// BenchMate Study Mode — service worker.
// Tracks how long the active tab's page has been in front of the user; after MIN_SECONDS on an allow-listed
// page it POSTs {url, text, seconds} to the local BenchMate server, then re-posts progress every ALARM_MINUTES
// and when the user leaves the page. Chrome's PDF viewer exposes no text to content scripts, so PDFs are sent
// with text: null and the server fetches the PDF itself. Nothing is ever sent anywhere but localhost.

const DEFAULT_ALLOWLIST = [
  "bosch-sensortec.com", "espressif.com", "docs.espressif.com", "arduino.cc", "docs.arduino.cc",
  "adafruit.com", "learn.adafruit.com", "sparkfun.com", "learn.sparkfun.com", "ti.com", "st.com",
  "microchip.com", "nxp.com", "analog.com", "wikipedia.org", "randomnerdtutorials.com", "localhost"
];
const DEFAULT_ENDPOINT = "http://localhost:8000/read";
const MIN_SECONDS = 30;
const ALARM_NAME = "bm-progress";
const ALARM_MINUTES = 1;

// Current reading session: {tabId, url, startedAt, accumulated, lastSent}. Kept in storage.session so a
// restarted service worker keeps counting.
async function getSession() {
  const { session } = await chrome.storage.session.get("session");
  return session || null;
}
async function setSession(session) {
  await chrome.storage.session.set({ session });
}
async function getSettings() {
  const { studyMode = false, allowlist = DEFAULT_ALLOWLIST, endpoint = DEFAULT_ENDPOINT } =
    await chrome.storage.sync.get(["studyMode", "allowlist", "endpoint"]);
  return { studyMode, allowlist, endpoint };
}

function hostAllowed(url, allowlist) {
  let host;
  try { host = new URL(url).hostname.toLowerCase(); } catch { return false; }
  return allowlist.some((d) => host === d || host.endsWith("." + d));
}
function isPdf(url) {
  try { return new URL(url).pathname.toLowerCase().endsWith(".pdf"); } catch { return false; }
}
function isTrackable(url) {
  return typeof url === "string" && /^https?:/.test(url);
}

async function pageText(tabId, url) {
  if (isPdf(url)) return null;
  try {
    const reply = await chrome.tabs.sendMessage(tabId, { type: "bm-get-text" });
    return reply && typeof reply.text === "string" ? reply.text : null;
  } catch {
    return null; // no content script on this page (chrome://, PDF viewer, not yet injected)
  }
}

async function post(endpoint, url, text, seconds) {
  const body = JSON.stringify({ url, text, seconds: Math.round(seconds) });
  // Only localhost endpoints are honoured, whatever the options page says.
  let target;
  try { target = new URL(endpoint); } catch { return; }
  if (!["localhost", "127.0.0.1"].includes(target.hostname)) return;
  try {
    await fetch(endpoint, { method: "POST", headers: { "Content-Type": "application/json" }, body });
  } catch (err) {
    console.debug("[BenchMate] server not reachable:", err && err.message);
  }
}

// Report the current session if it qualifies. `final` = the user is leaving the page.
async function flush(final) {
  const session = await getSession();
  if (!session) return;
  const { studyMode, allowlist, endpoint } = await getSettings();
  const seconds = session.accumulated + (session.startedAt ? (Date.now() - session.startedAt) / 1000 : 0);
  const unsent = seconds - (session.lastSent || 0);
  const shouldSend = studyMode && hostAllowed(session.url, allowlist) && seconds >= MIN_SECONDS &&
    (session.lastSent === 0 || unsent >= 15);
  if (shouldSend) {
    const text = await pageText(session.tabId, session.url);
    await post(endpoint, session.url, text, seconds);
    session.lastSent = seconds;
  }
  if (final) {
    await setSession(null);
  } else {
    session.accumulated = seconds;
    session.startedAt = Date.now();
    await setSession(session);
  }
}

async function startSession(tabId, url) {
  await flush(true);
  if (!isTrackable(url)) return;
  await setSession({ tabId, url, startedAt: Date.now(), accumulated: 0, lastSent: 0 });
}

async function pauseSession() {
  const session = await getSession();
  if (!session || !session.startedAt) return;
  session.accumulated += (Date.now() - session.startedAt) / 1000;
  session.startedAt = null;
  await setSession(session);
}

async function resumeSession() {
  const session = await getSession();
  if (!session || session.startedAt) return;
  session.startedAt = Date.now();
  await setSession(session);
}

async function syncToActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  const session = await getSession();
  if (!tab || !tab.url) { await flush(true); return; }
  if (!session || session.tabId !== tab.id || session.url !== tab.url) {
    await startSession(tab.id, tab.url);
  }
}

chrome.tabs.onActivated.addListener(() => syncToActiveTab());
chrome.tabs.onUpdated.addListener((tabId, info, tab) => {
  if (info.url && tab.active) syncToActiveTab();
});
chrome.tabs.onRemoved.addListener(async (tabId) => {
  const session = await getSession();
  if (session && session.tabId === tabId) await flush(true);
});
chrome.windows.onFocusChanged.addListener(async (windowId) => {
  if (windowId === chrome.windows.WINDOW_ID_NONE) await pauseSession();
  else { await resumeSession(); await syncToActiveTab(); }
});
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  // Content script reports visibility changes of its own document.
  (async () => {
    const session = await getSession();
    if (msg && msg.type === "bm-visibility" && sender.tab && session && session.tabId === sender.tab.id) {
      if (msg.hidden) await pauseSession(); else await resumeSession();
    }
    sendResponse({ ok: true });
  })();
  return true;
});
chrome.alarms.onAlarm.addListener((alarm) => { if (alarm.name === ALARM_NAME) flush(false); });
chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create(ALARM_NAME, { periodInMinutes: ALARM_MINUTES });
  chrome.storage.sync.get(["allowlist", "studyMode"]).then(({ allowlist, studyMode }) => {
    const init = {};
    if (!allowlist) init.allowlist = DEFAULT_ALLOWLIST;
    if (studyMode === undefined) init.studyMode = false;
    if (Object.keys(init).length) chrome.storage.sync.set(init);
  });
});
chrome.runtime.onStartup.addListener(() => chrome.alarms.create(ALARM_NAME, { periodInMinutes: ALARM_MINUTES }));

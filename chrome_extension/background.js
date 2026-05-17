/* LeadsManager WhatsApp Sync — background service worker.
 * Stores the LeadsManager server URL and brokers fetches (sends session cookies).
 */
const DEFAULT_SERVER = 'https://eadmanager-fresh-2024-dev-f83e51d73e01.herokuapp.com';

async function getServer() {
  const { server } = await chrome.storage.sync.get(['server']);
  return (server || DEFAULT_SERVER).replace(/\/+$/, '');
}

chrome.runtime.onMessage.addListener((req, sender, sendResponse) => {
  if (req.type === 'LM_FETCH') {
    (async () => {
      try {
        const server = await getServer();
        const url = server + req.path;
        const opts = req.opts || {};
        opts.credentials = 'include'; // send session cookies
        const res = await fetch(url, opts);
        const data = await res.json().catch(() => ({}));
        sendResponse({ ok: res.ok, status: res.status, data });
      } catch (e) {
        sendResponse({ ok: false, error: String(e && e.message || e) });
      }
    })();
    return true; // async
  }
  if (req.type === 'LM_GET_SERVER') {
    getServer().then((s) => sendResponse({ server: s }));
    return true;
  }
  if (req.type === 'LM_SET_SERVER') {
    chrome.storage.sync.set({ server: req.server || DEFAULT_SERVER }).then(() => sendResponse({ ok: true }));
    return true;
  }
});

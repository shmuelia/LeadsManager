/* Popup: drives the user flow.
 *  1) Asks the content script (on web.whatsapp.com tab) to extract the current chat
 *  2) Auto-fills the phone (if detected) or uses what the user typed
 *  3) POSTs to /api/whatsapp/import on the LeadsManager backend (background script forwards the fetch so cookies are included)
 */
const $ = (id) => document.getElementById(id);

function setStatus(msg, cls) {
  const el = $('status');
  el.textContent = msg;
  el.className = 'status' + (cls ? ' ' + cls : '');
}

async function getActiveWhatsappTab() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  const tab = tabs[0];
  if (!tab || !tab.url || tab.url.indexOf('https://web.whatsapp.com') !== 0) {
    return null;
  }
  return tab;
}

async function sendToContent(tab, payload) {
  return new Promise((resolve) => {
    chrome.tabs.sendMessage(tab.id, payload, (resp) => {
      if (chrome.runtime.lastError) {
        resolve({ ok: false, error: chrome.runtime.lastError.message });
      } else {
        resolve(resp || { ok: false, error: 'no response from content script' });
      }
    });
  });
}

async function lmFetch(path, opts) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage({ type: 'LM_FETCH', path, opts }, resolve);
  });
}

// On load: fill server input, last URL phone, etc.
(async function init() {
  const srvResp = await new Promise((r) => chrome.runtime.sendMessage({ type: 'LM_GET_SERVER' }, r));
  $('server').value = srvResp.server || '';

  const { lastUrlPhone, lastUrlPhoneAt } = await chrome.storage.local.get(['lastUrlPhone', 'lastUrlPhoneAt']);
  if (lastUrlPhone) {
    $('phone').value = lastUrlPhone;
    const minsAgo = lastUrlPhoneAt ? Math.round((Date.now() - lastUrlPhoneAt) / 60000) : '?';
    $('autoPhoneNote').textContent = `📥 זוהה אוטומטית לפני ${minsAgo} דק׳`;
  }
})();

$('saveServerBtn').addEventListener('click', async () => {
  const v = $('server').value.trim();
  await new Promise((r) => chrome.runtime.sendMessage({ type: 'LM_SET_SERVER', server: v }, r));
  setStatus('✔ השרת נשמר', 'ok');
});

$('lookupBtn').addEventListener('click', async () => {
  const phone = $('phone').value.trim();
  if (!phone) return setStatus('⚠ הזן טלפון', 'err');
  setStatus('🔍 מחפש ליד...');
  const resp = await lmFetch(`/api/leads/by-phone?phone=${encodeURIComponent(phone)}`, { method: 'GET' });
  if (!resp.ok) return setStatus('⚠ שגיאת רשת: ' + (resp.error || resp.status), 'err');
  if (resp.data && resp.data.found) {
    setStatus(`✔ נמצא: ${resp.data.name} (#${resp.data.lead_id}, סטטוס: ${resp.data.status})`, 'ok');
  } else {
    setStatus('❌ לא נמצא ליד עם הטלפון הזה', 'err');
  }
});

$('syncBtn').addEventListener('click', async () => {
  const tab = await getActiveWhatsappTab();
  if (!tab) return setStatus('⚠ פתח טאב של web.whatsapp.com', 'err');

  setStatus('📥 מחלץ הודעות מהצ׳אט...');
  const ext = await sendToContent(tab, { type: 'EXTRACT_CHAT' });
  if (!ext.ok) return setStatus('⚠ ' + (ext.error || 'extraction failed'), 'err');

  const phone = ($('phone').value || ext.phone || '').trim();
  if (!phone) return setStatus('⚠ לא נמצא טלפון — הזן ידנית', 'err');

  if (!ext.messages || ext.messages.length === 0) {
    return setStatus('⚠ לא נמצאו הודעות בצ׳אט הזה', 'err');
  }

  setStatus(`📤 שולח ${ext.messages.length} הודעות...`);
  const resp = await lmFetch('/api/whatsapp/import', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ phone, messages: ext.messages }),
  });

  if (!resp.ok) {
    return setStatus(`⚠ ${resp.status || ''} ${resp.data && resp.data.error || resp.error || 'שגיאה'}`, 'err');
  }
  const d = resp.data || {};
  setStatus(`✔ ייבוא הסתיים: ${d.imported || 0} חדשות, ${d.skipped || 0} כפילויות (ליד #${d.lead_id})`, 'ok');
});

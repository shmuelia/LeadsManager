/* LeadsManager WhatsApp Sync — content script.
 * Runs on web.whatsapp.com. Scrapes the currently-open chat on demand
 * and replies to the popup with {phone, messages}.
 *
 * WhatsApp Web's class names are obfuscated and change. We rely on stable-ish hooks:
 *   - [data-pre-plain-text]  → carries "[HH:MM, DD/MM/YYYY] Sender Name: " (timestamp + sender)
 *   - .message-in / .message-out ancestors → direction (or copyable-text wrappers)
 *   - main panel: header has the chat title/phone
 */
(function () {
  'use strict';

  // -------- chat phone detection --------
  // 1) Capture phone from the URL on /send/?phone=...  (LeadsManager's WhatsApp button uses this)
  // 2) Fall back to clicking the header → reading the contact-info panel
  let lastUrlPhone = null;
  function rememberUrlPhone() {
    try {
      const sp = new URLSearchParams(window.location.search);
      const p = sp.get('phone');
      if (p) {
        lastUrlPhone = p.replace(/[^\d]/g, '');
        chrome.storage.local.set({ lastUrlPhone, lastUrlPhoneAt: Date.now() });
      }
    } catch (e) {}
  }
  rememberUrlPhone();
  // WhatsApp rewrites the URL very quickly — also listen for SPA nav.
  const _push = history.pushState;
  history.pushState = function () { _push.apply(this, arguments); rememberUrlPhone(); };
  window.addEventListener('popstate', rememberUrlPhone);

  function detectChatPhone() {
    // Prefer URL-captured phone (most reliable)
    if (lastUrlPhone) return lastUrlPhone;
    // Try the header — for unsaved contacts, the header shows the phone like "+972 50-123-4567"
    const headerTitle = document.querySelector('header [title]');
    if (headerTitle) {
      const t = headerTitle.getAttribute('title') || headerTitle.textContent || '';
      const digits = t.replace(/[^\d]/g, '');
      if (digits.length >= 9) return digits;
    }
    return '';
  }

  // -------- message extraction --------
  function extractMessages() {
    const out = [];
    // Find every element with a data-pre-plain-text (one per message bubble)
    const bubbles = document.querySelectorAll('[data-pre-plain-text]');
    bubbles.forEach((bubble) => {
      const meta = bubble.getAttribute('data-pre-plain-text') || '';
      // meta looks like: "[HH:MM, DD/MM/YYYY] Sender Name: "
      const timeMatch = meta.match(/\[([^\]]+)\]/);
      const senderMatch = meta.match(/]\s*([^:]+):/);
      const timestamp = timeMatch ? timeMatch[1].trim() : '';
      const sender = senderMatch ? senderMatch[1].trim() : '';

      // Direction: walk up to find .message-in or .message-out
      let node = bubble;
      let direction = 'log';
      for (let i = 0; i < 8 && node; i++) {
        const cls = node.className || '';
        if (typeof cls === 'string') {
          if (cls.indexOf('message-out') !== -1) { direction = 'sent'; break; }
          if (cls.indexOf('message-in') !== -1) { direction = 'received'; break; }
        }
        node = node.parentElement;
      }

      // Text: the span inside .copyable-text that contains the actual message
      // Try a few selectors
      let text = '';
      const candidates = [
        bubble.querySelector('span.selectable-text'),
        bubble.querySelector('.copyable-text span.selectable-text'),
        bubble.querySelector('span'),
      ].filter(Boolean);
      if (candidates.length) text = candidates[0].innerText || candidates[0].textContent || '';
      text = (text || '').trim();
      if (!text) return; // skip non-text messages (images, voice, etc.)

      out.push({ text, direction, timestamp, sender });
    });
    return out;
  }

  // -------- message bridge from popup --------
  chrome.runtime.onMessage.addListener((req, sender, sendResponse) => {
    if (req && req.type === 'EXTRACT_CHAT') {
      try {
        const phone = detectChatPhone();
        const messages = extractMessages();
        sendResponse({ ok: true, phone, messages, count: messages.length, url: location.href });
      } catch (e) {
        sendResponse({ ok: false, error: String(e && e.message || e) });
      }
      return true; // keep channel open for async
    }
  });
})();

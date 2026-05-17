# LeadsManager WhatsApp Sync — Chrome extension

Pulls the currently-open WhatsApp Web chat into LeadsManager as activity entries.
No copy-paste; click one button and the messages are saved on the matching lead.

## Install (one-time, ~30 seconds)

1. Open Chrome → `chrome://extensions/`
2. Top-right toggle → **Developer mode** ON
3. Click **Load unpacked**
4. Pick this folder: `chrome_extension/`
5. The icon "LeadsManager WhatsApp Sync" appears in the toolbar (pin it for convenience).

## Use it

1. Log into **LeadsManager** in any tab (cookies are reused — no extra login).
2. From a lead row, click 📋 / ✨ / 💬 to open the WhatsApp Web chat (the phone is auto-detected from the URL).
3. Wait until the chat is fully loaded and you can see the messages.
4. Click the extension icon → **🔄 סנכרן צ׳אט נוכחי**.
5. The popup shows e.g. `✔ ייבוא הסתיים: 14 חדשות, 0 כפילויות` — that's it.

The phone field auto-fills from the URL captured when you opened the chat. If you got there by searching inside WhatsApp Web instead, type the phone (e.g. `972501234567`) manually and click **🔍 בדוק** to confirm a matching lead exists.

## How it works

- `content.js` runs on `web.whatsapp.com`, scans every `[data-pre-plain-text]` bubble in the open chat, and extracts {text, direction, timestamp}.
- `popup.js` POSTs the array to `/api/whatsapp/import` on the LeadsManager backend.
- The backend matches the phone (Israeli normalisation, last 9 digits) to a lead within the current customer scope and saves each message as a `whatsapp_message` activity. SHA-256 hashes are stored in `activity_metadata.msg_hash` to dedupe across repeat syncs.

## Server URL

Default points to `eadmanager-fresh-2024-dev-f83e51d73e01.herokuapp.com`. To switch (e.g. production), open the popup → "הגדרות מתקדמות" → change the URL → "💾 שמור שרת".

## Privacy

- The extension only sends data to the LeadsManager server you configured. Nothing else.
- It requires `host_permissions` for `web.whatsapp.com` (to read the open chat) and the LeadsManager domain (to POST).
- Cookies from the LeadsManager tab are used — you must already be logged in there.

## Known limitations

- Only text messages (no images, voice, stickers).
- WhatsApp Web changes its DOM occasionally; if extraction stops working, the `[data-pre-plain-text]` selector in `content.js` may need updating.
- The lead must already exist in LeadsManager with the matching phone number for that customer. Use **🔍 בדוק** to verify before syncing.

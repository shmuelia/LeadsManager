---
name: photo-send-to-whatsapp
description: How the lead-detail "Send Photos" flow delivers gallery images to WhatsApp, and the user's desktop setup
metadata:
  type: project
---

The "Send Photos" feature (lead detail popup in `templates/unified_lead_manager.html`, `openGalleryShare` / `_sendPhotos` / `_mobileSharePhotos` / `_desktopSendPhotos`) lets a campaign manager send gallery photos to a lead over WhatsApp.

User's primary environment for this: **desktop, Microsoft Edge + WhatsApp installed from the Microsoft Store**. This is the supported combo for the Web Share API (`navigator.share({files})`) → Windows share sheet → WhatsApp attaches all photos in one action.

**The user strongly prefers the one-click Windows Share path and dislikes any download-then-drag fallback.** Do NOT auto-fall-back to downloading when share fails — surface the real error (`e.name`) instead. The grouped-folder download (`Downloads/whatsapp-<slug>/`) exists only as the explicit "⬇ רק הורד" secondary button and for browsers that can't share files.

Final design (verified live in Chrome via the in-browser MCP):
- Desktop (Edge/Chrome) + Android → **single click**: `_shareNow()` fetches the selected photos then calls `navigator.share({files})`. Transient user activation survives the fetch (~0.5s for 3 images; 5s activation window), so no "click again" step. Confirmed `share()` is called with `userActivation.isActive === true`.
- iOS only → two-stage `_mobileSharePhotos` (prepare-then-share), because iOS Safari rejects `share()` if there's any async gap before it.
- Routing lives in `_sendPhotos`; `isIOS` is computed in `openGalleryShare`.

DO NOT re-add a `whatsapp://send?phone=...` pre-open before sharing. It was tried (v703) and BROKE the flow: on the user's machine it launched WhatsApp Desktop and stole focus on the first click, so the user never completed the share. Confirmed via Chrome that it fires a page `beforeunload`. The customer's chat already exists from earlier correspondence, so it shows in WhatsApp's share picker without pre-opening.

Hard constraint: the OS share sheet has no recipient field — WhatsApp always shows its own chat picker; a web page cannot pre-select the contact. `whatsapp://` only opens a chat with text; clipboard pastes one image at a time. The Meta Cloud API can send images server-side but only inside the 24h customer-service window (see [[whatsapp-setup]]).

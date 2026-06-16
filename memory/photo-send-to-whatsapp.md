---
name: photo-send-to-whatsapp
description: How the lead-detail "Send Photos" flow delivers gallery images to WhatsApp, and the user's desktop setup
metadata:
  type: project
---

The "Send Photos" feature (lead detail popup in `templates/unified_lead_manager.html`, `openGalleryShare` / `_sendPhotos` / `_mobileSharePhotos` / `_desktopSendPhotos`) lets a campaign manager send gallery photos to a lead over WhatsApp.

User's primary environment for this: **desktop, Microsoft Edge + WhatsApp installed from the Microsoft Store**. This is the supported combo for the Web Share API (`navigator.share({files})`) → Windows share sheet → WhatsApp attaches all photos in one action.

**The user strongly prefers the one-click Windows Share path and dislikes any download-then-drag fallback.** Do NOT auto-fall-back to downloading when share fails — surface the real error (`e.name`) instead. The grouped-folder download (`Downloads/whatsapp-<slug>/`) exists only as the explicit "⬇ רק הורד" secondary button and for browsers that can't share files.

Hard constraint: a web page cannot push files into WhatsApp Desktop except via the OS share sheet — `whatsapp://` only opens a chat with text; clipboard pastes one image at a time. The Meta Cloud API can send images server-side but only inside the 24h customer-service window (see [[whatsapp-setup]]).

Mobile uses the same `_mobileSharePhotos` two-stage flow (prepare-then-share) so `share()` runs on a fresh click (iOS transient-activation requirement).

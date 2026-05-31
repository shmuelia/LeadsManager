---
name: whatsapp-setup
description: Step-by-step guide for the Meta WhatsApp Cloud API integration in LeadsManager — webhook subscription, sending test messages, swapping to the real business number, token renewal, and troubleshooting. Use when the user asks about WhatsApp setup, webhooks, Meta dashboard, sending WhatsApp from the app, or "continue the WhatsApp setup".
---

# WhatsApp Cloud API — Setup & Operations Guide

This is a **step-by-step** runbook for אמיקם. Present **one step at a time**, wait for
confirmation/screenshot before the next. Do not dump the whole list at once.

## Key facts (current state)

| Item | Value |
|---|---|
| Meta App | **LeadMessaging** · App ID `837819029404196` |
| WABA (WhatsApp Business Account) | `1702506717540173` |
| Test phone | `+1 555-640-1377` · Phone ID `1151422578047739` |
| Test recipient (אמיקם cell) | `+972 54 593 2808` |
| Webhook URL | `https://eadmanager-fresh-2024-dev-f83e51d73e01.herokuapp.com/webhook/whatsapp` |
| Webhook verify token | `leadsmgr_wa_verify_7x2k9` |
| Registration PIN | `835291` |

Heroku config vars (app `eadmanager-fresh-2024-dev`):
`META_WA_TOKEN` (permanent system-user token), `META_WA_PHONE_ID`,
`META_WA_BUSINESS_ID`, `META_WA_VERIFY_TOKEN`, `META_WA_PIN`,
optional `META_WA_APP_SECRET`, `META_WA_CUSTOMER_ID` (default 1).

---

## TASK A — Subscribe the webhook (final setup step)

> Do this once. After it, customer replies auto-log into LeadsManager.

**A1.** In Chrome, open the LeadMessaging app config page:
`https://developers.facebook.com/apps/837819029404196/whatsapp-business/wa-settings/`
→ say "open" when it loads.

**A2.** Find the **Webhook** section at the top → click **"Edit" (ערוך)**.
→ screenshot.

**A3.** In the dialog, paste exactly:
- **Callback URL:** `https://eadmanager-fresh-2024-dev-f83e51d73e01.herokuapp.com/webhook/whatsapp`
- **Verify token:** `leadsmgr_wa_verify_7x2k9`
→ click **"Verify and save" (אימות ושמירה)**. Should succeed instantly (endpoint is live).
→ say "saved".

**A4.** Back on the page → **Webhook fields** → click **"Manage"**.
→ find the **`messages`** row → toggle **ON** (Subscribe).
→ say "subscribed".

**A4b. ⚠️ CRITICAL — subscribe the APP to the WABA itself.** This is separate from
A4 and easy to miss. Without it, Meta receives messages but has no app to deliver them
to — the webhook stays silent even though A1–A4 look correct. Run (assistant side):
```bash
TOKEN=$(heroku config:get META_WA_TOKEN -a eadmanager-fresh-2024-dev)
# should be non-empty {"data":[{...LeadMessaging...}]} after this:
curl -s -X POST "https://graph.facebook.com/v18.0/1702506717540173/subscribed_apps" -H "Authorization: Bearer $TOKEN"
curl -s -X GET  "https://graph.facebook.com/v18.0/1702506717540173/subscribed_apps" -H "Authorization: Bearer $TOKEN"
```
If GET returns `{"data":[]}` inbound will NOT work — re-run the POST.

**A5.** Test: on the phone, reply to the Hello World thread with any text.
Then I check the lead timeline (the assistant runs the curl/db check) — the message
should appear as a `whatsapp_message` activity, and a `new` lead flips to `contacted`.

---

## TASK B — Send a test message (verify token + plumbing)

Run from a terminal that can reach Heroku (assistant side):

```bash
TOKEN=$(heroku config:get META_WA_TOKEN -a eadmanager-fresh-2024-dev)
curl -s -X POST "https://graph.facebook.com/v18.0/1151422578047739/messages" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"messaging_product":"whatsapp","to":"972545932808","type":"template","template":{"name":"hello_world","language":{"code":"en_US"}}}'
```

`message_status: accepted` = success. Free-form text only works inside the 24h
customer-service window (after the customer messages first); otherwise use a template.

If you get `(#133010) Account not registered`, run the one-time register first:
```bash
curl -s -X POST "https://graph.facebook.com/v18.0/1151422578047739/register" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"messaging_product":"whatsapp","pin":"835291"}'
```

---

## TASK C — Add a recipient to the test list (free testing, max 5)

Test numbers can only message **pre-approved** recipients.

**C1.** Open dev console:
`https://developers.facebook.com/apps/837819029404196/whatsapp-business/wa-dev-console/`
**C2.** Under **"To"** → open dropdown → **"Manage phone number list"** / "Add phone number".
**C3.** Pick country **Israel (+972)**, type the mobile **without leading 0** (e.g. `54xxxxxxx`).
**C4.** A 6-digit code arrives on that phone via WhatsApp → enter it → verify.

---

## TASK D — Swap to the real business number (go-live)

When moving off the US test number:

**D1.** WhatsApp Manager → **Phone numbers (מספרי טלפון)** → **"Add phone number" (הוספת מספר טלפון)**.
**D2.** Enter the real Israeli business number → verify by SMS or voice call.
**D3.** Copy the **new Phone number ID**.
**D4.** Update Heroku: `heroku config:set -a eadmanager-fresh-2024-dev META_WA_PHONE_ID=<new_id>`
**D5.** Register it once with the PIN (TASK B register snippet, new phone ID).
**D6.** No webhook change needed — webhook is per-WABA, not per-number.
**D7.** Real numbers are NOT limited to 5 recipients, but outbound outside 24h still needs templates.

---

## TASK E — Renew / replace the access token

The current token is a **permanent system-user token** — it should NOT expire. If it ever
breaks (revoked, permissions changed):

**E1.** `https://business.facebook.com/settings/system-users?business_id=642825171414404`
**E2.** Click **LeadsManager API** (system user, Admin) → **"ליצור אסימון" (Generate token)**.
**E3.** App = **LeadMessaging**, expiry = **Never**, permissions = check all 3:
`whatsapp_business_messaging`, `whatsapp_business_management`, `whatsapp_business_manage_events`.
**E4.** Copy token (shown once). Update Heroku (אמיקם pastes, not the assistant):
`heroku config:set -a eadmanager-fresh-2024-dev META_WA_TOKEN="EAA..."`
**E5.** Verify: `curl -s "https://graph.facebook.com/v18.0/1702506717540173/phone_numbers" -H "Authorization: Bearer $TOKEN"`

Prereq for token generation: the system user must have an **app role** on LeadMessaging
(Business Settings → אפליקציות → LeadMessaging → "הקצאת אנשים" → add the system user)
AND the WhatsApp account assigned (system user → "הקצאת נכסים" → חשבונות WhatsApp).

---

## Troubleshooting

- **`Malformed access token`** → token has stray `<`, `>`, quotes, or a doubled `EAA` prefix.
  Re-set cleanly: starts with `EAA`, one unbroken string, inside double-quotes, no brackets.
- **Webhook GET 403** → verify token mismatch. Confirm `META_WA_VERIFY_TOKEN` == the token typed in Meta.
- **Webhook GET works, no inbound logged** → most common cause: APP NOT SUBSCRIBED TO WABA
  (TASK A4b — check `GET /{waba}/subscribed_apps` is non-empty). Other causes: `messages`
  field not subscribed (A4), or sender's phone doesn't match any lead (matched by last 9 digits).
- **Dev mode is NOT the blocker** for the test number — test-number inbound works in
  Development mode once A4b is done. (Live mode only needed for production numbers.)
- **Meta dashboard "This page is not available"** → known Meta flakiness. Try WhatsApp Manager
  surface instead of the dev console, or retry later.
- **`(#131030) recipient not in allowed list`** → add them via TASK C (test number only).
- **`(#133010) Account not registered`** → run the register snippet in TASK B.

## Quick health checks (assistant runs these)

```bash
# token shape (no secrets printed)
TOKEN=$(heroku config:get META_WA_TOKEN -a eadmanager-fresh-2024-dev); echo "len=${#TOKEN} starts=${TOKEN:0:3}"
# token valid + phone list
curl -s "https://graph.facebook.com/v18.0/1702506717540173/phone_numbers" -H "Authorization: Bearer $TOKEN"
# webhook verify handshake (should echo OK123)
curl -s "https://eadmanager-fresh-2024-dev-f83e51d73e01.herokuapp.com/webhook/whatsapp?hub.mode=subscribe&hub.verify_token=leadsmgr_wa_verify_7x2k9&hub.challenge=OK123"
```

# Google Sheets Auto-Sync Setup Guide

## Overview
This guide shows how to set up automatic lead import from Google Sheets (like campaign #1 "drushim_sheet" that's already working).

## How It Works
1. You add a new row to your Google Sheet
2. Zapier detects the new row
3. Zapier sends the data to your webhook
4. LeadsManager automatically creates a new lead

## Step-by-Step Setup

### Step 1: Prepare Your Google Sheet
Make sure your sheet has these columns (matching your Excel structure):
- **תאריך** (Date)
- **שם מלא** (Full Name)
- **מס פלאפון** (Phone)
- **מייל** (Email)
- **תאריך אירוע** (Event Date)
- **כמות אנשים** (Number of People)
- **מה היה בשיחה** (Call Notes)

### Step 2: Create Campaign in LeadsManager

1. Go to: https://eadmanager-fresh-2024-dev-f83e51d73e01.herokuapp.com/admin/campaigns
2. Click "➕ קמפיין חדש"
3. Fill in:
   - **לקוח**: Select "אלחנן תרבות לחם משמרות" (or your customer)
   - **שם קמפיין**: "אירועים ומסיבות" (or any name you want)
   - **Sheet ID**: `events_party_sheet` (important - remember this!)
   - **קישור ל-Sheet**: Paste your Google Sheet URL
   - **סטטוס**: פעיל
4. Click "צור קמפיין"

### Step 3: Create Zapier Integration

1. **Go to Zapier**: https://zapier.com/app/zaps
2. **Click "Create Zap"**

3. **Set up Trigger:**
   - App: **Google Sheets**
   - Event: **New Spreadsheet Row**
   - Click Continue
   - Connect your Google account
   - Select your spreadsheet and worksheet
   - Click Test trigger (should show a sample row)

4. **Set up Action:**
   - App: **Webhooks by Zapier**
   - Event: **POST**
   - Click Continue

5. **Configure Webhook:**
   - **URL**: `https://eadmanager-fresh-2024-dev-f83e51d73e01.herokuapp.com/webhook`
   - **Payload Type**: json
   - **Data** (map each field from your sheet):
     ```
     source: google_sheets
     sheet_id: events_party_sheet
     row_number: {{Row Number from Step 1}}
     name: {{שם מלא from Step 1}}
     phone: {{מס פלאפון from Step 1}}
     email: {{מייל from Step 1}}
     תאריך: {{תאריך from Step 1}}
     תאריך_אירוע: {{תאריך אירוע from Step 1}}
     כמות_אנשים: {{כמות אנשים from Step 1}}
     מה_היה_בשיחה: {{מה היה בשיחה from Step 1}}
     ```

   **CRITICAL NOTES:**
   - Use the **Data** field (not Value field) for each mapping
   - Make sure `sheet_id` exactly matches what you entered in Step 2
   - The `source: google_sheets` is required for proper processing

6. **Test the webhook:**
   - Click "Test & Continue"
   - Should see "200 OK" response
   - Check your leads in LeadsManager to confirm it arrived

7. **Turn on your Zap:**
   - Give it a name: "Events Party Leads - Auto Import"
   - Click "Publish"
   - **IMPORTANT**: Make sure Zap is ON (test mode doesn't send real data)

### Step 4: Verify It Works

1. Add a test row to your Google Sheet with sample data
2. Wait 1-2 minutes for Zapier to trigger
3. Check: https://eadmanager-fresh-2024-dev-f83e51d73e01.herokuapp.com/check-recent-webhooks
4. You should see your new lead in the system!

## Field Mapping to LeadsManager

Your Excel columns map to the LeadsManager database like this:

| Excel Column | LeadsManager Field | Storage Location |
|--------------|-------------------|------------------|
| תאריך | received_at | Main field |
| שם מלא | name | Main field |
| מס פלאפון | phone | Main field |
| מייל | email | Main field |
| תאריך אירוע | תאריך_אירוע | raw_data (JSONB) |
| כמות אנשים | כמות_אנשים | raw_data (JSONB) |
| מה היה בשיחה | notes | notes field |

## Troubleshooting

### Lead not appearing?
1. Check Zapier task history - did it trigger?
2. Check the webhook logs: `/check-recent-webhooks`
3. Make sure `sheet_id` in Zapier matches the campaign exactly
4. Verify Zap is Published (not just tested)

### Missing phone/email icons?
The system extracts these from your raw data. If icons are missing, use:
- Fix single lead: `/fix-lead/<id>`
- Fix all leads: `/admin/fix-phone-numbers`

### Wrong customer_id?
Edit the campaign in `/admin/campaigns` and select the correct customer.

## Example: Campaign #1 (drushim_sheet)

The existing working campaign uses:
- Customer: אלחנן תרבות לחם משמרות (ID: 1)
- Campaign Name: דרושים
- Sheet ID: drushim_sheet
- Type: google_sheets
- Status: Active

Your new campaign will work exactly the same way!

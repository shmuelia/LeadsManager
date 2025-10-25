# Google Sheets Automatic Lead Import Setup

## Overview
This guide shows how to automatically import leads from Google Sheets using Google Apps Script (used by campaign #1 "drushim_sheet").

## Debugging Existing Script (drushim_sheet)

Your script at: https://script.google.com/u/0/home/projects/1ZrSVIrlTtFR2iXZ30dADt8xqcn5kLB2y1-1zSKqggC1xhnFTyQeLppSi/executions

### Check 1: Verify Triggers are Active
1. Open your script project
2. Click the **clock icon** ⏰ (Triggers) on the left sidebar
3. Check if you see a trigger for `onEdit` or `onChange` or `onFormSubmit`
4. If no triggers exist, you need to recreate them (see setup below)

### Check 2: Check Recent Executions
1. In your script, click **Executions** (the icon you're already looking at)
2. Look for errors in recent executions
3. Common issues:
   - **Authorization error**: Script needs to be re-authorized
   - **Quota exceeded**: You hit Google's daily limit
   - **Webhook timeout**: Our server was slow/down
   - **Script disabled**: Trigger was accidentally deleted

### Check 3: Test Manually
1. In your script editor, select the function (probably `sendToWebhook` or `onEdit`)
2. Click **Run** ▶️
3. Check if it prompts for authorization
4. Look at the **Execution log** for errors

## Complete Google Apps Script Code

Here's the script that should be in your Google Sheet:

```javascript
// Configuration
const WEBHOOK_URL = 'https://eadmanager-fresh-2024-dev-f83e51d73e01.herokuapp.com/webhook';
const SHEET_ID = 'drushim_sheet'; // Change this for each campaign

// This function triggers when a form is submitted or row is edited
function onEdit(e) {
  // Only trigger for new rows (not edits to existing rows)
  const sheet = e.source.getActiveSheet();
  const row = e.range.getRow();

  // Skip header row
  if (row === 1) return;

  // Get the entire row data
  sendNewRowToWebhook(sheet, row);
}

// Alternative: This triggers only on form submissions (more reliable)
function onFormSubmit(e) {
  const sheet = e.range.getSheet();
  const row = e.range.getRow();
  sendNewRowToWebhook(sheet, row);
}

// Manual trigger function (for testing)
function sendLatestRowManually() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  const lastRow = sheet.getLastRow();
  sendNewRowToWebhook(sheet, lastRow);
}

// Main function that sends data to webhook
function sendNewRowToWebhook(sheet, rowNumber) {
  try {
    // Get headers from first row
    const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];

    // Get data from the specified row
    const rowData = sheet.getRange(rowNumber, 1, 1, sheet.getLastColumn()).getValues()[0];

    // Build the payload
    const payload = {
      source: 'google_sheets',
      sheet_id: SHEET_ID,
      row_number: rowNumber,
      timestamp: new Date().toISOString()
    };

    // Map headers to data
    for (let i = 0; i < headers.length; i++) {
      const header = headers[i];
      const value = rowData[i];

      if (header && value !== '') {
        // Map common Hebrew field names
        if (header === 'שם מלא' || header === 'שם') {
          payload.name = value;
        } else if (header === 'מס פלאפון' || header === 'טלפון' || header === 'מספר טלפון') {
          payload.phone = value;
        } else if (header === 'מייל' || header === 'אימייל' || header === 'דוא"ל') {
          payload.email = value;
        }

        // Also include the original field name
        payload[header] = value;
      }
    }

    // Log what we're sending (for debugging)
    Logger.log('Sending to webhook: ' + JSON.stringify(payload));

    // Send POST request to webhook
    const options = {
      method: 'post',
      contentType: 'application/json',
      payload: JSON.stringify(payload),
      muteHttpExceptions: true // Don't throw error on non-200 response
    };

    const response = UrlFetchApp.fetch(WEBHOOK_URL, options);
    const responseCode = response.getResponseCode();
    const responseBody = response.getContentText();

    Logger.log('Response Code: ' + responseCode);
    Logger.log('Response Body: ' + responseBody);

    if (responseCode === 200) {
      Logger.log('✅ Successfully sent row ' + rowNumber + ' to LeadsManager');

      // Optional: Mark the row as sent (add a column "Sent" with checkmark)
      // sheet.getRange(rowNumber, sheet.getLastColumn() + 1).setValue('✓');
    } else {
      Logger.log('❌ Error: Server returned ' + responseCode);
      Logger.log('Response: ' + responseBody);
    }

  } catch (error) {
    Logger.log('❌ Error sending to webhook: ' + error.toString());

    // Optional: Send email notification on error
    // MailApp.sendEmail('your-email@example.com', 'Webhook Error', error.toString());
  }
}

// Function to set up triggers (run this once)
function setupTriggers() {
  // Remove existing triggers first
  const triggers = ScriptApp.getProjectTriggers();
  triggers.forEach(trigger => ScriptApp.deleteTrigger(trigger));

  // Create new trigger for form submissions
  const sheet = SpreadsheetApp.getActiveSpreadsheet();
  ScriptApp.newTrigger('onFormSubmit')
    .forSpreadsheet(sheet)
    .onFormSubmit()
    .create();

  Logger.log('✅ Trigger created successfully!');
}
```

## Setup Instructions for New Sheet

### Step 1: Open Your Google Sheet
Open the sheet you want to sync (drushim or the new events/parties sheet)

### Step 2: Open Script Editor
1. Click **Extensions** → **Apps Script**
2. This opens the script editor

### Step 3: Paste the Script
1. Delete any existing code
2. Paste the complete script above
3. **IMPORTANT**: Change `SHEET_ID` to match your campaign:
   - For drushim: `const SHEET_ID = 'drushim_sheet';`
   - For events: `const SHEET_ID = 'events_party_sheet';`

### Step 4: Authorize the Script
1. Click **Run** ▶️ (select `sendLatestRowManually` function)
2. Google will ask for permissions
3. Click **Review Permissions** → **Advanced** → **Go to [Project Name] (unsafe)**
4. Grant permissions (needs access to sheets and external connections)

### Step 5: Set Up Trigger
1. Click the **clock icon** ⏰ (Triggers) on the left
2. Click **+ Add Trigger** (bottom right)
3. Configure:
   - Function: `onFormSubmit` (if using Google Form) OR `onEdit` (if adding rows manually)
   - Event source: `From spreadsheet`
   - Event type: `On form submit` OR `On edit`
4. Click **Save**

### Step 6: Test It
1. Add a new row to your sheet (or submit a form)
2. Check **Executions** to see if it ran successfully
3. Check LeadsManager: https://eadmanager-fresh-2024-dev-f83e51d73e01.herokuapp.com/check-recent-webhooks

## For Events/Parties Sheet

For your new events sheet, use this adjusted mapping:

```javascript
// In the sendNewRowToWebhook function, add these mappings:
if (header === 'תאריך') {
  payload.date = value;
} else if (header === 'תאריך אירוע') {
  payload.event_date = value;
  payload.תאריך_אירוע = value;
} else if (header === 'כמות אנשים') {
  payload.number_of_people = value;
  payload.כמות_אנשים = value;
} else if (header === 'מה היה בשיחה') {
  payload.call_notes = value;
  payload.notes = value;
}
```

## Troubleshooting

### Script Authorization Expired
**Symptom**: Executions show "Authorization required"
**Fix**: Run the script manually and re-authorize

### Trigger Deleted/Missing
**Symptom**: New rows don't trigger the script
**Fix**: Re-run `setupTriggers()` function

### Webhook Returns 500 Error
**Symptom**: Script runs but LeadsManager returns error
**Fix**:
1. Check if campaign exists in `/admin/campaigns`
2. Verify `sheet_id` matches exactly
3. Check database is accessible (Heroku may be sleeping)

### No Execution Logs
**Symptom**: Nothing appears in Executions
**Fix**: The trigger is not set up - follow Step 5 again

### Quota Exceeded
**Symptom**: "Service invoked too many times"
**Fix**: Google limits scripts to ~90 minutes of execution per day. You may need to:
- Reduce frequency of triggers
- Use time-based trigger instead of edit-based
- Upgrade to Google Workspace if needed

## Benefits of Google Apps Script

- ✅ **Free** - No subscription costs (within Google's quotas)
- ✅ **Instant** - Triggers immediately when rows are added
- ✅ **Direct** - No third-party service required
- ✅ **Customizable** - Full control over data mapping and logic
- ✅ **Reliable** - Runs directly in Google's infrastructure

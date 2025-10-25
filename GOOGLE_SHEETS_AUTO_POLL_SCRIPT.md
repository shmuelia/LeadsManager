# Google Sheets Auto-Polling Script (For Zapier-Updated Sheets)

## When to Use This Script

Use this version when:
- ✅ Rows are added by **Zapier** or other external services (not by human edits)
- ✅ You need to detect new rows automatically
- ✅ Normal `onEdit` triggers don't work (Zapier doesn't trigger them)

## How It Works

1. **Time-based trigger** runs every 5 minutes
2. **Checks all tabs** for new rows since last check
3. **Sends new leads** to your webhook automatically
4. **Tracks progress** using Script Properties (remembers last processed row per tab)

## Complete Auto-Polling Script

**Copy and paste this entire script into your Google Apps Script editor:**

```javascript
// Configuration
const WEBHOOK_URL = 'https://eadmanager-fresh-2024-dev-f83e51d73e01.herokuapp.com/webhook';
const SHEET_ID = 'drushim_sheet'; // Change this for each campaign

// Main function that runs every 5 minutes via time-based trigger
function checkForNewRows() {
  try {
    Logger.log('=== Starting automated check for new rows ===');

    const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
    const sheets = spreadsheet.getSheets();
    const scriptProperties = PropertiesService.getScriptProperties();

    let totalNewLeads = 0;

    // Check each tab/sheet for new rows
    sheets.forEach(sheet => {
      const sheetName = sheet.getName();
      const propertyKey = 'lastRow_' + sheetName;

      // Get the last processed row for this sheet (default to 1 if first run)
      const lastProcessedRow = parseInt(scriptProperties.getProperty(propertyKey)) || 1;
      const currentLastRow = sheet.getLastRow();

      Logger.log(`Sheet "${sheetName}": Last processed row = ${lastProcessedRow}, Current last row = ${currentLastRow}`);

      // If there are new rows
      if (currentLastRow > lastProcessedRow) {
        const newRowsCount = currentLastRow - lastProcessedRow;
        Logger.log(`Found ${newRowsCount} new row(s) in "${sheetName}"`);

        // Process each new row
        for (let row = lastProcessedRow + 1; row <= currentLastRow; row++) {
          // Skip header row
          if (row === 1) continue;

          Logger.log(`Processing row ${row} from "${sheetName}"...`);
          const success = sendNewRowToWebhook(sheet, row);

          if (success) {
            totalNewLeads++;
            // Update the last processed row after successful send
            scriptProperties.setProperty(propertyKey, row.toString());
          } else {
            // If sending failed, stop processing this sheet to retry next time
            Logger.log(`Failed to send row ${row}, will retry on next run`);
            break;
          }
        }
      } else {
        Logger.log(`No new rows in "${sheetName}"`);
      }
    });

    Logger.log(`=== Check complete. Sent ${totalNewLeads} new lead(s) ===`);

  } catch (error) {
    Logger.log('Error in checkForNewRows: ' + error.toString());
  }
}

// Function to send a single row to webhook
function sendNewRowToWebhook(sheet, rowNumber) {
  try {
    // Get the sheet/tab name (represents job title or category)
    const sheetName = sheet.getName();

    // Get headers from first row
    const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];

    // Get data from the specified row
    const rowData = sheet.getRange(rowNumber, 1, 1, sheet.getLastColumn()).getValues()[0];

    // Check if row is empty (all cells empty)
    const isEmpty = rowData.every(cell => cell === '' || cell === null || cell === undefined);
    if (isEmpty) {
      Logger.log(`Row ${rowNumber} is empty, skipping`);
      return true; // Return true so we mark it as processed
    }

    // Build the payload
    const payload = {
      source: 'google_sheets',
      sheet_id: SHEET_ID,
      sheet_name: sheetName,
      tab_name: sheetName,
      job_title: sheetName,
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

    Logger.log('Sending to webhook: ' + JSON.stringify(payload));

    // Send POST request to webhook
    const options = {
      method: 'post',
      contentType: 'application/json',
      payload: JSON.stringify(payload),
      muteHttpExceptions: true
    };

    const response = UrlFetchApp.fetch(WEBHOOK_URL, options);
    const responseCode = response.getResponseCode();
    const responseBody = response.getContentText();

    Logger.log('Response Code: ' + responseCode);
    Logger.log('Response Body: ' + responseBody);

    if (responseCode === 200) {
      Logger.log('✅ Successfully sent row ' + rowNumber + ' from tab "' + sheetName + '" to LeadsManager');
      return true;
    } else {
      Logger.log('❌ Error: Server returned ' + responseCode);
      Logger.log('Response: ' + responseBody);
      return false;
    }

  } catch (error) {
    Logger.log('❌ Error sending to webhook: ' + error.toString());
    return false;
  }
}

// Manual test function - processes latest row from active sheet
function sendLatestRowManually() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  const lastRow = sheet.getLastRow();
  Logger.log('Testing with latest row: ' + lastRow);
  sendNewRowToWebhook(sheet, lastRow);
}

// Manual test function - checks all sheets for new rows right now
function testCheckForNewRows() {
  checkForNewRows();
}

// Reset tracking (use if you need to reprocess all rows)
function resetLastProcessedRows() {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const sheets = spreadsheet.getSheets();
  const scriptProperties = PropertiesService.getScriptProperties();

  sheets.forEach(sheet => {
    const sheetName = sheet.getName();
    const propertyKey = 'lastRow_' + sheetName;
    scriptProperties.setProperty(propertyKey, '1'); // Reset to row 1
    Logger.log(`Reset "${sheetName}" to row 1`);
  });

  Logger.log('✅ All sheets reset. Next run will process all rows.');
}

// Initialize tracking to current last row (use when first setting up)
function initializeLastProcessedRows() {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const sheets = spreadsheet.getSheets();
  const scriptProperties = PropertiesService.getScriptProperties();

  sheets.forEach(sheet => {
    const sheetName = sheet.getName();
    const propertyKey = 'lastRow_' + sheetName;
    const currentLastRow = sheet.getLastRow();
    scriptProperties.setProperty(propertyKey, currentLastRow.toString());
    Logger.log(`Initialized "${sheetName}" to row ${currentLastRow} (will only process new rows from now on)`);
  });

  Logger.log('✅ Initialization complete. Only new rows added after this will be processed.');
}

// Set up the time-based trigger (run this once)
function setupTimeTrigger() {
  // First, remove any existing triggers for checkForNewRows
  const triggers = ScriptApp.getProjectTriggers();
  triggers.forEach(trigger => {
    if (trigger.getHandlerFunction() === 'checkForNewRows') {
      ScriptApp.deleteTrigger(trigger);
      Logger.log('Removed existing trigger');
    }
  });

  // Create new time-based trigger - runs every 5 minutes
  ScriptApp.newTrigger('checkForNewRows')
    .timeBased()
    .everyMinutes(5)
    .create();

  Logger.log('✅ Time-based trigger created! Will check for new rows every 5 minutes.');
  Logger.log('Note: First execution may take up to 5 minutes.');
}

// Remove the time-based trigger
function removeTimeTrigger() {
  const triggers = ScriptApp.getProjectTriggers();
  triggers.forEach(trigger => {
    if (trigger.getHandlerFunction() === 'checkForNewRows') {
      ScriptApp.deleteTrigger(trigger);
      Logger.log('Removed time-based trigger');
    }
  });
  Logger.log('✅ Time-based trigger removed.');
}
```

## Setup Instructions

### Step 1: Replace Your Existing Script

1. Open your script editor: https://script.google.com/u/0/home/projects/1ZrSVIrlTtFR2iXZ30dADt8xqcn5kLB2y1-1zSKqggC1xhnFTyQeLppSi
2. **Select all code** (Ctrl+A)
3. **Delete it**
4. **Paste the complete auto-polling script** above
5. **Save** (Ctrl+S)

### Step 2: Initialize Tracking

This tells the script which row to start from (so it doesn't reprocess old leads):

1. Select function: **`initializeLastProcessedRows`**
2. Click **Run** ▶️
3. Check the log - it will show the current last row for each tab
4. From now on, it will only process **new rows added after this point**

### Step 3: Delete Old Trigger

1. Click the **clock icon** ⏰ (Triggers)
2. Find the trigger for `onSheetEdit`
3. Click **3 dots** ⋮ → **Delete trigger**

### Step 4: Create Time-Based Trigger

1. In the script editor, select function: **`setupTimeTrigger`**
2. Click **Run** ▶️
3. Authorize if prompted
4. Check the log - should say "✅ Time-based trigger created!"

### Step 5: Verify Trigger is Active

1. Click the **clock icon** ⏰ (Triggers)
2. You should see:
   - **Function**: `checkForNewRows`
   - **Event source**: `Time-driven`
   - **Type**: `Minutes timer`
   - **Interval**: `Every 5 minutes`

### Step 6: Test It

**Option A - Manual test:**
1. Select function: **`testCheckForNewRows`**
2. Click **Run** ▶️
3. Check **Execution log** (View → Logs)
4. Should show how many new rows found (probably 0 if nothing new)

**Option B - Real test:**
1. Wait for your media supplier to add a new lead via Zapier
2. Within 5-10 minutes, check **Executions** page
3. You should see `checkForNewRows` executed
4. Check the log to see if the new lead was sent

## How to Monitor

### Check Recent Activity
Go to **Executions**: https://script.google.com/u/0/home/projects/1ZrSVIrlTtFR2iXZ30dADt8xqcn5kLB2y1-1zSKqggC1xhnFTyQeLppSi/executions

You'll see `checkForNewRows` running every 5 minutes:
- ✅ **Status: Completed** = Good (check logs to see if any new rows found)
- ❌ **Status: Failed** = Problem (click to see error)

### View Execution Logs
Click any execution → View the log to see:
- Which sheets were checked
- How many new rows found
- Whether they were sent successfully

## Useful Functions

### `testCheckForNewRows`
Run this manually anytime to check for new rows immediately (don't wait 5 minutes)

### `sendLatestRowManually`
Test sending the latest row from the currently active tab

### `resetLastProcessedRows`
⚠️ **Careful!** This resets tracking to row 1. Next run will try to send ALL rows (may create duplicates)

### `initializeLastProcessedRows`
Set tracking to current last row (only new rows after this will be processed)

### `removeTimeTrigger`
Stops the automatic checking (useful if you need to pause temporarily)

## Troubleshooting

### No new rows detected but you know they were added
- Check the **Executions** log for details
- The script might have already processed them
- Run `testCheckForNewRows` manually to see current state

### Script keeps re-sending old rows
- Run `initializeLastProcessedRows` to reset to current position

### Script stopped running
- Check **Triggers** page - is the trigger still there?
- Check **Executions** - any authorization errors?
- Script may have been disabled due to errors (re-run `setupTimeTrigger`)

### "Authorization required" error
- Run any function manually (click Run)
- Grant permissions again

## Benefits of Auto-Polling

✅ **Works with Zapier** - Detects rows added by external services
✅ **Reliable** - Checks every 5 minutes, won't miss leads
✅ **Multi-tab support** - Monitors all tabs automatically
✅ **Resume-friendly** - If it fails, it retries from last successful row
✅ **No duplicates** - Tracks progress per tab to avoid re-sending

## Limitations

⏱️ **5-minute delay** - New leads take up to 5 minutes to arrive (vs instant with direct webhook)
📊 **Quota limits** - Google limits script execution time (should be fine for normal use)

---

## Next Steps After Setup

1. ✅ Initialize tracking (`initializeLastProcessedRows`)
2. ✅ Set up time trigger (`setupTimeTrigger`)
3. ✅ Wait for next lead from media supplier
4. ✅ Check Executions after 5-10 minutes
5. ✅ Verify lead appears in LeadsManager

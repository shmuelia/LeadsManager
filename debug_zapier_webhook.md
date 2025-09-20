# Debugging Zapier Webhook Phone Issue

## What We've Done

1. **Added comprehensive logging** to the webhook endpoint to see exactly what Zapier sends
2. **Fixed phone extraction** to include "Phone Number" field (with capital P and N)
3. **Added "Phone Number" to standard fields** so it's not converted to a custom field

## Next Steps to Debug

### 1. Send a Test Lead from Zapier

Trigger a new lead from your Zapier integration (either test or live).

### 2. Check Heroku Logs

If you have Heroku CLI installed:
```bash
heroku logs --tail --app eadmanager-fresh-2024-dev | grep -E "(WEBHOOK|phone|Phone)"
```

Or view in browser:
1. Go to: https://dashboard.heroku.com/apps/eadmanager-fresh-2024-dev
2. Click on "More" → "View logs"

### 3. Look for These Log Messages

You should see logs like:
```
=== WEBHOOK DATA RECEIVED ===
Total fields: X
Field names: [list of fields]
Found phone field 'Phone Number': +972509476212
All phone-related fields: ['Phone Number']
Extracted values - Name: Ohad Levi, Email: Lxdohad@gmail.com, Phone: +972509476212
About to save lead: name='Ohad Levi', email='Lxdohad@gmail.com', phone='+972509476212'
Lead saved to database: Ohad Levi (Lxdohad@gmail.com) - ID: XXX
```

### 4. What to Check

- **Does Zapier send "Phone Number" or a different field name?**
- **Is the phone value present in the logs?**
- **Is the phone value being extracted correctly?**
- **Is the phone value being saved to database?**

## Common Issues and Solutions

### Issue: Phone field name mismatch
**Solution**: Check what field name Zapier actually sends and add it to the extraction logic

### Issue: Phone is nested in another field
**Solution**: May need to parse nested JSON structure

### Issue: Phone is being converted to custom field
**Solution**: Already fixed by adding "Phone Number" to standard fields list

## Manual Fix for Existing Leads

Visit this URL to fix all existing leads with phone in raw_data:
```
https://eadmanager-fresh-2024-dev-f83e51d73e01.herokuapp.com/admin/fix-phone-numbers
```
(Must be logged in as admin)

## Test the Webhook Manually

You can test with curl to verify the webhook works:
```bash
curl -X POST "https://eadmanager-fresh-2024-dev-f83e51d73e01.herokuapp.com/webhook" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test User",
    "email": "test@example.com",
    "Phone Number": "+972501234567",
    "campaign_name": "Test Campaign"
  }'
```

This should return:
```json
{"database_saved":true,"lead_id":XXX,"message":"Lead processed successfully","status":"success"}
```

And the lead should have phone icons when viewed.
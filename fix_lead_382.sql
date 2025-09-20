-- Fix phone number for lead #382 and any other leads with phone in raw_data
-- This script extracts phone numbers from raw_data JSON and updates the main phone field

-- First, check what we're about to fix
SELECT id, name, phone,
       raw_data->>'Phone Number' as phone_from_raw,
       raw_data->>'Full Name' as full_name,
       raw_data->>'Email' as email_from_raw
FROM leads
WHERE id = 382;

-- Update lead #382 specifically
UPDATE leads
SET phone = raw_data->>'Phone Number'
WHERE id = 382
  AND (phone IS NULL OR phone = '')
  AND raw_data->>'Phone Number' IS NOT NULL;

-- Fix all leads that have Phone Number in raw_data but not in main phone field
UPDATE leads
SET phone = raw_data->>'Phone Number'
WHERE (phone IS NULL OR phone = '')
  AND raw_data->>'Phone Number' IS NOT NULL
  AND raw_data->>'Phone Number' != '';

-- Alternative: Check for other phone field variations
UPDATE leads
SET phone = COALESCE(
    raw_data->>'Phone Number',
    raw_data->>'phone',
    raw_data->>'phone_number',
    raw_data->>'טלפון',
    raw_data->>'מספר טלפון',
    raw_data->>'Raw מספר טלפון'
)
WHERE (phone IS NULL OR phone = '')
  AND (
    raw_data->>'Phone Number' IS NOT NULL OR
    raw_data->>'phone' IS NOT NULL OR
    raw_data->>'phone_number' IS NOT NULL OR
    raw_data->>'טלפון' IS NOT NULL OR
    raw_data->>'מספר טלפון' IS NOT NULL OR
    raw_data->>'Raw מספר טלפון' IS NOT NULL
  );

-- Verify the fix
SELECT id, name, phone,
       raw_data->>'Phone Number' as phone_from_raw,
       CASE
         WHEN phone IS NOT NULL AND phone != '' THEN 'Fixed'
         ELSE 'Not Fixed'
       END as status
FROM leads
WHERE id = 382;
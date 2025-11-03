-- Check for duplicate leads by normalized phone (removing spaces and dashes)
SELECT
    REPLACE(REPLACE(phone, '-', ''), ' ', '') as normalized_phone,
    COUNT(*) as count,
    array_agg(id ORDER BY received_at ASC) as lead_ids,
    array_agg(phone) as phone_formats
FROM leads
WHERE phone IS NOT NULL AND phone != ''
GROUP BY REPLACE(REPLACE(phone, '-', ''), ' ', ''), customer_id
HAVING COUNT(*) > 1
ORDER BY count DESC;

-- Check for duplicate leads by email
SELECT
    email,
    COUNT(*) as count,
    array_agg(id ORDER BY received_at ASC) as lead_ids
FROM leads
WHERE email IS NOT NULL AND email != ''
GROUP BY email, customer_id
HAVING COUNT(*) > 1
ORDER BY count DESC;

-- Count total duplicates
SELECT
    'Total potential phone duplicates' as type,
    COUNT(*) as duplicate_groups
FROM (
    SELECT REPLACE(REPLACE(phone, '-', ''), ' ', '') as normalized_phone
    FROM leads
    WHERE phone IS NOT NULL AND phone != ''
    GROUP BY REPLACE(REPLACE(phone, '-', ''), ' ', ''), customer_id
    HAVING COUNT(*) > 1
) sub;

#!/usr/bin/env python3
"""
One-time script to find row number for lead 595 (Hania Masarwe) in Google Sheet
"""

import os
import requests
import csv
import psycopg2
import json
from io import StringIO

# Sheet URL for "קמפיין לידים - דרושים - 02.07.25"
SHEET_URL = "https://docs.google.com/spreadsheets/d/1lsUyiuflqFV9qU2FEFoR0PGUJDRrBx9Qpv_Xe7Ag4iA/edit?gid=2095877733"

# Lead details to search for
LEAD_ID = 595
SEARCH_EMAIL = "heniahmdan10@gmail.com"
SEARCH_PHONE = "+972549210117"
SEARCH_NAME = "Hania Masarwe"

def clean_phone(phone):
    """Clean phone number for comparison"""
    if not phone:
        return ''
    return str(phone).strip().replace('-', '').replace(' ', '').replace('+972', '0').replace('972', '0')

def clean_email(email):
    """Clean email for comparison"""
    if not email:
        return ''
    return email.strip().lower().rstrip('.')

# Extract spreadsheet ID and gid
spreadsheet_id = "1lsUyiuflqFV9qU2FEFoR0PGUJDRrBx9Qpv_Xe7Ag4iA"
gid = "2095877733"

# Build CSV export URL
csv_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv&gid={gid}"

print(f"Fetching Google Sheet...")
response = requests.get(csv_url, timeout=30)
response.raise_for_status()
response.encoding = 'utf-8'

reader = csv.DictReader(StringIO(response.text))

# Clean search values
search_email_clean = clean_email(SEARCH_EMAIL)
search_phone_clean = clean_phone(SEARCH_PHONE)
search_name_clean = SEARCH_NAME.strip().lower()

print(f"\nSearching for:")
print(f"  Name: {SEARCH_NAME}")
print(f"  Email: {SEARCH_EMAIL}")
print(f"  Phone: {SEARCH_PHONE}")
print()

found_row = None
current_row = 1  # Header is row 1

for row_data in reader:
    current_row += 1

    # Skip empty rows
    if not any(row_data.values()):
        continue

    # Extract email and phone from row
    row_email = None
    row_phone = None
    row_name = None

    for col, value in row_data.items():
        col_lower = col.lower()

        if 'email' in col_lower or 'מייל' in col_lower or 'אימייל' in col_lower:
            row_email = clean_email(value) if value else None

        if 'phone' in col_lower or 'טלפון' in col_lower or 'פלאפון' in col_lower:
            row_phone = clean_phone(value) if value else None

        if 'name' in col_lower or 'שם' in col_lower:
            row_name = value.strip().lower() if value else None

    # Check if this row matches
    email_match = row_email and row_email == search_email_clean
    phone_match = row_phone and row_phone == search_phone_clean
    name_match = row_name and search_name_clean in row_name

    if email_match or phone_match or name_match:
        print(f"✓ FOUND at row {current_row}!")
        print(f"  Match by: ", end="")
        matches = []
        if email_match:
            matches.append(f"email ({row_email})")
        if phone_match:
            matches.append(f"phone ({row_phone})")
        if name_match:
            matches.append(f"name ({row_name})")
        print(", ".join(matches))

        found_row = current_row
        break

if found_row:
    print(f"\n{'='*60}")
    print(f"Lead found at row {found_row}")
    print(f"{'='*60}")

    # Get database connection
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        print("\nERROR: DATABASE_URL not set")
        print("Run this SQL manually in pgAdmin:")
        print(f"""
UPDATE leads
SET raw_data = jsonb_set(
    COALESCE(raw_data, '{{}}'::jsonb),
    '{{row_number}}',
    '"{found_row}"'::jsonb
)
WHERE id = {LEAD_ID};

UPDATE leads
SET raw_data = jsonb_set(
    raw_data,
    '{{sheet_url}}',
    '"{SHEET_URL}"'::jsonb
)
WHERE id = {LEAD_ID};
        """)
    else:
        # Update database
        if database_url.startswith('postgres://'):
            database_url = database_url.replace('postgres://', 'postgresql://', 1)

        conn = psycopg2.connect(database_url, sslmode='require')
        cur = conn.cursor()

        # Get current raw_data
        cur.execute("SELECT raw_data FROM leads WHERE id = %s", (LEAD_ID,))
        result = cur.fetchone()

        if result:
            raw_data = result[0] if result[0] else {}
            if isinstance(raw_data, str):
                raw_data = json.loads(raw_data)

            # Add row_number and sheet_url
            raw_data['row_number'] = found_row
            raw_data['sheet_url'] = SHEET_URL

            # Update database
            cur.execute("""
                UPDATE leads
                SET raw_data = %s
                WHERE id = %s
            """, (json.dumps(raw_data), LEAD_ID))

            conn.commit()
            cur.close()
            conn.close()

            print(f"\n✅ Database updated successfully!")
            print(f"   Lead {LEAD_ID} now has row_number = {found_row}")
        else:
            print(f"\nERROR: Lead {LEAD_ID} not found in database")
else:
    print(f"\n❌ Lead not found in Google Sheet")
    print(f"   Searched {current_row} rows")

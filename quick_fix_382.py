#!/usr/bin/env python
"""
Quick script to fix lead #382's phone number by running directly on Heroku
Run this with: heroku run python quick_fix_382.py -a eadmanager-fresh-2024-dev
"""
import os
import psycopg2
import psycopg2.extras
from urllib.parse import urlparse
import json

DATABASE_URL = os.environ.get('DATABASE_URL')

def fix_lead_382():
    """Fix phone number for lead #382 specifically"""
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL not set")
        return False

    parsed_url = urlparse(DATABASE_URL)
    conn = psycopg2.connect(
        database=parsed_url.path[1:],
        user=parsed_url.username,
        password=parsed_url.password,
        host=parsed_url.hostname,
        port=parsed_url.port
    )

    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        # First check current state
        cur.execute("""
            SELECT id, name, phone, raw_data
            FROM leads
            WHERE id = 382
        """)
        lead = cur.fetchone()

        if not lead:
            print("Lead #382 not found!")
            return False

        print(f"Lead #382 - {lead['name']}")
        print(f"Current phone field: {lead['phone']}")

        raw_data = lead['raw_data']
        if isinstance(raw_data, str):
            raw_data = json.loads(raw_data)

        phone_in_raw = raw_data.get('Phone Number')
        print(f"Phone in raw_data: {phone_in_raw}")

        if not lead['phone'] and phone_in_raw:
            # Update the phone field
            cur.execute("""
                UPDATE leads
                SET phone = %s
                WHERE id = 382
            """, (phone_in_raw,))

            conn.commit()
            print(f"✓ Updated phone to: {phone_in_raw}")

            # Verify the update
            cur.execute("SELECT phone FROM leads WHERE id = 382")
            updated = cur.fetchone()
            print(f"✓ Verification - Phone is now: {updated['phone']}")
            return True
        elif lead['phone']:
            print(f"Phone already set to: {lead['phone']}")
            return True
        else:
            print("No phone number found in raw_data")
            return False

    except Exception as e:
        print(f"ERROR: {e}")
        conn.rollback()
        return False
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    success = fix_lead_382()
    exit(0 if success else 1)
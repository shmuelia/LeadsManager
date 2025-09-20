"""
Script to fix phone numbers for existing leads where phone is in raw_data but not in main phone field
This addresses leads that were imported before the 'Phone Number' field was added to the extraction logic
"""
import os
import psycopg2
import psycopg2.extras
import json
from urllib.parse import urlparse
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Get DATABASE_URL from environment
DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    print("ERROR: DATABASE_URL environment variable not set")
    print("Please set it using: export DATABASE_URL='your_database_url'")
    exit(1)

def get_db_connection():
    """Create database connection"""
    parsed_url = urlparse(DATABASE_URL)

    conn = psycopg2.connect(
        database=parsed_url.path[1:],
        user=parsed_url.username,
        password=parsed_url.password,
        host=parsed_url.hostname,
        port=parsed_url.port
    )
    return conn

def fix_phone_numbers():
    """Update phone field for leads that have phone in raw_data but not in main phone field"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        # Find leads with empty phone field but phone data in raw_data
        cur.execute("""
            SELECT id, name, phone, raw_data
            FROM leads
            WHERE (phone IS NULL OR phone = '')
            AND raw_data IS NOT NULL
        """)

        leads_to_fix = cur.fetchall()
        logger.info(f"Found {len(leads_to_fix)} leads to check")

        fixed_count = 0
        for lead in leads_to_fix:
            raw_data = lead['raw_data']
            if not raw_data:
                continue

            # Parse raw_data if it's a string
            if isinstance(raw_data, str):
                try:
                    raw_data = json.loads(raw_data)
                except:
                    continue

            # Look for phone number in various fields
            phone = None
            phone_fields = ['Phone Number', 'phone', 'phone_number', 'טלפון', 'מספר טלפון', 'Raw מספר טלפון']

            for field in phone_fields:
                if field in raw_data and raw_data[field]:
                    phone = raw_data[field]
                    break

            if phone:
                # Update the lead with the phone number
                cur.execute("""
                    UPDATE leads
                    SET phone = %s
                    WHERE id = %s
                """, (phone, lead['id']))

                logger.info(f"Fixed lead #{lead['id']} - {lead['name']}: {phone}")
                fixed_count += 1

        # Commit the changes
        conn.commit()
        logger.info(f"Successfully fixed {fixed_count} leads")

        # Show specific info for lead #382
        cur.execute("""
            SELECT id, name, phone, email, raw_data->>'Phone Number' as raw_phone
            FROM leads
            WHERE id = 382
        """)
        lead_382 = cur.fetchone()
        if lead_382:
            logger.info(f"\nLead #382 status:")
            logger.info(f"  Name: {lead_382['name']}")
            logger.info(f"  Phone field: {lead_382['phone']}")
            logger.info(f"  Raw phone: {lead_382['raw_phone']}")

    except Exception as e:
        logger.error(f"Error fixing phone numbers: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    fix_phone_numbers()
#!/usr/bin/env python3
"""
Script to find and update row numbers for leads by scanning Google Sheets
For each row in each sheet, finds the matching lead in DB and updates row_number + sheet_url
"""

import os
import sys
import logging
import psycopg2
import psycopg2.extras
import requests
import csv
import json
import re
from io import StringIO

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def get_db_connection():
    """Get database connection"""
    try:
        database_url = os.environ.get('DATABASE_URL')
        if not database_url:
            logger.error('DATABASE_URL not set')
            return None

        # Heroku PostgreSQL URLs start with postgres:// but psycopg2 needs postgresql://
        if database_url.startswith('postgres://'):
            database_url = database_url.replace('postgres://', 'postgresql://', 1)

        conn = psycopg2.connect(database_url, sslmode='require')
        return conn
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return None

def clean_phone(phone):
    """Clean phone number for comparison"""
    if not phone:
        return ''
    return str(phone).strip().replace('-', '').replace(' ', '').replace('+972', '0').replace('972', '0')

def clean_email(email):
    """Clean email for comparison - remove trailing dots and extra whitespace"""
    if not email:
        return ''
    # Strip whitespace, convert to lowercase, remove trailing dots
    cleaned = email.strip().lower().rstrip('.')
    return cleaned

def find_row_numbers_for_campaign(campaign):
    """Scan Google Sheet and update row numbers for matching leads in DB"""
    try:
        conn = get_db_connection()
        if not conn:
            return {'success': False, 'error': 'Database connection failed'}

        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Get campaign details
        cur.execute("""
            SELECT c.*, cu.name as customer_name
            FROM campaigns c
            JOIN customers cu ON c.customer_id = cu.id
            WHERE c.id = %s
        """, (campaign['id'],))

        campaign_full = cur.fetchone()
        if not campaign_full:
            cur.close()
            conn.close()
            return {'success': False, 'error': 'Campaign not found'}

        sheet_url = campaign_full['sheet_url']
        if not sheet_url:
            cur.close()
            conn.close()
            return {'success': False, 'error': 'No sheet URL'}

        logger.info(f"Processing campaign: {campaign['campaign_name']}")
        logger.info(f"Sheet URL: {sheet_url}")

        # Extract spreadsheet ID and gid from URL
        sheet_id_match = re.search(r'/d/([a-zA-Z0-9-_]+)', sheet_url)
        if not sheet_id_match:
            cur.close()
            conn.close()
            return {'success': False, 'error': 'Invalid sheet URL'}

        spreadsheet_id = sheet_id_match.group(1)
        gid_match = re.search(r'gid=(\d+)', sheet_url)
        gid = gid_match.group(1) if gid_match else '0'

        # Convert sheet URL to CSV export URL
        csv_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv&gid={gid}"

        # Fetch CSV data
        logger.info(f"Fetching sheet data...")
        response = requests.get(csv_url, timeout=30)
        response.raise_for_status()
        response.encoding = 'utf-8'

        reader = csv.DictReader(StringIO(response.text))

        updated = 0
        not_found = 0
        skipped = 0
        current_row = 1  # Start at row 1 (header is row 0 in sheets, row 1 in our counting)

        # Iterate through each row in the sheet
        for row_data in reader:
            current_row += 1

            # Skip empty rows
            if not any(row_data.values()):
                continue

            try:
                # Extract email, phone, and name from row using common column names
                row_email = None
                row_phone = None
                row_name = None

                # Look for email in common columns
                for col in row_data.keys():
                    col_lower = col.lower()
                    if 'email' in col_lower or 'מייל' in col_lower or 'אימייל' in col_lower or 'דוא' in col_lower:
                        row_email = clean_email(row_data[col]) if row_data[col] else None
                        if row_email:
                            break

                # Look for phone in common columns
                for col in row_data.keys():
                    col_lower = col.lower()
                    if 'phone' in col_lower or 'טלפון' in col_lower or 'פלאפון' in col_lower:
                        row_phone = clean_phone(row_data[col]) if row_data[col] else None
                        if row_phone:
                            break

                # Look for name in common columns
                for col in row_data.keys():
                    col_lower = col.lower()
                    if 'name' in col_lower or 'שם' in col_lower:
                        row_name = row_data[col].strip() if row_data[col] else None
                        if row_name:
                            break

                # Skip if no identifying information
                if not row_email and not row_phone and not row_name:
                    continue

                # Search for matching lead in database
                # Try multiple strategies in order of reliability
                matched_lead = None
                match_method = None

                # Strategy 1: Match by email (most reliable)
                if row_email:
                    cur.execute("""
                        SELECT id, name, email, phone, campaign_name, raw_data
                        FROM leads
                        WHERE customer_id = %s
                        AND LOWER(TRIM(TRAILING '.' FROM email)) = %s
                        LIMIT 1
                    """, (campaign_full['customer_id'], row_email))

                    result = cur.fetchone()
                    if result:
                        matched_lead = result
                        match_method = 'email'

                # Strategy 2: Match by phone (reliable)
                if not matched_lead and row_phone:
                    # Clean the phone in the query too
                    cur.execute("""
                        SELECT id, name, email, phone, campaign_name, raw_data
                        FROM leads
                        WHERE customer_id = %s
                        AND REPLACE(REPLACE(REPLACE(REPLACE(phone, '-', ''), ' ', ''), '+972', '0'), '972', '0') = %s
                        LIMIT 1
                    """, (campaign_full['customer_id'], row_phone))

                    result = cur.fetchone()
                    if result:
                        matched_lead = result
                        match_method = 'phone'

                # Strategy 3: Match by name + email (strong match)
                if not matched_lead and row_name and row_email:
                    cur.execute("""
                        SELECT id, name, email, phone, campaign_name, raw_data
                        FROM leads
                        WHERE customer_id = %s
                        AND LOWER(name) = LOWER(%s)
                        AND LOWER(TRIM(TRAILING '.' FROM email)) = %s
                        LIMIT 1
                    """, (campaign_full['customer_id'], row_name, row_email))

                    result = cur.fetchone()
                    if result:
                        matched_lead = result
                        match_method = 'name+email'

                # Strategy 4: Match by name + phone (strong match)
                if not matched_lead and row_name and row_phone:
                    cur.execute("""
                        SELECT id, name, email, phone, campaign_name, raw_data
                        FROM leads
                        WHERE customer_id = %s
                        AND LOWER(name) = LOWER(%s)
                        AND REPLACE(REPLACE(REPLACE(REPLACE(phone, '-', ''), ' ', ''), '+972', '0'), '972', '0') = %s
                        LIMIT 1
                    """, (campaign_full['customer_id'], row_name, row_phone))

                    result = cur.fetchone()
                    if result:
                        matched_lead = result
                        match_method = 'name+phone'

                if matched_lead:
                    # Check if this lead already has a row_number for THIS SPECIFIC sheet
                    raw_data = matched_lead['raw_data'] if matched_lead['raw_data'] else {}
                    if isinstance(raw_data, str):
                        raw_data = json.loads(raw_data)

                    existing_row = raw_data.get('row_number')
                    existing_sheet = raw_data.get('sheet_url')

                    # Skip if already has row_number for this exact sheet
                    if existing_row and existing_sheet == sheet_url:
                        skipped += 1
                        logger.info(f"  Row {current_row}: Skipped '{matched_lead['name']}' - already has row {existing_row} for this sheet")
                        continue

                    # Update raw_data with row_number and sheet_url
                    raw_data['row_number'] = current_row
                    raw_data['sheet_url'] = sheet_url
                    raw_data['sheet_id'] = campaign_full.get('sheet_id', '')

                    # Mark source as google_sheets if not already set
                    if 'source' not in raw_data:
                        raw_data['source'] = 'google_sheets'

                    # Update the lead
                    cur.execute("""
                        UPDATE leads
                        SET raw_data = %s
                        WHERE id = %s
                    """, (json.dumps(raw_data), matched_lead['id']))

                    updated += 1
                    logger.info(f"  Row {current_row}: ✓ Updated '{matched_lead['name']}' (campaign: {matched_lead['campaign_name']}, matched by: {match_method})")
                else:
                    not_found += 1
                    logger.debug(f"  Row {current_row}: ✗ Not found - name: {row_name}, email: {row_email}, phone: {row_phone}")

            except Exception as e:
                logger.error(f"Error processing row {current_row}: {e}")
                continue

        conn.commit()
        cur.close()
        conn.close()

        logger.info(f"Campaign {campaign['campaign_name']}: {updated} updated, {skipped} skipped, {not_found} not found")

        return {
            'success': True,
            'campaign_name': campaign['campaign_name'],
            'updated': updated,
            'skipped': skipped,
            'not_found': not_found
        }

    except Exception as e:
        logger.error(f"Error finding rows for campaign {campaign.get('campaign_name', campaign.get('id'))}: {e}")
        return {
            'success': False,
            'campaign_name': campaign.get('campaign_name', campaign.get('id')),
            'error': str(e)
        }

def main():
    """Main function"""
    logger.info("=== Find Missing Row Numbers Started ===")

    try:
        conn = get_db_connection()
        if not conn:
            logger.error("Failed to connect to database")
            sys.exit(1)

        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Get all campaigns with sheet URLs (including non-active)
        cur.execute("""
            SELECT id, campaign_name, sheet_url
            FROM campaigns
            WHERE sheet_url IS NOT NULL
            AND sheet_url != ''
            ORDER BY id
        """)

        campaigns = cur.fetchall()
        cur.close()
        conn.close()

        if not campaigns:
            logger.info("No campaigns found")
            return

        logger.info(f"Found {len(campaigns)} campaigns to check")

        # Process each campaign
        total_updated = 0
        total_skipped = 0
        total_not_found = 0

        for campaign in campaigns:
            result = find_row_numbers_for_campaign(campaign)

            if result['success']:
                total_updated += result.get('updated', 0)
                total_skipped += result.get('skipped', 0)
                total_not_found += result.get('not_found', 0)

        logger.info("=== Process Completed ===")
        logger.info(f"Total: {total_updated} leads updated, {total_skipped} skipped (already had row), {total_not_found} not found in DB")

    except Exception as e:
        logger.error(f"Process failed: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()

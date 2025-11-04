#!/usr/bin/env python3
"""
Script to find row numbers for leads by searching Google Sheets using email or phone
This handles leads that were imported before row_number tracking was added
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
    """Find row numbers for leads missing them in a specific campaign"""
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

        # Get leads for this campaign that are missing row_number
        cur.execute("""
            SELECT id, name, email, phone, raw_data
            FROM leads
            WHERE customer_id = %s
            AND campaign_name = %s
            AND (raw_data->>'row_number' IS NULL OR raw_data->>'sheet_url' IS NULL)
        """, (campaign_full['customer_id'], campaign_full['campaign_name']))

        leads_without_rows = cur.fetchall()

        if not leads_without_rows:
            logger.info(f"Campaign {campaign['campaign_name']}: All leads have row numbers")
            cur.close()
            conn.close()
            return {'success': True, 'updated': 0, 'not_found': 0}

        logger.info(f"Campaign {campaign['campaign_name']}: Found {len(leads_without_rows)} leads without row numbers")

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
        response = requests.get(csv_url, timeout=30)
        response.raise_for_status()
        response.encoding = 'utf-8'

        reader = csv.DictReader(StringIO(response.text))

        updated = 0
        not_found = 0
        current_row = 1  # Start at row 1 (header is row 0 in sheets, row 1 in our counting)

        # Create lookup dictionaries for faster matching
        leads_by_email = {}
        leads_by_phone = {}
        leads_by_name = {}

        for lead in leads_without_rows:
            if lead['email']:
                cleaned_email = clean_email(lead['email'])
                if cleaned_email:
                    leads_by_email[cleaned_email] = lead
            if lead['phone']:
                clean_phone_num = clean_phone(lead['phone'])
                if clean_phone_num:
                    leads_by_phone[clean_phone_num] = lead
            if lead['name']:
                # Store by normalized name (lowercase, stripped) for fallback matching
                normalized_name = lead['name'].strip().lower()
                if normalized_name:
                    leads_by_name[normalized_name] = lead

        logger.info(f"Searching sheet for {len(leads_by_email)} emails, {len(leads_by_phone)} phones, {len(leads_by_name)} names")

        # Search through sheet rows
        for row_data in reader:
            current_row += 1

            # Skip empty rows
            if not any(row_data.values()):
                continue

            try:
                # Try to extract email, phone, and name from row using common column names
                row_email = None
                row_phone = None
                row_name = None

                # Look for email in common columns
                for col in row_data.keys():
                    col_lower = col.lower()
                    if 'email' in col_lower or 'מייל' in col_lower or 'אימייל' in col_lower or 'דוא' in col_lower:
                        row_email = clean_email(row_data[col]) if row_data[col] else None
                        break

                # Look for phone in common columns
                for col in row_data.keys():
                    col_lower = col.lower()
                    if 'phone' in col_lower or 'טלפון' in col_lower or 'פלאפון' in col_lower:
                        row_phone = clean_phone(row_data[col]) if row_data[col] else None
                        break

                # Look for name in common columns
                for col in row_data.keys():
                    col_lower = col.lower()
                    if 'name' in col_lower or 'שם' in col_lower:
                        row_name = row_data[col].strip().lower() if row_data[col] else None
                        break

                # Try to match by email, phone, or name (in priority order)
                matched_lead = None
                match_method = None

                if row_email and row_email in leads_by_email:
                    matched_lead = leads_by_email[row_email]
                    match_method = 'email'
                elif row_phone and row_phone in leads_by_phone:
                    matched_lead = leads_by_phone[row_phone]
                    match_method = 'phone'
                elif row_name and row_name in leads_by_name:
                    matched_lead = leads_by_name[row_name]
                    match_method = 'name'

                if matched_lead:
                    # Update raw_data with row_number and sheet_url
                    raw_data = matched_lead['raw_data'] if matched_lead['raw_data'] else {}
                    if isinstance(raw_data, str):
                        raw_data = json.loads(raw_data)

                    raw_data['row_number'] = current_row
                    raw_data['sheet_url'] = sheet_url
                    raw_data['sheet_id'] = campaign_full.get('sheet_id', '')

                    cur.execute("""
                        UPDATE leads
                        SET raw_data = %s
                        WHERE id = %s
                    """, (json.dumps(raw_data), matched_lead['id']))

                    updated += 1
                    logger.info(f"✓ Found lead '{matched_lead['name']}' at row {current_row} (matched by {match_method})")

                    # Remove from lookup to avoid duplicate matches
                    if row_email and row_email in leads_by_email:
                        del leads_by_email[row_email]
                    if row_phone and row_phone in leads_by_phone:
                        del leads_by_phone[row_phone]
                    if row_name and row_name in leads_by_name:
                        del leads_by_name[row_name]

            except Exception as e:
                logger.error(f"Error processing row {current_row}: {e}")
                continue

        # Count leads that weren't found (avoid double counting - a lead might be in multiple dicts)
        remaining_lead_ids = set()
        for lead in leads_by_email.values():
            remaining_lead_ids.add(lead['id'])
        for lead in leads_by_phone.values():
            remaining_lead_ids.add(lead['id'])
        for lead in leads_by_name.values():
            remaining_lead_ids.add(lead['id'])
        not_found = len(remaining_lead_ids)

        conn.commit()
        cur.close()
        conn.close()

        logger.info(f"Campaign {campaign['campaign_name']}: {updated} updated, {not_found} not found")

        return {
            'success': True,
            'campaign_name': campaign['campaign_name'],
            'updated': updated,
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
        total_not_found = 0

        for campaign in campaigns:
            result = find_row_numbers_for_campaign(campaign)

            if result['success']:
                total_updated += result.get('updated', 0)
                total_not_found += result.get('not_found', 0)

        logger.info("=== Process Completed ===")
        logger.info(f"Total: {total_updated} leads updated, {total_not_found} not found in sheets")

    except Exception as e:
        logger.error(f"Process failed: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()

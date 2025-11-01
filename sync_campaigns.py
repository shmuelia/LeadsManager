#!/usr/bin/env python3
"""
Auto-sync script for Heroku Scheduler
Syncs all active campaigns with Google Sheets
"""

import os
import sys
import logging
import psycopg2
import psycopg2.extras
import requests
import csv
import json
from io import StringIO
from datetime import datetime

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

def sync_campaign(campaign):
    """Sync a single campaign"""
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
        column_mapping = campaign_full.get('column_mapping', {})

        # Convert sheet URL to CSV export URL
        if '/edit' in sheet_url:
            csv_url = sheet_url.split('/edit')[0] + '/export?format=csv'
        else:
            csv_url = sheet_url + '/export?format=csv'

        # Fetch CSV data
        response = requests.get(csv_url, timeout=30)
        response.raise_for_status()
        response.encoding = 'utf-8'

        reader = csv.DictReader(StringIO(response.text))

        new_leads = 0
        duplicates = 0
        errors = 0

        for row in reader:
            try:
                row_data = dict(row)

                # Extract fields using column mapping
                custom_data = {}
                if column_mapping and column_mapping.get('name'):
                    name = row_data.get(column_mapping['name'], '').strip()
                    phone = row_data.get(column_mapping.get('phone', ''), '').strip()
                    email = row_data.get(column_mapping.get('email', ''), '').strip()
                    campaign_name_from_row = row_data.get(column_mapping.get('campaign', ''), '').strip()

                    # Extract custom fields
                    if 'custom_fields' in column_mapping:
                        for field_name in column_mapping['custom_fields']:
                            field_value = row_data.get(field_name, '').strip()
                            if field_value:
                                custom_data[field_name] = field_value
                else:
                    # No column mapping - skip this campaign
                    logger.warning(f"Campaign {campaign['campaign_name']} has no column mapping configured")
                    continue

                # Validate required fields
                if not name or (not phone and not email):
                    continue

                # Determine final campaign name
                final_campaign_name = campaign_name_from_row if campaign_name_from_row else campaign_full['campaign_name']

                # Check for duplicates
                check_query = "SELECT id FROM leads WHERE customer_id = %s AND ("
                check_params = [campaign_full['customer_id']]
                conditions = []

                if phone:
                    conditions.append("phone = %s")
                    check_params.append(phone)
                if email:
                    conditions.append("email = %s")
                    check_params.append(email)

                check_query += " OR ".join(conditions) + ")"

                cur.execute(check_query, check_params)
                existing = cur.fetchone()

                if existing:
                    duplicates += 1
                    continue

                # Insert new lead
                cur.execute("""
                    INSERT INTO leads
                    (customer_id, name, email, phone, status, campaign_name, raw_data, custom_data, received_at)
                    VALUES (%s, %s, %s, %s, 'new', %s, %s, %s, CURRENT_TIMESTAMP)
                    RETURNING id
                """, (
                    campaign_full['customer_id'],
                    name,
                    email if email else None,
                    phone if phone else None,
                    final_campaign_name,
                    json.dumps(row_data),
                    json.dumps(custom_data)
                ))

                new_leads += 1

            except Exception as e:
                errors += 1
                logger.error(f"Error processing row in campaign {campaign['campaign_name']}: {e}")
                continue

        conn.commit()
        cur.close()
        conn.close()

        logger.info(f"Campaign {campaign['campaign_name']}: {new_leads} new, {duplicates} duplicates, {errors} errors")

        return {
            'success': True,
            'campaign_name': campaign['campaign_name'],
            'new_leads': new_leads,
            'duplicates': duplicates,
            'errors': errors
        }

    except Exception as e:
        logger.error(f"Error syncing campaign {campaign.get('campaign_name', campaign.get('id'))}: {e}")
        return {
            'success': False,
            'campaign_name': campaign.get('campaign_name', campaign.get('id')),
            'error': str(e)
        }

def main():
    """Main sync function"""
    logger.info("=== Auto-sync started ===")
    start_time = datetime.now()

    try:
        conn = get_db_connection()
        if not conn:
            logger.error("Failed to connect to database")
            sys.exit(1)

        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Get all active campaigns with sheet URLs
        cur.execute("""
            SELECT id, campaign_name, sheet_url
            FROM campaigns
            WHERE active = true
            AND sheet_url IS NOT NULL
            AND sheet_url != ''
            ORDER BY id
        """)

        campaigns = cur.fetchall()
        cur.close()
        conn.close()

        if not campaigns:
            logger.info("No active campaigns to sync")
            return

        logger.info(f"Found {len(campaigns)} active campaigns to sync")

        # Sync each campaign
        total_new = 0
        total_duplicates = 0
        total_errors = 0

        for campaign in campaigns:
            result = sync_campaign(campaign)

            if result['success']:
                total_new += result['new_leads']
                total_duplicates += result['duplicates']
                total_errors += result['errors']
            else:
                total_errors += 1

        duration = (datetime.now() - start_time).total_seconds()

        logger.info(f"=== Auto-sync completed in {duration:.2f}s ===")
        logger.info(f"Total: {total_new} new leads, {total_duplicates} duplicates, {total_errors} errors")

    except Exception as e:
        logger.error(f"Auto-sync failed: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()

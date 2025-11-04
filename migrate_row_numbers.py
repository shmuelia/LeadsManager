#!/usr/bin/env python3
"""
One-time migration script to populate row_number for existing leads
Run this once to match existing leads with their Google Sheet row numbers
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

def migrate_campaign(campaign):
    """Migrate row numbers for a single campaign"""
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

        if not column_mapping or not column_mapping.get('name'):
            logger.warning(f"Campaign {campaign['campaign_name']} has no column mapping - skipping")
            cur.close()
            conn.close()
            return {'success': False, 'error': 'No column mapping'}

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

        updated = 0
        not_found = 0
        current_row = 0

        for row_data in reader:
            current_row += 1

            # Skip empty rows
            if not any(row_data.values()):
                continue

            try:
                # Extract fields using column mapping
                name = row_data.get(column_mapping['name'], '').strip()
                phone = row_data.get(column_mapping.get('phone', ''), '').strip()
                email = row_data.get(column_mapping.get('email', ''), '').strip()

                # Clean phone number
                if phone:
                    phone = str(phone).strip().replace('-', '').replace(' ', '')

                # Skip if no identifying information
                if not name or (not phone and not email):
                    continue

                # Find matching lead in database
                cur.execute("""
                    SELECT id, raw_data FROM leads
                    WHERE customer_id = %s
                    AND name = %s
                    AND ((phone IS NOT NULL AND phone = %s) OR (email IS NOT NULL AND email = %s))
                    LIMIT 1
                """, (campaign_full['customer_id'], name, phone or '', email or ''))

                lead = cur.fetchone()

                if lead:
                    # Update raw_data with row_number and sheet_url
                    raw_data = lead['raw_data'] if lead['raw_data'] else {}
                    if isinstance(raw_data, str):
                        raw_data = json.loads(raw_data)

                    # Check if we need to update (missing row_number OR missing sheet_url)
                    needs_update = False

                    if 'row_number' not in raw_data:
                        raw_data['row_number'] = current_row
                        needs_update = True

                    if 'sheet_url' not in raw_data:
                        raw_data['sheet_url'] = campaign_full.get('sheet_url', '')
                        needs_update = True

                    if 'sheet_id' not in raw_data:
                        raw_data['sheet_id'] = campaign_full.get('sheet_id', '')
                        needs_update = True

                    if needs_update:
                        cur.execute("""
                            UPDATE leads
                            SET raw_data = %s
                            WHERE id = %s
                        """, (json.dumps(raw_data), lead['id']))

                        updated += 1
                else:
                    not_found += 1

            except Exception as e:
                logger.error(f"Error processing row {current_row} in campaign {campaign['campaign_name']}: {e}")
                continue

        conn.commit()
        cur.close()
        conn.close()

        logger.info(f"Campaign {campaign['campaign_name']}: {updated} updated, {not_found} not found in DB")

        return {
            'success': True,
            'campaign_name': campaign['campaign_name'],
            'updated': updated,
            'not_found': not_found
        }

    except Exception as e:
        logger.error(f"Error migrating campaign {campaign.get('campaign_name', campaign.get('id'))}: {e}")
        return {
            'success': False,
            'campaign_name': campaign.get('campaign_name', campaign.get('id')),
            'error': str(e)
        }

def main():
    """Main migration function"""
    logger.info("=== Row Number Migration Started ===")

    try:
        conn = get_db_connection()
        if not conn:
            logger.error("Failed to connect to database")
            sys.exit(1)

        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Get all campaigns with sheet URLs
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
            logger.info("No campaigns found to migrate")
            return

        logger.info(f"Found {len(campaigns)} campaigns to migrate")

        # Migrate each campaign
        total_updated = 0
        total_not_found = 0

        for campaign in campaigns:
            result = migrate_campaign(campaign)

            if result['success']:
                total_updated += result['updated']
                total_not_found += result['not_found']

        logger.info("=== Migration Completed ===")
        logger.info(f"Total: {total_updated} leads updated, {total_not_found} not found in sheets")

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()

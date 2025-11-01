#!/usr/bin/env python3
"""
Add column_mapping field to campaigns table
This allows storing custom field mappings for each campaign
"""
import os
import psycopg2

# Database connection from environment
DATABASE_URL = os.environ.get('DATABASE_URL')

if not DATABASE_URL:
    print("Error: DATABASE_URL environment variable not set")
    exit(1)

# Fix postgres:// to postgresql:// if needed
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

def add_column_mapping():
    """Add column_mapping JSONB field to campaigns table"""

    try:
        # Connect to database
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()

        print("Connected to database successfully!")
        print("Adding column_mapping field to campaigns table...")

        # Add column_mapping field if it doesn't exist
        cur.execute("""
            ALTER TABLE campaigns
            ADD COLUMN IF NOT EXISTS column_mapping JSONB DEFAULT '{}'::jsonb;
        """)

        conn.commit()

        print("✅ column_mapping field added successfully!")
        print("   This field will store mappings like:")
        print("   {")
        print("     'name': 'שם מלא',")
        print("     'phone': 'מס פלאפון',")
        print("     'email': 'מייל',")
        print("     'date': 'תאריך',")
        print("     'campaign': 'שם הקמפיין'")
        print("   }")

        cur.close()
        conn.close()

    except Exception as e:
        print(f"❌ Error: {e}")
        return False

    return True

if __name__ == "__main__":
    print("🚀 Starting migration...")

    if add_column_mapping():
        print("\n🎉 Migration complete!")
    else:
        print("❌ Migration failed!")
        exit(1)

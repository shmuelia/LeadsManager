#!/usr/bin/env python3
"""
Migration script to ensure campaigns table has proper structure and foreign keys
Run this on Heroku: heroku run python migrate_campaigns.py --app eadmanager-fresh-2024-dev
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

def migrate_campaigns_table():
    """Ensure campaigns table exists with proper foreign keys"""

    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()

        print("🔄 Checking campaigns table...")

        # Create campaigns table if it doesn't exist
        cur.execute("""
            CREATE TABLE IF NOT EXISTS campaigns (
                id SERIAL PRIMARY KEY,
                customer_id INTEGER NOT NULL,
                campaign_name VARCHAR(255) NOT NULL,
                campaign_type VARCHAR(50) DEFAULT 'google_sheets',
                sheet_id VARCHAR(255),
                sheet_url TEXT,
                active BOOLEAN DEFAULT true,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_synced_row INTEGER DEFAULT 1,
                last_synced_at TIMESTAMP,
                UNIQUE(customer_id, campaign_name)
            );
        """)
        print("✅ Campaigns table created/verified")

        # Check if last_synced_row column exists and its type
        cur.execute("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'campaigns'
            AND column_name = 'last_synced_row';
        """)

        sync_col = cur.fetchone()

        if not sync_col:
            print("🔧 Adding last_synced_row column as JSONB...")
            cur.execute("""
                ALTER TABLE campaigns
                ADD COLUMN last_synced_row JSONB DEFAULT '{}'::jsonb,
                ADD COLUMN last_synced_at TIMESTAMP;
            """)
            print("✅ Sync tracking columns added (JSONB)")
        elif sync_col[1] == 'integer':
            print("🔧 Converting last_synced_row from INTEGER to JSONB for multi-tab support...")

            # Get current data before conversion
            cur.execute("""
                SELECT id, last_synced_row
                FROM campaigns
                WHERE last_synced_row IS NOT NULL
            """)
            existing_data = cur.fetchall()

            # Drop and recreate as JSONB
            cur.execute("""
                ALTER TABLE campaigns
                DROP COLUMN last_synced_row;
            """)
            cur.execute("""
                ALTER TABLE campaigns
                ADD COLUMN last_synced_row JSONB DEFAULT '{}'::jsonb;
            """)

            # Restore data in new format: INTEGER -> {"gid_0": value}
            for row_id, old_value in existing_data:
                if old_value and old_value > 1:
                    cur.execute("""
                        UPDATE campaigns
                        SET last_synced_row = %s::jsonb
                        WHERE id = %s
                    """, (f'{{"gid_0": {old_value}}}', row_id))

            print(f"✅ Converted {len(existing_data)} campaigns to JSONB format")
        elif sync_col[1] == 'jsonb':
            print("✅ Sync tracking columns already exist (JSONB)")
        else:
            print(f"⚠️  Unexpected column type: {sync_col[1]}")

        # Check if foreign key constraint exists
        cur.execute("""
            SELECT constraint_name
            FROM information_schema.table_constraints
            WHERE table_name = 'campaigns'
            AND constraint_type = 'FOREIGN KEY'
            AND constraint_name = 'campaigns_customer_id_fkey';
        """)

        fk_exists = cur.fetchone()

        if not fk_exists:
            print("🔧 Adding foreign key constraint for customer_id...")

            # Add foreign key constraint
            cur.execute("""
                ALTER TABLE campaigns
                ADD CONSTRAINT campaigns_customer_id_fkey
                FOREIGN KEY (customer_id)
                REFERENCES customers(id)
                ON DELETE CASCADE;
            """)
            print("✅ Foreign key constraint added")
        else:
            print("✅ Foreign key constraint already exists")

        # Create indexes for better performance
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_campaigns_customer_id ON campaigns(customer_id);
            CREATE INDEX IF NOT EXISTS idx_campaigns_sheet_id ON campaigns(sheet_id);
            CREATE INDEX IF NOT EXISTS idx_campaigns_active ON campaigns(active);
        """)
        print("✅ Indexes created/verified")

        # Create update trigger for updated_at
        cur.execute("""
            CREATE OR REPLACE FUNCTION update_campaigns_updated_at()
            RETURNS TRIGGER AS $$
            BEGIN
                NEW.updated_at = CURRENT_TIMESTAMP;
                RETURN NEW;
            END;
            $$ language 'plpgsql';
        """)

        cur.execute("""
            DROP TRIGGER IF EXISTS update_campaigns_updated_at ON campaigns;
        """)

        cur.execute("""
            CREATE TRIGGER update_campaigns_updated_at
                BEFORE UPDATE ON campaigns
                FOR EACH ROW
                EXECUTE FUNCTION update_campaigns_updated_at();
        """)
        print("✅ Update trigger created")

        conn.commit()

        # Show table info
        cur.execute("""
            SELECT
                column_name,
                data_type,
                is_nullable,
                column_default
            FROM information_schema.columns
            WHERE table_name = 'campaigns'
            ORDER BY ordinal_position;
        """)

        columns = cur.fetchall()
        print("\n📋 Campaigns table structure:")
        for col in columns:
            print(f"  - {col[0]}: {col[1]} {'NULL' if col[2] == 'YES' else 'NOT NULL'}")

        # Show constraints
        cur.execute("""
            SELECT constraint_name, constraint_type
            FROM information_schema.table_constraints
            WHERE table_name = 'campaigns';
        """)

        constraints = cur.fetchall()
        print("\n🔒 Constraints:")
        for const in constraints:
            print(f"  - {const[0]}: {const[1]}")

        # Count existing campaigns
        cur.execute("SELECT COUNT(*) FROM campaigns;")
        count = cur.fetchone()[0]
        print(f"\n📊 Total campaigns: {count}")

        cur.close()
        conn.close()

        print("\n🎉 Migration completed successfully!")
        return True

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🚀 Starting campaigns table migration...")

    if migrate_campaigns_table():
        print("\n✅ All done!")
    else:
        print("\n❌ Migration failed!")
        exit(1)

#!/usr/bin/env python3
"""
Database setup script for LeadsManager
Creates all required tables from scratch
"""

import os
import psycopg2

def create_tables():
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        print("ERROR: DATABASE_URL not set")
        return False

    # Convert postgres:// to postgresql://
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)

    conn = psycopg2.connect(database_url)
    conn.autocommit = True
    cur = conn.cursor()

    try:
        # 1. Create update_updated_at_column function
        cur.execute("""
            CREATE OR REPLACE FUNCTION update_updated_at_column()
            RETURNS TRIGGER AS $$
            BEGIN
                NEW.updated_at = CURRENT_TIMESTAMP;
                RETURN NEW;
            END;
            $$ language 'plpgsql';
        """)
        print('1. Created update_updated_at_column function')

        # 2. Create customers table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                webhook_url VARCHAR(500),
                zapier_webhook_key VARCHAR(255),
                zapier_account_email VARCHAR(255),
                facebook_app_id VARCHAR(100),
                instagram_app_id VARCHAR(100),
                api_settings JSONB DEFAULT '{}',
                sender_email VARCHAR(255),
                smtp_server VARCHAR(255),
                smtp_port INTEGER DEFAULT 587,
                smtp_username VARCHAR(255),
                smtp_password VARCHAR(255),
                email_notifications_enabled BOOLEAN DEFAULT false,
                timezone VARCHAR(100) DEFAULT 'Asia/Jerusalem',
                active BOOLEAN DEFAULT true,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        print('2. Created customers table')

        # 3. Create users table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(100) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                plain_password VARCHAR(255),
                full_name VARCHAR(255) NOT NULL,
                email VARCHAR(255),
                phone VARCHAR(50),
                role VARCHAR(50) DEFAULT 'user',
                department VARCHAR(100),
                customer_id INTEGER REFERENCES customers(id) ON DELETE SET NULL,
                active BOOLEAN DEFAULT true,
                whatsapp_notifications BOOLEAN DEFAULT true,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        print('3. Created users table')

        # 4. Create leads table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                id SERIAL PRIMARY KEY,
                external_lead_id VARCHAR(255),
                customer_id INTEGER REFERENCES customers(id) ON DELETE SET NULL,
                name VARCHAR(255),
                email VARCHAR(255),
                phone VARCHAR(50),
                platform VARCHAR(50) DEFAULT 'facebook',
                campaign_name TEXT,
                form_name TEXT,
                lead_source TEXT,
                created_time TIMESTAMP,
                received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status VARCHAR(50) DEFAULT 'new',
                assigned_to VARCHAR(255),
                priority INTEGER DEFAULT 0,
                raw_data JSONB,
                custom_data JSONB,
                notes TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        print('4. Created leads table')

        # 5. Create lead_activities table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS lead_activities (
                id SERIAL PRIMARY KEY,
                lead_id INTEGER REFERENCES leads(id) ON DELETE CASCADE,
                customer_id INTEGER REFERENCES customers(id) ON DELETE SET NULL,
                user_name VARCHAR(255) NOT NULL,
                activity_type VARCHAR(50) NOT NULL,
                description TEXT,
                call_duration INTEGER,
                call_outcome VARCHAR(100),
                previous_status VARCHAR(50),
                new_status VARCHAR(50),
                activity_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                activity_metadata JSONB
            );
        """)
        print('5. Created lead_activities table')

        # 6. Create campaigns table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS campaigns (
                id SERIAL PRIMARY KEY,
                customer_id INTEGER REFERENCES customers(id) ON DELETE SET NULL,
                campaign_name VARCHAR(255) NOT NULL,
                campaign_type VARCHAR(50) DEFAULT 'google_sheets',
                sheet_id VARCHAR(255),
                sheet_url TEXT,
                column_mapping JSONB DEFAULT '{}',
                last_synced_row JSONB,
                last_synced_at TIMESTAMP,
                active BOOLEAN DEFAULT true,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        print('6. Created campaigns table')

        # 7. Create notifications table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id SERIAL PRIMARY KEY,
                customer_id INTEGER REFERENCES customers(id) ON DELETE SET NULL,
                lead_id INTEGER REFERENCES leads(id) ON DELETE CASCADE,
                notification_type VARCHAR(50) NOT NULL,
                title VARCHAR(255) NOT NULL,
                message TEXT NOT NULL,
                data JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                read_by_users JSONB DEFAULT '[]'::jsonb
            );
        """)
        print('7. Created notifications table')

        # 8. Create indexes
        cur.execute('CREATE INDEX IF NOT EXISTS idx_customers_active ON customers(active);')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_leads_customer_id ON leads(customer_id);')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_leads_assigned_to ON leads(assigned_to);')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_users_customer_id ON users(customer_id);')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_lead_activities_customer_id ON lead_activities(customer_id);')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_lead_activities_lead_id ON lead_activities(lead_id);')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_campaigns_customer_id ON campaigns(customer_id);')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_campaigns_active ON campaigns(active);')
        print('8. Created indexes')

        # 9. Drop old irrelevant tables
        old_tables = ['bankmovmizrachi', 'movement_types', 'movements', 'parameters', 'transaction_assignments']
        for table in old_tables:
            try:
                cur.execute(f"DROP TABLE IF EXISTS {table} CASCADE;")
                print(f'   Dropped old table: {table}')
            except Exception as e:
                print(f'   Could not drop {table}: {e}')
        print('9. Cleaned up old tables')

        # 10. Insert default customer
        cur.execute("""
            INSERT INTO customers (id, name, webhook_url, zapier_webhook_key, active, timezone)
            VALUES (1, 'מאפיית משמרות - לקוח ברירת מחדל', '/webhook', 'default_webhook_key', true, 'Asia/Jerusalem')
            ON CONFLICT (id) DO NOTHING;
        """)
        print('10. Inserted default customer')

        # 11. Insert default admin user (password: admin123) - use customer_id=1 (not 0)
        cur.execute("""
            INSERT INTO users (username, password_hash, plain_password, full_name, email, role, department, customer_id, active)
            VALUES ('admin', '240be518fabd2724ddb6f04eeb9d5b13', 'admin123', 'System Administrator', 'admin@leadmanager.com', 'admin', 'management', 1, true)
            ON CONFLICT (username) DO NOTHING;
        """)
        print('11. Inserted default admin user')

        # Verify tables
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name")
        tables = cur.fetchall()
        print('\n=== Tables created ===')
        for t in tables:
            print(f'  - {t[0]}')

        cur.close()
        conn.close()
        print('\nDone! Database setup complete.')
        return True

    except Exception as e:
        print(f"ERROR: {e}")
        cur.close()
        conn.close()
        return False

if __name__ == '__main__':
    create_tables()

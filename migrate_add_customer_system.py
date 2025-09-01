#!/usr/bin/env python3
"""
Migration script to add customer system to LeadsManager
Adds customers table and customer_id to all existing tables
"""
import os
import psycopg2
from datetime import datetime

# Database connection from environment
DATABASE_URL = os.environ.get('DATABASE_URL')

if not DATABASE_URL:
    print("Error: DATABASE_URL environment variable not set")
    exit(1)

# Fix postgres:// to postgresql:// if needed
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

def migrate_add_customer_system():
    """Add customer system to existing database"""
    
    migration_sql = """
    -- Create customers table
    CREATE TABLE IF NOT EXISTS customers (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        webhook_url VARCHAR(500),
        zapier_webhook_key VARCHAR(255),
        zapier_account_email VARCHAR(255),
        facebook_app_id VARCHAR(100),
        instagram_app_id VARCHAR(100),
        api_settings JSONB DEFAULT '{}',
        active BOOLEAN DEFAULT true,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- Add customer_id to leads table
    ALTER TABLE leads 
    ADD COLUMN IF NOT EXISTS customer_id INTEGER REFERENCES customers(id) ON DELETE SET NULL;

    -- Add customer_id to users table
    ALTER TABLE users 
    ADD COLUMN IF NOT EXISTS customer_id INTEGER REFERENCES customers(id) ON DELETE SET NULL;

    -- Add customer_id to lead_activities table
    ALTER TABLE lead_activities 
    ADD COLUMN IF NOT EXISTS customer_id INTEGER REFERENCES customers(id) ON DELETE SET NULL;

    -- Add customer_id to lead_assignments table (if it exists)
    ALTER TABLE lead_assignments 
    ADD COLUMN IF NOT EXISTS customer_id INTEGER REFERENCES customers(id) ON DELETE SET NULL;

    -- Create indexes for better performance
    CREATE INDEX IF NOT EXISTS idx_customers_active ON customers(active);
    CREATE INDEX IF NOT EXISTS idx_leads_customer_id ON leads(customer_id);
    CREATE INDEX IF NOT EXISTS idx_users_customer_id ON users(customer_id);
    CREATE INDEX IF NOT EXISTS idx_lead_activities_customer_id ON lead_activities(customer_id);
    CREATE INDEX IF NOT EXISTS idx_lead_assignments_customer_id ON lead_assignments(customer_id);

    -- Create function to automatically update updated_at timestamp for customers
    CREATE OR REPLACE FUNCTION update_updated_at_column()
    RETURNS TRIGGER AS $$
    BEGIN
        NEW.updated_at = CURRENT_TIMESTAMP;
        RETURN NEW;
    END;
    $$ language 'plpgsql';

    -- Create trigger to automatically update updated_at on customers table
    DROP TRIGGER IF EXISTS update_customers_updated_at ON customers;
    CREATE TRIGGER update_customers_updated_at 
        BEFORE UPDATE ON customers 
        FOR EACH ROW 
        EXECUTE FUNCTION update_updated_at_column();

    -- Insert default customer #1 (Bakery) with current webhook details
    INSERT INTO customers (id, name, webhook_url, zapier_webhook_key, active) 
    VALUES (1, 'מאפיית משמרות - לקוח ברירת מחדל', '/webhook', 'default_webhook_key', true)
    ON CONFLICT (id) DO NOTHING;

    -- Update all existing data to belong to customer #1
    UPDATE leads SET customer_id = 1 WHERE customer_id IS NULL;
    UPDATE users SET customer_id = 1 WHERE customer_id IS NULL;
    UPDATE lead_activities SET customer_id = 1 WHERE customer_id IS NULL;
    UPDATE lead_assignments SET customer_id = 1 WHERE customer_id IS NULL;

    -- Reset sequence to start from 2 for new customers
    SELECT setval('customers_id_seq', 1, true);
    """
    
    try:
        # Connect to database
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        print("Connected to database successfully!")
        print("Adding customer system...")
        
        # Execute migration
        cur.execute(migration_sql)
        conn.commit()
        
        print("✅ Customer system added successfully!")
        print("✅ Tables updated: customers (new), leads, users, lead_activities, lead_assignments")
        print("✅ Indexes and triggers created")
        print("✅ Default customer #1 (Bakery) created")
        print("✅ Existing data migrated to customer #1")
        
        # Show customer info
        cur.execute("SELECT id, name, active FROM customers ORDER BY id;")
        customers = cur.fetchall()
        print(f"\n📋 Customers: {customers}")
        
        # Show data counts
        cur.execute("SELECT COUNT(*) FROM leads WHERE customer_id = 1;")
        lead_count = cur.fetchone()[0]
        print(f"📊 Leads migrated to customer #1: {lead_count}")
        
        cur.close()
        conn.close()
        
    except Exception as e:
        print(f"❌ Migration error: {e}")
        return False
    
    return True

if __name__ == "__main__":
    print("🚀 Starting customer system migration...")
    print(f"📊 Database: {DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else 'Hidden'}")
    
    if migrate_add_customer_system():
        print("\n🎉 Customer system migration complete!")
        print("\n✨ Next steps:")
        print("1. Deploy updated application")
        print("2. Admin can now select customers and manage them")
        print("3. All webhook data will be filtered by customer")
    else:
        print("❌ Migration failed!")
        exit(1)
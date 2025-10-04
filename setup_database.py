#!/usr/bin/env python3
"""
Database setup script for LeadsManager
Run this to create all necessary tables and initial data
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

def create_tables():
    """Create all database tables"""
    
    schema_sql = """
    -- Leads table - stores all lead information
    CREATE TABLE IF NOT EXISTS leads (
        id SERIAL PRIMARY KEY,
        external_lead_id VARCHAR(255),
        name VARCHAR(255),
        email VARCHAR(255),
        phone VARCHAR(20),
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
        notes TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- Lead activities table - tracks what actions were taken on each lead
    CREATE TABLE IF NOT EXISTS lead_activities (
        id SERIAL PRIMARY KEY,
        lead_id INTEGER REFERENCES leads(id) ON DELETE CASCADE,
        user_name VARCHAR(255) NOT NULL,
        activity_type VARCHAR(100) NOT NULL,
        description TEXT,
        call_duration INTEGER,
        call_outcome VARCHAR(100),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        activity_metadata JSONB
    );

    -- Users table - for tracking who is working on leads
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username VARCHAR(100) UNIQUE NOT NULL,
        full_name VARCHAR(255),
        email VARCHAR(255),
        phone VARCHAR(20),
        role VARCHAR(50) DEFAULT 'agent',
        active BOOLEAN DEFAULT true,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- Lead assignments table - for managing lead distribution
    CREATE TABLE IF NOT EXISTS lead_assignments (
        id SERIAL PRIMARY KEY,
        lead_id INTEGER REFERENCES leads(id) ON DELETE CASCADE,
        assigned_to_user_id INTEGER REFERENCES users(id),
        assigned_by_user_id INTEGER REFERENCES users(id),
        assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        status VARCHAR(50) DEFAULT 'active',
        notes TEXT
    );

    -- Create indexes for better performance
    CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
    CREATE INDEX IF NOT EXISTS idx_leads_assigned_to ON leads(assigned_to);
    CREATE INDEX IF NOT EXISTS idx_leads_created_time ON leads(created_time);
    CREATE INDEX IF NOT EXISTS idx_leads_received_at ON leads(received_at);
    CREATE INDEX IF NOT EXISTS idx_lead_activities_lead_id ON lead_activities(lead_id);
    CREATE INDEX IF NOT EXISTS idx_lead_activities_created_at ON lead_activities(created_at);
    CREATE INDEX IF NOT EXISTS idx_lead_assignments_lead_id ON lead_assignments(lead_id);

    -- Create function to automatically update updated_at timestamp
    CREATE OR REPLACE FUNCTION update_updated_at_column()
    RETURNS TRIGGER AS $$
    BEGIN
        NEW.updated_at = CURRENT_TIMESTAMP;
        RETURN NEW;
    END;
    $$ language 'plpgsql';

    -- Create trigger to automatically update updated_at on leads table
    DROP TRIGGER IF EXISTS update_leads_updated_at ON leads;
    CREATE TRIGGER update_leads_updated_at 
        BEFORE UPDATE ON leads 
        FOR EACH ROW 
        EXECUTE FUNCTION update_updated_at_column();

    -- Insert default admin user if not exists
    INSERT INTO users (username, full_name, email, role) 
    VALUES ('admin', 'System Administrator', 'admin@leadmanager.com', 'admin')
    ON CONFLICT (username) DO NOTHING;
    """
    
    try:
        # Connect to database
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        print("Connected to database successfully!")
        print("Creating tables...")
        
        # Execute schema
        cur.execute(schema_sql)
        conn.commit()
        
        print("✅ Database schema created successfully!")
        print("✅ Tables: leads, lead_activities, users, lead_assignments")
        print("✅ Indexes and triggers created")
        print("✅ Default admin user inserted")
        
        # Show table info
        cur.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
            ORDER BY table_name;
        """)
        
        tables = cur.fetchall()
        print(f"\n📋 Created tables: {[t[0] for t in tables]}")
        
        cur.close()
        conn.close()
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return False
    
    return True

def migrate_existing_lead():
    """Migrate the existing lead from memory to database"""
    existing_lead_data = {
        "external_lead_id": "1246157837204098",
        "name": "ענבר כהן",
        "email": "1122inbar@gmail.com", 
        "phone": "532235973",
        "platform": "ig",
        "campaign_name": "קמפיין לידים - דרושים - 02.07.25",
        "form_name": "טופס לידים 03.07.25 - דרושים - שאלות סינון",
        "created_time": "2025-07-26T15:54:54+00:00",
        "status": "new"
    }
    
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        # Check if lead already exists
        cur.execute("SELECT id FROM leads WHERE external_lead_id = %s", (existing_lead_data["external_lead_id"],))
        if cur.fetchone():
            print("📋 Existing lead already migrated")
            cur.close()
            conn.close()
            return True
        
        # Insert the existing lead
        cur.execute("""
            INSERT INTO leads (external_lead_id, name, email, phone, platform, campaign_name, form_name, created_time, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id;
        """, (
            existing_lead_data["external_lead_id"],
            existing_lead_data["name"],
            existing_lead_data["email"],
            existing_lead_data["phone"],
            existing_lead_data["platform"],
            existing_lead_data["campaign_name"],
            existing_lead_data["form_name"],
            existing_lead_data["created_time"],
            existing_lead_data["status"]
        ))
        
        lead_id = cur.fetchone()[0]
        
        # Add initial activity
        cur.execute("""
            INSERT INTO lead_activities (lead_id, user_name, activity_type, description)
            VALUES (%s, %s, %s, %s);
        """, (lead_id, 'system', 'lead_received', 'Lead received from Instagram via webhook - migrated to database'))
        
        conn.commit()
        
        print(f"✅ Migrated existing lead: {existing_lead_data['name']} (ID: {lead_id})")
        
        cur.close()
        conn.close()
        
    except Exception as e:
        print(f"❌ Migration error: {e}")
        return False
    
    return True

if __name__ == "__main__":
    print("🚀 Starting database setup...")
    print(f"📊 Database: {DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else 'Hidden'}")
    
    if create_tables():
        print("\n🔄 Migrating existing lead data...")
        migrate_existing_lead()
        print("\n🎉 Database setup complete!")
        print("\n🌐 Your API is ready at: https://leadmanagement-dev-4c46df30a3b3.herokuapp.com/leads")
    else:
        print("❌ Database setup failed!")
        exit(1)

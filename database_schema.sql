-- LeadsManager PostgreSQL Database Schema
-- Complete database structure for lead management system

-- Main leads table - stores all lead information
CREATE TABLE IF NOT EXISTS leads (
    id SERIAL PRIMARY KEY,
    external_lead_id VARCHAR(255) UNIQUE, -- Facebook lead ID from webhook
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255),
    phone VARCHAR(20),
    platform VARCHAR(50) DEFAULT 'facebook',
    campaign_name TEXT,
    form_name TEXT,
    lead_source TEXT,
    created_time TIMESTAMP, -- When lead was originally created on Facebook
    received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, -- When we received it
    status VARCHAR(50) DEFAULT 'new',
    assigned_to VARCHAR(255),
    priority INTEGER DEFAULT 0,
    raw_data JSONB, -- Store complete original data (webhook/CSV)
    notes TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Constraints
    CONSTRAINT unique_email_per_campaign UNIQUE(email, campaign_name)
);

-- Lead activities table - tracks all interactions with each lead
CREATE TABLE IF NOT EXISTS lead_activities (
    id SERIAL PRIMARY KEY,
    lead_id INTEGER REFERENCES leads(id) ON DELETE CASCADE,
    user_name VARCHAR(255) NOT NULL, -- Who performed the action
    activity_type VARCHAR(50) NOT NULL, -- 'call', 'email', 'whatsapp', 'note', 'status_change', 'assignment'
    description TEXT,
    call_duration INTEGER, -- For call activities (seconds)
    call_outcome VARCHAR(100), -- 'answered', 'no_answer', 'busy', 'interested', 'not_interested', 'callback'
    previous_status VARCHAR(50), -- For status changes
    new_status VARCHAR(50), -- For status changes  
    activity_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    activity_metadata JSONB -- Additional data (phone numbers, email templates, etc.)
);

-- Users table - for team management and assignments
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    email VARCHAR(255),
    phone VARCHAR(20),
    role VARCHAR(50) DEFAULT 'agent', -- 'admin', 'manager', 'agent'
    department VARCHAR(100), -- For bakery: 'hr', 'management', 'production'
    active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Performance indexes
CREATE INDEX IF NOT EXISTS idx_leads_email ON leads(email);
CREATE INDEX IF NOT EXISTS idx_leads_phone ON leads(phone);
CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
CREATE INDEX IF NOT EXISTS idx_leads_external_id ON leads(external_lead_id);
CREATE INDEX IF NOT EXISTS idx_leads_created_time ON leads(created_time);
CREATE INDEX IF NOT EXISTS idx_leads_received_at ON leads(received_at);
CREATE INDEX IF NOT EXISTS idx_leads_platform ON leads(platform);
CREATE INDEX IF NOT EXISTS idx_leads_campaign ON leads(campaign_name);

CREATE INDEX IF NOT EXISTS idx_activities_lead_id ON lead_activities(lead_id);
CREATE INDEX IF NOT EXISTS idx_activities_type ON lead_activities(activity_type);
CREATE INDEX IF NOT EXISTS idx_activities_date ON lead_activities(activity_date);
CREATE INDEX IF NOT EXISTS idx_activities_user ON lead_activities(user_name);

CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
CREATE INDEX IF NOT EXISTS idx_users_active ON users(active);

-- Trigger function to auto-update timestamps
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Auto-update triggers
CREATE TRIGGER IF NOT EXISTS update_leads_updated_at 
    BEFORE UPDATE ON leads 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER IF NOT EXISTS update_users_updated_at 
    BEFORE UPDATE ON users 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

-- Insert default system user
INSERT INTO users (username, full_name, email, role, department) 
VALUES ('system', 'System Administrator', 'admin@leadmanager.com', 'admin', 'management')
ON CONFLICT (username) DO NOTHING;

-- Lead Status Reference Values:
-- 'new' - Just received from Facebook
-- 'contacted' - Initial contact attempted
-- 'qualified' - Meets job requirements  
-- 'interested' - Expressed interest in position
-- 'not_interested' - Not interested in job
-- 'callback' - Requested callback/follow-up
-- 'interview_scheduled' - Interview arranged
-- 'hired' - Successfully hired
-- 'rejected' - Not suitable for position
-- 'closed' - Process completed

-- Activity Type Reference Values:
-- 'call' - Phone call made
-- 'whatsapp' - WhatsApp message sent
-- 'email' - Email sent
-- 'note' - General note added
-- 'status_change' - Lead status updated
-- 'assignment' - Lead assigned to team member
-- 'callback_scheduled' - Follow-up call scheduled
-- 'interview_scheduled' - Job interview arranged
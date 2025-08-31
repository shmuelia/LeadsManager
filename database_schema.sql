-- LeadsManager PostgreSQL Database Schema

-- Leads table - stores all lead information
CREATE TABLE leads (
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
CREATE TABLE lead_activities (
    id SERIAL PRIMARY KEY,
    lead_id INTEGER REFERENCES leads(id) ON DELETE CASCADE,
    user_name VARCHAR(255) NOT NULL,
    activity_type VARCHAR(100) NOT NULL, -- 'call', 'email', 'note', 'status_change', 'assigned'
    description TEXT,
    call_duration INTEGER, -- seconds, for call activities
    call_outcome VARCHAR(100), -- 'answered', 'voicemail', 'no_answer', 'busy'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    activity_metadata JSONB -- additional data like call recording ID, email template used, etc.
);

-- Users table - for tracking who is working on leads
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    full_name VARCHAR(255),
    email VARCHAR(255),
    phone VARCHAR(20),
    role VARCHAR(50) DEFAULT 'agent', -- 'admin', 'manager', 'agent'
    active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Lead assignments table - for managing lead distribution
CREATE TABLE lead_assignments (
    id SERIAL PRIMARY KEY,
    lead_id INTEGER REFERENCES leads(id) ON DELETE CASCADE,
    assigned_to_user_id INTEGER REFERENCES users(id),
    assigned_by_user_id INTEGER REFERENCES users(id),
    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(50) DEFAULT 'active', -- 'active', 'completed', 'reassigned'
    notes TEXT
);

-- Create indexes for better performance
CREATE INDEX idx_leads_status ON leads(status);
CREATE INDEX idx_leads_assigned_to ON leads(assigned_to);
CREATE INDEX idx_leads_created_time ON leads(created_time);
CREATE INDEX idx_leads_received_at ON leads(received_at);
CREATE INDEX idx_lead_activities_lead_id ON lead_activities(lead_id);
CREATE INDEX idx_lead_activities_created_at ON lead_activities(created_at);
CREATE INDEX idx_lead_assignments_lead_id ON lead_assignments(lead_id);

-- Create function to automatically update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Create trigger to automatically update updated_at on leads table
CREATE TRIGGER update_leads_updated_at 
    BEFORE UPDATE ON leads 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

-- Insert default admin user
INSERT INTO users (username, full_name, email, role) 
VALUES ('admin', 'System Administrator', 'admin@leadmanager.com', 'admin');

-- Lead status enum values (for reference)
-- 'new', 'contacted', 'qualified', 'interested', 'not_interested', 'callback', 'converted', 'closed'

-- Activity type enum values (for reference)  
-- 'call_outbound', 'call_inbound', 'email_sent', 'email_received', 'sms_sent', 'sms_received', 
-- 'note_added', 'status_changed', 'assigned', 'callback_scheduled', 'meeting_scheduled'
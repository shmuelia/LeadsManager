# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# LeadsManager - Hebrew Lead Management System

## Project Overview
A Flask-based lead management system built for a Hebrew-speaking bakery's HR department. Handles lead collection from Facebook/Instagram via webhooks, provides role-based user management, and includes comprehensive lead tracking with activity logging.

**Live Development Environment:** https://eadmanager-fresh-2024-dev-f83e51d73e01.herokuapp.com/

## Core Architecture

### Main Application Structure
- **`app.py`** - Main Flask application (1000+ lines) with webhook handling, authentication, lead management, and routing
- **`setup_database.py`** - Database schema creation and initial data migration script
- **`templates/`** - Hebrew RTL interface templates (login, dashboard, admin_dashboard, user_management)

### Database Schema (PostgreSQL)
**Primary Tables:**
- **`leads`** - Core lead storage with JSONB raw_data, status tracking, assignment management
  - Key fields: `id`, `external_lead_id`, `name`, `email`, `phone`, `platform`, `status`, `assigned_to`, `raw_data`
  - Status values: 'new', 'contacted', 'qualified', 'interested', 'not_interested', 'callback', 'interview_scheduled', 'hired', 'rejected', 'closed'
- **`users`** - User management with role-based permissions
  - Roles: 'admin' (full access), 'user' (assigned leads only)
  - Authentication: MD5 password hashing (should upgrade to bcrypt)
- **`lead_activities`** - Activity logging for lead interactions
  - Tracks: activity_type, description, call_duration, call_outcome, user actions
- **`lead_assignments`** - Lead distribution management (optional table, using assigned_to field in leads)

### Key Business Logic
**Lead Assignment System:**
- Admins can assign leads to users via dropdown selection
- Users see only leads assigned to them in their dashboard
- Assignment filtering: "unassigned", "assigned", specific user assignments
- Real-time assignment updates with toast notifications

**Activity Logging:**
- All lead interactions logged with timestamps
- Activity types: 'lead_received', 'status_change', 'assignment', 'call', 'note_added'
- Comprehensive activity history displayed in lead details modal

## Development Commands

### Local Development
```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export DATABASE_URL="postgresql://user:pass@localhost/leadmanager"
export SECRET_KEY="your-secret-key"

# Run application
python app.py
```

### Database Operations
```bash
# Initialize database schema
python setup_database.py

# Connect to Heroku database
heroku pg:psql --app eadmanager-fresh-2024-dev

# Check lead count
SELECT COUNT(*) FROM leads;

# View recent activities
SELECT * FROM lead_activities ORDER BY activity_date DESC LIMIT 10;
```

### Deployment Commands
```bash
# Deploy to development environment
git push heroku main

# Check application status
curl https://eadmanager-fresh-2024-dev-f83e51d73e01.herokuapp.com/status

# View logs
heroku logs --tail --app eadmanager-fresh-2024-dev
```

## Authentication & Access Control

### Authentication System
- **Session-based**: Uses Flask sessions with `user_id`, `username`, `full_name`, `role`
- **Password Security**: Currently MD5 (upgrade to bcrypt recommended)
- **Role Decorators**: `@login_required` and `@admin_required` for route protection

### Access Levels
- **Admin**: Full system access, user management, lead assignment, system configuration
- **User**: View assigned leads only, update lead status, add activities

### Default Admin Account
- Username: Available after database initialization
- Access user management via `/admin/users` to create accounts

## Lead Management Workflow

### Lead Collection
1. **Webhook Reception**: `/webhook` endpoint receives Facebook/Instagram leads via Zapier
2. **Data Processing**: Extracts name, email, phone, campaign data, handles Hebrew content
3. **Database Storage**: Saves to leads table with JSONB raw_data preservation
4. **Activity Logging**: Creates 'lead_received' activity record

### Lead Processing
1. **Admin Assignment**: Leads assigned to users via admin dashboard
2. **User Workflow**: Users access assigned leads, update status, add activities
3. **Status Progression**: new → contacted → qualified → interested → hired/rejected/closed
4. **Activity Tracking**: All interactions logged with timestamps and details

## Key Features & Interfaces

### Admin Dashboard (`/admin`)
- **Lead Overview**: 12-column comprehensive lead table with assignment controls
- **Filtering System**: Campaign, status, assignment, and user-specific filters with localStorage persistence
- **Mass Operations**: Bulk lead closure, assignment, and export capabilities
- **Lead Details Modal**: Complete lead information with copy-to-clipboard functionality for WhatsApp sharing
- **User Management**: Create/edit users, role assignment, activation/deactivation

### User Dashboard (`/dashboard`)
- **Personal Leads**: Shows only leads assigned to logged-in user
- **Status Management**: Update lead status with activity logging
- **Activity Addition**: Add notes, call logs, and interaction records
- **Responsive Design**: Hebrew RTL interface optimized for mobile and desktop

### Advanced Features
- **Filter State Persistence**: localStorage maintains filter selections across page refreshes
- **Lead Detail Export**: Formatted lead information for copy-paste to messaging applications
- **Real-time Updates**: Assignment changes immediately reflected in filtered views
- **Hebrew Localization**: Full RTL interface with Hebrew text throughout

## Technical Architecture

### Flask Application Structure
- **Route Organization**: Authentication, lead management, admin functions, API endpoints
- **Database Layer**: Direct psycopg2 connections with connection pooling via get_db_connection()
- **Error Handling**: Comprehensive try-catch with logging and user-friendly error messages
- **Session Management**: Flask sessions for authentication state and user context

### Frontend Technology
- **Templates**: Jinja2 with Hebrew RTL styling, Inter font, modern CSS Grid/Flexbox
- **JavaScript**: Vanilla JS with async/await for API calls, localStorage for state persistence
- **Responsive Design**: Mobile-first approach with horizontal scrolling for wide tables
- **UI/UX**: Toast notifications, modal dialogs, progressive enhancement

### Data Flow Architecture
1. **Webhook → Database**: External leads received and stored
2. **Admin → Assignment**: Lead distribution to team members
3. **User → Processing**: Status updates and activity logging
4. **System → Reporting**: Activity tracking and lead progression analysis

## Deployment Environment

### Production Stack
- **Platform**: Heroku with gunicorn WSGI server
- **Database**: PostgreSQL (essential-0 plan)
- **Repository**: GitHub with Heroku Git integration
- **Branch Strategy**: `main` branch for deployment

### Environment Configuration
- **DATABASE_URL**: PostgreSQL connection string (required)
- **SECRET_KEY**: Flask session encryption key
- **Heroku Apps**: 
  - Development: `eadmanager-fresh-2024-dev`
  - Git remote: `heroku` → `eadmanager-fresh-2024-dev.git`

## Development Dependencies
```
Flask==2.3.3
gunicorn==21.2.0
psycopg2-binary==2.9.7
```

**WSGI Configuration**: `Procfile` runs `gunicorn app:app`

## Critical Implementation Notes

### Hebrew Language Support
- **All UI text in Hebrew**: Forms, buttons, messages, status indicators
- **RTL Layout**: CSS direction: rtl throughout application
- **Data Handling**: Supports Hebrew characters in names, campaign names, form responses

### Security Considerations
- **SQL Injection Protection**: All queries use parameterized statements
- **Session Security**: Secure session configuration with proper secret key
- **Role-Based Access**: Strict permission checking on sensitive operations
- **Password Upgrade Needed**: Current MD5 hashing should be replaced with bcrypt

### Performance Optimizations
- **Database Indexes**: Created on frequently queried columns (status, assigned_to, dates)
- **Efficient Filtering**: Client-side filtering with server-side data loading
- **Connection Management**: Proper database connection handling with cleanup

### Data Integrity
- **Foreign Keys**: Proper referential integrity between tables
- **Trigger Functions**: Automatic updated_at timestamp management
- **Activity Logging**: Comprehensive audit trail for all lead interactions

## Common Development Patterns

### Route Protection
```python
@app.route('/admin/endpoint')
@admin_required
def admin_function():
    # Admin-only functionality
```

### Database Operations
```python
conn = get_db_connection()
cur = conn.cursor()
cur.execute("SELECT * FROM leads WHERE status = %s", (status,))
results = cur.fetchall()
cur.close()
conn.close()
```

### Activity Logging
```python
cur.execute("""
    INSERT INTO lead_activities (lead_id, user_name, activity_type, description)
    VALUES (%s, %s, %s, %s)
""", (lead_id, session.get('username'), 'status_change', description))
```

### Error Handling
```python
try:
    # Database operations
    conn.commit()
    return jsonify({'status': 'success'})
except Exception as e:
    logger.error(f"Operation failed: {e}")
    return jsonify({'status': 'error', 'message': str(e)})
```
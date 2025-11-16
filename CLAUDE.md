# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# LeadsManager - Multi-Tenant Hebrew Lead Management System

## Project Overview
A Flask-based lead management system built for Hebrew-speaking businesses' HR departments. Features multi-tenant customer isolation, Facebook/Instagram lead collection via webhooks, role-based user management, and comprehensive lead tracking with activity logging. Includes React Native mobile companion app.

**Live Development Environment:** https://eadmanager-fresh-2024-dev-f83e51d73e01.herokuapp.com/

## Core Architecture

### Main Application Files
- **`app.py`** (3400+ lines) - Monolithic Flask application containing:
  - Routes: Authentication, leads, users, customers, activities, webhook handling
  - Email system: `send_email_notification()` function using per-customer SMTP
  - Multi-tenant logic: Customer isolation via `customer_id` filtering
  - Status change handling: Requires mandatory notes (lines 1788-1848)
  - Webhook field extraction: Handles multiple field formats including colons (`:`)
- **`database.py`** - PostgreSQL connection management with Heroku URL parsing
- **`templates/unified_lead_manager.html`** - Single component serving all roles (admin/campaign_manager/user)
  - Desktop: Table view (>768px)
  - Mobile: Card view (≤768px)
  - JavaScript class `UnifiedLeadManagerClass` handles all interactions
  - Template variables injected: `{{ session.get("role") }}`, `{{ session.get("username") }}`
  - Key properties: `this.userRole`, `this.username`, `this.leads`, `this.filteredLeads`, `this.selectedLeads`
- **`templates/dashboard_mobile_enhanced.html`** - Mobile web version for campaign managers
  - Dynamic version display using `{{ version }}` template variable
  - Sync all campaigns functionality
  - Lead assignment from detail popups
- **`templates/campaign_manager_dashboard.html`** - PC version for campaign managers

### Multi-Tenant Customer System
**Customer Isolation Architecture:**
- **`customers`** table - Contains customer configurations, webhook URLs, API settings
- **Customer ID filtering** - All leads, users, and activities are filtered by `customer_id`
- **Admin vs Campaign Manager access**:
  - Admins can select which customer to manage via session `selected_customer_id`
  - Campaign managers are restricted to their assigned `customer_id` only
- **Admin customer separation** - Admin users belong to customer_id=0 to separate them from regular customers

### Database Schema (PostgreSQL)
**Core Tables:**
- **`customers`** - Multi-tenant customer configurations with webhook settings, API keys, Zapier integration
- **`leads`** - Lead storage with JSONB raw_data, customer_id isolation, comprehensive status tracking
  - Status values: 'new', 'contacted', 'qualified', 'interested', 'hired', 'rejected', 'closed'
  - Key fields: `id`, `name`, `email`, `phone`, `status`, `assigned_to`, `customer_id`, `raw_data` (JSONB)
- **`users`** - Multi-role user management with customer isolation
  - Roles: 'admin' (full access), 'campaign_manager' (customer-scoped), 'user' (assigned leads only)
- **`lead_activities`** - Complete audit trail for all lead interactions with customer isolation
  - Activity types: 'lead_received', 'status_change', 'assignment', 'call', 'note_added'
  - Status changes include mandatory notes in `description` field

## Development Commands

### Local Development
```bash
# Install dependencies
pip install -r requirements.txt

# Run Flask application locally (requires DATABASE_URL)
python app.py

# Test webhook endpoint locally
curl -X POST http://localhost:5000/webhook \
  -H "Content-Type: application/json" \
  -d '{"name": "Test Lead", "email": "test@example.com", "Phone Number": "+972501234567"}'
```

### Mobile App Development
```bash
# Navigate to mobile app directory
cd mobile_app/

# Install React Native dependencies
npm install

# Start Expo development server
npm start

# Run on specific platform
npm run android    # Android emulator
npm run ios        # iOS simulator
npm run web        # Web browser
```

### Database Operations
```bash
# Connect to database
heroku pg:psql --app eadmanager-fresh-2024-dev

# Run database setup
python setup_database.py

# Check recent leads
curl https://eadmanager-fresh-2024-dev-f83e51d73e01.herokuapp.com/check-recent-webhooks
```

### Deployment Commands

**CRITICAL: Always use deploy.ps1 for deployments**

```bash
# Deploy with commit message (REQUIRED METHOD)
powershell.exe -File deploy.ps1 "Your commit message here"

# What deploy.ps1 does:
# 1. Adds all changed files (git add .)
# 2. Commits with custom message
# 3. Pushes to GitHub (git push origin main)
# 4. Pushes to Heroku (git push heroku main)
# 5. Opens campaign manager page in browser
# 6. Reminds to hard refresh (Ctrl+Shift+R)

# Monitor deployment logs
heroku logs --tail --app eadmanager-fresh-2024-dev

# Check application health
curl https://eadmanager-fresh-2024-dev-f83e51d73e01.herokuapp.com/
```

**Why use deploy.ps1:**
- Keeps GitHub and Heroku in sync
- Consistent deployment process
- Automatically opens app for testing
- Browser caching reminder

## Critical Webhook Field Handling

### Field Name Variations
The webhook handles multiple field name formats from different sources (Zapier, Facebook, forms):

**Phone Fields:**
- With colons: `Phone Number:`, `Email:`, `Full Name:`, `Campaign Name:`
- Hebrew: `טלפון`, `מספר טלפון`, `דוא"ל`, `שם`
- English: `phone`, `phone_number`, `email`, `name`
- Raw fields: `Raw מספר טלפון`, `Raw Email`, `Raw Full Name`

**Field Extraction Priority (app.py lines 691-701):**
```python
name = (lead_data.get('name') or lead_data.get('Full Name') or lead_data.get('Full Name:') ...)
email = (lead_data.get('email') or lead_data.get('Email') or lead_data.get('Email:') ...)
phone = (lead_data.get('phone') or lead_data.get('Phone Number') or lead_data.get('Phone Number:') ...)
```

### Zapier Configuration Requirements
- **Webhook URL**: `https://eadmanager-fresh-2024-dev-f83e51d73e01.herokuapp.com/webhook`
- **Method**: POST with JSON payload
- **Data Type**: `json` (not form)
- **Critical**: Use Data field (not Value field) for field mapping
- **Zap Status**: Must be published/ON (test mode ≠ live data)

## Debug & Maintenance Endpoints

### Lead Management
- `/check-recent-webhooks` - Analyze recent webhook data and field patterns
- `/analyze-field-patterns` - Check field name variations across all campaigns
- `/fix-lead/<id>` - Fix individual lead's missing phone/email/name from raw_data
- `/admin/fix-phone-numbers` - Batch fix all leads with missing phone numbers
- `/debug/lead/<id>` - View detailed lead data including raw_data
- `/debug/search/<term>` - Search for leads by name/email/ID

### System Administration
- `/admin` - Admin dashboard
- `/admin/customers` - Customer management with SMTP configuration
- `/campaign-manager` - Campaign manager dashboard
- `/dashboard` - User dashboard with unified lead manager

### Campaign Sync Operations
- `/admin/campaigns/sync-all-preview` - Preview what will be synced across all active campaigns
- `/admin/campaigns/sync-all` - Execute sync for all active campaigns (respects column mapping, last synced row)
- `/admin/campaigns/<id>/sync` - Sync individual campaign from Google Sheets
- Campaign sync logic:
  - Only syncs campaigns with `active = true`
  - Tracks last synced row per sheet tab using JSONB column (`last_synced_row`)
  - Uses column mapping to extract fields (handles variations: "Phone Number:", "Email:", Hebrew fields)
  - Validates required fields: name AND phone AND email
  - Skips duplicates based on email+campaign combination

## Authentication & Testing

### Test Credentials
- **Admin**: Username: `admin`, Password: `admin123`
- **Campaign Manager**: Check users table for active accounts
- **Regular User**: Check users table for role='user' accounts

### Session Management
- Session stores: `user_id`, `username`, `full_name`, `role`, `selected_customer_id` (admin only)
- Role checking: `session.get('role')` in routes
- Customer filtering: Based on `customer_id` in session

## Mobile Application

### React Native Setup (mobile_app/)
The mobile application is built with Expo and React Native:
- **Framework**: Expo managed workflow
- **Navigation**: React Navigation stack
- **UI**: React Native Paper for Material Design
- **Features**: Contact integration, direct calling, offline support

## Environment Configuration

### Required Environment Variables
```bash
DATABASE_URL  # PostgreSQL connection (auto-set by Heroku)
SECRET_KEY    # Flask session secret (optional, has default)
```

### Heroku Deployment
- **Procfile**: `web: gunicorn app:app`
- **Python**: 3.11 (specified in runtime.txt)
- **Database**: PostgreSQL essential-0 plan
- **Add-ons**: Heroku Postgres

## Common Issues & Solutions

### Browser Caching After Deployment
**Issue**: Changes not visible after deployment
**Solution**: Always hard refresh with Ctrl+Shift+R (or Cmd+Shift+R on Mac)
- Browser caches HTML, CSS, and JavaScript aggressively
- Incognito mode can help test if issue is cache-related
- Version numbers in templates help verify correct version is loaded

### Template Variable Access Issues
**Issue**: JavaScript trying to access `this.role` returns undefined
**Solution**: Use `this.userRole` instead in UnifiedLeadManagerClass
- Template injects `{{ session.get("role") }}` into `this.userRole` property
- Common mistake: using `this.role` instead of `this.userRole`
- Same applies to `this.username` (not `this.user`)

### Webhook Data Not Extracting
**Issue**: Zapier sends fields with colons (`:`) that aren't standard
**Solution**: Webhook now handles `Phone Number:`, `Email:`, `Full Name:` variants

### Missing Phone/Email Icons
**Issue**: Lead data in raw_data but not in main fields
**Solution**: Use `/fix-lead/<id>` or `/admin/fix-phone-numbers` endpoints

### Database Connection
**Issue**: `postgres://` URLs deprecated
**Solution**: Code automatically converts to `postgresql://` format

## Customer Email Configuration

Each customer can configure their own SMTP settings for email notifications:
1. Navigate to `/admin/customers`
2. Edit customer and set:
   - SMTP Server (e.g., smtp.gmail.com)
   - SMTP Port (587)
   - SMTP Username & Password (App Password for Gmail)
   - Sender Email
3. Enable "Email Notifications"

## Multi-Tenant Data Access Pattern

All database queries must include customer filtering:
```python
# Admin users can select customer
selected_customer_id = session.get('selected_customer_id', 1)

# Campaign managers restricted to their customer
if session.get('role') == 'campaign_manager':
    customer_id = session.get('customer_id')
    cur.execute("SELECT * FROM leads WHERE customer_id = %s", (customer_id,))
```

## Key Frontend Patterns

### UnifiedLeadManagerClass Structure
The main JavaScript class managing all lead operations:

```javascript
class UnifiedLeadManagerClass {
    constructor() {
        this.userRole = '{{ session.get("role") }}';  // NOT this.role
        this.username = '{{ session.get("username") }}';
        this.leads = [];
        this.filteredLeads = [];
        this.selectedLeads = new Set();
    }

    // Key methods:
    async loadLeads() - Fetches leads from API
    async viewLead(leadId) - Opens lead detail modal
    async assignLeadFromModal(leadId) - Assigns lead to user from popup
    async loadUsersForAssignment(leadId) - Populates user dropdown
}
```

### Adding Features to Lead Detail Popup
When adding UI elements to the lead detail popup in `unified_lead_manager.html`:

1. **Check role conditionally**: Use `this.userRole` (not `this.role`)
   ```javascript
   ${this.userRole === 'campaign_manager' || this.userRole === 'admin' ? `
       // Your HTML here
   ` : ''}
   ```

2. **Load data after modal opens**: Add logic after `modal.style.display = 'block'` in `showLeadModal()`
   ```javascript
   modal.style.display = 'block';

   if (this.userRole === 'campaign_manager' || this.userRole === 'admin') {
       this.loadUsersForAssignment(lead.id);
   }
   ```

3. **Use unique IDs**: Include lead ID in element IDs to avoid conflicts
   ```javascript
   <select id="assignUserSelect_${lead.id}">
   ```

### Google Sheets Campaign Sync
Campaigns table includes:
- `sheet_url` - Google Sheets URL
- `column_mapping` - JSONB mapping of sheet columns to lead fields
- `last_synced_row` - JSONB tracking last row synced per sheet tab
- `active` - Boolean to control which campaigns sync

Sync process (app.py lines 4352-4600):
1. Extract gid from sheet URL to identify specific tab
2. Fetch CSV export using `{sheet_url}/export?format=csv&gid={gid}`
3. Use column mapping to extract fields from each row
4. Track last synced row in JSONB: `{"gid_123": 45}` means row 45 was last synced for tab with gid=123
5. Only process rows after last synced row
6. Validate required fields (name AND phone AND email)
7. Check for duplicates (email + campaign_name combination)
8. Create lead and activity records
9. Update last_synced_row JSONB
# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# LeadsManager - Multi-Tenant Hebrew Lead Management System

## Project Overview
A Flask-based lead management system built for Hebrew-speaking businesses' HR departments. Features multi-tenant customer isolation, Facebook/Instagram lead collection via webhooks, role-based user management, and comprehensive lead tracking with activity logging. Includes React Native mobile companion app.

**Live Development Environment:** https://eadmanager-fresh-2024-dev-f83e51d73e01.herokuapp.com/

## Core Architecture

### Application Structure
- **`app.py`** - Main Flask application (1000+ lines) with all routes, authentication, lead management, and multi-tenant logic
- **`setup_database.py`** - Database schema initialization with tables for leads, users, customers, and activities  
- **`migrate_add_customer_system.py`** - Migration script that added multi-tenant customer system to existing database
- **`templates/`** - Hebrew RTL interface templates with unified components for consistency across roles
- **`mobile_app/`** - React Native/Expo mobile application for field lead management

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
  - Status flow: 'new' → 'contacted' → 'qualified' → 'interested' → 'hired'/'rejected'/'closed'
  - Fields: `external_lead_id`, `name`, `email`, `phone`, `platform`, `campaign_name`, `status`, `assigned_to`, `customer_id`
- **`users`** - Multi-role user management with customer isolation
  - Roles: 'admin' (full access), 'campaign_manager' (customer-scoped), 'user' (assigned leads only)  
  - Customer scoping: `customer_id` field links users to specific customers
- **`lead_activities`** - Complete audit trail for all lead interactions with customer isolation
  - Activity types: 'lead_received', 'status_change', 'assignment', 'call', 'note_added'

### Role-Based Access Control System
**Authentication Flow:**
1. Session stores: `user_id`, `username`, `full_name`, `role`, `selected_customer_id` (admin only)
2. Route decorators: `@admin_required`, `@campaign_manager_required`, `@login_required`  
3. Data filtering: All queries include customer_id checks based on user role
4. Dynamic permissions: UI elements shown/hidden based on role capabilities

**Role Capabilities:**
- **Admin**: Multi-customer management, user creation across customers, system configuration
- **Campaign Manager**: Single customer scope, user management for their customer only, lead assignment
- **User**: View only assigned leads, update status, add activities

## Development Commands

### Local Development Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Required environment variables
export DATABASE_URL="postgresql://user:pass@localhost/leadmanager" 
export SECRET_KEY="your-secret-key-change-in-production"

# Initialize database schema
python setup_database.py

# Run Flask application
python app.py
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
# Connect to Heroku database
heroku pg:psql --app eadmanager-fresh-2024-dev

# Run customer system migration (if needed)
python migrate_add_customer_system.py

# Check system health
SELECT COUNT(*) FROM leads;
SELECT COUNT(*) FROM customers WHERE active = true;
SELECT COUNT(*) FROM users WHERE active = true;

# Debug customer isolation
SELECT c.name, COUNT(l.id) as lead_count 
FROM customers c 
LEFT JOIN leads l ON c.id = l.customer_id 
GROUP BY c.id, c.name;
```

### Deployment Commands
```bash
# Deploy to development environment
git push heroku main

# Monitor deployment logs
heroku logs --tail --app eadmanager-fresh-2024-dev

# Check application health
curl https://eadmanager-fresh-2024-dev-f83e51d73e01.herokuapp.com/status
```

### Webhook Testing & Development
```bash
# Test webhook endpoint with sample lead data (Linux/Mac)
./test_webhook.sh

# Test webhook endpoint with sample lead data (Windows)
./test_webhook.bat

# Manual webhook test with curl
curl -X POST https://eadmanager-fresh-2024-dev-f83e51d73e01.herokuapp.com/webhook \
  -H "Content-Type: application/json" \
  -d '{"Full Name": "Test User", "Email": "test@example.com", "Raw מספר טלפון": "+972501234567"}'

# Check webhook logs for debugging
# Look for: POST /webhook, "=== WEBHOOK DATA RECEIVED ===", "Lead saved to database"
```

## Technical Architecture

### Multi-Tenant Data Filtering Pattern
All database queries include customer-based filtering:
```python
# Admin users can select customer via session
selected_customer_id = session.get('selected_customer_id', 1)

# Campaign managers restricted to their customer only  
if session.get('role') == 'campaign_manager':
    user_customer_id = session.get('customer_id')
    cur.execute("SELECT * FROM leads WHERE customer_id = %s", (user_customer_id,))
elif session.get('role') == 'admin':
    cur.execute("SELECT * FROM leads WHERE customer_id = %s", (selected_customer_id,))
```

### Unified Component Architecture
**Template Structure:**
- **`unified_lead_manager.html`** - Single powerful component serving all user roles with responsive design:
  - **Desktop (>768px)**: Clean table layout with essential columns (no phone/email/priority columns)
  - **Mobile (≤768px)**: Card-based layout optimized for touch interaction
  - **Auto-adapts** based on screen size and user role capabilities
- **`user_management_component.html`** - Unified user management for admin and campaign manager dashboards
- **Dashboard templates** include the unified component:
  ```html
  {% include 'unified_lead_manager.html' %}
  <!-- Component automatically adapts based on user session role and screen size -->
  ```

### Lead Collection Workflow
1. **Webhook Reception**: `/webhook` endpoint receives Facebook/Instagram leads via Zapier
2. **Customer Routing**: Webhook includes customer identification to route leads to correct tenant
3. **Data Processing**: Extracts contact info, campaign data, form responses into JSONB raw_data
   - **Enhanced Field Mapping**: Supports multiple field variants (`Full Name`/`Raw Full Name`/`שם`)
   - **Custom Form Fields**: Automatically detects and stores non-standard fields in raw_data
   - **Hebrew RTL Support**: Handles Hebrew field names and content properly
4. **Activity Logging**: Creates audit trail entry for lead reception
5. **Assignment Ready**: Leads appear in appropriate customer dashboards for assignment

### Webhook Field Extraction Logic
The webhook handles multiple field formats from Zapier:
```python
# Primary field extraction with fallbacks
name = (lead_data.get('name') or lead_data.get('Full Name') or
        lead_data.get('Raw Full Name') or lead_data.get('שם'))
email = (lead_data.get('email') or lead_data.get('Email') or
         lead_data.get('Raw Email') or lead_data.get('דוא"ל'))
phone = (lead_data.get('phone') or lead_data.get('Raw מספר טלפון') or
         lead_data.get('מספר טלפון'))
```

**Zapier Integration Status:**
- ✅ Webhook URL: `https://eadmanager-fresh-2024-dev-f83e51d73e01.herokuapp.com/webhook`
- ✅ Method: POST with JSON payload
- ⚠️ **Critical**: Zap must be **published/turned ON** to send real data (test mode only validates endpoint)

### Frontend Architecture  
- **Hebrew RTL Design**: All templates use `direction: rtl` with Inter font and comprehensive Hebrew tooltips
- **Responsive Design**: Mobile-first approach with CSS flexbox ordering:
  - **Mobile (≤768px)**: Leads appear first, filters below, headers at bottom
  - **Desktop (>768px)**: Traditional layout with headers moved to bottom for consistency
- **Dual Rendering System**: Same JavaScript renders both table (desktop) and cards (mobile) from identical data
- **Progressive Enhancement**: Core functionality works without JavaScript, enhanced with async features
- **State Persistence**: Filter selections stored in localStorage per user role
- **Modal System**: Unified lead details modals with proper sizing (95% width, 95vh height)
- **WhatsApp Integration**: Proper Israeli phone number formatting (972 country code handling)

## Key Features & Business Logic

### Lead Priority Scoring Algorithm
```javascript
// Automatic priority calculation for assignment recommendations (no longer displayed in main UI)
let priorityScore = 0;
if (leadAge <= 1) priorityScore += 30;        // Fresh leads priority
if (hasPhone && hasEmail) priorityScore += 20; // Complete contact info
if (activityCount === 0) priorityScore += 15; // Untouched leads priority  
if (platform === 'ig') priorityScore += 5;    // Instagram slight priority
// Priority info available in detailed view modal only
```

### Customer Configuration System
- **Webhook URLs**: Each customer has unique webhook endpoint for Zapier integration
- **API Settings**: Customer-specific Facebook/Instagram app configurations stored in JSONB
- **Zapier Integration**: Email-based webhook key system for secure lead routing

### Activity Logging & Audit Trail
All lead interactions automatically logged:
```python
cur.execute("""
    INSERT INTO lead_activities (lead_id, user_name, activity_type, description, customer_id)
    VALUES (%s, %s, %s, %s, %s)
""", (lead_id, session.get('username'), 'status_change', description, customer_id))
```

## Security & Performance Considerations

### Multi-Tenant Security
- **Data Isolation**: All queries include customer_id filtering to prevent cross-tenant data access
- **Role Verification**: Session-based role checking on every route with decorator enforcement
- **Customer Assignment**: Campaign managers cannot access other customers' data via URL manipulation

### Authentication Security  
- **Password Hashing**: Currently MD5 (upgrade to bcrypt recommended for production)
- **Session Management**: Flask sessions with secure secret key configuration
- **SQL Injection Protection**: All queries use parameterized statements

### Performance Optimizations
- **Database Indexing**: Indexes on frequently queried columns (status, customer_id, assigned_to, created_time)
- **Connection Pooling**: Proper database connection management with cleanup
- **Efficient Filtering**: Client-side filtering combined with server-side pagination for large datasets

## Mobile Application Integration

### React Native Architecture
- **Expo Framework**: Cross-platform development with managed workflow
- **Navigation**: React Navigation stack for iOS/Android consistency  
- **UI Library**: React Native Paper for Material Design components
- **Communication**: Direct API integration with Flask backend for real-time lead updates

### Mobile-Specific Features
- **Contact Integration**: `expo-contacts` for importing phone contacts
- **Phone Integration**: `expo-phone` and `react-native-communications` for direct calling
- **Offline Support**: Local state management for poor network conditions

## Deployment Environment

### Heroku Production Stack
- **Platform**: Heroku with gunicorn WSGI server (`Procfile: gunicorn app:app`)
- **Database**: PostgreSQL essential-0 plan with connection pooling
- **Environment Variables**: `DATABASE_URL` (auto), `SECRET_KEY` (manual)
- **Git Integration**: Direct git push deployment to heroku remote

### Dependencies
```
Flask==2.3.3          # Web framework
gunicorn==21.2.0       # WSGI server
psycopg2-binary==2.9.7 # PostgreSQL adapter
Flask-Mail==0.9.1      # Email notifications
pytz==2024.1           # Timezone support
requests==2.31.0       # HTTP requests for external APIs
```

### Critical System Files
- **`app.py`** - Main Flask application with all routes and business logic
- **`database.py`** - DatabaseManager class for PostgreSQL connections with Heroku URL parsing
- **`setup_database.py`** - Database schema initialization script
- **`Procfile`** - Heroku deployment configuration (`web: gunicorn app:app`)
- **`requirements.txt`** - Python dependencies for Heroku deployment

## Common Development Patterns

### Customer-Scoped Database Operations
```python
def get_customer_leads(customer_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM leads 
        WHERE customer_id = %s 
        ORDER BY COALESCE(created_time, received_at) DESC
    """, (customer_id,))
    return cur.fetchall()
```

### Role-Based Route Protection  
```python
@app.route('/admin/customers')
@admin_required  
def manage_customers():
    # Only admins can access customer management
    pass

@app.route('/leads')
@campaign_manager_required
def campaign_leads():
    # Campaign managers and admins can access
    customer_id = get_user_customer_id()  # Automatically scoped
    pass
```

### Unified Component Usage
```html
<!-- All dashboards use the same unified component -->
{% include 'unified_lead_manager.html' %}

<!-- Component automatically adapts based on session role:
- Admin: Full access with customer switching, lead assignment, user management
- Campaign Manager: Customer-scoped access with lead assignment capabilities  
- User: View assigned leads only with status update capabilities
-->
```

### Multi-Tenant Session Management
```python
# Admin can switch between customers
if session.get('role') == 'admin':
    session['selected_customer_id'] = request.form.get('customer_id')

# Campaign managers locked to their customer
elif session.get('role') == 'campaign_manager':  
    customer_id = session.get('customer_id')  # Read-only
```

## Current UI/UX State (Post-Optimization)

### Interface Cleanup (January 2025)
**Desktop Table Columns (>768px):**
- ☑️ **Checkbox** (selection)
- 🔧 **Actions** (call, WhatsApp, email ✉️, view, assign buttons)  
- 📌 **Status** (current stage with Hebrew labels)
- 👤 **Name** (lead identifier)
- 🎯 **Campaign** (source - expanded to 30 chars)
- 👥 **Assigned To** (ownership)
- 📅 **Date** (timing)

**Mobile Cards (≤768px):**
- **Header**: Lead name + Status badge
- **Campaign**: Enlarged (16px font) + expanded (40 chars)
- **Date**: Separate line  
- **Assignment**: Separate line below with margin-top spacing
- **Actions**: Touch-friendly buttons (44px min height)

**Removed Fields (Both Platforms):**
- ❌ Phone number display (accessible via 📞 call button)
- ❌ Email display (accessible via ✉️ email button)  
- ❌ Priority scores (available in detailed modal view)

### Hebrew Tooltips System
All interface elements include comprehensive Hebrew tooltips with:
- Dynamic lead names in tooltips
- Contact info shown on hover
- Action-specific guidance
- Priority level explanations
- Role-based contextual help

### WhatsApp Integration
- **Phone Formatting**: `formatPhoneForWhatsApp()` function handles Israeli numbers
- **Supported Formats**: 050-1234567, 0501234567, 972501234567, 501234567
- **Auto Country Code**: Adds/maintains 972 prefix correctly

### Email Notification System (September 2025)
**Two-Step Email Notifications:**
- **Campaign Manager Alerts**: Receive emails when new leads arrive from Facebook/Instagram
- **User Assignment Alerts**: Users receive emails when leads are assigned to them
- **Customer-Managed Settings**: Each customer configures their own SMTP settings and sender email
- **Hebrew Email Templates**: Beautiful HTML emails with proper RTL formatting and Israel timezone

**Email Configuration:**
```python
# Customer email settings stored per customer in database
customers table: sender_email, smtp_server, smtp_port, smtp_username, smtp_password, email_notifications_enabled, timezone

# Email types
send_email_notification(customer_id, to_email, to_username, lead_name, ..., email_type="new_lead"|"assignment")
```

**Admin Email Management:**
- `/admin/customers` - Configure email settings per customer with tooltips
- Required: Gmail App Password (not regular password), sender email, SMTP credentials
- Email status display shows if notifications are enabled: "📧 התראות אימייל פעילות"

### Mobile UX Enhancements (Version 1.6)
**Touch Optimization:**
- **44px minimum touch targets** (iOS/Android standard)
- **Status indicator bars** at top of lead cards (green=new, blue=contacted, etc.)
- **Enhanced card shadows** and modern rounded corners (16px)
- **Touch feedback** with scale animations and visual states
- **Haptic feedback simulation** using navigator.vibrate()

**Mobile-First Design Pattern:**
- Cards displayed on mobile (≤768px), table on desktop (>768px)
- Header positioned at bottom for mobile thumb accessibility
- Action buttons with proper spacing and visual feedback
- Status badges with color coding for quick visual identification

### Development URLs
- **Main Dashboard**: `/dashboard` (standard user interface)
- **Enhanced Mobile**: `/mobile-dashboard` (demonstration of modern mobile patterns)
- **Campaign Manager**: `/campaign-manager` (campaign manager specific interface)
- **Admin Panel**: `/admin` (administrative functions)
- **Customer Management**: `/admin/customers` (email settings, customer configuration)
- **Webhook Endpoint**: `/webhook` (receives Zapier lead data)
- **Debug Routes**: `/debug/search/<term>`, `/debug/lead/<id>`, `/debug/session`

## Common Troubleshooting

### Webhook Issues
**Symptom**: Zapier test passes but no leads appear in dashboard
- ✅ Check: Is the Zap published/turned ON? (Test mode ≠ Live mode)
- ✅ Check: Look for `POST /webhook` entries in Heroku logs
- ✅ Check: Verify webhook URL is exactly `https://eadmanager-fresh-2024-dev-f83e51d73e01.herokuapp.com/webhook`

**Expected webhook logs:**
```
POST /webhook HTTP/1.1" 200
INFO:app:=== WEBHOOK DATA RECEIVED ===
INFO:app:Custom form field: כמות האנשים שצפויה להגיע = 50-60
INFO:app:Lead saved to database: [Name] ([Email]) - ID: [ID]
```

### Database Connection Issues
**Symptom**: `ModuleNotFoundError: No module named 'database'`
- ✅ Ensure `database.py` exists with `DatabaseManager` class
- ✅ Check `DATABASE_URL` environment variable is set
- ✅ Verify `psycopg2-binary` is in requirements.txt

### Role Permission Issues
**Symptom**: Users can't access expected features
- ✅ Check session role: `session.get('role')` vs database `user_role` field
- ✅ Verify customer_id filtering in queries
- ✅ Confirm route decorators: `@admin_required`, `@campaign_manager_required`

# important-instruction-reminders
Do what has been asked; nothing more, nothing less.
NEVER create files unless they're absolutely necessary for achieving your goal.
ALWAYS prefer editing an existing file to creating a new one.
NEVER proactively create documentation files (*.md) or README files. Only create documentation files if explicitly requested by the User.
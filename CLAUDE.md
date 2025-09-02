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
- **`lead_management_component.html`** - Reusable lead table with role-based features (assignment, editing, filtering)
- **`user_management_component.html`** - Unified user management for admin and campaign manager dashboards
- **Dashboard templates** include components with role-specific parameters:
  ```html
  {% include 'lead_management_component.html' %}
  <!-- Component automatically adapts based on user session role -->
  ```

### Lead Collection Workflow
1. **Webhook Reception**: `/webhook` endpoint receives Facebook/Instagram leads via Zapier
2. **Customer Routing**: Webhook includes customer identification to route leads to correct tenant  
3. **Data Processing**: Extracts contact info, campaign data, form responses into JSONB raw_data
4. **Activity Logging**: Creates audit trail entry for lead reception
5. **Assignment Ready**: Leads appear in appropriate customer dashboards for assignment

### Frontend Architecture  
- **Hebrew RTL Design**: All templates use `direction: rtl` with Inter font
- **Progressive Enhancement**: Core functionality works without JavaScript, enhanced with async features
- **State Persistence**: Filter selections stored in localStorage per user role
- **Modal System**: Unified lead details and user management modals across dashboards
- **Responsive Design**: Mobile-first CSS Grid/Flexbox with horizontal scrolling tables

## Key Features & Business Logic

### Lead Priority Scoring Algorithm
```javascript
// Automatic priority calculation for assignment recommendations
let priorityScore = 0;
if (leadAge <= 1) priorityScore += 30;        // Fresh leads priority
if (hasPhone && hasEmail) priorityScore += 20; // Complete contact info
if (activityCount === 0) priorityScore += 15; // Untouched leads priority  
if (platform === 'ig') priorityScore += 5;    // Instagram slight priority
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
```

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
<!-- Admin dashboard - can assign leads, edit users -->
{% include 'lead_management_component.html' with canAssign=true, canEdit=true %}

<!-- Campaign manager - can assign leads, limited user editing -->  
{% include 'user_management_component.html' with canAssign=true, canEdit=false %}

<!-- User dashboard - view only assigned leads -->
{% include 'lead_management_component.html' with canAssign=false, canEdit=false %}
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
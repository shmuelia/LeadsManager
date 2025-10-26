import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, request, jsonify, render_template, session, redirect, url_for, flash, Response, send_from_directory
from datetime import datetime
import pytz
import json
import logging
import hashlib
from functools import wraps
import time
import threading
from queue import Queue
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import psycopg2
import psycopg2.extras
from database import db_manager
import gspread
from google.oauth2.service_account import Credentials
import re

# Database configuration
DATABASE_URL = os.environ.get('DATABASE_URL')

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-change-in-production')

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Email configuration
SMTP_SERVER = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
SMTP_USERNAME = os.environ.get('SMTP_USERNAME')
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD')
FROM_EMAIL = os.environ.get('FROM_EMAIL', SMTP_USERNAME)

# Notification system for real-time updates
notification_queues = {}  # Dictionary to store notification queues by customer_id

# Google Sheets API helper functions
def get_google_sheets_client():
    """Initialize Google Sheets client with service account credentials"""
    try:
        # Get credentials from environment variable (JSON string)
        creds_json = os.environ.get('GOOGLE_SHEETS_CREDENTIALS')
        if not creds_json:
            logger.warning("GOOGLE_SHEETS_CREDENTIALS not set, tab names won't be fetched")
            return None
        
        # Parse JSON credentials
        creds_dict = json.loads(creds_json)
        
        # Define the scopes
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets.readonly',
            'https://www.googleapis.com/auth/drive.readonly'
        ]
        
        # Create credentials
        credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        
        # Return gspread client
        return gspread.authorize(credentials)
    except Exception as e:
        logger.error(f"Error initializing Google Sheets client: {e}")
        return None

def get_sheet_tab_names(spreadsheet_id):
    """Fetch all tab names from a Google Spreadsheet
    
    Args:
        spreadsheet_id: The spreadsheet ID from the URL
    
    Returns:
        dict: {gid: tab_name} mapping, or None if failed
    """
    try:
        client = get_google_sheets_client()
        if not client:
            return None
        
        # Open spreadsheet
        spreadsheet = client.open_by_key(spreadsheet_id)
        
        # Get all worksheets and create gid -> name mapping
        tab_names = {}
        for worksheet in spreadsheet.worksheets():
            gid = worksheet.id
            name = worksheet.title
            tab_names[str(gid)] = name
            logger.info(f"Found tab: {name} (gid={gid})")
        
        return tab_names
    except Exception as e:
        logger.error(f"Error fetching sheet tab names: {e}")
        return None

def get_tab_name_for_gid(spreadsheet_id, gid):
    """Get the tab name for a specific gid
    
    Args:
        spreadsheet_id: The spreadsheet ID
        gid: The tab gid
    
    Returns:
        str: Tab name, or None if not found
    """
    tab_names = get_sheet_tab_names(spreadsheet_id)
    if tab_names:
        return tab_names.get(str(gid), f"gid_{gid}")
    return f"gid_{gid}"

def get_db_connection():
    """Get database connection using centralized DatabaseManager"""
    return db_manager.get_connection()

def init_database():
    """Initialize database tables if they don't exist"""
    try:
        conn = get_db_connection()
        if not conn:
            logger.warning("Skipping database initialization - no connection")
            return False
            
        cur = conn.cursor()
        
        # Auto-migrate: Add phone and email notification columns if they don't exist
        try:
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR(20)")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS whatsapp_notifications BOOLEAN DEFAULT true")
            logger.info("Auto-migration: Added phone columns to users table")
        except Exception as e:
            logger.info(f"Phone columns migration (probably already exist): {e}")
            
        # Auto-migrate: Add email notification settings to customers table
        try:
            cur.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS sender_email VARCHAR(255)")
            cur.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS smtp_server VARCHAR(255) DEFAULT 'smtp.gmail.com'")
            cur.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS smtp_port INTEGER DEFAULT 587")
            cur.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS smtp_username VARCHAR(255)")
            cur.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS smtp_password VARCHAR(255)")
            cur.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS email_notifications_enabled BOOLEAN DEFAULT false")
            logger.info("Auto-migration: Added email notification columns to customers table")
        except Exception as e:
            logger.info(f"Email notification columns migration (probably already exist): {e}")
        
        # Create leads table
        # Create leads table
        cur.execute("""
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
        """)
        
        # Create users table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(100) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                full_name VARCHAR(255) NOT NULL,
                email VARCHAR(255),
                role VARCHAR(50) DEFAULT 'user',
                department VARCHAR(100),
                active BOOLEAN DEFAULT true,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # Create activities table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS lead_activities (
                id SERIAL PRIMARY KEY,
                lead_id INTEGER REFERENCES leads(id) ON DELETE CASCADE,
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
        
        # Create notifications table for real-time notifications history
        logger.info("Creating notifications table...")
        try:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS notifications (
                    id SERIAL PRIMARY KEY,
                    customer_id INTEGER,
                    lead_id INTEGER REFERENCES leads(id) ON DELETE CASCADE,
                    notification_type VARCHAR(50) NOT NULL,
                    title VARCHAR(255) NOT NULL,
                    message TEXT NOT NULL,
                    data JSONB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    read_by_users JSONB DEFAULT '[]'::jsonb
                );
            """)
            logger.info("Notifications table created successfully")
        except Exception as e:
            logger.error(f"Error creating notifications table: {e}")
            # Continue anyway - don't fail the entire initialization
        
        # Insert default admin user if not exists
        cur.execute("""
            INSERT INTO users (username, password_hash, full_name, email, role, department)
            VALUES ('admin', %s, 'System Administrator', 'admin@leadmanager.com', 'admin', 'management')
            ON CONFLICT (username) DO NOTHING;
        """, (hash_password('admin123'),))
        
        conn.commit()
        cur.close()
        conn.close()
        logger.info("Database tables initialized successfully")
        return True
        
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
        return False

# Authentication decorators
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or session.get('role') != 'admin':
            flash('נדרשות הרשאות מנהל לצפייה בדף זה')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

def campaign_manager_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or session.get('role') not in ['admin', 'campaign_manager']:
            flash('גישה מוגבלת למנהלי קמפיין ומנהלים בלבד')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

def hash_password(password):
    """Simple MD5 hash for passwords (upgrade to bcrypt in production)"""
    return hashlib.md5(password.encode()).hexdigest()

# Authentication routes
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')
    
    username = request.form.get('username')
    password = request.form.get('password')
    
    if not username or not password:
        flash('שם משתמש וסיסמה נדרשים')
        return render_template('login.html')
    
    try:
        conn = get_db_connection()
        if not conn:
            flash('שגיאה בהתחברות למסד הנתונים')
            return render_template('login.html')
        
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT u.id, u.username, u.full_name, u.role, u.active, u.customer_id, c.name as customer_name
            FROM users u
            LEFT JOIN customers c ON u.customer_id = c.id
            WHERE u.username = %s AND u.password_hash = %s AND u.active = true
        """, (username, hash_password(password)))
        
        user = cur.fetchone()
        cur.close()
        conn.close()
        
        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['full_name'] = user['full_name']
            session['role'] = user['role']
            
            # Set customer context if user has an assigned customer
            if user['customer_id']:
                session['customer_id'] = user['customer_id']
                session['selected_customer_id'] = user['customer_id'] 
                session['selected_customer_name'] = user['customer_name']
            else:
                # Default to customer #1 if no customer assigned
                session['customer_id'] = 1
                session['selected_customer_id'] = 1
                session['selected_customer_name'] = 'מאפיית משמרות - לקוח ברירת מחדל'
            
            flash(f'ברוך הבא, {user["full_name"]}!')
            
            # Check if there's a next URL to redirect to
            next_page = request.args.get('next')
            
            # Validate next URL for security (must be relative)
            if next_page and next_page.startswith('/') and not next_page.startswith('//'):
                return redirect(next_page)
            
            # Default redirect based on role
            if user['role'] == 'admin':
                return redirect(url_for('admin_dashboard'))
            elif user['role'] == 'campaign_manager':
                return redirect(url_for('campaign_manager_dashboard'))
            else:
                return redirect(url_for('dashboard'))
        else:
            flash('שם משתמש או סיסמה שגויים')
            return render_template('login.html')
            
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        flash('שגיאה בהתחברות')
        return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('התנתקת בהצלחה')
    return redirect(url_for('login'))

@app.route('/')
def home():
    """Home page - redirect to login if not authenticated"""
    if 'user_id' in session:
        if session.get('role') == 'admin':
            return redirect(url_for('admin_dashboard'))
        else:
            return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/status')
def server_status():
    """Public server status endpoint"""
    try:
        conn = get_db_connection()
        if conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM leads")
            total_leads = cur.fetchone()[0]
            cur.close()
            conn.close()
            db_status = "connected"
        else:
            total_leads = 0
            db_status = "no database"
    except Exception as e:
        logger.error(f"Database query error: {e}")
        total_leads = 0
        db_status = f"error: {str(e)}"
    
    return jsonify({
        'status': 'active',
        'message': 'LeadsManager Webhook Server (Hybrid)',
        'database': db_status,
        'leads_received': total_leads,
        'timestamp': datetime.now().isoformat(),
        'database_url_set': bool(DATABASE_URL)
    })

@app.route('/admin/fix-admin-customer')
@admin_required
def fix_admin_customer():
    """Fix admin user customer assignment - create admin company and assign admins to it"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available'}), 500
            
        cur = conn.cursor()
        
        # First, create or get the admin company (customer_id = 0)
        cur.execute("""
            INSERT INTO customers (id, name, webhook_url, zapier_webhook_key, active)
            VALUES (0, 'מערכת ניהול - מנהלים', '', '', true)
            ON CONFLICT (id) DO UPDATE SET
                name = 'מערכת ניהול - מנהלים',
                active = true
        """)
        
        # Update admin users to belong to the admin company (customer_id = 0)
        cur.execute("""
            UPDATE users 
            SET customer_id = 0 
            WHERE role = 'admin'
        """)
        
        admin_count = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({
            'status': 'success',
            'message': f'Created admin company and updated {admin_count} admin users',
            'admin_users_updated': admin_count
        })
        
    except Exception as e:
        logger.error(f"Fix admin customer error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/debug/session')
@login_required
def debug_session():
    """Debug endpoint to check session data and user info"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available'}), 500
            
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # Get current user info from database
        user_id = session.get('user_id')
        if user_id:
            cur.execute("""
                SELECT u.id, u.username, u.full_name, u.role, u.customer_id, c.name as customer_name
                FROM users u
                LEFT JOIN customers c ON u.customer_id = c.id
                WHERE u.id = %s
            """, (user_id,))
            user_db = cur.fetchone()
        else:
            user_db = None
            
        # Get users for this customer
        customer_id = session.get('selected_customer_id')
        if customer_id:
            cur.execute("""
                SELECT u.id, u.username, u.full_name, u.role, u.active, u.customer_id
                FROM users u
                WHERE u.customer_id = %s
            """, (customer_id,))
            customer_users = cur.fetchall()
        else:
            customer_users = []
            
        cur.close()
        conn.close()
        
        return jsonify({
            'session_data': {
                'user_id': session.get('user_id'),
                'username': session.get('username'),
                'full_name': session.get('full_name'),
                'role': session.get('role'),
                'selected_customer_id': session.get('selected_customer_id'),
                'selected_customer_name': session.get('selected_customer_name')
            },
            'user_in_database': dict(user_db) if user_db else None,
            'customer_users': [dict(u) for u in customer_users],
            'customer_users_count': len(customer_users)
        })
        
    except Exception as e:
        logger.error(f"Debug session error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/check-recent-webhooks')
def check_recent_webhooks():
    """Check recent leads to see what webhook data was received"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available'}), 500

        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Get the 5 most recent leads with their raw_data
        cur.execute("""
            SELECT id, name, email, phone, created_time, raw_data
            FROM leads
            ORDER BY id DESC
            LIMIT 5
        """)

        recent_leads = cur.fetchall()
        results = []

        for lead in recent_leads:
            raw_data = lead['raw_data']
            if isinstance(raw_data, str):
                try:
                    raw_data = json.loads(raw_data)
                except:
                    pass

            # Check for phone fields in raw_data
            phone_fields_found = {}
            if raw_data and isinstance(raw_data, dict):
                for key in raw_data.keys():
                    if 'phone' in key.lower() or 'טלפון' in key:
                        phone_fields_found[key] = raw_data[key]

            results.append({
                'id': lead['id'],
                'name': lead['name'],
                'email': lead['email'],
                'phone_in_db': lead['phone'],
                'has_phone': bool(lead['phone']),
                'phone_fields_in_raw_data': phone_fields_found,
                'all_raw_data_fields': list(raw_data.keys()) if raw_data else []
            })

        cur.close()
        conn.close()

        return jsonify({
            'status': 'success',
            'message': 'Recent leads analysis',
            'leads': results
        })

    except Exception as e:
        logger.error(f"Error checking recent webhooks: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/analyze-field-patterns')
def analyze_field_patterns():
    """Analyze field name patterns across all leads"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available'}), 500

        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Get all leads with raw_data
        cur.execute("""
            SELECT id, raw_data, campaign_name
            FROM leads
            WHERE raw_data IS NOT NULL
        """)

        leads = cur.fetchall()

        # Track field patterns
        field_patterns = {
            'phone': set(),
            'email': set(),
            'name': set(),
            'campaign': set()
        }

        # Patterns by campaign
        campaign_patterns = {}

        # Keywords to identify field types
        phone_keywords = ['phone', 'טלפון', 'mobile', 'cell', 'tel']
        email_keywords = ['email', 'mail', 'דואר', 'דוא"ל', '@']
        name_keywords = ['name', 'שם', 'full']
        campaign_keywords = ['campaign', 'קמפיין', 'form']

        for lead in leads:
            raw_data = lead['raw_data']
            if isinstance(raw_data, str):
                try:
                    raw_data = json.loads(raw_data)
                except:
                    continue

            if not raw_data or not isinstance(raw_data, dict):
                continue

            campaign = lead.get('campaign_name') or 'Unknown'
            if campaign not in campaign_patterns:
                campaign_patterns[campaign] = {
                    'phone': set(),
                    'email': set(),
                    'name': set()
                }

            for field_name in raw_data.keys():
                if not field_name or field_name.startswith('custom_'):
                    continue

                field_lower = field_name.lower()

                # Categorize the field
                if any(keyword in field_lower for keyword in phone_keywords):
                    field_patterns['phone'].add(field_name)
                    campaign_patterns[campaign]['phone'].add(field_name)
                elif any(keyword in field_lower for keyword in email_keywords):
                    field_patterns['email'].add(field_name)
                    campaign_patterns[campaign]['email'].add(field_name)
                elif any(keyword in field_lower for keyword in name_keywords):
                    field_patterns['name'].add(field_name)
                    campaign_patterns[campaign]['name'].add(field_name)
                elif any(keyword in field_lower for keyword in campaign_keywords):
                    field_patterns['campaign'].add(field_name)

        cur.close()
        conn.close()

        # Convert sets to lists for JSON serialization
        result = {
            'global_patterns': {
                'phone': sorted(list(field_patterns['phone'])),
                'email': sorted(list(field_patterns['email'])),
                'name': sorted(list(field_patterns['name'])),
                'campaign': sorted(list(field_patterns['campaign']))
            },
            'campaign_specific': {}
        }

        # Only include campaigns with variations
        for campaign, patterns in campaign_patterns.items():
            if any(patterns[field_type] for field_type in ['phone', 'email', 'name']):
                result['campaign_specific'][campaign] = {
                    'phone': sorted(list(patterns['phone'])),
                    'email': sorted(list(patterns['email'])),
                    'name': sorted(list(patterns['name']))
                }

        # Add recommendations
        recommendations = []
        if len(field_patterns['phone']) > 3:
            recommendations.append(f"Found {len(field_patterns['phone'])} phone field variations - consider field mapping")
        if len(field_patterns['email']) > 3:
            recommendations.append(f"Found {len(field_patterns['email'])} email field variations")
        if len(field_patterns['name']) > 3:
            recommendations.append(f"Found {len(field_patterns['name'])} name field variations")

        result['recommendations'] = recommendations
        result['total_variations'] = {
            'phone': len(field_patterns['phone']),
            'email': len(field_patterns['email']),
            'name': len(field_patterns['name'])
        }

        return jsonify(result)

    except Exception as e:
        logger.error(f"Error analyzing field patterns: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/fix-lead/<int:lead_id>')
def fix_specific_lead(lead_id):
    """Fix a specific lead's phone number from raw_data"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available'}), 500

        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Get the lead
        cur.execute("""
            SELECT id, name, email, phone, raw_data
            FROM leads
            WHERE id = %s
        """, (lead_id,))
        lead = cur.fetchone()

        if not lead:
            return jsonify({'error': f'Lead #{lead_id} not found'}), 404

        result = {
            'lead_id': lead_id,
            'name': lead['name'],
            'email': lead['email'],
            'phone_before': lead['phone']
        }

        raw_data = lead['raw_data']
        if isinstance(raw_data, str):
            raw_data = json.loads(raw_data)

        # Look for phone, name, and email in raw_data (including fields with colons)
        phone = None
        name = lead['name']
        email = lead['email']

        # Check for phone
        phone_fields = ['Phone Number:', 'Phone Number', 'phone', 'phone_number', 'טלפון', 'מספר טלפון', 'Raw מספר טלפון']
        for field in phone_fields:
            if field in raw_data and raw_data[field]:
                phone = raw_data[field]
                result['phone_found_in'] = field
                break

        # Check for name if missing
        if not name:
            name_fields = ['Full Name:', 'Full Name', 'name', 'full_name', 'שם', 'Raw Full Name']
            for field in name_fields:
                if field in raw_data and raw_data[field]:
                    name = raw_data[field]
                    result['name_found_in'] = field
                    break

        # Check for email if missing
        if not email:
            email_fields = ['Email:', 'Email', 'email', 'Raw Email', 'דוא"ל']
            for field in email_fields:
                if field in raw_data and raw_data[field]:
                    email = raw_data[field]
                    result['email_found_in'] = field
                    break

        # Update the lead
        updates_made = []
        if phone and not lead['phone']:
            cur.execute("UPDATE leads SET phone = %s WHERE id = %s", (phone, lead_id))
            updates_made.append(f"phone={phone}")
        if name and not lead['name']:
            cur.execute("UPDATE leads SET name = %s WHERE id = %s", (name, lead_id))
            updates_made.append(f"name={name}")
        if email and not lead['email']:
            cur.execute("UPDATE leads SET email = %s WHERE id = %s", (email, lead_id))
            updates_made.append(f"email={email}")

        if updates_made:
            conn.commit()
            result['status'] = 'fixed'
            result['updates'] = updates_made
            result['message'] = f'Updated: {", ".join(updates_made)}'
        else:
            result['status'] = 'no_updates_needed'
            result['message'] = 'All fields already set or no data found in raw_data'

        cur.close()
        conn.close()
        return jsonify(result)

    except Exception as e:
        logger.error(f"Error fixing lead {lead_id}: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/fix-lead-382')
def fix_lead_382():
    """Public endpoint to fix lead #382 phone number"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available'}), 500

        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Check current state of lead #382
        cur.execute("""
            SELECT id, name, phone, raw_data
            FROM leads
            WHERE id = 382
        """)
        lead = cur.fetchone()

        if not lead:
            return jsonify({'error': 'Lead #382 not found'}), 404

        result = {
            'lead_id': 382,
            'name': lead['name'],
            'phone_before': lead['phone']
        }

        raw_data = lead['raw_data']
        if isinstance(raw_data, str):
            raw_data = json.loads(raw_data)

        # Look for phone in raw_data
        phone = None
        phone_fields = ['Phone Number', 'phone', 'phone_number', 'טלפון', 'מספר טלפון', 'Raw מספר טלפון']

        for field in phone_fields:
            if field in raw_data and raw_data[field]:
                phone = raw_data[field]
                result['phone_found_in'] = field
                break

        if phone and (not lead['phone'] or lead['phone'] == ''):
            # Update the phone field
            cur.execute("""
                UPDATE leads
                SET phone = %s
                WHERE id = 382
            """, (phone,))
            conn.commit()

            result['status'] = 'fixed'
            result['phone_after'] = phone
            result['message'] = f'Phone updated from raw_data to: {phone}'
        elif lead['phone']:
            result['status'] = 'already_set'
            result['phone_after'] = lead['phone']
            result['message'] = f'Phone already set to: {lead["phone"]}'
        else:
            result['status'] = 'no_phone_found'
            result['message'] = 'No phone number found in raw_data'
            result['raw_data_keys'] = list(raw_data.keys()) if raw_data else []

        cur.close()
        conn.close()
        return jsonify(result)

    except Exception as e:
        logger.error(f"Error fixing lead 382: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    """Receive Facebook leads from Zapier or Meta directly"""
    if request.method == 'GET':
        # Handle Meta webhook verification
        verify_token = "leadmanager2024"  # Set your verify token here
        
        mode = request.args.get('hub.mode')
        token = request.args.get('hub.verify_token')
        challenge = request.args.get('hub.challenge')
        
        # Meta webhook verification
        if mode and token:
            if mode == 'subscribe' and token == verify_token:
                logger.info('Meta webhook verified successfully')
                return challenge, 200
            else:
                logger.warning('Meta webhook verification failed - token mismatch')
                return 'Forbidden', 403
        
        # Regular GET request (not Meta verification)
        return jsonify({
            'message': 'Webhook endpoint ready',
            'method': 'POST requests only',
            'content_type': 'application/json',
            'status': 'ready',
            'database_available': bool(DATABASE_URL),
            'meta_webhook_ready': True
        })
    
    try:
        lead_data = request.get_json()
        
        if not lead_data:
            logger.warning("No JSON data received")
            return jsonify({'error': 'No data received'}), 400
        
        # Handle Meta's direct webhook format
        if 'entry' in lead_data and isinstance(lead_data.get('entry'), list):
            # This is a direct Meta webhook
            logger.info("Received direct Meta webhook")
            processed_leads = 0
            
            for entry in lead_data.get('entry', []):
                for change in entry.get('changes', []):
                    if change.get('field') == 'leadgen':
                        value = change.get('value', {})
                        lead_id = value.get('leadgen_id')
                        form_id = value.get('form_id')
                        created_time = value.get('created_time')
                        
                        # Meta sends minimal data, we'd need to fetch full lead details
                        # For now, log it
                        logger.info(f"Meta lead received: ID={lead_id}, Form={form_id}")
                        processed_leads += 1
                        
                        # TODO: Use Graph API to fetch full lead details
                        # This requires Facebook app access token
            
            return jsonify({
                'status': 'success',
                'message': f'Received {processed_leads} leads from Meta',
                'note': 'Full lead fetch requires Graph API access'
            }), 200
        
        
        # Handle Google Sheets webhook format
        if lead_data.get('source') == 'google_sheets':
            logger.info("=== GOOGLE SHEETS WEBHOOK RECEIVED ===")
            logger.info(f"Row number: {lead_data.get('row_number')}")
            logger.info(f"Total fields: {len(lead_data)}")
            logger.info(f"Field names: {list(lead_data.keys())}")
            
            # Look up campaign from database based on sheet_id
            sheet_id = lead_data.get('sheet_id')
            if sheet_id:
                try:
                    conn_campaign = get_db_connection()
                    if conn_campaign:
                        cur_campaign = conn_campaign.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                        cur_campaign.execute("""
                            SELECT campaign_name, customer_id 
                            FROM campaigns 
                            WHERE sheet_id = %s AND active = true
                            LIMIT 1
                        """, (sheet_id,))
                        campaign_info = cur_campaign.fetchone()
                        cur_campaign.close()
                        conn_campaign.close()
                        
                        if campaign_info:
                            campaign_from_sheet = campaign_info['campaign_name']
                            customer_id_from_sheet = campaign_info['customer_id']
                            logger.info(f"Found campaign from database: {campaign_from_sheet} (Customer: {customer_id_from_sheet})")
                            
                            # Set campaign name and customer_id
                            lead_data['campaign_name'] = campaign_from_sheet
                            lead_data['קמפיין'] = campaign_from_sheet
                            lead_data['_customer_id'] = customer_id_from_sheet  # Store for later use
                        else:
                            # Auto-create campaign if it doesn't exist
                            logger.info(f"No campaign found for sheet_id: {sheet_id}, creating automatically...")
                            try:
                                conn_create = get_db_connection()
                                if conn_create:
                                    cur_create = conn_create.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                                    
                                    # Create campaign with sheet_id as the name (user can rename later)
                                    default_campaign_name = f"Google Sheet: {sheet_id}"
                                    default_customer_id = 1  # Default to customer #1
                                    
                                    cur_create.execute("""
                                        INSERT INTO campaigns (customer_id, campaign_name, campaign_type, sheet_id, active)
                                        VALUES (%s, %s, 'google_sheets', %s, true)
                                        ON CONFLICT (customer_id, campaign_name) DO NOTHING
                                        RETURNING id, campaign_name, customer_id
                                    """, (default_customer_id, default_campaign_name, sheet_id))
                                    
                                    new_campaign = cur_create.fetchone()
                                    conn_create.commit()
                                    cur_create.close()
                                    conn_create.close()
                                    
                                    if new_campaign:
                                        campaign_from_sheet = new_campaign['campaign_name']
                                        customer_id_from_sheet = new_campaign['customer_id']
                                        logger.info(f"✅ Auto-created campaign: {campaign_from_sheet} (ID: {new_campaign['id']})")
                                        
                                        # Set campaign name and customer_id
                                        lead_data['campaign_name'] = campaign_from_sheet
                                        lead_data['קמפיין'] = campaign_from_sheet
                                        lead_data['_customer_id'] = customer_id_from_sheet
                                    else:
                                        logger.warning(f"Campaign creation returned no result for sheet_id: {sheet_id}")
                            except Exception as create_error:
                                logger.error(f"Error auto-creating campaign: {create_error}")
                except Exception as e:
                    logger.error(f"Error looking up campaign: {e}")
            
            # Google Sheets data is already in the correct format
            # Continue processing with the existing lead extraction logic below
            logger.info("Processing Google Sheets lead data...")
        
        # Otherwise, process as Zapier format (existing code continues...)
        
        # Log ALL fields received from Zapier for debugging
        logger.info(f"=== WEBHOOK DATA RECEIVED ===")
        logger.info(f"Total fields: {len(lead_data)}")
        logger.info(f"Field names: {list(lead_data.keys())}")

        # Log specific phone-related fields for debugging (including with colons)
        phone_fields_to_check = ['phone', 'Phone Number', 'Phone Number:', 'phone_number', 'טלפון', 'מספר טלפון', 'Raw מספר טלפון']
        for field in phone_fields_to_check:
            if field in lead_data:
                logger.info(f"Found phone field '{field}': {lead_data[field]}")

        # Log if we have any field containing 'phone' (case-insensitive)
        phone_related_fields = [k for k in lead_data.keys() if 'phone' in k.lower()]
        if phone_related_fields:
            logger.info(f"All phone-related fields: {phone_related_fields}")
        
        # Prepare clean lead data with numbered custom fields
        clean_lead_data = dict(lead_data)  # Create a copy of original data

        # Define standard fields to exclude from custom questions (including with colons)
        standard_fields = {
            'id', 'ID', 'name', 'email', 'phone', 'Phone Number', 'Phone Number:', 'platform', 'Platform',
            'campaign_name', 'Campaign Name', 'Campaign Name:', 'form_name', 'Form Name', 'lead_source',
            'created_time', 'Created Time', 'Create Time:', 'full_name', 'Full Name', 'Full Name:',
            'phone_number', 'Page Id', 'Page Name', 'Adset Id', 'Adset Name', 'Campaign Id', 'Form Id',
            'Ad Name', 'נוצר', 'שם', 'דוא"ל', 'טלפון', 'Raw Full Name', 'Raw Email', 'Raw מספר טלפון',
            'Email', 'Email:', 'מספר טלפון', 'Custom Disclaimer Responses', 'Partner Name', 'Retailer Item Id',
            'Vehicle', 'form_id', 'lead_form_id', 'מזהה טופס לידים', 'source', 'row_number', 'timestamp'
        }

        # Check if data already has custom_question_X format (from Zapier)
        has_numbered_format = any(key.startswith('custom_question_') for key in lead_data.keys())

        if not has_numbered_format:
            # Convert non-standard fields to numbered format for consistent display
            form_fields = {}
            question_index = 0

            # Special handling for known Hebrew form questions
            hebrew_form_fields = [
                'יש לך ניסיון בתחום?',
                'מיקום מגורים:',
                'תתאר/י אותך במשפט/שניים על עצמך:',
                'מה התאריך הרצוי לקיום האירוע?',
                'כמות האנשים שצפויה להגיע?',
                'סוג האירוע',
                'תקציב',
                'בקשות מיוחדות',
                'זמן מועדף לקשר'
            ]

            # Process fields in order - Hebrew form fields first, then others
            for field_name in hebrew_form_fields:
                if field_name in lead_data and lead_data[field_name] and str(lead_data[field_name]).strip():
                    clean_lead_data[f'custom_question_{question_index}'] = field_name
                    clean_lead_data[f'custom_answer_{question_index}'] = lead_data[field_name]
                    form_fields[field_name] = lead_data[field_name]
                    logger.info(f"Custom form field [{question_index}]: {field_name} = {lead_data[field_name]}")
                    question_index += 1

            # Then process any other non-standard fields
            for key, value in lead_data.items():
                if key not in standard_fields and key not in hebrew_form_fields:
                    if value and str(value).strip() and not key.startswith('custom_'):
                        clean_lead_data[f'custom_question_{question_index}'] = key
                        clean_lead_data[f'custom_answer_{question_index}'] = value
                        form_fields[key] = value
                        logger.info(f"Custom form field [{question_index}]: {key} = {value}")
                        question_index += 1

            if form_fields:
                logger.info(f"Found {len(form_fields)} custom form response fields, converted to numbered format")
        else:
            # Data already has numbered format, log it
            logger.info("Data already contains custom_question_X format from Zapier")
        
        # Extract data with multiple fallbacks including Zapier field mappings (with and without colons)
        name = (lead_data.get('name') or lead_data.get('full name') or lead_data.get('full_name') or
                lead_data.get('Full Name') or lead_data.get('Full Name:') or lead_data.get('שם') or
                lead_data.get('Raw Full Name'))

        email = (lead_data.get('email') or lead_data.get('Email') or lead_data.get('Email:') or
                 lead_data.get('Raw Email') or lead_data.get('דוא"ל'))

        phone = (lead_data.get('phone') or lead_data.get('Phone Number') or lead_data.get('Phone Number:') or
                 lead_data.get('phone_number') or lead_data.get('טלפון') or lead_data.get('מספר טלפון') or
                 lead_data.get('Raw מספר טלפון'))

        # Extract campaign and form info from Zapier (with comprehensive field mapping)
        campaign_name = None
        
        # Try all possible campaign name field variations
        campaign_fields = [
            'campaign_name', 'Campaign Name', 'Campaign Name:', '\r\n\r\nCampaign Name:',
            'קמפיין', '321085506__campaign_name', 'campaign', 'Campaign',
            'ad_campaign_name', 'ad_campaign', 'campaign_id', 'Campaign ID',
            'campaign_title', 'Campaign Title', 'adset_name', 'Adset Name'
        ]
        
        for field in campaign_fields:
            if field in lead_data and lead_data[field] and str(lead_data[field]).strip():
                campaign_name = str(lead_data[field]).strip()
                logger.info(f"Found campaign name in field '{field}': {campaign_name}")
                break
        
        # If not found in exact fields, try fields with leading/trailing spaces
        if not campaign_name:
            for key, value in lead_data.items():
                if value and str(value).strip():
                    # Check if the key (with spaces trimmed) matches campaign patterns
                    key_trimmed = key.strip().lower()
                    if any(pattern in key_trimmed for pattern in ['campaign', 'קמפיין']):
                        campaign_name = str(value).strip()
                        logger.info(f"Found campaign name in field '{key}' (trimmed): {campaign_name}")
                        break
        
        # If still not found, log all available fields for debugging
        if not campaign_name:
            logger.warning("No campaign name found in any known field")
            logger.info(f"Available fields: {list(lead_data.keys())}")
            # Look for any field containing 'campaign' (case-insensitive)
            campaign_related = [k for k in lead_data.keys() if 'campaign' in k.lower()]
            if campaign_related:
                logger.info(f"Campaign-related fields found: {campaign_related}")
                for field in campaign_related:
                    logger.info(f"  {field}: {lead_data[field]}")

        # Log what we extracted
        logger.info(f"Extracted values - Name: {name}, Email: {email}, Phone: {phone}")
        logger.info(f"Campaign name extracted: {campaign_name}")

        form_name = (lead_data.get('form_name') or lead_data.get('Form Name') or
                    lead_data.get('טופס'))

        # Extract platform
        platform = lead_data.get('platform') or lead_data.get('Platform') or 'facebook'
        
        # Try to save to database, but don't fail if database is unavailable
        lead_id = None
        try:
            conn = get_db_connection()
            if conn:
                cur = conn.cursor()
                
                # Parse created_time
                created_time = None
                if lead_data.get('created_time'):
                    try:
                        created_time = datetime.fromisoformat(lead_data['created_time'].replace('Z', '+00:00'))
                    except:
                        pass
                else:
                    # If no created_time from Zapier, try to extract from raw_data
                    created_date = (lead_data.get('﻿נוצר') or lead_data.get('נוצר') or 
                                  lead_data.get('Created Time') or lead_data.get('date'))
                    if created_date:
                        try:
                            # Handle am/pm format properly
                            if 'am' in created_date.lower() or 'pm' in created_date.lower():
                                date_str = created_date.replace('am', ' AM').replace('pm', ' PM')
                                created_time = datetime.strptime(date_str, '%m/%d/%Y %I:%M %p')
                            else:
                                created_time = datetime.strptime(created_date, '%m/%d/%Y %H:%M')
                        except Exception as e:
                            logger.warning(f"Could not parse date from raw_data '{created_date}': {e}")
                            pass

                # Log what we're about to save
                logger.info(f"About to save lead: name='{name}', email='{email}', phone='{phone}'")

                cur.execute("""
                    INSERT INTO leads (external_lead_id, name, email, phone, platform, campaign_name, form_name, lead_source, created_time, raw_data, customer_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id;
                """, (
                    lead_data.get('id') or lead_data.get('ID'),
                    name,
                    email,
                    phone,
                    platform,
                    campaign_name,
                    form_name,
                    lead_data.get('lead_source'),
                    created_time,
                    json.dumps(clean_lead_data),  # Use clean_lead_data with numbered format
                    1  # Default to customer #1 for main webhook
                ))
                
                lead_id = cur.fetchone()[0]
                conn.commit()
                cur.close()
                conn.close()
                
                # Send real-time notification for new lead
                customer_id = 1  # Default customer ID for main webhook
                notification_title = "לייד חדש הגיע!"
                notification_message = f"לייד חדש מ{platform}: {name}"

                # Additional notification data
                notification_data = {
                    'lead_name': name,
                    'lead_email': email,
                    'lead_phone': phone,
                    'platform': platform,
                    'campaign_name': campaign_name,
                    'form_name': form_name
                }
                
                logger.info(f"Lead {lead_id} created successfully, sending email notifications...")
                
                # Send email notification to campaign managers
                try:
                    # Get campaign managers for this customer
                    conn_email = get_db_connection()
                    if conn_email:
                        cur_email = conn_email.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                        cur_email.execute("""
                            SELECT email, full_name FROM users 
                            WHERE role = 'campaign_manager' 
                            AND customer_id = %s 
                            AND active = true 
                            AND email IS NOT NULL
                        """, (customer_id,))
                        
                        campaign_managers = cur_email.fetchall()
                        cur_email.close()
                        conn_email.close()
                        
                        for manager in campaign_managers:
                            if manager['email']:
                                logger.info(f"Sending email notification to {manager['full_name']} ({manager['email']})")
                                email_sent = send_email_notification(
                                    customer_id=customer_id,
                                    to_email=manager['email'],
                                    to_username=manager['full_name'],
                                    lead_name=name,
                                    lead_phone=phone,
                                    lead_email=email,
                                    platform=platform,
                                    campaign_name=campaign_name
                                )
                                if email_sent:
                                    logger.info(f"Email notification sent successfully to {manager['email']}")
                                else:
                                    logger.warning(f"Failed to send email notification to {manager['email']}")
                        
                        if not campaign_managers:
                            logger.info("No campaign managers with email found for email notifications")
                            
                except Exception as email_error:
                    logger.error(f"Error sending email notifications: {email_error}")
                
                
                logger.info(f"Lead saved to database: {name} ({email}) - ID: {lead_id}")
            else:
                logger.warning("Database not available, lead data logged only")
                
        except Exception as db_error:
            logger.error(f"Database save error: {db_error}")
            # Continue without database - at least log the lead
        
        # Always log the lead data for debugging
        logger.info(f"Lead received: {name} ({email}) from {platform}")
        
        return jsonify({
            'status': 'success',
            'message': 'Lead processed successfully',
            'lead_id': lead_id or 'logged',
            'database_saved': bool(lead_id)
        }), 200
        
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': 'Failed to process lead',
            'error': str(e)
        }), 500

def create_notification(customer_id, lead_id, notification_type, title, message, data=None):
    """Create a notification in the database and send to connected clients"""
    try:
        conn = get_db_connection()
        if not conn:
            logger.warning("Database not available for notification creation")
            return None
            
        cur = conn.cursor()
        
        # Insert notification into database
        logger.info(f"Attempting to insert notification: customer_id={customer_id}, lead_id={lead_id}, type={notification_type}")
        try:
            cur.execute("""
                INSERT INTO notifications (customer_id, lead_id, notification_type, title, message, data)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (customer_id, lead_id, notification_type, title, message, json.dumps(data) if data else None))
            
            result = cur.fetchone()
            if not result:
                logger.error("No result returned from notification INSERT")
                cur.close()
                conn.close()
                return None
                
            notification_id = result[0]
            logger.info(f"Notification inserted successfully with ID: {notification_id}")
            
            conn.commit()
            cur.close()
            conn.close()
        except Exception as db_error:
            logger.error(f"Database error inserting notification: {db_error}")
            cur.close()
            conn.close()
            return None
        
        # Create notification data for real-time sending
        notification_data = {
            'id': notification_id,
            'type': notification_type,
            'title': title,
            'message': message,
            'lead_id': lead_id,
            'customer_id': customer_id,
            'data': data,
            'timestamp': int(time.time())
        }
        
        # Send to connected clients
        logger.info(f"Sending notification to SSE clients for customer {customer_id}")
        send_notification(customer_id, notification_data)
        logger.info(f"Notification sent to SSE stream")
        
        return notification_id
        
    except Exception as e:
        logger.error(f"Error creating notification: {e}")
        return None

def send_email_notification(customer_id, to_email, to_username, lead_name, lead_phone, lead_email, platform, campaign_name, email_type="new_lead", assigned_to=None):
    """Send email notification for new lead using customer-specific email settings"""
    try:
        # Get customer email settings
        conn = get_db_connection()
        if not conn:
            logger.warning("Database not available for email settings")
            return False
            
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT sender_email, smtp_server, smtp_port, smtp_username, smtp_password, email_notifications_enabled, timezone
            FROM customers WHERE id = %s
        """, (customer_id,))
        
        customer_email_settings = cur.fetchone()
        cur.close()
        conn.close()
        
        if not customer_email_settings or not customer_email_settings['email_notifications_enabled']:
            logger.info(f"Email notifications disabled for customer {customer_id}")
            return False
            
        if not customer_email_settings['smtp_username'] or not customer_email_settings['smtp_password']:
            logger.info(f"Email credentials not configured for customer {customer_id}")
            return False
            
        # Create email message using customer settings
        if email_type == "new_lead":
            # Extract role title (remove personal name)
            role_title = to_username.split()[0] + " " + to_username.split()[1] if len(to_username.split()) > 1 else to_username
            subject = f'🔔 ליד חדש הגיע! - {lead_name}'
            title = f'שלום {role_title}, ליד חדש הגיע!'
            instruction = 'כנס למערכת לניהול והקצאת הליד:'
            target_url = '/campaign-manager'
        else:  # assignment
            subject = f'📋 הוקצה לך ליד חדש - {lead_name}'
            title = f'שלום {to_username}, הוקצה לך ליד חדש על ידי {assigned_to}!'
            instruction = 'כנס למערכת לניהול הליד:'
            target_url = '/dashboard'
        
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = customer_email_settings['sender_email'] or customer_email_settings['smtp_username']
        msg['To'] = to_email
        
        # Get Israel timezone timestamp
        customer_timezone = customer_email_settings.get('timezone', 'Asia/Jerusalem')
        israel_tz = pytz.timezone(customer_timezone)
        current_time = datetime.now(israel_tz).strftime('%d/%m/%Y %H:%M')
        
        # Hebrew email content
        text_content = f"""
{title}

שם: {lead_name}
טלפון: {lead_phone or 'לא צוין'}
אימייל: {lead_email or 'לא צוין'}  
פלטפורמה: {platform or 'לא ידוע'}
קמפיין: {campaign_name or 'לא צוין'}
זמן: {current_time} (שעון ישראל)

{instruction}
https://eadmanager-fresh-2024-dev-f83e51d73e01.herokuapp.com{target_url}

מערכת ניהול לידים - אלחנן מאפיית לחם
        """
        
        html_content = f"""
        <!DOCTYPE html>
        <html dir="rtl" lang="he">
        <head>
            <meta charset="UTF-8">
            <style>
                body {{ font-family: Arial, sans-serif; direction: rtl; background: #f5f5f5; margin: 0; padding: 20px; }}
                .container {{ background: white; border-radius: 10px; padding: 30px; max-width: 500px; margin: 0 auto; box-shadow: 0 4px 10px rgba(0,0,0,0.1); direction: rtl; }}
                .header {{ background: linear-gradient(135deg, #10b981 0%, #059669 100%); color: white; padding: 20px; border-radius: 8px; text-align: center; margin-bottom: 20px; direction: rtl; }}
                .lead-info {{ background: #f8f9fa; padding: 15px; border-radius: 8px; margin: 10px 0; direction: rtl; text-align: right; }}
                .lead-info strong {{ color: #1e40af; }}
                .footer {{ text-align: center; color: #6b7280; font-size: 12px; margin-top: 20px; direction: rtl; }}
                .cta-button {{ display: inline-block; background: #3b82f6; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; margin: 15px 0; }}
                .rtl-text {{ direction: rtl; text-align: right; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2 class="rtl-text">{title}</h2>
                </div>
                
                <div class="lead-info">
                    <p><strong>שם:</strong> {lead_name}</p>
                    <p><strong>טלפון:</strong> {lead_phone or 'לא צוין'}</p>
                    <p><strong>אימייל:</strong> {lead_email or 'לא צוין'}</p>
                    <p><strong>פלטפורמה:</strong> {platform or 'לא ידוע'}</p>
                    <p><strong>קמפיין:</strong> {campaign_name or 'לא צוין'}</p>
                </div>
                
                <div style="text-align: center;">
                    <a href="https://eadmanager-fresh-2024-dev-f83e51d73e01.herokuapp.com{target_url}" class="cta-button">
                        🚀 {instruction.replace(':', '')}
                    </a>
                </div>
                
                <div class="footer">
                    <p>מערכת ניהול לידים - אלחנן מאפיית לחם</p>
                    <p>התראה אוטומטית למנהלי קמפיין</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        # Create text and HTML parts
        text_part = MIMEText(text_content, 'plain', 'utf-8')
        html_part = MIMEText(html_content, 'html', 'utf-8')
        
        msg.attach(text_part)
        msg.attach(html_part)
        
        # Send email using customer settings
        with smtplib.SMTP(customer_email_settings['smtp_server'], customer_email_settings['smtp_port']) as server:
            server.starttls()
            server.login(customer_email_settings['smtp_username'], customer_email_settings['smtp_password'])
            server.send_message(msg)
            
        logger.info(f"Email notification sent to {to_email} for lead: {lead_name}")
        return True
        
    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"SMTP Authentication failed for {customer_email_settings['smtp_username']}: {e}")
        logger.error(f"Check Gmail App Password or enable 2-factor authentication")
        return False
    except smtplib.SMTPException as e:
        logger.error(f"SMTP error sending to {to_email}: {e}")
        return False
    except Exception as e:
        logger.error(f"Email notification error: {e}")
        logger.error(f"SMTP settings: server={customer_email_settings.get('smtp_server')}, port={customer_email_settings.get('smtp_port')}, user={customer_email_settings.get('smtp_username')}")
        return False


def send_notification(customer_id, notification_data):
    """Send notification to all connected clients for a specific customer"""
    try:
        if customer_id not in notification_queues:
            notification_queues[customer_id] = []
        
        # Add notification to all active queues for this customer
        for queue in notification_queues[customer_id][:]:  # Create copy to iterate safely
            try:
                queue.put(notification_data, timeout=1)  # Non-blocking put
            except:
                # Remove dead queues
                notification_queues[customer_id].remove(queue)
                
        logger.info(f"Notification sent to {len(notification_queues.get(customer_id, []))} clients for customer {customer_id}")
    except Exception as e:
        logger.error(f"Error sending notification: {e}")



@app.route('/init-db')
@admin_required
def initialize_database():
    """Manually trigger database initialization"""
    try:
        logger.info("Manual database initialization triggered")
        result = init_database()
        return jsonify({
            'success': result,
            'message': 'Database initialization completed' if result else 'Database initialization failed'
        })
    except Exception as e:
        logger.error(f"Manual database initialization error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/static/<path:filename>')
def serve_static(filename):
    """Serve static files including service worker"""
    return send_from_directory('static', filename)

@app.route('/email-status')
@campaign_manager_required
def email_status():
    """Check email notification status for current customer"""
    try:
        user_role = session.get('role')
        if user_role == 'admin':
            customer_id = session.get('selected_customer_id', 1)
        else:
            customer_id = session.get('customer_id', 1)
            
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available'}), 500
            
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT sender_email, smtp_server, smtp_username, email_notifications_enabled
            FROM customers WHERE id = %s
        """, (customer_id,))
        
        customer_settings = cur.fetchone()
        cur.close()
        conn.close()
        
        if customer_settings and customer_settings['email_notifications_enabled']:
            return jsonify({
                'enabled': True,
                'sender_email': customer_settings['sender_email'] or customer_settings['smtp_username'],
                'smtp_server': customer_settings['smtp_server']
            })
        else:
            return jsonify({
                'enabled': False,
                'message': 'Email notifications not configured'
            })
            
    except Exception as e:
        logger.error(f"Email status check error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/test-email-to-user')
@admin_required
def test_email_to_user():
    """Test sending assignment email to ofriwas"""
    try:
        logger.info("Testing direct assignment email to ofriwas")
        
        result = send_email_notification(
            customer_id=1,
            to_email="amikam.shmueli@gmail.com",
            to_username="עפרי ווסר",
            lead_name="בדיקת אימייל ישירה",
            lead_phone="050-1234567",
            lead_email="test@direct.com",
            platform="test",
            campaign_name="בדיקה ישירה",
            email_type="assignment",
            assigned_to="מנהל בדיקה"
        )
        
        return jsonify({
            'success': result,
            'message': 'Direct assignment email test completed',
            'email_sent': result
        })
        
    except Exception as e:
        logger.error(f"Direct assignment email test error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/test-deployment')
def test_deployment():
    """Test if template deployment is working"""
    return render_template('test_deployment.html')

@app.route('/dashboard-new')
@login_required  
def dashboard_new():
    """NEW Enhanced dashboard with mobile improvements"""
    return render_template('dashboard.html')

@app.route('/mobile-dashboard')
@login_required
def mobile_dashboard():
    """Enhanced mobile-first dashboard with modern UX"""
    return render_template('dashboard_mobile_enhanced.html')

@app.route('/leads')
@login_required
def get_leads():
    """View leads with optimized pagination (filtered by assignment for non-admin users)"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available', 'leads': []}), 200
            
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # Get pagination parameters
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 100))  # Default 100 leads per page
        offset = (page - 1) * per_page
        
        # Get selected customer ID (default to 1 if none selected)
        selected_customer_id = session.get('selected_customer_id', 1)
        
        # TEMPORARY FIX: Force customer_id = 1 if not set
        if not selected_customer_id:
            selected_customer_id = 1
        
        # DEBUG: Log what we're using for the query
        logger.info(f"DEBUG: selected_customer_id = {selected_customer_id} (type: {type(selected_customer_id)})")
        logger.info(f"DEBUG: session data = {dict(session)}")
        
        # Optimize query - select only essential fields for main view, exclude heavy raw_data
        
        # Filter leads based on user role and selected customer
        user_role = session.get('role')
        logger.info(f"User role: {user_role}, Username: {session.get('username')}")
        
        if user_role in ['admin', 'campaign_manager']:
            # Count total for pagination
            cur.execute("""
                SELECT COUNT(*) as count
                FROM leads l 
                WHERE l.customer_id = %s OR l.customer_id IS NULL
            """, (selected_customer_id,))
            count_result = cur.fetchone()
            if count_result is None:
                logger.error(f"COUNT query returned None for customer_id: {selected_customer_id}")
                total_count = 0
            else:
                total_count = count_result['count']
            
            # Get paginated results with optimized query
            cur.execute("""
                SELECT l.id, l.external_lead_id, l.name, l.email, l.phone, l.platform, 
                       l.campaign_name, l.form_name, l.lead_source, l.created_time, 
                       l.received_at, l.status, l.assigned_to, l.priority, l.updated_at,
                       u.full_name as assigned_full_name
                FROM leads l
                LEFT JOIN users u ON l.assigned_to = u.username AND u.active = true
                WHERE l.customer_id = %s OR l.customer_id IS NULL
                ORDER BY COALESCE(l.created_time, l.received_at) DESC
                LIMIT %s OFFSET %s
            """, (selected_customer_id, per_page, offset))
        else:
            # Regular users see only leads assigned to them
            username = session.get('username')
            
            # Count total for pagination
            cur.execute("""
                SELECT COUNT(*) as count
                FROM leads l
                WHERE l.assigned_to = %s AND (l.customer_id = %s OR l.customer_id IS NULL)
            """, (username, selected_customer_id))
            count_result = cur.fetchone()
            if count_result is None:
                logger.error(f"COUNT query returned None for username: {username}, customer_id: {selected_customer_id}")
                total_count = 0
            else:
                total_count = count_result['count']
            
            # Get paginated results
            cur.execute("""
                SELECT l.id, l.external_lead_id, l.name, l.email, l.phone, l.platform, 
                       l.campaign_name, l.form_name, l.lead_source, l.created_time, 
                       l.received_at, l.status, l.assigned_to, l.priority, l.updated_at,
                       u.full_name as assigned_full_name
                FROM leads l
                LEFT JOIN users u ON l.assigned_to = u.username AND u.active = true
                WHERE l.assigned_to = %s AND (l.customer_id = %s OR l.customer_id IS NULL)
                ORDER BY COALESCE(l.created_time, l.received_at) DESC
                LIMIT %s OFFSET %s
            """, (username, selected_customer_id, per_page, offset))
        
        leads = cur.fetchall()
        
        # Convert to JSON-serializable format (optimized)
        leads_list = []
        for lead in leads:
            lead_dict = dict(lead)
            # Safely convert datetime objects that exist
            for key in ['created_time', 'received_at', 'updated_at']:
                if lead_dict.get(key):
                    try:
                        if hasattr(lead_dict[key], 'isoformat'):
                            lead_dict[key] = lead_dict[key].isoformat()
                    except Exception as e:
                        logger.warning(f"Failed to convert datetime {key} for lead {lead_dict.get('id', 'unknown')}: {e}")
                        # Keep original value if conversion fails
                        pass
            leads_list.append(lead_dict)
        
        cur.close()
        conn.close()
        
        # Calculate pagination info
        total_pages = (total_count + per_page - 1) // per_page
        has_next = page < total_pages
        has_prev = page > 1
        
        return jsonify({
            'total_leads': total_count,
            'leads': leads_list,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total_pages': total_pages,
                'has_next': has_next,
                'has_prev': has_prev,
                'total_count': total_count
            }
        })
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"Error fetching leads: {str(e)}")
        logger.error(f"Full traceback: {error_details}")
        
        return jsonify({
            'error': str(e),
            'error_type': type(e).__name__,
            'error_details': error_details,
            'leads': []
        }), 200

@app.route('/leads/<int:lead_id>')
def get_lead(lead_id):
    """Get specific lead with details"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available'}), 500
            
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # Get lead details
        cur.execute("""
            SELECT id, external_lead_id, name, email, phone, platform, campaign_name, form_name, 
                   lead_source, created_time, received_at, status, assigned_to, priority, 
                   raw_data, notes, updated_at
            FROM leads 
            WHERE id = %s
        """, (lead_id,))
        
        lead = cur.fetchone()
        
        if not lead:
            cur.close()
            conn.close()
            return jsonify({'error': 'Lead not found'}), 404
        
        # Get activities for this lead
        cur.execute("""
            SELECT user_name, activity_type, description, call_duration, call_outcome, 
                   previous_status, new_status, activity_date, activity_metadata
            FROM lead_activities 
            WHERE lead_id = %s 
            ORDER BY activity_date DESC
        """, (lead_id,))
        
        activities = cur.fetchall()
        
        cur.close()
        conn.close()
        
        # Convert to JSON-serializable format
        lead_dict = dict(lead)
        for key in ['created_time', 'received_at', 'updated_at']:
            if lead_dict[key]:
                lead_dict[key] = lead_dict[key].isoformat()
        
        # Convert activities to JSON-serializable format
        activities_list = []
        for activity in activities:
            activity_dict = dict(activity)
            activity_dict['activity_date'] = activity_dict['activity_date'].isoformat() if activity_dict['activity_date'] else None
            activities_list.append(activity_dict)
        
        return jsonify({
            'lead': lead_dict,
            'activities': activities_list
        })
        
    except Exception as e:
        logger.error(f"Error fetching lead {lead_id}: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/dashboard')
@login_required
def dashboard():
    """Beautiful web dashboard for viewing leads - with mobile detection"""
    # Detect mobile device from user agent
    user_agent = request.headers.get('User-Agent', '').lower()
    is_mobile = any(device in user_agent for device in ['mobile', 'android', 'iphone', 'ipad'])

    # Use enhanced mobile template for mobile devices
    if is_mobile:
        return render_template('dashboard_mobile_enhanced.html')
    return render_template('dashboard.html')

@app.route('/lead/<int:lead_id>')
@login_required
def get_single_lead(lead_id):
    """Get details for a single lead"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database connection error'}), 500

        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Get customer context
        if session.get('role') == 'admin':
            selected_customer_id = session.get('selected_customer_id', 1)
        else:
            selected_customer_id = session.get('customer_id', 1)

        # Fetch the lead with customer filtering
        cur.execute("""
            SELECT
                l.id,
                l.name,
                l.email,
                l.phone,
                l.status,
                l.platform,
                l.campaign_name,
                l.assigned_to,
                l.created_time,
                l.updated_at,
                l.notes,
                l.external_lead_id,
                u.full_name as assigned_to_name
            FROM leads l
            LEFT JOIN users u ON l.assigned_to = u.username AND u.customer_id = l.customer_id
            WHERE l.id = %s AND l.customer_id = %s
        """, (lead_id, selected_customer_id))

        lead = cur.fetchone()

        if not lead:
            return jsonify({'error': 'Lead not found'}), 404

        cur.close()
        conn.close()

        # Convert datetime objects to strings for JSON serialization
        if lead.get('created_time'):
            lead['created_time'] = lead['created_time'].isoformat()
        if lead.get('updated_at'):
            lead['updated_at'] = lead['updated_at'].isoformat()

        return jsonify(lead)

    except Exception as e:
        logger.error(f"Error fetching lead {lead_id}: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/campaign-manager')
@campaign_manager_required
def campaign_manager_dashboard():
    """Campaign manager dashboard - with mobile detection"""
    # Detect mobile device from user agent
    user_agent = request.headers.get('User-Agent', '').lower()
    is_mobile = any(device in user_agent for device in ['mobile', 'android', 'iphone', 'ipad'])

    # Use enhanced mobile template for mobile devices
    if is_mobile:
        return render_template('dashboard_mobile_enhanced.html')
    return render_template('campaign_manager_dashboard.html', 
                         user_name=session.get('full_name', 'מנהל קמפיין'),
                         customer_name=session.get('selected_customer_name', 'לא נבחר'))

@app.route('/pull-history', methods=['POST'])
def pull_history():
    """Trigger to pull historical leads from Facebook via Zapier"""
    try:
        # This endpoint will be called by the dashboard
        # It returns instructions for setting up the Zapier bulk pull
        
        # For now, return setup instructions
        return jsonify({
            'status': 'setup_required',
            'message': 'Choose one of these methods to import historical leads',
            'methods': {
                'zapier_scheduled': {
                    'title': 'Zapier Scheduled Import (Recommended)',
                    'steps': [
                        'Create new Zap: Schedule by Zapier → Every Month',
                        'Action: Facebook Lead Ads → Find Lead or Search Leads', 
                        'Filter: Set date range for historical leads',
                        'Action 2: Webhooks by Zapier → POST',
                        f'URL: {request.url_root}webhook-bulk',
                        'Test and run once, then turn off'
                    ]
                },
                'csv_upload': {
                    'title': 'Manual CSV Upload',
                    'steps': [
                        'Export leads from Facebook Ads Manager as CSV',
                        f'Visit: {request.url_root}upload-csv',
                        'Upload the CSV file',
                        'System will automatically import all leads'
                    ]
                },
                'facebook_direct': {
                    'title': 'Facebook API Direct',
                    'steps': [
                        'Go to Facebook Ads Manager',
                        'Navigate to Lead Ads section',
                        'Download all historical leads',
                        'Use CSV upload method above'
                    ]
                }
            },
            'webhook_url': f'{request.url_root}webhook-bulk',
            'csv_upload_url': f'{request.url_root}upload-csv'
        })
    except Exception as e:
        logger.error(f"Error in pull history: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/webhook-bulk', methods=['POST'])
def webhook_bulk():
    """Special webhook endpoint for bulk historical lead import from Zapier"""
    try:
        leads_data = request.get_json()
        
        if not leads_data:
            return jsonify({'error': 'No data received'}), 400
        
        # Handle both single lead and array of leads
        if not isinstance(leads_data, list):
            leads_data = [leads_data]
        
        imported_count = 0
        conn = get_db_connection()
        
        if not conn:
            return jsonify({'error': 'Database connection failed'}), 500
            
        cur = conn.cursor()
        
        for lead_data in leads_data:
            try:
                # Check if lead already exists
                external_id = lead_data.get('id')
                if external_id:
                    cur.execute("SELECT id FROM leads WHERE external_lead_id = %s", (external_id,))
                    if cur.fetchone():
                        logger.info(f"Lead {external_id} already exists, skipping")
                        continue
                
                # Extract data same as regular webhook
                name = lead_data.get('name') or lead_data.get('full name') or lead_data.get('full_name')
                phone = lead_data.get('phone') or lead_data.get('phone_number')
                
                # Parse created_time
                created_time = None
                if lead_data.get('created_time'):
                    try:
                        created_time = datetime.fromisoformat(lead_data['created_time'].replace('Z', '+00:00'))
                    except:
                        pass
                
                # Insert lead
                cur.execute("""
                    INSERT INTO leads (external_lead_id, name, email, phone, platform, campaign_name, form_name, lead_source, created_time, raw_data, customer_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id;
                """, (
                    lead_data.get('id'),
                    name,
                    lead_data.get('email'),
                    phone,
                    lead_data.get('platform', 'facebook'),
                    lead_data.get('campaign_name'),
                    lead_data.get('form_name'),
                    lead_data.get('lead_source'),
                    created_time,
                    json.dumps(lead_data),
                    1  # Default to customer #1 for bulk webhook
                ))
                
                lead_id = cur.fetchone()[0]
                imported_count += 1
                
                logger.info(f"Historical lead imported: {name} ({lead_data.get('email')}) - ID: {lead_id}")
                
            except Exception as e:
                logger.error(f"Error importing individual lead: {str(e)}")
                continue
        
        conn.commit()
        cur.close()
        conn.close()
        
        logger.info(f"Bulk import completed: {imported_count} leads imported")
        
        return jsonify({
            'status': 'success',
            'message': f'Successfully imported {imported_count} historical leads',
            'leads_imported': imported_count
        }), 200
        
    except Exception as e:
        logger.error(f"Error in bulk import: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': 'Failed to import historical leads',
            'error': str(e)
        }), 500

@app.route('/upload-csv', methods=['GET', 'POST'])
def upload_csv():
    """Upload CSV file with historical leads"""
    if request.method == 'GET':
        return '''
        <!DOCTYPE html>
        <html dir="rtl" lang="he">
        <head>
            <title>העלאת קובץ לידים</title>
            <meta charset="UTF-8">
            <style>
                body { font-family: Arial; padding: 20px; text-align: center; }
                .upload-form { max-width: 500px; margin: 0 auto; }
                input[type=file] { margin: 20px 0; padding: 10px; }
                button { background: #007cba; color: white; padding: 15px 30px; border: none; border-radius: 5px; cursor: pointer; }
                button:hover { background: #005a87; }
            </style>
        </head>
        <body>
            <div class="upload-form">
                <h1>העלאת קובץ לידים היסטוריים</h1>
                <p>בחר קובץ CSV מ-Facebook Ads Manager:</p>
                <form enctype="multipart/form-data" method="post">
                    <input type="file" name="csv_file" accept=".csv" required>
                    <br>
                    <button type="submit">העלה לידים</button>
                    <button type="button" onclick="debugCSV()" style="background:#f39c12; margin-right:10px;">🔍 בדוק CSV קודם</button>
                </form>
                <div id="debug-result" style="margin-top:20px; text-align:right; background:#f8f9fa; padding:15px; border-radius:5px; display:none;">
                </div>
                <script>
                async function debugCSV() {
                    const fileInput = document.querySelector('input[type="file"]');
                    if (!fileInput.files[0]) {
                        alert('אנא בחר קובץ תחילה');
                        return;
                    }
                    
                    const formData = new FormData();
                    formData.append('csv_file', fileInput.files[0]);
                    
                    try {
                        const response = await fetch('/debug-csv', {
                            method: 'POST',
                            body: formData
                        });
                        const result = await response.json();
                        
                        const debugDiv = document.getElementById('debug-result');
                        debugDiv.style.display = 'block';
                        debugDiv.innerHTML = `
                            <h3>🔍 בדיקת מבנה הקובץ:</h3>
                            <p><strong>קובץ:</strong> ${result.filename}</p>
                            <p><strong>מספר עמודות:</strong> ${result.total_columns}</p>
                            <p><strong>עמודות שנמצאו:</strong></p>
                            <ul>${result.columns_found.map(col => '<li>' + col + '</li>').join('')}</ul>
                            <p><strong>הצעות למיפוי:</strong></p>
                            <ul>
                                <li>שמות אפשריים: ${result.suggestions.name_columns.join(', ') || 'לא נמצא'}</li>
                                <li>אימיילים אפשריים: ${result.suggestions.email_columns.join(', ') || 'לא נמצא'}</li>
                                <li>טלפונים אפשריים: ${result.suggestions.phone_columns.join(', ') || 'לא נמצא'}</li>
                            </ul>
                            <p style="color:#27ae60;"><strong>עכשיו אתה יכול להעלות את הקובץ בביטחון!</strong></p>
                        `;
                    } catch (error) {
                        alert('שגיאה בבדיקת הקובץ: ' + error.message);
                    }
                }
                </script>
            </div>
        </body>
        </html>
        '''
    
    try:
        if 'csv_file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
            
        file = request.files['csv_file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
            
        # Read and process CSV
        import csv
        import io
        
        # Read file content
        stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
        csv_input = csv.DictReader(stream)
        
        imported_count = 0
        conn = get_db_connection()
        
        if not conn:
            return jsonify({'error': 'Database connection failed'}), 500
            
        cur = conn.cursor()
        
        for row in csv_input:
            try:
                # Debug: Log the first row to see column names
                if imported_count == 0:
                    logger.info(f"CSV columns found: {list(row.keys())}")
                
                # Map based on the actual Hebrew CSV columns you provided
                name = (row.get('שם') or row.get('name') or row.get('Full Name') or 
                       row.get('Name') or row.get('FULL_NAME') or row.get('Full name') or
                       row.get('שם מלא') or row.get('full_name'))
                
                email = (row.get('דוא"ל') or row.get('email') or row.get('Email') or 
                        row.get('EMAIL') or row.get('E-mail') or row.get('e-mail') or 
                        row.get('אימייל'))
                
                phone = (row.get('טלפון') or row.get('מספר טלפון משני') or 
                        row.get('phone_number') or row.get('phone') or row.get('Phone') or 
                        row.get('PHONE') or row.get('Phone Number') or 
                        row.get('מספר טלפון'))
                
                # Also try to get created date and other info
                created_date = (row.get('﻿נוצר') or row.get('נוצר') or row.get('created_time') or 
                              row.get('Created Time') or row.get('date') or 
                              row.get('Date') or row.get('תאריך'))
                
                form_name = row.get('טופס') or row.get('form_name')
                channel = row.get('ערוץ') or row.get('platform')
                source = row.get('מקור') or row.get('source')
                
                logger.info(f"Processing row: name='{name}', email='{email}', phone='{phone}'")
                
                if not name and not email and not phone:
                    logger.info("Skipping row - no name, email, or phone found")
                    continue  # Skip rows without any contact info
                
                # Check if lead already exists
                if email:
                    cur.execute("SELECT id FROM leads WHERE email = %s", (email,))
                    if cur.fetchone():
                        continue  # Skip duplicates
                
                # Parse created time if available
                created_time = None
                if created_date:
                    try:
                        # Try to parse the Hebrew date format from your CSV
                        # e.g., "12/10/2024 12:36am" 
                        from datetime import datetime
                        import re
                        
                        # Handle am/pm format properly
                        if 'am' in created_date.lower() or 'pm' in created_date.lower():
                            # Use %I for 12-hour format with %p for AM/PM
                            date_str = created_date.replace('am', ' AM').replace('pm', ' PM')
                            created_time = datetime.strptime(date_str, '%m/%d/%Y %I:%M %p')
                        else:
                            # Try 24-hour format
                            created_time = datetime.strptime(created_date, '%m/%d/%Y %H:%M')
                    except Exception as e:
                        logger.warning(f"Could not parse date '{created_date}': {e}")
                        pass
                
                # Insert lead
                cur.execute("""
                    INSERT INTO leads (name, email, phone, platform, campaign_name, form_name, 
                                     lead_source, created_time, raw_data, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id;
                """, (
                    name,
                    email, 
                    phone,
                    channel or 'facebook_csv',
                    form_name,  # This will show which specific campaign/form
                    form_name,
                    source or 'CSV Import',
                    created_time,
                    json.dumps(dict(row)),
                    'new'
                ))
                
                lead_id = cur.fetchone()[0]
                imported_count += 1
                
                logger.info(f"CSV lead imported: {name} ({email}) - ID: {lead_id}")
                
            except Exception as e:
                logger.error(f"Error importing CSV row: {str(e)}")
                continue
        
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({
            'status': 'success',
            'message': f'Successfully imported {imported_count} leads from CSV',
            'leads_imported': imported_count,
            'debug_info': 'Check server logs for column names and processing details'
        })
        
    except Exception as e:
        logger.error(f"Error processing CSV: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': 'Failed to process CSV file',
            'error': str(e)
        }), 500

@app.route('/debug-csv', methods=['POST'])
def debug_csv():
    """Debug endpoint to see CSV structure without importing"""
    try:
        if 'csv_file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
            
        file = request.files['csv_file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
            
        import csv
        import io
        
        # Read file content
        stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
        csv_input = csv.DictReader(stream)
        
        # Get first few rows for debugging
        sample_rows = []
        columns = []
        
        for i, row in enumerate(csv_input):
            if i == 0:
                columns = list(row.keys())
            if i < 3:  # Get first 3 rows as samples
                sample_rows.append(dict(row))
            else:
                break
                
        return jsonify({
            'status': 'debug',
            'filename': file.filename,
            'columns_found': columns,
            'total_columns': len(columns),
            'sample_rows': sample_rows,
            'suggestions': {
                'name_columns': [col for col in columns if any(x in col.lower() for x in ['name', 'שם'])],
                'email_columns': [col for col in columns if any(x in col.lower() for x in ['email', 'mail', 'אימייל'])],
                'phone_columns': [col for col in columns if any(x in col.lower() for x in ['phone', 'טלפון', 'tel'])]
            }
        })
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'Debug failed: {str(e)}'
        }), 500

@app.route('/webhook-test', methods=['POST'])
def webhook_test():
    """Test webhook endpoint that shows exactly what Zapier sends"""
    try:
        # Get raw data in different formats
        json_data = request.get_json(force=True, silent=True)
        form_data = request.form.to_dict() if request.form else {}
        args_data = request.args.to_dict() if request.args else {}
        
        # Get headers
        headers = dict(request.headers)
        
        # Build comprehensive response
        response = {
            'status': 'success',
            'message': 'Test webhook received data',
            'data_received': {
                'json_body': json_data,
                'form_data': form_data,
                'query_params': args_data,
                'total_json_fields': len(json_data) if json_data else 0,
                'json_field_names': list(json_data.keys()) if json_data else [],
            },
            'request_info': {
                'method': request.method,
                'content_type': request.content_type,
                'content_length': request.content_length
            }
        }
        
        # Log for debugging
        logger.info("=== TEST WEBHOOK DATA ===")
        logger.info(f"JSON Data: {json_data}")
        logger.info(f"Form Data: {form_data}")
        logger.info(f"Query Params: {args_data}")
        
        # If we have JSON data, analyze it for form fields
        if json_data:
            form_responses = {}
            standard_fields = ['id', 'name', 'email', 'phone', 'platform', 'campaign_name', 
                             'form_name', 'lead_source', 'created_time', 'full_name', 
                             'phone_number', 'נוצר', 'שם', 'דוא"ל', 'טלפון', 'טופס', 
                             'מקור', 'ערוץ', 'בעלים', 'שלב']
            
            for key, value in json_data.items():
                if key not in standard_fields and value:
                    form_responses[key] = value
            
            response['form_responses_detected'] = form_responses
            response['form_responses_count'] = len(form_responses)
        
        return jsonify(response), 200
        
    except Exception as e:
        logger.error(f"Test webhook error: {str(e)}")
        return jsonify({
            'status': 'error',
            'error': str(e),
            'message': 'Error processing test webhook'
        }), 500

@app.route('/test')
def test():
    return jsonify({
        'test': 'success',
        'webhook_ready': True,
        'webhook_test_endpoint': '/webhook-test',
        'database_url_present': bool(DATABASE_URL)
    })

@app.route('/leads/<int:lead_id>/activity', methods=['POST'])
def add_activity():
    """Add activity to a lead"""
    try:
        activity_data = request.get_json()
        lead_id = request.view_args['lead_id']
        
        if not activity_data:
            return jsonify({'error': 'No activity data provided'}), 400
            
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available'}), 500
            
        cur = conn.cursor()
        
        # Insert activity
        cur.execute("""
            INSERT INTO lead_activities 
            (lead_id, user_name, activity_type, description, call_duration, call_outcome, activity_metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id;
        """, (
            lead_id,
            activity_data.get('user_name', 'אנונימי'),
            activity_data.get('activity_type'),
            activity_data.get('description'),
            activity_data.get('call_duration'),
            activity_data.get('call_outcome'),
            json.dumps(activity_data.get('metadata', {}))
        ))
        
        activity_id = cur.fetchone()[0]
        
        # Update lead status if provided
        if activity_data.get('new_status'):
            cur.execute("""
                UPDATE leads SET status = %s, updated_at = CURRENT_TIMESTAMP 
                WHERE id = %s
            """, (activity_data.get('new_status'), lead_id))
        
        conn.commit()
        cur.close()
        conn.close()
        
        logger.info(f"Activity added to lead {lead_id}: {activity_data.get('activity_type')}")
        
        return jsonify({
            'status': 'success',
            'activity_id': activity_id,
            'message': 'פעילות נוספה בהצלחה'
        })
        
    except Exception as e:
        logger.error(f"Error adding activity: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': 'שגיאה בהוספת הפעילות',
            'error': str(e)
        }), 500

@app.route('/leads/<int:lead_id>/status', methods=['PUT'])
def update_lead_status(lead_id):
    """Update lead status"""
    try:
        data = request.get_json()

        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available'}), 500

        cur = conn.cursor()

        # Get current status
        cur.execute("SELECT status FROM leads WHERE id = %s", (lead_id,))
        result = cur.fetchone()
        if not result:
            return jsonify({'error': 'Lead not found'}), 404

        old_status = result[0]
        new_status = data.get('status')
        user_name = data.get('user_name', 'אנונימי')
        note = data.get('note', '').strip()

        # Make note mandatory for status changes
        if not note:
            return jsonify({'error': 'הערה היא שדה חובה בעת שינוי סטטוס'}), 400

        # Update status
        cur.execute("""
            UPDATE leads SET status = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (new_status, lead_id))

        # Build description with note
        status_description = f'סטטוס שונה מ-{old_status} ל-{new_status}'
        if note:
            status_description += f' | הערה: {note}'

        # Log status change activity with note
        cur.execute("""
            INSERT INTO lead_activities
            (lead_id, user_name, activity_type, description, previous_status, new_status)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            lead_id, user_name, 'status_change',
            status_description,
            old_status, new_status
        ))

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            'status': 'success',
            'message': 'סטטוס עודכן בהצלחה'
        })

    except Exception as e:
        logger.error(f"Error updating status: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/admin')
@admin_required
def admin_dashboard():
    """Admin-only dashboard - with mobile detection"""
    # Detect mobile device from user agent
    user_agent = request.headers.get('User-Agent', '').lower()
    is_mobile = any(device in user_agent for device in ['mobile', 'android', 'iphone', 'ipad'])

    # Use enhanced mobile template for mobile devices
    if is_mobile:
        return render_template('dashboard_mobile_enhanced.html')
    return render_template('admin_dashboard.html')

@app.route('/admin/fix-phone-numbers')
@admin_required
def fix_phone_numbers():
    """Admin endpoint to fix phone numbers from raw_data"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available'}), 500

        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Find leads with empty phone field but phone data in raw_data
        cur.execute("""
            SELECT id, name, phone, raw_data
            FROM leads
            WHERE (phone IS NULL OR phone = '')
            AND raw_data IS NOT NULL
        """)

        leads_to_fix = cur.fetchall()
        fixed_count = 0
        fixed_leads = []

        for lead in leads_to_fix:
            raw_data = lead['raw_data']
            if not raw_data:
                continue

            # Parse raw_data if it's a string
            if isinstance(raw_data, str):
                try:
                    raw_data = json.loads(raw_data)
                except:
                    continue

            # Look for phone number in various fields
            phone = None
            phone_fields = ['Phone Number', 'phone', 'phone_number', 'טלפון', 'מספר טלפון', 'Raw מספר טלפון']

            for field in phone_fields:
                if field in raw_data and raw_data[field]:
                    phone = raw_data[field]
                    break

            if phone:
                # Update the lead with the phone number
                cur.execute("""
                    UPDATE leads
                    SET phone = %s
                    WHERE id = %s
                """, (phone, lead['id']))

                fixed_leads.append({
                    'id': lead['id'],
                    'name': lead['name'],
                    'phone': phone
                })
                fixed_count += 1

        # Commit the changes
        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            'status': 'success',
            'message': f'Successfully fixed {fixed_count} leads',
            'fixed_count': fixed_count,
            'fixed_leads': fixed_leads
        })

    except Exception as e:
        logger.error(f"Error fixing phone numbers: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/admin/mass-close', methods=['POST'])
def mass_close_leads():
    """Admin: Mass close multiple leads"""
    try:
        data = request.get_json()
        lead_ids = data.get('lead_ids', [])
        user_name = data.get('user_name', 'Admin')
        
        if not lead_ids:
            return jsonify({'error': 'No leads selected'}), 400
            
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available'}), 500
            
        cur = conn.cursor()
        
        closed_count = 0
        for lead_id in lead_ids:
            # Update status
            cur.execute("""
                UPDATE leads SET status = 'closed', updated_at = CURRENT_TIMESTAMP 
                WHERE id = %s AND status != 'closed'
            """, (lead_id,))
            
            if cur.rowcount > 0:
                # Log activity
                cur.execute("""
                    INSERT INTO lead_activities 
                    (lead_id, user_name, activity_type, description, new_status)
                    VALUES (%s, %s, %s, %s, %s)
                """, (
                    lead_id, user_name, 'status_change',
                    'סגירה המונית על ידי מנהל', 'closed'
                ))
                closed_count += 1
        
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({
            'status': 'success',
            'closed_count': closed_count,
            'message': f'{closed_count} לידים נסגרו בהצלחה'
        })
        
    except Exception as e:
        logger.error(f"Error in mass close: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/admin/users')
@admin_required
def manage_users():
    """Admin: User management page"""
    return render_template('user_management.html')

@app.route('/admin/users/api')
@login_required
def get_users_api():
    """Get users based on user role - Admin sees all, Campaign Manager sees only their customer"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available'}), 500
            
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # Get user role and customer from session
        user_role = session.get('role')
        user_customer_id = session.get('selected_customer_id') or session.get('customer_id')
        
        # Admin query - include plain_password for admins
        if user_role == 'admin':
            customer_filter = request.args.get('customer_id')
            if customer_filter:
                cur.execute("""
                    SELECT u.id, u.username, u.full_name, u.email, u.phone, u.role, u.department, u.active, u.created_at, 
                           u.customer_id, c.name as customer_name, u.plain_password, u.whatsapp_notifications
                    FROM users u
                    LEFT JOIN customers c ON u.customer_id = c.id
                    WHERE u.customer_id = %s
                    ORDER BY u.created_at DESC
                """, (customer_filter,))
            else:
                cur.execute("""
                    SELECT u.id, u.username, u.full_name, u.email, u.phone, u.role, u.department, u.active, u.created_at, 
                           u.customer_id, c.name as customer_name, u.plain_password, u.whatsapp_notifications
                    FROM users u
                    LEFT JOIN customers c ON u.customer_id = c.id
                    ORDER BY u.created_at DESC
                """)
        # Campaign Manager query - only their customer's users
        elif user_role == 'campaign_manager':
            logger.info(f"Campaign manager {session.get('username')} requesting users for customer {user_customer_id}")
            logger.info(f"Session data: {dict(session)}")  # Debug session data
            
            if not user_customer_id:
                logger.error(f"Campaign manager {session.get('username')} has no customer_id in session!")
                return jsonify({'error': 'No customer assigned to your account'}), 400
                
            cur.execute("""
                SELECT u.id, u.username, u.full_name, u.email, u.phone, u.role, u.department, u.active, u.created_at, 
                       u.customer_id, c.name as customer_name, u.plain_password, u.whatsapp_notifications
                FROM users u
                LEFT JOIN customers c ON u.customer_id = c.id
                WHERE u.customer_id = %s AND u.customer_id > 0
                ORDER BY u.created_at DESC
            """, (user_customer_id,))
        else:
            return jsonify({'error': 'Access denied'}), 403
        
        users = cur.fetchall()
        logger.info(f"Found {len(users)} users for role {user_role}, customer {user_customer_id}")
        
        # Convert to JSON-serializable format
        users_list = []
        for user in users:
            user_dict = dict(user)
            user_dict['created_at'] = user_dict['created_at'].isoformat() if user_dict['created_at'] else None
            users_list.append(user_dict)
            
        logger.info(f"Returning {len(users_list)} users in JSON response")
        
        cur.close()
        conn.close()
        
        return jsonify({'users': users_list})
        
    except Exception as e:
        logger.error(f"Error fetching users: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/admin/fix-dates', methods=['POST'])
@admin_required
def fix_lead_dates():
    """Update existing leads to parse creation dates from raw_data"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available'}), 500
            
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # Find leads with null created_time but date in raw_data
        cur.execute("""
            SELECT id, raw_data 
            FROM leads 
            WHERE created_time IS NULL AND raw_data IS NOT NULL
        """)
        
        leads_to_update = cur.fetchall()
        updated_count = 0
        
        for lead in leads_to_update:
            raw_data = lead['raw_data']
            created_date = None
            
            # Try to find date in raw_data
            if isinstance(raw_data, dict):
                created_date = (raw_data.get('﻿נוצר') or raw_data.get('נוצר') or 
                               raw_data.get('created_time') or raw_data.get('Created Time'))
            
            if created_date:
                try:
                    # Parse the date
                    if 'am' in created_date.lower() or 'pm' in created_date.lower():
                        date_str = created_date.replace('am', ' AM').replace('pm', ' PM')
                        created_time = datetime.strptime(date_str, '%m/%d/%Y %I:%M %p')
                    else:
                        created_time = datetime.strptime(created_date, '%m/%d/%Y %H:%M')
                    
                    # Update the lead
                    cur.execute("""
                        UPDATE leads SET created_time = %s WHERE id = %s
                    """, (created_time, lead['id']))
                    
                    updated_count += 1
                    logger.info(f"Updated lead {lead['id']} with date {created_time}")
                    
                except Exception as e:
                    logger.warning(f"Could not parse date '{created_date}' for lead {lead['id']}: {e}")
        
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({
            'status': 'success',
            'message': f'Updated {updated_count} leads with creation dates',
            'updated_count': updated_count
        })
        
    except Exception as e:
        logger.error(f"Error fixing dates: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/admin/users', methods=['POST'])
@login_required
def create_user():
    """Admin/Campaign Manager: Create new user"""
    try:
        data = request.get_json()
        user_role = session.get('role')
        user_customer_id = session.get('selected_customer_id')
        
        # Check permissions
        if user_role not in ['admin', 'campaign_manager']:
            return jsonify({'error': 'Access denied'}), 403
        
        # Use plain_password if provided, otherwise password
        password = data.get('plain_password', data.get('password'))
        required_fields = ['username', 'full_name']
        if not password:
            required_fields.append('password')
        
        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        # Set customer_id based on user role
        if user_role == 'campaign_manager':
            # Campaign managers can only create users for their own customer
            target_customer_id = user_customer_id
            # Force role to be 'user' for campaign managers
            target_role = 'user'
        else:
            # Admins can specify customer_id and role
            target_customer_id = data.get('customer_id', user_customer_id)
            target_role = data.get('role', 'user')
        
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available'}), 500
            
        cur = conn.cursor()
        
        # Check if username exists
        cur.execute("SELECT id FROM users WHERE username = %s", (data['username'],))
        if cur.fetchone():
            return jsonify({'error': 'Username already exists'}), 400
        
        # Create user
        cur.execute("""
            INSERT INTO users (username, password_hash, plain_password, full_name, email, phone, role, department, customer_id, active, whatsapp_notifications)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id;
        """, (
            data['username'],
            hash_password(password),
            password,  # Store plain password for admin reference
            data['full_name'],
            data.get('email'),
            data.get('phone'),
            target_role,
            data.get('department'),
            target_customer_id,
            data.get('active', True),
            data.get('whatsapp_notifications', True)
        ))
        
        user_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        
        logger.info(f"User created: {data['username']} by {session.get('username')}")
        
        return jsonify({
            'status': 'success',
            'user_id': user_id,
            'message': 'משתמש נוצר בהצלחה'
        })
        
    except Exception as e:
        logger.error(f"Error creating user: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/admin/users/<int:user_id>', methods=['PUT'])
@login_required
def update_user(user_id):
    """Admin/Campaign Manager: Update existing user"""
    try:
        data = request.get_json()
        user_role = session.get('role')
        user_customer_id = session.get('selected_customer_id')
        
        # Check permissions
        if user_role not in ['admin', 'campaign_manager']:
            return jsonify({'error': 'Access denied'}), 403
        
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available'}), 500
            
        cur = conn.cursor()
        
        # Check if user exists and if campaign manager has access
        if user_role == 'campaign_manager':
            cur.execute("SELECT id FROM users WHERE id = %s AND customer_id = %s", (user_id, user_customer_id))
        else:
            cur.execute("SELECT id FROM users WHERE id = %s", (user_id,))
            
        if not cur.fetchone():
            return jsonify({'error': 'User not found or access denied'}), 404
        
        # Build update query dynamically based on provided fields
        update_fields = []
        update_values = []
        
        if 'username' in data:
            # Check username uniqueness
            cur.execute("SELECT id FROM users WHERE username = %s AND id != %s", (data['username'], user_id))
            if cur.fetchone():
                return jsonify({'error': 'Username already exists'}), 400
            update_fields.append("username = %s")
            update_values.append(data['username'])
        
        # Handle password update (support both 'password' and 'plain_password' fields)
        password = data.get('plain_password', data.get('password'))
        if password:
            update_fields.append("password_hash = %s")
            update_values.append(hash_password(password))
            update_fields.append("plain_password = %s")
            update_values.append(password)
        
        if 'full_name' in data:
            update_fields.append("full_name = %s")
            update_values.append(data['full_name'])
        
        if 'email' in data:
            update_fields.append("email = %s")
            update_values.append(data['email'])
        
        if 'phone' in data:
            update_fields.append("phone = %s")
            update_values.append(data['phone'])
        
        if 'whatsapp_notifications' in data:
            update_fields.append("whatsapp_notifications = %s")
            update_values.append(data['whatsapp_notifications'])
        
        # Role and customer changes only for admins
        if user_role == 'admin':
            if 'role' in data:
                update_fields.append("role = %s")
                update_values.append(data['role'])
            
            if 'customer_id' in data:
                update_fields.append("customer_id = %s")
                update_values.append(data['customer_id'])
        
        if 'department' in data:
            update_fields.append("department = %s")
            update_values.append(data['department'])
        
        if 'active' in data:
            update_fields.append("active = %s")
            update_values.append(data['active'])
        
        if not update_fields:
            return jsonify({'error': 'No fields to update'}), 400
        
        # Add timestamp
        update_fields.append("updated_at = CURRENT_TIMESTAMP")
        
        # Execute update
        update_values.append(user_id)
        query = f"UPDATE users SET {', '.join(update_fields)} WHERE id = %s"
        cur.execute(query, update_values)
        
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({
            'status': 'success',
            'message': 'משתמש עודכן בהצלחה'
        })
        
    except Exception as e:
        logger.error(f"Error updating user: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/admin/users/delete/<int:user_id>', methods=['DELETE'])
@admin_required
def delete_user(user_id):
    """Admin: Delete user"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available'}), 500
            
        cur = conn.cursor()
        
        # Check if user exists
        cur.execute("SELECT username FROM users WHERE id = %s", (user_id,))
        result = cur.fetchone()
        if not result:
            return jsonify({'error': 'User not found'}), 404
        
        username = result[0]
        
        # Prevent deleting the last admin
        cur.execute("SELECT COUNT(*) FROM users WHERE role = 'admin' AND active = true")
        admin_count = cur.fetchone()[0]
        
        cur.execute("SELECT role FROM users WHERE id = %s", (user_id,))
        user_role = cur.fetchone()[0]
        
        if user_role == 'admin' and admin_count <= 1:
            return jsonify({'error': 'Cannot delete the last admin user'}), 400
        
        # Delete user
        cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
        
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({
            'status': 'success',
            'message': f'משתמש {username} נמחק בהצלחה'
        })
        
    except Exception as e:
        logger.error(f"Error deleting user: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/admin/users/<int:user_id>', methods=['GET'])
@admin_required
def get_user(user_id):
    """Admin: Get single user details"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available'}), 500
            
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT u.id, u.username, u.full_name, u.email, u.role, u.department, u.customer_id, 
                   u.active, u.created_at, u.updated_at, u.plain_password, c.name as customer_name
            FROM users u
            LEFT JOIN customers c ON u.customer_id = c.id
            WHERE u.id = %s
        """, (user_id,))
        
        user = cur.fetchone()
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        user_dict = dict(user)
        user_dict['created_at'] = user_dict['created_at'].isoformat() if user_dict['created_at'] else None
        user_dict['updated_at'] = user_dict['updated_at'].isoformat() if user_dict['updated_at'] else None
        
        cur.close()
        conn.close()
        
        return jsonify({'user': user_dict})
        
    except Exception as e:
        logger.error(f"Error getting user: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/admin/leads/<int:lead_id>/assign', methods=['PUT'])
@admin_required
def assign_lead(lead_id):
    """Admin: Assign lead to user"""
    try:
        data = request.get_json()
        assigned_to = data.get('assigned_to', '').strip()
        
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available'}), 500
            
        cur = conn.cursor()
        
        # Check if lead exists
        cur.execute("SELECT id, name FROM leads WHERE id = %s", (lead_id,))
        lead = cur.fetchone()
        if not lead:
            return jsonify({'error': 'Lead not found'}), 404
        
        lead_name = lead[1]
        
        # If assigning to a user, validate user exists
        if assigned_to:
            cur.execute("SELECT full_name FROM users WHERE username = %s AND active = true", (assigned_to,))
            user = cur.fetchone()
            if not user:
                return jsonify({'error': 'User not found or inactive'}), 400
            user_full_name = user[0]
        else:
            user_full_name = None
        
        # Update lead assignment
        cur.execute("""
            UPDATE leads SET assigned_to = %s, updated_at = CURRENT_TIMESTAMP 
            WHERE id = %s
        """, (assigned_to if assigned_to else None, lead_id))
        
        # Log assignment activity
        cur.execute("""
            INSERT INTO lead_activities 
            (lead_id, user_name, activity_type, description)
            VALUES (%s, %s, %s, %s)
        """, (
            lead_id, 
            session.get('username', 'מנהל'),
            'assignment',
            f'ליד הוקצה ל{user_full_name}' if assigned_to else 'הקצאת הליד בוטלה'
        ))
        
        conn.commit()
        cur.close()
        conn.close()
        
        # Send email notification to assigned user
        if assigned_to:
            try:
                # Get assigned user's email
                conn_email = get_db_connection()
                if conn_email:
                    cur_email = conn_email.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                    cur_email.execute("""
                        SELECT email, full_name, customer_id FROM users 
                        WHERE username = %s AND active = true AND email IS NOT NULL
                    """, (assigned_to,))
                    
                    assigned_user = cur_email.fetchone()
                    cur_email.close()
                    conn_email.close()
                    
                    if assigned_user and assigned_user['email']:
                        logger.info(f"Sending assignment email to {assigned_user['full_name']} ({assigned_user['email']})")
                        email_sent = send_email_notification(
                            customer_id=assigned_user['customer_id'],
                            to_email=assigned_user['email'],
                            to_username=assigned_user['full_name'],
                            lead_name=lead_name,
                            lead_phone=lead_phone,
                            lead_email=lead_email,
                            platform=platform,
                            campaign_name=campaign_name,
                            email_type="assignment",
                            assigned_to=session.get('full_name', 'מנהל קמפיין')
                        )
                        if email_sent:
                            logger.info(f"Assignment email sent to {assigned_user['email']}")
                        else:
                            logger.warning(f"Failed to send assignment email to {assigned_user['email']}")
                            
            except Exception as email_error:
                logger.error(f"Error sending assignment email: {email_error}")
        
        return jsonify({
            'status': 'success',
            'message': f'ליד {lead_name} הוקצה בהצלחה' if assigned_to else f'הקצאת ליד {lead_name} בוטלה'
        })
        
    except Exception as e:
        logger.error(f"Error assigning lead: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/leads/<int:lead_id>/assign', methods=['POST'])
@campaign_manager_required
def assign_lead_campaign_manager(lead_id):
    """Campaign Manager & Admin: Assign lead to user"""
    try:
        data = request.get_json()
        assigned_to = data.get('assigned_to', '').strip()
        
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available'}), 500
            
        cur = conn.cursor()
        
        # Get user's customer context
        user_role = session.get('role')
        if user_role == 'admin':
            selected_customer_id = session.get('selected_customer_id', 1)
        else:  # campaign_manager
            selected_customer_id = session.get('selected_customer_id') or session.get('customer_id')
            
        # Debug logging
        logger.info(f"Assignment attempt by {session.get('username')} (role: {user_role})")
        logger.info(f"Customer context: {selected_customer_id}")
        
        if not selected_customer_id:
            logger.error(f"No customer_id found in session for {session.get('username')}")
            return jsonify({'error': 'No customer assigned to your account'}), 400
        
        # Check if lead exists and belongs to user's customer scope - get all details for email
        cur.execute("SELECT id, name, customer_id, phone, email, platform, campaign_name FROM leads WHERE id = %s", (lead_id,))
        lead = cur.fetchone()
        if not lead:
            return jsonify({'error': 'Lead not found'}), 404
        
        # Verify lead belongs to user's customer scope
        lead_customer_id = lead[2] or selected_customer_id
        if user_role == 'campaign_manager' and lead_customer_id != selected_customer_id:
            return jsonify({'error': 'Access denied'}), 403
            
        lead_name = lead[1]
        lead_phone = lead[3]
        lead_email = lead[4]  
        platform = lead[5]
        campaign_name = lead[6]
        
        # If assigning to a user, validate user exists and belongs to same customer
        if assigned_to:
            if user_role == 'admin':
                cur.execute("""
                    SELECT full_name FROM users 
                    WHERE username = %s AND active = true AND customer_id = %s
                """, (assigned_to, selected_customer_id))
            else:  # campaign_manager
                cur.execute("""
                    SELECT full_name FROM users 
                    WHERE username = %s AND active = true AND customer_id = %s
                """, (assigned_to, selected_customer_id))
                
            user = cur.fetchone()
            if not user:
                return jsonify({'error': 'User not found or not accessible'}), 400
            user_full_name = user[0]
        else:
            user_full_name = None
        
        # Update lead assignment
        cur.execute("""
            UPDATE leads SET assigned_to = %s, updated_at = CURRENT_TIMESTAMP 
            WHERE id = %s
        """, (assigned_to if assigned_to else None, lead_id))
        
        # Log assignment activity
        cur.execute("""
            INSERT INTO lead_activities 
            (lead_id, user_name, activity_type, description, customer_id)
            VALUES (%s, %s, %s, %s, %s)
        """, (
            lead_id, 
            session.get('username', 'מנהל'),
            'assignment',
            f'ליד הוקצה ל{user_full_name}' if assigned_to else 'הקצאת הליד בוטלה',
            selected_customer_id
        ))
        
        # Send WhatsApp notification to assigned user
        if assigned_to and user_full_name:
            try:
                # Get user's phone number for notification
                cur.execute("SELECT phone, whatsapp_notifications FROM users WHERE username = %s", (assigned_to,))
                user_contact = cur.fetchone()
                
                if user_contact and user_contact[0] and user_contact[1]:  # Has phone and notifications enabled
                    user_phone = user_contact[0]
                    
                    # Create WhatsApp message
                    message = f"""🎯 ליד חדש הוקצה אליך!

📋 שם הליד: {lead_name}
👤 הוקצה על ידי: {session.get('full_name', session.get('username', 'מנהל'))}
⏰ זמן הקצאה: {datetime.now().strftime('%H:%M %d/%m/%Y')}

🔗 לצפייה בליד: https://eadmanager-fresh-2024-dev-f83e51d73e01.herokuapp.com/dashboard

בהצלחה! 💪"""
                    
                    # Send WhatsApp notification
                    notification_sent = send_whatsapp_notification(user_phone, message)
                    if notification_sent:
                        logger.info(f"WhatsApp notification sent to {assigned_to} ({user_phone}) for lead {lead_id}")
                    else:
                        logger.warning(f"Failed to send WhatsApp notification to {assigned_to}")
                else:
                    logger.info(f"User {assigned_to} has no phone or notifications disabled")
                    
            except Exception as e:
                logger.error(f"Error sending WhatsApp notification: {e}")
        
        # Send email notification to assigned user (Campaign Manager Assignment) - BEFORE commit
        if assigned_to:
            logger.info(f"Campaign Manager assignment detected: {assigned_to}, attempting to send email notification")
            try:
                # Get assigned user's email using same connection
                cur.execute("""
                    SELECT email, full_name, customer_id FROM users 
                    WHERE username = %s AND active = true AND email IS NOT NULL
                """, (assigned_to,))
                
                assigned_user = cur.fetchone()
                
                if assigned_user and assigned_user[0]:  # assigned_user[0] is email
                    logger.info(f"Sending assignment email to {assigned_user[1]} ({assigned_user[0]})")
                    
                    # Get lead details for email
                    email_sent = send_email_notification(
                        customer_id=assigned_user[2],  # customer_id
                        to_email=assigned_user[0],     # email
                        to_username=assigned_user[1],  # full_name
                        lead_name=lead_name,
                        lead_phone=lead_phone,
                        lead_email=lead_email,
                        platform=platform,
                        campaign_name=campaign_name,
                        email_type="assignment",
                        assigned_to=session.get('full_name', 'מנהל קמפיין')
                    )
                    if email_sent:
                        logger.info(f"Assignment email sent to {assigned_user[0]}")
                    else:
                        logger.warning(f"Failed to send assignment email to {assigned_user[0]}")
                else:
                    logger.warning(f"User {assigned_to} not found or has no email address")
                        
            except Exception as email_error:
                logger.error(f"Error sending assignment email: {email_error}")

        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({
            'status': 'success',
            'message': f'ליד {lead_name} הוקצה בהצלחה' if assigned_to else f'הקצאת ליד {lead_name} בוטלה'
        })
        
    except Exception as e:
        logger.error(f"Error assigning lead: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/admin/customers')
@admin_required
def customer_management():
    """Admin-only customer management page"""
    return render_template('customer_management.html')

@app.route('/admin/campaigns')
@admin_required
def campaigns_management():
    """Admin-only campaigns management page"""
    return render_template('campaigns_management.html')

@app.route('/admin/campaigns/create', methods=['POST'])
@admin_required
def create_campaign():
    """API: Create new campaign"""
    try:
        data = request.get_json()

        # Validate required fields
        if not data.get('customer_id'):
            return jsonify({'error': 'חסר מזהה לקוח'}), 400
        if not data.get('campaign_name'):
            return jsonify({'error': 'חסר שם קמפיין'}), 400

        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available'}), 500

        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Insert new campaign
        cur.execute("""
            INSERT INTO campaigns (customer_id, campaign_name, campaign_type, sheet_id, sheet_url, active)
            VALUES (%s, %s, 'google_sheets', %s, %s, %s)
            RETURNING id, campaign_name, customer_id
        """, (
            data['customer_id'],
            data['campaign_name'],
            data.get('sheet_id'),
            data.get('sheet_url'),
            data.get('active', True)
        ))

        new_campaign = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        return jsonify({'success': True, 'campaign': new_campaign})

    except Exception as e:
        logger.error(f"Error creating campaign: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/admin/campaigns/api')
@campaign_manager_required
def get_campaigns_api():
    """API: Get campaigns with customer names (filtered by user's customer for campaign managers)"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available'}), 500

        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # Get user role and customer context
        user_role = session.get('role')
        user_customer_id = session.get('selected_customer_id') or session.get('customer_id')
        
        # Campaign managers only see their customer's campaigns, admins see all
        if user_role == 'campaign_manager':
            if not user_customer_id:
                return jsonify({'error': 'No customer assigned to your account'}), 400
            
            cur.execute("""
                SELECT
                    c.id,
                    c.customer_id,
                    c.campaign_name,
                    c.campaign_type,
                    c.sheet_id,
                    c.sheet_url,
                    c.active,
                    cu.name as customer_name
                FROM campaigns c
                LEFT JOIN customers cu ON c.customer_id = cu.id
                WHERE c.customer_id = %s
                ORDER BY c.id DESC
            """, (user_customer_id,))
        else:
            # Admin sees all campaigns
            cur.execute("""
                SELECT
                    c.id,
                    c.customer_id,
                    c.campaign_name,
                    c.campaign_type,
                    c.sheet_id,
                    c.sheet_url,
                    c.active,
                    cu.name as customer_name
                FROM campaigns c
                LEFT JOIN customers cu ON c.customer_id = cu.id
                ORDER BY c.id DESC
            """)
        
        campaigns = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({'campaigns': campaigns})

    except Exception as e:
        logger.error(f"Error fetching campaigns: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/admin/campaigns/delete/<int:campaign_id>', methods=['DELETE'])
@admin_required
def delete_campaign(campaign_id):
    """API: Delete a campaign"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available'}), 500

        cur = conn.cursor()
        cur.execute("DELETE FROM campaigns WHERE id = %s", (campaign_id,))
        conn.commit()
        cur.close()
        conn.close()

        return jsonify({'success': True, 'message': 'Campaign deleted'})

    except Exception as e:
        logger.error(f"Error deleting campaign: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/admin/campaigns/update/<int:campaign_id>', methods=['PUT'])
@admin_required
def update_campaign(campaign_id):
    """API: Update a campaign"""
    try:
        data = request.get_json()

        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available'}), 500

        cur = conn.cursor()

        # Build update query dynamically based on provided fields
        update_fields = []
        params = []

        if 'customer_id' in data:
            update_fields.append("customer_id = %s")
            params.append(data['customer_id'])

        if 'campaign_name' in data:
            update_fields.append("campaign_name = %s")
            params.append(data['campaign_name'])

        if 'sheet_id' in data:
            update_fields.append("sheet_id = %s")
            params.append(data['sheet_id'] if data['sheet_id'] else None)

        if 'sheet_url' in data:
            update_fields.append("sheet_url = %s")
            params.append(data['sheet_url'] if data['sheet_url'] else None)

        if 'active' in data:
            update_fields.append("active = %s")
            params.append(data['active'])

        if not update_fields:
            return jsonify({'error': 'No fields to update'}), 400

        # Add campaign_id to params
        params.append(campaign_id)

        query = f"UPDATE campaigns SET {', '.join(update_fields)} WHERE id = %s"
        cur.execute(query, params)
        conn.commit()
        cur.close()
        conn.close()

        return jsonify({'success': True, 'message': 'Campaign updated'})

    except Exception as e:
        logger.error(f"Error updating campaign: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/admin/campaigns/sync/<int:campaign_id>', methods=['POST'])
@campaign_manager_required
def sync_campaign(campaign_id):
    """Sync leads from Google Sheet for a specific campaign"""
    try:
        import requests
        import csv
        from io import StringIO

        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available'}), 500

        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Get campaign details
        cur.execute("""
            SELECT * FROM campaigns
            WHERE id = %s
        """, (campaign_id,))
        campaign = cur.fetchone()

        if not campaign:
            return jsonify({'error': 'Campaign not found'}), 404

        if not campaign['sheet_url']:
            return jsonify({'error': 'No sheet URL configured for this campaign'}), 400

        logger.info(f"=== Starting sync for campaign: {campaign['campaign_name']} ===")

        # Extract spreadsheet ID from URL
        sheet_url = campaign['sheet_url']
        sheet_id_match = re.search(r'/d/([a-zA-Z0-9-_]+)', sheet_url)
        if not sheet_id_match:
            return jsonify({'error': 'Invalid Google Sheet URL'}), 400

        spreadsheet_id = sheet_id_match.group(1)

        # Extract gid (sheet/tab ID) from URL if present
        gid_match = re.search(r'gid=(\d+)', sheet_url)
        gid = gid_match.group(1) if gid_match else '0'
        gid_key = f'gid_{gid}'  # e.g., "gid_0" or "gid_123456"

        # Try to fetch the actual tab name from Google Sheets API
        tab_name = get_tab_name_for_gid(spreadsheet_id, gid)
        if not tab_name:
            tab_name = f"gid_{gid}"  # Fallback if API not configured

        logger.info(f"Syncing tab: {tab_name} (gid={gid})")

        # Build CSV export URL
        csv_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv&gid={gid}"

        logger.info(f"Fetching tab gid={gid} from: {csv_url}")

        # Fetch the CSV data
        response = requests.get(csv_url, timeout=30)
        response.raise_for_status()

        # Parse CSV
        csv_data = StringIO(response.text)
        reader = csv.DictReader(csv_data)

        # Get headers
        headers = reader.fieldnames
        logger.info(f"Sheet headers: {headers}")

        # Get starting row for THIS specific tab (from JSONB)
        last_synced_data = campaign.get('last_synced_row') or {}
        if isinstance(last_synced_data, int):
            # Handle old INTEGER format: convert to JSONB format
            last_synced_data = {'gid_0': last_synced_data} if last_synced_data > 1 else {}
        last_synced_row = last_synced_data.get(gid_key, 1)
        logger.info(f"Last synced row for {gid_key}: {last_synced_row}")

        new_leads = 0
        duplicates = 0
        errors = 0
        current_row = 1  # CSV row counter (header is row 0)

        for row_data in reader:
            current_row += 1

            # Skip rows we've already processed
            if current_row <= last_synced_row:
                continue

            try:
                # Skip empty rows
                if not any(row_data.values()):
                    logger.info(f"Row {current_row}: Empty, skipping")
                    continue

                # Extract lead data with Hebrew field mapping
                name = (row_data.get('שם מלא') or row_data.get('שם') or
                       row_data.get('name') or row_data.get('Name') or '')

                phone = (row_data.get('מס פלאפון') or row_data.get('טלפון') or
                        row_data.get('מספר טלפון') or row_data.get('phone') or
                        row_data.get('Phone Number') or row_data.get('טלפון:') or '')

                email = (row_data.get('מייל') or row_data.get('אימייל') or
                        row_data.get('דוא"ל') or row_data.get('email') or
                        row_data.get('Email') or row_data.get('אימייל:') or '')

                # Clean phone number
                if phone:
                    phone = str(phone).strip().replace('-', '').replace(' ', '')

                # Skip if no name or contact info
                if not name and not phone and not email:
                    logger.info(f"Row {current_row}: No name/phone/email, skipping")
                    continue

                logger.info(f"Row {current_row}: {name}, {phone}, {email}")

                # Check for duplicate by phone or email
                duplicate_check_sql = """
                    SELECT id FROM leads
                    WHERE customer_id = %s
                    AND (
                        (phone IS NOT NULL AND phone = %s)
                        OR (email IS NOT NULL AND email = %s)
                    )
                    LIMIT 1
                """
                cur.execute(duplicate_check_sql, (campaign['customer_id'], phone or '', email or ''))
                existing_lead = cur.fetchone()

                if existing_lead:
                    logger.info(f"Row {current_row}: Duplicate found (Lead ID: {existing_lead['id']}), skipping")
                    duplicates += 1
                    continue

                # Build raw_data JSONB with all fields
                raw_data = {
                    'source': 'google_sheets',
                    'sheet_id': campaign['sheet_id'],
                    'campaign_name': campaign['campaign_name'],
                    'row_number': current_row
                }

                # Add all CSV fields to raw_data
                for key, value in row_data.items():
                    if value:
                        raw_data[key] = value

                # Insert the lead
                cur.execute("""
                    INSERT INTO leads (
                        customer_id, name, email, phone, status,
                        campaign, raw_data, received_at
                    ) VALUES (%s, %s, %s, %s, 'new', %s, %s, CURRENT_TIMESTAMP)
                    RETURNING id
                """, (
                    campaign['customer_id'],
                    name or 'Unknown',
                    email if email else None,
                    phone if phone else None,
                    campaign['campaign_name'],
                    json.dumps(raw_data)
                ))

                lead_id = cur.fetchone()['id']

                # Log the activity
                cur.execute("""
                    INSERT INTO lead_activities (
                        lead_id, customer_id, user_id, activity_type, description
                    ) VALUES (%s, %s, NULL, 'lead_received', %s)
                """, (
                    lead_id,
                    campaign['customer_id'],
                    f"Lead imported from Google Sheet: {campaign['campaign_name']}, Row {current_row}"
                ))

                new_leads += 1
                logger.info(f"Row {current_row}: Created lead ID {lead_id}")

            except Exception as row_error:
                logger.error(f"Row {current_row}: Error processing - {str(row_error)}")
                errors += 1
                continue

        # Update last_synced_row JSONB with this tab's progress
        # Merge with existing data to preserve other tabs' tracking
        last_synced_data[gid_key] = current_row

        cur.execute("""
            UPDATE campaigns
            SET last_synced_row = %s::jsonb, last_synced_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (json.dumps(last_synced_data), campaign_id))

        conn.commit()
        cur.close()
        conn.close()

        result = {
            'success': True,
            'campaign_name': campaign['campaign_name'],
            'tab_gid': gid,
            'total_rows_checked': current_row - last_synced_row,
            'new_leads': new_leads,
            'duplicates': duplicates,
            'errors': errors,
            'last_synced_row': current_row,
            'last_synced_data': last_synced_data
        }

        logger.info(f"=== Sync complete: {result} ===")

        return jsonify(result)

    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching Google Sheet: {str(e)}")
        return jsonify({'error': f'Failed to fetch Google Sheet: {str(e)}'}), 500
    except Exception as e:
        logger.error(f"Error syncing campaign: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/admin/campaigns/sync-all', methods=['POST'])
@campaign_manager_required
def sync_all_campaigns():
    """Sync all active campaigns that have sheet URLs"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available'}), 500

        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Get all active campaigns with sheet URLs
        cur.execute("""
            SELECT id, campaign_name, sheet_url
            FROM campaigns
            WHERE active = true AND sheet_url IS NOT NULL AND sheet_url != ''
            ORDER BY id
        """)
        campaigns = cur.fetchall()
        cur.close()
        conn.close()

        if not campaigns:
            return jsonify({
                'success': True,
                'message': 'No active campaigns with sheet URLs found',
                'results': []
            })

        logger.info(f"=== Starting sync for {len(campaigns)} campaigns ===")

        results = []
        total_new_leads = 0
        total_duplicates = 0
        total_errors = 0

        # Sync each campaign
        for campaign in campaigns:
            try:
                # Call the existing sync_campaign function logic
                import requests
                import csv
                from io import StringIO

                conn = get_db_connection()
                if not conn:
                    results.append({
                        'campaign_id': campaign['id'],
                        'campaign_name': campaign['campaign_name'],
                        'success': False,
                        'error': 'Database not available'
                    })
                    continue

                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

                # Get full campaign details
                cur.execute("SELECT * FROM campaigns WHERE id = %s", (campaign['id'],))
                full_campaign = cur.fetchone()

                # Extract spreadsheet ID from URL
                sheet_url = full_campaign['sheet_url']
                sheet_id_match = re.search(r'/d/([a-zA-Z0-9-_]+)', sheet_url)
                if not sheet_id_match:
                    results.append({
                        'campaign_id': campaign['id'],
                        'campaign_name': campaign['campaign_name'],
                        'success': False,
                        'error': 'Invalid Google Sheet URL'
                    })
                    cur.close()
                    conn.close()
                    continue

                spreadsheet_id = sheet_id_match.group(1)
                gid_match = re.search(r'gid=(\d+)', sheet_url)
                gid = gid_match.group(1) if gid_match else '0'
                gid_key = f'gid_{gid}'

                # Build CSV export URL
                csv_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv&gid={gid}"

                # Fetch the CSV data
                response = requests.get(csv_url, timeout=30)
                response.raise_for_status()

                # Parse CSV
                csv_data = StringIO(response.text)
                reader = csv.DictReader(csv_data)

                # Get starting row for THIS specific tab (from JSONB)
                last_synced_data = full_campaign.get('last_synced_row') or {}
                if isinstance(last_synced_data, int):
                    last_synced_data = {'gid_0': last_synced_data} if last_synced_data > 1 else {}
                last_synced_row = last_synced_data.get(gid_key, 1)

                new_leads = 0
                duplicates = 0
                errors = 0
                current_row = 1

                for row_data in reader:
                    current_row += 1

                    if current_row <= last_synced_row:
                        continue

                    try:
                        if not any(row_data.values()):
                            continue

                        name = (row_data.get('שם מלא') or row_data.get('שם') or
                               row_data.get('name') or row_data.get('Name') or '')
                        phone = (row_data.get('מס פלאפון') or row_data.get('טלפון') or
                                row_data.get('מספר טלפון') or row_data.get('phone') or
                                row_data.get('Phone Number') or row_data.get('טלפון:') or '')
                        email = (row_data.get('מייל') or row_data.get('אימייל') or
                                row_data.get('דוא"ל') or row_data.get('email') or
                                row_data.get('Email') or row_data.get('אימייל:') or '')

                        if phone:
                            phone = str(phone).strip().replace('-', '').replace(' ', '')

                        if not name and not phone and not email:
                            continue

                        # Check for duplicate
                        cur.execute("""
                            SELECT id FROM leads
                            WHERE customer_id = %s
                            AND ((phone IS NOT NULL AND phone = %s) OR (email IS NOT NULL AND email = %s))
                            LIMIT 1
                        """, (full_campaign['customer_id'], phone or '', email or ''))

                        if cur.fetchone():
                            duplicates += 1
                            continue

                        # Build raw_data
                        raw_data = {
                            'source': 'google_sheets',
                            'sheet_id': full_campaign['sheet_id'],
                            'campaign_name': full_campaign['campaign_name'],
                            'row_number': current_row
                        }
                        for key, value in row_data.items():
                            if value:
                                raw_data[key] = value

                        # Insert lead
                        cur.execute("""
                            INSERT INTO leads (
                                customer_id, name, email, phone, status, campaign, raw_data, received_at
                            ) VALUES (%s, %s, %s, %s, 'new', %s, %s, CURRENT_TIMESTAMP)
                            RETURNING id
                        """, (
                            full_campaign['customer_id'],
                            name or 'Unknown',
                            email if email else None,
                            phone if phone else None,
                            full_campaign['campaign_name'],
                            json.dumps(raw_data)
                        ))

                        lead_id = cur.fetchone()['id']

                        # Log activity
                        cur.execute("""
                            INSERT INTO lead_activities (
                                lead_id, customer_id, user_id, activity_type, description
                            ) VALUES (%s, %s, NULL, 'lead_received', %s)
                        """, (
                            lead_id,
                            full_campaign['customer_id'],
                            f"Lead imported from Google Sheet: {full_campaign['campaign_name']}, Row {current_row}"
                        ))

                        new_leads += 1

                    except Exception as row_error:
                        logger.error(f"Row {current_row} error: {str(row_error)}")
                        errors += 1
                        continue

                # Update last_synced_row JSONB with this tab's progress
                last_synced_data[gid_key] = current_row

                cur.execute("""
                    UPDATE campaigns SET last_synced_row = %s::jsonb, last_synced_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (json.dumps(last_synced_data), campaign['id']))

                conn.commit()
                cur.close()
                conn.close()

                total_new_leads += new_leads
                total_duplicates += duplicates
                total_errors += errors

                results.append({
                    'campaign_id': campaign['id'],
                    'campaign_name': campaign['campaign_name'],
                    'tab_gid': gid,
                    'success': True,
                    'new_leads': new_leads,
                    'duplicates': duplicates,
                    'errors': errors,
                    'last_synced_row': current_row
                })

                logger.info(f"✅ {campaign['campaign_name']}: {new_leads} new, {duplicates} duplicates")

            except Exception as campaign_error:
                logger.error(f"Error syncing {campaign['campaign_name']}: {str(campaign_error)}")
                results.append({
                    'campaign_id': campaign['id'],
                    'campaign_name': campaign['campaign_name'],
                    'success': False,
                    'error': str(campaign_error)
                })

        logger.info(f"=== Sync all complete: {total_new_leads} new leads total ===")

        return jsonify({
            'success': True,
            'total_campaigns': len(campaigns),
            'total_new_leads': total_new_leads,
            'total_duplicates': total_duplicates,
            'total_errors': total_errors,
            'results': results
        })

    except Exception as e:
        logger.error(f"Error in sync all campaigns: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/admin/customers/api')
@admin_required
def get_customers():
    """API: Get all customers"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available'}), 500
            
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT c.*, 
                   COUNT(l.id) as lead_count,
                   COUNT(u.id) as user_count
            FROM customers c
            LEFT JOIN leads l ON c.id = l.customer_id
            LEFT JOIN users u ON c.id = u.customer_id
            GROUP BY c.id
            ORDER BY c.id
        """)
        customers = cur.fetchall()
        
        cur.close()
        conn.close()
        
        return jsonify(customers)
        
    except Exception as e:
        logger.error(f"Error fetching customers: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/admin/customers/create', methods=['POST'])
@admin_required
def create_customer():
    """API: Create new customer"""
    try:
        data = request.get_json()
        
        required_fields = ['name']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'חסר שדה חובה: {field}'}), 400
        
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available'}), 500
            
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO customers (name, webhook_url, zapier_webhook_key, zapier_account_email, 
                                 facebook_app_id, instagram_app_id, api_settings, active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            data['name'],
            data.get('webhook_url', ''),
            data.get('zapier_webhook_key', ''),
            data.get('zapier_account_email', ''),
            data.get('facebook_app_id', ''),
            data.get('instagram_app_id', ''),
            json.dumps(data.get('api_settings', {})),
            data.get('active', True)
        ))
        
        customer_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({
            'status': 'success',
            'message': f'לקוח {data["name"]} נוצר בהצלחה',
            'customer_id': customer_id
        })
        
    except Exception as e:
        logger.error(f"Error creating customer: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/admin/customers/update/<int:customer_id>', methods=['PUT'])
@admin_required
def update_customer(customer_id):
    """API: Update existing customer"""
    try:
        data = request.get_json()
        
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available'}), 500
            
        cur = conn.cursor()
        
        # Build update query dynamically based on provided fields
        update_fields = []
        update_values = []
        
        allowed_fields = ['name', 'webhook_url', 'zapier_webhook_key', 'zapier_account_email', 
                         'facebook_app_id', 'instagram_app_id', 'active', 
                         'sender_email', 'smtp_server', 'smtp_port', 'smtp_username', 
                         'smtp_password', 'email_notifications_enabled']
        
        for field in allowed_fields:
            if field in data:
                update_fields.append(f"{field} = %s")
                update_values.append(data[field])
        
        if 'api_settings' in data:
            update_fields.append("api_settings = %s")
            update_values.append(json.dumps(data['api_settings']))
        
        if not update_fields:
            return jsonify({'error': 'No valid fields to update'}), 400
            
        update_values.append(customer_id)
        query = f"UPDATE customers SET {', '.join(update_fields)} WHERE id = %s"
        
        cur.execute(query, update_values)
        
        if cur.rowcount == 0:
            return jsonify({'error': 'לקוח לא נמצא'}), 404
            
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({
            'status': 'success',
            'message': 'פרטי הלקוח עודכנו בהצלחה'
        })
        
    except Exception as e:
        logger.error(f"Error updating customer: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/admin/customers/delete/<int:customer_id>', methods=['DELETE'])
@admin_required
def delete_customer(customer_id):
    """API: Delete customer (only if no associated data)"""
    try:
        if customer_id == 1:
            return jsonify({'error': 'לא ניתן למחוק את לקוח ברירת המחדל'}), 400
            
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available'}), 500
            
        cur = conn.cursor()
        
        # Check if customer has associated data
        cur.execute("""
            SELECT 
                (SELECT COUNT(*) FROM leads WHERE customer_id = %s) as lead_count,
                (SELECT COUNT(*) FROM users WHERE customer_id = %s) as user_count
        """, (customer_id, customer_id))
        
        counts = cur.fetchone()
        if counts[0] > 0 or counts[1] > 0:
            return jsonify({'error': f'לא ניתן למחוק לקוח עם {counts[0]} לידים ו-{counts[1]} משתמשים'}), 400
        
        cur.execute("DELETE FROM customers WHERE id = %s", (customer_id,))
        
        if cur.rowcount == 0:
            return jsonify({'error': 'לקוח לא נמצא'}), 404
            
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({
            'status': 'success',
            'message': 'לקוח נמחק בהצלחה'
        })
        
    except Exception as e:
        logger.error(f"Error deleting customer: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/admin/select-customer', methods=['POST'])
@admin_required
def select_customer():
    """API: Set selected customer for current session"""
    try:
        data = request.get_json()
        customer_id = data.get('customer_id')
        
        if not customer_id:
            return jsonify({'error': 'Customer ID required'}), 400
            
        # Verify customer exists
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available'}), 500
            
        cur = conn.cursor()
        cur.execute("SELECT name FROM customers WHERE id = %s AND active = true", (customer_id,))
        customer = cur.fetchone()
        
        if not customer:
            return jsonify({'error': 'לקוח לא נמצא או לא פעיל'}), 404
            
        cur.close()
        conn.close()
        
        # Store in session
        session['selected_customer_id'] = customer_id
        session['selected_customer_name'] = customer[0]
        
        return jsonify({
            'status': 'success',
            'message': f'לקוח {customer[0]} נבחר בהצלחה',
            'customer_name': customer[0]
        })
        
    except Exception as e:
        logger.error(f"Error selecting customer: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/run-customer-migration')
@admin_required
def run_customer_migration():
    """Temporary route to run customer system migration"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available'}), 500
            
        cur = conn.cursor()
        
        # Check if customers table already exists
        cur.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = 'customers'
            );
        """)
        
        if cur.fetchone()[0]:
            return jsonify({'status': 'already_migrated', 'message': 'Customer system already exists'})
        
        # Run the migration SQL
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
        
        cur.execute(migration_sql)
        conn.commit()
        
        # Get migration results
        cur.execute("SELECT COUNT(*) FROM customers")
        customer_count = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM leads WHERE customer_id = 1")
        migrated_leads = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM users WHERE customer_id = 1")
        migrated_users = cur.fetchone()[0]
        
        cur.close()
        conn.close()
        
        return jsonify({
            'status': 'success',
            'message': 'Customer system migration completed successfully!',
            'results': {
                'customers_created': customer_count,
                'leads_migrated': migrated_leads,
                'users_migrated': migrated_users
            }
        })
        
    except Exception as e:
        logger.error(f"Migration error: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/debug/search/<search_term>')
def debug_search_lead(search_term):
    """Search for leads by name or phone to debug"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available'}), 500
            
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # Search by name or phone
        cur.execute("""
            SELECT id, name, phone, email, external_lead_id, created_time
            FROM leads 
            WHERE name ILIKE %s OR phone LIKE %s OR email ILIKE %s
            ORDER BY created_time DESC
            LIMIT 10
        """, (f'%{search_term}%', f'%{search_term}%', f'%{search_term}%'))
        
        leads = cur.fetchall()
        
        results = []
        for lead in leads:
            results.append({
                'id': lead['id'],
                'name': lead['name'],
                'phone': lead['phone'],
                'email': lead['email'],
                'external_lead_id': lead['external_lead_id'],
                'created_time': lead['created_time'].isoformat() if lead['created_time'] else None,
                'debug_url': f'/debug/lead/{lead["id"]}'
            })
        
        conn.close()
        
        return jsonify({
            'status': 'success',
            'search_term': search_term,
            'found': len(leads),
            'leads': results
        })
        
    except Exception as e:
        logger.error(f"Debug search error: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500

@app.route('/admin/clear-leads', methods=['POST'])
@admin_required
def clear_leads():
    """Clear all leads from the database - ADMIN ONLY"""
    try:
        # Safety check - require confirmation
        confirm = request.get_json()
        if not confirm or confirm.get('confirm') != 'DELETE_ALL_LEADS':
            return jsonify({
                'error': 'Safety confirmation required',
                'message': 'Send {"confirm": "DELETE_ALL_LEADS"} to proceed'
            }), 400
        
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available'}), 500
            
        cur = conn.cursor()
        
        # First, delete all lead activities
        cur.execute("DELETE FROM lead_activities")
        activities_deleted = cur.rowcount
        
        # Then delete all leads
        cur.execute("DELETE FROM leads")
        leads_deleted = cur.rowcount
        
        # Reset the ID sequence to start from 1 again
        cur.execute("ALTER SEQUENCE leads_id_seq RESTART WITH 1")
        
        conn.commit()
        cur.close()
        conn.close()
        
        logger.info(f"Cleared {leads_deleted} leads and {activities_deleted} activities from database")
        
        return jsonify({
            'status': 'success',
            'message': f'Successfully deleted {leads_deleted} leads and {activities_deleted} activities',
            'leads_deleted': leads_deleted,
            'activities_deleted': activities_deleted
        })
        
    except Exception as e:
        logger.error(f"Error clearing leads: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500

@app.route('/admin/leads/delete/<int:lead_id>', methods=['DELETE'])
@admin_required
def delete_lead(lead_id):
    """Delete a specific lead - ADMIN ONLY"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available'}), 500
            
        cur = conn.cursor()
        
        # First check if lead exists
        cur.execute("SELECT id, name FROM leads WHERE id = %s", (lead_id,))
        lead = cur.fetchone()
        
        if not lead:
            return jsonify({'error': f'Lead {lead_id} not found'}), 404
        
        lead_name = lead[1] if lead[1] else f"Lead {lead_id}"
        
        # Delete lead activities first (foreign key constraint)
        cur.execute("DELETE FROM lead_activities WHERE lead_id = %s", (lead_id,))
        activities_deleted = cur.rowcount
        
        # Delete the lead
        cur.execute("DELETE FROM leads WHERE id = %s", (lead_id,))
        lead_deleted = cur.rowcount
        
        conn.commit()
        cur.close()
        conn.close()
        
        if lead_deleted > 0:
            logger.info(f"Admin deleted lead {lead_id} ({lead_name}) and {activities_deleted} activities")
            return jsonify({
                'status': 'success',
                'message': f'Successfully deleted lead: {lead_name}',
                'lead_id': lead_id,
                'activities_deleted': activities_deleted
            })
        else:
            return jsonify({'error': 'Failed to delete lead'}), 500
        
    except Exception as e:
        logger.error(f"Error deleting lead {lead_id}: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500

@app.route('/admin/optimize-database', methods=['POST'])
@admin_required
def optimize_database():
    """Admin-only database optimization - create indexes and improve performance"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available'}), 500
            
        cur = conn.cursor()
        
        # Database indexes for performance
        indexes_created = 0
        indexes_to_create = [
            ("idx_leads_customer_id", "CREATE INDEX IF NOT EXISTS idx_leads_customer_id ON leads (customer_id)"),
            ("idx_leads_status", "CREATE INDEX IF NOT EXISTS idx_leads_status ON leads (status)"),
            ("idx_leads_assigned_to", "CREATE INDEX IF NOT EXISTS idx_leads_assigned_to ON leads (assigned_to)"),
            ("idx_leads_created_time", "CREATE INDEX IF NOT EXISTS idx_leads_created_time ON leads (created_time DESC)"),
            ("idx_leads_received_at", "CREATE INDEX IF NOT EXISTS idx_leads_received_at ON leads (received_at DESC)"),
            ("idx_leads_customer_time", "CREATE INDEX IF NOT EXISTS idx_leads_customer_time ON leads (customer_id, COALESCE(created_time, received_at) DESC)"),
            ("idx_users_username", "CREATE INDEX IF NOT EXISTS idx_users_username ON users (username)"),
            ("idx_users_active", "CREATE INDEX IF NOT EXISTS idx_users_active ON users (active)"),
            ("idx_activities_lead_id", "CREATE INDEX IF NOT EXISTS idx_activities_lead_id ON lead_activities (lead_id)"),
        ]
        
        for index_name, create_sql in indexes_to_create:
            try:
                cur.execute(create_sql)
                indexes_created += 1
                logger.info(f"Created index: {index_name}")
            except Exception as e:
                logger.warning(f"Index {index_name} creation failed: {e}")
        
        # Update table statistics
        cur.execute("ANALYZE leads")
        cur.execute("ANALYZE users") 
        cur.execute("ANALYZE lead_activities")
        
        conn.commit()
        cur.close()
        conn.close()
        
        logger.info(f"Database optimization completed: {indexes_created} indexes created")
        
        return jsonify({
            'status': 'success',
            'message': f'Database optimized successfully - {indexes_created} indexes created',
            'indexes_created': indexes_created
        })
        
    except Exception as e:
        logger.error(f"Error optimizing database: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500

@app.route('/health')
def health_check():
    """Health check endpoint for monitoring"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat()
    })

@app.route('/debug/leads-count')
def debug_leads_count():
    """Debug endpoint to check leads count and customer distribution"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available'}), 500
            
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # Total leads count
        cur.execute("SELECT COUNT(*) as total_leads FROM leads")
        total = cur.fetchone()['total_leads']
        
        # Leads by customer_id
        cur.execute("""
            SELECT customer_id, COUNT(*) as count 
            FROM leads 
            GROUP BY customer_id 
            ORDER BY customer_id
        """)
        by_customer = cur.fetchall()
        
        # Recent leads
        cur.execute("""
            SELECT id, name, customer_id, created_time, received_at
            FROM leads 
            ORDER BY COALESCE(created_time, received_at) DESC 
            LIMIT 5
        """)
        recent = cur.fetchall()
        
        cur.close()
        conn.close()
        
        return jsonify({
            'total_leads': total,
            'leads_by_customer': [dict(row) for row in by_customer],
            'recent_leads': [dict(row) for row in recent]
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/debug/leads-api')
def debug_leads_api():
    """Debug the leads API response without authentication"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available'}), 500
            
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # Simulate what the leads API does
        selected_customer_id = 1  # Default
        page = 1
        per_page = 100
        offset = 0
        
        # Count total
        cur.execute("""
            SELECT COUNT(*) 
            FROM leads l 
            WHERE l.customer_id = %s OR l.customer_id IS NULL
        """, (selected_customer_id,))
        total_count = cur.fetchone()[0]
        
        # Get leads
        base_fields = """
            l.id, l.external_lead_id, l.name, l.email, l.phone, l.platform, 
            l.campaign_name, l.form_name, l.lead_source, l.created_time, 
            l.received_at, l.status, l.assigned_to, l.priority, l.updated_at,
            u.full_name as assigned_full_name
        """
        
        cur.execute(f"""
            SELECT {base_fields}
            FROM leads l
            LEFT JOIN users u ON l.assigned_to = u.username AND u.active = true
            WHERE l.customer_id = %s OR l.customer_id IS NULL
            ORDER BY COALESCE(l.created_time, l.received_at) DESC
            LIMIT %s OFFSET %s
        """, (selected_customer_id, per_page, offset))
        
        leads = cur.fetchall()
        
        cur.close()
        conn.close()
        
        return jsonify({
            'debug_info': {
                'selected_customer_id': selected_customer_id,
                'page': page,
                'per_page': per_page,
                'offset': offset,
                'total_count': total_count,
                'leads_returned': len(leads)
            },
            'leads': [dict(lead) for lead in leads[:3]]  # Show first 3 leads
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/debug/quick-test')
def debug_quick_test():
    """Quick test to see what's happening"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'No DB connection'}), 500
            
        cur = conn.cursor()
        
        # Test the exact query from the leads API
        selected_customer_id = 1  # Hard-coded test
        
        cur.execute("""
            SELECT COUNT(*) 
            FROM leads l 
            WHERE l.customer_id = %s OR l.customer_id IS NULL
        """, (selected_customer_id,))
        count_result = cur.fetchone()[0]
        
        cur.execute("""
            SELECT id, name, customer_id 
            FROM leads 
            WHERE customer_id = %s OR customer_id IS NULL
            ORDER BY id DESC 
            LIMIT 5
        """, (selected_customer_id,))
        leads_sample = cur.fetchall()
        
        cur.close()
        conn.close()
        
        return jsonify({
            'success': True,
            'count_query_result': count_result,
            'sample_leads': leads_sample,
            'test_customer_id': selected_customer_id
        })
        
    except Exception as e:
        return jsonify({'error': f'Exception: {str(e)}'}), 500

@app.route('/debug/users-schema')
def debug_users_schema():
    """Check if phone columns exist in users table"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available'}), 500
            
        cur = conn.cursor()
        
        # Check users table schema
        cur.execute("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns 
            WHERE table_name = 'users' 
            ORDER BY ordinal_position
        """)
        columns = cur.fetchall()
        
        # Check if we can query phone field
        phone_exists = False
        whatsapp_exists = False
        try:
            cur.execute("SELECT phone FROM users LIMIT 1")
            phone_exists = True
        except Exception:
            pass
            
        try:
            cur.execute("SELECT whatsapp_notifications FROM users LIMIT 1")  
            whatsapp_exists = True
        except Exception:
            pass
            
        cur.close()
        conn.close()
        
        return jsonify({
            'columns': [{'name': col[0], 'type': col[1], 'nullable': col[2]} for col in columns],
            'phone_column_exists': phone_exists,
            'whatsapp_column_exists': whatsapp_exists
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/setup-phone-columns')
def setup_phone_columns():
    """Public endpoint to add phone columns to users table - ONE TIME SETUP"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available'}), 500
            
        cur = conn.cursor()
        
        results = []
        
        # Add phone column
        try:
            cur.execute("ALTER TABLE users ADD COLUMN phone VARCHAR(20)")
            results.append("✅ Added phone column")
            logger.info("Added phone column to users table")
        except Exception as e:
            results.append(f"⚠️ Phone column: {str(e)}")
        
        # Add whatsapp_notifications column
        try:
            cur.execute("ALTER TABLE users ADD COLUMN whatsapp_notifications BOOLEAN DEFAULT true")  
            results.append("✅ Added whatsapp_notifications column")
            logger.info("Added whatsapp_notifications column to users table")
        except Exception as e:
            results.append(f"⚠️ WhatsApp notifications column: {str(e)}")
        
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({
            'status': 'completed',
            'results': results,
            'message': 'Phone columns setup completed - refresh user management to see phone fields'
        })
        
    except Exception as e:
        logger.error(f"Error setting up phone columns: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/admin/add-phone-to-users', methods=['POST'])
@admin_required
def add_phone_column_to_users():
    """Admin: Add phone column to users table for WhatsApp notifications"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available'}), 500
            
        cur = conn.cursor()
        
        # Add phone column to users table
        try:
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR(20)")
            logger.info("Added phone column to users table")
        except Exception as e:
            logger.warning(f"Phone column might already exist: {e}")
        
        # Add whatsapp_notifications column
        try:
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS whatsapp_notifications BOOLEAN DEFAULT true")
            logger.info("Added whatsapp_notifications column to users table")
        except Exception as e:
            logger.warning(f"WhatsApp notifications column might already exist: {e}")
        
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({
            'status': 'success',
            'message': 'Phone and WhatsApp notification columns added to users table'
        })
        
    except Exception as e:
        logger.error(f"Error adding phone column: {e}")
        return jsonify({'error': str(e)}), 500

def send_whatsapp_notification(phone_number, message):
    """Send WhatsApp notification using WhatsApp Business API"""
    try:
        import requests
        
        # Format phone number for WhatsApp
        formatted_phone = format_phone_for_whatsapp(phone_number)
        if not formatted_phone:
            logger.warning(f"Invalid phone number for WhatsApp: {phone_number}")
            return False
        
        # WhatsApp Business API credentials
        access_token = os.environ.get('WHATSAPP_ACCESS_TOKEN', '').strip().replace('\n', '').replace('\r', '')
        phone_number_id = os.environ.get('WHATSAPP_PHONE_NUMBER_ID', '').strip()
        app_id = os.environ.get('WHATSAPP_APP_ID', '837819029404196').strip()
        
        # Log attempt for debugging
        logger.info(f"📱 Attempting WhatsApp to {formatted_phone}")
        logger.info(f"App ID: {app_id}, Phone Number ID: {phone_number_id}")
        logger.info(f"Access Token configured: {bool(access_token)}")
        
        if not access_token or not phone_number_id:
            logger.warning("⚠️ WhatsApp credentials not configured - logging notification")
            logger.info(f"📱 LOGGED WhatsApp to {formatted_phone}: {message}")
            return True  # Return True for testing without credentials
        
        # WhatsApp Business API endpoint
        url = f"https://graph.facebook.com/v18.0/{phone_number_id}/messages"
        
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
        
        # Message payload for WhatsApp Business API
        payload = {
            'messaging_product': 'whatsapp',
            'to': formatted_phone,
            'type': 'text',
            'text': {
                'body': message
            }
        }
        
        logger.info(f"📤 Sending WhatsApp API request to {url}")
        
        # Send WhatsApp message
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        
        if response.status_code == 200:
            result = response.json()
            message_id = result.get('messages', [{}])[0].get('id', 'unknown')
            logger.info(f"✅ WhatsApp sent successfully to {formatted_phone}")
            logger.info(f"📧 Message ID: {message_id}")
            return True
        else:
            logger.error(f"❌ WhatsApp API error {response.status_code}")
            logger.error(f"Response: {response.text}")
            return False
        
    except Exception as e:
        logger.error(f"❌ WhatsApp notification failed: {e}")
        return False

def format_phone_for_whatsapp(phone):
    """Format phone number for WhatsApp API"""
    if not phone:
        return None
        
    # Remove all non-digit characters
    clean_phone = ''.join(filter(str.isdigit, phone))
    
    # Handle Israeli phone numbers
    if clean_phone.startswith('972'):
        return clean_phone
    elif clean_phone.startswith('0'):
        return '972' + clean_phone[1:]
    elif len(clean_phone) == 9:
        return '972' + clean_phone
    else:
        return clean_phone

@app.route('/debug/lead/<int:lead_id>')
def debug_specific_lead(lead_id):
    """Debug endpoint to check a specific lead's raw data"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available'}), 500
            
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # Get the specific lead
        cur.execute("""
            SELECT id, name, email, phone, raw_data, created_time, external_lead_id
            FROM leads 
            WHERE id = %s
        """, (lead_id,))
        
        lead = cur.fetchone()
        
        if not lead:
            return jsonify({'error': f'Lead {lead_id} not found'}), 404
        
        raw_data = lead['raw_data']
        parsed_data = raw_data
        
        # Try to parse if it's a string
        if isinstance(raw_data, str) and raw_data.strip():
            try:
                parsed_data = json.loads(raw_data)
            except:
                parsed_data = raw_data
        
        # Look for form-related fields
        form_fields = {}
        if isinstance(parsed_data, dict):
            for key, value in parsed_data.items():
                # Look for any field that might be a form question
                if (value and value != '' and 
                    key not in ['id', 'name', 'email', 'phone', 'platform', 'created_time', 
                               'campaign_name', 'form_name', 'lead_source']):
                    form_fields[key] = value
        
        conn.close()
        
        return jsonify({
            'status': 'success',
            'lead': {
                'id': lead['id'],
                'name': lead['name'],
                'email': lead['email'],
                'phone': lead['phone'],
                'external_lead_id': lead['external_lead_id'],
                'created_time': lead['created_time'].isoformat() if lead['created_time'] else None
            },
            'raw_data_type': type(raw_data).__name__,
            'raw_data': parsed_data,
            'potential_form_fields': form_fields,
            'all_keys': list(parsed_data.keys()) if isinstance(parsed_data, dict) else None
        })
        
    except Exception as e:
        logger.error(f"Debug lead error: {e}")
        import traceback
        return jsonify({
            'status': 'error',
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500

@app.route('/debug/raw-data')
def debug_raw_data():
    """Debug endpoint to check raw_data structure"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available'}), 500
            
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # Get total count of leads
        cur.execute("SELECT COUNT(*) as total FROM leads")
        total_count = cur.fetchone()['total']
        
        # Get leads with any raw_data
        cur.execute("""
            SELECT id, name, raw_data, created_time
            FROM leads 
            WHERE raw_data IS NOT NULL 
            ORDER BY created_time DESC 
            LIMIT 10
        """)
        
        leads = cur.fetchall()
        
        result = []
        for lead in leads:
            raw_data = lead['raw_data']
            raw_data_type = type(raw_data).__name__
            
            # Try to parse if it's a string
            parsed_data = raw_data
            if isinstance(raw_data, str) and raw_data.strip():
                try:
                    parsed_data = json.loads(raw_data)
                except:
                    parsed_data = raw_data
            
            result.append({
                'lead_id': lead['id'],
                'lead_name': lead['name'],
                'created_time': lead['created_time'].isoformat() if lead['created_time'] else 'None',
                'raw_data_type': raw_data_type,
                'raw_data_length': len(str(raw_data)) if raw_data else 0,
                'raw_data': parsed_data,
                'raw_data_keys': list(parsed_data.keys()) if isinstance(parsed_data, dict) else 'Not a dict',
                'contains_hebrew_event_question': str(raw_data).find('התאריך הרצוי') != -1 if raw_data else False
            })
        
        conn.close()
        return jsonify({
            'status': 'success',
            'total_leads_in_db': total_count,
            'leads_with_raw_data': len(leads),
            'leads': result
        })
        
    except Exception as e:
        logger.error(f"Debug raw data error: {e}")
        import traceback
        return jsonify({
            'status': 'error',
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500

@app.route('/upload-facebook-csv', methods=['GET', 'POST'])
def upload_facebook_csv():
    """Upload Facebook CSV export with form data"""
    if request.method == 'GET':
        return render_template('upload_facebook_csv.html')
    
    try:
        if 'csv_file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
            
        file = request.files['csv_file']
        update_existing = request.form.get('update_existing') == '1'
        
        import csv
        import io
        
        # Read CSV
        stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
        csv_reader = csv.DictReader(stream)
        
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database connection failed'}), 500
            
        cur = conn.cursor()
        
        imported = 0
        updated = 0
        
        for row in csv_reader:
            # Build raw_data with ALL fields including form responses
            raw_data = {}
            custom_fields = {}
            field_index = 0
            
            # Process all columns - Facebook might have Hebrew headers
            for key, value in row.items():
                if value and value.strip():  # Only include non-empty values
                    raw_data[key] = value
                    
                    # Identify potential form response fields
                    standard_fields = ['full_name', 'name', 'email', 'phone', 'phone_number', 
                                     'created_time', 'id', 'campaign_name', 'form_name',
                                     'platform', 'ad_id', 'ad_name', 'adset_id', 'adset_name',
                                     'שם מלא', 'אימייל', 'דוא"ל', 'טלפון', 'תאריך יצירה',
                                     'שם', 'מזהה', 'קמפיין', 'טופס']
                    
                    # If not a standard field, treat as custom question
                    if key not in standard_fields and not any(std in key.lower() for std in ['id', 'time', 'date']):
                        custom_fields[f'custom_question_{field_index}'] = key
                        custom_fields[f'custom_answer_{field_index}'] = value
                        field_index += 1
            
            # Add custom fields to raw_data
            raw_data.update(custom_fields)
            
            # Extract basic fields with multiple fallbacks
            name = row.get('full_name') or row.get('שם מלא') or row.get('name') or row.get('שם')
            email = row.get('email') or row.get('אימייל') or row.get('דוא"ל')
            phone = row.get('phone_number') or row.get('טלפון') or row.get('phone')
            
            # Clean phone number
            if phone:
                phone = phone.replace(' ', '').replace('-', '')
                if not phone.startswith('+'):
                    phone = '+972' + phone.lstrip('0')
            
            # Check if lead exists
            if email or phone:
                if email and phone:
                    cur.execute("SELECT id FROM leads WHERE email = %s OR phone = %s LIMIT 1", (email, phone))
                elif email:
                    cur.execute("SELECT id FROM leads WHERE email = %s LIMIT 1", (email,))
                else:
                    cur.execute("SELECT id FROM leads WHERE phone = %s LIMIT 1", (phone,))
                
                existing = cur.fetchone()
                
                if existing and update_existing:
                    # Update existing lead with form data
                    cur.execute("""
                        UPDATE leads 
                        SET raw_data = %s, updated_at = NOW()
                        WHERE id = %s
                    """, (json.dumps(raw_data, ensure_ascii=False), existing[0]))
                    updated += 1
                elif not existing:
                    # Create new lead
                    cur.execute("""
                        INSERT INTO leads (name, email, phone, raw_data, customer_id, status, platform)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (name, email, phone, json.dumps(raw_data, ensure_ascii=False), 1, 'new', 'facebook'))
                    imported += 1
        
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({
            'status': 'success',
            'message': f'Import completed successfully',
            'new_leads': imported,
            'updated_leads': updated,
            'redirect': '/campaign-manager'
        })
        
    except Exception as e:
        logger.error(f"Facebook CSV upload error: {str(e)}")
        import traceback
        return jsonify({
            'status': 'error',
            'error': str(e),
            'details': traceback.format_exc()
        }), 500

@app.route('/debug-webhook-fields', methods=['POST'])
def debug_webhook_fields():
    """Debug endpoint to see exactly what fields Zapier is sending"""
    try:
        lead_data = request.get_json()
        if not lead_data:
            return jsonify({'error': 'No data received'}), 400
        
        # Log all fields received
        logger.info("=== WEBHOOK DEBUG - ALL FIELDS ===")
        logger.info(f"Total fields: {len(lead_data)}")
        
        # Group fields by type
        all_fields = list(lead_data.keys())
        campaign_fields = [k for k in all_fields if 'campaign' in k.lower()]
        name_fields = [k for k in all_fields if 'name' in k.lower()]
        phone_fields = [k for k in all_fields if 'phone' in k.lower()]
        email_fields = [k for k in all_fields if 'email' in k.lower()]
        
        logger.info(f"All fields: {all_fields}")
        logger.info(f"Campaign-related fields: {campaign_fields}")
        logger.info(f"Name-related fields: {name_fields}")
        logger.info(f"Phone-related fields: {phone_fields}")
        logger.info(f"Email-related fields: {email_fields}")
        
        # Show values for campaign fields
        for field in campaign_fields:
            logger.info(f"Campaign field '{field}': {lead_data[field]}")
        
        return jsonify({
            'status': 'success',
            'message': 'Webhook fields logged for debugging',
            'total_fields': len(all_fields),
            'campaign_fields': campaign_fields,
            'campaign_values': {field: lead_data[field] for field in campaign_fields}
        }), 200
        
    except Exception as e:
        logger.error(f"Error in debug_webhook_fields: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/debug-lead/<int:lead_id>')
def debug_lead(lead_id):
    """Debug specific lead to see raw data fields"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available'}), 500
        
        cur = conn.cursor()
        
        # Get lead with raw_data
        cur.execute("""
            SELECT id, name, email, phone, campaign_name, created_time, raw_data
            FROM leads 
            WHERE id = %s
        """, (lead_id,))
        
        lead = cur.fetchone()
        
        if not lead:
            return jsonify({'error': f'Lead #{lead_id} not found'}), 404
        
        lead_id_db, name, email, phone, campaign_name, created_time, raw_data = lead
        
        result = {
            'lead_id': lead_id_db,
            'name': name,
            'email': email,
            'phone': phone,
            'campaign_name': campaign_name,
            'created_time': str(created_time) if created_time else None,
            'raw_data_fields': {},
            'campaign_related_fields': {},
            'all_fields': []
        }
        
        if raw_data:
            try:
                if isinstance(raw_data, str):
                    data = json.loads(raw_data)
                else:
                    data = raw_data
                
                result['raw_data_fields'] = data
                result['all_fields'] = list(data.keys())
                
                # Find campaign-related fields
                campaign_fields = [k for k in data.keys() if 'campaign' in k.lower()]
                result['campaign_related_fields'] = {field: data[field] for field in campaign_fields}
                
            except Exception as e:
                result['raw_data_error'] = str(e)
                result['raw_data_type'] = str(type(raw_data))
        
        cur.close()
        conn.close()
        
        return jsonify(result), 200
        
    except Exception as e:
        logger.error(f"Error in debug_lead: {e}")
        return jsonify({'error': str(e)}), 500

# Initialize database on startup (but don't fail if it doesn't work)
try:
    init_database()
except Exception as e:
    logger.error(f"Database initialization failed: {e}")
    logger.info("Continuing without database - webhook will still work")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug_mode = os.environ.get('FLASK_ENV') != 'production'
    app.run(host='0.0.0.0', port=port, debug=debug_mode)
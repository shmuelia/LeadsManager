from flask import Flask, request, jsonify, render_template, session, redirect, url_for, flash, Response
import psycopg2
import psycopg2.extras
from datetime import datetime
import json
import logging
import os
import hashlib
from functools import wraps
import time
import threading
from queue import Queue

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-change-in-production')

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Notification system for real-time updates
notification_queues = {}  # Dictionary to store notification queues by customer_id

# Database connection
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL and DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

def get_db_connection():
    """Get database connection with error handling"""
    try:
        if DATABASE_URL:
            conn = psycopg2.connect(DATABASE_URL)
            return conn
        else:
            logger.warning("No DATABASE_URL found")
            return None
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        return None

def init_database():
    """Initialize database tables if they don't exist"""
    try:
        conn = get_db_connection()
        if not conn:
            logger.warning("Skipping database initialization - no connection")
            return False
            
        cur = conn.cursor()
        
        # Auto-migrate: Add phone columns if they don't exist
        try:
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR(20)")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS whatsapp_notifications BOOLEAN DEFAULT true")
            logger.info("Auto-migration: Added phone columns to users table")
        except Exception as e:
            logger.info(f"Phone columns migration (probably already exist): {e}")
        
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
        
        # Otherwise, process as Zapier format (existing code continues...)
        
        # Log ALL fields received from Zapier for debugging
        logger.info(f"=== WEBHOOK DATA RECEIVED ===")
        logger.info(f"Total fields: {len(lead_data)}")
        logger.info(f"Field names: {list(lead_data.keys())}")
        
        # Log any potential form response fields
        form_fields = {}
        for key, value in lead_data.items():
            # Skip known system fields
            if key not in ['id', 'name', 'email', 'phone', 'platform', 'campaign_name', 
                          'form_name', 'lead_source', 'created_time', 'full_name', 
                          'phone_number', 'נוצר', 'שם', 'דוא"ל', 'טלפון']:
                if value and str(value).strip():
                    form_fields[key] = value
                    logger.info(f"Potential form field: {key} = {value}")
        
        if form_fields:
            logger.info(f"Found {len(form_fields)} potential form response fields")
        
        # Extract data with multiple fallbacks
        name = lead_data.get('name') or lead_data.get('full name') or lead_data.get('full_name') or lead_data.get('שם')
        phone = lead_data.get('phone') or lead_data.get('phone_number') or lead_data.get('טלפון')
        
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
                    1  # Default to customer #1 for main webhook
                ))
                
                lead_id = cur.fetchone()[0]
                conn.commit()
                cur.close()
                conn.close()
                
                # Send real-time notification for new lead
                customer_id = 1  # Default customer ID for main webhook
                notification_title = "לייד חדש הגיע!"
                notification_message = f"לייד חדש מ{lead_data.get('platform', 'פייסבוק')}: {name}"
                
                # Additional notification data
                notification_data = {
                    'lead_name': name,
                    'lead_email': lead_data.get('email'),
                    'lead_phone': phone,
                    'platform': lead_data.get('platform', 'facebook'),
                    'campaign_name': lead_data.get('campaign_name'),
                    'form_name': lead_data.get('form_name')
                }
                
                # Create and send notification
                create_notification(
                    customer_id=customer_id,
                    lead_id=lead_id,
                    notification_type='new_lead',
                    title=notification_title,
                    message=notification_message,
                    data=notification_data
                )
                
                logger.info(f"Lead saved to database: {name} ({lead_data.get('email')}) - ID: {lead_id}")
            else:
                logger.warning("Database not available, lead data logged only")
                
        except Exception as db_error:
            logger.error(f"Database save error: {db_error}")
            # Continue without database - at least log the lead
        
        # Always log the lead data for debugging
        logger.info(f"Lead received: {name} ({lead_data.get('email')}) from {lead_data.get('platform', 'unknown')}")
        
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
        cur.execute("""
            INSERT INTO notifications (customer_id, lead_id, notification_type, title, message, data)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (customer_id, lead_id, notification_type, title, message, json.dumps(data) if data else None))
        
        notification_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        
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
        send_notification(customer_id, notification_data)
        
        return notification_id
        
    except Exception as e:
        logger.error(f"Error creating notification: {e}")
        return None

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

@app.route('/notifications/stream')
@campaign_manager_required
def notification_stream():
    """Server-Sent Events endpoint for real-time notifications"""
    try:
        # Get user's customer ID before creating the generator
        user_role = session.get('role')
        username = session.get('username', 'unknown')
        
        if user_role == 'admin':
            customer_id = session.get('selected_customer_id', 1)
        else:
            customer_id = session.get('customer_id', 1)
        
        logger.info(f"SSE connection request from {username} (role: {user_role}, customer: {customer_id})")
        
        def event_stream():
            # Create a new queue for this client
            client_queue = Queue()
            
            try:
                # Initialize the customer's queue list if it doesn't exist
                if customer_id not in notification_queues:
                    notification_queues[customer_id] = []
                notification_queues[customer_id].append(client_queue)
                
                logger.info(f"SSE client connected: {username} for customer {customer_id}")
                
                # Send initial connection confirmation
                yield f"data: {json.dumps({'type': 'connected', 'customer_id': customer_id, 'username': username})}\n\n"
                
                while True:
                    # Wait for notification with timeout
                    try:
                        notification = client_queue.get(timeout=30)
                        yield f"data: {json.dumps(notification)}\n\n"
                    except:
                        # Send heartbeat to keep connection alive
                        yield f"data: {json.dumps({'type': 'heartbeat', 'timestamp': int(time.time()), 'customer_id': customer_id})}\n\n"
                        
            except GeneratorExit:
                # Client disconnected, clean up
                if customer_id in notification_queues and client_queue in notification_queues[customer_id]:
                    notification_queues[customer_id].remove(client_queue)
                logger.info(f"SSE client disconnected: {username} for customer {customer_id}")
            except Exception as e:
                logger.error(f"SSE stream error for {username}: {e}")
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

        return Response(event_stream(), mimetype='text/event-stream',
                       headers={'Cache-Control': 'no-cache',
                               'Connection': 'keep-alive',
                               'Access-Control-Allow-Origin': '*',
                               'X-Accel-Buffering': 'no'})
                               
    except Exception as e:
        logger.error(f"SSE endpoint error: {e}")
        return jsonify({'error': str(e)}), 500

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
    """Beautiful web dashboard for viewing leads"""
    return render_template('dashboard.html')

@app.route('/campaign-manager')
@campaign_manager_required
def campaign_manager_dashboard():
    """Campaign manager dashboard - lead management only"""
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
        
        # Update status
        cur.execute("""
            UPDATE leads SET status = %s, updated_at = CURRENT_TIMESTAMP 
            WHERE id = %s
        """, (new_status, lead_id))
        
        # Log status change activity
        cur.execute("""
            INSERT INTO lead_activities 
            (lead_id, user_name, activity_type, description, previous_status, new_status)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            lead_id, user_name, 'status_change',
            f'סטטוס שונה מ-{old_status} ל-{new_status}',
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
    """Admin-only dashboard - desktop design"""
    return render_template('admin_dashboard.html')

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
        
        # Check if lead exists and belongs to user's customer scope
        cur.execute("SELECT id, name, customer_id FROM leads WHERE id = %s", (lead_id,))
        lead = cur.fetchone()
        if not lead:
            return jsonify({'error': 'Lead not found'}), 404
        
        # Verify lead belongs to user's customer scope
        lead_customer_id = lead[2] or selected_customer_id
        if user_role == 'campaign_manager' and lead_customer_id != selected_customer_id:
            return jsonify({'error': 'Access denied'}), 403
            
        lead_name = lead[1]
        
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
                         'facebook_app_id', 'instagram_app_id', 'active']
        
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
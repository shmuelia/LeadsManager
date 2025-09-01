from flask import Flask, request, jsonify, render_template, session, redirect, url_for, flash
import psycopg2
import psycopg2.extras
from datetime import datetime
import json
import logging
import os
import hashlib
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-change-in-production')

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
            SELECT id, username, full_name, role, active 
            FROM users 
            WHERE username = %s AND password_hash = %s AND active = true
        """, (username, hash_password(password)))
        
        user = cur.fetchone()
        cur.close()
        conn.close()
        
        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['full_name'] = user['full_name']
            session['role'] = user['role']
            
            flash(f'ברוך הבא, {user["full_name"]}!')
            
            # Check if there's a next URL to redirect to
            next_page = request.args.get('next')
            
            # Validate next URL for security (must be relative)
            if next_page and next_page.startswith('/') and not next_page.startswith('//'):
                return redirect(next_page)
            
            # Default redirect based on role
            if user['role'] == 'admin':
                return redirect(url_for('admin_dashboard'))
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

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    """Receive Facebook leads from Zapier"""
    if request.method == 'GET':
        return jsonify({
            'message': 'Webhook endpoint ready',
            'method': 'POST requests only',
            'content_type': 'application/json',
            'status': 'ready',
            'database_available': bool(DATABASE_URL)
        })
    
    try:
        lead_data = request.get_json()
        
        if not lead_data:
            logger.warning("No JSON data received")
            return jsonify({'error': 'No data received'}), 400
        
        # Extract data
        name = lead_data.get('name') or lead_data.get('full name') or lead_data.get('full_name')
        phone = lead_data.get('phone') or lead_data.get('phone_number')
        
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
                    INSERT INTO leads (external_lead_id, name, email, phone, platform, campaign_name, form_name, lead_source, created_time, raw_data)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                    json.dumps(lead_data)
                ))
                
                lead_id = cur.fetchone()[0]
                conn.commit()
                cur.close()
                conn.close()
                
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

@app.route('/leads')
@login_required
def get_leads():
    """View all received leads (filtered by assignment for non-admin users)"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available', 'leads': []}), 200
            
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # Filter leads based on user role
        if session.get('role') == 'admin':
            # Admin sees all leads
            cur.execute("""
                SELECT id, external_lead_id, name, email, phone, platform, campaign_name, form_name, 
                       lead_source, created_time, received_at, status, assigned_to, priority, 
                       raw_data, notes, updated_at
                FROM leads 
                ORDER BY COALESCE(created_time, received_at) DESC
            """)
        else:
            # Regular users see only leads assigned to them
            username = session.get('username')
            cur.execute("""
                SELECT id, external_lead_id, name, email, phone, platform, campaign_name, form_name, 
                       lead_source, created_time, received_at, status, assigned_to, priority, 
                       raw_data, notes, updated_at
                FROM leads 
                WHERE assigned_to = %s
                ORDER BY COALESCE(created_time, received_at) DESC
            """, (username,))
        
        leads = cur.fetchall()
        
        # Convert to JSON-serializable format
        leads_list = []
        for lead in leads:
            lead_dict = dict(lead)
            # Convert datetime objects to ISO format
            for key in ['created_time', 'received_at', 'updated_at']:
                if lead_dict[key]:
                    lead_dict[key] = lead_dict[key].isoformat()
            leads_list.append(lead_dict)
        
        cur.close()
        conn.close()
        
        return jsonify({
            'total_leads': len(leads_list),
            'leads': leads_list
        })
        
    except Exception as e:
        logger.error(f"Error fetching leads: {str(e)}")
        return jsonify({'error': str(e), 'leads': []}), 200

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
                    INSERT INTO leads (external_lead_id, name, email, phone, platform, campaign_name, form_name, lead_source, created_time, raw_data)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                    json.dumps(lead_data)
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

@app.route('/test')
def test():
    return jsonify({
        'test': 'success',
        'webhook_ready': True,
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
@admin_required
def get_users_api():
    """Admin: Get all users (API)"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available'}), 500
            
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT id, username, full_name, email, role, department, active, created_at
            FROM users
            ORDER BY created_at DESC
        """)
        
        users = cur.fetchall()
        
        # Convert to JSON-serializable format
        users_list = []
        for user in users:
            user_dict = dict(user)
            user_dict['created_at'] = user_dict['created_at'].isoformat() if user_dict['created_at'] else None
            users_list.append(user_dict)
        
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

@app.route('/admin/users/create', methods=['POST'])
@admin_required
def create_user():
    """Admin: Create new user"""
    try:
        data = request.get_json()
        
        required_fields = ['username', 'password', 'full_name', 'role']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
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
            INSERT INTO users (username, password_hash, full_name, email, role, department, active)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id;
        """, (
            data['username'],
            hash_password(data['password']),
            data['full_name'],
            data.get('email'),
            data['role'],
            data.get('department'),
            data.get('active', True)
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

@app.route('/admin/users/update/<int:user_id>', methods=['PUT'])
@admin_required
def update_user(user_id):
    """Admin: Update existing user"""
    try:
        data = request.get_json()
        
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available'}), 500
            
        cur = conn.cursor()
        
        # Check if user exists
        cur.execute("SELECT id FROM users WHERE id = %s", (user_id,))
        if not cur.fetchone():
            return jsonify({'error': 'User not found'}), 404
        
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
        
        if 'password' in data and data['password']:
            update_fields.append("password_hash = %s")
            update_values.append(hash_password(data['password']))
        
        if 'full_name' in data:
            update_fields.append("full_name = %s")
            update_values.append(data['full_name'])
        
        if 'email' in data:
            update_fields.append("email = %s")
            update_values.append(data['email'])
        
        if 'role' in data:
            update_fields.append("role = %s")
            update_values.append(data['role'])
        
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
            SELECT id, username, full_name, email, role, department, active, created_at, updated_at
            FROM users WHERE id = %s
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

@app.route('/health')
def health_check():
    """Health check endpoint for monitoring"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat()
    })

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
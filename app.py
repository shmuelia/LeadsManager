from flask import Flask, request, jsonify, render_template
import psycopg2
import psycopg2.extras
from datetime import datetime
import json
import logging
import os

app = Flask(__name__)

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
        
        conn.commit()
        cur.close()
        conn.close()
        logger.info("Database tables initialized successfully")
        return True
        
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
        return False

@app.route('/')
def home():
    """Home page showing server status"""
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
def get_leads():
    """View all received leads"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database not available', 'leads': []}), 200
            
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        cur.execute("""
            SELECT id, external_lead_id, name, email, phone, platform, campaign_name, form_name, 
                   lead_source, created_time, received_at, status, assigned_to, priority, 
                   raw_data, notes, updated_at
            FROM leads 
            ORDER BY received_at DESC
        """)
        
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
        
        # Convert to JSON-serializable format
        lead_dict = dict(lead)
        for key in ['created_time', 'received_at', 'updated_at']:
            if lead_dict[key]:
                lead_dict[key] = lead_dict[key].isoformat()
        
        cur.close()
        conn.close()
        
        return jsonify({
            'lead': lead_dict,
            'activities': []  # Activities can be added later
        })
        
    except Exception as e:
        logger.error(f"Error fetching lead {lead_id}: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/dashboard')
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
                created_date = (row.get('נוצר') or row.get('created_time') or 
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
                        # e.g., "09/01/2025 1:39am" 
                        from datetime import datetime
                        import re
                        
                        # Remove "am/pm" and convert to 24h format if needed
                        date_str = created_date.replace('am', '').replace('pm', '').strip()
                        created_time = datetime.strptime(date_str, '%m/%d/%Y %I:%M')
                    except:
                        logger.warning(f"Could not parse date: {created_date}")
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
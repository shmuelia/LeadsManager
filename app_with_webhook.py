from flask import Flask, request, jsonify
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
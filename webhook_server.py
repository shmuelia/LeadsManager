from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
import json
import logging
from datetime import datetime
import os

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Configure database
database_url = os.environ.get('DATABASE_URL')
if database_url and database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url or 'postgresql://localhost/leadmanager'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database Models
class Lead(db.Model):
    __tablename__ = 'leads'
    
    id = db.Column(db.Integer, primary_key=True)
    external_lead_id = db.Column(db.String(255))
    name = db.Column(db.String(255))
    email = db.Column(db.String(255))
    phone = db.Column(db.String(20))
    platform = db.Column(db.String(50), default='facebook')
    campaign_name = db.Column(db.Text)
    form_name = db.Column(db.Text)
    lead_source = db.Column(db.Text)
    created_time = db.Column(db.DateTime)
    received_at = db.Column(db.DateTime, default=datetime.now)
    status = db.Column(db.String(50), default='new')
    assigned_to = db.Column(db.String(255))
    priority = db.Column(db.Integer, default=0)
    raw_data = db.Column(db.JSON)
    notes = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    
    activities = db.relationship('LeadActivity', backref='lead', lazy=True, cascade='all, delete-orphan')
    
    def to_dict(self):
        return {
            'id': self.id,
            'external_lead_id': self.external_lead_id,
            'name': self.name,
            'email': self.email,
            'phone': self.phone,
            'platform': self.platform,
            'campaign_name': self.campaign_name,
            'form_name': self.form_name,
            'lead_source': self.lead_source,
            'created_time': self.created_time.isoformat() if self.created_time else None,
            'received_at': self.received_at.isoformat() if self.received_at else None,
            'status': self.status,
            'assigned_to': self.assigned_to,
            'priority': self.priority,
            'raw_data': self.raw_data,
            'notes': self.notes,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

class LeadActivity(db.Model):
    __tablename__ = 'lead_activities'
    
    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey('leads.id'), nullable=False)
    user_name = db.Column(db.String(255), nullable=False)
    activity_type = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    call_duration = db.Column(db.Integer)  # seconds
    call_outcome = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.now)
    metadata = db.Column(db.JSON)
    
    def to_dict(self):
        return {
            'id': self.id,
            'lead_id': self.lead_id,
            'user_name': self.user_name,
            'activity_type': self.activity_type,
            'description': self.description,
            'call_duration': self.call_duration,
            'call_outcome': self.call_outcome,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'metadata': self.metadata
        }

@app.route('/')
def home():
    """Home page showing server status"""
    total_leads = Lead.query.count()
    return jsonify({
        'status': 'active',
        'message': 'LeadsManager Webhook Server',
        'leads_received': total_leads,
        'timestamp': datetime.now().isoformat()
    })

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    """Receive Facebook leads from Zapier"""
    if request.method == 'GET':
        return jsonify({
            'message': 'Webhook endpoint ready',
            'method': 'POST requests only',
            'content_type': 'application/json',
            'test_url': 'Use POST with JSON data'
        })
    
    try:
        # Get JSON data from Zapier
        lead_data = request.get_json()
        
        if not lead_data:
            logger.warning("No JSON data received")
            return jsonify({'error': 'No data received'}), 400
        
        # Extract name from raw data if not in main fields
        name = lead_data.get('name') or lead_data.get('full name') or lead_data.get('full_name')
        phone = lead_data.get('phone') or lead_data.get('phone_number')
        
        # Parse created_time if it's a string
        created_time = None
        if lead_data.get('created_time'):
            try:
                from datetime import datetime as dt
                created_time = dt.fromisoformat(lead_data['created_time'].replace('Z', '+00:00'))
            except:
                pass
        
        # Create new lead record
        new_lead = Lead(
            external_lead_id=lead_data.get('id'),
            name=name,
            email=lead_data.get('email'),
            phone=phone,
            platform=lead_data.get('platform', 'facebook'),
            campaign_name=lead_data.get('campaign_name'),
            form_name=lead_data.get('form_name'),
            lead_source=lead_data.get('lead_source'),
            created_time=created_time,
            raw_data=lead_data
        )
        
        # Save to database
        db.session.add(new_lead)
        db.session.commit()
        
        # Create initial activity record
        activity = LeadActivity(
            lead_id=new_lead.id,
            user_name='system',
            activity_type='lead_received',
            description=f'Lead received from {new_lead.platform} via webhook'
        )
        db.session.add(activity)
        db.session.commit()
        
        # Log successful receipt
        logger.info(f"New lead received: {new_lead.name} ({new_lead.email}) - ID: {new_lead.id}")
        
        # TODO: Add additional processing actions here
        # - Send welcome email
        # - Send WhatsApp notification  
        # - Update CRM
        # - Add to Google Sheets
        
        return jsonify({
            'status': 'success',
            'message': 'Lead processed successfully',
            'lead_id': new_lead.id
        }), 200
        
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': 'Failed to process lead'
        }), 500

@app.route('/leads')
def get_leads():
    """View all received leads"""
    leads = Lead.query.order_by(Lead.received_at.desc()).all()
    return jsonify({
        'total_leads': len(leads),
        'leads': [lead.to_dict() for lead in leads]
    })

@app.route('/leads/<int:lead_id>')
def get_lead(lead_id):
    """Get specific lead with activities"""
    lead = Lead.query.get_or_404(lead_id)
    activities = LeadActivity.query.filter_by(lead_id=lead_id).order_by(LeadActivity.created_at.desc()).all()
    
    return jsonify({
        'lead': lead.to_dict(),
        'activities': [activity.to_dict() for activity in activities]
    })

@app.route('/leads/<int:lead_id>/activity', methods=['POST'])
def add_lead_activity(lead_id):
    """Add activity to a lead"""
    lead = Lead.query.get_or_404(lead_id)
    data = request.get_json()
    
    activity = LeadActivity(
        lead_id=lead_id,
        user_name=data.get('user_name', 'unknown'),
        activity_type=data.get('activity_type', 'note'),
        description=data.get('description'),
        call_duration=data.get('call_duration'),
        call_outcome=data.get('call_outcome'),
        metadata=data.get('metadata')
    )
    
    db.session.add(activity)
    
    # Update lead status if provided
    if data.get('new_status'):
        lead.status = data['new_status']
    
    db.session.commit()
    
    return jsonify({
        'status': 'success',
        'activity_id': activity.id
    })

@app.route('/leads/<int:lead_id>/status', methods=['PUT'])
def update_lead_status(lead_id):
    """Update lead status"""
    lead = Lead.query.get_or_404(lead_id)
    data = request.get_json()
    
    old_status = lead.status
    new_status = data.get('status')
    user_name = data.get('user_name', 'unknown')
    
    lead.status = new_status
    
    # Create activity record
    activity = LeadActivity(
        lead_id=lead_id,
        user_name=user_name,
        activity_type='status_changed',
        description=f'Status changed from {old_status} to {new_status}'
    )
    
    db.session.add(activity)
    db.session.commit()
    
    return jsonify({'status': 'success'})

@app.route('/health')
def health_check():
    """Health check endpoint for monitoring"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat()
    })

# Initialize database tables
with app.app_context():
    try:
        db.create_all()
        logger.info("Database tables created successfully")
    except Exception as e:
        logger.error(f"Error creating database tables: {e}")

if __name__ == '__main__':
    # Get port from environment variable or default to 5000
    port = int(os.environ.get('PORT', 5000))
    
    # Run in debug mode locally, production mode on Heroku
    debug_mode = os.environ.get('FLASK_ENV') != 'production'
    
    app.run(host='0.0.0.0', port=port, debug=debug_mode)
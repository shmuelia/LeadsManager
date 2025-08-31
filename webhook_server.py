from flask import Flask, request, jsonify
import json
import logging
from datetime import datetime
import os

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Store leads in memory for now (will add database later)
leads_storage = []

@app.route('/')
def home():
    """Home page showing server status"""
    return jsonify({
        'status': 'active',
        'message': 'LeadsManager Webhook Server',
        'leads_received': len(leads_storage),
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
        
        # Add timestamp and processing info
        processed_lead = {
            'id': len(leads_storage) + 1,
            'received_at': datetime.now().isoformat(),
            'raw_data': lead_data,
            'name': lead_data.get('name'),
            'email': lead_data.get('email'),
            'phone': lead_data.get('phone'),
            'lead_source': lead_data.get('lead_source'),
            'created_time': lead_data.get('created_time'),
            'campaign_name': lead_data.get('campaign_name'),
            'form_name': lead_data.get('form_name'),
            'platform': lead_data.get('platform', 'facebook')
        }
        
        # Store lead
        leads_storage.append(processed_lead)
        
        # Log successful receipt
        logger.info(f"New lead received: {processed_lead['name']} ({processed_lead['email']})")
        
        # TODO: Add additional processing actions here
        # - Send welcome email
        # - Send WhatsApp notification  
        # - Update CRM
        # - Add to Google Sheets
        
        return jsonify({
            'status': 'success',
            'message': 'Lead processed successfully',
            'lead_id': processed_lead['id']
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
    return jsonify({
        'total_leads': len(leads_storage),
        'leads': leads_storage
    })

@app.route('/health')
def health_check():
    """Health check endpoint for monitoring"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat()
    })

if __name__ == '__main__':
    # Get port from environment variable or default to 5000
    port = int(os.environ.get('PORT', 5000))
    
    # Run in debug mode locally, production mode on Heroku
    debug_mode = os.environ.get('FLASK_ENV') != 'production'
    
    app.run(host='0.0.0.0', port=port, debug=debug_mode)
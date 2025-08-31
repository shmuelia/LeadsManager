from flask import Flask, jsonify
import os

app = Flask(__name__)

@app.route('/')
def hello():
    return jsonify({
        'status': 'working',
        'message': 'Minimal Flask app is running',
        'no_sqlalchemy': True
    })

@app.route('/test')
def test():
    return jsonify({'test': 'success'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
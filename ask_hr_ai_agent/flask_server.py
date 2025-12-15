from flask import Flask, request, jsonify, render_template
from typing import Dict, Any, Tuple
import traceback
from agent import chat_with_workday

app = Flask(__name__)

@app.route('/')
def index() -> str:
    """Serve the main HTML interface"""
    return render_template('index.html')

@app.route('/chat', methods=['POST'])
def chat() -> Tuple[Dict[str, Any], int]:
    """Handle chat messages from the client
    
    Returns:
        Tuple of (response dict, HTTP status code)
    """
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'No JSON body provided'}), 400
        
        message = data.get('message', '').strip()
        
        if not message:
            return jsonify({'error': 'No message provided'}), 400
        
        response = chat_with_workday(message)
        return jsonify({'response': response}), 200
        
    except ValueError as e:
        # Expected validation errors
        return jsonify({'error': f'Validation error: {str(e)}'}), 400
    except TimeoutError as e:
        # Request timeout
        return jsonify({'error': f'Request timeout: {str(e)}'}), 504
    except Exception as e:
        # Unexpected errors
        print(f"Unexpected error: {traceback.format_exc()}")
        return jsonify({'error': f'Server error: {str(e)}'}), 500

@app.errorhandler(404)
def not_found(error) -> Tuple[Dict[str, str], int]:
    """Handle 404 errors"""
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def internal_error(error) -> Tuple[Dict[str, str], int]:
    """Handle 500 errors"""
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)

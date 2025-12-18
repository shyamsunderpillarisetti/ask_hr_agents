from flask import Flask, request, jsonify, render_template, send_file
from typing import Dict, Any, Tuple
import traceback
import os
from agent import chat_with_workday, reset_auth_cache
from doc_generator import get_document_from_cache, get_document_filename_from_cache

app = Flask(__name__)

if os.getenv("ASKHR_RESET_AUTH_ON_STARTUP", "true").lower() in ("1", "true", "yes"):
    reset_auth_cache()

@app.route('/')
def index() -> str:
    """Serve the main HTML interface."""
    return render_template('index.html')


@app.route('/chat', methods=['POST'])
def chat() -> Tuple[Dict[str, Any], int]:
    """Handle chat messages."""
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
        return jsonify({'error': f'Validation error: {str(e)}'}), 400
    except TimeoutError as e:
        return jsonify({'error': f'Request timeout: {str(e)}'}), 504
    except Exception as e:
        print(f"Unexpected error: {traceback.format_exc()}")
        return jsonify({'error': f'Server error: {str(e)}'}), 500


@app.errorhandler(404)
def not_found(error) -> Tuple[Dict[str, str], int]:
    """Handle 404 errors."""
    return jsonify({'error': 'Not found'}), 404


@app.errorhandler(500)
def internal_error(error) -> Tuple[Dict[str, str], int]:
    """Handle 500 errors."""
    return jsonify({'error': 'Internal server error'}), 500

@app.route('/reset', methods=['POST'])
def reset() -> Tuple[Dict[str, Any], int]:
    """Clear cached auth so next request prompts login again."""
    try:
        ok = reset_auth_cache()
        return jsonify({'success': ok, 'message': 'Auth cache cleared. Next request will trigger login.'}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/download_doc/<doc_key>', methods=['GET'])
def download_doc_from_memory(doc_key: str):
    """Download a document from memory cache."""
    doc_bytes = get_document_from_cache(doc_key)
    if doc_bytes is None:
        return jsonify({'error': 'Document not found or expired'}), 404
    
    filename = get_document_filename_from_cache(doc_key) or "document.docx"
    
    # Reset BytesIO position to beginning
    doc_bytes.seek(0)
    
    return send_file(
        doc_bytes,
        mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        as_attachment=True,
        download_name=filename
    )


if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=5000, use_reloader=False)

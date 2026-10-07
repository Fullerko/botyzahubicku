"""Installable mobile client for the existing Flask application; no second DB."""
from pathlib import Path
import json
from flask import Blueprint, Response, render_template, send_from_directory

mobile_bp = Blueprint('mobile', __name__)
ASSETS = Path(__file__).parent / 'static' / 'pwa'

@mobile_bp.get('/app.webmanifest')
def manifest():
    data = json.loads((ASSETS / 'manifest.json').read_text(encoding='utf-8'))
    return Response(json.dumps(data, ensure_ascii=False), mimetype='application/manifest+json', headers={'Cache-Control': 'no-cache'})

@mobile_bp.get('/service-worker.js')
def worker():
    response = send_from_directory(ASSETS, 'service-worker.js', mimetype='application/javascript')
    response.headers['Service-Worker-Allowed'] = '/'
    response.headers['Cache-Control'] = 'no-cache'
    return response

@mobile_bp.get('/aplikace')
def install():
    return render_template('pwa/install.html')

@mobile_bp.get('/aplikace/offline')
def offline():
    return send_from_directory(ASSETS, 'offline.html', mimetype='text/html')

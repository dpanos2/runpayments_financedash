import os
import json
import re
import secrets
from datetime import datetime
from flask import Flask, redirect, request, jsonify, render_template, session
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from qbo_client import QBOClient
from processor import process_pl_report
from data_store import DataStore

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))

# ── Clients ───────────────────────────────────────────────────────────────────
store = DataStore()

qbo = QBOClient(
    client_id=os.environ['QBO_CLIENT_ID'],
    client_secret=os.environ['QBO_CLIENT_SECRET'],
    redirect_uri=os.environ['QBO_REDIRECT_URI'],
    environment=os.environ.get('QBO_ENVIRONMENT', 'production'),
)

VALID_MONTHS = {
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December'
}


def _clean_data(data):
    """Remove malformed entries — QBO Total column, partial months like 'Mar 1-4, 2026'."""
    result = []
    for d in data:
        parts = (d.get('month') or '').split()
        if len(parts) == 2 and parts[0] in VALID_MONTHS and parts[1].isdigit() and len(parts[1]) == 4:
            result.append(d)
    return result


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    """Serve the dashboard with live data injected directly into the HTML."""
    data = _clean_data(store.get_data())
    template_path = os.path.join(app.root_path, 'templates', 'dashboard.html')
    with open(template_path, 'r', encoding='utf-8') as f:
        html = f.read()
    # Inject live data — simple string replacement, no Jinja2 processing
    data_json = json.dumps(data)
    html = html.replace('const RAW = [];', f'const RAW = {data_json};', 1)
    return html, 200, {'Content-Type': 'text/html; charset=utf-8'}


@app.route('/setup')
def setup():
    tokens = store.get_tokens()
    meta = store.get_meta()
    data = _clean_data(store.get_data())
    return render_template(
        'setup.html',
        connected=tokens is not None,
        realm_id=tokens.get('realm_id') if tokens else None,
        last_refreshed=meta.get('last_refreshed') if meta else None,
        month_count=len(data),
    )


@app.route('/api/data')
def api_data():
    return jsonify(_clean_data(store.get_data()))


@app.route('/api/status')
def api_status():
    tokens = store.get_tokens()
    meta = store.get_meta()
    data = _clean_data(store.get_data())
    return jsonify({
        'connected': tokens is not None,
        'last_refreshed': meta.get('last_refreshed') if meta else None,
        'month_count': len(data),
    })


# ── OAuth ─────────────────────────────────────────────────────────────────────

@app.route('/auth/quickbooks')
def auth_qbo():
    auth_url, state = qbo.get_auth_url()
    session['oauth_state'] = state
    return redirect(auth_url)


@app.route('/auth/callback')
def auth_callback():
    error = request.args.get('error')
    if error:
        return f'QuickBooks authorization failed: {error}', 400

    code = request.args.get('code')
    state = request.args.get('state')
    realm_id = request.args.get('realmId')

    if state != session.get('oauth_state'):
        return 'State mismatch — possible CSRF attempt.', 400

    tokens = qbo.exchange_code(code, realm_id)
    store.save_tokens(tokens)
    _refresh_data()
    return redirect('/setup')


# ── Manual refresh ────────────────────────────────────────────────────────────

@app.route('/refresh')
def manual_refresh():
    secret = request.args.get('secret', '')
    if secret != os.environ.get('REFRESH_SECRET', ''):
        return jsonify({'error': 'Unauthorized'}), 401
    _refresh_data()
    meta = store.get_meta()
    return jsonify({'status': 'ok', 'last_refreshed': meta.get('last_refreshed')})


# ── Core refresh logic ────────────────────────────────────────────────────────

def _refresh_data():
    tokens = store.get_tokens()
    if not tokens:
        print('[refresh] No tokens stored — skipping.')
        return
    try:
        tokens = qbo.ensure_valid_token(tokens)
        store.save_tokens(tokens)
        report = qbo.get_pl_report(tokens)
        data = process_pl_report(report)
        store.save_data(data)
        clean = _clean_data(data)
        print(f'[refresh] ✅  {len(clean)} months at {datetime.utcnow().isoformat()}Z')
        if clean:
            s = clean[0]
            print(f'[refresh] Sample: {s["month"]} income={s["totalIncome"]} net={s["netIncome"]}')
    except Exception as e:
        import traceback
        print(f'[refresh] ❌  Error: {e}')
        traceback.print_exc()


# ── Scheduler ─────────────────────────────────────────────────────────────────

scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(_refresh_data, CronTrigger(day='5-15', hour=6, minute=0))
scheduler.start()


# ── Entrypoint ────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)

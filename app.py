import os
import secrets
from datetime import datetime
from flask import Flask, redirect, request, jsonify, render_template, session, url_for
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

# ── Routes ────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/setup')
def setup():
    tokens   = store.get_tokens()
    meta     = store.get_meta()
    data     = store.get_data()
    return render_template(
        'setup.html',
        connected=tokens is not None,
        realm_id=tokens.get('realm_id') if tokens else None,
        last_refreshed=meta.get('last_refreshed') if meta else None,
        month_count=len(data),
    )


@app.route('/api/data')
def api_data():
    return jsonify(store.get_data())


@app.route('/api/status')
def api_status():
    tokens = store.get_tokens()
    meta   = store.get_meta()
    data   = store.get_data()
    return jsonify({
        'connected':      tokens is not None,
        'last_refreshed': meta.get('last_refreshed') if meta else None,
        'month_count':    len(data),
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

    code     = request.args.get('code')
    state    = request.args.get('state')
    realm_id = request.args.get('realmId')

    if state != session.get('oauth_state'):
        return 'State mismatch — possible CSRF attempt.', 400

    tokens = qbo.exchange_code(code, realm_id)
    store.save_tokens(tokens)

    # Immediately pull data after connecting
    _refresh_data()

    return redirect('/setup')


# ── Manual refresh (protected) ────────────────────────────────────────────────

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
    """Fetch latest P&L from QuickBooks and update stored data."""
    tokens = store.get_tokens()
    if not tokens:
        print('[refresh] No tokens stored — skipping.')
        return

    try:
        tokens = qbo.ensure_valid_token(tokens)
        store.save_tokens(tokens)

        report = qbo.get_pl_report(tokens)
        data   = process_pl_report(report)
        store.save_data(data)
        print(f'[refresh] ✅  Updated {len(data)} months at {datetime.utcnow().isoformat()}Z')
    except Exception as e:
        print(f'[refresh] ❌  Error: {e}')


# ── Scheduler: auto-refresh on the 1st of each month at 6 AM ─────────────────

scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(_refresh_data, CronTrigger(day=1, hour=6, minute=0))
scheduler.start()


# ── Entrypoint ────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)

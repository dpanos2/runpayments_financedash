"""
QuickBooks Online OAuth 2.0 client + Reports API wrapper.
"""
import time
import secrets
from urllib.parse import urlencode
import requests

INTUIT_AUTH_URL  = 'https://appcenter.intuit.com/connect/oauth2'
INTUIT_TOKEN_URL = 'https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer'
INTUIT_REVOKE_URL = 'https://developer.api.intuit.com/v2/oauth2/tokens/revoke'

PROD_API_BASE    = 'https://quickbooks.api.intuit.com/v3/company'
SANDBOX_API_BASE = 'https://sandbox-quickbooks.api.intuit.com/v3/company'

# How far back to pull history (adjust if needed)
HISTORY_START = '2023-01-01'


class QBOClient:
    def __init__(self, client_id: str, client_secret: str,
                 redirect_uri: str, environment: str = 'production'):
        self.client_id     = client_id
        self.client_secret = client_secret
        self.redirect_uri  = redirect_uri
        self.api_base      = SANDBOX_API_BASE if environment == 'sandbox' else PROD_API_BASE

    # ── OAuth ──────────────────────────────────────────────────────────────

    def get_auth_url(self) -> tuple[str, str]:
        """Return (authorization_url, state) for the OAuth redirect."""
        state  = secrets.token_urlsafe(16)
        params = {
            'client_id':     self.client_id,
            'response_type': 'code',
            'scope':         'com.intuit.quickbooks.accounting',
            'redirect_uri':  self.redirect_uri,
            'state':         state,
        }
        return f'{INTUIT_AUTH_URL}?{urlencode(params)}', state

    def exchange_code(self, code: str, realm_id: str) -> dict:
        """Exchange authorization code for access + refresh tokens."""
        resp = requests.post(
            INTUIT_TOKEN_URL,
            data={
                'grant_type':   'authorization_code',
                'code':         code,
                'redirect_uri': self.redirect_uri,
            },
            auth=(self.client_id, self.client_secret),
            headers={'Accept': 'application/json'},
        )
        resp.raise_for_status()
        tokens = resp.json()
        tokens['realm_id']   = realm_id
        tokens['expires_at'] = time.time() + tokens['expires_in']
        return tokens

    def refresh_access_token(self, tokens: dict) -> dict:
        """Use refresh_token to get a new access_token."""
        resp = requests.post(
            INTUIT_TOKEN_URL,
            data={
                'grant_type':    'refresh_token',
                'refresh_token': tokens['refresh_token'],
            },
            auth=(self.client_id, self.client_secret),
            headers={'Accept': 'application/json'},
        )
        resp.raise_for_status()
        new_tokens = resp.json()
        new_tokens['realm_id']   = tokens['realm_id']
        new_tokens['expires_at'] = time.time() + new_tokens['expires_in']
        return new_tokens

    def ensure_valid_token(self, tokens: dict) -> dict:
        """Refresh the access token if it's within 5 minutes of expiry."""
        if time.time() > tokens.get('expires_at', 0) - 300:
            tokens = self.refresh_access_token(tokens)
        return tokens

    # ── Reports API ────────────────────────────────────────────────────────

    def get_pl_report(self, tokens: dict, start_date: str = HISTORY_START, end_date: str = None) -> dict:
        """
        Fetch the Profit & Loss report from QBO summarized by month.
        end_date defaults to today, but can be overridden to limit data
        to a specific cutoff (e.g. last day of most recent closed month).
        Returns the raw JSON response from the Reports API.
        """
        from datetime import date
        if not end_date:
            end_date = date.today().strftime('%Y-%m-%d')
        realm_id  = tokens['realm_id']
        url       = f'{self.api_base}/{realm_id}/reports/ProfitAndLoss'

        headers = {
            'Authorization': f"Bearer {tokens['access_token']}",
            'Accept':        'application/json',
        }
        params = {
            'start_date':          start_date,
            'end_date':            end_date,
            'summarize_column_by': 'Month',
            'minorversion':        '65',
        }

        resp = requests.get(url, headers=headers, params=params)
        resp.raise_for_status()
        return resp.json()

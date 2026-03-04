# Run Payments Live Dashboard — Deployment Guide

## Overview

This is a Flask web app that connects to QuickBooks Online, pulls your P&L
report automatically once a month, and serves the branded dashboard at a
permanent URL accessible from anywhere.

**Stack:** Python · Flask · QuickBooks Online API · Render (hosting)

---

## Step 1 — Create a QuickBooks Developer App

1. Go to [developer.intuit.com](https://developer.intuit.com) and sign in with
   your Intuit/QuickBooks credentials
2. Click **Create an App** → select **QuickBooks Online and Payments**
3. Give it a name (e.g. "Run Payments Dashboard") — this is internal only
4. Under **Development → Keys & OAuth**, note your **Client ID** and
   **Client Secret** — you'll need these in Step 3
5. Under **Redirect URIs**, add:
   ```
   https://YOUR-APP-NAME.onrender.com/auth/callback
   ```
   (You'll know the exact URL after Step 2. You can come back and update this.)

---

## Step 2 — Deploy to Render

1. Push this project folder to a **GitHub repository** (private is fine)
2. Go to [render.com](https://render.com) and create a free account
3. Click **New → Web Service** and connect your GitHub repo
4. Render will detect `render.yaml` automatically and configure the service
5. Click **Create Web Service** — your app URL will be something like:
   ```
   https://run-payments-dashboard.onrender.com
   ```
6. Go back to the Intuit Developer Portal and update your Redirect URI to:
   ```
   https://run-payments-dashboard.onrender.com/auth/callback
   ```

---

## Step 3 — Set Environment Variables in Render

In your Render dashboard → **Environment** tab, add these variables:

| Variable | Value |
|----------|-------|
| `QBO_CLIENT_ID` | From Intuit Developer Portal (Step 1) |
| `QBO_CLIENT_SECRET` | From Intuit Developer Portal (Step 1) |
| `QBO_REDIRECT_URI` | `https://YOUR-APP.onrender.com/auth/callback` |
| `QBO_ENVIRONMENT` | `production` |
| `SECRET_KEY` | Any random string (or use Render's "Generate" button) |
| `REFRESH_SECRET` | Any secret string — you'll use this for manual refreshes |
| `DATA_DIR` | `/data` |

Render will redeploy automatically after you save.

---

## Step 4 — Connect QuickBooks

1. Visit `https://your-app.onrender.com/setup`
2. Click **Connect QuickBooks Online →**
3. Sign in with your QuickBooks credentials and approve access
4. You'll be redirected back to `/setup` — the app will immediately pull all
   historical P&L data and show a "Connected" status
5. Click **View Dashboard** — it's live!

---

## Ongoing: Auto-Refresh

The dashboard auto-refreshes on the **1st of every month at 6 AM UTC**. No
action needed — when you close January's books in QuickBooks, the dashboard
will pick up the new data automatically on the 1st of February.

**Manual refresh** (force an immediate update):
```
https://your-app.onrender.com/refresh?secret=YOUR_REFRESH_SECRET
```
Replace `YOUR_REFRESH_SECRET` with the value you set in Step 3.

---

## Render Free Tier Notes

- The free tier spins down after 15 minutes of inactivity — the first page
  load after a period of inactivity takes ~30 seconds to wake up
- For always-on access, upgrade to Render's Starter plan (~$7/month)
- The persistent disk (1 GB, ~$0.25/month) stores your tokens and data and
  is required — it's included in `render.yaml`

---

## Local Development (optional)

```bash
# 1. Clone the repo and install dependencies
pip install -r requirements.txt

# 2. Copy environment variables
cp .env.example .env
# Fill in your QBO sandbox credentials

# 3. Run the app
python app.py

# 4. Visit http://localhost:5000/setup to connect
```

For local development, use `QBO_ENVIRONMENT=sandbox` and your sandbox
credentials from the Intuit Developer Portal.

---

## File Structure

```
├── app.py              Flask app, routes, scheduler
├── qbo_client.py       QuickBooks OAuth + Reports API
├── processor.py        Converts QBO JSON → dashboard data format
├── data_store.py       Persists tokens and P&L data to disk
├── templates/
│   ├── index.html      The dashboard (fetches data from /api/data)
│   └── setup.html      Connection status and setup page
├── requirements.txt
├── render.yaml         Render deployment config
├── Procfile
└── .env.example
```

---

## Troubleshooting

**"Connect QuickBooks" button gives an error**
→ Double-check `QBO_CLIENT_ID`, `QBO_CLIENT_SECRET`, and `QBO_REDIRECT_URI`
   in your Render environment variables. The redirect URI must exactly match
   what's registered in the Intuit Developer Portal.

**Dashboard shows "No data yet"**
→ Visit `/setup` and check the connection status. If connected, trigger a
   manual refresh using the URL above.

**Some line items show $0 in the dashboard**
→ The account names in your QuickBooks chart of accounts may not match the
   keywords in `processor.py`. Open `processor.py`, find `ACCOUNT_MAP`, and
   add your exact account names.

**QuickBooks token expired**
→ Refresh tokens expire after 100 days of inactivity. If the dashboard stops
   updating, visit `/setup` and click "Reconnect QuickBooks" to re-authorize.

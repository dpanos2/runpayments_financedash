"""
Simple JSON-file persistence for OAuth tokens and P&L data.
Files are stored in DATA_DIR (default: ./data), which should be mounted
as a persistent disk on Render so data survives redeploys.
"""
import json
import os
from datetime import datetime, timezone

DATA_DIR = os.environ.get('DATA_DIR', os.path.join(os.path.dirname(__file__), 'data'))


class DataStore:
    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self._tokens_path = os.path.join(DATA_DIR, 'tokens.json')
        self._data_path   = os.path.join(DATA_DIR, 'pl_data.json')
        self._meta_path   = os.path.join(DATA_DIR, 'meta.json')

    # ── Token storage ──────────────────────────────────────────────────────

    def save_tokens(self, tokens: dict) -> None:
        self._write(self._tokens_path, tokens)

    def get_tokens(self) -> dict | None:
        return self._read(self._tokens_path)

    def clear_tokens(self) -> None:
        if os.path.exists(self._tokens_path):
            os.remove(self._tokens_path)

    # ── P&L data storage ───────────────────────────────────────────────────

    def save_data(self, data: list) -> None:
        self._write(self._data_path, data)
        self._write(self._meta_path, {
            'last_refreshed': datetime.now(timezone.utc).isoformat(),
            'month_count':    len(data),
        })

    def get_data(self) -> list:
        return self._read(self._data_path) or []

    def get_meta(self) -> dict:
        return self._read(self._meta_path) or {}

    # ── Internal helpers ───────────────────────────────────────────────────

    def _write(self, path: str, obj) -> None:
        with open(path, 'w') as f:
            json.dump(obj, f, indent=2)

    def _read(self, path: str):
        if not os.path.exists(path):
            return None
        with open(path) as f:
            return json.load(f)

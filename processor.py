"""
Convert a raw QuickBooks Online P&L (by Month) JSON report into the
list-of-monthly-records format the dashboard expects.

QBO report structure (simplified):
  Columns → list of column defs, first is "Account", rest are month Money cols
  Rows    → nested Sections, each with sub-Rows (Data) and a Summary row

We use two layers of matching:
  1. SECTION_TOTALS  – exact match on Summary labels (reliable QBO labels)
  2. ACCOUNT_MAP     – keyword match on individual account line-item names
                       (matches your chart of accounts names)

If your account names differ from the keywords below, add entries to ACCOUNT_MAP.
"""

from datetime import datetime

# ── Target field template ──────────────────────────────────────────────────────

ZERO_RECORD = {
    # Totals (populated from QBO Summary rows)
    'totalIncome':          0.0,
    'totalCOGS':            0.0,
    'grossProfit':          0.0,
    'totalExpenses':        0.0,
    'netOperatingIncome':   0.0,
    'totalOtherIncome':     0.0,
    'totalOtherExpenses':   0.0,
    'netIncome':            0.0,
    # Revenue line items
    'fiservRevenue':        0.0,
    'payrocRevenue':        0.0,
    'advisoryRevenue':      0.0,
    'equipmentRevenue':     0.0,
    # Expense line items
    'fiservCommissions':    0.0,
    'personnelExpenses':    0.0,
    'travelMeals':          0.0,
    'marketing':            0.0,
    'insurance':            0.0,
    'professionalFees':     0.0,
    'facilities':           0.0,
    'itCosts':              0.0,
    'feesDues':             0.0,
    'officeSupplies':       0.0,
}

# ── Section total label → field name (exact match on QBO Summary labels) ──────

SECTION_TOTALS = {
    'Total Income':                 'totalIncome',
    'Total Revenue':                'totalIncome',
    'Total Cost of Goods Sold':     'totalCOGS',
    'Cost of Goods Sold':           'totalCOGS',
    'Gross Profit':                 'grossProfit',
    'Total Expenses':               'totalExpenses',
    'Total Operating Expenses':     'totalExpenses',
    'Net Operating Income':         'netOperatingIncome',
    'Operating Income':             'netOperatingIncome',
    'Total Other Income':           'totalOtherIncome',
    'Total Other Expenses':         'totalOtherExpenses',
    'Net Other Income':             'totalOtherIncome',
    'Net Income':                   'netIncome',
}

# ── Account keyword → field name (case-insensitive substring match) ───────────
# Add or edit entries here if your QuickBooks account names differ.

ACCOUNT_MAP = [
    # Revenue — order matters: more specific keywords first
    ('fiserv',          'fiservRevenue'),
    ('payroc',          'payrocRevenue'),
    ('advisory',        'advisoryRevenue'),
    ('equipment',       'equipmentRevenue'),
    # COGS
    ('fiserv commission', 'fiservCommissions'),
    ('commission',       'fiservCommissions'),
    # Expenses
    ('personnel',        'personnelExpenses'),
    ('payroll',          'personnelExpenses'),
    ('salaries',         'personnelExpenses'),
    ('wages',            'personnelExpenses'),
    ('travel',           'travelMeals'),
    ('meals',            'travelMeals'),
    ('entertainment',    'travelMeals'),
    ('marketing',        'marketing'),
    ('advertising',      'marketing'),
    ('insurance',        'insurance'),
    ('professional fee', 'professionalFees'),
    ('legal',            'professionalFees'),
    ('accounting',       'professionalFees'),
    ('consulting',       'professionalFees'),
    ('facilities',       'facilities'),
    ('rent',             'facilities'),
    ('utilities',        'facilities'),
    ('information tech', 'itCosts'),
    ('software',         'itCosts'),
    ('technology',       'itCosts'),
    ('computer',         'itCosts'),
    ('subscriptions',    'feesDues'),
    ('dues',             'feesDues'),
    ('licenses',         'feesDues'),
    ('memberships',      'feesDues'),
    ('office supplies',  'officeSupplies'),
    ('office expense',   'officeSupplies'),
    ('supplies',         'officeSupplies'),
]


# ── Public entry point ─────────────────────────────────────────────────────────

def process_pl_report(report: dict) -> list[dict]:
    """
    Parse a QBO ProfitAndLoss report JSON into a list of monthly dicts
    sorted chronologically.
    """
    columns = report.get('Columns', {}).get('Column', [])
    rows    = report.get('Rows',    {}).get('Row',    [])

    # Identify Money columns (index, "Mon YYYY" title)
    month_cols = [
        (i, col['ColTitle'])
        for i, col in enumerate(columns)
        if col.get('ColType') == 'Money' and col.get('ColTitle', '').strip()
    ]
    if not month_cols:
        return []

    # Build a dict keyed by column index
    months: dict[int, dict] = {
        idx: {'month': _normalize_month(title), **dict(ZERO_RECORD)}
        for idx, title in month_cols
    }

    # Walk all rows
    for row in rows:
        _walk_row(row, month_cols, months)

    # Sort by date, strip the index key, filter out empty months and invalid entries
    # (e.g. QBO "Total" column, partial month entries like "Mar 1-4, 2026")
    result = sorted(months.values(), key=lambda r: _parse_date(r['month']))
    return [
        r for r in result
        if _parse_date(r['month']) > datetime.min
        and (r['totalIncome'] != 0 or r['netIncome'] != 0)
    ]


# ── Recursive row walker ───────────────────────────────────────────────────────

def _walk_row(row: dict, month_cols: list, months: dict) -> None:
    row_type = row.get('type', '')

    if row_type == 'Section':
        # Recurse into sub-rows first
        for sub in row.get('Rows', {}).get('Row', []):
            _walk_row(sub, month_cols, months)
        # Then process the Summary line for this section
        summary = row.get('Summary', {})
        if summary:
            _apply_col_data(summary.get('ColData', []), month_cols, months, is_summary=True)

    elif row_type == 'Data':
        _apply_col_data(row.get('ColData', []), month_cols, months, is_summary=False)


def _apply_col_data(col_data: list, month_cols: list, months: dict, is_summary: bool) -> None:
    if not col_data:
        return
    label = col_data[0].get('value', '').strip()
    if not label:
        return

    # 1. Try exact match on section totals (summary rows)
    if is_summary:
        field = SECTION_TOTALS.get(label)
        if field:
            for idx, _ in month_cols:
                if idx < len(col_data):
                    months[idx][field] = _parse_amount(col_data[idx].get('value', ''))
            return

    # 2. Keyword match on individual account names
    label_lower = label.lower()
    for keyword, field in ACCOUNT_MAP:
        if keyword in label_lower:
            for idx, _ in month_cols:
                if idx < len(col_data):
                    months[idx][field] += _parse_amount(col_data[idx].get('value', ''))
            return   # only assign to the first matching keyword


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_amount(s: str) -> float:
    if not s:
        return 0.0
    try:
        return float(str(s).replace(',', '').strip())
    except (ValueError, TypeError):
        return 0.0


_MONTH_ABBR = {
    'jan': 'January', 'feb': 'February', 'mar': 'March',    'apr': 'April',
    'may': 'May',     'jun': 'June',     'jul': 'July',     'aug': 'August',
    'sep': 'September','oct': 'October', 'nov': 'November', 'dec': 'December',
}

def _normalize_month(title: str) -> str:
    """Convert 'Jan 2026' → 'January 2026', 'January 2026' → unchanged."""
    parts = title.strip().split()
    if len(parts) == 2:
        mo_key = parts[0].lower()[:3]
        if mo_key in _MONTH_ABBR:
            return f'{_MONTH_ABBR[mo_key]} {parts[1]}'
    return title


def _parse_date(month_str: str) -> datetime:
    for fmt in ('%B %Y', '%b %Y'):
        try:
            return datetime.strptime(month_str, fmt)
        except ValueError:
            pass
    return datetime.min

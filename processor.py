"""
Convert a raw QuickBooks Online P&L (by Month) JSON report into the
list-of-monthly-records format the dashboard expects.

QBO report structure:
  Columns → list of column defs; first is "Account", rest are Money cols per month
  Rows    → nested Sections with sub-Rows (Data) and a Summary row per section

Matching strategy:
  1. SECTION_TOTALS  – exact match on Summary label  (reliable QBO labels)
  2. ACCOUNT_MAP     – case-insensitive substring match on account names
                       ORDER MATTERS: more specific keywords must come first.
"""

from datetime import datetime

# ── Target field template ──────────────────────────────────────────────────────

ZERO_RECORD = {
    # Section totals (from QBO Summary rows — reliable)
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
    # COGS line items
    'fiservCommissions':    0.0,
    # Expense line items
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

# ── Section total label → field name ──────────────────────────────────────────
# Exact match on QBO Summary row labels. These are stable across companies.

SECTION_TOTALS = {
    'Total Income':                 'totalIncome',
    'Total Revenue':                'totalIncome',
    'Total Cost of Goods Sold':     'totalCOGS',
    'Cost of Goods Sold':           'totalCOGS',
    'Total COGS':                   'totalCOGS',
    'Gross Profit':                 'grossProfit',
    'Total Expenses':               'totalExpenses',
    'Total Operating Expenses':     'totalExpenses',
    'Net Operating Income':         'netOperatingIncome',
    'Operating Income':             'netOperatingIncome',
    'Total Other Income':           'totalOtherIncome',
    'Other Income':                 'totalOtherIncome',
    'Total Other Expenses':         'totalOtherExpenses',
    'Other Expenses':               'totalOtherExpenses',
    'Net Other Income':             'totalOtherIncome',
    'Net Income':                   'netIncome',
    'Net Profit':                   'netIncome',
}

# ── Account keyword → field name ──────────────────────────────────────────────
# Case-insensitive substring match on individual account line-item names.
# CRITICAL: More specific keywords MUST appear before broader ones.
# e.g. 'fiserv commission' must come before 'fiserv' so commissions
# are not incorrectly classified as revenue.

ACCOUNT_MAP = [
    # COGS — must come before revenue keywords to avoid misclassification
    ('fiserv commission',   'fiservCommissions'),
    ('fiserv commissions',  'fiservCommissions'),
    ('merchant commission', 'fiservCommissions'),
    ('processing fee',      'fiservCommissions'),

    # Revenue
    ('fiserv',              'fiservRevenue'),
    ('payroc',              'payrocRevenue'),
    ('advisory',            'advisoryRevenue'),
    ('equipment',           'equipmentRevenue'),

    # Expenses — specific before broad
    ('payroll tax',         'personnelExpenses'),
    ('payroll',             'personnelExpenses'),
    ('salaries',            'personnelExpenses'),
    ('wages',               'personnelExpenses'),
    ('personnel',           'personnelExpenses'),
    ('officer compensation','personnelExpenses'),
    ('contractor',          'personnelExpenses'),

    ('travel',              'travelMeals'),
    ('meals',               'travelMeals'),
    ('entertainment',       'travelMeals'),

    ('marketing',           'marketing'),
    ('advertising',         'marketing'),
    ('promotion',           'marketing'),

    ('insurance',           'insurance'),

    ('legal',               'professionalFees'),
    ('accounting',          'professionalFees'),
    ('consulting',          'professionalFees'),
    ('professional fee',    'professionalFees'),
    ('professional service','professionalFees'),

    ('rent',                'facilities'),
    ('utilities',           'facilities'),
    ('facilities',          'facilities'),
    ('office rent',         'facilities'),

    ('information tech',    'itCosts'),
    ('software',            'itCosts'),
    ('technology',          'itCosts'),
    ('computer',            'itCosts'),
    ('hosting',             'itCosts'),
    ('cloud',               'itCosts'),

    ('subscriptions',       'feesDues'),
    ('subscription',        'feesDues'),
    ('dues',                'feesDues'),
    ('licenses',            'feesDues'),
    ('license',             'feesDues'),
    ('memberships',         'feesDues'),
    ('membership',          'feesDues'),
    ('fees & dues',         'feesDues'),
    ('bank fee',            'feesDues'),
    ('bank charge',         'feesDues'),

    ('office supplies',     'officeSupplies'),
    ('office expense',      'officeSupplies'),
    ('supplies',            'officeSupplies'),
    ('postage',             'officeSupplies'),
    ('printing',            'officeSupplies'),
]


# ── Public entry point ─────────────────────────────────────────────────────────

def process_pl_report(report: dict) -> list:
    """
    Parse a QBO ProfitAndLoss report (summarized by Month) into a list
    of monthly dicts, sorted chronologically. Filters out the QBO 'Total'
    summary column automatically.
    """
    columns = report.get('Columns', {}).get('Column', [])
    rows    = report.get('Rows',    {}).get('Row',    [])

    if not columns or not rows:
        print('[processor] Empty report — no columns or rows.')
        return []

    # Identify Money columns that look like real months (e.g. "Jan 2023")
    # Skip any column whose title doesn't parse as a month (e.g. "TOTAL")
    month_cols = []
    for i, col in enumerate(columns):
        if col.get('ColType') != 'Money':
            continue
        title = col.get('ColTitle', '').strip()
        if not title:
            continue
        normalized = _normalize_month(title)
        if _parse_date(normalized) == datetime.min:
            print(f'[processor] Skipping non-month column: "{title}"')
            continue
        month_cols.append((i, normalized))

    if not month_cols:
        print('[processor] No valid month columns found.')
        return []

    print(f'[processor] Found {len(month_cols)} month columns: {[t for _, t in month_cols[:3]]}...')

    # Build a dict keyed by column index
    months = {
        idx: {'month': title, **dict(ZERO_RECORD)}
        for idx, title in month_cols
    }

    # Walk all rows
    for row in rows:
        _walk_row(row, month_cols, months)

    # Sort chronologically and drop months with no meaningful data
    result = sorted(months.values(), key=lambda r: _parse_date(r['month']))
    result = [r for r in result if r['totalIncome'] != 0 or r['netIncome'] != 0]
    print(f'[processor] Returning {len(result)} months.')
    return result


# ── Recursive row walker ───────────────────────────────────────────────────────

def _walk_row(row: dict, month_cols: list, months: dict) -> None:
    row_type = row.get('type', '')

    if row_type == 'Section':
        # Recurse into sub-rows
        for sub in row.get('Rows', {}).get('Row', []):
            _walk_row(sub, month_cols, months)
        # Process the Summary (section total) line
        summary = row.get('Summary')
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

    # 1. Exact match on section total labels
    if is_summary:
        field = SECTION_TOTALS.get(label)
        if field:
            for idx, _ in month_cols:
                if idx < len(col_data):
                    months[idx][field] = _parse_amount(col_data[idx].get('value', ''))
            return

    # 2. Keyword match on individual account names (first match wins)
    label_lower = label.lower()
    for keyword, field in ACCOUNT_MAP:
        if keyword in label_lower:
            for idx, _ in month_cols:
                if idx < len(col_data):
                    months[idx][field] += _parse_amount(col_data[idx].get('value', ''))
            return


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_amount(s: str) -> float:
    if not s:
        return 0.0
    try:
        return float(str(s).replace(',', '').strip())
    except (ValueError, TypeError):
        return 0.0


_MONTH_ABBR = {
    'jan': 'January',  'feb': 'February', 'mar': 'March',    'apr': 'April',
    'may': 'May',      'jun': 'June',     'jul': 'July',     'aug': 'August',
    'sep': 'September','oct': 'October',  'nov': 'November', 'dec': 'December',
}


def _normalize_month(title: str) -> str:
    """Convert 'Jan 2026' → 'January 2026'. Leaves invalid titles unchanged."""
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

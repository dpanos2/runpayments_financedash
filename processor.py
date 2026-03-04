"""
Convert a raw QuickBooks Online P&L (by Month) JSON report into the
list-of-monthly-records format the dashboard expects.

QBO report structure (simplified):
  Columns → list of column defs, first is "Account", rest are month Money cols
  Rows    → nested Sections, each with sub-Rows (Data) and a Summary row

We use two layers of matching:
  1. SECTION_TOTALS  – exact match on Summary labels (uses SET = for authoritative totals)
  2. ACCOUNT_MAP     – keyword match on individual Data row account names ONLY
                       (Summary rows never fall through to ACCOUNT_MAP — prevents double-counting)

Keywords are matched against Run Payments' actual QBO chart of accounts names.
CRITICAL: More specific keywords must appear before broader ones in ACCOUNT_MAP.
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

# ── Section total label → field name ──────────────────────────────────────────
# Exact match on QBO Summary row labels. Uses SET semantics (=) so subsection
# totals give clean authoritative values regardless of Data row accumulation.

SECTION_TOTALS = {
    # ── Top-level P&L totals ───────────────────────────────────────────────────
    'Total Income':                             'totalIncome',
    'Total Revenue':                            'totalIncome',
    'Total Cost of Goods Sold':                 'totalCOGS',
    'Cost of Goods Sold':                       'totalCOGS',
    'Total COGS':                               'totalCOGS',
    'Gross Profit':                             'grossProfit',
    'Total Expenses':                           'totalExpenses',
    'Total Operating Expenses':                 'totalExpenses',
    'Net Operating Income':                     'netOperatingIncome',
    'Operating Income':                         'netOperatingIncome',
    'Total Other Income':                       'totalOtherIncome',
    'Other Income':                             'totalOtherIncome',
    'Total Other Expenses':                     'totalOtherExpenses',
    'Other Expenses':                           'totalOtherExpenses',
    'Net Other Income':                         'totalOtherIncome',
    'Net Income':                               'netIncome',
    'Net Profit':                               'netIncome',

    # ── Revenue subsection totals (multiple label variants for QBO compatibility)
    'Total for 4000000 Fiserv Processing Revenue':  'fiservRevenue',
    'Total 4000000 Fiserv Processing Revenue':      'fiservRevenue',
    'Total Fiserv Processing Revenue':              'fiservRevenue',
    'Total for 4000002 Payroc Processing Revenue':  'payrocRevenue',
    'Total 4000002 Payroc Processing Revenue':      'payrocRevenue',
    'Total Payroc Processing Revenue':              'payrocRevenue',
    'Total for 4000004 Run Merchant Revenue':        'fiservRevenue',

    # ── Expense subsection totals ─────────────────────────────────────────────
    'Total for 6000000 Personnel Expenses':             'personnelExpenses',
    'Total 6000000 Personnel Expenses':                 'personnelExpenses',
    'Total Personnel Expenses':                         'personnelExpenses',
    'Total for 6300000 Travel, Meals & Ent':            'travelMeals',
    'Total 6300000 Travel, Meals & Ent':                'travelMeals',
    'Total for 6400000 Marketing, Advertising, & Promotion Expense': 'marketing',
    'Total 6400000 Marketing, Advertising, & Promotion Expense':     'marketing',
    'Total for 6500000 Insurance':                      'insurance',
    'Total 6500000 Insurance':                          'insurance',
    'Total for 6600000 Fees, Dues & Licenses Expense':  'feesDues',
    'Total 6600000 Fees, Dues & Licenses Expense':      'feesDues',
    'Total for 6700000 Office Supply Expenses':         'officeSupplies',
    'Total 6700000 Office Supply Expenses':             'officeSupplies',
    'Total for 6800000 Professional Fees':              'professionalFees',
    'Total 6800000 Professional Fees':                  'professionalFees',
    'Total for Facilities':                             'facilities',
    'Total Facilities':                                 'facilities',
    'Total for Information & Technology':               'itCosts',
    'Total Information & Technology':                   'itCosts',
    'Total for 6200000 IT Costs':                       'itCosts',
}

# ── Account keyword → field name ──────────────────────────────────────────────
# Applied ONLY to Data rows (individual account lines).
# Summary rows always return early — they never reach this list.
# Keywords match Run Payments' actual QBO account names (case-insensitive substring).
# CRITICAL: More specific keywords MUST appear before broader ones.

ACCOUNT_MAP = [
    # ── COGS — before revenue keywords to avoid misclassification ─────────────
    ('fiserv commissions',              'fiservCommissions'),   # 5000001 Fiserv Commissions
    ('fiserv commission',               'fiservCommissions'),   # singular
    ('equipment cost',                  'fiservCommissions'),   # 5100001 Equipment Cost (COGS!)
    ('hardware costs',                  'fiservCommissions'),   # 6200007B Hardware Costs COGS
    ('3rd party gateway',               'fiservCommissions'),   # 5100003 3rd Party Gateway Fees
    ('gateway fee',                     'fiservCommissions'),
    ('merchant commission',             'fiservCommissions'),
    ('processing fee',                  'fiservCommissions'),
    ('other cogs',                      'fiservCommissions'),   # 5100005 Other COGS

    # ── Revenue ───────────────────────────────────────────────────────────────
    ('fiserv-processing',               'fiservRevenue'),       # 4001001 Fiserv-Processing Revenue
    ('fiserv processing',               'fiservRevenue'),
    ('processor residual',              'fiservRevenue'),       # 4001003 Processor Residual
    ('run merchant',                    'fiservRevenue'),       # 4000004 Run Merchant Revenue
    ('other processing revenue',        'fiservRevenue'),       # 4004001 Other Processing Revenue
    ('fiserv',                          'fiservRevenue'),       # fallback
    ('payroc',                          'payrocRevenue'),       # 4002001 Payroc-Processing Revenue
    ('advisory-monthly',                'advisoryRevenue'),     # 4300001 Advisory-Monthly Revenue
    ('advisory',                        'advisoryRevenue'),
    ('equipment revenue',               'equipmentRevenue'),    # 4300011 Equipment Revenue
    ('equipment',                       'equipmentRevenue'),    # fallback (after 'equipment cost')

    # ── Personnel — payroll PROCESSING FEES must precede 'payroll' ────────────
    ('payroll processing',              'professionalFees'),    # 6800005 Payroll Processing Fees
    ('regular wages',                   'personnelExpenses'),   # all "X Regular Wages" accounts
    ('employer taxes',                  'personnelExpenses'),   # all "X Employer Taxes" accounts
    ('employer 401',                    'personnelExpenses'),   # 6099005 Employer 401(k) Costs
    ('employee benefits',               'personnelExpenses'),   # 6099000
    ('dental & vision',                 'personnelExpenses'),   # 6099003
    ("workers' compensation",           'personnelExpenses'),   # 6099007
    ('continuing eduction',             'personnelExpenses'),   # 6099009 (QBO typo — keep as-is)
    ('continuing education',            'personnelExpenses'),   # correct spelling variant
    ('employee gifts',                  'personnelExpenses'),   # 6099480
    ('health insurance & accident',     'personnelExpenses'),   # 609901
    ('sales support bonus',             'personnelExpenses'),
    ('tech & dev bonus',                'personnelExpenses'),   # 6016003
    ('compensation & benefits',         'personnelExpenses'),   # 6001000 section
    ('payroll tax',                     'personnelExpenses'),
    ('payroll',                         'personnelExpenses'),
    ('salaries',                        'personnelExpenses'),
    ('wages',                           'personnelExpenses'),   # catches all "X Regular Wages"
    ('personnel',                       'personnelExpenses'),
    ('officer compensation',            'personnelExpenses'),
    ('contractor',                      'personnelExpenses'),
    ('severance',                       'personnelExpenses'),

    # ── Travel, Meals & Entertainment ─────────────────────────────────────────
    ('airfare',                         'travelMeals'),         # 6300001
    ('lodging',                         'travelMeals'),         # 6300003
    ('parking',                         'travelMeals'),         # 6300005
    ('taxi',                            'travelMeals'),         # 6300007
    ('ride share',                      'travelMeals'),         # 6300007
    ('vehicle rental',                  'travelMeals'),         # 6300011
    ('travel - other',                  'travelMeals'),         # 6300013
    ('meals with clients',              'travelMeals'),         # 6310110
    ('team meals',                      'travelMeals'),         # 6310120
    ('travel meals',                    'travelMeals'),         # 6310130
    ('team events',                     'travelMeals'),         # 6310220
    ('meals & entertainment',           'travelMeals'),         # 6300009
    ('entertainment',                   'travelMeals'),         # 6310210
    ('travel, meals',                   'travelMeals'),         # section name fallback
    ('travel',                          'travelMeals'),
    ('meals',                           'travelMeals'),

    # ── Marketing, Advertising & Promotion ────────────────────────────────────
    ('advertising & promotion',         'marketing'),           # 6400001
    ('sponsorship costs',               'marketing'),           # 6400003
    ('tradeshows and conferences',      'marketing'),           # 6400009
    ('charitable contributions',        'marketing'),           # 6400023
    ('website design',                  'marketing'),           # 6400320
    ('trade show displays',             'marketing'),           # 6400380
    ('gifts/contributions',             'marketing'),           # 6400025
    ('marketing',                       'marketing'),
    ('advertising',                     'marketing'),
    ('promotion',                       'marketing'),
    ('sponsorship',                     'marketing'),

    # ── Insurance ─────────────────────────────────────────────────────────────
    ('general liability insurance',     'insurance'),           # 6500001
    ('d&o insurance',                   'insurance'),           # 6500003
    ('insurance - other',               'insurance'),           # 6500005
    ('business insurance',              'insurance'),
    ('insurance',                       'insurance'),

    # ── Professional Fees — payroll processing fee handled above ──────────────
    ('legal fees',                      'professionalFees'),    # 6800003
    ('legal & accounting services',     'professionalFees'),    # 6800006
    ('finance / accounting',            'professionalFees'),    # 6800007
    ('general consulting fees',         'professionalFees'),    # 6800013
    ('professional fees - other',       'professionalFees'),    # 6800019
    ('accounting fees',                 'professionalFees'),    # 680005
    ('professional fee',                'professionalFees'),
    ('professional service',            'professionalFees'),
    ('consulting',                      'professionalFees'),
    ('legal',                           'professionalFees'),
    ('accounting',                      'professionalFees'),

    # ── Facilities ────────────────────────────────────────────────────────────
    ('office rent',                     'facilities'),          # 6100001
    ('utility costs',                   'facilities'),          # 6100005
    ('philadelphia office rent',        'facilities'),          # 6100006
    ('chicago office rent',             'facilities'),          # 6100007B
    ('general repairs',                 'facilities'),          # 6100007
    ('wayne office rent',               'facilities'),          # 6100008
    ('regus office rent',               'facilities'),          # 6100009B
    ('phone service',                   'facilities'),          # 6100009
    ('lease expense',                   'facilities'),          # 6100002
    ('rent',                            'facilities'),
    ('utilities',                       'facilities'),
    ('facilities',                      'facilities'),

    # ── Information & Technology ───────────────────────────────────────────────
    ('software / saas',                 'itCosts'),             # 6200003
    ('web/cloud hosting',               'itCosts'),             # 6200005
    ('server hosting fees',             'itCosts'),             # 6200007
    ('it costs - other',                'itCosts'),             # 6200011
    ('software & apps',                 'itCosts'),             # 6200014
    ('it costs',                        'itCosts'),
    ('information tech',                'itCosts'),
    ('software',                        'itCosts'),
    ('technology',                      'itCosts'),
    ('computer',                        'itCosts'),
    ('hosting',                         'itCosts'),
    ('cloud',                           'itCosts'),

    # ── Fees, Dues & Licenses ─────────────────────────────────────────────────
    ('bank fees & service charges',     'feesDues'),            # 6600001
    ('bank fees',                       'feesDues'),
    ('membership fees',                 'feesDues'),            # 6600005
    ('fees/subscriptions',              'feesDues'),            # 6600009
    ('quickbooks payments fees',        'feesDues'),            # 6600120
    ('subscriptions',                   'feesDues'),
    ('subscription',                    'feesDues'),
    ('dues',                            'feesDues'),
    ('licenses',                        'feesDues'),
    ('license',                         'feesDues'),
    ('memberships',                     'feesDues'),
    ('membership',                      'feesDues'),
    ('fees & dues',                     'feesDues'),
    ('bank fee',                        'feesDues'),
    ('bank charge',                     'feesDues'),

    # ── Office Supplies ───────────────────────────────────────────────────────
    ('postage & delivery',              'officeSupplies'),      # 6700003
    ('office supplies - other',         'officeSupplies'),      # 6700009
    ('supplies & materials',            'officeSupplies'),      # 6701018
    ('office supplies',                 'officeSupplies'),      # 6700001
    ('office expense',                  'officeSupplies'),
    ('supplies',                        'officeSupplies'),
    ('postage',                         'officeSupplies'),
    ('printing',                        'officeSupplies'),
]


# ── Public entry point ─────────────────────────────────────────────────────────

def process_pl_report(report: dict) -> list:
    """
    Parse a QBO ProfitAndLoss report JSON into a list of monthly dicts
    sorted chronologically.
    """
    columns = report.get('Columns', {}).get('Column', [])
    rows    = report.get('Rows',    {}).get('Row',    [])

    # Identify Money columns that look like real months (e.g. "Jan 2023").
    # Skip the QBO "TOTAL" column and any partial-month entries.
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

    # 1. Summary rows: exact match against SECTION_TOTALS only.
    #    ALWAYS return here — never fall through to ACCOUNT_MAP.
    #    This prevents double-counting when subsection totals contain keywords.
    if is_summary:
        field = SECTION_TOTALS.get(label)
        if field:
            for idx, _ in month_cols:
                if idx < len(col_data):
                    months[idx][field] = _parse_amount(col_data[idx].get('value', ''))
        return  # ← critical: return regardless of whether label matched

    # 2. Data rows only: keyword match on individual account names
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



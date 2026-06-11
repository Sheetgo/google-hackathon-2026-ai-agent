"""
Skill handlers for the Sheetgo A2A agent.

Provides three chainable skills with mock data:
  search_workflows  → list/filter workflows
  get_workflow_context → workflow details + spreadsheet list
  query_spreadsheet_data → columns + rows for a spreadsheet
"""

# ---------------------------------------------------------------------------
# Mock Data
# ---------------------------------------------------------------------------

MOCK_WORKFLOWS = [
    {"id": "wf-001", "name": "Sales Pipeline Sync"},
    {"id": "wf-002", "name": "HR Onboarding Tracker"},
    {"id": "wf-003", "name": "Inventory Management"},
    {"id": "wf-004", "name": "Marketing Campaign Reports"},
    {"id": "wf-005", "name": "Finance Monthly Close"},
]

MOCK_SPREADSHEETS = {
    "wf-001": [
        {"id": "ss-001", "name": "Q1 Sales Data"},
        {"id": "ss-002", "name": "Sales Targets 2025"},
    ],
    "wf-002": [
        {"id": "ss-003", "name": "Employee Directory"},
        {"id": "ss-004", "name": "Onboarding Checklist"},
        {"id": "ss-005", "name": "Benefits Enrollment"},
    ],
    "wf-003": [
        {"id": "ss-006", "name": "Warehouse Stock Levels"},
        {"id": "ss-007", "name": "Supplier Orders"},
    ],
    "wf-004": [
        {"id": "ss-008", "name": "Campaign Performance"},
        {"id": "ss-009", "name": "Ad Spend Tracker"},
    ],
    "wf-005": [
        {"id": "ss-010", "name": "GL Balances"},
        {"id": "ss-011", "name": "Expense Reports"},
        {"id": "ss-012", "name": "Revenue Summary"},
    ],
}

MOCK_SPREADSHEET_DATA = {
    "ss-001": {
        "columns": ["Date", "Region", "Amount", "Rep"],
        "rows": [
            ["2025-01-15", "North", 15000, "Alice"],
            ["2025-01-22", "South", 22000, "Bob"],
            ["2025-02-03", "East", 18500, "Carol"],
        ],
    },
    "ss-002": {
        "columns": ["Region", "Q1 Target", "Q2 Target"],
        "rows": [
            ["North", 50000, 55000],
            ["South", 60000, 65000],
            ["East", 45000, 50000],
        ],
    },
    "ss-003": {
        "columns": ["Name", "Department", "Start Date"],
        "rows": [
            ["Alice Johnson", "Engineering", "2024-03-01"],
            ["Bob Smith", "Marketing", "2024-06-15"],
        ],
    },
    "ss-004": {
        "columns": ["Task", "Owner", "Status"],
        "rows": [
            ["Laptop setup", "IT", "Done"],
            ["Badge request", "Security", "Pending"],
            ["Orientation", "HR", "Scheduled"],
        ],
    },
    "ss-005": {
        "columns": ["Plan", "Monthly Cost", "Enrolled"],
        "rows": [
            ["Health Plus", 450, True],
            ["Dental Basic", 75, False],
        ],
    },
    "ss-006": {
        "columns": ["SKU", "Product", "Quantity", "Warehouse"],
        "rows": [
            ["SKU-100", "Widget A", 1200, "WH-East"],
            ["SKU-101", "Widget B", 800, "WH-West"],
            ["SKU-102", "Gadget C", 350, "WH-East"],
        ],
    },
    "ss-007": {
        "columns": ["Supplier", "Order Date", "Total"],
        "rows": [
            ["Acme Corp", "2025-01-10", 25000],
            ["Global Parts", "2025-02-01", 18000],
        ],
    },
    "ss-008": {
        "columns": ["Campaign", "Channel", "Impressions", "Clicks"],
        "rows": [
            ["Spring Launch", "Email", 50000, 3200],
            ["Spring Launch", "Social", 120000, 8500],
        ],
    },
    "ss-009": {
        "columns": ["Channel", "Budget", "Spent"],
        "rows": [
            ["Google Ads", 10000, 8750],
            ["Facebook", 5000, 4200],
            ["LinkedIn", 3000, 2900],
        ],
    },
    "ss-010": {
        "columns": ["Account", "Debit", "Credit"],
        "rows": [
            ["1000 - Cash", 150000, 0],
            ["2000 - AP", 0, 45000],
            ["3000 - Revenue", 0, 210000],
        ],
    },
    "ss-011": {
        "columns": ["Employee", "Category", "Amount", "Approved"],
        "rows": [
            ["Alice", "Travel", 1200, True],
            ["Bob", "Software", 499, True],
        ],
    },
    "ss-012": {
        "columns": ["Month", "Revenue", "Expenses", "Net"],
        "rows": [
            ["January", 210000, 175000, 35000],
            ["February", 225000, 180000, 45000],
        ],
    },
}


# ---------------------------------------------------------------------------
# Skill Handlers
# ---------------------------------------------------------------------------

def search_workflows(query=None):
    """Filter mock workflows by name substring. Returns all if no query."""
    if query:
        results = [w for w in MOCK_WORKFLOWS if query.lower() in w["name"].lower()]
    else:
        results = list(MOCK_WORKFLOWS)


    data = ['This are the workflows:']

    for w in results:
        data.append(f'- {w["name"]}')

    # return "\n".join(data) + "\n", len(results)
    return {'workflows': results, 'count': len(results),}


def get_workflow_context(workflow_id):
    """Return workflow name + spreadsheet list, or error dict."""
    workflow = next((w for w in MOCK_WORKFLOWS if w["id"] == workflow_id), None)
    if not workflow:
        return {"error": f"Workflow '{workflow_id}' not found"}
    spreadsheets = MOCK_SPREADSHEETS.get(workflow_id, [])
    return {"workflow": workflow, "spreadsheets": spreadsheets}


def query_spreadsheet_data(spreadsheet_id):
    """Return columns + rows for a spreadsheet, or error dict."""
    data = MOCK_SPREADSHEET_DATA.get(spreadsheet_id)
    if not data:
        return {"error": f"Spreadsheet '{spreadsheet_id}' not found"}
    return {"columns": data["columns"], "rows": data["rows"]}

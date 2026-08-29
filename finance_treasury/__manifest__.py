# -*- coding: utf-8 -*-
{
    'name': 'Finance Treasury',
    'version': '17.0.2.0.0',
    'category': 'Accounting/Finance',
    'summary': 'Universal Treasury Management: Cash, Bank, Card, Wallet & Financial Operations',
    'description': """
Finance Treasury — Universal Treasury Management
=================================================

A comprehensive treasury management system that handles all financial operations
through a single unified transaction engine with full Odoo Accounting integration.

Key Features
------------
* **Multi-Account Management** — Cash, Bank, Card, and Wallet accounts in one place
* **Universal Transactions** — Single model for income and expenses with auto journal entries
* **Account-to-Account Transfers** — Same-currency transfers with balance validation
* **Multi-Currency Exchange** — Auto-calculated rates from Odoo, manual override, fee support
* **Real-Time Balances** — Computed live from posted journal items (account.move.line)
* **Negative Balance Protection** — Per-account toggle to allow or prevent overdraft
* **Kanban Dashboard** — Visual overview of all accounts grouped by type
* **Pivot & Graph Reports** — Cash Flow and Income vs. Expense analysis
* **Role-Based Security** — Treasury User (daily ops) and Treasury Manager (full control)
* **Auto Sequences** — Automatic reference numbers for all documents
* **Multi-Company** — Full multi-company support with company-based record rules
* **Mail Tracking** — Chatter integration with field tracking on all records

Accounting Integration
----------------------
Every treasury operation automatically creates and posts journal entries:
* Income: Debit Account CoA → Credit Category CoA
* Expense: Debit Category CoA → Credit Account CoA
* Transfers & Exchanges: Paired transactions with proper counterparts

Data Models: finance.account, finance.transaction, finance.transfer,
finance.exchange, finance.category
    """,
    'author': 'Jonibek Yorqulov',
    'website': 'https://github.com/jonibekodoo',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
        'account',
    ],
    'data': [
        # Security
        'security/treasury_security.xml',
        'security/ir.model.access.csv',
        # Data
        'data/sequence_data.xml',
        # Views
        'views/finance_account_views.xml',
        'views/finance_category_views.xml',
        'views/finance_transaction_views.xml',
        'views/finance_transfer_views.xml',
        'views/finance_exchange_views.xml',
        # Reports (must load before menus that reference report actions)
        'report/transaction_report_views.xml',
        # Menus
        'views/menu_views.xml',
    ],
    'demo': [
        'demo/demo_data.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'images': [
        'static/description/icon.png',
    ],
}

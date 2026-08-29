# -*- coding: utf-8 -*-

from odoo import models, fields


class FinanceCategory(models.Model):
    """
    Categories used to classify transactions.
    Each category is linked to a Chart of Account entry that serves as
    the counterpart side of the journal entry when a transaction is confirmed.

    Examples:
        Income category "Sales Revenue"  → linked to CoA income account
        Expense category "Rent"          → linked to CoA expense account
        Transfer category                → linked to CoA transfer clearing account
    """
    _name = 'finance.category'
    _description = 'Finance Category'
    _order = 'type, name'

    name = fields.Char(
        string='Category Name',
        required=True,
        help='Name of the financial category.',
    )
    type = fields.Selection(
        selection=[
            ('income', 'Income'),
            ('expense', 'Expense'),
            ('transfer', 'Transfer'),
            ('exchange', 'Exchange'),
        ],
        string='Category Type',
        required=True,
        default='expense',
        help='Type of category: income, expense, transfer or currency exchange.',
    )
    account_account_id = fields.Many2one(
        comodel_name='account.account',
        string='Chart of Account',
        required=True,
        help='The chart of accounts entry for this category. '
             'This is used as the counterpart side of journal entries:\n'
             '- Income: this account is CREDITED\n'
             '- Expense: this account is DEBITED',
    )
    active = fields.Boolean(
        string='Active',
        default=True,
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company',
        default=lambda self: self.env.company,
    )

    _sql_constraints = [
        ('name_type_unique', 'UNIQUE(name, type, company_id)',
         'A category with this name and type already exists for this company!'),
    ]

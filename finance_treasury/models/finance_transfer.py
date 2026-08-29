# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class FinanceTransfer(models.Model):
    """
    Account-to-account transfer.
    On confirmation, two transactions are created:
      - an outgoing transaction on the source account
      - an incoming transaction on the destination account
    A category must be selected to determine the counterpart CoA for journal entries.
    """
    _name = 'finance.transfer'
    _description = 'Finance Transfer'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(
        string='Reference',
        readonly=True,
        copy=False,
        default=lambda self: _('New'),
        help='Unique auto-generated reference for this transfer.',
    )
    date = fields.Date(
        string='Date',
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    from_account_id = fields.Many2one(
        comodel_name='finance.account',
        string='From Account',
        required=True,
        tracking=True,
        help='Source account (money leaves here).',
    )
    to_account_id = fields.Many2one(
        comodel_name='finance.account',
        string='To Account',
        required=True,
        tracking=True,
        help='Destination account (money arrives here).',
    )
    category_id = fields.Many2one(
        comodel_name='finance.category',
        string='Category',
        required=True,
        domain="[('type', '=', 'transfer')]",
        tracking=True,
        help='Transfer category — determines the counterpart Chart of Account for journal entries.',
    )
    amount = fields.Monetary(
        string='Amount',
        required=True,
        currency_field='currency_id',
        tracking=True,
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        related='from_account_id.currency_id',
        store=True,
        readonly=True,
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('confirmed', 'Confirmed'),
            ('cancelled', 'Cancelled'),
        ],
        string='Status',
        default='draft',
        required=True,
        tracking=True,
        copy=False,
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company',
        related='from_account_id.company_id',
        store=True,
        readonly=True,
    )
    description = fields.Text(
        string='Description',
        help='Additional notes about this transfer.',
    )
    # Links to generated transactions
    out_transaction_id = fields.Many2one(
        comodel_name='finance.transaction',
        string='Outgoing Transaction',
        readonly=True,
        copy=False,
    )
    in_transaction_id = fields.Many2one(
        comodel_name='finance.transaction',
        string='Incoming Transaction',
        readonly=True,
        copy=False,
    )

    # -------------------------------------------------------------------------
    # CONSTRAINTS
    # -------------------------------------------------------------------------

    @api.constrains('from_account_id', 'to_account_id')
    def _check_different_accounts(self):
        """Source and destination accounts must be different."""
        for rec in self:
            if rec.from_account_id == rec.to_account_id:
                raise ValidationError(
                    _('Source and destination accounts must be different.')
                )

    @api.constrains('from_account_id', 'to_account_id')
    def _check_same_currency(self):
        """Both accounts must use the same currency for a transfer."""
        for rec in self:
            if rec.from_account_id and rec.to_account_id:
                if rec.from_account_id.currency_id != rec.to_account_id.currency_id:
                    raise ValidationError(
                        _('Currency mismatch: you cannot transfer between accounts '
                          'with different currencies.\n'
                          '• %(from_acc)s uses %(from_cur)s\n'
                          '• %(to_acc)s uses %(to_cur)s\n\n'
                          'Use a Currency Exchange instead.',
                          from_acc=rec.from_account_id.name,
                          from_cur=rec.from_account_id.currency_id.name,
                          to_acc=rec.to_account_id.name,
                          to_cur=rec.to_account_id.currency_id.name,
                          )
                    )

    @api.constrains('amount')
    def _check_amount_positive(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError(_('Transfer amount must be greater than zero.'))

    # -------------------------------------------------------------------------
    # ONCHANGE
    # -------------------------------------------------------------------------

    @api.onchange('from_account_id')
    def _onchange_from_account_id(self):
        """
        When the source account changes:
        - Clear the destination if its currency no longer matches.
        - Return a domain so the dropdown only shows accounts with the same currency.
        """
        if self.from_account_id:
            currency = self.from_account_id.currency_id
            # Clear destination if it now has a different currency
            if self.to_account_id and self.to_account_id.currency_id != currency:
                self.to_account_id = False
            return {
                'domain': {
                    'to_account_id': [
                        ('currency_id', '=', currency.id),
                        ('id', '!=', self.from_account_id.id),
                    ],
                },
            }
        return {
            'domain': {
                'to_account_id': [],
            },
        }

    # -------------------------------------------------------------------------
    # CRUD
    # -------------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('finance.transfer') or _('New')
        return super().create(vals_list)

    # -------------------------------------------------------------------------
    # ACTIONS
    # -------------------------------------------------------------------------

    def action_confirm(self):
        """
        Confirm transfer:
        1. Validate sufficient balance on source account
        2. Create outgoing transaction on source
        3. Create incoming transaction on destination
        Both transactions use the transfer's category for journal entry counterpart.
        """
        Transaction = self.env['finance.transaction']
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only draft transfers can be confirmed.'))

            # Check negative balance on source
            if not rec.from_account_id.allow_negative:
                if rec.from_account_id.balance < rec.amount:
                    raise UserError(
                        _('Insufficient balance on source account "%s". '
                          'Balance: %s, Transfer amount: %s.')
                        % (rec.from_account_id.name,
                           rec.from_account_id.balance, rec.amount)
                    )

            # Create outgoing transaction
            out_txn = Transaction.create({
                'date': rec.date,
                'account_id': rec.from_account_id.id,
                'type': 'out',
                'amount': rec.amount,
                'category_id': rec.category_id.id,
                'description': _('Transfer to %s — %s') % (rec.to_account_id.name, rec.name),
                'transfer_id': rec.id,
                'state': 'confirmed',
            })

            # Create incoming transaction
            in_txn = Transaction.create({
                'date': rec.date,
                'account_id': rec.to_account_id.id,
                'type': 'in',
                'amount': rec.amount,
                'category_id': rec.category_id.id,
                'description': _('Transfer from %s — %s') % (rec.from_account_id.name, rec.name),
                'transfer_id': rec.id,
                'state': 'confirmed',
            })

            rec.write({
                'state': 'confirmed',
                'out_transaction_id': out_txn.id,
                'in_transaction_id': in_txn.id,
            })

    def action_cancel(self):
        """Cancel the transfer and its generated transactions (+ journal entries)."""
        for rec in self:
            if rec.state not in ('draft', 'confirmed'):
                raise UserError(_('Cannot cancel a transfer in this state.'))
            if rec.out_transaction_id and rec.out_transaction_id.state == 'confirmed':
                rec.out_transaction_id.action_cancel()
            if rec.in_transaction_id and rec.in_transaction_id.state == 'confirmed':
                rec.in_transaction_id.action_cancel()
            rec.state = 'cancelled'

    def action_reset_draft(self):
        """Reset cancelled transfer back to draft (removes linked transactions)."""
        for rec in self:
            if rec.state != 'cancelled':
                raise UserError(_('Only cancelled transfers can be reset to draft.'))
            txns = rec.out_transaction_id | rec.in_transaction_id
            rec.write({
                'out_transaction_id': False,
                'in_transaction_id': False,
                'state': 'draft',
            })
            txns.filtered(lambda t: t.state == 'cancelled').unlink()

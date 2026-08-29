# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class FinanceExchange(models.Model):
    """
    Currency exchange between two accounts with different currencies.
    On confirmation, two transactions are created:
      - an outgoing transaction from the source account (from_amount in from_currency)
      - an incoming transaction to the destination account (to_amount in to_currency)
    The exchange rate can be entered manually or calculated automatically.
    """
    _name = 'finance.exchange'
    _description = 'Finance Exchange'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(
        string='Reference',
        readonly=True,
        copy=False,
        default=lambda self: _('New'),
        help='Unique auto-generated reference.',
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
        help='Source account (outgoing currency).',
    )
    to_account_id = fields.Many2one(
        comodel_name='finance.account',
        string='To Account',
        required=True,
        tracking=True,
        help='Destination account (incoming currency).',
    )
    from_currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='From Currency',
        related='from_account_id.currency_id',
        store=True,
        readonly=True,
    )
    to_currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='To Currency',
        related='to_account_id.currency_id',
        store=True,
        readonly=True,
    )
    from_amount = fields.Monetary(
        string='From Amount',
        required=True,
        currency_field='from_currency_id',
        tracking=True,
        help='Amount leaving the source account.',
    )
    to_amount = fields.Monetary(
        string='To Amount',
        required=True,
        currency_field='to_currency_id',
        tracking=True,
        help='Amount arriving at the destination account.',
    )
    rate = fields.Float(
        string='Exchange Rate',
        digits=(16, 6),
        compute='_compute_rate',
        inverse='_inverse_rate',
        store=True,
        tracking=True,
        help='Rate = to_amount / from_amount.',
    )
    category_id = fields.Many2one(
        comodel_name='finance.category',
        string='Category',
        required=True,
        domain="[('type', '=', 'exchange')]",
        tracking=True,
        help='Exchange category — determines the counterpart Chart of Account for journal entries.',
    )
    fee = fields.Monetary(
        string='Fee',
        currency_field='from_currency_id',
        default=0.0,
        help='Exchange fee charged in source currency.',
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
    # COMPUTE / INVERSE
    # -------------------------------------------------------------------------

    @api.depends('from_amount', 'to_amount')
    def _compute_rate(self):
        """Calculate rate as to_amount / from_amount."""
        for rec in self:
            if rec.from_amount:
                rec.rate = rec.to_amount / rec.from_amount
            else:
                rec.rate = 0.0

    def _inverse_rate(self):
        """When rate is set manually, recalculate to_amount."""
        for rec in self:
            if rec.rate and rec.from_amount:
                rec.to_amount = rec.from_amount * rec.rate

    @api.onchange('from_amount', 'rate')
    def _onchange_compute_to_amount(self):
        """Auto-compute to_amount when from_amount or rate changes."""
        if self.from_amount and self.rate:
            self.to_amount = self.from_amount * self.rate

    @api.onchange('from_account_id', 'to_account_id', 'from_amount')
    def _onchange_auto_rate(self):
        """
        Auto-fill exchange rate from Odoo's currency rates
        when both accounts and from_amount are set.
        """
        if (self.from_account_id and self.to_account_id
                and self.from_account_id.currency_id != self.to_account_id.currency_id
                and self.from_amount):
            from_currency = self.from_account_id.currency_id
            to_currency = self.to_account_id.currency_id
            self.to_amount = from_currency._convert(
                self.from_amount,
                to_currency,
                self.env.company,
                self.date or fields.Date.context_today(self),
            )

    # -------------------------------------------------------------------------
    # CONSTRAINTS
    # -------------------------------------------------------------------------

    @api.constrains('from_account_id', 'to_account_id')
    def _check_different_accounts(self):
        for rec in self:
            if rec.from_account_id == rec.to_account_id:
                raise ValidationError(
                    _('Source and destination accounts must be different.')
                )

    @api.constrains('from_amount', 'to_amount')
    def _check_amounts_positive(self):
        for rec in self:
            if rec.from_amount <= 0 or rec.to_amount <= 0:
                raise ValidationError(_('Exchange amounts must be greater than zero.'))

    # -------------------------------------------------------------------------
    # CRUD
    # -------------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('finance.exchange') or _('New')
        return super().create(vals_list)

    # -------------------------------------------------------------------------
    # ACTIONS
    # -------------------------------------------------------------------------

    def action_confirm(self):
        """
        Confirm the exchange:
        1. Validate source balance
        2. Create outgoing transaction (from_amount + fee) on source
        3. Create incoming transaction (to_amount) on destination
        """
        Transaction = self.env['finance.transaction']
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only draft exchanges can be confirmed.'))

            total_out = rec.from_amount + rec.fee
            # Check negative balance on source
            if not rec.from_account_id.allow_negative:
                if rec.from_account_id.balance < total_out:
                    raise UserError(
                        _('Insufficient balance on source account "%s". '
                          'Balance: %s, Required: %s (amount + fee).')
                        % (rec.from_account_id.name,
                           rec.from_account_id.balance, total_out)
                    )

            # Create outgoing transaction with the exchange's category
            out_txn = Transaction.create({
                'date': rec.date,
                'account_id': rec.from_account_id.id,
                'type': 'out',
                'amount': total_out,
                'category_id': rec.category_id.id,
                'description': _('Exchange to %s — %s') % (rec.to_account_id.name, rec.name),
                'exchange_id': rec.id,
                'state': 'confirmed',
            })

            # Create incoming transaction with the exchange's category
            in_txn = Transaction.create({
                'date': rec.date,
                'account_id': rec.to_account_id.id,
                'type': 'in',
                'amount': rec.to_amount,
                'category_id': rec.category_id.id,
                'description': _('Exchange from %s — %s') % (rec.from_account_id.name, rec.name),
                'exchange_id': rec.id,
                'state': 'confirmed',
            })

            rec.write({
                'state': 'confirmed',
                'out_transaction_id': out_txn.id,
                'in_transaction_id': in_txn.id,
            })

    def action_cancel(self):
        """Cancel the exchange and its generated transactions (+ journal entries)."""
        for rec in self:
            if rec.state not in ('draft', 'confirmed'):
                raise UserError(_('Cannot cancel an exchange in this state.'))
            # Cancel linked transactions — use action_cancel to also cancel journal entries
            if rec.out_transaction_id and rec.out_transaction_id.state == 'confirmed':
                rec.out_transaction_id.action_cancel()
            if rec.in_transaction_id and rec.in_transaction_id.state == 'confirmed':
                rec.in_transaction_id.action_cancel()
            rec.state = 'cancelled'

    def action_reset_draft(self):
        """Reset cancelled exchange back to draft."""
        for rec in self:
            if rec.state != 'cancelled':
                raise UserError(_('Only cancelled exchanges can be reset to draft.'))
            txns = rec.out_transaction_id | rec.in_transaction_id
            rec.write({
                'out_transaction_id': False,
                'in_transaction_id': False,
                'state': 'draft',
            })
            txns.filtered(lambda t: t.state == 'cancelled').unlink()

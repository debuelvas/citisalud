# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class FinanceTransaction(models.Model):
    """
    Universal financial transaction model.

    On confirmation:
        - Checks that the account has sufficient balance (for outgoing)
        - Creates a journal entry using:
            * The finance.account's CoA  as one side
            * The finance.category's CoA as the counterpart side
            * The finance.account's journal
        - Posts the journal entry

    On cancellation:
        - The linked journal entry is cancelled

    On deletion:
        - The linked journal entry is deleted too
    """
    _name = 'finance.transaction'
    _description = 'Finance Transaction'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(
        string='Reference',
        readonly=True,
        copy=False,
        default=lambda self: _('New'),
        help='Unique auto-generated reference for this transaction.',
    )
    date = fields.Date(
        string='Date',
        required=True,
        default=fields.Date.context_today,
        tracking=True,
        help='Date of the transaction.',
    )
    account_id = fields.Many2one(
        comodel_name='finance.account',
        string='Account',
        required=True,
        tracking=True,
        help='The finance account this transaction belongs to.',
    )
    type = fields.Selection(
        selection=[
            ('in', 'Income'),
            ('out', 'Expense'),
        ],
        string='Type',
        required=True,
        default='out',
        tracking=True,
        help='Whether money is coming in or going out.',
    )
    amount = fields.Monetary(
        string='Amount',
        required=True,
        currency_field='currency_id',
        tracking=True,
        help='Transaction amount in account currency.',
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        related='account_id.currency_id',
        store=True,
        readonly=True,
        help='Currency inherited from the linked account.',
    )
    category_id = fields.Many2one(
        comodel_name='finance.category',
        string='Category',
        required=True,
        tracking=True,
        help='Category determines the counterpart Chart of Account for the journal entry.',
    )
    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Partner',
        help='Related partner (customer, vendor, employee, etc.).',
    )
    description = fields.Text(
        string='Description',
        help='Additional notes about this transaction.',
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
        help='Draft: editable. Confirmed: posted and affects balance. Cancelled: void.',
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company',
        related='account_id.company_id',
        store=True,
        readonly=True,
    )

    # -------------------------------------------------------------------------
    # Accounting Integration
    # -------------------------------------------------------------------------
    move_id = fields.Many2one(
        comodel_name='account.move',
        string='Journal Entry',
        readonly=True,
        copy=False,
        help='The accounting journal entry created when this transaction is confirmed.',
    )

    # Origin references (for traceability from transfers / exchanges)
    transfer_id = fields.Many2one(
        comodel_name='finance.transfer',
        string='Source Transfer',
        readonly=True,
        copy=False,
        help='Transfer that generated this transaction.',
    )
    exchange_id = fields.Many2one(
        comodel_name='finance.exchange',
        string='Source Exchange',
        readonly=True,
        copy=False,
        help='Exchange that generated this transaction.',
    )

    # -------------------------------------------------------------------------
    # ONCHANGE
    # -------------------------------------------------------------------------

    @api.onchange('type')
    def _onchange_type(self):
        """Clear category when type changes if it no longer matches."""
        if self.type and self.category_id:
            expected = 'income' if self.type == 'in' else 'expense'
            if self.category_id.type != expected:
                self.category_id = False

    # -------------------------------------------------------------------------
    # CONSTRAINTS
    # -------------------------------------------------------------------------

    @api.constrains('amount')
    def _check_amount_positive(self):
        """Amount must be strictly positive."""
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError(
                    _('Transaction amount must be greater than zero.')
                )

    # -------------------------------------------------------------------------
    # CRUD
    # -------------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        """Assign a unique sequence reference on creation."""
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('finance.transaction') or _('New')
        records = super().create(vals_list)
        # If created directly in 'confirmed' state (e.g. from transfer/exchange),
        # run the confirmation logic (balance check + journal entry).
        for rec in records:
            if rec.state == 'confirmed':
                rec._check_balance_before_confirm()
                rec._create_journal_entry()
        return records

    def write(self, vals):
        """
        Intercept state changes to create / cancel journal entries.
        """
        # Transition to 'confirmed'
        if vals.get('state') == 'confirmed':
            draft_records = self.filtered(lambda r: r.state == 'draft')
            result = super().write(vals)
            for rec in draft_records:
                rec._check_balance_before_confirm()
                rec._create_journal_entry()
            return result
        # Transition to 'cancelled'
        if vals.get('state') == 'cancelled':
            confirmed_records = self.filtered(lambda r: r.state == 'confirmed')
            result = super().write(vals)
            for rec in confirmed_records:
                rec._cancel_journal_entry()
            return result
        return super().write(vals)

    def unlink(self):
        """Delete linked journal entries when transactions are deleted."""
        moves_to_delete = self.env['account.move']
        for rec in self:
            if rec.move_id:
                moves_to_delete |= rec.move_id
        # First delete the transactions
        result = super().unlink()
        # Then clean up the journal entries
        for move in moves_to_delete:
            if move.state == 'posted':
                move.button_draft()
            if move.state in ('draft', 'cancel'):
                move.with_context(force_delete=True).unlink()
            elif move.state == 'draft':
                move.unlink()
        return result

    # -------------------------------------------------------------------------
    # PRIVATE: Balance Check
    # -------------------------------------------------------------------------

    def _check_balance_before_confirm(self):
        """Prevent confirmation if outgoing amount exceeds available balance."""
        for rec in self:
            if rec.type == 'out' and not rec.account_id.allow_negative:
                # Balance is computed live from journal items — always fresh
                current_balance = rec.account_id.balance
                if current_balance < rec.amount:
                    raise UserError(
                        _('Insufficient balance on account "%(account)s". '
                          'Current balance: %(balance)s, Transaction amount: %(amount)s.',
                          account=rec.account_id.name,
                          balance=current_balance,
                          amount=rec.amount,
                          )
                    )

    # -------------------------------------------------------------------------
    # PRIVATE: Journal Entry Creation
    # -------------------------------------------------------------------------

    def _create_journal_entry(self):
        """
        Create and post a journal entry (account.move) for this transaction.

        The two sides of the journal entry:
          - Account side:  finance.account → account_account_id (the CoA from the treasury account)
          - Category side: finance.category → account_account_id (the CoA from the category)

        For INCOME (type == 'in'):
            Debit:  Account's CoA   (asset increases)
            Credit: Category's CoA  (income recognized)

        For EXPENSE (type == 'out'):
            Debit:  Category's CoA  (expense recognized)
            Credit: Account's CoA   (asset decreases)
        """
        for rec in self:
            account = rec.account_id
            category = rec.category_id

            # Both the account and category must have CoA configured
            if not account.account_account_id:
                raise UserError(
                    _('Cannot create journal entry: account "%(account)s" '
                      'has no Chart of Account linked.',
                      account=account.name)
                )
            if not category or not category.account_account_id:
                raise UserError(
                    _('Cannot create journal entry: category "%(category)s" '
                      'has no Chart of Account linked.',
                      category=category.name if category else '')
                )

            account_coa = account.account_account_id
            category_coa = category.account_account_id
            company = rec.company_id
            company_currency = company.currency_id

            # Debit/credit in journal are always in company currency (e.g. UZS).
            # When transaction is in account currency (e.g. USD), convert for balance.
            if rec.currency_id == company_currency:
                balance = rec.amount
            else:
                balance = rec.currency_id._convert(
                    rec.amount, company_currency, company, rec.date
                )

            if rec.type == 'in':
                debit_account = account_coa
                credit_account = category_coa
            else:
                debit_account = category_coa
                credit_account = account_coa

            # Account-coa line uses transaction currency + amount_currency so balance shows in USD.
            # Category-coa line uses company currency.
            is_foreign = rec.currency_id != company_currency
            debit_line_vals = {
                'account_id': debit_account.id,
                'name': rec.description or rec.name,
                'debit': balance,
                'credit': 0.0,
                'currency_id': rec.currency_id.id if debit_account == account_coa else company_currency.id,
                'partner_id': rec.partner_id.id if rec.partner_id else False,
            }
            credit_line_vals = {
                'account_id': credit_account.id,
                'name': rec.description or rec.name,
                'debit': 0.0,
                'credit': balance,
                'currency_id': rec.currency_id.id if credit_account == account_coa else company_currency.id,
                'partner_id': rec.partner_id.id if rec.partner_id else False,
            }
            if is_foreign:
                if debit_account == account_coa:
                    debit_line_vals['amount_currency'] = rec.amount
                if credit_account == account_coa:
                    credit_line_vals['amount_currency'] = -rec.amount
            else:
                debit_line_vals['amount_currency'] = rec.amount
                credit_line_vals['amount_currency'] = -rec.amount

            move_vals = {
                'date': rec.date,
                'journal_id': account.journal_id.id,
                'ref': '%s — %s' % (rec.name, account.name),
                'move_type': 'entry',
                'currency_id': rec.currency_id.id,
                'line_ids': [
                    (0, 0, debit_line_vals),
                    (0, 0, credit_line_vals),
                ],
            }
            move = self.env['account.move'].sudo().create(move_vals)
            move.action_post()
            rec.move_id = move.id

    # -------------------------------------------------------------------------
    # PRIVATE: Journal Entry Cancellation
    # -------------------------------------------------------------------------

    def _cancel_journal_entry(self):
        """Cancel the linked journal entry when the transaction is cancelled."""
        for rec in self:
            if rec.move_id:
                move = rec.move_id
                if move.state == 'posted':
                    move.button_draft()
                if move.state == 'draft':
                    move.button_cancel()

    # -------------------------------------------------------------------------
    # ACTIONS
    # -------------------------------------------------------------------------

    def action_confirm(self):
        """Confirm the transaction — checks balance, creates journal entry."""
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only draft transactions can be confirmed.'))
            # Check negative balance before confirming
            if rec.type == 'out' and not rec.account_id.allow_negative:
                future_balance = rec.account_id.balance - rec.amount
                if future_balance < 0:
                    raise UserError(
                        _('Insufficient balance on account "%(account)s". '
                          'Current balance: %(balance)s, Transaction amount: %(amount)s.',
                          account=rec.account_id.name,
                          balance=rec.account_id.balance,
                          amount=rec.amount,
                          )
                    )
            rec.state = 'confirmed'

    def action_cancel(self):
        """Cancel the transaction — cancels the journal entry too."""
        for rec in self:
            if rec.state not in ('draft', 'confirmed'):
                raise UserError(_('Cannot cancel a transaction in this state.'))
            rec.state = 'cancelled'

    def action_reset_draft(self):
        """Reset a cancelled transaction back to draft."""
        for rec in self:
            if rec.state != 'cancelled':
                raise UserError(_('Only cancelled transactions can be reset to draft.'))
            rec.state = 'draft'

    def action_open_transfer(self):
        """Smart button: open the related transfer."""
        self.ensure_one()
        if self.transfer_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'finance.transfer',
                'res_id': self.transfer_id.id,
                'view_mode': 'form',
            }

    def action_open_exchange(self):
        """Smart button: open the related exchange."""
        self.ensure_one()
        if self.exchange_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'finance.exchange',
                'res_id': self.exchange_id.id,
                'view_mode': 'form',
            }

    def action_open_journal_entry(self):
        """Smart button: open the related journal entry."""
        self.ensure_one()
        if self.move_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'account.move',
                'res_id': self.move_id.id,
                'view_mode': 'form',
            }

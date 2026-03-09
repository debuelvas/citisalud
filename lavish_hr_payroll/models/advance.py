from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from odoo import api, fields, models, Command, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_round
import logging

_logger = logging.getLogger(__name__)

class ResCompany(models.Model):
    _inherit = 'res.company'
    
    advance_expiry_days = fields.Float('Advance Expiry Days', digits='Account')
    advance_payment_days = fields.Float('Advance Payment Days', digits='Account')

class ResPartner(models.Model):
    _inherit = 'res.partner'
    
    property_advance_account_receivable_id = fields.Many2one(
        'account.account',
        company_dependent=True,
        string="Advance Account Receivable"
    )
    property_advance_account_payable_id = fields.Many2one(
        'account.account', 
        company_dependent=True,
        string="Advance Account Payable"
    )

class HrPayslipAdvanceLine(models.Model):
    _name = 'hr.payslip.advance.line'
    _description = 'Payslip Advance Line'
    _rec_name = 'advance_id'

    advance_id = fields.Many2one('hr.employee.advance', required=True, ondelete='cascade')
    payslip_id = fields.Many2one('hr.payslip', required=True, ondelete='cascade')
    rule_id = fields.Many2one('hr.salary.rule', string='Salary Rule', required=True)
    amount_total = fields.Monetary('Total Amount', required=True, readonly=True)
    amount_discount = fields.Monetary('Discounted Amount', required=True)
    max_discount_amount = fields.Monetary('Max Discount Amount', compute='_compute_max_discount')
    base_amount = fields.Monetary('Base Amount')
    currency_id = fields.Many2one(related='advance_id.currency_id')
    state = fields.Selection(related='payslip_id.state', store=True)

    @api.depends('rule_id.max_discount_percentage', 'base_amount')
    def _compute_max_discount(self):
        for line in self:
            if line.rule_id.consider_base_amount:
                line.max_discount_amount = line.base_amount * (line.rule_id.max_discount_percentage / 100)
            else:
                line.max_discount_amount = line.amount_total

    @api.constrains('amount_discount', 'max_discount_amount', 'amount_total')
    def _check_amounts(self):
        for line in self:
            if line.amount_discount < 0 or line.amount_discount > line.amount_total:
                raise ValidationError(_('Discount amount must be between 0 and total amount'))
            if line.amount_discount > line.max_discount_amount:
                raise ValidationError(_('Discount exceeds maximum allowed amount'))

class HrEmployeeAdvance(models.Model):
    _name = 'hr.employee.advance'
    _description = 'Employee Advance'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name desc'

    name = fields.Char('Reference', readonly=True, copy=False, default='/')
    employee_id = fields.Many2one(
        'hr.employee', 
        required=True,
        tracking=True,
        states={'draft': [('readonly', False)]}
    )
    currency_id = fields.Many2one(
        'res.currency',
        required=True,
        tracking=True,
        default=lambda self: self.env.company.currency_id,
        states={'draft': [('readonly', False)]}
    )
    amount = fields.Monetary(
        required=True,
        tracking=True,
        states={'draft': [('readonly', False)]}
    )
    description = fields.Text(
        required=True,
        tracking=True,
        states={'draft': [('readonly', False)]}
    )
    request_date = fields.Date(
        required=True,
        default=fields.Date.context_today,
        tracking=True,
        states={'draft': [('readonly', False)]}
    )
    approve_date = fields.Date(
        tracking=True,
        states={'waiting_financial_approval': [('readonly', False)]}
    )
    start_date = fields.Date(
        required=True,
        tracking=True,
        states={'draft': [('readonly', False)]}
    )
    end_date = fields.Date(required=True, tracking=True)
    expire_date = fields.Date(compute='_compute_expire_date', store=True)
    pay_date = fields.Date(tracking=True, states={'validated': [('readonly', False)]})
    payment_state = fields.Selection([
        ('not_paid', 'Not Paid'),
        ('in_payment', 'In Payment'),
        ('paid', 'Paid')
    ], string='Payment Status', default='not_paid', tracking=True)
    
    state = fields.Selection([
        ('draft', 'Draft'),
        ('waiting_approval', 'Waiting Approval'),
        ('refused', 'Refused'),
        ('waiting_financial_approval', 'Waiting Financial Approval'),
        ('waiting_signature', 'Waiting Signature'),
        ('validated', 'Validated'),
        ('cancelled', 'Cancelled'),
        ('to_pay', 'To Pay'),
        ('paid', 'Paid'),
        ('expired', 'Expired'),
        ('to_discount', 'To Discount From Payroll'),
        ('to_refund', 'To Refund'),
        ('refunded', 'Refunded')
    ], default='draft', tracking=True, readonly=True, copy=False)
    
    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company
    )
    analytic_account_id = fields.Many2one(
        'account.analytic.account',
        required=True,
        states={
            'draft': [('readonly', False)],
            'waiting_approval': [('readonly', False)],
            'waiting_financial_approval': [('readonly', False)]
        }
    )
    journal_id = fields.Many2one(
        'account.journal',
        string='Payment Journal',
        states={'waiting_signature': [('readonly', False)]},
        domain=[('type', 'in', ['bank', 'cash'])]
    )
    move_id = fields.Many2one('account.move', readonly=True, copy=False)
    refund_move_id = fields.Many2one('account.move', string='Refund Entry', readonly=True, copy=False)
    payment_id = fields.Many2one('account.payment', readonly=True, copy=False)
    refund_payment_id = fields.Many2one('account.payment', string='Refund Payment', readonly=True, copy=False)
    expense_ids = fields.One2many('hr.expense', 'advance_id', string='Expense Claims')
    payslip_line_ids = fields.One2many('hr.payslip.advance.line', 'advance_id', string='Payslip Lines')
    remaining_amount = fields.Monetary(compute='_compute_remaining_amount', store=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('hr.employee.advance')
        return super().create(vals_list)

    @api.depends('end_date', 'company_id.advance_expiry_days')
    def _compute_expire_date(self):
        for advance in self:
            if advance.end_date:
                advance.expire_date = advance.end_date + timedelta(
                    days=advance.company_id.advance_expiry_days or 0.0
                )

    @api.depends('amount', 'expense_ids.total_amount', 'expense_ids.state', 
                'payslip_line_ids.amount_discount', 'payslip_line_ids.state')
    def _compute_remaining_amount(self):
        for advance in self:
            validated_expenses = advance.expense_ids.filtered(
                lambda x: x.state in ['approved', 'done']
            )
            validated_discounts = advance.payslip_line_ids.filtered(
                lambda x: x.state == 'done'
            )
            
            total_expenses = sum(validated_expenses.mapped('total_amount'))
            total_discounts = sum(validated_discounts.mapped('amount_discount'))
            
            advance.remaining_amount = advance.amount - total_expenses - total_discounts

    def action_submit(self):
        self.ensure_one()
        if not self.employee_id.parent_id:
            raise UserError(_("Employee must have a manager assigned"))
        self.write({'state': 'waiting_approval'})
        self.activity_schedule(
            'mail.mail_activity_data_todo',
            user_id=self.employee_id.parent_id.user_id.id,
            note=_('Please review and approve the advance request')
        )

    def action_approve(self):
        self.ensure_one()
        if self.env.user != self.employee_id.parent_id.user_id:
            raise UserError(_("Only the employee's manager can approve this advance"))
        self.write({
            'state': 'waiting_financial_approval',
            'approve_date': fields.Date.context_today(self)
        })

    def action_refuse(self):
        self.write({'state': 'refused'})

    def action_financial_approve(self):
        self.ensure_one()
        if not self.env.user.has_group('account.group_account_manager'):
            raise UserError(_("Only financial managers can approve this step"))
        self.write({'state': 'waiting_signature'})

    def action_validate(self):
        self.ensure_one()
        if not self.journal_id:
            raise UserError(_("Please select a payment journal"))
        move_vals = self._prepare_move_vals()
        move = self.env['account.move'].create(move_vals)
        move.action_post()
        self.write({
            'move_id': move.id,
            'state': 'validated'
        })

    def action_register_payment(self):
        self.ensure_one()
        if self.payment_id or self.state != 'validated':
            raise UserError(_("Payment already registered or advance not validated"))
            
        return {
            'name': _('Register Payment'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.payment.register',
            'view_mode': 'form',
            'context': {
                'active_model': 'hr.employee.advance',
                'active_ids': self.ids,
                'default_payment_type': 'outbound',
                'default_partner_type': 'supplier',
                'default_partner_id': self.employee_id.partner_id.id,
                'default_amount': self.amount,
            },
            'target': 'new'
        }

    def action_create_refund(self):
        self.ensure_one()
        if self.state != 'to_refund' or not self.remaining_amount:
            raise UserError(_("Cannot create refund"))
            
        move_vals = self._prepare_refund_move_vals()
        refund_move = self.env['account.move'].create(move_vals)
        refund_move.action_post()
        
        self.write({
            'refund_move_id': refund_move.id,
            'state': 'refunded'
        })

    def action_register_refund_payment(self):
        self.ensure_one()
        if not self.refund_move_id or self.refund_payment_id:
            raise UserError(_("Cannot register refund payment"))

        return {
            'name': _('Register Refund Payment'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.payment.register',
            'view_mode': 'form',
            'context': {
                'active_model': 'hr.employee.advance',
                'active_ids': self.ids,
                'default_payment_type': 'inbound',
                'default_partner_type': 'customer',
                'default_partner_id': self.employee_id.partner_id.id,
                'default_amount': self.remaining_amount,
            },
            'target': 'new'
        }

    def _prepare_move_vals(self):
        return {
            'journal_id': self.journal_id.id,
            'date': fields.Date.context_today(self),
            'ref': self.name,
            'line_ids': [
                (0, 0, {
                    'name': self.name,
                    'partner_id': self.employee_id.partner_id.id,
                    'account_id': self.employee_id.partner_id.property_advance_account_receivable_id.id,
                    'debit': self.amount,
                    'credit': 0.0,
                    'analytic_account_id': self.analytic_account_id.id,
                }),
                (0, 0, {
                    'name': self.name,
                    'partner_id': self.employee_id.partner_id.id,
                    'account_id': self.journal_id.default_account_id.id,
                    'debit': 0.0,
                    'credit': self.amount,
                })
            ]
        }

    def _prepare_refund_move_vals(self):
        return {
            'journal_id': self.journal_id.id,
            'date': fields.Date.context_today(self),
            'ref': f'{self.name}/REFUND',
            'line_ids': [
                (0, 0, {
                    'name': 'Advance Refund',
                    'partner_id': self.employee_id.partner_id.id,
                    'account_id': self.employee_id.partner_id.property_advance_account_payable_id.id,
                    'debit': self.remaining_amount,
                    'credit': 0.0,
                }),
                (0, 0, {
                    'name': 'Advance Refund',
                    'partner_id': self.employee_id.partner_id.id,
                    'account_id': self.employee_id.partner_id.property_advance_account_receivable_id.id,
                    'debit': 0.0,
                    'credit': self.remaining_amount,
                })
            ]
        }

    def _register_payment(self, payment_vals):
        payment = self.env['account.payment'].create(payment_vals)
        payment.action_post()
        self.write({
            'payment_id': payment.id,
            'payment_state': 'paid',
            'state': 'to_pay'
        })
        return payment

    def action_cancel(self):
        for advance in self:
            if advance.payment_id and advance.payment_id.state != 'draft':
                raise UserError(_("Cannot cancel advance with confirmed payment"))
            if advance.move_id:
                advance.move_id.button_draft()
                advance.move_id.unlink()
            if advance.refund_move_id:
                advance.refund_move_id.button_draft()
                advance.refund_move_id.unlink()
            if advance.payment_id:
                advance.payment_id.action_draft()
                advance.payment_id.unlink()
            if advance.refund_payment_id:
                advance.refund_payment_id.action_draft()
                advance.refund_payment_id.unlink()             
        self.write({'state': 'cancelled'})

    def action_to_discount(self):
        self.ensure_one()
        if self.state != 'to_pay' or not self.remaining_amount:
            raise UserError(_("Cannot move to discount state"))
        self.write({'state': 'to_discount'})

    def action_to_refund(self):
        self.ensure_one()
        if self.state != 'to_pay' or not self.remaining_amount:
            raise UserError(_("Cannot move to refund state"))
        self.write({'state': 'to_refund'})

class HrSalaryRule(models.Model):
    _inherit = 'hr.salary.rule'

    is_advance_rule = fields.Boolean('Is Advance Rule', default=False)
    advance_priority = fields.Integer('Advance Priority', default=10,
        help="Priority for processing advances. Lower number = higher priority")
    max_discount_percentage = fields.Float('Max Discount %', default=30.0)
    consider_base_amount = fields.Boolean('Consider Base Amount', default=True,
        help="If checked, max discount will be calculated as percentage of base salary")

    @api.constrains('is_advance_rule', 'max_discount_percentage')
    def _check_max_discount(self):
        for rule in self:
            if rule.is_advance_rule and not (0 <= rule.max_discount_percentage <= 100):
                raise ValidationError(_('Max discount percentage must be between 0 and 100'))

class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    advance_line_ids = fields.One2many(
        'hr.payslip.advance.line',
        'payslip_id',
        string='Advance Lines'
    )
    total_advance_discount = fields.Monetary(
        compute='_compute_total_advance_discount',
        string='Total Advance Discounts'
    )

    @api.depends('advance_line_ids.amount_discount')
    def _compute_total_advance_discount(self):
        for payslip in self:
            payslip.total_advance_discount = sum(
                payslip.advance_line_ids.mapped('amount_discount')
            )

    def _get_advances_to_discount(self):
        self.ensure_one()
        domain = [
            ('employee_id', '=', self.employee_id.id),
            ('state', '=', 'to_discount'),
            ('currency_id', '=', self.company_id.currency_id.id)
        ]
        return self.env['hr.employee.advance'].search(domain)

    def _get_base_amount(self):
        self.ensure_one()
        base_amount = self.contract_id.wage
        
        # Add additional earnings that should be considered for advance discount limit
        for line in self.line_ids.filtered(lambda l: l.category_id.code in ['BASIC', 'ALW']):
            base_amount += line.total
            
        return base_amount

    def compute_sheet(self):
        for payslip in self:
            # Clear existing advance lines
            payslip.advance_line_ids.unlink()
            
            # Get advances to process
            advances = payslip._get_advances_to_discount()
            if not advances:
                continue
                
            # Get base amount for calculations
            base_amount = payslip._get_base_amount()
            
            # Get advance rules ordered by priority
            advance_rules = self.env['hr.salary.rule'].search([
                ('is_advance_rule', '=', True)
            ], order='advance_priority')

            if not advance_rules:
                continue

            for advance in advances:
                remaining = advance.remaining_amount

                for rule in advance_rules:
                    if remaining <= 0:
                        break
                        
                    max_discount = base_amount * (rule.max_discount_percentage / 100) \
                        if rule.consider_base_amount else remaining
                    
                    amount_discount = min(remaining, max_discount)
                    
                    if amount_discount > 0:
                        self.env['hr.payslip.advance.line'].create({
                            'advance_id': advance.id,
                            'payslip_id': payslip.id,
                            'rule_id': rule.id,
                            'amount_total': remaining,
                            'amount_discount': amount_discount,
                            'base_amount': base_amount
                        })
                        remaining -= amount_discount

        return super().compute_sheet()

    def action_payslip_done(self):
        res = super().action_payslip_done()
        for payslip in self:
            advances_done = []
            for line in payslip.advance_line_ids:
                advance = line.advance_id
                if advance.id not in advances_done:
                    if advance.remaining_amount <= 0:
                        advance.write({'state': 'paid'})
                    advances_done.append(advance.id)
        return res

class HrExpense(models.Model):
    _inherit = 'hr.expense'

    advance_id = fields.Many2one(
        'hr.employee.advance',
        string='Advance',
        domain="[('employee_id', '=', employee_id),"
               "('state', 'in', ['to_pay']),"
               "('remaining_amount', '>', 0.0)]"
    )

    @api.constrains('advance_id', 'employee_id')
    def _check_advance_employee(self):
        for expense in self:
            if expense.advance_id and expense.employee_id != expense.advance_id.employee_id:
                raise ValidationError(_("Expense employee must match advance employee"))

    @api.constrains('advance_id', 'currency_id')
    def _check_advance_currency(self):
        for expense in self:
            if expense.advance_id and expense.currency_id != expense.advance_id.currency_id:
                raise ValidationError(_("Expense currency must match advance currency"))

    def action_submit_expenses(self):
        res = super().action_submit_expenses()
        for expense in self:
            if expense.advance_id and expense.advance_id.state == 'to_pay':
                if expense.total_amount > expense.advance_id.remaining_amount:
                    raise UserError(_('Expense amount exceeds advance remaining amount'))
        return res
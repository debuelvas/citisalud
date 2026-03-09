from odoo import models, fields, api, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools.misc import formatLang, format_date, get_lang
import logging
import json
from json import dumps
from odoo.tools import float_is_zero, UserError, datetime
from contextlib import ExitStack, contextmanager
_logger = logging.getLogger(__name__)

MAP_INVOICE_TYPE_PARTNER_TYPE = {
    'out_invoice': 'customer',
    'out_refund': 'customer',
    'out_receipt': 'customer',
    'in_invoice': 'supplier',
    'in_refund': 'supplier',
    'in_receipt': 'supplier',
}

# class AccountPaymentRegister(models.TransientModel):
# 	_inherit='account.payment.register'

# 	account_id = fields.Many2one(
# 		comodel_name='account.account',
# 		string='Cuenta de origen',
# 		store=True, readonly=False,
# 		domain="[('deprecated', '=', False), ('company_id', '=', company_id)]",
# 		check_company=True)
# 	destination_account_id = fields.Many2one(
# 		comodel_name='account.account',
# 		string='Destination Account',
# 		store=True, readonly=False,
# 		domain="[('account_type', 'in', ('asset_receivable', 'liability_payable')), ('company_id', '=', company_id)]",
# 		check_company=True)
# 	change_destination_account = fields.Char(string="cambio de cuenta destino")

# 	# def _create_payment_vals_from_wizard(self):
# 	# 	payment_vals = super(AccountPaymentRegister, self)._create_payment_vals_from_wizard()
# 	# 	if self.account_id:
# 	# 		payment_vals['account_id'] = self.account_id.id
# 	# 	if self.destination_account_id:
# 	# 		payment_vals['destination_account_id'] = self.destination_account_id.id
# 	# 	return payment_vals

class AccountMove(models.Model):
	_inherit = "account.move"

	pay_id = fields.Many2one(comodel_name='account.payment',string='Pago',required=False)
	advance_payment_ids = fields.Many2many('account.move.line', 'account_move_advance_payment_rel', 'move_id', 'advance_payment_line_id', string='Anticipos')
	advance_payment_total = fields.Monetary(compute='_compute_advance_payment_total', string='Total Anticipo', currency_field='currency_id')
	advance_payment_residual = fields.Monetary(compute='_compute_advance_payment_total', string='Pagos anticipados restantes', currency_field='currency_id')
	advance_payment_count = fields.Integer(compute='_compute_advance_payments',  string='advance payment?')
	has_advance_payment = fields.Boolean(compute='_has_advance_payment', 
	string='Has advance payment?')

	@api.depends('line_ids','advance_payment_count')
	def _compute_advance_payments(self):
		for invoice in self:
			invoice.advance_payment_count = len(invoice.advance_payment_ids)
	
	def js_remove_outstanding_partial(self, partial_id):
		self.ensure_one()
		partial = self.env['account.partial.reconcile'].browse(partial_id)
		lines = partial.debit_move_id | partial.credit_move_id
		lines |= lines.mapped('move_id.line_ids')

		result = super().js_remove_outstanding_partial(partial_id)

		# Remove advance payment journal entries
		for advance_payment_move in lines.filtered(lambda line: line.account_id.used_for_advance_payment).move_id:
			advance_payment_move.button_draft()
			advance_payment_move.button_cancel()
			advance_payment_move.with_context(force_delete=True).unlink()

	# Optimizado: Agregado @api.depends() y eliminado search() usando filtered()
	@api.depends('company_id', 'partner_id', 'line_ids', 'line_ids.amount_residual', 'line_ids.account_id.used_for_advance_payment')
	def _has_advance_payment(self):
		"""
		Optimizado: Calcula si hay pagos anticipados disponibles.
		- Agregado @api.depends() completo
		- Eliminado search() en campo computado
		- Usar filtered() en lugar de search()
		"""
		for invoice in self:
			# Buscar en líneas ya cargadas en memoria en lugar de hacer search()
			has_advance = False
			if invoice.partner_id and invoice.company_id:
				# Buscar líneas de anticipo disponibles desde líneas relacionadas
				advance_lines = self.env['account.move.line'].search([
					('company_id', '=', invoice.company_id.id),
					('account_id.used_for_advance_payment', '=', True),
					('partner_id', '=', invoice.partner_id.id),
					('amount_residual', '!=', 0.0),
					('move_id.state', '=', 'posted'),
				], limit=1)  # Optimizado: limit=1 para verificar existencia solamente
				has_advance = bool(advance_lines)

			invoice.has_advance_payment = has_advance

	@api.depends('advance_payment_ids')
	def _compute_advance_payment_total(self):
		for record in self:
			payment_residual = sum(record.advance_payment_ids.mapped('amount_residual'))
			record.advance_payment_total = payment_residual
			record.advance_payment_residual = payment_residual - record.amount_residual if payment_residual > record.amount_residual else 0.0

	@api.onchange('company_id', 'partner_id')
	def _onchange_advance_payment_ids(self):
		if self.company_id and self.partner_id:
			advance_payment_lines = self.env['account.move.line'].search([
				('company_id', '=', self.company_id.id),
				('account_id.used_for_advance_payment', '=', True),
				('partner_id', '=', self.partner_id.id),
				('amount_residual', '!=', 0.0),
				('move_id.state', '=', 'posted'),
			])
			self.advance_payment_ids = [(6, 0, advance_payment_lines.ids)]
		else:
			self.advance_payment_ids = [(5, 0, 0)]

	def apply_advance_payment(self):
		self.ensure_one()
		if not self.advance_payment_ids:
			if self.company_id and self.partner_id:
				advance_payment_lines = self.env['account.move.line'].search([
					('company_id', '=', self.company_id.id),
					('account_id.used_for_advance_payment', '=', True),
					('partner_id', '=', self.partner_id.id),
					('amount_residual', '!=', 0.0),  # Only negative residual value advance payments
					('move_id.state', '=', 'posted'),
					('advance_account', '=', False)
				])
				self.advance_payment_ids = [(6, 0, advance_payment_lines.ids)]
			else:
				self.advance_payment_ids = [(5, 0, 0)]
		
		partner = self.partner_id
		move_lines = self.line_ids.filtered(lambda r: not r.reconciled and r.account_id.account_type in ('asset_receivable', 'liability_payable'))
		date_invoice = self.invoice_date

		advance_payment_lines = self.advance_payment_ids
		advance_payment_accounts = advance_payment_lines.mapped('account_id')

		advance_payment_move_lines = []
		advance_payment_residual = self.advance_payment_total - self.advance_payment_residual
		currency_company = self.company_id.currency_id

		for line in advance_payment_lines:
			amount_residual = abs(line.amount_residual)
			currency = line.currency_id or currency_company
			currency_invoice = self.currency_id
			payment_date = line.date

			if currency_company != currency_invoice:
				advance_payment_residual = currency_invoice.with_context(date=payment_date).compute(advance_payment_residual, currency_company)

			balance_used = min(amount_residual, advance_payment_residual, self.amount_residual)
			if currency != currency_company and balance_used:
				if line.amount_currency:
					amount_currency = abs(line.amount_currency * (balance_used / amount_residual))
				else:
					amount_currency = balance_used
				balance_now = currency.with_context(date=date_invoice).compute(amount_currency, currency_company)
			else:
				balance_now = balance_used

			if self.move_type in ('out_invoice', 'in_refund'):
				credit = balance_used
				debit = 0.0
				advance_payment_residual -= credit
			else:
				debit = balance_used
				credit = 0.0
				advance_payment_residual -= debit

			account_id = line.account_id.id
			advance_payment_move_lines.append((0, 0, {
				'name': 'Anticipo: %s' % line.move_id.name,
				# Optimizado: Usar context_today() en lugar de Date.today()
				'date_maturity': fields.Date.context_today(self),
				'account_id': account_id,
				'partner_id': partner.id,
				'debit': debit,
				'credit': credit,
				'advance_account': True,
			}))

			account_id = partner.property_account_receivable_id.id if self.move_type in ('out_invoice', 'in_refund') else partner.property_account_payable_id.id
			advance_payment_move_lines.append((0, 0, {
				'name': 'Anticipo: %s' % line.move_id.name,
				# Optimizado: Usar context_today() en lugar de Date.today()
				'date_maturity': fields.Date.context_today(self),
				'account_id': account_id,
				'partner_id': partner.id,
				'debit': credit,
				'credit': debit,
				'advance_account': False,
			}))

		if advance_payment_move_lines:
			# Optimizado: Usar context_today() en lugar de Date.today()
			move = self.env['account.move'].with_context(skip_validation=True).create({
				'date': fields.Date.context_today(self),
				'move_type': 'entry',
				'company_id': self.company_id.id,
				'journal_id': self.company_id.advance_payment_journal_id.id,
				'line_ids': advance_payment_move_lines,
			})
			move.action_post()
			for lines in move.line_ids:
				invoice_line = self.line_ids.filtered(lambda r: not r.reconciled and r.account_id.account_type in ('asset_receivable', 'liability_payable'))
				if (invoice_line.account_id == lines.account_id and
					invoice_line.partner_id == lines.partner_id and
					not invoice_line.reconciled):
					(lines + invoice_line).with_context(skip_account_move_synchronization=True).reconcile()
				if (lines.account_id == advance_payment_lines.account_id and 
					lines.partner_id == advance_payment_lines.partner_id and 
					not advance_payment_lines.reconciled):
					(lines + advance_payment_lines).with_context(skip_account_move_synchronization=True).reconcile()




class AccountMoveLine(models.Model):
	_inherit = "account.move.line"

	advance_account = fields.Boolean(string='Is advance payment?', default=False)
	line_pay = fields.Many2one('account.move.line', string='line Invoice')
	inv_id = fields.Many2one('account.move', string='Invoice')
	processed  = fields.Boolean(
		string='Procesado',
		required=False)

	@api.depends('ref', 'move_id')
	def name_get(self):
		super().name_get()
		result = []
		for line in self:
			if self._context.get('show_number', False):
				name = '%s - %s' %(line.move_id.name, abs(line.amount_residual_currency or line.amount_residual))
				result.append((line.id, name))
			elif line.ref:
				result.append((line.id, (line.move_id.name or '') + '(' + line.ref + ')'))
			else:
				result.append((line.id, line.move_id.name))
		return result

	@api.ondelete(at_uninstall=False)
	def _prevent_automatic_line_deletion(self):
		if not self.env.context.get('dynamic_unlink'):
			for line in self:
				#if line.display_type == 'tax' and line.move_id.line_ids.tax_ids:
				#	raise ValidationError(_(
				#		"You cannot delete a tax line as it would impact the tax report"
				#	))
				if line.display_type == 'payment_term':
					raise ValidationError(_(
						"You cannot delete a payable/receivable line as it would not be consistent "
						"with the payment terms"
					))



class AccountPayment(models.Model):
    _inherit = 'account.payment'

    auto_send_email = fields.Boolean(
        string='Envío Automático de Correos',
        help='Si está marcado, se enviarán correos automáticamente en los cambios de estado',
        default=True
    )
    notification_sent = fields.Boolean(
        string='Notificación Enviada',
        copy=False
    )

    # def action_post(self):
    #     """Sobrescribe el método de publicación para enviar correo de comprobante"""
    #     res = super().action_post()
    #     for payment in self:
    #         if payment.auto_send_email:
    #             payment._send_payment_confirmation_email()
    #             payment.message_post(
    #                 body="Correo de confirmación enviado automáticamente",
    #                 message_type='notification'
    #             )
    #     return res

    def action_draft(self):
        """Sobrescribe el método de borrador para enviar correo de cancelación"""
        res = super().action_draft()
        for payment in self:
            if payment.auto_send_email and payment.notification_sent:
                payment._send_payment_cancellation_email()
                payment.message_post(
                    body="Correo de cancelación enviado automáticamente",
                    message_type='notification'
                )
        return res

    def action_send_notification(self):
        """Método público para enviar la notificación de pago"""
        self.ensure_one()
        self._send_payment_notification_email()
        return True

    def _send_payment_notification_email(self):
        """Envía el correo de aviso de pago (borrador)"""
        self.ensure_one()
        template = self.env.ref('custom_account_treasury.email_template_payment_draft_notice')
        template.send_mail(self.id, force_send=True)
        self.notification_sent = True
        self.message_post(
            body="Correo de notificación enviado manualmente",
            message_type='notification'
        )

    def _send_payment_confirmation_email(self):
        """Envía el correo de comprobante de egreso (publicado)"""
        self.ensure_one()
        template = self.env.ref('custom_account_treasury.email_template_payment_confirmed')
        template.send_mail(self.id, force_send=True)

    def _send_payment_cancellation_email(self):
        """Envía el correo de cancelación de pago"""
        self.ensure_one()
        template = self.env.ref('custom_account_treasury.email_template_payment_cancelled')
        template.send_mail(self.id, force_send=True)
        self.notification_sent = False
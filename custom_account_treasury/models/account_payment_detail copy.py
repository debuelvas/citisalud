from odoo import fields, models, api, _
import logging
_logger = logging.getLogger(__name__)
from odoo.tools import float_is_zero, float_compare,float_round
from datetime import datetime, timedelta
MAP_INVOICE_TYPE_PAYMENT_SIGN = {
	'out_invoice': 1,
	'in_refund': 1,
	'in_invoice': -1,
	'out_refund': -1,
	'entry': 1,
}

class AccountPaymentDetail(models.Model):
	_name = "account.payment.detail"
	_description = "Detalle de transferencia, pago y/o cobro"
	_inherit = "analytic.mixin"

	# -------------------------------------------------------------------------
	# Utility methods
	# -------------------------------------------------------------------------

	def _convert_amount(self, amount, from_currency, to_currency, date, company=None, round=True):
		"""
		Centralized method to perform currency conversion, making it easier to 
		change the logic if needed in the future.

		:param amount: float - The amount to convert
		:param from_currency: record of res.currency
		:param to_currency: record of res.currency
		:param date: date object - The rate date
		:param company: record of res.company or None
		:param round: bool - Whether to round the conversion result
		:return: float - Converted amount
		"""
		if not company:
			company = self.company_id or self.env.company

		if from_currency == to_currency or float_is_zero(amount, precision_rounding=from_currency.rounding):
			return amount
		return from_currency._convert(amount, to_currency, company, date, round=round)

	@api.depends('move_line_id.amount_residual', 'move_line_id.amount_residual_currency', 
				'move_line_id.currency_id', 'date', 'payment_currency_id')
	def _compute_amount_residual(self):
		"""
		Calcula los montos residuales en moneda de compañía y extranjera,
		considerando la fecha del documento para la conversión.
		"""
		for record in self:
			if not record.move_line_id:
				record.amount_residual = 0.0
				record.amount_residual_currency = 0.0
				continue

			move_line = record.move_line_id
			move = move_line.move_id
			
			document_date = move.date or move.invoice_date or fields.Date.context_today(record)
			record.amount_residual = move_line.amount_residual
			if move_line.currency_id and move_line.currency_id != record.company_currency_id:
				if move_line.amount_residual_currency:
					record.amount_residual_currency = move_line.amount_residual_currency
				else:
					record.amount_residual_currency = record.company_currency_id._convert(
						move_line.amount_residual,
						move_line.currency_id,
						record.company_id,
						document_date,
						round=True
					)
			else:
				record.amount_residual_currency = move_line.amount_residual

	@api.depends('move_line_id', 'move_line_id.currency_id', 'payment_id.currency_id')
	def _compute_payment_currency(self):
		"""
		Computa la moneda de pago basándose en:
		1. Moneda del pago principal
		2. Moneda de la compañía como fallback
		"""
		for record in self:
			if record.payment_id and record.payment_id.currency_id:
				record.payment_currency_id = record.payment_id.currency_id
			else:
				record.payment_currency_id = record.company_id.currency_id or self.env.company.currency_id

	@api.depends('payment_amount', 'payment_currency_id', 'invoice_id', 'move_line_id',
				'payment_id.payment_type', 'payment_id.date', 'payment_id.currency_id')
	def _compute_debit_credit_balance(self):
		for val in self:
			balance = val.payment_amount
			company = val.company_id or val.env.company
			if val.payment_id.currency_id and val.payment_id.currency_id != company.currency_id:
				currency = val.payment_id.currency_id
				balance = currency._convert(balance, val.company_currency_id, company, 
											val.payment_id.date or fields.Date.today())
			if val.move_line_id:
				balance *= -1
			val.debit = abs(balance) if balance < 0.0 else 0.0
			val.credit = abs(balance) if balance > 0.0 else 0.0
			val.balance = balance



	@api.depends('balance')
	def _compute_type(self):
		for val in self:
			val.type = val.balance > 0 and 'Ingreso' or "Egreso"
	
	name = fields.Char('Etiqueta')
	sequence = fields.Integer(compute='_compute_sequence', store=True, readonly=False, precompute=True)
	payment_id = fields.Many2one('account.payment', string="Pago y/o Cobro", index=True, auto_join=True, ondelete="cascade")
	state = fields.Selection(related='payment_id.state', store=True)
	display_type = fields.Selection(
		selection=[
			('asset_cash', 'Banco o Caja'),
			('bill', 'Factura de Compra'),
			('invoice', 'Factura de Venta'),
			('entry', 'Apunte Manual'),
			('reverse', 'Notas Creditos'),
			('tax', 'Impuestos'),
			('rounding', "Rounding"),
			('counterpart', 'Contra partida'),
			('diff', 'Contra partida Diferencia en cambio'),
			('diff_curr', 'Contra partida Diferencia en cambio'),
			('advance', 'Anticipo'),
			('line_section', 'Section'),
			('line_note', 'Note'),
			('epd', 'Early Payment Discount')
		],
		compute='_compute_display_type', store=True, readonly=False, precompute=True,
		required=True,
	)
	other_payment_id = fields.Many2one('account.payment', string="Pagos")
	move_line_id = fields.Many2one('account.move.line', string="Documentos, pagos/cobros", copy=False)
	partner_type = fields.Selection(related="payment_id.partner_type") 
	account_id = fields.Many2one('account.account', string="Cuenta", required=True)
	invoice_id = fields.Many2one('account.move', string="Factura")
	partner_id = fields.Many2one('res.partner', string="Empresa")
	currency_id = fields.Many2one('res.currency', string="Moneda")
	company_currency_id = fields.Many2one('res.currency', string="Moneda de la compañia",
		required=True, default=lambda self: self.env.company.currency_id)
	move_id = fields.Many2one('account.move', string="Comprobante diario")
	ref = fields.Char(string="Referencia")
	number = fields.Char('Número')
	type = fields.Char(compute="_compute_type", store=True, readonly=True, string="Type")
	debit = fields.Monetary('Debit', compute='_compute_debit_credit_balance', inverse='_inverse_debit', precompute=True, store=True, readonly=True, currency_field='company_currency_id')
	credit = fields.Monetary('Credit', compute='_compute_debit_credit_balance', inverse='_inverse_credit', precompute=True, store=True, readonly=True, currency_field='company_currency_id')
	balance = fields.Monetary(compute='_compute_debit_credit_balance', store=True, readonly=False, currency_field='company_currency_id', precompute=True, help="Technical field holding the debit - credit in order to open meaningful graph views from reports")
	amount_currency = fields.Monetary(string="Moneda de importes")
	journal_id = fields.Many2one('account.journal', related="payment_id.journal_id", string="Diario", store=True)
	company_id = fields.Many2one('res.company', related="journal_id.company_id", store=True)
	date = fields.Date(related="payment_id.date")
	is_main = fields.Boolean(string="Is Principal", default=False)
	is_account_line = fields.Boolean(string="Cuenta origen", default=False)
	is_transfer = fields.Boolean(string="Es transferencia", default=False)
	is_diff = fields.Boolean(string="Es Diferencia", default=False)
	is_counterpart = fields.Boolean(string="Es Contrapartida", default=False)
	is_manual_currency = fields.Boolean(string="Moneda manual", default=False)
	amount_residual = fields.Monetary(string="Deuda MN", compute="_compute_amount_residual", store=True, currency_field='company_currency_id',
		help="The residual amount on a journal item expressed in the company currency.")
	amount_residual_currency = fields.Monetary(string="Deuda ME", compute="_compute_amount_residual", store=True, currency_field='currency_id',
		help="The residual amount on a journal item expressed in its currency (possibly not the company currency).")
	date_maturity = fields.Date(related="move_line_id.date_maturity", store=True, string="Fecha vencimiento")
	payment_currency_id = fields.Many2one(
		'res.currency', 
		string="Moneda de pago",
		compute='_compute_payment_currency',
		store=True,
		help="Moneda en la que se realizará el pago. Se determina automáticamente basado en la moneda del pago principal, "
			"o la moneda de la compañía."
	)
	payment_amount = fields.Monetary('Monto de pago', currency_field="payment_currency_id")
	exclude_from_payment_detail = fields.Boolean(help="Campo tecnico utilizado para excluir algunas lineas de la \
		pestaña detalle de payment_lines en la vista formulario")
	to_pay = fields.Boolean('A pagar', default=False)
	product_id = fields.Many2one('product.product', string='Product')
	tax_ids = fields.Many2many('account.tax', string='Taxes', help="Taxes that apply on the base amount", index=True,  store=True, check_company=True)
	tax_tag_ids = fields.Many2many(string="Tags", comodel_name='account.account.tag', ondelete='restrict',
		help="Tags assigned to this line by the tax creating it, if any. It determines its impact on financial reports.")
	tax_repartition_line_id = fields.Many2one('account.tax.repartition.line',
		string="Originator Tax Distribution Line", ondelete='restrict', 
		check_company=True,
		help="Tax distribution line that caused the creation of this move line, if any") 
  
	auto_tax_line = fields.Boolean()
	tax_line_id = fields.Many2one('account.payment.detail', ondelete = 'cascade')
	tax_line_id2 = fields.Many2one('account.tax', ondelete = 'cascade')
	tax_base_amount = fields.Monetary(string="Base Amount", currency_field='company_currency_id')

	# TASA DE CAMBIO
	currency_rate = fields.Float(
		'Tasa de Cambio',
		digits=(16, 6),
		compute='_compute_currency_rate',
		readonly=False,
		store=True,
		help="Tasa de cambio usada en la conversión"
	)

	needs_rate_update = fields.Boolean(
		compute='_compute_needs_rate_update',
		help="Indica si la tasa necesita actualización (>3 días)"
	)
	exchange_diff_amount = fields.Monetary(
		string='Diferencia de Cambio',
		compute='_compute_exchange_diff',
		store=True,
		currency_field='company_currency_id',
		help="Diferencia de cambio generada por el monto pagado"
	)

	@api.depends('move_line_id', 'payment_amount', 'payment_currency_id', 'date')
	def _compute_exchange_diff(self):
		"""
		Calcula la diferencia de cambio basada en el monto que se está pagando
		"""
		for record in self:
			record.exchange_diff_amount = 0.0
			if not record.move_line_id or not record.payment_amount:
				continue

			# Obtener fechas relevantes
			original_date = record.move_line_id.move_id.date or record.move_line_id.date
			payment_date = record.date or fields.Date.today()

			# Solo calcular si las fechas son diferentes
			if original_date == payment_date:
				continue

			record.exchange_diff_amount = record._calculate_exchange_difference_payment(
				original_date,
				payment_date
			)

	def _calculate_exchange_difference_payment(self, original_date, payment_date):
		"""
		Calcula la diferencia de cambio basada en el monto de pago actual
		
		Args:
			original_date: Fecha del documento original
			payment_date: Fecha del pago
		Returns:
			float: Monto de diferencia de cambio en moneda de la compañía
		"""
		self.ensure_one()

		# Si no hay moneda extranjera, no hay diferencia
		if (self.payment_currency_id == self.company_currency_id and 
			(not self.move_line_id.currency_id or 
				self.move_line_id.currency_id == self.company_currency_id)):
			return 0.0

		# Obtener el monto que se está pagando
		payment_amount = self.payment_amount
		
		if self.move_line_id.currency_id and self.move_line_id.currency_id != self.company_currency_id:
			# Caso: Documento en moneda extranjera
			doc_currency = self.move_line_id.currency_id
			
			# Si el pago está en la misma moneda del documento
			if self.payment_currency_id == doc_currency:
				# Convertir el monto del pago a moneda de la compañía en fecha original
				amount_original = doc_currency._convert(
					payment_amount,
					self.company_currency_id,
					self.company_id,
					original_date
				)
				
				# Convertir el monto del pago a moneda de la compañía en fecha de pago
				amount_payment = doc_currency._convert(
					payment_amount,
					self.company_currency_id,
					self.company_id,
					payment_date
				)
			else:
				# Si el pago está en una moneda diferente al documento
				# Primero convertir a la moneda del documento
				amount_doc_curr = self.payment_currency_id._convert(
					payment_amount,
					doc_currency,
					self.company_id,
					payment_date
				)
				
				# Luego calcular en ambas fechas
				amount_original = doc_currency._convert(
					amount_doc_curr,
					self.company_currency_id,
					self.company_id,
					original_date
				)
				
				amount_payment = doc_currency._convert(
					amount_doc_curr,
					self.company_currency_id,
					self.company_id,
					payment_date
				)
		else:
			# Caso: Documento en moneda local pero pago en moneda extranjera
			amount_original = self.payment_currency_id._convert(
				payment_amount,
				self.company_currency_id,
				self.company_id,
				original_date
			)
			
			amount_payment = self.payment_currency_id._convert(
				payment_amount,
				self.company_currency_id,
				self.company_id,
				payment_date
			)

		# Calcular la diferencia
		exchange_diff = amount_payment - amount_original
		
		# Ajustar el signo según el tipo de documento
		if self.move_line_id.move_id.move_type in ['out_invoice', 'in_refund']:
			exchange_diff *= -1

		return exchange_diff

	def _get_payment_info(self):
		"""
		Obtiene información detallada del pago incluyendo diferencia de cambio
		Returns:
			dict: Información del pago y sus montos
		"""
		self.ensure_one()
		
		info = {
			'payment_currency': self.payment_currency_id.name,
			'payment_amount': self.payment_amount,
			'company_currency': self.company_currency_id.name,
			'exchange_diff': self.exchange_diff_amount,
			'original_rate': 0.0,
			'payment_rate': 0.0,
		}
		
		if self.payment_currency_id != self.company_currency_id:
			# Calcular tasas de cambio
			info.update({
				'original_rate': abs(self.company_currency_id.rate / self.payment_currency_id.rate),
				'payment_rate': abs(self.company_currency_id.rate / self.payment_currency_id.with_context(date=self.date).rate)
			})
			
		return info

	@api.depends('display_type')
	def _compute_sequence(self):
		seq_map = {
			'tax': 10000,
			'rounding': 11000,
			'payment_term': 12000,
		}
		for line in self:
			line.sequence = seq_map.get(line.display_type, 100)
	@api.depends('payment_id')
	def _compute_display_type(self):
		for line in self.filtered(lambda l: not l.display_type):
			line.display_type = (
				'tax' if line.tax_line_id else
				'invoice' if line.move_line_id.move_id.move_type in ("out_invoice","out_receipt") else 
				'bill' if line.move_line_id.move_id.move_type in ("in_invoice","in_receipt") else 
				'reverse' if line.move_line_id.move_id.move_type in ("in_refund","out_refund") else 
				'entry' if line.move_line_id.move_id.move_type == 'entry' else 
				'advance' if not line.move_line_id and line.account_id.used_for_advance_payment  else
				'product' if line.product_id  else
				'counterpart'
			)


	@api.onchange('debit')
	def _inverse_debit(self):
		for line in self:
			if line.debit:
				line.credit = 0
			line.balance = line.debit - line.credit
			payment_amount =0
			if line.payment_currency_id != line.company_currency_id:
				payment_amount = line.company_currency_id._convert(
					line.debit - line.credit,
					line.payment_currency_id,
					line.company_id,
					line.date or fields.Date.today()
				)
			else:
				payment_amount = line.debit - line.credit
				
			line.payment_amount = payment_amount
			line.amount_currency = payment_amount

	@api.onchange('credit')
	def _inverse_credit(self):
		for line in self:
			if line.credit:
				line.debit = 0
			line.balance = line.debit - line.credit
			payment_amount =0
			if line.payment_currency_id != line.company_currency_id:
				payment_amount = line.company_currency_id._convert(
					line.debit - line.credit,
					line.payment_currency_id,
					line.company_id,
					line.date or fields.Date.today()
				)
			else:
				payment_amount = line.debit - line.credit
				
			line.amount_currency = payment_amount
			line.payment_amount = payment_amount		

	@api.depends('move_line_id', 'invoice_id', 'payment_amount', 'payment_id.date', 'payment_currency_id')
	def _compute_payment_difference(self):
		"""Calcula la diferencia entre el monto a pagar y el residual."""
		for record in self:
			if not record.move_line_id:
				record.payment_difference = 0.0
				continue

			if record.payment_currency_id != record.company_currency_id:
				residual_payment_currency = record.company_currency_id._convert(
					record.amount_residual,
					record.payment_currency_id,
					record.company_id,
					record.date or fields.Date.context_today(record)
				)
			else:
				residual_payment_currency = record.amount_residual

			record.payment_difference = residual_payment_currency - record.payment_amount

	payment_difference = fields.Monetary(compute='_compute_payment_difference', string='Payment Difference', readonly=True, store=True)
	payment_difference_handling = fields.Selection([('open', 'Mantener abierto'), ('reconcile', 'Marcar la factura como totalmente pagada')], default='open', string="Payment Difference Handling", copy=False)
	writeoff_account_id = fields.Many2one('account.account', string="Difference Account", domain=[('deprecated', '=', False)], copy=False)
	amount_info = fields.Json(
		string='Amount Information',
		compute='_compute_amount_info'
	)

	@api.depends('move_line_id', 'payment_amount', 'currency_id', 'payment_currency_id')
	def _compute_amount_info(self):
		for record in self:
			if not record.move_line_id:
				record.amount_info = False
				continue

			record.amount_info = record._get_payment_info()
	def _compute_payment_amount_currency(self):
		for val in self:
			document_currency = val.move_line_id.currency_id if val.move_line_id else val.currency_id
			company_currency = val.company_currency_id

			if val.move_line_id:
				amount = val.move_line_id.amount_residual
				amount_currency = val.move_line_id.amount_residual_currency

				if document_currency != company_currency and not float_is_zero(amount_currency, precision_rounding=document_currency.rounding):
					amount = document_currency._convert(
						amount_currency,
						company_currency,
						val.company_id,
						val.date or fields.date.today()
					)
			else:
				amount = val.payment_amount
				amount_currency = 0.0

			return amount, amount_currency




	@api.onchange('payment_amount', 'payment_currency_id', 'payment_id.payment_type', 'date')
	def _onchange_payment_amount(self):
		for val in self:
			currency = False
			amount_currency = 0.0
			
			if val.currency_id != val.company_currency_id:
				if val.move_line_id:
					sign = -1 
				else:
					sign = -1 if val.credit > 0 else 1
				
				if val.payment_currency_id == val.currency_id:
					amount_currency = val.payment_amount * sign
				else:
					amount_currency = val.payment_currency_id._convert(
						val.payment_amount,
						val.currency_id,
						val.company_id,
						val.date or fields.Date.today()
					) * sign
				currency = val.currency_id

			val.amount_currency = val.payment_amount
			#val.currency_id = currency
			return {'values': {
				'currency_id': currency and currency.id or False,
				'amount_currency': amount_currency
			}}

	def _compute_payment_amount(self, invoices=None, currency: 'res.currency' = None) -> float:
		self.ensure_one()
		payment_currency = (currency or 
							self.payment_currency_id or 
							self.journal_id.currency_id or 
							self.company_currency_id)
		if not self.move_line_id:
			return self.payment_amount
		sign = -1
		amount_company_currency = self.amount_residual * sign
		if (self.move_line_id.currency_id == self.company_currency_id and 
			payment_currency != self.company_currency_id):
			return self.company_currency_id._convert(
				amount_company_currency,
				payment_currency,
				self.company_id,
				self.date or fields.Date.today()
			)
		
		if self.move_line_id.currency_id != self.company_currency_id:
			if self.move_line_id.amount_residual_currency:
				amount_foreign_currency = self.move_line_id.amount_residual_currency * sign
				
				if payment_currency != self.move_line_id.currency_id:
					return self.move_line_id.currency_id._convert(
						amount_foreign_currency,
						payment_currency,
						self.company_id,
						self.date or fields.Date.today()
					)
				return amount_foreign_currency
			
		if payment_currency == self.company_currency_id:
			return amount_company_currency

		return self.company_currency_id._convert(
			amount_company_currency,
			payment_currency,
			self.company_id,
			self.date or fields.Date.today()
		)

	@api.onchange('to_pay', 'payment_id.payment_type', 'payment_amount')
	def _onchange_to_pay(self):
		for record in self:
			if not record.payment_id.payment_type == 'transfer' and record.to_pay:
				payment_amount = record._compute_payment_amount(
					currency=record.payment_currency_id
				)
				
				record.payment_amount = float_round(
					payment_amount,
					precision_rounding=record.payment_currency_id.rounding
				)
				record.currency_id = record.payment_currency_id.id

	@api.onchange('move_line_id')
	def _onchange_move_lines(self) -> None:
		"""
		Handle changes in move_line_id field and update related fields accordingly.
		This method is triggered when the journal item is changed.
		"""
		for record in self:
			if not record.move_line_id:
				continue

			move_line = record.move_line_id
			move = move_line.move_id
			record.update({
				'invoice_id': move.id if move else False,
				'name': move_line.name,
				'ref': move_line.ref or False,
				'account_id': move_line.account_id.id,
				'partner_id': move_line.partner_id.id,
				'number': move.name if move else False,
				'company_currency_id': move_line.company_currency_id.id,
				'other_payment_id': move_line.payment_id.id,
				'currency_id': move_line.currency_id.id,
			})
			move_type = move.move_type if move else False
			display_type_mapping: Dict[str, str] = {
				'out_invoice': 'invoice',
				'out_receipt': 'invoice',
				'in_invoice': 'bill',
				'in_receipt': 'bill',
				'in_refund': 'reverse',
				'out_refund': 'reverse',
				'entry': 'entry'
			}
			record.display_type = display_type_mapping.get(move_type, 'entry')
			self._update_payment_amount(record)

	def _update_payment_amount(self, record) -> None:
		"""
		Update payment amount related fields.
		
		Args:
			record: The payment record to update
		"""
		vals = record._onchange_payment_amount()
		if vals and isinstance(vals, dict):
			values = vals.get('values', {})
			if values.get('amount_currency'):
				record.amount_currency = values['amount_currency']


	def _onchange_read_line_pay(self):
		for line in self:
			line._onchange_to_pay()
			line._onchange_payment_amount()

	def _get_counterpart_move_line_vals(self):
		"""
		Prepara los valores para crear la línea de contrapartida del asiento contable.
		Returns:
			dict: Valores para crear la línea de contrapartida
		"""
		self.ensure_one()
		
		move_line_name = (
			f"Pago Documento: {self.invoice_id.name}" 
			if self.invoice_id 
			else self.name or ''
		)
		
		currency = (
			self.currency_id 
			if self.currency_id != self.company_currency_id 
			else self.payment_currency_id
		)
		
		vals = {
			'name': move_line_name,
			'ref': self.payment_id.ref or '',
			'account_id': self.account_id.id,
			'partner_id': self.partner_id.id if self.partner_id else False,
			'date': self.date,
			'currency_id': currency.id,
			'company_id': self.company_id.id,
			'company_currency_id': self.company_currency_id.id,
		}
		if any([self.tax_ids, self.tax_tag_ids, self.tax_base_amount]):
			vals.update({
				'tax_ids': [(6, 0, self.tax_ids.ids)],
				'tax_tag_ids': [(6, 0, self.tax_tag_ids.ids)],
				'tax_base_amount': self.tax_base_amount,
				'tax_line_id': self.tax_line_id2.id if self.tax_line_id2 else False,
				'tax_repartition_line_id': self.tax_repartition_line_id.id if self.tax_repartition_line_id else False,
			})
		
		if self.analytic_distribution:
			vals['analytic_distribution'] = self.analytic_distribution
		
		if self.currency_id and self.currency_id != self.company_currency_id:
			sign = 1 if self.debit > 0.0 else -1
			vals['amount_currency'] = abs(self.amount_currency) * sign
		
		return vals
	def _get_counterpart_move_name(self):
		move_type = self.move_line_id.move_id.move_type
		invoice_name = self.invoice_id.name
		move_ref = self.move_line_id.move_id.ref or ''

		name_mapping = {
			("out_invoice", "out_receipt"): f"Pago de Factura: {invoice_name}",
			("in_invoice", "in_receipt"): f"Pago Factura de compra: {invoice_name} - {move_ref}",
			("in_refund", "out_refund"): f"Cruce de Nota Credito: {invoice_name} - {move_ref}",
			"entry": f"Pago Documento: {invoice_name} - {move_ref}"
		}

		name = next((v for k, v in name_mapping.items() if move_type in (k if isinstance(k, tuple) else (k,))), self.name or '')

		return {
			'name': name,
		}

	@api.constrains('debit', 'credit')
	def _check_debit_credit(self):
		"""Valida que no se tenga débito y crédito al mismo tiempo."""
		for record in self:
			if float_is_zero(record.debit, precision_rounding=record.company_currency_id.rounding):
				continue
			if float_is_zero(record.credit, precision_rounding=record.company_currency_id.rounding):
				continue
			if not float_is_zero(record.debit * record.credit, precision_rounding=record.company_currency_id.rounding):
				raise ValidationError(_("No puede tener débito y crédito al mismo tiempo."))

	def _get_payment_info(self) -> dict:
		"""Genera información detallada para tooltips."""
		self.ensure_one()
		if not self.move_line_id:
			return False

		move_line = self.move_line_id
		move = move_line.move_id
		company_currency = self.company_currency_id
		original_currency = move_line.currency_id or company_currency
		original_amount = abs(move_line.amount_currency or move_line.balance)
		converted_amount = original_amount
		if original_currency != company_currency:
			converted_amount = original_currency._convert(
				original_amount,
				company_currency,
				self.company_id,
				move.date or fields.Date.today()
			)
			exchange_rate = converted_amount / original_amount if original_amount else 0.0
		else:
			exchange_rate = 1.0
		paid_amount = abs(original_amount - abs(self.amount_residual_currency or self.amount_residual))
		
		tax_details = []
		tax_total = 0.0
		
		if move.line_ids:
			for tax_line in move.line_ids:
				if tax_line.tax_line_id:
					tax_amount = tax_line.amount_currency or tax_line.balance
					tax_details.append({
						'id': tax_line.tax_line_id.id,
						'name': tax_line.tax_line_id.name,
						'amount': tax_amount,
						'rate': tax_line.tax_line_id.amount
					})
					tax_total += tax_amount

		return {
			'original_amount': original_amount,
			'original_currency': original_currency.name,
			'exchange_rate': exchange_rate,
			'converted_amount': converted_amount,
			'company_currency': company_currency.name,
			'residual_amount': abs(self.amount_residual_currency or self.amount_residual),
			'paid_amount': paid_amount,
			'tax_amount': tax_total,
			'tax_details': tax_details
		}


	@api.depends('currency_id', 'company_currency_id', 'payment_id.date')
	def _compute_needs_rate_update(self):
		"""Verifica si la tasa necesita actualización (más de 3 días)."""
		for record in self:
			if record.currency_id == record.company_currency_id:
				record.needs_rate_update = False
				continue

			record.needs_rate_update = not record._check_recent_rate(
				record.payment_id.date or fields.Date.context_today(record)
			)

	def _get_currency_rate(self, date):
		"""Obtiene la tasa de cambio inversa para una fecha específica."""
		self.ensure_one()
		if self.payment_currency_id == self.company_currency_id:
			return 1.0

		rate = self.payment_currency_id._get_conversion_rate(
			self.payment_currency_id,
			self.company_currency_id,
			self.company_id,
			date
		)
		
		return rate

	@api.depends('currency_id', 'company_currency_id', 'move_line_id', 'payment_id.date')
	def _compute_currency_rate(self):
		"""Calcula la tasa de cambio inversa para las conversiones."""
		for record in self:
			if record.payment_currency_id == record.company_currency_id:
				record.currency_rate = 1.0
				continue

			date = record.payment_id.date or fields.Date.context_today(record)
			rate = record._get_currency_rate(date)
			record.currency_rate = rate


	def _check_recent_rate(self, date):
		"""Verifica si existe una tasa de cambio reciente (últimos 3 días)."""
		self.ensure_one()
		if self.payment_currency_id == self.company_currency_id:
			return True

		three_days_ago = date - timedelta(days=3)
		
		self.env.cr.execute("""
			SELECT id FROM res_currency_rate 
			WHERE currency_id = %s 
			AND company_id = %s 
			AND name >= %s
			LIMIT 1
		""", (self.payment_currency_id.id, self.company_id.id, three_days_ago))
		
		return bool(self.env.cr.fetchone())

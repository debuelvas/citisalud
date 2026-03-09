from odoo import fields, models, api, _
import logging
from odoo.tools import float_is_zero, float_round
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any

_logger = logging.getLogger(__name__)


class AccountPaymentDetail(models.Model):
	_name = "account.payment.detail"
	_description = "Detalle de transferencia, pago y/o cobro"
	_inherit = "analytic.mixin"

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
	balance = fields.Monetary(compute='_compute_debit_credit_balance', store=True, readonly=False, currency_field='company_currency_id', precompute=True)
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
	amount_residual = fields.Monetary(string="Deuda MN", compute="_compute_amount_residual", store=True, currency_field='company_currency_id')
	amount_residual_currency = fields.Monetary(string="Deuda ME", compute="_compute_amount_residual", store=True, currency_field='currency_id')
	date_maturity = fields.Date(related="move_line_id.date_maturity", store=True, string="Fecha vencimiento")
	payment_currency_id = fields.Many2one('res.currency', string="Moneda de pago", compute='_compute_payment_currency', store=True)
	payment_amount = fields.Monetary('Monto de pago', currency_field="payment_currency_id")
	exclude_from_payment_detail = fields.Boolean()
	to_pay = fields.Boolean('A pagar', default=False)
	product_id = fields.Many2one('product.product', string='Product')
	tax_ids = fields.Many2many('account.tax', string='Taxes', store=True, check_company=True)
	tax_tag_ids = fields.Many2many('account.account.tag', string="Tags", ondelete='restrict')
	tax_repartition_line_id = fields.Many2one('account.tax.repartition.line', string="Originator Tax Distribution Line", ondelete='restrict', check_company=True)
	auto_tax_line = fields.Boolean()
	tax_line_id = fields.Many2one('account.payment.detail', ondelete='cascade')
	tax_line_id2 = fields.Many2one('account.tax', ondelete='cascade')
	tax_base_amount = fields.Monetary(string="Base Amount", currency_field='company_currency_id')
	currency_rate = fields.Float('Tasa de Cambio', digits=(16, 6), compute='_compute_currency_rate', store=True, help="Tasa de cambio usada en la conversión")
	needs_rate_update = fields.Boolean(compute='_compute_needs_rate_update')
	exchange_diff_amount = fields.Monetary(string='Diferencia de Cambio', compute='_compute_exchange_diff', store=True, currency_field='company_currency_id')
	exchange_diff_foreign = fields.Monetary(
		string='Diferencia ME',
		currency_field='currency_id',
		help="Diferencia de cambio en moneda extranjera del documento"
	)
	needs_rate_adjustment = fields.Boolean(
		string='Requiere Ajuste',
		compute='_compute_needs_rate_adjustment',
		help="Indica si la diferencia en cambio requiere ajuste"
	)

	is_final_payment = fields.Boolean(
		string='Es Pago Final',
		compute='_compute_is_final_payment',
		store=True,
		help="Indica si este pago cubre o excede el monto residual"
	)
	payment_difference = fields.Monetary(compute='_compute_payment_difference', string='Payment Difference', readonly=True, store=True)
	payment_difference_handling = fields.Selection([('open', 'Mantener abierto'), ('reconcile', 'Marcar la factura como totalmente pagada')], default='open', string="Payment Difference Handling", copy=False)
	writeoff_account_id = fields.Many2one('account.account', string="Difference Account", domain=[('deprecated', '=', False)], copy=False)
	amount_info = fields.Json(string='Amount Information', compute='_compute_amount_info')
	# -------------------------------------------------------------------------
	# Utility methods
	# -------------------------------------------------------------------------

	def _convert_amount(
		self,
		amount: float,
		from_currency: 'res.currency',
		to_currency: 'res.currency',
		date: fields.Date,
		company: Optional['res.company'] = None,
		round: bool = True
	) -> float:
		"""
		Convierte un monto entre monedas, usando tasa manual si está configurada.
		Maneja conversiones entre cualquier par de divisas basándose en la moneda de la compañía.
		"""
		_logger = logging.getLogger(__name__)
		company = company or self.company_id or self.env.company
		company_currency = company.currency_id
		if from_currency == to_currency or float_is_zero(amount, precision_rounding=from_currency.rounding):
			return amount
		if self.payment_id.manual_currency_rate_active and self.payment_id.current_exchange_rate:
			rate = self.payment_id.current_exchange_rate
			if from_currency == company_currency and to_currency != company_currency:
				converted_amount = amount / rate
			elif from_currency != company_currency and to_currency == company_currency:
				converted_amount = amount * rate
			else:
				amount_company = amount * rate if from_currency != company_currency else amount / rate
				converted_amount = amount_company / rate if to_currency != company_currency else amount_company * rate
			if round:
				converted_amount = to_currency.round(converted_amount)
			return converted_amount

		return from_currency._convert(amount, to_currency, company, date, round=round)
	# -------------------------------------------------------------------------
	# Compute methods
	# -------------------------------------------------------------------------

	@api.depends('move_line_id.amount_residual', 'move_line_id.amount_residual_currency', 
					'move_line_id.currency_id', 'date', 'payment_currency_id')
	def _compute_amount_residual(self) -> None:
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
					record.amount_residual_currency = record._convert_amount(
						move_line.amount_residual,
						record.company_currency_id,
						move_line.currency_id,
						document_date,
						record.company_id,
						round=True
					)
			else:
				record.amount_residual_currency = move_line.amount_residual

	@api.depends('move_line_id', 'move_line_id.currency_id', 'payment_id.currency_id')
	def _compute_payment_currency(self) -> None:
		for record in self:
			record.payment_currency_id = record.payment_id.currency_id or record.company_id.currency_id or self.env.company.currency_id

	@api.depends('payment_amount', 'payment_currency_id', 'invoice_id', 'move_line_id',
			'payment_id.payment_type', 'payment_id.date', 'payment_id.currency_id')
	def _compute_debit_credit_balance(self):
		"""
		Optimizado: Calcula débito, crédito y balance.
		- Usar context_today() en lugar de Date.today()
		- Eliminada variable sign sin uso
		"""
		for val in self:
			balance = val.payment_amount
			company = val.company_id or val.env.company
			# Optimizado: Usar context_today() en lugar de Date.today()
			payment_date = val.payment_id.date or fields.Date.context_today(val)

			if val.payment_id.currency_id and self.payment_id.currency_id != company.currency_id:
				currency = val.payment_id.currency_id
				balance = val._convert_amount(balance,val.payment_id.currency_id, 
					val.company_currency_id, 
					payment_date, 
					company
				)
			if val.move_line_id:
				val.debit = balance > 0.0 and balance or False
				val.credit = balance < 0.0 and abs(balance) or False
				val.balance = balance	
			else:
				val.debit = balance > 0.0 and balance or False
				val.credit = balance < 0.0 and abs(balance) or False
				val.balance = balance


	@api.depends('balance')
	def _compute_type(self) -> None:
		for val in self:
			val.type = 'Ingreso' if val.balance > 0 else 'Egreso'

	@api.depends('move_line_id', 'payment_amount', 'payment_currency_id', 'date')
	def _compute_exchange_diff(self) -> None:
		"""
		Optimizado: Calcula diferencia de cambio.
		- Usar context_today() en lugar de Date.today()
		"""
		for record in self:
			record.exchange_diff_amount = 0.0
			if not record.move_line_id or not record.payment_amount:
				continue
			original_date = record.move_line_id.move_id.date or record.move_line_id.date
			# Optimizado: Usar context_today() en lugar de Date.today()
			payment_date = record.date or fields.Date.context_today(record)

			if original_date != payment_date:
				diff_company, diff_foreign = record._calculate_exchange_difference_payment(original_date, payment_date)
				record.exchange_diff_amount = diff_company

	def _calculate_exchange_difference_payment(self, original_date, payment_date):
		"""Calcula diferencia en ambas monedas"""
		self.ensure_one()
		
		if (self.payment_currency_id == self.company_currency_id and 
			(not self.move_line_id.currency_id or 
				self.move_line_id.currency_id == self.company_currency_id)):
			return 0.0, 0.0

		payment_amount = self.payment_amount
		doc_currency = self.move_line_id.currency_id or self.company_currency_id

		if self.move_line_id.currency_id and doc_currency != self.company_currency_id:
			# Documento en moneda extranjera
			if self.payment_currency_id == doc_currency:
				amount_doc_curr = payment_amount
				amount_original = self._convert_amount(payment_amount, doc_currency, self.company_currency_id, original_date)
				amount_payment = self._convert_amount(payment_amount, doc_currency, self.company_currency_id, payment_date)
			else:
				amount_doc_curr = self._convert_amount(payment_amount, self.payment_currency_id, doc_currency, payment_date)
				amount_original = self._convert_amount(amount_doc_curr, doc_currency, self.company_currency_id, original_date)
				amount_payment = self._convert_amount(amount_doc_curr, doc_currency, self.company_currency_id, payment_date)
		else:
			amount_doc_curr = payment_amount
			amount_original = self._convert_amount(payment_amount, self.payment_currency_id, self.company_currency_id, original_date)
			amount_payment = self._convert_amount(payment_amount, self.payment_currency_id, self.company_currency_id, payment_date)

		# Calcular diferencias
		diff_company = amount_payment - amount_original
		diff_foreign = amount_doc_curr - (self.amount_residual_currency or 0.0)

		# Ajustar signo
		if self.move_line_id.move_id.move_type in ['out_invoice', 'in_refund']:
			diff_company *= -1
			diff_foreign *= -1

		self.exchange_diff_amount = diff_company
		self.exchange_diff_foreign = diff_foreign

		return diff_company, diff_foreign

	def _get_payment_info(self) -> Optional[Dict[str, Any]]:
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
		# Optimizado: Usar context_today() en lugar de Date.today()
		if original_currency != company_currency:
			converted_amount = original_currency._convert(
				original_amount,
				company_currency,
				self.company_id,
				move.date or fields.Date.context_today(self)
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


	@api.depends('display_type')
	def _compute_sequence(self) -> None:
		seq_map = {
			'tax': 10000,
			'rounding': 11000,
			'payment_term': 12000,
		}
		for line in self:
			line.sequence = seq_map.get(line.display_type, 100)

	@api.depends('payment_id')
	def _compute_display_type(self) -> None:
		for line in self.filtered(lambda l: not l.display_type):
			move = line.move_line_id.move_id if line.move_line_id else None
			move_type = move.move_type if move else ''
			if line.tax_line_id:
				line.display_type = 'tax'
			elif move_type in ("out_invoice", "out_receipt"):
				line.display_type = 'invoice'
			elif move_type in ("in_invoice", "in_receipt"):
				line.display_type = 'bill'
			elif move_type in ("in_refund", "out_refund"):
				line.display_type = 'reverse'
			elif move_type == 'entry':
				line.display_type = 'entry'
			elif not line.move_line_id and line.account_id and getattr(line.account_id, 'used_for_advance_payment', False):
				line.display_type = 'advance'
			elif line.product_id:
				line.display_type = 'product'
			else:
				line.display_type = 'counterpart'

	@api.depends('move_line_id', 'invoice_id', 'payment_amount', 'payment_currency_id')
	def _compute_payment_difference(self) -> None:
		for record in self:
			if not record.move_line_id:
				record.payment_difference = 0.0
				continue

			residual_payment_currency = record.amount_residual
			if record.payment_currency_id != record.company_currency_id:
				residual_payment_currency = record._convert_amount(
					record.amount_residual,
					record.company_currency_id,
					record.payment_currency_id,
					record.date or fields.Date.context_today(record),
					record.company_id
				)
			record.payment_difference = residual_payment_currency - record.payment_amount

	@api.depends('move_line_id', 'payment_amount', 'currency_id', 'payment_currency_id')
	def _compute_amount_info(self) -> None:
		for record in self:
			record.amount_info = record._get_payment_info() if record.move_line_id else False

	@api.onchange('payment_amount', 'payment_currency_id', 'payment_id.payment_type', 'date')
	def _onchange_payment_amount(self) -> None:
		"""
		Ajusta amount_currency según el payment_amount, aplicando el signo apropiado.
		Si la línea es débito => payment_amount > 0, si es crédito => payment_amount < 0.
		"""
		if self.env.context.get('skip_recalc', False):
			return

		for val in self:
			# Determinar signo según si es débito o crédito
			# Si credit > 0 significa la línea es de crédito => monto negativo
			# Si debit > 0 la línea es de débito => monto positivo
			if val.credit > 0:
				sign = -1
			else:
				sign = 1

			# Si la currency es distinta a la compañía, ya se ha convertido antes,
			# aquí sólo ajustamos signo.
			# Si se quiere mantener la conversión exacta, ya está hecha en los onchanges inversos.
			sign = -1 if val.credit > 0 else 1
			val.payment_amount = abs(val.payment_amount) * sign
			val.amount_currency = val.payment_amount

	def _compute_payment_amount(self, invoices=None, currency: Optional['res.currency'] = None) -> float:
		self.ensure_one()
		payment_currency = currency or self.payment_currency_id or self.journal_id.currency_id or self.company_currency_id
		if not self.move_line_id:
			return self.payment_amount

		sign = -1
		amount_company_currency = self.amount_residual * sign
		doc_currency = self.move_line_id.currency_id or self.company_currency_id

		if doc_currency == self.company_currency_id and payment_currency != self.company_currency_id:
			return self._convert_amount(
				amount_company_currency,
				self.company_currency_id,
				payment_currency,
				self.date or fields.Date.today(),
				self.company_id
			)

		if doc_currency != self.company_currency_id and self.move_line_id.amount_residual_currency:
			amount_foreign_currency = self.move_line_id.amount_residual_currency * sign
			if payment_currency != doc_currency:
				return self._convert_amount(
					amount_foreign_currency,
					doc_currency,
					payment_currency,
					self.date or fields.Date.today(),
					self.company_id
				)
			return amount_foreign_currency

		if payment_currency == self.company_currency_id:
			return amount_company_currency

		return self._convert_amount(
			amount_company_currency,
			self.company_currency_id,
			payment_currency,
			self.date or fields.Date.today(),
			self.company_id
		)

	@api.onchange('to_pay', 'payment_id.payment_type', 'payment_amount')
	def _onchange_to_pay(self) -> None:
		if self.env.context.get('skip_recalc', False):
			return

		for record in self:
			if record.payment_id.payment_type != 'transfer' and record.to_pay:
				payment_amount = record._compute_payment_amount(currency=record.payment_currency_id)
				payment_amount = float_round(payment_amount, precision_rounding=record.payment_currency_id.rounding)
				# Ajustar el signo según sea débito o crédito
				if record.credit > 0:
					# Línea de crédito => monto negativo
					payment_amount = -payment_amount
				else:
					# Línea de débito => monto positivo
					payment_amount = payment_amount

				record.with_context(skip_recalc=True).write({
					'payment_amount': payment_amount,
					'currency_id': record.payment_currency_id.id
				})

	@api.onchange('move_line_id')
	def _onchange_move_lines(self) -> None:
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
				'currency_id': move_line.currency_id.id if move_line.currency_id else False,
			})
			self._update_payment_amount(record)

	def _update_payment_amount(self, record: 'account.payment.detail') -> None:
		if self.env.context.get('skip_recalc', False):
			return
		record._onchange_payment_amount()

	def _onchange_read_line_pay(self) -> None:
		if self.env.context.get('skip_recalc', False):
			return
		for line in self:
			line._onchange_to_pay()
			line._onchange_payment_amount()

	def _get_counterpart_move_line_vals(self) -> Dict[str, Any]:
		self.ensure_one()
		move_line_name = f"Pago Documento: {self.invoice_id.name}" if self.invoice_id else (self.name or '')
		currency = self.currency_id if (self.currency_id and self.currency_id != self.company_currency_id) else self.payment_currency_id

		vals: Dict[str, Any] = {
			'name': move_line_name,
			'ref': self.payment_id.ref or '',
			'account_id': self.account_id.id,
			'partner_id': self.partner_id.id if self.partner_id else False,
			'date': self.date,
			'currency_id': currency.id if currency else False,
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

		if currency and currency != self.company_currency_id:
			sign = 1 if self.debit > 0.0 else -1
			vals['amount_currency'] = abs(self.amount_currency) * sign

		return vals

	def _get_counterpart_move_name(self) -> Dict[str, str]:
		move_type = self.move_line_id.move_id.move_type
		invoice_name = self.invoice_id.name if self.invoice_id else ''
		move_ref = self.move_line_id.move_id.ref or ''

		name_mapping = {
			("out_invoice", "out_receipt"): f"Pago de Factura: {invoice_name}",
			("in_invoice", "in_receipt"): f"Pago Factura de compra: {invoice_name} - {move_ref}",
			("in_refund", "out_refund"): f"Cruce de Nota Credito: {invoice_name} - {move_ref}",
			"entry": f"Pago Documento: {invoice_name} - {move_ref}"
		}

		for key, val in name_mapping.items():
			if move_type in (key if isinstance(key, tuple) else (key,)):
				return {'name': val}

		return {'name': self.name or ''}

	@api.constrains('debit', 'credit')
	def _check_debit_credit(self) -> None:
		for record in self:
			if (not float_is_zero(record.debit, precision_rounding=record.company_currency_id.rounding) and 
				not float_is_zero(record.credit, precision_rounding=record.company_currency_id.rounding) and
				not float_is_zero(record.debit * record.credit, precision_rounding=record.company_currency_id.rounding)):
				raise ValueError(_("No puede tener débito y crédito al mismo tiempo."))

	def _check_recent_rate(self, date: fields.Date) -> bool:
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

	@api.depends('currency_id', 'company_currency_id', 'payment_id.date')
	def _compute_needs_rate_update(self) -> None:
		for record in self:
			if record.currency_id == record.company_currency_id:
				record.needs_rate_update = False
				continue
			record.needs_rate_update = not record._check_recent_rate(record.payment_id.date or fields.Date.context_today(record))

	def _get_currency_rate(self, date: fields.Date) -> float:
		self.ensure_one()
		if self.payment_currency_id == self.company_currency_id:
			return 1.0
		return self._convert_amount(1.0, self.payment_currency_id, self.company_currency_id, date, self.company_id)

	@api.depends('currency_id', 'company_currency_id', 'move_line_id', 'payment_id.date')
	def _compute_currency_rate(self) -> None:
		for record in self:
			if record.payment_currency_id == record.company_currency_id:
				record.currency_rate = 1.0
				continue
			date = record.payment_id.date or fields.Date.context_today(record)
			record.currency_rate = record._get_currency_rate(date)


	@api.onchange('debit')
	def _inverse_debit(self):
		"""
		Maneja cambios en el campo débito asegurando el signo correcto
		"""
		if self.env.context.get('skip_recalc', False):
			return
			
		for line in self:
			if float_is_zero(line.debit, precision_rounding=line.company_currency_id.rounding):
				continue
				
			line.credit = 0.0
			balance = abs(line.debit)  # El débito siempre es positivo
			
			# Optimizado: Usar context_today() en lugar de Date.today()
			# Convertir a moneda de pago si es necesario
			payment_amount = balance
			if line.payment_currency_id != line.company_currency_id:
				payment_amount = line._convert_amount(
					balance,
					line.company_currency_id,
					line.payment_currency_id,
					line.date or fields.Date.context_today(line),
					line.company_id
				)
			
			# Para débito el payment_amount debe ser positivo
			payment_amount = abs(payment_amount)
			
			line.with_context(skip_recalc=True).write({
				'payment_amount': payment_amount,
				'amount_currency': payment_amount,
				'balance': balance
			})

	@api.onchange('credit')
	def _inverse_credit(self):
		"""
		Maneja cambios en el campo crédito asegurando el signo correcto
		"""
		if self.env.context.get('skip_recalc', False):
			return
			
		for line in self:
			if float_is_zero(line.credit, precision_rounding=line.company_currency_id.rounding):
				continue
				
			line.debit = 0.0
			balance = -abs(line.credit)  # El crédito siempre es negativo
			
			# Optimizado: Usar context_today() en lugar de Date.today()
			# Convertir a moneda de pago si es necesario
			payment_amount = abs(balance)  # El monto de pago siempre es positivo
			if line.payment_currency_id != line.company_currency_id:
				payment_amount = line._convert_amount(
					abs(balance),  # Convertimos el valor absoluto
					line.company_currency_id,
					line.payment_currency_id,
					line.date or fields.Date.context_today(line),
					line.company_id
				)
			
			# Para crédito el payment_amount debe ser negativo
			payment_amount = -abs(payment_amount)
			
			line.with_context(skip_recalc=True).write({
				'payment_amount': payment_amount,
				'amount_currency': payment_amount,
				'balance': balance
			})

	@api.onchange('payment_amount')
	def _onchange_payment_amount(self):
		"""
		Maneja cambios en el monto de pago asegurando el signo correcto
		según si es débito o crédito
		"""
		if self.env.context.get('skip_recalc', False):
			return
			
		for record in self:
			if float_is_zero(record.payment_amount, precision_rounding=record.payment_currency_id.rounding):
				continue

			# Determinar si debe ser débito o crédito basado en el signo del monto
			is_credit = record.payment_amount < 0
			payment_amount = record.payment_amount
			
			# Optimizado: Usar context_today() en lugar de Date.today()
			# Convertir a moneda de la compañía si es necesario
			company_amount = payment_amount
			if record.payment_currency_id != record.company_currency_id:
				company_amount = record._convert_amount(
					abs(payment_amount),  # Convertimos el valor absoluto
					record.payment_currency_id,
					record.company_currency_id,
					record.date or fields.Date.context_today(record),
					record.company_id
				)
				if is_credit:
					company_amount = -company_amount

			# Actualizar débito/crédito según el signo
			record.with_context(skip_recalc=True).write({
				'debit': abs(company_amount) if company_amount > 0 else 0.0,
				'credit': abs(company_amount) if company_amount < 0 else 0.0,
				'balance': company_amount,
				'amount_currency': payment_amount
			})

	def _update_amounts_from_balance(self, balance):
		"""
		Actualiza los montos basados en el balance manteniendo el signo correcto
		"""
		self.ensure_one()
		
		# Determinar si es crédito o débito basado en el balance
		is_credit = balance < 0
		
		# Calcular monto de pago en moneda de pago
		payment_amount = abs(balance)
		if self.payment_currency_id != self.company_currency_id:
			payment_amount = self._convert_amount(
				abs(balance),
				self.company_currency_id,
				self.payment_currency_id
			)
		
		# Aplicar el signo según sea crédito o débito
		if is_credit:
			payment_amount = -payment_amount
			
		return {
			'payment_amount': payment_amount,
			'amount_currency': payment_amount
		}

	def action_view_move_line(self):
		"""
		Muestra la vista detallada de la línea con campos editables
		"""
		self.ensure_one()
		
		return {
			'name': 'Detalle de línea',
			'type': 'ir.actions.act_window',
			'view_mode': 'form',
			'res_model': 'account.payment.detail',
			'res_id': self.id,
			'view_id': self.env.ref('custom_account_treasury.view_payment_detail_from').id,
			'target': 'new',
			'context': {
				'force_detailed_view': True
			}
		}

	def action_save_changes(self):
		"""
		Guarda los cambios y cierra el modal
		"""
		return {'type': 'ir.actions.act_window_close'}


	@api.depends('payment_amount', 'amount_residual', 'amount_residual_currency')
	def _compute_is_final_payment(self):
		"""Determina si el pago actual cubre o excede el residual"""
		for record in self:
			record.is_final_payment = False
			if not record.move_line_id or not record.payment_amount:
				continue

			# Convertir montos a la moneda de la empresa si es necesario
			payment_company = record.debit - record.credit
			if record.payment_currency_id != record.company_currency_id:
				# Optimizado: Usar context_today() y agregar company
				payment_company = record._convert_amount(
					record.payment_amount,
					record.payment_currency_id,
					record.company_currency_id,
					record.date or fields.Date.context_today(record),
					record.company_id
				)

			# Verificar en moneda de la empresa
			is_final_company = abs(payment_company) >= abs(record.amount_residual)

			# Verificar en moneda extranjera si aplica
			if record.move_line_id.currency_id and record.move_line_id.currency_id != record.company_currency_id:
				if record.payment_currency_id == record.move_line_id.currency_id:
					payment_foreign = record.payment_amount
				else:
					# Optimizado: Usar context_today() y agregar company
					payment_foreign = record._convert_amount(
						record.payment_amount,
						record.payment_currency_id,
						record.move_line_id.currency_id,
						record.date or fields.Date.context_today(record),
						record.company_id
					)
				is_final_foreign = abs(payment_foreign) >= abs(record.amount_residual_currency)
				record.is_final_payment = is_final_company and is_final_foreign
			else:
				record.is_final_payment = is_final_company


	@api.depends('payment_amount', 'amount_residual', 'amount_residual_currency', 
				'debit', 'credit', 'amount_currency', 'is_final_payment')
	def _compute_needs_rate_adjustment(self):
		"""
		Determina si se necesita ajuste de tipo de cambio comparando saldos
		en moneda local y extranjera
		"""
		for record in self:
			record.needs_rate_adjustment = False
			if not record.move_line_id or not record.payment_amount:
				continue

			if not record.currency_id or record.currency_id == record.company_currency_id:
				continue
			if record.is_final_payment:
				local_balance = abs(record.amount_residual) - abs(record.debit - record.credit)
				foreign_balance = abs(record.amount_residual_currency) - abs(record.amount_currency)
				
				local_zero = float_is_zero(
					local_balance,
					precision_rounding=record.company_currency_id.rounding
				)
				foreign_zero = float_is_zero(
					foreign_balance,
					precision_rounding=record.currency_id.rounding
				)
				
				record.needs_rate_adjustment = local_zero != foreign_zero
			else:
				if float_is_zero(record.amount_residual_currency, precision_rounding=record.currency_id.rounding):
					continue
					
				company_payment_ratio = abs(record.debit - record.credit) / abs(record.amount_residual)
				foreign_payment_ratio = abs(record.amount_currency) / abs(record.amount_residual_currency)
				
				record.needs_rate_adjustment = not float_is_zero(
					company_payment_ratio - foreign_payment_ratio,
					precision_digits=4  # Precisión para comparar ratios
				)

	def _get_exchange_diff_params(self):
		"""
		Obtiene los parámetros necesarios para la diferencia en cambio:
		- Diario específico para diferencias de cambio
		- Cuenta contable (ganancia o pérdida)
		- Fecha contable
		
		Returns:
			tuple: (journal, account, date)
		"""
		self.ensure_one()
		company = self.company_id
		journal = company.currency_exchange_journal_id
		if not journal:
			raise UserError(_('Configure el diario para diferencias en cambio en la compañía.'))
		if self.writeoff_account_id:
			exchange_account = self.writeoff_account_id
		else:
			if self.exchange_diff_amount > 0:
				exchange_account = company.income_currency_exchange_account_id
				if not exchange_account:
					raise UserError(_('Configure la cuenta de ganancia por diferencia en cambio en la compañía.'))
			else:
				exchange_account = company.expense_currency_exchange_account_id
				if not exchange_account:
					raise UserError(_('Configure la cuenta de pérdida por diferencia en cambio en la compañía.'))
		# Optimizado: Usar context_today() en lugar de Date.today()
		exchange_date = self.date or fields.Date.context_today(self)
		accounting_date = journal.with_context(move_date=exchange_date).accounting_date
		return journal, exchange_account, accounting_date

	def _prepare_exchange_diff_vals(self, exchange_move, exchange_account, full_reconcile):
		"""
		Prepara los valores para las líneas de diferencia en cambio
		considerando ganancia/pérdida y signos correctos
		"""
		self.ensure_one()
		is_gain = self.exchange_diff_amount > 0

		# Para la línea de diferencia
		diff_line_vals = {
			'name': f'Diferencia en cambio {self.move_line_id.move_id.name or ""}',
			'account_id': exchange_account.id,
			'partner_id': self.partner_id.id,
			'move_id': exchange_move.id,
			'currency_id': self.payment_currency_id.id,
			'line_pay': self.move_line_id.id,
			#'full_reconcile_id': full_reconcile.id if full_reconcile else False,
			#'exchange_rate': self.currency_rate,
		}

		# Para la contrapartida
		counterpart_vals = {
			'name': f'Contrapartida dif. cambio {self.move_line_id.move_id.name or ""}',
			'account_id': self.move_line_id.account_id.id,
			'partner_id': self.partner_id.id,
			'move_id': exchange_move.id,
			'currency_id': self.payment_currency_id.id,
			'line_pay': self.move_line_id.id,
			'full_reconcile_id': full_reconcile.id if full_reconcile else False,
			#'exchange_rate': self.currency_rate,
		}

		if is_gain:
			# Diferencia en cambio positiva (ganancia)
			diff_line_vals.update({
				'credit': abs(self.exchange_diff_amount),
				'debit': 0.0,
				'amount_currency': -abs(self.exchange_diff_foreign) if self.currency_id != self.company_currency_id else 0.0,
			})
			counterpart_vals.update({
				'debit': abs(self.exchange_diff_amount),
				'credit': 0.0,
				'amount_currency': abs(self.exchange_diff_foreign) if self.currency_id != self.company_currency_id else 0.0,
			})
		else:
			# Diferencia en cambio negativa (pérdida)
			diff_line_vals.update({
				'debit': abs(self.exchange_diff_amount),
				'credit': 0.0,
				'amount_currency': abs(self.exchange_diff_foreign) if self.currency_id != self.company_currency_id else 0.0,
			})
			counterpart_vals.update({
				'credit': abs(self.exchange_diff_amount),
				'debit': 0.0,
				'amount_currency': -abs(self.exchange_diff_foreign) if self.currency_id != self.company_currency_id else 0.0,
			})

		return diff_line_vals, counterpart_vals

	def create_exchange_diff_line(self):
		"""
		Crea asiento de diferencia en cambio, manejando casos de:
		- Asiento existente (borrar y recrear)
		- Diferencia igual al pago (no crear)
		- Conciliación múltiple
		"""
		self.ensure_one()
		
		if float_is_zero(self.exchange_diff_amount, precision_rounding=self.company_currency_id.rounding):
			return False
		if self.move_id:
			reconciled_lines = self.move_id.line_ids.filtered(lambda l: l.full_reconcile_id)
			if reconciled_lines:
				reconciled_lines.remove_move_reconcile()
			self.move_id.button_draft()
			self.move_id.unlink()

		journal, exchange_account, accounting_date = self._get_exchange_diff_params()
		full_reconcile = self.move_line_id.full_reconcile_id

		exchange_move = self.env['account.move'].create({
			'move_type': 'entry',
			'date': accounting_date,
			'journal_id': journal.id,
			'company_id': self.company_id.id,
			'ref': f'Dif. Cambio - {self.move_line_id.move_id.name or ""}',
			'currency_id': self.payment_currency_id.id,
		})
		diff_line_vals, counterpart_vals = self._prepare_exchange_diff_vals(
			exchange_move, exchange_account, full_reconcile
		)

		exchange_move.write({
			'line_ids': [
				(0, 0, diff_line_vals),
				(0, 0, counterpart_vals)
			]
		})

		exchange_move.action_post()
		self.move_id = exchange_move.id

		lines_to_reconcile = self.env['account.move.line']
		payment_line = self.payment_id.move_id.line_ids.filtered(
			lambda l: l.line_pay.id == self.move_line_id.id
		)
		lines_to_reconcile |= payment_line  
		lines_to_reconcile |= self.move_line_id 
		lines_to_reconcile |= exchange_move.line_ids.filtered( 
			lambda l: l.account_id == self.move_line_id.account_id
		)
		lines_to_reconcile.reconcile()
		return exchange_move
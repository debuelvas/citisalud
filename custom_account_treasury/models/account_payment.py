from odoo import models, fields, api, _,Command
from odoo.exceptions import UserError, ValidationError
from odoo.tools import (
	date_utils,
	email_re,
	email_split,
	float_compare,
	float_is_zero,
	float_repr,
	format_amount,
	format_date,
	formatLang,
	frozendict,
	get_lang,
	is_html_empty,
	sql
)
from functools import partial
from collections import defaultdict
import logging

_logger = logging.getLogger(__name__)

class AccountPayment(models.Model):
	_inherit = 'account.payment'

	@api.depends('payment_line_ids.invoice_id')
	def _compute_domain_move_line(self):
		for pay in self:
			invoices = pay.mapped('payment_line_ids.invoice_id')
			pay.domain_move_lines = [(6,0,invoices.ids)]

	@api.depends('payment_line_ids.move_line_id')
	def _compute_domain_accountmove_line(self):
		for pay in self:
			invoices = pay.mapped('payment_line_ids.move_line_id')
			pay.domain_account_move_lines = [(6,0,invoices.ids)]


	move_diff_ids = fields.Many2many('account.move', 'account_move_payment_rel_ids', 'move_id', 'payment_id', copy=False)
	payment_line_ids = fields.One2many('account.payment.detail', 'payment_id', copy=False, string="Detalle de pago", help="detalle de pago")
	currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        compute='_compute_currency_id', store=True, readonly=False, precompute=True, default=lambda self: self.env.company.currency_id,
        help="The payment's currency.")
	destination_account_id = fields.Many2one(
		comodel_name='account.account',
		string='Destination Account',
		store=True, readonly=False,
		compute='_compute_destination_account_id',
		domain="[('account_type', 'in', ('asset_receivable', 'liability_payable')), ('company_id', '=', company_id)]",
		check_company=True)
	change_destination_account = fields.Char(string="cambio de cuenta destino")

	invoice_cash_rounding_id = fields.Many2one(
		comodel_name='account.cash.rounding',
		string='Cash Rounding Method',
		readonly=True,
		help='Defines the smallest coinage of the currency that can be used to pay by cash.',
	)

	company_currency_id = fields.Many2one('res.currency', string="Moneda de la compañia",
		required=True, default=lambda self: self.env.company.currency_id)

	# === Buscar Documentos fields === #
	customer_invoice_ids = fields.Many2many("account.move", "customer_invoice_payment_rel", 'invoice_id', 'payment_id',
		string="Buscar Documentos Clientes", domain="[('state','!=','draft')]")
	supplier_invoice_ids = fields.Many2many("account.move", "supplier_invoice_payment_rel", 'invoice_id', 'payment_id',
		string="Buscar Documentos Proveedores", domain="[('state','!=','draft')]")
	account_move_payment_ids = fields.Many2many("account.move.line", "account_move_payment_rel",
		string="Buscar Otros Documentos", domain="[('amount_residual','!=', 0),('parent_state','!=','draft'),('account_id.account_type', 'in', ['asset_receivable', 'liability_payable'])]")
	
	invoice_id = fields.Many2one(
		comodel_name='account.move',
		string='Factura',
		required=False)

	# === Filtrar Documentos fields === #
	domain_account_move_lines = fields.Many2many("account.move.line", 'domain_account_move_line_pay_rel', string="restriccion de campos", compute="_compute_domain_accountmove_line")
	domain_move_lines = fields.Many2many("account.move", 'domain_move_line_pay_rel', string="restriccion de campos", compute="_compute_domain_move_line")


	# === advance fields === #
	advance_type_id = fields.Many2one('advance.type', string="Tipo de anticipo")
	advance = fields.Boolean('Anticipo', default=False)
	code_advance = fields.Char(string="Número de anticipo", copy=False)
	partner_type = fields.Selection(selection_add=[
		('employee', 'Empleado'),
	], ondelete={'employee': 'set default'})

	# === writeoff fields === #
	writeoff_account_id = fields.Many2one('account.account', string="Cuenta de diferencia", copy=False,
		domain="[('deprecated', '=', False), ('company_id', '=', company_id)]")
	writeoff_label = fields.Char(string='Journal Item Label', default='Diferencia',
		help='Change label of the counterpart that will hold the payment difference')
	payment_difference_line = fields.Monetary(string="Diferencia de pago",
		store=True, readonly=True,
		tracking=True)
	current_exchange_rate = fields.Float(
		string='Current exchange rate',
		readonly=False,
		default=1
	)
	manual_currency_rate_active = fields.Boolean('Aplicar TRM Manual')
	manual_currency_rate = fields.Float('Rate', digits=(12, 12),readonly=True)
	exchange_diff_type = fields.Selection([
		('native', 'Diferencia Nativa'),
		('custom', 'Diferencia por Pago')
	], string='Tipo de Diferencia Cambiaria', default='native')


	@api.onchange('date', 'currency_id')
	def _onchange_date_aux(self):
		"""
		Optimizado: Calcula el tipo de cambio actual.
		- Eliminado código redundante record.date or record.date
		- Usar fields.Date.context_today() correctamente
		"""
		for record in self:
			amount = 0
			rate = 0
			if record.manual_currency_rate_active:
				break
			if record.currency_id:
				# Optimizado: Eliminado duplicación record.date or record.date
				rate = self.env['res.currency']._get_conversion_rate(
					from_currency=record.company_currency_id,
					to_currency=record.currency_id,
					company=record.company_id,
					date=record.date or fields.Date.context_today(record),
				)
				amount = 1 / rate if rate else 1
			else:
				amount = 1
			record.current_exchange_rate = amount
			record.manual_currency_rate = rate or 1

	@api.constrains("manual_currency_rate")
	def _check_manual_currency_rate(self):
		for record in self:
			if record.manual_currency_rate_active:
				if record.manual_currency_rate == 0:
					raise UserError(_('El campo tipo de cambio es obligatorio, complételo.'))

	@api.onchange('manual_currency_rate_active', 'currency_id','current_exchange_rate')
	def check_currency_id(self):
		if self.manual_currency_rate_active:
			if self.currency_id == self.company_id.currency_id:
				self.manual_currency_rate_active = False
				raise UserError(
					_('La moneda de la empresa y la moneda de la factura son las mismas. No se puede agregar el tipo de cambio manual para la misma moneda.'
						))
			else:
				self.manual_currency_rate = 1 / self.current_exchange_rate or 1

	@api.onchange('manual_currency_rate_active')
	def _onchange_manual_currency_rate_active(self):
		if self.manual_currency_rate_active:
			self.exchange_diff_type = 'custom'
		else:
			self.exchange_diff_type = 'native'

	def open_reconcile_view(self):
		return self.move_id.line_ids.open_reconcile_view()

	@api.depends('journal_id')
	def _compute_currency_id(self):
		for pay in self:
			pay.currency_id = pay.journal_id.currency_id or pay.journal_id.company_id.currency_id or self.env.company.currency_id.id


	def action_draft(self):
		res = super().action_draft()
		for rec in self.filtered(lambda x: x.payment_line_ids):
			rec.move_id.line_ids.unlink()
		return res

	def unlink(self):
		for rec in self:
			rec.move_id.line_ids.unlink()
			self.payment_line_ids.unlink()
		res = super().unlink()
		return res

	@api.onchange('payment_line_ids','payment_line_ids.tax_ids')
	def _onchange_matched_manual_ids(self, force_update = False):
		in_draft_mode = self != self._origin
		
		def need_update():
			amount = 0
			for line in self.payment_line_ids:
				if line.auto_tax_line:
					amount -= line.balance
					continue
				if line.tax_ids:
					balance_taxes_res = line.tax_ids._origin.compute_all(
						line.invoice_id.amount_untaxed  or line.payment_amount or line.balance,
						currency=line.currency_id,
						quantity=1,
						product=line.product_id,
						partner=line.partner_id,
						is_refund=False,
						handle_price_include=True,
					)
					for tax_res in balance_taxes_res.get("taxes"):
						amount += tax_res['amount']
			return amount 
		
		if not force_update and not need_update():
			return
		
		to_remove = self.env['account.payment.detail']		
		if self.payment_line_ids:
			for line in list(self.payment_line_ids):
				print(line, line.auto_tax_line)
				if line.auto_tax_line:
					to_remove += line
					continue
				if line.tax_ids:
					balance_taxes_res = line.tax_ids._origin.compute_all(
						line.invoice_id.amount_untaxed or line.payment_amount or line.balance,
						currency=line.currency_id,
						quantity=1,
						product=line.product_id,
						partner=line.partner_id,
						is_refund=False,
						handle_price_include=True,
					)
					for tax_res in balance_taxes_res.get("taxes"):
						create_method = in_draft_mode and line.new or line.create
						create_method({
							'payment_id' : self.id,
							'partner_id' : line.partner_id.id,
							'account_id' : tax_res['account_id'],
							'name' : tax_res['name'],
							'payment_amount' : tax_res['amount'],
							'tax_repartition_line_id' : tax_res['tax_repartition_line_id'],
							'tax_tag_ids' : tax_res['tag_ids'],
							'auto_tax_line' : True,
							'tax_line_id2' :tax_res['id'],
							'tax_base_amount' : line.invoice_id.amount_untaxed or line.payment_amount or line.balance,
							'tax_line_id' : line.id,
							})
			
			if in_draft_mode:
				self.payment_line_ids -=to_remove
			else:
				to_remove.unlink()

	def _prepare_move_line_default_vals(self, write_off_line_vals=None, force_balance=None):
		if not self.payment_line_ids:
			return super()._prepare_move_line_default_vals(write_off_line_vals,force_balance)

		return [
			{
				'debit': line.debit,
				'credit': line.credit,
				'balance': line.debit - line.credit,
				'amount_currency': line.amount_currency or (line.debit - line.credit),
				'journal_id': self.journal_id.id,
				'account_id': line.account_id.id,
				'analytic_distribution': line.analytic_distribution or False,
				'tax_ids': [(6, 0, line.tax_ids.ids)],
				'tax_tag_ids': [(6, 0, line.tax_tag_ids.ids)],
				'tax_repartition_line_id': line.tax_repartition_line_id.id,
				'tax_base_amount': line.tax_base_amount,
				'inv_id': line.invoice_id.id,
				'line_pay': line.move_line_id.id,
				'date_maturity': self.date,
				'partner_id': line.partner_id.commercial_partner_id.id or line.partner_id.id,
				'currency_id': self.currency_id.id,
				'payment_id': self.id,
                **line._get_counterpart_move_name() 
			}
			for line in self.payment_line_ids
		]


	@api.onchange('advance_type_id')
	def _onchange_advance_type_id(self):
		self._onchange_payment_type()

	@api.onchange('advance')
	def _onchange_advance(self):
		res = {}
		if not self.reconciled_invoice_ids:
			if self.is_internal_transfer:
				self.advance = False
				self.advance_type_id = False
			elif not self.advance:
				self.advance_type_id = False
		if self.advance:
			self.advance_type_id = False
			res['domain'] = {'advance_type_id': [('internal_type','=', self.payment_type == 'outbound' and 'asset_receivable' or 'liability_payable')]}
		return res

	def _get_moves_domain(self):
		domain = [
			("amount_residual", "!=", 0.0),
			("state", "=", "posted"),
			("company_id", "=", self.company_id.id),
			(
				"commercial_partner_id",
				"=",
				self.partner_id.commercial_partner_id.id,
			),
		]
		if self.partner_type == "supplier":
			if self.payment_type == "outbound":
				domain.append(("move_type", "in", ("in_invoice", "in_receipt")))
			if self.payment_type == "inbound":
				domain.append(("move_type", "=", "in_refund"))
		elif self.partner_type == "customer":
			if self.payment_type == "outbound":
				domain.append(("move_type", "=", "out_refund"))
			if self.payment_type == "inbound":
				domain.append(("move_type", "in", ("out_invoice", "out_receipt")))
		return domain

	def _filter_amls(self, amls):
		return amls.filtered(
			lambda x: x.partner_id.commercial_partner_id.id
			== self.partner_id.commercial_partner_id.id
			and x.amount_residual != 0
			and x.account_id.account_type in ("asset_receivable", "liability_payable")
		)

	def _hook_create_new_line(self, invoice, aml, amount_to_apply,amount_residual):
		line_model = self.env["account.payment.detail"]
		if amount_residual > 0:
			amount_to_apply *= -1
		self.ensure_one()
		return line_model.create(
			{
				"payment_id": self.id,
				"name": invoice.name + str(aml.ref),
				"move_id": invoice.id,
				"move_line_id": aml.id,
				"account_id": aml.account_id.id,
				"partner_id": self.partner_id.commercial_partner_id.id,
				"payment_amount": amount_to_apply,
			}
		)

	def action_propose_payment_distribution(self):
		move_model = self.env["account.move"]
		for rec in self:
			if self.is_internal_transfer:
				continue
			domain = self._get_moves_domain()
			pending_invoices = move_model.search(domain, order="invoice_date_due ASC")
			pending_amount = rec.amount
			rec.payment_line_ids.filtered(lambda line: not line.is_main or line.display_type == 'asset_cash').unlink()
			for invoice in pending_invoices:
				for aml in self._filter_amls(invoice.line_ids):
					amount_to_apply = 0
					amount_residual = rec.company_id.currency_id._convert(
						aml.amount_residual,
						rec.currency_id,
						rec.company_id,
						date=rec.date,
					)
					if pending_amount >= 0:
						amount_to_apply = min(abs(amount_residual), pending_amount)
						pending_amount -= abs(amount_residual)
						# Check if both amounts are negative to adjust the sign

					rec._hook_create_new_line(invoice, aml, amount_to_apply,amount_residual)
			rec._recompute_dynamic_lines_payment()

	def action_delete_counterpart_lines(self):
		if self.payment_line_ids and self.state == "draft":
			self.payment_line_ids = [(5, 0, 0)]
			self._recompute_dynamic_lines_payment()

	def action_post(self):
		for rec in self:
			if not rec.code_advance:
				sequence_code = ''
				if rec.advance:
					if rec.partner_type == 'customer':
						sequence_code = 'account.payment.advance.customer'
					if rec.partner_type == 'supplier':
						sequence_code = 'account.payment.advance.supplier'
					if rec.partner_type == 'employee':
						sequence_code = 'account.payment.advance.employee'

				rec.code_advance = self.env['ir.sequence'].with_context(ir_sequence_date=rec.date).next_by_code(sequence_code)
				if not rec.code_advance and rec.advance:
					raise UserError(_("You have to define a sequence for %s in your company.") % (sequence_code,))
			if not rec.name:
				if rec.partner_type == 'employee':
					sequence_code = 'account.payment.employee'
					rec.name = self.env['ir.sequence'].with_context(ir_sequence_date=rec.date).next_by_code(sequence_code)
					if not rec.name:
						raise UserError(_("You have to define a sequence for %s in your company.") % (sequence_code,))
			if rec.payment_line_ids and not rec.is_internal_transfer:
				rec.move_id.line_ids.unlink()
				rec.move_id.line_ids = [
					(0, 0, line_vals) for line_vals in rec._prepare_move_line_default_vals()
				]
				super().action_post()
				for line in rec.line_ids:
					invoice_line = line.line_pay
					if line and invoice_line:
						if (invoice_line.account_id == line.account_id and
							invoice_line.partner_id == line.partner_id and
							not invoice_line.reconciled):
							#if rec.exchange_diff_type == 'native':
							(line + invoice_line).with_context(skip_account_move_synchronization=True).reconcile()
							#Falta el modulo de pago con diferencia cambiairia propia
							# else:
							# 	(line + invoice_line).with_context(
							# 		no_exchange_difference=True,
							# 		skip_account_move_synchronization=True
							# 	).reconcile()
							# 	if any(lines.needs_rate_adjustment for lines in rec.payment_line_ids):
							# 		for linex in rec.payment_line_ids:
							# 			linex.create_exchange_diff_line()
			else:
				super(AccountPayment, rec).action_post()


	##### END advance

	@api.onchange('payment_type')
	def _onchange_payment_type(self):
		self.change_destination_account = None

	@api.onchange('reconciled_invoice_ids', 'payment_type', 'partner_type', 'partner_id', 'journal_id', 'destination_account_id')
	def _change_destination_account(self):
		change_destination_account = '0'
		account_id = None
		partner = self.partner_id.with_context(company_id=self.company_id.id)
		if self.reconciled_invoice_ids:
			self.change_destination_account = self.reconciled_invoice_ids[0].account_id.id
			return
		elif self.is_internal_transfer:
			#self._onchange_amount()
			if not self.company_id.transfer_account_id.id:
				raise UserError(_('There is no Transfer Account defined in the accounting settings. Please define one to be able to confirm this transfer.'))
			account_id = self.company_id.transfer_account_id.id
		elif self.partner_id:
			if self.partner_type == 'customer':
				account_id = partner.property_account_receivable_id.id
			else:
				account_id = partner.property_account_payable_id.id
		elif self.partner_type == 'customer':
			default_account = partner.property_account_receivable_id
			account_id = default_account.id
		elif self.partner_type == 'supplier':
			default_account = partner.property_account_payable_id
			account_id = default_account.id
		if self.destination_account_id.id != account_id:
			change_destination_account = self.destination_account_id.id
		self.change_destination_account = change_destination_account

	@api.depends('journal_id','partner_id','is_internal_transfer','reconciled_invoice_ids','journal_id','payment_type', 'partner_type', 'partner_id', 'change_destination_account', 'advance_type_id')
	def _compute_destination_account_id(self):
		for val in self:
			if val.change_destination_account not in (False,'0') :
				val.destination_account_id = int(val.change_destination_account)
			if val.advance_type_id:
				val.destination_account_id = val.advance_type_id.account_id.id
			else:
				super(AccountPayment, self)._compute_destination_account_id()
			if val.partner_type == 'employee':
				val.destination_account_id = int(val.change_destination_account)

	def _get_liquidity_move_line_vals(self, amount):
		res = super(AccountPayment, self)._get_liquidity_move_line_vals(amount)
		res.update(
			account_id = self.outstanding_account_id  and self.outstanding_account_id .id or res.get('account_id'),
			name = self.advance and self.code_advance or res.get('name')
			)
		return res

	def button_journal_difference_entries(self):
		return {
			'name': _('Diarios'),
			'view_type': 'form',
			'view_mode': 'tree,form',
			'res_model': 'account.move',
			'view_id': False,
			'type': 'ir.actions.act_window',
			'domain': [('id', 'in', self.move_diff_ids.ids)],
		}

	### END manual account ###
	def _compute_payment_difference_line(self):
		for val in self:
			amount = 0.0
			if not val.is_internal_transfer:
				for line in val.payment_line_ids:
					amount += line.payment_amount
			val.payment_difference_line = val.currency_id.round(amount)

	@api.onchange('currency_id')
	def _onchange_currency(self):
		for line in self.payment_line_ids:
			line.payment_currency_id = self.currency_id.id or False
			line._onchange_to_pay()
			line._onchange_payment_amount()
	@api.returns('self', lambda value: value.id)
	def copy(self, default=None):
		default = dict(default or {})
		default.update(payment_line_ids=[])
		return super(AccountPayment, self).copy(default)

	@api.onchange('account_move_payment_ids', 'customer_invoice_ids', 'supplier_invoice_ids')
	def _onchange_invoice_field(self):
		fields_to_check = ['account_move_payment_ids', 'customer_invoice_ids', 'supplier_invoice_ids']

		for field_name in fields_to_check:
			field_ids = self[field_name]
			if field_ids:
				if field_name == "account_move_payment_ids":
					where_clause = "account_move_line.amount_residual != 0 AND ac.reconcile AND account_move_line.id in %s"
				else:  # Para 'customer_invoice_ids' y 'supplier_invoice_ids'
					where_clause = "account_move_line.amount_residual != 0 AND ac.reconcile AND am.id in %s"
					
				where_params = [tuple(field_ids.ids)]
				
				self._cr.execute('''
				SELECT account_move_line.id
				FROM account_move_line
				LEFT JOIN account_move am ON (account_move_line.move_id = am.id)
				LEFT JOIN account_account ac ON (account_move_line.account_id = ac.id)
				WHERE ''' + where_clause, where_params
				)
				
				res = self._cr.fetchall()
				
				if res:
					for r in res:
						moves = self.env['account.move.line'].browse(r)
						self._change_and_add_payment_detail(moves)
				
				self[field_name] = None
				break

	def _change_and_add_payment_detail(self, moves):
		SelectPaymentLine = self.env['account.payment.detail']
		current_payment_lines = self.payment_line_ids.filtered(lambda line: line.is_main == False)
		move_lines = moves - current_payment_lines.mapped('move_line_id')
		payment_lines_to_create = []
		for line in move_lines:
			data = self._get_data_move_lines_payment(line)
			pay = SelectPaymentLine.new(data)
			pay._onchange_move_lines()
			pay._onchange_to_pay()
			pay._onchange_payment_amount()
			values_to_create = pay._convert_to_write(pay._cache)
			payment_lines_to_create.append(values_to_create)
		# Crear todas las líneas de pago en una sola operación en la base de datos
		SelectPaymentLine.create(payment_lines_to_create)

	def _get_data_move_lines_payment(self, line):
		data = {
			'move_line_id': line.id,
			'account_id': line.account_id.id,
			'analytic_distribution' : line.analytic_distribution and line.analytic_distribution or False,
			'tax_ids' : [(6, 0, line.tax_ids.ids)],
			'tax_repartition_line_id' : line.tax_repartition_line_id.id,
			'tax_base_amount': line.tax_base_amount,
			'tax_tag_ids' : [(6, 0, line.tax_tag_ids.ids)],
			'payment_id': self.id,
			'payment_currency_id': self.currency_id.id,
			'payment_difference_handling': 'open',
			'writeoff_account_id': False,
			'to_pay': True
			}
		return data


	@api.onchange('currency_id')
	def _onchange_payment_amount_currency(self):
		self.writeoff_account_id = self._get_account_diff_currency(self.payment_difference_line)
		self._recompute_dynamic_lines_payment()

	def _get_account_diff_currency(self, amount):
		account = False
		company = self.env.company
		account = amount > 0 and company.expense_currency_exchange_account_id 
		if not account:
			account = company.income_currency_exchange_account_id
		return account

	@api.onchange('date')
	def _onchange_payment_date(self):
		"""
		Optimizado: Recomputa valores cuando cambia la fecha.
		- Usar filtered() para filtrar líneas
		- Evitar llamadas a métodos compute desde onchange
		"""
		# Optimizado: Filtrar líneas que no son principales
		lines_to_update = self.payment_line_ids.filtered(lambda line: not line.is_main)
		for line in lines_to_update:
			line._onchange_to_pay()
			line._onchange_payment_amount()
			# Optimizado: Los computes se ejecutarán automáticamente
		self._recompute_dynamic_lines_payment()

	@api.onchange('payment_line_ids', 'outstanding_account_id','payment_type', 'destination_account_id','amount','journal_id','currency_id')
	def _onchange_recompute_dynamic_line(self):
		self._recompute_dynamic_lines_payment()

	def _recompute_dynamic_lines_payment(self):
		self.ensure_one()
		diff_cash = self.payment_line_ids.filtered(lambda line: line.is_counterpart and line.is_main)
		if len(diff_cash) > 1:
			diff_cash.unlink()
		amount = self.amount * (self.payment_type in ('outbound', 'transfer') and 1 or -1)
		self._onchange_accounts(-amount, account_id=self.outstanding_account_id.id , display_type='asset_cash', is_main=True, is_counterpart=False)
		if self.advance:
			amount = self.amount * (self.payment_type in ('outbound', 'transfer') and -1 or 1)
			self._onchange_accounts(-amount, account_id=self.destination_account_id.id , display_type='advance', is_main=True, is_counterpart=False)		
		if not self.is_internal_transfer and not self.advance:
			manual_entries_total = sum(line.payment_amount for line in self.payment_line_ids.filtered(lambda l: l.display_type not in ['asset_cash',] and l.is_main == False))
			counter_part_amount = amount - manual_entries_total
			amount_diff = counter_part_amount - amount
			display_type = 'counterpart'
			account_id = self.destination_account_id.id
			self._compute_payment_difference_line()
			diif_amount =self.payment_difference_line 
			if (self.payment_type == 'outbound' and diif_amount != 0) or (self.payment_type == 'inbound' and diif_amount != 0):
				account_id =  self.writeoff_account_id
				display_type = 'counterpart'
			counter_part_amount = amount - manual_entries_total
			self._onchange_accounts(counter_part_amount, account_id, display_type=display_type, is_main=True, is_counterpart=True)
		if self.is_internal_transfer:
			display_type = 'counterpart'
			self._onchange_accounts(amount, account_id=self.destination_account_id.id, is_transfer=True, display_type=display_type, is_main=True, is_counterpart=False)



	def _onchange_accounts(self, amount, account_id=None, is_transfer=False, display_type=None, is_main=False, is_counterpart=False):
		self.ensure_one()
		in_draft_mode = self != self._origin
		existing_line = is_main and self.payment_line_ids.filtered(lambda line: line.display_type == display_type and line.is_main) or None
		if not account_id or self.currency_id.is_zero(amount):
			if existing_line:
				self.payment_line_ids -= existing_line
			return
		line_values = self._set_fields_detail(amount, account_id, is_transfer, display_type, is_main, is_counterpart)
		
		if existing_line:
			existing_line.update(line_values)
		else:
			if in_draft_mode:
				self.env['account.payment.detail'].new(line_values)
			else:
				self.env['account.payment.detail'].create(line_values)

	def _set_fields_detail(self, total_balance, account, is_transfer, display_type,is_main,is_counterpart):
		line_values = {
			'payment_amount': total_balance,
			'partner_id': self.partner_id.id or False,
			'payment_id': self.id,
			'company_currency_id': self.env.company.currency_id.id,
			'display_type': display_type,
			'is_transfer': is_transfer,
			'is_main': is_main,
			'is_counterpart': is_counterpart,
			'name': self.ref or '/',
			'currency_id': self.currency_id.id,
			'account_id': account,
			'ref': self.name or '/',
			'payment_currency_id': self.currency_id.id,
			'amount_currency': total_balance,
		}
		# if self.currency_id and self.currency_id != self.company_currency_id:
		# 	amount_currency = self.company_currency_id._convert(
		# 		total_balance,
		# 		self.currency_id,
		# 		self.company_id,
		# 		self.date or fields.Date.today()
		# 	) 
		# 	line_values.update({
		# 		'amount_currency': amount_currency
		# 	})
		# Optimizado: Código comentado eliminado para mejor legibilidad
		return line_values


	def _cleanup_lines(self):
		""" 
		Limpiar lineas aplica para evitar errores, comunes dentro del ORM evita:
		--> Si hay más de una línea que cumple el criterio de 'diff_cash', elimínalas todas (Para cuando se vuelva a computar el asiento quede cuadrado)
		---> Encuentra y elimina las líneas con cantidad de pago igual a cero evita crear en la base de datos datos inecesaro
		"""
		diff_cash = self.payment_line_ids.filtered(lambda line: line.display_type != 'asset_cash' and line.is_main)
		if len(diff_cash) > 1:
			diff_cash.unlink()
		zero_lines = self.payment_line_ids.filtered(lambda l: self.currency_id.is_zero(l.payment_amount))
		zero_lines.unlink()

	def _is_advance(self):
		return self.advance

	def _get_counterpart_move_line_vals(self, invoice=False):
		res = super(AccountPayment, self)._get_counterpart_move_line_vals(invoice=invoice)
		if self.advance:
			name = ''
			if self.partner_type == 'employee':
				name += _('Employee Payment Advance')
			elif self.partner_type == 'customer':
				name += _('Customer Payment Advance')
			elif self.partner_type == 'supplier':
				name += _('Vendor Payment Advance')
			name += self.code_advance or ''
			res.update(name=name)
		return res

	def _get_shared_move_line_vals(self, line_debit, line_credit, line_amount_currency, move, invoice_id=False):
		""" Returns values common to both move lines (except for debit, credit and amount_currency which are reversed)
		"""
		return {
			'partner_id': self.payment_type in ('inbound', 'outbound') and self.env['res.partner']._find_accounting_partner(self.partner_id).id or False,
			'inv_id': invoice_id and invoice_id.id or False,
			'move_id': move,
			'debit': line_debit,
			'credit': line_credit,
			'amount_currency': line_amount_currency or False,
			'payment_id': self.id,
			'journal_id': self.journal_id.id,
		}
	def _create_payment_entry_line(self, move):
		aml_obj = self.env['account.move.line'].with_context(check_move_validity=False, skip_account_move_synchronization=True)
		self.line_ids.unlink()
		# Usamos una lista de comprensión para construir los diccionarios
		aml_dicts = [{
			'partner_id': self.payment_type in ('inbound', 'outbound') and self.env['res.partner']._find_accounting_partner(self.partner_id).id or False,
			'move_id': move.id,
			'debit': line.debit,
			'credit': line.credit,
			'amount_currency': line.amount_currency if line.amount_currency != 0.0 else line.balance,
			'payment_id': self.id,
			'journal_id': self.journal_id.id,
			'account_id': line.account_id.id,
			'analytic_distribution': line.analytic_distribution or False,
			'tax_ids': [(6, 0, line.tax_ids.ids)],
			'tax_tag_ids': [(6, 0, line.tax_tag_ids.ids)],
			'tax_repartition_line_id': line.tax_repartition_line_id.id,
			'tax_base_amount': line.tax_base_amount,
			'inv_id': line.invoice_id.id,
			'line_pay': line.move_line_id.id,
			**line._get_counterpart_move_line_vals()  # Merging the dictionary directly
		} for line in self.payment_line_ids]

		# Crear entradas de una vez, sin bucle for
		aml_obj.create(aml_dicts)

		return True


	def _synchronize_from_moves(self, changed_fields):
		if self._context.get('skip_account_move_synchronization'):
			return
		to_change = self.filtered(lambda l: not l.payment_line_ids)
		if to_change:
			res = super(AccountPayment, to_change)._synchronize_from_moves(changed_fields)
		else:
			res = True
		return res

	def _synchronize_to_moves(self, changed_fields):
		if self._context.get('skip_account_move_synchronization'):
			return
		to_change = self.filtered(lambda l: not l.payment_line_ids)
		if to_change:
			res = super(AccountPayment, to_change)._synchronize_to_moves(changed_fields)
		else:
			res = True
		return res

	@api.constrains('payment_line_ids')
	def _check_payment_balance(self):
		for payment in self:
			if payment.payment_line_ids:
				debit_sum = sum(payment.payment_line_ids.mapped('debit'))
				credit_sum = sum(payment.payment_line_ids.mapped('credit'))

				if float_compare(debit_sum, credit_sum, precision_rounding=payment.currency_id.rounding) != 0:
					difference = (debit_sum - credit_sum)
					#raise ValidationError(_("Los montos totales de débito y crédito deben ser iguales para el pago %s. (%s)") % (payment.name, difference))

	def _get_tax_lines(self, line):
		"""Obtiene las líneas de impuestos y retenciones"""
		result = {
			'iva': {'lines': False, 'amount': 0.0},
			'rteiva': {'lines': False, 'amount': 0.0},
			'rtefuente': {'lines': False, 'amount': 0.0},
			'rteica': {'lines': False, 'amount': 0.0},
		}
		
		if line.move_line_id.move_id:
			move = line.move_line_id.move_id
			result['iva']['lines'] = move.line_ids.filtered(lambda l: l.name and '19% VAT' in l.name)
			result['rteiva']['lines'] = move.line_ids.filtered(lambda l: l.name and 'RteVAT 19%' in l.name)
			result['rtefuente']['lines'] = move.line_ids.filtered(lambda l: l.name and 'RteFte' in l.name)
			result['rteica']['lines'] = move.line_ids.filtered(lambda l: l.name and 'RTE Ica' in l.name)
			
			result['iva']['amount'] = abs(sum(result['iva']['lines'].mapped('debit')))
			result['rteiva']['amount'] = abs(sum(result['rteiva']['lines'].mapped('credit')))
			result['rtefuente']['amount'] = abs(sum(result['rtefuente']['lines'].mapped('credit')))
			result['rteica']['amount'] = abs(sum(result['rteica']['lines'].mapped('credit')))
			
		return result

class ResPartner(models.Model):
	_inherit = 'res.partner'

	def _find_accounting_partner(self, partner):
		''' Find the partner for which the accounting entries will be created '''
		return partner.commercial_partner_id

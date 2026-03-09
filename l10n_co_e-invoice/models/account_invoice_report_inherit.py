# -*- coding: utf-8 -*-
from odoo import api, fields, models, _

class AccountInvoiceReportInherit(models.Model):
	_inherit = "account.invoice.report"

	diancode_id = fields.Many2one('dian.document', string='Código DIAN')

	_depends = {
		'account.move': ['diancode_id'],
	}
	
	def _select(self):
		return  super(AccountInvoiceReportInherit, self)._select() + ", move.diancode_id as diancode_id"

	def _group_by(self):
		return super(AccountInvoiceReportInherit, self)._group_by() + ", move.diancode_id"
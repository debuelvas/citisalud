# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.tools.translate import _


class AccountMoveReversalInherit(models.TransientModel):
	"""
	Account move reversal wizard, it cancel an account move by reversing it.
	"""
	_inherit = 'account.move.reversal'

	def _prepare_default_reversal(self, move):

		vals = super(AccountMoveReversalInherit, self)._prepare_default_reversal(move)
		vals.update({
			'invoice_origin': move.name,
			'diancode_id': None,
			'state_dian_document': '',
			'shipping_response':'',
			'response_document_dian':'',
			'email_response':'',
			'response_message_dian':'',
			'debit_origin_id': False,
			'QR_code': None,
			'cufe':'',
			'xml_response_dian':'',
			'state_contingency':'',
			'contingency_invoice_number':'',
			'count_error_DIAN': None,
			'in_contingency_4': False,
			'exists_invoice_contingency_4': None,
			'archivo_xml_invoice': None,
			'xml_adjunto_ids':None
		})

		return vals










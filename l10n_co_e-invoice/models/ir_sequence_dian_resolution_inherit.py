# -*- coding: utf-8 -*-
from odoo import api, fields, models, _

class IrSequenceDianResolutionInherit(models.Model):
	_inherit = 'ir.sequence.dian_resolution'

	technical_key = fields.Char(string="Clave técnica", required = True, default="")


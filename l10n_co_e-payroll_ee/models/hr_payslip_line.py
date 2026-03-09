# -*- coding: utf-8 -*-
from odoo import api, fields, models, _, tools

class HrPayslipLine(models.Model):
    _inherit = 'hr.payslip.line'

    days_qty = fields.Integer('Dias Calculados')
    calculated_percentage = fields.Float('% Calculado')
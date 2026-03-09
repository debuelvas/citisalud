from odoo import fields, models, api


class HrPayrollPeriod(models.Model):
    _name = 'hr.payroll.period'
    _description = 'Hr Payroll Period'

    code = fields.Char()
    name = fields.Char()

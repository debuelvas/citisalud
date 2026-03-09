from odoo import _, api, fields, models

class HrSalaryRule(models.Model):
    _name = "hr.salary.rule"
    _inherit = ["hr.salary.rule", "hr.salary.rule.abstract"]

    leave_id = fields.Many2one('hr.leave.type', string="Tipo de incapacidad")
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.safe_eval import safe_eval

class HrSalaryRule(models.AbstractModel):
    _name = "hr.salary.rule.abstract"
    _description = "Model Abstract for hr salary rule"

    deduccion_rule_id = fields.Many2one('hr.deduct.rule', string='Tipo Deducción')
    devengado_rule_id = fields.Many2one('hr.accrued.rule', string='Tipo Devengado')
    type_inability_id = fields.Many2one('hr.type.inability', string='Tipo de Incapacidad')
    type_overtime_id = fields.Many2one('hr.type.overtime', string='Tipo de Hora Extra')
    type_incapacidad = fields.Selection([
        ('1', 'Común'),
        ('2', 'Profesional'),
        ('3', 'Laboral'),
    ], string="Type Incapacity", default="1")


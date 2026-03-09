from odoo import fields, models, api


class HrTypeContract(models.Model):
    _name = 'hr.type.contract'
    _description = 'Type of Contract'

    code = fields.Char()
    name = fields.Char()

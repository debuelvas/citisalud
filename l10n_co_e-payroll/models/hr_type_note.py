from odoo import fields, models, api


class HrTypeNote(models.Model):
    _name = 'hr.type.note'
    _description = 'Description'

    code = fields.Char()
    name = fields.Char()

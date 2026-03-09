from odoo import fields, models, api


class HrTypeWorker(models.Model):
    _name = 'hr.type.worker'
    _description = 'Type of Worker'

    code = fields.Char()
    name = fields.Char()

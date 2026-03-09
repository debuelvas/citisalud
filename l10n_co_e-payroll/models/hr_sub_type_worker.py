from odoo import fields, models, api


class HrSubTypeWorker(models.Model):
    _name = 'hr.sub.type.worker'
    _description = 'Sub Type of Worker'

    code = fields.Char()
    name = fields.Char()

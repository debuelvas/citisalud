from odoo import api, fields, models

TYPE_COMPANY = [("pub", "Pública"), ("prv", "Privada"), ("mix", "Mixta")]


class ResPartner(models.Model):
    _inherit = "res.partner"

    type_company = fields.Selection(string="Tipo de empresa", selection=TYPE_COMPANY)

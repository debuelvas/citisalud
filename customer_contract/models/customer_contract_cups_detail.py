from odoo import api, fields, models


class CustomerContractCupsDetail(models.Model):
    _name = "customer.contract.cups.detail"
    _description = "Detalle de CUPS"
    _order = "start_date"

    cups_id = fields.Many2one(comodel_name="customer.contract.cups", string="CUPS")
    start_date = fields.Date(string="Inicio", required=True)
    end_date = fields.Date(string="Fin", required=True)
    soat_amount = fields.Float(string="SOAT", required=True)
    own_amount = fields.Float(string="Propio", required=True)

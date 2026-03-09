from odoo import api, fields, models

TYPE = [
    ("CDP", "Certificado de disponibilidad presupuestal"),
    ("RP", "Registro Presupuestal de Compromiso"),
]


class CustomerContractReportBudget(models.Model):
    _name = "customer.contract.report.budget"
    _description = "Certificados y registros presupuestales"
    _order = "id"

    customer_contract_id = fields.Many2one(
        comodel_name="customer.contract", string="Contrato de cliente", required=True
    )
    type = fields.Selection(string="Tipo", selection=TYPE, required=True)
    name = fields.Char(string="Número", required=True)
    amount = fields.Float(string="Monto", required=True)
    file = fields.Binary(string="Documento", required=True)

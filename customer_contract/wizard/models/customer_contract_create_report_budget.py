from odoo import api, fields, models

TYPE = [
    ("CDP", "Certificado de disponibilidad presupuestal"),
    ("RP", "Registro Presupuestal de Compromiso"),
]


class CustomerContractCreateReportBudget(models.TransientModel):
    _name = "customer.contract.create.report.budget"
    _description = "Creador de certificados y registros presupuestales"

    type = fields.Selection(string="Tipo", selection=TYPE, required=True)
    name = fields.Char(string="Número", required=True)
    amount = fields.Float(string="Monto", required=True)
    file = fields.Binary(string="Documento", required=True)

    def create_customer_contract_report_budget(self):
        self.env["customer.contract.report.budget"].create(
            {
                "type": self.type,
                "name": self.name,
                "amount": self.amount,
                "file": self.file,
                "customer_contract_id": self._context["active_id"],
            }
        )

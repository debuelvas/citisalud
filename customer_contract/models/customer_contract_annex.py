from odoo import api, fields, models

TYPE = [("time", "Prórroga"), ("money", "Adición")]


class CustomerContractAnnex(models.Model):
    _name = "customer.contract.annex"
    _description = "Otrosí"
    _order = "id"

    customer_contract_id = fields.Many2one(
        comodel_name="customer.contract", string="Contrato de cliente", required=True
    )
    type = fields.Selection(string="Tipo", selection=TYPE, required=True)
    file = fields.Binary(string="Documento")
    date = fields.Date(string="Fecha")
    amount = fields.Float(string="Monto")
    sequence = fields.Integer(string="Secuencia")
    cdp_id = fields.Many2one(
        comodel_name="customer.contract.report.budget",
        string="CDP",
        domain="[('customer_contract_id','=',customer_contract_id),('type','=','CDP')]",
    )
    rp_id = fields.Many2one(
        comodel_name="customer.contract.report.budget",
        string="RP",
        domain="[('customer_contract_id','=',customer_contract_id),('type','=','RP')]",
    )

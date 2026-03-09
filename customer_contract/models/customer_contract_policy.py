from odoo import api, fields, models
from odoo.exceptions import ValidationError


class CustomerContractPolicy(models.Model):
    _name = "customer.contract.policy"
    _description = "Póliza de contratos de clientes"
    _order = "id"

    customer_contract_id = fields.Many2one(
        comodel_name="customer.contract", string="Contrato de cliente", required=True
    )
    number = fields.Char(string="Número", required=True)
    amount = fields.Float(string="Cuantía", required=True)
    expedition_date = fields.Date(string="Expedición", required=True)
    effective_date = fields.Date(string="Vigencia", required=True)
    rate = fields.Float(string="Porcentaje", required=True)
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Seguro",
        required=True,
        domain="[('is_company', '=', True)]",
    )
    description = fields.Char(string="Descripción", required=True)
    file = fields.Binary(string="Documento")
    receipt = fields.Binary(string="Recibo")

    @api.constrains("rate")
    def _check_description(self):
        for record in self:
            if not (0 <= record.rate <= 100):
                raise ValidationError(
                    "El porcentaje de la póliza debe estar dentro del rango de 0 - 100"
                )

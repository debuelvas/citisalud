from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.safe_eval import safe_eval


class HrContractPayment(models.Model):
    _inherit = "hr.contract"
    _description = "Contract Payment"

    payment_method_id = fields.Many2one("hr.payment.method", string="Método de Pago")
    way_pay_id = fields.Many2one("hr.way.pay", string="Forma de Pago")

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        way_pay_id = self.env["hr.way.pay"].search([("code", "=", "1")], limit=1)
        defaults.update({"way_pay_id": way_pay_id})
        return defaults

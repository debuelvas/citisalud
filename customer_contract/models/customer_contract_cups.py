from datetime import datetime

from odoo import api, fields, models

AMOUNT_TO_INVOICE = [("SOAT", "SOAT"), ("OWN", "PROPIO")]


class CustomerContractCups(models.Model):
    _name = "customer.contract.cups"
    _description = "CUPS"
    _order = "name"

    name = fields.Char(string="Nombre", required=True)
    product_id = fields.Many2one(comodel_name="product.product", string="Producto")
    description = fields.Text(string="Descripción", required=True)
    code = fields.Char(string="Código", required=True)
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Cliente",
        domain="[('is_company', '=', True)]",
        required=True,
    )
    amount_to_invoice = fields.Selection(
        string="Monto a facturar", selection=AMOUNT_TO_INVOICE, default="OWN"
    )
    detail_ids = fields.One2many(
        comodel_name="customer.contract.cups.detail", inverse_name="cups_id", string="Detalles"
    )

    def _get_price_from_date(self, date):
        if isinstance(date, datetime):
            date = date.date()

        def between_date(rec):
            return rec.start_date <= date <= rec.end_date

        def get_start_date(rec):
            return rec.start_date

        details = sorted(list(filter(between_date, self.detail_ids)), key=get_start_date)
        if not details:
            return 0
        else:
            detail = details[0]
            is_own = self.amount_to_invoice == "OWN"
            price_to_sel = detail.own_amount if is_own else detail.soat_amount
            return price_to_sel

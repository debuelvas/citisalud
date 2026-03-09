from odoo import _, api, fields, models, SUPERUSER_ID
from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tools import format_date, frozendict

class SaleAdvancePaymentInv(models.TransientModel):
    _inherit = 'sale.advance.payment.inv'

    def create_invoices(self):
        self._check_amount_is_positive()
        invoices = self._create_invoices(self.sale_order_ids)
        quantity_days = invoices.invoice_line_ids.treatment_id.treatment_days
        if invoices:
            for inv in invoices.invoice_line_ids:
                if inv.product_id and inv.product_id.type in ['consu', 'product']:
                    inv.write({'quantity': quantity_days})
            
        return self.sale_order_ids.action_view_invoice(invoices=invoices)
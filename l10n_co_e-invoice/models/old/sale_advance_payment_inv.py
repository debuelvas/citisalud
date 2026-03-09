from odoo import fields, models, api


class SaleAdvancePaymentInv(models.TransientModel):
    _inherit = 'sale.advance.payment.inv'

    def _create_invoice(self, order, so_line, amount):
        invoices = super(SaleAdvancePaymentInv, self)._create_invoice(order, so_line, amount)
        #invoices._change_invoice_line_ids()


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def _create_invoices(self, grouped=False, final=False, date=None):
        invoices = super()._create_invoices(grouped, final, date)
        for invoice in invoices:
            for line_id in invoices.invoice_line_ids:
                if line_id.product_id:
                    if invoice.fiscal_position_id and invoice.move_type != "entry":
                        taxes_id = invoice.return_data_wh_taxes()
                        invoice_tax = line_id.tax_ids.ids
                        invoice_tax.extend(taxes_id)
                        line_id.tax_ids = [(6, 0, invoice_tax)]


from odoo import api, fields, models


class ProductProduct(models.Model):
    _inherit = "product.product"

    cups_ids = fields.One2many(
        comodel_name="customer.contract.cups", inverse_name="product_id", string="CUPS"
    )

    # def _set_product_price(self):
    #     if not self.is_cums:
    #         super(ProductProduct, self)._set_product_price()

    # def _set_product_lst_price(self):
    #     if not self.is_cums:
    #         super(ProductProduct, self)._set_product_lst_price()

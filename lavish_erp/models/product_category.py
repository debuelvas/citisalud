# -*- coding: utf-8 -*-
# Copyright 2019 NMKSoftware
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

from odoo import SUPERUSER_ID, api, fields, models, _


class ProductCategory(models.Model):
    _inherit = 'product.category'

    active = fields.Boolean(string="Activo", default=True)

    taxes_ids = fields.Many2many(
        string="Customer taxes",
        comodel_name="account.tax",
        relation="product_category_sale_tax_rel",
        column1="product_id",
        column2="tax_id",
        domain="[('type_tax_use','=','sale')]",
        help="Taxes applied for sale.",
    )
    supplier_taxes_ids = fields.Many2many(
        string="Supplier taxes",
        comodel_name="account.tax",
        relation="product_category_purchase_tax_rel",
        column1="product_id",
        column2="tax_id",
        domain="[('type_tax_use','=','purchase')]",
        help="Taxes applied for purchase.",
    )

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    dian_brand = fields.Char(
        'Marca',
        help='Marca informó en los documentos electrónicos a la DIAN.'
    )
    dian_model = fields.Char(
        'Modelo',
        help='Modelo reportado en los documentos electrónicos a la DIAN.'
    )
    dian_customs_code = fields.Char(
        'Partida Arancel',
        help='Necesario principalmente para facturas de exportación.'
    )



class ProductUom(models.Model):
    _inherit = 'uom.uom'

    dian_country_code = fields.Char(
        'Codigo Pais',
        default=lambda self: self.env.company.country_id.code
    )
    dian_uom_id = fields.Many2one(
        'dian.uom.code', 'DIAN UoM'
    )
# -*- coding: utf-8 -*-

from odoo import models, fields

class ProductCategory(models.Model):
    _inherit = 'product.category'

    active = fields.Boolean(string="Activo", default=True)

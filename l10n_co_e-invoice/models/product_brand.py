# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

class ProductBrand(models.Model):
    _name = 'product.brand'
    _description = 'Modelo para las marcas de los productos'

    name = fields.Char(string="Nombre", required=True)
    active = fields.Boolean(string="Active", default=True)

    product_ids = fields.One2many(
        'product.template', 
        'brand_id', string = 'Productos')


    @api.constrains('name')
    def _check_brand_name(self):
        if self.search_count([('name', 'ilike', self.name)]) > 1:
            raise ValidationError('Ya hay una marca con este nombre')


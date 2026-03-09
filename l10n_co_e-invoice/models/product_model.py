# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.osv import  expression
class ProductModel(models.Model):
    _name = 'product.model'
    _description = 'Modelo para los modelos de los productos'

    name = fields.Char(string="Nombre", required=True)
    active = fields.Boolean(string="Active", default=True)

    product_ids = fields.One2many(
        'product.template', 
        'model_id', string = 'Productos')


    @api.constrains('name')
    def _check_model_name(self):
        if self.search_count([('name', 'ilike', self.name)]) > 1:
            raise ValidationError('Ya hay un modelo con este nombre')


class DianUomCode(models.Model):
    _name = 'dian.uom.code'
    _description = 'Unit of measure code defined from DIAN'

    name = fields.Char('Name')
    dian_code = fields.Char('DIAN code')

    def _get_complete_name(self):
        res = []
        for record in self:
            name = u'[%s] %s' % (record.dian_code or '', record.name)
            res.append((record.id, name))
        return res
    
    @api.depends('name', 'dian_code')
    def _compute_display_name(self):
        for template in self:
            template.display_name = False if not template.name else (
                '{}{}'.format(
                    template.dian_code and '[%s] ' % template.dian_code or '', template.name
                ))
    @api.model
    def _name_search(self, name, args=None, operator='ilike',
                     limit=100, name_get_uid=None,order=None):
        args = args or []
        if operator == 'ilike' and not (name or '').strip():
            domain = []
        else:
            domain = ['|', ('name', 'ilike', name),
                      ('dian_code', 'ilike', name)]
        return self._search(
            expression.AND([domain, args]),
            limit=limit, order=order,
            access_rights_uid=name_get_uid
        )

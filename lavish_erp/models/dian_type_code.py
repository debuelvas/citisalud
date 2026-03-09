# coding: utf-8
from odoo import api, fields, models, _
from odoo.osv import expression


class DianTypeCode(models.Model):
    _name = 'dian.type_code'
    _description = 'Representations, Obligations, Customs and' \
        ' Establishments defined by the DIAN'

    dian_code = fields.Char('DIAN code', required=True)
    name = fields.Char('Description', required=True)
    type = fields.Selection([('representation', 'Representación'),
                             ('obligation', 'Obligación'),
                             ('customs', 'Aduanas'),
                             ('establishment', 'Establecimiento')],
                            'Tipo valor',
                            required=True)
    is_required_dian = fields.Boolean('Válido para documentos electrónicos')

    def _get_complete_name(self):
        res = []
        for record in self:
            name = u'[%s] %s' % (record.dian_code, record.name)
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
            domain = ['|', ('dian_code', 'ilike', name),
                      ('name', 'ilike', name)]
        return self._search(
            expression.AND([domain, args]),
            limit=limit, order=order,
            access_rights_uid=name_get_uid
        )

class DianTaxType(models.Model):
    _name = 'dian.tax.type'
    _description = 'DIAN Tax Type'

    name = fields.Char('Name')
    description = fields.Char('Description')
    dian_code = fields.Char('DIAN code', required=True)
    retention = fields.Boolean('Withholding')

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

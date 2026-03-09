# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class FeCustomParameter(models.Model):
    """Parámetros Personalizados FE"""
    _name = 'fe.custom.parameter'
    _description = 'Parámetro Personalizado FE'
    _order = 'sequence, name'

    name = fields.Char(string='Nombre', required=True)
    technical_name = fields.Char(string='Nombre Técnico', required=True)
    description = fields.Text(string='Descripción')
    help_text = fields.Char(string='Ayuda')
    active = fields.Boolean(string='Activo', default=True)
    sequence = fields.Integer(string='Secuencia', default=10)

    parameter_type = fields.Selection([
        ('header', 'Encabezado'),
        ('line', 'Línea'),
        ('party', 'Terceros'),
        ('payment', 'Pago'),
        ('delivery', 'Entrega'),
        ('extension', 'Extensión'),
    ], string='Tipo', required=True, default='extension')

    data_type = fields.Selection([
        ('char', 'Texto'),
        ('text', 'Texto Largo'),
        ('integer', 'Entero'),
        ('float', 'Decimal'),
        ('date', 'Fecha'),
        ('datetime', 'Fecha/Hora'),
        ('boolean', 'Sí/No'),
        ('selection', 'Selección'),
    ], string='Tipo Dato', required=True, default='char')

    ubl_element_name = fields.Char(string='Elemento UBL')
    ubl_namespace = fields.Selection([
        ('cbc', 'cbc'),
        ('cac', 'cac'),
        ('ext', 'ext'),
        ('custom', 'custom'),
    ], string='Namespace', default='cbc')
    ubl_xpath = fields.Char(string='XPath')
    ubl_structure = fields.Text(string='Estructura JSON')

    required = fields.Boolean(string='Obligatorio', default=False)
    validation_regex = fields.Char(string='Regex')
    validation_error_message = fields.Char(string='Mensaje Error')
    selection_options = fields.Text(string='Opciones')

    apply_to_fe_types = fields.Selection([
        ('all', 'Todos'),
        ('01', 'Factura (01)'),
        ('02', 'Exportación (02)'),
        ('03', 'Contingencia (03)'),
        ('04', 'Importación (04)'),
    ], string='Aplica a', default='all')

    _sql_constraints = [
        ('technical_name_unique', 'UNIQUE(technical_name)', 'Nombre técnico debe ser único'),
    ]

    @api.constrains('technical_name')
    def _check_technical_name(self):
        import re
        for rec in self:
            if rec.technical_name and not re.match(r'^[a-z0-9_]+$', rec.technical_name):
                raise ValidationError('Nombre técnico: solo letras minúsculas, números y guión bajo')

    def generate_xml_element(self, value):
        """Genera elemento XML UBL"""
        self.ensure_one()
        if not value:
            return ''
        ns = self.ubl_namespace or 'cbc'
        elem = self.ubl_element_name or self.technical_name
        return f'<{ns}:{elem}>{value}</{ns}:{elem}>'


class FeCustomParameterValue(models.Model):
    """Valores de Parámetros por Factura"""
    _name = 'fe.custom.parameter.value'
    _description = 'Valor Parámetro FE'

    parameter_id = fields.Many2one('fe.custom.parameter', string='Parámetro', required=True, ondelete='cascade')
    invoice_id = fields.Many2one('account.move', string='Factura', required=True, ondelete='cascade')

    value_char = fields.Char(string='Texto')
    value_text = fields.Text(string='Texto Largo')
    value_integer = fields.Integer(string='Entero')
    value_float = fields.Float(string='Decimal')
    value_date = fields.Date(string='Fecha')
    value_datetime = fields.Datetime(string='Fecha/Hora')
    value_boolean = fields.Boolean(string='Booleano')
    value_selection = fields.Char(string='Selección')

    value = fields.Char(string='Valor', compute='_compute_value', inverse='_inverse_value')

    @api.depends('parameter_id.data_type', 'value_char', 'value_text', 'value_integer',
                 'value_float', 'value_date', 'value_datetime', 'value_boolean', 'value_selection')
    def _compute_value(self):
        for rec in self:
            if not rec.parameter_id:
                rec.value = False
                continue
            dt = rec.parameter_id.data_type
            if dt == 'char':
                rec.value = rec.value_char
            elif dt == 'text':
                rec.value = rec.value_text
            elif dt == 'integer':
                rec.value = str(rec.value_integer) if rec.value_integer else False
            elif dt == 'float':
                rec.value = str(rec.value_float) if rec.value_float else False
            elif dt == 'date':
                rec.value = str(rec.value_date) if rec.value_date else False
            elif dt == 'datetime':
                rec.value = str(rec.value_datetime) if rec.value_datetime else False
            elif dt == 'boolean':
                rec.value = 'true' if rec.value_boolean else 'false'
            elif dt == 'selection':
                rec.value = rec.value_selection
            else:
                rec.value = False

    def _inverse_value(self):
        for rec in self:
            if not rec.parameter_id or not rec.value:
                continue
            dt = rec.parameter_id.data_type
            val = rec.value
            if dt == 'char':
                rec.value_char = val
            elif dt == 'text':
                rec.value_text = val
            elif dt == 'integer':
                try:
                    rec.value_integer = int(val)
                except:
                    pass
            elif dt == 'float':
                try:
                    rec.value_float = float(val)
                except:
                    pass
            elif dt == 'date':
                rec.value_date = val
            elif dt == 'datetime':
                rec.value_datetime = val
            elif dt == 'boolean':
                rec.value_boolean = val.lower() in ('true', '1', 'yes', 'sí')
            elif dt == 'selection':
                rec.value_selection = val

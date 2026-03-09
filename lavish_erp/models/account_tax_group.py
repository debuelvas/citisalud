# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api, fields, models, _

TRIBUTES = [('01','IVA'), 
            ('02','IC'), 
            ('03','ICA'), 
            ('04','INC'), 
            ('05','ReteIVA'), 
            ('06','ReteFuente'),
            ('07','ReteICA'), 
            ('08','ReteCREE'), 
            ('20','FtoHorticultura'), 
            ('21','Timbre'),
            ('22','Bolsas'), 
            ('23','INCarbono'), 
            ('24','INCombustibles'),
            ('25','Sobretasa Combustibles'), 
            ('26','Sordicom'),
            ('ZY','No causa'),
            ('ZZ','Nombre de la figura tributaria')]

class AccountTaxGroup(models.Model):
    _inherit = 'account.tax.group'

    code = fields.Char(string="Identifier")
    description = fields.Char(string="Description")
    is_percent = fields.Boolean(string="Is percent", default=True)

class AccountTax(models.Model):
    _inherit = 'account.tax'
    
    tributes = fields.Selection(TRIBUTES, string="Tributo DIAN")
    codigo_dian = fields.Char(
        string='Código DIAN',
        #compute='_dian_detalle',store = True
    )

    nombre_dian = fields.Char(
        string='Nombre técnico DIAN',
        #compute='_dian_detalle',store = True
    )
    description_dian = fields.Char(
        string='Descripción DIAN',
        #compute='_dian_detalle',store = True
    )
    @api.depends('tributes')
    def _dian_detalle(self):
        """Optimizado: Usa diccionario para lookup O(1) en lugar de if-elif O(n)"""
        # Diccionario estático de códigos DIAN
        TRIBUTES_MAPPING = {
            '01': ('Impuesto de Valor Agregado', 'IVA'),
            '02': ('Impuesto al Consumo', 'IC'),
            '03': ('Impuesto de Industria, Comercio y Aviso', 'ICA'),
            '04': ('Impuesto Nacional al Consumo', 'INC'),
            '05': ('Retención sobre el IVA', 'ReteIVA'),
            '06': ('Retención sobre Renta', 'ReteRenta'),
            '07': ('Retención sobre el ICA', 'ReteICA'),
            '08': ('Impuesto al Consumo Departamental Porcentual', 'IC Porcentual'),
            '20': ('Cuota de Fomento Hortifrutícula', 'FtoHoticultura'),
            '21': ('Impuesto de Timbre', 'Timbre'),
            '22': ('Impuesto al Consumo de Bolsa Plástica', 'INC Bolsas'),
            '23': ('Impuesto Nacional al Carbono', 'INCarbono'),
            '24': ('Impuesto Nacional a los Combustibles', 'INCombustibles'),
            '25': ('Sobretasa a los combustibles', 'Sobretasa Combustibles'),
            '26': ('Contribución minoristas (Combustibles)', 'Sordicom'),
            '30': ('Impuesto al Consumo de Datos', 'IC Datos'),
            'ZZ': ('Otros Tributos, tasas, contribuciones, y similares', 'Nombre de la figura tributaria'),
        }

        for rec in self:
            code = rec.tributes
            if code in TRIBUTES_MAPPING:
                description, name = TRIBUTES_MAPPING[code]
            else:
                description = ''
                name = ''

            rec.codigo_dian = code
            rec.description_dian = description
            rec.nombre_dian = name

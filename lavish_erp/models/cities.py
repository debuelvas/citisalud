# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class Cities(models.Model):
    _inherit = "res.city"
    _description = 'Ciudades por departamento'
    
    code_zip = fields.Char(string='Código', size=10)
    code = fields.Char(string='Código', size=10)

class ResCountry(models.Model):
    _inherit = 'res.country'
	
    code_dian = fields.Char(string='Código del país para la DIAN')

class ResCountryState(models.Model):
    _inherit = 'res.country.state'
	
    code_dian = fields.Char(string='Código de provincia/departamento para la DIAN')

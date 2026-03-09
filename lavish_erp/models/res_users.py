# -*- coding: utf-8 -*-
from odoo import models, fields, api

class res_users(models.Model):
    _inherit = 'res.users'
    
    #Sucursal
    branch_ids = fields.Many2many('lavish.res.branch', string='Sucursal', ondelete='restrict')    
    #Firma
    signature_documents = fields.Binary(string='Firma lavish')
    #Firma autorizada para certificado laboral
    signature_certification_laboral = fields.Boolean('Firma autorizada para certificado laboral')
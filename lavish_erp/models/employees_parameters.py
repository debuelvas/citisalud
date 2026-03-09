# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from odoo.osv import expression
import datetime


# ÁREAS
class x_areas(models.Model):
    _name = 'lavish.areas'
    _description = 'Áreas'
    _order = 'code,name'

    code = fields.Char(string='Código', size=10, required=True)
    name = fields.Char(string='Nombre', required=True)

    def name_get(self):
        result = []
        for record in self:
            result.append((record.id, "{} | {}".format(record.code, record.name)))
        return result

# CARGOS
class x_job_title(models.Model):
    _name = 'lavish.job_title'
    _description = 'Cargos'
    _order = 'area_id,code,name'

    name = fields.Char(string='Nombre', required=True)
    area_id = fields.Many2one('lavish.areas', string='Área')
    code = fields.Char(string='Código', size=10, required=True)


    def name_get(self):
        result = []
        for record in self:
            result.append((record.id, "{} | {}".format(record.code, record.name)))
        return result

# GRUPOS DE TRABAJO
class x_work_groups(models.Model):
    _name = 'lavish.work_groups'
    _description = 'Grupos de Trabajo'
    
    name = fields.Char(string='Nombre', required=True)
    code = fields.Char(string='Código', size=10, required=True)


    def name_get(self):
        result = []
        for record in self:
            result.append((record.id, "{} | {}".format(record.code, record.name)))
        return result

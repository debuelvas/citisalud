from odoo import models, fields, api, _
from datetime import datetime, timedelta, date
from odoo.exceptions import UserError, ValidationError
import time

class hr_social_security_branches(models.Model):
    _name = 'hr.social.security.branches'
    _description = 'Sucursales seguridad social'

    code = fields.Char('Codigo', required=True)
    name = fields.Char('Nombre', required=True)
    company_id = fields.Many2one('res.company', string='Compañía', default=lambda self: self.env.company)

    _sql_constraints = [('change_code_uniq', 'unique(code,company_id)', 'Ya existe una sucursal de seguridad social con este código para esta compañía, por favor verificar')]

class hr_social_security_work_center(models.Model):
    _name = 'hr.social.security.work.center'
    _description = 'Centro de trabajo seguridad social'

    code = fields.Integer('Codigo', required=True)
    name = fields.Char('Nombre', required=True)
    branch_social_security_id = fields.Many2one('hr.social.security.branches', 'Sucursal seguridad social', required=True)
    company_id = fields.Many2one(related='branch_social_security_id.company_id', string='Compañía')

    _sql_constraints = [('change_code_uniq', 'unique(code,branch_social_security_id)', 'Ya existe un centro de trabajo de seguridad social con este código para esta compañía, por favor verificar')]
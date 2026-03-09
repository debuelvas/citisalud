# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class hr_employee(models.Model):
    _inherit = 'hr.employee'

    #Seguridad social - asignación
    branch_social_security_id = fields.Many2one('hr.social.security.branches', 'Sucursal seguridad social', tracking=True)
    work_center_social_security_id = fields.Many2one('hr.social.security.work.center', 'Centro de trabajo seguridad social', tracking=True)

class hr_employeePublic(models.Model):
    _inherit = 'hr.employee.public'

    #Seguridad social - asignación
    branch_social_security_id = fields.Many2one('hr.social.security.branches', 'Sucursal seguridad social', tracking=True)
    work_center_social_security_id = fields.Many2one('hr.social.security.work.center', 'Centro de trabajo seguridad social', tracking=True)
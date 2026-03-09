# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

def name_selection_groups(ids):
    return 'sel_groups_' + '_'.join(str(it) for it in sorted(ids))

#Proceso para validar que al asignar un empleado como gerente no le cambie su tipo de usuario.
class hr_employee(models.Model):
    _inherit = 'hr.employee'

    # @api.model
    # def create(self, vals):
    #     user_type = False
    #     if vals.get('parent_id', False):
    #         obj_employee_parent = self.env['hr.employee'].search([('id', '=', vals.get('parent_id', False))])
    #         user_types_category = self.env.ref('base.module_category_user_type', raise_if_not_found=False)
    #         field_name = name_selection_groups(self.env['res.groups'].search([('category_id', '=', user_types_category.id)]).ids) if user_types_category else False
    #         # Verificar tipo de usuario del Gerente
    #         if obj_employee_parent.user_id.has_group('base.group_user'):  # Usuario Interno
    #             user_type = self.env.ref('base.group_user', raise_if_not_found=False).id
    #         elif obj_employee_parent.user_id.has_group('base.group_public'):  # Usuario Público
    #             user_type = self.env.ref('base.group_public', raise_if_not_found=False).id
    #         elif obj_employee_parent.user_id.has_group('base.group_portal'):  # Usuario de Portal
    #             user_type = self.env.ref('base.group_portal', raise_if_not_found=False).id
    #         else:
    #             user_type = False

    #     obj_create = super(hr_employee, self).create(vals)

    #     if user_type:
    #         obj_create.parent_id.user_id.write({field_name:user_type})

    #     return obj_create

    def write(self, vals):
        user_type = False
        if vals.get('parent_id',False):
            obj_employee_parent = self.env['hr.employee'].search([('id','=',vals.get('parent_id',False))])
            user_types_category = self.env.ref('base.module_category_user_type', raise_if_not_found=False)
            field_name = name_selection_groups(self.env['res.groups'].search([('category_id', '=', user_types_category.id)]).ids) if user_types_category else False
            #Verificar tipo de usuario del Gerente
            if obj_employee_parent.user_id.has_group('base.group_user'): # Usuario Interno
                user_type = self.env.ref('base.group_user', raise_if_not_found=False).id
            elif obj_employee_parent.user_id.has_group('base.group_public'): # Usuario Público
                user_type = self.env.ref('base.group_public', raise_if_not_found=False).id
            elif obj_employee_parent.user_id.has_group('base.group_portal'): # Usuario de Portal
                user_type = self.env.ref('base.group_portal', raise_if_not_found=False).id
            else:
                user_type = False

        obj_write = super(hr_employee, self).write(vals)

        if user_type:
            for record in self:
                record.parent_id.user_id.write({field_name:user_type})

        return obj_write
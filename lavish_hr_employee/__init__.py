# -*- coding: utf-8 -*-

from . import controllers
from . import models

def pre_init_hook(cr):
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    
    fields_to_rename = [
        ('res.partner', 'x_type_thirdparty', 'type_thirdparty'),
        ('res.partner', 'x_document_type', 'document_type'),
        ('res.partner', 'x_digit_verification', 'digit_verification'),
        ('res.partner', 'x_business_name', 'business_name'),
        ('res.partner', 'x_first_name', 'firs_name'),
        ('res.partner', 'x_second_name', 'second_name'),
        ('res.partner', 'x_first_lastname', 'first_lastname'),
        ('res.partner', 'x_second_lastname', 'second_lastname'),
        ('res.partner', 'x_digit_verification', 'digit_verification'),
    ]
    
    for model, old_field_name, new_field_name in fields_to_rename:
        if env['ir.model.fields'].search([('model', '=', model), ('name', '=', old_field_name)]):
            cr.execute(f'ALTER TABLE {model.replace(".", "_")} RENAME COLUMN {old_field_name} TO {new_field_name}')
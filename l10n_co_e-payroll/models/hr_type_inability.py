# Part of Odoo. See LICENSE file for full copyright and licensing details.
from odoo import api, fields, models, _, tools
from odoo.exceptions import  UserError, ValidationError
from datetime import datetime, timedelta, date
import logging

_logger = logging.getLogger(__name__)

class HrTypeInability(models.Model):
    _name = 'hr.type.inability'
    _description = 'Type Inability'

    name = fields.Char(required=True, string='Nombre')
    code = fields.Char(required=True, string='Código')

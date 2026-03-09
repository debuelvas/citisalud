# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from .browsable_object import BrowsableObject, InputLine, WorkedDays, Payslips
from odoo.tools import float_compare, float_is_zero

from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import math
import logging

class hr_history_cesantias(models.Model):
    _name = 'hr.history.cesantias'
    _description = 'Historico de cesantias'
    
    employee_id = fields.Many2one('hr.employee', 'Empleado')
    employee_identification = fields.Char('Identificación empleado')
    type_history = fields.Selection(
        [('cesantias', 'Cesantías'), ('intcesantias', 'Intereses de cesantías'), ('all', 'Ambos')], string='Tipo',
        default='all', required=True)
    initial_accrual_date = fields.Date('Fecha inicial de causación')
    final_accrual_date = fields.Date('Fecha final de causación')
    settlement_date = fields.Date('Fecha de liquidación')
    time = fields.Float('Tiempo')
    severance_value = fields.Float('Valor de cesantías')
    severance_interest_value = fields.Float('Valor intereses de cesantías')
    payslip = fields.Many2one('hr.payslip', 'Liquidación')
    contract_id = fields.Many2one('hr.contract', 'Contrato')
    base_value = fields.Float('Valor base')
    
    def name_get(self):
        result = []
        for record in self:
            type_text = 'Intereses de cesantías' if record.type_history == 'intcesantias' else 'Cesantías'
            result.append((record.id, "{} {} del {} al {}".format(type_text,record.employee_id.name, str(record.initial_accrual_date),str(record.final_accrual_date))))
        return result

    @api.depends('severance_value', 'severance_interest_value')
    def _compute_display_name(self):
        for record in self:
            record.display_name = f"CES: {record.severance_value} - INT. CES.:{record.severance_interest_value}"


    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('employee_identification'):
                obj_employee = self.env['hr.employee'].search(
                    [('identification_id', '=', vals.get('employee_identification'))],
                    limit=1
                )
                if obj_employee:
                    vals['employee_id'] = obj_employee.id
            
            if vals.get('employee_id'):
                obj_employee = self.env['hr.employee'].search(
                    [('id', '=', vals.get('employee_id'))],
                    limit=1
                )
                if obj_employee:
                    vals['employee_identification'] = obj_employee.identification_id

        return super().create(vals_list)


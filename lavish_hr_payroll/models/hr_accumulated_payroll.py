from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from dateutil.relativedelta import relativedelta

class hr_accumulated_payroll(models.Model):
    _name = 'hr.accumulated.payroll'
    _description = 'Acumulados de nómina'

    employee_id = fields.Many2one('hr.employee', string='Empleado')    
    employee_identification = fields.Char('Identificación empleado')
    salary_rule_id = fields.Many2one('hr.salary.rule',string='Regla salarial', required=True)
    date = fields.Date('Fecha', required=True)
    amount = fields.Float(string='Valor')       
    contract_id = fields.Many2one('hr.contract', string='Contrato')
    origin_payslip_id = fields.Many2one('hr.payslip', string='Nómina de origen')
    note = fields.Text('Nota')

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
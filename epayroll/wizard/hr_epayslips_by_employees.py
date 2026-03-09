# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class HrEPayslipsEmployees(models.TransientModel):
    _name = 'hr.epayslips.by.edi.employees'
    _description = 'Generar nóminas electrónicas para todos los empleados seleccionados'

    def _get_employees(self):
        if not self.env.context.get('active_id'):
            return []
        payslip_run = self.env['hr.payslip.edi.run'].browse(self.env.context.get('active_id'))
        payslips = self.env['hr.payslip'].search([
            ('date_to', '>=', payslip_run.date_start),
            ('date_to', '<=', payslip_run.date_end),
            ('state', 'in', ('done', 'paid')),
            ('company_id', '=', payslip_run.company_id.id)
        ])
        return list(set(payslips.mapped('employee_id').with_context(active_test=False).ids))

    employee_ids = fields.Many2many('hr.employee', 'hr_employee_group_edi_rel', 'payslip_id', 'employee_id', 'Employees',
                                    default=lambda self: self._get_employees(), required=True)
    
    def compute_sheet(self):
        self.ensure_one()
        if not self.env.context.get('active_id'):
            from_date = fields.Date.to_date(self.env.context.get('default_date_start'))
            end_date = fields.Date.to_date(self.env.context.get('default_date_end'))
            payslip_run = self.env['hr.payslip.edi.run'].create({
                'name': from_date.strftime('%B %Y'),
                'date_start': from_date,
                'date_end': end_date,
            })
        else:
            payslip_run = self.env['hr.payslip.edi.run'].browse(self.env.context.get('active_id'))
        existing_payslips = self.env['hr.payslip'].search([
            ('date_to', '>=', payslip_run.date_start),
            ('date_to', '<=', payslip_run.date_end),
            ('state', 'in', ('done', 'paid')),
            ('employee_id', 'in', self.employee_ids.ids),
            ('company_id', '=', payslip_run.company_id.id)
        ])

        if not existing_payslips:
            raise ValidationError('No existen nóminas en el periodo para los empleados seleccionados')
        Payslip = self.env['hr.payslip.edi']
        new_payslips = self.env['hr.payslip.edi']
        processed_employees = set()

        for payslip in existing_payslips:
            if payslip.employee_id.id in processed_employees:
                continue 
            values = {
                'name':'/',
                'employee_id': payslip.employee_id.id,
                'credit_note': payslip_run.credit_note,
                'payslip_run_id': payslip_run.id,
                'date_from': payslip_run.date_start,  
                'date_to': payslip_run.date_end,
                'contract_id': payslip.contract_id.id,
                'struct_id': payslip.struct_id.id,
            }
            new_payslip = Payslip.create(values)
            new_payslip._onchange_employee()
            new_payslips += new_payslip
            processed_employees.add(payslip.employee_id.id)
        new_payslips.update_data()
        payslip_run.state = 'verify'
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hr.payslip.edi.run',
            'views': [[False, 'form']],
            'res_id': payslip_run.id,
        }

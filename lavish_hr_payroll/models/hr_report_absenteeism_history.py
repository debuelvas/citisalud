from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError


class hr_report_absenteeism_history(models.TransientModel):
    _name = "hr.report.absenteeism.history"
    _description = "Historico de Ausencias"

    employee_id = fields.Many2many('hr.employee', string='Empleado')
    branch = fields.Many2many('lavish.res.branch', string='Sucursal',
                              domain=lambda self: [('id', 'in', self.env.user.branch_ids.ids)])
    start_date = fields.Date('Fecha de Inicio', required=True)
    date_end = fields.Date('Fecha de Fin', required=True)
    state = fields.Boolean('Solo empleados activos')

    def get_info_absenteeism(self):
        if len(self.employee_id) > 0:
            obj_absenteeism = self.env['hr.leave'].search([('employee_id','in',self.employee_id.ids),
                                                           ('state', '=', 'validate'),
                                                           ('employee_id.company_id','in',self.env.companies.ids),
                                                            ('request_date_from', '>=', self.start_date),
                                                            ('request_date_from', '<=', self.date_end)],order='employee_id asc')
        else:
            obj_absenteeism = self.env['hr.leave'].search([('employee_id.company_id','in',self.env.companies.ids),
                                                           ('state', '=', 'validate'),
                                                           ('request_date_from','>=',self.start_date),
                                                           ('request_date_from','<=',self.date_end)],order='employee_id asc')

        if self.state:
            obj_absenteeism = obj_absenteeism.filtered(lambda x: x.employee_id.contract_id.state == 'open')

        if len(self.branch) > 0:
            obj_absenteeism = obj_absenteeism.filtered(lambda x: x.employee_id.branch_id.id in self.branch.ids)
        else:
            obj_absenteeism = obj_absenteeism.filtered(lambda x: x.employee_id.branch_id.id in self.env.user.branch_ids.ids)

        return obj_absenteeism

    def get_employee_absenteeism(self):
        obj_absenteeism = self.get_info_absenteeism()
        obj_employee = self.env['hr.employee'].search([('id','in',obj_absenteeism.employee_id.ids)])
        return obj_employee


    def generate_report(self):
        datas = {
            'id': self.id,
            'model': 'hr.report.absenteeism.history'
        }

        return {
            'type': 'ir.actions.report',
            'report_name': 'lavish_hr_payroll.hr_report_absenteeism_history',
            'report_type': 'qweb-pdf',
            'datas': datas
        }
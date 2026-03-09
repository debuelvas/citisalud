from odoo import fields, models, api, _
from odoo.exceptions import UserError, ValidationError

class hr_novelties_independents(models.Model):
    _name = 'hr.novelties.independents'
    _description = 'Novedades Independientes'

    employee_id = fields.Many2one('hr.employee', string='Empleado', index=True)
    employee_identification = fields.Char('Identificación empleado')
    salary_rule_id = fields.Many2one('hr.salary.rule', string='Regla salarial', required=True)
    dev_or_ded = fields.Selection('Naturaleza', related='salary_rule_id.dev_or_ded',
                                  store=True, readonly=True)
    date = fields.Date('Fecha', required=True)
    amount = fields.Float('Valor', required=True)
    description = fields.Char('Descripción')

    @api.constrains('amount')
    def _check_amount(self):
        for record in self:
            if record.dev_or_ded == 'deduccion' and record.amount > 0:
                raise UserError(_('La regla es de tipo deducción, el valor ingresado debe ser negativo'))
            if record.dev_or_ded == 'devengo' and record.amount < 0:
                raise UserError(_('La regla es de tipo devengo, el valor ingresado debe ser positivo'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # Handle employee identification lookup
            if vals.get('employee_identification'):
                obj_employee = self.env['hr.employee'].search(
                    [('identification_id', '=', vals.get('employee_identification'))],
                    limit=1
                )
                if obj_employee:
                    vals['employee_id'] = obj_employee.id
            
            # Handle employee id lookup
            if vals.get('employee_id'):
                obj_employee = self.env['hr.employee'].search(
                    [('id', '=', vals.get('employee_id'))],
                    limit=1
                )
                if obj_employee:
                    vals['employee_identification'] = obj_employee.identification_id

        return super().create(vals_list)
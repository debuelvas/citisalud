from logging import exception
from odoo import models, fields, api, _, SUPERUSER_ID
from odoo.exceptions import UserError, ValidationError

from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta


import odoo
import threading

class hr_consolidated_provisions(models.Model):
    _name = 'hr.consolidated.provisions'
    _description = 'Consolidado Provisiones'

    company_id = fields.Many2one('res.company', string='Compañía', readonly=True, required=True,
                                 default=lambda self: self.env.company)
    details_ids = fields.One2many('hr.consolidated.provisions.detail', 'consolidated_provision_id', string='Ejecución')
    year = fields.Integer('Año', required=True)
    provision = fields.Selection([('cesantias', 'Cesantías'),
                                  ('intcesantias', 'Intereses de cesantías'),
                                  ('prima', 'Prima'),
                                  ('vacaciones', 'Vacaciones')], string='Provisión', required=True)
    observations = fields.Text('Observaciones')
    state = fields.Selection([('draft', 'Borrador'), ('done', 'Hecho'),('approved', 'Aprobado')], string='Estado', default='draft')

    _sql_constraints = [('consolidated_provisions_uniq', 'unique(company_id,year,provision)',
                         'El año seleccionado ya esta registrado para esta provisión y compañía, por favor verificar.')]

    def name_get(self):
        result = []
        for record in self:
            provision_str = dict(self._fields['provision'].selection).get(record.provision)
            result.append((record.id, "Consolidado {} - {}".format(str(record.year), provision_str)))
        return result

    # @api.model
    # def _default_months(self):
    #     return [(0, 0, {'consolidated_provision_id': self.id,
    #                     'month': str(month)})
    #             for month in range(1, 13)]

    def action_done(self):
        for record in self:
            query = '''
                Select 
                    %s as consolidated_provision_id,
                    a.employee_id as employee_id,sum(a.value_balance) as total_provision,sum(a.value_balance) as total
                From hr_executing_provisions_details as a
                inner join hr_executing_provisions as b on a.executing_provisions_id = b.id 
                where b."year" = %s and a.provision = '%s' and b.state = 'accounting'
                group by b."year",a.employee_id,a.provision                
            ''' % (str(record.id),str(record.year),record.provision)
            self.env.cr.execute(query)
            result_query = self.env.cr.dictfetchall()
            for item in result_query:
                obj_item = self.env['hr.consolidated.provisions.detail'].create(item)
            record.state = 'done'

    def approved_provision(self):
        for record in self:
            record.state = 'approved'

    def cancel_provision(self):
        for record in self:
            self.env['hr.consolidated.provisions.detail'].search([('consolidated_provision_id','=',record.id)]).unlink()
            record.state = 'draft'

    def unlink(self):
        for record in self:
            if record.state != 'draft':
                raise ValidationError(_('No se puede eliminar el consolidado de provisión debido a que su estado es diferente de borrador.'))
        return super(hr_consolidated_provisions, self).unlink()

class hr_consolidated_provisions_detail(models.Model):
    _name = 'hr.consolidated.provisions.detail'
    _description = 'Detalle Consolidado Provisones'

    consolidated_provision_id = fields.Many2one('hr.consolidated.provisions', string='Consolidado Provision', required=True, ondelete='cascade')
    employee_id = fields.Many2one('hr.employee', 'Empleado', required=True)
    total_provision = fields.Float('Total provisión', required=True)
    # month = fields.Selection([('1', 'Enero'),
    #                         ('2', 'Febrero'),
    #                         ('3', 'Marzo'),
    #                         ('4', 'Abril'),
    #                         ('5', 'Mayo'),
    #                         ('6', 'Junio'),
    #                         ('7', 'Julio'),
    #                         ('8', 'Agosto'),
    #                         ('9', 'Septiembre'),
    #                         ('10', 'Octubre'),
    #                         ('11', 'Noviembre'),
    #                         ('12', 'Diciembre')
    #                         ], string='Mes', required=True)
    total = fields.Float('Total', required=True)

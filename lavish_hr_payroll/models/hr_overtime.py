from odoo import models, fields, api, _
from datetime import datetime, timedelta, date
from odoo.exceptions import UserError, ValidationError
import time
import pytz
class hr_type_overtime(models.Model):
    _name = 'hr.type.overtime'
    _description = 'Tipos de horas extras'

    name = fields.Char(string="Descripción", required=True)
    salary_rule = fields.Many2one('hr.salary.rule', string="Regla salarial", required=True)
    type_overtime = fields.Selection([('overtime_rn','RN | Recargo nocturno'),
                                      ('overtime_ext_d','EXT-D | Extra diurna'),
                                      ('overtime_ext_n','EXT-N | Extra nocturna'),
                                      ('overtime_eddf','E-D-D/F | Extra diurna dominical/festivo'),
                                      ('overtime_endf','E-N-D/F | Extra nocturna dominical/festivo'),
                                      ('overtime_dof','D o F | Dominicales o festivos'),
                                      ('overtime_rndf','RN-D/F | Recargo nocturno dominical/festivo'),
                                      ('overtime_rdf','R-D/F | Recargo dominical/festivo'),
                                      ('overtime_rnf','RN-F | Recargo nocturno festivo')],'Tipo',  required=True)
    percentage = fields.Float(string='Porcentaje')
    equivalence_number_ne = fields.Integer(string='Num. Equivalencia NE')
    start_time = fields.Float('Hora inicio', required=True, default=0)
    end_time = fields.Float('Hora finalización', required=True, default=0)
    start_time_two = fields.Float('Segunda hora de inicio', required=True, default=0)
    end_time_two = fields.Float('Segunda hora de finalización', required=True, default=0)
    contains_holidays = fields.Boolean(string='¿Tener en cuenta días festivos?')
    mon = fields.Boolean(default=False, string='Lun')
    tue = fields.Boolean(default=False, string='Mar')
    wed = fields.Boolean(default=False, string='Mié')
    thu = fields.Boolean(default=False, string='Jue')
    fri = fields.Boolean(default=False, string='Vie')
    sat = fields.Boolean(default=False, string='Sáb')
    sun = fields.Boolean(default=False, string='Dom')

    _sql_constraints = [('change_type_uniq', 'unique(type_overtime)', 'Ya existe este tipo de hora extra, por favor verficar.')]

class hr_overtime(models.Model):
    _name = 'hr.overtime'
    _description = 'Novedades | Horas extras'
    
    branch_id = fields.Many2one('lavish.res.branch', 'Sucursal')
    date = fields.Date('Fecha Novedad', required=True)
    date_end = fields.Date('Fecha Final Novedad', required=True)
    employee_id = fields.Many2one('hr.employee', string="Empleado", index=True)
    employee_identification = fields.Char('Identificación empleado')
    department_id = fields.Many2one('hr.department', related="employee_id.department_id", readonly=True,string="Departamento")
    job_id = fields.Many2one('hr.job', related="employee_id.job_id", readonly=True,string="Servicio")
    overtime_rn = fields.Float('RN', help='Horas recargo nocturno (35%)') # EXTRA_RECARGO
    overtime_ext_d = fields.Float('EXT-D', help='Horas extra diurnas (125%)') # EXTRA_DIURNA
    overtime_ext_n = fields.Float('EXT-N', help='Horas extra nocturna (175%)') # EXTRA_NOCTURNA
    overtime_eddf = fields.Float('E-D-D/F', help='Horas extra diurnas dominical/festiva (200%)') # EXTRA_DIURNA_DOMINICAL
    overtime_endf = fields.Float('E-N-D/F', help='Horas extra nocturna dominical/festiva (250%)') # EXTRA_NOCTURNA_DOMINICAL
    overtime_dof = fields.Float('D o F', help='Horas dominicales (175%)') # DOMINICALES O FESTIVOS
    overtime_rndf = fields.Float('RN-D/F', help='Horas recargo festivo (110%)') # EXTRA_RECARGO_DOMINICAL
    overtime_rdf = fields.Float('R-D/F', help='Recargos dominicales (0.75%)', default=0)  # EXTRA_RECARGO_DOMINICAL_FESTIVO
    overtime_rnf = fields.Float('RN-F', help='Recargo festivo nocturno (210%)')  # EXTRA_RECARGO_NOCTURNO_FESTIVO
    days_actually_worked = fields.Integer('Días efectivamente laborados')
    days_snack = fields.Integer('Días refrigerio')
    justification = fields.Char('Justificación')
    state = fields.Selection([('revertido','Revertido'),('procesado','Procesado'),('nuevo','Nuevo')],'Estado')
    payslip_run_id = fields.Many2one('hr.payslip','Ref. Liquidación')
    shift_hours = fields.Float('Horas del Turno')
    attendance_id = fields.Many2one('hr.attendance', string='Asistencia')
    total_hours = fields.Float(string='Total Horas', compute='_compute_total_hours', store=True)
    
    @api.depends('overtime_rn', 'overtime_ext_d', 'overtime_ext_n', 'overtime_eddf', 
                'overtime_endf', 'overtime_dof', 'overtime_rndf', 'overtime_rdf', 'overtime_rnf')
    def _compute_total_hours(self):
        for record in self:
            record.total_hours = (
                record.overtime_rn + record.overtime_ext_d + record.overtime_ext_n + 
                record.overtime_eddf + record.overtime_endf + record.overtime_dof + 
                record.overtime_rndf + record.overtime_rdf + record.overtime_rnf
            )

    # @api.constrains('total_hours')
    # def _check_overtime_limits(self):
    #     for record in self:
    #         #if record.total_hours > 2:
    #         #    raise ValidationError(_('No se pueden registrar más de 2 horas extras por día'))
                
    #         # Verificar límite semanal
    #         week_start = record.date - timedelta(days=record.date.weekday())
    #         week_end = week_start + timedelta(days=6)
            
    #         domain = [
    #             ('employee_id', '=', record.employee_id.id),
    #             ('date', '>=', week_start),
    #             ('date', '<=', week_end),
    #             ('id', '!=', record.id)  # Excluir el registro actual
    #         ]
            
    #         week_overtimes = self.search(domain)
    #         total_week = sum(week_overtimes.mapped('total_hours')) + record.total_hours
                
    #         if total_week > 12:
    #             raise ValidationError(_('No se pueden registrar más de 12 horas extras por semana'))

    def action_approve(self):
        self.write({'state': 'procesado'})
        
    def action_reject(self):
        self.write({'state': 'revertido'})

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # Calculate total hours/days
            total = sum(vals.get(field, 0) for field in [
                'shift_hours',
                'days_snack',
                'days_actually_worked',
                'overtime_rn',
                'overtime_ext_d',
                'overtime_ext_n',
                'overtime_eddf',
                'overtime_endf',
                'overtime_dof',
                'overtime_rndf',
                'overtime_rdf',
                'overtime_rnf'
            ])

            if total <= 0:
                raise UserError(_('Valores en 0 detectados | No se ha detectado la cantidad de horas / dias de la novedad ingresada!'))

            # Handle employee identification lookup
            if vals.get('employee_identification'):
                obj_employee = self.env['hr.employee'].search([
                    ('company_id', '=', self.env.company.id),
                    ('identification_id', '=', vals.get('employee_identification'))
                ], limit=1)
                if obj_employee:
                    vals['employee_id'] = obj_employee.id

            # Handle employee id lookup
            if vals.get('employee_id'):
                obj_employee = self.env['hr.employee'].search([
                    ('company_id', '=', self.env.company.id),
                    ('id', '=', vals.get('employee_id'))
                ], limit=1)
                if obj_employee:
                    vals['employee_identification'] = obj_employee.identification_id

        return super().create(vals_list)

class HrAttendanceOvertime(models.Model):
    _inherit = 'hr.attendance'
    
    overtime_ids = fields.One2many('hr.overtime', 'attendance_id', string='Horas Extras')
    total_overtime_hours = fields.Float(string='Total Horas Extras', compute='_compute_total_overtime')
    has_exceeded_limit = fields.Boolean(string='Excede Límite', compute='_compute_overtime_limit')

    @api.depends('total_overtime_hours')
    def _compute_overtime_limit(self):
        for record in self:
            # Obtener el total de horas extras en la semana actual
            week_start = record.check_in.date() - timedelta(days=record.check_in.weekday())
            week_end = week_start + timedelta(days=6)
            
            domain = [
                ('employee_id', '=', record.employee_id.id),
                ('check_in', '>=', week_start),
                ('check_in', '<=', week_end)
            ]
            
            week_overtimes = self.search(domain)
            total_week_overtime = sum(week_overtimes.mapped('total_overtime_hours'))
            
            record.has_exceeded_limit = total_week_overtime > 12  # Límite de 12 horas semanales


    @api.depends('overtime_ids')
    def _compute_total_overtime(self):
        for record in self:
            record.total_overtime_hours = sum(record.overtime_ids.mapped(lambda x: 
                x.overtime_rn + x.overtime_ext_d + x.overtime_ext_n + 
                x.overtime_eddf + x.overtime_endf + x.overtime_dof + 
                x.overtime_rndf + x.overtime_rdf + x.overtime_rnf))
    def _get_hour_intervals(self, check_in, check_out):
        """
        Divide el tiempo trabajado en intervalos según los horarios definidos,
        considerando las horas de descanso
        """
        NIGHT_START = 21  # 9 PM
        NIGHT_END = 6    # 6 AM
        BREAK_HOURS = 2  # Horas de descanso
        
        intervals = {
            'day_hours': 0.0,
            'night_hours': 0.0,
            'total_hours': 0.0
        }
        
        # Calcular tiempo total trabajado excluyendo el descanso
        total_time = check_out - check_in
        total_hours = total_time.total_seconds() / 3600.0
        
        # Si el tiempo trabajado es mayor a 6 horas, restar el tiempo de descanso
        if total_hours > 6:
            total_hours -= BREAK_HOURS
            
        current_time = check_in
        hours_counted = 0
        
        while current_time < check_out and hours_counted < total_hours:
            next_hour = min(current_time + timedelta(hours=1), check_out)
            
            # Calcular horas en este intervalo
            hours_in_interval = min(
                (next_hour - current_time).total_seconds() / 3600.0,
                total_hours - hours_counted
            )
            
            # Clasificar las horas según el horario
            if current_time.hour >= NIGHT_START or current_time.hour < NIGHT_END:
                intervals['night_hours'] += hours_in_interval
            else:
                intervals['day_hours'] += hours_in_interval
                
            hours_counted += hours_in_interval
            current_time = next_hour
        
        intervals['total_hours'] = intervals['day_hours'] + intervals['night_hours']
        return intervals

    def _calculate_overtime_distribution(self, intervals, is_holiday, standard_hours):
        """
        Calcula la distribución de horas extras según los intervalos y tipo de día
        """
        overtime_vals = {
            'overtime_rn': 0.0,      # Recargo nocturno (35%)
            'overtime_ext_d': 0.0,   # Extra diurna (25%)
            'overtime_ext_n': 0.0,   # Extra nocturna (75%)
            'overtime_eddf': 0.0,    # Extra diurna dominical/festiva (100%)
            'overtime_endf': 0.0,    # Extra nocturna dominical/festiva (150%)
            'overtime_dof': 0.0,     # Dominicales o festivos (75%)
            'overtime_rndf': 0.0,    # Recargo nocturno dominical/festivo (110%)
            'overtime_rdf': 0.0,     # Recargo dominical/festivo (75%)
            'overtime_rnf': 0.0      # Recargo nocturno festivo (210%)
        }
        
        # Calcular horas efectivas trabajadas
        total_hours = intervals['total_hours']
        # Para un turno de 7:45, las horas estándar serían 7.75
        effective_standard_hours = 7.75  
        
        if total_hours <= effective_standard_hours:
            return overtime_vals
            
        overtime_hours = total_hours - effective_standard_hours
        
        # Distribuir las horas extras según el tipo de día y horario
        if is_holiday:
            if intervals['night_hours'] > 0:
                overtime_vals['overtime_rndf'] = min(intervals['night_hours'], overtime_hours)
                remaining_overtime = overtime_hours - overtime_vals['overtime_rndf']
                if remaining_overtime > 0:
                    overtime_vals['overtime_endf'] = remaining_overtime
            else:
                overtime_vals['overtime_eddf'] = overtime_hours
                
            # Agregar recargo festivo para las horas ordinarias
            overtime_vals['overtime_rdf'] = min(effective_standard_hours, intervals['day_hours'])
            overtime_vals['overtime_rnf'] = min(effective_standard_hours, intervals['night_hours'])
        else:
            if intervals['night_hours'] > 0:
                overtime_vals['overtime_rn'] = min(intervals['night_hours'], effective_standard_hours)
                night_overtime = max(0, intervals['night_hours'] - effective_standard_hours)
                if night_overtime > 0:
                    overtime_vals['overtime_ext_n'] = night_overtime
                    
            day_overtime = max(0, overtime_hours - overtime_vals['overtime_ext_n'])
            if day_overtime > 0:
                overtime_vals['overtime_ext_d'] = day_overtime
                
        return overtime_vals

    def action_create_overtime(self):
        """Crear registro de horas extras basado en la asistencia"""
        self.ensure_one()
        
        if self.has_exceeded_limit:
            raise ValidationError(_('El empleado ya ha excedido el límite de horas extras semanales (12 horas)'))
            
        user_tz = pytz.timezone(self.env.user.tz or 'UTC')
        check_in = pytz.utc.localize(self.check_in).astimezone(user_tz)
        check_out = pytz.utc.localize(self.check_out).astimezone(user_tz)
        
        # Usar 7.75 horas como estándar (7:45)
        standard_hours = 7.75
        
        is_holiday = self.is_holiday(check_in.date()) or check_in.weekday() == 6
        intervals = self._get_hour_intervals(check_in, check_out)
        overtime_vals = self._calculate_overtime_distribution(intervals, is_holiday, standard_hours)
        
        values = {
            'attendance_id': self.id,
            'employee_id': self.employee_id.id,
            'date': check_in.date(),
            'date_end': check_out.date(),
            'state': 'nuevo',
            'employee_identification': self.employee_id.identification_id,
            **overtime_vals
        }
        
        return self.env['hr.overtime'].create(values)

    def is_holiday(self, date):
        """Verificar si una fecha es festivo"""
        domain = [
            ('date_from', '<=', datetime.combine(date, datetime.min.time())),
            ('date_to', '>=', datetime.combine(date, datetime.max.time())),
            ('resource_id', '=', False),
            ('calendar_id', '=', self.employee_id.resource_calendar_id.id),
            ('time_type', '=', 'leave')
        ]
        return bool(self.env['resource.calendar.leaves'].search_count(domain))
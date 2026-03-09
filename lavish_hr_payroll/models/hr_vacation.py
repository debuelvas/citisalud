# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from .browsable_object import BrowsableObject, InputLine, WorkedDays, Payslips
from odoo.tools import float_compare, float_is_zero

from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

import logging

_logger = logging.getLogger(__name__)
class VacationInterruptionReason(models.Model):
    _name = 'hr.vacation.interruption.reason'
    _description = 'Motivo de interrupción de vacaciones'
    
    code = fields.Char('Código', required=True)
    name = fields.Char('Nombre', required=True)
    
    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'El código debe ser único')
    ]

class hr_vacation(models.Model):
    _name = 'hr.vacation'
    _description = 'Historico de vacaciones'
    
    vacation_type = fields.Selection([
        ('enjoy', 'Disfrute'),
        ('money', 'En Dinero')
    ], string='Tipo de Vacaciones', compute='_compute_vacation_type', store=True)
    employee_id = fields.Many2one('hr.employee', 'Empleado')
    employee_identification = fields.Char('Identificación empleado')
    initial_accrual_date = fields.Date('Fecha inicial de causación')
    final_accrual_date = fields.Date('Fecha final de causación')
    departure_date = fields.Date('Fechas salida')
    return_date = fields.Date('Fecha regreso')
    base_value = fields.Float('Base vacaciones disfrutadas')
    base_value_money = fields.Float('Base vacaciones remuneradas')
    business_units = fields.Float('Unidades hábiles')
    value_business_days = fields.Float('Valor días hábiles')
    holiday_units = fields.Float('Unidades festivos')
    holiday_value = fields.Float('Valor días festivos')
    units_of_money = fields.Float('Unidades dinero')
    money_value = fields.Float('Valor en dinero')
    total = fields.Float('Total')
    remaining_days = fields.Float('Días restantes', compute='_compute_remaining_days')
    payslip = fields.Many2one('hr.payslip', 'Liquidación')
    leave_id = fields.Many2one('hr.leave', 'Ausencia')
    contract_id = fields.Many2one('hr.contract', 'Contrato')
    description = fields.Char('Nota')
    is_interrupted = fields.Boolean('¿Vacaciones interrumpidas?', default=False)
    interruption_date = fields.Date('Fecha de interrupción')
    interruption_reason_id = fields.Many2one('hr.vacation.interruption.reason', 'Motivo de interrupción')
    interruption_detail = fields.Text('Detalle de interrupción')
    days_returned = fields.Float('Días devueltos', digits=(16, 4))
    pay_warning = fields.Boolean('Advertencia de pago mínimo', default=False, compute='_compute_pay_warning', store=True)
    pay_warning_message = fields.Char('Mensaje de advertencia', compute='_compute_pay_warning')
    holiday_warning = fields.Boolean('Advertencia de festivo', default=False, compute='_compute_holiday_warning', store=True)
    holiday_warning_message = fields.Char('Mensaje de advertencia', compute='_compute_holiday_warning')
    available_days = fields.Float('Días disponibles', digits=(16, 4), compute='_compute_available_days', store=True)
    will_return = fields.Boolean('Volverá a vacaciones', default=False)
    return_vacation_date = fields.Date('Fecha para retomar vacaciones')
    unused_vacation_lines = fields.One2many('hr.vacation.unused.line', 'vacation_id', 'Líneas de días no usados')
    ibc_pila = fields.Float('IBC PILA')
    
    @api.depends('business_units', 'holiday_units', 'units_of_money', 'value_business_days', 'holiday_value', 'money_value')
    def _compute_pay_warning(self):
        """Verificar si el pago cumple con el mínimo legal"""
        for record in self:
            warning = False
            warning_message = ""
            annual_parameters = self.env['hr.annual.parameters'].search([
                ('year', '=', record.departure_date.year if record.departure_date else datetime.now().year)
            ], limit=1)
            if annual_parameters and record.departure_date:
                smmlv_daily = annual_parameters.smmlv_monthly / 30
                if record.vacation_type == 'enjoy' and record.business_units > 0:
                    avg_daily_value = record.value_business_days / record.business_units
                    if avg_daily_value < smmlv_daily:
                        warning = True
                        warning_message = f"⚠️ El valor diario de vacaciones ({avg_daily_value:.2f}) es menor al mínimo legal ({smmlv_daily:.2f})"
                elif record.vacation_type == 'money' and record.units_of_money > 0:
                    avg_daily_value = record.money_value / record.units_of_money
                    if avg_daily_value < smmlv_daily:
                        warning = True
                        warning_message = f"⚠️ El valor diario de vacaciones en dinero ({avg_daily_value:.2f}) es menor al mínimo legal ({smmlv_daily:.2f})"
            
            record.pay_warning = warning
            record.pay_warning_message = warning_message
    
    @api.depends('departure_date', 'return_date')
    def _compute_holiday_warning(self):
        """Verificar si hay festivos en el período de vacaciones"""
        for record in self:
            warning = False
            warning_message = ""
            if record.departure_date and record.return_date:
                current_date = record.departure_date
                holidays_found = []
                while current_date <= record.return_date:
                    is_holiday = self.env['lavish.holidays'].ensure_holidays(current_date)
                    if is_holiday:
                        holidays_found.append(current_date.strftime('%Y-%m-%d'))
                    current_date += timedelta(days=1)
                
                if holidays_found:
                    warning = True
                    warning_message = f"⚠️ Se detectaron festivos en el período de vacaciones: {', '.join(holidays_found)}"
            record.holiday_warning = warning
            record.holiday_warning_message = warning_message
    
    @api.depends('contract_id', 'employee_id', 'departure_date', 'leave_id')
    def _compute_available_days(self):
        for record in self:
            if record.contract_id and record.employee_id:
                date_start = record.contract_id.date_start
                date_end = record.departure_date or fields.Date.today()
                company = record.employee_id.company_id
                if hasattr(company, 'vacation_cutoff_day') and hasattr(company, 'vacation_cutoff_month'):
                    cutoff_day = company.vacation_cutoff_day
                    cutoff_month = company.vacation_cutoff_month
                    if cutoff_day and cutoff_month:
                        current_year = date_end.year
                        cutoff_date = datetime(current_year, cutoff_month, cutoff_day).date()
                        if date_end > cutoff_date:
                            date_end = cutoff_date
                days_contracted = 0
                if hasattr(record.contract_id, 'dias360'):
                    days_contracted = record.contract_id.dias360(date_start, date_end)
                else:
                    delta = date_end - date_start
                    days_contracted = delta.days + 1
                days_unpaid_absences = record._get_unpaid_absence_days(date_start, date_end, record.contract_id)
                days_vacation = ((days_contracted - days_unpaid_absences) * 15) / 360
                days_vacation = round(days_vacation, 4)
                days_enjoyed = record._get_enjoyed_vacation_days()
                available_days = days_vacation - days_enjoyed
                
                record.available_days = available_days
            else:
                record.available_days = 0
    def _get_unpaid_absence_days(self, start_date, end_date, contract_id):
        """Obtener días de ausencias no remuneradas"""
        leaves = self.env['hr.leave'].search([
            ('contract_id', '=', contract_id.id),
            ('date_from', '>=', start_date),
            ('date_to', '<=', end_date),
            ('state', '=', 'validate'),
            ('holiday_status_id.unpaid_absences', '=', True)
        ])
        absence_days = sum(leave.number_of_days for leave in leaves)
        if hasattr(self.env, 'hr.absence.history'):
            absence_histories = self.env['hr.absence.history'].search([
                ('employee_id', '=', contract_id.employee_id.id),
                ('star_date', '>=', start_date),
                ('end_date', '<=', end_date),
                ('leave_type_id.unpaid_absences', '=', True)
            ])
            absence_days += sum(history.days for history in absence_histories)
        return absence_days
    
    def _get_enjoyed_vacation_days(self):
        """Obtener días de vacaciones ya disfrutados"""
        if not self.contract_id or not self.employee_id:
            return 0
        domain = [
            ('contract_id', '=', self.contract_id.id),
            ('employee_id', '=', self.employee_id.id),
            ('id', '!=', self.id)
        ]
        vacations = self.env['hr.vacation'].search(domain)
        enjoyed_days = 0
        for vacation in vacations:
            if vacation.vacation_type == 'enjoy':
                enjoyed_days += vacation.business_units
            elif vacation.vacation_type == 'money':
                enjoyed_days += vacation.units_of_money
            if vacation.is_interrupted and vacation.days_returned > 0:
                enjoyed_days -= vacation.days_returned
        return enjoyed_days
    
    @api.onchange('is_interrupted', 'interruption_date', 'days_returned')
    def _onchange_interruption(self):
        """Al cambiar datos de interrupción, actualizar valores"""
        for record in self:
            if record.is_interrupted and record.interruption_date and record.days_returned > 0:
                if record.departure_date <= record.interruption_date <= record.return_date:
                    record.return_date = record.interruption_date
                    if record.business_units > record.days_returned:
                        record.business_units -= record.days_returned
                        
    @api.depends('leave_id.holiday_status_id')
    def _compute_vacation_type(self):
        for record in self:
            if record.leave_id and record.leave_id.holiday_status_id:
                if record.leave_id.holiday_status_id.is_vacation_money:
                    record.vacation_type = 'money'
                else:
                    record.vacation_type = 'enjoy'
            else:
                if record.units_of_money != 0:
                    record.vacation_type = 'money'
                else:
                    record.vacation_type = 'enjoy'

    @api.depends('departure_date', 'return_date', 'vacation_type')
    def _compute_remaining_days(self):
        for record in self:
            if record.contract_id:
                remaining = record.contract_id.calculate_remaining_days(
                    ignore_payslip_id=record.payslip.id if record.payslip else None
                )
                record.remaining_days = remaining
            else:
                record.remaining_days = 0

    def _compute_display_name(self):
        result = []
        for record in self:
            result.append((record.id, "Vacaciones {} del {} al {}".format(
                record.employee_id.name, str(record.departure_date), str(record.return_date)
            )))
            record.display_name = result
    
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

    def get_paid_vacations(self, contract_id, ignore_payslip_id):
        domain = [('contract_id', '=', contract_id)]
        if ignore_payslip_id:
            domain.append(('payslip', '!=', ignore_payslip_id))
        
        vacations = self.env['hr.vacation'].search(domain)
        total_days = 0
        for v in vacations:
            if v.vacation_type == 'enjoy':
                total_days += v.business_units
            elif v.vacation_type == 'money':
                total_days += v.units_of_money
        return total_days

    def calculate_vacation_days(self, working_days, unpaid_days):
        VACATION_FACTOR = 15
        YEAR_DAYS = 360
        return ((working_days - unpaid_days) * VACATION_FACTOR) / YEAR_DAYS

class HrVacationUnusedLine(models.Model):
    _name = 'hr.vacation.unused.line'
    _description = 'Líneas de días de vacaciones no usados'
    _order = 'date'
    
    vacation_id = fields.Many2one('hr.vacation', 'Vacaciones', required=True, ondelete='cascade')
    employee_id = fields.Many2one('hr.employee', related='vacation_id.employee_id', store=True)
    date = fields.Date('Fecha', required=True)
    is_business_day = fields.Boolean('Día hábil', default=True)
    unused_reason_id = fields.Many2one('hr.vacation.interruption.reason', 'Motivo')
    description = fields.Char('Descripción')
    work_day_value = fields.Float('Valor día laboral')
    is_holiday = fields.Boolean('Es festivo')
    is_weekend = fields.Boolean('Es fin de semana')
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('validated', 'Validado'),
        ('used', 'A utilizar en futuro')
    ], string='Estado', default='draft')

class hr_payslip_paid_vacation(models.Model):
    _name = 'hr.payslip.paid.vacation'
    _description = 'Liquidación vacaciones remuneradas'

    slip_id = fields.Many2one('hr.payslip',string='Nómina', required=True)
    paid_vacation_days = fields.Integer(string='Cantidad de días', required=True)
    start_date_paid_vacation = fields.Date(string='Fecha inicial', required=True)
    end_date_paid_vacation = fields.Date(string='Fecha final', required=True)

    @api.onchange('paid_vacation_days','start_date_paid_vacation')
    def _onchange_paid_vacation_days(self):
        for record in self:
            if record.paid_vacation_days > 0 and record.start_date_paid_vacation:
                date_to = record.start_date_paid_vacation - timedelta(days=1)
                cant_days = record.paid_vacation_days
                days = 0
                days_31 = 0
                while cant_days > 0:
                    date_add = date_to + timedelta(days=1)
                    cant_days = cant_days - 1
                    days += 1
                    days_31 += 1 if date_add.day == 31 else 0
                    date_to = date_add

                record.end_date_paid_vacation = date_to
                record.paid_vacation_days = days - days_31

class Hr_payslip_line(models.Model):
    _inherit = 'hr.payslip.line'

    initial_accrual_date = fields.Date('C. Inicio')
    final_accrual_date = fields.Date('C. Fin')
    vacation_departure_date = fields.Date('Fechas salida vacaciones')
    vacation_return_date = fields.Date('Fechas regreso vacaciones')
    vacation_leave_id = fields.Many2one('hr.leave', 'Ausencia')
    business_units = fields.Float('Unidades hábiles')
    business_31_units = fields.Float('Unidades hábiles - Días 31')
    holiday_units = fields.Float('Unidades festivos')
    holiday_31_units = fields.Float('Unidades festivos  - Días 31')
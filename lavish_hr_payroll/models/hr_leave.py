from odoo import api, fields, models, SUPERUSER_ID,  _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare
from odoo.osv import expression
from calendar import monthrange
from dateutil.relativedelta import relativedelta
from collections import defaultdict
from datetime import datetime, time, timedelta, date
from pytz import UTC
from odoo.osv.expression import AND
from odoo.tools import format_date
from operator import itemgetter
import pytz
UTC = pytz.UTC
STATE = [
    ('draft', 'Borrador'),
    ('validated', 'Validada'),
    ('paid', 'Pagada')
]

import logging
HOURS_PER_DAY = 8
import logging
_logger = logging.getLogger(__name__)
import calendar
from collections import namedtuple
_nt_holiday_stock = namedtuple("Holiday", ["day", "days_to_sum", "celebration"])

EASTER_WEEK_HOLIDAYS = [
    _nt_holiday_stock(day=-3, days_to_sum=None, celebration="Jueves Santo"),
    _nt_holiday_stock(day=-2, days_to_sum=None, celebration="Viernes Santo"),
    _nt_holiday_stock(day=39, days_to_sum=calendar.MONDAY, celebration="Ascensión del Señor"),
    _nt_holiday_stock(day=60, days_to_sum=calendar.MONDAY, celebration="Corphus Christi"),
    _nt_holiday_stock(day=68, days_to_sum=calendar.MONDAY, celebration="Sagrado Corazón de Jesús")
]

HOLIDAYS = [
    _nt_holiday_stock(day="01-01", days_to_sum=None, celebration="Año Nuevo"),
    _nt_holiday_stock(day="05-01", days_to_sum=None, celebration="Día del Trabajo"),
    _nt_holiday_stock(day="07-20", days_to_sum=None, celebration="Día de la Independencia"),
    _nt_holiday_stock(day="08-07", days_to_sum=None, celebration="Batalla de Boyacá"),
    _nt_holiday_stock(day="12-08", days_to_sum=None, celebration="Día de la Inmaculada Concepción"),
    _nt_holiday_stock(day="12-25", days_to_sum=None, celebration="Día de Navidad"),
    _nt_holiday_stock(day="01-06", days_to_sum=calendar.MONDAY, celebration="Día de los Reyes Magos"),
    _nt_holiday_stock(day="03-19", days_to_sum=calendar.MONDAY, celebration="Día de San José"),
    _nt_holiday_stock(day="06-29", days_to_sum=calendar.MONDAY, celebration="San Pedro y San Pablo"),
    _nt_holiday_stock(day="08-15", days_to_sum=calendar.MONDAY, celebration="La Asunción de la Virgen"),
    _nt_holiday_stock(day="10-12", days_to_sum=calendar.MONDAY, celebration="Día de la Raza"),
    _nt_holiday_stock(day="11-01", days_to_sum=calendar.MONDAY, celebration="Todos los Santos"),
    _nt_holiday_stock(day="11-11", days_to_sum=calendar.MONDAY, celebration="Independencia de Cartagena")
]

def next_weekday(d, weekday):
    """ https://stackoverflow.com/a/6558571 """
    days_ahead = weekday - d.weekday()
    if days_ahead <= 0: # Target day already happened this week
        days_ahead += 7
    return d + timedelta(days_ahead)

def calc_easter(year):
    """ Returns Easter as a date object.

    upstream: http://code.activestate.com/recipes/576517-calculate-easter-western-given-a-year/

    :type year: integer

    :raises:
    :rtype: ValueError if year is not integer
    """
    year = int(year)
    a = year % 19
    b = year // 100
    c = year % 100
    d = (19 * a + b - b // 4 - ((b - (b + 8) // 25 + 1) // 3) + 15) % 30
    e = (32 + 2 * (b % 4) + 2 * (c // 4) - d - (c % 4)) % 7
    f = d + e - 7 * ((a + 11 * d + 22 * e) // 451) + 114
    month = f // 31
    day = f % 31 + 1
    return date(year, month, day)

def get_colombia_holidays_by_year(year):
    try:
        year = int(year)
    except ValueError:
        raise TypeError("El año debe ser un entero")

    if year < 1970 or year > 99999:
        raise ValueError("El año debe ser mayor a 1969 y menor a 100000")

    nt_holiday = namedtuple("Holiday", ["date", "celebration"])
    normal_holidays = []
    for holiday in HOLIDAYS:
        holiday_date = datetime.strptime("%s-%d" % (holiday.day, year), "%m-%d-%Y").date()
        if holiday.days_to_sum is not None and holiday_date.weekday() != holiday.days_to_sum:
            holiday_date = next_weekday(holiday_date, holiday.days_to_sum)
        normal_holidays.append(nt_holiday(date=holiday_date, celebration=holiday.celebration))

    sunday_date = calc_easter(year)
    easter_holidays = []
    for holiday in EASTER_WEEK_HOLIDAYS:
        holiday_date = sunday_date + timedelta(days=holiday.day)
        if holiday.days_to_sum is not None and holiday_date.weekday() != holiday.days_to_sum:
            holiday_date = next_weekday(holiday_date, holiday.days_to_sum)
        easter_holidays.append(nt_holiday(date=holiday_date, celebration=holiday.celebration))

    holiday_list = normal_holidays + easter_holidays
    holiday_list.sort(key=lambda holiday: holiday.date)
    return holiday_list

def is_holiday_date(d):
    if not isinstance(d, date):
        raise TypeError("Debe proporcionar un objeto tipo date")
    if isinstance(d, datetime):
        d = d.date()
    holiday_list = set([holiday.date for holiday in get_colombia_holidays_by_year(d.year)])
    return d in holiday_list


_logger = logging.getLogger(__name__)
class HrWorkEntryType(models.Model):    
    _inherit = "hr.work.entry.type"
    
    deduct_deductions = fields.Selection([('all', 'Todas las deducciones'),
                                          ('law', 'Solo las deducciones de ley')],'Tener en cuenta al descontar', default='all')    #Vacaciones
    not_contribution_base = fields.Boolean(string='No es base de aportes',help='Este tipo de ausencia no es base para seguridad social')
    short_name = fields.Char(string='Nombre corto/reportes')

class HolidaysRequest(models.Model):    
    _inherit = "hr.leave"
    _order = 'date_from desc'

    number_of_vac_money_days = fields.Float( 'Duracion (Dias Compensadas)', store=True, tracking=True, help='Number of days of the time off request. Used in the calculation.')
    sequence = fields.Char('Numero')
    employee_identification = fields.Char('Identificación empleado')
    unpaid_absences = fields.Boolean(related='holiday_status_id.unpaid_absences', string='Ausencia no remunerada',store=True)
    discounting_bonus_days = fields.Boolean(related='holiday_status_id.discounting_bonus_days', string='Descontar días en prima',store=True,tracking=True)
    contract_id = fields.Many2one(comodel_name='hr.contract', string='Contrato', compute='_inverse_get_contract',store=True)
    #Campos para vacaciones
    is_vacation = fields.Boolean(related='holiday_status_id.is_vacation', string='Es vacaciones',store=True)
    is_vacation_money = fields.Boolean(related='holiday_status_id.is_vacation_money', string='Es vacaciones en Dinero',store=True)
    business_days = fields.Float(compute='_compute_number_of_days', string='Días habiles')
    holidays = fields.Float(compute='_compute_number_of_days', string='Días festivos')
    days_31_business = fields.Float(compute='_compute_number_of_days', string='Días 31 habiles', help='Este día no se tiene encuenta para el calculo del pago pero si afecta su historico de vacaciones.')
    days_31_holidays = fields.Float(compute='_compute_number_of_days', string='Días 31 festivos', help='Este día no se tiene encuenta para el calculo del pago ni afecta su historico de vacaciones.')
    alert_days_vacation = fields.Boolean(string='Alerta días vacaciones')
    accumulated_vacation_days = fields.Float(string='Días acumulados de vacaciones')
    #Creación de ausencia
    type_of_entity = fields.Many2one('hr.contribution.register', 'Tipo de Entidad',tracking=True)
    entity = fields.Many2one('hr.employee.entities', 'Entidad',tracking=True)
    diagnostic = fields.Many2one('hr.leave.diagnostic', 'Diagnóstico',tracking=True)
    radicado = fields.Char('Radicado #',tracking=True)
    is_recovery = fields.Boolean('Es recobro',tracking=True)
    evaluates_day_off = fields.Boolean('Evalúa festivos')
    apply_day_31 = fields.Boolean(string='Aplica día 31')
    discount_rest_day = fields.Boolean(string='Descontar día de descanso')
    payroll_value = fields.Float('Valor a pagado',tracking=True)
    ibc = fields.Float('IBL',tracking=True)
    force_ibc = fields.Boolean('Forzar IBL ausencia',tracking=True)
    force_porc = fields.Float('Forzar Porcentaje',tracking=True)
    leave_ids = fields.One2many('hr.absence.days', 'leave_id', string='Novedades', readonly=True)
    line_ids = fields.One2many(comodel_name='hr.leave.line', inverse_name='leave_id', readonly=True, string='Lineas de Ausencia')
    eps_value = fields.Float('Valor pagado por la EPS',tracking=True)
    payment_date = fields.Date ('Fecha de pago',tracking=True)
    return_date = fields.Date ('Fecha de regreso',tracking=True)
    #Prorroga
    payroll_value_with_extension = fields.Float('Valor pagado en nómina con prorrogas',  store=True, tracking=True)
    eps_value_with_extension = fields.Float('Valor pagado por la EPS  con prorrogas', store=True, tracking=True)
    is_extension = fields.Boolean(string='Es prórroga', default=False)
    extension_id = fields.Many2one(
        comodel_name='hr.leave',
        domain="[('state', '=', 'validate'),('holiday_status_id', '=', holiday_status_id), ('employee_id', '=', employee_id),]",
        string='Prórroga')
    payroll_id = fields.Many2one('hr.payslip')
    days_used = fields.Float(string='Dias a usar',compute="_days_used")

    #####################
    state = fields.Selection(selection_add=[
        ('paid', 'Pagada'),
        ('validate1',),
    ], string='Estado', readonly=True)
    approve_date = fields.Datetime('Aprobación', readonly=True,)
    payed_vac = fields.Float('Vacaciones en dinero')
    special_vac_base = fields.Boolean('Disfrutadas con todo')
    #####################
    number_of_days_temp = fields.Float(compute='_compute_number_of_days', string='Días de licencia', readonly=True, store=True)
    number_of_days_in_payslip = fields.Float(compute='_compute_number_of_days', string='Días en la nómina')
    number_of_hours_in_payslip = fields.Float(compute='_compute_number_of_days', string='Horas en nómina')
    number_of_hours = fields.Float(compute='_compute_number_of_days', string='Horas de licencia')
    dummy = fields.Boolean('Actualizar')
    apply_payslip_pay_31 = fields.Boolean('Pagar el 31 en la Nomina')
    pay_out_slip = fields.Boolean('Pagar fuera de periodo', help="Permite que el sistema calcule los días")
    type_name = fields.Char(related='holiday_status_id.name', string='Nombre del tipo de permiso')
    payroll_code = fields.Char(string="Código de nómina", related="holiday_status_id.code")
    # Campos para interrupciones de vacaciones
    is_vacation_interrupted = fields.Boolean('Vacaciones interrumpidas', default=False, help='Indica si estas vacaciones fueron interrumpidas')
    vacation_interruption_date = fields.Date('Fecha de interrupción')
    vacation_interruption_reason_id = fields.Many2one('hr.vacation.interruption.reason', 'Motivo de interrupción')
    vacation_interruption_detail = fields.Text('Detalle de interrupción')
    vacation_days_returned = fields.Float('Días devueltos', digits=(16, 4), help='Días de vacaciones devueltos por interrupción')
    vacation_will_return = fields.Boolean('Volverá a vacaciones', default=False)
    vacation_return_date = fields.Date('Fecha para retomar vacaciones')
    # Campos para mostrar advertencias
    min_payment_warning = fields.Boolean('Advertencia pago mínimo', compute='_compute_warnings')
    min_payment_message = fields.Char('Mensaje pago mínimo', compute='_compute_warnings')
    holiday_warning = fields.Boolean('Advertencia festivo', compute='_compute_warnings')
    holiday_warning_message = fields.Char('Mensaje festivo', compute='_compute_warnings')
    # Campo para días disponibles
    available_vacation_days = fields.Float('Días de vacaciones disponibles', digits=(16, 4), compute='_compute_available_vacation_days')
    # Campos para cálculos de nómina
    is_vacation_interrupted = fields.Boolean('Vacaciones interrumpidas', default=False)
    vacation_interruption_date = fields.Date('Fecha de interrupción')
    vacation_interruption_reason_id = fields.Many2one('hr.vacation.interruption.reason', 'Motivo de interrupción')
    vacation_interruption_detail = fields.Text('Detalle de interrupción')
    vacation_days_returned = fields.Float('Días devueltos', digits=(16, 4))
    vacation_will_return = fields.Boolean('Volverá a vacaciones', default=False)
    vacation_return_date = fields.Date('Fecha para retomar vacaciones')
    
    # Campos para advertencias
    min_payment_warning = fields.Boolean('Advertencia pago mínimo', compute='_compute_warnings')
    min_payment_message = fields.Char('Mensaje pago mínimo', compute='_compute_warnings')
    holiday_warning = fields.Boolean('Advertencia festivo', compute='_compute_warnings')
    holiday_warning_message = fields.Char('Mensaje festivo', compute='_compute_warnings')
    
    # Campos para cálculos
    available_vacation_days = fields.Float('Días de vacaciones disponibles', digits=(16, 4), compute='_compute_available_vacation_days')
    ibc_pila = fields.Float('IBC PILA', tracking=True)
    
    ibl_total = fields.Float('IBL Total', compute='_compute_ibl_total', store=True)
    diferencia_ibc = fields.Float('Diferencia a cargo de empresa', compute='_compute_ibl_total', store=True)
    use_ibc_pila = fields.Boolean('Usar IBC PILA para todos los cálculos', default=False)
    
    days_work_count = fields.Float('Días laborables', compute='_compute_days_count', store=True)
    days_rest_count = fields.Float('Días de descanso', compute='_compute_days_count', store=True)
    
    resumen_calculo = fields.Html('Resumen de cálculo', compute='_compute_resumen_calculo', store=True)
    
    @api.depends('line_ids', 'line_ids.amount', 'ibc', 'ibc_pila')
    def _compute_ibl_total(self):
        for leave in self:
            leave.ibl_total = sum(line.amount for line in leave.line_ids)
            
            if leave.holiday_status_id.completar_salario and leave.holiday_status_id.novelty in ['ige', 'irl']:
                if leave.request_unit_hours:
                    annual_parameters = self.env['hr.annual.parameters'].search([('year', '=', leave.date_from.year)])
                    hours_monthly = annual_parameters.hours_monthly or 240
                    valor_base = (leave.contract_id.wage / hours_monthly) * leave.number_of_hours_display
                else:
                    valor_base = leave.contract_id.wage / 30 * leave.number_of_days
                    
                leave.diferencia_ibc = max(0, valor_base - leave.ibl_total)
            else:
                leave.diferencia_ibc = 0

    @api.depends('date_from', 'date_to', 'contract_id', 'holiday_status_id', 'line_ids')
    def _compute_days_count(self):
        for leave in self:
            days_work = days_rest = 0
            
            if leave.line_ids:
                days_work = sum(line.days_work for line in leave.line_ids)
                days_rest = sum(line.days_holiday for line in leave.line_ids)
                days_rest += sum(line.days_holiday_31 for line in leave.line_ids)
            elif leave.date_from and leave.date_to:
                current_date = leave.date_from.date()
                while current_date <= leave.date_to.date():
                    is_rest_day = (
                        current_date.weekday() == 6 or
                        self._is_holiday(current_date) or
                        (current_date.weekday() == 5 and not leave.employee_id.sabado)
                    )
                    
                    if is_rest_day:
                        days_rest += 1
                    else:
                        days_work += 1
                    
                    current_date += timedelta(days=1)
            
            leave.days_work_count = days_work
            leave.days_rest_count = days_rest
    
    @api.depends('date_from', 'date_to', 'contract_id', 'holiday_status_id', 'line_ids', 
                'ibc', 'ibc_pila', 'ibl_total', 'diferencia_ibc')
    def _compute_resumen_calculo(self):
        for leave in self:
            if not leave.line_ids:
                leave.resumen_calculo = "<div>Sin líneas de ausencia calculadas</div>"
                continue
                
            dias_laborables = leave.days_work_count
            dias_descanso = leave.days_rest_count
            total_dias = dias_laborables + dias_descanso
            valor_ibc = leave.ibc
            valor_ibc_pila = leave.ibc_pila
            valor_ibl = leave.ibl_total
            diferencia = leave.diferencia_ibc
            tipo_liquidacion = leave.holiday_status_id.liquidacion_value
            valores_dict = dict([
                ('IBC', 'IBC Mes Anterior'),
                ('YEAR', 'Promedio Año Anterior'),
                ('WAGE', 'Sueldo Actual'),
                ('MIN', 'Parámetros mínimos de ley')
            ])
            tipo_texto = valores_dict.get(tipo_liquidacion, 'No definido')
            
            desglose_tramos = ""
            if leave.holiday_status_id.novelty in ['ige', 'irl']:
                tramos = {
                    'iniciales': [],
                    'hasta_90': [],
                    'hasta_180': [],
                    'mas_180': []
                }
                
                for line in leave.line_ids:
                    if line.sequence <= leave.holiday_status_id.num_days_no_assume:
                        tramos['iniciales'].append(line)
                    elif line.sequence <= 90:
                        tramos['hasta_90'].append(line)
                    elif line.sequence <= 180:
                        tramos['hasta_180'].append(line)
                    else:
                        tramos['mas_180'].append(line)
                
                desglose_tramos = """
                <div class="mt-3">
                    <strong>Desglose por tramos:</strong>
                    <ul>
                """
                
                if tramos['iniciales']:
                    dias = len(tramos['iniciales'])
                    valor = sum(line.amount for line in tramos['iniciales'])
                    desglose_tramos += f"<li>Primeros {dias} días (Empresa): {valor:.2f}</li>"
                
                if tramos['hasta_90']:
                    dias = len(tramos['hasta_90'])
                    valor = sum(line.amount for line in tramos['hasta_90'])
                    desglose_tramos += f"<li>Días 3-90 (EPS/ARL 66.67%): {valor:.2f}</li>"
                
                if tramos['hasta_180']:
                    dias = len(tramos['hasta_180'])
                    valor = sum(line.amount for line in tramos['hasta_180'])
                    desglose_tramos += f"<li>Días 91-180 (EPS/ARL 50%): {valor:.2f}</li>"
                
                if tramos['mas_180']:
                    dias = len(tramos['mas_180'])
                    valor = sum(line.amount for line in tramos['mas_180'])
                    desglose_tramos += f"<li>Días +180 (EPS/ARL 50%): {valor:.2f}</li>"
                
                desglose_tramos += """
                    </ul>
                </div>
                """
            
            completar_info = ""
            if leave.holiday_status_id.completar_salario and diferencia > 0:
                completar_info = f"""
                <div class="alert alert-info mt-3">
                    <strong>Complemento salarial:</strong> La empresa asumirá {diferencia:.2f} 
                    para completar hasta el 100% del salario actual.
                </div>
                """
            
            resumen = f"""
            <div class="row">
                <div class="col-6">
                    <strong>Detalles de Días:</strong>
                    <ul>
                        <li>Días laborables: {dias_laborables}</li>
                        <li>Días de descanso: {dias_descanso}</li>
                        <li>Total días: {total_dias}</li>
                    </ul>
                </div>
                <div class="col-6">
                    <strong>Valores:</strong>
                    <ul>
                        <li>IBC Base: {valor_ibc:.2f}</li>
                        <li>IBC PILA: {valor_ibc_pila:.2f}</li>
                        <li>IBL Total (Pago al empleado): {valor_ibl:.2f}</li>
                    </ul>
                </div>
            </div>
            <div class="row">
                <div class="col-12">
                    <strong>Tipo de liquidación:</strong> {tipo_texto}
                </div>
            </div>
            {desglose_tramos}
            {completar_info}
            """
            
            leave.resumen_calculo = resumen

    @api.depends('date_from', 'date_to', 'resource_calendar_id', 'holiday_status_id.request_unit', 'number_of_vac_money_days')
    def _compute_duration(self):
        for holiday in self:
            if holiday.number_of_vac_money_days:
                days = holiday.number_of_vac_money_days
                hours = days * HOURS_PER_DAY
            else:
                days, hours = holiday._get_duration()
            holiday.number_of_hours = hours
            holiday.number_of_days = days

    @api.depends('line_ids', 'apply_payslip_pay_31')
    def _compute_number_of_days(self):
        for leave in self:
            leave.number_of_days_temp = sum(line.days_assigned for line in leave.line_ids)
            leave.number_of_days_in_payslip = sum(line.days_payslip for line in leave.line_ids)
            leave.number_of_hours_in_payslip = sum(line.hours for line in leave.line_ids)
            leave.number_of_hours = sum(line.hours_assigned for line in leave.line_ids)
            leave.business_days = sum(line.days_work for line in leave.line_ids)
            leave.holidays = sum(line.days_holiday for line in leave.line_ids)
            leave.days_31_business = sum(line.days_31 for line in leave.line_ids)
            leave.days_31_holidays = sum(line.days_holiday_31 for line in leave.line_ids)
            
    @api.depends('holiday_status_id', 'date_from', 'date_to', 'line_ids', 'line_ids.amount')
    def _compute_warnings(self):
        """Calcular advertencias sobre pagos mínimos y festivos"""
        for leave in self:
            leave.min_payment_warning = False
            leave.min_payment_message = ""
            leave.holiday_warning = False
            leave.holiday_warning_message = ""
            if not leave.holiday_status_id.is_vacation and not leave.holiday_status_id.is_vacation_money:
                continue
            if leave.line_ids:
                annual_parameters = self.env['hr.annual.parameters'].search([
                    ('year', '=', leave.date_from.year)
                ], limit=1)
                
                if annual_parameters:
                    smmlv_daily = annual_parameters.smmlv_monthly / 30
                    work_lines = leave.line_ids.filtered(lambda l: l.days_work > 0)
                    if work_lines:
                        total_work_days = sum(line.days_work for line in work_lines)
                        total_amount = sum(line.amount for line in work_lines)
                        
                        if total_work_days > 0:
                            avg_daily = total_amount / total_work_days
                            if avg_daily < smmlv_daily:
                                leave.min_payment_warning = True
                                leave.min_payment_message = f"⚠️ El pago diario ({avg_daily:.2f}) es menor al mínimo legal ({smmlv_daily:.2f})"
            if leave.date_from and leave.date_to:
                current_date = leave.date_from.date()
                holidays_found = []
                while current_date <= leave.date_to.date():
                    is_holiday = self.env['lavish.holidays'].ensure_holidays(current_date)
                    if is_holiday:
                        holidays_found.append(current_date.strftime('%d/%m/%Y'))
                    current_date += timedelta(days=1)
                
                if holidays_found:
                    leave.holiday_warning = True
                    leave.holiday_warning_message = f"⚠️ Festivos detectados: {', '.join(holidays_found)}"
    
    @api.depends('employee_id', 'contract_id', 'date_from')
    def _compute_available_vacation_days(self):
        """Calcular días de vacaciones disponibles"""
        for leave in self:
            leave.available_vacation_days = 0
            if (leave.holiday_status_id.is_vacation or leave.holiday_status_id.is_vacation_money) and \
               leave.employee_id and leave.contract_id:
                date_end = leave.date_from.date() if leave.date_from else fields.Date.today()
                date_start = leave.contract_id.date_start
                days_contracted = 0
                if hasattr(leave.contract_id, 'dias360'):
                    days_contracted = leave.contract_id.dias360(date_start, date_end)
                else:
                    delta = date_end - date_start
                    days_contracted = delta.days + 1
                days_unpaid = self._get_unpaid_absence_days(date_start, date_end, leave.employee_id)
                days_vacation = ((days_contracted - days_unpaid) * 15) / 360
                days_vacation = round(days_vacation, 4)
                days_enjoyed = self._get_enjoyed_vacation_days(leave.contract_id.id, leave.employee_id.id)
                leave.available_vacation_days = days_vacation - days_enjoyed
    


    def _get_enjoyed_vacation_days(self, contract_id, employee_id):
        """Obtener días de vacaciones ya disfrutados"""
        vacations = self.env['hr.vacation'].search([
            ('contract_id', '=', contract_id),
            ('employee_id', '=', employee_id)
        ])
        enjoyed_days = 0
        for vacation in vacations:
            if vacation.vacation_type == 'enjoy':
                enjoyed_days += vacation.business_units
            elif vacation.vacation_type == 'money':
                enjoyed_days += vacation.units_of_money
            if vacation.is_interrupted and vacation.days_returned > 0:
                enjoyed_days -= vacation.days_returned
        return enjoyed_days
    
    def action_draft(self):
        [record._clean_leave() for record in self]
        return super(HolidaysRequest, self).action_draft()


    @api.depends('employee_id','employee_ids','date_from')
    def _inverse_get_contract(self):
        for record in self:
            if not record.employee_id or not record.date_from or not record.date_to:
                record.contract_id = False
                continue
            # Add a default contract if not already defined or invalid
            if record.contract_id and record.employee_id == record.contract_id.employee_id:
                continue
            contracts = record.employee_id._get_contracts(record.date_from.date(), record.date_to.date())
            record.contract_id = contracts[0] if contracts else False

    @api.constrains('date_from', 'date_to', 'employee_id')
    def _check_contract(self):
        for record in self:
            contract_id = self.env['hr.contract'].search([('employee_id', '=', record.employee_id.id),('state', '=', 'open')])
    
    @api.depends('leave_ids', 'leave_ids.days_used')
    def _days_used(self):
        for rec in self:
            rec.days_used += sum(value for value in rec.leave_ids.mapped('days_used') if isinstance(value, (int, float)))
    
    @api.onchange('ibc','force_ibc', 'number_of_days', 'date_from', 'date_to',)
    def force_ibc_amt(self):
        for record in self:
            if record.force_ibc and record.ibc != 0:
                record.payroll_value = (record.ibc / 30) * record.number_of_days
            else:
                record._compute_amount_license()
                
    def interrupt_vacation(self, interruption_date, reason_id, detail, days_returned, will_return=False, return_date=None):
        """Interrumpir vacaciones"""
        self.ensure_one()
        if not self.holiday_status_id.is_vacation:
            raise UserError(_("Solo se pueden interrumpir ausencias de tipo vacaciones."))
        if not interruption_date or interruption_date < self.date_from.date() or interruption_date > self.date_to.date():
            raise UserError(_("La fecha de interrupción debe estar dentro del período de vacaciones."))
        if days_returned <= 0:
            raise UserError(_("Debe indicar cuántos días se devuelven por la interrupción."))
        self.write({
            'is_vacation_interrupted': True,
            'vacation_interruption_date': interruption_date,
            'vacation_interruption_reason_id': reason_id,
            'vacation_interruption_detail': detail,
            'vacation_days_returned': days_returned,
            'vacation_will_return': will_return,
            'vacation_return_date': return_date,
            'date_to': datetime.combine(interruption_date, datetime.max.time())
        })
        if self.payroll_id and self.payroll_id.state in ['done', 'paid']:
            credit_note_vals = {
                'name': f"R{self.payroll_id.sequence_prefix}{self.employee_id.name}",
                'employee_id': self.employee_id.id,
                'date_from': self.date_from.date(),
                'date_to': interruption_date,
                'contract_id': self.contract_id.id,
                'struct_id': self.payroll_id.struct_id.id,
                'credit_note': True,
                'leave_id': self.id,
                'worked_days_line_ids': []  # Se calculará después
            }
            credit_note = self.env['hr.payslip'].create(credit_note_vals)
            message = _(f"""
            Vacaciones interrumpidas:
            - Fecha: {interruption_date}
            - Motivo: {self.vacation_interruption_reason_id.name}
            - Días devueltos: {days_returned}
            - Nota crédito: {credit_note.name}
            """)
            self.message_post(body=message)
            return {
                'name': _('Nota Crédito por Interrupción'),
                'type': 'ir.actions.act_window',
                'res_model': 'hr.payslip',
                'view_mode': 'form',
                'res_id': credit_note.id,
                'target': 'current'
            }
        return True
       

    @api.onchange('date_from', 'date_to', 'employee_id', 'holiday_status_id', 'number_of_days')
    def _compute_amount_license(self):
        for record in self:
            contracts = record.env['hr.contract'].search([('employee_id', '=', record.employee_id.id),('state','=','open')])
            ibc = 0.0
            amount = 0.0
            if contracts and self.date_to:
                annual_parameters = self.env['hr.annual.parameters'].search([('year', '=', record.date_to.date().year)], limit=1)
                if record.holiday_status_id.liquidacion_value == 'IBC':
                    record.ibc = self._get_ibc_last_month(record.date_to.date(), record.contract_id)
                elif record.holiday_status_id.liquidacion_value in ['WAGE', 'MIN']:
                    record.ibc = self._get_wage_in_date(record.date_to.date(), record.contract_id)
                elif record.holiday_status_id.liquidacion_value == 'YEAR':
                    record.ibc = self._get_average_last_year(record.contract_id)
                else:
                    record.ibc = record.contract_id.wage
                if record.line_ids:
                    record.payroll_value = sum(x.amount for x in record.line_ids)
                else:
                    if record.request_unit_hours:
                        record.payroll_value = (record.ibc / annual_parameters.hours_monthly) * record.number_of_hours_display
                    else:
                        record.payroll_value = (record.ibc / 30) * record.number_of_days

    def _get_wage_in_date(self, process_date, contract):
        wage_in_date = contract.wage
        for change in sorted(contract.change_wage_ids, key=lambda x: x.date_start):
            if process_date >= change.date_start:
                wage_in_date = change.wage
        return wage_in_date

    def _get_ibc_last_month(self, date_to, contract):
        """
        Obtiene el IBC del mes anterior considerando las reglas de seguridad social.
        """
        from_date = (date_to.replace(day=1) - relativedelta(months=1))
        to_date = (date_to.replace(day=1) - relativedelta(days=1))
        annual_parameters = self.env['hr.annual.parameters'].search([
            ('year', '=', date_to.year)
        ], limit=1)
        if not annual_parameters:
            raise UserError(_(
                'No se encontraron parámetros anuales para el año %s.'
            ) % date_to.year)
        payslip_lines = self.env['hr.payslip.line'].search([
            ('slip_id.state', 'in', ['done', 'paid']),
            ('slip_id.contract_id', '=', contract.id),
            ('slip_id.date_from', '<=', to_date),
            ('slip_id.date_to', '>=', from_date),
        ])
        lines_by_type = {
            'base_ss': [],
            'no_salarial': [],
        }

        for line in payslip_lines:
            if line.salary_rule_id.base_seguridad_social:
                lines_by_type['base_ss'].append(line)
            
            if (line.salary_rule_id.category_id.code == 'DEV_NO_SALARIAL' or
                (line.salary_rule_id.category_id.parent_id and 
                line.salary_rule_id.category_id.parent_id.code == 'DEV_NO_SALARIAL')):
                lines_by_type['no_salarial'].append(line)

        value_base_ss = sum(abs(line.total) for line in lines_by_type['base_ss'])
        value_no_salarial = sum(abs(line.total) for line in lines_by_type['no_salarial'])

        gran_total = value_base_ss + value_no_salarial
        statute_value = gran_total * (annual_parameters.value_porc_statute_1395 / 100)
        total_statute = value_no_salarial - statute_value
        base_40 = max(total_statute, 0)
        ibc = value_base_ss + base_40
        calculo_detalle = {
            'periodo': {
                'desde': from_date,
                'hasta': to_date
            },
            'valores': {
                'base_seguridad_social': value_base_ss,
                'no_salarial': value_no_salarial,
                'total': gran_total
            },
            'estatuto_1395': {
                'porcentaje': annual_parameters.value_porc_statute_1395,
                'valor': statute_value
            },
            'calculo_40': {
                'excedente_estatuto': total_statute,
                'base_aplicada': base_40
            },
            'ibc_final': ibc,
            'detalle_conceptos': {
                'base_ss': [{'code': line.salary_rule_id.code, 
                            'name': line.salary_rule_id.name,
                            'valor': line.total} 
                        for line in lines_by_type['base_ss']],
                'no_salarial': [{'code': line.salary_rule_id.code,
                            'name': line.salary_rule_id.name,
                            'valor': line.total} 
                            for line in lines_by_type['no_salarial']]
            }
        }
        if (contract.fecha_ibc and 
            from_date.year == contract.fecha_ibc.year and 
            from_date.month == contract.fecha_ibc.month):
            return contract.u_ibc

        return ibc if ibc else contract.wage


    def calculate_average_salary(self, contract_id, end_date, months=3):
        calculated_start = end_date - relativedelta(months=months)
        start_date = max(calculated_start, contract_id.date_start)
        query = """
            WITH RECURSIVE date_ranges AS (
                SELECT
                    %s::date as date_from,
                    CASE
                        WHEN date_trunc('month', %s::date) = date_trunc('month', %s::date)
                        THEN %s::date
                        ELSE (date_trunc('month', %s::date) + interval '1 month - 1 day')::date
                    END as date_to,
                    date_trunc('month', %s::date) as month_start
                
                UNION ALL
                
                SELECT
                    (month_start + interval '1 month')::date as date_from,
                    CASE
                        WHEN date_trunc('month', month_start + interval '1 month') = date_trunc('month', %s::date)
                        THEN %s::date
                        ELSE ((month_start + interval '2 month - 1 day'))::date
                    END as date_to,
                    month_start + interval '1 month' as month_start
                FROM date_ranges
                WHERE month_start < date_trunc('month', %s::date)
            ),
            period_data AS (
                SELECT
                    dr.date_from,
                    dr.date_to,
                    CASE
                        WHEN extract(day from dr.date_from) = 1 AND 
                            extract(day from dr.date_to) >= 30
                        THEN 30
                        ELSE LEAST(
                            extract(day from dr.date_to) - 
                            extract(day from dr.date_from) + 1,
                            30 - extract(day from dr.date_from) + 1
                        )
                    END as days,
                    COALESCE(
                        (
                            SELECT wage
                            FROM hr_contract_change_wage wcw
                            WHERE wcw.contract_id = %s
                            AND wcw.date_start <= dr.date_from
                            ORDER BY wcw.date_start DESC
                            LIMIT 1
                        ),
                        %s
                    ) as wage
                FROM date_ranges dr
            )
            SELECT
                date_from,
                date_to,
                days,
                wage,
                (wage / 30.0 * days) as amount
            FROM period_data
            ORDER BY date_from;
        """
        self.env.cr.execute(query, (
            start_date, start_date, end_date, end_date, start_date, start_date,
            end_date, end_date, end_date,
            contract_id.id, contract_id.wage
        ))
        periods = self.env.cr.dictfetchall()
        if not periods:
            return contract_id.wage
        total_amount = 0
        total_days = 0
        for period in periods:
            total_amount += period['amount']
            total_days += period['days']
        average_salary = round((total_amount / total_days) * 30, 2) if total_days > 0 else contract_id.wage
        return average_salary



    def _get_average_last_year(self, contract):
        if not self.date_to or not self.date_from:
            return 0
        date_to = self.date_from.date()
        date_from = (date_to - relativedelta(years=1))
        initial_process_date = max(contract.date_start, date_from)
        if self.is_vacation:
            base_field = 'base_vacaciones'
        if self.is_vacation_money:
            base_field = 'base_vacaciones_dinero'

        PayslipLine = self.env['hr.payslip.line']
        Payslip = self.env['hr.payslip']
        AccumulatedPayroll = self.env['hr.accumulated.payroll']
        def get_payslip_total(contract_id, date_start, date_end):
            query_total = """
                SELECT COALESCE(SUM(pl.total), 0) as total
                FROM hr_payslip_line pl
                INNER JOIN hr_payslip hp ON pl.slip_id = hp.id
                INNER JOIN hr_salary_rule sr ON pl.salary_rule_id = sr.id
                INNER JOIN hr_salary_rule_category src ON sr.category_id = src.id
                WHERE hp.state IN ('done', 'paid')
                AND hp.contract_id = %(contract_id)s
                AND sr.code != 'AUX000'
                AND sr.""" + base_field + """ = true
                AND src.code != 'BASIC'
                AND (
                    (hp.date_from BETWEEN %(date_start)s AND %(date_end)s)
                    OR (hp.date_to BETWEEN %(date_start)s AND %(date_end)s)
                )
            """
            self.env.cr.execute(query_total, {
                'contract_id': contract.id,
                'date_start': date_start,
                'date_end': date_end
            })
            return self.env.cr.fetchone()[0] or 0

        payslip_total = get_payslip_total(contract, initial_process_date, self.date_to)
        accumulated_domain = [
            ('employee_id', '=', contract.employee_id.id),
            ('date', '>=', initial_process_date),
            ('date', '<=', self.date_to),
            ('salary_rule_id.code', '!=', 'AUX000'),
            ('salary_rule_id.' + base_field, '=', True),
            ('salary_rule_id.category_id.code', '!=', 'BASIC'),
        ]
        accumulated_payrolls = AccumulatedPayroll.search(accumulated_domain)
        accumulated_total = sum(accumulated_payrolls.mapped('amount'))
        
        dias_trabajados = self._days360(initial_process_date, self.date_to)
        dias_ausencias = self._get_unpaid_absence_days(initial_process_date, self.date_to, contract.employee_id)
        dias_liquidacion = dias_trabajados - dias_ausencias
        wage_average = self.calculate_average_salary(contract, date_to, 12)
        amount = payslip_total + accumulated_total
        if dias_liquidacion > 0:
            return  wage_average + (amount/dias_liquidacion) * 30  # ((amount + wage_average) / dias_liquidacion) * 30
        else:
            return 0

    def _get_average_last_year(self, contract):
        import logging
        _logger = logging.getLogger(__name__)
        
        def formato_moneda(monto):
            return "{:,.2f}".format(monto)
        
        detalles_log = []
        
        # Verificación inicial de fechas
        if not self.date_to or not self.date_from:
            _logger.info("No se especificó rango de fechas, retornando 0")
            return 0
            
        date_to = self.date_from.date()
        date_from = (date_to - relativedelta(years=1))
        initial_process_date = max(contract.date_start, date_from)
        
        # Registro del análisis de períodos
        detalles_log.append(f"Análisis de Período:")
        detalles_log.append(f"- Fecha Desde: {date_from}")
        detalles_log.append(f"- Fecha Hasta: {date_to}")
        detalles_log.append(f"- Inicio de Contrato: {contract.date_start}")
        detalles_log.append(f"- Fecha Inicial de Proceso: {initial_process_date}")
        base_field = 'base_vacaciones'
        # Determinación del tipo de cálculo
        if self.is_vacation:
            base_field = 'base_vacaciones'
            detalles_log.append("Tipo: Cálculo de vacaciones (base_vacaciones)")
        if self.is_vacation_money:
            base_field = 'base_vacaciones_dinero'
            detalles_log.append("Tipo: Cálculo de dinero de vacaciones (base_vacaciones_dinero)")
        
        PayslipLine = self.env['hr.payslip.line']
        Payslip = self.env['hr.payslip']
        AccumulatedPayroll = self.env['hr.accumulated.payroll']
        
        def get_payslip_total(contract_id, date_start, date_end):
            base_field = "base_vacaciones"
            # Consulta SQL para obtener el total de las nóminas
            query_total = """
                SELECT COALESCE(SUM(pl.total), 0) as total
                FROM hr_payslip_line pl
                INNER JOIN hr_payslip hp ON pl.slip_id = hp.id
                INNER JOIN hr_salary_rule sr ON pl.salary_rule_id = sr.id
                INNER JOIN hr_salary_rule_category src ON sr.category_id = src.id
                WHERE hp.state IN ('done', 'paid')
                AND hp.contract_id = %(contract_id)s
                AND sr.code != 'AUX000'
                AND sr.""" + base_field + """ = true
                AND src.code != 'BASIC'
                AND (
                    (hp.date_from BETWEEN %(date_start)s AND %(date_end)s)
                    OR (hp.date_to BETWEEN %(date_start)s AND %(date_end)s)
                )
            """
            self.env.cr.execute(query_total, {
                'contract_id': contract.id,
                'date_start': date_start,
                'date_end': date_end
            })
            return self.env.cr.fetchone()[0] or 0
        
        # Cálculo de totales de nómina
        payslip_total = get_payslip_total(contract, initial_process_date, self.date_to)
        detalles_log.append(f"\nAnálisis de Nómina:")
        detalles_log.append(f"- Total de nóminas: {formato_moneda(payslip_total)}")
        
        # Búsqueda de nóminas acumuladas
        accumulated_domain = [
            ('employee_id', '=', contract.employee_id.id),
            ('date', '>=', initial_process_date),
            ('date', '<=', self.date_to),
            ('salary_rule_id.code', '!=', 'AUX000'),
            ('salary_rule_id.' + base_field, '=', True),
            ('salary_rule_id.category_id.code', '!=', 'BASIC'),
        ]
        accumulated_payrolls = AccumulatedPayroll.search(accumulated_domain)
        accumulated_total = sum(accumulated_payrolls.mapped('amount'))
        detalles_log.append(f"- Total de nóminas acumuladas: {formato_moneda(accumulated_total)}")
        detalles_log.append(f"- Número de registros acumulados encontrados: {len(accumulated_payrolls)}")
        
        # Cálculo de días
        dias_trabajados = min(self._days360(initial_process_date, self.date_to), 360)
        dias_ausencias = self._get_unpaid_absence_days(initial_process_date, self.date_to, contract.employee_id)
        dias_liquidacion = dias_trabajados - dias_ausencias
        
        detalles_log.append(f"\nAnálisis de Días:")
        detalles_log.append(f"- Días trabajados totales (base 360): {dias_trabajados}")
        detalles_log.append(f"- Días de ausencia no pagados: {dias_ausencias}")
        detalles_log.append(f"- Días netos de liquidación: {dias_liquidacion}")
        
        # Cálculos finales
        wage_average = self.calculate_average_salary(contract, date_to, 12)
        amount = payslip_total + accumulated_total
        
        detalles_log.append(f"\nCálculos Finales:")
        detalles_log.append(f"- Salario base promedio: {formato_moneda(wage_average)}")
        detalles_log.append(f"- Monto total (nómina + acumulado): {formato_moneda(amount)}")
        
        result = 0
        if dias_liquidacion > 0:
            promedio_diario = amount/dias_liquidacion
            factor_mensual = promedio_diario * 30
            result = wage_average + factor_mensual
            detalles_log.append(f"- Promedio diario: {formato_moneda(promedio_diario)}")
            detalles_log.append(f"- Factor mensual (prom. diario * 30): {formato_moneda(factor_mensual)}")
            detalles_log.append(f"- Resultado final: {formato_moneda(result)}")
        else:
            detalles_log.append("- Resultado final: 0 (sin días de liquidación)")
        
        # Registro del análisis completo
        _logger.info("\n".join([
            "=" * 80,
            f"CÁLCULO DETALLADO DE PROMEDIO SALARIAL PARA EMPLEADO: {contract.employee_id.name}",
            f"CONTRATO: {contract.name}",
            "=" * 80,
            "\n".join(detalles_log),
            "=" * 80
        ]))
        
        return result
    def _days360(self, start_date, end_date, method_eu=True):
        """Compute number of days between two dates regarding all months
        as 30-day months"""

        start_day = start_date.day
        start_month = start_date.month
        start_year = start_date.year
        end_day = end_date.day
        end_month = end_date.month
        end_year = end_date.year

        if (
                start_day == 31 or
                (
                    method_eu is False and
                    start_month == 2 and (
                        start_day == 29 or (
                            start_day == 28 and
                            calendar.isleap(start_year) is False
                        )
                    )
                )
        ):
            start_day = 30

        if end_day == 31:
            if method_eu is False and start_day != 30:
                end_day = 1

                if end_month == 12:
                    end_year += 1
                    end_month = 1
                else:
                    end_month += 1
            else:
                end_day = 30
        if end_month == 2 and end_day in (28, 29):
            end_day = 30

        return (
            end_day + end_month * 30 + end_year * 360 -
            start_day - start_month * 30 - start_year * 360 + 1
        )

    def _get_unpaid_absence_days(self, start_date, end_date, employee):
        leaves = self.env['hr.leave'].search([
            ('date_from', '>=', start_date),
            ('date_to', '<=', end_date),
            ('state', '=', 'validate'),
            ('employee_id', '=', employee.id),
            ('unpaid_absences', '=', True)
        ])
        absence_histories = self.env['hr.absence.history'].search([
            ('star_date', '>=', start_date),
            ('end_date', '<=', end_date),
            ('employee_id', '=', employee.id),
            ('leave_type_id.unpaid_absences', '=', True)
        ])
        return sum(leave.number_of_days for leave in leaves) + sum(absence.days for absence in absence_histories)

    def _calculate_wage_average(self, start_date, end_date, contract):
        wage_average = 0
        current_date = start_date
        while current_date <= end_date:
            if current_date.day != 31:
                wage = self._get_wage_in_date(current_date, contract)
                if current_date.month == 2 and current_date.day == 28 and (current_date + timedelta(days=1)).day != 29:
                    wage_average += (wage / 30) * 3
                elif current_date.month == 2 and current_date.day == 29:
                    wage_average += (wage / 30) * 2
                else:
                    wage_average += wage / 30
            current_date += timedelta(days=1)
        return wage_average

    @api.onchange('is_extension')
    def _onchange_extension_id(self):
        for rec in self:
            if rec.date_to and rec.is_extension:
                last_leave = self.env['hr.leave'].search([('date_to', '<', rec.date_to),('state', '=', 'validate'),('holiday_status_id','=',rec.holiday_status_id.id),('employee_id','=',rec.employee_id.id)], order='date_to desc', limit=1)
                rec.extension_id = last_leave.id
            else:
                rec.extension_id = False

    @api.onchange('date_from', 'date_to', 'employee_id')
    def _onchange_leave_dates(self):
        if self.holiday_status_id.is_vacation == False:            
            if self.date_from and self.date_to:
                self.number_of_days = self._get_number_of_days(self.date_from, self.date_to, self.employee_id.id)['days']
            else:
                self.number_of_days = 0

    @api.onchange('employee_id','holiday_status_id')
    def _onchange_info_entity(self):
        for record in self:
            if record.employee_id and record.holiday_status_id:
                record.type_of_entity = record.holiday_status_id.type_of_entity_association.id
                for entities in record.employee_id.social_security_entities:
                    if entities.contrib_id.id == record.holiday_status_id.type_of_entity_association.id:                        
                        record.entity = entities.partner_id.id
            else:
                record.type_of_entity = False
                record.entity = False
                record.diagnostic = False

    @api.constrains('date_from', 'date_to', 'employee_id')
    def _check_date(self):
        if self.env.context.get('leave_skip_date_check', False):
            return

        all_employees = self.employee_ids
        all_leaves = self.search([
            ('date_from', '<', max(self.mapped('date_to'))),
            ('date_to', '>', min(self.mapped('date_from'))),
            ('employee_id', 'in', all_employees.ids),
            ('id', 'not in', self.ids),
            ('state', 'not in', ['cancel', 'refuse']),
        ])
        for holiday in self:
            if holiday.holiday_status_id.code == 'VAC_MONEY' or holiday.holiday_status_id.is_vacation_money:
                continue 
            domain = [
                ('date_from', '<', holiday.date_to),
                ('date_to', '>', holiday.date_from),
                ('id', '!=', holiday.id),
                ('state', 'not in', ['cancel', 'refuse']),
            ]

            employee_ids = (holiday.employee_id | holiday.employee_ids).ids
            search_domain = domain + [('employee_id', 'in', employee_ids)]
            conflicting_holidays = all_leaves.filtered_domain(search_domain)

            # Filter out VAC_MONEY leaves from conflicting_holidays
            conflicting_holidays = conflicting_holidays.filtered(lambda h: h.holiday_status_id.code != 'VAC_MONEY' or h.holiday_status_id.is_vacation_money)

            if conflicting_holidays:
                conflicting_holidays_list = []
                # Do not display the name of the employee if the conflicting holidays have an employee_id.user_id equivalent to the user id
                holidays_only_have_uid = bool(holiday.employee_id)
                holiday_states = dict(conflicting_holidays.fields_get(allfields=['state'])['state']['selection'])
                for conflicting_holiday in conflicting_holidays:
                    conflicting_holiday_data = {}
                    conflicting_holiday_data['employee_name'] = conflicting_holiday.employee_id.name
                    conflicting_holiday_data['date_from'] = format_date(self.env, min(conflicting_holiday.mapped('date_from')))
                    conflicting_holiday_data['date_to'] = format_date(self.env, min(conflicting_holiday.mapped('date_to')))
                    conflicting_holiday_data['state'] = holiday_states[conflicting_holiday.state]
                    if conflicting_holiday.employee_id.user_id.id != self.env.uid:
                        holidays_only_have_uid = False
                    if conflicting_holiday_data not in conflicting_holidays_list:
                        conflicting_holidays_list.append(conflicting_holiday_data)
                if not conflicting_holidays_list:
                    return
                conflicting_holidays_strings = []
                if holidays_only_have_uid:
                    for conflicting_holiday_data in conflicting_holidays_list:
                        conflicting_holidays_string = _('From %(date_from)s To %(date_to)s - %(state)s',
                                                        date_from=conflicting_holiday_data['date_from'],
                                                        date_to=conflicting_holiday_data['date_to'],
                                                        state=conflicting_holiday_data['state'])
                        conflicting_holidays_strings.append(conflicting_holidays_string)
                    raise ValidationError(_('You can not set two time off that overlap on the same day.\nExisting time off:\n%s') %
                                          ('\n'.join(conflicting_holidays_strings)))
                for conflicting_holiday_data in conflicting_holidays_list:
                    conflicting_holidays_string = _('%(employee_name)s - From %(date_from)s To %(date_to)s - %(state)s',
                                                    employee_name=conflicting_holiday_data['employee_name'],
                                                    date_from=conflicting_holiday_data['date_from'],
                                                    date_to=conflicting_holiday_data['date_to'],
                                                    state=conflicting_holiday_data['state'])
                    conflicting_holidays_strings.append(conflicting_holidays_string)
                conflicting_employees = set(employee_ids) - set(conflicting_holidays.employee_id.ids)
                # Only one employee has a conflicting holiday
                if len(conflicting_employees) == len(employee_ids) - 1:
                    raise ValidationError(_('You can not set two time off that overlap on the same day for the same employee.\nExisting time off:\n%s') %
                                          ('\n'.join(conflicting_holidays_strings)))
                raise ValidationError(_('You can not set two time off that overlap on the same day for the same employees.\nExisting time off:\n%s') %
                                      ('\n'.join(conflicting_holidays_strings)))



    @api.constrains('date_from', 'date_to', 'employee_id')
    def _check_date_state(self):
        if self.env.context.get('leave_skip_state_check'):
            return
        for holiday in self:
            if holiday.state in ['cancel', 'refuse', 'validate1', 'validate']:
                raise ValidationError(_("This modification is not allowed in the current state."))



    @api.onchange('number_of_days', 'request_date_from')
    def onchange_number_of_days_vacations(self):
        """
        Calcula los días de vacaciones considerando días laborales, festivos y días 31.
        También valida contra los días acumulados disponibles.
        """
        for record in self:
            try:
                # Solo proceder si es vacaciones y tiene fecha inicial
                if not (record.holiday_status_id.is_vacation and record.request_date_from):
                    continue

                _logger.info(f"Iniciando cálculo de vacaciones para empleado {record.employee_id.name}")
                
                # Configuración inicial
                lst_days = [5, 6] if not record.employee_id.sabado else [6]
                date_to = record.request_date_from - timedelta(days=1)
                cant_days = record.number_of_days
                
                _logger.info(f"Días iniciales a calcular: {cant_days}")
                
                # Contadores
                holidays = business_days = days_31_b = days_31_h = 0
                
                # Calcular días
                while cant_days > 0:
                    date_add = date_to + timedelta(days=1)
                    if not date_add.weekday() in lst_days:
                        #Obtener dias festivos parametrizados
                        obj_holidays = self.env['lavish.holidays'].search([('date', '=', date_add)])
                        if obj_holidays:
                            holidays += 1
                            days_31_h += 1 if date_add.day == 31 else 0
                            date_to = date_add
                        else:
                            cant_days = cant_days - 1     
                            business_days += 1
                            days_31_b += 1 if date_add.day == 31 else 0
                            date_to = date_add
                    else:
                        holidays += 1
                        days_31_h += 1 if date_add.day == 31 else 0
                        _logger.debug(f"Fin de semana: {date_add}")
                    
                    date_to = date_add
                
                _logger.info(f"""
                    Resultados del cálculo:
                    - Días laborales: {business_days}
                    - Días festivos: {holidays}
                    - Días 31 laborales: {days_31_b}
                    - Días 31 festivos: {days_31_h}
                """)

                

                
                # Verificar días acumulados disponibles
                contract_domain = [
                    ('employee_id', '=', record.employee_id.id),
                    ('state', '=', 'open'),
                    '|',
                    ('date_end', '=', False),
                    ('date_end', '>=', fields.Date.today())
                ]
                
                contract = self.env['hr.contract'].search(contract_domain, limit=1)
                
                if contract:
                    accumulated_days = contract.get_accumulated_vacation_days()
                    
                    _logger.info(f"""
                        Validación de días:
                        - Días solicitados: {business_days}
                        - Días acumulados: {accumulated_days}
                    """)
                    
                    # Actualizar campos relacionados con días acumulados
                    record.write({
                        'accumulated_vacation_days': accumulated_days,
                        'alert_days_vacation': business_days > accumulated_days
                    })
                    
                    if business_days > accumulated_days:
                        return {
                            'warning': {
                                'title': _('Advertencia'),
                                'message': _(
                                    'Los días solicitados ({:.2f}) superan los días disponibles ({:.2f}).'
                                ).format(business_days, accumulated_days)
                            }
                        }
                else:
                    _logger.warning(f"No se encontró contrato activo para el empleado {record.employee_id.name}")
                    return {
                        'warning': {
                            'title': _('Advertencia'),
                            'message': _('El empleado {} no tiene un contrato activo.').format(
                                record.employee_id.name
                            )
                        }
                    }
                
            except Exception as e:
                _logger.error('Error en cálculo de días de vacaciones: %s', str(e))
                return {
                    'warning': {
                        'title': _('Error'),
                        'message': _('Error al calcular los días de vacaciones. Por favor, verifique la configuración.')
                    }
                }

    # @api.constrains('state', 'number_of_days', 'holiday_status_id')
    # def _check_holidays(self):
    #     mapped_days = self.mapped('holiday_status_id').get_employees_days(self.mapped('employee_id').ids)
    #     for holiday in self:
    #         if holiday.holiday_type != 'employee' or not holiday.employee_id or holiday.holiday_status_id.requires_allocation == 'no':
    #             continue
    #         leave_days = mapped_days[holiday.employee_id.id][holiday.holiday_status_id.id]
    #         if float_compare(leave_days['remaining_leaves'], 0, precision_digits=2) == -1 or float_compare(leave_days['virtual_remaining_leaves'], 0, precision_digits=2) == -1:
    #             continue
    #             # # Se comenta validación original de odoo
    #             # raise ValidationError(_('The number of remaining time off is not sufficient for this time off type.\n'
    #             #                         'Please also check the time off waiting for validation.'))

    def action_force_paid(self):
        #Validación adjunto
        for holiday in self:
            holiday.line_ids.write({'state': 'paid'})
    def action_confirm(self):
        obj = super(HolidaysRequest, self).action_confirm()
        #Creación registro en el historico de vacaciones cuando es una ausencia no remunerada
        for record in self:
            if not record.line_ids:
                record.compute_holiday()
            record.line_ids.write({'state': 'validated'})
        return obj
    def action_approve(self):
        #Validación adjunto
        for holiday in self:
            if not holiday.line_ids:
                holiday.compute_holiday()
            # Validacion compañia
            if self.env.company.id != holiday.employee_id.company_id.id:
                raise ValidationError(_('El empleado ' + holiday.employee_id.name + ' esta en la compañía ' + holiday.employee_id.company_id.name + ' por lo cual no se puede aprobar debido a que se encuentra ubicado en la compañía ' + self.env.company.name + ', seleccione la compañía del empleado para aprobar la ausencia.'))
            # Validación adjunto
            if holiday.holiday_status_id.obligatory_attachment:
                attachment = self.env['ir.attachment'].search([('res_model', '=', 'hr.leave'),('res_id','=',holiday.id)])    
                if not attachment:    
                    raise ValidationError(_('Es obligatorio agregar un adjunto para la ausencia '+holiday.display_name+'.'))
            holiday.line_ids.write({'state': 'validated'})
        #Ejecución metodo estandar
        
        obj = super(HolidaysRequest, self).action_approve()
        #Creación registro en el historico de vacaciones cuando es una ausencia no remunerada
        for record in self:
            if not record.line_ids:
                record.compute_holiday()
            if record.unpaid_absences:
                days_unpaid_absences = record.number_of_days
                days_vacation_represent = round((days_unpaid_absences * 15) / 365,0)
                if days_vacation_represent > 0:
                    # Obtener contrato y ultimo historico de vacaciones
                    obj_contract = self.env['hr.contract'].search([('employee_id','=',record.employee_id.id),('state','=','open')])
                    date_vacation = obj_contract.date_start
                    obj_vacation = self.env['hr.vacation'].search(
                        [('employee_id', '=', record.employee_id.id), ('contract_id', '=', obj_contract.id)])
                    if obj_vacation:
                        for history in sorted(obj_vacation, key=lambda x: x.final_accrual_date):
                            date_vacation = history.final_accrual_date + timedelta(
                                days=1) if history.final_accrual_date > date_vacation else date_vacation
                    #Fechas de causación
                    initial_accrual_date = date_vacation
                    final_accrual_date = date_vacation + timedelta(days=days_vacation_represent)

                    info_vacation = {
                        'employee_id': record.employee_id.id,
                        'contract_id': obj_contract.id,
                        'initial_accrual_date': initial_accrual_date,
                        'final_accrual_date': final_accrual_date,
                        'departure_date': record.request_date_from,
                        'return_date': record.request_date_to,
                        'business_units': days_vacation_represent,
                        'leave_id': record.id
                    }
                    self.env['hr.vacation'].create(info_vacation)

        return obj

    def action_refuse(self):
        obj = super(HolidaysRequest, self).action_refuse()
        for record in self:
            self.env['hr.vacation'].search([('leave_id','=',record.id)]).unlink()
        return obj

    def action_validate(self):
        # Validación adjunto
        for holiday in self:
            if holiday.holiday_status_id.obligatory_attachment:
                attachment = self.env['ir.attachment'].search([('res_model', '=', 'hr.leave'), ('res_id', '=', holiday.id)])
                if not attachment:
                    raise ValidationError(_('Es obligatorio agregar un adjunto para la ausencia ' + holiday.display_name + '.'))
            holiday.line_ids.write({'state': 'validated'})
        # Ejecución metodo estandar
        obj = super(HolidaysRequest, self).action_validate()
        return obj

    @api.model_create_multi
    def create(self, vals_list):
        IrSequence = self.env['ir.sequence']
        
        for vals in vals_list:
            # Generate sequence for each record
            vals['sequence'] = IrSequence.next_by_code('seq.hr.leave') or ''
            
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

    #############################################################################################
    #GET HR_LEAVE_LINE
    #############################################################################################

    def compute_line(self):
        self.compute_holiday()

    def _get_number_of_days_batch_co(self, date_from, date_to, employee_ids):
        """ Returns a float equals to the timedelta between two dates given as string."""
        employee = self.env['hr.employee'].browse(employee_ids)
        # We force the company in the domain as we are more than likely in a compute_sudo
        domain = [('time_type', '=', 'leave'),
                  ('company_id', 'in', self.env.company.ids + self.env.context.get('allowed_company_ids', []))]
        result = employee._get_work_days_data_batch(date_from, date_to, compute_leaves=False, calendar=False,  domain=domain)
        for employee_id in result:
            if self.request_unit_half and result[employee_id]['hours'] > 0:
                result[employee_id]['days'] = 0.5
        return result

    def _get_number_of_days(self, date_from, date_to, employee_id):
        """ Returns a float equals to the timedelta between two dates given as string."""
        if employee_id:
            return self._get_number_of_days_batch_co(date_from, date_to, employee_id)[employee_id]

        today_hours = self.env.company.resource_calendar_id.get_work_hours_count(
            datetime.combine(date_from.date(), time.min),
            datetime.combine(date_from.date(), time.max),
            False)

        hours = self.env.company.resource_calendar_id.get_work_hours_count(date_from, date_to)
        days = hours / (today_hours or HOURS_PER_DAY) if not self.request_unit_half else 0.5
        return {'days': days, 'hours': hours}


    def _get_leaves_on_public_holiday(self):
        return False #self.filtered(lambda l: l.employee_id and not l.number_of_days)


    def _clean_leave(self):
        self.line_ids.unlink()

    def _is_holiday(self, date):
        return self.env['lavish.holidays'].ensure_holidays(date)

    def _should_apply_day_31(self, holiday):
        """
        Determina si se debe aplicar el día 31 para la ausencia dada.
        
        :param holiday: Registro de ausencia
        :return: True si se debe aplicar el día 31, False en caso contrario
        """
        return self.apply_day_31
    
    def _compute_return_date(self):
        self.ensure_one()
        if not self.date_to:
            return False
        end_date = self.date_to.date()
        next_day = end_date + timedelta(days=1)
        works_saturday = self.employee_id.sabado
        if self.holiday_status_id.apply_publicholiday:
            while True:
                is_saturday = next_day.weekday() == 5
                is_sunday = next_day.weekday() == 6
                is_holiday = self.env['lavish.holidays'].ensure_holidays(next_day)
                if (is_saturday and not works_saturday) or is_sunday or is_holiday:
                    next_day += timedelta(days=1)
                else:
                    break
        return next_day
    

    def calcular_valor_pago_incapacidad(self, day_data, current_date, sequence, is_rest_day, is_day_31):
        holiday = self
        
        apply_day_31 = holiday.holiday_status_id.apply_day_31
        discount_rest_day = holiday.holiday_status_id.discount_rest_day
        apply_publicholiday = holiday.holiday_status_id.apply_publicholiday
        liquidacion_type = holiday.holiday_status_id.liquidacion_value
        annual_parameters = self.env['hr.annual.parameters'].search([('year', '=', holiday.date_from.year)])
        smmlv = annual_parameters.smmlv_monthly
        hours_monthly = annual_parameters.hours_monthly or 240
        
        if is_day_31 and not apply_day_31:
            return 0
        
        if is_rest_day and discount_rest_day and not apply_publicholiday:
            return 0
        
        if bool(liquidacion_type == 'IBC'):
            base_amount = holiday.ibc
        elif bool(liquidacion_type == 'YEAR'):
            base_amount = holiday._get_average_last_year(holiday.contract_id)
        elif bool(liquidacion_type == 'MIN'):
            base_amount = smmlv
        else: 
            base_amount = holiday.contract_id.wage
        rate, rule = holiday.holiday_status_id.get_rate_concept_id(sequence)
        if holiday.holiday_status_id.code == 'EGA' and sequence <= holiday.holiday_status_id.num_days_no_assume:
            if holiday.holiday_status_id.liquidacion_value == 'WAGE':
                if holiday.request_unit_hours:
                    amount_real = (holiday.contract_id.wage / hours_monthly) * day_data['hours']
                else:
                    amount_real = holiday.contract_id.wage / 30
            else:
                if holiday.request_unit_hours:
                    amount_real = (base_amount / hours_monthly) * day_data['hours']
                else:
                    amount_real = base_amount / 30
        elif holiday.holiday_status_id.novelty == 'irl' and sequence == 1:
            if holiday.request_unit_hours:
                amount_real = (base_amount / hours_monthly) * day_data['hours']
            else:
                amount_real = base_amount / 30
        else:
            if holiday.request_unit_hours:
                amount_real = (base_amount / hours_monthly) * day_data['hours'] * rate
            else:
                amount_real = base_amount * rate / 30
        if holiday.force_porc != 0:
            if holiday.request_unit_hours:
                amount_real = (base_amount / hours_monthly) * day_data['hours'] * holiday.force_porc / 100
            else:
                amount_real = (base_amount / 30) * holiday.force_porc / 100
        if liquidacion_type == 'MIN':
            if holiday.request_unit_hours:
                min_hourly = smmlv / hours_monthly
                amount_real = max(amount_real, min_hourly * day_data['hours'])
            else:
                min_daily = smmlv / 30
                amount_real = max(amount_real, min_daily)
        if holiday.holiday_status_id.completar_salario and rate < 1:
            return amount_real
        return amount_real
    
    def compute_holiday(self):
        for holiday in self:
            if not holiday.contract_id:
                raise UserError(_('¡Error! La licencia no tiene contrato asignado.'))
            if not holiday.contract_id.resource_calendar_id:
                raise UserError(_('¡Error! El contrato no tiene un horario laboral definido.'))
            holiday.line_ids.unlink()
            sequence = 0
            if holiday.extension_id:
                last_sequence = holiday.extension_id.line_ids.mapped('sequence')
                if last_sequence:
                    sequence = max(last_sequence)
            if holiday.holiday_status_id.is_vacation:
                holiday.return_date = self._compute_return_date()
            if holiday.holiday_status_id.is_vacation_money:
                self._compute_vacation_money(holiday, sequence)
            else:
                self._compute_regular_leave(holiday, sequence)
            self.validate_february_days(holiday)
            holiday.payroll_value = sum(x.amount for x in holiday.line_ids)
            holiday.number_of_days = sum(x.days_payslip for x in holiday.line_ids)

            return True
    
    def _compute_vacation_money(self, holiday, sequence):
        days_to_process = int(holiday.number_of_vac_money_days)
        current_date = holiday.date_from.date()
        
        liquidacion_type = holiday.holiday_status_id.liquidacion_value
        annual_parameters = self.env['hr.annual.parameters'].search([('year', '=', holiday.date_from.year)])
        smmlv = annual_parameters.smmlv_monthly
        
        if bool(liquidacion_type == 'IBC'):
            amount = holiday.ibc_pila
        elif bool(liquidacion_type == 'YEAR'):
            amount = holiday._get_average_last_year(holiday.contract_id)
        elif bool(liquidacion_type == 'MIN'):
            amount = smmlv
        else: 
            amount = holiday.contract_id.wage
        
        for day in range(days_to_process):
            sequence += 1
            
            day_from = datetime.combine(current_date, time.min).replace(tzinfo=UTC)
            day_to = datetime.combine(current_date, time.max).replace(tzinfo=UTC)
            day_data = holiday._get_number_of_days(day_from, day_to, holiday.employee_id.id)
            
            amount_real = amount / 30
            
            if liquidacion_type == 'MIN':
                amount_real = max(amount_real, (smmlv/30))
            
            vals = {
                'leave_id': holiday.id,
                'sequence': sequence,
                'name': current_date.strftime('%Y-%m-%d'),
                'date': current_date,
                'hours_assigned': day_data['hours'],
                'days_assigned': 1,
                'hours': day_data['hours'],
                'days_payslip': 1,
                'day': str(current_date.weekday()),
                'days_work': 1,
                'days_holiday': 0,
                'days_31': 1 if current_date.day == 31 else 0,
                'days_holiday_31': 0,
                'amount': amount_real,
                'rule_id': holiday.holiday_status_id.get_rate_concept_id(sequence)[1],
            }
            self.env['hr.leave.line'].create(vals)
            current_date += timedelta(days=1)
    
    
    def _compute_regular_leave(self, holiday, sequence):
        date_from = holiday.date_from.replace(tzinfo=UTC)
        date_to = holiday.date_to.replace(tzinfo=UTC)

        if holiday.request_unit_hours and (date_to.date() - date_from.date()).days > 0:
            raise UserError(_('Advertencia: Las solicitudes de licencia por horas no deben abarcar varios días.'))

        current_date = date_from.date()
        
        apply_day_31 = holiday.holiday_status_id.apply_day_31
        discount_rest_day = holiday.holiday_status_id.discount_rest_day
        apply_publicholiday = holiday.holiday_status_id.apply_publicholiday
        
        while current_date <= date_to.date():
            sequence += 1
            
            day_from = datetime.combine(current_date, time.min).replace(tzinfo=UTC)
            day_to = datetime.combine(current_date, time.max).replace(tzinfo=UTC)
            if holiday.request_unit_hours:
                if current_date == date_from.date():
                    day_from = date_from
                if current_date == date_to.date():
                    day_to = date_to
            day_data = holiday._get_number_of_days(day_from, day_to, holiday.employee_id.id)
            
            is_day_31 = current_date.day == 31
            is_holiday = holiday._is_holiday(current_date)
            is_sunday = current_date.weekday() == 6
            is_saturday = current_date.weekday() == 5 and not holiday.employee_id.sabado
            is_rest_day = is_holiday or is_sunday or is_saturday
            
            days_payslip = day_data['days']
            days_work = day_data['days']
            hours_payslip = day_data['hours']
            days_holiday = 0
            days_holiday_31 = 0
            days_31 = 0
            
            if is_day_31:
                if apply_day_31:
                    if is_rest_day:
                        days_holiday_31 = day_data['days']
                        days_31 = 0
                    else:
                        days_31 = day_data['days']
                else:
                    days_payslip = 0
                    days_work = 0
                    hours_payslip = 0
                    days_holiday_31 = 0
                    days_31 = 0
            
            if is_rest_day:
                if apply_publicholiday:
                    days_holiday = day_data['days']
                else:
                    days_holiday = 0
                    
                if discount_rest_day:
                    days_work = 0
                    if not apply_publicholiday:
                        days_payslip = 0
                        hours_payslip = 0
            amount_real = holiday.calcular_valor_pago_incapacidad(
                day_data, current_date, sequence, is_rest_day, is_day_31
            )
            _, rule = holiday.holiday_status_id.get_rate_concept_id(sequence)

            vals = {
                'leave_id': holiday.id,
                'sequence': sequence,
                'name': current_date.strftime('%Y-%m-%d'),
                'date': current_date,
                'hours_assigned': day_data['hours'],
                'days_assigned': day_data['days'],
                'hours': hours_payslip,
                'days_payslip': days_payslip,
                'day': str(current_date.weekday()),
                'days_work': days_work,
                'days_holiday': days_holiday,
                'days_31': days_31,
                'days_holiday_31': days_holiday_31,
                'amount': amount_real,
                'rule_id': rule,
            }
            self.env['hr.leave.line'].create(vals)
            current_date += timedelta(days=1)
    
    def validate_february_days(self, leave):
        if not leave.contract_id:
            return
            
        start_month = leave.date_from.month if leave.date_from else 0
        end_month = leave.date_to.month if leave.date_to else 0
        
        if not (start_month == 2 or end_month == 2):
            return
            
        year = leave.date_from.year
        feb_last_day = 29 if calendar.isleap(year) else 28
        
        if end_month == 2 and leave.date_to.day == feb_last_day:
            sequence = max(leave.line_ids.mapped('sequence')) if leave.line_ids else 0
            liquidacion_type = leave.holiday_status_id.liquidacion_value
            annual_parameters = self.env['hr.annual.parameters'].search([('year', '=', leave.date_from.year)])
            smmlv = annual_parameters.smmlv_monthly
            if bool(liquidacion_type == 'IBC'):
                amount = leave.ibc
            elif bool(liquidacion_type == 'YEAR'):
                amount = leave._get_average_last_year(leave.contract_id)
            elif bool(liquidacion_type == 'MIN'):
                amount = smmlv
            else:
                amount = leave.contract_id.wage
            
            for virtual_day in range(feb_last_day + 1, 31):
                sequence += 1
                
                virtual_date = date(year, 2, feb_last_day)
                
                amount_real = amount / 30
                if liquidacion_type == 'MIN':
                    amount_real = max(amount_real, (smmlv/30))
                
                vals = {
                    'leave_id': leave.id,
                    'sequence': sequence,
                    'name': f'2-{virtual_day}-{year}',
                    'date': virtual_date,
                    'hours_assigned': 8,
                    'days_assigned': 1,
                    'hours': 8,
                    'days_payslip': 1,
                    'day': str(virtual_date.weekday()),
                    'days_work': 1,
                    'days_holiday': 0,
                    'days_31': 0,
                    'days_holiday_31': 0,
                    'amount': amount_real,
                    'rule_id': leave.holiday_status_id.eps_arl_input_id.id,
                    'is_virtual_day': True,
                    'virtual_day_number': virtual_day
                }
                self.env['hr.leave.line'].create(vals)

        
    def recompute_amounts(self):
        """Recomputar montos de las líneas no pagadas"""
        for holiday in self:
            if not holiday.contract_id:
                raise UserError(_('¡Error! La licencia no tiene contrato asignado.'))
            if not holiday.contract_id.resource_calendar_id:
                raise UserError(_('¡Error! El contrato no tiene un horario laboral definido.'))

            annual_parameters = self.env['hr.annual.parameters'].search([('year', '=', holiday.date_from.year)])
            smmlv = annual_parameters.smmlv_monthly
            amount = holiday.ibc
            _logger.error('Recomputing amounts %s', amount)
            unpaid_lines = holiday.line_ids.filtered(lambda x: not x.state == 'paid')
            for line in unpaid_lines:
                rate, rule = holiday.holiday_status_id.get_rate_concept_id(line.sequence)
                if holiday.holiday_status_id.code == 'EGA' and line.sequence <= holiday.holiday_status_id.num_days_no_assume:
                    amount_real = amount / 30
                elif holiday.holiday_status_id.novelty == 'irl' and line.sequence == 1:
                    amount_real = amount / 30
                else:
                    amount_real = amount * rate / 30

                if holiday.force_porc != 0:
                    amount_real = (amount / 30) * holiday.force_porc / 100

                if holiday.request_unit_hours:
                    daily_rate = amount / annual_parameters.hours_monthly
                    amount_real = daily_rate * line.hours
                elif holiday.force_ibc:
                    amount_real = amount_real
                else:
                    amount_real = max(amount_real, (smmlv/30))

                is_day_31 = line.date.day == 31
                if is_day_31 and not self._should_apply_day_31(holiday):
                    amount_real = 0

                line.write({
                    'amount': amount_real,
                    'rule_id': rule,
                })
            _logger.error('Recomputed amounts for holiday %s', amount_real)
            holiday.payroll_value = sum(x.amount for x in holiday.line_ids)

        return True

    def update_ibc_and_recompute(self, new_ibc):
        """Actualizar IBC y recomputar montos"""
        self.ensure_one()
        self.write({'ibc': new_ibc})
        return self.recompute_amounts() 
    
    def _cancel_work_entry_conflict(self):
        leaves_to_defer = self.filtered(lambda l: l.payslip_state == 'blocked')
        leaves_vco = self.filtered(lambda l: l.holiday_status_id.code == 'vco')  # Filtrar las ausencias de tipo 'vco'
        
        for leave in leaves_to_defer:
            leave.activity_schedule(
                'hr_payroll_holidays.mail_activity_data_hr_leave_to_defer',
                summary=_('Validated Time Off to Defer'),
                note=_(
                    'Please create manually the work entry for %s',
                    leave.employee_id._get_html_link()),
                user_id=leave.employee_id.company_id.deferred_time_off_manager.id or self.env.ref('base.user_admin').id)
        
        for leave in leaves_vco:
            leave.activity_schedule('mail.mail_activity_data_todo', 
                summary=_('Compensación de vacaciones en dinero'),
                note=_(
                    'Compensación de vacaciones en dinero para %(employee)s.\n'
                    'Periodo de cobertura: desde %(start_date)s to %(end_date)s\n'
                    'Número de días: %(days)s'
                ) % {
                    'employee': leave.employee_id._get_html_link(),
                    'start_date': leave.date_from.date(),
                    'end_date': leave.date_to.date(),
                    'days': leave.number_of_days
                },
                user_id=leave.employee_id.company_id.deferred_time_off_manager.id or self.env.ref('base.user_admin').id
            )
            
        return super(HolidaysRequest, self - leaves_to_defer - leaves_vco)._cancel_work_entry_conflict()


class hr_leave_diagnostic(models.Model):
    _name = "hr.leave.diagnostic"
    _description = "Diagnosticos Ausencias"

    name = fields.Char('Nombre', required=True)
    code = fields.Char('Código', required=True)

    _sql_constraints = [('leave_diagnostic_code_uniq', 'unique(code)',
                         'Ya existe un diagnóstico con este código, por favor verificar.')]

    def _compute_display_name(self):
        result = []
        for record in self:
            record.display_name = "{} | {}".format(record.code,record.name)

    @api.model
    def _name_search(self, name, args=None, operator='ilike',
                     limit=100, name_get_uid=None,order=None):
        args = args or []
        if operator == 'ilike' and not (name or '').strip():
            domain = []
        else:
            domain = ['|', ('name', 'ilike', name),
                      ('code', 'ilike', name)]
        return self._search(expression.AND([domain, args]),
                            limit=limit, order=order,
                            access_rights_uid=name_get_uid)


class HrLeaveLine(models.Model):
    _name = 'hr.leave.line'
    _description = 'Lineas de Ausencia'
    _order = 'date desc'

    leave_id = fields.Many2one(comodel_name='hr.leave', string='Ausencia', required=True,ondelete='cascade')
    payslip_id = fields.Many2one(comodel_name='hr.payslip', string='Nónima')
    contract_id = fields.Many2one(string='Contrato', related='leave_id.contract_id')
    rule_id = fields.Many2one('hr.salary.rule', 'Reglas Salarial')
    date = fields.Date(string='Fecha')
    state = fields.Selection(
        string='Estado',
        selection=STATE,
        compute='_compute_state',
        store=True,
        default='draft'
    )
    amount = fields.Float(string='Valor')
    days_payslip = fields.Float(string='Dias en nomina')
    hours = fields.Float(string='Hora')
    days_assigned = fields.Float('Dias de asignacion')
    hours_assigned = fields.Float('Horas de asignacion')
    sequence = fields.Integer(string='Secuencia')
    name = fields.Char('Reason', size=128, help='Reason for holiday')
    day = fields.Selection([('0', 'Lunes'),
                            ('1', 'Martes'),
                            ('2', 'Miercoles'),
                            ('3', 'Jueves'),
                            ('4', 'Viernes'),
                            ('5', 'Sabado'),
                            ('6', 'Domingo'),
                            ], 'Dia Semana')
    days_work = fields.Float('Dias laborales')
    days_holiday = fields.Float('Dias Festivo')
    days_31 = fields.Float('Dias 31 laborales')
    days_holiday_31 = fields.Float('Dias 31 Festivo')
    is_virtual_day = fields.Boolean(
        string='Día Virtual',
        default=False,
        help='Indica si este registro corresponde a un día virtual añadido para completar cálculos.'
    )
    virtual_day_number = fields.Integer(
        string='Número de Día Virtual',
        help='Número del día virtual (29 o 30 para febrero)'
    )
    is_unused = fields.Boolean('No utilizado', default=False)
    unused_reason_id = fields.Many2one('hr.vacation.interruption.reason', 'Motivo de no uso')
    unused_detail = fields.Char('Detalle de no uso')
    unused_date = fields.Date('Fecha de marcado como no usado')
    will_be_used_later = fields.Boolean('Se usará después', default=False)
    future_use_date = fields.Date('Fecha futura de uso')


    @api.depends('leave_id.state','payslip_id', 'payslip_id.state')
    def _compute_state(self):
        for line in self:
            try:
                state = 'draft'
                if line.leave_id and line.leave_id.state == 'validate':
                    state = 'validated'
                if line.payslip_id and line.payslip_id.state in ['done', 'paid']:
                    state = 'paid'
                line.state = state
            except Exception as e:
                line.state = 'draft'

    @api.constrains('leave_id', 'payslip_id')
    def _check_leave_state_with_payslip(self):
        for line in self:
            if line.leave_id.state == 'draft' and line.payslip_id and line.payslip_id.state not in ['draft', 'cancel','verify']:
                raise UserError(_(
                    'No se puede cambiar la ausencia a estado borrador porque tiene una nómina asociada ({}).\n'
                    'Por favor, primero debe restablecer la nómina a estado borrador.'
                ).format(line.payslip_id.name))
            if line.leave_id.state == 'refuse' and line.payslip_id and line.payslip_id.state not in ['draft', 'cancel','verify']:
                raise UserError(_(
                    'No se puede cambiar la ausencia a estado Rechazada porque tiene una nómina asociada ({}).\n'
                    'Por favor, primero debe restablecer la nómina a estado borrador.'
                ).format(line.payslip_id.name))
            if line.leave_id.state == 'cancel' and line.payslip_id and line.payslip_id.state not in ['draft', 'cancel','verify']:
                raise UserError(_(
                    'No se puede cambiar la ausencia a estado Cancelada porque tiene una nómina asociada ({}).\n'
                    'Por favor, primero debe restablecer la nómina a estado borrador.'
                ).format(line.payslip_id.name))  
    
    def belongs_category(self, categories):
        return self.leave_id.leave_type_id.id in categories

    def unlink(self):
        for line in self:
            if line.payslip_id and line.payslip_id.state not in ['draft', 'cancel','verify']:
                raise UserError(_(
                    'No se puede eliminar la línea de ausencia porque está asociada a la nómina {} que está procesada.\n'
                    'Debe primero restablecer la nómina a estado borrador.'
                ).format(line.payslip_id.name))
            
            if line.leave_id.state == 'draft' and line.payslip_id and line.payslip_id.state not in ['draft', 'cancel','verify']:
                raise UserError(_(
                    'No se puede eliminar la línea de ausencia porque la ausencia está en borrador y tiene una nómina procesada ({}).\n'
                    'Por favor, primero debe restablecer la nómina a estado borrador.'
                ).format(line.payslip_id.name))
    
            if line.leave_id.state == 'refuse' and line.payslip_id and line.payslip_id.state not in ['draft', 'cancel','verify']:
                raise UserError(_(
                    'No se puede eliminar la línea de ausencia porque la ausencia está en borrador y tiene una nómina procesada ({}).\n'
                    'Por favor, primero debe restablecer la nómina a estado borrador.'
                ).format(line.payslip_id.name))
            _logger.info('Eliminando línea de ausencia %s de la ausencia %s', line.id, line.leave_id.name)
        
        return super(HrLeaveLine, self).unlink()

class HolidaySyncYear(models.Model):
    _name = 'lavish.holidays.sync'
    _description = 'Control de Años Sincronizados para Festivos'

    year = fields.Integer('Año', required=True)
    sync_date = fields.Datetime('Fecha de sincronización', default=fields.Datetime.now)
    
    _sql_constraints = [
        ('year_unique', 'unique(year)', 'El año debe ser único!')
    ]


class HolidaySync(models.Model):
    _inherit = 'lavish.holidays'

    @api.model
    def _is_year_synced(self, year):
        """Verifica si un año ya fue sincronizado"""
        return self.env['lavish.holidays.sync'].search_count([('year', '=', year)]) > 0

    @api.model
    def _mark_year_synced(self, year):
        """Marca un año como sincronizado"""
        if not self._is_year_synced(year):
            self.env['lavish.holidays.sync'].create({'year': year})

    @api.model
    def sync_holidays_for_year(self, year):
        """Sincroniza los festivos para un año si no están ya sincronizados"""
        pass
        # try:
        #     self.env.cr.execute('SAVEPOINT sync_holidays')
            
        #     if self._is_year_synced(year):
        #         return True

        #     holiday_list = get_colombia_holidays_by_year(year)
            
        #     # Obtener festivos existentes
        #     existing_holidays = self.env['lavish.holidays'].search([
        #         ('date', '>=', f'{year}-01-01'),
        #         ('date', '<=', f'{year}-12-31')
        #     ])
        #     existing_dates = {holiday.date for holiday in existing_holidays}

        #     # Obtener todas las ausencias existentes
        #     existing_leaves = self.env['resource.calendar.leaves'].search([
        #         ('date_from', '>=', f'{year}-01-01 00:00:00'),
        #         ('date_to', '<=', f'{year}-12-31 23:59:59')
        #     ])

        #     # Mapear fechas de ausencias existentes
        #     leave_dates = {}
        #     for leave in existing_leaves:
        #         date_from = leave.date_from.date()
        #         date_to = leave.date_to.date()
        #         current_date = date_from
        #         while current_date <= date_to:
        #             if current_date not in leave_dates:
        #                 leave_dates[current_date] = []
        #             leave_dates[current_date].append(leave.calendar_id.id)
        #             current_date += timedelta(days=1)

        #     # Preparar datos para crear
        #     calendars = self.env['resource.calendar'].search([('active', '=', True)])
        #     calendar_ids = calendars.ids

        #     for holiday in holiday_list:
        #         try:
        #             # Crear festivo si no existe
        #             if holiday.date not in existing_dates:
        #                 try:
        #                     self.env.cr.execute('SAVEPOINT create_holiday')
        #                     self.env['lavish.holidays'].create({
        #                         'date': holiday.date,
        #                         'name': holiday.celebration
        #                     })
        #                     self.env.cr.execute('RELEASE SAVEPOINT create_holiday')
        #                     _logger.info(f'Festivo creado: {holiday.celebration} - {holiday.date}')
        #                 except Exception as e:
        #                     self.env.cr.execute('ROLLBACK TO SAVEPOINT create_holiday')
        #                     _logger.error(f'Error creando festivo {holiday.celebration}: {str(e)}')

        #             # Crear ausencias en calendarios si no existen
        #             if holiday.date in leave_dates:
        #                 calendars_with_leave = leave_dates[holiday.date]
        #                 calendars_to_process = [cal_id for cal_id in calendar_ids if cal_id not in calendars_with_leave]
        #             else:
        #                 calendars_to_process = calendar_ids

        #             for calendar_id in calendars_to_process:
        #                 try:
        #                     self.env.cr.execute('SAVEPOINT create_leave')
        #                     self.env['resource.calendar.leaves'].create({
        #                         'name': f'Festivo: {holiday.celebration}',
        #                         'calendar_id': calendar_id,
        #                         'date_from': datetime.combine(holiday.date, datetime.min.time()),
        #                         'date_to': datetime.combine(holiday.date, datetime.max.time()),
        #                         'time_type': 'leave'
        #                     })
        #                     self.env.cr.execute('RELEASE SAVEPOINT create_leave')
        #                     _logger.info(f'Ausencia creada para calendario {calendar_id}: {holiday.celebration}')
        #                 except Exception as e:
        #                     self.env.cr.execute('ROLLBACK TO SAVEPOINT create_leave')
        #                     _logger.error(f'Error creando ausencia para calendario {calendar_id}: {str(e)}')

        #         except Exception as e:
        #             _logger.error(f'Error procesando festivo {holiday.celebration}: {str(e)}')
        #             continue

        #     self._mark_year_synced(year)
        #     self.env.cr.execute('RELEASE SAVEPOINT sync_holidays')
        #     return True

        # except Exception as e:
        #     self.env.cr.execute('ROLLBACK TO SAVEPOINT sync_holidays')
        #     _logger.error(f'Error general sincronizando festivos del año {year}: {str(e)}')
        #     return False

    @api.model
    def ensure_holidays(self, check_date):
        """
        Asegura que los festivos estén creados para una fecha dada
        Retorna True si es festivo, False si no lo es
        """
        if isinstance(check_date, datetime):
            check_date = check_date.date()
            
        year = check_date.year
        if not self._is_year_synced(year):
            self.sync_holidays_for_year(year)
        return self.search_count([('date', '=', check_date)]) > 0

    @api.model
    def cron_sync_next_year(self):
        """Cron job para sincronizar el próximo año"""
        next_year = fields.Date.today().year + 1
        if not self._is_year_synced(next_year):
            self.sync_holidays_for_year(next_year)
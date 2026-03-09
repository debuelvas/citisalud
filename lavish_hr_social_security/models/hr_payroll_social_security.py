# -*- coding: utf-8 -*-

from logging import exception
from odoo import models, fields, api, _, SUPERUSER_ID
from odoo.exceptions import UserError, ValidationError
from datetime import datetime, timedelta,date
from dateutil.relativedelta import relativedelta
from decimal import *
from odoo import registry as registry_get
import base64
import io
import xlsxwriter
import odoo
import threading
import math
import calendar
import logging
_logger = logging.getLogger(__name__)
from odoo.tools import float_round, date_utils, convert_file, html2plaintext
from odoo.tools.float_utils import float_compare
from typing import List, Tuple, Dict, Any
from collections import defaultdict, Counter
def days360(start_date, end_date, method_eu=True):
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
class BrowsableObject(object):
    def __init__(self, employee_id, dict, env):
        self.employee_id = employee_id
        self.dict = dict
        self.env = env

    def __getattr__(self, attr):
        return attr in self.dict and self.dict.__getitem__(attr) or 0.0
def roundup100(amount):
    return math.ceil(amount / 100.0) * 100
def roundupdecimal(amount):
    return math.ceil(amount)
class hr_payroll_social_security(models.Model):
    _name = 'hr.payroll.social.security'
    _description = 'Seguridad Social'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_end desc, id desc'


    sequence = fields.Char(string=' Sequencia')
    name = fields.Char('Nombre', compute='_compute_name', store=True)
    year = fields.Integer('Año', required=True, index=True)
    month = fields.Selection([('1', 'Enero'),
                            ('2', 'Febrero'),
                            ('3', 'Marzo'),
                            ('4', 'Abril'),
                            ('5', 'Mayo'),
                            ('6', 'Junio'),
                            ('7', 'Julio'),
                            ('8', 'Agosto'),
                            ('9', 'Septiembre'),
                            ('10', 'Octubre'),
                            ('11', 'Noviembre'),
                            ('12', 'Diciembre')        
                            ], string='Mes', required=True, index=True)
    observations = fields.Text('Observaciones')
    state = fields.Selection([
            ('draft', 'Borrador'),
            ('done', 'Realizado'),
            ('accounting', 'Contabilizado'),
        ], string='Estado', default='draft')
    #Proceso
    executing_social_security_ids = fields.One2many('hr.executing.social.security', 'executing_social_security_id', string='Ejecución')
    errors_social_security_ids = fields.One2many('hr.errors.social.security', 'executing_social_security_id', string='Advertencias')
    time_process = fields.Char(string='Tiempo ejecución')
    #Plano
    presentation_form = fields.Selection([('U', 'Único'),
                                            ('S','Sucursal')], string='Forma de presentación', default='U')
    branch_social_security_id = fields.Many2one('hr.social.security.branches',string='Sucursal', help='Seleccione la sucursal a generar el archivo plano.')
    work_center_social_security_id = fields.Many2one('hr.social.security.work.center', string='Centro de trabajo seguridad social', help='Seleccione el centro de trabajo a generar el archivo plano, si deja el campo vacio se generara con todos los centros de trabajo.')
    #Archivos
    excel_file = fields.Binary('Excel file')
    excel_file_name = fields.Char('Excel name')
    txt_file = fields.Binary('TXT file')
    txt_file_name = fields.Char('TXT name')
    # Campos básicos
    date_start = fields.Date('Fecha Inicio',  index=True)
    date_end = fields.Date('Fecha Fin', compute='_compute_date_end', store=True)
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('accounting', 'Contabilizado'),
        ('done', 'Hecho'),
        ('error', 'Error')
    ], default='draft', index=True)

    # Relaciones
    executing_social_security_ids = fields.One2many(
        'hr.executing.social.security',
        'executing_social_security_id',
        string='Líneas de Seguridad Social'
    )
    fecha_limite_pago = fields.Date(
        string='Fecha Límite de Pago',
        compute='_compute_fecha_limite_pago',
        store=True
    )

    # Campos calculados
    total_employees = fields.Integer(
        'Total Empleados', 
        compute='_compute_total_employees',
        store=True
    )
    total_base_ss = fields.Float(
        'Base Total SS',
        compute='_compute_total_base_ss',
        store=True
    )
    health_system_date_start = fields.Date('Fecha Inicio Salud', compute='_compute_dates', store=True)
    health_system_date_end = fields.Date('Fecha Fin Salud', compute='_compute_dates', store=True)
    system_date_different_health_start = fields.Date('Fecha Inicio Resto de entidades', compute='_compute_dates', store=True)
    system_date_different_health_end = fields.Date('Fecha Fin Resto de entidades', compute='_compute_dates', store=True)
    presentation_type = fields.Selection([
        ('E', 'Empleador'),
        ('A', 'Administrador'),
        ('I', 'Independiente')
    ], string='Tipo de Presentación', default='E')
    arl_id = fields.Many2one('hr.employee.entities', string='ARL', compute='_compute_arl', store=True)
    sequence = fields.Char('Secuencia', readonly=True, default=lambda self: self._get_sequence())
    number_settlement = fields.Char(string='No. Settlement')

    move_id = fields.Many2one('account.move', string='Contabilidad')
    company_id = fields.Many2one('res.company', string='Compañía', readonly=True, required=True,
        default=lambda self: self.env.company)
    total_amount_employees = fields.Float('Total a Pagar Empleados', compute='_compute_amounts', store=True)
    total_amount_company = fields.Float('Total a Pagar Empresa', compute='_compute_amounts', store=True)
    total_amount_final = fields.Float('Total a Pagar', compute='_compute_amounts', store=True)
    total_health = fields.Float('Total Salud', compute='_compute_totals', store=True)
    total_pension = fields.Float('Total Pensión', compute='_compute_totals', store=True)
    total_solidarity = fields.Float('Total Solidaridad', compute='_compute_totals', store=True)
    total_arl = fields.Float('Total ARL', compute='_compute_totals', store=True)
    total_parafiscal = fields.Float('Total Parafiscales', compute='_compute_totals', store=True)

    executing_line_count = fields.Integer(compute='_compute_counts')
    payslip_count = fields.Integer(compute='_compute_counts')
    employee_count = fields.Integer(compute='_compute_counts')
    contract_count = fields.Integer(compute='_compute_counts')
    error_count = fields.Integer(compute='_compute_counts')


    @api.depends('year', 'month')
    def _compute_name(self):
        """
        Calcula el nombre del registro de seguridad social basado en año y mes
        """
        months = {
            '1': 'Enero', '2': 'Febrero', '3': 'Marzo',
            '4': 'Abril', '5': 'Mayo', '6': 'Junio',
            '7': 'Julio', '8': 'Agosto', '9': 'Septiembre',
            '10': 'Octubre', '11': 'Noviembre', '12': 'Diciembre'
        }
        
        for record in self:
            if record.year and record.month:
                record.name = f'Seguridad Social {months.get(record.month)} {record.year}'
            else:
                record.name = 'Nuevo'
    def _is_holiday(self, date):         
        return self.env['lavish.holidays'].search_count([('date', '=', date)]) > 0
    
    @api.depends('year', 'month', 'company_id')
    def _compute_fecha_limite_pago(self):
        """
        Calcula la fecha límite de pago basado en los últimos dígitos del NIT
        """
        for record in self:
            if not record.year or not record.month or not record.company_id.partner_id.vat_co:
                record.fecha_limite_pago = False
                continue

            company_vat = record.company_id.partner_id.vat_co
            last_digits = company_vat[-2:] if len(company_vat) >= 2 else '00'
            last_digits = int(last_digits)

            day_ranges = [
                (0, 7), (8, 14), (15, 21), (22, 28), (29, 35),
                (36, 42), (43, 49), (50, 56), (57, 63), (64, 69),
                (70, 75), (76, 81), (82, 87), (88, 93), (94, 99)
            ]

            payment_range = None
            for i, (start, end) in enumerate(day_ranges):
                if start <= last_digits <= end:
                    payment_range = i + 2  
                    break

            if not payment_range:
                record.fecha_limite_pago = False
                continue

            if record.month == '12':
                next_month = 1
                next_year = record.year + 1
            else:
                next_month = int(record.month) + 1
                next_year = record.year

            base_date = date(next_year, next_month, payment_range)

            current_date = base_date
            while record._is_holiday(current_date) or current_date.weekday() in (5, 6):
                current_date += timedelta(days=1)

            record.fecha_limite_pago = current_date

    @api.depends('year', 'month')
    def _compute_dates(self):
        """
        Calcula las fechas de inicio y fin para los períodos de seguridad social
        Las fechas se calculan según las reglas de la PILA:
        - El período de cotización para salud es el mes siguiente al período trabajado
        - Para los otros sistemas es el mismo período trabajado
        """
        for record in self:
            if record.year and record.month:
                month = int(record.month)
                year = record.year

                health_month = month + 1 if month < 12 else 1
                health_year = year if month < 12 else year + 1

                record.health_system_date_start = date(health_year, health_month, 1)
                record.health_system_date_end = date(
                    health_year, 
                    health_month, 
                    calendar.monthrange(health_year, health_month)[1]
                )

                # Calcular fechas para otros sistemas (mes actual)
                record.system_date_different_health_start = date(year, month, 1)
                record.system_date_different_health_end = date(
                    year,
                    month,
                    calendar.monthrange(year, month)[1])
    @api.depends('company_id', 'company_id.entity_arp_id')
    def _compute_arl(self):
        """
        Obtiene la ARL automáticamente desde la configuración de la compañía
        """
        for record in self:
            record.arl_id = record.company_id.entity_arp_id

    @api.model
    def _get_sequence(self):
        """
        Genera una secuencia automática para el registro
        Format: SSYYMM####
        SS: Seguridad Social
        YY: Año (2 dígitos)
        MM: Mes (2 dígitos)
        ####: Secuencia numérica
        """
        prefix = "SS"
        if self.year and self.month:
            year_suffix = str(self.year)[-2:]
            month_suffix = str(self.month).zfill(2)
        else:
            today = fields.Date.today()
            year_suffix = str(today.year)[-2:]
            month_suffix = str(today.month).zfill(2)
            
        sequence = self.env['ir.sequence'].next_by_code('hr.payroll.social.security.sequence')
        return f"{prefix}{year_suffix}{month_suffix}{sequence}"
    @api.depends('year', 'month')
    def _compute_name(self):
        """
        Calcula el nombre del registro de seguridad social basado en año y mes
        """
        months = {
            '1': 'Enero', '2': 'Febrero', '3': 'Marzo',
            '4': 'Abril', '5': 'Mayo', '6': 'Junio',
            '7': 'Julio', '8': 'Agosto', '9': 'Septiembre',
            '10': 'Octubre', '11': 'Noviembre', '12': 'Diciembre'
        }
        
        for record in self:
            if record.year and record.month:
                record.name = f'Seguridad Social {months.get(record.month)} {record.year}'
            else:
                record.name = 'Nuevo'

    def _compute_counts(self):
        for rec in self:
            rec.executing_line_count = len(rec.executing_social_security_ids)
            rec.payslip_count = len(rec.executing_social_security_ids.mapped('payslip_ids'))
            rec.employee_count = len(rec.executing_social_security_ids.mapped('employee_id'))
            rec.contract_count = len(rec.executing_social_security_ids.mapped('contract_id'))
            rec.error_count = len(rec.errors_social_security_ids)

    def action_view_executing_lines(self):
        return {
            'name': 'Líneas de Ejecución',
            'view_mode': 'list,form',
            'res_model': 'hr.executing.social.security',
            'domain': [('executing_social_security_id', '=', self.id)],
            'type': 'ir.actions.act_window',
            'context': {'default_executing_social_security_id': self.id}
        }

    def action_view_payslips(self):
        return {
            'name': 'Nóminas',
            'view_mode': 'list,form',
            'res_model': 'hr.payslip',
            'domain': [('id', 'in', self.executing_social_security_ids.mapped('payslip_ids').ids)],
            'type': 'ir.actions.act_window'
        }

    def action_view_employees(self):
        return {
            'name': 'Empleados',
            'view_mode': 'list,form',
            'res_model': 'hr.employee',
            'domain': [('id', 'in', self.executing_social_security_ids.mapped('employee_id').ids)],
            'type': 'ir.actions.act_window'
        }

    def action_view_contracts(self):
        return {
            'name': 'Contratos',
            'view_mode': 'list,form', 
            'res_model': 'hr.contract',
            'domain': [('id', 'in', self.executing_social_security_ids.mapped('contract_id').ids)],
            'type': 'ir.actions.act_window'
        }

    def action_view_errors(self):
        return {
            'name': 'Errores',
            'view_mode': 'list,form',
            'res_model': 'hr.errors.social.security',
            'domain': [('executing_social_security_id', '=', self.id)],
            'type': 'ir.actions.act_window'
        }
    @api.depends('executing_social_security_ids.nValorSaludEmpleadoNomina',
                'executing_social_security_ids.nValorPensionEmpleadoNomina',
                'executing_social_security_ids.nDiferenciaSalud',
                'executing_social_security_ids.nDiferenciaPension',
                'executing_social_security_ids.nValorSaludEmpresa',
                'executing_social_security_ids.nValorPensionEmpresa',
                'executing_social_security_ids.nValorARP',
                'executing_social_security_ids.nValorCajaCom',
                'executing_social_security_ids.nValorSENA',
                'executing_social_security_ids.nValorICBF')
    def _compute_amounts(self):
        for record in self:
            total_amount_employees = sum(
                record.executing_social_security_ids.mapped('nValorSaludEmpleado') +
                record.executing_social_security_ids.mapped('nValorPensionEmpleado') +
                record.executing_social_security_ids.mapped('nValorFondoSubsistencia') +
                record.executing_social_security_ids.mapped('nValorFondoSolidaridad')
            )
            total_amount_company = sum(
                record.executing_social_security_ids.mapped('nValorSaludEmpresa') +
                record.executing_social_security_ids.mapped('nValorPensionEmpresa') +
                record.executing_social_security_ids.mapped('nValorARP') +
                record.executing_social_security_ids.mapped('nValorCajaCom') +
                record.executing_social_security_ids.mapped('nValorSENA') +
                record.executing_social_security_ids.mapped('nValorICBF')
            )
            record.total_amount_employees = float("{:.2f}".format(total_amount_employees))
            record.total_amount_company = float("{:.2f}".format(total_amount_company))
            record.total_amount_final = float("{:.2f}".format(total_amount_employees + total_amount_company))

    @api.depends('executing_social_security_ids.nValorSaludTotal',
                'executing_social_security_ids.nValorPensionTotal',
                'executing_social_security_ids.nValorFondoSolidaridad',
                'executing_social_security_ids.nValorARP',
                'executing_social_security_ids.nValorCajaCom',
                'executing_social_security_ids.nValorSENA',
                'executing_social_security_ids.nValorICBF')
    def _compute_totals(self):
        for record in self:
            record.total_health = sum(record.executing_social_security_ids.mapped('nValorSaludTotal'))
            record.total_pension = sum(record.executing_social_security_ids.mapped('nValorPensionTotal'))
            record.total_solidarity = sum(record.executing_social_security_ids.mapped('nValorFondoSolidaridad')) + sum(record.executing_social_security_ids.mapped('nValorFondoSubsistencia')) #nValorFondoSubsistencia
            record.total_arl = sum(record.executing_social_security_ids.mapped('nValorARP'))
            record.total_parafiscal = sum(
                record.executing_social_security_ids.mapped('nValorCajaCom') +
                record.executing_social_security_ids.mapped('nValorSENA') +
                record.executing_social_security_ids.mapped('nValorICBF')
            )

    _sql_constraints = [('ssecurity_period_uniq', 'unique(company_id,year,month)', 'El periodo seleccionado ya esta registrado para esta compañía, por favor verificar.')]


    @api.depends('executing_social_security_ids')
    def _compute_total_employees(self):
        for record in self:
            record.total_employees = len(record.executing_social_security_ids.mapped('employee_id'))

    @api.depends('executing_social_security_ids.nValorBaseSalud')
    def _compute_total_base_ss(self):
        for record in self:
            record.total_base_ss = sum(record.executing_social_security_ids.mapped('nValorBaseSalud'))

    @api.depends('year', 'month')
    def _compute_date_end(self):
        """Calcula la fecha fin basada en el año y mes seleccionados"""
        for record in self:
            if record.year and record.month:
                date_initial = date(int(record.year), int(record.month), 1)
                date_final = date_initial + relativedelta(months=1) - relativedelta(days=1)
                record.date_end = date_final
            

    def name_get(self):
        result = []
        for record in self:
            result.append((record.id, "Periodo {}-{}".format(record.month,str(record.year))))
        return result
    def _get_worked_day_lines_hours_per_day(self, contract_id):
        self.ensure_one()
        return contract_id.resource_calendar_id.hours_per_day

    def _round_days(self, work_entry_type, days):
        if work_entry_type.round_days != 'NO':
            precision_rounding = 0.5 if work_entry_type.round_days == "HALF" else 1
            day_rounded = float_round(days, precision_rounding=precision_rounding, rounding_method=work_entry_type.round_days_type)
            return day_rounded
        return days
                        
    def get_accounting(self):
        line_ids = []
        debit_sum = 0.0
        credit_sum = 0.0
        # Obtener fechas del periodo seleccionado
        date_start = '01/' + str(self.month) + '/' + str(self.year)
        try:
            date_start = datetime.strptime(date_start, '%d/%m/%Y')

            date_end = date_start + relativedelta(months=1)
            date_end = date_end - timedelta(days=1)

            date_start = date_start.date()
            date_end = date_end.date()
        except:
            raise UserError(_('El año digitado es invalido, por favor verificar.'))

        date = date_end
        move_dict = {
            'narration': '',
            'ref': f"Seguridad Social - {date.strftime('%B %Y')}",
            'journal_id': False,
            'date': date,
        }

        ls_process_accounting = ['ss_empresa_salud','ss_empresa_pension','ss_empresa_arp','ss_empresa_caja','ss_empresa_sena','ss_empresa_icbf']
        obj_employee = self.env['hr.employee'].search([('id','!=',False)])

        for employee in obj_employee:
            executing_social_security = self.env['hr.executing.social.security'].search([('executing_social_security_id', '=', self.id),('employee_id','=',employee.id)])

            debit_third_id = employee.work_contact_id
            credit_third_id = employee.work_contact_id

            if len(executing_social_security) > 0:
                for executing in executing_social_security:
                    analytic_account_id = executing.analytic_account_id.id if executing.analytic_account_id.id else False
                for process in ls_process_accounting:
                    value_account = 0
                    value_account_difference = 0
                    description = ''
                    description_difference = ''
                    obj_closing = self.env['hr.closing.configuration.header'].search([('process', '=', process)])

                    for closing in obj_closing:
                        move_dict['journal_id'] = closing.journal_id.id
                        for account_rule in closing.detail_ids:
                            debit_account_id = False
                            credit_account_id = False
                            # Validar ubicación de trabajo
                            bool_work_location = False
                            if account_rule.work_location.id == employee.address_id.id or account_rule.work_location.id == False:
                                bool_work_location = True
                            # Validar compañia
                            bool_company = False
                            if account_rule.company.id == employee.company_id.id or account_rule.company.id == False:
                                bool_company = True
                            # Validar departamento
                            bool_department = False
                            if account_rule.department.id == employee.department_id.id or account_rule.department.id == employee.department_id.parent_id.id or account_rule.department.id == employee.department_id.parent_id.parent_id.id or account_rule.department.id == False:
                                bool_department = True

                            if bool_department and bool_company and bool_work_location:
                                debit_account_id = account_rule.debit_account
                                credit_account_id = account_rule.credit_account

                            # Tercero debito
                            if account_rule.third_debit == 'entidad':
                                for entity in employee.social_security_entities:
                                    if entity.contrib_id.type_entities == 'eps' and process == 'ss_empresa_salud':  # SALUD
                                        debit_third_id = entity.partner_id.partner_id
                                    if entity.contrib_id.type_entities == 'pension' and process == 'ss_empresa_pension':  # PENSION
                                        debit_third_id = entity.partner_id.partner_id
                                    if entity.contrib_id.type_entities == 'riesgo' and process == 'ss_empresa_arp': # ARP
                                        debit_third_id = entity.partner_id.partner_id
                                    if entity.contrib_id.type_entities == 'caja' and process == 'ss_empresa_caja': # CAJA DE COMPENSACIÓN
                                        debit_third_id = entity.partner_id.partner_id
                                if process == 'ss_empresa_sena':
                                    id_type_entities_sena = self.env['hr.contribution.register'].search([('type_entities', '=', 'sena')], limit=1).id
                                    debit_third_id = self.env['hr.employee.entities'].search([('types_entities', 'in', [id_type_entities_sena])], limit=1).partner_id  # SENA
                                if process == 'ss_empresa_icbf':
                                    id_type_entities_icbf = self.env['hr.contribution.register'].search([('type_entities', '=', 'icbf')], limit=1).id
                                    debit_third_id = self.env['hr.employee.entities'].search([('types_entities', 'in', [id_type_entities_icbf])], limit=1).partner_id  # ICBF
                            elif account_rule.third_debit == 'compañia':
                                debit_third_id = employee.company_id.partner_id
                            elif account_rule.third_debit == 'empleado':
                                debit_third_id = employee.work_contact_id

                            # Tercero credito
                            if account_rule.third_credit == 'entidad':
                                for entity in employee.social_security_entities:
                                    if entity.contrib_id.type_entities == 'eps' and process == 'ss_empresa_salud':  # SALUD
                                        credit_third_id = entity.partner_id.partner_id
                                    if entity.contrib_id.type_entities == 'pension' and process == 'ss_empresa_pension':  # PENSION
                                        credit_third_id = entity.partner_id.partner_id
                                    if entity.contrib_id.type_entities == 'riesgo' and process == 'ss_empresa_arp':  # ARP
                                        credit_third_id = entity.partner_id.partner_id
                                    if entity.contrib_id.type_entities == 'caja' and process == 'ss_empresa_caja':  # CAJA DE COMPENSACIÓN
                                        credit_third_id = entity.partner_id.partner_id
                                if process == 'ss_empresa_sena':
                                    id_type_entities_sena = self.env['hr.contribution.register'].search([('type_entities', '=', 'sena')], limit=1).id
                                    credit_third_id = self.env['hr.employee.entities'].search([('types_entities', 'in', [id_type_entities_sena])], limit=1).partner_id  # SENA
                                if process == 'ss_empresa_icbf':
                                    id_type_entities_icbf = self.env['hr.contribution.register'].search([('type_entities', '=', 'icbf')], limit=1).id
                                    credit_third_id = self.env['hr.employee.entities'].search([('types_entities', 'in', [id_type_entities_icbf])], limit=1).partner_id  # ICBF
                            elif account_rule.third_credit == 'compañia':
                                credit_third_id = employee.company_id.partner_id
                            elif account_rule.third_credit == 'empleado':
                                credit_third_id = employee.work_contact_id

                            if process == 'ss_empresa_salud':
                                if closing.debit_account_difference and closing.credit_account_difference:
                                    value_account_difference = sum([i.nDiferenciaSalud for i in executing_social_security])
                                    if value_account_difference > 1000 or value_account_difference < -1000:
                                        value_account = sum([i.nValorSaludEmpresa for i in executing_social_security])+value_account_difference
                                        value_account_difference = 0
                                    else:
                                        value_account = sum([i.nValorSaludEmpresa for i in executing_social_security])
                                        description_difference = f'Diferencia salud - {employee.identification_id} - {employee.name}'
                                    description = f'Aporte empresa salud - {employee.identification_id} - {employee.name}'
                                else:
                                    value_account = sum([i.nValorSaludEmpresa+i.nDiferenciaSalud for i in executing_social_security])
                                    description = f'Aporte empresa salud - {employee.identification_id} - {employee.name}'
                            elif process == 'ss_empresa_pension':
                                if closing.debit_account_difference and closing.credit_account_difference:
                                    value_account_difference = sum([i.nDiferenciaPension for i in executing_social_security])
                                    if value_account_difference > 1000 or value_account_difference < -1000:
                                        value_account = sum([i.nValorPensionEmpresa for i in executing_social_security])+value_account_difference
                                        value_account_difference = 0
                                    else:
                                        value_account = sum([i.nValorPensionEmpresa for i in executing_social_security])
                                        description_difference = f'Diferencia pensión - {employee.identification_id} - {employee.name}'
                                    description = f'Aporte empresa pensión - {employee.identification_id} - {employee.name}'
                                else:
                                    value_account = sum([i.nValorPensionEmpresa + i.nDiferenciaPension for i in executing_social_security])
                                    description = f'Aporte empresa pensión - {employee.identification_id} - {employee.name}'
                            elif process == 'ss_empresa_arp':
                                value_account = sum([i.nValorARP for i in executing_social_security])
                                description = f'Aporte ARP - {employee.identification_id} - {employee.name}'
                            elif process == 'ss_empresa_caja':
                                value_account = sum([i.nValorCajaCom for i in executing_social_security])
                                description = f'Aporte caja de compensación - {employee.identification_id} - {employee.name}'
                            elif process == 'ss_empresa_sena':
                                value_account = sum([i.nValorSENA for i in executing_social_security])
                                description = f'Aporte SENA - {employee.identification_id} - {employee.name}'
                            elif process == 'ss_empresa_icbf':
                                value_account = sum([i.nValorICBF for i in executing_social_security])
                                description = f'Aporte ICBF - {employee.identification_id} - {employee.name}'

                            if debit_third_id == False and credit_third_id == False:
                                raise ValidationError(_(f'Falta configurar la entidad para el proceso {description}.'))

                            #Descripción final
                            addref_work_address_account_moves = self.env['ir.config_parameter'].sudo().get_param(
                                'lavish_hr_payroll.addref_work_address_account_moves') or False
                            if addref_work_address_account_moves and employee.address_id:
                                if employee.address_id.parent_id:
                                    description = f"{employee.address_id.parent_id.vat} {employee.address_id.display_name}|{description}"
                                    if description_difference != '':
                                        description_difference = f"{employee.address_id.parent_id.vat} {employee.address_id.display_name}|{description_difference}"
                                else:
                                    description = f"{employee.address_id.vat} {employee.address_id.display_name}|{description}"
                                    if description_difference != '':
                                        description_difference = f"{employee.address_id.vat} {employee.address_id.display_name}|{description_difference}"

                            #Crear item contable
                            amount = value_account
                            amount_difference = value_account_difference
                            if debit_account_id and amount != 0:
                                debit = abs(amount) if amount > 0.0 else 0.0
                                credit = abs(amount) if amount < 0.0 else 0.0
                                debit_line = {
                                    'name': description,
                                    'partner_id': debit_third_id.id,# if debit > 0 else credit_third_id.id,
                                    'account_id': debit_account_id.id,# if debit > 0 else credit_account_id.id,
                                    'journal_id': closing.journal_id.id,
                                    'date': date,
                                    'debit': debit,
                                    'credit': credit,
                                    'analytic_distribution': (analytic_account_id and {analytic_account_id: 100})
                                }
                                line_ids.append(debit_line)

                            if credit_account_id and amount != 0:
                                debit = abs(amount) if amount < 0.0 else 0.0
                                credit = abs(amount) if amount > 0.0 else 0.0

                                credit_line = {
                                    'name': description,
                                    'partner_id': credit_third_id.id,
                                    'account_id': credit_account_id.id,
                                    'journal_id': closing.journal_id.id,
                                    'date': date,
                                    'debit': debit,
                                    'credit': credit,
                                    'analytic_distribution': (analytic_account_id and {analytic_account_id: 100})
                                }
                                line_ids.append(credit_line)

                            if debit_account_id and closing.debit_account_difference and closing.credit_account_difference and amount_difference != 0:
                                debit = abs(amount_difference) if amount_difference > 0.0 else 0.0
                                credit = abs(amount_difference) if amount_difference < 0.0 else 0.0
                                debit_line = {
                                    'name': description_difference,
                                    'partner_id': debit_third_id.id,# if debit > 0 else credit_third_id.id,
                                    'account_id': closing.debit_account_difference.id if amount_difference > 0 else closing.credit_account_difference.id,# if debit > 0 else credit_account_id.id,
                                    'journal_id': closing.journal_id.id,
                                    'date': date,
                                    'debit': debit,
                                    'credit': credit,
                                    'analytic_distribution': (analytic_account_id and {analytic_account_id: 100})
                                }
                                line_ids.append(debit_line)

                            if credit_account_id and amount_difference != 0:
                                debit = abs(amount_difference) if amount_difference < 0.0 else 0.0
                                credit = abs(amount_difference) if amount_difference > 0.0 else 0.0

                                credit_line = {
                                    'name': description_difference,
                                    'partner_id': credit_third_id.id,
                                    'account_id': credit_account_id.id,
                                    'journal_id': closing.journal_id.id,
                                    'date': date,
                                    'debit': debit,
                                    'credit': credit,
                                    'analytic_distribution': (analytic_account_id and {analytic_account_id: 100})
                                }
                                line_ids.append(credit_line)

        move_dict['line_ids'] = [(0, 0, line_vals) for line_vals in line_ids]
        move = self.env['account.move'].create(move_dict)
        self.write({'move_id': move.id, 'state': 'accounting'})

    def cancel_process(self):
        #Eliminar ejecución
        self.env['hr.errors.social.security'].search([('executing_social_security_id','=',self.id)]).unlink()
        self.env['hr.executing.social.security'].search([('executing_social_security_id','=',self.id)]).unlink()
        return self.write({'state':'draft','time_process':''})

    def restart_accounting(self):
        if self.move_id:
            if self.move_id.state != 'draft':
                raise ValidationError(_('No se puede reversar el movimiento contable debido a que su estado es diferente de borrador.'))
            self.move_id.unlink()
        return self.write({'state': 'done'})

    def unlink(self):
        for record in self:
            if record.state != 'draft':
                raise ValidationError(_('No se puede eliminar la provisión debido a que su estado es diferente de borrador.'))
        return super(hr_payroll_social_security, self).unlink()

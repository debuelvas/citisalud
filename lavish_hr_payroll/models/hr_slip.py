# -*- coding: utf-8 -*-
from odoo import models, fields, api, _, SUPERUSER_ID , tools
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_is_zero, float_round, date_utils
from collections import defaultdict
from typing import Dict, List, Tuple, Any, Optional, Union, TypedDict
from datetime import datetime, timedelta, date, time
from odoo.tools.misc import format_date
import calendar
from collections import defaultdict, Counter
from dateutil.relativedelta import relativedelta
import ast
import re
from odoo import api, Command, fields, models, _
from .browsable_object import BrowsableObject, InputLine, WorkedDays, Payslips, ResultRules
from .browsable_object import ResultRules_co
from odoo.exceptions import UserError, ValidationError
from odoo.osv.expression import AND
from odoo.tools import float_round, date_utils, convert_file, html2plaintext, is_html_empty, format_amount
from odoo.tools.float_utils import float_compare
from odoo.tools.misc import format_date
from odoo.tools.safe_eval import safe_eval
from pprint import pformat
import logging
import json
import io
import base64
from decimal import Decimal,ROUND_HALF_UP
import math
import pytz
from psycopg2 import sql
from psycopg2.extras import Json # USAR PARA CONVERTIR A JSON EN POSTGRESQL -> https://www.psycopg.org/docs/extras.html#psycopg2.extras.Json -> {str(obj): Json(obj) for obj in list_of_dicts}
_logger = logging.getLogger(__name__)


DAYS_YEAR = 360
DAYS_YEAR_NATURAL = 365
DAYS_MONTH = 30
PRECISION_TECHNICAL = 10
PRECISION_DISPLAY = 0
DATETIME_MIN = datetime.min.time()
DATETIME_MAX = datetime.max.time()
TPCT = 'total_previous_categories'
TPCP = 'total_previous_concepts'
NCI = 'non_constitutive_income'
UTC = pytz.UTC
HOURS_PER_DAY = 8 #Solo pór si no ponen las horas en parametros anuales, para nominas simple no suma ni resta 

TYPE_PERIOD = [
    ('monthly', 'Mensual'),
    ('bi-monthly', 'Quincenal'),
    ('weekly', 'Semanal'),
    ('dualmonth', 'Cada 2 Meses'),
    ('quarterly', 'Cada Cuatro meses'),
    ('semi-annually', 'Cada 6 Meses'),
    ('annually', 'Anual'),
]

TYPE_BIWEEKLY = [
    ('first', 'Primera Quincena'),
    ('second', 'Segunda Quincena')
]
@staticmethod
def round_1_decimal(value):
    """Redondea a 1 decimal."""
    return float(Decimal(str(value)).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP))
def json_serial(obj):
    """
    Función auxiliar extendida para serializar objetos de Odoo y tipos básicos.
    Maneja fechas, decimales, objetos de Odoo y objetos genéricos con __dict__.
    """
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    elif isinstance(obj, Decimal):
        return float(obj)
    elif hasattr(obj, '_name'):  
        return {
            'id': getattr(obj, 'id', None),
            'name': getattr(obj, 'name', ''),
            'model': getattr(obj, '_name', '')
        }
    elif hasattr(obj, 'name') and callable(getattr(obj, 'name_get', None)):
        return dict(obj.name_get()[0]) if obj.name_get() else str(obj)
    elif hasattr(obj, '__dict__'):
        return {k: v for k, v in obj.__dict__.items() 
                if not k.startswith('_') and not callable(v)}
    raise TypeError(f"Type {type(obj)} not serializable")

class HrPayslip(models.Model):
    _name = 'hr.payslip'
    _inherit = ['hr.payslip', 'sequence.mixin']
    _sequence_index = 'sequence_prefix'
    _sequence_field = 'number'
    _sequence_fixed_regex = r'^(?P<prefix1>.*?)(?P<seq>\d*)(?P<suffix>\D*?)$'
    
    def convert_tuples_to_dict(self,tuple_list):
        data_list = ast.literal_eval(tuple_list)
        return data_list

    def days_between(self,start_date:date, end_date:date) -> int:
        s1, e1 =  start_date , end_date + timedelta(days=1)
        s360 = (s1.year * 12 + s1.month) * 30 + s1.day
        e360 = (e1.year * 12 + e1.month) * 30 + e1.day
        res = divmod(e360 - s360, 30)
        return ((res[0] * 30) + res[1]) or 0   
    
    @api.depends('struct_id', 'struct_id.process', 'credit_note')
    def _compute_sequence_prefix(self) -> None:
        """Compute sequence prefix based on payslip type"""
        for slip in self:
            if slip.struct_id and slip.struct_id.process:
                prefix_map = {
                    'nomina': 'NOM' if not slip.credit_note else 'RNOM',
                    'vacaciones': 'VAC' if not slip.credit_note else 'RVAC',
                    'prima': 'PRI' if not slip.credit_note else 'RPRI',
                    'cesantias': 'CES' if not slip.credit_note else 'RCES',
                    'contrato': 'LIQ' if not slip.credit_note else 'RLIQ',
                    'intereses_cesantias': 'INT' if not slip.credit_note else 'RINT',
                    'otro': 'OTR' if not slip.credit_note else 'ROTR'
                }
                slip.sequence_prefix = f"{prefix_map.get(slip.struct_id.process, 'OTR')}-"
            else:
                slip.sequence_prefix = 'OTR-'

    @api.depends('struct_id', 'struct_id.process', 'credit_note')
    def _compute_move_type(self) -> None:
        """Compute move_type based on structure process and reversal status"""
        for slip in self:
            if slip.struct_id:
                process = slip.struct_id.process
                if process == 'nomina':
                    slip.move_type = 'r_payroll' if slip.credit_note else 'payroll'
                elif process == 'vacaciones':
                    slip.move_type = 'r_vacaciones' if slip.credit_note else 'vacaciones'
                elif process == 'prima':
                    slip.move_type = 'r_prima' if slip.credit_note else 'prima'
                elif process == 'cesantias':
                    slip.move_type = 'r_cesantias' if slip.credit_note else 'cesantias'
                elif process == 'contrato':
                    slip.move_type = 'r_liquidacion' if slip.credit_note else 'liquidacion'
                else:
                    slip.move_type = 'r_otros' if slip.credit_note else 'otros'
            else:
                slip.move_type = 'r_payroll' if slip.credit_note else 'payroll'
    period_id = fields.Many2one('hr.period', string='Periodo de Nómina',
                               domain="[('closed', '=', False)]")
    move_type = fields.Selection([
        ('payroll', 'Nomina'),
        ('prima', 'Prima'),
        ('cesantias', 'Cesantias'),
        ('vacaciones', 'Vacaciones'),
        ('liquidacion', 'Liquidacion Final'),
        ('otros', 'Otros'),
        ('r_payroll', 'Reversion de Nomina'),
        ('r_prima', 'Reversion Prima'),
        ('r_cesantias', 'Reversion Cesantias'),
        ('r_vacaciones', 'Reversion Vacaciones'),
        ('r_liquidacion', 'Reversion Liquidacion'),
        ('r_otros', 'Reversion Otros')
    ], string='Tipo de documento', compute='_compute_move_type', store=True)
    number = fields.Char(string='Reference', required=True, copy=False, readonly=True, default='/')
    reversed_slip_id = fields.Many2one('hr.payslip', string='Reversed Payslip', readonly=True, copy=False)
    sequence_prefix = fields.Char(compute='_compute_sequence_prefix', store=True)
    sequence_number = fields.Integer(compute='_compute_split_sequence', store=True)
    leave_ids = fields.One2many('hr.absence.days', 'payroll_id', string='Novedades', readonly=True)
    
    ret_line_ids =fields.One2many('lavish.retencion.reporte', 'payslip_id', string='Detalle de retencion', readonly=True)
    
    leave_days_ids =fields.One2many('hr.leave.line', 'payslip_id', string='Detalle de Ausencia', readonly=True)
    
    histori_vacation_ids =fields.One2many('hr.vacation', 'payslip', string='Detalle de Vacaciones', readonly=True) 
    
    
    payslip_day_ids = fields.One2many(comodel_name='hr.payslip.day', inverse_name='payslip_id', string='Días de Nómina', readonly=True)
    rtefte_id = fields.Many2one('hr.employee.rtefte', 'RteFte', readonly=True)
    not_line_ids = fields.One2many('hr.payslip.not.line', 'slip_id', string='Reglas no aplicadas', readonly=True)
    observation = fields.Text(string='Observación')
    analytic_account_id = fields.Many2one('account.analytic.account', string='Cuenta analítica')
    struct_process = fields.Selection(related='struct_id.process', string='Proceso', store=True)
    employee_branch_id = fields.Many2one(related='employee_id.branch_id', string='Sucursal empleado', store=True)
    definitive_plan = fields.Boolean(string='Plano definitivo generado')
    #Fechas liquidación de contrato
    date_liquidacion = fields.Date('Fecha liquidación de contrato')
    date_prima = fields.Date('Fecha liquidación de prima')
    date_cesantias = fields.Date('Fecha liquidación de cesantías')
    date_vacaciones = fields.Date('Fecha liquidación de vacaciones')
    worked_days_line_ids = fields.One2many('hr.payslip.worked_days', 'payslip_id', compute=False, )
    pay_cesantias_in_payroll = fields.Boolean('¿Liquidar Interese de cesantia periodo anterior en nómina ?')
    pay_primas_in_payroll = fields.Boolean('¿Liquidar Primas en nómina?')
    pay_vacations_in_payroll = fields.Boolean('¿Liquidar vacaciones en nómina?')
    provisiones = fields.Boolean('Provisiones')
    journal_struct_id = fields.Many2one('account.journal', string='Salary Journal', domain="[('company_id', '=', company_id)]")
    earnings_ids = fields.One2many(comodel_name='hr.payslip.line', compute="_compute_concepts_category", string='Conceptos de Nómina / Devengos')
    deductions_ids = fields.One2many(comodel_name='hr.payslip.line', compute="_compute_concepts_category", string='Conceptos de Nómina / Deducciones')
    bases_ids = fields.One2many(comodel_name='hr.payslip.line', compute="_compute_concepts_category", string='Conceptos de Nómina / Bases')
    provisions_ids = fields.One2many(comodel_name='hr.payslip.line', compute="_compute_concepts_category", string='Conceptos de Nómina / Provisiones')
    outcome_ids = fields.One2many(comodel_name='hr.payslip.line', compute="_compute_concepts_category", string='Conceptos de Nómina / Totales')
    date_from = fields.Date(
        string='From', readonly=False, required=True, tracking=True,
        compute=False, store=True, precompute=False)
    date_to = fields.Date(
        string='To', readonly=False, required=True, tracking=True,
        compute=False, store=True, precompute=False)
    periodo = fields.Char('Periodo', compute="_periodo", store=True)
    extrahours_ids = fields.One2many('hr.overtime', 'payslip_run_id',  string='Horas Extra Detallada', )
    novedades_ids = fields.One2many('hr.novelties.different.concepts', 'payslip_id',  string='Novedades Detalladas')
    payslip_old_ids = fields.Many2many('hr.payslip', 'hr_payslip_rel', 'current_payslip_id', 'old_payslip_id', string='Nominas relacionadas')
    resulados_op = fields.Html('Resultados')
    resulados_rt = fields.Html('Resultados RT')
    payslip_detail = fields.Html(compute='_compute_payslip_detail')
    prestaciones_sociales_report = fields.Html(string="Reporte de Prestaciones Sociales", compute='_compute_prestaciones_sociales_report')
    reason_retiro = fields.Many2one('hr.departure.reason', string='Motivo de retiro')
    have_compensation = fields.Boolean('Indemnización', default=False)
    settle_payroll_concepts = fields.Boolean('Liquida conceptos de nómina', default=True)
    novelties_payroll_concepts = fields.Boolean('Liquida conceptos de novedades', default=True)
    pagar_cesantias_ano_anterior = fields.Boolean('Liquida conceptos de Cesantia periodo anterior', default=True)
    no_days_worked = fields.Boolean('Sin días laborados', default=False, help='Aplica unicamente cuando la fecha de inicio es igual a la fecha de finalización.')
    paid_vacation_ids = fields.One2many('hr.payslip.paid.vacation', 'slip_id',string='Vacaciones remuneradas')
    refund_date = fields.Date(string='Fecha reintegro')
    is_advance_severance = fields.Boolean(string='Es avance de cesantías')
    value_advance_severance = fields.Float(string='Valor a pagar avance')
    employee_severance_pay = fields.Boolean(string='Pago cesantías al empleado')
    severance_payments_reverse = fields.Many2many('hr.history.cesantias',
                                                  string='Historico de cesantias/int.cesantias a tener encuenta',
                                                  domain="[('employee_id', '=', employee_id)]")
    prima_run_reverse_id = fields.Many2one('hr.payslip.run', string='Lote de prima a ajustar')
    prima_payslip_reverse_id = fields.Many2one('hr.payslip', string='Prima a ajustar', domain="[('employee_id', '=', employee_id)]")
    rule_override_ids = fields.One2many('hr.payslip.rule.override', 'payslip_id', 'Ajustes de Reglas')
    has_overrides = fields.Boolean('Tiene Ajustes', compute='_compute_has_overrides')
    enable_rule_overrides = fields.Boolean(
        'Habilitar ajustes manuales', 
        help='Permite modificar manualmente los valores de las reglas salariales',
        tracking=True
    )
    
    @api.depends('rule_override_ids.active')
    def _compute_has_overrides(self):
        for record in self:
            record.has_overrides = bool(record.rule_override_ids.filtered('active'))

    @api.onchange('enable_rule_overrides')
    def _onchange_enable_rule_overrides(self) -> Union[dict[str, dict[str, str]], None]:
        if self.enable_rule_overrides:
            message = _("""ADVERTENCIA: Ha activado el modo de ajustes manuales.
            
            Tenga en cuenta que:
            - Los ajustes manuales pueden crear diferencias con los cálculos automáticos
            - Estas modificaciones quedarán registradas en el historial
            - Se recomienda documentar el motivo de cada ajuste
            - Los totales de nómina pueden variar significativamente
            - Las novedades se debe ajustar directamente, desde su modulo
            Asegúrese de validar todos los cálculos antes de confirmar la nómina.""")
            
            return {
                'warning': {
                    'title': _("Modo de Ajustes Manuales"),
                    'message': message
                }
            }

    def init(self):
        if not self._abstract and self._sequence_index:
            index_name = self._table + '_sequence_index'
            self.env.cr.execute('SELECT indexname FROM pg_indexes WHERE indexname = %s', (index_name,))
            if not self.env.cr.fetchone():
                self.env.cr.execute(sql.SQL("""
                    CREATE INDEX {index_name} ON {table} ({sequence_index}, sequence_prefix desc, sequence_number desc, {field});
                    CREATE INDEX {index2_name} ON {table} ({sequence_index}, id desc, sequence_prefix);
                """).format(
                    sequence_index=sql.Identifier(self._sequence_index),
                    index_name=sql.Identifier(index_name),
                    index2_name=sql.Identifier(index_name + "2"),
                    table=sql.Identifier(self._table),
                    field=sql.Identifier(self._sequence_field),
                ))

    def _get_last_sequence_domain(self, relaxed=False) -> Tuple[str, Dict[str, Any]]:
        self.ensure_one()
        where_string = "WHERE sequence_prefix = %(sequence_prefix)s"
        param = {'sequence_prefix': self.sequence_prefix}
        return where_string, param

    def _get_starting_sequence(self):
        """ Returns the initial sequence for the given document type """
        self.ensure_one()
        return f"{self.sequence_prefix}00001"

    def _compute_split_sequence(self):
        """Compute the sequence number"""
        for record in self:
            sequence = record[record._sequence_field] or ''
            regex = re.sub(r"\?P<\w+>", "?:", record._sequence_fixed_regex.replace(r"?P<seq>", ""))
            matching = re.match(regex, sequence)
            if matching:
                record.sequence_number = int(matching.group(1) or 0)
            else:
                record.sequence_number = 0
                
    @api.depends('sequence_prefix', 'sequence_number')
    def _compute_name(self) -> None:
        """Compute the full name based on prefix and sequence number"""
        for record in self:
            if record.sequence_number:
                record.number = f'{record.sequence_prefix}{record.sequence_number:05d}'

    def _sequence_matches_date(self) -> bool:
        """Override to always return True since we don't use date in sequence"""
        return True
    
    def _set_next_sequence(self) -> None:
        """Set the next sequence.
        This method ensures that the sequence is set both in the ORM and in the database.
        """
        self.ensure_one()

        # Obtener la última secuencia
        last_sequence = self._get_last_sequence()
        new = not last_sequence
        if new:
            last_sequence = self._get_starting_sequence()

        format_string = "{prefix1}{seq:05d}"
        sequence_number = 1

        if not new:
            match = re.match(self._sequence_fixed_regex, last_sequence)
            if match:
                sequence_number = int(match.group('seq') or 0) + 1

        self[self._sequence_field] = format_string.format(
            prefix1=self.sequence_prefix, 
            seq=sequence_number
        )
        self._compute_split_sequence()

    def _get_sequence_format_param(self, previous) -> Tuple[str, Dict[str, Any]]:
        """Get format parameters for the sequence"""
        if not previous or not re.match(self._sequence_fixed_regex, previous):
            return "{prefix1}{seq:05d}{suffix}", {
                'prefix1': self.sequence_prefix,
                'seq': 0,
                'seq_length': 5,
                'suffix': ''
            }

        format_values = re.match(self._sequence_fixed_regex, previous).groupdict()
        format_values['seq_length'] = 5
        format_values['seq'] = int(format_values.get('seq') or 0)
            
        if not format_values.get('prefix1'):
            format_values['prefix1'] = self.sequence_prefix
        if not format_values.get('suffix'):
            format_values['suffix'] = ''
                
        return "{prefix1}{seq:0{seq_length}d}{suffix}", format_values

    @api.onchange('struct_id', 'credit_note')
    def onchange_struct_id(self) -> None:
        """Update move_type when structure or reversal status changes"""
        self._compute_move_type()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('number', '/') == '/':
                vals['number'] = '/'
        return super().create(vals_list)

    def write(self, vals):
        """Handle sequence updates on write"""
        if 'struct_id' in vals or 'credit_note' in vals:
            self._compute_move_type()
        if vals.get(self._sequence_field):
            self._compute_split_sequence()
        return super().write(vals)

    @api.onchange('employee_id', 'contract_id', 'struct_id', 'date_to')
    def load_dates_liq_contrato(self) -> None:
        """
        Carga las fechas para liquidación de contrato con manejo de excepciones.
        En caso de error, asigna la fecha de inicio del contrato como valor predeterminado.
        """
        if not self.struct_id or self.struct_id.process != 'contrato':
            return
            
        try:
            self.date_liquidacion = self.date_to
            contract_start_date = self.contract_id.date_start if self.contract_id else False
            try:
                date_prima = contract_start_date
                if self.employee_id and self.contract_id:
                    obj_prima = self.env['hr.history.prima'].search([
                        ('employee_id', '=', self.employee_id.id),
                        ('contract_id', '=', self.contract_id.id)
                    ])
                    
                    if obj_prima:
                        for history in sorted(obj_prima, key=lambda x: x.final_accrual_date):
                            if history.final_accrual_date and history.final_accrual_date > date_prima:
                                date_prima = history.final_accrual_date + timedelta(days=1)
                
                self.date_prima = date_prima
            except Exception as e:
                self.date_prima = contract_start_date
            try:
                date_vacation = contract_start_date
                if self.employee_id and self.contract_id:
                    obj_vacation = self.env['hr.vacation'].search([
                        ('employee_id', '=', self.employee_id.id),
                        ('contract_id', '=', self.contract_id.id)
                    ])
                    
                    if obj_vacation:
                        for history in sorted(obj_vacation, key=lambda x: x.final_accrual_date):
                            if not history.final_accrual_date:
                                continue
                                
                            update_date = False
                            if history.leave_id:
                                if not history.leave_id.holiday_status_id.unpaid_absences:
                                    update_date = True
                            else:
                                update_date = True
                                
                            if update_date and history.final_accrual_date > date_vacation:
                                date_vacation = history.final_accrual_date + timedelta(days=1)
                self.date_vacaciones = date_vacation
            except Exception as e:
                self.date_vacaciones = contract_start_date
            try:
                date_cesantias = contract_start_date
                if self.employee_id and self.contract_id:
                    obj_cesantias = self.env['hr.history.cesantias'].search([
                        ('employee_id', '=', self.employee_id.id),
                        ('contract_id', '=', self.contract_id.id)
                    ])
                    
                    if obj_cesantias:
                        for history in sorted(obj_cesantias, key=lambda x: x.final_accrual_date):
                            if history.final_accrual_date and history.final_accrual_date > date_cesantias:
                                date_cesantias = history.final_accrual_date + timedelta(days=1)
                
                self.date_cesantias = date_cesantias
            except Exception as e:
                self.date_cesantias = contract_start_date
                
        except Exception as e:
            contract_start_date = self.contract_id.date_start if self.contract_id else False
            self.date_liquidacion = self.date_to
            self.date_prima = contract_start_date
            self.date_vacaciones = contract_start_date
            self.date_cesantias = contract_start_date

    @api.depends('line_ids.computation')
    def _compute_prestaciones_sociales_report(self) -> None:
        for payslip in self:
            prestaciones_lines = payslip.line_ids.filtered(lambda line: line.computation and line.salary_rule_id.code not in ('IBD','IBC_R','RT_MET_01'))
            if prestaciones_lines:
                all_reports = []
                for line in prestaciones_lines:
                    try:
                        computation_data = json.loads(line.computation)
                        report = self._generate_formatted_prestaciones_report(line, computation_data)
                        all_reports.append(report)
                    except json.JSONDecodeError:
                        all_reports.append(f'<p>Error al procesar los datos de la línea {line.name}.</p>')
                
                payslip.prestaciones_sociales_report = self._combine_reports(all_reports)
            else:
                payslip.prestaciones_sociales_report = '<p>No hay datos de prestaciones sociales disponibles.</p>'

    def _format_reporte_html(self, data) -> str:
        """
        Genera un reporte HTML detallado de la retención en la fuente
        Args:
            data: Diccionario con los datos del reporte
        Returns:
            str: Reporte HTML formateado
        """
        def format_currency(value):
            try:
                if isinstance(value, str):
                    value = float(value.replace(',', '').strip('$'))
                return f"${value:,.0f}" if value else "$0"
            except:
                return "$0"
                
        def format_number(value, decimals=2):
            try:
                return f"{float(value):,.{decimals}f}" if value else "0"
            except:
                return "0"
                
        def format_percent(value):
            try:
                return f"{float(value):,.2f}%" if value is not None else "0%"
            except:
                return "0%"

        def format_section(title, content, base_legal=None):
            legal_text = f'<div class="legal-ref" style="font-size: 0.85em; color: #666; text-align: right;">Base legal: {base_legal}</div>' if base_legal else ''
            return f"""
                <div class="section-container" style="margin-bottom: 20px;">
                    <div class="section-title" style="background-color: #1E6C93; color: white; padding: 8px; font-weight: bold; border-radius: 4px 4px 0 0; display: flex; justify-content: space-between;">
                        <div>{title}</div>
                        {legal_text}
                    </div>
                    <div class="section-content" style="border: 1px solid #ddd; border-top: none; padding: 15px; border-radius: 0 0 4px 4px; background-color: #f9f9f9;">
                        {content}
                    </div>
                </div>
            """

        def format_row(label, value, base_legal=None, observation=None, is_total=False):
            legal_ref = f'<span style="font-size: 0.8em; color: #1E6C93; margin-left: 5px;">({base_legal})</span>' if base_legal else ''
            obs_text = f'<div style="color: #666; font-size: 0.9em; font-style: italic; margin-top: 3px;">{observation}</div>' if observation else ''
            
            bg_color = "#e6f3f8" if is_total else "transparent"
            font_weight = "bold" if is_total else "normal"
            
            return f"""
                <div style="display: flex; justify-content: space-between; padding: 8px 5px; border-bottom: 1px solid #eee; background-color: {bg_color};">
                    <div style="flex: 3; font-weight: {font_weight};">
                        {label} {legal_ref}
                        {obs_text}
                    </div>
                    <div style="flex: 1; text-align: right; font-weight: {font_weight}; margin-left: 10px;">
                        {value}
                    </div>
                </div>
            """
            
        def format_info_box(title, content, color="info"):
            color_map = {
                "info": {"bg": "#d1ecf1", "border": "#bee5eb", "text": "#0c5460"},
                "warning": {"bg": "#fff3cd", "border": "#ffeeba", "text": "#856404"},
                "legal": {"bg": "#e2e3e5", "border": "#d6d8db", "text": "#383d41"},
                "success": {"bg": "#d4edda", "border": "#c3e6cb", "text": "#155724"}
            }
            colors = color_map.get(color, color_map["info"])
            
            return f"""
                <div style="background-color: {colors['bg']}; border: 1px solid {colors['border']}; color: {colors['text']}; 
                            padding: 12px; margin: 15px 0; border-radius: 4px; font-size: 0.95em;">
                    <div style="font-weight: bold; margin-bottom: 5px;">{title}</div>
                    <div>{content}</div>
                </div>
            """
            
        def format_subsection(title, content):
            return f"""
                <div style="margin-top: 10px; margin-bottom: 10px;">
                    <div style="font-weight: bold; color: #1E6C93; border-bottom: 1px solid #1E6C93; padding-bottom: 3px; margin-bottom: 8px;">
                        {title}
                    </div>
                    <div style="margin-left: 10px;">
                        {content}
                    </div>
                </div>
            """
            
        def format_detail_table(desglose):
            if not desglose:
                return ""
                
            rows = ""
            for key, value in desglose.items():
                if key not in ['base_legal', 'pasos', 'employee', 'employee_name', 'employee_document']:
                    label = key.replace('_', ' ').title()
                    
                    # Format value based on its type
                    if isinstance(value, bool):
                        formatted_value = "Sí" if value else "No"
                    elif isinstance(value, (int, float)):
                        if 'porcentaje' in key.lower() or 'rate' in key.lower():
                            formatted_value = format_percent(value)
                        elif 'uvt' in key.lower() and 'pesos' not in key.lower():
                            formatted_value = format_number(value)
                        else:
                            formatted_value = format_currency(value)
                    else:
                        formatted_value = str(value)
                    
                    rows += f"""
                        <tr>
                            <td style="padding: 5px; border-bottom: 1px solid #eee;">{label}</td>
                            <td style="padding: 5px; border-bottom: 1px solid #eee; text-align: right;">{formatted_value}</td>
                        </tr>
                    """
                    
            if rows:
                return f"""
                    <table style="width: 100%; border-collapse: collapse; font-size: 0.9em;">
                        <tbody>
                            {rows}
                        </tbody>
                    </table>
                """
            return ""
        
        def format_steps_table(pasos):
            if not pasos:
                return ""
                
            steps_html = ""
            for paso in pasos:
                if 'desglose' in paso:
                    # Es un paso con desglose de valores
                    desglose_rows = ""
                    for item in paso['desglose']:
                        valor = format_currency(item['valor']) if 'valor' in item else ''
                        desglose_rows += f"""
                            <tr>
                                <td style="padding: 5px 5px 5px 20px; border-bottom: 1px solid #eee;">{item.get('concepto', '')}</td>
                                <td style="padding: 5px; border-bottom: 1px solid #eee; text-align: right;">{valor}</td>
                            </tr>
                        """
                    
                    steps_html += f"""
                        <tr>
                            <td colspan="2" style="padding: 8px 5px; border-bottom: 1px solid #ddd; background-color: #f5f5f5; font-weight: bold;">
                                {paso.get('descripcion', '')}
                            </td>
                        </tr>
                        {desglose_rows}
                    """
                else:
                    # Es un paso simple
                    valor = format_currency(paso.get('valor', '')) if 'valor' in paso else ''
                    resultado = paso.get('resultado', '')
                    
                    # Mostrar valor o resultado según lo que esté disponible
                    valor_final = valor if valor else resultado
                    
                    steps_html += f"""
                        <tr>
                            <td style="padding: 8px 5px; border-bottom: 1px solid #eee;">{paso.get('descripcion', '')}</td>
                            <td style="padding: 8px 5px; border-bottom: 1px solid #eee; text-align: right;">{valor_final}</td>
                        </tr>
                    """
            
            if steps_html:
                return f"""
                    <table style="width: 100%; border-collapse: collapse; font-size: 0.9em;">
                        <tbody>
                            {steps_html}
                        </tbody>
                    </table>
                """
            return ""

        try:
            if not data:
                return "<div>No hay datos disponibles para mostrar</div>"
                
            # Determine the type of report
            report_type = data.get('tipo', 'calculo_normal')
            
            if report_type == 'monto_fijo':
                # Simple fixed amount withholding report
                html = f"""
                <div style="font-family: Arial, sans-serif; font-size: 14px; line-height: 1.5; max-width: 800px; margin: 0 auto;">
                    <div style="background-color: #1E6C93; color: white; padding: 15px; border-radius: 5px; margin-bottom: 20px;">
                        <div style="font-size: 18px; font-weight: bold;">RETENCIÓN EN LA FUENTE - MONTO FIJO</div>
                        <div style="font-size: 14px;">Empleado: {data.get('employee_name', 'N/A')} - Documento: {data.get('employee_document', 'N/A')}</div>
                        <div style="font-size: 14px;">Año fiscal: {data.get('year', '')}</div>
                    </div>
                    
                    {format_info_box("Información", "Este empleado tiene configurado un monto fijo de retención en la fuente.")}
                    
                    {format_section("RETENCIÓN APLICADA", format_row("Valor de retención mensual", format_currency(data.get('valor', 0)), is_total=True, base_legal='Art. 385-389 ET'))}
                </div>
                """
                return html
            
            # Handle specific case for indemnity withholding
            if report_type == 'indemnizacion':
                indem_data = data.get('indemnizacion', {})
                limite_uvt = data.get('limite_uvt', {})
                
                html = f"""
                <div style="font-family: Arial, sans-serif; font-size: 14px; line-height: 1.5; max-width: 800px; margin: 0 auto;">
                    <div style="background-color: #1E6C93; color: white; padding: 15px; border-radius: 5px; margin-bottom: 20px;">
                        <div style="font-size: 18px; font-weight: bold;">RETENCIÓN EN LA FUENTE - INDEMNIZACIÓN LABORAL</div>
                        <div style="font-size: 14px;">Empleado: {data.get('employee_name', 'N/A')} - Documento: {data.get('employee_document', 'N/A')}</div>
                        <div style="font-size: 14px;">Año fiscal: {data.get('year', '')}</div>
                    </div>
                    
                    {format_info_box("Información", "Cálculo de retención para indemnización laboral según Art. 401-3 del Estatuto Tributario.", "info")}
                    
                    {format_section("1. VERIFICACIÓN DE UMBRAL",
                        format_row("Ingresos mensuales totales", format_currency(data.get('ingresos', {}).get('total', 0))) +
                        format_row("Límite 204 UVT", format_currency(limite_uvt.get('valor', 0)), base_legal="Art. 401-3 ET") +
                        format_row("¿Excede el límite?", "Sí" if limite_uvt.get('excede', False) else "No", is_total=True)
                    )}
                    
                    {format_section("2. LIQUIDACIÓN RETENCIÓN",
                        format_row("Valor indemnización", format_currency(indem_data.get('valor', 0))) +
                        format_row("Renta exenta (25%)", format_currency(indem_data.get('exenta', 0)), base_legal="Art. 401-3 ET") +
                        format_row("Base gravable", format_currency(indem_data.get('gravada', 0))) +
                        format_row("Tarifa aplicable", "20%", base_legal="Art. 401-3 ET") +
                        format_row("Retención calculada", format_currency(indem_data.get('gravada', 0) * 0.20), is_total=True)
                    )}
                </div>
                """
                
                # Add steps if available
                pasos = data.get('pasos', [])
                if pasos:
                    html += f"""
                    <details style="margin-top: 20px; margin-bottom: 20px; border: 1px solid #ddd; border-radius: 4px; padding: 0;">
                        <summary style="padding: 10px; background-color: #f0f0f0; font-weight: bold; cursor: pointer;">
                            Pasos de cálculo (clic para expandir)
                        </summary>
                        <div style="padding: 15px; border-top: 1px solid #ddd;">
                            {format_steps_table(pasos)}
                        </div>
                    </details>
                    """
                    
                return html
                
            # Get UVT value
            value_uvt = data.get('uvt', 0)
            
            # Prepare headers
            html = f"""
            <div style="font-family: Arial, sans-serif; font-size: 14px; line-height: 1.5; max-width: 800px; margin: 0 auto;">
                <div style="background-color: #1E6C93; color: white; padding: 15px; border-radius: 5px; margin-bottom: 20px;">
                    <div style="font-size: 18px; font-weight: bold;">LIQUIDACIÓN RETENCIÓN EN LA FUENTE</div>
                    <div style="font-size: 14px;">Empleado: {data.get('employee_name', 'N/A')} - Documento: {data.get('employee_document', 'N/A')}</div>
                    <div style="font-size: 14px;">Año fiscal: {data.get('year', '')}</div>
                    <div style="display: flex; justify-content: space-between; margin-top: 10px;">
                        <div>Valor UVT: {format_currency(value_uvt)}</div>
                    </div>
                </div>
            """
            
            # Verification message if using projection
            if data.get('es_proyectado', False):
                html += format_info_box(
                    "Proyección aplicada", 
                    "Este cálculo se realizó aplicando una proyección de ingresos y deducciones por tratarse de la primera quincena del mes.", 
                    "warning"
                )
                
                # Show unprojected values if available
                valores_sin_proyectar = data.get('valores_sin_proyectar', None)
                if valores_sin_proyectar:
                    html += format_info_box(
                        "Valores originales sin proyectar",
                        f"""
                        <table style="width: 100%; border-collapse: collapse; font-size: 0.9em;">
                            <tr><td>Salario:</td><td style="text-align: right;">{format_currency(valores_sin_proyectar.get('basic', 0))}</td></tr>
                            <tr><td>Comisiones:</td><td style="text-align: right;">{format_currency(valores_sin_proyectar.get('comisiones', 0))}</td></tr>
                            <tr><td>Devengos salariales:</td><td style="text-align: right;">{format_currency(valores_sin_proyectar.get('dev_salarial', 0))}</td></tr>
                            <tr><td>Devengos no salariales:</td><td style="text-align: right;">{format_currency(valores_sin_proyectar.get('dev_no_salarial', 0))}</td></tr>
                            <tr><td style="font-weight: bold;">Total ingresos base:</td><td style="text-align: right; font-weight: bold;">{format_currency(valores_sin_proyectar.get('total_ing_base', 0))}</td></tr>
                        </table>
                        """,
                        "info"
                    )
            
            # 1. INGRESOS
            ingresos_content = "".join([
                format_row("Salario básico", format_currency(data.get('salario', 0))),
                format_row("Comisiones", format_currency(data.get('comisiones', 0))),
                format_row("Devengos salariales", format_currency(data.get('dev_salarial', 0))),
                format_row("Devengos no salariales", format_currency(data.get('dev_no_salarial', 0))),
                format_row("Total ingresos laborales", format_currency(data.get('total_ing_base', 0)), is_total=True)
            ])
            
            html += format_section("1. INGRESOS LABORALES", ingresos_content)
            
            # 2. INGRESOS NO CONSTITUTIVOS DE RENTA
            pension_info = ""
            desglose_pension = data.get('desglose_pension', {})
            if desglose_pension:
                pension_info = format_subsection("Detalle aportes a pensión", 
                    "".join([
                        format_row("Pensión obligatoria", format_currency(desglose_pension.get('pension', 0)), base_legal="Art. 55 ET"),
                        format_row("Fondo de subsistencia", format_currency(desglose_pension.get('subsistencia', 0)), base_legal="Art. 55 ET"),
                        format_row("Fondo de solidaridad", format_currency(desglose_pension.get('solidaridad', 0)), base_legal="Art. 55 ET")
                    ])
                )
            
            no_renta_content = "".join([
                format_row("Aportes obligatorios a pensión", format_currency(data.get('total_pension', 0)), base_legal="Art. 55 ET"),
                format_row("Aportes obligatorios a salud", format_currency(data.get('salud', 0)), base_legal="Art. 56 ET"),
                format_row("Total ingresos no constitutivos", format_currency(data.get('ing_no_gravados', 0)), is_total=True)
            ])
            
            no_renta_content += pension_info
            
            html += format_section("2. INGRESOS NO CONSTITUTIVOS DE RENTA", no_renta_content)
            
            # Calculate the remaining sections data
            html += format_section("3. INGRESO NETO", format_row("Ingresos netos (base para cálculo)", format_currency(data.get('ing_base', 0)), is_total=True))
            
            # 4. DEDUCCIONES
            deducciones_rows = []
            
            # Vivienda
            desglose_vivienda = data.get('desglose_vivienda', {})
            if desglose_vivienda:
                limite_text = f"Límite: 100 UVT mensuales ({format_currency(desglose_vivienda.get('limite_pesos', 0))})"
                deducciones_rows.append(format_row(
                    "Intereses de vivienda", 
                    format_currency(data.get('ded_vivienda', 0)),
                    base_legal="Art. 387 ET",
                    observation=limite_text
                ))
                
            # Dependientes
            desglose_dependientes = data.get('desglose_dependientes', {})
            if desglose_dependientes:
                limite_text = f"Límite: 10% del ingreso total, máx. 32 UVT mensuales ({format_currency(desglose_dependientes.get('limite_pesos_uvt', 0))})"
                deducciones_rows.append(format_row(
                    "Dependientes", 
                    format_currency(data.get('ded_dependientes', 0)),
                    base_legal="Art. 387 ET",
                    observation=limite_text
                ))
                
            # Salud prepagada
            desglose_salud = data.get('desglose_salud', {})
            if desglose_salud:
                limite_text = f"Límite: 16 UVT mensuales ({format_currency(desglose_salud.get('limite_pesos', 0))})"
                deducciones_rows.append(format_row(
                    "Medicina prepagada", 
                    format_currency(data.get('ded_salud', 0)),
                    base_legal="Art. 387 ET",
                    observation=limite_text
                ))
                
            # Auxilios de alimentación
            desglose_alimentacion = data.get('desglose_alimentacion', {})
            if desglose_alimentacion:
                limite_text = f"Límite: 41 UVT, aplicable si ingreso < 310 UVT ({format_currency(desglose_alimentacion.get('limite_pesos', 0))})"
                deducciones_rows.append(format_row(
                    "Auxilios de alimentación", 
                    format_currency(data.get('ded_alimentacion', 0)),
                    base_legal="Art. 387 ET",
                    observation=limite_text
                ))
                
            deducciones_rows.append(format_row("Total deducciones", format_currency(data.get('total_deducciones', 0)), is_total=True))
            
            deducciones_content = "".join(deducciones_rows)
            html += format_section("4. DEDUCCIONES", deducciones_content)
            
            # 5. RENTAS EXENTAS
            rentas_exentas_rows = []
            
            # AVP/AFC
            desglose_avp_afc = data.get('desglose_avp_afc', {})
            if desglose_avp_afc:
                avp_afc_content = format_subsection("Detalle aportes AVP/AFC", 
                    "".join([
                        format_row("Aportes a AVP (nómina)", format_currency(desglose_avp_afc.get('avp_nomina', 0))),
                        format_row("Aportes a AVP (empleador)", format_currency(desglose_avp_afc.get('avp_empleador', 0))),
                        format_row("Aportes a AVP (certificado)", format_currency(desglose_avp_afc.get('avp_certificado', 0))),
                        format_row("Aportes a AFC (nómina)", format_currency(desglose_avp_afc.get('afc_nomina', 0))),
                        format_row("Aportes a AFC (empleador)", format_currency(desglose_avp_afc.get('afc_empleador', 0))),
                        format_row("Aportes a AFC (certificado)", format_currency(desglose_avp_afc.get('afc_certificado', 0)))
                    ])
                )
                
                limite_text = (
                    f"Límite: 30% del ingreso total ({format_currency(desglose_avp_afc.get('limite_pesos_porcentaje', 0))}) y "
                    f"máx. 3.800 UVT anuales ({format_currency(desglose_avp_afc.get('limite_pesos_anual', 0))})"
                )
                
                acum_info = (
                    f"Acumulado anual: {format_currency(desglose_avp_afc.get('acumulado_anual', 0))} - "
                    f"Disponible: {format_currency(desglose_avp_afc.get('limite_disponible', 0))}"
                )
                
                rentas_exentas_rows.append(format_row(
                    "Aportes a AVP y AFC", 
                    format_currency(data.get('total_re', 0)),
                    base_legal="Art. 126-1, 126-4 ET",
                    observation=f"{limite_text}<br>{acum_info}"
                ))
                
                rentas_exentas_rows.append(avp_afc_content)
                
            # Subtotal después de deducciones y AVP/AFC
            rentas_exentas_rows.append(format_row("Subtotal 1 (Ingresos - Deducciones)", format_currency(data.get('subtotal_ibr1', 0))))
            rentas_exentas_rows.append(format_row("Subtotal 2 (Subtotal 1 - AVP/AFC)", format_currency(data.get('subtotal_ibr2', 0))))
            
            # Renta exenta 25%
            desglose_re25 = data.get('desglose_re25', {})
            if desglose_re25:
                limite_text = f"Límite: 790 UVT anuales ({format_currency(desglose_re25.get('limite_pesos_anual', 0))})"
                acum_info = (
                    f"Acumulado anual: {format_currency(desglose_re25.get('acumulado_anual', 0))} - "
                    f"Disponible: {format_currency(desglose_re25.get('limite_disponible', 0))}"
                )
                
                rentas_exentas_rows.append(format_row(
                    "Renta exenta del 25%", 
                    format_currency(data.get('renta_exenta_25', 0)),
                    base_legal="Art. 206 ET, Núm. 10",
                    observation=f"{limite_text}<br>{acum_info}"
                ))
                
            rentas_exentas_rows.append(format_row("Total rentas exentas", format_currency(data.get('renta_exenta_25', 0) + data.get('total_re', 0)), is_total=True))
            
            rentas_exentas_content = "".join(rentas_exentas_rows)
            html += format_section("5. RENTAS EXENTAS", rentas_exentas_content)
            
            # 6. LÍMITE GLOBAL 40%
            desglose_limite = data.get('desglose_limite', {})
            if desglose_limite:
                limite_text = (
                    f"Límite: 40% del ingreso neto ({format_currency(desglose_limite.get('limite_pesos_porcentaje', 0))}) y "
                    f"máx. 1.340 UVT anuales ({format_currency(desglose_limite.get('limite_pesos_anual', 0))})"
                )
                
                acum_info = (
                    f"Acumulado anual: {format_currency(desglose_limite.get('acumulado_anual', 0))} - "
                    f"Disponible: {format_currency(desglose_limite.get('limite_disponible', 0))}"
                )
                
                proporcion = f"Proporción aplicada: {format_percent(desglose_limite.get('proporcion_aplicada', 0))}"
                
                limite_content = "".join([
                    format_row("Total beneficios antes de límite", format_currency(data.get('total_beneficios', 0))),
                    format_row(
                        "Beneficios limitados", 
                        format_currency(data.get('beneficios_limitados', 0)),
                        base_legal="Art. 387 ET, Ley 2277/2022",
                        observation=f"{limite_text}<br>{acum_info}<br>{proporcion}"
                    )
                ])
                
                html += format_section("6. APLICACIÓN LÍMITE GLOBAL 40%", limite_content)
                
            # 7. BASE GRAVABLE Y CÁLCULO DE RETENCIÓN
            base_content = "".join([
                format_row("Base gravable final", format_currency(data.get('subtotal_ibr3', 0))),
                format_row("Base gravable en UVTs", format_number(data.get('ibr_uvts', 0))),
                format_row("Tarifa aplicable", f"{format_number(data.get('rate', 0), 0)}%", base_legal="Art. 383 ET"),
                format_row("Retención calculada", format_currency(data.get('retencion', 0))),
                format_row("Retención anterior", format_currency(data.get('retencion_anterior', 0))),
                format_row("Retención a aplicar", format_currency(data.get('retencion_def', 0)), is_total=True, base_legal="Ley 1111/2006 Art. 50")
            ])
            
            html += format_section("7. BASE GRAVABLE Y CÁLCULO DE RETENCIÓN", base_content)
            
            # Add legal information and notes
            html += format_info_box(
                "NOTA LEGAL SOBRE LÍMITE GLOBAL", 
                "La sumatoria de las deducciones, rentas exentas y la renta de trabajo exenta del 25%, no podrá exceder del 40% del ingreso neto del contribuyente y con un límite de 1.340 UVT anuales conforme al Art. 387 ET y la Ley 2277 de 2022.",
                "legal"
            )
            
            # Agregar sección de pasos detallados si está disponible
            pasos = data.get('pasos', [])
            if pasos:
                html += f"""
                    <details style="margin-top: 20px; margin-bottom: 20px; border: 1px solid #ddd; border-radius: 4px; padding: 0;">
                        <summary style="padding: 10px; background-color: #f0f0f0; font-weight: bold; cursor: pointer;">
                            Pasos de cálculo detallados (clic para expandir)
                        </summary>
                        <div style="padding: 15px; border-top: 1px solid #ddd;">
                            {format_steps_table(pasos)}
                        </div>
                    </details>
                """
            
            # If there's detailed data, add collapsible section
            if 'desglose_vivienda' in data or 'desglose_dependientes' in data or 'desglose_salud' in data or 'desglose_alimentacion' in data:
                detalles_html = ""
                
                if 'desglose_vivienda' in data:
                    detalles_html += format_subsection("Intereses vivienda", format_detail_table(data['desglose_vivienda']))
                
                if 'desglose_dependientes' in data:
                    detalles_html += format_subsection("Dependientes", format_detail_table(data['desglose_dependientes']))
                
                if 'desglose_salud' in data:
                    detalles_html += format_subsection("Medicina prepagada", format_detail_table(data['desglose_salud']))
                
                if 'desglose_alimentacion' in data:
                    detalles_html += format_subsection("Auxilios alimentación", format_detail_table(data['desglose_alimentacion']))
                
                if 'desglose_avp_afc' in data:
                    detalles_html += format_subsection("AVP y AFC", format_detail_table(data['desglose_avp_afc']))
                
                if 'desglose_re25' in data:
                    detalles_html += format_subsection("Renta exenta 25%", format_detail_table(data['desglose_re25']))
                
                if 'desglose_limite' in data:
                    detalles_html += format_subsection("Límite global 40%", format_detail_table(data['desglose_limite']))
                
                html += f"""
                    <details style="margin-top: 20px; margin-bottom: 20px; border: 1px solid #ddd; border-radius: 4px; padding: 0;">
                        <summary style="padding: 10px; background-color: #f0f0f0; font-weight: bold; cursor: pointer;">
                            Detalles de cálculo (clic para expandir)
                        </summary>
                        <div style="padding: 15px; border-top: 1px solid #ddd;">
                            {detalles_html}
                        </div>
                    </details>
                """
                
            # Add footer
            html += f"""
                <div style="margin-top: 20px; border-top: 1px solid #ddd; padding-top: 10px; font-size: 0.8em; color: #666; text-align: center;">
                    Liquidación de retención en la fuente - Art. 383 a 389 del Estatuto Tributario<br>
                    Generado por el sistema de nómina
                </div>
            </div>
            """
                
            return html
        except Exception as e:
            return f"<div>Error al generar el reporte: {str(e)}</div>"

    def _combine_reports(self, reports):
        combined_html = '<div class="prestaciones-sociales-combined-report">'
        combined_html += '<h1>Reporte de Prestaciones Sociales</h1>'
        for report in reports:
            combined_html += report
            combined_html += '<hr>'  # Separador entre reportes
        combined_html += '</div>'
        return combined_html

    @api.depends('line_ids', 'leave_ids', 'worked_days_line_ids')
    def _compute_payslip_detail(self):
        for payslip in self:
            payslip.payslip_detail = 'Calculated'

    def _periodo(self):
        for rec in self:
            if rec.date_to:
                rec.periodo = rec.date_to.strftime("%Y%m")
            else:
                rec.periodo = ''
    
    def old_payslip_moth(self):
        payslip_objs = self.env['hr.payslip'].search([('struct_id.process', 'in', ['vacaciones', 'prima'])])
        for record in self:
            record.payslip_old_ids = [(6, 0, payslip_objs.ids)]

    def _assign_old_payslips(self):
        for payslip in self:
            start_date = payslip.date_from.replace(day=1)
            end_date = (start_date + relativedelta(months=1, days=-1))
            
            domain = [
                ('id', '!=', payslip.id),  # Para excluir la nómina actual
                ('employee_id', '=', payslip.employee_id.id),
                ('contract_id', '=', payslip.contract_id.id),
                ('date_from', '>=', start_date.strftime('%Y-%m-%d')),
                ('date_to', '<=', end_date.strftime('%Y-%m-%d')),
                ('struct_id.process', 'in', ['vacaciones', 'prima']),
            ]
            old_payslips = self.env['hr.payslip'].search(domain)
            payslip.payslip_old_ids = [(6, 0, old_payslips.ids)]

    def _compute_extra_hours(self):
        for payslip in self:
            if payslip.struct_id.process in ('nomina', 'contrato', 'otro'):
                query = """
                UPDATE hr_overtime
                SET payslip_run_id = %s
                WHERE 
                    (state = 'validated' OR payslip_run_id IS NULL)
                    AND date_end BETWEEN %s AND %s
                    AND employee_id = %s
                """
                self.env.cr.execute(query, (payslip.id, payslip.date_from, payslip.date_to, payslip.employee_id.id))

    def _compute_novedades(self):
        for payslip in self:
            query_params = [payslip.id, payslip.employee_id.id]
            date_conditions = ""
            if payslip.struct_id.process in ('nomina', 'contrato', 'otro', 'prima'):
                date_conditions = "AND date >= %s AND date <= %s"
                query_params.extend([payslip.date_from, payslip.date_to])

            query = """
            UPDATE hr_novelties_different_concepts
            SET payslip_id = %s
            WHERE payslip_id IS NULL 
            AND employee_id = %s 
            """ + date_conditions
            self.env.cr.execute(query, tuple(query_params))

    def compute_slip(self):
        self_ids = tuple(self._ids)
        if not self_ids:
            return True
        self._cr.execute("""
            SELECT id, struct_id, date_from, date_to, contract_id, employee_id, 
                struct_process, date_liquidacion, pay_primas_in_payroll, 
                pay_cesantias_in_payroll, number
            FROM hr_payslip
            WHERE id IN %s AND state IN ('draft', 'verify')
        """, (self_ids,))
        slips_data = self._cr.dictfetchall()
        if not slips_data:
            return True
        today = fields.Date.today()
        PayslipLine = self.env['hr.payslip.line']
        for slip_data in slips_data:
            slip = self.browse(slip_data['id'])
            slip._update_prima_cesantias_dates(slip, slip_data)
            if slip._check_duplicate_slip(slip_data):
                raise UserError(f"No puede existir más de una nómina del mismo tipo y periodo para el empleado {slip.employee_id.name}")
            name = f"Nomina de {slip.contract_id.name}"
            slip.write({
                'name': name,
                'state': 'verify',
                'compute_date': today
            })
            date_from = slip_data['date_from']
            date_to = slip_data['date_to']
            days_diff = (date_to - date_from).days + 1
            period_type = 'monthly' if days_diff > 15 else 'bi-monthly'
            period = self.env['hr.period'].get_period(
                date_from, 
                date_to,
                period_type,
                self.company_id.id
            )
            if period:
                self.period_id = period.id
            else:
                self.assign_periods_to_draft_payslips()
                self.period_id = self.env['hr.period'].get_period(date_from, date_to, period_type, self.company_id.id).id
            slip.leave_ids.unlink()
            slip.compute_sheet_leave()
            slip._compute_extra_hours()
            slip._process_loan_lines()
            slip._compute_novedades()
            self._cr.execute("DELETE FROM hr_payslip_worked_days WHERE payslip_id = %s", (slip.id,))
            self._cr.execute("DELETE FROM hr_payslip_line WHERE slip_id = %s", (slip.id,))
            self.env.flush_all()
            slip._action_compute_worked_days()
            PayslipLine.create(slip._get_payslip_lines_lavish())
        return True

    def recompute_worked_days_action(self):
        errors = []
        success = 0
        for slip in self:
            try:
                slip.leave_ids.unlink()
                slip.worked_days_line_ids.unlink()
                slip.compute_sheet_leave()
                worked_days_line_ids = slip.get_worked_day_lines()
                slip.worked_days_line_ids = [(0, 0, line) for line in worked_days_line_ids]
            except Exception as e:
                errors.append(f'Error en nómina {slip.name}: {str(e)}')
        message = f'Proceso completado.\nNóminas actualizadas: {success}'
        if errors:
            message += '\n\nErrores encontrados:\n' + '\n'.join(errors)
            
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Resultado del recálculo',
                'message': message,
                'sticky': True,
                'type': 'info' if success else 'warning',
            }
        }

    def _update_prima_cesantias_dates(self, slip, slip_data):
        if slip_data['struct_process'] in ['prima', 'contrato'] or slip_data['pay_primas_in_payroll']:
            from_month = 1 if slip_data['date_from'].month <= 6 else 7
            date_from = slip_data['date_from'].replace(month=from_month, day=1)
            if date_from < slip.contract_id.date_start:
                date_from = slip.contract_id.date_start
            slip.date_prima = date_from
        if slip_data['struct_process'] in ['cesantias', 'contrato'] or slip_data['pay_cesantias_in_payroll']:
            date_ref = slip_data['date_to']
            date_from = date_ref.replace(month=1, day=1)
            if date_from < slip.contract_id.date_start:
                date_from = slip.contract_id.date_start
            slip.date_cesantias = date_from

    def _check_duplicate_slip(self, slip_data):
        if slip_data['struct_process'] not in ('vacaciones', 'contrato', 'otro'):
            self._cr.execute("""
                SELECT COUNT(id) FROM hr_payslip
                WHERE contract_id = %s AND date_from >= %s AND date_to <= %s
                AND struct_process = %s AND id != %s
            """, (slip_data['contract_id'], slip_data['date_from'], slip_data['date_to'], 
                slip_data['struct_process'], slip_data['id']))
            return self._cr.fetchone()[0] > 0
        return False

    def compute_precise(self, value1: float =0.0, value2: float  =0.0, operation: str = '*', decimals: int = PRECISION_TECHNICAL) -> float:
        """Realiza cálculos con alta precisión"""
        factor = 10 ** decimals
        int_value1 = int(float(value1) * factor)
        int_value2 = int(float(value2) * factor)
        
        if operation == '*':
            result = (int_value1 * int_value2) // factor
        elif operation == '/':
            if int_value2 == 0:
                raise ValueError("División por cero")
            result = (int_value1 * factor) // int_value2
        elif operation == '+':
            result = int_value1 + int_value2
        elif operation == '-':
            result = int_value1 - int_value2
        else:
            raise ValueError(f"Operación {operation} no soportada")
        return result / factor
    
    def get_completed_paid_payslips_by_period(self, contract_id: int, from_year_month: Optional[str] = None, to_year_month: Optional[str] = None) -> Dict[str, int]:
        """
        Obtiene las nóminas con estado 'done' / 'paid' por período para un contrato específico.
        """
        query = """
        SELECT 
            to_char(p.date_from, 'YYYY-MM') as year_month,
            COUNT(p.id) as total_payslips,
            array_agg(p.id) as payslip_ids
        FROM 
            hr_payslip p
        WHERE 
            p.state IN ('done', 'paid')
            AND p.contract_id = %s
        """
        params = [contract_id]
        if from_year_month and not to_year_month:
            query += " AND to_char(p.date_from, 'YYYY-MM') = %s"
            params.append(from_year_month)
        elif from_year_month and to_year_month:
            query += " AND to_char(p.date_from, 'YYYY-MM') >= %s AND to_char(p.date_from, 'YYYY-MM') <= %s"
            params.extend([from_year_month, to_year_month])
        query += """
        GROUP BY to_char(p.date_from, 'YYYY-MM')
        ORDER BY year_month ASC
        """
        self.env.cr.execute(query, params)
        return self.env.cr.dictfetchall()

    def get_payslip_days_count(self, payslip_id: int) -> dict[str, int]:
        """
        Devuelve un diccionario con la cantidad de días de la nómina por tipo:
        - Días festivos
        - Domingos
        - Días trabajados
        - Ausencias
        
        Args:
            payslip_id (int): ID de la nómina
        
        Returns:
            dict: Diccionario con la cantidad de días por tipo
        """
        payslip_days = self.env['hr.payslip.day'].search([
            ('payslip_id', '=', payslip_id)
        ])
        
        festivos = 0
        domingos = 0
        ausencias = 0
        trabajados = 0
        sabado = 0
        for day in payslip_days:
            if day.is_holiday:
                festivos += 1
            elif day.is_sunday:
                domingos += 1
            elif day.is_saturday:
                sabado += 1
            elif day.is_absence:
                ausencias += 1
            elif not (day.is_holiday or day.is_sunday or day.is_absence):
                trabajados += 1
        
        result = {
            'sabado': sabado,
            'festivos': festivos,
            'domingos': domingos,
            'trabajados': trabajados,
            'ausencias': ausencias,
        }
        
        return result
    
    def load_payslip_lines(self, localdict):
        """
        Carga todas las líneas de nómina de períodos anteriores y las organiza
        por código de regla y tipo de período, con acceso optimizado a totales.
        
        Args:
            localdict (dict): Diccionario local con datos de nómina
            
        Returns:
            dict: Estructura de líneas de nómina organizadas por código y período
        """
        payslip_lines = {}
        all_payslip_ids = set()
        period_mapping = {}
        
        # Mes actual
        if 'current_month' in localdict and localdict['current_month']:
            for month_info in localdict['current_month']:
                payslip_ids = [p for p in month_info.get('payslip_ids', []) if p != self.id]
                for p_id in payslip_ids:
                    all_payslip_ids.add(p_id)
                    period_mapping[p_id] = 'current_month'
        
        # Mes anterior
        if 'before_month' in localdict and localdict['before_month']:
            for month_info in localdict['before_month']:
                payslip_ids = month_info.get('payslip_ids', [])
                for p_id in payslip_ids:
                    all_payslip_ids.add(p_id)
                    period_mapping[p_id] = 'before_month'
        
        # Prima
        if 'prima_current_month' in localdict and localdict['prima_current_month']:
            for month_info in localdict['prima_current_month']:
                payslip_ids = month_info.get('payslip_ids', [])
                for p_id in payslip_ids:
                    all_payslip_ids.add(p_id)
                    if p_id in period_mapping:
                        period_mapping[p_id] = f"{period_mapping[p_id]},prima"
                    else:
                        period_mapping[p_id] = 'prima'
        
        # Cesantías
        if 'cesantias_current_month' in localdict and localdict['cesantias_current_month']:
            for month_info in localdict['cesantias_current_month']:
                payslip_ids = month_info.get('payslip_ids', [])
                for p_id in payslip_ids:
                    all_payslip_ids.add(p_id)
                    if p_id in period_mapping:
                        period_mapping[p_id] = f"{period_mapping[p_id]},cesantias"
                    else:
                        period_mapping[p_id] = 'cesantias'

        if 'last_year_info' in localdict and localdict['last_year_info']:
            for month_info in localdict['last_year_info']:
                payslip_ids = month_info.get('payslip_ids', [])
                for p_id in payslip_ids:
                    all_payslip_ids.add(p_id)
                    if p_id in period_mapping:
                        period_mapping[p_id] = f"{period_mapping[p_id]},last_year"
                    else:
                        period_mapping[p_id] = 'last_year'    
        
        # 2. Buscar y procesar las líneas de nómina
        if all_payslip_ids:
            lines = self.env['hr.payslip.line'].search([
                ('slip_id', 'in', list(all_payslip_ids))
            ])
            
            for line in lines:
                if line.code not in payslip_lines:
                    payslip_lines[line.code] = {
                        'current_month': {'entries': [], 'total': 0, 'rule': None, 'tiene_ausencias': False, 'total_ausencias': 0, 'cantidad_ausencias': 0},
                        'before_month': {'entries': [], 'total': 0, 'rule': None, 'tiene_ausencias': False, 'total_ausencias': 0, 'cantidad_ausencias': 0},
                        'prima': {'entries': [], 'total': 0, 'rule': None, 'tiene_ausencias': False, 'total_ausencias': 0, 'cantidad_ausencias': 0},
                        'cesantias': {'entries': [], 'total': 0, 'rule': None, 'tiene_ausencias': False, 'total_ausencias': 0, 'cantidad_ausencias': 0},
                        'last_year': {'entries': [], 'total': 0, 'rule': None, 'tiene_ausencias': False, 'total_ausencias': 0, 'cantidad_ausencias': 0}
                    }
                    # Agregar totales globales por código
                    payslip_lines[line.code]['tiene_ausencias'] = False
                    payslip_lines[line.code]['total_ausencias'] = 0
                    payslip_lines[line.code]['cantidad_ausencias'] = 0
                
                # Verificar si la línea tiene ausencia asociada
                tiene_ausencia = line.leave_id
                
                entry = {
                    'payslip_id': line,
                    'amount': line.amount,
                    'quantity': line.quantity,
                    'rate': line.rate,
                    'total': line.total,
                    'date': line.slip_id.date_to,
                    'rule': line.salary_rule_id,
                    'tiene_ausencia': tiene_ausencia  # Booleano a nivel de entrada
                }
                
                periods = period_mapping.get(line.slip_id.id, '').split(',')
                
                for period in periods:
                    if period and period in payslip_lines[line.code]:
                        payslip_lines[line.code][period]['entries'].append(entry)
                        payslip_lines[line.code][period]['total'] += line.total
                        payslip_lines[line.code][period]['rule'] = line.salary_rule_id
                        
                        # Actualizar contadores de ausencias a nivel de período
                        if tiene_ausencia:
                            payslip_lines[line.code][period]['tiene_ausencias'] = True
                            payslip_lines[line.code][period]['total_ausencias'] += line.total
                            payslip_lines[line.code][period]['cantidad_ausencias'] += line.quantity if hasattr(line, 'quantity') else 0
                            
                            # Actualizar totales globales por código
                            payslip_lines[line.code]['tiene_ausencias'] = True
                            payslip_lines[line.code]['total_ausencias'] += line.total
                            payslip_lines[line.code]['cantidad_ausencias'] += line.quantity if hasattr(line, 'quantity') else 0
        
        return payslip_lines
            
    def _get_localdict_payslip(self) -> dict[str, Any]:
        
        def get_previous_month(date_str: date) -> str:
            """
            Obtiene el año-mes (YYYY-MM) del mes anterior al proporcionado.
            """
            current_date = date_str.strftime('%Y-%m')
            previous_month = datetime.strptime(current_date, '%Y-%m') - relativedelta(months=1)
            return previous_month.strftime('%Y-%m')
        self.ensure_one()
        worked_days_dict = {line.code: line for line in self.worked_days_line_ids if line.code}
        date_from = self.date_from
        start_period = date_from.replace(day=1)
        date_to = self.date_to        
        employee = self.employee_id
        contract = self.contract_id
        date_from_time = datetime.combine(date_from, DATETIME_MIN)
        date_to_time = datetime.combine(date_to, DATETIME_MAX)
        date_prima = self.date_prima if  self.date_prima else date_from.replace(month=1, day=1)
        date_liquidacion = self.date_liquidacion or date_to
        date_from_last_year = date_liquidacion - relativedelta(years=1)
        if date_from_last_year < contract.date_start:
            date_from_last_year = contract.date_start
        date_cesantias = self.date_cesantias or date_from.replace(month=1, day=1)
        input_list = [line.code for line in self.input_line_ids if line.code]
        cnt = Counter(input_list)
        multi_input_lines = [k for k, v in cnt.items() if v > 1]
        same_type_input_lines = {line_code: [line for line in self.input_line_ids if line.code == line_code] for line_code in multi_input_lines}
        inputs_dict = {line.code: line for line in self.input_line_ids if line.code}

        wage = False
        annual_parameters = self.env['hr.annual.parameters'].search([('year', '=', date_to.year)])
        current_month = self.get_completed_paid_payslips_by_period(contract.id, from_year_month=date_from.strftime("%Y-%m"))
        before_month = self.get_completed_paid_payslips_by_period(contract.id, from_year_month=get_previous_month(date_from))
        prima_current_month = {}
        cesantias_current_month = {}
        last_year_info = {}       
        if self.struct_process in ['prima', 'contrato'] or self.pay_primas_in_payroll:
            prima_current_month = self.get_completed_paid_payslips_by_period(contract.id, from_year_month=date_prima.strftime("%Y-%m"), to_year_month=date_liquidacion.strftime("%Y-%m"))
        if self.struct_process in ['cesantias', 'contrato'] or self.pay_cesantias_in_payroll:
            cesantias_current_month = self.get_completed_paid_payslips_by_period(contract.id, from_year_month=date_cesantias.strftime("%Y-%m"), to_year_month=date_liquidacion.strftime("%Y-%m"))
        if self.struct_process in ['vacaciones', 'contrato', 'otros'] or self.pay_cesantias_in_payroll:
            last_year_info = self.get_completed_paid_payslips_by_period(contract.id, from_year_month=date_from_last_year.strftime("%Y-%m"), to_year_month=date_liquidacion.strftime("%Y-%m"))
        if not annual_parameters:
            raise UserError('Falta Configurar los parametros anuales ir a --> Configuracion/ Parametros anuales')
        wage = contract.wage
        obj_wage = self.env['hr.contract.change.wage'].search([('contract_id', '=', contract.id), ('date_start', '<', date_to)])
        for change in sorted(obj_wage, key=lambda x: x.date_start):
            if float(change.wage) > 0:
                wage = change.wage 
        rules_multi = {}
        payslip_lines = self.load_payslip_lines({
        'current_month': current_month,
        'before_month': before_month,
        'prima_current_month': prima_current_month,
        'cesantias_current_month': cesantias_current_month,
        'last_year_info': last_year_info
        })
        localdict = {
            **self._get_base_local_dict(),
            **self.get_payslip_days_count(self.id),
            **{
                'categories': BrowsableObject(employee.id, {}, self.env),
                'rules_computed': BrowsableObject(employee.id, {}, self.env),
                'rules': BrowsableObject(employee.id, {}, self.env),
                'payslip': Payslips(employee.id, self, self.env),
                'worked_days': WorkedDays(employee.id, worked_days_dict, self.env),
                'inputs': InputLine(employee.id, inputs_dict, self.env),
                'employee': employee,
                'contract': contract,
                'ibc_full': 0,
                'date_to_time': date_to_time,
                'date_from_time': date_from_time,
                'current_month': current_month,
                'before_month': before_month,
                'prima_current_month': prima_current_month,
                'cesantias_current_month': cesantias_current_month,
                'last_year_info': last_year_info,
                'result_rules': ResultRules(employee.id, {}, self.env),
                'result_rules_co': ResultRules_co(employee.id, {}, self.env),
                'same_type_input_lines': same_type_input_lines,
                'wage':wage,
                'slip': self,
                'start_period': start_period,
                'id_contract_concepts':0,
                'annual_parameters': annual_parameters,
                'payslips_month':current_month,
                'inherit_contrato':0,
                'rules_multi': rules_multi,
                'payslip_lines': payslip_lines,
            }
        }

        return localdict

    def _sum_salary_rule_category(self, localdict, category, amount):
        if category.parent_id:
            localdict = self._sum_salary_rule_category(localdict, category.parent_id, amount)
        localdict['categories'].dict[category.code] = localdict['categories'].dict.get(category.code, 0) + amount
        return localdict

    def _sum_salary_rule(self, localdict, rule, amount, quantity=1.0, rate=100.0, dict_leave={}, log=None):
        """
        Actualiza la suma de reglas en la estructura tradicional BrowsableObject
        y almacena información básica en rules_multi para la regla actual.
        Si la clave ya existe, solo actualiza el valor en lugar de sobrescribirlo.
        """
        localdict['rules_computed'].dict[rule.code] = localdict['rules_computed'].dict.get(rule.code, 0) + amount
        qty_unit = quantity
        if 'rules_multi' not in localdict:
            localdict['rules_multi'] = {}
        if quantity == 0:
            qty_unit = 0
        else:
            qty_unit = amount / quantity
        
        if rule.code in localdict['rules_multi']:
            localdict['rules_multi'][rule.code]['current']['amount'] += qty_unit
            localdict['rules_multi'][rule.code]['current']['quantity'] += quantity
            localdict['rules_multi'][rule.code]['current']['total'] += amount
            if dict_leave:
                localdict['rules_multi'][rule.code]['current']['leave'].update(dict_leave)
        else:
            localdict['rules_multi'][rule.code] = {
                'current': {
                    'payslip_id': self.id,
                    'amount': qty_unit,
                    'quantity': quantity,
                    'rate': rate,
                    'total': amount,
                    'category': rule.category_id.code if rule.category_id else None,
                    'object': rule,
                    'leave': dict_leave,
                    'log': log
                }
            }
        
        return localdict

    def _get_payslip_lines_lavish(self) -> list[dict[str, Any]]:
        for payslip in self:
            if not payslip.contract_id:
                raise UserError(_("No hay ningún contrato establecido en La nomina %s para %s. Verifique que haya al menos un contrato establecido en el formulario del empleado.", payslip.name, payslip.employee_id.name))
            
            localdict = self.env.context.get('force_payslip_localdict', None) or payslip._get_localdict_payslip()
            localdict['rules'] = localdict.get('rules', {})
            localdict['result_rules'] = localdict.get('result_rules', {})
            localdict['result_rules_co'] = localdict.get('result_rules_co', {})
            result_leave = {}
            result = {}
            absence_dict = payslip._calculate_absences()
            localdict, result_leave = payslip._update_localdict_for_absences(localdict, absence_dict)
            localdict, result = payslip._calculate_absences_and_update_dict(payslip, localdict)
            result = payslip._process_salary_rules(payslip, localdict, result)

          
            #    return {}  # Devolver diccionario vacío en lugar de valor no válido
            combined_result = {**result_leave, **result}
            return list(combined_result.values())
        return []  

    def _calculate_absences_and_update_dict(self, payslip:'HrPayslip', localdict:dict[str,Any]) -> tuple[dict[str,Any], dict[str,Any]]:
        """
        Procesa conceptos y actualiza el diccionario local
        """
        result = {}
        skip_novelties = (payslip.struct_id.process == 'contrato' and not payslip.novelties_payroll_concepts)
        applicable_rules = payslip._get_rules_to_process()
        # 1. Procesar conceptos de contrato
        for concept in localdict['contract'].concepts_ids.filtered(lambda l: l.state in ['done', 'closed']):
            if skip_novelties:
                continue
            if concept.input_id.amount_select in ['code', 'concept']:
                continue
            concept_process_result = concept.get_computed_amount_for_payslip(
                payslip=payslip,
                date_from=payslip.date_from,
                date_to=payslip.date_to,
                localdict=localdict
            )
            if not concept_process_result.get('create_line', False):
                continue
            rule = concept.input_id
            if rule.id not in applicable_rules.ids:
                continue
            line_values = concept_process_result.get('values', {})
            code = rule.code
            name = line_values.get('name', concept.input_id.name)
            amount = line_values.get('amount', 0.0)
            quantity = line_values.get('quantity', 1.0)
            rate = line_values.get('rate', 100.0)
            if amount == 0 and not concept_process_result.get('force_create', False):
                continue
            localdict, result = self._create_concept_line(
                    localdict, 
                    concept, 
                    amount,
                    concept_process_result,
                    name,
                    result
                )
        if payslip.loan_installment_ids:
            for installment in payslip.loan_installment_ids:
                localdict, result = self._create_loan_line(
                    localdict,
                    installment,
                    result
                )

        obj_novelties = self.env['hr.novelties.different.concepts'].search([
            ('employee_id', '=', localdict['employee'].id),
            ('date', '>=', localdict['slip'].date_from),
            ('date', '<=', localdict['slip'].date_to)
        ])
        for concepts in obj_novelties:
            if concepts.amount != 0 and self._should_process_novelty(concepts, payslip):
                localdict, result = self._update_localdict_for_novelty(localdict, concepts, result)
        return localdict, result
    
    def _create_loan_line(self, localdict, installment, result):
        """
        Crea una línea para una cuota de préstamo
        """
        line_code = f'LOAN-{installment.loan_id.id}-{installment.sequence}'
        
        loan = installment.loan_id
        amount = -abs(installment.amount)  # Monto negativo para descuento
        
        description = f"Cuota {installment.sequence}/{len(loan.installment_ids)} -{[loan.category_id.code]} {loan.category_id.name}"
        if len(localdict['slip'].loan_installment_ids) > 1:
            description += f" ({installment.date})"
        
        # Obtener la regla salarial para préstamos
        rule = installment.loan_id.category_id.salary_rule_id#self.env.ref('hr_loan.rule_loan_payment', raise_if_not_found=False)
        if not rule:
            return localdict, result
        
        localdict[line_code] = amount
        localdict['rules'].dict[line_code] = rule
        
        rule_values = {
            'total': amount,
            'amount': amount,
            'quantity': 1,
            'base_prima': False,
            'base_cesantias': False,
            'base_vacaciones': False,
            'base_vacaciones_dinero': False
        }
        
        localdict['result_rules'].dict[line_code] = rule_values
        localdict['result_rules_co'].dict[line_code] = {
            **rule_values,
            'base_seguridad_social': False
        }
        
        localdict = self._sum_salary_rule_category(
            localdict, 
            rule.category_id,
            amount
        )
        localdict = self._sum_salary_rule(localdict, rule, amount)
        
        result[line_code] = {
            'sequence': rule.sequence,
            'code': rule.code,
            'name': description,
            'salary_rule_id': rule.id,
            'contract_id': localdict['contract'].id,
            'employee_id': localdict['employee'].id,
            'entity_id': loan.entity_id.id,
            'loan_id': loan.id,
            #'loan_installment_id': installment.id,
            'amount': amount,
            'quantity': 1.00,
            'rate': 100,
            'total': round(amount),
            'slip_id': self.id,
            'is_previous_period': False
        }
        
        return localdict, result
    
    def _should_process_novelty(self, novelty, payslip):
        """
        Determina si una novedad debe ser procesada según estructuras y condiciones
        """
        if not novelty.salary_structure_ids:
            return payslip.struct_process in ['nomina', 'contrato']
        return payslip.struct_id.id in novelty.salary_structure_ids.ids

    def _process_salary_rules(self, payslip, localdict, result):
        rules_to_process = self._get_rules_to_process()
        blacklisted_rule_ids = self.env.context.get('prevent_payslip_computation_line_ids', [])
        rule_results = {}
        overrides = {}
        if payslip.has_overrides or self.env.context.get('simulate_override'):
            if self.env.context.get('simulate_override'):
                overrides = {
                    self.env.context.get('override_rule'): {
                        'type': self.env.context.get('override_type'),
                        'value': self.env.context.get('override_value')
                    }
                }
            else:
                overrides = {
                    o.rule_id.code: {
                        'type': o.override_type,
                        'value': o.value_override
                    } for o in payslip.rule_override_ids.filtered('active')
                }
        for rule in sorted(rules_to_process, key=lambda x: x.sequence):
            if rule.id in blacklisted_rule_ids:
                continue
                
            temp_dict = localdict.copy()
            if rule._satisfy_condition(temp_dict):
                amount, qty, rate, name, log, data = rule._compute_rule_lavish(temp_dict)#monto:float, cantidad:float, tasa:float, nombre:str, log:opticonal[dict,any], data:dict
                tot_rule = 0 

                if rule.code in overrides:
                    override = overrides[rule.code]
                    if override['type'] == 'amount':
                        amount = override['value']
                    elif override['type'] == 'quantity':
                        qty = override['value']
                    elif override['type'] == 'rate':
                        rate = override['value']
                    elif override['type'] == 'total':
                        tot_rule = override['value']
                if rule.code in ("CESANTIAS","PRIMA",):
                    if data:
                            tot_rule = float(self._round1(data['data_kpi']['meta_info']['valor_prestacion']))
                if rule.code in ("INTCESANTIAS", "INTCES_YEAR"):
                    if data:
                            tot_rule = float(self._round1(data['data_kpi']['meta_info']['valor_prestacion'] * rate/100) )

                if rule.code in ("VACCONTRATO"):
                    if data:
                            tot_rule =  float(self._round1(data['monto_total']))
                if not tot_rule:
                    tot_rule = round(amount * qty * rate / 100.0)

                previous_amount = rule.code in temp_dict and temp_dict[rule.code] or 0.0
                
                temp_dict['result_rules_co'].dict[rule.code] = {
                    'total': tot_rule, 
                    'amount': tot_rule, 
                    'quantity': 1,
                    'base_seguridad_social': rule.base_seguridad_social, 
                    'base_prima': rule.base_prima,
                    'base_cesantias': rule.base_cesantias, 
                    'base_vacaciones': rule.base_vacaciones,
                    'base_vacaciones_dinero': rule.base_vacaciones_dinero
                }
                
                temp_dict = self._sum_salary_rule_category(temp_dict, rule.category_id, tot_rule - previous_amount)
                temp_dict = self._sum_salary_rule(temp_dict, rule, tot_rule,qty, rate, log=data)
                if rule.code in ('IBD'):
                    if log and 'ibc_final' in log:
                        temp_dict['ibc_full'] += log['ibc_final']
                if tot_rule != 0.0:
                    rule_results[rule.code] = self._prepare_rule_result(
                        rule, temp_dict, amount, qty, rate, name, log, payslip, data
                    )
                print(f"Acumulando ibc_final: {log} - Total: {temp_dict['ibc_full']}")
        result.update(rule_results)
        return result

    def _create_concept_line(self, localdict, concept, amount, data, description, result):
        """
        Crea una línea de concepto y actualiza el localdict
        """
        line_code = concept.input_id.code + '-PCD' + str(concept.id)

        previous_amount = concept.input_id.code in localdict and localdict[concept.input_id.code] or 0.0
        
        localdict[line_code] = amount
        localdict['rules'].dict[line_code] = concept.input_id
        
        rule = concept.input_id
        rule_values = {
            'total': amount,
            'amount': amount,
            'quantity': 1,
            'base_prima': rule.base_prima,
            'base_cesantias': rule.base_cesantias,
            'base_vacaciones': rule.base_vacaciones,
            'base_vacaciones_dinero': rule.base_vacaciones_dinero
        }
        
        localdict['result_rules'].dict[line_code] = rule_values
        localdict['result_rules_co'].dict[line_code] = {
            **rule_values,
            'base_seguridad_social': rule.base_seguridad_social
        }
        
        localdict = self._sum_salary_rule_category(
            localdict, 
            concept.input_id.category_id, 
            amount - previous_amount
        )
        localdict = self._sum_salary_rule(localdict, concept.input_id, amount, 1.0, 100.0)
        
        result[line_code] = {
            'sequence': concept.input_id.sequence,
            'code': concept.input_id.code,
            'name': description,
            'salary_rule_id': concept.input_id.id,
            'contract_id': localdict['contract'].id,
            'employee_id': localdict['employee'].id,
            'entity_id': concept.partner_id.id,
            'loan_id': concept.loan_id.id,
            'concept_id': concept.id,
            'amount': amount,
            'quantity': 1.00,
            'rate': 100,
            'log_compute':data['detail_html'],
            'total': amount,
            'slip_id': self.id,
        }
        
        return localdict, result

    def _update_localdict_for_novelty(self, localdict, concepts, result):
        previous_amount = concepts.salary_rule_id.code in localdict and localdict[concepts.salary_rule_id.code] or 0.0
        tot_rule = self._get_payslip_line_total(concepts.amount, 1, 100, concepts.salary_rule_id)
        localdict[concepts.salary_rule_id.code+'-PCD'] = tot_rule
        localdict['rules'].dict[concepts.salary_rule_id.code+'-PCD'] = concepts.salary_rule_id
        localdict = self._sum_salary_rule_category(localdict, concepts.salary_rule_id.category_id, tot_rule - previous_amount)
        localdict = self._sum_salary_rule(localdict, concepts.salary_rule_id, tot_rule, 1.0, 100.0)
        rule = concepts.salary_rule_id
        localdict['result_rules'].dict[rule.code +'-PCD'+str(concepts.id)] = {
            'total': tot_rule, 'amount': tot_rule, 'quantity': 1, 
            'base_prima':rule.base_prima, 'base_cesantias':rule.base_cesantias, 
            'base_vacaciones':rule.base_vacaciones,'base_vacaciones_dinero':rule.base_vacaciones_dinero
        }
        localdict['result_rules_co'].dict[rule.code +'-PCD'+str(concepts.id)] = {
            'total': tot_rule,
            'amount': tot_rule,
            'quantity': 1, 
            'base_seguridad_social': rule.base_seguridad_social, 
            'base_prima':rule.base_prima, 
            'base_cesantias':rule.base_cesantias, 
            'base_vacaciones':rule.base_vacaciones,
            'base_vacaciones_dinero':rule.base_vacaciones_dinero
        }

        result_item = concepts.salary_rule_id.code+'-PCD'+str(concepts.id)
        result[result_item] = {
            'sequence': concepts.salary_rule_id.sequence,
            'code': concepts.salary_rule_id.code,
            'name': concepts.description or concepts.salary_rule_id.name,
            #'note': concepts.salary_rule_id.note,
            'salary_rule_id': concepts.salary_rule_id.id,
            'contract_id': localdict['contract'].id,
            'employee_id': localdict['employee'].id,
            'entity_id': concepts.partner_id.id if concepts.partner_id else False,
            'amount': tot_rule,
            'quantity': 1.0,
            'rate': 100,
            'total': tot_rule,
            'slip_id': self.id,
        }
        return localdict, result
    
    def _prepare_rule_result(self, rule, localdict, amount, qty, rate, name, log, payslip, data) -> Dict[str, Union[float, str, int,Dict[str,str],bool]]:
        tot_rule = payslip._get_payslip_line_total(amount, qty, rate, rule)
        result = {
            'sequence': rule.sequence,
            'code': rule.code,
            'name':  name or rule.name,
            'salary_rule_id': rule.id,
            'contract_id': localdict['contract'].id,
            'employee_id': localdict['employee'].id,
            'entity_id': False,
            'amount': amount,
            'quantity': qty,
            'rate': rate,
            'total': tot_rule,
            'slip_id': payslip.id,
            'run_id': payslip.payslip_run_id.id,
        }
        
        if rule.category_id.code == 'SSOCIAL':
            for entity in localdict['employee'].social_security_entities:
                if entity.contrib_id.type_entities == 'eps' and rule.code == 'SSOCIAL001':
                    result['entity_id'] = entity.partner_id.id
                elif entity.contrib_id.type_entities == 'pension' and rule.code in ['SSOCIAL002', 'SSOCIAL003', 'SSOCIAL004']:
                    result['entity_id'] = entity.partner_id.id
                elif entity.contrib_id.type_entities == 'subsistencia' and rule.code == 'SSOCIAL003':
                    result['entity_id'] = entity.partner_id.id
                elif entity.contrib_id.type_entities == 'solidaridad' and rule.code == 'SSOCIAL004':
                    result['entity_id'] = entity.partner_id.id
        if rule.category_id.code in ("PROV"):
            result.update({
            'total': amount * qty * rate / 100 })   
        if rule.code in ("CESANTIAS","PRIMA","INTCESANTIAS", "INTCES_YEAR"):
            if data:
                result.update({
                    'total': self._round1(data['data_kpi']['meta_info']['valor_prestacion']),
                    'days_unpaid_absences': self._round1(data['data_kpi']['meta_info']['susp']),                        
                    'amount_base': self._round1(data['data_kpi']['meta_info']['amount_base'] / 360 * qty),
                    'initial_accrual_date': data['data_kpi']['meta_info']['fecha_inicio'],
                    'final_accrual_date':  data['data_kpi']['meta_info']['fecha_fin'],
                    'computation': json.dumps(data['data_kpi'], default=json_serial),
                }) 
        if rule.code in ("VACCONTRATO"):
            if data:
                result.update({
                    'total': self._round1(data['monto_total']),
                    'days_unpaid_absences': self._round1(data['data_kpi']['days_suspension']),                        
                    'amount_base': self._round1(data['amount_base']),
                    'initial_accrual_date': data['fecha_inicio'],
                    'final_accrual_date':  data['fecha_fin'],
                    'computation': json.dumps(data['data_kpi'], default=json_serial),
                }) 
        elif rule.code in ('RT_MET_01',):
            if data:
                result.update({
                    'amount_base': data[0].get('subtotal_ibr3', 0) if not data[0].get('es_proyectado', False) else data[0].get('otro_valor', 0)/2,
                    'computation': json.dumps(data, default=json_serial), 
                                                            
                }) 
                self.resulados_rt = log
        elif rule.code in ('IBD'):
            result.update({
                'amount_base': data['ctx'].ibc_full,
                'computation': json.dumps(data, default=json_serial),                                          
            }) 
            self.resulados_op = self.generate_ibd_html_report(data)
        if log:
            result['log_compute'] = log
        return result

    def _calculate_absences(self) -> Dict[str, Any]:
        self.ensure_one()
        temp_dict = {}
        for leave_day in self.leave_days_ids:
            composite_key = (leave_day.leave_id.id, leave_day.rule_id.id)
            if composite_key not in temp_dict:
                temp_dict[composite_key] = {
                    'name': leave_day.leave_id.name,
                    'total_days': 0,
                    'total_amount': 0,
                    'leave_type': leave_day.leave_id.holiday_status_id.name,
                    'date_from': leave_day.date,
                    'date_to': leave_day.date,
                    'rule_id': leave_day.rule_id,
                    'leave_id': leave_day.leave_id,
                    'entity_id': leave_day.leave_id.entity.id if leave_day.leave_id.entity else False,
                    'days_work': 0,
                    'days_holiday': 0,
                    'days_31': 0,
                    'days_holiday_31': 0,
                    'additional_novelties': [],
                }
            else:
                temp_dict[composite_key]['date_from'] = min(temp_dict[composite_key]['date_from'], leave_day.date)
                temp_dict[composite_key]['date_to'] = max(temp_dict[composite_key]['date_to'], leave_day.date)
                
            # Acumular los días y montos
            temp_dict[composite_key]['total_days'] += leave_day.days_payslip
            temp_dict[composite_key]['total_amount'] += leave_day.amount
            temp_dict[composite_key]['days_work'] += leave_day.days_work
            temp_dict[composite_key]['days_holiday'] += leave_day.days_holiday
            temp_dict[composite_key]['days_31'] += leave_day.days_31
            temp_dict[composite_key]['days_holiday_31'] += leave_day.days_holiday_31
            
            # Agregar novedad individual
            temp_dict[composite_key]['additional_novelties'].append({
                'date': leave_day.date,
                'amount': leave_day.amount,
                'days': leave_day.days_payslip,
                'days_work': leave_day.days_work,
                'days_holiday': leave_day.days_holiday,
                'days_31': leave_day.days_31,
                'days_holiday_31': leave_day.days_holiday_31,
            })
        
        absence_dict = {}
        for (leave_id, rule_id), data in temp_dict.items():
            composite_key = f"{leave_id}_{rule_id}"
            absence_dict[composite_key] = {
                'name': data['name'],
                'total_days': data['total_days'],
                'total_amount': data['total_amount'],
                'leave_type': data['leave_type'],
                'date_from': data['date_from'],
                'date_to': data['date_to'],
                'rule_id': data['rule_id'],
                'leave_id': data['leave_id'],
                'entity_id': data['entity_id'],
                'days_work': data['days_work'],
                'days_holiday': data['days_holiday'],
                'days_31': data['days_31'],
                'days_holiday_31': data['days_holiday_31'],
            }
            
            # Ordenar las novedades por fecha
            data['additional_novelties'].sort(key=lambda x: x['date'])
            absence_dict[composite_key]['additional_novelties'] = data['additional_novelties']
        return absence_dict

    def _update_localdict_for_absences(self, localdict, absence_dict):
        result = {}
        for leave_id, absence_data in absence_dict.items():
            if not absence_data['rule_id']:
                continue
            elif self.struct_process in ['prima', 'cesantias', 'intereses_cesantias']:
                continue
            concept = {
                'input_id': absence_data['rule_id'],
                'leave_id': absence_data['leave_id'],
                'partner_id': absence_data['entity_id'],
                'loan_id': False,
                'days': absence_data['total_days'],
                'days_work': absence_data['days_work'],
                'days_holiday': absence_data['days_holiday'],
                'days_31': absence_data['days_31'],
                'days_holiday_31': absence_data['days_holiday_31'],
                'leave_type': absence_data['leave_type'],
                'date_from': absence_data['date_from'],
                'date_to': absence_data['date_to'],
            }
            tot_rule = absence_data['total_amount']
            
            localdict, result = self._update_localdict_for_leave(localdict, concept, tot_rule, result)
            
        return localdict, result
    
    def _update_localdict_for_leave(self, localdict, concept, tot_rule, result):
        input_code = concept['input_id'].code
        previous_amount = localdict.get(input_code, 0.0)
        tot_rule = tot_rule * (1 if concept['input_id'].dev_or_ded == 'devengo' else -1)
        localdict[f"{input_code}-PCD{concept['leave_id']}"] = tot_rule
        localdict['rules'].dict[f"{input_code}-PCD{concept['leave_id']}"] = concept['input_id']
        rule = concept['input_id']
        days = concept['days']
        contract = localdict['contract']
        employee = localdict['employee']
        amount_per_day = tot_rule / days if days else 0
        
        leave = concept['leave_id']
        is_money_vacation = input_code == 'VACATIONS_MONEY' or (leave.holiday_status_id.is_vacation_money)
        
        vacation_type = 'money' if is_money_vacation else 'enjoy'
        localdict[f"vacation_type-PCD{concept['leave_id']}"] = vacation_type
        
        result_rule = {
            'total': round(tot_rule),
            'amount': amount_per_day,
            'quantity': days,
            'base_prima': rule.base_prima,
            'base_cesantias': rule.base_cesantias,
            'base_vacaciones': rule.base_vacaciones,
            'base_vacaciones_dinero': rule.base_vacaciones_dinero,
            'vacation_type': vacation_type
        }
        
        localdict['result_rules'].dict[f"{rule.code}-PCD{concept['leave_id']}"] = result_rule
        result_rule_co = result_rule.copy()
        result_rule_co['base_seguridad_social'] = rule.base_seguridad_social
        localdict['result_rules_co'].dict[f"{rule.code}-PCD{concept['leave_id']}"] = result_rule_co
        localdict = self._sum_salary_rule_category(localdict, rule.category_id, tot_rule - previous_amount)
        localdict = self._sum_salary_rule(localdict, rule, tot_rule, days, 100, {f"{rule.code}-PCD{concept['leave_id']}": concept['leave_id']})
        result_item = f"{input_code}-PCD{concept['leave_id']}"
        
        result[result_item] = {
            'sequence': rule.sequence,
            'code': rule.code,
            'name': rule.name,
            'salary_rule_id': rule.id,
            'contract_id': localdict['contract'].id,
            'employee_id': localdict['employee'].id,
            'entity_id': concept['partner_id'],
            'loan_id': concept['loan_id'],
            'amount': amount_per_day,
            'quantity': days,
            'rate': 100,
            'total': round(tot_rule),
            'slip_id': self.id,
            'leave_id': concept['leave_id'].id,
            'initial_accrual_date': concept['date_from'],
            'final_accrual_date': concept['date_to'],
            'business_units': concept['days_work'],
            'holiday_units': concept['days_holiday'],
            'business_31_units': concept['days_31'],
            'holiday_31_units': concept['days_holiday_31'],
        }
        
        if leave.holiday_status_id.is_vacation or leave.holiday_status_id.is_vacation_money:
            Vac = self.env['hr.vacation']
            
            if '_vacation_accrual_dates' not in localdict:
                localdict['_vacation_accrual_dates'] = {}
            
            employee_id = employee.id
            
            if employee_id in localdict['_vacation_accrual_dates']:
                start = localdict['_vacation_accrual_dates'][employee_id] + timedelta(days=1)
            else:
                last = Vac.search(
                    [('employee_id', '=', employee.id)],
                    order='final_accrual_date desc', limit=1
                )
                if last:
                    start = last.final_accrual_date
                    if start < contract.date_start:
                        start = contract.date_start
                else:
                    start = contract.date_start
            
            domain = [
                ('state', '=', 'validate'),
                ('employee_id', '=', employee.id),
                ('unpaid_absences', '=', True),
                ('date_from', '>=', start),
                ('date_to', '<=', self.date_to),
            ]
            dias_aus = sum(l.number_of_days_in_payslip for l in self.env['hr.leave'].search(domain))
            dias_aus += sum(h.days for h in self.env['hr.absence.history'].search([
                ('employee_id', '=', employee.id),
                ('leave_type_id.unpaid_absences', '=', True),
                ('star_date', '>=', start),
                ('end_date', '<=', self.date_to),
            ]))

            dias_hab = concept['days_work']
            dias_fest = concept['days_holiday']
            dias_31_hab = concept['days_31']
            dias_31_fest = concept['days_holiday_31']

            dias_equiv = ((Decimal(dias_hab) + Decimal(dias_31_hab)) * Decimal(365)) / Decimal(15)
            dias_equiv = int(dias_equiv.quantize(0, rounding=ROUND_HALF_UP))
            if not start:
                start = contract.date_start
            end = start + timedelta(days=(dias_equiv + dias_aus) +1 )
            
            localdict['_vacation_accrual_dates'][employee_id] = end

            disp = self.get_holiday_book(contract, start)['days_left']
            dias_rest = max(disp - dias_hab, 0)

            log_lines = [
                '<div class="vac-log" style="font-family:Arial,sans-serif;font-size:12px;">',
                f'<p><strong>Tipo de vacaciones:</strong> {"En Dinero" if is_money_vacation else "Disfrute"}</p>',
                f'<p><strong>Inicio causación:</strong> {start.strftime("%d/%m/%Y")}</p>',
                f'<p><strong>Fin causación:</strong> {end.strftime("%d/%m/%Y")}</p>',
                f'<p><strong>Días hábiles:</strong> {dias_hab}</p>',
                f'<p><strong>Días festivos:</strong> {dias_fest}</p>',
                f'<p><strong>Días "31" hábiles:</strong> {dias_31_hab}</p>',
                f'<p><strong>Días "31" festivos:</strong> {dias_31_fest}</p>',
                f'<p><strong>Equivalente calendario:</strong> {dias_equiv + dias_aus}</p>',
                f'<p><strong>Ausencias no pagadas:</strong> {dias_aus}</p>',
                f'<p><strong>Disponibles antes:</strong> {disp}</p>',
                f'<p><strong>Restantes:</strong> {dias_rest}</p>',
                '</div>',
            ]

            vacation_info = {
                'start_date': start,
                'end_date': end,
                'business_days': dias_hab,
                'holiday_days': dias_fest,
                'equivalent_days': dias_equiv,
                'unpaid_absences': dias_aus,
                'available_days': disp,
                'remaining_days': dias_rest,
                'base_value': amount_per_day * 30  # Base mensual
            }
            localdict[f"vacation_info-PCD{concept['leave_id']}"] = vacation_info

            vacation_values = {
                'amount_base': amount_per_day * 30,
                'object_type': 'vacation',
                'vacation_leave_id': leave.id,
                'vacation_departure_date': concept['date_from'],
                'vacation_return_date': concept['date_to'],
                'initial_accrual_date': start,
                'final_accrual_date': end,
                'business_units': dias_hab,
                'holiday_units': dias_fest,
                'business_31_units': dias_31_hab,
                'holiday_31_units': dias_31_fest,
                'days_count': days,
                'log_compute': ''.join(log_lines),
            }
            result[result_item].update(vacation_values)

        return localdict, result
        
    def action_update_vacation_data(self):
        """
        Actualiza los datos de vacaciones de una nómina ya confirmada,
        diferenciando entre vacaciones disfrutadas y vacaciones en dinero.
        """
        self.ensure_one()
        
        if self.state not in ('done', 'paid'):
            raise UserError(_("Solo se pueden actualizar datos de vacaciones en nóminas confirmadas."))
        
        vacation_lines = self.line_ids.filtered(lambda line: 
            line.code in ['VACATIONS_MONEY', 'VACDISFRUTADAS'] or 
            (line.leave_id and (line.leave_id.holiday_status_id.is_vacation or 
                            line.leave_id.holiday_status_id.is_vacation_money))
        )
        
        if not vacation_lines:
            raise UserError(_("No se encontraron líneas de vacaciones para actualizar."))
        
        leave_periods = [(line.leave_id.date_from, line.leave_id.date_to, line.leave_id.name) 
                        for line in vacation_lines if line.leave_id]
        leave_periods.sort()  
        
        for i in range(1, len(leave_periods)):
            if leave_periods[i-1][1] >= leave_periods[i][0]:
                raise UserError(_(
                    "Se detectó un solapamiento entre períodos de vacaciones: %s (%s - %s) y %s (%s - %s). "
                    "Por favor, corrija las fechas antes de actualizar."
                ) % (
                    leave_periods[i-1][2], leave_periods[i-1][0].strftime('%d/%m/%Y'), leave_periods[i-1][1].strftime('%d/%m/%Y'),
                    leave_periods[i][2], leave_periods[i][0].strftime('%d/%m/%Y'), leave_periods[i][1].strftime('%d/%m/%Y')
                ))
        
        last_accrual_end = {}
        
        vacation_lines_sorted = sorted(
            [line for line in vacation_lines if line.leave_id], 
            key=lambda line: line.leave_id.date_from
        )
        
        for line in vacation_lines_sorted:
            employee = self.employee_id
            contract = self.contract_id
            leave = line.leave_id
            
            is_money_vacation = line.code == 'VACATIONS_MONEY' or (leave.holiday_status_id.is_vacation_money if leave else False)
            
            concept = {
                'leave_id': leave,
                'date_from': leave.date_from,
                'date_to': leave.date_to,
                'days_work': line.business_units,
                'days_holiday': line.holiday_units,
                'days_31': line.business_31_units,
                'days_holiday_31': line.holiday_31_units,
            }
            
            Vac = self.env['hr.vacation']
            
            if employee.id in last_accrual_end:
                start = last_accrual_end[employee.id] + timedelta(days=1)
            else:
                last_vacation = Vac.search(
                    [
                        ('employee_id', '=', employee.id),
                        ('payslip', '!=', self.id),
                    ],
                    order='final_accrual_date desc', limit=1
                )
                
                if last_vacation:
                    start = last_vacation.final_accrual_date + timedelta(days=1)
                    if start < contract.date_start:
                        start = contract.date_start
                else:
                    start = contract.date_start
            
            domain = [
                ('state', '=', 'validate'),
                ('employee_id', '=', employee.id),
                ('unpaid_absences', '=', True),
                ('date_from', '>=', start),
                ('date_to', '<=', self.date_to),
            ]
            
            dias_aus = sum(l.number_of_days for l in self.env['hr.leave'].search(domain))
            dias_aus += sum(h.days for h in self.env['hr.absence.history'].search([
                ('employee_id', '=', employee.id),
                ('leave_type_id.unpaid_absences', '=', True),
                ('star_date', '>=', start),
                ('end_date', '<=', self.date_to),
            ]))
            
            dias_hab = concept['days_work']
            dias_fest = concept['days_holiday']
            dias_31_hab = concept['days_31']
            dias_31_fest = concept['days_holiday_31']
            
            from decimal import Decimal, ROUND_HALF_UP
            dias_equiv = ((Decimal(dias_hab) + Decimal(dias_31_hab)) * Decimal(365)) / Decimal(15)
            dias_equiv = int(dias_equiv.quantize(0, rounding=ROUND_HALF_UP))
            
            end = start + timedelta(days=(dias_equiv + dias_aus) - 1)
            
            last_accrual_end[employee.id] = end
            
            disp = self.get_holiday_book(contract, start)['days_left']
            dias_rest = max(disp - dias_hab, 0)
            
            amount_per_day = line.amount if line.amount else 0
            total_amount = line.total if line.total else 0
            
            log_lines = [
                '<div class="vac-log" style="font-family:Arial,sans-serif;font-size:12px;">',
                f'<p><strong>Tipo de vacaciones:</strong> {"En Dinero" if is_money_vacation else "Disfrute"}</p>',
                f'<p><strong>Inicio causación:</strong> {start.strftime("%d/%m/%Y")}</p>',
                f'<p><strong>Fin causación:</strong> {end.strftime("%d/%m/%Y")}</p>',
                f'<p><strong>Fechas vacaciones:</strong> {concept["date_from"].strftime("%d/%m/%Y")} - {concept["date_to"].strftime("%d/%m/%Y")}</p>',
                f'<p><strong>Días hábiles:</strong> {dias_hab}</p>',
                f'<p><strong>Días festivos:</strong> {dias_fest}</p>',
                f'<p><strong>Días "31" hábiles:</strong> {dias_31_hab}</p>',
                f'<p><strong>Días "31" festivos:</strong> {dias_31_fest}</p>',
                f'<p><strong>Equivalente calendario:</strong> {dias_equiv} días</p>',
                f'<p style="color:#e74c3c;"><strong>Ausencias no pagadas:</strong> {dias_aus} días</p>',
                f'<p><strong>Disponibles antes:</strong> {disp} días</p>',
                f'<p><strong>Restantes:</strong> {dias_rest} días</p>',
                f'<p><strong>Valor por día:</strong> ${amount_per_day:,.2f}</p>',
                f'<p><strong>Valor total:</strong> ${total_amount:,.2f}</p>',
                '</div>',
            ]
            
            line.write({
                'initial_accrual_date': start,
                'final_accrual_date': end,
                'vacation_departure_date': concept['date_from'],
                'vacation_return_date': concept['date_to'],
                'log_compute': ''.join(log_lines),
            })
            
            vacation_values = {
                'employee_id': employee.id,
                'employee_identification': employee.identification_id,
                'leave_id': leave.id,
                'payslip': self.id,
                'initial_accrual_date': start,
                'final_accrual_date': end,
                'departure_date': concept['date_from'],
                'return_date': concept['date_to'],
                'business_units': dias_hab,
                'holiday_units': dias_fest,
                'days_returned': 0,
                'contract_id': contract.id,
                'ibc_pila': self.env['hr.payslip.line'].search([
                    ('slip_id', '=', self.id),
                    ('code', '=', 'IBD')
                ], limit=1).total or 0,
            }
            
            if is_money_vacation:
                vacation_values.update({
                    'base_value_money': amount_per_day * 30,  # Base mensual
                    'units_of_money': dias_hab + dias_fest,   # Total días
                    'money_value': total_amount,              # Valor pagado
                    'total': total_amount,
                    'description': 'Vacaciones en Dinero'
                })
            else:
                vacation_values.update({
                    'base_value': amount_per_day * 30,       # Base mensual
                    'value_business_days': amount_per_day * dias_hab,
                    'holiday_value': amount_per_day * dias_fest,
                    'total': total_amount,
                    'description': 'Vacaciones Disfrutadas'
                })
            
            vacation_records = Vac.search([
                ('employee_id', '=', employee.id),
                ('payslip', '=', self.id)
            ])
            
            if vacation_records:
                for vac_record in vacation_records:
                    vac_record.write(vacation_values)
            else:
                Vac.create(vacation_values)
        
        self.message_post(
            body=_("Se actualizaron los datos de %d períodos de vacaciones (%d disfrutadas, %d en dinero).") % (
                len(vacation_lines_sorted),
                len([l for l in vacation_lines_sorted if l.code == 'VACDISFRUTADAS' or 
                    (l.leave_id and l.leave_id.holiday_status_id.is_vacation and not l.leave_id.holiday_status_id.is_vacation_money)]),
                len([l for l in vacation_lines_sorted if l.code == 'VACATIONS_MONEY' or 
                    (l.leave_id and l.leave_id.holiday_status_id.is_vacation_money)])
            ),
            subject=_("Actualización de Datos de Vacaciones")
        )
        
        # Mensaje de éxito
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Éxito'),
                'message': _('Datos de vacaciones actualizados correctamente.'),
                'sticky': False,
            }
        }
        
    def get_holiday_book(self, contract, date_from=False, date_ref=False):
        """
        Calcula los días de vacaciones acumulados y disponibles para un empleado
        
        Args:
            contract: Contrato del empleado
            date_ref: Fecha de referencia para el cálculo (por defecto, fecha actual)
            
        Returns:
            dict: Diccionario con información de días trabajados, disponibles, disfrutados, etc.
        """
        date_ref = date_ref or contract.date_ref_holiday_book or self.date_to
        prestaciones_service = self.env['prestaciones.sociales.service']
        worked_days = prestaciones_service.days360(date_from, date_ref)
        
        days_enjoyed, days_paid, days_suspension = 0, 0, 0
        
        for holiday_book in contract.vacaciones_ids:
            days_enjoyed += holiday_book.business_units
        
        leave_lines = self.env["hr.leave.line"].search([
            ("leave_id.employee_id", "=", contract.employee_id.id),
            ("leave_id.state", "=", "validate"),
            ("leave_id.unpaid_absences", "=", True),
            ("date", ">=", date_from),
            ("date", "<=", date_ref),
        ])
        
        days_suspension = sum(line.days_payslip for line in leave_lines)
        
        worked_days_adjusted = worked_days - days_suspension
        
        days_left = (worked_days_adjusted * 15 / DAYS_YEAR) - days_enjoyed
        return {
            'worked_days': round_1_decimal(worked_days),
            'worked_days_adjusted': round_1_decimal(worked_days_adjusted),
            'days_left': round_1_decimal(days_left),
            'days_enjoyed': round_1_decimal(days_enjoyed),
            'days_paid': round_1_decimal(days_paid),
            'days_suspension': round_1_decimal(days_suspension),
        }

    def _get_rules_to_process(self):
        self.ensure_one()
        process = self.struct_id.process
        def get_specific_rules(process):
            return self.env['hr.salary.rule'].search([
                ('struct_id.process', '=', process),
                ('active', '=', True)
            ])
            
        common_rules = self.env['hr.salary.rule'].search([
            ('code', 'in', ['TOTALDEV', 'TOTALDED', 'NET']),
            ('active', '=', True)
        ])
        if process == 'nomina':
            rules = get_specific_rules('nomina')
            if self.pay_primas_in_payroll:
                rules |= get_specific_rules('prima')
            if self.pay_cesantias_in_payroll:
                rules |= self.env['hr.salary.rule'].search([('code','=','INTCES_YEAR')])
            if self.pay_vacations_in_payroll:
                rules |= self.env['hr.salary.rule'].search([('code','in',('VACDISFRUTADAS','VAC001','VAC002'))])
        elif process == 'vacaciones':
            rules = self.env['hr.salary.rule'].search([('code', 'in', ['VACDISFRUTADAS','VACATIONS_MONEY','SSOCIAL001','SSOCIAL002','VAC001','VAC002','IBD','IBC_R', 'TOTALDEV', 'TOTALDED', 'NET'])])
        elif process in ['prima', 'cesantias', 'intereses_cesantias']:
            rules = get_specific_rules(process)
        elif process == 'contrato':
            rules = get_specific_rules('nomina') | get_specific_rules('prima') | \
                    get_specific_rules('cesantias') | get_specific_rules('intereses_cesantias') | \
                    get_specific_rules('vacaciones') 
            if self.have_compensation:
                rules |= self.struct_id.rule_ids            
            if not self.settle_payroll_concepts:
                rules = rules.filtered(lambda r: r.struct_id.process != 'nomina')
            if self.no_days_worked:
                rules = rules.filtered(lambda r: r.category_id.code not in ('BASIC','AUX'))
            if not self.novelties_payroll_concepts:
                rules = rules.filtered(lambda r: r.type_concepts != 'novedad')
        else: 
            rules = self.struct_id.rule_ids
        return rules | common_rules

    def _no_round(self, amount):
        return amount

    def _round1(self, amount):
        return round(amount)

    def _round100(self, amount):
        return int(math.ceil(amount / 100.0)) * 100

    def _round1000(self, amount):
        return round(amount, -3)

    def _round2d(self, amount):
        return round(amount, 2)

    @api.depends('line_ids')
    def _compute_concepts_category(self):
        category_mapping = {
            'EARNINGS': ['BASIC', 'AUX', 'AUS', 'ALW', 'ACCIDENTE_TRABAJO', 'DEV_NO_SALARIAL', 'DEV_SALARIAL', 'TOTALDEV', 'HEYREC', 'COMISIONES', 'INCAPACIDAD', 'LICENCIA_MATERNIDAD', 'LICENCIA_NO_REMUNERADA', 'LICENCIA_REMUNERADA', 'PRESTACIONES_SOCIALES', 'PRIMA', 'VACACIONES'],
            'DEDUCTIONS': ['DED', 'DEDUCCIONES', 'TOTALDED', 'SANCIONES', 'DESCUENTO_AFC', 'SSOCIAL'],
            'PROVISIONS': ['PROV'],
            'OUTCOME': ['NET']}
        categorized_lines = {
            'EARNINGS': [],
            'DEDUCTIONS': [],
            'PROVISIONS': [],
            'BASES': [],
            'OUTCOME': []}
        for payslip_line in self.line_ids:
            category_found = False
            for category, codes in category_mapping.items():
                if payslip_line.category_id.code in codes or payslip_line.category_id.parent_id.code in codes:
                    categorized_lines[category].append(payslip_line.id)
                    category_found = True
                    break
            if not category_found:
                categorized_lines['BASES'].append(payslip_line.id)
        for category, line_ids in categorized_lines.items():
            setattr(self, f'{category.lower()}_ids', self.env['hr.payslip.line'].browse(line_ids))
    
    def _get_payslip_line_total(self, amount, quantity, rate, rule):
        self.ensure_one()
        total = amount * quantity * rate / 100.0
        return round(total) 

    def name_get(self):
        result = []
        for record in self:
            if record.payslip_run_id:
                result.append((record.id, "{} - {}".format(record.payslip_run_id.name,record.employee_id.name)))
            else:
                result.append((record.id, "{} - {} - {}".format(record.struct_id.name,record.employee_id.name,str(record.date_from))))
        return result

    def get_hr_payslip_reports_template(self):
        type_report = self.struct_process if self.struct_process != 'otro' else 'nomina'
        obj = self.env['hr.payslip.reports.template'].search([('company_id','=',self.employee_id.company_id.id),('type_report','=',type_report)])
        if len(obj) == 0:
            raise ValidationError(_('No tiene configurada plantilla de liquidacion. Por favor verifique!'))
        return obj

    def get_pay_vacations_in_payroll(self):
        return bool(self.env['ir.config_parameter'].sudo().get_param('lavish_hr_payroll.pay_vacations_in_payroll')) or False

    def get_increase(self):
        return True

    @api.onchange('employee_id', 'struct_id', 'contract_id', 'date_from', 'date_to')
    def _onchange_employee(self):
        if (not self.employee_id) or (not self.date_from) or (not self.date_to):
            return
        employee = self.employee_id
        date_from = self.date_from
        date_to = self.date_to
        self.company_id = employee.company_id
        if not self.contract_id or self.employee_id != self.contract_id.employee_id:  # Add a default contract if not already defined
            contracts = employee._get_contracts(date_from, date_to)
            if not contracts or not contracts[0].structure_type_id.default_struct_id:
                self.contract_id = False
                self.struct_id = False
                return
            self.contract_id = contracts[0]
            self.struct_id = contracts[0].structure_type_id.default_struct_id
        days_diff = (date_to - date_from).days + 1
        period_type = 'monthly' if days_diff > 15 else 'bi-monthly'
        period = self.env['hr.period'].get_period(
            date_from, 
            date_to,
            period_type,
            self.company_id.id
        )
        if period:
            self.period_id = period.id
        else:
            self.assign_periods_to_draft_payslips()
            self.period_id = self.env['hr.period'].get_period(date_from, date_to, period_type, self.company_id.id).id
        payslip_name = self.struct_id.payslip_name or _('Recibo de Salario')
        
        mes = self.date_from.month
        month_name = self.env['hr.birthday.list'].get_name_month(mes)
        
        date_name = month_name + ' ' + str(self.date_from.year)
        self.name = '%s - %s - %s' % (payslip_name, self.employee_id.name or '', date_name)
        self.analytic_account_id = self.contract_id.analytic_account_id
        
        if date_to > date_utils.end_of(fields.Date.today(), 'month'):
            self.warning_message = _("This payslip can be erroneous! Work entries may not be generated for the period from %s to %s." %
                (date_utils.add(date_utils.end_of(fields.Date.today(), 'month'), days=1), date_to))
        else:
            self.warning_message = False

    def compute_sheet(self):
        for payslip in self.filtered(lambda slip: slip.state not in ['cancel', 'done','paid']):
            payslip.compute_slip()

    def action_payslip_draft(self):
        for payslip in self:
            payslip.payslip_day_ids.unlink()
            for line in payslip.input_line_ids:
                if line.loan_line_id:
                    line.loan_line_id.paid = False
                    line.loan_line_id.payslip_id = False
                    line.loan_line_id.loan_id._compute_loan_amount()
            payslip.leave_ids.leave_id.line_ids.filtered(lambda l: l.date <= payslip.date_to).write({'payslip_id': False})
        return self.write({'state': 'draft'})

    def restart_payroll(self):
        for payslip in self:
            for line in payslip.input_line_ids:
                if line.loan_line_id:
                    line.loan_line_id.paid = False
                    line.loan_line_id.payslip_id = False
                    line.loan_line_id.loan_id._compute_loan_amount()
            payslip.leave_ids.leave_id.line_ids.filtered(lambda l: l.date <= payslip.date_to).write({'payslip_id': False})
            payslip.mapped('move_id').unlink()
            obj_payslip_line = self.env['hr.payslip.line'].search(
                [('slip_id', '=', payslip.id), ('loan_id', '!=', False)])
            for payslip_line in obj_payslip_line:
                obj_loan_line = self.env['hr.loan.installment'].search(
                    [('employee_id', '=', payslip_line.employee_id.id),
                     ('payslip_id', '>=', payslip.id)])
                if payslip.struct_id.process == 'contrato' and payslip_line.loan_id.final_settlement_contract == True:
                    obj_loan_line.unlink()
                else:
                    obj_loan_line.write({
                        'paid': False,
                        'payslip_id': False
                    })
                obj_loan = self.env['hr.loan'].search(
                    [('employee_id', '=', payslip_line.employee_id.id), ('id', '=', payslip_line.loan_id.id)])
                #if obj_loan.balance_amount > 0:
                #    self.env['hr.contract.concepts'].search([('loan_id', '=', payslip_line.loan_id.id)]).write(
                #        {'state': 'done'})
            payslip.line_ids.unlink()
            payslip.not_line_ids.unlink()
            #Eliminar historicos            
            self.env['hr.vacation'].search([('payslip', '=', payslip.id)]).unlink()
            self.env['hr.history.prima'].search([('payslip', '=', payslip.id)]).unlink()
            self.env['hr.history.cesantias'].search([('payslip', '=', payslip.id)]).unlink()
            #Reversar Liquidación            
            payslip.action_payslip_draft()            

    #--------------------------------------------------LIQUIDACIÓN DE LA NÓMINA PERIÓDICA---------------------------------------------------------#

    @api.depends('line_ids.total')
    def _compute_basic_net(self):
        line_values = (self._origin)._get_line_values(['BASIC', 'BASIC002', 'BASIC003', 'GROSS',  'TOTALDEV', 'NET'])
        for payslip in self:
            payslip.basic_wage = line_values['BASIC'][payslip._origin.id]['total'] + line_values['BASIC002'][payslip._origin.id]['total'] + line_values['BASIC003'][payslip._origin.id]['total']
            #payslip.gross_wage = line_values['GROSS'][payslip._origin.id]['total'] + line_values['TOTALDEV'][payslip._origin.id]['total']
            payslip.net_wage = line_values['NET'][payslip._origin.id]['total']

    def _get_history_key_fields(self, model_name):
        """
        Define campos clave para cada modelo de historial
        """
        key_fields = {
            'hr.vacation': ['employee_id', 'contract_id', 'initial_accrual_date', 'final_accrual_date', 'leave_id'],
            'hr.history.cesantias': ['employee_id', 'contract_id', 'initial_accrual_date', 'final_accrual_date'],
            'hr.history.prima': ['employee_id', 'contract_id', 'initial_accrual_date', 'final_accrual_date'],
        }
        return key_fields.get(model_name, [])
    
    def _create_or_update_history(self, model_name, values):
        """
        Crea o actualiza cualquier historial basado en campos clave
        """
        Model = self.env[model_name]
        key_fields = self._get_history_key_fields(model_name)
        
        domain = [(field, '=', values.get(field)) for field in key_fields if values.get(field) is not False]
        
        if domain:
            existing = Model.search(domain, limit=1)
            if existing:
                existing.write(values)
                return existing
        
        return Model.create(values)
    
    def _get_vacation_values(self, record, line):
        """
        Obtiene valores de vacaciones según el código de línea
        """
        base_values = {
            'employee_id': record.employee_id.id,
            'contract_id': record.contract_id.id,
            'initial_accrual_date': line.initial_accrual_date,
            'final_accrual_date': line.final_accrual_date,
            'payslip': record.id,
        }
        
        vacation_configs = {
            'VACDISFRUTADAS': {
                'departure_date': line.vacation_departure_date or record.date_from,
                'return_date': line.vacation_return_date or record.date_to,
                'business_units': line.business_units + line.business_31_units,
                'value_business_days': line.business_units * line.amount,
                'holiday_units': line.holiday_units + line.holiday_31_units,
                'holiday_value': line.holiday_units * line.amount,
                'base_value': line.amount_base,
                'total': (line.business_units * line.amount) + (line.holiday_units * line.amount),
                'leave_id': line.vacation_leave_id.id if line.vacation_leave_id else False
            },
            'VACREMUNERADAS': {
                'departure_date': record.date_from,
                'return_date': record.date_to,
                'units_of_money': line.quantity,
                'money_value': line.total,
                'base_value_money': line.amount_base,
                'total': line.total,
            },
            'VACATIONS_MONEY': {
                'departure_date': record.date_from,
                'return_date': record.date_to,
                'units_of_money': line.quantity,
                'business_units': line.quantity,
                'money_value': line.total,
                'base_value_money': line.amount_base,
                'total': line.total,
                'leave_id': line.vacation_leave_id.id if line.vacation_leave_id else False
            },
            'VACCONTRATO': {
                'departure_date': record.date_liquidacion,
                'return_date': record.date_liquidacion,
                'units_of_money': (line.quantity * 15) / 360,
                'money_value': line.total,
                'base_value_money': line.amount_base,
                'total': line.total,
            }
        }
        
        if line.code in vacation_configs:
            base_values.update(vacation_configs[line.code])
            return base_values
        
        return None
    
    def _get_severance_values(self, record, line_cesantias=None, line_interes=None):
        """
        Obtiene valores consolidados de cesantías e intereses
        """
        values = {}
        
        if record.struct_id.process == 'contrato':
            date_from = record.date_cesantias
            date_to = record.date_liquidacion
        else:
            date_from = record.date_cesantias
            date_to = record.date_to
        
        if line_cesantias and not line_cesantias.is_history_reverse:
            values.update({
                'employee_id': record.employee_id.id,
                'contract_id': record.contract_id.id,
                'type_history': 'cesantias',
                'initial_accrual_date': date_from,
                'final_accrual_date': date_to,
                'settlement_date': date_to,
                'time': line_cesantias.quantity,
                'base_value': line_cesantias.amount_base,
                'severance_value': line_cesantias.total,
                'payslip': record.id
            })
        
        if line_interes and not line_interes.is_history_reverse:
            if record.struct_id.process in ('cesantias', 'intereses_cesantias'):
                values.update({
                    'type_history': 'intcesantias',
                    'severance_interest_value': line_interes.total,
                })
            else:
                values.update({'severance_interest_value': line_interes.total})
        
        return values
    
    def _process_history_lines(self, record):
        """
        Procesa todas las líneas de historial en un solo método
        """
        process_type = record.struct_id.process
        lines_by_code = {line.code: line for line in record.line_ids}
        
        vacation_codes = ['VACDISFRUTADAS', 'VACREMUNERADAS', 'VACATIONS_MONEY', 'VACCONTRATO']
        for code in vacation_codes:
            line = lines_by_code.get(code)
            if line and line.initial_accrual_date:
                values = self._get_vacation_values(record, line)
                if values:
                    if record.pay_vacations_in_payroll and code != 'VACCONTRATO':
                        self._create_or_update_history('hr.vacation', values)
                    else:
                        self.env['hr.vacation'].create(values)
        
        if process_type in ('cesantias', 'intereses_cesantias', 'contrato', 'nomina'):
            ces_line = lines_by_code.get('CESANTIAS')
            int_line = lines_by_code.get('INTCESANTIAS')
            
            if ces_line or int_line:
                values = self._get_severance_values(record, ces_line, int_line)
                if values:
                    self._create_or_update_history('hr.history.cesantias', values)
        
        if process_type in ('prima', 'contrato', 'nomina'):
            prima_line = lines_by_code.get('PRIMA')
            if prima_line:
                if process_type == 'prima':
                    date_from, date_to, settlement_date = record.date_prima, record.date_to, record.date_liquidacion
                else:
                    date_from, date_to, settlement_date = record.date_prima, record.date_to, record.date_liquidacion
                
                values = {
                    'employee_id': record.employee_id.id,
                    'contract_id': record.contract_id.id,
                    'initial_accrual_date': date_from,
                    'final_accrual_date': date_to,
                    'settlement_date': settlement_date,
                    'time': prima_line.quantity,
                    'base_value': prima_line.amount_base,
                    'bonus_value': prima_line.total,
                    'payslip': record.id
                }
                self._create_or_update_history('hr.history.prima', values)
    
    def _process_loans_and_reverse_payments(self, record):
        """
        Procesa préstamos y pagos inversos en un solo método
        """
        for line in record.input_line_ids.filtered(lambda l: l.loan_line_id):
            line.loan_line_id.write({'paid': True, 'payslip_id': record.id})
            line.loan_line_id.loan_id._compute_loan_amount()
        
        for line in record.line_ids.filtered(lambda l: l.loan_id):
            installments = self.env['hr.loan.installment'].search([
                ('employee_id', '=', line.employee_id.id),
                ('date', '>=', record.date_from),
                ('date', '<=', record.date_to)
            ])
            installments.write({'paid': True, 'payslip_id': record.id})
            
            #if line.loan_id.balance_amount <= 0:
            #    self.env['hr.contract.concepts'].search([
            #        ('loan_id', '=', line.loan_id.id)
            #    ]).write({'state': 'cancel'})
        
        for payment in record.severance_payments_reverse.filtered(lambda p: p.payslip):
            lines_to_update = {}
            for line in payment.payslip.line_ids:
                if line.code in ('CESANTIAS', 'INTCESANTIAS'):
                    lines_to_update[line.code] = line.total
                    line.write({'amount': 0})

            observation = payment.payslip.observation or ''
            new_obs = f"El valor se trasladó a la liquidación {record.number} de {record.struct_id.name}"
            payment.payslip.write({
                'observation': f"{observation}\n{new_obs}" if observation else new_obs
            })
    
    def action_payslip_done(self):
        """
        Versión ultra optimizada del método de confirmación de nómina
        """
        if any(slip.state == 'cancel' for slip in self):
            raise ValidationError(_("You can't validate a cancelled payslip."))
        
        self.write({'state': 'done'})
        self.mapped('payslip_run_id').action_close()
        self._action_create_account_move()
        
        for record in self:
            if record.number == '/':
                record._set_next_sequence()
            
            self._process_history_lines(record)
            self._process_loans_and_reverse_payments(record)
            if record.struct_id.process == 'contrato':
                record.contract_id.write({
                    'retirement_date': record.date_liquidacion,
                    'state': 'close'
                })

    
    def check_payslips_without_period(self) -> List[object]:
        payslips_without_period = self.env['hr.payslip'].search([
            ('state', 'in', ['verify', 'done', 'paid']),
            ('period_id', '=', False),
        ])
        
        if payslips_without_period:
            message = f"Se encontraron {len(payslips_without_period)} nóminas en estados avanzados sin período asignado."
            
            if len(payslips_without_period) <= 10:
                slip_details = []
                for slip in payslips_without_period:
                    details = f"- {slip.name} ({slip.employee_id.name}), Estado: {slip.state}, Fechas: {slip.date_from} - {slip.date_to}"
                    slip_details.append(details)
                
                message += "\n\nDetalles:\n" + "\n".join(slip_details)
            
            
            admin_user = self.env.ref('base.user_admin')
            model_id = self.env['ir.model'].search([('model', '=', 'hr.payslip')], limit=1).id
            
            self.env['mail.activity'].create({
                'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
                'note': message,
                'user_id': admin_user.id,
                'res_model_id': model_id,
                'res_id': payslips_without_period[0].id if payslips_without_period else False,
                'summary': "Nóminas sin período asignado",
            })
        
        return payslips_without_period

    def assign_periods_to_draft_payslips(self) -> int:
        draft_slips = self.env['hr.payslip'].search([
            ('period_id', '=', False),
        ])
        
        if not draft_slips:
            return 0
        
        years_to_check = set(slip.date_from.year for slip in draft_slips)
        
        for year in years_to_check:
            for period_type in ['monthly', 'bi-monthly']:
                existing_periods = self.env['hr.period'].search([
                    ('year', '=', year),
                    ('type_period', '=', period_type),
                    ('company_id', '=', self.env.company.id)
                ], limit=1)
                
                if not existing_periods:
                    self.env.cr.commit()
                    self.env['hr.period'].create_periods_for_year(
                        year, schedule_pays=[period_type], company_id=self.env.company.id
                    )
                    self.env.cr.commit()
        
        updated_count = 0
        batch_size = 100
        period_obj = self.env['hr.period']
        for i in range(0, len(draft_slips), batch_size):
            batch = draft_slips[i:i+batch_size]
            
            for slip in batch:
                days_diff = (slip.date_to - slip.date_from).days + 1
                period_type = 'monthly' if days_diff > 15 else 'bi-monthly'
                
                period = period_obj.get_period(
                slip.date_from, 
                slip.date_to, 
                period_type,
                slip.company_id.id)
            
                if period:
                    slip.write({"period_id": period.id})
                    updated_count += 1
            
            self.env.cr.commit()
        
        return updated_count

    def _get_entry_types(self) -> Dict[str, object]:
        """
        Obtiene tipos de entrada de trabajo necesarios para el cálculo.
        Busca y carga los tipos de entrada de trabajo utilizados en el
        cálculo de días trabajados y valida que todos existan en el sistema.
        
        Returns:
            dict: Diccionario con los tipos de entrada encontrados
            
        Raises:
            UserError: Si algún tipo de entrada requerido no existe
        """
        types = {}
        missing_types = []
        for code, name in [
            ('WORK131', 'days31'), ('OUT', 'outdays'), ('WORK100', 'wdays'),
            ('WORK_D', 'wdayst'), ('PREV_PAYS', 'prevdays')
        ]:
            entry_type = self.env['hr.work.entry.type'].search([("code", "=", code)], limit=1)
            if not entry_type:
                missing_types.append(code)
            else:
                types[name] = entry_type
        
        if missing_types:
            raise UserError(_(f"Faltan tipos de entrada: {', '.join(missing_types)}"))
            
        return types
    
    def _validate_leave_types(self) -> bool:
        """
        Valida que los tipos de ausencia estén correctamente configurados.
        
        Esta función verifica que los tipos de ausencia utilizados en las nóminas
        tengan correctamente configurados los campos que determinan su comportamiento
        en el cálculo de días trabajados.
        
        Returns:
            bool: True si todos los tipos están correctamente configurados
            
        Raises:
            UserError: Si algún tipo de ausencia no está correctamente configurado
        """
        if not self.leave_ids:
            return True
            
        valid_novelty_types = [
            'sln', 'ige', 'irl', 'lma', 'lpa', 'vco', 'vdi', 
            'vre', 'lr', 'lnr', 'lt', 'p'
        ]
        
        leave_status_list = self.leave_ids.leave_id.mapped('holiday_status_id')
        missing_config = []
        
        for leave_status in leave_status_list:
            if not leave_status.novelty:
                missing_config.append(f"{leave_status.name}: Sin tipo PILA configurado")
            elif leave_status.novelty not in valid_novelty_types:
                missing_config.append(f"{leave_status.name}: Tipo PILA '{leave_status.novelty}' no válido")
                
            if leave_status.novelty in ['vco', 'p'] and leave_status.sub_wd:
                missing_config.append(f"{leave_status.name}: Tipo '{leave_status.novelty}' no debe restar días trabajados (sub_wd)")
                
            if not leave_status.work_entry_type_id:
                missing_config.append(f"{leave_status.name}: Falta tipo de entrada de trabajo (work_entry_type_id)")
        
        if missing_config:
            raise UserError(_(f"Configuración incorrecta en tipos de ausencia:\n{chr(10).join(missing_config)}"))
        
        return True
    
    def _action_compute_worked_days(self) -> bool:
        """
        Calcula los días trabajados para la nómina.
        
        Este método integra la validación de tipos de ausencia,
        carga los tipos de entrada necesarios y calcula las líneas
        de días trabajados para la nómina.
        """
        for payslip in self:
            payslip.worked_days_line_ids.unlink()
            payslip._validate_leave_types()
            payslip.compute_sheet_leave()
            worked_days_lines = payslip.get_worked_day_lines()
            for line in worked_days_lines:
                self.env['hr.payslip.worked_days'].create({
                    'payslip_id': payslip.id,
                    **line
                })
        
        return True
    
    def get_worked_day_lines(self) -> list[Any]:
        """
        Calcula y genera las líneas de días trabajados para la nómina.
        
        Este método determina los días trabajados, días de ausencia, y otros ajustes
        necesarios para el cálculo correcto de la nómina.
        
        Returns:
            list: Lista de diccionarios con la información de cada línea de días trabajados
        """
        res = []
        
        def format_number(number: float) -> float:
            """ Convierte un número a formato decimal. y devuelve como float """
            return float(Decimal(number))
            
        for rec in self:
            contract = rec.contract_id
            date_from = rec.date_from
            start_period = rec.date_from.replace(day=1)
            date_to = rec.date_to
            wage_changes_sorted = sorted(contract.change_wage_ids, key=lambda x: x.date_start)
            last_wage_change = max((change for change in wage_changes_sorted if change.date_start < date_from), default=None)
            current_wage_day = last_wage_change.wage / DAYS_MONTH if last_wage_change else contract.wage / DAYS_MONTH
            leaves_worked_lines = {}
            worked_days = 0
            worked_aux_days = 0
            aux_transport_days = 0
            worked30 = 0
            hp_type = rec.struct_process
            annual_parameters = self.env['hr.annual.parameters'].search([('year', '=', date_to.year)])
            w_hours = annual_parameters.hours_daily or HOURS_PER_DAY
            types = self._get_entry_types()
            days31 = types['days31']
            outdays = types['outdays']
            wdays = types['wdays']
            wdayst = types['wdayst']
            prevdays = types['prevdays']
            ps_types = ['nomina', 'contrato']
            if not rec.company_id.fragment_vac:
                ps_types.append('Vacaciones')
            adjustments = []
            if hp_type in ps_types:
                lab_days = rec.days_between(start_period, date_to)
                res.append({
                    'work_entry_type_id': wdayst.id,
                    'name': 'Total días del período',
                    'sequence': 1,
                    'code': 'TOTAL_DIAS',
                    'symbol': '',
                    'number_of_days': format_number(lab_days),
                    'number_of_hours': format_number(w_hours * lab_days),
                    'contract_id': contract.id
                })
                query = """
                    SELECT
                        SUM(wd.number_of_days) AS number_of_days,
                        wd.symbol,
                        hw.code
                    FROM hr_payslip_worked_days wd
                    INNER JOIN hr_payslip hp ON hp.id = wd.payslip_id
                    LEFT JOIN hr_work_entry_type hw ON hw.id = wd.work_entry_type_id
                    WHERE hp.date_from >= %s
                        AND hp.date_to <= %s
                        AND hp.contract_id = %s
                        AND hp.id != %s
                        AND hw.code NOT IN ('WORK_D', 'LICENCIA_REMUNERADA')
                        AND hp.struct_process IN ('vacaciones', 'nomina', 'contrato')
                        AND hp.state IN ('done', 'paid')
                    GROUP BY wd.symbol, hw.code
                """
                params = (date_from, date_to, contract.id, rec.id)
                self._cr.execute(query, params)
                wd_other_data = self._cr.fetchall()
                wd_other = 0
                wd_prev = 0
                wd_minus = 0
                
                for number_of_days, symbol, code in wd_other_data:
                    if code == 'WORK_D':
                        wd_other += number_of_days
                    else:
                        if code in ('PREV_AUS', 'PREV_PAYS'):
                            wd_prev += number_of_days
                        elif symbol in ('-', '') and code not in ('OUT', 'VAC', 'VACDISFRUTADAS'):
                            wd_minus += number_of_days

                sum_wdo = wd_minus - wd_prev
                wd_other = sum_wdo
                if wd_other > 0:
                    adjustments.append(f"(-{wd_other} D previos)")
                date_tmp = date_from
                out_of_contract_days = 0
                while date_tmp <= date_to:
                    is_absence_day = any(
                        leave.date_from.date() <= date_tmp <= leave.date_to.date() and 
                        leave.holiday_status_id.novelty not in ['vco', 'p'] and
                        leave.holiday_status_id.sub_wd
                        for leave in rec.leave_ids.leave_id
                    )
                    
                    is_within_contract = contract.date_start <= date_tmp <= (contract.date_end or date_tmp)
                    
                    wage_change_today = next((change for change in wage_changes_sorted if change.date_start == date_tmp), None)
                    if wage_change_today:
                        current_wage_day = wage_change_today.wage / DAYS_MONTH
                    if is_within_contract:
                        if is_absence_day:
                            leave = next(leave for leave in rec.leave_ids.leave_id 
                                       if leave.date_from.date() <= date_tmp <= leave.date_to.date() 
                                       and leave.holiday_status_id.novelty not in ['vco', 'p']
                                       and leave.holiday_status_id.sub_wd)
                            key = (leave.holiday_status_id.id, '-')
                            absence_line = next((line for line in leave.line_ids if line.date == date_tmp), None)
                            
                            if absence_line:
                                days_to_subtract = absence_line.days_payslip
                                hour_to_subtract = absence_line.hours
                                amount = absence_line.amount
                                if key not in leaves_worked_lines:
                                    leaves_worked_lines[key] = {
                                        'work_entry_type_id': leave.holiday_status_id.work_entry_type_id.id,
                                        'name': f"Días {leave.holiday_status_id.name.capitalize()}",
                                        'sequence': 5,
                                        'code': leave.holiday_status_id.code or 'nocode',
                                        'symbol': '-',
                                        'amount': amount,
                                        'number_of_days': days_to_subtract,
                                        'number_of_hours': hour_to_subtract,
                                        'contract_id': contract.id,
                                    }
                                else:
                                    leaves_worked_lines[key]['number_of_days'] += days_to_subtract
                                    leaves_worked_lines[key]['number_of_hours'] += hour_to_subtract
                                    leaves_worked_lines[key]['amount'] += amount
                                    
                                if leave.holiday_status_id.sub_not_aux:
                                    aux_transport_days += days_to_subtract

                            if date_tmp.month == 2:
                                last_day_of_february = calendar.monthrange(date_tmp.year, 2)[1]
                                if date_tmp.day == last_day_of_february:
                                    if date_tmp.day == 28:
                                        worked_days += 2
                                        worked_aux_days += 2
                                    else:
                                        worked_days += 1
                                        worked_aux_days += 1
                        
                        else:
                            if date_tmp.month == 2:
                                last_day_of_february = calendar.monthrange(date_tmp.year, 2)[1]
                                if date_tmp.day == last_day_of_february:
                                    if date_tmp.day == 28:
                                        worked_days += 3
                                        worked_aux_days += 3
                                        adjustments.append("(+2 D febrero)")
                                    else:
                                        worked_days += 2
                                        worked_aux_days += 2
                                        adjustments.append("(+1 D febrero)")
                                else:
                                    worked_days += 1
                                    worked_aux_days += 1
                            elif date_tmp.day == 31:
                                if any(leave.date_from.date() <= date_tmp <= leave.date_to.date() 
                                      and leave.apply_day_31 for leave in rec.leave_ids.leave_id):
                                    worked_days -= 1
                                    worked_aux_days -= 1
                                    worked30 = 0
                                else:
                                    worked_days += 0
                                    worked_aux_days += 0
                                    worked30 = 1
                                    adjustments.append("(-1 D día 31)")
                            else:
                                worked_days += 1
                                worked_aux_days += 1
                    
                    else:
                        out_of_contract_days += 1
                    date_tmp += timedelta(days=1)

                if out_of_contract_days > 0:
                    description = 'Deducción por inicio de contrato' if date_from < contract.date_start else 'Deducción por fin de contrato'
                    res.append({
                        'work_entry_type_id': outdays.id,
                        'name': description,
                        'sequence': 2,
                        'code': 'OUT',
                        'symbol': '-',
                        'number_of_days': format_number(out_of_contract_days),
                        'number_of_hours': format_number(w_hours * out_of_contract_days),
                        'contract_id': contract.id,
                    })
                    adjustments.append(f"(-{out_of_contract_days} D fuera contrato)")

                for key, line_data in leaves_worked_lines.items():
                    line_data['number_of_days'] = format_number(line_data['number_of_days'])
                    line_data['number_of_hours'] = format_number(line_data['number_of_hours'])
                    res.append(line_data)
                worked_aux_days = worked_days + aux_transport_days
                worked_days_name = 'Días Trabajados'
                if adjustments:
                    worked_days_name += " " + " ".join(adjustments)
                res.append({
                    'work_entry_type_id': wdays.id,
                    'name': worked_days_name,
                    'sequence': 6,
                    'code': 'WORK100',
                    'symbol': '+',
                    'amount': current_wage_day * worked_days,
                    'number_of_days': format_number(worked_days),
                    'number_of_hours': format_number(worked_days * w_hours),
                    'number_of_days_aux': format_number(worked_aux_days),
                    'number_of_hours_aux': format_number(worked_aux_days * w_hours),
                    'contract_id': contract.id
                })
                if rec.struct_id.regular_31:
                    res.append({
                        'work_entry_type_id': days31.id,
                        'name': 'Día 31',
                        'sequence': 6,
                        'code': 'WORK131',
                        'symbol': '+',
                        'amount': current_wage_day * worked30,
                        'number_of_days': format_number(worked30),
                        'number_of_hours': format_number(worked30 * w_hours),
                        'number_of_days_aux': format_number(worked30),
                        'number_of_hours_aux': format_number(worked30 * w_hours),
                        'contract_id': contract.id
                    })
                if wd_other:
                    res.append({
                        'work_entry_type_id': prevdays.id,
                        'name': 'Días Previos',
                        'sequence': 7,
                        'code': 'PREV_PAYS',
                        'symbol': '-',
                        'number_of_days': format_number(wd_other),
                        'number_of_hours': format_number(wd_other * w_hours),
                        'contract_id': contract.id
                    })
        return res
    
    def compute_sheet_leave(self) -> bool:
        """
        Calcula y asigna las ausencias para la nómina con detalle mejorado
        de días usados y no utilizados, respetando la estructura de campos existente.
        """
        for rec in self:
            rec.leave_ids.unlink()
            rec.payslip_day_ids.unlink()
            date_from = datetime.combine(rec.date_from, DATETIME_MIN)
            date_to = datetime.combine(rec.date_to, DATETIME_MAX)
            employee_id = rec.employee_id.id
            leaves = self.env['hr.leave'].search([
                ('state', '=', 'validate'),
                ('date_to', '>=', date_from),
                ('date_from', '<=', date_to),
                ('employee_id', '=', employee_id),
            ])
            self._validate_leave_types()
            
            if not leaves:
                rec.compute_worked_days()
                return True
            
            absence_records = []
            
            for leave in leaves:
                leave_start = max(leave.date_from.date(), rec.date_from)
                leave_end = min(leave.date_to.date(), rec.date_to)
                days_in_payslip = (leave_end - leave_start).days + 1
                days_in_other_payslips = sum(
                    line.days_payslip 
                    for line in leave.line_ids 
                    if line.payslip_id and line.payslip_id.id != rec.id
                )
                affects_payroll = leave.holiday_status_id.novelty not in ['vco', 'p'] and leave.holiday_status_id.sub_wd
                days_to_use = days_in_payslip if affects_payroll else 0
                days_not_used = leave.number_of_days - days_to_use - days_in_other_payslips
                absence_data = {
                    'leave_id': leave.id,
                    'leave_type': leave.holiday_status_id.name,
                    'employee_id': employee_id,
                    'payroll_id': rec.id,
                    'total_days': leave.number_of_days,
                    'days_used': days_to_use,
                    'days_unused': days_not_used,
                    'is_interrupted': False,
                }
                
                absence_records.append(absence_data)
            if absence_records:
                leave_records = self.env['hr.absence.days'].create(absence_records)
                all_lines = leave_records.mapped('leave_id.line_ids').filtered(
                    lambda l: l.state == 'validated'
                )
                if rec.struct_id.process == 'vacaciones' or rec.pay_vacations_in_payroll:
                    vacation_lines = all_lines.filtered(lambda l: l.leave_id.holiday_status_id.is_vacation)
                    if vacation_lines:
                        money_lines = vacation_lines.filtered(
                            lambda l: l.leave_id.holiday_status_id.is_vacation_money
                        )
                        time_lines = vacation_lines - money_lines
                        
                        relevant_lines = money_lines
                        if rec.company_id.fragment_vac:
                            relevant_lines |= time_lines.filtered(
                                lambda l: rec.date_from <= l.date <= rec.date_to
                            )
                        else:
                            relevant_lines |= time_lines
                        
                        relevant_lines.write({
                            'payslip_id': rec.id,
                        })
                    
                    other_lines = all_lines - vacation_lines
                    if other_lines:
                        other_lines.filtered(
                            lambda l: rec.date_from <= l.date <= rec.date_to
                        ).write({
                            'payslip_id': rec.id
                        })
                
                else:
                    relevant_lines = all_lines.filtered(
                        lambda l: (
                            rec.date_from <= l.date <= rec.date_to and
                            not l.leave_id.holiday_status_id.is_vacation and 
                            not l.leave_id.holiday_status_id.is_vacation_money
                        )
                    )
                    if relevant_lines:
                        relevant_lines.write({
                            'payslip_id': rec.id
                        })
            rec.compute_worked_days()
        return True

    def compute_worked_days(self) -> bool:
        """
        Calcula los días trabajados para la nómina.
        Incluye manejo especial para febrero, día 31, días de descanso, sábados y feriados.
        """
        for rec in self:
            payslip_day_ids = []
            rec._validate_leave_types()
            wage_changes_sorted = sorted(rec.contract_id.change_wage_ids, key=lambda x: x.date_start)
            last_wage_change_before_payslip = max((change for change in wage_changes_sorted 
                                                if change.date_start < rec.date_from), default=None)
            current_wage_day = last_wage_change_before_payslip.wage / DAYS_MONTH if last_wage_change_before_payslip else rec.contract_id.wage / DAYS_MONTH
            has_day_31 = False
            holiday_service = self.env['lavish.holidays']
            date_tmp = rec.date_from
            while date_tmp <= rec.date_to:
                absence_line = None
                permission_line = None
                permission_leaves = [
                    leave for leave in rec.leave_ids.leave_id 
                    if leave.date_from.date() <= date_tmp <= leave.date_to.date() and 
                    leave.holiday_status_id.novelty == 'p'
                ]
                is_permission_day = bool(permission_leaves)
                if is_permission_day:
                    permission_leave = permission_leaves[0]
                    permission_line = next(
                        (line for line in permission_leave.line_ids 
                        if line.date == date_tmp and line.state == 'validated'), 
                        None
                    )
                absence_leaves = [
                    leave for leave in rec.leave_ids.leave_id 
                    if leave.date_from.date() <= date_tmp <= leave.date_to.date() and 
                    leave.holiday_status_id.novelty not in ['vco', 'p'] and
                    leave.holiday_status_id.sub_wd
                ]
                
                is_absence_day = bool(absence_leaves)
                
                if is_absence_day:
                    absence_leave = absence_leaves[0]
                    absence_line = next(
                        (line for line in absence_leave.line_ids 
                        if line.date == date_tmp and line.state == 'validated'), 
                        None
                    )
                
                is_within_contract = rec.contract_id.date_start <= date_tmp <= (rec.contract_id.date_end or date_tmp)
                is_holiday = holiday_service.ensure_holidays(date_tmp)
                is_sunday = date_tmp.weekday() == 6
                is_saturday = date_tmp.weekday() == 5 and not rec.employee_id.sabado
                is_day_31 = date_tmp.day == 31
                wage_change_today = next((change for change in wage_changes_sorted if change.date_start == date_tmp), None)
                if wage_change_today:
                    current_wage_day = wage_change_today.wage / DAYS_MONTH
                if is_within_contract:
                    if is_absence_day:
                        day_type = 'A'  # Ausencia
                    elif is_permission_day:
                        day_type = 'P'  # Permiso (informativo, no resta días)
                    elif is_holiday:
                        day_type = 'H'  # Feriado
                    elif is_sunday:
                        day_type = 'D'  # Día de descanso (domingo)
                    elif is_saturday:
                        day_type = 'S'  # Sábado
                    else:
                        day_type = 'W'  # Trabajado
                    payslip_day_data = {
                        'payslip_id': rec.id, 
                        'day': date_tmp.day, 
                        'day_type': day_type,
                        'is_holiday': is_holiday,
                        'is_sunday': is_sunday,
                        'is_saturday': is_saturday,
                        'is_permission': is_permission_day,
                        'is_absence': is_absence_day
                    }
                    
                    if absence_line:
                        payslip_day_data['leave_line_id'] = absence_line.id
                    elif permission_line:
                        payslip_day_data['leave_line_id'] = permission_line.id
                    if is_day_31:
                        has_day_31 = True
                        apply_day_31 = any(
                            leave.date_from.date() <= date_tmp <= leave.date_to.date() and 
                            leave.apply_day_31 
                            for leave in rec.leave_ids.leave_id
                        )
                        
                        if not apply_day_31:
                            payslip_day_data['is_day_31'] = True
                    if date_tmp.month == 2:
                        last_day_of_february = calendar.monthrange(date_tmp.year, 2)[1]
                        if date_tmp.day == last_day_of_february:
                            payslip_day_data['is_feb_last'] = True
                    
                            if date_tmp.day == 28:
                                payslip_day_data['feb_adjust'] = 2  
                            else:  # día 29
                                payslip_day_data['feb_adjust'] = 1  
                    if day_type not in ['A', 'X']:
                        payslip_day_data['subtotal'] = current_wage_day
                    payslip_day_ids.append(payslip_day_data)
                else:
                    payslip_day_ids.append({
                        'payslip_id': rec.id, 
                        'day': date_tmp.day, 
                        'day_type': 'X',
                        'is_holiday': is_holiday,
                        'is_sunday': is_sunday,
                        'is_saturday': is_saturday
                    })
                date_tmp += timedelta(days=1)
            if rec.period_id.type_period == "monthly" and not has_day_31:
                last_day = calendar.monthrange(rec.date_to.year, rec.date_to.month)[1]
                if last_day < 31:
                    payslip_day_ids.append({
                        'payslip_id': rec.id,
                        'day': 31,
                        'day_type': 'V',
                        'is_virtual': True,
                        'is_day_31': True
                    })
            rec.payslip_day_ids.create(payslip_day_ids)
        
        return True

class HrPeriod(models.Model):
    _name = 'hr.period'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Periodo de nómina'
    _order = 'date_start,name'

    name = fields.Char(string='Nombre', readonly=True)
    active = fields.Boolean(string='Activo', default=True)
    date_start = fields.Date(string='Fecha de Inicio', readonly=True)
    date_end = fields.Date(string='Fecha de Fin', readonly=True)
    type_period = fields.Selection(string='Tipo de periodo', selection=TYPE_PERIOD, readonly=True)
    type_biweekly = fields.Selection(string='Tipo de quincena', selection=TYPE_BIWEEKLY, readonly=True)
    company_id = fields.Many2one(comodel_name='res.company', string='Compañia', default=lambda self: self.env.company, readonly=True)
    closed = fields.Boolean(string='Cerrado', default=False)
    unlock_reason = fields.Text(string='Motivo de Desbloqueo', readonly=True)
    year = fields.Integer(string='Año', compute='_compute_year', store=True)
    year_month = fields.Char(string='Año-Mes', compute='_compute_year_month', store=True)
    all_payslips_computed = fields.Boolean(string='Nóminas Calculadas', default=False)
    all_payslips_paid = fields.Boolean(string='Nóminas Pagadas', default=False)
    display_name = fields.Char(compute='_compute_display_name')

    _sql_constraints = [
        ('date_period_company_uniq', 'unique(start, end, type_period, type_biweekly, company_id)', 'No puede existir un periodo duplicado para la misma compañía')
    ]

    @api.depends('date_start')
    def _compute_year(self):
        for record in self:
            record.year = record.date_start.year if record.date_start else False

    @api.depends('date_start')
    def _compute_year_month(self):
        for record in self:
            if record.date_start:
                record.year_month = f"{record.date_start.year}{record.date_start.month:02d}"
            else:
                record.year_month = False

    @api.depends('name', 'type_period', 'type_biweekly')
    def _compute_display_name(self):
        for record in self:
            name = record.name or ''
            if record.type_period:
                type_text = dict(TYPE_PERIOD).get(record.type_period, '')
                name = f"{name} ({type_text})"
                if record.type_period == 'bi-monthly' and record.type_biweekly:
                    biweekly_text = dict(TYPE_BIWEEKLY).get(record.type_biweekly, '')
                    name = f"{name} - {biweekly_text}"
            record.display_name = name

    @api.model
    def create(self, vals):
        if 'allow_create' in vals and vals['allow_create']:
            vals.pop('allow_create')
            return super(HrPeriod, self).create(vals)
        raise UserError(_('Ningún usuario tiene permitido crear periodos manualmente. Vaya al creador de periodos.'))

    def write(self, vals):
        allowed_fields = {'active', 'closed', 'unlock_reason', 'all_payslips_computed', 'all_payslips_paid'}
        if not set(vals.keys()).issubset(allowed_fields):
            raise UserError(_('Solo se puede modificar el estado activo, cerrado y otros campos de estado del periodo.'))
        return super(HrPeriod, self).write(vals)

    def get_period(self, date_from:date, date_to:date, type_period:str, company_id: Optional[int]=None) -> 'HrPeriod':
        domain = [
            ('type_period', '=', type_period),
            ('active', '=', True)
        ]
        if company_id:
            domain.append(('company_id', '=', company_id))
        else:
            domain.append(('company_id', '=', self.env.company.id))
        domain.extend([
            ('date_start', '<=', date_to),
            ('date_end', '>=', date_from)
        ])
        
        return self.search(domain, limit=1)

    def between(self, date):
        if not date:
            return False
        return self.date_start <= date <= self.date_end

    def _get_schedule_days(self, type_period):
        dias_dif = 0
        if type_period == 'weekly':
            dias_dif = 7
        elif type_period == 'bi-monthly':
            dias_dif = 15
        elif type_period == 'monthly':
            dias_dif = 30
        elif type_period == 'dualmonth':
            dias_dif = 60
        elif type_period == 'quarterly':
            dias_dif = 90
        elif type_period == 'semi-annually':
            dias_dif = 180
        elif type_period == 'annually':
            dias_dif = 360
        
        return dias_dif

    def get_previous_periods(self, count=1):
        self.ensure_one()
        return self.search([
            ('type_period', '=', self.type_period),
            ('type_biweekly', '=', self.type_biweekly),
            ('company_id', '=', self.company_id.id),
            ('date_end', '<', self.date_start),
            ('active', '=', True)
        ], order='date_end desc', limit=count)
        
    def get_next_periods(self, count:int=1) -> 'HrPeriod':
        self.ensure_one()
        return self.search([
            ('type_period', '=', self.type_period),
            ('type_biweekly', '=', self.type_biweekly),
            ('company_id', '=', self.company_id.id),
            ('date_start', '>', self.date_end),
            ('active', '=', True)
        ], order='date_start asc', limit=count)

    def close_period(self) -> bool:
        self.ensure_one()
        payslips = self.env['hr.payslip'].search([
            ('period_id', '=', self.id),
            ('state', 'not in', ['done', 'cancel'])
        ])
        
        if payslips:
            raise UserError(_("No se puede cerrar el periodo porque existen nóminas en proceso. Finalice todas las nóminas antes de cerrar el periodo."))
        
        self.closed = True
        return True

    def unlock_period(self, reason:str) -> bool:
        self.ensure_one()
        if not reason:
            raise UserError(_("Debe proporcionar un motivo para desbloquear el periodo."))
        
        self.write({
            'closed': False,
            'unlock_reason': reason,
        })
        
        self.env['mail.message'].create({
            'model': self._name,
            'res_id': self.id,
            'message_type': 'notification',
            'body': _("Periodo desbloqueado. Motivo: %s") % reason,
        })
        
        return True

    @api.model
    def create_periods_for_year(self, year: int, schedule_pays: Optional[list[str]]=None, company_id: Optional[int] = None) -> list[int]:
        if schedule_pays is None:
            schedule_pays = ['monthly', 'bi-monthly']
        
        if company_id is None:
            company_id = self.env.company.id
            
        created_periods = []
        
        for schedule_pay in schedule_pays:
            if schedule_pay == 'weekly':
                start_date = datetime(year, 1, 1)
                while start_date.weekday() != 0:
                    start_date += timedelta(days=1)
                
                for week in range(52):
                    end_date = start_date + timedelta(days=6)
                    period_name = f"Semana {week+1}/{year}"
                    
                    period_vals = {
                        'name': period_name,
                        'date_start': start_date,
                        'date_end': end_date,
                        'type_period': 'weekly',
                        'company_id': company_id,
                        'allow_create': True
                    }
                    
                    period_id = self.create(period_vals)
                    created_periods.append(period_id.id)
                    
                    start_date = end_date + timedelta(days=1)
            
            elif schedule_pay == 'bi-monthly':
                for month in range(1, 13):
                    start_date = datetime(year, month, 1)
                    end_date = datetime(year, month, 15)
                    period_name = f"1-15/{month}/{year}"
                    
                    period_vals = {
                        'name': period_name,
                        'date_start': start_date,
                        'date_end': end_date,
                        'type_period': 'bi-monthly',
                        'type_biweekly': 'first',
                        'company_id': company_id,
                        'allow_create': True
                    }
                    
                    period_id = self.create(period_vals)
                    created_periods.append(period_id.id)
                    
                    start_date = datetime(year, month, 16)
                    if month == 12:
                        end_date = datetime(year, month, 30)
                    elif month == 2:
                        end_date = datetime(year, month, 28)
                    else:
                        month_days = 30
                        end_date = datetime(year, month, month_days)
                    
                    period_name = f"16-30/{month}/{year}"
                    
                    period_vals = {
                        'name': period_name,
                        'date_start': start_date,
                        'date_end': end_date,
                        'type_period': 'bi-monthly',
                        'type_biweekly': 'second',
                        'company_id': company_id,
                        'allow_create': True
                    }
                    
                    period_id = self.create(period_vals)
                    created_periods.append(period_id.id)
            
            elif schedule_pay == 'monthly':
                for month in range(1, 13):
                    start_date = datetime(year, month, 1)
                    if month == 12:
                        end_date = datetime(year, month, 30)
                    elif month == 2:
                        end_date = datetime(year, month, 28)
                    else:
                        end_date = datetime(year, month, 30)
                    
                    month_name = start_date.strftime('%B').capitalize()
                    period_name = f"{month_name} {year}"
                    
                    period_vals = {
                        'name': period_name,
                        'date_start': start_date,
                        'date_end': end_date,
                        'type_period': 'monthly',
                        'company_id': company_id,
                        'allow_create': True
                    }
                    
                    period_id = self.create(period_vals)
                    created_periods.append(period_id.id)
            
            elif schedule_pay == 'dualmonth':
                for i in range(6):
                    month = i * 2 + 1
                    start_date = datetime(year, month, 1)
                    
                    if month == 11:
                        end_date = datetime(year, month + 1, 30)
                    else:
                        next_month = month + 1 if month < 12 else 1
                        next_month_year = year if month < 12 else year + 1
                        end_date = datetime(next_month_year, next_month, 30)
                    
                    period_name = f"{month}-{month+1}/{year}"
                    
                    period_vals = {
                        'name': period_name,
                        'start': start_date,
                        'date_start': start_date,
                        'date_end': end_date,
                        'type_period': 'dualmonth',
                        'company_id': company_id,
                        'allow_create': True
                    }
                    
                    period_id = self.create(period_vals)
                    created_periods.append(period_id.id)
            
            elif schedule_pay == 'quarterly':
                for quarter in range(4):
                    month = quarter * 3 + 1
                    start_date = datetime(year, month, 1)
                    
                    end_month = month + 2
                    end_date = datetime(year, end_month, 30)
                    
                    period_name = f"Q{quarter+1}/{year}"
                    
                    period_vals = {
                        'name': period_name,
                        'date_start': start_date,
                        'date_end': end_date,
                        'type_period': 'quarterly',
                        'company_id': company_id,
                        'allow_create': True
                    }
                    
                    period_id = self.create(period_vals)
                    created_periods.append(period_id.id)
            
            elif schedule_pay == 'semi-annually':
                start_date = datetime(year, 1, 1)
                end_date = datetime(year, 6, 30)
                period_name = f"S1/{year}"
                
                period_vals = {
                    'name': period_name,
                    'date_start': start_date,
                    'date_end': end_date,
                    'type_period': 'semi-annually',
                    'company_id': company_id,
                    'allow_create': True
                }
                
                period_id = self.create(period_vals)
                created_periods.append(period_id.id)
                
                start_date = datetime(year, 7, 1)
                end_date = datetime(year, 12, 30)
                period_name = f"S2/{year}"
                
                period_vals = {
                    'name': period_name,
                    'date_start': start_date,
                    'date_end': end_date,
                    'type_period': 'semi-annually',
                    'company_id': company_id,
                    'allow_create': True
                }
                
                period_id = self.create(period_vals)
                created_periods.append(period_id.id)
            
            elif schedule_pay == 'annually':
                start_date = datetime(year, 1, 1)
                end_date = datetime(year, 12, 30)
                period_name = f"Año {year}"
                
                period_vals = {
                    'name': period_name,
                    'date_start': start_date,
                    'date_end': end_date,
                    'type_period': 'annually',
                    'company_id': company_id,
                    'allow_create': True
                }
                
                period_id = self.create(period_vals)
                created_periods.append(period_id.id)
        
        return created_periods

    @api.model
    def _cron_check_payslips_status(self):
        active_periods = self.search([
            ('active', '=', True),
            ('closed', '=', False),
            ('date_end', '<', fields.Date.today())
        ])
        
        for period in active_periods:
            payslips = self.env['hr.payslip'].search([
                ('period_id', '=', period.id),
                ('state', 'not in', ['cancel'])
            ])
            
            if not payslips:
                continue
                
            all_computed = all(p.state != 'draft' for p in payslips)
            all_paid = all(p.state == 'done' for p in payslips)
            
            period.write({
                'all_payslips_computed': all_computed,
                'all_payslips_paid': all_paid
            })
            
            if all_paid:
                self.env['mail.activity'].create({
                    'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
                    'note': _("Todas las nóminas de este período están pagadas. Se recomienda cerrar el período."),
                    'user_id': self.env.user.id,
                    'res_id': period.id,
                    'res_model_id': self.env['ir.model'].search(
                        [('model', '=', 'hr.period')], limit=1).id,
                })

class HrPayslipRun(models.Model):
    _inherit = 'hr.payslip.run'
    
    period_id = fields.Many2one('hr.period', string='Periodo de Nómina',
                               domain="[('closed', '=', False)]")
    
    @api.onchange('period_id')
    def _onchange_period_id(self):
        if self.period_id and (not self.date_start or not self.date_end or 
                               self.date_start.year != self.period_id.date_start.year or 
                               self.date_end.year != self.period_id.date_end.year):
            self.date_start = self.period_id.date_start
            self.date_end = self.period_id.date_end
    
    @api.onchange('date_start', 'date_end')
    def _onchange_dates(self):
        if not self._context.get('skip_period_search'):
            if self.date_start:
                company_id = self.company_id.id or self.env.company.id
                if self.date_end:
                    days_diff = (self.date_end - self.date_start).days + 1
                    if days_diff <= 7:
                        schedule_pay = 'weekly'
                    elif days_diff <= 15:
                        schedule_pay = 'bi-monthly'
                    elif days_diff <= 31:
                        schedule_pay = 'monthly'
                    else:
                        schedule_pay = 'monthly'
                else:
                    schedule_pay = 'monthly'
                
                period = self.env['hr.period'].get_period(
                    self.date_start, self.date_end, schedule_pay, company_id)
                
                if period and self.period_id != period:
                    self.with_context(skip_period_search=True).period_id = period.id
    
    @api.model
    def create(self, vals):
        res = super(HrPayslipRun, self).create(vals)
        if res.period_id:
            for slip in res.slip_ids:
                slip.write({
                    'period_id': res.period_id.id,
                    'date_from': res.period_id.date_start,
                    'date_to': res.period_id.date_end,
                })
        
        return res

class ResourceCalendar(models.Model):
    _inherit = "resource.calendar"

    def get_holidays(self, year, add_offset=False):
        self.ensure_one()
        leave_obj = self.env['resource.calendar.leaves']
        holidays = []
        tz_offset = 0
        if add_offset:
            tz_offset = fields.Datetime.context_timestamp(
                self, fields.Datetime.from_string(fields.Datetime.now())).\
                utcoffset().total_seconds()
        start_dt = fields.Datetime.from_string(fields.Datetime.now()).\
            replace(year=year, month=1, day=1, hour=0, minute=0, second=0) + \
            relativedelta(seconds=tz_offset)
        end_dt = start_dt + relativedelta(years=1) - relativedelta(seconds=1)
        leaves_domain = [
            ('calendar_id', '=', self.id),
            ('resource_id', '=', False),
            ('date_from', '>=', fields.Datetime.to_string(start_dt)),
            ('date_to', '<=', fields.Datetime.to_string(end_dt))]
        for leave in leave_obj.search(leaves_domain):
            date_from = fields.Datetime.from_string(leave.date_from)
            holidays.append((date_from.date(), leave.name))
        return holidays

class HrPayslipRuleOverride(models.Model):
    _name = 'hr.payslip.rule.override'
    _description = 'Modificación de Reglas de Nómina'

    payslip_id = fields.Many2one('hr.payslip', 'Nómina', required=True)
    rule_id = fields.Many2one('hr.salary.rule', 'Regla', required=True)
    override_type = fields.Selection([
        ('amount', 'Monto Base'),
        ('quantity', 'Cantidad'),
        ('rate', 'Tasa'),
        ('total', 'Total Final'),
    ], string='Tipo de Modificación', required=True)
    value_original = fields.Float('Valor Original', readonly=True)
    value_override = fields.Float('Valor Nuevo')
    active = fields.Boolean('Aplicar Modificación', default=True)
    description = fields.Text('Descripción/Motivo')
    simulation_date = fields.Datetime('Fecha Simulación', default=fields.Datetime.now)
    simulation_result = fields.Float('Resultado Simulado', readonly=True)
    difference = fields.Float('Diferencia', compute='_compute_difference')
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('simulated', 'Simulado'),
        ('applied', 'Aplicado')
    ], string='Estado', default='draft')

    @api.depends('value_original', 'value_override')
    def _compute_difference(self):
        for record in self:
            record.difference = record.value_override - record.value_original

    def action_simulate(self):
        self.ensure_one()
        if self.payslip_id.state not in ['draft', 'verify']:
            raise UserError('Solo se pueden simular ajustes en nóminas en borrador o verificación')
        
        # Crear una copia del cálculo original para simular
        result = self.payslip_id.with_context(
            simulate_override=True, 
            override_rule=self.rule_id.code,
            override_type=self.override_type,
            override_value=self.value_override
        )._get_payslip_lines_lavish()
        
        # Encontrar el resultado simulado para esta regla
        rule_result = next((r for r in result if r['code'] == self.rule_id.code), None)
        if rule_result:
            self.simulation_result = rule_result['total']
            self.state = 'simulated'
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Simulación Completada',
                'message': f'Resultado simulado: {self.simulation_result:,.2f}\nDiferencia: {self.difference:,.2f}',
                'sticky': False,
                'type': 'info'
            }
        }


    @api.onchange('value_override')
    def _onchange_value_override(self):
        if self.value_override and self.value_original:
            if abs((self.value_override - self.value_original) / self.value_original) > 0.5:
                return {
                    'warning': {
                        'title': _("Variación Significativa"),
                        'message': _("El ajuste representa una variación mayor al 50% del valor original. Por favor verifique.")
                    }
                }
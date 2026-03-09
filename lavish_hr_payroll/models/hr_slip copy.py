# -*- coding: utf-8 -*-
from odoo import _, api, Command, fields, models, SUPERUSER_ID, tools
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_is_zero, float_round, date_utils
from odoo.osv.expression import AND
from odoo.tools.misc import format_date, format_amount
import logging
from datetime import datetime, timedelta, date
from collections import defaultdict, Counter, OrderedDict
import json
import calendar
import math
from decimal import Decimal, ROUND_HALF_UP
from dateutil.relativedelta import relativedelta
from .browsable_object import BrowsableObject, InputLine, WorkedDays, Payslips, ResultRules, ResultRules_co
import base64
import time
from functools import lru_cache
from psycopg2.extensions import AsIs
_logger = logging.getLogger(__name__)

# Constantes globales
DAYS_YEAR = 360
DAYS_MONTH = 30
PRECISION_TECHNICAL = 10
PRECISION_DISPLAY = 0
DATETIME_MIN = datetime.min.time()
DATETIME_MAX = datetime.max.time()

def json_serial(obj):
    """Helper para serializar objetos complejos a JSON"""
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
    _inherit = 'hr.payslip'
    
    # ==========================================================================
    # CAMPOS BÁSICOS Y COMPUTADOS
    # ==========================================================================
    # Campos generales
    rtefte_id = fields.Many2one('hr.employee.rtefte', 'RteFte', readonly=True)
    not_line_ids = fields.One2many('hr.payslip.not.line', 'slip_id', string='Reglas no aplicadas', readonly=True)
    observation = fields.Text(string='Observación')
    analytic_account_id = fields.Many2one('account.analytic.account', string='Cuenta analítica')
    employee_branch_id = fields.Many2one(related='employee_id.branch_id', string='Sucursal empleado', store=True)
    definitive_plan = fields.Boolean(string='Plano definitivo generado')
    journal_struct_id = fields.Many2one('account.journal', string='Salary Journal', domain="[('company_id', '=', company_id)]")
    contract_info = fields.Html()
    
    # Campos de fechas
    date_liquidacion = fields.Date('Fecha liquidación de contrato')
    date_prima = fields.Date('Fecha liquidación de prima')
    date_cesantias = fields.Date('Fecha liquidación de cesantías')
    date_vacaciones = fields.Date('Fecha liquidación de vacaciones')
    refund_date = fields.Date(string='Fecha reintegro')
    date_from = fields.Date(string='From', readonly=False, required=True, tracking=True, compute=False, store=True, precompute=False)
    date_to = fields.Date(string='To', readonly=False, required=True, tracking=True, compute=False, store=True, precompute=False)
    periodo = fields.Char('Periodo', compute="_compute_periodo", store=True)
    
    # Campos de opciones de procesamiento
    provisiones = fields.Boolean('Provisiones')
    reason_retiro = fields.Many2one('hr.departure.reason', string='Motivo de retiro')
    have_compensation = fields.Boolean('Indemnización', default=False)
    settle_payroll_concepts = fields.Boolean('Liquida conceptos de nómina', default=True)
    novelties_payroll_concepts = fields.Boolean('Liquida conceptos de novedades', default=True)
    pagar_cesantias_ano_anterior = fields.Boolean('Liquida conceptos de Cesantia periodo anterior', default=True)
    no_days_worked = fields.Boolean('Sin días laborados', default=False, help='Aplica unicamente cuando la fecha de inicio es igual a la fecha de finalización.')
    pay_cesantias_in_payroll = fields.Boolean('¿Liquidar Intereses de cesantía periodo anterior en nómina?')
    pay_primas_in_payroll = fields.Boolean('¿Liquidar Primas en nómina?')
    pay_vacations_in_payroll = fields.Boolean('¿Liquidar vacaciones en nómina?')
    
    # Campos de opciones avanzadas
    is_advance_severance = fields.Boolean(string='Es avance de cesantías')
    value_advance_severance = fields.Float(string='Valor a pagar avance')
    employee_severance_pay = fields.Boolean(string='Pago cesantías al empleado')
    severance_payments_reverse = fields.Many2many('hr.history.cesantias', string='Historico de cesantias/int.cesantias a tener encuenta', domain="[('employee_id', '=', employee_id)]")
    prima_run_reverse_id = fields.Many2one('hr.payslip.run', string='Lote de prima a ajustar')
    prima_payslip_reverse_id = fields.Many2one('hr.payslip', string='Prima a ajustar', domain="[('employee_id', '=', employee_id)]")
    rule_override_ids = fields.One2many('hr.payslip.rule.override', 'payslip_id', 'Ajustes de Reglas')
    has_overrides = fields.Boolean('Tiene Ajustes', compute='_compute_has_overrides')
    enable_rule_overrides = fields.Boolean('Habilitar ajustes manuales', help='Permite modificar manualmente los valores de las reglas salariales', tracking=True)
    
    # Campos relacionados con otros registros
    extrahours_ids = fields.One2many('hr.overtime', 'payslip_run_id', string='Horas Extra Detallada')
    novedades_ids = fields.One2many('hr.novelties.different.concepts', 'payslip_id', string='Novedades Detalladas')
    payslip_old_ids = fields.Many2many('hr.payslip', 'hr_payslip_rel', 'current_payslip_id', 'old_payslip_id', string='Nominas relacionadas')
    paid_vacation_ids = fields.One2many('hr.payslip.paid.vacation', 'slip_id', string='Vacaciones remuneradas')
    leave_ids = fields.One2many('hr.absence.days', 'payroll_id', string='Novedades', readonly=True)
    leave_days_ids = fields.One2many('hr.leave.line', 'payslip_id', string='Detalle de Ausencia', readonly=True)
    payslip_day_ids = fields.One2many('hr.payslip.day', 'payslip_id', string='Días de Nómina', readonly=True)
    worked_days_line_ids = fields.One2many('hr.payslip.worked_days', 'payslip_id', compute=False)
    line_ids = fields.One2many('hr.payslip.line', 'slip_id', string='Líneas de Nómina', readonly=True)
    
    # Campos computados por categoría
    earnings_ids = fields.One2many('hr.payslip.line', compute="_compute_concepts_category", string='Conceptos de Nómina / Devengos')
    deductions_ids = fields.One2many('hr.payslip.line', compute="_compute_concepts_category", string='Conceptos de Nómina / Deducciones')
    bases_ids = fields.One2many('hr.payslip.line', compute="_compute_concepts_category", string='Conceptos de Nómina / Bases')
    provisions_ids = fields.One2many('hr.payslip.line', compute="_compute_concepts_category", string='Conceptos de Nómina / Provisiones')
    outcome_ids = fields.One2many('hr.payslip.line', compute="_compute_concepts_category", string='Conceptos de Nómina / Totales')
    
    # Campos técnicos
    struct_process = fields.Selection(related='struct_id.process', string='Proceso', store=True)
    computation_context_data = fields.Binary('Contexto de Cálculo', attachment=False)
    computation_log = fields.Text('Log de Cálculo', readonly=True, copy=False)
    result_co = fields.Binary('Resultado Cálculos', compute='_compute_result_co')
    period_id = fields.Many2one('hr.period', string='Periodo de Nómina', domain="[('closed', '=', False)]")
    computation_info = fields.Text(string='Información de Cómputo', readonly=True)
    computation_summary = fields.Html(string='Resumen de Cómputo', readonly=True)
    computation_logs = fields.Text(string='Logs de Cómputo', readonly=True)
    
    # Campos de ajustes de período
    computation_summary_html = fields.Html(string='Detalle del Cálculo', readonly=True)
    has_period_adjustments = fields.Boolean(string='Tiene Ajustes de Período', default=False)
    adjustment_days_31 = fields.Integer(string='Ajuste Días 31', default=0)
    adjustment_february = fields.Integer(string='Ajuste Febrero', default=0)
    adjustment_out_of_contract = fields.Integer(string='Ajuste Fuera de Contrato', default=0)
    effective_days = fields.Float(string='Días Efectivos', compute='_compute_effective_days', store=True)
    period_days_base = fields.Integer('Días Base del Período', related='period_id.base_days')

    # ==========================================================================
    # MÉTODOS COMPUTADOS
    # ==========================================================================
    @api.depends('date_to')
    def _compute_periodo(self):
        for rec in self:
            if rec.date_to:
                rec.periodo = rec.date_to.strftime("%Y%m")
            else:
                rec.periodo = ''

    @api.depends('worked_days_line_ids', 'adjustment_days_31', 'adjustment_february', 'adjustment_out_of_contract')
    def _compute_effective_days(self):
        """Calcula los días efectivos considerando ajustes de período"""
        for payslip in self:
            work100_lines = payslip.worked_days_line_ids.filtered(lambda l: l.code == 'WORK100')
            base_days = sum(line.number_of_days for line in work100_lines) if work100_lines else 0
            payslip.effective_days = base_days

    @api.depends('line_ids')
    def _compute_concepts_category(self):
        """Clasifica líneas de nómina por categorías para visualización"""
        category_mapping = {
            'EARNINGS': ['BASIC', 'AUX', 'AUS', 'ALW', 'ACCIDENTE_TRABAJO', 'DEV_NO_SALARIAL', 'DEV_SALARIAL', 
                         'TOTALDEV', 'HEYREC', 'COMISIONES', 'INCAPACIDAD', 'LICENCIA_MATERNIDAD', 
                         'LICENCIA_NO_REMUNERADA', 'LICENCIA_REMUNERADA', 'PRESTACIONES_SOCIALES', 
                         'PRIMA', 'VACACIONES'],
            'DEDUCTIONS': ['DED', 'DEDUCCIONES', 'TOTALDED', 'SANCIONES', 'DESCUENTO_AFC', 'SSOCIAL'],
            'PROVISIONS': ['PROV'],
            'OUTCOME': ['NET']
        }
        
        for payslip in self:
            categorized_lines = {
                'EARNINGS': [],
                'DEDUCTIONS': [],
                'PROVISIONS': [],
                'BASES': [],
                'OUTCOME': []
            }
            
            # Obtener líneas y sus categorías
            lines = self.env['hr.payslip.line'].search_read(
                [('slip_id', '=', payslip.id)],
                ['id', 'category_id']
            )
            
            if not lines:
                # Sin líneas, inicializar campos vacíos
                for field_name in categorized_lines.keys():
                    setattr(payslip, f"{field_name.lower()}_ids", self.env['hr.payslip.line'])
                continue
            
            # Obtener datos de categorías
            category_ids = list(set([line['category_id'][0] for line in lines if line['category_id']]))
            categories = {
                cat['id']: cat['code'] 
                for cat in self.env['hr.salary.rule.category'].search_read(
                    [('id', 'in', category_ids)],
                    ['id', 'code', 'parent_id']
                )
            }
            
            # Obtener categorías padre
            parent_ids = list(set([cat['parent_id'][0] for cat in self.env['hr.salary.rule.category'].search_read(
                [('id', 'in', category_ids), ('parent_id', '!=', False)],
                ['parent_id']
            ) if cat['parent_id']]))
            
            parent_categories = {
                cat['id']: cat['code'] 
                for cat in self.env['hr.salary.rule.category'].search_read(
                    [('id', 'in', parent_ids)],
                    ['id', 'code']
                )
            }
            
            # Clasificar cada línea
            for line in lines:
                category_found = False
                if line['category_id']:
                    cat_id = line['category_id'][0]
                    cat_code = categories.get(cat_id)
                    parent_code = None
                    
                    cat_info = self.env['hr.salary.rule.category'].browse(cat_id)
                    if cat_info.parent_id:
                        parent_code = parent_categories.get(cat_info.parent_id.id)
                    
                    # Buscar en las categorías conocidas
                    for category, codes in category_mapping.items():
                        if (cat_code in codes) or (parent_code in codes):
                            categorized_lines[category].append(line['id'])
                            category_found = True
                            break
                
                # Si no se encontró categoría, va a BASES
                if not category_found:
                    categorized_lines['BASES'].append(line['id'])
            
            # Asignar líneas a campos computados
            payslip.earnings_ids = self.env['hr.payslip.line'].browse(categorized_lines['EARNINGS'])
            payslip.deductions_ids = self.env['hr.payslip.line'].browse(categorized_lines['DEDUCTIONS'])
            payslip.provisions_ids = self.env['hr.payslip.line'].browse(categorized_lines['PROVISIONS'])
            payslip.bases_ids = self.env['hr.payslip.line'].browse(categorized_lines['BASES'])
            payslip.outcome_ids = self.env['hr.payslip.line'].browse(categorized_lines['OUTCOME'])

    def _compute_has_overrides(self):
        """Determina si la nómina tiene sobreescrituras de reglas"""
        db_manager = self._get_db_manager()
        for record in self:
            query = """
                SELECT COUNT(id) AS count
                FROM hr_payslip_rule_override
                WHERE payslip_id = %s AND active = TRUE
                LIMIT 1
            """
            result = db_manager.execute_query(query, [record.id])
            record.has_overrides = result['data'][0]['count'] > 0 if result['status'] == 'success' else False
            
    @api.depends('line_ids')
    def _compute_result_co(self):
        """
        Calcula el campo binario result_co que contiene información serializada 
        de las líneas de nómina con propiedades adicionales.
        """
        for payslip in self:
            result_data = {}
            
            # Si no hay líneas, no hay resultado
            if not payslip.line_ids:
                payslip.result_co = False
                continue
                
            # Procesar cada línea
            for line in payslip.line_ids:
                # Datos base para todas las líneas
                base_data = {
                    'amount': line.amount,
                    'quantity': line.quantity,
                    'rate': line.rate,
                    'total': line.total
                }
                
                # Agregar propiedades adicionales si existen
                for prop in ['base_seguridad_social', 'base_prima', 'base_cesantias', 
                            'base_vacaciones', 'base_vacaciones_dinero']:
                    if hasattr(line.salary_rule_id, prop) and getattr(line.salary_rule_id, prop):
                        base_data[prop] = True
                
                # Guardar datos para esta línea
                result_data[line.code] = base_data
            
            # Serializar y codificar resultado
            if result_data:
                serialized = json.dumps(result_data, default=json_serial)
                payslip.result_co = base64.b64encode(serialized.encode('utf-8'))
            else:
                payslip.result_co = False

    def _read_result_co(self):
        """
        Lee y deserializa el contenido del campo result_co.
        
        Returns:
            Dict: Datos de resultados deserializados o diccionario vacío si no hay datos
        """
        self.ensure_one()
        
        if not self.result_co:
            return {}
            
        try:
            # Decodificar y deserializar
            binary_data = base64.b64decode(self.result_co)
            return json.loads(binary_data)
        except Exception as e:
            _logger.error(f"Error al deserializar result_co: {str(e)}")
            return {}

    # ==========================================================================
    # MÉTODOS DE UTILIDAD
    # ==========================================================================
    def _get_db_manager(self):
        """Obtiene o crea una instancia del gestor de base de datos"""
        if not hasattr(self, '_db_manager'):
            self._db_manager = DatabaseManager(self.env)
        return self._db_manager
        
    def _get_notification_manager(self):
        """Obtiene o crea una instancia del gestor de notificaciones"""
        if not hasattr(self, '_notification_manager'):
            self._notification_manager = NotificationManager()
        return self._notification_manager

    def flush_models_before_compute(self):
        """
        Sincroniza modelos principales en la base de datos antes de cálculos.
        Esto mejora la consistencia de datos durante el proceso.
        """
        models_to_flush = [
            'hr.payslip', 'hr.payslip.line', 'hr.payslip.worked_days', 
            'hr.leave', 'hr.leave.line', 'hr.contract', 'hr.contract.concepts', 
            'hr.novelties.different.concepts', 'hr.overtime', 'hr.payslip.rule.override'
        ]
        
        for model_name in models_to_flush:
            self.env[model_name].flush_model()
        
        return True

    def compute_precise(self, value1, value2, operation='*', decimals=PRECISION_TECHNICAL):
        """
        Realiza cálculos con alta precisión para evitar errores de redondeo.
        
        Args:
            value1: Primer valor
            value2: Segundo valor
            operation: Operación a realizar (*, /, +, -)
            decimals: Decimales de precisión
            
        Returns:
            float: Resultado con la precisión indicada
        """
        # Convertir a enteros para evitar errores de punto flotante
        factor = 10 ** decimals
        int_value1 = int(float(value1) * factor)
        int_value2 = int(float(value2) * factor)
        
        # Realizar operación
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
            raise ValueError(f"Operación no soportada: {operation}")
        
        # Convertir de vuelta
        return result / factor

    def _get_entry_types(self):
        """
        Obtiene los tipos de entrada necesarios para los días trabajados.
        
        Returns:
            dict: Tipos de entrada por código
        """
        types = {}
        missing_types = []
        
        # Mapeo de códigos a nombres internos
        type_mappings = [
            ('WORK131', 'days31'), ('OUT', 'outdays'), ('WORK100', 'wdays'),
            ('WORK_D', 'wdayst'), ('PREV_PAYS', 'prevdays')
        ]
        
        # Buscar tipos de entrada
        for code, name in type_mappings:
            entry_type = self.env['hr.work.entry.type'].search([("code", "=", code)], limit=1)
            if not entry_type:
                missing_types.append(code)
            else:
                types[name] = entry_type
        
        # Reportar tipos faltantes
        if missing_types:
            raise UserError(_(f"Faltan los siguientes tipos de entrada: {', '.join(missing_types)}. "
                            f"Configúrelos antes de continuar."))
        
        return types

    def _get_rule_overrides(self):
        """
        Obtiene las sobreescrituras de reglas para esta nómina.
        
        Returns:
            dict: Sobreescrituras organizadas por código de regla
        """
        self.ensure_one()
        overrides = {}
        
        # Verificar si hay sobreescrituras
        is_sim_override = self.env.context.get('simulate_override', False)
        if not is_sim_override and not self.has_overrides:
            return overrides
            
        # Simular sobreescritura desde contexto (para pruebas)
        if is_sim_override:
            overrides = {
                self.env.context.get('override_rule'): {
                    'type': self.env.context.get('override_type'),
                    'value': self.env.context.get('override_value')
                }
            }
        else:
            # Buscar sobreescrituras reales
            db_manager = self._get_db_manager()
            query = """
                SELECT r.code, ro.override_type, ro.value_override
                FROM hr_payslip_rule_override ro
                JOIN hr_salary_rule r ON ro.rule_id = r.id
                WHERE ro.payslip_id = %s AND ro.active = TRUE
            """
            result = db_manager.execute_query(query, [self.id])
            
            if result['status'] == 'success':
                for row in result['data']:
                    overrides[row['code']] = {
                        'type': row['override_type'],
                        'value': row['value_override']
                    }
        
        return overrides

    def _get_rules_to_process(self):
        """
        Determina qué reglas salariales se deben procesar según el proceso.
        
        Returns:
            recordset: Reglas salariales a procesar para la nómina actual
        """
        self.ensure_one()
        process = self.struct_id.process
        
        # Función para obtener reglas específicas por proceso
        def get_specific_rules(process):
            return self.env['hr.salary.rule'].search([
                ('struct_id.process', '=', process),
                ('active', '=', True)
            ])
        
        # Reglas comunes para todos los procesos
        common_rules = self.env['hr.salary.rule'].search([
            ('code', 'in', ['TOTALDEV', 'TOTALDED', 'NET']),
            ('active', '=', True)
        ])
        
        # Determinar reglas según el proceso
        if process == 'nomina':
            rules = get_specific_rules('nomina')
            if self.pay_primas_in_payroll:
                rules |= get_specific_rules('prima')
            if self.pay_cesantias_in_payroll:
                rules |= self.env['hr.salary.rule'].search([('code', '=', 'INTCES_YEAR')])
            if self.pay_vacations_in_payroll:
                rules |= self.env['hr.salary.rule'].search([('code', 'in', ('VACDISFRUTADAS', 'VAC001', 'VAC002'))])
        elif process == 'vacaciones':
            rules = self.env['hr.salary.rule'].search([
                ('code', 'in', ['VACDISFRUTADAS', 'VACATIONS_MONEY', 'SSOCIAL001', 'SSOCIAL002',
                               'VAC001', 'VAC002', 'IBD', 'IBC_R', 'TOTALDEV', 'TOTALDED', 'NET'])
            ])
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
                rules = rules.filtered(lambda r: r.category_id.code not in ('BASIC', 'AUX'))
            if not self.novelties_payroll_concepts:
                rules = rules.filtered(lambda r: r.type_concepts != 'novedad')
        else: 
            # Proceso no estándar, usar reglas de la estructura
            rules = self.struct_id.rule_ids
            
        return rules | common_rules

    def _create_worked_line(self, work_entry_type_id, name, sequence, code, symbol, days, hours, 
                           contract_id, amount=None, days_aux=None, display_type='normal'):
        """
        Crea un diccionario para línea de días trabajados con soporte para display_type.
        
        Args:
            work_entry_type_id: ID del tipo de entrada de trabajo
            name: Nombre descriptivo
            sequence: Secuencia para ordenar
            code: Código identificador
            symbol: Símbolo (+ o -)
            days: Número de días
            hours: Número de horas
            contract_id: ID del contrato
            amount: Valor monetario (opcional)
            days_aux: Días para auxilio de transporte (opcional)
            display_type: Tipo de visualización ('normal', 'line_section', etc.)
            
        Returns:
            dict: Valores para la línea de días trabajados
        """
        line = {
            'work_entry_type_id': work_entry_type_id,
            'name': name,
            'sequence': sequence,
            'code': code,
            'symbol': symbol,
            'number_of_days': days,
            'number_of_hours': hours,
            'contract_id': contract_id,
            'display_type': display_type
        }
        
        # Agregar campos opcionales si están presentes
        if amount is not None:
            line['amount'] = amount
        
        if days_aux is not None:
            line['number_of_days_aux'] = days_aux
            # Calcular horas auxiliares proporcionales
            line['number_of_hours_aux'] = round(days_aux * hours / days) if days else 0
        
        return line

    # ==========================================================================
    # MÉTODOS PARA MANEJO DE DÍAS Y AUSENCIAS
    # ==========================================================================
    def _check_previously_paid_vacations(self, employee_id, date_from, date_to, current_payslip_id):
        """
        Verifica si hay vacaciones ya liquidadas en otras nóminas para este período.
        
        Args:
            employee_id: ID del empleado
            date_from: Fecha inicial
            date_to: Fecha final
            current_payslip_id: ID de la nómina actual
            
        Returns:
            List: IDs de ausencias de vacaciones ya pagadas
        """
        query = """
            SELECT DISTINCT l.leave_id
            FROM hr_leave_line l
            JOIN hr_leave h ON h.id = l.leave_id
            JOIN hr_leave_type t ON t.id = h.holiday_status_id
            JOIN hr_payslip p ON p.id = l.payslip_id
            WHERE h.employee_id = %s
            AND l.date BETWEEN %s AND %s
            AND l.payslip_id != %s
            AND p.state IN ('done', 'paid')
            AND t.is_vacation = TRUE 
            AND t.is_vacation_money = TRUE
        """
        self.env.cr.execute(query, (employee_id, date_from, date_to, current_payslip_id))
        
        return [r[0] for r in self.env.cr.fetchall()]

    def _get_previous_worked_days(self, payslip, date_from, date_to, contract_id):
        """
        Obtiene días trabajados en períodos previos para el mismo mes.
        Útil para nóminas quincenales o complementarias.
        
        Args:
            payslip: Registro de nómina
            date_from: Fecha inicial
            date_to: Fecha final 
            contract_id: ID del contrato
            
        Returns:
            dict: Información consolidada de días previos
        """
        # Determinamos rango de fechas previas a consultar
        month_start = date_utils.start_of(date_from, 'month')
        prev_from = month_start
        prev_to = date_from - timedelta(days=1)
        
        # Si no hay rango previo, retornar estructura vacía
        if prev_from > prev_to:
            return {
                'worked_days': 0,
                'permisos': 0,
                'out_days': 0,
                'absences': {}
            }
        
        # Consultar nóminas previas del mismo mes
        query = """
            SELECT
                SUM(wd.number_of_days) AS number_of_days,
                wd.symbol,
                hw.code,
                hw.name,
                hp.id as payslip_id
            FROM hr_payslip_worked_days wd
            INNER JOIN hr_payslip hp ON hp.id = wd.payslip_id
            LEFT JOIN hr_work_entry_type hw ON hw.id = wd.work_entry_type_id
            WHERE hp.contract_id = %s
                AND hp.id != %s
                AND hp.date_from >= %s
                AND hp.date_to <= %s
                AND hp.state IN ('done', 'paid')
                AND hp.struct_process IN ('vacaciones', 'nomina', 'contrato')
            GROUP BY wd.symbol, hw.code, hw.name, hp.id
            ORDER BY hw.code
        """
        params = (contract_id, payslip.id, prev_from, prev_to)
        
        # Ejecutar consulta y procesar resultados
        result = {
            'worked_days': 0,
            'permisos': 0,
            'out_days': 0,
            'absences': defaultdict(lambda: {'days': 0, 'name': ''})
        }
        
        db_manager = self._get_db_manager()
        query_result = db_manager.execute_query(
            query=query,
            params=params,
            show_notification=False,
            auto_translate=False
        )
        
        if query_result['status'] == 'success' and query_result['data']:
            for row in query_result['data']:
                number_of_days = row.get('number_of_days', 0) or 0
                symbol = row.get('symbol')
                code = row.get('code')
                name = row.get('name')
                
                # Clasificar según el tipo de línea
                if code == 'WORK100':
                    result['worked_days'] += number_of_days
                elif code == 'OUT':
                    result['out_days'] += number_of_days
                elif symbol == '-' and code not in ('WORK_D', 'PREV_PAYS'):
                    # Es una ausencia
                    result['absences'][code]['days'] += number_of_days
                    result['absences'][code]['name'] = name or code
        
        # Convertir defaultdict a diccionario normal
        result['absences'] = dict(result['absences'])
        return result

    def _calculate_day_values(self, date_value, end_date, all_leaves, apply_day_31=True):
        """
        Calcula valores para un día específico considerando casos especiales.
        
        Args:
            date_value: Fecha a evaluar
            end_date: Fecha final del período
            all_leaves: Lista de ausencias
            apply_day_31: Si se debe aplicar regla especial para día 31
            
        Returns:
            tuple: (días_valor, días_aux, día31_valor)
        """
        # Inicializar valores
        days_value = 0
        aux_value = 0
        day31_value = 0
        
        # Caso: Último día de febrero
        month_end = date_utils.end_of(date_value, 'month')
        if date_value.month == 2 and date_value.day == month_end.day:
            days_value = 1
            aux_value = 1
        
        # Caso: Día 31 sin ajuste especial
        elif date_value.day == 31 and not apply_day_31:
            days_value = 1
            aux_value = 1
        
        # Caso: Día 31 con ajuste especial
        elif date_value.day == 31:
            # Verificar si alguna ausencia aplica el día 31
            apply_day31_rule = any(
                leave.date_from.date() <= date_value <= leave.date_to.date() and 
                leave.holiday_status_id.apply_day_31 
                for leave in all_leaves
            )
            
            if apply_day31_rule:
                days_value = -1
                aux_value = -1
            else:
                day31_value = 1
        else:
            days_value = 1
            aux_value = 1
        return days_value, aux_value, day31_value

    def _create_virtual_absence_days(self, line, feb_last_day, year, days_to_complete, payslip_id):
        """
        Crea días virtuales de ausencia para completar febrero a 30 días.
        Estos días se crean en marzo para ausencias que cruzan de febrero a marzo.
        Args:
            line: Línea de ausencia
            feb_last_day: Último día de febrero (28 o 29)
            year: Año actual
            days_to_complete: Número de días virtuales a crear
            payslip_id: ID de la nómina
        Returns:
            bool: True si se crearon los días virtuales
        """
        if feb_last_day not in (28, 29):
            return False
            
        leave = line.leave_id
        leave_end_date = leave.date_to.date()
        if leave_end_date.month != 3:
            return False
        daily_amount = 0
        if line.days_payslip:
            daily_amount = line.amount / line.days_payslip
        virtual_lines = []
        for i in range(1, days_to_complete + 1):
            virtual_date = date(year, 3, i)
            if virtual_date > leave_end_date:
                continue
            vals = {
                'leave_id': leave.id,
                'date': virtual_date,
                'days_payslip': 1.0,
                'hours': line.hours / line.days_payslip if line.days_payslip else 0,
                'amount': daily_amount,
                'state': 'validated',
                'payslip_id': payslip_id,
                'days_work': 0,
                'days_holiday': 0,
                'days_31': 0,
                'days_holiday_31': 0,
                'is_virtual_day': True,
                'rule_id': line.rule_id.id if hasattr(line, 'rule_id') else False
            }
            virtual_lines.append(vals)
        if virtual_lines:
            self.env['hr.leave.line'].create(virtual_lines)
            return True
            
        return False

    def _process_absence(self, leave, absence_lines, leaves_worked_lines, date_value, permisos, 
                        worked_days, worked_aux_days, contract_id, 
                        payslip_struct=None, continues_from_prev_month=False, 
                        use_absence_type=True):
        """
        Procesa líneas de ausencia con soporte para política de cambio de mes.
        Args:
            leave: Registro de ausencia
            absence_lines: Líneas de ausencia para este día
            leaves_worked_lines: Diccionario para acumular líneas de ausencia
            date_value: Fecha actual
            permisos: Contador de permisos
            worked_days: Contador de días trabajados
            worked_aux_days: Contador de días auxiliares
            contract_id: ID del contrato
            payslip_struct: Estructura de nómina
            continues_from_prev_month: Si la ausencia continúa del mes anterior
            use_absence_type: Si se debe usar tipo de ausencia o como día trabajado
        Returns:
            tuple: (días_descontables, valor_días, permisos)
        """
        key = (leave.holiday_status_id.id, '-')
        discountable_days = 0
        days_value = 0
        for line in absence_lines:
            days_to_subtract = line.days_payslip
            hour_to_subtract = line.hours
            amount = line.amount
            if key not in leaves_worked_lines:
                leaves_worked_lines[key] = {
                    'work_entry_type_id': leave.holiday_status_id.work_entry_type_id.id,
                    'name': f"Días {leave.holiday_status_id.name.capitalize()}",
                    'sequence': 5,
                    'code': leave.holiday_status_id.code or 'LEAVE',
                    'symbol': '-',
                    'number_of_days': days_to_subtract,
                    'number_of_hours': hour_to_subtract,
                    'contract_id': contract_id,
                    'amount': amount,
                    'display_type': 'days'
                }
            else:
                leaves_worked_lines[key]['number_of_days'] += days_to_subtract
                leaves_worked_lines[key]['number_of_hours'] += hour_to_subtract
                leaves_worked_lines[key]['amount'] += amount
            if continues_from_prev_month and not use_absence_type:
                days_value += 1
                continue
            holiday_status = leave.holiday_status_id
            holiday_code = holiday_status.code or ''
            if holiday_status.novelty == 'p':
                permisos += days_to_subtract
            elif holiday_code == 'PERMISO_NO_DESCONTABLE':
                pass
            elif holiday_status.novelty == 'vco':
                days_value += 1
            elif holiday_code == 'INCAPACIDAD' and date_value.month == 2:
                is_paid_incapacity = leave.state == "paid"
                
                if is_paid_incapacity:
                    month_end = date_utils.end_of(date_value, 'month')
                    days_in_feb = month_end.day
                    if payslip_struct and hasattr(payslip_struct, 'schedule_pay') and payslip_struct.schedule_pay == 'bi-weekly':
                        is_second_half = date_value.day > 15
                        if is_second_half:
                            days_in_second_half = days_in_feb - 15
                            missing_days = 15 - days_in_second_half
                            if missing_days > 0:
                                days_value += missing_days
                                if not holiday_status.sub_not_aux:
                                    worked_aux_days += 1 - missing_days
                    else:
                        missing_days = 30 - days_in_feb
                        days_value += missing_days
                        if not holiday_status.sub_not_aux:
                            worked_aux_days += 1 - missing_days
            else:
                discountable_days += days_to_subtract
                if holiday_status.sub_not_aux:
                    worked_aux_days += 1 - days_to_subtract
                else:
                    days_value -= days_to_subtract 
        
        return discountable_days, days_value - permisos, permisos

    def _calculate_absences(self):
        """
        Calcula información de ausencias para la nómina.
        Integra detección de casos especiales como febrero y día 31.
        
        Returns:
            dict: Información detallada de ausencias y ajustes aplicados
        """
        self.ensure_one()
        absences_dict = {}
        leave_lines = self.env['hr.leave.line'].search([
            ('payslip_id', '=', self.id)
        ])
        if not leave_lines:
            return absences_dict
        for line in leave_lines:
            leave = line.leave_id
            if not leave or not hasattr(line, 'rule_id') or not line.rule_id:
                continue
            key = f"{leave.id}_{line.rule_id.id}"
            if key not in absences_dict:
                absences_dict[key] = {
                    'name': leave.name,
                    'leave_id': leave,
                    'rule_id': line.rule_id,
                    'leave_type': leave.holiday_status_id.name,
                    'date_from': line.date,
                    'date_to': line.date,
                    'total_days': 0,
                    'total_amount': 0,
                    'days_work': 0,
                    'days_holiday': 0,
                    'days_31': 0,
                    'days_holiday_31': 0,
                    'entity_id': hasattr(leave, 'entity') and leave.entity and leave.entity.id or False,
                    'february_adjustment': 0,
                    'day_31_adjustment': 0,
                    'is_virtual_day': False,
                    'day_details': []
                }
            else:
                absences_dict[key]['date_from'] = min(absences_dict[key]['date_from'], line.date)
                absences_dict[key]['date_to'] = max(absences_dict[key]['date_to'], line.date)
            absences_dict[key]['total_days'] += line.days_payslip
            absences_dict[key]['total_amount'] += line.amount
            absences_dict[key]['days_work'] += getattr(line, 'days_work', 0)
            absences_dict[key]['days_holiday'] += getattr(line, 'days_holiday', 0)
            absences_dict[key]['days_31'] += getattr(line, 'days_31', 0)
            absences_dict[key]['days_holiday_31'] += getattr(line, 'days_holiday_31', 0)
            absences_dict[key]['day_details'].append({
                'date': line.date,
                'days': line.days_payslip,
                'hours': line.hours,
                'amount': line.amount,
                'is_virtual': getattr(line, 'is_virtual_day', False),
                'days_work': getattr(line, 'days_work', 0),
                'days_holiday': getattr(line, 'days_holiday', 0),
                'days_31': getattr(line, 'days_31', 0),
                'days_holiday_31': getattr(line, 'days_holiday_31', 0)
            })
            if line.is_virtual_day:
                absences_dict[key]['is_virtual_day'] = True
        
        for key, data in absences_dict.items():
            data['day_details'] = sorted(data['day_details'], key=lambda x: x['date'])
            if data['date_to'].month == 2:
                month_end = date_utils.end_of(data['date_to'], 'month')
                if data['date_to'].day == month_end.day and not data['is_virtual_day']:
                    if data['leave_id'].date_to.date().month > 2:
                        data['february_adjustment'] = 30 - month_end.day
            if any(detail['date'].day == 31 for detail in data['day_details']):
                if data['leave_id'].holiday_status_id.apply_day_31:
                    data['day_31_adjustment'] = -1
        return absences_dict

    # ==========================================================================
    # CORE COMPUTATION METHODS
    # ==========================================================================
    def compute_unified_payroll_data(self, period_rules=None):
        """
        Método unificado para el cálculo de días trabajados y ausencias.
        Implementa todos los casos especificados en la documentación.
        Args:
            period_rules: Diccionario con reglas específicas del período (opcional)
        Returns:
            tuple: (líneas_trabajadas, localdict, ajustes_período)
        """
        period_rules = period_rules or {}
        period_adjustments = {
            'days_31': 0,
            'february': 0,
            'out_of_contract': 0
        }
        
        for payslip in self:
            payslip.leave_ids.unlink()
            payslip.payslip_day_ids.unlink()
            payslip.worked_days_line_ids = [(5, 0, 0)]
            contract = payslip.contract_id
            date_from = payslip.date_from
            date_to = payslip.date_to
            employee_id = payslip.employee_id.id
            month_start, month_end = date_utils.get_month(date_from)
            month_last_day = month_end.day
            is_full_month = (date_from.day == 1 and date_to.day == month_last_day)
            is_first_half = (date_from.day == 1 and date_to.day == 15)
            is_second_half = (date_from.day == 16 and date_to.day == month_last_day)
            annual_parameters = self.env['hr.annual.parameters'].search([('year', '=', date_to.year)], limit=1)
            if not annual_parameters:
                raise UserError(_("No se encontraron parámetros anuales para el año %s.") % date_to.year)
            w_hours = annual_parameters.hours_daily
            complete_february = period_rules.get('complete_february', annual_parameters.complete_february_to_30)
            month_change_policy = period_rules.get('month_change_policy', annual_parameters.month_change_policy)
            apply_day_31 = period_rules.get('apply_day_31', annual_parameters.apply_day_31)
            base_days = period_rules.get('base_days', 30)
            date_from_dt = datetime.combine(date_from, DATETIME_MIN)
            date_to_dt = datetime.combine(date_to, DATETIME_MAX)
            # Calcular salario diario
            current_wage_day = contract.wage / 30
            
            # Inicializar contadores y estructuras
            leaves_worked_lines = {}
            worked_days = 0
            worked_aux_days = 0
            worked30 = 0
            total_month_adjustment = 0
            
            # Variables de proceso
            hp_type = payslip.struct_process
            payslip_struct = payslip.struct_id
            is_liquidation = hp_type == 'contrato'
            ps_types = ['nomina', 'contrato']
            if not payslip.company_id.fragment_vac:
                ps_types.append('vacaciones')
            end_date = contract.date_end if is_liquidation and contract.date_end else date_to
            
            # Obtener tipos de entrada
            entry_types = self._get_entry_types()
            
            # ===================================================================
            # 1. DETECTAR CASOS ESPECIALES DE AJUSTE (FEBRERO Y DÍA 31)
            # ===================================================================
            
            # Caso especial: Febrero (completar a 30 días)
            is_feb = date_from.month == 2
            feb_last_day = 0
            
            if is_feb and complete_february and (is_full_month or is_second_half):
                feb_last_day = month_last_day
                days_to_complete = 30 - feb_last_day
                
                if days_to_complete > 0:
                    period_adjustments['february'] = days_to_complete
            
            # Caso especial: Día 31 (descontar según configuración)
            days31_to_subtract = 0
            day31_dates = []
            
            if apply_day_31 and not payslip.struct_id.regular_31:
                # Encontrar todos los días 31 en el período
                day31_dates = [
                    d for d in date_utils.date_range(date_from, date_to, step=relativedelta(days=1))
                    if d.day == 31
                ]
                days31_to_subtract = len(day31_dates)
                
                period_adjustments['days_31'] = days31_to_subtract
            
            # ===================================================================
            # 2. BUSCAR Y PROCESAR AUSENCIAS
            # ===================================================================
            
            # Buscar ausencias aplicables al período
            work_entries = self.env['hr.leave'].search([
                ('state', '=', 'validate'),
                ('date_to', '>=', date_from_dt),
                ('date_from', '<=', date_to_dt),
                ('employee_id', '=', employee_id),
            ])
            
            # Verificar vacaciones ya pagadas para evitar duplicidad
            previous_paid_vacations = self._check_previously_paid_vacations(
                employee_id, date_from_dt, date_to_dt, payslip.id
            )
            
            # Crear registros de ausencia
            leave_vals = []
            for leave in work_entries:
                # Saltar vacaciones ya pagadas
                if leave.holiday_status_id.is_vacation and leave.id in previous_paid_vacations:
                    continue
                    
                leave_vals.append({
                    'leave_id': leave.id,
                    'leave_type': leave.holiday_status_id.name,
                    'employee_id': employee_id,
                    'total_days': leave.number_of_days,
                    'payroll_id': payslip.id,
                })
            
            # Procesar líneas de ausencia
            all_absence_lines = []
            if leave_vals:
                leave_records = self.env['hr.absence.days'].create(leave_vals)
                all_leave_lines = leave_records.mapped('leave_id.line_ids').filtered(
                    lambda l: l.state == 'validated'
                )
                
                # Filtrar líneas dentro del período actual
                period_lines = all_leave_lines.filtered(
                    lambda l: date_from <= l.date <= date_to
                )
                
                # Limpiar líneas existentes
                existing_lines = self.env['hr.leave.line'].search([
                    ('payslip_id', '=', payslip.id)
                ])
                if existing_lines:
                    existing_lines.write({
                        'payslip_id': False
                    })
                
                # Separar vacaciones y ausencias regulares
                vacation_lines = period_lines.filtered(lambda l: l.leave_id.holiday_status_id.is_vacation)
                regular_absence_lines = period_lines - vacation_lines
                
                # Procesar vacaciones según configuración
                if vacation_lines:
                    money_lines = vacation_lines.filtered(
                        lambda l: l.leave_id.holiday_status_id.is_vacation_money
                    )
                    time_lines = vacation_lines - money_lines
                    
                    if payslip.company_id.fragment_vac:
                        # Solo procesar vacaciones dentro del período
                        vacation_relevant_lines = money_lines | time_lines.filtered(
                            lambda l: date_from <= l.date <= date_to
                        )
                    else:
                        # Procesar todas las vacaciones
                        vacation_relevant_lines = money_lines | time_lines
                    
                    if vacation_relevant_lines:
                        vacation_relevant_lines.write({
                            'payslip_id': payslip.id
                        })
                        all_absence_lines.extend(vacation_relevant_lines)
                
                # Procesar ausencias regulares
                if regular_absence_lines:
                    regular_absence_lines.write({
                        'payslip_id': payslip.id
                    })
                    all_absence_lines.extend(regular_absence_lines)
            
            # Agrupar ausencias por día para facilitar procesamiento
            absence_day_map = {}
            for line in all_absence_lines:
                if line.date not in absence_day_map:
                    absence_day_map[line.date] = []
                absence_day_map[line.date].append(line)
            
            # ===================================================================
            # 3. APLICAR REGLAS ESPECIALES A AUSENCIAS (FEBRERO Y DÍA 31)
            # ===================================================================
            
            # Regla especial para febrero: días virtuales para ausencias que cruzan mes
            feb_adjustment_applied_to_absence = False
            
            if is_feb and complete_february and (is_full_month or is_second_half) and month_change_policy == 'use_absence':
                days_to_complete = 30 - feb_last_day
                if days_to_complete > 0:
                    # Buscar ausencias en el último día de febrero que cruzan a marzo
                    feb_last_date = date(date_from.year, 2, feb_last_day)
                    cross_month_absences = []
                    
                    for line in absence_day_map.get(feb_last_date, []):
                        if line.leave_id.date_to.date().month > 2:
                            cross_month_absences.append(line)
                    
                    if cross_month_absences:
                        # Crear días virtuales para ausencias que cruzan
                        for line in cross_month_absences:
                            self._create_virtual_absence_days(
                                line, feb_last_day, date_from.year, days_to_complete, payslip.id
                            )
                        
                        feb_adjustment_applied_to_absence = True
                    else:
                        # Si no hay ausencias que cruzan, aplicar ajuste general
                        total_month_adjustment += days_to_complete
                        feb_adjustment_applied_to_absence = False
            elif is_feb and complete_february and (is_full_month or is_second_half):
                # Caso add_days: siempre aplicar ajuste general
                days_to_complete = 30 - feb_last_day
                if days_to_complete > 0:
                    total_month_adjustment += days_to_complete
            
            # Regla especial para día 31: distribuir ajuste en ausencias que cruzan
            day31_adjustment_applied_to_absence = False
            
            if days31_to_subtract > 0:
                has_cross_month_absences = False
                
                for d31 in day31_dates:
                    cross_month_absences = []
                    
                    # Verificar ausencias que cruzan al siguiente mes
                    for line in absence_day_map.get(d31, []):
                        next_month_date = date_utils.add(d31, months=1)
                        if line.leave_id.date_to.date().month == next_month_date.month:
                            cross_month_absences.append(line)
                    
                    if cross_month_absences:
                        has_cross_month_absences = True
                        # Distribuir el ajuste entre las ausencias
                        adjustment_per_absence = -1.0 / len(cross_month_absences)
                        
                        for line in cross_month_absences:
                            original_days = line.days_payslip
                            line.days_payslip += adjustment_per_absence  
                            if original_days:
                                line.hours = line.hours * (line.days_payslip / original_days)
                
                if not has_cross_month_absences:
                    # Ajuste general si no hay ausencias que cruzan
                    total_month_adjustment -= days31_to_subtract
                else:
                    day31_adjustment_applied_to_absence = True
            
            # ===================================================================
            # 4. PROCESAR DÍAS DÍA POR DÍA
            # ===================================================================
            
            # Inicializar resultados
            res = []
            
            # Solo procesar para tipos específicos de estructura
            if hp_type in ps_types or is_liquidation:
                period_days = (end_date - date_from).days + 1
                
                # Sección para días trabajados
                res.append({
                    'work_entry_type_id': entry_types['wdayst'].id, 
                    'name': 'TOTAL Días Trabajados', 
                    'sequence': 1, 
                    'code': 'SECTION',
                    'symbol': '', 
                    'number_of_days': period_days, 
                    'number_of_hours': period_days * w_hours, 
                    'contract_id': contract.id,
                    'display_type': 'line_section' 
                })
                
                # Obtener información de días previos
                prev_data = self._get_previous_worked_days(
                    payslip, date_from, date_to, contract.id
                )
                prev_worked = prev_data['worked_days']
                prev_permisos = prev_data['permisos']
                prev_out_days = prev_data['out_days']
                prev_absences = prev_data['absences']
                
                # Mostrar días previos si existen
                if prev_worked > 0 or prev_out_days > 0 or prev_absences:
                    # Título para días previos
                    res.append(self._create_worked_line(
                        entry_types['wdayst'].id, '(1) Liquidación Días Previos', 2, 'PREV_TITLE', 
                        '', 0, 0, contract.id, display_type='line_section'
                    ))
                    
                    # Días trabajados previos
                    if prev_worked > 0:
                        res.append(self._create_worked_line(
                            entry_types['prevdays'].id, 'Días Trabajados Previos', 3, 'PREV_WORK', '+',
                            prev_worked, prev_worked * w_hours, contract.id, display_type='days'
                        ))
                    
                    # Deducciones previas
                    if prev_out_days > 0:
                        res.append(self._create_worked_line(
                            entry_types['outdays'].id, 'Deducción Previa por Contrato', 3, 'PREV_OUT', '-',
                            prev_out_days, prev_out_days * w_hours, contract.id, display_type='days'
                        ))
                    
                    # Ausencias previas
                    for code, absence_info in prev_absences.items():
                        absence_type = self.env['hr.work.entry.type'].search([('code', '=', code)], limit=1)
                        
                        if absence_type:
                            res.append(self._create_worked_line(
                                absence_type.id, f"Ausencia: {absence_type.name}", 3, f"PREV_{code}", '-',
                                absence_info['days'], absence_info['days'] * w_hours, contract.id, display_type='days'
                            ))
                        else:
                            res.append(self._create_worked_line(
                                entry_types['outdays'].id, f"Ausencia: {absence_info['name']}", 3, 'PREV_AUS', '-',
                                absence_info['days'], absence_info['days'] * w_hours, contract.id, display_type='days'
                            ))
                
                # Título para período actual
                res.append(self._create_worked_line(
                    entry_types['wdayst'].id, '(2) Liquidación Período Actual', 4, 'CURR_TITLE', 
                    '', 0, 0, contract.id, display_type='line_section'
                ))
                
                # Procesar día por día
                date_tmp = date_from
                out_of_contract_days = 0
                discountable_absences = 0
                wb_permisos = 0
                
                # Iterar por cada día del período
                for date_tmp in date_utils.date_range(date_from, end_date):
                    is_within_contract = (contract.date_start <= date_tmp and 
                                         (not contract.date_end or contract.date_end >= date_tmp))
                    
                    if is_within_contract:
                        absence_lines = absence_day_map.get(date_tmp, [])
                        
                        if absence_lines:
                            # Procesar ausencias para este día
                            for absence_line in absence_lines:
                                leave = absence_line.leave_id
                                
                                # Verificar si continúa del mes anterior
                                continues_from_prev_month = leave.date_from.date().month != date_tmp.month
                                use_absence_type = month_change_policy == 'use_absence'
                                
                                discountable, days_value, wb_permisos = self._process_absence(
                                    leave, [absence_line], leaves_worked_lines, date_tmp, 
                                    wb_permisos, worked_days, worked_aux_days, contract.id,
                                    payslip_struct=payslip_struct,
                                    continues_from_prev_month=continues_from_prev_month,
                                    use_absence_type=use_absence_type
                                )
                                
                                discountable_absences += discountable
                                worked_days += days_value
                        else:
                            # Día normal sin ausencias
                            skip_day31 = date_tmp.day == 31 and apply_day_31 and not payslip.struct_id.regular_31
                            
                            if not skip_day31:
                                days_value, aux_value, day31_value = self._calculate_day_values(
                                    date_tmp, end_date, work_entries, apply_day_31
                                )
                                
                                worked_days += days_value
                                worked_aux_days += aux_value
                                worked30 += day31_value
                    else:
                        # Día fuera del contrato
                        out_of_contract_days += 1
                        period_adjustments['out_of_contract'] = out_of_contract_days
                
                # ===================================================================
                # 5. AÑADIR LÍNEAS DE RESULTADO
                # ===================================================================
                
                # Línea de días fuera de contrato
                if out_of_contract_days > 0:
                    desc = 'Deducción por inicio de contrato' if date_from < contract.date_start else 'Deducción por fin de contrato'
                    res.append(self._create_worked_line(
                        entry_types['outdays'].id, desc, 5, 'OUT', '-', 
                        out_of_contract_days, w_hours * out_of_contract_days, contract.id, display_type='days'
                    ))
                
                # Líneas de ausencias
                res.extend(leaves_worked_lines.values())
                
                # Calcular días efectivos trabajados
                effective_days = period_days - out_of_contract_days - discountable_absences
                
                # Aplicar ajustes especiales
                adjusted_effective_days = effective_days + total_month_adjustment
                adjusted_effective_days = round(adjusted_effective_days, 2)
                
                # Descripción para línea de días trabajados
                description = 'Días Trabajados'
                
                # Mostrar ajustes en la descripción
                adjustment_desc = []
                if is_feb and complete_february and (is_full_month or is_second_half):
                    days_to_complete = 30 - feb_last_day
                    if days_to_complete > 0:
                        adjustment_text = f"+{days_to_complete} FEB"
                        if feb_adjustment_applied_to_absence:
                            adjustment_text += " en ausencias"
                        adjustment_desc.append(adjustment_text)
                
                if days31_to_subtract > 0:
                    adjustment_text = f"-{days31_to_subtract} D31"
                    if day31_adjustment_applied_to_absence:
                        adjustment_text += " en ausencias"
                    adjustment_desc.append(adjustment_text)
                
                if adjustment_desc:
                    description = f"Días Trabajados ({', '.join(adjustment_desc)})"
                    
                # Línea de días trabajados
                res.append(self._create_worked_line(
                    entry_types['wdays'].id, description, 6, 'WORK100', '+',
                    adjusted_effective_days, adjusted_effective_days * w_hours,
                    contract.id, current_wage_day * adjusted_effective_days, worked_aux_days, display_type='days'
                ))
                
                # Línea para día 31 si aplica
                if apply_day_31 and payslip.struct_id.regular_31 and worked30 > 0:
                    res.append(self._create_worked_line(
                        entry_types['days31'].id, 'Día 31', 6, 'WORK131', '+',
                        worked30, worked30 * w_hours, contract.id, 
                        current_wage_day * worked30, worked30, display_type='days'
                    ))
            
            # Crear líneas de trabajo en la nómina
            worked_days_values = []
            for day_line in res:
                worked_days_values.append((0, 0, day_line))
            
            payslip.worked_days_line_ids = worked_days_values
            
            # Sincronizar modelos antes de calcular localdict
            self.flush_models_before_compute()
            
            # Preparar localdict para cálculos
            localdict = self._get_localdict(payslip)
            
            # Retornar resultados
            return res, localdict, period_adjustments

    def _get_localdict(self, payslip):
        """
        Crea el diccionario localdict optimizado con solo los datos esenciales.
        
        Args:
            payslip: Nómina para la que se crea el diccionario
            
        Returns:
            dict: Diccionario con datos esenciales para cálculos
        """
        # Información básica
        employee = payslip.employee_id
        contract = payslip.contract_id
        date_from = payslip.date_from
        date_to = payslip.date_to
        
        # Obtener parámetros anuales
        annual_parameters = self.env['hr.annual.parameters'].search([('year', '=', date_to.year)], limit=1)
        if not annual_parameters:
            raise UserError(_('Falta Configurar los parametros anuales para el año %s') % date_to.year)
        
        # Obtener valores de líneas existentes
        worked_days_dict = {line.code: line for line in payslip.worked_days_line_ids if line.code}
        inputs_dict = {line.code: line for line in payslip.input_line_ids if line.code}
        
        # Obtener variables económicas
        economic_variables = {
            'SMMLV': {date_to.year: round(annual_parameters.smmlv_monthly, PRECISION_TECHNICAL)},
            'SUB_TRANS': {date_to.year: round(annual_parameters.transportation_assistance_monthly, PRECISION_TECHNICAL)},
            'UVT': {date_to.year: round(annual_parameters.value_uvt, PRECISION_TECHNICAL)}
        }
        
        # Obtener políticas de cálculo
        politics = {
            'pays_sub_trans_train_prod': annual_parameters.top_max_transportation_assistance > 0,
            'eps_rate_employee': round(annual_parameters.value_porc_health_employee, PRECISION_TECHNICAL),
            'pen_rate_employee': round(annual_parameters.value_porc_pension_employee, PRECISION_TECHNICAL)
        }
        
        # Usar result_co si existe 
        previous_results = payslip._read_result_co() or {}
        
        # Estructuras virtuales para cálculos
        virtual_structures = {
            'absences_virtual': payslip._calculate_absences(),
            'rules_computed_virtual': previous_results,
            'categories_virtual': {},
            'accumulated_base': {
                'base_prima': 0.0,
                'base_cesantias': 0.0,
                'base_vacaciones': 0.0,
                'days_prima': 0,
                'days_cesantias': 0,
                'days_vacaciones': 0
            },
            'period_adjustments': {
                'days_31': payslip.adjustment_days_31,
                'february': payslip.adjustment_february,
                'out_of_contract': payslip.adjustment_out_of_contract
            },
            'cache_values': {
                'economic_vars': economic_variables,
            }
        }
        
        # Construir el diccionario final con utilidades y datos
        localdict = {
            # Objetos principales
            'employee': employee,
            'contract': contract,
            'payslip': payslip,
            
            # Fechas y períodos
            'date_from': date_from,
            'date_to': date_to,
            'date_utils': date_utils,
            
            # Parámetros y configuración
            'annual_parameters': annual_parameters,
            'economic_variables': economic_variables,
            'politics': politics,
            
            # Estructuras para cálculo
            'worked_days': WorkedDays(employee.id, worked_days_dict, self.env),
            'inputs': InputLine(employee.id, inputs_dict, self.env),
            
            # Funciones útiles
            'datetime': datetime,
            'date': date,
            'timedelta': timedelta,
            'relativedelta': relativedelta,
            'calendar': calendar,
            'compute_precise': self.compute_precise,
            'round': round,
            
            # Estado inicial
            'categories': BrowsableObject(employee.id, {}, self.env),
            'rules_computed': BrowsableObject(employee.id, {}, self.env),
            'rules': BrowsableObject(employee.id, {}, self.env),
            'result_rules': ResultRules(employee.id, {}, self.env),
            'result_rules_co': ResultRules_co(employee.id, {}, self.env),
            
            # Estructuras virtuales
            **virtual_structures
        }
        
        return localdict

    def _create_payslip_line(self, rule, amount, qty, rate, localdict, result_dict):
        """
        Crea línea de nómina y actualiza estructuras virtuales.
        
        Args:
            rule: Regla salarial
            amount: Valor unitario
            qty: Cantidad
            rate: Tasa
            localdict: Diccionario con variables locales
            result_dict: Diccionario donde almacenar el resultado
            
        Returns:
            dict: Valores para la línea de nómina
        """
        # Calcular total
        tot_rule = round(amount * qty * rate / 100.0)
        
        # Datos base de la línea
        vals = {
            'sequence': rule.sequence,
            'code': rule.code,
            'name': rule.name,
            'salary_rule_id': rule.id,
            'contract_id': localdict['contract'].id,
            'employee_id': localdict['employee'].id,
            'amount': amount,
            'quantity': qty,
            'rate': rate,
            'total': tot_rule,
            'slip_id': localdict['payslip'].id,
            'amount_technical': amount,
            'amount_display': round(amount),
            'total_display': round(tot_rule)
        }
        
        # Determinar tipo de visualización
        category = rule.category_id
        if category and hasattr(category, 'category_type') and category.category_type in ('provisions', 'totals'):
            vals['display_type'] = 'totals'
        elif rule.code in ('WORK100', 'WORK131'):
            vals['display_type'] = 'days'
        else:
            vals['display_type'] = 'normal'
        
        # Actualizar diccionario con valores virtuales
        self._sum_salary_rule_category(localdict, category, tot_rule)
        self._sum_salary_rule(localdict, rule, tot_rule)
        
        # Guardar línea en resultado
        result_dict[f"{rule.code}_{localdict['contract'].id}"] = vals
        
        return vals

    def _sum_salary_rule_category(self, localdict, category, amount):
        """Suma una cantidad a una categoría y sus padres en el localdict"""
        if not category:
            return localdict
            
        # Primero procesar categorías padre
        if category.parent_id:
            localdict = self._sum_salary_rule_category(localdict, category.parent_id, amount)
        
        # Inicializar si no existe
        if 'categories' not in localdict:
            localdict['categories'] = {}
        
        # Acumular en la estructura
        if hasattr(localdict['categories'], 'dict'):
            # BrowsableObject
            if category.code in localdict['categories'].dict:
                localdict['categories'].dict[category.code] += amount
            else:
                localdict['categories'].dict[category.code] = amount
        elif isinstance(localdict['categories'], dict):
            # Diccionario normal
            if category.code in localdict['categories']:
                localdict['categories'][category.code] += amount
            else:
                localdict['categories'][category.code] = amount
        
        # Acumular en categories_virtual
        if 'categories_virtual' not in localdict:
            localdict['categories_virtual'] = {}
            
        if category.code not in localdict['categories_virtual']:
            localdict['categories_virtual'][category.code] = amount
        else:
            localdict['categories_virtual'][category.code] += amount
        
        return localdict

    def _sum_salary_rule(self, localdict, rule, amount):
        """Suma una cantidad a una regla en el localdict"""
        # Inicializar si no existe
        if 'rules_computed' not in localdict:
            localdict['rules_computed'] = {}
        
        # Acumular en la estructura
        if hasattr(localdict['rules_computed'], 'dict'):
            # BrowsableObject
            localdict['rules_computed'].dict[rule.code] = localdict['rules_computed'].dict.get(rule.code, 0) + amount
        elif isinstance(localdict['rules_computed'], dict):
            # Diccionario normal
            if rule.code in localdict['rules_computed']:
                localdict['rules_computed'][rule.code] += amount
            else:
                localdict['rules_computed'][rule.code] = amount
        
        # Acumular en rules_computed_virtual
        if 'rules_computed_virtual' not in localdict:
            localdict['rules_computed_virtual'] = {}
        
        # Si es la primera vez que vemos esta regla, inicializar estructura completa
        if rule.code not in localdict['rules_computed_virtual']:
            localdict['rules_computed_virtual'][rule.code] = {
                'amount': amount,
                'quantity': 1.0,
                'rate': 100.0,
                'total': amount
            }
            
            # Agregar propiedades adicionales si existen
            for prop in ['base_seguridad_social', 'base_prima', 'base_cesantias', 
                        'base_vacaciones', 'base_vacaciones_dinero']:
                if hasattr(rule, prop) and getattr(rule, prop):
                    localdict['rules_computed_virtual'][rule.code][prop] = True
        else:
            # Actualizar valor
            localdict['rules_computed_virtual'][rule.code]['total'] = amount
        
        return localdict

    def _process_all_rules_and_concepts(self, payslip, localdict):
        """
        Procesa todas las reglas y conceptos de nómina.
        
        Args:
            payslip: Nómina a procesar
            localdict: Diccionario con variables locales
            
        Returns:
            list: Lista de líneas de nómina calculadas
        """
        result_dict = {}
        
        # Obtener sobreescrituras de reglas
        overrides = payslip._get_rule_overrides()
        
        # Obtener reglas a procesar
        rules = payslip._get_rules_to_process()
        
        # Ordenar reglas por secuencia
        rules = sorted(rules, key=lambda x: x.sequence)
        
        # Procesar cada regla
        for rule in rules:
            # Verificar si aplica la regla
            if rule._satisfy_condition(localdict):
                amount, qty, rate, name, log, data = rule._compute_rule_lavish(localdict)
                
                # Aplicar sobreescrituras si existen
                if rule.code in overrides:
                    override = overrides[rule.code]
                    if override['type'] == 'amount':
                        amount = override['value']
                    elif override['type'] == 'quantity':
                        qty = override['value']
                    elif override['type'] == 'rate':
                        rate = override['value']
                    elif override['type'] == 'total':
                        # Si se sobreescribe el total, calcular amount proporcionalmente
                        amount = override['value'] / (qty * rate / 100.0) if (qty * rate) != 0 else override['value']
                
                # Crear línea solo si hay valor
                tot_rule = amount * qty * rate / 100.0
                if not float_is_zero(tot_rule, precision_digits=2):
                    # Crear línea y actualizar diccionario
                    line_vals = self._create_payslip_line(rule, amount, qty, rate, localdict, result_dict)
                    
                    # Agregar datos adicionales para reglas especiales
                    if rule.code in ("PRIMA", "CESANTIAS", "INTCESANTIAS") or (rule.category_id and rule.category_id.code == 'PROV'):
                        if data:
                            line_vals.update({
                                'days_unpaid_absences': data.get('susp', 0),                        
                                'amount_base': data.get('base_periodo', 0),
                                'initial_accrual_date': data.get('date_from'),
                                'final_accrual_date': data.get('date_to'),
                                'computation': json.dumps(data.get('data_kpi', {}), default=json_serial),
                            })
        
        # Validar y ajustar totales
        result_list = list(result_dict.values())
        
        # Asegurar que NET = TOTALDEV - TOTALDED
        totaldev_line = next((line for line in result_list if line['code'] == 'TOTALDEV'), None)
        totalded_line = next((line for line in result_list if line['code'] == 'TOTALDED'), None)
        net_line = next((line for line in result_list if line['code'] == 'NET'), None)
        
        if totaldev_line and totalded_line and net_line:
            expected_net = round(totaldev_line['total'] - totalded_line['total'])
            
            if net_line['total'] != expected_net:
                # Corregir NET y ajustar alguna deducción menor para compensar
                net_line['total'] = expected_net
                net_line['total_display'] = expected_net
                
                # Encontrar una deducción pequeña para ajustar
                deduction_lines = [line for line in result_list 
                                  if line['total'] < 0 and line['code'] != 'TOTALDED']
                
                if deduction_lines:
                    # Ordenar por valor absoluto (menor primero)
                    deduction_to_adjust = sorted(deduction_lines, 
                                              key=lambda x: (abs(x['total']), x['sequence']))[0]
                    
                    # Calcular y aplicar ajuste
                    current_net = totaldev_line['total'] - totalded_line['total']
                    adjustment = expected_net - current_net
                    
                    deduction_to_adjust['total'] += adjustment
                    deduction_to_adjust['total_display'] = round(deduction_to_adjust['total'])
                    
                    # Actualizar total de deducciones
                    totalded_line['total'] = round(totaldev_line['total'] - expected_net)
                    totalded_line['total_display'] = totalded_line['total']
        
        return result_list

    # ==========================================================================
    # MÉTODOS DE ACCIÓN
    # ==========================================================================
    def compute_sheet(self):
        """Calcula todas las nóminas en el conjunto"""
        for payslip in self.filtered(lambda slip: slip.state not in ['cancel', 'done','paid']):
            # Verificar que tenga un período asignado
            if not payslip.period_id:
                period = self.env['hr.period'].search([
                    ('date_start', '<=', payslip.date_from),
                    ('date_end', '>=', payslip.date_to),
                    ('closed', '=', False)
                ], limit=1)
                
                if period:
                    payslip.period_id = period.id
                else:
                    raise UserError(_("Debe seleccionar un período para la nómina de %s") % payslip.employee_id.name)
            
            # Calcular la nómina
            payslip.compute_slip()
        return True

    def compute_slip(self):
        """Calcula una nómina individual"""
        self_ids = tuple(self._ids)
        if not self_ids:
            return True
            
        # Sincronizar modelos
        self.flush_models_before_compute()
        
        # Obtener datos básicos de nóminas
        db_manager = self._get_db_manager()
        query = """
            SELECT id, struct_id, date_from, date_to, contract_id, employee_id, 
                struct_process, date_liquidacion, pay_primas_in_payroll, 
                pay_cesantias_in_payroll, number, period_id
            FROM hr_payslip
            WHERE id IN %s AND state IN ('draft', 'verify')
        """
        result = db_manager.execute_query(query, [self_ids])
        slips_data = result['data'] if result['status'] == 'success' else []
        
        if not slips_data:
            return True
            
        # Procesar cada nómina
        today = fields.Date.today()
        for slip_data in slips_data:
            # Obtener registro completo
            payslip = self.browse(slip_data['id'])
            
            # Actualizar fechas según proceso
            self._update_dates(payslip, slip_data)
            
            # Verificar duplicidad
            if self._check_duplicate_slip(slip_data):
                raise UserError(
                    _("No puede existir más de una nómina del mismo tipo y periodo para el empleado %s") 
                    % payslip.employee_id.name
                )
                
            # Actualizar nombre y estado
            name = f"Nomina de {payslip.contract_id.name}"
            payslip.write({
                'name': name,
                'state': 'verify',
                'compute_date': today
            })
            
            # Limpiar datos previos
            self._clean_previous_data(payslip)
            
            # Obtener reglas de período
            period_rules = {}
            if payslip.period_id:
                period_rules = payslip.period_id.get_period_rules()
            
            # Calcular líneas de nómina
            try:
                start_time = fields.Datetime.now()
                
                # Calcular días trabajados y localdict
                worked_days_lines, localdict, period_adjustments = payslip.compute_unified_payroll_data(period_rules)
                
                # Procesar reglas salariales
                payslip_lines
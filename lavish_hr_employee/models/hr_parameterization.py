from odoo import models, fields, api, _
from datetime import datetime, timedelta, date
from dateutil.relativedelta import relativedelta
import calendar
from odoo.exceptions import UserError, ValidationError
import time
from odoo.tools.safe_eval import safe_eval
import json
from odoo.tools.float_utils import float_round
import logging
_logger = logging.getLogger(__name__)
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from collections import defaultdict
from odoo.tools import format_date, formatLang, frozendict, date_utils

from decimal import Decimal, getcontext,ROUND_HALF_UP
getcontext().prec = 10 
DAYS_YEAR = 360
DAYS_YEAR_NATURAL= 365
DAYS_MONTH = 30
PRECISION_TECHNICAL = 10
PRECISION_DISPLAY = 0
DATETIME_MIN = datetime.min.time()
DATETIME_MAX = datetime.max.time()
HOURS_PER_DAY = 8 #Solo pór si no ponen las horas en parametros anuales, para nominas simple no suma ni resta 

def monthrange(year=None, month=None):
    today = datetime.today()
    y = year or today.year
    m = month or today.month
    return y, m, calendar.monthrange(y, m)[1]

def get_days_in_months():
    """
    Genera una lista con el número de días en cada mes, considerando los años bisiestos.
    
    Returns:
        list: Lista con el número de días en cada mes.
    """
    days_in_months = [0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    
    # Ajustar el número de días en febrero para años bisiestos
    days_in_months[2] = 29 if calendar.isleap(datetime.now().year) else 28
    
    return days_in_months

def format_currency(value):
    """
    Formatea un número como una cadena de texto con formato de moneda.
    """
    return "${:,.2f}".format(value)

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
tabla_retencion = [
    (0, 95, 0, 0, 0),
    (95, 150, 19, 95, 0),
    (150, 360, 28, 150, 10),
    (360, 640, 33, 360, 69),
    (640, 945, 35, 640, 162),
    (945, 2300, 37, 945, 268),
    (2300, float('inf'), 39, 2300, 770)
]
@staticmethod
def round_1_decimal(value):
    """Redondea a 1 decimal."""
    return float(Decimal(str(value)).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP))
class ProvisionHTMLBuilder:
    """
    Constructor de HTML para informes de provisiones
    """
    def __init__(self, provision_type):
        self.provision_type = provision_type
        self.nombres = {
            'vacaciones': 'VACACIONES',
            'prima': 'PRIMA DE SERVICIOS',
            'cesantias': 'CESANTÍAS',
            'intereses': 'INTERESES SOBRE CESANTÍAS'
        }
        self.formulas = {
            'vacaciones': 'Base × 4.17%',
            'prima': 'Base × 8.33%',
            'cesantias': 'Base × 8.33%',
            'intereses': 'Base Cesantías × 12%'
        }
        
        self.nombre = self.nombres.get(provision_type, provision_type.upper())
        self.formula = self.formulas.get(provision_type, '')
        
        self.partes = []
        
        # Iniciar el HTML con los estilos y cabecera - NOTA: escapamos las llaves de CSS
        self.partes.append("""
        <div class="provision-detail">
            <style>
                .provision-detail {{ font-family: Arial, sans-serif; }}
                .text-end {{ text-align: right; }}
                .table {{ width: 100%; margin-bottom: 1rem; color: #212529; border-collapse: collapse; }}
                .table-sm td, .table-sm th {{ padding: 0.3rem; }}
                .table-secondary {{ background-color: #e2e3e5; }}
                .row {{ display: flex; flex-wrap: wrap; }}
                .col {{ flex: 1 0 0%; padding: 0 15px; }}
                .alert-info {{ color: #0c5460; background-color: #d1ecf1; border-color: #bee5eb; padding: 0.75rem 1.25rem; margin-bottom: 1rem; border: 1px solid transparent; border-radius: 0.25rem; }}
                .alert-warning {{ color: #856404; background-color: #fff3cd; border-color: #ffeeba; padding: 0.75rem 1.25rem; margin-bottom: 1rem; border: 1px solid transparent; border-radius: 0.25rem; }}
                .bg-white {{ background-color: #fff; }}
                .p-3 {{ padding: 1rem; }}
                .mb-3 {{ margin-bottom: 1rem; }}
                .mt-3 {{ margin-top: 1rem; }}
                .border {{ border: 1px solid #dee2e6; }}
                .rounded {{ border-radius: 0.25rem; }}
                .bg-light {{ background-color: #f8f9fa; }}
                .text-primary {{ color: #007bff; }}
                .text-success {{ color: #28a745; }}
                .badge {{ display: inline-block; padding: 0.25em 0.4em; font-size: 75%; font-weight: 700; line-height: 1; text-align: center; white-space: nowrap; vertical-align: baseline; border-radius: 0.25rem; }}
                .badge-primary {{ color: #fff; background-color: #007bff; }}
                .badge-success {{ color: #fff; background-color: #28a745; }}
                .badge-warning {{ color: #212529; background-color: #ffc107; }}
                .border-4 {{ border-width: 4px; }}
                .border-primary {{ border-color: #007bff; }}
                .border-success {{ border-color: #28a745; }}
                .shadow-sm {{ box-shadow: 0 .125rem .25rem rgba(0,0,0,.075); }}
                .list-group {{ display: flex; flex-direction: column; padding-left: 0; margin-bottom: 0; border-radius: 0.25rem; }}
                .list-group-item {{ position: relative; display: block; padding: 0.75rem 1.25rem; background-color: #fff; border: 1px solid rgba(0,0,0,.125); }}
            </style>
            <h4>CÁLCULO DE PROVISIÓN DE {0}</h4>
        """.format(self.nombre))
    
    def add_days_info(self, dias_trabajados, dias_ausencias, dias_suspension):
        """Añade información de días"""
        dias_computables = dias_trabajados + dias_ausencias - dias_suspension
        
        self.partes.append("""
        <div class="p-3 mb-3 bg-light rounded border">
            <h5 class="text-primary">INFORMACIÓN DE DÍAS:</h5>
            <table class="table table-sm">
                <tr>
                    <td>Días trabajados:</td>
                    <td class="text-end">{0}</td>
                </tr>
                <tr>
                    <td>Días de ausencia remunerada:</td>
                    <td class="text-end">{1}</td>
                </tr>
        """.format(dias_trabajados, dias_ausencias))
        
        if dias_suspension > 0:
            self.partes.append("""
                <tr>
                    <td>Días de suspensión (no remunerados):</td>
                    <td class="text-end">{0}</td>
                </tr>
            """.format(dias_suspension))
        
        self.partes.append("""
                <tr>
                    <td><strong>Total días computables:</strong></td>
                    <td class="text-end"><strong>{0}</strong></td>
                </tr>
            </table>
        </div>
        """.format(dias_computables))
        
        return self
    
    def add_formula_info(self):
        """Añade información de la fórmula aplicada"""
        self.partes.append("""
        <div class="p-3 mb-3 bg-light rounded border">
            <h5 class="text-primary">FÓRMULA APLICADA:</h5>
            <div class="alert alert-info">
                <i class="fa fa-calculator"></i> {0}
            </div>
        </div>
        """.format(self.formula))
        
        return self
    
    def add_base_concepts(self, base_salario, auxilio_transporte, conceptos_incluidos):
        """Añade información de los conceptos base"""
        self.partes.append("""
        <div class="p-3 mb-3 bg-white rounded shadow-sm border">
            <h5 class="text-primary">CONCEPTOS INCLUIDOS EN LA BASE:</h5>
            <table class="table table-sm">
                <thead>
                    <tr>
                        <th>CONCEPTO</th>
                        <th class="text-end">VALOR</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td>SALARIO BASE</td>
                        <td class="text-end">${0:,.2f}</td>
                    </tr>
        """.format(base_salario))
        
        # Auxilio de transporte solo se incluye para prima, cesantías e intereses
        if auxilio_transporte > 0 and self.provision_type != 'vacaciones':
            self.partes.append("""
                    <tr>
                        <td>AUXILIO DE TRANSPORTE</td>
                        <td class="text-end">${0:,.2f}</td>
                    </tr>
            """.format(auxilio_transporte))
        
        # Añadir otros conceptos base
        for concepto in conceptos_incluidos:
            self.partes.append("""
                    <tr>
                        <td>{0}</td>
                        <td class="text-end">${1:,.2f}</td>
                    </tr>
            """.format(concepto['nombre'].upper(), concepto['valor']))
        
        # Total base
        base_total = base_salario
        if self.provision_type != 'vacaciones':
            base_total += auxilio_transporte
        base_total += sum(c['valor'] for c in conceptos_incluidos)
        
        self.partes.append("""
                    <tr class="table-secondary">
                        <th>TOTAL BASE</th>
                        <th class="text-end">${0:,.2f}</th>
                    </tr>
                </tbody>
            </table>
        </div>
        """.format(base_total))
        
        return self, base_total
    
    def add_intereses_note(self):
        """Añade nota específica para intereses de cesantías"""
        if self.provision_type == 'intereses':
            self.partes.append("""
            <div class="alert alert-warning mb-3">
                <strong>Nota:</strong> Los intereses se calculan como el 12% del valor de cesantías.
            </div>
            """)
        return self
    
    def add_result(self, base_total, tasa, valor_provision, saldo_contable=None, valor_liquidacion=None):
        """Añade información del resultado de la provisión"""
        self.partes.append("""
        <div class="p-3 mb-3 bg-light rounded border border-success">
            <h5 class="text-success">RESULTADO DE LA PROVISIÓN:</h5>
            <table class="table table-sm">
                <tr>
                    <td>Base total:</td>
                    <td class="text-end">${0:,.2f}</td>
                </tr>
                <tr>
                    <td>Tasa de provisión:</td>
                    <td class="text-end">{1}%</td>
                </tr>
                <tr class="table-secondary">
                    <th>VALOR PROVISIÓN:</th>
                    <th class="text-end">${2:,.2f}</th>
                </tr>
        """.format(base_total, tasa, valor_provision))
        
        # Añadir información contable si está disponible
        if saldo_contable is not None:
            self.partes.append("""
                <tr>
                    <td>Saldo contable acumulado:</td>
                    <td class="text-end">${0:,.2f}</td>
                </tr>
            """.format(saldo_contable))
        
        # Añadir valor a pagar si es liquidación
        if valor_liquidacion is not None and valor_liquidacion > 0:
            self.partes.append("""
                <tr>
                    <td><strong>Valor a pagar en liquidación:</strong></td>
                    <td class="text-end text-primary"><strong>${0:,.2f}</strong></td>
                </tr>
            """.format(valor_liquidacion))
            
            # Calcular ajuste necesario
            if saldo_contable is not None:
                ajuste = valor_liquidacion - saldo_contable
                self.partes.append("""
                <tr>
                    <td><strong>Ajuste necesario:</strong></td>
                    <td class="text-end {0}">${1:,.2f}</td>
                </tr>
                """.format(
                    "text-success" if ajuste >= 0 else "text-danger", 
                    abs(ajuste)
                ))
        
        self.partes.append("""
            </table>
        </div>
        """)
        
        return self
    
    def generate(self):
        """Genera el HTML completo"""
        self.partes.append('</div>')
        return ''.join(self.partes)
    
class AccountAccount(models.Model):
    _inherit = 'account.account'
    
    payroll_concept = fields.Boolean(string='Aplica Concepto de nómina', default=False, help='Indica si esta cuenta se puede usar en los conceptos, para evitar mostrar todo el plan de cuenta')

#Tabla de tipos de empleados
class hr_types_employee(models.Model):
    _name = 'hr.types.employee'
    _description = 'Tipos de empleado'

    code = fields.Char('Código',required=True)
    name = fields.Char('Nombre',required=True)

    _sql_constraints = [('change_code_uniq', 'unique(code)', 'Ya existe un tipo de empleado con este código, por favor verificar')]

#Tabla de tiesgos profesionales
class hr_contract_risk(models.Model):
    _name = 'hr.contract.risk'
    _description = 'Riesgos profesionales'

    code = fields.Char('Codigo', size=10, required=True)
    name = fields.Char('Nombre', size=100, required=True)
    percent = fields.Float('Porcentaje', digits=(12,3), required=True, help='porcentaje del riesgo profesional')
    date = fields.Date('Fecha vigencia')

    _sql_constraints = [('change_code_uniq', 'unique(1=1)', 'Ya existe un riesgo con este código, por favor verificar')]  

class lavish_economic_activity_level_risk(models.Model):
    _name = 'lavish.economic.activity.level.risk'
    _description = 'Actividad económica por nivel de riesgo'

    risk_class_id = fields.Many2one('hr.contract.risk','Clase de riesgo', required=True)
    code_ciiu_id = fields.Many2one('lavish.ciiu','CIIU', required=True)
    code = fields.Char('Código', required=True)
    name = fields.Char('Descripción', required=True)

    _sql_constraints = [('economic_activity_level_risk_uniq', 'unique(risk_class_id,code_ciiu_id,code)', 'Ya existe un riesgo con este código, por favor verificar')]

    def name_get(self):
        result = []
        for record in self:
            result.append((record.id, "{}{}{} | {}".format(record.risk_class_id.code, record.code_ciiu_id.code, record.code, record.code_ciiu_id.name)))
        return result

#Tabla tipos de entidades
class hr_contrib_register(models.Model):
    _name = 'hr.contribution.register'
    _description = 'Tipo de Entidades'
    
    name = fields.Char('Nombre', required=True)
    type_entities = fields.Selection([('none', 'No aplica'),
                             ('eps', 'Entidad promotora de salud'),
                             ('pension', 'Fondo de pensiones'),
                             ('cesantias', 'Fondo de cesantias'),
                             ('caja', 'Caja de compensación'),
                             ('riesgo', 'Aseguradora de riesgos profesionales'),
                             ('sena', 'SENA'),
                             ('icbf', 'ICBF'),
                             ('solidaridad', 'Fondo de solidaridad'),
                             ('subsistencia', 'Fondo de subsistencia')], 'Tipo', required=True)
    note = fields.Text('Description')

    _sql_constraints = [('change_name_uniq', 'unique(name)', 'Ya existe un tipo de entidad con este nombre, por favor verificar')]         

#Tabla de entidades
class hr_employee_entities(models.Model):
    _name = 'hr.employee.entities'
    _description = 'Entidades empleados'

    partner_id = fields.Many2one('res.partner', 'Entidad', help='Entidad relacionada')
    name = fields.Char(related="partner_id.name", readonly=True,string="Nombre")
    business_name = fields.Char(related="partner_id.business_name", readonly=True,string="Nombre de negocio")
    types_entities = fields.Many2many('hr.contribution.register',string='Tipo de entidad')
    code_pila_eps = fields.Char('Código PILA')
    code_pila_ccf = fields.Char('Código PILA para CCF')
    code_pila_regimen = fields.Char('Código PILA Regimen de excepción')
    code_pila_exterior = fields.Char('Código PILA Reside en el exterior')
    order = fields.Selection([('territorial', 'Orden Terrritorial'),
                             ('nacional', 'Orden Nacional')], 'Orden de la entidad')
    debit_account = fields.Many2one('account.account', string='Cuenta débito', company_dependent=True)
    credit_account = fields.Many2one('account.account', string='Cuenta crédito', company_dependent=True)
    _sql_constraints = [('change_partner_uniq', 'unique(partner_id)', 'Ya existe una entidad asociada a este tercero, por favor verificar')]         

    def name_get(self):
        result = []
        for record in self:
            if record.partner_id.business_name: 
                result.append((record.id, "{}".format(record.partner_id.business_name)))
            else: 
                result.append((record.id, "{}".format(record.partner_id.name)))
        return result

#Categorias reglas salariales herencia

class HrCategoriesSalaryRules(models.Model):
    _inherit = 'hr.salary.rule.category'
    _description = 'Categorías de Reglas Salariales'
    _order = 'sequence, id'

    group_payroll_voucher = fields.Boolean(
        string='Agrupar comprobante de nómina',
        help='Si está marcado, las reglas salariales de esta categoría se agruparán en el comprobante de nómina'
    )
    sequence = fields.Integer(
        tracking=True,
        help='Secuencia para determinar el orden de las categorías'
    )
    active = fields.Boolean(
        string='Activo',
        default=True,
        help='Si está desmarcado, esta categoría se ocultará pero no se eliminará'
    )
    category_type = fields.Selection([
       ('basic', 'Salario Básico'),
       ('earnings', 'Devengos Salariales'),
       ('earnings_non_salary', 'Devengos No Salariales'),
       ('o_rights', 'Otros Derechos'),
       ('benefits', 'Prestaciones Sociales'),
       ('additional', 'Complementarios'),
       ('non_taxed_earnings', 'Ingresos No Gravados'),
       ('deductions', 'Deducciones'),
       ('contributions', 'Aportes'),
       ('provisions', 'Provisiones'),
       ('totals', 'Totales'),
       ('other', 'Otros')
    ], string='Tipo de Categoría', help='Tipo funcional de la categoría para cálculos automatizados')
   
    def toggle_active(self):
        for record in self:
            record.active = not record.active
            
#Contabilización reglas salariales
class hr_salary_rule_accounting(models.Model):
    _name ='hr.salary.rule.accounting'
    _description = 'Contabilización reglas salariales'    

    salary_rule = fields.Many2one('hr.salary.rule', string = 'Regla salarial')
    department = fields.Many2one('hr.department', string = 'Departamento')
    company = fields.Many2one('res.company', string = 'Compañía')
    work_location = fields.Many2one('res.partner', string = 'Ubicación de trabajo')
    third_debit = fields.Selection([('entidad', 'Entidad'),
                                    ('compañia', 'Compañia'),
                                    ('empleado', 'Empleado')], string='Tercero débito') 
    third_credit = fields.Selection([('entidad', 'Entidad'),
                                    ('compañia', 'Compañia'),
                                    ('empleado', 'Empleado')], string='Tercero crédito')
    debit_account = fields.Many2one('account.account', string = 'Cuenta débito', company_dependent=True)
    credit_account = fields.Many2one('account.account', string = 'Cuenta crédito', company_dependent=True)

#Estructura Salariales - Herencia
class hr_payroll_structure(models.Model):
    _inherit = 'hr.payroll.structure'

    @api.model
    def _get_default_rule_ids(self):
        default_rules = []
        if self.country_id.code == 'CO':
            if self.process == 'prima':
                # Añade las reglas para 'primas'
                default_rules.append((0, 0, {
                    # Detalles de la regla para 'primas'
                }))
            elif self.process == 'vacaciones':
                # Añade las reglas para 'nomina base'
                default_rules.append((0, 0, {
                    # Detalles de la regla para 'nomina base'
                }))
            elif self.process == 'cesantias':
                # Añade la regla para 'cesantias'
                default_rules.append((0, 0, {
                    'name': _('Cesantias'),
                    'sequence': 1,
                    'code': 'CESANTIAS',
                    'category_id': self.env.ref('lavish_hr_employee.PRESTACIONES_SOCIALES').id,
                    'condition_select': 'python',
                    'condition_python': 'result = payslip.get_salary_rule(\'CESANTIAS\',employee.type_employee.id)',
                    'amount_select': 'code',
                    'amount_python_compute': """
                        result = 0.0
                        obj_salary_rule = result
                        if obj_salary_rule:
                            date_start = payslip.date_from
                            date_end = payslip.date_to
                            if inherit_contrato != 0:
                                date_start = payslip.date_cesantias
                                date_end = payslip.date_liquidacion
                            accumulated = payslip.get_accumulated_cesantias(date_start,date_end) + values_base_cesantias
                            result = accumulated""",
                }))
        return default_rules

    process = fields.Selection([('nomina', 'Nónima'),
                                ('vacaciones', 'Vacaciones'),
                                ('prima', 'Prima'),
                                ('cesantias', 'Cesantías'),
                                ('intereses_cesantias', 'Intereses de cesantías'),
                                ('contrato', 'Liq. de Contrato'),
                                ('otro', 'Otro')], string='Proceso')
    regular_pay = fields.Boolean('Pago standar')
    regular_31 = fields.Boolean('Pago Dia 31')
    rule_ids = fields.One2many(
        'hr.salary.rule', 'struct_id',
        string='Salary Rules', default=_get_default_rule_ids)

    @api.onchange('regular_pay')
    def onchange_regular_pay(self):
        for record in self:
            record.process = 'nomina' if record.regular_pay == True else False  
  
    @api.onchange('process')
    def _onchange_process(self):
        # Solo cambia las reglas si el registro no ha sido guardado todavía
        if not self._origin:
            self.rule_ids = self._get_default_rule_ids()
#Tipos entradas de trabajo - Herencia
class hr_work_entry_type(models.Model):
    _name = 'hr.work.entry.type'
    _inherit = ['hr.work.entry.type','mail.thread', 'mail.activity.mixin']

    code = fields.Char(tracking=True)
    sequence = fields.Integer(tracking=True)
    round_days = fields.Selection(tracking=True)
    round_days_type = fields.Selection(tracking=True)
    is_leave = fields.Boolean(tracking=True)
    is_unforeseen = fields.Boolean(tracking=True)

class hr_salary_rule(models.Model):
    _name = 'hr.salary.rule'
    _inherit = ['hr.salary.rule','mail.thread', 'mail.activity.mixin']

    #Trazabilidad
    struct_id = fields.Many2one(tracking=True)
    active = fields.Boolean(tracking=True)
    sequence = fields.Integer(tracking=True)
    condition_select = fields.Selection(tracking=True)
    amount_select = fields.Selection(tracking=True)
    amount_python_compute = fields.Text(tracking=True)
    appears_on_payslip = fields.Boolean(tracking=True)
    proyectar_nom = fields.Boolean('Proyectar en nomina')
    proyectar_ret = fields.Boolean('Proyectar en Retencion')
    #Campos lavish
    types_employee = fields.Many2many('hr.types.employee',string='Tipos de Empleado', tracking=True)
    dev_or_ded = fields.Selection([('devengo', 'Devengo'),
                                     ('deduccion', 'Deducción')],'Naturaleza', tracking=True)
    type_concepts = fields.Selection([('contrato', 'Fijo Contrato'),
                                     ('ley', 'Por Ley'),
                                     ('novedad', 'Novedad Variable'),
                                     ('prestacion', 'Prestación Social'),
                                     ('tributaria', 'Deducción Tributaria')],'Tipo', required=True, default='contrato', tracking=True)
    aplicar_cobro = fields.Selection([('15','Primera quincena'),
                                        ('30','Segunda quincena'),
                                        ('0','Siempre')],'Aplicar cobro', tracking=True)
    modality_value = fields.Selection([('fijo', 'Valor fijo'),
                                       ('diario', 'Valor diario'),
                                       ('diario_efectivo', 'Valor diario del día efectivamente laborado')],'Modalidad de valor', tracking=True)
    deduction_applies_bonus = fields.Boolean('Aplicar deducción en Prima', tracking=True)
    account_tax_id = fields.Many2one("account.tax", "Impuesto de Retefuente Laboral")
    #Es incapacidad / deducciones
    amount_select = fields.Selection(
        selection_add=[
            ('concept', 'Concept Code')
        ], 
        ondelete={
            'concept': 'set default'
        }
    )
    is_leave = fields.Boolean('Es Ausencia', tracking=True)
    is_recargo = fields.Boolean('Es Recargos', tracking=True)
    deduct_deductions = fields.Selection([('all', 'Todas las deducciones'),
                                          ('law', 'Solo las deducciones de ley')],'Tener en cuenta al descontar', default='all', tracking=True)
    rounding_method = fields.Selection([
        ('no_round', 'Sin redondeo'),
        ('round1', 'Redondear a entero'),
        ('round100', 'Redondear al 100 más cercano'),
        ('round1000', 'Redondear al 1000 más cercano'),
        ('round2d', 'Redondear a 2 decimales')
    ], string='Método de redondeo', default='no_round', 
       help="Seleccione el método de redondeo para aplicar al resultado de esta regla salarial.")




    restart_one_month_prima = fields.Boolean('Restar 1 mes al promedio de los acumulados en prima', tracking=True)
    liquidar_con_base = fields.Boolean('Liquidar con IBC mes anterior', tracking=True)
    base_prima = fields.Boolean('Para prima', tracking=True)
    base_cesantias = fields.Boolean('Para cesantías', tracking=True)
    base_vacaciones = fields.Boolean('Para vacaciones tomadas', tracking=True)
    base_vacaciones_dinero = fields.Boolean('Para vacaciones dinero', tracking=True)
    base_intereses_cesantias = fields.Boolean('Para intereses de cesantías', tracking=True)
    base_auxtransporte_tope = fields.Boolean('Para tope de auxilio de transporte', tracking=True)
    base_compensation = fields.Boolean('Para liquidación de indemnización', tracking=True)
    #Base de Seguridad Social
    base_seguridad_social = fields.Boolean('Para seguridad social', tracking=True)
    base_arl = fields.Boolean('Para seguridad social', tracking=True)
    base_parafiscales = fields.Boolean('Para parafiscales', tracking=True)
    excluir_ret = fields.Boolean('excluir de Calculo retefuente', tracking=True)
    is_projectable_rtf = fields.Boolean(
        string='Proyectable para Retención / Fondos',
        default=False,
        help='Indica si este concepto debe ser proyectado en el cálculo de retención en la fuente'
    )

    descontar_suspensiones = fields.Boolean('Descontar Licencia No remuneradas', tracking=True)
    salary_rule_accounting = fields.One2many('hr.salary.rule.accounting', 'salary_rule', string="Contabilización", tracking=True)
    #Reportes
    display_days_worked = fields.Boolean(string='Mostrar la cantidad de días trabajados en los formatos de impresión', tracking=True)
    short_name = fields.Char(string='Nombre corto/reportes')
    process = fields.Selection([('nomina', 'Nónima'),
                                ('vacaciones', 'Vacaciones'),
                                ('prima', 'Prima'),
                                ('cesantias', 'Cesantías'),
                                ('intereses_cesantias', 'Intereses de cesantías'),
                                ('contrato', 'Liq. de Contrato'),
                                ('otro', 'Otro')], string='Proceso')
    novedad_ded = fields.Selection([('cont', 'Contrato'),
                                    ('Noved', 'Novedad'),
                                    ('0', 'No'),],'Opcion de Novedad', tracking=True)
    not_include_flat_payment_file = fields.Boolean(string='No incluir en archivo plano de pagos')
    #Empleados publicos
    account_id_cxp = fields.Many2one('account.account',string='Cuenta CXP', company_dependent=True)
    state_budget_item = fields.Char(string='Rubro')
    state_budget_resource = fields.Char(string='Recurso')



    def _compute_rule(self, localdict):
        """
        :param localdict: dictionary containing the current computation environment
        :return: returns a tuple (amount, qty, rate)
        :rtype: (float, float, float)
        """
        self.ensure_one()
        res = 0,0,0,0,0,[]#monto:float, cantidad:float, tasa:float, nombre:str, log:Xml, data:dict
        if self.amount_select == 'fix':
            try:
                return
            except Exception as e:
                self._raise_error(localdict, _("Wrong quantity defined for:"), e)
        if self.amount_select == 'percentage':
            try:
                return (float(safe_eval(self.amount_percentage_base, localdict)),
                        float(safe_eval(self.quantity, localdict)),
                        self.amount_percentage or 0.0, self.name,False,False)
            except Exception as e:
                self._raise_error(localdict, _("Wrong percentage base or quantity defined for:"), e)
        if self.amount_select == 'code':
            try:
                safe_eval(self.amount_python_compute or 0.0, localdict, mode='exec', nocopy=True)
                return float(localdict['result']), localdict.get('result_qty', 1.0), localdict.get('result_rate', 100.0), self.name,False,False
            except Exception as e:
                self._raise_error(localdict, _("Wrong python code defined for:"), e)
        if self.amount_select == 'concept':
            try:
                method = getattr(self, '_' + str(self.code).lower(), None)
                if method:
                    res = method(localdict)
                    return float(res[0]), res[1], res[2], res[3],res[4],res[5]
                return float(res[0]), res[1], res[2] , res[3],res[4],res[5]
            except Exception as e:
                self._raise_error(localdict, _("Wrong python code defined for:"), e)



    def _compute_rule_lavish(self, localdict):
        """
        :param localdict: dictionary containing the current computation environment
        :return: returns a tuple (amount, qty, rate)
        :rtype: (float, float, float)
        """
        self.ensure_one()
        res = 0,0,0,0,0,[]
        try:
            if self.amount_select == 'fix':
                try:
                    return self.amount_fix or 0.0, float(safe_eval(self.quantity, localdict)), 100.0,False,False,False
                except Exception as e:
                    self._raise_error(localdict, _("Wrong quantity defined for:"), e, "amount_fix calculation")
                    
            if self.amount_select == 'percentage':
                try:
                    return (float(safe_eval(self.amount_percentage_base, localdict)),
                            float(safe_eval(self.quantity, localdict)),
                            self.amount_percentage or 0.0,False,False,False)
                except Exception as e:
                    self._raise_error(localdict, _("Wrong percentage base or quantity defined for:"), e, "percentage calculation")
                    
            if self.amount_select == 'code':
                try:
                    safe_eval(self.amount_python_compute or 0.0, localdict, mode='exec', nocopy=True)
                    return float(localdict['result']), localdict.get('result_qty', 1.0), localdict.get('result_rate', 100.0),False,False,False
                except Exception as e:
                    error_context = {
                        'code': self.amount_python_compute,
                        'location': 'Python code evaluation'
                    }
                    self._raise_error(localdict, _("Wrong python code defined for:"), e, "code evaluation", error_context)
                    
            if self.amount_select == 'concept':
                try:
                    method = getattr(self, '_' + str(self.code).lower(), None)
                    if method:
                        res = method(localdict)
                        return float(res[0]), res[1], res[2], res[3], res[4], res[5]
                    return float(res[0]), res[1], res[2], res[3], res[4], res[5]
                except Exception as e:
                    error_context = {
                        'method_name': f'_{str(self.code).lower()}',
                        'location': 'Concept method execution'
                    }
                    self._raise_error(localdict, _("Wrong python code defined for:"), e, "concept execution", error_context)
                    
        except Exception as e:
            self._raise_error(localdict, _("Unexpected error in rule computation:"), e, "general computation")
            
    def _raise_error(self, localdict, error_type, e, error_location=None, error_context=None):
        """
        Raise a detailed error message with context information
        Args:
            localdict: The local dictionary with computation context
            error_type: Type of error that occurred
            e: The exception object
            error_location: Where the error occurred
            error_context: Additional context about the error (optional)
        """
        import traceback
        import sys
        
        # Get the full traceback
        exc_type, exc_value, exc_traceback = sys.exc_info()
        trace_details = ''.join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        
        # Get relevant code if available
        code_context = ""
        if error_context and 'code' in error_context:
            code_context = f"\n\nRelevant code:\n{error_context['code']}"
        
        # Get specific error details
        error_details = f"\n\nError Location: {error_location}"
        if error_context:
            for key, value in error_context.items():
                if key != 'code':  # Skip code as it's already included above
                    error_details += f"\n{key}: {value}"
        
        # Build the complete error message
        error_message = _("""%s
    - Employee: %s
    - Contract: %s
    - Payslip: %s
    - Salary rule: %s (%s)
    - Error type: %s
    - Error message: %s
    %s
    %s

    Traceback:
    %s""",
            error_type,
            localdict['employee'].name,
            localdict['contract'].name,
            localdict['payslip'].name,
            self.name,
            self.code,
            type(e).__name__,
            str(e),
            error_details,
            code_context,
            trace_details)
        
        raise UserError(error_message)



    def _basic(self, ld):
        """
        Sueldo básico prorrateado con validación de vacaciones.
        """
        contract = ld['contract']
        slip = ld['slip']
        periodo = f"{slip.date_from.strftime('%d/%m/%Y')} - {slip.date_to.strftime('%d/%m/%Y')}"
        if contract.subcontract_type or contract.modality_salary not in ('basico','especie','variable'):
            html = self._build_ssocial_html_log(periodo, False, 'Modalidad no aplicable')
            return 0, 0, 0, False, html, False

        worked = ld['worked_days'].WORK100
        total_days = worked.number_of_days
        total_hours = worked.number_of_hours
        steps = [f"Días trabajados: {total_days}", f"Horas trabajadas: {total_hours}"]

        cambios = sorted(contract.change_wage_ids, key=lambda c: c.date_start)
        change = next((c for c in cambios if slip.date_from <= c.date_start <= slip.date_to), None)
        old_wage = contract.wage
        if change:
            change_day = change.date_start
            new_wage = change.wage
            days_old = min((change_day - slip.date_from).days, total_days)
            days_new = total_days - days_old
            hours_old = round(total_hours * days_old / total_days)
            hours_new = total_hours - hours_old
            steps.append(f"Antiguo ({old_wage}): {days_old}d/{hours_old}h")
            steps.append(f"Nuevo ({new_wage}): {days_new}d/{hours_new}h")
        else:
            days_old, days_new = 0, total_days
            hours_old, hours_new = 0, total_hours
            new_wage = old_wage
            steps.append("Sin cambios salariales en el periodo: operación estándar")

        if slip.struct_type_id.wage_type == 'hourly':
            rate_old = Decimal(old_wage) / Decimal(ld['annual_parameters'].hours_monthly)
            rate_new = Decimal(new_wage) / Decimal(ld['annual_parameters'].hours_monthly)
            pay_old = rate_old * Decimal(hours_old)
            pay_new = rate_new * Decimal(hours_new)
            steps.append(f"Tasa horaria antiguo: {rate_old:.2f}")
            steps.append(f"Tasa horaria nuevo: {rate_new:.2f}")
        else:
            rate_old = Decimal(old_wage) / Decimal(DAYS_MONTH)
            rate_new = Decimal(new_wage) / Decimal(DAYS_MONTH)
            pay_old = rate_old * Decimal(days_old)
            pay_new = rate_new * Decimal(days_new)
            steps.append(f"Tasa diaria antiguo: {rate_old:.2f}")
            steps.append(f"Tasa diaria nuevo: {rate_new:.2f}")

        total_pay = pay_old + pay_new
        steps.append(f"Monto antiguo = {pay_old:.2f}")
        steps.append(f"Monto nuevo = {pay_new:.2f}")
        steps.append(f"Total Sueldo Basico = {total_pay:.2f}")

        quantity = total_hours if slip.struct_type_id.wage_type == 'hourly' else total_days
        avg_rate = float(total_pay / Decimal(quantity)) if quantity else 0.0
        name = 'SUELDO BASICO'
        html = self._build_ssocial_html_log(periodo, True, 'Cálculo Sueldo Básico', pasos=steps)
        return avg_rate, quantity, 100.0, name, html, False

    def _basic002(self, ld):
        """
        Sueldo básico integral con validación de vacaciones.
        """
        contract = ld['contract']
        slip = ld['slip']
        periodo = f"{slip.date_from.strftime('%d/%m/%Y')} - {slip.date_to.strftime('%d/%m/%Y')}"
        if hasattr(ld['worked_days'], 'VAC') and ld['worked_days'].VAC:
            html = self._build_ssocial_html_log(periodo, False, 'No se puede calcular Sueldo Integral durante periodo de vacaciones')
            raise UserError('No se puede calcular Sueldo Integral durante periodo de vacaciones')
        if contract.subcontract_type or contract.modality_salary != 'integral':
            html = self._build_ssocial_html_log(periodo, False, 'Modalidad integral no aplicable')
            return 0, 0, 0, False, html, False

        worked = ld['worked_days'].WORK100
        total_days = worked.number_of_days
        total_hours = worked.number_of_hours
        steps = [f"Días trabajados: {total_days}", f"Horas trabajadas: {total_hours}"]

        cambios = sorted(contract.change_wage_ids, key=lambda c: c.date_start)
        change = next((c for c in cambios if slip.date_from <= c.date_start <= slip.date_to), None)
        old_wage = contract.wage
        if change:
            days_old = min((change.date_start - slip.date_from).days, total_days)
            days_new = total_days - days_old
            hours_old = round(total_hours * days_old / total_days)
            hours_new = total_hours - hours_old
            steps.append(f"Antiguo integral: {days_old}d/{hours_old}h a {old_wage}")
            steps.append(f"Nuevo integral: {days_new}d/{hours_new}h a {change.wage}")
        else:
            days_old, days_new = 0, total_days
            hours_old, hours_new = 0, total_hours
            steps.append("Sin cambios salariales: estándar integral")

        rate_old = Decimal(old_wage) / Decimal(DAYS_MONTH)
        rate_new = Decimal(change.wage if change else old_wage) / Decimal(DAYS_MONTH)
        pay_old = rate_old * Decimal(days_old)
        pay_new = rate_new * Decimal(days_new)
        total_pay = pay_old + pay_new
        steps.append(f"Total Integral = {total_pay:.2f}")

        quantity = total_hours if slip.struct_type_id.wage_type == 'hourly' else total_days
        avg_rate = float(total_pay / Decimal(quantity)) if quantity else 0.0
        name = 'SUELDO BASICO INTEGRAL'
        html = self._build_ssocial_html_log(periodo, True, 'Cálculo Sueldo Integral', pasos=steps)
        return avg_rate, quantity, 100.0, name, html, False

    def _basic003(self, ld):
        """
        Cuota sostenimiento con validación de vacaciones.
        """
        contract = ld['contract']
        slip = ld['slip']
        periodo = f"{slip.date_from.strftime('%d/%m/%Y')} - {slip.date_to.strftime('%d/%m/%Y')}"
        if hasattr(ld['worked_days'], 'VAC') and ld['worked_days'].VAC:
            html = self._build_ssocial_html_log(periodo, False, 'No se puede calcular Sostenimiento durante vacaciones')
            raise UserError('No se puede calcular Sostenimiento durante vacaciones')
        if contract.subcontract_type or contract.modality_salary != 'sostenimiento':
            html = self._build_ssocial_html_log(periodo, False, 'Modalidad sostenimiento no aplicable')
            return 0, 0, 0, False, html, False

        worked = ld['worked_days'].WORK100
        total_days = worked.number_of_days
        total_hours = worked.number_of_hours
        steps = [f"Días trabajados: {total_days}", f"Horas trabajadas: {total_hours}"]

        cambios = sorted(contract.change_wage_ids, key=lambda c: c.date_start)
        change = next((c for c in cambios if slip.date_from <= c.date_start <= slip.date_to), None)
        old_wage = contract.wage
        if change:
            days_old = min((change.date_start - slip.date_from).days, total_days)
            days_new = total_days - days_old
            hours_old = round(total_hours * days_old / total_days)
            hours_new = total_hours - hours_old
            steps.append(f"Lectivo antiguo: {days_old}d/{hours_old}h a {old_wage}")
            steps.append(f"Productivo nuevo: {days_new}d/{hours_new}h a {change.wage}")
        else:
            days_old, days_new = 0, total_days
            hours_old, hours_new = 0, total_hours
            steps.append("Sin cambios salariales: estándar sostenimiento")

        rate_old = Decimal(old_wage) / Decimal(DAYS_MONTH)
        rate_new = Decimal(change.wage if change else old_wage) / Decimal(DAYS_MONTH)
        pay_old = rate_old * Decimal(days_old)
        pay_new = rate_new * Decimal(days_new)
        total_pay = pay_old + pay_new
        steps.append(f"Total Sostenimiento = {total_pay:.2f}")

        quantity = total_hours if slip.struct_type_id.wage_type == 'hourly' else total_days
        avg_rate = float(total_pay / Decimal(quantity)) if quantity else 0.0
        tp = ld['employee'].tipo_coti_id.code
        name = 'CUOTA DE SOSTENIMIENTO LECTIVO' if tp == '12' else 'CUOTA DE SOSTENIMIENTO PRODUCTIVO'
        html = self._build_ssocial_html_log(periodo, True, 'Cálculo Sostenimiento', pasos=steps)
        return avg_rate, quantity, 100.0, name, html, False

    def _embargo001(self, ld: Dict[str, Any]) -> Tuple[float,int,float,str,str,Dict[str, float]]:
        """
        Calcula el embargo aplicable según la ley (CST Art. 154 y siguientes).
        Prioriza embargos por alimentos y respeta límites legales.
        """
        slip = ld['payslip']
        periodo = self._get_periodo(slip)
        emp = ld['employee']
        contract = ld['contract']
        rule = slip.get_salary_rule('EMBARGO001', emp.type_employee.id)
        concept = slip.get_concepts(contract.id, rule.id, 0)
        
        data_result = {
            'valor_embargo': 0.0,
            'tipo_embargo': '',
            'limite_legal': 0.0,
            'base_calculo': 0.0,
            'otros_embargos': 0.0,
            'limite_disponible': 0.0,
            'es_alimentario': False,
            'context_name': ''
        }
        
        if not concept:
            html = self._build_ssocial_html_log(periodo, False, 'Concepto no definido')
            return 0.0, 1, 0.0, periodo, html, data_result

        context_name = self._get_context_name(concept, slip)
        data_result['context_name'] = context_name
        name = context_name or periodo
        
        if  concept.embargo_judged:
            name += f" - Juzgado: {concept.embargo_judged}"
        if  concept.embargo_process:
            name += f" - Proceso: {concept.embargo_process}"
        
        data_result['tipo_embargo'] = concept.type_emb or 'OTRO'
        data_result['es_alimentario'] = (data_result['tipo_embargo'] == 'ECA')

        day = slip.date_from.day
        if (day < 15 and concept.aplicar == '30') or (day >= 15 and concept.aplicar == '15'):
            html = self._build_ssocial_html_log(
                periodo=periodo, 
                aplicado=False, 
                descripcion='No aplica en esta quincena'
            )
            return 0.0, 0, 0.0, name, html, data_result

        cat_codes = [c.code for c in concept.discount_categoria]
        rule_codes = [r.code for r in concept.discount_rule]
        if not cat_codes and not rule_codes:
            cat_codes = ['BASIC']
        
        usar_mes_completo = concept.aplicar == '30'
        excedente = 0.0
        base_cat, _ = self._get_totalizar_categorias(
            ld, cat_codes, 
            incluir_current=True, incluir_before=False, 
            incluir_multi=usar_mes_completo, incluir_subcategorias=True
        ) if cat_codes else (0.0, 0)
        
        base_rule = self._get_totalizar_reglas(
            ld, rule_codes,
            incluir_current=True, incluir_before=False, incluir_multi=usar_mes_completo
        ) if rule_codes else 0.0
        
        base = base_cat + base_rule
        data_result['base_calculo'] = base
        
        pasos = [f"Base total = {self._format_money(base)}"]
        
        smmlv = ld['annual_parameters'].smmlv_monthly
        pasos.append(f"SMMLV = {self._format_money(smmlv)}")
        
        otros_embargos = self._obtener_otros_embargos(ld, concept.id)
        otros_embargos_total = sum(e['valor'] for e in otros_embargos)
        otros_embargos_alimentos = sum(e['valor'] for e in otros_embargos if e['type'] == 'ECA')
        
        data_result['otros_embargos'] = otros_embargos_total
        total, qty_days = self._get_totalizar_categorias(ld, categorias=['BASIC'], 
            incluir_current=False, incluir_before=False, incluir_multi=True)
        if data_result['es_alimentario']:  
            limite_maximo = base * 0.5 
            limite_disponible = limite_maximo - otros_embargos_alimentos
            
            pasos.append(f"Tipo: Embargo por alimentos")
            pasos.append(f"Límite máximo (50% del salario) = {self._format_money(limite_maximo)}")
            
            if otros_embargos_alimentos > 0:
                pasos.append(f"Otros embargos alimentos = {self._format_money(otros_embargos_alimentos)}")
                pasos.append(f"Límite disponible = {self._format_money(limite_disponible)}")
        else:  
            excedente = max(0.0, (base /qty_days or 15) - (smmlv / DAYS_MONTH))
            limite_maximo = excedente * 0.2  
            limite_disponible = limite_maximo - (otros_embargos_total - otros_embargos_alimentos)
            
            pasos.append(f"Tipo: Embargo general")
            pasos.append(f"Excedente sobre SMMLV = {self._format_money(excedente)}")
            pasos.append(f"Límite máximo (20% del excedente) = {self._format_money(limite_maximo)}")
            
            if otros_embargos_total - otros_embargos_alimentos > 0:
                pasos.append(f"Otros embargos generales = {self._format_money(otros_embargos_total - otros_embargos_alimentos)}")
                pasos.append(f"Límite disponible = {self._format_money(limite_disponible)}")
        
        data_result['limite_legal'] = limite_maximo
        data_result['limite_disponible'] = limite_disponible
        
        if limite_disponible <= 0:
            html = self._build_ssocial_html_log(
                periodo=periodo, 
                aplicado=False, 
                descripcion="No hay límite disponible para embargo",
                pasos=pasos
            )
            return 0.0, 0, 0.0, name, html, data_result
        
        sel = concept.amount_select
        pct = 0.0
        if sel == 'percentage':
            pct = concept.amount
            if data_result['es_alimentario']:
                embargoable_raw = base * (pct / 100.0)
            else:
                embargoable_raw = excedente * (pct / 100.0)
            desc = f"{pct}% ordenado por juez"
        elif sel == 'fix':
            pct = 100.0
            embargoable_raw = concept.amount
            desc = f"Monto fijo"
        else:  # 'min'
            pct = concept.amount /100.0
            embargoable_raw = base
            desc = f"Mínimo legal"
        
        pasos.append(f"Cálculo inicial ({desc}) = {self._format_money(embargoable_raw)}")
        
        embargoable = min(embargoable_raw, limite_disponible)
        data_result['valor_embargo'] = embargoable
        
        pasos.append(f"Valor final ajustado al límite = {self._format_money(embargoable)}")
        
        if otros_embargos:
            pasos.append("Listado de embargos activos:")
            for idx, emb in enumerate(otros_embargos, 1):
                tipo = "Alimentario" if emb['type'] == 'ECA' else "General"
                pasos.append(f"{idx}. {emb['name']} ({tipo}): {self._format_money(emb['valor'])}")
        
        html = self._build_ssocial_html_log(
            periodo=periodo, 
            aplicado=True, 
            descripcion=f"Embargo aplicado: {desc}",
            pasos=pasos
        )
        
        return embargoable, -1, pct*100, name, html, data_result

    def _get_context_name(self, concept, payslip):
        """
        Obtiene el nombre contextual del concepto según la nómina actual.
        Si el concepto ya tiene context_name, lo devuelve; de lo contrario, lo calcula.
        """
        base_parts = []
        if concept.input_id:
            base_parts.append(concept.input_id.name)
        
        if payslip:
            date_to = payslip.date_to
            fortnight = "1Q" if date_to.day <= 15 else "2Q"
            month_year = f"{date_to.strftime('%b').upper()}/{date_to.year}"
            base_parts.append(f"{fortnight} {month_year}")
        
        if concept.is_deduction and concept.is_earning:
            tipo = "D" if concept.is_deduction else "I" if concept.is_earning else "C"
            base_parts.append(f"[{tipo}]")
        
        return " - ".join(base_parts) if base_parts else ""

    def _obtener_otros_embargos(self, liquidacion_data, current_concept_id):
        """
        Obtiene otros embargos activos en la nómina para consideración de prioridades.
        Utiliza rule_multi para obtener todos los embargos ya calculados.
        
        Returns:
            List[Dict]: Lista de diccionarios con información de otros embargos
                cada elemento contiene: 'name', 'valor', 'type', 'priority'
        """
        result = []
        
        if 'rules_multi' in liquidacion_data:
            for rule_code, rule_data in liquidacion_data['rules_multi'].items():
                if rule_code.startswith('EMBARGO') and rule_code != 'EMBARGO001':
                    for periodo, periodo_data in rule_data.items():
                        if periodo == 'current':
                            continue  # Saltar el actual ya que está en proceso
                        
                        if 'concept_id' in periodo_data and periodo_data['concept_id'] != current_concept_id:
                            tipo_emb = periodo_data.get('type_emb', 'OTRO')
                            
                            nombre = periodo_data.get('context_name', '')
                            if not nombre:
                                nombre = periodo_data.get('name', rule_code)
                            
                            result.append({
                                'name': nombre,
                                'valor': periodo_data.get('total', 0.0),
                                'type': tipo_emb,
                                'priority': 1 if tipo_emb == 'ECA' else 2,
                                'juzgado': periodo_data.get('embargo_judged', ''),
                                'proceso': periodo_data.get('embargo_process', ''),
                                'context_name': periodo_data.get('context_name', '')
                            })
        
        return sorted(result, key=lambda x: x['priority'])

    def _format_money(self, value):
        """
        Formatea un valor numérico como moneda con punto como separador de miles
        y coma como separador decimal, siempre con 2 decimales.
        """
        if value is None:
            return "$0,00"
        # Formatear con punto como separador de miles y coma como decimal
        return f"${value:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')

    def _format_number(self, value):
        """
        Formatea un valor numérico con punto como separador de miles
        y coma como separador decimal, siempre con 2 decimales.
        """
        if value is None:
            return "0,00"
        # Formatear con punto como separador de miles y coma como decimal
        return f"{value:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')

    def _dev_aux000(self, liquidacion_data):
        """Devolución del subsidio de transporte"""
        contrato = liquidacion_data['contract']
        nomina = liquidacion_data['slip']
        parametros_anuales = liquidacion_data['annual_parameters']
        aux_trans_mensual = parametros_anuales.transportation_assistance_monthly
        name = 'DEVOLUCION AUXILIO DE TRANSPORTE' + ' ' + str(nomina.date_from.month) + '-15'
        periodo = self._get_periodo(nomina)
        pasos = []
        
        # Cálculo salario proyectado
        total, qty_days = self._get_totalizar_categorias(liquidacion_data, categorias=['BASIC'], 
            incluir_current=False, incluir_before=False, incluir_multi=True)
        total_dev, _ = self._get_totalizar_categorias(liquidacion_data, categorias=['DEV_SALARIAL'], 
            categorias_excluir="BASIC", incluir_current=False, incluir_before=False, incluir_multi=True)
        
        if liquidacion_data['slip'].struct_type_id.wage_type == "hourly" and qty_days > 0:
            hours_daily = liquidacion_data['annual_parameters'].hours_daily
            qty_days = qty_days / hours_daily
             

        total_basic = contrato.wage / DAYS_MONTH
        days_project =  qty_days + 15
        BASIC = total_basic * days_project
        devengados_totales = (total + total_dev)
        

        if nomina.date_from.day > 15:
            devengados_totales = (BASIC + total_dev)
            pasos.append(f"Días a Proyectar = (30 - {qty_days:.2f}) + 15 = {days_project:.2f}")
            pasos.append(f"BASIC proyectado = {self._format_money(BASIC)}")           
        pasos.append(f"Salario diario = {self._format_money(total_basic)}")
        pasos.append(f"Devengados totales = {self._format_money(devengados_totales)}")
        auxilio_previo = self._get_totalizar_reglas(
                liquidacion_data, 'AUX000', 
                incluir_current=True, incluir_before=False, incluir_multi=False, 
                devolver_cantidad=False
            )
        if contrato.dev_aux:
            html = self._build_ssocial_html_log(
                periodo=periodo, aplicado=False, 
                descripcion="No esta la opcion de devolver",
                pasos=pasos
            )
            return 0, 0, 0, 0, html, 0        
        if auxilio_previo <= 0:
            html = self._build_ssocial_html_log(
                periodo=periodo, aplicado=False, 
                descripcion="No hay auxilio previo para devolver",
                pasos=pasos
            )
            return 0, 0, 0, 0, html, 0
        
        valor_diario = aux_trans_mensual / DAYS_MONTH
        dias_pagados = round(abs(auxilio_previo / valor_diario))
        
        pasos.append(f"Auxilio previo = {self._format_money(auxilio_previo)}")
        pasos.append(f"Valor diario = {self._format_money(valor_diario)}")
        pasos.append(f"Días pagados = {self._format_number(dias_pagados)}")
        
        dos_salarios_minimos = 2 * parametros_anuales.smmlv_monthly
        
        if contrato.only_wage == 'wage':
            wage_for_comparison = contrato.wage
            supera_tope = wage_for_comparison >= dos_salarios_minimos
            pasos.append(f"Salario base {self._format_money(wage_for_comparison)} vs tope {self._format_money(dos_salarios_minimos)}")
        else:
            supera_tope = devengados_totales >= dos_salarios_minimos
            pasos.append(f"Devengados {self._format_money(devengados_totales)} vs tope {self._format_money(dos_salarios_minimos)}")
        
        if supera_tope:
            html = self._build_ssocial_html_log(
                periodo=periodo, aplicado=True, 
                descripcion=f"Devolución auxilio de transporte por superar tope",
                pasos=pasos
            )
            return -valor_diario, dias_pagados, 100, name, html, False
        
        html = self._build_ssocial_html_log(
            periodo=periodo, aplicado=False, 
            descripcion="No se requiere devolución de auxilio",
            pasos=pasos
        )
        return 0, 0, 0, 0, html, 0


    def _aux000(self, liquidacion_data):
        """Subsidio de transporte"""
        contrato = liquidacion_data['contract']
        empleado = liquidacion_data['employee']
        nomina = liquidacion_data['slip']
        dias_trabajados = liquidacion_data['worked_days']
        parametros_anuales = liquidacion_data['annual_parameters']
        aux_trans_mensual = parametros_anuales.transportation_assistance_monthly
        periodo = self._get_periodo(nomina).upper()
        pasos = []
        
        # Verificaciones básicas
        if contrato.skip_commute_allowance:
            return 0, 0, 0, 0, self._build_ssocial_html_log(
                periodo=periodo, aplicado=False, 
                descripcion="Contrato omite auxilio de transporte"), 0
        
        if contrato.not_validate_top_auxtransportation and dias_trabajados.WORK100.number_of_days != 0.0:
            dias = dias_trabajados.WORK100.number_of_days
            valor_diario = aux_trans_mensual / DAYS_MONTH
            
            pasos.append(f"Sin validar tope - Días: {self._format_number(dias)}")
            pasos.append(f"Valor diario: {self._format_money(valor_diario)}")
            
            html = self._build_ssocial_html_log(
                periodo=periodo, aplicado=True, 
                descripcion="Auxilio sin validar tope",
                pasos=pasos
            )
            return valor_diario, dias, 100, periodo, html, False
        
        if ((contrato.pay_auxtransportation and nomina.date_from.day < 15) or
                contrato.modality_salary == 'integral' or
                empleado.tipo_coti_id.code == '12'):
            
            razon = "Primera quincena" if (contrato.pay_auxtransportation and nomina.date_from.day < 15) else (
                    "Salario integral" if contrato.modality_salary == 'integral' else "Cotizante 12")
            
            pasos.append(f"No aplica: {razon}")
            
            html = self._build_ssocial_html_log(
                periodo=periodo, aplicado=False, 
                descripcion=f"No aplica auxilio ({razon})",
                pasos=pasos
            )
            return 0, 0, 0, 0, html, 0
        
        # Proyección salarial
        total, qty_days = self._get_totalizar_categorias(liquidacion_data, categorias=['BASIC'], 
            incluir_current=True, incluir_before=False, incluir_multi=True)
        total_dev, _ = self._get_totalizar_categorias(liquidacion_data, categorias=['DEV_SALARIAL'], 
            categorias_excluir="BASIC", incluir_current=True, incluir_before=False, incluir_multi=True)
        
        if liquidacion_data['slip'].struct_type_id.wage_type == "hourly" and qty_days > 0:
            qty_days = qty_days / parametros_anuales.hours_daily
        
        total_basic = contrato.wage / DAYS_MONTH
        days_project =  qty_days + 15
        BASIC = total_basic * days_project
        devengados_totales = (total + total_dev)
        

        if nomina.date_from.day > 15:
            devengados_totales = (BASIC + total_dev)
            pasos.append(f"Días a Proyectar = (30 - {qty_days:.2f}) + 15 = {days_project:.2f}")
            pasos.append(f"BASIC proyectado = {self._format_money(BASIC)}")        
        pasos.append(f"Salario diario = {self._format_money(total_basic)}")
        pasos.append(f"Devengados totales = {self._format_money(devengados_totales)}")
        
        # Verificar tope salarial
        dos_salarios_minimos = 2 * parametros_anuales.smmlv_monthly + 0.01
        
        if contrato.only_wage == 'wage':
            wage_for_comparison = contrato.wage
            supera_tope = wage_for_comparison > dos_salarios_minimos
            pasos.append(f"Salario base {self._format_money(wage_for_comparison)} vs tope {self._format_money(dos_salarios_minimos)}")
        else:
            supera_tope = devengados_totales > dos_salarios_minimos
            pasos.append(f"Devengados {self._format_money(devengados_totales)} vs tope {self._format_money(dos_salarios_minimos)}")
        
        if supera_tope:
            html = self._build_ssocial_html_log(
                periodo=periodo, aplicado=False, 
                descripcion="No aplica por superar tope salarial",
                pasos=pasos
            )
            return 0, 0, 100, 0, html, 0
        
        # Verificar política
        politica_aplica = (
            contrato.modality_salary in ['basico','especie','variable','sostenimiento'] 
            and not contrato.subcontract_type
        )
        
        if not politica_aplica:
            pasos.append(f"Modalidad: {contrato.modality_salary}, No aplica por política")
            html = self._build_ssocial_html_log(
                periodo=periodo, aplicado=False, 
                descripcion="No aplica por política salarial",
                pasos=pasos
            )
            return 0, 0, 0, 0, html, 0
        
        # Cálculo final
        dias_ausencias = sum(
            leave_line.days_payslip
            for leave_line in nomina.leave_days_ids
            if leave_line.leave_id.holiday_status_id.sub_not_aux
        )
        
        valor_base = aux_trans_mensual / DAYS_MONTH
        cantidad_dias = dias_trabajados.WORK100.number_of_days
        
        # Ajuste para aprendices
        if empleado.tipo_coti_id.code == '19' and contrato.apr_prod_date:
            inicio_periodo, fin_periodo = nomina.date_from, nomina.date_to
            if inicio_periodo < contrato.apr_prod_date <= fin_periodo:
                cantidad_dias = days360(contrato.apr_prod_date, fin_periodo) + dias_ausencias
                pasos.append(f"Ajuste aprendiz: {self._format_number(cantidad_dias)} días")
        
        valor_total = valor_base * cantidad_dias
        
        pasos.append(f"Auxilio diario: {self._format_money(valor_base)}")
        pasos.append(f"Días: {self._format_number(cantidad_dias)}")
        pasos.append(f"Total: {self._format_money(valor_total)}")
        
        html = self._build_ssocial_html_log(
            periodo=periodo, aplicado=True, 
            descripcion=f"Pago de auxilio de transporte",
            pasos=pasos
        )
        
        return valor_base, cantidad_dias, 100, periodo, html, False

    def need_compute_salary_average(self, contract, date_from, date_to):
        date_3_months_before = date_to - relativedelta(months=3)
        if date_from > date_3_months_before:
            date_3_months_before = date_from
        return contract.has_change_salary(date_3_months_before, date_to)
    

    def _get_periodo(self, slip) -> str:
        """
        Devuelve la etiqueta de periodo basada en payslip:
          - "Vacaciones MM-YY" para struct_process='vacaciones'
          - "Primera Q1 MM-YY" o "Segunda Q2 MM-YY" en nóminas ordinarias
        """
        date_to = slip.date_to
        etiqueta_fecha = date_to.strftime('%m-%y')
        tipo = slip.struct_process
        if tipo == 'vacaciones':
            label = 'Vacaciones'
        else:
            label = 'Q1' if date_to.day <= 15 else 'Q2'
        return f"{self.name} {label} {etiqueta_fecha}".capitalize()

    def _build_ibd_html_log(
        self,
        ibc_full: float,
        day_value: float,
        effective_days: int,
        periodo: str,
        es_aprendiz: bool
     ) -> str:
        """
        Construye el bloque HTML con:
          - Nombre de la regla (self.name)
          - Periodo
          - IBC final
          - Valor día
          - Días efectivos
          - Motivo si es aprendiz
        """
        html = "<div class='ibd-log'>"
        html += _("""<p><strong>Regla:</strong> %(name)s</p>""", name=self.name)
        html += _("""<p><strong>Periodo:</strong> %(periodo)s</p>""", periodo=periodo)
        html += _("""<p>IBC final: <strong>%(ibc)s</strong></p>""",
                  ibc=self._format_money(ibc_full))
        html += _("""<p>Valor día: <strong>%(dv)s</strong></p>""",
                  dv=self._format_money(day_value))
        html += _("""<p>Días efectivos: <strong>%(ed)s</strong></p>""",
                  ed=effective_days)
        if es_aprendiz:
            html += _("<p style='color: #a00;'><em>Motivo:</em> Practicante que no cotiza</p>")
        html += "</div>"
        return html
    
    def _ibd(self, payslip_data: Dict[str, Any]) -> Tuple[float, int, int, str, str, Dict[str, Any]]:
        """
        Calcula el IBD y retorna:
            day_value, effective_days, 100, periodo, html_log, resultado_completo
        •  Para contrato de aprendizaje → ceros + log con motivo
        •  Para cualquier otro contrato → valores reales + log detallado
        """
        slip     = payslip_data.get('slip')          
        contract = payslip_data.get('contract')
        periodo  = self._get_periodo(slip)  

        if contract and contract.contract_type == 'aprendizaje':
            html_log = self._build_ssocial_html_log(
                periodo      = periodo,
                aplicado     = False,
                descripcion  = "Contrato de aprendizaje: no genera IBC.",
            )
            return 0.0, 0, 100, periodo, html_log, {}


        service  = self.env['payroll.ibd.service']
        ctx      = service.compute(payslip_data,slip, write_lines=False)   

        day_value       = ctx.day_value
        effective_days  = int(ctx.dias.get('eff', 0))
        ibc_full        = ctx.ibc_final


        resultado_full = {
            'ibc_final':      ibc_full,
            'day_value':      day_value,
            'effective_days': effective_days,
            'ctx':            ctx,             # puedes inspeccionar ctx.log, ctx.notas…
        }

        return day_value, effective_days, 100, periodo, ctx.html, resultado_full



    def _get_totalizar_reglas(
        self,
        liquidacion_data: Dict[str, Any],
        codigos_regla: Optional[Union[str, List[str]]] = None,
        filtros: Optional[Dict[str, Callable[[Any], bool]]] = None,
        incluir_current: bool = True,
        incluir_before: bool = False,
        incluir_multi: bool = True,
        devolver_cantidad: bool = False,
        ) -> Union[float, int]:
        
        if codigos_regla is None:
            codigos = [
                c for c in liquidacion_data.get('payslip_lines', {}).keys()
                if c != 'rules_multi'
            ]
        else:
            codigos = codigos_regla if isinstance(codigos_regla, list) else [codigos_regla]

        filtros = filtros or {}
        def pasa_filter(obj: Any) -> bool:
            cond = filtros.get('object')
            return cond(obj) if cond else True

        entradas: List[Dict[str, Any]] = []

        payslip_lines = liquidacion_data.get('payslip_lines', {})
        for code in codigos:
            rd = payslip_lines.get(code) or {}
            if incluir_current and (info := rd.get('current_month')):
                entradas.append({
                    'object':  info.get('rule'),
                    'total':   info.get('total', 0.0),
                    'entries': info.get('entries', []),
                })
            if incluir_before and (info := rd.get('before_month')):
                entradas.append({
                    'object':  info.get('rule'),
                    'total':   info.get('total', 0.0),
                    'entries': info.get('entries', []),
                })

        if incluir_multi and (rm := liquidacion_data.get('rules_multi')):
            for code in codigos:
                if (info := rm.get(code, {}).get('current')):
                    entradas.append({
                        'object':   info.get('object'),
                        'total':    info.get('total', 0.0),
                        'quantity': info.get('quantity', 0),
                    })

        total_valor = 0.0
        total_entradas = 0
        for item in entradas:
            obj = item.get('object')
            if not obj or not pasa_filter(obj):
                continue

            if devolver_cantidad:
                if 'entries' in item:
                    total_entradas += sum(e.get('quantity', 0) for e in item['entries'])
                else:
                    total_entradas += item.get('quantity', 0)
            else:
                total_valor += item.get('total', 0.0)

        return total_entradas if devolver_cantidad else total_valor

    def _get_totalizar_categorias(
        self,
        localdict: Dict[str, Any],
        categorias: Optional[Union[List[str], str]] = None,
        categorias_excluir: Optional[Union[List[str], str]] = None,
        filtros: Optional[Dict[str, Callable[[Any], bool]]] = None,
        incluir_current: bool = True,
        incluir_before: bool = False,
        incluir_multi: bool = True,
        incluir_subcategorias: bool = True,
        ) -> Tuple[float, float]:
        def _to_list(x: Optional[Union[List[str], str]]) -> Optional[List[str]]:
            if x is None:
                return None
            return x if isinstance(x, list) else [x]

        categorias = _to_list(categorias)
        categorias_excluir = _to_list(categorias_excluir)
        filtros = filtros or {}

        def _pasa_filtros(obj: Any) -> bool:
            for clave, cond in filtros.items():
                if clave == 'object':
                    if not cond(obj):
                        return False
                else:
                    val = getattr(obj, clave, None)
                    if callable(cond):
                        if not cond(val):
                            return False
                    else:
                        if bool(val) != bool(cond):
                            return False
            return True

        fuente: List[Dict[str, Any]] = []
        for code, rd in localdict.get('payslip_lines', {}).items():
            if incluir_current and (info := rd.get('current_month')) and info.get('rule'):
                fuente.append({
                    'code': code,
                    'object': info['rule'],
                    'total': info.get('total', 0.0),
                    'entries': info.get('entries', []),
                })
            if incluir_before and (info := rd.get('before_month')) and info.get('rule'):
                fuente.append({
                    'code': code,
                    'object': info['rule'],
                    'total': info.get('total', 0.0),
                    'entries': info.get('entries', []),
                })

        if incluir_multi:
            for code, rd in localdict.get('rules_multi', {}).items():
                if (info := rd.get('current')) and info.get('object'):
                    fuente.append({
                        'code': code,
                        'object': info['object'],
                        'total': info.get('total', 0.0),
                        'quantity': info.get('quantity', 0),
                    })

        
        reglas_por_cat: Dict[str, set] = {} # construir mapeos categoría ← reglas y padre ← hijo
        padres: Dict[str, str] = {}
        for item in fuente:
            obj = item['object']
            if not obj.category_id:
                continue
            cat = obj.category_id.code
            reglas_por_cat.setdefault(cat, set()).add(item['code'])
            if obj.category_id.parent_id:
                padres.setdefault(cat, obj.category_id.parent_id.code)

        hijos: Dict[str, set] = {}
        for cat, p in padres.items():
            hijos.setdefault(p, set()).add(cat)

        if categorias is None:
            cats = set(reglas_por_cat)
        else:
            cats = set(categorias)
            if incluir_subcategorias:
                cola = list(cats)
                while cola:
                    c = cola.pop()
                    for h in hijos.get(c, ()):
                        if h not in cats:
                            cats.add(h)
                            cola.append(h)

        if categorias_excluir:
            ex = set(categorias_excluir)
            if incluir_subcategorias:
                cola = list(ex)
                while cola:
                    c = cola.pop()
                    for h in hijos.get(c, ()):
                        if h not in ex:
                            ex.add(h)
                            cola.append(h)
            cats -= ex
        total_valor = 0.0
        total_entradas = 0
        for item in fuente:
            obj = item['object']
            cat = obj.category_id.code if obj.category_id else None
            if cat not in cats or not _pasa_filtros(obj):
                continue

            total_valor += item.get('total', 0.0)
            if 'entries' in item:
                total_entradas += len(item['entries'])
            else:
                total_entradas += item.get('quantity', 0)

        return total_valor, total_entradas
    

    def _build_ssocial_html_log(
            self,
            periodo: str,
            aplicado: bool,
            descripcion: str,
            saldo_anterior: float = None,
            rango_log: List[Tuple[str, str]] = None,
            pasos: List[str] = None
        ) -> str:
            """
            Genera un log HTML para reglas de seguridad social usando clases CSS
            que son compatibles con el modo oscuro.
            
            Args:
                periodo: Periodo de la nómina (ej. "Primera Q1 04-23")
                aplicado: Indica si la regla se aplicó
                descripcion: Descripción de la operación o razón de no aplicación
                saldo_anterior: Saldo acumulado del periodo anterior
                rango_log: Lista de tuplas (etiqueta, estado) para rangos de cálculo
                pasos: Lista de pasos del cálculo realizados
                
            Returns:
                Representación HTML del log
            """
            html = '<div class="simulation-container p-3 border rounded bg-light">'
            
            html += '<div class="d-flex justify-content-between align-items-center mb-3 pb-2 border-bottom">'
            html += f'<h5 class="mb-0 text-primary">{self.name}</h5>'
            
            badge_class = "badge bg-success" if aplicado else "badge bg-danger"
            badge_text = "Aplicado" if aplicado else "No Aplicado"
            html += f'<span class="{badge_class}">{badge_text}</span>'
            html += '</div>'
            
            html += f'<div class="mb-2"><strong>Periodo:</strong> {periodo.upper()}</div>'
            
            alert_class = "alert alert-success p-2" if aplicado else "alert alert-danger p-2"
            html += f'<div class="mb-3 {alert_class}">'
            
            if aplicado:
                html += f'<i class="fa fa-check-circle"></i> <strong>Operación realizada:</strong> {descripcion}'
            else:
                html += f'<i class="fa fa-times-circle"></i> <strong>No aplica:</strong> {descripcion}'
            
            html += '</div>'
            
            if aplicado and saldo_anterior is not None:
                html += '<div class="mb-3 p-2 bg-white rounded shadow-sm border-start border-warning border-4">'
                html += f'<div><strong>Saldo anterior:</strong> <span class="text-primary">{self._format_money(saldo_anterior)}</span></div>'
                html += '</div>'
            
            if rango_log:
                html += '<div class="mt-3 mb-3">'
                html += '<h6 class="mb-2">Rangos evaluados:</h6>'
                
                html += '<ul class="list-group mb-0">'
                for label, estado in rango_log:
                    item_class = "list-group-item-success" if estado == "Si" else "list-group-item-light"
                    icon = '<i class="fa fa-check-circle text-success"></i>' if estado == "Si" else '<i class="fa fa-times-circle text-danger"></i>'
                    html += f'<li class="list-group-item {item_class} py-1">{icon} {label}</li>'
                html += '</ul>'
                html += '</div>'
            
            if pasos and aplicado:
                html += '<div class="mt-3">'
                html += '<h6 class="mb-2">Pasos del cálculo:</h6>'
                
                html += '<div class="table-responsive">'
                html += '<table class="table table-sm table-bordered">'
                html += '<tbody>'
                for i, paso in enumerate(pasos, 1):
                    html += f'<tr><td class="text-center" style="width: 40px;">{i}</td><td>{paso.upper()}</td></tr>'
                html += '</tbody></table>'
                html += '</div>'
                html += '</div>'
            
            html += '</div>'
            return html

    def _ssocial001(self, liquidacion_data):
        """
        Calcula la deducción de salud del empleado
        """
        porcentaje_salud = liquidacion_data['annual_parameters'].value_porc_health_employee / 100
        slip = liquidacion_data['slip']
        periodo = self._get_periodo(slip).upper()
        empleado = liquidacion_data['employee']
        
        # Verificar si el empleado no contribuye a EPS
        if empleado.subtipo_coti_id.not_contribute_eps:
            html = self._build_ssocial_html_log(
                periodo=periodo, 
                aplicado=False, 
                descripcion="El empleado no contribuye a EPS según su subtipo de cotizante"
            )
            return 0, 0, 0, 0, html, False
        
        # Verificar si no es contrato de aprendizaje
        if liquidacion_data['contract'].contract_type != 'aprendizaje':
            ibc_full = liquidacion_data['rules_multi']['IBD']['current']['log']['ibc_final']
            ingreso_base_cotizacion = liquidacion_data['rules_computed'].IBD
            ibc = ibc_full - ingreso_base_cotizacion
            
            # Obtener valor acumulado del mes anterior
            valor_mes_anterior = self._get_totalizar_reglas(
                liquidacion_data, 'SSOCIAL001', 
                incluir_current=True, incluir_before=False, incluir_multi=False, 
                devolver_cantidad=False
            )
            ibc_anterior = valor_mes_anterior / porcentaje_salud if porcentaje_salud else 0
            ibc_adjustado = ibc + ibc_anterior
            base_calculo = ingreso_base_cotizacion + ibc_adjustado
            
            # Preparar pasos de cálculo en formato conciso
            pasos = [
                f"IBC Diferencia = {self._format_money(ibc_full)} - {self._format_money(ingreso_base_cotizacion)} = {self._format_money(ibc)}",
                f"IBC Anterior = {self._format_money(valor_mes_anterior)} ÷ {porcentaje_salud * 100}% = {self._format_money(ibc_anterior)}",
                f"IBC Ajustado = {self._format_money(ibc)} + {self._format_money(ibc_anterior)} = {self._format_money(ibc_adjustado)}",
                f"Base Cálculo = {self._format_money(ingreso_base_cotizacion)} + {self._format_money(ibc_adjustado)} = {self._format_money(base_calculo)}"
            ]
            
            porcentaje_salud = liquidacion_data['annual_parameters'].value_porc_health_employee
            
            # Verificar si aplica según la quincena de cobro
            if ((self.aplicar_cobro == '15' and slip.date_from.day >= 15) or 
                (self.aplicar_cobro == '30' and slip.date_from.day < 15)):
                html = self._build_ssocial_html_log(
                    periodo=periodo, 
                    aplicado=False, 
                    descripcion=f"No aplica para esta quincena (Quincena: {self.aplicar_cobro}, Día inicio: {slip.date_from.day})"
                )
                return 0, 0, porcentaje_salud, '', html, False
            else:
                html = self._build_ssocial_html_log(
                    periodo=periodo, 
                    aplicado=True, 
                    descripcion=f"Cálculo de deducción de salud ({porcentaje_salud}% del IBC)",
                    saldo_anterior=ibc_anterior,
                    pasos=pasos
                )
                return base_calculo, -1, porcentaje_salud, periodo, html, False
        else:
            html = self._build_ssocial_html_log(
                periodo=periodo, 
                aplicado=False, 
                descripcion="No aplica para contratos de aprendizaje"
            )
            return 0, 0, 0, 0, html, False

    def _ssocial002(self, liquidacion_data):
        """
        Calcula la deducción de pensión del empleado
        """
        porcentaje_pension = liquidacion_data['annual_parameters'].value_porc_pension_employee / 100
        slip = liquidacion_data['slip']
        periodo = self._get_periodo(slip).upper()
        empleado = liquidacion_data['employee']
        
        if empleado.subtipo_coti_id.not_contribute_pension:
            html = self._build_ssocial_html_log(
                periodo=periodo, 
                aplicado=False, 
                descripcion="El empleado no contribuye a pensión según su subtipo de cotizante"
            )
            return 0, 0, 0, 0, html, False
        
        if liquidacion_data['contract'].contract_type != 'aprendizaje':
            ibc_full = liquidacion_data['rules_multi']['IBD']['current']['log']['ibc_final']
            ingreso_base_cotizacion = liquidacion_data['rules_computed'].IBD
            ibc = ibc_full - ingreso_base_cotizacion
            
            valor_mes_anterior = self._get_totalizar_reglas(
                liquidacion_data, 'SSOCIAL002', 
                incluir_current=True, incluir_before=False, incluir_multi=False, 
                devolver_cantidad=False
            )
            ibc_anterior = valor_mes_anterior / porcentaje_pension if porcentaje_pension else 0
            ibc_adjustado = ibc + ibc_anterior
            base_calculo = ingreso_base_cotizacion + ibc_adjustado
            
            pasos = [
                f"IBC = {self._format_money(ingreso_base_cotizacion)}",
                f"Valor Acumulado = {self._format_money(valor_mes_anterior)}",
                f"IBC Anterior = {self._format_money(valor_mes_anterior)} ÷ {porcentaje_pension * 100}% = {self._format_money(ibc_anterior)}",
                f"Base Cálculo = {self._format_money(ingreso_base_cotizacion)} + {self._format_money(ibc_anterior)} = {self._format_money(base_calculo)}"
            ]
            
            porcentaje_pension = liquidacion_data['annual_parameters'].value_porc_pension_employee
            
            if ((self.aplicar_cobro == '15' and slip.date_from.day >= 15) or 
                (self.aplicar_cobro == '30' and slip.date_from.day < 15)):
                html = self._build_ssocial_html_log(
                    periodo=periodo, 
                    aplicado=False, 
                    descripcion=f"No aplica para esta quincena (Quincena: {self.aplicar_cobro}, Día inicio: {slip.date_from.day})"
                )
                return 0, 0, porcentaje_pension, '', html, False
            else:
                html = self._build_ssocial_html_log(
                    periodo=periodo, 
                    aplicado=True, 
                    descripcion=f"Cálculo de deducción de pensión ({porcentaje_pension}% del IBC)",
                    saldo_anterior=ibc_anterior,
                    pasos=pasos
                )
                return base_calculo, -1, porcentaje_pension, periodo, html, False
        else:
            html = self._build_ssocial_html_log(
                periodo=periodo, 
                aplicado=False, 
                descripcion="No aplica para contratos de aprendizaje"
            )
            return 0, 0, 0, 0, html, False
          
    def _ssocial003(self, liquidacion_data):
        """
        Calcula el aporte a fondo de solidaridad
        """
        porcentaje_fsp = 0.5
        slip = liquidacion_data['slip']
        periodo = self._get_periodo(slip).upper()
        parametros_anuales = liquidacion_data['annual_parameters']
        contrato = liquidacion_data['contract']
        pasos = []
        
        debe_proyectar = (contrato.proyectar_fondos and slip.date_from.day <= 15)
        
        if debe_proyectar:
            total, qty_days = self._get_totalizar_categorias(
                liquidacion_data, categorias=['BASIC'], 
                incluir_current=False, incluir_before=False, incluir_multi=True
            )
            total_dev, _ = self._get_totalizar_categorias(
                liquidacion_data, categorias=['DEV_SALARIAL'], categorias_excluir="BASIC", 
                incluir_current=False, incluir_before=False, incluir_multi=True
            )
            
            if liquidacion_data['slip'].struct_type_id.wage_type == "hourly" and qty_days > 0:
                hours_daily = parametros_anuales.hours_daily
                qty_days = qty_days / hours_daily
                
            total_basic = total / qty_days if qty_days > 0 else 0
            days_project =  qty_days + 15
            BASIC = total_basic * days_project
            ingreso_base_cotizacion = (BASIC + total_dev)
            
            pasos = [
                f"Días Acumulados = {qty_days:.2f}",
                f"Salario Diario = {self._format_money(total)} ÷ {qty_days:.2f} = {self._format_money(total_basic)}",
                f"Días a Proyectar = (30 - {qty_days:.2f}) + 15 = {days_project:.2f}",
                f"BASIC Proyectado = {self._format_money(total_basic)} × {days_project:.2f} = {self._format_money(BASIC)}",
                f"IBC = {self._format_money(BASIC)} + {self._format_money(total_dev)} = {self._format_money(ingreso_base_cotizacion)}"
            ]
        else:
            ingreso_base_cotizacion = liquidacion_data['rules_computed'].IBD
            pasos = [f"IBC = {self._format_money(ingreso_base_cotizacion)}"]
        
        if (round_1_decimal(ingreso_base_cotizacion) < round_1_decimal(parametros_anuales.top_four_fsp_smmlv) or 
            contrato.contract_type == 'aprendizaje'):
            
            if round_1_decimal(ingreso_base_cotizacion) < round_1_decimal(parametros_anuales.top_four_fsp_smmlv):
                pasos.append(f"IBC {self._format_money(ingreso_base_cotizacion)} ≤ 4 SMMLV {self._format_money(parametros_anuales.top_four_fsp_smmlv)}")
                descripcion = f"No aplica porque el IBC no supera 4 SMMLV"
            else:
                descripcion = "No aplica para contratos de aprendizaje"
                
            html = self._build_ssocial_html_log(
                periodo=periodo, 
                aplicado=False, 
                descripcion=descripcion,
                pasos=pasos
            )
            return 0, 0, porcentaje_fsp, '', html, False
        
        pasos.append(f"IBC {self._format_money(ingreso_base_cotizacion)} > 4 SMMLV {self._format_money(parametros_anuales.top_four_fsp_smmlv)}")
        
        empleado = liquidacion_data['employee']
        es_pensionado = empleado.subtipo_coti_id.code not in ['00', False]
        
        if es_pensionado:
            html = self._build_ssocial_html_log(
                periodo=periodo, 
                aplicado=False, 
                descripcion="No aplica por ser pensionado",
                pasos=pasos
            )
            return 0, 0, porcentaje_fsp, '', html, False
        
        valor_mes_anterior = self._get_totalizar_reglas(
            liquidacion_data, 'SSOCIAL003', 
            incluir_current=True
        )
        
        if valor_mes_anterior != 0:
            base_mes_anterior = valor_mes_anterior / (porcentaje_fsp / 100)
        else:
            base_mes_anterior = 0
            
        base_calculo = ingreso_base_cotizacion - abs(base_mes_anterior)
        
        pasos.extend([
            f"Valor Acumulado = {self._format_money(valor_mes_anterior)}",
            f"Base Anterior = {self._format_money(valor_mes_anterior)} ÷ {porcentaje_fsp}% = {self._format_money(base_mes_anterior)}",
            f"Base Cálculo = {self._format_money(ingreso_base_cotizacion)} - {self._format_money(base_mes_anterior)} = {self._format_money(base_calculo)}"
        ])
        
        if ((self.aplicar_cobro == '15' and slip.date_from.day >= 15) or 
            (self.aplicar_cobro == '30' and slip.date_from.day < 15)):
            html = self._build_ssocial_html_log(
                periodo=periodo, 
                aplicado=False, 
                descripcion=f"No aplica para esta quincena (Quincena: {self.aplicar_cobro}, Día inicio: {slip.date_from.day})",
                pasos=pasos
            )
            return 0, 0, porcentaje_fsp, '', html, False
        
        if debe_proyectar and base_calculo > 0:
            base_calculo = base_calculo / 2
            pasos.append(f"Base Cálculo (Proyección) = {self._format_money(base_calculo * 2)} ÷ 2 = {self._format_money(base_calculo)}")
        
        html = self._build_ssocial_html_log(
            periodo=periodo, 
            aplicado=True, 
            descripcion=f"Cálculo de aporte a fondo de solidaridad ({porcentaje_fsp}% del IBC)",
            saldo_anterior=valor_mes_anterior if valor_mes_anterior != 0 else None,
            pasos=pasos
        )
        return base_calculo, -1, porcentaje_fsp, periodo, html, False

    def _ssocial004(self, liquidacion_data):
        """
        Calcula el aporte al fondo de subsistencia
        """
        def calcular_porcentaje_subsistencia(ingreso_base, salario_minimo):
            """Determina el porcentaje según el rango de IBC"""
            if ingreso_base < 4 * salario_minimo:
                return 0.0
            elif ingreso_base <= 16 * salario_minimo:
                return 0.5
            elif ingreso_base <= 17 * salario_minimo:
                return 0.7
            elif ingreso_base <= 18 * salario_minimo:
                return 0.9
            elif ingreso_base <= 19 * salario_minimo:
                return 1.1
            elif ingreso_base <= 20 * salario_minimo:
                return 1.3
            else:
                return 1.5         

        def generar_log_rangos(ingreso_base, salario_minimo):
            """Genera log de los rangos evaluados"""
            return [
                ('≤ 4 SMMLV = 0.0%', 'Si' if ingreso_base <= 4 * salario_minimo else 'No'),
                ('> 4 SMMLV ≤ 16 SMMLV = 0.5%', 'Si' if 4 * salario_minimo < ingreso_base <= 16 * salario_minimo else 'No'),
                ('> 16 SMMLV ≤ 17 SMMLV = 0.7%', 'Si' if 16 * salario_minimo < ingreso_base <= 17 * salario_minimo else 'No'),
                ('> 17 SMMLV ≤ 18 SMMLV = 0.9%', 'Si' if 17 * salario_minimo < ingreso_base <= 18 * salario_minimo else 'No'),
                ('> 18 SMMLV ≤ 19 SMMLV = 1.1%', 'Si' if 18 * salario_minimo < ingreso_base <= 19 * salario_minimo else 'No'),
                ('> 19 SMMLV ≤ 20 SMMLV = 1.3%', 'Si' if 19 * salario_minimo < ingreso_base <= 20 * salario_minimo else 'No'),
                ('> 20 SMMLV = 1.5%', 'Si' if ingreso_base > 20 * salario_minimo else 'No')
            ]

        parametros_anuales = liquidacion_data['annual_parameters']
        salario_minimo = parametros_anuales.smmlv_monthly
        slip = liquidacion_data['payslip']
        periodo = self._get_periodo(slip).upper()
        contrato = liquidacion_data['contract']
        pasos = []
        
        # Verificar si debe proyectar
        debe_proyectar = (contrato.proyectar_fondos and slip.date_from.day <= 15)
        
        if debe_proyectar:
            total, qty_days = self._get_totalizar_categorias(
                liquidacion_data, categorias=['BASIC'], 
                incluir_current=False, incluir_before=False, incluir_multi=True
            )
            total_dev, _ = self._get_totalizar_categorias(
                liquidacion_data, categorias=['DEV_SALARIAL'], categorias_excluir="BASIC", 
                incluir_current=False, incluir_before=False, incluir_multi=True
            )
            
            if liquidacion_data['slip'].struct_type_id.wage_type == "hourly" and qty_days > 0:
                hours_daily = parametros_anuales.hours_daily
                qty_days = qty_days / hours_daily
                
            total_basic = total / qty_days if qty_days > 0 else 0
            days_project =  qty_days + 15
            BASIC = total_basic * days_project
            ingreso_base_cotizacion = (BASIC + total_dev)
            
            pasos = [
                f"Días Acumulados = {qty_days:.2f}",
                f"Salario Diario = {self._format_money(total)} ÷ {qty_days:.2f} = {self._format_money(total_basic)}",
                f"Días a Proyectar = (30 - {qty_days:.2f}) + 15 = {days_project:.2f}",
                f"BASIC Proyectado = {self._format_money(total_basic)} × {days_project:.2f} = {self._format_money(BASIC)}",
                f"IBC = {self._format_money(BASIC)} + {self._format_money(total_dev)} = {self._format_money(ingreso_base_cotizacion)}"
            ]
        else:
            ingreso_base_cotizacion = liquidacion_data['rules_computed'].IBD
            pasos = [f"IBC = {self._format_money(ingreso_base_cotizacion)}"]
        
        pasos.append(f"SMMLV = {self._format_money(salario_minimo)}")
        
        empleado = liquidacion_data['employee']
        es_pensionado = empleado.subtipo_coti_id.code not in ['00', False]
        
        # Verificar condiciones iniciales
        if (es_pensionado or 
            contrato.contract_type == 'aprendizaje' or 
            round_1_decimal(ingreso_base_cotizacion) < round_1_decimal(parametros_anuales.top_four_fsp_smmlv)):
            
            if es_pensionado:
                descripcion = "No aplica por ser pensionado"
            elif contrato.contract_type == 'aprendizaje':
                descripcion = "No aplica para contratos de aprendizaje"
            else:
                pasos.append(f"IBC {self._format_money(ingreso_base_cotizacion)} < 4 SMMLV {self._format_money(parametros_anuales.top_four_fsp_smmlv)}")
                descripcion = f"No aplica porque el IBC no supera 4 SMMLV"
                
            html = self._build_ssocial_html_log(
                periodo=periodo,
                aplicado=False,
                descripcion=descripcion,
                pasos=pasos
            )
            return 0.0, 1, 0.0, '', html, False

        # Calcular porcentaje según rango
        multiples_sm = ingreso_base_cotizacion / salario_minimo
        porcentaje = calcular_porcentaje_subsistencia(round_1_decimal(ingreso_base_cotizacion), round_1_decimal(salario_minimo))
        log_rangos = generar_log_rangos(round_1_decimal(ingreso_base_cotizacion), round_1_decimal(salario_minimo))
        
        pasos.append(f"Múltiplos SMMLV = {ingreso_base_cotizacion:.2f} ÷ {salario_minimo:.2f} = {multiples_sm:.2f}")
        pasos.append(f"Porcentaje Aplicable = {porcentaje:.2f}%")
        
        if porcentaje != 0.0:
            valor_mes_anterior = self._get_totalizar_reglas(
                liquidacion_data, 'SSOCIAL004', 
                incluir_current=True
            )
            
            if valor_mes_anterior != 0:
                base_mes_anterior = valor_mes_anterior / (porcentaje / 100)
            else:
                base_mes_anterior = 0
                
            base_calculo = ingreso_base_cotizacion - abs(base_mes_anterior)
            
            pasos.extend([
                f"Valor Acumulado = {self._format_money(valor_mes_anterior)}",
                f"Base Anterior = {self._format_money(valor_mes_anterior)} ÷ {porcentaje:.2f}% = {self._format_money(base_mes_anterior)}",
                f"Base Cálculo = {self._format_money(ingreso_base_cotizacion)} - {self._format_money(base_mes_anterior)} = {self._format_money(base_calculo)}"
            ])
            
            if ((self.aplicar_cobro == '15' and slip.date_from.day >= 15) or 
                (self.aplicar_cobro == '30' and slip.date_from.day < 15)):
                html = self._build_ssocial_html_log(
                    periodo=periodo, 
                    aplicado=False, 
                    descripcion=f"No aplica para esta quincena (Quincena: {self.aplicar_cobro}, Día inicio: {slip.date_from.day})",
                    rango_log=log_rangos,
                    pasos=pasos
                )
                return 0, 0, porcentaje, '', html, False
            
            if debe_proyectar and base_calculo > 0:
                base_calculo = base_calculo / 2
                pasos.append(f"Base Cálculo (Proyección) = {self._format_money(base_calculo * 2)} ÷ 2 = {self._format_money(base_calculo)}")
            
            html = self._build_ssocial_html_log(
                periodo=periodo, 
                aplicado=True, 
                descripcion=f"Cálculo de aporte al fondo de subsistencia ({porcentaje}% del IBC)",
                rango_log=log_rangos,
                saldo_anterior=valor_mes_anterior if valor_mes_anterior != 0 else None,
                pasos=pasos
            )
            return base_calculo, -1, porcentaje, periodo, html, False
        else:
            html = self._build_ssocial_html_log(
                periodo=periodo, 
                aplicado=False, 
                descripcion="No aplica por IBC dentro de rango exento",
                rango_log=log_rangos,
                pasos=pasos
            )
            return 0.0, 1, 0.0, '', html, False
        
    def _calculate_provision(self, data_payslip, provision_type):
        """
        Función centralizada para calcular provisiones (vacaciones, prima, cesantías, intereses)
        
        Args:
            data_payslip (dict): Diccionario con datos de liquidación
            provision_type (str): Tipo de provisión ('vacaciones', 'prima', 'cesantias', 'intereses')
            
        Returns:
            tuple: (base, días, tasa, nombre, log, datos_visuales)
        """
        employee = data_payslip['employee']
        contract = data_payslip['contract']
        slip = data_payslip['slip']
        parametros_anuales = data_payslip['annual_parameters']
        if (employee.tipo_coti_id.code in ['12', '19'] or 
            (provision_type != 'vacaciones' and contract.modality_salary == 'integral')):
            return 0, 0, 0, 0, "", {}
        struct_process = slip.struct_process
        config = {
            'vacaciones': {'campo_base': 'base_vacaciones', 'tasa': 4.17, 'nombre': "VACACIONES", 'codigo': 'PRV_VAC'},
            'prima': {'campo_base': 'base_prima', 'tasa': 8.33, 'nombre': "PRIMA", 'codigo': 'PRV_PRIM'},
            'cesantias': {'campo_base': 'base_cesantias', 'tasa': 8.33, 'nombre': "CESANTÍAS", 'codigo': 'PRV_CES'},
            'intereses': {'campo_base': 'base_cesantias', 'tasa': 1, 'nombre': "INTERESES CESANTÍAS", 'codigo': 'PRV_ICES'}
        }[provision_type]
        
        descontar_suspensiones = self.descontar_suspensiones
        
        if self.env.company.simple_provisions or self.code == 'PRV_VAC':
            herramientas = self.env['lavish.tools.nomina']
            dias_info = herramientas.calcular_dias(data_payslip)
            dias_trabajados = dias_info.get('trabajados', 0)
            dias_ausencias = dias_info.get('ausencias', 0)
           

            dias_trabajados = sum(l.number_of_days for l in slip.worked_days_line_ids if l.code == 'WORK100')
            dias_ausencias  = sum(ld.days_payslip for ld in slip.leave_days_ids
                if not ld.leave_id.holiday_status_id.unpaid_absences)
            dias_suspension  = sum(ld.days_payslip for ld in slip.leave_days_ids
                if ld.leave_id.holiday_status_id.unpaid_absences)
            dias_computables = dias_trabajados + dias_ausencias
            if descontar_suspensiones:
                dias_computables = dias_trabajados + dias_ausencias + dias_suspension            
            base_salario = (contract.wage / 30) * dias_computables
            dos_salarios_minimos = 2 * parametros_anuales.smmlv_monthly
            auxilio_transporte = (parametros_anuales.transportation_assistance_monthly / 30) * dias_computables

            conceptos_incluidos = []
            rules_multi = data_payslip.get('rules_multi', {})
            base_total = 0.0
            for code, rule_info in rules_multi.items():
                if code in ['BASIC', 'AUX000']:
                    continue
                    
                current_data = rule_info.get('current', {})
                rule_obj = current_data.get('object')
                leave_info = current_data.get('leave', {})
                
                if leave_info:
                    continue
                    
                campo_base = config['campo_base']
                if rule_obj and hasattr(rule_obj, campo_base) and getattr(rule_obj, campo_base):
                    valor = current_data.get('total', 0)
                    base_total += valor
                    if valor == 0:
                        continue
                    conceptos_incluidos.append({
                        'codigo': code,
                        'nombre': rule_obj.name,
                        'valor': valor
                    })            
            if provision_type == 'vacaciones':
                base_total += base_salario
            else:
                if contract.modality_aux == 'basico':
                    wage_for_comparison = contract.wage
                    supera_tope = wage_for_comparison >= dos_salarios_minimos
                elif contract.modality_aux == 'variable':
                    supera_tope = base_total >= dos_salarios_minimos
                else:
                    supera_tope = True
                    
                if supera_tope:
                    auxilio_transporte = 0
                base_total += base_salario + auxilio_transporte
            

            
            if provision_type == 'intereses':
                base_cesantias = herramientas.extraer_valor(data_payslip, 'PRV_CES',periodo='multi', campo='total', default=0.0)
                valor_provision = base_cesantias * 0.1
                base_intereses = base_cesantias
                base_total = base_cesantias
            else:
                valor_provision = base_total * (config['tasa'] / 100)
                base_intereses = None
                
            saldo_contable = self._obtener_saldo_contable_provision(data_payslip, config['codigo'])
            
            es_liquidacion = data_payslip['slip'].struct_process == 'contrato'
            valor_liquidacion = None
            if data_payslip['slip'].struct_process == 'contrato':
                valor_liquidacion = self._obtener_valor_liquidacion(data_payslip, provision_type)
            
            html_builder = ProvisionHTMLBuilder(provision_type)
            
            html_builder.add_days_info(dias_trabajados, dias_ausencias, dias_suspension)
            
            html_builder.add_formula_info()
            
            html_builder, _ = html_builder.add_base_concepts(base_salario, auxilio_transporte, conceptos_incluidos)
            
            html_builder.add_intereses_note()
            
            if provision_type == 'intereses':
                html_builder.add_result(
                    base_intereses, config['tasa'], valor_provision, 
                    saldo_contable, valor_liquidacion
                )
            else:
                html_builder.add_result(
                    base_total, config['tasa'], valor_provision, 
                    saldo_contable, valor_liquidacion
                )
            
            log_html = html_builder.generate()
            
            data_visual = {
                'base_total': base_total,
                'dias_trabajados': dias_trabajados,
                'dias_ausencias': dias_ausencias,
                'dias_suspension': dias_suspension,
                'conceptos_incluidos': conceptos_incluidos,
                'saldo_contable': saldo_contable
            }
            
            if provision_type == 'intereses':
                data_visual['base_cesantias'] = base_intereses
                
            if es_liquidacion:
                data_visual['valor_liquidacion'] = valor_liquidacion
                data_visual['es_liquidacion'] = True
                
            nombre = f"{config['nombre']} SIMPLE"
            tasa = config['tasa']
            if es_liquidacion:
                nombre = f"PROVISIÓN {config['nombre']} - SALDO CONTABLE:  ${saldo_contable:,.2f} - A PAGAR: ${valor_liquidacion:,.2f}"
                base_total = (valor_liquidacion - saldo_contable) 
                dias = 1
                tasa = 100
            return base_total, 1, tasa, nombre, log_html, data_visual
        
        prestaciones_service = self.env['prestaciones.sociales.service']
        
        kwargs = {'es_visual': True, 'es_provision': True}
        
        if provision_type == 'prima':
            from_month = 1 if slip.date_from.month <= 6 else 7
            to_month = 6 if slip.date_from.month <= 6 else 12
            to_day = 30 if slip.date_from.month <= 6 else 31
            date_from = slip.date_from.replace(month=from_month, day=1)
            date_to = slip.date_to
            if date_from < contract.date_start:
                date_from = contract.date_start
            if data_payslip['slip'].struct_process == 'contrato' or data_payslip['slip'].date_liquidacion:
                date_to = data_payslip['slip'].date_liquidacion
        
        elif provision_type in ['cesantias', 'intereses']:
            date_ref = slip.date_to
            date_from = date_ref.replace(month=1, day=1)
            date_to = slip.date_to
            if date_from < contract.date_start:
                date_from = contract.date_start
            if data_payslip['slip'].struct_process == 'contrato' or data_payslip['slip'].date_liquidacion:
                date_to = data_payslip['slip'].date_liquidacion
            
        
        resultado = prestaciones_service.obtener_base(
            localdict=data_payslip,
            tipo_prestacion=provision_type,
            regla_obj=self,
            es_visual=True,
            es_provision=True,
            fecha_inicio=date_from,
            fecha_fin=date_to)
        
        if provision_type == 'vacaciones':
            base_dias = resultado['resultado_compatible']['base']
            dias = resultado['resultado_compatible']['days']
            tasa = 4.17
        elif provision_type in ['prima', 'cesantias']:
            base_dias = resultado['data_visual']['meta_info']['diferencia_provision'] / resultado['resultado_compatible']['days']
            dias = resultado['resultado_compatible']['days']
            tasa = 100
        elif provision_type == 'intereses':
            herramientas = self.env['lavish.tools.nomina']
            base_dias = resultado['data_visual']['meta_info']['diferencia_provision'] / resultado['resultado_compatible']['days']
            dias = resultado['resultado_compatible']['days']
            dias_anio = days360(
                date_from,
                date_to
            )
            tasa = 100 #(dias_anio / DAYS_YEAR) * 12  # 12% anual prorrateado
            resultado['data_visual']['base_cesantias'] = herramientas.extraer_valor(data_payslip, 'PRV_CES', campo='total', default=0.0)
        
        log_html = resultado.get('log_html', '')
        data_visual = resultado.get('data_visual', {})
        
        saldo_contable = self._obtener_saldo_contable_provision(data_payslip, config['codigo'])
        data_visual['saldo_contable'] = saldo_contable
        
        es_liquidacion = slip.date_liquidacion and True or False
        if data_payslip['slip'].struct_process == 'contrato':
            valor_liquidacion = self._obtener_valor_liquidacion(data_payslip, provision_type)
            data_visual['valor_liquidacion'] = valor_liquidacion
            data_visual['es_liquidacion'] = True
            base_dias = (valor_liquidacion - saldo_contable) 
            dias = 1
            tasa = 100
            nombre = f"PROVISIÓN {config['nombre']} - SALDO CONTABLE: ${saldo_contable:,.2f} - A PAGAR: ${valor_liquidacion:,.2f}"
        else:
            nombre = f"PROVISIÓN {config['nombre']}"
        
        return base_dias, dias, tasa, nombre, log_html, data_visual

    def _obtener_saldo_contable_provision(self, data_payslip, codigo_regla):
        """
        Obtiene el saldo contable de la provisión usando las cuentas contables directamente del objeto self
        
        Args:
            data_payslip (dict): Diccionario con datos de liquidación
            codigo_regla (str): Código de la regla salarial de provisión
            
        Returns:
            float: Saldo contable de la provisión
        """
        employee = data_payslip['employee']
        slip = data_payslip['slip']
        
        AccountMove = self.env['account.move.line']
        account_ids = [self.account_credit.id] + self.salary_rule_accounting.mapped('credit_account').ids

        domain = [
            ('account_id', 'in', account_ids),
            ('move_id.state', '=', 'posted'),
            ('partner_id', '=', self._get_employee_address_id(employee).id),
            ('date', '<=', slip.date_to)
        ]
        provision_lines = AccountMove.search(domain)
        return sum(line.credit - line.debit for line in provision_lines)
    
    def _get_employee_address_id(self, employee):
        """
        Obtiene el ID de dirección del empleado de manera compatible con diferentes versiones de Odoo
        
        Args:
            employee (hr.employee): Objeto empleado
            
        Returns:
            int: ID de la dirección del empleado (partner_id)
        """
        if hasattr(employee, 'address_home_id') and employee.address_home_id:
            return employee.address_home_id
        elif hasattr(employee, 'work_contact_id') and employee.work_contact_id:
            return employee.work_contact_id
        return False
    
    def _obtener_valor_liquidacion(self, data_payslip, provision_type):
        """
        Obtiene el valor a pagar en liquidación usando rules_multi
        
        Args:
            data_payslip (dict): Diccionario con datos de liquidación
            provision_type (str): Tipo de provisión
            
        Returns:
            float: Valor a pagar en liquidación
        """
        rule_code_map = {
            'vacaciones': 'VACCONTRATO',
            'prima': 'PRIMA',
            'cesantias': 'CESANTIAS',
            'intereses': 'INTCESANTIAS'
        }
        
        codigo_liquidacion = rule_code_map.get(provision_type)
        if not codigo_liquidacion:
            return 0
        
        rules_multi = data_payslip.get('rules_multi', {})
        if codigo_liquidacion in rules_multi and 'current' in rules_multi[codigo_liquidacion]:
            return rules_multi[codigo_liquidacion]['current'].get('total', 0)
        
        return 0

    def _prv_vac(self, data_payslip):
        """
        Calcula la provisión de vacaciones
        Args:
            data_payslip (dict): Diccionario con datos de liquidación
        Returns:
            tuple: (base, días, tasa, nombre, log, datos_vacaciones)
        """
        return self._calculate_provision(data_payslip, 'vacaciones')

    def _prv_prim(self, data_payslip):
        """
        Calcula la provisión de prima
        Args:
            data_payslip (dict): Diccionario con datos de liquidación
        Returns:
            tuple: (base, días, tasa, nombre, log, datos_prima)
        """
        return self._calculate_provision(data_payslip, 'prima')

    def _prv_ces(self, data_payslip):
        """
        Calcula la provisión de cesantías
        Args:
            data_payslip (dict): Diccionario con datos de liquidación
        Returns:
            tuple: (base, días, tasa, nombre, log, datos_cesantias)
        """
        return self._calculate_provision(data_payslip, 'cesantias')

    def _prv_ices(self, data_payslip):
        """
        Calcula la provisión de intereses de cesantías
        Args:
            data_payslip (dict): Diccionario con datos de liquidación
        Returns:
            tuple: (base, días, tasa, nombre, log, datos_intereses)
        """
        return self._calculate_provision(data_payslip, 'intereses')
    
    def get_holiday_book(self, contract, date_from=False, date_ref=False):
        """
        Calcula los días de vacaciones acumulados y disponibles para un empleado
        
        Args:
            contract: Contrato del empleado
            date_ref: Fecha de referencia para el cálculo (por defecto, fecha actual)
            
        Returns:
            dict: Diccionario con información de días trabajados, disponibles, disfrutados, etc.
        """
        date_ref = date_ref or contract.date_ref_holiday_book or datetime.now()
        prestaciones_service = self.env['prestaciones.sociales.service']
        worked_days = days360(date_from, date_ref)
        
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
        
        days_left = (worked_days_adjusted * 15 / DAYS_YEAR) #- days_enjoyed
        return {
            'worked_days': round_1_decimal(worked_days),
            'worked_days_adjusted': round_1_decimal(worked_days_adjusted),
            'days_left': round_1_decimal(days_left),
            'days_enjoyed': round_1_decimal(days_enjoyed),
            'days_paid': round_1_decimal(days_paid),
            'days_suspension': round_1_decimal(days_suspension),
        }

    def _vaccontrato(self, data_payslip):
        """
        Calcula vacaciones por terminación de contrato usando el servicio de prestaciones
        
        Args:
            data_payslip (dict): Diccionario con datos de liquidación
            
        Returns:
            tuple: (base, días, tasa, nombre, log_html, datos_vacaciones)
        """
        # Inicializar log HTML
        log_html = ['<div class="vacation-log">']
        log_html.append('<h3 style="color:#2c5282;">Cálculo de Vacaciones por Terminación de Contrato</h3>')
        log_html.append('<div class="section">')
        
        def format_currency(value):
            """Formatea valores monetarios para el log"""
            if isinstance(value, Decimal):
                value = float(value)
            return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        
        def calcular_base_sin_basic_aux(concepts_info):
            """Calcula la base variable sin incluir conceptos básicos ni auxilios"""
            total_base = Decimal('0')
            
            log_html.append('<h4 style="color:#4299e1;">Conceptos Variables Incluidos en Base</h4>')
            log_html.append('<table style="width:100%; border-collapse:collapse; margin-bottom:15px;">')
            log_html.append('<tr style="background-color:#ebf4ff;">')
            log_html.append('<th style="border:1px solid #a0aec0; padding:8px; text-align:left;">Código</th>')
            log_html.append('<th style="border:1px solid #a0aec0; padding:8px; text-align:left;">Nombre</th>')
            log_html.append('<th style="border:1px solid #a0aec0; padding:8px; text-align:right;">Valor</th>')
            log_html.append('<th style="border:1px solid #a0aec0; padding:8px; text-align:center;">Incluido</th>')
            log_html.append('</tr>')
            
            conceptos_count = 0
            for concept_code, concept_data in concepts_info.items():
                incluido = concept_data.get('base_fields', {}).get('base_vacaciones', False)
                categoria = concept_data.get('categoria', '')
                nombre = concept_data.get('nombre', concept_code)
                valor = concept_data.get('total', Decimal('0'))
                if not incluido:
                    continue
                incluido_txt = "✓" if incluido and categoria not in ['BASIC', 'AUX'] else "✗"
                color = "#e6ffed" if incluido and categoria not in ['BASIC', 'AUX'] else "#fff5f5"
                
                log_html.append(f'<tr style="background-color:{color};">')
                log_html.append(f'<td style="border:1px solid #a0aec0; padding:8px;">{concept_code}</td>')
                log_html.append(f'<td style="border:1px solid #a0aec0; padding:8px;">{nombre}</td>')
                log_html.append(f'<td style="border:1px solid #a0aec0; padding:8px; text-align:right;">{format_currency(valor)}</td>')
                log_html.append(f'<td style="border:1px solid #a0aec0; padding:8px; text-align:center;">{incluido_txt}</td>')
                log_html.append('</tr>')
                
                if incluido and categoria not in ['BASIC', 'AUX']:
                    total_base += valor
                    conceptos_count += 1
            
            if conceptos_count == 0:
                log_html.append('<tr>')
                log_html.append('<td colspan="5" style="border:1px solid #a0aec0; padding:8px; text-align:center;">No hay conceptos variables que apliquen para la base</td>')
                log_html.append('</tr>')
            
            log_html.append('</table>')
            log_html.append(f'<p><strong>Total base variable:</strong> ${format_currency(total_base)}</p>')
            
            return total_base
        
        employee = data_payslip['employee']
        contract = data_payslip['contract']
        payslip = data_payslip['slip']
        struct_process = payslip.struct_process
        descontar_suspensiones = self.descontar_suspensiones
        
        log_html.append('<h4 style="color:#4299e1;">Información General</h4>')
        log_html.append('<table style="width:100%; border-collapse:collapse; margin-bottom:15px;">')
        log_html.append('<tr><td style="padding:4px;"><strong>Empleado:</strong></td><td style="padding:4px;">' + employee.name + '</td></tr>')
        log_html.append('<tr><td style="padding:4px;"><strong>Número de Documento:</strong></td><td style="padding:4px;">' + (employee.identification_id or '') + '</td></tr>')
        log_html.append('<tr><td style="padding:4px;"><strong>Contrato:</strong></td><td style="padding:4px;">' + contract.name + '</td></tr>')
        log_html.append('<tr><td style="padding:4px;"><strong>Fecha Inicio:</strong></td><td style="padding:4px;">' + contract.date_start.strftime('%d/%m/%Y') + '</td></tr>')
        log_html.append('<tr><td style="padding:4px;"><strong>Tipo de Proceso:</strong></td><td style="padding:4px;">' + struct_process + '</td></tr>')
        log_html.append('<tr><td style="padding:4px;"><strong>Periodo Nómina:</strong></td><td style="padding:4px;">' + payslip.date_from.strftime('%d/%m/%Y') + ' - ' + payslip.date_to.strftime('%d/%m/%Y') + '</td></tr>')
        log_html.append('</table>')
        
        if employee.tipo_coti_id.code in ['12', '19']:
            log_html.append('<div class="alert" style="background-color:#fff5f5; padding:10px; border-left:4px solid #f56565; margin-bottom:15px;">')
            log_html.append('<p><strong>⚠️ El empleado no tiene derecho a vacaciones</strong> por su tipo de cotizante (aprendiz o practicante)</p>')
            log_html.append('</div>')
            log_html.append('</div>')  # Cerrar section
            log_html.append('</div>')  # Cerrar vacation-log
            return 0, 0, 0, 0, "".join(log_html), {}
        
        date_to = payslip.date_to
        if struct_process == 'contrato':
            date_to = payslip.date_liquidacion
        date_from = contract.date_start
        if struct_process == 'contrato':
            date_from = payslip.date_vacaciones or contract.date_start           
        log_html.append(f'<p><strong>Fecha fin para cálculo:</strong> {date_from.strftime("%d/%m/%Y")}</p>')
        
        data_vacaciones = self.get_holiday_book(contract, date_from, date_to)
        
        log_html.append('<h4 style="color:#4299e1;">Cálculo de Días de Vacaciones</h4>')
        log_html.append('<table style="width:100%; border-collapse:collapse; margin-bottom:15px;">')
        log_html.append('<tr style="background-color:#ebf4ff;">')
        log_html.append('<th style="border:1px solid #a0aec0; padding:8px; text-align:left;">Concepto</th>')
        log_html.append('<th style="border:1px solid #a0aec0; padding:8px; text-align:right;">Días</th>')
        log_html.append('</tr>')
        
        log_html.append('<tr>')
        log_html.append(f'<td style="border:1px solid #a0aec0; padding:8px;">Días trabajados totales</td>')
        log_html.append(f'<td style="border:1px solid #a0aec0; padding:8px; text-align:right;">{data_vacaciones["worked_days"]}</td>')
        log_html.append('</tr>')
        
        log_html.append('<tr>')
        log_html.append(f'<td style="border:1px solid #a0aec0; padding:8px;">Días de suspensión</td>')
        log_html.append(f'<td style="border:1px solid #a0aec0; padding:8px; text-align:right;">{data_vacaciones["days_suspension"]}</td>')
        log_html.append('</tr>')
        
        if descontar_suspensiones:
            log_html.append('<tr style="background-color:#e6ffed;">')
            log_html.append(f'<td style="border:1px solid #a0aec0; padding:8px;"><strong>Días trabajados ajustados</strong> (descontando suspensiones)</td>')
            log_html.append(f'<td style="border:1px solid #a0aec0; padding:8px; text-align:right;"><strong>{data_vacaciones["worked_days_adjusted"]}</strong></td>')
            log_html.append('</tr>')
        else:
            log_html.append('<tr>')
            log_html.append('<td style="border:1px solid #a0aec0; padding:8px; color:#718096;" colspan="2">No se descuentan días de suspensión por configuración de la regla</td>')
            log_html.append('</tr>')
        
        log_html.append('<tr>')
        log_html.append(f'<td style="border:1px solid #a0aec0; padding:8px;">Días disfrutados</td>')
        log_html.append(f'<td style="border:1px solid #a0aec0; padding:8px; text-align:right;">{data_vacaciones["days_enjoyed"]}</td>')
        log_html.append('</tr>')
        
        log_html.append('<tr style="background-color:#ebf8ff;">')
        log_html.append(f'<td style="border:1px solid #a0aec0; padding:8px;"><strong>Días disponibles para liquidar</strong></td>')
        log_html.append(f'<td style="border:1px solid #a0aec0; padding:8px; text-align:right;"><strong>{data_vacaciones["days_left"]}</strong></td>')
        log_html.append('</tr>')
        
        log_html.append('</table>')
        
        dias_calc = data_vacaciones["worked_days_adjusted"] if descontar_suspensiones else data_vacaciones["worked_days"]
        formula = f"({dias_calc} días trabajados × 15 días) ÷ 360 días - {data_vacaciones['days_enjoyed']} días disfrutados = {data_vacaciones['days_left']} días"
        log_html.append(f'<p><strong>Fórmula aplicada:</strong> {formula}</p>')
        
        log_html.append('<h4 style="color:#4299e1;">Base Diaria para Liquidación</h4>')
        
        prestaciones_service = self.env['prestaciones.sociales.service']
        wage = contract.wage / DAYS_MONTH
        
        log_html.append('<table style="width:100%; border-collapse:collapse; margin-bottom:15px;">')
        log_html.append('<tr style="background-color:#ebf4ff;">')
        log_html.append('<th style="border:1px solid #a0aec0; padding:8px; text-align:left;">Componente</th>')
        log_html.append('<th style="border:1px solid #a0aec0; padding:8px; text-align:right;">Valor Diario</th>')
        log_html.append('</tr>')
        
        log_html.append('<tr>')
        log_html.append(f'<td style="border:1px solid #a0aec0; padding:8px;">Salario básico diario (${format_currency(contract.wage)} ÷ 30)</td>')
        log_html.append(f'<td style="border:1px solid #a0aec0; padding:8px; text-align:right;">${format_currency(wage)}</td>')
        log_html.append('</tr>')
        
        variable = prestaciones_service._collect_concepts_info(data_payslip, periodos=['last_year', 'multi'])
        total_base_variable = calcular_base_sin_basic_aux(variable)
        
        dias_promedio = dias_calc
        if total_base_variable > 0:
            base_diaria_variable = total_base_variable / Decimal(dias_promedio)
            log_html.append('<tr>')
            log_html.append(f'<td style="border:1px solid #a0aec0; padding:8px;">Salario variable diario (${format_currency(total_base_variable)} ÷ {dias_promedio})</td>')
            log_html.append(f'<td style="border:1px solid #a0aec0; padding:8px; text-align:right;">${format_currency(base_diaria_variable)}</td>')
            log_html.append('</tr>')
        else:
            base_diaria_variable = Decimal('0')
            log_html.append('<tr>')
            log_html.append('<td style="border:1px solid #a0aec0; padding:8px;">Salario variable diario</td>')
            log_html.append('<td style="border:1px solid #a0aec0; padding:8px; text-align:right;">$0,00</td>')
            log_html.append('</tr>')
        
        base_diaria_total = ((Decimal(wage) + Decimal(base_diaria_variable)) * Decimal(30)/Decimal(720))
        
        log_html.append('<tr style="background-color:#ebf8ff; font-weight:bold;">')
        log_html.append('<br/><td style="border:1px solid #a0aec0; padding:8px;">TOTAL BASE DIARIA FORMULA</td> ')
        log_html.append(f'<td style="border:1px solid #a0aec0; padding:8px; text-align:right;">(${format_currency(wage)} + ${format_currency(base_diaria_variable)}) * 30 / 720 = ${format_currency(base_diaria_total)} </td>')
        log_html.append('<br/><td style="border:1px solid #a0aec0; padding:8px;">TOTAL BASE DIARIA</td> ')
        log_html.append(f'<td style="border:1px solid #a0aec0; padding:8px; text-align:right;">${format_currency(base_diaria_total)}</td>')
        log_html.append('</tr>')
        log_html.append('</table>')
        
        monto_vacaciones = Decimal(base_diaria_total) * Decimal(dias_promedio)
        
        log_html.append('<h4 style="color:#4299e1;">Liquidación Final de Vacaciones</h4>')
        log_html.append('<div style="background-color:#ebf8ff; padding:15px; border-radius:5px; margin-bottom:15px;">')
        log_html.append(f'<p><strong>Base diaria</strong> × <strong>Días disponibles</strong> = <strong>Total a pagar</strong></p>')
        log_html.append(f'<p>${format_currency(base_diaria_total)} × {dias_calc} días = ${format_currency(monto_vacaciones)}</p>')
        log_html.append('</div>')
        
        log_html.append('</div>') 
        log_html.append('</div>')  
        
        log_completo_html = "".join(log_html)
        
        datos_vacaciones = {
            'data_kpi': data_vacaciones,
            'base_diaria': base_diaria_total,
            'base_diaria_variable': base_diaria_variable,
            'base_diaria_fija': wage,
            'fecha_inicio':date_from,
            'fecha_fin':date_to,
            'total_variable': total_base_variable,
            'descontar_suspensiones': descontar_suspensiones,
            'monto_total': float(monto_vacaciones),
            'amount_base': ((Decimal(wage) + base_diaria_variable )* Decimal(30) )
        }

        
        return base_diaria_total, dias_promedio, 100, self._label_vac_liq(data_vacaciones['days_left'],data_vacaciones['days_enjoyed']), log_completo_html, datos_vacaciones
    
    def _round1(self, amount: Decimal | float) -> Decimal:
        """Redondea al entero más cercano (sin decimales) usando Decimal."""
        from decimal import Decimal, ROUND_HALF_UP
        if not isinstance(amount, Decimal):
            amount = Decimal(str(amount))
        return amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP)

    def _label_vac_liq(
        self,
        days_pending: Decimal | float,
        days_enjoyed: Decimal | float,
    ) -> str:
        """Construye la etiqueta *VACACIONES LIQ.* con acrónimos y emojis. 
        """
        icon_pending = '$' 
        icon_enjoyed = "" 
        dpp = f"D.P.P=({icon_pending} {round(days_pending,2)})"
        ddf = f"D.D.F=({icon_enjoyed} {round(days_enjoyed,2)})"
        return f"VACACIONES LIQ. DE CONTRATO {dpp} {ddf}"

    def _prima(self, data_payslip):
        """
        Calcula prima de servicios usando el servicio de prestaciones
        Args:
            data_payslip (dict): Diccionario con datos de liquidación
        Returns:
            tuple: (base, días, tasa, nombre, log, datos_prima)
        """
        employee = data_payslip['employee']
        contract = data_payslip['contract']
        
        if (employee.tipo_coti_id.code in ['12', '19'] or
            contract.modality_salary == 'integral'):
            return 0, 0, 0, 0, "", {}
        
        prestaciones_service = self.env['prestaciones.sociales.service']
        from_month = 1 if data_payslip['slip'].date_from.month <= 6 else 7
        to_month = 6 if data_payslip['slip'].date_from.month <= 6 else 12
        to_day = 30 if data_payslip['slip'].date_from.month <= 6 else 31
        date_from = data_payslip['slip'].date_from.replace(month=from_month, day=1)
        date_to = data_payslip['slip'].date_from.replace(month=to_month, day=to_day)
        if data_payslip['slip'].struct_process == 'contrato':
            date_to = data_payslip['slip'].date_liquidacion
        if date_from < data_payslip['contract'].date_start:
            date_from = data_payslip['contract'].date_start
        resultado = prestaciones_service.obtener_base(
            localdict=data_payslip,
            tipo_prestacion='prima',
            regla_obj=self,
            es_visual=True,
            fecha_inicio=date_from,
            fecha_fin=date_to
        )
        
        base_dias = resultado['resultado_compatible']['base']
        log_html = resultado.get('log_html', '')
        data_visual = resultado.get('data_visual', {})
        
        fecha_fin = data_payslip['slip'].date_to
        semestre = 1 if fecha_fin.month <= 6 else 2
        nombre = f"PRIMA DE SERVICIOS {semestre}° SEMESTRE {fecha_fin.year}"
        
        return base_dias, resultado['resultado_compatible']['days'], 100, nombre, log_html, {'data_kpi': data_visual}

    def _cesantias(self, data_payslip):
        """
        Calcula cesantías usando el servicio de prestaciones
        Args:
            data_payslip (dict): Diccionario con datos de liquidación
        Returns:
            tuple: (base, días, tasa, nombre, log, datos_cesantias)
        """
        employee = data_payslip['employee']
        contract = data_payslip['contract']
        
        if (employee.tipo_coti_id.code in ['12', '19'] or
            contract.modality_salary == 'integral'):
            return 0, 0, 0, 0, "", {}
        
        prestaciones_service = self.env['prestaciones.sociales.service']
        date_ref = data_payslip['slip'].date_to
        date_from = date_ref.replace(month=1, day=1)
        date_to = date_ref.replace(month=12, day=31)
        if date_from < data_payslip['contract'].date_start:
            date_from = data_payslip['contract'].date_start
        if data_payslip['slip'].struct_process == 'contrato' or data_payslip['slip'].date_liquidacion:
            date_to = data_payslip['slip'].date_liquidacion
        resultado = prestaciones_service.obtener_base(
            localdict=data_payslip,
            tipo_prestacion='cesantias',
            regla_obj=self,
            es_visual=True,
            fecha_inicio=date_from,
            fecha_fin=date_to
        )
        
        base_dias = resultado['resultado_compatible']['base']
        log_html = resultado.get('log_html', '')
        data_visual = resultado.get('data_visual', {})
        
        fecha_fin = data_payslip['slip'].date_to
        nombre = f"CESANTÍAS AÑO {fecha_fin.year}"
        
        return base_dias, resultado['resultado_compatible']['days'], 100, nombre, log_html, {'data_kpi': data_visual}

    def _intcesantias(self, data_payslip):
        """
        Calcula intereses de cesantías usando el servicio de prestaciones
        Args:
            data_payslip (dict): Diccionario con datos de liquidación
        Returns:
            tuple: (base, días, tasa, nombre, log, datos_intereses)
        """
        employee = data_payslip['employee']
        contract = data_payslip['contract']
        payslip = data_payslip['slip']
        
        if (employee.tipo_coti_id.code in ['12', '19'] or
            contract.modality_salary == 'integral'):
            return 0, 0, 0, 0, "", {}
        
        is_interest_process = payslip.struct_id.process == 'nomina'
        should_pay_in_payroll = payslip.pay_cesantias_in_payroll
        
        if is_interest_process and should_pay_in_payroll:
            return 0, 0, 0, 0, "", {}
        
        prestaciones_service = self.env['prestaciones.sociales.service']
        date_ref = data_payslip['slip'].date_to
        date_from = date_ref.replace(month=1, day=1)
        date_to = date_ref.replace(month=12, day=31)
        if date_from < data_payslip['contract'].date_start:
            date_from = data_payslip['contract'].date_start
        if data_payslip['slip'].struct_process == 'contrato' or data_payslip['slip'].date_liquidacion:
            date_to = data_payslip['slip'].date_liquidacion
        resultado = prestaciones_service.obtener_base(
            localdict=data_payslip,
            tipo_prestacion='intereses',
            regla_obj=self,
            es_visual=True,
            fecha_inicio=date_from,
            fecha_fin=date_to
        )
        
        base_dias = resultado['resultado_compatible']['base']
        log_html = resultado.get('log_html', '')
        data_visual = resultado.get('data_visual', {})
        
        fecha_fin = data_payslip['slip'].date_to
        tasa = (resultado['resultado_compatible']['days'] / DAYS_YEAR) * 12  # 12% anual prorrateado
        
        nombre = f"INTERESES CESANTÍAS AÑO {fecha_fin.year}"
        
        return base_dias, resultado['resultado_compatible']['days'], tasa, nombre, log_html, {'data_kpi': data_visual}

    def _intces_year(self, data_payslip):
        """
        Calcula intereses de cesantías del año anterior
        Args:
            data_payslip (dict): Diccionario con datos de liquidación
        Returns:
            tuple: (base, días, tasa, nombre, log, datos_intereses)
        """
        employee = data_payslip['employee']
        contract = data_payslip['contract']
        payslip = data_payslip['slip']
        
        skip = employee.tipo_coti_id.code in ['12', '19']
        skip |= contract.modality_salary == 'integral'
        skip |= contract.date_start.year == payslip.date_to.year
        
        if skip:
            return 0, 0, 0, 0, "", {}
        
        should_pay_in_payroll = payslip.pay_cesantias_in_payroll
        
        if not should_pay_in_payroll:
            return 0, 0, 0, 0, "", {}
        
        date_ref = payslip.date_to.replace(year=payslip.date_to.year - 1)
        date_from = date_ref.replace(month=1, day=1)  
        date_to = date_ref.replace(month=12, day=31)

        if date_from < contract.date_start:
            date_from = contract.date_start
        
        prestaciones_service = self.env['prestaciones.sociales.service']
        
        resultado = prestaciones_service.obtener_base(
            localdict=data_payslip,
            tipo_prestacion='intereses',
            regla_obj=self,
            es_visual=True,
            fecha_inicio=date_from,
            fecha_fin=date_to,
            periodo_texto=f"Año Anterior {date_from.year}"
        )
        
        base_dias = resultado['resultado_compatible']['base']
        log_html = resultado.get('log_html', '')
        data_visual = resultado.get('data_visual', {})
        
        nombre = f"INT. CESANTIAS DEL PERIODO ANTERIOR {date_to.year}"
        tasa = (resultado['resultado_compatible']['days'] / DAYS_YEAR) * 12 
        return base_dias, resultado['resultado_compatible']['plain_days'], tasa, nombre, log_html, {'data_kpi': data_visual}

    def _ces_year(self, data_payslip):
        """
        Calcula cesantías del año anterior
        Args:
            data_payslip (dict): Diccionario con datos de liquidación
        Returns:
            tuple: (base, días, tasa, nombre, log, datos_cesantias)
        """
        employee = data_payslip['employee']
        contract = data_payslip['contract']
        payslip = data_payslip['slip']
        
        skip = employee.tipo_coti_id.code in ['12', '19']
        skip |= contract.modality_salary == 'integral'
        skip |= contract.date_start.year == payslip.date_to.year
        
        if skip:
            return 0, 0, 0, 0, "", {}
        
        for payments in payslip.severance_payments_reverse:
            if payments.type_history in ('cesantias', 'all'):
                tot_rule = payments.severance_value 
                return tot_rule, 1, 100, f"{self.name} {payments.final_accrual_date.year}", "", {}
        
        is_liquidation = payslip.struct_process == 'contrato'
        is_jan_feb = payslip.date_to.month in [1, 2]
        has_previous_year_option = payslip.pagar_cesantias_ano_anterior

        if not (is_liquidation and is_jan_feb and has_previous_year_option):
            return 0, 0, 0, 0, "", {}
        
        date_ref = payslip.date_to.replace(year=payslip.date_to.year - 1)
        date_from = date_ref.replace(month=1, day=1)  
        date_to = date_ref.replace(month=12, day=31)

        if date_from < contract.date_start:
            date_from = contract.date_start
        
        prestaciones_service = self.env['prestaciones.sociales.service']
        
        resultado = prestaciones_service.obtener_base(
            localdict=data_payslip,
            tipo_prestacion='cesantias',
            regla_obj=self,
            es_visual=True,
            fecha_inicio=date_from,
            fecha_fin=date_to,
            periodo_texto=f"Año Anterior {date_from.year}"
        )
        
        base_dias = resultado['resultado_compatible']['base']
        log_html = resultado.get('log_html', '')
        data_visual = resultado.get('data_visual', {})
        
        nombre = f"CESANTIAS DEL PERIODO ANTERIOR {date_from.year}"
        
        return base_dias, resultado['resultado_compatible']['plain_days'], 100, nombre, log_html, {'data_kpi': data_visual}

    def _totaldev(self, ld): #	TOTALDEV
        base = 0
        rate = 100
        name = ''
        log = ''
        total_earnings = ld['categories'].DEV_SALARIAL + ld['categories'].DEV_NO_SALARIAL + ld['categories'].PRESTACIONES_SOCIALES
        base = total_earnings
        return base,1,rate,name,log,False

    def _totalded(self, ld): # 	TOTALDED
        base = 0
        rate = 100
        name = ''
        log = ''
        total_deductions = ld['categories'].DEDUCCIONES
        if ld['contract'].limit_deductions and total_deductions > 0.5 * ld['concepts'].TOTALDEV:
            if ld['slip'].struct_process == 'Nomina':
                raise UserError(u"La nomina de {emp} presenta un total de deducciones "
                              u"superior al 50% de los devengos y el contrato esta configurado para limitarlo.".format(
                                emp=ld['employee'].name))
        base = total_deductions
        return base,1,rate,name,log,False

    def _net(self, ld):
        """
        Neto a pagar
        :param ld:
        :return: Valor a pagar al empleado
        """
        base = 0
        rate = 100
        name = ''
        log = ''
        total_earnings = ld['categories'].TOTALDEV
        total_deductions = ld['categories'].TOTALDED
        neto = total_earnings + total_deductions 
        # neto = 0 if neto < 0 else neto
        base = neto
        return base,1,rate,name,log,False
    
    def get_last_year(self, data_payslip, date_to):
        date_from = date_to - relativedelta(years=1)
        if date_from < data_payslip['contract'].date_start:
            date_from = data_payslip['contract'].date_start
        days = days360(date_from, date_to)
        dias_ausencias =  sum([i.number_of_days for i in self.env['hr.leave'].search([('date_from','>=',data_payslip['slip'].date_vacaciones),('date_to','<=',data_payslip['slip'].date_liquidacion),('state','=','validate'),('employee_id','=',data_payslip['slip'].employee_id.id),('unpaid_absences','=',True)])])
        dias_ausencias += sum([i.days for i in self.env['hr.absence.history'].search([('star_date', '>=', data_payslip['slip'].date_vacaciones), ('end_date', '<=', data_payslip['slip'].date_liquidacion),('employee_id', '=', data_payslip['slip'].employee_id.id), ('leave_type_id.unpaid_absences', '=', True)])])
        wd = days - dias_ausencias
        data = {}
        values_base_compensation = 0.0
        result_rules = data_payslip['result_rules_co']
        for rule_code, rule_data in result_rules.dict.items():
            total = rule_data.get('total', 0)
            if rule_code != 'BASIC' and rule_code != 'AUX000' and rule_data.get('base_prima', False):
                values_base_compensation += total
        acumulatdo = self.get_accumulated_compensation(data_payslip, date_from, date_to, values_base_compensation)
        return acumulatdo# / 30
    
    def get_accumulated_compensation(self, data_payslip, date_start, date_end, values_base_compensation):
        date_start = date_end-relativedelta(years=1)
        date_start = data_payslip['contract'].date_start if date_start <= data_payslip['contract'].date_start else date_start
        dias_trabajados = days360(date_start, date_end)
        # formatear fechas
        date_start = str(date_start.year) + '-' + str(date_start.month) + '-' + str(date_start.day)
        date_end = str(date_end.year) + '-' + str(date_end.month) + '-' + str(date_end.day)

        self.env.cr.execute("""Select Sum(accumulated) as accumulated
                                From
                                (
                                    Select COALESCE(sum(pl.total),0) as accumulated 
                                        From hr_payslip as hp 
                                        Inner Join hr_payslip_line as pl on  hp.id = pl.slip_id 
                                        Inner Join hr_salary_rule hc on pl.salary_rule_id = hc.id and hc.base_compensation = true
                                        Inner Join hr_salary_rule_category hsc on hc.category_id = hsc.id and (hsc.code != 'BASIC' or hc.code='BASICTURNOS')
                                        WHERE hp.state = 'done' and hp.contract_id = %s
                                        AND (hp.date_from between %s and %s
                                            or
                                            hp.date_to between %s and %s )
                                    Union 
                                    Select COALESCE(sum(pl.amount),0) as accumulated
                                        From hr_accumulated_payroll as pl
                                        Inner Join hr_salary_rule hc on pl.salary_rule_id = hc.id and hc.base_compensation = true
                                        Inner Join hr_salary_rule_category hsc on hc.category_id = hsc.id and (hsc.code != 'BASIC' or hc.code='BASICTURNOS')
                                        WHERE pl.employee_id = %s and pl.date between %s and %s
                                ) As A""",
                            (data_payslip['contract'].id, date_start, date_end, date_start, date_end, data_payslip['contract'].employee_id.id,
                             date_start, date_end))
        res = self.env.cr.fetchone()
        if res and res[0]:
            return ((res[0]+values_base_compensation) / dias_trabajados) * DAYS_YEAR
        else:
            return 0.0
        
    def _indem(self, data_payslip):
        """
        Calcula la indemnización por terminación de contrato sin justa causa.
        Incluye cálculo proporcional para fracciones de año.
        
        Args:
            data_payslip (dict): Diccionario con datos de liquidación
            
        Returns:
            tuple: (valor_diario, días, porcentaje, nombre, log_html, datos_para_visualización)
        """

        
        def to_decimal(value):
            """Convierte un valor a Decimal de manera segura."""
            if isinstance(value, Decimal):
                return value
            elif value is None:
                return Decimal("0")
            return Decimal(str(value))
        
        def decimal_round(value, precision=2):
            """Redondea un valor Decimal al número de decimales especificado."""
            value = to_decimal(value)
            decimal_precision = Decimal(f'0.{"0" * precision}1')
            return value.quantize(decimal_precision, rounding=ROUND_HALF_UP)
        
        def fmt_money(val):
            """Formatea un valor monetario."""
            from odoo.tools import format_amount
            if isinstance(val, Decimal):
                val_float = float(val)
            elif val is None:
                val_float = 0.0
            else:
                try:
                    val_float = float(val)
                except (ValueError, TypeError):
                    val_float = 0.0
            return format_amount(self.env, val_float, self.env.company.currency_id)
        

        
        def generar_html_indemnizacion(tipo_contrato, date_start, settlement_date, duration_days, 
                                    years_worked, salario_basico, salario_variable, salario_total,
                                    explicaciones, pasos, dias_indemnizacion, valor_diario, valor_total):
            """Genera directamente el HTML para la visualización."""
            tipos_contrato = {
                'fijo': _('Término Fijo'),
                'indefinido': _('Término Indefinido'),
                'obra': _('Obra o Labor')
            }
            tipo_contrato_mostrar = tipos_contrato.get(tipo_contrato, tipo_contrato.capitalize())
            
            html = [
                '<div class="p-3 border rounded bg-light">',
                f'<h5 class="text-primary">{_("Cálculo de Indemnización")} - {tipo_contrato_mostrar}</h5>'
            ]
            
            html.append(
                f'<div class="mb-3">'
                f'<small><strong>{_("Periodo")}:</strong> {date_start.strftime("%d/%m/%Y")} – {settlement_date.strftime("%d/%m/%Y")}</small><br/>'
                f'<small><strong>{_("Días trabajados")}:</strong> {duration_days} ({years_worked:.2f} años)</small>'
                f'</div><hr/>'
            )
            
            html.append('<div class="mb-3 p-2 bg-white rounded shadow-sm border-start border-primary border-4">')
            html.append(f'<h6 class="mb-2">{_("Componentes del Salario")}:</h6>')
            
            html.append(
                f'<div><strong>{_("Salario básico")}:</strong> '
                f'<span class="text-primary">{fmt_money(salario_basico)}</span></div>'
            )
            
            html.append(
                f'<div><strong>{_("Promedio variable")}:</strong> '
                f'<span class="text-primary">{fmt_money(salario_variable)}</span></div>'
            )
            
            html.append(
                f'<div><strong>{_("Salario total")}:</strong> '
                f'<span class="text-primary font-weight-bold">{fmt_money(salario_total)}</span></div>'
            )
            
            html.append('</div>')
            
            if explicaciones and len(explicaciones) > 0:
                html.append('<div class="mt-3 mb-3 p-2 bg-white rounded shadow-sm">')
                html.append(f'<h6 class="mb-2">{_("Criterios del Cálculo")}:</h6>')
                
                html.append('<ul class="mb-0">')
                for explicacion in explicaciones:
                    html.append(f'<li>{explicacion}</li>')
                html.append('</ul>')
                
                html.append('</div>')
            
            if pasos and len(pasos) > 0:
                html.append('<div class="mt-3 mb-3">')
                html.append(f'<h6 class="mb-2">{_("Detalle del Cálculo")}:</h6>')
                
                html.append('<div class="table-responsive">')
                html.append('<table class="table table-sm table-bordered">')
                html.append(f'<thead class="table-light"><tr><th>{_("Concepto")}</th><th>{_("Detalle")}</th><th class="text-end">{_("Valor")}</th></tr></thead>')
                html.append('<tbody>')
                
                for paso in pasos:
                    detalle = paso.get('detalle', '')
                    calculo = paso.get('calculo', '')
                    valor = paso.get('valor', 0)
                    
                    html.append('<tr>')
                    html.append(f'<td><strong>{detalle}</strong></td>')
                    html.append(f'<td>{calculo}</td>')
                    html.append(f'<td class="text-end">{fmt_money(valor) if "diario" not in detalle.lower() else valor}</td>')
                    html.append('</tr>')
                
                html.append('</tbody></table>')
                html.append('</div>')
                html.append('</div>')
            
            html.append('<div class="mt-3 p-3 bg-light rounded shadow-sm border border-success">')
            html.append(f'<h6 class="mb-2 text-success">{_("Resultado Final")}:</h6>')
            
            html.append(
                f'<div><strong>{_("Días de indemnización")}:</strong> '
                f'<span class="text-success fw-bold">{dias_indemnizacion:.2f}</span></div>'
            )
            
            html.append(
                f'<div><strong>{_("Valor diario")}:</strong> '
                f'<span class="text-success fw-bold">{fmt_money(valor_diario)}</span></div>'
            )
            
            html.append(
                f'<div><strong>{_("Valor total indemnización")}:</strong> '
                f'<span class="text-success fw-bold">{fmt_money(valor_total)}</span></div>'
            )
            
            html.append('</div>')
            
            html.append('</div>')
            
            return ''.join(html)
        
        annual_params = data_payslip['annual_parameters']
        slip = data_payslip.get('slip')
        contract = data_payslip.get('contract')
        
        if not slip or not contract or not slip.reason_retiro or not slip.have_compensation:
            return 0, 0, 0, 0, "", {}
        
        settlement_date = slip.date_liquidacion
        if not settlement_date:
            return 0, 0, 0, 0, "", {}
        
        date_start = contract.date_start
        if not date_start:
            return 0, 0, 0, 0, "", {}
        
        
        salario_variable = to_decimal(0)
        if contract.modality_salary == 'variable':
            salario_variable = to_decimal(self.get_last_year(data_payslip, settlement_date))

        
        salario_basico = to_decimal(contract.wage)
        salario_total = salario_basico + salario_variable
        
        duration_days = days360(date_start, settlement_date)
        years_worked = to_decimal(duration_days) / to_decimal(DAYS_YEAR)
        
        smmlv = to_decimal(annual_params.smmlv_monthly)
        
        pasos = []
        explicaciones = []
        
        dias_indemnizacion = to_decimal(0)
        
        if contract.contract_type in ['fijo', 'obra']:
            date_end = contract.date_end
            if not date_end:
                return 0, 0, 0, 0, "", {}
            
            if settlement_date > date_end:
                return 0, 0, 0, 0, "", {}
            
            days_not_pay = days360(settlement_date, date_end) - 1
            
            explicaciones.append(
                f"Contrato a término {contract.contract_type}. "
                f"Se calcula indemnización por los días faltantes para terminar el contrato."
            )
            
            if days_not_pay <= 0:
                return 0, 0, 0, 0, "", {}
            
            dias_indemnizacion = to_decimal(days_not_pay)
            
            if contract.contract_type == 'obra' and dias_indemnizacion < 15:
                pasos.append({
                    'detalle': 'Ajuste mínimo para contrato por obra',
                    'calculo': f"Días faltantes: {float(dias_indemnizacion)}. "
                            f"Como es menor a 15 días, se ajusta al mínimo legal.",
                    'valor': 15.0
                })
                dias_indemnizacion = to_decimal(15)
            else:
                pasos.append({
                    'detalle': 'Días faltantes para terminar el contrato',
                    'calculo': f"Desde {settlement_date.strftime('%d/%m/%Y')} "
                            f"hasta {date_end.strftime('%d/%m/%Y')}",
                    'valor': float(dias_indemnizacion)
                })
        
        else:
            explicaciones.append(
                f"Contrato a término indefinido. "
                f"El salario total es {fmt_money(salario_total)} y el límite de 10 SMMLV es {fmt_money(smmlv * 10)}."
            )
            
            if salario_total < smmlv * 10:
                explicaciones.append(
                    f"El salario es menor a 10 SMMLV. "
                    f"Se aplica: 30 días por el primer año + 20 días por cada año adicional hasta el 5to año "
                    f"+ 13.33 días por cada año después del 5to."
                )
                
                if years_worked <= 1:
                    dias_primer_anio = to_decimal(DAYS_MONTH) * years_worked
                    pasos.append({
                        'detalle': 'Primer año o fracción',
                        'calculo': f"30 días × {float(years_worked):.2f} años = {float(dias_primer_anio):.2f} días",
                        'valor': float(dias_primer_anio)
                    })
                    dias_indemnizacion = dias_primer_anio
                else:
                    pasos.append({
                        'detalle': 'Primer año completo',
                        'calculo': f"30 días por el primer año completo",
                        'valor': DAYS_MONTH
                    })
                    dias_indemnizacion = to_decimal(DAYS_MONTH)
                    
                    if years_worked <= 6:
                        anios_adicionales = years_worked - 1
                        dias_anios_2_a_5 = anios_adicionales * to_decimal(20)
                        
                        pasos.append({
                            'detalle': 'Años 2 al 5 o fracción',
                            'calculo': f"{float(anios_adicionales):.2f} años × 20 días = {float(dias_anios_2_a_5):.2f} días",
                            'valor': float(dias_anios_2_a_5)
                        })
                        dias_indemnizacion += dias_anios_2_a_5
                    else:
                        dias_anios_2_a_5 = to_decimal(5) * to_decimal(20)
                        pasos.append({
                            'detalle': 'Años 2 al 5 completos',
                            'calculo': f"5 años × 20 días = {float(dias_anios_2_a_5)} días",
                            'valor': float(dias_anios_2_a_5)
                        })
                        dias_indemnizacion += dias_anios_2_a_5
                        
                        anios_despues_6 = years_worked - 6
                        dias_anios_6_adelante = anios_despues_6 * to_decimal('13.33')
                        
                        pasos.append({
                            'detalle': 'Años posteriores al 5to',
                            'calculo': f"{float(anios_despues_6):.2f} años × 13.33 días = {float(dias_anios_6_adelante):.2f} días",
                            'valor': float(dias_anios_6_adelante)
                        })
                        dias_indemnizacion += dias_anios_6_adelante
            else:
                explicaciones.append(
                    f"El salario es igual o mayor a 10 SMMLV. "
                    f"Se aplica: 20 días por el primer año + 15 días por cada año adicional."
                )
                
                if years_worked <= 1:
                    dias_primer_anio = to_decimal(20) * years_worked
                    pasos.append({
                        'detalle': 'Primer año o fracción',
                        'calculo': f"20 días × {float(years_worked):.2f} años = {float(dias_primer_anio):.2f} días",
                        'valor': float(dias_primer_anio)
                    })
                    dias_indemnizacion = dias_primer_anio
                else:
                    pasos.append({
                        'detalle': 'Primer año completo',
                        'calculo': f"20 días por el primer año completo",
                        'valor': 20.0
                    })
                    dias_indemnizacion = to_decimal(20)
                    
                    anios_adicionales = years_worked - 1
                    dias_anios_adicionales = anios_adicionales * to_decimal(15)
                    
                    pasos.append({
                        'detalle': 'Años adicionales o fracción',
                        'calculo': f"{float(anios_adicionales):.2f} años × 15 días = {float(dias_anios_adicionales):.2f} días",
                        'valor': float(dias_anios_adicionales)
                    })
                    dias_indemnizacion += dias_anios_adicionales
        
        valor_diario = salario_total / DAYS_MONTH
        valor_total = valor_diario * dias_indemnizacion
        
        dias_indemnizacion = decimal_round(dias_indemnizacion, 2)
        valor_diario = decimal_round(valor_diario, 2)
        valor_total = decimal_round(valor_total, 2)
        
        pasos.append({
            'detalle': 'Cálculo del valor diario',
            'calculo': f"Salario total {fmt_money(salario_total)} ÷ 30 días = {fmt_money(valor_diario)}",
            'valor': float(valor_diario)
        })
        
        pasos.append({
            'detalle': 'Cálculo del valor total',
            'calculo': f"Valor diario {fmt_money(valor_diario)} × {float(dias_indemnizacion)} días = {fmt_money(valor_total)}",
            'valor': float(valor_total)
        })
        
        html_log = generar_html_indemnizacion(
            contract.contract_type,
            date_start, 
            settlement_date, 
            duration_days, 
            float(years_worked),
            float(salario_basico),
            float(salario_variable),
            float(salario_total),
            explicaciones,
            pasos,
            float(dias_indemnizacion),
            float(valor_diario),
            float(valor_total)
        )
        
        contract_type = contract.contract_type
        contract_name = dict(contract._fields['contract_type'].selection).get(contract_type, "")
        
        nombre = f"INDEMNIZACIÓN CONTRATO {contract_name.upper()}"
        
        visual_data = {
            'employee': {
                'name': contract.employee_id.name,
                'id': contract.employee_id.identification_id,
            },
            'contract': {
                'type': contract_name,
                'start_date': contract.date_start.strftime('%Y-%m-%d'),
                'end_date': contract.date_end.strftime('%Y-%m-%d') if contract.date_end else 'N/A',
                'salary': float(salario_total),
                'avg': float(salario_variable),
            },
            'calculation': {
                'years_worked': float(years_worked),
                'days_first_year': float(dias_indemnizacion),
                'total_indem': float(valor_total),
                'steps': pasos,
                'explanation': explicaciones,
            },
            'params': {
                'smmlv': float(smmlv),
            }
        }
        
        return float(valor_diario), float(dias_indemnizacion), 100, nombre, html_log, visual_data
    
    def _rtf_indem(self, payslip_data):
        """
        Calcula la retención en la fuente para indemnizaciones laborales.
        Según art. 401-3 del E.T.:
        - Aplica 20% solo si los ingresos mensuales del trabajador superan 204 UVT
        - Los ingresos incluyen todo pago que remunere la actividad laboral
        - La retención es independiente de la retención por salarios
        - Se aplica una exención del 25% sin límite mensual
        """
        service  = self.env['lavish.retencion.service']
        monto,qty,porc,nombr,log,data = service._rtf_indem(payslip_data)
        return monto, qty, porc, nombr, log , data

    
    def _rt_met_01(self, payslip_data):
        """
        Calcula la retención en la fuente según el procedimiento 1
        Args:
            payslip_data: Dict con datos de nómina
        Returns:
            tuple: (base, -1, rate, name, log, False)
        """
        # Validación inicial
        if payslip_data['contract'].contract_type == 'aprendizaje':
            return 0, -1, 0, '', [], False
            
        aplicar = self.aplicar_cobro
        modality = self.modality_value
        day = payslip_data['payslip'].date_from.day
        
        if (aplicar != "0" and  
            ((aplicar == "15" and day > 15) or 
            (aplicar == "30" and day < 16))): 
            return 0, -1, 0, '', [], False


        service  = self.env['lavish.retencion.service']
        monto,qty,porc,nombr,log,data = service._rt_met_01(payslip_data)
       
        
        return monto, qty, porc, nombr, log , data


    def get_overtime(self, employee_id, from_date, to_date, inherit_contrato = 0, aplicar = 0):
        if inherit_contrato == 0 and aplicar != 0:
            from_month = from_date.month
            from_year = from_date.year
            date = str(from_year)+'-'+str(from_month)+'-01'
        else:
            date = from_date
        if employee_id.contract_id.not_pay_overtime:
            res = self.env['hr.overtime']
        else:
            res = self.env['hr.overtime'].search([('employee_id', '=', employee_id.id),('date','>=',date),('date_end','<=',to_date)])
        return res

    def get_salary_rule(self, salary_rule_code, type_employee_id):
        res = self.env['hr.salary.rule'].search([('code', '=', salary_rule_code)])
        return res
    def get_type_overtime(self, salary_rule_id):
        res = self.env['hr.type.overtime'].search([('salary_rule', '=', salary_rule_id)])
        return res

    def _get_hours_config_for_date(self, company_id, date_reference):
        """
        Busca la configuración de horas aplicable para una fecha específica
        """
        all_configs = self.env['hr.company.working.hours'].search([
            ('company_id', '=', company_id),
            ('effective_date', '<=', date_reference)
        ], order='effective_date desc')
        
        if all_configs:
            for config in all_configs:
                if config.effective_date <= date_reference:
                    next_config = self.env['hr.company.working.hours'].search([
                        ('company_id', '=', company_id),
                        ('effective_date', '>', config.effective_date)
                    ], order='effective_date asc', limit=1)
                    
                    if not next_config or date_reference < next_config.effective_date:
                        return config.hours_to_pay or config.hours_per_month
        
        year, month, day = date_reference.year, date_reference.month, date_reference.day
        
        if year < 2024:
            return 240
        elif year == 2024:
            return 240 if month < 7 or (month == 7 and day < 15) else 230
        elif year == 2025:
            return 230 if month < 7 or (month == 7 and day < 15) else 220
        elif year == 2026:
            return 220 if month < 7 or (month == 7 and day < 15) else 210
        else:
            return 210
    
    def _compute_overtime_with_log(self, localdict, rule_code):
        """
        Calcula horas extras con log detallado
        """
        contract = localdict.get('contract')
        employee = localdict.get('employee')
        payslip = localdict.get('payslip')
        inherit_contrato = localdict.get('inherit_contrato', 0)
        

        OVERTIME_CONFIG = {
            'HEYREC001': {'percentage': 125.0, 'multiplier': 1.25, 'name': 'Horas extra diurnas', 'field': 'overtime_ext_d'},
            'HEYREC002': {'percentage': 200.0, 'multiplier': 2.0,  'name': 'Horas extra diurnas dominical/festiva', 'field': 'overtime_eddf'},
            'HEYREC003': {'percentage': 175.0, 'multiplier': 1.75, 'name': 'Horas extra nocturna', 'field': 'overtime_ext_n'},
            'HEYREC004': {'percentage': 110.0, 'multiplier': 1.1,  'name': 'Horas recargo festivo', 'field': 'overtime_rndf'},
            'HEYREC005': {'percentage': 35.0,  'multiplier': 0.35, 'name': 'Horas Recargo Nocturno', 'field': 'overtime_rn'},
            'HEYREC006': {'percentage': 250.0, 'multiplier': 2.5,  'name': 'Horas extra nocturna dominical/festiva', 'field': 'overtime_endf'},
            'HEYREC007': {'percentage': 175.0, 'multiplier': 1.75, 'name': 'Horas Dominicales', 'field': 'overtime_dof'},
            'HEYREC008': {'percentage': 75.0,  'multiplier': 0.75, 'name': 'Recargos dominicales', 'field': 'overtime_rdf'}
        }
        
        config = OVERTIME_CONFIG.get(rule_code, {})
        percentage = config.get('percentage', 100.0)
        multiplier = config.get('multiplier', 1.0)
        rule_name = config.get('name', rule_code)
        
        salary_rule = payslip.get_salary_rule(rule_code, employee.type_employee.id)
        if not salary_rule:
            return 0.0, 0.0, percentage, False, '', False
        
        aplicar = int(salary_rule.aplicar_cobro)
        day_from = payslip.date_from.day
        day_to = 30 if payslip.date_to.month == 2 and payslip.date_to.day in (28, 29) else payslip.date_to.day
        
        if not ((aplicar == 0) or (aplicar >= day_from and aplicar <= day_to)):
            return 0.0, 0.0, percentage, False, '', False
        
        type_overtime = payslip.get_type_overtime(salary_rule.id)
        if not type_overtime:
            return 0.0, 0.0, percentage, False, '', False
        
        overtime_records = self.get_overtime(employee, payslip.date_from, payslip.date_to, inherit_contrato, aplicar)
        if not overtime_records:
            return 0.0, 0.0, percentage, False, '', False
        
        log_lines = []
        log_lines.append(f"<b>{rule_name} ({percentage}%)</b>")
        log_lines.append(f"Salario base: ${contract.wage:,.0f}")
        log_lines.append("=" * 50)
        result_tota_rate = 0.0
        result_total = 0.0
        hours_total = 0.0
        overtime_field = type_overtime.type_overtime
        
        for i, record in enumerate(overtime_records, 1):
            hours = getattr(record, overtime_field, 0)
            if hours <= 0:
                continue
                
            base_hours = self._get_hours_config_for_date(contract.company_id.id, record.date)
            
            if contract.subcontract_type in ('obra_parcial', 'obra_integral'):
                base_hours = base_hours / 2
                
            if contract.schedule_pay == 'partial':
                base_hours = base_hours * (contract.part_time_percentage / 100)
            
            hourly_rate = contract.wage / base_hours
            rate_per_hour = float(Decimal(hourly_rate * multiplier)).__round__(2)
            line_total = hourly_rate * hours
            
            log_lines.append(f"Línea {i} - Fecha: {record.date.strftime('%d/%m/%Y')}")
            log_lines.append(f"  Horas base config: {base_hours}")
            log_lines.append(f"  Horas registradas: {hours}")
            log_lines.append(f"  Tarifa por hora: ${contract.wage:,.0f} / {base_hours} = ${hourly_rate:,.0f}")
            log_lines.append(f"  Tarifa con recargo: ${hourly_rate:,.0f} × {multiplier} = ${rate_per_hour:,.0f}")
            log_lines.append(f"  Subtotal: ${rate_per_hour:,.0f} × {hours} = ${rate_per_hour *hours:,.0f}")
            log_lines.append("-" * 30)
            result_tota_rate += rate_per_hour *hours
            result_total += line_total
            hours_total += hours
        
        if hours_total <= 0:
            return 0.0, 0.0, percentage, False, '', False
        
        avg_rate = result_tota_rate / hours_total
        avg_nom_rate = result_total / hours_total     
        log_lines.append("=" * 50)
        log_lines.append("RESUMEN TOTAL:")
        log_lines.append(f"Total horas: {hours_total}")
        log_lines.append(f"Total valor: ${result_tota_rate:,.0f}")
        log_lines.append(f"Tarifa promedio: ${result_tota_rate:,.0f} / {hours_total} = ${avg_rate:,.0f}")
        
        name = f"{rule_name} ({percentage}%) - {hours_total}h a ${avg_rate:,.0f}"
        
        html_log = "<div style='font-family: monospace; font-size: 12px;'>" + "<br>".join(log_lines) + "</div>"
        
        return avg_nom_rate, hours_total, percentage, name, html_log, False
    
    def _heyrec001(self, localdict):
        return self._compute_overtime_with_log(localdict, 'HEYREC001')
    
    def _heyrec002(self, localdict):
        return self._compute_overtime_with_log(localdict, 'HEYREC002')
    
    def _heyrec003(self, localdict):
        return self._compute_overtime_with_log(localdict, 'HEYREC003')
    
    def _heyrec004(self, localdict):
        return self._compute_overtime_with_log(localdict, 'HEYREC004')
    
    def _heyrec005(self, localdict):
        return self._compute_overtime_with_log(localdict, 'HEYREC005')
    
    def _heyrec006(self, localdict):
        return self._compute_overtime_with_log(localdict, 'HEYREC006')
    
    def _heyrec007(self, localdict):
        return self._compute_overtime_with_log(localdict, 'HEYREC007')
    
    def _heyrec008(self, localdict):
        return self._compute_overtime_with_log(localdict, 'HEYREC008')

class hr_types_faults(models.Model):
    _name = 'hr.types.faults'
    _description = 'Tipos de faltas'

    name = fields.Char('Nombre', required=True)
    description = fields.Text('Descripción')

class Hr_payslip_line(models.Model):
    _inherit = 'hr.payslip.line'
    amount_old  = fields.Float(digits='Payroll')
    quantity_old = fields.Float(digits='Payroll', default=1.0)
    total_technical = fields.Float(digits='Payroll')
    total_old = fields.Float(digits='Payroll')
    total = fields.Float(compute=False)
    amount = fields.Float(digits='Payroll')
    quantity = fields.Float(digits='Payroll', default=1.0)
    amount_technical = fields.Float('Monto Técnico', digits=(16, 10))
    quantity_technical = fields.Float('Cantidad Técnica', digits=(16, 10))
    rate_technical = fields.Float('Tasa Técnica', digits=(16, 10))
    amount_display = fields.Float('Monto INT', digits=(16, 0))
    total_display = fields.Float('Total INT', digits=(16, 0))
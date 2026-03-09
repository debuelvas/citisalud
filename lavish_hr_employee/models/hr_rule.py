from odoo import models, fields, api, _
from datetime import datetime, timedelta, date
from dateutil.relativedelta import relativedelta
import calendar
from collections import defaultdict
import re
from odoo.exceptions import UserError, ValidationError
from odoo.tools.safe_eval import safe_eval
from odoo.tools import format_date, formatLang, frozendict, date_utils, format_amount
from decimal import Decimal, getcontext, ROUND_HALF_UP
import logging

_logger = logging.getLogger(__name__)

# Constantes
DAYS_YEAR = 360
DAYS_YEAR_NATURAL = 365
DAYS_MONTH = 30
PRECISION_DISPLAY = 0
PRECISION_TECHNICAL = 10
HOURS_PER_DAY = 8

getcontext().prec = 10

# Tabla de retención
tabla_retencion = [
    (0, 95, 0, 0, 0),
    (95, 150, 19, 95, 0),
    (150, 360, 28, 150, 10),
    (360, 640, 33, 360, 69),
    (640, 945, 35, 640, 162),
    (945, 2300, 37, 945, 268),
    (2300, float('inf'), 39, 2300, 770)
]

def days360(start_date, end_date, method_eu=True):
    """Compute number of days between two dates regarding all months as 30-day months"""
    start_day = start_date.day
    start_month = start_date.month
    start_year = start_date.year
    end_day = end_date.day
    end_month = end_date.month
    end_year = end_date.year

    if (start_day == 31 or (method_eu is False and start_month == 2 and 
        (start_day == 29 or (start_day == 28 and calendar.isleap(start_year) is False)))):
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

    return (end_day + end_month * 30 + end_year * 360 -
            start_day - start_month * 30 - start_year * 360 + 1)

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
   
class PayrollCalculationEngine:
    """Motor de cálculo unificado para reglas de nómina"""
    
    def __init__(self, env):
        self.env = env
        
    def to_decimal(self, value):
        """Convierte valor a Decimal de manera segura"""
        if isinstance(value, Decimal):
            return value
        elif value is None:
            return Decimal("0")
        return Decimal(str(value))
    
    def decimal_round(self, value, precision=PRECISION_DISPLAY):
        """Redondea un valor Decimal"""
        value = self.to_decimal(value)
        decimal_precision = Decimal(f'0.{"0" * precision}1')
        return value.quantize(decimal_precision, rounding=ROUND_HALF_UP)
    
    def format_currency(self, value):
        """Formatea valor monetario"""
        return format_amount(self.env, float(value), self.env.company.currency_id)
    
    def validate_conditions(self, localdict, conditions):
        """Valida condiciones para aplicación de reglas"""
        contract = localdict.get('contract')
        employee = localdict.get('employee')
        
        for condition in conditions:
            condition_type = condition.get('type')
            expected = condition.get('expected')
            negate = condition.get('negate', False)
            
            if condition_type == 'modality_salary':
                if isinstance(expected, list):
                    passed = contract.modality_salary in expected
                else:
                    passed = contract.modality_salary == expected
            elif condition_type == 'tipo_coti_code':
                coti_code = employee.tipo_coti_id.code if employee.tipo_coti_id else None
                if isinstance(expected, list):
                    passed = coti_code in expected
                else:
                    passed = coti_code == expected
            elif condition_type == 'contract_type':
                passed = contract.contract_type == expected
            elif condition_type == 'field_check':
                field_name = condition.get('field')
                if hasattr(contract, field_name):
                    field_value = getattr(contract, field_name)
                    passed = bool(field_value)
                else:
                    passed = False
            else:
                passed = True
            
            if negate:
                passed = not passed
                
            if not passed:
                return False, condition.get('message', f'Condición {condition_type} falló')
        
        return True, 'Todas las condiciones se cumplieron'

    def get_worked_days_info(self, localdict):
        """Obtiene información de días trabajados"""
        worked_days = localdict.get('worked_days', {})
        anual_parameters = localdict.get('anual_parameters', {})
        if worked_days.WORK100:
            work_entry = worked_days.WORK100
            return {
                'days': self.to_decimal(work_entry.number_of_days),
                'hours': self.to_decimal(work_entry.number_of_hours),
                'has_work_entry': True
            }
        
        slip = localdict.get('slip')
        if slip:
            total_days = (slip.date_to - slip.date_from).days + 1
            return {
                'days': self.to_decimal(total_days),
                'hours': self.to_decimal(total_days * anual_parameters.hours_per_day),
                'has_work_entry': False
            }
        
        return {'days': Decimal("0"), 'hours': Decimal("0"), 'has_work_entry': False}

    def get_categories_total(self, localdict, categories):
        """Obtiene total de categorías desde localdict"""
        total = Decimal("0")
        categories_data = localdict.get('categories', {})
        
        if isinstance(categories, str):
            categories = [categories]
        
        for category in categories:
            total += self.to_decimal(getattr(categories_data, category, 0))
        
        return total

    def get_rules_total(self, localdict, rules_codes):
        """Obtiene total de reglas específicas desde localdict"""
        total = Decimal("0")
        
        if isinstance(rules_codes, str):
            rules_codes = [rules_codes]
        
        rules_multi = localdict.get('rules_multi', {})
        for rule_code in rules_codes:
            if rule_code in rules_multi:
                rule_data = rules_multi[rule_code]
                total += self.to_decimal(rule_data.get('current', {}).get('total', 0))
        
        return total

class PayrollHTMLGenerator:
    """Generador de HTML mejorado para logs de nómina"""
    
    def __init__(self, rule_name, rule_code, env=None):
        self.rule_name = rule_name
        self.rule_code = rule_code
        self.env = env
        self.validations = []
        self.kpis = []
        self.calculations = []
        self.errors = []
        self.period_info = {}
        self.salary_variations = []
        self.final_result = {}
        self.details = []
        self.ranges_log = []
    
    def add_validation(self, passed, message, type_='info'):
        """Añade validación al log"""
        self.validations.append({
            'passed': passed,
            'message': message,
            'type': type_
        })
    
    def add_kpi(self, label, value, icon='info', color='primary', format_currency=False):
        """Añade KPI al dashboard"""
        if format_currency and isinstance(value, (int, float, Decimal)):
            formatted_value = self._format_currency(value)
        else:
            formatted_value = str(value)
        
        self.kpis.append({
            'label': label,
            'value': formatted_value,
            'icon': icon,
            'color': color
        })
    
    def add_calculation(self, description, formula="", result=""):
        """Añade paso de cálculo"""
        self.calculations.append({
            'description': description,
            'formula': formula,
            'result': result
        })
    
    def add_detail(self, label, value, highlight=False):
        """Añade detalle adicional"""
        self.details.append({
            'label': label,
            'value': value,
            'highlight': highlight
        })

    def add_range_log(self, ranges):
        """Añade log de rangos evaluados"""
        self.ranges_log = ranges
    
    def add_period(self, date_from, date_to, additional_info=None):
        """Añade información del período"""
        self.period_info = {
            'date_from': date_from,
            'date_to': date_to,
            'days': days360(date_from, date_to),
            'additional_info': additional_info or {}
        }
    
    def add_salary_variation(self, date_change, old_salary, new_salary):
        """Añade variación salarial"""
        self.salary_variations.append({
            'date': date_change,
            'old_salary': float(old_salary),
            'new_salary': float(new_salary),
            'variation': float(new_salary - old_salary)
        })
    
    def set_final_result(self, amount, quantity=1, rate=100):
        """Establece resultado final"""
        self.final_result = {
            'amount': float(amount) if amount else 0,
            'quantity': float(quantity) if quantity else 0,
            'rate': float(rate) if rate else 0
        }

    def add_error(self, message, details=""):
        """Añade error al log"""
        self.errors.append({
            'message': message,
            'details': details
        })
    
    def _format_currency(self, value):
        """Formatea valor monetario"""
        if self.env:
            return format_amount(self.env, float(value), self.env.company.currency_id)
        return f"${float(value):,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    
    def generate_html(self):
        """Genera HTML completo del log"""
        status = self._get_status()
        
        html = f'''
        <div class="payroll-log-container">
            <style>
                .payroll-log-container {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                    max-width: 100%;
                    background: #ffffff;
                    border-radius: 12px;
                    box-shadow: 0 4px 20px rgba(0,0,0,0.1);
                    border: 1px solid #e1e5e9;
                    overflow: hidden;
                }}
                .header {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    padding: 1.5rem;
                }}
                .body {{
                    padding: 1.5rem;
                }}
                .status-banner {{
                    border-radius: 8px;
                    padding: 1rem;
                    margin-bottom: 1.5rem;
                    border-left: 4px solid;
                }}
                .status-success {{ background: #f0f9ff; border-color: #10b981; color: #047857; }}
                .status-warning {{ background: #fffbeb; border-color: #f59e0b; color: #b45309; }}
                .status-danger {{ background: #fef2f2; border-color: #ef4444; color: #b91c1c; }}
                .kpi-grid {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                    gap: 1rem;
                    margin: 1.5rem 0;
                }}
                .kpi-card {{
                    background: #f8fafc;
                    border: 1px solid #e2e8f0;
                    border-radius: 10px;
                    padding: 1.25rem;
                    text-align: center;
                    transition: transform 0.2s ease;
                }}
                .kpi-card:hover {{
                    transform: translateY(-2px);
                    box-shadow: 0 4px 12px rgba(0,0,0,0.1);
                }}
                .calculations {{
                    background: #f3f4f6;
                    border-radius: 8px;
                    padding: 1.5rem;
                    margin: 1.5rem 0;
                }}
                .calculation-step {{
                    margin-bottom: 1rem;
                    padding: 0.75rem;
                    background: white;
                    border-radius: 6px;
                }}
                .final-result {{
                    background: linear-gradient(135deg, #10b981 0%, #059669 100%);
                    color: white;
                    padding: 2rem;
                    border-radius: 12px;
                    text-align: center;
                    margin: 1.5rem 0;
                }}
                .validation-list {{
                    list-style: none;
                    padding: 0;
                    margin: 1rem 0;
                }}
                .validation-item {{
                    padding: 0.5rem 0;
                    display: flex;
                    align-items: center;
                }}
                .validation-icon {{
                    width: 20px;
                    height: 20px;
                    margin-right: 0.75rem;
                    border-radius: 50%;
                    display: inline-block;
                }}
                .validation-passed {{ background: #10b981; }}
                .validation-failed {{ background: #ef4444; }}
                .details-table {{
                    width: 100%;
                    border-collapse: collapse;
                    margin: 1rem 0;
                }}
                .details-table th, .details-table td {{
                    padding: 0.75rem;
                    text-align: left;
                    border-bottom: 1px solid #e5e7eb;
                }}
                .details-table th {{
                    background-color: #f9fafb;
                    font-weight: 600;
                }}
                .highlight-row {{
                    background-color: #eff6ff;
                    font-weight: 600;
                }}
                .ranges-grid {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                    gap: 0.5rem;
                    margin: 1rem 0;
                }}
                .range-item {{
                    padding: 0.5rem;
                    border-radius: 6px;
                    border: 1px solid #e5e7eb;
                }}
                .range-active {{ background-color: #dcfce7; border-color: #22c55e; }}
                .range-inactive {{ background-color: #fef2f2; border-color: #ef4444; }}
            </style>
            
            <div class="header">
                <h3 style="margin: 0; font-size: 1.5rem; font-weight: 700;">{self.rule_name}</h3>
                <p style="margin: 0.5rem 0 0 0; opacity: 0.9;">Código: {self.rule_code}</p>
            </div>
            
            <div class="body">
                <div class="status-banner status-{status['class']}">
                    <span style="font-weight: 600;">{status['message']}</span>
                </div>
        '''
        
        # Información del período
        if self.period_info:
            html += self._render_period_info()
        
        # Validaciones
        if self.validations:
            html += self._render_validations()
        
        # Variaciones salariales
        if self.salary_variations:
            html += self._render_salary_variations()
        
        # Rangos evaluados
        if self.ranges_log:
            html += self._render_ranges()
        
        # KPIs
        if self.kpis:
            html += self._render_kpis()

        # Detalles adicionales
        if self.details:
            html += self._render_details()
        
        # Cálculos
        if self.calculations:
            html += self._render_calculations()
        
        # Resultado final
        if self.final_result and self.final_result.get('amount', 0) != 0:
            html += self._render_final_result()
        
        # Errores
        if self.errors:
            html += self._render_errors()
        
        html += "</div></div>"
        return html
    
    def _get_status(self):
        """Obtiene configuración de estado"""
        if self.errors:
            return {'class': 'danger', 'message': 'Error en el cálculo'}
        
        failed_validations = [v for v in self.validations if not v['passed']]
        if failed_validations:
            return {'class': 'warning', 'message': 'Validaciones fallidas'}
            
        return {'class': 'success', 'message': 'Cálculo exitoso'}
    
    def _render_period_info(self):
        """Renderiza información del período"""
        period = self.period_info
        html = f'''
            <div style="background: #eff6ff; border: 1px solid #3b82f6; border-radius: 8px; padding: 1rem; margin: 1rem 0;">
                <h4 style="margin: 0 0 0.5rem 0;">Período de Cálculo</h4>
                <div style="display: flex; justify-content: space-between; flex-wrap: wrap;">
                    <span>Desde: {period['date_from'].strftime('%d/%m/%Y')}</span>
                    <span>Hasta: {period['date_to'].strftime('%d/%m/%Y')}</span>
                    <span>Días: {period['days']}</span>
        '''
        
        for key, value in period.get('additional_info', {}).items():
            html += f'<span>{key}: {value}</span>'
        
        html += '</div></div>'
        return html
    
    def _render_validations(self):
        """Renderiza validaciones"""
        html = '<div class="validation-list">'
        for validation in self.validations:
            icon_class = 'validation-passed' if validation['passed'] else 'validation-failed'
            html += f'''
                <div class="validation-item">
                    <span class="validation-icon {icon_class}"></span>
                    <span>{validation['message']}</span>
                </div>
            '''
        html += '</div>'
        return html
    
    def _render_salary_variations(self):
        """Renderiza variaciones salariales"""
        html = '''
            <div style="background: #fef3c7; border-radius: 8px; padding: 1rem; margin: 1rem 0;">
                <h4 style="margin: 0 0 0.75rem 0;">Variaciones Salariales Detectadas</h4>
                <p style="margin: 0 0 0.5rem 0; font-size: 0.875rem;">
                    Se aplicará promedio según Art. 253 CST
                </p>
        '''
        
        for var in self.salary_variations:
            html += f'''
                <div style="margin: 0.25rem 0; font-size: 0.875rem;">
                    • {var['date'].strftime('%d/%m/%Y')}: 
                    {self._format_currency(var['old_salary'])} → 
                    {self._format_currency(var['new_salary'])}
                    (Δ {self._format_currency(var['variation'])})
                </div>
            '''
        
        html += '</div>'
        return html

    def _render_ranges(self):
        """Renderiza rangos evaluados"""
        html = '''
            <div style="margin: 1rem 0;">
                <h4 style="margin: 0 0 0.75rem 0;">Rangos Evaluados</h4>
                <div class="ranges-grid">
        '''
        
        for range_item in self.ranges_log:
            label = range_item.get('label', '')
            active = range_item.get('active', False)
            css_class = 'range-active' if active else 'range-inactive'
            icon = '✓' if active else '✗'
            
            html += f'''
                <div class="range-item {css_class}">
                    <span style="font-weight: 600;">{icon}</span> {label}
                </div>
            '''
        
        html += '</div></div>'
        return html

    def _render_details(self):
        """Renderiza detalles adicionales"""
        html = '''
            <div style="margin: 1rem 0;">
                <h4 style="margin: 0 0 0.75rem 0;">Detalles del Cálculo</h4>
                <table class="details-table">
        '''
        
        for detail in self.details:
            row_class = 'highlight-row' if detail.get('highlight') else ''
            html += f'''
                <tr class="{row_class}">
                    <td>{detail['label']}</td>
                    <td>{detail['value']}</td>
                </tr>
            '''
        
        html += '</table></div>'
        return html
    
    def _render_kpis(self):
        """Renderiza KPIs"""
        html = '<div class="kpi-grid">'
        for kpi in self.kpis:
            html += f'''
                <div class="kpi-card">
                    <div style="font-size: 1.5rem; font-weight: 700; margin-bottom: 0.5rem;">
                        {kpi['value']}
                    </div>
                    <div style="color: #64748b; font-size: 0.875rem;">
                        {kpi['label']}
                    </div>
                </div>
            '''
        html += '</div>'
        return html
    
    def _render_calculations(self):
        """Renderiza pasos de cálculo"""
        html = '''
            <div class="calculations">
                <h4 style="margin: 0 0 1rem 0;">Pasos del Cálculo</h4>
        '''
        
        for i, calc in enumerate(self.calculations, 1):
            html += f'''
                <div class="calculation-step">
                    <strong>Paso {i}: {calc['description']}</strong>
                    {f'<div style="margin: 0.5rem 0; font-family: monospace;">{calc["formula"]}</div>' if calc['formula'] else ''}
                    {f'<div style="color: #059669; font-weight: 600;">= {calc["result"]}</div>' if calc['result'] else ''}
                </div>
            '''
        
        html += '</div>'
        return html
    
    def _render_final_result(self):
        """Renderiza resultado final"""
        result = self.final_result
        return f'''
            <div class="final-result">
                <h3 style="margin: 0 0 1rem 0;">Resultado Final</h3>
                <div style="font-size: 2.5rem; font-weight: 800; margin-bottom: 1rem;">
                    {self._format_currency(result['amount'])}
                </div>
                <div style="opacity: 0.9;">
                    Cantidad: {result['quantity']:.2f} | Tasa: {result['rate']:.2f}%
                </div>
            </div>
        '''
    
    def _render_errors(self):
        """Renderiza errores"""
        html = '<div style="background: #fef2f2; border: 1px solid #ef4444; border-radius: 8px; padding: 1rem; margin-top: 1rem;">'
        for error in self.errors:
            html += f'''
                <div style="color: #b91c1c; margin: 0.5rem 0;">
                    <strong>Error:</strong> {error['message']}
                    {f'<div style="font-size: 0.875rem; margin-top: 0.25rem;">{error.get("details", "")}</div>' if error.get('details') else ''}
                </div>
            '''
        html += '</div>'
        return html

class PayrollRuleService:
    """Servicio especializado para cálculo de reglas de nómina"""
    
    def __init__(self, env):
        self.env = env
        self.engine = PayrollCalculationEngine(env)
    
    def calculate_salary_unified(self, contract, slip, worked_days, annual_parameters, 
                               salary_type='basic', validate_vacation=False, rate_percentage=100.0):
        """Método único para cálculo de salarios con manejo de cambios"""
        if worked_days and hasattr(worked_days, 'WORK100'):
            worked = worked_days.WORK100
            total_days = Decimal(str(worked.number_of_days))
            total_hours = Decimal(str(worked.number_of_hours))
        else:
            total_days = 0
            total_hours = 0

        steps = []
        steps.append(f"Días trabajados: {total_days}")
        steps.append(f"Horas trabajadas: {total_hours}")
        
        # Verificar cambios salariales
        cambios = sorted(contract.change_wage_ids, key=lambda c: c.date_start)
        change = next(
            (c for c in cambios if slip.date_from <= c.date_start <= slip.date_to), 
            None
        )
        
        old_wage = Decimal(str(contract.wage))
        hours_monthly = Decimal(str(annual_parameters.hours_monthly)) if annual_parameters.hours_monthly else Decimal('240')
        
        periods = []
        total_pay = Decimal('0')
        
        if change:
            # Manejo de cambios salariales
            change_day = change.date_start
            new_wage = Decimal(str(change.wage))
            
            days_before_change = days360(slip.date_from, change_day - timedelta(days=1))
            days_after_change = days360(change_day, slip.date_to)

            if days_before_change + days_after_change > total_days:
                ratio = total_days / (days_before_change + days_after_change)
                days_before_change = days_before_change * ratio
                days_after_change = days_after_change * ratio
            
            if total_days > 0:
                hours_before_change = total_hours * days_before_change / total_days
                hours_after_change = total_hours * days_after_change / total_days
            else:
                hours_before_change = Decimal('0')
                hours_after_change = Decimal('0')
            
            steps.append(f"Cambio salarial el {change_day.strftime('%d/%m/%Y')}")
            steps.append(f"Período 1 - Salario anterior ({old_wage}): {days_before_change:.2f} días")
            steps.append(f"Período 2 - Salario nuevo ({new_wage}): {days_after_change:.2f} días")
            
            if slip.struct_type_id.wage_type == 'hourly':
                rate_old = old_wage / hours_monthly
                rate_new = new_wage / hours_monthly
                pay_old = rate_old * hours_before_change
                pay_new = rate_new * hours_after_change
                
                periods.append({
                    'start': slip.date_from,
                    'end': change_day - timedelta(days=1),
                    'wage': float(old_wage),
                    'rate': float(rate_old),
                    'quantity': float(hours_before_change),
                    'amount': float(pay_old),
                    'unit': 'horas'
                })
                
                periods.append({
                    'start': change_day,
                    'end': slip.date_to,
                    'wage': float(new_wage),
                    'rate': float(rate_new),
                    'quantity': float(hours_after_change),
                    'amount': float(pay_new),
                    'unit': 'horas'
                })
                
            else:
                rate_old = old_wage / Decimal('30')
                rate_new = new_wage / Decimal('30')
                pay_old = rate_old * days_before_change
                pay_new = rate_new * days_after_change
                
                periods.append({
                    'start': slip.date_from,
                    'end': change_day - timedelta(days=1),
                    'wage': float(old_wage),
                    'rate': float(rate_old),
                    'quantity': float(days_before_change),
                    'amount': float(pay_old),
                    'unit': 'días'
                })
                
                periods.append({
                    'start': change_day,
                    'end': slip.date_to,
                    'wage': float(new_wage),
                    'rate': float(rate_new),
                    'quantity': float(days_after_change),
                    'amount': float(pay_new),
                    'unit': 'días'
                })
            
            total_pay = pay_old + pay_new
            has_changes = True
            
        else:
            steps.append("Sin cambios salariales en el periodo")
            
            if slip.struct_type_id.wage_type == 'hourly':
                rate = old_wage / hours_monthly
                total_pay = rate * total_hours
                
                periods.append({
                    'start': slip.date_from,
                    'end': slip.date_to,
                    'wage': float(old_wage),
                    'rate': float(rate),
                    'quantity': float(total_hours),
                    'amount': float(total_pay),
                    'unit': 'horas'
                })
                
            else:
                rate = old_wage / Decimal('30')
                total_pay = rate * total_days
                
                periods.append({
                    'start': slip.date_from,
                    'end': slip.date_to,
                    'wage': float(old_wage),
                    'rate': float(rate),
                    'quantity': float(total_days),
                    'amount': float(total_pay),
                    'unit': 'días'
                })
            
            has_changes = False
        
        if rate_percentage != 100.0:
            total_pay = total_pay * Decimal(str(rate_percentage)) / Decimal('100')
            steps.append(f"Aplicando {rate_percentage}% al total")
        
        steps.append(f"Total calculado: {total_pay:.2f}")
        
        if slip.struct_type_id.wage_type == 'hourly':
            quantity = total_hours
            avg_rate = total_pay / quantity if quantity > 0 else Decimal('0')
        else:
            quantity = total_days
            avg_rate = total_pay / quantity if quantity > 0 else Decimal('0')
        
        return {
            'rate': float(avg_rate),
            'quantity': float(quantity),
            'percentage': rate_percentage,
            'total': float(total_pay),
            'periods': periods,
            'steps': steps,
            'has_changes': has_changes,
            'wage_type': slip.struct_type_id.wage_type if hasattr(slip.struct_type_id, 'wage_type') else 'monthly'
        }

    def calculate_prestacion(self, localdict, prestacion_type, html_builder):
        """Método unificado para calcular prestaciones sociales"""
        contract = localdict['contract']
        slip = localdict['slip']
        employee = localdict['employee']
        
        # Configuración por tipo de prestación
        config = {
            'prima': {
                'rate': 8.33,
                'name': 'PRIMA DE SERVICIOS',
                'period_type': 'semestral',
                'conditions': [
                    {'type': 'tipo_coti_code', 'expected': ['12', '19'], 'negate': True, 'message': 'No es aprendiz'},
                    {'type': 'modality_salary', 'expected': 'integral', 'negate': True, 'message': 'No es salario integral'}
                ]
            },
            'cesantias': {
                'rate': 8.33,
                'name': 'CESANTÍAS',
                'period_type': 'anual',
                'conditions': [
                    {'type': 'tipo_coti_code', 'expected': ['12', '19'], 'negate': True, 'message': 'No es aprendiz'},
                    {'type': 'modality_salary', 'expected': 'integral', 'negate': True, 'message': 'No es salario integral'}
                ]
            },
            'vacaciones': {
                'rate': 4.17,
                'name': 'VACACIONES',
                'period_type': 'liquidacion',
                'conditions': [
                    {'type': 'tipo_coti_code', 'expected': ['12', '19'], 'negate': True, 'message': 'No es aprendiz'}
                ]
            },
            'intereses': {
                'rate': 12.0,
                'name': 'INTERESES CESANTÍAS',
                'period_type': 'anual',
                'conditions': [
                    {'type': 'tipo_coti_code', 'expected': ['12', '19'], 'negate': True, 'message': 'No es aprendiz'},
                    {'type': 'modality_salary', 'expected': 'integral', 'negate': True, 'message': 'No es salario integral'}
                ]
            }
        }
        
        prestacion_config = config[prestacion_type]
        
        # Validar condiciones
        valid, message = self.engine.validate_conditions(localdict, prestacion_config['conditions'])
        html_builder.add_validation(valid, message)
        
        if not valid:
            return 0, 0, 0, prestacion_config['name'], html_builder.generate_html(), {}
        
        # Determinar período
        date_from, date_to = self._get_period_dates(localdict, prestacion_config['period_type'])
        html_builder.add_period(date_from, date_to)
        
        # Calcular días
        dias_periodo = days360(date_from, date_to)
        dias_efectivos = self._calculate_effective_days(localdict, date_from, date_to)
        
        # Calcular base
        base_info = self._calculate_prestacion_base(localdict, prestacion_type, date_from, date_to)
        
        # KPIs principales
        html_builder.add_kpi('Días Período', dias_periodo, 'calendar', 'primary')
        html_builder.add_kpi('Días Efectivos', dias_efectivos, 'calendar-check', 'success')
        html_builder.add_kpi('Base Total', base_info['total'], 'calculator', 'primary', True)
        
        # Cálculo específico según tipo
        if prestacion_type == 'prima':
            return self._calculate_prima(base_info, dias_efectivos, html_builder, date_to)
        elif prestacion_type == 'cesantias':
            return self._calculate_cesantias(base_info, dias_efectivos, html_builder, date_to)
        elif prestacion_type == 'vacaciones':
            return self._calculate_vacaciones(localdict, base_info, date_from, date_to, html_builder)
        elif prestacion_type == 'intereses':
            return self._calculate_intereses(localdict, base_info, dias_efectivos, html_builder, date_to)
    
    def _get_period_dates(self, localdict, period_type):
        """Determina fechas del período según tipo"""
        slip = localdict['slip']
        contract = localdict['contract']
        
        if period_type == 'semestral':
            if slip.date_from.month <= 6:
                date_from = slip.date_from.replace(month=1, day=1)
                date_to = slip.date_from.replace(month=6, day=30)
            else:
                date_from = slip.date_from.replace(month=7, day=1)
                date_to = slip.date_from.replace(month=12, day=31)
        elif period_type == 'anual':
            date_from = slip.date_to.replace(month=1, day=1)
            date_to = slip.date_to.replace(month=12, day=31)
        elif period_type == 'liquidacion':
            date_from = slip.date_vacaciones if hasattr(slip, 'date_vacaciones') and slip.date_vacaciones else contract.date_start
            date_to = slip.date_liquidacion if hasattr(slip, 'date_liquidacion') and slip.date_liquidacion else slip.date_to
        else:
            date_from = contract.date_start
            date_to = slip.date_to
        
        # Ajustar si el contrato inició después
        if date_from < contract.date_start:
            date_from = contract.date_start
            
        # Ajustar si es liquidación
        if hasattr(slip, 'struct_process') and slip.struct_process == 'contrato' and hasattr(slip, 'date_liquidacion') and slip.date_liquidacion:
            date_to = slip.date_liquidacion
        
        return date_from, date_to
    
    def _calculate_effective_days(self, localdict, date_from, date_to):
        """Calcula días efectivos considerando suspensiones"""
        dias_periodo = days360(date_from, date_to)
        return dias_periodo
    
    def _calculate_prestacion_base(self, localdict, prestacion_type, date_from, date_to):
        """Calcula base para prestación considerando promedios según CST"""
        contract = localdict['contract']
        annual_params = localdict.get('annual_parameters')
        
        # Salario base
        salario_base = self.engine.to_decimal(contract.wage)
        
        # Auxilio de transporte (excepto vacaciones)
        auxilio_transporte = self.engine.to_decimal(0)
        if prestacion_type != 'vacaciones' and annual_params:
            if contract.wage < 2 * annual_params.smmlv_monthly:
                auxilio_transporte = self.engine.to_decimal(annual_params.transportation_assistance_monthly)
        
        # Conceptos variables (simplificado)
        conceptos_variables = self.engine.to_decimal(0)
        
        return {
            'salario_base': salario_base,
            'auxilio_transporte': auxilio_transporte,
            'conceptos_variables': conceptos_variables,
            'total': salario_base + auxilio_transporte + conceptos_variables
        }
    
    def _calculate_prima(self, base_info, dias_efectivos, html_builder, date_to):
        """Calcula prima de servicios"""
        base_diaria = base_info['total'] / self.engine.to_decimal(30)
        factor_prima = self.engine.to_decimal(15) / self.engine.to_decimal(180)
        valor_prima = base_diaria * dias_efectivos * factor_prima
        
        html_builder.add_calculation(
            'Fórmula Prima',
            '(Base Total / 30) × Días × (15 / 180)',
            self.engine.format_currency(valor_prima)
        )
        
        html_builder.set_final_result(valor_prima, dias_efectivos, 8.33)
        
        semestre = 1 if date_to.month <= 6 else 2
        nombre = f'PRIMA DE SERVICIOS {semestre}° SEMESTRE {date_to.year}'
        
        return float(base_diaria), float(dias_efectivos), 8.33, nombre, html_builder.generate_html(), {
            'valor_prima': float(valor_prima),
            'semestre': semestre
        }
    
    def _calculate_cesantias(self, base_info, dias_efectivos, html_builder, date_to):
        """Calcula cesantías"""
        base_diaria = base_info['total'] / self.engine.to_decimal(30)
        factor_cesantias = self.engine.to_decimal(30) / self.engine.to_decimal(360)
        valor_cesantias = base_diaria * dias_efectivos * factor_cesantias
        
        html_builder.add_calculation(
            'Fórmula Cesantías',
            '(Base Total / 30) × Días × (30 / 360)',
            self.engine.format_currency(valor_cesantias)
        )
        
        html_builder.set_final_result(valor_cesantias, dias_efectivos, 8.33)
        
        nombre = f'CESANTÍAS AÑO {date_to.year}'
        
        return float(base_diaria), float(dias_efectivos), 8.33, nombre, html_builder.generate_html(), {
            'valor_cesantias': float(valor_cesantias)
        }
    
    def _calculate_vacaciones(self, localdict, base_info, date_from, date_to, html_builder):
        """Calcula vacaciones por liquidación"""
        contract = localdict['contract']
        
        dias_trabajados = days360(date_from, date_to)
        dias_causados = (dias_trabajados * 15) / 360
        
        # Buscar días disfrutados (simplificado)
        dias_disfrutados = 0
        
        dias_pendientes = max(0, dias_causados - dias_disfrutados)
        
        base_diaria = base_info['total'] / self.engine.to_decimal(30)
        valor_vacaciones = base_diaria * self.engine.to_decimal(dias_pendientes)
        
        html_builder.add_kpi('Días Causados', f'{dias_causados:.2f}', 'plus-circle', 'info')
        html_builder.add_kpi('Días Disfrutados', dias_disfrutados, 'minus-circle', 'warning')
        html_builder.add_kpi('Días Pendientes', f'{dias_pendientes:.2f}', 'exclamation-circle', 'danger')
        
        html_builder.add_calculation(
            'Días Causados',
            f'({dias_trabajados} × 15) / 360',
            f'{dias_causados:.2f} días'
        )
        
        html_builder.set_final_result(valor_vacaciones, dias_pendientes, 100)
        
        nombre = f'VACACIONES LIQUIDACIÓN - PENDIENTES: {dias_pendientes:.2f} DÍAS'
        
        return float(base_diaria), float(dias_pendientes), 100, nombre, html_builder.generate_html(), {
            'dias_causados': dias_causados,
            'dias_pendientes': dias_pendientes,
            'valor_vacaciones': float(valor_vacaciones)
        }
    
    def _calculate_intereses(self, localdict, base_info, dias_efectivos, html_builder, date_to):
        """Calcula intereses de cesantías"""
        # Obtener cesantías (simplificado)
        cesantias = base_info['total'] * 0.0833
        
        tasa_anual = self.engine.to_decimal(12)
        tasa_prorrateada = (dias_efectivos / self.engine.to_decimal(360)) * tasa_anual
        valor_intereses = self.engine.to_decimal(cesantias) * (tasa_prorrateada / 100)
        
        html_builder.add_kpi('Base Cesantías', cesantias, 'bank', 'primary', True)
        html_builder.add_kpi('Tasa Prorrateada', f'{tasa_prorrateada:.2f}%', 'percentage', 'warning')
        
        html_builder.add_calculation(
            'Fórmula Intereses',
            'Cesantías × (Días / 360) × 12%',
            self.engine.format_currency(valor_intereses)
        )
        
        html_builder.set_final_result(valor_intereses, dias_efectivos, float(tasa_prorrateada))
        
        nombre = f'INTERESES CESANTÍAS AÑO {date_to.year}'
        
        return float(valor_intereses / dias_efectivos) if dias_efectivos > 0 else 0, float(dias_efectivos), float(tasa_prorrateada), nombre, html_builder.generate_html(), {
            'cesantias_base': float(cesantias),
            'valor_intereses': float(valor_intereses)
        }

class HrSalaryRule(models.Model):
    _inherit = 'hr.salary.rule'
    
    # Campos existentes mantenidos y mejorados
    struct_id = fields.Many2one(tracking=True)
    active = fields.Boolean(tracking=True)
    sequence = fields.Integer(tracking=True)
    condition_select = fields.Selection(tracking=True)
    amount_select = fields.Selection(
        selection_add=[('concept', 'Concept Code')], 
        ondelete={'concept': 'set default'}
    )
    amount_python_compute = fields.Text(tracking=True)
    appears_on_payslip = fields.Boolean(tracking=True)
    
    # Campos específicos lavish
    types_employee = fields.Many2many('hr.types.employee', string='Tipos de Empleado', tracking=True)
    dev_or_ded = fields.Selection([
        ('devengo', 'Devengo'),
        ('deduccion', 'Deducción')
    ], 'Naturaleza', tracking=True)
    type_concepts = fields.Selection([
        ('contrato', 'Fijo Contrato'),
        ('ley', 'Por Ley'),
        ('novedad', 'Novedad Variable'),
        ('prestacion', 'Prestación Social'),
        ('tributaria', 'Deducción Tributaria')
    ], 'Tipo', required=True, default='contrato', tracking=True)
    
    aplicar_cobro = fields.Selection([
        ('15', 'Primera quincena'),
        ('30', 'Segunda quincena'),
        ('0', 'Siempre')
    ], 'Aplicar cobro', tracking=True)
    
    modality_value = fields.Selection([
        ('fijo', 'Valor fijo'),
        ('diario', 'Valor diario'),
        ('diario_efectivo', 'Valor diario del día efectivamente laborado')
    ], 'Modalidad de valor', tracking=True)
    
    # Campos para prestaciones sociales
    base_prima = fields.Boolean('Para prima', tracking=True)
    base_cesantias = fields.Boolean('Para cesantías', tracking=True)
    base_vacaciones = fields.Boolean('Para vacaciones tomadas', tracking=True)
    base_vacaciones_dinero = fields.Boolean('Para vacaciones dinero', tracking=True)
    base_intereses_cesantias = fields.Boolean('Para intereses de cesantías', tracking=True)
    base_auxtransporte_tope = fields.Boolean('Para tope de auxilio de transporte', tracking=True)
    base_compensation = fields.Boolean('Para liquidación de indemnización', tracking=True)
    
    # Base de Seguridad Social
    base_seguridad_social = fields.Boolean('Para seguridad social', tracking=True)
    base_arl = fields.Boolean('Para ARL', tracking=True)
    base_parafiscales = fields.Boolean('Para parafiscales', tracking=True)
    
    # Campos adicionales
    proyectar_nom = fields.Boolean('Proyectar en nomina')
    proyectar_ret = fields.Boolean('Proyectar en Retencion')
    is_leave = fields.Boolean('Es Ausencia', tracking=True)
    is_recargo = fields.Boolean('Es Recargos', tracking=True)
    deduction_applies_bonus = fields.Boolean('Aplicar deducción en Prima', tracking=True)
    account_tax_id = fields.Many2one("account.tax", "Impuesto de Retefuente Laboral")
    
    deduct_deductions = fields.Selection([
        ('all', 'Todas las deducciones'),
        ('law', 'Solo las deducciones de ley')
    ], 'Tener en cuenta al descontar', default='all', tracking=True)
    
    rounding_method = fields.Selection([
        ('no_round', 'Sin redondeo'),
        ('round1', 'Redondear a entero'),
        ('round100', 'Redondear al 100 más cercano'),
        ('round1000', 'Redondear al 1000 más cercano'),
        ('round2d', 'Redondear a 2 decimales')
    ], string='Método de redondeo', default='no_round')
    
    restart_one_month_prima = fields.Boolean('Restar 1 mes al promedio de los acumulados en prima', tracking=True)
    liquidar_con_base = fields.Boolean('Liquidar con IBC mes anterior', tracking=True)
    excluir_ret = fields.Boolean('Excluir de Calculo retefuente', tracking=True)
    is_projectable_rtf = fields.Boolean(
        string='Proyectable para Retención / Fondos',
        default=False,
        help='Indica si este concepto debe ser proyectado en el cálculo de retención en la fuente'
    )
    
    descontar_suspensiones = fields.Boolean('Descontar Licencia No remuneradas', tracking=True)
    salary_rule_accounting = fields.One2many('hr.salary.rule.accounting', 'salary_rule', string="Contabilización", tracking=True)
    
    # Reportes
    display_days_worked = fields.Boolean(string='Mostrar la cantidad de días trabajados en los formatos de impresión', tracking=True)
    short_name = fields.Char(string='Nombre corto/reportes')
    process = fields.Selection([
        ('nomina', 'Nónima'),
        ('vacaciones', 'Vacaciones'),
        ('prima', 'Prima'),
        ('cesantias', 'Cesantías'),
        ('intereses_cesantias', 'Intereses de cesantías'),
        ('contrato', 'Liq. de Contrato'),
        ('otro', 'Otro')
    ], string='Proceso')
    
    novedad_ded = fields.Selection([
        ('cont', 'Contrato'),
        ('Noved', 'Novedad'),
        ('0', 'No')
    ], 'Opcion de Novedad', tracking=True)
    
    not_include_flat_payment_file = fields.Boolean(string='No incluir en archivo plano de pagos')
    
    # Empleados públicos
    account_id_cxp = fields.Many2one('account.account', string='Cuenta CXP', company_dependent=True)
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
        :return: returns a tuple (amount, qty, rate, leave, log, other)
        :rtype: (float, float, float, bool/dict, bool/str, list)
        """
        self.ensure_one()
        res = 0, 0, 0, 0, 0, []
        
        try:
            if self.amount_select == 'fix':
                try:
                    return (
                        self.amount_fix or 0.0, 
                        float(safe_eval(self.quantity, localdict)), 
                        100.0,
                        False,
                        False,
                        False
                    )
                except Exception as e:
                    self._raise_error(localdict, _("Wrong quantity defined for:"), e, "amount_fix calculation")
                        
            if self.amount_select == 'percentage':
                try:
                    return (
                        float(safe_eval(self.amount_percentage_base, localdict)),
                        float(safe_eval(self.quantity, localdict)),
                        self.amount_percentage or 0.0,
                        False,
                        False,
                        False
                    )
                except Exception as e:
                    self._raise_error(localdict, _("Wrong percentage base or quantity defined for:"), e, "percentage calculation")
                        
            if self.amount_select == 'code':
                try:
                    safe_eval(self.amount_python_compute or "result = 0", localdict, mode='exec', nocopy=True)
                    result = float(localdict.get('result', 0))
                    result_qty = localdict.get('result_qty', 1.0) or 1
                    result_rate = localdict.get('result_rate', 100.0) or 100
                    return (
                        result,
                        result_qty,
                        result_rate,
                        False,
                        False,
                        False
                    )
                except Exception as e:
                    error_context = {
                        'code': self.amount_python_compute,
                        'location': 'Python code evaluation'
                    }
                    self._raise_error(localdict, _("Wrong python code defined for:"), e, "code evaluation", error_context)
                        
            if self.amount_select == 'concept':
                try:
                    method = getattr(self, f'_{str(self.code).lower()}', None)
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
   
    def _build_salary_html_log(
        self,
        periodo,
        aplicado,
        descripcion,
        calculation_result=None,
        days_info=None
        ):
        """
        Genera un log HTML simplificado para el cálculo de salario.
        Usa Font Awesome icons y diseño limpio.
        """
        # Color y icono según estado
        status_color = "success" if aplicado else "danger"
        status_icon = "check-circle" if aplicado else "times-circle"
        status_text = "Aplicado" if aplicado else "No Aplicado"
        
        # Iniciar HTML
        html = f'''
        <div class="salary-log-container card shadow-sm mb-3">
            <div class="card-header bg-light">
                <div class="d-flex justify-content-between align-items-center">
                    <h5 class="mb-0">
                        <i class="fa fa-calculator text-primary"></i> {self.name or descripcion}
                    </h5>
                    <span class="badge badge-{status_color}">
                        <i class="fa fa-{status_icon}"></i> {status_text}
                    </span>
                </div>
            </div>
            
            <div class="card-body">
                <!-- Periodo -->
                <div class="alert alert-info py-2 mb-3">
                    <i class="fa fa-calendar"></i> <strong>Período:</strong> {periodo}
                </div>
        '''
        
        # Si no está aplicado, mostrar razón
        if not aplicado:
            html += f'''
                <div class="alert alert-danger">
                    <i class="fa fa-exclamation-triangle"></i> {descripcion}
                </div>
            </div>
        </div>
            '''
            return html
        
        # Información de días
        if days_info and any(days_info.values()):
            html += '''
            <div class="row mb-3">
            '''
            
            days_config = [
                ('trabajados', 'Trabajados', 'briefcase', 'primary'),
                ('domingos', 'Domingos', 'sun', 'info'),
                ('sabado', 'Sábados', 'calendar-week', 'purple'),
                ('festivos', 'Festivos', 'gift', 'warning'),
                ('ausencias', 'Ausencias', 'user-times', 'danger')
            ]
            
            for key, label, icon, color in days_config:
                if key in days_info and days_info[key] > 0:
                    html += f'''
                    <div class="col-md-2 col-sm-4 col-6 mb-2">
                        <div class="text-center p-2 border rounded">
                            <i class="fa fa-{icon} text-{color} fa-2x mb-1"></i>
                            <h4 class="mb-0">{days_info[key]}</h4>
                            <small class="text-muted">{label}</small>
                        </div>
                    </div>
                    '''
            
            html += '</div><hr>'
        
        # Información del cálculo
        if calculation_result:
            total = calculation_result.get('total', 0)
            quantity = calculation_result.get('quantity', 0)
            rate = calculation_result.get('rate', 0)
            has_changes = calculation_result.get('has_changes', False)
            periods = calculation_result.get('periods', [])
            
            # Total calculado
            html += f'''
            <div class="bg-primary text-white rounded p-3 mb-3">
                <div class="row">
                    <div class="col-md-4">
                        <h6 class="text-white-50">TOTAL CALCULADO</h6>
                        <h3 class="mb-0">
                            <i class="fa fa-dollar-sign"></i> {total:,.2f}
                        </h3>
                    </div>
                    <div class="col-md-4">
                        <h6 class="text-white-50">CANTIDAD</h6>
                        <h4 class="mb-0">{quantity:.2f}</h4>
                    </div>
                    <div class="col-md-4">
                        <h6 class="text-white-50">TARIFA PROMEDIO</h6>
                        <h4 class="mb-0">${rate:,.2f}</h4>
                    </div>
                </div>
            </div>
            '''
            
            # Períodos con cambios
            if has_changes and periods:
                html += '''
                <h6 class="mb-2">
                    <i class="fa fa-exchange-alt"></i> Períodos con Cambios Salariales
                </h6>
                <div class="table-responsive mb-3">
                    <table class="table table-sm table-bordered">
                        <thead class="thead-light">
                            <tr>
                                <th width="50">#</th>
                                <th>Período</th>
                                <th>Salario</th>
                                <th>Cantidad</th>
                                <th class="text-right">Monto</th>
                            </tr>
                        </thead>
                        <tbody>
                '''
                
                for i, period in enumerate(periods, 1):
                    start = period['start']
                    end = period['end']
                    if hasattr(start, 'strftime'):
                        start = start.strftime('%d/%m/%Y')
                    if hasattr(end, 'strftime'):
                        end = end.strftime('%d/%m/%Y')
                    
                    html += f'''
                        <tr>
                            <td class="text-center">{i}</td>
                            <td>{start} - {end}</td>
                            <td>${period['wage']:,.2f}</td>
                            <td>{period['quantity']:.2f} {period['unit']}</td>
                            <td class="text-right"><strong>${period['amount']:,.2f}</strong></td>
                        </tr>
                    '''
                
                html += '''
                        </tbody>
                    </table>
                </div>
                '''
            
            # Detalles del cálculo
            steps = calculation_result.get('steps', [])
            if steps:
                html += '''
                <details>
                    <summary class="btn btn-sm btn-outline-secondary">
                        <i class="fa fa-info-circle"></i> Ver detalles del cálculo
                    </summary>
                    <div class="mt-2 p-2 bg-light rounded">
                        <ol class="mb-0 pl-3">
                '''
                
                for step in steps:
                    html += f'<li>{step}</li>'
                
                html += '''
                        </ol>
                    </div>
                </details>
                '''
        
        html += '''
            </div>
        </div>
        '''
        
        return html

    def _calculate_salary_unified(
        self,
        contract,
        slip,
        worked_days,
        annual_parameters,
        salary_type='basic',
        validate_vacation=False,
        rate_percentage=100.0):
        """
        Método único que contiene toda la lógica de cálculo de salario con manejo de cambios.
        """
        if worked_days.WORK100:
            worked = worked_days.WORK100
            total_days = Decimal(str(worked.number_of_days))
            total_hours = Decimal(str(worked.number_of_hours))
        else:
            worked = self.env['hr.work.entry']
            total_days = 0
            total_hours = 0
        
        steps = []
        steps.append(f"Días trabajados: {total_days}")
        steps.append(f"Horas trabajadas: {total_hours}")
        
        cambios = sorted(contract.change_wage_ids, key=lambda c: c.date_start)
        change = next(
            (c for c in cambios if slip.date_from <= c.date_start <= slip.date_to), 
            None
        )
        
        if change:
            previous_changes = [c for c in cambios if c.date_start < change.date_start]
            if previous_changes:
                old_wage = Decimal(str(previous_changes[-1].wage))
            else:
                old_wage = Decimal(str(contract.wage))
        else:
            old_wage = Decimal(str(contract.wage))
        
        hours_monthly = Decimal(str(annual_parameters.hours_monthly))
        
        periods = []
        total_pay = Decimal('0')
        
        if change:
            change_day = change.date_start
            new_wage = Decimal(str(change.wage))
            
            days_before_change = days360(slip.date_from, change_day - timedelta(days=1))
            days_after_change = days360(change_day, slip.date_to)

            if days_before_change + days_after_change > total_days:
                ratio = total_days / (days_before_change + days_after_change)
                days_before_change = days_before_change * ratio
                days_after_change = days_after_change * ratio
            
            if total_days > 0:
                hours_before_change = total_hours * days_before_change / total_days
                hours_after_change = total_hours * days_after_change / total_days
            else:
                hours_before_change = Decimal('0')
                hours_after_change = Decimal('0')
            
            steps.append(f"Cambio salarial el {change_day.strftime('%d/%m/%Y')}")
            steps.append(f"Período 1 - Salario anterior ({old_wage}): {days_before_change:.2f} días / {hours_before_change:.2f} horas")
            steps.append(f"Período 2 - Salario nuevo ({new_wage}): {days_after_change:.2f} días / {hours_after_change:.2f} horas")
            
            if slip.struct_type_id.wage_type == 'hourly':
                rate_old = old_wage / hours_monthly
                rate_new = new_wage / hours_monthly
                pay_old = rate_old * hours_before_change
                pay_new = rate_new * hours_after_change
                
                steps.append(f"Tasa horaria anterior: {rate_old:.2f}")
                steps.append(f"Tasa horaria nueva: {rate_new:.2f}")
                
                periods.append({
                    'start': slip.date_from,
                    'end': change_day - timedelta(days=1),
                    'wage': float(old_wage),
                    'rate': float(rate_old),
                    'quantity': float(hours_before_change),
                    'amount': float(pay_old),
                    'unit': 'horas'
                })
                
                periods.append({
                    'start': change_day,
                    'end': slip.date_to,
                    'wage': float(new_wage),
                    'rate': float(rate_new),
                    'quantity': float(hours_after_change),
                    'amount': float(pay_new),
                    'unit': 'horas'
                })
                
            else:
                rate_old = old_wage / Decimal('30')
                rate_new = new_wage / Decimal('30')
                pay_old = rate_old * days_before_change
                pay_new = rate_new * days_after_change
                
                steps.append(f"Tasa diaria anterior: {rate_old:.2f}")
                steps.append(f"Tasa diaria nueva: {rate_new:.2f}")
                
                periods.append({
                    'start': slip.date_from,
                    'end': change_day - timedelta(days=1),
                    'wage': float(old_wage),
                    'rate': float(rate_old),
                    'quantity': float(days_before_change),
                    'amount': float(pay_old),
                    'unit': 'días'
                })
                
                periods.append({
                    'start': change_day,
                    'end': slip.date_to,
                    'wage': float(new_wage),
                    'rate': float(rate_new),
                    'quantity': float(days_after_change),
                    'amount': float(pay_new),
                    'unit': 'días'
                })
            
            total_pay = pay_old + pay_new
            steps.append(f"Monto período anterior: {pay_old:.2f}")
            steps.append(f"Monto período nuevo: {pay_new:.2f}")
            
            has_changes = True
            
        else:
            steps.append("Sin cambios salariales en el periodo")
            
            if slip.struct_type_id.wage_type == 'hourly':
                rate = old_wage / hours_monthly
                total_pay = rate * total_hours
                steps.append(f"Tasa horaria: {rate:.2f}")
                
                periods.append({
                    'start': slip.date_from,
                    'end': slip.date_to,
                    'wage': float(old_wage),
                    'rate': float(rate),
                    'quantity': float(total_hours),
                    'amount': float(total_pay),
                    'unit': 'horas'
                })
                
            else:
                rate = old_wage / Decimal('30')
                total_pay = rate * total_days
                steps.append(f"Tasa diaria: {rate:.2f}")
                
                periods.append({
                    'start': slip.date_from,
                    'end': slip.date_to,
                    'wage': float(old_wage),
                    'rate': float(rate),
                    'quantity': float(total_days),
                    'amount': float(total_pay),
                    'unit': 'días'
                })
            
            has_changes = False
        
        if rate_percentage != 100.0:
            total_pay = total_pay * Decimal(str(rate_percentage)) / Decimal('100')
            steps.append(f"Aplicando {rate_percentage}% al total")
        
        steps.append(f"Total calculado: {total_pay:.2f}")
        
        if slip.struct_type_id.wage_type == 'hourly':
            quantity = total_hours
            avg_rate = total_pay / quantity if quantity > 0 else Decimal('0')
        else:
            quantity = total_days
            avg_rate = total_pay / quantity if quantity > 0 else Decimal('0')
        
        return {
            'rate': float(avg_rate),
            'quantity': float(quantity),
            'percentage': rate_percentage,
            'total': float(total_pay),
            'periods': periods,
            'steps': steps,
            'has_changes': has_changes,
            'wage_type': slip.struct_type_id.wage_type
        }

    def _basic(self, ld):
        """
        Sueldo básico estándar usando el método unificado.
        """
        contract = ld['contract']
        slip = ld['slip']
        periodo = f"{slip.date_from.strftime('%d/%m/%Y')} - {slip.date_to.strftime('%d/%m/%Y')}"
        
        if contract.subcontract_type or contract.modality_salary not in ('basico','especie','variable'):
            html = self._build_salary_html_log(
                periodo=periodo,
                aplicado=False,
                descripcion='Modalidad no aplicable'
            )
            return 0, 0, 0, False, html, False

        result = self._calculate_salary_unified(
            contract=contract,
            slip=slip,
            worked_days=ld['worked_days'],
            annual_parameters=ld['annual_parameters'],
            salary_type='basic',
            validate_vacation=False,
            rate_percentage=100.0
        )

        days_info = {
            'trabajados': ld.get('trabajados', 0),
            'domingos': ld.get('domingos', 0),
            'sabado': ld.get('sabado', 0),
            'festivos': ld.get('festivos', 0),
            'ausencias': ld.get('ausencias', 0)
        }
        html = self._build_salary_html_log(
            periodo=periodo,
            aplicado=True,
            descripcion='Cálculo Sueldo Básico',
            calculation_result=result,
            days_info=days_info
        )
        
        return (
            result['rate'],
            result['quantity'],
            result['percentage'],
            'SUELDO BASICO',
            html,
            False
        )

    def _basic002(self, ld):
        """
        Sueldo básico integral usando el método unificado.
        """
        contract = ld['contract']
        slip = ld['slip']
        periodo = f"{slip.date_from.strftime('%d/%m/%Y')} - {slip.date_to.strftime('%d/%m/%Y')}"
        
        if contract.subcontract_type or contract.modality_salary != 'integral':
            html = self._build_salary_html_log(
                periodo=periodo,
                aplicado=False,
                descripcion='Modalidad integral no aplicable'
            )
            return 0, 0, 0, False, html, False
        
        try:
            result = self._calculate_salary_unified(
                contract=contract,
                slip=slip,
                worked_days=ld['worked_days'],
                annual_parameters=ld['annual_parameters'],
                salary_type='integral',
                validate_vacation=True,
                rate_percentage=100.0
            )
        except UserError as e:
            html = self._build_salary_html_log(
                periodo=periodo,
                aplicado=False,
                descripcion=str(e)
            )
            raise
        
        days_info = {
            'trabajados': ld.get('trabajados', 0),
            'domingos': ld.get('domingos', 0),
            'sabado': ld.get('sabado', 0),
            'festivos': ld.get('festivos', 0),
            'ausencias': ld.get('ausencias', 0)
        }
        
        html = self._build_salary_html_log(
            periodo=periodo,
            aplicado=True,
            descripcion='Cálculo Sueldo Integral',
            calculation_result=result,
            days_info=days_info
        )
        
        return (
            result['rate'],
            result['quantity'],
            result['percentage'],
            'SUELDO BASICO INTEGRAL',
            html,
            False
        )

    def _basic003(self, ld):
        """
        Cuota sostenimiento usando el método unificado.
        """
        contract = ld['contract']
        slip = ld['slip']
        employee = ld['employee']
        periodo = f"{slip.date_from.strftime('%d/%m/%Y')} - {slip.date_to.strftime('%d/%m/%Y')}"
        
        if contract.subcontract_type or contract.modality_salary != 'sostenimiento':
            html = self._build_salary_html_log(
                periodo=periodo,
                aplicado=False,
                descripcion='Modalidad sostenimiento no aplicable'
            )
            return 0, 0, 0, False, html, False
        
        rate_percentage = 100.0
        name = 'CUOTA DE SOSTENIMIENTO'
        
        if employee.tipo_coti_id:
            tp = employee.tipo_coti_id.code
            if tp == '12':
                name = 'CUOTA DE SOSTENIMIENTO LECTIVO'
                rate_percentage = 100.0
            elif tp == '19':
                name = 'CUOTA DE SOSTENIMIENTO PRODUCTIVO'
                rate_percentage = 100.0
        
        try:
            result = self._calculate_salary_unified(
                contract=contract,
                slip=slip,
                worked_days=ld['worked_days'],
                annual_parameters=ld['annual_parameters'],
                salary_type='apprentice',
                validate_vacation=True,
                rate_percentage=rate_percentage
            )
        except UserError as e:
            html = self._build_salary_html_log(
                periodo=periodo,
                aplicado=False,
                descripcion=str(e)
            )
            raise
        
        days_info = {
            'trabajados': ld.get('trabajados', 0),
            'domingos': ld.get('domingos', 0),
            'sabado': ld.get('sabado', 0),
            'festivos': ld.get('festivos', 0),
            'ausencias': ld.get('ausencias', 0)
        }
        
        html = self._build_salary_html_log(
            periodo=periodo,
            aplicado=True,
            descripcion=f'Cálculo {name}',
            calculation_result=result,
            days_info=days_info
        )
        
        return (
            result['rate'],
            result['quantity'],
            result['percentage'],
            name,
            html,
            False
        )

    # =====================================================
    # MÉTODOS AUXILIARES PARA CÁLCULO DE AUXILIOS
    # =====================================================

    def _get_auxilio_previo(self, localdict, codigo_auxilio):
        """
        Busca valor de auxilio previo en current_month
        
        Args:
            localdict: Diccionario con datos
            codigo_auxilio: Código del auxilio a buscar (AUX000, AUX00C)
        
        Returns:
            dict: {
                'encontrado': bool,
                'valor': float,
                'dias': float
            }
        """
        contract = localdict['contract']
        current_month = localdict['current_month']
        all_payslip_ids = set()
        current_slip_ids = [p for p in current_month]
        for p_id in current_slip_ids:
            all_payslip_ids.add(p_id)
        if all_payslip_ids:
            aux_lines = self.env['hr.payslip.line'].search([
                ('slip_id', 'in', list(all_payslip_ids)),
                ('salary_rule_id.code', '=', codigo_auxilio),
                ('contract_id', '=', contract.id)
            ])
            
            if aux_lines:
                valor_total = sum(line.amount for line in aux_lines)
                dias_total = sum(line.quantity for line in aux_lines)
                return {
                    'encontrado': True,
                    'valor': valor_total,
                    'dias': dias_total
                }
        
        return {
            'encontrado': False,
            'valor': 0,
            'dias': 0
        }

    def _get_salary_base_for_tope(self, localdict):
        """
        Calcula la base salarial para validación de tope de auxilios
        Usa rules_multi para el periodo actual
        
        Returns:
            float: Base salarial calculada
        """
        contract = localdict['contract']
        slip = localdict['slip']
        rules_multi = localdict['rules_multi']
        
        basic_total = 0
        for code, rule_data in rules_multi.items():
            current = rule_data.get('current', {})
            if current.get('category') == 'BASIC':
                basic_total += current.get('total', 0)
        
        if contract.only_wage == 'wage':
            salary_base = contract.wage
            
        elif contract.only_wage == 'wage_dev':
            dev_salarial_total = 0
            for code, rule_data in rules_multi.items():
                current = rule_data['current']
                if current.get('object').category_id.code == 'DEV_SALARIAL' or current.get('object').category_id.parent_id.code == 'DEV_SALARIAL':
                    dev_salarial_total += current.get('total', 0)
                all_payslip_ids = set()
                current_month = localdict['current_month']
                current_slip_ids = [p for p in current_month]

                for p_id in current_slip_ids:
                    all_payslip_ids.add(p_id)

                if all_payslip_ids:
                    dev_lines = self.env['hr.payslip.line'].search([
                        ('slip_id', 'in', list(all_payslip_ids)),
                        ('contract_id', '=', contract.id),
                        ('salary_rule_id.category_id.code', '!=', 'BASIC'),
                        ('salary_rule_id.category_id.code', '=', 'DEV_SALARIAL'),
                        ('salary_rule_id.category_id.parent_id.code', '=', 'DEV_SALARIAL')
                    ])
                    
                    for line in dev_lines:
                        dev_salarial_total += line.amount
            salary_base = (dev_salarial_total - basic_total) + contract.wage
            
        else:
            salary_base = basic_total
        
        return salary_base

    def _calculate_auxilio_days(self, localdict):
        """
        Calcula los días para auxilio considerando pagos quincenales
        
        Returns:
            tuple: (dias_total, dias_primera_quincena)
        """
        contract = localdict['contract']
        worked_days = localdict['worked_days']
        dias = worked_days.WORK100.number_of_days
        dias_primera = 0
        all_payslip_ids = set()
        current_month = localdict['current_month']
        current_slip_ids = [p for p in current_month]
        if current_slip_ids:
            for p_id in current_slip_ids:
                all_payslip_ids.add(p_id)
            dev_lines = self.env['hr.payslip.line'].search([
                ('slip_id', 'in', list(all_payslip_ids)),
                ('contract_id', '=', contract.id),
                ('salary_rule_id.category_id.code', '=', 'BASIC'),
            ])
            for line in dev_lines:
                dias_primera += line.quantity       
        return dias, dias_primera

    def _validate_auxilio_conditions(self, localdict, tipo_auxilio):
        """
        Valida condiciones específicas del auxilio
        
        Args:
            localdict: diccionario con datos
            tipo_auxilio: 'transporte' o 'conectividad'
        
        Returns:
            tuple: (es_valido, razon)
        """
        contract = localdict['contract']
        employee = localdict['employee']
        slip = localdict['slip']
        annual_parameters = localdict.get('annual_parameters')
        if contract.not_validate_top_auxtransportation:
            return True, "Auxilio sin validación de condiciones"
        if not annual_parameters:
            return False, "No hay parámetros anuales configurados"
        
        if tipo_auxilio == 'conectividad':
            if not contract.remote_work_allowance:
                return False, "No aplica auxilio de conectividad"
        else: 
            if contract.not_pay_auxtransportation:
                return False, "Auxilio desactivado en contrato"
            
            if contract.modality_salary == 'sostenimiento':
                if not employee.tipo_coti_id or employee.tipo_coti_id.code not in ['12', '19']:
                    return False, "Modalidad sostenimiento solo para aprendices"
            
            if employee.tipo_coti_id and not contract.not_validate_top_auxtransportation:
                tipo_coti = employee.tipo_coti_id.code
                if tipo_coti == '12' and not annual_parameters.aux_apr_lectiva:
                    return False, "Aprendiz etapa lectiva sin auxilio"
                elif tipo_coti == '19' and not annual_parameters.aux_apr_prod:
                    return False, "Aprendiz etapa productiva sin auxilio"
        
        if contract.pay_auxtransportation and slip.date_from.day < 15:
            return False, "Se paga solo en segunda quincena"
        
        if contract.modality_salary == 'integral':
            return False, "Salario integral no recibe auxilio"
        
        return True, ""

    def _calculate_auxilio_generic(self, localdict, tipo_auxilio, codigo_auxilio):
        """
        Método genérico para calcular auxilios
        
        Args:
            localdict: diccionario con datos
            tipo_auxilio: 'transporte' o 'conectividad'
            codigo_auxilio: 'AUX000' o 'AUX00C'
        
        Returns:
            tuple estándar de payroll
        """
        html_builder = PayrollHTMLGenerator(self.name, self.code, self.env)
        service = PayrollCalculationEngine(self.env)
        
        contract = localdict['contract']
        slip = localdict['slip']
        annual_parameters = localdict.get('annual_parameters')
        worked_days = localdict['worked_days']
        
        html_builder.add_period(slip.date_from, slip.date_to)
        
        aux_previo = self._get_auxilio_previo(localdict, codigo_auxilio)
        
        es_valido, razon = self._validate_auxilio_conditions(localdict, tipo_auxilio)
        if not es_valido:
            html_builder.add_validation(False, razon)
            display_name = 'AUXILIO DE CONECTIVIDAD' if tipo_auxilio == 'conectividad' else 'AUXILIO DE TRANSPORTE'
            return 0, 0, 0, display_name, html_builder.generate_html(), {}
        
        if tipo_auxilio == 'conectividad':
            monthly_value = annual_parameters.value_auxilio_conectividad or annual_parameters.transportation_assistance_monthly
            salary_limit = annual_parameters.top_max_auxilio_conectividad or (2 * annual_parameters.smmlv_monthly)
            display_name = 'AUXILIO DE CONECTIVIDAD'
            icon = 'wifi'
        else:
            monthly_value = annual_parameters.transportation_assistance_monthly
            salary_limit = 2 * annual_parameters.smmlv_monthly
            display_name = 'AUXILIO DE TRANSPORTE'
            icon = 'money-bill'
        
        daily_value = monthly_value / 30
        
        dias, dias_primera = self._calculate_auxilio_days(localdict)
        
        if dias == 0:
            html_builder.add_validation(False, "Sin días trabajados")
            return 0, 0, 0, display_name, html_builder.generate_html(), {}
        
        if contract.pay_auxtransportation and slip.date_from.day >= 15:
            html_builder.add_detail('Días 1ra quincena', dias_primera)
            html_builder.add_detail('Días 2da quincena', worked_days.WORK100.number_of_days if worked_days.WORK100 else 0)
            html_builder.add_detail('Total días mes', dias)
        
        total = daily_value * dias
        supera_tope = False
        
        if contract.not_validate_top_auxtransportation:
            html_builder.add_detail('Validación tope', 'DESHABILITADA - Pago directo')
            html_builder.add_validation(True, "Auxilio sin validación de tope")
        else:
            salary_validation = self._get_salary_base_for_tope(localdict)
            
            html_builder.add_detail('Salario para tope', service.format_currency(salary_validation))
            html_builder.add_detail('Tope', service.format_currency(salary_limit))
            
            supera_tope = salary_validation > salary_limit
            
            if supera_tope:
                html_builder.add_validation(False, "Supera el tope salarial")
                if contract.dev_aux:
                    html_builder.add_kpi('Estado', 'DEVOLUCIÓN REQUERIDA', 'exclamation-triangle', 'danger')
                    html_builder.add_detail('Acción', 'Se aplicará devolución (dev_aux activo)', True)
                else:
                    html_builder.add_kpi('Estado', 'NO APLICA AUXILIO', 'times-circle', 'warning')
                    html_builder.add_detail('Acción', 'No se paga auxilio (sin devolución)', True)
                
                total = 0
                dias = 0
            else:
                html_builder.add_validation(True, "Dentro del tope salarial")
        
        if not supera_tope:
            html_builder.add_kpi('Días Aplicados', dias, 'calendar', 'primary')
            html_builder.add_kpi('Valor Diario', daily_value, 'dollar-sign', 'info', True)
            html_builder.add_kpi('Valor Mensual', monthly_value, icon, 'success', True)
            
            if contract.pay_auxtransportation and slip.date_from.day >= 15:
                html_builder.add_kpi('Período', 'Mes Completo', 'calendar-check', 'warning')
            
            html_builder.add_calculation(
                display_name,
                f'${daily_value:,.2f} × {dias} días',
                service.format_currency(total)
            )
        
        html_builder.set_final_result(total, dias, 100)
        
        if 'auxilio_info' not in localdict:
            localdict['auxilio_info'] = {}
        
        dias_totales, _ = self._calculate_auxilio_days(localdict)
        
        localdict['auxilio_info'][tipo_auxilio] = {
            'supera_tope': supera_tope,
            'dias_calculados': dias_totales,
            'valor_diario': daily_value,
            'valor_total_sin_tope': daily_value * dias_totales
        }
        
        return daily_value if not supera_tope else 0, dias, 100, display_name, html_builder.generate_html(), {
            'valor_diario': daily_value,
            'dias': dias,
            'total': total,
            'supera_tope': supera_tope
        }

    def _calculate_devolucion_generic(self, localdict, tipo_auxilio, codigo_auxilio):
        """
        Método genérico para calcular devoluciones de auxilios
        
        Args:
            localdict: diccionario con datos
            tipo_auxilio: 'transporte' o 'conectividad'
            codigo_auxilio: 'AUX000' o 'AUX00C'
        
        Returns:
            tuple estándar de payroll
        """
        html_builder = PayrollHTMLGenerator(self.name, self.code, self.env)
        service = PayrollCalculationEngine(self.env)

        contract = localdict['contract']
        annual_parameters = localdict.get('annual_parameters')
        
        auxilio_info = localdict.get('auxilio_info', {}).get(tipo_auxilio, {})
        supera_tope = auxilio_info.get('supera_tope', False)
        
        display_name = 'DEVOLUCION AUXILIO DE CONECTIVIDAD' if tipo_auxilio == 'conectividad' else 'DEVOLUCION AUXILIO DE TRANSPORTE'
        
        if not contract.dev_aux:
            html_builder.add_validation(False, "Devolución no habilitada en el contrato")
            return 0, 0, 0, display_name, html_builder.generate_html(), {}
        
        if not supera_tope:
            html_builder.add_validation(False, "No supera el tope salarial - No aplica devolución")
            return 0, 0, 0, display_name, html_builder.generate_html(), {}
        
        auxilio_a_devolver = auxilio_info.get('valor_total_sin_tope', 0)
        dias_devolver = auxilio_info.get('dias_calculados', 0)
        
        if auxilio_a_devolver <= 0:
            # Buscar en current_month si no hay info
            aux_previo = self._get_auxilio_previo(localdict, codigo_auxilio)
            if aux_previo['encontrado'] and aux_previo['valor'] > 0:
                auxilio_a_devolver = abs(aux_previo['valor'])
                dias_devolver = aux_previo['dias']
            else:
                html_builder.add_validation(False, "No hay valor de auxilio para devolver")
                return 0, 0, 0, display_name, html_builder.generate_html(), {}
        
        html_builder.add_validation(True, "Devolución aplicada: Contrato con dev_aux Y supera tope salarial")
        html_builder.add_kpi('Contrato dev_aux', 'SÍ', 'check-circle', 'success')
        html_builder.add_kpi('Supera Tope', 'SÍ', 'exclamation-triangle', 'warning')
        
        html_builder.add_kpi('Auxilio a Devolver', auxilio_a_devolver, 'undo', 'danger', True)
        html_builder.add_kpi('Días a Devolver', dias_devolver, 'calendar-minus', 'warning')
        
        html_builder.add_detail('Condición 1: dev_aux', 'CUMPLE', True)
        html_builder.add_detail('Condición 2: Supera tope', 'CUMPLE', True)
        html_builder.add_detail('Valor sin tope', service.format_currency(auxilio_a_devolver))
        
        html_builder.add_calculation(
            'Devolución Auxilio',
            f'Valor total auxilio calculado',
            service.format_currency(-auxilio_a_devolver)
        )
        
        html_builder.set_final_result(-auxilio_a_devolver, dias_devolver, 100)
        
        # Obtener valor diario según tipo
        if tipo_auxilio == 'conectividad':
            monthly_value = annual_parameters.value_auxilio_conectividad or annual_parameters.transportation_assistance_monthly
        else:
            monthly_value = annual_parameters.transportation_assistance_monthly
        
        daily_value = monthly_value / 30
        
        return -daily_value, dias_devolver, 100, display_name, html_builder.generate_html(), {
            'devolucion': -auxilio_a_devolver,
            'motivo': 'dev_aux_y_tope_salarial'
        }

    # =====================================================
    # REGLAS PRINCIPALES DE AUXILIOS
    # =====================================================

    def _aux000(self, localdict):
        """Auxilio de transporte"""
        return self._calculate_auxilio_generic(localdict, 'transporte', 'AUX000')

    def _aux00c(self, localdict):
        """Auxilio de conectividad"""
        return self._calculate_auxilio_generic(localdict, 'conectividad', 'AUX00C')

    def _dev_aux000(self, localdict):
        """Devolución auxilio de transporte"""
        return self._calculate_devolucion_generic(localdict, 'transporte', 'AUX000')

    def _dev_aux00c(self, localdict):
        """Devolución auxilio de conectividad"""
        return self._calculate_devolucion_generic(localdict, 'conectividad', 'AUX00C')

    #                                         =
    # MÉTODOS DE SEGURIDAD SOCIAL
    #                                         =
    
    def _ibd(self, localdict, calculate_for='IBC'):
        """
        Calcula el IBC (Ingreso Base de Cotización) de forma unificada y organizada.
        
        Args:
            localdict: Diccionario con datos del cálculo
            calculate_for: Tipo de cálculo ('IBC' o 'FONDOS')
            
        Returns:
            tuple: (valor_dia, dias_ibc, rate, nombre, html, data_dict)
        """
        # Inicializar estructura de datos
        _ibd = self._initialize_ibd_structure(localdict, calculate_for)
        
        # Extraer datos básicos
        contract = localdict['contract']
        slip = localdict['slip']
        annual_parameters = localdict['annual_parameters']
        
        # Validar contrato de aprendizaje
        if contract and contract.contract_type == 'aprendizaje':
            return self._get_aprendizaje_response(_ibd)
        
        # 1. Calcular IBC mes anterior
        prev_month_data = self._calculate_prev_month_ibc_unified(contract, localdict, slip)
        _ibd['MES_ANTERIOR'] = prev_month_data
        daily_rate = prev_month_data['tarifa_diaria']
        dias_info = self._calculate_worked_days(slip, localdict)
        all_absences = self._collect_all_absences_unified(slip, contract, localdict)
        all_concepts = self._collect_all_normal_concepts(slip, contract, localdict, all_absences)
        processing_result = self._process_all_data(
            all_absences, 
            all_concepts, 
            daily_rate, 
            slip, 
            _ibd
        )
        
        # 6. Calcular IBC final con reglas del 40%
        ibc_calculation = self._calculate_final_ibc(
            processing_result,
            annual_parameters,
            calculate_for,
            localdict,
            _ibd
        )
        
        # 7. Calcular valor día
        dias_ibc = dias_info['total_days'] - processing_result['ausencias_no_remuneradas_days']
        day_value_info = self._calculate_day_value(
            ibc_calculation['ibc_final'],
            dias_ibc,
            dias_info['total_hours'],
            dias_info['wage_type'],
            annual_parameters
        )
        
        # 8. Actualizar estructura _ibd con todos los cálculos
        _ibd['CALCULOS'].update({
            **processing_result['totales'],
            **ibc_calculation,
            **day_value_info,
            'dias_trabajados': dias_info['total_days'],
            'dias_ibc': dias_ibc,
            'ausencias_no_remuneradas_dias': processing_result['ausencias_no_remuneradas_days'],
        })
        
        # 9. Generar HTML
        html = self._generate_complete_html(_ibd, processing_result['conceptos_tabla'], slip, calculate_for)
        
        # 10. Preparar respuesta
        nombre = f'BASES SEGURIDAD SOCIAL - {calculate_for}'
        if ibc_calculation.get('fondos_prev_month'):
            nombre += ' (Fondos ya calculados mes anterior)'
        
        return (
            float(day_value_info['valor_dia']),
            float(dias_ibc),
            100.0,
            nombre,
            html,
            {
                'ibc_final': ibc_calculation['ibc_final'],
                'day_value': day_value_info['valor_dia'],
                'ibc_base_puro': ibc_calculation['ibc_base_puro'],
                'ibc_40': ibc_calculation['ibc_40'],
                'ibc_base_final': ibc_calculation['ibc_base_final'],
                'ibc_sin_topes': ibc_calculation['ibc_sin_topes'],
                'vacaciones_incluidas': ibc_calculation.get('vacaciones_a_incluir', 0),
                'fondos_prev_month': ibc_calculation.get('fondos_prev_month', False),
                'force_ibc': processing_result.get('force_ibc', False),
                'wage_type': dias_info['wage_type'],
                '_ibd': _ibd,
            }
        )
    
                
    def _calculate_social_security_generic(self, localdict, tipo_ss, param_field, validation_field, display_name, rule_code=None):

        html_builder = PayrollHTMLGenerator(self.name, self.code, self.env)
        engine = PayrollCalculationEngine(self.env)
        
        contract = localdict['contract']
        slip = localdict['slip']
        employee = localdict['employee']
        annual_parameters = localdict['annual_parameters']
        
        periodo = f"{slip.date_from.strftime('%d/%m/%Y')} - {slip.date_to.strftime('%d/%m/%Y')}"
        html_builder.add_period(slip.date_from, slip.date_to)
        
        # Validar si contribuye
        if employee.subtipo_coti_id and getattr(employee.subtipo_coti_id, validation_field, False):
            html_builder.add_validation(False, f"El empleado no contribuye a {tipo_ss}")
            return 0, 0, 0, display_name, html_builder.generate_html(), {}
        
        if contract.contract_type == 'aprendizaje':
            html_builder.add_validation(False, "No aplica para contratos de aprendizaje")
            return 0, 0, 0, display_name, html_builder.generate_html(), {}
        
        porcentaje = getattr(annual_parameters, param_field, 0)
        
        ibc = 0
        dias = 0
        base = 0
        ibc = self._get_totalizar_reglas(liquidacion_data=localdict, codigos_regla="IBD", incluir_multi=True)
        html_builder.add_kpi('IBC (IBD)', ibc, 'calculator', 'primary', True)
        if self.code in ('SSOCIAL003','SSOCIAL004'):
            ibc,dias,_,_,_,_, = self._ibd(localdict=localdict, calculate_for="FONDO")
            ibc = ibc * dias
        if localdict["current_month"]:
            current_slip_ids = list(localdict["current_month"])
            lines = self.env['hr.payslip.line'].search([
                ('slip_id', '!=', slip.id),
                ('slip_id', 'in', current_slip_ids),
                ('contract_id', '=', contract.id),
                ('salary_rule_id.code', '=', rule_code),
                ('amount', '!=', 0)
            ], order='slip_id, sequence')
            for line in lines:
                base += line.amount
        aplicar = self.aplicar_cobro
        day = slip.date_from.day
        if aplicar and aplicar != '0':
            if (aplicar == '15' and day >= 15) or (aplicar == '30' and day < 15):
                html_builder.add_validation(False, f"No aplica para esta quincena (configurado para {aplicar})")
                return 0, 0, 0, display_name, html_builder.generate_html(), {}
        
        valor = float(ibc  - base) * (porcentaje / 100)
        
        html_builder.add_kpi('Porcentaje', f'{porcentaje}%', 'percent', 'info')
        html_builder.add_kpi('Tipo Cotizante', employee.subtipo_coti_id.name if employee.subtipo_coti_id else 'N/A', 'user', 'warning')
        
        html_builder.add_calculation(
            f'Cálculo {display_name}',
            f'{ibc - base} - {(base)} = × {porcentaje}%',
            engine.format_currency(valor)
        )
        
        html_builder.set_final_result(valor, -1, porcentaje)
        
        return float(ibc - base), -1, porcentaje, display_name, html_builder.generate_html(), {
            'ibc': float(ibc),
            'porcentaje': porcentaje,
            'valor': valor
        }

    def _ssocial001(self, localdict):
        return self._calculate_social_security_generic(
            localdict, 'salud', 'value_porc_health_employee', 
            'not_contribute_eps', 'Salud empleado',
            rule_code='SSOCIAL001'
        )

    def _ssocial002(self, localdict):
        """Pensión empleado"""
        return self._calculate_social_security_generic(
            localdict, 'pensión', 'value_porc_pension_employee',
            'not_contribute_pension', 'Pensión empleado',
            rule_code='SSOCIAL002'
        )

    def _ssocial003(self, localdict):
        html_builder = PayrollHTMLGenerator(self.name, self.code, self.env)
        annual_parameters = localdict.get('annual_parameters')
        contract = localdict['contract']

        ibc,dias,_,_,_,_, = self._ibd(localdict=localdict, calculate_for="FONDO")
        ibc = ibc * dias
        
        smmlv = annual_parameters.smmlv_monthly
        
        if ibc <= 4 * smmlv:
            html_builder.add_validation(False, f"IBC ({ibc:,.0f}) menor o igual a 4 SMMLV ({4 * smmlv:,.0f})")
            return 0, 0, 0, 'Fondo de solidaridad', html_builder.generate_html(), {}
        all_payslip_ids = set()
        current_month = localdict['current_month']
        current_slip_ids = [p for p in current_month]

        if current_slip_ids:
            for p_id in current_slip_ids:
                all_payslip_ids.add(p_id)
            fondos_lines = self.env['hr.payslip.line'].search([
                ('slip_id', 'in', list(all_payslip_ids)),
                ('salary_rule_id.code', 'in', ['SSOCIAL003',]),
                ('contract_id', '=', contract.id)
            ])
            
            for line in fondos_lines:
                if line.amount > 0 and line.salary_rule_id.code == 'SSOCIAL003':
                    html_builder.add_validation(False, f"Fondo solidaridad ya calculado: ${line.amount:,.0f}")
                    return 0, 0, 0, 'Fondo de solidaridad', html_builder.generate_html(), {}
        
        porcentaje = 0.5
        valor = float(ibc) * (porcentaje / 100)
        
        html_builder.add_kpi('IBC Base', ibc, 'calculator', 'primary', True)
        html_builder.add_kpi('SMMLV', f'{ibc / smmlv:.1f}', 'trending-up', 'warning')
        html_builder.add_kpi('Porcentaje', f'{porcentaje}%', 'percent', 'info')
        
        html_builder.add_detail('Condición:', f'IBC > 4 SMMLV ✓')
        
        html_builder.add_calculation(
            'Fondo de solidaridad',
            f'IBC × {porcentaje}%',
            f'${valor:,.0f}'
        )
        
        html_builder.set_final_result(valor, -1, porcentaje)
        
        return float(ibc), -1, porcentaje, 'Fondo de solidaridad', html_builder.generate_html(), {
            'ibc': float(ibc),
            'porcentaje': porcentaje,
            'valor': valor
        }

    def _ssocial004(self, localdict):
        """Fondo de subsistencia"""
        html_builder = PayrollHTMLGenerator(self.name, self.code, self.env)
        annual_parameters = localdict.get('annual_parameters')
        rules_multi = localdict.get('rules_multi', {})
        contract = localdict['contract']
        
        # Obtener IBC de IBD
        ibc,dias,_,_,_,_, = self._ibd(localdict=localdict, calculate_for="FONDO")
        ibc = ibc * dias
        smmlv = annual_parameters.smmlv_monthly
        if ibc <= 4 * smmlv:
            porcentaje = 0.0
            html_builder.add_validation(False, f"IBC ({ibc:,.0f}) menor o igual a 4 SMMLV ({4 * smmlv:,.0f})")
            return 0, 0, 0, 'Fondo de subsistencia', html_builder.generate_html(), {}
        elif ibc <= 16 * smmlv:
            porcentaje = 0.5
        elif ibc <= 17 * smmlv:
            porcentaje = 0.7
        elif ibc <= 18 * smmlv:
            porcentaje = 0.9
        elif ibc <= 19 * smmlv:
            porcentaje = 1.1
        elif ibc <= 20 * smmlv:
            porcentaje = 1.3
        else:
            porcentaje = 1.5
        all_payslip_ids = set()
        # Verificar si ya se calculó usando current_month
        current_month = localdict['current_month']
        current_slip_ids = [p for p in current_month]

        if current_slip_ids:
            for p_id in current_slip_ids:
                all_payslip_ids.add(p_id)

            fondos_lines = self.env['hr.payslip.line'].search([
                ('slip_id', 'in', list(all_payslip_ids)),
                ('salary_rule_id.code', 'in', ['SSOCIAL004']),
                ('contract_id', '=', contract.id)
            ])
            
            for line in fondos_lines:
                if line.amount > 0 and line.salary_rule_id.code == 'SSOCIAL004':
                    html_builder.add_validation(False, f"Fondo subsistencia ya calculado: ${line.amount:,.0f}")
                    return 0, 0, 0, 'Fondo de subsistencia', html_builder.generate_html(), {}
        
        # Calcular valor
        valor = float(ibc) * (porcentaje / 100)
        
        # Mostrar rangos
        html_builder.add_kpi('IBC Base', ibc, 'calculator', 'primary', True)
        html_builder.add_kpi('SMMLV', f'{ibc / smmlv:.1f}', 'trending-up', 'warning')
        html_builder.add_kpi('Porcentaje', f'{porcentaje}%', 'percent', 'info')
        
        html_builder.add_detail('Rangos Fondo Subsistencia:', '')
        ranges = [
            {'range': 'IBC ≤ 4 SMMLV', 'percent': '0.0%', 'active': ibc <= 4 * smmlv},
            {'range': 'IBC > 4 ≤ 16 SMMLV', 'percent': '0.5%', 'active': 4 * smmlv < ibc <= 16 * smmlv},
            {'range': 'IBC > 16 ≤ 17 SMMLV', 'percent': '0.7%', 'active': 16 * smmlv < ibc <= 17 * smmlv},
            {'range': 'IBC > 17 ≤ 18 SMMLV', 'percent': '0.9%', 'active': 17 * smmlv < ibc <= 18 * smmlv},
            {'range': 'IBC > 18 ≤ 19 SMMLV', 'percent': '1.1%', 'active': 18 * smmlv < ibc <= 19 * smmlv},
            {'range': 'IBC > 19 ≤ 20 SMMLV', 'percent': '1.3%', 'active': 19 * smmlv < ibc <= 20 * smmlv},
            {'range': 'IBC > 20 SMMLV', 'percent': '1.5%', 'active': ibc > 20 * smmlv}
        ]
        
        for r in ranges:
            marker = '→' if r['active'] else ' '
            html_builder.add_detail(f'{marker} {r["range"]}', r['percent'])
        
        html_builder.add_calculation(
            'Fondo de subsistencia',
            f'IBC × {porcentaje}%',
            f'${valor:,.0f}'
        )
        
        html_builder.set_final_result(valor, -1, porcentaje)
        
        return float(ibc), -1, porcentaje, 'Fondo de subsistencia', html_builder.generate_html(), {
            'ibc': float(ibc),
            'porcentaje': porcentaje,
            'valor': valor
        }
            
    #                                         =
    # PRESTACIONES SOCIALES
    #                                         =


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
        
        localdict = data_payslip
        
        prestaciones_service = self.env['prestaciones.sociales.service']
        from_month = 1 if localdict['payslip'].date_from.month <= 6 else 7
        to_month = 6 if localdict['payslip'].date_from.month <= 6 else 12
        to_day = 30 if localdict['payslip'].date_from.month <= 6 else 31
        date_from = localdict['payslip'].date_from.replace(month=from_month, day=1)
        date_to = localdict['payslip'].date_from.replace(month=to_month, day=to_day)
        
        if localdict['payslip'].struct_process == 'contrato':
            date_to = localdict['payslip'].date_liquidacion
        if date_from < contract.date_start:
            date_from = contract.date_start
        
        resultado = prestaciones_service.obtener_base(
            localdict=localdict,
            tipo_prestacion='prima',
            regla_obj=self,
            es_visual=True,
            fecha_inicio=date_from,
            fecha_fin=date_to
        )
        
        res_compat = resultado['resultado_compatible']
        base_dias = res_compat['base']
        dias = res_compat['days']
        log_html = resultado.get('log_html', '')
        data_visual = resultado.get('data_visual', {})
        
        fecha_fin = localdict['payslip'].date_to
        semestre = 1 if fecha_fin.month <= 6 else 2
        nombre = f"PRIMA DE SERVICIOS {semestre}° SEMESTRE {fecha_fin.year}"
        
        if localdict['payslip'].struct_process == 'contrato':
            nombre = f"PRIMA DE SERVICIOS {semestre}° SEMESTRE {fecha_fin.year} - LIQUIDACIÓN"
            valor_mes_anterior = self._get_totalizar_reglas(
                data_payslip, 'PRIMA', 
                incluir_current=True
            )
            if valor_mes_anterior:
                nombre += f" - VALOR ANTERIOR: ${valor_mes_anterior:,.2f}"
                valor_total = (base_dias * dias) - valor_mes_anterior
                return valor_total, 1, 100, nombre, log_html, {'data_kpi': data_visual}
        
        return base_dias, dias, 100, nombre, log_html, {'data_kpi': data_visual}

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
        
        # Adaptar localdict
        localdict = data_payslip
        # Calcular fechas del año
        prestaciones_service = self.env['prestaciones.sociales.service']
        date_ref = localdict['payslip'].date_to
        date_from = date_ref.replace(month=1, day=1)
        date_to = date_ref.replace(month=12, day=31)
        
        if date_from < contract.date_start:
            date_from = contract.date_start
            
        # Ajuste para liquidación
        if localdict['payslip'].struct_process == 'contrato' or localdict['payslip'].date_liquidacion:
            date_to = localdict['payslip'].date_liquidacion
        
        # Llamar al servicio
        resultado = prestaciones_service.obtener_base(
            localdict=localdict,
            tipo_prestacion='cesantias',
            regla_obj=self,
            es_visual=True,
            fecha_inicio=date_from,
            fecha_fin=date_to
        )
        
        # Extraer resultados
        res_compat = resultado['resultado_compatible']
        base_dias = res_compat['base']
        dias = res_compat['days']
        log_html = resultado.get('log_html', '')
        data_visual = resultado.get('data_visual', {})
        
        # Nombre descriptivo
        fecha_fin = localdict['payslip'].date_to
        nombre = f"CESANTÍAS AÑO {fecha_fin.year}"
        
        return base_dias, dias, 100, nombre, log_html, {'data_kpi': data_visual}

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
        
        # Validaciones para proceso de nómina
        is_interest_process = payslip.struct_id.process == 'nomina'
        should_pay_in_payroll = payslip.pay_cesantias_in_payroll
        
        if is_interest_process and should_pay_in_payroll:
            return 0, 0, 0, 0, "", {}
        
        # Adaptar localdict
        localdict = data_payslip

        # Calcular fechas del año
        prestaciones_service = self.env['prestaciones.sociales.service']
        date_ref = localdict['payslip'].date_to
        date_from = date_ref.replace(month=1, day=1)
        date_to = date_ref.replace(month=12, day=31)
        
        if date_from < contract.date_start:
            date_from = contract.date_start
            
        # Ajuste para liquidación
        if localdict['payslip'].struct_process == 'contrato' or localdict['payslip'].date_liquidacion:
            date_to = localdict['payslip'].date_liquidacion
        
        # Llamar al servicio
        resultado = prestaciones_service.obtener_base(
            localdict=localdict,
            tipo_prestacion='intereses',
            regla_obj=self,
            es_visual=True,
            fecha_inicio=date_from,
            fecha_fin=date_to
        )
        
        # Extraer resultados
        res_compat = resultado['resultado_compatible']
        base_dias = res_compat['base']
        dias = res_compat['days']
        log_html = resultado.get('log_html', '')
        data_visual = resultado.get('data_visual', {})
        
        # Calcular tasa (12% anual prorrateado)
        tasa = (dias / 360) * 12
        
        # Nombre descriptivo
        fecha_fin = localdict['payslip'].date_to
        nombre = f"INTERESES CESANTÍAS AÑO {fecha_fin.year}"
        
        return base_dias, dias, tasa, nombre, log_html, {'data_kpi': data_visual}

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
        
        # Validaciones
        skip = employee.tipo_coti_id.code in ['12', '19']
        skip |= contract.modality_salary == 'integral'
        skip |= contract.date_start.year == payslip.date_to.year
        
        if skip:
            return 0, 0, 0, 0, "", {}
        
        should_pay_in_payroll = payslip.pay_cesantias_in_payroll
        
        if not should_pay_in_payroll:
            return 0, 0, 0, 0, "", {}
        
        # Adaptar localdict
        localdict = data_payslip

        # Fechas del año anterior
        date_ref = payslip.date_to.replace(year=payslip.date_to.year - 1)
        date_from = date_ref.replace(month=1, day=1)  
        date_to = date_ref.replace(month=12, day=31)

        if date_from < contract.date_start:
            date_from = contract.date_start
        
        # Asegurar que el código de la regla esté presente
        localdict['rule']['code'] = 'INTCES_YEAR'
        
        # Llamar al servicio
        prestaciones_service = self.env['prestaciones.sociales.service']
        resultado = prestaciones_service.obtener_base(
            localdict=localdict,
            tipo_prestacion='intereses',
            regla_obj=self,
            es_visual=True,
            fecha_inicio=date_from,
            fecha_fin=date_to,
            periodo_texto=f"Año Anterior {date_from.year}"
        )
        
        # Extraer resultados
        res_compat = resultado['resultado_compatible']
        base_dias = res_compat['base']
        dias_plain = res_compat.get('plain_days', res_compat['days'])
        log_html = resultado.get('log_html', '')
        data_visual = resultado.get('data_visual', {})
        
        # Calcular tasa
        tasa = (res_compat['days'] / 360) * 12
        
        # Nombre descriptivo
        nombre = f"INT. CESANTIAS DEL PERIODO ANTERIOR {date_to.year}"
        
        return base_dias, dias_plain, tasa, nombre, log_html, {'data_kpi': data_visual}

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
        
        # Validaciones
        skip = employee.tipo_coti_id.code in ['12', '19']
        skip |= contract.modality_salary == 'integral'
        skip |= contract.date_start.year == payslip.date_to.year
        
        if skip:
            return 0, 0, 0, 0, "", {}
        
        # Verificar pagos previos
        for payments in payslip.severance_payments_reverse:
            if payments.type_history in ('cesantias', 'all'):
                tot_rule = payments.severance_value 
                return tot_rule, 1, 100, f"{self.name} {payments.final_accrual_date.year}", "", {}
        
        # Validaciones adicionales
        is_liquidation = payslip.struct_process == 'contrato'
        is_jan_feb = payslip.date_to.month in [1, 2]
        has_previous_year_option = payslip.pagar_cesantias_ano_anterior

        if not (is_liquidation and is_jan_feb and has_previous_year_option):
            return 0, 0, 0, 0, "", {}
        
        # Adaptar localdict
        localdict = data_payslip

        # Fechas del año anterior
        date_ref = payslip.date_to.replace(year=payslip.date_to.year - 1)
        date_from = date_ref.replace(month=1, day=1)  
        date_to = date_ref.replace(month=12, day=31)

        if date_from < contract.date_start:
            date_from = contract.date_start
        
        # Asegurar que el código de la regla esté presente
        localdict['rule']['code'] = 'CES_YEAR'
        
        # Llamar al servicio
        prestaciones_service = self.env['prestaciones.sociales.service']
        resultado = prestaciones_service.obtener_base(
            localdict=localdict,
            tipo_prestacion='cesantias',
            regla_obj=self,
            es_visual=True,
            fecha_inicio=date_from,
            fecha_fin=date_to,
            periodo_texto=f"Año Anterior {date_from.year}"
        )
        
        # Extraer resultados
        res_compat = resultado['resultado_compatible']
        base_dias = res_compat['base']
        dias_plain = res_compat.get('plain_days', res_compat['days'])
        log_html = resultado.get('log_html', '')
        data_visual = resultado.get('data_visual', {})
        
        # Nombre descriptivo
        nombre = f"CESANTIAS DEL PERIODO ANTERIOR {date_from.year}"
        
        return base_dias, dias_plain, 100, nombre, log_html, {'data_kpi': data_visual}
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

    #                                         =
    # INDEMNIZACIÓN
    #                                         =
       
    def _indem(self, data_payslip):
        
        def to_decimal(value):
            if isinstance(value, Decimal):
                return value
            elif value is None:
                return Decimal("0")
            return Decimal(str(value))
        
        def decimal_round(value, precision=2):
            value = to_decimal(value)
            decimal_precision = Decimal(f'0.{"0" * precision}1')
            return value.quantize(decimal_precision, rounding=ROUND_HALF_UP)
        
        def fmt_money(val):
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
        service = self.env['lavish.retencion.service']
        return service.calcular_retencion(payslip_data, tipo='indemnizacion')

    def _rt_met_01(self, payslip_data):
        if payslip_data['contract'].contract_type == 'aprendizaje':
            return 0, -1, 0, '', '', False
        aplicar = self.aplicar_cobro if hasattr(self, 'aplicar_cobro') else '0'
        day = payslip_data['slip'].date_from.day
        
        if (aplicar != "0" and 
            ((aplicar == "15" and day > 15) or 
            (aplicar == "30" and day < 16))):
            return 0, -1, 0, '', '', False
        service = self.env['lavish.retencion.service']
        return service.calcular_retencion(payslip_data, tipo='nomina')

    def _rtf_prima(self, payslip_data):
        if payslip_data['contract'].contract_type == 'aprendizaje':
            return 0, -1, 0, '', '', False
        
        if payslip_data['contract'].retention_procedure == '102':
            return 0, -1, 0, 'Prima incluida en cálculo normal', '', False
        
        service = self.env['lavish.retencion.service']
        return service.calcular_retencion(payslip_data, tipo='prima')

    #                                         =
    # PROVISIONES
    #                                         =
    def _calculate_days(
        self,
        localdict,
        ajustes
        ):
        """
        Calculates different types of days for the payroll period.
        
        This is a mid-level implementation of the calcular_dias method.
        """
        dias_info = {
            'trabajados': 0, 'ausencias': 0, 'festivos': 0, 'domingos': 0,
            'efectivos': 0, 'total':0, 'habiles': 0
        }

        worked_days_dict = localdict.get('worked_days', {}).dict

        if not worked_days_dict:
            _logger.warning("'worked_days' not found in localdict for calcular_dias.")
            dias_info['trabajados'] = localdict.get('trabajados', 0)
            dias_info['ausencias'] = localdict.get('ausencias', 0)
            dias_info['festivos'] = localdict.get('festivos', 0)
            dias_info['domingos'] = localdict.get('domingos', 0)
        else:
            # Sum days by type from worked_days
            for code, wd_line in worked_days_dict.items():
                days = wd_line.number_of_days if hasattr(wd_line, 'number_of_days') else 0
                if not days: continue

                if code == 'WORK100':
                    dias_info['trabajados'] += days
                elif code.startswith('LEAVE'):
                    dias_info['ausencias'] += days
                elif code == 'FEST':
                    dias_info['festivos'] += days
                elif code == 'DOM':
                    dias_info['domingos'] += days

        # Calculate effective days and totals
        dias_info['efectivos'] = dias_info['trabajados']
        dias_info['total'] = dias_info['trabajados'] + dias_info['ausencias'] + dias_info['festivos'] + dias_info['domingos']
        dias_info['habiles'] = dias_info['trabajados'] + (0 if ajustes.get('excluir_festivos', False) else dias_info['festivos'])

        # Check if there are detailed absences
        if self._has_detailed_absences(localdict):
            absence_details = self._detail_absences(localdict, filtros=ajustes.get('filtros_ausencias'))
            if absence_details:
                dias_info['ausencias_detalle'] = absence_details

        return dias_info

    def _has_detailed_absences(self, localdict) -> bool:
        """
        Verifies if the localdict has the necessary information to detail absences.
        """
        return bool(localdict.get('employee') and localdict.get('date_from') and localdict.get('date_to'))

    def _detail_absences(self, localdict, filtros = None):
        """
        Extracts absence details (hr.leave) that intersect with the payroll period,
        applying optional filters.
        """
        filtros = filtros or {}
        employee = localdict.get('employee')
        fecha_inicio_nomina = localdict.get('date_from')
        fecha_fin_nomina = localdict.get('date_to')

        if not employee or not fecha_inicio_nomina or not fecha_fin_nomina:
            return {}

        filtro_fecha_inicio = filtros.get('solo_periodo', {}).get('fecha_inicio', fecha_inicio_nomina)
        filtro_fecha_fin = filtros.get('solo_periodo', {}).get('fecha_fin', fecha_fin_nomina)

        Leave = self.env['hr.leave']
        domain = [
            ('employee_id', '=', employee.id),
            ('state', '=', 'validate'),
            ('date_from', '<=', filtro_fecha_fin),
            ('date_to', '>=', filtro_fecha_inicio)
        ]
        
        # Add type filter if specified
        if 'solo_tipo' in filtros:
            leave_type = self.env['hr.leave.type'].search([('code', '=', filtros['solo_tipo'])], limit=1)
            if leave_type:
                domain.append(('holiday_status_id', '=', leave_type.id))
            else:
                _logger.warning(f"Absence type with code '{filtros['solo_tipo']}' not found.")
                return {}

        leaves = Leave.search(domain)
        if not leaves:
            return {}

        # Group by type and calculate days within original payroll period
        resultado = defaultdict(lambda: {
            'nombre': '', 'dias': 0, 'descuenta_prima': False,
            'descuenta_cesantias': False, 'descuenta_vacaciones': False,
            'descuenta_prestaciones': False, 'ausencias': []
        })

        for leave in leaves:
            leave_type = leave.holiday_status_id
            tipo_codigo = getattr(leave_type, 'code', f"LEAVE{leave_type.id}")

            # Check 'afecta_prestaciones' filter
            descuenta_alguna = (getattr(leave_type, 'descuenta_prima', False) or
                              getattr(leave_type, 'descuenta_cesantias', False) or
                              getattr(leave_type, 'descuenta_vacaciones', False))

            if filtros.get('afecta_prestaciones', False) and not descuenta_alguna:
                continue

            # Calculate effective days of absence WITHIN payroll period
            fecha_inicio_efectiva = max(leave.date_from.date(), fecha_inicio_nomina)
            fecha_fin_efectiva = min(leave.date_to.date(), fecha_fin_nomina)

            # Ensure effective range is valid
            if fecha_inicio_efectiva > fecha_fin_efectiva:
                continue

            # Calculate days using exact method for real duration within period
            dias_en_periodo = (fecha_fin_efectiva - fecha_inicio_efectiva).days + 1

            # Initialize type info if first time
            if tipo_codigo not in resultado:
                resultado[tipo_codigo]['nombre'] = leave_type.name
                resultado[tipo_codigo]['descuenta_prima'] = getattr(leave_type, 'descuenta_prima', False)
                resultado[tipo_codigo]['descuenta_cesantias'] = getattr(leave_type, 'descuenta_cesantias', False)
                resultado[tipo_codigo]['descuenta_vacaciones'] = getattr(leave_type, 'descuenta_vacaciones', False)
                resultado[tipo_codigo]['descuenta_prestaciones'] = descuenta_alguna

            # Accumulate days
            resultado[tipo_codigo]['dias'] += dias_en_periodo

            # Add absence detail (with effective dates in period)
            resultado[tipo_codigo]['ausencias'].append({
                'id': leave.id,
                'fecha_inicio_original': leave.date_from.date(),
                'fecha_fin_original': leave.date_to.date(),
                'fecha_inicio_efectiva': fecha_inicio_efectiva,
                'fecha_fin_efectiva': fecha_fin_efectiva,
                'dias_en_periodo': dias_en_periodo,
                'nombre': leave.name or leave_type.name
            })

        return dict(resultado)



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
            'intereses': {'campo_base': 'base_cesantias', 'tasa': 12, 'nombre': "INTERESES CESANTÍAS", 'codigo': 'PRV_ICES'}
        }[provision_type]
        
        descontar_suspensiones = self.descontar_suspensiones
        
        if self.env.company.simple_provisions or self.code == 'PRV_VAC':
            dias_info = self._calculate_days(data_payslip, ajustes={})
            dias_trabajados = dias_info.get('trabajados', 0)
            dias_ausencias = dias_info.get('ausencias', 0)
            
            dias_trabajados = sum(l.number_of_days for l in slip.worked_days_line_ids if l.code == 'WORK100')
            dias_ausencias = sum(ld.days_payslip for ld in slip.leave_days_ids
                if not ld.leave_id.holiday_status_id.unpaid_absences)
            dias_suspension = sum(ld.days_payslip for ld in slip.leave_days_ids
                if ld.leave_id.holiday_status_id.unpaid_absences)
            dias_computables = dias_trabajados + dias_ausencias
            if descontar_suspensiones:
                dias_computables = dias_trabajados + dias_ausencias + dias_suspension
                
            base_salario = (contract.wage / 30) * dias_computables
            
            # Calcular auxilio de transporte con la lógica mejorada
            auxilio_transporte = self._calcular_auxilio_transporte_provision(
                data_payslip, contract, parametros_anuales, dias_computables
            )

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
                base_total += base_salario + auxilio_transporte
            
            if provision_type == 'intereses':
                base_cesantias = self._get_totalizar_reglas(data_payslip, codigos_regla="PRV_CES", incluir_current=False, incluir_multi=True)
                valor_provision = base_cesantias * 0.12
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
            fecha_fin=date_to
        )
        
        if provision_type == 'vacaciones':
            base_dias = resultado['resultado_compatible']['base']
            dias = resultado['resultado_compatible']['days']
            tasa = 4.17
        elif provision_type in ['prima', 'cesantias']:
            base_dias = resultado['data_visual']['meta_info']['diferencia_provision'] / resultado['resultado_compatible']['days']
            dias = resultado['resultado_compatible']['days']
            tasa = 100
        elif provision_type == 'intereses':
            base_dias = resultado['data_visual']['meta_info']['diferencia_provision'] / resultado['resultado_compatible']['days']
            dias = resultado['resultado_compatible']['days']
            dias_anio = days360(date_from, date_to)
            tasa = 100
            resultado['data_visual']['base_cesantias'] = self._get_totalizar_reglas(data_payslip, codigos_regla="PRV_CES", incluir_current=False, incluir_multi=True)

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

    def _calcular_auxilio_transporte_provision(self, data_payslip, contract, parametros_anuales, dias_computables):
        """
        
        Args:
            data_payslip: Diccionario con datos de liquidación
            contract: Contrato del empleado
            parametros_anuales: Parámetros anuales
            dias_computables: Días a considerar para el cálculo
            
        Returns:
            float: Valor del auxilio de transporte
        """
        if contract.modality_aux == "basico":
            salary_base = contract.wage
            tope_aux = parametros_anuales.top_max_transportation_assistance
            if salary_base <= tope_aux:
                auxilio_diario = parametros_anuales.transportation_assistance_monthly / 30
                return auxilio_diario * dias_computables
            else:
                return 0
                
        elif contract.modality_aux == "variable":
            salary_base = self._get_salary_base_for_tope(data_payslip)
            
            tope_aux = parametros_anuales.top_max_transportation_assistance
            
            if salary_base <= tope_aux:
                auxilio_diario = parametros_anuales.transportation_assistance_monthly / 30
                return auxilio_diario * dias_computables
            else:
                return 0
            
        else:
            return 0


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
        return sum(line.balance for line in provision_lines)
    
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
        Args:
            data_payslip (dict): Diccionario con datos de liquidación
        Returns:
            tuple: (base, días, tasa, nombre, log, datos_prima)
        """
        return self._calculate_provision(data_payslip, 'prima')

    def _prv_ces(self, data_payslip):
        """
        Args:
            data_payslip (dict): Diccionario con datos de liquidación
        Returns:
            tuple: (base, días, tasa, nombre, log, datos_cesantias)
        """
        return self._calculate_provision(data_payslip, 'cesantias')

    def _prv_ices(self, data_payslip):
        """
        Args:
            data_payslip (dict): Diccionario con datos de liquidación
        Returns:
            tuple: (base, días, tasa, nombre, log, datos_intereses)
        """
        return self._calculate_provision(data_payslip, 'intereses')


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
        """Calcula horas extras con log detallado y validación por línea"""
        html_builder = PayrollHTMLGenerator(self.name, self.code, self.env)
        engine = PayrollCalculationEngine(self.env)
        
        contract = localdict['contract']
        employee = localdict['employee']
        slip = localdict['slip']
        annual_parameters = localdict['annual_parameters']
                
        if contract.not_pay_overtime:
            html_builder.add_validation(False, 'El contrato tiene marcado "No liquidar horas extras"')
            return 0.0, 0.0, 0.0, self.name, html_builder.generate_html(), {}
        
        OVERTIME_CONFIG = {
            'HEYREC001': {'percentage': 125.0, 'multiplier': 1.25, 'name': 'Horas extra diurnas', 'field': 'overtime_ext_d'},
            'HEYREC002': {'percentage': 200.0, 'multiplier': 2.0, 'name': 'Horas extra diurnas dominical/festiva', 'field': 'overtime_eddf'},
            'HEYREC003': {'percentage': 175.0, 'multiplier': 1.75, 'name': 'Horas extra nocturna', 'field': 'overtime_ext_n'},
            'HEYREC004': {'percentage': 110.0, 'multiplier': 1.1, 'name': 'Horas recargo festivo', 'field': 'overtime_rndf'},
            'HEYREC005': {'percentage': 35.0, 'multiplier': 0.35, 'name': 'Horas Recargo Nocturno', 'field': 'overtime_rn'},
            'HEYREC006': {'percentage': 250.0, 'multiplier': 2.5, 'name': 'Horas extra nocturna dominical/festiva', 'field': 'overtime_endf'},
            'HEYREC007': {'percentage': 175.0, 'multiplier': 1.75, 'name': 'Horas Dominicales', 'field': 'overtime_dof'},
            'HEYREC008': {'percentage': 75.0, 'multiplier': 0.75, 'name': 'Recargos dominicales', 'field': 'overtime_rdf'}
        }
        
        config = self.env['hr.type.overtime'].search([('salary_rule.code', '=', rule_code)], limit=1)
        percentage = config.percentage if config and config.percentage != 0 else OVERTIME_CONFIG.get(rule_code, {}).get('percentage', 100.0)
        multiplier = percentage / 100.0
        rule_name = config.name if config else OVERTIME_CONFIG.get(rule_code, {}).get('name', rule_code)
        field_name = OVERTIME_CONFIG.get(rule_code, {}).get('field', '')
        
        aplicar = int(self.aplicar_cobro or 0)
        day_from = slip.date_from.day
        date_search = slip.date_from
        if aplicar == 30:
            date_search = datetime(slip.date_from.year, slip.date_from.month, 1).date()        
        if aplicar != 0 and not (aplicar >= day_from):
            html_builder.add_validation(False, f'No aplica para esta quincena (configurado para día {aplicar})')
            return 0.0, 0.0, percentage, rule_name, html_builder.generate_html(), {}
        
        all_overtime_records = self.env['hr.overtime'].search([
            ('employee_id', '=', employee.id),
            ('date', '>=', date_search),
            ('date_end', '<=', slip.date_to)
        ])
        
        if not all_overtime_records:
            html_builder.add_validation(False, 'No hay horas registradas para este tipo')
            return 0.0, 0.0, percentage, rule_name, html_builder.generate_html(), {}
        
        if slip.date_from.month == 7 or slip.date_to.month == 7:
            html_builder.add_validation(
                True, 
                "Período cruza julio - Validando cambio de horas según Ley 2101 de 2021",
                'warning'
            )
        
        total_hours = 0
        total_value = 0
        line_details = []
        base_hours_variations = {}
        sunday_surcharge_variations = {}
        
        weighted_hourly_rate_sum = 0
        total_hours_for_average = 0
        
        for idx, overtime in enumerate(all_overtime_records):
            if not field_name or not hasattr(overtime, field_name):
                continue
                
            hours_in_record = getattr(overtime, field_name, 0)
            if hours_in_record <= 0:
                continue
            
            result = self.env['hr.company.working.hours'].get_current_hours(
                company_id=employee.company_id.id,
                date=overtime.date
            )
            base_hours = self._get_hours_config_for_date(
                company_id=employee.company_id.id,
                date_reference=overtime.date
            )
            if not base_hours:
                base_hours = annual_parameters.hours_monthly if annual_parameters and annual_parameters.hours_monthly else 240
            if isinstance(result, dict):
                sunday_surcharge = result.get('sunday_surcharge', 75.0)
            else:
                _, sunday_surcharge = result
            

            
            if base_hours not in base_hours_variations:
                base_hours_variations[base_hours] = []
            base_hours_variations[base_hours].append({
                'date': overtime.date,
                'record_id': overtime.id
            })
            
            current_multiplier = multiplier
            current_percentage = percentage
            
            if config.apply_sunday_surcharge:
                current_percentage = sunday_surcharge
                current_multiplier = current_percentage / 100.0
                
                if sunday_surcharge not in sunday_surcharge_variations:
                    sunday_surcharge_variations[sunday_surcharge] = []
                sunday_surcharge_variations[sunday_surcharge].append({
                    'date': overtime.date,
                    'record_id': overtime.id
                })
                percentage = sunday_surcharge
            hourly_rate = contract.wage / base_hours
            
            weighted_hourly_rate_sum += hourly_rate * hours_in_record
            total_hours_for_average += hours_in_record
            
            rate_with_overtime = hourly_rate * current_multiplier
            value_for_record = rate_with_overtime * hours_in_record
            
            line_detail = {
                'record_id': overtime.id,
                'date': overtime.date,
                'date_end': overtime.date_end,
                'hours': hours_in_record,
                'base_hours': base_hours,
                'hourly_rate': hourly_rate,
                'rate_with_overtime': rate_with_overtime,
                'value': value_for_record
            }
            line_details.append(line_detail)
            
            html_builder.add_calculation(
                f'Registro #{idx + 1} ({overtime.date.strftime("%d/%m")} - {overtime.date_end.strftime("%d/%m")})',
                f'{hours_in_record:.2f}h × ${hourly_rate:,.2f}/h × {current_multiplier} (Base: {base_hours}h/mes)',
                engine.format_currency(value_for_record)
            )
            
            total_hours += hours_in_record
            total_value += value_for_record
        
        # Calcular el hourly_rate promedio ponderado
        average_hourly_rate = weighted_hourly_rate_sum / total_hours_for_average if total_hours_for_average > 0 else 0
        
        unit_value = total_value / total_hours if total_hours > 0 else 0
        
        if rule_code in ['HEYREC007'] and sunday_surcharge_variations:
            percentage = list(sunday_surcharge_variations.keys())[0]
            if rule_code == 'HEYREC007':
                percentage = percentage
        
        html_builder.add_kpi('Total Horas', f'{total_hours:.2f}', 'clock', 'primary')
        html_builder.add_kpi('Valor Total', total_value, 'dollar-sign', 'success', True)
        html_builder.add_kpi('Valor Unitario', unit_value, 'dollar-sign', 'info', True)
        html_builder.add_kpi('Recargo', f'{percentage}%', 'percent', 'warning')
        
        # Agregar KPI para el hourly_rate promedio si hay variaciones
        if len(base_hours_variations) > 1:
            html_builder.add_kpi('Tarifa/hora promedio', average_hourly_rate, 'dollar-sign', 'info', True)
            html_builder.add_validation(
                True,
                f'Se detectaron {len(base_hours_variations)} configuraciones diferentes de horas base',
                'warning'
            )
            for base_hours, records in base_hours_variations.items():
                html_builder.add_detail(
                    f'Base {base_hours}h/mes',
                    f'Aplicado en {len(records)} registro(s)'
                )
        
        # Mostrar variaciones en recargo dominical si aplica
        if rule_code in ['HEYREC007'] and len(sunday_surcharge_variations) > 1:
            html_builder.add_validation(
                True,
                f'Se detectaron {len(sunday_surcharge_variations)} porcentajes diferentes de recargo dominical',
                'warning'
            )
            for surcharge, records in sunday_surcharge_variations.items():
                html_builder.add_detail(
                    f'Recargo dominical {surcharge}%',
                    f'Aplicado en {len(records)} registro(s)'
                )
        
        html_builder.add_detail('Total de registros procesados', len(line_details), True)
        html_builder.add_detail('Promedio horas por registro', f'{total_hours/len(line_details):.2f}' if line_details else '0', False)
        
        html_builder.set_final_result(total_value, total_hours, percentage)
        
        name = f'{rule_name} - {total_hours:.2f}h'
        
        overtime_data = {
            'hours': total_hours,
            'rate': unit_value, 
            'value': total_value,
            'line_details': line_details,
            'base_hours_variations': base_hours_variations,
            'average_hourly_rate': average_hourly_rate  # Agregar el promedio al diccionario
        }
        
        if rule_code in ['HEYREC007']:
            overtime_data['sunday_surcharge_variations'] = sunday_surcharge_variations
        
        # Retornar el hourly_rate promedio ponderado en lugar del hourly_rate del contrato
        return average_hourly_rate, total_hours, percentage, name, html_builder.generate_html(), overtime_data

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

    def _calculate_total_from_rules(self, localdict, category, exclude_not_in_net=True):
        html_builder = PayrollHTMLGenerator(self.name, self.code, self.env)
        rules_multi = localdict['rules_multi']
        total = 0
        details = {}
        category_totals = {}
        
        for code, rule_data in rules_multi.items():
            current = rule_data['current']
            rule_obj = current.get('object')
            
            if not rule_obj:
                continue
                
            if exclude_not_in_net and rule_obj.not_computed_in_net:
                continue
            
            cat_code = rule_obj.category_id.code
            parent_cat_code = rule_obj.category_id.parent_id.code if rule_obj.category_id.parent_id else None
            
            if cat_code in category or (parent_cat_code and parent_cat_code in category):
                amount = current.get('total', 0)
                total += amount
                details[code] = amount
                
                category_key = cat_code if cat_code in category else parent_cat_code
                if category_key not in category_totals:
                    category_totals[category_key] = 0
                category_totals[category_key] += amount
        
        html = self._generate_category_summary_html(category_totals, grand_total=total, localdict=localdict, categories_used=category)
        
        return total, 1, 100, False, html, details

    def _generate_category_summary_html(self, category_totals, grand_total, localdict, categories_used):
        """Genera HTML con resumen de categorías - versión simplificada"""
        
        # Definir colores planos y iconos para categorías
        categories_style = {
            'DEV_SALARIAL': {'icon': 'fa-money', 'color': '#28a745'},
            'DEV_NO_SALARIAL': {'icon': 'fa-gift', 'color': '#17a2b8'},
            'PRESTACIONES_SOCIALES': {'icon': 'fa-shield', 'color': '#20c997'},
            'AUX': {'icon': 'fa-plus-square', 'color': '#6610f2'},
            'IND': {'icon': 'fa-gavel', 'color': '#fd7e14'},
            'BASIC': {'icon': 'fa-briefcase', 'color': '#28a745'},
            'HEYREС': {'icon': 'fa-clock-o', 'color': '#ffc107'},
            'COMISIONES': {'icon': 'fa-percent', 'color': '#17a2b8'},
            'DEDUCCIONES': {'icon': 'fa-minus-circle', 'color': '#f59e0b'},
            'SSOCIAL': {'icon': 'fa-heartbeat', 'color': '#dc3545'},
        }
        
        # Calcular totales
        total_devengos = sum(amount for cat, amount in category_totals.items() 
                            if cat != 'DEDUCCIONES' and amount > 0)
        total_deducciones = abs(category_totals.get('DEDUCCIONES', 0))
        
        # Color del neto según positivo o negativo
        neto_color = '#3b82f6' if grand_total >= 0 else '#ef4444'
        
        html = f'''
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif; max-width: 800px; margin: 0 auto;">
            
            <!-- Cards de categorías -->
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin-bottom: 2rem;">
        '''
        
        # Mostrar cada categoría calculada
        for cat in categories_used:
            if cat in category_totals and category_totals[cat] != 0:
                style = categories_style.get(cat, {'icon': 'fa-circle', 'color': '#6c757d'})
                amount = category_totals[cat]
                
                # Card de categoría
                html += f'''
                <div style="background: white; border: 2px solid #e9ecef; border-radius: 8px; padding: 1.25rem; text-align: center;">
                    <div style="font-size: 2rem; color: {style['color']}; margin-bottom: 0.5rem;">
                        <i class="fa {style['icon']}"></i>
                    </div>
                    <div style="font-size: 1.25rem; font-weight: 700; color: #2d3748; margin-bottom: 0.25rem;">
                        ${abs(amount):,.2f}
                    </div>
                    <div style="font-size: 0.75rem; color: #718096; text-transform: uppercase;">
                        {cat.replace('_', ' ')}
                    </div>
                </div>
                '''
        
        html += '''
            </div>
            
            <!-- Sección de totales -->
            <div style="background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
        '''
        
        # Total Devengos
        html += f'''
                <div style="display: flex; justify-content: space-between; align-items: center; padding: 1.5rem; border-bottom: 1px solid #e9ecef;">
                    <div style="display: flex; align-items: center; gap: 1rem;">
                        <div style="width: 48px; height: 48px; background: #28a74510; border-radius: 8px; display: flex; align-items: center; justify-content: center;">
                            <i class="fa fa-plus-circle" style="color: #28a745; font-size: 1.5rem;"></i>
                        </div>
                        <span style="color: #4b5563; font-weight: 600;">TOTAL DEVENGOS</span>
                    </div>
                    <span style="color: #28a745; font-size: 1.5rem; font-weight: 700;">
                        ${total_devengos:,.2f}
                    </span>
                </div>
        '''
        
        # Total Deducciones
        html += f'''
                <div style="display: flex; justify-content: space-between; align-items: center; padding: 1.5rem; border-bottom: 1px solid #e9ecef;">
                    <div style="display: flex; align-items: center; gap: 1rem;">
                        <div style="width: 48px; height: 48px; background: #f59e0b10; border-radius: 8px; display: flex; align-items: center; justify-content: center;">
                            <i class="fa fa-minus-circle" style="color: #f59e0b; font-size: 1.5rem;"></i>
                        </div>
                        <span style="color: #4b5563; font-weight: 600;">TOTAL DEDUCCIONES</span>
                    </div>
                    <span style="color: #f59e0b; font-size: 1.5rem; font-weight: 700;">
                        ${total_deducciones:,.2f}
                    </span>
                </div>
        '''
        
        # Neto a Pagar
        html += f'''
                <div style="background: {neto_color}10; padding: 2rem;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <div style="display: flex; align-items: center; gap: 1rem;">
                            <div style="width: 56px; height: 56px; background: white; border-radius: 8px; display: flex; align-items: center; justify-content: center;">
                                <i class="fa fa-money" style="color: {neto_color}; font-size: 1.75rem;"></i>
                            </div>
                            <span style="color: #1f2937; font-weight: 700; font-size: 1.125rem;">NETO A PAGAR</span>
                        </div>
                        <span style="color: {neto_color}; font-size: 2rem; font-weight: 800;">
                            ${grand_total:,.2f}
                        </span>
                    </div>
                </div>
            </div>
        </div>
        '''
        
        return html

    
    def _totaldev(self, localdict):
        return self._calculate_total_from_rules(
            localdict, 
            category=['DEV_SALARIAL', 'DEV_NO_SALARIAL', 'PRESTACIONES_SOCIALES', 'AUX', 'IND']
        )

    def _totalded(self, localdict):
        return self._calculate_total_from_rules(localdict, category=['DEDUCCIONES'])

    def _net(self, localdict):
        devengos, _, _, _, _, _ = self._calculate_total_from_rules(
            localdict,
            category=['DEV_SALARIAL', 'DEV_NO_SALARIAL', 'PRESTACIONES_SOCIALES', 'AUX', 'IND']
        )
        
        deducciones, _, _, _, _, _ = self._calculate_total_from_rules(
            localdict,
            category=['DEDUCCIONES']
        )
        
        neto = devengos + deducciones
        category_totals = {
            'DEV_SALARIAL': 0,
            'DEV_NO_SALARIAL': 0,
            'PRESTACIONES_SOCIALES': 0,
            'AUX': 0,
            'IND': 0,
            'DEDUCCIONES': deducciones
        }
        category = ['DEV_SALARIAL', 'DEDUCCIONES', 'DEV_NO_SALARIAL', 'PRESTACIONES_SOCIALES', 'AUX', 'IND']
        rules_multi = localdict['rules_multi']
        for code, rule_data in rules_multi.items():
            current = rule_data['current']
            rule_obj = current.get('object')
            if rule_obj and not getattr(rule_obj, 'not_computed_in_net', False):
                cat_code = rule_obj.category_id.code
                if cat_code in category_totals and cat_code != 'DEDUCCIONES':
                    category_totals[cat_code] += current.get('total', 0)
        html = self._generate_category_summary_html(category_totals, grand_total=neto, localdict=localdict, categories_used=category)
        return neto, 1, 100, False, html, {'neto': neto}

    #                                         =
    # MÉTODOS AUXILIARES ADICIONALES
    #                                         =
    
    def need_compute_salary_average(self, contract, date_from, date_to):
        """Determina si necesita calcular promedio salarial según Art. 253 CST"""
        date_3_months_before = date_to - relativedelta(months=3)
        if date_from > date_3_months_before:
            date_3_months_before = date_from
        
        return contract.has_change_salary(date_3_months_before, date_to)
    
    def get_salary_rule(self, salary_rule_code, type_employee_id):
        """Obtiene regla salarial por código"""
        return self.env['hr.salary.rule'].search([('code', '=', salary_rule_code)], limit=1)
        
    def get_holiday_book(self, contract, date_from=False, date_ref=False):
        """Calcula los días de vacaciones acumulados y disponibles"""
        date_ref = date_ref or contract.date_ref_holiday_book or datetime.now().date()
        worked_days = days360(date_from or contract.date_start, date_ref)
        
        days_enjoyed = 0
        days_paid = 0
        days_suspension = 0
        
        for holiday_book in contract.vacaciones_ids:
            days_enjoyed += holiday_book.business_units
        
        leave_lines = self.env["hr.leave.line"].search([
            ("leave_id.employee_id", "=", contract.employee_id.id),
            ("leave_id.state", "=", "validate"),
            ("leave_id.holiday_status_id.unpaid_absences", "=", True),
            ("date", ">=", date_from or contract.date_start),
            ("date", "<=", date_ref),
        ])
        
        days_suspension = sum(line.days_payslip for line in leave_lines)
        worked_days_adjusted = worked_days - days_suspension
        days_left = (worked_days_adjusted * 15 / 360) - days_enjoyed
        
        return {
            'worked_days': round_1_decimal(worked_days),
            'worked_days_adjusted': round_1_decimal(worked_days_adjusted),
            'days_left': round_1_decimal(days_left),
            'days_enjoyed': round_1_decimal(days_enjoyed),
            'days_paid': round_1_decimal(days_paid),
            'days_suspension': round_1_decimal(days_suspension),
        }



    def _get_period_ids_from_localdict(self, localdict, period_name):
        """
        Extrae IDs únicos de un período específico del localdict
        """
        period_data = localdict.get(period_name)
        if not period_data:
            return []
        
        if isinstance(period_data, (list, tuple)):
            return list(period_data)
        elif isinstance(period_data, dict):
            if 'ids' in period_data:
                return period_data['ids']
            elif 'id' in period_data:
                return [period_data['id']]
        elif isinstance(period_data, (int, str)):
            return [period_data]
        return []

    def _determine_periods(self,
        localdict,
        incluir_current: bool,
        incluir_before: bool,
        incluir_prima: bool,
        incluir_cesantias: bool,
        ):
        all_payslip_ids = set()
        
        if incluir_current:
            ids = self._get_period_ids_from_localdict(localdict, "current_month")
            all_payslip_ids.update(ids)
            
        if incluir_before:
            ids = self._get_period_ids_from_localdict(localdict, "before_month")
            all_payslip_ids.update(ids)
            
        if incluir_prima:
            ids = self._get_period_ids_from_localdict(localdict, "prima_month")
            all_payslip_ids.update(ids)
            
        if incluir_cesantias:
            ids = self._get_period_ids_from_localdict(localdict, "cesantias_month")
            all_payslip_ids.update(ids)
            
        return list(all_payslip_ids)

    def _get_totalizar_reglas(
        self,
        liquidacion_data,
        codigos_regla=None,
        filtros=None,
        *,
        incluir_current=False,
        incluir_before=False,
        incluir_prima=False,
        incluir_cesantias=False,
        incluir_multi=True,
        devolver_cantidad=False,
    ):
        filtros = filtros or {}
        
        payslip_ids = self._determine_periods(
            liquidacion_data,
            incluir_current,
            incluir_before,
            incluir_prima,
            incluir_cesantias,
        )
        
        entries = []
        
        if payslip_ids:
            domain = [
                ("slip_id", "in", payslip_ids),
                ("contract_id", "=", liquidacion_data["contract"].id),
            ]
            
            if codigos_regla is not None:
                if isinstance(codigos_regla, str):
                    codigos = [codigos_regla]
                else:
                    codigos = list(codigos_regla)
                domain.append(("salary_rule_id.code", "in", codigos))
            
            payslip_lines = self.env["hr.payslip.line"].search(domain)
            
            lines_by_code = {}
            for line in payslip_lines:
                code = line.salary_rule_id.code
                if code not in lines_by_code:
                    lines_by_code[code] = {
                        'rule': line.salary_rule_id,
                        'total': 0.0,
                        'quantity': 0.0,
                        'lines': []
                    }
                lines_by_code[code]['total'] += line.total
                lines_by_code[code]['quantity'] += line.quantity
                lines_by_code[code]['lines'].append(line)
            
            # Convertir a formato entries
            for code, data in lines_by_code.items():
                entries.append({
                    "object": data['rule'],
                    "total": data['total'],
                    "entries": data['lines'],
                    "quantity": data['quantity']
                })
        
        if incluir_multi:
            rules_multi = liquidacion_data.get("rules_multi", {})
            
            if codigos_regla is not None:
                if isinstance(codigos_regla, str):
                    codigos = [codigos_regla]
                else:
                    codigos = list(codigos_regla)
                
                for code in codigos:
                    if code in rules_multi:
                        multi_info = rules_multi.get(code, {}).get("current")
                        if multi_info and multi_info.get("object"):
                            entries.append({
                                "object": multi_info["object"],
                                "total": multi_info.get("total", 0.0),
                                "quantity": multi_info.get("quantity", 0),
                            })
            else:
                for code, multi_dict in rules_multi.items():
                    multi_info = multi_dict.get("current")
                    if multi_info and multi_info.get("object"):
                        entries.append({
                            "object": multi_info["object"],
                            "total": multi_info.get("total", 0.0),
                            "quantity": multi_info.get("quantity", 0),
                        })
        
        def _passes_filter(obj):
            cond = filtros.get("object")
            return cond(obj) if cond else True
        
        total_value = 0.0
        total_entries = 0
        
        for item in entries:
            obj = item.get("object")
            if not obj or not _passes_filter(obj):
                continue
                
            if devolver_cantidad:
                if "entries" in item:
                    total_entries += sum(line.quantity for line in item["entries"])
                else:
                    total_entries += item.get("quantity", 0)
            else:
                total_value += item.get("total", 0.0)

        return float(total_entries) if devolver_cantidad else total_value

    def _get_totalizar_categorias(
        self,
        localdict,
        categorias=None,
        categorias_excluir=None,
        filtros=None,
        *,
        incluir_current=True,
        incluir_before=False,
        incluir_prima=False,
        incluir_cesantias=False,
        incluir_multi=True,
        incluir_subcategorias=True,
    ):

        filtros = filtros or {}

        def _to_list(x):
            if x is None:
                return None
            if isinstance(x, str):
                return [x]
            elif not isinstance(x, list):
                return list(x)
            else:
                return x

        categorias = _to_list(categorias)
        categorias_excluir = _to_list(categorias_excluir)

        def _passes_rule_filters(obj):
            for clave, cond in filtros.items():
                if clave == "object":
                    if not cond(obj):
                        return False
                else:
                    if hasattr(obj, clave):
                        val = getattr(obj, clave)
                    else:
                        val = None
                    if callable(cond):
                        if not cond(val):
                            return False
                    else:
                        if bool(val) != bool(cond):
                            return False
            return True

        payslip_ids = self._determine_periods(
            localdict,
            incluir_current,
            incluir_before,
            incluir_prima,
            incluir_cesantias,
        )

        fuente = []
        
        if payslip_ids:
            payslip_lines = self.env["hr.payslip.line"].search([
                ("slip_id", "in", payslip_ids),
                 ("slip_id", "!=", localdict["slip"].id),
                ("contract_id", "=", localdict["contract"].id),
            ])
            
            # Agrupar por código de regla
            lines_by_code = {}
            for line in payslip_lines:
                code = line.salary_rule_id.code
                if code not in lines_by_code:
                    lines_by_code[code] = {
                        'rule': line.salary_rule_id,
                        'total': 0.0,
                        'quantity': 0.0,
                        'lines': []
                    }
                lines_by_code[code]['total'] += line.total
                lines_by_code[code]['quantity'] += line.quantity
                lines_by_code[code]['lines'].append(line)
            
            for code, data in lines_by_code.items():
                fuente.append({
                    "code": code,
                    "object": data['rule'],
                    "total": data['total'],
                    "entries": data['lines'],
                    "quantity": data['quantity']
                })
        
        if incluir_multi:
            rules_multi = localdict.get("rules_multi", {})
            for code, multi_dict in rules_multi.items():
                info = multi_dict.get("current")
                if info and info.get("object"):
                    fuente.append({
                        "code": code,
                        "object": info["object"],
                        "total": info.get("total", 0.0),
                        "quantity": info.get("quantity", 0),
                    })

        reglas_por_cat = {}
        padres = {}
        
        for item in fuente:
            obj = item["object"]
            category = None
            if obj and hasattr(obj, "category_id"):
                category = obj.category_id
            if not category:
                continue
                
            cat_code = category.code
            reglas_por_cat.setdefault(cat_code, set()).add(item["code"])
            
            parent = None
            if hasattr(category, "parent_id"):
                parent = category.parent_id
            if parent:
                padres.setdefault(cat_code, parent.code)

        children = {}
        for child, parent in padres.items():
            children.setdefault(parent, set()).add(child)

        if categorias is None:
            cats = set(reglas_por_cat)
        else:
            cats = set(categorias)
            if incluir_subcategorias:
                queue = list(cats)
                while queue:
                    c = queue.pop()
                    for h in children.get(c, ()):
                        if h not in cats:
                            cats.add(h)
                            queue.append(h)

        if categorias_excluir:
            exclude = set(categorias_excluir)
            if incluir_subcategorias:
                queue = list(exclude)
                while queue:
                    c = queue.pop()
                    for h in children.get(c, ()):
                        if h not in exclude:
                            exclude.add(h)
                            queue.append(h)
            cats -= exclude

        total_valor = 0.0
        total_entradas = 0.0
        
        for item in fuente:
            obj = item["object"]
            category = None
            if obj and hasattr(obj, "category_id"):
                category = obj.category_id
            cat_code = category.code if category else None
            
            if cat_code not in cats or not _passes_rule_filters(obj):
                continue
                
            total_valor += item.get("total", 0.0)
            
            if "entries" in item:
                total_entradas += len(item["entries"])
            else:
                total_entradas += item.get("quantity", 0)

        return total_valor, total_entradas
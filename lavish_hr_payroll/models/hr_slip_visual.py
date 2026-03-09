# -*- coding: utf-8 -*-
from odoo import models, fields, api, _, SUPERUSER_ID , tools
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_is_zero, float_round, date_utils
from collections import defaultdict
from datetime import datetime, timedelta, date, time
from odoo.tools.misc import format_date
import calendar
from collections import defaultdict, Counter
from dateutil.relativedelta import relativedelta
import ast
from odoo import api, Command, fields, models, _
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
from decimal import Decimal
import math
#from math import round
_logger = logging.getLogger(__name__)
import re
from psycopg2 import sql
def json_serial(obj):
    """Función auxiliar extendida para serializar varios tipos de objetos."""
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    elif isinstance(obj, Decimal):
        return float(obj)
    elif hasattr(obj, '__dict__'):
        return obj.__dict__
    raise TypeError(f"Type {type(obj)} not serializable")

class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    resulados_op = fields.Html('Resultados')
    resulados_rt = fields.Html('Resultados RT')
    payslip_detail = fields.Html(compute='_compute_payslip_detail')
    prestaciones_sociales_report = fields.Html(string="Reporte de Prestaciones Sociales", compute='_compute_prestaciones_sociales_report')
    
    @api.depends('line_ids', 'leave_ids', 'worked_days_line_ids')
    def _compute_payslip_detail(self):
        for payslip in self:
            payslip.payslip_detail = 'Calculated'



    @api.depends('line_ids.computation')
    def _compute_prestaciones_sociales_report(self):
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

    def generate_ibd_html_report(self, data: dict) -> str:
        """
        Genera el informe HTML completo de IBC usando Bootstrap para un mejor estilo.
        
        Args:
            data: Diccionario con los datos del contexto y resultados del cálculo IBC
                
        Returns:
            str: HTML formateado del reporte completo
        """
        # Verificar que existan datos
        ctx = data.get("ctx")
        if not ctx:
            return '<div class="alert alert-warning">No hay datos disponibles para generar el informe IBC</div>'
        
        # Extraer datos necesarios
        dias = ctx.dias
        actual = ctx.actual
        previo = ctx.previo
        params = ctx.params
        payslip = ctx.payslip
        
        # Realizar cálculos necesarios
        total_ibc = ctx.ibc_final
        sal_total = actual.salarial
        nsal_total = actual.no_salarial
        ibc_anterior = previo.salarial + previo.no_salarial
        ibc_mes_actual = ctx.ibc_final_mes if hasattr(ctx, 'ibc_final_mes') else ctx.ibc_final
        
        # Cálculo de porcentajes
        total_devengado = sal_total + nsal_total
        if total_devengado:
            porc_sal = round((sal_total * 100 / total_devengado), 1)
            porc_nsal = round((nsal_total * 100 / total_devengado), 1)
        else:
            porc_sal = 100
            porc_nsal = 0
        
        # Relación con SMMLV
        smmlv_mensual = params.get('SMMLV_DAILY', 0) * 30
        relacion_smmlv = total_ibc / smmlv_mensual if smmlv_mensual else 0
        
        # Distribución temporal
        total_ambos = total_ibc + ibc_anterior
        if total_ambos:
            porc_actual = round((total_ibc * 100 / total_ambos), 1)
            porc_anterior = round((ibc_anterior * 100 / total_ambos), 1)
        else:
            porc_actual = 100
            porc_anterior = 0
        
        # Calcular días de IBC anterior
        dias_anterior = ctx.dias_previo if hasattr(ctx, 'dias_previo') else 0
        
        # Calcular valores para topes
        tope_smmlv = smmlv_mensual * 25
        tope_estado = "No excede" if total_ibc <= tope_smmlv else "Excede"
        
        excedente_40 = 0
        if nsal_total > (total_devengado * 0.4):
            excedente_40 = nsal_total - (total_devengado * 0.4)
        
        tope_40_estado = "No excede" if excedente_40 <= 0 else "Excede"
        
        # Obtener el tipo de contrato
        es_integral = ctx.contract.modality_salary == 'integral'
        factor_contrato = '70%' if es_integral else '100%'
        
        # Funciones auxiliares de formateo
        def fmt_cur(value):
            """Formatea un valor como moneda"""
            try:
                return f"${value:,.2f}" if value else "$0.00"
            except:
                return "$0.00"
        
        def fmt_date(date):
            """Formatea una fecha en formato dd/mm/yyyy"""
            if not date:
                return "—"
            try:
                if hasattr(date, 'strftime'):
                    return date.strftime('%d/%m/%Y')
                return str(date)
            except:
                return "—"
        
        def fmt_value(value):
            """Formatea un valor para mostrarlo en el reporte"""
            if isinstance(value, (int, float)):
                try:
                    if value > 100:  # Probablemente es un valor monetario
                        return fmt_cur(value)
                    else:
                        return f"{value:,.2f}".rstrip('0').rstrip('.') if '.' in f"{value:,.2f}" else f"{value:,}"
                except:
                    return str(value)
            elif isinstance(value, list):
                if len(value) > 3:
                    return f"{len(value)} elementos"
                elif len(value) > 0:
                    return ", ".join(str(v) for v in value)
                else:
                    return "[]"
            elif isinstance(value, dict):
                return f"{len(value)} elementos"
            elif isinstance(value, bool):
                return "Sí" if value else "No"
            else:
                return str(value)
        
        def fmt_fecha(info):
            """Formatea la fecha o fechas de un registro"""
            if not info:
                return ""
                
            if 'fecha' in info:
                return fmt_date(info['fecha'])
            elif 'fechas' in info:
                fechas_html = []
                for f in info.get('fechas', []):
                    from_date = f.get('from', '')
                    to_date = f.get('to', '')
                    fechas_html.append(f"{fmt_date(from_date)} - {fmt_date(to_date)}")
                return "<br>".join(fechas_html)
            return ""
        
        def tipo_badge(tipo):
            """Genera un badge para el tipo de ingreso"""
            if tipo == 'salarial':
                return '<span class="badge bg-success">Salarial</span>'
            else:
                return '<span class="badge bg-secondary">No Salarial</span>'
        
        def estado_badge(estado, positivo=True):
            """Genera un badge para estados"""
            if estado == "No excede" and positivo:
                return f'<span class="badge bg-success">{estado}</span>'
            elif estado == "Excede" and not positivo:
                return f'<span class="badge bg-danger">{estado}</span>'
            return f'<span class="badge bg-secondary">{estado}</span>'
        
        def tipo_nomina_badge(tipo):
            """Genera un badge para el tipo de nómina"""
            tipo_map = {
                'Regular': 'bg-success',
                'Liquidación': 'bg-danger',
                'Vacaciones Disfrutadas': 'bg-warning',
                'Vacaciones en Dinero': 'bg-info',
                'Incapacidad': 'bg-primary'
            }
            bg_class = tipo_map.get(tipo, 'bg-secondary')
            return f'<span class="badge {bg_class}">{tipo}</span>'
        
        def estado_nomina_badge(estado):
            """Genera un badge para el estado de la nómina"""
            estado_map = {
                'done': {'class': 'bg-success', 'text': 'Completada'},
                'paid': {'class': 'bg-info', 'text': 'Pagada'},
                'verify': {'class': 'bg-warning', 'text': 'Por Verificar'},
                'draft': {'class': 'bg-secondary', 'text': 'Borrador'}
            }
            style = estado_map.get(estado, {'class': 'bg-secondary', 'text': estado})
            return f'<span class="badge {style["class"]}">{style["text"]}</span>'
        
        def category_badge(category, parent_category=None):
            """Genera un badge para categorías"""
            if not category:
                return '<span class="text-muted">-</span>'
                
            badge = category
            if parent_category:
                badge += f' <small class="text-muted">({parent_category})</small>'
            
            return f'<span class="badge bg-light text-dark">{badge}</span>'
        
        # Función para generar la tabla de reglas
        def generate_rules_html():
            """Genera la tabla de reglas de cálculo detalladas"""
            # Verificar si existe el atributo reglas_detalle
            if not hasattr(ctx, 'reglas_detalle'):
                return '<div class="alert alert-info">No hay información detallada de reglas disponible.</div>'
                
            reglas_incluidas = [r for r in ctx.reglas_detalle if r.get('incluida', False) and r.get('valor_usado', 0) > 0]
            
            # Si no hay reglas incluidas, mostrar mensaje informativo
            if not reglas_incluidas:
                return '<div class="alert alert-info">No se encontraron reglas de cálculo que afecten el IBC.</div>'
            
            # Separar por tipo y paso
            reglas_sal_1b = [r for r in reglas_incluidas if r.get('tipo') == 'DEV_SALARIAL' and r.get('paso') == '1.B']
            reglas_sal_1c = [r for r in reglas_incluidas if r.get('tipo') == 'DEV_SALARIAL' and r.get('paso') == '1.C']
            reglas_nosal_1b = [r for r in reglas_incluidas if r.get('tipo') == 'DEV_NO_SALARIAL' and r.get('paso') == '1.B']
            reglas_nosal_1c = [r for r in reglas_incluidas if r.get('tipo') == 'DEV_NO_SALARIAL' and r.get('paso') == '1.C']
            reglas_ausencias = [r for r in reglas_incluidas if r.get('es_ausencia', False)]
            
            html_rules = ""
            
            # Sección de Ingresos Salariales
            if reglas_sal_1b or reglas_sal_1c:
                total_sal = sum(r.get('valor_usado', 0) for r in reglas_sal_1b + reglas_sal_1c)
                html_rules += f'''
                <div class="accordion-item">
                    <h2 class="accordion-header">
                        <button class="accordion-button" type="button" data-bs-toggle="collapse" data-bs-target="#collapseSalarial">
                            Ingresos Salariales - {fmt_cur(total_sal)}
                        </button>
                    </h2>
                    <div id="collapseSalarial" class="accordion-collapse collapse show">
                        <div class="accordion-body">
                            <div class="row">
                '''
                
                # Columna 1: Reglas del paso 1.B
                html_rules += '<div class="col-md-6">'
                if reglas_sal_1b:
                    total_sal_1b = sum(r.get('valor_usado', 0) for r in reglas_sal_1b)
                    html_rules += f'''
                    <div class="card mb-3">
                        <div class="card-header bg-light">
                            Periodo Anterior (Paso 1.B) - {fmt_cur(total_sal_1b)}
                        </div>
                        <div class="card-body p-0">
                            <div class="table-responsive">
                                <table class="table table-sm table-bordered mb-0">
                                    <thead class="table-light">
                                        <tr>
                                            <th>Código</th>
                                            <th>Concepto</th>
                                            <th class="text-end">Valor</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                    '''
                    for r in reglas_sal_1b:
                        html_rules += f'''
                                    <tr>
                                        <td><code>{r.get('codigo', '-')}</code></td>
                                        <td>{r.get('nombre', 'Sin nombre')}</td>
                                        <td class="text-end">{fmt_cur(r.get('valor_usado', 0))}</td>
                                    </tr>
                        '''
                    html_rules += '''
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                    '''
                html_rules += '</div>'
                
                # Columna 2: Reglas del paso 1.C
                html_rules += '<div class="col-md-6">'
                if reglas_sal_1c:
                    total_sal_1c = sum(r.get('valor_usado', 0) for r in reglas_sal_1c)
                    html_rules += f'''
                    <div class="card mb-3">
                        <div class="card-header bg-light">
                            Periodo Actual (Paso 1.C) - {fmt_cur(total_sal_1c)}
                        </div>
                        <div class="card-body p-0">
                            <div class="table-responsive">
                                <table class="table table-sm table-bordered mb-0">
                                    <thead class="table-light">
                                        <tr>
                                            <th>Código</th>
                                            <th>Concepto</th>
                                            <th class="text-end">Valor</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                    '''
                    for r in reglas_sal_1c:
                        html_rules += f'''
                                    <tr>
                                        <td><code>{r.get('codigo', '-')}</code></td>
                                        <td>{r.get('nombre', 'Sin nombre')}</td>
                                        <td class="text-end">{fmt_cur(r.get('valor_usado', 0))}</td>
                                    </tr>
                        '''
                    html_rules += '''
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                    '''
                html_rules += '</div></div></div></div></div>'
            
            # Sección de Ingresos No Salariales
            if reglas_nosal_1b or reglas_nosal_1c:
                total_nosal = sum(r.get('valor_usado', 0) for r in reglas_nosal_1b + reglas_nosal_1c)
                html_rules += f'''
                <div class="accordion-item">
                    <h2 class="accordion-header">
                        <button class="accordion-button" type="button" data-bs-toggle="collapse" data-bs-target="#collapseNoSalarial">
                            Ingresos No Salariales - {fmt_cur(total_nosal)}
                        </button>
                    </h2>
                    <div id="collapseNoSalarial" class="accordion-collapse collapse show">
                        <div class="accordion-body">
                            <div class="row">
                '''
                
                # Columna 1: Reglas del paso 1.B
                html_rules += '<div class="col-md-6">'
                if reglas_nosal_1b:
                    total_nosal_1b = sum(r.get('valor_usado', 0) for r in reglas_nosal_1b)
                    html_rules += f'''
                    <div class="card mb-3">
                        <div class="card-header bg-light">
                            Periodo Anterior (Paso 1.B) - {fmt_cur(total_nosal_1b)}
                        </div>
                        <div class="card-body p-0">
                            <div class="table-responsive">
                                <table class="table table-sm table-bordered mb-0">
                                    <thead class="table-light">
                                        <tr>
                                            <th>Código</th>
                                            <th>Concepto</th>
                                            <th class="text-end">Valor</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                    '''
                    for r in reglas_nosal_1b:
                        html_rules += f'''
                                    <tr>
                                        <td><code>{r.get('codigo', '-')}</code></td>
                                        <td>{r.get('nombre', 'Sin nombre')}</td>
                                        <td class="text-end">{fmt_cur(r.get('valor_usado', 0))}</td>
                                    </tr>
                        '''
                    html_rules += '''
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                    '''
                html_rules += '</div>'
                
                # Columna 2: Reglas del paso 1.C
                html_rules += '<div class="col-md-6">'
                if reglas_nosal_1c:
                    total_nosal_1c = sum(r.get('valor_usado', 0) for r in reglas_nosal_1c)
                    html_rules += f'''
                    <div class="card mb-3">
                        <div class="card-header bg-light">
                            Periodo Actual (Paso 1.C) - {fmt_cur(total_nosal_1c)}
                        </div>
                        <div class="card-body p-0">
                            <div class="table-responsive">
                                <table class="table table-sm table-bordered mb-0">
                                    <thead class="table-light">
                                        <tr>
                                            <th>Código</th>
                                            <th>Concepto</th>
                                            <th class="text-end">Valor</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                    '''
                    for r in reglas_nosal_1c:
                        html_rules += f'''
                                    <tr>
                                        <td><code>{r.get('codigo', '-')}</code></td>
                                        <td>{r.get('nombre', 'Sin nombre')}</td>
                                        <td class="text-end">{fmt_cur(r.get('valor_usado', 0))}</td>
                                    </tr>
                        '''
                    html_rules += '''
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                    '''
                html_rules += '</div></div></div></div></div>'
            
            # Tabla de Ausencias
            if reglas_ausencias:
                total_aus = sum(r.get('valor_usado', 0) for r in reglas_ausencias)
                html_rules += f'''
                <div class="accordion-item">
                    <h2 class="accordion-header">
                        <button class="accordion-button" type="button" data-bs-toggle="collapse" data-bs-target="#collapseAusencias">
                            Ausencias y Licencias - {fmt_cur(total_aus)}
                        </button>
                    </h2>
                    <div id="collapseAusencias" class="accordion-collapse collapse show">
                        <div class="accordion-body">
                            <div class="table-responsive">
                                <table class="table table-sm table-bordered">
                                    <thead class="table-light">
                                        <tr>
                                            <th>Concepto</th>
                                            <th class="text-end">Valor Original</th>
                                            <th class="text-end">Valor Ajustado</th>
                                            <th class="text-center">Factor</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                '''
                for r in reglas_ausencias:
                    # Manejo seguro de divisiones por cero
                    total = r.get('total', 0) or 0
                    valor_usado = r.get('valor_usado', 0) or 0
                    factor = valor_usado / total if total else 0
                    html_rules += f'''
                                    <tr>
                                        <td>{r.get('nombre', 'Sin nombre')}</td>
                                        <td class="text-end">{fmt_cur(total)}</td>
                                        <td class="text-end">{fmt_cur(valor_usado)}</td>
                                        <td class="text-center">{factor:.2f}</td>
                                    </tr>
                    '''
                html_rules += '''
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                </div>
                '''
                
            return html_rules
        
        # Generar tablas adicionales
        def generate_income_table():
            """Genera la tabla de ingresos detallada"""
            # Verificar si hay datos de ingresos
            if 'ingresos' not in data or not data.get('ingresos'):
                return ""
                
            ingresos = data['ingresos']
            
            # Verificar si existe el detalle de ingresos
            if 'detalle' not in ingresos or not ingresos.get('detalle'):
                return ""
                
            html = '''
            <div class="card mt-4 mb-4">
                <div class="card-header bg-success text-white">
                    <h5 class="card-title mb-0">Detalle de Ingresos del Periodo</h5>
                    <p class="card-subtitle text-white-50 mb-0">Desglose por conceptos y categorías</p>
                </div>
                <div class="card-body p-0">
                    <div class="table-responsive">
                        <table class="table table-bordered table-striped table-hover mb-0">
                            <thead>
                                <tr>
                                    <th>Concepto</th>
                                    <th class="text-end">Valor</th>
                                    <th>Fecha</th>
                                    <th>Categoría</th>
                                    <th>Tipo</th>
                                </tr>
                            </thead>
                            <tbody>
            '''

            # Procesar ingresos salariales y no salariales
            ingresos_detalle = ingresos.get('detalle', {})
            ingresos_salariales = [(code, info) for code, info in ingresos_detalle.items() 
                                if info.get('tipo') == 'salarial']
            ingresos_no_salariales = [(code, info) for code, info in ingresos_detalle.items() 
                                    if info.get('tipo') != 'salarial']

            # Sección Ingresos Salariales
            html += '''
                                <tr class="table-light">
                                    <th colspan="5">Ingresos Salariales</th>
                                </tr>
            '''
            for code, info in ingresos_salariales:
                html += f'''
                                <tr>
                                    <td>{info.get('name', 'Sin nombre')}</td>
                                    <td class="text-end">{fmt_cur(info.get('valor', 0))}</td>
                                    <td>{fmt_fecha(info)}</td>
                                    <td>{category_badge(info.get('categoria'), info.get('categoria_padre'))}</td>
                                    <td>{tipo_badge(info.get('tipo', 'salarial'))}</td>
                                </tr>
                '''

            # Sección Ingresos No Salariales
            if ingresos_no_salariales:
                html += '''
                                <tr class="table-light">
                                    <th colspan="5">Ingresos No Salariales</th>
                                </tr>
                '''
                for code, info in ingresos_no_salariales:
                    html += f'''
                                <tr>
                                    <td>{info.get('name', 'Sin nombre')}</td>
                                    <td class="text-end">{fmt_cur(info.get('valor', 0))}</td>
                                    <td>{fmt_fecha(info)}</td>
                                    <td>{category_badge(info.get('categoria'), info.get('categoria_padre'))}</td>
                                    <td>{tipo_badge(info.get('tipo', 'no_salarial'))}</td>
                                </tr>
                    '''

            # Totales
            salariales = ingresos.get('salariales', {})
            no_salariales = ingresos.get('no_salariales', {})
            
            html += f'''
                                <tr class="table-success">
                                    <th>Total Ingresos Salariales</th>
                                    <th class="text-end">{fmt_cur(salariales.get('total', 0))}</th>
                                    <td colspan="3"></td>
                                </tr>
                                <tr class="table-light">
                                    <th>Total Ingresos No Salariales</th>
                                    <th class="text-end">{fmt_cur(no_salariales.get('total', 0))}</th>
                                    <td colspan="3"></td>
                                </tr>
            '''

            html += '''
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
            '''
            return html
        
        def generate_previous_payslips_table():
            """Genera la tabla de nóminas anteriores"""
            # Verificar si hay nóminas anteriores
            nominas_anteriores = data.get('nominas_anteriores', [])
            if not nominas_anteriores:
                return ""
                
            html = '''
            <div class="card mt-4 mb-4">
                <div class="card-header bg-info text-white">
                    <h5 class="card-title mb-0">Nóminas Anteriores del Periodo</h5>
                    <p class="card-subtitle text-white-50 mb-0">Nóminas previas consideradas en el cálculo</p>
                </div>
                <div class="card-body p-0">
                    <div class="table-responsive">
                        <table class="table table-bordered table-striped table-hover mb-0">
                            <thead>
                                <tr>
                                    <th>Número</th>
                                    <th>Tipo</th>
                                    <th>Periodo</th>
                                    <th>Estado</th>
                                    <th class="text-end">Total Salarial</th>
                                    <th class="text-end">Total No Salarial</th>
                                </tr>
                            </thead>
                            <tbody>
            '''

            # Listar las nóminas anteriores
            for nomina in nominas_anteriores:
                html += f'''
                                <tr>
                                    <td>{nomina.get('number', '-')}</td>
                                    <td>{tipo_nomina_badge(nomina.get('tipo', 'Regular'))}</td>
                                    <td>{nomina.get('period', '')}</td>
                                    <td>{estado_nomina_badge(nomina.get('state', 'draft'))}</td>
                                    <td class="text-end">{fmt_cur(nomina.get('total_salarial', 0))}</td>
                                    <td class="text-end">{fmt_cur(nomina.get('total_no_salarial', 0))}</td>
                                </tr>
                '''

            html += '''
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
            '''
            return html
        
        def generate_absences_table():
            """Genera la tabla de ausencias"""
            # Verificar si hay ausencias
            ausencias_detalle = data.get('ausencias_detalle', [])
            if not ausencias_detalle:
                return ""
                
            html = '''
            <div class="card mt-4 mb-4">
                <div class="card-header bg-warning text-dark">
                    <h5 class="card-title mb-0">Ausencias del Periodo</h5>
                    <p class="card-subtitle text-muted mb-0">Detalle de ausencias agrupadas por tipo</p>
                </div>
                <div class="card-body p-0">
                    <div class="table-responsive">
                        <table class="table table-bordered table-striped table-hover mb-0">
                            <thead>
                                <tr>
                                    <th>Tipo</th>
                                    <th>Código</th>
                                    <th class="text-center">Cantidad</th>
                                    <th class="text-center">Días</th>
                                    <th>Características</th>
                                </tr>
                            </thead>
                            <tbody>
            '''

            # Listar las ausencias
            for ausencia in ausencias_detalle:
                # Determinar características
                caracteristicas = []
                if ausencia.get('es_incapacidad'):
                    caracteristicas.append("Incapacidad")
                if ausencia.get('es_vacacion'):
                    caracteristicas.append("Vacación")
                if ausencia.get('es_vacacion_dinero'):
                    caracteristicas.append("Vacación en dinero")
                
                html += f'''
                                <tr>
                                    <td>{ausencia.get('tipo', '')}</td>
                                    <td>{ausencia.get('codigo', '')}</td>
                                    <td class="text-center">{ausencia.get('cantidad', 0)}</td>
                                    <td class="text-center">{ausencia.get('dias', 0)}</td>
                                    <td>{", ".join(caracteristicas) or "N/A"}</td>
                                </tr>
                '''

            # Totalizar días
            total_dias = sum(ausencia.get('dias', 0) for ausencia in ausencias_detalle)
            total_cantidad = sum(ausencia.get('cantidad', 0) for ausencia in ausencias_detalle)
            
            html += f'''
                                <tr class="table-warning">
                                    <th>Total</th>
                                    <td></td>
                                    <th class="text-center">{total_cantidad}</th>
                                    <th class="text-center">{total_dias}</th>
                                    <td></td>
                                </tr>
            '''

            html += '''
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
            '''
            return html
        
        def generate_calculation_process_section():
            """Genera la sección que muestra el proceso detallado de cálculo del IBC"""
            calculo_detallado = data.get('calculo_detallado', [])
            if not calculo_detallado:
                return ""
            
            html = '''
            <div class="card mt-4 mb-4">
                <div class="card-header bg-primary text-white">
                    <h5 class="card-title mb-0">Proceso de Cálculo IBC</h5>
                    <p class="card-subtitle text-white-50 mb-0">Detalle paso a paso del procedimiento aplicado</p>
                </div>
                <div class="card-body p-0">
            '''
            
            # Timeline del proceso de cálculo
            for idx, paso in enumerate(calculo_detallado):
                # Alternar colores para cada paso
                bg_class = "bg-light" if idx % 2 == 0 else ""
                border_class = "border-warning" if paso.get('descripcion', '').lower().find('vacaciones') >= 0 else "border-primary"
                
                html += f'''
                    <div class="p-3 {bg_class} border-start {border_class} border-3">
                        <div class="d-flex">
                            <div class="me-3">
                                <span class="badge rounded-pill bg-primary">{paso.get('paso', idx+1)}</span>
                            </div>
                            <div class="flex-grow-1">
                                <h5 class="mb-1">{paso.get('descripcion', 'Paso de cálculo')}</h5>
                                <p class="text-muted mb-2">{paso.get('detalle', '')}</p>
                '''
                
                # Datos del paso
                datos = paso.get('datos', {})
                if datos:
                    html += '<div class="mt-2 small">'
                    
                    # Si hay fórmula, mostrarla de manera destacada
                    if 'formula' in datos:
                        html += f'''
                            <div class="bg-light p-2 rounded mb-2 font-monospace fw-bold">
                                {datos['formula']}
                            </div>
                        '''
                    
                    # Crear una mini tabla con los datos
                    html += '<table class="table table-sm table-borderless mb-0">'
                    
                    # Filtrar campos especiales
                    excluded_keys = ['formula', 'reglas_detalle']
                    
                    for key, value in [(k, v) for k, v in datos.items() if k not in excluded_keys]:
                        html += f'''
                            <tr>
                                <td class="text-muted" style="width: 40%;">{key.replace('_', ' ').title()}:</td>
                                <td class="fw-bold">{fmt_value(value)}</td>
                            </tr>
                        '''
                    
                    html += '</table></div>'
                
                html += '''
                            </div>
                        </div>
                    </div>
                '''
            
            html += '''
                </div>
            </div>
            '''
            
            return html
        
        def generate_previous_month_rules_table():
            """Genera una tabla con las reglas del mes anterior para vacaciones disfrutadas"""
            # Verificar si hay datos de ajuste de vacaciones y si se usó base de liquidación
            if not data.get('ajuste_vacaciones', {}).get('usar_base_liquidacion', False):
                return ""  # No mostrar esta sección si no aplica
            
            html = '''
            <div class="card mt-4 mb-4">
                <div class="card-header bg-warning text-dark">
                    <h5 class="card-title mb-0">Reglas Base del Mes Anterior</h5>
                    <p class="card-subtitle text-muted mb-0">Reglas utilizadas como base para vacaciones disfrutadas</p>
                </div>
                <div class="card-body p-0">
                    <div class="table-responsive">
                        <table class="table table-bordered table-striped table-hover mb-0">
                            <thead>
                                <tr>
                                    <th>Código</th>
                                    <th>Nombre</th>
                                    <th>Periodo</th>
                                    <th>Tipo</th>
                                    <th class="text-end">Valor</th>
                                    <th>Categoría</th>
                                </tr>
                            </thead>
                            <tbody>
            '''

            # Si tenemos los datos de reglas del mes anterior en el diccionario
            base_rules = data.get('base_reglas_mes_anterior', [])
            
            if base_rules:
                # Primero mostramos las reglas salariales
                html += '''
                                <tr class="table-light">
                                    <th colspan="6">Reglas Salariales</th>
                                </tr>
                '''
                for rule in [r for r in base_rules if r.get('es_salarial', False)]:
                    html += f'''
                                <tr>
                                    <td>{rule.get('codigo', '')}</td>
                                    <td>{rule.get('nombre', '')}</td>
                                    <td>{rule.get('period', '')}</td>
                                    <td>{tipo_badge('salarial')}</td>
                                    <td class="text-end">{fmt_cur(rule.get('valor', 0))}</td>
                                    <td>{category_badge(rule.get('categoria'), rule.get('categoria_padre'))}</td>
                                </tr>
                    '''
                
                # Luego las reglas no salariales
                not_salary_rules = [r for r in base_rules if not r.get('es_salarial', False)]
                if not_salary_rules:
                    html += '''
                                <tr class="table-light">
                                    <th colspan="6">Reglas No Salariales</th>
                                </tr>
                    '''
                    for rule in not_salary_rules:
                        html += f'''
                                <tr>
                                    <td>{rule.get('codigo', '')}</td>
                                    <td>{rule.get('nombre', '')}</td>
                                    <td>{rule.get('period', '')}</td>
                                    <td>{tipo_badge('no_salarial')}</td>
                                    <td class="text-end">{fmt_cur(rule.get('valor', 0))}</td>
                                    <td>{category_badge(rule.get('categoria'), rule.get('categoria_padre'))}</td>
                                </tr>
                        '''
                
                # Totales
                total_salarial = sum(r.get('valor', 0) for r in base_rules if r.get('es_salarial', False))
                total_no_salarial = sum(r.get('valor', 0) for r in base_rules if not r.get('es_salarial', False))
                ibc_base = data.get('ajuste_vacaciones', {}).get('ibc_diario', 0) * 30
                
                html += f'''
                                <tr class="table-success">
                                    <th colspan="4">Total Reglas Salariales</th>
                                    <th class="text-end">{fmt_cur(total_salarial)}</th>
                                    <td></td>
                                </tr>
                                <tr class="table-light">
                                    <th colspan="4">Total Reglas No Salariales</th>
                                    <th class="text-end">{fmt_cur(total_no_salarial)}</th>
                                    <td></td>
                                </tr>
                                <tr class="table-warning">
                                    <th colspan="4">IBC Base Mensual</th>
                                    <th class="text-end">{fmt_cur(ibc_base)}</th>
                                    <td></td>
                                </tr>
                '''
            else:
                # Mensaje cuando no hay datos
                html += '''
                                <tr>
                                    <td colspan="6" class="text-center text-muted p-3">
                                        No se encontraron reglas del mes anterior que sirvieran como base para el cálculo.
                                    </td>
                                </tr>
                '''
            
            html += '''
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
            
            <div class="alert alert-warning">
                <i class="bi bi-info-circle me-2"></i>
                <strong>Nota:</strong> Para vacaciones disfrutadas con 'liquidar_con_base' activa, 
                se utiliza el IBC del mes anterior como base para calcular el valor diario aplicado a días de vacaciones.
            </div>
            '''
            
            return html
        
        # ------------------------------------------------
        # Comienzo del HTML principal
        # ------------------------------------------------
        
        # Incluir enlaces a Bootstrap CSS y JS (si es necesario)
        bootstrap_cdn = '''
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.8.1/font/bootstrap-icons.css">
        <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
        '''
        
        # Generar el HTML del reporte con Bootstrap
        html = f'''
        <div class="container-fluid p-3">
            <div class="row mb-4">
                <div class="col-12">
                    <h2 class="text-primary mb-2">Informe de Ingreso Base de Cotización (IBC)</h2>
                    <p class="text-muted mb-1">Cálculo detallado según normativa vigente</p>
                    <p class="text-muted mb-0">Periodo: {fmt_date(payslip.date_from)} - {fmt_date(payslip.date_to)}</p>
                </div>
            </div>
            
            <!-- Información Principal -->
            <div class="card mb-4">
                <div class="card-header bg-primary text-white">
                    <h5 class="card-title mb-0">Información Principal</h5>
                </div>
                <div class="card-body">
                    <div class="row">
                        <div class="col-md-4 mb-3">
                            <div class="card h-100">
                                <div class="card-header bg-light">
                                    <h6 class="card-title mb-0">Ingreso Base de Cotización</h6>
                                </div>
                                <div class="card-body">
                                    <h3 class="text-center text-primary mb-4">{fmt_cur(total_ibc)}</h3>
                                    <table class="table table-sm">
                                        <tr>
                                            <td>Días efectivos:</td>
                                            <td class="text-end">{dias.get('eff', 0)}</td>
                                        </tr>
                                        <tr>
                                            <td>Valor diario:</td>
                                            <td class="text-end">{fmt_cur(ctx.day_value)}</td>
                                        </tr>
                                        <tr>
                                            <td>IBC mes actual:</td>
                                            <td class="text-end">{fmt_cur(ibc_mes_actual)}</td>
                                        </tr>
                                    </table>
                                </div>
                            </div>
                        </div>
                        
                        <div class="col-md-4 mb-3">
                            <div class="card h-100">
                                <div class="card-header bg-light">
                                    <h6 class="card-title mb-0">IBC Anterior</h6>
                                </div>
                                <div class="card-body">
                                    <h3 class="text-center text-secondary mb-4">{fmt_cur(ibc_anterior)}</h3>
                                    <table class="table table-sm">
                                        <tr>
                                            <td>Días considerados:</td>
                                            <td class="text-end">{dias_anterior}</td>
                                        </tr>
                                    </table>
                                    <p class="text-muted small mb-0">Periodo anterior de referencia</p>
                                </div>
                            </div>
                        </div>
                        
                        <div class="col-md-4 mb-3">
                            <div class="card h-100">
                                <div class="card-header bg-light">
                                    <h6 class="card-title mb-0">Contrato</h6>
                                </div>
                                <div class="card-body">
                                    <h5 class="text-center mb-3">{'Integral' if es_integral else 'Ordinario'}</h5>
                                    <table class="table table-sm">
                                        <tr>
                                            <td>Factor aplicado:</td>
                                            <td class="text-end">{factor_contrato}</td>
                                        </tr>
                                        <tr>
                                            <td>Valor original:</td>
                                            <td class="text-end">{fmt_cur(ctx.ibc_pre)}</td>
                                        </tr>
                                        <tr>
                                            <td>Valor ajustado:</td>
                                            <td class="text-end">{fmt_cur(total_ibc)}</td>
                                        </tr>
                                    </table>
                                    <p class="text-muted small mb-0">{'Contrato con salario integral' if es_integral else 'Contrato con salario ordinario'}</p>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- Días del Periodo -->
            <div class="card mb-4">
                <div class="card-header bg-success text-white">
                    <h5 class="card-title mb-0">Días del Periodo</h5>
                </div>
                <div class="card-body">
                    <div class="row text-center">
                        <div class="col-md-4">
                            <div class="p-3 border rounded">
                                <span class="text-muted d-block mb-1">Trabajados</span>
                                <h3>{dias.get('trab', 0)}</h3>
                            </div>
                        </div>
                        <div class="col-md-4">
                            <div class="p-3 border rounded">
                                <span class="text-muted d-block mb-1">Remunerados</span>
                                <h3>{dias.get('rem', 0)}</h3>
                            </div>
                        </div>
                        <div class="col-md-4">
                            <div class="p-3 border rounded">
                                <span class="text-muted d-block mb-1">Efectivos</span>
                                <h3>{dias.get('eff', 0)}</h3>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- Resumen de Ingresos -->
            <div class="card mb-4">
                <div class="card-header bg-success text-white">
                    <h5 class="card-title mb-0">Resumen de Ingresos</h5>
                </div>
                <div class="card-body">
                    <div class="row">
                        <div class="col-md-4 mb-3">
                            <div class="card h-100">
                                <div class="card-header bg-light">
                                    <h6 class="card-title mb-0">Ingresos Salariales</h6>
                                </div>
                                <div class="card-body">
                                    <table class="table table-sm">
                                        <tr>
                                            <td>Actuales:</td>
                                            <td class="text-end">{fmt_cur(sal_total)}</td>
                                        </tr>
                                        <tr>
                                            <td>Previos:</td>
                                            <td class="text-end">{fmt_cur(0)}</td>
                                        </tr>
                                        <tr class="border-top">
                                            <th>Total:</th>
                                            <th class="text-end">{fmt_cur(sal_total)}</th>
                                        </tr>
                                    </table>
                                </div>
                            </div>
                        </div>
                        
                        <div class="col-md-4 mb-3">
                            <div class="card h-100">
                                <div class="card-header bg-light">
                                    <h6 class="card-title mb-0">Ingresos No Salariales</h6>
                                </div>
                                <div class="card-body">
                                    <table class="table table-sm">
                                        <tr>
                                            <td>Actuales:</td>
                                            <td class="text-end">{fmt_cur(nsal_total)}</td>
                                        </tr>
                                        <tr>
                                            <td>Previos:</td>
                                            <td class="text-end">{fmt_cur(0)}</td>
                                        </tr>
                                        <tr class="border-top">
                                            <th>Total:</th>
                                            <th class="text-end">{fmt_cur(nsal_total)}</th>
                                        </tr>
                                    </table>
                                </div>
                            </div>
                        </div>
                        
                        <div class="col-md-4 mb-3">
                            <div class="card h-100 bg-light">
                                <div class="card-header">
                                    <h6 class="card-title mb-0">Total Ingresos</h6>
                                </div>
                                <div class="card-body text-center">
                                    <h3 class="mb-2">{fmt_cur(total_devengado)}</h3>
                                    <p class="text-muted mb-0">Base para cálculo de topes</p>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- Topes Aplicados -->
            <div class="card mb-4">
                <div class="card-header bg-info text-white">
                    <h5 class="card-title mb-0">Topes Aplicados</h5>
                </div>
                <div class="card-body">
                    <div class="row">
                        <div class="col-md-6 mb-3">
                            <div class="card h-100">
                                <div class="card-header bg-light">
                                    <h6 class="card-title mb-0">Tope 25 SMMLV</h6>
                                </div>
                                <div class="card-body">
                                    <table class="table table-sm">
                                        <tr>
                                            <td>Valor máximo:</td>
                                            <td class="text-end">{fmt_cur(tope_smmlv)}</td>
                                        </tr>
                                        <tr>
                                            <td>Estado:</td>
                                            <td class="text-end">{estado_badge(tope_estado, True)}</td>
                                        </tr>
                                    </table>
                                    <p class="text-muted small mb-0">Límite legal máximo para IBC</p>
                                </div>
                            </div>
                        </div>
                        
                        <div class="col-md-6 mb-3">
                            <div class="card h-100">
                                <div class="card-header bg-light">
                                    <h6 class="card-title mb-0">Tope 40% No Salarial</h6>
                                </div>
                                <div class="card-body">
                                    <table class="table table-sm">
                                        <tr>
                                            <td>Excedente:</td>
                                            <td class="text-end">{fmt_cur(excedente_40)}</td>
                                        </tr>
                                        <tr>
                                            <td>Estado:</td>
                                            <td class="text-end">{estado_badge(tope_40_estado, True)}</td>
                                        </tr>
                                    </table>
                                    <p class="text-muted small mb-0">Límite pagos no constitutivos</p>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- Métricas del IBC -->
            <div class="card mb-4">
                <div class="card-header bg-info text-white">
                    <h5 class="card-title mb-0">Métricas del IBC</h5>
                </div>
                <div class="card-body">
                    <div class="row">
                        <div class="col-md-4 mb-3">
                            <div class="card h-100">
                                <div class="card-header bg-light">
                                    <h6 class="card-title mb-0 text-center">Composición</h6>
                                </div>
                                <div class="card-body">
                                    <div class="progress mb-3" style="height: 25px">
                                        <div class="progress-bar bg-success" style="width: {porc_sal}%" 
                                            data-bs-toggle="tooltip" title="Salarial: {porc_sal}%">
                                            Salarial: {porc_sal}%
                                        </div>
                                        <div class="progress-bar bg-warning" style="width: {porc_nsal}%" 
                                            data-bs-toggle="tooltip" title="No Salarial: {porc_nsal}%">
                                            No Salarial: {porc_nsal}%
                                        </div>
                                    </div>
                                    <div class="d-flex justify-content-between">
                                        <span>{fmt_cur(sal_total)}</span>
                                        <span>{fmt_cur(nsal_total)}</span>
                                    </div>
                                </div>
                            </div>
                        </div>
                        
                        <div class="col-md-4 mb-3">
                            <div class="card h-100">
                                <div class="card-header bg-light">
                                    <h6 class="card-title mb-0 text-center">Relación con SMMLV</h6>
                                </div>
                                <div class="card-body text-center">
                                    <h3 class="mb-2">{relacion_smmlv:.1f} SMMLV</h3>
                                    <p class="text-muted mb-0">SMMLV: {fmt_cur(smmlv_mensual)}</p>
                                </div>
                            </div>
                        </div>
                        
                        <div class="col-md-4 mb-3">
                            <div class="card h-100">
                                <div class="card-header bg-light">
                                    <h6 class="card-title mb-0 text-center">Distribución Temporal</h6>
                                </div>
                                <div class="card-body">
                                    <div class="progress mb-3" style="height: 25px">
                                        <div class="progress-bar bg-primary" style="width: {porc_actual}%" 
                                            data-bs-toggle="tooltip" title="Actual: {porc_actual}%">
                                            Actual: {porc_actual}%
                                        </div>
                                        <div class="progress-bar bg-secondary" style="width: {porc_anterior}%" 
                                            data-bs-toggle="tooltip" title="Previo: {porc_anterior}%">
                                            Previo: {porc_anterior}%
                                        </div>
                                    </div>
                                    <div class="d-flex justify-content-between">
                                        <span>{fmt_cur(total_ibc)}</span>
                                        <span>{fmt_cur(ibc_anterior)}</span>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- Detalle de Conceptos -->
            <div class="card mb-4">
                <div class="card-header bg-primary text-white">
                    <h5 class="card-title mb-0">Detalle de Conceptos</h5>
                </div>
                <div class="card-body p-0">
                    <div class="accordion" id="accordionConceptos">
                        {generate_rules_html()}
                    </div>
                </div>
            </div>
            
            <!-- Paso a paso del cálculo -->
            <div class="card mb-4">
                <div class="card-header bg-success text-white">
                    <h5 class="card-title mb-0">Paso a Paso del Cálculo</h5>
                </div>
                <div class="card-body p-0">
                    <div class="table-responsive">
                        <table class="table table-bordered table-hover mb-0">
                            <thead class="table-light">
                                <tr>
                                    <th style="width: 5%;" class="text-center">Paso</th>
                                    <th style="width: 65%;">Descripción</th>
                                    <th style="width: 30%;" class="text-end">Resultado</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr>
                                    <td class="text-center">1</td>
                                    <td>Cálculo del Total de Ingresos Base</td>
                                    <td class="text-end">{fmt_cur(total_devengado)}</td>
                                </tr>
                                <tr>
                                    <td class="text-center">2</td>
                                    <td>Aplicación de Porcentaje por Tipo de Contrato ({factor_contrato})</td>
                                    <td class="text-end">{fmt_cur(ctx.ibc_pre)}</td>
                                </tr>
                                <tr>
                                    <td class="text-center">3</td>
                                    <td>Verificación de Tope 25 SMMLV</td>
                                    <td class="text-end">{estado_badge(tope_estado, True)}</td>
                                </tr>
                                <tr>
                                    <td class="text-center">4</td>
                                    <td>Verificación de Tope 40% No Salarial</td>
                                    <td class="text-end">{estado_badge(tope_40_estado, True)}</td>
                                </tr>
                                <tr>
                                    <td class="text-center">5</td>
                                    <td>Ajuste Final por Días y Topes</td>
                                    <td class="text-end">{fmt_cur(total_ibc)}</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
            
            <!-- Base Legal -->
            <div class="card mb-4">
                <div class="card-header bg-secondary text-white">
                    <h5 class="card-title mb-0">Base Legal</h5>
                </div>
                <div class="card-body">
                    <div class="row">
                        <div class="col-md-4">
                            <div class="mb-3">
                                <h6>Artículo 127 del CST</h6>
                                <p class="text-muted">Constituye salario todo lo que recibe el trabajador como contraprestación directa del servicio.</p>
                            </div>
                        </div>
                        <div class="col-md-4">
                            <div class="mb-3">
                                <h6>Decreto 1295 de 1994</h6>
                                <p class="text-muted">El IBC para Riesgos Laborales es el mismo de los aportes al Sistema de Pensiones.</p>
                            </div>
                        </div>
                        <div class="col-md-4">
                            <div class="mb-3">
                                <h6>Ley 1393 de 2010</h6>
                                <p class="text-muted">Limita los pagos no constitutivos de salario al 40% del total de la remuneración.</p>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        '''
        
        # Tablas adicionales
        if 'ingresos' in data and data.get('ingresos', {}).get('detalle'):
            html += generate_income_table()
        
        if data.get('nominas_anteriores'):
            html += generate_previous_payslips_table()
        
        if data.get('ausencias_detalle'):
            html += generate_absences_table()
        
        if data.get('calculo_detallado'):
            html += generate_calculation_process_section()
        
        if data.get('ajuste_vacaciones', {}).get('usar_base_liquidacion'):
            html += generate_previous_month_rules_table()
        
        # Cerrar el contenedor
        html += '''
        </div>
        '''
        
        return html
    def _generate_formatted_prestaciones_report(self, line, prestaciones_data):
        """
        Genera un reporte HTML de prestaciones usando concatenación simple de strings
        para evitar errores de sintaxis.
        
        :param line: Línea de nómina
        :param prestaciones_data: Diccionario con datos de prestaciones
        :return: String HTML con el reporte formateado
        """
        meta_info = prestaciones_data.get('meta_info', {})
        tipo_prestacion = meta_info.get("tipo_prestacion", "N/A")
        code = line.salary_rule_id.code
        plain_days = meta_info.get("plain_days", 0)
        susp = meta_info.get("susp", 0)
        wage = meta_info.get("wage", 0)
        auxtransporte = meta_info.get("auxtransporte", 0)
        total_variable = meta_info.get("total_variable", 0)
        amount_base = meta_info.get("amount_base", 0)
        valor_pagar = meta_info.get("valor_prestacion", 0)
        fecha_inicio = meta_info.get("fecha_inicio", "N/A")
        fecha_fin = meta_info.get("fecha_fin", "N/A")
        formula_usada = meta_info.get("formula_usada", "")
        contract_modality = meta_info.get("contract_modality", "fijo")
        
        provisiones = prestaciones_data.get('provisiones', {})
        provision_anterior = provisiones.get('valor_anterior', 0)
        provision_actual = provisiones.get('valor_actual', 0)
        diferencia_provision = provisiones.get('diferencia', 0)
        
        reglas_salario = prestaciones_data.get('reglas_salario_promedio', {})
        novedades_promedio = prestaciones_data.get('novedades_promedio', {})
        novedades_entradas = novedades_promedio.get('entradas', [])
        
        es_cesantias = code in ("CESANTIAS", "PRV_CES", "CES_YEAR")
        es_intereses = code in ("INTCESANTIAS", "PRV_ICES", "INTCES_YEAR")
        es_vacaciones = code in ("VACATIONS_MONEY", "PRV_VAC", "VACCONTRATO")
        es_prima = code in ("prima", "PRV_PRIM", "primaextralegal")
        es_provision = code.startswith("PRV_")
        es_salario_variable = contract_modality == "variable"
        
        # Asegurar que la base de cesantías esté correctamente definida
        if 'base_cesantias' not in meta_info:
            meta_info['base_cesantias'] = wage + auxtransporte + total_variable

        if es_intereses:
            base_cesantias = meta_info.get('base_cesantias', amount_base)
            proporcion_anual = (plain_days / 360) if plain_days > 0 else 0
            if proporcion_anual > 0:
                factor = 12 * proporcion_anual / 100
                print(factor)
                valor_pagar = (base_cesantias/360) * plain_days * factor
        
        wage_fmt = "{:,.2f}".format(wage)
        auxtransporte_fmt = "{:,.2f}".format(auxtransporte)
        total_variable_fmt = "{:,.2f}".format(total_variable)
        amount_base_fmt = "{:,.2f}".format(amount_base)
        valor_pagar_fmt = "{:,.2f}".format(valor_pagar) 
        provision_anterior_fmt = "{:,.2f}".format(provision_anterior)
        provision_actual_fmt = "{:,.2f}".format(provision_actual)
        diferencia_fmt = "{:,.2f}".format(diferencia_provision)
        
        porcentaje_dias = (plain_days/360)*100 if plain_days <= 360 else 100
        
        if plain_days <= 30 and es_salario_variable:
            promedio_variable = total_variable
        else:
            promedio_variable = total_variable / plain_days * 30 if plain_days else 0
        
        promedio_variable_fmt = "{:,.2f}".format(promedio_variable)
        
        html = []
        
        html.append("""
        <div style="font-family: Arial, sans-serif; max-width: 1000px; margin: 0 auto; background-color: #f8f9fa; padding: 20px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
            <div style="background: linear-gradient(135deg, #1e88e5 0%, #0d47a1 100%); padding: 20px; color: white; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
                <h2 style="margin: 0; font-size: 22px; font-weight: 600;">{nombre_linea}</h2>
                <div style="display: flex; justify-content: space-between; margin-top: 15px;">
                    <div style="background: rgba(255,255,255,0.2); padding: 10px; border-radius: 6px;">
                        <div style="font-size: 11px; text-transform: uppercase; opacity: 0.8;">Tipo Prestación</div>
                        <div style="font-size: 14px; font-weight: 600;">{tipo_prestacion}</div>
                    </div>
                    <div style="background: rgba(255,255,255,0.2); padding: 10px; border-radius: 6px;">
                        <div style="font-size: 11px; text-transform: uppercase; opacity: 0.8;">Período</div>
                        <div style="font-size: 14px; font-weight: 600;">{fecha_inicio} a {fecha_fin}</div>
                    </div>
                    <div style="background: rgba(255,255,255,0.2); padding: 10px; border-radius: 6px;">
                        <div style="font-size: 11px; text-transform: uppercase; opacity: 0.8;">Código</div>
                        <div style="font-size: 14px; font-weight: 600;">{code}</div>
                    </div>
                </div>
            </div>
        """.format(
            nombre_linea=line.name,
            tipo_prestacion=tipo_prestacion,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            code=code
        ))
        
        html.append("""
            <div style="display: flex; gap: 20px; margin-bottom: 20px;">
                <!-- Días -->
                <div style="flex: 1; background-color: white; border-radius: 8px; padding: 15px; box-shadow: 0 2px 4px rgba(0,0,0,0.05);">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <div>
                            <div style="font-size: 12px; color: #666; margin-bottom: 5px;">Días a liquidar</div>
                            <div style="display: flex; align-items: center;">
                                <span style="font-size: 26px; font-weight: 700; color: #1e88e5;">{dias}</span>
                                <span style="font-size: 14px; color: #888; margin-left: 6px;">/ 360</span>
                            </div>
                        </div>
                        <div style="width: 50px; height: 50px; border-radius: 50%; display: flex; align-items: center; justify-content: center; background-color: #e3f2fd; margin-left: 10px;">
                            <span style="font-weight: 700; color: #1e88e5;">{porcentaje}%</span>
                        </div>
                    </div>
                    <!-- Barra de progreso -->
                    <div style="height: 8px; background-color: #e0e0e0; border-radius: 4px; margin: 10px 0; overflow: hidden;">
                        <div style="height: 100%; background: linear-gradient(90deg, #1e88e5, #64b5f6); width: {porcentaje_width}%;"></div>
                    </div>
                    <div style="font-size: 12px; color: #666;">Días no pagables: <span style="font-weight: 600; color: #333;">{suspension}</span></div>
                </div>
                
                <!-- Montos -->
                <div style="flex: 1; background-color: white; border-radius: 8px; padding: 15px; box-shadow: 0 2px 4px rgba(0,0,0,0.05);">
                    <div style="font-size: 12px; color: #666; margin-bottom: 5px;">Valor a Pagar</div>
                    <div style="font-size: 26px; font-weight: 700; color: #43a047;">$ {valor_pagar}</div>
                    <div style="display: flex; align-items: center; margin-top: 10px;">
                        <div style="flex: 1; margin-right: 10px;">
                            <div style="font-size: 11px; color: #666; margin-bottom: 2px;">Salario</div>
                            <div style="font-size: 13px; font-weight: 600; color: #333;">$ {salario}</div>
                        </div>
                        <div style="flex: 1;">
                            <div style="font-size: 11px; color: #666; margin-bottom: 2px;">Auxilio Transporte</div>
                            <div style="font-size: 13px; font-weight: 600; color: #333;">$ {auxilio}</div>
                        </div>
                    </div>
                </div>
                
                <!-- Monto Base y Provisión -->
                <div style="flex: 1; background-color: white; border-radius: 8px; padding: 15px; box-shadow: 0 2px 4px rgba(0,0,0,0.05);">
                    <div style="font-size: 12px; color: #666; margin-bottom: 5px;">Provisión</div>
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                        <div style="font-size: 26px; font-weight: 700; color: #1e88e5;">$ {provision_actual}</div>
                        <div style="font-size: 16px; padding: 8px 12px; border-radius: 6px; font-weight: 600; 
                            background-color: #e3f2fd; color: #1e88e5;">
                            +{diferencia}
                        </div>
                    </div>
                    
                    <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
                        <div style="font-size: 16px; color: #666;">Anterior:</div>
                        <div style="font-size: 16px; font-weight: 600; color: #333;">$ {provision_anterior}</div>
                    </div>
                    
                    <div style="display: flex; justify-content: space-between; margin-top: 5px;">
                        <div style="font-size: 16px; color: #666;">A contabilizar:</div>
                        <div style="font-size: 16px; font-weight: 600; color: #43a047;">$ {valor_contabilizar}</div>
                    </div>
                </div>
            </div>
        """.format(
            dias=plain_days,
            porcentaje=int(porcentaje_dias),
            porcentaje_width=porcentaje_dias,
            suspension=susp,
            valor_pagar=valor_pagar_fmt,
            salario=wage_fmt,
            auxilio=auxtransporte_fmt,
            provision_actual=provision_actual_fmt,
            diferencia=diferencia_fmt,
            provision_anterior=provision_anterior_fmt,
            valor_contabilizar=diferencia_fmt
        ))
        
        if es_intereses:
            base_cesantias = meta_info.get('base_cesantias', amount_base)
            base_cesantias_fmt = "{:,.2f}".format(base_cesantias)
            
            proporcion_anual = plain_days / 360 if plain_days > 0 else 0
            factor_decimal = 12 * proporcion_anual  if proporcion_anual > 0 else 0
            factor_porcentaje = factor_decimal 
            
            html.append("""
                <div style="background-color: #f8f9fa; border-radius: 8px; padding: 15px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.05);">
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr>
                            <td style="padding: 10px 0; font-weight: 600; color: #666;">Base de Cesantías:</td>
                            <td style="padding: 10px 0; font-weight: 600; text-align: right; color: #333;">$ {base}</td>
                        </tr>
                        <tr>
                            <td style="padding: 10px 0; font-weight: 600; color: #666;">Fórmula:</td>
                            <td style="padding: 10px 0; font-weight: 600; text-align: right; color: #333;">12 * ({dias}/360) / 100</td>
                        </tr>
                        <tr>
                            <td style="padding: 10px 0; font-weight: 600; color: #666;">Factor:</td>
                            <td style="padding: 10px 0; font-weight: 600; text-align: right; color: #333;">{factor}%</td>
                        </tr>
                    </table>
                </div>
            """.format(
                base=base_cesantias_fmt,
                dias=plain_days,
                factor="{:.2f}".format(factor_porcentaje)
            ))
        
        # 3. Cálculo con explicaciones
        titulo_calculo = ""
        if es_cesantias:
            titulo_calculo = "Cesantías"
        elif es_intereses:
            titulo_calculo = "Intereses de Cesantías"
        elif es_vacaciones:
            titulo_calculo = "Vacaciones"
        elif es_prima:
            titulo_calculo = "Prima de Servicios"
        else:
            titulo_calculo = tipo_prestacion
        
        if es_provision:
            titulo_calculo += " (Provisión)"
        else:
            titulo_calculo += " (Liquidación)"
            
        # Formulas
        if plain_days <= 30 and es_salario_variable:
            formula_usada = "{salario} + {auxilio} + {variable}".format(
                salario=wage_fmt, 
                auxilio=auxtransporte_fmt, 
                variable=total_variable_fmt
            )
        else:
            formula_usada = "{salario} + {auxilio} + ({variable} / {dias}) * 30".format(
                salario=wage_fmt, 
                auxilio=auxtransporte_fmt, 
                variable=total_variable_fmt, 
                dias=plain_days
            )
        
        if es_intereses:
            base_cesantias = meta_info.get('base_cesantias', amount_base)
            proporcion_anual = plain_days / 360 if plain_days > 0 else 0
            factor = 12 * proporcion_anual if proporcion_anual > 0 else 0
            factor_porcentaje = (factor /100)
            
            formula_valor_pagar = "{base} * {factor:.8f}% = {valor}".format(
                base="{:,.2f}".format(base_cesantias),
                factor=factor_porcentaje,
                valor=valor_pagar_fmt
            )
        elif es_cesantias:
            formula_valor_pagar = "({base} / 360) * {dias} = {valor}".format(
                base=amount_base_fmt, 
                dias=plain_days, 
                valor=valor_pagar_fmt
            )
        else:
            formula_valor_pagar = "({base} / 360) * {dias} = {valor}".format(
                base=amount_base_fmt, 
                dias=plain_days, 
                valor=valor_pagar_fmt
            )
        
        # Preparar explicación
        variacion_salario = '<span style="color: #1e88e5;">(Con variación en el período)</span>' if wage != meta_info.get("initial_wage", wage) else ''
        auxilio_explicacion = '<span style="color: #1e88e5;">(Incluido por salario menor al tope legal)</span>' if auxtransporte > 0 else '<span style="color: #e53935;">(No aplicable por salario superior al tope)</span>'
        
        # Explicación de variable según período y tipo de contrato
        if total_variable > 0:
            if plain_days <= 30 and es_salario_variable:
                variable_explicacion = '<span style="color: #1e88e5;">(Valor directo para período ≤ 30 días)</span>'
            else:
                variable_explicacion = '<span style="color: #1e88e5;">(Calculado de $ {variable} en {dias} días)</span>'.format(
                    variable=total_variable_fmt,
                    dias=plain_days
                )
        else:
            variable_explicacion = ''
        
        html.append("""
            <div style="background-color: white; border-radius: 8px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.05);">
                <h3 style="margin: 0 0 15px 0; font-size: 16px; color: #333; border-bottom: 2px solid #1e88e5; padding-bottom: 8px;">
                    Cálculo de {titulo}
                </h3>
                
                <!-- Explicación del Cálculo -->
                <div style="background-color: #f5f5f5; padding: 15px; border-radius: 6px; margin-bottom: 15px;">
                    <p style="margin: 0 0 10px 0; font-size: 14px; line-height: 1.5; color: #333;">
                        <strong>Explicación del cálculo</strong>
                    </p>
                    <ul style="margin: 0 0 10px 20px; padding: 0; font-size: 13px; line-height: 1.6; color: #555;">
                        <li style="margin-bottom: 6px;">
                            <span style="font-weight: 600;">Salario base:</span> 
                            $ {salario} {variacion}
                        </li>
                        <li style="margin-bottom: 6px;">
                            <span style="font-weight: 600;">Auxilio de transporte:</span> 
                            $ {auxilio} {auxilio_exp}
                        </li>
                        <li style="margin-bottom: 6px;">
                            <span style="font-weight: 600;">Promedio variable:</span> 
                            $ {promedio} {variable_exp}
                        </li>
                        <li style="margin-bottom: 6px;">
                            <span style="font-weight: 600;">Tipo de contrato:</span> 
                            <span style="color: #1e88e5;">{tipo_contrato}</span>
                        </li>
                    </ul>
                </div>
                
                <table style="width: 100%; border-collapse: collapse; border-radius: 4px; overflow: hidden; border: 1px solid #e0e0e0;">
                    <tr style="background-color: #f5f5f5;">
                        <th style="padding: 10px; text-align: left; font-weight: 600; color: #333; border-bottom: 1px solid #e0e0e0; width: 20%;">Concepto</th>
                        <th style="padding: 10px; text-align: left; font-weight: 600; color: #333; border-bottom: 1px solid #e0e0e0;">Fórmula</th>
                        <th style="padding: 10px; text-align: right; font-weight: 600; color: #333; border-bottom: 1px solid #e0e0e0; width: 20%;">Valor</th>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid #e0e0e0;">Base de cálculo</td>
                        <td style="padding: 10px; border-bottom: 1px solid #e0e0e0; font-family: monospace; color: #333;">{formula}</td>
                        <td style="padding: 10px; border-bottom: 1px solid #e0e0e0; text-align: right; font-weight: 600;">$ {base}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px;">Cálculo valor a pagar</td>
                        <td style="padding: 10px; font-family: monospace; color: #333;">{formula_pagar}</td>
                        <td style="padding: 10px; text-align: right; font-weight: 600;">$ {valor}</td>
                    </tr>
                </table>
            </div>
        """.format(
            titulo=titulo_calculo, 
            salario=wage_fmt,
            variacion=variacion_salario,
            auxilio=auxtransporte_fmt,
            auxilio_exp=auxilio_explicacion,
            promedio=promedio_variable_fmt,
            variable_exp=variable_explicacion,
            tipo_contrato="Salario Variable" if es_salario_variable else "Salario Fijo",
            formula=formula_usada,
            base=amount_base_fmt,
            formula_pagar=formula_valor_pagar,
            valor=valor_pagar_fmt
        ))
        
        # NUEVA SECCIÓN: Tabla de conceptos usados en el cálculo
        if reglas_salario or novedades_entradas:
            html.append("""
                <div style="background-color: white; border-radius: 8px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.05);">
                    <h3 style="margin: 0 0 15px 0; font-size: 16px; color: #333; border-bottom: 2px solid #1e88e5; padding-bottom: 8px;">
                        Conceptos Utilizados en el Cálculo
                    </h3>
                    
                    <table style="width: 100%; border-collapse: collapse; border-radius: 4px; overflow: hidden; border: 1px solid #e0e0e0;">
                        <tr style="background-color: #f5f5f5;">
                            <th style="padding: 10px; text-align: left; font-weight: 600; color: #333; border-bottom: 1px solid #e0e0e0;">Concepto</th>
                            <th style="padding: 10px; text-align: left; font-weight: 600; color: #333; border-bottom: 1px solid #e0e0e0;">Origen</th>
                            <th style="padding: 10px; text-align: center; font-weight: 600; color: #333; border-bottom: 1px solid #e0e0e0;">Fecha</th>
                            <th style="padding: 10px; text-align: right; font-weight: 600; color: #333; border-bottom: 1px solid #e0e0e0;">Monto</th>
                        </tr>
            """)
            
            # Agregar reglas salariales
            conceptos_usados = []
            
            # Usar entradas de novedades si están disponibles
            for novedad in novedades_entradas:
                fecha = novedad.get('fecha', '')
                if isinstance(fecha, str) and fecha:
                    try:
                        from datetime import datetime
                        fecha = datetime.strptime(fecha, '%Y-%m-%d').strftime('%d/%m/%Y')
                    except:
                        pass
                        
                conceptos_usados.append({
                    'concepto': novedad.get('nombre_regla', novedad.get('regla_salarial', 'N/A')),
                    'origen': novedad.get('origen', 'N/A'),
                    'fecha': fecha,
                    'monto': "{:,.2f}".format(novedad.get('monto', 0))
                })
            
            # Alternativamente, usar reglas de salario si no hay novedades
            if not conceptos_usados:
                for code, info in reglas_salario.items():
                    nombre = info.get('nombre', code)
                    total = info.get('total', 0)
                    ocurrencias = info.get('ocurrencias', [])
                    
                    if ocurrencias:
                        for ocurrencia in ocurrencias:
                            fecha = ocurrencia.get('fecha', '')
                            if isinstance(fecha, str) and fecha:
                                try:
                                    from datetime import datetime
                                    fecha = datetime.strptime(fecha, '%Y-%m-%d').strftime('%d/%m/%Y')
                                except:
                                    pass
                                    
                            conceptos_usados.append({
                                'concepto': nombre,
                                'origen': ocurrencia.get('origen', 'N/A'),
                                'fecha': fecha,
                                'monto': "{:,.2f}".format(ocurrencia.get('monto', 0))
                            })
                    else:
                        conceptos_usados.append({
                            'concepto': nombre,
                            'origen': 'Sistema',
                            'fecha': '',
                            'monto': "{:,.2f}".format(total)
                        })
            
            # Renderizar filas de la tabla
            for concepto in conceptos_usados:
                html.append("""
                    <tr style="border-bottom: 1px solid #e0e0e0;">
                        <td style="padding: 8px 10px; font-weight: 500; color: #333;">{concepto}</td>
                        <td style="padding: 8px 10px; color: #555;">{origen}</td>
                        <td style="padding: 8px 10px; color: #555; text-align: center;">{fecha}</td>
                        <td style="padding: 8px 10px; font-weight: 600; color: #333; text-align: right;">$ {monto}</td>
                    </tr>
                """.format(
                    concepto=concepto['concepto'],
                    origen=concepto['origen'],
                    fecha=concepto['fecha'],
                    monto=concepto['monto']
                ))
            
            # Mostrar total
            total_conceptos = "{:,.2f}".format(total_variable)
            html.append("""
                    <tr style="background-color: #f8f9fa;">
                        <td colspan="3" style="padding: 10px; font-weight: 700; color: #333; text-align: right;">TOTAL:</td>
                        <td style="padding: 10px; font-weight: 700; color: #1e88e5; text-align: right;">$ {total}</td>
                    </tr>
                </table>
            </div>
            """.format(total=total_conceptos))
        
        # 4. Información de Provisiones
        html.append("""
            <div style="background-color: white; border-radius: 8px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.05);">
                <h3 style="margin: 0 0 15px 0; font-size: 16px; color: #333; border-bottom: 2px solid #1e88e5; padding-bottom: 8px;">
                    Provisiones
                </h3>
                
                <!-- Tarjeta de provisiones -->
                <div style="background-color: #f8f9fa; border-radius: 6px; padding: 15px; margin-bottom: 15px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                        <div style="font-size: 15px; font-weight: 600; color: #333;">
                            Resumen de {tipo_resumen}
                        </div>
                        <div style="font-size: 16px; font-weight: 700; color: #1e88e5;">$ {provision_actual}</div>
                    </div>
                    
                    <div style="font-size: 12px; color: #666; margin-bottom: 8px; background-color: #e3f2fd; padding: 6px; border-radius: 4px;">
                        <span style="font-weight: 600;">Código:</span> {code} |
                        <span style="font-weight: 600;">Tipo:</span> {tipo_provision} |
                        <span style="font-weight: 600;">Días base:</span> {dias}/360 ({porcentaje_dias}%)
                    </div>
                    
                    <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
                        <div style="font-size: 13px; color: #666;">
                            {etiqueta_provision}
                        </div>
                        <div style="font-size: 13px; font-weight: 600; color: #333;">$ {provision_anterior}</div>
                    </div>
                    
                    <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
                        <div style="font-size: 13px; color: #666;">Diferencia:</div>
                        <div style="font-size: 13px; font-weight: 600; color: {color_diferencia};">
                            {signo}{diferencia}
                        </div>
                    </div>
                    
                    <div style="height: 1px; background-color: #e0e0e0; margin: 10px 0;"></div>
                    
                    <div style="display: flex; justify-content: space-between;">
                        <div style="font-size: 14px; font-weight: 600; color: #333;">
                            {etiqueta_accion}
                        </div>
                        <div style="font-size: 16px; font-weight: 700; color: {color_accion};">
                            $ {valor_accion}
                        </div>
                    </div>
                </div>
            </div>
        """.format(
            tipo_resumen="Provisión" if es_provision else "Liquidación",
            provision_actual=provision_actual_fmt,
            code=code,
            tipo_provision="Provisión" if es_provision else "Liquidación",
            dias=plain_days,
            porcentaje_dias="{:.1f}".format((plain_days/360)*100),
            etiqueta_provision="Provisión al corte anterior:" if es_provision else "Valor provisionado:",
            provision_anterior=provision_anterior_fmt,
            color_diferencia="#43a047" if diferencia_provision >= 0 else "#e53935",
            signo="+" if diferencia_provision >= 0 else "",
            diferencia=diferencia_fmt,
            etiqueta_accion=("Valor a provisionar:" if diferencia_provision >= 0 else "Ajuste de provisión:") if es_provision else 
                            ("Valor a pagar adicional:" if diferencia_provision >= 0 else "Valor sobreestimado:"),
            color_accion="#43a047" if diferencia_provision >= 0 else "#e53935",
            valor_accion="{:,.2f}".format(abs(diferencia_provision))
        ))
        
        # Cierre
        html.append("</div>")
        
        # Unir todo el HTML
        return "".join(html)

    def _combine_reports(self, reports):
        """Combina múltiples reportes en uno solo"""
        combined_html = """
        <div class="prestaciones-sociales-combined-report">
        <h1>Reporte de Prestaciones Sociales</h1>
        """
        
        for report in reports:
            combined_html += report
            combined_html += "<hr>"  # Separador entre reportes
        
        combined_html += "</div>"
        return combined_html

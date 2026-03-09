
# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from datetime import datetime, timedelta, date
from odoo.exceptions import UserError, ValidationError
from calendar import monthrange
import time

from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import logging
from dateutil.relativedelta import relativedelta
import base64
import xlsxwriter
from io import BytesIO
import logging

_logger = logging.getLogger(__name__)

tabla_retencion = [
    (0, 95, 0, 0, 0),   
    (95, 150, 19, 95, 0),    
    (150, 360, 28, 150, 10),   
    (360, 640, 33, 360, 69),  
    (640, 945, 35, 640, 162),   
    (945, 2300, 37, 945, 268),  
    (2300, float('inf'), 39, 2300, 770)  
]

class HrContractRtfLog(models.Model):
    _name = 'hr.contract.rtf.log'
    _description = 'Registro de cálculo de RTF'

    name = fields.Char('Descripción')
    value = fields.Char('Detalle', help="Valor formateado para presentación")
    value_float = fields.Float('Valor Numérico', help="Valor numérico para cálculos")
    contract_id = fields.Many2one('hr.contract', 'Contrato')
    calculation_date = fields.Date('Fecha de cálculo', default=fields.Date.today)
    january = fields.Float('ENE', default=0.0)
    february = fields.Float('FEB', default=0.0)
    march = fields.Float('MAR', default=0.0)
    april = fields.Float('ABR', default=0.0)
    may = fields.Float('MAY', default=0.0)
    june = fields.Float('JUN', default=0.0)
    july = fields.Float('JUL', default=0.0)
    august = fields.Float('AGO', default=0.0)
    september = fields.Float('SEP', default=0.0)
    october = fields.Float('OCT', default=0.0)
    november = fields.Float('NOV', default=0.0)
    december = fields.Float('DIC', default=0.0)
    
    concept_type = fields.Selection([
        ('income', 'Ingreso'),
        ('deduction', 'Deducción'),
        ('exempt', 'Renta Exenta'),
        ('retention', 'Retención'),
        ('summary', 'Resumen')
    ], string='Tipo de Concepto')
    concept_code = fields.Char('Código de Concepto', 
                             help='Código del concepto para agrupar valores')
    calculation_period = fields.Selection([
        ('1', 'Primer Semestre (Dic-May)'),
        ('2', 'Segundo Semestre (Jun-Nov)')
    ], string='Periodo de Cálculo')
    sequence = fields.Integer('Secuencia', default=10)
class hr_employee(models.Model):
    _inherit = 'hr.employee'
    
    ret_line_ids =fields.One2many('lavish.retencion.reporte', 'employee_id', string='Detalle de retencion', readonly=True)
class hr_employeePublic(models.Model):
    _inherit = 'hr.employee.public'
    ret_line_ids =fields.One2many('lavish.retencion.reporte', 'employee_id', string='Detalle de retencion', readonly=True)
class hr_contract(models.Model):
    _inherit = 'hr.contract'

    prima_ids = fields.One2many('hr.history.prima', 'contract_id', string="Historico de prima", readonly=True)
    cesantia_ids = fields.One2many('hr.history.cesantias', 'contract_id', string="Historico de cesantías", readonly=True)

    vacaciones_ids = fields.One2many('hr.vacation', 'contract_id', string="Historico de vacaciones", readonly=True)
    days_left = fields.Float(string='Días restantes', default=0)
    days_total = fields.Float(string='Días totales', default=0)
    date_ref_holiday_book = fields.Date(string='Fecha referencia')

    contract_days = fields.Integer(string='Días de Contrato')
    rtf_log = fields.One2many('hr.contract.rtf.log', 'contract_id', string="Calculo tarifa RTFP2")
    rtf_rate = fields.Float(string='Porcentaje de retencion', digits='Payroll', default=1.0)
    ded_dependents = fields.Boolean('Dependiente', tracking=True)
    pr_rtf = fields.Boolean('Primer Calculo', tracking=True)
    contract_progress = fields.Float(compute='_compute_contract_progress', store=True)
    contract_color = fields.Char(compute='_compute_contract_progress', store=True)
    last_rtf_calculation = fields.Date('Última fecha de cálculo RTF')
    rtf_date_from = fields.Date(string='Fecha inicio RTF', 
                                help='Fecha de inicio para el cálculo manual de retención')
    rtf_date_to = fields.Date(string='Fecha fin RTF',
                              help='Fecha fin para el cálculo manual de retención')
    rtf_rate_first_semester = fields.Float(string='Retención 1er semestre (%)', digits='Payroll', default=0.0)
    rtf_rate_second_semester = fields.Float(string='Retención 2do semestre (%)', digits='Payroll', default=0.0)
    rtf_current_period = fields.Selection([
        ('1', 'Primer Semestre (Dic-May)'),
        ('2', 'Segundo Semestre (Jun-Nov)')
    ], string='Periodo Actual de RTF')
    excel_file = fields.Binary('Archivo Excel')
    excel_filename = fields.Char('Nombre del archivo')
    provision_adjustment_created = fields.Boolean('Ajuste de Provisión Creado', default=False)
    last_adjustment_date = fields.Date('Última Fecha de Ajuste')
    accumulated_payroll_ids = fields.One2many(
        'hr.accumulated.payroll', 
        'contract_id', 
        string='Acumulados de Nómina'
    )
    @api.onchange('rtf_current_period')
    def _onchange_rtf_period(self):
        """Actualiza fechas automáticamente al cambiar el periodo"""
        if self.rtf_current_period:
            today = fields.Date.today()
            if self.rtf_current_period == '1':
                # Primer semestre (Dic-May)
                if today.month <= 5:
                    year = today.year - 1
                    self.rtf_date_from = date(year, 12, 1)
                    self.rtf_date_to = date(today.year, 5, 31)
                else:
                    year = today.year
                    self.rtf_date_from = date(year, 12, 1)
                    self.rtf_date_to = date(year + 1, 5, 31)
            else:
                # Segundo semestre (Jun-Nov)
                if today.month <= 11 and today.month >= 6:
                    self.rtf_date_from = date(today.year, 6, 1)
                    self.rtf_date_to = date(today.year, 11, 30)
                else:
                    year = today.year - 1
                    self.rtf_date_from = date(year, 6, 1)
                    self.rtf_date_to = date(year, 11, 30)
    
    def days_between(self, start_date, end_date):
        """Calcula días entre dos fechas usando el método comercial de 360 días"""
        s1, e1 = start_date, end_date + timedelta(days=1)
        # Convertir a 360 días
        s360 = (s1.year * 12 + s1.month) * 30 + s1.day
        e360 = (e1.year * 12 + e1.month) * 30 + e1.day
        # Contar días entre las dos fechas 360 y devolver tupla (meses, días)
        res = divmod(e360 - s360, 30)
        return ((res[0] * 30) + res[1]) or 0
    
    def get_contract_deductions_rtf(self, contract_id, code):
        """Recupera las deducciones de retención configuradas en el contrato"""
        res = self.env['hr.contract.deductions.rtf'].search([
            ('contract_id', '=', contract_id),
            ('input_id.code', '=', code)
        ], limit=1)
        
        if not res:
            # Si no hay registro, crear uno vacío para evitar errores
            return self.env['hr.contract.deductions.rtf'].new({
                'contract_id': contract_id,
                'value_monthly': 0.0
            })
        return res
    
    def get_calcula_rtefte_ordinaria(self, base_rtefte_uvt):
        """Obtiene la información de cálculo de retención según la base en UVT"""
        # Buscar el rango aplicable en la tabla de retención
        for desde, hasta, tarifa, resta_uvt, suma_uvt in tabla_retencion:
            if desde <= base_rtefte_uvt < hasta:
                return {
                    'range_initial': desde,
                    'range_finally': hasta,
                    'porc': tarifa,
                    'subtract_uvt': resta_uvt,
                    'addition_uvt': suma_uvt
                }
        return {
            'range_initial': 0,
            'range_finally': 0,
            'porc': 0,
            'subtract_uvt': 0,
            'addition_uvt': 0
        }
    
    def sum_mount(self, category_code, contract, date_from, date_to):
        """Suma los montos por categoría de regla salarial"""
        self.env.cr.execute("""
            SELECT SUM(pl.total)
            FROM hr_payslip_line pl
            JOIN hr_salary_rule_category src ON pl.category_id = src.id
            JOIN hr_payslip p ON pl.slip_id = p.id
            WHERE p.contract_id = %s
              AND p.state IN ('done', 'paid')
              AND p.date_to >= %s
              AND p.date_from <= %s
              AND src.code = %s
        """, (contract.id, date_from, date_to, category_code))
        result = self.env.cr.fetchone()
        return result[0] if result and result[0] else 0.0
    
    def sum_mount_x_rule(self, rule_code, contract, date_from, date_to):
        """Suma los montos por código de regla salarial"""
        self.env.cr.execute("""
            SELECT SUM(pl.total)
            FROM hr_payslip_line pl
            JOIN hr_payslip p ON pl.slip_id = p.id
            WHERE p.contract_id = %s
              AND p.state IN ('done', 'paid')
              AND p.date_to >= %s
              AND p.date_from <= %s
              AND pl.code = %s
        """, (contract.id, date_from, date_to, rule_code))
        result = self.env.cr.fetchone()
        return result[0] if result and result[0] else 0.0

    def compute_rtf2(self):
        log_data = []
        for contract in self:
            if contract.retention_procedure != '102':
                continue
                
            if not contract.rtf_date_from or not contract.rtf_date_to or not contract.rtf_current_period:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Error',
                        'message': 'Debe configurar fechas y periodo de cálculo',
                        'type': 'danger',
                        'sticky': False,
                    }
                }
            
            ref_date_from = contract.rtf_date_from
            ref_date_to = contract.rtf_date_to
            seg = contract.rtf_current_period
            
            self.env.cr.execute("DELETE FROM hr_contract_rtf_log WHERE contract_id = %s AND calculation_period = %s", 
                            (contract.id, seg))
            
            payslips = self.env['hr.payslip'].search([
                ('date_to', '>=', ref_date_from),
                ('date_to', '<=', ref_date_to),
                ('contract_id', '=', contract.id),
                ('state', 'in', ['done', 'paid'])
            ], order='date_from asc')
            
            payslip_count = len(payslips)
            
            if payslip_count >= 6:
                contract.pr_rtf = True
            
            def format_currency(amount):
                return "${:,.2f}".format(amount).replace(',', 'X').replace('.', ',').replace('X', '.')
            
            payslip_lines = self.env['hr.payslip.line'].search([
                ('slip_id', 'in', payslips.ids)
            ])
            
            payslips_by_month = {}
            all_months = {}
            
            start_date = ref_date_from
            while start_date <= ref_date_to:
                month_key = (start_date.year, start_date.month)
                all_months[month_key] = {'has_data': False}
                
                if start_date.month == 12:
                    start_date = start_date.replace(year=start_date.year + 1, month=1)
                else:
                    start_date = start_date.replace(month=start_date.month + 1)
            
            for payslip in payslips:
                month_key = (payslip.date_from.year, payslip.date_from.month)
                if month_key not in payslips_by_month:
                    payslips_by_month[month_key] = self.env['hr.payslip']
                payslips_by_month[month_key] |= payslip
                all_months[month_key]['has_data'] = True
            
            annual_parameters = self.env['hr.annual.parameters'].search([
                ('year', '=', ref_date_to.year)
            ], limit=1)
            
            concepts = {
                'BASIC': {'name': 'Salario', 'type': 'income', 'code': 'BASIC', 'sequence': 10},
                'COMISIONES': {'name': 'Comisiones', 'type': 'income', 'code': 'COMISIONES', 'sequence': 20},
                'DEV_SALARIAL': {'name': 'Otros Ingresos Salariales', 'type': 'income', 'code': 'DEV_SALARIAL', 'sequence': 30},
                'COMPLEMENTARIOS': {'name': 'Ingresos Complementarios', 'type': 'income', 'code': 'COMPLEMENTARIOS', 'sequence': 40},
                'DEV_NO_SALARIAL': {'name': 'Ingresos No Salariales', 'type': 'income', 'code': 'DEV_NO_SALARIAL', 'sequence': 50},
                'SSOCIAL001': {'name': 'Aportes Salud', 'type': 'deduction', 'code': 'SSOCIAL001', 'sequence': 60},
                'SSOCIAL002': {'name': 'Aportes Pensión', 'type': 'deduction', 'code': 'SSOCIAL002', 'sequence': 70},
                'SSOCIAL003': {'name': 'Aporte Subsistencia', 'type': 'deduction', 'code': 'SSOCIAL003', 'sequence': 80},
                'SSOCIAL004': {'name': 'Aporte Solidaridad', 'type': 'deduction', 'code': 'SSOCIAL004', 'sequence': 90},
                'AFC': {'name': 'Aportes AFC', 'type': 'exempt', 'code': 'AFC', 'sequence': 100}
            }
            
            monthly_values = {}
            for concept_code in concepts:
                monthly_values[concept_code] = {
                    'name': concepts[concept_code]['name'],
                    'type': concepts[concept_code]['type'],
                    'code': concept_code,
                    'sequence': concepts[concept_code]['sequence'],
                    'total': 0.0,
                    'months': {
                        1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0, 5: 0.0, 6: 0.0,
                        7: 0.0, 8: 0.0, 9: 0.0, 10: 0.0, 11: 0.0, 12: 0.0
                    }
                }
            
            for (year, month), month_payslips in payslips_by_month.items():
                month_lines = payslip_lines.filtered(lambda l: l.slip_id in month_payslips)
                
                for concept_code, concept_info in concepts.items():
                    if concept_code == 'BASIC':
                        value = sum(line.total for line in month_lines if line.category_id.code == 'BASIC')
                    elif concept_code == 'COMISIONES':
                        value = sum(line.total for line in month_lines if line.code == 'COMISIONES')
                    elif concept_code == 'DEV_SALARIAL':
                        value = sum(line.total for line in month_lines 
                                if (line.category_id.code == 'DEV_SALARIAL' or 
                                    (line.category_id.parent_id and line.category_id.parent_id.code == 'DEV_SALARIAL')) 
                                and line.category_id.code != 'BASIC'
                                and line.code != 'COMISIONES')
                    elif concept_code == 'COMPLEMENTARIOS':
                        value = sum(line.total for line in month_lines if line.category_id.code == 'COMPLEMENTARIOS')
                    elif concept_code == 'DEV_NO_SALARIAL':
                        value = sum(line.total for line in month_lines 
                                if (line.category_id.code == 'DEV_NO_SALARIAL' or 
                                    (line.category_id.parent_id and line.category_id.parent_id.code == 'DEV_NO_SALARIAL'))
                                and line.code != 'AUX000')
                    elif concept_code in ['SSOCIAL001', 'SSOCIAL002', 'SSOCIAL003', 'SSOCIAL004', 'AFC']:
                        value = sum(line.total for line in month_lines if line.code == concept_code)
                        if value > 0:
                            value *= -1
                    else:
                        value = 0.0
                    
                    monthly_values[concept_code]['months'][month] += value
                    monthly_values[concept_code]['total'] += value
            
            months_with_data = {k: v for k, v in all_months.items() if v['has_data']}
            
            if months_with_data:
                concept_averages = {}
                for concept_code, data in monthly_values.items():
                    months_with_values = sum(1 for month in range(1, 13) if data['months'][month] > 0)
                    
                    if months_with_values > 0:
                        concept_averages[concept_code] = data['total'] / months_with_values
                    else:
                        if concept_code == 'BASIC':
                            concept_averages[concept_code] = contract.wage
                        elif concept_code == 'SSOCIAL001':
                            concept_averages[concept_code] = contract.wage * 0.04
                        elif concept_code == 'SSOCIAL002':
                            concept_averages[concept_code] = contract.wage * 0.04
                        elif concept_code == 'SSOCIAL003':
                            if contract.wage > annual_parameters.smmlv_monthly * 4:
                                porcentaje_subsistencia = contract._calcular_porcentaje_subsistencia(
                                    contract.wage, annual_parameters.smmlv_monthly)
                                concept_averages[concept_code] = contract.wage * (porcentaje_subsistencia / 100)
                            else:
                                concept_averages[concept_code] = 0.0
                        elif concept_code == 'SSOCIAL004':
                            if contract.wage > annual_parameters.smmlv_monthly * 4:
                                concept_averages[concept_code] = contract.wage * 0.005
                            else:
                                concept_averages[concept_code] = 0.0
                        else:
                            concept_averages[concept_code] = 0.0
                
                for (year, month), month_data in all_months.items():
                    if not month_data['has_data']:
                        for concept_code in concepts:
                            monthly_values[concept_code]['months'][month] = concept_averages.get(concept_code, 0.0)
                            monthly_values[concept_code]['total'] += concept_averages.get(concept_code, 0.0)
            
            elif payslip_count < 3:
                months_count = len(all_months)
                
                for month_key in all_months:
                    month = month_key[1]
                    
                    monthly_values['BASIC']['months'][month] = contract.wage
                    
                    monthly_values['SSOCIAL001']['months'][month] = contract.wage * 0.04
                    monthly_values['SSOCIAL002']['months'][month] = contract.wage * 0.04
                    
                    if contract.wage > annual_parameters.smmlv_monthly * 4:
                        monthly_values['SSOCIAL004']['months'][month] = contract.wage * 0.005
                        
                        subsistencia_porcentaje = contract._calcular_porcentaje_subsistencia(
                            contract.wage, annual_parameters.smmlv_monthly)
                        monthly_values['SSOCIAL003']['months'][month] = contract.wage * (subsistencia_porcentaje / 100)
                    
                    deduction_medpre = contract.get_contract_deductions_rtf(contract.id, 'MEDPRE').value_monthly
                    deduction_intviv = contract.get_contract_deductions_rtf(contract.id, 'INTVIV').value_monthly
                
                for concept_code in concepts:
                    monthly_values[concept_code]['total'] = sum(monthly_values[concept_code]['months'].values())
            
            uvt = annual_parameters.value_uvt
            
            total_income = sum(monthly_values[code]['total'] for code in 
                            ['BASIC', 'COMISIONES', 'DEV_SALARIAL', 'COMPLEMENTARIOS', 'DEV_NO_SALARIAL'])
            
            total_non_income = monthly_values['SSOCIAL001']['total'] + monthly_values['SSOCIAL002']['total'] + \
                            monthly_values['SSOCIAL003']['total'] + monthly_values['SSOCIAL004']['total']
            
            net_income = total_income - total_non_income
            
            if contract.ded_dependents:
                dep_base = total_income * 0.1
                ded_depend = dep_base if dep_base <= 72 * uvt else 72 * uvt
            else:
                ded_depend = 0
            
            base_mp = contract.get_contract_deductions_rtf(contract.id, 'MEDPRE').value_monthly * 12
            ded_mp = base_mp if base_mp <= 192 * uvt else 192 * uvt
            
            base_liv = contract.get_contract_deductions_rtf(contract.id, 'INTVIV').value_monthly * 12
            ded_liv = base_liv if base_liv <= 1200 * uvt else 1200 * uvt
            
            total_deduct = ded_depend + ded_mp + ded_liv
            
            re_afc = monthly_values['AFC']['total']
            
            base25 = (net_income - total_deduct - re_afc) * 0.25
            top25 = base25 if base25 <= 2880 * uvt else 2880 * uvt
            
            base40 = net_income * 0.4
            baserex = total_deduct + re_afc + top25
            rent_ex = baserex if baserex <= base40 else base40
            
            brtf = net_income - rent_ex
            
            days = contract.days_between(ref_date_from, ref_date_to)
            
            if days < 360:
                meses_vinculacion = (days // 30) + (1 if days % 30 > 0 else 0)
                factor = meses_vinculacion
            else:
                factor = 13
            
            brtf_month = brtf / factor if factor else 0
            
            b_uvt = brtf_month / uvt if uvt else 0
            
            retencion = 0
            tarifa = 0
            resta_uvt = 0
            suma_uvt = 0
            
            tabla_retencion = [
                (0, 95, 0, 0, 0),
                (95, 150, 19, 95, 0),
                (150, 360, 28, 150, 10),
                (360, 640, 33, 360, 69),
                (640, 945, 35, 640, 162),
                (945, 2300, 37, 945, 268),
                (2300, float('inf'), 39, 2300, 770)
            ]
            
            for desde, hasta, tarifa_rango, resta, suma in tabla_retencion:
                if desde <= b_uvt < hasta:
                    tarifa = tarifa_rango
                    resta_uvt = resta
                    suma_uvt = suma
                    if desde == 0:
                        retencion = 0
                    else:
                        retencion = (((b_uvt - resta_uvt) * (tarifa/100)) + suma_uvt) * uvt
                    break
            
            if b_uvt and uvt:
                rate_p2 = retencion * 100 / brtf_month
            else:
                rate_p2 = 0
            
            if seg == '1':
                contract.rtf_rate_first_semester = rate_p2
            else:
                contract.rtf_rate_second_semester = rate_p2
            
            contract.rtf_rate = rate_p2
            contract.last_rtf_calculation = fields.Date.today()
            
            for concept_code, data in monthly_values.items():
                if concept_code in ['BASIC', 'COMISIONES', 'DEV_SALARIAL', 'COMPLEMENTARIOS', 'DEV_NO_SALARIAL']:
                    log_data.append({
                        'name': data['name'],
                        'value': format_currency(data['total']),
                        'value_float': data['total'],
                        'contract_id': contract.id,
                        'concept_type': data['type'],
                        'concept_code': data['code'],
                        'calculation_period': seg,
                        'calculation_date': fields.Date.today(),
                        'sequence': data['sequence'],
                        'january': data['months'][1],
                        'february': data['months'][2],
                        'march': data['months'][3],
                        'april': data['months'][4],
                        'may': data['months'][5],
                        'june': data['months'][6],
                        'july': data['months'][7],
                        'august': data['months'][8],
                        'september': data['months'][9],
                        'october': data['months'][10],
                        'november': data['months'][11],
                        'december': data['months'][12],
                    })
            
            log_data.append({
                'name': 'Aportes Salud',
                'value': format_currency(monthly_values['SSOCIAL001']['total']),
                'value_float': monthly_values['SSOCIAL001']['total'],
                'contract_id': contract.id,
                'concept_type': 'deduction',
                'concept_code': 'SSOCIAL001',
                'calculation_period': seg,
                'calculation_date': fields.Date.today(),
                'sequence': 60,
                'january': monthly_values['SSOCIAL001']['months'][1],
                'february': monthly_values['SSOCIAL001']['months'][2],
                'march': monthly_values['SSOCIAL001']['months'][3],
                'april': monthly_values['SSOCIAL001']['months'][4],
                'may': monthly_values['SSOCIAL001']['months'][5],
                'june': monthly_values['SSOCIAL001']['months'][6],
                'july': monthly_values['SSOCIAL001']['months'][7],
                'august': monthly_values['SSOCIAL001']['months'][8],
                'september': monthly_values['SSOCIAL001']['months'][9],
                'october': monthly_values['SSOCIAL001']['months'][10],
                'november': monthly_values['SSOCIAL001']['months'][11],
                'december': monthly_values['SSOCIAL001']['months'][12],
            })
            
            log_data.append({
                'name': 'Aportes Pensión',
                'value': format_currency(monthly_values['SSOCIAL002']['total']),
                'value_float': monthly_values['SSOCIAL002']['total'],
                'contract_id': contract.id,
                'concept_type': 'deduction',
                'concept_code': 'SSOCIAL002',
                'calculation_period': seg,
                'calculation_date': fields.Date.today(),
                'sequence': 70,
                'january': monthly_values['SSOCIAL002']['months'][1],
                'february': monthly_values['SSOCIAL002']['months'][2],
                'march': monthly_values['SSOCIAL002']['months'][3],
                'april': monthly_values['SSOCIAL002']['months'][4],
                'may': monthly_values['SSOCIAL002']['months'][5],
                'june': monthly_values['SSOCIAL002']['months'][6],
                'july': monthly_values['SSOCIAL002']['months'][7],
                'august': monthly_values['SSOCIAL002']['months'][8],
                'september': monthly_values['SSOCIAL002']['months'][9],
                'october': monthly_values['SSOCIAL002']['months'][10],
                'november': monthly_values['SSOCIAL002']['months'][11],
                'december': monthly_values['SSOCIAL002']['months'][12],
            })
            
            if monthly_values['SSOCIAL003']['total'] > 0:
                log_data.append({
                    'name': 'Fondo de Solidaridad',
                    'value': format_currency(monthly_values['SSOCIAL003']['total']),
                    'value_float': monthly_values['SSOCIAL003']['total'],
                    'contract_id': contract.id,
                    'concept_type': 'deduction',
                    'concept_code': 'SSOCIAL003',
                    'calculation_period': seg,
                    'calculation_date': fields.Date.today(),
                    'sequence': 80,
                    'january': monthly_values['SSOCIAL003']['months'][1],
                    'february': monthly_values['SSOCIAL003']['months'][2],
                    'march': monthly_values['SSOCIAL003']['months'][3],
                    'april': monthly_values['SSOCIAL003']['months'][4],
                    'may': monthly_values['SSOCIAL003']['months'][5],
                    'june': monthly_values['SSOCIAL003']['months'][6],
                    'july': monthly_values['SSOCIAL003']['months'][7],
                    'august': monthly_values['SSOCIAL003']['months'][8],
                    'september': monthly_values['SSOCIAL003']['months'][9],
                    'october': monthly_values['SSOCIAL003']['months'][10],
                    'november': monthly_values['SSOCIAL003']['months'][11],
                    'december': monthly_values['SSOCIAL003']['months'][12],
                })
            
            if monthly_values['SSOCIAL004']['total'] > 0:
                log_data.append({
                    'name': 'Fondo de Subsistencia',
                    'value': format_currency(monthly_values['SSOCIAL004']['total']),
                    'value_float': monthly_values['SSOCIAL004']['total'],
                    'contract_id': contract.id,
                    'concept_type': 'deduction',
                    'concept_code': 'SSOCIAL004',
                    'calculation_period': seg,
                    'calculation_date': fields.Date.today(),
                    'sequence': 90,
                    'january': monthly_values['SSOCIAL004']['months'][1],
                    'february': monthly_values['SSOCIAL004']['months'][2],
                    'march': monthly_values['SSOCIAL004']['months'][3],
                    'april': monthly_values['SSOCIAL004']['months'][4],
                    'may': monthly_values['SSOCIAL004']['months'][5],
                    'june': monthly_values['SSOCIAL004']['months'][6],
                    'july': monthly_values['SSOCIAL004']['months'][7],
                    'august': monthly_values['SSOCIAL004']['months'][8],
                    'september': monthly_values['SSOCIAL004']['months'][9],
                    'october': monthly_values['SSOCIAL004']['months'][10],
                    'november': monthly_values['SSOCIAL004']['months'][11],
                    'december': monthly_values['SSOCIAL004']['months'][12],
                })
            
            log_data.append({
                'name': 'Deducción Dependientes',
                'value': format_currency(ded_depend),
                'value_float': ded_depend,
                'contract_id': contract.id,
                'concept_type': 'deduction',
                'concept_code': 'DEP',
                'calculation_period': seg,
                'calculation_date': fields.Date.today(),
                'sequence': 110,
            })
            
            log_data.append({
                'name': 'Medicina Prepagada',
                'value': format_currency(ded_mp),
                'value_float': ded_mp,
                'contract_id': contract.id,
                'concept_type': 'deduction',
                'concept_code': 'MEDPRE',
                'calculation_period': seg,
                'calculation_date': fields.Date.today(),
                'sequence': 120,
            })
            
            log_data.append({
                'name': 'Intereses de Vivienda',
                'value': format_currency(ded_liv),
                'value_float': ded_liv,
                'contract_id': contract.id,
                'concept_type': 'deduction',
                'concept_code': 'INTVIV',
                'calculation_period': seg,
                'calculation_date': fields.Date.today(),
                'sequence': 130,
            })
            
            log_data.append({
                'name': 'Aportes AFC',
                'value': format_currency(re_afc),
                'value_float': re_afc,
                'contract_id': contract.id,
                'concept_type': 'exempt',
                'concept_code': 'AFC',
                'calculation_period': seg,
                'calculation_date': fields.Date.today(),
                'sequence': 140,
                'january': monthly_values['AFC']['months'][1],
                'february': monthly_values['AFC']['months'][2],
                'march': monthly_values['AFC']['months'][3],
                'april': monthly_values['AFC']['months'][4],
                'may': monthly_values['AFC']['months'][5],
                'june': monthly_values['AFC']['months'][6],
                'july': monthly_values['AFC']['months'][7],
                'august': monthly_values['AFC']['months'][8],
                'september': monthly_values['AFC']['months'][9],
                'october': monthly_values['AFC']['months'][10],
                'november': monthly_values['AFC']['months'][11],
                'december': monthly_values['AFC']['months'][12],
            })
            
            log_data.append({
                'name': 'Renta Exenta 25%',
                'value': format_currency(top25),
                'value_float': top25,
                'contract_id': contract.id,
                'concept_type': 'exempt',
                'concept_code': 'RENTA25',
                'calculation_period': seg,
                'calculation_date': fields.Date.today(),
                'sequence': 150,
            })
            
            log_data.append({
                'name': 'Total Ingresos',
                'value': format_currency(total_income),
                'value_float': total_income,
                'contract_id': contract.id,
                'concept_type': 'summary',
                'concept_code': 'TOTAL_ING',
                'calculation_period': seg,
                'calculation_date': fields.Date.today(),
                'sequence': 200,
            })
            
            log_data.append({
                'name': 'Ingresos No Constitutivos',
                'value': format_currency(total_non_income),
                'value_float': total_non_income,
                'contract_id': contract.id,
                'concept_type': 'summary',
                'concept_code': 'TOTAL_INCRGO',
                'calculation_period': seg,
                'calculation_date': fields.Date.today(),
                'sequence': 210,
            })
            
            log_data.append({
                'name': 'Ingresos Netos',
                'value': format_currency(net_income),
                'value_float': net_income,
                'contract_id': contract.id,
                'concept_type': 'summary',
                'concept_code': 'NETO',
                'calculation_period': seg,
                'calculation_date': fields.Date.today(),
                'sequence': 220,
            })
            
            log_data.append({
                'name': 'Total Deducciones',
                'value': format_currency(total_deduct),
                'value_float': total_deduct,
                'contract_id': contract.id,
                'concept_type': 'summary',
                'concept_code': 'TOTAL_DED',
                'calculation_period': seg,
                'calculation_date': fields.Date.today(),
                'sequence': 230,
            })
            
            log_data.append({
                'name': 'Total Rentas Exentas',
                'value': format_currency(rent_ex),
                'value_float': rent_ex,
                'contract_id': contract.id,
                'concept_type': 'summary',
                'concept_code': 'TOTAL_RE',
                'calculation_period': seg,
                'calculation_date': fields.Date.today(),
                'sequence': 240,
            })
            
            log_data.append({
                'name': 'Base Retención',
                'value': format_currency(brtf),
                'value_float': brtf,
                'contract_id': contract.id,
                'concept_type': 'summary',
                'concept_code': 'BASE_RET',
                'calculation_period': seg,
                'calculation_date': fields.Date.today(),
                'sequence': 250,
            })
            
            log_data.append({
                'name': 'Factor Meses',
                'value': str(factor),
                'value_float': factor,
                'contract_id': contract.id,
                'concept_type': 'summary',
                'concept_code': 'FACTOR',
                'calculation_period': seg,
                'calculation_date': fields.Date.today(),
                'sequence': 255,
            })
            
            log_data.append({
                'name': 'Base Retención Promedio',
                'value': format_currency(brtf_month),
                'value_float': brtf_month,
                'contract_id': contract.id,
                'concept_type': 'summary',
                'concept_code': 'BASE_RET_PROM',
                'calculation_period': seg,
                'calculation_date': fields.Date.today(),
                'sequence': 260,
            })
            
            log_data.append({
                'name': 'Base Mensual UVT',
                'value': str(round(b_uvt, 2)),
                'value_float': b_uvt,
                'contract_id': contract.id,
                'concept_type': 'summary',
                'concept_code': 'BASE_UVT',
                'calculation_period': seg,
                'calculation_date': fields.Date.today(),
                'sequence': 265,
            })
            
            log_data.append({
                'name': 'Porcentaje Retención',
                'value': str(round(rate_p2, 2)) + '%',
                'value_float': rate_p2,
                'contract_id': contract.id,
                'concept_type': 'summary',
                'concept_code': 'PORC_RET',
                'calculation_period': seg,
                'calculation_date': fields.Date.today(),
                'sequence': 270,
            })
            
            log_data.append({
                'name': 'FECHA INICIO',
                'value': str(ref_date_from),
                'contract_id': contract.id,
                'concept_type': 'summary',
                'concept_code': 'FECHA_INICIO',
                'calculation_period': seg,
                'calculation_date': fields.Date.today(),
                'sequence': 300,
            })
            
            log_data.append({
                'name': 'FECHA FIN',
                'value': str(ref_date_to),
                'contract_id': contract.id,
                'concept_type': 'summary',
                'concept_code': 'FECHA_FIN',
                'calculation_period': seg,
                'calculation_date': fields.Date.today(),
                'sequence': 310,
            })
            
            log_data.append({
                'name': 'VALOR UVT',
                'value': format_currency(uvt),
                'value_float': uvt,
                'contract_id': contract.id,
                'concept_type': 'summary',
                'concept_code': 'UVT',
                'calculation_period': seg,
                'calculation_date': fields.Date.today(),
                'sequence': 320,
            })
            
            log_data.append({
                'name': 'DIAS INTERVALO',
                'value': str(days),
                'value_float': days,
                'contract_id': contract.id,
                'concept_type': 'summary',
                'concept_code': 'DIAS',
                'calculation_period': seg,
                'calculation_date': fields.Date.today(),
                'sequence': 330,
            })
        
        if log_data:
            self.env['hr.contract.rtf.log'].sudo().create(log_data)
            
            self.action_generate_excel()
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Éxito',
                    'message': f'Cálculo de retención completado. Porcentaje: {rate_p2:.2f}%',
                    'type': 'success',
                    'sticky': False,
                }
            }
        return True
        
    def _calcular_porcentaje_subsistencia(self, ingreso_base, salario_minimo):
        """Determina el porcentaje según el rango de IBC para el fondo de subsistencia"""
        if ingreso_base <= 4 * salario_minimo:
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
            
    def _generate_excel_report(self):
        output = BytesIO()
        workbook = xlsxwriter.Workbook(output)
        worksheet = workbook.add_worksheet('Retención en la fuente')
        
        header_format = workbook.add_format({
            'bold': True, 
            'align': 'center', 
            'valign': 'vcenter', 
            'fg_color': '#4F81BD', 
            'font_color': 'white',
            'border': 1
        })
        
        title_format = workbook.add_format({
            'bold': True, 
            'align': 'center', 
            'valign': 'vcenter', 
            'font_size': 14
        })
        
        subtitle_format = workbook.add_format({
            'bold': True, 
            'align': 'left', 
            'valign': 'vcenter', 
            'font_size': 12
        })
        
        data_format = workbook.add_format({
            'align': 'right', 
            'valign': 'vcenter',
            'border': 1
        })
        
        currency_format = workbook.add_format({
            'align': 'right', 
            'valign': 'vcenter',
            'border': 1,
            'num_format': '$#,##0.00'
        })
        
        label_format = workbook.add_format({
            'align': 'left', 
            'valign': 'vcenter',
            'border': 1
        })
        
        percent_format = workbook.add_format({
            'align': 'right',
            'valign': 'vcenter',
            'border': 1,
            'num_format': '0.00%'
        })
        
        income_format = workbook.add_format({
            'align': 'right',
            'valign': 'vcenter',
            'border': 1,
            'num_format': '$#,##0.00',
            'bg_color': '#FFFF99'
        })
        
        deduction_format = workbook.add_format({
            'align': 'right',
            'valign': 'vcenter',
            'border': 1,
            'num_format': '$#,##0.00',
            'bg_color': '#B8CCE4'
        })
        
        exempt_format = workbook.add_format({
            'align': 'right',
            'valign': 'vcenter',
            'border': 1,
            'num_format': '$#,##0.00',
            'bg_color': '#C4D79B'
        })
        
        summary_format = workbook.add_format({
            'align': 'right',
            'valign': 'vcenter',
            'border': 1,
            'num_format': '$#,##0.00',
            'bg_color': '#F2DCDB',
            'bold': True
        })
        
        info_format = workbook.add_format({
            'align': 'left',
            'valign': 'vcenter',
            'border': 1,
            'bg_color': '#E6E0EC',
            'text_wrap': True
        })
        
        employee = self.employee_id
        worksheet.merge_range('A1:O1', 'Retención en la fuente recálculo semestral', title_format)
        worksheet.merge_range('A2:O2', f'Expedición América NIT: {self.env.company.vat}', subtitle_format)
        worksheet.merge_range('A3:O3', f'Fecha: {datetime.now().strftime("%d/%m/%Y %H:%M:%S")}', subtitle_format)
        
        row = 5
        worksheet.merge_range(f'A{row}:B{row}', 'Identificación', header_format)
        worksheet.merge_range(f'C{row}:E{row}', 'Valor', header_format)
        row += 1
        worksheet.merge_range(f'A{row}:B{row}', 'Empleado', label_format)
        worksheet.merge_range(f'C{row}:E{row}', employee.name, data_format)
        row += 1
        worksheet.merge_range(f'A{row}:B{row}', 'Identificación', label_format)
        worksheet.merge_range(f'C{row}:E{row}', employee.identification_id, data_format)
        row += 1
        worksheet.merge_range(f'A{row}:B{row}', 'Fecha de cálculo', label_format)
        worksheet.merge_range(f'C{row}:E{row}', self.last_rtf_calculation.strftime('%d/%m/%Y') if self.last_rtf_calculation else '', data_format)
        row += 1
        
        period_text = 'Primer Semestre (Dic-May)' if self.rtf_current_period == '1' else 'Segundo Semestre (Jun-Nov)'
        worksheet.merge_range(f'A{row}:B{row}', 'Periodo de cálculo', label_format)
        worksheet.merge_range(f'C{row}:E{row}', period_text, data_format)
        row += 1
        worksheet.merge_range(f'A{row}:B{row}', 'Fecha inicio', label_format)
        worksheet.merge_range(f'C{row}:E{row}', self.rtf_date_from.strftime('%d/%m/%Y') if self.rtf_date_from else '', data_format)
        row += 1
        worksheet.merge_range(f'A{row}:B{row}', 'Fecha fin', label_format)
        worksheet.merge_range(f'C{row}:E{row}', self.rtf_date_to.strftime('%d/%m/%Y') if self.rtf_date_to else '', data_format)
        row += 1
        
        annual_parameters = self.env['hr.annual.parameters'].search([
            ('year', '=', self.rtf_date_to.year)
        ], limit=1)
        
        worksheet.merge_range(f'A{row}:B{row}', 'UVT', label_format)
        worksheet.merge_range(f'C{row}:E{row}', f"{annual_parameters.value_uvt:,.2f}", currency_format)
        row += 1
        worksheet.merge_range(f'A{row}:B{row}', 'SMMLV', label_format)
        worksheet.merge_range(f'C{row}:E{row}', f"{annual_parameters.smmlv_monthly:,.2f}", currency_format)
        row += 1
        worksheet.merge_range(f'A{row}:B{row}', 'Porcentaje Retención', label_format)
        worksheet.merge_range(f'C{row}:E{row}', f"{self.rtf_rate:.2f}%", data_format)
        row += 2
        
        domain = [
            ('contract_id', '=', self.id),
            ('calculation_period', '=', self.rtf_current_period)
        ]
        
        base_uvt_log = self.env['hr.contract.rtf.log'].search(
            domain + [('concept_code', '=', 'BASE_UVT')],
            limit=1
        )
        
        base_uvt = base_uvt_log.value_float if base_uvt_log else 0
        
        rango_uvt = "No aplica"
        tarifa_aplicada = 0
        resta_uvt = 0
        suma_uvt = 0
        
        tabla_retencion = [
            (0, 95, 0, 0, 0),
            (95, 150, 19, 95, 0),
            (150, 360, 28, 150, 10),
            (360, 640, 33, 360, 69),
            (640, 945, 35, 640, 162),
            (945, 2300, 37, 945, 268),
            (2300, float('inf'), 39, 2300, 770)
        ]
        
        for desde, hasta, tarifa, resta, suma in tabla_retencion:
            if desde <= base_uvt < hasta:
                rango_uvt = f"Entre {desde} y {hasta} UVT"
                tarifa_aplicada = tarifa
                resta_uvt = resta
                suma_uvt = suma
                break
        
        worksheet.merge_range(f'A{row}:O{row}', 'INFORMACIÓN DEL RANGO UVT APLICADO', subtitle_format)
        row += 1
        
        worksheet.merge_range(f'A{row}:B{row}', 'Base mensual en UVT', label_format)
        worksheet.merge_range(f'C{row}:E{row}', f"{base_uvt:.2f}", data_format)
        row += 1
        
        worksheet.merge_range(f'A{row}:B{row}', 'Rango aplicable', label_format)
        worksheet.merge_range(f'C{row}:E{row}', rango_uvt, data_format)
        row += 1
        
        worksheet.merge_range(f'A{row}:B{row}', 'Tarifa marginal', label_format)
        worksheet.merge_range(f'C{row}:E{row}', f"{tarifa_aplicada}%", data_format)
        row += 1
        
        formula_text = "No aplica (ingresos exentos)"
        if tarifa_aplicada > 0:
            if suma_uvt > 0:
                formula_text = f"[(Base en UVT - {resta_uvt} UVT) X {tarifa_aplicada}%] + {suma_uvt} UVT"
            else:
                formula_text = f"(Base en UVT - {resta_uvt} UVT) X {tarifa_aplicada}%"
        
        worksheet.merge_range(f'A{row}:B{row}', 'Fórmula aplicada', label_format)
        worksheet.merge_range(f'C{row}:J{row}', formula_text, info_format)
        row += 2
        
        base_retribucion = self.wage
        
        aplica_fondos = base_retribucion > (annual_parameters.smmlv_monthly * 4)
        
        worksheet.merge_range(f'A{row}:O{row}', 'INFORMACIÓN DE FONDOS ESPECIALES', subtitle_format)
        row += 1
        
        if aplica_fondos:
            porcentaje_solidaridad = 0.005
            valor_solidaridad = base_retribucion * porcentaje_solidaridad
            
            porcentaje_subsistencia = 0.0
            if base_retribucion <= 4 * annual_parameters.smmlv_monthly:
                porcentaje_subsistencia = 0.0
            elif base_retribucion <= 16 * annual_parameters.smmlv_monthly:
                porcentaje_subsistencia = 0.005
            elif base_retribucion <= 17 * annual_parameters.smmlv_monthly:
                porcentaje_subsistencia = 0.007
            elif base_retribucion <= 18 * annual_parameters.smmlv_monthly:
                porcentaje_subsistencia = 0.009
            elif base_retribucion <= 19 * annual_parameters.smmlv_monthly:
                porcentaje_subsistencia = 0.011
            elif base_retribucion <= 20 * annual_parameters.smmlv_monthly:
                porcentaje_subsistencia = 0.013
            else:
                porcentaje_subsistencia = 0.015
                
            valor_subsistencia = base_retribucion * porcentaje_subsistencia
            
            worksheet.merge_range(f'A{row}:B{row}', 'Salario Base', label_format)
            worksheet.merge_range(f'C{row}:E{row}', base_retribucion, currency_format)
            worksheet.merge_range(f'F{row}:G{row}', 'SMMLV', label_format)
            worksheet.merge_range(f'H{row}:J{row}', annual_parameters.smmlv_monthly, currency_format)
            row += 1
            
            worksheet.merge_range(f'A{row}:B{row}', 'Relación Salarial', label_format)
            worksheet.merge_range(f'C{row}:E{row}', f"{base_retribucion/annual_parameters.smmlv_monthly:.2f} SMMLV", data_format)
            row += 1
            
            worksheet.merge_range(f'A{row}:B{row}', 'Fondo Solidaridad', label_format)
            worksheet.merge_range(f'C{row}:E{row}', valor_solidaridad, currency_format)
            worksheet.merge_range(f'F{row}:G{row}', 'Porcentaje', label_format)
            worksheet.merge_range(f'H{row}:J{row}', 0.5, percent_format)
            row += 1
            
            worksheet.merge_range(f'A{row}:B{row}', 'Fondo Subsistencia', label_format)
            worksheet.merge_range(f'C{row}:E{row}', valor_subsistencia, currency_format)
            worksheet.merge_range(f'F{row}:G{row}', 'Porcentaje', label_format)
            worksheet.merge_range(f'H{row}:J{row}', porcentaje_subsistencia * 100, percent_format)
            row += 1
        else:
            worksheet.merge_range(f'A{row}:J{row}', 'No aplican fondos especiales (salario inferior a 4 SMMLV)', info_format)
            row += 1
        
        row += 1
        
        worksheet.merge_range(f'A{row}:B{row}', 'Concepto', header_format)
        worksheet.write(row-1, 2, 'ENE', header_format)
        worksheet.write(row-1, 3, 'FEB', header_format)
        worksheet.write(row-1, 4, 'MAR', header_format)
        worksheet.write(row-1, 5, 'ABR', header_format)
        worksheet.write(row-1, 6, 'MAY', header_format)
        worksheet.write(row-1, 7, 'JUN', header_format)
        worksheet.write(row-1, 8, 'JUL', header_format)
        worksheet.write(row-1, 9, 'AGO', header_format)
        worksheet.write(row-1, 10, 'SEP', header_format)
        worksheet.write(row-1, 11, 'OCT', header_format)
        worksheet.write(row-1, 12, 'NOV', header_format)
        worksheet.write(row-1, 13, 'DIC', header_format)
        worksheet.write(row-1, 14, 'TOTAL', header_format)
        row += 1
        
        worksheet.merge_range(f'A{row}:O{row}', 'INGRESOS', subtitle_format)
        row += 1
        
        income_logs = self.env['hr.contract.rtf.log'].search(
            domain + [('concept_type', '=', 'income')],
            order='sequence, id'
        )
        
        monthly_income_totals = {month: 0 for month in range(1, 13)}
        
        for log in income_logs:
            worksheet.merge_range(f'A{row}:B{row}', log.name, label_format)
            
            if log.january != 0:
                worksheet.write(row-1, 2, log.january, income_format)
                monthly_income_totals[1] += log.january
            if log.february != 0:
                worksheet.write(row-1, 3, log.february, income_format)
                monthly_income_totals[2] += log.february
            if log.march != 0:
                worksheet.write(row-1, 4, log.march, income_format)
                monthly_income_totals[3] += log.march
            if log.april != 0:
                worksheet.write(row-1, 5, log.april, income_format)
                monthly_income_totals[4] += log.april
            if log.may != 0:
                worksheet.write(row-1, 6, log.may, income_format)
                monthly_income_totals[5] += log.may
            if log.june != 0:
                worksheet.write(row-1, 7, log.june, income_format)
                monthly_income_totals[6] += log.june
            if log.july != 0:
                worksheet.write(row-1, 8, log.july, income_format)
                monthly_income_totals[7] += log.july
            if log.august != 0:
                worksheet.write(row-1, 9, log.august, income_format)
                monthly_income_totals[8] += log.august
            if log.september != 0:
                worksheet.write(row-1, 10, log.september, income_format)
                monthly_income_totals[9] += log.september
            if log.october != 0:
                worksheet.write(row-1, 11, log.october, income_format)
                monthly_income_totals[10] += log.october
            if log.november != 0:
                worksheet.write(row-1, 12, log.november, income_format)
                monthly_income_totals[11] += log.november
            if log.december != 0:
                worksheet.write(row-1, 13, log.december, income_format)
                monthly_income_totals[12] += log.december
            
            worksheet.write(row-1, 14, log.value_float, income_format)
            row += 1
                
        income_total = sum(log.value_float for log in income_logs)
        worksheet.merge_range(f'A{row}:B{row}', 'TOTAL INGRESOS', label_format)
        
        for month in range(1, 13):
            if monthly_income_totals[month] > 0:
                worksheet.write(row-1, month + 1, monthly_income_totals[month], summary_format)
        
        worksheet.write(row-1, 14, income_total, summary_format)
        row += 2
        
        worksheet.merge_range(f'A{row}:O{row}', 'INGRESOS NO CONSTITUTIVOS DE RENTA', subtitle_format)
        row += 1
        
        deduction_logs = self.env['hr.contract.rtf.log'].search(
            domain + [('concept_type', '=', 'deduction')],
            order='sequence, id'
        )
        
        monthly_deduction_totals = {month: 0 for month in range(1, 13)}
        
        for log in deduction_logs:
            worksheet.merge_range(f'A{row}:B{row}', log.name, label_format)
            
            if log.january != 0:
                worksheet.write(row-1, 2, log.january, deduction_format)
                monthly_deduction_totals[1] += log.january
            if log.february != 0:
                worksheet.write(row-1, 3, log.february, deduction_format)
                monthly_deduction_totals[2] += log.february
            if log.march != 0:
                worksheet.write(row-1, 4, log.march, deduction_format)
                monthly_deduction_totals[3] += log.march
            if log.april != 0:
                worksheet.write(row-1, 5, log.april, deduction_format)
                monthly_deduction_totals[4] += log.april
            if log.may != 0:
                worksheet.write(row-1, 6, log.may, deduction_format)
                monthly_deduction_totals[5] += log.may
            if log.june != 0:
                worksheet.write(row-1, 7, log.june, deduction_format)
                monthly_deduction_totals[6] += log.june
            if log.july != 0:
                worksheet.write(row-1, 8, log.july, deduction_format)
                monthly_deduction_totals[7] += log.july
            if log.august != 0:
                worksheet.write(row-1, 9, log.august, deduction_format)
                monthly_deduction_totals[8] += log.august
            if log.september != 0:
                worksheet.write(row-1, 10, log.september, deduction_format)
                monthly_deduction_totals[9] += log.september
            if log.october != 0:
                worksheet.write(row-1, 11, log.october, deduction_format)
                monthly_deduction_totals[10] += log.october
            if log.november != 0:
                worksheet.write(row-1, 12, log.november, deduction_format)
                monthly_deduction_totals[11] += log.november
            if log.december != 0:
                worksheet.write(row-1, 13, log.december, deduction_format)
                monthly_deduction_totals[12] += log.december
                
            worksheet.write(row-1, 14, log.value_float, deduction_format)
            row += 1
                
        deduction_total = sum(log.value_float for log in deduction_logs)
        worksheet.merge_range(f'A{row}:B{row}', 'TOTAL INGRESOS NO CONSTITUTIVOS', label_format)
        
        for month in range(1, 13):
            if monthly_deduction_totals[month] > 0:
                worksheet.write(row-1, month + 1, monthly_deduction_totals[month], summary_format)
                
        worksheet.write(row-1, 14, deduction_total, summary_format)
        row += 2
        
        worksheet.merge_range(f'A{row}:O{row}', 'RENTAS EXENTAS', subtitle_format)
        row += 1
        
        exempt_logs = self.env['hr.contract.rtf.log'].search(
            domain + [('concept_type', '=', 'exempt')],
            order='sequence, id'
        )
        
        monthly_exempt_totals = {month: 0 for month in range(1, 13)}
        
        for log in exempt_logs:
            worksheet.merge_range(f'A{row}:B{row}', log.name, label_format)
            
            if log.january != 0:
                worksheet.write(row-1, 2, log.january, exempt_format)
                monthly_exempt_totals[1] += log.january
            if log.february != 0:
                worksheet.write(row-1, 3, log.february, exempt_format)
                monthly_exempt_totals[2] += log.february
            if log.march != 0:
                worksheet.write(row-1, 4, log.march, exempt_format)
                monthly_exempt_totals[3] += log.march
            if log.april != 0:
                worksheet.write(row-1, 5, log.april, exempt_format)
                monthly_exempt_totals[4] += log.april
            if log.may != 0:
                worksheet.write(row-1, 6, log.may, exempt_format)
                monthly_exempt_totals[5] += log.may
            if log.june != 0:
                worksheet.write(row-1, 7, log.june, exempt_format)
                monthly_exempt_totals[6] += log.june
            if log.july != 0:
                worksheet.write(row-1, 8, log.july, exempt_format)
                monthly_exempt_totals[7] += log.july
            if log.august != 0:
                worksheet.write(row-1, 9, log.august, exempt_format)
                monthly_exempt_totals[8] += log.august
            if log.september != 0:
                worksheet.write(row-1, 10, log.september, exempt_format)
                monthly_exempt_totals[9] += log.september
            if log.october != 0:
                worksheet.write(row-1, 11, log.october, exempt_format)
                monthly_exempt_totals[10] += log.october
            if log.november != 0:
                worksheet.write(row-1, 12, log.november, exempt_format)
                monthly_exempt_totals[11] += log.november
            if log.december != 0:
                worksheet.write(row-1, 13, log.december, exempt_format)
                monthly_exempt_totals[12] += log.december
                
            worksheet.write(row-1, 14, log.value_float, exempt_format)
            row += 1
                
        exempt_total = sum(log.value_float for log in exempt_logs)
        worksheet.merge_range(f'A{row}:B{row}', 'TOTAL RENTAS EXENTAS', label_format)
        
        for month in range(1, 13):
            if monthly_exempt_totals[month] > 0:
                worksheet.write(row-1, month + 1, monthly_exempt_totals[month], summary_format)
                
        worksheet.write(row-1, 14, exempt_total, summary_format)
        row += 2
        
        worksheet.merge_range(f'A{row}:O{row}', 'CÁLCULO FINAL', subtitle_format)
        row += 1
        
        summary_logs = self.env['hr.contract.rtf.log'].search(
            domain + [('concept_type', '=', 'summary')],
            order='sequence, id'
        )
        
        for log in summary_logs:
            worksheet.merge_range(f'A{row}:B{row}', log.name, label_format)
            worksheet.merge_range(f'C{row}:N{row}', '', data_format)
            display_value = log.value if log.concept_code in ['FECHA_INICIO', 'FECHA_FIN', 'DIAS', 'UVT', 'PORC_RET'] else log.value_float
            worksheet.write(row-1, 14, display_value, summary_format)
            row += 1
        
        row += 2
        worksheet.merge_range(f'A{row}:O{row}', 'PROYECCIÓN DE RETENCIÓN PARA LOS SIGUIENTES MESES', subtitle_format)
        row += 1
        
        worksheet.merge_range(f'A{row}:B{row}', 'Mes', header_format)
        worksheet.merge_range(f'C{row}:E{row}', 'Ingreso Base', header_format)
        worksheet.merge_range(f'F{row}:H{row}', 'Retención Proyectada', header_format)
        worksheet.merge_range(f'I{row}:K{row}', 'Porcentaje', header_format)
        row += 1
        
        current_month = datetime.now().month
        current_year = datetime.now().year
        
        months_with_data = sum(1 for m in range(1, 13) if monthly_income_totals[m] > 0)
        if months_with_data > 0:
            basic_logs = [log for log in income_logs if 'Salario' in log.name]
            comision_logs = [log for log in income_logs if 'Comisiones' in log.name]
            other_income_logs = [log for log in income_logs 
                                if 'Salario' not in log.name and 'Comisiones' not in log.name]
            
            avg_basic = sum(log.value_float for log in basic_logs) / months_with_data if basic_logs else self.wage
            avg_comisiones = sum(log.value_float for log in comision_logs) / months_with_data if comision_logs else 0
            avg_other_income = sum(log.value_float for log in other_income_logs) / months_with_data if other_income_logs else 0
            
            avg_basic = max(avg_basic, self.wage)
            
            avg_deducciones = deduction_total / months_with_data
            avg_exenciones = exempt_total / months_with_data
        else:
            avg_basic = self.wage
            avg_comisiones = 0
            avg_other_income = 0
            avg_deducciones = 0
            avg_exenciones = 0
        
        projected_monthly_income = avg_basic + avg_comisiones + avg_other_income
        
        if aplica_fondos:
            projected_solidaridad = projected_monthly_income * porcentaje_solidaridad
            projected_subsistencia = projected_monthly_income * porcentaje_subsistencia
            projected_salud = projected_monthly_income * 0.04
            projected_pension = projected_monthly_income * 0.04
            projected_deducciones = projected_salud + projected_pension + projected_solidaridad + projected_subsistencia + avg_deducciones
        else:
            projected_salud = projected_monthly_income * 0.04
            projected_pension = projected_monthly_income * 0.04
            projected_deducciones = projected_salud + projected_pension + avg_deducciones
        
        for i in range(6):
            proj_month = (current_month + i) % 12
            if proj_month == 0:
                proj_month = 12
            proj_year = current_year + ((current_month + i) // 12)
            
            month_name = {
                1: 'Enero', 2: 'Febrero', 3: 'Marzo', 4: 'Abril', 5: 'Mayo', 6: 'Junio',
                7: 'Julio', 8: 'Agosto', 9: 'Septiembre', 10: 'Octubre', 11: 'Noviembre', 12: 'Diciembre'
            }[proj_month]
            
            base_proyectada = projected_monthly_income - projected_deducciones
            proj_retention = base_proyectada * (self.rtf_rate / 100)
            
            worksheet.merge_range(f'A{row}:B{row}', f'{month_name} {proj_year}', label_format)
            worksheet.merge_range(f'C{row}:E{row}', projected_monthly_income, currency_format)
            worksheet.merge_range(f'F{row}:H{row}', proj_retention, currency_format)
            worksheet.merge_range(f'I{row}:K{row}', self.rtf_rate / 100, percent_format)
            row += 1
        
        row += 2
        worksheet.merge_range(f'A{row}:E{row}', 'PORCENTAJES DE RETENCIÓN', subtitle_format)
        row += 1
        worksheet.merge_range(f'A{row}:C{row}', 'PRIMER SEMESTRE', header_format)
        worksheet.merge_range(f'D{row}:E{row}', 'SEGUNDO SEMESTRE', header_format)
        row += 1
        first_semester = f"{self.rtf_rate_first_semester}%"
        second_semester = f"{self.rtf_rate_second_semester}%"
        worksheet.merge_range(f'A{row}:C{row}', first_semester, data_format)
        worksheet.merge_range(f'D{row}:E{row}', second_semester, data_format)
        
        worksheet.set_column('A:B', 20)
        worksheet.set_column('C:N', 12)
        worksheet.set_column('O:O', 15)
        
        workbook.close()
        excel_data = base64.b64encode(output.getvalue())
        return excel_data
    
    def action_auto_date_first_semester(self):
        """Configura automáticamente fechas para primer semestre"""
        for contract in self:
            today = fields.Date.today()
            if today.month <= 5:
                year = today.year - 1
            else:
                year = today.year
                
            contract.rtf_date_from = date(year, 12, 1)
            contract.rtf_date_to = date(year + 1, 5, 31)
            contract.rtf_current_period = '1'
            
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Información',
                'message': 'Fechas para primer semestre configuradas',
                'type': 'info',
                'sticky': False,
            }
        }
    
    def action_auto_date_second_semester(self):
        """Configura automáticamente fechas para segundo semestre"""
        for contract in self:
            today = fields.Date.today()
            if today.month <= 11 and today.month >= 6:
                year = today.year
            else:
                year = today.year - 1
                
            contract.rtf_date_from = date(year, 6, 1)
            contract.rtf_date_to = date(year, 11, 30)
            contract.rtf_current_period = '2'
            
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Información',
                'message': 'Fechas para segundo semestre configuradas',
                'type': 'info',
                'sticky': False,
            }
        }


    def action_generate_excel(self):
        """Genera el archivo Excel con el reporte de retención"""
        self.ensure_one()
        
        # Verificar que existan datos de RTF
        if not self.rtf_log:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Advertencia',
                    'message': 'Debe calcular la retención primero',
                    'type': 'warning',
                    'sticky': False,
                }
            }
        
        # Generar el Excel
        excel_data = self._generate_excel_report()
        filename = f"Retención_{self.employee_id.name}_{datetime.now().strftime('%Y%m%d')}.xlsx"
        
        self.write({
            'excel_file': excel_data,
            'excel_filename': filename
        })
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Éxito',
                'message': 'Excel generado correctamente',
                'type': 'success',
                'sticky': False,
            }
        }
       
    @api.depends('date_start', 'date_end')
    def _compute_contract_progress(self):
        today = fields.Date.today()
        for contract in self:
            if not contract.date_end:
                contract.contract_progress = 0
                contract.contract_color = ''
                continue

            total_days = (contract.date_end - contract.date_start).days
            days_left = (contract.date_end - today).days

            if days_left <= 0:
                contract.contract_progress = 100
                contract.contract_color = 'bg-danger'
            else:
                progress = ((total_days - days_left) / total_days) * 100
                contract.contract_progress = min(max(progress, 0), 100)
                
                if days_left <= 30:
                    contract.contract_color = 'bg-warning'
                else:
                    contract.contract_color = 'bg-success'    
                
    def days_between(self,start_date,end_date):
        s1, e1 =  start_date , end_date + timedelta(days=1)
        #Convert to 360 days
        s360 = (s1.year * 12 + s1.month) * 30 + s1.day
        e360 = (e1.year * 12 + e1.month) * 30 + e1.day
        #Count days between the two 360 dates and return tuple (months, days)
        res = divmod(e360 - s360, 30)
        return ((res[0] * 30) + res[1]) or 0

    def get_holiday_book(self, date_ref=False):
        for rec in self:
            date_ref = rec.date_ref_holiday_book or fields.Date.context_today(rec)
            current_date = rec.date_start
            all_holiday_records = []
            total_vacation_days = (rec.days_between(current_date, date_ref) * 15) / 360
            unused_vacation_days = rec.days_left
            used_vacation_days = 0
            days_total = total_vacation_days
            while current_date <= date_ref and used_vacation_days < (total_vacation_days - unused_vacation_days):
                next_year_date = rec.add_one_year(current_date)
                #if next_year_date > date_ref:
                #    next_year_date = date_ref


                worked_days = rec.days_between(current_date, next_year_date)
                annual_vacation_entitlement = worked_days * 15 / 360

                # Ajustar los días utilizados para no exceder el límite
                if used_vacation_days + annual_vacation_entitlement > (total_vacation_days - unused_vacation_days):
                    annual_vacation_entitlement = (total_vacation_days - unused_vacation_days) - used_vacation_days
                    next_year_date = rec.calculate_adjusted_final_date(current_date, annual_vacation_entitlement)
                
                used_vacation_days += annual_vacation_entitlement

                holiday_record = {
                    'employee_id': self.employee_id.id,
                    'initial_accrual_date': current_date,
                    'final_accrual_date': next_year_date - timedelta(days=1),
                    'contract_id': self.id,
                    'business_units': round(annual_vacation_entitlement),
                    'description': 'Saldo Inicial',
                }
                all_holiday_records.append(holiday_record)
                current_date = next_year_date

            self.env['hr.vacation'].create(all_holiday_records)

    def calculate_adjusted_final_date(self, start_date, vacation_days):
        current_date = start_date
        while vacation_days > 0:
            current_date += timedelta(days=1)
            if self.is_business_day(current_date):
                vacation_days -= 1
        return current_date

    def is_business_day(self, date):
        return date.weekday() < 5  
    
    def add_one_year(self, date):
        try:
            return date.replace(year=date.year + 1)
        except ValueError:  
            return date.replace(year=date.year + 1, month=date.month + 1, day=1)

    @api.onchange('date_end', 'contract_days', 'date_start')
    def _compute_contract_days(self):

        def monthdelta(d1, d2):
            delta = 0
            while True:
                mdays = monthrange(d1.year, d1.month)[1]
                d1 += timedelta(days=mdays)
                if d1 <= d2:
                    delta += 1
                else:
                    break
            return delta

        if 'field_onchange' in self.env.context and self.env.context['field_onchange'] == 'contract_days':
            if self.contract_days > 0:
                months = int(self.contract_days / 30)
                days = self.contract_days - (30 * months)
                start = fields.Date.from_string(self.date_start)
                date_end = start + relativedelta(months=months) + relativedelta(days=days)
                self.date_end = fields.Date.to_string(date_end)
            else:
                self.date_end = False

        elif 'field_onchange' in self.env.context and self.env.context['field_onchange'] == 'date_start':
            self.date_end, self.contract_days = False, False

        else:
            if self.date_end:
                month = monthdelta(fields.Date.from_string(self.date_start),
                                   fields.Date.from_string(self.date_end))
                end = int(self.date_end.day)
                start = int(self.date_start.day)
                if start > end:
                    days = (30 - int(start) + int(end))
                else:
                    days = int(end) - int(start)
                self.contract_days = 0
                self.contract_days = month * 30 + days
            else:
                self.contract_days = 0


    @api.onchange('date_end', 'contract_days', 'date_start')
    def _compute_contract_days(self):

        def monthdelta(d1, d2):
            delta = 0
            while True:
                mdays = monthrange(d1.year, d1.month)[1]
                d1 += timedelta(days=mdays)
                if d1 <= d2:
                    delta += 1
                else:
                    break
            return delta

        if 'field_onchange' in self.env.context and self.env.context['field_onchange'] == 'contract_days':
            if self.contract_days > 0:
                months = int(self.contract_days / 30)
                days = self.contract_days - (30 * months)
                start = fields.Date.from_string(self.date_start)
                date_end = start + relativedelta(months=months) + relativedelta(days=days)
                self.date_end = fields.Date.to_string(date_end)
            else:
                self.date_end = False

        elif 'field_onchange' in self.env.context and self.env.context['field_onchange'] == 'date_start':
            self.date_end, self.contract_days = False, False

        else:
            if self.date_end:
                month = monthdelta(fields.Date.from_string(self.date_start),
                                   fields.Date.from_string(self.date_end))
                end = int(self.date_end.day)
                start = int(self.date_start.day)
                if start > end:
                    days = (30 - int(start) + int(end))
                else:
                    days = int(end) - int(start)
                self.contract_days = 0
                self.contract_days = month * 30 + days
            else:
                self.contract_days = 0

    def get_calcula_rtefte_ordinaria(self, base_rtefte_uvt):
        res_initial = self.env['hr.calculation.rtefte.ordinary'].search([('range_initial', '<=', base_rtefte_uvt)])
        max_value = 0
        for i in res_initial:
            if i.range_finally > max_value:
                max_value = i.range_finally                
        res = self.env['hr.calculation.rtefte.ordinary'].search([('range_initial', '<=', base_rtefte_uvt),('range_finally', '=', max_value)])
        return res 
    
    def get_contract_deductions_rtf(self, contract_id,code):
        res = self.env['hr.contract.deductions.rtf'].search([('contract_id', '=', contract_id),('input_id.code','=',code)])
        return res

   
    def create_payslip_reliquidation(self):
        """
        Funcion de reliquidar contratos
        """
        payslip_type_liq = self.env['hr.payroll.structure'].search([('process','=','contrato')])
        
        if not payslip_type_liq:
            raise UserError('Debe configurar en los tipos de nomina, un tipo con el codigo <Liquidacion>')
        elif len(payslip_type_liq) > 1:
            raise UserError('Se encontraron {N} tipos de nomina con el codigo <Liquidacion>'.format(N=len(payslip_type_liq)))
        
        new_payslip_ids = []
        for contract in self:
            payslips_ids = self.env['hr.payslip'].search([('contract_id','=',contract.id),('tipo_nomina','=',payslip_type_liq.id)])
            no_done_payslips = [p for p in payslips_ids if p.state != 'done']

            if not payslips_ids:
                raise UserError('Debe crear primero una nomina de tipo <Liquidacion> para el contrato {C}'.format(C=contract.name))
            elif no_done_payslips:
                raise UserError('Este proceso se debe hacer unicamente para ajustar la nomina de tipo <Liquidacion> que ya esta causada. Se encontraron las nominas {N} de tipo <Liquidacion> en estado {E}'.format(N=[p.number for p in no_done_payslips], E=[p.state for p in no_done_payslips]))
            

            if not (contract.employee_id and payslips_ids.journal_id):
                message = 'Del contrato {C} la siguiente informacion es errónea\n'.format(C=contract.name)
                message += '    -Empleado = {E}\n'.format(E=contract.employee_id.name if contract.employee_id else False)
                message += '    -Diario de Salarios = {L}\n'.format(L=contract.journal_id.name if contract.journal_id else False)
                raise UserError(message)
            
            notes = 'Reliquidacion de {E}\n'.format(E=contract.employee_id.name)
            notes += 'Inicio de contrato = {F}\n'.format(F=contract.date_start)
            notes += 'Fin de contrato = {F}\n'.format(F=contract.date_end)
            notes += 'Dias de contrato = {D}\n'.format(D=contract.contract_days)
            
            new_payslip = {
                'employee_id': contract.employee_id.id,
                'payslip_period_id': contract.payslip_period_id.id,
                'contract_id': contract.id,
                'name': '',
                'note': notes,
                'contract_create': True,
                'liquidacion_date': contract.payslip_period_id.end_date,
                'journal_id': contract.journal_id.id,
                'tipo_nomina': payslip_type_liq.id,
            }
            new_payslip_id = self.env['hr.payslip'].create(new_payslip)
            new_payslip_id.compute_sheet()            
            new_payslip_ids.append(new_payslip_id.id)
        
        return {
            'type': 'ir.actions.act_window',
            'view_type': 'form',
            'view_mode': 'tree,form',
            'res_model': 'hr.payslip',
            'target': 'current',
            'context': {},
            'domain': [('id','in',new_payslip_ids)],
        }
        
    def get_info_book_vacation(self):
        return self.env['hr.vacation'].search([('contract_id','=',self.id)])

    def get_accumulated_vacation_days(self,ignore_payslip_id=0,method_old=0):
        date_start = self.date_start
        date_end = self.retirement_date if self.retirement_date else datetime.now().date()
        employee_id = self.employee_id.id
        if method_old != 0:
            #------------------ CALCULO ANTIGUO------------------------------------
            days_service = self.dias360(date_start, date_end)
            days_unpaid_absences = sum([i.number_of_days for i in self.env['hr.leave'].search(
                [('date_from', '>=', date_start), ('date_to', '<=', date_end),
                 ('state', '=', 'validate'), ('employee_id', '=', employee_id),
                 ('unpaid_absences', '=', True)])])
            days_unpaid_absences += sum([i.days for i in self.env['hr.absence.history'].search(
                [('star_date', '>=', date_start), ('end_date', '<=', date_end),
                 ('employee_id', '=', employee_id), ('leave_type_id.unpaid_absences', '=', True)])])
            days_vacations_total = ((days_service - days_unpaid_absences) * 15) / 360
            if ignore_payslip_id == 0:
                days_paid = sum([i.business_units+i.units_of_money for i in self.env['hr.vacation'].search([('contract_id', '=', self.id)])])
            else:
                days_paid = sum([i.business_units + i.units_of_money for i in
                                 self.env['hr.vacation'].search([('contract_id', '=', self.id),('payslip','!=',ignore_payslip_id)])])
            #Dias faltantes por disfrutar
            days_vacations = round(days_vacations_total - days_paid,2)
        else:
            # ------------------ NUEVO CALCULO------------------------------------
            date_vacation = date_start
            if ignore_payslip_id == 0:
                obj_vacation = self.env['hr.vacation'].search([('employee_id', '=', employee_id), ('contract_id', '=', self.id)])
            else:
                obj_vacation = self.env['hr.vacation'].search([('employee_id', '=', employee_id), ('contract_id', '=', self.id),('payslip','!=',ignore_payslip_id)])
            if obj_vacation:
                for history in sorted(obj_vacation, key=lambda x: x.final_accrual_date):
                    if history.leave_id:
                        if history.leave_id.holiday_status_id.unpaid_absences == False:
                            date_vacation = history.final_accrual_date + timedelta(days=1) if history.final_accrual_date > date_vacation else date_vacation
                    else:
                        date_vacation = history.final_accrual_date + timedelta(days=1) if history.final_accrual_date > date_vacation else date_vacation

            dias_trabajados = self.dias360(date_vacation, date_end)
            dias_ausencias = sum([i.number_of_days for i in self.env['hr.leave'].search(
                [('date_from', '>=', date_vacation), ('date_to', '<=', date_end),
                 ('state', '=', 'validate'), ('employee_id', '=', employee_id),
                 ('unpaid_absences', '=', True)])])
            dias_ausencias += sum([i.days for i in self.env['hr.absence.history'].search(
                [('star_date', '>=', date_vacation), ('end_date', '<=', date_end),
                 ('employee_id', '=', employee_id), ('leave_type_id.unpaid_absences', '=', True)])])
            days_vacations = ((dias_trabajados - dias_ausencias) * 15) / 360
        return days_vacations


    def validate_and_set_accrual_dates(self, vacation_record):
        """
        Método para validar fechas de causación desde el contrato
        """
        if not vacation_record.initial_accrual_date or not vacation_record.final_accrual_date:
            start_date = self.date_start
            
            last_vacation = self.env['hr.vacation'].search([
                ('employee_id', '=', vacation_record.employee_id.id),
                ('id', '!=', vacation_record.id),
                ('final_accrual_date', '!=', False),
                ('departure_date', '<', vacation_record.departure_date or fields.Date.today())
            ], order='final_accrual_date desc', limit=1)
            
            if last_vacation:
                start_date = max(last_vacation.final_accrual_date + timedelta(days=1), self.date_start)
            
            dias_trabajados = vacation_record.business_units + vacation_record.units_of_money if vacation_record.business_units else 15
            
            from decimal import Decimal, ROUND_HALF_UP
            dias_equiv = ((Decimal(dias_trabajados) * Decimal(365)) / Decimal(15))
            dias_equiv = int(dias_equiv.quantize(0, rounding=ROUND_HALF_UP))
            
            end_date = start_date + timedelta(days=dias_equiv - 1)
            
            vacation_record.write({
                'initial_accrual_date': start_date,
                'final_accrual_date': end_date,
                'contract_id': self.id,
            })
    
    def get_accumulated_vacation_days(self, ignore_payslip_id=0, method_old=0):
        """
        Calcula los días de vacaciones acumulados validando las fechas de causación
        """
        date_start = self.date_start
        date_end = self.retirement_date if self.retirement_date else datetime.now().date()
        employee_id = self.employee_id.id
        
        vacation_records = self.env['hr.vacation'].search([
            ('employee_id', '=', employee_id),
            ('contract_id', '=', self.id)
        ])
        
        for vacation in vacation_records:
            if not vacation.initial_accrual_date or not vacation.final_accrual_date:
                self.validate_and_set_accrual_dates(vacation)
        
        if method_old != 0:
            #------------------ CALCULO ANTIGUO------------------------------------
            days_service = self.dias360(date_start, date_end)
            days_unpaid_absences = sum([i.number_of_days for i in self.env['hr.leave'].search(
                [('date_from', '>=', date_start), ('date_to', '<=', date_end),
                 ('state', '=', 'validate'), ('employee_id', '=', employee_id),
                 ('unpaid_absences', '=', True)])])
            days_unpaid_absences += sum([i.days for i in self.env['hr.absence.history'].search(
                [('star_date', '>=', date_start), ('end_date', '<=', date_end),
                 ('employee_id', '=', employee_id), ('leave_type_id.unpaid_absences', '=', True)])])
            days_vacations_total = ((days_service - days_unpaid_absences) * 15) / 360
            
            if ignore_payslip_id == 0:
                days_paid = sum([i.business_units+i.units_of_money for i in self.env['hr.vacation'].search([('contract_id', '=', self.id)])])
            else:
                days_paid = sum([i.business_units + i.units_of_money for i in
                                 self.env['hr.vacation'].search([('contract_id', '=', self.id),('payslip','!=',ignore_payslip_id)])])
            
            days_vacations = round(days_vacations_total - days_paid, 2)
        else:
            # ------------------ NUEVO CALCULO------------------------------------
            date_vacation = date_start
            if ignore_payslip_id == 0:
                obj_vacation = self.env['hr.vacation'].search([('employee_id', '=', employee_id), ('contract_id', '=', self.id)])
            else:
                obj_vacation = self.env['hr.vacation'].search([('employee_id', '=', employee_id), ('contract_id', '=', self.id),('payslip','!=',ignore_payslip_id)])
            
            if obj_vacation:
                for history in sorted(obj_vacation, key=lambda x: x.final_accrual_date or date_start):
                    if history.final_accrual_date:  # Solo si tiene fecha de causación válida
                        if history.leave_id:
                            if history.leave_id.holiday_status_id.unpaid_absences == False:
                                date_vacation = history.final_accrual_date + timedelta(days=1) if history.final_accrual_date > date_vacation else date_vacation
                        else:
                            date_vacation = history.final_accrual_date + timedelta(days=1) if history.final_accrual_date > date_vacation else date_vacation
             
            dias_trabajados = self.dias360(date_vacation, date_end)
            dias_ausencias = sum([i.number_of_days for i in self.env['hr.leave'].search(
                [('date_from', '>=', date_vacation), ('date_to', '<=', date_end),
                 ('state', '=', 'validate'), ('employee_id', '=', employee_id),
                 ('unpaid_absences', '=', True)])])
            dias_ausencias += sum([i.days for i in self.env['hr.absence.history'].search(
                [('star_date', '>=', date_vacation), ('end_date', '<=', date_end),
                 ('employee_id', '=', employee_id), ('leave_type_id.unpaid_absences', '=', True)])])
            days_vacations = ((dias_trabajados - dias_ausencias) * 15) / 360
        
        return days_vacations


    def get_info_book_cesantias(self):
        return self.env['hr.history.cesantias'].search([('contract_id','=',self.id)])
    
    def get_wage_in_date(self,process_date):
        wage_in_date = self.wage
        for change in sorted(self.change_wage_ids, key=lambda x: x.date_start):
            if process_date >= change.date_start:
                wage_in_date = change.wage
        return wage_in_date


#---------------------- IBC ------------------------>

    def GetIBCSLastMonth(self, date_to, contract_id):
        date_actual = date_to
        month = date_to.month - 1
        year = date_to.year
        if month == 0:
            month = 12
            year -= 1
        day = 30 if month != 2 else 28
        from_date = datetime(year, month, 1).date()
        to_date = datetime(year, month, day).date()
        annual_parameters = self.env['hr.annual.parameters'].search([('year', '=', date_actual.year)])
        PayslipLine = self.env['hr.payslip.line']
        payslip_lines = PayslipLine.search([
            ('slip_id.state', 'in', ['done', 'paid']),
            ('slip_id.contract_id', '=', contract_id.id),
            ('slip_id.date_to', '>', from_date),
            ('slip_id.date_from', '<', to_date),
        ])
        value_base = 0
        base_40 = 0
        value_base_no_dev = 0
        for line in payslip_lines:
            value_base += abs(line.total) if line.salary_rule_id.category_id.code == 'DEV_SALARIAL' or line.salary_rule_id.category_id.parent_id.code == 'DEV_SALARIAL' else 0
            value_base_no_dev += abs(line.total) if line.salary_rule_id.category_id.code == 'DEV_NO_SALARIAL' or line.salary_rule_id.category_id.parent_id.code == 'DEV_NO_SALARIAL' else 0
        gran_total = value_base + value_base_no_dev 
        statute_value = gran_total*(annual_parameters.value_porc_statute_1395/100)
        total_statute = value_base_no_dev-statute_value 
        if total_statute > 0: 
            base_40 = total_statute     
        ibc = value_base + base_40
        # If IBC is not zero, return it
        if ibc:
            return ibc
        # Check for custom IBC (u_ibc) on the contract, if it matches the IBC date
        if contract_id.fecha_ibc and from_date.year == contract_id.fecha_ibc.year and from_date.month == contract_id.fecha_ibc.month:
            return contract_id.u_ibc
        # If no IBC is found, return the contract's wage
        return contract_id.wage


    def MethodAverageAnnual(self,date_to,contract_id, nowage=None, noavg=None):
        """
        Calcula el salario promedio anual para el cálculo de la indemnización.
        @param date_to: Fecha final del periodo.
        @param contract_id: ID del contrato.
        @param nowage: True si no se tiene en cuenta el salario actual para el cálculo del promedio.
        @param noavg: True si se quiere obtener el total y no el promedio.
        @return: Salario promedio anual.
        """
        wage = 0.0
        first_day_of_current_month = date_to.replace(day=1)
        last_day_of_previous_month = first_day_of_current_month - timedelta(days=1)
        to_date = last_day_of_previous_month
        date_start = date_to + relativedelta(months=-11)
        date_from = date(date_start.year,date_start.month,1)
        initial_process_date = contract_id.date_start
        initial_process_date = initial_process_date if date_from < initial_process_date else date_from

        payslips = self.env['hr.payslip.line'].search([('date_from','>=',date_from),('date_from','<',to_date),('employee_id', '=', contract_id.employee_id.id),('category_id.code','=','DEV_SALARIAL')], order="date_from desc")
        hr_accumula = self.env['hr.accumulated.payroll'].search([('date','>=',date_from),('date','<',to_date),('employee_id', '=', contract_id.employee_id.id),('salary_rule_id.category_id.code','=','DEV_SALARIAL')], order="date desc")
        obj_wage = self.env['hr.contract.change.wage'].search([('contract_id', '=', contract_id.id), ('date_start', '>=', initial_process_date), ('date_start', '<=', to_date)])
        dias_trabajados = self.dias360(initial_process_date, to_date)
        dias_ausencias =  sum([i.number_of_days for i in self.env['hr.leave'].search([('date_from','>=',initial_process_date),('date_to','<=',to_date),('state','=','validate'),('employee_id','=',self.employee_id.id),('unpaid_absences','=',True)])])
        dias_ausencias += sum([i.days for i in self.env['hr.absence.history'].search([('star_date', '>=', initial_process_date), ('end_date', '<=', to_date),('employee_id', '=', self.employee_id.id),('leave_type_id.unpaid_absences', '=', True)])])
        dias_liquidacion = dias_trabajados - dias_ausencias
        if len(obj_wage) > 0 and nowage:
            wage_average = 0
            while initial_process_date <= to_date:
                if initial_process_date.day != 31:
                    if initial_process_date.month == 2 and  initial_process_date.day == 28 and (initial_process_date + timedelta(days=1)).day != 29:
                        wage_average += (contract_id.get_wage_in_date(initial_process_date) / 30)*3
                    elif initial_process_date.month == 2 and initial_process_date.day == 29:
                        wage_average += (contract_id.get_wage_in_date(initial_process_date) / 30)*2
                    else:
                        wage_average += contract_id.get_wage_in_date(initial_process_date)/30
                initial_process_date = initial_process_date + timedelta(days=1)
            if dias_trabajados != 0:
                wage = contract_id.wage if wage_average == 0 else (wage_average/dias_trabajados)*30
            else:
                wage = 0
        amount=0
        if payslips:
            for payslip in payslips:
                amount += payslip.total
            if hr_accumula:
                for hr in hr_accumula:
                    amount += hr.amount
                    _logger.info(amount)
            if noavg:
                return (amount+((wage/30)*dias_liquidacion))
            else:
                return ((amount+((wage/30)*dias_liquidacion))/dias_liquidacion)*30
        else:
            return 0

    def mount_rule_before(self, code, from_date, contract_id):
        date_actual = from_date
        month = from_date.month - 1
        year = from_date.year
        if month == 0:
            month = 12
            year -= 1
        day = 30 if month != 2 else 28
        from_date = datetime(year, month, 1).date()
        to_date = datetime(year, month, day).date()
        annual_parameters = self.env['hr.annual.parameters'].search([('year', '=', date_actual.year)])
        PayslipLine = self.env['hr.payslip.line']
        payslip_lines = PayslipLine.search([
            ('slip_id.state', 'in', ['done', 'paid']),
            ('slip_id.contract_id', '=', contract_id.id),
            ('slip_id.date_to', '>', from_date),
            ('slip_id.date_from', '<', to_date),
        ])
        value_base = 0
        base_40 = 0
        value_base_no_dev = 0
        for line in payslip_lines:
            value_base += abs(line.total) if line.salary_rule_id.category_id.code == 'DEV_SALARIAL' or line.salary_rule_id.category_id.parent_id.code == 'DEV_SALARIAL' else 0
            value_base_no_dev += abs(line.total) if line.salary_rule_id.category_id.code == 'DEV_NO_SALARIAL' or line.salary_rule_id.category_id.parent_id.code == 'DEV_NO_SALARIAL' else 0
        gran_total = value_base + value_base_no_dev 
        statute_value = gran_total*(annual_parameters.value_porc_statute_1395/100)
        total_statute = value_base_no_dev-statute_value 
        if total_statute > 0: 
            base_40 = total_statute     
        ibc = value_base + base_40
        if ibc:
            return ibc
        if contract_id.fecha_ibc and from_date.year == contract_id.fecha_ibc.year and from_date.month == contract_id.fecha_ibc.month:
            return contract_id.u_ibc
        return contract_id.wage

    def is_working_day(self, date):
        work_days = [int(x.dayofweek)
                     for x in self.resource_calendar_id.attendance_ids]
        return date.weekday() in work_days


    def has_change_salary(self, date_from, date_to):
        wages_in_period = filter(lambda x: date_from <= x.date_start <= date_to, self.change_wage_ids)
        return len(list(wages_in_period)) >= 1



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

    def calculate_remaining_days(self, ignore_payslip_id=None, method_old=False):
        if self.days_left > 0 and self.date_ref_holiday_book:
            initial_days = self.days_left
            date_start = self.date_ref_holiday_book
        else:
            initial_days = 0
            date_start = self.date_start
        employee_id = self.employee_id.id
        vacation_records = self.env['hr.vacation'].search([
            ('employee_id', '=', employee_id),
            ('contract_id', '=', self.id)
        ])
        
        for vacation in vacation_records:
            if not vacation.initial_accrual_date or not vacation.final_accrual_date:
                self.validate_and_set_accrual_dates(vacation)
        
        date_end = self.retirement_date or fields.Date.today()
        employee_id = self.employee_id.id

        if method_old:
            days_service = self.dias360(date_start, date_end)
            days_unpaid = self.get_unpaid_absences(date_start, date_end, employee_id)
            days_vacations_total = self.calculate_vacation_days(days_service, days_unpaid)
            days_paid = self.get_paid_vacations(self.id, ignore_payslip_id)
            return round(initial_days + days_vacations_total - days_paid, 2)
        else:
            date_vacation = date_start
            domain = [
                ('employee_id', '=', employee_id),
                ('contract_id', '=', self.id)
            ]
            if ignore_payslip_id:
                domain.append(('payslip', '!=', ignore_payslip_id))

            vacation_history = self.env['hr.vacation'].search(domain)

            if vacation_history:
                for history in sorted(vacation_history, key=lambda x: x.final_accrual_date or x.return_date):
                    if history.final_accrual_date and (not history.leave_id or not history.leave_id.holiday_status_id.unpaid_absences):
                        if history.final_accrual_date or history.return_date > date_vacation:
                            date_vacation = history.final_accrual_date or x.return_date + timedelta(days=1)

            working_days = self.dias360(date_vacation, date_end)
            unpaid_days = self.get_unpaid_absences(date_vacation, date_end, employee_id)
            current_period_days = self.calculate_vacation_days(working_days, unpaid_days)
            total_days = initial_days + current_period_days

            return round(total_days, 2)


    def get_unpaid_absences(self, date_start, date_end, employee_id):
        """
        Calcula los días de ausencias no pagadas en un período.
        """
        domain = [
            ('employee_id', '=', employee_id),
            ('date_from', '>=', date_start),
            ('date_to', '<=', date_end),
            ('state', '=', 'validate'),
            ('holiday_status_id.unpaid_absences', '=', True)
        ]
        
        leaves = self.env['hr.leave'].search(domain)
        total_unpaid_days = 0
        
        for leave in leaves:
            days = self.dias360(leave.date_from, leave.date_to)
            total_unpaid_days += days
            
        return total_unpaid_days

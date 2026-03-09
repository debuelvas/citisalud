# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from datetime import datetime, date
from pytz import timezone
import calendar
from dateutil.relativedelta import relativedelta

import pandas as pd
import numpy as np 
import base64
import io
import xlsxwriter
# ReportLab imports
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak, KeepTogether
from reportlab.platypus.flowables import HRFlowable
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics import renderPDF
from reportlab.lib.pagesizes import letter, landscape, A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, cm
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.pagesizes import letter, landscape, A4
from reportlab.lib.utils import ImageReader

class HrPayrollReportAdvancedFilter(models.TransientModel):
    _name = "hr.payroll.report.lavish.filter"
    _description = "Filtros Avanzados - Informe de Liquidación"
    
    # Filtros originales
    payslip_ids = fields.Many2many('hr.payslip.run', string='Lotes de nómina', domain=[('state', '!=', 'draft')])    
    liquidations_ids = fields.Many2many('hr.payslip', string='Liquidaciones individuales', domain=[('payslip_run_id', '=', False)])
    
    # Opciones de visualización
    show_date_of_entry = fields.Boolean(string="Fecha de Ingreso", default=True)
    show_job_placement = fields.Boolean(string="Ubicación Laboral", default=True)
    show_sectional = fields.Boolean(string="Seccional", default=True)
    show_department = fields.Boolean(string="Departamento", default=True)
    show_analytical_account = fields.Boolean(string="Cuenta Analítica", default=True)
    show_job = fields.Boolean(string="Cargo", default=True)
    show_sena_code = fields.Boolean(string="Código SENA", default=True)
    show_basic_salary = fields.Boolean(string="Salario Base", default=True)
    show_dispersing_account = fields.Boolean(string="Cuenta Dispersora", default=True)
    show_bank_officer = fields.Boolean(string="Banco del Funcionario", default=True)
    show_bank_account_officer = fields.Boolean(string="Cuenta Bancaria del Funcionario", default=True)
    show_risk_level = fields.Boolean(string="Nivel de Riesgo ARL", default=True)
    show_provisions = fields.Boolean(string="Mostrar Provisiones", default=False)
    not_show_rule_entity = fields.Boolean(string="No mostrar las reglas + entidad", default=False)
    not_show_quantity = fields.Boolean(string="No mostrar cantidades horas extra y prestaciones", default=False)
    
    # NUEVAS OPCIONES DE AGRUPACIÓN
    group_by = fields.Selection([
        ('none', 'No agrupar'),
        ('department', 'Departamento'),
        ('job', 'Cargo'),
        ('analytic_account', 'Cuenta Analítica'),
        ('risk_level', 'Nivel de Riesgo ARL'),
        ('branch', 'Seccional'),
        ('job_placement', 'Ubicación Laboral'),
        ('month', 'Mes')
    ], string='Agrupar por', default='none')
    
    # NUEVOS FILTROS ADICIONALES
    department_ids = fields.Many2many('hr.department', string='Departamentos')
    job_ids = fields.Many2many('hr.job', string='Cargos')
    analytic_account_ids = fields.Many2many('account.analytic.account', string='Cuentas Analíticas')
    employee_ids = fields.Many2many('hr.employee', string='Empleados')
    rule_category_ids = fields.Many2many('hr.salary.rule.category', string='Categorías de Reglas')
    salary_rule_ids = fields.Many2many('hr.salary.rule', string='Reglas Salariales')
    branch_ids = fields.Many2many('lavish.res.branch', string='Seccionales')
    
    # FILTRO POR RANGO DE FECHAS
    date_from = fields.Date(string='Fecha Desde')
    date_to = fields.Date(string='Fecha Hasta')
    use_date_range = fields.Boolean(string='Usar Rango de Fechas', default=False)
    
    # NUEVAS OPCIONES DE VISUALIZACIÓN
    show_social_security = fields.Boolean(string='Mostrar Seguridad Social', default=False)
    show_individual_payslips = fields.Boolean(string='Mostrar Nóminas Individuales', default=False)
    show_all_in_one = fields.Boolean(string='Mostrar Todo Unido', default=True)
    
    # Campos para archivos de resultado
    excel_file = fields.Binary('Excel file')
    excel_file_name = fields.Char('Excel name')
    pdf_report_payroll = fields.Html('Reporte en PDF')

    # Ordenamiento predefinido de categorías
    earnings_codes = fields.Char(string='Códigos de Devengos', default=lambda self: ','.join([
        'BASIC', 'AUX', 'AUS', 'ALW', 'ACCIDENTE_TRABAJO', 
        'DEV_NO_SALARIAL', 'DEV_SALARIAL', 'HEYREC',
        'COMISIONES', 'INCAPACIDAD', 'LICENCIA_MATERNIDAD',
        'LICENCIA_NO_REMUNERADA', 'LICENCIA_REMUNERADA',
        'PRESTACIONES_SOCIALES', 'PRIMA', 'VACACIONES','TOTALDEV'
    ]))
    
    deductions_codes = fields.Char(string='Códigos de Deducciones', default=lambda self: ','.join([
        'BASE_SEC','IBC_R','SSOCIAL','DED', 'DEDUCCIONES', 'SANCIONES', 
        'DESCUENTO_AFC', 'TOTALDED','NET','PROVISION'
    ]))

    def name_get(self):
        result = []
        for record in self:            
            result.append((record.id, "Informe de nómina avanzado"))
        return result

    def show_all_fields(self):
        self.show_date_of_entry = True
        self.show_job_placement = True
        self.show_sectional = True
        self.show_department = True
        self.show_analytical_account = True
        self.show_job = True
        self.show_sena_code = True
        self.show_basic_salary = True
        self.show_dispersing_account = True
        self.show_bank_officer = True
        self.show_bank_account_officer = True
        self.show_risk_level = True
        return {
            'context': self.env.context,
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': 'hr.payroll.report.lavish.filter',
            'res_id': self.id,
            'type': 'ir.actions.act_window',
            'target': 'new',
        }

    def not_show_all_fields(self):
        self.show_date_of_entry = False
        self.show_job_placement = False
        self.show_sectional = False
        self.show_department = False
        self.show_analytical_account = False
        self.show_job = False
        self.show_sena_code = False
        self.show_basic_salary = False
        self.show_dispersing_account = False
        self.show_bank_officer = False
        self.show_bank_account_officer = False
        self.show_risk_level = False
        return {
            'context': self.env.context,
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': 'hr.payroll.report.lavish.filter',
            'res_id': self.id,
            'type': 'ir.actions.act_window',
            'target': 'new',
        }

    def get_hr_payslip_template_signature(self):
        """Obtiene la plantilla de firma para la compañía correspondiente."""
        obj_company = self.env['res.company']
        if self.payslip_ids:
            obj_company = self.payslip_ids[0].company_id
        elif self.liquidations_ids:
            obj_company = self.liquidations_ids[0].company_id

        return self.env['hr.payslip.reports.template'].search([
            ('company_id', '=', obj_company.id),
            ('type_report', '=', 'nomina')
        ], limit=1)

    def _get_payslips(self):
        """Obtiene las nóminas aplicando todos los filtros seleccionados utilizando el ORM de Odoo."""
        payslips = self.env['hr.payslip']
        min_date = False
        max_date = False
        
        # Filtrar por rango de fechas
        if self.use_date_range:
            min_date = self.date_from
            max_date = self.date_to
            
            domain = ['|', 
                     '&', ('date_from', '>=', min_date), ('date_from', '<=', max_date),
                     '&', ('date_to', '>=', min_date), ('date_to', '<=', max_date)]
            
            # Aplicar filtros adicionales
            if self.employee_ids:
                domain.append(('employee_id', 'in', self.employee_ids.ids))
            if self.department_ids:
                domain.append(('employee_id.department_id', 'in', self.department_ids.ids))
            if self.job_ids:
                domain.append(('employee_id.job_id', 'in', self.job_ids.ids))
            if self.analytic_account_ids:
                domain.append(('contract_id.analytic_account_id', 'in', self.analytic_account_ids.ids))
            if self.branch_ids:
                domain.append(('employee_id.branch_id', 'in', self.branch_ids.ids))
            domain.append(('state', 'in', ('done', 'paid')))    
            # Obtener las nóminas que cumplen los criterios básicos
            payslips = self.env['hr.payslip'].search(domain)
            
            # Si hay filtros por reglas salariales o categorías, debemos filtrar adicionalmente
            if self.salary_rule_ids or self.rule_category_ids:
                filtered_payslips = self.env['hr.payslip']
                
                for slip in payslips:
                    # Verificar si la nómina tiene líneas con las reglas o categorías especificadas
                    if self.salary_rule_ids:
                        for line in slip.line_ids:
                            if line.salary_rule_id.id in self.salary_rule_ids.ids:
                                filtered_payslips |= slip
                                break
                                
                    if self.rule_category_ids and slip not in filtered_payslips:
                        for line in slip.line_ids:
                            if line.category_id.id in self.rule_category_ids.ids:
                                filtered_payslips |= slip
                                break
                                
                payslips = filtered_payslips
        else:
            # Método original para seleccionar liquidaciones desde lotes o individuales
            if not self.payslip_ids and not self.liquidations_ids:
                raise ValidationError(_('Debe seleccionar algún filtro.'))

            # Obtener liquidaciones de lotes seleccionados
            if self.payslip_ids:
                # Establecer fechas mínima y máxima
                for batch in self.payslip_ids:
                    if not min_date or batch.date_start < min_date:
                        min_date = batch.date_start
                    if not max_date or batch.date_end > max_date:
                        max_date = batch.date_end
                
                # Obtener todas las nóminas de los lotes
                batch_payslips = self.env['hr.payslip'].search([
                    ('payslip_run_id', 'in', self.payslip_ids.ids)
                ])
                
                # Aplicar filtros adicionales
                for payslip in batch_payslips:
                    if (not self.employee_ids or payslip.employee_id.id in self.employee_ids.ids) and \
                       (not self.department_ids or payslip.employee_id.department_id.id in self.department_ids.ids) and \
                       (not self.job_ids or payslip.employee_id.job_id.id in self.job_ids.ids) and \
                       (not self.analytic_account_ids or payslip.contract_id.analytic_account_id.id in self.analytic_account_ids.ids) and \
                       (not self.branch_ids or payslip.employee_id.branch_id.id in self.branch_ids.ids):
                        
                        # Verificar reglas salariales y categorías
                        include_payslip = True
                        if self.salary_rule_ids or self.rule_category_ids:
                            include_payslip = False
                            for line in payslip.line_ids:
                                if (self.salary_rule_ids and line.salary_rule_id.id in self.salary_rule_ids.ids) or \
                                   (self.rule_category_ids and line.category_id.id in self.rule_category_ids.ids):
                                    include_payslip = True
                                    break
                        
                        if include_payslip:
                            payslips |= payslip
            
            # Obtener liquidaciones individuales seleccionadas
            if self.liquidations_ids:
                # Actualizar fechas mínima y máxima
                for payslip in self.liquidations_ids:
                    if not min_date or payslip.date_from < min_date:
                        min_date = payslip.date_from
                    if not max_date or payslip.date_to > max_date:
                        max_date = payslip.date_to
                
                # Aplicar filtros a las liquidaciones seleccionadas
                for payslip in self.liquidations_ids:
                    if (not self.employee_ids or payslip.employee_id.id in self.employee_ids.ids) and \
                       (not self.department_ids or payslip.employee_id.department_id.id in self.department_ids.ids) and \
                       (not self.job_ids or payslip.employee_id.job_id.id in self.job_ids.ids) and \
                       (not self.analytic_account_ids or payslip.contract_id.analytic_account_id.id in self.analytic_account_ids.ids) and \
                       (not self.branch_ids or payslip.employee_id.branch_id.id in self.branch_ids.ids):
                        
                        # Verificar reglas salariales y categorías
                        include_payslip = True
                        if self.salary_rule_ids or self.rule_category_ids:
                            include_payslip = False
                            for line in payslip.line_ids:
                                if (self.salary_rule_ids and line.salary_rule_id.id in self.salary_rule_ids.ids) or \
                                   (self.rule_category_ids and line.category_id.id in self.rule_category_ids.ids):
                                    include_payslip = True
                                    break
                        
                        if include_payslip:
                            payslips |= payslip
        
        return payslips, min_date, max_date

    def _get_social_security_data(self, employee_id, date_from, date_to):
        """Obtiene datos de seguridad social para un empleado en un rango de fechas."""
        ss_lines = self.env['hr.executing.social.security'].search([
            ('employee_id', '=', employee_id),
            ('executing_social_security_id.date_start', '>=', date_from),
            ('executing_social_security_id.date_end', '<=', date_to)
        ])
        
        if not ss_lines:
            return {
                'health_company': 0,
                'health_employee': 0,
                'health_total': 0,
                'health_diff': 0,
                'pension_company': 0,
                'pension_employee': 0,
                'pension_total': 0,
                'pension_diff': 0,
                'risk_level': 0,
                'arl': 0,
                'ccf': 0,
                'sena': 0,
                'icbf': 0
            }
        
        total_data = {
            'health_company': sum(ss_lines.mapped('nValorSaludEmpresa')),
            'health_employee': sum(ss_lines.mapped('nValorSaludEmpleado')),
            'health_total': sum(ss_lines.mapped('nValorSaludTotal')),
            'health_diff': sum(ss_lines.mapped('nDiferenciaSalud')),
            'pension_company': sum(ss_lines.mapped('nValorPensionEmpresa')),
            'pension_employee': sum(ss_lines.mapped('nValorPensionEmpleado')),
            'pension_total': sum(ss_lines.mapped('nValorPensionTotal')),
            'pension_diff': sum(ss_lines.mapped('nDiferenciaPension')),
            'risk_level': ss_lines[0].nPorcAporteARP * 100 if ss_lines else 0,
            'arl': sum(ss_lines.mapped('nValorARP')),
            'ccf': sum(ss_lines.mapped('nValorCajaCom')),
            'sena': sum(ss_lines.mapped('nValorSENA')),
            'icbf': sum(ss_lines.mapped('nValorICBF'))
        }
        
        return total_data

    def _get_novedades(self, min_date, max_date, employees):
        """Obtiene las novedades (ausencias) para los empleados en el rango de fechas dado."""
        if not min_date or not max_date:
            return {}
        
        employee_ids = employees.mapped('id')
        
        leaves = self.env['hr.leave'].search([
            ('employee_id', 'in', employee_ids),
            ('state', '=', 'validate'),
            '|',
            '&', ('request_date_from', '>=', min_date), ('request_date_from', '<=', max_date),
            '&', ('request_date_to', '>=', min_date), ('request_date_to', '<=', max_date)
        ])
        
        # Organizar las novedades por empleado
        novedades_por_empleado = {}
        for leave in leaves:
            identificacion = leave.employee_id.identification_id
            if identificacion not in novedades_por_empleado:
                novedades_por_empleado[identificacion] = []
            
            nombre_novedad = leave.private_name or leave.holiday_status_id.name
            novedades_por_empleado[identificacion].append(nombre_novedad)
        
        # Convertir listas de novedades a strings concatenados
        for identificacion, novedades in novedades_por_empleado.items():
            novedades_por_empleado[identificacion] = ' -\r\n '.join(novedades)
            
        return novedades_por_empleado

    def _prepare_report_data(self, payslips, min_date, max_date):
        """Prepara los datos para el informe utilizando el ORM."""
        if not payslips:
            raise ValidationError(_('No se encontraron nóminas con los filtros seleccionados.'))
        
        # Filtrar solo empleados con las reglas/categorías seleccionadas si corresponde
        if self.salary_rule_ids or self.rule_category_ids:
            filtered_payslips = self.env['hr.payslip']
            
            for payslip in payslips:
                include_payslip = False
                
                # Verificar si el empleado tiene las reglas seleccionadas
                for line in payslip.line_ids:
                    if (self.salary_rule_ids and line.salary_rule_id.id in self.salary_rule_ids.ids) or \
                       (self.rule_category_ids and line.category_id.id in self.rule_category_ids.ids):
                        include_payslip = True
                        break
                
                if include_payslip:
                    filtered_payslips |= payslip
            
            payslips = filtered_payslips
        
        if not payslips:
            raise ValidationError(_('No se encontraron nóminas con las reglas o categorías seleccionadas.'))
        
        # Obtener las novedades
        employees = payslips.mapped('employee_id')
        novedades_por_empleado = self._get_novedades(min_date, max_date, employees)
        
        # Preparar datos para el dataframe
        report_data = []
        item_counter = 1
        
        # Configurar agrupación por mes si está seleccionada
        if self.group_by == 'month':
            for payslip in payslips:
                # Determinar el mes de la nómina basado en la fecha de inicio
                mes = payslip.date_from.month
                anio = payslip.date_from.year
                nombre_mes = calendar.month_name[mes]
        
        # Procesamiento de días trabajados y líneas de nómina
        for payslip in payslips:
            employee = payslip.employee_id
            contract = payslip.contract_id
            
            if self.group_by == 'month':
                mes = payslip.date_from.month
                anio = payslip.date_from.year
                nombre_mes = calendar.month_name[mes]
                grupo_mes = f"{nombre_mes} {anio}"
            
            # Datos base del empleado que se utilizarán en todos los registros
            employee_base_data = {
                'Item': item_counter,
                'Identificación': employee.identification_id or '',
                'Empleado': employee.name or '',
                'Fecha Ingreso': contract.date_start or datetime(1900, 1, 1).date(),
                'Seccional': employee.branch_id.name if employee.branch_id else '',
                'Cuenta Analítica': contract.analytic_account_id.name if contract.analytic_account_id else '',
                'Cargo': employee.job_id.name if employee.job_id else '',
                'Banco': employee.work_contact_id and employee.work_contact_id.bank_ids and employee.work_contact_id.bank_ids.filtered(lambda b: b.is_main) and employee.work_contact_id.bank_ids.filtered(lambda b: b.is_main)[0].bank_id.name or '',
                'Cuenta Bancaria': employee.work_contact_id and employee.work_contact_id.bank_ids and employee.work_contact_id.bank_ids.filtered(lambda b: b.is_main) and employee.work_contact_id.bank_ids.filtered(lambda b: b.is_main)[0].acc_number or '',
                'Cuenta Dispersora': employee.work_contact_id and employee.work_contact_id.bank_ids and employee.work_contact_id.bank_ids.filtered(lambda b: b.is_main and b.payroll_dispersion_account) and employee.work_contact_id.bank_ids.filtered(lambda b: b.is_main)[0].payroll_dispersion_account.name or '',
                'Código SENA': contract.code_sena or '',
                'Ubicación Laboral': employee.address_id.name if employee.address_id else '',
                'Departamento': employee.department_id.name if employee.department_id else '',
                'Nivel de Riesgo ARL': contract.risk_id.name if contract.risk_id else '',
                'Salario Base': contract.wage or 0,
                'Novedades': novedades_por_empleado.get(employee.identification_id, ''),
                'Fecha Inicio': payslip.date_from,
                'Fecha Fin': payslip.date_to
            }
            
            # Definir etiqueta de grupo para agrupación
            if self.group_by == 'department':
                employee_base_data['Grupo'] = employee.department_id.name if employee.department_id else 'Sin Departamento'
            elif self.group_by == 'job':
                employee_base_data['Grupo'] = employee.job_id.name if employee.job_id else 'Sin Cargo'
            elif self.group_by == 'analytic_account':
                employee_base_data['Grupo'] = contract.analytic_account_id.name if contract.analytic_account_id else 'Sin Cuenta Analítica'
            elif self.group_by == 'risk_level':
                employee_base_data['Grupo'] = contract.risk_id.name if contract.risk_id else 'Sin Nivel de Riesgo'
            elif self.group_by == 'branch':
                employee_base_data['Grupo'] = employee.branch_id.name if employee.branch_id else 'Sin Seccional'
            elif self.group_by == 'job_placement':
                employee_base_data['Grupo'] = employee.address_id.name if employee.address_id else 'Sin Ubicación Laboral'
            elif self.group_by == 'month':
                employee_base_data['Grupo'] = grupo_mes
            else:
                employee_base_data['Grupo'] = 'Todos'
            
            # Añadir información de seguridad social si está activada
            if self.show_social_security:
                ss_data = self._get_social_security_data(
                    employee.id, 
                    payslip.date_from, 
                    payslip.date_to
                )
                employee_base_data.update({
                    'SS_Salud_Empresa': ss_data['health_company'],
                    'SS_Salud_Empleado': ss_data['health_employee'],
                    'SS_Salud_Total': ss_data['health_total'],
                    'SS_Salud_Diferencia': ss_data['health_diff'],
                    'SS_Pensión_Empresa': ss_data['pension_company'],
                    'SS_Pensión_Empleado': ss_data['pension_employee'],
                    'SS_Pensión_Total': ss_data['pension_total'],
                    'SS_Pensión_Diferencia': ss_data['pension_diff'],
                    'SS_Nivel_Riesgo': ss_data['risk_level'],
                    'SS_ARL': ss_data['arl'],
                    'SS_CCF': ss_data['ccf'],
                    'SS_SENA': ss_data['sena'],
                    'SS_ICBF': ss_data['icbf']
                })
            
            # Procesar días trabajados
            for worked_day in payslip.worked_days_line_ids:
                # Solo incluir días trabajados si no hay filtro de reglas o si coincide con el filtro
                if self.salary_rule_ids:
                    # Verificar si el tipo de entrada corresponde a alguna regla seleccionada
                    matching_rule = False
                    for rule in self.salary_rule_ids:
                        # Aquí deberías implementar la lógica para verificar si el work_entry_type
                        # está relacionado con alguna de las reglas salariales seleccionadas
                        if worked_day.work_entry_type_id.code == rule.code:
                            matching_rule = True
                            break
                    
                    if not matching_rule:
                        continue
                
                day_data = employee_base_data.copy()
                day_data.update({
                    'Regla Salarial': worked_day.work_entry_type_id.short_name or worked_day.work_entry_type_id.name or '',
                    'Reglas Salariales + Entidad': worked_day.work_entry_type_id.short_name or worked_day.work_entry_type_id.name or '',
                    'Categoría': 'Días',
                    'Secuencia': 0,
                    'Monto': worked_day.number_of_days or 0
                })
                report_data.append(day_data)
            
            # Obtener listas de categorías permitidas
            earnings_codes_list = self.earnings_codes.split(',') if self.earnings_codes else []
            deductions_codes_list = self.deductions_codes.split(',') if self.deductions_codes else []
            
            # Procesar líneas de nómina
            has_matching_rule = False
            for line in payslip.line_ids:
                # Verificar si aplican los filtros de reglas y categorías
                if self.salary_rule_ids and self.rule_category_ids:
                    if line.salary_rule_id.id not in self.salary_rule_ids.ids and line.category_id.id not in self.rule_category_ids.ids:
                        continue
                elif self.salary_rule_ids:
                    if line.salary_rule_id.id not in self.salary_rule_ids.ids:
                        continue
                elif self.rule_category_ids:
                    if line.category_id.id not in self.rule_category_ids.ids:
                        continue
                
                # Verificar si se debe mostrar provisiones
                if line.category_id.code == 'PROVISION' and not self.show_provisions:
                    continue
                
                # Verificar que la categoría esté en las listas permitidas
                if line.category_id.code not in earnings_codes_list + deductions_codes_list + ['TOTALDEV', 'TOTALDED', 'NET', 'PROVISION']:
                    if line.salary_rule_id.code not in ['TOTALDEV', 'TOTALDED', 'NET']:
                        continue
                
                has_matching_rule = True
                
                # Datos base para esta línea
                entity_name = ''
                if line.entity_id and line.category_id.code != 'SSOCIAL':
                    entity_name = line.entity_id.partner_id.business_name or line.entity_id.partner_id.name or ''
                
                line_data = employee_base_data.copy()
                rule_name = line.salary_rule_id.short_name or line.salary_rule_id.name or ''
                
                # Agregar datos de la línea
                line_data.update({
                    'Regla Salarial': rule_name,
                    'Reglas Salariales + Entidad': f"{rule_name} {entity_name}".strip() if not self.not_show_rule_entity else rule_name,
                    'Categoría': line.category_id.name or '',
                    'Código Categoría': line.category_id.code or '',
                    'Secuencia': line.sequence or 0,
                    'Monto': line.total or 0
                })
                report_data.append(line_data)
                
                # Si no es mostrar cantidades, continuar
                if self.not_show_quantity:
                    continue
                
                # Agregar cantidad para horas extras y prestaciones sociales
                if line.category_id.code in ['HEYREC', 'PRESTACIONES_SOCIALES'] and line.quantity:
                    quantity_data = employee_base_data.copy()
                    quantity_data.update({
                        'Regla Salarial': rule_name,
                        'Reglas Salariales + Entidad': f"Cantidad de {rule_name}" if not self.not_show_rule_entity else f"Cantidad de {rule_name}",
                        'Categoría': line.category_id.name or '',
                        'Código Categoría': line.category_id.code or '',
                        'Secuencia': line.sequence or 0,
                        'Monto': line.quantity or 0
                    })
                    report_data.append(quantity_data)
                
                # Agregar base para prestaciones sociales
                if line.category_id.code == 'PRESTACIONES_SOCIALES' and line.amount_base:
                    base_data = employee_base_data.copy()
                    base_data.update({
                        'Regla Salarial': rule_name,
                        'Reglas Salariales + Entidad': f"Base de {rule_name}" if not self.not_show_rule_entity else f"Base de {rule_name}",
                        'Categoría': line.category_id.name or '',
                        'Código Categoría': line.category_id.code or '',
                        'Secuencia': line.sequence or 0,
                        'Monto': line.amount_base or 0
                    })
                    report_data.append(base_data)
                
                # Agregar días de ausencias no remuneradas
                if line.days_unpaid_absences:
                    absence_data = employee_base_data.copy()
                    absence_data.update({
                        'Regla Salarial': rule_name,
                        'Reglas Salariales + Entidad': f"Días Ausencias no remuneradas de {rule_name}" if not self.not_show_rule_entity else f"Días Ausencias no remuneradas de {rule_name}",
                        'Categoría': line.category_id.name or '',
                        'Código Categoría': line.category_id.code or '',
                        'Secuencia': line.sequence or 0,
                        'Monto': line.days_unpaid_absences or 0
                    })
                    report_data.append(absence_data)
            
            # Solo incrementar el contador si el empleado tiene reglas coincidentes
            if has_matching_rule or not (self.salary_rule_ids or self.rule_category_ids):
                item_counter += 1
        
        # Agregar subtotales y totales
        self._add_grouped_totals_to_report_data(report_data)
        
        # Convertir a DataFrame
        df_report = pd.DataFrame(report_data)
        
        return df_report

    def _add_grouped_totals_to_report_data(self, report_data):
        """Agrega filas de subtotales por grupo y totales generales al conjunto de datos."""
        if not report_data:
            return
            
        # Convertir a DataFrame para procesar
        df = pd.DataFrame(report_data)
        if 'Grupo' not in df.columns or len(df) == 0:
            return
            
        # Agrupar por grupo y regla para calcular subtotales
        groups = df['Grupo'].unique().tolist()
        
        # Para cada grupo, calcular subtotales
        subtotals_data = []
        
        for group in groups:
            # Obtener solo los datos de este grupo
            group_data = df[df['Grupo'] == group]
            
            # Agrupar por regla salarial y sumar montos
            for rule in group_data['Reglas Salariales + Entidad'].unique():
                rule_data = group_data[group_data['Reglas Salariales + Entidad'] == rule]
                
                # Solo si la regla tiene montos diferentes de cero
                if rule_data['Monto'].sum() != 0:
                    # Crear registro de subtotal
                    subtotal_data = {
                        'Item': 400000,  # Valor para identificar que es un subtotal
                        'Identificación': '',
                        'Empleado': f'SUBTOTAL {group}',
                        'Grupo': group,
                        'Fecha Ingreso': datetime(1900, 1, 1).date(),
                        'Seccional': '',
                        'Cuenta Analítica': '',
                        'Cargo': '',
                        'Banco': '',
                        'Cuenta Bancaria': '',
                        'Cuenta Dispersora': '',
                        'Código SENA': '',
                        'Ubicación Laboral': '',
                        'Departamento': '',
                        'Nivel de Riesgo ARL': '',
                        'Salario Base': 0,
                        'Novedades': '',
                        'Regla Salarial': rule_data['Regla Salarial'].iloc[0],
                        'Reglas Salariales + Entidad': rule,
                        'Categoría': rule_data['Categoría'].iloc[0],
                        'Código Categoría': rule_data['Código Categoría'].iloc[0] if 'Código Categoría' in rule_data else '',
                        'Secuencia': rule_data['Secuencia'].iloc[0],
                        'Monto': rule_data['Monto'].sum()
                    }
                    
                    # Añadir campos de seguridad social si existen
                    ss_fields = [field for field in rule_data.columns if field.startswith('SS_')]
                    for field in ss_fields:
                        subtotal_data[field] = rule_data[field].sum()
                    
                    subtotals_data.append(subtotal_data)
        
        # Agregar subtotales al reporte
        report_data.extend(subtotals_data)
        
        # Ahora calcular totales generales
        df = pd.DataFrame(report_data)
        df_employee_rows = df[df['Item'] < 400000]  # Solo filas de empleados reales
        
        # Calcular totales por regla
        for rule in df_employee_rows['Reglas Salariales + Entidad'].unique():
            rule_data = df_employee_rows[df_employee_rows['Reglas Salariales + Entidad'] == rule]
            
            # Solo si la regla tiene montos diferentes de cero
            if rule_data['Monto'].sum() != 0:
                # Crear registro de total general
                total_data = {
                    'Item': 500000,  # Valor para identificar que es un total general
                    'Identificación': '',
                    'Empleado': 'TOTAL GENERAL',
                    'Grupo': 'TOTAL',
                    'Fecha Ingreso': datetime(1900, 1, 1).date(),
                    'Seccional': '',
                    'Cuenta Analítica': '',
                    'Cargo': '',
                    'Banco': '',
                    'Cuenta Bancaria': '',
                    'Cuenta Dispersora': '',
                    'Código SENA': '',
                    'Ubicación Laboral': '',
                    'Departamento': '',
                    'Nivel de Riesgo ARL': '',
                    'Salario Base': 0,
                    'Novedades': '',
                    'Regla Salarial': rule_data['Regla Salarial'].iloc[0],
                    'Reglas Salariales + Entidad': rule,
                    'Categoría': rule_data['Categoría'].iloc[0],
                    'Código Categoría': rule_data['Código Categoría'].iloc[0] if 'Código Categoría' in rule_data else '',
                    'Secuencia': rule_data['Secuencia'].iloc[0],
                    'Monto': rule_data['Monto'].sum()
                }
                
                # Añadir campos de seguridad social si existen
                ss_fields = [field for field in rule_data.columns if field.startswith('SS_')]
                for field in ss_fields:
                    total_data[field] = rule_data[field].sum()
                
                report_data.append(total_data)

    def _get_company_data(self):
        """Obtiene los datos de la empresa para el encabezado del informe."""
        company = self.env.company
        if self.payslip_ids:
            company = self.payslip_ids[0].company_id
        elif self.liquidations_ids:
            company = self.liquidations_ids[0].company_id
            
        return {
            'name': company.name,
            'nit': company.vat,  # NIT o VAT
            'street': company.street,
            'city': company.city,
            'state': company.state_id.name if company.state_id else '',
            'country': company.country_id.name if company.country_id else '',
            'phone': company.phone,
            'email': company.email,
            'website': company.website,
            'logo': company.logo
        }
        
    def _get_summary_metrics(self, df_report, payslips):
        """Calcula métricas de resumen para el informe."""
        # Inicializar métricas
        metrics = {
            'total_devengos': 0,
            'total_deducciones': 0,
            'neto_pagar': 0,
            'empleados_count': len(payslips.mapped('employee_id')),
            'ausencias_count': 0,
            'ausencias_dias': 0,
            'horas_extras_valor': 0
        }
        
        # Total devengos, deducciones y neto
        for slip in payslips:
            metrics['total_devengos'] += slip.line_ids.filtered(lambda l: l.salary_rule_id.code == 'TOTALDEV').mapped('total')[0] if slip.line_ids.filtered(lambda l: l.salary_rule_id.code == 'TOTALDEV') else 0
            metrics['total_deducciones'] += slip.line_ids.filtered(lambda l: l.salary_rule_id.code == 'TOTALDED').mapped('total')[0] if slip.line_ids.filtered(lambda l: l.salary_rule_id.code == 'TOTALDED') else 0
            metrics['neto_pagar'] += slip.line_ids.filtered(lambda l: l.salary_rule_id.code == 'NET').mapped('total')[0] if slip.line_ids.filtered(lambda l: l.salary_rule_id.code == 'NET') else 0
        
        # Ausencias
        for slip in payslips:
            # Contar ausencias
            leave_lines = slip.worked_days_line_ids.filtered(lambda w: w.work_entry_type_id.is_leave)
            if leave_lines:
                metrics['ausencias_count'] += len(leave_lines)
                metrics['ausencias_dias'] += sum(leave_lines.mapped('number_of_days'))
        
        # Horas extras
        for slip in payslips:
            # Valor de horas extras (categoría HEYREC)
            extras_lines = slip.line_ids.filtered(lambda l: l.category_id.code == 'HEYREC')
            if extras_lines:
                metrics['horas_extras_valor'] += sum(extras_lines.mapped('total'))
        
        return metrics
        
    def _get_category_totals(self, payslips):
        """Obtiene totales por categoría de regla salarial."""
        category_totals = {}
        
        # Obtener las listas de categorías permitidas
        earnings_codes_list = self.earnings_codes.split(',') if self.earnings_codes else []
        deductions_codes_list = self.deductions_codes.split(',') if self.deductions_codes else []
        allowed_codes = earnings_codes_list + deductions_codes_list
        
        for slip in payslips:
            for line in slip.line_ids:
                # Verificar si la categoría está permitida
                if line.category_id.code in allowed_codes or line.category_id.code in ['TOTALDEV', 'TOTALDED', 'NET', 'PROVISION']:
                    category_name = line.category_id.name
                    if category_name not in category_totals:
                        category_totals[category_name] = {
                            'total': 0,
                            'code': line.category_id.code
                        }
                    category_totals[category_name]['total'] += line.total
        
        # Convertir a lista para facilitar su uso en el gráfico
        categories = []
        for name, data in category_totals.items():
            if name and data['total'] != 0:  # Filtrar valores vacíos o cero
                categories.append({
                    'name': name, 
                    'total': data['total'],
                    'code': data['code']
                })
        
        # Ordenar primero por el orden de las categorías en las listas y luego por monto
        def get_category_order(item):
            if item['code'] in earnings_codes_list:
                return (1, earnings_codes_list.index(item['code']))
            elif item['code'] in deductions_codes_list:
                return (2, deductions_codes_list.index(item['code']))
            elif item['code'] == 'TOTALDEV':
                return (3, 0)
            elif item['code'] == 'TOTALDED':
                return (4, 0)
            elif item['code'] == 'NET':
                return (5, 0)
            else:
                return (6, 0)
        
        return sorted(categories, key=get_category_order)
    
    def _get_department_totals(self, payslips):
        """Obtiene totales por departamento y cuenta empleados por departamento."""
        department_totals = {}
        
        for slip in payslips:
            dept_name = slip.employee_id.department_id.name or 'Sin Departamento'
            if dept_name not in department_totals:
                department_totals[dept_name] = {
                    'devengos': 0,
                    'deducciones': 0,
                    'neto': 0,
                    'empleados': set()
                }
            
            # Añadir empleado al set
            department_totals[dept_name]['empleados'].add(slip.employee_id.id)
            
            # Sumar totales
            totaldev_line = slip.line_ids.filtered(lambda l: l.salary_rule_id.code == 'TOTALDEV')
            totalded_line = slip.line_ids.filtered(lambda l: l.salary_rule_id.code == 'TOTALDED')
            net_line = slip.line_ids.filtered(lambda l: l.salary_rule_id.code == 'NET')
            
            if totaldev_line:
                department_totals[dept_name]['devengos'] += totaldev_line[0].total
            if totalded_line:
                department_totals[dept_name]['deducciones'] += totalded_line[0].total
            if net_line:
                department_totals[dept_name]['neto'] += net_line[0].total
        
        # Convertir a lista y contar empleados
        departments = []
        for name, data in department_totals.items():
            departments.append({
                'name': name,
                'devengos': data['devengos'],
                'deducciones': data['deducciones'],
                'neto': data['neto'],
                'empleados': len(data['empleados'])
            })
        
        return sorted(departments, key=lambda x: x['neto'], reverse=True)
    
    def _get_analytic_account_totals(self, payslips):
        """Obtiene totales por cuenta analítica."""
        analytic_totals = {}
        
        for slip in payslips:
            account_name = slip.contract_id.analytic_account_id.name if slip.contract_id.analytic_account_id else 'Sin Cuenta Analítica'
            if account_name not in analytic_totals:
                analytic_totals[account_name] = {
                    'devengos': 0,
                    'deducciones': 0,
                    'neto': 0,
                    'empleados': set()
                }
            
            # Añadir empleado al set
            analytic_totals[account_name]['empleados'].add(slip.employee_id.id)
            
            # Sumar totales
            totaldev_line = slip.line_ids.filtered(lambda l: l.salary_rule_id.code == 'TOTALDEV')
            totalded_line = slip.line_ids.filtered(lambda l: l.salary_rule_id.code == 'TOTALDED')
            net_line = slip.line_ids.filtered(lambda l: l.salary_rule_id.code == 'NET')
            
            if totaldev_line:
                analytic_totals[account_name]['devengos'] += totaldev_line[0].total
            if totalded_line:
                analytic_totals[account_name]['deducciones'] += totalded_line[0].total
            if net_line:
                analytic_totals[account_name]['neto'] += net_line[0].total
        
        # Convertir a lista y contar empleados
        accounts = []
        for name, data in analytic_totals.items():
            accounts.append({
                'name': name,
                'devengos': data['devengos'],
                'deducciones': data['deducciones'],
                'neto': data['neto'],
                'empleados': len(data['empleados'])
            })
        
        return sorted(accounts, key=lambda x: x['neto'], reverse=True)
    
    def _get_rule_totals(self, payslips):
        """Obtiene totales por regla salarial para el gráfico circular."""
        rule_totals = {}
        
        # Obtener listas de categorías permitidas
        earnings_codes_list = self.earnings_codes.split(',') if self.earnings_codes else []
        deductions_codes_list = self.deductions_codes.split(',') if self.deductions_codes else []
        allowed_codes = earnings_codes_list + deductions_codes_list
        
        for slip in payslips:
            for line in slip.line_ids:
                # Excluir totales como TOTALDEV, TOTALDED, NET a menos que la categoría esté en la lista permitida
                if line.salary_rule_id.code in ['TOTALDEV', 'TOTALDED', 'NET'] and line.category_id.code not in allowed_codes:
                    continue
                
                # Si hay filtro de categorías, aplicarlo
                if allowed_codes and line.category_id.code not in allowed_codes + ['TOTALDEV', 'TOTALDED', 'NET', 'PROVISION']:
                    continue
                
                # Si debe mostrar o no provisiones
                if line.category_id.code == 'PROVISION' and not self.show_provisions:
                    continue
                
                rule_name = line.salary_rule_id.short_name or line.salary_rule_id.name
                if rule_name not in rule_totals:
                    rule_totals[rule_name] = {
                        'total': 0,
                        'code': line.category_id.code,
                        'sequence': line.sequence
                    }
                rule_totals[rule_name]['total'] += line.total
        
        # Filtrar y ordenar
        rules = []
        for name, data in rule_totals.items():
            if data['total'] != 0:  # Solo incluir valores distintos de cero
                rules.append({
                    'name': name, 
                    'total': data['total'],
                    'code': data['code'],
                    'sequence': data['sequence']
                })
        
        # Ordenar reglas primero por código de categoría según el orden especificado
        def get_rule_order(item):
            if item['code'] in earnings_codes_list:
                return (1, earnings_codes_list.index(item['code']), item['sequence'])
            elif item['code'] in deductions_codes_list:
                return (2, deductions_codes_list.index(item['code']), item['sequence'])
            elif item['code'] == 'TOTALDEV':
                return (3, 0, item['sequence'])
            elif item['code'] == 'TOTALDED':
                return (4, 0, item['sequence'])
            elif item['code'] == 'NET':
                return (5, 0, item['sequence'])
            else:
                return (6, 0, item['sequence'])
        
        sorted_rules = sorted(rules, key=get_rule_order)
        
        # Limitar a las 15 reglas más significativas para el gráfico
        if len(sorted_rules) > 15:
            # Sumar el resto en "Otros"
            others_total = sum(r['total'] for r in sorted_rules[15:])
            top_rules = sorted_rules[:15]
            if others_total != 0:
                top_rules.append({'name': 'Otros', 'total': others_total, 'code': 'OTHER', 'sequence': 999})
            return top_rules
        
        return sorted_rules
    
    def _get_entity_totals(self, payslips):
        """Obtiene totales pagados por entidad."""
        entity_totals = {}
        
        for slip in payslips:
            for line in slip.line_ids:
                if line.entity_id:
                    entity_name = line.entity_id.partner_id.business_name or line.entity_id.partner_id.name
                    if entity_name not in entity_totals:
                        entity_totals[entity_name] = 0
                    entity_totals[entity_name] += line.total
        
        # Convertir a lista para el gráfico
        entities = []
        for name, total in entity_totals.items():
            if total != 0:  # Solo incluir valores distintos de cero
                entities.append({'name': name, 'total': total})
        
        # Ordenar por valor absoluto
        return sorted(entities, key=lambda x: abs(x['total']), reverse=True)
    
    def _add_company_header(self, worksheet, workbook, company_data):
        """Añade encabezado con información de la empresa."""
        # Definir formatos
        title_format = workbook.add_format({
            'bold': True, 
            'font_size': 16, 
            'align': 'center',
            'valign': 'vcenter',
            'font_color': '#1F497D'
        })
        
        info_format = workbook.add_format({
            'align': 'center',
            'valign': 'vcenter',
            'font_size': 10
        })
        
        # Insertar logo si existe
        if company_data.get('logo'):
            logo_data = io.BytesIO(base64.b64decode(company_data['logo']))
            worksheet.insert_image('A1', "logo_company.png", {'image_data': logo_data, 'x_scale': 0.6, 'y_scale': 0.4})
        
        # Nombre de la empresa
        worksheet.merge_range('C1:F1', company_data['name'], title_format)
        
        # NIT
        nit_text = f"NIT: {company_data['nit']}" if company_data.get('nit') else ""
        worksheet.merge_range('C2:F2', nit_text, info_format)
        
        # Dirección
        address_parts = []
        if company_data.get('street'):
            address_parts.append(company_data['street'])
        if company_data.get('city'):
            address_parts.append(company_data['city'])
        if company_data.get('state'):
            address_parts.append(company_data['state'])
        
        address_text = ', '.join([p for p in address_parts if p])
        worksheet.merge_range('C3:F3', address_text, info_format)
        
        # Contacto
        contact_parts = []
        if company_data.get('phone'):
            contact_parts.append(f"Tel: {company_data['phone']}")
        if company_data.get('email'):
            contact_parts.append(company_data['email'])
        if company_data.get('website'):
            contact_parts.append(company_data['website'])
        
        contact_text = ' | '.join([p for p in contact_parts if p])
        worksheet.merge_range('C4:F4', contact_text, info_format)
        
        return 5  # Retorna la siguiente fila disponible
    
    def _add_summary_dashboard(self, worksheet, workbook, metrics, next_row):
        """Añade cuadro de resumen con métricas principales."""
        # Formatos
        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#1F497D',
            'font_color': 'white',
            'align': 'center',
            'valign': 'vcenter',
            'border': 1
        })
        
        value_format = workbook.add_format({
            'bold': True,
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
            'num_format': '#,##0.00'
        })
        
        label_format = workbook.add_format({
            'bold': True,
            'align': 'left',
            'valign': 'vcenter',
            'border': 1
        })
        
        # Encabezado del cuadro
        worksheet.merge_range(next_row, 0, next_row, 6, 'RESUMEN DE NÓMINA', header_format)
        next_row += 1
        
        # Métricas principales
        metrics_data = [
            ('Total Devengos:', metrics['total_devengos']),
            ('Total Deducciones:', metrics['total_deducciones']),
            ('Neto a Pagar:', metrics['neto_pagar']),
            ('Total Empleados:', metrics['empleados_count']),
            ('Total Ausencias:', metrics['ausencias_count']),
            ('Días de Ausencias:', metrics['ausencias_dias']),
            ('Valor Horas Extras:', metrics['horas_extras_valor'])
        ]
        
        for label, value in metrics_data:
            worksheet.write(next_row, 0, label, label_format)
            
            # Formato especial para valores numéricos
            if isinstance(value, (int, float)):
                worksheet.write(next_row, 1, value, value_format)
            else:
                worksheet.write(next_row, 1, value, label_format)
                
            next_row += 1
        
        # Añadir espacio después del cuadro
        next_row += 1
        
        return next_row

# -*- coding: utf-8 -*-
# Parte del modelo hr.payroll.report.lavish.filter

    def _add_summary_charts(self, workbook, category_totals, department_totals, analytic_totals, rule_totals, entity_totals, payslips):
        """Añade hoja con gráficos de resumen mejorados."""
        # Crear hoja para gráficos
        worksheet = workbook.add_worksheet('Gráficos y Análisis')
        
        # Formatos
        title_format = workbook.add_format({
            'bold': True, 
            'font_size': 14, 
            'align': 'center',
            'valign': 'vcenter',
            'font_color': '#1F497D'
        })
        
        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#1F497D',
            'font_color': 'white',
            'align': 'center',
            'valign': 'vcenter',
            'border': 1
        })
        
        cell_format = workbook.add_format({
            'border': 1,
            'align': 'left',
            'valign': 'vcenter'
        })
        
        number_format = workbook.add_format({
            'border': 1,
            'align': 'right',
            'num_format': '#,##0.00'
        })
        
        count_format = workbook.add_format({
            'border': 1,
            'align': 'center',
            'num_format': '0'
        })
        
        current_row = 1  # Iniciar desde la fila 1
        
        # 1. Gráfico circular de reglas salariales
        if rule_totals:
            worksheet.merge_range(current_row, 0, current_row, 6, 'DISTRIBUCIÓN DE REGLAS SALARIALES', title_format)
            current_row += 1
            
            # Preparar datos
            rule_names = [rule['name'] for rule in rule_totals]
            rule_values = [rule['total'] for rule in rule_totals]
            
            # Escribir datos para el gráfico
            data_start_row = current_row + 1
            worksheet.write_column(data_start_row, 0, rule_names)
            worksheet.write_column(data_start_row, 1, rule_values)
            
            # Crear gráfico circular
            chart_rules = workbook.add_chart({'type': 'pie'})
            chart_rules.add_series({
                'name': 'Reglas Salariales',
                'categories': ['Gráficos y Análisis', data_start_row, 0, data_start_row + len(rule_names) - 1, 0],
                'values': ['Gráficos y Análisis', data_start_row, 1, data_start_row + len(rule_values) - 1, 1],
                'data_labels': {'percentage': True, 'category': True, 'position': 'outside_end'}
            })
            
            chart_rules.set_title({'name': 'Distribución por Reglas Salariales'})
            chart_rules.set_style(10)
            chart_rules.set_size({'width': 720, 'height': 400})
            worksheet.insert_chart(current_row, 3, chart_rules)
            
            # Agregar también los datos en formato tabla
            current_row += 22  # Espacio para el gráfico
            worksheet.write(current_row, 0, 'Regla Salarial', header_format)
            worksheet.write(current_row, 1, 'Valor Total', header_format)
            current_row += 1
            
            for rule in rule_totals:
                worksheet.write(current_row, 0, rule['name'], cell_format)
                worksheet.write(current_row, 1, rule['total'], number_format)
                current_row += 1
            
            current_row += 2  # Espacio extra
        
        # 2. Gráfico de categorías
        if category_totals:
            worksheet.merge_range(current_row, 0, current_row, 6, 'DISTRIBUCIÓN POR CATEGORÍA', title_format)
            current_row += 1
            
            # Preparar datos
            category_names = [category['name'] for category in category_totals]
            category_values = [category['total'] for category in category_totals]
            
            # Escribir datos para el gráfico
            data_start_row = current_row + 1
            worksheet.write_column(data_start_row, 0, category_names)
            worksheet.write_column(data_start_row, 1, category_values)
            
            # Crear gráfico de barras
            chart_categories = workbook.add_chart({'type': 'column'})
            chart_categories.add_series({
                'name': 'Categorías',
                'categories': ['Gráficos y Análisis', data_start_row, 0, data_start_row + len(category_names) - 1, 0],
                'values': ['Gráficos y Análisis', data_start_row, 1, data_start_row + len(category_values) - 1, 1],
                'data_labels': {'value': True}
            })
            
            chart_categories.set_title({'name': 'Distribución por Categoría'})
            chart_categories.set_x_axis({'name': 'Categoría'})
            chart_categories.set_y_axis({'name': 'Valor'})
            chart_categories.set_style(11)
            chart_categories.set_size({'width': 720, 'height': 400})
            worksheet.insert_chart(current_row, 3, chart_categories)
            
            # Agregar también los datos en formato tabla
            current_row += 22  # Espacio para el gráfico
            worksheet.write(current_row, 0, 'Categoría', header_format)
            worksheet.write(current_row, 1, 'Valor Total', header_format)
            current_row += 1
            
            for category in category_totals:
                worksheet.write(current_row, 0, category['name'], cell_format)
                worksheet.write(current_row, 1, category['total'], number_format)
                current_row += 1
            
            current_row += 2  # Espacio extra
        
        # 3. Grafico de dispersión por departamento (empleados)
        if department_totals:
            worksheet.merge_range(current_row, 0, current_row, 6, 'EMPLEADOS POR DEPARTAMENTO', title_format)
            current_row += 1
            
            # Preparar datos
            dept_names = [dept['name'] for dept in department_totals]
            dept_employee_count = [dept['empleados'] for dept in department_totals]
            
            # Escribir datos para el gráfico
            data_start_row = current_row + 1
            worksheet.write_column(data_start_row, 0, dept_names)
            worksheet.write_column(data_start_row, 1, dept_employee_count)
            
            # Crear gráfico de dispersión
            chart_dept_employees = workbook.add_chart({'type': 'scatter'})
            chart_dept_employees.add_series({
                'name': 'Empleados por Departamento',
                'categories': ['Gráficos y Análisis', data_start_row, 0, data_start_row + len(dept_names) - 1, 0],
                'values': ['Gráficos y Análisis', data_start_row, 1, data_start_row + len(dept_employee_count) - 1, 1],
                'marker': {'type': 'circle', 'size': 10}
            })
            
            chart_dept_employees.set_title({'name': 'Empleados por Departamento'})
            chart_dept_employees.set_x_axis({'name': 'Departamento', 'num_format': '@'})
            chart_dept_employees.set_y_axis({'name': 'Cantidad de Empleados'})
            chart_dept_employees.set_style(11)
            chart_dept_employees.set_size({'width': 720, 'height': 400})
            worksheet.insert_chart(current_row, 3, chart_dept_employees)
            
            # Agregar también los datos en formato tabla
            current_row += 22  # Espacio para el gráfico
            worksheet.write(current_row, 0, 'Departamento', header_format)
            worksheet.write(current_row, 1, 'Cantidad de Empleados', header_format)
            current_row += 1
            
            for dept in department_totals:
                worksheet.write(current_row, 0, dept['name'], cell_format)
                worksheet.write(current_row, 1, dept['empleados'], count_format)
                current_row += 1
            
            current_row += 2  # Espacio extra
        
        # 4. Gráfico de dispersión por regla
        if rule_totals:
            worksheet.merge_range(current_row, 0, current_row, 6, 'DISPERSIÓN DE REGLAS SALARIALES', title_format)
            current_row += 1
            
            # Asignar valores de x (índice) para cada regla
            x_values = list(range(1, len(rule_totals) + 1))
            rule_names = [rule['name'] for rule in rule_totals]
            rule_values = [rule['total'] for rule in rule_totals]
            
            # Escribir datos para el gráfico
            data_start_row = current_row + 1
            worksheet.write_column(data_start_row, 0, x_values)
            worksheet.write_column(data_start_row, 1, rule_names)
            worksheet.write_column(data_start_row, 2, rule_values)
            
            # Crear gráfico de dispersión
            chart_rule_scatter = workbook.add_chart({'type': 'scatter'})
            chart_rule_scatter.add_series({
                'name': 'Valores por Regla',
                'categories': ['Gráficos y Análisis', data_start_row, 0, data_start_row + len(x_values) - 1, 0],
                'values': ['Gráficos y Análisis', data_start_row, 2, data_start_row + len(rule_values) - 1, 2],
                'marker': {'type': 'diamond', 'size': 8}
            })
            
            chart_rule_scatter.set_title({'name': 'Dispersión de Valores por Regla'})
            chart_rule_scatter.set_x_axis({'name': 'Índice de Regla'})
            chart_rule_scatter.set_y_axis({'name': 'Valor'})
            chart_rule_scatter.set_style(11)
            chart_rule_scatter.set_size({'width': 720, 'height': 400})
            worksheet.insert_chart(current_row, 3, chart_rule_scatter)
            
            current_row += 22  # Espacio para el gráfico
            
        # 5. Gráfico por cuenta analítica
        if analytic_totals:
            worksheet.merge_range(current_row, 0, current_row, 6, 'TOTALES POR CUENTA ANALÍTICA', title_format)
            current_row += 1
            
            # Encabezados
            headers = ['Cuenta Analítica', 'Empleados', 'Devengos', 'Deducciones', 'Neto a Pagar']
            for i, header in enumerate(headers):
                worksheet.write(current_row, i, header, header_format)
            current_row += 1
            
            # Datos
            for acc in analytic_totals:
                worksheet.write(current_row, 0, acc['name'], cell_format)
                worksheet.write(current_row, 1, acc['empleados'], count_format)
                worksheet.write(current_row, 2, acc['devengos'], number_format)
                worksheet.write(current_row, 3, acc['deducciones'], number_format)
                worksheet.write(current_row, 4, acc['neto'], number_format)
                current_row += 1
            
            # Gráfico de cuentas analíticas
            acc_chart = workbook.add_chart({'type': 'bar'})
            
            # Rango de datos para el gráfico
            start_row = current_row - len(analytic_totals)
            end_row = current_row - 1
            
            # Serie para neto
            acc_chart.add_series({
                'name': 'Neto a Pagar',
                'categories': ['Gráficos y Análisis', start_row, 0, end_row, 0],
                'values': ['Gráficos y Análisis', start_row, 4, end_row, 4],
                'data_labels': {'value': True}
            })
            
            acc_chart.set_title({'name': 'Neto a Pagar por Cuenta Analítica'})
            acc_chart.set_x_axis({'name': 'Cuenta Analítica'})
            acc_chart.set_y_axis({'name': 'Valor'})
            acc_chart.set_style(11)
            acc_chart.set_size({'width': 720, 'height': 400})
            
            worksheet.insert_chart(current_row, 0, acc_chart)
            current_row += 22  # Espacio para el gráfico
        
        # 6. Gráfico de valores pagados por entidad
        if entity_totals:
            worksheet.merge_range(current_row, 0, current_row, 6, 'VALORES PAGADOS POR ENTIDAD', title_format)
            current_row += 1
            
            # Preparar datos
            entity_names = [entity['name'] for entity in entity_totals]
            entity_values = [entity['total'] for entity in entity_totals]
            
            # Escribir datos para el gráfico
            data_start_row = current_row + 1
            worksheet.write_column(data_start_row, 0, entity_names)
            worksheet.write_column(data_start_row, 1, entity_values)
            
            # Crear gráfico de barras
            chart_entities = workbook.add_chart({'type': 'bar'})
            chart_entities.add_series({
                'name': 'Valores por Entidad',
                'categories': ['Gráficos y Análisis', data_start_row, 0, data_start_row + len(entity_names) - 1, 0],
                'values': ['Gráficos y Análisis', data_start_row, 1, data_start_row + len(entity_values) - 1, 1],
                'data_labels': {'value': True}
            })
            
            chart_entities.set_title({'name': 'Valores Pagados por Entidad'})
            chart_entities.set_x_axis({'name': 'Entidad'})
            chart_entities.set_y_axis({'name': 'Valor'})
            chart_entities.set_style(11)
            chart_entities.set_size({'width': 720, 'height': 400})
            worksheet.insert_chart(current_row, 3, chart_entities)
            
            # Agregar también los datos en formato tabla
            current_row += 22  # Espacio para el gráfico
            worksheet.write(current_row, 0, 'Entidad', header_format)
            worksheet.write(current_row, 1, 'Valor Total', header_format)
            current_row += 1
            
            for entity in entity_totals:
                worksheet.write(current_row, 0, entity['name'], cell_format)
                worksheet.write(current_row, 1, entity['total'], number_format)
                current_row += 1
                
            current_row += 2  # Espacio extra
        
        # 7. Gráfico global por concepto
        if payslips:
            # Agrupar datos por tipo de concepto (devengos, deducciones, etc.)
            concept_totals = {}
            
            # Obtener las listas de categorías permitidas
            earnings_codes_list = self.earnings_codes.split(',') if self.earnings_codes else []
            deductions_codes_list = self.deductions_codes.split(',') if self.deductions_codes else []
            
            for slip in payslips:
                for line in slip.line_ids:
                    # Determinar tipo de concepto
                    concept_type = 'Otros'
                    if line.category_id.code in earnings_codes_list:
                        concept_type = 'Devengos'
                    elif line.category_id.code in deductions_codes_list:
                        concept_type = 'Deducciones'
                    elif line.category_id.code == 'PROVISION':
                        concept_type = 'Provisiones'
                    elif line.salary_rule_id.code == 'TOTALDEV':
                        continue  # Ignorar, ya contabilizado en Devengos
                    elif line.salary_rule_id.code == 'TOTALDED':
                        continue  # Ignorar, ya contabilizado en Deducciones
                    elif line.salary_rule_id.code == 'NET':
                        concept_type = 'Neto a Pagar'
                    
                    if concept_type not in concept_totals:
                        concept_totals[concept_type] = 0
                    concept_totals[concept_type] += line.total
            
            # Preparar datos para gráfico
            worksheet.merge_range(current_row, 0, current_row, 6, 'DISTRIBUCIÓN GLOBAL POR CONCEPTO', title_format)
            current_row += 1
            
            concept_names = list(concept_totals.keys())
            concept_values = [concept_totals[name] for name in concept_names]
            
            # Escribir datos para el gráfico
            data_start_row = current_row + 1
            worksheet.write_column(data_start_row, 0, concept_names)
            worksheet.write_column(data_start_row, 1, concept_values)
            
            # Crear gráfico circular
            chart_concepts = workbook.add_chart({'type': 'pie'})
            chart_concepts.add_series({
                'name': 'Distribución por Concepto',
                'categories': ['Gráficos y Análisis', data_start_row, 0, data_start_row + len(concept_names) - 1, 0],
                'values': ['Gráficos y Análisis', data_start_row, 1, data_start_row + len(concept_values) - 1, 1],
                'data_labels': {'percentage': True, 'category': True, 'position': 'outside_end'}
            })
            
            chart_concepts.set_title({'name': 'Distribución Global por Concepto'})
            chart_concepts.set_style(10)
            chart_concepts.set_size({'width': 720, 'height': 400})
            worksheet.insert_chart(current_row, 3, chart_concepts)
            
            # Agregar también los datos en formato tabla
            current_row += 22  # Espacio para el gráfico
            worksheet.write(current_row, 0, 'Concepto', header_format)
            worksheet.write(current_row, 1, 'Valor Total', header_format)
            current_row += 1
            
            for name, value in concept_totals.items():
                worksheet.write(current_row, 0, name, cell_format)
                worksheet.write(current_row, 1, value, number_format)
                current_row += 1


    def generate_excel(self):
        """Genera el informe en Excel aplicando todos los filtros y agrupaciones."""
        # Obtener liquidaciones aplicando todos los filtros
        obj_payslips, min_date, max_date = self._get_payslips()
        
        if not obj_payslips:
            raise ValidationError(_('No se encontraron nóminas con los filtros seleccionados.'))
            
        # Preparar datos del informe
        df_report = self._prepare_report_data(obj_payslips, min_date, max_date)
        
        if len(df_report) == 0:
            raise ValidationError(_('No se ha encontrado información con los filtros seleccionados, por favor verificar.'))
        
        # Obtener datos para métricas y gráficos
        company_data = self._get_company_data()
        summary_metrics = self._get_summary_metrics(df_report, obj_payslips)
        category_totals = self._get_category_totals(obj_payslips)
        department_totals = self._get_department_totals(obj_payslips)
        analytic_totals = self._get_analytic_account_totals(obj_payslips)
        rule_totals = self._get_rule_totals(obj_payslips)
        entity_totals = self._get_entity_totals(obj_payslips)
        
        # Crear Excel
        filename = 'Informe Liquidación.xlsx'
        stream = io.BytesIO()
        writer = pd.ExcelWriter(stream, engine='xlsxwriter')
        workbook = writer.book
        
        # Crear formatos usados en todo el informe
        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#1F497D',
            'font_color': 'white',
            'align': 'center',
            'valign': 'vcenter',
            'border': 1
        })
        
        group_title_format = workbook.add_format({
            'bold': True,
            'bg_color': '#4F81BD',
            'font_color': 'white',
            'align': 'left',
            'valign': 'vcenter',
            'border': 1,
            'font_size': 12
        })
        
        cell_format = workbook.add_format({
            'border': 1,
            'align': 'left',
            'valign': 'vcenter'
        })
        
        number_format = workbook.add_format({
            'border': 1,
            'align': 'right',
            'num_format': '#,##0.00'
        })
        
        subtotal_format = workbook.add_format({
            'bold': True, 
            'bg_color': '#E0E0E0',
            'border': 1,
            'num_format': '#,##0.00',
            'align': 'right'
        })
        
        total_format = workbook.add_format({
            'bold': True, 
            'bg_color': '#C0C0C0',
            'border': 1,
            'num_format': '#,##0.00',
            'align': 'right'
        })
        
        title_format = workbook.add_format({
            'bold': True, 
            'font_size': 14, 
            'align': 'left',
            'valign': 'vcenter',
            'font_color': '#1F497D'
        })
        
        # Crear hoja principal
        worksheet = workbook.add_worksheet('Liquidación')
        
        # Agregar encabezado con datos de la empresa
        next_row = self._add_company_header(worksheet, workbook, company_data)
        
        # Agregar cuadro de resumen
        next_row = self._add_summary_dashboard(worksheet, workbook, summary_metrics, next_row)
        
        # Añadir título del informe
        worksheet.merge_range(next_row, 0, next_row, 8, 'INFORME DE LIQUIDACIÓN', title_format)
        next_row += 1
        
        text_dates = 'Fechas Liquidación: %s a %s' % (min_date.strftime('%Y-%m-%d') if min_date else '', 
                                                    max_date.strftime('%Y-%m-%d') if max_date else '')
        worksheet.merge_range(next_row, 0, next_row, 8, text_dates, title_format)
        next_row += 2  # Agregar espacio
        
        # Determinar columnas de índice según las opciones seleccionadas
        columns_index = ['Identificación', 'Empleado']
        
        # Configurar columnas según la agrupación seleccionada
        group_by_field = 'Departamento'  # Valor por defecto
        if self.group_by == 'department':
            group_by_field = 'Departamento'
        elif self.group_by == 'job':
            group_by_field = 'Cargo'
            columns_index.append('Cargo')
        elif self.group_by == 'analytic_account':
            group_by_field = 'Cuenta Analítica'
            columns_index.append('Cuenta Analítica')
        elif self.group_by == 'risk_level':
            group_by_field = 'Nivel de Riesgo ARL'
            columns_index.append('Nivel de Riesgo ARL')
        elif self.group_by == 'branch':
            group_by_field = 'Seccional'
            columns_index.append('Seccional')
        elif self.group_by == 'job_placement':
            group_by_field = 'Ubicación Laboral'
            columns_index.append('Ubicación Laboral')
        elif self.group_by == 'month':
            group_by_field = 'Grupo'  # En este caso, Grupo contiene el mes
        else:
            # Si no hay agrupación, usamos un valor único para agrupar todo junto
            group_by_field = 'Grupo'
        
        # Agregar columnas según las opciones de visualización seleccionadas
        if self.show_date_of_entry:
            columns_index.append('Fecha Ingreso')
        if self.show_job_placement and self.group_by != 'job_placement':
            columns_index.append('Ubicación Laboral')
        if self.show_sectional and self.group_by != 'branch':
            columns_index.append('Seccional')
        if self.show_department and self.group_by != 'department':
            columns_index.append('Departamento')
        if self.show_analytical_account and self.group_by != 'analytic_account':
            columns_index.append('Cuenta Analítica')
        if self.show_job and self.group_by != 'job':
            columns_index.append('Cargo')
        if self.show_sena_code:
            columns_index.append('Código SENA')
        if self.show_basic_salary:
            columns_index.append('Salario Base')
        if self.show_dispersing_account:
            columns_index.append('Cuenta Dispersora')
        if self.show_bank_officer:
            columns_index.append('Banco')
        if self.show_bank_account_officer:
            columns_index.append('Cuenta Bancaria')
        if self.show_risk_level and self.group_by != 'risk_level':
            columns_index.append('Nivel de Riesgo ARL')
        
        # Verificar si hay reglas/categorías seleccionadas
        has_rule_filters = bool(self.salary_rule_ids or self.rule_category_ids)
        
        # Obtener listas de categorías permitidas
        earnings_codes_list = self.earnings_codes.split(',') if self.earnings_codes else []
        deductions_codes_list = self.deductions_codes.split(',') if self.deductions_codes else []
        
        # Identificar reglas salariales únicas en los datos
        # Obtener reglas en el orden específico solicitado
        rule_names = []
        
        # 1. Devengos en el orden especificado
        if 'Código Categoría' in df_report.columns:
            for code in earnings_codes_list:
                # Filtrar reglas de esta categoría específica
                category_rules = df_report[df_report['Código Categoría'] == code]['Regla Salarial'].unique()
                
                # Agregar reglas de esta categoría al listado ordenado
                for rule in category_rules:
                    if rule not in rule_names:
                        rule_names.append(rule)
            
            # 2. Añadir TOTALDEV después de devengos
            if 'TOTALDEV' in df_report['Regla Salarial'].unique():
                rule_names.append('TOTALDEV')
            
            # 3. Deducciones en el orden especificado
            for code in deductions_codes_list:
                # Filtrar reglas de esta categoría específica
                category_rules = df_report[df_report['Código Categoría'] == code]['Regla Salarial'].unique()
                
                # Agregar reglas de esta categoría al listado ordenado
                for rule in category_rules:
                    if rule not in rule_names:
                        rule_names.append(rule)
            
            # 4. Añadir TOTALDED después de deducciones
            if 'TOTALDED' in df_report['Regla Salarial'].unique():
                rule_names.append('TOTALDED')
            
            # 5. Añadir NET al final
            if 'NET' in df_report['Regla Salarial'].unique():
                rule_names.append('NET')
            
            # 6. Añadir provisiones si están activas
            if self.show_provisions:
                provision_rules = df_report[df_report['Código Categoría'] == 'PROVISION']['Regla Salarial'].unique()
                for rule in provision_rules:
                    if rule not in rule_names:
                        rule_names.append(rule)
        else:
            # Si no hay columna de código de categoría, usar todas las reglas disponibles
            rule_names = sorted(df_report['Regla Salarial'].unique())
        
        # Escribir encabezados de columnas
        for col, header in enumerate(columns_index):
            worksheet.write(next_row, col, header, header_format)
        
        # Si se muestran datos de seguridad social, añadir esas columnas
        if self.show_social_security:
            ss_headers = []
            
            # Nivel de riesgo (solo porcentaje)
            ss_headers.append('% Nivel Riesgo')
            
            # Salud
            ss_headers.extend(['Salud Empresa', 'Salud Empleado', 'Total Salud', 'Diferencia Salud'])
            
            # Pensión
            ss_headers.extend(['Pensión Empresa', 'Pensión Empleado', 'Total Pensión', 'Diferencia Pensión'])
            
            # Parafiscales
            ss_headers.extend(['ARL', 'CCF', 'SENA', 'ICBF'])
            
            # Escribir encabezados de seguridad social
            for i, header in enumerate(ss_headers):
                worksheet.write(next_row, len(columns_index) + len(rule_names) + i, header, header_format)
        
        # Escribir encabezados de reglas salariales
        for col, rule_name in enumerate(rule_names):
            worksheet.write(next_row, col + len(columns_index), rule_name, header_format)
        
        next_row += 1
        
        # Filtrar solo las filas de empleados (no subtotales/totales)
        df_employees = df_report[df_report['Item'] < 400000].copy()
        
        # Agrupar por el campo seleccionado
        if group_by_field in df_employees.columns:
            groups = df_employees[group_by_field].unique()
        else:
            # Si el campo no existe, usar un grupo único
            groups = ['Todos']
            df_employees['Grupo'] = 'Todos'
            group_by_field = 'Grupo'
        
        # Inicializar arrays para totales generales
        grand_totals = {rule: 0 for rule in rule_names}
        grand_totals_ss = {
            'SS_Nivel_Riesgo': 0,
            'SS_Salud_Empresa': 0,
            'SS_Salud_Empleado': 0,
            'SS_Salud_Total': 0,
            'SS_Salud_Diferencia': 0,
            'SS_Pensión_Empresa': 0, 
            'SS_Pensión_Empleado': 0,
            'SS_Pensión_Total': 0,
            'SS_Pensión_Diferencia': 0,
            'SS_ARL': 0,
            'SS_CCF': 0,
            'SS_SENA': 0,
            'SS_ICBF': 0
        }
        
        # Procesar cada grupo
        for group in sorted(groups):
            if pd.isna(group):
                group_name = 'Sin Clasificar'
            else:
                group_name = group
            
            # Filtrar empleados del grupo actual
            group_employees = df_employees[df_employees[group_by_field] == group]
            
            # Escribir título del grupo
            header_width = len(columns_index) + len(rule_names)
            if self.show_social_security:
                header_width += len(ss_headers)
                
            worksheet.merge_range(
                next_row, 0, next_row, header_width - 1,
                f"{group_name.upper()} - {len(group_employees['Identificación'].unique())} EMPLEADOS",
                group_title_format
            )
            next_row += 1
            
            # Inicializar subtotales del grupo
            group_subtotals = {rule: 0 for rule in rule_names}
            group_subtotals_ss = {
                'SS_Nivel_Riesgo': 0,
                'SS_Salud_Empresa': 0,
                'SS_Salud_Empleado': 0,
                'SS_Salud_Total': 0,
                'SS_Salud_Diferencia': 0,
                'SS_Pensión_Empresa': 0, 
                'SS_Pensión_Empleado': 0,
                'SS_Pensión_Total': 0,
                'SS_Pensión_Diferencia': 0,
                'SS_ARL': 0,
                'SS_CCF': 0,
                'SS_SENA': 0,
                'SS_ICBF': 0
            }
            
            # Procesar cada empleado del grupo
            for _, emp_id in enumerate(group_employees['Identificación'].unique()):
                employee_data = group_employees[group_employees['Identificación'] == emp_id].iloc[0]
                
                # Escribir datos del empleado
                for col, field in enumerate(columns_index):
                    value = employee_data.get(field, '')
                    worksheet.write(next_row, col, value, cell_format)
                
                # Escribir valores de seguridad social si corresponde
                if self.show_social_security:
                    # Usar los datos de SS del empleado
                    ss_values = [
                        employee_data.get('SS_Nivel_Riesgo', 0),
                        employee_data.get('SS_Salud_Empresa', 0),
                        employee_data.get('SS_Salud_Empleado', 0),
                        employee_data.get('SS_Salud_Total', 0),
                        employee_data.get('SS_Salud_Diferencia', 0),
                        employee_data.get('SS_Pensión_Empresa', 0),
                        employee_data.get('SS_Pensión_Empleado', 0),
                        employee_data.get('SS_Pensión_Total', 0),
                        employee_data.get('SS_Pensión_Diferencia', 0),
                        employee_data.get('SS_ARL', 0),
                        employee_data.get('SS_CCF', 0),
                        employee_data.get('SS_SENA', 0),
                        employee_data.get('SS_ICBF', 0)
                    ]
                    
                    # Escribir valores de SS
                    for i, value in enumerate(ss_values):
                        worksheet.write(next_row, len(columns_index) + len(rule_names) + i, value, number_format)
                    
                    # Acumular para subtotales
                    group_subtotals_ss['SS_Nivel_Riesgo'] += employee_data.get('SS_Nivel_Riesgo', 0)
                    group_subtotals_ss['SS_Salud_Empresa'] += employee_data.get('SS_Salud_Empresa', 0)
                    group_subtotals_ss['SS_Salud_Empleado'] += employee_data.get('SS_Salud_Empleado', 0)
                    group_subtotals_ss['SS_Salud_Total'] += employee_data.get('SS_Salud_Total', 0)
                    group_subtotals_ss['SS_Salud_Diferencia'] += employee_data.get('SS_Salud_Diferencia', 0)
                    group_subtotals_ss['SS_Pensión_Empresa'] += employee_data.get('SS_Pensión_Empresa', 0)
                    group_subtotals_ss['SS_Pensión_Empleado'] += employee_data.get('SS_Pensión_Empleado', 0)
                    group_subtotals_ss['SS_Pensión_Total'] += employee_data.get('SS_Pensión_Total', 0)
                    group_subtotals_ss['SS_Pensión_Diferencia'] += employee_data.get('SS_Pensión_Diferencia', 0)
                    group_subtotals_ss['SS_ARL'] += employee_data.get('SS_ARL', 0)
                    group_subtotals_ss['SS_CCF'] += employee_data.get('SS_CCF', 0)
                    group_subtotals_ss['SS_SENA'] += employee_data.get('SS_SENA', 0)
                    group_subtotals_ss['SS_ICBF'] += employee_data.get('SS_ICBF', 0)
                
                # Escribir valores de las reglas salariales
                for col, rule_name in enumerate(rule_names):
                    # Buscar el valor de esta regla para este empleado
                    rule_value = 0
                    for _, row in df_report[(df_report['Identificación'] == emp_id) & 
                                        (df_report['Regla Salarial'] == rule_name)].iterrows():
                        rule_value += row['Monto']
                    
                    # Si no hay valor específico y es SUELDO, usar el salario base
                    if rule_value == 0 and rule_name == 'SUELDO' and 'Salario Base' in employee_data:
                        rule_value = employee_data['Salario Base']
                    
                    # Escribir valor
                    worksheet.write(next_row, col + len(columns_index), rule_value, number_format)
                    
                    # Acumular para subtotales
                    group_subtotals[rule_name] += rule_value
                
                next_row += 1
            
            # Escribir subtotal del grupo
            worksheet.merge_range(
                next_row, 0, next_row, len(columns_index) - 1,
                f"SUBTOTAL {group_name.upper()}",
                subtotal_format
            )
            
            # Escribir valores de subtotales
            for col, rule_name in enumerate(rule_names):
                worksheet.write(next_row, col + len(columns_index), group_subtotals[rule_name], subtotal_format)
                # Acumular para total general
                grand_totals[rule_name] += group_subtotals[rule_name]
            
            # Escribir subtotales de seguridad social
            if self.show_social_security:
                ss_subtotals = [
                    group_subtotals_ss['SS_Nivel_Riesgo'] / len(group_employees['Identificación'].unique()) if len(group_employees['Identificación'].unique()) > 0 else 0,  # Promedio para nivel de riesgo
                    group_subtotals_ss['SS_Salud_Empresa'],
                    group_subtotals_ss['SS_Salud_Empleado'],
                    group_subtotals_ss['SS_Salud_Total'],
                    group_subtotals_ss['SS_Salud_Diferencia'],
                    group_subtotals_ss['SS_Pensión_Empresa'],
                    group_subtotals_ss['SS_Pensión_Empleado'],
                    group_subtotals_ss['SS_Pensión_Total'],
                    group_subtotals_ss['SS_Pensión_Diferencia'],
                    group_subtotals_ss['SS_ARL'],
                    group_subtotals_ss['SS_CCF'],
                    group_subtotals_ss['SS_SENA'],
                    group_subtotals_ss['SS_ICBF']
                ]
                
                # Escribir subtotales de SS
                for i, value in enumerate(ss_subtotals):
                    worksheet.write(next_row, len(columns_index) + len(rule_names) + i, value, subtotal_format)
                
                # Acumular para totales generales
                for key in grand_totals_ss:
                    if key == 'SS_Nivel_Riesgo':
                        continue  # Este se calculará como promedio al final
                    grand_totals_ss[key] += group_subtotals_ss[key]
            
            next_row += 2  # Espacio entre grupos
        
        # Escribir total general
        worksheet.merge_range(
            next_row, 0, next_row, len(columns_index) - 1,
            "TOTAL GENERAL",
            total_format
        )
        
        # Escribir valores de totales generales
        for col, rule_name in enumerate(rule_names):
            worksheet.write(next_row, col + len(columns_index), grand_totals[rule_name], total_format)
        
        # Escribir totales generales de seguridad social
        if self.show_social_security:
            # Calcular promedio de nivel de riesgo
            promedio_riesgo = 0
            total_empleados = df_employees['Identificación'].nunique()
            if total_empleados > 0:
                # Calcular promedio de nivel de riesgo
                empleados_con_riesgo = df_employees[df_employees['SS_Nivel_Riesgo'] > 0]['Identificación'].nunique()
                if empleados_con_riesgo > 0:
                    promedio_riesgo = df_employees['SS_Nivel_Riesgo'].sum() / empleados_con_riesgo
            
            ss_totals = [
                promedio_riesgo,
                grand_totals_ss['SS_Salud_Empresa'],
                grand_totals_ss['SS_Salud_Empleado'],
                grand_totals_ss['SS_Salud_Total'],
                grand_totals_ss['SS_Salud_Diferencia'],
                grand_totals_ss['SS_Pensión_Empresa'],
                grand_totals_ss['SS_Pensión_Empleado'],
                grand_totals_ss['SS_Pensión_Total'],
                grand_totals_ss['SS_Pensión_Diferencia'],
                grand_totals_ss['SS_ARL'],
                grand_totals_ss['SS_CCF'],
                grand_totals_ss['SS_SENA'],
                grand_totals_ss['SS_ICBF']
            ]
            
            # Escribir totales de SS
            for i, value in enumerate(ss_totals):
                worksheet.write(next_row, len(columns_index) + len(rule_names) + i, value, total_format)
        
        next_row += 2  # Espacio antes de firmas
        
        # Ajustar anchos de columna
        for i, field in enumerate(columns_index):
            max_len = max(len(str(field)), 15)  # Mínimo 15 caracteres
            worksheet.set_column(i, i, max_len + 2)
        
        # Ajustar anchos para columnas de reglas
        for i, rule_name in enumerate(rule_names):
            col_idx = i + len(columns_index)
            max_len = max(len(str(rule_name)), 12)  # Mínimo 12 caracteres
            worksheet.set_column(col_idx, col_idx, max_len + 2)
        
        # Ajustar anchos para columnas de seguridad social
        if self.show_social_security:
            for i, header in enumerate(ss_headers):
                col_idx = i + len(columns_index) + len(rule_names)
                max_len = max(len(str(header)), 12)  # Mínimo 12 caracteres
                worksheet.set_column(col_idx, col_idx, max_len + 2)
        
        worksheet.set_zoom(80)
        
        # Agregar hoja de gráficos y análisis
        self._add_summary_charts(workbook, category_totals, department_totals, analytic_totals, rule_totals, entity_totals, obj_payslips)
        
        # Firmas
        obj_signature = self.get_hr_payslip_template_signature()
        cell_format_firma = workbook.add_format({'bold': True, 'align': 'center', 'top': 1})
        cell_format_txt_firma = workbook.add_format({'bold': True, 'align': 'center'})
        
        if obj_signature:
            if obj_signature.signature_prepared:
                worksheet.merge_range(next_row, 1, next_row, 2, 'ELABORO', cell_format_firma)
                if obj_signature.txt_signature_prepared:
                    worksheet.merge_range(next_row + 1, 1, next_row + 1, 2, obj_signature.txt_signature_prepared, cell_format_txt_firma)
            if obj_signature.signature_reviewed:
                worksheet.merge_range(next_row, 4, next_row, 5, 'REVISO', cell_format_firma)
                if obj_signature.txt_signature_reviewed:
                    worksheet.merge_range(next_row + 1, 4, next_row + 1, 5, obj_signature.txt_signature_reviewed, cell_format_txt_firma)
            if obj_signature.signature_approved:
                worksheet.merge_range(next_row, 7, next_row, 8, 'APROBO', cell_format_firma)
                if obj_signature.txt_signature_approved:
                    worksheet.merge_range(next_row + 1, 7, next_row + 1, 8, obj_signature.txt_signature_approved, cell_format_txt_firma)
        else:
            worksheet.merge_range(next_row, 1, next_row, 2, 'ELABORO', cell_format_firma)
            worksheet.merge_range(next_row, 4, next_row, 5, 'REVISO', cell_format_firma)
            worksheet.merge_range(next_row, 7, next_row, 8, 'APROBO', cell_format_firma)
        
        # Guardar excel
        writer.close()

        self.write({
            'excel_file': base64.b64encode(stream.getvalue()).decode('utf-8'),
            'excel_file_name': filename,
        })
        
        action = {
            'name': filename,
            'type': 'ir.actions.act_url',
            'url': "web/content/?model=hr.payroll.report.lavish.filter&id=" + str(self.id) + "&filename_field=excel_file_name&field=excel_file&download=true&filename=" + self.excel_file_name,
            'target': 'self',
        }
        return action



    def _obtener_parametros_anuales(self):
        annual_params = self.env["hr.annual.parameters"].search([("year", "=", 2025)], limit=1)
        if not annual_params:
            raise UserError(_("No se encontraron parámetros anuales para el año %s") % 2025)
        return annual_params

    def generate_pdf(self):
        """Genera un informe PDF con tabla simplificada y correctamente alineada."""
        # Importaciones necesarias
        from reportlab.pdfgen.canvas import Canvas
        from reportlab.lib.pagesizes import letter, landscape
        from reportlab.lib import colors
        from reportlab.lib.units import inch, cm
        from reportlab.lib.utils import ImageReader
        from datetime import datetime
        
        # Obtener nóminas con filtros aplicados
        payslips, min_date, max_date = self._get_payslips()
        
        if not payslips:
            raise ValidationError(_('No se encontraron nóminas con los filtros seleccionados.'))
        
        # Obtener parámetros anuales para Colombia basados en la fecha más reciente
        if max_date:
            year = max_date.year
            annual_params = self.env["hr.annual.parameters"].search([("year", "=", year)], limit=1)
            if not annual_params:
                raise UserError(_("No se encontraron parámetros anuales para el año %s") % year)
        else:
            raise UserError(_("No se pudo determinar la fecha para los parámetros anuales."))
        
        # Obtener datos de la empresa para el encabezado
        company_data = self._get_company_data()
        
        # Calcular métricas resumen
        summary_metrics = self._get_summary_metrics(None, payslips)
        
        # Obtener listas de categorías permitidas
        earnings_codes_list = self.earnings_codes.split(',') if self.earnings_codes else []
        deductions_codes_list = self.deductions_codes.split(',') if self.deductions_codes else []
        
        # Crear buffer y canvas
        buffer = io.BytesIO()
        pagesize = landscape(letter)
        canvas = Canvas(buffer, pagesize=pagesize)
        page_width, page_height = pagesize  # Renombradas para evitar conflictos
        
        # Definir colores
        color_titulo = colors.HexColor(0x1F497D)  # Azul oscuro
        
        # Variable para almacenar información sobre la tabla
        table_columns = []
        table_x_positions = []
        
        # Función para dibujar el encabezado - sin tabla, organizado en filas
        def draw_header(canvas, page_width, page_height):
            # Logo
            if company_data.get('logo'):
                logo_data = io.BytesIO(base64.b64decode(company_data['logo']))
                img = ImageReader(logo_data)
                canvas.drawImage(img, 30, page_height - 65, width=50, height=40, mask='auto')
            
            # Línea horizontal superior
            canvas.setStrokeColor(colors.black)
            canvas.line(30, page_height-25, page_width-30, page_height-25)
            
            # Información empresa - Primera fila
            company_name = company_data.get('name', 'VITALIAH SAS')
            canvas.setFont('Helvetica-Bold', 14)
            canvas.setFillColor(color_titulo)
            canvas.drawString(90, page_height - 40, company_name)
            
            # Título informe - Primera fila, alineado a la derecha
            canvas.setFont('Helvetica-Bold', 14)
            canvas.setFillColor(color_titulo)
            canvas.drawString(page_width - 275, page_height - 40, "INFORME DE LIQUIDACIÓN")
            
            # Segunda fila - NIT y Fechas
            canvas.setFont('Helvetica', 9)
            canvas.setFillColor(colors.black)
            canvas.drawString(90, page_height - 55, f"NIT: {company_data.get('nit', '')}")
            
            # Fechas - Segunda fila, alineado a la derecha
            date_text = f"Fechas: {min_date.strftime('%Y-%m-%d') if min_date else ''} a {max_date.strftime('%Y-%m-%d') if max_date else ''}"
            canvas.drawString(page_width - 275, page_width - 55, date_text)
            
            # Tercera fila - Dirección
            address = company_data.get('street', '') + ', ' + company_data.get('city', '') + ', COLOMBIA'
            canvas.drawString(90, page_height - 70, address)
            
            # Generado por y hora - Tercera fila, alineado a la derecha
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            user_name = self.env.user.name
            canvas.setFont('Helvetica', 8)
            canvas.drawString(page_width - 375, page_height - 70, f"Generado por: {user_name} - {current_time}")
            
            # Cuarta fila - Información de Salario Mínimo y Auxilio de Transporte
            canvas.setFont('Helvetica-Bold', 8)
            canvas.drawString(90, page_height - 85, f"SMMLV {annual_params.year}: ${annual_params.smmlv_monthly:,.0f}")
            canvas.drawString(page_width - 375, page_height - 85, f"Auxilio de Transporte: ${annual_params.transportation_assistance_monthly:,.0f}")
            
            # Línea horizontal inferior
            canvas.line(30, page_height-100, page_width-30, page_height-100)
        
        # Función para dibujar un resumen en la parte superior
        def draw_top_summary(canvas, page_width, y_position):
            # Total de empleados
            total_employees = len(payslips.mapped('employee_id'))
            
            # Calcular días trabajados vs programados
            total_days_scheduled = 0
            total_days_worked = 0
            for payslip in payslips:
                # Días WORK100
                work_days = payslip.worked_days_line_ids.filtered(
                    lambda w: w.work_entry_type_id.code == 'WORK100'
                )
                if work_days:
                    total_days_worked += sum(work_days.mapped('number_of_days'))
                
                # Todos los días programados
                total_days_scheduled += sum(payslip.worked_days_line_ids.mapped('number_of_days'))
            
            # Calcular porcentaje de trabajo
            work_percentage = (total_days_worked / total_days_scheduled * 100) if total_days_scheduled > 0 else 0
            
            # Título
            canvas.setFont('Helvetica-Bold', 11)
            canvas.setFillColor(color_titulo)
            canvas.drawString(30, y_position, "COSTOS LABORALES PARA LAS EMPRESAS")
            
            # Líneas horizontales
            canvas.setStrokeColor(colors.black)
            canvas.line(30, y_position - 5, page_width - 30, y_position - 5)
            canvas.line(30, y_position - 140, page_width - 30, y_position - 140)
            
            # Elementos del resumen
            text_labels = [
                "Total Devengos",
                "Total Deducciones",
                "Neto a Pagar",
                "Días Trabajados",
                "Días Ausencias",
                "Porcentaje Trabajado",
                "Total Empleados"
            ]
            
            text_values = [
                f"${summary_metrics['total_devengos']:,.0f}",
                f"$-{summary_metrics['total_deducciones']:,.0f}",
                f"${summary_metrics['neto_pagar']:,.0f}",
                f"WORK100: {total_days_worked}",
                f"{total_days_scheduled - total_days_worked}",
                f"{work_percentage:.2f}%",
                f"{total_employees}"
            ]
            
            # Posicionar etiquetas y valores - primera columna
            for i, (label, value) in enumerate(zip(text_labels[:4], text_values[:4])):
                y = y_position - 30 - (i * 20)
                
                # Etiqueta
                canvas.setFont('Helvetica', 9)
                canvas.setFillColor(colors.black)
                canvas.drawString(50, y, label)
                
                # Valor
                canvas.setFont('Helvetica-Bold', 9)
                canvas.setFillColor(colors.black)
                canvas.drawString(250, y, value)
            
            # Posicionar etiquetas y valores - segunda columna
            for i, (label, value) in enumerate(zip(text_labels[4:], text_values[4:])):
                y = y_position - 30 - (i * 20)
                
                # Etiqueta
                canvas.setFont('Helvetica', 9)
                canvas.setFillColor(colors.black)
                canvas.drawString(350, y, label)
                
                # Valor
                canvas.setFont('Helvetica-Bold', 9)
                canvas.setFillColor(colors.black)
                canvas.drawString(550, y, value)
            
            return y_position - 150  # Menor espacio después del resumen
        
        # Función para dibujar el encabezado de la tabla
        def draw_table_header(canvas, y_position, columns, x_positions):
            header_height = 20
            canvas.setFillColor(color_titulo)
            canvas.rect(10, y_position - header_height, page_width - 20, header_height, fill=True, stroke=False)
            
            # Textos de encabezado
            canvas.setFillColor(colors.white)
            canvas.setFont('Helvetica-Bold', 5)
            
            for i, col in enumerate(columns):
                x = x_positions[i]
                name = col["name"]
                width = col["width"]
                
                if col["align"] == "left":
                    canvas.drawString(x + 2, y_position - 14, name)
                elif col["align"] == "center":
                    text_width = canvas.stringWidth(name, 'Helvetica-Bold', 5)
                    canvas.drawString(x + (width - text_width) / 2, y_position - 14, name)
                else:  # right
                    text_width = canvas.stringWidth(name, 'Helvetica-Bold', 5)
                    canvas.drawString(x + width - text_width - 2, y_position - 14, name)
            
            return y_position - header_height
        
        # Función para dibujar la tabla principal - con todas las categorías ordenadas
        def draw_main_table(canvas, page_width, page_height, y_position):
            # Guardar referencia a las variables globales
            nonlocal table_columns, table_x_positions
            
            # Determinar las columnas visibles y sus anchos
            table_width = page_width - 20  # Reducir aún más el margen
            
            # Definir orden de categorías según los códigos proporcionados
            ordered_earnings_codes = [
                'BASIC', 'AUX', 'AUS', 'ALW', 'ACCIDENTE_TRABAJO',
                'DEV_NO_SALARIAL', 'DEV_SALARIAL', 'HEYREC',
                'COMISIONES', 'INCAPACIDAD', 'LICENCIA_MATERNIDAD',
                'LICENCIA_NO_REMUNERADA', 'LICENCIA_REMUNERADA',
                'PRESTACIONES_SOCIALES', 'PRIMA', 'VACACIONES'
            ]
            
            ordered_deductions_codes = [
                'DED', 'DEDUCCIONES', 'SANCIONES',
                'DESCUENTO_AFC', 'SSOCIAL'
            ]
            
            # Identificar categorías con valores
            visible_categories = {}
            
            # Diccionarios para mapear códigos a nombres más cortos y obtener nombre de categoría
            code_to_shortname = {
                'BASIC': 'Básico',
                'AUX': 'Auxilio',
                'AUS': 'Aus',
                'ALW': 'Alw',
                'ACCIDENTE_TRABAJO': 'AccTrab',
                'DEV_NO_SALARIAL': 'DevNoSal',
                'DEV_SALARIAL': 'DevSal',
                'HEYREC': 'HorExt',
                'COMISIONES': 'Comis',
                'INCAPACIDAD': 'Incap',
                'LICENCIA_MATERNIDAD': 'LicMat',
                'LICENCIA_NO_REMUNERADA': 'LicNoRem',
                'LICENCIA_REMUNERADA': 'LicRem',
                'PRESTACIONES_SOCIALES': 'PresSoc',
                'PRIMA': 'Prima',
                'VACACIONES': 'Vacac',
                'DED': 'Ded',
                'DEDUCCIONES': 'Deduc',
                'SANCIONES': 'Sanc',
                'DESCUENTO_AFC': 'AFC',
                'SSOCIAL': 'SSocial'
            }
            
            # Mapeo de códigos a categorías reales en Odoo
            category_names = {}
            
            # Recolectar todas las categorías utilizadas
            for payslip in payslips:
                for line in payslip.line_ids:
                    if line.total == 0:
                        continue
                    
                    category_code = line.category_id.code if line.category_id else ''
                    category_name = line.category_id.name if line.category_id else ''
                    rule_name = line.salary_rule_id.name if line.salary_rule_id else ''
                    rule_code = line.salary_rule_id.code if line.salary_rule_id else ''
                    
                    # Guardar nombre de categoría real
                    if category_code and category_code not in category_names and category_name:
                        category_names[category_code] = category_name
                    
                    # Reglas especiales
                    if rule_code == 'TOTALDEV':
                        visible_categories['TOTALDEV'] = 'Total Dev'
                    elif rule_code == 'TOTALDED':
                        visible_categories['TOTALDED'] = 'Total Ded'
                    elif rule_code == 'NET':
                        visible_categories['NET'] = 'Neto'
                    elif category_code in earnings_codes_list + deductions_codes_list:
                        short_name = code_to_shortname.get(category_code, category_code[:6])
                        visible_categories[category_code] = short_name
            
            # Definir columnas básicas
            columns = []
            columns.append({"name": "Nombre", "width": 110, "align": "left"})
            columns.append({"name": "Identif.", "width": 70, "align": "left"})
            columns.append({"name": "Días", "width": 25, "align": "center"})
            
            # Agregar columnas de devengos en el orden especificado
            for code in ordered_earnings_codes:
                if code in visible_categories:
                    # Usar el nombre real de la categoría si está disponible
                    display_name = category_names.get(code, visible_categories[code])
                    if len(display_name) > 7:
                        display_name = display_name[:6] + "."
                    
                    columns.append({
                        "name": display_name, 
                        "code": code,
                        "width": 38, 
                        "align": "right"
                    })
            
            # Agregar columnas de deducciones en el orden especificado
            for code in ordered_deductions_codes:
                if code in visible_categories:
                    # Usar el nombre real de la categoría si está disponible
                    display_name = category_names.get(code, visible_categories[code])
                    if len(display_name) > 7:
                        display_name = display_name[:6] + "."
                    
                    columns.append({
                        "name": display_name, 
                        "code": code,
                        "width": 38, 
                        "align": "right"
                    })
            
            # Agregar columnas de totales al final
            if 'TOTALDEV' in visible_categories:
                columns.append({"name": "Total Dev", "code": "TOTALDEV", "width": 52, "align": "right"})
            if 'TOTALDED' in visible_categories:
                columns.append({"name": "Total Ded", "code": "TOTALDED", "width": 52, "align": "right"})
            if 'NET' in visible_categories:
                columns.append({"name": "Neto", "code": "NET", "width": 52, "align": "right"})
            
            # Calcular espacio restante para columna de firma
            columns_width_used = sum(col["width"] for col in columns) + 10  # 10 px margen izquierdo
            remaining_width = page_width - 20 - columns_width_used
            
            # Columna de firma - ajustar para llegar al borde derecho
            columns.append({"name": "Firma", "code": "FIRMA", "width": max(80, remaining_width), "align": "center"})
            
            # Guardar columnas para uso posterior
            table_columns = columns
            
            # Calcular posiciones X acumuladas
            x_positions = [10]  # Comenzar desde un margen izquierdo más pequeño
            for col in columns:
                next_x = x_positions[-1] + col["width"]
                x_positions.append(next_x)
            
            # Guardar posiciones X para uso posterior
            table_x_positions = x_positions
            
            # Dibujar encabezado de la tabla
            y_position = draw_table_header(canvas, y_position, columns, x_positions)
            
            # Recolectar valores para totales y categorías
            totals_by_category = {}
            totals_by_column = {}
            
            # Dibujar filas de datos
            row_height = 16
            
            # Preparar datos para cada empleado
            employee_rows = []
            for payslip in payslips:
                employee = payslip.employee_id
                
                # Obtener datos básicos
                employee_name = employee.name
                
                # Obtener identificación
                identification = employee.identification_id or ''
                
                # Obtener días trabajados
                total_days = sum(payslip.worked_days_line_ids.mapped('number_of_days'))
                
                # Preparar fila
                row = {
                    "employee_name": employee_name,
                    "identification": identification,
                    "days": int(total_days),
                    "values": {}
                }
                
                # Inicializar valores para cada columna
                for col in columns:
                    if "code" in col:
                        row["values"][col["code"]] = 0
                
                # Obtener valores para cada columna
                for line in payslip.line_ids:
                    category_code = line.category_id.code if line.category_id else ''
                    rule_code = line.salary_rule_id.code if line.salary_rule_id else ''
                    
                    # Acumular valores por categoría para el resumen
                    if line.total != 0:
                        if category_code not in totals_by_category:
                            totals_by_category[category_code] = 0
                        totals_by_category[category_code] += line.total
                    
                    # Valores para columnas específicas
                    if rule_code == 'TOTALDEV':
                        row["values"]["TOTALDEV"] = line.total
                    elif rule_code == 'TOTALDED':
                        row["values"]["TOTALDED"] = line.total
                    elif rule_code == 'NET':
                        row["values"]["NET"] = line.total
                    
                    # Categorías específicas
                    if category_code in ordered_earnings_codes + ordered_deductions_codes and line.total != 0:
                        row["values"][category_code] = line.total
                
                employee_rows.append(row)
            
            # Dibujar filas
            for i, row in enumerate(employee_rows):
                # Verificar si necesitamos nueva página
                if y_position < 115:
                    canvas.showPage()
                    draw_header(canvas, page_width, page_height)
                    y_position = page_height - 115
                    
                    # Volver a dibujar el encabezado de la tabla
                    y_position = draw_table_header(canvas, y_position, table_columns, table_x_positions)
                
                # Solo dibujar líneas horizontales para separar las filas
                canvas.setStrokeColor(colors.lightgrey)
                canvas.line(10, y_position, x_positions[-1], y_position)
                
                # Datos básicos
                canvas.setFillColor(colors.black)
                canvas.setFont('Helvetica', 4)  # Fuente más pequeña
                
                # Nombre - truncar si es muy largo
                name_to_display = row["employee_name"]
                if len(name_to_display) > 30:
                    name_to_display = name_to_display[:28] + ".."
                canvas.drawString(12, y_position - 10, name_to_display)
                
                # ID
                id_to_display = row["identification"]
                if len(id_to_display) > 18:
                    id_to_display = id_to_display[:16] + ".."
                canvas.drawString(x_positions[1] + 2, y_position - 10, id_to_display)
                
                # Días
                canvas.drawString(x_positions[2] + 7, y_position - 10, str(row["days"]))
                
                # Valores para cada columna - todos en negro
                for i, col in enumerate(columns[3:], 3):
                    if "code" not in col:
                        continue
                        
                    col_code = col["code"]
                    if col_code in row["values"] and row["values"][col_code] != 0:
                        value = row["values"][col_code]
                        
                        # Todos los valores en negro
                        canvas.setFillColor(colors.black)
                        
                        # Dar formato según el tipo de valor
                        if col_code == "TOTALDED":  # Total Deducciones (signo negativo)
                            formatted_value = '${:,.0f}'.format(-value) if value > 0 else '${:,.0f}'.format(value)
                        else:
                            formatted_value = '${:,.0f}'.format(value)
                        
                        # Dibujar valor alineado a la derecha
                        x = x_positions[i]
                        width = col["width"]
                        text_width = canvas.stringWidth(formatted_value, 'Helvetica', 4)
                        
                        if col_code != "FIRMA":
                            canvas.drawString(x + width - text_width - 2, y_position - 10, formatted_value)
                
                # Actualizar posición Y
                y_position -= row_height
            
            # Línea después de los datos
            canvas.setStrokeColor(colors.black)
            canvas.line(10, y_position, x_positions[-1], y_position)
            
            # Fila de totales
            y_position -= 5
            # Sin fondo coloreado - solo línea más gruesa
            canvas.setStrokeColor(colors.black)
            canvas.setLineWidth(1.5)
            canvas.line(10, y_position, x_positions[-1], y_position)
            canvas.setLineWidth(1.0)
            
            # Texto "TOTALES"
            canvas.setFillColor(colors.black)
            canvas.setFont('Helvetica-Bold', 5)  # Más pequeña
            canvas.drawString(12, y_position - 10, "TOTALES")
            
            # Total de días
            total_days = sum(row["days"] for row in employee_rows)
            canvas.drawString(x_positions[2] + 7, y_position - 10, str(total_days))
            
            # Valores totales por columna - todos en negro
            for i, col in enumerate(columns[3:], 3):
                if "code" not in col:
                    continue
                    
                col_code = col["code"]
                
                # Sumar todos los valores para esta columna
                total_value = sum(row["values"].get(col_code, 0) for row in employee_rows)
                
                if total_value != 0:
                    # Todo en negro
                    canvas.setFillColor(colors.black)
                    
                    # Dar formato según el tipo de valor
                    if col_code == "TOTALDED":  # Total Deducciones
                        formatted_value = '${:,.0f}'.format(-total_value) if total_value > 0 else '${:,.0f}'.format(total_value)
                    else:
                        formatted_value = '${:,.0f}'.format(total_value)
                    
                    # Dibujar valor alineado a la derecha
                    x = x_positions[i]
                    width = col["width"]
                    text_width = canvas.stringWidth(formatted_value, 'Helvetica-Bold', 5)
                    
                    if col_code != "FIRMA":
                        canvas.drawString(x + width - text_width - 2, y_position - 10, formatted_value)
                        
                    # Guardar valores para el resumen
                    if col_code not in ["TOTALDEV", "TOTALDED", "NET", "FIRMA"]:
                        totals_by_column[col_code] = total_value
            
            return y_position - row_height - 20, totals_by_category, totals_by_column
        
        # Función para dibujar el resumen por categoría
        def draw_category_summary(canvas, page_width, page_height, y_position, totals_by_category, totals_by_column):
            # Título
            canvas.setFont('Helvetica-Bold', 11)
            canvas.setFillColor(color_titulo)
            canvas.drawString(30, y_position, "RESUMEN POR CATEGORÍA")
            
            # Línea horizontal
            canvas.setStrokeColor(colors.black)
            canvas.line(30, y_position - 5, page_width - 30, y_position - 5)
            y_position -= 25
            
            # Encabezado de la tabla de resumen
            header_height = 20
            table_width = page_width - 60
            
            canvas.setFillColor(color_titulo)
            canvas.rect(30, y_position - header_height, table_width, header_height, fill=True, stroke=False)
            
            # Textos de encabezado
            canvas.setFillColor(colors.white)
            canvas.setFont('Helvetica-Bold', 8)
            canvas.drawString(35, y_position - 14, "Categoría")
            canvas.drawString(350, y_position - 14, "Valor Total")
            canvas.drawString(500, y_position - 14, "% del Total")
            
            y_position -= header_height
            
            # Agrupar por tipo de categoría
            categories = {
                "Devengos": [],
                "Deducciones": [],
                "Especiales": []
            }
            
            # Código a nombre legible y grupo
            code_to_info = {
                'BASIC': {'name': 'Básico', 'group': 'Devengos'},
                'AUX': {'name': 'Auxilio', 'group': 'Devengos'},
                'AUS': {'name': 'Ausencia', 'group': 'Devengos'},
                'ALW': {'name': 'Asignación', 'group': 'Devengos'},
                'ACCIDENTE_TRABAJO': {'name': 'Accidente Trabajo', 'group': 'Devengos'},
                'DEV_NO_SALARIAL': {'name': 'Devengo No Salarial', 'group': 'Devengos'},
                'DEV_SALARIAL': {'name': 'Devengo Salarial', 'group': 'Devengos'},
                'HEYREC': {'name': 'Horas Extra y Recargo', 'group': 'Devengos'},
                'COMISIONES': {'name': 'Comisiones', 'group': 'Devengos'},
                'INCAPACIDAD': {'name': 'Incapacidad', 'group': 'Devengos'},
                'LICENCIA_MATERNIDAD': {'name': 'Licencia Maternidad', 'group': 'Devengos'},
                'LICENCIA_NO_REMUNERADA': {'name': 'Licencia No Remunerada', 'group': 'Devengos'},
                'LICENCIA_REMUNERADA': {'name': 'Licencia Remunerada', 'group': 'Devengos'},
                'PRESTACIONES_SOCIALES': {'name': 'Prestaciones Sociales', 'group': 'Devengos'},
                'PRIMA': {'name': 'Prima', 'group': 'Devengos'},
                'VACACIONES': {'name': 'Vacaciones', 'group': 'Devengos'},
                'DED': {'name': 'Deducción', 'group': 'Deducciones'},
                'DEDUCCIONES': {'name': 'Deducciones', 'group': 'Deducciones'},
                'SANCIONES': {'name': 'Sanciones', 'group': 'Deducciones'},
                'DESCUENTO_AFC': {'name': 'Descuento AFC', 'group': 'Deducciones'},
                'SSOCIAL': {'name': 'Seguridad Social', 'group': 'Deducciones'}
            }
            
            # Categorizar los totales
            total_general = 0
            
            # Usar totals_by_column para que coincida mejor con las columnas mostradas
            for code, value in totals_by_column.items():
                if code in code_to_info:
                    info = code_to_info[code]
                    group = info['group']
                    name = info['name']
                    
                    categories[group].append({"name": name, "code": code, "value": value})
                    total_general += abs(value)
            
            # Dibujar cada grupo de categorías
            row_height = 20
            row_colors = [colors.white, colors.lightgrey]
            
            # Procesar cada grupo
            row_index = 0
            for group_name, items in categories.items():
                if not items:
                    continue
                    
                # Título del grupo
                canvas.setFillColor(colors.black)
                canvas.setFont('Helvetica-Bold', 9)
                canvas.drawString(35, y_position - 14, group_name)
                y_position -= row_height
                
                # Ordenar por valor absoluto descendente
                items.sort(key=lambda x: abs(x["value"]), reverse=True)
                
                # Dibujar cada ítem
                for item in items:
                    # Verificar si necesitamos nueva página
                    if y_position < 115:
                        canvas.showPage()
                        draw_header(canvas, page_width, page_height)
                        y_position = page_height - 115
                        
                        # Re-dibujar el encabezado de la categoría
                        canvas.setFillColor(color_titulo)
                        canvas.rect(30, y_position - header_height, table_width, header_height, fill=True, stroke=False)
                        
                        # Textos de encabezado
                        canvas.setFillColor(colors.white)
                        canvas.setFont('Helvetica-Bold', 8)
                        canvas.drawString(35, y_position - 14, "Categoría")
                        canvas.drawString(350, y_position - 14, "Valor Total")
                        canvas.drawString(500, y_position - 14, "% del Total")
                        
                        y_position -= header_height
                    
                    # Alternar colores
                    canvas.setFillColor(row_colors[row_index % 2])
                    canvas.rect(30, y_position - row_height, table_width, row_height, fill=True, stroke=False)
                    
                    # Nombre
                    canvas.setFillColor(colors.black)
                    canvas.setFont('Helvetica', 8)
                    canvas.drawString(50, y_position - 14, item["name"])
                    
                    # Valor
                    value = item["value"]
                    if value < 0:
                        formatted_value = '$-{:,.0f}'.format(abs(value))
                    else:
                        formatted_value = '${:,.0f}'.format(value)
                    
                    canvas.drawString(350, y_position - 14, formatted_value)
                    
                    # Porcentaje
                    percentage = (abs(value) / total_general * 100) if total_general > 0 else 0
                    formatted_pct = '{:.2f}%'.format(percentage)
                    
                    # Usar color rojo para valores negativos
                    if value < 0:
                        formatted_pct = '-' + formatted_pct
                    
                    canvas.drawString(500, y_position - 14, formatted_pct)
                    
                    y_position -= row_height
                    row_index += 1
            
            return y_position - 20
        
        # Draw the PDF - ahora pasando explícitamente los parámetros necesarios
        draw_header(canvas, page_width, page_height)
        y_position = page_height - 115
        
        # Resumen en la parte superior
        y_position = draw_top_summary(canvas, page_width, y_position)
        
        # Tabla principal - con menos margen superior
        y_position += 30  # Subir más la tabla (reducir el espacio)
        y_position, totals_by_category, totals_by_column = draw_main_table(canvas, page_width, page_height, y_position)
        
        # Resumen por categoría
        y_position = draw_category_summary(canvas, page_width, page_height, y_position, totals_by_category, totals_by_column)
        
        # Nota al pie
        if y_position < 150:  # Mayor margen para asegurar espacio para firmas
            canvas.showPage()
            draw_header(canvas, page_width, page_height)
            y_position = page_height - 115
        
        canvas.setFont('Helvetica-Bold', 8)
        canvas.setFillColor(colors.black)
        canvas.drawString(30, y_position, "NOTA:")
        
        canvas.setFont('Helvetica', 8)
        note_text = f"El costo total para la empresa es de ${summary_metrics['total_devengos']:,.0f} incluyendo todos los conceptos."
        note_text2 = f"Los empleados reciben un neto de ${summary_metrics['neto_pagar']:,.0f} después de deducciones por valor de $-{summary_metrics['total_deducciones']:,.0f}."
        
        canvas.drawString(70, y_position, note_text)
        canvas.drawString(70, y_position - 15, note_text2)
        
        y_position -= 40
        
        # Firmas - asegurar suficiente espacio
        if y_position < 115:
            canvas.showPage()
            draw_header(canvas, page_width, page_height)
            y_position = page_height - 115
        
        signature_y = y_position - 20
        
        # Línea horizontal
        canvas.setStrokeColor(colors.black)
        canvas.line(30, signature_y + 10, page_width - 30, signature_y + 10)
        
        # Textos de firma
        canvas.setFont('Helvetica-Bold', 9)
        canvas.setFillColor(colors.black)
        canvas.drawString(100, signature_y, "ELABORÓ")
        canvas.drawString(page_width / 2, signature_y, "REVISÓ")
        canvas.drawString(page_width - 100, signature_y, "APROBÓ")
        
        # Líneas de firma - más espacio
        canvas.line(50, signature_y - 40, 150, signature_y - 40)
        canvas.line(page_width / 2 - 50, signature_y - 40, page_width / 2 + 50, signature_y - 40)
        canvas.line(page_width - 150, signature_y - 40, page_width - 50, signature_y - 40)
        
        # Nombres de firmantes si están disponibles
        obj_signature = self.get_hr_payslip_template_signature()
        if obj_signature:
            canvas.setFont('Helvetica', 8)
            if obj_signature.txt_signature_prepared:
                canvas.drawString(75, signature_y - 55, obj_signature.txt_signature_prepared)
            if obj_signature.txt_signature_reviewed:
                canvas.drawString(page_width / 2 - 25, signature_y - 55, obj_signature.txt_signature_reviewed)
            if obj_signature.txt_signature_approved:
                canvas.drawString(page_width - 125, signature_y - 55, obj_signature.txt_signature_approved)
        
        # Guardar PDF
        canvas.save()
        
        # Guardar archivo PDF
        pdf_data = base64.b64encode(buffer.getvalue())
        filename = 'Informe_Liquidacion.pdf'
        
        # Actualizar el registro con datos PDF
        self.write({
            'excel_file': pdf_data,
            'excel_file_name': filename,
        })
        
        action = {
            'name': filename,
            'type': 'ir.actions.act_url',
            'url': "web/content/?model=hr.payroll.report.lavish.filter&id=" + str(self.id) + "&filename_field=excel_file_name&field=excel_file&download=true&filename=" + self.excel_file_name,
            'target': 'self',
        }
        return action
    def _count_employees_on_leave(self, payslips):
        count = 0
        employees_counted = set()
        
        for slip in payslips:
            employee_id = slip.employee_id.id
            if employee_id in employees_counted:
                continue
                
            # Look for specific leave work entry types related to sick leave/disability
            sick_days = slip.worked_days_line_ids.filtered(
                lambda w: w.work_entry_type_id.code in ['INCAPACIDAD', 'SICK', 'DISABILITY']
            )
            if sick_days:
                count += 1
                employees_counted.add(employee_id)
        
        return count

    def _get_absences_by_type(self, min_date, max_date, employees):
        """Group absences by type and count them."""
        if not min_date or not max_date:
            return {}
        
        employee_ids = employees.mapped('id')
        
        leaves = self.env['hr.leave'].search([
            ('employee_id', 'in', employee_ids),
            ('state', '=', 'validate'),
            '|',
            '&', ('request_date_from', '>=', min_date), ('request_date_from', '<=', max_date),
            '&', ('request_date_to', '>=', min_date), ('request_date_to', '<=', max_date)
        ])
        
        absence_types = {}
        for leave in leaves:
            leave_type = leave.holiday_status_id.name
            if leave_type not in absence_types:
                absence_types[leave_type] = 0
            absence_types[leave_type] += 1
        
        return absence_types

    def _add_comparison_summary(self, elements, styles, payslips, summary_metrics):
        """Adds a visual comparison summary section similar to the reference image."""
        # Get total days scheduled vs worked
        total_days_scheduled = 0
        total_days_worked = 0
        for payslip in payslips:
            # Assume WORK100 is the code for regular work days
            work_days = payslip.worked_days_line_ids.filtered(lambda w: w.work_entry_type_id.code == 'WORK100')
            if work_days:
                total_days_worked += sum(work_days.mapped('number_of_days'))
            
            # All scheduled days
            total_days_scheduled += sum(payslip.worked_days_line_ids.mapped('number_of_days'))
        
        # Calculate work percentage
        work_percentage = (total_days_worked / total_days_scheduled * 100) if total_days_scheduled > 0 else 0
        
        # Create a visual summary with bar-like representation
        summary_style = ParagraphStyle(
            'Summary',
            parent=styles['Normal'],
            fontSize=10,
            alignment=TA_LEFT
        )
        
        # Title for the section
        elements.append(Paragraph("<b>COMPARATIVO DE COSTOS LABORALES</b>", summary_style))
        elements.append(Spacer(1, 0.1*inch))
        
        # Data for comparison table
        data = [
            # Category, Current Value, Bar/Color Indicator, Value with style
            ["Total Devengos", "", "", f"<b>${summary_metrics['total_devengos']:,.0f}</b>"],
            ["Total Deducciones", "", "", f"<b>${summary_metrics['total_deducciones']:,.0f}</b>"],
            ["Neto a Pagar", "", "", f"<b>${summary_metrics['neto_pagar']:,.0f}</b>"],
            ["Días Trabajados", "", "", f"<b>WORK100: {total_days_worked:,.0f}</b>"],
            ["Días Ausencias", "", "", f"<b>{total_days_scheduled - total_days_worked:,.0f}</b>"],
            ["Porcentaje Trabajado", "", "", f"<b>{work_percentage:.2f}%</b>"],
        ]
        
        # Column widths (adjust as needed)
        colWidths = [2.5*inch, 0.2*inch, 2*inch, 1.5*inch]
        
        # Create table
        table = Table(data, colWidths=colWidths)
        
        # Style the table
        table.setStyle(TableStyle([
            # Borders
            ('LINEBELOW', (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ('LEFTPADDING', (0, 0), (0, -1), 0),
            ('RIGHTPADDING', (-1, 0), (-1, -1), 0),
            
            # Text alignment
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (-1, 0), (-1, -1), 'RIGHT'),
            
            # Bar colors for different rows (column 2)
            ('BACKGROUND', (2, 0), (2, 0), colors.lightgreen),  # Devengos
            ('BACKGROUND', (2, 1), (2, 1), colors.salmon),      # Deducciones
            ('BACKGROUND', (2, 2), (2, 2), colors.lightblue),   # Neto
            ('BACKGROUND', (2, 3), (2, 3), colors.lightgreen),  # Días trabajados
            ('BACKGROUND', (2, 4), (2, 4), colors.salmon),      # Días ausencia
            ('BACKGROUND', (2, 5), (2, 5), colors.lightblue),   # Porcentaje
            
            # Special formatting for values column
            ('TEXTCOLOR', (3, 0), (3, 0), colors.darkgreen),    # Devengos
            ('TEXTCOLOR', (3, 1), (3, 1), colors.darkred),      # Deducciones
            ('TEXTCOLOR', (3, 2), (3, 2), colors.darkblue),     # Neto
            ('TEXTCOLOR', (3, 3), (3, 3), colors.darkgreen),    # Días trabajados
            ('TEXTCOLOR', (3, 4), (3, 4), colors.darkred),      # Días ausencia 
            ('TEXTCOLOR', (3, 5), (3, 5), colors.darkblue),     # Porcentaje
        ]))
        
        elements.append(table)
        elements.append(Spacer(1, 0.3*inch))
        
        # Divider before main table
        elements.append(HRFlowable(width="100%", thickness=1, color=colors.black))
        elements.append(Spacer(1, 0.2*inch))
        
        return elements



###EXCEL



    def _prepare_report_data(self, payslips, min_date, max_date):
        """Prepara los datos para el informe utilizando el ORM."""
        if not payslips:
            raise ValidationError(_('No se encontraron nóminas con los filtros seleccionados.'))
        
        # Filtrar solo empleados con las reglas/categorías seleccionadas si corresponde
        if self.salary_rule_ids or self.rule_category_ids:
            filtered_payslips = self.env['hr.payslip']
            
            for payslip in payslips:
                include_payslip = False
                
                # Verificar si el empleado tiene las reglas seleccionadas
                for line in payslip.line_ids:
                    if (self.salary_rule_ids and line.salary_rule_id.id in self.salary_rule_ids.ids) or \
                    (self.rule_category_ids and line.category_id.id in self.rule_category_ids.ids):
                        include_payslip = True
                        break
                
                if include_payslip:
                    filtered_payslips |= payslip
            
            payslips = filtered_payslips
        
        if not payslips:
            raise ValidationError(_('No se encontraron nóminas con las reglas o categorías seleccionadas.'))
        
        # Obtener las novedades
        employees = payslips.mapped('employee_id')
        novedades_por_empleado = self._get_novedades(min_date, max_date, employees)
        
        # Preparar datos para el dataframe
        report_data = []
        item_counter = 1
        
        # Configurar agrupación por mes si está seleccionada
        if self.group_by == 'month':
            for payslip in payslips:
                # Determinar el mes de la nómina basado en la fecha de inicio
                mes = payslip.date_from.month
                anio = payslip.date_from.year
                nombre_mes = calendar.month_name[mes]
        
        # Counter for employees in the report
        employee_count = 0
        
        # Procesamiento de días trabajados y líneas de nómina
        for payslip in payslips:
            employee = payslip.employee_id
            contract = payslip.contract_id
            
            # Increment employee counter
            employee_count += 1
            
            if self.group_by == 'month':
                mes = payslip.date_from.month
                anio = payslip.date_from.year
                nombre_mes = calendar.month_name[mes]
                grupo_mes = f"{nombre_mes} {anio}"
            
            # Determine wage type based on contract flags
            wage_type = contract.modality_salary
        
            
            # Determine if it's a new hire or retirement
            is_new_hire = False
            is_retired = False
            
            # Check if employee was hired in this period
            if contract.date_start and min_date and max_date:
                is_new_hire = (contract.date_start.month == min_date.month and 
                            contract.date_start.year == min_date.year)
            
            # Check if employee was retired in this period
            if contract.date_end and min_date and max_date:
                is_retired = (contract.date_end >= min_date and contract.date_end <= max_date)
            
            # Datos base del empleado que se utilizarán en todos los registros
            employee_base_data = {
                'Item': item_counter,
                'Contador': employee_count,
                'Identificación': employee.identification_id or '' + ' ' + employee.work_contact_id.l10n_latam_identification_type_id.dian_code or '',
                'Empleado': employee.name or '',
                'Tipo Contrato': contract.contract_type if hasattr(contract, 'contract_type') and contract.contract_type else '',
                'Fecha Ingreso': contract.date_start.strftime('%d/%m/%Y') or datetime(1900, 1, 1).date(),
                'Fecha Retiro': contract.date_end.strftime('%d/%m/%Y') if contract.date_end else  None,
                'Estructura Salarial': contract.structure_type_id.name if hasattr(contract, 'structure_type_id') and contract.structure_type_id else '',
                'Seccional': employee.branch_id.name if employee.branch_id else '',
                'Cuenta Analítica': contract.analytic_account_id.name if contract.analytic_account_id else '',
                'Cargo': employee.job_id.name if employee.job_id else '',
                'Banco': employee.work_contact_id and employee.work_contact_id.bank_ids and employee.work_contact_id.bank_ids.filtered(lambda b: b.is_main) and employee.work_contact_id.bank_ids.filtered(lambda b: b.is_main)[0].bank_id.name or '',
                'Cuenta Bancaria': employee.work_contact_id and employee.work_contact_id.bank_ids and employee.work_contact_id.bank_ids.filtered(lambda b: b.is_main) and employee.work_contact_id.bank_ids.filtered(lambda b: b.is_main)[0].acc_number or '',
                'Cuenta Dispersora': employee.work_contact_id and employee.work_contact_id.bank_ids and employee.work_contact_id.bank_ids.filtered(lambda b: b.is_main and b.payroll_dispersion_account) and employee.work_contact_id.bank_ids.filtered(lambda b: b.is_main)[0].payroll_dispersion_account.name or '',
                'Código SENA': contract.code_sena or '',
                'Ubicación Laboral': employee.address_id.name if employee.address_id else '',
                'Departamento': employee.department_id.name if employee.department_id else '',
                'Nivel de Riesgo ARL': contract.risk_id.name if contract.risk_id else '',
                'Salario Base': contract.wage or 0,
                'Tipo Salario': wage_type,
                'Es Nuevo Ingreso': is_new_hire,
                'Es Retiro': is_retired,
                'Novedades': novedades_por_empleado.get(employee.identification_id, ''),
                'Fecha Inicio': payslip.date_from.strftime('%d/%m/%Y'),
                'Fecha Fin': payslip.date_to.strftime('%d/%m/%Y')
            }
            
            # Definir etiqueta de grupo para agrupación
            if self.group_by == 'department':
                employee_base_data['Grupo'] = employee.department_id.name if employee.department_id else 'Sin Departamento'
            elif self.group_by == 'job':
                employee_base_data['Grupo'] = employee.job_id.name if employee.job_id else 'Sin Cargo'
            elif self.group_by == 'analytic_account':
                employee_base_data['Grupo'] = contract.analytic_account_id.name if contract.analytic_account_id else 'Sin Cuenta Analítica'
            elif self.group_by == 'risk_level':
                employee_base_data['Grupo'] = contract.risk_id.name if contract.risk_id else 'Sin Nivel de Riesgo'
            elif self.group_by == 'branch':
                employee_base_data['Grupo'] = employee.branch_id.name if employee.branch_id else 'Sin Seccional'
            elif self.group_by == 'job_placement':
                employee_base_data['Grupo'] = employee.address_id.name if employee.address_id else 'Sin Ubicación Laboral'
            elif self.group_by == 'month':
                employee_base_data['Grupo'] = grupo_mes
            else:
                employee_base_data['Grupo'] = 'Todos'
            
            # Añadir información de seguridad social si está activada
            if self.show_social_security:
                ss_data = self._get_social_security_data(
                    employee.id, 
                    payslip.date_from, 
                    payslip.date_to
                )
                employee_base_data.update({
                    'SS_Salud_Empresa': ss_data['health_company'],
                    'SS_Salud_Empleado': ss_data['health_employee'],
                    'SS_Salud_Total': ss_data['health_total'],
                    'SS_Salud_Diferencia': ss_data['health_diff'],
                    'SS_Pensión_Empresa': ss_data['pension_company'],
                    'SS_Pensión_Empleado': ss_data['pension_employee'],
                    'SS_Pensión_Total': ss_data['pension_total'],
                    'SS_Pensión_Diferencia': ss_data['pension_diff'],
                    'SS_Nivel_Riesgo': ss_data['risk_level'],
                    'SS_ARL': ss_data['arl'],
                    'SS_CCF': ss_data['ccf'],
                    'SS_SENA': ss_data['sena'],
                    'SS_ICBF': ss_data['icbf']
                })
            
            # Obtener códigos de trabajo en orden de prioridad
            work_entry_order = ['WORK_D', 'WORK100']
            
            # 1. Primero procesar WORK_D y WORK100 en ese orden
            for code in work_entry_order:
                for worked_day in payslip.worked_days_line_ids.filtered(lambda w: w.work_entry_type_id.code == code):
                    # Solo incluir días trabajados si no hay filtro de reglas o si coincide con el filtro
                    if self.salary_rule_ids:
                        # Verificar si el tipo de entrada corresponde a alguna regla seleccionada
                        matching_rule = False
                        for rule in self.salary_rule_ids:
                            if worked_day.work_entry_type_id.code == rule.code:
                                matching_rule = True
                                break
                        
                        if not matching_rule:
                            continue
                    
                    day_data = employee_base_data.copy()
                    day_data.update({
                        'Regla Salarial': worked_day.work_entry_type_id.short_name or worked_day.work_entry_type_id.name or '',
                        'Reglas Salariales + Entidad': worked_day.work_entry_type_id.short_name or worked_day.work_entry_type_id.name or '',
                        'Categoría': 'Días',
                        'Secuencia': 0,
                        'Monto': worked_day.number_of_days or 0
                    })
                    report_data.append(day_data)
            
            # 2. Luego procesar las ausencias (todas las entradas que no son WORK_D o WORK100)
            for worked_day in payslip.worked_days_line_ids.filtered(
                lambda w: w.work_entry_type_id.code not in work_entry_order
            ):
                # Solo incluir días trabajados si no hay filtro de reglas o si coincide con el filtro
                if self.salary_rule_ids:
                    # Verificar si el tipo de entrada corresponde a alguna regla seleccionada
                    matching_rule = False
                    for rule in self.salary_rule_ids:
                        if worked_day.work_entry_type_id.code == rule.code:
                            matching_rule = True
                            break
                    
                    if not matching_rule:
                        continue
                
                day_data = employee_base_data.copy()
                day_data.update({
                    'Regla Salarial': worked_day.work_entry_type_id.short_name or worked_day.work_entry_type_id.name or '',
                    'Reglas Salariales + Entidad': worked_day.work_entry_type_id.short_name or worked_day.work_entry_type_id.name or '',
                    'Categoría': 'Días',
                    'Secuencia': 0,
                    'Monto': worked_day.number_of_days or 0
                })
                report_data.append(day_data)
            
            # Obtener listas de categorías permitidas
            earnings_codes_list = self.earnings_codes.split(',') if self.earnings_codes else []
            deductions_codes_list = self.deductions_codes.split(',') if self.deductions_codes else []
            
            # Procesar líneas de nómina
            has_matching_rule = False
            for line in payslip.line_ids:
                # Verificar si aplican los filtros de reglas y categorías
                if self.salary_rule_ids and self.rule_category_ids:
                    if line.salary_rule_id.id not in self.salary_rule_ids.ids and line.category_id.id not in self.rule_category_ids.ids:
                        continue
                elif self.salary_rule_ids:
                    if line.salary_rule_id.id not in self.salary_rule_ids.ids:
                        continue
                elif self.rule_category_ids:
                    if line.category_id.id not in self.rule_category_ids.ids:
                        continue
                
                # Verificar si se debe mostrar provisiones
                if line.category_id.code == 'PROVISION' and not self.show_provisions:
                    continue
                
                # Verificar que la categoría esté en las listas permitidas
                if line.category_id.code not in earnings_codes_list + deductions_codes_list + ['TOTALDEV', 'TOTALDED', 'NET', 'PROVISION']:
                    if line.salary_rule_id.code not in ['TOTALDEV', 'TOTALDED', 'NET']:
                        continue
                
                has_matching_rule = True
                
                # Datos base para esta línea
                entity_name = ''
                if line.entity_id and line.category_id.code != 'SSOCIAL':
                    entity_name = line.entity_id.partner_id.business_name or line.entity_id.partner_id.name or ''
                
                line_data = employee_base_data.copy()
                rule_name = line.salary_rule_id.short_name or line.salary_rule_id.name or ''
                
                # Agregar datos de la línea
                line_data.update({
                    'Regla Salarial': rule_name,
                    'Reglas Salariales + Entidad': f"{rule_name} {entity_name}".strip() if not self.not_show_rule_entity else rule_name,
                    'Categoría': line.category_id.name or '',
                    'Código Categoría': line.category_id.code or '',
                    'Secuencia': line.sequence or 0,
                    'Monto': line.total or 0
                })
                report_data.append(line_data)
                
                # Si no es mostrar cantidades, continuar
                if self.not_show_quantity:
                    continue
                
                # Agregar cantidad para horas extras y prestaciones sociales
                if line.category_id.code in ['HEYREC', 'PRESTACIONES_SOCIALES'] and line.quantity:
                    quantity_data = employee_base_data.copy()
                    quantity_data.update({
                        'Regla Salarial': rule_name,
                        'Reglas Salariales + Entidad': f"Cantidad de {rule_name}" if not self.not_show_rule_entity else f"Cantidad de {rule_name}",
                        'Categoría': line.category_id.name or '',
                        'Código Categoría': line.category_id.code or '',
                        'Secuencia': line.sequence or 0,
                        'Monto': line.quantity or 0
                    })
                    report_data.append(quantity_data)
                
                # Agregar base para prestaciones sociales
                if line.category_id.code == 'PRESTACIONES_SOCIALES' and line.amount_base:
                    base_data = employee_base_data.copy()
                    base_data.update({
                        'Regla Salarial': rule_name,
                        'Reglas Salariales + Entidad': f"Base de {rule_name}" if not self.not_show_rule_entity else f"Base de {rule_name}",
                        'Categoría': line.category_id.name or '',
                        'Código Categoría': line.category_id.code or '',
                        'Secuencia': line.sequence or 0,
                        'Monto': line.amount_base or 0
                    })
                    report_data.append(base_data)
                
                # Agregar días de ausencias no remuneradas
                if line.days_unpaid_absences:
                    absence_data = employee_base_data.copy()
                    absence_data.update({
                        'Regla Salarial': rule_name,
                        'Reglas Salariales + Entidad': f"Días Ausencias no remuneradas de {rule_name}" if not self.not_show_rule_entity else f"Días Ausencias no remuneradas de {rule_name}",
                        'Categoría': line.category_id.name or '',
                        'Código Categoría': line.category_id.code or '',
                        'Secuencia': line.sequence or 0,
                        'Monto': line.days_unpaid_absences or 0
                    })
                    report_data.append(absence_data)
            
            # Solo incrementar el contador si el empleado tiene reglas coincidentes
            if has_matching_rule or not (self.salary_rule_ids or self.rule_category_ids):
                item_counter += 1
        
        # Agregar subtotales y totales
        self._add_grouped_totals_to_report_data(report_data)
        
        # Convertir a DataFrame
        df_report = pd.DataFrame(report_data)
        
        return df_report


    def generate_excel(self):
        """Genera el informe en Excel aplicando todos los filtros y agrupaciones."""
        # Obtener liquidaciones aplicando todos los filtros
        obj_payslips, min_date, max_date = self._get_payslips()
        
        if not obj_payslips:
            raise ValidationError(_('No se encontraron nóminas con los filtros seleccionados.'))
            
        # Preparar datos del informe
        df_report = self._prepare_report_data(obj_payslips, min_date, max_date)
        
        if len(df_report) == 0:
            raise ValidationError(_('No se ha encontrado información con los filtros seleccionados, por favor verificar.'))
        
        # Obtener datos para métricas y gráficos
        company_data = self._get_company_data()
        summary_metrics = self._get_summary_metrics(df_report, obj_payslips)
        category_totals = self._get_category_totals(obj_payslips)
        department_totals = self._get_department_totals(obj_payslips)
        analytic_totals = self._get_analytic_account_totals(obj_payslips)
        rule_totals = self._get_rule_totals(obj_payslips)
        entity_totals = self._get_entity_totals(obj_payslips)
        
        # Crear Excel
        filename = 'Informe Liquidación.xlsx'
        stream = io.BytesIO()
        writer = pd.ExcelWriter(stream, engine='xlsxwriter')
        workbook = writer.book
        
        # Crear formatos usados en todo el informe
        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#1F497D',
            'font_color': 'white',
            'align': 'center',
            'valign': 'vcenter',
            'border': 1
        })
        
        group_title_format = workbook.add_format({
            'bold': True,
            'bg_color': '#4F81BD',
            'font_color': 'white',
            'align': 'left',
            'valign': 'vcenter',
            'border': 1,
            'font_size': 12
        })
        
        cell_format = workbook.add_format({
            'border': 1,
            'align': 'left',
            'valign': 'vcenter'
        })
        
        number_format = workbook.add_format({
            'border': 1,
            'align': 'right',
            'num_format': '#,##0.00'
        })
        
        subtotal_format = workbook.add_format({
            'bold': True, 
            'bg_color': '#E0E0E0',
            'border': 1,
            'num_format': '#,##0.00',
            'align': 'right'
        })
        
        total_format = workbook.add_format({
            'bold': True, 
            'bg_color': '#C0C0C0',
            'border': 1,
            'num_format': '#,##0.00',
            'align': 'right'
        })
        
        title_format = workbook.add_format({
            'bold': True, 
            'font_size': 14, 
            'align': 'left',
            'valign': 'vcenter',
            'font_color': '#1F497D'
        })
        
        # Crear hoja principal
        worksheet = workbook.add_worksheet('Liquidación')
        
        # Agregar encabezado con datos de la empresa
        next_row = self._add_company_header(worksheet, workbook, company_data)
        
        # Agregar cuadro de resumen
        next_row = self._add_summary_dashboard(worksheet, workbook, summary_metrics, next_row)
        
        # Añadir título del informe
        worksheet.merge_range(next_row, 0, next_row, 8, 'INFORME DE LIQUIDACIÓN', title_format)
        next_row += 1
        
        text_dates = 'Fechas Liquidación: %s a %s' % (min_date.strftime('%d/%m/%Y') if min_date else '', 
                                                    max_date.strftime('%d/%m/%Y') if max_date else '')
        worksheet.merge_range(next_row, 0, next_row, 8, text_dates, title_format)
        
        # Mostrar cantidad de nóminas procesadas
        if self.payslip_ids:
            text_payslips = f"Lotes de nómina: {len(self.payslip_ids)} - Total nóminas: {len(obj_payslips)}"
            worksheet.merge_range(next_row+1, 0, next_row+1, 8, text_payslips, title_format)
            next_row += 2
        elif self.liquidations_ids:
            text_payslips = f"Liquidaciones individuales: {len(self.liquidations_ids)}"
            worksheet.merge_range(next_row+1, 0, next_row+1, 8, text_payslips, title_format)
            next_row += 2
        else:
            # Caso para búsqueda por filtros de fecha
            text_payslips = f"Total nóminas: {len(obj_payslips)}"
            worksheet.merge_range(next_row+1, 0, next_row+1, 8, text_payslips, title_format)
            next_row += 2
        
        next_row += 1  # Agregar espacio
        
        # Determinar columnas de índice según las opciones seleccionadas
        columns_index = ['Contador', 'Identificación', 'Empleado', 'Tipo Contrato', 'Estructura Salarial', 'Tipo Salario', 'Número Comprobante']
        
        # Agregar columnas especiales para indicar nuevo ingreso y retiro
        columns_index.extend(['Es Nuevo Ingreso', 'Es Retiro'])
        
        # Configurar columnas según la agrupación seleccionada
        group_by_field = 'Departamento'  # Valor por defecto
        if self.group_by == 'department':
            group_by_field = 'Departamento'
        elif self.group_by == 'job':
            group_by_field = 'Cargo'
            columns_index.append('Cargo')
        elif self.group_by == 'analytic_account':
            group_by_field = 'Cuenta Analítica'
            columns_index.append('Cuenta Analítica')
        elif self.group_by == 'risk_level':
            group_by_field = 'Nivel de Riesgo ARL'
            columns_index.append('Nivel de Riesgo ARL')
        elif self.group_by == 'branch':
            group_by_field = 'Seccional'
            columns_index.append('Seccional')
        elif self.group_by == 'job_placement':
            group_by_field = 'Ubicación Laboral'
            columns_index.append('Ubicación Laboral')
        elif self.group_by == 'month':
            group_by_field = 'Grupo'  # En este caso, Grupo contiene el mes
        else:
            # Si no hay agrupación, usamos un valor único para agrupar todo junto
            group_by_field = 'Grupo'
        
        # Agregar columnas según las opciones de visualización seleccionadas
        if self.show_date_of_entry:
            columns_index.append('Fecha Ingreso')
            columns_index.append('Fecha Retiro')
        if self.show_job_placement and self.group_by != 'job_placement':
            columns_index.append('Ubicación Laboral')
        if self.show_sectional and self.group_by != 'branch':
            columns_index.append('Seccional')
        if self.show_department and self.group_by != 'department':
            columns_index.append('Departamento')
        if self.show_analytical_account and self.group_by != 'analytic_account':
            columns_index.append('Cuenta Analítica')
        if self.show_job and self.group_by != 'job':
            columns_index.append('Cargo')
        if self.show_sena_code:
            columns_index.append('Código SENA')
        if self.show_basic_salary:
            columns_index.append('Salario Base')
        if self.show_dispersing_account:
            columns_index.append('Cuenta Dispersora')
        if self.show_bank_officer:
            columns_index.append('Banco')
        if self.show_bank_account_officer:
            columns_index.append('Cuenta Bancaria')
        if self.show_risk_level and self.group_by != 'risk_level':
            columns_index.append('Nivel de Riesgo ARL')
        
        # Añadir las fechas de inicio y fin para liquidaciones individuales
        if self.show_individual_payslips or len(self.liquidations_ids) > 0:
            columns_index.extend(['Fecha Inicio', 'Fecha Fin'])
        
        # Escribir encabezados de columnas
        for col, header in enumerate(columns_index):
            worksheet.write(next_row, col, header, header_format)
        
        # Si se muestran datos de seguridad social, añadir esas columnas
        if self.show_social_security:
            ss_headers = []
            
            # Nivel de riesgo (solo porcentaje)
            ss_headers.append('% Nivel Riesgo')
            
            # Salud
            ss_headers.extend(['Salud Empresa', 'Salud Empleado', 'Total Salud', 'Diferencia Salud'])
            
            # Pensión
            ss_headers.extend(['Pensión Empresa', 'Pensión Empleado', 'Total Pensión', 'Diferencia Pensión'])
            
            # Parafiscales
            ss_headers.extend(['ARL', 'CCF', 'SENA', 'ICBF'])
            
            # Escribir encabezados de seguridad social
            for i, header in enumerate(ss_headers):
                worksheet.write(next_row, len(columns_index) + len(rule_names) + i, header, header_format)
        
        # Verificar si hay reglas/categorías seleccionadas
        has_rule_filters = bool(self.salary_rule_ids or self.rule_category_ids)
        
        # Obtener listas de categorías permitidas
        earnings_codes_list = self.earnings_codes.split(',') if self.earnings_codes else []
        deductions_codes_list = self.deductions_codes.split(',') if self.deductions_codes else []
        
        # Identificar reglas salariales únicas en los datos
        # Obtener reglas en el orden específico solicitado
        rule_names = []
        
        # Sección para encabezados con títulos de secciones
        rule_sections = {
            'DIAS': {'title': 'DÍAS TRABAJADOS', 'rules': []},
            'DEVENGOS': {'title': 'DEVENGOS', 'rules': []},
            'DEDUCCIONES': {'title': 'DEDUCCIONES', 'rules': []},
            'TOTALES': {'title': 'TOTALES', 'rules': []},
            'PROVISIONES': {'title': 'PROVISIONES', 'rules': []}
        }
        
        # 0. Primero añadir las entradas de días trabajados
        # Orden: WORK_D, WORK100, luego otras entradas de días
        work_entry_priority = ['WORK_D', 'WORK100']
        
        # Añadir primero los días de trabajo prioritarios en el orden especificado
        for entry_code in work_entry_priority:
            # Buscar reglas salariales que corresponden a estos códigos de trabajo
            work_rules = df_report[df_report['Categoría'] == 'Días']['Regla Salarial'].unique()
            for rule in work_rules:
                # Verificar si la regla corresponde al código actual (comparación aproximada)
                if entry_code in rule and rule not in rule_names:
                    rule_names.append(rule)
                    rule_sections['DIAS']['rules'].append(rule)
        
        # Añadir otras entradas de días (ausencias, etc.)
        other_day_rules = df_report[df_report['Categoría'] == 'Días']['Regla Salarial'].unique()
        for rule in other_day_rules:
            if rule not in rule_names:
                rule_names.append(rule)
                rule_sections['DIAS']['rules'].append(rule)
        
        # 1. Después añadir devengos en el orden especificado
        if 'Código Categoría' in df_report.columns:
            for code in earnings_codes_list:
                # Filtrar reglas de esta categoría específica
                category_rules = df_report[df_report['Código Categoría'] == code]['Regla Salarial'].unique()
                
                # Agregar reglas de esta categoría al listado ordenado
                for rule in category_rules:
                    if rule not in rule_names:
                        rule_names.append(rule)
                        rule_sections['DEVENGOS']['rules'].append(rule)
            
            # 2. Añadir TOTALDEV después de devengos
            if 'TOTALDEV' in df_report['Regla Salarial'].unique():
                rule_names.append('TOTALDEV')
                rule_sections['TOTALES']['rules'].append('TOTALDEV')
            
            # 3. Deducciones en el orden especificado
            for code in deductions_codes_list:
                # Filtrar reglas de esta categoría específica
                category_rules = df_report[df_report['Código Categoría'] == code]['Regla Salarial'].unique()
                
                # Agregar reglas de esta categoría al listado ordenado
                for rule in category_rules:
                    if rule not in rule_names:
                        rule_names.append(rule)
                        rule_sections['DEDUCCIONES']['rules'].append(rule)
            
            # 4. Añadir TOTALDED después de deducciones
            if 'TOTALDED' in df_report['Regla Salarial'].unique():
                rule_names.append('TOTALDED')
                rule_sections['TOTALES']['rules'].append('TOTALDED')
            
            # 5. Añadir NET al final
            if 'NET' in df_report['Regla Salarial'].unique():
                rule_names.append('NET')
                rule_sections['TOTALES']['rules'].append('NET')
            
            # 6. Añadir provisiones si están activas
            if self.show_provisions:
                provision_rules = df_report[df_report['Código Categoría'] == 'PROVISION']['Regla Salarial'].unique()
                for rule in provision_rules:
                    if rule not in rule_names:
                        rule_names.append(rule)
                        rule_sections['PROVISIONES']['rules'].append(rule)
        else:
            # Si no hay columna de código de categoría, ordenar manualmente
            # Primero los días trabajados (ya añadidos), luego otras reglas
            other_rules = [rule for rule in sorted(df_report['Regla Salarial'].unique()) 
                        if rule not in rule_names]
            rule_names.extend(other_rules)
            
            # Intentar categorizar las reglas restantes
            for rule in other_rules:
                if 'TOTAL' in rule or rule in ['TOTALDEV', 'TOTALDED', 'NET']:
                    rule_sections['TOTALES']['rules'].append(rule)
                elif 'PROVISION' in rule:
                    rule_sections['PROVISIONES']['rules'].append(rule)
                else:
                    # Dividir entre devengos y deducciones basado en el valor
                    is_deduction = False
                    for _, row in df_report[df_report['Regla Salarial'] == rule].iterrows():
                        if row['Monto'] < 0:
                            is_deduction = True
                            break
                    
                    if is_deduction:
                        rule_sections['DEDUCCIONES']['rules'].append(rule)
                    else:
                        rule_sections['DEVENGOS']['rules'].append(rule)
        
        # Escribir encabezados de reglas salariales con secciones
        current_col = len(columns_index)
        
        # Formato para los títulos de secciones
        section_format = workbook.add_format({
            'bold': True,
            'bg_color': '#C0C0C0',  # Gris claro para diferenciar de encabezados normales
            'font_color': 'black',
            'align': 'center',
            'valign': 'vcenter',
            'border': 1
        })
        
        # Escribir encabezados por secciones
        for section_key, section_data in rule_sections.items():
            # Solo mostrar secciones que tengan reglas
            if not section_data['rules']:
                continue
                
            # Escribir título de la sección
            section_width = len(section_data['rules'])
            if section_width > 0:
                worksheet.merge_range(next_row-1, current_col, next_row-1, current_col + section_width - 1, 
                                    section_data['title'], section_format)
                
                # Escribir encabezados de columnas individuales
                for rule_name in section_data['rules']:
                    worksheet.write(next_row, current_col, rule_name, header_format)
                    current_col += 1
        
        next_row += 1
        
        # Filtrar solo las filas de empleados (no subtotales/totales)
        df_employees = df_report[df_report['Item'] < 400000].copy()
        
        # Agrupar por el campo seleccionado
        if group_by_field in df_employees.columns:
            groups = df_employees[group_by_field].unique()
        else:
            # Si el campo no existe, usar un grupo único
            groups = ['Todos']
            df_employees['Grupo'] = 'Todos'
            group_by_field = 'Grupo'
        
        # Inicializar arrays para totales generales
        grand_totals = {rule: 0 for rule in rule_names}
        grand_totals_dias = {rule: 0 for rule in rule_names 
                            if 'Días' in df_report[df_report['Regla Salarial'] == rule]['Categoría'].values}
        grand_totals_ss = {
            'SS_Nivel_Riesgo': 0,
            'SS_Salud_Empresa': 0,
            'SS_Salud_Empleado': 0,
            'SS_Salud_Total': 0,
            'SS_Salud_Diferencia': 0,
            'SS_Pensión_Empresa': 0, 
            'SS_Pensión_Empleado': 0,
            'SS_Pensión_Total': 0,
            'SS_Pensión_Diferencia': 0,
            'SS_ARL': 0,
            'SS_CCF': 0,
            'SS_SENA': 0,
            'SS_ICBF': 0
        }
        
        # Procesar cada grupo
        for group in sorted(groups):
            if pd.isna(group):
                group_name = 'Sin Clasificar'
            else:
                group_name = group
            
            # Filtrar empleados del grupo actual
            group_employees = df_employees[df_employees[group_by_field] == group]
            
            # Escribir título del grupo
            header_width = len(columns_index) + len(rule_names)
            if self.show_social_security:
                header_width += len(ss_headers)
                
            worksheet.merge_range(
                next_row, 0, next_row, header_width - 1,
                f"{group_name.upper()} - {len(group_employees['Identificación'].unique())} EMPLEADOS",
                group_title_format
            )
            next_row += 1
            
            # Añadir contador para subtotales de días trabajados
            subtotal_dias = {}
            # Inicializar contadores para cada tipo de día
            for rule in rule_names:
                if 'Días' in df_report[df_report['Regla Salarial'] == rule]['Categoría'].values:
                    subtotal_dias[rule] = 0
            
            # Inicializar subtotales del grupo
            group_subtotals = {rule: 0 for rule in rule_names}
            group_subtotals_ss = {
                'SS_Nivel_Riesgo': 0,
                'SS_Salud_Empresa': 0,
                'SS_Salud_Empleado': 0,
                'SS_Salud_Total': 0,
                'SS_Salud_Diferencia': 0,
                'SS_Pensión_Empresa': 0, 
                'SS_Pensión_Empleado': 0,
                'SS_Pensión_Total': 0,
                'SS_Pensión_Diferencia': 0,
                'SS_ARL': 0,
                'SS_CCF': 0,
                'SS_SENA': 0,
                'SS_ICBF': 0
            }
            
            # Procesar cada empleado del grupo
            for _, emp_id in enumerate(group_employees['Identificación'].unique()):
                employee_data = group_employees[group_employees['Identificación'] == emp_id].iloc[0]
                
                # Escribir datos del empleado
                for col, field in enumerate(columns_index):
                    value = employee_data.get(field, '')
                    
                    # Ajustar el formato para campos específicos
                    if field in ['Es Nuevo Ingreso', 'Es Retiro']:
                        # Convertir valores booleanos a X o vacío
                        value = 'X' if value else ''
                    elif field == 'Tipo Salario':
                        # Asegurar que se muestre el valor como está
                        value = value
                    elif field == 'Fecha Retiro' and pd.isna(value):
                        value = ''
                    
                    # Escribir el valor con el formato apropiado
                    if field in ['Salario Base'] and not pd.isna(value):
                        worksheet.write(next_row, col, value, number_format)
                    else:
                        worksheet.write(next_row, col, value, cell_format)
                
                # Escribir valores de seguridad social si corresponde
                if self.show_social_security:
                    # Usar los datos de SS del empleado
                    ss_values = [
                        employee_data.get('SS_Nivel_Riesgo', 0),
                        employee_data.get('SS_Salud_Empresa', 0),
                        employee_data.get('SS_Salud_Empleado', 0),
                        employee_data.get('SS_Salud_Total', 0),
                        employee_data.get('SS_Salud_Diferencia', 0),
                        employee_data.get('SS_Pensión_Empresa', 0),
                        employee_data.get('SS_Pensión_Empleado', 0),
                        employee_data.get('SS_Pensión_Total', 0),
                        employee_data.get('SS_Pensión_Diferencia', 0),
                        employee_data.get('SS_ARL', 0),
                        employee_data.get('SS_CCF', 0),
                        employee_data.get('SS_SENA', 0),
                        employee_data.get('SS_ICBF', 0)
                    ]
                    
                    # Escribir valores de SS
                    for i, value in enumerate(ss_values):
                        worksheet.write(next_row, len(columns_index) + len(rule_names) + i, value, number_format)
                    
                    # Acumular para subtotales
                    group_subtotals_ss['SS_Nivel_Riesgo'] += employee_data.get('SS_Nivel_Riesgo', 0)
                    group_subtotals_ss['SS_Salud_Empresa'] += employee_data.get('SS_Salud_Empresa', 0)
                    group_subtotals_ss['SS_Salud_Empleado'] += employee_data.get('SS_Salud_Empleado', 0)
                    group_subtotals_ss['SS_Salud_Total'] += employee_data.get('SS_Salud_Total', 0)
                    group_subtotals_ss['SS_Salud_Diferencia'] += employee_data.get('SS_Salud_Diferencia', 0)
                    group_subtotals_ss['SS_Pensión_Empresa'] += employee_data.get('SS_Pensión_Empresa', 0)
                    group_subtotals_ss['SS_Pensión_Empleado'] += employee_data.get('SS_Pensión_Empleado', 0)
                    group_subtotals_ss['SS_Pensión_Total'] += employee_data.get('SS_Pensión_Total', 0)
                    group_subtotals_ss['SS_Pensión_Diferencia'] += employee_data.get('SS_Pensión_Diferencia', 0)
                    group_subtotals_ss['SS_ARL'] += employee_data.get('SS_ARL', 0)
                    group_subtotals_ss['SS_CCF'] += employee_data.get('SS_CCF', 0)
                    group_subtotals_ss['SS_SENA'] += employee_data.get('SS_SENA', 0)
                    group_subtotals_ss['SS_ICBF'] += employee_data.get('SS_ICBF', 0)
                
                # Escribir valores de las reglas salariales
                for col, rule_name in enumerate(rule_names):
                    # Buscar el valor de esta regla para este empleado
                    rule_value = 0
                    
                    # Determinar si esta regla representa días trabajados o ausencias
                    is_day_rule = False
                    for _, row in df_report[(df_report['Identificación'] == emp_id) & 
                                        (df_report['Regla Salarial'] == rule_name)].iterrows():
                        rule_value += row['Monto']
                        if row['Categoría'] == 'Días':
                            is_day_rule = True
                    
                    # Si no hay valor específico y es SUELDO, usar el salario base
                    if rule_value == 0 and rule_name == 'SUELDO' and 'Salario Base' in employee_data:
                        rule_value = employee_data['Salario Base']
                    
                    # Para deducciones, convertir a valores positivos para la visualización
                    is_deduction = False
                    if rule_name in rule_sections['DEDUCCIONES']['rules'] and rule_value < 0:
                        is_deduction = True
                        rule_value = abs(rule_value)  # Valor absoluto para mostrar
                    
                    # Escribir valor con formato adecuado según si es días o valor monetario
                    if is_day_rule:
                        # Para días, usar formato con decimales pero sin símbolo de moneda
                        day_format = workbook.add_format({
                            'border': 1,
                            'align': 'right',
                            'num_format': '0.00'
                        })
                        worksheet.write(next_row, col + len(columns_index), rule_value, day_format)
                        
                        # Acumular para subtotales de días trabajados
                        if rule_name in subtotal_dias:
                            subtotal_dias[rule_name] += rule_value
                    else:
                        # Para valores monetarios, usar formato con moneda
                        if is_deduction:
                            # Formato para deducciones (positivo pero con color diferente)
                            deduction_format = workbook.add_format({
                                'border': 1,
                                'align': 'right',
                                'num_format': '#,##0.00',
                                'font_color': 'red'  # Color rojo para deducciones
                            })
                            worksheet.write(next_row, col + len(columns_index), rule_value, deduction_format)
                        else:
                            # Formato normal para valores monetarios
                            worksheet.write(next_row, col + len(columns_index), rule_value, number_format)
                    
                    # Acumular para subtotales generales
                    group_subtotals[rule_name] += rule_value
                
                next_row += 1
            
            # Escribir subtotal del grupo
            worksheet.merge_range(
                next_row, 0, next_row, len(columns_index) - 1,
                f"SUBTOTAL {group_name.upper()}",
                subtotal_format
            )
            
            # Escribir valores de subtotales
            for col, rule_name in enumerate(rule_names):
                # Determinar si es un subtotal de días o de valor monetario
                if rule_name in subtotal_dias:
                    # Formato para subtotales de días
                    day_subtotal_format = workbook.add_format({
                        'bold': True, 
                        'bg_color': '#E0E0E0',
                        'border': 1,
                        'num_format': '0.00',
                        'align': 'right'
                    })
                    worksheet.write(next_row, col + len(columns_index), subtotal_dias[rule_name], day_subtotal_format)
                else:
                    # Formato normal para subtotales monetarios
                    worksheet.write(next_row, col + len(columns_index), group_subtotals[rule_name], subtotal_format)
                
                # Acumular para total general
                grand_totals[rule_name] += group_subtotals[rule_name]
            
            # Escribir subtotales de seguridad social
            if self.show_social_security:
                ss_subtotals = [
                    group_subtotals_ss['SS_Nivel_Riesgo'] / len(group_employees['Identificación'].unique()) if len(group_employees['Identificación'].unique()) > 0 else 0,  # Promedio para nivel de riesgo
                    group_subtotals_ss['SS_Salud_Empresa'],
                    group_subtotals_ss['SS_Salud_Empleado'],
                    group_subtotals_ss['SS_Salud_Total'],
                    group_subtotals_ss['SS_Salud_Diferencia'],
                    group_subtotals_ss['SS_Pensión_Empresa'],
                    group_subtotals_ss['SS_Pensión_Empleado'],
                    group_subtotals_ss['SS_Pensión_Total'],
                    group_subtotals_ss['SS_Pensión_Diferencia'],
                    group_subtotals_ss['SS_ARL'],
                    group_subtotals_ss['SS_CCF'],
                    group_subtotals_ss['SS_SENA'],
                    group_subtotals_ss['SS_ICBF']
                ]
                
                # Escribir subtotales de SS
                for i, value in enumerate(ss_subtotals):
                    worksheet.write(next_row, len(columns_index) + len(rule_names) + i, value, subtotal_format)
                
                # Acumular para totales generales
                for key in grand_totals_ss:
                    if key == 'SS_Nivel_Riesgo':
                        continue  # Este se calculará como promedio al final
                    grand_totals_ss[key] += group_subtotals_ss[key]
            
            next_row += 2  # Espacio entre grupos
        
        # Escribir total general
        worksheet.merge_range(
            next_row, 0, next_row, len(columns_index) - 1,
            "TOTAL GENERAL",
            total_format
        )
        
        # Escribir valores de totales generales
        for col, rule_name in enumerate(rule_names):
            # Determinar si es un total de días o de valor monetario
            if rule_name in grand_totals_dias:
                # Formato para totales de días
                day_total_format = workbook.add_format({
                    'bold': True, 
                    'bg_color': '#C0C0C0',
                    'border': 1,
                    'num_format': '0.00',
                    'align': 'right'
                })
                worksheet.write(next_row, col + len(columns_index), grand_totals[rule_name], day_total_format)
            else:
                # Formato normal para totales monetarios
                worksheet.write(next_row, col + len(columns_index), grand_totals[rule_name], total_format)
        
        # Escribir totales generales de seguridad social
        if self.show_social_security:
            # Calcular promedio de nivel de riesgo
            promedio_riesgo = 0
            total_empleados = df_employees['Identificación'].nunique()
            if total_empleados > 0:
                # Calcular promedio de nivel de riesgo
                empleados_con_riesgo = df_employees[df_employees['SS_Nivel_Riesgo'] > 0]['Identificación'].nunique()
                if empleados_con_riesgo > 0:
                    promedio_riesgo = df_employees['SS_Nivel_Riesgo'].sum() / empleados_con_riesgo
            
            ss_totals = [
                promedio_riesgo,
                grand_totals_ss['SS_Salud_Empresa'],
                grand_totals_ss['SS_Salud_Empleado'],
                grand_totals_ss['SS_Salud_Total'],
                grand_totals_ss['SS_Salud_Diferencia'],
                grand_totals_ss['SS_Pensión_Empresa'],
                grand_totals_ss['SS_Pensión_Empleado'],
                grand_totals_ss['SS_Pensión_Total'],
                grand_totals_ss['SS_Pensión_Diferencia'],
                grand_totals_ss['SS_ARL'],
                grand_totals_ss['SS_CCF'],
                grand_totals_ss['SS_SENA'],
                grand_totals_ss['SS_ICBF']
            ]
            
            # Escribir totales de SS
            for i, value in enumerate(ss_totals):
                worksheet.write(next_row, len(columns_index) + len(rule_names) + i, value, total_format)
        
        next_row += 2  # Espacio antes de firmas
        
        # Ajustar anchos de columna
        for i, field in enumerate(columns_index):
            max_len = max(len(str(field)), 15)  # Mínimo 15 caracteres
            worksheet.set_column(i, i, max_len + 2)
        
        # Ajustar anchos para columnas de reglas
        for i, rule_name in enumerate(rule_names):
            col_idx = i + len(columns_index)
            max_len = max(len(str(rule_name)), 12)  # Mínimo 12 caracteres
            worksheet.set_column(col_idx, col_idx, max_len + 2)
        
        # Ajustar anchos para columnas de seguridad social
        if self.show_social_security:
            for i, header in enumerate(ss_headers):
                col_idx = i + len(columns_index) + len(rule_names)
                max_len = max(len(str(header)), 12)  # Mínimo 12 caracteres
                worksheet.set_column(col_idx, col_idx, max_len + 2)
        
        worksheet.set_zoom(80)
        
        # Agregar hoja de gráficos y análisis
        self._add_summary_charts(workbook, category_totals, department_totals, analytic_totals, rule_totals, entity_totals, obj_payslips)
        
        # Firmas
        obj_signature = self.get_hr_payslip_template_signature()
        cell_format_firma = workbook.add_format({'bold': True, 'align': 'center', 'top': 1})
        cell_format_txt_firma = workbook.add_format({'bold': True, 'align': 'center'})
        
        if obj_signature:
            if obj_signature.signature_prepared:
                worksheet.merge_range(next_row, 1, next_row, 2, 'ELABORO', cell_format_firma)
                if obj_signature.txt_signature_prepared:
                    worksheet.merge_range(next_row + 1, 1, next_row + 1, 2, obj_signature.txt_signature_prepared, cell_format_txt_firma)
            if obj_signature.signature_reviewed:
                worksheet.merge_range(next_row, 4, next_row, 5, 'REVISO', cell_format_firma)
                if obj_signature.txt_signature_reviewed:
                    worksheet.merge_range(next_row + 1, 4, next_row + 1, 5, obj_signature.txt_signature_reviewed, cell_format_txt_firma)
            if obj_signature.signature_approved:
                worksheet.merge_range(next_row, 7, next_row, 8, 'APROBO', cell_format_firma)
                if obj_signature.txt_signature_approved:
                    worksheet.merge_range(next_row + 1, 7, next_row + 1, 8, obj_signature.txt_signature_approved, cell_format_txt_firma)
        else:
            worksheet.merge_range(next_row, 1, next_row, 2, 'ELABORO', cell_format_firma)
            worksheet.merge_range(next_row, 4, next_row, 5, 'REVISO', cell_format_firma)
            worksheet.merge_range(next_row, 7, next_row, 8, 'APROBO', cell_format_firma)
        
        # Guardar excel
        writer.close()

        self.write({
            'excel_file': base64.b64encode(stream.getvalue()).decode('utf-8'),
            'excel_file_name': filename,
        })
        
        action = {
            'name': filename,
            'type': 'ir.actions.act_url',
            'url': "web/content/?model=hr.payroll.report.lavish.filter&id=" + str(self.id) + "&filename_field=excel_file_name&field=excel_file&download=true&filename=" + self.excel_file_name,
            'target': 'self',
        }
        return action
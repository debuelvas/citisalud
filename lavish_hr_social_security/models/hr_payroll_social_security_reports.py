# -*- coding: utf-8 -*-

from logging import exception
from odoo import models, fields, api, _, SUPERUSER_ID
from odoo.exceptions import UserError, ValidationError

from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from pytz import timezone

import base64
import io
import xlsxwriter
import math

class hr_payroll_social_security(models.Model):
    _inherit = 'hr.payroll.social.security'
    
    def _get_employees_dict(self):
        """
        Organiza las líneas de seguridad social por empleado.
        Retorna un diccionario donde la clave es el id del empleado y el valor
        contiene la información del empleado y sus líneas agrupadas.
        """
        result = {}
        
        # Obtener todas las líneas de seguridad social
        lines = self.executing_social_security_ids
        
        # Agrupar líneas por empleado
        for line in lines:
            employee_id = line.employee_id.id
            
            if employee_id not in result:
                result[employee_id] = {
                    'employee': line.employee_id,
                    'lines': [],
                    'main_line': None,
                    'novelty_lines': []
                }
            
            result[employee_id]['lines'].append(line)
            
            # Determinar si es línea principal o novedad
            if line.main or (not any([
                line.nDiasIncapacidadEPS, 
                line.nDiasLicencia, 
                line.nDiasMaternidad, 
                line.nDiasVacaciones, 
                line.nDiasLicenciaRenumerada,
                line.vct
            ]) and not result[employee_id]['main_line']):
                result[employee_id]['main_line'] = line
            else:
                result[employee_id]['novelty_lines'].append(line)
        
        # Asegurarse de que cada empleado tenga una línea principal
        for employee_id, data in result.items():
            if not data['main_line'] and data['lines']:
                # Si no se identificó una línea principal, usar la primera línea como principal
                data['main_line'] = data['lines'][0]
                # Y quitar esta línea de las novedades si está allí
                if data['main_line'] in data['novelty_lines']:
                    data['novelty_lines'].remove(data['main_line'])
        
        return result
    
    @api.depends('month')
    def _compute_month_name(self):
        """
        Calcula el nombre del mes basado en el número del mes.
        """
        months = {
            '1': 'Enero', '2': 'Febrero', '3': 'Marzo', '4': 'Abril',
            '5': 'Mayo', '6': 'Junio', '7': 'Julio', '8': 'Agosto',
            '9': 'Septiembre', '10': 'Octubre', '11': 'Noviembre', '12': 'Diciembre'
        }
        for record in self:
            record.month_name = months.get(record.month, '')
    
    month_name = fields.Char(string="Nombre del Mes", compute="_compute_month_name", store=True)
    
    def action_view_html_report(self):
        """
        Acción para mostrar el reporte HTML organizado por empleado
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.report',
            'report_name': 'hr_payroll_social_security.report_social_security_summary',
            'report_type': 'qweb-html',
            'data': {'id': self.id}
        }
    
    def action_print_pdf_report(self):
        """
        Acción para imprimir el reporte en PDF
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.report',
            'report_name': 'hr_payroll_social_security.report_social_security_summary',
            'report_type': 'qweb-pdf',
            'data': {'id': self.id}
        }
    def get_excel(self):
        filename = 'Seguridad Social Periodo {}-{}.xlsx'.format(self.month, str(self.year))
        stream = io.BytesIO()
        book = xlsxwriter.Workbook(stream, {'in_memory': True})
        sheet = book.add_worksheet('Seguridad Social')

        columns = [
            'N° de identificación', 'Empleado', 'Sucursal', 'Contrato', 'Días liquidados', 'Días incapacidad EPS',
            'Días licencia', 'Días licencia remunerada', 'Días maternidad', 'Días vacaciónes', 'Días incapacidad ARP',
            'Ingreso', 'Retiro', 'Sueldo', 'Tercero EPS', 'Valor base salud', 'Porc. Aporte salud empleados',
            'Valor salud empleado', 'Valor salud empleado nómina', 'Porc. Aporte salud empresa',
            'Valor salud empresa', 'Valor salud total', 'Diferencia salud', 'Tercero pensión',
            'Valor base fondo de pensión', 'Porc. Aporte pensión empleado', 'Valor pensión empleado',
            'Valor pensión empleado nómina', 'Porc. Aporte pensión empresa', 'Valor pensión empresa',
            'Valor pensión total', 'Diferencia pensión', 'Tiene AVP', 'Valor AVP','Tercero fondo solidaridad',
            'Porc. Fondo solidaridad', 'Valor fondo solidaridad', 'Valor fondo subsistencia', 'Tercero ARP',
            'Valor base ARP', 'Porc. Aporte ARP', 'Valor ARP', 'Exonerado ley 1607',
            'Tercero caja compensación', 'Valor base caja com', 'Porc. Aporte caja com', 'Valor caja com',
            'Tercero SENA', 'Valor base SENA', 'Porc. Aporte SENA', 'Valor SENA',
            'Tercero ICBF', 'Valor base ICBF', 'Porc. Aporte ICBF', 'Valor ICBF', 'Fecha Inicio SLN', 'Fecha Fin SLN',
            'Fecha Inicio IGE', 'Fecha Fin IGE',
            'Fecha Inicio LMA', 'Fecha Fin LMA', 'Fecha Inicio VACLR', 'Fecha Fin VACLR', 'Fecha Inicio VCT',
            'Fecha Fin VCT', 'Fecha Inicio IRL', 'Fecha Fin IRL'
        ]

        # Agregar textos al excel
        text_title = 'Seguridad Social'
        text_generate = 'Informe generado el %s' % (datetime.now(timezone(self.env.user.tz)))
        cell_format_title = book.add_format({'bold': True, 'align': 'left'})
        cell_format_title.set_font_name('Calibri')
        cell_format_title.set_font_size(15)
        cell_format_title.set_bottom(5)
        cell_format_title.set_bottom_color('#1F497D')
        cell_format_title.set_font_color('#1F497D')
        sheet.merge_range('A1:BO1', text_title, cell_format_title)
        cell_format_text_generate = book.add_format({'bold': False, 'align': 'left'})
        cell_format_text_generate.set_font_name('Calibri')
        cell_format_text_generate.set_font_size(10)
        cell_format_text_generate.set_bottom(5)
        cell_format_text_generate.set_bottom_color('#1F497D')
        cell_format_text_generate.set_font_color('#1F497D')
        sheet.merge_range('A2:BO2', text_generate, cell_format_text_generate)
        # Formato para fechas
        date_format = book.add_format({'num_format': 'dd/mm/yyyy'})

        # Agregar columnas
        aument_columns = 0
        for column in columns:
            sheet.write(2, aument_columns, column)
            sheet.set_column(aument_columns, aument_columns, len(str(column)) + 10)
            aument_columns = aument_columns + 1

        # Agregar valores
        aument_rows = 3
        for item in self.executing_social_security_ids:
            sheet.write(aument_rows, 0, item.employee_id.identification_id)
            sheet.write(aument_rows, 1, item.employee_id.name)
            sheet.write(aument_rows, 2, item.employee_id.branch_social_security_id.name)
            sheet.write(aument_rows, 3, item.contract_id.name)
            sheet.write(aument_rows, 4, item.nDiasLiquidados)
            sheet.write(aument_rows, 5, item.nDiasIncapacidadEPS)
            sheet.write(aument_rows, 6, item.nDiasLicencia)
            sheet.write(aument_rows, 7, item.nDiasLicenciaRenumerada)
            sheet.write(aument_rows, 8, item.nDiasMaternidad)
            sheet.write(aument_rows, 9, item.nDiasVacaciones)
            sheet.write(aument_rows, 10, item.nDiasIncapacidadARP)
            sheet.write(aument_rows, 11, item.nIngreso)
            sheet.write(aument_rows, 12, item.nRetiro)
            sheet.write(aument_rows, 13, item.nSueldo)
            sheet.write(aument_rows, 14, item.TerceroEPS.name if item.TerceroEPS else '')
            sheet.write(aument_rows, 15, item.nValorBaseSalud)
            sheet.write(aument_rows, 16, item.nPorcAporteSaludEmpleado)
            sheet.write(aument_rows, 17, item.nValorSaludEmpleado)
            sheet.write(aument_rows, 18, item.nValorSaludEmpleadoNomina)
            sheet.write(aument_rows, 19, item.nPorcAporteSaludEmpresa)
            sheet.write(aument_rows, 20, item.nValorSaludEmpresa)
            sheet.write(aument_rows, 21, item.nValorSaludTotal)
            sheet.write(aument_rows, 22, item.nDiferenciaSalud)
            sheet.write(aument_rows, 23, item.TerceroPension.name if item.TerceroPension else '')
            sheet.write(aument_rows, 24, item.nValorBaseFondoPension)
            sheet.write(aument_rows, 25, item.nPorcAportePensionEmpleado)
            sheet.write(aument_rows, 26, item.nValorPensionEmpleado)
            sheet.write(aument_rows, 27, item.nValorPensionEmpleadoNomina)
            sheet.write(aument_rows, 28, item.nPorcAportePensionEmpresa)
            sheet.write(aument_rows, 29, item.nValorPensionEmpresa)
            sheet.write(aument_rows, 30, item.nValorPensionTotal)
            sheet.write(aument_rows, 31, item.nDiferenciaPension)
            sheet.write(aument_rows, 32, item.cAVP)
            sheet.write(aument_rows, 33, item.nAporteVoluntarioPension)
            sheet.write(aument_rows, 34, item.TerceroFondoSolidaridad.name if item.TerceroFondoSolidaridad else '')
            sheet.write(aument_rows, 35, item.nPorcFondoSolidaridad)
            sheet.write(aument_rows, 36, item.nValorFondoSolidaridad)
            sheet.write(aument_rows, 37, item.nValorFondoSubsistencia)
            sheet.write(aument_rows, 38, item.TerceroARP.name if item.TerceroARP else '')
            sheet.write(aument_rows, 39, item.nValorBaseARP)
            sheet.write(aument_rows, 40, item.nPorcAporteARP)
            sheet.write(aument_rows, 41, item.nValorARP)
            sheet.write(aument_rows, 42, item.cExonerado1607)
            sheet.write(aument_rows, 43, item.TerceroCajaCom.name if item.TerceroCajaCom else '')
            sheet.write(aument_rows, 44, item.nValorBaseCajaCom)
            sheet.write(aument_rows, 45, item.nPorcAporteCajaCom)
            sheet.write(aument_rows, 46, item.nValorCajaCom)
            sheet.write(aument_rows, 47, item.TerceroSENA.name if item.TerceroSENA else '')
            sheet.write(aument_rows, 48, item.nValorBaseSENA)
            sheet.write(aument_rows, 49, item.nPorcAporteSENA)
            sheet.write(aument_rows, 50, item.nValorSENA)
            sheet.write(aument_rows, 51, item.TerceroICBF.name if item.TerceroICBF else '')
            sheet.write(aument_rows, 52, item.nValorBaseICBF)
            sheet.write(aument_rows, 53, item.nPorcAporteICBF)
            sheet.write(aument_rows, 54, item.nValorICBF)
            sheet.write(aument_rows, 55, item.dFechaInicioSLN, date_format)
            sheet.write(aument_rows, 56, item.dFechaFinSLN, date_format)
            sheet.write(aument_rows, 57, item.dFechaInicioIGE, date_format)
            sheet.write(aument_rows, 58, item.dFechaFinIGE, date_format)
            sheet.write(aument_rows, 59, item.dFechaInicioLMA, date_format)
            sheet.write(aument_rows, 60, item.dFechaFinLMA, date_format)
            sheet.write(aument_rows, 61, item.dFechaInicioVACLR, date_format)
            sheet.write(aument_rows, 62, item.dFechaFinVACLR, date_format)
            sheet.write(aument_rows, 63, item.dFechaInicioVCT, date_format)
            sheet.write(aument_rows, 64, item.dFechaFinVCT, date_format)
            sheet.write(aument_rows, 65, item.dFechaInicioIRL, date_format)
            sheet.write(aument_rows, 66, item.dFechaFinIRL, date_format)
            aument_rows = aument_rows + 1

        # Convertir en tabla
        array_header_table = []
        for i in columns:
            dict = {'header': i}
            array_header_table.append(dict)

        sheet.add_table(2, 0, aument_rows - 1, len(columns) - 1,
                        {'style': 'Table Style Medium 2', 'columns': array_header_table})

        book.close()

        self.write({
            'excel_file': base64.b64encode(stream.getvalue()).decode('utf-8'),
            'excel_file_name': filename,
        })

        action = {
            'name': 'Export Seguridad Social',
            'type': 'ir.actions.act_url',
            'url': "web/content/?model=hr.payroll.social.security&id=" + str(
                self.id) + "&filename_field=excel_file_name&field=excel_file&download=true&filename=" + self.excel_file_name,
            'target': 'self',
        }
        return action

    def get_excel_errors(self):
        filename = 'Seguridad Social Advertencias Periodo {}-{}.xlsx'.format(self.month, str(self.year))
        stream = io.BytesIO()
        book = xlsxwriter.Workbook(stream, {'in_memory': True})
        sheet = book.add_worksheet('Seguridad Social')

        columns = [
            'Empleado', 'Sucursal', 'Advertencia'
        ]

        # Agregar columnas
        aument_columns = 0
        for columns in columns:
            sheet.write(0, aument_columns, columns)
            aument_columns = aument_columns + 1

        # Agregar valores
        aument_rows = 1
        for item in self.errors_social_security_ids:
            sheet.write(aument_rows, 0, item.employee_id.name)
            sheet.write(aument_rows, 1, item.branch_id.name)
            sheet.write(aument_rows, 2, item.description)
            aument_rows = aument_rows + 1
        book.close()

        self.write({
            'excel_file': base64.b64encode(stream.getvalue()).decode('utf-8'),
            'excel_file_name': filename,
        })

        action = {
            'name': 'Export Seguridad Social',
            'type': 'ir.actions.act_url',
            'url': "web/content/?model=hr.payroll.social.security&id=" + str(
                self.id) + "&filename_field=excel_file_name&field=excel_file&download=true&filename=" + self.excel_file_name,
            'target': 'self',
        }
        return action

    #METODOS REPORTE SEGURIDAD SOCIAL POR TIPO Y ENTIDAD
    def info_totals(self):
        dict_totals = {}
        for record in self:
            # Cálculos existentes
            total_amount_employees = sum([i.nValorSaludEmpleadoNomina+i.nValorPensionEmpleadoNomina+i.nDiferenciaSalud+i.nDiferenciaPension for i in record.executing_social_security_ids])
            total_amount_company = sum([i.nValorSaludEmpresa+i.nValorPensionEmpresa+i.nValorARP+i.nValorCajaCom+i.nValorSENA+i.nValorICBF for i in record.executing_social_security_ids])
            
            # Cálculos para métricas de empleados
            total_estudiantes = len([i for i in record.executing_social_security_ids if i.employee_id.tipo_coti_id.code == '19'])
            total_pensionados = len([i for i in record.executing_social_security_ids if i.employee_id.subtipo_coti_id.code  != '00'])
            total_empleados_normales = len(record.executing_social_security_ids.employee_id) - total_estudiantes - total_pensionados
            
            total_tipo_12 = len([i for i in record.executing_social_security_ids if i.employee_id.tipo_coti_id.code  == '12'])
            total_tipo_19 = total_estudiantes
            total_subtipo_00 = len([i for i in record.executing_social_security_ids if i.employee_id.subtipo_coti_id.code  == '00'])
            total_subtipo_01 = len([i for i in record.executing_social_security_ids if i.employee_id.subtipo_coti_id.code  == '01'])
            
            dict_totals = {
                'total_employees': len(record.executing_social_security_ids.employee_id),
                'total_amount_employees': float("{:.2f}".format(total_amount_employees)),
                'total_amount_company': float("{:.2f}".format(total_amount_company)),
                'total_amount_final': float("{:.2f}".format(total_amount_employees+total_amount_company)),
                
                # Nuevas métricas de empleados
                'total_estudiantes': total_estudiantes,
                'total_pensionados': total_pensionados,
                'total_empleados_normales': total_empleados_normales,
                'total_tipo_12': total_tipo_12,
                'total_tipo_19': total_tipo_19,
                'total_subtipo_00': total_subtipo_00,
                'total_subtipo_01': total_subtipo_01
            }
        return dict_totals

    def get_info_eps(self):
        lst_eps = []
        for record in self:
            obj_type_eps = self.env['hr.contribution.register'].search([('type_entities','=','eps')],limit=1)
            obj_entities = self.env['hr.employee.entities'].search([('types_entities','in',obj_type_eps.ids)])

            for entity in sorted(obj_entities,key=lambda x: x.id):
                info = record.executing_social_security_ids.filtered(lambda x: x.TerceroEPS.id == entity.id and x.nValorSaludEmpleadoNomina+x.nValorSaludEmpresa+x.nDiferenciaSalud != 0)
                nValorSaludEmpleadoTotal,nValorSaludEmpresaTotal,nDiferenciaSaludTotal = 0,0,0
                for i in info:
                    nValorSaludEmpleadoTotal += i.nValorSaludEmpleadoNomina
                    nValorSaludEmpresaTotal += i.nValorSaludEmpresa
                    nDiferenciaSaludTotal += i.nDiferenciaSalud

                if nValorSaludEmpleadoTotal + nValorSaludEmpresaTotal + nDiferenciaSaludTotal != 0:
                    dict_eps = {'name': entity.partner_id.name,
                                'identifcation': entity.partner_id.vat_co,
                                'cod_pila': entity.code_pila_eps,
                                'num_employees': len(info.employee_id),
                                'value_employees': float("{:.2f}".format(nValorSaludEmpleadoTotal)),
                                'value_company': float("{:.2f}".format(nValorSaludEmpresaTotal)),
                                'dif_round': float("{:.2f}".format(nDiferenciaSaludTotal)),
                                }
                    lst_eps.append(dict_eps)

        return lst_eps

    def get_info_pension(self):
        lst_eps = []
        for record in self:
            obj_type_eps = self.env['hr.contribution.register'].search([('type_entities','=','pension')],limit=1)
            obj_entities = self.env['hr.employee.entities'].search([('types_entities','in',obj_type_eps.ids)])

            for entity in sorted(obj_entities,key=lambda x: x.id):
                info = record.executing_social_security_ids.filtered(lambda x: x.TerceroPension.id == entity.id and x.nValorPensionEmpleadoNomina+x.nValorPensionEmpresa+x.nDiferenciaPension != 0)
                nValorPensionEmpleadoTotal,nValorPensionEmpresaTotal,nDiferenciaPensionTotal = 0,0,0
                for i in info:
                    nValorPensionEmpleadoTotal += i.nValorPensionEmpleadoNomina
                    nValorPensionEmpresaTotal += i.nValorPensionEmpresa
                    nDiferenciaPensionTotal += i.nDiferenciaPension

                if nValorPensionEmpleadoTotal + nValorPensionEmpresaTotal + nDiferenciaPensionTotal != 0:
                    dict_eps = {'name': entity.partner_id.name,
                                'identifcation': entity.partner_id.vat,
                                'cod_pila': entity.code_pila_eps,
                                'num_employees': len(info.employee_id),
                                'value_employees': float("{:.2f}".format(nValorPensionEmpleadoTotal)),
                                'value_company': float("{:.2f}".format(nValorPensionEmpresaTotal)),
                                'dif_round': float("{:.2f}".format(nDiferenciaPensionTotal)),
                                }
                    lst_eps.append(dict_eps)

        return lst_eps

    def get_info_solidaridad(self):
        lst_eps = []
        for record in self:
            obj_type_eps = self.env['hr.contribution.register'].search([('type_entities','in',['pension', 'solidaridad', 'subsistencia'])],limit=1)
            obj_entities = self.env['hr.employee.entities'].search([('types_entities','in',obj_type_eps.ids)])

            for entity in sorted(obj_entities,key=lambda x: x.id):
                info = record.executing_social_security_ids.filtered(lambda x: x.TerceroFondoSolidaridad.id == entity.id and x.nValorFondoSolidaridad+x.nValorFondoSubsistencia != 0)
                nValorFondoSolidaridad,nValorFondoSubsistencia = 0,0
                for i in info:
                    nValorFondoSolidaridad += i.nValorFondoSolidaridad
                    nValorFondoSubsistencia += i.nValorFondoSubsistencia

                if nValorFondoSolidaridad + nValorFondoSubsistencia != 0:
                    dict_eps = {'name': entity.partner_id.name,
                                'identifcation': entity.partner_id.vat,
                                'cod_pila': entity.code_pila_eps,
                                'num_employees': len(info.employee_id),
                                'value_solidaridad': float("{:.2f}".format(nValorFondoSolidaridad+nValorFondoSubsistencia))                                
                                }
                    lst_eps.append(dict_eps)

        return lst_eps

    def get_info_arp(self):
        lst_eps = []
        for record in self:
            obj_type_eps = self.env['hr.contribution.register'].search([('type_entities','=','riesgo')],limit=1)
            obj_entities = self.env['hr.employee.entities'].search([('types_entities','in',obj_type_eps.ids)])

            for entity in sorted(obj_entities,key=lambda x: x.id):
                info = record.executing_social_security_ids.filtered(lambda x: x.TerceroARP.id == entity.id and x.nValorARP != 0)
                nValorARP = 0
                for i in info:
                    nValorARP += i.nValorARP

                if nValorARP != 0:
                    dict_eps = {'name': entity.partner_id.name,
                                'identifcation': entity.partner_id.vat,
                                'cod_pila': entity.code_pila_eps,
                                'num_employees': len(info.employee_id),
                                'value_arp': float("{:.2f}".format(nValorARP)),
                                }
                    lst_eps.append(dict_eps)

        return lst_eps

    def get_info_compensacion(self): 
        lst_eps = []
        for record in self:
            obj_type_eps = self.env['hr.contribution.register'].search([('type_entities','=','caja')],limit=1)
            obj_entities = self.env['hr.employee.entities'].search([('types_entities','in',obj_type_eps.ids)])

            for entity in sorted(obj_entities,key=lambda x: x.id):
                info = record.executing_social_security_ids.filtered(lambda x: x.TerceroCajaCom.id == entity.id and x.nValorCajaCom != 0)
                nValorCajaCom = 0
                for i in info:
                    nValorCajaCom += i.nValorCajaCom

                if nValorCajaCom != 0:
                    dict_eps = {'name': entity.partner_id.name,
                                'identifcation': entity.partner_id.vat,
                                'cod_pila': entity.code_pila_ccf,
                                'num_employees': len(info.employee_id),
                                'value_cajacom': float("{:.2f}".format(nValorCajaCom)),
                                }
                    lst_eps.append(dict_eps)

        return lst_eps

    def get_info_sena(self): 
        lst_eps = []
        for record in self:
            obj_type_eps = self.env['hr.contribution.register'].search([('type_entities','=','sena')],limit=1)
            obj_entities = self.env['hr.employee.entities'].search([('types_entities','in',obj_type_eps.ids)])

            for entity in sorted(obj_entities,key=lambda x: x.id):
                info = record.executing_social_security_ids.filtered(lambda x: x.TerceroSENA.id == entity.id and x.nValorSENA != 0)
                nValorSENA = 0
                for i in info:
                    nValorSENA += i.nValorSENA

                if nValorSENA != 0:
                    dict_eps = {'name': entity.partner_id.name,
                                'identifcation': entity.partner_id.vat,
                                'cod_pila': entity.code_pila_eps,
                                'num_employees': len(info.employee_id),
                                'value_sena': float("{:.2f}".format(nValorSENA)),
                                }
                    lst_eps.append(dict_eps)

        return lst_eps

    def get_info_icbf(self): 
        lst_eps = []
        for record in self:
            obj_type_eps = self.env['hr.contribution.register'].search([('type_entities','=','icbf')],limit=1)
            obj_entities = self.env['hr.employee.entities'].search([('types_entities','in',obj_type_eps.ids)])

            for entity in sorted(obj_entities,key=lambda x: x.id):
                info = record.executing_social_security_ids.filtered(lambda x: x.TerceroICBF.id == entity.id and x.nValorICBF != 0)
                nValorICBF = 0
                for i in info:
                    nValorICBF += i.nValorICBF

                if nValorICBF != 0:
                    dict_eps = {'name': entity.partner_id.name,
                                'identifcation': entity.partner_id.vat,
                                'cod_pila': entity.code_pila_eps,
                                'num_employees': len(info.employee_id),
                                'value_icbf': float("{:.2f}".format(nValorICBF)),
                                }
                    lst_eps.append(dict_eps)

        return lst_eps




    def get_excel(self):
        """
        Genera el archivo Excel de la planilla de seguridad social con diseño simplificado:
        - Encabezados con ajuste de texto (text_wrap)
        - Fijación (freeze) de la cabecera de la tabla de empleados
        - Totales y subtotales optimizados para mejor visualización
        - Paleta de colores simplificada para mejorar la experiencia visual
        - Gráficos para visualización de métricas clave
        """
        import io, math, base64, unicodedata
        from io import BytesIO
        from datetime import datetime, timedelta
        from dateutil.relativedelta import relativedelta
        import xlsxwriter
        from odoo.exceptions import UserError
        from odoo import _
        from collections import defaultdict

        def auto_adjust_columns(ws, rows):
            # Ajusta el ancho de cada columna en función del contenido más largo
            col_widths = {}
            for row_data in rows:
                for i, cell in enumerate(row_data):
                    cell_str = str(cell)
                    col_widths[i] = max(col_widths.get(i, 0), len(cell_str))
            for col, width in col_widths.items():
                ws.set_column(col, col, width + 2)

        def remove_accents(input_str):
            nfkd_form = unicodedata.normalize('NFKD', input_str)
            return "".join([c for c in nfkd_form if not unicodedata.combining(c)])

        def get_applied_days(item, cVAC, cSLN, cIGE, cLMA):
            if cVAC in ('X', 'L'):
                return item.nDiasVacaciones if item.nDiasVacaciones else item.nDiasLiquidados
            elif cSLN == 'X':
                return item.nDiasLicencia if item.nDiasLicencia else item.nDiasLiquidados
            elif cIGE == 'X':
                return item.nDiasIncapacidadEPS if item.nDiasIncapacidadEPS else item.nDiasLiquidados
            elif cLMA == 'X':
                return item.nDiasMaternidad if item.nDiasMaternidad else item.nDiasLiquidados
            else:
                return item.nDiasLiquidados

        # -------------------------------------------------------------------------
        # Preparación del workbook
        # -------------------------------------------------------------------------
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output)
        
        date_start_str = '01/' + str(self.month) + '/' + str(self.year)
        try:
            date_start_dt = datetime.strptime(date_start_str, '%d/%m/%Y')
            date_end_dt = date_start_dt + relativedelta(months=1) - timedelta(days=1)
            date_start = date_start_dt.date()
            date_end = date_end_dt.date()
            period_str = date_start_dt.strftime('%B %Y').title()
        except Exception:
            raise UserError(_('El año digitado es inválido, por favor verificar.'))

        # Paleta de colores simplificada
        primary_color = '#2F5496'      # Azul más profesional 
        secondary_color = '#4472C4'    # Azul más claro para acentos
        neutral_bg = '#F2F2F2'         # Gris claro para filas alternas
        header_bg = '#E7EFFA'          # Azul muy claro para encabezados
        section_bg = '#CFD9EA'         # Azul grisáceo para secciones
        alert_color = '#FF6B6B'        # Color para alertas (menos intenso)
        
        # Colores para gráficos
        chart_colors = ['#4472C4', '#ED7D31', '#A5A5A5', '#FFC000', '#5B9BD5', '#70AD47', '#264478', '#9E480E']

        # Formatos básicos
        title_format = workbook.add_format({
            'bold': True, 'align': 'center', 'valign': 'vcenter',
            'font_size': 14, 'font_color': 'black',
            'border': 0, 'font_name': 'Arial'
        })

        subtitle_format = workbook.add_format({
            'bold': True, 'align': 'center', 'valign': 'vcenter',
            'font_size': 12, 'font_color': primary_color,
            'font_name': 'Arial'
        })

        header_format = workbook.add_format({
            'bold': True, 'align': 'center', 'valign': 'vcenter',
            'bg_color': primary_color, 'border': 1,
            'font_color': 'white', 'font_size': 10,
            'font_name': 'Arial', 'text_wrap': True
        })

        section_format = workbook.add_format({
            'bold': True, 'align': 'left', 'valign': 'vcenter',
            'bg_color': secondary_color, 'border': 1,
            'font_color': 'white', 'font_size': 11,
            'font_name': 'Arial'
        })

        # Formato para etiquetas sin fondo de color - como en la imagen
        label_format = workbook.add_format({
            'bold': False, 
            'align': 'left', 
            'valign': 'vcenter',
            'border': 1,
            'font_color': 'black',
            'font_size': 10,
            'font_name': 'Arial'
        })

        # Formato para datos
        data_format = workbook.add_format({
            'align': 'left', 
            'valign': 'vcenter',
            'border': 1,
            'font_color': 'black', 
            'font_size': 10,
            'font_name': 'Arial'
        })

        cell_format = workbook.add_format({
            'align': 'left', 'valign': 'vcenter', 'border': 1,
            'font_name': 'Arial', 'font_size': 9
        })

        number_format = workbook.add_format({
            'align': 'right', 'valign': 'vcenter', 'border': 1,
            'num_format': '#,##0', 'font_name': 'Arial', 'font_size': 9
        })

        number_format_decimals = workbook.add_format({
            'align': 'right', 'valign': 'vcenter', 'border': 1,
            'num_format': '#,##0.00', 'font_name': 'Arial', 'font_size': 9
        })

        date_format = workbook.add_format({
            'align': 'center', 'valign': 'vcenter', 'border': 1,
            'num_format': 'dd/mm/yyyy', 'font_name': 'Arial', 'font_size': 9
        })

        indicator_format = workbook.add_format({
            'align': 'center', 'valign': 'vcenter', 'border': 1,
            'bg_color': secondary_color, 'font_color': 'white',
            'bold': True, 'font_name': 'Arial', 'font_size': 9
        })

        no_entity_format = workbook.add_format({
            'align': 'center', 'valign': 'vcenter', 'border': 1,
            'bg_color': alert_color, 'font_color': 'white',
            'bold': True, 'font_name': 'Arial', 'font_size': 9
        })

        subtotal_format = workbook.add_format({
            'align': 'right', 'valign': 'vcenter', 'border': 1,
            'bg_color': section_bg, 'font_color': 'black',
            'bold': True, 'font_name': 'Arial', 'font_size': 9,
            'num_format': '#,##0.00'
        })

        total_row_format = workbook.add_format({
            'align': 'right', 'valign': 'vcenter', 'border': 1,
            'bg_color': primary_color, 'font_color': 'white',
            'bold': True, 'font_name': 'Arial', 'font_size': 10,
            'num_format': '#,##0.00', 'bottom': 2
        })

        total_label_format = workbook.add_format({
            'align': 'right', 'valign': 'vcenter', 'border': 1,
            'bg_color': primary_color, 'font_color': 'white',
            'bold': True, 'font_name': 'Arial', 'font_size': 10,
            'bottom': 2
        })

        total_empty_format = workbook.add_format({
            'bg_color': primary_color, 'border': 1,
            'bottom': 2
        })

        warning_format = workbook.add_format({
            'align': 'center', 'valign': 'vcenter', 'border': 1,
            'bg_color': alert_color, 'font_color': 'white',
            'bold': True, 'font_name': 'Arial', 'font_size': 9
        })
        
        chart_title_format = workbook.add_format({
            'bold': True,
            'font_size': 10,
            'font_color': primary_color,
            'font_name': 'Arial',
            'align': 'center'
        })

        # -------------------------------------------------------------------------
        # Creación de la hoja de trabajo
        # -------------------------------------------------------------------------
        ws = workbook.add_worksheet('Planilla SS')
        ws.set_zoom(85)
        ws.set_default_row(18)
        
        # Configurar anchos de columna según los nuevos requerimientos (15 columnas en total)
        ws.set_column('A:D', 15)      # Etiquetas (4 columnas)
        ws.set_column('E:G', 15)     # Datos bloque 1 (3 columnas)
        ws.set_column('H:K', 15)     # Etiquetas bloque 2 (4 columnas)
        ws.set_column('L:O', 15)     # Datos bloque 2 (4 columnas)

        ws.set_margins(left=0.5, right=0.5, top=0.5, bottom=0.5)
        ws.set_paper(9)
        ws.set_landscape()

        # Insertar logo
        if self.company_id.logo:
            try:
                logo_data = base64.b64decode(self.company_id.logo)
                logo_image = BytesIO(logo_data)
                ws.insert_image('A1', 'logo.png', {
                    'image_data': logo_image,
                    'x_scale': 0.5,
                    'y_scale': 0.5,
                    'x_offset': 5,
                    'y_offset': 5
                })
            except Exception:
                pass

        # Título principal - Centrado en la hoja
        ws.merge_range('D1:L1', 'PLANILLA INTEGRADA DE LIQUIDACIÓN DE APORTES', title_format)
        ws.merge_range('D2:L2', f'PERIODO: {period_str}', subtitle_format)

        # Información general y cálculos
        totals = self.info_totals()
        month_next = str(int(self.month) + 1).zfill(2) if self.month != '12' else '01'
        year_next = str(self.year) if self.month != '12' else str(self.year + 1)
        period_health = f"{year_next}-{month_next}"
        period_dif_health = f"{self.year}-{self.month.zfill(2)}"

        # Filtrar detalles según presentación
        if self.presentation_form != 'U':
            if self.work_center_social_security_id:
                details = self.executing_social_security_ids.filtered(
                    lambda x: x.employee_id.work_center_social_security_id.id == self.work_center_social_security_id.id
                )
            else:
                details = self.executing_social_security_ids.filtered(
                    lambda x: x.employee_id.branch_social_security_id.id == self.branch_social_security_id.id
                )
        else:
            details = self.executing_social_security_ids

        # Ordenar por nombre y apellidos
        details = sorted(details, key=lambda item: (
            remove_accents(item.employee_id.work_contact_id.first_lastname or ''),
            remove_accents(item.employee_id.work_contact_id.second_lastname or ''),
            remove_accents(item.employee_id.work_contact_id.firs_name or ''),
            remove_accents(item.employee_id.work_contact_id.second_name or '')
        ))
        
        # Cálculos de días totales
        total_liquidados = sum(item.nDiasLiquidados for item in details)
        total_incap_eps = sum(item.nDiasIncapacidadEPS for item in details)
        total_licencia = sum(item.nDiasLicencia for item in details)
        total_licencia_ren = sum(item.nDiasLicenciaRenumerada for item in details)
        total_maternidad = sum(item.nDiasMaternidad for item in details)
        total_vacaciones_dias = sum(item.nDiasVacaciones for item in details)
        total_incap_arp = sum(item.nDiasIncapacidadARP for item in details)
        total_horas = sum(item.nNumeroHorasLaboradas for item in details)
        
        # Total de días para gráfico
        total_dias_all = total_liquidados + total_incap_eps + total_licencia + total_licencia_ren + total_maternidad + total_vacaciones_dias + total_incap_arp
        
        # Contar novedades
        ingresos_set = set()
        retiros_set = set()
        vacaciones_set = set()
        licencias_set = set()
        incapacidades_set = set()
        for item in details:
            cIngreso = 'X' if item.nIngreso and item.nDiasLiquidados > 0 else ''
            cRetiro = 'X' if item.nRetiro and item.nDiasLiquidados > 0 else ''
            cVAC = 'X' if item.nDiasVacaciones > 0 else ('L' if item.nDiasLicenciaRenumerada > 0 else '')
            cSLN = 'X' if item.nDiasLicencia > 0 else ''
            cIGE = 'X' if item.nDiasIncapacidadEPS > 0 else ''
            
            if cIngreso == 'X':
                ingresos_set.add(item.employee_id.id)
            if cRetiro == 'X':
                retiros_set.add(item.employee_id.id)
            if cVAC in ('X', 'L'):
                vacaciones_set.add(item.employee_id.id)
            if cSLN == 'X':
                licencias_set.add(item.employee_id.id)
            if cIGE == 'X':
                incapacidades_set.add(item.employee_id.id)
                    
        total_ingresos_unique = len(ingresos_set)
        total_retiros_unique = len(retiros_set)
        total_vacaciones_unique = len(vacaciones_set)
        total_licencias_unique = len(licencias_set)
        total_incapacidades_unique = len(incapacidades_set)

        # -------------------------------------------------------------------------
        # SECCIÓN DE INFORMACIÓN DE LA EMPRESA (2 columnas x 2 valores)
        # -------------------------------------------------------------------------
        row = 4
        ws.merge_range(row, 0, row, 14, 'INFORMACIÓN DE LA EMPRESA', section_format)
        row += 1
        
        # Primera fila - 2 datos (Empresa y NIT)
        ws.merge_range(row, 0, row, 3, "Empresa:", label_format)
        ws.merge_range(row, 4, row, 6, self.company_id.name, data_format)
        
        ws.merge_range(row, 7, row, 10, "NIT:", label_format)
        ws.merge_range(row, 11, row, 14, f"{self.company_id.partner_id.vat_co}-{self.company_id.partner_id.dv}", data_format)
        row += 1
        
        # Segunda fila - 2 datos (Dirección y Periodo)
        ws.merge_range(row, 0, row, 3, "Dirección:", label_format)
        ws.merge_range(row, 4, row, 6, self.company_id.partner_id.street or 'N/A', data_format)
        
        ws.merge_range(row, 7, row, 10, "Periodo:", label_format)
        ws.merge_range(row, 11, row, 14, f"{self.month}/{self.year}", data_format)
        row += 1
        
        # Tercera fila - 2 datos (Sucursal y Tipo Planilla)
        ws.merge_range(row, 0, row, 3, "Sucursal:", label_format)
        ws.merge_range(row, 4, row, 6, self.branch_social_security_id.name if self.branch_social_security_id else 'N/A', data_format)
        
        ws.merge_range(row, 7, row, 10, "Tipo de Planilla:", label_format)
        ws.merge_range(row, 11, row, 14, self.presentation_form or "N/A", data_format)
        row += 1
        
        # Cuarta fila - 2 datos (Centro Trabajo y Código Sucursal)
        ws.merge_range(row, 0, row, 3, "Centro de Trabajo:", label_format)
        ws.merge_range(row, 4, row, 6, self.work_center_social_security_id.name if self.work_center_social_security_id else 'N/A', data_format)
        
        ws.merge_range(row, 7, row, 10, "Código Sucursal:", label_format)
        ws.merge_range(row, 11, row, 14, self.branch_social_security_id.code if self.branch_social_security_id else 'N/A', data_format)
        row += 1
        
        # Quinta fila - 2 datos (Impreso por y Fecha Generación)
        ws.merge_range(row, 0, row, 3, "Impreso por:", label_format)
        ws.merge_range(row, 4, row, 6, self.env.user.name or 'N/A', data_format)
        
        ws.merge_range(row, 7, row, 10, "Fecha Generación:", label_format)
        ws.merge_range(row, 11, row, 14, fields.Datetime.now().strftime('%Y-%m-%d %H:%M'), data_format)
        row += 1
        
        # Sexta fila - 2 datos (Entidad ARL y Periodo Cot. Salud)
        ws.merge_range(row, 0, row, 3, "Entidad ARL:", label_format)
        ws.merge_range(row, 4, row, 6, self.arl_id.name if hasattr(self, 'arl_id') and self.arl_id else 'N/A', data_format)
        
        ws.merge_range(row, 7, row, 10, "Periodo Cot. Salud:", label_format)
        ws.merge_range(row, 11, row, 14, period_health, data_format)
        row += 1
        
        # Séptima fila - 2 datos (Código ARL y Periodo Dif. Salud)
        ws.merge_range(row, 0, row, 3, "Código ARL:", label_format)
        ws.merge_range(row, 4, row, 6, self.arl_id.code_pila_eps if hasattr(self, 'arl_id') and self.arl_id else 'N/A', data_format)
        
        ws.merge_range(row, 7, row, 10, "Periodo Dif. Salud:", label_format)
        ws.merge_range(row, 11, row, 14, period_dif_health, data_format)
        row += 1
        
        # Octava fila - 2 datos (Fecha Impresión y Generado por)
        ws.merge_range(row, 0, row, 3, "Fecha Impresión:", label_format)
        ws.merge_range(row, 4, row, 6, fields.Datetime.now().strftime('%Y-%m-%d %H:%M'), data_format)
        
        ws.merge_range(row, 7, row, 10, "Generado por:", label_format)
        ws.merge_range(row, 11, row, 14, self.env.user.name or 'N/A', data_format)
        row += 1
        
        # Novena fila - 2 datos (Total Empleados y Total Pagar Empleados)
        ws.merge_range(row, 0, row, 3, "Total Empleados:", label_format)
        ws.merge_range(row, 4, row, 6, totals['total_employees'], number_format)
        
        ws.merge_range(row, 7, row, 10, "Total Pagar Empleados:", label_format)
        ws.merge_range(row, 11, row, 14, totals['total_amount_employees'], number_format_decimals)
        row += 1
        
        # Décima fila - 2 datos (Total Pagar Empresa y Total General)
        ws.merge_range(row, 0, row, 3, "Total Pagar Empresa:", label_format)
        ws.merge_range(row, 4, row, 6, totals['total_amount_company'], number_format_decimals)
        
        ws.merge_range(row, 7, row, 10, "Total General:", label_format)
        ws.merge_range(row, 11, row, 14, totals['total_amount_final'], number_format_decimals)
        row += 1
        
        # -------------------------------------------------------------------------
        # GRÁFICOS DE PAGOS Y DÍAS
        # -------------------------------------------------------------------------
        # Crear una hoja para almacenar los datos de los gráficos (oculta)
        chart_data = workbook.add_worksheet('_ChartData')
        chart_data.hide()

        # Datos para gráfico de pagos
        chart_data.write_column('A1', ['Empleados', 'Empresa'])
        chart_data.write_column('B1', [totals['total_amount_employees'], totals['total_amount_company']])

        # Datos para gráfico de días
        chart_data.write_column('D1', ['Liquidados', 'Incapacidad EPS', 'Licencia', 'Licencia Rem.', 'Maternidad', 'Vacaciones', 'Incapacidad ARP'])
        chart_data.write_column('E1', [total_liquidados, total_incap_eps, total_licencia, total_licencia_ren, total_maternidad, total_vacaciones_dias, total_incap_arp])

        # Crear gráfico de pagos (pie chart)
        pay_chart = workbook.add_chart({'type': 'pie'})
        pay_chart.add_series({
            'name': 'Distribución de Pagos',
            'categories': '_ChartData!$A$1:$A$2',
            'values': '_ChartData!$B$1:$B$2',
            'data_labels': {'percentage': True, 'category': True, 'position': 'outside_end'},
            'points': [
                {'fill': {'color': chart_colors[0]}},
                {'fill': {'color': chart_colors[1]}}
            ]
        })
        # Formato del título con diccionario de propiedades en lugar de objeto de formato
        pay_chart.set_title({
            'name': 'Distribución de Pagos', 
            'name_font': {
                'bold': True,
                'size': 10,
                'color': primary_color
            }
        })
        pay_chart.set_legend({'position': 'bottom'})
        pay_chart.set_size({'width': 300, 'height': 200})

        # Crear gráfico de días (columnas apiladas)
        days_chart = workbook.add_chart({'type': 'column'})
        days_chart.add_series({
            'name': 'Días por Tipo',
            'categories': '_ChartData!$D$1:$D$7',
            'values': '_ChartData!$E$1:$E$7',
            'data_labels': {'value': True},
            'points': [
                {'fill': {'color': chart_colors[0]}},
                {'fill': {'color': chart_colors[1]}},
                {'fill': {'color': chart_colors[2]}},
                {'fill': {'color': chart_colors[3]}},
                {'fill': {'color': chart_colors[4]}},
                {'fill': {'color': chart_colors[5]}},
                {'fill': {'color': chart_colors[6]}}
            ]
        })
        # Formato del título con diccionario de propiedades en lugar de objeto de formato
        days_chart.set_title({
            'name': 'Distribución de Días', 
            'name_font': {
                'bold': True,
                'size': 10,
                'color': primary_color
            }
        })
        days_chart.set_legend({'position': 'bottom'})
        days_chart.set_y_axis({'major_gridlines': {'visible': False}})
        days_chart.set_size({'width': 500, 'height': 200})

        # Insertar los gráficos
        chart_row = row + 1
        ws.merge_range(chart_row, 0, chart_row, 14, 'GRÁFICOS DE ANÁLISIS', section_format)
        chart_row += 1

        ws.insert_chart(chart_row, 0, pay_chart, {'x_offset': 25, 'y_offset': 10})
        ws.insert_chart(chart_row, 7, days_chart, {'x_offset': 25, 'y_offset': 10})
        # Avanzar filas para dar espacio a los gráficos
        row = chart_row + 15  # Aproximadamente el espacio que ocuparán los gráficos
        
        # -------------------------------------------------------------------------
        # SECCIÓN DE MÉTRICAS DE EMPLEADOS
        # -------------------------------------------------------------------------
        ws.merge_range(row, 0, row, 14, 'MÉTRICAS DE EMPLEADOS', section_format)
        row += 1
        
        # Primera fila de métricas - Estudiantes/Practicantes y Pensionados
        ws.merge_range(row, 0, row, 3, "Estudiantes/Practicantes:", label_format)
        ws.merge_range(row, 4, row, 6, totals.get('total_estudiantes', 0), number_format)
        
        ws.merge_range(row, 7, row, 10, "Pensionados:", label_format)
        ws.merge_range(row, 11, row, 14, totals.get('total_pensionados', 0), number_format)
        row += 1
        
        # Segunda fila de métricas - Tipo Contribuyente 12 y Tipo Contribuyente 19
        ws.merge_range(row, 0, row, 3, "Tipo Contribuyente 12:", label_format)
        ws.merge_range(row, 4, row, 6, totals.get('total_tipo_12', 0), number_format)
        
        ws.merge_range(row, 7, row, 10, "Tipo Contribuyente 19:", label_format)
        ws.merge_range(row, 11, row, 14, totals.get('total_tipo_19', 0), number_format)
        row += 1
        
        # Tercera fila de métricas - Subtipo != 00 y Subtipo 00
        ws.merge_range(row, 0, row, 3, "Subtipo != 00 (Pens.):", label_format)
        ws.merge_range(row, 4, row, 6, totals.get('total_pensionados', 0), number_format)
        
        ws.merge_range(row, 7, row, 10, "Subtipo 00 (No pens.):", label_format)
        ws.merge_range(row, 11, row, 14, totals.get('total_subtipo_00', 0), number_format)
        row += 1
        
        # Cuarta fila de métricas - Empleados Normales y Subtipo 01
        ws.merge_range(row, 0, row, 3, "Empleados Normales:", label_format)
        ws.merge_range(row, 4, row, 6, totals.get('total_empleados_normales', 0), number_format)
        
        ws.merge_range(row, 7, row, 10, "Subtipo 01 (Regulares):", label_format)
        ws.merge_range(row, 11, row, 14, totals.get('total_subtipo_01', 0), number_format)
        row += 1
        
        # -------------------------------------------------------------------------
        # SECCIÓN DE RESUMEN DE NOVEDADES
        # -------------------------------------------------------------------------
        row += 1
        ws.merge_range(row, 0, row, 14, 'RESUMEN DE NOVEDADES', section_format)
        row += 1
        
        # Primera fila de resumen - Días Liquidados y Días Incap. EPS
        ws.merge_range(row, 0, row, 3, "Días Liquidados:", label_format)
        ws.merge_range(row, 4, row, 6, total_liquidados, number_format)
        
        ws.merge_range(row, 7, row, 10, "Días Incap. EPS:", label_format)
        ws.merge_range(row, 11, row, 14, total_incap_eps, number_format)
        row += 1
        
        # Segunda fila de resumen - Días Lic. Rem. y Días Maternidad
        ws.merge_range(row, 0, row, 3, "Días Lic. Rem.:", label_format)
        ws.merge_range(row, 4, row, 6, total_licencia_ren, number_format)
        
        ws.merge_range(row, 7, row, 10, "Días Maternidad:", label_format)
        ws.merge_range(row, 11, row, 14, total_maternidad, number_format)
        row += 1
        
        # Tercera fila de resumen - Días Incap. ARP y Horas laboradas
        ws.merge_range(row, 0, row, 3, "Días Incap. ARP:", label_format)
        ws.merge_range(row, 4, row, 6, total_incap_arp, number_format)
        
        ws.merge_range(row, 7, row, 10, "Horas laboradas:", label_format)
        ws.merge_range(row, 11, row, 14, total_horas, number_format)
        row += 1
        
        # Cuarta fila de resumen - Días Licencia y Días Vacaciones
        ws.merge_range(row, 0, row, 3, "Días Licencia:", label_format)
        ws.merge_range(row, 4, row, 6, total_licencia, number_format)
        
        ws.merge_range(row, 7, row, 10, "Días Vacaciones:", label_format)
        ws.merge_range(row, 11, row, 14, total_vacaciones_dias, number_format)
        row += 1
        
        # Quinta fila de resumen - Empleados Ingreso y Empleados Retiro
        ws.merge_range(row, 0, row, 3, "Empleados Ingreso:", label_format)
        ws.merge_range(row, 4, row, 6, total_ingresos_unique, number_format)
        
        ws.merge_range(row, 7, row, 10, "Empleados Retiro:", label_format)
        ws.merge_range(row, 11, row, 14, total_retiros_unique, number_format)
        row += 1
        
        # Sexta fila de resumen - Empleados Vac. y Empleados Licencia
        ws.merge_range(row, 0, row, 3, "Empleados Vac.:", label_format)
        ws.merge_range(row, 4, row, 6, total_vacaciones_unique, number_format)
        
        ws.merge_range(row, 7, row, 10, "Empleados Licencia:", label_format)
        ws.merge_range(row, 11, row, 14, total_licencias_unique, number_format)
        row += 1
        
        # Séptima fila de resumen - Empleados Incap. y Días Susp. Contrato
        ws.merge_range(row, 0, row, 3, "Empleados Incap.:", label_format)
        ws.merge_range(row, 4, row, 6, total_incapacidades_unique, number_format)
        
        ws.merge_range(row, 7, row, 10, "Días Susp. Contrato:", label_format)
        ws.merge_range(row, 11, row, 14, 0, number_format)
        row += 1
        
        # Octava fila de resumen - Empleados Suspendidos
        ws.merge_range(row, 0, row, 3, "Empleados Suspendidos:", label_format)
        ws.merge_range(row, 4, row, 6, 0, number_format)
        row += 1
        
    
        # Pie de página
        row += 2
        footer_format = workbook.add_format({
            'font_size': 9,
            'align': 'center',
            'valign': 'vcenter',
            'italic': True
        })
        
        ws.merge_range(row, 0, row, 33, 
            f"Generado el {fields.Datetime.now().strftime('%Y-%m-%d %H:%M')} por {self.env.user.name}. Documento meramente informativo.", 
            footer_format)
        # -------------------------------------------------------------------------
        # DETALLE DE EMPLEADOS
        # -------------------------------------------------------------------------
        ws.merge_range(row, 0, row, 87, '', section_format)
        ws.write(row, 0, "DETALLE DE EMPLEADOS", section_format)
        row += 1

        headers = [
            "Tipo ID", "Documento", "Tipo Cotizante", "Subtipo Cotizante",
            "Ext. No Aporta", "Residente Ext.", "Depto.", "Ciudad", "Nombre Empleado",
            "ING", "RET", "TDE", "TAE", "TDP", "TAP", "VSP", "VST", "SLN", "IGE", "LMA", "VAC", "AVP", "VCT", "IRP",
            "Cód. Pensión", "Adm. Pensión", "Cód. Traslado P.", "Adm. Traslado P.",
            "Cód. Salud", "Adm. Salud", "Cód. Traslado S.", "Adm. Traslado S.",
            "Cód. CCF", "CCF", "Días Pensión", "Días Salud", "Días Riesgos", "Días CCF",
            "Salario Base", "Salario Integral", "IBC Pensión", "IBC Salud", "IBC Riesgos", "IBC CCF", "IBC Parafiscales",
            "Tarifa Pensión", "Aporte Adic. P.", "Cot. Oblig. Pensión", "Aporte Vol. Afil.",
            "Aporte Vol. Aport.", "FSP Solidaridad", "FSP Subsistencia","Total Pensión", 
            "Tarifa Salud", "Cot. Oblig. Salud", "Valor UPC", "Clase Riesgo", "Tarifa ARL", 
            "Centro Trabajo", "Cot. Riesgos", "Tarifa CCF", "Cot. CCF", "Tarifa SENA", "Cot. SENA",
            "Tarifa ICBF", "Cot. ICBF", "Exonerado", "Act. Económica",
            "F. Ingreso", "F. Retiro", "F. Inicio VSP", "F. Inicio SLN", "F. Fin SLN",
            "F. Inicio IGE", "F. Fin IGE", "F. Inicio LMA", "F. Fin LMA", "F. Inicio VAC",
            "F. Fin VAC", "F. Inicio VCT", "F. Fin VCT", "F. Inicio IRL", "F. Fin IRL",
            "Horas", "F. Rad. Exterior",
            "Total Empleado", "Total Empresa", "Total Línea"
        ]
        total_columns = len(headers)
        for col, header in enumerate(headers):
            ws.write(row, col, header, header_format)
        ws.set_row(row, 30)  # Ajuste de altura para encabezados
        row += 1
        #ws.freeze_panes(row, 0)  # Fijar la cabecera de la tabla

        # Almacenar filas para luego calcular totales
        detail_data_rows = [headers]

        # Agrupar detalles por empleado
        employee_dict = {}
        for item in details:
            emp_id = item.employee_id.id
            if emp_id not in employee_dict:
                employee_dict[emp_id] = []
            employee_dict[emp_id].append(item)

        # Para resaltar filas pares/impares
        idx = 0

        # Calcular totales de empleado, empresa, etc.
        total_general_empleado = 0
        total_general_empresa = 0
        total_general_linea = 0

        # Diccionarios para entidades
        eps_totals = defaultdict(lambda: {'employees': 0, 'value_employees': 0, 'value_company': 0, 'dif_round': 0})
        pension_totals = defaultdict(lambda: {'employees': 0, 'value_employees': 0, 'value_company': 0, 'dif_round': 0})
        arp_totals = defaultdict(lambda: {'employees': 0, 'value_arp': 0})
        ccf_totals = defaultdict(lambda: {'employees': 0, 'value_cajacom': 0})

        without_pension = 0
        without_eps = 0
        without_ccf = 0
        # Procesar cada empleado y sus líneas
        for emp_id, emp_details in employee_dict.items():
            # Ordenar: línea principal primero, luego novedades
            emp_details.sort(key=lambda x: 1 if (x.nDiasLicencia > 0 or x.nDiasIncapacidadEPS > 0 or
                                            x.nDiasMaternidad > 0 or x.nDiasVacaciones > 0) else 0)
            for item in emp_details:
                # Formatos alternados - simplificados
                row_bg_color = neutral_bg if idx % 2 == 0 else 'white'
                row_format = workbook.add_format({
                    'align': 'left', 'valign': 'vcenter', 'border': 1,
                    'font_name': 'Arial', 'font_size': 9,
                    'bg_color': row_bg_color
                })
                row_number_format = workbook.add_format({
                    'align': 'right', 'valign': 'vcenter', 'border': 1,
                    'num_format': '#,##0', 'font_name': 'Arial', 'font_size': 9,
                    'bg_color': row_bg_color
                })
                row_decimal_format = workbook.add_format({
                    'align': 'right', 'valign': 'vcenter', 'border': 1,
                    'num_format': '#,##0.00', 'font_name': 'Arial', 'font_size': 9,
                    'bg_color': row_bg_color
                })
                row_date_format = workbook.add_format({
                    'align': 'center', 'valign': 'vcenter', 'border': 1,
                    'num_format': 'dd/mm/yyyy', 'font_name': 'Arial', 'font_size': 9,
                    'bg_color': row_bg_color
                })
                row_indicator_format = workbook.add_format({
                    'align': 'center', 'valign': 'vcenter', 'border': 1,
                    'bg_color': secondary_color, 
                    'font_color': 'white',
                    'bold': True, 'font_name': 'Arial', 'font_size': 9
                })
                row_no_entity_format = workbook.add_format({
                    'align': 'center', 'valign': 'vcenter', 'border': 1,
                    'bg_color': alert_color, 'font_color': 'white',
                    'bold': True, 'font_name': 'Arial', 'font_size': 9
                })

                # Tipo de ID
                switch_type_id = {
                    '11': 'RC', '12': 'TI', '13': 'CC', '22': 'CE',
                    '31': 'NI', '41': 'PA', '47': 'PT', '42': 'CE'
                }
                id_type = switch_type_id.get(item.employee_id.work_contact_id.l10n_latam_identification_type_id.dian_code, '/')

                # Detectar cambio de salario
                obj_change_wage = self.env['hr.contract.change.wage'].search([
                    ('contract_id', '=', item.contract_id.id),
                    ('date_start', '!=', False),
                    ('date_start', '>=', date_start),
                    ('date_start', '<=', date_end)
                ], limit=1)

                # Indicadores
                cIngreso = 'X' if item.nIngreso and item.nDiasLiquidados > 0 else ''
                cRetiro = 'X' if item.nRetiro and item.nDiasLiquidados > 0 else ''
                cVSP = 'X' if obj_change_wage and item.nDiasLiquidados > 0 and cIngreso != 'X' else ''
                if item.employee_id.tipo_coti_id.code == '51':
                    cVSP = ''
                cVST = 'X' if (item.nValorBaseSalud > math.ceil((item.nSueldo / 30) * item.nDiasLiquidados)
                            and item.nDiasLiquidados > 0
                            and (item.employee_id.tipo_coti_id.code not in ('12', '19'))
                            and cVSP != 'X') else ''
                if item.employee_id.tipo_coti_id.code == '51':
                    cVST = ''
                cSLN = 'X' if item.nDiasLicencia > 0 else ''
                cIGE = 'X' if item.nDiasIncapacidadEPS > 0 else ''
                cLMA = 'X' if item.nDiasMaternidad > 0 else ''
                cVAC = 'X' if item.nDiasVacaciones > 0 else ('L' if item.nDiasLicenciaRenumerada > 0 else '')
                cAVP = 'X' if item.nDiasLiquidados > 0 and item.cAVP and item.nAporteVoluntarioPension > 0 else ''

                dias_aplicados = get_applied_days(item, cVAC, cSLN, cIGE, cLMA)
                dias_cotizados_pension = dias_aplicados if (item.nValorPensionEmpleado + item.nValorPensionEmpresa) > 0 else 0
                dias_cotizados_salud = dias_aplicados if (item.nValorSaludEmpleado + item.nValorSaludEmpresa) > 0 else 0
                dias_cotizados_riesgos = dias_aplicados if (item.nValorARP) > 0 else 0
                dias_cotizados_caja = dias_aplicados if (item.nValorCajaCom) > 0 else 0

                dept_code = item.employee_id.work_contact_id.city_id.state_id.code if (item.employee_id.work_contact_id.city_id and item.employee_id.work_contact_id.city_id.state_id) else ''
                city_code = item.employee_id.work_contact_id.city_id.code if item.employee_id.work_contact_id.city_id else ''
                full_name = item.employee_id.work_contact_id.name or ''
                activity = item.contract_id.economic_activity_level_risk_id
                activity_code = f"{activity.risk_class_id.code}-{activity.code_ciiu_id.code}-{activity.code}" if activity else ''
                risk_name = activity.risk_class_id.name if activity else ''

                pension_missing = not item.TerceroPension
                eps_missing = not item.TerceroEPS
                ccf_missing = not item.TerceroCajaCom

                if pension_missing:
                    without_pension += 1
                if eps_missing:
                    without_eps += 1
                if ccf_missing:
                    without_ccf += 1
                total_empleado = (
                    item.nValorPensionEmpleado +
                    item.nValorSaludEmpleado +
                    item.nAporteVoluntarioPension +
                    item.nValorFondoSolidaridad +
                    item.nValorFondoSubsistencia
                )
                total_empresa = (
                    item.nValorPensionEmpresa +
                    item.nValorSaludEmpresa +
                    item.nValorARP +
                    item.nValorCajaCom +
                    item.nValorSENA +
                    item.nValorICBF
                )
                total_linea = total_empleado + total_empresa

                total_general_empleado += total_empleado
                total_general_empresa += total_empresa
                total_general_linea += total_linea

                # Actualizar dicts de entidades
                if item.TerceroEPS:
                    key = item.TerceroEPS.id
                    eps_totals[key]['employees'] += 1
                    eps_totals[key]['value_employees'] += item.nValorSaludEmpleado
                    eps_totals[key]['value_company'] += item.nValorSaludEmpresa
                    eps_totals[key]['name'] = item.TerceroEPS.partner_id.name
                    eps_totals[key]['identifcation'] = item.TerceroEPS.partner_id.vat
                    eps_totals[key]['cod_pila'] = item.TerceroEPS.code_pila_eps

                if item.TerceroPension:
                    key = item.TerceroPension.id
                    pension_totals[key]['employees'] += 1
                    pension_totals[key]['value_employees'] += (item.nValorPensionEmpleado
                                                            + item.nAporteVoluntarioPension
                                                            + item.nValorFondoSolidaridad
                                                            + item.nValorFondoSubsistencia)
                    pension_totals[key]['value_company'] += item.nValorPensionEmpresa
                    pension_totals[key]['name'] = item.TerceroPension.partner_id.name
                    pension_totals[key]['identifcation'] = item.TerceroPension.partner_id.vat
                    pension_totals[key]['cod_pila'] = item.TerceroPension.code_pila_eps

                if item.TerceroARP:
                    key = item.TerceroARP.id
                    arp_totals[key]['employees'] += 1
                    arp_totals[key]['value_arp'] += item.nValorARP
                    arp_totals[key]['name'] = item.TerceroARP.partner_id.name
                    arp_totals[key]['identifcation'] = item.TerceroARP.partner_id.vat
                    arp_totals[key]['cod_pila'] = item.TerceroARP.code_pila_eps

                if item.TerceroCajaCom:
                    key = item.TerceroCajaCom.id
                    ccf_totals[key]['employees'] += 1
                    ccf_totals[key]['value_cajacom'] += item.nValorCajaCom
                    ccf_totals[key]['name'] = item.TerceroCajaCom.partner_id.name
                    ccf_totals[key]['identifcation'] = item.TerceroCajaCom.partner_id.vat
                    ccf_totals[key]['cod_pila'] = item.TerceroCajaCom.code_pila_ccf
                # Construir fila de detalle con misma información pero en formato optimizado
                detail_row = [
                    id_type,
                    item.employee_id.work_contact_id.vat_co,
                    item.employee_id.tipo_coti_id.name,
                    item.employee_id.subtipo_coti_id.name if item.employee_id.subtipo_coti_id else '',
                    'X' if item.employee_id.extranjero else '',
                    'X' if item.employee_id.residente else '',
                    dept_code,
                    city_code,
                    full_name,
                    cIngreso,
                    cRetiro,
                    '', '', '', '',  # TDE, TAE, TDP, TAP (vacíos)
                    cVSP,
                    cVST,
                    cSLN,
                    cIGE,
                    cLMA,
                    cVAC,
                    cAVP,
                    ' ',  # Espacio
                    str(str(item.nDiasIncapacidadARP).zfill(2)) if item.nDiasIncapacidadARP else '00',
                    item.TerceroPension.code_pila_eps if item.TerceroPension else 'SIN ASIGNAR',
                    item.TerceroPension.name if item.TerceroPension else 'SIN ASIGNAR',
                    '', '',  # Traslado pensión vacío
                    item.TerceroEPS.code_pila_eps if item.TerceroEPS else 'SIN ASIGNAR',
                    item.TerceroEPS.name if item.TerceroEPS else 'SIN ASIGNAR',
                    '', '',  # Traslado salud vacío
                    item.TerceroCajaCom.code_pila_ccf if item.TerceroCajaCom else 'SIN ASIGNAR',
                    item.TerceroCajaCom.name if item.TerceroCajaCom else 'SIN ASIGNAR',
                    dias_cotizados_pension,
                    dias_cotizados_salud,
                    dias_cotizados_riesgos,
                    dias_cotizados_caja,
                    item.nSueldo,
                    item.nSueldo if item.contract_id.modality_salary == 'integral' else '',
                    item.nValorBaseFondoPension,
                    item.nValorBaseSalud,
                    item.nValorBaseARP,
                    item.nValorBaseCajaCom,
                    item.nValorBaseSENA,
                    (item.nPorcAportePensionEmpleado + item.nPorcAportePensionEmpresa),
                    '',  # Aporte adicional pensión
                    item.nValorPensionEmpleado + item.nValorPensionEmpresa,
                    item.nAporteVoluntarioPension,
                    '',  # Aporte voluntario aportante
                    item.nValorFondoSolidaridad,
                    item.nValorFondoSubsistencia,                    
                    item.nValorPensionEmpleado + item.nValorPensionEmpresa + item.nAporteVoluntarioPension +item.nValorFondoSolidaridad + item.nValorFondoSubsistencia,
                    (item.nPorcAporteSaludEmpleado + item.nPorcAporteSaludEmpresa),
                    item.nValorSaludEmpleado + item.nValorSaludEmpresa,
                    '',  # Valor UPC
                    risk_name,
                    item.nPorcAporteARP,
                    item.employee_id.work_center_social_security_id.name if item.employee_id.work_center_social_security_id else '',
                    item.nValorARP,
                    item.nPorcAporteCajaCom,
                    item.nValorCajaCom,
                    item.nPorcAporteSENA,
                    item.nValorSENA,
                    item.nPorcAporteICBF,
                    item.nValorICBF,
                    item.cExonerado1607 if item.cExonerado1607 else '',
                    activity_code,
                    item.contract_id.date_start.strftime('%d/%m/%Y') if item.contract_id.date_start else '',
                    (item.contract_id.retirement_date.strftime('%d/%m/%Y')
                    if item.contract_id.retirement_date
                    else item.contract_id.date_end.strftime('%d/%m/%Y'))
                    if item.nRetiro and item.nDiasLiquidados > 0 else '',
                    (obj_change_wage.date_start.strftime('%d/%m/%Y')
                    if obj_change_wage and item.nDiasLiquidados > 0 and cIngreso != 'X'
                    else ''),
                    (item.dFechaInicioSLN.strftime('%d/%m/%Y') if item.dFechaInicioSLN else ''),
                    (item.dFechaFinSLN.strftime('%d/%m/%Y') if item.dFechaFinSLN else ''),
                    (item.dFechaInicioIGE.strftime('%d/%m/%Y') if item.dFechaInicioIGE else ''),
                    (item.dFechaFinIGE.strftime('%d/%m/%Y') if item.dFechaFinIGE else ''),
                    (item.dFechaInicioLMA.strftime('%d/%m/%Y') if item.dFechaInicioLMA else ''),
                    (item.dFechaFinLMA.strftime('%d/%m/%Y') if item.dFechaFinLMA else ''),
                    (item.dFechaInicioVACLR.strftime('%d/%m/%Y') if item.dFechaInicioVACLR else ''),
                    (item.dFechaFinVACLR.strftime('%d/%m/%Y') if item.dFechaFinVACLR else ''),
                    (item.dFechaInicioVCT.strftime('%d/%m/%Y') if item.dFechaInicioVCT else ''),
                    (item.dFechaFinVCT.strftime('%d/%m/%Y') if item.dFechaFinVCT else ''),
                    (item.dFechaInicioIRL.strftime('%d/%m/%Y') if item.dFechaInicioIRL else ''),
                    (item.dFechaFinIRL.strftime('%d/%m/%Y') if item.dFechaFinIRL else ''),
                    item.nNumeroHorasLaboradas,
                    item.employee_id.date_of_residence_abroad.strftime('%d/%m/%Y')
                    if item.employee_id.date_of_residence_abroad else '',
                    total_empleado,
                    total_empresa,
                    total_linea
                ]
                # Escribir la fila en el Excel
                for col_idx, value in enumerate(detail_row):
                    # Resaltar entidades sin asignar
                    if col_idx in [24, 25, 28, 29, 32, 33] and (
                        (col_idx in [24, 25] and pension_missing) or
                        (col_idx in [28, 29] and eps_missing) or
                        (col_idx in [32, 33] and ccf_missing)
                    ):
                        ws.write(row, col_idx, value, row_no_entity_format)
                    # Campos de indicadores
                    elif col_idx in [9, 10, 16, 17, 18, 19, 20, 21, 22, 23]:
                        if value:
                            ws.write(row, col_idx, value, row_indicator_format)
                        else:
                            ws.write(row, col_idx, value, row_format)
                    # Columnas enteras
                    elif col_idx in [34, 35, 36, 37, 76, 77] and isinstance(value, (int, float)):
                        ws.write(row, col_idx, value, row_number_format)
                    # Columnas numéricas con decimales
                    elif isinstance(value, (int, float)):
                        ws.write(row, col_idx, value, row_decimal_format)
                    # Columnas de fechas
                    elif 63 <= col_idx <= 75 and value:
                        ws.write(row, col_idx, value, row_date_format)
                    else:
                        ws.write(row, col_idx, value, row_format)

                detail_data_rows.append(detail_row)
                row += 1
                idx += 1
        # -------------------------------------------------------------------------
        # FILA DE TOTALES DEL DETALLE - Con totales financieros completos
        # -------------------------------------------------------------------------
        # Primera columna: etiqueta
        ws.write(row, 0, "TOTALES GENERALES", total_label_format)
        
        # Rellenar celdas vacías para las primeras columnas
        for col in range(1, 34):
            ws.write(row, col, "", total_empty_format)
        
        # Escribir totales de días
        ws.write(row, 34, total_liquidados, total_row_format)
        ws.write(row, 35, total_licencia, total_row_format)
        ws.write(row, 36, total_incap_eps, total_row_format)
        ws.write(row, 37, total_vacaciones_dias, total_row_format)
        
        # Calcular totales financieros relevantes
        total_salario_base = sum(item.nSueldo for item in details)
        total_ibc_pension = sum(item.nValorBaseFondoPension for item in details)
        total_ibc_salud = sum(item.nValorBaseSalud for item in details)
        total_ibc_arl = sum(item.nValorBaseARP for item in details)
        total_ibc_ccf = sum(item.nValorBaseCajaCom for item in details)
        total_ibc_pf = sum(item.nValorBaseSENA for item in details)
        total_pension = sum(item.nValorPensionEmpleado + item.nValorPensionEmpresa for item in details)
        total_pension_fd = sum(item.nValorPensionEmpleado + item.nValorFondoSolidaridad + item.nValorFondoSubsistencia + item.nValorPensionEmpresa for item in details)
        total_salud = sum(item.nValorSaludEmpleado + item.nValorSaludEmpresa for item in details)
        fsp = sum(item.nValorFondoSolidaridad for item in details)
        fss = sum(item.nValorFondoSubsistencia for item in details)
        total_arl = sum(item.nValorARP for item in details)
        total_ccf = sum(item.nValorCajaCom for item in details)
        total_sena = sum(item.nValorSENA for item in details)
        total_icbf = sum(item.nValorICBF for item in details)
        
        # Escribir totales financieros
        ws.write(row, 38, total_salario_base, total_row_format)  # Salario Base
        ws.write(row, 40, total_ibc_pension, total_row_format)   # IBC Pensión
        ws.write(row, 41, total_ibc_salud, total_row_format)     # IBC Salud
        ws.write(row, 42, total_ibc_arl, total_row_format)       # IBC Riesgos
        ws.write(row, 43, total_ibc_ccf, total_row_format)                # IBC CCF
        ws.write(row, 44, total_ibc_pf, total_row_format)                # IBC Parafiscales
        ws.write(row, 45, "", total_empty_format)                # Tarifa Pensión
        ws.write(row, 46, "", total_empty_format)                # Aporte Adicional
        ws.write(row, 47, total_pension, total_row_format)       # Total Cotización Pensión
        ws.write(row, 52, total_pension_fd, total_row_format)
        ws.write(row, 50, fsp, total_row_format) 
        ws.write(row, 51, fss, total_row_format)  
        ws.write(row, 53, "", total_empty_format)                # IBC Parafiscales
        # Total Pensión
        ws.write(row, 54, total_salud, total_row_format) 
        for col in range(55, 57):
            ws.write(row, col, "", total_empty_format)
        # Total Cotización Salud
        ws.write(row, 59, total_arl, total_row_format)           # Total ARL
        ws.write(row, 61, total_ccf, total_row_format)           # Total CCF
        ws.write(row, 63, total_sena, total_row_format)          # Total SENA
        ws.write(row, 65, total_icbf, total_row_format)          # Total ICBF
        
        # Rellenar columnas vacías
        for col in range(38, 85):
            if col not in [65,63,61,59,38, 40, 41, 42, 43, 42,  44, 47, 51, 52, 50, 54]:
                ws.write(row, col, "", total_empty_format)
        
        # Totales generales (últimas columnas)
        ws.write(row, 85, total_general_empleado, total_row_format)
        ws.write(row, 86, total_general_empresa, total_row_format)
        ws.write(row, 87, total_general_linea, total_row_format)

        row += 2
        # -------------------------------------------------------------------------
        # FUNCIÓN PARA GENERAR RESÚMENES DE ENTIDADES - Usando datos locales
        # -------------------------------------------------------------------------
        def write_entity_summary(ws, row, title, headers, entity_dict, without_count, entity_type):
            if entity_type in ['eps','pension']:
                ws.merge_range(row, 0, row, 7, title, section_format)
                row += 1
            elif entity_type in ['arp','ccf']:
                ws.merge_range(row, 0, row, 4, title, section_format)
                row += 1
            else:
                ws.merge_range(row, 0, row, 4, title, section_format)
                row += 1
            for col, header in enumerate(headers):
                ws.write(row, col, header, header_format)
            row += 1

            # Inicializar cálculos de totales
            totals_entity = {'employees': 0, 'value_emp': 0, 'value_comp': 0, 'diff': 0, 'total': 0}
            
            # Procesar los datos según tipo de entidad
            entities_list = []
            
            if entity_type == 'eps':
                for key, data in entity_dict.items():
                    if isinstance(data, dict) and 'name' in data:
                        entity_info = {
                            'name': data.get('name', 'Sin nombre'),
                            'identifcation': data.get('identifcation', 'N/A'),
                            'cod_pila': data.get('cod_pila', 'N/A'),
                            'num_employees': data.get('employees', 0),
                            'value_employees': data.get('value_employees', 0),
                            'value_company': data.get('value_company', 0),
                            'dif_round': data.get('dif_round', 0)
                        }
                        entities_list.append(entity_info)
                        
                        # Actualizar totales
                        totals_entity['employees'] += entity_info['num_employees']
                        totals_entity['value_emp'] += entity_info['value_employees']
                        totals_entity['value_comp'] += entity_info['value_company']
                        totals_entity['diff'] += entity_info.get('dif_round', 0)
            
            elif entity_type == 'pension':
                for key, data in entity_dict.items():
                    if isinstance(data, dict) and 'name' in data:
                        entity_info = {
                            'name': data.get('name', 'Sin nombre'),
                            'identifcation': data.get('identifcation', 'N/A'),
                            'cod_pila': data.get('cod_pila', 'N/A'),
                            'num_employees': data.get('employees', 0),
                            'value_employees': data.get('value_employees', 0),
                            'value_company': data.get('value_company', 0),
                            'dif_round': data.get('dif_round', 0)
                        }
                        entities_list.append(entity_info)
                        
                        # Actualizar totales
                        totals_entity['employees'] += entity_info['num_employees']
                        totals_entity['value_emp'] += entity_info['value_employees']
                        totals_entity['value_comp'] += entity_info['value_company']
                        totals_entity['diff'] += entity_info.get('dif_round', 0)
            
            elif entity_type == 'arp':
                for key, data in entity_dict.items():
                    if isinstance(data, dict) and 'name' in data:
                        entity_info = {
                            'name': data.get('name', 'Sin nombre'),
                            'identifcation': data.get('identifcation', 'N/A'),
                            'cod_pila': data.get('cod_pila', 'N/A'),
                            'num_employees': data.get('employees', 0),
                            'value_arp': data.get('value_arp', 0)
                        }
                        entities_list.append(entity_info)
                        
                        # Actualizar totales
                        totals_entity['employees'] += entity_info['num_employees']
                        totals_entity['value_comp'] += entity_info['value_arp']
            
            elif entity_type == 'ccf':
                for key, data in entity_dict.items():
                    if isinstance(data, dict) and 'name' in data:
                        entity_info = {
                            'name': data.get('name', 'Sin nombre'),
                            'identifcation': data.get('identifcation', 'N/A'),
                            'cod_pila': data.get('cod_pila', 'N/A'),
                            'num_employees': data.get('employees', 0),
                            'value_cajacom': data.get('value_cajacom', 0)
                        }
                        entities_list.append(entity_info)
                        
                        # Actualizar totales
                        totals_entity['employees'] += entity_info['num_employees']
                        totals_entity['value_comp'] += entity_info['value_cajacom']
            
            # Calcular el total
            if entity_type in ['eps', 'pension']:
                totals_entity['total'] = totals_entity['value_emp'] + totals_entity['value_comp'] #+ totals_entity['diff']
            else:
                totals_entity['total'] = totals_entity['value_comp']
            
            # Detectar y destacar empleados sin entidad asignada
            if without_count > 0:
                # Calcular promedios para estimación
                avg_emp = 0
                avg_comp = 0
                if totals_entity['employees'] > 0:
                    if entity_type in ['eps', 'pension']:
                        avg_emp = totals_entity['value_emp'] / totals_entity['employees']
                        avg_comp = totals_entity['value_comp'] / totals_entity['employees']
                    elif entity_type in ['arp', 'ccf']:
                        avg_comp = totals_entity['value_comp'] / totals_entity['employees']
                
                # Estimación de valores
                est_emp_value = round(avg_emp * without_count, 2)
                est_comp_value = round(avg_comp * without_count, 2)
                est_total = est_emp_value + est_comp_value

            for entity in entities_list:
                if entity_type in ['eps', 'pension']:
                    row_values = [
                        entity['name'],
                        entity['identifcation'],
                        entity['cod_pila'],
                        entity['num_employees'],
                        entity['value_employees'],
                        entity['value_company'],
                        entity.get('dif_round', 0),
                        entity['value_employees'] + entity['value_company'] #+ entity.get('dif_round', 0)
                    ]
                else:
                    value_key = 'value_arp' if entity_type == 'arp' else 'value_cajacom'
                    row_values = [
                        entity['name'],
                        entity['identifcation'],
                        entity['cod_pila'],
                        entity['num_employees'],
                        entity[value_key]
                    ]
                
                for col, val in enumerate(row_values):
                    if col == 3:  # Columna de empleados
                        ws.write(row, col, val, number_format)
                    elif col >= 4:  # Columnas de valores
                        ws.write(row, col, val, number_format_decimals)
                    else:  # Columnas de texto
                        ws.write(row, col, val, cell_format)
                row += 1

            # Fila de totales con formato consistente
            if entity_type in ['eps', 'pension']:
                num_cols = 8
                ws.write(row, 0, f'TOTAL {entity_type.upper()}', total_label_format)
                ws.write(row, 3, totals_entity['employees'], total_row_format)
                ws.write(row, 4, totals_entity['value_emp'], total_row_format)
                ws.write(row, 5, totals_entity['value_comp'], total_row_format)
                ws.write(row, 6, totals_entity['diff'], total_row_format)
                ws.write(row, 7, totals_entity['total'], total_row_format)
                # Rellenar celdas vacías
                for col in [1, 2]:
                    ws.write(row, col, "", total_empty_format)
            else:
                # ARP, CCF
                num_cols = 5
                ws.write(row, 0, f'TOTAL {entity_type.upper()}', total_label_format)
                ws.write(row, 3, totals_entity['employees'], total_row_format)
                ws.write(row, 4, totals_entity['value_comp'], total_row_format)
                # Rellenar celdas vacías
                for col in [1, 2]:
                    ws.write(row, col, "", total_empty_format)

            return row + 2
        # -------------------------------------------------------------------------
        # RESÚMENES DE ENTIDADES - Sin usar métodos externos
        # -------------------------------------------------------------------------
        # Encabezados consistentes para todos los informes
        eps_headers = ['Entidad', 'NIT', 'Código', 'Empleados', 'Valor Empleado', 'Valor Empresa', 'Diferencia', 'Total']
        pension_headers = ['Entidad', 'NIT', 'Código', 'Empleados', 'Valor Empleado', 'Valor Empresa', 'Diferencia', 'Total']
        arp_headers = ['Entidad', 'NIT', 'Código', 'Empleados', 'Valor Total']
        ccf_headers = ['Entidad', 'NIT', 'Código', 'Empleados', 'Valor Total']

        # Generar resúmenes de entidades usando los diccionarios ya calculados
        row = write_entity_summary(ws, row, 'RESUMEN EPS', eps_headers, eps_totals, without_eps, 'eps')
        row = write_entity_summary(ws, row, 'RESUMEN PENSIÓN', pension_headers, pension_totals, without_pension, 'pension')
        row = write_entity_summary(ws, row, 'RESUMEN ARL', arp_headers, arp_totals, 0, 'arp')
        row = write_entity_summary(ws, row, 'RESUMEN CCF', ccf_headers, ccf_totals, without_ccf, 'ccf')
        # -------------------------------------------------------------------------
        # RESUMEN PARAFISCAL - Simplificado (SENA e ICBF)
        # -------------------------------------------------------------------------
        ws.merge_range(row, 0, row, 2, 'APORTES PARAFISCALES (SENA e ICBF)', section_format)
        row += 1
        
        # Encabezados simplificados
        parafiscal_headers = ['Entidad', 'Empleados', 'Valor Total']
        for col, header in enumerate(parafiscal_headers):
            ws.write(row, col, header, header_format)
        row += 1

        # Cálculo de totales
        total_sena = sum(item.nValorSENA for item in details)
        total_icbf = sum(item.nValorICBF for item in details)
        employees_count = len({item.employee_id.id for item in details})

        # SENA
        ws.write(row, 0, 'SENA', cell_format)
        ws.write(row, 1, employees_count, number_format)
        ws.write(row, 2, total_sena, number_format_decimals)
        row += 1

        # ICBF
        ws.write(row, 0, 'ICBF', cell_format)
        ws.write(row, 1, employees_count, number_format)
        ws.write(row, 2, total_icbf, number_format_decimals)
        row += 1

        # Total parafiscales
        ws.write(row, 0, 'TOTAL PARAFISCALES', total_label_format)
        ws.write(row, 1, employees_count, total_row_format)
        ws.write(row, 2, total_sena + total_icbf, total_row_format)
        row += 2
        # -------------------------------------------------------------------------
        # RESUMEN CONSOLIDADO - Calculado directamente de los datos recopilados
        # -------------------------------------------------------------------------
        ws.merge_range(row, 0, row, 3, 'RESUMEN CONSOLIDADO', section_format)
        row += 1

        # Encabezados simplificados
        consolidated_headers = ['Concepto', 'Valor Empleado', 'Valor Empresa', 'Total']
        for col, header in enumerate(consolidated_headers):
            ws.write(row, col, header, header_format)
        row += 1

        # Usar los diccionarios que ya hemos calculado anteriormente en lugar de llamar a métodos externos
        # Calcular totales de EPS directamente
        total_eps_emp = 0
        total_eps_comp = 0
        eps_employees = 0
        for key, data in eps_totals.items():
            if isinstance(data, dict) and 'value_employees' in data and 'value_company' in data:
                total_eps_emp += data['value_employees']
                total_eps_comp += data['value_company']
                eps_employees += data.get('employees', 0)

        # Calcular totales de Pensión directamente
        total_pension_emp = 0
        total_pension_comp = 0
        pension_employees = 0
        for key, data in pension_totals.items():
            if isinstance(data, dict) and 'value_employees' in data and 'value_company' in data:
                total_pension_emp += data['value_employees']
                total_pension_comp += data['value_company']
                pension_employees += data.get('employees', 0)

        # Calcular totales de ARP directamente
        total_arp = 0
        arp_employees = 0
        for key, data in arp_totals.items():
            if isinstance(data, dict) and 'value_arp' in data:
                total_arp += data['value_arp']
                arp_employees += data.get('employees', 0)

        # Calcular totales de CCF directamente
        total_ccf = 0
        ccf_employees = 0
        for key, data in ccf_totals.items():
            if isinstance(data, dict) and 'value_cajacom' in data:
                total_ccf += data['value_cajacom']
                ccf_employees += data.get('employees', 0)

        # # Ajustes si hay empleados sin EPS/Pensión/CCF
        # if without_eps > 0 and eps_employees > 0:
        #     avg_emp_eps = total_eps_emp / eps_employees
        #     avg_comp_eps = total_eps_comp / eps_employees
        #     total_eps_emp += avg_emp_eps * without_eps
        #     total_eps_comp += avg_comp_eps * without_eps

        # if without_pension > 0 and pension_employees > 0:
        #     avg_emp_pension = total_pension_emp / pension_employees
        #     avg_comp_pension = total_pension_comp / pension_employees
        #     total_pension_emp += avg_emp_pension * without_pension
        #     total_pension_comp += avg_comp_pension * without_pension

        # if without_ccf > 0 and ccf_employees > 0:
        #     avg_ccf = total_ccf / ccf_employees
        #     total_ccf += avg_ccf * without_ccf

        # Resumen de entidades con formato consistente
        entities_data = [
            ('Salud (EPS)', total_eps_emp, total_eps_comp),
            ('Pensión', total_pension_emp, total_pension_comp),
            ('Riesgos Laborales (ARL)', 0, total_arp),
            ('Caja de Compensación (CCF)', 0, total_ccf),
            ('SENA', 0, total_sena),
            ('ICBF', 0, total_icbf)
        ]

        # Mostrar datos en formato tabular optimizado
        for entity, val_emp, val_comp in entities_data:
            ws.write(row, 0, entity, cell_format)
            ws.write(row, 1, val_emp, number_format_decimals)
            ws.write(row, 2, val_comp, number_format_decimals)
            ws.write(row, 3, val_emp + val_comp, number_format_decimals)
            row += 1

        # Totales generales
        grand_total_employee = total_eps_emp + total_pension_emp
        grand_total_company = (total_eps_comp + total_pension_comp
                        + total_arp + total_ccf
                        + total_sena + total_icbf)
        grand_total = grand_total_employee + grand_total_company

        # Fila de totales
        ws.write(row, 0, 'TOTAL GENERAL', total_label_format)
        ws.write(row, 1, grand_total_employee, total_row_format)
        ws.write(row, 2, grand_total_company, total_row_format)
        ws.write(row, 3, grand_total, total_row_format)
        
        # Rellenar celdas vacías en la fila de totales
        for col in range(4, 10):
            ws.write(row, col, "", total_empty_format)
        
        row += 2
        # -------------------------------------------------------------------------
        # PANEL DE INDICADORES - Simplificado y más visual
        # -------------------------------------------------------------------------
        ws.merge_range(row, 0, row, 10, 'INDICADORES PRINCIPALES', section_format)
        row += 1
        
        # Contenedor para indicadores
        indicator_row_start = row
        indicator_row_height = 3
        
        # KPIs principales
        kpi_data = [
            ('Empleados', totals['total_employees']),
            ('$ Empleados', grand_total_employee),
            ('$ Empresa', grand_total_company),
            ('Total General', grand_total)
        ]
        
        # Formato para KPIs
        kpi_title_format = workbook.add_format({
            'bold': True, 'align': 'center', 'valign': 'vcenter',
            'bg_color': primary_color, 'font_color': 'white',
            'font_name': 'Arial', 'font_size': 11, 'border': 1
        })
        
        kpi_value_format = workbook.add_format({
            'bold': True, 'align': 'center', 'valign': 'vcenter',
            'bg_color': header_bg, 'font_color': primary_color,
            'font_name': 'Arial', 'font_size': 12, 'border': 1,
            'num_format': '#,##0.00'
        })

        # Distribución de KPIs en filas
        col_offset = 0
        for title, value in kpi_data:
            col_width = 2  # Cada KPI ocupa 2 columnas
            
            # Título del KPI
            ws.merge_range(row, col_offset, row, col_offset + col_width - 1, title, kpi_title_format)
            
            # Valor del KPI
            ws.merge_range(row + 1, col_offset, row + 1, col_offset + col_width - 1, value, kpi_value_format)
            
            col_offset += col_width + 1  # Espacio entre KPIs
        
        row += 3  # Avanzar después de los KPIs
        
        # Alertas de entidades faltantes
        alert_data = [
            ('Sin Pensión', without_pension),
            ('Sin EPS', without_eps),
            ('Sin CCF', without_ccf),
            ('Total Novedades', total_ingresos_unique + total_retiros_unique + 
            total_vacaciones_unique + total_licencias_unique + total_incapacidades_unique)
        ]

        alert_title_format = workbook.add_format({
            'bold': True, 'align': 'center', 'valign': 'vcenter',
            'bg_color': secondary_color, 'font_color': 'white',
            'font_name': 'Arial', 'font_size': 11, 'border': 1
        })
        
        alert_value_format = workbook.add_format({
            'bold': True, 'align': 'center', 'valign': 'vcenter',
            'bg_color': header_bg, 'font_color': primary_color,
            'font_name': 'Arial', 'font_size': 12, 'border': 1
        })
        
        alert_warning_format = workbook.add_format({
            'bold': True, 'align': 'center', 'valign': 'vcenter',
            'bg_color': alert_color, 'font_color': 'white',
            'font_name': 'Arial', 'font_size': 12, 'border': 1
        })

        # Mostrar alertas
        col_offset = 0
        for title, value in alert_data:
            col_width = 2  # Cada alerta ocupa 2 columnas
            
            # Título de la alerta
            ws.merge_range(row, col_offset, row, col_offset + col_width - 1, title, alert_title_format)
            
            # Valor con formato según contenido
            format_to_use = alert_warning_format if value > 0 and title.startswith('Sin') else alert_value_format
            ws.merge_range(row + 1, col_offset, row + 1, col_offset + col_width - 1, value, format_to_use)
            
            col_offset += col_width + 1  # Espacio entre alertas
        
        row += 4  # Avanzar después de las alertas
        # -------------------------------------------------------------------------
        # RESUMEN DE FECHAS DE FINALIZACIÓN - Simplificado
        # -------------------------------------------------------------------------
        ws.merge_range(row, 0, row, 3, 'FECHAS DE FINALIZACIÓN DE NOVEDADES', section_format)
        row += 1
        
        # Encabezados
        ws.write(row, 0, 'Tipo de Novedad', header_format)
        ws.write(row, 1, 'Empleados', header_format)
        ws.write(row, 2, 'Observación', header_format)
        row += 1

        # Datos de novedades
        novedad_data = [
            ('Fecha fin SLN', sum(1 for item in details if item.dFechaFinSLN), 'Licencias No Remuneradas'),
            ('Fecha fin IGE', sum(1 for item in details if item.dFechaFinIGE), 'Incapacidades por Enfermedad General'),
            ('Fecha fin LMA', sum(1 for item in details if item.dFechaFinLMA), 'Licencias de Maternidad/Paternidad'),
            ('Fecha fin VAC - LR', sum(1 for item in details if item.dFechaFinVACLR), 'Vacaciones o Licencias Remuneradas'),
            ('Fecha fin VCT', sum(1 for item in details if item.dFechaFinVCT), 'Variación Centros de Trabajo'),
            ('Fecha fin IRL', sum(1 for item in details if item.dFechaFinIRL), 'Incapacidades por Riesgos Laborales')
        ]

        # Mostrar novedades
        for novedad, count, obs in novedad_data:
            ws.write(row, 0, novedad, cell_format)
            ws.write(row, 1, count, number_format)
            ws.write(row, 2, obs, cell_format)
            row += 1

        # Total de novedades
        total_novedades_fin = sum(count for _, count, _ in novedad_data)
        ws.write(row, 0, 'TOTAL NOVEDADES FINALIZADAS', total_label_format)
        ws.write(row, 1, total_novedades_fin, total_row_format)
        
        # Rellenar celdas vacías
        for col in range(2, 3):
            ws.write(row, col, "", total_empty_format)
        # -------------------------------------------------------------------------
        # FINALIZACIÓN DEL DOCUMENTO
        # -------------------------------------------------------------------------
        # Pie de página con información de generación
        footer_text = f"Generado el {datetime.now().strftime('%d/%m/%Y %H:%M:%S')} - {self.company_id.name}"
        ws.set_footer(f"&L{footer_text}&R&P de &N")

        # Ajuste automático de columnas
        auto_adjust_columns(ws, detail_data_rows)

        # Cerrar y devolver el workbook
        workbook.close()
        excel_content = output.getvalue()
        output.close()

        # Nombre del archivo
        filename = f'PlanillaSS_{self.year}_{self.month}'
        if self.presentation_form != 'U':
            if self.work_center_social_security_id:
                filename += f'_{self.branch_social_security_id.name}_{self.work_center_social_security_id.name}'
            else:
                filename += f'_{self.branch_social_security_id.name}'
        filename += '.xlsx'

        # Guardar el archivo en el registro
        self.write({
            'excel_file': base64.b64encode(excel_content),
            'excel_file_name': filename,
        })

        # Devolver acción para descargar el archivo
        return {
            'name': 'Planilla Seguridad Social',
            'type': 'ir.actions.act_url',
            'url': f"web/content/?model=hr.payroll.social.security&id={self.id}&filename_field=excel_file_name&field=excel_file&download=true&filename={self.excel_file_name}",
            'target': 'self',
        }
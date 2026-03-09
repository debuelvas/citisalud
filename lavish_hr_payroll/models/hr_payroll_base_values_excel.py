from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from datetime import datetime, timedelta,date
from dateutil.relativedelta import relativedelta
import json
import base64
import io
import xlsxwriter
from odoo.tools import get_lang

class Hr_payslip(models.Model):
    _inherit = 'hr.payslip'

    excel_value_base_file = fields.Binary('Excel Valores base file')
    excel_value_base_file_name = fields.Char('Excel Valores base filename')
    excel_lines = fields.Binary('Excel líneas de recibo de nómina')
    excel_lines_filename = fields.Char('Excel líneas de recibo de nómina filename')

    def get_query(self,process,date_start,date_end):
        # formatear fechas
        date_start = str(date_start.year) + '-' + str(date_start.month) + '-' + str(date_start.day)
        date_end = str(date_end.year) + '-' + str(date_end.month) + '-' + str(date_end.day)
        lang = self.env.user.lang or get_lang(self.env).code
        query = """Select * from (
                    Select COALESCE(hc.name::jsonb ->>  '%s', hc.name::jsonb ->> 'en_US', ''),hp.date_from,COALESCE(sum(pl.total),0) as accumulated, 
                        case when hp.id = %s then 'Liquidación Actual' else 'Liquidaciones' end as origin  
                        From hr_payslip as hp 
                        Inner Join hr_payslip_line as pl on  hp.id = pl.slip_id 
                        Inner Join hr_salary_rule hc on pl.salary_rule_id = hc.id and hc.%s = true
                        Inner Join hr_salary_rule_category hsc on hc.category_id = hsc.id and hsc.code != 'BASIC'
                        WHERE (hp.state = 'done' and hp.contract_id = %s
                                AND (hp.date_from between '%s' and '%s'
                                    or
                                    hp.date_to between '%s' and '%s' )) or hp.id = %s
                        group by COALESCE(hc.name::jsonb ->>  '%s', hc.name::jsonb ->> 'en_US', ''),hp.date_from,hp.id
                    Union 
                    Select COALESCE(hc.name::jsonb ->>  '%s', hc.name::jsonb ->> 'en_US', ''),pl.date,COALESCE(sum(pl.amount),0) as accumulated, 'Acumulados' as origin
                        From hr_accumulated_payroll as pl
                        Inner Join hr_salary_rule hc on pl.salary_rule_id = hc.id and hc.%s = true
                        Inner Join hr_salary_rule_category hsc on hc.category_id = hsc.id and hsc.code != 'BASIC'
                        WHERE pl.employee_id = %s and pl.date between '%s' and '%s'
                        group by COALESCE(hc.name::jsonb ->>  '%s', hc.name::jsonb ->> 'en_US', ''),pl.date) as a order by a.date_from
                """ % (lang,
                        self.id, process, self.contract_id.id, date_start, date_end, date_start, date_end, self.id,lang, lang, process, self.employee_id.id, date_start,
        date_end, lang) 

        return query

    def base_values_export_excel(self):
        query_vacaciones = ''
        query_vacaciones_dinero = ''
        query_prima = ''
        query_cesantias = ''

        if self.struct_id.process == 'vacaciones':
            date_start = self.date_from - relativedelta(years=1)
            date_start = self.contract_id.date_start if date_start <= self.contract_id.date_start else date_start
            date_end = self.date_from
            query_vacaciones = self.get_query('base_vacaciones',date_start,date_end)
            query_vacaciones_dinero = self.get_query('base_vacaciones_dinero', date_start, date_end)
        elif self.struct_id.process == 'prima':
            date_start = self.date_prima or self.date_from
            date_start = self.contract_id.date_start if date_start <= self.contract_id.date_start else date_start
            date_end = self.date_to
            query_prima = self.get_query('base_prima', date_start, date_end)
        elif self.struct_id.process == 'cesantias' or self.struct_id.process == 'intereses_cesantias':
            date_start = self.date_cesantias or self.date_from
            date_start = self.contract_id.date_start if date_start <= self.contract_id.date_start else date_start
            date_end = self.date_to
            query_cesantias = self.get_query('base_cesantias', date_start, date_end)
        elif self.struct_id.process == 'contrato' or self.struct_id.process == 'nomina':
            date_start = self.date_liquidacion - relativedelta(years=1) or self.date_from
            date_end = self.date_liquidacion or self.date_to
            query_vacaciones_dinero = self.get_query('base_vacaciones_dinero', date_start, date_end)
            date_start = self.date_prima or self.date_from
            date_end = self.date_liquidacion or self.date_to
            query_prima = self.get_query('base_prima', date_start, date_end)
            date_start = self.date_cesantias or self.date_from
            date_end = self.date_liquidacion or self.date_to
            query_cesantias = self.get_query('base_cesantias', date_start, date_end)
        else:
            raise ValidationError(_('Esta estructura salarial no posee exportación de valores base a excel.'))

        #Generar EXCEL
        filename = f'Acumulados valores variables - {self.employee_id.name}.xlsx'
        stream = io.BytesIO()
        book = xlsxwriter.Workbook(stream, {'in_memory': True})
        date_format = book.add_format({'num_format': 'dd/mm/yyyy'})

        if query_vacaciones != '':
            columns = ['Regla Salarial', 'Fecha', 'Valor', 'Origen']
            sheet_vacaciones = book.add_worksheet('VACACIONES DISFRUTADAS')
            # Agregar columnas
            aument_columns = 0
            for column in columns:
                sheet_vacaciones.write(0, aument_columns, column)
                aument_columns = aument_columns + 1

            #Agregar Información generada en la consulta
            self._cr.execute(query_vacaciones)
            result_query = self._cr.dictfetchall()
            aument_columns = 0
            aument_rows = 1
            for query in result_query:
                for column, row in query.items():
                    width = len(str(row)) + 10
                    if isinstance(row, date):  # Check if the value is a date
                        sheet_vacaciones.write_datetime(aument_rows, aument_columns, row, date_format)
                    else:
                        sheet_vacaciones.write(aument_rows, aument_columns, row)
                    sheet_vacaciones.set_column(aument_columns, aument_columns, width)
                    aument_columns += 1
                aument_rows += 1
                aument_columns = 0
            # Convertir en tabla
            array_header_table = []
            aument_rows = 2 if aument_rows == 1 else aument_rows
            for i in columns:
                dict = {'header': i}
                array_header_table.append(dict)
            sheet_vacaciones.add_table(0, 0, aument_rows - 1, len(columns) - 1,
                                              {'style': 'Table Style Medium 2', 'columns': array_header_table})
        if query_vacaciones_dinero != '':
            columns = ['Regla Salarial', 'Fecha', 'Valor', 'Origen']
            sheet_vacaciones_dinero = book.add_worksheet('VACACIONES REMUNERADAS')
            # Agregar columnas
            aument_columns = 0
            for column in columns:
                sheet_vacaciones_dinero.write(0, aument_columns, column)
                aument_columns = aument_columns + 1

            #Agregar Información generada en la consulta
            self._cr.execute(query_vacaciones_dinero)
            result_query = self._cr.dictfetchall()
            aument_columns = 0
            aument_rows = 1
            for query in result_query:
                for column, row in query.items():
                    width = len(str(row)) + 10
                    if isinstance(row, date):
                        sheet_vacaciones_dinero.write_datetime(aument_rows, aument_columns, row, date_format)
                    else:
                        sheet_vacaciones_dinero.write(aument_rows, aument_columns, row)
                    sheet_vacaciones_dinero.set_column(aument_columns, aument_columns, width)
                    aument_columns += 1
                aument_rows += 1
                aument_columns = 0
            # Convertir en tabla
            array_header_table = []
            aument_rows = 2 if aument_rows == 1 else aument_rows
            for i in columns:
                dict = {'header': i}
                array_header_table.append(dict)
            sheet_vacaciones_dinero.add_table(0, 0, aument_rows - 1, len(columns) - 1,
                                  {'style': 'Table Style Medium 2', 'columns': array_header_table})
        if query_prima != '':
            columns = ['Regla Salarial', 'Fecha', 'Valor', 'Origen']
            sheet_prima = book.add_worksheet('PRIMA')
            # Agregar columnas
            aument_columns = 0
            for column in columns:
                sheet_prima.write(0, aument_columns, column)
                aument_columns = aument_columns + 1

            #Agregar Información generada en la consulta
            self._cr.execute(query_prima)
            result_query = self._cr.dictfetchall()
            aument_columns = 0
            aument_rows = 1
            for query in result_query:
                for column, row in query.items():
                    width = len(str(row)) + 10
                    if isinstance(row, date):
                        sheet_prima.write_datetime(aument_rows, aument_columns, row, date_format)
                    else:
                        sheet_prima.write(aument_rows, aument_columns, row)
                    sheet_prima.set_column(aument_columns, aument_columns, width)
                    aument_columns += 1
                aument_rows += 1
                aument_columns = 0
            # Convertir en tabla
            array_header_table = []
            aument_rows = 2 if aument_rows == 1 else aument_rows
            for i in columns:
                dict = {'header': i}
                array_header_table.append(dict)
            sheet_prima.add_table(0, 0, aument_rows - 1, len(columns) - 1,
                                      {'style': 'Table Style Medium 2', 'columns': array_header_table})
        if query_cesantias != '':
            columns = ['Regla Salarial', 'Fecha', 'Valor', 'Origen']
            sheet_cesantias = book.add_worksheet('CESANTIAS')
            # Agregar columnas
            aument_columns = 0
            for column in columns:
                sheet_cesantias.write(0, aument_columns, column)
                aument_columns = aument_columns + 1

            #Agregar Información generada en la consulta
            self._cr.execute(query_cesantias)
            result_query = self._cr.dictfetchall()
            aument_columns = 0
            aument_rows = 1
            for query in result_query:
                for column, row in query.items():
                    width = len(str(row)) + 10
                    if isinstance(row, date):
                        sheet_cesantias.write_datetime(aument_rows, aument_columns, row, date_format)
                    else:
                        sheet_cesantias.write(aument_rows, aument_columns, row)
                    sheet_cesantias.set_column(aument_columns, aument_columns, width)
                    aument_columns += 1
                aument_rows += 1
                aument_columns = 0
            # Convertir en tabla
            array_header_table = []
            aument_rows = 2 if aument_rows == 1 else aument_rows
            for i in columns:
                dict = {'header': i}
                array_header_table.append(dict)
            sheet_cesantias.add_table(0, 0, aument_rows - 1, len(columns) - 1,
                            {'style': 'Table Style Medium 2', 'columns': array_header_table})
        book.close()
        self.write({
            'excel_value_base_file': base64.b64encode(stream.getvalue()).decode('utf-8'),
            'excel_value_base_file_name': filename,
        })

        action = {
            'name': 'Export Acumulados variables',
            'type': 'ir.actions.act_url',
            'url': "web/content/?model=hr.payslip&id=" + str(
                self.id) + "&filename_field=excel_value_base_file_name&field=excel_value_base_file&download=true&filename=" + self.excel_value_base_file_name,
            'target': 'self',
        }
        return action

    def get_excel_lines(self):
        # Generar EXCEL
        filename = f'Líneas de recibo de nómina - {self.display_name}.xlsx'
        stream = io.BytesIO()
        book = xlsxwriter.Workbook(stream, {'in_memory': True})
        date_format = book.add_format({'num_format': 'dd/mm/yyyy'})
        number_format = book.add_format({'num_format': '#,##'})

        columns = ['Nombre', 'Categoría', 'Cantidad', 'C. Inicio', 'C. Fin', 'Base', 'Entidad', 'Prestamo', 'Regla',
                   'Importe', 'Total']

        sheet = book.add_worksheet('Líneas')
        # Agregar columnas
        aument_columns = 0
        for column in columns:
            sheet.write(0, aument_columns, column)
            aument_columns = aument_columns + 1

        # Agregar Información
        aument_rows = 1
        for line in self.line_ids:
            sheet.write(aument_rows, 0, line.name)
            sheet.write(aument_rows, 1, line.category_id.display_name)
            sheet.write(aument_rows, 2, line.quantity,number_format)
            if line.initial_accrual_date:
                sheet.write_datetime(aument_rows, 3, line.initial_accrual_date, date_format)
            else:
                sheet.write(aument_rows, 3, '')
            if line.final_accrual_date:
                sheet.write_datetime(aument_rows, 4, line.final_accrual_date, date_format)
            else:
                sheet.write(aument_rows, 4, '')
            sheet.write(aument_rows, 5, line.amount_base,number_format)
            if line.entity_id:
                sheet.write(aument_rows, 6, line.entity_id.display_name)
            else:
                sheet.write(aument_rows, 6, '')
            if line.loan_id:
                sheet.write(aument_rows, 7, line.loan_id.display_name)
            else:
                sheet.write(aument_rows, 7, '')
            sheet.write(aument_rows, 8, line.salary_rule_id.display_name)
            sheet.write(aument_rows, 9, line.amount,number_format)
            sheet.write(aument_rows, 10, line.total,number_format)
            aument_rows = aument_rows + 1
        # Tamaño columnas
        sheet.set_column('A:B', 30)
        sheet.set_column('C:C', 10)
        sheet.set_column('D:F', 15)
        sheet.set_column('G:I', 30)
        sheet.set_column('J:K', 15)
        # Convertir en tabla
        array_header_table = []
        aument_rows = 2 if aument_rows == 1 else aument_rows
        for i in columns:
            dict = {'header': i}
            array_header_table.append(dict)
        sheet.add_table(0, 0, aument_rows - 1, len(columns) - 1,
                                   {'style': 'Table Style Medium 2', 'columns': array_header_table})

        book.close()
        self.write({
            'excel_lines': base64.encodebytes(stream.getvalue()),
            'excel_lines_filename': filename,
        })

        action = {
            'name': 'Export Excel líneas de recibo de nómina',
            'type': 'ir.actions.act_url',
            'url': "web/content/?model=hr.payslip&id=" + str(
                self.id) + "&filename_field=excel_lines_filename&field=excel_lines&download=true&filename=" + self.excel_lines_filename,
            'target': 'self',
        }
        return action


    def action_exportar_excel_retencion(self):
    
        self.ensure_one()
        linea_retencion = False
        for rec in self.line_ids.filtered(lambda l: l.code == 'RT_MET_01'):
            linea_retencion = rec
            break
        if not linea_retencion or not linea_retencion.computation:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Advertencia'),
                    'message': _('No hay datos de retención para exportar.'),
                    'sticky': False,
                    'type': 'warning',
                }
            }
        
        log_data = linea_retencion.computation
        if isinstance(log_data, str):
            try:
                log_data = json.loads(log_data)
            except:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Error'),
                        'message': _('El formato de los datos de retención no es válido.'),
                        'sticky': False,
                        'type': 'danger',
                    }
                }
        
        company = self.company_id
        company_info = {
            'name': company.name,
            'vat': company.vat or '',
            'street': company.street or '',
            'phone': company.phone or '',
            'email': company.email or '',
        }
        payslip_info = {
            'employee_name': self.employee_id.name,
            'employee_identification': self.employee_id.identification_id or '',
            'number': self.number or '',
            'date': self.date_to.strftime('%d/%m/%Y') if self.date_to else '',
            'date_from': self.date_from.strftime('%d/%m/%Y') if self.date_from else '',
            'date_to': self.date_to.strftime('%d/%m/%Y') if self.date_to else '',
        }
        excel_base64 = self._generar_excel_retencion(
            log_data, 
            company_info=company_info,
            payslip_info=payslip_info
        )
        if not excel_base64:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Error'),
                    'message': _('No se pudo generar el Excel.'),
                    'sticky': False,
                    'type': 'danger',
                }
            }
        filename = f'retencion_{self.employee_id.name}_{self.date_to.strftime("%Y%m%d")}.xlsx'
        self.write({
            'excel_lines': excel_base64,
            'excel_lines_filename': filename
        })
        action = {
            'name': 'Export Excel Retención en la Fuente',
            'type': 'ir.actions.act_url',
            'url': "web/content/?model=hr.payslip&id=" + str(
                self.id) + "&filename_field=excel_lines_filename&field=excel_lines&download=true&filename=" + self.excel_lines_filename,
            'target': 'self',
        }
        
        return action
            

    def generate_prestaciones_excel(self):
        for payslip in self:
            prestaciones_lines = payslip.line_ids.filtered(
                lambda line: line.computation and line.salary_rule_id.code not in ('IBD', 'IBC_R', 'RT_MET_01')
            )
            
            if not prestaciones_lines:
                raise UserError('No hay datos de prestaciones sociales disponibles para generar el reporte Excel.')
            
            valid_lines = []
            for line in prestaciones_lines:
                try:
                    json.loads(line.computation)
                    valid_lines.append(line)
                except json.JSONDecodeError:
                    continue
            
            if not valid_lines:
                raise UserError('No se encontraron líneas con datos JSON válidos para generar el reporte.')
            
            file_data = self._create_prestaciones_excel(valid_lines)
            
            payslip.write({
                'excel_lines': file_data,
                'excel_lines_filename':  f'prestaciones_{payslip.number}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
            })
            action = {
                'name': 'Export  prestaciones socialeen la Fuente',
                'type': 'ir.actions.act_url',
                'url': "web/content/?model=hr.payslip&id=" + str(
                    self.id) + "&filename_field=excel_lines_filename&field=excel_lines&download=true&filename=" + self.excel_lines_filename,
                'target': 'self',
            }
            
            return action

    def _generar_excel_retencion(self, log_data, company_info=None, payslip_info=None):
        """
        Genera un reporte Excel para la retención en la fuente.
        
        El cálculo se basa en el artículo 383 del Estatuto Tributario,
        modificado por el artículo 42 de la Ley 2010 de 2019.
        
        Args:
            log_data: Datos de cálculo de retención
            company_info: Información de la empresa
            payslip_info: Información de la nómina
            
        Returns:
            Excel codificado en base64
        """
        # Normalizar los datos de entrada
        if isinstance(log_data, list):
            data = log_data[0] if log_data else {}
        else:
            data = log_data
            
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output)
        worksheet = workbook.add_worksheet('Retención en la Fuente')
        
        # Definición de colores y formatos
        azul_oscuro = '#0A3D62'  
        azul_claro = '#2980B9' 
        gris_claro = '#F5F5F5'
        verde_claro = '#d1e7dd'  # Color verde suave para valores proyectados
        naranja_claro = '#fff3cd'  # Color naranja suave para advertencias
        
        titulo_formato = workbook.add_format({
            'font_name': 'Arial', 'font_size': 14, 'bold': True, 
            'font_color': 'white', 'bg_color': azul_oscuro, 
            'align': 'center', 'valign': 'vcenter'
        })
        subtitulo_formato = workbook.add_format({
            'font_name': 'Arial', 'font_size': 12, 'bold': True, 
            'font_color': 'white', 'bg_color': azul_oscuro, 
            'align': 'left', 'valign': 'vcenter'
        })
        texto_normal = workbook.add_format({
            'font_name': 'Arial', 'font_size': 10, 
            'align': 'left', 'valign': 'vcenter', 'border': 1
        })
        texto_normal_alt = workbook.add_format({
            'font_name': 'Arial', 'font_size': 10, 
            'align': 'left', 'valign': 'vcenter', 'border': 1,
            'bg_color': gris_claro
        })
        texto_bold = workbook.add_format({
            'font_name': 'Arial', 'font_size': 10, 'bold': True, 
            'align': 'right', 'valign': 'vcenter', 'border': 1
        })
        texto_bold_alt = workbook.add_format({
            'font_name': 'Arial', 'font_size': 10, 'bold': True, 
            'align': 'right', 'valign': 'vcenter', 'border': 1,
            'bg_color': gris_claro
        })
        retención_formato = workbook.add_format({
            'font_name': 'Arial', 'font_size': 10, 'bold': True, 
            'align': 'right', 'valign': 'vcenter', 'border': 1,
            'bg_color': azul_claro, 'font_color': 'white'
        })
        
        # Nuevos formatos para proyección
        proyeccion_titulo = workbook.add_format({
            'font_name': 'Arial', 'font_size': 12, 'bold': True, 
            'font_color': 'white', 'bg_color': '#28a745',  # Verde oscuro
            'align': 'left', 'valign': 'vcenter'
        })
        
        texto_proyectado = workbook.add_format({
            'font_name': 'Arial', 'font_size': 10, 'bold': True, 
            'align': 'right', 'valign': 'vcenter', 'border': 1,
            'bg_color': verde_claro, 'font_color': '#0f5132'  # Verde oscuro
        })
        
        header_format = workbook.add_format({
            'font_name': 'Arial', 'font_size': 11, 'bold': True, 
            'bg_color': '#F2F2F2', 'border': 1, 
            'align': 'right', 'valign': 'vcenter'
        })
        
        data_format = workbook.add_format({
            'font_name': 'Arial', 'font_size': 11, 
            'bg_color': '#F2F2F2', 'border': 1, 
            'align': 'left', 'valign': 'vcenter'
        })
        
        nota_formato = workbook.add_format({
            'font_name': 'Arial', 'font_size': 9, 
            'font_color': '#0A3D62', 'align': 'center', 'valign': 'vcenter'
        })
        
        alerta_formato = workbook.add_format({
            'font_name': 'Arial', 'font_size': 10, 
            'bg_color': naranja_claro, 'border': 1, 
            'align': 'left', 'valign': 'vcenter', 'text_wrap': True
        })
        
        referencia_legal_formato = workbook.add_format({
            'font_name': 'Arial', 'font_size': 9, 'italic': True,
            'font_color': '#666666', 'align': 'left', 'valign': 'vcenter',
        })
        
        encabezado_proyeccion = workbook.add_format({
            'font_name': 'Arial', 'font_size': 10, 'bold': True, 
            'align': 'center', 'valign': 'vcenter', 'border': 1,
            'bg_color': azul_oscuro, 'font_color': 'white'
        })
        
        # Configuración de columnas
        worksheet.set_column('A:A', 5)
        worksheet.set_column('B:B', 40)
        worksheet.set_column('C:C', 15)
        worksheet.set_column('D:D', 15)
        worksheet.set_column('E:E', 15)
        worksheet.set_column('F:F', 15)  # Para proyección
        
        fila_actual = 0
        
        # Información de empresa
        if company_info:
            worksheet.merge_range(fila_actual, 1, fila_actual, 4, company_info.get('name', 'EMPRESA'), workbook.add_format({
                'font_name': 'Arial', 'font_size': 14, 'bold': True, 
                'align': 'center', 'valign': 'vcenter'
            }))
            fila_actual += 1
            worksheet.write(fila_actual, 1, "NIT:", header_format)
            worksheet.write(fila_actual, 2, company_info.get('vat', ''), data_format)
            worksheet.write(fila_actual, 3, "Dirección:", header_format)
            worksheet.write(fila_actual, 4, company_info.get('street', ''), data_format)
            fila_actual += 1
            worksheet.write(fila_actual, 1, "Teléfono:", header_format)
            worksheet.write(fila_actual, 2, company_info.get('phone', ''), data_format)
            worksheet.write(fila_actual, 3, "Email:", header_format)
            worksheet.write(fila_actual, 4, company_info.get('email', ''), data_format)
            fila_actual += 1
        
        # Información del empleado/nómina
        if payslip_info:
            worksheet.write(fila_actual, 1, "Empleado:", header_format)
            worksheet.write(fila_actual, 2, payslip_info.get('employee_name', ''), data_format)
            worksheet.write(fila_actual, 3, "Documento:", header_format)
            worksheet.write(fila_actual, 4, payslip_info.get('employee_identification', ''), data_format)
            fila_actual += 1
            worksheet.write(fila_actual, 1, "Nómina No.:", header_format)
            worksheet.write(fila_actual, 2, payslip_info.get('number', ''), data_format)
            worksheet.write(fila_actual, 3, "Fecha:", header_format)
            worksheet.write(fila_actual, 4, payslip_info.get('date', ''), data_format)
            fila_actual += 1
            worksheet.write(fila_actual, 1, "Periodo:", header_format)
            periodo = f"{payslip_info.get('date_from', '')} - {payslip_info.get('date_to', '')}"
            worksheet.merge_range(fila_actual, 2, fila_actual, 4, periodo, data_format)
            fila_actual += 2
        
        # Título principal
        worksheet.merge_range(fila_actual, 1, fila_actual, 4, "RETENCIÓN EN LA FUENTE MENSUAL", titulo_formato)
        fila_actual += 1
        
        # Referencia legal
        worksheet.merge_range(fila_actual, 1, fila_actual, 4, 
                        "Cálculo según Art. 383 del E.T., modificado por Art. 42 de la Ley 2010 de 2019", 
                        referencia_legal_formato)
        fila_actual += 1
        
        # Valor UVT
        worksheet.merge_range(fila_actual, 1, fila_actual, 2, "Valor UVT:", workbook.add_format({
            'font_name': 'Arial', 'font_size': 10, 'bold': True, 
            'align': 'left', 'valign': 'vcenter'
        }))
        worksheet.merge_range(fila_actual, 3, fila_actual, 4, f"${data.get('uvt', 0):,.0f}", workbook.add_format({
            'font_name': 'Arial', 'font_size': 10, 'bold': True, 
            'align': 'right', 'valign': 'vcenter'
        }))
        fila_actual += 2
        
        # Verificar tipo de cálculo (fijo o normal)
        if data.get("tipo") == "monto_fijo":
            valor_fijo = data.get("valor", 0)
            
            # Sección de valor fijo con alerta
            worksheet.merge_range(fila_actual, 1, fila_actual, 4, "VALOR FIJO DE RETENCIÓN", subtitulo_formato)
            fila_actual += 1
            
            worksheet.merge_range(fila_actual, 1, fila_actual + 1, 4, 
                            "ADVERTENCIA: Se está aplicando un valor fijo de retención establecido por el usuario. "
                            "Este valor no se calcula según el procedimiento estándar.", 
                            alerta_formato)
            fila_actual += 3
            
            worksheet.merge_range(fila_actual, 1, fila_actual, 2, "Valor de retención fijo:", texto_bold)
            valor_fijo_formato = workbook.add_format({
                'font_name': 'Arial', 'font_size': 12, 'bold': True, 
                'bg_color': verde_claro, 'color': '#0f5132',
                'align': 'right', 'valign': 'vcenter', 'border': 1
            })
            worksheet.merge_range(fila_actual, 3, fila_actual, 4, f"${valor_fijo:,.2f}", valor_fijo_formato)
            
        elif data.get("tipo") == "extranjero_no_residente":
            # Sección para extranjero no residente
            worksheet.merge_range(fila_actual, 1, fila_actual, 4, "RETENCIÓN PARA EXTRANJERO NO RESIDENTE", subtitulo_formato)
            fila_actual += 1
            
            worksheet.merge_range(fila_actual, 1, fila_actual + 1, 4, 
                        "Se aplica una tarifa única del 20% sobre la totalidad de pagos laborales según Artículo 408 del Estatuto Tributario.",
                        alerta_formato)
            fila_actual += 3
            
            worksheet.merge_range(fila_actual, 1, fila_actual, 2, "Total ingresos:", texto_bold)
            worksheet.merge_range(fila_actual, 3, fila_actual, 4, f"${data.get('total_ingresos', 0):,.2f}", texto_bold)
            fila_actual += 1
            
            worksheet.merge_range(fila_actual, 1, fila_actual, 2, "Tarifa aplicable:", texto_bold)
            worksheet.merge_range(fila_actual, 3, fila_actual, 4, "20%", texto_bold)
            fila_actual += 1
            
            worksheet.merge_range(fila_actual, 1, fila_actual, 2, "Retención a aplicar:", texto_bold)
            worksheet.merge_range(fila_actual, 3, fila_actual, 4, f"${data.get('retencion', 0):,.2f}", retención_formato)
            
        else:
            # SECCIÓN DE PROYECCIÓN (solo si es cálculo normal y tiene proyección)
            es_proyectado = data.get('es_proyectado', False)
            
            if es_proyectado:
                worksheet.merge_range(fila_actual, 1, fila_actual, 4, "INFORMACIÓN DE PROYECCIÓN", proyeccion_titulo)
                fila_actual += 1
                
                worksheet.merge_range(fila_actual, 1, fila_actual + 1, 4, 
                                "NOTA: Los valores han sido proyectados para el cálculo de la retención.\n"
                                "A continuación se muestran los valores originales y proyectados para comparación.\n"
                                "El resultado final se divide por 2 ya que solo aplica para esta quincena.",
                                alerta_formato)
                fila_actual += 3
                
                # Encabezados de tabla de proyección
                worksheet.write(fila_actual, 1, "Concepto", encabezado_proyeccion)
                worksheet.write(fila_actual, 2, "Valor Base", encabezado_proyeccion)
                worksheet.write(fila_actual, 3, "Valor Proyectado", encabezado_proyeccion)
                worksheet.write(fila_actual, 4, "Diferencia", encabezado_proyeccion)
                fila_actual += 1
                
                # Calcular formato alternado para filas
                def formato_alt(idx, normal, alt):
                    return alt if idx % 2 else normal
                
                # Valores de ingresos sin proyectar vs proyectados
                valores_sin_proyectar = data.get('valores_sin_proyectar', {})
                
                # Factor de proyección
                factor_idx = 0
                worksheet.write(fila_actual, 1, "Factor de proyección", formato_alt(factor_idx, texto_normal, texto_normal_alt))
                factor = 0
                for paso in data.get('pasos', []):
                    if isinstance(paso, dict) and paso.get('descripcion') == 'Factor de proyección':
                        factor = paso.get('valor', 0)
                        break
                worksheet.write(fila_actual, 2, f"{factor:.2f}", formato_alt(factor_idx, texto_bold, texto_bold_alt))
                worksheet.merge_range(fila_actual, 3, fila_actual, 4, "Se aplica este factor a los valores base", formato_alt(factor_idx, texto_normal, texto_normal_alt))
                fila_actual += 1
                
                # Días
                dias_idx = 1
                dias_trabajados = data.get('dias_trabajados', 0)
                worksheet.write(fila_actual, 1, "Días trabajados", formato_alt(dias_idx, texto_normal, texto_normal_alt))
                worksheet.write(fila_actual, 2, f"{dias_trabajados}", formato_alt(dias_idx, texto_bold, texto_bold_alt))
                worksheet.write(fila_actual, 3, f"{30}", formato_alt(dias_idx, texto_proyectado, texto_proyectado))
                worksheet.write(fila_actual, 4, f"{30 - dias_trabajados}", formato_alt(dias_idx, texto_bold, texto_bold_alt))
                fila_actual += 1
                
                # Ingresos proyectados
                conceptos_ingresos = [
                    ("Salario básico", "basic", "salario"),
                    ("Comisiones", "comisiones", "comisiones"),
                    ("Devengos salariales", "dev_salarial", "dev_salarial"),
                    ("Devengos no salariales", "dev_no_salarial", "dev_no_salarial"),
                    ("Total ingresos", "total_ing_base", "total_ing_base")
                ]
                
                for idx, (concepto, key_base, key_proy) in enumerate(conceptos_ingresos, 2):
                    valor_base = valores_sin_proyectar.get(key_base, 0)
                    valor_proyectado = data.get(key_proy, 0)
                    diferencia = valor_proyectado - valor_base
                    
                    worksheet.write(fila_actual, 1, concepto, formato_alt(idx, texto_normal, texto_normal_alt))
                    worksheet.write(fila_actual, 2, f"${valor_base:,.0f}", formato_alt(idx, texto_bold, texto_bold_alt))
                    worksheet.write(fila_actual, 3, f"${valor_proyectado:,.0f}", formato_alt(idx, texto_proyectado, texto_proyectado))
                    worksheet.write(fila_actual, 4, f"${diferencia:,.0f}", formato_alt(idx, texto_bold, texto_bold_alt))
                    fila_actual += 1
                
                # Aportes proyectados
                aportes_sin_proyectar = data.get('aportes_sin_proyectar', {})
                desglose_pension = data.get('desglose_pension', {})
                
                fila_actual += 1  # Espacio entre secciones
                
                worksheet.write(fila_actual, 1, "APORTES OBLIGATORIOS", encabezado_proyeccion)
                worksheet.merge_range(fila_actual, 2, fila_actual, 4, "Comparativo de valores base y proyectados", encabezado_proyeccion)
                fila_actual += 1
                
                # Pensión total
                idx = 0
                concepto = "Pensión total"
                valor_base = aportes_sin_proyectar.get("pension_total", 0)
                valor_proyectado = data.get("total_pension", 0)
                diferencia = valor_proyectado - valor_base
                
                worksheet.write(fila_actual, 1, concepto, formato_alt(idx, texto_normal, texto_normal_alt))
                worksheet.write(fila_actual, 2, f"${valor_base:,.0f}", formato_alt(idx, texto_bold, texto_bold_alt))
                worksheet.write(fila_actual, 3, f"${valor_proyectado:,.0f}", formato_alt(idx, texto_proyectado, texto_proyectado))
                worksheet.write(fila_actual, 4, f"${diferencia:,.0f}", formato_alt(idx, texto_bold, texto_bold_alt))
                fila_actual += 1
                
                # Componentes de pensión
                componentes_pension = [
                    ("Aporte Pensión", "pension", "pension"),
                    ("Fondo de Solidaridad", "solidaridad", "solidaridad"),
                    ("Subsistencia", "subsistencia", "subsistencia")
                ]
                
                for idx, (concepto, key_base, key_desglose) in enumerate(componentes_pension, 1):
                    valor_base = aportes_sin_proyectar.get(key_base, 0)
                    valor_proyectado = desglose_pension.get(key_desglose, 0)
                    diferencia = valor_proyectado - valor_base
                    
                    worksheet.write(fila_actual, 1, f"  • {concepto}", formato_alt(idx, texto_normal, texto_normal_alt))
                    worksheet.write(fila_actual, 2, f"${valor_base:,.0f}", formato_alt(idx, texto_bold, texto_bold_alt))
                    worksheet.write(fila_actual, 3, f"${valor_proyectado:,.0f}", formato_alt(idx, texto_proyectado, texto_proyectado))
                    worksheet.write(fila_actual, 4, f"${diferencia:,.0f}", formato_alt(idx, texto_bold, texto_bold_alt))
                    fila_actual += 1
                
                # Salud y total aportes
                otros_aportes = [
                    ("Salud", "salud", "salud"),
                    ("Total aportes", "total", "ing_no_gravados")
                ]
                
                for idx, (concepto, key_base, key_proy) in enumerate(otros_aportes, 4):
                    valor_base = aportes_sin_proyectar.get(key_base, 0)
                    valor_proyectado = data.get(key_proy, 0)
                    diferencia = valor_proyectado - valor_base
                    
                    worksheet.write(fila_actual, 1, concepto, formato_alt(idx, texto_normal, texto_normal_alt))
                    worksheet.write(fila_actual, 2, f"${valor_base:,.0f}", formato_alt(idx, texto_bold, texto_bold_alt))
                    worksheet.write(fila_actual, 3, f"${valor_proyectado:,.0f}", formato_alt(idx, texto_proyectado, texto_proyectado))
                    worksheet.write(fila_actual, 4, f"${diferencia:,.0f}", formato_alt(idx, texto_bold, texto_bold_alt))
                    fila_actual += 1
                
                fila_actual += 1  # Espacio extra después de la sección de proyección
                
            # SECCIONES NORMALES DEL REPORTE
            
            def crear_seccion(titulo, contenido_filas, referencia_legal=None):
                nonlocal fila_actual
                worksheet.merge_range(fila_actual, 1, fila_actual, 4, titulo, subtitulo_formato)
                fila_actual += 1
                
                # Agregar referencia legal si existe
                if referencia_legal:
                    worksheet.merge_range(fila_actual, 1, fila_actual, 4, referencia_legal, referencia_legal_formato)
                    fila_actual += 1
                    
                for i, fila in enumerate(contenido_filas):
                    es_alterna = i % 2 == 1
                    formato_texto = texto_normal_alt if es_alterna else texto_normal
                    formato_valor = texto_bold_alt if es_alterna else texto_bold
                    es_retencion = "Retención" in fila[0] if len(fila) > 0 else False
                    if es_retencion:
                        formato_valor = retención_formato
                    label = fila[0] if len(fila) > 0 else ""
                    value = fila[1] if len(fila) > 1 else ""
                    observation = fila[2] if len(fila) > 2 else None
                    limit = fila[3] if len(fila) > 3 else None
                    worksheet.merge_range(fila_actual, 1, fila_actual, 2, label, formato_texto)
                    worksheet.merge_range(fila_actual, 3, fila_actual, 4, value, formato_valor)
                    fila_actual += 1
                    if observation or limit:
                        notas = []
                        if observation:
                            notas.append(f"Nota: {observation}")
                        if limit:
                            notas.append(f"Límite: {limit}")
                        
                        nota_texto = " | ".join(notas)
                        worksheet.merge_range(fila_actual, 1, fila_actual, 4, nota_texto, nota_formato)
                        fila_actual += 1
                
                fila_actual += 1
            
            # Crear entradas para ingresos
            ingresos_filas = [
                ("Sueldo básico", f"${data.get('salario', 0):,.0f}", None),
                ("Comisiones", f"${data.get('comisiones', 0):,.0f}", None),
                ("Otros pagos laborales", f"${data.get('dev_salarial', 0) + data.get('dev_no_salarial', 0):,.0f}", None),
                ("Total Ingresos Laborales", f"${data.get('total_ing_base', 0):,.0f}", None)
            ]
            crear_seccion("1. PAGOS LABORALES DEL MES", ingresos_filas)
            
            # Crear entradas para aportes
            aportes_filas = [
                ("Aportes obligatorios a Pensión", f"${data.get('total_pension', 0):,.0f}", "Sin límites"),
                ("Aportes obligatorios a Salud", f"${data.get('salud', 0):,.0f}", "Sin límites"),
                ("Total Ingresos No Constitutivos", f"${data.get('ing_no_gravados', 0):,.0f}", None),
                ("Subtotal 1", f"${data.get('subtotal_ibr1', 0) + data.get('total_deducciones', 0):,.0f}", None)
            ]
            crear_seccion("2. INGRESOS NO CONSTITUTIVOS DE RENTA", aportes_filas)
            
            # Crear entradas para deducciones
            deducciones_filas = [
                ("Vales de alimentación", f"${data.get('ded_vales', 0):,.0f}", 
                "Máximo 41 UVT mensual para ingresos menores a 310 UVT"),
                
                ("Intereses de vivienda", f"${data.get('ded_vivienda', 0):,.0f}", 
                "Límite máximo 100 UVT Mensuales"),
                
                ("Dependientes", f"${data.get('ded_dependientes', 0):,.0f}", 
                "No puede exceder del 10% del ingreso bruto y máximo 32 UVT mensuales"),
                
                ("Medicina prepagada", f"${data.get('ded_salud', 0):,.0f}", 
                "No puede exceder 16 UVT Mensuales"),
                
                ("Total Deducciones", f"${data.get('total_deducciones', 0):,.0f}", None)
            ]
            crear_seccion("3. DEDUCCIONES", deducciones_filas, 
                        "Según Art. 387 del E.T. y normas reglamentarias")
            
            # Crear entradas para rentas exentas
            rentas_filas = [
                ("Aportes AFC", f"${data.get('re_afc', 0):,.0f}", 
                "Límite del 30% del ingreso laboral y hasta 3.800 UVT anuales"),
                
                ("Renta Exenta 25%", f"${data.get('renta_exenta_25', 0):,.0f}", 
                "Límite máximo de 790 UVT anuales (Ley 2277 de 2022)"),
                
                ("Total Rentas Exentas", f"${data.get('total_re', 0) + data.get('renta_exenta_25', 0):,.0f}", None)
            ]
            crear_seccion("4. RENTAS EXENTAS", rentas_filas, 
                        "Basado en Art. 126-4 y Art. 206 numeral 10 del E.T.")
            
            # Crear entradas para base gravable y retención
            base_filas = [
                ("Base Gravable en UVTs", f"{data.get('ibr_uvts', 0):,.2f}", None),
                ("Porcentaje de Retención", f"{data.get('rate', 0)}%", None),
                ("Retención calculada", f"${data.get('retencion', 0):,.0f}", None),
            ]
            
            # Agregar nota de proyección si aplica
            if es_proyectado:
                nota_ajuste = "(Dividido por 2 al ser proyectado)"
                base_filas.append(("Ajuste por proyección", nota_ajuste, None))
                
            base_filas.extend([
                ("Retención anterior", f"${data.get('retencion_anterior', 0):,.0f}", None),
                ("Retención definitiva", f"${data.get('retencion_def', 0):,.0f}", None)
            ])
            
            crear_seccion("5. BASE GRAVABLE Y RETENCIÓN", base_filas, 
                        "Calculado según Art. 383 del E.T. con redondeo según Ley 1111 de 2006, Art. 50")
            
            worksheet.merge_range(fila_actual, 1, fila_actual + 2, 4,
                                "NOTA IMPORTANTE: La sumatoria de las Deducciones, Rentas exentas y el 25% de la renta de trabajo exenta, "
                                "no podrá superar el 40% del ingreso señalado en el subtotal 1 hasta 1340 UVT anuales (Ley 2277 de 2022)",
                                alerta_formato)
            fila_actual += 4
            
            # SECCIÓN DE TABLA DE RANGOS
            
            worksheet.merge_range(fila_actual, 1, fila_actual, 4, "TABLA DE RANGOS DE RETENCIÓN EN LA FUENTE", subtitulo_formato)
            fila_actual += 1
            
            worksheet.merge_range(fila_actual, 1, fila_actual, 6, 
                            "Conforme al Art. 383 del E.T., modificado por el Art. 42 de la Ley 2010 de 2019",
                            referencia_legal_formato)
            fila_actual += 1
            
            tabla_encabezado = workbook.add_format({
                'font_name': 'Arial', 'font_size': 10, 'bold': True, 
                'bg_color': azul_oscuro, 'font_color': 'white',
                'align': 'center', 'valign': 'vcenter', 'border': 1
            })
            
            worksheet.write(fila_actual, 1, "Rangos en UVT", tabla_encabezado)
            worksheet.write(fila_actual, 2, "Desde", tabla_encabezado)
            worksheet.write(fila_actual, 3, "Hasta", tabla_encabezado)
            worksheet.write(fila_actual, 4, "Tarifa marginal", tabla_encabezado)
            worksheet.write(fila_actual, 5, "Impuesto", tabla_encabezado)
            worksheet.write(fila_actual, 6, "Aplicable", tabla_encabezado)
            fila_actual += 1
            
            tabla_data = [
                ["1", ">0", "95", "0%", "-"],
                ["2", "95", "150", "19%", "(Ingreso laboral gravado expresado en UVT menos 95 UVT)*19%"],
                ["3", "150", "360", "28%", "(Ingreso laboral gravado expresado en UVT menos 150 UVT)*28% más 10 UVT"],
                ["4", "360", "640", "33%", "(Ingreso laboral gravado expresado en UVT menos 360 UVT)*33% más 69 UVT"],
                ["5", "640", "945", "35%", "(Ingreso laboral gravado expresado en UVT menos 640 UVT)*35% más 162 UVT"],
                ["6", "945", "2300", "37%", "(Ingreso laboral gravado expresado en UVT menos 945 UVT)*37% más 268 UVT"],
                ["7", "2300", "En adelante", "39%", "(Ingreso laboral gravado expresado en UVT menos 2300 UVT)*39% más 770 UVT"]
            ]
            
            base_uvts = data.get('ibr_uvts', 0)
            rango_aplicable = 0
            
            if base_uvts <= 95:
                rango_aplicable = 1
            elif 95 < base_uvts <= 150:
                rango_aplicable = 2
            elif 150 < base_uvts <= 360:
                rango_aplicable = 3
            elif 360 < base_uvts <= 640:
                rango_aplicable = 4
            elif 640 < base_uvts <= 945:
                rango_aplicable = 5
            elif 945 < base_uvts <= 2300:
                rango_aplicable = 6
            else:  # > 2300
                rango_aplicable = 7
            
            formato_tabla = workbook.add_format({
                'font_name': 'Arial', 'font_size': 10, 'border': 1,
                'align': 'center', 'valign': 'vcenter'
            })
            
            formato_tabla_alt = workbook.add_format({
                'font_name': 'Arial', 'font_size': 10, 'border': 1,
                'align': 'center', 'valign': 'vcenter',
                'bg_color': gris_claro
            })
            
            formato_rango_aplicable = workbook.add_format({
                'font_name': 'Arial', 'font_size': 10, 'border': 1,
                'align': 'center', 'valign': 'vcenter',
                'bg_color': azul_claro, 'font_color': 'white', 'bold': True
            })
            
            for i, fila in enumerate(tabla_data):
                es_alterna = i % 2 == 1
                es_aplicable = int(fila[0]) == rango_aplicable
                
                formato_fila = formato_rango_aplicable if es_aplicable else (formato_tabla_alt if es_alterna else formato_tabla)
                
                for j, valor in enumerate(fila):
                    worksheet.write(fila_actual, j + 1, valor, formato_fila)
                worksheet.write(fila_actual, 6, "X" if es_aplicable else "", formato_fila)
                
                fila_actual += 1
            
            # BASE APLICABLE CON DISMINUCIÓN DE UVT
            if base_uvts > 0:
                fila_actual += 1
                worksheet.merge_range(fila_actual, 1, fila_actual, 6, "BASE APLICABLE CON DISMINUCIÓN DE UVT", subtitulo_formato)
                fila_actual += 1
                worksheet.write(fila_actual, 1, "Base UVTs", tabla_encabezado)
                worksheet.write(fila_actual, 2, "Menos UVTs", tabla_encabezado)
                worksheet.write(fila_actual, 3, "Base Restante", tabla_encabezado)
                worksheet.write(fila_actual, 4, "Tarifa", tabla_encabezado)
                worksheet.write(fila_actual, 5, "Más UVTs", tabla_encabezado)
                worksheet.write(fila_actual, 6, "Retención UVTs", tabla_encabezado)
                fila_actual += 1
                resta_uvt = 0
                mas_uvt = 0
                tarifa = data.get('rate', 0)
                
                if 95 < base_uvts <= 150:
                    resta_uvt = 95
                    mas_uvt = 0
                elif 150 < base_uvts <= 360:
                    resta_uvt = 150
                    mas_uvt = 10
                elif 360 < base_uvts <= 640:
                    resta_uvt = 360
                    mas_uvt = 69
                elif 640 < base_uvts <= 945:
                    resta_uvt = 640
                    mas_uvt = 162
                elif 945 < base_uvts <= 2300:
                    resta_uvt = 945
                    mas_uvt = 268
                elif base_uvts > 2300:
                    resta_uvt = 2300
                    mas_uvt = 770
                
                base_restante = base_uvts - resta_uvt
                retencion_uvts = (base_restante * tarifa / 100) + mas_uvt
                
                # Aplicar ajuste por proyección
                if es_proyectado:
                    retencion_uvts = retencion_uvts / 2
                
                formato_valores = workbook.add_format({
                    'font_name': 'Arial', 'font_size': 10, 'border': 1,
                    'align': 'center', 'valign': 'vcenter', 'bold': True,
                    'bg_color': azul_claro, 'font_color': 'white'
                })
                
                worksheet.write(fila_actual, 1, f"{base_uvts:,.2f}", formato_valores)
                worksheet.write(fila_actual, 2, f"{resta_uvt:,.0f}", formato_valores)
                worksheet.write(fila_actual, 3, f"{base_restante:,.2f}", formato_valores)
                worksheet.write(fila_actual, 4, f"{tarifa}%", formato_valores)
                worksheet.write(fila_actual, 5, f"{mas_uvt:,.0f}", formato_valores)
                worksheet.write(fila_actual, 6, f"{retencion_uvts:,.2f}", formato_valores)
                
                # Si es proyectado, agregar nota explicativa
                if es_proyectado:
                    fila_actual += 2
                    worksheet.merge_range(fila_actual, 1, fila_actual, 6, 
                                    "Nota: El valor de retención UVTs ha sido dividido por 2 debido a que es una proyección para quincena.", 
                                    alerta_formato)
        
        workbook.close()
        
        output.seek(0)
        return base64.b64encode(output.read()).decode('utf-8')
    
    def _create_prestaciones_excel(self, prestaciones_lines):
        import io
        import math
        output = io.BytesIO()
        
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        
        # Formatos para el Excel (mantenemos los mismos formatos)
        header_format = workbook.add_format({
            'bold': True, 
            'align': 'center',
            'valign': 'vcenter',
            'fg_color': '#1e88e5',
            'color': 'white',
            'border': 1
        })
        
        # [Resto de formatos igual que en el código original]
        subheader_format = workbook.add_format({
            'bold': True, 
            'align': 'center',
            'valign': 'vcenter',
            'fg_color': '#64b5f6',
            'color': 'white',
            'border': 1
        })
        
        company_header_format = workbook.add_format({
            'bold': True,
            'align': 'left',
            'valign': 'vcenter',
            'fg_color': '#f0f0f0',
            'color': '#333333',
            'border': 1,
            'font_size': 12
        })
        
        date_format = workbook.add_format({
            'num_format': 'dd/mm/yyyy',
            'align': 'center',
            'border': 1
        })
        
        currency_format = workbook.add_format({
            'num_format': '#,##0.00',
            'align': 'right',
            'border': 1
        })
        
        formula_format = workbook.add_format({
            'num_format': '#,##0.00',
            'align': 'right',
            'border': 1,
            'italic': True,
            'fg_color': '#e3f2fd'
        })
        
        formula_text_format = workbook.add_format({
            'align': 'right',
            'border': 1,
            'italic': True,
            'fg_color': '#e3f2fd'
        })
        
        text_format = workbook.add_format({
            'align': 'left',
            'border': 1
        })
        
        cell_label_format = workbook.add_format({
            'align': 'left',
            'border': 1,
            'bold': True
        })
        
        step_title_format = workbook.add_format({
            'align': 'left',
            'border': 1,
            'bold': True,
            'fg_color': '#e8eaf6'
        })
        
        calculation_format = workbook.add_format({
            'align': 'left',
            'border': 1,
            'font_size': 11,
            'font_color': '#1565c0'
        })
        
        porcent_format = workbook.add_format({
            'num_format': '0.00%',
            'align': 'right',
            'border': 1
        })
        
        # Obtener datos de la empresa
        company = self.env.company
        company_name = company.name
        company_vat = company.vat or 'N/A'
        payslip = prestaciones_lines[0].slip_id if prestaciones_lines else None
        payslip_number = payslip.number if payslip else 'N/A'
        payslip_date = payslip.date_to if payslip else datetime.now()
        employee_name = payslip.employee_id.name if payslip and payslip.employee_id else 'N/A'
        
        # Procesar cada línea de prestación
        for line in prestaciones_lines:
            # Cargar los datos JSON
            computation_data = json.loads(line.computation)
            
            # Nombre de la hoja (limitar longitud para evitar errores)
            sheet_name = line.salary_rule_id.code[:10] if line.salary_rule_id.code else f'Prestacion_{line.id}'
            
            # Crear hoja para cada tipo de prestación
            worksheet = workbook.add_worksheet(sheet_name)
            
            # Configurar ancho de columnas
            worksheet.set_column('A:A', 20)
            worksheet.set_column('B:B', 40)
            worksheet.set_column('C:C', 20)
            worksheet.set_column('D:D', 20)
            worksheet.set_column('E:E', 20)
            
            # Encabezado con datos de la empresa
            worksheet.merge_range('A1:E1', 'REPORTE DE PRESTACIONES SOCIALES', header_format)
            worksheet.merge_range('A2:C2', f'EMPRESA: {company_name}', company_header_format)
            worksheet.merge_range('D2:E2', f'NIT: {company_vat}', company_header_format)
            worksheet.merge_range('A3:C3', f'COMPROBANTE: {payslip_number}', company_header_format)
            worksheet.merge_range('D3:E3', f'FECHA: {payslip_date.strftime("%d/%m/%Y")}', company_header_format)
            worksheet.merge_range('A4:E4', f'EMPLEADO: {employee_name}', company_header_format)
            
            # Datos de la prestación
            worksheet.write('A6', 'Prestación:', cell_label_format)
            worksheet.write('B6', line.name, text_format)
            worksheet.write('C6', 'Código:', cell_label_format)
            worksheet.write('D6', line.salary_rule_id.code if line.salary_rule_id else 'N/A', text_format)
            
            # Extraer los datos principales
            meta_info = computation_data.get('meta_info', {})
            plain_days = meta_info.get('plain_days', 0)
            susp = meta_info.get('susp', 0)
            wage = meta_info.get('wage', 0)
            auxtransporte = meta_info.get('auxtransporte', 0)
            total_variable = meta_info.get('total_variable', 0)
            amount_base = meta_info.get('amount_base', 0)
            valor_primas = meta_info.get('valor_primas', 0)
            
            provisiones = computation_data.get('provisiones', {})
            provision_anterior = provisiones.get('valor_anterior', 0)
            provision_actual = provisiones.get('valor_actual', 0)
            diferencia_provision = provisiones.get('diferencia', 0)
            
            code = line.salary_rule_id.code
            es_cesantias = code in ("CESANTIAS", "PRV_CES", "CES_YEAR")
            es_intereses = code in ("INTCESANTIAS", "PRV_ICES", "INTCES_YEAR")
            es_vacaciones = code in ("VACATIONS_MONEY", "PRV_VAC", "VACCONTRATO")
            es_prima = code in ("prima", "PRV_PRIM", "primaextralegal")
            es_provision = code.startswith("PRV_")
            
            contract_modality = meta_info.get('contract_modality', 'fijo')  # 'fijo' por defecto
            es_salario_variable = contract_modality == 'variable'
            
            fecha_inicio = ''
            fecha_fin = ''
            
            if 'fecha_inicio' in meta_info and meta_info['fecha_inicio']:
                try:
                    fecha_inicio = datetime.strptime(meta_info['fecha_inicio'], '%Y-%m-%d').date()
                except ValueError:
                    fecha_inicio = ''
            
            if 'fecha_fin' in meta_info and meta_info['fecha_fin']:
                try:
                    fecha_fin = datetime.strptime(meta_info['fecha_fin'], '%Y-%m-%d').date()
                except ValueError:
                    fecha_fin = ''
            
            # ----------------------------------
            # 1. INFORMACIÓN GENERAL
            # ----------------------------------
            
            # Determinar filas y referencias exactas
            info_header_row = 8
            fecha_inicio_row = 9
            num_comprobante_row = 10
            dias_totales_row = 11
            dias_susp_row = 12
            salario_row = 13
            auxilio_row = 13  # Misma fila, columna diferente
            
            dias_totales_cell = f'B{dias_totales_row}'
            dias_suspension_cell = f'B{dias_susp_row}'
            dias_liquidados_cell = f'D{dias_totales_row}'
            porcentaje_cell = f'D{dias_susp_row}'
            salario_cell = f'B{salario_row}'
            auxilio_cell = f'D{auxilio_row}'
            
            worksheet.merge_range(f'A{info_header_row}:E{info_header_row}', 'INFORMACIÓN GENERAL', header_format)
            
            worksheet.write(f'A{fecha_inicio_row}', 'Fecha Inicio:', cell_label_format)
            worksheet.write(f'B{fecha_inicio_row}', fecha_inicio, date_format if fecha_inicio else text_format)
            worksheet.write(f'C{fecha_inicio_row}', 'Fecha Fin:', cell_label_format)
            worksheet.write(f'D{fecha_inicio_row}', fecha_fin, date_format if fecha_fin else text_format)
            
            worksheet.write(f'A{num_comprobante_row}', 'Número Comprobante:', cell_label_format)
            worksheet.write(f'B{num_comprobante_row}', payslip_number, text_format)
            
            worksheet.write(f'A{dias_totales_row}', 'Días Totales:', cell_label_format)
            worksheet.write(f'B{dias_totales_row}', plain_days, text_format)
            worksheet.write(f'C{dias_totales_row}', 'Días Liquidados:', cell_label_format)
            worksheet.write_formula(f'D{dias_totales_row}', f'={dias_totales_cell}-{dias_suspension_cell}', formula_format, plain_days - susp)
            
            worksheet.write(f'A{dias_susp_row}', 'Días Suspensión:', cell_label_format)
            worksheet.write(f'B{dias_susp_row}', susp, text_format)
            worksheet.write(f'C{dias_susp_row}', 'Porcentaje Liquidado:', cell_label_format)
            
            if es_intereses:
                # Caso especial para intereses de cesantías - simplemente mostramos el porcentaje
                # El cálculo real se realizará en la fórmula (12% / (días/360) / 100)
                porcentaje = (plain_days - susp) / 360 if plain_days > 0 else 0
                worksheet.write_formula(
                    f'D{dias_susp_row}', 
                    f'={dias_liquidados_cell}/360', 
                    porcent_format, 
                    porcentaje
                )
            else:
                # Para otras prestaciones, mantener la fórmula original
                porcentaje = min((plain_days - susp) / 360, 1)
                worksheet.write_formula(f'D{dias_susp_row}', f'=MIN({dias_liquidados_cell}/360, 1)', porcent_format, porcentaje)
            
            worksheet.write(f'A{salario_row}', 'Salario Base:', cell_label_format)
            worksheet.write(f'B{salario_row}', wage, currency_format)
            worksheet.write(f'C{salario_row}', 'Auxilio Transporte:', cell_label_format)
            worksheet.write(f'D{salario_row}', auxtransporte, currency_format)
            
            # ----------------------------------
            # 2. DETALLE DE CÁLCULOS
            # ----------------------------------
            calculo_header_row = 17
            promedio_dia_row = 18
            factor_dia_row = 19
            
            worksheet.merge_range(f'A{calculo_header_row}:E{calculo_header_row}', 'DETALLE DE CÁLCULOS', header_format)
            
            worksheet.write(f'A{promedio_dia_row}', 'Promedio diario:', cell_label_format)
            diario_salario = wage / 30
            worksheet.write_formula(f'B{promedio_dia_row}', f'={salario_cell}/30', formula_format, diario_salario)
            worksheet.write(f'C{promedio_dia_row}', 'Promedio día variable:', cell_label_format)
            
            # Promedio diario variable
            if plain_days > 0:
                if plain_days <= 30 and es_salario_variable:
                    diario_variable = total_variable / plain_days
                    worksheet.write(f'D{promedio_dia_row}', diario_variable, currency_format)
                else:
                    # Cálculo normal
                    diario_variable = total_variable / plain_days
                    worksheet.write_formula(f'D{promedio_dia_row}', f'=E31/{dias_totales_cell}', formula_format, diario_variable)
            else:
                worksheet.write(f'D{promedio_dia_row}', 0, currency_format)
            
            worksheet.write(f'A{factor_dia_row}', 'Factor día (360):', cell_label_format)
            worksheet.write_formula(f'B{factor_dia_row}', '=1/360', formula_format, 1/360)
            worksheet.write(f'C{factor_dia_row}', 'Total días liquidados:', cell_label_format)
            worksheet.write(f'D{factor_dia_row}', plain_days - susp, text_format)
            
            # ----------------------------------
            # 4. NOVEDADES EN ORDEN CRONOLÓGICO
            # ----------------------------------
            novedades_header_row = 21
            novedades_columns_row = 22
            first_entry_row = 23
            
            worksheet.merge_range(f'A{novedades_header_row}:E{novedades_header_row}', 'NOVEDADES ORDENADAS POR FECHA', header_format)
            
            worksheet.write(f'A{novedades_columns_row}', 'Fecha', subheader_format)
            worksheet.write(f'B{novedades_columns_row}', 'Descripción', subheader_format)
            worksheet.write(f'C{novedades_columns_row}', 'Código', subheader_format)
            worksheet.write(f'D{novedades_columns_row}', 'Origen', subheader_format)
            worksheet.write(f'E{novedades_columns_row}', 'Monto', subheader_format)
            
            all_entries = []
            
            entradas_nomina = computation_data.get('novedades_promedio', {}).get('entradas', [])
            filtered_entries = [
                entry for entry in entradas_nomina 
                if entry.get('regla_salarial', '') not in ['VARIACION', 'LICENCIA']
            ]
            all_entries.extend(filtered_entries)
            
            # Función para convertir fecha a objeto datetime para ordenamiento
            def get_fecha_for_sorting(entry):
                fecha = entry.get('fecha', '1900-01-01')
                if isinstance(fecha, str):
                    try:
                        return datetime.strptime(fecha, '%Y-%m-%d')
                    except ValueError:
                        return datetime(1900, 1, 1)
                return fecha or datetime(1900, 1, 1)
            
            # Ordenar por fecha
            sorted_entries = sorted(all_entries, key=get_fecha_for_sorting)
            
            # Escribir entradas ordenadas
            current_row = first_entry_row
            for entry in sorted_entries:
                try:
                    fecha = entry.get('fecha', '')
                    if isinstance(fecha, str) and fecha:
                        try:
                            fecha = datetime.strptime(fecha, '%Y-%m-%d').date()
                        except ValueError:
                            fecha = ''
                    
                    worksheet.write(f'A{current_row}', fecha, date_format if fecha else text_format)
                    worksheet.write(f'B{current_row}', entry.get('nombre_regla', ''), text_format)
                    worksheet.write(f'C{current_row}', entry.get('regla_salarial', ''), text_format)
                    worksheet.write(f'D{current_row}', entry.get('origen', ''), text_format)
                    worksheet.write(f'E{current_row}', entry.get('monto', 0), currency_format)
                    current_row += 1
                except Exception as e:
                    worksheet.write(f'A{current_row}', "Error en entrada", text_format)
                    worksheet.write(f'B{current_row}', str(e), text_format)
                    current_row += 1
            
            last_entry_row = current_row - 1
            
            if last_entry_row >= first_entry_row:
                worksheet.write(f'D{current_row}', 'TOTAL NOVEDADES:', cell_label_format)
                total_novedades_cell = f'E{current_row}'
                worksheet.write_formula(total_novedades_cell, f'=SUM(E{first_entry_row}:E{last_entry_row})', formula_format, total_variable)
                workbook.define_name('TOTAL_NOVEDADES', f'={sheet_name}!{total_novedades_cell}')
                current_row += 1
            else:
                total_novedades_cell = f'E{current_row}'
                worksheet.write(f'D{current_row}', 'TOTAL NOVEDADES:', cell_label_format)
                worksheet.write(total_novedades_cell, total_variable, currency_format)
                current_row += 1
            
            promedio_variable_row = current_row
            worksheet.write(f'A{current_row}', 'Promedio Variable:', cell_label_format)
            if plain_days > 0:
                if plain_days <= 30:
                    promedio_variable = total_variable
                    worksheet.write(
                        f'B{current_row}', 
                        promedio_variable, 
                        currency_format
                    )
                else:
                    promedio_variable = total_variable / plain_days * 30
                    worksheet.write_formula(
                        f'B{current_row}', 
                        f'=({total_novedades_cell}/{plain_days})*30', 
                        formula_format, 
                        promedio_variable
                    )
            else:
                worksheet.write(f'B{current_row}', 0, currency_format)
            promedio_variable_cell = f'B{current_row}'
            current_row += 1
            
            # Base de cálculo con fórmula
            base_calculo_row = current_row
            worksheet.write(f'A{current_row}', 'Base de Cálculo:', cell_label_format)
            if plain_days > 0:
                worksheet.write_formula(f'B{current_row}', f'={salario_cell}+{auxilio_cell}+{promedio_variable_cell}', formula_format, amount_base)
            else:
                worksheet.write(f'B{current_row}', amount_base, currency_format)
            base_calculo_cell = f'B{current_row}'
            current_row += 1
            
            # ----------------------------------
            # 3. PROVISIONES
            # ----------------------------------
            provisiones_header_row = current_row + 1
            provisiones_anterior_row = provisiones_header_row + 1
            provisiones_actual_row = provisiones_anterior_row + 1
            provisiones_diferencia_row = provisiones_actual_row + 1
            provisiones_estado_row = provisiones_diferencia_row + 1
            provisiones_contabilizar_row = provisiones_estado_row + 1
            
            worksheet.merge_range(f'A{provisiones_header_row}:E{provisiones_header_row}', 'PROVISIONES', header_format)
            
            provision_anterior_cell = f'B{provisiones_anterior_row}'
            worksheet.write(f'A{provisiones_anterior_row}', 'Provisión Anterior:', cell_label_format)
            worksheet.write(provision_anterior_cell, abs(provision_anterior), currency_format)
            
            provision_actual_cell = f'B{provisiones_actual_row}'
            worksheet.write(f'A{provisiones_actual_row}', 'Provisión Actual:', cell_label_format)
            
            if es_intereses:
                base_cesantias = meta_info.get('base_cesantias', amount_base)
                base_cesantias_cell = f'B{base_calculo_row + 1}'
                worksheet.write(f'A{base_calculo_row + 1}', 'Base Cesantías:', cell_label_format)
                worksheet.write(base_cesantias_cell, base_cesantias, currency_format)
                
                worksheet.write_formula(
                    provision_actual_cell, 
                    f'=({base_cesantias_cell}/ {360})*{dias_liquidados_cell} *(12% * {dias_liquidados_cell})/360', 
                    formula_format, 
                    valor_primas
                )
            else:
                # Caso estándar: otras prestaciones
                valor_base_diario = amount_base / 360
                worksheet.write_formula(provision_actual_cell, f'={base_calculo_cell}/360*{dias_liquidados_cell}', formula_format, valor_primas)
            
            diferencia_cell = f'B{provisiones_diferencia_row}'
            worksheet.write(f'A{provisiones_diferencia_row}', 'Diferencia:', cell_label_format)
            worksheet.write_formula(diferencia_cell, f'={provision_actual_cell}-{provision_anterior_cell}', formula_format, diferencia_provision)
            
            worksheet.write(f'A{provisiones_estado_row}', 'Estado:', cell_label_format)
            worksheet.write_formula(f'B{provisiones_estado_row}', f'=IF({diferencia_cell}>0,"Por provisionar","Ajustar provisión")', formula_text_format, 
                                    "Por provisionar" if diferencia_provision > 0 else "Ajustar provisión")
            
            worksheet.write(f'A{provisiones_contabilizar_row}', 'Valor a Contabilizar:', cell_label_format)
            worksheet.write_formula(f'B{provisiones_contabilizar_row}', f'=ABS({diferencia_cell})', formula_format, abs(diferencia_provision))
            
            # ----------------------------------
            # 5. RESUMEN DE TOTALES
            # ----------------------------------
            current_row = provisiones_contabilizar_row + 2
            totales_header_row = current_row
            totales_columns_row = totales_header_row + 1
            total_nomina_row = totales_columns_row + 1
            total_acumulado_row = total_nomina_row + 1
            total_novedades_row = total_acumulado_row + 1
            valor_base_diario_row = total_novedades_row + 1
            valor_final_row = valor_base_diario_row + 1
            valor_redondeado_row = valor_final_row + 1
            numero_nomina_row = valor_redondeado_row + 1
            
            worksheet.merge_range(f'A{totales_header_row}:E{totales_header_row}', 'RESUMEN DE TOTALES', header_format)
            
            worksheet.write(f'A{totales_columns_row}', 'Concepto', subheader_format)
            worksheet.write(f'B{totales_columns_row}', 'Valor', subheader_format)
            worksheet.write(f'C{totales_columns_row}', 'Fórmula/Origen', subheader_format)
            
            totales = computation_data.get('novedades_promedio', {}).get('totales', {})
            payslip_total_cell = f'B{total_nomina_row}'
            worksheet.write(f'A{total_nomina_row}', 'Total Nómina:', cell_label_format)
            total_nomina = totales.get('payslip_total', 0)
            worksheet.write(payslip_total_cell, total_nomina, currency_format)
            worksheet.write(f'C{total_nomina_row}', 'Suma de entradas de nómina', formula_text_format)
            
            acumulado_total_cell = f'B{total_acumulado_row}'
            worksheet.write(f'A{total_acumulado_row}', 'Total Acumulado:', cell_label_format)
            total_acumulado = totales.get('accumulated_total', 0)
            worksheet.write(acumulado_total_cell, total_acumulado, currency_format)
            worksheet.write(f'C{total_acumulado_row}', 'Suma de acumulados previos', formula_text_format)
            
            total_novedades_valor_cell = f'B{total_novedades_row}'
            worksheet.write(f'A{total_novedades_row}', 'Total Novedades:', cell_label_format)
            if 'total_novedades_cell' in locals():
                worksheet.write_formula(total_novedades_valor_cell, f'={total_novedades_cell}', formula_format, total_variable)
            else:
                worksheet.write(total_novedades_valor_cell, total_variable, currency_format)
            # En la columna de fórmula, mostrar el valor del total de nómina
            worksheet.write_formula(f'C{total_novedades_row}', f'={payslip_total_cell}', formula_format, total_nomina)
            
            valor_base_diario_cell = f'B{valor_base_diario_row}'
            worksheet.write(f'A{valor_base_diario_row}', 'Valor Base Diario:', cell_label_format)
            valor_base_diario = amount_base / 360
            worksheet.write_formula(valor_base_diario_cell, f'={base_calculo_cell}/360', formula_format, valor_base_diario)
            worksheet.write(f'C{valor_base_diario_row}', 'Base Cálculo / 360', formula_text_format)
            
            # Valor final con la fórmula corregida para intereses
            valor_final_cell = f'B{valor_final_row}'
            worksheet.write(f'A{valor_final_row}', 'Valor Final:', cell_label_format)
            if es_intereses:
                # Nueva fórmula para intereses: Base * (12% / (días/360) / 100)
                base_cesantias = meta_info.get('base_cesantias', amount_base)
                
                # Verificar si ya existe la celda de base_cesantias
                if 'base_cesantias_cell' not in locals():
                    base_cesantias_cell = f'B{base_calculo_row + 1}'
                
                # Aplicar la nueva fórmula de intereses
                worksheet.write_formula(
                    valor_final_cell, 
                    f'=({base_cesantias_cell} / {360})* {dias_liquidados_cell} *((0.12*{dias_liquidados_cell})/360)', 
                    formula_format, 
                    valor_primas
                )
                worksheet.write(f'C{valor_final_row}', 'Base Cesantías * (12% / (Días/360) / 100)', formula_text_format)
            else:
                worksheet.write_formula(valor_final_cell, f'={valor_base_diario_cell}*{dias_liquidados_cell}', formula_format, valor_primas)
                worksheet.write(f'C{valor_final_row}', 'Valor Base Diario * Días Efectivos', formula_text_format)
            
            # Redondeo 
            worksheet.write(f'A{valor_redondeado_row}', 'Valor Redondeado:', cell_label_format)
            worksheet.write_formula(f'B{valor_redondeado_row}', f'=ROUNDUP({valor_final_cell},0)', formula_format, math.ceil(valor_primas))
            worksheet.write(f'C{valor_redondeado_row}', 'Redondeo al entero superior', formula_text_format)
            
            worksheet.write(f'A{numero_nomina_row}', 'Número de Nómina:', cell_label_format)
            worksheet.write(f'B{numero_nomina_row}', payslip_number, text_format)
            
            # ----------------------------------
            # 6. TABLA PARA VARIACIONES DE SALARIO Y AUSENCIAS
            # ----------------------------------
            # [Resto del código igual que en la versión original]
            variaciones_header_row = numero_nomina_row + 2
            worksheet.merge_range(f'A{variaciones_header_row}:E{variaciones_header_row}', 'VARIACIONES DE SALARIO Y AUSENCIAS', header_format)
            
            variaciones_columns_row = variaciones_header_row + 1
            worksheet.write(f'A{variaciones_columns_row}', 'Fecha', subheader_format)
            worksheet.write(f'B{variaciones_columns_row}', 'Tipo', subheader_format)
            worksheet.write(f'C{variaciones_columns_row}', 'Valor Anterior', subheader_format)
            worksheet.write(f'D{variaciones_columns_row}', 'Valor Nuevo', subheader_format)
            worksheet.write(f'E{variaciones_columns_row}', 'Diferencia', subheader_format)
            
            # Escribir variaciones de salario
            current_row = variaciones_columns_row + 1
            variaciones = computation_data.get('variaciones_salario', [])
            
            # Si no hay explícitamente variaciones en el formato deseado, buscar en novedades
            if not variaciones:
                for entry in entradas_nomina:
                    if entry.get('regla_salarial') == 'VARIACION':
                        variaciones.append({
                            'fecha': entry.get('fecha', ''),
                            'salario_anterior': 0,  # No tenemos este dato en las novedades
                            'salario': entry.get('monto', 0)
                        })
            
            for variacion in variaciones:
                try:
                    fecha = variacion.get('fecha', '')
                    if isinstance(fecha, str) and fecha:
                        try:
                            fecha = datetime.strptime(fecha, '%Y-%m-%d').date()
                        except ValueError:
                            fecha = ''
                    
                    salario_anterior = variacion.get('salario_anterior', 0)
                    salario_nuevo = variacion.get('salario', 0)
                    
                    worksheet.write(f'A{current_row}', fecha, date_format if fecha else text_format)
                    worksheet.write(f'B{current_row}', 'Variación Salarial', text_format)
                    worksheet.write(f'C{current_row}', salario_anterior, currency_format)
                    worksheet.write(f'D{current_row}', salario_nuevo, currency_format)
                    worksheet.write_formula(f'E{current_row}', f'=D{current_row}-C{current_row}', formula_format, salario_nuevo - salario_anterior)
                    current_row += 1
                except Exception as e:
                    worksheet.write(f'A{current_row}', "Error en variación", text_format)
                    worksheet.write(f'B{current_row}', str(e), text_format)
                    current_row += 1

            # Escribir ausencias/licencias
            licencias = computation_data.get('licencias_no_remuneradas', [])
            for licencia in licencias:
                try:
                    fecha_inicio = licencia.get('fecha_inicio', '')
                    if isinstance(fecha_inicio, str) and fecha_inicio:
                        try:
                            fecha_inicio = datetime.strptime(fecha_inicio, '%Y-%m-%d').date()
                        except ValueError:
                            fecha_inicio = ''
                    
                    tipo_licencia = licencia.get('tipo_licencia', 'Sin tipo')
                    dias = licencia.get('dias', 0)
                    
                    worksheet.write(f'A{current_row}', fecha_inicio, date_format if fecha_inicio else text_format)
                    worksheet.write(f'B{current_row}', f'Licencia: {tipo_licencia}', text_format)
                    worksheet.write(f'C{current_row}', 'N/A', text_format)
                    worksheet.write(f'D{current_row}', f'{dias} días', text_format)
                    worksheet.write(f'E{current_row}', 0, currency_format)
                    current_row += 1
                except Exception as e:
                    worksheet.write(f'A{current_row}', "Error en licencia", text_format)
                    worksheet.write(f'B{current_row}', str(e), text_format)
                    current_row += 1
        
        # Crear una hoja de resumen si no hay ninguna hoja
        if not workbook.worksheets_objs:
            resumen_sheet = workbook.add_worksheet('Resumen')
            resumen_sheet.write('A1', 'No se encontraron datos para generar el reporte', header_format)
        
        # Cerrar el libro y obtener los datos
        workbook.close()
        output.seek(0)
        return base64.b64encode(output.read()).decode('utf-8')
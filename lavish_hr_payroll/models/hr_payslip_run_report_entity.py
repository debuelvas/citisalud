from odoo import tools
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from datetime import datetime

import base64
import io
import xlsxwriter

class HrPayslipRun(models.Model):
    _inherit = 'hr.payslip.run'

    excel_report_entity = fields.Binary(string='Reporte por fondos')
    excel_report_entity_filename = fields.Char(string='Filename reporte por fondos')

    # Reporte liquidacion lote por entidad
    def generate_settlement_report_entity(self):
        # ----------------------------------Ejecutar consulta

        query_report = f'''
                Select 
                    f."name" as Entidad, c."name" as NombreEmpleado, c.identification_id as IdentificacionEmpleado,d.quantity as Tiempo, 
                    (30/360::float)*d.quantity as Unidades,d.total as Valor
                From hr_payslip_run as a 
                inner join hr_payslip as b on a.id = b.payslip_run_id 
                inner join hr_employee as c on b.employee_id = c.id 
                inner join hr_payslip_line as d on b.id = d.slip_id
                inner join hr_employee_entities as e on d.entity_id = e.id 
                inner join res_partner as f on e.partner_id = f.id
                where a.id = {self.id}
        '''

        self._cr.execute(query_report)
        result_query = self._cr.dictfetchall()

        # Generar EXCEL
        filename = f'Reporte por fondos {self.name}'
        stream = io.BytesIO()
        book = xlsxwriter.Workbook(stream, {'in_memory': True})

        # Columnas
        columns = ['Entidad', 'Nombre del empleado', 'Identificación', 'Tiempo', 'Unidades', 'Valor liquidado']
        sheet = book.add_worksheet('Reporte por fondos')

        # Agregar textos al excel
        text_company = self.company_id.name
        text_title = f'Liquidacion - {self.name}'
        text_generate = 'Informe generado el %s' % (datetime.now())
        cell_format_title = book.add_format({'bold': True, 'align': 'left'})
        cell_format_title.set_font_name('Calibri')
        cell_format_title.set_font_size(15)
        cell_format_title.set_bottom(5)
        cell_format_title.set_bottom_color('#1F497D')
        cell_format_title.set_font_color('#1F497D')
        sheet.merge_range('A1:F1', text_company, cell_format_title)
        sheet.merge_range('A2:F2', text_title, cell_format_title)
        cell_format_text_generate = book.add_format({'bold': False, 'align': 'left'})
        cell_format_text_generate.set_font_name('Calibri')
        cell_format_text_generate.set_font_size(10)
        cell_format_text_generate.set_bottom(5)
        cell_format_text_generate.set_bottom_color('#1F497D')
        cell_format_text_generate.set_font_color('#1F497D')
        sheet.merge_range('A3:F3', text_generate, cell_format_text_generate)

        # Formato para fechas
        date_format = book.add_format({'num_format': 'dd/mm/yyyy'})

        # Agregar columnas
        aument_columns = 0
        for column in columns:
            sheet.write(3, aument_columns, column)
            aument_columns = aument_columns + 1

        # Agregar query
        aument_columns = 0
        aument_rows = 4
        for query in result_query:
            for row in query.values():
                width = len(str(row)) + 10
                if str(type(row)).find('date') > -1:
                    sheet.write_datetime(aument_rows, aument_columns, row, date_format)
                else:
                    sheet.write(aument_rows, aument_columns, row)
                # Ajustar tamaño columna
                sheet.set_column(aument_columns, aument_columns, width)
                aument_columns = aument_columns + 1
            aument_rows = aument_rows + 1
            aument_columns = 0

        # Convertir en tabla
        array_header_table = []
        for i in columns:
            dict = {'header': i}
            array_header_table.append(dict)

        sheet.add_table(3, 0, aument_rows, 5, {'style': 'Table Style Medium 2', 'columns': array_header_table})

        # Guadar Excel
        book.close()

        self.write({
            'excel_report_entity': base64.b64encode(stream.getvalue()).decode('utf-8'),
            'excel_report_entity_filename': filename,
        })

        action = {
            'name': 'Reporte por fondos',
            'type': 'ir.actions.act_url',
            'url': "web/content/?model=hr.payslip.run&id=" + str(
                self.id) + "&filename_field=excel_report_entity_filename&field=excel_report_entity&download=true&filename=" + self.excel_report_entity_filename,
            'target': 'self',
        }
        return action
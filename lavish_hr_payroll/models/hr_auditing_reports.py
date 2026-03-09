from odoo import tools
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from datetime import datetime, timedelta,date
from pytz import timezone
from dateutil.relativedelta import relativedelta
import base64
import io
import xlsxwriter


class hr_auditing_reports(models.TransientModel):
    _name = "hr.auditing.reports"
    _description = "Reporte auditoria"

    year = fields.Integer('Año', required=True)
    month = fields.Selection([('1', 'Enero'),
                            ('2', 'Febrero'),
                            ('3', 'Marzo'),
                            ('4', 'Abril'),
                            ('5', 'Mayo'),
                            ('6', 'Junio'),
                            ('7', 'Julio'),
                            ('8', 'Agosto'),
                            ('9', 'Septiembre'),
                            ('10', 'Octubre'),
                            ('11', 'Noviembre'),
                            ('12', 'Diciembre')
                            ], string='Mes', required=True)
    type_process = fields.Selection([('1', 'No incluidos en liquidaciones'),
                            ('2', 'No incluidos en seguridad social'),
                            ('3', 'No incluidos en Nómina Electrónica'),
                            ], string='Tipo', required=True, default='1')

    excel_file = fields.Binary('Excel')
    excel_file_name = fields.Char('Excel filename')

    def generate_excel_auditing(self):
        # Periodo
        date_initial = date(int(self.year), int(self.month), 1)
        date_from = date_initial.strftime('%Y-%m-%d')
        
        # Calcular la fecha final (último día del mes)
        date_end = date_initial + relativedelta(months=1) - relativedelta(days=1)
        date_to = date_end.strftime('%Y-%m-%d')
        # Obtener datos según el tipo de proceso
        if self.type_process == '1':  # No incluidos en liquidaciones del mes
            # Buscar todos los empleados de la compañía (activos e inactivos)
            employees = self.env['hr.employee'].with_context(active_test=False).search([
                ('company_id', '=', self.env.company.id)
            ])
            
            # Buscar nóminas en cualquier estado excepto canceladas
            payslips = self.env['hr.payslip'].search([
                ('employee_id', 'in', employees.ids),
                ('date_from', '>=', date_from),
                ('date_to', '<=', date_to),
                ('state', '!=', 'cancel')
            ])
            employees_with_payslips = payslips.mapped('employee_id')
            employees_without_payslips = employees - employees_with_payslips

            result_query = [{
                'identification_id': e.identification_id,
                'name_employee': e.name,
                'employee_state': 'Activo' if e.active else 'Archivado',
                'date_start': e.contract_id.date_start,
                'name_contract': e.contract_id.name,
                'contract_state': e.contract_id.state,
                'retirement_date': e.contract_id.retirement_date or '1900-01-01',
            } for e in employees_without_payslips]

        elif self.type_process == '2':  # No incluidos en seguridad social
            # Buscar todos los empleados (activos e inactivos) que tienen nóminas en el período
            payslips = self.env['hr.payslip'].search([
                ('date_from', '>=', date_from),
                ('date_to', '<=', date_to),
                ('company_id', '=', self.env.company.id),
                ('state', '!=', 'cancel')  # Cualquier estado menos cancelada
            ])
            
            employees = payslips.mapped('employee_id')
            
            # Buscar empleados que no están en seguridad social
            employees_without_ss = employees.filtered(
                lambda e: not self.env['hr.executing.social.security'].search([
                    ('employee_id', '=', e.id),
                    ('executing_social_security_id.year', '=', self.year),
                    ('executing_social_security_id.month', '=', self.month)
                ])
            )
            
            # Obtener las nóminas correspondientes a estos empleados
            payslips_without_ss = payslips.filtered(
                lambda p: p.employee_id.id in employees_without_ss.ids
            )

            result_query = [{
                'identification_id': p.employee_id.identification_id,
                'name_employee': p.employee_id.name,
                'employee_state': 'Activo' if p.employee_id.active else 'Archivado',
                'date_start': p.contract_id.date_start,
                'name_contract': p.contract_id.name,
                'contract_state': p.contract_id.state,
                'retirement_date': p.contract_id.retirement_date or '1900-01-01',
                'payslip_number': p.number,
                'payslip_state': p.state
            } for p in payslips_without_ss]

        else:  
            payslips = self.env['hr.payslip'].search([
                ('date_from', '>=', date_from),
                ('date_to', '<=', date_to),
                ('company_id', '=', self.env.company.id),
                ('state', '!=', 'cancel')
            ])
            
            payslips_without_edi = payslips.filtered(
                lambda p: not self.env['hr.payslip.edi'].search([
                    ('payslip_ids', 'in', p.ids),
                    ('date_from', '>=', date_from),
                    ('date_to', '<=', date_to),
                ])
            )

            result_query = [{
                'identification_id': p.employee_id.identification_id,
                'name_employee': p.employee_id.name,
                'date_start': p.contract_id.date_start,
                'name_contract': p.contract_id.name,
                'contract_state': p.contract_id.state,
                'retirement_date': p.contract_id.retirement_date or '1900-01-01',
                'payslip_number': p.number,
                'payslip_state': p.state
            } for p in payslips_without_edi]

        # Generar EXCEL
        filename = 'Reporte Auditoria'
        stream = io.BytesIO()
        book = xlsxwriter.Workbook(stream, {'in_memory': True})

        # Definir columnas según tipo de reporte
        base_columns = ['Identificación', 'Nombres', 'Estado Empleado', 'Fecha Ingreso', 'Contrato', 
                    'Estado Contrato', 'Fecha de Retiro']
        
        if self.type_process == '1':
            columns = base_columns
        else:
            columns = base_columns + ['Número de Nómina', 'Estado Nómina']

        sheet = book.add_worksheet('Auditoria')

        # Formatos
        formats = {
            'title': book.add_format({
                'bold': True,
                'align': 'left',
                'font_name': 'Calibri',
                'font_size': 15,
                'bottom': 5,
                'bottom_color': '#1F497D',
                'font_color': '#1F497D'
            }),
            'subtitle': book.add_format({
                'bold': True,
                'align': 'left',
                'font_name': 'Calibri',
                'font_size': 10,
                'bottom': 5,
                'bottom_color': '#1F497D',
                'font_color': '#1F497D'
            }),
            'header': book.add_format({
                'bold': True,
                'align': 'center',
                'bg_color': '#1F497D',
                'font_color': 'white',
                'border': 1
            }),
            'date': book.add_format({'num_format': 'dd/mm/yyyy'})
        }

        # Textos del reporte
        dict_type = {
            '1': 'No incluidos en liquidaciones',
            '2': 'No incluidos en seguridad social',
            '3': 'No incluidos en Nómina Electrónica'
        }
        texts = {
            'title': 'Informe de auditoría',
            'type': dict_type.get(self.type_process),
            'period': f'Periodo: {str(self.year)}-{str(self.month)}',
            'generated': f'Informe generado el {datetime.now(timezone(self.env.user.tz))}'
        }
        column_mapping = {
            'Identificación': 'identification_id',
            'Nombres': 'name_employee',
            'Estado Empleado': 'employee_state',
            'Fecha Ingreso': 'date_start',
            'Contrato': 'name_contract',
            'Estado Contrato': 'contract_state',
            'Fecha de Retiro': 'retirement_date',
            'Número de Nómina': 'payslip_number',
            'Estado Nómina': 'payslip_state'
        }
        # Escribir encabezados
        sheet.merge_range('A1:H1', texts['title'], formats['title'])
        sheet.merge_range('A2:H2', texts['type'], formats['title'])
        sheet.merge_range('A3:H3', texts['period'], formats['title'])
        sheet.merge_range('A4:H4', texts['generated'], formats['subtitle'])
        column_widths = {}
        # Escribir columnas
        for col, column in enumerate(columns):
            column_widths[col] = len(column) + 5
            sheet.write(4, col, column, formats['header'])

        # Escribir datos
        row = 5
        if result_query:
            for item in result_query:
                col = 0
                for column in columns:
                    value = item.get(column_mapping.get(column, column))
                    if isinstance(value, (datetime, date)):
                        sheet.write_datetime(row, col, value, formats['date'])
                    else:
                        sheet.write(row, col, value)
                    
                    # Calcular el ancho máximo de la columna
                    if value:
                        width = len(str(value)) + 5
                        # Mantener un registro de los anchos máximos
                        column_widths[col] = max(column_widths.get(col, 0), width)
                    col += 1
                row += 1

            # Aplicar los anchos de columna calculados
            for col, width in column_widths.items():
                sheet.set_column(col, col, width)

            # Convertir en tabla
            sheet.add_table(4, 0, row-1, len(columns)-1, {
                'style': 'Table Style Medium 2',
                'columns': [{'header': col} for col in columns]
            })


        # Guardar Excel
        book.close()

        self.write({
            'excel_file': base64.encodebytes(stream.getvalue()),
            'excel_file_name': filename,
        })

        return {
            'name': 'Reporte Auditoria',
            'type': 'ir.actions.act_url',
            'url': "web/content/?model=hr.auditing.reports&id=" + str(
                self.id) + "&filename_field=excel_file_name&field=excel_file&download=true&filename=" + self.excel_file_name,
            'target': 'self',
        }
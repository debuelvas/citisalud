from odoo import tools
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from pytz import timezone

import base64
import io
import xlsxwriter


class hr_vacation_book(models.TransientModel):
    _name = "hr.vacation.book"
    _description = "Libro de vacaciones"

    final_year = fields.Integer('Año', required=True)
    final_month = fields.Selection([
        ('1', 'Enero'), ('2', 'Febrero'), ('3', 'Marzo'),
        ('4', 'Abril'), ('5', 'Mayo'), ('6', 'Junio'),
        ('7', 'Julio'), ('8', 'Agosto'), ('9', 'Septiembre'),
        ('10', 'Octubre'), ('11', 'Noviembre'), ('12', 'Diciembre')
    ], string='Mes', required=True)
    contract_state = fields.Selection([
        ('draft', 'Borrador'),
        ('open', 'En Proceso'),
        ('close', 'Cerrado'),
        ('cancel', 'Cancelado')
    ], string='Estado del Contrato', required=True)
    employee_ids = fields.Many2many('hr.employee', string='Empleados')
    excel_file = fields.Binary('Excel file')
    excel_file_name = fields.Char('Excel name')

    def dias360(self, start_date, end_date):
        if start_date > end_date:
            return 0
        year_360 = (end_date.year - start_date.year) * 360
        month_360 = (end_date.month - start_date.month) * 30
        day_diff = end_date.day - start_date.day
        return year_360 + month_360 + day_diff

    def generate_excel(self):
        # Configuración de fechas
        date_from = f'{str(self.final_year)}-{str(self.final_month)}-01'
        date_initial = datetime.strptime(date_from, '%Y-%m-%d').date()
        final_year = self.final_year if self.final_month != '12' else self.final_year + 1
        final_month = int(self.final_month) + 1 if self.final_month != '12' else 1
        date_to = f'{str(final_year)}-{str(final_month)}-01'
        date_end = (datetime.strptime(date_to,'%Y-%m-%d') - timedelta(days=1)).date()

        # Dominio de búsqueda
        domain = [('company_id', '=', self.env.company.id)]
        if self.employee_ids:
            domain.append(('employee_id', 'in', self.employee_ids.ids))
        if self.contract_state:
            domain.append(('state', '=', self.contract_state))

        contracts = self.env['hr.contract'].search(domain)
        
        filename = 'Reporte_Vacaciones.xlsx'
        stream = io.BytesIO()
        book = xlsxwriter.Workbook(stream, {'in_memory': True})

        # Formatos
        title_format = book.add_format({
            'bold': True,
            'font_size': 14,
            'font_color': '#1F497D',
            'align': 'left'
        })
        subtitle_format = book.add_format({
            'bold': True,
            'font_size': 12,
            'font_color': '#1F497D',
            'align': 'left'
        })
        header_format = book.add_format({
            'bold': True, 
            'align': 'center',
            'valign': 'vcenter',
            'bg_color': '#1F497D',
            'font_color': 'white'
        })
        date_format = book.add_format({'num_format': 'dd/mm/yyyy'})
        number_format = book.add_format({'num_format': '#,##0.00'})

        sheet = book.add_worksheet('Resumen Vacaciones')

        # Encabezado del reporte
        sheet.merge_range('A1:O1', self.env.company.name, title_format)
        sheet.merge_range('A2:O2', f'Libro de Vacaciones - Corte: {date_end.strftime("%d/%m/%Y")}', title_format)
        sheet.merge_range('A3:O3', f'Generado por: {self.env.user.name}', subtitle_format)
        sheet.merge_range('A4:O4', f'Fecha generación: {fields.Datetime.now().strftime("%d/%m/%Y %H:%M:%S")}', subtitle_format)

        # Estadísticas
        total_employees = len(contracts)
        total_vacation_days = 0
        total_pending_days = 0
        total_value = 0
        
        # Cálculo de totales
        for contract in contracts:
            vacations = self.env['hr.vacation'].search([
                ('employee_id', '=', contract.employee_id.id),
                ('contract_id', '=', contract.id),
                ('departure_date', '<=', date_end)
            ])
            total_vacation_days += sum(v.business_units + v.holiday_units + v.units_of_money for v in vacations)
            total_value += sum(v.value_business_days + v.holiday_value + v.money_value for v in vacations)
            days_worked = self.dias360(contract.date_start, date_end)
            earned_days = (days_worked * 15) / 360
            total_pending_days += earned_days - total_vacation_days

        sheet.merge_range('A5:O5', f'Resumen General:', title_format)
        sheet.write(5, 0, f'Total Empleados: {total_employees}', subtitle_format)
        sheet.write(6, 0, f'Total Días Vacaciones Usados: {total_vacation_days:.2f}', subtitle_format)
        sheet.write(7, 0, f'Total Días Pendientes: {total_pending_days:.2f}', subtitle_format)
        sheet.write(7, 5, f'Valor Total: ${total_value:,.2f}', subtitle_format)

        # Encabezados de datos
        headers = [
            'Identificación', 'Empleado', 'Estado Contrato', 'Fecha Ingreso', 
            'Días Trabajados', 'Días Inasistencia', 'Días Ganados', 'Días Hábiles', 
            'Días Festivos', 'Días en Dinero', 'Días Pendientes', 
            'Valor Días Hábiles', 'Valor Días Festivos', 'Valor en Dinero', 'Total'
        ]
        
        row = 9
        for col, header in enumerate(headers):
            sheet.write(row, col, header, header_format)
            sheet.set_column(col, col, 15)

        row += 1
        for contract in contracts:
            days_worked = self.dias360(contract.date_start, date_end)
            
            # Cálculo de inasistencias
            absences = self.env['hr.leave'].search([
                ('employee_id', '=', contract.employee_id.id),
                ('date_from', '>=', contract.date_start),
                ('date_to', '<=', date_end),
                ('state', '=', 'validate'),
                ('holiday_status_id.unpaid_absences', '=', True)
            ])
            
            total_absences = sum(self.dias360(leave.date_from, leave.date_to) for leave in absences)
            
            # Cálculo de vacaciones
            vacations = self.env['hr.vacation'].search([
                ('employee_id', '=', contract.employee_id.id),
                ('contract_id', '=', contract.id),
                ('departure_date', '<=', date_end)
            ])

            total_money_days = sum(v.units_of_money for v in vacations)
            total_business_days = sum(v.business_units for v in vacations)
            total_holiday_days = sum(v.holiday_units for v in vacations)
            money_value = sum(v.money_value for v in vacations)
            business_value = sum(v.value_business_days for v in vacations)
            holiday_value = sum(v.holiday_value for v in vacations)

            earned_days = ((days_worked - total_absences) * 15) / 360
            remaining_days = earned_days - (total_money_days + total_business_days + total_holiday_days)

            sheet.write(row, 0, contract.employee_id.identification_id)
            sheet.write(row, 1, contract.employee_id.name)
            sheet.write(row, 2, dict(contract._fields['state'].selection).get(contract.state))
            sheet.write_datetime(row, 3, contract.date_start, date_format)
            sheet.write(row, 4, days_worked, number_format)
            sheet.write(row, 5, total_absences, number_format)
            sheet.write(row, 6, earned_days, number_format)
            sheet.write(row, 7, total_business_days, number_format)
            sheet.write(row, 8, total_holiday_days, number_format)
            sheet.write(row, 9, total_money_days, number_format)
            sheet.write(row, 10, remaining_days, number_format)
            sheet.write(row, 11, business_value, number_format)
            sheet.write(row, 12, holiday_value, number_format)
            sheet.write(row, 13, money_value, number_format)
            sheet.write(row, 14, business_value + holiday_value + money_value, number_format)
            row += 1

        # Totales
        sheet.write(row, 0, 'Totales', header_format)
        for col in range(4, 15):
            sheet.write(row, col, f'=SUM({chr(65+col)}{11}:{chr(65+col)}{row})', number_format)

        book.close()

        self.write({
            'excel_file': base64.b64encode(stream.getvalue()).decode('utf-8'),
            'excel_file_name': filename,
        })

        action = {
            'name': 'Reporte de Vacaciones',
            'type': 'ir.actions.act_url',
            'url': "web/content/?model=hr.vacation.book&id=" + str(self.id) + 
                   "&filename_field=excel_file_name&field=excel_file&download=true&filename=" + self.excel_file_name,
            'target': 'self',
        }
        return action
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from datetime import datetime
from pytz import timezone

import base64
import io
import xlsxwriter

class hr_salary_history_report(models.TransientModel):
    _name = "hr.salary.history.report"
    _description = "Reporte histórico salarial"

    date_start = fields.Date('Fecha de Inicio')
    date_end = fields.Date('Fecha de Fin')
    employee = fields.Many2many('hr.employee', string='Empleado')
    branch = fields.Many2many('lavish.res.branch', string='Sucursal',
                              domain=lambda self: [('id', 'in', self.env.user.branch_ids.ids)])
    contract_active = fields.Boolean(string='Solo contratos activos', default=True)

    excel_file = fields.Binary('Excel')
    excel_file_name = fields.Char('Excel filename')

    def generate_excel(self):
        query_where = ''

        # Filtro de compañia
        query_where = query_where + f"where b.company_id = {self.env.company.id} "
        #Filtro fchas
        if self.date_start:
            query_where = query_where + f"and d.date_start >= '{str(self.date_start)}' "
        if self.date_end:
            query_where = query_where + f"and d.date_start <= '{str(self.date_end)}' "
        # Filtro Empleado
        str_ids_employee = ''
        for i in self.employee:
            str_ids_employee = str(i.id) if str_ids_employee == '' else str_ids_employee + ',' + str(i.id)
        if str_ids_employee != '':
            query_where = query_where + f"and b.id in ({str_ids_employee}) "
        # Filtro Sucursal
        str_ids_branch = ''
        for i in self.branch:
            str_ids_branch = str(i.id) if str_ids_branch == '' else str_ids_branch + ',' + str(i.id)
        if str_ids_branch == '' and len(self.env.user.branch_ids.ids) > 0:
            for i in self.env.user.branch_ids.ids:
                str_ids_branch = str(i) if str_ids_branch == '' else str_ids_branch + ',' + str(i)
        if str_ids_branch != '':
            query_where = query_where + f"and e.id in ({str_ids_branch}) "
        #Filtro contratos activos
        if self.contract_active == True:
            query_where = query_where + f"and a.state = 'open' "
        # ----------------------------------Ejecutar consulta
        query_report = f'''
                        select coalesce(a."sequence",'/') ||' - '|| a."name" as contrato, a.date_start as fecha_ingreso, 
                                case when a.state = 'open' then 'En Proceso' else 'Inactivo' end as estado_contrato,
                                b."name" as empleado,c."name" as compania, coalesce(e."name",'') as sucursal,
                                coalesce(d.date_start,'1900-01-01') as fecha_inicio_salario_cargo, coalesce(d.wage,0) as salario, coalesce(f."name",'') as cargo
                        from hr_contract as a
                        inner join hr_employee as b on a.employee_id = b.id
                        inner join res_company as c on b.company_id = c.id
                        left join hr_contract_change_wage as d on a.id =d.contract_id 
                        left join lavish_res_branch as e on b.branch_id = e.id
                        left join hr_job as f on d.job_id = f.id
                        %s
                        order by b."name",d.date_start 
        ''' % query_where

        self._cr.execute(query_report)
        result_query = self._cr.dictfetchall()

        # Generar EXCEL
        filename = 'Reporte histórico salarial'
        stream = io.BytesIO()
        book = xlsxwriter.Workbook(stream, {'in_memory': True})

        # Columnas
        columns = ['Contrato', 'Fecha Ingreso', 'Estado Contrato', 'Empleado', 'Compañia', 'Sucursal' , 'Fecha Inicio Salario/Cargo','Salario', 'Cargo']
        sheet = book.add_worksheet('Historico salarial')

        # Agregar textos al excel
        text_title = 'Histórico salarial'
        text_generate = 'Informe generado el %s' % (datetime.now(timezone(self.env.user.tz)))
        cell_format_title = book.add_format({'bold': True, 'align': 'left'})
        cell_format_title.set_font_name('Calibri')
        cell_format_title.set_font_size(15)
        cell_format_title.set_bottom(5)
        cell_format_title.set_bottom_color('#1F497D')
        cell_format_title.set_font_color('#1F497D')
        sheet.merge_range('A1:I1', text_title, cell_format_title)
        cell_format_text_generate = book.add_format({'bold': False, 'align': 'left'})
        cell_format_text_generate.set_font_name('Calibri')
        cell_format_text_generate.set_font_size(10)
        cell_format_text_generate.set_bottom(5)
        cell_format_text_generate.set_bottom_color('#1F497D')
        cell_format_text_generate.set_font_color('#1F497D')
        sheet.merge_range('A2:H2', text_generate, cell_format_text_generate)
        # Formato para fechas
        date_format = book.add_format({'num_format': 'dd/mm/yyyy'})

        # Agregar columnas
        aument_columns = 0
        for column in columns:
            sheet.write(2, aument_columns, column)
            aument_columns = aument_columns + 1

            # Agregar query
            aument_columns = 0
            aument_rows = 3
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

            sheet.add_table(2, 0, aument_rows-1, len(columns)-1, {'style': 'Table Style Medium 2', 'columns': array_header_table})
            # Guadar Excel
            book.close()

            self.write({
                'excel_file': base64.b64encode(stream.getvalue()).decode('utf-8'),
                'excel_file_name': filename,
            })

            action = {
                'name': 'Reporte histórico salarial',
                'type': 'ir.actions.act_url',
                'url': "web/content/?model=hr.salary.history.report&id=" + str(
                    self.id) + "&filename_field=excel_file_name&field=excel_file&download=true&filename=" + self.excel_file_name,
                'target': 'self',
            }
            return action

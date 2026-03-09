from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from datetime import datetime
from pytz import timezone

import base64
import io
import xlsxwriter
import logging
_logger = logging.getLogger(__name__)
class hr_birthday_list(models.TransientModel):
    _name = "hr.birthday.list"
    _description = "Listado de cumpleaños"

    branch = fields.Many2many('lavish.res.branch', string='Sucursal')
    company = fields.Many2many('res.company',string='Compañías', required=True, default=lambda self: self.env.company.ids)
    month = fields.Selection([('0', 'Todos'),
                            ('1', 'Enero'),
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

    excel_file = fields.Binary('Excel')
    excel_file_name = fields.Char('Excel filename')
    show_dependent = fields.Boolean(string='Mostrar dependientes')
    active_employee = fields.Boolean(string='Solo empleados con contrato activo', default=True)

    def name_get(self):
        result = []
        for record in self:            
            result.append((record.id, "Listado de cumpleaños"))
        return result

    def get_month(self):
        if self.month == '0':
            month = [1,2,3,4,5,6,7,8,9,10,11,12]
        else: 
            month = [int(self.month)]
        return month

    def get_info_birthday(self,month):
        domain = [('birthday','!=',False)]
        if len(self.company) > 0:
            domain.append(('company_id','in',self.company.ids))
        if len(self.branch) > 0:
            domain.append(('branch_id','in',self.branch.ids))
        obj_employee = self.env['hr.employee'].search(domain).filtered(lambda x: x.birthday.month == int(month))
        return obj_employee

    def get_name_month(self,month_number):
        #Mes
        month = ''
        month = 'Enero' if month_number == 1 else month
        month = 'Febrero' if month_number == 2 else month
        month = 'Marzo' if month_number == 3 else month
        month = 'Abril' if month_number == 4 else month
        month = 'Mayo' if month_number == 5 else month
        month = 'Junio' if month_number == 6 else month
        month = 'Julio' if month_number == 7 else month
        month = 'Agosto' if month_number == 8 else month
        month = 'Septiembre' if month_number == 9 else month
        month = 'Octubre' if month_number == 10 else month
        month = 'Noviembre' if month_number == 11 else month
        month = 'Diciembre' if month_number == 12 else month

        return month

    def get_date_text(self,date,calculated_week=0,hide_year=0):
        #Mes
        month = self.get_name_month(date.month)
        #Dia de la semana
        week = ''
        week = 'Lunes' if date.weekday() == 0 else week
        week = 'Martes' if date.weekday() == 1 else week
        week = 'Miercoles' if date.weekday() == 2 else week
        week = 'Jueves' if date.weekday() == 3 else week
        week = 'Viernes' if date.weekday() == 4 else week
        week = 'Sábado' if date.weekday() == 5 else week
        week = 'Domingo' if date.weekday() == 6 else week

        if hide_year == 0:
            if calculated_week == 0:
                date_text = date.strftime('%d de '+month+' del %Y')
            else:
                date_text = date.strftime(week+', %d de '+month+' del %Y')
        else:
            if calculated_week == 0:
                date_text = date.strftime('%d de '+month)
            else:
                date_text = date.strftime(week+', %d de '+month)

        return date_text

    def generate_report(self):
        datas = {
             'id': self.id,
             'model': 'hr.birthday.list'             
            }

        return {
            'type': 'ir.actions.report',
            'report_name': 'lavish_hr_employee.report_birthday_list',
            'report_type': 'qweb-pdf',
            'datas': datas        
        }      
    def build_query(self):
        # Inicializando filtros
        filters = []
        filters_dependent = []

        if self.month != '0':
            month_filter = f"date_part('month',a.birthday) = {self.month}"
            month_filter_dependent = f"date_part('month',hed.date_birthday) = {self.month}"
            filters.append(month_filter)
            filters_dependent.append(month_filter_dependent)

        company_filter = f"a.company_id in ({','.join(map(str, self.company.ids))})"
        filters.append(company_filter)
        filters_dependent.append(company_filter)

        if self.branch:
            branch_filter = f"zrb.id in ({','.join(map(str, self.branch.ids))})"
            filters.append(branch_filter)
            filters_dependent.append(branch_filter)
        if not self.show_dependent:
            filters.append("1=2")

        # Construyendo la consulta
        active_employee_join = f"Inner join hr_contract as hc on a.id = hc.employee_id and hc.state='open'" if self.active_employee else ''
        where_clause = " AND ".join(filters)
        where_clause_dependent = " AND ".join(filters_dependent)

        query_report = f'''
            SELECT * FROM (
                SELECT c.name, b.vat, b.name as name_employee, '' as name_dependet, '' as dependents_type,
                    zrb."name" as branch, a.birthday, date_part('year',age(a.birthday)) as edad
                FROM hr_employee as a
                {active_employee_join}
                LEFT JOIN res_partner as b ON b.id = a.work_contact_id
                LEFT JOIN res_company c ON c.id = a.company_id 
                LEFT JOIN lavish_res_branch as zrb ON a.branch_id = zrb.id
                WHERE {where_clause}
                AND EXISTS (SELECT 1 FROM hr_contract hc WHERE a.id = hc.employee_id AND hc.state='open')
                UNION                    
                SELECT c."name", '' as vat, b.name as name_employee, hed.name as name_dependet,
                    upper(hed.dependents_type) as dependents_type, zrb."name" as branch,
                    hed.date_birthday, date_part('year',age(hed.date_birthday)) as edad
                FROM hr_employee as a
                {active_employee_join}
                LEFT JOIN hr_employee_dependents hed ON a.id = hed.employee_id
                LEFT JOIN res_partner as b ON b.id = a.work_contact_id
                LEFT JOIN res_company c ON c.id = a.company_id 
                LEFT JOIN lavish_res_branch as zrb ON a.branch_id = zrb.id
                WHERE {where_clause_dependent}
                AND EXISTS (SELECT 1 FROM hr_contract hc WHERE a.id = hc.employee_id AND hc.state='open')
            ) as a
            ORDER BY name_employee, date_part('month',birthday), date_part('day',birthday)
        '''
        return query_report
    def generate_birthday_excel(self):
        # Luego, para ejecutar:
        query = self.build_query()
        _logger.info(query)
        self._cr.execute(query)
        result_query = self._cr.dictfetchall()
        _logger.info(result_query)
        if len(result_query) == 0:
            raise ValidationError(_('No se encontraron datos con los filtros seleccionados, por favor verificar.'))
        # Generar EXCEL
        filename = 'Reporte Listado de Cumpleaños'
        stream = io.BytesIO()
        book = xlsxwriter.Workbook(stream, {'in_memory': True})

        # Columnas
        columns = ['Compañia', 'Identificación', 'Empleado', 'Dependiente', 'Tipo dependiente', 'Sucursal','Fecha de cumpleaños', 'Edad']
        sheet = book.add_worksheet('Listado de Cumpleaños')

        # Agregar textos al excel
        text_title = 'Listado de Cumpleaños'
        text_generate = 'Informe generado el %s' % (datetime.now(timezone(self.env.user.tz)))
        cell_format_title = book.add_format({'bold': True, 'align': 'left'})
        cell_format_title.set_font_name('Calibri')
        cell_format_title.set_font_size(15)
        cell_format_title.set_bottom(5)
        cell_format_title.set_bottom_color('#1F497D')
        cell_format_title.set_font_color('#1F497D')
        sheet.merge_range('A1:H1', text_title, cell_format_title)
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
                width = 40 if width == 10 else width
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
            'name': 'Listado de Cumpleaños',
            'type': 'ir.actions.act_url',
            'url': "web/content/?model=hr.birthday.list&id=" + str(
                self.id) + "&filename_field=excel_file_name&field=excel_file&download=true&filename=" + self.excel_file_name,
            'target': 'self',
        }
        return action
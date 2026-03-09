from odoo import tools
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

import base64
import io
import xlsxwriter


class hr_consolidated_reports(models.TransientModel):
    _name = 'hr.consolidated.reports'
    _description = 'Reportes Consolidados'

    year = fields.Integer(string='Año', required=True)
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
    company_id = fields.Many2one('res.company', string='Compañia', required=True, default=lambda self: self.env.company)
    employee = fields.Many2many('hr.employee', string='Empleado')
    branch = fields.Many2many('lavish.res.branch', string='Sucursal',
                              domain=lambda self: [('id', 'in', self.env.user.branch_ids.ids)])
    analytic_account = fields.Many2many('account.analytic.account', string='Cuenta Analítica')
    type_of_consolidation = fields.Selection([('cesantias', 'Cesantías'),
                                              ('prima', 'Prima'),
                                              ('vacaciones', 'Vacaciones')
                                              ], string='Tipo de consolidado', required=True, default='cesantias')

    excel_file = fields.Binary('Excel')
    excel_file_name = fields.Char('Excel filename')

    def create_closing_date(self):
        date_from = f'{str(self.year)}-{str(self.month)}-01'
        date_from = datetime.strptime(date_from, '%Y-%m-%d')

        date_to = date_from + relativedelta(months=1)
        date_to = date_to - timedelta(days=1)

        return date_to.date()

    def create_initial_month_date(self):
        date_from = f'{str(self.year)}-{str(self.month)}-01'
        date_from = datetime.strptime(date_from, '%Y-%m-%d')

        return date_from.date()

    def create_date_initial_process(self):
        date_from = f'{str(self.year)}-01-01'
        date_from = datetime.strptime(date_from, '%Y-%m-%d')
        return date_from.date()

    def query_filter_period(self,and_or_where,field,initial_month=0,custom_compare=''):
        filter_period = ''
        date_filter = str(self.create_closing_date()) if initial_month == 0 else str(self.create_initial_month_date())
        if custom_compare != '':
            comparation_symbol = custom_compare
        else:
            comparation_symbol = '<=' if initial_month == 0 else '>='
        filter_period = f" {and_or_where} {field} {comparation_symbol} '{date_filter}' "
        return filter_period

    def query_where_filters(self):
        query_where = ''
        # Filtro compañia
        query_where = f"where a.company_id = '{self.company_id.id}' "
        # Filtro Empleado
        str_ids_employee = ''
        for i in self.employee:
            str_ids_employee = str(i.id) if str_ids_employee == '' else str_ids_employee + ',' + str(i.id)
        if str_ids_employee != '':
            query_where = query_where + f"and a.id in ({str_ids_employee}) "
        # Filtro Sucursal
        str_ids_branch = ''
        for i in self.branch:
            str_ids_branch = str(i.id) if str_ids_branch == '' else str_ids_branch + ',' + str(i.id)
        if str_ids_branch == '' and len(self.env.user.branch_ids.ids) > 0:
            for i in self.env.user.branch_ids.ids:
                str_ids_branch = str(i) if str_ids_branch == '' else str_ids_branch + ',' + str(i)
        if str_ids_branch != '':
            query_where = query_where + f"and rb.id in ({str_ids_branch}) "
        # Filtro Cuenta analitica
        str_ids_analytic = ''
        for i in self.analytic_account:
            str_ids_analytic = str(i.id) if str_ids_analytic == '' else str_ids_analytic + ',' + str(i.id)
        if str_ids_analytic != '':
            query_where = query_where + f"and aaa.id in ({str_ids_analytic}) "

        return query_where

    # Reporte Consolidado de Vacaciones
    def generate_excel_vacaciones(self):
        # ----------------------------------Ejecutar consulta
        query_report = f'''
                select distinct a."name",a.identification_id, b.date_start, 0 as days_service, coalesce(c.days_unpaid_absences,0)+coalesce(d.days_unpaid_absences,0) as days_unpaid_absences,
                            0 as days_service_real,0 as vacation_days_right,coalesce(e.days_vacations,0) as vacation_days_paid,0 as vacations_days_pending,
                            coalesce(f.amount,0) as total_provision,coalesce(f.value_payments,0) as pagos_realizados,coalesce(f.current_payable_value,0) as valor_pagar_actual,
                            coalesce(g.amount,0) as valor_provision_acumulada,coalesce(f.value_balance,0) as valor_provision_mes,            
                            coalesce(h.final_accrual_date,'1900-01-01') as final_accrual_date,
                            coalesce(i.total,0) as total_vacations_last,coalesce(i.departure_date,'1900-01-01') as departure_date_last,
                            coalesce(i.return_date,'1900-01-01') as return_date_last,coalesce(i.days,0) as days_last
                from hr_employee as a
                inner join hr_contract as b on a.id = b.employee_id and b.active = true {self.query_filter_period('and','b.date_start')}
                                                and (b.state = 'open' or (({self.query_filter_period('','b.retirement_date',1)} {self.query_filter_period('and','b.retirement_date')}) or ({self.query_filter_period('','b.retirement_date',0,'>=')})))                                                
                left join lavish_res_branch as rb on a.branch_id = rb.id
                left join account_analytic_account as aaa on b.analytic_account_id = aaa.id 
                left join (select a.employee_id,sum(a.days) as days_unpaid_absences 
                            from hr_absence_history as a
                            inner join hr_leave_type as b on a.leave_type_id = b.id and b.unpaid_absences = true
                            {self.query_filter_period('where','a.end_date')}
                            group by a.employee_id) as c on a.id = c.employee_id
                left join (select a.employee_id,sum(a.number_of_days) as days_unpaid_absences 
                            from hr_leave as a
                            inner join hr_leave_type as b on a.holiday_status_id = b.id and b.unpaid_absences = true
                            where a.state = 'validate' {self.query_filter_period('and','a.request_date_to')}
                            group by a.employee_id) as d on a.id = d.employee_id
                left join (select a.employee_id,a.contract_id,sum(coalesce(a.business_units,0))+sum(coalesce(units_of_money,0)) as days_vacations 
                            from hr_vacation as a		
                            {self.query_filter_period('where','a.return_date')}	
                            group by a.employee_id,a.contract_id) as e on a.id = e.employee_id and b.id = e.contract_id
                left join (select a.*
                            from hr_executing_provisions_details as a 
                            inner join hr_executing_provisions as b on a.executing_provisions_id = b.id 
                                        and b."year" = '{str(self.year)}' and b."month" = '{str(self.month)}'
                            where a.provision = 'vacaciones'
                            ) as f on a.id = f.employee_id
                left join (select a.*
                            from hr_executing_provisions_details as a 
                            inner join hr_executing_provisions as b on a.executing_provisions_id = b.id 
                                        and b."year" = '{str(self.year) if str(self.month) != '1' else str(self.year-1)}' 
                                        and b."month" = '{str(int(self.month)-1) if str(self.month) != '1' else '12'}'
                            where a.provision = 'vacaciones'
                            ) as g on a.id = g.employee_id
                left join (select employee_id,contract_id,max(final_accrual_date) as final_accrual_date 
                            from hr_vacation as a 
                            {self.query_filter_period('where','a.return_date')}
                            group by employee_id,contract_id                            
                            ) as h on a.id = h.employee_id and b.id = h.contract_id
                left join (select employee_id,contract_id,final_accrual_date,departure_date,return_date,sum(total) as total,
                            sum(coalesce(business_units,0))+sum(coalesce(units_of_money,0)) as days 
                            from hr_vacation as a
                            {self.query_filter_period('where','a.return_date')}
                            group by employee_id,contract_id,
                            final_accrual_date,departure_date,return_date) as i on a.id = i.employee_id and b.id = i.contract_id and h.final_accrual_date = i.final_accrual_date
                {self.query_where_filters()}      
            '''

        self._cr.execute(query_report)
        result_query = self._cr.dictfetchall()

        # Generar EXCEL
        filename = 'Reporte Consolidados de Vacaciones'
        stream = io.BytesIO()
        book = xlsxwriter.Workbook(stream, {'in_memory': True})

        # Columnas
        columns = ['Nombres', 'Identificación', 'Fecha Ingreso', 'Días Servicio', 'Ausencias no Remunerdas',
                   'Días Servicio Neto','Días Vacaciones Derecho', 'Días Vacaciones Pagados', 'Días Vacaciones Pendientes',
                   'Total Provisión','Pagos del Mes','Valor a Pagar Actual','Valor Provisión Acumulada','Valor Provisión Mes',
                   'Fecha Vacaciones Pagados Hasta', 'Valor Liquidado', 'Fecha Inicio Vacaciones',
                   'Fecha Fin Vacaciones', 'Días de Vacaciones']
        sheet = book.add_worksheet('Consolidados de Vacaciones')

        # Agregar textos al excel
        text_company = self.company_id.name
        text_title = 'Consolidados de Vacaciones'
        text_dates = f'Corte {str(self.create_closing_date())}'
        cell_format_title = book.add_format({'bold': True, 'align': 'center'})
        cell_format_title.set_font_name('Calibri')
        cell_format_title.set_font_size(15)
        cell_format_title.set_bottom(5)
        cell_format_title.set_bottom_color('#1F497D')
        cell_format_title.set_font_color('#1F497D')
        sheet.merge_range('A1:S1', text_company, cell_format_title)
        sheet.merge_range('A2:S2', text_title, cell_format_title)
        sheet.merge_range('A3:S3', text_dates, cell_format_title)
        #Formato para fechas
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
            date_start = ''
            days_unpaid_absences = 0
            days_paid = 0
            days_service = 0
            days_vacations_total = 0
            for row in query.values():
                width = len(str(row)) + 10
                #La columna 2 es Fecha Ingreso por ende se guarda su valor en la variable date_start
                date_start = row if aument_columns == 2 else date_start
                # La columna 4 es días ausencias no remunedaras por ende se guarda su valor en la variable days_unpaid_absences
                days_unpaid_absences = row if aument_columns == 4 else days_unpaid_absences
                # La columna 7 es días vacaciones pagados por ende se guarda su valor en la variable days_paid
                days_paid = row if aument_columns == 7 else days_paid
                #La columna 3,5,6 y 8 se debe realizar un calculo y no tomarlo directamente de la consulta
                if aument_columns not in [3,5,6,8]:
                    if str(type(row)).find('date') > -1:
                        sheet.write_datetime(aument_rows, aument_columns, row, date_format)
                    else:
                        sheet.write(aument_rows, aument_columns, row)
                else:
                    if aument_columns == 3: # Dias Servicio
                        days_service = self.dias360(date_start,self.create_closing_date())
                        sheet.write(aument_rows, aument_columns, days_service)
                    elif aument_columns == 5: # Dias Servicio Neto
                        sheet.write(aument_rows, aument_columns,(days_service-days_unpaid_absences))
                    elif aument_columns == 6:
                        days_vacations_total = ((days_service-days_unpaid_absences)*15)/360
                        sheet.write(aument_rows, aument_columns,days_vacations_total)
                    elif aument_columns == 8:
                        sheet.write(aument_rows, aument_columns,(days_vacations_total-days_paid))
                #Ajustar tamaño columna
                sheet.set_column(aument_columns, aument_columns, width)

                aument_columns = aument_columns + 1
            aument_rows = aument_rows + 1
            aument_columns = 0

        # Convertir en tabla
        array_header_table = []
        for i in columns:
            dict = {'header': i}
            array_header_table.append(dict)

        sheet.add_table(3, 0, aument_rows-1, len(columns)-1, {'style': 'Table Style Medium 2', 'columns': array_header_table})
        # Guadar Excel
        book.close()

        self.write({
            'excel_file': base64.encodebytes(stream.getvalue()),
            'excel_file_name': filename,
        })

        action = {
            'name': 'Reporte Consolidados de Vacaciones',
            'type': 'ir.actions.act_url',
            'url': "web/content/?model=hr.consolidated.reports&id=" + str(
                self.id) + "&filename_field=excel_file_name&field=excel_file&download=true&filename=" + self.excel_file_name,
            'target': 'self',
        }
        return action

    # Reporte Consolidado de cesantías
    def generate_excel_cesantias(self):

        # ----------------------------------Ejecutar consulta
        query_report = f'''
                select distinct a."name",a.identification_id,b.date_start,
                    case when b.date_start >= '{str(self.create_date_initial_process())}' then b.date_start else '{str(self.create_date_initial_process())}' end as date_initial_process,
                    0 as days_service,coalesce(c.days_unpaid_absences,0)+coalesce(d.days_unpaid_absences,0) as days_unpaid_absences,0 as days_real,
                    coalesce(f.value_wage,0) as value_wage,coalesce(f.value_base,0) as value_base,coalesce(f.amount,0) as amount,
                    coalesce(h.amount,0) as intamount,coalesce(pf.value_payments,0) as value_payments,coalesce(ph.value_payments,0) as intvalue_payments,
                    coalesce(f.current_payable_value,0) as current_payable_value,coalesce(h.current_payable_value,0) as intcurrent_payable_value
                from hr_employee as a
                inner join hr_contract as b on a.id = b.employee_id and b.active = true {self.query_filter_period('and','b.date_start')}
                                                and (b.state = 'open' or (({self.query_filter_period('','b.retirement_date',1)} {self.query_filter_period('and','b.retirement_date')}) or ({self.query_filter_period('','b.retirement_date',0,'>=')})))
                left join lavish_res_branch as rb on a.branch_id = rb.id
                left join account_analytic_account as aaa on b.analytic_account_id = aaa.id 
                left join (select a.employee_id,sum(a.days) as days_unpaid_absences 
                            from hr_absence_history as a
                            inner join hr_leave_type as b on a.leave_type_id = b.id and b.unpaid_absences = true
                            where a.star_date <= '{str(self.create_closing_date())}' and a.end_date >= '{str(self.create_date_initial_process())}'
                            group by a.employee_id) as c on a.id = c.employee_id
                left join (select a.employee_id,sum(a.number_of_days) as days_unpaid_absences 
                            from hr_leave as a
                            inner join hr_leave_type as b on a.holiday_status_id = b.id and b.unpaid_absences = true
                            where a.state = 'validate' and a.request_date_from <= '{str(self.create_closing_date())}' and a.request_date_to >= '{str(self.create_date_initial_process())}' 
                            group by a.employee_id) as d on a.id = d.employee_id
                left join (select a.employee_id,a.contract_id,max(a.id) as max_id 
                            from hr_executing_provisions_details as a
                            inner join hr_executing_provisions as b on a.executing_provisions_id = b.id {self.query_filter_period('and','b.date_end')}
                            where a.provision = 'cesantias'
                            group by a.employee_id,a.contract_id) as e on a.id = e.employee_id and b.id = e.contract_id
                left join hr_executing_provisions_details as f on e.max_id = f.id 
                left join (select a.employee_id,a.contract_id,sum(coalesce(a.value_payments,0)) as value_payments 
                            from hr_executing_provisions_details as a 
                            inner join hr_executing_provisions as b on a.executing_provisions_id = b.id {self.query_filter_period('and','b.date_end')}
                            where a.provision = 'cesantias'
                            group by a.employee_id,a.contract_id) as pf on a.id = pf.employee_id and b.id = pf.contract_id	
                left join (select a.employee_id,a.contract_id,max(a.id) as max_id 
                            from hr_executing_provisions_details as a
                            inner join hr_executing_provisions as b on a.executing_provisions_id = b.id {self.query_filter_period('and','b.date_end')}
                            where a.provision = 'intcesantias'
                            group by a.employee_id,a.contract_id) as g on a.id = g.employee_id and b.id = g.contract_id
                left join hr_executing_provisions_details as h on g.max_id = h.id
                left join (select a.employee_id,a.contract_id,sum(coalesce(a.value_payments,0)) as value_payments 
                            from hr_executing_provisions_details  as a
                            inner join hr_executing_provisions as b on a.executing_provisions_id = b.id {self.query_filter_period('and','b.date_end')}
                            where a.provision = 'intcesantias'
                            group by a.employee_id,a.contract_id) as ph on a.id = ph.employee_id and b.id = ph.contract_id               
                {self.query_where_filters()}   
            '''

        self._cr.execute(query_report)
        result_query = self._cr.dictfetchall()

        # Generar EXCEL
        filename = 'Reporte Consolidados de Cesantías'
        stream = io.BytesIO()
        book = xlsxwriter.Workbook(stream, {'in_memory': True})

        # Columnas
        columns = ['Nombres', 'Identificación', 'Fecha Ingreso', 'Fecha inicial de causación','Días Servicio', 'Ausencias no Remunerdas',
                   'Días Servicio Neto', 'Salario Básico', 'Base de Cesantías', 'Valor Cesantías Acumulado',
                   'Valor Intereses Cesantías Acumulados', 'Pagos Acumulados Cesantías', 'Pagos Acumulados Intereses',
                   'Neto a Pagar Cesantias Año Actual', 'Neto a Pagar Intereses  las Cesantias Año Actual']
        sheet = book.add_worksheet('Consolidados de cesantias')

        # Agregar textos al excel
        text_company = self.company_id.name
        text_title = 'Consolidados de Cesantías'
        text_dates = f'Corte {str(self.create_closing_date())}'
        cell_format_title = book.add_format({'bold': True, 'align': 'center'})
        cell_format_title.set_font_name('Calibri')
        cell_format_title.set_font_size(15)
        cell_format_title.set_bottom(5)
        cell_format_title.set_bottom_color('#1F497D')
        cell_format_title.set_font_color('#1F497D')
        sheet.merge_range('A1:O1', text_company, cell_format_title)
        sheet.merge_range('A2:O2', text_title, cell_format_title)
        sheet.merge_range('A3:O3', text_dates, cell_format_title)
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
            date_start = ''
            date_initial_process = ''
            days_unpaid_absences = 0
            days_service = 0
            for row in query.values():
                width = len(str(row)) + 10
                # La columna 2 es Fecha Ingreso por ende se guarda su valor en la variable date_start
                date_start = row if aument_columns == 2 else date_start
                date_initial_process = row if aument_columns == 3 else date_initial_process
                # La columna 5 es días ausencias no remunedaras por ende se guarda su valor en la variable days_unpaid_absences
                days_unpaid_absences = row if aument_columns == 5 else days_unpaid_absences
                # La columna 4 y 6 se debe realizar un calculo y no tomarlo directamente de la consulta
                if aument_columns not in [4, 6]:
                    if str(type(row)).find('date') > -1:
                        sheet.write_datetime(aument_rows, aument_columns, row, date_format)
                    else:
                        sheet.write(aument_rows, aument_columns, row)
                else:
                    if aument_columns == 4:  # Dias Servicio
                        days_service = self.dias360(date_initial_process, self.create_closing_date())
                        sheet.write(aument_rows, aument_columns, days_service)
                    elif aument_columns == 6:  # Dias Servicio Neto
                        sheet.write(aument_rows, aument_columns, (days_service - days_unpaid_absences))
                # Ajustar tamaño columna
                sheet.set_column(aument_columns, aument_columns, width)

                aument_columns = aument_columns + 1
            aument_rows = aument_rows + 1
            aument_columns = 0
        #Convertir en tabla
        array_header_table = []
        for i in columns:
            dict = {'header': i}
            array_header_table.append(dict)

        sheet.add_table(3,0,aument_rows-1,len(columns)-1,{'style': 'Table Style Medium 2','columns': array_header_table})
        # Guadar Excel
        book.close()

        self.write({
            'excel_file': base64.encodebytes(stream.getvalue()),
            'excel_file_name': filename,
        })

        action = {
            'name': 'Reporte Consolidados de Cesantías',
            'type': 'ir.actions.act_url',
            'url': "web/content/?model=hr.consolidated.reports&id=" + str(
                self.id) + "&filename_field=excel_file_name&field=excel_file&download=true&filename=" + self.excel_file_name,
            'target': 'self',
        }
        return action

    # Reporte Consolidado de cesantías
    def generate_excel_prima(self):

        # ----------------------------------Ejecutar consulta
        query_report = f'''
                select distinct a."name",a.identification_id,b.date_start,
                case when b.date_start >= '{str(self.create_date_initial_process())}' then b.date_start else '{str(self.create_date_initial_process())}' end as date_initial_process,
                0 as days_service,coalesce(c.days_unpaid_absences,0)+coalesce(d.days_unpaid_absences,0) as days_unpaid_absences,0 as days_real,
                coalesce(f.value_wage,0) as value_wage,coalesce(f.value_base,0) as value_base,coalesce(f.amount,0) as amount,
                coalesce(pf.value_payments,0) as value_payments,coalesce(f.current_payable_value,0) as current_payable_value
                from hr_employee as a
                inner join hr_contract as b on a.id = b.employee_id and b.active = true {self.query_filter_period('and','b.date_start')}
                                                and (b.state = 'open' or (({self.query_filter_period('','b.retirement_date',1)} {self.query_filter_period('and','b.retirement_date')}) or ({self.query_filter_period('','b.retirement_date',0,'>=')})))
                left join lavish_res_branch as rb on a.branch_id = rb.id
                left join account_analytic_account as aaa on b.analytic_account_id = aaa.id 
                left join (select a.employee_id,sum(a.days) as days_unpaid_absences 
                            from hr_absence_history as a
                            inner join hr_leave_type as b on a.leave_type_id = b.id and b.unpaid_absences = true
                            where a.star_date <= '{str(self.create_closing_date())}' and a.end_date >= '{str(self.create_date_initial_process())}'
                            group by a.employee_id) as c on a.id = c.employee_id
                left join (select a.employee_id,sum(a.number_of_days) as days_unpaid_absences 
                            from hr_leave as a
                            inner join hr_leave_type as b on a.holiday_status_id = b.id and b.unpaid_absences = true
                            where a.state = 'validate' and a.request_date_from <= '{str(self.create_closing_date())}' and a.request_date_to >= '{str(self.create_date_initial_process())}'
                            group by a.employee_id) as d on a.id = d.employee_id
                left join (select a.employee_id,a.contract_id,max(a.id) as max_id 
                            from hr_executing_provisions_details as a
                            inner join hr_executing_provisions as b on a.executing_provisions_id = b.id {self.query_filter_period('and','b.date_end')}
                            where a.provision = 'prima'
                            group by a.employee_id,a.contract_id) as e on a.id = e.employee_id and b.id = e.contract_id
                left join hr_executing_provisions_details as f on e.max_id = f.id 
                left join (select a.employee_id,a.contract_id,sum(coalesce(a.value_payments,0)) as value_payments 
                            from hr_executing_provisions_details as a 
                            inner join hr_executing_provisions as b on a.executing_provisions_id = b.id {self.query_filter_period('and','b.date_end')}
                            where a.provision = 'prima'
                            group by a.employee_id,a.contract_id) as pf on a.id = pf.employee_id and b.id = pf.contract_id
                {self.query_where_filters()}     
            '''

        self._cr.execute(query_report)
        result_query = self._cr.dictfetchall()

        # Generar EXCEL
        filename = 'Reporte Consolidados de Prima'
        stream = io.BytesIO()
        book = xlsxwriter.Workbook(stream, {'in_memory': True})

        # Columnas
        columns = ['Nombres', 'Identificación', 'Fecha Ingreso', 'Fecha inicial de causación','Días Servicio', 'Ausencias no Remunerdas',
                   'Días Servicio Neto', 'Salario Básico', 'Base de Prima', 'Valor Prima Acumulado',
                   'Pagos Acumulados Prima', 'Neto a Pagar Prima Actual']
        sheet = book.add_worksheet('Consolidados de prima')

        # Agregar textos al excel
        text_company = self.company_id.name
        text_title = 'Consolidados de Prima'
        text_dates = f'Corte {str(self.create_closing_date())}'
        cell_format_title = book.add_format({'bold': True, 'align': 'center'})
        cell_format_title.set_font_name('Calibri')
        cell_format_title.set_font_size(15)
        cell_format_title.set_bottom(5)
        cell_format_title.set_bottom_color('#1F497D')
        cell_format_title.set_font_color('#1F497D')
        sheet.merge_range('A1:L1', text_company, cell_format_title)
        sheet.merge_range('A2:L2', text_title, cell_format_title)
        sheet.merge_range('A3:L3', text_dates, cell_format_title)
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
            date_start = ''
            date_initial_process = ''
            days_unpaid_absences = 0
            days_service = 0
            for row in query.values():
                width = len(str(row)) + 10
                # La columna 2 es Fecha Ingreso por ende se guarda su valor en la variable date_start
                date_start = row if aument_columns == 2 else date_start
                date_initial_process = row if aument_columns == 3 else date_initial_process
                # La columna 5 es días ausencias no remunedaras por ende se guarda su valor en la variable days_unpaid_absences
                days_unpaid_absences = row if aument_columns == 5 else days_unpaid_absences
                # La columna 4 y 6 se debe realizar un calculo y no tomarlo directamente de la consulta
                if aument_columns not in [4, 6]:
                    if str(type(row)).find('date') > -1:
                        sheet.write_datetime(aument_rows, aument_columns, row, date_format)
                    else:
                        sheet.write(aument_rows, aument_columns, row)
                else:
                    if aument_columns == 4:  # Dias Servicio
                        days_service = self.dias360(date_initial_process, self.create_closing_date())
                        sheet.write(aument_rows, aument_columns, days_service)
                    elif aument_columns == 6:  # Dias Servicio Neto
                        sheet.write(aument_rows, aument_columns, (days_service - days_unpaid_absences))
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

        sheet.add_table(3, 0, aument_rows-1, len(columns)-1, {'style': 'Table Style Medium 2', 'columns': array_header_table})
        # Guadar Excel
        book.close()

        self.write({
            'excel_file': base64.encodebytes(stream.getvalue()),
            'excel_file_name': filename,
        })

        action = {
            'name': 'Reporte Consolidados de Prima',
            'type': 'ir.actions.act_url',
            'url': "web/content/?model=hr.consolidated.reports&id=" + str(
                self.id) + "&filename_field=excel_file_name&field=excel_file&download=true&filename=" + self.excel_file_name,
            'target': 'self',
        }
        return action

    def generate_excel(self):
        if self.type_of_consolidation == 'prima':
            return self.generate_excel_prima()

        if self.type_of_consolidation == 'cesantias':
            return self.generate_excel_cesantias()

        if self.type_of_consolidation == 'vacaciones':
            return self.generate_excel_vacaciones()
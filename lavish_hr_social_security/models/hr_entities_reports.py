from odoo import tools
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from datetime import datetime
from pytz import timezone

import base64
import io
import xlsxwriter
import pandas as pd


class hr_entities_reports(models.TransientModel):
    _name = "hr.entities.reports"
    _description = 'Entidades del empleado'

    employee = fields.Many2many('hr.employee', string='Empleado')
    entities = fields.Many2many('hr.employee.entities', string='Entidad')
    branch = fields.Many2many('lavish.res.branch', string='Sucursal')
    type_of_entity = fields.Many2many('hr.contribution.register', string='Tipo de Entidad')
    analytic_account = fields.Many2many('account.analytic.account', string='Cuenta Analítica')
    branch_social_security = fields.Many2many('hr.social.security.branches', string='Sucursal seguridad social')
    work_center_social_security = fields.Many2many('hr.social.security.work.center', string='Centro de trabajo seguridad social')
    show_history = fields.Boolean(string='Mostrar historico', default=True)

    excel_file = fields.Binary('Excel')
    excel_file_name = fields.Char('Excel filename')

    def generate_entities_excel(self):
        query_where = ''
        # Filtro de compañia
        query_where = query_where + f"where a.company_id = {self.env.company.id} "
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
        # Filtro Entidad
        str_ids_entities = ''
        for i in self.entities:
            str_ids_entities = str(i.id) if str_ids_entities == '' else str_ids_entities + ',' + str(i.id)
        if str_ids_entities != '':
            query_where = query_where + f"and d.id in ({str_ids_entities}) "
        # Filtro Tipo de Entidad
        str_ids_type_entities = ''
        for i in self.type_of_entity:
            str_ids_type_entities = str(i.id) if str_ids_type_entities == '' else str_ids_type_entities + ',' + str(i.id)
        if str_ids_type_entities != '':
            query_where = query_where + f"and c.id in ({str_ids_type_entities}) "
        # Filtro Sucursal de seguridad social
        str_ids_branch_social_security = ''
        for i in self.branch_social_security:
            str_ids_branch_social_security = str(i.id) if str_ids_branch_social_security == '' else str_ids_branch_social_security + ',' + str(
                i.id)
        if str_ids_branch_social_security != '':
            query_where = query_where + f"and hssb.id in ({str_ids_branch_social_security}) "
        # Filtro Centro de trabajo seguridad social
        str_ids_work_center_social_security = ''
        for i in self.work_center_social_security:
            str_ids_work_center_social_security = str(
                i.id) if str_ids_work_center_social_security == '' else str_ids_work_center_social_security + ',' + str(
                i.id)
        if str_ids_work_center_social_security != '':
            query_where = query_where + f"and hsswc.id in ({str_ids_work_center_social_security}) "
        #Filtro de mostrar historicos
        query_where_show_history = ''
        if self.show_history == False:
            query_where_show_history = 'where a.es_actual = true '
        # ----------------------------------Ejecutar consulta
        query_report = f'''
                        select * from
                        (
                            select a."name" as empleado,rc."name" as compania,b.date_change as fecha_ingreso,rb."name"  as sucursal,aaa."name" as cuenta_analitica,c."name" as tipo_entidad,e."name" as entidad,
                                    hssb."name" as sucusal_seguridad_social,hsswc."name" as centro_trabajo_seguridad_social,
                                    true as es_actual,coalesce(f."name",'') as nivel_riesgo, false as es_traslado
                            from hr_employee as a
                            inner join hr_contract as hc on a.id = hc.employee_id and hc.active = true							
                            inner join hr_contract_setting as b on a.id = b.employee_id 
                            inner join hr_contribution_register as c on b.contrib_id = c.id 
                            inner join hr_employee_entities as d on b.partner_id = d.id 
                            inner join res_partner as e on d.partner_id = e.id
                            left join hr_contract_risk as f on hc.risk_id = f.id 
                            left join lavish_res_branch as rb on a.branch_id = rb.id
                            left join account_analytic_account as aaa on hc.analytic_account_id = aaa.id 
                            left join res_company as rc on rc.id = a.company_id
                            left join hr_social_security_branches as hssb on a.branch_social_security_id = hssb.id
                            left join hr_social_security_work_center as hsswc on a.work_center_social_security_id = hsswc.id
                            %s
                            union
                            select a."name" as empleado,rc."name" as compania,b.date_change as fecha_ingreso,rb."name"  as sucursal,aaa."name" as cuenta_analitica,c."name" as tipo_entidad,e."name" as entidad,
                                    hssb."name" as sucusal_seguridad_social,hsswc."name" as centro_trabajo_seguridad_social,
                                    false as es_actual,coalesce(f."name",'') as nivel_riesgo,b.is_transfer as es_traslado
                            from hr_employee as a
                            inner join hr_contract as hc on a.id = hc.employee_id and hc.active = true	
                            inner join hr_contract_setting_history as b on a.id = b.employee_id 
                            inner join hr_contribution_register as c on b.contrib_id = c.id 
                            inner join hr_employee_entities as d on b.partner_id = d.id 
                            inner join res_partner as e on d.partner_id = e.id
                            left join hr_contract_risk as f on hc.risk_id = f.id 
                            left join lavish_res_branch as rb on a.branch_id = rb.id
                            left join account_analytic_account as aaa on hc.analytic_account_id = aaa.id 
                            left join res_company as rc on rc.id = a.company_id
                            left join hr_social_security_branches as hssb on a.branch_social_security_id = hssb.id
                            left join hr_social_security_work_center as hsswc on a.work_center_social_security_id = hsswc.id
                            %s
                        ) as a
                        %s
                        order by a.empleado,a.tipo_entidad
                        ''' % (query_where,query_where,query_where_show_history)

        self._cr.execute(query_report)
        result_query = self._cr.dictfetchall()
        df_report = pd.DataFrame(result_query)
        pt_report = pd.pivot_table(df_report, values='empleado', index=['tipo_entidad', 'entidad'], aggfunc='count',
                                   margins=True, margins_name='Total', fill_value=0)
        # Generar EXCEL
        filename = 'Reporte Entidades del Empleado'
        stream = io.BytesIO()
        #book = xlsxwriter.Workbook(stream, {'in_memory': True})
        writer = pd.ExcelWriter(stream, engine='xlsxwriter')
        writer.book.filename = stream
        book = writer.book

        # Columnas
        columns = ['Empleado', 'Compañia', 'Fecha ingreso entidad', 'Sucursal', 'Cuenta analitica', 'Tipo de entidad', 'Entidad',
                    'Sucursal seguridad social','Centro de trabajo de seguridad social','Actual', 'Nivel de riesgo', 'Es traslado']
        sheet = book.add_worksheet('Entidades del empleado')
        pt_report.to_excel(writer, sheet_name='Entidades agrupadas',header=['Cantidad Empleados'])
        sheet_pivot = writer.sheets['Entidades agrupadas']
        #Tamaños columnas pivot
        align_format = book.add_format({'align': 'left'})
        sheet_pivot.set_column(0,0, 20, align_format)
        sheet_pivot.set_column(1,1, 100, align_format)
        sheet_pivot.set_column(2,2, 20, align_format)
        border_format = book.add_format({'border': 1, 'align': 'right'})
        sheet_pivot.conditional_format(0, 0, len(pt_report), 2,
                                     {'type': 'no_errors',
                                      'format': border_format})
        header_format = book.add_format({'border': 1, 'align': 'center','bold':True, 'bg_color':'#1F497D', 'font_color':'#FFFFFF'})
        sheet_pivot.write(0, 0, 'Tipo de entidad',header_format)
        sheet_pivot.write(0, 1, 'Entidad',header_format)
        sheet_pivot.write(0, 2, 'Cantidad Empleados', header_format)
        sheet_pivot.merge_range(len(pt_report), 0, len(pt_report), 1, 'Total', header_format)
        # Agregar textos al excel
        text_title = 'Entidades del empleado'
        text_generate = 'Informe generado el %s' % (datetime.now(timezone(self.env.user.tz)))
        cell_format_title = book.add_format({'bold': True, 'align': 'left'})
        cell_format_title.set_font_name('Calibri')
        cell_format_title.set_font_size(15)
        cell_format_title.set_bottom(5)
        cell_format_title.set_bottom_color('#1F497D')
        cell_format_title.set_font_color('#1F497D')
        sheet.merge_range('A1:L1', text_title, cell_format_title)
        cell_format_text_generate = book.add_format({'bold': False, 'align': 'left'})
        cell_format_text_generate.set_font_name('Calibri')
        cell_format_text_generate.set_font_size(10)
        cell_format_text_generate.set_bottom(5)
        cell_format_text_generate.set_bottom_color('#1F497D')
        cell_format_text_generate.set_font_color('#1F497D')
        sheet.merge_range('A2:L2', text_generate, cell_format_text_generate)
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
                'excel_file': base64.encodebytes(stream.getvalue()),
                'excel_file_name': filename,
            })

            action = {
                'name': 'Reporte entidades',
                'type': 'ir.actions.act_url',
                'url': "web/content/?model=hr.entities.reports&id=" + str(
                    self.id) + "&filename_field=excel_file_name&field=excel_file&download=true&filename=" + self.excel_file_name,
                'target': 'self',
            }
            return action
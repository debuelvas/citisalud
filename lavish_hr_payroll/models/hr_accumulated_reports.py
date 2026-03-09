from odoo import tools
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from datetime import datetime
from pytz import timezone

import base64
import io
import xlsxwriter


class hr_accumulated_reports(models.TransientModel):
    _name = "hr.accumulated.reports"
    _description = "Reporte acumulados"
    
    initial_year = fields.Integer('Año inicial', required=True)
    initial_month = fields.Selection([('1', 'Enero'),
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
                            ], string='Mes inicial', required=True)
    final_year= fields.Integer('Año final', required=True)
    final_month = fields.Selection([('1', 'Enero'),
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
                            ], string='Mes final', required=True)
    employee = fields.Many2many('hr.employee',string='Empleado')    
    salary_rule = fields.Many2many('hr.salary.rule', string='Reglas salariales')
    branch = fields.Many2many('lavish.res.branch', string='Sucursal', domain=lambda self:[('id','in',self.env.user.branch_ids.ids)])
    analytic_account = fields.Many2many('account.analytic.account', string='Cuenta Analítica')
    entities = fields.Many2many('hr.employee.entities', string='Entidad')

    excel_file = fields.Binary('Excel')
    excel_file_name = fields.Char('Excel filename')

    def generate_excel(self):
        query_where = ''
        query_where_accumulated = ''
        #Filtro periodo
        date_from = f'{str(self.initial_year)}-{str(self.initial_month)}-01'
        final_year = self.final_year if self.final_month != '12' else self.final_year+1
        final_month = int(self.final_month)+1 if self.final_month != '12' else 1
        date_to = f'{str(final_year)}-{str(final_month)}-01'
        # query_where = f"where a.date_from >= '{date_from}' and a.date_to < '{date_to}' "
        query_where = f'''where (
                        --Validar con fecha inicial (Nóminas,Vacaciones,Liq Contrato)
                        (a.struct_process in ('nomina','vacaciones','contrato','otro') and a.date_from >= '{date_from}' and a.date_from < '{date_to}')
                        or
                        --Validar con fecha final (Prima,Cesantias,Int Cesantias)
                        (a.struct_process in ('prima','cesantias','intereses_cesantias') and a.date_to >= '{date_from}' and a.date_to < '{date_to}')
                        ) '''
        query_where_accumulated = f"where a.date >= '{date_from}' and a.date < '{date_to}' "
        #Filtro compañia
        query_where = query_where + f"and b.id = {self.env.company.id} "
        query_where_accumulated = query_where_accumulated + f"and c.id = {self.env.company.id} "
        #Filtro Empleado
        str_ids_employee = ''
        for i in self.employee:
            str_ids_employee = str(i.id) if str_ids_employee == '' else str_ids_employee + ',' + str(i.id)
        if str_ids_employee != '':
            query_where = query_where + f"and c.id in ({str_ids_employee}) "
            query_where_accumulated = query_where_accumulated + f"and b.id in ({str_ids_employee}) "
        # Filtro Reglas Salariales
        str_ids_rules = ''
        for i in self.salary_rule:
            str_ids_rules = str(i.id) if str_ids_rules == '' else str_ids_rules + ',' + str(i.id)
        if str_ids_rules != '':
            query_where = query_where + f"and f.id in ({str_ids_rules}) "
            query_where_accumulated = query_where_accumulated + f"and f.id in ({str_ids_rules}) "
        # Filtro Sucursal
        str_ids_branch = ''
        for i in self.branch:
            str_ids_branch = str(i.id) if str_ids_branch == '' else str_ids_branch + ',' + str(i.id)
        if str_ids_branch == '' and len(self.env.user.branch_ids.ids) > 0:
            for i in self.env.user.branch_ids.ids:
                str_ids_branch = str(i) if str_ids_branch == '' else str_ids_branch + ',' + str(i)
        if str_ids_branch != '':
            query_where = query_where + f"and h.id in ({str_ids_branch}) "
            query_where_accumulated = query_where_accumulated + f"and h.id in ({str_ids_branch}) "
        # Filtro Cuenta analitica
        str_ids_analytic = ''
        for i in self.analytic_account:
            str_ids_analytic = str(i.id) if str_ids_analytic == '' else str_ids_analytic + ',' + str(i.id)
        if str_ids_analytic != '':
            query_where = query_where + f"and k.id in ({str_ids_analytic}) "
            query_where_accumulated = query_where_accumulated + f"and k.id in ({str_ids_analytic}) "
        # Filtro Entidad
        str_ids_entities = ''
        for i in self.entities:
            str_ids_entities = str(i.id) if str_ids_entities == '' else str_ids_entities + ',' + str(i.id)
        if str_ids_entities != '':
            query_where = query_where + f"and l.id in ({str_ids_entities}) "
            query_where_accumulated = query_where_accumulated + f"and 1 = 2 "
        # ----------------------------------Ejecutar consulta tablas estandar
        query_report = '''
            Select estructura,liquidacion,estado_de_liquidacion,descripcion,contrato,estado_de_contrato,fecha_liquidacion,fecha_inicial,fecha_final,compania,sucursal,identificacion,empleado,ubicacion_laboral,
                    cuenta_analitica,secuencia_contrato,categoria_regla,regla_salarial,entidad,unidades,valor_devengo,valor_deduccion,
                    base_seguridad_social,base_parafiscales,base_prima,base_cesantias,base_intereses_cesantias,base_vacaciones,base_vacaciones_dinero 
            From ( 
            Select upper(a.struct_process) as estructura,a."number" as liquidacion,
            case when a."state" = 'draft' then 'Borrador'
						else case when a."state" = 'verify' then 'En espera'
							else case when a."state" = 'done' then 'Hecho'
								else case when a."state" = 'draft' then 'Nuevo'
									else case when a."state" = 'cancel' then 'Rechazada'
										else ''
										end
									end
								end
							end
						end as estado_de_liquidacion,
            a."name" as descripcion,e."name" as contrato,
				case when e."state" = 'open' then 'En proceso'
						else case when e."state" = 'close' then 'Expirado'
							else case when e."state" = 'finished' then 'Finalizado'
								else case when e."state" = 'draft' then 'Nuevo'
									else case when e."state" = 'cancel' then 'Cancelado(a)'
										else ''
										end
									end
								end
							end
						end as estado_de_contrato,
                    a.date_to as fecha_liquidacion,a.date_from as fecha_inicial,a.date_to as fecha_final,
                    b."name" as compania,coalesce(h."name",'') as sucursal,
                    c.identification_id as identificacion,c."name" as empleado,
                    coalesce(i."name",'') as ubicacion_laboral, coalesce(k."name",'') as cuenta_analitica,
                    e."sequence" as secuencia_contrato,
                    g."name" as categoria_regla, f."name" as regla_salarial, f."sequence" as secuencia_regla,coalesce(m."name",'') as entidad,
                    aa.quantity as unidades, 
                    case when aa.total > 0 then aa.total else 0 end as valor_devengo,
                    case when aa.total <= 0 then aa.total else 0 end as valor_deduccion,
                    f.base_seguridad_social,f.base_parafiscales,
                    f.base_prima,f.base_cesantias,f.base_intereses_cesantias,f.base_vacaciones,f.base_vacaciones_dinero
            From hr_payslip as a
            inner join hr_payslip_line as aa on a.id = aa.slip_id 
            inner join res_company as b on a.company_id = b.id
            inner join hr_employee as c on a.employee_id = c.id
            inner join res_partner as d on c.work_contact_id = d.id
            inner join hr_contract as e on a.contract_id = e.id
            inner join hr_salary_rule as f on aa.salary_rule_id = f.id 
            inner join hr_salary_rule_category as g on f.category_id = g.id
            left join lavish_res_branch as h on c.branch_id = h.id
            left join res_partner as i on c.address_id = i.id            
            left join account_analytic_account as k on a.analytic_account_id  = k.id
            left join hr_employee_entities as l on aa.entity_id = l.id
            left join res_partner as m on l.partner_id = m.id 
            %s          
            UNION ALL
           Select 'ACUMULADOS' as estructura,'SLIP/00000' as liquidacion,'' as estado_de_liquidacion,'Tabla de acumulados' as descripcion,'' as contrato,'' as estado_de_contrato,
                    a."date" as fecha_liquidacion,a."date" as fecha_inicial,a."date" as fecha_final,
                    c."name" as compania,coalesce(h."name",'') as sucursal,
                    b.identification_id as identificacion,b."name" as empleado,
                    coalesce(i."name",'') as ubicacion_laboral, coalesce(k."name",'') as cuenta_analitica,
                    '' as secuencia_contrato,g."name" as categoria_regla, f."name" as regla_salarial, f."sequence" as secuencia_regla,'' as entidad,
                    1 as unidades, 
                    case when a.amount > 0 then a.amount else 0 end as valor_devengo,
                    case when a.amount <= 0 then a.amount else 0 end as valor_deduccion,
                    f.base_seguridad_social,f.base_parafiscales,
                    f.base_prima,f.base_cesantias,f.base_intereses_cesantias,f.base_vacaciones,f.base_vacaciones_dinero
            from hr_accumulated_payroll as a 
            inner join hr_employee as b on a.employee_id = b.id 
            inner join res_company as c on b.company_id = c.id
            inner join res_partner as d on b.work_contact_id = d.id
            inner join hr_salary_rule as f on a.salary_rule_id = f.id 
            inner join hr_salary_rule_category as g on f.category_id = g.id
            left join lavish_res_branch as h on b.branch_id = h.id
            left join res_partner as i on b.address_id = i.id     
            left join hr_contract as hc on hc.employee_id = b.id and hc.state = 'open'       
            left join account_analytic_account as k on hc.analytic_account_id  = k.id
            %s
            ) as a
            order by a.fecha_liquidacion,a.fecha_inicial,a.fecha_final,a.compania,a.sucursal, a.empleado, a.secuencia_regla           
            ''' % (query_where,query_where_accumulated)
        self._cr.execute(query_report)
        result_query = self._cr.dictfetchall()

        # Generar EXCEL
        filename = f'Reporte Acumulados {str(self.initial_year)}-{str(self.initial_month)} hasta {str(self.final_year)}-{str(self.final_month)}.xlsx'
        stream = io.BytesIO()
        book = xlsxwriter.Workbook(stream, {'in_memory': True})
        #Columnas
        columns = ['Estructura','Liquidación','Estado de liquidación', 'Descripción','Contrato','Estado de contrato', 'Fecha liquidación', 'Fecha inicial', 'Fecha final', 'Compañía',
                   'Sucursal', 'Identificación', 'Nombre empleado', 'Ubicación laboral', 'Cuenta analÍtica',
                   'Secuencia contrato', 'Categoria','Regla Salarial', 'Entidad', 'Unidades', 'Valor devengo', 'Valor deducción',
                   'Base seguridad social','Base parafiscales','Base prima','Base cesantias','Base int. cesantias','Base vacaciones','Base vacaciones en dinero']
        sheet = book.add_worksheet('Acumulados')
        # Agregar textos al excel
        text_company = self.env.company.name
        text_title = 'Informe de Acumulados'
        text_dates = 'Desde: %s a %s' % (date_from, date_to)
        text_generate = 'Informe generado el %s' % (datetime.now(timezone(self.env.user.tz)))
        cell_format_title = book.add_format({'bold': True, 'align': 'left'})
        cell_format_title.set_font_name('Calibri')
        cell_format_title.set_font_size(15)
        cell_format_title.set_bottom(5)
        cell_format_title.set_bottom_color('#1F497D')
        cell_format_title.set_font_color('#1F497D')
        sheet.merge_range('A1:AC1', text_company, cell_format_title)
        sheet.merge_range('A2:AC2', text_title, cell_format_title)
        sheet.merge_range('A3:AC3', text_dates, cell_format_title)
        cell_format_text_generate = book.add_format({'bold': False, 'align': 'left'})
        cell_format_text_generate.set_font_name('Calibri')
        cell_format_text_generate.set_font_size(10)
        cell_format_text_generate.set_bottom(5)
        cell_format_text_generate.set_bottom_color('#1F497D')
        cell_format_text_generate.set_font_color('#1F497D')
        sheet.merge_range('A4:AC4', text_generate, cell_format_text_generate)
        # Formato para fechas
        date_format = book.add_format({'num_format': 'dd/mm/yyyy'})
        # Agregar columnas
        aument_columns = 0
        for column in columns:
            sheet.write(4, aument_columns, column)
            aument_columns = aument_columns + 1
        #Agregar query
        aument_columns = 0
        aument_rows = 5
        for query in result_query:
            for row in query.values():
                width = len(str(row)) + 10
                if str(type(row)).find('date') > -1:
                    sheet.write_datetime(aument_rows, aument_columns, row, date_format)
                else:
                    sheet.write(aument_rows, aument_columns, row)
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

        sheet.add_table(4, 0, aument_rows-1, len(columns)-1, {'style': 'Table Style Medium 2', 'columns': array_header_table})
        #Guadar Excel
        book.close()

        self.write({
            'excel_file': base64.b64encode(stream.getvalue()).decode('utf-8'),
            'excel_file_name': filename,
        })

        action = {
            'name': 'Reporte Acumulados',
            'type': 'ir.actions.act_url',
            'url': "web/content/?model=hr.accumulated.reports&id=" + str(
                self.id) + "&filename_field=excel_file_name&field=excel_file&download=true&filename=" + self.excel_file_name,
            'target': 'self',
        }
        return action

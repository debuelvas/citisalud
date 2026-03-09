from odoo import api, fields, models, _
from datetime import datetime
import base64
import io
import xlsxwriter
from odoo.exceptions import UserError, ValidationError

class ConfigAccounts(models.Model):
    _name = 'hr.config.rule.exogena'
    _description = 'Configuracion de reglas Reporte 2276'

    name = fields.Char(string='Name', required=True)
    code = fields.Char(string='Code', required=True)
    config_rule_line_ids = fields.One2many(comodel_name='hr.config.rule.concepts', inverse_name='confi_id', string='Account Lines')


class ConfigAccountsConcepts(models.Model):
    _name = 'hr.config.rule.concepts'
    _description = 'lineas Configuracion de reglas Reporte 2276'
    
    columnas = [
        ('12', 'Pagos por Salarios'),
        ('13', 'Pagos por emolumentos eclesiásticos'),
        ('14', 'Pagos por honorarios'),
        ('15', 'Pagos por servicios'),
        ('16', 'Pagos por comisiones'),
        ('17', 'Pagos por prestaciones sociales'),
        ('18', 'Pagos por viáticos'),
        ('19', 'Pagos por gastos de representación'),
        ('20', 'Pagos por compensaciones trabajo asociado cooperativo'),
        ('21', 'Otros pagos'),
        ('22', 'Cesantías e intereses de cesantías efectivamente pagadas, consignadas o reconocidas en el periodo'),
        ('23', 'Pensiones de Jubilación, vejez o invalidez'),
        ('24', 'Total Ingresos brutos de rentas de trabajo y pensión'),
        ('25', 'Aportes Obligatorios por Salud'),
        ('26', 'Aportes obligatorios a fondos de pensiones y solidaridad pensional y Aportes voluntarios al - RAIS'),
        ('27', 'Aportes voluntarios a fondos de pensiones voluntarias'),
        ('28', 'Aportes a cuentas AFC'),
        ('29', 'Aportes a cuentas AVC'),
        ('30', 'Valor de las retenciones en la fuente por pagos de rentas de trabajo o pensiones'),
        ('31', 'Pagos realizados con bonos electrónicos o de papel de servicio, cheques, tarjetas, vales, etc.'),
        ('32', 'Apoyos económicos no reembolsables o condonados, entregados por el Estado o financiados con recursos públicos, para financiar programas educativos'),
        ('33', 'Pagos por alimentación mayores a 41 UVT'),
        ('34', 'Pagos por alimentación hasta a 41 UVT'),
        ('35', 'Identificación del fideicomiso o contrato'),
        ('36', 'Tipo documento participante en contrato de colaboración'),
        ('37', 'Identificación participante en contrato colaboración')
    ]
    confi_id = fields.Many2one('hr.config.rule.exogena',ondelete='cascade')
    column_selection = fields.Selection(columnas, string='Columna')
    calculation = fields.Selection([('sum_rule', 'Sumatoria Reglas'),
                                    ('dependents_type_vat', 'Dependientes - Tipo documento'),
                                    ('dependents_vat', 'Dependientes - No. Documento'),
                                    ('dependents_name', 'Dependientes - Apellidos y Nombres'),
                                    ('dependents_type', 'Dependientes - Parentesco'),], string='Tipo Cálculo',
                                   default='sum_rule', required=True)
    salary_rule_id = fields.Many2many('hr.salary.rule', string='Regla Salarial')
    origin_severance_pay = fields.Selection([('employee', 'Empleado'), ('fund', 'Fondo')], string='Pago cesantías')
    accumulated_previous_year = fields.Boolean(string='Acumulado año anterior')

class ExogenaWizard(models.TransientModel):
    _name = 'hr.report.2276.exogena.wizard'
    _description = 'Exogena 2276 Wizard'

    start_date = fields.Date('Start Date', required=True)
    end_date = fields.Date('End Date', required=True, default=fields.Datetime.now)
    confi_id = fields.Many2one('hr.config.rule.exogena', string='Format Configuration to use')

    def getaccountssummarized(self, data):
        records = []
        date_start = data['date_start']
        date_end = data['date_end']
        company_id = self.env.company.id

        for record in data["confi_id"].pt_config_account_line_ids:
            for line in record.pt_config_accounts_concepts_line_ids:
                acc_moves = self.env['account.move.line'].read_group([('account_id', '=', line.account_id.id),
                                                                      ('date', '>=', date_start),
                                                                      ('date', '<=', date_end),
                                                                      ('company_id', '=', company_id)],
                                                                     ['debit', 'credit', 'balance'], ['partner_id'])
                for acc_move in acc_moves:
                    data = {
                        'code': record.code,
                        'partner_id': acc_move['partner_id'][0],
                        'account_id': line.account_id.id,
                        'calculation_type': line.calculation_type,
                        'column_number': line.column_number,
                        'debit': acc_move['debit'],
                        'credit': acc_move['credit'],
                        'balance': acc_move['balance'],
                    }
                    records.append(data)
        return records


    def generate_xlsx_report(self):
        self.ensure_one()
        data = self.get_report_data()
        return self.create_excel_report(data)

    def get_report_data(self):
        columnas = [
            'Entidad Informante', 'Tipo de documento del beneficiario', 'Número de Identificación del beneficiario',
            'Primer Apellido del beneficiario', 'Segundo Apellido del beneficiario', 'Primer Nombre del beneficiario',
            'Otros Nombres del beneficiario', 'Dirección del beneficiario', 'Departamento del beneficiario',
            'Municipio del beneficiario', 'País del beneficiario', 'Pagos por Salarios',
            'Pagos por emolumentos eclesiásticos', 'Pagos por honorarios', 'Pagos por servicios',
            'Pagos por comisiones', 'Pagos por prestaciones sociales', 'Pagos por viáticos',
            'Pagos por gastos de representación', 'Pagos por compensaciones trabajo asociado cooperativo',
            'Otros pagos', 'Cesantías e intereses de cesantías efectivamente pagadas, consignadas o reconocidas en el periodo',
            'Pensiones de Jubilación, vejez o invalidez', 'Total Ingresos brutos de rentas de trabajo y pensión',
            'Aportes Obligatorios por Salud',
            'Aportes obligatorios a fondos de pensiones y solidaridad pensional y Aportes voluntarios al - RAIS',
            'Aportes voluntarios a fondos de pensiones voluntarias', 'Aportes a cuentas AFC', 'Aportes a cuentas AVC',
            'Valor de las retenciones en la fuente por pagos de rentas de trabajo o pensiones',
            'Pagos realizados con bonos electrónicos o de papel de servicio, cheques, tarjetas, vales, etc.',
            'Apoyos económicos no reembolsables o condonados, entregados por el Estado o financiados con recursos públicos, para financiar programas educativos',
            'Pagos por alimentación mayores a 41 UVT', 'Pagos por alimentación hasta a 41 UVT',
            'Identificación del fideicomiso o contrato', 'Tipo documento participante en contrato de colaboración',
            'Identificación participante en contrato colaboración'
        ]

        employees = self.env['hr.employee'].search([])
        reportlines = []

        for employee in employees:
            dataline = self.get_employee_data(employee, columnas)
            if dataline:
                reportlines.append(dataline)

        return {
            'start_date': self.start_date,
            'end_date': self.end_date,
            'lines': reportlines,
            'columns': columnas,
        }

    def get_employee_data(self, employee, columnas):
        date_start = self.start_date
        date_end = self.end_date
        date_start_ant = date_start.replace(year=date_start.year - 1)
        date_end_ant = date_end.replace(year=date_end.year - 1)

        obj_payslip = self.env['hr.payslip'].search([
            ('state', '=', 'done'), ('employee_id', '=', employee.id),
            ('date_from', '>=', date_start), ('date_from', '<=', date_end)
        ])
        obj_payslip += self.env['hr.payslip'].search([
            ('state', '=', 'done'), ('employee_id', '=', employee.id),
            ('id', 'not in', obj_payslip.ids),
            ('struct_id.process', 'in', ['cesantias', 'intereses_cesantias', 'prima']),
            ('date_to', '>=', date_start), ('date_to', '<=', date_end)
        ])

        obj_payslip_accumulated = self.env['hr.accumulated.payroll'].search([
            ('employee_id', '=', employee.id),
            ('date', '>=', date_start),
            ('date', '<=', date_end)
        ])

        obj_payslip_ant = self.env['hr.payslip'].search([
            ('state', '=', 'done'), ('employee_id', '=', employee.id),
            ('date_from', '>=', date_start_ant), ('date_from', '<=', date_end_ant)
        ])
        obj_payslip_ant += self.env['hr.payslip'].search([
            ('state', '=', 'done'), ('employee_id', '=', employee.id),
            ('id', 'not in', obj_payslip_ant.ids),
            ('struct_id.process', 'in', ['cesantias', 'intereses_cesantias', 'prima']),
            ('date_to', '>=', date_start_ant), ('date_to', '<=', date_end_ant)
        ])

        obj_payslip_accumulated_ant = self.env['hr.accumulated.payroll'].search([
            ('employee_id', '=', employee.id),
            ('date', '>=', date_start_ant),
            ('date', '<=', date_end_ant)
        ])
        self.validate_dataline(employee, concepto='Reporte 2276')
        dataline = {
            'Entidad Informante': self.env.company.id,
            'Tipo de documento del beneficiario': self.get_document_type(employee),
            'Número de Identificación del beneficiario': employee.work_contact_id.vat_co,
            'Primer Apellido del beneficiario': employee.work_contact_id.first_lastname or '',
            'Segundo Apellido del beneficiario': employee.work_contact_id.second_lastname or '',
            'Primer Nombre del beneficiario': employee.work_contact_id.firs_name or '',
            'Otros Nombres del beneficiario': employee.work_contact_id.second_name or '',
            'Dirección del beneficiario': employee.work_contact_id.street or '',
            'Departamento del beneficiario': employee.work_contact_id.city_id.code if employee.work_contact_id.state_id else '',
            'Municipio del beneficiario': employee.work_contact_id.city_id.code  if employee.work_contact_id.city_id else '',
            'País del beneficiario': employee.work_contact_id.country_id.code if employee.work_contact_id.country_id else '',
        }

        for line in self.confi_id.config_rule_line_ids:
            column_name = dict(line._fields['column_selection'].selection).get(line.column_selection)
            if column_name in columnas:
                value = self.calculate_line_value(line, employee, obj_payslip, obj_payslip_accumulated, 
                                                  obj_payslip_ant, obj_payslip_accumulated_ant)
                dataline[column_name] = value if value else 0

        return dataline

    def get_document_type(self, employee):
        switch_id = {
            'rut': '31', 'id_document': '13', 'national_citizen_id': '13', 'id_card': '12', 'passport': '41',
            'foreigner_id_card': '22', 'foreign_colombian_card': '22', 'external_id': '42', 'diplomatic_card': '42',
            'foreign_resident_card': '21', 'residence_document': '21', 'civil_registration': '11',
        }
        return employee.work_contact_id.l10n_latam_identification_type_id.dian_code
    def calculate_line_value(self, line, employee, obj_payslip, obj_payslip_accumulated, 
                             obj_payslip_ant, obj_payslip_accumulated_ant):
        if line.calculation == 'sum_rule':
            return self.sum_salary_rules(line, obj_payslip, obj_payslip_accumulated, 
                                         obj_payslip_ant, obj_payslip_accumulated_ant)
        elif line.calculation in ['dependents_type_vat', 'dependents_vat', 'dependents_name', 'dependents_type']:
            return self.get_dependents_info(employee, line.calculation)
        # Add more calculation types as needed
        return 0

    def sum_salary_rules(self, line, obj_payslip, obj_payslip_accumulated, 
                         obj_payslip_ant, obj_payslip_accumulated_ant):
        total = 0
        if line.accumulated_previous_year:
            if line.origin_severance_pay:
                for payslip in obj_payslip_ant:
                    if line.origin_severance_pay == 'employee':
                        total += sum(l.total for l in payslip.line_ids if l.salary_rule_id in line.salary_rule_id and payslip.employee_severance_pay)
                    else:
                        total += sum(l.total for l in payslip.line_ids if l.salary_rule_id in line.salary_rule_id and not payslip.employee_severance_pay)
                if line.origin_severance_pay != 'employee':
                    total += sum(acc.amount for acc in obj_payslip_accumulated_ant if acc.salary_rule_id in line.salary_rule_id)
            else:
                for payslip in obj_payslip_ant:
                    total += sum(l.total for l in payslip.line_ids if l.salary_rule_id in line.salary_rule_id)
                total += sum(acc.amount for acc in obj_payslip_accumulated_ant if acc.salary_rule_id in line.salary_rule_id)
        else:
            if line.origin_severance_pay:
                for payslip in obj_payslip:
                    if line.origin_severance_pay == 'employee':
                        total += sum(l.total for l in payslip.line_ids if l.salary_rule_id in line.salary_rule_id and payslip.employee_severance_pay)
                    else:
                        total += sum(l.total for l in payslip.line_ids if l.salary_rule_id in line.salary_rule_id and not payslip.employee_severance_pay)
                if line.origin_severance_pay != 'employee':
                    total += sum(acc.amount for acc in obj_payslip_accumulated if acc.salary_rule_id in line.salary_rule_id)
            else:
                for payslip in obj_payslip:
                    total += sum(l.total for l in payslip.line_ids if l.salary_rule_id in line.salary_rule_id)
                total += sum(acc.amount for acc in obj_payslip_accumulated if acc.salary_rule_id in line.salary_rule_id)
        return total

    def get_dependents_info(self, employee, info_type):
        dependents = employee.dependents_information.filtered(lambda d: d.report_income_and_withholdings)
        if info_type == 'dependents_type_vat':
            return ' lavish_BREAK_LINE '.join(d.document_type for d in dependents)
        elif info_type == 'dependents_vat':
            return ' lavish_BREAK_LINE '.join(d.vat for d in dependents)
        elif info_type == 'dependents_name':
            return ' lavish_BREAK_LINE '.join(d.name for d in dependents)
        elif info_type == 'dependents_type':
            return ' lavish_BREAK_LINE '.join(str(d.dependents_type).capitalize() for d in dependents)
        return ''
    
    def validate_dataline(self, employee, concepto=None):
        missing_location = not (employee.work_contact_id.country_id or 
                            employee.work_contact_id.city_id.code or 
                            employee.work_contact_id.state_id or 
                            self.get_document_type(employee))
        
        if missing_location:
            missing_fields = []
            if not employee.work_contact_id.firs_name:
                missing_fields.append("primer nombre")
            if not employee.work_contact_id.first_lastname:
                missing_fields.append("primer apellido")
            if not employee.work_contact_id.street:
                missing_fields.append("dirección")
            if missing_fields:
                campos_faltantes = ", ".join(missing_fields)
                concepto_msg = f"Por concepto {concepto}: " if concepto else "Por concepto: "
                raise UserError(_(f"{concepto_msg}El empleado {employee.name} debe completar los siguientes campos: {campos_faltantes}."))
            
    def create_excel_report(self, data):
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet('Reporte Exogena 2276')

        # Escribir encabezados
        for col, header in enumerate(data['columns']):
            worksheet.write(0, col, header)

        # Escribir datos
        for row, line in enumerate(data['lines'], start=1):
            for col, header in enumerate(data['columns']):
                worksheet.write(row, col, line.get(header, ''))

        workbook.close()
        output.seek(0)

        filename = f'reporte_exogena_2276_{self.start_date}_{self.end_date}.xlsx'
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'datas': base64.b64encode(output.read()),
            'store_fname': filename,
            'type': 'binary',
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }


class ExogenaReport(models.TransientModel):
    _name = 'hr.exogena.report'
    _description = 'Exogena 2276 Report'

    name = fields.Char('Nombre', default='Exogena')
    col_1 = fields.Char('Columna 1')
    col_2 = fields.Char('Columna 2')
    col_3 = fields.Char('Columna 3')
    col_4 = fields.Char('Columna 4')
    col_5 = fields.Char('Columna 5')
    col_6 = fields.Char('Columna 6')
    col_7 = fields.Char('Columna 7')
    col_8 = fields.Char('Columna 8')
    col_9 = fields.Char('Columna 9')
    col_10 = fields.Char('Columna 10')
    col_11 = fields.Char('Columna 11')
    col_12 = fields.Char('Columna 12')
    col_13 = fields.Char('Columna 13')
    col_14 = fields.Char('Columna 14')
    col_15 = fields.Char('Columna 15')
    col_16 = fields.Char('Columna 16')
    col_17 = fields.Char('Columna 17')
    col_18 = fields.Char('Columna 18')
    col_19 = fields.Char('Columna 19')
    col_20 = fields.Char('Columna 20')
    col_21 = fields.Char('Columna 21')
    col_22 = fields.Char('Columna 22')
    col_23 = fields.Char('Columna 23')
    col_24 = fields.Char('Columna 24')
    col_25 = fields.Char('Columna 25')
    col_26 = fields.Char('Columna 26')
    col_27 = fields.Char('Columna 27')
    col_28 = fields.Char('Columna 28')
    col_29 = fields.Char('Columna 29')
    col_30 = fields.Char('Columna 30')
    col_31 = fields.Char('Columna 31')
    col_32 = fields.Char('Columna 32')
    col_33 = fields.Char('Columna 33')
    col_34 = fields.Char('Columna 34')
    col_35 = fields.Char('Columna 35')
    col_36 = fields.Char('Columna 36')
    col_37 = fields.Char('Columna 37')

    def clean_data(self):
        self.env["hr.exogena.report"].search([]).unlink()
        return True

    def show_report(self, data):
        self.clean_data()
        columns = data["columns"]
        lineas = data["lines"]

        data_reg = {}
        for i, column in enumerate(columns, 1):
            data_reg[f'col_{i}'] = column

        self.env["hr.exogena.report"].create(data_reg)

        for line in lineas:
            line_reg = {}
            for i, column in enumerate(columns, 1):
                line_reg[f'col_{i}'] = line[column]
            self.env["hr.exogena.report"].create(line_reg)

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hr.exogena.report',
            'view_mode': 'list',
            'target': 'current'
        }
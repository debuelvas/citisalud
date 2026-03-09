import html
import io
import base64
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError,UserError
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from pytz import timezone
from PyPDF2 import  PdfFileReader, PdfFileWriter
#---------------------------Certificado ingreso y retenciones-------------------------------#

class hr_withholding_and_income_certificate(models.TransientModel):
    _name = 'hr.withholding.and.income.certificate'
    _description = 'Certificado ingreso y retenciones'

    employee_ids = fields.Many2many('hr.employee', string="Empleado",)
    year = fields.Integer('Año', required=True)
    save_documents = fields.Boolean(string="Guardar en documentos")
    struct_report_income_and_withholdings = fields.Html('Estructura Certificado ingresos y retenciones')

    def generate_certificate(self):
        struct_report_income_and_withholdings_finally = ''
        if len(self.employee_ids) == 0:
            raise UserError('No se seleccionaron empleados.')

        obj_annual_parameters = self.env['hr.annual.parameters'].search([('year', '=', self.year)], limit=1)
        for employee in self.employee_ids:
            if self.save_documents:
                struct_report_income_and_withholdings_finally = ''
            if len(obj_annual_parameters) > 0:
                struct_report_income_and_withholdings = obj_annual_parameters.report_income_and_withholdings
                lst_items = []
                #Obtener nóminas
                year_process = obj_annual_parameters.taxable_year
                year_process_ant = obj_annual_parameters.taxable_year - 1
                # Obtener fechas del periodo seleccionado
                try:
                    date_start = '01/01/' + str(year_process)
                    date_start = datetime.strptime(date_start, '%d/%m/%Y')
                    date_start = date_start.date()
                    date_end = '31/12/' + str(year_process)
                    date_end = datetime.strptime(date_end, '%d/%m/%Y')
                    date_end = date_end.date()

                    date_start_ant = '01/01/' + str(year_process_ant)
                    date_start_ant = datetime.strptime(date_start_ant, '%d/%m/%Y')
                    date_start_ant = date_start_ant.date()
                    date_end_ant = '31/12/' + str(year_process_ant)
                    date_end_ant = datetime.strptime(date_end_ant, '%d/%m/%Y')
                    date_end_ant = date_end_ant.date()
                except:
                    raise UserError('El año digitado es invalido, por favor verificar.')

                obj_payslip = self.env['hr.payslip'].search(
                    [('state', '=', 'done'), ('employee_id', '=', employee.id),
                     ('date_from', '>=', date_start), ('date_from', '<=', date_end)])
                obj_payslip += self.env['hr.payslip'].search(
                    [('state', '=', 'done'), ('employee_id', '=', employee.id),
                     ('id', 'not in', obj_payslip.ids),
                     ('struct_id.process', 'in', ['cesantias', 'intereses_cesantias', 'prima']),
                     ('date_to', '>=', date_start), ('date_to', '<=', date_end)])

                obj_payslip_accumulated = self.env['hr.accumulated.payroll'].search([('employee_id', '=', employee.id),
                                                                                     ('date', '>=', date_start),
                                                                                     ('date', '<=', date_end)])

                obj_payslip_ant = self.env['hr.payslip'].search(
                    [('state', '=', 'done'), ('employee_id', '=', employee.id),
                     ('date_from', '>=', date_start_ant), ('date_from', '<=', date_end_ant)])
                obj_payslip_ant += self.env['hr.payslip'].search(
                    [('state', '=', 'done'), ('employee_id', '=', employee.id),
                     ('id', 'not in', obj_payslip_ant.ids),
                     ('struct_id.process', 'in', ['cesantias', 'intereses_cesantias', 'prima']),
                     ('date_to', '>=', date_start_ant), ('date_to', '<=', date_end_ant)])

                obj_payslip_accumulated_ant = self.env['hr.accumulated.payroll'].search([('employee_id', '=', employee.id),
                                                                                     ('date', '>=', date_start_ant),
                                                                                     ('date', '<=', date_end_ant)])
                #Info dependientes:
                dependents_type_vat,dependents_vat,dependents_name,dependents_type = '','','',''
                for dependent in employee.dependents_information.filtered(lambda a: a.report_income_and_withholdings == True):
                    dependents_type_vat += f'{dependent.document_type} lavish_BREAK_LINE'
                    dependents_vat += f'{dependent.vat} lavish_BREAK_LINE'
                    dependents_name += f'{dependent.name} lavish_BREAK_LINE'
                    dependents_type += f'{str(dependent.dependents_type).capitalize()} lavish_BREAK_LINE'

                #Recorrer configuración
                for conf in sorted(obj_annual_parameters.conf_certificate_income_ids, key=lambda x: x.sequence):
                    ldict = {'employee':employee}
                    value = None
                    #Tipo de Calculo ---------------------- INFORMACIÓN
                    if conf.calculation == 'info':
                        if conf.type_partner == 'employee':
                            if conf.information_fields_id.model_id.model == 'hr.employee':
                                if conf.information_fields_id.ttype == 'many2one':
                                    code_python = 'value = employee.' + str(conf.information_fields_id.name) + '.' + str(conf.related_field_id.name)
                                else:
                                    code_python = 'value = employee.' + str(conf.information_fields_id.name)
                                exec(code_python, ldict)
                                value = ldict.get('value')
                            elif conf.information_fields_id.model_id.model == 'hr.contract':
                                raise UserError('No se puede traer información del empleado de un campo de la tabla contratos, EN DESARROLLO.')
                            elif conf.information_fields_id.model_id.model == 'res.partner':
                                if conf.information_fields_id.ttype == 'many2one':
                                    code_python = 'value = employee.work_contact_id.'+str(conf.information_fields_id.name) + '.' + str(conf.related_field_id.name)
                                else:
                                    code_python = 'value = employee.work_contact_id.' + str(conf.information_fields_id.name)
                                exec(code_python, ldict)
                                value = ldict.get('value')
                        if conf.type_partner == 'company':
                            if conf.information_fields_id.model_id.model == 'hr.employee':
                                raise UserError('No se puede traer información de la compañía de un campo de la tabla empleados, por favor verificar.')
                            elif conf.information_fields_id.model_id.model == 'hr.contract':
                                raise UserError('No se puede traer información de la compañía de un campo de la tabla contratos, por favor verificar.')
                            elif conf.information_fields_id.model_id.model == 'res.partner':
                                if conf.information_fields_id.ttype == 'many2one':
                                    code_python = 'value = employee.company_id.partner_id.'+str(conf.information_fields_id.name) + '.' + str(conf.related_field_id.name)
                                else:
                                    code_python = 'value = employee.company_id.partner_id.' + str( conf.information_fields_id.name)
                                exec(code_python, ldict)
                                value = ldict.get('value')
                    # Tipo de Calculo ---------------------- SUMATORIA REGLAS
                    elif conf.calculation == 'sum_rule':
                        amount = 0
                        if conf.accumulated_previous_year == True:
                            if conf.origin_severance_pay:
                                # Nóminas
                                for payslip_ant in obj_payslip_ant:
                                    if conf.origin_severance_pay == 'employee':
                                        amount += abs(sum([i.total for i in payslip_ant.line_ids.filtered(lambda line: line.salary_rule_id.id in conf.salary_rule_id.ids and line.slip_id.employee_severance_pay == True)]))
                                    else:
                                        amount += abs(sum([i.total for i in payslip_ant.line_ids.filtered(lambda line: line.salary_rule_id.id in conf.salary_rule_id.ids and line.slip_id.employee_severance_pay == False)]))
                                if conf.origin_severance_pay != 'employee':
                                    # Acumulados
                                    amount += abs(sum([i.amount for i in obj_payslip_accumulated_ant.filtered(lambda line: line.salary_rule_id.id in conf.salary_rule_id.ids)]))
                            else:
                                # Nóminas
                                for payslip_ant in obj_payslip_ant:
                                    amount += abs(sum([i.total for i in payslip_ant.line_ids.filtered(lambda line: line.salary_rule_id.id in conf.salary_rule_id.ids)]))
                                # Acumulados
                                amount += abs(sum([i.amount for i in obj_payslip_accumulated_ant.filtered(lambda line: line.salary_rule_id.id in conf.salary_rule_id.ids)]))
                        else:
                            if conf.origin_severance_pay:
                                # Nóminas
                                for payslip in obj_payslip:
                                    if conf.origin_severance_pay == 'employee':
                                        amount += abs(sum([i.total for i in payslip.line_ids.filtered(lambda line: line.salary_rule_id.id in conf.salary_rule_id.ids and line.slip_id.employee_severance_pay == True)]))
                                    else:
                                        amount += abs(sum([i.total for i in payslip.line_ids.filtered(lambda line: line.salary_rule_id.id in conf.salary_rule_id.ids and line.slip_id.employee_severance_pay == False)]))
                                if conf.origin_severance_pay != 'employee':
                                    # Acumulados
                                    amount += abs(sum([i.amount for i in obj_payslip_accumulated.filtered(lambda line: line.salary_rule_id.id in conf.salary_rule_id.ids)]))
                            else:
                                #Nóminas
                                for payslip in obj_payslip:
                                    amount += abs(sum([i.total for i in payslip.line_ids.filtered(lambda line: line.salary_rule_id.id in conf.salary_rule_id.ids)]))
                                #Acumulados
                                amount += abs(sum([i.amount for i in obj_payslip_accumulated.filtered(lambda line: line.salary_rule_id.id in conf.salary_rule_id.ids)]))
                        value = amount
                    # Tipo de Calculo ---------------------- SUMATORIA SECUENCIAS ANTERIORES
                    elif conf.calculation == 'sum_sequence':
                        if conf.sequence_list_sum:
                            amount = 0
                            sequence_list_sum = conf.sequence_list_sum.split(',')
                            for item in lst_items:
                                amount += float(item[1]) if str(item[0]) in sequence_list_sum else 0
                            value = amount
                    # Tipo de Calculo ---------------------- FECHA EXPEDICIÓN
                    elif conf.calculation == 'date_issue':
                        value = str(datetime.now(timezone(self.env.user.tz)).strftime("%Y-%m-%d"))
                    # Tipo de Calculo ---------------------- FECHA CERTIFICACIÓN INICIAL
                    elif conf.calculation == 'start_date_year':
                        value = str(year_process)+'-01-01'
                    # Tipo de Calculo ---------------------- FECHA CERTIFICACIÓN FINAL
                    elif conf.calculation == 'end_date_year':
                        value = str(year_process)+'-12-31'
                    # Tipo de Calculo ---------------------- DEPENDIENTES - TIPO DOCUMENTO
                    elif conf.calculation == 'dependents_type_vat':
                        value = dependents_type_vat
                    # Tipo de Calculo ---------------------- DEPENDIENTES - NO. DOCUMENTO
                    elif conf.calculation == 'dependents_vat':
                        value = dependents_vat
                    # Tipo de Calculo ---------------------- DEPENDIENTES - APELLIDOS Y NOMBRES
                    elif conf.calculation == 'dependents_name':
                        value = dependents_name
                    # Tipo de Calculo ---------------------- DEPENDIENTES - PARENTESCO
                    elif conf.calculation == 'dependents_type':
                        value = dependents_type
                    #----------------------------------------------------------------------------------------------
                    #                                       GUARDAR RESULTADO
                    # ----------------------------------------------------------------------------------------------
                    lst_items.append((conf.sequence, value))
                    if value != None and value != False:
                        struct_report_income_and_withholdings = struct_report_income_and_withholdings.replace('$_val'+str(conf.sequence)+'_$',("{:,.2f}".format(value) if type(value) is float else str(value)))
                    else:
                        struct_report_income_and_withholdings = struct_report_income_and_withholdings.replace('$_val' + str(conf.sequence)+'_$', '')
                if struct_report_income_and_withholdings_finally == '':
                    struct_report_income_and_withholdings_finally = struct_report_income_and_withholdings
                else:
                    # struct_report_income_and_withholdings_finally += '\n <div style="page-break-after: always;"/> \n'
                    struct_report_income_and_withholdings_finally += struct_report_income_and_withholdings

                #Limpiar vals no calculados
                for sequence_val in range(1,101):
                    struct_report_income_and_withholdings_finally = struct_report_income_and_withholdings_finally.replace('$_val' + str(sequence_val) + '_$', '')
                    for sequence_val_internal in range(1,10):
                        struct_report_income_and_withholdings_finally = struct_report_income_and_withholdings_finally.replace('$_val' + str(sequence_val) + '.' + str(sequence_val_internal) + '_$', '')

                if self.save_documents:
                    pdf_writer = PdfFileWriter()
                    obj_report = self.env['hr.withholding.and.income.certificate'].create(
                        {
                            'year': self.year,
                            'employee_ids': employee.ids,
                            'struct_report_income_and_withholdings':str(struct_report_income_and_withholdings_finally).replace("lavish_BREAK_LINE", "<br>"),
                        }
                    )
                    report = self.env.ref('lavish_hr_payroll.hr_report_income_and_withholdings_action', False)
                    pdf_content, _ = report._render_qweb_pdf(obj_report.id)
                    reader = PdfFileReader(io.BytesIO(pdf_content), strict=False, overwriteWarnings=False)
                    for page in range(reader.getNumPages()):
                        pdf_writer.addPage(reader.getPage(page))
                    _buffer = io.BytesIO()
                    pdf_writer.write(_buffer)
                    merged_pdf = _buffer.getvalue()
                    _buffer.close()

                    # Crear adjunto
                    name = 'Certificado Ingreso y Retenciones año gravable ' + str(self.year - 1) + '.pdf'
                    obj_attachment = self.env['ir.attachment'].create({
                        'name': name,
                        'store_fname': name,
                        'res_name': name,
                        'type': 'binary',
                        'res_model': 'res.partner',
                        'res_id': employee.work_contact_id.id,
                        'datas': base64.b64encode(merged_pdf),
                    })
                    # Asociar adjunto a documento de Odoo
                    doc_vals = {
                        'name': name,
                        'owner_id': self.env.user.id,
                        'partner_id': employee.work_contact_id.id,
                        'folder_id': self.env.user.company_id.documents_hr_folder.id,
                        'tag_ids': self.env.user.company_id.validated_certificate.ids,
                        'type': 'binary',
                        'attachment_id': obj_attachment.id
                    }
                    self.env['documents.document'].sudo().create(doc_vals)

        #Retonar PDF
        self.struct_report_income_and_withholdings = str(struct_report_income_and_withholdings_finally).replace("lavish_BREAK_LINE", "<br>")
        datas = {
             'id': self.id,
             'model': 'hr.withholding.and.income.certificate'
            }

        if self.save_documents:
            return True

        return {
            'type': 'ir.actions.report',
            'report_name': 'lavish_hr_payroll.hr_report_income_and_withholdings',
            'report_type': 'qweb-pdf',
            'datas': datas
        }
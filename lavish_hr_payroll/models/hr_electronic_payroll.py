from odoo import models, fields, api, _, SUPERUSER_ID
from odoo.exceptions import UserError, ValidationError

from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from pytz import timezone
from lxml import etree

import random
import base64
import io
import uuid
import time

class hr_electronic_payroll_detail(models.Model):
    _name = 'hr.electronic.payroll.detail'
    _description = 'Nómina electrónica detalle'

    electronic_payroll_id = fields.Many2one('hr.electronic.payroll',string='Nómina electrónica', ondelete='cascade')
    employee_id = fields.Many2one('hr.employee',string='Empleado')
    contract_id = fields.Many2one('hr.contract', string='Contrato')
    item = fields.Integer(string='Item')
    sequence = fields.Char(string='Prefijo+Consecutivo')
    nonce = fields.Char(string='Nonce')
    transaction_id = fields.Char(string='Id Transacción')
    cune = fields.Char(string='CUNE')
    return_file_dian = fields.Binary(string='Archivo DIAN')
    payslip_ids = fields.Many2many('hr.payslip',string='Nóminas', domain="[('employee_id','=',employee_id)]")
    # XML
    xml_file = fields.Binary('XML')
    xml_file_name = fields.Char('XML name')
    result_upload_xml = fields.Text(string='Respuesta envio XML', readonly=True)
    status = fields.Char(string='Estado')
    result_status = fields.Text(string='Descripción estado', readonly=True)

    resource_type_document = fields.Selection([
        ('ORIGINAL_DOCUMENT', 'Documento original'),
        ('SIGNED_XML', 'XML firmado'),
        ('PDF', 'Archivo PDF'),
        ('DIAN_RESULT', 'Resultado Dian'),
        ('DOCUMENT_TRANSFORMED', 'Documento transformado a la salida'),
        ('ATTACHED_DOCUMENT', 'Attached document de nómina'),
    ], string='Tipo de archivo', default='PDF')
    data_file = fields.Binary('Data File')
    data_file_name = fields.Char('Data file name')

    def download_xml(self):
        action = {
            'name': 'XMLNominaElectronica',
            'type': 'ir.actions.act_url',
            'url': "web/content/?model=hr.electronic.payroll.detail&id=" + str(
                self.id) + "&filename_field=xml_file_name&field=xml_file&download=true&filename=" + self.xml_file_name,
            'target': 'self',
        }
        return action

    def get_xml(self):
        try:
            identificador = 'NomElectronica_' + str(self.electronic_payroll_id.company_id.payroll_electronic_operator)
            obj_xml = self.env['lavish.xml.generator.header'].search([('code', '=', identificador)])

            if len(obj_xml) > 0:
                xml = obj_xml.xml_generator(self)
            else:
                raise ValidationError(_("No ha configurado un XML con el identificador: '" + identificador + "', por favor verificar."))

            if str(self.electronic_payroll_id.company_id.payroll_electronic_operator) == 'FacturaTech':
                xml = xml.decode('utf-8').replace('SchemaLocation=""','SchemaLocation="" xsi:schemaLocation="dian:gov:co:facturaelectronica:NominaIndividual NominaIndividualElectronicaXSD.xsd"')
                xml = xml.replace('<UBLExtensions> </UBLExtensions>', '<ext:UBLExtensions/>')
                xml = bytes(xml, 'utf-8')

            filename = f'NominaElectronica{str(self.electronic_payroll_id.year)}-{self.electronic_payroll_id.month}_{str(self.employee_id.identification_id)}.xml'
            self.write({
                'xml_file': base64.encodestring(xml),
                'xml_file_name': filename,
                'status': False,
                'result_status': False,
            })
        except Exception as e:
            self.status = 'SIN XML'
            self.result_status = 'Empleado %s Error: %s' % (self.employee_id.name, e)

        return True

    def consume_web_service_send_xml(self):
        try:
            operator = str(self.electronic_payroll_id.company_id.payroll_electronic_operator)
            username = self.electronic_payroll_id.company_id.payroll_electronic_username_ws
            password = self.electronic_payroll_id.company_id.payroll_electronic_password_ws
            nonce = str(uuid.uuid4().hex) + str(uuid.uuid1().hex)
            date = datetime.now(timezone(self.env.user.tz)).strftime("%Y-%m-%d")
            time = datetime.now(timezone(self.env.user.tz)).strftime("%H:%M:%S")
            created = f'{str(date)}T{str(time)}-05:00'
            filename = self.xml_file_name
            filedata = str(self.xml_file).split("'")[1]
            company_id = self.electronic_payroll_id.company_id.payroll_electronic_company_id_ws
            account_id = self.electronic_payroll_id.company_id.payroll_electronic_account_id_ws
            service = self.electronic_payroll_id.company_id.payroll_electronic_service_ws

            #Ejecutar ws
            obj_ws = self.env['lavish.request.ws'].search([('name', '=', operator+'_ne_upload_xml')])
            if not obj_ws:
                raise ValidationError(_("Error! No ha configurado un web service con el nombre '"+operator+"_ne_upload_xml'"))

            if operator == 'Carvajal':
                result = obj_ws.connection_requests(username, password, nonce, created, filename, filedata, company_id,account_id, service, not_show_errors=1)
            if operator == 'FacturaTech':
                result = obj_ws.connection_requests(username, password, filedata, not_show_errors=1)
            self.result_upload_xml = result
            self.convert_result_send_xml(result)
        except Exception as e:
            self.status = 'ERROR AL ENVIAR XML'
            self.result_status = 'Empleado %s Error: %s' % (self.employee_id.name, str(e))

    def convert_result_send_xml(self,result=''):
        operator = str(self.electronic_payroll_id.company_id.payroll_electronic_operator)
        if result == '':
            result = self.result_upload_xml

        if operator == 'Carvajal':
            if result.find('<status>') > -1:
                status = result[result.find('<status>') + len('<status>'):result.find('</status>')]
                self.result_upload_xml = f'Status: {status}'
            if result.find('<transactionId>') > -1:
                transaction_id = result[result.find('<transactionId>') + len('<transactionId>'):result.find('</transactionId>')]
                self.transaction_id = transaction_id
        if operator == 'FacturaTech':
            if result.find('<transactionID xsi:type="xsd:string">') > -1:
                transaction_id = result[result.find('<transactionID xsi:type="xsd:string">') + len(
                    '<transactionID xsi:type="xsd:string">'):result.find('</transactionID>')]
                if transaction_id == '':
                    if result.find('<error xsi:type="xsd:string">El comprobante  ya ha sido firmado previamente. TrasactionID ') > -1:
                        transaction_id = result[result.find('<error xsi:type="xsd:string">El comprobante  ya ha sido firmado previamente. TrasactionID ') + len('<error xsi:type="xsd:string">El comprobante  ya ha sido firmado previamente. TrasactionID '):result.find('</error>')]
                    if transaction_id == '':
                        self.status = 'ERROR AL ENVIAR XML'
                    else:
                        self.status = 'XML ENVIADO'
                        self.transaction_id = transaction_id
                else:
                    self.status = 'XML ENVIADO'
                    self.transaction_id = transaction_id

    def consume_web_service_status_document(self):
        try:
            operator = str(self.electronic_payroll_id.company_id.payroll_electronic_operator)
            username = self.electronic_payroll_id.company_id.payroll_electronic_username_ws
            password = self.electronic_payroll_id.company_id.payroll_electronic_password_ws
            nonce = str(uuid.uuid4().hex) + str(uuid.uuid1().hex)
            date = datetime.now(timezone(self.env.user.tz)).strftime("%Y-%m-%d")
            time = datetime.now(timezone(self.env.user.tz)).strftime("%H:%M:%S")
            created = f'{str(date)}T{str(time)}-05:00'
            company_id = self.electronic_payroll_id.company_id.payroll_electronic_company_id_ws
            account_id = self.electronic_payroll_id.company_id.payroll_electronic_account_id_ws
            transaction_id = self.transaction_id
            service = self.electronic_payroll_id.company_id.payroll_electronic_service_ws
            # Ejecutar ws
            result_status = ''
            message = ''
            obj_ws = self.env['lavish.request.ws'].search([('name', '=', operator + '_ne_status_document')])
            if not obj_ws:
                raise ValidationError(_("Error! No ha configurado un web service con el nombre '"+operator+"_ne_status_document'"))
            if operator == 'Carvajal':
                result = obj_ws.connection_requests(username, password, nonce, created, company_id,
                                                    account_id, transaction_id, service)

                result_status = ''
                if result.find('<processName>') > -1:
                    result_status = 'Último proceso realizado: '+result[result.find('<processName>') + len('<processName>'):result.find('</processName>')] +'\n'
                if result.find('<processStatus>') > -1:
                    result_status = result_status + 'Estado último proceso realizado: '+result[result.find('<processStatus>') + len('<processStatus>'):result.find('</processStatus>')] +'\n'
                if result.find('<processDate>') > -1:
                    result_status = result_status + 'Fecha último proceso realizado: '+result[result.find('<processDate>') + len('<processDate>'):result.find('</processDate>')] +'\n'
                if result.find('<legalStatus>') > -1:
                    result_status = result_status + 'Estado legal del documento, con base a la información recibida por la DIAN: '+result[result.find('<legalStatus>') + len('<legalStatus>'):result.find('</legalStatus>')] +'\n'
                    self.status = result[result.find('<legalStatus>') + len('<legalStatus>'):result.find('</legalStatus>')]
                if result.find('<governmentResponseDescription>') > -1:
                    result_status = result_status + 'Descripción: '+result[result.find('<governmentResponseDescription>') + len('<governmentResponseDescription>'):result.find('</governmentResponseDescription>')] +'\n'
            if operator == 'FacturaTech':
                result = obj_ws.connection_requests(username, password, transaction_id)
                if result.find('<code xsi:type="xsd:string">') > -1:
                    result_status = 'Code: ' + result[result.find('<code xsi:type="xsd:string">') + len(
                        '<code xsi:type="xsd:string">'):result.find('</code>')] + '\n'
                if result.find('<message xsi:type="xsd:string">') > -1:
                    result_status = result_status + 'Mensaje: ' + result[result.find('<message xsi:type="xsd:string">') + len('<message xsi:type="xsd:string">'):result.find('</message>')] + '\n'
                    message = result[result.find('<message xsi:type="xsd:string">') + len('<message xsi:type="xsd:string">'):result.find('</message>')]
                if result.find('<messageError xsi:type="xsd:string">') > -1:
                    result_status = result_status + 'Mensaje Error: ' + result[result.find('<messageError xsi:type="xsd:string">') + len('<messageError xsi:type="xsd:string">'):result.find('</messageError>')] + '\n'
                if message == f'El comprobante {str(self.sequence)} ha sido autorizado':
                    self.status = 'ACCEPTED'
                else:
                    self.status = 'REJECTED'

            self.result_status = result_status
        except Exception as e:
            self.status = 'REJECTED'
            self.result_status = 'Empleado %s Error: %s' % (self.employee_id.name, str(e))

    def consume_web_service_download_files(self):
        operator = str(self.electronic_payroll_id.company_id.payroll_electronic_operator)
        username = self.electronic_payroll_id.company_id.payroll_electronic_username_ws
        password = self.electronic_payroll_id.company_id.payroll_electronic_password_ws
        nonce = str(uuid.uuid4().hex) + str(uuid.uuid1().hex)
        date = datetime.now(timezone(self.env.user.tz)).strftime("%Y-%m-%d")
        time = datetime.now(timezone(self.env.user.tz)).strftime("%H:%M:%S")
        created = f'{str(date)}T{str(time)}-05:00'
        company_id = self.electronic_payroll_id.company_id.payroll_electronic_company_id_ws
        account_id = self.electronic_payroll_id.company_id.payroll_electronic_account_id_ws
        document_type = 'NM'
        document_number = self.sequence
        resource_type = self.resource_type_document
        service = self.electronic_payroll_id.company_id.payroll_electronic_service_ws
        # Ejecutar ws
        obj_ws = self.env['lavish.request.ws'].search([('name', '=', operator+'_ne_download_file_document')])
        if not obj_ws:
            raise ValidationError(_("Error! No ha configurado un web service con el nombre '"+operator+"_ne_download_file_document'"))
        if operator == 'Carvajal':
            result = obj_ws.connection_requests(username, password, nonce, created, company_id,
                                                account_id, document_type, document_number, resource_type, service)
            if result.find('<downloadData>') > -1:
                download_data = result[result.find('<downloadData>') + len('<downloadData>'):result.find('</downloadData>')]

                filename = f'{self.resource_type_document}_{str(self.electronic_payroll_id.year)}-{self.electronic_payroll_id.month}_{str(self.employee_id.identification_id)}'
                filename = filename+'.pdf' if self.resource_type_document == 'PDF' else filename+'.xml'

                self.write({
                    'data_file': download_data,
                    'data_file_name': filename,
                })
            else:
                raise ValidationError(_('Error al descargar el archivo, intente mas tarde.'))
        elif operator == 'FacturaTech':
            if self.resource_type_document == 'PDF':
                result = obj_ws.connection_requests(username, password, self.electronic_payroll_id.prefix, self.item)
                if result.find('<documentBase64 xsi:type="xsd:string">') > -1:
                    download_data = result[result.find('<documentBase64 xsi:type="xsd:string">') + len(
                        '<documentBase64 xsi:type="xsd:string">'):result.find('</documentBase64>')]

                    filename = f'{self.resource_type_document}_{str(self.electronic_payroll_id.year)}-{self.electronic_payroll_id.month}_{str(self.employee_id.identification_id)}'
                    filename = filename + '.pdf' if self.resource_type_document == 'PDF' else filename + '.xml'

                    self.write({
                        'data_file': download_data,
                        'data_file_name': filename,
                    })
                else:
                    raise ValidationError(_('Error al descargar el archivo, intente mas tarde.'))
            else:
                raise ValidationError(_("Solo es posible descargar el Archivo PDF"))
        else:
            raise ValidationError(_('Error al descargar el archivo, intente mas tarde.'))

        action = {
            'name': self.resource_type_document,
            'type': 'ir.actions.act_url',
            'url': "web/content/?model=hr.electronic.payroll.detail&id=" + str(
                self.id) + "&filename_field=data_file_name&field=data_file&download=true&filename=" + self.data_file_name,
            'target': 'self',
        }
        return action

    def consume_web_service_get_cune(self):
        try:
            operator = str(self.electronic_payroll_id.company_id.payroll_electronic_operator)
            username = self.electronic_payroll_id.company_id.payroll_electronic_username_ws
            password = self.electronic_payroll_id.company_id.payroll_electronic_password_ws
            nonce = self.nonce + '_' + str(uuid.uuid4())
            date = datetime.now(timezone(self.env.user.tz)).strftime("%Y-%m-%d")
            time = datetime.now(timezone(self.env.user.tz)).strftime("%H:%M:%S")
            created = f'{str(date)}T{str(time)}-05:00'
            company_id = self.electronic_payroll_id.company_id.payroll_electronic_company_id_ws
            account_id = self.electronic_payroll_id.company_id.payroll_electronic_account_id_ws
            document_type = 'NM'
            document_number = self.sequence
            resource_type = self.resource_type_document
            service = self.electronic_payroll_id.company_id.payroll_electronic_service_ws
            # Ejecutar ws
            obj_ws = self.env['lavish.request.ws'].search([('name', '=', operator + '_ne_get_cune')])
            if not obj_ws:
                raise ValidationError(_("Error! No ha configurado un web service con el nombre '" + operator + "_ne_get_cune'"))
            if operator == 'Carvajal':
                raise ValidationError(_('Carvajal no tiene esta funcionalidad.'))
            elif operator == 'FacturaTech':
                result = obj_ws.connection_requests(username, password, self.electronic_payroll_id.prefix, self.item,
                                                    not_show_errors=1)
                if result.find('<resourceData xsi:type="xsd:string">') > -1:
                    cune = result[result.find('<resourceData xsi:type="xsd:string">') + len('<resourceData xsi:type="xsd:string">'):result.find('</resourceData>')]
                    self.cune = cune
        except Exception as e:
            print('Empleado %s Error: %s' % (self.employee_id.name, str(e)))

    def get_type_contract(self):
        type = self.contract_id.contract_type
        if type == 'fijo':
            type = '1' # Contrato de Trabajo a Término Fijo
        elif type == 'indefinido':
            type = '2' # Contrato de Trabajo a Término Indefinido
        elif type == 'obra' or type == 'temporal':
            type = '3' # Contrato por Obra o Labor
        elif type == 'aprendizaje':
            type = '4' # Aprendizaje
        else:
            type = '0'
        # type = 5 | Practicante
        return type

    def get_date_now(self):
        return str(datetime.now(timezone(self.env.user.tz)).date())

    def get_time_now(self):
        time = datetime.now(timezone(self.env.user.tz)).strftime("%H:%M:%S")
        return time+'-05:00' # https://24timezones.com/es/difference/gmt/bogota

    def get_dates_process(self,end=0): #Si se envia el parametro end en 1 retornara la fecha final del periodo sino retornara fecha inicial.
        try:
            date_start = '01/' + str(self.electronic_payroll_id.month) + '/' + str(self.electronic_payroll_id.year)
            date_start = datetime.strptime(date_start, '%d/%m/%Y')

            date_end = date_start + relativedelta(months=1)
            date_end = date_end - timedelta(days=1)

            date_start = date_start.date()
            date_end = date_end.date()

            if end == 1:
                return str(date_end)
            else:
                return str(date_start)
        except:
            raise UserError(_('El año digitado es invalido, por favor verificar.'))

    def get_time_working(self):
        date_start = self.contract_id.date_start
        date_end = datetime.strptime(self.get_dates_process(end=1), '%Y-%m-%d').date() if not self.contract_id.retirement_date else self.contract_id.retirement_date
        dias = self.dias360(date_start,date_end)
        return dias

    def get_bank_information(self,r_bank=0,r_type=0,r_account=0):
        for bank in self.employee_id.work_contact_id.bank_ids:
            if bank.is_main:
                if r_bank != 0:
                    return bank.bank_id.name
                if r_type != 0:
                    return bank.type_account
                if r_account != 0:
                    return bank.acc_number

    def get_dates_payment_payrolls(self):
        dates = []
        for payslip in self.payslip_ids:
            dates.append(str(payslip.date_to))
        return dates

    def get_days_lines(self,lst_codes):
        days = 0
        for payslip in self.payslip_ids:
            for entries in payslip.worked_days_line_ids:
                days += entries.number_of_days if entries.work_entry_type_id.code in lst_codes else 0
        return int(days)

    def get_value_salary_rules(self,lst_codes):
        value = 0
        for payslip in self.payslip_ids:
            for line in payslip.line_ids:
                value += abs(line.total) if line.salary_rule_id.code in lst_codes else 0
        return value

    def get_quantity_salary_rules(self,lst_codes):
        quantity = 0
        for payslip in self.payslip_ids:
            for line in payslip.line_ids:
                quantity += abs(line.quantity) if line.salary_rule_id.code in lst_codes else 0
        return quantity

    def get_annual_parameters(self):
        obj = self.env['hr.annual.parameters'].search([('year', '=', self.electronic_payroll_id.year)])
        return obj

    def get_type_overtime(self,equivalence_number_ne):
        obj = self.env['hr.type.overtime'].search([('equivalence_number_ne', '=', equivalence_number_ne)], limit=1)
        return obj

    def get_porc_fsp(self):
        porc = 0
        annual_parameters = self.env['hr.annual.parameters'].search([('year', '=', self.electronic_payroll_id.year)])
        value_base = 0
        for payslip in self.payslip_ids:
            for line in payslip.line_ids:
                value_base += abs(line.total) if line.salary_rule_id.category_id.code == 'DEV_SALARIAL' or line.salary_rule_id.category_id.parent_id.code == 'DEV_SALARIAL' else 0

        if (value_base / annual_parameters.smmlv_monthly) >= 4 and (
                value_base / annual_parameters.smmlv_monthly) < 16:
            porc = 1
        if (value_base / annual_parameters.smmlv_monthly) >= 16 and (
                value_base / annual_parameters.smmlv_monthly) <= 17:
            porc = 1.2
        if (value_base / annual_parameters.smmlv_monthly) > 17 and (
                value_base / annual_parameters.smmlv_monthly) <= 18:
            porc = 1.4
        if (value_base / annual_parameters.smmlv_monthly) > 18 and (
                value_base / annual_parameters.smmlv_monthly) <= 19:
            porc = 1.6
        if (value_base / annual_parameters.smmlv_monthly) > 19 and (
                value_base / annual_parameters.smmlv_monthly) <= 20:
            porc = 1.8
        if (value_base / annual_parameters.smmlv_monthly) > 20:
            porc = 2

        return porc

class hr_electronic_payroll(models.Model):
    _name = 'hr.electronic.payroll'
    _description = 'Nómina electrónica'

    year = fields.Integer('Año', required=True, copy=False, default=fields.Date.today().year)
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
                            ], string='Mes', required=True, copy=False, default=str(fields.Date.today().month))
    observations = fields.Text('Observaciones', copy=False)
    state = fields.Selection([
            ('draft', 'Borrador'),
            ('xml', 'XML Generados'),
            ('ws', 'Enviados por WS'),
            ('close', 'Finalizado'),
        ], string='Estado', default='draft', copy=False)
    #Proceso
    prefix = fields.Char(string='Prefijo', required=True)
    qty_failed = fields.Integer(string='Cantidad Fallidos / Sin Respuesta', default=0, copy=False)
    qty_done = fields.Integer(string='Cantidad Aceptados', default=0, copy=False)
    executing_electronic_payroll_ids = fields.One2many('hr.electronic.payroll.detail', 'electronic_payroll_id', string='Ejecución')
    time_process = fields.Char(string='Tiempo ejecución', copy=False)
    
    company_id = fields.Many2one('res.company', string='Compañía', readonly=True, required=True,
        default=lambda self: self.env.company)

    _sql_constraints = [('electronic_payroll_period_uniq', 'unique(company_id,year,month)', 'El periodo seleccionado ya esta registrado para esta compañía, por favor verificar.')]

    def name_get(self):
        result = []
        for record in self:
            result.append((record.id, "Nómina Electrónica | Periodo {}-{}".format(record.month,str(record.year))))
        return result

    def executing_electronic_payroll(self):
        # Eliminar ejecución
        self.env['hr.electronic.payroll.detail'].search([('electronic_payroll_id', '=', self.id)]).unlink()

        # Obtener fechas del periodo seleccionado
        date_start = '01/' + str(self.month) + '/' + str(self.year)
        try:
            date_start = datetime.strptime(date_start, '%d/%m/%Y')

            date_end = date_start + relativedelta(months=1)
            date_end = date_end - timedelta(days=1)

            date_start = date_start.date()
            date_end = date_end.date()
        except:
            raise UserError(_('El año digitado es invalido, por favor verificar.'))

        #Validar que todas las reglas salariales sean usadas en el proceso de Nómina electronica
        identificador = 'NomElectronica_' + str(self.company_id.payroll_electronic_operator)
        obj_salary_rules_value_zero = self.env['hr.salary.rule'].search([('active', '=', True), ('amount_select', '=', 'fix'), ('amount_fix', '=', 0.00)])
        obj_salary_rules_value_null = self.env['hr.salary.rule'].search([('active', '=', True), ('amount_select', '=', 'fix'), ('amount_fix', '=', False)])
        obj_salary_rules = self.env['hr.salary.rule'].search(
            [('active', '=', True), ('type_concepts', '!=', 'tributaria'), ('category_id.code', '!=', 'HEYREC'),
             ('id', 'not in', obj_salary_rules_value_zero.ids),('id', 'not in', obj_salary_rules_value_null.ids)])
        obj_xml = self.env['lavish.xml.generator.header'].search([('code', '=', identificador)])

        lst_rule_not_include = []
        for rule in obj_salary_rules:
            lst_rule_include = []
            for tags_xml in obj_xml.details_ids:
                if tags_xml.code_python or tags_xml.attributes_code_python:
                    if str(tags_xml.code_python).find(rule.code) != -1 or str(tags_xml.attributes_code_python).find(rule.code) != -1:
                         lst_rule_include.append(rule.code)
            if len(lst_rule_include) == 0:
                lst_rule_not_include.append(rule.code)

        if len(lst_rule_not_include) >= 1:
            raise ValidationError(_(f'Las siguentes reglas salariales no estan asociadas a ningun tag {str(lst_rule_not_include)}.'))

        # Obtener empleados que tuvieron liquidaciones en el mes
        query = '''
            select distinct b.id 
            from hr_payslip a 
            inner join hr_employee b on a.employee_id = b.id 
            where a.state = 'done' and a.date_from >= '%s' and a.date_from <= '%s' and a.company_id = %s
        ''' % (date_start, date_end, self.company_id.id)

        self.env.cr.execute(query)
        result_query = self.env.cr.fetchall()

        employee_ids = []
        for result in result_query:
            employee_ids.append(result)
        obj_employee = self.env['hr.employee'].search([('id', 'in', employee_ids)])

        query_max_item = '''
        Select max(next_item) as next_item from 
        (
        Select max(a.item) as next_item from hr_electronic_payroll_detail as a 
        inner join hr_electronic_payroll as b on a.electronic_payroll_id = b.id and b.prefix = '%s' and b.id != %s
        union
        Select coalesce(max(a.item),0) as next_item from hr_electronic_adjust_payroll_detail as a 
        inner join hr_electronic_adjust_payroll as b on a.electronic_adjust_payroll_id = b.id and b.prefix = '%s' 
        ) as a        
        ''' % (self.prefix, self.id, self.prefix)
        self.env.cr.execute(query_max_item)
        res_max_item = self.env.cr.fetchone()
        max_item = res_max_item[0] or 0

        item = 0
        for employee in obj_employee:
            obj_contracts = self.env['hr.contract']
            # Obtener contrato activo
            obj_contracts += self.env['hr.contract'].search([('state', '=', 'open'), ('employee_id', '=', employee.id), ('date_start','<=',date_end)])
            # Obtener contratos finalizados en el mes
            obj_contracts += self.env['hr.contract'].search([('state', '=', 'close'), ('employee_id', '=', employee.id), ('retirement_date', '>=', date_start), ('retirement_date', '<=', date_end)])

            for obj_contract in obj_contracts:
                item += 1
                # Obtener nóminas en ese rango de fechas
                obj_payslip = self.env['hr.payslip'].search(
                    [('state', '=', 'done'), ('employee_id', '=', employee.id), ('contract_id', '=', obj_contract.id),
                     ('date_from', '>=', date_start), ('date_from', '<=', date_end)])
                obj_payslip += self.env['hr.payslip'].search(
                    [('state', '=', 'done'), ('employee_id', '=', employee.id), ('contract_id', '=', obj_contract.id),
                     ('id', 'not in', obj_payslip.ids),('struct_id.process', 'in', ['cesantias', 'intereses_cesantias', 'prima']),
                     ('date_to', '>=', date_start), ('date_to', '<=', date_end)])

                value_detail = {
                    'electronic_payroll_id':self.id,
                    'employee_id':employee.id,
                    'contract_id':obj_contract.id,
                    'item':item+max_item,
                    'sequence': self.prefix+''+str(item+max_item),
                    'nonce': 'lavish_NOMINAELECTRONICA_'+self.prefix+''+str(item+max_item),
                    'payslip_ids':[(6, 0, obj_payslip.ids)]
                }

                self.env['hr.electronic.payroll.detail'].create(value_detail)

        for detail in self.executing_electronic_payroll_ids:
            detail.get_xml()

        self.write({'state':'xml'})

    def executing_electronic_payroll_failed(self):
        for record in self.executing_electronic_payroll_ids:
            if record.status:
                if record.status != 'ACCEPTED': # and record.status != ''
                    record.get_xml()
            else:
                #if not record.transaction_id:
                record.get_xml()

    def consume_ws(self):
        count = 1
        count_all = 1
        operator = str(self.company_id.payroll_electronic_operator)
        for record in self.executing_electronic_payroll_ids:
            if record.status:
                if record.status != 'ACCEPTED':
                    record.consume_web_service_send_xml()
                    if operator == 'FacturaTech':
                        # Tiempo de espera de 10 segundos por cada 15 envios
                        count += 1
                        count_all += 1
                        if count == 15:
                            time.sleep(10)
                            count = 1
                        if count_all == 450:
                            break
            else:
                # if not record.transaction_id:
                record.consume_web_service_send_xml()
                if operator == 'FacturaTech':
                    # Tiempo de espera de 10 segundos por cada 15 envios
                    count += 1
                    count_all += 1
                    if count == 15:
                        time.sleep(10)
                        count = 1
                    if count_all == 450:
                        break
        self.write({'state': 'ws'})

    def consume_ws_failed(self):
        count = 1
        count_all = 1
        operator = str(self.company_id.payroll_electronic_operator)
        for record in self.executing_electronic_payroll_ids:
            if record.status:
                if record.status != 'ACCEPTED': #and record.status != ''
                    record.consume_web_service_send_xml()
                    if operator == 'FacturaTech':
                        # Tiempo de espera de 10 segundos por cada 15 envios
                        count += 1
                        count_all += 1
                        if count == 15:
                            time.sleep(10)
                            count = 1
                        if count_all == 450:
                            break
            else:
                #if not record.transaction_id:
                record.consume_web_service_send_xml()
                if operator == 'FacturaTech':
                    # Tiempo de espera de 10 segundos por cada 15 envios
                    count += 1
                    count_all += 1
                    if count == 15:
                        time.sleep(10)
                        count = 1
                    if count_all == 450:
                        break

    def consume_web_service_status_document_all(self):
        qty_failed = 0
        qty_done = 0
        count = 1
        count_all = 1
        operator = str(self.company_id.payroll_electronic_operator)
        for record in self.executing_electronic_payroll_ids:
            if record.status != 'ACCEPTED' and record.transaction_id:
                record.consume_web_service_status_document()
                if operator == 'FacturaTech':
                    # Tiempo de espera de 10 segundos por cada 15 envios
                    count += 1
                    count_all += 1
                    if count == 15:
                        time.sleep(10)
                        count = 1
                    if count_all == 450:
                        break
            if record.status != 'ACCEPTED':
                qty_failed += 1
            else:
                qty_done += 1

        self.write({'qty_failed':qty_failed,
                    'qty_done':qty_done})

        if qty_failed == 0:
            self.write({'state': 'close'})

    def consume_web_service_get_cune_all(self):
        count = 1
        count_all = 1
        operator = str(self.company_id.payroll_electronic_operator)
        for record in self.executing_electronic_payroll_ids:
            if not record.cune:
                record.consume_web_service_get_cune()
                if operator == 'FacturaTech':
                    # Tiempo de espera de 10 segundos por cada 15 envios
                    count += 1
                    count_all += 1
                    if count == 15:
                        time.sleep(10)
                        count = 1
                    if count_all == 450:
                        break

    def convert_result_send_xml_all(self):
        for record in self.executing_electronic_payroll_ids:
            record.convert_result_send_xml()

    def cancel_process(self):
        self.env['hr.electronic.payroll.detail'].search([('electronic_payroll_id', '=', self.id)]).unlink()
        self.write({'state': 'draft'})

    def unlink(self):
        for record in self:
            if record.state != 'draft':
                raise ValidationError(_('No se puede eliminar debido a que su estado es diferente de borrador.'))
        return super(hr_electronic_payroll, self).unlink()

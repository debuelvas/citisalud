from odoo import  _, api, fields, models, tools
import zipfile
from io import BytesIO
import base64
import logging
_logger = logging.getLogger(__name__)


import sys
import importlib
importlib.reload(sys)
import base64
import re
from io import StringIO ## for Python 3
from datetime import datetime, timedelta
from base64 import b64encode, b64decode
from zipfile import ZipFile
from . import global_functions
from pytz import timezone
from requests import post, exceptions
from lxml import etree
from odoo import models, fields, _, api
from odoo.exceptions import ValidationError, UserError
from odoo.http import request
import logging
_logger = logging.getLogger(__name__)

import ssl

ssl._create_default_https_context = ssl._create_unverified_context

DIAN = {'wsdl-hab': 'https://vpfe-hab.dian.gov.co/WcfDianCustomerServices.svc?wsdl',
        'wsdl': 'https://vpfe.dian.gov.co/WcfDianCustomerServices.svc?wsdl',
        'catalogo-hab': 'https://catalogo-vpfe-hab.dian.gov.co/Document/FindDocument?documentKey={}&partitionKey={}&emissionDate={}',
        'catalogo': 'https://catalogo-vpfe.dian.gov.co/Document/FindDocument?documentKey={}&partitionKey={}&emissionDate={}'}
class DianDocument(models.Model):
    _inherit = "dian.document"

    get_status_zip_status_code = fields.Selection([('00', 'Procesado Correctamente'),
                                                   ('66', 'NSU no encontrado'),
                                                   ('90', 'TrackId no encontrado'),
                                                   ('99', 'Validaciones contienen errores en campos mandatorios'),
                                                   ('other', 'Other')], string='StatusCode', default=False)
    get_status_zip_response = fields.Text(string='Response')

    def make_zip(self, FileNameXML, file):
        output = BytesIO()
        with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(FileNameXML, file)
        return output

    def _generate_files(self, data_xml_document):
        # files = []
        output = BytesIO()
        output.write(str(data_xml_document).encode())
        output.seek(0)
        # files.append((FileNameXML, output.read()))
        return output.read()

    def _generate_zip_content(self, FileNameXML, FileNameZIP, data_xml_document, document_repository):
        files = self._generate_files(data_xml_document)
        zipfiles = self.make_zip(FileNameXML, files)
        zipfiles.seek(0)
        contenido_data_xml_b64 = base64.b64encode(zipfiles.read())
        contenido_data_xml_b64 = contenido_data_xml_b64.decode()
        return contenido_data_xml_b64
 
    def _template_basic_data_fe_xml(self):
        template = super()._template_basic_data_fe_xml()
        if self.document_id.partner_id.l10n_latam_identification_type_id.l10n_co_document_code != "rut" and self.document_id.move_type != 'in_invoice':
            template = template.replace('<cbc:ID schemeName="%(SchemeNameAdquiriente)s" schemeID="%(SchemeIDAdquiriente)s">%(IDAdquiriente)s</cbc:ID>','<cbc:ID schemeName="%(SchemeNameAdquiriente)s">%(IDAdquiriente)s</cbc:ID>')
            template = template.replace('<cbc:CompanyID schemeAgencyID="195" schemeAgencyName="CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)" schemeID="%(CustomerschemeID)s" schemeName="31">%(CustomerID)s</cbc:CompanyID>','<cbc:CompanyID schemeAgencyID="195" schemeAgencyName="CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)"  schemeName="%(SchemeNameAdquiriente)s">%(CustomerID)s</cbc:CompanyID>')
        if self.document_id.partner_id.l10n_latam_identification_type_id.l10n_co_document_code != "rut" and self.document_id.partner_id.country_id.code != "CO" and self.document_id.move_type != 'in_invoice':
            template = template.replace("<cbc:ID>%(CustomerCityCode)s</cbc:ID>",'')
            template = template.replace("<cbc:CityName>%(CustomerCityName)s</cbc:CityName>",'')
            template = template.replace("<cbc:CountrySubentity>%(CustomerCountrySubentity)s</cbc:CountrySubentity>",'')
            template = template.replace("<cbc:CountrySubentityCode>%(CustomerCountrySubentityCode)s</cbc:CountrySubentityCode>",'')
            template = template.replace('<cbc:ID schemeName="%(SchemeNameAdquiriente)s" schemeID="%(SchemeIDAdquiriente)s">%(IDAdquiriente)s</cbc:ID>','<cbc:ID schemeName="%(SchemeNameAdquiriente)s">%(IDAdquiriente)s</cbc:ID>')
        if self.document_id.partner_id.l10n_latam_identification_type_id.l10n_co_document_code != "rut" and self.document_id.partner_id.country_id.code != "CO" and self.document_id.move_type == 'in_invoice':
            template = template.replace("<cbc:ID>%(SupplierCityCode)s</cbc:ID>",'<cbc:ID/>')
            #template = template.replace("<cbc:CityName>%(SupplierCityName)s</cbc:CityName>",'<cbc:CityName/>')
            template = template.replace("<cbc:CountrySubentity>%(SupplierCountrySubentity)s</cbc:CountrySubentity>",'<cbc:CountrySubentity/>')
            template = template.replace("<cbc:CountrySubentityCode>%(SupplierCountrySubentityCode)s</cbc:CountrySubentityCode>",'<cbc:CountrySubentityCode/>')
            template = template.replace('<cbc:PostalZone>%(SupplierPostal)s</cbc:PostalZone>','<cbc:PostalZone/>')
            template = template.replace('<cbc:CompanyID schemeAgencyID="195" schemeAgencyName="CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)" schemeID="%(schemeID)s" schemeName="31">%(ProviderID)s</cbc:CompanyID>','<cbc:CompanyID schemeAgencyID="195" schemeAgencyName="CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)" schemeName="%(SupplierSchemeName)s">%(ProviderID)s</cbc:CompanyID>')
        return template

    def _template_basic_data_nc_xml(self):
        template = super()._template_basic_data_nc_xml()
        if self.document_id.partner_id.l10n_latam_identification_type_id.l10n_co_document_code != "rut" and self.document_id.move_type != 'in_invoice':
            template = template.replace('<cbc:ID schemeName="%(SchemeNameAdquiriente)s" schemeID="%(SchemeIDAdquiriente)s">%(IDAdquiriente)s</cbc:ID>','<cbc:ID schemeName="%(SchemeNameAdquiriente)s">%(IDAdquiriente)s</cbc:ID>')
            template = template.replace('<cbc:CompanyID schemeAgencyID="195" schemeAgencyName="CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)" schemeID="%(CustomerschemeID)s" schemeName="31">%(CustomerID)s</cbc:CompanyID>','<cbc:CompanyID schemeAgencyID="195" schemeAgencyName="CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)"  schemeName="%(SchemeNameAdquiriente)s">%(CustomerID)s</cbc:CompanyID>')
        if self.document_id.partner_id.l10n_latam_identification_type_id.l10n_co_document_code != "rut" and self.document_id.partner_id.country_id.code != "CO" and self.document_id.move_type != 'in_refund':
            template = template.replace("<cbc:ID>%(CustomerCityCode)s</cbc:ID>",'')
            template = template.replace("<cbc:CityName>%(CustomerCityName)s</cbc:CityName>",'')
            template = template.replace("<cbc:CountrySubentity>%(CustomerCountrySubentity)s</cbc:CountrySubentity>",'')
            template = template.replace("<cbc:CountrySubentityCode>%(CustomerCountrySubentityCode)s</cbc:CountrySubentityCode>",'')
            template = template.replace('<cbc:ID schemeName="%(SchemeNameAdquiriente)s" schemeID="%(SchemeIDAdquiriente)s">%(IDAdquiriente)s</cbc:ID>','<cbc:ID schemeName="%(SchemeNameAdquiriente)s">%(IDAdquiriente)s</cbc:ID>')
        if self.document_id.partner_id.l10n_latam_identification_type_id.l10n_co_document_code != "rut" and self.document_id.partner_id.country_id.code != "CO" and self.document_id.move_type == 'in_refund':
            template = template.replace("<cbc:ID>%(SupplierCityCode)s</cbc:ID>",'<cbc:ID/>')
            #template = template.replace("<cbc:CityName>%(SupplierCityName)s</cbc:CityName>",'<cbc:CityName/>')
            template = template.replace("<cbc:CountrySubentity>%(SupplierCountrySubentity)s</cbc:CountrySubentity>",'<cbc:CountrySubentity/>')
            template = template.replace("<cbc:CountrySubentityCode>%(SupplierCountrySubentityCode)s</cbc:CountrySubentityCode>",'<cbc:CountrySubentityCode/>')
            #template = template.replace('<cbc:PostalZone>%(SupplierPostal)s</cbc:PostalZone>','<cbc:PostalZone/>')
            template = template.replace('<cbc:CompanyID schemeAgencyID="195" schemeAgencyName="CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)" schemeID="%(schemeID)s" schemeName="31">%(ProviderID)s</cbc:CompanyID>','<cbc:CompanyID schemeAgencyID="195" schemeAgencyName="CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)" schemeName="%(SupplierSchemeName)s">%(ProviderID)s</cbc:CompanyID>')
        return template

    def _generate_data_fe_document_xml(self,
                                    template_basic_data_fe_xml,
                                    dc,
                                    dcd,
                                    data_taxs_xml,
                                    data_lines_xml,
                                    CUFE,
                                    data_xml_signature):

        res = super()._generate_data_fe_document_xml(template_basic_data_fe_xml,
                                                    dc,
                                                    dcd,
                                                    data_taxs_xml,
                                                    data_lines_xml,
                                                    CUFE,
                                                    data_xml_signature)

        if self.document_id.ref and self.document_id.move_type == "out_invoice":
            txt = """</cbc:LineCountNumeric>
                    <cac:OrderReference>
                        <cbc:ID>%s</cbc:ID>
                        <cbc:IssueDate>date</cbc:IssueDate>
                    </cac:OrderReference>
                """ % self.document_id.ref
            if self.document_id.order_reference_date:
                ref_date = (self.document_id.order_reference_date).strftime("%Y-%m-%d")
                ref_d = "<cbc:IssueDate>%s</cbc:IssueDate>" % ref_date
                txt = txt.replace("<cbc:IssueDate>date</cbc:IssueDate>", ref_d)
            else:
                txt = txt.replace("<cbc:IssueDate>date</cbc:IssueDate>","")
            res = res.replace("</cbc:LineCountNumeric>", txt)

        # if self.document_id.partner_id.l10n_latam_identification_type_id.l10n_co_document_code != "rut" and self.document_id.partner_id.country_id.code != "CO":
        #     txt_2 = """ <cac:AccountingCustomerParty>
        #                     <cbc:AdditionalAccountID>{CustomerAdditionalAccountID}</cbc:AdditionalAccountID>
        #                     <cac:Party>
        #                         <cac:PartyIdentification>
        #                             <cbc:ID schemeName="{SchemeNameAdquiriente}">{IDAdquiriente}</cbc:ID>
        #                         </cac:PartyIdentification>
        #                         <cac:PartyName>
        #                             <cbc:Name>{CustomerPartyName}</cbc:Name>
        #                         </cac:PartyName>
        #                         <cac:PhysicalLocation>
        #                             <cac:Address>
        #                                 <cac:AddressLine>
        #                                     <cbc:Line>{CustomerLine}</cbc:Line>
        #                                 </cac:AddressLine>
        #                                 <cac:Country>
        #                                     <cbc:IdentificationCode>{CustomerCountryCode}</cbc:IdentificationCode>
        #                                     <cbc:Name languageID="es">{CustomerCountryName}</cbc:Name>
        #                                 </cac:Country>
        #                             </cac:Address>
        #                         </cac:PhysicalLocation>
        #                         <cac:PartyTaxScheme>
        #                             <cbc:RegistrationName>{CustomerPartyName}</cbc:RegistrationName>
        #                             <cbc:CompanyID schemeAgencyID="195" schemeAgencyName="CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)" schemeName="31">{CustomerID}</cbc:CompanyID>
        #                             <cbc:TaxLevelCode listName="48">{CustomerTaxLevelCode}</cbc:TaxLevelCode>
        #                             <cac:RegistrationAddress>
        #                                 <cac:AddressLine>
        #                                     <cbc:Line>{CustomerLine}</cbc:Line>
        #                                 </cac:AddressLine>
        #                                 <cac:Country>
        #                                     <cbc:IdentificationCode>{CustomerCountryCode}</cbc:IdentificationCode>
        #                                     <cbc:Name languageID="es">{CustomerCountryName}</cbc:Name>
        #                                 </cac:Country>
        #                             </cac:RegistrationAddress>
        #                             <cac:TaxScheme>
        #                                 <cbc:ID>{TaxSchemeID}</cbc:ID>
        #                                 <cbc:Name>{TaxSchemeName}</cbc:Name>
        #                             </cac:TaxScheme>
        #                         </cac:PartyTaxScheme>
        #                         <cac:PartyLegalEntity>
        #                             <cbc:RegistrationName>{CustomerPartyName}</cbc:RegistrationName>
        #                             <cbc:CompanyID schemeAgencyID="195" schemeAgencyName="CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)" schemeName="31">{CustomerID}</cbc:CompanyID>
        #                         </cac:PartyLegalEntity>
        #                         <cac:Contact>
        #                             <cbc:ElectronicMail>{CustomerElectronicMail}</cbc:ElectronicMail>
        #                         </cac:Contact>
        #                         <cac:Person>
        #                             <cbc:FirstName>{Firstname}</cbc:FirstName>
        #                         </cac:Person>
        #                     </cac:Party>
        #                 </cac:AccountingCustomerParty>""".format(
        #                             CustomerAdditionalAccountID=("1" if self.document_id.partner_id.is_company else "2"),
        #                             SchemeNameAdquiriente= self.return_number_document_type(self.document_id.partner_id.l10n_co_document_code),
        #                             IDAdquiriente=self.document_id.partner_id.identification_document,
        #                             CustomerPartyName=self._replace_character_especial(self.document_id.partner_id.name),
        #                             CustomerLine=self.document_id.partner_id.street,
        #                             CustomerCountryCode=self.document_id.partner_id.country_id.code,
        #                             CustomerCountryName=self.document_id.partner_id.country_id.name,
        #                             CustomerID=self.document_id.partner_id.identification_document,
        #                             CustomerTaxLevelCode=self._get_partner_fiscal_responsability_code(self.document_id.partner_id.id),
        #                             TaxSchemeID=self.document_id.partner_id.tribute_id.code,
        #                             TaxSchemeName=self.document_id.partner_id.tribute_id.name,
        #                             CustomerElectronicMail=self.document_id.partner_id.email,
        #                             Firstname=self._replace_character_especial(self.document_id.partner_id.name))
                                
        #     # Buscar el inicio y fin del nodo AccountingCustomerParty en la plantilla
        #     res = res.replace(res[res.find("<cac:AccountingCustomerParty>")+len("<cac:AccountingCustomerParty>"):res.find("</cac:AccountingCustomerParty>")],
        #         txt_2
        #     )


        return res
#------------------------------------------------> Intento de Getstatus <----------------------------

    def _get_GetStatus_values(self):
        xml_soap_values = global_functions.get_xml_soap_values(
            self.document_id.company_id.certificate_file,
            self.document_id.company_id.certificate_key)

        xml_soap_values['trackId'] = self.cufe
        return xml_soap_values

    def action_GetStatus(self):
        wsdl = DIAN['wsdl-hab']

        if self.document_id.company_id.production:
            wsdl = DIAN['wsdl']

        GetStatus_values = self._get_GetStatus_values()
        GetStatus_values['To'] = wsdl.replace('?wsdl', '')
        xml_soap_with_signature = global_functions.get_xml_soap_with_signature(
            global_functions.get_template_xml(GetStatus_values, 'GetStatus'),
            GetStatus_values['Id'],
            self.document_id.company_id.certificate_file,
            self.document_id.company_id.certificate_key)

        response = post(
            wsdl,
            headers={'content-type': 'application/soap+xml;charset=utf-8'},
            data=etree.tostring(xml_soap_with_signature, encoding="unicode"))

        if response.status_code == 200:
            self._get_status_response(response,send_mail=False)
        else:
            raise ValidationError(response.status_code)

        return True

    def action_GetStatusevent(self):
        wsdl = DIAN['wsdl-hab']

        if self.document_id.company_id.production:
            wsdl = DIAN['wsdl']

        GetStatus_values = self._get_GetStatus_values()
        GetStatus_values['To'] = wsdl.replace('?wsdl', '')
        xml_soap_with_signature = global_functions.get_xml_soap_with_signature(
            global_functions.get_template_xml(GetStatus_values, 'GetStatusEvent'),
            GetStatus_values['Id'],
            self.document_id.company_id.certificate_file,
            self.document_id.company_id.certificate_key)

        response = post(
            wsdl,
            headers={'content-type': 'application/soap+xml;charset=utf-8'},
            data=etree.tostring(xml_soap_with_signature, encoding="unicode"))

        if response.status_code == 200:
            self._get_status_response(response,send_mail=False)
        else:
            raise ValidationError(response.status_code)

        return True



    def _get_status_response(self, response, send_mail):
        b = "http://schemas.datacontract.org/2004/07/DianResponse"
        c = "http://schemas.microsoft.com/2003/10/Serialization/Arrays"
        s = "http://www.w3.org/2003/05/soap-envelope"
        strings = ''
        to_return = True
        status_code = 'other'
        root = etree.fromstring(response.content)
        date_invoice = self.document_id.invoice_date

        if not date_invoice:
            date_invoice = fields.Date.today()

        for element in root.iter("{%s}StatusCode" % b):
            if element.text in ('0', '00', '66', '90', '99'):
                if element.text == '00':
                    self.write({'state': 'exitoso'})

                    # if self.get_status_zip_status_code != '00':
                    #     if (self.document_id.move_type == "out_invoice"):
                    #         #self.document_id.company_id.out_invoice_sent += 1
                    #     elif (self.document_id.move_type == "out_refund" and self.document_type != "d"):
                    #         #self.document_id.company_id.out_refund_sent += 1
                    #     elif (self.document_id.move_type == "out_invoice" and self.document_type == "d"):
                    #         #self.document_id.company_id.out_refund_sent += 1

                status_code = element.text
        if status_code == '0':
            self.action_GetStatus()
            return True
        if status_code == '00':
            for element in root.iter("{%s}StatusMessage" % b):
                strings = element.text
            for element in root.iter("{%s}XmlBase64Bytes" % b):
                self.write({'message_error_DIAN_1': element.text})
            #if not self.mail_sent:
            #    self.action_send_mail()
            to_return = True
        else:
            if send_mail:
                self.send_failure_email()
            self.send_failure_email()
            to_return = True
        for element in root.iter("{%s}string" % c):
            if strings == '':
                strings = '- ' + element.text
            else:
                strings += '\n\n- ' + element.text
        if strings == '':
            for element in root.iter("{%s}Body" % s):
                strings = etree.tostring(element, pretty_print=True)
            if strings == '':
                strings = etree.tostring(root, pretty_print=True)
        self.write({
            'get_status_zip_status_code': status_code,
            'get_status_zip_response': strings,
            'response_message_dian' : strings})

        return True

    def send_failure_email(self):
        msg1 = _("The notification group for Einvoice failures is not set.\n" +
                 "You won't be notified if something goes wrong.\n" +
                 "Please go to Settings > Company > Notification Group.")
        subject = _('ALERTA! La Factura %s no fue enviada a la DIAN.') % self.document_id.name
        msg_body = _('''Cordial Saludo,<br/><br/>La factura ''' + self.document_id.name +
                     ''' del cliente ''' + self.document_id.partner_id.name + ''' no pudo ser ''' +
                     '''enviada a la Dian según el protocolo establecido previamente. Por '''
                     '''favor revise el estado de la misma en el menú Documentos Dian e '''
                     '''intente reprocesarla según el procedimiento definido.'''
                     '''<br/>''' + self.document_id.company_id.name + '''.''')
        
        email_ids = self.document_id.company_id.email

        if email_ids:
            email_to = ''

            for mail_id in email_ids:
                email_to += mail_id.email.strip() + ','
        else:
            raise UserError(msg1)

        mail_obj = self.env['mail.mail']
        msg_vals = {
            'subject': subject,
            'email_to': email_to,
            'body_html': msg_body}
        msg_id = mail_obj.create(msg_vals)
        msg_id.send()

        return True
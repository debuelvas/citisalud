import json
import uuid
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from . dian_document import server_url, tipo_ambiente
import logging
import pytz
import xmltodict
from datetime import datetime
from lxml import etree
_logger = logging.getLogger(__name__)
import requests
import hashlib
LOCALTZ = pytz.timezone('America/Bogota')


class DianApplicationResponse(models.Model):
    _name = 'dian.application.response'
    _description = 'Application Response'

    name = fields.Char()
    number = fields.Char(default="/")
    cude = fields.Char(compute='_compute_cude', store=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company.id)
    user_id = fields.Many2one('res.users', default=lambda self: self.env.user.id )
    response_code = fields.Selection([
        ('030','Acuse de recibo de Factura Electrónica de Venta'),
        ('031', 'Reclamo de la Factura Electrónica de Venta'),
        ('032', 'Recibo del bien y/o prestación del servicio'),
        ('033', 'Aceptación expresa'),
        ('034', 'Aceptación Tácita'),
        ('035', 'Aval'),
        ('036', 'Inscripción de la factura electrónica de venta como título valor - RADIAN'),
        ('037', 'Endoso en Propiedad'),
        ('038', 'Endoso en Garantía'),
        ('039', 'Endoso en Procuración'),
        ('040', 'Cancelación de endoso'),
        ('041', 'Limitaciones a la circulación de la factura electrónica de venta como título'),
        ('042', 'Terminación de las limitaciones a la circulación de la factura electrónica de venta como título'),
        ('043', 'Mandatos'),
        ('044', 'Terminacion del Mandato'),
        ('045', 'Pago de la factura electrónica de venta como título valor'),
        ('046', 'Informe para el pago'),
        ('047', 'Endoso con efectos de cesión ordinaria'),
        ('048', 'Protesto'),
        ('049', 'Transferencia de los derechos económicos'),
        ('050', 'Notificación al deudor sobre la transferencia de los derechos económicos'),
        ('051', 'Pago de la transferencia de los derechos economicos'),
        ], string="Evento")
    doc_adq = fields.Char(help='Documento de la Persona que recibe este ApplicationResponse')
    document_referenced = fields.Char('Prefijo y Número del documento referenciado')
    document_type_code = fields.Selection([('01', '01')], help='Identificador del tipo de documento referenciado', default='01')
    response_xml = fields.Text()
    response_dian = fields.Text()
    response_message_dian = fields.Text('Respuesta DIAN')
    issue_date = fields.Char(compute='_compute_date_time')
    issue_time = fields.Char(compute='_compute_date_time')
    status = fields.Selection([ ("por_notificar", "Por notificar"),
            ("error", "Error"),
            ("por_validar", "Por validar"),
            ("exitoso", "Exitoso"),
            ("rechazado", "Rechazado"),], default='por_notificar', string="Estado")
    move_id = fields.Many2one('account.move')
    dian_get = fields.Boolean(string='Dian API')
    
    @api.depends('create_date')
    def _compute_date_time(self):
        """
        Calcula fecha y hora de emisión en timezone Colombia.
        Optimizado: Agregado @api.depends('create_date').
        """
        for rec in self:
            if rec.create_date:
                rec.issue_date = rec.create_date.date().isoformat()
                rec.issue_time = rec.create_date.astimezone(LOCALTZ).strftime('%H:%M:%S%Z:00')
            else:
                rec.issue_date = False
                rec.issue_time = False
    
    def name_get(self):
        result = []
        response_codes = dict(self._fields['response_code'].selection)
        for rec in self:
            name = rec.name or response_codes.get(rec.response_code)
            result.append((rec.id, name))
        return result


    def dian_preview(self):
        for rec in self:
            if rec.cude:
                return {
                    'type': 'ir.actions.act_url',
                    'target': 'new',
                    'url': 'https://catalogo-vpfe.dian.gov.co/document/searchqr?documentkey=' + rec.cude,
                }

    def dian_pdf_view(self):
        for rec in self:
            if rec.cude:
                return {
                    'type': 'ir.actions.act_url',
                    'target': 'new',
                    'url': 'https://catalogo-vpfe.dian.gov.co/Document/DownloadPDF?trackId=' + rec.cude,
                }



    def tacit_acceptation(self):
        pass



    @api.depends('company_id', 'company_id.partner_id', 'company_id.partner_id.vat_co',
                 'company_id.software_pin', 'response_code', 'doc_adq',
                 'document_referenced', 'document_type_code', 'issue_date', 'issue_time')
    def _compute_cude(self):
        """
        Calcula CUDE (Código Único de Documento Electrónico).
        Optimizado: Agregados todos los campos dependientes para correcta invalidación.
        CRÍTICO: Este hash es validado por DIAN, no modificar lógica.
        """
        for rec in self:
            if rec.dian_get:
                continue
            Num_DE = rec.id
            Fec_Emi = rec.issue_date
            Hor_Emi = rec.issue_time
            NitFe = rec.company_id.partner_id.vat_co
            ID = rec.document_referenced
            software_pin = rec.company_id.software_pin

            CUDE = f'{Num_DE}{Fec_Emi}{Hor_Emi}{NitFe}{rec.doc_adq}{rec.response_code}{ID}{rec.document_type_code}{software_pin}'
            CUDE = hashlib.sha384(CUDE.encode())
            rec.cude = CUDE.hexdigest()
    
    
    def _get_dian_constants(self):
        company = self.company_id
        dian_document = self.env['dian.document'].with_company(company)
        dian_constants = {
            'CertDigestDigestValue': dian_document._generate_CertDigestDigestValue(),
            'IssuerName':  company.issuer_name,
            'SerialNumber': company.serial_number,

        }
        return dian_constants

    @staticmethod
    def _get_data_constants_document():
        constants_document = {
            'identifier': uuid.uuid4(),
            'identifierkeyinfo': uuid.uuid4()
        }
        return constants_document

    def _generate_signature(
        self, response_xml
    ):          
        company = self.company_id
        dian_document = self.env['dian.document'].with_company(company)
        dian_constants = self._get_dian_constants()
        data_constants_document = self._get_data_constants_document()
        data_xml_keyinfo_base = ""
        data_xml_politics = ""
        data_xml_SignedProperties_base = ""
        data_xml_SigningTime = ""
        data_xml_SignatureValue = ""
        template_signature_data_xml = dian_document._template_signature_data_xml()
        # Generar clave de referencia 0 para la firma del documento (referencia ref0)
        # Actualizar datos de signature
        #    Generar certificado publico para la firma del documento en el elemento keyinfo
        data_public_certificate_base = company.digital_certificate
        #    Generar clave de politica de firma para la firma del documento (SigPolicyHash)
        data_xml_politics = dian_document._generate_signature_politics('')
        #    Obtener la hora de Colombia desde la hora del pc
        data_xml_SigningTime = self.create_date.astimezone(LOCALTZ).strftime('%Y-%m-%dT%H:%M:%S%Z:00')
        #    Generar clave de referencia 0 para la firma del documento (referencia ref0)
        #    1ra. Actualización de firma ref0 (leer todo el xml sin firma)
        data_xml_signature_ref_zero = dian_document._generate_signature_ref0(
            response_xml, None, None
        )
        data_xml_signature = dian_document._update_signature(
            template_signature_data_xml,
            data_xml_signature_ref_zero,
            data_public_certificate_base,
            data_xml_keyinfo_base,
            data_xml_politics,
            data_xml_SignedProperties_base,
            data_xml_SigningTime,
            dian_constants,
            data_xml_SignatureValue,
            data_constants_document,
        )
        parser = etree.XMLParser(remove_blank_text=True)
        data_xml_signature = etree.tostring(
            etree.XML(data_xml_signature, parser=parser)
        )
        data_xml_signature = data_xml_signature.decode()
        xmlns = (
            'xmlns="urn:oasis:names:specification:ubl:schema:xsd:ApplicationResponse-2" '
            'xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2" '
            'xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2" '
            'xmlns:ds="http://www.w3.org/2000/09/xmldsig#" '
            'xmlns:ext="urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2" '
            'xmlns:sts="dian:gov:co:facturaelectronica:Structures-2-1" '
            'xmlns:xades="http://uri.etsi.org/01903/v1.3.2#" '
            'xmlns:xades141="http://uri.etsi.org/01903/v1.4.1#" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
                     )
        #    Actualiza Keyinfo
        KeyInfo = etree.fromstring(data_xml_signature)
        KeyInfo = etree.tostring(KeyInfo[2])
        KeyInfo = KeyInfo.decode()
        KeyInfo = KeyInfo.replace(
            'xmlns:ds="http://www.w3.org/2000/09/xmldsig#"', "%s" % xmlns
        )
        data_xml_keyinfo_base = dian_document._generate_signature_ref1(
            KeyInfo,
            None,
            None,
        )
        data_xml_signature = data_xml_signature.replace(
            "<ds:DigestValue/>",
            "<ds:DigestValue>%s</ds:DigestValue>" % data_xml_keyinfo_base,
            1,
        )
        #    Actualiza SignedProperties
        SignedProperties = etree.fromstring(data_xml_signature)
        SignedProperties = etree.tostring(SignedProperties[3])
        SignedProperties = etree.fromstring(SignedProperties)
        SignedProperties = etree.tostring(SignedProperties[0])
        SignedProperties = etree.fromstring(SignedProperties)
        SignedProperties = etree.tostring(SignedProperties[0])
        SignedProperties = SignedProperties.decode()
        SignedProperties = SignedProperties.replace(
            'xmlns:xades="http://uri.etsi.org/01903/v1.3.2#" xmlns:xades141="http://uri.etsi.org/01903/v1.4.1#" '
            'xmlns:ds="http://www.w3.org/2000/09/xmldsig#"',
            "%s" % xmlns,
        )

        data_xml_SignedProperties_base = dian_document._generate_signature_ref2(SignedProperties)
        data_xml_signature = data_xml_signature.replace(
            "<ds:DigestValue/>",
            "<ds:DigestValue>%s</ds:DigestValue>" % data_xml_SignedProperties_base,
            1,
        )
        #    Actualiza Signeinfo
        Signedinfo = etree.fromstring(data_xml_signature)
        Signedinfo = etree.tostring(Signedinfo[0])
        Signedinfo = Signedinfo.decode()

        Signedinfo = Signedinfo.replace(
                'xmlns:ds="http://www.w3.org/2000/09/xmldsig#"', "%s" % xmlns
            )

        data_xml_SignatureValue = dian_document._generate_SignatureValue(Signedinfo)
        SignatureValue = etree.fromstring(data_xml_signature)
        SignatureValue = etree.tostring(SignatureValue[1])
        SignatureValue = SignatureValue.decode()
        data_xml_signature = data_xml_signature.replace(
            '-sigvalue"/>',
            '-sigvalue">%s</ds:SignatureValue>' % data_xml_SignatureValue,
            1,
        )
        return data_xml_signature

    def _get_common_template_vals(self):
        dian_document = self.env['dian.document']
        validation_errors = []
        if not self.user_id.partner_id.vat_co:
            validation_errors.append('Falta Nit en el contacto del empleado %s' % self.user_id.partner_id.display_name)
        if not self.user_id.partner_id.dv == 0 and not self.user_id.partner_id.dv:
            validation_errors.append('Falta digito de verificación en el contacto del empleado %s' % self.user_id.partner_id.display_name)
        if not self.user_id.partner_id.function:
            validation_errors.append('Falta Puesto de trabajo en el contacto del empleado %s' % self.user_id.partner_id.display_name)
        if validation_errors:
            raise UserError('Información obligatoria faltante: %s' % ','.join(validation_errors))
        return {
                "IdentificationCode": 'CO',
                "UBLVersionID": 'UBL 2.1',
                "CustomizationID": '1',
                "ProfileID": 'DIAN 2.1: ApplicationResponse de la Factura Electrónica de Venta',
                "ProfileExecutionID": tipo_ambiente["PRODUCCION"] if self.company_id.production else tipo_ambiente["PRUEBA"],
                "ID": self.id,
                "UUID": self.cude,
                "IssueDate": self.issue_date,
                "IssueTime": self.issue_time,
                "SenderPartyName": dian_document._replace_character_especial(self.company_id.partner_id.name),
                "SenderSchemeID": self.company_id.partner_id.dv,
                "SenderSchemeName": self.company_id.partner_id.l10n_latam_identification_type_id.dian_code,
                "SenderIDtext": self.company_id.partner_id.vat_co,
                "SenderTaxSchemeID": self._l10n_co_edi_get_fiscal_regimen_code(self.company_id.partner_id) or "01",#.tribute_id.code,
                "SenderTaxSchemeName": self._l10n_co_edi_get_fiscal_regimen_name(self.company_id.partner_id)  or "IVA",#.tribute_id.name,
                "ResponseCode": self.response_code,
                "ResponseDescription": dict(self._fields['response_code'].selection).get(self.response_code),
                "DocumentTypeCode": self.document_type_code,
                "notes": '',
                "reclamacion": '',
                "PersonSchemeID": self.user_id.partner_id.dv,
                "PersonSchemeName": self.user_id.partner_id.l10n_latam_identification_type_id.dian_code,
                "PersonID": self.user_id.partner_id.vat_co,
                "PersonFirstName": dian_document._replace_character_especial(self.user_id.partner_id.firs_name or self.user_id.partner_id.name),
                "PersonFamilyName": dian_document._replace_character_especial(self.user_id.partner_id.first_lastname or self.user_id.partner_id.name),
                "PersonJobTitle": dian_document._replace_character_especial(self.user_id.partner_id.function) or 'Auxiliar',
                "PersonOrganizationDepartment": 'Contabilidad',
                "SoftwareProviderID": self.company_id.partner_id.vat_co,
                "SoftwareProviderSchemeID": self.company_id.partner_id.dv,
                "SoftwareID": dian_document._get_software_identification_code(),
                "SoftwareSecurityCode": dian_document._generate_software_security_code(
                                dian_document._get_software_identification_code(),
                                dian_document._get_software_pin(),
                                str(self.id)),
                "UBLExtension2" : ''
            
            }

    def send_dian(self):
        dian_document = self.env['dian.document'].with_company(self.company_id)
        testSetId = dian_document._get_identificador_set_pruebas()
        timestamp = dian_document._generate_datetime_timestamp()
        document = dian_document._generate_zip_content(
                    f'ar{self.id}.xml',
                    f'ar{self.id}.zip',
                    self.response_xml,
                    self.company_id.document_repository,
                )
        data_xml_send = self._template_SendEventUpdateStatus_xml() % {
            "contentFile": document,
            "testSetId": testSetId,
            "identifier": uuid.uuid4(),
            "Created": timestamp["Created"],
            "Expires": timestamp["Expires"],
            "Certificate": self.company_id.digital_certificate,
            "identifierSecurityToken": uuid.uuid4(),
            "identifierTo": uuid.uuid4(),
        }
        parser = etree.XMLParser(remove_blank_text=True)
        data_xml_send = etree.tostring(etree.XML(data_xml_send, parser=parser))
        data_xml_send = data_xml_send.decode()
        #   Generar DigestValue Elemento to y lo reemplaza en el xml
        ElementTO = etree.fromstring(data_xml_send)
        ElementTO = etree.tostring(ElementTO[0])
        ElementTO = etree.fromstring(ElementTO)
        ElementTO = etree.tostring(ElementTO[2])
        DigestValueTO = dian_document._generate_digestvalue_to(ElementTO)
        data_xml_send = data_xml_send.replace(
            "<ds:DigestValue/>",
            "<ds:DigestValue>%s</ds:DigestValue>" % DigestValueTO,
        )
        #   Generar firma para el header de envío con el Signedinfo
        Signedinfo = etree.fromstring(data_xml_send)
        Signedinfo = etree.tostring(Signedinfo[0])
        Signedinfo = etree.fromstring(Signedinfo)
        Signedinfo = etree.tostring(Signedinfo[0])
        Signedinfo = etree.fromstring(Signedinfo)
        Signedinfo = etree.tostring(Signedinfo[2])
        Signedinfo = etree.fromstring(Signedinfo)
        Signedinfo = etree.tostring(Signedinfo[0])
        Signedinfo = Signedinfo.decode()
        Signedinfo = Signedinfo.replace(
            '<ds:SignedInfo xmlns:ds="http://www.w3.org/2000/09/xmldsig#" '
            'xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd" '
            'xmlns:wsu="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd" '
            'xmlns:wsa="http://www.w3.org/2005/08/addressing" '
            'xmlns:soap="http://www.w3.org/2003/05/soap-envelope" xmlns:wcf="http://wcf.dian.colombia">',
            '<ds:SignedInfo xmlns:ds="http://www.w3.org/2000/09/xmldsig#" '
            'xmlns:soap="http://www.w3.org/2003/05/soap-envelope" xmlns:wcf="http://wcf.dian.colombia" '
            'xmlns:wsa="http://www.w3.org/2005/08/addressing">',
        )
        SignatureValue = dian_document._generate_SignatureValue_GetStatus(Signedinfo)
        data_xml_send = data_xml_send.replace(
            "<ds:SignatureValue/>",
            "<ds:SignatureValue>%s</ds:SignatureValue>" % SignatureValue,
        )

        #   Contruye XML de envío de petición
        headers = {"content-type": "application/soap+xml"}
        URL_WEBService_DIAN = (
            server_url["PRODUCCION_VP"]
            if self.company_id.production
            else server_url["HABILITACION_VP"]
        )
        try:
            response = requests.post(
                URL_WEBService_DIAN, data=data_xml_send, headers=headers
            )
            self.response_dian = response.text
            response_dict = xmltodict.parse(self.response_dian)
            send_event_response = response_dict["s:Envelope"]["s:Body"]["SendEventUpdateStatusResponse"]["SendEventUpdateStatusResult"]
            status_code = send_event_response["b:StatusCode"]
            response_message_dian = ''
            response_message_dian = (
                status_code + " "
            )
            response_message_dian += (
                send_event_response["b:StatusDescription"]+ "\n"
            )
            response_message_dian += send_event_response["b:StatusMessage"]
            if (status_code == "00"):
                self.write(
                    {"status": "exitoso", 'response_message_dian': response_message_dian}
                )
            else:
                error_message = send_event_response["b:ErrorMessage"]
                if isinstance(error_message, dict):
                    response_message_dian += (json.dumps(error_message)+ "\n")
                self.write({
                    'status': 'error', 'response_message_dian': response_message_dian
                })

        except Exception:
            raise UserError(
                _(
                    "No existe comunicación con la DIAN para el servicio de recepción de Facturas Electrónicas. Por favor, revise su red o el acceso a internet."
                )
            )


    @api.model
    def generate_from_attached_document(self, attached_document_xml, response_type):
        """
        :param: attached_document_xml: string
        :param: response_type: string enum: see the field response_code of this model
        """
        wizard = self._context.get('wizard')
        data_ad = xmltodict.parse(attached_document_xml)
        data_fe = xmltodict.parse(data_ad['AttachedDocument']['cac:Attachment']['cac:ExternalReference']['cbc:Description'])

        document_referenced = data_ad['AttachedDocument']['cac:ParentDocumentLineReference']['cac:DocumentReference']['cbc:ID']
        doc_adq = data_ad['AttachedDocument']['cac:SenderParty']['cac:PartyTaxScheme']['cbc:CompanyID']['#text']

        rec = self.create({
            'response_code': response_type,
            'doc_adq': doc_adq,
            'document_referenced': document_referenced,

        })
        template_vals = rec._get_common_template_vals()
        template_vals.update({
                "CustomerPartyName": data_ad['AttachedDocument']['cac:SenderParty']['cac:PartyTaxScheme']['cbc:RegistrationName'],
                "CustomerschemeID":data_ad['AttachedDocument']['cac:SenderParty']['cac:PartyTaxScheme']['cbc:CompanyID']['@schemeID'],
                "CustomerID": data_ad['AttachedDocument']['cac:SenderParty']['cac:PartyTaxScheme']['cbc:CompanyID']['@schemeName'],
                "CustomercompanyIDtext": doc_adq,
                "InvoiceID": document_referenced,
                "CustomerTaxSchemeID": data_ad['AttachedDocument']['cac:SenderParty']['cac:PartyTaxScheme']['cac:TaxScheme']['cbc:ID'],
                "CustomerTaxSchemeName": data_ad['AttachedDocument']['cac:SenderParty']['cac:PartyTaxScheme']['cac:TaxScheme']['cbc:Name'],
                "UUIDinvoice": data_fe['Invoice']['cbc:UUID']['#text'],
            })
        if wizard and wizard.notes_xml:
            template_vals.update({
                'notes': wizard.notes_xml
            })
        ar_xml = self._template_application_response() % template_vals
        data_xml_signature = rec._generate_signature(ar_xml)
        parser = etree.XMLParser(remove_blank_text=True)
        data_xml_signature = etree.tostring(
            etree.XML(data_xml_signature, parser=parser)
        )
        data_xml_signature = data_xml_signature.decode()
        # Construye el documento XML con firma
        data_xml_document = ar_xml.replace(
            "<ext:ExtensionContent></ext:ExtensionContent>",
            "<ext:ExtensionContent>%s</ext:ExtensionContent>" % data_xml_signature,
        )
        rec.response_xml = '<?xml version="1.0" encoding="UTF-8"?>' + data_xml_document
        rec.name = template_vals.get('ResponseDescription')
        rec.send_dian()
        return rec

    @staticmethod
    def _replace_character_especial(text):
        """Reemplaza caracteres especiales de forma optimizada"""
        if not text:
            return text
            
        replacements = {
            '&': '&amp;', '<': '&lt;', '>': '&gt;',
            '"': '&quot;', "'": '&apos;',
            '®': '(R)',
            '©': '(C)',
            '™': '(TM)',
            '℠': '(SM)',
            '′': "'",
            '″': '"',
            '‴': "'''",
            '●': '*',
            '•': '*',
            '‒': '-',
            '–': '-',
            '—': '-',
            '―': '-',
            '⁃': '-',
            }
        for char, replacement in replacements.items():
            text = text.replace(char, replacement)
        return text

    def _l10n_co_edi_get_fiscal_regimen_code(self,entity):
        if entity.dian_fiscal_regimen == '48':
            return '01'
        if entity.dian_fiscal_regimen == '49':
            return 'ZZ'
        return entity.dian_fiscal_regimen

    def _l10n_co_edi_get_fiscal_regimen_name(self,entity):
        return dict(entity._fields["dian_fiscal_regimen"].selection).get(entity.dian_fiscal_regimen)

    @api.model
    def generate_from_electronic_invoice(self, id_e, response_type):
        """
        :param: attached_document_xml: string
        :param: response_type: string enum: see the field response_code of this model
        """
        data = self.env['account.move'].search([('id', '=', id_e)])
        document_referenced = data.ref 
        doc_adq = data.partner_id.vat_co 
        number = ""
        if self.number == False or self.number == "/":
            number = self.env["ir.sequence"].next_by_code(response_type)

        rec = self.create({
            'response_code': response_type,
            'doc_adq': doc_adq,
            'document_referenced': document_referenced,
            'move_id': id_e,
            'number':number,
        })
        template_vals = rec._get_common_template_vals()
        template_vals.update({
                "CustomerPartyName": self._replace_character_especial(data.partner_id.name), 
                "CustomerschemeID":  data.partner_id.dv, 
                "CustomerID": data.partner_id.l10n_latam_identification_type_id.dian_code or "31",
                "CustomercompanyIDtext": doc_adq,
                "InvoiceID": document_referenced,
                "CustomerTaxSchemeID": self._l10n_co_edi_get_fiscal_regimen_code(data.partner_id) or "01",#.tribute_id.code or "01", 
                "CustomerTaxSchemeName": self._l10n_co_edi_get_fiscal_regimen_name(data.partner_id) or "IVA", #.tribute_id.name or  "IVA",
                "UUIDinvoice": data.cufe_cuds_other_system, 
            })
        if response_type == '034':
            partner_tribute_name = data.partner_id.tribute_id.name
            template_vals.update({
                'notes': 'Manifiesto bajo la gravedad de juramento que transcurridos 3 días hábiles siguientes a la fecha de recepción de la mercancía o del servicio en la referida factura de este evento, el adquirente {} identificado con NIT {} no manifestó expresamente la aceptación o rechazo de la referida factura, ni reclamó en contra de su contenido.'.format(partner_tribute_name, doc_adq)
            })
        if response_type == '031':
            reclamacion = data.supplier_claim_concept
            reclamacion_text = dict(data._fields['supplier_claim_concept'].selection).get(data.supplier_claim_concept)
            template_vals.update({
                'reclamacion': 'name="{}" listID="{}"'.format(reclamacion_text, reclamacion)
                })
        ar_xml = self._template_application_response() % template_vals
        data_xml_signature = rec._generate_signature(ar_xml)
        parser = etree.XMLParser(remove_blank_text=True)
        data_xml_signature = etree.tostring(
            etree.XML(data_xml_signature, parser=parser)
        )
        data_xml_signature = data_xml_signature.decode()
        # Construye el documento XML con firma
        data_xml_document = ar_xml.replace(
            "<ext:ExtensionContent></ext:ExtensionContent>",
            "<ext:ExtensionContent>%s</ext:ExtensionContent>" % data_xml_signature,
        )
        rec.response_xml = '<?xml version="1.0" encoding="UTF-8"?>' + data_xml_document
        rec.name = template_vals.get('ResponseDescription')
        rec.send_dian()
        return rec

    @staticmethod
    def _template_application_response():
        return """
<ApplicationResponse xmlns="urn:oasis:names:specification:ubl:schema:xsd:ApplicationResponse-2"
                     xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
                     xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
                     xmlns:ds="http://www.w3.org/2000/09/xmldsig#"
                     xmlns:ext="urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2"
                     xmlns:sts="dian:gov:co:facturaelectronica:Structures-2-1"
                     xmlns:xades="http://uri.etsi.org/01903/v1.3.2#"
                     xmlns:xades141="http://uri.etsi.org/01903/v1.4.1#"
                     xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                     xsi:schemaLocation="urn:oasis:names:specification:ubl:schema:xsd:ApplicationResponse-2 http://docs.oasis-open.org/ubl/os-UBL-2.1/xsd/maindoc/UBL-ApplicationResponse-2.1.xsd">
    <ext:UBLExtensions>
        <ext:UBLExtension>
            <ext:ExtensionContent>
                <sts:DianExtensions>
                    <sts:InvoiceSource>
                        <cbc:IdentificationCode listAgencyID="6"
                                                listAgencyName="United Nations Economic Commission for Europe"
                                                listSchemeURI="urn:oasis:names:specification:ubl:codelist:gc:CountryIdentificationCode-2.1">CO</cbc:IdentificationCode>
                    </sts:InvoiceSource>
                    <sts:SoftwareProvider>
                        <sts:ProviderID schemeID="%(SoftwareProviderSchemeID)s"
                                        schemeName="31"
                                        schemeAgencyID="195"
                                        schemeAgencyName="CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)">%(SoftwareProviderID)s</sts:ProviderID>
                        <sts:SoftwareID schemeAgencyID="195"
                                        schemeAgencyName="CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)">%(SoftwareID)s</sts:SoftwareID>
                    </sts:SoftwareProvider>
                    <sts:SoftwareSecurityCode schemeAgencyID="195"
                                                schemeAgencyName="CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)">%(SoftwareSecurityCode)s</sts:SoftwareSecurityCode>
                    <sts:AuthorizationProvider>
                        <sts:AuthorizationProviderID schemeID="4"
                                                        schemeName="31"
                                                        schemeAgencyID="195"
                                                        schemeAgencyName="CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)">800197268</sts:AuthorizationProviderID>
                    </sts:AuthorizationProvider>
                    <sts:QRCode>https://catalogo-vpfe.dian.gov.co/document/searchqr?documentkey=%(UUIDinvoice)s</sts:QRCode>
                </sts:DianExtensions>
            </ext:ExtensionContent>
        </ext:UBLExtension>
        %(UBLExtension2)s
        <ext:UBLExtension>
            <ext:ExtensionContent></ext:ExtensionContent>
        </ext:UBLExtension>
    </ext:UBLExtensions>
    <cbc:UBLVersionID>%(UBLVersionID)s</cbc:UBLVersionID>
    <cbc:CustomizationID>%(CustomizationID)s</cbc:CustomizationID>
    <cbc:ProfileID>%(ProfileID)s</cbc:ProfileID>
    <cbc:ProfileExecutionID>%(ProfileExecutionID)s</cbc:ProfileExecutionID>
    <cbc:ID>%(ID)s</cbc:ID>
    <cbc:UUID schemeID="%(ProfileExecutionID)s"
              schemeName="CUDE-SHA384">%(UUID)s</cbc:UUID>
    <cbc:IssueDate>%(IssueDate)s</cbc:IssueDate>
    <cbc:IssueTime>%(IssueTime)s</cbc:IssueTime>
    <cbc:Note>%(notes)s</cbc:Note>
    <cac:SenderParty>
        <cac:PartyTaxScheme>
            <cbc:RegistrationName>%(SenderPartyName)s</cbc:RegistrationName>
            <cbc:CompanyID schemeAgencyID="195"
                           schemeAgencyName="CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)"
                           schemeID="%(SenderSchemeID)s"
                           schemeName="%(SenderSchemeName)s"
                           schemeVersionID="1">%(SenderIDtext)s</cbc:CompanyID>
            <cac:TaxScheme>
                <cbc:ID>%(SenderTaxSchemeID)s</cbc:ID>
                <cbc:Name>%(SenderTaxSchemeName)s</cbc:Name>
            </cac:TaxScheme>
        </cac:PartyTaxScheme>
    </cac:SenderParty>
    <cac:ReceiverParty>
        <cac:PartyTaxScheme>
            <cbc:RegistrationName>%(CustomerPartyName)s</cbc:RegistrationName>
            <cbc:CompanyID schemeAgencyID="195"
                           schemeAgencyName="CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)"
                           schemeID="%(CustomerschemeID)s"
                           schemeName="%(CustomerID)s"
                           schemeVersionID="1">%(CustomercompanyIDtext)s</cbc:CompanyID>
            <cac:TaxScheme>
                <cbc:ID>%(CustomerTaxSchemeID)s</cbc:ID>
                <cbc:Name>%(CustomerTaxSchemeName)s</cbc:Name>
            </cac:TaxScheme>
        </cac:PartyTaxScheme>
    </cac:ReceiverParty>
    <cac:DocumentResponse>
        <cac:Response>
            <cbc:ResponseCode %(reclamacion)s>%(ResponseCode)s</cbc:ResponseCode>
            <cbc:Description>%(ResponseDescription)s</cbc:Description>
        </cac:Response>
        <cac:DocumentReference>
            <cbc:ID>%(InvoiceID)s</cbc:ID>
            <cbc:UUID schemeName="CUFE-SHA384">%(UUIDinvoice)s</cbc:UUID>
            <cbc:DocumentTypeCode>%(DocumentTypeCode)s</cbc:DocumentTypeCode>
        </cac:DocumentReference>
        <cac:IssuerParty>
            <cac:Person>
                <cbc:ID schemeID="%(PersonSchemeID)s"
                        schemeName="%(PersonSchemeName)s">%(PersonID)s</cbc:ID>
                <cbc:FirstName>%(PersonFirstName)s</cbc:FirstName>
                <cbc:FamilyName>%(PersonFamilyName)s</cbc:FamilyName>
                <cbc:JobTitle>%(PersonJobTitle)s</cbc:JobTitle>
                <cbc:OrganizationDepartment>%(PersonOrganizationDepartment)s</cbc:OrganizationDepartment>
            </cac:Person>
        </cac:IssuerParty>
    </cac:DocumentResponse>
</ApplicationResponse>
        """

    @staticmethod
    def _template_SendEventUpdateStatus_xml():
        return """
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" xmlns:wcf="http://wcf.dian.colombia">
    <soap:Header xmlns:wsa="http://www.w3.org/2005/08/addressing">
        <wsse:Security xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd" xmlns:wsu="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">
            <wsu:Timestamp wsu:Id="TS-%(identifier)s">
                <wsu:Created>%(Created)s</wsu:Created>
                <wsu:Expires>%(Expires)s</wsu:Expires>
            </wsu:Timestamp>
            <wsse:BinarySecurityToken EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary" ValueType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-x509-token-profile-1.0#X509v3" wsu:Id="BAKENDEVS-%(identifierSecurityToken)s">%(Certificate)s</wsse:BinarySecurityToken>
            <ds:Signature Id="SIG-%(identifier)s" xmlns:ds="http://www.w3.org/2000/09/xmldsig#">
                <ds:SignedInfo>
                    <ds:CanonicalizationMethod Algorithm="http://www.w3.org/2001/10/xml-exc-c14n#">
                        <ec:InclusiveNamespaces PrefixList="wsa soap wcf" xmlns:ec="http://www.w3.org/2001/10/xml-exc-c14n#"/>
                    </ds:CanonicalizationMethod>
                    <ds:SignatureMethod Algorithm="http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"/>
                    <ds:Reference URI="#ID-%(identifierTo)s">
                        <ds:Transforms>
                            <ds:Transform Algorithm="http://www.w3.org/2001/10/xml-exc-c14n#">
                                <ec:InclusiveNamespaces PrefixList="soap wcf" xmlns:ec="http://www.w3.org/2001/10/xml-exc-c14n#"/>
                            </ds:Transform>
                        </ds:Transforms>
                        <ds:DigestMethod Algorithm="http://www.w3.org/2001/04/xmlenc#sha256"/>
                        <ds:DigestValue></ds:DigestValue>
                    </ds:Reference>
                </ds:SignedInfo>
                <ds:SignatureValue></ds:SignatureValue>
                <ds:KeyInfo Id="KI-%(identifier)s">
                    <wsse:SecurityTokenReference wsu:Id="STR-%(identifier)s">
                        <wsse:Reference URI="#BAKENDEVS-%(identifierSecurityToken)s" ValueType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-x509-token-profile-1.0#X509v3"/>
                    </wsse:SecurityTokenReference>
                </ds:KeyInfo>
            </ds:Signature>
        </wsse:Security>
        <wsa:Action>http://wcf.dian.colombia/IWcfDianCustomerServices/SendEventUpdateStatus</wsa:Action>
        <wsa:To wsu:Id="ID-%(identifierTo)s" xmlns:wsu="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">https://vpfe.dian.gov.co/WcfDianCustomerServices.svc</wsa:To>
    </soap:Header>
    <soap:Body>
        <wcf:SendEventUpdateStatus>
            <wcf:contentFile>%(contentFile)s</wcf:contentFile>
        </wcf:SendEventUpdateStatus>
    </soap:Body>
</soap:Envelope>"""


    @api.model
    def create(self, vals):
        """
        Crea ApplicationResponse con numeración secuencial.
        Optimizado: Usa fields.Date.context_today() en lugar de datetime.now().
        """
        if vals.get("number", "/") == "/":
            # Usar context_today para obtener fecha del servidor/usuario
            sequence_date = fields.Date.context_today(self)
            vals["number"] = (
                self.env["ir.sequence"]
                .with_context(ir_sequence_date=sequence_date)
                .next_by_code(vals.get("response_code"))
            )
        return super().create(vals)

    def return_number_document_type(self, document_type):
        number_document_type = 13

        if document_type:
            if document_type == "31" or document_type == "rut":
                number_document_type = 31
            if document_type == "national_citizen_id":
                number_document_type = 13
            if document_type == "civil_registration":
                number_document_type = 11
            if document_type == "id_card":
                number_document_type = 12
            if document_type == "21":
                number_document_type = 21
            if document_type == "foreign_id_card":
                number_document_type = 22
            if document_type == "passport":
                number_document_type = 41
            if document_type == "43":
                number_document_type = 43
        else:
            raise UserError(_("Debe de ingresar el tipo de documento"))
        return str(number_document_type)
import logging
from datetime import datetime, timedelta
import uuid
import base64
import hashlib
import xmltodict
import requests
from lxml import etree
from odoo import _, api, fields, models, tools
from odoo.exceptions import UserError, ValidationError
from pytz import timezone
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import pkcs12, load_pem_private_key
from cryptography.hazmat.backends import default_backend

_logger = logging.getLogger(__name__)

server_url = {
    "HABILITACION": "https://facturaelectronica.dian.gov.co/habilitacion/B2BIntegrationEngine/FacturaElectronica/facturaElectronica.wsdl",
    "PRODUCCION": "https://facturaelectronica.dian.gov.co/operacion/B2BIntegrationEngine/FacturaElectronica/facturaElectronica.wsdl",
    "HABILITACION_CONSULTA": "https://facturaelectronica.dian.gov.co/habilitacion/B2BIntegrationEngine/FacturaElectronica/consultaDocumentos.wsdl",
    "PRODUCCION_CONSULTA": "https://facturaelectronica.dian.gov.co/operacion/B2BIntegrationEngine/FacturaElectronica/consultaDocumentos.wsdl",
    "PRODUCCION_VP": "https://vpfe.dian.gov.co/WcfDianCustomerServices.svc?wsdl",
    "HABILITACION_VP": "https://vpfe-hab.dian.gov.co/WcfDianCustomerServices.svc?wsdl",
}

class ResCompanyInherit(models.Model):
    _inherit = "res.company"

    OPERATION_TYPE = [("09", "AIU"), ("10", "Estandar *"), ("11", "Mandatos")]

    def _get_dian_sequence(self):
        list_dian_sequence = []
        rec_dian_sequence = self.env["ir.sequence"].search(
            [
                ("company_id", "=", self.env.company.id),
                ("use_dian_control", "=", True),
                ("active", "=", True),
            ]
        )
        for sequence in rec_dian_sequence:
            list_dian_sequence.append((str(sequence.id), sequence.name))
        return list_dian_sequence

    trade_name = fields.Char(string="Razón social", default="0")
    digital_certificate = fields.Text(string="Certificado digital público", default="0")
    software_identification_code = fields.Char(string="Código de identificación del software", default="0")
    identificador_set_pruebas = fields.Char(string="Identificador del SET de pruebas")
    software_pin = fields.Char(string="PIN del software", default="0")
    password_environment = fields.Char(string="Clave de ambiente", default="0")
    seed_code = fields.Integer(string="Código de semilla", default=5000000)
    issuer_name = fields.Char(string="Ente emisor del certificado", default="0")
    serial_number = fields.Char(string="Serial del certificado", default="0")
    document_repository = fields.Char(string="Ruta de almacenamiento de archivos", default="0")
    in_use_dian_sequence = fields.Selection("_get_dian_sequence", "Secuenciador DIAN a utilizar", required=False)
    certificate_key = fields.Char(string="Clave del certificado P12", default="0")
    operation_type = fields.Selection(OPERATION_TYPE, string="Tipo de operación DIAN")
    pem = fields.Char(string="Nombre del archivo PEM del certificado", default="0")
    pem_file = fields.Binary("Archivo PEM")
    certificate = fields.Char(string="Nombre del archivo del certificado", default="0")
    certificate_file = fields.Binary("Archivo del certificado")
    production = fields.Boolean(string="Pase a producción", default=False)
    xml_response_numbering_range = fields.Text(
        string="Contenido XML de la respuesta DIAN a la consulta de rangos",
        readonly=True,
    )
    in_contingency_4 = fields.Boolean(string="En contingencia", default=False)
    date_init_contingency_4 = fields.Datetime(string="Fecha de inicio de contingencia 4")
    date_end_contingency_4 = fields.Datetime(string="Fecha de fin de contingencia 4")
    exists_invoice_contingency_4 = fields.Boolean(
        string="Cantidad de facturas con contingencia 4 sin reportar a la DIAN",
        default=False,
    )
    sales_discount_account = fields.Many2one('account.account', string="Cuenta Descuento ventas")
    purchase_discount_account = fields.Many2one('account.account', string="Cuenta Descuento Compras")

    def query_numbering_range(self):
        identifier = uuid.uuid4()
        identifierTo = uuid.uuid4()
        identifierSecurityToken = uuid.uuid4()
        timestamp = self._generate_datetime_timestamp()
        Created = timestamp["Created"]
        Expires = timestamp["Expires"]
        Certificate = self.digital_certificate
        ProviderID = self.partner_id.vat_co
        SoftwareID = self.software_identification_code
        template_GetNumberingRange_xml = self._template_GetNumberingRange_xml()
        data_xml_send = self._generate_GetNumberingRange_send_xml(
            template_GetNumberingRange_xml,
            identifier,
            Created,
            Expires,
            Certificate,
            ProviderID,
            ProviderID,
            SoftwareID,
            identifierSecurityToken,
            identifierTo,
        )

        parser = etree.XMLParser(remove_blank_text=True)
        data_xml_send = etree.tostring(etree.XML(data_xml_send, parser=parser))
        data_xml_send = data_xml_send.decode()
        ElementTO = etree.fromstring(data_xml_send)
        ElementTO = etree.tostring(ElementTO[0])
        ElementTO = etree.fromstring(ElementTO)
        ElementTO = etree.tostring(ElementTO[2])
        DigestValueTO = self._generate_digestvalue_to(ElementTO)
        data_xml_send = data_xml_send.replace(
            "<ds:DigestValue/>", "<ds:DigestValue>%s</ds:DigestValue>" % DigestValueTO
        )
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
            '<ds:SignedInfo xmlns:ds="http://www.w3.org/2000/09/xmldsig#" xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd" xmlns:wsu="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd" xmlns:wsa="http://www.w3.org/2005/08/addressing" xmlns:soap="http://www.w3.org/2003/05/soap-envelope" xmlns:wcf="http://wcf.dian.colombia">',
            '<ds:SignedInfo xmlns:ds="http://www.w3.org/2000/09/xmldsig#" xmlns:soap="http://www.w3.org/2003/05/soap-envelope" xmlns:wcf="http://wcf.dian.colombia" xmlns:wsa="http://www.w3.org/2005/08/addressing">',
        )

        SignatureValue = self._generate_SignatureValue_GetNumberingRange(Signedinfo)
        data_xml_send = data_xml_send.replace(
            "<ds:SignatureValue/>",
            "<ds:SignatureValue>%s</ds:SignatureValue>" % SignatureValue,
        )
        headers = {"content-type": "application/soap+xml"}
        if self.production:
            try:
                response = requests.post(
                    server_url["PRODUCCION_VP"], data=data_xml_send, headers=headers
                )
            except Exception:
                raise ValidationError(
                    _("No existe comunicación con la DIAN para el servicio de consulta de rangos de numeración")
                )
        else:
            try:
                response = requests.post(
                    server_url["HABILITACION_VP"], data=data_xml_send, headers=headers
                )
            except Exception:
                raise ValidationError(
                    _("No existe comunicación con la DIAN para el servicio de consulta de rangos de numeración")
                )
        if response.status_code != 200:
            if response.status_code == 500:
                raise ValidationError(_("Error 500 = Error de servidor interno"))
            if response.status_code == 503:
                raise ValidationError(_("Error 503 = Servicio no disponible"))
        response_dict = xmltodict.parse(response.content)
        self.xml_response_numbering_range = response.content

        is_valid = response_dict["s:Envelope"]["s:Body"]["GetNumberingRangeResponse"][
            "GetNumberingRangeResult"
        ]["b:OperationCode"]
        if is_valid == "100":
            dict_mensaje = list(
                response_dict["s:Envelope"]["s:Body"]["GetNumberingRangeResponse"][
                    "GetNumberingRangeResult"
                ]["b:ResponseList"]["c:NumberRangeResponse"]
            )
            if dict_mensaje[0] == "c:ResolutionNumber":
                dict_mensaje = []
                mensaje = dict(
                    response_dict["s:Envelope"]["s:Body"]["GetNumberingRangeResponse"][
                        "GetNumberingRangeResult"
                    ]["b:ResponseList"]["c:NumberRangeResponse"]
                )
                dict_mensaje.append(mensaje)
            for dic in dict_mensaje:
                sequence_id = self.env["ir.sequence"].search([
                    ("prefix", "=", dic["c:Prefix"]),
                    ("company_id", "=", self.env.company.id)
                ], limit=1)

                if not sequence_id:
                    raise UserError(
                        _("No existe secuencia creada con el prefijo {}. Por favor, créala.").format(dic["c:Prefix"])
                    )

                resolution_number = dic["c:ResolutionNumber"]
                prefix = dic["c:Prefix"]
                from_number = dic["c:FromNumber"]
                to_number = dic["c:ToNumber"]
                valid_from = dic["c:ValidDateFrom"]
                valid_to = dic["c:ValidDateTo"]
                technical_key = dic["c:TechnicalKey"]

                existing_resolution = self.env["ir.sequence.dian_resolution"].search([
                    ("sequence_id", "=", sequence_id.id),
                    ("resolution_number", "=", resolution_number)], limit=1)

                for resolution_id in sequence_id.dian_resolution_ids:
                    if resolution_id == existing_resolution:
                        resolution_id.active_resolution = True
                    else:
                        resolution_id.active_resolution = False

                if not existing_resolution:
                    vals_resolution = {
                        "resolution_number": resolution_number,
                        "number_from": from_number,
                        "number_to": to_number,
                        "number_next": from_number,
                        "date_from": valid_from,
                        "date_to": valid_to,
                        "technical_key": technical_key,
                        "active_resolution": True,
                    }

                    values = {
                        "prefix": prefix,
                        "use_dian_control": True,
                        "dian_resolution_ids": [(0, 0, vals_resolution)],
                    }

                    sequence_id.write(values)

    def _generate_SignatureValue_GetNumberingRange(self, data_xml_SignedInfo_generate):
        data_xml_SignatureValue_c14n = etree.tostring(
            etree.fromstring(data_xml_SignedInfo_generate), method="c14n"
        )
        password = self.certificate_key.encode('utf-8')
        try:
            p12 = pkcs12.load_key_and_certificates(
                base64.b64decode(self.certificate_file),
                password,
                default_backend()
            )
            private_key = p12[0]
        except Exception as ex:
            raise UserError(tools.ustr(ex))
        try:
            signature = private_key.sign(
                data_xml_SignatureValue_c14n,
                padding.PKCS1v15(),
                hashes.SHA256()
            )
        except Exception as ex:
            raise UserError(tools.ustr(ex))
        SignatureValue = base64.b64encode(signature).decode()
        pem_cert = x509.load_pem_x509_certificate(base64.b64decode(self.pem_file), default_backend())
        try:
            pem_cert.public_key().verify(
                signature,
                data_xml_SignatureValue_c14n,
                padding.PKCS1v15(),
                hashes.SHA256()
            )
        except Exception:
            raise ValidationError(
                _("Signature for GetStatus was not validated successfully")
            )
        return SignatureValue

    def _generate_digestvalue_to(self, elementTo):
        elementTo = etree.tostring(etree.fromstring(elementTo), method="c14n")
        elementTo_sha256 = hashlib.sha256(elementTo)
        elementTo_digest = elementTo_sha256.digest()
        elementTo_base = base64.b64encode(elementTo_digest)
        return elementTo_base.decode()

    def _generate_datetime_timestamp(self):
        fmt = "%Y-%m-%dT%H:%M:%S.%f"
        now_bogota = datetime.now(timezone("UTC"))
        Created = now_bogota.strftime(fmt)[:-3] + "Z"
        now_bogota = now_bogota + timedelta(minutes=5)
        Expires = now_bogota.strftime(fmt)[:-3] + "Z"
        timestamp = {"Created": Created, "Expires": Expires}
        return timestamp

    def _template_GetNumberingRange_xml(self):
        template_GetNumberingRange_xml = """
        <soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" xmlns:wcf="http://wcf.dian.colombia">
                <soap:Header xmlns:wsa="http://www.w3.org/2005/08/addressing">
                        <wsse:Security xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
                xmlns:wsu="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">
                                <wsu:Timestamp wsu:Id="TS-%(identifier)s">
                                        <wsu:Created>%(Created)s</wsu:Created>
                                        <wsu:Expires>%(Expires)s</wsu:Expires>
                                </wsu:Timestamp>
                                <wsse:BinarySecurityToken EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary"
                ValueType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-x509-token-profile-1.0#X509v3"
                wsu:Id="BAKENDEVS-%(identifierSecurityToken)s">%(Certificate)s</wsse:BinarySecurityToken>
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
                                                        <wsse:Reference URI="#BAKENDEVS-%(identifierSecurityToken)s"
                ValueType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-x509-token-profile-1.0#X509v3"/>
                                                </wsse:SecurityTokenReference>
                                        </ds:KeyInfo>
                                </ds:Signature>
                        </wsse:Security>
                        <wsa:Action>http://wcf.dian.colombia/IWcfDianCustomerServices/GetNumberingRange</wsa:Action>
                        <wsa:To wsu:Id="ID-%(identifierTo)s"
                xmlns:wsu="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">
                https://vpfe.dian.gov.co/WcfDianCustomerServices.svc</wsa:To>
                </soap:Header>
                <soap:Body>
                        <wcf:GetNumberingRange>
                                <wcf:accountCode>%(accountCode)s</wcf:accountCode>
                                <wcf:accountCodeT>%(accountCodeT)s</wcf:accountCodeT>
                                <wcf:softwareCode>%(softwareCode)s</wcf:softwareCode>
                        </wcf:GetNumberingRange>
                </soap:Body>
        </soap:Envelope>
        """
        return template_GetNumberingRange_xml

    @api.model
    def _generate_GetNumberingRange_send_xml(
        self,
        template_getstatus_send_data_xml,
        identifier,
        Created,
        Expires,
        Certificate,
        accountCode,
        accountCodeT,
        softwareCode,
        identifierSecurityToken,
        identifierTo,
    ):
        data_consult_numbering_range_send_xml = template_getstatus_send_data_xml % {
            "identifier": identifier,
            "Created": Created,
            "Expires": Expires,
            "Certificate": Certificate,
            "accountCode": accountCode,
            "accountCodeT": accountCodeT,
            "softwareCode": softwareCode,
            "identifierSecurityToken": identifierSecurityToken,
            "identifierTo": identifierTo,
        }
        return data_consult_numbering_range_send_xml




    def get_key(self):
        self.ensure_one()
        if not self.certificate_file:
            raise UserError(_("Certificado digital no encontrado"))
        if not self.certificate_key:
            raise UserError(_("Clave del certificado no configurada"))
        try:
            p12_data = base64.b64decode(self.certificate_file)
            private_key, certificate, _ = pkcs12.load_key_and_certificates(
                p12_data,
                self.certificate_key.encode('utf-8'),
                backend=default_backend()
            )
            if not private_key or not certificate:
                raise UserError(_("No se pudo extraer la llave privada o el certificado"))
            return private_key, certificate
        except ValueError as ve:
            raise UserError(_("Clave del certificado incorrecta"))
        except Exception as e:
            raise UserError(_(f"Error cargando certificado: {str(e)}"))


    @api.constrains('certificate_file')
    def _check_certificate_format(self):
        """Valida el formato del certificado"""
        for record in self:
            if record.certificate_file:
                try:
                    p12_data = base64.b64decode(record.certificate_file)
                    pkcs12.load_key_and_certificates(
                        p12_data,
                        b'dummy',
                        backend=default_backend()
                    )
                except ValueError:
                    continue
                except Exception as e:
                    raise ValidationError(_("Formato de certificado inválido. Debe ser un archivo .p12 o .pfx válido"))
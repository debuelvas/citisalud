# -*- coding: utf-8 -*-
from odoo import _, api, fields, models, tools, Command
from odoo.exceptions import UserError,ValidationError
from datetime import datetime, timedelta
from pytz import timezone
import logging
_logger = logging.getLogger(__name__)
try:
    import hashlib
except ImportError:
    _logger.info("Cannot import hashlib library ****************************")

try:
    import base64
except ImportError:
    _logger.info("Cannot import base64 library *****************************")

try:
    from lxml import etree
except ImportError:
    _logger.info("Cannot import  etree *************************************")

try:
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography import x509
except ImportError:
    _logger.info("Cannot import OpenSSL library")

server_url = {
    "HABILITACION": "https://facturaelectronica.dian.gov.co/habilitacion/B2BIntegrationEngine/FacturaElectronica/facturaElectronica.wsdl",
    "PRODUCCION": "https://facturaelectronica.dian.gov.co/operacion/B2BIntegrationEngine/FacturaElectronica/facturaElectronica.wsdl",
    "HABILITACION_CONSULTA": "https://facturaelectronica.dian.gov.co/habilitacion/B2BIntegrationEngine/FacturaElectronica/consultaDocumentos.wsdl",
    "PRODUCCION_CONSULTA": "https://facturaelectronica.dian.gov.co/operacion/B2BIntegrationEngine/FacturaElectronica/consultaDocumentos.wsdl",
    "PRODUCCION_VP": "https://vpfe.dian.gov.co/WcfDianCustomerServices.svc?wsdl",
    # 'PRODUCCION_VP':'https://vpfe-hab.dian.gov.co/WcfDianCustomerServices.svc?wsdl',
    "HABILITACION_VP": "https://vpfe-hab.dian.gov.co/WcfDianCustomerServices.svc?wsdl",
}

tipo_ambiente = {
    "PRODUCCION": "1",
    "PRUEBA": "2",
}

class DianDocument(models.Model):
    _name = "dian.document"
    _rec_name = "dian_code"
    _description = "Dian Document"

    active = fields.Boolean(string="Activo", default=True)
    document_id = fields.Many2one(
        "account.move", string="Número de documento", required=True
    )
    state = fields.Selection(
        [
            ("por_notificar", "Por notificar"),
            ("error", "Error"),
            ("por_validar", "Por validar"),
            ("exitoso", "Exitoso"),
            ("rechazado", "Rechazado"),
        ],
        string="Estatus",
        readonly=True,
        default="por_notificar",
        required=True,
    )
    date_document_dian = fields.Char(string="Fecha envio al DIAN", readonly=True)
    shipping_response = fields.Selection(
        [
            ("100", "100 Error al procesar la solicitud WS entrante"),
            ("101","101 El formato de los datos del ejemplar recibido no es correcto"),
            ("102","102 El formato de los datos del ejemplar recibido no es correcto"),
            ("103","103 Tamaño de archivo comprimido zip es 0 o desconocido"),
            ("104","104 Sólo un archivo es permitido por archivo Zip"),
            ("200","200 Ejemplar recibido exitosamente pasará a verificación"),
            ("300","300 Archivo no soportado"),
            ("310", "310 El ejemplar contiene errores de validación semantica"),
            ("320", "320 Parámetros de solicitud de servicio web, no coincide contra el archivo"),
            ("500", "500 Error interno del servicio intentar nuevamente"),
        ],
        string="Respuesta de envío",
    )
    transaction_code = fields.Integer(string="Código de la Transacción de validación")
    transaction_description = fields.Char(string="Descripción de la transacción de validación")
    response_document_dian = fields.Selection(
        [
            ("7200001", "7200001 Recibida"),
            ("7200002", "7200002 Exitosa"),
            ("7200003", "7200003 En proceso de validación"),
            ("7200004", "7200004 Fallida"),
            ("7200005", "7200005 Error"),
        ],
        string="Respuesta de consulta")
    dian_code = fields.Char(string="Código DIAN")
    xml_document = fields.Text(string="Contenido XML del documento")
    xml_file_name = fields.Char(string="Nombre archivo xml")
    zip_file_name = fields.Char(string="Nombre archivo zip")
    cufe_seed = fields.Char(string="CUFE SEED")
    date_request_dian = fields.Datetime(string="Fecha consulta DIAN", readonly=True)
    cufe = fields.Char(string="CUFE")
    QR_code = fields.Binary(string="Código QR", readonly=True)
    date_email_send = fields.Datetime(string="Fecha envío email", readonly=True)
    date_email_acknowledgment = fields.Datetime(string="Fecha acuse email")
    response_message_dian = fields.Text(string="Respuesta DIAN", readonly=True)
    last_shipping = fields.Boolean(string="Ultimo envío", default=True)
    customer_name = fields.Char(
        string="Cliente", readonly=True, related="document_id.partner_id.name"
    )
    date_document = fields.Date(
        string="Fecha documento", readonly=True, related="document_id.invoice_date"
    )
    customer_email = fields.Char(
        string="Email cliente", readonly=True, related="document_id.partner_id.email"
    )
    document_type = fields.Selection(
        [("f", "Factura"), ("c", "Nota/Credito"), ("d", "Nota/Debito")],
        string="Tipo de documento",
        readonly=True,
    )
    resend = fields.Boolean(string="Autorizar reenvio?", default=False)
    email_response = fields.Selection(
        [("accepted", "ACEPTADA"), ("rejected", "RECHAZADA"), ("pending", "PENDIENTE")],
        string="Decisión del cliente",
        required=True,
        default="pending",
        readonly=True,
    )
    email_reject_reason = fields.Char(string="Motivo del rechazo", readonly=True)
    ZipKey = fields.Char(string="Identificador del documento enviado", readonly=True)
    xml_response_dian = fields.Text(
        string="Contenido XML de la respuesta DIAN", readonly=True
    )
    xml_send_query_dian = fields.Text(
        string="Contenido XML de envío de consulta de documento DIAN", readonly=True
    )
    xml_response_contingency_dian = fields.Text(
        string="Mensaje de respuesta DIAN al envío de la contigencia", 
    )
    state_contingency = fields.Selection(
        [
            ("por_notificar", "por_notificar"),
            ("exitosa", "Exitosa"),
            ("rechazada", "Rechazada"),
        ],
        string="Estatus de contingencia",
        default="por_notificar",
        required=True,
    )
    contingency_3 = fields.Boolean(
        string="Contingencia tipo 3", related="document_id.contingency_3"
    )
    contingency_4 = fields.Boolean(
        string="Contingencia tipo 4", related="document_id.contingency_4"
    )
    count_error_DIAN = fields.Integer(
        string="contador de intentos fallidos por problemas de la DIAN", default=0
    )
    date_error_DIAN_1 = fields.Datetime(string="Fecha del 1er. mensaje de error DIAN")
    message_error_DIAN_1 = fields.Text(
        string="Mensaje del 1er. error de respuesta DIAN"
    )
    date_error_DIAN_2 = fields.Datetime(string="Fecha del 2do. mensaje de error DIAN")
    message_error_DIAN_2 = fields.Text(
        string="Mensaje del 2do. error de respuesta DIAN"
    )
    date_error_DIAN_3 = fields.Datetime(string="Fecha del 3er. mensaje de error DIAN")
    message_error_DIAN_3 = fields.Text(
        string="Mensaje del 3er. error de respuesta DIAN"
    )
    qr_data = fields.Text(string="qr Data")
    
    # Campos nuevos del modelo heredado
    message_json = fields.Html(string="Mensaje JSON")
    invoice_id = fields.Many2one(comodel_name='ir.attachment', string="XML Factura", ondelete='cascade')
    response_id = fields.Many2one(comodel_name='ir.attachment', string="Respuesta DIAN", ondelete='cascade')
    attachment_id = fields.Many2one(comodel_name='ir.attachment', string="Attached DIAN", ondelete='cascade')
    zip_id = fields.Many2one(comodel_name='ir.attachment', string="Archivo ZIP", ondelete='cascade')
    email_state = fields.Selection([
        ('pending', 'Pendiente'),
        ('sent', 'Enviado'),
        ('failed', 'Fallido')
    ], string='Estado Email', default='pending')
    email_retry_count = fields.Integer('Intentos de Envío', default=0)
    last_email_try = fields.Datetime('Último Intento de Envío')
    email_error = fields.Text('Error de Envío')
    email_cron = fields.Boolean('Envío Por Cron')

    # Campos computados para facilitar descarga
    has_xml = fields.Boolean(compute='_compute_has_attachments', store=True, string='Tiene XML')
    has_zip = fields.Boolean(compute='_compute_has_attachments', store=True, string='Tiene ZIP')
    has_response = fields.Boolean(compute='_compute_has_attachments', store=True, string='Tiene Respuesta')

    @api.depends('invoice_id', 'zip_id', 'response_id')
    def _compute_has_attachments(self):
        for rec in self:
            rec.has_xml = bool(rec.invoice_id)
            rec.has_zip = bool(rec.zip_id)
            rec.has_response = bool(rec.response_id)

    @api.model
    def _auto_init(self):
        """Inicializa campos computados al crear/actualizar la tabla"""
        res = super()._auto_init()

        # Actualizar campos computados para registros existentes
        if self.env.context.get('module_install'):
            _logger.info("Inicializando campos computados de dian.document")
            try:
                # Recomputar campos has_xml, has_zip, has_response
                self.search([])._compute_has_attachments()
            except Exception as e:
                _logger.warning(f"No se pudieron inicializar campos computados: {e}")

        return res

    def _get_software_identification_code(self):
        company = self.env.company
        return company.software_identification_code

    def _generate_software_security_code(
        self, software_identification_code, software_pin, NroDocumento
    ):
        software_security_code = hashlib.sha384(
            (software_identification_code + software_pin + NroDocumento).encode()
        )
        software_security_code = software_security_code.hexdigest()
        return software_security_code

    def _get_software_pin(self):
        company = self.env.company
        return company.software_pin

    def _generate_CertDigestDigestValue(self):
        _, certificate = self.get_key()

        cert_der = certificate.public_bytes(encoding=serialization.Encoding.DER)
        digest = hashes.Hash(hashes.SHA256())
        digest.update(cert_der)
        cert_digest = digest.finalize()
        CertDigestDigestValue = base64.b64encode(cert_digest).decode()
        return CertDigestDigestValue

    def get_key(self):
        company = self.env.company
        password = company.certificate_key
        try:
            archivo_key = base64.b64decode(company.certificate_file)

            private_key, certificate, additional_certificates = pkcs12.load_key_and_certificates(
                archivo_key, password.encode(), backend=default_backend()
            )

            return private_key, certificate
        except Exception as ex:
            raise UserError(_("Failed to load certificate: %s") % tools.ustr(ex))

    def _template_signature_data_xml(self):
        template_signature_data_xml = """
                <ds:Signature xmlns:ds="http://www.w3.org/2000/09/xmldsig#" Id="xmldsig-%(identifier)s">
                    <ds:SignedInfo>
                        <ds:CanonicalizationMethod Algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315"/>
                        <ds:SignatureMethod Algorithm="http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"/>
                        <ds:Reference Id="xmldsig-%(identifier)s-ref0" URI="">
                            <ds:Transforms>
                                <ds:Transform Algorithm="http://www.w3.org/2000/09/xmldsig#enveloped-signature"/>
                            </ds:Transforms>
                            <ds:DigestMethod  Algorithm="http://www.w3.org/2001/04/xmlenc#sha256"/>
                            <ds:DigestValue>%(data_xml_signature_ref_zero)s</ds:DigestValue>
                        </ds:Reference>
                        <ds:Reference URI="#xmldsig-%(identifierkeyinfo)s-keyinfo">
                            <ds:DigestMethod  Algorithm="http://www.w3.org/2001/04/xmlenc#sha256"/>
                            <ds:DigestValue>%(data_xml_keyinfo_base)s</ds:DigestValue>
                        </ds:Reference>
                        <ds:Reference Type="http://uri.etsi.org/01903#SignedProperties" URI="#xmldsig-%(identifier)s-signedprops">
                            <ds:DigestMethod  Algorithm="http://www.w3.org/2001/04/xmlenc#sha256"/>
                            <ds:DigestValue>%(data_xml_SignedProperties_base)s</ds:DigestValue>
                        </ds:Reference>
                    </ds:SignedInfo>
                    <ds:SignatureValue Id="xmldsig-%(identifier)s-sigvalue">%(SignatureValue)s</ds:SignatureValue>
                    <ds:KeyInfo Id="xmldsig-%(identifierkeyinfo)s-keyinfo">
                        <ds:X509Data>
                            <ds:X509Certificate>%(data_public_certificate_base)s</ds:X509Certificate>
                        </ds:X509Data>
                    </ds:KeyInfo>
                    <ds:Object>
                        <xades:QualifyingProperties xmlns:xades="http://uri.etsi.org/01903/v1.3.2#" xmlns:xades141="http://uri.etsi.org/01903/v1.4.1#" Target="#xmldsig-%(identifier)s">
                            <xades:SignedProperties Id="xmldsig-%(identifier)s-signedprops">
                                <xades:SignedSignatureProperties>
                                    <xades:SigningTime>%(data_xml_SigningTime)s</xades:SigningTime>
                                    <xades:SigningCertificate>
                                        <xades:Cert>
                                            <xades:CertDigest>
                                                <ds:DigestMethod Algorithm="http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"/>
                                                <ds:DigestValue>%(CertDigestDigestValue)s</ds:DigestValue>
                                            </xades:CertDigest>
                                            <xades:IssuerSerial>
                                                <ds:X509IssuerName>%(IssuerName)s</ds:X509IssuerName>
                                                <ds:X509SerialNumber>%(SerialNumber)s</ds:X509SerialNumber>
                                            </xades:IssuerSerial>
                                        </xades:Cert>
                                    </xades:SigningCertificate>
                                    <xades:SignaturePolicyIdentifier>
                                        <xades:SignaturePolicyId>
                                            <xades:SigPolicyId>
                                                <xades:Identifier>https://facturaelectronica.dian.gov.co/politicadefirma/v2/politicadefirmav2.pdf</xades:Identifier>
                                                <xades:Description>Politica de firma para facturas electronicas de la Republica de Colombia</xades:Description>
                                            </xades:SigPolicyId>
                                            <xades:SigPolicyHash>
                                                <ds:DigestMethod Algorithm="http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"/>
                                                <ds:DigestValue>%(data_xml_politics)s</ds:DigestValue>
                                            </xades:SigPolicyHash>
                                        </xades:SignaturePolicyId>
                                    </xades:SignaturePolicyIdentifier>
                                    <xades:SignerRole>
                                        <xades:ClaimedRoles>
                                            <xades:ClaimedRole>supplier</xades:ClaimedRole>
                                        </xades:ClaimedRoles>
                                    </xades:SignerRole>
                                </xades:SignedSignatureProperties>
                            </xades:SignedProperties>
                        </xades:QualifyingProperties>
                    </ds:Object>
                </ds:Signature>"""
        return template_signature_data_xml

    def _generate_signature_politics(self, document_repository):
        data_xml_politics = "dMoMvtcG5aIzgYo0tIsSQeVJBDnUnfSOfBpxXrmor0Y="
        return data_xml_politics

    @api.model
    def _generate_signature_ref0(
            self, data_xml_document, document_repository, password
    ):
        template_basic_data_fe_xml = data_xml_document
        template_basic_data_fe_xml = etree.tostring(
            etree.fromstring(template_basic_data_fe_xml),
            method="c14n",
            exclusive=False,
            with_comments=False,
            inclusive_ns_prefixes=None,
        )
        data_xml_sha256 = hashlib.new("sha256", template_basic_data_fe_xml)
        data_xml_digest = data_xml_sha256.digest()
        data_xml_signature_ref_zero = base64.b64encode(data_xml_digest)
        data_xml_signature_ref_zero = data_xml_signature_ref_zero.decode()
        return data_xml_signature_ref_zero

    @api.model
    def _update_signature(
            self,
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
    ):
        data_xml_signature = template_signature_data_xml % {
            "data_xml_signature_ref_zero": data_xml_signature_ref_zero,
            "data_public_certificate_base": data_public_certificate_base,
            "data_xml_keyinfo_base": data_xml_keyinfo_base,
            "data_xml_politics": data_xml_politics,
            "data_xml_SignedProperties_base": data_xml_SignedProperties_base,
            "data_xml_SigningTime": data_xml_SigningTime,
            "CertDigestDigestValue": dian_constants["CertDigestDigestValue"],
            "IssuerName": dian_constants["IssuerName"],
            "SerialNumber": dian_constants["SerialNumber"],
            "SignatureValue": data_xml_SignatureValue,
            "identifier": data_constants_document["identifier"],
            "identifierkeyinfo": data_constants_document["identifierkeyinfo"],
        }
        return data_xml_signature

    def _generate_signature_ref1(
        self, data_xml_keyinfo_generate, document_repository, password
    ):
        data_xml_keyinfo_generate = etree.tostring(
            etree.fromstring(data_xml_keyinfo_generate), method="c14n"
        )
        data_xml_keyinfo_sha256 = hashlib.new("sha256", data_xml_keyinfo_generate)
        data_xml_keyinfo_digest = data_xml_keyinfo_sha256.digest()
        data_xml_keyinfo_base = base64.b64encode(data_xml_keyinfo_digest)
        data_xml_keyinfo_base = data_xml_keyinfo_base.decode()
        return data_xml_keyinfo_base

    def _generate_signature_ref2(self, data_xml_SignedProperties_generate):
        # Generar la referencia 2, se obtine desde el elemento SignedProperties que se
        # encuentra en la firma aplicando el algoritmo SHA256 y convirtiendolo a base64.
        data_xml_SignedProperties_c14n = etree.tostring(
            etree.fromstring(data_xml_SignedProperties_generate), method="c14n"
        )
        data_xml_SignedProperties_sha256 = hashlib.new(
            "sha256", data_xml_SignedProperties_c14n
        )
        data_xml_SignedProperties_digest = data_xml_SignedProperties_sha256.digest()
        data_xml_SignedProperties_base = base64.b64encode(
            data_xml_SignedProperties_digest
        )
        data_xml_SignedProperties_base = data_xml_SignedProperties_base.decode()
        return data_xml_SignedProperties_base

    def _generate_SignatureValue(self, data_xml_SignedInfo_generate):
        data_xml_SignatureValue_c14n = etree.tostring(
            etree.fromstring(data_xml_SignedInfo_generate),
            method="c14n",
            exclusive=False,
            with_comments=False,
        )
        private_key, _ = self.get_key()
        try:
            # Sign the data
            signature = private_key.sign(
                data_xml_SignatureValue_c14n,
                padding.PKCS1v15(),
                hashes.SHA256()
            )
        except Exception as ex:
            raise UserError(_("Failed to sign the document: %s") % tools.ustr(ex))
        SignatureValue = base64.b64encode(signature).decode()

        public_key = self.get_pem()
        try:
            public_key.verify(
                signature,
                data_xml_SignatureValue_c14n,
                padding.PKCS1v15(),
                hashes.SHA256()
            )
        except Exception:
            raise UserError(_("Signature was not successfully validated"))

        return SignatureValue

    def get_pem(self):
        company = self.env.company
        try:
            archivo_pem = base64.b64decode(company.pem_file)
            certificate = x509.load_pem_x509_certificate(archivo_pem, default_backend())
            return certificate.public_key()
        except Exception as ex:
            raise UserError(_("Failed to load PEM file: %s") % tools.ustr(ex))

    def _get_identificador_set_pruebas(self):
        company = (
            self.env["res.company"].sudo().search([("id", "=", self.env.company.id)])
        )
        return company.identificador_set_pruebas

    def _generate_datetime_timestamp(self):
        fmt = "%Y-%m-%dT%H:%M:%S.%f"
        # now_utc = datetime.now(timezone('UTC'))
        now_bogota = datetime.now(timezone("UTC"))
        # now_bogota = now_utc.astimezone(timezone('America/Bogota'))
        Created = now_bogota.strftime(fmt)[:-3] + "Z"
        now_bogota = now_bogota + timedelta(minutes=5)
        Expires = now_bogota.strftime(fmt)[:-3] + "Z"
        timestamp = {"Created": Created, "Expires": Expires}
        return timestamp

    def _generate_digestvalue_to(self, elementTo):
        # Generar el digestvalue de to
        elementTo = etree.tostring(etree.fromstring(elementTo), method="c14n")
        elementTo_sha256 = hashlib.new("sha256", elementTo)
        elementTo_digest = elementTo_sha256.digest()
        elementTo_base = base64.b64encode(elementTo_digest)
        elementTo_base = elementTo_base.decode()
        return elementTo_base

    def _generate_SignatureValue_GetStatus(self, data_xml_SignedInfo_generate):
        data_xml_SignatureValue_c14n = etree.tostring(
            etree.fromstring(data_xml_SignedInfo_generate), method="c14n"
        )

        private_key, _ = self.get_key()

        try:
            signature = private_key.sign(
                data_xml_SignatureValue_c14n,
                padding.PKCS1v15(),
                hashes.SHA256()
            )
        except Exception as ex:
            raise UserError(_("Failed to sign the document: %s") % tools.ustr(ex))

        SignatureValue = base64.b64encode(signature).decode()

        public_key = self.get_pem()

        try:
            public_key.verify(
                signature,
                data_xml_SignatureValue_c14n,
                padding.PKCS1v15(),
                hashes.SHA256()
            )
        except Exception:
            raise UserError(_("Firma para el GestStatus no fué validada exitosamente"))
        return SignatureValue

    def action_reload_from_xml(self):
        """
        Actualiza los datos del documento DIAN desde el XML almacenado.
        Útil para reprocesar información o corregir datos.
        """
        self.ensure_one()

        if not self.xml_document:
            raise UserError(_("No hay contenido XML para procesar."))

        try:
            # Parse del XML
            root = etree.fromstring(self.xml_document.encode('utf-8'))

            # Namespace del XML UBL
            namespaces = {
                'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2',
                'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2',
                'ext': 'urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2'
            }

            # Extraer información del XML
            vals = {}

            # CUFE
            cufe_element = root.find('.//cbc:UUID', namespaces)
            if cufe_element is not None:
                vals['cufe'] = cufe_element.text

            # Fecha del documento
            issue_date = root.find('.//cbc:IssueDate', namespaces)
            if issue_date is not None:
                vals['date_document_dian'] = issue_date.text

            # Nombre del cliente
            customer_name = root.find('.//cac:AccountingCustomerParty/cac:Party/cac:PartyName/cbc:Name', namespaces)
            if customer_name is not None:
                vals['customer_name'] = customer_name.text

            # Email del cliente
            customer_email = root.find('.//cac:AccountingCustomerParty/cac:Party/cac:Contact/cbc:ElectronicMail', namespaces)
            if customer_email is not None:
                vals['customer_email'] = customer_email.text

            # Actualizar el registro
            if vals:
                self.write(vals)
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Datos actualizados'),
                        'message': _('Los datos se han actualizado correctamente desde el XML.'),
                        'type': 'success',
                        'sticky': False,
                    }
                }
            else:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Sin cambios'),
                        'message': _('No se encontraron datos para actualizar en el XML.'),
                        'type': 'warning',
                        'sticky': False,
                    }
                }

        except etree.XMLSyntaxError as e:
            raise UserError(_("Error al procesar el XML: %s") % str(e))
        except Exception as e:
            raise UserError(_("Error inesperado al actualizar desde XML: %s") % str(e))

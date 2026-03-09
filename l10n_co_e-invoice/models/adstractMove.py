# -*- coding: utf-8 -*-
"""
Abstract DIAN Mixin - Lógica completa de firma digital DIAN Colombia
Versión completa con todos los métodos integrados de ambos archivos
"""
import logging
import base64
import zipfile
import hashlib
import uuid
import requests
import xmltodict
import re
import math
import pyqrcode
import png
import textwrap
import gzip
import json
from datetime import datetime, timedelta
from io import BytesIO
from lxml import etree
from pytz import timezone
from random import randint
from unidecode import unidecode
from odoo import api, fields, models, _, tools
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_repr, cleanup_xml_node, html_escape
from markupsafe import Markup
from . import xml_utils

# Importaciones para firma digital
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography import x509

try:
    import zlib
    compression = zipfile.ZIP_DEFLATED
except ImportError:
    compression = zipfile.ZIP_STORED

_logger = logging.getLogger(__name__)

# URLs DIAN
server_url = {
    "HABILITACION": "https://facturaelectronica.dian.gov.co/habilitacion/B2BIntegrationEngine/FacturaElectronica/facturaElectronica.wsdl",
    "PRODUCCION": "https://facturaelectronica.dian.gov.co/operacion/B2BIntegrationEngine/FacturaElectronica/facturaElectronica.wsdl",
    "HABILITACION_CONSULTA": "https://facturaelectronica.dian.gov.co/habilitacion/B2BIntegrationEngine/FacturaElectronica/consultaDocumentos.wsdl",
    "PRODUCCION_CONSULTA": "https://facturaelectronica.dian.gov.co/operacion/B2BIntegrationEngine/FacturaElectronica/consultaDocumentos.wsdl",
    "PRODUCCION_VP": "https://vpfe.dian.gov.co/WcfDianCustomerServices.svc?wsdl",
    "HABILITACION_VP": "https://vpfe-hab.dian.gov.co/WcfDianCustomerServices.svc?wsdl",
}

tipo_ambiente = {
    "PRODUCCION": "1",
    "PRUEBA": "2",
}

tributes = {
    "01": "IVA",
    "02": "IC",
    "03": "ICA",
    "04": "INC",
    "05": "ReteIVA",
    "06": "ReteFuente",
    "07": "ReteICA",
    "08": "ReteCREE",
    "20": "FtoHorticultura",
    "21": "Timbre",
    "22": "Bolsas",
    "23": "INCarbono",
    "24": "INCombustibles",
    "25": "Sobretasa Combustibles",
    "26": "Sordicom",
    "ZY": "No causa",
    "ZZ": "Nombre de la figura tributaria",
}

class AbstractDianMixin(models.AbstractModel):
    """
    Modelo abstracto que contiene toda la lógica de envío DIAN con firma digital completa
    """
    _name = 'abstract.dian.mixin'
    _description = 'DIAN Electronic Invoice Mixin with Complete Signing Logic'
    
    # -------------------------------------------------------------------------
    # CAMPOS
    # -------------------------------------------------------------------------
    
    dian_xml_attachment_id = fields.Many2one('ir.attachment', string="Adjunto XML", ondelete='cascade')
    dian_zip_attachment_id = fields.Many2one('ir.attachment', string="Archivo ZIP", ondelete='cascade')
    dian_response_attachment_id = fields.Many2one('ir.attachment', string="Respuesta", ondelete='cascade')
    dian_attached_document_id = fields.Many2one('ir.attachment', string="Documento Adjunto DIAN", ondelete='cascade')
    force_attached_document_recreation = fields.Boolean(
        string="Forzar Recreación de Documento Adjunto",
        help="Si está activo, se regenerará el documento adjunto aunque ya exista"
    )
    
    # -------------------------------------------------------------------------
    # MÉTODOS ABSTRACTOS
    # -------------------------------------------------------------------------
    
    def _collect_all_dian_data(self):
        """
        Recolecta todos los datos necesarios para DIAN
        Debe ser implementado en las clases hijas
        """
        raise NotImplementedError("Este método debe ser implementado en la clase hija")
    
    def generate_dian_xml(self):
        """
        Genera el XML del documento
        Debe ser implementado en las clases hijas
        """
        raise NotImplementedError("Este método debe ser implementado en la clase hija")
    
    # -------------------------------------------------------------------------
    # MÉTODO PRINCIPAL DE ENVÍO
    # -------------------------------------------------------------------------

    def dian_send_invoice(self):
        """
        Método de compatibilidad que redirige a action_send_to_dian.
        Este método se mantiene para compatibilidad con vistas antiguas.
        """
        return self.action_send_to_dian()

    # -------------------------------------------------------------------------
    # MÉTODOS DE CERTIFICADOS
    # -------------------------------------------------------------------------

    def get_key(self):
        """Obtiene la clave privada y certificado desde PKCS12"""
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

    # -------------------------------------------------------------------------
    # NUEVOS MÉTODOS DE FIRMA Y ENVÍO (Basados en citysalud-17)
    # -------------------------------------------------------------------------

    def _sign_dian_xml_new(self, xml_content):
        """
        Firma el XML con el certificado digital usando xml_utils.

        Args:
            xml_content: XML sin firmar (string)

        Returns:
            str: XML firmado
        """
        self.ensure_one()

        try:
            # Parse XML
            root = etree.fromstring(xml_content.encode('utf-8'))

            # Obtener certificado y clave privada
            private_key, cert = self.get_key()

            # Buscar el nodo de firma en el XML
            # Namespace para firma digital
            ns_map = {'ds': 'http://www.w3.org/2000/09/xmldsig#'}
            signature_node = root.find('.//ds:Signature', namespaces=ns_map)

            if signature_node is None:
                raise UserError(_(
                    "El XML no contiene un nodo de firma (ds:Signature). "
                    "Asegúrese de que el template XML incluya la estructura de firma."
                ))

            # Calcular los digest values de las referencias
            xml_utils._reference_digests(signature_node)

            # Firmar usando xml_utils
            xml_utils._fill_signature(signature_node, private_key)

            # Convertir de vuelta a string
            xml_signed = etree.tostring(root, encoding='unicode', pretty_print=True)

            return xml_signed

        except Exception as e:
            _logger.error(f"Error firmando XML: {str(e)}")
            raise UserError(_(f"Error al firmar XML: {str(e)}"))

    def _create_dian_zip_file(self, xml_signed, dian_constants):
        """
        Crea el archivo ZIP para envío a DIAN.

        Args:
            xml_signed: XML firmado (string)
            dian_constants: Constantes del documento

        Returns:
            bytes: Contenido del ZIP en base64
        """
        self.ensure_one()

        # Usar el nombre de archivo correcto desde dian_constants
        filename_xml = dian_constants.get('FileNameXML', f"{dian_constants.get('invoice_number', 'document')}.xml")

        # Crear ZIP en memoria
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
            zipf.writestr(filename_xml, xml_signed.encode('utf-8'))

        # Retornar en base64
        return base64.b64encode(zip_buffer.getvalue())

    def _send_soap_to_dian(self, zip_content, dian_constants):
        """
        Envía el ZIP a DIAN vía SOAP usando xml_utils.

        Args:
            zip_content: ZIP en base64
            dian_constants: Constantes del documento

        Returns:
            dict: Respuesta de DIAN parseada
        """
        self.ensure_one()

        _logger.info(f"Enviando documento a DIAN vía SOAP")

        # Determinar servicio según modo de la compañía
        company = self.env.company
        # Usar el campo production directamente si existe
        production_val = company.production if company else False
        is_test_mode = not production_val

        # Seleccionar servicio SOAP
        if is_test_mode:
            service = "SendTestSetAsync"
            soap_body_template = "l10n_co_e-invoice.send_test_set_async"
        else:
            service = "SendBillSync"
            soap_body_template = "l10n_co_e-invoice.send_bill_sync"

        # Preparar payload usando constantes
        filename_zip = dian_constants.get('FileNameZIP', f"{dian_constants.get('invoice_number', 'document')}.zip")
        payload = {
            'file_name': filename_zip,
            'content_file': zip_content.decode() if isinstance(zip_content, bytes) else zip_content,
            'soap_body_template': soap_body_template,
        }

        # Agregar test_set_id si es modo prueba y existe el campo
        if is_test_mode and company.identificador_set_pruebas:
            payload['test_set_id'] = company.identificador_set_pruebas

        # Llamar a xml_utils para construir y enviar el SOAP
        try:
            response = xml_utils._build_and_send_request(self, payload, service, company)
            return response
        except Exception as e:
            _logger.error(f"Error enviando a DIAN: {str(e)}")
            raise UserError(_(f"Error al enviar a DIAN: {str(e)}"))

    def get_pem(self):
        """Obtiene la clave pública del certificado PEM"""
        company = self.env.company
        try:
            archivo_pem = base64.b64decode(company.pem_file)
            certificate = x509.load_pem_x509_certificate(archivo_pem, default_backend())
            return certificate.public_key()
        except Exception as ex:
            raise UserError(_("Failed to load PEM file: %s") % tools.ustr(ex))

    # -------------------------------------------------------------------------
    # FIRMA USANDO XML_UTILS
    # -------------------------------------------------------------------------


    # -------------------------------------------------------------------------
    # MÉTODOS DE FIRMA
    # -------------------------------------------------------------------------

    def _generate_CertDigestDigestValue(self):
        """Genera el digest value del certificado"""
        _, certificate = self.get_key()

        cert_der = certificate.public_bytes(encoding=serialization.Encoding.DER)
        digest = hashes.Hash(hashes.SHA256())
        digest.update(cert_der)
        cert_digest = digest.finalize()
        CertDigestDigestValue = base64.b64encode(cert_digest).decode()
        return CertDigestDigestValue

    def _generate_SignatureValue(self, data_xml_SignedInfo_generate):
        """Genera el valor de la firma"""
        try:
            # Asegurar que el contenido esté en formato string
            if isinstance(data_xml_SignedInfo_generate, bytes):
                data_xml_SignedInfo_generate = data_xml_SignedInfo_generate.decode('utf-8')
            
            # Parsear y canonicalizar el SignedInfo
            parser = etree.XMLParser(remove_blank_text=True)
            xml_element = etree.fromstring(data_xml_SignedInfo_generate.encode('utf-8'), parser=parser)
            data_xml_SignatureValue_c14n = etree.tostring(
                xml_element,
                method="c14n",
                exclusive=False,
                with_comments=False,
            )
            
            # Obtener clave privada
            private_key, _ = self.get_key()
            
            try:
                # Firmar los datos
                signature = private_key.sign(
                    data_xml_SignatureValue_c14n,
                    padding.PKCS1v15(),
                    hashes.SHA256()
                )
            except Exception as ex:
                raise UserError(_("Failed to sign the document: %s") % tools.ustr(ex))
            
            SignatureValue = base64.b64encode(signature).decode()
            
            # Verificar la firma
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
            
        except Exception as e:
            _logger.error(f"Error generando SignatureValue: {str(e)}")
            raise UserError(_("Error generando valor de firma: %s") % str(e))

    def _generate_SignatureValue_GetStatus(self, data_xml_SignedInfo_generate):
        """Genera la firma para GetStatus"""
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
            raise UserError(_("Firma para el GetStatus no fué validada exitosamente"))
        return SignatureValue


    def _generate_digestvalue_to(self, elementTo):
        """Generar el digestvalue de to"""
        try:
            # Asegurar que el contenido esté en formato correcto
            if isinstance(elementTo, str):
                elementTo = elementTo.encode('utf-8')
            
            # Parsear y canonicalizar
            parser = etree.XMLParser(remove_blank_text=True)
            xml_element = etree.fromstring(elementTo, parser=parser)
            elementTo = etree.tostring(xml_element, method="c14n")
            
            # Generar hash
            elementTo_sha256 = hashlib.new("sha256", elementTo)
            elementTo_digest = elementTo_sha256.digest()
            elementTo_base = base64.b64encode(elementTo_digest)
            elementTo_base = elementTo_base.decode()
            return elementTo_base
            
        except Exception as e:
            _logger.error(f"Error generando digestvalue_to: {str(e)}")
            raise UserError(_("Error generando digest value: %s") % str(e))

    # -------------------------------------------------------------------------
    # MÉTODOS DE ENVÍO A DIAN (de ambos archivos)
    # -------------------------------------------------------------------------

    def _send_to_dian_service(self, signed_xml, dian_constants):
        """Envía el XML firmado a DIAN"""
        # Comprimir XML
        zip_content = self._create_zip_content(signed_xml, dian_constants)
        
        # Determinar servicio según ambiente
        if not self.company_id.production:
            return self._send_test_set_async(zip_content, dian_constants)
        else:
            return self._send_bill_sync(zip_content, dian_constants)

    def _send_test_set_async(self, zip_content, dian_constants):
        """Envío asíncrono para ambiente de pruebas"""
        response = xml_utils._build_and_send_request(
            self,
            payload={
                'file_name': dian_constants['FileNameZIP'],
                'content_file': base64.b64encode(zip_content).decode(),
                'test_set_id': self.company_id.identificador_set_pruebas,
                'soap_body_template': "l10n_co_e-invoice.send_test_set_async",
            },
            service="SendTestSetAsync",
            company=self.company_id,
        )
        
        if response['status_code'] == 200:
            root = etree.fromstring(response['response'])
            zip_key = root.findtext('.//{*}ZipKey')
            
            return {
                'status': 'success',
                'zip_key': zip_key,
                'response': response['response'],
                'status_code': response['status_code']
            }
        else:
            return {
                'status': 'error',
                'response': response.get('response', ''),
                'status_code': response.get('status_code', 0)
            }

    def _send_bill_sync(self, zip_content, dian_constants):
        """Envío síncrono para producción"""
        response = xml_utils._build_and_send_request(
            self,
            payload={
                'file_name': dian_constants['FileNameZIP'],
                'content_file': base64.b64encode(zip_content).decode(),
                'soap_body_template': "l10n_co_e-invoice.send_bill_sync",
            },
            service="SendBillSync",
            company=self.company_id,
        )
        
        if response['status_code'] == 200:
            return self._parse_sync_response(response['response'])
        else:
            return {
                'status': 'error',
                'response': response.get('response', ''),
                'status_code': response.get('status_code', 0)
            }

    def _parse_sync_response(self, response_xml):
        """Parsea la respuesta síncrona de DIAN"""
        try:
            root = etree.fromstring(response_xml)
            namespaces = {
                's': 'http://www.w3.org/2003/05/soap-envelope',
                'b': 'http://schemas.datacontract.org/2004/07/DianResponse',
                'c': 'http://schemas.microsoft.com/2003/10/Serialization/Arrays'
            }
            
            # Extraer datos
            status_code = root.findtext('.//b:StatusCode', namespaces=namespaces)
            status_desc = root.findtext('.//b:StatusDescription', namespaces=namespaces)
            status_msg = root.findtext('.//b:StatusMessage', namespaces=namespaces)
            is_valid = root.findtext('.//b:IsValid', namespaces=namespaces) == 'true'
            document_key = root.findtext('.//b:XmlDocumentKey', namespaces=namespaces)
            xml_file_name = root.findtext('.//b:XmlFileName', namespaces=namespaces)
            
            # Errores si existen
            errors = []
            error_nodes = root.findall('.//b:ErrorMessage/c:string', namespaces=namespaces)
            for error in error_nodes:
                if error.text:
                    errors.append(error.text)
            
            # Si no hay errores en ErrorMessage, buscar en StatusMessage
            if not errors and status_msg and 'Regla' in status_msg:
                errors.append(status_msg)
            
            return {
                'status': 'success' if is_valid else 'error',
                'status_code': status_code,
                'status_description': status_desc,
                'status_message': status_msg,
                'is_valid': is_valid,
                'document_key': document_key,
                'xml_file_name': xml_file_name,
                'errors': errors,
                'response': response_xml
            }
            
        except Exception as e:
            _logger.error(f"Error parseando respuesta DIAN: {str(e)}")
            return {
                'status': 'error',
                'errors': [str(e)],
                'response': response_xml
            }

    # -------------------------------------------------------------------------
    # PROCESAMIENTO DE RESPUESTA
    # -------------------------------------------------------------------------
    
    def _process_dian_response(self, response, dian_constants):
        """Procesa la respuesta de DIAN y actualiza el documento"""

        if response['status'] == 'error' and response.get('errors'):
            regla_90_error = any(
                'Regla: 90' in error and 'Documento procesado anteriormente' in error 
                for error in response.get('errors', [])
            )
            
            if regla_90_error:
                _logger.info(f"Documento {dian_constants['InvoiceID']} ya procesado anteriormente en DIAN")
                
                document_key = None
                if response.get('document_key', False):
                    document_key = response['document_key']
                for error in response.get('errors', []):
                    if 'CUFE' in error or 'UUID' in error:
                        cufe_match = re.search(r'[0-9a-fA-F]{96}', error)
                        if cufe_match:
                            document_key = cufe_match.group(0)
                            break
                
                if not document_key and dian_constants.get('cufe'):
                    document_key = dian_constants['cufe']
                
                if document_key:
                    self.cufe = document_key
                    if hasattr(self, 'diancode_id') and self.diancode_id:
                        self.diancode_id.cufe = document_key
                    dian_constants["cufe"] = document_key
                    try:
                        result = self._action_get_xml(cufe=document_key)
                        if result.get('success'):
                            self.state_dian_document = 'exitoso'
                            self.response_message_dian = 'Documento procesado anteriormente. XML recuperado exitosamente.'
                            
                            self._format_regla_90_message(response, document_key)
                            
                            if response.get('response'):
                                self._save_response_attachment(response['response'], dian_constants)
                            
                            if self.journal_id.dian_email_enabled and self.move_type in ('out_invoice', 'out_refund'):
                                self._create_dian_document_record(dian_constants, response)
                                self._send_dian_email()
                            
                            return
                    except Exception as e:
                        _logger.warning(f"No se pudo recuperar XML para documento procesado: {str(e)}")
                self.state_dian_document = 'exitoso'
                self.response_message_dian = 'Documento procesado anteriormente en DIAN'
                self._format_regla_90_message(response, document_key)
                
                if response.get('response'):
                    self._save_response_attachment(response['response'], dian_constants)
                
                if self.journal_id.dian_email_enabled and self.move_type in ('out_invoice', 'out_refund'):
                    self._create_dian_document_record(dian_constants, response)
                    self._send_dian_email()
                
                return
        
        if response['status'] == 'success':
            if self.company_id.production:
                if response.get('is_valid'):
                    self.state_dian_document = 'exitoso'
                    self.cufe = response.get('document_key', '')
                    self.response_message_dian = response.get('status_description', 'Documento procesado exitosamente')
                    
                    if self.journal_id.dian_email_enabled and self.move_type in ('out_invoice', 'out_refund'):
                        self._create_dian_document_record(dian_constants, response)
                        self._send_dian_email()
                else:
                    self.state_dian_document = 'rechazado'
                    self.response_message_dian = '\n'.join(response.get('errors', ['Documento rechazado']))
            else:
                self.state_dian_document = 'por_validar'
                self.ZipKey = response.get('zip_key', '')
                self.response_message_dian = 'Documento enviado, pendiente validación'
        else:
            self.state_dian_document = 'error'
            self.response_message_dian = '\n'.join(response.get('errors', ['Error en el envío']))
        
        if response.get('response'):
            self._save_response_attachment(response['response'], dian_constants)
        
        self._format_response_message(response)

    def _format_response_message(self, response):
        """Formatea el mensaje de respuesta en HTML"""
        if response['status'] == 'success':
            style = 'alert-success'
            title = 'Envío Exitoso'
        else:
            style = 'alert-danger'
            title = 'Error en el Envío'
        
        errors_html = ''
        if response.get('errors'):
            errors_html = '<ul>' + ''.join([f'<li>{e}</li>' for e in response['errors']]) + '</ul>'
        
        html_message = f'''
        <div class="alert {style}">
            <h4>{title}</h4>
            <p><strong>Estado:</strong> {response.get('status_description', 'N/A')}</p>
            {errors_html}
            {f"<p><strong>CUFE:</strong> {response.get('document_key', '')}</p>" if response.get('document_key') else ''}
        </div>
        '''
        
        self.response_message_dian = Markup(html_message)

    def _format_regla_90_message(self, response, document_key=None):
        """Formatea el mensaje HTML para error Regla 90"""
        errors_list = response.get('errors', [])
        error_90 = next((e for e in errors_list if 'Regla: 90' in e), errors_list[0] if errors_list else '')
        
        html_message = Markup(f'''
        <div class="alert alert-warning">
            <h4>Documento Procesado Anteriormente</h4>
            <p><strong>Estado:</strong> Exitoso (Regla 90)</p>
            <p><strong>Mensaje DIAN:</strong> {error_90}</p>
            {f'<p><strong>CUFE:</strong> {document_key}</p>' if document_key else ''}
            <p><em>Este documento ya fue procesado anteriormente en DIAN y se considera válido.</em></p>
        </div>
        ''')
        
        self.response_message_dian = html_message

    # -------------------------------------------------------------------------
    # MÉTODOS DE VALIDACIÓN Y GETSTATUS (del primer archivo)
    # -------------------------------------------------------------------------

    def request_validating_dian(self, document_id):
        """Solicita validación a DIAN (método del primer archivo)"""
        company = (
            self.env["res.company"].sudo().search([("id", "=", self.env.company.id)])
        )
        dian_document = self.env["dian.document"].search([("id", "=", document_id)])
        data_header_doc = self.env["account.move"].search(
            [("id", "=", dian_document.document_id.id)]
        )
        dian_constants = self._generate_dian_constants(data_header_doc, data_header_doc.move_type, False)
        trackId = dian_document.ZipKey
        identifier = uuid.uuid4()
        identifierTo = uuid.uuid4()
        identifierSecurityToken = uuid.uuid4()
        timestamp = self._generate_datetime_timestamp()
        Created = timestamp["Created"]
        Expires = timestamp["Expires"]
        template_GetStatus_xml = self._template_GetStatus_xml()
        data_xml_send = self._generate_GetStatus_send_xml(
            template_GetStatus_xml,
            identifier,
            Created,
            Expires,
            dian_constants["Certificate"],
            identifierSecurityToken,
            identifierTo,
            trackId,
        )

        parser = etree.XMLParser(remove_blank_text=True)
        data_xml_send = etree.tostring(etree.XML(data_xml_send, parser=parser))
        data_xml_send = data_xml_send.decode()
        
        # Generar DigestValue Elemento to y lo reemplaza en el xml
        ElementTO = etree.fromstring(data_xml_send)
        ElementTO = etree.tostring(ElementTO[0])
        ElementTO = etree.fromstring(ElementTO)
        ElementTO = etree.tostring(ElementTO[2])
        DigestValueTO = self._generate_digestvalue_to(ElementTO)
        data_xml_send = data_xml_send.replace(
            "<ds:DigestValue/>", "<ds:DigestValue>%s</ds:DigestValue>" % DigestValueTO
        )
        
        # Generar firma para el header de envío con el Signedinfo
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
            'xmlns:wsa="http://www.w3.org/2005/08/addressing" xmlns:soap="http://www.w3.org/2003/05/soap-envelope" '
            'xmlns:wcf="http://wcf.dian.colombia">',
            '<ds:SignedInfo xmlns:ds="http://www.w3.org/2000/09/xmldsig#" '
            'xmlns:soap="http://www.w3.org/2003/05/soap-envelope" '
            'xmlns:wcf="http://wcf.dian.colombia" xmlns:wsa="http://www.w3.org/2005/08/addressing">',
        )
        SignatureValue = self._generate_SignatureValue_GetStatus(Signedinfo)
        data_xml_send = data_xml_send.replace(
            "<ds:SignatureValue/>",
            "<ds:SignatureValue>%s</ds:SignatureValue>" % SignatureValue,
        )
        
        # Construye XML de envío de petición
        headers = {"content-type": "application/soap+xml"}
        URL_WEBService_DIAN = (
            server_url["PRODUCCION_VP"]
            if company.production
            else server_url["HABILITACION_VP"]
        )
        try:
            response = requests.post(
                URL_WEBService_DIAN, data=data_xml_send, headers=headers
            )
        except Exception:
            raise UserError(
                _(
                    "No existe comunicación con la DIAN para el servicio de recepción de Facturas Electrónicas. Por favor, revise su red o el acceso a internet."
                )
            )
        
        # Respuesta de petición
        if response.status_code != 200:  # Respuesta de envío no exitosa
            if response.status_code == 500:
                raise UserError(_("Error 500 = Error de servidor interno."))
            elif response.status_code == 503:
                raise UserError(_("Error 503 = Servicio no disponible."))
            elif response.status_code == 507:
                raise UserError(_("Error 507 = Espacio insuficiente."))
            elif response.status_code == 508:
                raise UserError(_("Error 508 = Ciclo detectado."))
            else:
                raise UserError(
                    _("Se ha producido un error de comunicación con la DIAN.")
                )
        response_dict = xmltodict.parse(response.content)
        dian_document.xml_response_dian = response.content
        if (
            response_dict["s:Envelope"]["s:Body"]["GetStatusZipResponse"][
                "GetStatusZipResult"
            ]["b:DianResponse"]["b:StatusCode"]
            == "00"
        ):
            data_header_doc.write({"diancode_id": dian_document.id})
            dian_document.response_message_dian += (
                "- Respuesta consulta estado del documento: Procesado correctamente \n"
            )
            dian_document.write({"state": "exitoso", "resend": False})
            # Envío de correo
            if not dian_document.contingency_4:
                self.env.cr.commit()

                if self.enviar_email_attached_document(
                    response.content,
                    dian_document=dian_document,
                    dian_constants=dian_constants,
                    data_header_doc=data_header_doc,
                ):
                    dian_document.date_email_send = fields.Datetime.now()
        else:
            data_header_doc.write({"diancode_id": dian_document.id})
            if (
                response_dict["s:Envelope"]["s:Body"]["GetStatusZipResponse"][
                    "GetStatusZipResult"
                ]["b:DianResponse"]["b:StatusCode"]
                == "90"
            ):
                dian_document.response_message_dian += (
                    "- Respuesta consulta estado del documento: TrackId no encontrado"
                )
                dian_document.write({"state": "por_validar", "resend": False})
            elif (
                response_dict["s:Envelope"]["s:Body"]["GetStatusZipResponse"][
                    "GetStatusZipResult"
                ]["b:DianResponse"]["b:StatusCode"]
                == "99"
            ):
                dian_document.response_message_dian += (
                    "- Respuesta consulta estado del documento: Validaciones "
                    "contiene errores en campos mandatorios "
                )
                dian_document.write({"state": "rechazado", "resend": True})
            elif (
                response_dict["s:Envelope"]["s:Body"]["GetStatusZipResponse"][
                    "GetStatusZipResult"
                ]["b:DianResponse"]["b:StatusCode"]
                == "66"
            ):
                dian_document.response_message_dian += (
                    "- Respuesta consulta estado del documento: NSU no encontrado"
                )
                dian_document.write({"state": "por_validar", "resend": False})

            dian_document.xml_send_query_dian = data_xml_send
        return True

    def action_GetStatus(self):
        """Acción para obtener estado"""
        return True

    def _generate_GetStatus_send_xml(self, template, identifier, Created, Expires, certificate, identifierSecurityToken, identifierTo, trackId):
        """Genera XML para GetStatus"""
        return template % {
            'identifier': identifier,
            'Created': Created,
            'Expires': Expires,
            'Certificate': certificate,
            'identifierSecurityToken': identifierSecurityToken,
            'identifierTo': identifierTo,
            'trackId': trackId
        }

    # -------------------------------------------------------------------------
    # MÉTODOS DE ATTACHED DOCUMENT (del primer archivo)
    # -------------------------------------------------------------------------

    def get_application_response(self, xml_response_dian):
        """Obtiene la respuesta de aplicación"""
        response_dict = xmltodict.parse(xml_response_dian)
        if "s:Envelope" in response_dict:
            if "s:Body" in response_dict["s:Envelope"]:
                if "GetStatusZipResponse" in response_dict["s:Envelope"]["s:Body"]:
                    result = response_dict["s:Envelope"]["s:Body"]["GetStatusZipResponse"]["GetStatusZipResult"]
                    if "b:XmlBase64Bytes" in result:
                        xml_base64 = result["b:XmlBase64Bytes"]
                        return base64.b64decode(xml_base64)
        return None

    def generate_attached_document(self, dian_constants, xml_document, application_response, data_header_doc, cufe):
        """Genera el documento adjunto"""
        # Implementación del attached document
        pass

    def enviar_email_attached_document_xml(
        self, xml_response_dian, dian_document, dian_constants, data_header_doc
    ):
        """Envía email con documento adjunto XML"""
        application_response = self.get_application_response(xml_response_dian)
        xml_attached_document = self.generate_attached_document(
            dian_constants,
            dian_document.xml_document,
            application_response=application_response,
            data_header_doc=data_header_doc,
            cufe=dian_document.cufe,
        )

        xml_file_name = (
            "ad%s" % (dian_document.xml_file_name[6:] if dian_document.xml_file_name else "000000.xml")
        )
        return unidecode(xml_attached_document), xml_file_name

    def enviar_email_attached_document_fe_xml(
        self, xml_response_dian, dian_document, dian_constants, data_header_doc
    ):
        """Envía email con documento adjunto FE XML"""
        xml_attached_document = self.generate_attached_document(
            dian_constants,
            dian_document.xml_document,
            application_response=xml_response_dian,
            data_header_doc=data_header_doc,
            cufe=dian_document.cufe,
        )

        xml_file_name = (
            "ad%s" % (dian_document.xml_file_name[6:] if dian_document.xml_file_name else "000000.xml")
        )
        return unidecode(xml_attached_document), xml_file_name

    def enviar_email_attached_document(
        self, xml_response_dian, dian_document, dian_constants, data_header_doc
    ):
        """Envía email con documento adjunto"""
        try:
            application_response = self.get_application_response(xml_response_dian)
            if not application_response:
                _logger.info("ERROR CON APLICATION RESPONSE")
                return
            xml_attached_docuement = self.generate_attached_document(
                dian_constants,
                dian_document.xml_document,
                application_response=application_response,
                data_header_doc=data_header_doc,
                cufe=dian_document.cufe,
            )
            return self.enviar_email(
                unidecode(xml_attached_docuement),
                dian_document.document_id.id,
                "ad%s"
                % (
                    dian_document.xml_file_name[6:]
                    if dian_document.xml_file_name
                    else "000000.xml"
                ),
            )
        except Exception as e:
            raise e

    def enviar_email(self, invoice):
        """Envía email con documentos electrónicos"""        
        template = self.env.ref("l10n_co_e-invoice.email_template_edi_invoice_dian", False)
        xml_document, error = invoice._get_attached_document()
        if error:
            raise UserError(error)
        rs_adjunto = self.env["ir.attachment"].sudo()
        name_xml = self.xml_file_name
        zip_file_name = name_xml.split(".")[0].replace("fv", "AD")
        pdf_file_name = f"{zip_file_name}.pdf"
        
        # Comprimir XML al ZIP
        with BytesIO() as zip_buffer:
            with zipfile.ZipFile(zip_buffer, 'a', zipfile.ZIP_DEFLATED) as zip_file:
                zip_file.writestr(name_xml, xml_document)
                pdf_content = self.env['ir.actions.report'].sudo()._render_qweb_pdf("account.account_invoices", invoice.id)[0]
                zip_file.writestr(pdf_file_name, pdf_content)
            zip_content = zip_buffer.getvalue()
        zip_base64 = base64.b64encode(zip_content).decode()
        attachment_data = {
            "res_id": invoice.id,
            "res_model": "account.move",
            "type": "binary",
            "name": f"{zip_file_name}.zip",
            "datas": zip_base64,
        }        
        
        nuevo_adjunto = rs_adjunto.create(attachment_data)
        if template:
            template.sudo().send_mail(
                invoice.id,
                force_send=True,
                email_values={"attachment_ids": nuevo_adjunto.ids},
            )

            invoice.message_post(
                body=_("Email enviado con documentos electrónicos adjuntos"),
                subject=_("Envío de documentos electrónicos")
            )
        else:
            raise UserError(
                _(
                    "No existe la plantilla de correo email_template_edi_invoice_dian para el email"
                )
            )
        return True

    # -------------------------------------------------------------------------
    # MÉTODOS AUXILIARES Y UTILITARIOS (del primer archivo)
    # -------------------------------------------------------------------------

    def _get_identificador_set_pruebas(self):
        """Obtiene el identificador del set de pruebas"""
        company = (
            self.env["res.company"].sudo().search([("id", "=", self.env.company.id)])
        )
        return company.identificador_set_pruebas

    def _get_software_identification_code(self):
        """Obtiene el código de identificación del software"""
        company = self.env.company
        return company.software_identification_code

    def _get_software_pin(self):
        """Obtiene el PIN del software"""
        company = self.env.company
        return company.software_pin

    def _get_password_environment(self):
        """Obtiene la contraseña del ambiente"""
        company = self.env.company
        return company.password_environment

    def _get_profile_id(self, data_header_doc):
        """Obtiene el Profile ID según el tipo de documento"""
        if data_header_doc.move_type == "out_invoice" and not data_header_doc.is_debit_note:
            return "DIAN 2.1: Factura Electrónica de Venta"
        elif data_header_doc.is_debit_note:
            return "DIAN 2.1: Nota Débito de Factura Electrónica de Venta"
        elif data_header_doc.move_type == 'out_refund':
            return "DIAN 2.1: Nota Crédito de Factura Electrónica de Venta"
        elif data_header_doc.move_type == 'in_invoice' and data_header_doc.is_debit_note == False:
            return "DIAN 2.1: documento soporte en adquisiciones efectuadas a no obligados a facturar."
        elif data_header_doc.move_type == 'in_invoice' and data_header_doc.is_debit_note or data_header_doc.debit_origin_id:
            raise UserError('Los documentos Soporte No tiene Nota Debito Habilitadas para su emisión a la DIAN, Por Favor Emitir Otro documento Soporte')
        elif data_header_doc.move_type == 'in_refund':
            return "DIAN 2.1: Nota de ajuste al documento soporte en adquisiciones efectuadas a sujetos no obligados a expedir factura o documento equivalente"

    def _get_customization_id(self, data_header_doc):
        """Obtiene el Customization ID"""
        if data_header_doc.move_type == "out_refund":
            return "22" if data_header_doc.document_without_reference else "20"
        elif data_header_doc.is_debit_note:
            return "32" if data_header_doc.document_without_reference else "30"
        elif data_header_doc.move_type in ('in_invoice', 'in_refund'):
            if data_header_doc.partner_id.type_residence == "si":
                return '10'
            elif self.document_id.partner_id.type_residence == "no":
                return '11'
            else:
                raise ValidationError('El proveedor {0} no tiene la informacion de residencia en su formulario'.format(self.document_id.partner_id.name))
        return data_header_doc.fe_operation_type

    def _get_url_qr_code(self, company):
        """Obtiene la URL del código QR"""
        if company.production:
            return 'https://catalogo-vpfe.dian.gov.co/document/searchqr?documentkey'
        else:
            return 'https://catalogo-vpfe-hab.dian.gov.co/document/searchqr?documentkey'

    def return_number_document_type(self, document_type):
        """Retorna el número del tipo de documento"""
        document_type_map = {
            "31": "31",
            "rut": "31",
            "national_citizen_id": "13",
            "civil_registration": "11",
            "id_card": "12",
            "21": "21",
            "foreign_id_card": "22",
            "passport": "41",
            "43": "43",
            'id_document': '',
            'external_id': '50',
            'residence_document': '47',
            'PEP': '47',
            'niup_id': '91',
            'foreign_colombian_card': '21',
            'foreign_resident_card': '22',
            'diplomatic_card': '',
            'PPT': '48',
            'vat': '50',
        }
        return str(document_type_map.get(document_type, "13"))

    def _generate_filename_data(self, data_resolution, NitSinDV, data_header_doc):
        """Genera los nombres de archivos"""
        return {
            "FileNameXML": self._generate_xml_filename(data_resolution, NitSinDV, data_header_doc.move_type, data_header_doc.debit_origin_id),
            "FileNameZIP": self._generate_zip_filename(data_resolution, NitSinDV, data_header_doc.move_type, data_header_doc.debit_origin_id),
        }

    def _generate_resolution_data(self, data_resolution, data_header_doc,document_type,dian_constants):
        """Genera los datos de resolución"""
        return {
            "InvoiceAuthorization": data_resolution["InvoiceAuthorization"],
            "StartDate": data_resolution["StartDate"],
            "EndDate": data_resolution["EndDate"],
            "Prefix": self._get_prefix(data_resolution, data_header_doc),
            "From": data_resolution["From"],
            "To": data_resolution["To"],
            "InvoiceID": data_resolution["InvoiceID"],
            "ContingencyID": data_resolution["ContingencyID"] if document_type == "contingency" else " ",
            "Nonce": self._generate_nonce(data_resolution["InvoiceID"], dian_constants["SeedCode"]),
            "TechnicalKey": data_resolution["TechnicalKey"],
        }

    def _generate_payment_data(self, data_header_doc):
        """Genera los datos de pago"""
        payment_data = {
            "PaymentMeansID": "1",
            "PaymentDueDate": data_header_doc.invoice_date,
            "PaymentMeansCode": data_header_doc.method_payment_id.code or "1",
        }
        if data_header_doc.payment_format == 'Credito':
            payment_data["PaymentMeansID"] = "2"
            payment_data["PaymentDueDate"] = data_header_doc.invoice_date_due

        if data_header_doc.invoice_payment_term_id.line_ids:
            for line_term_pago in data_header_doc.invoice_payment_term_id.line_ids:
                if line_term_pago.nb_days == 0:
                    payment_data["PaymentMeansID"] = "1"
                    payment_data["PaymentDueDate"] = data_header_doc.invoice_date
                else:
                    payment_data["PaymentMeansID"] = "2"
                    payment_data["PaymentDueDate"] = data_header_doc.invoice_date_due

        return payment_data

    def _generate_credit_debit_data(self, data_header_doc,in_contingency_4):
        """Genera los datos de crédito/débito"""
        credit_debit_data = {
            "credit_note_reason": data_header_doc.reversed_entry_id.narration or data_header_doc.ref,
            "billing_reference_id": data_header_doc.reversed_entry_id.name,
            "ResponseCodeCreditNote": data_header_doc.concepto_credit_note,
            "ResponseCodeDebitNote": data_header_doc.concept_debit_note,
            "DescriptionDebitCreditNote": dict(data_header_doc._fields['concepto_credit_note'].selection).get(data_header_doc.concepto_credit_note),
        }

        if self._get_doctype(data_header_doc.move_type, data_header_doc.debit_origin_id, in_contingency_4) in ("91", "92", "95"):
            invoice_cancel = data_header_doc.reversed_entry_id
            if data_header_doc.debit_origin_id:
                invoice_cancel = data_header_doc.debit_origin_id
            credit_debit_data["InvoiceReferenceDate"] = ''
            if data_header_doc.document_without_reference:
                credit_debit_data["InvoiceReferenceDate"] = data_header_doc.invoice_date

            if invoice_cancel and invoice_cancel.state_dian_document == 'exitoso':
                dian_document_cancel = self.env["dian.document"].search([
                    ("state", "=", "exitoso"),
                    ("document_type", "in", ["f", "c"]),
                    ("id", "=", invoice_cancel.diancode_id.id),
                ])
                if dian_document_cancel:
                    credit_debit_data["InvoiceReferenceID"] = dian_document_cancel.dian_code
                    credit_debit_data["InvoiceReferenceUUID"] = dian_document_cancel.cufe
                    credit_debit_data["InvoiceReferenceDate"] = invoice_cancel.invoice_date

            if (
                self.document_id.document_from_other_system
                and self.document_id.cufe_cuds_other_system
                and self.document_id.date_from_other_system
            ):
                credit_debit_data["InvoiceReferenceID"] = self.document_id.document_from_other_system
                credit_debit_data["InvoiceReferenceUUID"] = self.document_id.cufe_cuds_other_system
                credit_debit_data["InvoiceReferenceDate"] = str(self.document_id.date_from_other_system)

        return credit_debit_data

    def _generate_contingency_data(self, data_header_doc,in_contingency_4):
        """Genera los datos de contingencia"""
        contingency_data = {}

        if self._get_doctype(data_header_doc.move_type, data_header_doc.debit_origin_id, in_contingency_4)  == ("03"):
            contingency_data["ContingencyReferenceID"] = data_header_doc.contingency_invoice_number
            contingency_data["ContingencyIssueDate"] = data_header_doc.invoice_date
            contingency_data["ContingencyDocumentTypeCode"] = "FTC"

        return contingency_data

    def _generate_identifier_data(self):
        """Genera los datos de identificadores"""
        return {
            "identifier": uuid.uuid4(),
            "identifierkeyinfo": uuid.uuid4(),
        }

    def _get_prefix(self, data_resolution, data_header_doc):
        """Obtiene el prefijo según el tipo de documento"""
        prefix = data_resolution["Prefix"]
        if data_header_doc.move_type != "out_invoice" and data_header_doc.move_type != "in_invoice":
            prefix = data_resolution["PrefixNC"]
        if data_header_doc.is_debit_note:
            prefix = data_resolution["PrefixND"]
        return prefix

    def _get_calculation_rate(self, data_header_doc):
        """Obtiene la tasa de cálculo"""
        if data_header_doc.company_id.currency_id == data_header_doc.currency_id:
            return 1.00
        else:
            calculation_rate = self._get_rate_date(
                data_header_doc.company_id.id,
                data_header_doc.currency_id.id,
                data_header_doc.invoice_date,
            )
            return self._complements_second_decimal_total(calculation_rate)

    def _replace_character_especial(self, text):
        """Reemplaza caracteres especiales"""
        if text:
            for char, replacement in [('&', '&amp;'), ('<', '&lt;'), ('>', '&gt;'), ('"', '&quot;'), ("'", '&apos;')]:
                text = text.replace(char, replacement)
        return text

    def _get_partner_fiscal_responsability_code(self, partner_id):
        """Obtiene el código de responsabilidad fiscal del partner"""
        partner = self.env["res.partner"].browse(partner_id)
        return ";".join(partner.dian_obligation_type_ids.mapped('dian_code'))

    def _get_doctype(self, doctype, is_debit_note, in_contingency_4):
        """Obtiene el tipo de documento DIAN"""
        docdian = False
        if doctype == "out_invoice" and not is_debit_note:  # Es una factura
            if (
                not self.contingency_3
                and not self.contingency_4
                and not in_contingency_4
            ):
                docdian = "01"
            elif self.contingency_3 and not in_contingency_4:
                docdian = "03"
            elif self.contingency_4 and not in_contingency_4:
                docdian = "04"
            elif in_contingency_4:
                docdian = "04"
        if doctype == "out_refund":
            docdian = "91"
        if doctype == "out_invoice" and is_debit_note:
            docdian = "92"
        return docdian

    def _get_lines_invoice(self, invoice_id):
        """Obtiene el número de líneas de la factura"""
        lines = self.env["account.move.line"].search_count([
                ("move_id", "=", invoice_id),
                ("product_id", "!=", None),
                ("product_id.enable_charges", "!=", True),
                ("display_type", "=", 'product'),
                ("price_subtotal", "!=", 0.00),])
        return lines

    def _get_time(self):
        """Obtiene la hora actual"""
        fmt = "%H:%M:%S"
        now_utc = datetime.now(timezone("UTC"))
        now_time = now_utc.strftime(fmt)
        return now_time

    def _get_time_colombia(self):
        """Obtiene la hora de Colombia"""
        fmt = "%H:%M:%S-05:00"
        now_utc = datetime.now(timezone("UTC"))
        now_time = now_utc.strftime(fmt)
        return now_time

    def _generate_signature_signingtime(self):
        """Genera el tiempo de firma"""
        fmt = "%Y-%m-%dT%H:%M:%S"
        now_utc = datetime.now(timezone("UTC"))
        now_bogota = now_utc
        data_xml_SigningTime = now_bogota.strftime(fmt) + "-05:00"
        return data_xml_SigningTime

    def _generate_xml_filename(self, data_resolution, NitSinDV, doctype, is_debit_note):
        """Genera el nombre del archivo XML"""
        if doctype == "out_invoice" and not is_debit_note:
            docdian = "fv"
        elif doctype == "out_refund":
            docdian = "nc"
        elif doctype == "out_invoice" and is_debit_note:
            docdian = "nd"

        len_prefix = len(data_resolution["Prefix"])
        len_invoice = len(data_resolution["InvoiceID"])
        dian_code_int = int(data_resolution["InvoiceID"][len_prefix:len_invoice])
        dian_code_hex = self.IntToHex(dian_code_int)
        dian_code_hex.zfill(10)
        file_name_xml = docdian + NitSinDV.zfill(10) + dian_code_hex.zfill(10) + ".xml"
        return file_name_xml

    def IntToHex(self, dian_code_int):
        """Convierte entero a hexadecimal"""
        dian_code_hex = "%02x" % dian_code_int
        return dian_code_hex

    def _generate_zip_filename(self, data_resolution, NitSinDV, doctype, is_debit_note):
        """Genera el nombre del archivo ZIP"""
        if doctype == "out_invoice" and not is_debit_note:
            docdian = "fv"
        elif doctype == "out_refund":
            docdian = "nc"
        elif doctype == "out_invoice" and is_debit_note:
            docdian = "nd"
        secuenciador = data_resolution["InvoiceID"]
        dian_code_int = int(re.sub(r"\D", "", secuenciador))
        dian_code_hex = self.IntToHex(dian_code_int)
        dian_code_hex.zfill(10)
        file_name_zip = docdian + NitSinDV.zfill(10) + dian_code_hex.zfill(10) + ".zip"
        return file_name_zip

    def _generate_zip_content(
        self, FileNameXML, FileNameZIP, data_xml_document, document_repository
    ):
        """Genera el contenido ZIP"""
        # Almacena archivo XML
        xml_file = document_repository + "/" + FileNameXML
        f = open(xml_file, "w")
        f.write(str(data_xml_document))
        f.close()
        # Comprime archivo XML
        zip_file = document_repository + "/" + FileNameZIP
        zf = zipfile.ZipFile(zip_file, mode="w")
        try:
            zf.write(xml_file, compress_type=compression)
        finally:
            zf.close()
        # Obtiene datos comprimidos
        data_xml = zip_file
        data_xml = open(data_xml, "rb")
        data_xml = data_xml.read()
        contenido_data_xml_b64 = base64.b64encode(data_xml)
        contenido_data_xml_b64 = contenido_data_xml_b64.decode()
        return contenido_data_xml_b64

    @staticmethod
    def _generate_zip_multiple_files(files, zip_file_name):
        """
        Genera un ZIP con múltiples archivos
        @param: files: tuple((file_name, file_data))
        @return: base64 zip file
        """
        with zipfile.ZipFile(f"/tmp/{zip_file_name}", mode="w") as zf:
            for name, data in files:
                zf.writestr(name, data)
        with open(f"/tmp/{zip_file_name}", "rb") as zfile:
            data = zfile.read()
            return base64.b64encode(data)

    def _generate_nonce(self, InvoiceID, seed_code):
        """Genera el nonce"""
        nonce = randint(1, seed_code)
        nonce = base64.b64encode((InvoiceID + str(nonce)).encode())
        nonce = nonce.decode()
        return nonce

    def _generate_software_security_code(
        self, software_identification_code, software_pin, NroDocumento
    ):
        """Genera el código de seguridad del software"""
        software_security_code = hashlib.sha384(
            (software_identification_code + software_pin + NroDocumento).encode()
        )
        software_security_code = software_security_code.hexdigest()
        return software_security_code

    def _generate_datetime_timestamp(self):
        """Genera el timestamp de fecha y hora"""
        fmt = "%Y-%m-%dT%H:%M:%S.%f"
        now_bogota = datetime.now(timezone("UTC"))
        Created = now_bogota.strftime(fmt)[:-3] + "Z"
        now_bogota = now_bogota + timedelta(minutes=5)
        Expires = now_bogota.strftime(fmt)[:-3] + "Z"
        timestamp = {"Created": Created, "Expires": Expires}
        return timestamp

    def _generate_datetime_IssueDate(self):
        """Genera la fecha de emisión"""
        date_invoice_cufe = {}
        fmtSend = "%Y-%m-%dT%H:%M:%S"
        now_utc = datetime.now(timezone("UTC"))
        now_bogota = now_utc
        date_invoice_cufe["IssueDateSend"] = now_bogota.strftime(fmtSend)
        fmtCUFE = "%Y-%m-%d"
        date_invoice_cufe["IssueDateCufe"] = now_bogota.strftime(fmtCUFE)
        fmtInvoice = "%Y-%m-%d"
        date_invoice_cufe["IssueDate"] = now_bogota.strftime(fmtInvoice)
        return date_invoice_cufe

    def _complements_second_decimal(self, amount):
        """Complementa el segundo decimal"""
        amount_dec = round(((amount - int(amount)) * 100.0), 2)
        amount_int = int(amount_dec)
        if amount_int % 10 == 0:
            amount = str(amount) + "0"
        else:
            amount = str(amount)
        return amount

    def count_decimals(self, amount):
        """Cuenta los decimales"""
        if amount:
            return str(amount)[::-1].find(".")
        return amount

    def truncate(self, amount, decimals):
        """Trunca a un número específico de decimales"""
        if amount:
            return math.floor(amount * 10**decimals) / 10**decimals
        else:
            return "0.00"

    def _complements_second_decimal_total(
        self, amount, allow_more_than_two_decimals=False
    ):
        """Complementa el segundo decimal del total"""
        if amount:
            cant_decimals = self.count_decimals(amount)
            if cant_decimals >= 3:
                if allow_more_than_two_decimals:
                    return self.truncate(amount, 3)
                return str("{:.2f}".format(amount))
            return str("{:.2f}".format(amount))
        else:
            return "0.00"

    def _second_decimal_total(self, amount):
        """Formatea a segundo decimal"""
        if amount:
            return str("{:.2f}".format(str(amount)))
        else:
            return 0

    def _cron_validate_accept_email_invoice_dian(self):
        """Cron para validar aceptación de email de factura DIAN"""
        date_current = self._get_datetime()
        date_current = datetime.strptime(date_current, "%Y-%m-%d %H:%M:%S")
        rec_dian_documents = (
            self.env["dian.document"]
            .sudo()
            .search([("state", "=", "exitoso"), ("email_response", "=", "pending")])
        )
        for rec_dian_document in rec_dian_documents:
            if rec_dian_document.date_email_send:
                time_difference = date_current - rec_dian_document.date_email_send
                if time_difference.days > 3:
                    rec_dian_document.date_email_acknowledgment = fields.Datetime.now()
                    rec_dian_document.email_response = "accepted"

    def _get_rate_date(self, company_id, currency_id, date_invoice):
        """Obtiene la tasa de cambio por fecha"""
        Calculationrate = 0.00
        sql = """
        select max(name) as date
          from res_currency_rate
         where company_id = {}
           and currency_id = {}
           and name <= '{}'
         """.format(
            company_id,
            currency_id,
            date_invoice,
        )

        self.sudo().env.cr.execute(sql)
        resultado = self.sudo().env.cr.dictfetchall()
        if resultado[0]["date"] is not None:
            sql = """
            select rate as rate
              from res_currency_rate
             where company_id = {}
               and currency_id = {}
               and name = '{}'
             """.format(
                company_id,
                currency_id,
                resultado[0]["date"],
            )

            self.sudo().env.cr.execute(sql)
            resultado = self.sudo().env.cr.dictfetchall()
            rate = resultado[0]["rate"]
            Calculationrate = 1.00 / rate
        else:
            raise UserError(
                _(
                    "La divisa utilizada en la factura no tiene tasa de cambio registrada"
                )
            )
        return Calculationrate

    def reset_rejected_dian_data(self):
        """Resetea los datos rechazados de DIAN"""
        self.response_message_dian = " "
        self.xml_response_dian = " "
        self.xml_send_query_dian = " "
        self.response_message_dian = " "
        self.xml_document = " "
        self.xml_file_name = " "
        self.zip_file_name = " "
        self.cufe = " "
        self.date_document_dian = " "
        self.write({"state": "por_notificar", "resend": False})

    # -------------------------------------------------------------------------
    # MÉTODOS DEL SEGUNDO ARCHIVO - ATTACHED DOCUMENT
    # -------------------------------------------------------------------------
    
    def _get_attached_document_values(self, original_xml_etree, application_response_etree):
        """Obtiene los valores para generar el documento adjunto"""
        scheme_mapping = {
            'out_invoice': 'CUFE-SHA384',
            'out_refund': 'CUDE-SHA384',
            'in_invoice': 'CUDS-SHA384',
            'in_refund': 'CUDS-SHA384',
        }
        
        return {
            'profile_execution_id': original_xml_etree.findtext('./{*}ProfileExecutionID'),
            'id': original_xml_etree.findtext('./{*}ID'),
            'uuid': self.cufe,
            'uuid_attrs': {
                'schemeName': str(scheme_mapping.get(self.move_type, "CUFE-SHA384")),
            },
            'issue_date': original_xml_etree.findtext('./{*}IssueDate'),
            'issue_time': original_xml_etree.findtext('./{*}IssueTime'),
            'document_type': "Contenedor de Factura Electrónica",
            'parent_document_id': original_xml_etree.findtext('./{*}ID'),
            'parent_document': {
                'id': original_xml_etree.findtext('./{*}ID'),
                'uuid': self.cufe,
                'uuid_attrs': {
                    'schemeName': str(scheme_mapping.get(self.move_type, "CUFE-SHA384")),
                },
                'issue_date': application_response_etree.findtext('./{*}IssueDate'),
                'issue_time': application_response_etree.findtext('./{*}IssueTime'),
                'response_code': application_response_etree.findtext('.//{*}Response/{*}ResponseCode'),
                'validation_date': application_response_etree.findtext('./{*}IssueDate'),
                'validation_time': application_response_etree.findtext('./{*}IssueTime'),
            },
        }
    
    def _get_attached_document(self):
        """Retorna una tupla: (el xml del documento adjunto, mensaje de error)"""
        self.ensure_one()
        
        # Si ya existe el documento adjunto y no se fuerza recreación, devolverlo
        if self.dian_attached_document_id and not self.force_attached_document_recreation:
            return self.dian_attached_document_id.raw, ""
        
        # Llamar a GetStatus para obtener el ApplicationResponse
        status_response = self._get_status()
        if status_response['status_code'] != 200:
            return "", _(
                "Error %(code)s al llamar al servidor DIAN: %(response)s",
                code=status_response['status_code'],
                response=status_response['response'],
            )
        
        status_etree = etree.fromstring(status_response['response'])
        application_response = base64.b64decode(status_etree.findtext(".//{*}XmlBase64Bytes"))
        
        # Obtener el XML original
        original_xml = None
        if self.dian_xml_attachment_id:
            original_xml = base64.b64decode(self.dian_xml_attachment_id.datas)
        else:
            # Si no hay attachment, intentar recuperarlo
            xml_content = self._retrieve_xml_from_dian()
            if xml_content:
                original_xml = xml_content
        
        if not original_xml:
            return "", _("No se pudo obtener el XML original del documento")
        
        original_xml_etree = etree.fromstring(original_xml)
        
        # Renderizar el Documento Adjunto
        vals = self._get_attached_document_values(
            original_xml_etree=original_xml_etree,
            application_response_etree=etree.fromstring(application_response),
        )
        
        attached_document = self.env['ir.qweb']._render('l10n_co_e-invoice.attached_document_template', vals)
        attached_doc_etree = etree.fromstring(attached_document)
        
        supplier_node = original_xml_etree.find('./{*}AccountingSupplierParty//{*}PartyTaxScheme')
        customer_node = original_xml_etree.find('./{*}AccountingCustomerParty//{*}PartyTaxScheme')
        if supplier_node is not None:
            attached_doc_etree.find('./{*}SenderParty').append(supplier_node)
        if customer_node is not None:
            attached_doc_etree.find('./{*}ReceiverParty').append(customer_node)
        
        desc_original = attached_doc_etree.find('./{*}Attachment/{*}ExternalReference/{*}Description')
        if desc_original is not None:
            original_text = original_xml.decode() if isinstance(original_xml, bytes) else original_xml
            desc_original.text = original_text
        
        desc_response = attached_doc_etree.find('./{*}ParentDocumentLineReference//{*}Description')
        if desc_response is not None:
            response_text = application_response.decode() if isinstance(application_response, bytes) else application_response
            desc_response.text = response_text
        
        # Limpiar el XML
        attached_document_xml = etree.tostring(
            cleanup_xml_node(attached_doc_etree), 
            encoding="UTF-8", 
            xml_declaration=True
        )
        
        self._save_attached_document(attached_document_xml)
        
        if self.force_attached_document_recreation:
            self.force_attached_document_recreation = False
        
        return attached_document_xml, ""
    
    def _save_attached_document(self, attached_document_xml):
        """Guarda el documento adjunto como attachment"""
        if isinstance(attached_document_xml, str):
            attached_document_xml = attached_document_xml.encode('utf-8')
        
        vals = {
            'name': f'AD_{self.name}.xml',
            'type': 'binary',
            'datas': base64.b64encode(attached_document_xml),
            'raw': attached_document_xml,
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/xml',
        }
        
        if self.dian_attached_document_id:
            self.dian_attached_document_id.write(vals)
        else:
            self.dian_attached_document_id = self.env['ir.attachment'].create(vals)
    
    def _get_status(self):
        """Obtiene el estado del documento en DIAN"""
        return xml_utils._build_and_send_request(
            self,
            payload={
                'track_id': self.diancode_id,
                'soap_body_template': "l10n_co_e-invoice.get_status",
            },
            service="GetStatus",
            company=self.company_id,
        )
    
    def action_get_attached_document(self):
        """Acción para obtener manualmente el documento adjunto"""
        self.ensure_one()
        attached_document, error = self._get_attached_document()
        if error:
            raise UserError(error)
        
        return {
            'type': 'ir.actions.act_window',
            'name': _('Documento Adjunto'),
            'res_model': 'ir.attachment',
            'res_id': self.dian_attached_document_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # -------------------------------------------------------------------------
    # MÉTODOS DE EMAIL (completos de ambos archivos)
    # -------------------------------------------------------------------------
    
    def _send_dian_email(self):
        """Envía el email con los documentos electrónicos"""
        try:
            attached_document = None
            if self.state_dian_document == 'exitoso' and self.cufe:
                try:
                    attached_document, error = self._get_attached_document()
                    if error:
                        _logger.warning(f"No se pudo obtener attached document: {error}")
                except Exception as e:
                    _logger.warning(f"Error obteniendo attached document: {str(e)}")
            
            if attached_document:
                return self._send_dian_email_with_attached_document(attached_document)
            
            template = self.env.ref("l10n_co_e-invoice.email_template_edi_invoice_dian", False)
            if not template:
                _logger.warning("No se encontró la plantilla de correo email_template_edi_invoice_dian")
                return False
            
            xml_document = False
            if self.dian_xml_attachment_id:
                xml_document = base64.b64decode(self.dian_xml_attachment_id.datas)
            
            if not xml_document:
                _logger.warning("No se encontró el XML del documento para enviar por email")
                return False
            
            zip_buffer = BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                _logger.info('%s', self.diancode_id)
                xml_filename = self.diancode_id.xml_file_name if hasattr(self, 'diancode_id') and self.diancode_id else f"FE_{self.name}.xml"
                zip_file.writestr(xml_filename, xml_document)
                
                pdf_content = self.env['ir.actions.report'].sudo()._render_qweb_pdf("account.account_invoices", self.id)[0]
                pdf_filename = xml_filename.replace('.xml', '.pdf')
                zip_file.writestr(pdf_filename, pdf_content)
            
            zip_content = zip_buffer.getvalue()
            zip_base64 = base64.b64encode(zip_content).decode()
            
            zip_attachment = self.env['ir.attachment'].create({
                'name': f"FE_{self.name}.zip",
                'type': 'binary',
                'datas': zip_base64,
                'res_model': self._name,
                'res_id': self.id,
                'mimetype': 'application/zip',
            })
            
            template.sudo().send_mail(
                self.id,
                force_send=True,
                email_values={'attachment_ids': [zip_attachment.id]}
            )
            
            self.message_post(
                body=_("Email enviado con documentos electrónicos adjuntos"),
                subject=_("Envío de documentos electrónicos")
            )
            
            if self.diancode_id:
                self.diancode_id.date_email_send = fields.Datetime.now()
            
            return True
            
        except Exception as e:
            _logger.error(f"Error enviando email DIAN: {str(e)}", exc_info=True)
            return False

    def _send_dian_email_with_attached_document(self, attached_document_xml):
        """Envía el email con los documentos electrónicos incluyendo el attached document"""
        try:
            template = self.env.ref("l10n_co_e-invoice.email_template_edi_invoice_dian", False)
            if not template:
                _logger.warning("No se encontró la plantilla de correo email_template_edi_invoice_dian")
                return False
            
            # Obtener nombre del archivo XML
            xml_filename = self.diancode_id.xml_file_name if hasattr(self, 'diancode_id') and self.diancode_id else f"FE_{self.name}.xml"
            if 'FE' in xml_filename:
                attached_name = xml_filename.replace('FE_', 'ad')
            elif 'fv' in xml_filename:
                attached_name = xml_filename.replace('fv', 'ad')
            else:
                'ad' + xml_filename
            ad_filename = f"{attached_name}"  # Attached Document filename
            zip_filename = xml_filename.split(".")[0] + ".zip"
            zip_filename = zip_filename.replace('fv', 'z')
            pdf_filename = xml_filename.replace('.xml', '.pdf')
            
            # Crear ZIP con XML, PDF y Attached Document
            zip_buffer = BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                # Agregar Attached Document
                if isinstance(attached_document_xml, str):
                    attached_document_xml = attached_document_xml.encode('utf-8')
                zip_file.writestr(ad_filename, attached_document_xml)
                
                # Generar y agregar PDF
                pdf_content = self.env['ir.actions.report'].sudo()._render_qweb_pdf("account.account_invoices", self.id)[0]
                zip_file.writestr(pdf_filename, pdf_content)
            
            zip_content = zip_buffer.getvalue()
            zip_base64 = base64.b64encode(zip_content).decode()
            
            # Crear attachment del ZIP
            zip_attachment = self.env['ir.attachment'].create({
                'name': zip_filename,
                'type': 'binary',
                'datas': zip_base64,
                'res_model': self._name,
                'res_id': self.id,
                'mimetype': 'application/zip',
            })
            
            # Enviar email
            template.sudo().send_mail(
                self.id,
                force_send=True,
                email_values={'attachment_ids': [zip_attachment.id]}
            )
            
            # Registrar en el chatter
            self.message_post(
                body=_("Email enviado con documentos electrónicos adjuntos (incluye Attached Document)"),
                subject=_("Envío de documentos electrónicos")
            )
            
            # Actualizar fecha de envío si existe el campo
            if hasattr(self, 'diancode_id') and self.diancode_id:
                self.diancode_id.date_email_send = fields.Datetime.now()
            
            return True
            
        except Exception as e:
            _logger.error(f"Error enviando email DIAN con attached document: {str(e)}", exc_info=True)
            return False

    # -------------------------------------------------------------------------
    # MÉTODOS AUXILIARES FINALES
    # -------------------------------------------------------------------------
    
    def _get_or_generate_xml(self, dian_constants):
        """Obtiene o genera el XML"""
        # Si ya tiene CUFE y no tiene XML guardado, intentar recuperar de DIAN
        if self.diancode_id and not self.archivo_xml_invoice:
            xml_content = self._retrieve_xml_from_dian()
            if xml_content:
                return xml_content
        
        # Generar nuevo
        return self.generate_dian_xml()
    
    def _retrieve_xml_from_dian(self):
        """Recupera XML desde DIAN usando GetXmlByDocumentKey"""
        try:
            response = xml_utils._build_and_send_request(
                self,
                payload={
                    'track_id': self.diancode_id,
                    'soap_body_template': "l10n_co_e-invoice.get_xml",
                },
                service="GetXmlByDocumentKey",
                company=self.company_id,
            )
            
            if response['status_code'] == 200:
                root = etree.fromstring(response['response'])
                namespaces = {
                    's': 'http://www.w3.org/2003/05/soap-envelope',
                    'b': 'http://schemas.datacontract.org/2004/07/EventResponse'
                }
                
                xml_bytes_base64 = root.xpath('//s:Body//b:XmlBytesBase64/text()', namespaces=namespaces)
                if xml_bytes_base64:
                    return base64.b64decode(xml_bytes_base64[0])
                    
        except Exception as e:
            _logger.warning(f"No se pudo recuperar XML de DIAN: {str(e)}")
            
        return None
    
    def _action_get_xml(self, name=False, cufe=False):
        """Obtiene el XML desde DIAN usando GetXmlByDocumentKey"""
        self.ensure_one()
        
        if not cufe:
            cufe = self.diancode_id
            name = f'DIAN_{self._get_dian_document_type_dian()}_invoice.xml'
        
        response = xml_utils._build_and_send_request(
            self,
            payload={
                'track_id': cufe,
                'soap_body_template': "l10n_co_e-invoice.get_xml",
            },
            service="GetXmlByDocumentKey",
            company=self.company_id,
        )
        
        if response['status_code'] == 200:
            root = etree.fromstring(response['response'])
            namespaces = {
                's': 'http://www.w3.org/2003/05/soap-envelope',
                'b': 'http://schemas.datacontract.org/2004/07/EventResponse'
            }
            
            code = root.xpath('//s:Body//b:Code/text()', namespaces=namespaces)
            message = root.xpath('//s:Body//b:Message/text()', namespaces=namespaces)
            xml_bytes_base64 = root.xpath('//s:Body//b:XmlBytesBase64/text()', namespaces=namespaces)
            
            if xml_bytes_base64:
                base64_content = xml_bytes_base64[0]
                decoded_content = base64.b64decode(base64_content)
                
                # Crear o actualizar attachment
                attachment_vals = {
                    'name': name,
                    'type': 'binary',
                    'datas': base64.b64encode(decoded_content),
                    'res_model': self._name,
                    'res_id': self.id,
                    'mimetype': 'application/xml',
                }
                
                if self.dian_xml_attachment_id:
                    self.dian_xml_attachment_id.write(attachment_vals)
                else:
                    self.dian_xml_attachment_id = self.env['ir.attachment'].create(attachment_vals)
                
                # Actualizar el documento
                self.write({
                    'state_dian_document': 'exitoso',
                    'xml_text': decoded_content.decode('utf-8') if hasattr(self, 'xml_text') else False,
                })
                
                return {
                    'success': True,
                    'xml_content': decoded_content,
                    'attachment_id': self.dian_xml_attachment_id.id
                }
            else:
                return {
                    'success': False,
                    'error': message[0] if message else 'No se pudo obtener el XML'
                }
        
        elif response['status_code']:
            raise UserError(_("El servidor de la DIAN arrojó error (Código %s)") % response['status_code'])
        else:
            raise UserError(_("El servidor DIAN no respondió."))
    
    def _create_zip_content(self, xml_content, dian_constants):
        """Crea el contenido ZIP"""
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as zip_file:
            if isinstance(xml_content, str):
                xml_content = xml_content.encode('utf-8')
            zip_file.writestr(dian_constants['FileNameXML'], xml_content)
        return buffer.getvalue()
    
    def _save_xml_attachment(self, xml_content, dian_constants):
        """Guarda el XML como attachment"""
        if isinstance(xml_content, str):
            xml_content = xml_content.encode('utf-8')
        
        vals = {
            'name': dian_constants['FileNameXML'],
            'type': 'binary',
            'datas': base64.b64encode(xml_content),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/xml',
        }
        
        if self.dian_xml_attachment_id:
            self.dian_xml_attachment_id.write(vals)
        else:
            self.dian_xml_attachment_id = self.env['ir.attachment'].create(vals)

    def _save_zip_attachment(self, zip_content, dian_constants):
        """Guarda el archivo ZIP como attachment"""
        # El zip_content ya viene en base64
        if isinstance(zip_content, bytes):
            zip_b64 = base64.b64encode(zip_content).decode()
        else:
            zip_b64 = zip_content

        vals = {
            'name': dian_constants['FileNameZIP'],
            'type': 'binary',
            'datas': zip_b64,
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/zip',
        }

        if hasattr(self, 'dian_zip_attachment_id') and self.dian_zip_attachment_id:
            self.dian_zip_attachment_id.write(vals)
        else:
            self.dian_zip_attachment_id = self.env['ir.attachment'].create(vals)

    def _save_response_attachment(self, response_content, dian_constants):
        """Guarda la respuesta como attachment"""
        if isinstance(response_content, str):
            response_content = response_content.encode('utf-8')
        
        vals = {
            'name': f"RESP_{dian_constants['FileNameXML']}",
            'type': 'binary',
            'datas': base64.b64encode(response_content),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/xml',
        }
        
        self.dian_response_attachment_id = self.env['ir.attachment'].create(vals)
    
    def _get_colombia_time_iso(self):
        """Obtiene la hora de Colombia en formato ISO"""
        tz_co = timezone('America/Bogota')
        now_co = datetime.now(tz=tz_co)
        return now_co.strftime('%Y-%m-%dT%H:%M:%S-05:00')
    
    def _get_dian_document_type_dian(self):
        """Retorna el tipo de documento DIAN"""
        if hasattr(self, 'is_debit_note') and self.is_debit_note:
            return 'd'
        elif self.move_type in ['out_refund', 'in_refund']:
            return 'c'
        return 'f'
    
    def _is_dian_applicable(self):
        """Verifica si aplica para DIAN"""
        return (
            self.state == 'posted' and
            self.journal_id.sequence_id.use_dian_control and
            self.move_type in ['out_invoice', 'out_refund', 'in_invoice', 'in_refund']
        )
    
    def _create_dian_document_record(self, dian_constants, response):
        """Crea el registro en dian.document con toda la información"""
        
        # Determinar si es un caso de Regla 90
        is_regla_90 = False
        if response.get('errors'):
            is_regla_90 = any(
                'Regla: 90' in error and 'Documento procesado anteriormente' in error 
                for error in response.get('errors', [])
            )
        
        vals = {
            'document_id': self.id,
            'document_type': self._get_dian_document_type_dian(),
            'state': self.state_dian_document,
            'dian_code': dian_constants['InvoiceID'],
            'cufe': self.cufe or dian_constants.get('cufe', ''),
            'cufe_seed': dian_constants.get('cufe_seed', ''),
            'QR_code': dian_constants.get('qr_code', False),
            'qr_data': dian_constants.get('qr_data', ''),
            'xml_file_name': dian_constants['FileNameXML'],
            'zip_file_name': dian_constants['FileNameZIP'],
            'response_message_dian': self.response_message_dian,
            'xml_response_dian': response.get('response', ''),
            'shipping_response': '200' if is_regla_90 else self._get_shipping_response_code(response),
            'date_document_dian': fields.Datetime.now(),
            'ZipKey': response.get('zip_key', ''),
            'contingency_3': self.contingency_3 if hasattr(self, 'contingency_3') else False,
            'contingency_4': self.contingency_4 if hasattr(self, 'contingency_4') else False,
        }
        
        # Attachments - vincular todos los archivos
        if self.dian_xml_attachment_id:
            vals['invoice_id'] = self.dian_xml_attachment_id.id
        if self.dian_zip_attachment_id:
            vals['zip_id'] = self.dian_zip_attachment_id.id
        if self.dian_response_attachment_id:
            vals['response_id'] = self.dian_response_attachment_id.id
        
        # Crear o actualizar
        if hasattr(self, 'diancode_id') and self.diancode_id:
            self.diancode_id.write(vals)
            return self.diancode_id
        else:
            dian_doc = self.env['dian.document'].create(vals)
            self.diancode_id = dian_doc
            return dian_doc
    
    def _get_shipping_response_code(self, response):
        """Determina el código de respuesta de envío"""
        if response['status'] == 'success':
            return '200'
        elif response.get('status_code') == '500':
            return '500'
        elif 'validación' in str(response.get('errors', '')):
            return '310'
        else:
            return '100'

    def _is_regla_90_response(self, response):
        """Verifica si la respuesta es un error de Regla 90"""
        if response.get('errors'):
            return any(
                'Regla: 90' in error and 'Documento procesado anteriormente' in error 
                for error in response.get('errors', [])
            )
        return False

    def _handle_regla_90_recovery(self, response, dian_doc):
        """Maneja la recuperación del XML para documentos con Regla 90"""
        try:
            document_key = self._extract_document_key_from_response(response)
            
            if document_key:
                _logger.info(f"Recuperando XML para documento Regla 90 con CUFE: {document_key}")
                
                if dian_doc:
                    dian_doc.cufe = document_key
                
                result = self._action_get_xml(
                    name=f"DIAN_{self._get_dian_document_type_dian()}_invoice.xml",
                    cufe=document_key
                )
                
                if result.get('success'):
                    _logger.info("XML recuperado exitosamente para documento Regla 90")
                    
                    html_message = Markup(f'''
                    <div class="alert alert-success">
                        <h4>Documento Procesado Anteriormente - XML Recuperado</h4>
                        <p><strong>Estado:</strong> Exitoso (Regla 90)</p>
                        <p><strong>CUFE:</strong> {document_key}</p>
                        <p><em>Este documento ya fue procesado anteriormente en DIAN. El XML ha sido recuperado exitosamente.</em></p>
                    </div>
                    ''')
                    
                    self.response_message_dian = html_message
                    if dian_doc:
                        dian_doc.response_message_dian = html_message
                else:
                    _logger.warning(f"No se pudo recuperar XML para documento Regla 90: {result.get('error', 'Error desconocido')}")
            else:
                _logger.warning("No se pudo extraer XmlDocumentKey de la respuesta Regla 90")
                
        except Exception as e:
            _logger.error(f"Error recuperando XML para Regla 90: {str(e)}", exc_info=True)

    def _extract_document_key_from_response(self, response):
        """Extrae el XmlDocumentKey de la respuesta XML"""
        try:
            if response.get('response'):
                root = etree.fromstring(response['response'].encode('utf-8') if isinstance(response['response'], str) else response['response'])
                
                namespaces = {
                    's': 'http://www.w3.org/2003/05/soap-envelope',
                    'b': 'http://schemas.datacontract.org/2004/07/DianResponse'
                }
                
                document_key = root.findtext('.//b:XmlDocumentKey', namespaces=namespaces)
                
                if document_key:
                    return document_key.strip()
                
                document_key = root.findtext('.//XmlDocumentKey')
                if document_key:
                    return document_key.strip()
                    
            if response.get('errors'):
                for error in response.get('errors', []):
                    if 'CUFE' in error or 'UUID' in error:
                        import re
                        cufe_match = re.search(r'[0-9a-fA-F]{96}', error)
                        if cufe_match:
                            return cufe_match.group(0)
                            
        except Exception as e:
            _logger.error(f"Error extrayendo XmlDocumentKey: {str(e)}")
        
        return None
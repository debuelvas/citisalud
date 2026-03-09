from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from lxml import etree
import requests
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.hazmat.backends import default_backend
from base64 import b64encode, b64decode, encodebytes
from copy import deepcopy
from datetime import timedelta
import hashlib
import logging
import uuid

from odoo.exceptions import UserError
from odoo import fields

_logger = logging.getLogger(__name__)


NS_MAP = {'ds': "http://www.w3.org/2000/09/xmldsig#"}

TEST_ENDPOINT = "https://vpfe-hab.dian.gov.co/WcfDianCustomerServices.svc?wsdl"
ENDPOINT = "https://vpfe.dian.gov.co/WcfDianCustomerServices.svc?wsdl"


def _decode_certificate(certif):
    if isinstance(certif, int):
        raise TypeError("El certificado no puede ser un número entero")
    if isinstance(certif, str):
        certif = certif.encode('ascii')
    try:
        return x509.load_pem_x509_certificate(b64decode(certif))
    except ValueError:
        # Si falla la decodificación base64, intenta cargar directamente
        return x509.load_pem_x509_certificate(certif)


def _decode_private_key(certif):
    """ Returns the private key ('cryptography.hazmat.backends.openssl.rsa._RSAPrivateKey')"""
    return serialization.load_pem_private_key(b64decode(certif.with_context(bin_size=False).key), password=None)

def _extract_certificates(cert_data):
    """Extrae todos los certificados públicos del archivo binario"""
    certs = []
    cert_start = b'-----BEGIN CERTIFICATE-----'
    cert_end = b'-----END CERTIFICATE-----'
    start = 0
    while True:
        start = cert_data.find(cert_start, start)
        if start == -1:
            break
        end = cert_data.find(cert_end, start) + len(cert_end)
        certs.append(cert_data[start:end])
        start = end
    return certs

def _extract_from_p12(p12_data, password):
    """Extrae la clave privada y los certificados de un archivo P12"""
    try:
        if isinstance(password, str):
            password = password.encode()
        private_key, cert, additional_certs = pkcs12.load_key_and_certificates(
            p12_data, password, default_backend()
        )
        return private_key, cert, additional_certs
    except Exception as e:
        _logger.error(f"Error al extraer datos del archivo P12: {str(e)}")
        raise UserError(f"No se pudo extraer la información del archivo P12: {str(e)}")


def _extract_private_key(cert_data):
    """Extrae la clave privada del archivo binario"""
    key_start = b'-----BEGIN PRIVATE KEY-----'
    key_end = b'-----END PRIVATE KEY-----'
    start = cert_data.find(key_start)
    if start == -1:
        raise ValueError("No se encontró la clave privada en el archivo")
    end = cert_data.find(key_end, start) + len(key_end)
    return cert_data[start:end]

def _decode_certificate(cert_der):
    try:
        return x509.load_der_x509_certificate(cert_der)
    except ValueError:
        # Si falla como DER, intenta como PEM
        return x509.load_pem_x509_certificate(cert_der)

def _decode_private_key(key_der):
    try:
        return load_der_private_key(key_der, password=None)
    except ValueError:
        # Si falla como DER, intenta como PEM
        return serialization.load_pem_private_key(key_der, password=None)

def _canonicalize_node(node, **kwargs):
    """
    Returns the canonical representation of node.
    Specified in: https://www.w3.org/TR/2001/REC-xml-c14n-20010315
    Required for computing digests and signatures.
    Returns an UTF-8 encoded bytes string.
    """
    return etree.tostring(node, method="c14n", with_comments=False, **kwargs)


def _get_uri(uri, reference, base_uri=""):
    """
    Returns the content within `reference` that is identified by `uri`.
    Canonicalization is used to convert node reference to an octet stream.
    - URIs starting with # are same-document references
    https://www.w3.org/TR/xmldsig-core/#sec-URI
    - Empty URIs point to the whole document tree, without the signature
    https://www.w3.org/TR/xmldsig-core/#sec-EnvelopedSignature
    Returns an UTF-8 encoded bytes string.
    """
    transform_nodes = reference.findall(".//{*}Transform")
    # handle exclusive canonization
    exc_c14n = bool(transform_nodes) and transform_nodes[0].attrib.get('Algorithm') == 'http://www.w3.org/2001/10/xml-exc-c14n#'
    prefix_list = []
    if exc_c14n:
        inclusive_ns_node = transform_nodes[0].find(".//{*}InclusiveNamespaces")
        if inclusive_ns_node is not None and inclusive_ns_node.attrib.get('PrefixList'):
            prefix_list = inclusive_ns_node.attrib.get('PrefixList').split(' ')

    node = deepcopy(reference.getroottree().getroot())
    if uri == base_uri:
        # Base URI: whole document, without signature (default is empty URI)
        for signature in node.findall('.//ds:Signature', namespaces=NS_MAP):
            if signature.tail:
                # move the tail to the previous node or to the parent
                if (previous := signature.getprevious()) is not None:
                    previous.tail = "".join([previous.tail or "", signature.tail or ""])
                else:
                    signature.getparent().text = "".join([signature.getparent().text or "", signature.tail or ""])
            signature.getparent().remove(signature)  # we can only remove a node from its direct parent
        return _canonicalize_node(node, exclusive=exc_c14n, inclusive_ns_prefixes=prefix_list)

    if uri.startswith("#"):
        path = "//*[@*[local-name() = '{}' ]=$uri]"
        results = node.xpath(path.format("Id"), uri=uri.lstrip("#"))  # case-sensitive 'Id'
        if len(results) == 1:
            return _canonicalize_node(results[0], exclusive=exc_c14n, inclusive_ns_prefixes=prefix_list)
        if len(results) > 1:
            raise UserError(f"Ambiguous reference URI {uri} resolved to {len(results)} nodes")

    raise UserError(f'URI {uri} not found')


def _reference_digests(node, base_uri=""):
    """
    Processes the references from node and computes their digest values as specified in
    https://www.w3.org/TR/xmldsig-core/#sec-DigestMethod
    https://www.w3.org/TR/xmldsig-core/#sec-DigestValue
    """
    for reference in node.findall("ds:Reference", namespaces=NS_MAP):
        ref_node = _get_uri(reference.get("URI", ""), reference, base_uri=base_uri)
        lib = hashlib.new("sha256", ref_node)
        reference.find("ds:DigestValue", namespaces=NS_MAP).text = b64encode(lib.digest())


def _fill_signature(node, private_key):
    """
    Uses private_key to sign the SignedInfo sub-node of `node`, as specified in:
    https://www.w3.org/TR/xmldsig-core/#sec-SignatureValue
    https://www.w3.org/TR/xmldsig-core/#sec-SignedInfo
    """
    signed_info_xml = node.find("ds:SignedInfo", namespaces=NS_MAP)

    exc_c14n = signed_info_xml.find(".//{*}CanonicalizationMethod").attrib.get('Algorithm') == 'http://www.w3.org/2001/10/xml-exc-c14n#'
    prefix_list = []
    if exc_c14n:
        inclusive_ns_node = signed_info_xml.find(".//{*}CanonicalizationMethod").find(".//{*}InclusiveNamespaces")
        if inclusive_ns_node is not None and inclusive_ns_node.attrib.get('PrefixList'):
            prefix_list = inclusive_ns_node.attrib.get('PrefixList').split(' ')

    signature = private_key.sign(
        _canonicalize_node(signed_info_xml, exclusive=exc_c14n, inclusive_ns_prefixes=prefix_list),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    node.find("ds:SignatureValue", namespaces=NS_MAP).text = encodebytes(signature).decode()


def _remove_tail_and_text_in_hierarchy(node):
    """ Recursively remove the tail of all nodes in hierarchy and remove the text of all non-leaf nodes. """
    node.tail = None
    if list(node):
        node.text = None
        for child in node:
            _remove_tail_and_text_in_hierarchy(child)


def _uuid1():
    return uuid.uuid1()


def _build_and_send_request(self, payload, service, company):
    certificate_file = company.certificate_file
    certificate_password = company.certificate_key

    if not certificate_file:
        raise UserError("No se encontró un archivo de certificado para esta compañía")

    p12_data = b64decode(certificate_file)
    private_key, main_cert, additional_certs = _extract_from_p12(p12_data, certificate_password)

    dt_now = fields.datetime.utcnow()
    vals = {
        'creation_time': dt_now.isoformat(timespec='milliseconds') + "Z",
        'expiration_time': (dt_now + timedelta(seconds=60000)).isoformat(timespec='milliseconds') + "Z",
        'binary_security_token_id': "X509-" + str(_uuid1()),
        'binary_security_token': b64encode(main_cert.public_bytes(encoding=serialization.Encoding.DER)).decode(),
        'wsa_node_id': "id-" + str(_uuid1()),
        'action': f"http://wcf.dian.colombia/IWcfDianCustomerServices/{service}",
        **payload,
    }

    envelope = etree.fromstring(self.env['ir.qweb']._render('l10n_co_e-invoice.soap_request_dian', vals))
    _remove_tail_and_text_in_hierarchy(envelope)
    # Hash and sign
    _reference_digests(envelope.find(".//ds:SignedInfo", {'ds': 'http://www.w3.org/2000/09/xmldsig#'}))
    _fill_signature(envelope.find(".//ds:Signature", {'ds': 'http://www.w3.org/2000/09/xmldsig#'}), private_key)
    # Send the request
    try:
        response = requests.post(
            url=TEST_ENDPOINT if not company.production else ENDPOINT,
            data=etree.tostring(envelope),
            timeout=10,
            headers={"Content-Type": f'application/soap+xml;charset=UTF-8;action="http://wcf.dian.colombia/IWcfDianCustomerServices/{service}"'},
        )
    except requests.exceptions.ReadTimeout:
        xml_response = """<?xml version="1.0" encoding="UTF-8"?>
            <s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:a="http://www.w3.org/2005/08/addressing">
                <s:Body>
                    <SendBillSyncResponse xmlns="http://wcf.dian.colombia">
                        <SendBillSyncResult>
                            <b:ErrorMessage xmlns:b="http://schemas.datacontract.org/2004/07/ServiceSoap.UBL2._0.Response">Timeout en la conexión</b:ErrorMessage>
                            <b:StatusCode xmlns:b="http://schemas.datacontract.org/2004/07/ServiceSoap.UBL2._0.Response">000</b:StatusCode>
                            <b:StatusDescription xmlns:b="http://schemas.datacontract.org/2004/07/ServiceSoap.UBL2._0.Response">Error de conexión</b:StatusDescription>
                            <b:StatusMessage xmlns:b="http://schemas.datacontract.org/2004/07/ServiceSoap.UBL2._0.Response">La conexión con DIAN ha expirado</b:StatusMessage>
                            <b:Success xmlns:b="http://schemas.datacontract.org/2004/07/ServiceSoap.UBL2._0.Response">false</b:Success>
                        </SendBillSyncResult>
                    </SendBillSyncResponse>
                </s:Body>
            </s:Envelope>"""
        return {'response': xml_response, 'status_code': '000'}
    if response.status_code != 200:
        _logger.info("DIAN server returned code %s\n%s", response.status_code, response.text)
    return {'response': response.text, 'status_code': response.status_code}


def parse_soap_response(response_text):
    """
    Parsea la respuesta SOAP de DIAN y extrae la información clave.

    Args:
        response_text (str): Texto XML de la respuesta SOAP

    Returns:
        dict: Diccionario con los datos parseados:
            - status_code: Código de estado de DIAN
            - status_description: Descripción del estado
            - status_message: Mensaje del estado
            - zip_key: Clave del ZIP (para consultar estado después)
            - is_valid: Boolean indicando si fue exitoso
            - error_messages: Lista de mensajes de error (si aplica)
            - root: Elemento raíz del XML (para procesamiento adicional)
    """
    try:
        root = etree.fromstring(response_text.encode('utf-8'))

        # Namespaces comunes en respuestas DIAN
        namespaces = {
            's': 'http://www.w3.org/2003/05/soap-envelope',
            'b': 'http://schemas.datacontract.org/2004/07/ServiceSoap.UBL2._0.Response',
            'wcf': 'http://wcf.dian.colombia',
        }

        # Buscar elementos clave
        status_code = root.find('.//{*}StatusCode')
        status_description = root.find('.//{*}StatusDescription')
        status_message = root.find('.//{*}StatusMessage')
        zip_key = root.find('.//{*}ZipKey')
        is_valid = root.find('.//{*}IsValid')

        # Buscar mensajes de error
        error_messages = []
        for error in root.findall('.//{*}ErrorMessage'):
            if error.text:
                error_messages.append(error.text)

        # Construir respuesta
        parsed = {
            'status_code': status_code.text if status_code is not None else None,
            'status_description': status_description.text if status_description is not None else None,
            'status_message': status_message.text if status_message is not None else None,
            'zip_key': zip_key.text if zip_key is not None else None,
            'is_valid': is_valid.text.lower() == 'true' if is_valid is not None else False,
            'error_messages': error_messages,
            'root': root,
        }

        # Determinar si fue exitoso
        # Generalmente StatusCode '00' o '66' indican éxito
        if parsed['status_code'] in ['00', '66', '99']:
            parsed['is_valid'] = True

        return parsed

    except Exception as e:
        _logger.error(f"Error parseando respuesta SOAP: {str(e)}")
        return {
            'error': str(e),
            'status_code': None,
            'status_description': 'Error al parsear respuesta',
            'status_message': response_text[:500] if response_text else '',
            'is_valid': False,
        }
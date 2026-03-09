# -*- coding: utf-8 -*-

import hashlib
from os import path
from uuid import uuid4
from base64 import b64encode, b64decode
from io import StringIO, BytesIO
from datetime import datetime, date, timedelta
import xmlsig
from lxml import etree
from pytz import timezone
from jinja2 import Environment, FileSystemLoader
from odoo import _, tools
from odoo.exceptions import ValidationError
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509 import load_pem_x509_certificate
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from cryptography.exceptions import InvalidKey
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography import x509

import logging
_logger = logging.getLogger(__name__)

def get_xml_soap_with_signature(
        xml_soap_without_signature,
        Id,
        certificate_file,
        certificate_key):
    wsse = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
    wsu = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"
    X509v3 = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-x509-token-profile-1.0#X509v3"
    parser = etree.XMLParser(remove_blank_text=True)
    root = etree.fromstring(xml_soap_without_signature, parser=parser)
    signature_id = "{}".format(Id)
    signature = xmlsig.template.create(
        xmlsig.constants.TransformExclC14N,
        xmlsig.constants.TransformRsaSha256,
        "SIG-" + signature_id)
    ref = xmlsig.template.add_reference(
        signature,
        xmlsig.constants.TransformSha256,
        uri="#id-" + signature_id)
    xmlsig.template.add_transform(
        ref,
        xmlsig.constants.TransformExclC14N)
    ki = xmlsig.template.ensure_key_info(
        signature,
        name="KI-" + signature_id)
    ctx = xmlsig.SignatureContext()
    ctx.load_pkcs12(get_pkcs12(certificate_file, certificate_key))

    for element in root.iter("{%s}Security" % wsse):
        element.append(signature)

    ki_str = etree.SubElement(
        ki,
        "{%s}SecurityTokenReference" % wsse)
    ki_str.attrib["{%s}Id" % wsu] = "STR-" + signature_id
    ki_str_reference = etree.SubElement(
        ki_str,
        "{%s}Reference" % wsse)
    ki_str_reference.attrib['URI'] = "#X509-" + signature_id
    ki_str_reference.attrib['ValueType'] = X509v3
    ctx.sign(signature)
    ctx.verify(signature)

    return root

# def get_xml_soap_values(certificate_file, certificate_key):
#     try:
#         Created = datetime.now().replace(tzinfo=timezone('UTC'))
#         Created = Created.astimezone(timezone('UTC'))
#         Expires = (Created + timedelta(seconds=60000)).strftime('%Y-%m-%dT%H:%M:%S.001Z')
#         Created = Created.strftime('%Y-%m-%dT%H:%M:%S.001Z')
#         private_key, cert, _ = get_pkcs12(certificate_file, certificate_key)
#         try:
#             der = b64encode(cert.public_bytes(encoding=x509.Encoding.DER)).decode("utf-8", "ignore")
#         except AttributeError:
#             try:
#                 der = b64encode(cert.public_bytes(x509.Encoding.DER)).decode("utf-8", "ignore")
#             except AttributeError:
#                 der = b64encode(cert.public_bytes()).decode("utf-8", "ignore")
        
#         return {
#             'Created': Created,
#             'Expires': Expires,
#             'Id': uuid4(),
#             'BinarySecurityToken': der
#         }
        
#     except Exception as e:
#         _logger.error(f"Error in get_xml_soap_values: {str(e)}")
#         raise Exception(f"Failed to generate SOAP values: {str(e)}")

def get_template_xml(values, template_name):
    """
    Carga y renderiza un template XML usando Jinja2.

    Estructura de templates reorganizada (2025-10-19):
    - templates/ubl/ - Templates UBL 2.1 (Invoice, CreditNote, DebitNote, AttachedDocument)
    - templates/signature/ - Templates de firma digital
    - data/soap/send/ - Templates SOAP de envío
    - data/soap/query/ - Templates SOAP de consulta
    - data/soap/events/ - Templates SOAP de eventos

    Args:
        values (dict): Valores para renderizar el template
        template_name (str): Nombre del template (con o sin extensión .xml)

    Returns:
        str: XML renderizado con entidades HTML escapadas
    """
    base_path = path.dirname(path.dirname(__file__))

    # Buscar en múltiples ubicaciones
    search_paths = [
        path.join(base_path, 'templates'),           # Raíz templates (compatibilidad)
        path.join(base_path, 'templates', 'ubl'),    # UBL 2.1
        path.join(base_path, 'templates', 'signature'),  # Firma
        path.join(base_path, 'data', 'soap', 'send'),    # SOAP envío
        path.join(base_path, 'data', 'soap', 'query'),   # SOAP consulta
        path.join(base_path, 'data', 'soap', 'events'),  # SOAP eventos
    ]

    env = Environment(loader=FileSystemLoader(search_paths))

    # Agregar .xml si no está presente
    if not template_name.endswith('.xml'):
        template_name = '{}.xml'.format(template_name)

    template_xml = env.get_template(template_name)
    xml = template_xml.render(values)

    return xml.replace('&', '&amp;').replace('&amp;amp;', '&amp;')

def get_pkcs12(certificate_file, certificate_key):
    password = certificate_key.encode('utf-8')
    try:
        p12 = pkcs12.load_key_and_certificates(
            b64decode(certificate_file),
            password,
            default_backend()
        )
        return p12
    except Exception as ex:
        raise ValidationError(tools.ustr(ex))

def get_xml_soap_values(certificate_file, certificate_key):
    try:
        Created = datetime.now().replace(tzinfo=timezone('UTC'))
        Created = Created.astimezone(timezone('UTC'))
        Expires = (Created + timedelta(seconds=60000)).strftime('%Y-%m-%dT%H:%M:%S.001Z')
        Created = Created.strftime('%Y-%m-%dT%H:%M:%S.001Z')
        
        private_key, cert, additional_certs = get_pkcs12(certificate_file, certificate_key)
        
        der = b64encode(cert.public_bytes(
            encoding=serialization.Encoding.DER,
            #format=serialization.PublicFormat.SubjectPublicKeyInfo
        )).decode("utf-8", "ignore")
        
        return {
            'Created': Created,
            'Expires': Expires,
            'Id': uuid4(),
            'BinarySecurityToken': der
        }
        
    except Exception as e:
        logging.error(f"Error in get_xml_soap_values: {str(e)}")
        raise ValidationError(f"Failed to generate SOAP values: {str(e)}")


# ==============================================================================
# UTILIDADES GENERALES (Migradas de move_inv.py)
# ==============================================================================

def get_time_utc():
    """
    Retorna la hora actual en UTC en formato HH:MM:SS

    Returns:
        str: Hora en formato HH:MM:SS
    """
    fmt = "%H:%M:%S"
    now_utc = datetime.now(timezone("UTC"))
    return now_utc.strftime(fmt)


def get_time_colombia():
    """
    Retorna la hora actual en zona horaria Colombia (-05:00) en formato HH:MM:SS-05:00

    Returns:
        str: Hora en formato HH:MM:SS-05:00
    """
    fmt = "%H:%M:%S-05:00"
    now_utc = datetime.now(timezone("UTC"))
    now_colombia = now_utc.astimezone(timezone('America/Bogota'))
    return now_colombia.strftime(fmt)


def remove_accents(input_str):
    """
    Elimina acentos y caracteres especiales de una cadena.

    Args:
        input_str (str): Cadena con posibles acentos

    Returns:
        str: Cadena sin acentos
    """
    import unicodedata
    if not input_str:
        return ''

    # Normalizar a NFD (descomponer caracteres acentuados)
    nfd = unicodedata.normalize('NFD', input_str)

    # Filtrar solo caracteres que NO sean marcas de combinación
    return ''.join(c for c in nfd if unicodedata.category(c) != 'Mn')
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
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization import pkcs12, Encoding, PublicFormat
from cryptography.hazmat.primitives.asymmetric import padding

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

    # Load PKCS12 using cryptography
    private_key, certificate, _ = pkcs12.load_key_and_certificates(
        b64decode(certificate_file),
        certificate_key.encode('utf-8')
    )
    ctx.private_key = private_key
    ctx.certificate = certificate

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

def get_xml_soap_values(certificate_file, certificate_key):
    Created = datetime.now().replace(tzinfo=timezone('UTC'))
    Created = Created.astimezone(timezone('UTC'))
    Expires = (Created + timedelta(seconds=60000)).strftime('%Y-%m-%dT%H:%M:%S.001Z')
    Created = Created.strftime('%Y-%m-%dT%H:%M:%S.001Z')

    # Load PKCS12 using cryptography
    _, certificate, _ = pkcs12.load_key_and_certificates(
        b64decode(certificate_file),
        certificate_key.encode('utf-8')
    )
    der = b64encode(certificate.public_bytes(Encoding.DER)).decode("utf-8", "ignore")

    return {
        'Created': Created,
        'Expires': Expires,
        'Id': uuid4(),
        'BinarySecurityToken': der}

def get_template_xml(values, template_name):
    base_path = path.dirname(path.dirname(__file__))
    env = Environment(loader=FileSystemLoader(path.join(
        base_path,
        'templates')))
    template_xml = env.get_template('{}.xml'.format(template_name))
    xml = template_xml.render(values)

    return xml.replace('&', '&amp;').replace('&amp;amp;', '&amp;')

def get_pkcs12(certificate_file, certificate_key):
    try:
        private_key, certificate, _ = pkcs12.load_key_and_certificates(
            b64decode(certificate_file),
            certificate_key.encode('utf-8')
        )
        return private_key, certificate
    except Exception as e:
        raise ValidationError(_("The certificate password or certificate file is not"
                                " valid.\nException: %s") % e)
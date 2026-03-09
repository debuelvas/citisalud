from odoo import _, api, fields, models, tools
import logging
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.hazmat.backends import default_backend
import base64
from io import BytesIO

_logger = logging.getLogger(__name__)

class ResCompany(models.Model):
    _inherit = "res.company"

    issuer_name = fields.Char(required=False, default='/')
    serial_number = fields.Char(required=False, default='/')
    certificate_key = fields.Char(required=False, default='/')

    def button_extract_certificate(self):
        password = self.certificate_key.encode('utf-8')
        archivo_key = base64.b64decode(self.certificate_file)
        
        try:
            private_key, certificate, additional_certificates = pkcs12.load_key_and_certificates(
                archivo_key,
                password,
                default_backend()
            )
        except Exception as ex:
            raise ValidationError(tools.ustr(ex))

        def get_reversed_rdns_name(rdns):
            OID_NAMES = {
                x509.NameOID.COMMON_NAME: 'CN',
                x509.NameOID.COUNTRY_NAME: 'C',
                x509.NameOID.DOMAIN_COMPONENT: 'DC',
                x509.NameOID.EMAIL_ADDRESS: 'E',
                x509.NameOID.GIVEN_NAME: 'G',
                x509.NameOID.LOCALITY_NAME: 'L',
                x509.NameOID.ORGANIZATION_NAME: 'O',
                x509.NameOID.ORGANIZATIONAL_UNIT_NAME: 'OU',
                x509.NameOID.SURNAME: 'SN'
            }
            name = ''
            for rdn in reversed(rdns):
                for attr in rdn:
                    if len(name) > 0:
                        name = name + ','
                    if attr.oid in OID_NAMES:
                        name = name + OID_NAMES[attr.oid]
                    else:
                        name = name + attr.oid._name
                    name = name + '=' + attr.value
            return name

        issuer = get_reversed_rdns_name(certificate.issuer.rdns)

        s = base64.b64encode(
            certificate.public_bytes(encoding=serialization.Encoding.DER)
        )
        self.issuer_name = issuer
        self.serial_number = certificate.serial_number
        self.digital_certificate = s.decode('utf-8')

        pem_data = certificate.public_bytes(encoding=serialization.Encoding.PEM)
        self.pem = "Certificate.pem"
        self.pem_file = base64.b64encode(pem_data)

        # Load PEM certificate (this step is not strictly necessary in this context, 
        # but kept for consistency with the original code)
        x509.load_pem_x509_certificate(pem_data, default_backend())
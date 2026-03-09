from datetime import date, datetime, timedelta

from odoo import _, api, fields, models, tools
from odoo.exceptions import UserError, ValidationError
from pytz import timezone
from odoo import _, api, fields, models, tools
import logging
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.hazmat.backends import default_backend
import base64
from io import BytesIO

_logger = logging.getLogger(__name__)


class ResCompanyInherit(models.Model):
    _inherit = "res.company"

    digital_certificate_payroll = fields.Text(
        string="Certificado Nomina digital público", required=True, default=""
    )
    software_identification_code_payroll = fields.Char(
        string="Código Nomina de identificación del software", required=True, default=""
    )
    identificador_set_pruebas_payroll = fields.Char(
        string="Identificador Nomina del SET de pruebas", required=True, default=""
    )
    software_pin_payroll = fields.Char(
        string="PIN Nomina del software", required=True, default=""
    )
    password_environment_payroll = fields.Char(
        string="Clave Nomina de ambiente", required=True, default=""
    )
    seed_code_payroll = fields.Integer(
        string="Código Nomina de semilla", required=True, default=5000000
    )
    issuer_name_payroll = fields.Char(
        string="Ente emisor Nomina del certificado", required=True, default=""
    )
    serial_number_payroll = fields.Char(
        string="Serial Nomina del certificado", required=True, default=""
    )
    document_repository_payroll = fields.Char(
        string="Ruta de almacenamiento de archivos Nomina", required=True, default=""
    )
    certificate_key_payroll = fields.Char(
        string="Clave del certificado P12 Nomina", required=True, default=""
    )
    pem = fields.Char(
        string="Nombre del archivo PEM del certificado", required=True, default=""
    )
    pem_file_payroll = fields.Binary("Archivo PEM")
    certificate = fields.Char(
        string="Nombre del archivo del certificado", required=True, default=""
    )
    certificate_file_payroll = fields.Binary("Archivo del certificado")
    production_payroll = fields.Boolean(
        string="Pase a producción Nomina", default=False
    )
    xml_response_numbering_range_payroll = fields.Text(
        string="Contenido XML de la respuesta DIAN a la consulta de rangos Nomina",
        readonly=True,
        default="",
    )

    def button_extract_certificate_payroll(self):
        password = self.certificate_key_payroll.encode('utf-8')
        archivo_key = base64.b64decode(self.certificate_file_payroll)
        
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
        self.issuer_name_payroll = issuer
        self.serial_number_payroll = certificate.serial_number
        self.digital_certificate_payroll = s.decode('utf-8')

        pem_data = certificate.public_bytes(encoding=serialization.Encoding.PEM)
        self.pem = "Certificate.pem"
        self.pem_file_payroll = base64.b64encode(pem_data)

        # Load PEM certificate (this step is not strictly necessary in this context, 
        # but kept for consistency with the original code)
        x509.load_pem_x509_certificate(pem_data, default_backend())
import logging
import math
import zipfile
from datetime import datetime, timedelta
from random import randint
import pytz
from odoo import _, api, fields, models, tools, Command
from odoo.exceptions import UserError,ValidationError
from pytz import timezone
from unidecode import unidecode
from hashlib import sha384
from odoo.tools import float_repr,cleanup_xml_node
from io import BytesIO
import html
from base64 import b64encode, b64decode, encodebytes
from copy import deepcopy
from datetime import timedelta
import hashlib
import logging
import uuid
from . import xml_utils
import html
from lxml import etree
import pyqrcode
import png
import hashlib
import base64
import textwrap
import gzip
try:
    import zlib
    compression = zipfile.ZIP_DEFLATED
except ImportError:
    compression = zipfile.ZIP_STORED
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509 import load_pem_x509_certificate
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from cryptography.exceptions import InvalidKey
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography import x509
import requests
import xmltodict
import uuid
import re
_logger = logging.getLogger(__name__)

ROLE_MAPPING = {
            'out_invoice': {'main': 'company', 'third': 'partner'},
            'in_invoice': {'main': 'partner', 'third': 'company'},
            'out_refund': {'main': 'company', 'third': 'partner'},
            'in_refund': {'main': 'partner', 'third': 'company'}
        }

PREFIX_MAPPING = {
            'company': 'Supplier',
            'partner': 'Customer'
        }

scheme_mapping = {
    'out_invoice': 'CUFE-SHA384',
    'out_refund': 'CUDE-SHA384',
    'in_invoice': 'CUDS-SHA384',
    'in_refund': 'CUDS-SHA384',
}


tipo_ambiente = {
    "PRODUCCION": "1",
    "PRUEBA": "2",
}

DOCUMENT_TYPES = {
            'out_invoice': {'id': 'f', 'require_prefix': True},
            'in_invoice': {'id': 'ds', 'require_prefix': True},
            'out_refund': {'id': 'nc', 'require_prefix': False},
            'in_refund': {'id': 'nc', 'require_prefix': False}
        }

TIMEOUT = 3

NAMESPACES = {
    'soap': 'http://www.w3.org/2003/05/soap-envelope',
    'wcf': 'http://wcf.dian.colombia',
    'wsa': 'http://www.w3.org/2005/08/addressing',
    'wsse': 'http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd',
    'wsu': 'http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd',
    'ds': 'http://www.w3.org/2000/09/xmldsig#', 
    'b': 'http://schemas.datacontract.org/2004/07/DianResponse',
    'xades': 'http://uri.etsi.org/01903/v1.3.2#',
    'xades141': 'http://uri.etsi.org/01903/v1.4.1#',
    'ext': 'urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2',
    'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2',
    'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2'
}
server_url = {
    "HABILITACION": "https://facturaelectronica.dian.gov.co/habilitacion/B2BIntegrationEngine/FacturaElectronica/facturaElectronica.wsdl",
    "PRODUCCION": "https://facturaelectronica.dian.gov.co/operacion/B2BIntegrationEngine/FacturaElectronica/facturaElectronica.wsdl",
    "HABILITACION_CONSULTA": "https://facturaelectronica.dian.gov.co/habilitacion/B2BIntegrationEngine/FacturaElectronica/consultaDocumentos.wsdl",
    "PRODUCCION_CONSULTA": "https://facturaelectronica.dian.gov.co/operacion/B2BIntegrationEngine/FacturaElectronica/consultaDocumentos.wsdl",
    "PRODUCCION_VP": "https://vpfe.dian.gov.co/WcfDianCustomerServices.svc?wsdl",
    "HABILITACION_VP": "https://vpfe-hab.dian.gov.co/WcfDianCustomerServices.svc?wsdl",
}


class DianDocument(models.Model):
    _inherit = "dian.document"


    def _generate_dian_constants(self, data_header_doc, document_type, in_contingency_4):
        """Genera un solo diccionario consolidado con todos los valores necesarios para las constantes DIAN."""
        company = self.env.company
        partner = company.partner_id if data_header_doc.journal_id.type == "purchase" else data_header_doc.partner_id
        roles = self._get_roles(data_header_doc)
        NitSinDV = partner.vat_co if partner.vat_co else ""
        dian_constants = {}        
        tax_data = data_header_doc.generar_invoice_tax(data_header_doc)
        dian_constants.update(self._get_technical_constants(company, data_header_doc))
        dian_constants.update(self._get_party_constants(data_header_doc, roles))
        dian_constants.update(self._get_document_constants(data_header_doc))
        data_resolution = self._get_resolution_dian(data_header_doc)
        dian_constants.update(self._get_resolution_constants(data_resolution, data_header_doc, document_type))

        dian_constants.update(tax_data)
        dian_constants.update(self._get_reference_constants(data_header_doc))
        dian_constants.update(self._generate_filename_data(data_resolution,NitSinDV,data_header_doc))
        dian_constants.update(self._get_delivery_constants(data_header_doc))
        dian_constants.update(self._generate_payment_data(data_header_doc))
        dian_constants.update(self._get_additional_constants(data_header_doc, partner))
        return dian_constants
    
    def _generate_filename_data(self, data_resolution, NitSinDV, data_header_doc):
        return {
            "FileNameXML": self._generate_xml_filename(data_resolution, NitSinDV, data_header_doc.move_type, data_header_doc.debit_origin_id),
            "FileNameZIP": self._generate_zip_filename(data_resolution, NitSinDV, data_header_doc.move_type, data_header_doc.debit_origin_id),
            "NitSinDV":NitSinDV,
        }

    def _generate_payment_data(self, data_header_doc):
        payment_data = {
            "PaymentMeansID": "1",
            "PaymentDueDate": data_header_doc.invoice_date,
            "PaymentMeansCode": data_header_doc.method_payment_id.code or "1",
            "PaymentMeansref": data_header_doc.payment_reference or data_header_doc.ref or data_header_doc.name,
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

    def _get_technical_constants(self, company, data_header_doc):
        """Obtiene constantes técnicas relacionadas con la compañía y el software."""
        software_id = self._get_software_identification_code()
        software_pin = self._get_software_pin()
        return {
            'Username': software_id,
            'Password': hashlib.new("sha256", self._get_password_environment().encode()).hexdigest(),
            'SoftwareID': software_id,
            'SoftwareSecurityCode': self._generate_software_security_code(software_id, software_pin, data_header_doc.name),
            'Certificate': company.digital_certificate,
            'CertificateKey': company.certificate_key,
            'archivo_pem': company.pem,
            'archivo_certificado': company.certificate,
            'IssuerName': company.issuer_name,
            'SerialNumber': company.serial_number,
        }


    def _get_party_constants(self, data_header_doc, roles):
        """Construye constantes para las partes involucradas (compañía y cliente/proveedor)."""
        constants = {}
        main_entity = data_header_doc.partner_id if roles['main'] == 'partner' else self.env.company.partner_id
        third_entity = self.env.company.partner_id if roles['main'] == 'partner' else data_header_doc.partner_id
        main_prefix = PREFIX_MAPPING[roles['main']]
        third_prefix = PREFIX_MAPPING[roles['third']]
        self._add_customer_supplier_info(constants, main_entity, third_entity)
        document_type = data_header_doc.partner_id.l10n_latam_identification_type_id.dian_code
        if data_header_doc.move_type in ('in_refund','in_invoice') and document_type == '13':
            document_type = '31'
            constants.update({f'SupplierSchemeIDCode': document_type})
        return constants

    def _l10n_co_edi_get_fiscal_regimen_code(self,entity):
        if entity.dian_fiscal_regimen == '48':
            return '01'
        if entity.dian_fiscal_regimen == '49':
            return 'ZZ'
        return entity.dian_fiscal_regimen

    def _l10n_co_edi_get_fiscal_regimen_name(self,entity):
        if entity.dian_fiscal_regimen == '48':
            return 'IVA'
        if entity.dian_fiscal_regimen == '49':
            return 'No aplica *'
        return dict(entity._fields["dian_fiscal_regimen"].selection).get(entity.dian_fiscal_regimen)

    def _add_customer_supplier_info(self, constants, main_entity, third_entity):
        """Agrega información adicional específica para cliente/proveedor."""
        for entity, prefix in [(main_entity, 'Supplier'), (third_entity, 'Customer')]:
            constants.update({
                f'{prefix}ID': entity.vat_co or '',
                f'{prefix}SchemeIDCode': entity.l10n_latam_identification_type_id.dian_code,
                f'{prefix}PartyName': self._replace_character_especial(entity.name),
                f'{prefix}Postal': self._replace_character_especial(entity.zip),
                f'{prefix}ElectronicPhone': self._replace_character_especial(entity.phone),
                f'{prefix}Department': entity.state_id.name if entity.state_id.name else '',
                f'{prefix}CityCode': entity.city_id.code if entity.city_id else False,
                f'{prefix}CityName': entity.city_id.name.title() if entity.city_id else entity.city,
                f'{prefix}CountrySubentity': entity.state_id.name,
                f'{prefix}IndustryClassificationCode': entity.ciiu_activity.code or '',
                f'{prefix}CountrySubentityCode': entity.city_id.code[0:2] if entity.city_id else False,
                f'{prefix}CountryCode': entity.country_id.code,
                f'{prefix}CountryName': entity.country_id.name,
                f'{prefix}AddressLine': entity.street,
                f'{prefix}TaxLevelCode': self._get_partner_fiscal_responsability_code(entity.id),
                f'{prefix}RegistrationName': self._replace_character_especial(entity.name),
                f'{prefix}Email': entity.email if entity.email else '',
                f'{prefix}Line': entity.street,
                f'{prefix}ElectronicMail': entity.email,
                f'{prefix}schemeID': entity.dv,
                f'{prefix}Firstname': self._replace_character_especial(entity.name),
                f'{prefix}TaxSchemeID': entity.tribute_id.code,
                f'{prefix}TaxSchemeName': entity.tribute_id.name,
                f'{prefix}AdditionalAccountID': "1" if entity.is_company else "2",
            })


    @api.model
    def _get_document_constants(self, data_header_doc):
        """
        Obtiene las constantes del documento, manejando múltiples referencias como tags separados.
        """
        def split_references(ref_str, date_str):
            if not ref_str:
                return []
                
            refs = ref_str.split(',')
            dates = (date_str or '').split(',')
            dates.extend([''] * (len(refs) - len(dates)))
            return list(zip(refs, dates))
        order_reference, order_date = self._extract_sale_order_data(data_header_doc.invoice_line_ids)
        despatch_ref, despatch_date = self._extract_despatch_data(data_header_doc)
        order_references = []
        if data_header_doc.invoice_origin or data_header_doc.ref:
            order_references.append({
                'cbc:ID': data_header_doc.ref or data_header_doc.invoice_origin  
            })
        despatch_references = []
        if despatch_ref:
            for ref, date in split_references(despatch_ref, despatch_date):
                ref_dict = {
                    'cbc:ID': ref.strip()
                }
                if date:
                    ref_dict['cbc:IssueDate'] = date.strip()
                despatch_references.append(ref_dict)

        constants = {
            "identifier": uuid.uuid4(),
            "identifierkeyinfo": uuid.uuid4(),
            'document_repository': self.env.company.document_repository,
            'UBLVersionID': 'UBL 2.1',
            'CustomizationID': self._get_customization_id(data_header_doc),
            'ProfileID': self._get_profile_id(data_header_doc),
            'ProfileExecutionID': tipo_ambiente["PRODUCCION"] if self.env.company.production else tipo_ambiente["PRUEBA"],
            #'UUID': str(uuid.uuid4()),
            'InvoiceTypeCode': self._get_doctype(data_header_doc.move_type, data_header_doc.debit_origin_id, False),
            'CreditNoteTypeCode': self._get_doctype(data_header_doc.move_type, data_header_doc.debit_origin_id, False),
            'DebitNoteTypeCode': self._get_doctype(data_header_doc.move_type, data_header_doc.debit_origin_id, False),
            'IssueDate': data_header_doc.fecha_xml.date().isoformat(),
            'IssueTime': data_header_doc.fecha_xml.strftime("%H:%M:%S-05:00"),
            'DocumentCurrencyCode': data_header_doc.currency_id.name,
            'LineCountNumeric': self._get_lines_invoice(data_header_doc.id),
        }

        if order_references:
            constants['OrderReference'] = order_references
        if despatch_references:
            constants['DespatchDocumentReference'] = despatch_references

        return constants

    @api.model
    def _extract_sale_order_data(self, invoice_lines):
        if not hasattr(invoice_lines, 'sale_line_ids'):
            return False, False

        sale_orders = invoice_lines.sale_line_ids.order_id
        if not sale_orders:
            return False, False

        order_refs = ",".join(order for order in sale_orders.mapped('name') if order)
        order_dates = ",".join(date.strftime('%Y-%m-%d') for date in sale_orders.mapped('date_order') if date)

        return order_refs or False, order_dates or False

    @api.model
    def _extract_despatch_data(self, invoice):
    
        if not hasattr(invoice, 'picking_ids'):
            if hasattr(invoice.invoice_line_ids, 'sale_line_ids'):
                pickings = invoice.invoice_line_ids.sale_line_ids.mapped('order_id.picking_ids')
            else:
                return False, False
        else:
            pickings = invoice.picking_ids

        if not pickings:
            return False, False

        # Filtrar solo pickings hechos/completados
        done_pickings = pickings.filtered(lambda p: p.state == 'done')
        if not done_pickings:
            return False, False

        # Extraer referencias y fechas
        picking_refs = ",".join(pick for pick in done_pickings.mapped('name') if pick)
        picking_dates = ",".join(date.strftime('%Y-%m-%d') 
                            for date in done_pickings.mapped('date_done') 
                            if date)

        return picking_refs or False, picking_dates or False


    def _get_resolution_constants(self, data_resolution, data_header_doc, document_type):
        """Obtiene constantes relacionadas con la resolución del documento."""
        return {
            'InvoiceAuthorization': data_resolution["InvoiceAuthorization"],
            'StartDate': data_resolution["StartDate"],
            'EndDate': data_resolution["EndDate"],
            'Prefix': self._get_prefix(data_resolution, data_header_doc),
            'From': data_resolution["From"],
            'To': data_resolution["To"],
            'InvoiceID': data_resolution["InvoiceID"],
            'ContingencyID': data_resolution["ContingencyID"] if document_type == "contingency" else " ",
            'TechnicalKey': data_resolution["TechnicalKey"],
        }


    def _get_reference_constants(self, data_header_doc):
        """Obtiene constantes de referencia relacionadas con el documento (créditos y débitos)."""
        credit_debit_data = {
            "credit_note_reason": data_header_doc.reversed_entry_id.narration or data_header_doc.ref,
            "billing_reference_id": data_header_doc.reversed_entry_id.name,
            "ResponseCodeCreditNote": data_header_doc.concepto_credit_note,
            "ResponseCodeDebitNote": data_header_doc.concept_debit_note,
            "DescriptionDebitCreditNote": dict(data_header_doc._fields['concepto_credit_note'].selection).get(data_header_doc.concepto_credit_note),
            "DescriptionDebitNote": dict(data_header_doc._fields['concept_debit_note'].selection).get(data_header_doc.concept_debit_note),
        }

        if self._get_doctype(data_header_doc.move_type, data_header_doc.debit_origin_id,False) in ("91", "92", "95"):
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
                data_header_doc.document_from_other_system
                and data_header_doc.cufe_cuds_other_system
                and data_header_doc.date_from_other_system
            ):
                credit_debit_data["InvoiceReferenceID"] = data_header_doc.document_from_other_system
                credit_debit_data["InvoiceReferenceUUID"] = data_header_doc.cufe_cuds_other_system
                credit_debit_data["InvoiceReferenceDate"] = str(data_header_doc.date_from_other_system)

        return credit_debit_data


    def _get_delivery_constants(self, data_header_doc):
        """Obtiene constantes relacionadas con la entrega del documento."""
        partner = data_header_doc.partner_shipping_id or data_header_doc.partner_id
        return {
            'DeliveryAddress': partner.street,
            'DeliveryCityCode': partner.city_id.code if partner.city_id else '',
            'DeliveryCityName': partner.city_id.name.title() if partner.city_id else partner.city,
            'DeliveryCountrySubentity': partner.state_id.name if partner.state_id else '',
            'DeliveryCountrySubentityCode': partner.city_id.code[:2] if partner.city_id else '',
            'DeliveryLine': partner.street,
            'DeliveryCountryCode': partner.country_id.code,
            'DeliveryCountryName': partner.country_id.name,
        }


    def _get_roles(self, doc):
        """Determina los roles según el tipo de documento."""
        doc_type = doc.move_type
        if doc.is_debit_note:
            doc_type = f'{doc_type}_debit'
        return ROLE_MAPPING.get(doc_type, ROLE_MAPPING['out_invoice'])


    def _get_additional_constants(self, data_header_doc, partner):
        partner_to_send = self.env.company.partner_id if data_header_doc.journal_id.type == "purchase" else data_header_doc.partner_id
        """Obtiene constantes adicionales necesarias para completar el diccionario DIAN."""
        return {
            "IDAdquiriente": partner_to_send.vat_co,
            "SchemeNameAdquiriente": partner_to_send.l10n_latam_identification_type_id.dian_code,
            "SchemeIDAdquiriente": partner_to_send.vat_vd,
            'SupplierAdditionalAccountID': '1' if partner.is_company else '2',
            'SeedCode': self.env.company.seed_code,
            'IdentificationCode': partner.country_id.code,
            'SoftwareProviderID': self.env.company.partner_id.vat_co or '',
            'SoftwareProviderSchemeID': self.env.company.partner_id.vat_vd,
            'ProviderID': partner.vat_co or '',
            'PINSoftware': self._get_software_pin(),
            'URLQRCode': self._get_url_qr_code(self.env.company),
            'CertDigestDigestValue': self._generate_CertDigestDigestValue(),
            'CurrencyID': data_header_doc.company_id.currency_id.name,
            'Currency': data_header_doc.currency_id.name,
            "IssueDateSend": data_header_doc.fecha_xml.date().isoformat(),
            "IssueDateCufe": data_header_doc.fecha_xml.date().isoformat(),
        }


    def _get_document_type_code(self, document_type):
        """Obtiene código de tipo de documento optimizado"""
        document_type_map = {
            "31": "31", "rut": "31", "national_citizen_id": "13",
            "civil_registration": "11", "id_card": "12", "21": "21",
            "foreign_id_card": "22", "passport": "41", "43": "43",
            'external_id': '50', 'residence_document': '47', 'PEP': '47',
            'niup_id': '91', 'foreign_colombian_card': '21',
            'foreign_resident_card': '22', 'PPT': '48', 'vat': '50'
        }
        return str(document_type_map.get(document_type, "13"))

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

    def _get_fiscal_responsibility_codes(self, entity):
        """Obtiene códigos de responsabilidad fiscal"""
        return ';'.join(entity.fiscal_responsability_ids.mapped('code'))

    def _determine_document_type(self):
        """Determina el tipo de documento y su estructura correspondiente"""
        if self.document_id.is_debit_note:
            return 'debit_note'
        elif self.document_id.move_type in ["out_refund", "in_refund"]:
            return 'credit_note'
        return 'invoice'

    @api.model
    def _get_lines_invoice(self, invoice_id):
        lines = self.env["account.move.line"].search_count([
                ("move_id", "=", invoice_id),
                ("product_id", "!=", None),
                ("product_id.enable_charges", "!=", True),
                ("display_type", "=", 'product'),
                ("price_subtotal", "!=", 0.00),])
        return lines


class DianXMLBuilder(models.AbstractModel):
    _name = 'dian.xml.builder'
    _description = 'Constructor XML DIAN'

    @api.model
    def build_ubl_extensions(self, move, template_data, tree):
        """Construye la sección UBLExtensions completa para documentos DIAN"""
        # Inicializar la estructura base de UBLExtensions con una lista de extensiones
        tree['ext:UBLExtensions'] = {
            'ext:UBLExtension': []
        }
        
        # Primera extensión: DianExtensions
        dian_extension = {
            'ext:ExtensionContent': {
                'sts:DianExtensions': {}
            }
        }
        
        dian_extensions = dian_extension['ext:ExtensionContent']['sts:DianExtensions']
        
        # InvoiceControl - Solo para facturas
        if move.move_type in ['out_invoice','in_invoice']:
            dian_extensions['sts:InvoiceControl'] = {
                'sts:InvoiceAuthorization': template_data['InvoiceAuthorization'],
                'sts:AuthorizationPeriod': {
                    'cbc:StartDate': template_data['StartDate'],
                    'cbc:EndDate': template_data['EndDate']
                },
                'sts:AuthorizedInvoices': {
                    'sts:Prefix': template_data['Prefix'],
                    'sts:From': template_data['From'],
                    'sts:To': template_data['To']
                }
            }

        # InvoiceSource
        dian_extensions['sts:InvoiceSource'] = {
            'cbc:IdentificationCode': {
                '_value': template_data['IdentificationCode'],
                '_attributes': {
                    'listAgencyID': '6',
                    'listAgencyName': 'United Nations Economic Commission for Europe',
                    'listSchemeURI': 'urn:oasis:names:specification:ubl:codelist:gc:CountryIdentificationCode-2.1'
                }
            }
        }

        # SoftwareProvider
        dian_extensions['sts:SoftwareProvider'] = {
            'sts:ProviderID': {
                '_value': template_data['SoftwareProviderID'],
                '_attributes': {
                    'schemeAgencyID': '195',
                    'schemeAgencyName': 'CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)',
                    'schemeID': template_data['SoftwareProviderSchemeID'],
                    'schemeName': '31'
                }
            },
            'sts:SoftwareID': {
                '_value': template_data['SoftwareID'],
                '_attributes': {
                    'schemeAgencyID': '195',
                    'schemeAgencyName': 'CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)'
                }
            }
        }

        # SoftwareSecurityCode
        dian_extensions['sts:SoftwareSecurityCode'] = {
            '_value': template_data['SoftwareSecurityCode'],
            '_attributes': {
                'schemeAgencyID': '195',
                'schemeAgencyName': 'CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)'
            }
        }

        # AuthorizationProvider
        dian_extensions['sts:AuthorizationProvider'] = {
            'sts:AuthorizationProviderID': {
                '_value': '800197268',
                '_attributes': {
                    'schemeAgencyID': '195',
                    'schemeAgencyName': 'CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)',
                    'schemeID': '4',
                    'schemeName': '31'
                }
            }
        }

        # QRCode
        if move.move_type == 'in_invoice':
            qr_code = (
                f"CUDS={template_data['cufe']}\n"
                f"URL={template_data['URLQRCode']}={template_data['cufe']}"
            )
        elif move.move_type == 'in_refund':
            qr_code = (
                f"CUDS={template_data['cufe']}\n"
                f"URL={template_data['URLQRCode']}={template_data['cufe']}"
            )
        else: 
            qr_code = f"NroFactura={template_data['InvoiceID']} \n"\
                    f"NitFacturador={template_data['SoftwareProviderID']} \n"\
                    f"NitAdquiriente={template_data['IDAdquiriente']} \n"\
                    f"FechaFactura={template_data['IssueDate']} \n"\
                    f"ValorTotalFactura={template_data['payable_amount']} \n"\
                    f"CUFE={template_data['cufe']} \n"\
                    f"URL={template_data['URLQRCode']}={template_data['cufe']}"

        dian_extensions['sts:QRCode'] = qr_code

        # Agregar primera extensión
        tree['ext:UBLExtensions']['ext:UBLExtension'].append(dian_extension)

        # Segunda extensión para moneda extranjera
        if move.currency_id.name != 'COP':
            foreign_currency_extension = {
                'ext:ExtensionContent': {
                    'CustomTagGeneral': {
                        'Interoperabilidad': {
                            'Group': {
                                '_attributes': {'schemeName': 'Factura de Venta'},
                                'Collection': {
                                    '_attributes': {'schemeName': 'DATOS ADICIONALES'}
                                }
                            }
                        },
                        'TotalesCop': {
                            'FctConvCop': f"{move.current_exchange_rate:.2f}",
                            'MonedaCop': move.currency_id.name,
                            'SubTotalCop': f"{float(template_data['TotalLineExtensionAmount'])/move.current_exchange_rate:.2f}",
                            'TotalBrutoFacturaCop': f"{float(template_data['TotalLineExtensionAmount'])/move.current_exchange_rate:.2f}",
                            'TotIvaCop': f"{template_data['tot_iva_cop']/move.current_exchange_rate:.2f}",
                            'TotalNetoFacturaCop': f"{float(template_data['TotalTaxExclusiveAmount'])/move.current_exchange_rate:.2f}",
                            'VlrPagarCop': f"{float(template_data['PayableAmount'])/move.current_exchange_rate:.2f}",
                            'ReteFueCop': f"{template_data.get('rete_fue_cop', 0.0)/move.current_exchange_rate:.2f}",
                            'ReteIvaCop': f"{template_data.get('rete_iva_cop', 0.0)/move.current_exchange_rate:.2f}"
                        }
                    }
                }
            }
            tree['ext:UBLExtensions']['ext:UBLExtension'].append(foreign_currency_extension)

        # Tercera extensión (vacía)
        empty_extension = {
            'ext:ExtensionContent': {}
        }
        tree['ext:UBLExtensions']['ext:UBLExtension'].append(empty_extension)

        return tree

    @api.model
    def build_header(self, move, template_data):
        """
        Construye la sección Header del documento incluyendo todas las secciones adicionales
        en el orden correcto.
        """
        header = {
            'cbc:UBLVersionID': template_data['UBLVersionID'],
            'cbc:CustomizationID': template_data['CustomizationID'],
            'cbc:ProfileID': template_data['ProfileID'],
            'cbc:ProfileExecutionID': template_data['ProfileExecutionID'],
            'cbc:ID': template_data['InvoiceID'],
            'cbc:UUID': {
                '_value': template_data['cufe'],
                '_attributes': {
                    'schemeID': template_data['ProfileExecutionID'],
                    'schemeName': str(scheme_mapping.get(move.move_type, "CUFE-SHA384"))#'CUFE-SHA384' if move.move_type in ['out_invoice'] else 'CUDE-SHA384'
                }
            },
            'cbc:IssueDate': template_data['IssueDate'],
            'cbc:IssueTime': template_data['IssueTime']
        }

        # Agregar tipos de documento y notas
        header.update(self._get_document_type_code(move, template_data))
        # Currency y Line Count al final
        header['cbc:DocumentCurrencyCode'] = self._get_currency_code(template_data)
        header['cbc:LineCountNumeric'] = template_data['LineCountNumeric']
        # Invoice Period si existe
        if template_data.get('invoice_start_date') or move.document_without_reference:
            header['cac:InvoicePeriod'] = {
                'cbc:StartDate': template_data.get('invoice_start_date') or move.date_from
            }
            if template_data.get('invoice_end_date') or move.date_to:
                header['cac:InvoicePeriod']['cbc:EndDate'] = template_data.get('invoice_end_date') or move.date_to

        # DiscrepancyResponse para notas crédito/débito
        if move.move_type in ['out_refund', 'in_refund'] or move.is_debit_note:
            header['cac:DiscrepancyResponse'] = {
                'cbc:ReferenceID': template_data.get('InvoiceReferenceID',''),
                'cbc:ResponseCode': template_data['ResponseCodeCreditNote'],
                'cbc:Description': template_data['DescriptionDebitCreditNote']
            }

        # OrderReference
        if template_data.get('OrderReference'):
            order_ref = {
                'cbc:ID': template_data['OrderReference']
            }
            if template_data.get('order_reference_date'):
                order_ref['cbc:IssueDate'] = template_data['order_reference_date']
            header['cac:OrderReference'] = order_ref

        # BillingReference
        if not move.document_without_reference and move.move_type in ['out_refund', 'in_refund'] or move.is_debit_note:
            billing_ref = {
                'cac:InvoiceDocumentReference': {
                    'cbc:ID': template_data['InvoiceReferenceID'],
                    'cbc:UUID': {
                        '_value': template_data['InvoiceReferenceUUID'],
                        '_attributes': {'schemeName': str(scheme_mapping.get(move.reversed_entry_id.move_type, "CUFE-SHA384"))}
                    }
                }
            }
            if template_data.get('InvoiceReferenceDate'):
                billing_ref['cac:InvoiceDocumentReference']['cbc:IssueDate'] = template_data['InvoiceReferenceDate']
            header['cac:BillingReference'] = billing_ref

        # DespatchDocumentReference
        if template_data.get('DespatchDocumentReference'):
            if len(template_data['DespatchDocumentReference']) == 1:
                header['cac:DespatchDocumentReference'] = template_data['DespatchDocumentReference'][0]
            else:
                header['cac:DespatchDocumentReference'] = template_data['DespatchDocumentReference']

        # ReceiptDocumentReference
        if template_data.get('OrderReference'):
            if len(template_data['OrderReference']) == 1:
                header['cac:OrderReference'] = template_data['OrderReference'][0]
            else:
                header['cac:OrderReference'] = template_data['OrderReference']

        return header

    @api.model
    def _get_document_type_code(self, move, template_data):
        """Obtiene el código de tipo de documento según el caso"""
        if move.move_type in ['out_invoice', 'in_invoice']:
            result = {'cbc:InvoiceTypeCode': template_data['InvoiceTypeCode']}
            if template_data.get('Notes'):
                result['cbc:Note'] = template_data['Notes']
            return result
        elif move.move_type in ['out_refund', 'in_refund']:
            return {'cbc:CreditNoteTypeCode': template_data['CreditNoteTypeCode']}
        elif hasattr(move, 'is_debit_note') and move.is_debit_note:
            return {'cbc:DebitNoteTypeCode': template_data['DebitNoteTypeCode']}
        return {}

    @api.model
    def _get_currency_code(self, template_data):
        """Obtiene el código de moneda con sus atributos si corresponde"""
        if template_data['CurrencyID'] != 'COP':
            return {
                '_value': template_data['DocumentCurrencyCode'],
                '_attributes': {
                    'listAgencyID': '6',
                    'listAgencyName': 'United Nations Economic Commission for Europe',
                    'listID': 'ISO 4217 Alpha'
                }
            }
        return template_data['DocumentCurrencyCode']

    @api.model
    def build_party_structures(self, move, template_data):
        """Construye las estructuras de Supplier y Customer"""
        return {
            **self._build_supplier_party(move, template_data),
            **self._build_customer_party(move, template_data)
        }

    @api.model
    def _build_supplier_party(self, move, template_data):
        """
        Construye la estructura XML para AccountingSupplierParty
        con todas las condiciones necesarias según UBL 2.1
        """
        party_dict = {
            'cac:AccountingSupplierParty': {
                'cbc:AdditionalAccountID': {
                    '_value': template_data['SupplierAdditionalAccountID'],
                    '_attributes': {'schemeAgencyID': '195'}
                },
                'cac:Party': {
                    'cac:PartyName': {
                        'cbc:Name': template_data['SupplierPartyName']
                    }
                }
            }
        }
        
        party = party_dict['cac:AccountingSupplierParty']['cac:Party']
        
        address = {}
        address['cbc:ID'] = template_data.get('SupplierCityCode')
        address['cbc:CityName'] = template_data.get('SupplierCityName')
        if move.move_type in ['in_invoice','in_refund']:
            address['cbc:PostalZone'] = template_data.get('SupplierPostal', '')
        address['cbc:CountrySubentity'] = template_data.get('SupplierDepartment')
        address['cbc:CountrySubentityCode'] = template_data.get('SupplierCountrySubentityCode')
        if template_data.get('SupplierLine'):
            address['cac:AddressLine'] = {
                'cbc:Line': template_data['SupplierLine']
            }
        address['cac:Country'] = {
            'cbc:IdentificationCode': template_data['SupplierCountryCode'],
            'cbc:Name': {
                '_value': template_data['SupplierCountryName'],
                '_attributes': {'languageID': 'es'}
            }
        }
        
        party['cac:PhysicalLocation'] = {'cac:Address': address}
        
        if template_data.get('SupplierID'):
            company_attrs = {
                'schemeAgencyID': '195',
                'schemeAgencyName': 'CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)'
            }
            
            if template_data.get('SupplierSchemeIDCode') == '31':
                company_attrs.update({
                    'schemeID': template_data['SupplierschemeID'],
                    'schemeName': '31'
                })
            else:
                company_attrs['schemeName'] = template_data.get('SupplierSchemeIDCode', '')
            
            party_tax_scheme = {
                'cbc:RegistrationName': template_data['SupplierRegistrationName'],
                'cbc:CompanyID': {
                    '_value': template_data['SupplierID'],
                    '_attributes': company_attrs
                }
            }
            
            if template_data.get('SupplierTaxLevelCode'):
                party_tax_scheme['cbc:TaxLevelCode'] = {
                    '_value': template_data['SupplierTaxLevelCode'],
                    '_attributes': {'listName': '48'}
                }
            
            party_tax_scheme['cac:RegistrationAddress'] = {
                'cbc:ID': {
                    '_value': template_data.get('SupplierCityCode')
                },
                'cbc:CityName': {
                    '_value': template_data.get('SupplierCityName')
                },
                'cbc:CountrySubentity': {
                    '_value': template_data.get('SupplierDepartment')
                },
                'cbc:CountrySubentityCode': {
                    '_value': template_data.get('SupplierCountrySubentityCode')
                },
                'cac:AddressLine': {
                    'cbc:Line': {
                        '_value': template_data['SupplierLine']
                    }
                },
                'cac:Country': {
                    'cbc:IdentificationCode': {
                        '_value': template_data['SupplierCountryCode']
                    },
                    'cbc:Name': {
                        '_value': template_data['SupplierCountryName'],
                        '_attributes': {'languageID': 'es'}
                    }
                }
            }
            
            if template_data.get('SupplierTaxSchemeID'):
                party_tax_scheme['cac:TaxScheme'] = {
                    'cbc:ID': template_data['SupplierTaxSchemeID'],
                    'cbc:Name': template_data.get('SupplierTaxSchemeName', '')
                }
            
            party['cac:PartyTaxScheme'] = party_tax_scheme
            
            party_legal = {
                'cbc:RegistrationName': template_data['SupplierRegistrationName'],
                'cbc:CompanyID': {
                    '_value': template_data['SupplierID'],
                    '_attributes': company_attrs
                }
            }
            
            if template_data.get('Prefix') or template_data.get('SupplierCommercialName'):
                corp_reg = {}
                if template_data.get('Prefix'):
                    corp_reg['cbc:ID'] = template_data['Prefix']
                if template_data.get('SupplierCommercialName'):
                    corp_reg['cbc:Name'] = template_data['SupplierCommercialName']
                party_legal['cac:CorporateRegistrationScheme'] = corp_reg
            
            party['cac:PartyLegalEntity'] = party_legal
        
        contact = {}
        if template_data.get('SupplierElectronicPhone'):
            contact['cbc:Telephone'] = template_data['SupplierElectronicPhone']
        if template_data.get('SupplierElectronicMail'):
            contact['cbc:ElectronicMail'] = template_data['SupplierElectronicMail']
        
        if contact:
            party['cac:Contact'] = contact
        
        return party_dict


    @api.model
    def _build_customer_party(self, move, template_data):
        """
        Construye la estructura AccountingCustomerParty
        con manejo condicional del schemeID
        """
        def _build_party_identification():
            id_attributes = {'schemeName': template_data['SchemeNameAdquiriente']}
            if template_data.get('CustomerSchemeIDCode') == '31':
                id_attributes['schemeID'] = template_data['SchemeIDAdquiriente']
                
            return {
                'cbc:ID': {
                    '_value': template_data['IDAdquiriente'],
                    '_attributes': id_attributes
                }
            }

        customer_structure = {
            'cac:AccountingCustomerParty': {
                'cbc:AdditionalAccountID': template_data['CustomerAdditionalAccountID'],
                'cac:Party': {
                    'cac:PartyIdentification': _build_party_identification(),
                    'cac:PartyName': {
                        'cbc:Name': template_data['CustomerPartyName']
                    },
                    'cac:PhysicalLocation': {
                        'cac:Address': self._build_address_structure('Customer', template_data)
                    },
                    'cac:PartyTaxScheme': {
                        'cbc:RegistrationName': template_data['CustomerPartyName'],
                        'cbc:CompanyID': {
                            '_value': template_data['CustomerID'],
                            '_attributes': self._get_customer_company_attributes(template_data)
                        },
                        'cbc:TaxLevelCode': {
                            '_value': template_data['CustomerTaxLevelCode'],
                            '_attributes': {'listName': '48'}
                        },
                        'cac:RegistrationAddress': self._build_address_structure('Customer', template_data),
                        'cac:TaxScheme': {
                            'cbc:ID': template_data['CustomerTaxSchemeID'],
                            'cbc:Name': template_data['CustomerTaxSchemeName']
                        }
                    },
                    'cac:PartyLegalEntity': {
                        'cbc:RegistrationName': template_data['CustomerPartyName'],
                        'cbc:CompanyID': {
                            '_value': template_data['CustomerID'],
                            '_attributes': self._get_customer_company_attributes(template_data)
                        }
                    },
                    'cac:Contact': self._build_customer_contact(move, template_data),
                    'cac:Person': {
                        'cbc:FirstName': template_data['CustomerFirstname']
                    }
                }
            }
        }
        
        return customer_structure

    @api.model
    def _build_address_structure(self, prefix, data):
        """Construye la estructura de dirección"""
        from collections import OrderedDict
        address = OrderedDict()
        address['cbc:ID'] = data[f'{prefix}CityCode']
        address['cbc:CityName'] = data[f'{prefix}CityName']
        if prefix == 'Supplier' and data['CustomizationID'] in ('10', '11'):
            postal_zone_key = f'{prefix}Postal'
            if postal_zone_key in data and data[postal_zone_key]:
                address['cbc:PostalZone'] = data[postal_zone_key]
            else:
                city_code = data[f'{prefix}CityCode']
                address['cbc:PostalZone'] = f"{city_code[:2]}0000"
        address['cbc:CountrySubentity'] = data[f'{prefix}CountrySubentity']
        address['cbc:CountrySubentityCode'] = data[f'{prefix}CountrySubentityCode']
        address['cac:AddressLine'] = {
            'cbc:Line': data[f'{prefix}Line']
        }
        address['cac:Country'] = {
            'cbc:IdentificationCode': data[f'{prefix}CountryCode'],
            'cbc:Name': {
                '_value': data[f'{prefix}CountryName'],
                '_attributes': {'languageID': 'es'}
            }
        }

        return address

    @api.model
    def _get_customer_company_attributes(self, template_data):
        """Obtiene los atributos para CompanyID del cliente"""
        attributes = {
            'schemeAgencyID': '195',
            'schemeAgencyName': 'CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)',
            'schemeName': template_data['CustomerSchemeIDCode']
        }
        
        if template_data['CustomerSchemeIDCode'] == '31':
            attributes['schemeID'] = template_data['CustomerschemeID']
        
        return attributes

    @api.model
    def _build_customer_contact(self, move, template_data):
        """Construye la estructura de contacto del cliente"""
        contact = {           
        }
        
        if hasattr(move, 'partner_contact_id') and move.partner_contact_id:
            if move.partner_contact_id.name:
                contact['cbc:Name'] = move.partner_contact_id.name
            if move.partner_contact_id.phone:
                contact['cbc:Telephone'] = move.partner_contact_id.phone
            if move.partner_contact_id.phone:
                contact['cbc:ElectronicMail'] = move.partner_contact_id.email
        return contact

    @api.model
    def _get_root_structure(self, document_id):
        if hasattr(document_id, 'is_debit_note') and document_id.is_debit_note:
            doc_type = 'debit_note'
        elif document_id.move_type in ['out_refund', 'in_refund']:
            doc_type = 'credit_note'
        else:
            doc_type = 'invoice'
        root_tag = {
            'invoice': 'Invoice',
            'credit_note': 'CreditNote',
            'debit_note': 'DebitNote'
        }[doc_type]
        base_ns = f"urn:oasis:names:specification:ubl:schema:xsd:{root_tag}-2"
        schema_url = f"http://docs.oasis-open.org/ubl/os-UBL-2.1/xsd/maindoc/UBL-{root_tag}-2.1.xsd"
        if document_id.move_type in ['in_invoice', 'in_refund'] or document_id.fe_type_ei_ref == '02':
            namespaces = {
                None: base_ns,
                'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2',
                'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2',
                'ds': 'http://www.w3.org/2000/09/xmldsig#',
                'ext': 'urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2',
                'sts': 'dian:gov:co:facturaelectronica:Structures-2-1',
                'xsi': 'http://www.w3.org/2001/XMLSchema-instance',
                'xades':"http://uri.etsi.org/01903/v1.3.2#",
                'xades141':"http://uri.etsi.org/01903/v1.4.1#"
            }
        elif doc_type in ['credit_note', 'debit_note'] and document_id.move_type in ['out_refund'] or document_id.is_debit_note:
            namespaces = {
                None: base_ns,
                'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2',
                'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2',
                'ds': 'http://www.w3.org/2000/09/xmldsig#',
                'ext': 'urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2',
                'sts': 'http://www.dian.gov.co/contratos/facturaelectronica/v1/Structures',
                'xsi': 'http://www.w3.org/2001/XMLSchema-instance'
            }
            
        else:
            namespaces = {
                None: base_ns,
                'cac':"urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
                'cbc':"urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
                'ds': "http://www.w3.org/2000/09/xmldsig#",
                'ext':"urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2",
                'sts': "http://www.dian.gov.co/contratos/facturaelectronica/v1/Structures",
                'xsi': "http://www.w3.org/2001/XMLSchema-instance",
            }

        return {
            'tag': root_tag,
            'namespaces': namespaces,
            'schema_location': f'{base_ns} {schema_url}'
    }



    @api.model
    def build_payment_sections(self, move, template_data):
        """Construye todas las secciones relacionadas con pagos"""
        payment_sections = {}

        # PaymentMeans
        payment_means = {
            'cac:PaymentMeans': {
                'cbc:ID': template_data['PaymentMeansID'],
                'cbc:PaymentMeansCode': template_data['PaymentMeansCode'],
                'cbc:PaymentDueDate': template_data['PaymentDueDate'],
                'cbc:PaymentID': template_data['PaymentMeansref'],
            }
        }

        # Agregar cuenta bancaria si existe
        if move.company_id.partner_id.bank_ids:
            bank_account = move.company_id.partner_id.bank_ids[0]
            payment_means['cac:PaymentMeans'].update({
                'cac:PayeeFinancialAccount': {
                    'cbc:ID': bank_account.acc_number,
                    'cac:FinancialInstitutionBranch': {
                        'cac:FinancialInstitution': {
                            'cbc:ID': bank_account.bank_id.bic
                        }
                    }
                }
            })
        payment_sections.update(payment_means)

        # PaymentTerms
        if template_data.get('PaymentTermNote'):
            payment_sections.update({
                'cac:PaymentTerms': {
                    'cbc:Note': template_data['PaymentTermNote']
                }
            })

        # PrepaidPayment
        if template_data.get('prepaid_payments'):
            prepaid_payments = []
            for prepaid in template_data['prepaid_payments']:
                prepaid_payments.append({
                    'cac:PrepaidPayment': {
                        'cbc:ID': prepaid['id'],
                        'cbc:PaidAmount': {
                            '_value': '{:.2f}'.format(prepaid['amount']),
                            '_attributes': {'currencyID': template_data['CurrencyID']}
                        },
                        'cbc:ReceivedDate': prepaid['received_date'],
                        'cbc:PaidDate': prepaid['paid_date']
                    }
                })
            payment_sections['cac:PrepaidPayment'] = prepaid_payments

        return payment_sections

    @api.model
    def build_allowance_charges(self, move, template_data):
        """Construye las secciones de descuentos y cargos"""
        allowance_charges = {}
        
        # Descuento global
        if template_data.get('invoice_discount', 0) != 0:
            allowance_charges['cac:AllowanceCharge'] = []
            
            # Descuento
            allowance_charges['cac:AllowanceCharge'].append({
                'cbc:ID': '1',
                'cbc:ChargeIndicator': 'false',
                'cbc:AllowanceChargeReasonCode': '01',
                'cbc:AllowanceChargeReason': template_data.get('discount_reason', 'Descuento general'),
                'cbc:MultiplierFactorNumeric': template_data['discount_percentage'],
                'cbc:Amount': {
                    '_value': template_data['invoice_discount'],
                    '_attributes': {'currencyID': template_data['CurrencyID']}
                },
                'cbc:BaseAmount': {
                    '_value': template_data['discount_base_amount'],
                    '_attributes': {'currencyID': template_data['CurrencyID']}
                }
            })
        
        # Ajuste de redondeo
        if template_data.get('rounding_adjustment_data'):
            if not allowance_charges.get('cac:AllowanceCharge'):
                allowance_charges['cac:AllowanceCharge'] = []
            
            rounding_data = template_data['rounding_adjustment_data']
            allowance_charges['cac:AllowanceCharge'].append({
                'cbc:ID': rounding_data['ID'],
                'cbc:ChargeIndicator': rounding_data['ChargeIndicator'],
                'cbc:AllowanceChargeReason': rounding_data['AllowanceChargeReason'],
                'cbc:MultiplierFactorNumeric': rounding_data['MultiplierFactorNumeric'],
                'cbc:Amount': {
                    '_value': rounding_data['Amount'],
                    '_attributes': {'currencyID': rounding_data['CurrencyID']}
                },
                'cbc:BaseAmount': {
                    '_value': rounding_data['BaseAmount'],
                    '_attributes': {'currencyID': rounding_data['CurrencyID']}
                }
            })
        
        return allowance_charges

    @api.model
    def build_monetary_totals(self, document_id, data):
        # Calcular totales
        line_extension_amount = data.get('line_extension_amount', 0)
        tax_exclusive_amount = data.get('tax_exclusive_amount', 0)
        tax_inclusive_amount = data.get('tax_inclusive_amount', 0)
        allowance_amount = data.get('rounding_discount', 0)
        charge_amount =  data.get('rounding_charge', 0)
        payable_amount = data.get('payable_amount', 0)
        if document_id.is_debit_note:
            monetary_totals = {
                'cac:RequestedMonetaryTotal': {
                    'cbc:LineExtensionAmount': {
                        '_value': line_extension_amount,
                        '_attributes': {'currencyID': data.get('currency', 'COP')}
                    },
                    'cbc:TaxExclusiveAmount': {
                        '_value': tax_exclusive_amount,
                        '_attributes': {'currencyID': data.get('currency', 'COP')}
                    },
                    'cbc:TaxInclusiveAmount': {
                        '_value': tax_inclusive_amount,
                        '_attributes': {'currencyID': data.get('currency', 'COP')}
                    },
                    'cbc:AllowanceTotalAmount': {
                        '_value': allowance_amount,
                        '_attributes': {'currencyID': data.get('currency', 'COP')}
                    },
                    'cbc:ChargeTotalAmount': {
                        '_value': charge_amount,
                        '_attributes': {'currencyID': data.get('currency', 'COP')}
                    },
                    'cbc:PayableAmount': {
                        '_value': payable_amount,
                        '_attributes': {'currencyID': data.get('currency', 'COP')}
                    }
                }
            }
        else:
            monetary_totals = {
                'cac:LegalMonetaryTotal': {
                    'cbc:LineExtensionAmount': {
                        '_value': line_extension_amount,
                        '_attributes': {'currencyID': data.get('currency', 'COP')}
                    },
                    'cbc:TaxExclusiveAmount': {
                        '_value': tax_exclusive_amount,
                        '_attributes': {'currencyID': data.get('currency', 'COP')}
                    },
                    'cbc:TaxInclusiveAmount': {
                        '_value': tax_inclusive_amount,
                        '_attributes': {'currencyID': data.get('currency', 'COP')}
                    },
                    'cbc:AllowanceTotalAmount': {
                        '_value': allowance_amount,
                        '_attributes': {'currencyID': data.get('currency', 'COP')}
                    },
                    'cbc:ChargeTotalAmount': {
                        '_value': charge_amount,
                        '_attributes': {'currencyID': data.get('currency', 'COP')}
                    },
                    'cbc:PayableAmount': {
                        '_value': payable_amount,
                        '_attributes': {'currencyID': data.get('currency', 'COP')}
                    }
                }
            }
        return monetary_totals

    @api.model
    def build_tax_totals(self, document_id, data):
        """
        Construye los elementos TaxTotal y WithholdingTaxTotal para la factura electrónica.
        Utiliza los valores pre-calculados tax_total_values y ret_total_values.
        
        Args:
            document_id: ID del documento
            data: Diccionario con los datos de la factura
            
        Returns:
            dict: Estructura de impuestos según formato UBL
        """
        tax_totals = {}
        withholding_tax_totals = {}
        currency_id = data.get('currency', 'COP')

        # Procesar impuestos normales
        if data.get('tax_total_values'):
            tax_totals['cac:TaxTotal'] = []
            for tax_id, tax_data in data['tax_total_values'].items():
                tax_total = {
                    'cbc:TaxAmount': {
                        '_value': '{:.2f}'.format(float(tax_data['total'])),
                        '_attributes': {'currencyID': currency_id}
                    },
                    'cbc:RoundingAmount': {
                        '_value': '0.00',
                        '_attributes': {'currencyID': currency_id}
                    },
                    'cac:TaxSubtotal': []
                }

                for percent, info in tax_data['info'].items():
                    tax_subtotal = {
                        'cbc:TaxableAmount': {
                            '_value': '{:.2f}'.format(float(info['taxable_amount'])),
                            '_attributes': {'currencyID': currency_id}
                        },
                        'cbc:TaxAmount': {
                            '_value': '{:.2f}'.format(float(info['value'])),
                            '_attributes': {'currencyID': currency_id}
                        },
                        'cac:TaxCategory': {
                            'cbc:Percent': '{:.2f}'.format(float(percent)),
                            'cac:TaxScheme': {
                                'cbc:ID': tax_id,
                                'cbc:Name': info['technical_name']
                            }
                        }
                    }
                    tax_total['cac:TaxSubtotal'].append(tax_subtotal)

                tax_totals['cac:TaxTotal'].append(tax_total)

        # Procesar retenciones (solo para facturas normales, no notas crédito/débito)
        if data.get('ret_total_values') and not document_id.move_type == 'out_refund':
            withholding_tax_totals['cac:WithholdingTaxTotal'] = []
            for tax_id, tax_data in data['ret_total_values'].items():
                withholding_total = {
                    'cbc:TaxAmount': {
                        '_value': '{:.2f}'.format(float(tax_data['total'])),
                        '_attributes': {'currencyID': currency_id}
                    },
                    'cac:TaxSubtotal': []
                }

                for percent, info in tax_data['info'].items():
                    # Determinar formato según tipo de retención
                    value_format = '{:.2f}' if tax_id == '06' else '{:.3f}'
                    
                    tax_subtotal = {
                        'cbc:TaxableAmount': {
                            '_value': value_format.format(float(info['taxable_amount'])),
                            '_attributes': {'currencyID': currency_id}
                        },
                        'cbc:TaxAmount': {
                            '_value': value_format.format(float(info['value'])),
                            '_attributes': {'currencyID': currency_id}
                        },
                        'cac:TaxCategory': {
                            'cbc:Percent': value_format.format(float(percent)),
                            'cac:TaxScheme': {
                                'cbc:ID': tax_id,
                                'cbc:Name': info['technical_name']
                            }
                        }
                    }
                    withholding_total['cac:TaxSubtotal'].append(tax_subtotal)

                withholding_tax_totals['cac:WithholdingTaxTotal'].append(withholding_total)

        # Combinar resultados
        result = {}
        if tax_totals:
            result.update(tax_totals)
        if withholding_tax_totals:
            result.update(withholding_tax_totals)

        return result


    @api.model
    def build_document_lines(self, document_id, data):
        """
        Construye las líneas del documento según su tipo, usando los datos del diccionario data.
        Asegura que todos los valores monetarios tengan exactamente 2 decimales.
        """
        def format_amount(amount):
            """Helper para formatear montos con 2 decimales exactos"""
            return '{:.2f}'.format(float(amount))

        def get_line_tag(move_type, is_debit_note):
            if is_debit_note:
                return 'DebitNoteLine'
            elif move_type in ['out_refund', 'in_refund']:
                return 'CreditNoteLine'
            return 'InvoiceLine'

        def get_quantity_tag(move_type, is_debit_note):
            if is_debit_note:
                return 'DebitedQuantity'
            elif move_type in ['out_refund', 'in_refund']:
                return 'CreditedQuantity'
            return 'InvoicedQuantity'

        lines_data = []
        line_tag = get_line_tag(document_id.move_type, document_id.is_debit_note)
        quantity_tag = get_quantity_tag(document_id.move_type, document_id.is_debit_note)

        for invoice_line in data.get('invoice_lines', []):
            line_tree = {
                f'cac:{line_tag}': {
                    'cbc:ID': str(int(invoice_line['id'])),
                    'cbc:Note': invoice_line.get('note', ''),
                }
            }
            
            # Cantidad según tipo de documento
            if invoice_line.get('uom_product_id') and invoice_line['uom_product_id'].dian_uom_id:
                line_tree[f'cac:{line_tag}'][f'cbc:{quantity_tag}'] = {
                    '_value': format_amount(invoice_line['invoiced_quantity']),
                    '_attributes': {'unitCode': invoice_line['uom_product_id'].dian_uom_id.dian_code}
                }
            else:
                line_tree[f'cac:{line_tag}'][f'cbc:{quantity_tag}'] = {
                    '_value': format_amount(invoice_line['invoiced_quantity']),
                    '_attributes': {'unitCode': 'EA'}
                }

            # Monto de extensión de línea
            line_tree[f'cac:{line_tag}']['cbc:LineExtensionAmount'] = {
                '_value': format_amount(invoice_line['line_extension_amount']),
                '_attributes': {'currencyID': data['currency_id']}
            }

            # Período de factura para facturas entrantes
            if document_id.move_type == 'in_invoice' and not document_id.is_debit_note:
                line_tree[f'cac:{line_tag}']['cac:InvoicePeriod'] = {
                    'cbc:StartDate': str(invoice_line['invoice_start_date']),
                    'cbc:DescriptionCode': str(invoice_line['transmission_type_code']),
                    'cbc:Description': str(invoice_line['transmission_description'])
                }

            # Referencia de precios para montos cero
            if float(invoice_line['line_extension_amount']) == 0:
                line_tree[f'cac:{line_tag}']['cac:PricingReference'] = {
                    'cac:AlternativeConditionPrice': {
                        'cbc:PriceAmount': {
                            '_value': format_amount(invoice_line['line_price_reference']),
                            '_attributes': {'currencyID': data['currency_id']}
                        },
                        'cbc:PriceTypeCode': str(invoice_line['line_trade_sample_price'])
                    }
                }

            if (document_id.move_type == "out_invoice" and not document_id.is_debit_note)  or (document_id.move_type == "in_invoice" and not document_id.is_debit_note):
                if float(invoice_line['line_extension_amount']) > 0 and float(invoice_line.get('discount', 0)) > 0:
                    amount_base = float(invoice_line['line_extension_amount']) + float(invoice_line['discount'])
                    line_tree[f'cac:{line_tag}']['cac:AllowanceCharge'] = {
                        'cbc:ID': '1',
                        'cbc:ChargeIndicator': 'false',
                        'cbc:AllowanceChargeReasonCode': invoice_line.get('discount_code', '01'),
                        'cbc:AllowanceChargeReason': invoice_line.get('discount_text', 'Descuento general'),
                        'cbc:MultiplierFactorNumeric': format_amount(invoice_line.get('discount_percentage')),
                        'cbc:Amount': {
                            '_value': format_amount(invoice_line['discount']),
                            '_attributes': {'currencyID': data['currency_id']}
                        },
                        'cbc:BaseAmount': {
                            '_value': format_amount(amount_base),
                            '_attributes': {'currencyID': data['currency_id']}
                        }
                    }

                if 'tax_info' in invoice_line:
                    line_tree[f'cac:{line_tag}']['cac:TaxTotal'] = []
                    for tax_id, tax_data in invoice_line['tax_info'].items():
                        tax_total = {
                            'cbc:TaxAmount': {
                                '_value': format_amount(tax_data['total']),
                                '_attributes': {'currencyID': data['currency_id']}
                            },
                            'cbc:RoundingAmount': {
                                '_value': '0.00',
                                '_attributes': {'currencyID': data['currency_id']}
                            },
                            'cac:TaxSubtotal': []
                        }

                        for amount, info in tax_data['info'].items():
                            tax_subtotal = {
                                'cbc:TaxableAmount': {
                                    '_value': format_amount(info['taxable_amount']),
                                    '_attributes': {'currencyID': data['currency_id']}
                                },
                                'cbc:TaxAmount': {
                                    '_value': format_amount(info['value']),
                                    '_attributes': {'currencyID': data['currency_id']}
                                },
                                'cac:TaxCategory': {
                                    'cbc:Percent': format_amount(amount),
                                    'cac:TaxScheme': {
                                        'cbc:ID': tax_id,
                                        'cbc:Name': info['technical_name']
                                    }
                                }
                            }
                            tax_total['cac:TaxSubtotal'].append(tax_subtotal)
                        
                        line_tree[f'cac:{line_tag}']['cac:TaxTotal'].append(tax_total)
            else:
                if 'tax_info' in invoice_line:
                    line_tree[f'cac:{line_tag}']['cac:TaxTotal'] = []
                    for tax_id, tax_data in invoice_line['tax_info'].items():
                        tax_total = {
                            'cbc:TaxAmount': {
                                '_value': format_amount(tax_data['total']),
                                '_attributes': {'currencyID': data['currency_id']}
                            },
                            'cbc:RoundingAmount': {
                                '_value': '0.00',
                                '_attributes': {'currencyID': data['currency_id']}
                            },
                            'cac:TaxSubtotal': []
                        }

                        for amount, info in tax_data['info'].items():
                            tax_subtotal = {
                                'cbc:TaxableAmount': {
                                    '_value': format_amount(info['taxable_amount']),
                                    '_attributes': {'currencyID': data['currency_id']}
                                },
                                'cbc:TaxAmount': {
                                    '_value': format_amount(info['value']),
                                    '_attributes': {'currencyID': data['currency_id']}
                                },
                                'cac:TaxCategory': {
                                    'cbc:Percent': format_amount(amount),
                                    'cac:TaxScheme': {
                                        'cbc:ID': tax_id,
                                        'cbc:Name': info['technical_name']
                                    }
                                }
                            }
                            tax_total['cac:TaxSubtotal'].append(tax_subtotal)
                        
                        line_tree[f'cac:{line_tag}']['cac:TaxTotal'].append(tax_total)  
                if float(invoice_line['line_extension_amount']) > 0 and float(invoice_line.get('discount', 0)) > 0:
                    amount_base = float(invoice_line['line_extension_amount']) + float(invoice_line['discount'])
                    line_tree[f'cac:{line_tag}']['cac:AllowanceCharge'] = {
                        'cbc:ID': '1',
                        'cbc:ChargeIndicator': 'false',
                        'cbc:AllowanceChargeReasonCode': invoice_line.get('discount_code', '01'),
                        'cbc:AllowanceChargeReason': invoice_line.get('discount_text', 'Descuento general'),
                        'cbc:MultiplierFactorNumeric': format_amount(invoice_line.get('discount_percentage')),
                        'cbc:Amount': {
                            '_value': format_amount(invoice_line['discount']),
                            '_attributes': {'currencyID': data['currency_id']}
                        },
                        'cbc:BaseAmount': {
                            '_value': format_amount(amount_base),
                            '_attributes': {'currencyID': data['currency_id']}
                        }
                    }                  
            line_tree[f'cac:{line_tag}']['cac:Item'] = {
                'cbc:Description': invoice_line['item_description'],
                'cac:SellersItemIdentification': {
                    'cbc:ID': str(invoice_line['product_id'].default_code)
                },
                'cac:StandardItemIdentification': {
                    'cbc:ID': {
                        '_value': str(invoice_line['StandardItemIdentificationID']),
                        '_attributes': {
                            'schemeID': str(invoice_line['StandardItemIdentificationschemeID']),
                            'schemeAgencyID': str(invoice_line['StandardItemIdentificationschemeAgencyID']),
                            'schemeName': str(invoice_line['StandardItemIdentificationschemeName'])
                        }
                    }
                }
            }

            # Precio
            price_tree = {
                'cbc:PriceAmount': {
                    '_value': format_amount(invoice_line['price']),
                    '_attributes': {'currencyID': data['currency_id']}
                }
            }

            if invoice_line.get('uom_product_id') and invoice_line['uom_product_id'].dian_uom_id:
                price_tree['cbc:BaseQuantity'] = {
                    '_value': format_amount(invoice_line['invoiced_quantity']),
                    '_attributes': {'unitCode': invoice_line['uom_product_id'].dian_uom_id.dian_code}
                }
            else:
                price_tree['cbc:BaseQuantity'] = {
                    '_value': format_amount(invoice_line['invoiced_quantity']),
                    '_attributes': {'unitCode': 'EA'}
                }

            line_tree[f'cac:{line_tag}']['cac:Price'] = price_tree
            lines_data.append(line_tree)

        return lines_data


    def _get_document_type(self, document_id):
        """Determina el tipo de documento"""
        if hasattr(document_id, 'is_debit_note') and document_id.is_debit_note:
            return 'debit_note'
        elif document_id.move_type in ['out_refund', 'in_refund']:
            return 'credit_note'
        return 'invoice'

    def _add_node(self, tree, path, value=None, attributes=None):
        """Agrega un nodo a la estructura del árbol"""
        current = tree
        parts = path.split('.')
        
        # Navegar/crear la estructura
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]
            
        # Agregar el nodo final
        if attributes:
            current[parts[-1]] = {'_value': value, '_attributes': attributes}
        else:
            current[parts[-1]] = value if value is not None else {}


    def generate_xml(self, document_id, data):
        """
            Genera documento electrónico XML bajo especificaciones UBL 2.1 y Anexo Técnico DIAN.
            Proceso de construcción secuencial UBL:
            1. Root Configuration:
            - Namespace binding (UBL-2.1, CBC, CAC, EXT, XSI)
            - Schema location mapping
            - Root tag según tipo documento (Invoice|CreditNote|DebitNote)
            
            2. UBL Structure Generation [Anexo Técnico v1.9]:
            a) UBLExtensions [ext:UBLExtension]
                - DianExtensions
                - SoftwareSecurityCode
                - QR Data
                - DocumentMetadata
            b) DocumentHeader
                - UBLVersionID (2.1)
                - CustomizationID
                - ProfileID/ExecutionID
                - UUID (CUFE/CUDE)
                - IssueDate/Time
                - DocumentType/Notes
            c) PartyStructures
                - AccountingSupplierParty
                - AccountingCustomerParty
                - TaxRepresentativeParty
            d) Complementary Data
                - DeliveryTerms
                - PaymentMeans/Exchange
                - PrepaidPayment
            e) Financial Totals
                - AllowanceCharges
                - TaxTotal/Subtotal
                - WithholdingTaxTotal
                - LegalMonetaryTotal
            f) InvoiceLines/DocumentLines
                - Sequential line processing
                - Line-level taxes/charges
                - Item identification
            Params:
                document_id: active_model record (account.move)
                data (dict): Preprocessed UBL data mapping
                            { ELEMENTOS }
            
            """
        try:
            root_structure = self._get_root_structure(document_id)
            
            root = etree.Element(
                root_structure['tag'], 
                nsmap=root_structure['namespaces']
            )
            root.set(
                '{http://www.w3.org/2001/XMLSchema-instance}schemaLocation',
                root_structure['schema_location']
            )
            tree = {}
            tree.update(self.build_ubl_extensions(document_id, data, {}))
            tree.update(self.build_header(document_id, data))
            tree.update(self.build_party_structures(document_id, data))
            if data.get('DeliveryData'):
                tree.update(self.build_delivery(document_id, data))
            tree.update(self.build_payment_sections(document_id, data))
            if hasattr(document_id, 'prepaid_payments_ids') and document_id.prepaid_payments_ids:
                tree.update(self.build_prepaid_payments(document_id, data))
            charges = self.build_allowance_charges(document_id, data)
            if charges:
                tree.update(charges)
            tree.update(self.build_tax_totals(document_id, data))
            tree.update(self.build_monetary_totals(document_id, data))
            lines = self.build_document_lines(document_id, data)
            for line in lines:
                for key, value in line.items():
                    if key in tree:
                        if not isinstance(tree[key], list):
                            tree[key] = [tree[key]]
                        tree[key].append(value)
                    else:
                        tree[key] = value
            self._build_xml_tree(root, tree)
            return self._clean_and_format_xml(root)
        except Exception as e:
            _logger.error(f"Error generando XML DIAN: {str(e)}")
            raise
                


    def _build_xml_tree(self, parent, structure):
        if structure is None:
            return

        for key, value in structure.items():
            if isinstance(value, dict):
                if '_value' in value:
                    # Asegurar que el valor sea una cadena
                    val = value.get('_value', '')
                    if isinstance(val, bool):
                        val = str(val).lower()  # Convert True/False to 'true'/'false'
                    elif val is not None:
                        val = str(val)
                    
                    element = self._create_element(parent, key, val)
                    if '_attributes' in value:
                        for attr_key, attr_value in value['_attributes'].items():
                            # Convertir atributos a string
                            element.set(attr_key, str(attr_value))
                else:
                    element = self._create_element(parent, key)
                    self._build_xml_tree(element, value)
            elif isinstance(value, list):
                for item in value:
                    element = self._create_element(parent, key)
                    if isinstance(item, dict):
                        self._build_xml_tree(element, item)
                    else:
                        # Convertir elemento de lista a string
                        if isinstance(item, bool):
                            element.text = str(item).lower()
                        else:
                            element.text = str(item) if item is not None else ''
            else:
                # Convertir valor a string antes de crear el elemento
                if isinstance(value, bool):
                    text_value = str(value).lower()
                else:
                    text_value = str(value) if value is not None else ''
                
                element = self._create_element(parent, key, text_value)

    def _add_lines_to_xml(self, root, lines_data):
        for line_data in lines_data:
            self._build_xml_tree(root, line_data)

    def _create_element(self, parent, tag, text=None):
        if ':' in tag:
            prefix, tag_name = tag.split(':')
            nsmap = {prefix: parent.nsmap[prefix]}
            element = etree.SubElement(parent, f'{{{parent.nsmap[prefix]}}}{tag_name}', nsmap=nsmap)
        else:
            element = etree.SubElement(parent, tag)
            
        if text is not None:
            # Asegurar que text sea siempre una cadena
            if isinstance(text, bool):
                element.text = str(text).lower()  # Convierte True/False a 'true'/'false'
            else:
                element.text = str(text)
            
        return element

    def _clean_and_format_xml(self, root):
        parser = etree.XMLParser(remove_blank_text=True, remove_comments=True)
        xml_string = etree.tostring(root, encoding='UTF-8')
        clean_root = etree.fromstring(xml_string, parser)
        # Agregar declaración XML y formatear
        return etree.tostring(
            clean_root,
            encoding='UTF-8',
            #xml_declaration=True,
            #pretty_print=True
        ).decode('UTF-8')
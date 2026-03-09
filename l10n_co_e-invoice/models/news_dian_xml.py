# -*- coding: utf-8 -*-
from odoo import _, api, fields, models, tools, Command
from cryptography.hazmat.primitives import hashes, serialization
from pytz import timezone
from odoo.exceptions import UserError,ValidationError
from odoo.tools import float_repr,cleanup_xml_node
from odoo.tools.float_utils import float_round
from collections import defaultdict
import hashlib
from lxml import etree
import xml.etree.ElementTree as ET
import re
from markupsafe import Markup
from base64 import encodebytes, b64encode
import io
import zipfile
from odoo.tools import html_escape
from . import xml_utils
from odoo.exceptions import UserError
from hashlib import sha384
import base64
import logging
import html
from random import randint
import qrcode
import json
from io import BytesIO
_logger = logging.getLogger(__name__)
COUNTRIES_ES = {
    "AF": "Afganistán",
    "AX": "Åland",
    "AL": "Albania",
    "DE": "Alemania",
    "AD": "Andorra",
    "AO": "Angola",
    "AI": "Anguila",
    "AQ": "Antártida",
    "AG": "Antigua y Barbuda",
    "SA": "Arabia Saudita",
    "DZ": "Argelia",
    "AR": "Argentina",
    "AM": "Armenia",
    "AW": "Aruba",
    "AU": "Australia",
    "AT": "Austria",
    "AZ": "Azerbaiyán",
    "BS": "Bahamas",
    "BD": "Bangladés",
    "BB": "Barbados",
    "BH": "Baréin",
    "BE": "Bélgica",
    "BZ": "Belice",
    "BJ": "Benín",
    "BM": "Bermudas",
    "BY": "Bielorrusia",
    "BO": "Bolivia",
    "BQ": "Bonaire, San Eustaquio y Saba",
    "BA": "Bosnia y Herzegovina",
    "BW": "Botsuana",
    "BR": "Brasil",
    "BN": "Brunéi",
    "BG": "Bulgaria",
    "BF": "Burkina Faso",
    "BI": "Burundi",
    "BT": "Bután",
    "CV": "Cabo Verde",
    "KH": "Camboya",
    "CM": "Camerún",
    "CA": "Canadá",
    "QA": "Catar",
    "TD": "Chad",
    "CL": "Chile",
    "CN": "China",
    "CY": "Chipre",
    "CO": "Colombia",
    "KM": "Comoras",
    "KP": "Corea del Norte",
    "KR": "Corea del Sur",
    "CI": "Costa de Marfil",
    "CR": "Costa Rica",
    "HR": "Croacia",
    "CU": "Cuba",
    "CW": "Curazao",
    "DK": "Dinamarca",
    "DM": "Dominica",
    "EC": "Ecuador",
    "EG": "Egipto",
    "SV": "El Salvador",
    "AE": "Emiratos Árabes Unidos",
    "ER": "Eritrea",
    "SK": "Eslovaquia",
    "SI": "Eslovenia",
    "ES": "España",
    "US": "Estados Unidos",
    "EE": "Estonia",
    "ET": "Etiopía",
    "PH": "Filipinas",
    "FI": "Finlandia",
    "FJ": "Fiyi",
    "FR": "Francia",
    "GA": "Gabón",
    "GM": "Gambia",
    "GE": "Georgia",
    "GH": "Ghana",
    "GI": "Gibraltar",
    "GD": "Granada",
    "GR": "Grecia",
    "GL": "Groenlandia",
    "GP": "Guadalupe",
    "GU": "Guam",
    "GT": "Guatemala",
    "GF": "Guayana Francesa",
    "GG": "Guernsey",
    "GN": "Guinea",
    "GW": "Guinea-Bisáu",
    "GQ": "Guinea Ecuatorial",
    "GY": "Guyana",
    "HT": "Haití",
    "HN": "Honduras",
    "HK": "Hong Kong",
    "HU": "Hungría",
    "IN": "India",
    "ID": "Indonesia",
    "IQ": "Irak",
    "IR": "Irán",
    "IE": "Irlanda",
    "BV": "Isla Bouvet",
    "IM": "Isla de Man",
    "CX": "Isla de Navidad",
    "IS": "Islandia",
    "KY": "Islas Caimán",
    "CC": "Islas Cocos",
    "CK": "Islas Cook",
    "FO": "Islas Feroe",
    "GS": "Islas Georgias del Sur y Sandwich del Sur",
    "HM": "Islas Heard y McDonald",
    "FK": "Islas Malvinas",
    "MP": "Islas Marianas del Norte",
    "MH": "Islas Marshall",
    "PN": "Islas Pitcairn",
    "SB": "Islas Salomón",
    "TC": "Islas Turcas y Caicos",
    "UM": "Islas ultramarinas de Estados Unidos",
    "VG": "Islas Vírgenes Británicas",
    "VI": "Islas Vírgenes de los Estados Unidos",
    "IL": "Israel",
    "IT": "Italia",
    "JM": "Jamaica",
    "JP": "Japón",
    "JE": "Jersey",
    "JO": "Jordania",
    "KZ": "Kazajistán",
    "KE": "Kenia",
    "KG": "Kirguistán",
    "KI": "Kiribati",
    "XK": "Kosovo",
    "KW": "Kuwait",
    "LA": "Laos",
    "LS": "Lesoto",
    "LV": "Letonia",
    "LB": "Líbano",
    "LR": "Liberia",
    "LY": "Libia",
    "LI": "Liechtenstein",
    "LT": "Lituania",
    "LU": "Luxemburgo",
    "MO": "Macao",
    "MK": "Macedonia",
    "MG": "Madagascar",
    "MY": "Malasia",
    "MW": "Malaui",
    "MV": "Maldivas",
    "ML": "Malí",
    "MT": "Malta",
    "MA": "Marruecos",
    "MQ": "Martinica",
    "MU": "Mauricio",
    "MR": "Mauritania",
    "YT": "Mayotte",
    "MX": "México",
    "FM": "Micronesia",
    "MD": "Moldavia",
    "MC": "Mónaco",
    "MN": "Mongolia",
    "ME": "Montenegro",
    "MS": "Montserrat",
    "MZ": "Mozambique",
    "MM": "Myanmar",
    "NA": "Namibia",
    "NR": "Nauru",
    "NP": "Nepal",
    "NI": "Nicaragua",
    "NE": "Níger",
    "NG": "Nigeria",
    "NU": "Niue",
    "NF": "Norfolk",
    "NO": "Noruega",
    "NC": "Nueva Caledonia",
    "NZ": "Nueva Zelanda",
    "OM": "Omán",
    "NL": "Países Bajos",
    "PK": "Pakistán",
    "PW": "Palaos",
    "PS": "Palestina",
    "PA": "Panamá",
    "PG": "Papúa Nueva Guinea",
    "PY": "Paraguay",
    "PE": "Perú",
    "PF": "Polinesia Francesa",
    "PL": "Polonia",
    "PT": "Portugal",
    "PR": "Puerto Rico",
    "GB": "Reino Unido",
    "EH": "República Árabe Saharaui Democrática",
    "CF": "República Centroafricana",
    "CZ": "República Checa",
    "CG": "República del Congo",
    "CD": "República Democrática del Congo",
    "DO": "República Dominicana",
    "RE": "Reunión",
    "RW": "Ruanda",
    "RO": "Rumania",
    "RU": "Rusia",
    "WS": "Samoa",
    "AS": "Samoa Americana",
    "BL": "San Bartolomé",
    "KN": "San Cristóbal y Nieves",
    "SM": "San Marino",
    "MF": "San Martín",
    "PM": "San Pedro y Miquelón",
    "VC": "San Vicente y las Granadinas",
    "SH": "Santa Elena, Ascensión y Tristán de Acuña",
    "LC": "Santa Lucía",
    "ST": "Santo Tomé y Príncipe",
    "SN": "Senegal",
    "RS": "Serbia",
    "SC": "Seychelles",
    "SL": "Sierra Leona",
    "SG": "Singapur",
    "SX": "Sint Maarten",
    "SY": "Siria",
    "SO": "Somalia",
    "LK": "Sri Lanka",
    "SZ": "Suazilandia",
    "ZA": "Sudáfrica",
    "SD": "Sudán",
    "SS": "Sudán del Sur",
    "SE": "Suecia",
    "CH": "Suiza",
    "SR": "Surinam",
    "SJ": "Svalbard y Jan Mayen",
    "TH": "Tailandia",
    "TW": "Taiwán (República de China)",
    "TZ": "Tanzania",
    "TJ": "Tayikistán",
    "IO": "Territorio Británico del Océano Índico",
    "TF": "Tierras Australes y Antárticas Francesas",
    "TL": "Timor Oriental",
    "TG": "Togo",
    "TK": "Tokelau",
    "TO": "Tonga",
    "TT": "Trinidad y Tobago",
    "TN": "Túnez",
    "TM": "Turkmenistán",
    "TR": "Turquía",
    "TV": "Tuvalu",
    "UA": "Ucrania",
    "UG": "Uganda",
    "UY": "Uruguay",
    "UZ": "Uzbekistán",
    "VU": "Vanuatu",
    "VA": "Vaticano, Ciudad del",
    "VE": "Venezuela",
    "VN": "Vietnam",
    "WF": "Wallis y Futuna",
    "YE": "Yemen",
    "DJ": "Yibuti",
    "ZM": "Zambia",
    "ZW": "Zimbabue",
}

tipo_ambiente = {
    "PRODUCCION": "1",
    "PRUEBA": "2",
}

class DianDocument(models.Model):
    _inherit = "dian.document"
    message_json = fields.Html(string="Mensaje JSON")
    message = fields.Html(compute="_compute_message")
    invoice_id = fields.Many2one(comodel_name='ir.attachment', string="XML Factura")
    response_id = fields.Many2one(comodel_name='ir.attachment', string="Respuesta DIAN")
    attachment_id = fields.Many2one(comodel_name='ir.attachment', string="Attached DIAN")
    email_state = fields.Selection([
        ('pending', 'Pendiente'),
        ('sent', 'Enviado'),
        ('failed', 'Fallido')
    ], string='Estado Email', default='pending')
    email_retry_count = fields.Integer('Intentos de Envío', default=0)
    last_email_try = fields.Datetime('Último Intento de Envío')
    email_error = fields.Text('Error de Envío')
    email_cron = fields.Boolean('Envío Por Cron')   
    def _validate_and_send_email(self, doc, values):
        """
        Valida y procesa el envío de email según el tipo de factura
        """
        doc.write(values)
        
        if self.contingency_4 or doc.move_type in ('in_invoice', 'in_refund'):
            return
        pos_installed = self.env['ir.module.module'].sudo().search([
            ('name', '=', 'point_of_sale'),
            ('state', '=', 'installed')
        ]).exists()

        if pos_installed and doc.pos_order_ids:
            # Programar envío diferido para facturas POS
            doc.write({
                'email_state': 'pending',
                'email_retry_count': 0
            })
            message = _("Factura POS: Email programado para envío diferido")
        else:
            # Envío inmediato para facturas normales
            self.env.cr.commit()
            try:
                email_sent = self.enviar_email(invoice=doc)
                if email_sent:
                    now = fields.Datetime.now()
                    doc.write({
                        'date_email_send': now,
                        'email_state': 'sent'
                    })
                    message = _("Email enviado exitosamente el %s") % now.strftime('%Y-%m-%d %H:%M:%S')
            except Exception as e:
                message = _("Error al enviar email: %s") % str(e)
                doc.write({
                    'email_state': 'failed',
                    'email_error': str(e)
                })

        # Registrar mensaje en el chatter de la factura
        doc.message_post(
            body=message,
            subject=_("Envío de Documentos Electrónicos")
        )

    @api.model
    def process_pending_emails(self):
        """
        Método para procesar emails pendientes (llamado por cron)
        """
        pending_docs = self.search([
            ('email_cron', '=', True),
            ('email_state', '=', 'pending'),
            ('email_retry_count', '<', 3)
        ])
        pos_installed = self.env['ir.module.module'].sudo().search([
                        ('name', '=', 'point_of_sale'),
                        ('state', '=', 'installed')
                    ]).exists()
                    
                   
        for doc in pending_docs:
            try:
                if pos_installed: 
                    
                    email_sent = self.enviar_email(invoice=doc.document_id)
                    now = fields.Datetime.now()
                    if email_sent:
                        message = _("Email enviado exitosamente el %s") % now.strftime('%Y-%m-%d %H:%M:%S')
                        values = {
                            'date_email_send': now,
                            'email_state': 'sent',
                            'last_email_try': now
                        }
                    else:
                        message = _("Falló el envío del email")
                        values = {
                            'email_state': 'failed',
                            'last_email_try': now,
                            'email_retry_count': self.email_retry_count + 1
                        }
                    self.write(values)
                    self.document_id.message_post(
                        body=message,
                        subject=_("Envío posterior de Documentos Electrónicos")
                    )
                    self.env.cr.commit()

            except Exception as e:
                error_message = _("Error al procesar envío posterior: %s") % str(e)
                self.write({
                    'email_state': 'failed' if self.email_retry_count >= 2 else 'pending',
                    'email_retry_count': self.email_retry_count + 1,
                    'last_email_try': fields.Datetime.now(),
                    'email_error': str(e)
                })
                self.document_id.message_post(
                    body=error_message,
                    subject=_("Error en Envío posterior")
                )
                self.env.cr.commit()
                _logger.error(error_message) 
    
    @api.depends('message_json')
    def _compute_message(self):
        for doc in self:
            if not doc.message_json:
                doc.message = Markup("<p>No hay información de mensaje disponible</p>")
                continue

            try:
                # Try to parse the HTML content as JSON
                message_data = json.loads(doc.message_json)
                
                msg = html_escape(message_data.get('status', ""))
                
                if message_data.get('errors'):
                    errors = message_data['errors']
                    if isinstance(errors, list):
                        error_list = Markup().join(
                            Markup("<li>%s</li>") % html_escape(error) for error in errors
                        )
                        msg += Markup("<ul>{errors}</ul>").format(errors=error_list)
                    elif isinstance(errors, str):
                        msg += Markup("<ul><li>%s</li></ul>") % html_escape(errors)
                    else:
                        msg += Markup("<ul><li>Error desconocido</li></ul>")
                
                doc.message = Markup(msg)
            except json.JSONDecodeError:
                # If it's not valid JSON, assume it's already HTML
                doc.message = doc.message_json

    @api.model
    def _parse_errors(self, root):
        """ Returns a list containing the errors/warnings from a DIAN response """
        return [node.text for node in root.findall(".//{*}ErrorMessage/{*}string")]

    @api.model
    def _build_message(self, root):
        msg = {'status': False, 'errors': []}
        fault = root.find('.//{*}Fault/{*}Reason/{*}Text')
        if fault is not None and fault.text:
            msg['status'] = fault.text + " (Esto podría deberse al uso de certificados incorrectos.)"
        status = root.find('.//{*}StatusDescription')
        if status is not None and status.text:
            msg['status'] = status.text
        msg['errors'] = self._parse_errors(root)
        
        # Convert the message dictionary to HTML format
        html_content = []
        if msg['status']:
            html_content.append(f"<p><strong>Estado:</strong> {html_escape(msg['status'])}</p>")
        
        if msg['errors']:
            html_content.append("<p><strong>Errores:</strong></p><ul>")
            for error in msg['errors']:
                html_content.append(f"<li>{html_escape(error)}</li>")
            html_content.append("</ul>")
            
        return Markup(''.join(html_content))

    def _action_get__xml(self,name=False,cufe=False):
        """ Fetch the status of a document sent to 'SendTestSetAsync' using the 'GetStatusZip' webservice. """
        self.ensure_one()
        if not cufe:
            cufe = self.cufe
            name = f'DIAN_invoice_.xml'
        response = xml_utils._build_and_send_request(
            self,
            payload={
                'track_id': cufe,
                'soap_body_template': "l10n_co_e-invoice.get_xml",
            },
            service="GetXmlByDocumentKey",
            company=self.document_id.company_id,
        )
        
        if response['status_code'] == 200:
            root = etree.fromstring(response['response'])
            self.message_json = self._build_message(root)
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
                attachment_vals = {
                    'name': name,
                    'type': 'binary',
                    'datas': base64.b64encode(decoded_content),
                    'res_model': self._name,
                    'res_id': self.id,
                }
                attachment = self.env['ir.attachment'].create(attachment_vals)
                self.write({'invoice_id': attachment.id, 'xml_document': decoded_content, 'state': 'exitoso', })
        elif response['status_code']:
            raise UserError(_("El servidor de la DIAN arrojó error (Codigo %s)", response['status_code']))
        else:
            raise UserError(_("El servidor DIAN no respondió."))

    def _get_qr_co(self):
        """
        """
        self.ensure_one()
        root = etree.fromstring(self.invoice_id.raw)
        nsmap = {k: v for k, v in root.nsmap.items() if k}  # empty namespace prefix is not supported for XPaths
        supplier_company_id = root.findtext('./cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID', namespaces=nsmap)
        customer_company_id = root.findtext('./cac:AccountingCustomerParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID', namespaces=nsmap)
        line_extension_amount = root.findtext('./cac:LegalMonetaryTotal/cbc:LineExtensionAmount', namespaces=nsmap)
        tax_amount_01 = sum(float(x) for x in root.xpath('./cac:TaxTotal[.//cbc:ID/text()="01"]/cbc:TaxAmount/text()', namespaces=nsmap))
        payable_amount = root.findtext('./cac:LegalMonetaryTotal/cbc:PayableAmount', namespaces=nsmap)
        identifier = root.findtext('./cbc:UUID', namespaces=nsmap)
        qr_code = root.findtext('./ext:UBLExtensions/ext:UBLExtension/ext:ExtensionContent/sts:DianExtensions/sts:QRCode', namespaces=nsmap)
        vals = {
            'NumDS': root.findtext('./cbc:ID', namespaces=nsmap),
            'FecFD': root.findtext('./cbc:IssueDate', namespaces=nsmap),
            'HorDS': root.findtext('./cbc:IssueTime', namespaces=nsmap),
        }
        if self.move_type in ('in_invoice', 'in_refund'):
            vals.update({
                'NumSNO': supplier_company_id,
                'DocABS': customer_company_id,
                'ValDS': line_extension_amount,
                'ValIva': tax_amount_01,
                'ValTolDS': payable_amount,
                'CUDS': identifier,
                'QRCode': qr_code,
            })
        else:
            vals.update({
                'NitFac': supplier_company_id,
                'DocAdq': customer_company_id,
                'ValFac': line_extension_amount,
                'ValIva': tax_amount_01,
                'ValOtroIm': sum(float(x) for x in root.xpath('./cac:TaxTotal[.//cbc:ID/text()!="01"]/cbc:TaxAmount/text()', namespaces=nsmap)),
                'ValTolFac': payable_amount,
                'CUFE': identifier,
                'QRCode': qr_code,
            })
        qr_code_text = "\n".join(f"{k}: {v}" for k, v in vals.items())
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(qr_code_text)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        # Convertir la imagen a base64
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        qr_code_image = base64.b64encode(buffered.getvalue()).decode()

        return qr_code_text, qr_code_image

    def generate_and_save_qr_code(self):
        for record in self:
            qr_code_text, qr_code_image = record._l10n_co_dian_get_invoice_report_qr_code_value()
            record.write({
                'QR_code': qr_code_image,
                'qr_data': qr_code_text,
            })

    def format_float(self, amount, precision_digits):
        if amount is None:
            return None
        return float_repr(float_round(amount, precision_digits), precision_digits)

    @api.model
    def _send_to_dian(self, xml, move):
        """ Send an xml to DIAN.
        If the Certification Process is activated, use the dedicated 'SendTestSetAsync' (asynchronous) webservice,
        otherwise, use the 'SendBillSync' (synchronous) webservice.

        """
        # Zip the xml
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as zipfile_obj:
            for att in [{'name': 'invoice.xml', 'content': xml}]:
                zipfile_obj.writestr(att['name'], att['content'])
        zipped_content = buffer.getvalue()

        if not move.company_id.production:
            document_vals = self._send_test_set_async(zipped_content, move)
        else:
            document_vals = self._send_bill_sync(zipped_content, move)
        return {'xml': xml, 'move': move, **document_vals}



    @api.model
    def _send_test_set_async(self, zipped_content, move):
        """ Send the document to the 'SendTestSetAsync' (asynchronous) webservice.
        NB: later, need to fetch the result by calling the 'GetStatusZip' webservice.
        """
        response = xml_utils._build_and_send_request(
            self,
            payload={
                'file_name': "invoice.zip",
                'content_file': b64encode(zipped_content).decode(),
                'test_set_id': self._get_identificador_set_pruebas(),
                'soap_body_template': "l10n_co_e-invoice.send_test_set_async",
            },
            service="SendTestSetAsync",
            company=move.company_id,
        )
        if not response['response']:
            return {
                'state': 'por_validar',
                'message_json': {'status': _("The DIAN server did not respond.")},**response
            }
        root = etree.fromstring(response['response'])
        if response['status_code'] != 200:
            return {
                'state': 'por_validar',
                'message_json': self._build_message(root),**response
            }
        zip_key = root.findtext('.//{*}ZipKey')
        if zip_key:
            return {
                'state': 'por_validar',
                'message_json': {'status': _("Invoice is being processed by the DIAN.")},
                'ZipKey': zip_key,**response
            }
        return {
            'state': 'exitoso',
            'message_json': {'errors': [node.text for node in root.findall('.//{*}ProcessedMessage')]},**response
        }

    @api.model
    def _send_bill_sync(self, zipped_content, move):
        """ Send the document to the 'SendBillSync' (synchronous) webservice. """
        response = xml_utils._build_and_send_request(
            self,
            payload={
                'file_name': "invoice.zip",
                'content_file': b64encode(zipped_content).decode(),
                'soap_body_template': "l10n_co_e-invoice.send_bill_sync",
            },
            service="SendBillSync",
            company=move.company_id,
        )
        if not response['response']:
            return {
                'state': 'por_validar',
                'message_json': {'status': _("The DIAN server did not respond.")},**response
            }
        root = etree.fromstring(response['response'])
        if response['status_code'] != 200:
            return {
                'state': 'por_validar',
                'message_json': self._build_message(root),**response
            }
        return {
            'state': 'exitoso' if root.findtext('.//{*}IsValid') == 'true' else 'rechazado',
            'message_json': self._build_message(root),**response
        }


    def _get_status_zip(self):
        """ Fetch the status of a document sent to 'SendTestSetAsync' using the 'GetStatusZip' webservice. """
        self.ensure_one()
        response = xml_utils._build_and_send_request(
            self,
            payload={
                'track_id': self.ZipKey,
                'soap_body_template': "l10n_co_e-invoice.get_status_zip",
            },
            service="GetStatusZip",
            company=self.document_id.company_id,
        )
        if response['status_code'] == 200:
            root = etree.fromstring(response['response'])
            self.message_json = self._build_message(root)
            if root.findtext('.//{*}IsValid') == 'true':
                self.state = 'exitoso'
            elif not root.findtext('.//{*}StatusCode'):
                self.state = 'por_validar'
            else:
                self.state = 'rechazado'
        elif response['status_code']:
            raise UserError(_("The DIAN server returned an error (code %s)", response['status_code']))
        else:
            raise UserError(_("The DIAN server did not respond."))

    def _get_status(self):
        return xml_utils._build_and_send_request(
            self,
            payload={
                'track_id': self.cufe,
                'soap_body_template': "l10n_co_e-invoice.get_status",
            },
            service="GetStatus",
            company=self.document_id.company_id,
        )
    def action_get_status_zip(self):
        for doc in self:
            doc._get_status_zip()

    def action_get_status(self):
        for doc in self:
            doc._get_status()
# -*- coding: utf-8 -*-
import datetime
from datetime import timedelta, date
import hashlib
import logging
import pyqrcode
import zipfile
import pytz
import json
from unidecode import unidecode
from collections import defaultdict
from contextlib import contextmanager
from functools import lru_cache
from odoo import api, fields, models, Command, _
import base64
from odoo.tools.misc import formatLang, format_date, get_lang, groupby
from odoo.exceptions import AccessError, UserError, RedirectWarning, ValidationError
from lxml import etree
from io import BytesIO
from xml.sax import saxutils
import xml.etree.ElementTree as ET
import html
_logger = logging.getLogger(__name__)
urllib3_logger = logging.getLogger('urllib3')
urllib3_logger.setLevel(logging.ERROR)
from . import global_functions
from pytz import timezone
from requests import post, exceptions
from lxml import etree
from odoo import models, fields, _, api
import logging
_logger = logging.getLogger(__name__)
import unicodedata
from odoo.tools.image import image_data_uri
import ssl
from html2text import html2text
import logging

from decimal import Decimal, ROUND_HALF_UP
from odoo.tools import convert_file, html2plaintext, is_html_empty
ssl._create_default_https_context = ssl._create_unverified_context
DIAN = {'wsdl-hab': 'https://vpfe-hab.dian.gov.co/WcfDianCustomerServices.svc?wsdl',
        'wsdl': 'https://vpfe.dian.gov.co/WcfDianCustomerServices.svc?wsdl',
        'catalogo-hab': 'https://catalogo-vpfe-hab.dian.gov.co/Document/FindDocument?documentKey={}&partitionKey={}&emissionDate={}',
        'catalogo': 'https://catalogo-vpfe.dian.gov.co/Document/FindDocument?documentKey={}&partitionKey={}&emissionDate={}'}

TYPE_DOC_NAME = {
    'invoice': _('Invoice'),
    'credit': _('Credit Note'),
    'debit': _('Debit Note')
}

EDI_OPERATION_TYPE = [
    ('10', 'Estandar'),
    ('09', 'AIU'),
    ('11', 'Mandatos'),
]
from . import xml_utils
from lxml import etree
from lxml.etree import CDATA
from markupsafe import Markup

from base64 import b64encode, b64decode
import io
import zipfile

from odoo import models, fields, api, _
from odoo.tools import html_escape, cleanup_xml_node
from odoo.exceptions import UserError
EVENT_CODES = [
    ('02', '[02] Documento validado por la DIAN'),
    ('04', '[03] Documento rechazado por la DIAN'),
    ('030', '[030] Acuse de recibo'),
    ('031', '[031] Reclamo'),
    ('032', '[032] Recibo del bien'),
    ('033', '[033] Aceptación expresa'),
    ('034', '[034] Aceptación Tácita'),
    ('other', 'Otro')
]


class Invoice(models.Model):
    _inherit = "account.move"

          
    fecha_envio = fields.Datetime(string='Fecha de envío en UTC',copy=False)
    fecha_entrega = fields.Datetime(string='Fecha de entrega',copy=False)
    fecha_xml = fields.Datetime(string='Fecha de factura Publicada',copy=False)
    total_withholding_amount = fields.Float(string='Total de retenciones')
    invoice_trade_sample = fields.Boolean(string='Tiene muestras comerciales',)
    receipt = fields.Boolean(string='Tiene ordenes de entrega?',)
    trade_sample_price = fields.Selection([('01', 'Valor comercial')],   string='Referencia a precio real',  )
    application_response_ids = fields.One2many('dian.application.response','move_id')
    get_status_event_status_code = fields.Selection([('00', 'Procesado Correctamente'),
                                                   ('66', 'NSU no encontrado'),
                                                   ('90', 'TrackId no encontrado'),
                                                   ('99', 'Validaciones contienen errores en campos mandatorios'),
                                                   ('other', 'Other')], string='StatusCode', default=False)
    get_status_event_response = fields.Text(string='Response')
    response_message_dian = fields.Text(string='Response Dian')
    response_eve_dian = fields.Text(string='Response Dian')
    message_error_DIAN_event = fields.Text(string='Response Dian error')
    receipts = fields.One2many("receipt.code","move_id", string="Codigo de entrega")
    titulo_state = fields.Selection([
        ('grey', 'No Titulo Valor'),
        ('red', 'Proceso'),
        ('green', 'Titulo Valor')], string='Titulo Valor', default='grey')

    fe_type = fields.Selection(
        [('01', 'Factura de venta'),
         ('02', 'Factura de exportación'),
         ('03', 'Documento electrónico de transmisión - tipo 03'),
         ('04', 'Factura electrónica de Venta - tipo 04'), 
         ],
        'Tipo De Factura Electronica',
        required=False,
        default='01',
        readonly=True,
    )
    fe_type_ei_ref = fields.Selection(
        [('01', 'Factura de venta'),
         ('02', 'Factura de exportación'),
        # ('03', 'Documento electrónico de transmisión - tipo 03'),
         #('04', 'Factura electrónica de Venta - tipo 04'),
         ('91', 'Nota Crédito'),
         ('92', 'Nota Débito'),
         ('96', 'Eventos (ApplicationResponse)'), ],
        'Tipo de Documento Electronico',
        required=False,
        readonly=True,
        compute='_type_ei_default',
        
    )
    fe_operation_type = fields.Selection(EDI_OPERATION_TYPE,
                                         'Tipo de Operacion',
                                         default='10',
                                         required=True)
    supplier_claim_concept = fields.Selection(
        [
            ('01', 'Documento con inconsistencias'),
            ('02', 'Mercancia no entregada totalmente'),
            ('03', 'Mercancia no entregada parcialmente'),
            ('04', 'Servicio no prestado'),
        ],
        string="Concepto de Reclamo", tracking=True)
    zip_file = fields.Binary('Archivo Zip')
    zip_file_name = fields.Char('File name')
    xml_text = fields.Text('Contenido XML')
    invoice_xml = fields.Text('Factura XML')
    credit_note_count = fields.Integer('# NC', compute='_compute_credit_count')

    def send_dian_document_new(self):
        """
        Método principal para enviar documentos a DIAN
        Returns:
            bool: True si el proceso fue exitoso
        """
        for rec in self:
            document_dian = rec.diancode_id
            if not document_dian and rec.state == "posted":
                vals = {
                    "document_id": rec.id,
                    "document_type": rec._get_document_type()
                }
                document_dian = self.env["dian.document"].sudo().create(vals)
                rec.diancode_id = document_dian.id
            if document_dian:
                document_type = document_dian.document_type
                document_dian.with_context(
                    active_id=rec.id,
                    active_model=rec._name
                ).send_pending_dian(document_dian, document_type=document_type, invoice=rec)
        return True

    def _get_document_type(self):
        """
        Determina el tipo de documento DIAN
        Returns:
            str: Tipo de documento (f: factura, c: nota crédito, d: nota débito)
        """
        self.ensure_one()
        if self.move_type in ("out_invoice", "in_invoice"):
            if self.debit_origin_id:
                return "d" 
            return "f" 
        elif self.move_type in ("out_refund", "in_refund"):
            return "c" 
        return False

    def _get_last_sequence_domain(self, relaxed=False):
        where_string, param = super()._get_last_sequence_domain(relaxed)
        if self.journal_id.debit_note_sequence:
            where_string += " AND debit_origin_id IS " + ("NOT NULL" if self.debit_origin_id else "NULL")
        return where_string, param
    
    def _get_starting_sequence(self):
        """EXTENDS account sequence.mixin"""
        self.ensure_one()
        sequence_id = self.journal_id.sequence_id
        if sequence_id.use_dian_control:
            prefix = self.journal_id.code
            if self.journal_id.refund_sequence and self.move_type in ('out_refund', 'in_refund'):
                prefix = "R" + prefix
            elif (self.journal_id.debit_note_sequence 
                and self.debit_origin_id 
                and self.move_type in ("in_invoice", "out_invoice")):
                prefix = "D" + prefix
            elif self.journal_id.payment_sequence and self.payment_id:
                prefix = "P" + prefix
                
            return prefix + "00000"
        if self.journal_id.type in ['sale', 'bank', 'cash']:
            starting_sequence = "%s/%04d/00000" % (self.journal_id.code, self.date.year)
        else:
            starting_sequence = "%s/%04d/%02d/0000" % (
                self.journal_id.code, 
                self.date.year, 
                self.date.month
            )
        if self.journal_id.refund_sequence and self.move_type in ('out_refund', 'in_refund'):
            starting_sequence = "R" + starting_sequence
        elif (self.journal_id.debit_note_sequence 
            and self.debit_origin_id 
            and self.move_type in ("in_invoice", "out_invoice")):
            starting_sequence = "D" + starting_sequence
        elif self.journal_id.payment_sequence and self.payment_id:
            starting_sequence = "P" + starting_sequence
        return starting_sequence

    def _get_einv_warning(self):
        warn_remaining = False
        inactive_resolution = False
        sequence_id = self.journal_id.sequence_id

        if sequence_id.use_dian_control:
            remaining_numbers = max(5,sequence_id.remaining_numbers)
            remaining_days = max(5,sequence_id.remaining_days)
            date_range = self.env['ir.sequence.dian_resolution'].search(
                [('sequence_id', '=', sequence_id.id),
                 ('active_resolution', '=', True)])
            today = datetime.datetime.strptime(
                str(fields.Date.today(self)),
                '%Y-%m-%d'
            )
            if date_range:
                date_range.ensure_one()
                date_to = datetime.datetime.strptime(
                    str(date_range.date_to),
                    '%Y-%m-%d'
                )
                days = (date_to - today).days
                numbers = date_range.number_to - self.sequence_number
                if numbers < remaining_numbers or days < remaining_days:
                    warn_remaining = True
            else:
                inactive_resolution = True
        self.is_inactive_resolution = inactive_resolution
        self.fe_warning = warn_remaining

    fe_warning = fields.Boolean('¿Advertir por rangos de resolución?',
                                compute='_get_einv_warning',
                                store=False)
    is_inactive_resolution = fields.Boolean('¿Advertir resolución inactiva?',
                                            compute='_get_einv_warning',
                                            store=False)

    last_event_status = fields.Char(string="Último evento exitoso", compute="_compute_last_event_status")

    @api.depends('application_response_ids.status', 'application_response_ids.response_code')
    def _compute_last_event_status(self):
        for record in self:
            last_successful_event = record.application_response_ids.filtered(lambda r: r.status == 'exitoso').sorted(key=lambda r: r.create_date, reverse=True)
            record.last_event_status = last_successful_event[0].response_code if last_successful_event else False

    @api.depends('reversal_move_id')
    def _compute_credit_count(self):
        credit_data = self.env['account.move'].read_group(
            [('reversed_entry_id', 'in', self.ids)],
            ['reversed_entry_id'],
            ['reversed_entry_id']
        )
        data_map = {
            datum['reversed_entry_id'][0]:
            datum['reversed_entry_id_count'] for datum in credit_data
        }
        for inv in self:
            inv.credit_note_count = data_map.get(inv.id, 0.0)

    def action_view_credit_notes(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Credit Notes'),
            'res_model': 'account.move',
            'view_mode': 'tree,form',
            'domain': [('reversed_entry_id', '=', self.id)],
        }

    @api.depends('move_type','partner_id')
    def _type_ei_default(self):
        for rec in self:
            if rec.move_type in ('out_invoice','in_invoice') and not rec.is_debit_note:
                rec.fe_type_ei_ref = '01'
            elif rec.move_type in ('out_invoice','in_invoice') and rec.is_debit_note:
                rec.fe_type_ei_ref =  '92'
            elif rec.move_type in ('out_refund','in_refund'):
                rec.fe_type_ei_ref =  '91'  
            else:
                rec.fe_type_ei_ref =  '01'
    
    def validate_event(self):
        sql = """SELECT am.id 
                FROM account_move am
                WHERE am.titulo_state != 'green' 
                    AND am.move_type = 'out_invoice'
                    AND am.state = 'posted';"""
        self.env.cr.execute(sql)
        sql_result = self.env.cr.dictfetchall()

        # Crear lotes de 40 registros cada uno
        batch_size = 40
        for i in range(0, len(sql_result), batch_size):
            batch = sql_result[i:i + batch_size]
            inv_to_validate_dian = (
                self.env["account.move"].sudo().browse([n.get("id") for n in batch])
            )

            # Procesar cada registro en el lote
            for idian in inv_to_validate_dian:
                try:
                    # Creando un punto de guardado
                    with self.env.cr.savepoint():
                        idian.action_GetStatusevent()
                except Exception as e:
                    _logger.info(f"Error procesando el registro {idian.name}: {e}")


    def _get_status(self):
        return xml_utils._build_and_send_request(
            self,
            payload={
                'track_id': self.cufe,
                'soap_body_template': "l10n_co_e-invoice.get_status",
            },
            service="GetStatus",
            company=self.company_id,
        )

    def _get_attached_document_values(self, original_xml_etree, application_response_etree):
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
                'scheme_name': str(scheme_mapping.get(self.move_type, "CUFE-SHA384")),
            },
            'issue_date': original_xml_etree.findtext('./{*}IssueDate'),
            'issue_time': original_xml_etree.findtext('./{*}IssueTime'),
            'document_type': "Contenedor de Factura Electrónica",
            'parent_document_id': original_xml_etree.findtext('./{*}ID'),
            'parent_document': {
                'id': original_xml_etree.findtext('./{*}ID'),
                'uuid': self.cufe,
                'uuid_attrs': {
                    'scheme_name': str(scheme_mapping.get(self.move_type, "CUFE-SHA384")),
                },
                'issue_date': application_response_etree.findtext('./{*}IssueDate'),
                'issue_time': application_response_etree.findtext('./{*}IssueTime'),
                'response_code': application_response_etree.findtext('.//{*}Response/{*}ResponseCode'),
                'validation_date': application_response_etree.findtext('./{*}IssueDate'),
                'validation_time': application_response_etree.findtext('./{*}IssueTime'),
            },
        }

    def _get_attached_document(self):
        """ Return a tuple: (the attached document xml, an error message) """
        self.ensure_one()

        # call to GetStatus to get the ApplicationResponse
        status_response = self._get_status()
        if status_response['status_code'] != 200:
            return "", _(
                "Error %(code)s when calling the DIAN server: %(response)s",
                code=status_response['status_code'],
                response=status_response['response'],
            )
        status_etree = etree.fromstring(status_response['response'])
        application_response = b64decode(status_etree.findtext(".//{*}XmlBase64Bytes"))
        original_xml_etree = etree.fromstring(self.diancode_id.invoice_id.raw)

        # render the Attached Document
        vals = self._get_attached_document_values(
            original_xml_etree=original_xml_etree,
            application_response_etree=etree.fromstring(application_response),
        )
        attached_document = self.env['ir.qweb']._render('l10n_co_e-invoice.attached_document_template', vals)
        attached_doc_etree = etree.fromstring(attached_document)

        # copy the Sender and Receiver from the original xml
        supplier_node = original_xml_etree.find('./{*}AccountingSupplierParty//{*}PartyTaxScheme')
        customer_node = original_xml_etree.find('./{*}AccountingCustomerParty//{*}PartyTaxScheme')
        attached_doc_etree.find('./{*}SenderParty').append(supplier_node)
        attached_doc_etree.find('./{*}ReceiverParty').append(customer_node)

        # Add the xmls (enclosed in CDATA)
        attached_doc_etree.find('./{*}Attachment/{*}ExternalReference/{*}Description').text = CDATA(self.diancode_id.invoice_id.raw.decode())
        attached_doc_etree.find('./{*}ParentDocumentLineReference//{*}Description').text = CDATA(application_response.decode())

        return etree.tostring(cleanup_xml_node(attached_doc_etree), encoding="UTF-8", xml_declaration=True), ""

    def action_get_attached_document(self):
        self.ensure_one()
        attached_document, error = self._get_attached_document()
        if error:
            raise UserError(error)
        attachment = self.env['ir.attachment'].create({
            'raw': attached_document,
            'name': self.name + '_manual.xml',
            'res_model': 'account.move',
            'res_id': self.id,
        })
        return attachment



    def action_send_and_print(self):
        self.ensure_one()
        
        if any(not x.is_sale_document(include_receipts=True) for x in self):
            raise UserError(_("You can only send sales documents"))
        
        template = self.env.ref('l10n_co_e-invoice.email_template_edi_invoice_dian', raise_if_not_found=False)
        
        xml_document, error = self._get_attached_document()
        if error:
            raise UserError(error)
            
        name_xml = self.diancode_id.xml_file_name
        zip_file_name = name_xml.split(".")[0]
        pdf_file_name = f"{zip_file_name}.pdf"
        
        with BytesIO() as zip_buffer:
            with zipfile.ZipFile(zip_buffer, 'a', zipfile.ZIP_DEFLATED) as zip_file:
                # Agregar XML al ZIP
                zip_file.writestr(name_xml, xml_document)
                
                # Generar y agregar PDF al ZIP
                pdf_content = self.env['ir.actions.report'].sudo()._render_qweb_pdf("account.account_invoices", self.id)[0]
                zip_file.writestr(pdf_file_name, pdf_content)
                
            # Obtener contenido del ZIP
            zip_content = zip_buffer.getvalue()
        
        zip_base64 = base64.b64encode(zip_content).decode()
        
        # Crear adjunto
        attachment_data = {
            "res_id": self.id,
            "res_model": "account.move",
            "type": "binary",
            "name": f"{zip_file_name}.zip",
            "datas": zip_base64,
        }
        
        # Actualizar adjuntos en la plantilla
        if template:
            template.sudo().write({
                'attachment_ids': [(5, 0, 0), (0, 0, attachment_data)]
            })
        
        # Crear registro del documento XML
        self.env['ir.attachment'].create({
            'raw': xml_document,
            'name': f'{self.name}_manual.xml',
            'res_model': 'account.move',
            'res_id': self.id,
        })
        
        # Retornar acción para enviar correo
        return {
            'name': _("Send"),
            'type': 'ir.actions.act_window',
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': 'account.move.send',
            'target': 'new',
            'context': {
                'active_ids': self.ids,
                'default_mail_template_id': template and template.id or False,
            },
        }


    def action_invoice_sent_2(self):
        if self.company_id.production:
            for rec in self:
                dian_constants = rec.diancode_id._get_dian_constants(rec)
                response = rec.diancode_id.xml_response_dian
                
                try:
                    root = ET.fromstring(response)
                    if root.tag == '{http://www.w3.org/2003/05/soap-envelope}Envelope':
                        xml, name_xml = rec.diancode_id.enviar_email_attached_document_xml(
                            response,
                            dian_document=rec.diancode_id,
                            dian_constants=dian_constants,
                            data_header_doc=rec,
                        )
                    else:
                        raise ValueError("XML structure is not as expected")
                except (ET.ParseError, ValueError):
                    response_attachment = rec.diancode_id.response_id
                    if not response_attachment:
                        raise UserError(_("No valid DIAN response found. Please verify the invoice status."))
                    
                    response_xml_escaped = base64.b64decode(response_attachment.datas).decode('UTF-8')
                    response_xml = html.unescape(response_xml_escaped)
                    response_root = ET.fromstring(response_xml.encode('UTF-8'))
                    response = ET.tostring(response_root, encoding='UTF-8').decode('UTF-8')
                    _logger.error(response)
                    xml, name_xml = rec.diancode_id.enviar_email_attached_document_fe_xml(
                        response,
                        dian_document=rec.diancode_id,
                        dian_constants=dian_constants,
                        data_header_doc=rec,
                    )

                zip_file_name = name_xml.split(".")[0]
                
                with BytesIO() as zip_buffer:
                    with zipfile.ZipFile(zip_buffer, 'a', zipfile.ZIP_DEFLATED) as zip_file:
                        zip_file.writestr(name_xml, xml)
                        pdf_file_name = zip_file_name + ".pdf"
                        pdf_content = self.env['ir.actions.report'].sudo()._render_qweb_pdf("account.account_invoices", rec.id)[0]
                        zip_file.writestr(pdf_file_name, pdf_content)
                    
                    zip_content = zip_buffer.getvalue()
                
                zip_base64 = base64.b64encode(zip_content).decode()
                template = self.env.ref('l10n_co_e-invoice.email_template_edi_invoice_dian', raise_if_not_found=False)
                lang = self.env.lang
                if template and template.lang:
                    lang = template._render_template(template.lang, 'account.move', rec.ids)
                
                compose_form = self.env.ref('account.account_invoice_send_wizard_form', raise_if_not_found=False)
                ctx = dict(
                    default_model='account.move',
                    default_res_id=rec.id,
                    default_res_model='account.move',
                    default_use_template=bool(template),
                    default_template_id=template and template.id or False,
                    default_composition_mode='comment',
                    mark_invoice_as_sent=True,
                    default_email_layout_xmlid="mail.mail_notification_layout_with_responsible_signature",
                    model_description=rec.with_context(lang=lang).type_name,
                    force_email=True,
                    active_ids=rec.ids,
                )
                
                dict_adjunto = {
                    "res_id": rec.id,
                    "res_model": "account.move",
                    "type": "binary",
                    "name": zip_file_name + ".zip",
                    "datas": zip_base64,
                }
                if template:
                    template.sudo().attachment_ids = [(5, 0, [])]
                    template.sudo().attachment_ids = [(0, 0, dict_adjunto)]
                return {
                    'name': _('Send Invoice'),
                    'type': 'ir.actions.act_window',
                    'view_type': 'form',
                    'view_mode': 'form',
                    'res_model': 'account.invoice.send',
                    'views': [(compose_form.id, 'form')],
                    'view_id': compose_form.id,
                    'target': 'new',
                    'context': ctx,
                }
        else:
            return super(Invoice, self).action_invoice_sent()
   
   
    
    def dian_preview(self):
        for rec in self:
            if rec.cufe:
                return {
                    'type': 'ir.actions.act_url',
                    'target': 'new',
                    'url': 'https://catalogo-vpfe.dian.gov.co/document/searchqr?documentkey=' + rec.cufe,
                }

    def dian_pdf_view(self):
        for rec in self:
            if rec.cufe:
                return {
                    'type': 'ir.actions.act_url',
                    'target': 'new',
                    'url': 'https://catalogo-vpfe.dian.gov.co/Document/DownloadPDF?trackId=' + rec.cufe,
                }

    def action_open_dian_page(self):
        self.ensure_one()
        base_url = self.env['ir.config_parameter'].sudo().get_param('dian.verification_page_url', 'https://catalogo-vpfe.dian.gov.co/document/searchqr')
        if not base_url:
            self.env['ir.config_parameter'].sudo().set_param('dian.verification_page_url', 'https://catalogo-vpfe.dian.gov.co/document/searchqr')
        return {
            'type': 'ir.actions.act_url',
            'url': f"{base_url}?documentkey={self.cufe_cuds_other_system}",
            'target': 'new',
        }

    @api.depends('application_response_ids')
    def _compute_titulo_state(self):
        kanban_state = 'grey'
        for rec in self:
            for event in rec.application_response_ids:
                if event.response_code in ('034','033') and event.status == "exitoso":
                    kanban_state = 'green'
            rec.titulo_state = kanban_state

    def add_application_response(self):
        for rec in self:
            response_code = rec._context.get('response_code')
            ar = self.env['dian.application.response'].generate_from_electronic_invoice(rec.id, response_code)


    def _get_GetStatus_values(self):
        xml_soap_values = global_functions.get_xml_soap_values(
            self.company_id.certificate_file,
            self.company_id.certificate_key)
        cufe = self.cufe
        if self.move_type == "in_invoice":
            cufe = self.cufe_cuds_other_system
        xml_soap_values['trackId'] = cufe
        return xml_soap_values

    def action_GetStatus(self):
        wsdl = DIAN['wsdl-hab']
        if self.company_id.production:
            wsdl = DIAN['wsdl']
        GetStatus_values = self._get_GetStatus_values()
        GetStatus_values['To'] = wsdl.replace('?wsdl', '')
        xml_soap_with_signature = global_functions.get_xml_soap_with_signature(
            global_functions.get_template_xml(GetStatus_values, 'GetStatus'),
            GetStatus_values['Id'],
            self.company_id.certificate_file,
            self.company_id.certificate_key)
        response = post(
            wsdl,
            headers={'content-type': 'application/soap+xml;charset=utf-8'},
            data=etree.tostring(xml_soap_with_signature, encoding="unicode"))

        if response.status_code == 200:
            self._get_status_response(response,send_mail=False)
        else:
            raise ValidationError(response.status_code)

        return True

    def action_GetStatusevent(self):
        wsdl = DIAN['wsdl-hab']

        if self.company_id.production:
            wsdl = DIAN['wsdl']

        GetStatus_values = self._get_GetStatus_values()
        GetStatus_values['To'] = wsdl.replace('?wsdl', '')
        xml_soap_with_signature = global_functions.get_xml_soap_with_signature(
            global_functions.get_template_xml(GetStatus_values, 'GetStatusEvent'),
            GetStatus_values['Id'],
            self.company_id.certificate_file,
            self.company_id.certificate_key)

        response = post(
            wsdl,
            headers={'content-type': 'application/soap+xml;charset=utf-8'},
            data=etree.tostring(xml_soap_with_signature, encoding="unicode"))

        if response.status_code == 200:
            self._get_status_response(response,send_mail=False)
        else:
            raise ValidationError(response.status_code)

        return True

    def create_records_from_xml(self):
        if not hasattr(self, 'message_error_DIAN_event') or not self.message_error_DIAN_event:
            return
        ar = self.env['dian.application.response']
        xml_string = self.message_error_DIAN_event  # Your XML string
        xml_bytes = xml_string.encode('utf-8')  # Convert to bytes
        root = etree.fromstring(xml_bytes)
        document_responses = []
        titulo_value = 'grey'
        for doc_response in root.findall('.//cac:DocumentResponse', namespaces=root.nsmap):
            if doc_response.find('.//cbc:ResponseCode', namespaces=root.nsmap).text in ['034', '033']:
                titulo_value = 'green'
            response_data = {
                'response_code': doc_response.find('.//cbc:ResponseCode', namespaces=root.nsmap).text,
                'name': doc_response.find('.//cbc:Description', namespaces=root.nsmap).text,
                'issue_date': doc_response.find('.//cbc:EffectiveDate', namespaces=root.nsmap).text,
                'move_id': self.id,
                'status': "exitoso",
                'dian_get': True,
                'response_message_dian': 'Procesado Correctamente',
            }
            doc_reference = doc_response.find('.//cac:DocumentReference', namespaces=root.nsmap)
            response_data['number'] = doc_reference.find('.//cbc:ID', namespaces=root.nsmap).text
            response_data['cude'] = doc_reference.find('.//cbc:UUID', namespaces=root.nsmap).text
            existing_record = ar.search([('cude', '=', response_data['cude'])], limit=1)
            if not existing_record:
                document_responses.append(response_data)
            else:
                continue 
        if document_responses or doc_response:
            if document_responses:
                ar.create(document_responses)
            self.titulo_state = titulo_value


    def _get_status_response(self, response, send_mail):
        b = "http://schemas.datacontract.org/2004/07/DianResponse"
        c = "http://schemas.microsoft.com/2003/10/Serialization/Arrays"
        s = "http://www.w3.org/2003/05/soap-envelope"
        strings = ''
        to_return = True
        status_code = 'other'
        root = etree.fromstring(response.content)
        date_invoice = self.invoice_date
        root2 = etree.tostring(root, pretty_print=True).decode()
        if not date_invoice:
            date_invoice = fields.Date.today()

        for element in root.iter("{%s}StatusCode" % b):
            if element.text in ('0', '00', '66', '90', '99'):
                status_code = element.text
        if status_code == '0':
            self.action_GetStatus()
            return True
        if status_code == '00':
            for element in root.iter("{%s}StatusMessage" % b):
                strings = element.text
            for element in root.iter("{%s}XmlBase64Bytes" % b):
                self.write({'message_error_DIAN_event': base64.b64decode(element.text).decode('utf-8') })
            to_return = True
        else:
            if send_mail:
                to_return = True
        for element in root.iter("{%s}string" % c):
            if strings == '':
                strings = '- ' + element.text
            else:
                strings += '\n\n- ' + element.text
        if strings == '':
            for element in root.iter("{%s}Body" % s):
                strings = etree.tostring(element, pretty_print=True)
            if strings == '':
                strings = etree.tostring(root, pretty_print=True)
        self.write({
            'get_status_event_status_code': status_code,
            'get_status_event_response': strings,
            'response_eve_dian' : strings})
        self.create_records_from_xml()
        return True

    @api.model
    def _get_time(self):
        fmt = "%H:%M:%S"
        now_utc = datetime.now(timezone("UTC"))
        now_time = now_utc.strftime(fmt)
        return now_time

    @api.model
    def _get_time_colombia(self):
        fmt = "%H:%M:%S-05:00"
        now_utc = datetime.datetime.now(timezone("UTC"))
        now_time = now_utc.strftime(fmt)
        return now_time


    def generar_invoice_tax(self, invoice):
        """
        Genera toda la estructura fiscal DIAN con manejo completo de:
        - Impuestos incluidos/excluidos
        - Retenciones
        - Redondeos (EDI 2.1)
        - Conversiones monetarias
        - Cálculo de totales
        """
        # Configuración inicial de tiempos
        invoice.fecha_xml = fields.Datetime.to_string(datetime.datetime.now(tz=timezone('America/Bogota')))
        invoice.fecha_entrega = invoice.fecha_entrega or fields.Datetime.to_string(datetime.datetime.now(tz=timezone('America/Bogota')))
                
        # Parámetros monetarios y de conversión
        calculation_rate = invoice.current_exchange_rate if invoice.currency_id.name != 'COP' else 1.0
        is_purchase = invoice.move_type in ['in_invoice', 'in_refund']
        currency_code = invoice.currency_id.name

        # Estructuras de datos principales
        tax_total_values = {}
        ret_total_values = {}
        line_extension_amount = 0.0
        line_excluir_amount = 0.0
        total_impuestos = 0.0
        invoice.total_withholding_amount = 0.0
        invoice_lines = []
        total_iva = 0.0

        def is_excluded_tax(tax):
            """Determina si un impuesto está excluido"""
            return tax.codigo_dian == '01' and any(t in tax.name.lower() for t in ['excluido', 'exc'])

        def format_rate(rate, tax_code):
            """Formatea la tasa según el código de impuesto"""
            return f"{rate:.4f}" if tax_code == '07' else f"{rate:.2f}"

        def process_tax(line, taxes_computed, base_amount_unit):
            """Procesa los impuestos de una línea específica"""
            tax_info = {}
            ret_info = {}
            iva_amount = 0.0

            # Filtrar y procesar impuestos aplicables
            for tax in line.tax_ids.filtered(lambda t: t.tributes != 'ZZ' and not is_excluded_tax(t)):
                tax_code = tax.codigo_dian
                is_retention = tax.amount < 0
                
                # Validar retenciones en compras
                if is_purchase and is_retention and tax_code != '06':
                    continue

                # Cálculos base por línea
                tax_amount = sum(t['amount'] for t in taxes_computed['taxes'] if t['id'] == tax.id)
                tax_amount_abs = abs(tax_amount)
                tax_amount_cop = tax_amount_abs * calculation_rate
                taxable_amount = line._l10n_co_dian_net_price_subtotal()
                rate = abs(tax.amount)
                rate = rate / 1000 if tax_code == '07' else rate

                # Preparar datos de impuestos por línea
                rate_key = format_rate(rate, tax_code)
                tax_data = {
                    'taxable_amount': line._l10n_co_dian_net_price_subtotal(),
                    'value': tax_amount_cop,
                    'technical_name': tax.nombre_dian,
                    'amount_type': tax.amount_type,
                    'per_unit_amount': rate,
                    'price_include': tax.price_include,
                }

                # Actualizar estructura por línea
                target_dict = ret_info if is_retention else tax_info
                target_dict.setdefault(tax_code, {'total': 0.0, 'info': {}})
                target_dict[tax_code]['info'][rate_key] = tax_data
                target_dict[tax_code]['total'] = tax_amount_cop

                # Actualizar totales globales
                global_dict = ret_total_values if is_retention else tax_total_values
                global_dict.setdefault(tax_code, {'total': 0.0, 'info': {}})
                
                if rate_key in global_dict[tax_code]['info']:
                    global_dict[tax_code]['info'][rate_key]['value'] += tax_amount_cop
                    global_dict[tax_code]['info'][rate_key]['taxable_amount'] += taxable_amount
                else:
                    global_dict[tax_code]['info'][rate_key] = {
                        'taxable_amount': taxable_amount,
                        'value': tax_amount_cop,
                        'technical_name': tax.nombre_dian,
                        'amount_type': tax.amount_type,
                        'per_unit_amount': rate,
                        'price_include': tax.price_include,
                    }
                
                global_dict[tax_code]['total'] += tax_amount_cop

                # Acumular IVA y retenciones
                if tax_code in ('01',"04","03","02") and not is_retention:
                    iva_amount += tax_amount_cop
                elif is_retention:
                    invoice.total_withholding_amount += tax_amount_cop

            return tax_info, ret_info, iva_amount

        # Procesar líneas de la factura
        for line in invoice.invoice_line_ids.filtered(lambda l: l.display_type == 'product' and not l.product_id.enable_charges and l.price_unit > 0):
            base = (line.price_unit * line.quantity) * (1 - line.discount / 100)
            taxes_computed = line.tax_ids.compute_all(
                base,
                currency=line.currency_id,
                quantity=1,
                product=line.product_id,
                partner=invoice.partner_id,
            )

            # Manejar base imponible
            total_excluded = taxes_computed['total_excluded']
            line_extension_amount += total_excluded

            # Verificar exclusiones
            if any(is_excluded_tax(t) for t in line.tax_ids):
                line_excluir_amount += total_excluded
                #continue

            # Procesar impuestos de la línea
            base_amount_unit = total_excluded / (line.quantity or 1.0)
            tax_info, ret_info, iva_amount = process_tax(line, taxes_computed, base_amount_unit)
            total_iva += iva_amount
            total_impuestos += sum(t['amount'] for t in taxes_computed['taxes']) * calculation_rate

            # Agregar línea al XML
            invoice_lines.append(self._prepare_invoice_line_data(
                line=line,
                index=len(invoice_lines) + 1,
                tax_info=tax_info,
                ret_info=ret_info,
                discount_line=round(total_excluded * (line.discount / 100), 2),
                discount_percentage=line.discount,
                base_discount=total_excluded,
                code=invoice._get_product_code(line),
                taxes=taxes_computed,
                calculation_rate=calculation_rate,
                quantity=line.quantity,
                price_unit=total_excluded / line.quantity if line.quantity else 0.0
            ))

        # Conversión final a COP
        line_extension_amount = abs(line_extension_amount * calculation_rate)
        line_excluir_amount = abs(line_excluir_amount * calculation_rate)
        total_impuestos = abs(total_impuestos)
        tax_inclusive_amount = line_extension_amount + total_iva

        # Manejo de redondeo DIAN EDI 2.1
        rounding_lines = invoice.line_ids.filtered(lambda l: 
            l.display_type == 'rounding' or 
            (l.product_id.default_code == 'RED' and l.product_id.enable_charges)
        )
        rounding_total = sum(rounding_lines.mapped('balance')) * (-1 if invoice.move_type == 'out_refund' else 1)
        rounding_charge = abs(rounding_total) if rounding_total < 0 else 0.0
        rounding_discount = abs(rounding_total) if rounding_total > 0 else 0.0

        # Calcular ajuste de redondeo
        rounding_adjustment_data = None
        if rounding_total != 0:
            try:
                multiplier = abs(rounding_total) / line_extension_amount * 100
            except ZeroDivisionError:
                multiplier = 0.0
                
            rounding_adjustment_data = {
                'ID': '3' if rounding_total < 0 else '2',
                'ChargeIndicator': 'true' if rounding_total < 0 else 'false',
                'AllowanceChargeReason': 'Cargo por ajuste al peso' if rounding_total < 0 else 'Descuento por ajuste al peso',
                'MultiplierFactorNumeric': f"{multiplier:.6f}",
                'Amount': f"{abs(rounding_total):.2f}",
                'BaseAmount': f"{line_extension_amount:.2f}",
                'CurrencyID': currency_code
            }

        # Calcular total a pagar final
        payable_amount = tax_inclusive_amount + rounding_charge - rounding_discount

        # Generación de códigos de seguridad
        cufe_cuds, qr, cude_seed, qr_code = invoice.calcular_cufe_cuds(
            tax_total_values, 
            line_extension_amount,
            rounding_charge,
            rounding_discount,
            total_iva
        )

        # Convertir montos a COP si es necesario
        if invoice.currency_id.name != 'COP':
            rete_cop, tax_cop = invoice.calculate_cop_taxes(tax_total_values, ret_total_values, calculation_rate)
        else:
            rete_cop = {'rete_fue_cop': 0.0, 'rete_iva_cop': 0.0, 'rete_ica_cop': 0.0}
            tax_cop = {'tot_iva_cop': 0.0, 'tot_inc_cop': 0.0, 'tot_bol_cop': 0.0, 'imp_otro_cop': 0.0}

        # Preparar datos de salida
        return {
            'cufe': cufe_cuds,
            'cufe': cufe_cuds,
            'qr': qr,
            'qr_code': qr_code,
            'cude_seed': cude_seed,
            'UUID': cufe_cuds,
            'currency_id': currency_code,
            'invoice_lines': invoice_lines,
            'invoice_note': html2text(invoice.narration or '')[:1000] if invoice.narration else '',
            
            
            # Totales
            'line_extension_amount': f"{line_extension_amount:.2f}",
            'tax_exclusive_amount': f"{(line_extension_amount - line_excluir_amount):.2f}",
            'tax_inclusive_amount': f"{tax_inclusive_amount:.2f}",
            'payable_amount': f"{payable_amount:.2f}",
            
            # Redondeo
            'rounding_discount': f"{rounding_discount:.2f}",
            'rounding_charge': f"{rounding_charge:.2f}",
            'rounding_adjustment_data': rounding_adjustment_data,
            
            # Impuestos
            'ret_total_values': ret_total_values,
            'tax_total_values': tax_total_values,
            'total_withholding_amount': invoice.total_withholding_amount,
            
            # Campos de contacto
            'ContactName': invoice.partner_contact_id.name or '',
            'ContactTelephone': invoice.partner_contact_id.phone or '',
            'ContactElectronicMail': invoice.partner_contact_id.email or '',
            'rete_fue_cop': rete_cop['rete_fue_cop'],
            'rete_iva_cop': rete_cop['rete_iva_cop'],
            'rete_ica_cop': rete_cop['rete_ica_cop'],
            'tot_iva_cop': tax_cop['tot_iva_cop'],
            'tot_inc_cop': tax_cop['tot_inc_cop'],
            'tot_bol_cop': tax_cop['tot_bol_cop'],
            'imp_otro_cop': tax_cop['imp_otro_cop'],
            'rounding_adjustment_data': rounding_adjustment_data,
        }


    def _prepare_invoice_line_data(self, line, index, tax_info, ret_info, discount_line, discount_percentage, base_discount, code, taxes, calculation_rate, quantity=None, name=None, price_unit=None):
        return {
            'id': index,
            'product_id': line.product_id,
            'invoiced_quantity': quantity or line.quantity,
            'uom_product_id': line.product_uom_id,
            'line_extension_amount': base_discount, #- (sum(tax['amount'] for tax in taxes['taxes'] if tax['amount'] > 0) * calculation_rate),
            'item_description': saxutils.escape(name or line.name),
            'price': price_unit * calculation_rate if price_unit is not None else (base_discount / (quantity or line.quantity)),
            'total_amount_tax': sum(tax['amount'] for tax in taxes['taxes'] if tax['amount'] > 0) * calculation_rate,
            'tax_info': tax_info,
            'ret_info': ret_info,
            'discount': discount_line,
            'discount_percentage': discount_percentage,
            'base_discount': base_discount,
            'invoice_start_date': datetime.datetime.now().astimezone(pytz.timezone("America/Bogota")).strftime('%Y-%m-%d'),
            'transmission_type_code': 1,
            'transmission_description': 'Por operación',
            'discount_text':  dict(line._fields['invoice_discount_text'].selection).get(line.invoice_discount_text),
            'discount_code': line.invoice_discount_text,
            'multiplier_discount': discount_percentage,
            'line_trade_sample_price': line.line_trade_sample_price * calculation_rate,
            'line_price_reference': (line.line_price_reference * (quantity or line.quantity)) * calculation_rate,
            'brand_name': line.product_id.brand_id.name,
            'model_name': line.product_id.model_id.name,
            'StandardItemIdentificationID': code[0],
            'StandardItemIdentificationschemeID': code[1],
            'StandardItemIdentificationschemeAgencyID': code[2],
            'StandardItemIdentificationschemeName': code[3]
        }
    def _get_product_code(self, line):
        if line.move_id.fe_type == '02':
            if not line.product_id.dian_customs_code:
                raise UserError(_('Las facturas de exportación requieren un código aduanero en todos los productos, completa esta información antes de validar la factura.'))
            return [line.product_id.dian_customs_code, '020', '195', 'Partida Arancelarias']
        if line.product_id.barcode:
            return [line.product_id.barcode, '010', '9', 'GTIN']
        elif line.product_id.unspsc_code_id:
            return [line.product_id.unspsc_code_id.code, '001', '10', 'UNSPSC']
        elif line.product_id.default_code:
            return [line.product_id.default_code, '999', '', 'Estándar de adopción del contribuyente']
        return ['NA', '999', '', 'Estándar de adopción del contribuyente']



    def get_customer_commercial_registration(self):
        if self.partner_id and self.partner_id.business_name:
            return self.partner_id.business_name
        elif not self.partner_id and self.partner_id.parent_id.business_name:
            return self.partner_id.parent_id.business_name
        else:
            return 0

    def calculate_cop_taxes(self, tax_total_values, ret_total_values, calculation_rate):
        rete_cop = {'rete_fue_cop': 0.0, 'rete_iva_cop': 0.0, 'rete_ica_cop': 0.0}
        tax_cop = {'tot_iva_cop': 0.0, 'tot_inc_cop': 0.0, 'tot_bol_cop': 0.0, 'imp_otro_cop': 0.0}
        
        for tax_type, ret_total in ret_total_values.items():
            if tax_type == '05':
                rete_cop['rete_iva_cop'] = abs(ret_total['total']) * calculation_rate
            elif tax_type == '06':
                rete_cop['rete_fue_cop'] = abs(ret_total['total']) * calculation_rate
            elif tax_type == '07':
                rete_cop['rete_ica_cop'] = abs(ret_total['total']) * calculation_rate
        
        for tax_type, tax_total in tax_total_values.items():
            if tax_type == '01':
                tax_cop['tot_iva_cop'] = tax_total['total'] * calculation_rate
            elif tax_type == '04':
                tax_cop['tot_inc_cop'] = tax_total['total'] * calculation_rate
            elif tax_type == '22':
                tax_cop['tot_bol_cop'] = tax_total['total'] * calculation_rate
            else:
                tax_cop['imp_otro_cop'] += tax_total['total'] * calculation_rate
        
        return rete_cop, tax_cop

    def calcular_cufe_cuds(self, tax_total_values, amount_untaxed, rounding_charge, rounding_discount,total_impuestos):
        if self.move_type in ["out_invoice", "out_refund"]:
            return self.calcular_cufe(tax_total_values, amount_untaxed, rounding_charge, rounding_discount,total_impuestos)
        elif self.move_type in ["in_invoice", "in_refund"]:
            return self.calcular_cuds(tax_total_values, amount_untaxed, rounding_charge, rounding_discount,total_impuestos)

    def _generate_qr_code(self, silent_errors=False):
        self.ensure_one()
        if self.company_id.country_code == 'CO':
            payment_url = self.diancode_id.qr_data or self.cufe_seed or self.name
            barcode = self.env['ir.actions.report'].barcode(barcode_type="QR", value=payment_url, width=120, height=120)
            return image_data_uri(base64.b64encode(barcode))
        return super()._generate_qr_code(silent_errors)


    def calcular_cufe(self, tax_total_values,amount_untaxed, rounding_charge, rounding_discount,total_impuestos):
        rec_active_resolution = (self.journal_id.sequence_id.dian_resolution_ids.filtered(lambda r: r.active_resolution))
        tax_computed_values = {tax: value['total'] for tax, value in tax_total_values.items()}

        numfac = self.name
        fecfac = self.fecha_xml.date().isoformat()
        horfac = self.fecha_xml.strftime("%H:%M:%S-05:00")
        valfac = '{:.2f}'.format(abs(amount_untaxed))
        codimp1 = '01'
        valimp1 = '{:.2f}'.format(tax_computed_values.get('01', 0))
        codimp2 = '04'
        valimp2 = '{:.2f}'.format(tax_computed_values.get('04', 0))
        codimp3 = '03'
        valimp3 = '{:.2f}'.format(tax_computed_values.get('03', 0))
        valtot = '{:.2f}'.format(abs(amount_untaxed) + abs(total_impuestos) + abs(rounding_charge) - abs(rounding_discount))
        contacto_compañia = self.company_id.partner_id
        nitofe = str(contacto_compañia.vat_co)
        if self.company_id.production:
            tipoambiente = '1'
        else:
            tipoambiente = '2'
        numadq = str(self.partner_id.vat_co) or str(self.partner_id.parent_id.vat_co)
        if self.move_type == 'out_invoice' and not self.is_debit_note:
            citec =  rec_active_resolution.technical_key
        else:
            citec = self.company_id.software_pin

        total_otros_impuestos = sum([value for key, value in tax_computed_values.items() if key != '01'])
        iva = tax_computed_values.get('01', '0.00')
                #1
        cufe = unidecode(
            str(numfac) + str(fecfac) + str(horfac) + str(valfac) + str(codimp1) + str(valimp1) + str(codimp2) +
            str(valimp2) + str(codimp3) + str(valimp3) + str(valtot) + str(nitofe) + str(numadq) + str(citec) +
            str(tipoambiente))
        cufe_seed = cufe

        sha384 = hashlib.sha384()
        sha384.update(cufe.encode())
        cufe = sha384.hexdigest()

        qr_code = 'NumFac: {}\n' \
                  'FecFac: {}\n' \
                  'HorFac: {}\n' \
                  'NitFac: {}\n' \
                  'DocAdq: {}\n' \
                  'ValFac: {}\n' \
                  'ValIva: {}\n' \
                  'ValOtroIm: {:.2f}\n' \
                  'ValFacIm: {}\n' \
                  'CUFE: {}'.format(
                    numfac,
                    fecfac,
                    horfac,
                    nitofe,
                    numadq,
                    valfac,
                    iva,
                    total_otros_impuestos,
                    valtot,
                    cufe
                    )

        qr = pyqrcode.create(qr_code, error='L')        
        return cufe, qr.png_as_base64_str(scale=2),cufe_seed,qr_code

    def calcular_cuds(self, tax_total_values, amount_untaxed, rounding_charge, rounding_discount,total_impuestos):
        tax_computed_values = {tax: value['total'] for tax, value in tax_total_values.items()}
        numfac = self.name
        fecfac = self.fecha_xml.date().isoformat()
        horfac = self.fecha_xml.strftime("%H:%M:%S-05:00")
        valfac = '{:.2f}'.format(abs(amount_untaxed))
        codimp1 = '01'
        valimp1 = '{:.2f}'.format(tax_computed_values.get('01', 0))
        valtot = '{:.2f}'.format(abs(amount_untaxed) + abs(total_impuestos) + abs(rounding_charge) - abs(rounding_discount))
        company_contact = self.company_id.partner_id
        nitofe = str(company_contact.vat_co)
        if self.company_id.production:
            tipoambiente = '1'
        else:
            tipoambiente = '2'
        numadq = str(self.partner_id.vat_co) or str(self.partner_id.parent_id.vat_co)
        citec = self.company_id.software_pin

        total_otros_impuestos = sum([value for key, value in tax_computed_values.items() if key != '01'])
        iva = tax_computed_values.get('01', '0.00')

        cuds =  unidecode(
            str(numfac) + str(fecfac) + str(horfac) + str(valfac) + str(codimp1) + str(valimp1) + str(valtot) +
            str(numadq) + str(nitofe) + str(citec) + str(tipoambiente)
        )
        cuds_seed = cuds

        sha384 = hashlib.sha384()
        sha384.update(cuds.encode())
        cuds = sha384.hexdigest()

        if not self.company_id.production:
            qr_code = 'NumFac: {}\n' \
                    'FecFac: {}\n' \
                    'HorFac: {}\n' \
                    'NitFac: {}\n' \
                    'DocAdq: {}\n' \
                    'ValFac: {}\n' \
                    'ValIva: {}\n' \
                    'ValOtroIm: {:.2f}\n' \
                    'ValFacIm: {}\n' \
                    'CUDS: {}\n' \
                    'https://catalogo-vpfe-hab.dian.gov.co/document/searchqr?documentkey={}'.format(
                    numfac,
                    fecfac,
                    horfac,
                    nitofe,
                    numadq,
                    valfac,
                    iva,
                    total_otros_impuestos,
                    valtot,
                    cuds,
                    cuds
                    )
        else:
            qr_code = 'NumFac: {}\n' \
                  'FecFac: {}\n' \
                  'HorFac: {}\n' \
                  'NitFac: {}\n' \
                  'DocAdq: {}\n' \
                  'ValFac: {}\n' \
                  'ValIva: {}\n' \
                  'ValOtroIm: {:.2f}\n' \
                  'ValFacIm: {}\n' \
                  'CUDS: {}\n' \
                  'https://catalogo-vpfe.dian.gov.co/document/searchqr?documentkey={}'.format(
                    numfac,
                    fecfac,
                    horfac,
                    nitofe,
                    numadq,
                    valfac,
                    iva,
                    total_otros_impuestos,
                    valtot,
                    cuds,
                    cuds
                    )

        qr = pyqrcode.create(qr_code, error='L')

        return cuds, qr.png_as_base64_str(scale=2),cuds_seed,qr_code



    def remove_accents(self, chain):
        s = ''.join((c for c in unicodedata.normalize('NFD', chain) if unicodedata.category(c) != 'Mn'))
        return s

class InvoiceLine(models.Model):
    _inherit = "account.move.line"
    line_price_reference = fields.Float(string='Precio de referencia')
    line_trade_sample_price = fields.Selection(string='Tipo precio de referencia',
                                               related='move_id.trade_sample_price')
    line_trade_sample = fields.Boolean(string='Muestra comercial', related='move_id.invoice_trade_sample')
    invoice_discount_text = fields.Selection(
        selection=[
            ('00', 'Descuento no condicionado'),
            ('01', 'Descuento condicionado')
        ],
        string='Motivo de Descuento',
    )

    def _l10n_co_dian_net_price_subtotal(self):
        """ Returns the price subtotal after discount in company currency. """
        self.ensure_one()
        return self.move_id.direction_sign * self.balance

    def _l10n_co_dian_gross_price_subtotal(self):
        """ Returns the price subtotal without discount in company currency. """
        self.ensure_one()
        if self.discount == 100.0:
            return 0.0
        else:
            net_price_subtotal = self._l10n_co_dian_net_price_subtotal()
            return self.company_id.currency_id.round(net_price_subtotal / (1.0 - (self.discount or 0.0) / 100.0))

class receiptCode(models.Model):
    _name = 'receipt.code'
    _description = 'Receipt'

    name = fields.Char('Name')
    move_id = fields.Many2one("account.move")
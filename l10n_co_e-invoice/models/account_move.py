
import logging
import xmltodict
import hashlib
import uuid
import base64
import zipfile
import pyqrcode
import time
import ssl
import html
import binascii
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, date
from num2words import num2words
from lxml import etree
from lxml.builder import ElementMaker
from lxml.etree import CDATA
from markupsafe import Markup
from odoo import api, models, fields, Command, _, tools
from odoo.exceptions import UserError, ValidationError, AccessError, RedirectWarning
from odoo.tools import float_repr, cleanup_xml_node, html_escape, formatLang, format_date, get_lang
from odoo.tools.image import image_data_uri
from pytz import timezone
from unidecode import unidecode
from io import BytesIO
from xml.sax import saxutils
from requests import post, exceptions
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives import hashes
from cryptography import x509
from . import xml_utils
import io

_logger = logging.getLogger(__name__)
urllib3_logger = logging.getLogger('urllib3')
urllib3_logger.setLevel(logging.ERROR)

ssl._create_default_https_context = ssl._create_unverified_context

# =============================================================================
# SECCIÓN: CONSTANTES Y CONFIGURACIÓN GLOBAL
# =============================================================================

# URLs DIAN
DIAN = {
    'wsdl-hab': 'https://vpfe-hab.dian.gov.co/WcfDianCustomerServices.svc?wsdl',
    'wsdl': 'https://vpfe.dian.gov.co/WcfDianCustomerServices.svc?wsdl',
    'catalogo-hab': 'https://catalogo-vpfe-hab.dian.gov.co/Document/FindDocument?documentKey={}&partitionKey={}&emissionDate={}',
    'catalogo': 'https://catalogo-vpfe.dian.gov.co/Document/FindDocument?documentKey={}&partitionKey={}&emissionDate={}'
}

# Tipos de documento
DOCUMENT_TYPES = {
    'out_invoice': {'id': 'fv', 'prefix': True, 'tag': 'Invoice', 'code': '01'},
    'in_invoice': {'id': 'ds', 'prefix': True, 'tag': 'Invoice', 'code': '05'},
    'out_invoice_03': {'id': 'fv', 'prefix': True, 'tag': 'Invoice', 'code': '03'},
    'out_invoice_04': {'id': 'fv', 'prefix': True, 'tag': 'Invoice', 'code': '03'},
    'out_refund': {'id': 'nc', 'prefix': False, 'tag': 'CreditNote', 'code': '91'},
    'in_refund': {'id': 'nc', 'prefix': False, 'tag': 'CreditNote', 'code': '95'},
    'debit_note': {'id': 'nd', 'prefix': False, 'tag': 'DebitNote', 'code': '92'},
    'export_invoice': {'id': 'fv', 'prefix': True, 'tag': 'Invoice', 'code': '02'},
}

# Códigos de impuestos
TAX_CODES = {
    '01': {'name': 'IVA', 'type': 'standard'},
    '02': {'name': 'IC', 'type': 'consumption'},
    '03': {'name': 'ICA', 'type': 'local'},
    '04': {'name': 'INC', 'type': 'consumption'},
    '05': {'name': 'ReteIVA', 'type': 'withholding'},
    '06': {'name': 'ReteFuente', 'type': 'withholding'},
    '07': {'name': 'ReteICA', 'type': 'withholding'},
    '22': {'name': 'Bolsas', 'type': 'environmental'},
    '32': {'name': 'ICL', 'type': 'special'},
    '34': {'name': 'IBUA', 'type': 'special'},
    'ZZ': {'name': 'Otros', 'type': 'other'}
}

# Tipos de operación
EDI_OPERATION_TYPE = [
    ('10', 'Estándar'),
    ('09', 'AIU'),
    ('11', 'Mandatos'),
    ('12', 'Transporte'),
    ('13', 'Cambiario'),
    ('15', 'Compra Divisas'),
    ('16', 'Venta Divisas'),
    ('20', 'Nota Crédito que referencia una factura electrónica'),
    ('22', 'Nota Crédito sin referencia a facturas'),
    ('23', 'Nota Crédito para facturación electrónica V1 (Decreto 2242)'),
    ('30', 'Nota Débito que referencia una factura electrónica'),
    ('32', 'Nota Débito sin referencia a facturas'),
    ('33', 'Nota Débito para facturación electrónica V1 (Decreto 2242)')
]

# Esquemas de seguridad
SCHEME_MAPPING = {
    'out_invoice': 'CUFE-SHA384',
    'out_refund': 'CUDE-SHA384',
    'in_invoice': 'CUDS-SHA384',
    'in_refund': 'CUDS-SHA384',
    'debit_note': 'CUDE-SHA384'
}

# Códigos de eventos
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

# Ambiente
AMBIENTE_MAPPING = {
    "PRODUCCION": "1",
    "PRUEBA": "2",
}


class PaymentMethodDian(models.Model):
    """Métodos de pago DIAN"""
    _name = "account.payment.method.dian"
    _description = "Métodos de Pago DIAN"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True)

    _sql_constraints = [
        ("name_code_unique", "unique (code)", "El código ya existe!"),
    ]


class AccountMove(models.Model):
    _name = 'account.move'
    _inherit = ['account.move', 'abstract.dian.mixin']
    _description = 'Account Move with DIAN'
        
    def _auto_init(self):
        res = super()._auto_init()
        cr = self.env.cr
        
        _logger.info("Verificando y creando columnas DIAN en account.move...")
        
        # Crear columnas de texto/char
        if not tools.column_exists(cr, "account_move", "cufe_seed"):
            tools.create_column(cr, 'account_move', 'cufe_seed', 'varchar')

        if not tools.column_exists(cr, "account_move", "archivo_xml_invoice_name"):
            tools.create_column(cr, 'account_move', 'archivo_xml_invoice_name', 'varchar')
            
        if not tools.column_exists(cr, "account_move", "zip_file_name"):
            tools.create_column(cr, 'account_move', 'zip_file_name', 'varchar')
            
        if not tools.column_exists(cr, "account_move", "contingency_invoice_number"):
            tools.create_column(cr, 'account_move', 'contingency_invoice_number', 'varchar')
            
        if not tools.column_exists(cr, "account_move", "concepto_credit_note"):
            tools.create_column(cr, 'account_move', 'concepto_credit_note', 'varchar')
            
        if not tools.column_exists(cr, "account_move", "concept_debit_note"):
            tools.create_column(cr, 'account_move', 'concept_debit_note', 'varchar')
            
        if not tools.column_exists(cr, "account_move", "payment_format"):
            tools.create_column(cr, 'account_move', 'payment_format', 'varchar')
            
        if not tools.column_exists(cr, "account_move", "document_from_other_system"):
            tools.create_column(cr, 'account_move', 'document_from_other_system', 'varchar')
            
        if not tools.column_exists(cr, "account_move", "cufe_cuds_other_system"):
            tools.create_column(cr, 'account_move', 'cufe_cuds_other_system', 'varchar')
            
        if not tools.column_exists(cr, "account_move", "amount_letters"):
            tools.create_column(cr, 'account_move', 'amount_letters', 'varchar')
            
        if not tools.column_exists(cr, "account_move", "trade_sample_price"):
            tools.create_column(cr, 'account_move', 'trade_sample_price', 'varchar')
            
        if not tools.column_exists(cr, "account_move", "get_status_event_status_code"):
            tools.create_column(cr, 'account_move', 'get_status_event_status_code', 'varchar')
            
        if not tools.column_exists(cr, "account_move", "titulo_state"):
            tools.create_column(cr, 'account_move', 'titulo_state', 'varchar')
            
        if not tools.column_exists(cr, "account_move", "fe_type"):
            tools.create_column(cr, 'account_move', 'fe_type', 'varchar')
            
        if not tools.column_exists(cr, "account_move", "fe_type_ei_ref"):
            tools.create_column(cr, 'account_move', 'fe_type_ei_ref', 'varchar')
            
        if not tools.column_exists(cr, "account_move", "fe_operation_type"):
            tools.create_column(cr, 'account_move', 'fe_operation_type', 'varchar')
            
        if not tools.column_exists(cr, "account_move", "supplier_claim_concept"):
            tools.create_column(cr, 'account_move', 'supplier_claim_concept', 'varchar')
            
        if not tools.column_exists(cr, "account_move", "last_event_status"):
            tools.create_column(cr, 'account_move', 'last_event_status', 'varchar')
        
        if not tools.column_exists(cr, "account_move", "validate_cron"):
            tools.create_column(cr, 'account_move', 'validate_cron', 'boolean')
            
        if not tools.column_exists(cr, "account_move", "is_debit_note"):
            tools.create_column(cr, 'account_move', 'is_debit_note', 'boolean')
            
        if not tools.column_exists(cr, "account_move", "contingency_3"):
            tools.create_column(cr, 'account_move', 'contingency_3', 'boolean')
            
        if not tools.column_exists(cr, "account_move", "contingency_4"):
            tools.create_column(cr, 'account_move', 'contingency_4', 'boolean')
            
        if not tools.column_exists(cr, "account_move", "hide_button_dian"):
            tools.create_column(cr, 'account_move', 'hide_button_dian', 'boolean')
            
        if not tools.column_exists(cr, "account_move", "document_without_reference"):
            tools.create_column(cr, 'account_move', 'document_without_reference', 'boolean')
            
        if not tools.column_exists(cr, "account_move", "document_other_system"):
            tools.create_column(cr, 'account_move', 'document_other_system', 'boolean')
            
        if not tools.column_exists(cr, "account_move", "invoice_trade_sample"):
            tools.create_column(cr, 'account_move', 'invoice_trade_sample', 'boolean')
            
        if not tools.column_exists(cr, "account_move", "receipt"):
            tools.create_column(cr, 'account_move', 'receipt', 'boolean')
            
        if not tools.column_exists(cr, "account_move", "fe_warning"):
            tools.create_column(cr, 'account_move', 'fe_warning', 'boolean')
            
        if not tools.column_exists(cr, "account_move", "is_inactive_resolution"):
            tools.create_column(cr, 'account_move', 'is_inactive_resolution', 'boolean')
        
        if not tools.column_exists(cr, "account_move", "total_withholding_amount"):
            tools.create_column(cr, 'account_move', 'total_withholding_amount', 'float8')
            
        if not tools.column_exists(cr, "account_move", "credit_note_count"):
            tools.create_column(cr, 'account_move', 'credit_note_count', 'int4')
            
        if not tools.column_exists(cr, "account_move", "current_exchange_rate"):
            tools.create_column(cr, 'account_move', 'current_exchange_rate', 'float8')
        
        if not tools.column_exists(cr, "account_move", "diancode_id"):
            tools.create_column(cr, 'account_move', 'diancode_id', 'int4')
            
        if not tools.column_exists(cr, "account_move", "mandante_id"):
            tools.create_column(cr, 'account_move', 'mandante_id', 'int4')

        if not tools.column_exists(cr, "account_move", "method_payment_id"):
            tools.create_column(cr, 'account_move', 'method_payment_id', 'int4')

        if not tools.column_exists(cr, "account_move", "partner_contact_id"):
            tools.create_column(cr, 'account_move', 'partner_contact_id', 'int4')
        
        _logger.info("Verificación y creación de columnas DIAN completada en account.move")
        
    # Estado y validación
    validate_cron = fields.Boolean(string="Validar con CRON", default=False, copy=False)
    diancode_id = fields.Many2one(
        "dian.document", string="Código DIAN", readonly=True, tracking=True, copy=False
    )
    state_dian_document = fields.Selection(
        string="Estado documento DIAN", related="diancode_id.state", store=True
    )
    shipping_response = fields.Selection(
        string="Respuesta de envío DIAN", related="diancode_id.shipping_response"
    )
    response_document_dian = fields.Selection(
        string="Respuesta de consulta DIAN",
        related="diancode_id.response_document_dian",
    )
    email_response = fields.Selection(
        string="Decisión del cliente",
        related="diancode_id.email_response",
        tracking=True,
    )
    response_message_dian = fields.Text(
        string="Mensaje de respuesta DIAN", related="diancode_id.response_message_dian"
    )
    
    # Tipo de documento
    is_debit_note = fields.Boolean(
        string="Nota de débito", default=False, tracking=True, copy=False,
        compute='_compute_is_debit_note', store=True
    )
    
    # Códigos de seguridad
    cufe_seed = fields.Char(string="CUFE SEED")
    QR_code = fields.Binary(
        string="Código QR", readonly=True, related="diancode_id.QR_code", 
    )
    cufe = fields.Char(string="CUFE", readonly=True, related="diancode_id.cufe")
    qr_data = fields.Text(
        string="QR Data", related="diancode_id.qr_data",
    )
    qr_code = fields.Binary("Qr CODE")
    
    # XML y respuestas
    xml_response_dian = fields.Text(
        string="Contenido XML de la respuesta DIAN",
        readonly=True,
        related="diancode_id.xml_response_dian",
    )
    archivo_xml_invoice = fields.Binary(
        "Archivo DIAN XML de factura", readonly=True, copy=False
    )
    archivo_xml_invoice_name = fields.Char("Nombre de Xml")  
    xml_adjunto_ids = fields.Many2many(
        "ir.attachment",
        string="Archivo adjunto XML de factura",
        tracking=True,
        copy=False,
    )
    zip_file = fields.Binary('Archivo Zip')
    zip_file_name = fields.Char('Nombre archivo Zip')
    xml_text = fields.Text('Contenido XML')
    invoice_xml = fields.Text('Factura XML')

    mandante_id = fields.Many2one("res.partner", "Mandante", copy=False)
    
    # Contingencia
    contingency_3 = fields.Boolean(
        string="Contingencia tipo 3",
        copy=False,
        default=False,
        help="Cuando el facturador no puede expedir la factura electrónica por inconvenientes tecnológicos",
    )
    contingency_4 = fields.Boolean(
        string="Contingencia tipo 4",
        copy=False,
        default=False,
        help="Cuando las causas son atribuibles a situaciones de índole tecnológico a cargo de la DIAN",
    )
    xml_response_contingency_dian = fields.Text(
        string="Mensaje de respuesta DIAN al envío de la contingencia",
        related="diancode_id.xml_response_contingency_dian",
    )
    state_contingency = fields.Selection(
        string="Estatus de contingencia", related="diancode_id.state_contingency"
    )
    contingency_invoice_number = fields.Char(
        "Número de factura de contingencia", copy=False
    )
    count_error_DIAN = fields.Integer(
        string="Contador de intentos fallidos por problemas de la DIAN",
        related="diancode_id.count_error_DIAN",
    )
    in_contingency_4 = fields.Boolean(
        string="En contingencia", related="company_id.in_contingency_4"
    )
    exists_invoice_contingency_4 = fields.Boolean(
        string="Cantidad de facturas con contingencia 4 sin reportar a la DIAN",
        related="company_id.exists_invoice_contingency_4",
    )
    
    # UI y validación
    hide_button_dian = fields.Boolean(
        string="Ocultar", compute="_compute_hide_button_dian", default=True
    )
    concepto_credit_note = fields.Selection(
        [("1", "Devolución parcial de los bienes y/o no aceptación parcial del servicio"),
         ("2", "Anulación de factura electrónica"),
         ("3", "Rebaja total aplicada"),
         ("4", "Ajuste de precio"),
         ("5", "Descuento comercial por pronto pago"),
         ("6", "Descuento comercial por volumen de ventas")],
        string="Concepto Corrección Crédito",
    )
    concept_debit_note = fields.Selection(
        [("1", "Intereses"),
         ("2", "Gastos por cobrar"),
         ("3", "Cambio del valor"),
         ("4", "Otros"),],
        string="Concepto Corrección Débito",
    )
    method_payment_id = fields.Many2one(
        "account.payment.method.dian", 
        string="Método de Pago",        
        compute='_compute_payment_method_id', 
    )
    payment_format = fields.Char(
        string="Forma de Pago", compute="_compute_get_payment_format"
    )
    
    # Documentos externos
    document_from_other_system = fields.Char("Documento Sistema Anterior")
    date_from_other_system = fields.Date("Documento Sistema Anterior Fecha")
    date_from = fields.Date("Rango Inicial")
    date_to = fields.Date("Rango Final")
    cufe_cuds_other_system = fields.Char("CUFE/CUDS Otro sistema")
    document_without_reference = fields.Boolean('Documento sin Referencia')
    document_other_system = fields.Boolean('Documento Otro Sistema')
    
    # Información adicional
    refusal_reason = fields.Html('Motivo/s de rechazo', compute="_compute_refusal")
    amount_letters = fields.Char('Monto en letras', compute="_compute_amount_in_letters", store=True)
    application_response_ids = fields.Many2many('dian.application.response')
    attachment_ids = fields.One2many('ir.attachment', 'res_id', domain=[('res_model', '=', 'account.move')], string='Attachments')
    invoice_datetime = fields.Datetime('Fecha y hora de la factura', store=True)
    partner_contact_id = fields.Many2one(
        comodel_name='res.partner',
        string="Contacto Tercero",
        compute='_compute_partner_contact',
        store=True, readonly=False, precompute=True,
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]",
    )
    
    # Fechas DIAN
    fecha_envio = fields.Datetime(string='Fecha de envío en UTC', copy=False)
    fecha_entrega = fields.Datetime(string='Fecha de entrega', copy=False)
    fecha_xml = fields.Datetime(string='Fecha de factura Publicada', copy=False)
    
    # Totales
    total_withholding_amount = fields.Float(string='Total de retenciones')
    
    # Muestras comerciales
    invoice_trade_sample = fields.Boolean(string='Tiene muestras comerciales')
    receipt = fields.Boolean(string='Tiene órdenes de entrega?')
    trade_sample_price = fields.Selection([('01', 'Valor comercial')], string='Referencia a precio real')
    
    # Eventos
    get_status_event_status_code = fields.Selection([
        ('00', 'Procesado Correctamente'),
        ('66', 'NSU no encontrado'),
        ('90', 'TrackId no encontrado'),
        ('99', 'Validaciones contienen errores en campos mandatorios'),
        ('other', 'Other')
    ], string='StatusCode', default=False)
    get_status_event_response = fields.Text(string='Response')
    response_eve_dian = fields.Text(string='Response Dian')
    message_error_DIAN_event = fields.Text(string='Response Dian error')
    receipts = fields.One2many("receipt.code", "move_id", string="Código de entrega")
    
    # Título valor
    titulo_state = fields.Selection([
        ('grey', 'No Título Valor'),
        ('red', 'Proceso'),
        ('green', 'Título Valor')
    ], string='Título Valor', default='grey')
    
    # Tipo de factura electrónica
    fe_type = fields.Selection(
        [('01', 'Factura de venta'),
         ('02', 'Factura de exportación'),
         ('03', 'Documento electrónico de transmisión - tipo 03'),
         ('04', 'Factura electrónica de Venta - tipo 04'),
         ('05', 'Documento Equivalente'),],
        'Tipo De Factura Electrónica',
        required=False,
        default='01',
        readonly=True,
    )
    fe_type_ei_ref = fields.Selection(
        [('01', 'Factura de venta'),
         ('02', 'Factura de exportación'),
         ('05', 'Documento Equivalente'),
         ('91', 'Nota Crédito'),
         ('92', 'Nota Débito'),
         ('96', 'Eventos (ApplicationResponse)'),],
        'Tipo de Documento Electrónico',
        required=False,
        readonly=True,
        compute='_compute_type_ei_default',
    )
    fe_operation_type = fields.Selection(
        EDI_OPERATION_TYPE,
        'Tipo de Operación',
        default='10',
        required=True
    )
    
    # Reclamo proveedor
    supplier_claim_concept = fields.Selection(
        [('01', 'Documento con inconsistencias'),
         ('02', 'Mercancía no entregada totalmente'),
         ('03', 'Mercancía no entregada parcialmente'),
         ('04', 'Servicio no prestado'),],
        string="Concepto de Reclamo", tracking=True
    )
    
    # Conteo de notas crédito
    credit_note_count = fields.Integer('# NC', compute='_compute_credit_count')

    # Advertencias
    fe_warning = fields.Boolean(
        '¿Advertir por rangos de resolución?',
        compute='_compute_einv_warning',
        store=False
    )
    is_inactive_resolution = fields.Boolean(
        '¿Advertir resolución inactiva?',
        compute='_compute_einv_warning',
        store=False
    )
    
    # Último evento
    last_event_status = fields.Char(
        string="Último evento exitoso", 
        compute="_compute_last_event_status"
    )
    current_exchange_rate = fields.Float(
        string="Tasa de Cambio Actual",
        digits=(12, 6),
        help="Tasa de cambio actual utilizada para la conversión de moneda.",
        default=lambda self: self.currency_id._get_rates(self.company_id, date=date.today()) if self.company_id else 0.0
    )
        
    # =============================================================================
    # SECCIÓN: MÉTODOS COMPUTE
    # =============================================================================
    
    @api.depends('method_payment_id', 'journal_id')
    def _compute_payment_method_id(self):
        for move in self:
            if not move.method_payment_id:
                move.method_payment_id = move.journal_id.default_payment_method_dian_id.id
            payment_id = self.env['account.payment.method.dian'].search([('code', '=', '1')], limit=1).id
            if not payment_id:
                if move.state_dian_document == 'exitoso':
                    _logger.warning(
                        "No se encontró el método de pago predeterminado '1' en la configuración. "
                        "Asegúrese de que exista un método de pago con código '1'."
                    )
                    move.method_payment_id = False
                    _logger.warning(_("No se encontró el método de pago predeterminado '1' en la configuración."))
            else:
                move.method_payment_id = payment_id

    @api.depends('debit_origin_id')
    def _compute_is_debit_note(self):
        for record in self:
            record.is_debit_note = True if record.debit_origin_id else False
    
    @api.depends('partner_id')
    def _compute_partner_contact(self):
        for move in self:
            if move.is_invoice(include_receipts=True):
                addr = move.partner_id.address_get(['other'])
                move.partner_contact_id = addr and addr.get('other')
            else:
                move.partner_contact_id = False
    
    @api.depends('amount_total')
    def _compute_amount_in_letters(self):
        for rec in self:
            number_dec = round((rec.amount_total - int(rec.amount_total)) * 100, 0)
            palabra1 = num2words(int(rec.amount_total), lang="es")
            palabra2 = num2words(number_dec, lang="es")
            rec.amount_letters = palabra1.capitalize() + ' con ' + palabra2.replace('punto cero', '') + ' centavos'
    
    @api.depends("journal_id.sequence_id.use_dian_control", "move_type", "state", "state_dian_document")
    def _compute_hide_button_dian(self):
        for move in self:
            show_button = (
                move.journal_id.sequence_id.use_dian_control and
                move.move_type in ("out_invoice", "out_refund", "in_invoice", "in_refund") and
                move.state == "posted" and
                move.state_dian_document != "exitoso"
            )
            move.hide_button_dian = not show_button
    
    @api.depends("invoice_date", "invoice_date_due")
    def _compute_get_payment_format(self):
        for rec in self:
            if rec.invoice_date == rec.invoice_date_due:
                rec.payment_format = "Contado"
            else:
                rec.payment_format = "Crédito"
    
    @api.depends('move_type', 'partner_id')
    def _compute_type_ei_default(self):
        for rec in self:
            if rec.move_type in ('in_invoice') and not rec.is_debit_note:
                rec.fe_type_ei_ref = '05'
            elif rec.move_type in ('out_invoice', 'in_invoice') and rec.is_debit_note:
                rec.fe_type_ei_ref = '92'
            elif rec.move_type in ('out_refund', 'in_refund'):
                rec.fe_type_ei_ref = '91'
            else:
                rec.fe_type_ei_ref = '01'
    
    @api.depends('reversal_move_id')
    def _compute_credit_count(self):
        credit_data = self.env['account.move'].read_group(
            [('reversed_entry_id', 'in', self.ids)],
            ['reversed_entry_id'],
            ['reversed_entry_id']
        )
        data_map = {
            datum['reversed_entry_id'][0]: datum['reversed_entry_id_count'] 
            for datum in credit_data
        }
        for inv in self:
            inv.credit_note_count = data_map.get(inv.id, 0.0)
    
    @api.depends('application_response_ids.status', 'application_response_ids.response_code')
    def _compute_last_event_status(self):
        for record in self:
            last_successful_event = record.application_response_ids.filtered(
                lambda r: r.status == 'exitoso'
            ).sorted(key=lambda r: r.create_date, reverse=True)
            record.last_event_status = last_successful_event[0].response_code if last_successful_event else False
    
    @api.depends('xml_response_dian')
    def _compute_refusal(self):
        """Calcula el motivo de rechazo desde la respuesta XML"""
        def safe_get(dictionary, *keys):
            for key in keys:
                try:
                    dictionary = dictionary[key]
                except (KeyError, TypeError):
                    return None
            return dictionary

        def get_status_style(status_code=None, has_errors=False):
            if status_code == '00' or (status_code == '99' and 'Documento procesado anteriormente' in str(has_errors)):
                return 'success'
            elif status_code == '99' or has_errors:
                return 'error'
            return 'info'

        def build_html_message(status=None, errors=None, status_code=None):
            style = get_status_style(status_code, errors)
            
            styles = {
                'success': 'background-color: #dff0d8; color: #3c763d; padding: 15px; border: 1px solid #d6e9c6; border-radius: 4px; margin-bottom: 20px;',
                'error': 'background-color: #f2dede; color: #a94442; padding: 15px; border: 1px solid #ebccd1; border-radius: 4px; margin-bottom: 20px;',
                'info': 'background-color: #f5f5f5; color: #31708f; padding: 15px; border: 1px solid #ddd; border-radius: 4px; margin-bottom: 20px;'
            }
            
            html_content = [f'<div style="{styles[style]}">']
            
            if status:
                html_content.append(f"<p style='margin: 0 0 10px 0;'><strong>Estado:</strong> {html_escape(status)}</p>")
            
            if errors:
                if isinstance(errors, list) and errors:
                    html_content.append("<p style='margin: 0 0 10px 0;'><strong>Detalles:</strong></p><ul style='margin: 0; padding-left: 20px;'>")
                    for error in errors:
                        html_content.append(f"<li style='margin-bottom: 5px;'>{html_escape(error)}</li>")
                    html_content.append("</ul>")
                elif isinstance(errors, str):
                    html_content.append("<p style='margin: 0 0 10px 0;'><strong>Detalles:</strong></p><ul style='margin: 0; padding-left: 20px;'>")
                    html_content.append(f"<li style='margin-bottom: 5px;'>{html_escape(errors)}</li>")
                    html_content.append("</ul>")
            
            html_content.append('</div>')
            return Markup(''.join(html_content))

        for record in self:
            if not record.xml_response_dian or not isinstance(record.xml_response_dian, (str, bytes)):
                record.refusal_reason = build_html_message(
                    status="Error de validación",
                    errors="No hay respuesta XML válida de DIAN",
                    status_code="99"
                )
                continue

            try:
                dict_data_xml = xmltodict.parse(record.xml_response_dian)
            except Exception as e:
                record.refusal_reason = build_html_message(
                    status="Error de parsing",
                    errors=f"Error al parsear la respuesta XML: {str(e)}",
                    status_code="99"
                )
                continue

            message_data = {
                'status': None,
                'errors': [],
                'status_code': None
            }

            # Procesar respuesta
            for path in [
                ('s:Envelope', 's:Body', 'SendBillSyncResponse', 'SendBillSyncResult'),
                ('s:Envelope', 's:Body', 'SendTestSetAsyncResponse', 'SendTestSetAsyncResult')
            ]:
                status_code = safe_get(dict_data_xml, *path, 'b:StatusCode')
                status_desc = safe_get(dict_data_xml, *path, 'b:StatusDescription')
                status_msg = safe_get(dict_data_xml, *path, 'b:StatusMessage')
                errors = safe_get(dict_data_xml, *path, 'b:ErrorMessage', 'c:string')

                if status_code:
                    message_data['status_code'] = status_code
                if status_desc:
                    message_data['status'] = status_desc
                    if status_msg and status_msg != status_desc:
                        message_data['errors'].append(status_msg)

                if errors:
                    if isinstance(errors, str):
                        message_data['errors'].append(errors)
                    elif isinstance(errors, list):
                        message_data['errors'].extend(errors)

            record.refusal_reason = build_html_message(
                status=message_data['status'],
                errors=message_data['errors'],
                status_code=message_data['status_code']
            )
    
    def _compute_einv_warning(self):
        """Calcula advertencias sobre resoluciones"""
        for move in self:
            warn_remaining = False
            inactive_resolution = False
            sequence_id = move.journal_id.sequence_id

            if sequence_id.use_dian_control:
                remaining_numbers = max(5, sequence_id.remaining_numbers)
                remaining_days = max(5, sequence_id.remaining_days)
                date_range = self.env['ir.sequence.dian_resolution'].search([
                    ('sequence_id', '=', sequence_id.id),
                    ('active_resolution', '=', True)
                ])
                
                today = datetime.strptime(str(fields.Date.today(self)), '%Y-%m-%d')
                
                if date_range:
                    date_range.ensure_one()
                    date_to = datetime.strptime(str(date_range.date_to), '%Y-%m-%d')
                    days = (date_to - today).days
                    numbers = date_range.number_to - move.sequence_number
                    
                    if numbers < remaining_numbers or days < remaining_days:
                        warn_remaining = True
                else:
                    inactive_resolution = True
            
            move.is_inactive_resolution = inactive_resolution
            move.fe_warning = warn_remaining
    
    # =============================================================================
    # SECCIÓN: MÉTODOS DE ACCIÓN
    # =============================================================================
    
    def action_post(self):
        """Publicar factura y enviar a DIAN si aplica"""
        rec = super(AccountMove, self).action_post()
        
        for record in self:
            if record.journal_id.sequence_id.use_dian_control:
                errors = []
                #if not record.partner_id.dv and record.partner_id.l10n_latam_identification_type_id.dian_code in ("31","13"):
                #    record.partner_id._onchange_dv()
                # Validaciones básicas
                if record.move_type in record._hook_type_invoice(["out_invoice"]):
                    if record.debit_origin_id:
                        sequence_code = record.journal_id.debit_note_sequence_id.code
                        if not sequence_code:
                            errors.append("Debe definir el código de secuencia de la nota de débito")
                        else:
                            rec_sequence_nd = self.env["ir.sequence"]
                            number = rec_sequence_nd.next_by_code(sequence_code)
                            record.name = number
                
                # Validar datos del partner
                if record.move_type in ["in_invoice", "in_refund"] and record.partner_id.country_id.code == "CO":
                    if not record.partner_id.zip:
                        errors.append("El cliente no tiene código postal")
                    elif len(record.partner_id.zip) != 6:
                        errors.append("El código postal debe tener 6 dígitos")
             
                # Validar resolución
                resol = record.journal_id.sequence_id.dian_resolution_ids.filtered(lambda r: r.active_resolution)
                if not resol:
                    errors.append("La factura no tiene resolución DIAN asociada")
                elif not resol.technical_key:
                    errors.append("La resolución DIAN no tiene clave técnica")
                
                # Validar configuración de la compañía
                company = record.company_id
                required_fields = [
                    ("software_identification_code", "código de identificación del software"),
                    ("password_environment", "password del ambiente"),
                ]
                for field, message in required_fields:
                    if not getattr(company, field):
                        errors.append(f"Se debe configurar {message}")
                if not record.partner_id.dv and record.partner_id.l10n_latam_identification_type_id.dian_code == "31":
                    errors.append("El Digito Verificación esta vacio en el contacto")      
                if not record.partner_id.l10n_latam_identification_type_id and not record.partner_id.l10n_latam_identification_type_id.dian_code:
                    errors.append("No tiene tipo de verificacion")                 
                if record.invoice_line_ids:
                    for line in record.invoice_line_ids.filtered(lambda l: l.display_type == 'product'):
                        if line.tax_ids:
                            for tax in line.tax_ids:
                                if not tax.tributes:
                                    errors.append("Algunos impuestos no tienen tributo DIAN asociado")
                        else:
                            errors.append("La línea de factura no tiene impuestos asociados")
                
                # Validar email del cliente
                if not record.partner_id.email:
                    errors.append("El cliente no tiene email definido")
                
                if errors:
                    raise UserError("\n".join(errors))
                
                # Enviar a DIAN
            if record._is_dian_applicable() and not record.validate_cron:
                try:
                    record.dian_send_invoice()
                except Exception as e:
                    # No detener la publicación por errores DIAN
                    record.message_post(
                        body=_("Error enviando a DIAN: %s") % str(e),
                        message_type='notification'
                    )
                    return rec
        return rec
    
    def button_draft(self):
        """Establece la factura en borrador"""
        for record in self:
            if record.state_dian_document == "exitoso" and \
               not self.env.user.has_group('l10n_co_e-invoice.group_validation_invoice'):
                raise UserError(
                    _("No se puede establecer en borrador un documento ya validado por DIAN")
                )
        return super(AccountMove, self).button_draft()
    
    def button_cancel(self):
        """Cancela la factura"""
        if self.state_dian_document == "exitoso":
            raise UserError(_("Una factura en estado exitoso no puede ser cancelada"))
        return super(AccountMove, self).button_cancel()
    
    # =============================================================================
    # SECCIÓN: GENERACIÓN XML DIAN - MÉTODO PRINCIPAL
    # =============================================================================
    
    def generate_dian_xml(self):
        """
        Método principal para generar XML DIAN usando templates QWeb
        Recolecta todos los datos en un diccionario único y genera el XML
        """
        self.ensure_one()

        try:
            _logger.info(f"Iniciando generación XML DIAN para {self.name}")

            # Recolectar todos los datos necesarios
            data = self._collect_all_dian_data()

            # Adaptar datos para el formato esperado por el template
            template_data = self._prepare_template_data(data)

            # Seleccionar el template correcto según el tipo de documento
            template_id = self._get_dian_template_id()

            # Generar XML usando el template QWeb
            xml_string = self.env['ir.qweb']._render(template_id, template_data)

            # Guardar archivos generados
            self._save_dian_files(xml_string, data)

            _logger.info(f"XML DIAN generado exitosamente para {self.name}")
            return xml_string

        except Exception as e:
            _logger.error(f"Error generando XML DIAN para {self.name}: {str(e)}", exc_info=True)
            raise ValidationError(_(f"Error al generar XML: {str(e)}"))

    def _prepare_template_data(self, data):
        """
        Mapea TODOS los datos recolectados a los nombres esperados por el template
        """
        # Copiar todos los datos originales
        template_data = dict(data)

        # Mapear nombres específicos que el template espera
        template_data.update({
            # === DATOS DEL DOCUMENTO ===
            'InvoiceID': data.get('InvoiceID', self.name),
            'UUID': data.get('UUID', ''),
            'IssueDate': data.get('fecha_xml_date', ''),
            'IssueTime': data.get('fecha_xml_time', ''),
            'InvoiceTypeCode': data.get('InvoiceTypeCode', '01'),
            'Notes': data.get('Notes', ''),
            'CurrencyID': data.get('CurrencyID', 'COP'),
            'LineCountNumeric': data.get('LineCountNumeric', len(data.get('invoice_lines', []))),

            # === VERSIONES Y PERFILES ===
            'UBLVersionID': data.get('UBLVersionID', 'UBL 2.1'),
            'CustomizationID': data.get('CustomizationID', '10'),
            'ProfileID': data.get('ProfileID', 'DIAN 2.1'),
            'ProfileExecutionID': data.get('ProfileExecutionID', '2'),

            # === DATOS DEL SOFTWARE Y PROVEEDOR ===
            'IdentificationCode': data.get('company_country_code', 'CO'),
            'SupplierCountry': data.get('company_country_code', 'CO'),  # Para InvoiceSource
            'SoftwareProviderID': data.get('ProviderID', ''),
            'SoftwareProviderSchemeID': data.get('SupplierSchemeIDCode', ''),
            'SoftwareProviderDV': data.get('SupplierSchemeIDCode', ''),  # DV para schemeID
            'SupplierSchemeIDCode': data.get('SupplierSchemeIDCode', '31'),  # Para la condición
            'SoftwareID': data.get('SoftwareID', ''),
            'SoftwareSecurityCode': data.get('SoftwareSecurityCode', ''),
            'ProviderID': data.get('ProviderID', ''),
            'schemeID': data.get('SupplierSchemeIDCode', ''),

            # === DATOS PARA AUTORIZACIÓN ===
            'InvoiceAuthorization': data.get('InvoiceAuthorization', ''),
            'StartDate': data.get('StartDate', ''),
            'EndDate': data.get('EndDate', ''),
            'Prefix': data.get('Prefix', ''),
            'From': data.get('From', ''),
            'To': data.get('To', ''),

            # === DATOS PARA QR ===
            'IDAdquiriente': data.get('CustomerID', ''),
            'URLQRCode': data.get('qr_url', 'https://catalogo-vpfe.dian.gov.co/document/searchqr?documentkey'),
            'QRCode': data.get('QRCode', ''),  # Contenido completo del QR

            # === MONTOS TOTALES ===
            'PayableAmount': data.get('PayableAmount', '0.00'),
            'TotalLineExtensionAmount': data.get('line_extension_amount', '0.00'),
            'TotalTaxExclusiveAmount': data.get('tax_exclusive_amount', '0.00'),
            'TotalTaxInclusiveAmount': data.get('tax_inclusive_amount', '0.00'),
            'AllowanceTotalAmount': data.get('discount_amount', '0.00'),
            'PrepaidAmount': data.get('prepaid_amount', '0.00'),

            # === SUPPLIER (PROVEEDOR) ===
            'SupplierAdditionalAccountID': data.get('SupplierAdditionalAccountID', ''),
            'IndustryClassificationCode': data.get('SupplierIndustryClassificationCode', ''),
            'SupplierPartyName': data.get('SupplierPartyName', ''),
            'SupplierCityCode': data.get('SupplierCityCode', ''),
            'SupplierCityName': data.get('SupplierCityName', ''),
            'SupplierCountrySubentity': data.get('SupplierCountrySubentity', ''),
            'SupplierCountrySubentityCode': data.get('SupplierCountrySubentityCode', ''),
            'SupplierLine': data.get('SupplierAddressLine', ''),
            'SupplierCountryCode': data.get('SupplierCountryCode', 'CO'),
            'SupplierCountryName': data.get('SupplierCountryName', 'Colombia'),
            'SupplierTaxLevelCode': data.get('SupplierTaxLevelCode', ''),
            'SupplierSchemeID': data.get('SupplierSchemeID', ''),
            'SupplierID': data.get('SupplierID', ''),
            'SupplierEmail': data.get('SupplierEmail', ''),
            'SupplierElectronicMail': data.get('SupplierEmail', ''),
            'SupplierPhone': data.get('SupplierPhone', ''),

            # === CUSTOMER (CLIENTE) ===
            'CustomerAdditionalAccountID': data.get('CustomerAdditionalAccountID', ''),
            'CustomerPartyName': data.get('CustomerPartyName', ''),
            'CustomerCityCode': data.get('CustomerCityCode', ''),
            'CustomerCityName': data.get('CustomerCityName', ''),
            'CustomerCountrySubentity': data.get('CustomerCountrySubentity', ''),
            'CustomerCountrySubentityCode': data.get('CustomerCountrySubentityCode', ''),
            'CustomerLine': data.get('CustomerLine', ''),
            'CustomerCountryCode': data.get('CustomerCountryCode', 'CO'),
            'CustomerCountryName': data.get('CustomerCountryName', 'Colombia'),
            'CustomerTaxLevelCode': data.get('CustomerTaxLevelCode', ''),
            'CustomerSchemeID': data.get('CustomerSchemeID', ''),
            'CustomerschemeID': data.get('CustomerDV', ''),  # DV del cliente para el template
            'CustomerID': data.get('CustomerID', ''),
            'CustomerEmail': data.get('CustomerEmail', ''),
            'CustomerPhone': data.get('CustomerPhone', ''),
            'CustomerTaxSchemeID': data.get('CustomerTaxSchemeID', '01'),
            'CustomerTaxSchemeName': data.get('CustomerTaxSchemeName', 'IVA'),
            'CustomerElectronicMail': data.get('CustomerEmail', ''),
            'Firstname': data.get('CustomerFirstName', ''),
            'SchemeIDAdquiriente': data.get('CustomerSchemeID', ''),
            'SchemeNameAdquiriente': data.get('CustomerSchemeName', '31'),
            'IDAdquiriente': data.get('CustomerID', ''),

            # === IMPUESTOS ===
            'TaxSchemeID': data.get('TaxSchemeID', '01'),
            'TaxSchemeName': data.get('TaxSchemeName', 'IVA'),
            'tax_total_values': data.get('tax_total_values', {}),
            'ret_total_values': data.get('ret_total_values', {}),

            # === PAGO ===
            'PaymentMeansID': data.get('PaymentMeansID', '1'),
            'PaymentMeansCode': data.get('PaymentMeansCode', '10'),
            'PaymentDueDate': data.get('PaymentDueDate', ''),

            # === MANDANTE (si existe) ===
            'mandate_identification': data.get('mandate_id', ''),

            # === MONEDA ===
            'source_currency_name': data.get('CurrencyID', 'COP'),
            'CalculationRate': data.get('exchange_rate', '1.00'),
            'SourceCurrencyCode': data.get('source_currency_code', 'COP'),
            'TargetCurrencyCode': data.get('target_currency_code', 'COP'),

            # === Objeto del documento para referencias ===
            'document_id': self,
        })

        # === MAPEAR LÍNEAS DE LA FACTURA ===
        if 'invoice_lines' in data:
            mapped_lines = []
            for line in data['invoice_lines']:
                mapped_line = self._map_invoice_line(line)
                mapped_lines.append(mapped_line)
            template_data['invoice_lines'] = mapped_lines

        return template_data

    def _prepare_signature_data(self):
        """
        Prepara los datos necesarios para el nodo de firma digital en el XML.

        Returns:
            dict: Diccionario con las variables para la firma
        """
        import uuid
        import hashlib
        from datetime import datetime
        from pytz import timezone
        from base64 import b64encode
        from cryptography.hazmat.primitives.serialization import Encoding

        self.ensure_one()

        try:
            # Obtener certificado
            private_key, cert = self.get_key()

            # Generar IDs únicos para la firma
            signature_id = f"xmldsig-{str(uuid.uuid4())}"
            key_info_id = f"xmldsig-{str(uuid.uuid4())}-keyinfo"

            # Obtener información del certificado
            cert_der = cert.public_bytes(Encoding.DER)
            cert_digest = b64encode(hashlib.sha256(cert_der).digest()).decode()
            x509_certificate = b64encode(cert_der).decode()

            # Información del emisor del certificado
            x509_issuer_name = cert.issuer.rfc4514_string()
            x509_serial_number = str(cert.serial_number)

            # Tiempo de firma en zona horaria de Colombia
            bogota_tz = timezone('America/Bogota')
            signing_time = datetime.now(bogota_tz).isoformat()

            return {
                'signature_id': signature_id,
                'key_info_id': key_info_id,
                'signing_time': signing_time,
                'x509_certificate': x509_certificate,
                'cert_digest': cert_digest,
                'x509_issuer_name': x509_issuer_name,
                'x509_serial_number': x509_serial_number,
            }

        except Exception as e:
            _logger.error(f"Error preparando datos de firma: {str(e)}")
            # Devolver valores por defecto si hay error
            return {
                'signature_id': f"xmldsig-{str(uuid.uuid4())}",
                'key_info_id': f"xmldsig-{str(uuid.uuid4())}-keyinfo",
                'signing_time': datetime.now().isoformat(),
                'x509_certificate': '',
                'cert_digest': '',
                'x509_issuer_name': '',
                'x509_serial_number': '',
            }

    def _map_invoice_line(self, line):
        """
        Mapea una línea de factura a los nombres esperados por el template
        """
        # El template espera estos campos para cada línea
        return {
            # Identificación de línea
            'id': line.get('id', 1),
            'note': line.get('note', line.get('name', '')),

            # Cantidades
            'invoiced_quantity': line.get('quantity', 1),
            'uom_product_id': line.get('uom', None),  # El objeto UoM completo

            # Montos
            'line_extension_amount': line.get('line_extension_amount', 0),
            'price': line.get('price_unit', 0),
            'discount': line.get('discount', 0),
            'discount_percentage': line.get('discount_percentage', 0),
            'discount_code': line.get('discount_code', '00'),
            'discount_text': line.get('discount_text', 'Descuento no condicionado'),

            # Referencias de precio (muestras comerciales)
            'line_price_reference': line.get('line_price_reference', 0),
            'line_trade_sample_price': line.get('line_trade_sample_price', '01'),

            # Impuestos (mantener estructura original)
            'tax_info': line.get('tax_info', {}),
            'ret_info': line.get('ret_info', {}),

            # Información del producto
            'product_id': line.get('product_id', None),  # El objeto producto completo
            'item_description': line.get('name', ''),

            # Códigos estándar del producto
            'StandardItemIdentificationID': line.get('StandardItemIdentificationID', ''),
            'StandardItemIdentificationschemeID': line.get('StandardItemIdentificationschemeID', '999'),
            'StandardItemIdentificationschemeAgencyID': line.get('StandardItemIdentificationschemeAgencyID', '10'),
            'StandardItemIdentificationschemeName': line.get('StandardItemIdentificationschemeName', 'Estándar de adopción del contribuyente'),
        }

    def _get_dian_template_id(self):
        """
        Retorna el ID del template según el tipo de documento
        """
        self.ensure_one()

        if self.move_type == 'out_invoice':
            if self.is_debit_note:
                return 'l10n_co_e-invoice.nota_debito'
            else:
                return 'l10n_co_e-invoice.electronic_invoice_template'
        elif self.move_type == 'out_refund':
            return 'l10n_co_e-invoice.nota_credito'
        elif self.move_type == 'in_invoice':
            return 'l10n_co_e-invoice.bill_ds_template'
        elif self.move_type == 'in_refund':
            return 'l10n_co_e-invoice.credit_note_ds_template'
        else:
            raise ValidationError(f"Tipo de documento no soportado: {self.move_type}")

    # =============================================================================
    # SECCIÓN: RECOLECCIÓN DE DATOS - DICCIONARIO ÚNICO
    # =============================================================================

    def _collect_all_dian_data(self):
        """
        Recolecta TODOS los datos necesarios en un único diccionario
        Minimiza las consultas a la base de datos
        """
        # Configurar timezone Colombia
        tz_co = timezone('America/Bogota')
        now_co = datetime.now(tz=tz_co)
        
        # Establecer fechas
        self.fecha_xml = fields.Datetime.to_string(datetime.now(tz=timezone('America/Bogota')))
        self.fecha_entrega = fields.Datetime.to_string(datetime.now(tz=timezone('America/Bogota')))
        
        # Inicializar diccionario principal
        data = {
            # Metadatos del documento
            'move': self,
            'document_type': self._get_dian_document_type(),
            'move_type': self.move_type,
            'is_debit_note': self.is_debit_note,
            'document_number': self.name,
            
            # Fechas
            'current_datetime': now_co,
            'fecha_xml': self.fecha_xml,
            'fecha_xml_str': self.fecha_xml.strftime('%Y-%m-%dT%H:%M:%S-05:00'),
            'fecha_xml_date': self.fecha_xml.date().isoformat(),
            'fecha_xml_time': self.fecha_xml.strftime("%H:%M:%S-05:00"),
            'fecha_entrega': self.fecha_entrega,
            
            # Moneda y tasas
            'currency_id': self.company_id.currency_id.name,
            'exchange_rate': self.current_exchange_rate if self.currency_id.name != 'COP' else 1.0,
            'is_foreign_currency': self.currency_id.name != 'COP',
            
            # Entidades principales
            'company': self.company_id,
            'company_partner': self.company_id.partner_id,
            'partner': self.partner_id,
            
            # Contingencia
            'in_contingency_4': self.in_contingency_4,
            'contingency_4': self.contingency_4,
        }
        
        # Recolectar datos por secciones
        data.update(self._collect_resolution_data())
        data.update(self._get_dian_constants())
        data.update(self._collect_parties_data())
        data.update(self._collect_contact_data())
        data.update(self._collect_technical_data())
        data.update(self._collect_document_data())
        data.update(self._collect_reference_data())
        data.update(self._collect_delivery_data())
        data.update(self._collect_payment_data())
        data.update(self._collect_prepaid_payments_data())
        
        # Procesar líneas e impuestos
        lines_tax_data = self._process_lines_and_taxes()
        data.update(lines_tax_data)
        
        # Calcular totales
        totals_data = self._calculate_totals(data)
        data.update(totals_data)
        
        # Generar códigos de seguridad
        security_data = self._generate_security_codes(data)
        data.update(security_data)
        
        # Hook para extensiones
        data = self._extend_dian_data(data)
        
        return data

    def _get_dian_constants(self):
        company = self.company_id
        # Obtener el digest del certificado usando el nuevo método
        cert_digest_value = ''
        try:
            cert = company._get_certificate()
            cert_der = cert.public_bytes(encoding=serialization.Encoding.DER)
            digest = hashes.Hash(hashes.SHA256())
            digest.update(cert_der)
            cert_digest = digest.finalize()
            cert_digest_value = base64.b64encode(cert_digest).decode()
        except:
            cert_digest_value = ''

        dian_constants = {
            'CertDigestDigestValue': cert_digest_value,
            'IssuerName':  company.issuer_name,
            'SerialNumber': company.serial_number,
            'FileNameXML': self._generate_xml_filename(),
            'FileNameZIP' : self._generate_zip_filename(),
            'archivo_pem': company.pem,
            'archivo_certificado': company.certificate,
            'URLQRCode': self._get_url_qr_code(company),
        }
        return dian_constants
    
    def _get_url_qr_code(self, company):
        """Obtiene la URL base del código QR"""
        if company.production:
            return 'https://catalogo-vpfe.dian.gov.co/document/searchqr?documentkey'
        else:
            return 'https://catalogo-vpfe-hab.dian.gov.co/document/searchqr?documentkey'

    @api.model
    def _generate_xml_filename(self):
        doctype = self.move_type
        is_debit_note = self.is_debit_note
        NitSinDV = self.company_id.partner_id.vat_co
        docdian = ''
        if doctype == "out_invoice" and not is_debit_note:
            docdian = "fv"
        elif doctype == "out_refund":
            docdian = "nc"
        elif doctype == "out_invoice" and is_debit_note:
            docdian = "nd"
        elif doctype == "in_invoice":
            docdian = "ds"
        dian_code_hex = self.IntToHex(self.sequence_number)
        dian_code_hex.zfill(10)
        # TODO: Revisar el secuenciador segun la norma
        file_name_xml = docdian + NitSinDV.zfill(10) + dian_code_hex.zfill(10) + ".xml"
        return file_name_xml

    def IntToHex(self, dian_code_int):
        dian_code_hex = "%02x" % dian_code_int
        return dian_code_hex

    def _generate_zip_filename(self):
        doctype = self.move_type
        is_debit_note = self.is_debit_note
        NitSinDV = self.company_id.partner_id.vat_co
        docdian = ''
        if doctype == "out_invoice" and not is_debit_note:
            docdian = "fv"
        elif doctype == "out_refund":
            docdian = "nc"
        elif doctype == "out_invoice" and is_debit_note:
            docdian = "nd"
        elif doctype == "in_invoice":
            docdian = "ds"
        dian_code_hex = self.IntToHex(self.sequence_number)
        dian_code_hex.zfill(10)
        file_name_zip = docdian + NitSinDV.zfill(10) + dian_code_hex.zfill(10) + ".zip"
        return file_name_zip
    
    # -------------------------------------------------------------------------
    # Recolección: Resolución
    # -------------------------------------------------------------------------
    
    def _collect_resolution_data(self):
        """Recolecta datos de resolución DIAN"""
        resolution = self.journal_id.sequence_id.dian_resolution_ids.filtered(
            lambda r: r.active_resolution
        )
        
        if not resolution:
            raise UserError(_("No hay resolución DIAN activa para el diario %s") % self.journal_id.name)
        
        if not resolution.technical_key:
            raise UserError(_("La resolución DIAN no tiene clave técnica"))
        
        # Determinar prefijo según tipo de documento
        prefix = resolution.sequence_id.prefix or ''
        if self.move_type in ['out_refund', 'in_refund']:
            prefix = ''  # Las notas crédito no usan prefijo según DIAN
        if self.is_debit_note:
            prefix = self.journal_id.debit_note_sequence_id.prefix

        return {
            'resolution': resolution,
            'InvoiceAuthorization': resolution.resolution_number,
            'StartDate': str(resolution.date_from),
            'EndDate': str(resolution.date_to),
            'Prefix': prefix,
            'From': str(resolution.number_from),
            'To': str(resolution.number_to),
            'InvoiceID': self.name,
            'TechnicalKey': resolution.technical_key,
            'ContingencyID': self.contingency_invoice_number if self.contingency_4 else '',
        }
    
    # -------------------------------------------------------------------------
    # Recolección: Partes (Supplier/Customer)
    # -------------------------------------------------------------------------
    
    def _collect_parties_data(self):
        """Recolecta datos de las partes"""
        # Determinar roles según tipo de documento
        if self.move_type in ['out_invoice', 'out_refund'] or self.is_debit_note:
            supplier = self.company_id.partner_id
            customer = self.partner_id
        else:
            supplier = self.partner_id
            customer = self.company_id.partner_id
        
        data = {
            'supplier': supplier,
            'customer': customer,
        }
        
        # Recolectar datos del proveedor
        data.update(self._get_party_data(supplier, 'Supplier'))
        
        # Recolectar datos del cliente
        data.update(self._get_party_data(customer, 'Customer'))
        
        # Manejo especial para documentos de compra con tipo identificación 13
        if self.move_type in ['in_invoice', 'in_refund'] and supplier.l10n_latam_identification_type_id.dian_code == '13':
            data['SupplierSchemeIDCode'] = '31'
        
        return data
    
    def _get_party_data(self, partner, prefix):
        """Obtiene todos los datos de una parte"""
        if not partner:
            return {}
        
        # Esquema de identificación
        if partner.l10n_latam_identification_type_id.dian_code == '31':
            scheme_id = partner.dv
            scheme_name = '31'
        elif partner.l10n_latam_identification_type_id.dian_code == '13' and self.move_type in ['in_invoice', 'in_refund'] and prefix == 'Supplier':
            scheme_id = partner.dv 
            scheme_name = '31'
        else:
            scheme_id = ''
            scheme_name = partner.l10n_latam_identification_type_id.dian_code
        
        # Régimen fiscal
        # if partner.dian_fiscal_regimen == '48':
        #     tax_scheme_id = '01'
        #     tax_scheme_name = 'IVA'
        # elif partner.dian_fiscal_regimen == '49':
        #     tax_scheme_id = 'ZZ'
        #     tax_scheme_name = 'No aplica *'
        # else:
        tax_scheme_id = partner.tribute_id.code #partner.dian_fiscal_regimen or '01'
        tax_scheme_name = partner.tribute_id.name # dict(partner._fields.get("dian_fiscal_regimen", {}).selection or []).get(
            #     partner.dian_fiscal_regimen, 'IVA'
            # )
        
        # Responsabilidades fiscales
        fiscal_resp = ';'.join(
            partner.fiscal_responsability_ids.mapped('code')
        ) if partner.fiscal_responsability_ids else 'R-99-PN'
        
        return {
            # Identificación
            f'{prefix}ID': partner.vat_co or '',
            f'{prefix}DV': partner.dv,
            f'{prefix}SchemeID': scheme_id,
            f'{prefix}SchemeName': scheme_name,
            f'{prefix}SchemeIDCode': partner.l10n_latam_identification_type_id.dian_code,
            
            # Nombres
            f'{prefix}Name': self._escape_xml(partner.name),
            f'{prefix}CommercialName': self._escape_xml(partner.business_name or partner.name),
            f'{prefix}RegistrationName': self._escape_xml(partner.name),
            f'{prefix}FirstName': self._escape_xml(partner.firs_name or partner.name),
            f'{prefix}AdditionalAccountID': '1' if partner.is_company else '2',
            
            # Ubicación
            f'{prefix}AddressID': partner.city_id.code if partner.city_id else '',
            f'{prefix}CityCode': partner.city_id.code if partner.city_id else '',
            f'{prefix}CityName': partner.city_id.name.title() if partner.city_id else partner.city or '',
            f'{prefix}PostalZone': partner.zip or '',
            f'{prefix}DepartmentCode': partner.state_id.code_dian if partner.state_id else '',
            f'{prefix}DepartmentName': partner.state_id.name if partner.state_id else '',
            f'{prefix}CountrySubentity': partner.state_id.name if partner.state_id else '',
            f'{prefix}CountrySubentityCode': partner.state_id.code_dian if partner.state_id else '',
            f'{prefix}AddressLine': partner.street or '',
            f'{prefix}Country': partner.country_id.code if partner.country_id else 'CO',
            f'{prefix}CountryName': partner.country_id.name if partner.country_id else 'Colombia',
            
            # Fiscal
            f'{prefix}TaxLevelCode': fiscal_resp,
            f'{prefix}TaxSchemeID': tax_scheme_id,
            f'{prefix}TaxSchemeName': tax_scheme_name,
            
            # Contacto
            f'{prefix}Telephone': partner.phone or partner.mobile or '',
            f'{prefix}Email': partner.email or '',
            
            # Actividad económica
            f'{prefix}IndustryClassificationCode': partner.ciiu_activity.code if partner.ciiu_activity else '',
        }
    
    # -------------------------------------------------------------------------
    # Recolección: Contactos
    # -------------------------------------------------------------------------
    
    def _collect_contact_data(self):
        """Recolecta datos de contactos específicos"""
        data = {}
        
        # Contacto del documento
        if self.partner_contact_id:
            contact = self.partner_contact_id
        else:
            # Buscar contacto tipo 'other'
            addr = self.partner_id.address_get(['other'])
            contact = self.env['res.partner'].browse(addr['other']) if addr.get('other') else self.partner_id
        
        data.update({
            'ContactName': contact.name or '',
            'ContactTelephone': contact.phone or contact.mobile or '',
            'ContactElectronicMail': contact.email or '',
        })
        
        return data
    
    # -------------------------------------------------------------------------
    # Recolección: Datos Técnicos
    # -------------------------------------------------------------------------
    
    def _collect_technical_data(self):
        """Recolecta datos técnicos y de software"""
        company = self.company_id
        
        # Software
        software_id = company.software_identification_code
        software_pin = company.software_pin
        
        # Generar software security code
        software_security_code = self._generate_software_security_code(
            software_id, software_pin, self.name
        )
        
        return {
            'SoftwareID': software_id,
            'SoftwarePin': software_pin,
            'SoftwareSecurityCode': software_security_code,
            'SoftwareProviderID': company.partner_id.vat_co or '',
            'SoftwareProviderDV': company.partner_id.dv,
            
            # Certificados
            'Certificate': company.digital_certificate,
            'CertificateKey': company.certificate_key,
            'IssuerName': company.issuer_name or '',
            'SerialNumber': company.serial_number or '',
            
            # Ambiente
            'ProfileExecutionID': AMBIENTE_MAPPING["PRODUCCION"] if company.production else AMBIENTE_MAPPING["PRUEBA"],
            'TestSetID': company.identificador_set_pruebas if not company.production else '',
            
            # Identificadores
            'identifier': str(uuid.uuid4()),
            'identifierkeyinfo': str(uuid.uuid4()),
            
            # URLs
            'document_repository': company.document_repository or '',
            'seed_code': company.seed_code or '',
        }
    
    # -------------------------------------------------------------------------
    # Recolección: Datos del Documento
    # -------------------------------------------------------------------------
    
    def _collect_document_data(self):
        """Recolecta datos específicos del documento"""
        # Tipo de documento
        doc_type_info = DOCUMENT_TYPES.get(self.move_type, {})
        if self.is_debit_note:
            doc_type_info = DOCUMENT_TYPES.get('debit_note', {})
        elif self.fe_type == '02':
            doc_type_info = DOCUMENT_TYPES.get('export_invoice', {})
        # Customization ID
        customization_id = '10' 
        if self.move_type == 'out_refund':
            customization_id = '22' if self.document_without_reference else '20'
        elif self.is_debit_note:
            # Para notas débito
            customization_id = '32' if self.document_without_reference else '30'
        elif self.fe_operation_type == '09':
            customization_id = '09' 
        elif self.fe_operation_type == '11':
            customization_id = '11' 
        elif self.move_type in ('in_invoice', 'in_refund'):
            if self.partner_id.type_residence == "si":
                customization_id =  '10'
            elif self.partner_id.type_residence == "no":
                customization_id =  '11'
            else:
                raise ValidationError('El proveedor {0} no tiene la informacion de residencia en su formulario'.format(self.document_id.partner_id.name))
        else:
            customization_id = self.fe_operation_type

        # Profile ID
        profile_id = 'DIAN 2.1'
        if self.move_type == "out_invoice" and not self.is_debit_note:
            profile_id = "DIAN 2.1: Factura Electrónica de Venta"
        elif self.is_debit_note:
            profile_id = "DIAN 2.1: Nota Débito de Factura Electrónica de Venta"
        elif self.move_type == 'out_refund':
            profile_id = "DIAN 2.1: Nota Crédito de Factura Electrónica de Venta"
        elif self.move_type == 'in_invoice' and self.is_debit_note == False:
            profile_id = "DIAN 2.1: documento soporte en adquisiciones efectuadas a no obligados a facturar."
        elif self.move_type == 'in_invoice' and self.is_debit_note or self.debit_origin_id:
            raise UserError('Los documentos Soporte No tiene Nota Debito Habilitadas para su emisión a la DIAN, Por Favor Emitir Otro documento Soporte')
        elif self.move_type == 'in_refund':
            profile_id = "DIAN 2.1: Nota de ajuste al documento soporte en adquisiciones efectuadas a sujetos no obligados a expedir factura o documento equivalente"
        
        # Contar líneas válidas - EXCLUIR LÍNEAS DE CARGO
        valid_lines = self.invoice_line_ids.filtered(
            lambda l: l.display_type == 'product' and 
                     not l.product_id.enable_charges and
                     l.price_subtotal != 0.00
        )
        
        data = {
            'document_type_info': doc_type_info,
            'document_tag': doc_type_info.get('tag', 'Invoice'),
            'document_code': doc_type_info.get('code', '01'),
            'UBLVersionID': 'UBL 2.1',
            'CustomizationID': customization_id,
            'ProfileID': profile_id,
            'LineCountNumeric': len(valid_lines),
            'Notes': self.narration or '',
            'has_invoice_period': bool(self.date_from and self.date_to),
            'invoice_period_start': str(self.date_from) if self.date_from else '',
            'invoice_period_end': str(self.date_to) if self.date_to else '',
        }
        
        return data
    
    # -------------------------------------------------------------------------
    # Recolección: Referencias
    # -------------------------------------------------------------------------
    
    def _collect_reference_data(self):
        """Recolecta datos de referencias para notas"""
        data = {}
        
        # Solo para notas crédito/débito
        if self.move_type in ['out_refund', 'in_refund'] or self.is_debit_note:
            # Documento referenciado
            ref_doc = None
            if self.is_debit_note and self.debit_origin_id:
                ref_doc = self.debit_origin_id
            elif self.reversed_entry_id:
                ref_doc = self.reversed_entry_id
            
            if ref_doc and not self.document_without_reference:
                data.update({
                    'has_reference': True,
                    'InvoiceReferenceID': ref_doc.name,
                    'InvoiceReferenceUUID': ref_doc.cufe or '',
                    'InvoiceReferenceDate': str(ref_doc.invoice_date),
                    'InvoiceReferenceScheme': SCHEME_MAPPING.get(ref_doc.move_type if not self.is_debit_note else 'debit_note', 'CUFE-SHA384'),
                })
            elif self.document_without_reference:
                data.update({
                    'has_reference': False,
                    'InvoiceReferenceID': '',
                    'InvoiceReferenceDate': str(self.invoice_date),
                })
            elif self.document_from_other_system and self.cufe_cuds_other_system:
                data.update({
                    'has_reference': True,
                    'InvoiceReferenceID': self.document_from_other_system,
                    'InvoiceReferenceUUID': self.cufe_cuds_other_system,
                    'InvoiceReferenceDate': str(self.date_from_other_system),
                })
            
            # Concepto
            if self.is_debit_note:
                data.update({
                    'ResponseCode': self.concept_debit_note or '1',
                    'ResponseDescription': dict(
                        self._fields['concept_debit_note'].selection
                    ).get(self.concept_debit_note, 'Otros'),
                })
            else:
                data.update({
                    'ResponseCode': self.concepto_credit_note or '1',
                    'ResponseDescription': dict(
                        self._fields['concepto_credit_note'].selection
                    ).get(self.concepto_credit_note, 'Devolución parcial'),
                })
        
        # Referencias adicionales
        data.update(self._collect_additional_references())
        
        return data
    
    def _collect_additional_references(self):
        """Recolecta referencias de órdenes y despachos"""
        data = {
            'order_references': [],
            'despatch_references': [],
        }
        
        # Órdenes de compra/venta
        if self.invoice_origin:
            for ref in self.invoice_origin.split(','):
                ref = ref.strip()
                if ref:
                    data['order_references'].append({
                        'ID': ref,
                        'IssueDate': '',
                    })
        
        # Despachos desde líneas de venta
        if self.invoice_line_ids:
            sale_lines = self.invoice_line_ids.mapped('sale_line_ids')
            if sale_lines:
                picking_ids = sale_lines.mapped('order_id.picking_ids')
                picking_ids = picking_ids.filtered(lambda p: p.state == 'done')[:5]  # Máximo 5
                
                for picking in picking_ids:
                    data['despatch_references'].append({
                        'ID': picking.name,
                        'IssueDate': str(picking.date_done.date()) if picking.date_done else '',
                    })
        
        return data
    
    # -------------------------------------------------------------------------
    # Recolección: Entrega
    # -------------------------------------------------------------------------
    
    def _collect_delivery_data(self):
        """Recolecta datos de entrega"""
        data = {'has_delivery': False}
        
        if self.partner_shipping_id and self.partner_shipping_id != self.partner_id:
            partner = self.partner_shipping_id
            data.update({
                'has_delivery': True,
                'DeliveryAddress': partner.street or '',
                'DeliveryCityCode': partner.city_id.code if partner.city_id else '',
                'DeliveryCityName': partner.city_id.name.title() if partner.city_id else '',
                'DeliveryDepartmentCode': partner.state_id.code_dian if partner.state_id else '',
                'DeliveryDepartmentName': partner.state_id.name if partner.state_id else '',
                'DeliveryCountrySubentity': partner.state_id.name if partner.state_id else '',
                'DeliveryCountrySubentityCode': partner.state_id.code_dian if partner.state_id else '',
                'DeliveryAddressLine': partner.street or '',
                'DeliveryCountryCode': partner.country_id.code if partner.country_id else 'CO',
                'DeliveryCountryName': partner.country_id.name if partner.country_id else 'Colombia',
                'DeliveryPartyName': partner.name,
            })
            
            # if self.delivery_date:
            #     data['DeliveryDate'] = str(self.delivery_date)
        
        return data
    
    # -------------------------------------------------------------------------
    # Recolección: Pago
    # -------------------------------------------------------------------------
    
    def _collect_payment_data(self):
        """Recolecta datos de pago"""
        data = {
            'PaymentMeansID': '1',
            'PaymentMeansCode': '1',
            'PaymentDueDate': str(self.invoice_date_due or self.invoice_date),
            'PaymentReference': self.payment_reference or self.ref or self.name,
        }
        
        # Determinar si es crédito
        if self.invoice_date_due and self.invoice_date_due > self.invoice_date:
            data.update({
                'PaymentMeansID': '2',
                'PaymentMeansCode': '2',
            })
        
        # Método de pago específico
        if self.method_payment_id:
            data['PaymentMeansCode'] = self.method_payment_id.code
        
        # Términos de pago
        if self.invoice_payment_term_id:
            data['PaymentTermsNote'] = self.invoice_payment_term_id.name
        
        # Cuenta bancaria
        if self.company_id.partner_id.bank_ids:
            bank = self.company_id.partner_id.bank_ids[0]
            data.update({
                'PayeeAccountID': bank.acc_number,
                'PayeeBankID': bank.bank_id.bic if bank.bank_id else '',
            })
        
        # Tasa de cambio
        if self.currency_id.name != 'COP':
            data.update({
                'has_exchange_rate': True,
                'SourceCurrencyCode': 'COP',
                'TargetCurrencyCode': self.currency_id.name,
                'CalculationRate': f"{self.current_exchange_rate:.6f}",
                'ExchangeDate': str(self.invoice_date),
            })
        
        return data
    
    # -------------------------------------------------------------------------
    # Recolección: Prepaid Payments
    # -------------------------------------------------------------------------
    
    def _collect_prepaid_payments_data(self):
        """Recolecta datos de pagos anticipados"""
        data = {
            'prepaid_payments': []
        }
        
        if hasattr(self, 'prepaid_payments_ids') and self.prepaid_payments_ids:
            for idx, payment in enumerate(self.prepaid_payments_ids):
                data['prepaid_payments'].append({
                    'id': str(idx + 1),
                    'amount': payment.amount_total,
                    'received_date': str(payment.invoice_date),
                    'paid_date': str(payment.invoice_date),
                })
        
        return data
    
    # =============================================================================
    # SECCIÓN: PROCESAMIENTO DE LÍNEAS E IMPUESTOS
    # =============================================================================
    
    def _process_lines_and_taxes(self):
        """Procesa todas las líneas y calcula impuestos usando los nuevos métodos"""
        data = {
            'invoice_lines': [],
            'tax_total_values': {},
            'ret_total_values': {},
            'line_extension_amount': 0.0,
            'line_excluded_amount': 0.0,
            'total_discount_amount': 0.0,
            'total_charge_amount': 0.0,
            'total_tax_amount': 0.0,
            'total_withholding_amount': 0.0,
        }

        # Tasa de cambio
        rate = self.current_exchange_rate if self.currency_id.name != 'COP' else 1.0
        is_purchase = self.move_type in ['in_invoice', 'in_refund']

        # Mantener la lógica de filtrado de líneas - IMPORTANTE
        distributable_discount_lines = self.invoice_line_ids.filtered(
            lambda l: l.display_type == 'product' and
                     l.product_id.enable_charges and
                     l.invoice_discount_text == '00' and
                     l.price_subtotal < 0
        )

        valid_lines = self.invoice_line_ids.filtered(
            lambda l: l.display_type == 'product' and
                     not l.product_id.enable_charges and
                     l.price_unit > 0 and
                     l.price_subtotal != 0.00
        )

        # Calcular descuento global si aplica
        global_discount_percentage = 0.0
        if distributable_discount_lines and valid_lines:
            subtotal_base = sum(abs(line._l10n_co_dian_net_price_subtotal()) for line in valid_lines)
            if subtotal_base > 0:
                total_discount_amount = sum(abs(line._l10n_co_dian_net_price_subtotal()) for line in distributable_discount_lines)
                global_discount_percentage = min((total_discount_amount / subtotal_base) * 100, 100.0)

                for line in valid_lines:
                    line.global_discount_percentage = global_discount_percentage

        # Usar los nuevos métodos para obtener totales de impuestos y retenciones
        tax_totals = self._get_tax_totals()
        retention_totals = self._get_retention_totals()

        # Convertir el formato de los nuevos métodos al formato esperado
        data['tax_total_values'] = tax_totals
        data['ret_total_values'] = retention_totals

        # Calcular totales generales de impuestos
        data['total_tax_amount'] = sum(tax_data.get('total', 0) for tax_data in tax_totals.values())
        data['total_withholding_amount'] = sum(ret_data.get('total', 0) for ret_data in retention_totals.values())

        # Procesar líneas para obtener información detallada
        for idx, line in enumerate(valid_lines, 1):
            line_data = self._process_single_line(line, idx, rate, is_purchase)
            data['invoice_lines'].append(line_data)

            # Acumular totales de línea
            data['line_extension_amount'] += line_data['line_extension_amount']
            data['total_discount_amount'] += line_data['discount']

            # Verificar si está excluida
            if line_data.get('is_excluded'):
                data['line_excluded_amount'] += line_data['line_extension_amount']

        # Procesar cargos y descuentos globales
        charge_data = self._process_global_charges(data['line_extension_amount'])
        data.update(charge_data)

        # Actualizar total de retenciones
        self.total_withholding_amount = data['total_withholding_amount']

        return data
    
    def _process_single_line(self, line, sequence, rate, is_purchase):
        global_discount_percentage = line.global_discount_percentage or 0.0
        
        base_original = line._l10n_co_dian_gross_price_subtotal()
        
        has_included_taxes = any(tax.price_include for tax in line.tax_ids)
        
        line_discount_percentage = line.discount or 0.0
        total_discount_percentage = min(line_discount_percentage + global_discount_percentage, 100.0)
        
        # Calcular montos de descuento
        line_discount_amount = base_original * (line_discount_percentage / 100)
        global_discount_amount = base_original * (global_discount_percentage / 100)
        total_discount_amount = base_original * (total_discount_percentage / 100)
        
        base_after_discounts = base_original - total_discount_amount
        

        taxes_computed = line.tax_ids.compute_all(
            base_after_discounts,
            currency=line.company_id.currency_id,
            quantity=1,
            product=line.product_id,
            partner=self.partner_id,
            handle_price_include=False,            
        )
        line_extension_amount = taxes_computed['total_excluded']
        
        # Verificar si está excluida
        is_excluded = any(
            tax.codigo_dian == '01' and any(t in tax.name.lower() for t in ['excluido', 'exc'])
            for tax in line.tax_ids
        )
        
        # Procesar impuestos
        tax_info = {}
        ret_info = {}
        line_tax_amount = 0.0
        line_retention_amount = 0.0
        
        for tax in line.tax_ids:
            if tax.tributes == 'ZZ':
                continue
            
            # Verificar si es excluido
            if tax.codigo_dian == '01' and any(t in tax.name.lower() for t in ['excluido', 'exc']):
                continue
            
            tax_code = tax.codigo_dian
            is_retention = tax.amount < 0
            
            # Validar retenciones en compras
            if is_purchase and is_retention and tax_code not in ['05', '06', '07']:
                continue
            
            tax_amount = sum(t['amount'] for t in taxes_computed['taxes'] if t['id'] == tax.id)
            tax_amount_cop = abs(tax_amount)
            
            tax_rate = abs(tax.amount)
            if tax_code == '07':  # ReteICA usa milésimas
                tax_rate = tax_rate / 1000
            
            rate_key = f"{tax_rate:.4f}" if tax_code == '07' else f"{tax_rate:.2f}"
            
            tax_data = {
                'taxable_amount': line_extension_amount,  # Base sin impuestos
                'value': tax_amount_cop,
                'technical_name': tax.nombre_dian,
                'rate': tax_rate,
                'amount_type': tax.amount_type,
                'price_include': tax.price_include,
            }
            
            if tax_code in ['32', '34']:  # ICL, IBUA
                tax_data = self._process_special_tax(tax_code, tax_data, line, taxes_computed)
            
            target = ret_info if is_retention else tax_info
            if tax_code not in target:
                target[tax_code] = {'total': 0.0, 'info': {}}
            
            if rate_key not in target[tax_code]['info']:
                target[tax_code]['info'][rate_key] = tax_data
            else:
                target[tax_code]['info'][rate_key]['value'] += tax_data['value']
                target[tax_code]['info'][rate_key]['taxable_amount'] += tax_data['taxable_amount']
            
            target[tax_code]['total'] += tax_amount_cop
            
            if is_retention:
                line_retention_amount += tax_amount_cop
            else:
                line_tax_amount += tax_amount_cop
        
        # Obtener código de descuento de la línea
        discount_code_value = line.invoice_discount_text or '00'
        

        price_unit = base_original / line.quantity if line.quantity else 0.0
        
        # Preparar datos de línea
        return {
            'id': sequence,
            'product_id': line.product_id,
            'name': self._escape_xml(line.name),
            'note': self._escape_xml(line.name),
            'quantity': line.quantity,
            'uom': line.product_uom_id,
            'price_unit': price_unit,
            'discount': total_discount_amount,
            'discount_percentage': total_discount_percentage,
            'line_extension_amount': line_extension_amount,
            'tax_info': tax_info,
            'ret_info': ret_info,
            'product_code': self._get_product_type_code(line),
            'invoice_line_id': line,
            'is_excluded': is_excluded,
            'line_tax_amount': line_tax_amount,
            'line_retention_amount': line_retention_amount,
            'taxes_computed': taxes_computed,
            'invoice_start_date': datetime.now().astimezone(timezone("America/Bogota")).strftime('%Y-%m-%d'),
            'transmission_type_code': 1,
            'transmission_description': 'Por operación',
            'discount_text': dict(line._fields['invoice_discount_text'].selection).get(discount_code_value),
            'discount_code': discount_code_value,
            'line_trade_sample_price': line.line_trade_sample_price * rate if line.line_trade_sample_price else '01',
            'line_price_reference': (line.line_price_reference * line.quantity) * rate if line.line_price_reference else 0,
            'StandardItemIdentificationID': self._get_product_type_code(line)[0],
            'StandardItemIdentificationschemeID': self._get_product_type_code(line)[1],
            'StandardItemIdentificationschemeAgencyID': self._get_product_type_code(line)[2],
            'StandardItemIdentificationschemeName': self._get_product_type_code(line)[3],
        }
    
    def _process_special_tax(self, tax_code, tax_data, line, taxes_computed):
        product = line.product_id
        aux_subtotal = 0
        base_unit_measure = 0
        unit_code = ''
        tax_amount = tax_data.get('value', 0) / line.quantity if line.quantity else 0
        differential_amount_cop = tax_amount
        differential_amount = differential_amount_cop
        
        if tax_code == '34' and product.has_ibua:
            if not product.ml_ibua:
                raise UserError(
                    f'El producto {product.name} tiene IBUA activo pero falta el volumen en ml.'
                )
            
            aux_subtotal = (line.quantity * tax_amount * product.ml_ibua * 
                        line.product_uom_id.factor_inv) / 100
            
            base_unit_measure = round(
                product.ml_ibua * line.quantity * line.product_uom_id.factor_inv, 2
            )
            unit_code = 'MLT'
            
        elif tax_code == '33' and product.has_inpp:
            if not product.grams_inpp:
                raise UserError(
                    f'El producto {product.name} tiene INPP activo pero falta el peso en gramos.'
                )
            
            aux_subtotal = (line.quantity * tax_amount * product.grams_inpp * 
                        line.product_uom_id.factor_inv)
            
            base_unit_measure = round(
                product.grams_inpp * line.quantity * line.product_uom_id.factor_inv, 2
            )
            unit_code = 'GRS'
            
        elif tax_code == '32' and product.has_icl:
            if not product.alcohol_degree or not product.volume_ml:
                raise UserError(
                    f'El producto {product.name} tiene ICL activo pero faltan los datos de '
                    f'grados de alcohol o volumen en ml.'
                )
            
            if product.volume_ml == 750:
                aux_subtotal = line.quantity * line.product_uom_id.factor_inv * (
                    tax_amount * product.alcohol_degree
                )
                differential_amount = differential_amount_cop
            else:
                aux_subtotal = line.quantity * line.product_uom_id.factor_inv * (
                    (tax_amount * product.volume_ml) / 750) * product.alcohol_degree
                differential_amount = (differential_amount_cop * product.volume_ml) / 750
            
            base_unit_measure = round(
                product.alcohol_degree * line.quantity * line.product_uom_id.factor_inv, 2
            )
            unit_code = 'LTR'
            
        elif tax_code in ['32', '33', '34']:
            if (tax_code == '32' and product.has_icl) or \
            (tax_code == '33' and product.has_inpp) or \
            (tax_code == '34' and product.has_ibua):
                impuesto_name = {
                    '32': 'ICL',
                    '33': 'INPP', 
                    '34': 'IBUA'
                }.get(tax_code, tax_code)
                
                raise UserError(
                    f'No se encuentran diligenciados los campos requeridos en el producto '
                    f'{product.name} para usar el impuesto {impuesto_name} asignado.'
                )
        
        if unit_code:
            tax_data.update({
                'base_unit_measure': base_unit_measure,
                'base_unit_measure_attrs': {'unitCode': unit_code},
                'per_unit_amount': differential_amount,
                'differential_amount': differential_amount,
            })
        
        return tax_data
    
    def _accumulate_taxes(self, total_dict, tax_info):
        """Acumula impuestos en el diccionario total"""
        for tax_code, tax_data in tax_info.items():
            if tax_code not in total_dict:
                total_dict[tax_code] = {'total': 0.0, 'info': {}}

            total_dict[tax_code]['total'] += tax_data['total']

            for rate_key, info in tax_data['info'].items():
                if rate_key in total_dict[tax_code]['info']:
                    total_dict[tax_code]['info'][rate_key]['value'] += info['value']
                    total_dict[tax_code]['info'][rate_key]['taxable_amount'] += info['taxable_amount']
                else:
                    total_dict[tax_code]['info'][rate_key] = info.copy()

    def _get_tax_totals(self):
        """
        Prepara totales de impuestos agrupados por tipo de tributo.

        LÓGICA: compute_all de Odoo + agrupación por código DIAN.

        Maneja casos especiales:
        - IVA Excluido (código 01 con 'excluido/exc' en nombre)
        - ICA formato por mil (código 07)
        - ICL/IBUA con base unitaria (códigos 32/34)
        - NO incluye retenciones (05, 06, 07, ZZ)

        Returns:
            dict: {codigo_tributo: {'total': float, 'name': str, 'code': str, 'info': {...}}}
        """
        self.ensure_one()
        tax_totals = {}
        calculation_rate = 1

        def _is_excluded_tax(tax):
            """IVA Excluido: código 01 con 'excluido' o 'exc' en nombre"""
            tax_codigo = tax.codigo_dian if tax else None
            tax_name_lower = tax.name.lower() if tax.name else ''
            return (tax_codigo == '01' and
                    any(keyword in tax_name_lower for keyword in ['excluido', 'exc', 'exento']))

        # Filtrar líneas de productos
        product_lines = self.invoice_line_ids.filtered(lambda l: l.display_type == 'product')

        for line in product_lines:
            # Base antes de descuento
            base_before_discount = line.price_unit * line.quantity

            # Base después de descuento (net price)
            net_price = base_before_discount * (1 - (line.discount / 100.0))

            # Compute_all nativo de Odoo para todos los impuestos de la línea
            taxes_computed = line.tax_ids.compute_all(
                net_price,
                currency=line.currency_id,
                quantity=1,
                product=line.product_id,
                partner=self.partner_id
            )

            # Procesar cada impuesto (no retención)
            for tax in line.tax_ids.filtered(lambda t: t.codigo_dian if t else None):
                tax_id = tax.codigo_dian

                # Solo impuestos (no retenciones 05, 06, 07, ZZ)
                if tax_id in ['05', '06', '07', 'ZZ']:
                    continue

                # Excluir IVA Excluido
                if _is_excluded_tax(tax):
                    continue

                # Obtener monto calculado por compute_all
                tax_detail = next((t for t in taxes_computed['taxes'] if t['id'] == tax.id), None)
                if not tax_detail:
                    continue

                tax_amount = abs(tax_detail['amount']) * calculation_rate

                # Base imponible: usar método DIAN si existe
                if hasattr(line, '_l10n_co_dian_net_price_subtotal') and line._l10n_co_dian_net_price_subtotal():
                    taxable_amount = line._l10n_co_dian_net_price_subtotal()
                else:
                    taxable_amount = line.price_subtotal

                # Calcular tasa según tipo de impuesto
                if tax_id == '32':
                    # ICL (alcoholic beverages) - based on alcohol percentage per liter
                    rate = abs(tax.amount)
                    base_unit = line.product_id.l10n_co_edi_ref_nominal_tax if hasattr(line.product_id, 'l10n_co_edi_ref_nominal_tax') else 1.0
                elif tax_id == '34':
                    # IBUA (sugar beverages) - based on sugar per 100mL
                    base_unit = line.product_id.l10n_co_edi_ref_nominal_tax if hasattr(line.product_id, 'l10n_co_edi_ref_nominal_tax') else 1.0
                    rate = abs(tax.amount) * 100 / base_unit
                elif tax_id == '07':
                    # ICA - por mil
                    rate = abs(tax.amount) / 1000
                else:
                    # Impuestos normales (IVA, INC, etc.)
                    rate = abs(tax.amount)

                # Formato de clave
                if tax_id in ['32', '34', '07']:
                    rate_key = f"{rate:.4f}"  # 4 decimales
                else:
                    rate_key = f"{rate:.2f}"  # 2 decimales estándar

                # Inicializar estructura
                if tax_id not in tax_totals:
                    tax_totals[tax_id] = {
                        'total': 0.0,
                        'name': tax.nombre_dian if hasattr(tax, 'nombre_dian') and tax.nombre_dian else tax.name,
                        'code': tax_id,
                        'info': {}
                    }

                # Acumular o crear entrada
                if rate_key in tax_totals[tax_id]['info']:
                    tax_totals[tax_id]['info'][rate_key]['taxable_amount'] += taxable_amount
                    tax_totals[tax_id]['info'][rate_key]['value'] += tax_amount
                    if tax_id in ['32', '34']:
                        base_unit_prod = line.product_id.l10n_co_edi_ref_nominal_tax if hasattr(line.product_id, 'l10n_co_edi_ref_nominal_tax') else 0.0
                        tax_totals[tax_id]['info'][rate_key]['base_unit'] = tax_totals[tax_id]['info'][rate_key].get('base_unit', 0.0) + base_unit_prod
                else:
                    entry = {
                        'taxable_amount': taxable_amount,
                        'value': tax_amount,
                        'technical_name': tax.nombre_dian if hasattr(tax, 'nombre_dian') and tax.nombre_dian else tax.name,
                        'amount_type': tax.amount_type,
                        'per_unit_amount': rate,
                        'price_include': tax.price_include,
                    }
                    # Agregar base unitaria para ICL/IBUA
                    if tax_id in ['32', '34']:
                        base_unit_prod = line.product_id.l10n_co_edi_ref_nominal_tax if hasattr(line.product_id, 'l10n_co_edi_ref_nominal_tax') else 0.0
                        entry['base_unit'] = base_unit_prod
                        entry['unit_code'] = 'LTR' if tax_id == '32' else 'MLT'

                    tax_totals[tax_id]['info'][rate_key] = entry

                tax_totals[tax_id]['total'] += tax_amount

        return tax_totals

    def _get_retention_totals(self):
        """
        Prepara totales de retenciones (tributos 05, 06, 07).

        LÓGICA: compute_all de Odoo + validación especial.

        Validaciones:
        - En facturas de compra (in_invoice/in_refund): SOLO ReteFuente (06)
        - En facturas de venta (out_invoice/out_refund): Todas las retenciones
        - ReteIVA (05): Base es el monto del IVA, NO la base imponible
        - ReteICA (07): Formato por mil

        Returns:
            dict: {codigo_retencion: {'total': float, 'name': str, 'code': str, 'info': {...}}}
        """
        self.ensure_one()
        retention_totals = {}
        calculation_rate = 1
        is_purchase = self.move_type in ['in_invoice', 'in_refund']

        product_lines = self.invoice_line_ids.filtered(lambda l: l.display_type == 'product')

        for line in product_lines:
            # Base después de descuento
            net_price = (line.price_unit * line.quantity) * (1 - (line.discount / 100.0))

            # Compute_all nativo
            taxes_computed = line.tax_ids.compute_all(
                net_price,
                currency=line.currency_id,
                quantity=1,
                product=line.product_id,
                partner=self.partner_id
            )

            # Procesar retenciones
            for tax in line.tax_ids.filtered(lambda t: t.codigo_dian if t else None):
                tax_id = tax.codigo_dian

                # Solo retenciones (05, 06, 07)
                if tax_id not in ['05', '06', '07']:
                    continue

                # Validación DIAN: En documentos soporte (compras), solo ReteFuente (06)
                if is_purchase and tax_id != '06':
                    continue

                # Obtener monto calculado por compute_all
                tax_detail = next((t for t in taxes_computed['taxes'] if t['id'] == tax.id), None)
                if not tax_detail:
                    continue

                tax_amount = abs(tax_detail['amount']) * calculation_rate

                # Base imponible según tipo de retención
                if tax_id == '05':
                    # ReteIVA: La base es el MONTO del IVA, no la base imponible
                    # Según constraint DSAY05: base de '05' debe ser igual al Tax Amount de '01'
                    iva_tax = next((t for t in line.tax_ids if (t.codigo_dian if t else None) == '01'), None)
                    if iva_tax:
                        iva_detail = next((t for t in taxes_computed['taxes'] if t['id'] == iva_tax.id), None)
                        taxable_amount = abs(iva_detail['amount']) if iva_detail else 0.0
                    else:
                        taxable_amount = 0.0
                else:
                    # ReteFuente/ReteICA: Base imponible normal
                    if hasattr(line, '_l10n_co_dian_net_price_subtotal') and line._l10n_co_dian_net_price_subtotal():
                        taxable_amount = line._l10n_co_dian_net_price_subtotal()
                    else:
                        taxable_amount = line.price_subtotal

                # Calcular tasa según tipo
                if tax_id == '05':
                    # ReteIVA: Reportar tasa real (15%), no la de Odoo (-2.85%)
                    iva_tax = next((t for t in line.tax_ids if (t.codigo_dian if t else None) == '01'), None)
                    if iva_tax:
                        rate = abs(tax.amount) * 100 / abs(iva_tax.amount)
                    else:
                        rate = abs(tax.amount)
                elif tax_id == '07':
                    # ReteICA: por mil
                    rate = abs(tax.amount) / 1000
                else:
                    # ReteFuente: tasa normal
                    rate = abs(tax.amount)

                # Formato de clave
                rate_key = f"{rate:.4f}" if tax_id == '07' else f"{rate:.2f}"

                # Inicializar estructura
                if tax_id not in retention_totals:
                    retention_totals[tax_id] = {
                        'total': 0.0,
                        'name': tax.nombre_dian if hasattr(tax, 'nombre_dian') and tax.nombre_dian else tax.name,
                        'code': tax_id,
                        'info': {}
                    }

                # Acumular o crear entrada
                if rate_key in retention_totals[tax_id]['info']:
                    retention_totals[tax_id]['info'][rate_key]['taxable_amount'] += taxable_amount
                    retention_totals[tax_id]['info'][rate_key]['value'] += tax_amount
                else:
                    retention_totals[tax_id]['info'][rate_key] = {
                        'taxable_amount': taxable_amount,
                        'value': tax_amount,
                        'technical_name': tax.nombre_dian if hasattr(tax, 'nombre_dian') and tax.nombre_dian else tax.name,
                        'amount_type': tax.amount_type,
                        'per_unit_amount': rate,
                        'price_include': tax.price_include,
                    }

                retention_totals[tax_id]['total'] += tax_amount

        return retention_totals
    
    def _process_global_charges(self, line_extension_amount):
        """Procesa cargos y descuentos globales"""
        data = {
            'global_charges': [],
            'global_discounts': [],
            'rounding_adjustment_data': None,
        }
        
        # Líneas de cargo/descuento
        charge_lines = self.invoice_line_ids.filtered(
            lambda l: l.display_type == 'product' and 
                     l.product_id.enable_charges and
                     not ((l.product_id.discount_tax) and 
                          l.product_id.discount_tax == '00' and 
                          l.price_subtotal < 0)
        )
        
        for idx, line in enumerate(charge_lines):
            amount_in_company_currency = abs(line._l10n_co_dian_net_price_subtotal())
            
            if line.price_subtotal > 0:
                # Cargo
                data['global_charges'].append({
                    'id': idx + 1,
                    'reason': line.name or line.product_id.name,
                    'reason_code': '99',
                    'amount': amount_in_company_currency,
                    'base_amount': line_extension_amount,
                })
                data['total_charge_amount'] = data.get('total_charge_amount', 0) + amount_in_company_currency
            else:
                discount_code = '01' 
                if line.product_id.discount_tax:
                    discount_code = line.product_id.discount_tax or '01'
                
                data['global_discounts'].append({
                    'id': idx + 1,
                    'reason': line.name or line.product_id.name,
                    'reason_code': discount_code,
                    'amount': amount_in_company_currency,
                    'base_amount': line_extension_amount,
                })
                data['total_discount_amount'] = data.get('total_discount_amount', 0) + amount_in_company_currency
        
        rounding_lines = self.line_ids.filtered(
            lambda l: l.display_type == 'rounding' or 
                     (l.product_id and l.product_id.default_code == 'RED' and l.product_id.enable_charges)
        )
        
        if rounding_lines:
            rounding_total = sum(rounding_lines.mapped('balance')) * (-1 if self.move_type == 'out_refund' else 1)
            
            if rounding_total != 0:
                multiplier = abs(rounding_total) / line_extension_amount * 100 if line_extension_amount else 0
                
                data['rounding_adjustment_data'] = {
                    'ID': '3' if rounding_total < 0 else '2',
                    'ChargeIndicator': 'true' if rounding_total < 0 else 'false',
                    'AllowanceChargeReason': 'Cargo por ajuste al peso' if rounding_total < 0 else 'Descuento por ajuste al peso',
                    'MultiplierFactorNumeric': f"{multiplier:.6f}",
                    'Amount': f"{abs(rounding_total):.2f}",
                    'BaseAmount': f"{line_extension_amount:.2f}",
                    'CurrencyID': self.currency_id.name,
                }
                
                if rounding_total < 0:
                    data['total_charge_amount'] = data.get('total_charge_amount', 0) + abs(rounding_total)
                else:
                    data['total_discount_amount'] = data.get('total_discount_amount', 0) + abs(rounding_total)
        
        return data
    
    # =============================================================================
    # SECCIÓN: CÁLCULO DE TOTALES
    # =============================================================================
    
    def _calculate_totals(self, data):
        """Calcula todos los totales del documento"""
        # Obtener valores base
        line_extension = data['line_extension_amount']
        line_excluded = data['line_excluded_amount']
        total_tax = data['total_tax_amount']
        total_retention = data['total_withholding_amount']
        
        # Cargos y descuentos
        total_charges = data.get('total_charge_amount', 0)
        total_discounts = data.get('total_discount_amount', 0)
        
        # Redondeo
        rounding_charge = 0.0
        rounding_discount = 0.0
        if data.get('rounding_adjustment_data'):
            if data['rounding_adjustment_data']['ChargeIndicator'] == 'true':
                rounding_charge = float(data['rounding_adjustment_data']['Amount'])
            else:
                rounding_discount = float(data['rounding_adjustment_data']['Amount'])
        
        # Cálculo de totales
        tax_exclusive = line_extension - line_excluded
        tax_inclusive = line_extension + total_tax
        payable = tax_inclusive + rounding_charge - rounding_discount
        
        # Conversión a COP si es necesario
        cop_amounts = {'tot_iva_cop': 0, 'tot_inc_cop': 0, 'tot_bol_cop': 0, 'imp_otro_cop': 0,
                      'rete_fue_cop': 0, 'rete_iva_cop': 0, 'rete_ica_cop': 0}
        
        if self.currency_id.name != 'COP':
            rate = self.current_exchange_rate
            
            # Impuestos en COP
            for tax_code, tax_data in data['tax_total_values'].items():
                if tax_code == '01':
                    cop_amounts['tot_iva_cop'] = tax_data['total'] #* rate
                elif tax_code == '04':
                    cop_amounts['tot_inc_cop'] = tax_data['total'] #* rate
                elif tax_code == '22':
                    cop_amounts['tot_bol_cop'] = tax_data['total'] #* rate
                else:
                    cop_amounts['imp_otro_cop'] += tax_data['total'] #* rate
            
            # Retenciones en COP
            for ret_code, ret_data in data['ret_total_values'].items():
                if ret_code == '05':
                    cop_amounts['rete_iva_cop'] = ret_data['total'] #* rate
                elif ret_code == '06':
                    cop_amounts['rete_fue_cop'] = ret_data['total'] #* rate
                elif ret_code == '07':
                    cop_amounts['rete_ica_cop'] = ret_data['total'] #* rate
        
        return {
            'TotalLineExtensionAmount': f"{line_extension:.2f}",
            'TotalTaxExclusiveAmount': f"{tax_exclusive:.2f}",
            'TotalTaxInclusiveAmount': f"{tax_inclusive:.2f}",
            'TotalAllowanceAmount': f"{rounding_discount:.2f}",
            'TotalChargeAmount': f"{rounding_charge:.2f}",
            'PayableAmount': f"{payable:.2f}",
            'WithholdingAmount': f"{total_retention:.2f}",
            
            # Para cálculos posteriores
            'line_extension_amount_calc': line_extension,
            'total_tax_calc': total_tax,
            'rounding_charge': rounding_charge,
            'rounding_discount': rounding_discount,
            
            # Montos en COP
            **cop_amounts,
        }
    
    # =============================================================================
    # SECCIÓN: GENERACIÓN DE CÓDIGOS DE SEGURIDAD (CUFE/CUDE/CUDS)
    # =============================================================================
    
    def _generate_security_codes(self, data):
        """Genera CUFE/CUDE/CUDS y códigos QR"""
        # Determinar tipo
        if self.move_type in ['out_invoice', 'out_refund'] or self.is_debit_note:
            return self._generate_cufe(data)
        else:
            return self._generate_cuds(data)
    
    def _generate_cufe(self, data):
        """Genera CUFE para facturas de venta y notas"""
        # Datos para CUFE
        numfac = self.name
        fecfac = data['fecha_xml_date']
        horfac = data['fecha_xml_time']
        valfac = '{:.2f}'.format(data['line_extension_amount_calc'])
        
        # Impuestos
        tax_values = data['tax_total_values']
        codimp1 = '01'
        valimp1 = '{:.2f}'.format(tax_values.get('01', {}).get('total', 0))
        codimp2 = '04'
        valimp2 = '{:.2f}'.format(tax_values.get('04', {}).get('total', 0))
        codimp3 = '03'
        valimp3 = '{:.2f}'.format(tax_values.get('03', {}).get('total', 0))
        
        valtot = data['PayableAmount']
        
        # NIT
        nitofe = str(self.company_id.partner_id.vat_co)
        numadq = str(self.partner_id.vat_co or self.partner_id.parent_id.vat_co or '')
        
        # Ambiente
        tipoambiente = '1' if self.company_id.production else '2'
        
        # Clave técnica
        if self.move_type == 'out_invoice' and not self.is_debit_note:
            citec = data['TechnicalKey']
        else:
            citec = self.company_id.software_pin
        
        # Construir CUFE
        cufe_str = unidecode(
            str(numfac) + str(fecfac) + str(horfac) + str(valfac) + 
            str(codimp1) + str(valimp1) + str(codimp2) + str(valimp2) + 
            str(codimp3) + str(valimp3) + str(valtot) + str(nitofe) + 
            str(numadq) + str(citec) + str(tipoambiente)
        )
        
        # Hash
        sha384 = hashlib.sha384()
        sha384.update(cufe_str.encode())
        cufe = sha384.hexdigest()
        
        # QR
        qr_data = self._generate_qr_data(data, cufe, 'CUFE')
        qr = pyqrcode.create(qr_data, error='L')
        
        return {
            'cufe': cufe,
            'cufe_seed': cufe_str,
            'qr_data': qr_data,
            'qr_code': qr.png_as_base64_str(scale=2),
            'UUID': cufe,
        }
    
    def _generate_cuds(self, data):
        """Genera CUDS para documentos soporte"""
        # Similar a CUFE pero con formato CUDS
        numfac = self.name
        fecfac = data['fecha_xml_date']
        horfac = data['fecha_xml_time']
        valfac = '{:.2f}'.format(data['line_extension_amount_calc'])
        
        tax_values = data['tax_total_values']
        codimp1 = '01'
        valimp1 = '{:.2f}'.format(tax_values.get('01', {}).get('total', 0))
        
        valtot = data['PayableAmount']
        
        nitofe = str(self.company_id.partner_id.vat_co)
        numadq = str(self.partner_id.vat_co or self.partner_id.parent_id.vat_co or '')
        
        tipoambiente = '1' if self.company_id.production else '2'
        citec = self.company_id.software_pin
        
        # Construir CUDS
        cuds_str = unidecode(
            str(numfac) + str(fecfac) + str(horfac) + str(valfac) + 
            str(codimp1) + str(valimp1) + str(valtot) + str(numadq) + 
            str(nitofe) + str(citec) + str(tipoambiente)
        )
        
        # Hash
        sha384 = hashlib.sha384()
        sha384.update(cuds_str.encode())
        cuds = sha384.hexdigest()
        
        # QR
        qr_data = self._generate_qr_data(data, cuds, 'CUDS')
        qr = pyqrcode.create(qr_data, error='L')
        
        return {
            'cufe': cuds,
            'cufe_seed': cuds_str,
            'qr_data': qr_data,
            'qr_code': qr.png_as_base64_str(scale=2),
            'UUID': cuds,
        }
    
    def extract_signature_value(self):
        for record in self:
            signature_value = ''
            if record.dian_xml_attachment_id:
                try:
                    root = etree.fromstring(record.dian_xml_attachment_id.encode('utf-8'))
                    signature_element = root.xpath('//ds:SignatureValue', namespaces={'ds': 'http://www.w3.org/2000/09/xmldsig#'})
                    if signature_element:
                        signature_value = signature_element[0].text
                except etree.XMLSyntaxError:
                    pass
            #record.signature_value = signature_value
            _logger.error(signature_value)
            return signature_value


    def _generate_qr_data(self, data, cufe, type_code):
        """Genera los datos para el código QR"""
        base_url = 'https://catalogo-vpfe.dian.gov.co' if self.company_id.production else 'https://catalogo-vpfe-hab.dian.gov.co'
        
        total_otros = sum(v['total'] for k, v in data['tax_total_values'].items() if k != '01')
        
        qr_data = (
            f"NumFac: {self.name}\n"
            f"FecFac: {data['fecha_xml_date']}\n"
            f"HorFac: {data['fecha_xml_time']}\n"
            f"NitFac: {self.company_id.partner_id.vat_co}\n"
            f"DocAdq: {self.partner_id.vat_co or ''}\n"
            f"ValFac: {data['line_extension_amount_calc']:.2f}\n"
            f"ValIva: {data['tax_total_values'].get('01', {}).get('total', 0):.2f}\n"
            f"ValOtroIm: {total_otros:.2f}\n"
            f"ValFacIm: {data['PayableAmount']}\n"
            f"{type_code}: {cufe}"
        )
        
        if type_code == 'CUDS':
            qr_data += f"\n{base_url}/document/searchqr?documentkey={cufe}"
        
        return qr_data
    
    # =============================================================================
    # SECCIÓN: CONSTRUCCIÓN XML
    # =============================================================================
    



    def _build_xml_from_data(self, data):
        """Construye el XML con todos los namespaces necesarios"""
        
        if self.is_debit_note:
            tag, suffix = 'DebitNote', 'DebitNote-2'
        elif self.move_type in ['out_refund', 'in_refund']:
            tag, suffix = 'CreditNote', 'CreditNote-2'
        else:
            tag, suffix = 'Invoice', 'Invoice-2'
        
        base_ns = f"urn:oasis:names:specification:ubl:schema:xsd:{suffix}"
        
        namespaces = {
            None: base_ns,
            'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2',
            'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2',
            'ds': 'http://www.w3.org/2000/09/xmldsig#',
            'ext': 'urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2',
            'xsi': 'http://www.w3.org/2001/XMLSchema-instance'
        }
        
        if self.move_type in ['in_invoice', 'in_refund'] or self.fe_type == '02':
            namespaces.update({
                'sts': 'dian:gov:co:facturaelectronica:Structures-2-1',
                'xades': 'http://uri.etsi.org/01903/v1.3.2#',
                'xades141': 'http://uri.etsi.org/01903/v1.4.1#'
            })
        else:
            namespaces['sts'] = 'http://www.dian.gov.co/contratos/facturaelectronica/v1/Structures'
        
        root = etree.Element(f"{{{base_ns}}}{tag}", nsmap=namespaces)
        root.set(
            '{http://www.w3.org/2001/XMLSchema-instance}schemaLocation',
            f'{base_ns} http://docs.oasis-open.org/ubl/os-UBL-2.1/xsd/maindoc/UBL-{tag}-2.1.xsd'
        )
        
        _logger.info(f"XML {self.name}: {tag}, namespaces: {list(namespaces.keys())}")
        
        makers = {}
        for prefix, uri in namespaces.items():
            if prefix:  
                if prefix == 'sts':
                    makers[prefix] = ElementMaker(namespace=namespaces['sts'], nsmap=namespaces)
                else:
                    makers[prefix] = ElementMaker(namespace=uri, nsmap=namespaces)
        
        # 6. Construir documento
        self._build_ubl_extensions(root, data, makers)
        self._build_header(root, data, makers)
        self._build_parties(root, data, makers)
        self._build_payment_sections(root, data, makers)
        
        if data.get('prepaid_payments'):
            self._build_prepaid_payments(root, data, makers)
        
        if data.get('global_charges') or data.get('global_discounts') or data.get('rounding_adjustment_data'):
            self._build_allowance_charges(root, data, makers)
        
        self._build_tax_totals(root, data, makers)
        self._build_monetary_totals(root, data, makers)
        self._build_document_lines(root, data, makers)
        
        etree.cleanup_namespaces(root)
        xml_string = etree.tostring(root, pretty_print=True, xml_declaration=True, encoding='UTF-8').decode('utf-8')
        
        # Agregar xades si es necesario
        if self.move_type in ['in_invoice', 'in_refund'] or self.fe_type_ei_ref == '02':
            if 'xmlns:xades="http://uri.etsi.org/01903/v1.3.2#"' not in xml_string:
                # Buscar punto de inserción
                if 'xmlns:sts="dian:gov:co:facturaelectronica:Structures-2-1"' in xml_string:
                    xml_string = xml_string.replace(
                        'xmlns:sts="dian:gov:co:facturaelectronica:Structures-2-1"',
                        'xmlns:sts="dian:gov:co:facturaelectronica:Structures-2-1" xmlns:xades="http://uri.etsi.org/01903/v1.3.2#" xmlns:xades141="http://uri.etsi.org/01903/v1.4.1#"'
                    )
                elif 'xsi:schemaLocation=' in xml_string:
                    # Insertar antes de schemaLocation
                    xml_string = xml_string.replace(
                        'xsi:schemaLocation=',
                        'xmlns:xades="http://uri.etsi.org/01903/v1.3.2#" xmlns:xades141="http://uri.etsi.org/01903/v1.4.1#" xsi:schemaLocation='
                    )
        
        return xml_string
   
    
    # -------------------------------------------------------------------------
    # Construcción: UBL Extensions
    # -------------------------------------------------------------------------

    def _build_ubl_extensions(self, root, data, makers):
        """Construye la sección UBLExtensions completa"""
        ext = makers['ext']
        sts = makers['sts']
        cbc = makers['cbc']
        
        ubl_extensions = ext.UBLExtensions()
        
        # Extension 1: DIAN Extensions
        extension1 = ext.UBLExtension()
        extension_content = ext.ExtensionContent()
        dian_extensions = sts.DianExtensions()
        
        # InvoiceControl (solo para facturas)
        if data['move_type'] in ['out_invoice', 'in_invoice'] and not data['is_debit_note']:
            invoice_control = sts.InvoiceControl(
                sts.InvoiceAuthorization(data['InvoiceAuthorization']),
                sts.AuthorizationPeriod(
                    cbc.StartDate(data['StartDate']),
                    cbc.EndDate(data['EndDate'])
                ),
                sts.AuthorizedInvoices(
                    sts.Prefix(data['Prefix']),
                    sts.From(data['From']),
                    sts.To(data['To'])
                )
            )
            dian_extensions.append(invoice_control)
        
        # InvoiceSource
        invoice_source = sts.InvoiceSource(
            cbc.IdentificationCode(
                data['SupplierCountry'],
                listAgencyID='6',
                listAgencyName='United Nations Economic Commission for Europe',
                listSchemeURI='urn:oasis:names:specification:ubl:codelist:gc:CountryIdentificationCode-2.1'
            )
        )
        dian_extensions.append(invoice_source)
        
        # SoftwareProvider
        software_provider = sts.SoftwareProvider(
            sts.ProviderID(
                data['SoftwareProviderID'],
                schemeAgencyID='195',
                schemeAgencyName='CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)',
                schemeID=data['SoftwareProviderDV'] if data['SupplierSchemeIDCode'] == '31' else '',
                schemeName='31'
            ),
            sts.SoftwareID(
                data['SoftwareID'],
                schemeAgencyID='195',
                schemeAgencyName='CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)'
            )
        )
        dian_extensions.append(software_provider)
        
        # SoftwareSecurityCode
        dian_extensions.append(
            sts.SoftwareSecurityCode(
                data['SoftwareSecurityCode'],
                schemeAgencyID='195',
                schemeAgencyName='CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)'
            )
        )
        
        # AuthorizationProvider
        dian_extensions.append(
            sts.AuthorizationProvider(
                sts.AuthorizationProviderID(
                    '800197268',
                    schemeAgencyID='195',
                    schemeAgencyName='CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)',
                    schemeID='4',
                    schemeName='31'
                )
            )
        )
        
        # QRCode
        dian_extensions.append(sts.QRCode(self._build_qr_content(data)))
        
        extension_content.append(dian_extensions)
        extension1.append(extension_content)
        ubl_extensions.append(extension1)
        
        # Extension 2: Moneda extranjera (si aplica)
        if data.get('is_foreign_currency'):
            extension2 = self._build_foreign_currency_extension(data, makers)
            ubl_extensions.append(extension2)
        
        # Extension 3: Vacía (requerida)
        extension3 = ext.UBLExtension(ext.ExtensionContent())
        ubl_extensions.append(extension3)
        
        # Hook para extensiones adicionales
        self._add_custom_extensions(ubl_extensions, data, makers)
        
        root.append(ubl_extensions)

    def _build_qr_content(self, data):
        """Genera el contenido del código QR para UBLExtensions"""
        if data['move_type'] in ['in_invoice', 'in_refund']:
            return f"CUDS={data['cufe']}\nURL={self._get_qr_url(data)}={data['cufe']}"
        else:
            return (
                f"NroFactura={data['InvoiceID']}\n"
                f"NitFacturador={data['SoftwareProviderID']}\n"
                f"NitAdquiriente={data['CustomerID']}\n"
                f"FechaFactura={data['fecha_xml_date']}\n"
                f"ValorTotalFactura={data['PayableAmount']}\n"
                f"CUFE={data['cufe']}\n"
                f"URL={self._get_qr_url(data)}={data['cufe']}"
            )

    def _get_qr_url(self, data):
        """Obtiene la URL base para el QR"""
        if data['company'].production:
            return 'https://catalogo-vpfe.dian.gov.co/document/searchqr?documentkey'
        else:
            return 'https://catalogo-vpfe-hab.dian.gov.co/document/searchqr?documentkey'

    def _build_foreign_currency_extension(self, data, makers):
        """Construye la extensión para moneda extranjera"""
        ext = makers['ext']
        
        # CustomTagGeneral para moneda extranjera
        custom_content = etree.Element('CustomTagGeneral')
        
        # Interoperabilidad
        interop = etree.SubElement(custom_content, 'Interoperabilidad')
        group = etree.SubElement(interop, 'Group', schemeName='Factura de Venta')
        etree.SubElement(group, 'Collection', schemeName='DATOS ADICIONALES')
        
        # Totales en COP
        totales_cop = etree.SubElement(custom_content, 'TotalesCop')
        etree.SubElement(totales_cop, 'FctConvCop').text = f"{data['exchange_rate']:.2f}"
        etree.SubElement(totales_cop, 'MonedaCop').text = data['currency_id']
        etree.SubElement(totales_cop, 'SubTotalCop').text = f"{float(data['TotalLineExtensionAmount']) / data['exchange_rate']:.2f}"
        etree.SubElement(totales_cop, 'TotalBrutoFacturaCop').text = f"{float(data['TotalLineExtensionAmount']) / data['exchange_rate']:.2f}"
        etree.SubElement(totales_cop, 'TotIvaCop').text = f"{data.get('tot_iva_cop', 0) / data['exchange_rate']:.2f}"
        etree.SubElement(totales_cop, 'TotalNetoFacturaCop').text = f"{float(data['TotalTaxExclusiveAmount']) / data['exchange_rate']:.2f}"
        etree.SubElement(totales_cop, 'VlrPagarCop').text = f"{float(data['PayableAmount']) / data['exchange_rate']:.2f}"
        etree.SubElement(totales_cop, 'ReteFueCop').text = f"{data.get('rete_fue_cop', 0) / data['exchange_rate']:.2f}"
        etree.SubElement(totales_cop, 'ReteIvaCop').text = f"{data.get('rete_iva_cop', 0) / data['exchange_rate']:.2f}"
        etree.SubElement(totales_cop, 'ReteIcaCop').text = f"{data.get('rete_ica_cop', 0) / data['exchange_rate']:.2f}"
        
        extension = ext.UBLExtension(ext.ExtensionContent(custom_content))
        return extension

    def _add_custom_extensions(self, ubl_extensions, data, makers):
        """Hook para agregar extensiones personalizadas"""
        # Este método puede ser sobrescrito para agregar extensiones adicionales
        pass
    
    # -------------------------------------------------------------------------
    # Construcción: Header
    # -------------------------------------------------------------------------
    
    def _build_header(self, root, data, makers):
        """Construye el encabezado del documento"""
        cbc = makers['cbc']
        cac = makers['cac']
        
        # UBL Version
        root.append(cbc.UBLVersionID(data['UBLVersionID']))
        
        # Customization ID
        root.append(cbc.CustomizationID(data['CustomizationID']))
        
        # Profile ID y Execution ID
        root.append(cbc.ProfileID(data['ProfileID']))
        root.append(cbc.ProfileExecutionID(data['ProfileExecutionID']))
        
        # Document ID
        root.append(cbc.ID(data['InvoiceID']))
        
        # UUID con scheme correcto
        scheme_name = SCHEME_MAPPING.get(self.move_type if not self.is_debit_note else 'debit_note', 'CUFE-SHA384')
        root.append(
            cbc.UUID(
                data['cufe'],
                schemeID=data['ProfileExecutionID'],
                schemeName=scheme_name
            )
        )
        
        # Fecha y hora
        root.append(cbc.IssueDate(data['fecha_xml_date']))
        root.append(cbc.IssueTime(data['fecha_xml_time']))
        
        # Tipo de documento
        self._add_document_type_code(root, data, makers)
        
        # Nota (si existe)
        if data.get('Notes'):
            root.append(cbc.Note(data['Notes']))
        
        # Moneda
        root.append(cbc.DocumentCurrencyCode(data['currency_id']))
        
        # Contador de líneas
        root.append(cbc.LineCountNumeric(str(data['LineCountNumeric'])))
        
        # Período de factura
        if data.get('has_invoice_period') or self.document_without_reference or self.is_health_sector:
            period = cac.InvoicePeriod(
                cbc.StartDate(data.get('invoice_period_start') or str(self.date_from or self.date_start))
            )
            if data.get('invoice_period_end') or self.date_to or self.is_health_sector or self.document_without_reference:
                period.append(cbc.EndDate(data.get('invoice_period_end') or str(self.date_to or self.date_end)))
            root.append(period)
        
        # DiscrepancyResponse
        if data.get('ResponseCode') and data['move_type'] in ['out_refund', 'in_refund'] or data['is_debit_note']:
            discrepancy = cac.DiscrepancyResponse(
                cbc.ReferenceID(data.get('InvoiceReferenceID', '')),
                cbc.ResponseCode(data['ResponseCode']),
                cbc.Description(data.get('ResponseDescription', ''))
            )
            root.append(discrepancy)
                
        # Order Reference
        if data.get('order_references') and not self.ref:
            refs = data['order_references'][:3]
            if refs:
                concatenated_ids = ','.join(ref['ID'] for ref in refs if ref.get('ID'))
                order_ref = cac.OrderReference(cbc.ID(concatenated_ids))
                if refs[0].get('IssueDate'):
                    order_ref.append(cbc.IssueDate(refs[0]['IssueDate']))
                root.append(order_ref)
        elif self.ref:
            order_ref = cac.OrderReference(cbc.ID(str(self.ref)))
            if self.order_reference_date:
                order_ref.append(cbc.IssueDate(str(self.order_reference_date)))
            root.append(order_ref)
            
        if data.get('InvoiceReferenceID') and data.get('has_reference', True) and data['move_type'] in ['out_refund', 'in_refund'] or data['is_debit_note']:
            billing_ref = cac.BillingReference(
                cac.InvoiceDocumentReference(
                    cbc.ID(data['InvoiceReferenceID']),
                    cbc.UUID(
                        data.get('InvoiceReferenceUUID', ''),
                        schemeName=data.get('InvoiceReferenceScheme', 'CUFE-SHA384')
                    )
                )
            )
            
            if data.get('InvoiceReferenceDate'):
                billing_ref.find('.//cac:InvoiceDocumentReference', namespaces={'cac': billing_ref.nsmap['cac']}).append(
                    cbc.IssueDate(data['InvoiceReferenceDate'])
                )
            
            root.append(billing_ref)   
                 
        # Despatch Reference
        if data.get('despatch_references'):
            for ref in data['despatch_references']:
                despatch_ref = cac.DespatchDocumentReference(cbc.ID(ref['ID']))
                if ref.get('IssueDate'):
                    despatch_ref.append(cbc.IssueDate(ref['IssueDate']))
                root.append(despatch_ref)

            
    def _add_document_type_code(self, root, data, makers):
        """Agrega el código de tipo de documento"""
        cbc = makers['cbc']
        
        if data['move_type'] in ['out_invoice', 'in_invoice'] and not data['is_debit_note']:
            root.append(cbc.InvoiceTypeCode(data['document_code']))
        elif data['move_type'] in ['out_refund', 'in_refund']:
            root.append(cbc.CreditNoteTypeCode(data['document_code']))
        #elif data['is_debit_note']:
        #    root.append(cbc.DebitNoteTypeCode('92'))
    
    def _add_references(self, root, data, makers):
        """Agrega referencias para notas crédito/débito"""
        cac = makers['cac']
        cbc = makers['cbc']

        # BillingReference

    
    # -------------------------------------------------------------------------
    # Construcción: Parties
    # -------------------------------------------------------------------------
    
    def _build_parties(self, root, data, makers):
        """Construye las secciones AccountingSupplierParty y AccountingCustomerParty"""
        cac = makers['cac']
        
        # Supplier
        supplier_party = self._build_party_structure('Supplier', data, makers)
        root.append(cac.AccountingSupplierParty(*supplier_party))
        
        # Customer
        customer_party = self._build_party_structure('Customer', data, makers)
        root.append(cac.AccountingCustomerParty(*customer_party))
        
    def _safe_xml_value(self, value):
        if value is None or value == '':
            return "" 
        return str(value)
    
    def _build_party_structure(self, party_type, data, makers):
        """Construye la estructura completa de una parte"""
        cbc = makers['cbc']
        cac = makers['cac']
        
        prefix = party_type
        elements = []
        
        # AdditionalAccountID
        elements.append(
            cbc.AdditionalAccountID(
                data[f'{prefix}AdditionalAccountID'],
                schemeAgencyID='195'
            )
        )
        
        # Party
        party = cac.Party()
        
        if prefix == 'Customer':
            id_kwargs = {}
            
            scheme_id_code = data.get('CustomerSchemeIDCode')
            if scheme_id_code is not None:
                id_kwargs['schemeName'] = str(scheme_id_code)
            
            if scheme_id_code == '31':
                scheme_id = data.get('CustomerSchemeID')
                if scheme_id is not None:
                    id_kwargs['schemeID'] = str(scheme_id)
            
            party_id = cac.PartyIdentification(
                cbc.ID(str(data.get('CustomerID', '')), **id_kwargs)
            )
            party.append(party_id)
                
        # PartyName
        if data.get(f'{prefix}Name'):
            party.append(cac.PartyName(cbc.Name(data[f'{prefix}Name'])))
        
        # PhysicalLocation
        address = self._build_address(prefix, data, makers)
        if address is not None:
            party.append(cac.PhysicalLocation(address))
        
        # PartyTaxScheme
        tax_scheme = self._build_party_tax_scheme(prefix, data, makers)
        if tax_scheme is not None:
            party.append(tax_scheme)
        
        # PartyLegalEntity
        legal_entity = self._build_party_legal_entity(prefix, data, makers)
        if legal_entity is not None:
            party.append(legal_entity)
        
        # Contact
        contact = self._build_contact(prefix, data, makers)
        if contact is not None:
            party.append(contact)
        
        # Person (solo Customer)
        if prefix == 'Customer' and data.get(f'{prefix}firs_name'):
            party.append(cac.Person(cbc.FirstName(data[f'{prefix}firs_name'])))
        
        elements.append(party)
        return elements
    
    def _build_address(self, prefix, data, makers):
        """Construye la estructura de dirección"""
        cac = makers['cac']
        cbc = makers['cbc']
        
        # Verificar si hay datos de dirección
        if not any([
            data.get(f'{prefix}CityCode'),
            data.get(f'{prefix}CityName'),
            data.get(f'{prefix}AddressLine')
        ]):
            return None
        
        address = cac.Address()
        
        # Elementos de dirección en orden
        if data.get(f'{prefix}CityCode'):
            address.append(cbc.ID(data[f'{prefix}CityCode']))
        
        if data.get(f'{prefix}CityName'):
            address.append(cbc.CityName(data[f'{prefix}CityName']))
        
        # PostalZone solo para Supplier en ciertos casos
        if prefix == 'Supplier' and data['CustomizationID'] in ('10', '11') and data.get(f'{prefix}PostalZone'):
            address.append(cbc.PostalZone(data[f'{prefix}PostalZone']))
        
        if data.get(f'{prefix}DepartmentName'):
            address.append(cbc.CountrySubentity(data[f'{prefix}DepartmentName']))
        
        if data.get(f'{prefix}CountrySubentityCode'):
            address.append(cbc.CountrySubentityCode(data[f'{prefix}CountrySubentityCode']))
        
        if data.get(f'{prefix}AddressLine'):
            address.append(cac.AddressLine(cbc.Line(data[f'{prefix}AddressLine'])))
        
        # Country
        address.append(
            cac.Country(
                cbc.IdentificationCode(data.get(f'{prefix}Country', 'CO')),
                cbc.Name(data.get(f'{prefix}CountryName', 'Colombia'), languageID='es')
            )
        )
        
        return address
    
    def _build_party_tax_scheme(self, prefix, data, makers):
        """Construye el esquema tributario de la parte"""
        cac = makers['cac']
        cbc = makers['cbc']
        
        # CompanyID attributes
        company_attrs = {
            'schemeAgencyID': '195',
            'schemeAgencyName': 'CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)'
        }
        
        if data.get(f'{prefix}SchemeIDCode') == '31':
            company_attrs['schemeID'] = data.get(f'{prefix}SchemeID', '')
            company_attrs['schemeName'] = '31'
        else:
            company_attrs['schemeName'] = data.get(f'{prefix}SchemeIDCode', '')
        
        tax_scheme = cac.PartyTaxScheme(
            cbc.RegistrationName(data.get(f'{prefix}RegistrationName', '')),
            cbc.CompanyID(data.get(f'{prefix}ID', ''), **company_attrs)
        )
        
        # TaxLevelCode
        if data.get(f'{prefix}TaxLevelCode'):
            tax_scheme.append(
                cbc.TaxLevelCode(data[f'{prefix}TaxLevelCode'], listName='48')
            )
        
        # RegistrationAddress
        reg_address = self._build_registration_address(prefix, data, makers)
        if reg_address:
            tax_scheme.append(cac.RegistrationAddress(*reg_address))
        
        # TaxScheme
        if data.get(f'{prefix}TaxSchemeID'):
            tax_scheme.append(
                cac.TaxScheme(
                    cbc.ID(data[f'{prefix}TaxSchemeID']),
                    cbc.Name(data.get(f'{prefix}TaxSchemeName', ''))
                )
            )
        
        return tax_scheme
    
    def _build_registration_address(self, prefix, data, makers):
        """Construye la dirección de registro"""
        cac = makers['cac']
        cbc = makers['cbc']
        
        elements = []
        
        if data.get(f'{prefix}CityCode'):
            elements.append(cbc.ID(data[f'{prefix}CityCode']))
        
        if data.get(f'{prefix}CityName'):
            elements.append(cbc.CityName(data[f'{prefix}CityName']))
        
        if data.get(f'{prefix}DepartmentName'):
            elements.append(cbc.CountrySubentity(data[f'{prefix}DepartmentName']))
        
        if data.get(f'{prefix}CountrySubentityCode'):
            elements.append(cbc.CountrySubentityCode(data[f'{prefix}CountrySubentityCode']))
        
        if data.get(f'{prefix}AddressLine'):
            elements.append(cac.AddressLine(cbc.Line(data[f'{prefix}AddressLine'])))
        
        elements.append(
            cac.Country(
                cbc.IdentificationCode(data.get(f'{prefix}Country', 'CO')),
                cbc.Name(data.get(f'{prefix}CountryName', 'Colombia'), languageID='es')
            )
        )
        
        return elements
    
    def _build_party_legal_entity(self, prefix, data, makers):
        """Construye la entidad legal de la parte"""
        cac = makers['cac']
        cbc = makers['cbc']
        
        # CompanyID attributes
        company_attrs = {
            'schemeAgencyID': '195',
            'schemeAgencyName': 'CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)'
        }
        
        if data.get(f'{prefix}SchemeIDCode') == '31':
            company_attrs['schemeID'] = data.get(f'{prefix}SchemeID', '')
            company_attrs['schemeName'] = '31'
        else:
            company_attrs['schemeName'] = data.get(f'{prefix}SchemeIDCode', '')
        
        legal_entity = cac.PartyLegalEntity(
            cbc.RegistrationName(data.get(f'{prefix}RegistrationName', '')),
            cbc.CompanyID(data.get(f'{prefix}ID', ''), **company_attrs)
        )
        
        # CorporateRegistrationScheme
        if prefix == 'Supplier' and (data.get('Prefix') or data.get(f'{prefix}CommercialName')):
            corp_scheme = cac.CorporateRegistrationScheme()
            if data.get('Prefix'):
                corp_scheme.append(cbc.ID(data['Prefix']))
            if data.get(f'{prefix}CommercialName'):
                corp_scheme.append(cbc.Name(data[f'{prefix}CommercialName']))
            legal_entity.append(corp_scheme)
        
        return legal_entity
    
    def _build_contact(self, prefix, data, makers):
        """Construye la información de contacto"""
        cac = makers['cac']
        cbc = makers['cbc']
        
        # Verificar si hay datos
        has_data = any([
            data.get(f'{prefix}Telephone'),
            data.get(f'{prefix}Email'),
            data.get('ContactName') and prefix == 'Customer'
        ])
        
        if not has_data:
            return None
        
        contact = cac.Contact()
        
        if prefix == 'Customer' and data.get('ContactName'):
            contact.append(cbc.Name(data['ContactName']))
        
        if data.get(f'{prefix}Telephone'):
            contact.append(cbc.Telephone(data[f'{prefix}Telephone']))
        
        if data.get(f'{prefix}Email'):
            contact.append(cbc.ElectronicMail(data[f'{prefix}Email']))
        
        return contact
    
    # -------------------------------------------------------------------------
    # Construcción: Delivery
    # -------------------------------------------------------------------------
    
    def _build_delivery(self, root, data, makers):
        """Construye la sección Delivery si aplica"""
        cac = makers['cac']
        cbc = makers['cbc']
        
        delivery = cac.Delivery()
        
        # Fecha de entrega
        if data.get('DeliveryDate'):
            delivery.append(cbc.ActualDeliveryDate(data['DeliveryDate']))
        
        # Dirección de entrega
        delivery_location = cac.DeliveryLocation()
        delivery_address = self._build_delivery_address(data, makers)
        delivery_location.append(delivery_address)
        delivery.append(delivery_location)
        
        # Parte de entrega
        if data.get('DeliveryPartyName'):
            delivery_party = cac.DeliveryParty(
                cac.PartyName(cbc.Name(data['DeliveryPartyName']))
            )
            delivery.append(delivery_party)
        
        root.append(delivery)
    
    def _build_delivery_address(self, data, makers):
        """Construye la dirección de entrega"""
        cac = makers['cac']
        cbc = makers['cbc']
        
        address = cac.Address()
        
        if data.get('DeliveryAddress'):
            address.append(cbc.StreetName(data['DeliveryAddress']))
        
        #if data.get('DeliveryCityCode'):
        #    address.append(cbc.ID(data['DeliveryCityCode']))
        
        if data.get('DeliveryCityName'):
            address.append(cbc.CityName(data['DeliveryCityName']))
        
        if data.get('DeliveryCountrySubentity'):
            address.append(cbc.CountrySubentity(data['DeliveryCountrySubentity']))
        
        if data.get('DeliveryCountrySubentityCode'):
            address.append(cbc.CountrySubentityCode(data['DeliveryCountrySubentityCode']))
        
        if data.get('DeliveryAddressLine'):
            address.append(cac.AddressLine(cbc.Line(data['DeliveryAddressLine'])))
        
        address.append(
            cac.Country(
                cbc.IdentificationCode(data.get('DeliveryCountryCode', 'CO')),
                cbc.Name(data.get('DeliveryCountryName', 'Colombia'), languageID='es')
            )
        )
        
        return address
    
    # -------------------------------------------------------------------------
    # Construcción: Payment
    # -------------------------------------------------------------------------
    
    def _build_payment_sections(self, root, data, makers):
        """Construye todas las secciones relacionadas con pagos"""
        # PaymentMeans
        self._build_payment_means(root, data, makers)
        
        # PaymentTerms
        if data.get('PaymentTermsNote'):
            self._build_payment_terms(root, data, makers)
        
        # PaymentExchangeRate
        if data.get('has_exchange_rate'):
            self._build_payment_exchange_rate(root, data, makers)
    
    def _build_payment_means(self, root, data, makers):
        """Construye PaymentMeans"""
        cac = makers['cac']
        cbc = makers['cbc']
        
        payment_means = cac.PaymentMeans(
            cbc.ID(data.get('PaymentMeansID', '1')),
            cbc.PaymentMeansCode(data.get('PaymentMeansCode', '1')),
            cbc.PaymentDueDate(data.get('PaymentDueDate', str(self.invoice_date_due)))
        )
        
        if data.get('PaymentReference'):
            payment_means.append(cbc.PaymentID(data['PaymentReference']))
        
        # Cuenta bancaria
        if data.get('PayeeAccountID'):
            payee_account = cac.PayeeFinancialAccount(cbc.ID(data['PayeeAccountID']))
            
            if data.get('PayeeBankID'):
                financial_inst = cac.FinancialInstitutionBranch(
                    cac.FinancialInstitution(cbc.ID(data['PayeeBankID']))
                )
                payee_account.append(financial_inst)
            
            payment_means.append(payee_account)
        
        root.append(payment_means)
    
    def _build_payment_terms(self, root, data, makers):
        """Construye PaymentTerms"""
        cac = makers['cac']
        cbc = makers['cbc']
        
        payment_terms = cac.PaymentTerms(cbc.Note(data['PaymentTermsNote']))
        root.append(payment_terms)
    
    def _build_payment_exchange_rate(self, root, data, makers):
        """Construye PaymentExchangeRate"""
        cac = makers['cac']
        cbc = makers['cbc']
        
        exchange_rate = cac.PaymentExchangeRate(
            cbc.SourceCurrencyCode(data['SourceCurrencyCode']),
            cbc.SourceCurrencyBaseRate(data['CalculationRate']),
            cbc.TargetCurrencyCode(data['TargetCurrencyCode']),
            cbc.TargetCurrencyBaseRate('1.00'),
            cbc.CalculationRate(data['CalculationRate']),
            cbc.Date(data['ExchangeDate'])
        )
        
        root.append(exchange_rate)
    
    # -------------------------------------------------------------------------
    # Construcción: Prepaid Payments
    # -------------------------------------------------------------------------
    
    def _build_prepaid_payments(self, root, data, makers):
        """Construye la sección de pagos anticipados"""
        cac = makers['cac']
        cbc = makers['cbc']
        
        for payment in data.get('prepaid_payments', []):
            prepaid_payment = cac.PrepaidPayment(
                cbc.ID(payment['id']),
                cbc.PaidAmount(
                    f"{payment['amount']:.2f}",
                    currencyID=data['currency_id']
                ),
                cbc.ReceivedDate(payment['received_date']),
                cbc.PaidDate(payment['paid_date'])
            )
            root.append(prepaid_payment)
    
    # -------------------------------------------------------------------------
    # Construcción: Allowance Charges
    # -------------------------------------------------------------------------
    
    def _build_allowance_charges(self, root, data, makers):
        """Construye descuentos y cargos a nivel documento"""
        cac = makers['cac']
        cbc = makers['cbc']
        
        # Descuentos globales
        for discount in data.get('global_discounts', []):
            allowance = cac.AllowanceCharge(
                cbc.ID(str(discount['id'])),
                cbc.ChargeIndicator('false'),
                cbc.AllowanceChargeReasonCode(discount.get('reason_code', '00')),
                cbc.AllowanceChargeReason(discount.get('reason', 'Descuento general')),
                cbc.MultiplierFactorNumeric(f"{discount['amount'] / discount['base_amount'] * 100:.2f}"),
                cbc.Amount(
                    f"{discount['amount']:.2f}",
                    currencyID=data['currency_id']
                ),
                cbc.BaseAmount(
                    f"{discount['base_amount']:.2f}",
                    currencyID=data['currency_id']
                )
            )
            root.append(allowance)
        
        # Cargos globales
        for charge in data.get('global_charges', []):
            charge_element = cac.AllowanceCharge(
                cbc.ID(str(charge['id'])),
                cbc.ChargeIndicator('true'),
                cbc.AllowanceChargeReasonCode(charge.get('reason_code', '99')),
                cbc.AllowanceChargeReason(charge.get('reason', 'Otros cargos')),
                cbc.MultiplierFactorNumeric(f"{charge['amount'] / charge['base_amount'] * 100:.2f}"),
                cbc.Amount(
                    f"{charge['amount']:.2f}",
                    currencyID=data['currency_id']
                ),
                cbc.BaseAmount(
                    f"{charge['base_amount']:.2f}",
                    currencyID=data['currency_id']
                )
            )
            root.append(charge_element)
        
        # Ajuste de redondeo
        if data.get('rounding_adjustment_data'):
            rounding = data['rounding_adjustment_data']
            adjustment = cac.AllowanceCharge(
                cbc.ID(rounding['ID']),
                cbc.ChargeIndicator(rounding['ChargeIndicator']),
                cbc.AllowanceChargeReason(rounding['AllowanceChargeReason']),
                cbc.MultiplierFactorNumeric(rounding['MultiplierFactorNumeric']),
                cbc.Amount(rounding['Amount'], currencyID=rounding['CurrencyID']),
                cbc.BaseAmount(rounding['BaseAmount'], currencyID=rounding['CurrencyID'])
            )
            root.append(adjustment)
    
    # -------------------------------------------------------------------------
    # Construcción: Tax Totals
    # -------------------------------------------------------------------------
    
    def _build_tax_totals(self, root, data, makers):
        """Construye TaxTotal y WithholdingTaxTotal con lógica completa"""
        cbc = makers['cbc']
        cac = makers['cac']
        
        currency_id = data['currency_id']
        
        # TaxTotal para impuestos normales
        if data.get('tax_total_values'):
            for tax_id, tax_data in data['tax_total_values'].items():
                tax_total = cac.TaxTotal(
                    cbc.TaxAmount(f"{tax_data['total']:.2f}", currencyID=currency_id),
                    cbc.RoundingAmount('0.00', currencyID=currency_id)
                )
                
                # TaxSubtotal para cada porcentaje
                for percent, info in tax_data['info'].items():
                    subtotal = self._build_tax_subtotal(tax_id, percent, info, currency_id, makers)
                    tax_total.append(subtotal)
                
                root.append(tax_total)
        
        # WithholdingTaxTotal para retenciones
        if data.get('ret_total_values') and data['move_type'] != 'out_refund':
            for tax_id, tax_data in data['ret_total_values'].items():
                withholding = cac.WithholdingTaxTotal(
                    cbc.TaxAmount(f"{tax_data['total']:.2f}", currencyID=currency_id)
                )
                
                for percent, info in tax_data['info'].items():
                    format_str = '{:.2f}' if tax_id == '06' else '{:.3f}'
                    
                    subtotal = cac.TaxSubtotal(
                        cbc.TaxableAmount(
                            format_str.format(info['taxable_amount']),
                            currencyID=currency_id
                        ),
                        cbc.TaxAmount(
                            format_str.format(info['value']),
                            currencyID=currency_id
                        ),
                        cac.TaxCategory(
                            cbc.Percent(format_str.format(float(percent))),
                            cac.TaxScheme(
                                cbc.ID(tax_id),
                                cbc.Name(info['technical_name'])
                            )
                        )
                    )
                    withholding.append(subtotal)
                
                root.append(withholding)
    
    def _build_tax_subtotal(self, tax_id, percent, info, currency_id, makers):
        """Construye un TaxSubtotal con manejo de impuestos especiales"""
        cac = makers['cac']
        cbc = makers['cbc']
        
        subtotal = cac.TaxSubtotal()
        subtotal.append(cbc.TaxableAmount(
                f"{info['taxable_amount']:.2f}",
                currencyID=currency_id
            ))
        # Impuestos especiales (ICL, IBUA)
        if tax_id == '32':  # ICL
            subtotal.append(cbc.TaxAmount(
                f"{info['value']:.2f}",
                currencyID=currency_id
            ))
            subtotal.append(cbc.BaseUnitMeasure(
                f"{info.get('base_unit_measure', 0):.2f}",
                unitCode='LTR'
            ))
            subtotal.append(cbc.PerUnitAmount(
                f"{info.get('per_unit_amount', 0):.2f}",
                currencyID=currency_id
            ))
        elif tax_id == '34':  # IBUA
            subtotal.append(cbc.TaxAmount(
                f"{info['value']:.2f}",
                currencyID=currency_id
            ))
            subtotal.append(cbc.BaseUnitMeasure(
                f"{info.get('base_unit_measure', 0):.2f}",
                unitCode='ML'
            ))
            subtotal.append(cbc.PerUnitAmount(
                f"{info.get('per_unit_amount', 0):.2f}",
                currencyID=currency_id
            ))

        if tax_id not in ['32', '34']:  
            # Tax Amount
            subtotal.append(cbc.TaxAmount(
                f"{info['value']:.2f}",
                currencyID=currency_id
            ))
        
        # Tax Category
        tax_category = cac.TaxCategory()
        if tax_id not in ['32', '34']:  # No incluir percent para impuestos especiales
            tax_category.append(cbc.Percent(f"{float(percent):.2f}"))
        
        tax_category.append(
            cac.TaxScheme(
                cbc.ID(tax_id),
                cbc.Name(info['technical_name'])
            )
        )
        subtotal.append(tax_category)
        
        return subtotal
    
    # -------------------------------------------------------------------------
    # Construcción: Monetary Totals
    # -------------------------------------------------------------------------
    
    def _build_monetary_totals(self, root, data, makers):
        """Construye los totales monetarios"""
        cbc = makers['cbc']
        cac = makers['cac']
        
        currency_id = data['currency_id']
        
        # Determinar tag según tipo
        if data['is_debit_note']:
            tag_name = 'RequestedMonetaryTotal'
        else:
            tag_name = 'LegalMonetaryTotal'
        
        monetary_total = getattr(cac, tag_name)(
            cbc.LineExtensionAmount(data['TotalLineExtensionAmount'], currencyID=currency_id),
            cbc.TaxExclusiveAmount(data['TotalTaxExclusiveAmount'], currencyID=currency_id),
            cbc.TaxInclusiveAmount(data['TotalTaxInclusiveAmount'], currencyID=currency_id),
            cbc.AllowanceTotalAmount(data['TotalAllowanceAmount'], currencyID=currency_id),
            cbc.ChargeTotalAmount(data['TotalChargeAmount'], currencyID=currency_id),
            cbc.PayableAmount(data['PayableAmount'], currencyID=currency_id)
        )
        
        root.append(monetary_total)
    
    # -------------------------------------------------------------------------
    # Construcción: Document Lines
    # -------------------------------------------------------------------------
    
    def _build_document_lines(self, root, data, makers):
        """Construye las líneas del documento con toda la lógica de impuestos"""
        # Determinar tags
        line_tag = self._get_line_tag(data)
        quantity_tag = self._get_quantity_tag(data)
        
        # Procesar cada línea
        for line_data in data.get('invoice_lines', []):
            line_element = self._build_single_line(
                line_data, line_tag, quantity_tag, data, makers
            )
            root.append(line_element)
    
    def _get_line_tag(self, data):
        """Obtiene el tag de línea según el tipo de documento"""
        if data['is_debit_note']:
            return 'DebitNoteLine'
        elif data['move_type'] in ['out_refund', 'in_refund']:
            return 'CreditNoteLine'
        return 'InvoiceLine'
    
    def _get_quantity_tag(self, data):
        """Obtiene el tag de cantidad según el tipo de documento"""
        if data['is_debit_note']:
            return 'DebitedQuantity'
        elif data['move_type'] in ['out_refund', 'in_refund']:
            return 'CreditedQuantity'
        return 'InvoicedQuantity'
    
    def _build_single_line(self, line_data, line_tag, quantity_tag, data, makers):
        """Construye una línea individual del documento"""
        cac = makers['cac']
        cbc = makers['cbc']
        
        # Crear línea
        line = getattr(cac, line_tag)()
        
        # ID
        line.append(cbc.ID(str(line_data['id'])))
        
        # Nota
        if line_data.get('note'):
            line.append(cbc.Note(line_data['note']))
        
        # Cantidad
        uom_code = self._get_uom_code(line_data['uom'])
        quantity = getattr(cbc, quantity_tag)(
            f"{line_data['quantity']:.2f}",
            unitCode=uom_code
        )
        line.append(quantity)
        
        # LineExtensionAmount
        line.append(cbc.LineExtensionAmount(
            f"{line_data['line_extension_amount']:.2f}",
            currencyID=data['currency_id']
        ))
        
        # Período (documentos soporte)
        if data['move_type'] == 'in_invoice' and not data['is_debit_note']:
            period = cac.InvoicePeriod(
                cbc.StartDate(str(line_data.get('invoice_start_date', ''))),
                cbc.DescriptionCode(str(line_data.get('transmission_type_code', '1'))),
                cbc.Description(str(line_data.get('transmission_description', 'Por operación')))
            )
            line.append(period)
        
        # Referencias de precio (monto cero)
        if float(line_data['line_extension_amount']) == 0:
            pricing_ref = cac.PricingReference(
                cac.AlternativeConditionPrice(
                    cbc.PriceAmount(
                        f"{line_data.get('line_price_reference', 0):.2f}",
                        currencyID=data['currency_id']
                    ),
                    cbc.PriceTypeCode(str(line_data.get('line_trade_sample_price', '01')))
                )
            )
            line.append(pricing_ref)
        
        # Descuentos (AllowanceCharge)
        if line_data.get('discount', 0) > 0 and float(line_data['line_extension_amount']) > 0:
            amount_base = float(line_data['line_extension_amount']) + float(line_data['discount'])
            allowance = cac.AllowanceCharge(
                cbc.ID('1'),
                cbc.ChargeIndicator('false'),
                cbc.AllowanceChargeReasonCode(line_data.get('discount_code', '00')),
                cbc.AllowanceChargeReason(line_data.get('discount_text', 'Descuento general')),
                cbc.MultiplierFactorNumeric(f"{line_data.get('discount_percentage', 0):.2f}"),
                cbc.Amount(f"{line_data['discount']:.2f}", currencyID=data['currency_id']),
                cbc.BaseAmount(f"{amount_base:.2f}", currencyID=data['currency_id'])
            )
            line.append(allowance)
        
        # Impuestos
        if line_data.get('tax_info'):
            self._add_line_taxes(line, line_data, data, makers)
        
        # Retenciones (solo para facturas, no para notas)
        if line_data.get('ret_info') and data['move_type'] not in ['out_refund', 'in_refund']:
            self._add_line_retentions(line, line_data, data, makers)
        
        # Item
        item = self._build_item(line_data, makers)
        line.append(item)
        
        # Price
        price = self._build_price(line_data, data, uom_code, makers)
        line.append(price)
        
        return line
    
    def _get_uom_code(self, uom):
        """Obtiene el código de unidad de medida DIAN"""
        if uom and uom.dian_uom_id:
            return uom.dian_uom_id.dian_code
        return 'EA'  # Default: Each/Unidad
    
    def _add_line_taxes(self, line, line_data, data, makers):
        """Agrega impuestos a la línea con manejo de impuestos especiales"""
        cac = makers['cac']
        cbc = makers['cbc']
        
        for tax_id, tax_data in line_data['tax_info'].items():
            tax_total = cac.TaxTotal(
                cbc.TaxAmount(
                    f"{tax_data['total']:.2f}",
                    currencyID=data['currency_id']
                ),
                cbc.RoundingAmount('0.00', currencyID=data['currency_id'])
            )
            
            for rate, info in tax_data['info'].items():
                subtotal = self._build_line_tax_subtotal(
                    tax_id, rate, info, data['currency_id'], makers
                )
                tax_total.append(subtotal)
            
            line.append(tax_total)
    
    def _add_line_retentions(self, line, line_data, data, makers):
        """Agrega retenciones a la línea"""
        cac = makers['cac']
        cbc = makers['cbc']
        
        for tax_id, tax_data in line_data['ret_info'].items():
            withholding = cac.WithholdingTaxTotal(
                cbc.TaxAmount(
                    f"{tax_data['total']:.2f}",
                    currencyID=data['currency_id']
                )
            )
            
            for rate, info in tax_data['info'].items():
                format_str = '{:.2f}' if tax_id == '06' else '{:.4f}'
                
                subtotal = cac.TaxSubtotal(
                    cbc.TaxableAmount(
                        format_str.format(info['taxable_amount']),
                        currencyID=data['currency_id']
                    ),
                    cbc.TaxAmount(
                        format_str.format(info['value']),
                        currencyID=data['currency_id']
                    ),
                    cac.TaxCategory(
                        cbc.Percent(format_str.format(float(rate))),
                        cac.TaxScheme(
                            cbc.ID(tax_id),
                            cbc.Name(info['technical_name'])
                        )
                    )
                )
                withholding.append(subtotal)
            
            line.append(withholding)
    
    def _build_line_tax_subtotal(self, tax_id, rate, info, currency_id, makers):
        """Construye un TaxSubtotal para línea con manejo especial"""
        cac = makers['cac']
        cbc = makers['cbc']
        
        subtotal = cac.TaxSubtotal()
        subtotal.append(cbc.TaxableAmount(
                f"{info['taxable_amount']:.2f}",
                currencyID=currency_id
            ))
        if tax_id in ['32', '34']:  # ICL, IBUA
            if 'base_unit_measure' in info:
                subtotal.append(cbc.TaxableAmount(
                    f"{info['taxable_amount']:.2f}",
                    currencyID=currency_id
                ))
                subtotal.append(cbc.TaxAmount(
                    f"{info['value']:.2f}",
                    currencyID=currency_id
                ))
                subtotal.append(cbc.BaseUnitMeasure(
                    f"{info['base_unit_measure']:.2f}",
                    unitCode='LTR' if tax_id == '32' else 'ML'
                ))
            if 'per_unit_amount' in info:
                subtotal.append(cbc.PerUnitAmount(
                    f"{info['per_unit_amount']:.2f}",
                    currencyID=currency_id
                ))

        
        subtotal.append(cbc.TaxAmount(
            f"{info['value']:.2f}",
            currencyID=currency_id
        ))
        
        # Tax Category
        tax_category = cac.TaxCategory()
        if tax_id not in ['32', '34']:
            tax_category.append(cbc.Percent(f"{float(rate):.2f}"))
        
        tax_category.append(
            cac.TaxScheme(
                cbc.ID(tax_id),
                cbc.Name(info['technical_name'])
            )
        )
        subtotal.append(tax_category)
        
        return subtotal
    
    def _build_item(self, line_data, makers):
        """Construye el elemento Item"""
        cac = makers['cac']
        cbc = makers['cbc']
        
        item = cac.Item()
        
        # Descripción
        if line_data.get('name'):
            item.append(cbc.Description(line_data['name']))
        
        # Marca
        if line_data.get('product_id') and line_data['product_id'].brand_id:
            item.append(cbc.BrandName(line_data['product_id'].brand_id.name))
        
        # Modelo
        if line_data.get('product_id') and hasattr(line_data['product_id'], 'model_id') and line_data['product_id'].model_id:
            item.append(cbc.ModelName(line_data['product_id'].model_id.name))
        
        # Sellers Item Identification
        if line_data.get('product_id') and line_data['product_id'].default_code:
            item.append(
                cac.SellersItemIdentification(
                    cbc.ID(str(line_data['product_id'].default_code))
                )
            )
        
        # Standard Item Identification
        product_code = line_data['product_code']
        item.append(
            cac.StandardItemIdentification(
                cbc.ID(
                    str(product_code[0]),
                    schemeID=str(product_code[1]),
                    schemeAgencyID=str(product_code[2]),
                    schemeName=str(product_code[3])
                )
            )
        )
        
        # Información adicional para mandatos
        if self.fe_operation_type == '11' and self.mandante_id:
            if line_data.get('product_id') and line_data['product_id'].l10n_co_dian_mandate_contract:
                self._add_mandate_info(item, makers)
        
        return item
    
    def _add_mandate_info(self, item, makers):
        """Agrega información de mandato al item"""
        cac = makers['cac']
        cbc = makers['cbc']
        
        # InformationContentProviderParty para mandatos
        provider_party = cac.InformationContentProviderParty(
            cac.PowerOfAttorney(
                cac.AgentParty(
                    cac.PartyIdentification(
                        cbc.ID(
                            self.mandante_id.vat_co or '',
                            schemeAgencyID='195',
                            schemeAgencyName='CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)',
                            schemeID=self.mandante_id.dv if self.mandante_id.l10n_latam_identification_type_id.dian_code == '31' else '',
                            schemeName=self.mandante_id.l10n_latam_identification_type_id.dian_code
                        )
                    )
                )
            )
        )
        item.append(provider_party)
    
    def _build_price(self, line_data, data, uom_code, makers):
        """Construye el elemento Price"""
        cac = makers['cac']
        cbc = makers['cbc']
        
        price = cac.Price(
            cbc.PriceAmount(
                f"{line_data.get('price_unit', 0):.2f}",
                currencyID=data['currency_id']
            ),
            cbc.BaseQuantity(
                f"{line_data.get('quantity', 1):.2f}",
                unitCode=uom_code
            )
        )
        
        return price
    
    # =============================================================================
    # SECCIÓN: UTILIDADES Y MÉTODOS AUXILIARES
    # =============================================================================
    
    def _get_namespaces(self, doc_type, move_type):
        if self.is_debit_note:
            doc_type = 'debit_note'
        elif self.move_type in ['out_refund', 'in_refund']:
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
        if move_type in ['in_invoice', 'in_refund'] or self.fe_type == '02':
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
        elif doc_type in ['credit_note', 'debit_note'] and self.move_type in ['out_refund'] or self.is_debit_note:
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

        return namespaces



    def _format_xml(self, root):
        """Formatea el XML final"""
        etree.cleanup_namespaces(root)
        
        return etree.tostring(
            root,
            encoding='UTF-8',
            xml_declaration=True,
            pretty_print=True
        ).decode('UTF-8')
    
    def _save_dian_files(self, xml_string, data):
        """Guarda los archivos XML y relacionados"""
        # Guardar XML
        self.archivo_xml_invoice = base64.b64encode(xml_string.encode('UTF-8'))
        self.archivo_xml_invoice_name = f"{self.name}.xml"
        self.xml_text = xml_string
        
        # Guardar CUFE/CUDS
        self.cufe = data['cufe']
        self.cufe_seed = data['cufe_seed']
        
        # Guardar QR code con validación
        qr_code_data = data['qr_code']
        if qr_code_data:
            try:
                clean_qr = qr_code_data.strip()
                missing_padding = len(clean_qr) % 4
                if missing_padding:
                    clean_qr += '=' * (4 - missing_padding)
                self.qr_code = base64.b64decode(clean_qr)
            except (binascii.Error, ValueError):
                self.qr_code = qr_code_data.encode('utf-8')
        else:
            self.qr_code = False
            
        self.qr_data = data['qr_data']
        
        # Crear adjunto
        attachment = self.env['ir.attachment'].create({
            'name': self.archivo_xml_invoice_name,
            'type': 'binary',
            'datas': self.archivo_xml_invoice,
            'res_model': 'account.move',
            'res_id': self.id,
            'mimetype': 'application/xml',
        })
        
        # Asociar adjunto
        self.xml_adjunto_ids = [(4, attachment.id)]
    
    # =============================================================================
    # SECCIÓN: MÉTODOS AUXILIARES DE APOYO
    # =============================================================================
    
    def _get_dian_document_type(self):
        """Determina el tipo de documento DIAN"""
        if self.is_debit_note:
            return 'debit_note'
        elif self.move_type in ['out_refund', 'in_refund']:
            return 'credit_note'
        return 'invoice'
    
    def _get_document_type_dian(self):
        """Determina el tipo de documento para dian.document"""
        if self.move_type in ("out_invoice", "in_invoice"):
            if self.debit_origin_id:
                return "d"  # Nota débito
            return "f"  # Factura
        elif self.move_type in ("out_refund", "in_refund"):
            return "c"  # Nota crédito
        return False
    
    def _get_product_type_code(self, line):
        """Obtiene el código del producto según reglas DIAN"""
        product = line.product_id
        
        # Exportación
        if self.fe_type == '02':
            if not product.dian_customs_code:
                raise UserError(_('Las facturas de exportación requieren código aduanero en %s') % product.name)
            return [product.dian_customs_code, '020', '195', 'Partida Arancelaria']
        
        # Orden de prioridad
        if product.barcode:
            return [product.barcode, '010', '9', 'GTIN']
        #elif product.unspsc_code_id:
        #    return [product.unspsc_code_id.code, '001', '10', 'UNSPSC']
        elif product.default_code:
            return [product.default_code, '999', '', 'Estándar de adopción del contribuyente']
        
        return ['NA', '999', '', 'Estándar de adopción del contribuyente']
    
    def _escape_xml(self, text):
        """Escapa caracteres especiales para XML"""
        if not text:
            return ''
        
        text = str(text)
        
        # Reemplazos adicionales
        replacements = {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&apos;',
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
    
    def _generate_software_security_code(self, software_id, pin, invoice_name):
        """Genera el código de seguridad del software"""
        h = hashlib.sha384()
        h.update((software_id + pin + invoice_name).encode('utf-8'))
        return h.hexdigest()
    
    def _extend_dian_data(self, data):
        """Hook para permitir extensiones del diccionario de datos"""
        # Este método puede ser sobrescrito en módulos heredados
        return data
    
    def _hook_type_invoice(self, types):
        """Hook para extender tipos de factura"""
        return types
    
    def _is_dian_applicable(self):
        """Verifica si el documento es aplicable para DIAN"""
        return (
            self.journal_id.sequence_id.use_dian_control and
            self.move_type in ("out_invoice", "out_refund", "in_invoice", "in_refund") and
            self.state == "posted"
        )
    
    # =============================================================================
    # SECCIÓN: MÉTODOS DE VISTA Y ACCIONES UI
    # =============================================================================
    
    def action_view_credit_notes(self):
        """Abre vista de notas crédito relacionadas"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Notas Crédito'),
            'res_model': 'account.move',
            'view_mode': 'tree,form',
            'domain': [('reversed_entry_id', '=', self.id)],
        }
    
    def dian_preview(self):
        """Abre el documento en el portal DIAN"""
        self.ensure_one()
        
        if not self.cufe:
            raise UserError(_("Este documento no tiene CUFE"))
        
        document_key = self.cufe
        

        partition_key = 'co|' + str(self.fecha_xml.date()).split('-')[2] + '|' + document_key[:2]
        emission_date = self.fecha_xml.strftime('%Y%m%d') if self.fecha_xml else ''
        if self.company_id.production:
            url = 'https://catalogo-vpfe.dian.gov.co/Document/FindDocument?documentKey={}&partitionKey={}&emissionDate={}'.format(
                document_key, partition_key, emission_date
            )
        else:
            url = 'https://catalogo-vpfe-hab.dian.gov.co/Document/FindDocument?documentKey={}&partitionKey={}&emissionDate={}'.format(
                document_key, partition_key, emission_date
            )
        _logger.info(f"Abriendo documento DIAN en: {url}")
        return {
            'type': 'ir.actions.act_url',
            'url': url,
            'target': 'new',
        }
    
    def dian_pdf_view(self):
        """Descarga PDF desde DIAN"""
        for rec in self:
            if rec.cufe and rec.state_dian_document == 'exitoso':
                base_url = 'https://catalogo-vpfe.dian.gov.co' if rec.company_id.production else 'https://catalogo-vpfe-hab.dian.gov.co' # 'https://catalogo-vpfe.dian.gov.co/Document/DownloadPDF?trackId='
                return {
                    'type': 'ir.actions.act_url',
                    'target': 'new',
                    'url': f'{base_url}/Document/DownloadPDF?trackId={rec.cufe}',
                }
    
    def action_open_dian_page(self):
        """Abre página de verificación DIAN"""
        self.ensure_one()
        base_url = self.env['ir.config_parameter'].sudo().get_param(
            'dian.verification_page_url', 
            'https://catalogo-vpfe.dian.gov.co/document/searchqr'
        )
        return {
            'type': 'ir.actions.act_url',
            'url': f"{base_url}?documentkey={self.cufe or self.cufe_cuds_other_system}",
            'target': 'new',
        }
    
    def action_invoice_email_dian(self):
        """Envía email con documento DIAN"""
        for record in self:
            if record.diancode_id:
                dian_constants = record._collect_all_dian_data()
                record.diancode_id.enviar_email_attached_document(
                    record.diancode_id.xml_response_dian,
                    dian_document=record.diancode_id,
                    dian_constants=dian_constants,
                    data_header_doc=record,
                )
    

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
                'schemeName': str(SCHEME_MAPPING.get(self.move_type if not self.is_debit_note else 'debit_note', "CUFE-SHA384")),
            },
            'issue_date': original_xml_etree.findtext('./{*}IssueDate'),
            'issue_time': original_xml_etree.findtext('./{*}IssueTime'),
            'document_type': "Contenedor de Factura Electrónica",
            'parent_document_id': original_xml_etree.findtext('./{*}ID'),
            'parent_document': {
                'id': original_xml_etree.findtext('./{*}ID'),
                'uuid': self.cufe,
                'uuid_attrs': {
                    'schemeName': str(SCHEME_MAPPING.get(self.move_type, "CUFE-SHA384")),
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
        zip_file_name = name_xml.split(".")[0].replace('fv', 'z')
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
            'res_model':  'account.invoice.send',
            'target': 'new',
            'context': {
                'active_ids': self.ids,
                'default_mail_template_id': template and template.id or False,
            },
        }

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
        
    def _action_invoice_sent_fallback(self, template=None, attachments=None):
        """Método alternativo para versiones anteriores"""
        self.ensure_one()
        
        # Marcar como enviada
        self.is_move_sent = True
        
        # Preparar contexto
        compose_ctx = {
            'default_model': 'account.move',
            'default_res_ids': self.ids,
            'default_composition_mode': 'comment',
            'mark_invoice_as_sent': True,
            'custom_layout': "mail.mail_notification_paynow",
            'force_email': True,
        }
        
        if template:
            compose_ctx['default_template_id'] = template.id
            
        if attachments:
            compose_ctx['default_attachment_ids'] = [(6, 0, [att.id for att in attachments])]
        
        return {
            'name': _('Send Invoice'),
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_model': 'mail.compose.message',
            'target': 'new',
            'context': compose_ctx,
        }

    # Método adicional para envío directo DIAN
    def action_invoice_email_dian(self):
        """Envía email con documento DIAN usando el método original"""
        for record in self:
            if record.diancode_id:
                dian_constants = record._collect_all_dian_data()
                record.diancode_id.enviar_email_attached_document(
                    record.diancode_id.xml_response_dian,
                    dian_document=record.diancode_id,
                    dian_constants=dian_constants,
                    data_header_doc=record,
                )



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
            return super(AccountMove, self).action_invoice_sent()
    
    # =============================================================================
    # SECCIÓN: MÉTODOS HEREDADOS Y HOOKS
    # =============================================================================
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if "move_type" in vals:
                if vals["move_type"] == "out_refund":
                    if "refund_invoice_id" in vals and "invoice_payment_term_id" in vals:
                        rec_account_invoice = self.env["account.move"].search(
                            [("id", "=", vals["refund_invoice_id"])]
                        )
                        vals["invoice_payment_term_id"] = rec_account_invoice.invoice_payment_term_id.id
        return super().create(vals_list)
    
    @api.onchange("contingency_3")
    def _onchange_contingency_3(self):
        """Limpia número de contingencia si se desmarca"""
        if not self.contingency_3:
            self.contingency_invoice_number = ""
    
    def _get_last_sequence_domain(self, relaxed=False):
        """Extiende dominio de secuencia para notas débito"""
        where_string, param = super()._get_last_sequence_domain(relaxed)
        if self.journal_id.debit_note_sequence:
            where_string += " AND debit_origin_id IS " + ("NOT NULL" if self.debit_origin_id else "NULL")
        return where_string, param
    
    def _get_starting_sequence(self):
        """Genera secuencia inicial según tipo de documento"""
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
        
        # Secuencia estándar
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
    
    def _generate_qr_code(self, silent_errors=False):
        """Genera código QR para facturas DIAN"""
        self.ensure_one()
        if self.company_id.country_code == 'CO' and self.cufe:
            payment_url = self.qr_data or self.cufe_seed or self.cufe
            barcode = self.env['ir.actions.report'].barcode(
                barcode_type="QR", 
                value=payment_url, 
                width=120, 
                height=120
            )
            return image_data_uri(base64.b64encode(barcode))
        return super()._generate_qr_code(silent_errors)
    

    def extract_signature_value(self):
        for record in self:
            signature_value = ''
            if record.dian_xml_attachment_id:
                try:
                    root = etree.fromstring(record.dian_xml_attachment_id.raw)
                    signature_element = root.xpath('//ds:SignatureValue', namespaces={'ds': 'http://www.w3.org/2000/09/xmldsig#'})
                    if signature_element:
                        signature_value = signature_element[0].text
                except etree.XMLSyntaxError:
                    pass
            #record.signature_value = signature_value
            _logger.error(signature_value)
            return signature_value



    # =========================================================================
    # MÉTODOS DE ACCIÓN DIAN
    # =========================================================================

    def action_send_to_dian(self):
        """
        Método principal de envío a DIAN.
        Flujo correcto como Odoo 14:
        1. Generar XML sin firma
        2. Agregar firma al XML (mediante _dian_sign_xml)
        3. Crear ZIP con XML firmado
        4. Enviar SOAP (que también se firma)

        Returns:
            dict: Acción de notificación
        """
        self.ensure_one()

        try:
            # 1. Validar requisitos
            self._validate_dian_requirements()

            # 2. Recolectar datos DIAN
            dian_constants = self._collect_all_dian_data()

            # 3. Generar XML sin firma
            _logger.info(f"Generando XML para {self.name}")
            xml_content = self._get_or_generate_xml(dian_constants)

            # 4. Firmar XML (agregar nodo de firma y firmar)
            _logger.info(f"Firmando XML para {self.name}")
            xml_signed = self._dian_sign_xml(xml_content)

            # 5. Crear ZIP con XML firmado
            _logger.info(f"Creando ZIP para {self.name}")
            zip_file = self._create_dian_zip_file(xml_signed, dian_constants)

            # 6. Enviar a DIAN (el SOAP también se firma automáticamente)
            _logger.info(f"Enviando a DIAN: {self.name}")
            response = self._send_soap_to_dian(zip_file, dian_constants)

            # 7. Procesar respuesta y crear registro
            self._process_dian_response(response, dian_constants)
            dian_doc = self._create_dian_document_record(dian_constants, response)

            # 8. Crear attachment con XML firmado
            _logger.info(f"Creando attachment para {self.name}")
            self._create_xml_attachment(xml_signed)

            # Mensaje de éxito
            message = f'Documento {self.name} enviado a DIAN correctamente'
            _logger.info(message)

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': message,
                    'type': 'success',
                    'sticky': False,
                }
            }

        except Exception as e:
            error_msg = f'Error enviando {self.name} a DIAN: {str(e)}'
            _logger.error(error_msg, exc_info=True)

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': error_msg,
                    'type': 'danger',
                    'sticky': True,
                }
            }

    def _dian_sign_xml(self, xml_content, dian_constants=None):
        """
        Firma el XML de la factura agregando el nodo de firma.
        Basado en el flujo de Odoo 14.

        Args:
            xml_content: XML sin firmar (string o bytes)
            dian_constants: Datos DIAN ya compilados (opcional). Si se pasa, se usan estos datos.

        Returns:
            str: XML firmado
        """
        from lxml import etree
        from datetime import datetime
        from pytz import timezone
        from odoo.tools import cleanup_xml_node
        # Import desde el mismo paquete models
        from . import xml_utils

        self.ensure_one()

        # Parse XML
        if isinstance(xml_content, bytes):
            root = etree.fromstring(xml_content)
        else:
            root = etree.fromstring(xml_content.encode('utf-8'))

        # Obtener certificado
        private_key, cert = self.get_key()

        # Preparar datos para la firma
        import uuid
        import hashlib
        from base64 import b64encode
        from cryptography.hazmat.primitives.serialization import Encoding

        # IDs únicos
        document_id = f"xmldsig-{str(uuid.uuid1())}"
        key_info_id = f"xmldsig-{str(uuid.uuid1())}-keyinfo"

        # Datos del certificado
        cert_der = cert.public_bytes(Encoding.DER)
        x509_certificate = b64encode(cert_der).decode()
        cert_digest = b64encode(hashlib.sha256(cert_der).digest()).decode()
        x509_issuer_name = cert.issuer.rfc4514_string()
        x509_serial_number = str(cert.serial_number)

        # Tiempo de firma en Colombia
        bogota_tz = timezone('America/Bogota')
        signing_time = datetime.now(bogota_tz).isoformat(timespec='milliseconds')

        # Si se pasaron datos compilados, usarlos; si no, recolectarlos
        if dian_constants:
            # Usar datos ya compilados
            signature_vals = {
                'record': self,
                'sts_namespace': 'http://www.dian.gov.co/contratos/facturaelectronica/v1/Structures',

                # Datos del proveedor (desde dian_constants)
                'provider_check_digit': dian_constants.get('SupplierSchemeIDCode', ''),
                'provider_id': dian_constants.get('SupplierID', ''),

                # Datos del software
                'software_id': dian_constants.get('SoftwareID', ''),
                'software_security_code': dian_constants.get('SoftwareSecurityCode', ''),

                # Datos de la resolución DIAN
                'InvoiceAuthorization': dian_constants.get('InvoiceAuthorization', ''),
                'StartDate': dian_constants.get('StartDate', ''),
                'EndDate': dian_constants.get('EndDate', ''),
                'Prefix': dian_constants.get('Prefix', ''),
                'From': dian_constants.get('From', ''),
                'To': dian_constants.get('To', ''),

                # QR Code
                'qr_code_val': dian_constants.get('QRCode', ''),

                # IDs de firma
                'document_id': document_id,
                'key_info_id': key_info_id,

                # Certificado
                'x509_certificate': x509_certificate,
                'x509_certificates': [{
                    'x509_issuer_description': x509_issuer_name,
                    'x509_serial_number': int(x509_serial_number),
                }],

                # Firma
                'signature_value': 'to be filled later',
                'signing_time': signing_time,
                'sigcertif_digest': cert_digest,
                'claimed_role': 'supplier',
            }
        else:
            # Recolectar datos desde los campos del modelo
            # Obtener resolución DIAN activa
            resolution = self.journal_id.sequence_id.dian_resolution_ids.filtered(
                lambda r: r.active_resolution
            )
            if not resolution:
                raise UserError(_("No hay resolución DIAN activa para el diario %s") % self.journal_id.name)

            # Determinar prefijo según tipo de documento
            prefix = self.journal_id.sequence_id.prefix or ''
            if self.move_type in ['out_refund', 'in_refund']:
                prefix = ''
            if self.is_debit_note:
                prefix = self.journal_id.debit_note_sequence_id.prefix or ''

            # Obtener dígito de verificación
            supplier = self.company_id.partner_id
            dv = ''
            if hasattr(supplier, 'dv') and supplier.dv:
                dv = supplier.dv
            elif supplier.l10n_latam_identification_type_id.dian_code == '31':
                # Calcular DV si no existe
                from stdnum.co.nit import calc_check_digit
                try:
                    dv = str(calc_check_digit(supplier.vat_co or supplier.vat or ''))
                except:
                    dv = ''

            signature_vals = {
                'record': self,
                'sts_namespace': 'http://www.dian.gov.co/contratos/facturaelectronica/v1/Structures',

                # Datos del proveedor (usando campos existentes)
                'provider_check_digit': dv,
                'provider_id': supplier.vat_co or '',

                # Datos del software
                'software_id': self.company_id.software_identification_code or '',
                'software_security_code': self.company_id.software_pin or '',

                # Datos de la resolución DIAN (usando campos reales)
                'InvoiceAuthorization': resolution.resolution_number or '',
                'StartDate': str(resolution.date_from or ''),
                'EndDate': str(resolution.date_to or ''),
                'Prefix': prefix,
                'From': str(resolution.number_from or '1'),
                'To': str(resolution.number_to or '1'),

                # QR Code
                'qr_code_val': self.qr_data or '',

                # IDs de firma
                'document_id': document_id,
                'key_info_id': key_info_id,

                # Certificado
                'x509_certificate': x509_certificate,
                'x509_certificates': [{
                    'x509_issuer_description': x509_issuer_name,
                    'x509_serial_number': int(x509_serial_number),
                }],

                # Firma
                'signature_value': 'to be filled later',
                'signing_time': signing_time,
                'sigcertif_digest': cert_digest,
                'claimed_role': 'supplier',
            }

        # Renderizar el template de firma
        extensions = self.env['ir.qweb']._render('l10n_co_e-invoice.ubl_extension_dian', signature_vals)
        extensions = cleanup_xml_node(extensions, remove_blank_nodes=False)

        # Insertar la firma al principio del XML
        root.insert(0, extensions)
        xml_utils._remove_tail_and_text_in_hierarchy(root)

        # Calcular digests y firmar
        xml_utils._reference_digests(extensions.find(".//ds:SignedInfo", {'ds': 'http://www.w3.org/2000/09/xmldsig#'}))
        xml_utils._fill_signature(extensions.find(".//ds:Signature", {'ds': 'http://www.w3.org/2000/09/xmldsig#'}), private_key)

        # Retornar XML firmado como string
        return etree.tostring(root, encoding='UTF-8').decode('utf-8')

    def action_query_status_dian(self):
        """Consulta el estado del documento en DIAN"""
        self.ensure_one()

        if not self.diancode_id:
            raise UserError(_("Este documento no ha sido enviado a DIAN"))

        try:
            # Implementar consulta de estado
            _logger.info(f"Consultando estado DIAN para {self.name}")
            # TODO: Implementar lógica de consulta

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': f'Estado consultado para {self.name}',
                    'type': 'info',
                    'sticky': False,
                }
            }
        except Exception as e:
            raise UserError(_(f"Error consultando estado: {str(e)}"))

    def action_resend_to_dian(self):
        """Reenvía el documento a DIAN"""
        self.ensure_one()

        if self.state_dian_document == 'exitoso':
            raise UserError(_("Este documento ya fue validado exitosamente por DIAN"))

        # Limpiar estado anterior
        self.diancode_id = False
        self.state_dian_document = False

        # Reenviar
        return self.action_send_to_dian()

    def action_download_dian_xml(self):
        """Descarga el XML firmado de DIAN"""
        self.ensure_one()

        if not self.archivo_xml_invoice:
            raise UserError(_("No hay XML disponible para descargar"))

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{self._name}/{self.id}/archivo_xml_invoice/{self.archivo_xml_invoice_name}?download=true',
            'target': 'self',
        }

    # -------------------------------------------------------------------------
    # Métodos auxiliares
    # -------------------------------------------------------------------------

    def _validate_dian_requirements(self):
        """
        Valida que se cumplan todos los requisitos para envío a DIAN.

        Raises:
            UserError: Si falta algún requisito
        """
        self.ensure_one()

        errors = []
        company = self.company_id
        partner = self.partner_id

        # Validar estado de factura
        if self.state != 'posted':
            errors.append("La factura debe estar contabilizada")

        # Validar compañía
        if not company.software_identification_code:
            errors.append("Falta código de identificación del software en la compañía")

        if not company.password_environment:
            errors.append("Falta clave de ambiente en la compañía")

        if not company.certificate_file:
            errors.append("Falta certificado digital en la compañía")

        # Validar partner
        if not partner.vat:
            errors.append("El cliente/proveedor no tiene NIT/CC")

        # Validar resolución
        if self.journal_id and self.journal_id.sequence_id:
            resolutions = self.journal_id.sequence_id.dian_resolution_ids
            active_resolution = resolutions.filtered('active_resolution')
            if not active_resolution:
                errors.append("No hay resolución DIAN activa para el diario")

        if errors:
            raise UserError(_("Requisitos faltantes para DIAN:\n• " + "\n• ".join(errors)))

    def _create_xml_attachment(self, xml_content):
        """
        Crea el attachment con el XML firmado.

        Args:
            xml_content: XML en string o bytes
        """
        self.ensure_one()

        # Convertir a bytes si es string
        if isinstance(xml_content, str):
            xml_bytes = xml_content.encode('utf-8')
        else:
            xml_bytes = xml_content

        # Guardar en campo binario
        self.archivo_xml_invoice = base64.b64encode(xml_bytes)
        self.archivo_xml_invoice_name = f'{self.name}.xml'

        # Crear attachment
        attachment = self.env['ir.attachment'].create({
            'name': f'{self.name}_dian.xml',
            'res_model': 'account.move',
            'res_id': self.id,
            'type': 'binary',
            'datas': base64.b64encode(xml_bytes),
            'mimetype': 'application/xml',
            'description': 'Factura Electrónica DIAN',
        })

        # Agregar a xml_adjunto_ids
        self.xml_adjunto_ids = [(4, attachment.id)]

        return attachment


class AccountMoveLine(models.Model):
    """
    Extiende las líneas de factura con campos DIAN
    """
    _inherit = "account.move.line"
    
    # Campos de precio
    line_price_reference = fields.Float(string='Precio de referencia')
    line_trade_sample_price = fields.Selection(
        string='Tipo precio de referencia',
        related='move_id.trade_sample_price'
    )
    line_trade_sample = fields.Boolean(
        string='Muestra comercial', 
        related='move_id.invoice_trade_sample'
    )
    
    # Descuentos
    invoice_discount_text = fields.Selection(
        selection=[
            ('00', 'Descuento no condicionado'),
            ('01', 'Descuento condicionado')
        ],
        string='Motivo de Descuento',
        default='00'
    )
    global_discount_percentage = fields.Float(string='Descuento GLobal')
    def _l10n_co_dian_net_price_subtotal(self):
        """Retorna el subtotal después de descuento en moneda de la compañía"""
        self.ensure_one()
        return self.move_id.direction_sign * self.balance
    
    def _l10n_co_dian_gross_price_subtotal(self):
        """Retorna el subtotal sin descuento en moneda de la compañía"""
        self.ensure_one()
        if self.discount == 100.0:
            return 0.0
        else:
            net_price_subtotal = self._l10n_co_dian_net_price_subtotal()
            return self.company_id.currency_id.round(
                net_price_subtotal / (1.0 - (self.discount or 0.0) / 100.0)
            )


class ReceiptCode(models.Model):
    """
    Códigos de recepción de mercancía
    """
    _name = 'receipt.code'
    _description = 'Código de Recepción'
    
    name = fields.Char('Nombre', required=True)
    move_id = fields.Many2one("account.move", string="Factura")
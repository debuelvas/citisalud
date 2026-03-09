import logging

_logger = logging.getLogger(__name__)

from odoo import models, api, _, fields
from odoo.exceptions import UserError, ValidationError
import pytz

try:
    from lxml import etree
except ImportError:
    _logger.warning("Cannot import  etree *************************************")


try:
    import pyqrcode
except ImportError:
    _logger.warning("Cannot import pyqrcode library ***************************")


try:
    import re
except ImportError:
    _logger.warning("Cannot import re library")

try:
    import uuid
except ImportError:
    _logger.warning("Cannot import uuid library")

try:
    import requests
except ImportError:
    _logger.warning("no se ha cargado requests")

try:
    import xmltodict
except ImportError:
    _logger.warning("Cannot import xmltodict library")

try:
    import hashlib
except ImportError:
    _logger.warning("Cannot import hashlib library ****************************")

import re


NC_RAZONES = {
    '1' :  'Devolución parcial de los bienes y/o no aceptación parcial del servicio',
    '2' :  'Anulación del documento soporte en adquisiciones efectuadas a sujetos no obligados a expedir factura deventa o documento equivalente',
    '3' :  'Rebaja o descuento parcial o total',
    '4' :  'Ajuste de precio',
    '5' :  'Otros'
}
class DianDocument(models.Model):
    _inherit = 'dian.document'

    @api.model
    def _generate_xml_filename(self, data_resolution, NitSinDV, doctype, is_debit_note):
        if doctype == 'in_invoice' or doctype == 'in_refund':
            docdian = 'ds' if doctype == 'in_invoice' else 'nas'

            len_prefix = len(data_resolution["Prefix"])
            len_invoice = len(data_resolution["InvoiceID"])
            dian_code_int = int(data_resolution["InvoiceID"][len_prefix:len_invoice])
            dian_code_hex = self.IntToHex(dian_code_int)
            dian_code_hex.zfill(10)
            file_name_xml = docdian + NitSinDV.zfill(10) + dian_code_hex.zfill(10) + ".xml"
            return file_name_xml
        else:
            return super(DianDocument, self)._generate_xml_filename(data_resolution, NitSinDV, doctype, is_debit_note)

    def _generate_zip_filename(self, data_resolution, NitSinDV, doctype, is_debit_note):
        if doctype == 'in_invoice' or doctype == 'in_refund':
            docdian = 'ds' if doctype == 'in_invoice' else 'nas'
            secuenciador = data_resolution["InvoiceID"]
            dian_code_int = int(re.sub(r"\D", "", secuenciador))
            # dian_code_int = int(data_resolution['InvoiceID'][len_prefix:len_invoice])
            dian_code_hex = self.IntToHex(dian_code_int)
            dian_code_hex.zfill(10)
            file_name_zip = docdian + NitSinDV.zfill(10) + dian_code_hex.zfill(10) + ".zip"
            return file_name_zip
        else:
            return super(DianDocument, self)._generate_zip_filename(data_resolution, NitSinDV, doctype, is_debit_note)

    @api.model
    def _get_doctype(self, doctype, is_debit_note, in_contingency_4):
        docdian = False
        if self.document_id.move_type in ['in_invoice','in_refund']:
            if doctype == 'in_invoice' and not is_debit_note:
                docdian = "05"
            elif doctype == "in_refund":
                docdian = "95"
            elif doctype == "in_invoice" and is_debit_note or self.document_id.debit_origin_id or self.document_id.is_debit_note:
                docdian = "92"
            return docdian
        else:
            return super(DianDocument, self)._get_doctype(doctype, is_debit_note, in_contingency_4)
import json
import uuid
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from . dian_document import server_url, tipo_ambiente
import logging
import pytz
import xmltodict
from lxml import etree
_logger = logging.getLogger(__name__)
import requests
try:
    import hashlib
except ImportError:
    _logger.warning("Cannot import hashlib library ****************************")

LOCALTZ = pytz.timezone('America/Bogota')

class RecepcionFacturaDian(models.Model):
    _inherit = 'recepcion.factura.dian'

    cufe = fields.Char('cufe')
    

class DianApplicationResponse(models.Model):
    _inherit = 'dian.application.response'


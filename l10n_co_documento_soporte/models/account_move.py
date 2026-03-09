import logging
from datetime import datetime, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from pytz import timezone

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"

    # Campo utilizado para hacer visible campos en lineas de factura dependiendo si es o no Compra con Documento Soporte
    is_ds = fields.Boolean(
        "Factura DS", related="journal_id.sequence_id.use_dian_control", store=True
    )

    nc_discrepancy_response = fields.Selection(
        [('1', 'Devolución parcial de los bienes y/o no aceptación parcial del servicio'),
         ('2', 'nulación del documento soporte en adquisiciones efectuadas a sujetos no obligados a expedir factura deventa o documento equivalente'),
         ('3', 'Rebaja o descuento parcial o total'),
         ('4', 'Ajuste de precio'),
         ('5', 'Otros')], 'Razon de la devolucion (En la pestaña otra informacion)', help = 'Especifique la razon de la devolucion')

    nc_naturaleza_correccion = fields.Text('Naturaleza corrección (En la pestaña otra informacion)', help = 'Naturaleza de la corrección')

    def hook_type_invoice(self, data):
        data = super(AccountMove, self).hook_type_invoice(data)
        data.append("in_invoice")
        return data


    def _get_datetime_bogota(self):
        fmt = "%Y-%m-%dT%H:%M:%S"
        now_utc = datetime.now(timezone("UTC")) - timedelta(hours=5)
        now_bogota = now_utc
        return now_bogota.strftime(fmt)
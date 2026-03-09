from odoo import _, api, fields, models

import logging
_logger = logging.getLogger(__name__)

class AccountMoveInherit(models.Model):
    _inherit = "account.move"

    order_reference_date = fields.Date("Fecha de Order de referencia", copy=False)
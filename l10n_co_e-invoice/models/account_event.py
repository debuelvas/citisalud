import logging
import xmltodict
from datetime import date, time, datetime
from num2words import num2words

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)
    
class AccountMoveInherit(models.Model):
    _inherit = "account.move"
    
    application_response_ids = fields.One2many('dian.application.response','move_id',)
    tiene_eventos = fields.Boolean(compute='_compute_tiene_eventos', store=True)

    def add_application_response(self):
        for rec in self:
            response_code = self._context.get('response_code')
            ar = self.env['dian.application.response'].generate_from_electronic_invoice(rec.id,  response_code)


    @api.depends('application_response_ids')
    def _compute_tiene_eventos(self):
        for rec in self:
            rec.tiene_eventos = bool(rec.application_response_ids)
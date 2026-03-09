
from odoo import models, fields, api
import logging
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class ResPartnerInherit(models.Model):
    _inherit = 'res.partner'


    type_residence = fields.Selection([('si','Si'),('no','No')], string="Residente", default='si')

    @api.onchange('type_residence')
    def on_change_type_residence(self):
        for rec in self:
            if len(rec.country_id) > 0:
                if rec.type_residence == 'si' and rec.country_id.code != 'CO' and rec.name != False:
                    raise ValidationError('Los residentes solo puede ser de Colombia, actualiza el pais del contacto')
    
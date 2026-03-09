from odoo import fields, models, api
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = 'account.move'

    def get_field_move(self):
        if hasattr(self, 'partner_id'):
            return True
        elif hasattr(self, 'employee_id'):
            return False

from odoo import fields, models, api, _
import logging
_logger = logging.getLogger(__name__)
from odoo.exceptions import UserError, ValidationError


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'


    forma_generacion_ds = fields.Selection([('1', 'Por operacion'),('2', 'Acumulado semanal')], 'Forma de generación y transmisión',
                                           help = 'Aplica solo para documento soporte')

    purchase_date = fields.Date('Fecha Compra')
    note_ds = fields.Char('Nota')

    @api.onchange('forma_generacion_ds')
    def on_forma_generacion_ds(self):
        if self.forma_generacion_ds == '1':
            self.purchase_date = self.move_id.invoice_date

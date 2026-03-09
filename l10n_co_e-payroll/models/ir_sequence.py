from datetime import date

from odoo import fields, models, api


class IrSequence(models.Model):
    _inherit = 'ir.sequence'

    last_year = fields.Integer("Last", default=1)
    is_year = fields.Boolean('Is year', default=False)

    def _next(self, sequence_date=None):
        this_year = int(date.today().year)
        if this_year != self.last_year and self.is_year:
            self.last_year = this_year
            self.number_next_actual = 1
        result = super(IrSequence, self)._next(sequence_date)
        return result

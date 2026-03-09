from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class Account_journal(models.Model):
    _inherit = 'account.journal'

    is_payroll_spreader = fields.Boolean('Es dispersor de nómina')
    plane_type = fields.Selection([ ('alianza','Alianza Fiduciaria'),
                                    ('bancolombiasap', 'Bancolombia SAP'),
                                    ('bancolombiapab', 'Bancolombia PAB'),
                                    ('davivienda1', 'Davivienda 1'),
                                    ('occired', 'Occired'),
                                    ('avvillas1', 'AV VILLAS 1'),
                                    ('bancobogota', 'Banco Bogotá'),
                                    ('popular', 'Banco Popular'),
                                    ('bbva', 'Banco BBVA'),
                                    ('scotiabank', 'Banco Scotiabank'),
                                    ], string='Tipo de Plano')

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

class res_partner_bank(models.Model):
    _inherit = 'res.partner.bank'

    type_account = fields.Selection(selection_add=[('DP', 'Daviplata'),('N', 'Nequi')], ondelete={"DP": "set default","N": "set default"})
    payroll_dispersion_account = fields.Many2one('account.journal', string='Cuenta bancaria dispersora nómina', domain="[('company_id','=',company_id),('is_payroll_spreader', '=', True)]")
    company_id = fields.Many2one('res.company', string='Compañia', copy=False,  store=True,  default=lambda self: self.env.company,readonly=False,related=False)
from odoo import fields, models, api


class HrPayslipRun(models.Model):
    _inherit = 'hr.payslip.run'

    def validar_dian(self):
        for record in self:
            record.slip_ids.validate()

from odoo import fields, models, api


class HrContract(models.Model):
    _inherit = 'hr.contract'

    type_contract = fields.Many2one('hr.type.contract', string="Tipo de contrato")

    vacations_ids = fields.One2many('hr.contract.vacations', 'contract_id', 'Vacaciones')
    bonus_ids = fields.One2many('hr.contract.bonus', 'contract_id', 'Primas')
    layoffs_ids = fields.One2many('hr.contract.layoffs', 'contract_id', 'Cesantias')
    layoffs_interests_ids = fields.One2many('hr.contract.layoffs.interests', 'contract_id', 'Intereses Cesantias')



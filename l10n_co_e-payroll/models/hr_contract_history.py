from odoo import fields, models, api


class HrContractVacations(models.Model):
    _name = 'hr.contract.vacations'

    initial_period = fields.Date('Periodo Inicial')
    final_period = fields.Date('Periodo Final')
    accumulated_days = fields.Integer('Dias Acumulados')
    days_enjoyed = fields.Integer('Dias Disfrutados')
    available_days = fields.Integer('Dias Disponibles')
    day_last_vacations = fields.Date('Fecha Ultimas Vacaciones')

    contract_id = fields.Many2one('hr.contract', 'Contrato')


class HrContractBonus(models.Model):
    _name = 'hr.contract.bonus'

    initial_period = fields.Date('Periodo Inicial')
    final_period = fields.Date('Periodo Final')
    accumulated_days = fields.Integer('Dias Acumulados')
    days_paids = fields.Integer('Dias Pagados')
    available_days = fields.Integer('Dias Disponibles')
    day_last_bonus = fields.Date('Fecha Ultima Prima')

    contract_id = fields.Many2one('hr.contract', 'Contrato')

class HrContractLayoffs(models.Model):
    _name = 'hr.contract.layoffs'

    initial_period = fields.Date('Periodo Inicial')
    final_period = fields.Date('Periodo Final')
    accumulated_days = fields.Integer('Dias Acumulados')
    days_paids = fields.Integer('Dias Pagados')
    available_days = fields.Integer('Dias Disponibles')
    day_last_bonus = fields.Date('Fecha Ultima Prima')

    contract_id = fields.Many2one('hr.contract', 'Contrato')


class HrContractLayoffsInterests(models.Model):
    _name = 'hr.contract.layoffs.interests'

    initial_period = fields.Date('Periodo Inicial')
    final_period = fields.Date('Periodo Final')
    accumulated_days = fields.Integer('Dias Acumulados')
    days_paids = fields.Integer('Dias Pagados')
    available_days = fields.Integer('Dias Disponibles')
    day_last_bonus = fields.Date('Fecha Ultima Prima')

    contract_id = fields.Many2one('hr.contract', 'Contrato')


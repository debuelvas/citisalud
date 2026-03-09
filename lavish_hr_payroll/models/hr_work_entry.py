# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from datetime import date, datetime, time
from odoo.exceptions import UserError, ValidationError
from dateutil.relativedelta import relativedelta

class hr_work_entry(models.Model):
    _inherit = 'hr.work.entry'

    @api.model_create_multi
    def create(self, vals_list):
        Contract = self.env['hr.contract']
        for vals in vals_list:
            if vals.get('contract_id') and vals.get('date_start'):
                obj_contract = Contract.search([
                    ('id', '=', vals.get('contract_id'))
                ], limit=1)
                
                if obj_contract:
                    try:
                        # Handle both datetime string formats
                        try:
                            date_start = datetime.strptime(
                                str(vals.get('date_start')), 
                                '%Y-%m-%d %H:%M:%S'
                            ).date()
                        except ValueError:
                            date_start = datetime.strptime(
                                str(vals.get('date_start')), 
                                '%Y-%m-%d'
                            ).date()
                        
                        # Check if date_start is before contract start date
                        if date_start < obj_contract.date_start:
                            vals['state'] = 'conflict'
                            vals['active'] = False
                    except ValueError as e:
                        # Handle invalid date format
                        # You might want to log this error or handle it differently
                        vals['state'] = 'conflict'
                        vals['active'] = False

        return super().create(vals_list)

class hr_work_entry_refresh(models.TransientModel):
    _name = 'hr.work.entry.refresh'
    _description = 'Actualizar entradas de trabajo'

    date_start = fields.Date('Fecha Inicial', required=True)
    date_stop = fields.Date('Fecha Final', required=True)
    contract_ids = fields.Many2many('hr.contract', string='Contratos', required=True, domain=[('state', '=', 'open')])
    earliest_available_date = fields.Date('Earliest date', compute='_compute_earliest_available_date')
    earliest_available_date_message = fields.Char(readonly=True, store=False, default='')
    latest_available_date = fields.Date('Latest date', compute='_compute_latest_available_date')
    latest_available_date_message = fields.Char(readonly=True, store=False, default='')
    search_criteria_completed = fields.Boolean(compute='_compute_search_criteria_completed')

    @api.depends('date_start', 'date_stop', 'contract_ids')
    def _compute_search_criteria_completed(self):
        for wizard in self:
            wizard.search_criteria_completed = all([wizard.date_start, wizard.date_stop, wizard.contract_ids, wizard.earliest_available_date, wizard.latest_available_date])

    @api.onchange('date_start', 'date_stop', 'contract_ids')
    def _check_dates(self):
        for wizard in self:
            wizard.earliest_available_date_message = ''
            wizard.latest_available_date_message = ''
            if wizard.search_criteria_completed:
                if wizard.date_start > wizard.date_stop:
                    wizard.date_start, wizard.date_stop = wizard.date_stop, wizard.date_start
                if wizard.earliest_available_date and wizard.date_start < wizard.earliest_available_date:
                    wizard.date_start = wizard.earliest_available_date
                    wizard.earliest_available_date_message = f"La fecha más temprana disponible es {self._date_to_string(wizard.earliest_available_date)}"
                if wizard.latest_available_date and wizard.date_stop > wizard.latest_available_date:
                    wizard.date_stop = wizard.latest_available_date
                    wizard.latest_available_date_message = f"La última fecha disponible es {self._date_to_string(wizard.latest_available_date)}"

    @api.model
    def _date_to_string(self, date):
        if not date:
            return ''
        user_date_format = self.env['res.lang']._lang_get(self.env.user.lang).date_format
        return date.strftime(user_date_format)

    def _work_entry_fields_to_nullify(self):
        return ['active']

    @api.depends('date_start')
    def _compute_date_to(self):
        for wizard in self:
            if wizard.date_start:
                wizard.date_start = wizard.date_start + relativedelta(months=+1, day=1, days=-1)

    @api.depends('contract_ids')
    def _compute_earliest_available_date(self):
        for wizard in self:
            dates = wizard.contract_ids.mapped('date_generated_from')
            wizard.earliest_available_date = min(dates) if dates else None

    @api.depends('contract_ids')
    def _compute_latest_available_date(self):
        for wizard in self:
            dates = wizard.contract_ids.mapped('date_generated_to')
            wizard.latest_available_date = max(dates) if dates else None

    # def refresh_work_entry(self):
    #     for record in self:
    #         if not self.env.context.get('work_entry_skip_validation'):
    #             if record.date_start < record.earliest_available_date or record.date_stop > record.latest_available_date:
    #                 raise ValidationError(_("The from date must be >= '%(earliest_available_date)s' and the to date must be <= '%(latest_available_date)s', which correspond to the generated work entries time interval.", earliest_available_date=self._date_to_string(record.earliest_available_date), latest_available_date=self._date_to_string(record.latest_available_date)))
    #         date_from = max(record.date_start, record.earliest_available_date) if record.earliest_available_date else record.date_start
    #         date_to = min(record.date_stop, record.latest_available_date) if record.latest_available_date else record.date_stop
    #         for contract in record.contract_ids:
    #             work_entries = self.env['hr.work.entry'].search([
    #                 ('employee_id', '=', contract.employee_id.id),
    #                 ('date_stop', '>=', date_from),
    #                 ('date_start', '<=', date_to),
    #                 ('state', '!=', 'validated')])

    #             work_entries.write({'active': False})
    #             contract.employee_id.generate_work_entries(date_from, date_to, True)
    #             action = self.env["ir.actions.actions"]._for_xml_id('hr_work_entry.hr_work_entry_action')
    #             return action
       
    def refresh_work_entry(self):
        for record in self:
            if not self.env.context.get('work_entry_skip_validation'):
                if record.date_start < record.earliest_available_date or record.date_stop > record.latest_available_date:
                    raise ValidationError(_("The from date must be >= '%(earliest_available_date)s' and the to date must be <= '%(latest_available_date)s', which correspond to the generated work entries time interval.", earliest_available_date=self._date_to_string(record.earliest_available_date), latest_available_date=self._date_to_string(record.latest_available_date)))
            date_from = max(record.date_start, record.earliest_available_date) if record.earliest_available_date else record.date_start
            date_to = min(record.date_stop, record.latest_available_date) if record.latest_available_date else record.date_stop
            for contract in record.contract_ids:
                work_entries = self.env['hr.work.entry'].search([
                    ('employee_id', '=', contract.employee_id.id),
                    ('date_stop', '>=', date_from),
                    ('date_start', '<=', date_to),
                    ('state', '!=', 'validated')])

                work_entries.write({'active': False})
                contract.employee_id.generate_work_entries(date_from, date_to, True)
        action = self.env["ir.actions.actions"]._for_xml_id('hr_work_entry.hr_work_entry_action')
        return action
       



    
    

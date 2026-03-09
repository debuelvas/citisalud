# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import logging

_logger = logging.getLogger(__name__)

class HrHolidays(models.Model):
    _inherit = "hr.leave"
    _order = 'date_from desc'

    state = fields.Selection([
        ('draft', 'To Submit'),
        ('confirm', 'To Approve'),
        ('validate', 'Approved'),
        ('refuse', 'Refused'),
        ('cancel', 'Cancelled'),
    ], string='Status', readonly=True, tracking=True, copy=False, default='draft')
    approve_date = fields.Datetime('Approval Date', readonly=True, copy=False)
    payslip_id = fields.Many2one('hr.payslip', 'Paid in Payslip', readonly=True)
    allocation_rule_id = fields.Many2one('hr.leave.allocation.rule', 'Leave Allocation Rule')
    type_name = fields.Char(related='holiday_status_id.name', string='Leave Type Name')
    company_id = fields.Many2one(related='contract_id.company_id', string='Company', readonly=True, store=True)
    number_of_days_dummy = fields.Float('Number of Days', readonly=True, states={'draft': [('readonly', False)]})
    number_of_days_temp = fields.Float(compute='_compute_number_of_days', string='Days in Leave', readonly=True, store=True)
    number_of_days_in_payslip = fields.Float(compute='_compute_number_of_days', string='Days in Payslip')
    number_of_hours_in_payslip = fields.Float(compute='_compute_number_of_days', string='Hours in Payslip')
    number_of_hours = fields.Float(compute='_compute_number_of_days', string='Hours of Leave')
    employee_id = fields.Many2one('hr.employee', 'Employee', required=True, readonly=True, states={'draft': [('readonly', False)]})
    holiday_status_id = fields.Many2one("hr.leave.type", "Leave Type", required=True, readonly=True, states={'draft': [('readonly', False)]})
    vacaciones = fields.Boolean(related='holiday_status_id.vacaciones', string='Vacations')
    payed_vac = fields.Float('Vacaciones en Money')
    special_vac_base = fields.Boolean('Disfruté con todo')
    contract_id = fields.Many2one('hr.contract', string="Contract", compute='_compute_contract', store=True)
    working_hours_id = fields.Many2one('resource.calendar', string="Working Hours for Leave", compute='_compute_working_hours')
    working_hours_slip_id = fields.Many2one('resource.calendar', string="Working Hours for Payslip", compute='_compute_working_hours')
    line_ids = fields.One2many('hr.holidays.days', 'holiday_id', 'Absences', readonly=True)
    apply_cut = fields.Boolean(related='holiday_status_id.apply_cut', string='Apply in Cut?', readonly=True, store=True)
    dummy = fields.Boolean('Update')
    apply_payslip_pay_31 = fields.Boolean('Pay day 31 in payslip')
    absence_id = fields.Many2one('hr.leave', string="Absence to extend",
                                 domain="['|', ('general_illness', '=', True), ('atep', '=', True), ('employee_id', '=', employee_id)]")
    general_illness_ext = fields.Boolean(related='holiday_status_id.general_illness_ext', string='Extension General Illness')
    general_illness = fields.Boolean(related='holiday_status_id.general_illness', string='General Illness')
    atep = fields.Boolean(related='holiday_status_id.atep', string='ATEP')
    ibc = fields.Float('Force IBC absence')
    pay_out_slip = fields.Boolean('Pay out of period', help="Allows the system to calculate the days")

    @api.depends('date_from', 'date_to', 'employee_id')
    def _compute_contract(self):
        for leave in self:
            if leave.date_from:
                leave.contract_id = self.env['hr.employee'].get_contract(leave.employee_id, leave.date_from)

    @api.depends('contract_id', 'holiday_status_id')
    def _compute_working_hours(self):
        for leave in self:
            if leave.contract_id:
                if leave.holiday_status_id.vacaciones:
                    leave.working_hours_id = leave.contract_id.vacations_calendar_id
                else:
                    leave.working_hours_id = leave.contract_id.working_hours
                
                if leave.holiday_status_id.working_hours_id:
                    leave.working_hours_slip_id = leave.holiday_status_id.working_hours_id
                else:
                    leave.working_hours_slip_id = leave.working_hours_id

    @api.depends('line_ids', 'apply_payslip_pay_31')
    def _compute_number_of_days(self):
        for leave in self:
            leave.number_of_days_temp = sum(line.days_assigned for line in leave.line_ids)
            leave.number_of_days_in_payslip = sum(line.days_payslip for line in leave.line_ids)
            leave.number_of_hours_in_payslip = sum(line.hours_payslip for line in leave.line_ids)
            leave.number_of_hours = sum(line.hours_assigned for line in leave.line_ids)

    @api.constrains('date_from', 'date_to')
    def _check_date(self):
        for holiday in self:
            domain = [
                ('date_from', '<=', holiday.date_to),
                ('date_to', '>=', holiday.date_from),
                ('employee_id', '=', holiday.employee_id.id),
                ('id', '!=', holiday.id),
                ('state', 'not in', ['draft', 'cancel', 'refuse']),
            ]
            nholidays = self.search_count(domain)
            if nholidays:
                raise ValidationError(_('You can not have 2 leaves that overlap!'))

    # @api.model
    # def create(self, vals):
    #     if vals.get('state') and vals['state'] not in ['draft', 'confirm', 'cancel']:
    #         raise UserError(_('You cannot create a leave directly in the %s state.') % vals['state'])
    #     if 'number_of_days' not in vals and 'date_from' in vals and 'date_to' in vals:
    #         vals['number_of_days'] = self._get_number_of_days(vals['date_from'], vals['date_to'], vals.get('employee_id'))
    #     return super(HrHolidays, self).create(vals)

    def write(self, vals):
        if 'state' in vals and vals['state'] not in ['draft', 'confirm', 'cancel'] and self.filtered(lambda holiday: holiday.state == 'draft'):
            raise UserError(_('You cannot directly set a leave in the %s state.') % vals['state'])
        return super(HrHolidays, self).write(vals)

    def holidays_validate(self):
        for holiday in self:
            if not holiday.approve_date:
                holiday.approve_date = fields.Datetime.now()
        return self.write({'state': 'validate'})

    def holidays_confirm(self):
        self.check_overlap()
        self.compute()
        return self.write({'state': 'confirm'})

    def holidays_refuse(self):
        for holiday in self:
            if holiday.state == 'paid':
                raise UserError(_('You cannot refuse a leave that has been paid.'))
        return self.write({'state': 'refuse'})

    def holidays_reset(self):
        for holiday in self:
            if holiday.state == 'paid':
                raise UserError(_('You cannot reset a leave that has been paid.'))
        return self.write({'state': 'draft'})

    def check_overlap(self):
        for holiday in self:
            domain = [
                ('state', 'not in', ['draft', 'refuse']),
                ('employee_id', '=', holiday.employee_id.id),
                '|', '&', ('date_from', '<=', holiday.date_from), ('date_to', '>', holiday.date_from),
                     '&', ('date_from', '<', holiday.date_to), ('date_to', '>=', holiday.date_to)
            ]
            nholidays = self.search_count(domain)
            if nholidays:
                raise UserError(_('You can not have 2 leaves that overlap for the same employee.'))

    def compute(self):
        for holiday in self:
            holiday._compute_holiday()

    def _compute_holiday(self):
        self.ensure_one()
        HolidayDays = self.env['hr.holidays.days']
        ResourceCalendar = self.env['resource.calendar']

        if not self.employee_id or not self.date_from or not self.date_to:
            return

        employee = self.employee_id
        contract = self.contract_id or employee.contract_id
        if not contract:
            raise UserError(_("No valid contract found for the employee."))

        calendar = self.working_hours_id or contract.resource_calendar_id
        if not calendar:
            raise UserError(_("No working hours set for the employee's contract."))

        tz = timezone(employee.tz or self.env.user.tz or 'UTC')

        date_from = fields.Datetime.from_string(self.date_from).replace(tzinfo=tz)
        date_to = fields.Datetime.from_string(self.date_to).replace(tzinfo=tz)
        self.line_ids.unlink()
        working_hours = calendar._work_intervals(date_from, date_to)
        sequence = 0
        for start, stop, meta in working_hours:
            sequence += 1
            work_hours = (stop - start).total_seconds() / 3600
            work_days = work_hours / calendar.hours_per_day

            holiday_day = HolidayDays.create({
                'name': start.date(),
                'holiday_id': self.id,
                'hours_assigned': work_hours,
                'days_assigned': work_days,
                'hours_payslip': work_hours,
                'days_payslip': work_days,
                'sequence': sequence,
                'week_day': str(start.weekday()),
            })

            # Apply specific rules
            if self.holiday_status_id.apply_publicholiday:
                public_holidays = calendar.global_leave_ids.filtered(
                    lambda l: l.date_from.date() <= start.date() <= l.date_to.date())
                if public_holidays:
                    holiday_day.write({
                        'hours_assigned': 0,
                        'days_assigned': 0,
                    })

            if self.holiday_status_id.apply_publicholiday_pay_days:
                public_holidays_pay = self.working_hours_slip_id.global_leave_ids.filtered(
                    lambda l: l.date_from.date() <= start.date() <= l.date_to.date())
                if public_holidays_pay:
                    holiday_day.write({
                        'hours_payslip': 0,
                        'days_payslip': 0,
                    })

            if self.holiday_status_id.apply_payslip_pay_31 and start.day == 31:
                holiday_day.write({
                    'hours_payslip': 8,
                    'days_payslip': 1,
                })
                self.apply_payslip_pay_31 = True
        if self.holiday_status_id.disc_day_off:
            last_day = self.line_ids.sorted(key=lambda r: r.name)[-1].name
            next_day = last_day + timedelta(days=1)
            while len(self.line_ids) < (7 if len(set(calendar.attendance_ids.mapped('dayofweek'))) == 6 else 8):
                sequence += 1
                HolidayDays.create({
                    'name': next_day,
                    'holiday_id': self.id,
                    'hours_assigned': calendar.hours_per_day,
                    'days_assigned': 1,
                    'hours_payslip': calendar.hours_per_day,
                    'days_payslip': 1,
                    'sequence': sequence,
                    'week_day': str(next_day.weekday()),
                })
                next_day += timedelta(days=1)

        self._compute_number_of_days()

class HrHolidaysDays(models.Model):
    _name = "hr.holidays.days"
    _description = "Leave Days"

    name = fields.Date('Date')
    hours_assigned = fields.Float('Assigned Hours', digits=(16, 2), readonly=True)
    hours_payslip = fields.Float('Payslip Hours', digits=(16, 2), readonly=True)
    days_assigned = fields.Float('Assigned Days', digits=(16, 2), readonly=True)
    days_payslip = fields.Float('Payslip Days', digits=(16, 2), readonly=True)
    sequence = fields.Float('#', digits=(16, 2), readonly=True)
    holiday_id = fields.Many2one('hr.leave', 'Leave', required=True, ondelete='cascade')
    payslip_id = fields.Many2one('hr.payslip', 'Paid in Payslip', readonly=True)
    week_day = fields.Selection([
        ('0', 'Monday'),
        ('1', 'Tuesday'),
        ('2', 'Wednesday'),
        ('3', 'Thursday'),
        ('4', 'Friday'),
        ('5', 'Saturday'),
        ('6', 'Sunday'),
    ], 'Week Day', readonly=True)
    state = fields.Selection(related='holiday_id.state', string='State', readonly=True, store=True)
    contract_id = fields.Many2one(related='holiday_id.contract_id', string='Contract', readonly=True, store=True)
    holiday_status_id = fields.Many2one(related='holiday_id.holiday_status_id', string='Type', readonly=True, store=True)
    apply_cut = fields.Boolean(related='holiday_status_id.apply_cut', string='Apply in Cut?', readonly=True, store=True)
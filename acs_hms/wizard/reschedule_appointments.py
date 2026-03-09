# coding: utf-8

from odoo import models, api, fields
from datetime import date, datetime, timedelta


class AcsRescheduleAppointments(models.TransientModel):
    _name = 'acs.reschedule.appointments'
    _description = "Reschedule Appointments"

    acs_reschedule_time = fields.Float(string="Reschedule Selected Appointments by (Hours)", required=True)

    def acs_reschedule_appointments(self):
        appointments = self.env['hms.appointment'].search([('id','in',self.env.context.get('active_ids'))])
        #ACS: do it in method only to use that method for notifications.
        appointments.acs_reschedule_appointments(self.acs_reschedule_time)

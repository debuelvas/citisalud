# -*- coding: utf-8 -*-

from odoo import api, models, fields, _, SUPERUSER_ID

PHY_WRITABLE_FIELDS = [
    'physician_id',
    'acs_signature',
    'acs_medical_license',
    'acs_appointment_duration',
]

class User(models.Model):
    _inherit = ['res.users']

    physician_id = fields.Many2one('hms.physician', string="Company Physician",
        compute='_compute_company_physician', search='_search_company_physician', store=False)
    acs_signature = fields.Binary(related='physician_id.signature', string="Acs Signature", readonly=False, related_sudo=False)
    acs_medical_license = fields.Char(related='physician_id.medical_license', string="Acs Medical License,", readonly=False, related_sudo=False)
    acs_appointment_duration = fields.Float(related="physician_id.appointment_duration", string="Acs Appointment Duration",readonly=False, related_sudo=False)

    @api.depends('physician_ids')
    @api.depends_context('company')
    def _compute_company_physician(self):
        physician_per_user = {
            physician.user_id: physician
            for physician in self.env['hms.physician'].search([('user_id', 'in', self.ids), ('company_id', '=', self.env.company.id)])
        }
        for user in self:
            user.physician_id = physician_per_user.get(user)

    def _search_company_physician(self, operator, value):
        return [('physician_ids', operator, value)]

    @property
    def SELF_READABLE_FIELDS(self):
        return super().SELF_READABLE_FIELDS + PHY_WRITABLE_FIELDS

    @property
    def SELF_WRITEABLE_FIELDS(self):
        return super().SELF_WRITEABLE_FIELDS + PHY_WRITABLE_FIELDS
# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from random import randint


class ACSPatientTag(models.Model):
    _name = "hms.patient.tag"
    _description = "Acs Patient Tag"

    def _get_default_color(self):
        return randint(1, 11)

    name = fields.Char(string="Name")
    color = fields.Integer('Color', default=_get_default_color)


class ACSTherapeuticEffect(models.Model):
    _name = "hms.therapeutic.effect"
    _description = "Acs Therapeutic Effect"


    code = fields.Char(string="Code")
    name = fields.Char(string="Name", required=True)


class ACSReligion(models.Model):
    _name = 'acs.religion'
    _description = "ACS Religion"

    name = fields.Char(string="Name", required=True,translate=True)
    code = fields.Char(string='code')
    notes = fields.Char(string='Notes')

    _sql_constraints = [('name_uniq', 'UNIQUE(name)', 'Name must be unique!')]

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
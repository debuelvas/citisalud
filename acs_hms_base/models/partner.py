# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from dateutil.relativedelta import relativedelta
from datetime import datetime
HEALTH_TYPE_SELECTION = [
    ('01', 'Contributivo cotizante'),
    ('02', 'Contributivo beneficiario'),
    ('03', 'Contributivo adicional'),
    ('04', 'Subsidiado'),
    ('05', 'Sin régimen'),
    ('06', 'Especiales o de Excepción cotizante'),
    ('07', 'Especiales o de Excepción beneficiario'),
    ('08', 'Particular'),
    ('09', 'Tomador/Amparado ARL'),
    ('10', 'Tomador/Amparado SOAT'),
    ('11', 'Tomador/Amparado Planes voluntarios de salud'),
]

class ResPartner(models.Model):
    _inherit= "res.partner"

    @api.depends('birthday', 'date_of_death')
    def _get_age(self):
        today = datetime.now().date()
        for rec in self:
            age = 0
            age_unit = ''
            age_desc = ''
            today_is_birthday = False
            if rec.birthday:
                end_date = rec.date_of_death or today
                delta = relativedelta(end_date, rec.birthday)
                if delta.years == 0 and delta.months == 0 and delta.days < 30:
                    age = delta.days
                    age_unit = '3'  # Días
                    age_desc = f"{age} días"
                elif delta.years == 0:
                    age = delta.months
                    age_unit = '2'  # Meses
                    age_desc = f"{age} meses"
                else:
                    age = delta.years
                    age_unit = '1'  # Años
                    age_desc = f"{age} años"
                if today.month == rec.birthday.month and today.day == rec.birthday.day:
                    today_is_birthday = True
            rec.age = age
            rec.age_type = age_unit
            rec.age_description = age_desc
            rec.today_is_birthday = today_is_birthday

    age_description = fields.Char(string="Descripción de Edad", compute='_get_age', help="Edad del paciente en un formato legible")
    age_type = fields.Selection([
        ('1', 'Años'),
        ('2', 'Meses'),
        ('3', 'Días')
    ], string='Unidad de Medida de la Edad', compute='_get_age', store=True, help="Unidad de medida para la edad del paciente")
    health_type = fields.Selection(
        selection=HEALTH_TYPE_SELECTION,
        string='Tipo de Usuario',
    )
    eps_id = fields.Many2one('res.partner', string="EPS/ASEGURADORA")
    name = fields.Char(tracking=True)
    code = fields.Char(string='Identification Code', default='/',
        help='Identifier provided by the Health Center.', copy=False, tracking=True)
    gender = fields.Selection([
        ('H', 'Hombre'),
        ('M', 'Mujer'),
        ('I', 'Indeterminado o Intersexual')
    ], string='Sexo', default='H', tracking=True)
    birthday = fields.Date(string='Date of Birth', tracking=True)
    date_of_death = fields.Date(string='Date of Death')
    age = fields.Integer(string='Age', compute='_get_age')
    today_is_birthday = fields.Boolean(string='Birthday Today', compute='_get_age')
    hospital_name = fields.Char()
    blood_group = fields.Selection([
        ('A+', 'A+'),('A-', 'A-'),
        ('B+', 'B+'),('B-', 'B-'),
        ('AB+', 'AB+'),('AB-', 'AB-'),
        ('O+', 'O+'),('O-', 'O-')], string='Blood Group')

    is_patient = fields.Boolean(compute='_is_patient', search='_patient_search',
        string='Is Patient', help="Check if customer is linked with patient.")
    acs_amount_due = fields.Monetary(compute='_compute_acs_amount_due',currency_field='currency_id')
    acs_patient_id = fields.Many2one('hms.patient', compute='_is_patient', string='Patient', readonly=True)

    def _compute_acs_amount_due(self):
        MoveLine = self.env['account.move.line']
        for record in self:
            amount_due = 0
            unreconciled_aml_ids = MoveLine.sudo().search([('reconciled', '=', False),
               ('account_id.deprecated', '=', False),
               ('account_id.account_type', '=', 'asset_receivable'),
               ('move_id.state', '=', 'posted'),
               ('partner_id', '=', record.id),
               ('company_id','=',self.env.company.id)])
            for aml in unreconciled_aml_ids:
                amount_due += aml.amount_residual
            record.acs_amount_due = amount_due

    def _is_patient(self):
        Patient = self.env['hms.patient'].sudo()
        for rec in self:
            patient = Patient.search([('partner_id', '=', rec.id)], limit=1)
            rec.acs_patient_id = patient.id if patient else False
            rec.is_patient = True if patient else False

    def _patient_search(self, operator, value):
        patients = self.env['hms.patient'].sudo().search([])
        return [('id', 'in', patients.mapped('partner_id').ids)]

    def create_patient(self):
        self.ensure_one()
        patient_id = self.env['hms.patient'].create({
            'partner_id': self.id,
            'name': self.name,
        })
        return patient_id

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
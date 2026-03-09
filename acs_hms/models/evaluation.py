# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from dateutil.relativedelta import relativedelta

class AcsPatientEvaluation(models.Model):
    _name = 'acs.patient.evaluation'
    _description = "Patient Evaluation"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = "id desc"

    @api.depends('height', 'weight')
    def get_bmi_data(self):
        for rec in self:
            bmi = 0
            bmi_state = False
            if rec.height and rec.weight:
                try:
                    bmi = float(rec.weight) / ((float(rec.height) / 100) ** 2)
                except:
                    bmi = 0

                bmi_state = 'normal'
                if bmi < 18.5:
                    bmi_state = 'low_weight'
                elif 25 < bmi < 30:
                    bmi_state = 'over_weight'
                elif bmi > 30:
                    bmi_state = 'obesity'
            rec.bmi = bmi
            rec.bmi_state = bmi_state

    @api.depends('patient_id', 'patient_id.birthday', 'date')
    def get_patient_age(self):
        for rec in self:
            age = ''
            if rec.patient_id.birthday:
                end_data = rec.date or fields.Datetime.now()
                delta = relativedelta(end_data, rec.patient_id.birthday)
                if delta.years <= 2:
                    age = str(delta.years) + _(" Year") + str(delta.months) + _(" Month ") + str(delta.days) + _(" Days")
                else:
                    age = str(delta.years) + _(" Year")
            rec.age = age

    name = fields.Char(readonly=True, copy=False)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('done', 'Done'),
        ('cancel', 'Cancelled'),
    ], string='Status', default='draft', required=True, copy=False)
    date = fields.Datetime(string='Date', default=fields.Datetime.now)

    patient_id = fields.Many2one('hms.patient', ondelete='restrict',  string='Patient',
        required=True, index=True)
    image_128 = fields.Binary(related='patient_id.image_128',string='Image', readonly=True)
    age = fields.Char(compute="get_patient_age", string='Age', store=True,
        help="Computed patient age at the moment of the evaluation")
    physician_id = fields.Many2one('hms.physician', ondelete='restrict', string='Physician', 
        index=True)

    weight = fields.Float(string='Weight', help="Weight in KG")
    height = fields.Float(string='Height', help="Height in cm")
    temp = fields.Float(string='Temp')
    hr = fields.Integer(string='HR', help="Heart Rate")
    rr = fields.Integer(string='RR', help='Respiratory Rate')
    systolic_bp = fields.Integer("Systolic BP")
    diastolic_bp = fields.Integer("Diastolic BP")
    spo2 = fields.Integer(string='SpO2', 
        help='Oxygen Saturation, percentage of oxygen bound to hemoglobin')
    rbs = fields.Integer('RBS', help="Random blood sugar measures blood glucose regardless of when you last ate.")
    head_circum = fields.Float('Head Circumference')

    pain_level = fields.Selection([
        ('0', '0'),
        ('1', '1'),
        ('2', '2'),
        ('3', '3'),
        ('4', '4'),
        ('5', '5'),
        ('6', '6'),
        ('7', '7'),
        ('8', '8'),
        ('9', '9'),
        ('10', '10'),
    ], string="Pain Level", default="0")
    pain = fields.Selection([
        ('pain_0', 'Pain Free'),
        ('pain_1', 'Pain is very mild, barely noticeable. Most of the time you don’t think about it.'),
        ('pain_2', 'Minor pain. Annoying and may have occasional stronger twinges.'),
        ('pain_3', 'Pain is noticeable and distracting, however, you can get used to it and adapt.'),
        ('pain_4', 'Moderate pain. If you are deeply involved in an activity, it can be ignored for a period of time, but is still distracting.'),
        ('pain_5', 'Moderately strong pain. It can’t be ignored for more than a few minutes, but with effort you still can manage to work or participate in some social activities.'),
        ('pain_6', 'Moderately strong pain that interferes with normal daily activities. Difficulty concentrating.'),
        ('pain_7', 'Severe pain that dominates your senses and significantly limits your ability to perform normal daily activities or maintain social relationships. Interferes with sleep.'),
        ('pain_8', 'Intense pain. Physical activity is severely limited. Conversing requires great effort.'),
        ('pain_9', 'Excruciating pain. Unable to converse. Crying out and/or moaning uncontrollably.'),
        ('pain_10', 'Unspeakable pain. Bedridden and possibly delirious. Very few people will ever experience this level of pain.'),
    ], string="Pain", compute="_get_pain_info", store=True)

    bmi = fields.Float(compute="get_bmi_data", string='Body Mass Index', store=True, readonly=True)
    bmi_state = fields.Selection([
        ('low_weight', 'Low Weight'), 
        ('normal', 'Normal'),
        ('over_weight', 'Over Weight'), 
        ('obesity', 'Obesity')], compute="get_bmi_data", string='BMI State', store=True, readonly=True)
    company_id = fields.Many2one('res.company', ondelete='restrict',
        string='Hospital', default=lambda self: self.env.company)

    appointment_id = fields.Many2one('hms.appointment', string='Appointment')

    acs_weight_name = fields.Char(string='Patient Weight unit of measure label', compute='_compute_uom_name')
    acs_height_name = fields.Char(string='Patient Height unit of measure label', compute='_compute_uom_name')
    acs_temp_name = fields.Char(string='Patient Temp unit of measure label', compute='_compute_uom_name')
    acs_spo2_name = fields.Char(string='Patient SpO2 unit of measure label', compute='_compute_uom_name')
    acs_rbs_name = fields.Char(string='Patient RBS unit of measure label', compute='_compute_uom_name')
    acs_head_circum_name = fields.Char(string='Patient Head Circumference unit of measure label', compute='_compute_uom_name')

    def _compute_uom_name(self):
        """
        NOTA: Este método no puede usar @api.depends porque depende de ir.config_parameter
        que no tiene un campo observable. Se mantiene sin @api.depends.
        Consideración: Podría optimizarse con cache a nivel de modelo.
        """
        parameter = self.env['ir.config_parameter']
        for rec in self:
            weight_uom = parameter.sudo().get_param('acs_hms.acs_patient_weight_uom')
            rec.acs_weight_name = weight_uom or 'Kg'
            height_uom = parameter.sudo().get_param('acs_hms.acs_patient_height_uom')
            rec.acs_height_name = height_uom or 'Cm'
            temp_uom = parameter.sudo().get_param('acs_hms.acs_patient_temp_uom')
            rec.acs_temp_name = temp_uom or '°C'
            spo2_uom = parameter.sudo().get_param('acs_hms.acs_patient_spo2_uom')
            rec.acs_spo2_name = spo2_uom or '%'
            rbs_uom = parameter.sudo().get_param('acs_hms.acs_patient_rbs_uom')
            rec.acs_rbs_name = rbs_uom or 'mg/dl'
            head_circum_uom = parameter.sudo().get_param('acs_hms.patient_head_circum_measure_uom')
            rec.acs_head_circum_name = head_circum_uom or 'cm'

    @api.onchange('patient_id')
    def onchange_patient(self):
        if self.patient_id:
            active_evaluation = self.search([('patient_id','=',self.patient_id.id),('state','=','done')], limit=1)
            if active_evaluation and not self.height:
                self.height= active_evaluation.height
            if active_evaluation and not self.weight:
                self.weight= active_evaluation.weight

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            if not values.get('name'):
                values['name'] = self.env['ir.sequence'].next_by_code('acs.patient.evaluation') or 'New Appointment'
        return super().create(vals_list)

    def unlink(self):
        for data in self:
            if data.state in ['done']:
                raise UserError(_('You can not delete record in done state'))
        return super(AcsPatientEvaluation, self).unlink()

    def action_draft(self):
        self.state = 'draft'

    def action_done(self):
        self.state = 'done'

    def action_cancel(self):
        self.state = 'cancel'

    def create_evaluation(self):
        pass

    @api.depends('pain_level')
    def _get_pain_info(self):
        for rec in self:
            if rec.pain_level:
                rec.pain = 'pain_' + str(rec.pain_level)
            else:
                rec.pain = False

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
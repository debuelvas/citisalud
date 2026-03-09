# -*- coding: utf-8 -*-

from odoo import api, fields, models, _


class ResCompany(models.Model):
    #_description = "Hospital"  #Do not chnage moduel name to avoid testcase error
    _inherit = "res.company"

    patient_registration_product_id = fields.Many2one('product.product', 
        domain=[('type','=','service')],
        string='Patient Registration Invoice Product', 
        ondelete='cascade', help='Registration Product')
    treatment_registration_product_id = fields.Many2one('product.product', 
        domain=[('type','=','service')],
        string='Treatment Registration Invoice Product', 
        ondelete='cascade', help='Registration Product')
    consultation_product_id = fields.Many2one('product.product', 
        domain=[('type','=','service')],
        string='Consultation Invoice Product', 
        ondelete='cascade', help='Consultation Product')
    auto_followup_days = fields.Float('Auto Followup on (Days)', default=10)
    followup_days = fields.Float('Followup Days', default=30)
    followup_product_id = fields.Many2one('product.product', 
        domain=[('type','=','service')],
        string='Follow-up Invoice Product', 
        ondelete='cascade', help='Followup Product')
    acs_followup_activity_type_id = fields.Many2one('mail.activity.type', 
        string='Follow-up Activity Type', 
        ondelete='cascade', help='Followup Activity Type')
    birthday_mail_template_id = fields.Many2one('mail.template', 'Birthday Wishes Template',
        help="This will set the default mail template for birthday wishes.")
    registration_date = fields.Char(string='Date of Registration')
    appointment_invoice_policy = fields.Selection([('at_end','Invoice in the End'),
        ('anytime','Invoice Anytime'),
        ('advance','Invoice in Advance')], default='at_end', string="Appointment Invoicing Policy", required=True)
    acs_check_appo_payment = fields.Boolean(string="Check Appointment Payment Status before Accepting Request")
    appointment_usage_location_id = fields.Many2one('stock.location', 
        string='Usage Location for Consumed Products in Appointment')
    appointment_stock_location_id = fields.Many2one('stock.location', 
        string='Stock Location for Consumed Products in Appointment')

    procedure_usage_location_id = fields.Many2one('stock.location', 
        string='Usage Location for Consumed Products in Procedure')
    procedure_stock_location_id = fields.Many2one('stock.location', 
        string='Stock Location for Consumed Products in Procedure')

    acs_prescription_qrcode = fields.Boolean(string="Print Authetication QrCode on Presctiprion", default=True)
    acs_cancel_old_appointment = fields.Boolean(string='Cancel Old Appointment', default=True)
    acs_auto_appo_confirmation_mail = fields.Boolean(string="Sent Appointment Confirmation Mail")
    acs_appointment_planned_duration = fields.Float(string="Default Appointment Planned Duration", default=0.25)

    acs_reminder_day = fields.Float(string="Reminder Days")
    acs_reminder_hours = fields.Float(string="Reminder Hours", default=2)

    acs_flag_days = fields.Integer(string="Warning Flag Days", help="Days to count cancelled appointment", default=365)
    acs_flag_count_limit = fields.Integer(string="Count Limit for Flag", help="Configure number to show alert flag after couting that many cancelled appoitments", default=10)


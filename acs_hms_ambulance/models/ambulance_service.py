# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from datetime import timedelta, datetime


class AcsAmbulanceService(models.Model):
    _name = 'acs.ambulance.service'
    _description = 'Ambulance Service'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'acs.hms.mixin']


    @api.model
    def _get_service_id(self):
        service_product = False
        if self.env.company.acs_ambulance_invoicing:
            service_product = self.env.company.acs_ambulance_invoicing_product_id.id
        return service_product

    name = fields.Char(string='Name', copy=False, default="/", tracking=True)
    patient_id = fields.Many2one('hms.patient', ondelete='cascade', 
        string='Patient', tracking=True)
    user_id = fields.Many2one('res.users', ondelete='restrict', string='Responsible', 
        help="Nurse/User", default=lambda self: self.env.user, required=True, domain=[('share','=',False)])
    vehicle_id = fields.Many2one('fleet.vehicle', ondelete='restrict', string='Vehicle', 
        help="Ambulance Vehicle", required=True, tracking=True)
    driver_id = fields.Many2one('res.partner', ondelete='restrict', string='Driver', 
        help="Responsible Person", required=True, domain="[('is_driver','=',True)]")
    date = fields.Datetime('Date', default=fields.Datetime.now, required=True, tracking=True)
    date_to = fields.Datetime('Date Till', default=fields.datetime.now() + timedelta(minutes=120), required=True, tracking=True)
    pick_location = fields.Char('Pick Location')
    drop_location = fields.Char('Drop Location')
    remark = fields.Text('Remark')
    state = fields.Selection([
        ('draft','Draft'),
        ('confirm','Confirm'),
        ('to_invoice', 'To Invoice'),
        ('done','Done'),
        ('cancel','Cancel')], default="draft", string="Status", tracking=True)
    service_product_id = fields.Many2one('product.product', ondelete='restrict', 
        string='Ambulance Service', help="Ambulance Charge Service", 
        domain=[('type', '=', "ambulance")], default=_get_service_id)
    price = fields.Float(string="Price")
    invoice_id = fields.Many2one('account.move', string='Invoice', ondelete='cascade', copy=False)
    company_id = fields.Many2one('res.company', ondelete='restrict',
        string='Hospital', default=lambda self: self.env.company)
    acs_ambulance_invoicing = fields.Boolean(related='company_id.acs_ambulance_invoicing',string='Allow Ambulance Service Invoicing', readonly=True)
    odometer_start = fields.Float('Odometer Start')
    odometer_stop = fields.Float('Odometer Stop')
    invoice_exempt = fields.Boolean(string='Invoice Exempt', readonly=True)
    department_id = fields.Many2one('hr.department', ondelete='restrict', 
        domain=[('patient_department', '=', True)], string='Department', tracking=True)

    @api.onchange('vehicle_id')
    def onchange_vehicle(self):
        if self.vehicle_id:
            self.driver_id = self.vehicle_id.driver_id.id
            self.odometer_start = self.vehicle_id.odometer
            if self.vehicle_id.service_product_id:
                self.service_product_id = self.vehicle_id.service_product_id.id
            if self.vehicle_id.user_id:
                self.user_id = self.vehicle_id.user_id.id

    @api.onchange('service_product_id')
    def onchange_service_product(self):
        if self.service_product_id:
            self.price = self.service_product_id.lst_price

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            if values.get('name', '/') == '/':
                values['name'] = self.env['ir.sequence'].next_by_code('acs.ambulance.service') or ''
        return super().create(vals_list)

    def unlink(self):
        for data in self:
            if data.state in ['done']:
                raise UserError(('You can not delete record in done state'))
        return super(AcsAmbulanceService, self).unlink()

    def action_confirm(self):
        self.state = 'confirm'

    def action_done(self):
        if self.odometer_stop:
            self.env['fleet.vehicle.odometer'].create({
                'vehicle_id': self.vehicle_id.id,
                'value': self.odometer_stop,
                'driver_id': self.driver_id.id,
            })
        if self.env.company.acs_ambulance_invoicing and not self.invoice_exempt:
            self.state = 'to_invoice'
        else:
            self.state = 'done'

    def action_cancel(self):
        self.state = 'cancel' 

    def action_create_invoice(self):
        product_id = self.service_product_id or self.env.company.acs_ambulance_invoicing_product_id
        if not product_id:
            raise UserError(_("Please Set Service Product first for Ambulance Service in Configuration."))
        product_data = [{'product_id': product_id, 'price_unit': self.price}]
        inv_data = {}
        invoice = self.acs_create_invoice(partner=self.patient_id.partner_id, patient=self.patient_id, product_data=product_data, inv_data=inv_data)
        self.invoice_id = invoice.id
        if self.state == 'to_invoice':
            self.state = 'done'

    def view_invoice(self):
        invoices = self.mapped('invoice_id')
        return self.acs_action_view_invoice(invoices)

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4: 
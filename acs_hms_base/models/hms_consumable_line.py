# -*- coding: utf-8 -*-

from odoo import api, fields, models, _


class ACSAppointmentConsumable(models.Model):
    _name = "hms.consumable.line"
    _description = "List of Consumables"

    @api.depends('price_unit','qty')
    def acs_get_total_price(self):
        for rec in self:
            rec.subtotal = rec.qty * rec.price_unit

    name = fields.Char(string='Name',default=lambda self: self.product_id.name)
    product_id = fields.Many2one('product.product', ondelete="restrict", string='Products/Services')
    product_uom_category_id = fields.Many2one('uom.category', related='product_id.uom_id.category_id')
    product_uom_id = fields.Many2one('uom.uom', string='Unit of Measure', help='Amount of medication (eg, 250 mg) per dose', domain="[('category_id', '=', product_uom_category_id)]")
    qty = fields.Float(string='Quantity', default=1.0)
    tracking = fields.Selection(related='product_id.tracking', store=True)
    lot_id = fields.Many2one('stock.lot', string='Lot/Serial Number', 
        domain="[('product_id', '=', product_id),('product_qty','>',0),'|',('expiration_date','=',False),('expiration_date', '>', context_today().strftime('%Y-%m-%d'))]")
    price_unit = fields.Float(string='Unit Price', readonly=True)
    subtotal = fields.Float(compute=acs_get_total_price, string='Subtotal', readonly=True, store=True)
    move_id = fields.Many2one('stock.move', string='Stock Move')
    physician_id = fields.Many2one('hms.physician', string='Physician')
    department_id = fields.Many2one('hr.department', string='Department')
    patient_id = fields.Many2one('hms.patient', string='Patient')
    date = fields.Date("Date", default=fields.Date.context_today)
    note = fields.Char("Note")
    invoice_id = fields.Many2one('account.move', string='Invoice', copy=False)
    pricelist_id = fields.Many2one('product.pricelist', string='Pricelist')

    @api.onchange('product_id')
    def onchange_product(self):
        if self.product_id:
            price = self.product_id.list_price
            if self.pricelist_id:
                price = self.pricelist_id._get_product_price(self.product_id, 1)
            elif self.patient_id.property_product_pricelist:
                price = self.patient_id.property_product_pricelist._get_product_price(self.product_id, 1)
            self.price_unit = price
            self.product_uom_id = self.product_id.uom_id.id

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
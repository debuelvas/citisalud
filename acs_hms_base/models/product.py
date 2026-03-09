# -*- coding: utf-8 -*-

from odoo import api, fields, models, _


class ProductProduct(models.Model):
    _inherit = 'product.product'

    def acs_get_pricelist(self, partner):
        #if not partner passed use user partner
        if not partner:
            partner = self.env.user.sudo().partner_id

        #check if pricelist is passeed in context or partner has any applied pricelist.
        pricelist_id = False
        acs_pricelist_id = self.env.context.get('acs_pricelist_id')
        if acs_pricelist_id:
            pricelist_id = self.env['product.pricelist'].browse(acs_pricelist_id)
        elif partner.property_product_pricelist:
            pricelist_id = partner.property_product_pricelist
        return pricelist_id

    def acs_get_pricelist_price(self, pricelist, quantity, uom_id):
        if pricelist:
            uom = False
            if uom_id:
                uom = self.env['uom.uom'].browse(uom_id)
            price = pricelist._get_product_price(self, quantity, uom=uom)
        else:
            price = self.list_price
        return price

    def _acs_get_partner_price(self, quantity=1, uom_id=False, partner=False):
        pricelist_id = self.acs_get_pricelist(partner)
        #if any pricelist pass price based on pricelist else default price.
        if pricelist_id and pricelist_id.discount_policy!='without_discount':
            price = self.acs_get_pricelist_price(pricelist_id, quantity, uom_id)
        else:
            price = self.list_price
        return price

    #Only One level pricelist price is computed.
    def _acs_get_partner_price_discount(self, quantity=1, uom_id=False, partner=False):
        discount = 0
        base_price = self.list_price
        pricelist_id = self.acs_get_pricelist(partner)
        #if any pricelist pass price based on pricelist else default price.
        if pricelist_id and pricelist_id.discount_policy=='without_discount':
            pricelist_price = self.acs_get_pricelist_price(pricelist_id, quantity, uom_id)
            comp_discount = (base_price - pricelist_price) / base_price * 100
            if (comp_discount > 0 and base_price > 0) or (comp_discount < 0 and base_price < 0):
                # only show negative discounts if price is negative
                # otherwise it's a surcharge which shouldn't be shown to the customer
                discount = comp_discount
        return discount


class product_template(models.Model):
    _inherit = "product.template"

    form_id = fields.Many2one('drug.form', ondelete='cascade', string='Drug Form', tracking=True)
    active_component_ids = fields.Many2many('active.comp', 'product_active_comp_rel', 'product_id','comp_id','Active Component')
    drug_company_id = fields.Many2one('drug.company', ondelete='cascade', string='Drug Company', help='Company producing this drug')
    hospital_product_type = fields.Selection([
        ('medicament','Medicament'),
        ('fdrinks', 'Food & Drinks'),
        ('os', 'Other Service'),
        ('not_medical', 'Not Medical'),], string="Hospital Product Type", default='medicament')
    indications = fields.Text(string='Indication', help='Indications') 
    therapeutic_effect_ids = fields.Many2many('hms.therapeutic.effect', 'therapeutic_action_rel', 'therapeutic_effect_id', 'effect_id', string='Therapeutic Effect', help='Therapeutic action')
    pregnancy_warning = fields.Boolean(string='Pregnancy Warning',
        help='The drug represents risk to pregnancy')
    lactation_warning = fields.Boolean('Lactation Warning',
        help='The drug represents risk in lactation period')
    pregnancy = fields.Text(string='Pregnancy and Lactancy',
        help='Warnings for Pregnant Women')

    notes = fields.Text(string='Extra Info')
    storage = fields.Char(string='Storage')
    adverse_reaction = fields.Char(string='Adverse Reactions')
    dosage = fields.Float(string='Dosage', help='Dosage')
    product_uom_category_id = fields.Many2one('uom.category', related='uom_id.category_id')
    dosage_uom_id = fields.Many2one('uom.uom', string='Unit of Dosage', domain="[('category_id', '=', product_uom_category_id)]")
    route_id = fields.Many2one('drug.route', ondelete='cascade', 
        string='Route', help='')
    form_id = fields.Many2one('drug.form', ondelete='cascade', 
        string='Form',help='Drug form, such as tablet or gel')


class StockProductionLot(models.Model):
    _inherit = 'stock.lot'

    product_qty = fields.Float(search="_search_product_qty")

    #canbe used for filtering lots in selection on procedures and consumed products
    def _search_product_qty(self, operator, value):
        valid_record = []
        product_id = self._context.get('acs_product_id',False)
        domain =[('product_id','=',product_id)]
        if self._context.get('acs_all_products',False):
            domain =[]
        production_lots = self.search(domain)
        for production_lot in production_lots:
            if operator == '>' and production_lot.product_qty > value:
                valid_record.append(production_lot.id)
        return [('id', 'in', valid_record)]

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
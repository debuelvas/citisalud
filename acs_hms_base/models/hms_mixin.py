# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError

import base64
from io import BytesIO


class ACSQrcodeMixin(models.AbstractModel):
    _name = "acs.qrcode.mixin"
    _description = "QrCode Mixin"

    unique_code = fields.Char("Unique UID")
    qr_image = fields.Binary("QR Code", compute='acs_generate_qrcode')

    def acs_generate_qrcode(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        for rec in self:
            import qrcode
            model_name = (rec._name).replace('.','')
            url = base_url + '/validate/%s/%s' % (model_name,rec.unique_code)
            data = BytesIO()
            qrcode.make(url.encode(), box_size=4).save(data, optimise=True, format='PNG')
            qrcode = base64.b64encode(data.getvalue()).decode()
            rec.qr_image = qrcode


class ACSHmsMixin(models.AbstractModel):
    _name = "acs.hms.mixin"
    _description = "HMS Mixin"

    def acs_prepare_invocie_data(self, partner, patient, product_data, inv_data):
        fiscal_position_id = self.env['account.fiscal.position']._get_fiscal_position(partner)
        data = {
            'partner_id': partner.id,
            'patient_id': patient and patient.id,
            'move_type': inv_data.get('move_type','out_invoice'),
            'ref': self.name,
            'invoice_origin': self.name,
            'currency_id': self.env.company.currency_id.id,
            'invoice_line_ids': self.acs_get_invoice_lines(product_data, partner, inv_data, fiscal_position_id),
            'physician_id': inv_data.get('physician_id',False),
            'hospital_invoice_type': inv_data.get('hospital_invoice_type',False),
            'fiscal_position_id': fiscal_position_id and fiscal_position_id.id or False,
        }
        if inv_data.get('ref_physician_id',False):
            data['ref_physician_id'] = inv_data.get('ref_physician_id',False)
        if inv_data.get('appointment_id',False):
            data['appointment_id'] = inv_data.get('appointment_id',False)

        Module = self.env['ir.module.module'].sudo()
        if Module.search([('name','=','acs_hms_commission'),('state','=','installed')]) and self.env.context.get('commission_partner_ids',False):
            data['commission_partner_ids'] = [(6, 0, [self.env.context.get('commission_partner_ids')])]
        return data

    @api.model
    def acs_create_invoice(self, partner, patient=False, product_data=[], inv_data={}):
        inv_data = self.acs_prepare_invocie_data(partner, patient, product_data, inv_data)
        invoice = self.env['account.move'].create(inv_data)
        invoice._onchange_partner_id()
        for line in invoice.invoice_line_ids:
            line._get_computed_taxes()
        return invoice

    @api.model
    def acs_get_invoice_lines(self, product_data, partner, inv_data, fiscal_position_id):
        lines = [] 
        for data in product_data:
            product = data.get('product_id')
            quantity = data.get('quantity',1.0)
            uom_id = data.get('product_uom_id')
            discount = data.get('discount',0.0)

            if product:
                acs_pricelist_id = self.env.context.get('acs_pricelist_id')

                if not data.get('price_unit'):
                    price = product.with_context(acs_pricelist_id=acs_pricelist_id)._acs_get_partner_price(quantity, uom_id, partner)
                    discount = product.with_context(acs_pricelist_id=acs_pricelist_id)._acs_get_partner_price_discount(quantity, uom_id, partner)
                else:
                    price = data.get('price_unit', product.list_price)

                if inv_data.get('move_type','out_invoice') in ['out_invoice','out_refund']:
                    tax_ids = product.taxes_id
                else:
                    tax_ids = product.supplier_taxes_id

                if tax_ids:
                    if fiscal_position_id:
                        tax_ids = fiscal_position_id.map_tax(tax_ids._origin)
                    tax_ids = [(6, 0, tax_ids.ids)]

                lines.append((0, 0, {
                    'name': data.get('name',product.get_product_multiline_description_sale()),
                    'product_id': product.id,
                    'price_unit': price,
                    'quantity': quantity,
                    'discount': discount,
                    'product_uom_id': uom_id or product.uom_id.id or False,
                    'tax_ids': tax_ids,
                    'display_type': 'product',
                }))
            else:
                lines.append((0, 0, {
                    'name': data.get('name'),
                    'display_type': data.get('display_type', 'line_section'),
                }))
                
        return lines

    @api.model
    def acs_create_invoice_line(self, product_data, invoice):
        product = product_data.get('product_id')
        MoveLine = self.env['account.move.line']
        quantity = product_data.get('quantity',1.0)
        uom_id = product_data.get('product_uom_id')
        discount = product_data.get('discount',0.0)
        if product:
            acs_pricelist_id = self.env.context.get('acs_pricelist_id')
            if not product_data.get('price_unit'):
                price = product.with_context(acs_pricelist_id=acs_pricelist_id)._acs_get_partner_price(quantity, uom_id, invoice.partner_id)
                discount = product.with_context(acs_pricelist_id=acs_pricelist_id)._acs_get_partner_price_discount(quantity, uom_id, invoice.partner_id)
            else:
                price = product_data.get('price_unit', product.list_price)

            if invoice.move_type in ['out_invoice','out_refund']:
                tax_ids = product.taxes_id
            else:
                tax_ids = product.supplier_taxes_id

            if tax_ids:
                if invoice.fiscal_position_id:
                    tax_ids = invoice.fiscal_position_id.map_tax(tax_ids._origin)
                tax_ids = [(6, 0, tax_ids.ids)]

            account_id = product.property_account_income_id or product.categ_id.property_account_income_categ_id
            line = MoveLine.with_context(check_move_validity=False).create({
                'move_id': invoice.id,
                'name': product_data.get('name',product.get_product_multiline_description_sale()),
                'product_id': product.id,
                'account_id': account_id.id,
                'price_unit': price,
                'quantity': quantity,
                'discount': discount,
                'product_uom_id': uom_id,
                'tax_ids': tax_ids,
                'display_type': 'product',
            })
        else:
            line = MoveLine.with_context(check_move_validity=False).create({
                'move_id': invoice.id,
                'name': product_data.get('name'),
                'display_type': 'line_section',
            })
            
        return line

    def acs_action_view_invoice(self, invoices):
        action = self.env["ir.actions.actions"]._for_xml_id("account.action_move_out_invoice_type")
        if len(invoices) > 1:
            action['domain'] = [('id', 'in', invoices.ids)]
        elif len(invoices) == 1:
            action['views'] = [(self.env.ref('account.view_move_form').id, 'form')]
            action['res_id'] = invoices.id
        elif self.env.context.get('acs_open_blank_list'):
            #Allow to open invoices
            action['domain'] = [('id', 'in', invoices.ids)]
        else:
            action = {'type': 'ir.actions.act_window_close'}

        context = {
            'default_move_type': 'out_invoice',
        }
        action['context'] = context
        return action

    @api.model
    def assign_given_lots(self, move, lot_id, lot_qty):
        MoveLine = self.env['stock.move.line'].sudo()
        move_line_id = MoveLine.search([('move_id', '=', move.id),('lot_id','=',False)],limit=1)
        if move_line_id:
            move_line_id.lot_id = lot_id

    def consume_material(self, source_location_id, dest_location_id, product_data):
        product = product_data['product']
        move = self.env['stock.move'].sudo().create({
            'name' : product.name,
            'product_id': product.id,
            'product_uom': product.uom_id.id,
            'product_uom_qty': product_data.get('qty',1.0),
            'date': product_data.get('date',fields.datetime.now()),
            'location_id': source_location_id,
            'location_dest_id': dest_location_id,
            'state': 'draft',
            'origin': self.name,
            'quantity': product_data.get('qty',1.0),
            'picked': True,
        })
        move._action_confirm()
        move._action_assign()
        if product_data.get('lot_id', False):
            lot_id = product_data.get('lot_id')
            lot_qty = product_data.get('qty',1.0)
            self.sudo().assign_given_lots(move, lot_id, lot_qty)
        if move.state == 'assigned':
            move._action_done()
        return move

    def acs_apply_invoice_exemption(self):
        for rec in self:
            rec.invoice_exempt = False if rec.invoice_exempt else True


class ACSDocumntMixin(models.AbstractModel):
    _name = "acs.document.mixin"
    _description = "Document Mixin"

    def _acs_get_attachemnts(self):
        attachments = self.env['ir.attachment'].search([
            ('res_model', '=', self._name),
            ('res_id', '=', self.id)])
        return attachments 

    def _acs_attachemnt_count(self):
        for rec in self:
            attachments = rec._acs_get_attachemnts()
            rec.attach_count = len(attachments)
            rec.attachment_ids = [(6,0,attachments.ids)]

    attach_count = fields.Integer(compute="_acs_attachemnt_count", readonly=True, string="Documents")
    attachment_ids = fields.Many2many('ir.attachment', 'attachment_acs_hms_rel', 'record_id', 'attachment_id', compute="_acs_attachemnt_count", string="Attachments")

    def action_view_attachments(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("base.action_attachment")
        action['domain'] = [('id', 'in', self.attachment_ids.ids)]
        action['context'] = {
                'default_res_model': self._name,
                'default_res_id': self.id,
                'default_is_document': True}
        return action

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
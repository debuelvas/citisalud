# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from datetime import date, datetime, timedelta,time
from odoo.exceptions import ValidationError
import base64
import xlrd
import xlsxwriter
from io import BytesIO, StringIO


import logging
_logger = logging.getLogger(__name__)
class ACSTreatment(models.Model):
    _name = 'hms.treatment'
    _description = "Treatment"
    _inherit = ['mail.thread', 'mail.activity.mixin', 'acs.hms.mixin', 'acs.document.mixin']

    @api.depends('medical_alert_ids')
    def _get_alert_count(self):
        for rec in self:
            rec.alert_count = len(rec.medical_alert_ids)

    @api.model
    def _get_service_id(self):
        registration_product = False
        if self.env.company.treatment_registration_product_id:
            registration_product = self.env.company.treatment_registration_product_id.id
        return registration_product

    def _rec_count(self):
        for rec in self:
            rec.appointment_count = len(rec.appointment_ids)
            rec.patient_procedure_count = len(rec.patient_procedure_ids)

    name = fields.Char(string='Name', readonly=True, index=True, copy=False, tracking=1)
    subject = fields.Char(string='Subject', tracking=1)
    patient_id = fields.Many2one('hms.patient', 'Patient', required=True, index=True, tracking=1)
    vat = fields.Char(related="patient_id.vat", string='ID/CC',  index=True, tracking=1)
    department_id = fields.Many2one('hr.department', ondelete='restrict', string='Department',
        domain=[('patient_department', '=', True)], tracking=1)
    image_128 = fields.Binary(related='patient_id.image_128', string='Image', readonly=True)
    date = fields.Datetime(string='Date of Diagnosis', default=fields.Datetime.now)
    healed_date = fields.Date(string='Healed Date')
    treatment_days = fields.Integer(string='Días de Tratamiento', compute="acs_get_duration", store=True)
    is_imported = fields.Boolean(string='Importado', default=False)

    start_date = fields.Date(string='Fecha de inicio',help='End of treatment date', defualt=fields.Date.today())
    end_date = fields.Date(string='End Date',help='End of treatment date')
    diagnosis_id = fields.Many2one('hms.diseases',string='Diagnosis')
    physician_id = fields.Many2one('hms.physician', ondelete='restrict', string='Physician',
        help='Physician who treated or diagnosed the patient', tracking=1)
    attending_physician_ids = fields.Many2many('hms.physician','hosp_treat_doc_rel','treat_id','doc_id', string='Primary Doctors')
    prescription_line_ids = fields.One2many('prescription.line', 'treatment_id', 'Prescription')
    finding = fields.Text(string="Findings")
    appointment_ids = fields.One2many('hms.appointment', 'treatment_id', string='Appointments')
    appointment_count = fields.Integer(compute='_rec_count', string='# Appointments')
    state = fields.Selection([
            ('draft', 'Draft'),
            ('running', 'Running'),
            ('copay', 'Copago'),
            ('done', 'Completed'),
            ('cancel', 'Cancelled'),
        ], string='Status',default='draft', required=True, copy=False, tracking=1)
    description = fields.Char(string='Treatment Description')

    is_allergy = fields.Boolean(string='Allergic Disease')
    pregnancy_warning = fields.Boolean(string='Pregnancy warning')
    lactation = fields.Boolean('Lactation')
    disease_severity = fields.Selection([
            ('mild', 'Mild'),
            ('moderate', 'Moderate'),
            ('severe', 'Severe'),
        ], string='Severity',index=True)
    disease_status = fields.Selection([
            ('acute', 'Acute'),
            ('chronic', 'Chronic'),
            ('unchanged', 'Unchanged'),
            ('healed', 'Healed'),
            ('improving', 'Improving'),
            ('worsening', 'Worsening'),
        ], string='Status of the disease',index=True)
    is_infectious = fields.Boolean(string='Infectious Disease', 
        help='Check if the patient has an infectious transmissible disease')
    allergy_type = fields.Selection([
            ('da', 'Drug Allergy'),
            ('fa', 'Food Allergy'),
            ('ma', 'Misc Allergy'),
            ('mc', 'Misc Contraindication'),
        ], string='Allergy type',index=True)
    age = fields.Char(string='Age when diagnosed',
        help='Patient age at the moment of the diagnosis. Can be estimative')
    patient_disease_id = fields.Many2one('hms.patient.disease', string='Patient Disease')
    invoice_id = fields.Many2one('account.move',string='Invoice', ondelete='restrict', copy=False)
    company_id = fields.Many2one('res.company', ondelete='restrict', 
        string='Hospital',default=lambda self: self.env.company)
    medical_alert_ids = fields.Many2many('acs.medical.alert', 'treatment_medical_alert_rel','treatment_id', 'alert_id',
        string='Medical Alerts', related="patient_id.medical_alert_ids")
    alert_count = fields.Integer(compute='_get_alert_count', default=0)
    registration_product_id = fields.Many2one('product.product', default=_get_service_id, string="Registration Service")
    department_type = fields.Selection(related='department_id.department_type', string="Treatment Department", store=True)

    patient_procedure_ids = fields.One2many('acs.patient.procedure', 'treatment_id', 'Patient Procedures')
    patient_procedure_count = fields.Integer(compute='_rec_count', string='# Patient Procedures')
    procedure_group_id = fields.Many2one('procedure.group', ondelete="set null", string='Procedure Group')
    contract_id = fields.Many2one('customer.contract', string='Contrato', 
        domain="[('start_date', '<=', date), ('end_date', '>=', date)]",
        tracking=1)
    insurance_id = fields.Many2one('res.partner', string='EPS/Aseguradora',
                domain="[('is_company', '=', True)]", tracking=True)
    has_copay = fields.Boolean('Requiere Copago', tracking=True)
    copay_amount = fields.Float('Monto Copago', tracking=True)
    copay_journal_id = fields.Many2one('account.journal', string='Diario Copago')
    copay_payment_id = fields.Many2one('account.payment', string='Pago Copago', readonly=True)
    authorization_number = fields.Char('Número de Autorización', tracking=True)
    copay_product_id = fields.Many2one('product.product', string='Producto Copago',
        domain=[('default_code', '=', 'COPA')], tracking=True)

    @api.onchange('patient_id')
    def validate_state_patient(self):
        for rec in self:
            if rec.patient_id.state_patient == 'inactive':
               raise ValidationError(_('No se puede asignar un tratamiento a un paciente inactivo.'))
            # if rec.patient_id.state_patient == 'collected':
            #    raise ValidationError(_('No se puede asignar un tratamiento a un paciente recolectado.'))


    @api.depends('start_date', 'end_date')
    def acs_get_duration(self):
        for rec in self:
            duration = 0.0
            if rec.start_date and rec.end_date:
                diff = rec.end_date - rec.start_date
                duration = (diff.days * 24) + (diff.seconds/3600)
                # rec.duration = duration # Cambio de duración a horas
                rec.treatment_days = diff.days # Cambio de duración a días


    @api.depends('patient_procedure_ids.product_id', 'return_date',
                'sale_order_ids', 'sale_order_ids.order_line', 'sale_order_ids.order_line.product_id',
                'sale_order_ids.order_closed', 'sale_order_ids.create_date')
    def _compute_service_type(self):
        """
        Optimizado: Eliminadas búsquedas en BD, usa solo relaciones existentes
        """
        for record in self:
            service_type = 'delivery'  # Por defecto es primera entrega

            # OPTIMIZACIÓN: Usar relaciones existentes en lugar de búsquedas
            # Filtrar órdenes cerradas anteriores directamente desde sale_order_ids
            previous_orders = record.sale_order_ids.filtered(
                lambda o: o.state == 'sale' and
                         o.order_closed and
                         o.create_date < record.create_date
            )

            # Verificar si hay órdenes anteriores con los mismos productos
            current_products = record.patient_procedure_ids.mapped('product_id')
            has_same_products = any(
                line.product_id in current_products
                for order in previous_orders
                for line in order.order_line
            )

            # Determinar el tipo de servicio
            # NOTA: previous_picking eliminado porque requeriría búsqueda en BD
            # Si se necesita, debería agregarse un campo One2many en treatment
            if record.return_date:
                service_type = 'pickup'
            elif has_same_products:
                service_type = 'redelivery'

            record.service_type = service_type

    @api.onchange('return_date')
    def _onchange_return_date(self):
        """Propagar fecha de devolución a los procedimientos"""
        if self.return_date:
            for procedure in self.patient_procedure_ids:
                procedure.date_stop = fields.Datetime.from_string(
                    f"{self.return_date} 23:59:59"
                )


    @api.onchange('start_date', 'treatment_days')
    def _onchange_treatment_duration(self):
        if self.start_date and self.treatment_days:
            start_date = self.start_date
            self.end_date = start_date + timedelta(days=self.treatment_days)

    @api.onchange('patient_id')
    def onchange_eps(self):
        for rec in self:
            if rec.patient_id:
                rec.insurance_id = rec.patient_id.eps_id.id
                rec.contract_id = rec.patient_id.eps_id.id
            rec.contract_id = False
            if rec.insurance_id and rec.date:
                domain = [
                    ('partner_id', '=', rec.insurance_id.id),
                    ('start_date', '<=', rec.date),
                    ('end_date', '>=', rec.date),
                ]
                
                contract = self.env['customer.contract'].search(domain, limit=1)
                
                if contract:
                    rec.contract_id = contract.id
                else:
                    return {
                        'warning': {
                            'title': 'Advertencia',
                            'message': 'No se encontró un contrato activo para este cliente en la fecha especificada.'
                        }
                    }

    @api.depends('sale_order_ids')
    def _compute_sale_orders(self):
        for record in self:
            record.sale_order_count = len(record.sale_order_ids)

    @api.depends('patient_procedure_ids.product_id.rent_ok')
    def _compute_has_rented_products(self):
        for record in self:
            record.has_rented_products = any(
                procedure.product_id.rent_ok 
                for procedure in record.patient_procedure_ids
            )

    @api.depends('invoice_ids')
    def _compute_invoice_count(self):
        """
        Optimizado: Usa relación invoice_ids en lugar de búsqueda en BD
        NOTA: Asume que existe campo invoice_ids = One2many('account.move', 'treatment_id')
        Si no existe, debe agregarse al modelo para evitar búsquedas
        """
        for record in self:
            # CAMBIO CRÍTICO: Usar relación existente en lugar de search
            record.invoice_count = len(record.invoice_ids)

    def action_view_invoices(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Facturas',
            'res_model': 'account.move',
            'view_mode': 'tree,form',
            'domain': [('contract_id', '=', self.id)],
            'context': {
                'default_patient_id': self.patient_id.id,
                'default_partner_id': self.patient_id.partner_id.id,
                'default_contract_id': self.id,
                'default_move_type': 'out_invoice'
            },
        }

    def action_view_sale_orders(self):
        """Ver órdenes de venta relacionadas"""
        self.ensure_one()
        return {
            'name': _('Órdenes de Venta'),
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', self.sale_order_ids.ids)],
            'context': {
                'default_patient_id': self.patient_id.id,
                'default_partner_id': self.patient_id.partner_id.id,
                'default_contract_id': self.contract_id.id,
                'default_treatment_ids': [(4, self.id)],
                'default_pricelist_id': self.contract_id.pricelist_id.id if self.contract_id else False,
            }
        }

    def action_create_sale_order(self):
        """Crear orden de venta desde el tratamiento para uno o múltiples registros"""
        orders_created = []
        
        for record in self:
            if not record.contract_id:
                raise UserError(_("Por favor seleccione un contrato válido para el registro %s.") % record.name)
            if not record.contract_id.pricelist_id:
                raise UserError(_("El contrato no tiene una lista de precios configurada para el registro %s.") % record.name)
            
            open_order = self.env['sale.order'].search([
                ('patient_id', '=', record.patient_id.id),
                ('contract_id', '=', record.contract_id.id),
                ('state', 'in', ['draft', 'sent', 'sale']),
                ('order_closed', '=', False)
            ], limit=1)
            
            #try:
            if open_order.date_order and record.start_date:
                if open_order.date_order.month != record.start_date.month:
                        order = record._create_new_order()
                        message = _('La orden de venta no es del mismo mes del tratamiento Se creó la nueva orden %s') % order.name
                elif open_order:
                    order = record._update_existing_order(open_order)
                    message = _('Se actualizó la orden existente %s') % order.name
                else:
                    order = record._create_new_order()
                    message = _('Se creó la nueva orden %s') % order.name
            else:
                order = record._create_new_order()
                message = _('Se creó la nueva orden %s') % order.name

            #order._recompute_rental_prices()
            orders_created.append(order.id)
            
            self.env['bus.bus']._sendone(self.env.user.partner_id, 'simple_notification', {
                'title': _('Orden de Venta'),
                'message': message,
                'type': 'success',
            })
                
            # except Exception as e:
            #     raise UserError(_("Error al procesar el registro %s: %s") % (record.name, str(e)))
        
        # Retornar vista tree de las órdenes creadas/actualizadas
        return {
            'name': _('Órdenes de Venta'),
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', orders_created)],
            'target': 'current',
        }
        
    def _create_new_order(self):
        """Crear nueva orden de venta"""
        self.ensure_one()
        has_rented = any(proc.product_id.rent_ok for proc in self.patient_procedure_ids)
        
        order_vals = {
            'partner_id': self.insurance_id.id,
            'patient_id': self.patient_id.id,
            'contract_id': self.contract_id.id,
            'pricelist_id': self.contract_id.pricelist_id.id,
            'treatment_ids': [(4, self.id)],
            'is_rental_order': has_rented,
        }

        if has_rented:
            first_procedure = self.patient_procedure_ids.filtered(
                lambda p: p.product_id.rent_ok and p.date
            ).sorted('date', reverse=False)[:1]

            if first_procedure:
                order_vals['rental_start_date'] = first_procedure.date
                if first_procedure.date_stop:
                    order_vals['rental_return_date'] = first_procedure.date_stop
                else:
                    order_vals['rental_return_date'] = first_procedure.date + timedelta(days=30)
            else:
                now = fields.Datetime.now()
                order_vals['rental_start_date'] = now
                order_vals['rental_return_date'] = now + timedelta(days=30)

        order = self.env['sale.order'].create(order_vals)
        self._create_order_lines(order)
        self.write({'sale_order_ids': [(4, order.id)]})
        return order

    def _update_existing_order(self, order):
        """Actualizar orden existente"""
        self.ensure_one()
        has_rented = any(proc.product_id.rent_ok for proc in self.patient_procedure_ids)
        
        procedure_products = self.patient_procedure_ids.mapped('product_id')
        order_products = order.order_line.mapped('product_id')
        has_products = bool(procedure_products)

        should_extend = False
        if self.end_date and order.rental_return_date:
            if self.end_date > order.rental_return_date.date():
                should_extend = True

        vals = {
            'treatment_ids': [(4, self.id)],
            'is_rental_order': order.is_rental_order or has_rented,
        }
        vals_line = {}
        pending_pickings = order.picking_ids.filtered(
            lambda p: p.state not in ['done', 'cancel'] and 
                    p.picking_type_code == 'outgoing'
        )
        order.without_movement = bool(pending_pickings)

        if should_extend:
            vals['rental_return_date'] = datetime.combine(self.end_date, time(23, 59, 59))
            if order.rental_return_date:
                self._update_rental_prices(order)
        for line in order.order_line:
            vals_line = {}
            if has_products:
                if line.product_id in procedure_products:
                    vals_line['treatment_ids'] = [(4, self.id)]
                    line.write(vals_line)
            else:
                vals_line['treatment_ids'] = [(4, self.id)]
                line.write(vals_line)
        order.write(vals)

        if not order.without_movement:
            if has_products:
                new_products = procedure_products - order_products
                for procedure in self.patient_procedure_ids:
                    if order.date_order.month == procedure.date.month:
                        self._create_new_line(order, procedure)
                    elif procedure.product_id in new_products:
                        self._create_new_line(order, procedure)
            else:
                for line in order.order_line:
                    if not line.qty_invoiced or line.is_rental:
                        self._update_order_line(line)
        self.state = 'done'
        return order

    def _update_order_line(self, line):
        """Actualizar línea de orden existente"""
        line_vals = {}            
        price = line.order_id.pricelist_id._get_product_price(
                line.product_id, 
                1.0, 
                line.order_id.partner_id,
                date=fields.Date.today()
            )
        if line.is_rental and self.return_date:
            rental_days = (self.return_date - self.start_date).days + 1
            daily_price = line.product_id.list_price / 30  # Precio por día basado en precio mensual
            rental_price = daily_price * price
            
            line_vals.update({
                'price_unit': rental_price,
                'start_date': fields.Datetime.from_string(f"{self.start_date} 00:00:00"),
                'return_date': fields.Datetime.from_string(f"{self.return_date} 23:59:59")
            })
        else:
            # Si es línea normal no facturada

            line_vals['price_unit'] = price
        
        if line_vals:
            line.write(line_vals)


    def _create_order_lines(self, order):
        """Crear líneas de orden para los procedimientos"""
        SaleOrderLine = self.env['sale.order.line']
        
        for procedure in self.patient_procedure_ids:
            if procedure.product_id not in order.contract_id.products_ids:
                raise UserError(_(
                    f"El producto {procedure.product_id.name} no está disponible en el contrato."
                ))
            
            existing_lines = order.order_line.filtered(
                lambda l: l.product_id == procedure.product_id
            )
            
            if existing_lines and order.without_movement:
                continue 
            
            if existing_lines:
                for line in existing_lines:
                    if line.is_rental and procedure.product_id.rent_ok:
                        self._update_rental_prices(line.order_id)
            else:
                self._create_new_line(order, procedure)
            

    def _update_rental_prices(self, order):
        """Actualizar precios de líneas rentadas usando el sistema de precios de Odoo"""
        for line in order.order_line.filtered(lambda l: l.is_rental and not l.qty_returned):
            if not line.start_date or not line.return_date:
                continue
            current_days = (line.return_date - line.start_date).days
            new_days = (self.end_date - line.start_date.date()).days
            additional_days = new_days - current_days
            if additional_days <= 0:
                continue
            daily_price = order.pricelist_id._get_product_price(
                line.product_id, 
                1.0, 
                order.partner_id,
                uom_id=line.product_uom,
                date=fields.Date.today()
            )
            additional_amount = daily_price * additional_days
            line.write({
                'price_unit': line.price_unit + additional_amount,
                'return_date': fields.Datetime.from_string(self.end_date)
            })
            
    def _create_new_line(self, order, procedure):
        """Crear nueva línea de orden"""
        price = order.pricelist_id._get_product_price(
            procedure.product_id, 
            1.0, 
            order.partner_id,
            date=fields.Date.today()
        )
        
        line_vals = {
            'order_id': order.id,
            'product_id': procedure.product_id.id,
            'name': procedure.product_id.get_product_multiline_description_sale(),
            'product_uom_qty': 1.0,
            'price_unit': price,
            'patient_id': self.patient_id.id,
            'treatment_id': self.id,
            'is_rental': procedure.product_id.rent_ok,
        }
        
        if procedure.product_id.rent_ok:
            if procedure.date:
                start_date = procedure.date
                end_date = procedure.date_stop or (procedure.date + timedelta(days=self.treatment_days or 30))
            else:
                start_date = fields.Datetime.from_string(self.start_date)
                end_date = fields.Datetime.from_string(self.end_date or (self.start_date + timedelta(days=self.treatment_days or 30)))

            if end_date and start_date:
                rental_days = (end_date - start_date).days
            else:
                rental_days = 0
            daily_price = price / 30 
            rental_price = daily_price * rental_days

            line_vals.update({
                'is_rental': True,
                'start_date': start_date,
                'return_date': end_date,
                'price_unit': rental_price,
            })
        
        return self.env['sale.order.line'].create(line_vals)



    @api.model
    def default_get(self, fields_list):
        res = super(ACSTreatment, self).default_get(fields_list)
        if self._context.get('acs_department_type'):
            department = self.env['hr.department'].search([('department_type','=',self._context.get('acs_department_type'))], limit=1)
            if department:
                res['department_id'] = department.id
        return res

    def action_view_patient_procedures(self):
        action = self.env["ir.actions.actions"]._for_xml_id("acs_hms.action_acs_patient_procedure")
        action['domain'] = [('id', 'in', self.patient_procedure_ids.ids)]
        action['context'] = {'default_patient_id': self.patient_id.id, 'default_treatment_id': self.id, 'default_department_id': self.department_id.id}
        return action

    @api.onchange('department_id')
    def onchange_department(self):
        if self.department_id:
            self.department_type = self.department_id.department_type

    def get_line_data(self, line):
        base_date = fields.Date.today()
        return {
            'product_id': line.product_id.id,
            'patient_id': self.patient_id.id,
            'date': fields.Datetime.now() + timedelta(days=line.days_to_add),
            'date_stop': fields.Datetime.now() + timedelta(days=line.days_to_add) + timedelta(hours=line.product_id.procedure_time)
        }

    @api.onchange('procedure_group_id')
    def onchange_procedure_group(self):
        patient_procedure_ids = []
        if self.procedure_group_id:
            for line in self.procedure_group_id.line_ids:
                patient_procedure_ids.append((0,0,self.get_line_data(line)))
            self.patient_procedure_ids = patient_procedure_ids

    @api.model_create_multi
    def create(self, vals_list):
        copay_product = self._get_copay_product()
        
        for values in vals_list:
            if values.get('name', 'New Treatment') == 'New Treatment':
                values['name'] = self.env['ir.sequence'].next_by_code('hms.treatment') or 'New Treatment'
            if 'copay_product_id' not in values:
                values['copay_product_id'] = copay_product.id
            if values.get('has_copay') and not values.get('copay_amount'):
                values['copay_amount'] = copay_product.list_price
        return super().create(vals_list)

    def unlink(self):
        for data in self:
            if data.state in ['done']:
                raise UserError(('You can not delete record in done state'))
        return super(ACSTreatment, self).unlink()

    def treatment_draft(self):
        self.state = 'draft'

    @api.onchange('patient_id')
    def onchange_patient_id(self):
        self.age = self.patient_id.age

    def treatment_running(self):
        patient_disease_id = self.env['hms.patient.disease'].create({
            'patient_id': self.patient_id.id,
            'treatment_id': self.id,
            'disease_id': self.diagnosis_id.id,
            'age': self.age,
            'diagnosed_date': self.date,
            'healed_date': self.healed_date,
            'allergy_type': self.allergy_type,
            'is_infectious': self.is_infectious,
            'status': self.disease_status,
            'disease_severity': self.disease_severity,
            'lactation': self.lactation,
            'pregnancy_warning': self.pregnancy_warning,
            'is_allergy': self.is_allergy,
            'description': self.description,
        })
        self.patient_disease_id = patient_disease_id.id
        self.state = 'running'

    def treatment_done(self):
        self.state = 'done'

    def treatment_cancel(self):
        self.state = 'cancel'

    def action_appointment(self):
        action = self.env["ir.actions.actions"]._for_xml_id("acs_hms.action_appointment")
        action['domain'] = [('treatment_id','=',self.id)]
        action['context'] = { 
            'default_treatment_id': self.id, 
            'default_patient_id': self.patient_id.id, 
            'default_physician_id': self.physician_id.id,
            'default_department_id': self.department_id and self.department_id.id or False}
        return action
    @api.model
    def _get_copay_product(self):
        """Método auxiliar para obtener o crear el producto de copago"""
        copay_product = self.env['product.product'].search([('default_code', '=', 'COPA')], limit=1)
        if not copay_product:
            copay_product = self.env['product.product'].create({
                'name': 'Copago',
                'default_code': 'COPA',
                'type': 'service',
                'sale_ok': True,
                'purchase_ok': False,
                'invoice_policy': 'order',
                'detailed_type': 'service',
                'company_id': self.env.company.id,
            })
        return copay_product


    def create_invoice(self):
        """Crear factura de copago si aplica"""
        self.ensure_one()
        
        if not self.contract_id:
            raise UserError(_("Por favor seleccione un contrato válido."))
        if not self.insurance_id:
            raise UserError(_("Por favor seleccione una EPS/Aseguradora para facturar."))
                
        if self.has_copay and not self.copay_product_id:
            raise UserError(_("No se ha configurado el producto de copago."))

        invoice_data = {
            'hospital_invoice_type': 'treatment',
            'contract_id': self.contract_id.id,
            'authorization_number': self.authorization_number,
            'physician_id': self.physician_id.id,
            'department_id': self.department_id.id,
            'diagnosis_id': self.diagnosis_id.id,
            'treatment_id': self.id,
            'patient_id': self.patient_id.id,
            'disease_status': self.disease_status,
            'disease_severity': self.disease_severity,
            'ref': self.name,
            'invoice_type': 'copay' if self.has_copay else 'insurance'
        }
        # Si el contrato tiene campos adicionales
        if hasattr(self.contract_id, 'benefit_plan_ids'):
            invoice_data['benefit_plan_ids'] = [(6, 0, self.contract_id.benefit_plan_ids.ids)]
        if hasattr(self.contract_id, 'payment_method_id'):
            invoice_data['payment_method'] = self.contract_id.payment_method
        if self.has_copay:
            product_data = [{
                'product_id': self.copay_product_id,
                'price_unit': self.copay_amount,
                'name': f'Copago tratamiento {self.name}',
                'quantity': 1.0,
            }]
            # Crear factura de copago al paciente
            invoice = self.acs_create_invoice(
                partner=self.patient_id.partner_id,
                patient=self.patient_id,
                product_data=product_data,
                inv_data=invoice_data
            )
            self.invoice_id = invoice.id
        else:
            product_id = self.registration_product_id or self.env.company.treatment_registration_product_id
            if not product_id:
                raise UserError(_("Please Configure Registration Product in Configuration first."))
                
            product_data = [{
                'product_id': product_id,
                'price_unit': product_id.list_price,
                'name': f'Tratamiento {self.name}',
                'quantity': 1.0,
            }]
            # Crear factura normal a la aseguradora
            invoice = self.acs_create_invoice(
                partner=self.insurance_id,
                patient=self.patient_id,
                product_data=product_data,
                inv_data=invoice_data
            )
            self.invoice_id = invoice.id
        if invoice:
            self.state = 'copay'
        return {
                'name': _('Factura Creada'),
                'type': 'ir.actions.act_window',
                'res_model': 'account.move',
                'res_id': invoice.id,
                'view_mode': 'form',
                'view_type': 'form',
                'target': 'current',
            }
        
    def action_create_procedure_invoice(self):
        procedure_ids = self.patient_procedure_ids.filtered(lambda proc: not proc.invoice_id)
        if not procedure_ids:
            raise UserError(_("There is no Procedure to Invoice or all are already Invoiced."))

        product_data = []
        for procedure in procedure_ids:
            product_data.append({
                'product_id': procedure.product_id,
                'price_unit': procedure.price_unit,
                'name': f'Procedimiento: {procedure.product_id.name}',
                'quantity': 1.0,
            })

            for consumable in procedure.consumable_line_ids:
                product_data.append({
                    'product_id': consumable.product_id,
                    'quantity': consumable.qty,
                    'price_unit': consumable.product_id.list_price,
                    'lot_id': consumable.lot_id and consumable.lot_id.id or False,
                    'name': f'Consumible: {consumable.product_id.name}',
                })

        inv_data = {
            'physician_id': self.physician_id and self.physician_id.id or False,
            'contract_id': self.contract_id.id,
            'authorization_number': self.authorization_number,
            'department_id': self.department_id.id,
            'diagnosis_id': self.diagnosis_id.id,
            'treatment_id': self.id,
            'patient_id': self.patient_id.id,
            'disease_status': self.disease_status,
            'disease_severity': self.disease_severity,
            'invoice_type': 'insurance',
            'partner_bank_id': self.insurance_id.bank_ids[0].id if self.insurance_id.bank_ids else False,
        }

        # Si el contrato tiene campos adicionales
        if hasattr(self.contract_id, 'type_coverage_id'):
            inv_data['type_coverage_id'] = self.contract_id.type_coverage_id.id
        if hasattr(self.contract_id, 'payment_method_id'):
            inv_data['payment_method_id'] = self.contract_id.payment_method_id.id

        invoice = self.acs_create_invoice(
            partner=self.insurance_id,
            patient=self.patient_id,
            product_data=product_data,
            inv_data=inv_data
        )
        procedure_ids.write({'invoice_id': invoice.id})

    def view_invoice(self):
        invoices = self.invoice_id + self.patient_procedure_ids.mapped('invoice_id')
        action = self.acs_action_view_invoice(invoices)
        action['context'].update({
            'default_partner_id': self.patient_id.partner_id.id,
            'default_patient_id': self.id,
        })
        return action

    def acs_select_treatement_for_appointment(self):
        if self._context.get('acs_current_appointment'):
            #Check if we can get back to appointment in breadcrumb.
            appointment = self.env['hms.appointment'].search([('id','=',self._context.get('acs_current_appointment'))])
            appointment.treatment_id = self.id
            action = self.env["ir.actions.actions"]._for_xml_id("acs_hms.action_appointment")
            action['res_id'] = appointment.id
            action['views'] = [(self.env.ref('acs_hms.view_hms_appointment_form').id, 'form')]
            return action
        else:
            raise UserError(_("Something went wrong! Plese Open Appointment and try again"))

    
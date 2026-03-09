# -*- coding: utf-8 -*-
"""
Módulo AIU (Administración, Imprevistos, Utilidad) para Facturación Electrónica DIAN
Versión completa para Odoo 17 con manejo automático de impuestos y líneas dinámicas
"""
from odoo import api, fields, models, Command, _
from odoo.exceptions import UserError, ValidationError
import logging

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    """Extensión de producto para soporte AIU"""
    _inherit = "product.template"
    
    line_price_reference = fields.Float(
        string='Precio de referencia',
        help="Precio de referencia para cálculos especiales"
    )
    
    operation_type = fields.Selection(
        [("09", "Servicios AIU"), 
         ("10", "Estándar"), 
         ("11", "Mandatos bienes")],
        string="Tipo de operación DIAN",
        default="10",
        help="Define el tipo de operación para facturación electrónica DIAN"
    )
    
    is_aiu_service = fields.Boolean(
        string="Es servicio AIU", 
        compute='_compute_is_aiu_service',
        store=True,
        help="Indica si el producto es un servicio que aplica para AIU"
    )
    
    aiu_type = fields.Selection([
        ('service', 'Servicio Principal'),
        ('administration', 'Administración'),
        ('unforeseen', 'Imprevistos'),
        ('utility', 'Utilidad')
    ], string="Tipo AIU", default='service',
       help="Tipo de componente AIU que representa este producto")
    
    @api.depends('operation_type')
    def _compute_is_aiu_service(self):
        """Determina si es un servicio AIU basado en el tipo de operación"""
        for record in self:
            record.is_aiu_service = record.operation_type == '09'


class AIUTaxConfig(models.Model):
    """Configuración de impuestos específicos para componentes AIU"""
    _name = 'aiu.tax.config'
    _description = 'Configuración de Impuestos AIU'
    _rec_name = 'name'
    _order = 'sequence, name'
    
    name = fields.Char(
        string="Nombre", 
        required=True,
        help="Nombre descriptivo de la configuración"
    )
    
    sequence = fields.Integer(
        string="Secuencia",
        default=10,
        help="Orden de aparición en listas"
    )
    
    company_id = fields.Many2one(
        'res.company',
        string="Compañía",
        default=lambda self: self.env.company,
        required=True,
        help="Compañía a la que aplica esta configuración"
    )
    
    active = fields.Boolean(
        default=True,
        help="Si está activo, esta configuración puede ser utilizada"
    )
    
    tax_base_type = fields.Selection([
        ('subtotal', 'Subtotal del servicio'),
        ('base_aiu', 'Base AIU (A+I+U)'),
        ('utility', 'Solo Utilidad'),
        ('specific', 'Específico por componente'),
        ('manual', 'Base manual por línea')
    ], string="Base para impuestos", 
       default='base_aiu', 
       required=True,
       help="Define sobre qué base se calculan los impuestos")
    
    # Configuración de impuestos por componente
    administration_tax_ids = fields.Many2many(
        'account.tax',
        'aiu_config_admin_tax_rel',
        'config_id',
        'tax_id',
        string="Impuestos Administración",
        domain="[('type_tax_use', '=', 'sale'), ('company_id', '=', company_id)]",
        help="Impuestos aplicables al componente de administración"
    )
    
    unforeseen_tax_ids = fields.Many2many(
        'account.tax',
        'aiu_config_unforeseen_tax_rel',
        'config_id',
        'tax_id',
        string="Impuestos Imprevistos",
        domain="[('type_tax_use', '=', 'sale'), ('company_id', '=', company_id)]",
        help="Impuestos aplicables al componente de imprevistos"
    )
    
    utility_tax_ids = fields.Many2many(
        'account.tax',
        'aiu_config_utility_tax_rel',
        'config_id',
        'tax_id',
        string="Impuestos Utilidad",
        domain="[('type_tax_use', '=', 'sale'), ('company_id', '=', company_id)]",
        help="Impuestos aplicables al componente de utilidad"
    )
    
    service_tax_ids = fields.Many2many(
        'account.tax',
        'aiu_config_service_tax_rel',
        'config_id',
        'tax_id',
        string="Impuestos Servicio Principal",
        domain="[('type_tax_use', '=', 'sale'), ('company_id', '=', company_id)]",
        help="Impuestos aplicables al servicio principal"
    )
    
    notes = fields.Text(
        string="Notas",
        help="Notas adicionales sobre esta configuración"
    )
    
    @api.model
    def get_default_config(self, company_id=None):
        """Obtiene o crea la configuración por defecto para la compañía"""
        if not company_id:
            company_id = self.env.company.id
        
        # Buscar configuración activa
        config = self.search([
            ('company_id', '=', company_id),
            ('active', '=', True)
        ], limit=1)
        
        # Si no existe, crear una por defecto
        if not config:
            _logger.info(f"Creando configuración AIU por defecto para compañía {company_id}")
            config = self.create({
                'name': 'Configuración AIU Por Defecto',
                'company_id': company_id,
                'tax_base_type': 'base_aiu',
            })
        
        return config


class AIUMixin(models.AbstractModel):
    """Mixin con funcionalidad AIU compartida entre modelos"""
    _name = 'aiu.mixin'
    _description = 'AIU Mixin'
    
    # Configuración del modelo AIU
    aiu_model = fields.Selection([
        ('model_1', 'Base AIU NO sumada al total'),
        ('model_2', 'Base AIU sumada al total')
    ], string="Modelo AIU", 
       default='model_1',
       help="Define cómo se suma la base AIU al total del documento")
    
    show_aiu_in_lines = fields.Boolean(
        string="Mostrar AIU en líneas", 
        default=True,
        help="Si está activo, los componentes AIU se mostrarán como líneas separadas"
    )
    
    # Porcentajes AIU - pueden ser editados manualmente
    aiu_administration_percent = fields.Float(
        string="% Administración", 
        default=10.0,
        digits=(5, 2),
        help="Porcentaje de administración sobre el servicio base"
    )
    
    aiu_unforeseen_percent = fields.Float(
        string="% Imprevistos", 
        default=5.0,
        digits=(5, 2),
        help="Porcentaje de imprevistos sobre el servicio base"
    )
    
    aiu_utility_percent = fields.Float(
        string="% Utilidad", 
        default=5.0,
        digits=(5, 2),
        help="Porcentaje de utilidad sobre el servicio base"
    )
    
    # Configuración de impuestos
    aiu_tax_config_id = fields.Many2one(
        'aiu.tax.config', 
        string="Configuración de Impuestos AIU",
        help="Configuración específica de impuestos para componentes AIU"
    )
    
    aiu_tax_source = fields.Selection([
        ('from_service', 'Heredar de línea de servicio'),
        ('from_config', 'Usar configuración específica AIU'),
        ('no_tax', 'Sin impuestos en AIU')
    ], string="Origen de impuestos AIU", 
       default='from_config',
       help="Define de dónde se toman los impuestos para las líneas AIU")
    
    # Montos calculados - sin currency_field porque será definido en modelos concretos
    aiu_base_amount = fields.Float(
        string="Base AIU", 
        compute='_compute_aiu_amounts', 
        store=True,
        help="Suma total de los servicios base para cálculo AIU"
    )
    
    aiu_administration_amount = fields.Float(
        string="Administración",
        compute='_compute_aiu_amounts',
        inverse='_inverse_aiu_administration_amount',
        store=True,
        help="Monto calculado de administración"
    )
    
    aiu_unforeseen_amount = fields.Float(
        string="Imprevistos",
        compute='_compute_aiu_amounts',
        inverse='_inverse_aiu_unforeseen_amount',
        store=True,
        help="Monto calculado de imprevistos"
    )
    
    aiu_utility_amount = fields.Float(
        string="Utilidad",
        compute='_compute_aiu_amounts',
        inverse='_inverse_aiu_utility_amount',
        store=True,
        help="Monto calculado de utilidad"
    )
    
    # Indicador de factura AIU
    is_aiu_invoice = fields.Boolean(
        string="Es factura AIU",
        compute='_compute_is_aiu_invoice',
        store=True,
        help="Indica si la factura contiene servicios AIU"
    )
    
    contract_note = fields.Text(
        string="Nota de contrato",
        help="Información adicional del contrato para incluir en la factura"
    )
    
    def _compute_aiu_amounts(self):
        """Calcula los montos AIU basados en porcentajes"""
        for record in self:
            record.aiu_base_amount = 0
            record.aiu_administration_amount = 0
            record.aiu_unforeseen_amount = 0
            record.aiu_utility_amount = 0
    
    def _inverse_aiu_administration_amount(self):
        """Calcula el porcentaje cuando se modifica el monto manualmente"""
        for record in self:
            if record.aiu_base_amount > 0:
                record.aiu_administration_percent = (
                    record.aiu_administration_amount / record.aiu_base_amount * 100
                )
    
    def _inverse_aiu_unforeseen_amount(self):
        """Calcula el porcentaje cuando se modifica el monto manualmente"""
        for record in self:
            if record.aiu_base_amount > 0:
                record.aiu_unforeseen_percent = (
                    record.aiu_unforeseen_amount / record.aiu_base_amount * 100
                )
    
    def _inverse_aiu_utility_amount(self):
        """Calcula el porcentaje cuando se modifica el monto manualmente"""
        for record in self:
            if record.aiu_base_amount > 0:
                record.aiu_utility_percent = (
                    record.aiu_utility_amount / record.aiu_base_amount * 100
                )
    
    def _compute_is_aiu_invoice(self):
        """Determina si es una factura con servicios AIU"""
        for record in self:
            record.is_aiu_invoice = False
    
    @api.model
    def _get_or_create_aiu_products(self):
        """Obtiene o crea los productos AIU necesarios"""
        ProductProduct = self.env['product.product']
        products = {}
        
        aiu_configs = [
            ('administration', 'Administración AIU', 'ADM-AIU'),
            ('unforeseen', 'Imprevistos AIU', 'IMP-AIU'),
            ('utility', 'Utilidad AIU', 'UTI-AIU'),
        ]
        
        for aiu_type, name, default_code in aiu_configs:
            # Buscar producto existente
            domain = [
                ('aiu_type', '=', aiu_type),
                '|',
                ('company_id', '=', False),
                ('company_id', '=', self.env.company.id)
            ]
            
            product = ProductProduct.search(domain, limit=1)
            
            if not product:
                _logger.info(f"Creando producto AIU: {name}")
                product = ProductProduct.create({
                    'name': name,
                    'default_code': default_code,
                    'type': 'service',
                    'aiu_type': aiu_type,
                    'operation_type': '09',
                    'taxes_id': False,
                    'supplier_taxes_id': False,
                    'invoice_policy': 'order',
                    'purchase_ok': False,
                    'sale_ok': True,
                    'categ_id': self.env.ref('product.product_category_all').id,
                })
            
            products[aiu_type] = product
        
        return products


class SaleOrder(models.Model):
    """Extensión de orden de venta con funcionalidad AIU"""
    _name = 'sale.order'
    _inherit = ['sale.order', 'aiu.mixin']
    
    # Sobrescribir campos del mixin como Monetary con currency_field
    aiu_base_amount = fields.Monetary(
        string="Base AIU", 
        compute='_compute_aiu_amounts', 
        store=True,
        currency_field='currency_id',
        help="Suma total de los servicios base para cálculo AIU"
    )
    
    aiu_administration_amount = fields.Monetary(
        string="Administración",
        compute='_compute_aiu_amounts',
        inverse='_inverse_aiu_administration_amount',
        store=True,
        currency_field='currency_id',
        help="Monto calculado de administración"
    )
    
    aiu_unforeseen_amount = fields.Monetary(
        string="Imprevistos",
        compute='_compute_aiu_amounts',
        inverse='_inverse_aiu_unforeseen_amount',
        store=True,
        currency_field='currency_id',
        help="Monto calculado de imprevistos"
    )
    is_aiu_order = fields.Boolean("Tiene AIU")
    aiu_utility_amount = fields.Monetary(
        string="Utilidad",
        compute='_compute_aiu_amounts',
        inverse='_inverse_aiu_utility_amount',
        store=True,
        currency_field='currency_id',
        help="Monto calculado de utilidad"
    )
    
    @api.depends('order_line.price_subtotal', 'order_line.is_aiu_base',
                 'aiu_administration_percent', 'aiu_unforeseen_percent', 
                 'aiu_utility_percent')
    def _compute_aiu_amounts(self):
        """Calcula los montos AIU basados en líneas marcadas como base"""
        for order in self:
            # Filtrar líneas que son base para AIU
            service_lines = order.order_line.filtered(
                lambda l: l.product_id.is_aiu_service and 
                         l.product_id.aiu_type == 'service' and
                         not l.display_type and
                         l.is_aiu_base
            )
            
            service_subtotal = sum(service_lines.mapped('price_subtotal'))
            order.aiu_base_amount = service_subtotal
            
            # Si no está en modo inverso, calcular montos
            if not self.env.context.get('inverse_aiu'):
                order.aiu_administration_amount = service_subtotal * (order.aiu_administration_percent / 100)
                order.aiu_unforeseen_amount = service_subtotal * (order.aiu_unforeseen_percent / 100)
                order.aiu_utility_amount = service_subtotal * (order.aiu_utility_percent / 100)
    
    @api.depends('order_line.product_id', 'order_line.is_aiu_base', 'is_aiu_order')
    def _compute_is_aiu_invoice(self):
        """Determina si la orden tiene servicios AIU"""
        for order in self:
            order.is_aiu_invoice = (order.is_aiu_order and any(
                line.product_id.is_aiu_service and 
                line.product_id.aiu_type == 'service' and
                line.is_aiu_base
                for line in order.order_line if not line.display_type
            ))
    
    @api.onchange('is_aiu_order')
    def _onchange_is_aiu_order(self):
        """Activar/desactivar funcionalidad AIU"""
        if self.is_aiu_order:
            # Hacer backup de impuestos actuales y aplicar configuración AIU
            #self._backup_original_taxes()
            if not self.aiu_tax_config_id:
                # Asignar configuración por defecto
                config = self.env['aiu.tax.config'].get_default_config()
                if config:
                    self.aiu_tax_config_id = config.id
            self._apply_aiu_taxes_to_service_lines()
        else:
            # Restaurar impuestos originales
            #self._restore_original_taxes()
            # Limpiar líneas AIU
            if self.show_aiu_in_lines:
                self.show_aiu_in_lines = False
                self._update_aiu_lines()
    
    def _backup_original_taxes(self):
        """Hacer backup de los impuestos originales antes de aplicar AIU"""
        self.ensure_one()
        import json
        
        backup_data = {}
        for line in self.order_line:
            if line.product_id and not line.is_aiu_line:
                backup_data[line.id] = {
                    'tax_ids': line.tax_id.ids if line.tax_id else [],
                    'product_id': line.product_id.id,
                    'is_aiu_base': line.is_aiu_base
                }
        
        self.original_taxes_backup = json.dumps(backup_data) if backup_data else False
    
    def _restore_original_taxes(self):
        """Restaurar los impuestos originales"""
        self.ensure_one()
        if not self.original_taxes_backup:
            return
        
        import json
        try:
            backup_data = json.loads(self.original_taxes_backup)
            for line in self.order_line:
                if str(line.id) in backup_data:
                    line_backup = backup_data[str(line.id)]
                    line.tax_id = [(Command.set(line_backup['tax_ids']))]
                    line.is_aiu_base = line_backup['is_aiu_base']
        except Exception as e:
            _logger.warning(f"Error restaurando impuestos originales: {e}")
    
    @api.onchange('aiu_administration_percent', 'aiu_unforeseen_percent', 
                  'aiu_utility_percent', 'show_aiu_in_lines', 'aiu_tax_source', 
                  'aiu_tax_config_id')
    def _onchange_aiu_config(self):
        """Actualizar líneas AIU cuando cambia la configuración"""
        if self.state not in ['draft', 'sent'] or not self.is_aiu_order:
            return
        
        self._apply_aiu_taxes_to_service_lines()
        
        self._compute_aiu_amounts()
        if self.show_aiu_in_lines:
            self._update_aiu_lines()
        self._compute_amounts()
    
    @api.onchange('order_line')
    def _onchange_order_line(self):
        """Actualizar AIU cuando cambian las líneas"""
        if self.state not in ['draft', 'sent'] or not self.is_aiu_order:
            return
        
        # Verificar si hay servicios AIU
        has_aiu_service = any(
            line.product_id.is_aiu_service and 
            line.product_id.aiu_type == 'service' and
            line.is_aiu_base
            for line in self.order_line if not line.display_type
        )
        
        if has_aiu_service:
            # Recalcular montos
            self._compute_aiu_amounts()
            if self.show_aiu_in_lines:
                self._update_aiu_lines()
    
    def _update_aiu_lines(self):
        """Actualizar o crear líneas AIU siguiendo el patrón correcto de Odoo"""
        if not self.is_aiu_order or not self.show_aiu_in_lines:
            aiu_lines = self.order_line.filtered(
                lambda l: l.product_id.aiu_type in ['administration', 'unforeseen', 'utility'] and l.is_aiu_line
            )
            if aiu_lines:
                if self != self._origin:  # En borrador
                    # Remover de la lista en memoria
                    self.order_line -= aiu_lines
                else:  # Documento creado
                    aiu_lines.unlink()
            return
        
        # Aplicar impuestos a líneas de servicio primero
        self._apply_aiu_taxes_to_service_lines()
        
        # Obtener productos AIU
        aiu_products = self._get_or_create_aiu_products()
        
        # Buscar última línea de servicio base
        service_lines = self.order_line.filtered(
            lambda l: l.product_id.is_aiu_service and 
                     l.product_id.aiu_type == 'service' and
                     not l.display_type and
                     l.is_aiu_base
        )
        
        if not service_lines:
            return
        
        base_sequence = max(service_lines.mapped('sequence'))
        
        # Mapeo de líneas AIU existentes
        existing_aiu_lines = {
            line.product_id.aiu_type: line
            for line in self.order_line
            if line.product_id.aiu_type in ['administration', 'unforeseen', 'utility'] and line.is_aiu_line
        }
        
        # Configurar líneas AIU
        aiu_configs = [
            ('administration', self.aiu_administration_percent, self.aiu_administration_amount, 1),
            ('unforeseen', self.aiu_unforeseen_percent, self.aiu_unforeseen_amount, 2),
            ('utility', self.aiu_utility_percent, self.aiu_utility_amount, 3),
        ]
        
        for aiu_type, percent, amount, seq_offset in aiu_configs:
            if amount > 0:
                taxes = self._get_aiu_line_taxes(aiu_type)
                line_values = {
                    'order_id': self.id,
                    'product_id': aiu_products[aiu_type].id,
                    'name': f"{aiu_products[aiu_type].name} ({percent:.2f}%)",
                    'product_uom_qty': 1,
                    'price_unit': amount,
                    'tax_id': [(Command.set(taxes))],
                    'sequence': base_sequence + seq_offset,
                    'is_aiu_line': True,
                }
                
                if aiu_type in existing_aiu_lines:
                    # Actualizar línea existente
                    existing_aiu_lines[aiu_type].write({
                        'name': f"{aiu_products[aiu_type].name} ({percent:.2f}%)",
                        'price_unit': amount,
                        'tax_id': [(Command.set(taxes))],
                        'sequence': base_sequence + seq_offset,
                        'is_aiu_line': True,
                    })
                else:
                    if self != self._origin:  # En borrador/memoria
                        new_line = self.env['sale.order.line'].new(line_values)
                        self.order_line += new_line
                    else: 
                        self.env['sale.order.line'].create(line_values)
            elif aiu_type in existing_aiu_lines:
                line_to_remove = existing_aiu_lines[aiu_type]
                if self != self._origin:  
                    self.order_line -= line_to_remove
                else:  
                    line_to_remove.unlink()
    
    def _get_aiu_line_taxes(self, aiu_type):
        """Obtener impuestos para línea AIU según configuración"""
        self.ensure_one()
        
        if self.aiu_tax_source == 'no_tax':
            return []
        elif self.aiu_tax_source == 'from_service':
            service_lines = self.order_line.filtered(
                lambda l: l.product_id.is_aiu_service and 
                         l.product_id.aiu_type == 'service' and
                         not l.display_type and
                         l.is_aiu_base
            )
            if service_lines:
                return service_lines[0].tax_id.ids
        else:  # from_config
            if self.aiu_tax_config_id:
                tax_field_mapping = {
                    'administration': 'administration_tax_ids',
                    'unforeseen': 'unforeseen_tax_ids',
                    'utility': 'utility_tax_ids',
                    'service': 'service_tax_ids'  # Agregado para servicios
                }
                if aiu_type in tax_field_mapping:
                    return self.aiu_tax_config_id[tax_field_mapping[aiu_type]].ids
        
        return []
    
    def _apply_aiu_taxes_to_service_lines(self):
        """Aplicar impuestos de configuración AIU a líneas de servicio"""
        self.ensure_one()
        if not self.is_aiu_order or not self.aiu_tax_config_id or self.aiu_tax_source != 'from_config':
            return
        
        # Buscar líneas de servicio AIU
        service_lines = self.order_line.filtered(
            lambda l: l.product_id.is_aiu_service and 
                     l.product_id.aiu_type == 'service' and
                     not l.display_type
        )
        
        if service_lines:
            service_taxes = self._get_aiu_line_taxes('service')
            for line in service_lines:
                if service_taxes:
                    line.tax_id = [(Command.set(service_taxes))]
                # Para configuración manual, determinar automáticamente is_aiu_base
                if self.aiu_tax_config_id.tax_base_type == 'manual':
                    line.is_aiu_base = True  # Por defecto marcar como base
    
    def action_apply_aiu(self):
        """Aplicar AIU manualmente"""
        self.ensure_one()
        if self.state not in ['draft', 'sent']:
            raise UserError(_("Solo puede aplicar AIU en cotizaciones en borrador."))
        
        if not self.is_aiu_order:
            raise UserError(_("Debe marcar esta orden como 'Es orden AIU' primero."))
        
        # Aplicar impuestos a líneas de servicio
        self._apply_aiu_taxes_to_service_lines()
        
        self._compute_aiu_amounts()
        self._update_aiu_lines()
        self._compute_amounts()  # Recalcular totales
        return {'type': 'ir.actions.act_window_close'}
    
    def action_apply_aiu_taxes(self):
        """Aplicar impuestos AIU a todas las líneas relevantes"""
        self.ensure_one()
        if self.state not in ['draft', 'sent']:
            raise UserError(_("Solo puede aplicar impuestos en cotizaciones en borrador."))
        
        if not self.is_aiu_order:
            raise UserError(_("Debe marcar esta orden como 'Es orden AIU' primero."))
        
        self._apply_aiu_taxes_to_service_lines()
        return {'type': 'ir.actions.act_window_close'}
    
    def action_toggle_aiu_order(self):
        """Activar/desactivar orden AIU"""
        self.ensure_one()
        if self.state not in ['draft', 'sent']:
            raise UserError(_("Solo puede cambiar el estado AIU en cotizaciones en borrador."))
        
        self.is_aiu_order = not self.is_aiu_order
        return {'type': 'ir.actions.act_window_close'}
    
    def action_recompute_all(self):
        """Recomputar todos los valores incluyendo AIU"""
        self.ensure_one()
        if self.state not in ['draft', 'sent']:
            raise UserError(_("Solo puede recomputar en cotizaciones en borrador."))
        
        # Forzar recomputo
        self._compute_aiu_amounts()
        self._update_aiu_lines()
        self._compute_amounts()  # Método nativo de Odoo 17 para recalcular totales
        
        return {'type': 'ir.actions.act_window_close'}
    
    @api.model_create_multi
    def create(self, vals_list):
        """Crear con configuración AIU por defecto si aplica"""
        for vals in vals_list:
            # Asignar configuración por defecto si no viene
            if 'aiu_tax_config_id' not in vals:
                config = self.env['aiu.tax.config'].get_default_config()
                if config:
                    vals['aiu_tax_config_id'] = config.id
        
        return super().create(vals_list)
    
    def _prepare_invoice(self):
        """Transferir configuración AIU a la factura"""
        invoice_vals = super()._prepare_invoice()
        
        if self.is_aiu_order:
            invoice_vals.update({
                'is_aiu_invoice_move': True,  # Campo específico para facturas
                'aiu_model': self.aiu_model,
                'show_aiu_in_lines': self.show_aiu_in_lines,
                'aiu_administration_percent': self.aiu_administration_percent,
                'aiu_unforeseen_percent': self.aiu_unforeseen_percent,
                'aiu_utility_percent': self.aiu_utility_percent,
                'aiu_tax_config_id': self.aiu_tax_config_id.id if self.aiu_tax_config_id else False,
                'aiu_tax_source': self.aiu_tax_source,
                'contract_note': self.contract_note,
                'original_taxes_backup': self.original_taxes_backup,
            })
            
            if hasattr(self.env['account.move'], 'fe_operation_type'):
                invoice_vals['fe_operation_type'] = '09' if self.is_aiu_invoice else '10'
        
        return invoice_vals


class SaleOrderLine(models.Model):
    """Extensión de línea de orden de venta para AIU"""
    _inherit = 'sale.order.line'
    
    line_contract_note = fields.Text(
        string="Nota de contrato por línea",
        help="Nota específica de esta línea para el contrato"
    )
    
    is_aiu_line = fields.Boolean(
        string="Es línea AIU",
        compute='_compute_is_aiu_line',
        store=True,
        help="Indica si esta línea es un componente AIU"
    )
    
    is_aiu_base = fields.Boolean(
        string="Base para AIU",
        default=True,
        help="Si está marcado, esta línea se incluye en el cálculo de AIU"
    )
    
    @api.depends('product_id.aiu_type')
    def _compute_is_aiu_line(self):
        """Determina si es una línea de componente AIU"""
        for line in self:
            line.is_aiu_line = line.product_id.aiu_type in [
                'administration', 'unforeseen', 'utility'
            ]
    
    @api.onchange('is_aiu_base')
    def _onchange_is_aiu_base(self):
        """Actualizar cálculos AIU cuando cambia la marca de base"""
        if self.order_id and self.order_id.state in ['draft', 'sent'] and self.order_id.is_aiu_order:
            self.order_id._compute_aiu_amounts()
            if self.order_id.show_aiu_in_lines:
                self.order_id._update_aiu_lines()
    
    @api.onchange('product_id')
    def _onchange_product_id_aiu(self):
        """Aplicar impuestos automáticamente para productos AIU y marcar como base si es servicio"""
        if self.product_id and self.order_id and self.order_id.is_aiu_order:
            if (self.product_id.is_aiu_service and 
                self.product_id.aiu_type == 'service'):
                self.is_aiu_base = True
                
                if (self.order_id.aiu_tax_config_id and 
                    self.order_id.aiu_tax_source == 'from_config'):
                    service_taxes = self.order_id._get_aiu_line_taxes('service')
                    if service_taxes:
                        self.tax_id = [(Command.set(service_taxes))]
    
    @api.onchange('product_id')
    def _onchange_product_id_aiu_lines(self):
        """Aplicar configuración específica para líneas AIU generadas automáticamente"""
        if (self.product_id and self.product_id.aiu_type in ['administration', 'unforeseen', 'utility'] 
            and self.order_id and self.order_id.is_aiu_order and self.order_id.aiu_tax_config_id and 
            self.order_id.aiu_tax_source == 'from_config'):
            
            aiu_taxes = self.order_id._get_aiu_line_taxes(self.product_id.aiu_type)
            if aiu_taxes:
                self.tax_id = [(Command.set(aiu_taxes))]
                
            self.is_aiu_line = True
    
    def write(self, vals):
        """Sobrescribir write en líneas para detectar cambios relevantes"""
        result = super().write(vals)
        
        if 'is_aiu_base' in vals or 'price_unit' in vals or 'product_uom_qty' in vals:
            for line in self:
                if (line.order_id and line.order_id.state in ['draft', 'sent'] and
                    line.order_id.is_aiu_order and line.product_id.is_aiu_service and 
                    line.product_id.aiu_type == 'service'):
                    
                    line.order_id._compute_aiu_amounts()
                    
                    if line.order_id.show_aiu_in_lines:
                        try:
                            line.order_id._update_aiu_lines()
                        except Exception as e:
                            _logger.warning(f"Error actualizando líneas AIU: {e}")
        
        if 'product_id' in vals:
            for line in self:
                if (line.product_id and line.order_id and line.order_id.state in ['draft', 'sent'] and
                    line.order_id.is_aiu_order and line.order_id.aiu_tax_config_id and 
                    line.order_id.aiu_tax_source == 'from_config'):
                    
                    if line.product_id.is_aiu_service and line.product_id.aiu_type == 'service':
                        line.is_aiu_base = True 
                        service_taxes = line.order_id._get_aiu_line_taxes('service')
                        if service_taxes:
                            line.tax_id = [(Command.set(service_taxes))]
                    
                    elif line.product_id.aiu_type in ['administration', 'unforeseen', 'utility']:
                        aiu_taxes = line.order_id._get_aiu_line_taxes(line.product_id.aiu_type)
                        if aiu_taxes:
                            line.tax_id = [(Command.set(aiu_taxes))]
        
        return result
    
    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        
        for line in lines:
            if (line.order_id and line.order_id.state in ['draft', 'sent'] and 
                line.order_id.is_aiu_order and line.order_id.aiu_tax_config_id and 
                line.order_id.aiu_tax_source == 'from_config' and line.product_id):
                
                taxes_to_apply = None
                
                if line.product_id.is_aiu_service and line.product_id.aiu_type == 'service':
                    line.is_aiu_base = True  
                    taxes_to_apply = line.order_id._get_aiu_line_taxes('service')
                elif line.product_id.aiu_type in ['administration', 'unforeseen', 'utility']:
                    taxes_to_apply = line.order_id._get_aiu_line_taxes(line.product_id.aiu_type)
                
                if taxes_to_apply:
                    line.tax_id = [(Command.set(taxes_to_apply))]
        
        return lines


class AccountMove(models.Model):
    """Extensión de factura con funcionalidad AIU"""
    _name = 'account.move'
    _inherit = ['account.move', 'aiu.mixin']
    
    # Campo específico para marcar como factura AIU
    is_aiu_invoice_move = fields.Boolean(
        string="Es factura AIU",
        default=False,
        help="Marque esta casilla para habilitar la funcionalidad AIU en esta factura"
    )
    
    # Campos para guardar configuración original de impuestos
    original_taxes_backup = fields.Text(
        string="Respaldo de impuestos originales",
        help="Backup de los impuestos originales antes de aplicar configuración AIU"
    )
    
    # Sobrescribir campos del mixin como Monetary con currency_field
    aiu_base_amount = fields.Monetary(
        string="Base AIU", 
        compute='_compute_aiu_amounts', 
        store=True,
        currency_field='currency_id',
        help="Suma total de los servicios base para cálculo AIU"
    )
    
    aiu_administration_amount = fields.Monetary(
        string="Administración",
        compute='_compute_aiu_amounts',
        inverse='_inverse_aiu_administration_amount',
        store=True,
        currency_field='currency_id',
        help="Monto calculado de administración"
    )
    
    aiu_unforeseen_amount = fields.Monetary(
        string="Imprevistos",
        compute='_compute_aiu_amounts',
        inverse='_inverse_aiu_unforeseen_amount',
        store=True,
        currency_field='currency_id',
        help="Monto calculado de imprevistos"
    )
    
    aiu_utility_amount = fields.Monetary(
        string="Utilidad",
        compute='_compute_aiu_amounts',
        inverse='_inverse_aiu_utility_amount',
        store=True,
        currency_field='currency_id',
        help="Monto calculado de utilidad"
    )
    
    def _get_aiu_line_data_to_create(self):
        """Retorna datos de líneas AIU que deben existir"""
        self.ensure_one()
        if not self.show_aiu_in_lines or self.move_type not in ['out_invoice', 'out_refund']:
            return []
        
        needed_lines = []
        aiu_products = self._get_or_create_aiu_products()
        
        aiu_configs = [
            ('administration', self.aiu_administration_amount, aiu_products.get('administration')),
            ('unforeseen', self.aiu_unforeseen_amount, aiu_products.get('unforeseen')),
            ('utility', self.aiu_utility_amount, aiu_products.get('utility')),
        ]
        
        sequence = 1000  # Secuencia alta para que aparezcan al final
        for aiu_type, amount, product in aiu_configs:
            if amount > 0 and product:
                taxes = self._get_aiu_line_taxes(aiu_type)
                percent = getattr(self, f'aiu_{aiu_type}_percent', 0)
                
                line_data = {
                    'product_id': product.id,
                    'name': f"{product.name} ({percent:.2f}%)",
                    'quantity': 1,
                    'price_unit': amount,
                    'tax_ids': [(6, 0, taxes)],
                    'sequence': sequence,
                    'display_type': 'product',
                }
                needed_lines.append(line_data)
                sequence += 1
        
        return needed_lines
    
    def _update_aiu_lines_manual(self):
        """Actualizar líneas AIU manualmente (para botones de acción)"""
        self.ensure_one()
        if self.state != 'draft':
            return
        
        existing_aiu_lines = self.invoice_line_ids.filtered(
            lambda l: l.is_aiu_line and l.product_id.aiu_type in ['administration', 'unforeseen', 'utility']
        )
        if existing_aiu_lines:
            existing_aiu_lines.unlink()
        
        self._apply_aiu_taxes_to_service_lines()
        
        needed_lines = self._get_aiu_line_data_to_create()
        for line_data in needed_lines:
            line_data['move_id'] = self.id
            if 'tax_ids' in line_data and line_data['tax_ids']:
                pass
            self.env['account.move.line'].create(line_data)
    
    @api.depends('invoice_line_ids.price_subtotal', 'invoice_line_ids.is_aiu_base',
                 'aiu_administration_percent', 'aiu_unforeseen_percent', 
                 'aiu_utility_percent')
    def _compute_aiu_amounts(self):
        """Calcula los montos AIU en la factura"""
        for move in self:
            if move.move_type not in ['out_invoice', 'out_refund']:
                move.aiu_base_amount = 0
                move.aiu_administration_amount = 0
                move.aiu_unforeseen_amount = 0
                move.aiu_utility_amount = 0
                continue
            
            service_lines = move.invoice_line_ids.filtered(
                lambda l: l.product_id.is_aiu_service and 
                         l.product_id.aiu_type == 'service' and
                         l.display_type == 'product' and
                         l.is_aiu_base
            )
            
            service_subtotal = sum(service_lines.mapped('price_subtotal'))
            move.aiu_base_amount = service_subtotal
            
            if not self.env.context.get('inverse_aiu'):
                move.aiu_administration_amount = service_subtotal * (move.aiu_administration_percent / 100)
                move.aiu_unforeseen_amount = service_subtotal * (move.aiu_unforeseen_percent / 100)
                move.aiu_utility_amount = service_subtotal * (move.aiu_utility_percent / 100)
    
    @api.depends('invoice_line_ids.product_id', 'invoice_line_ids.is_aiu_base', 'is_aiu_invoice_move')
    def _compute_is_aiu_invoice(self):
        """Determina si es una factura con servicios AIU"""
        for move in self:
            if move.move_type not in ['out_invoice', 'out_refund']:
                move.is_aiu_invoice = False
            else:
                move.is_aiu_invoice = (move.is_aiu_invoice_move and any(
                    line.product_id.is_aiu_service and 
                    line.product_id.aiu_type == 'service' and
                    line.is_aiu_base
                    for line in move.invoice_line_ids 
                    if line.display_type == 'product'
                ))
    
    @api.onchange('is_aiu_invoice_move')
    def _onchange_is_aiu_invoice_move(self):
        """Activar/desactivar funcionalidad AIU en factura"""
        if self.is_aiu_invoice_move:
            if not self.aiu_tax_config_id:
                config = self.env['aiu.tax.config'].get_default_config()
                if config:
                    self.aiu_tax_config_id = config.id
            self._apply_aiu_taxes_to_service_lines()
        else:
            if self.show_aiu_in_lines:
                self.show_aiu_in_lines = False
                self._update_aiu_lines_manual()
    
    def _backup_original_taxes(self):
        """Hacer backup de los impuestos originales antes de aplicar AIU"""
        self.ensure_one()
        import json
        
        backup_data = {}
        for line in self.invoice_line_ids:
            if line.product_id and not line.is_aiu_line:
                backup_data[line.id] = {
                    'tax_ids': line.tax_ids.ids if line.tax_ids else [],
                    'product_id': line.product_id.id,
                    'is_aiu_base': line.is_aiu_base
                }
        
        self.original_taxes_backup = json.dumps(backup_data) if backup_data else False
    
    def _restore_original_taxes(self):
        """Restaurar los impuestos originales"""
        self.ensure_one()
        if not self.original_taxes_backup:
            return
        
        import json
        try:
            backup_data = json.loads(self.original_taxes_backup)
            for line in self.invoice_line_ids:
                if str(line.id) in backup_data:
                    line_backup = backup_data[str(line.id)]
                    line.tax_ids = [(Command.set(line_backup['tax_ids']))]
                    line.is_aiu_base = line_backup['is_aiu_base']
        except Exception as e:
            _logger.warning(f"Error restaurando impuestos originales: {e}")
    
    @api.onchange('aiu_administration_percent', 'aiu_unforeseen_percent', 
                  'aiu_utility_percent', 'show_aiu_in_lines', 'aiu_tax_source', 
                  'aiu_tax_config_id')
    def _onchange_aiu_config(self):
        """Actualizar líneas AIU cuando cambia la configuración"""
        if self.state != 'draft' or not self.is_aiu_invoice_move:
            return
        
        self._apply_aiu_taxes_to_service_lines()
        
        self._compute_aiu_amounts()
    
    @api.onchange('invoice_line_ids')
    def _onchange_invoice_line_ids(self):
        """Actualizar AIU cuando cambian las líneas"""
        if self.state != 'draft' or not self.is_aiu_invoice_move:
            return
        
        # Verificar si hay servicios AIU base
        has_aiu_service = any(
            line.product_id.is_aiu_service and 
            line.product_id.aiu_type == 'service' and
            line.is_aiu_base
            for line in self.invoice_line_ids 
            if line.display_type == 'product'
        )
        
        if has_aiu_service:
            # Forzar recálculo de montos AIU
            self._compute_aiu_amounts()
    
    def _get_aiu_line_taxes(self, aiu_type):
        """Obtener impuestos para línea AIU en factura"""
        self.ensure_one()
        
        if self.aiu_tax_source == 'no_tax':
            return []
        elif self.aiu_tax_source == 'from_service':
            service_lines = self.invoice_line_ids.filtered(
                lambda l: l.product_id.is_aiu_service and 
                         l.product_id.aiu_type == 'service' and
                         l.display_type == 'product' and
                         l.is_aiu_base
            )
            if service_lines:
                return service_lines[0].tax_ids.ids
        else:  # from_config
            if self.aiu_tax_config_id:
                tax_field_mapping = {
                    'administration': 'administration_tax_ids',
                    'unforeseen': 'unforeseen_tax_ids',
                    'utility': 'utility_tax_ids',
                    'service': 'service_tax_ids'  # Agregado para servicios
                }
                if aiu_type in tax_field_mapping:
                    return self.aiu_tax_config_id[tax_field_mapping[aiu_type]].ids
         
        return []
    
    def _apply_aiu_taxes_to_service_lines(self):
        """Aplicar impuestos de configuración AIU a líneas de servicio"""
        self.ensure_one()
        if not self.is_aiu_invoice_move or not self.aiu_tax_config_id or self.aiu_tax_source != 'from_config':
            return
        
        # Buscar líneas de servicio AIU
        service_lines = self.invoice_line_ids.filtered(
            lambda l: l.product_id.is_aiu_service and 
                     l.product_id.aiu_type == 'service' and
                     l.display_type == 'product'
        )
        
        if service_lines:
            service_taxes = self._get_aiu_line_taxes('service')
            for line in service_lines:
                if service_taxes:
                    line.tax_ids = [(Command.set(service_taxes))]
                if self.aiu_tax_config_id.tax_base_type == 'manual':
                    line.is_aiu_base = True  # Por defecto marcar como base
    
    def action_apply_aiu(self):
        """Aplicar AIU manualmente en factura"""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_("Solo puede aplicar AIU en facturas en borrador."))
        
        if not self.is_aiu_invoice_move:
            raise UserError(_("Debe marcar esta factura como 'Es factura AIU' primero."))
        
        self._apply_aiu_taxes_to_service_lines()
        
        self._compute_aiu_amounts()
        
        self._update_aiu_lines_manual()
        
        # Recalcular totales
        self._compute_totals()
        
        return {'type': 'ir.actions.act_window_close'}
    
    def action_apply_aiu_taxes(self):
        """Aplicar impuestos AIU a todas las líneas relevantes"""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_("Solo puede aplicar impuestos en facturas en borrador."))
        
        if not self.is_aiu_invoice_move:
            raise UserError(_("Debe marcar esta factura como 'Es factura AIU' primero."))
        
        self._apply_aiu_taxes_to_service_lines()
        return {'type': 'ir.actions.act_window_close'}
    
    def action_toggle_aiu_invoice(self):
        """Activar/desactivar factura AIU"""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_("Solo puede cambiar el estado AIU en facturas en borrador."))
        
        self.is_aiu_invoice_move = not self.is_aiu_invoice_move
        return {'type': 'ir.actions.act_window_close'}
    
    def action_recompute_all(self):
        """Recomputar todos los valores de la factura"""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_("Solo puede recomputar en facturas en borrador."))
        
        # Forzar recomputo completo
        self.action_apply_aiu()
        
        return {'type': 'ir.actions.act_window_close'}
    
    def write(self, vals):
        """Sobrescribir write para manejar líneas AIU automáticamente"""
        result = super().write(vals)
        
        # Campos que requieren actualización de líneas AIU
        aiu_fields = [
            'aiu_administration_percent', 'aiu_unforeseen_percent', 'aiu_utility_percent',
            'show_aiu_in_lines', 'aiu_tax_source', 'aiu_tax_config_id'
        ]
        
        # Si se modificaron campos AIU y está en borrador
        if any(field in vals for field in aiu_fields):
            for move in self:
                if (move.state == 'draft' and move.move_type in ['out_invoice', 'out_refund'] and
                    move.is_aiu_invoice_move):
                    # Verificar si hay servicios AIU
                    has_aiu_service = any(
                        line.product_id.is_aiu_service and 
                        line.product_id.aiu_type == 'service' and
                        line.is_aiu_base
                        for line in move.invoice_line_ids 
                        if line.display_type == 'product'
                    )
                    
                    if has_aiu_service and move.show_aiu_in_lines:
                        # Actualizar líneas AIU automáticamente
                        try:
                            move._update_aiu_lines_manual()
                        except Exception as e:
                            _logger.warning(f"Error actualizando líneas AIU automáticamente: {e}")
        
        return result
    
    def _schedule_aiu_lines_update(self):
        """Programa una actualización de líneas AIU de forma segura"""
        self.ensure_one()
        # Usar el contexto para evitar recursión
        if not self.env.context.get('updating_aiu_lines') and self.is_aiu_invoice_move:
            try:
                self.with_context(updating_aiu_lines=True)._update_aiu_lines_manual()
            except Exception as e:
                _logger.warning(f"Error en actualización automática de líneas AIU: {e}")
    
    @api.model_create_multi
    def create(self, vals_list):
        """Crear factura con configuración AIU si aplica"""
        for vals in vals_list:
            if vals.get('move_type') in ['out_invoice', 'out_refund']:
                if vals.get('is_aiu_invoice_move') and not vals.get('aiu_tax_config_id'):
                    config = self.env['aiu.tax.config'].get_default_config()
                    if config:
                        vals['aiu_tax_config_id'] = config.id
        
        return super().create(vals_list)
    
    def _post(self, soft=True):
        """Al confirmar, marcar como operación tipo 09 si tiene AIU"""
        for move in self:
            if hasattr(move, 'fe_operation_type') and move.is_aiu_invoice:
                if move.fe_operation_type != '09':
                    move.fe_operation_type = '09'
        
        return super()._post(soft=soft)


class AccountMoveLine(models.Model):
    """Extensión de línea de factura para AIU"""
    _inherit = 'account.move.line'
    
    line_contract_note = fields.Text(
        string="Nota de contrato por línea",
        help="Nota específica de esta línea para el contrato"
    )
    
    is_aiu_line = fields.Boolean(
        string="Es línea AIU",
        compute='_compute_is_aiu_line',
        store=True,
        help="Indica si esta línea es un componente AIU"
    )
    
    is_aiu_base = fields.Boolean(
        string="Base para AIU",
        default=True,
        help="Si está marcado, esta línea se incluye en el cálculo de AIU"
    )
    
    @api.depends('product_id.aiu_type')
    def _compute_is_aiu_line(self):
        """Determina si es una línea de componente AIU"""
        for line in self:
            line.is_aiu_line = line.product_id.aiu_type in [
                'administration', 'unforeseen', 'utility'
            ]
    
    @api.onchange('is_aiu_base')
    def _onchange_is_aiu_base(self):
        """Actualizar cálculos AIU cuando cambia la marca de base"""
        if self.move_id and self.move_id.state == 'draft' and self.move_id.is_aiu_invoice_move:
            self.move_id._compute_aiu_amounts()
    
    @api.onchange('product_id')
    def _onchange_product_id_aiu(self):
        """Aplicar impuestos automáticamente para productos AIU y marcar como base si es servicio"""
        if self.product_id and self.move_id and self.move_id.is_aiu_invoice_move:
            if (self.product_id.is_aiu_service and 
                self.product_id.aiu_type == 'service'):
                self.is_aiu_base = True
                
                if (self.move_id.aiu_tax_config_id and 
                    self.move_id.aiu_tax_source == 'from_config'):
                    service_taxes = self.move_id._get_aiu_line_taxes('service')
                    if service_taxes:
                        self.tax_ids = [(Command.set(service_taxes))]
    
    @api.onchange('product_id')
    def _onchange_product_id_aiu_lines(self):
        """Aplicar configuración específica para líneas AIU generadas automáticamente"""
        if (self.product_id and self.product_id.aiu_type in ['administration', 'unforeseen', 'utility'] 
            and self.move_id and self.move_id.is_aiu_invoice_move and self.move_id.aiu_tax_config_id and 
            self.move_id.aiu_tax_source == 'from_config'):
            
            # Aplicar impuestos específicos según el tipo AIU
            aiu_taxes = self.move_id._get_aiu_line_taxes(self.product_id.aiu_type)
            if aiu_taxes:
                self.tax_ids = [(Command.set(aiu_taxes))]
                
            # Marcar como línea AIU
            self.is_aiu_line = True
    
    def write(self, vals):
        """Sobrescribir write en líneas para detectar cambios relevantes"""
        result = super().write(vals)
        
        # Si se modificó is_aiu_base o campos relacionados con servicios AIU
        if 'is_aiu_base' in vals or 'price_unit' in vals or 'quantity' in vals:
            for line in self:
                if (line.move_id and line.move_id.state == 'draft' and 
                    line.move_id.move_type in ['out_invoice', 'out_refund'] and
                    line.move_id.is_aiu_invoice_move and line.product_id.is_aiu_service and 
                    line.product_id.aiu_type == 'service'):
                    
                    line.move_id._compute_aiu_amounts()
                    
                    if line.move_id.show_aiu_in_lines:
                        line.move_id._schedule_aiu_lines_update()
        
        if 'product_id' in vals:
            for line in self:
                if (line.product_id and line.move_id and line.move_id.state == 'draft' and
                    line.move_id.is_aiu_invoice_move and line.move_id.aiu_tax_config_id and 
                    line.move_id.aiu_tax_source == 'from_config'):
                    
                    # Aplicar impuestos según el tipo de producto AIU
                    if line.product_id.is_aiu_service and line.product_id.aiu_type == 'service':
                        line.is_aiu_base = True  # Marcar automáticamente como base
                        service_taxes = line.move_id._get_aiu_line_taxes('service')
                        if service_taxes:
                            line.tax_ids = [(Command.set(service_taxes))]
                    
                    elif line.product_id.aiu_type in ['administration', 'unforeseen', 'utility']:
                        aiu_taxes = line.move_id._get_aiu_line_taxes(line.product_id.aiu_type)
                        if aiu_taxes:
                            line.tax_ids = [(Command.set(aiu_taxes))]
        
        return result
    
    @api.model_create_multi
    def create(self, vals_list):
        """Sobrescribir create para aplicar configuración AIU automáticamente"""
        lines = super().create(vals_list)
        
        for line in lines:
            if (line.move_id and line.move_id.state == 'draft' and 
                line.move_id.is_aiu_invoice_move and line.move_id.aiu_tax_config_id and 
                line.move_id.aiu_tax_source == 'from_config' and line.product_id):
                
                # Aplicar impuestos según el tipo de producto
                taxes_to_apply = None
                
                if line.product_id.is_aiu_service and line.product_id.aiu_type == 'service':
                    line.is_aiu_base = True  # Marcar automáticamente como base
                    taxes_to_apply = line.move_id._get_aiu_line_taxes('service')
                elif line.product_id.aiu_type in ['administration', 'unforeseen', 'utility']:
                    taxes_to_apply = line.move_id._get_aiu_line_taxes(line.product_id.aiu_type)
                
                if taxes_to_apply:
                    line.tax_ids = [(Command.set(taxes_to_apply))]
        
        return lines
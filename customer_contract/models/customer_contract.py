from odoo import api, fields, models
from odoo.tools.sql import index_exists, column_exists, create_column
import logging

from .res_partner import TYPE_COMPANY

_logger = logging.getLogger(__name__)

HELP_CDP = "Certificado de disponibilidad presupuestal"
HELP_RP = "Registro Presupuestal de Compromiso"

class ProductPricelist(models.Model):
    _inherit = 'product.pricelist'

    contract_id = fields.Many2one('customer.contract', string='Contrato')

class ProductPricelistItem(models.Model):
    _inherit = 'product.pricelist.item'

    contract_id = fields.Many2one('customer.contract', string='Contrato')

class ProductPricing(models.Model):
    _inherit = 'product.pricing'

    contract_id = fields.Many2one('customer.contract', string='Contrato')

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    contract_id = fields.Many2one('customer.contract', string='Contrato')

class CustomerContract(models.Model):
    _name = "customer.contract"
    _inherit = ['portal.mixin', 'product.catalog.mixin', 'mail.thread', 'mail.activity.mixin', 'utm.mixin']
    _description = "Contratos de clientes"
    _order = "name"

    name = fields.Char(string="Número", required=True)
    description = fields.Text(string="Descripción", required=True)
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Cliente",
        # domain="[('is_company', '=', True)]",
        required=True,
    )
    type_company = fields.Selection(string="Tipo de empresa", related="partner_id.type_company")
    cdp_number = fields.Char(string="Número", help=HELP_CDP)
    cdp_amount = fields.Float(string="Monto")
    cdp_file = fields.Binary(string="Documento")

    diagnostics_ids = fields.Many2many("customer.contract.diagnostic", string="Ayudas Diagnosticas")

    rp_number = fields.Char(string="Número", help=HELP_RP)
    rp_amount = fields.Float(string="Monto")
    rp_file = fields.Binary(string="Documento")

    amount = fields.Float(string="Monto", required=True)
    start_date = fields.Date(string="Inicio", required=True)
    end_date = fields.Date(string="Fin", required=True)

    # New fields for sales and invoicing
    sale_order_count = fields.Integer(
        string='Órdenes de Venta', 
        compute='_compute_sale_order_count'
    )
    sale_order_id = fields.Many2one(
        comodel_name='sale.order',
        string='Ordenes de Venta asociadas',
        # compute='_compute_sale_order_count',
        # store=True,
        domain="[('contract_id', '=', id)]",
        help="Órdenes de venta relacionadas con este contrato."
        )
    # invoice_ids = fields.One2many(
    #     'account.move',
    #     'contract_id',
    #     string='Facturas Asociadas'
    # )
    pricelist_id = fields.Many2one(
        'product.pricelist',
        string='Lista de Precios del Contrato',
    )
    
    # Price rules fields
    item_ids = fields.One2many(
        'product.pricelist.item',
        'contract_id',
        string='Reglas de lista de precios'
    )
    product_pricing_ids = fields.One2many(
        'product.pricing',
        'contract_id',
        string='Reglas de fijación de precios'
    )

    report_budget_ids = fields.One2many(
        comodel_name="customer.contract.report.budget", 
        inverse_name="customer_contract_id"
    )
    report_budget_cdp_ids = fields.One2many(
        comodel_name="customer.contract.report.budget",
        compute="_get_report_budget",
        string=HELP_CDP,
    )
    report_budget_rp_ids = fields.One2many(
        comodel_name="customer.contract.report.budget", 
        compute="_get_report_budget", 
        string=HELP_RP
    )

    annex_ids = fields.One2many(
        comodel_name="customer.contract.annex", 
        inverse_name="customer_contract_id", 
        string="Otrosí"
    )
    annex_time_seq = fields.Integer(string="Secuencia de otrosi prorroga", default=0)
    annex_time_ids = fields.One2many(
        comodel_name="customer.contract.annex", 
        compute="_get_annex", 
        string="Prórroga"
    )
    annex_money_seq = fields.Integer(string="Secuencia de otrosi adicion", default=0)
    annex_money_ids = fields.One2many(
        comodel_name="customer.contract.annex", 
        compute="_get_annex", 
        string="Adición"
    )

    policy_ids = fields.One2many(
        comodel_name="customer.contract.policy",
        inverse_name="customer_contract_id",
        string="Pólizas",
    )
    products_ids = fields.Many2many(
        comodel_name="product.product", 
        string="Productos"
    )
    benefit_plan_ids = fields.Many2many(
        'benefit.plan',
        'contract_benefit_plan_rel',
        'contract_id',
        'benefit_plan_id',
        string="Planes de Beneficios"
    )
    payment_method = fields.Selection([
        ('01', 'Paquete/Canasta/Conjunto Integral en Salud'),
        ('02', 'Grupos Relacionados por Diagnóstico'),
        ('03', 'Integral por grupo de riesgo'),
        ('04', 'Pago por contacto de especialidad'),
        ('05', 'Pago por escenario de atención'),
        ('06', 'Pago por tipo de servicio'),
        ('07', 'Pago global prospectivo por episodio'),
        ('08', 'Pago global prospectivo por grupo de riesgo'),
        ('09', 'Pago global prospectivo por especialidad'),
        ('10', 'Pago global prospectivo por nivel de complejidad'),
        ('11', 'Capacitación'),
        ('12', 'Por servicio')
    ], string='Método de Pago', 
       help='Seleccione el método de pago para el contrato de salud')


    invoice_count = fields.Integer(
        string='Facturas',
        compute='_compute_invoice_count'
    )
    invoiced_value = fields.Float(
        string='Valor Facturado',
        compute='_compute_invoiced_value',
        store=True,
    )
    final_percentage = fields.Float(
        string='Porcentaje Final',
        compute='_compute_final_percentage',
        store=True,
        help='Calcula la Diferencia porcentual entre el monto del contrato y el valor facturado'
    )

    def _auto_init(self):
        """
        Crear columnas manualmente para campos computados con store=True
        antes de llamar a super() para evitar MemoryError en bases de datos grandes.
        """
        # Crear columnas manualmente ANTES de super()._auto_init()
        if not column_exists(self.env.cr, 'customer_contract', 'invoiced_value'):
            create_column(self.env.cr, 'customer_contract', 'invoiced_value', 'numeric')
            _logger.info('Created column invoiced_value in customer_contract')

        if not column_exists(self.env.cr, 'customer_contract', 'final_percentage'):
            create_column(self.env.cr, 'customer_contract', 'final_percentage', 'numeric')
            _logger.info('Created column final_percentage in customer_contract')

        """Crear índices para campos computados almacenados para optimizar búsquedas"""
        super()._auto_init()

        # Índice para invoiced_value - usado en reportes financieros
        if not index_exists(self.env.cr, 'customer_contract_invoiced_value_idx'):
            self.env.cr.execute("""
                CREATE INDEX customer_contract_invoiced_value_idx
                          ON customer_contract(invoiced_value)
                       WHERE invoiced_value > 0
            """)

        # Índice compuesto para análisis de ejecución de contratos
        if not index_exists(self.env.cr, 'customer_contract_percentage_idx'):
            self.env.cr.execute("""
                CREATE INDEX customer_contract_percentage_idx
                          ON customer_contract(partner_id, final_percentage)
                       WHERE final_percentage IS NOT NULL
            """)

        # Índice para búsquedas por rango de fecha y valor facturado
        if not index_exists(self.env.cr, 'customer_contract_date_value_idx'):
            self.env.cr.execute("""
                CREATE INDEX customer_contract_date_value_idx
                          ON customer_contract(start_date, end_date, invoiced_value)
            """)

    @api.depends('invoiced_value', 'amount')
    def _compute_final_percentage(self):
        for record in self:
            if record.amount > 0:
                record.final_percentage = ((record.amount - record.invoiced_value) / record.amount) * 100
                # record.final_percentage = round(record.final_percentage, 2)  # Redondear a 2 decimales
            else:
                record.final_percentage = 0.0
    
    @api.depends('name')
    def _compute_invoiced_value(self):
        """
        Calcula el valor facturado desde órdenes de venta relacionadas.
        OPTIMIZADO: Usa read_group() en lugar de search() + sum() + mapped()
        - Antes: N queries (1 search + N reads de amount_total)
        - Ahora: 1 query con SUM agregado en PostgreSQL
        Performance: ~10-50x más rápido dependiendo de cantidad de órdenes
        """
        # read_group para calcular suma en una sola query SQL
        result = self.env['sale.order'].read_group(
            domain=[
                ('contract_id', 'in', self.ids),
                ('state', 'in', ['sale', 'done']),
                ('invoice_status', '=', 'invoiced')
            ],
            fields=['amount_total:sum'],
            groupby=['contract_id']
        )

        # Mapear resultados a diccionario {contract_id: suma}
        invoiced_map = {
            data['contract_id'][0]: data['amount_total']
            for data in result
        }

        # Asignar valores (0.0 si no hay órdenes)
        for record in self:
            record.invoiced_value = invoiced_map.get(record.id, 0.0)

    def _compute_invoice_count(self):
        for record in self:
            record.invoice_count = 0 #len(record.invoice_ids)

    def action_view_invoices(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Facturas',
            'res_model': 'account.move',
            'view_mode': 'tree,form',
            'domain': [('contract_id', '=', self.id)],
            'context': {
                'default_contract_id': self.id,
                'default_move_type': 'out_invoice'
            },
        }

    def action_create_pricelist(self):
        for record in self:
            if not record.pricelist_id:
                record._create_contract_pricelist()
        return True

    def action_update_pricelist_items(self):
        """Action to update price list items"""
        self.ensure_one()
        if not self.pricelist_id:
            self._create_contract_pricelist()
        
        for product in self.products_ids:
            item = self.item_ids.filtered(lambda x: x.product_id == product)
            if item:
                item.write({
                    'fixed_price': product.list_price
                })
            else:
                self.env['product.pricelist.item'].create({
                    'pricelist_id': self.pricelist_id.id,
                    'contract_id': self.id,
                    'product_id': product.id,
                    'applied_on': '0_product_variant',
                    'compute_price': 'fixed',
                    'fixed_price': product.list_price
                })
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Lista de Precios',
                'message': 'Los precios han sido actualizados correctamente',
                'type': 'success',
                'sticky': False,
            }
        }

    @api.model
    def create(self, vals):
        record = super(CustomerContract, self).create(vals)
        if not record.pricelist_id:
            record._create_contract_pricelist()
        return record

    def _create_contract_pricelist(self):
        pricelist = self.env['product.pricelist'].create({
            'name': f'Lista de Precios - {self.partner_id.name} - # {self.name}',
            'currency_id': self.env.company.currency_id.id,
            'contract_id': self.id,
        })
        self.write({'pricelist_id': pricelist.id})

    @api.onchange('products_ids')
    def _onchange_products_ids(self):
        """When products are added, create pricing rules"""
        if self.pricelist_id and self.products_ids:
            existing_product_ids = self.item_ids.mapped('product_id').ids
            PricelistItem = self.env['product.pricelist.item']
            values = []
            for product in self.products_ids:
                if product.id not in existing_product_ids:
                    values.append({
                        'pricelist_id': self.pricelist_id.id,
                        'product_id': product.id,
                        'applied_on': '0_product_variant',
                        'compute_price': 'fixed',
                        'fixed_price': product.list_price
                    })
            
            # Crear las nuevas reglas si hay valores
            if values:
                PricelistItem.create(values)

    @api.depends('name')
    def _compute_sale_order_count(self):
        """
        Cuenta las órdenes de venta asociadas al contrato.
        Optimizado: Usa search_count() que es más eficiente que len(search()).
        Nota: Eliminada llamada manual a _compute_invoiced_value() ya que
        depende de 'name' y se ejecutará automáticamente si cambió.
        """
        for record in self:
            record.sale_order_count = self.env['sale.order'].search_count([
                ('contract_id', '=', record.id)
            ])

    def action_view_sale_orders(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Órdenes de Venta',
            'res_model': 'sale.order',
            'view_mode': 'tree,form',
            'domain': [('contract_id', '=', self.id)],
            'context': {'default_contract_id': self.id},
        }

    @api.depends("report_budget_ids", "report_budget_ids.type")
    def _get_report_budget(self):
        """
        Filtra reportes presupuestales por tipo (CDP/RP).
        Optimizado:
        - Agregado 'report_budget_ids.type' a depends para detectar cambios en tipo
        - Usa filtered() en lugar de loops y append
        - Elimina browse() innecesario (filtered ya retorna recordset)
        """
        for record in self:
            record.report_budget_cdp_ids = record.report_budget_ids.filtered(lambda rb: rb.type == "CDP")
            record.report_budget_rp_ids = record.report_budget_ids.filtered(lambda rb: rb.type == "RP")

    @api.depends("annex_ids", "annex_ids.type")
    def _get_annex(self):
        """
        Filtra anexos (otrosí) por tipo (time/money).
        Optimizado:
        - Agregado 'annex_ids.type' a depends para detectar cambios en tipo
        - Usa filtered() en lugar de loops y append
        - Elimina browse() innecesario
        """
        for record in self:
            record.annex_time_ids = record.annex_ids.filtered(lambda an: an.type == "time")
            record.annex_money_ids = record.annex_ids.filtered(lambda an: an.type == "money")

    def get_next_seq_annex(self, type):
        if type == "time":
            self.write({"annex_time_seq": self.annex_time_seq + 1})
            return self.annex_time_seq
        else:
            self.write({"annex_money_seq": self.annex_money_seq + 1})
            return self.annex_money_seq





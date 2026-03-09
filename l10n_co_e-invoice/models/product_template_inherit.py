from odoo import fields, models,api
from odoo.exceptions import UserError, ValidationError

class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    type = fields.Selection(
        selection_add=[("out_invoice", "Out Invoice"), ("out_refund", "Out Refund")],
        ondelete={"out_invoice": "set default", "out_refund": "set default"},
    )

class ProductUom(models.Model):
    _inherit = 'uom.uom'

    dian_country_code = fields.Char(
        'Country code',
        default=lambda self: self.env.company.country_id.code
    )
    dian_uom_id = fields.Many2one(
        'dian.uom.code', 'DIAN UoM'
    )



class ProductTemplate(models.Model):
    _inherit = "product.template"
    
    # ========== CAMPOS BÁSICOS DIAN ==========
    line_price_reference = fields.Float(
        string='Precio de referencia',
        help='Precio de referencia para cálculos DIAN'
    )
    
    operation_type = fields.Selection([
        ("09", "Servicios AIU"),
        ("10", "Estandar"),
        ("11", "Mandatos bienes")
    ], string="Tipo de operación DIAN", default="10")
    
    # ========== CLASIFICACIÓN UNSPSC ==========
    product_UNSPSC_id = fields.Many2one(
        "dian.unspsc.product",
        string="Producto UNSPSC",
        help="Clasificación de producto según estándar UNSPSC"
    )
    
    segment_name = fields.Char(
        string="Segmento UNSPSC",
        readonly=True,
        related="product_UNSPSC_id.segment_id.name",
        store=True
    )
    
    family_name = fields.Char(
        string="Familia UNSPSC",
        readonly=True,
        related="product_UNSPSC_id.family_id.name",
        store=True
    )
    
    class_name = fields.Char(
        string="Clase UNSPSC",
        readonly=True,
        related="product_UNSPSC_id.class_id.name",
        store=True
    )
    
    # ========== MARCA Y MODELO ==========
    brand_id = fields.Many2one(
        "product.brand",
        string="Marca",
        help="Marca del producto"
    )
    
    model_id = fields.Many2one(
        "product.model",
        string="Modelo",
        help="Modelo del producto"
    )
    
    # ========== CARGOS E IMPUESTOS ADICIONALES ==========
    enable_charges = fields.Boolean(
        string='Cargo de Factura Electrónica',
        help='Habilitar cargos adicionales en factura electrónica'
    )
    
    ref_nominal_tax = fields.Float(
        string='Referencia de Impuesto Nominal',
        help='Valor de referencia para impuesto nominal'
    )
    
    # ========== IMPUESTOS SALUDABLES - RESUMEN ==========
    has_health_taxes = fields.Boolean(
        string='Tiene Impuestos Saludables',
        compute='_compute_has_health_taxes',
        store=True,
        help='Indica si el producto tiene algún impuesto saludable aplicable'
    )
    
    # ========== ICL - IMPUESTO AL CONSUMO DE LICORES ==========
    has_icl = fields.Boolean(
        string='Aplica ICL',
        help='Impuesto al consumo de licores, vinos y aperitivos'
    )
    
    product_type = fields.Selection([
        ('liquor', 'Licor/Aperitivo'),
        ('wine', 'Vino/Aperitivo de vino')
    ], string='Tipo de bebida alcohólica')
    
    alcohol_degree = fields.Float(
        string='Grados de alcohol',
        help='Contenido alcohólico en grados (ej: 40 para 40°)',
        digits=(5, 2)
    )
    
    volume_ml = fields.Float(
        string='Volumen (ml)',
        default=750,
        help='Volumen del envase en mililitros',
        digits=(10, 2)
    )
    
    # ========== ICUI - ALIMENTOS ULTRAPROCESADOS ==========
    has_icui = fields.Boolean(
        string='Aplica ICUI',
        help='Impuesto a productos comestibles ultraprocesados (20%)'
    )
    
    # ========== IBUA - BEBIDAS AZUCARADAS ==========
    has_ibua = fields.Boolean(
        string='Aplica IBUA',
        help='Impuesto a bebidas ultraprocesadas azucaradas'
    )
    
    ml_ibua = fields.Float(
        string='Mililitros IBUA',
        help='Volumen en mililitros de la bebida',
        digits=(10, 2)
    )
    
    grams_ibua = fields.Float(
        string='Gramos azúcar por 100ml',
        help='Gramos de azúcar por cada 100ml',
        digits=(5, 2)
    )
    
    # ========== INPP - PRODUCTOS PLÁSTICOS ==========
    has_inpp = fields.Boolean(
        string='Aplica INPP',
        help='Impuesto nacional productos plásticos de un solo uso'
    )
    
    grams_inpp = fields.Float(
        string='Gramos empaque plástico',
        help='Peso en gramos del empaque plástico',
        digits=(10, 2)
    )
    
    # ========== INFORMACIÓN ARANCELARIA ==========
    hs_code = fields.Char(
        string='Partida Arancelaria',
        size=12,
        help='Código arancelario del producto (10 dígitos)'
    )
    
    tariff_rate = fields.Float(
        string='Tasa Arancelaria (%)',
        help='Porcentaje de arancel aplicable',
        digits=(5, 2)
    )
    
    # ========== MÉTODOS COMPUTADOS ==========
    
    @api.depends('has_icl', 'has_icui', 'has_ibua', 'has_inpp')
    def _compute_has_health_taxes(self):
        """Calcula si el producto tiene algún impuesto saludable"""
        for record in self:
            record.has_health_taxes = any([
                record.has_icl,
                record.has_icui,
                record.has_ibua,
                record.has_inpp
            ])
    
    # ========== MÉTODOS ONCHANGE ==========
    
    @api.onchange('enable_charges')
    def _onchange_enable_charges(self):
        """Limpia el valor de referencia si se deshabilitan los cargos"""
        if not self.enable_charges:
            self.ref_nominal_tax = 0.0
    
    @api.onchange('has_icl')
    def _onchange_has_icl(self):
        """Limpia los campos ICL si se desmarca"""
        if not self.has_icl:
            self.product_type = False
            self.alcohol_degree = 0.0
            self.volume_ml = 750.0
    
    @api.onchange('product_type')
    def _onchange_product_type(self):
        """Marca automáticamente has_icl si se selecciona un tipo de bebida"""
        if self.product_type and not self.has_icl:
            self.has_icl = True
    
    @api.onchange('alcohol_degree')
    def _onchange_alcohol_degree(self):
        """Marca automáticamente has_icl si se ingresa grado alcohólico"""
        if self.alcohol_degree > 0 and not self.has_icl:
            self.has_icl = True
    
    @api.onchange('has_ibua')
    def _onchange_has_ibua(self):
        """Limpia los campos IBUA si se desmarca"""
        if not self.has_ibua:
            self.ml_ibua = 0.0
            self.grams_ibua = 0.0
    
    @api.onchange('ml_ibua', 'grams_ibua')
    def _onchange_ibua_values(self):
        """Marca automáticamente has_ibua si se ingresan valores"""
        if (self.ml_ibua > 0 or self.grams_ibua > 0) and not self.has_ibua:
            self.has_ibua = True
    
    @api.onchange('has_inpp')
    def _onchange_has_inpp(self):
        """Limpia los campos INPP si se desmarca"""
        if not self.has_inpp:
            self.grams_inpp = 0.0
    
    @api.onchange('grams_inpp')
    def _onchange_grams_inpp(self):
        """Marca automáticamente has_inpp si se ingresan gramos"""
        if self.grams_inpp > 0 and not self.has_inpp:
            self.has_inpp = True
    
    @api.onchange('hs_code')
    def _onchange_hs_code(self):
        """Verifica automáticamente si aplica ICUI según partida arancelaria"""
        if self.hs_code and len(self.hs_code) >= 4:
            # Partidas que comúnmente aplican ICUI
            icui_chapters = ['1704', '1905', '2005', '2103', '2104', '2106']
            if self.hs_code[:4] in icui_chapters and not self.has_icui:
                self.has_icui = True
    
    # ========== VALIDACIONES ==========
    
    @api.constrains('alcohol_degree')
    def _check_alcohol_degree(self):
        """Valida que los grados de alcohol estén en rango válido"""
        for record in self:
            if record.alcohol_degree < 0:
                raise ValidationError("Los grados de alcohol no pueden ser negativos")
            if record.alcohol_degree > 100:
                raise ValidationError("Los grados de alcohol no pueden ser mayores a 100")
    
    @api.constrains('grams_ibua')
    def _check_grams_ibua(self):
        """Valida que los gramos de azúcar sean válidos"""
        for record in self:
            if record.grams_ibua < 0:
                raise ValidationError("Los gramos de azúcar no pueden ser negativos")
    
    @api.constrains('tariff_rate')
    def _check_tariff_rate(self):
        """Valida que la tasa arancelaria esté en rango válido"""
        for record in self:
            if record.tariff_rate < 0:
                raise ValidationError("La tasa arancelaria no puede ser negativa")
            if record.tariff_rate > 100:
                raise ValidationError("La tasa arancelaria no puede ser mayor a 100%")

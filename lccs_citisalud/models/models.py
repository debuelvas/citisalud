# -*- coding: utf-8 -*-

from odoo import models, fields, api
from datetime import datetime


class ProductTemplate(models.Model):
    """
    Extensión del modelo product.template con funcionalidades unificadas:
    - Campos INVIMA
    - Gestión de cuentas por categoría específica
    """
    _inherit = 'product.template'

    # ========== CAMPOS INVIMA ==========
    invima_register = fields.Char(
        string='Registro Invima',
        help="Número de registro del producto ante el INVIMA"
    )
    
    is_invima = fields.Boolean(
        string='Es Invima',
        default=False,
        help="Indica si el producto requiere registro INVIMA"
    )
    
    temperature_invima = fields.Char(
        string='Temperatura',
        help="Condiciones de temperatura requeridas para el producto"
    )
    
    city_salud_ext = fields.Char(
        string='Referencia CitiSalud Externa',
        help="Referencia externa del producto en el sistema CitiSalud"
    )
    
    cups_reference = fields.Char(
        string='Referencia CUPS',
        help="Código CUPS (Clasificación Única de Procedimientos en Salud) del producto"
    )

    # ========== CAMPO DE PRUEBA ==========
    test_field = fields.Boolean(
        string='Campo de Prueba',
        help="Campo de prueba para funcionalidades adicionales"
    )

    def _get_product_accounts(self):
        """
        Sobrescribe el método para usar las cuentas específicas de la categoría
        de la variante cuando está disponible.
        """
        result = super()._get_product_accounts()
        product_id = self.env.context.get('product_id')
        
        if product_id and hasattr(product_id, 'specific_categ_id'):
            # Actualiza la cuenta de ingresos
            if 'income' in result and product_id.specific_categ_id:
                income_account = (
                    product_id.specific_categ_id.property_account_income_categ_id or
                    self.property_account_income_id or
                    self.categ_id.property_account_income_categ_id
                )
                if income_account:
                    result['income'] = income_account
            
            # Actualiza la cuenta de gastos
            if 'expense' in result and product_id.specific_categ_id:
                expense_account = (
                    product_id.specific_categ_id.property_account_expense_categ_id or
                    self.property_account_expense_id or
                    self.categ_id.property_account_expense_categ_id
                )
                if expense_account:
                    result['expense'] = expense_account
        
        return result


class ProductProduct(models.Model):
    """
    Extensión del modelo product.product para categorías específicas por variante.
    """
    _inherit = 'product.product'

    categ_id = fields.Many2one(
        'product.category',
        string='Categoría de Producto',
        compute='_compute_categ_id',
        inverse='_inverse_categ_id',
        store=True,
        readonly=False,
        help="Categoría del producto. Si se especifica una categoría específica, "
             "esta tendrá prioridad sobre la categoría del template."
    )

    specific_categ_id = fields.Many2one(
        'product.category',
        string='Categoría Específica',
        help="Categoría específica para esta variante de producto. "
             "Si no se especifica, se usará la categoría del template."
    )

    @api.depends('specific_categ_id', 'product_tmpl_id.categ_id')
    def _compute_categ_id(self):
        """
        Calcula la categoría del producto basada en la categoría específica
        o la categoría del template.
        """
        for product in self:
            if product.specific_categ_id:
                product.categ_id = product.specific_categ_id
            else:
                product.categ_id = product.product_tmpl_id.categ_id

    def _inverse_categ_id(self):
        """
        Actualiza la categoría específica cuando se cambia la categoría del producto.
        """
        for product in self:
            if product.categ_id != product.product_tmpl_id.categ_id:
                product.specific_categ_id = product.categ_id
            else:
                product.specific_categ_id = False


class StockProductionLot(models.Model):
    """
    Extensión del modelo stock.lot para semaforización de caducidad.
    """
    _inherit = 'stock.lot'

    expiration_days = fields.Integer(
        string='Días para caducar',
        compute='_compute_expiration_days',
        help="Número de días restantes hasta la fecha de caducidad"
    )
    
    color_expiration = fields.Selection(
        selection=[
            ('red', 'Rojo'),
            ('yellow', 'Amarillo'),
            ('green', 'Verde')
        ],
        string='Color de Semaforización',
        compute='_compute_expiration_color',
        store=True,
        help="Color que indica el estado de caducidad del lote"
    )

    @api.depends('expiration_date')
    def _compute_expiration_days(self):
        """Calcula los días restantes hasta la fecha de caducidad."""
        for record in self:
            if record.expiration_date:
                delta = record.expiration_date - datetime.now()
                record.expiration_days = max(0, delta.days)
            else:
                record.expiration_days = 0

    @api.depends('expiration_days')
    def _compute_expiration_color(self):
        """Calcula el color de semaforización basado en los días restantes."""
        for record in self:
            if record.expiration_days < 181:
                record.color_expiration = 'red'
            elif 181 <= record.expiration_days < 365:
                record.color_expiration = 'yellow'
            else:
                record.color_expiration = 'green'


#class AccountMoveLine(models.Model):
    # """
    # Extensión del modelo account.move.line para usar cuentas específicas por categoría.
    # """
    # _inherit = 'account.move.line'

    # def _get_computed_account(self):
    #     """
    #     Sobrescribe el método para usar las cuentas específicas de la categoría
    #     del producto cuando está disponible.
    #     """
    #     result = super()._get_computed_account()
        
    #     if not self.product_id:
    #         return result
            
    #     fiscal_position = self.move_id.fiscal_position_id
        
    #     # Facturas de venta
    #     if self.move_id.is_sale_document(include_receipts=True):
    #         accounts = self.product_id.product_tmpl_id.with_context(
    #             product_id=self.product_id
    #         ).get_product_accounts(fiscal_pos=fiscal_position)
    #         result = accounts.get('income') or result
            
    #     # Facturas de compra
    #     elif self.move_id.is_purchase_document(include_receipts=True):
    #         accounts = self.product_id.product_tmpl_id.with_context(
    #             product_id=self.product_id
    #         ).get_product_accounts(fiscal_pos=fiscal_position)
    #         result = accounts.get('expense') or result
            
    #     return result


# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools.safe_eval import safe_eval

TRIBUTES = [
    ('01', 'IVA'), 
    ('02', 'IC'), 
    ('03', 'ICA'), 
    ('04', 'INC'), 
    ('05', 'ReteIVA'), 
    ('06', 'ReteFuente'),
    ('07', 'ReteICA'), 
    ('08', 'IC Porcentual'),
    ('20', 'FtoHorticultura'), 
    ('21', 'Timbre'),
    ('22', 'Bolsas'), 
    ('23', 'INCarbono'), 
    ('24', 'INCombustibles'),
    ('25', 'Sobretasa Combustibles'), 
    ('26', 'Sordicom'),
    ('30', 'IC Datos'),
    ('32', 'ICL'),
    ('33', 'INPP'),  
    ('34', 'IBUA'), 
    ('35', 'ICUI'), 
    ('36', 'ADV'),
    ('ZY', 'No causa'),
    ('ZZ', 'Nombre de la figura tributaria')
]

TAX_GROUP = [('iva_fe','IVA FE'), 
                ('ica_fe','ICA FE'), 
                ('ico_fe','INC FE'), 
                ('ret_fe','RET FE'), 
                ('nap_fe','No aplica a DIAN FE')]


class AccountTaxInherit(models.Model):
    _inherit = 'account.tax'


    tax_group_fe = fields.Selection(TAX_GROUP, string="Grupo de impuesto DIAN FE", default='nap_fe')

    # Campos DIAN existentes
    tributes = fields.Selection(TRIBUTES, string="Tributo DIAN")
    codigo_dian = fields.Char(string='Código DIAN', compute='_compute_dian_details', store=True)
    nombre_dian = fields.Char(string='Nombre técnico DIAN', compute='_compute_dian_details', store=True)
    description_dian = fields.Char(string='Descripción DIAN', compute='_compute_dian_details', store=True)
    
    # Campos para Python Code (ya existentes)
    amount_type = fields.Selection(selection_add=[
        ('code', 'Python Code')
    ], ondelete={'code': lambda recs: recs.write({'amount_type': 'percent', 'active': False})})
    
    python_compute = fields.Text(
        string='Python Code', 
        default="result = price_unit * 0.10",
        help="Compute the amount of the tax by setting the variable 'result'.\n\n"
             ":param base_amount: float, actual amount on which the tax is applied\n"
             ":param price_unit: float\n"
             ":param quantity: float\n"
             ":param company: res.company recordset singleton\n"
             ":param product: product.product recordset singleton or None\n"
             ":param partner: res.partner recordset singleton or None"
    )
    
    python_applicable = fields.Text(
        string='Applicable Code', 
        default="result = True",
        help="Determine if the tax will be applied by setting the variable 'result' to True or False.\n\n"
             ":param price_unit: float\n"
             ":param quantity: float\n"
             ":param company: res.company recordset singleton\n"
             ":param product: product.product recordset singleton or None\n"
             ":param partner: res.partner recordset singleton or None"
    )

    @api.depends('tributes')
    def _compute_dian_details(self):
        """Calcula los detalles DIAN según el código del tributo"""
        tax_details = {
            '01': ('IVA', 'Impuesto de Valor Agregado'),
            '02': ('IC', 'Impuesto al Consumo'),
            '03': ('ICA', 'Impuesto de Industria, Comercio y Aviso'),
            '04': ('INC', 'Impuesto Nacional al Consumo'),
            '05': ('ReteIVA', 'Retención sobre el IVA'),
            '06': ('ReteRenta', 'Retención sobre Renta'),
            '07': ('ReteICA', 'Retención sobre el ICA'),
            '08': ('IC Porcentual', 'Impuesto al Consumo Departamental Porcentual'),
            '20': ('FtoHorticultura', 'Cuota de Fomento Hortifrutícula'),
            '21': ('Timbre', 'Impuesto de Timbre'),
            '22': ('INC Bolsas', 'Impuesto al Consumo de Bolsa Plástica'),
            '23': ('INCarbono', 'Impuesto Nacional al Carbono'),
            '24': ('INCombustibles', 'Impuesto Nacional a los Combustibles'),
            '25': ('Sobretasa Combustibles', 'Sobretasa a los combustibles'),
            '26': ('Sordicom', 'Contribución minoristas (Combustibles)'),
            '30': ('IC Datos', 'Impuesto al Consumo de Datos'),
            '32': ('ICL', 'Impuesto al Consumo de Licores'),
            '33': ('INPP', 'Impuesto Nacional de Productos Plásticos'),
            '34': ('IBUA', 'Impuesto a las Bebidas Ultraprocesadas Azucaradas'),
            '35': ('ICUI', 'Impuesto a los Productos Comestibles Ultraprocesados'),
            '36': ('ADV', 'AD VALOREM'),
            'ZZ': ('Nombre de la figura tributaria', 'Otros Tributos, tasas, contribuciones, y similares'),
        }
        
        for rec in self:
            if rec.tributes in tax_details:
                rec.codigo_dian = rec.tributes
                rec.nombre_dian = tax_details[rec.tributes][0]
                rec.description_dian = tax_details[rec.tributes][1]
            else:
                rec.codigo_dian = rec.tributes or ''
                rec.nombre_dian = ''
                rec.description_dian = ''

    # def _compute_amount(self, base_amount, price_unit, quantity=1.0, product=None, partner=None, fixed_multiplicator=1):
    #     """Sobrescribe para manejar cálculo con Python code"""
    #     self.ensure_one()
        
    #     if product and product._name == 'product.template':
    #         product = product.product_variant_id
            
    #     if self.amount_type == 'code':
    #         company = self.env.company
            
    #         if self.codigo_dian == '34':  
    #             if product and product.ml_ibua and product.grams_ibua:
    #                 ml = product.ml_ibua or 0
    #                 grams = product.grams_ibua or 0
                    
    #                 year = fields.Date.today().year
    #                 tariff = 0
                    
    #                 if year == 2023:
    #                     if 6 <= grams < 10:
    #                         tariff = 18
    #                     elif grams >= 10:
    #                         tariff = 35
    #                 elif year == 2024:
    #                     if 6 <= grams < 10:
    #                         tariff = 28
    #                     elif grams >= 10:
    #                         tariff = 55
    #                 else:  
    #                     if 5 <= grams < 9:
    #                         tariff = 38
    #                     elif grams >= 9:
    #                         tariff = 65
                    
    #                 result = (ml / 100) * tariff * quantity
    #                 return result
                    
    #         elif self.codigo_dian == '33': 
    #             if product and product.grams_inpp:
    #                 grams = product.grams_inpp or 0
    #                 uvt_value = 49799
    #                 result = grams * 0.00005 * uvt_value * quantity
    #                 return result
            
    #         # Cálculo genérico con Python code
    #         product_sudo = product and product.sudo()
    #         localdict = {
    #             'base_amount': base_amount, 
    #             'price_unit': price_unit, 
    #             'quantity': quantity, 
    #             'product': product_sudo, 
    #             'partner': partner, 
    #             'company': company
    #         }
            
    #         try:
    #             safe_eval(self.python_compute, localdict, mode="exec", nocopy=True)
    #         except Exception as e:
    #             raise UserError(_("Error en código Python del impuesto %s: %s") % (self.name, str(e)))
                
    #         return localdict.get('result', 0.0)
            
    #     return super()._compute_amount(base_amount, price_unit, quantity, product, partner, fixed_multiplicator)

    # def compute_all(self, price_unit, currency=None, quantity=1.0, product=None, partner=None, is_refund=False, 
    #                 handle_price_include=True, include_caba_tags=False, fixed_multiplicator=1):
    #     """Sobrescribe para manejar aplicabilidad con Python code"""
    #     if product and product._name == 'product.template':
    #         product = product.product_variant_id
            
    #     def is_applicable_tax(tax, company=self.env.company):
    #         if tax.amount_type == 'code':
    #             if tax.codigo_dian == '34':  
    #                 if not product or not product.has_ibua:
    #                     return False
    #             elif tax.codigo_dian == '35':  
    #                 if not product or not product.has_icui:
    #                     return False
    #             elif tax.codigo_dian == '33': 
    #                 if not product or not product.has_inpp:
    #                     return False
                

    #             product_sudo = product and product.sudo()
    #             localdict = {
    #                 'price_unit': price_unit, 
    #                 'quantity': quantity, 
    #                 'product': product_sudo, 
    #                 'partner': partner, 
    #                 'company': company
    #             }
                
    #             try:
    #                 safe_eval(tax.python_applicable, localdict, mode="exec", nocopy=True)
    #             except Exception as e:
    #                 raise UserError(_("Error en código de aplicabilidad del impuesto %s: %s") % (tax.name, str(e)))
                    
    #             return localdict.get('result', False)
                
    #         return True
            
    #     return super(AccountTax, self.filtered(is_applicable_tax)).compute_all(
    #         price_unit, currency, quantity, product, partner, 
    #         is_refund=is_refund, 
    #         handle_price_include=handle_price_include, 
    #         include_caba_tags=include_caba_tags, 
    #         fixed_multiplicator=fixed_multiplicator
    #     )
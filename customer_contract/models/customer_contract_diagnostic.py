from odoo import api, fields, models
import random

def _get_random_color():
    r = random.randint(150, 240)
    g = random.randint(150, 240)
    b = random.randint(150, 240)
    return '#{:02x}{:02x}{:02x}'.format(r, g, b)

class BenefitPlan(models.Model):
    _name = "benefit.plan"
    _description = "Planes de Beneficios"
    _rec_names_search = ['name', 'code']

    active = fields.Boolean("Activo", default=True)
    name = fields.Char("Nombre", required=True)
    code = fields.Char("Código", required=True)
    color = fields.Char("Color", default=_get_random_color())

    @api.depends('name', 'code')
    def _compute_display_name(self):
        for template in self:
            template.display_name = False if not template.name else (
                '{}{}'.format(
                    template.code and '[%s] ' % template.code or '', template.name
                ))
            
class CustomerContractDiagnostic(models.Model):
    _name = "customer.contract.diagnostic"
    _description = "Ayudas diagnosticas"
    _rec_names_search = ['name', 'code']

    active = fields.Boolean("Activo", default=True)
    name = fields.Char("Nombre", required=True)
    code = fields.Char("Codigo", required=True)

    @api.depends('name', 'code')
    def _compute_display_name(self):
        for template in self:
            template.display_name = False if not template.name else (
                '{}{}'.format(
                    template.code and '[%s] ' % template.code or '', template.name
                ))
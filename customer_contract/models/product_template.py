from datetime import datetime

from odoo import api, fields, models
class MedicalCups(models.Model):
    _name = 'medical.cups'
    _description = 'Códigos CUPS'
    _rec_name = 'display_name'
    category = fields.Selection([
        ('diagnostic', 'Diagnóstico'),
        ('therapeutic', 'Terapéutico'),
        ('surgical', 'Quirúrgico'),
        ('laboratory', 'Laboratorio'),
        ('imaging', 'Imagenología'),
        ('other', 'Otros')
    ], string='Categoría', required=True, default='other')
    active = fields.Boolean('Activo', default=True)
    code = fields.Char('Código CUPS', required=True)
    name = fields.Char('Descripción', required=True)
    # display_name = fields.Char(
    #     'Nombre a Mostrar', 
    #     compute='_compute_display_name', 
    #     store=True
    # )

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for record in self:
            record.display_name = f'[{record.code}] {record.name}'

    _sql_constraints = [
        ('unique_cups_code', 
         'unique(code)',
         'El código CUPS debe ser único!')
    ]

class ProductTemplate(models.Model):
    _inherit = "product.template"

    is_cums = fields.Boolean(string="Es CUMS")
    atc = fields.Char(string="ATC")
    expedient = fields.Char(string="Expediente")
    consecutive = fields.Char(string="Consecutivo")
    code_type = fields.Selection([
        ('cups', 'Código CUPS'),
        ('custom', 'Código Propio')
    ], string='Tipo de Código', required=True, default='custom')
    cups_id = fields.Many2one(
        'medical.cups',
        string='Código CUPS',
        domain="[('active', '=', True)]"
    )
    custom_code = fields.Char(
        string='Código Personalizado'
    )

    @api.onchange('code_type')
    def _onchange_code_type(self):
        """Limpiar campos cuando cambia el tipo de código"""
        if self.code_type == 'cups':
            self.custom_code = False
        else:
            self.cups_id = False


    @api.onchange("atc", "expedient", "consecutive", "is_cums")
    def _onchange_name_cums(self):
        for record in self:
            if not record.is_cums:
                continue
            record.name = ""
            for i, field in enumerate(["atc", "expedient", "consecutive"]):
                value = getattr(record, field)
                record.name += "-" if i == 2 and value else ""
                record.name += value if value else ""

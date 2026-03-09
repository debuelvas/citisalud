# Part of Odoo. See LICENSE file for full copyright and licensing details.
from odoo import api, fields, models, _, tools
from odoo.exceptions import UserError, ValidationError
class HrAccruedRule(models.Model):
    _name = "hr.accrued.rule"
    _description = "Accrued Rule"
    _parent_name = "parent_id"
    _parent_store = True
    _rec_name = 'complete_name'
    _order = 'complete_name'

    name = fields.Char(required=True, string='Nombre')
    code = fields.Char(required=True, string='Código')
    sub_element = fields.Boolean(string='Sub Elemento')
    sequence = fields.Integer(
        string='Sequence',
        required=True
    )
    is_rate = fields.Boolean(string='Tiene Porcentaje')
    is_note = fields.Boolean(string='Tiene Detalles')
    is_total = fields.Boolean(string='Tiene Total')
    is_multi_rule = fields.Boolean(string='Tiene Varias Reglas')
    is_multi_nodo = fields.Boolean(string='Tiene Varios Nodo')
    is_nodo_text = fields.Boolean(string='Tiene text Nodo')
    is_nodo_principal = fields.Boolean(string='es el Nodo Principal')
    complete_name = fields.Char(
        'Complete Name', compute='_compute_complete_name', recursive=True,
        store=True)
    parent_id = fields.Many2one('hr.accrued.rule', 'Categoría principal', index=True, ondelete='cascade')
    parent_path = fields.Char(index=True)
    child_id = fields.One2many('product.category', 'parent_id', 'Child Categories')
    @api.depends('name', 'parent_id.complete_name')
    def _compute_complete_name(self):
        for category in self:
            if category.parent_id:
                category.complete_name = '%s / %s' % (category.parent_id.complete_name, category.name)
            else:
                category.complete_name = category.name

    @api.constrains('parent_id')
    def _check_category_recursion(self):
        if not self._check_recursion():
            raise ValidationError(_('You cannot create recursive categories.'))

    def name_get(self):
        if not self.env.context.get('hierarchical_naming', True):
            return [(record.id, record.name) for record in self]
        return super().name_get()
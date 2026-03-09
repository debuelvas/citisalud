from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

class hr_transfers_of_entities(models.TransientModel):
    _name = 'hr.transfers.of.entities'
    _description = 'Traslados de Entidades'

    employee_id = fields.Many2one('hr.employee', string='Empleado', required=True)
    type_of_entity = fields.Many2one('hr.contribution.register', string='Tipo de Entidad', required=True)
    entity_actually = fields.Many2one('hr.employee.entities', string='Entidad actual', compute='_get_entities')
    new_entity = fields.Many2one('hr.employee.entities', string='Nueva entidad', domain="[('types_entities','in',[type_of_entity])]", required=True)
    date = fields.Date('Fecha de traslado', required=True)

    @api.onchange('employee_id', 'type_of_entity')
    def _get_entities(self):
        if self.employee_id and self.type_of_entity:
            obj_entity = self.env['hr.contract.setting'].search([('employee_id','=',self.employee_id.id),('contrib_id','=',self.type_of_entity.id)])
            if len(obj_entity) == 1:
                self.entity_actually = obj_entity.partner_id
            else:
                raise ValidationError(_('No se encontró entidad actual o se encontró más de una, verificar.'))

    def process_transfer(self):
        if self.employee_id and self.type_of_entity:
            obj_entity = self.env['hr.contract.setting'].search([('employee_id','=',self.employee_id.id),('contrib_id','=',self.type_of_entity.id)])

            if obj_entity.partner_id.id == self.new_entity.id:
                raise ValidationError(_('Esta intentado trasladar a la misma entidad, por favor verificar.'))

            if len(obj_entity) == 1:
                obj_entity.write({'partner_id':self.new_entity.id,'date_change':self.date,'is_transfer':True})
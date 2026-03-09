# -*- coding: utf-8 -*-
from datetime import date, datetime, timedelta
import time
import odoo.tools
from odoo.tools.safe_eval import safe_eval as eval
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
PARTNER_TYPE = [
    ('eps', 'EPS'),
    ('arl', 'ARL'),
    ('cesantias', 'CESANTIAS'),
    ('pensiones', 'PENSIONES'),
    ('caja', 'CAJA DE COMPENSACION'),
    ('other', 'OTRO'),
]
CATEGORIES = [
    ('earnings', 'DEVENGADO'),
    ('o_earnings', 'OTROS DEVENGOS'),
    ('o_salarial_earnings', 'OTROS DEVENGOS SALARIALES'),
    ('o_rights', 'OTROS DERECHOS'),
    ('comp_earnings', 'INGRESOS COMPLEMENTARIOS'),
    ('non_taxed_earnings', 'INGRESOS NO GRAVADOS'),
    ('deductions', 'DEDUCCIONES'),
    ('contributions', 'APORTES'),
    ('provisions', 'PROVISIONES'),
    ('subtotals', 'SUBTOTALES'),
]

class HrPayslipNovedades(models.Model):
    _name = "hr.payslip.novedades"
    _description = "Novedades Payslip"

    category_id = fields.Many2one('hr.payroll.novedades.category', 'Categoria', required=True, index=True)
    cantidad = fields.Float("Cantidad", readonly=True)
    total = fields.Float("Total", readonly=True)
    payslip_id = fields.Many2one('hr.payslip', 'Payslip', required=True, ondelete='cascade', index=True)


class HrPayrollNovedades(models.Model):
    _name = "hr.payroll.novedades"
    _description = "Novedades"
    _inherit = ['mail.thread']

    def _get_contract(self):
        for novedad in self:
            novedad.contract_id = self.env['hr.employee'].get_contract(novedad.employee_id, novedad.date)

    def _compute_price(self):
        for novedad in self:
            novedad.total = novedad.valor * novedad.cantidad

    def _no_amount(self):
        return all(novedad.cantidad > 0 and novedad.valor != 0.0 for novedad in self)

    def _check_contract(self):
        return all(not novedad.contract_id.date_end for novedad in self)

    payslip_id = fields.Many2one('hr.payslip', 'Pagado en nomina', readonly=True)
    payslip_neto_id = fields.Many2one('hr.payslip', 'Creado en la nomina', readonly=True)
    moneda_local = fields.Many2one('res.currency', string="Moneda Local", related='company_id.currency_id', readonly=True, store=True)
    date = fields.Date('Fecha', required=True, help="Fecha en la que aplica la novedad para el empleado", readonly=True, states={'draft': [('readonly', False)]})
    approve_date = fields.Date('Fecha de aprobacion', readonly=True, help="Fecha en la que se aprobo la novedad, dejela vacia para que se llene automaticamente", states={'confirmed': [('readonly', False)], 'draft': [('readonly', False)]})
    category_id = fields.Many2one('hr.payroll.novedades.category', 'Categoria', required=True, readonly=True, states={'draft': [('readonly', False)]})
    employee_id = fields.Many2one('hr.employee', 'Empleado', required=True, readonly=True, states={'draft': [('readonly', False)]})
    company_id = fields.Many2one('res.company', string="Compañia", related='contract_id.company_id', readonly=True, store=True)
    contract_id = fields.Many2one('hr.contract', string="Contrato", compute='_get_contract', store=True)
    valor = fields.Float("Valor", readonly=True, states={'draft': [('readonly', False)]})
    cantidad = fields.Float("Cantidad", readonly=True, states={'draft': [('readonly', False)]})
    total = fields.Float("Total", compute='_compute_price', string="Total", digits='Product Price', store=True)
    description = fields.Text('Descripcion', readonly=True, states={'draft': [('readonly', False)]})
    name = fields.Char('Codigo', size=64, readonly=True)
    neto = fields.Boolean('Regla del Neto a Pagar')
    state = fields.Selection([
        ('draft', 'Borrador'), 
        ('confirmed', 'Confirmada'), 
        ('validated', 'Validada'), 
        ('refused', 'Rechazada'), 
        ('cancelled', 'Cancelada'), 
        ('done', 'Pagada'), 
    ], 'State', select=True, readonly=True)
    
    @api.depends('employee_id', 'date')
    def _get_contract(self):
        for novedad in self:
            novedad.contract_id = self.env['hr.employee'].get_contract(novedad.employee_id, novedad.date)

    @api.depends('valor', 'cantidad')
    def _compute_price(self):
        for novedad in self:
            novedad.total = novedad.valor * novedad.cantidad

    # Constraints
    
    @api.constrains('valor', 'cantidad')
    def _no_amount(self):
        for novedad in self:
            if novedad.cantidad <= 0 or novedad.valor == 0.0:
                raise ValidationError("No se puede ingresar un valor 0 o una cantidad negativa o igual a 0")

    @api.constrains('contract_id')
    def _check_contract(self):
        for novedad in self:
            if novedad.contract_id.date_end:
                raise ValidationError("No puede asignar un contrato liquidado!")

    # Actions
    
    def action_draft(self):
        self.write({'state': 'draft'})

    def action_confirm(self):
        self.write({'state': 'confirmed'})

    def action_validate(self):
        for novedad in self:
            if not novedad.approve_date:
                novedad.approve_date = fields.Date.today()
        self.write({'state': 'validated'})

    def action_refuse(self):
        self.write({'state': 'refused'})

    def action_done(self):
        self.write({'state': 'done'})

    def action_cancel(self):
        self.write({'state': 'cancelled'})
        
    def unlink(self):
        for novedad in self:
            if novedad.state not in ['draft', 'cancelled']:
                raise UserError(_('No puede borrar una novedad que no esta en borrador o cancelada!'))
        return super(HrPayrollNovedades, self).unlink()

    @api.model_create_multi
    def create(self, vals_list):
        IrSequence = self.env['ir.sequence']
        
        for vals in vals_list:
            # Generate sequence number if not provided
            if not vals.get('name'):
                vals['name'] = IrSequence.next_by_code('payroll.novedades.number') or '/'

        # Create all records at once
        novedades = super().create(vals_list)
        
        # Add followers for each created record
        for novedad in novedades:
            if novedad.employee_id:
                empleado = novedad.employee_id
                followers_to_add = empleado.partner_id
                
                # Add employee's manager if exists
                if empleado.parent_id:
                    followers_to_add |= empleado.parent_id.partner_id
                
                # Update followers using OR operator
                novedad.message_follower_ids |= followers_to_add
        
        return novedades

class HrPayrollNovedadesCategory(models.Model):
    _name = "hr.payroll.novedades.category"
    _description = "Categoria de la novedad"

    name = fields.Char('Nombre', size=64, required=True, translate=True)
    code = fields.Char('Codigo', size=16, required=True)
    descripcion = fields.Text('Descripcion')
    concept_category = fields.Selection(CATEGORIES, 'Categoria de concepto', required=True)
    partner_type = fields.Selection(PARTNER_TYPE, 'Tipo de tercero')
    partner_other = fields.Many2one('res.partner', 'Otro Tercero')
    ex_rent = fields.Boolean('Ingreso exento de retencion')
    ded_rent = fields.Boolean('Aporte voluntario')
    afc = fields.Boolean('AFC')
    hour_novelty = fields.Boolean('Novedad por horas')


    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'El Nombre tiene que ser unico!'),
        ('code_uniq', 'unique(code)', 'El Codgigo tiene que ser unico!'),
    ]

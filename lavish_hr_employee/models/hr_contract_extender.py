# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from datetime import datetime, timedelta, date
from dateutil.relativedelta import relativedelta
import calendar
from odoo.exceptions import UserError, ValidationError

class HrWageAdjustment(models.Model):
    _name = 'hr.wage.adjustment'
    _description = 'Ajuste Salarial en Bloque'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'
    
    sequence_code = fields.Char('Código', required=True, default='/', readonly=True, copy=False)
    name = fields.Char('Nombre', required=True, tracking=True)
    date = fields.Date('Fecha de ajuste', required=True, default=fields.Date.today, tracking=True)
    company_id = fields.Many2one('res.company', string='Compañía', required=True, 
                                default=lambda self: self.env.company, tracking=True)
    
    adjustment_type = fields.Selection([
        ('percentage', 'Porcentaje'),
        ('fixed', 'Valor fijo'),
        ('increment', 'Incremento'),
        ('minimum_wage', 'Salario mínimo')
    ], string='Tipo de ajuste', required=True, default='percentage', tracking=True)
    
    percentage_value = fields.Float('Porcentaje (%)', digits=(16, 4), tracking=True)
    fixed_value = fields.Float('Valor fijo', tracking=True)
    increment_value = fields.Float('Incremento', tracking=True)
    
    adjust_transport = fields.Boolean('Ajustar auxilio de transporte', default=False, tracking=True,
                                    help="Quitar auxilio de transporte a salarios que superen 2 SMMLV")
    transport_threshold = fields.Float('Umbral para auxilio', 
                                    help="Salario a partir del cual se elimina el auxilio de transporte (por defecto, 2 SMMLV)")
    
    annual_parameters_id = fields.Many2one('hr.annual.parameters', string='Parámetros anuales',
                                          domain="[('year', '=', year)]", tracking=True)
    year = fields.Integer('Año', default=lambda self: fields.Date.today().year, tracking=True)
    
    extend_contracts = fields.Boolean('Prorrogar contratos', default=False, tracking=True,
                                    help="Si está marcado, se prorrogarán automáticamente los contratos a término fijo")
    extension_months = fields.Integer('Meses de prórroga', default=6, tracking=True)
    
    change_reason = fields.Selection([
        ('annual_update', 'Actualización anual'),
        ('adjustment', 'Ajuste general'),
        ('legal', 'Ajuste por normativa legal'),
        ('collective', 'Negociación colectiva'),
        ('business_decision', 'Decisión empresarial'),
        ('performance', 'Desempeño'),
        ('promotion', 'Promoción'),
        ('market_adjustment', 'Ajuste al mercado'),
        ('restructuring', 'Reestructuración'),
        ('other', 'Otro')
    ], string='Motivo del ajuste', required=True, default='annual_update', tracking=True)
    other_reason = fields.Char('Otro motivo', tracking=True)
    
    apply_retroactive = fields.Boolean('Aplicar retroactivo', default=True, tracking=True)
    retroactive_date_from = fields.Date('Fecha desde para retroactivo', tracking=True,
                                      help="Fecha desde la cual se calculará el retroactivo. Por defecto, la fecha del ajuste.")
    retroactive_date_to = fields.Date('Fecha hasta para retroactivo', tracking=True,
                                    help="Fecha hasta la cual se calculará el retroactivo. Por defecto, la fecha actual.")
    retroactive_in_regular_payslip = fields.Boolean('Incluir en nómina regular', default=False, tracking=True)
    
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('approved', 'Aprobado'),  # Por defecto aprobado como solicitado
        ('in_process', 'En proceso'),
        ('done', 'Finalizado'),
        ('cancelled', 'Cancelado')
    ], string='Estado', default='approved', tracking=True)
    
    salary_rule_ids = fields.Many2many('hr.salary.rule', string='Reglas para retroactivo',
                                      domain=[('appears_on_payslip', '=', True)],
                                      default=lambda self: self._default_salary_rules())
    
    include_overtime = fields.Boolean('Incluir horas extra', default=True, tracking=True)
    include_allowances = fields.Boolean('Incluir subsidios', default=True, tracking=True)
    
    line_ids = fields.One2many('hr.wage.adjustment.line', 'adjustment_id', string='Líneas de ajuste')
    retroactive_id = fields.Many2one('hr.retroactive.salary', string='Retroactivo generado')
    
    employee_count = fields.Integer('Total empleados', compute='_compute_stats')
    processed_count = fields.Integer('Procesados', compute='_compute_stats')
    error_count = fields.Integer('Con errores', compute='_compute_stats')
    progress_percentage = fields.Float('Progreso %', compute='_compute_stats')
    
    total_wage_before = fields.Float('Total salarios antes', compute='_compute_totals')
    total_wage_after = fields.Float('Total salarios después', compute='_compute_totals')
    total_difference = fields.Float('Diferencia total', compute='_compute_totals')
    practitioner_count = fields.Integer('Practicantes', compute='_compute_contract_stats')
    integral_salary_count = fields.Integer('Salarios integrales', compute='_compute_contract_stats')
    active_contract_count = fields.Integer('Contratos activos', compute='_compute_contract_stats')
    health_contribution_impact = fields.Float('Impacto en aportes salud', compute='_compute_totals')
    
    @api.model
    def _default_salary_rules(self):
        basic_rules = self.env['hr.salary.rule'].search([
            ('category_id.code', 'in', ['BASIC', 'ALW', 'HE']),
            ('appears_on_payslip', '=', True)
        ])
        return basic_rules.ids
    
    @api.model
    def create(self, vals):
        if vals.get('sequence_code', '/') == '/':
            vals['sequence_code'] = self.env['ir.sequence'].next_by_code('hr.wage.adjustment') or '/'
        
        if vals.get('apply_retroactive') and not vals.get('retroactive_date_from'):
            vals['retroactive_date_from'] = vals.get('date')
        
        if vals.get('apply_retroactive') and not vals.get('retroactive_date_to'):
            vals['retroactive_date_to'] = fields.Date.today()
            
        if vals.get('adjust_transport') and not vals.get('transport_threshold'):
            annual_param = self.env['hr.annual.parameters'].search([
                ('year', '=', vals.get('year', fields.Date.today().year))
            ], limit=1)
            if annual_param and annual_param.smmlv_monthly:
                vals['transport_threshold'] = annual_param.smmlv_monthly * 2
                
        return super(HrWageAdjustment, self).create(vals)
    
    @api.depends('line_ids', 'line_ids.state')
    def _compute_stats(self):
        for record in self:
            record.employee_count = len(record.line_ids)
            record.processed_count = len(record.line_ids.filtered(lambda l: l.state == 'done'))
            record.error_count = len(record.line_ids.filtered(lambda l: l.state == 'error'))
            record.progress_percentage = (record.processed_count / record.employee_count * 100) if record.employee_count else 0.0
    
    @api.depends('line_ids', 'line_ids.current_wage', 'line_ids.new_wage')
    def _compute_totals(self):
        for record in self:
            record.total_wage_before = sum(record.line_ids.mapped('current_wage'))
            record.total_wage_after = sum(record.line_ids.mapped('new_wage'))
            record.total_difference = record.total_wage_after - record.total_wage_before
            
            record.health_contribution_impact = record.total_difference * 0.085
    
    @api.depends('line_ids', 'line_ids.contract_id')
    def _compute_contract_stats(self):
        for record in self:
            record.practitioner_count = len(record.line_ids.filtered(
                lambda l: l.contract_id.contract_type == 'aprendizaje'
            ))
            
            record.integral_salary_count = len(record.line_ids.filtered(
                lambda l: l.contract_id.modality_salary == 'integral'
            ))
            
            active_contracts = self.env['hr.contract'].search([
                ('state', '=', 'open'),
                ('company_id', '=', record.company_id.id)
            ])
            record.active_contract_count = len(active_contracts)
    
    @api.onchange('adjustment_type')
    def _onchange_adjustment_type(self):
        if self.adjustment_type == 'minimum_wage':
            params = self.env['hr.annual.parameters'].search([('year', '=', self.year)], limit=1)
            if params:
                self.annual_parameters_id = params.id
                self.fixed_value = params.smmlv_monthly
            else:
                warning = {
                    'title': _('Advertencia'),
                    'message': _('No se encontraron parámetros anuales para el año %s. Por favor, cree los parámetros primero.', self.year)
                }
                return {'warning': warning}
    
    @api.onchange('annual_parameters_id')
    def _onchange_annual_parameters(self):
        if self.annual_parameters_id and self.adjustment_type == 'minimum_wage':
            self.fixed_value = self.annual_parameters_id.smmlv_monthly
            self.transport_threshold = self.annual_parameters_id.smmlv_monthly * 2
    
    @api.onchange('date')
    def _onchange_date(self):
        if self.date:
            self.retroactive_date_from = self.date
    
    @api.onchange('adjust_transport')
    def _onchange_adjust_transport(self):
        if self.adjust_transport and not self.transport_threshold:
            params = self.env['hr.annual.parameters'].search([('year', '=', self.year)], limit=1)
            if params and params.smmlv_monthly:
                self.transport_threshold = params.smmlv_monthly * 2
    
    def action_load_employees(self):
        """Abre el asistente para cargar empleados"""
        self.ensure_one()
        
        return {
            'name': _('Cargar Empleados'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.wage.adjustment.load.employees.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_adjustment_id': self.id,
                'default_company_id': self.company_id.id,
            }
        }
    
    def action_process(self):
        """Inicia el procesamiento del ajuste salarial"""
        for record in self:
            if record.state != 'approved':
                continue
                
            record.state = 'in_process'
            
            # Crear modificaciones contractuales para cada línea
            record._create_modifications()
            
            # Crear retroactivo si está configurado
            if record.apply_retroactive and not record.retroactive_id:
                record._create_retroactive()
            
            record.state = 'done'
    
    def action_reset(self):
        """Restablece a borrador para permitir cambios"""
        for record in self:
            if record.state in ('approved', 'done'):
                record.state = 'draft'
    
    def action_cancel(self):
        """Cancela el ajuste salarial"""
        for record in self:
            if record.state in ('draft', 'approved'):
                record.state = 'cancelled'
    
    def action_view_retroactive(self):
        """Ver el retroactivo generado"""
        self.ensure_one()
        
        if not self.retroactive_id:
            raise UserError(_('No se ha generado ningún retroactivo para este ajuste.'))
        
        return {
            'name': _('Retroactivo'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.retroactive.salary',
            'res_id': self.retroactive_id.id,
            'view_mode': 'form',
        }
    
    def action_notify_employees(self):
        """Envía notificaciones a los empleados sobre el ajuste salarial"""
        self.ensure_one()
        
        lines = self.line_ids.filtered(lambda l: l.state == 'done' and l.employee_id.user_id and l.employee_id.work_email)
        
        for line in lines:
            # Enviar correo directo sin wizard
            partner = line.employee_id.user_id.partner_id
            subject = f"Actualización de su salario - {self.name}"
            body = f"""
                <p>Estimado/a {line.employee_id.name},</p>
                <p>Le informamos que su salario ha sido actualizado:</p>
                <ul>
                    <li><strong>Salario anterior:</strong> {line.current_wage}</li>
                    <li><strong>Nuevo salario:</strong> {line.new_wage}</li>
                    <li><strong>Incremento:</strong> {line.difference} ({line.difference_percentage:.4f}%)</li>
                    <li><strong>Fecha efectiva:</strong> {self.date}</li>
                </ul>
                <p>Este cambio se verá reflejado en su próxima nómina.</p>
                <p>Atentamente,<br/>Departamento de Recursos Humanos</p>
            """
            
            line.employee_id.message_post(
                body=body,
                subject=subject,
                partner_ids=[partner.id],
                message_type='notification',
                subtype_id=self.env.ref('mail.mt_note').id
            )
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Notificaciones enviadas'),
                'message': _('{} empleados han sido notificados.', len(lines)),
                'type': 'success',
            }
        }
    
    def _create_modifications(self):
        """Crea modificaciones contractuales para cada línea de ajuste"""
        self.ensure_one()
        
        for line in self.line_ids.filtered(lambda l: l.state == 'pending'):
            try:
                if line.difference < 0:
                    self.env.user.notify_warning(
                        title=_('Alerta de reducción salarial'),
                        message=_(
                            'El salario de {} será reducido de {} a {} ({}%). '
                            'Asegúrese de que esta reducción cumple con la normativa laboral.'.format(
                                line.employee_id.name, line.current_wage, line.new_wage, line.difference_percentage
                            )
                        )
                    )
                
                values = {
                    'contract_id': line.contract_id.id,
                    'date': self.date,
                    'description': f"{self.name} - {dict(self._fields['adjustment_type'].selection).get(self.adjustment_type)}",
                    'wage': line.new_wage,
                    'wage_adjustment_id': self.id,
                    'change_reason': self.change_reason,
                    'other_reason': self.other_reason,
                    'apply_retroactive': self.apply_retroactive,
                    'retroactive_date': self.retroactive_date_from or self.date,
                    'state': 'approved',
                }
                
                if self.adjust_transport and line.new_wage > self.transport_threshold:
                    values['modality_aux'] = 'no'  # Sin auxilio de transporte
                
                # Si hay prórroga, incluir datos
                if self.extend_contracts and line.extend_contract:
                    values.update({
                        'prorroga': True,
                        'date_from': line.extension_date_from,
                        'date_to': line.extension_date_to,
                        'sequence': line.extension_sequence
                    })
                
                # Crear la modificación
                modification = self.env['hr.contractual.modifications'].create(values)
                
                # Aplicar los cambios
                modification.action_apply_changes()
                
                # Actualizar línea
                line.state = 'done'
                line.modification_id = modification.id
                
            except Exception as e:
                line.state = 'error'
                line.error_message = str(e)
    
    def _create_retroactive(self):
        """Crea un cálculo retroactivo para el ajuste salarial"""
        self.ensure_one()
        
        if not self.retroactive_date_from:
            self.retroactive_date_from = self.date
            
        if not self.retroactive_date_to:
            self.retroactive_date_to = fields.Date.today()
        
        # Obtener reglas salariales para el retroactivo
        salary_rules = self.salary_rule_ids
        
        if not salary_rules:
            # Si no hay reglas seleccionadas, usar reglas por defecto
            salary_rules = self.env['hr.salary.rule'].search([
                ('category_id.code', 'in', ['BASIC', 'ALW']),
                ('appears_on_payslip', '=', True)
            ])
            
            # Incluir horas extra si está activado
            if self.include_overtime:
                overtime_rules = self.env['hr.salary.rule'].search([
                    ('category_id.code', '=', 'HE'),
                    ('appears_on_payslip', '=', True)
                ])
                salary_rules |= overtime_rules
                
            # Incluir subsidios si está activado
            if self.include_allowances:
                allowance_rules = self.env['hr.salary.rule'].search([
                    ('category_id.code', '=', 'AUX'),
                    ('appears_on_payslip', '=', True)
                ])
                salary_rules |= allowance_rules
        
        if not salary_rules:
            return False
        
        # Generar código de secuencia
        sequence_code = self.env['ir.sequence'].next_by_code('hr.retroactive.salary') or '/'
        
        # Crear retroactivo
        retroactive = self.env['hr.retroactive.salary'].create({
            'name': f"Retroactivo - {self.name}",
            'date_from': self.retroactive_date_from,
            'date_to': self.retroactive_date_to,
            'company_id': self.company_id.id,
            'salary_rule_ids': [(6, 0, salary_rules.ids)],
            'in_regular_payslip': self.retroactive_in_regular_payslip,
            'sequence_code': sequence_code,
            'wage_adjustment_id': self.id,
            'state': 'approved',
            'include_overtime': self.include_overtime,
            'include_allowances': self.include_allowances
        })
        
        # Vincular el retroactivo creado
        self.retroactive_id = retroactive.id
        
        # Crear líneas de retroactivo
        for line in self.line_ids.filtered(lambda l: l.state == 'done' and l.difference != 0):
            self.env['hr.retroactive.salary.line'].create({
                'retroactive_id': retroactive.id,
                'employee_id': line.employee_id.id,
                'contract_id': line.contract_id.id,
                'date_from': self.retroactive_date_from,
                'date_to': self.retroactive_date_to,
                'old_wage': line.current_wage,
                'new_wage': line.new_wage
            })
        
        # Procesar retroactivo automáticamente
        retroactive.action_confirm()
        
        return retroactive


class HrWageAdjustmentLine(models.Model):
    _name = 'hr.wage.adjustment.line'
    _description = 'Línea de ajuste salarial'
    
    adjustment_id = fields.Many2one('hr.wage.adjustment', string='Ajuste salarial', required=True, ondelete='cascade')
    employee_id = fields.Many2one('hr.employee', string='Empleado', required=True)
    contract_id = fields.Many2one('hr.contract', string='Contrato', required=True)
    
    # Datos de salario
    current_wage = fields.Float(string='Salario actual')
    new_wage = fields.Float(string='Nuevo salario', compute='_compute_new_wage', store=True)
    difference = fields.Float(string='Diferencia', compute='_compute_difference', store=True)
    difference_percentage = fields.Float(string='Diferencia %', compute='_compute_difference', store=True, digits=(16, 4))
    
    # Prórroga
    extend_contract = fields.Boolean(string='Prorrogar contrato', default=False)
    extension_date_from = fields.Date(string='Inicio prórroga')
    extension_date_to = fields.Date(string='Fin prórroga')
    extension_sequence = fields.Integer(string='Secuencia prórroga', default=0)
    
    # Estado
    state = fields.Selection([
        ('pending', 'Pendiente'),
        ('done', 'Realizado'),
        ('error', 'Error'),
        ('cancelled', 'Cancelado')
    ], string='Estado', default='pending')
    
    error_message = fields.Text(string='Mensaje de error')
    
    # Modificación generada
    modification_id = fields.Many2one('hr.contractual.modifications', string='Modificación generada')
    
    # Información adicional
    department_id = fields.Many2one(related='employee_id.department_id', store=True)
    job_id = fields.Many2one(related='employee_id.job_id', store=True)
    contract_type = fields.Selection(related='contract_id.contract_type', string='Tipo de contrato', store=True)
    modality_salary = fields.Selection(related='contract_id.modality_salary', string='Modalidad salarial', store=True)
    modality_aux = fields.Selection(related='contract_id.modality_aux', string='Auxilio transporte', store=True)
    employee_antiquity = fields.Integer('Antigüedad (meses)', compute='_compute_employee_info', store=True)
    
    # Opciones adicionales
    update_aux_transport = fields.Boolean(string='Actualizar auxilio transporte', default=False)
    
    @api.depends('current_wage', 'adjustment_id.adjustment_type', 'adjustment_id.percentage_value', 
                'adjustment_id.fixed_value', 'adjustment_id.increment_value')
    def _compute_new_wage(self):
        for record in self:
            adj = record.adjustment_id
            if adj.adjustment_type == 'percentage':
                record.new_wage = record.current_wage * (1 + (adj.percentage_value / 100))
            elif adj.adjustment_type == 'fixed':
                record.new_wage = adj.fixed_value
            elif adj.adjustment_type == 'increment':
                record.new_wage = record.current_wage + adj.increment_value
            elif adj.adjustment_type == 'minimum_wage':
                # Si el salario actual es menor que el mínimo, actualizar
                if record.current_wage < adj.fixed_value:
                    record.new_wage = adj.fixed_value
                else:
                    record.new_wage = record.current_wage
    
    @api.depends('current_wage', 'new_wage')
    def _compute_difference(self):
        for record in self:
            record.difference = record.new_wage - record.current_wage
            record.difference_percentage = (record.difference / record.current_wage * 100) if record.current_wage else 0.0
    
    @api.depends('employee_id', 'contract_id')
    def _compute_employee_info(self):
        for record in self:
            if record.employee_id and record.contract_id and record.contract_id.date_start:
                # Calcular antigüedad
                start_date = record.contract_id.date_start
                today = fields.Date.today()
                delta = relativedelta(today, start_date)
                record.employee_antiquity = delta.years * 12 + delta.months
            else:
                record.employee_antiquity = 0
    
    @api.onchange('contract_id')
    def _onchange_contract(self):
        if self.contract_id:
            self.current_wage = self.contract_id.wage
            
            # Configurar prórroga si el contrato es a término fijo
            if self.contract_id.date_end and self.adjustment_id.extend_contracts:
                if self.contract_id.contract_type in ('fijo', 'fijo_parcial', 'temporal'):
                    self.extend_contract = True
                    self.extension_date_from = self.contract_id.date_end + timedelta(days=1)
                    
                    # Calcular duración de prórroga
                    months = self.adjustment_id.extension_months
                    self.extension_date_to = self.extension_date_from + relativedelta(months=months) - timedelta(days=1)
                    
                    # Calcular secuencia de prórroga
                    extensions = self.env['hr.contractual.modifications'].search([
                        ('contract_id', '=', self.contract_id.id),
                        ('prorroga', '=', True),
                        ('state', '=', 'approved')
                    ])
                    
                    self.extension_sequence = len(extensions) + 1
                    
                    # Si es la 4ta prórroga o posterior, mínimo 1 año
                    if self.extension_sequence >= 4:
                        min_days = 365
                        current_days = (self.extension_date_to - self.extension_date_from).days + 1
                        if current_days < min_days:
                            self.extension_date_to = self.extension_date_from + timedelta(days=min_days - 1)
    
    def action_create_modification(self):
        """Crea una modificación contractual directamente desde la línea"""
        self.ensure_one()
        
        if self.state != 'pending':
            raise UserError(_('Solo se pueden crear modificaciones para líneas pendientes.'))
        
        # Crear la modificación contractual
        values = {
            'contract_id': self.contract_id.id,
            'date': self.adjustment_id.date,
            'description': f"{self.adjustment_id.name} - Ajuste individual",
            'wage': self.new_wage,
            'wage_adjustment_id': self.adjustment_id.id,
            'change_reason': self.adjustment_id.change_reason,
            'other_reason': self.adjustment_id.other_reason,
            'apply_retroactive': self.adjustment_id.apply_retroactive,
            'retroactive_date': self.adjustment_id.retroactive_date_from or self.adjustment_id.date,
            'state': 'approved',
        }
        
        # Actualizar modalidad de auxilio de transporte si corresponde
        if self.update_aux_transport:
            params = self.env['hr.annual.parameters'].search([
                ('year', '=', self.adjustment_id.year)
            ], limit=1)
            
            if params and params.smmlv and self.new_wage > (params.smmlv * 2):
                values['modality_aux'] = 'no'  # Sin auxilio de transporte
        
        # Si hay prórroga, incluir datos
        if self.extend_contract:
            values.update({
                'prorroga': True,
                'date_from': self.extension_date_from,
                'date_to': self.extension_date_to,
                'sequence': self.extension_sequence
            })
        
        # Crear la modificación
        modification = self.env['hr.contractual.modifications'].create(values)
        
        # Aplicar los cambios
        modification.action_apply_changes()
        
        # Actualizar línea
        self.state = 'done'
        self.modification_id = modification.id
        
        return {
            'name': _('Modificación Contractual'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.contractual.modifications',
            'res_id': modification.id,
            'view_mode': 'form',
        }
    
    def action_cancel(self):
        """Cancela la línea de ajuste"""
        for record in self:
            if record.state == 'pending':
                record.state = 'cancelled'
    
    def action_reset(self):
        """Restablece la línea a pendiente"""
        for record in self:
            if record.state in ('error', 'cancelled'):
                record.state = 'pending'
                record.error_message = False


class HrContractChangeWage(models.Model):
    _name = 'hr.contract.change.wage'
    _description = 'Cambios salario básico'
    _order = 'date_start'
    
    date_start = fields.Date('Fecha inicial')
    wage = fields.Float('Salario básico', help='Seguimiento de los cambios en el salario básico')
    contract_id = fields.Many2one('hr.contract', 'Contrato', required=True, ondelete='cascade')
    job_id = fields.Many2one('hr.job', string='Cargo')
    
    # Campos adicionales
    reason = fields.Selection([
        ('annual_update', 'Actualización anual'),
        ('adjustment', 'Ajuste general'),
        ('legal', 'Ajuste por normativa legal'),
        ('collective', 'Negociación colectiva'),
        ('business_decision', 'Decisión empresarial'),
        ('performance', 'Desempeño'),
        ('promotion', 'Promoción'),
        ('market_adjustment', 'Ajuste al mercado'),
        ('restructuring', 'Reestructuración'),
        ('other', 'Otro')
    ], string='Motivo del cambio')
    other_reason = fields.Char('Otro motivo')
    difference = fields.Float('Diferencia', compute='_compute_difference', store=True)
    difference_percentage = fields.Float('Porcentaje diferencia', compute='_compute_difference', store=True, digits=(16, 4))
    wage_adjustment_id = fields.Many2one('hr.wage.adjustment', string='Ajuste salarial origen')
    
    modification_id = fields.Many2one('hr.contractual.modifications', string='Modificación origen',
                                     compute='_compute_modification_id', store=True)
    
    _sql_constraints = [
        ('change_wage_uniq', 'unique(contract_id, date_start, wage, job_id)',
         'Ya existe un cambio de salario igual a este')
    ]
    
    @api.depends('contract_id', 'date_start', 'wage')
    def _compute_modification_id(self):
        for record in self:
            modification = self.env['hr.contractual.modifications'].search([
                ('contract_id', '=', record.contract_id.id),
                ('wage', '=', record.wage),
                ('date', '<=', record.date_start),
                ('state', '=', 'approved')
            ], order='date desc', limit=1)
            
            record.modification_id = modification.id if modification else False
    
    @api.depends('wage', 'contract_id.wage')
    def _compute_difference(self):
        for record in self:
            prev_wage = 0
            # Buscar el salario anterior
            prev_changes = self.search([
                ('contract_id', '=', record.contract_id.id),
                ('date_start', '<', record.date_start)
            ], order='date_start desc', limit=1)
            
            if prev_changes:
                prev_wage = prev_changes.wage
            else:
                prev_wage = record.contract_id.wage
            
            record.difference = record.wage - prev_wage
            record.difference_percentage = (record.difference / prev_wage * 100) if prev_wage else 0.0
    
    @api.model
    def create(self, vals):
        # Verificar si hay disminución de salario
        if 'wage' in vals and 'contract_id' in vals:
            contract = self.env['hr.contract'].browse(vals['contract_id'])
            if contract and vals['wage'] < contract.wage:
                # Generar alerta por disminución salarial
                self.env.user.notify_warning(
                    title=_('Alerta de reducción salarial'),
                    message=_(
                        'El salario del contrato {} será reducido de {} a {}. '
                        'Asegúrese de que esta reducción cumple con la normativa laboral.'.format(
                            contract.name, contract.wage, vals['wage']
                        )
                    )
                )
        
        return super(HrContractChangeWage, self).create(vals)


class HrRetroactiveSalary(models.Model):
    _name = 'hr.retroactive.salary'
    _description = 'Retroactivo salarial'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_from desc, date_to desc'

    # Campos básicos
    sequence_code = fields.Char('Código', required=True, default='/', readonly=True, copy=False)
    name = fields.Char(string='Nombre', required=True, tracking=True)
    date_from = fields.Date(string='Fecha desde', required=True, tracking=True)
    date_to = fields.Date(string='Fecha hasta', required=True, tracking=True)
    company_id = fields.Many2one('res.company', string='Compañía', required=True, 
                                default=lambda self: self.env.company, tracking=True)
    
    # Estado (aprobado por defecto como solicitado)
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('approved', 'Aprobado'),
        ('process', 'En proceso'),
        ('done', 'Realizado'),
        ('cancel', 'Cancelado')
    ], string='Estado', default='approved', tracking=True)
    
    # Relaciones
    line_ids = fields.One2many('hr.retroactive.salary.line', 'retroactive_id', string='Líneas')
    salary_rule_ids = fields.Many2many('hr.salary.rule', string='Reglas salariales', 
                                      required=True,
                                      help='Reglas salariales a incluir en el cálculo retroactivo')
    wage_adjustment_id = fields.Many2one('hr.wage.adjustment', string='Ajuste salarial origen')
    
    # Opciones de nómina
    in_regular_payslip = fields.Boolean('Incluir en nómina regular', default=False, tracking=True,
                                       help="Si está marcado, el retroactivo se pagará en la próxima nómina regular. Si no, se generará una nómina específica para el retroactivo.")
    
    # Opciones adicionales para el cálculo
    include_overtime = fields.Boolean('Incluir horas extra', default=True, tracking=True,
                                    help="Incluir horas extras en el cálculo del retroactivo")
    include_allowances = fields.Boolean('Incluir subsidios', default=True, tracking=True,
                                      help="Incluir subsidios en el cálculo del retroactivo")
    
    # Campos de progreso y estadísticas
    total_employees = fields.Integer(string='Total empleados', compute='_compute_stats')
    processed_employees = fields.Integer(string='Empleados procesados', compute='_compute_stats')
    progress_percentage = fields.Float(string='Progreso %', compute='_compute_stats')
    total_amount = fields.Float(string='Monto total', compute='_compute_stats')
    
    @api.model
    def create(self, vals):
        if vals.get('sequence_code', '/') == '/':
            vals['sequence_code'] = self.env['ir.sequence'].next_by_code('hr.retroactive.salary') or '/'
        return super(HrRetroactiveSalary, self).create(vals)

    @api.depends('line_ids', 'line_ids.state', 'line_ids.difference')
    def _compute_stats(self):
        for record in self:
            record.total_employees = len(record.line_ids)
            record.processed_employees = len(record.line_ids.filtered(lambda l: l.state == 'done'))
            record.progress_percentage = (record.processed_employees / record.total_employees * 100) if record.total_employees else 0.0
            
            # Calcular monto total teniendo en cuenta días y factor
            total = 0
            for line in record.line_ids:
                days = (line.date_to - line.date_from).days + 1
                daily_diff = line.difference / 30  # Base diaria
                total += daily_diff * days
            
            record.total_amount = total

    @api.onchange('date_from', 'date_to', 'company_id')
    def _onchange_period(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValidationError(_('La fecha desde no puede ser mayor que la fecha hasta'))

    def action_confirm(self):
        """Confirma el retroactivo y comienza a procesarlo"""
        for record in self:
            if record.state != 'approved':
                continue
                
            record.state = 'process'
            record.process_retroactive()
    
    def action_reset(self):
        """Restablece a borrador el retroactivo"""
        for record in self:
            if record.state in ('done', 'cancel'):
                record.state = 'approved'
    
    def action_cancel(self):
        """Cancela el retroactivo"""
        for record in self:
            if record.state in ('draft', 'approved', 'process'):
                record.state = 'cancel'
    
    def process_retroactive(self):
        """
        Procesa el cálculo de retroactivo para todas las líneas
        """
        self.ensure_one()
        
        if self.state != 'process':
            return
            
        # Procesar líneas en estado pendiente
        lines = self.line_ids.filtered(lambda l: l.state != 'done')
        
        for line in lines:
            try:
                if self.in_regular_payslip:
                    # Crear entrada para incluir en próxima nómina regular
                    self._create_retroactive_input(line)
                else:
                    # Procesar la línea con nómina específica
                    line.process_line(self.salary_rule_ids, self.include_overtime, self.include_allowances)
                    
                # Marcar como procesada
                line.state = 'done'
            except Exception as e:
                # Registrar error
                line.state = 'error'
                line.error_message = str(e)
        
        # Verificar si todas las líneas están procesadas
        if all(l.state in ('done', 'cancel', 'error') for l in self.line_ids):
            self.state = 'done'
    
    def _create_retroactive_input(self, line):
        """
        Crea entradas para incluir el retroactivo en la próxima nómina regular
        """
        # Calcular el monto retroactivo
        days = (line.date_to - line.date_from).days + 1
        daily_diff = line.difference / 30  # Proporción diaria
        base_amount = daily_diff * days
        
        # Crear input para cada regla salarial
        for rule in self.salary_rule_ids:
            category_code = rule.category_id.code
            
            # Determinar monto según categoría de la regla
            if category_code == 'BASIC':
                amount = base_amount
            elif category_code == 'ALW' and self.include_allowances:
                amount = base_amount
            elif category_code == 'HE' and self.include_overtime:
                # Para horas extra, buscamos la proporción de horas extra en nóminas del período
                overtime_factor = self._get_overtime_factor(line)
                amount = base_amount * overtime_factor
            else:
                amount = 0
            
            if amount > 0:
                self.env['hr.payslip.input'].create({
                    'name': f"Retroactivo {rule.name}",
                    'code': f"RETRO_{rule.code}",
                    'contract_id': line.contract_id.id,
                    'amount': amount,
                    'retroactive_id': self.id
                })
            
        return True
    
    def _get_overtime_factor(self, line):
        """
        Calcula el factor de horas extra basado en nóminas históricas
        """
        # Buscar nóminas en el período
        payslips = self.env['hr.payslip'].search([
            ('employee_id', '=', line.employee_id.id),
            ('contract_id', '=', line.contract_id.id),
            ('date_from', '>=', line.date_from),
            ('date_to', '<=', line.date_to),
            ('state', 'in', ['done', 'paid'])
        ])
        
        if not payslips:
            return 0.1  # Factor por defecto del 10% si no hay datos
        
        # Calcular la proporción de horas extra respecto al básico
        basic_total = sum(payslips.mapped('line_ids').filtered(
            lambda l: l.category_id.code == 'BASIC'
        ).mapped('amount'))
        
        overtime_total = sum(payslips.mapped('line_ids').filtered(
            lambda l: l.category_id.code == 'HE'
        ).mapped('amount'))
        
        if basic_total:
            return overtime_total / basic_total
        return 0.1  # Factor por defecto
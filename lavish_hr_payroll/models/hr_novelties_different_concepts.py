from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class HrNoveltyDifferentConcepts(models.Model):
    _name = 'hr.novelties.different.concepts'
    _description = 'Novedades por conceptos diferentes'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    # Campos básicos
    name = fields.Char(
        'Referencia', 
        readonly=True,
        copy=False,
        default='/'
    )
    company_id = fields.Many2one(
        'res.company', 
        string='Compañía',
        default=lambda self: self.env.company
    )
    employee_id = fields.Many2one(
        'hr.employee', 
        string='Empleado', 
        index=True,
        tracking=True
    )
    employee_identification = fields.Char(
        'Identificación empleado',
        related='employee_id.identification_id',
        store=True,
        tracking=True
    )
    salary_rule_id = fields.Many2one(
        'hr.salary.rule', 
        string='Regla salarial', 
        required=True,
        domain=[('novedad_ded', '=', 'Noved')],
        tracking=True
    )
    salary_structure_ids = fields.Many2many(
        'hr.payroll.structure',
        string='Estructuras Salariales Aplicables',
        help='Estructuras de nómina donde se puede aplicar esta novedad'
    )
    dev_or_ded = fields.Selection(
        'Naturaleza',
        related='salary_rule_id.dev_or_ded',
        store=True, 
        readonly=True
    )
    date = fields.Date(
        'Fecha', 
        required=True,
        tracking=True
    )
    amount = fields.Float(
        'Valor', 
        required=True,
        tracking=True
    )
    description = fields.Char(
        'Descripción',
        tracking=True
    )
    partner_id = fields.Many2one(
        'hr.employee.entities', 
        'Entidad'
    )
    payslip_id = fields.Many2one(
        'hr.payslip', 
        'Pagado en nomina', 
        readonly=True
    )
    
    # Campos para manejo de estado y aprobación
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('pending', 'Pendiente Aprobación'),
        ('approved', 'Aprobado'),
        ('rejected', 'Rechazado'),
        ('cancelled', 'Cancelado'),
        ('processed', 'Procesado')
    ], string='Estado', default='draft', tracking=True)
    
    approval_user_id = fields.Many2one(
        'res.users', 
        'Aprobado por',
        readonly=True,
        tracking=True
    )
    approval_date = fields.Datetime(
        'Fecha Aprobación',
        readonly=True
    )
    
    # Campos para novedades masivas
    is_massive = fields.Boolean(
        'Es Novedad Masiva',
        help='Indica si la novedad fue creada de forma masiva'
    )
    massive_group_id = fields.Many2one(
        'hr.novelty.massive.group',
        'Grupo de Novedades Masivas',
        ondelete='set null'
    )
    
    # Campos para traslados
    transfer_date = fields.Date('Fecha de Traslado')
    original_novelty_id = fields.Many2one(
        'hr.novelties.different.concepts',
        'Novedad Original'
    )
    transferred_novelty_ids = fields.One2many(
        'hr.novelties.different.concepts',
        'original_novelty_id',
        'Novedades Trasladadas'
    )

    massive_group_id = fields.Many2one(
        'hr.novelty.massive.group',
        'Grupo de Novedades Masivas',
        readonly=True
    )

    


    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # Generar secuencia
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('hr.novelty') or '/'
        return super().create(vals_list)

    @api.constrains('amount')
    def _check_amount(self):
        for record in self:
            if record.dev_or_ded == 'deduccion' and record.amount > 0:
                raise ValidationError(_('La regla es de tipo deducción, el valor debe ser negativo'))
            if record.dev_or_ded == 'devengo' and record.amount < 0:
                raise ValidationError(_('La regla es de tipo devengo, el valor debe ser positivo'))

    def action_submit_approval(self):
        """Enviar para aprobación"""
        for record in self:
            if record.state != 'draft':
                raise UserError(_('Solo se pueden enviar a aprobación novedades en borrador'))
            record.write({'state': 'pending'})
            
            # Notificar a aprobadores
            self._notify_approvers()

    def action_approve(self):
        """Aprobar novedad"""
        for record in self:
            if record.state != 'pending':
                raise UserError(_('Solo se pueden aprobar novedades pendientes'))
            record.write({
                'state': 'approved',
                'approval_user_id': self.env.user.id,
                'approval_date': fields.Datetime.now()
            })

    def action_reject(self):
        """Rechazar novedad"""
        return {
            'name': _('Rechazar Novedad'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.novelty.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_novelty_id': self.id}
        }

    def action_cancel(self):
        """Cancelar novedad"""
        for record in self:
            if record.payslip_id:
                raise UserError(_('No se puede cancelar una novedad ya procesada en nómina'))
            record.write({'state': 'cancelled'})

    def action_draft(self):
        """Volver a borrador"""
        for record in self:
            if record.state not in ['rejected', 'cancelled']:
                raise UserError(_('Solo se pueden pasar a borrador novedades rechazadas o canceladas'))
            record.write({'state': 'draft'})

    def action_transfer_novelty(self):
        """Abrir asistente para trasladar novedad"""
        return {
            'name': _('Trasladar Novedad'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.novelty.transfer.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_novelty_id': self.id}
        }

    def action_create_massive(self):
        """Abrir asistente para crear novedades masivas"""
        return {
            'name': _('Crear Novedades Masivas'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.novelty.massive.wizard',
            'view_mode': 'form',
            'target': 'new'
        }

    def action_view_form(self):
        """Ver formulario de novedad"""
        return {
            'name': _('Novedad'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.novelties.different.concepts',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current'
        }

    def action_delete_novedad(self):
        """Eliminar novedad"""
        for record in self:
            if record.state not in ['draft', 'cancelled']:
                raise UserError(_('Solo se pueden eliminar novedades en borrador o canceladas'))
            if record.payslip_id:
                raise UserError(_('No se puede eliminar una novedad ya procesada en nómina'))
        self.unlink()

    def _notify_approvers(self):
        """Notificar a los aprobadores sobre nueva novedad pendiente"""
        approver_group = self.env.ref('hr.group_hr_manager')
        partner_ids = approver_group.users.mapped('partner_id').ids
        
        for record in self:
            record.message_post(
                body=_('Nueva novedad pendiente de aprobación'),
                partner_ids=partner_ids,
                subtype_xmlid='mail.mt_comment'
            )

    def copy(self, default=None):
        """Duplicar novedad"""
        self.ensure_one()
        default = dict(default or {})
        default.update({
            'name': '/',
            'state': 'draft',
            'payslip_id': False,
            'approval_user_id': False,
            'approval_date': False,
            'is_massive': False,
            'massive_group_id': False,
            'original_novelty_id': False
        })
        return super().copy(default)

class HrNoveltyMassiveGroup(models.Model):
    _name = 'hr.novelty.massive.group'
    _description = 'Grupo de Novedades Masivas'
    _order = 'date desc, id desc'

    name = fields.Char('Nombre', required=True)
    date = fields.Date('Fecha', required=True)
    novelty_ids = fields.One2many(
        'hr.novelties.different.concepts',
        'massive_group_id',
        'Novedades'
    )
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('confirmed', 'Confirmado'),
        ('cancelled', 'Cancelado')
    ], string='Estado', default='draft')
    total_amount = fields.Float(
        'Monto Total',
        compute='_compute_total_amount',
        store=True
    )
    employee_count = fields.Integer(
        'Total Empleados',
        compute='_compute_employee_count',
        store=True
    )
    company_id = fields.Many2one(
        'res.company',
        string='Compañía',
        default=lambda self: self.env.company
    )
    created_by_id = fields.Many2one(
        'res.users',
        string='Creado por',
        default=lambda self: self.env.user,
        readonly=True
    )
    creation_date = fields.Datetime(
        'Fecha de Creación',
        default=fields.Datetime.now,
        readonly=True
    )

    @api.depends('novelty_ids.amount')
    def _compute_total_amount(self):
        for record in self:
            record.total_amount = sum(record.novelty_ids.mapped('amount'))

    @api.depends('novelty_ids')
    def _compute_employee_count(self):
        for record in self:
            record.employee_count = len(record.novelty_ids.mapped('employee_id'))

    def action_confirm(self):
        self.write({'state': 'confirmed'})

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_draft(self):
        self.write({'state': 'draft'})

class HrNoveltyRejectWizard(models.TransientModel):
    _name = 'hr.novelty.reject.wizard'
    _description = 'Wizard para Rechazo de Novedad'

    novelty_id = fields.Many2one(
        'hr.novelties.different.concepts',
        'Novedad',
        required=True
    )
    reject_reason = fields.Text(
        'Motivo de Rechazo',
        required=True
    )

    def action_reject(self):
        self.ensure_one()
        if not self.novelty_id:
            raise UserError(_('No se encontró la novedad a rechazar'))

        if self.novelty_id.state != 'pending':
            raise UserError(_('Solo se pueden rechazar novedades pendientes de aprobación'))

        self.novelty_id.write({
            'state': 'rejected'
        })

        self.novelty_id.message_post(
            body=_('Novedad rechazada. Motivo: %s') % self.reject_reason,
            subtype_xmlid='mail.mt_note'
        )

        return {'type': 'ir.actions.act_window_close'}

class HrNoveltyTransferWizard(models.TransientModel):
    _name = 'hr.novelty.transfer.wizard'
    _description = 'Wizard para Traslado de Novedad'

    novelty_id = fields.Many2one(
        'hr.novelties.different.concepts',
        'Novedad Original',
        required=True
    )
    transfer_date = fields.Date(
        'Fecha de Traslado',
        required=True
    )
    transfer_reason = fields.Text(
        'Motivo de Traslado',
        required=True
    )
    keep_original = fields.Boolean(
        'Mantener Novedad Original',
        help='Si está marcado, la novedad original no se cancelará'
    )
    adjust_amount = fields.Boolean(
        'Ajustar Monto'
    )
    new_amount = fields.Float(
        'Nuevo Monto',
        default=0.0
    )

    @api.onchange('novelty_id')
    def _onchange_novelty_id(self):
        if self.novelty_id:
            self.new_amount = self.novelty_id.amount

    @api.constrains('transfer_date')
    def _check_transfer_date(self):
        for record in self:
            if record.transfer_date and record.novelty_id:
                if record.transfer_date <= record.novelty_id.date:
                    raise ValidationError(_('La fecha de traslado debe ser posterior a la fecha de la novedad original'))

    def action_transfer(self):
        self.ensure_one()
        if not self.novelty_id:
            raise UserError(_('No se encontró la novedad a trasladar'))

        # Validar estado de la novedad
        if self.novelty_id.state != 'approved':
            raise UserError(_('Solo se pueden trasladar novedades aprobadas'))

        # Crear nueva novedad
        new_novelty = self.novelty_id.copy({
            'date': self.transfer_date,
            'amount': self.new_amount if self.adjust_amount else self.novelty_id.amount,
            'description': f"{self.novelty_id.description or ''} (Trasladado)",
            'original_novelty_id': self.novelty_id.id,
            'transfer_date': self.transfer_date,
            'state': 'draft'
        })

        # Actualizar novedad original si es necesario
        if not self.keep_original:
            self.novelty_id.write({
                'state': 'cancelled'
            })

        # Registrar mensaje en ambas novedades
        message = _(
            'Novedad trasladada a fecha %s. Motivo: %s'
        ) % (self.transfer_date, self.transfer_reason)
        
        self.novelty_id.message_post(
            body=message,
            subtype_xmlid='mail.mt_note'
        )
        
        new_novelty.message_post(
            body=_('Novedad creada por traslado de novedad %s') % self.novelty_id.name,
            subtype_xmlid='mail.mt_note'
        )

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hr.novelties.different.concepts',
            'res_id': new_novelty.id,
            'view_mode': 'form',
            'target': 'current',
        }



class HrNoveltyMassiveWizard(models.TransientModel):
    _name = 'hr.novelty.massive.wizard'
    _description = 'Asistente de Novedades Masivas'

    name = fields.Char(
        'Descripción', 
        required=True,
        help='Descripción que se usará para todas las novedades'
    )
    date = fields.Date(
        'Fecha', 
        required=True,
        default=fields.Date.context_today
    )
    salary_rule_id = fields.Many2one(
        'hr.salary.rule', 
        string='Regla salarial',
        required=True,
        domain=[('novedad_ded', '=', 'Noved')]
    )
    amount = fields.Float(
        'Valor', 
        required=True
    )
    partner_id = fields.Many2one(
        'hr.employee.entities', 
        'Entidad'
    )
    salary_structure_ids = fields.Many2many(
        'hr.payroll.structure',
        string='Estructuras Salariales'
    )
    
    # Campos para selección de empleados
    selection_type = fields.Selection([
        ('all', 'Todos los Empleados'),
        ('department', 'Por Departamento'),
        ('job', 'Por Cargo'),
        ('specific', 'Empleados Específicos')
    ], string='Tipo de Selección', default='specific', required=True)
    
    department_ids = fields.Many2many(
        'hr.department',
        string='Departamentos'
    )
    job_ids = fields.Many2many(
        'hr.job',
        string='Cargos'
    )
    employee_ids = fields.Many2many(
        'hr.employee',
        string='Empleados'
    )

    @api.onchange('selection_type')
    def _onchange_selection_type(self):
        """Limpiar selecciones previas al cambiar el tipo"""
        self.department_ids = False
        self.job_ids = False
        self.employee_ids = False

    def _get_employees(self):
        """
        Obtener empleados según el tipo de selección
        """
        domain = [('contract_id.state', '=', 'open')]  # Solo empleados con contrato activo
        
        if self.selection_type == 'all':
            return self.env['hr.employee'].search(domain)
            
        elif self.selection_type == 'department':
            if not self.department_ids:
                raise UserError(_('Debe seleccionar al menos un departamento'))
            domain.append(('department_id', 'in', self.department_ids.ids))
            
        elif self.selection_type == 'job':
            if not self.job_ids:
                raise UserError(_('Debe seleccionar al menos un cargo'))
            domain.append(('job_id', 'in', self.job_ids.ids))
            
        elif self.selection_type == 'specific':
            if not self.employee_ids:
                raise UserError(_('Debe seleccionar al menos un empleado'))
            return self.employee_ids.filtered(lambda e: e.contract_id.state == 'open')
            
        return self.env['hr.employee'].search(domain)

    def _check_existing_novelties(self, employees):
        """
        Verificar si ya existen novedades para los empleados en la fecha
        """
        existing = self.env['hr.novelties.different.concepts'].search([
            ('employee_id', 'in', employees.ids),
            ('salary_rule_id', '=', self.salary_rule_id.id),
            ('date', '=', self.date),
            ('state', '!=', 'cancelled')
        ])
        
        if existing:
            employee_names = existing.mapped('employee_id.name')
            raise ValidationError(_(
                'Ya existen novedades para los siguientes empleados en la fecha seleccionada:\n%s'
            ) % '\n'.join(employee_names))

    def action_create_massive_novelties(self):
        """
        Crear novedades masivas
        """
        self.ensure_one()
        employees = self._get_employees()
        
        if not employees:
            raise UserError(_('No se encontraron empleados que cumplan con los criterios seleccionados'))
            
        self._check_existing_novelties(employees)
        
        massive_group = self.env['hr.novelty.massive.group'].create({
            'name': self.name,
            'date': self.date
        })
        
        novelties_vals = []
        for employee in employees:
            novelties_vals.append({
                'name': '/',
                'employee_id': employee.id,
                'salary_rule_id': self.salary_rule_id.id,
                'date': self.date,
                'amount': self.amount,
                'description': self.name,
                'partner_id': self.partner_id.id,
                'salary_structure_ids': [(6, 0, self.salary_structure_ids.ids)],
                'is_massive': True,
                'massive_group_id': massive_group.id,
                'state': 'draft'
            })
        
        novelties = self.env['hr.novelties.different.concepts'].create(novelties_vals)
        
        message = _(
            'Se han creado %s novedades masivas.\n'
            'Puede verlas en el grupo de novedades masivas "%s"'
        ) % (len(novelties), massive_group.name)
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Novedades Creadas'),
                'message': message,
                'sticky': False,
                'next': {
                    'type': 'ir.actions.act_window',
                    'res_model': 'hr.novelty.massive.group',
                    'res_id': massive_group.id,
                    'view_mode': 'form',
                }
            }
        }
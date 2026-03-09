from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from datetime import datetime, timedelta


class GlosaMotivo(models.Model):
    _name = 'glosa.motivo'
    _description = 'Motivos de Glosa Médica'
    _order = 'code'
    
    code = fields.Char("Código", required=True, index=True)
    name = fields.Char("Descripción", required=True)
    category = fields.Selection([
        ('facturacion', 'Facturación'),
        ('tarifas', 'Tarifas'),
        ('soportes', 'Soportes'),
        ('autorizacion', 'Autorización'),
        ('cobertura', 'Cobertura'),
        ('pertinencia', 'Pertinencia'),
        ('devolucion', 'Devolución/Respuesta'),
        ('general', 'General')
    ], string="Categoría", required=True)
    active = fields.Boolean(default=True)
    
    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'El código de motivo de glosa debe ser único.')
    ]
    
    def name_get(self):
        result = []
        for record in self:
            result.append((record.id, f"{record.code} - {record.name}"))
        return result

class GlosaEtapa(models.Model):
    _name = 'glosa.etapa'
    _description = 'Etapas del Proceso de Glosa'
    _order = 'sequence'
    
    name = fields.Char("Nombre", required=True)
    sequence = fields.Integer("Secuencia", default=10)
    descripcion = fields.Text("Descripción")
    fold = fields.Boolean("Plegado en Kanban")
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('recepcion', 'Recepción'),
        ('clasificacion', 'Clasificación'),
        ('revision', 'Revisión'),
        ('conciliacion', 'Conciliación'),
        ('resuelto', 'Resuelto'),
        ('aceptado', 'Aceptado'),
        ('rechazado', 'Rechazado'),
        ('parcial', 'Parcialmente Aceptado'),
        ('cancelado', 'Cancelado')
    ], string="Estado")
    requiere_motivo = fields.Boolean("Requiere Motivo", help="Si está marcado, se requiere un motivo para avanzar a esta etapa")
    requiere_respuesta = fields.Boolean("Requiere Respuesta", help="Si está marcado, se requiere una respuesta para avanzar a esta etapa")
    requiere_nota_cierre = fields.Boolean("Requiere Nota de Cierre", help="Si está marcado, se requiere una nota de cierre para avanzar a esta etapa")
    es_estado_final = fields.Boolean("Es Estado Final", help="Indica si esta etapa representa un estado final en el proceso de glosa")
    permite_nota_credito = fields.Boolean("Permite Nota de Crédito", help="Indica si en esta etapa se puede generar una nota de crédito")
    
    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'El nombre de la etapa debe ser único.')
    ]
    
class GlosaMedica(models.Model):
    _name = 'glosa.medica'
    _description = 'Glosa Médica'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'
    
    name = fields.Char("Número de Glosa", readonly=True, copy=False, default=lambda self: _('Nuevo'))
    partner_id = fields.Many2one(related="invoice_id.commercial_partner_id", string="Cliente", store=True, readonly=True)
    patient_id = fields.Many2one('hms.patient', string="Paciente", required=True, tracking=True)
    
    invoice_id = fields.Many2one('account.move', string="Factura", tracking=True)
    invoice_line_id = fields.Many2one('account.move.line', string="Línea de Factura", tracking=True)
    is_line_glosa = fields.Boolean("¿Glosa de línea?", compute="_compute_is_line_glosa", store=True)

    def _auto_init(self):
        """Crear índices parciales para campos booleanos computados"""
        super()._auto_init()

        from odoo.tools.sql import index_exists

        # Índice parcial para glosas de línea (solo TRUE) - búsquedas frecuentes
        if not index_exists(self.env.cr, 'glosa_medica_is_line_idx'):
            self.env.cr.execute("""
                CREATE INDEX glosa_medica_is_line_idx
                          ON glosa_medica(invoice_id, state)
                       WHERE is_line_glosa = true
            """)

    total_factura = fields.Monetary(related="invoice_id.amount_total", string="Total Factura", store=True, readonly=True)
    monto_residual = fields.Monetary(related="invoice_id.amount_residual", string="Monto Residual", store=True, readonly=True)
    
    service_date = fields.Date("Fecha del Servicio", required=True, tracking=True)
    amount = fields.Monetary("Monto Glosado", required=True, tracking=True)
    currency_id = fields.Many2one('res.currency', string="Moneda", 
                                  compute="_compute_currency_id", store=True, readonly=True)
    
    motivo_id = fields.Many2one('glosa.motivo', string="Motivo de Glosa", tracking=True)
    motivo_code = fields.Char(related="motivo_id.code", string="Código de Motivo", store=True)
    motivo_category = fields.Selection(related="motivo_id.category", string="Categoría", store=True)
    
    etapa_id = fields.Many2one('glosa.etapa', string="Etapa", 
                               default=lambda self: self._get_default_etapa(),
                               group_expand='_read_group_etapa_ids', tracking=True)
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('recepcion', 'Recepción'),
        ('clasificacion', 'Clasificación'),
        ('revision', 'Revisión'),
        ('conciliacion', 'Conciliación'),
        ('resuelto', 'Resuelto'),
        ('aceptado', 'Aceptado'),
        ('rechazado', 'Rechazado'),
        ('parcial', 'Parcialmente Aceptado'),
        ('cancelado', 'Cancelado')
    ], string="Estado", compute="_compute_state", store=True)
    
    result = fields.Selection([
        ('favorable', 'Favorable (Glosa Rechazada)'),
        ('parcial', 'Parcialmente Favorable'),
        ('desfavorable', 'Desfavorable (Glosa Aceptada)'),
        ('pending', 'Pendiente')
    ], string="Resultado", default='pending', tracking=True)
    
    close_note = fields.Html("Nota de Cierre")
    
    deadline_date = fields.Date("Fecha Límite de Respuesta", compute='_compute_deadline', store=True)
    response_date = fields.Date("Fecha de Respuesta")
    days_remaining = fields.Integer("Días Restantes", compute='_compute_days_remaining')
    
    comments = fields.Html("Comentarios")
    response = fields.Html("Respuesta a la Glosa")
    
    company_id = fields.Many2one('res.company', string="Compañía", 
                                default=lambda self: self.env.company)
    user_id = fields.Many2one('res.users', string="Responsable", 
                             default=lambda self: self.env.user, tracking=True)
    
    credit_note_id = fields.Many2one('account.move', string="Nota de Crédito", 
                                     domain=[('move_type', '=', 'out_refund')], 
                                     readonly=True, copy=False)
    credit_note_state = fields.Selection([
        ('draft', 'Borrador'),
        ('posted', 'Publicada'),
        ('cancel', 'Cancelada')
    ], string="Estado de Nota de Crédito", compute="_compute_credit_note_state", store=True)
    
    is_conciliated = fields.Boolean("Conciliada", default=False, tracking=True)
    conciliation_date = fields.Date("Fecha de Conciliación")
    conciliation_details = fields.Html("Detalles de la Conciliación")
    
    accepted_percentage = fields.Float("Porcentaje Aceptado (%)", default=0.0, tracking=True)
    accepted_amount = fields.Monetary("Monto Aceptado", tracking=True)
    rejected_amount = fields.Monetary("Monto Rechazado", tracking=True)
    
    active = fields.Boolean(default=True)
    
    create_date = fields.Datetime("Fecha de Creación", readonly=True)
    write_date = fields.Datetime("Fecha de Modificación", readonly=True)
    
    treatment_id = fields.Many2one('hms.treatment', string='Tratamiento')
    date_start = fields.Date(string='Fecha Inicio')
    date_end = fields.Date(string='Fecha Fin')
    authorization_number = fields.Char(string='Número de Autorización', 
                                     related="treatment_id.authorization_number", store=True, readonly=False)
    
    contract_id = fields.Many2one('customer.contract', string='Contrato', 
                                related="invoice_id.contract_id", store=True, readonly=False)
    
    @api.depends('invoice_id', 'invoice_line_id')
    def _compute_is_line_glosa(self):
        for record in self:
            record.is_line_glosa = bool(record.invoice_line_id)
    
    @api.depends('invoice_id', 'invoice_line_id')
    def _compute_currency_id(self):
        for record in self:
            if record.invoice_line_id:
                record.currency_id = record.invoice_line_id.currency_id
            elif record.invoice_id:
                record.currency_id = record.invoice_id.currency_id
            else:
                record.currency_id = self.env.company.currency_id
    
    @api.depends('etapa_id')
    def _compute_state(self):
        for record in self:
            if record.etapa_id:
                record.state = record.etapa_id.state
            else:
                record.state = 'draft'
    
    @api.depends('credit_note_id')
    def _compute_credit_note_state(self):
        for record in self:
            if record.credit_note_id:
                record.credit_note_state = record.credit_note_id.state
            else:
                record.credit_note_state = False
    
    @api.model
    def _get_default_etapa(self):
        return self.env['glosa.etapa'].search([('state', '=', 'recepcion')], limit=1).id
    
    @api.model
    def _read_group_etapa_ids(self, etapas, domain, order):
        return self.env['glosa.etapa'].search([], order='sequence')
    
    @api.depends('create_date')
    def _compute_deadline(self):
        for record in self:
            if record.create_date:
                create_date = record.create_date.date()
                record.deadline_date = create_date + timedelta(days=15)
            else:
                record.deadline_date = False
    
    @api.depends('deadline_date')
    def _compute_days_remaining(self):
        today = fields.Date.today()
        for record in self:
            if record.deadline_date:
                if record.deadline_date >= today:
                    record.days_remaining = (record.deadline_date - today).days
                else:
                    record.days_remaining = -1 * (today - record.deadline_date).days
            else:
                record.days_remaining = 0
    
    @api.constrains('amount')
    def _check_amount(self):
        for record in self:
            if record.amount <= 0:
                raise ValidationError(_("El monto glosado debe ser mayor que cero."))
            
            if record.is_line_glosa and record.invoice_line_id and record.amount > record.invoice_line_id.price_total:
                raise ValidationError(_("El monto glosado no puede ser mayor que el total de la línea de factura."))
            elif not record.is_line_glosa and record.invoice_id and record.amount > record.invoice_id.amount_total:
                raise ValidationError(_("El monto glosado no puede ser mayor que el total de la factura."))
    
    @api.constrains('accepted_percentage')
    def _check_accepted_percentage(self):
        for record in self:
            if record.accepted_percentage < 0 or record.accepted_percentage > 100:
                raise ValidationError(_("El porcentaje aceptado debe estar entre 0 y 100."))
    
    @api.constrains('invoice_id', 'invoice_line_id')
    def _check_invoice_relation(self):
        for record in self:
            if record.invoice_line_id and record.invoice_id and record.invoice_line_id.move_id != record.invoice_id:
                raise ValidationError(_("La línea de factura debe pertenecer a la factura seleccionada."))
            
            if not record.invoice_id and not record.invoice_line_id:
                raise ValidationError(_("Debe seleccionar una factura o una línea de factura."))
    
    @api.model
    def create(self, vals):
        if vals.get('name', _('Nuevo')) == _('Nuevo'):
            vals['name'] = self.env['ir.sequence'].next_by_code('glosa.medica') or _('Nuevo')
        
        if vals.get('invoice_line_id') and not vals.get('invoice_id'):
            line = self.env['account.move.line'].browse(vals['invoice_line_id'])
            vals['invoice_id'] = line.move_id.id
        
        if 'accepted_percentage' in vals and not 'accepted_amount' in vals:
            amount = vals.get('amount', 0)
            accepted_percentage = vals.get('accepted_percentage', 0)
            vals['accepted_amount'] = amount * (accepted_percentage / 100.0)
            vals['rejected_amount'] = amount - vals['accepted_amount']
        
        return super(GlosaMedica, self).create(vals)
    
    @api.onchange('invoice_id')
    def _onchange_invoice_id(self):
        if self.invoice_id:
            if hasattr(self.invoice_id, 'patient_id') and self.invoice_id.patient_id:
                self.patient_id = self.invoice_id.patient_id.id
            
            if hasattr(self.invoice_id, 'treatment_id') and self.invoice_id.treatment_id:
                self.treatment_id = self.invoice_id.treatment_id.id
            
            self.invoice_line_id = False
    
    @api.onchange('invoice_line_id')
    def _onchange_invoice_line_id(self):
        if self.invoice_line_id:
            self.invoice_id = self.invoice_line_id.move_id.id
            
            if hasattr(self.invoice_line_id, 'patient_id') and self.invoice_line_id.patient_id:
                self.patient_id = self.invoice_line_id.patient_id.id
                
            if hasattr(self.invoice_line_id, 'treatment_id') and self.invoice_line_id.treatment_id:
                self.treatment_id = self.invoice_line_id.treatment_id.id
    
    @api.onchange('accepted_percentage', 'amount')
    def _onchange_accepted_percentage(self):
        if self.accepted_percentage == 0:
            self.result = 'favorable'
            self.accepted_amount = 0
            self.rejected_amount = self.amount
        elif self.accepted_percentage == 100:
            self.result = 'desfavorable'
            self.accepted_amount = self.amount
            self.rejected_amount = 0
        elif self.accepted_percentage > 0:
            self.result = 'parcial'
            self.accepted_amount = self.amount * (self.accepted_percentage / 100.0)
            self.rejected_amount = self.amount - self.accepted_amount
        else:
            self.result = 'pending'
    
    @api.onchange('accepted_amount')
    def _onchange_accepted_amount(self):
        if self.amount and self.amount > 0:
            self.accepted_percentage = (self.accepted_amount / self.amount) * 100
            self.rejected_amount = self.amount - self.accepted_amount
            
            if self.accepted_amount == 0:
                self.result = 'favorable'
            elif self.accepted_amount == self.amount:
                self.result = 'desfavorable'
            elif self.accepted_amount > 0:
                self.result = 'parcial'
    
    @api.onchange('rejected_amount')
    def _onchange_rejected_amount(self):
        if self.amount and self.amount > 0:
            self.accepted_amount = self.amount - self.rejected_amount
            self.accepted_percentage = (self.accepted_amount / self.amount) * 100
            
            if self.rejected_amount == self.amount:
                self.result = 'favorable'
            elif self.rejected_amount == 0:
                self.result = 'desfavorable'
            elif self.rejected_amount > 0:
                self.result = 'parcial'
    
    def write(self, vals):
        if 'etapa_id' in vals:
            nueva_etapa = self.env['glosa.etapa'].browse(vals['etapa_id'])
            
            if nueva_etapa.requiere_motivo and not (self.motivo_id or vals.get('motivo_id')):
                raise UserError(_("Se requiere especificar un motivo de glosa para avanzar a la etapa %s") % nueva_etapa.name)
            
            if nueva_etapa.requiere_respuesta and not (self.response or vals.get('response')):
                raise UserError(_("Se requiere registrar una respuesta para avanzar a la etapa %s") % nueva_etapa.name)
            
            if nueva_etapa.state == 'conciliacion' and self.state != 'conciliacion':
                vals['conciliation_date'] = fields.Date.today()
            
            if nueva_etapa.state == 'resuelto' and self.state != 'resuelto':
                vals['is_conciliated'] = True
                
                if not self.close_note and not vals.get('close_note'):
                    raise UserError(_("Debe proporcionar una nota de cierre para resolver la glosa."))
                
                if self.result == 'pending' and not vals.get('result'):
                    raise UserError(_("Debe especificar el resultado de la glosa (favorable, parcial o desfavorable)."))
        
        if vals.get('invoice_line_id') and not vals.get('invoice_id'):
            line = self.env['account.move.line'].browse(vals['invoice_line_id'])
            vals['invoice_id'] = line.move_id.id
        
        if 'result' in vals and 'accepted_percentage' not in vals and 'accepted_amount' not in vals:
            if vals['result'] == 'favorable':
                vals['accepted_percentage'] = 0.0
                vals['accepted_amount'] = 0.0
                vals['rejected_amount'] = self.amount
            elif vals['result'] == 'desfavorable':
                vals['accepted_percentage'] = 100.0
                vals['accepted_amount'] = self.amount
                vals['rejected_amount'] = 0.0
        
        if 'amount' in vals and ('accepted_percentage' in vals or 'accepted_amount' in vals):
            amount = vals.get('amount', self.amount)
            if 'accepted_percentage' in vals:
                accepted_percentage = vals.get('accepted_percentage', 0)
                vals['accepted_amount'] = amount * (accepted_percentage / 100.0)
                vals['rejected_amount'] = amount - vals['accepted_amount']
            elif 'accepted_amount' in vals:
                accepted_amount = vals.get('accepted_amount', 0)
                vals['accepted_percentage'] = (accepted_amount / amount) * 100 if amount else 0
                vals['rejected_amount'] = amount - accepted_amount
                
        return super(GlosaMedica, self).write(vals)
    
    def action_generate_credit_note(self):
        self.ensure_one()
        if self.credit_note_id:
            raise UserError(_("Ya existe una nota de crédito generada para esta glosa."))
        
        if not self.is_conciliated:
            raise UserError(_("La glosa debe estar conciliada antes de generar una nota de crédito."))
        
        if self.result in ['desfavorable', 'parcial'] and self.accepted_amount <= 0:
            raise UserError(_("Para generar una nota de crédito, debe especificar un monto aceptado mayor que cero."))
        
        return {
            'name': _('Generar Nota de Crédito'),
            'type': 'ir.actions.act_window',
            'res_model': 'generar.nota.credito.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_glosa_id': self.id,
                'default_amount': self.accepted_amount,
            },
        }
    
    def action_view_credit_note(self):
        self.ensure_one()
        if not self.credit_note_id:
            raise UserError(_("No hay nota de crédito asociada a esta glosa."))
        
        return {
            'name': _('Nota de Crédito'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self.credit_note_id.id,
            'view_mode': 'form',
        }
    
    def action_cancel(self):
        cancelado_etapa = self.env['glosa.etapa'].search([('state', '=', 'cancelado')], limit=1)
        if not cancelado_etapa:
            raise UserError(_("No se encontró la etapa 'Cancelado' en el sistema."))
        
        for record in self:
            record.write({
                'etapa_id': cancelado_etapa.id,
                'close_note': record.close_note or _("Glosa cancelada el %s") % fields.Date.today()
            })
    
    @api.model
    def _cron_check_deadlines(self):
        soon_to_expire = self.search([
            ('state', 'in', ['recepcion', 'clasificacion', 'revision']),
            ('deadline_date', '!=', False),
            ('days_remaining', '<=', 3),
            ('days_remaining', '>=', 0)
        ])
        
        for glosa in soon_to_expire:
            glosa.activity_schedule(
                'mail.mail_activity_data_todo',
                summary=_("Plazo de respuesta a punto de vencer"),
                note=_("La glosa %s tiene %s días restantes para responder.") % (glosa.name, glosa.days_remaining),
                user_id=glosa.user_id.id,
                date_deadline=glosa.deadline_date
            )
        
        expired = self.search([
            ('state', 'in', ['recepcion', 'clasificacion', 'revision']),
            ('deadline_date', '!=', False),
            ('days_remaining', '<', 0)
        ])
        
        for glosa in expired:
            glosa.activity_schedule(
                'mail.mail_activity_data_warning',
                summary=_("Plazo de respuesta vencido"),
                note=_("La glosa %s tiene el plazo de respuesta vencido por %s días.") % (glosa.name, abs(glosa.days_remaining)),
                user_id=glosa.user_id.id,
                date_deadline=fields.Date.today()
            )

class GenerarNotaCreditoWizard(models.TransientModel):
    _name = 'generar.nota.credito.wizard'
    _description = 'Asistente para Generar Nota de Crédito por Glosa'
    
    glosa_id = fields.Many2one('glosa.medica', string="Glosa", required=True)
    invoice_id = fields.Many2one('account.move', string="Factura Original", related="glosa_id.invoice_id", readonly=True)
    invoice_line_id = fields.Many2one('account.move.line', string="Línea de Factura", related="glosa_id.invoice_line_id", readonly=True)
    is_line_glosa = fields.Boolean(related='glosa_id.is_line_glosa', readonly=True)
    
    amount = fields.Monetary("Monto a Devolver", required=True)
    total_factura = fields.Monetary("Total Factura", related="glosa_id.total_factura", readonly=True)
    accepted_amount = fields.Monetary("Monto Aceptado", related="glosa_id.accepted_amount", readonly=True)
    currency_id = fields.Many2one('res.currency', string="Moneda", related="glosa_id.currency_id", readonly=True)
    date = fields.Date("Fecha", default=fields.Date.today, required=True)
    motivo = fields.Text("Motivo", required=True, default=lambda self: self._get_default_motivo())
    journal_id = fields.Many2one('account.journal', string="Diario", 
                               domain=[('type', '=', 'sale')], required=True)
    result = fields.Selection(related="glosa_id.result", string="Resultado de la Glosa", readonly=True)
    close_note = fields.Html(related="glosa_id.close_note", string="Nota de Cierre", readonly=True)
    
    generate_rips = fields.Boolean(string="Generar RIPS", default=False)
    rips_code = fields.Char(string="Código RIPS", help="Código para el registro RIPS")
    
    @api.onchange('glosa_id')
    def _onchange_glosa_id(self):
        if self.glosa_id:
            self.amount = self.glosa_id.accepted_amount
    
    def _get_default_motivo(self):
        glosa_id = self.env.context.get('default_glosa_id')
        if glosa_id:
            glosa = self.env['glosa.medica'].browse(glosa_id)
            if glosa.motivo_id and glosa.result:
                result_text = dict(glosa._fields['result'].selection).get(glosa.result, '')
                return f"Nota de crédito por glosa {glosa.name}: {glosa.motivo_id.name} - Resultado: {result_text}"
        return "Nota de crédito por glosa médica"
    
    def action_generate_credit_note(self):
        self.ensure_one()
        
        if self.amount <= 0:
            raise UserError(_("El monto a devolver debe ser mayor que cero."))
        
        if self.amount > self.total_factura:
            raise UserError(_("El monto a devolver no puede ser mayor que el total de la factura original."))
        
        if self.amount > self.accepted_amount and self.glosa_id.result != 'desfavorable':
            raise UserError(_("El monto a devolver no debería ser mayor que el monto aceptado de la glosa (%s).") % 
                        self.accepted_amount)
        
        default_values = {
            'move_type': 'out_refund',
            'reversed_entry_id': self.invoice_id.id,
            'ref': self.motivo,
            'invoice_date': self.date,
            'invoice_origin': self.invoice_id.name,
            'journal_id': self.journal_id.id,
            'partner_id': self.invoice_id.partner_id.id,
        }
        
        for field in ['patient_id', 'physician_id', 'treatment_id', 'invoice_type', 
                    'authorization_number', 'contract_id']:
            if hasattr(self.invoice_id, field):
                value = getattr(self.invoice_id, field)
                if hasattr(value, 'id'):
                    default_values[field] = value.id
                else:
                    default_values[field] = value
        
        reverse_moves = self.invoice_id.with_context(
            move_reverse_cancel=False,
            skip_invoice_sync=True
        )._reverse_moves([default_values])
        
        reverse_move = reverse_moves[0]
        

        # else:
        #     factor = self.amount / self.invoice_id.amount_total
            
        #     for line in reverse_move.invoice_line_ids.filtered(lambda l: l.display_type == 'product'):
        #         line.write({
        #             'quantity': line.quantity,
        #             'price_unit': line.price_unit * factor,
        #         })
        
        
        self.glosa_id.write({
            'credit_note_id': reverse_move.id
        })
        
        if self.generate_rips and hasattr(reverse_move, 'rips_generated'):
            reverse_move.write({
                'rips_generated': True,
                'rips_json': f'{{"codigo": "{self.rips_code}", "glosa": "{self.glosa_id.name}", "motivo": "{self.glosa_id.motivo_id.code}"}}'
            })
        
        self.glosa_id.message_post(
            body=_("Se ha generado la nota de crédito %s por un monto de %s %s") % 
                (reverse_move.name, self.amount, self.currency_id.name),
            subtype_id=self.env.ref('mail.mt_note').id
        )
        
        result_to_state = {
            'favorable': 'rechazado',
            'desfavorable': 'aceptado',
            'parcial': 'parcial'
        }
        
        if not self.glosa_id.etapa_id.es_estado_final:
            state = result_to_state.get(self.glosa_id.result, 'resuelto')
            etapa = self.env['glosa.etapa'].search([('state', '=', state)], limit=1)
            if etapa:
                self.glosa_id.write({'etapa_id': etapa.id})
        
        return {
            'name': _('Nota de Crédito'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': reverse_move.id,
            'view_mode': 'form',
        }

class AccountMove(models.Model):
    _inherit = 'account.move'

    glosa_ids = fields.One2many('glosa.medica', 'invoice_id', string="Glosas Médicas")
    glosa_count = fields.Integer(string="Número de Glosas", compute='_compute_glosa_count')
    glosa_total = fields.Monetary(string="Total Glosado", compute='_compute_glosa_total', store=True)

    def _auto_init(self):
        """Crear índices parciales para campos booleanos de glosas"""
        super()._auto_init()

        from odoo.tools.sql import index_exists

        # Índice parcial para facturas con glosas (solo TRUE)
        if not index_exists(self.env.cr, 'account_move_has_glosa_idx'):
            self.env.cr.execute("""
                CREATE INDEX account_move_has_glosa_idx
                          ON account_move(partner_id, glosa_state)
                       WHERE has_glosa = true
            """)
    
    glosa_state = fields.Selection([
        ('no_glosa', 'Sin Glosa'),
        ('glosa_pendiente', 'Glosa Pendiente'),
        ('glosa_respondida', 'Glosa Respondida'),
        ('glosa_conciliada', 'Glosa Conciliada'),
        ('glosa_aceptada', 'Glosa Aceptada'),
        ('glosa_rechazada', 'Glosa Rechazada'),
        ('glosa_parcial', 'Glosa Parcialmente Aceptada'),
        ('glosa_resuelta', 'Glosa Resuelta'),
    ], string="Estado de Glosa", compute='_compute_glosa_state', store=True)
   
    date_start = fields.Date(string='Fecha Inicio', default=fields.Date.today)
    date_end = fields.Date(string='Fecha Fin')
    
    invoice_type = fields.Selection([
        ('insurance', 'Aseguradora'),
        ('copay', 'Copago'),
        ('regular', 'Regular')
    ], string='Tipo de Factura', default='regular')
    
    patient_id = fields.Many2one('hms.patient', string='Paciente')
    contract_id = fields.Many2one('customer.contract', string='Contrato')
    authorization_number = fields.Char(string='Número de Autorización')
    
    copay_invoice_id = fields.Many2one('account.move', string='Factura de Copago')
    insurance_invoice_id = fields.Many2one('account.move', string='Factura de Aseguradora')
    finding = fields.Text(string='Hallazgos')    
    current_glosa_id = fields.Many2one('glosa.medica', string="Glosa Actual", compute='_compute_current_glosa')
    current_glosa_etapa = fields.Char(related='current_glosa_id.etapa_id.name', string="Etapa de Glosa Actual", store=True)
    has_glosa = fields.Boolean(string="Tiene Glosa", compute='_compute_has_glosa', store=True)
    glosa_result = fields.Selection(related='current_glosa_id.result', string="Resultado de Glosa", store=True)
    glosa_close_note = fields.Html(related='current_glosa_id.close_note', string="Nota de Cierre de Glosa", readonly=True)
    
    @api.depends('glosa_ids')
    def _compute_glosa_count(self):
        for record in self:
            record.glosa_count = len(record.glosa_ids.filtered(lambda g: g.active))
    
    @api.depends('glosa_ids.amount', 'glosa_ids.active')
    def _compute_glosa_total(self):
        for record in self:
            record.glosa_total = sum(record.glosa_ids.filtered(lambda g: g.active).mapped('amount'))
    
    @api.depends('invoice_type')
    def _compute_invoice_types(self):
        for record in self:
            record.is_insurance_invoice = record.invoice_type == 'insurance'
            record.is_copay_invoice = record.invoice_type == 'copay'
    
    @api.depends('glosa_ids.state', 'glosa_ids.active', 'glosa_ids.result')
    def _compute_glosa_state(self):
        for record in self:
            if not record.glosa_ids or not record.glosa_ids.filtered(lambda g: g.active):
                record.glosa_state = 'no_glosa'
                continue
            
            active_glosas = record.glosa_ids.filtered(lambda g: g.active)
            
            state_map = {
                'recepcion': 'glosa_pendiente',
                'clasificacion': 'glosa_pendiente',
                'revision': 'glosa_respondida',
                'conciliacion': 'glosa_conciliada',
                'resuelto': 'glosa_resuelta',
                'aceptado': 'glosa_aceptada',
                'rechazado': 'glosa_rechazada',
                'parcial': 'glosa_parcial',
                'cancelado': 'no_glosa'
            }
            
            priority_order = [
                'glosa_pendiente',
                'glosa_respondida',
                'glosa_conciliada',
                'glosa_aceptada',
                'glosa_parcial',
                'glosa_rechazada',
                'glosa_resuelta',
                'no_glosa'
            ]
            
            glosa_states = [state_map.get(g.state, 'no_glosa') for g in active_glosas]
            
            for state in priority_order:
                if state in glosa_states:
                    record.glosa_state = state
                    break
            else:
                record.glosa_state = 'no_glosa'
    
    @api.depends('glosa_ids.active', 'glosa_ids.create_date')
    def _compute_current_glosa(self):
        for record in self:
            active_glosas = record.glosa_ids.filtered(lambda g: g.active)
            if active_glosas:
                record.current_glosa_id = active_glosas.sorted('create_date', reverse=True)[0]
            else:
                record.current_glosa_id = False
    
    @api.depends('glosa_ids')
    def _compute_has_glosa(self):
        for record in self:
            record.has_glosa = bool(record.glosa_ids.filtered(lambda g: g.active))
    
    def action_view_glosas(self):
        """Acción para ver las glosas asociadas a la factura"""
        self.ensure_one()
        return {
            'name': _('Glosas'),
            'type': 'ir.actions.act_window',
            'res_model': 'glosa.medica',
            'view_mode': 'tree,form',
            'domain': [('invoice_id', '=', self.id)],
            'context': {
                'default_invoice_id': self.id,
                'default_patient_id': self.patient_id.id if self.patient_id else False,
                'default_service_date': self.invoice_date,
            }
        }
    
    def action_create_glosa(self):
        """Acción para crear una nueva glosa a partir de la factura"""
        self.ensure_one()
        patient_id = self.patient_id.id if self.patient_id else False
        
        return {
            'name': _('Crear Glosa'),
            'type': 'ir.actions.act_window',
            'res_model': 'glosa.medica',
            'view_mode': 'form',
            'context': {
                'default_invoice_id': self.id,
                'default_patient_id': patient_id,
                'default_service_date': self.invoice_date,
                'default_amount': self.amount_total,
            }
        }
    
    def _reverse_moves(self, default_values_list=None, cancel=False):
        """Sobrescribimos el método para vincular las notas de crédito con glosas si existen"""
        reverse_moves = super(AccountMove, self)._reverse_moves(default_values_list=default_values_list, cancel=cancel)
        
        for move, reverse_move in zip(self, reverse_moves):
            glosas_finales = move.glosa_ids.filtered(lambda g: g.active and 
                                                    g.is_conciliated and 
                                                    not g.credit_note_id)
            if glosas_finales:
                glosa_reciente = glosas_finales.sorted('create_date', reverse=True)[0]
                glosa_reciente.write({
                    'credit_note_id': reverse_move.id
                })
                
                # Agregar mensaje de log
                glosa_reciente.message_post(
                    body=_("Se ha generado la nota de crédito %s por un monto de %s %s") % 
                         (reverse_move.name, reverse_move.amount_total, reverse_move.currency_id.name),
                    subtype_id=self.env.ref('mail.mt_note').id
                )
        
        return reverse_moves
    
    def _reconcile_reversed_moves(self, reverse_moves, move_reverse_cancel):
        result = super(AccountMove, self)._reconcile_reversed_moves(reverse_moves, move_reverse_cancel)
        
        for move, reverse_move in zip(self, reverse_moves):
            glosas = self.env['glosa.medica'].search([
                ('invoice_id', '=', move.id),
                ('credit_note_id', '=', reverse_move.id)
            ])
            
            for glosa in glosas:
                if not glosa.is_conciliated:
                    close_note = glosa.close_note or _("Glosa cerrada automáticamente tras la generación y reconciliación de la nota de crédito %s") % reverse_move.name
                    
                    glosa.write({
                        'is_conciliated': True,
                        'close_note': close_note
                    })
                    result_to_state = {
                        'favorable': 'rechazado',
                        'desfavorable': 'aceptado',
                        'parcial': 'parcial'
                    }
                    state = result_to_state.get(glosa.result, 'resuelto')
                    etapa = self.env['glosa.etapa'].search([('state', '=', state)], limit=1)
                    
                    if etapa:
                        glosa.write({'etapa_id': etapa.id})
                    
                    glosa.message_post(
                        body=_("La glosa ha sido conciliada tras la reconciliación de la nota de crédito %s") % 
                             (reverse_move.name),
                        subtype_id=self.env.ref('mail.mt_note').id
                    )
        
        return result


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'
    
      
    # Campos relacionados con glosas
    glosa_ids = fields.One2many('glosa.medica', 'invoice_line_id', string="Glosas")
    has_glosa = fields.Boolean(string="Tiene Glosa", compute='_compute_has_glosa', store=True)
    
    @api.depends('glosa_ids')
    def _compute_has_glosa(self):
        for record in self:
            record.has_glosa = bool(record.glosa_ids.filtered(lambda g: g.active))
    
    def action_view_glosas(self):
        """Acción para ver las glosas asociadas a la línea"""
        self.ensure_one()
        return {
            'name': _('Glosas'),
            'type': 'ir.actions.act_window',
            'res_model': 'glosa.medica',
            'view_mode': 'tree,form',
            'domain': [('invoice_line_id', '=', self.id)],
            'context': {
                'default_invoice_line_id': self.id,
                'default_invoice_id': self.move_id.id,
                'default_patient_id': self.patient_id.id if self.patient_id else 
                                   (self.move_id.patient_id.id if self.move_id.patient_id else False),
                'default_service_date': self.move_id.invoice_date,
                'default_amount': self.price_total,
            }
        }
    
    def action_create_glosa(self):
        """Acción para crear una nueva glosa a partir de la línea"""
        self.ensure_one()
        # Determinar el paciente
        patient_id = self.patient_id.id if self.patient_id else \
                   (self.move_id.patient_id.id if self.move_id.patient_id else False)
        
        return {
            'name': _('Crear Glosa'),
            'type': 'ir.actions.act_window',
            'res_model': 'glosa.medica',
            'view_mode': 'form',
            'context': {
                'default_invoice_line_id': self.id,
                'default_invoice_id': self.move_id.id,
                'default_patient_id': patient_id,
                'default_service_date': self.move_id.invoice_date,
                'default_amount': self.price_total,
            }
        }
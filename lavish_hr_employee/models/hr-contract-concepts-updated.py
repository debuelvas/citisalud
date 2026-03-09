from odoo import api, fields, models, _, Command
from odoo.exceptions import UserError, ValidationError
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta
import calendar
import logging
from typing import Dict, List, Union, Optional, Tuple, Any, TypeVar, cast
from odoo.tools.safe_eval import safe_eval
_logger = logging.getLogger(__name__)

PRECISION_TECHNICAL = 10
PRECISION_DISPLAY = 2

T = TypeVar('T')

class HrContractConceptSkip(models.Model):
    _name = 'hr.contract.concept.skip'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Saltos en Conceptos de Nómina'
    _order = 'period_skip desc, id desc'
    
    name = fields.Char('Nombre', compute='_compute_name', store=True)
    concept_id = fields.Many2one('hr.contract.concepts', 'Concepto', required=True, 
                               ondelete='cascade', index=True, tracking=True)
    employee_id = fields.Many2one(related='concept_id.employee_id', store=True, string='Empleado')
    contract_id = fields.Many2one(related='concept_id.contract_id', store=True)
    company_id = fields.Many2one(related='concept_id.company_id', store=True)
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('approved', 'Aprobado'),
        ('applied', 'Aplicado'),
        ('canceled', 'Cancelado')
    ], string='Estado', default='draft', required=True, tracking=True)
    period_skip = fields.Date('Fecha de Salto', required=True, tracking=True,
                           help='Fecha de la quincena donde se aplicará el salto')
    fortnight = fields.Selection([
        ('15', 'Primera quincena'),
        ('30', 'Segunda quincena')
    ], string='Quincena', required=True, default='15', tracking=True)
    recovery_type = fields.Selection([
        ('none', 'Sin recuperación'),
        ('next', 'Siguiente cuota'),
        ('distributed', 'Distribuido en varias cuotas'),
        ('specific_date', 'Fecha específica')
    ], string='Tipo de Recuperación', required=True, default='next', tracking=True)
    recovery_date = fields.Date('Fecha de Recuperación', tracking=True)
    installments_number = fields.Integer('Número de Cuotas', default=1, tracking=True)
    creation_date = fields.Date('Fecha de Creación', default=fields.Date.today, readonly=True)
    approval_date = fields.Date('Fecha de Aprobación', readonly=True)
    application_date = fields.Date('Fecha de Aplicación', readonly=True)
    cancellation_date = fields.Date('Fecha de Cancelación', readonly=True)
    amount = fields.Float('Monto', compute='_compute_amount', store=True,
                      help='Monto estimado del salto')
    reason = fields.Text('Motivo', tracking=True)
    notes = fields.Text('Notas Adicionales')
    notify_employee = fields.Boolean('Notificar Empleado', default=True)
    notify_supervisor = fields.Boolean('Notificar Supervisor', default=True)
    related_absence_id = fields.Many2one('hr.leave', 'Ausencia Relacionada')
    related_payslip_id = fields.Many2one('hr.payslip', 'Nómina Relacionada')
    created_by = fields.Many2one('res.users', 'Creado por', default=lambda self: self.env.user)
    approved_by = fields.Many2one('res.users', 'Aprobado por')
    _sql_constraints = [
        ('period_skip_concept_uniq', 'unique(concept_id, period_skip, fortnight)', 
         'Ya existe un salto para este concepto en el mismo período y quincena.')
    ]
    
    @api.depends('concept_id', 'period_skip', 'fortnight', 'state')
    def _compute_name(self) -> None:
        """Calcula un nombre descriptivo para el salto"""
        for record in self:
            if not record.concept_id or not record.period_skip:
                record.name = _("Nuevo Salto")
                continue
                
            fortnight_str = _("1Q") if record.fortnight == '15' else _("2Q")
            month_str = record.period_skip.strftime('%b').upper()
            year_str = record.period_skip.year
            
            concept_name = record.concept_id.input_id.name if record.concept_id.input_id else ""
            
            state_str = ""
            if record.state == 'approved':
                state_str = _("[PENDIENTE]")
            elif record.state == 'applied':
                state_str = _("[APLICADO]")
            elif record.state == 'canceled':
                state_str = _("[CANCELADO]")
                
            record.name = f"{concept_name} - {fortnight_str} {month_str}/{year_str} {state_str}"
    
    @api.depends('concept_id', 'concept_id.amount', 'concept_id.amount_select')
    def _compute_amount(self) -> None:
        """Calcula el monto estimado del salto"""
        for record in self:
            if not record.concept_id:
                record.amount = 0.0
                continue
            if record.concept_id.modality_value == 'fijo':
                if record.concept_id.aplicar == '0': 
                    record.amount = record.concept_id.amount / 2
                else:
                    record.amount = record.concept_id.amount
            else:
                daily_amount = record.concept_id.amount / 30
                record.amount = daily_amount * 15
    
    @api.onchange('recovery_type')
    def _onchange_recovery_type(self) -> None:
        """Actualiza campos relacionados al cambiar el tipo de recuperación"""
        if self.recovery_type == 'none':
            self.recovery_date = False
            self.installments_number = 0
        elif self.recovery_type == 'next':
            self.installments_number = 1
            if self.period_skip:
                if self.fortnight == '15':
                    self.recovery_date = self._get_last_day_of_month(self.period_skip)
                else:
                    next_month = self.period_skip + timedelta(days=15)
                    self.recovery_date = date(next_month.year, next_month.month, 15)
        elif self.recovery_type == 'distributed':
            self.installments_number = 2
            self.recovery_date = False
        elif self.recovery_type == 'specific_date':
            self.installments_number = 1
    
    def _get_last_day_of_month(self, reference_date: date) -> date:
        """
        Obtiene el último día del mes de una fecha dada
        Args:
            reference_date: Fecha de referencia
        Returns:
            Fecha del último día del mes
        """
        if reference_date.month == 12:
            return date(reference_date.year, 12, 31)
        else:
            next_month = date(reference_date.year, reference_date.month + 1, 1)
            return next_month - timedelta(days=1)
    
    def action_approve(self) -> Dict[str, Any]:
        """
        Aprueba el salto
        Returns:
            Diccionario con resultado de la acción
        """
        for record in self:
            if record.state != 'draft':
                raise UserError(_("Solo se pueden aprobar saltos en estado borrador."))
            if record.recovery_type == 'specific_date' and not record.recovery_date:
                raise UserError(_("Debe especificar una fecha de recuperación."))
            if record.recovery_type == 'distributed' and record.installments_number < 1:
                raise UserError(_("El número de cuotas para distribución debe ser al menos 1."))
            record.write({
                'state': 'approved',
                'approval_date': fields.Date.today(),
                'approved_by': self.env.user.id
            })
            self._send_notifications('approve')
        return {'type': 'ir.actions.act_window_close'}
    
    def action_cancel(self) -> Dict[str, Any]:
        """
        Cancela el salto
        Returns:
            Diccionario con resultado de la acción
        """
        for record in self:
            if record.state == 'applied':
                raise UserError(_("No se pueden cancelar saltos ya aplicados."))
            record.write({
                'state': 'canceled',
                'cancellation_date': fields.Date.today()
            })
            self._send_notifications('cancel')
        return {'type': 'ir.actions.act_window_close'}
    
    def _send_notifications(self, action_type: str) -> None:
        """
        Envía notificaciones según configuración
        Args:
            action_type: Tipo de acción (approve, apply, cancel)
        """
        for record in self:
            if action_type == 'approve':
                title = _("Salto de Cuota Aprobado")
                message = _("Se ha aprobado un salto para el concepto '%s' en el período %s.") % (
                    record.concept_id.name or '', 
                    record.period_skip.strftime('%d/%m/%Y')
                )
            elif action_type == 'apply':
                title = _("Salto de Cuota Aplicado")
                message = _("Se ha aplicado un salto para el concepto '%s' en el período %s.") % (
                    record.concept_id.name or '', 
                    record.period_skip.strftime('%d/%m/%Y')
                )
            elif action_type == 'cancel':
                title = _("Salto de Cuota Cancelado")
                message = _("Se ha cancelado un salto para el concepto '%s' en el período %s.") % (
                    record.concept_id.name or '', 
                    record.period_skip.strftime('%d/%m/%Y')
                )
            else:
                return
            msg = f"""
                <div class="o_mail_notification">
                    <div><strong>{title}</strong></div>
                    <div>{message}</div>
                    <div>Motivo: {record.reason or 'No especificado'}</div>
                </div>
            """
            record.message_post(body=msg, subtype_xmlid="mail.mt_comment")
            if record.notify_employee and record.employee_id.user_id:
                record.employee_id.user_id.notify_info(message=message, title=title, sticky=True)
            if record.notify_supervisor and record.employee_id.parent_id.user_id:
                record.employee_id.parent_id.user_id.notify_info(message=message, title=title, sticky=True)


class HrContractConcepts(models.Model):
    _name = 'hr.contract.concepts'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Deducciones o Devengos, conceptos de nómina'
    _order = 'sequence, date_start desc, id desc'

    #==================================================
    # GRUPO: CAMPOS BÁSICOS Y DE IDENTIFICACIÓN
    #==================================================
    name = fields.Char('Nombre', compute='_compute_name', store=True)
    display_name = fields.Char('Nombre a mostrar', compute='_compute_display_name', store=True)
    context_name = fields.Char('Nombre contextual', compute='_compute_context_name')
    sequence = fields.Integer('Secuencia', default=10, tracking=True)
    type_employee = fields.Many2one('hr.types.employee', string='Tipo de Empleado', store=True, readonly=True)
    active = fields.Boolean('Activo', default=True, tracking=True)
    company_id = fields.Many2one('res.company', string='Compañía', default=lambda self: self.env.company)
    state = fields.Selection([
        ('draft', 'Por Aprobar'),
        ('done', 'Aprobado'),
        ('closed', 'Cerrado'),
        ('cancel', 'Cancelado')
    ], string='Estado', default='draft', required=True, tracking=True, group_expand='_expand_states')
    
    closed_date = fields.Date('Fecha de Cierre', readonly=True)
    closed_reason = fields.Text('Motivo de Cierre')
    cancel_date = fields.Date('Fecha de Cancelación', readonly=True)
    cancel_reason = fields.Text('Motivo de Cancelación')
    input_id = fields.Many2one('hr.salary.rule', 'Regla', required=True, 
                              help='Regla salarial', domain=[('novedad_ded','=','cont')])
    show_voucher = fields.Boolean('Mostrar en Voucher', default=True, help='Indica si se muestra o no en el comprobante de nomina')
    type_deduction = fields.Selection([
        ('P', 'Prestamo empresa'),
        ('A', 'Ahorro'),
        ('S', 'Seguro'),
        ('L', 'Libranza'),
        ('E', 'Embargo'),
        ('R', 'Retencion'),
        ('O', 'Otros')
    ], 'Tipo deduccion', tracking=True)
    
    monthly_behavior = fields.Selection([
        ('equal', 'Mismo valor en ambas quincenas'),
        ('proportional', 'Proporcional a días'),
        ('divided', 'Dividir en partes iguales')
    ], string='Comportamiento Mensual', default='equal', tracking=True)
    
    type_emb = fields.Selection([
        ('ECA', 'Emb. Cuotas alimentarias'),
        ('EDJ', 'Emb. Depósito judicial'),
        ('EI', 'Emb. ICETEX'),
        ('EJ', 'Emb. Ejecutivo'),
        ('O', 'Otros')
    ], 'Tipo Embargo', tracking=True)
    
    is_deduction = fields.Boolean('Es Deducción', compute='_compute_is_deduction', store=True)
    is_earning = fields.Boolean('Es Devengo', compute='_compute_is_deduction', store=True)
    period = fields.Selection([
        ('limited', 'Limitado'),
        ('indefinite', 'Indefinido')
    ], 'Limite', default='indefinite', tracking=True)
    
    date_start = fields.Date('Fecha Inicial', tracking=True)
    date_end = fields.Date('Fecha Final', tracking=True)
    amount_select = fields.Selection([
        ('percentage', 'Porcentaje (%)'),
        ('fix', 'Monto fijo'),
        ('min', 'Base minimo'),
    ], string='Tipo de Monto', index=True, required=True, default='fix', tracking=True)
    
    amount = fields.Float('Importe/porcentaje', required=True, tracking=True)
    minimum_amount = fields.Float('Monto Mínimo', help='Monto mínimo a aplicar cuando se usa porcentaje')
    maximum_amount = fields.Float('Monto Máximo', help='Monto máximo a aplicar cuando se usa porcentaje')
    aplicar = fields.Selection([
        ('15','Primera quincena'),
        ('30','Segunda quincena'),
        ('0','Siempre')
    ], 'Aplicar cobro', required=True, default='0', tracking=True)
    modality_value = fields.Selection([
        ('fijo', 'Valor fijo'),
        ('diario', 'Días trabajo + ausencias'),
        ('diario_efectivo', 'Días trabajados en período actual'),
        ('proyeccion_completa', 'Proyección mes completo (2da quincena)'),
        ('dias_trabajo_ausencias_justificadas', 'Días trabajo + ausencias justificadas'),
    ], 'Modalidad de valor', default='fijo', tracking=True)
    skip_ids = fields.One2many('hr.contract.concept.skip', 'concept_id', string='Saltos')
    active_skip_count = fields.Integer('Saltos Activos', compute='_compute_skip_counts')
    applied_skip_count = fields.Integer('Saltos Aplicados', compute='_compute_skip_counts')
    allow_skips = fields.Boolean('Permitir Saltos', default=True,
        help='Si no está marcado, no se podrán crear saltos para este concepto')
    skip_notification = fields.Boolean('Notificar Saltos', default=True,
        help='Enviar notificaciones al crear/aplicar saltos')
    auto_skip_suggestion = fields.Boolean('Sugerencias Automáticas', default=False,
        help='Sugerir automáticamente saltos cuando el empleado tiene ausencias')
    force_double_payment = fields.Boolean('Forzar Pago Doble')
    double_payment_date = fields.Date('Fecha Pago Doble')
    last_double_payment = fields.Date('Último Pago Doble', readonly=True)
    considerar_ausencias = fields.Selection([
        ('todas', 'Todas las ausencias'),
        ('justificadas', 'Solo ausencias justificadas'),
        ('ninguna', 'No considerar ausencias')
    ], string='Considerar ausencias', default='todas',
       help='Define qué ausencias afectan el cálculo del concepto')
    absence_codes_to_include = fields.Char('Códigos a Incluir', 
        help='Lista de códigos de ausencia a incluir en el cálculo, separados por coma')
    absence_codes_to_exclude = fields.Char('Códigos a Excluir',
        help='Lista de códigos de ausencia a excluir del cálculo, separados por coma')
    excluir_sabados = fields.Boolean('Excluir sábados', default=False)
    excluir_domingos = fields.Boolean('Excluir domingos', default=False)
    excluir_festivos = fields.Boolean('Excluir festivos', default=False)
    descontar_dia_31 = fields.Boolean('Descontar día 31', default=True,
        help='Si está marcado, se descontará el día 31 del mes (como en la nómina colombiana)')
    proyectar_pago_completo = fields.Boolean('Proyectar pago completo', default=False,
        help='Si está marcado, se proyectará el pago completo del mes en la segunda quincena')
    considerar_primera_quincena = fields.Boolean('Considerar primera quincena', default=True, 
        help='Si está marcado, se considerará lo pagado en primera quincena para el ajuste')
    ajustar_por_dias = fields.Boolean('Ajustar por días', default=True,
        help='Si está marcado, se ajustará el pago según los días efectivamente trabajados')
    dias_base = fields.Integer('Días base cálculo', default=30,
        help='Número de días base para el cálculo (normalmente 30)')
    pendiente_revision = fields.Boolean('Pendiente de revisión', default=False,
        help='Si está marcado, esta línea se marcará para revisión en el siguiente período')
    formula_ajuste = fields.Char('Fórmula de ajuste', 
        help='Fórmula para calcular el ajuste en la siguiente revisión')
    precision_calculo = fields.Integer('Precisión de cálculo', default=PRECISION_TECHNICAL,
        help='Número de decimales a considerar en los cálculos')
    precision_redondeada = fields.Boolean('Redondear a entero', default=False,
        help='Si está marcado, se redondeará el resultado final a un número entero')
    
    contract_id = fields.Many2one('hr.contract', 'Contrato', required=True,
                                 ondelete='cascade', index=True, auto_join=True)
    employee_id = fields.Many2one(related='contract_id.employee_id', store=True, string='Empleado')
    partner_id = fields.Many2one('hr.employee.entities', 'Entidad')
    payroll_structure_ids = fields.Many2many('hr.payroll.structure', 
                                           string='Estructuras Salariales')
    payslip_ids = fields.Many2many('hr.payslip', 'hr_concept_payslip_rel', 'concept_id', 'payslip_id', 
                               string='Nóminas Relacionadas', readonly=True)
    last_processed_payslip_id = fields.Many2one('hr.payslip', string='Última Nómina Procesada', readonly=True)
    last_processed_date = fields.Date('Última Fecha Procesada', readonly=True)
    closed_payslip_id = fields.Many2one('hr.payslip', string='Nómina de Cierre', readonly=True)
    
    base_structure_only = fields.Boolean('Aplicar solo en estructuras base', 
        default=True,
        help='Si está marcado, el concepto se aplicará solo en estructuras base')
    discount_rule = fields.Many2many('hr.salary.rule', string='Reglas de descuento')
    discount_categoria = fields.Many2many('hr.salary.rule.category',
                                        string='Categorias de descuento')
    description = fields.Char(string='Descripcion')
    detail = fields.Text('Notas', help='Notas')
    embargo_judged = fields.Char('Juzgado')
    embargo_process = fields.Char('Proceso')
    attached = fields.Binary('Adjunto')
    attached_name = fields.Char('Nombre adjunto')
    payroll_account_id = fields.Many2one('account.account', string="Cuenta Contable")
    balance = fields.Float('Saldo Pendiente', compute='_compute_balance', store=True)
    total_paid = fields.Float('Total Pagado', compute='_compute_balance', store=True)
    next_payment_date = fields.Date('Próximo Pago', compute='_compute_next_payment')
    simulation_text = fields.Html('Detalle de Simulación', compute='_compute_simulation_details')
    active_period = fields.Boolean('Periodo Activo', compute='_compute_active_period')
    accumulated_amount = fields.Float('Monto Acumulado', compute='_compute_accumulated')
    remaining_installments = fields.Integer('Cuotas Restantes', compute='_compute_remaining')
    total_installments = fields.Integer('Total Cuotas', compute='_compute_remaining')
    line_ids = fields.One2many('hr.payslip.line', 'concept_id', string='Líneas de Nómina')
    pending_review_line_ids = fields.One2many('hr.payslip.line', 'concept_id',
        domain=[('pending_review', '=', True), ('reviewed', '=', False)],
        string='Líneas Pendientes de Revisión')
    
    skips_summary = fields.Html('Resumen de Saltos', compute='_compute_skips_summary')
    close_ready = fields.Boolean('Listo para Cerrar', compute='_compute_close_ready',
                               help='Indica si el concepto está listo para ser cerrado')
    concept_type_display = fields.Char('Tipo de Concepto', compute='_compute_concept_type_display', store=True)
    
    ribbon_message = fields.Char("Mensaje de Ribbon", compute='_compute_ribbon_message')
    ribbon_color = fields.Char("Color de Ribbon", compute='_compute_ribbon_message')
    
    _sql_constraints = [
        ('check_amount_positive', 'CHECK(amount >= 0)', 'El monto debe ser positivo'),
        ('date_check', 'CHECK((date_start IS NULL AND date_end IS NULL) OR (date_start <= date_end OR date_end IS NULL))',
         'La fecha final debe ser posterior a la fecha inicial')
    ]
    
    #==================================================
    # MÉTODOS COMPUTADOS
    #==================================================
    @api.depends('input_id', 'contract_id', 'type_deduction', 'state')
    def _compute_name(self) -> None:
        """Calcula el nombre completo del concepto incluyendo su estado"""
        for record in self:
            name_parts = []
            if record.id:
                name_parts.append(f'# {record.id}')
            if record.input_id:
                name_parts.append(record.input_id.name)
            if record.type_deduction:
                name_parts.append(dict(record._fields['type_deduction'].selection).get(record.type_deduction))
                
            if record.state == 'closed':
                name_parts.append('[CERRADO]')
            elif record.state == 'cancel':
                name_parts.append('[CANCELADO]')
                
            record.name = " - ".join(filter(None, name_parts))
            
    @api.depends('name', 'employee_id', 'is_deduction', 'is_earning', 'amount', 'amount_select')
    def _compute_display_name(self) -> None:
        """Genera un nombre de visualización más completo para mostrar en vistas"""
        for record in self:
            parts = []
            
            tipo = "DED" if record.is_deduction else "DEV" if record.is_earning else "CON"
            parts.append(f"[{tipo}]")
            
            if record.id:
                parts.append(f"#{record.id}")
                
            if record.employee_id:
                parts.append(record.employee_id.name)
                
            if record.input_id:
                parts.append(record.input_id.name)
                
            if record.amount_select == 'percentage':
                parts.append(f"{record.amount}%")
            else:
                parts.append(f"${record.amount:,.2f}")
                
            if record.state == 'draft':
                parts.append("(Borrador)")
            elif record.state == 'closed':
                parts.append("(Cerrado)")
            elif record.state == 'cancel':
                parts.append("(Cancelado)")
                
            record.display_name = " - ".join(parts)
            
    def _compute_context_name(self) -> None:
        """
        Genera un nombre basado en el contexto actual (quincena, mes, etc.)
        Este nombre no se almacena, se calcula en tiempo real
        """
        for record in self:
            ctx = self.env.context
            today = fields.Date.context_today(self)
            base_parts = []
            if record.input_id:
                base_parts.append(record.input_id.name)
            payslip_id = ctx.get('payslip_id') or ctx.get('active_id') if ctx.get('active_model') == 'hr.payslip' else False
            if payslip_id:
                payslip = self.env['hr.payslip'].browse(payslip_id)
                date_to = payslip.date_to
                fortnight = "1Q" if date_to.day <= 15 else "2Q"
                month_year = f"{date_to.strftime('%b').upper()}/{date_to.year}"
                base_parts.append(f"{fortnight} {month_year}")
            else:
                fortnight = "1Q" if today.day <= 15 else "2Q"
                month_year = f"{today.strftime('%b').upper()}/{today.year}"
                base_parts.append(f"{fortnight} {month_year}")
            tipo = "D" if record.is_deduction else "I" if record.is_earning else "C"
            base_parts.append(f"[{tipo}]")
            record.context_name = " - ".join(base_parts)

    @api.depends('input_id.dev_or_ded')
    def _compute_is_deduction(self) -> None:
        """Determina si el concepto es deducción o devengo basado en la regla"""
        for record in self:
            if record.input_id:
                record.is_deduction = record.input_id.dev_or_ded == 'deduccion'
                record.is_earning = record.input_id.dev_or_ded == 'devengo'
            else:
                record.is_deduction = False
                record.is_earning = False
    
    @api.depends('is_deduction', 'is_earning')
    def _compute_concept_type_display(self) -> None:
        """Muestra el tipo de concepto para facilitar la identificación visual"""
        for record in self:
            if record.is_deduction:
                record.concept_type_display = 'Deducción'
            elif record.is_earning:
                record.concept_type_display = 'Devengo'
            else:
                record.concept_type_display = 'No definido'
    
    @api.depends('state')
    def _compute_ribbon_message(self) -> None:
        """Define el mensaje y color del ribbon para la visualización del estado"""
        for record in self:
            if record.state == 'draft':
                record.ribbon_message = 'Por Aprobar'
                record.ribbon_color = 'bg-info'
            elif record.state == 'done':
                record.ribbon_message = 'Aprobado'
                record.ribbon_color = 'bg-success'
            elif record.state == 'closed':
                record.ribbon_message = 'Cerrado'
                record.ribbon_color = 'bg-warning'
            elif record.state == 'cancel':
                record.ribbon_message = 'Cancelado'
                record.ribbon_color = 'bg-danger'
            else:
                record.ribbon_message = False
                record.ribbon_color = False

    @api.depends('line_ids', 'line_ids.total')
    def _compute_accumulated(self) -> None:
        """Calcula el monto acumulado de las líneas de nómina"""
        for record in self:
            record.accumulated_amount = sum(record.line_ids.mapped('total'))
    
    @api.depends('period', 'amount', 'line_ids', 'date_end', 'date_start', 'aplicar', 'modality_value', 'amount_select')
    def _compute_balance(self) -> None:
        """Calcula el saldo pendiente del concepto"""
        for record in self:
            total_paid = sum(record.line_ids.mapped('total'))
            record.total_paid = total_paid
            if record.period == 'indefinite':
                record.balance = 0
                continue
            base_per_period = record._get_amount_per_period()
            total_periods = record._calculate_total_periods()
            total_expected = record.compute_precise(base_per_period, total_periods, '*', record.precision_calculo)
            record.balance = record.compute_precise(total_expected, total_paid, '-', record.precision_calculo)
            
    @api.depends('balance', 'line_ids', 'date_end', 'period')
    def _compute_remaining(self) -> None:
        """Calcula las cuotas restantes y totales"""
        for record in self:
            if record.period == 'indefinite':
                record.remaining_installments = 0
                record.total_installments = 0
                continue
            total_periods = record._calculate_total_periods()
            record.total_installments = total_periods
            
            applied_periods = len(record.line_ids)
            record.remaining_installments = max(total_periods - applied_periods, 0)
    
    @api.depends('date_start', 'date_end', 'state')
    def _compute_active_period(self) -> None:
        """Determina si el período está activo en la fecha actual"""
        today = fields.Date.today()
        for record in self:
            record.active_period = record._is_period_active(today)
            
    @api.depends('date_start', 'aplicar', 'skip_ids', 'line_ids', 'line_ids.slip_id.state')
    def _compute_next_payment(self) -> None:
        """Calcula la próxima fecha de pago considerando saltos y configuración"""
        today = fields.Date.today()
        for record in self:
            record.next_payment_date = record._calculate_next_payment_date(today)
            
    @api.depends('amount', 'modality_value', 'amount_select', 'aplicar', 'type_deduction', 'skip_ids', 'proyectar_pago_completo', 'is_deduction', 'is_earning')
    def _compute_simulation_details(self) -> None:
        """Genera una representación visual del cálculo para simulación"""
        for record in self:
            simulation_text = record._generate_simulation_text()
            record.simulation_text = simulation_text
            
    @api.depends('state', 'period', 'date_end', 'balance', 'remaining_installments')
    def _compute_close_ready(self) -> None:
        """Determina si el concepto está listo para ser cerrado automáticamente"""
        today = fields.Date.today()
        for record in self:
            if record.state in ['closed', 'cancel']:
                record.close_ready = False
                continue
            if record.state != 'done':
                record.close_ready = False
                continue
            if record.period == 'indefinite':
                record.close_ready = False
                continue
            if record.period == 'limited':
                if record.date_end and record.date_end < today:
                    record.close_ready = True
                    continue
                if record.balance <= 0:
                    record.close_ready = True
                    continue
                if record.remaining_installments <= 0:
                    record.close_ready = True
                    continue
            record.close_ready = False
    
    @api.depends('skip_ids', 'skip_ids.state')
    def _compute_skip_counts(self) -> None:
        """Calcula contadores de saltos para indicadores visuales"""
        for record in self:
            record.active_skip_count = len(record.skip_ids.filtered(lambda s: s.state == 'approved'))
            record.applied_skip_count = len(record.skip_ids.filtered(lambda s: s.state == 'applied'))
    
    @api.depends('skip_ids', 'skip_ids.state')
    def _compute_skips_summary(self) -> None:
        """Genera un resumen HTML de los saltos asociados"""
        for record in self:
            if not record.skip_ids:
                record.skips_summary = '<p class="text-muted">No hay saltos configurados</p>'
                continue
                
            skips_approved = record.skip_ids.filtered(lambda s: s.state == 'approved')
            skips_applied = record.skip_ids.filtered(lambda s: s.state == 'applied')
            
            html = '<div class="d-flex flex-column">'
            
            if skips_approved:
                html += '<div class="alert alert-info" role="alert">'
                html += f'<h6 class="alert-heading mb-1"><i class="fa fa-clock-o"></i> {len(skips_approved)} Saltos Pendientes</h6>'
                html += '<ul class="mb-0 pl-3">'
                for skip in skips_approved[:3]: 
                    skip_date = skip.period_skip.strftime('%d/%m/%Y')
                    html += f'<li>{skip_date}</li>'
                html += '</ul>'
                if len(skips_approved) > 3:
                    html += f'<small>y {len(skips_approved) - 3} más...</small>'
                html += '</div>'
            
            if skips_applied:
                html += '<div class="alert alert-success" role="alert">'
                html += f'<h6 class="alert-heading mb-1"><i class="fa fa-check"></i> {len(skips_applied)} Saltos Aplicados</h6>'
                html += '<ul class="mb-0 pl-3">'
                for skip in skips_applied[:3]: 
                    skip_date = skip.period_skip.strftime('%d/%m/%Y')
                    html += f'<li>{skip_date}</li>'
                html += '</ul>'
                if len(skips_applied) > 3:
                    html += f'<small>y {len(skips_applied) - 3} más...</small>'
                html += '</div>'
                
            html += '</div>'
            record.skips_summary = html
    
    
    #==================================================
    # MÉTODOS AUXILIARES
    #==================================================
    def _expand_states(self, states: List[str], domain: List, order: str) -> List[str]:
        """Expande los estados para vista agrupada"""
        return [key for key, val in self._fields['state'].selection]
        
    def _get_amount_per_period(self) -> float:
        """Calcula el monto por período según la configuración"""
        base_amount = self._calculate_base_amount()
        daily_amount = self.compute_precise(base_amount, 30, '/', self.precision_calculo) if self.modality_value != 'fijo' else 0
        if self.modality_value != 'fijo':
            if self.aplicar == '0':
                return self.compute_precise(daily_amount, 30, '*', self.precision_calculo)
            else:
                return self.compute_precise(daily_amount, 15, '*', self.precision_calculo)
        
        if self.aplicar == '0':
            return self.compute_precise(base_amount, 2, '/', self.precision_calculo)
        return base_amount

    def _calculate_total_periods(self) -> int:
        """Calcula el número total de períodos según fechas y configuración"""
        if not self.date_start or not self.date_end:
            return 1

        start_date = self.date_start
        end_date = self.date_end
        months = (end_date.year - start_date.year) * 12 + end_date.month - start_date.month + 1

        if self.aplicar == '0':
            total_periods = months * 2
            if start_date.day > 15:
                total_periods -= 1
            elif start_date.day > 1:
                total_periods -= 2
            if end_date.day < 15:
                total_periods -= 2
            elif end_date.day < calendar.monthrange(end_date.year, end_date.month)[1]:
                total_periods -= 1
        else:
            total_periods = months
            if self.aplicar == '15' and start_date.day > 15:
                total_periods -= 1
            elif self.aplicar == '30':
                if start_date.day > 15:
                    total_periods -= 1
                if end_date.day < 15:
                    total_periods -= 1

        return max(total_periods, 1)
    
    def _calculate_base_amount(self) -> float:
        """Calcula el monto base según el tipo de cálculo"""
        if self.amount_select == 'percentage':
            base_salary = self.contract_id.wage
            return self.compute_precise(base_salary, self.amount / 100, '*', self.precision_calculo)
        return self.amount
        
    def _is_period_active(self, reference_date: fields.Date) -> bool:
        """Verifica si el período está activo para una fecha de referencia"""
        if self.state != 'done' and self.state != 'closed':
            return False
            
        if self.date_start and self.date_start > reference_date:
            return False
            
        if self.state == 'closed' and self.closed_date:
            if reference_date > self.closed_date:
                return False
                
        if self.date_end and self.date_end < reference_date:
            return False
            
        return True
        
    def compute_precise(self, value1: float = 0.0, value2: float = 0.0, operation: str = '*', decimals: int = PRECISION_TECHNICAL) -> float:
        """
        Realiza operaciones matemáticas con precisión controlada
        
        Args:
            value1: Primer valor
            value2: Segundo valor
            operation: Operación a realizar (+, -, *, /)
            decimals: Número de decimales para el resultado
            
        Returns:
            Resultado de la operación con la precisión especificada
        """
        try:
            value1 = float(value1)
            value2 = float(value2)
        except (ValueError, TypeError):
            return 0.0
        result = 0.0
        if operation == '+':
            result = value1 + value2
        elif operation == '-':
            result = value1 - value2
        elif operation == '*':
            result = value1 * value2
        elif operation == '/':
            if value2 == 0:
                return 0.0
            result = value1 / value2
        else:
            return 0.0
        
        precision = 10 ** -decimals
        result = float(int(result / precision) * precision)
        if self.precision_redondeada:
            result = round(result)
            
        return result
    
    def _get_active_skip(self, date_from: fields.Date, date_to: fields.Date) -> models.Model:
        """Obtiene el salto activo para el período si existe"""
        return self.skip_ids.filtered(lambda x: 
            x.state == 'approved' and 
            x.period_skip and 
            date_from <= x.period_skip <= date_to
        )[:1]
        
    def _calculate_next_payment_date(self, reference_date: fields.Date) -> Optional[fields.Date]:
        """
        Calcula la próxima fecha de pago considerando:
        - Estado de líneas de nómina
        - Períodos activos
        - Saltos programados
        - Reglas de quincena
        """
        self.ensure_one()

        if not self._is_period_active(reference_date):
            return False

        next_date = self._get_base_payment_date(reference_date)
        if not next_date:
            return False

        last_payslip_line = self._get_last_payslip_line()
        if last_payslip_line:
            next_date = self._adjust_date_after_last_payment(last_payslip_line, next_date)

        next_date = self._adjust_for_payment_rules(next_date)

        next_date = self._check_and_adjust_for_skips(next_date, reference_date)

        return next_date
        
    def _get_base_payment_date(self, reference_date: fields.Date) -> fields.Date:
        """
        Obtiene la fecha base inicial para el cálculo
        """
        if self.date_start and self.date_start > reference_date:
            return self.date_start
        return reference_date

    def _get_last_payslip_line(self) -> Optional[models.Model]:
        """
        Obtiene la última línea de nómina procesada usando la relación line_ids
        """
        return self.line_ids.filtered(
            lambda l: l.slip_id.state in ['done', 'paid']
        ).sorted(lambda l: l.slip_id.date_to, reverse=True)[:1]

    def _adjust_date_after_last_payment(self, last_line: models.Model, next_date: fields.Date) -> fields.Date:
        """
        Ajusta la próxima fecha de pago después del último pago
        """
        last_to_date = last_line.slip_id.date_to
        
        if last_to_date >= next_date:
            if self.aplicar == '15':  # Primera quincena
                if last_to_date.day <= 15:
                    next_month = last_to_date + relativedelta(months=1)
                    return date(next_month.year, next_month.month, 15)
                else:
                    # Siguiente mes, primera quincena
                    next_month = last_to_date + relativedelta(months=1)
                    return date(next_month.year, next_month.month, 15)
            elif self.aplicar == '30':  # Segunda quincena
                if last_to_date.day <= 15:
                    last_day = calendar.monthrange(last_to_date.year, last_to_date.month)[1]
                    return date(last_to_date.year, last_to_date.month, last_day)
                else:
                    next_month = last_to_date + relativedelta(months=1)
                    last_day = calendar.monthrange(next_month.year, next_month.month)[1]
                    return date(next_month.year, next_month.month, last_day)
            else:  # Siempre (0)
                if last_to_date.day <= 15:
                    last_day = calendar.monthrange(last_to_date.year, last_to_date.month)[1]
                    return date(last_to_date.year, last_to_date.month, last_day)
                else:
                    next_month = last_to_date + relativedelta(months=1)
                    return date(next_month.year, next_month.month, 15)
        
        return next_date

    def _adjust_for_payment_rules(self, next_date: fields.Date) -> fields.Date:
        """
        Ajusta la próxima fecha de pago según las reglas de aplicación
        """
        day = next_date.day
        month = next_date.month
        year = next_date.year
        
        if self.aplicar == '15':  # Primera quincena
            if day > 15:
                next_month = next_date + relativedelta(months=1)
                return date(next_month.year, next_month.month, 15)
            return date(year, month, 15)
            
        elif self.aplicar == '30':  # Segunda quincena
            last_day = calendar.monthrange(year, month)[1]
            return date(year, month, last_day)
        else:  # Siempre (0)
            if day <= 15:
                return date(year, month, 15)
            else:
                last_day = calendar.monthrange(year, month)[1]
                return date(year, month, last_day)
    
    def _check_and_adjust_for_skips(self, next_date: fields.Date, reference_date: fields.Date) -> fields.Date:
        """
        Verifica y ajusta la fecha por saltos programados
        """
        future_skips = self.skip_ids.filtered(
            lambda s: s.state == 'approved' and s.period_skip and s.period_skip >= reference_date
        ).sorted(key=lambda s: s.period_skip)
        
        if future_skips:
            for skip in future_skips:
                if (next_date.day <= 15 and 
                    skip.period_skip.month == next_date.month and 
                    skip.period_skip.year == next_date.year and
                    skip.fortnight == '15'):
                    last_day = calendar.monthrange(next_date.year, next_date.month)[1]
                    return date(next_date.year, next_date.month, last_day)
                    
                elif (next_date.day > 15 and 
                      skip.period_skip.month == next_date.month and 
                      skip.period_skip.year == next_date.year and
                      skip.fortnight == '30'):
                    next_month = next_date + relativedelta(months=1)
                    return date(next_month.year, next_month.month, 15)
        if self.force_double_payment and self.double_payment_date:
            if (self.double_payment_date.year == next_date.year and 
                self.double_payment_date.month == next_date.month):
                if (self.double_payment_date.day <= 15 and next_date.day <= 15) or \
                   (self.double_payment_date.day > 15 and next_date.day > 15):
                    return self.double_payment_date
        
        return next_date
    
    def _generate_simulation_text(self) -> str:
        """
        Genera texto explicativo con la simulación del cálculo
        """
        html = '<div class="simulation-container p-3">'
        
        tipo = 'Deducción' if self.is_deduction else 'Devengo' if self.is_earning else 'Concepto'
        html += f'<h5 class="mb-3 text-primary">{tipo}: {self.input_id.name if self.input_id else ""}</h5>'
        
        html += '<div class="mb-3 pb-2 border-bottom">'
        html += f'<div><strong>Monto base:</strong> {self.amount:,.2f} {"%" if self.amount_select == "percentage" else ""}</div>'
        html += f'<div><strong>Aplicación:</strong> {dict(self._fields["aplicar"].selection).get(self.aplicar)}</div>'
        html += f'<div><strong>Modalidad:</strong> {dict(self._fields["modality_value"].selection).get(self.modality_value)}</div>'
        html += '</div>'
        
        html += '<h6 class="mt-3 mb-2">Simulación próximo pago:</h6>'
        html += '<div class="p-2 bg-light rounded">'
        
        next_date = self.next_payment_date or fields.Date.today()
        dia = next_date.day
        mes = next_date.month
        anio = next_date.year
        
        es_primera_quincena = dia <= 15
        quincena_txt = "1ª Quincena" if es_primera_quincena else "2ª Quincena"
        html += f'<div class="mb-2"><strong>Período:</strong> {quincena_txt} {mes}/{anio}</div>'
        
        skip = self._get_active_skip(next_date, next_date)
        if skip:
            html += '<div class="alert alert-warning p-2 mb-2">'
            html += f'<i class="fa fa-exclamation-triangle"></i> <strong>ATENCIÓN:</strong> Este período tiene un SALTO programado'
            html += '</div>'
            html += '<div>No se aplicará cobro en este período.</div>'
            
            if skip.recovery_type == 'next':
                html += '<div>Recuperación: <span class="badge badge-info">Próxima cuota</span></div>'
            elif skip.recovery_type == 'distributed':
                html += f'<div>Recuperación: <span class="badge badge-info">Distribuida en {skip.installments_number} cuotas</span></div>'
            elif skip.recovery_type == 'specific_date':
                recovery_date = skip.recovery_date
                mes_rec = recovery_date.month
                anio_rec = recovery_date.year
                html += f'<div>Recuperación: <span class="badge badge-info">Fecha específica {mes_rec}/{anio_rec}</span></div>'
            elif skip.recovery_type == 'none':
                html += '<div>Sin recuperación</div>'
                
            html += '</div>'
            return html
            
        base_amount = self._calculate_base_amount()
        html += f'<div><strong>Monto base:</strong> {base_amount:,.2f}</div>'
        
        if self.modality_value == 'fijo':
            if self.aplicar == '0':  # Siempre
                if es_primera_quincena:
                    amount = self.compute_precise(base_amount, 2, '/', self.precision_calculo)
                    html += '<div class="mt-2 formula">'
                    html += f'Valor Base ÷ 2 = {base_amount:,.2f} ÷ 2 = <strong>{amount:,.2f}</strong>'
                    html += '</div>'
                else:
                    amount = self.compute_precise(base_amount, 2, '/', self.precision_calculo)
                    html += '<div class="mt-2 formula">'
                    html += f'Valor Base ÷ 2 = {base_amount:,.2f} ÷ 2 = <strong>{amount:,.2f}</strong>'
                    html += '</div>'
            else:  # Específico de quincena
                amount = base_amount
                html += '<div class="mt-2 formula">'
                html += f'Valor Base = <strong>{amount:,.2f}</strong>'
                html += '</div>'
        else:
            daily_amount = self.compute_precise(base_amount, 30, '/', self.precision_calculo)
            html += f'<div>Valor diario: {base_amount:,.2f} ÷ 30 = {daily_amount:,.2f}</div>'
            
            # Días base según quincena
            if es_primera_quincena:
                dias_base = 15
            else:
                dias_base = 15 if self.descontar_dia_31 else calendar.monthrange(anio, mes)[1] - 15
            
            html += f'<div>Días base para cálculo: {dias_base}</div>'
            
            # Cálculo final
            amount = self.compute_precise(daily_amount, dias_base, '*', self.precision_calculo)
            html += '<div class="mt-2 formula">'
            html += f'Valor diario × Días = {daily_amount:,.2f} × {dias_base} = <strong>{amount:,.2f}</strong>'
            html += '</div>'
            
            # Explicación de ajustes
            if self.modality_value == 'diario_efectivo':
                html += '<div class="mt-2 text-info small">'
                html += '* El valor final puede variar según los días efectivamente trabajados en el período'
                html += '</div>'
            elif self.modality_value == 'proyeccion_completa' and not es_primera_quincena:
                html += '<div class="mt-2 text-info small">'
                html += '* En la segunda quincena se realizará un ajuste considerando el mes completo'
                html += '</div>'
        
        html += '</div>'  # Cierre de bg-light
        
        html += '<div class="mt-3 pt-2 border-top">'
        if self.is_deduction and self.total_paid > 0:
            html += f'<div><strong>Total pagado:</strong> {self.total_paid:,.2f}</div>'
            
            if self.period == 'limited' and self.balance > 0:
                html += f'<div><strong>Saldo pendiente:</strong> {self.balance:,.2f}</div>'
                html += f'<div><strong>Cuotas restantes:</strong> {self.remaining_installments}</div>'
                
                if self.remaining_installments > 0:
                    meses_restantes = self.remaining_installments // 2
                    if self.remaining_installments % 2 != 0:
                        meses_restantes += 1
                    fecha_fin_estimada = next_date + relativedelta(months=meses_restantes)
                    html += f'<div><strong>Fin estimado:</strong> {fecha_fin_estimada.month}/{fecha_fin_estimada.year}</div>'
        
        html += '</div>'
        
        if self.state == 'closed':
            html += '<div class="alert alert-warning mt-3">'
            html += '<i class="fa fa-lock"></i> <strong>CONCEPTO CERRADO</strong><br>'
            html += f'Este concepto fue cerrado el {self.closed_date}. No se realizarán más pagos.'
            html += '</div>'
        elif self.state == 'cancel':
            html += '<div class="alert alert-danger mt-3">'
            html += '<i class="fa fa-times-circle"></i> <strong>CONCEPTO CANCELADO</strong><br>'
            html += 'Este concepto está cancelado. No se realizarán pagos.'
            html += '</div>'
        elif self.state == 'draft':
            html += '<div class="alert alert-info mt-3">'
            html += '<i class="fa fa-exclamation-circle"></i> <strong>PENDIENTE DE APROBACIÓN</strong><br>'
            html += 'Este concepto está en borrador. No se aplicará hasta ser aprobado.'
            html += '</div>'
            
        html += '</div>'  # Cierre container principal
        
        return html
    
    #==================================================
    # MÉTODOS PARA REGLAS SALARIALES
    #==================================================
    def validate_salary_rule_configuration(self, rule: models.Model) -> Dict[str, Any]:
        """
        Valida la configuración de la regla salarial y devuelve mensajes de advertencia
        """
        self.ensure_one()
        result = {
            'is_valid': True,
            'warnings': [],
            'suggestions': []
        }
        
        if rule.amount_select == 'concept':
            if rule.condition_select != 'none':
                result['warnings'].append(
                    _("""La regla está configurada para usar conceptos, pero tiene una condición definida. 
                    Se recomienda configurar la condición como 'Siempre Verdadero' para evitar conflictos.""")
                )
                result['suggestions'].append({
                    'field': 'condition_select',
                    'value': 'none',
                    'reason': _("Cambiar a 'Siempre Verdadero' para usar conceptos")
                })
        
        if rule.amount_select == 'code':
            if not rule.amount_python_compute:
                result['warnings'].append(
                    _("La regla está configurada para usar código Python, pero no tiene código definido.")
                )
                result['is_valid'] = False
                
        if rule.is_leave and self.modality_value in ['diario', 'diario_efectivo']:
            result['warnings'].append(
                _("""Esta regla está marcada como ausencia, pero el concepto está configurado 
                para cálculo diario. Verifique que esto sea intencional.""")
            )
            
        return result
    
    def get_computed_amount_for_payslip(self, 
                                       payslip: models.Model, 
                                       date_from: fields.Date, 
                                       date_to: fields.Date, 
                                       localdict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calcula el monto para la nómina según la configuración y el localdict
        Devuelve un diccionario con la información para crear la línea de nómina
        
        Args:
            payslip: Nómina
            date_from: Fecha inicial
            date_to: Fecha final
            localdict: Diccionario con variables para el cálculo
            
        Returns:
            Dict con información para crear la línea de nómina
        """
        self.ensure_one()
        
        if not self._should_apply_in_period(payslip, date_from, date_to, localdict):
            return {
                'create_line': False,
                'reason': 'no_apply_in_period'
            }
            
        if self._concept_already_applied(payslip, date_from, date_to, localdict):
            return {
                'create_line': False,
                'reason': 'already_applied'
            }
            
        skip = self._get_active_skip(date_from, date_to)
        if skip:
            if self.skip_notification and skip.state == 'approved':
                self._notify_skip_application(skip, payslip)
                skip.write({'state': 'applied', 'application_date': fields.Date.today()})
                
            return {
                'create_line': False,
                'reason': 'skip_applied',
                'skip_info': {
                    'id': skip.id,
                    'period': skip.period_skip,
                    'recovery_type': skip.recovery_type
                }
            }
            
        result = self._calculate_amount_for_payslip(payslip, date_from, date_to, localdict)
        
        if self.force_double_payment and self.double_payment_date:
            if date_from <= self.double_payment_date <= date_to:
                result['amount'] = self.compute_precise(result['amount'], 2, '*', self.precision_calculo)
                result['formula'] += f" × 2 (Pago doble forzado)"
                self.write({'last_double_payment': fields.Date.today(), 'force_double_payment': False})
        period_str = f"{date_from.strftime('%d/%m/%Y')} al {date_to.strftime('%d/%m/%Y')}"
        fortnight = "1Q" if date_to.day <= 15 else "2Q"
        month_year = f"{date_to.strftime('%b').upper()}/{date_to.year}"
        concept_type = "D" if self.is_deduction else "I"  # Deducción o Ingreso
        ctx_name = self._dynamic_name_with_context(date_from, date_to, result)
        
        return {
            'create_line': True,
            'values': {
                'name': ctx_name,
                'code': self.input_id.code,
                'amount': result['amount'],
                'quantity': result.get('quantity', 1),
                'rate': result.get('rate', 100),
                'concept_id': self.id,
                'fortnight_indicator': fortnight,
                'period': month_year,
                'pending_review': self.pendiente_revision,
                'is_deduction': self.is_deduction,
                'days_count': result.get('days_count', 0),
                'payslip_id': payslip.id,
                'formula_used': result['formula']
            },
            'skip_info': {},
            'formula': result['formula']
        }
        
    def _dynamic_name_with_context(self, date_from: fields.Date, date_to: fields.Date, 
                                  result: Dict[str, Any]) -> str:
        """
        Genera un nombre dinámico basado en el contexto y resultados del cálculo
        
        Args:
            date_from: Fecha inicial
            date_to: Fecha final
            result: Resultado del cálculo
            
        Returns:
            Nombre dinámico para la línea
        """
        fortnight = "1Q" if date_to.day <= 15 else "2Q"
        month_year = f"{date_to.strftime('%b').upper()}/{date_to.year}"
        concept_type = "D" if self.is_deduction else "I"  # Deducción o Ingreso
        name = f"{self.input_id.name} - {fortnight} {month_year}"
        if result.get('days_count'):
            name += f" ({result['days_count']}d"
            if result.get('percentage'):
                name += f", {result['percentage']}%"
            name += ")"
        name += f" [{concept_type}]"
        if self.modality_value == 'diario_efectivo':
            name += " [EFECTIVO]"
        elif self.modality_value == 'proyeccion_completa':
            name += " [PROYECCIÓN]"
            
        return name
    
    def _should_apply_in_period(self, 
                               payslip: models.Model, 
                               date_from: fields.Date, 
                               date_to: fields.Date, 
                               localdict: Dict[str, Any]) -> bool:
        """
        Determina si el concepto debe aplicarse en el período
        
        Args:
            payslip: Nómina
            date_from: Fecha inicial
            date_to: Fecha final
            localdict: Diccionario con variables
            
        Returns:
            True si debe aplicarse
        """
        payslip = cast('hr.payslip', payslip)
        if self.state != 'done' and self.state != 'closed':
            return False
        if self.state == 'closed' and self.closed_date:
            if date_from > self.closed_date:
                return False
        if payslip.id in self.payslip_ids.ids:
            return False
        if self.date_start and date_to < self.date_start:
            return False
        if self.date_end and date_from > self.date_end:
            return False
        if self.last_processed_date:
            if date_to <= self.last_processed_date:
                return False
                
        if self.aplicar == '15' and date_to.day > 15:
            return False
        elif self.aplicar == '30' and date_to.day <= 15:
            return False
        if self.payroll_structure_ids:
            struct_id = localdict.get('struct_id') or payslip.struct_id
            if struct_id.id not in self.payroll_structure_ids.ids:
                if self.base_structure_only and (struct_id.process != 'nomina' or not struct_id.regular_pay):
                    return False
        if self.input_id.condition_select != 'none':
            condition_met = self._evaluate_rule_condition(payslip, localdict)
            if not condition_met:
                return False
                    
        return True
        
    def _evaluate_rule_condition(self, payslip: models.Model, localdict: Dict[str, Any]) -> bool:
        """
        Evalúa la condición de la regla salarial en el contexto dado
        
        Args:
            payslip: Nómina
            localdict: Diccionario con variables
            
        Returns:
            True si la condición se cumple
        """
        payslip = cast('hr.payslip', payslip)
        rule = self.input_id
        if rule.condition_select == 'none':
            return True
        eval_context = dict(localdict)
        eval_context.update({
            'categories': payslip.rule_category_dict,
            'rules': payslip.rule_dict,
            'payslip': payslip,
            'worked_days': payslip.worked_days_dict,
            'inputs': payslip.input_dict,
            'employee': payslip.employee_id,
            'contract': payslip.contract_id,
            'result': None,
            'result_qty': 1.0,
            'result_rate': 100
        })
        
        if rule.condition_select == 'range':
            try:
                eval_context['result'] = eval(rule.condition_range, eval_context, mode='exec', nocopy=True)
                return bool(eval_context['result'])
            except Exception as e:
                _logger.error('Error evaluando condición range: %s', e)
                return False
        elif rule.condition_select == 'python':
            try:
                safe_eval(rule.condition_python, eval_context, mode='exec', nocopy=True)
                return bool(eval_context['result'])
            except Exception as e:
                _logger.error('Error evaluando condición python: %s', e)
                return False
                
        return True
    
    def _concept_already_applied(self, 
                                payslip: models.Model, 
                                date_from: fields.Date, 
                                date_to: fields.Date, 
                                localdict: Dict[str, Any]) -> bool:
        """
        Verifica si el concepto ya fue aplicado en el período
        
        Args:
            payslip: Nómina
            date_from: Fecha inicial
            date_to: Fecha final
            localdict: Diccionario con variables
            
        Returns:
            True si ya fue aplicado
        """
        processed_payslips = localdict.get('processed_payslips', {})
        current_month = date_from.month
        current_year = date_from.year
        current_fortnight = '1' if date_to.day <= 15 else '2'
        
        for p_id, p_data in processed_payslips.items():
            if p_data.get('month') == current_month and p_data.get('year') == current_year:
                for line in p_data.get('lines', []):
                    if line.get('concept_id') == self.id:
                        if self.aplicar == '0':
                            line_fortnight = '1' if line.get('date_to').day <= 15 else '2'
                            if line_fortnight == current_fortnight:
                                return True
                        else:
                            return True
        for line in payslip.line_ids:
            if line.concept_id and line.concept_id.id == self.id:
                return True
                
        return False
    
    def _calculate_amount_for_payslip(self, 
                                     payslip: models.Model, 
                                     date_from: fields.Date, 
                                     date_to: fields.Date, 
                                     localdict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calcula el monto para la nómina según configuración
        
        Args:
            payslip: Nómina
            date_from: Fecha inicial
            date_to: Fecha final
            localdict: Diccionario con variables
            
        Returns:
            Dict con el monto calculado y fórmula utilizada
        """
        precision = localdict.get('precision_technical', PRECISION_TECHNICAL)
        base_amount = self._calculate_base_amount()
        
        if self.modality_value == 'fijo':
            if self.aplicar == '0':
                amount = self.compute_precise(base_amount, 2, '/', precision)
                formula = f"{base_amount:,.2f} ÷ 2"
            else:
                amount = base_amount
                formula = f"{base_amount:,.2f}"
                
            return {
                'amount': amount,
                'formula': formula,
                'quantity': 1,
                'rate': 100
            }
            
        daily_amount = self.compute_precise(base_amount, 30, '/', precision)
        
        es_primera_quincena = date_to.day <= 15
        
        if es_primera_quincena:
            dias_periodo = 15
        else:
            dias_periodo = 15
            if not self.descontar_dia_31:
                if calendar.monthrange(date_to.year, date_to.month)[1] == 31:
                    dias_periodo = 16
        
        dias_trabajados = self._get_worked_days(payslip, date_from, date_to, localdict)
        
        if self.modality_value == 'diario_efectivo':
            dias_calculo = dias_trabajados
            formula = f"Valor diario × Días trabajados = {daily_amount:,.2f} × {dias_calculo}"
        elif self.modality_value == 'dias_trabajo_ausencias_justificadas':
            dias_ausentismo_justificado = self._get_justified_absences(payslip, date_from, date_to, localdict)
            dias_calculo = dias_trabajados + dias_ausentismo_justificado
            formula = f"Valor diario × (Días trabajados + Ausencias justificadas) = {daily_amount:,.2f} × {dias_calculo}"
        elif self.modality_value == 'proyeccion_completa' and not es_primera_quincena:
            monto_primera_quincena = 0
            if self.considerar_primera_quincena:
                monto_primera_quincena = self._get_amount_first_fortnight(payslip, date_from, localdict)
            proyeccion_mensual = self.compute_precise(daily_amount, 30, '*', precision)
            amount = self.compute_precise(proyeccion_mensual, monto_primera_quincena, '-', precision)
            
            formula = f"(Valor diario × 30) - Monto 1Q = ({daily_amount:,.2f} × 30) - {monto_primera_quincena:,.2f}"
            return {
                'amount': amount,
                'formula': formula,
                'days_count': 30 - self._get_worked_days_first_fortnight(payslip, date_from, localdict),
                'quantity': 1,
                'rate': 100
            }
        else:
            dias_calculo = dias_periodo
            formula = f"Valor diario × Días período = {daily_amount:,.2f} × {dias_calculo}"
        
        amount = self.compute_precise(daily_amount, dias_calculo, '*', precision)
        if self.precision_redondeada:
            amount = round(amount)
            formula += f" (redondeado a {amount:,.0f})"
            
        return {
            'amount': amount,
            'formula': formula,
            'days_count': dias_calculo,
            'quantity': dias_calculo,
            'rate': self.compute_precise(dias_calculo, dias_periodo, '/', precision) * 100
        }
    
    def _get_worked_days(self, 
                        payslip: models.Model, 
                        date_from: fields.Date, 
                        date_to: fields.Date, 
                        localdict: Dict[str, Any]) -> float:
        """
        Obtiene los días trabajados en el período según la configuración de ausencias
        
        Args:
            payslip: Nómina
            date_from: Fecha inicial
            date_to: Fecha final
            localdict: Diccionario con variables
            
        Returns:
            Días trabajados
        """
        workable_days = self._get_workable_days(date_from, date_to)
        absence_days = 0
        if self.considerar_ausencias == 'todas':
            absence_days = self._get_absence_days(payslip, date_from, date_to, localdict)
        elif self.considerar_ausencias == 'justificadas':
            absence_days = self._get_justified_absences(payslip, date_from, date_to, localdict)
        
        if self.absence_codes_to_include or self.absence_codes_to_exclude:
            absence_days = self._adjust_absence_days_by_codes(payslip, date_from, date_to, localdict, absence_days)
            
        worked_days = max(0, workable_days - absence_days)
        
        return worked_days
    
    def _get_workable_days(self, date_from: fields.Date, date_to: fields.Date) -> int:
        """
        Calcula los días laborables en el período según configuración
        
        Args:
            date_from: Fecha inicial
            date_to: Fecha final
            
        Returns:
            Número de días laborables
        """
        delta = (date_to - date_from).days + 1
        workable_days = delta
        if self.excluir_sabados or self.excluir_domingos or self.excluir_festivos:
            current_date = date_from
            excluded_days = 0
            
            while current_date <= date_to:
                if self.excluir_sabados and current_date.weekday() == 5:
                    excluded_days += 1
                elif self.excluir_domingos and current_date.weekday() == 6:
                    excluded_days += 1
                elif self.excluir_festivos and self._is_holiday(current_date):
                    excluded_days += 1
                    
                current_date += timedelta(days=1)
                
            workable_days -= excluded_days
            
        return workable_days
    
    def _is_holiday(self, date_check: fields.Date) -> bool:
        """
        Verifica si la fecha es festivo (debe implementarse según el calendario de festivos)
        
        Args:
            date_check: Fecha a verificar
            
        Returns:
            True si es festivo
        """
        # Implementar consulta a calendario de festivos
        # Por ahora, es un placeholder
        holiday_calendar = self.env['resource.calendar'].search([
            ('country_id', '=', self.company_id.country_id.id), 
            ('global_leave_ids.date_from', '<=', date_check),
            ('global_leave_ids.date_to', '>=', date_check)
        ], limit=1)
        
        if holiday_calendar:
            return True
            
        return False
    
    def _get_absence_days(self, 
                         payslip: models.Model, 
                         date_from: fields.Date, 
                         date_to: fields.Date, 
                         localdict: Dict[str, Any]) -> float:
        """
        Obtiene los días de ausencia en el período
        
        Args:
            payslip: Nómina
            date_from: Fecha inicial
            date_to: Fecha final
            localdict: Diccionario con variables
            
        Returns:
            Días de ausencia
        """
        absence_days = 0
        
        absence_entries = localdict.get('worked_days_line_ids', [])
        
        if not absence_entries and payslip:
            absence_entries = payslip.worked_days_line_ids
        
        for entry in absence_entries:
            work_entry_type_id = entry.work_entry_type_id if hasattr(entry, 'work_entry_type_id') else entry.get('work_entry_type_id')
            
            if work_entry_type_id and self._is_absence_type(work_entry_type_id):
                number_of_days = entry.number_of_days if hasattr(entry, 'number_of_days') else entry.get('number_of_days', 0)
                absence_days += number_of_days
                
        return absence_days
    
    def _is_absence_type(self, work_entry_type: Union[models.Model, int]) -> bool:
        """
        Verifica si el tipo de entrada de trabajo es una ausencia
        
        Args:
            work_entry_type: Tipo de entrada de trabajo o su ID
            
        Returns:
            True si es ausencia
        """
        if isinstance(work_entry_type, int):
            work_entry_type = self.env['hr.work.entry.type'].browse(work_entry_type)
            
        return work_entry_type.is_leave
    
    def _get_justified_absences(self, 
                               payslip: models.Model, 
                               date_from: fields.Date, 
                               date_to: fields.Date, 
                               localdict: Dict[str, Any]) -> float:
        """
        Obtiene los días de ausencias justificadas en el período
        
        Args:
            payslip: Nómina
            date_from: Fecha inicial
            date_to: Fecha final
            localdict: Diccionario con variables
            
        Returns:
            Días de ausencias justificadas
        """
        justified_days = 0
        absence_entries = localdict.get('worked_days_line_ids', [])
        if not absence_entries and payslip:
            absence_entries = payslip.worked_days_line_ids
        justified_codes = self._get_justified_absence_codes()
        for entry in absence_entries:
            work_entry_type_id = entry.work_entry_type_id if hasattr(entry, 'work_entry_type_id') else entry.get('work_entry_type_id')
            if work_entry_type_id and self._is_absence_type(work_entry_type_id):
                code = work_entry_type_id.code if hasattr(work_entry_type_id, 'code') else self._get_work_entry_type_code(work_entry_type_id)
                if code in justified_codes:
                    number_of_days = entry.number_of_days if hasattr(entry, 'number_of_days') else entry.get('number_of_days', 0)
                    justified_days += number_of_days
                
        return justified_days
    
    def _get_justified_absence_codes(self) -> List[str]:
        """
        Obtiene la lista de códigos de ausencias justificadas
        
        Returns:
            Lista de códigos
        """
        return [
            'LEAVE100',        
            'LEAVE105',         
            'LEAVE120',    
            'EGA',            
            'EGH',             
            'VACDISFRUTADAS',  
            'PAT',             
            'MAT',          
            'LUTO',           
            'EP',               
            'AT',               
            'LICENCIA004'   
        ]
    
    def _get_work_entry_type_code(self, work_entry_type_id: Union[models.Model, int]) -> str:
        """
        Obtiene el código de un tipo de entrada de trabajo
        
        Args:
            work_entry_type_id: Tipo de entrada de trabajo o su ID
            
        Returns:
            Código del tipo de entrada
        """
        if isinstance(work_entry_type_id, int):
            work_entry_type = self.env['hr.work.entry.type'].browse(work_entry_type_id)
            return work_entry_type.code
            
        if isinstance(work_entry_type_id, dict):
            return work_entry_type_id.get('code', '')
            
        return work_entry_type_id.code
    
    def _adjust_absence_days_by_codes(self, 
                                     payslip: models.Model, 
                                     date_from: fields.Date, 
                                     date_to: fields.Date, 
                                     localdict: Dict[str, Any],
                                     current_absence_days: float) -> float:
        """
        Ajusta los días de ausencia según los códigos a incluir/excluir
        
        Args:
            payslip: Nómina
            date_from: Fecha inicial
            date_to: Fecha final
            localdict: Diccionario con variables
            current_absence_days: Días de ausencia actuales
            
        Returns:
            Días de ausencia ajustados
        """
        if not self.absence_codes_to_include and not self.absence_codes_to_exclude:
            return current_absence_days
            
        absence_entries = localdict.get('worked_days_line_ids', [])
        
        if not absence_entries and payslip:
            absence_entries = payslip.worked_days_line_ids
            
        codes_to_include = self.absence_codes_to_include.split(',') if self.absence_codes_to_include else []
        codes_to_exclude = self.absence_codes_to_exclude.split(',') if self.absence_codes_to_exclude else []
        
        codes_to_include = [code.strip() for code in codes_to_include]
        codes_to_exclude = [code.strip() for code in codes_to_exclude]
        
        if codes_to_include:
            adjusted_days = 0
            for entry in absence_entries:
                work_entry_type_id = entry.work_entry_type_id if hasattr(entry, 'work_entry_type_id') else entry.get('work_entry_type_id')
                
                if work_entry_type_id:
                    code = self._get_work_entry_type_code(work_entry_type_id)
                    if code in codes_to_include:
                        number_of_days = entry.number_of_days if hasattr(entry, 'number_of_days') else entry.get('number_of_days', 0)
                        adjusted_days += number_of_days
                        
            return adjusted_days
        
        if codes_to_exclude:
            for entry in absence_entries:
                work_entry_type_id = entry.work_entry_type_id if hasattr(entry, 'work_entry_type_id') else entry.get('work_entry_type_id')
                
                if work_entry_type_id:
                    code = self._get_work_entry_type_code(work_entry_type_id)
                    if code in codes_to_exclude:
                        number_of_days = entry.number_of_days if hasattr(entry, 'number_of_days') else entry.get('number_of_days', 0)
                        current_absence_days -= number_of_days
                        
            return max(0, current_absence_days)
            
        return current_absence_days
    
    def _get_amount_first_fortnight(self, 
                                   payslip: models.Model, 
                                   date_from: fields.Date, 
                                   localdict: Dict[str, Any]) -> float:
        """
        Obtiene el monto pagado en la primera quincena
        
        Args:
            payslip: Nómina
            date_from: Fecha inicial
            localdict: Diccionario con variables
            
        Returns:
            Monto pagado en primera quincena
        """
        processed_payslips = localdict.get('processed_payslips', {})
        current_month = date_from.month
        current_year = date_from.year
        
        amount = 0
        for p_id, p_data in processed_payslips.items():
            if (p_data.get('month') == current_month and 
                p_data.get('year') == current_year and 
                p_data.get('date_to').day <= 15):
                
                for line in p_data.get('lines', []):
                    if line.get('concept_id') == self.id:
                        amount += line.get('total', 0)
                        
        return amount
    
    def _get_worked_days_first_fortnight(self, 
                                        payslip: models.Model, 
                                        date_from: fields.Date, 
                                        localdict: Dict[str, Any]) -> float:
        """
        Obtiene los días trabajados en la primera quincena
        
        Args:
            payslip: Nómina
            date_from: Fecha inicial
            localdict: Diccionario con variables
            
        Returns:
            Días trabajados en primera quincena
        """
        processed_payslips = localdict.get('processed_payslips', {})
        current_month = date_from.month
        current_year = date_from.year
        worked_days = 0
        for p_id, p_data in processed_payslips.items():
            if (p_data.get('month') == current_month and 
                p_data.get('year') == current_year and 
                p_data.get('date_to').day <= 15):
                worked_days += p_data.get('worked_days', 0)
                        
        return worked_days
    
    def _notify_skip_application(self, skip: models.Model, payslip: models.Model) -> None:
        """
        Envía notificación sobre la aplicación de un salto
        
        Args:
            skip: Salto aplicado
            payslip: Nómina
        """
        if not self.skip_notification:
            return
        msg = _("""
            <div class="o_mail_notification">
                <div><strong>Salto de cuota aplicado</strong></div>
                <div>Se ha aplicado un salto para el período %s.</div>
                <div>Concepto: %s</div>
                <div>Empleado: %s</div>
            </div>
        """) % (
            skip.period_skip.strftime('%d/%m/%Y'), 
            self.name or '',
            self.employee_id.name or ''
        )
        self.message_post(body=msg, subtype_xmlid="mail.mt_comment")
        
        if self.employee_id.user_id and skip.notify_employee:
            self.employee_id.user_id.notify_info(
                message=_("Se ha aplicado un salto para el concepto '%s' en el período %s.") % (
                    self.name or '', 
                    skip.period_skip.strftime('%d/%m/%Y')
                ),
                title=_("Salto de Concepto Aplicado"),
                sticky=True
            )
    
    #==================================================
    # MÉTODOS DE ACCIÓN (BOTONES)
    #==================================================
    def action_draft(self) -> Dict:
        """Establece el estado como borrador"""
        return self.write({'state': 'draft'})
        
    def action_approve(self) -> Dict:
        """Aprueba el concepto"""
        for record in self:
            if not record.input_id:
                raise UserError(_("Debe seleccionar una regla salarial para aprobar el concepto."))
                
            if record.period == 'limited':
                if not record.date_start:
                    raise UserError(_("Debe definir una fecha de inicio para conceptos limitados."))
                    
            rule_config = record.validate_salary_rule_configuration(record.input_id)
            if not rule_config['is_valid']:
                raise UserError(_("La configuración de la regla salarial no es válida:\n%s") % (
                    "\n".join(rule_config['warnings'])
                ))
                
            if rule_config['warnings']:
                message = _("El concepto ha sido aprobado con las siguientes advertencias:\n%s") % (
                    "\n".join(rule_config['warnings'])
                )
                record.message_post(body=message, subtype_xmlid="mail.mt_comment")
                
        return self.write({'state': 'done'})
        
    def action_close(self) -> Dict[str, Any]:
        """
        Cierra el concepto, registrando la nómina asociada al cierre
        
        Returns:
            Diccionario con resultado de la acción
        """
        for record in self:
            if record.state != 'done':
                raise UserError(_("Solo se pueden cerrar conceptos aprobados."))
                
            payslip_id = self.env.context.get('payslip_id') or self.env.context.get('active_id') \
                if self.env.context.get('active_model') == 'hr.payslip' else False
                
            if payslip_id:
                payslip = self.env['hr.payslip'].browse(payslip_id)
                if payslip.state in ['done', 'paid']:
                    record.closed_payslip_id = payslip.id
            
            values = {
                'state': 'closed',
                'closed_date': fields.Date.today()
            }
            msg = _("""
                <div class="o_mail_notification">
                    <div><strong>Concepto cerrado</strong></div>
                    <div>Fecha de cierre: %s</div>
                    %s
                    <div>Motivo: %s</div>
                </div>
            """) % (
                fields.Date.today().strftime('%d/%m/%Y'), 
                _("<div>Nómina de cierre: %s</div>") % record.closed_payslip_id.name if record.closed_payslip_id else "",
                record.closed_reason or _("No especificado")
            )
            
            record.message_post(body=msg, subtype_xmlid="mail.mt_comment")
                
        return self.write(values)
        
    def action_cancel(self) -> Dict:
        """Cancela el concepto"""
        return self.write({
            'state': 'cancel',
            'cancel_date': fields.Date.today()
        })
        
    def action_create_skip(self) -> Dict:
        """Abre el asistente para crear un nuevo salto"""
        self.ensure_one()
        
        if not self.allow_skips:
            raise UserError(_("No se permite crear saltos para este concepto."))
            
        if self.state not in ['done', 'closed']:
            raise UserError(_("Solo se pueden crear saltos para conceptos aprobados o cerrados."))
            
        # Crear un asistente para el salto
        wizard = self.env['hr.concept.skip.wizard'].create({
            'concept_id': self.id,
            'fortnight': '15',  # Por defecto primera quincena
            'period_skip': fields.Date.today(),
            'recovery_type': 'next',
            'notify_employee': self.skip_notification,
        })
        
        return {
            'name': _('Crear Salto de Cuota'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.concept.skip.wizard',
            'view_mode': 'form',
            'res_id': wizard.id,
            'target': 'new',
        }
        
    def action_force_double_payment(self) -> Dict:
        """Abre el asistente para configurar un pago doble"""
        self.ensure_one()
        
        if self.state not in ['done']:
            raise UserError(_("Solo se pueden forzar pagos dobles para conceptos aprobados."))
            
        wizard = self.env['hr.concept.double.payment.wizard'].create({
            'concept_id': self.id,
            'payment_date': fields.Date.today(),
        })
        
        return {
            'name': _('Configurar Pago Doble'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.concept.double.payment.wizard',
            'view_mode': 'form',
            'res_id': wizard.id,
            'target': 'new',
        }
        
    def view_skips(self) -> Dict:
        """Muestra los saltos del concepto"""
        self.ensure_one()
        
        return {
            'name': _('Saltos de "%s"') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'hr.contract.concept.skip',
            'view_mode': 'tree,form',
            'domain': [('concept_id', '=', self.id)],
            'context': {'default_concept_id': self.id},
        }
        
    def view_payslip_lines(self) -> Dict:
        """Muestra las líneas de nómina generadas por el concepto"""
        self.ensure_one()
        
        return {
            'name': _('Líneas de Nómina de "%s"') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'hr.payslip.line',
            'view_mode': 'tree,form',
            'domain': [('concept_id', '=', self.id)],
            'context': {'default_concept_id': self.id},
        }
        
    def view_simulation(self) -> Dict:
        """Muestra la simulación del concepto"""
        self.ensure_one()
        
        wizard = self.env['hr.concept.simulation.wizard'].create({
            'concept_id': self.id,
            'simulation_date': fields.Date.today(),
            'simulation_result': self.simulation_text,
        })
        
        return {
            'name': _('Simulación de "%s"') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'hr.concept.simulation.wizard',
            'view_mode': 'form',
            'res_id': wizard.id,
            'target': 'new',
        }
        
    def _suggest_skips_for_absences(self) -> List[Dict]:
        """
        Sugiere saltos basados en ausencias del empleado
        
        Returns:
            Lista de sugerencias de saltos
        """
        self.ensure_one()
        suggestions = []
        
        if not self.auto_skip_suggestion:
            return suggestions
            
        today = fields.Date.today()
        start_date = today - timedelta(days=30)
        
        absences = self.env['hr.leave'].search([
            ('employee_id', '=', self.employee_id.id),
            ('state', '=', 'validate'),
            ('date_from', '>=', start_date),
            ('date_to', '<=', today)
        ], limit=5)
        
        for absence in absences:
            duration = (absence.date_to - absence.date_from).days
            if duration >= 5:
                next_payment_date = self.next_payment_date
                if next_payment_date:
                    suggestions.append({
                        'period_skip': next_payment_date,
                        'reason': _("Ausencia extensa de %s días (%s)") % (
                            duration, 
                            absence.holiday_status_id.name
                        ),
                        'fortnight': '15' if next_payment_date.day <= 15 else '30',
                    })
                    
        return suggestions
    
    def action_check_close_ready(self) -> None:
        """
        Verifica conceptos listos para cerrar y notifica
        """
        concepts = self.search([
            ('state', '=', 'done'),
            ('close_ready', '=', True)
        ])
        
        if concepts:
            for concept in concepts:
                msg = _("""
                    <div class="o_mail_notification">
                        <div><strong>Concepto listo para cierre</strong></div>
                        <div>El concepto %s está listo para ser cerrado.</div>
                        <div>Empleado: %s</div>
                        <div>Razón: %s</div>
                    </div>
                """) % (
                    concept.name or '', 
                    concept.employee_id.name or '',
                    _("Balance completado") if concept.balance <= 0 else _("Fecha límite alcanzada")
                )
                
                concept.message_post(body=msg, subtype_xmlid="mail.mt_comment")

class HrConceptSkipWizard(models.TransientModel):
    _name = 'hr.concept.skip.wizard'
    _description = 'Asistente para Crear Saltos de Conceptos'
    
    concept_id = fields.Many2one('hr.contract.concepts', 'Concepto', required=True)
    employee_id = fields.Many2one(related='concept_id.employee_id', readonly=True)
    
    period_skip = fields.Date('Fecha de Salto', required=True, default=fields.Date.today)
    fortnight = fields.Selection([
        ('15', 'Primera quincena'),
        ('30', 'Segunda quincena')
    ], string='Quincena', required=True, default='15')
    
    recovery_type = fields.Selection([
        ('none', 'Sin recuperación'),
        ('next', 'Siguiente cuota'),
        ('distributed', 'Distribuido en varias cuotas'),
        ('specific_date', 'Fecha específica')
    ], string='Tipo de Recuperación', required=True, default='next')
    
    recovery_date = fields.Date('Fecha de Recuperación')
    installments_number = fields.Integer('Número de Cuotas', default=1)
    
    reason = fields.Text('Motivo', required=True)
    notes = fields.Text('Notas Adicionales')
    
    notify_employee = fields.Boolean('Notificar Empleado', default=True)
    notify_supervisor = fields.Boolean('Notificar Supervisor', default=True)
    
    related_absence_id = fields.Many2one('hr.leave', 'Ausencia Relacionada')
    auto_approve = fields.Boolean('Aprobar automáticamente', default=True)
    
    @api.onchange('period_skip', 'fortnight')
    def _onchange_period(self) -> None:
        """Actualiza la fecha al cambiar el período o quincena"""
        if self.period_skip:
            day = 15 if self.fortnight == '15' else self._get_last_day_of_month(self.period_skip).day
            self.period_skip = date(self.period_skip.year, self.period_skip.month, day)
    
    @api.onchange('recovery_type')
    def _onchange_recovery_type(self) -> None:
        """Actualiza campos relacionados al cambiar el tipo de recuperación"""
        if self.recovery_type == 'none':
            self.recovery_date = False
            self.installments_number = 0
        elif self.recovery_type == 'next':
            self.installments_number = 1
            if self.period_skip:
                if self.fortnight == '15':
                    self.recovery_date = self._get_last_day_of_month(self.period_skip)
                else:
                    next_month = self.period_skip + relativedelta(months=1)
                    self.recovery_date = date(next_month.year, next_month.month, 15)
        elif self.recovery_type == 'distributed':
            self.installments_number = 2
            self.recovery_date = False
        elif self.recovery_type == 'specific_date':
            self.installments_number = 1
    
    def _get_last_day_of_month(self, reference_date: date) -> date:
        """
        Obtiene el último día del mes de una fecha dada
        
        Args:
            reference_date: Fecha de referencia
            
        Returns:
            Fecha del último día del mes
        """
        next_month = reference_date + relativedelta(months=1, day=1)
        return next_month - timedelta(days=1)
    
    def action_create_skip(self) -> Dict[str, Any]:
        """
        Crea un nuevo salto con los datos del asistente
        
        Returns:
            Diccionario con resultado de la acción
        """
        self.ensure_one()
        if self.recovery_type == 'specific_date' and not self.recovery_date:
            raise UserError(_("Debe especificar una fecha de recuperación."))
            
        if self.recovery_type == 'distributed' and self.installments_number < 1:
            raise UserError(_("El número de cuotas para distribución debe ser al menos 1."))
        values = {
            'concept_id': self.concept_id.id,
            'period_skip': self.period_skip,
            'fortnight': self.fortnight,
            'recovery_type': self.recovery_type,
            'recovery_date': self.recovery_date,
            'installments_number': self.installments_number,
            'reason': self.reason,
            'notes': self.notes,
            'notify_employee': self.notify_employee,
            'notify_supervisor': self.notify_supervisor,
            'related_absence_id': self.related_absence_id.id if self.related_absence_id else False,
            'state': 'approved' if self.auto_approve else 'draft',
        }
        
        skip = self.env['hr.contract.concept.skip'].create(values)
        if self.auto_approve:
            skip.write({
                'approval_date': fields.Date.today(),
                'approved_by': self.env.user.id
            })
            skip._send_notifications('approve')
        
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hr.contract.concept.skip',
            'view_mode': 'form',
            'res_id': skip.id,
            'target': 'current',
        }


class HrConceptDoublePaymentWizard(models.TransientModel):
    _name = 'hr.concept.double.payment.wizard'
    _description = 'Asistente para Configurar Pago Doble'
    
    concept_id = fields.Many2one('hr.contract.concepts', 'Concepto', required=True)
    employee_id = fields.Many2one(related='concept_id.employee_id', readonly=True)
    
    payment_date = fields.Date('Fecha de Pago Doble', required=True, default=fields.Date.today)
    reason = fields.Text('Motivo', required=True)
    
    def action_confirm(self) -> Dict[str, Any]:
        """
        Configura el pago doble en el concepto
        
        Returns:
            Diccionario con resultado de la acción
        """
        self.ensure_one()
        self.concept_id.write({
            'force_double_payment': True,
            'double_payment_date': self.payment_date
        })
        
        msg = _("""
            <div class="o_mail_notification">
                <div><strong>Pago Doble Configurado</strong></div>
                <div>Se ha configurado un pago doble para la fecha %s.</div>
                <div>Motivo: %s</div>
            </div>
        """) % (
            self.payment_date.strftime('%d/%m/%Y'), 
            self.reason or _("No especificado")
        )
        
        self.concept_id.message_post(body=msg, subtype_xmlid="mail.mt_comment")
        
        return {'type': 'ir.actions.act_window_close'}


class HrConceptSimulationWizard(models.TransientModel):
    _name = 'hr.concept.simulation.wizard'
    _description = 'Asistente para Simulación de Concepto'
    
    concept_id = fields.Many2one('hr.contract.concepts', 'Concepto', required=True)
    employee_id = fields.Many2one(related='concept_id.employee_id', readonly=True)
    contract_id = fields.Many2one(related='concept_id.contract_id', readonly=True)
    
    simulation_date = fields.Date('Fecha de Simulación', default=fields.Date.today)
    is_first_fortnight = fields.Boolean('Primera Quincena', compute='_compute_fortnight')
    
    # Resultado de la simulación
    simulation_result = fields.Html('Resultado de Simulación', readonly=True)
    estimated_amount = fields.Float('Monto Estimado', compute='_compute_estimation')
    days_count = fields.Integer('Días Estimados', compute='_compute_estimation')
    
    # Acciones adicionales
    create_skip = fields.Boolean('Crear Salto', default=False)
    skip_reason = fields.Text('Motivo del Salto')
    
    @api.depends('simulation_date')
    def _compute_fortnight(self) -> None:
        """Determina si es primera o segunda quincena"""
        for record in self:
            record.is_first_fortnight = record.simulation_date.day <= 15
    
    @api.depends('concept_id', 'simulation_date', 'is_first_fortnight')
    def _compute_estimation(self) -> None:
        """Calcula estimación de monto y días"""
        for record in self:
            if not record.concept_id or not record.simulation_date:
                record.estimated_amount = 0.0
                record.days_count = 0
                continue
            if record.is_first_fortnight:
                date_from = date(record.simulation_date.year, record.simulation_date.month, 1)
                date_to = date(record.simulation_date.year, record.simulation_date.month, 15)
            else:
                date_from = date(record.simulation_date.year, record.simulation_date.month, 16)
                date_to = self._get_last_day_of_month(record.simulation_date)
                
            base_amount = record.concept_id._calculate_base_amount()
            if record.concept_id.modality_value == 'fijo':
                if record.concept_id.aplicar == '0':  # Ambas quincenas
                    record.estimated_amount = record.concept_id.compute_precise(base_amount, 2, '/')
                else:
                    record.estimated_amount = base_amount
                record.days_count = 15  # Valor por defecto
            else:
                daily_amount = record.concept_id.compute_precise(base_amount, 30, '/')
                dias_periodo = (date_to - date_from).days + 1
                record.days_count = dias_periodo
                record.estimated_amount = record.concept_id.compute_precise(daily_amount, dias_periodo, '*')
    
    def _get_last_day_of_month(self, reference_date: date) -> date:
        """
        Obtiene el último día del mes de una fecha dada
        
        Args:
            reference_date: Fecha de referencia
            
        Returns:
            Fecha del último día del mes
        """
        next_month = reference_date + relativedelta(months=1, day=1)
        return next_month - timedelta(days=1)
    
    def action_create_skip(self) -> Dict[str, Any]:
        """
        Abre asistente para crear salto desde la simulación
        
        Returns:
            Diccionario con acción para abrir el asistente
        """
        self.ensure_one()
        
        if not self.skip_reason:
            raise UserError(_("Debe especificar un motivo para crear el salto."))
            
        wizard = self.env['hr.concept.skip.wizard'].create({
            'concept_id': self.concept_id.id,
            'period_skip': self.simulation_date,
            'fortnight': '15' if self.is_first_fortnight else '30',
            'reason': self.skip_reason,
        })
        
        return {
            'name': _('Crear Salto de Cuota'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.concept.skip.wizard',
            'view_mode': 'form',
            'res_id': wizard.id,
            'target': 'new',
        }


class HrConceptCloseWizard(models.TransientModel):
    _name = 'hr.concept.close.wizard'
    _description = 'Asistente para Cierre de Concepto'
    
    concept_id = fields.Many2one('hr.contract.concepts', 'Concepto', required=True)
    employee_id = fields.Many2one(related='concept_id.employee_id', readonly=True)
    
    closed_reason = fields.Text('Motivo de Cierre', required=True)
    
    # Información del concepto para confirmación
    accumulated_amount = fields.Float(related='concept_id.accumulated_amount', readonly=True)
    balance = fields.Float(related='concept_id.balance', readonly=True)
    
    payslip_id = fields.Many2one('hr.payslip', 'Nómina de Cierre', 
                              domain="[('employee_id', '=', employee_id), ('state', 'in', ['done', 'paid'])]")
    
    def action_close_concept(self) -> Dict[str, Any]:
        """
        Cierra el concepto con los datos del asistente
        
        Returns:
            Diccionario con resultado de la acción
        """
        self.ensure_one()
        self.concept_id.write({
            'closed_reason': self.closed_reason
        })
        
        if self.payslip_id:
            ctx = {'payslip_id': self.payslip_id.id}
            self.concept_id.with_context(ctx).action_close()
        else:
            self.concept_id.action_close()
        
        return {'type': 'ir.actions.act_window_close'}    
class HrConceptCloseWizard(models.TransientModel):
    _name = 'hr.concept.close.wizard'
    _description = 'Asistente para Cierre de Concepto'
    
    concept_id = fields.Many2one('hr.contract.concepts', 'Concepto', required=True)
    employee_id = fields.Many2one(related='concept_id.employee_id', readonly=True)
    
    closed_reason = fields.Text('Motivo de Cierre', required=True)
    
    # Información del concepto para confirmación
    accumulated_amount = fields.Float(related='concept_id.accumulated_amount', readonly=True)
    balance = fields.Float(related='concept_id.balance', readonly=True)
    
    payslip_id = fields.Many2one('hr.payslip', 'Nómina de Cierre', 
                              domain="[('employee_id', '=', employee_id), ('state', 'in', ['done', 'paid'])]")
    
    def action_close_concept(self) -> Dict[str, Any]:
        """
        Cierra el concepto con los datos del asistente
        
        Returns:
            Diccionario con resultado de la acción
        """
        self.ensure_one()
        self.concept_id.write({
            'closed_reason': self.closed_reason
        })
        
        if self.payslip_id:
            ctx = {'payslip_id': self.payslip_id.id}
            self.concept_id.with_context(ctx).action_close()
        else:
            self.concept_id.action_close()
        
        return {'type': 'ir.actions.act_window_close'}             
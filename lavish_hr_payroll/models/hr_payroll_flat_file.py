# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import datetime, timedelta
from pytz import timezone

import base64
import io
import xlsxwriter
#---------------------------Modelo para generar Archivo plano de pago de nómina-------------------------------#

class PayrollFileProcessLog(models.Model):
    _name = 'payroll.file.process.log'
    _description = 'Log de Proceso de Archivos de Pago'
    _order = 'create_date desc'

    flat_file_id = fields.Many2one('hr.payroll.flat.file', 'Proceso')
    date = fields.Datetime('Fecha', default=fields.Datetime.now)
    type = fields.Selection([
        ('error', 'Error'),
        ('warning', 'Advertencia'),
        ('info', 'Información')
    ], string='Tipo', default='error')
    employee_id = fields.Many2one('hr.employee', 'Empleado')
    payslip_id = fields.Many2one('hr.payslip', 'Nómina')
    payslip_number = fields.Char(related='payslip_id.number', string='Número de nómina')
    bank_id = fields.Many2one('res.bank', 'Banco')
    account_number = fields.Char('Número de cuenta')
    error_type = fields.Selection([
        ('bank_missing', 'Falta cuenta bancaria'),
        ('multiple_banks', 'Múltiples cuentas principales'),
        ('invalid_bank', 'Banco no válido'),
        ('amount_error', 'Error en monto'),
        ('other', 'Otro')
    ], string='Tipo de Error')
    name = fields.Char('Descripción')
    detail = fields.Text('Detalle')

    def name_get(self):
        return [(log.id, f"{dict(log._fields['type'].selection).get(log.type)} - {log.employee_id.name or ''} - {log.name}") for log in self]



class HrPayrollFlatFileDetail(models.Model):
    _name = 'hr.payroll.flat.file.detail'
    _description = 'Archivo plano de pago de nómina detalle - Archivos planos'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    flat_file_id = fields.Many2one(
        'hr.payroll.flat.file',
        string='Proceso',
        tracking=True
    )
    journal_id = fields.Many2one(
        'account.journal', 
        string='Diario', 
        domain=[('is_payroll_spreader', '=', True)],
        tracking=True
    )
    employee_id = fields.Many2one(
        'hr.employee', 
        string='Empleado',
        tracking=True
    )
    liquidations_ids = fields.Many2many(
        'hr.payslip', 
        'hr_payroll_flat_file_detail_slip_rel',
        'detail_id',
        'slip_id',
        string='Liquidaciones', 
        #domain=[('definitive_plan', '=', False),('payslip_run_id', '=', False)],
        tracking=True
    )

    txt_file = fields.Binary('Archivo plano file')
    txt_file_name = fields.Char('Archivo plano filename')
    excel_file = fields.Binary('Excel')
    excel_file_name = fields.Char('Excel filename')

    plane_type = fields.Selection([
        ('alianza','Alianza Fiduciaria'),
        ('bancolombiasap', 'Bancolombia SAP'),
        ('bancolombiapab', 'Bancolombia PAB'),
        ('davivienda1', 'Davivienda 1'),
        ('occired', 'Occired'),
        ('avvillas1', 'AV VILLAS 1'),
        ('bancobogota', 'Banco Bogotá'),
        ('popular', 'Banco Popular'),
        ('bbva', 'Banco BBVA'),
        ('not_include', 'Reglas no incluidas'),
    ], string='Tipo de Plano', tracking=True)
    amount_total = fields.Float(
        'Total a Pagar',
        compute='_compute_amount_total',
        store=True
    )
    amount_excluded = fields.Float(
        'Total Excluido',
        compute='_compute_amount_total',
        store=True
    )
    employee_count = fields.Integer(
        'Número de Empleados',
        compute='_compute_employee_count',
        store=True
    )
    payslip_count = fields.Integer(
        'Número de Nóminas',
        compute='_compute_payslip_count',
        store=True
    )

    # Campos informativos
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('generated', 'Generado'),
        ('downloaded', 'Descargado')
    ], string='Estado', default='draft', tracking=True)
    notes = fields.Text('Notas')
    generation_date = fields.Datetime(
        'Fecha Generación',
        default=fields.Datetime.now,
        readonly=True
    )
    payment_status = fields.Selection([
        ('draft', 'Borrador'),
        ('paid', 'Pagado'),
        ('unpaid', 'No Pagado'),
        ('partial', 'Pago Parcial')
    ], string='Estado de Pago', default='draft', tracking=True)
    
    unpaid_payslip_ids = fields.Many2many(
        'hr.payslip',
        'hr_payroll_flat_file_detail_unpaid_slip_rel',
        'detail_id',
        'slip_id',
        string='Nóminas No Pagadas',
        tracking=True
    )
    
  
    current_balance = fields.Float(
        'Saldo Actual',
        compute='_compute_current_balance',
        store=True
    )
    
    projected_balance = fields.Float(
        'Saldo Proyectado',
        compute='_compute_projected_balance',
        store=True
    )
    
    dispersion_account_info = fields.Html(
        'Información Cuentas Dispersión',
        compute='_compute_dispersion_account_info',
        sanitize=False
    )


    def _get_account_balance(self, account, date=None):
        """Obtener saldo de cuenta a una fecha específica"""
        domain = [
            ('account_id', '=', account.id),
            ('parent_state', '=', 'posted')
        ]
        
        if date:
            domain.append(('date', '<=', date))
            
        moves = self.env['account.move.line'].read_group(
            domain=domain,
            fields=['balance:sum'],
            groupby=['account_id']
        )
        
        return moves[0]['balance'] if moves else 0.0

    @api.depends('journal_id')
    def _compute_current_balance(self):
        for record in self:
            if record.journal_id and record.journal_id.default_account_id:
                record.current_balance = self._get_account_balance(
                    record.journal_id.default_account_id,
                    fields.Date.today()
                )
            else:
                record.current_balance = 0.0

    @api.depends('current_balance', 'amount_total', 'flat_file_id.application_date')
    def _compute_projected_balance(self):
        for record in self:
            # Obtener movimientos futuros programados
            if record.journal_id and record.journal_id.default_account_id:
                future_moves = self.env['account.move.line'].search([
                    ('account_id', '=', record.journal_id.default_account_id.id),
                    ('parent_state', '=', 'posted'),
                    ('date', '<=', record.flat_file_id.application_date),
                    ('date', '>', fields.Date.today())
                ])
                
                future_balance = sum(future_moves.mapped('balance'))
                record.projected_balance = record.current_balance + future_balance - record.amount_total
            else:
                record.projected_balance = 0.0

    @api.depends('journal_id', 'current_balance', 'projected_balance', 'flat_file_id.application_date')
    def _compute_dispersion_account_info(self):
        for record in self:
            dispersion_journals = self.env['account.journal'].search([
                ('is_payroll_spreader', '=', True),
                ('company_id', '=', record.flat_file_id.company_id.id)
            ])

            html = ['<div class="table-responsive">',
                   '<table class="table table-bordered table-sm">',
                   '<thead><tr>',
                   '<th>Diario</th>',
                   '<th>Cuenta</th>',
                   '<th>Saldo Actual</th>',
                   '<th>Movimientos Programados</th>',
                   '<th>Saldo Proyectado</th>',
                   '</tr></thead>',
                   '<tbody>']

            for journal in dispersion_journals:
                if not journal.default_account_id:
                    continue
                    
                # Saldo actual
                current_balance = self._get_account_balance(
                    journal.default_account_id,
                    fields.Date.today()
                )
                
                # Movimientos futuros programados
                future_moves = self.env['account.move.line'].search([
                    ('account_id', '=', journal.default_account_id.id),
                    ('parent_state', '=', 'posted'),
                    ('date', '<=', record.flat_file_id.application_date),
                    ('date', '>', fields.Date.today())
                ])
                scheduled_balance = sum(future_moves.mapped('balance'))
                
                # Saldo proyectado
                projected = current_balance + scheduled_balance
                if journal == record.journal_id:
                    projected -= record.amount_total

                # Definir estilo basado en saldos
                style = ''
                if projected < 0:
                    style = 'color: red; font-weight: bold;'
                elif projected < 1000000:  # Alerta si es menor a 1M
                    style = 'color: orange;'

                html.extend([
                    f'<tr style="{style}">',
                    f'<td>{journal.name}</td>',
                    f'<td>{journal.bank_account_id.acc_number if journal.bank_account_id else ""}</td>',
                    f'<td class="text-end">{"{:,.2f}".format(current_balance)}</td>',
                    f'<td class="text-end">{"{:,.2f}".format(scheduled_balance)}</td>',
                    f'<td class="text-end">{"{:,.2f}".format(projected)}</td>',
                    '</tr>'
                ])

            html.extend(['</tbody></table></div>'])
            record.dispersion_account_info = ''.join(html)

    def action_mark_payslip_unpaid(self):
        """Abrir wizard para marcar nómina como no pagada"""
        self.ensure_one()
        return {
            'name': _('Marcar Nómina como No Pagada'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.payroll.unpaid.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_detail_id': self.id,
                #'default_payslip_ids': self.liquidations_ids.ids,
            }
        }

    def mark_payslip_as_unpaid(self, payslip_id, reason, notes):
        """Marcar una nómina específica como no pagada"""
        self.ensure_one()
        payslip = self.env['hr.payslip'].browse(payslip_id)
        
        if payslip not in self.liquidations_ids:
            raise ValidationError(_('La nómina seleccionada no pertenece a este detalle.'))
            
        payslip.write({
            'transfer_state': 'rejected',
            'transfer_reason': reason,
            'transfer_notes': notes,
            'transfer_date': fields.Datetime.now()
        })
        
        self.write({
            'unpaid_payslip_ids': [(4, payslip.id)],
            'payment_status': 'partial' if len(self.unpaid_payslip_ids) < len(self.liquidations_ids) else 'unpaid'
        })
        
        activity_type_id = self.env.ref('mail.mail_activity_data_todo').id
        self.env['mail.activity'].create({
            'activity_type_id': activity_type_id,
            'note': f'Nómina no pagada: {notes}',
            'user_id': self.env.user.id,
            'res_id': self.id,
            'res_model_id': self.env['ir.model']._get('hr.payroll.flat.file.detail').id,
            'summary': f'Revisar pago rechazado - {payslip.name}'
        })

    def action_resolve_transfer(self):
        """Abrir wizard para resolver problema de transferencia"""
        self.ensure_one()
        
        if not self.unpaid_payslip_ids:
            raise ValidationError(_('No hay nóminas marcadas como no pagadas en este detalle.'))
            
        return {
            'name': _('Resolver Problema de Transferencia'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.payroll.resolve.transfer.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_detail_id': self.id,
            }
        }

    def resolve_transfer_issue(self, payslip_id, resolution_notes=''):
        """Resolver problema de transferencia para una nómina específica"""
        self.ensure_one()
        payslip = self.env['hr.payslip'].browse(payslip_id)
        
        if payslip not in self.unpaid_payslip_ids:
            raise ValidationError(_('La nómina seleccionada no está marcada como no pagada.'))
            
        payslip.write({
            'transfer_state': 'done',
            'transfer_resolved_date': fields.Datetime.now(),
            'transfer_resolution_notes': resolution_notes
        })
        
        self.write({
            'unpaid_payslip_ids': [(3, payslip.id)]
        })
        
        if not self.unpaid_payslip_ids:
            self.payment_status = 'paid'
        
        activities = self.env['mail.activity'].search([
            ('res_id', '=', self.id),
            ('res_model', '=', 'hr.payroll.flat.file.detail'),
            ('activity_type_id', '=', self.env.ref('mail.mail_activity_data_todo').id)
        ])
        for activity in activities:
            activity.action_done()
            activity.write({
                'note': f'{activity.note}\n\nResuelto: {resolution_notes}'
            })
 
    @api.depends('liquidations_ids', 'flat_file_id.exclude_concepts_ids')
    def _compute_amount_total(self):
        for record in self:
            total = 0
            excluded = 0
            for payslip in record.liquidations_ids:
                excluded_concepts = payslip.line_ids.filtered(
                    lambda l: l.salary_rule_id in record.flat_file_id.exclude_concepts_ids or
                            l.salary_rule_id.not_include_flat_payment_file
                )
                excluded += sum(excluded_concepts.mapped('total'))
                
                # Monto neto
                net_lines = payslip.line_ids.filtered(lambda l: l.code == 'NET')
                total += sum(net_lines.mapped('total')) - excluded

            record.amount_total = total
            record.amount_excluded = excluded

    @api.depends('liquidations_ids')
    def _compute_employee_count(self):
        for record in self:
            record.employee_count = len(record.liquidations_ids.mapped('employee_id'))

    @api.depends('liquidations_ids')
    def _compute_payslip_count(self):
        for record in self:
            record.payslip_count = len(record.liquidations_ids)

    def download_txt(self):
        self.ensure_one()
        if not self.txt_file:
            raise ValidationError(_('No se ha generado el archivo plano.'))
            
        self.state = 'downloaded'
        return {
            'name': 'Archivo Plano',
            'type': 'ir.actions.act_url',
            'url': f"web/content/?model=hr.payroll.flat.file.detail&id={self.id}&filename_field=txt_file_name&field=txt_file&download=true&filename={self.txt_file_name}",
            'target': 'self',
        }

    def download_excel(self):
        self.ensure_one()
        if not self.excel_file:
            raise ValidationError(_('No se ha generado el archivo Excel.'))
            
        self.state = 'downloaded'
        return {
            'name': 'Archivo Excel',
            'type': 'ir.actions.act_url',
            'url': f"web/content/?model=hr.payroll.flat.file.detail&id={self.id}&filename_field=excel_file_name&field=excel_file&download=true&filename={self.excel_file_name}",
            'target': 'self',
        }

    def action_view_payslips(self):
        self.ensure_one()
        return {
            'name': _('Liquidaciones'),
            'view_mode': 'tree,form',
            'res_model': 'hr.payslip',
            'type': 'ir.actions.act_window',
            'domain': [('id', 'in', self.liquidations_ids.ids)]
        }

    def action_regenerate(self):
        """Regenerar archivos"""
        self.ensure_one()
        self.state = 'draft'
        self.txt_file = False
        self.excel_file = False
        return self.flat_file_id.generate_flat_file()

class hr_payroll_flat_file(models.Model):
    _name = 'hr.payroll.flat.file'
    _description = 'Archivo plano de pago de nómina'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(
        'Nombre',
        compute='_compute_name',
        store=True,
        tracking=True
    )
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('generated', 'Generado'),
        ('processed', 'Procesado'),
        ('cancelled', 'Cancelado')
    ], string='Estado', default='draft', tracking=True)
    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
        tracking=True
    )

    payment_type = fields.Selection([
        ('225', 'Pago de Nómina'),
        ('238', 'Pago de Cesantías'),
        ('239', 'Pago de Primas'),
        ('240', 'Pago de Vacaciones')
    ], string='Tipo de Pago', required=True, default='225', tracking=True)

    type = fields.Selection([
        ('CD', 'Cuenta de dispersión Por Contacto'),
        ('GL', 'Global'),
        ('SE', 'Separado por Empleado')
    ], string='Tipo de dispersión', default='GL', tracking=True)

    source_information = fields.Selection([
        ('lote', 'Por lote'),
        ('liquidacion', 'Por liquidaciones'),
        ('rango', 'Por rango de fechas')
    ], string='Origen información', default='lote', tracking=True)

    date_start = fields.Date(
        'Fecha Inicial',
        default=lambda self: fields.Date.today().replace(day=1),
        tracking=True
    )
    date_end = fields.Date(
        'Fecha Final',
        default=lambda self: fields.Date.today(),
        tracking=True
    )
    transmission_date = fields.Datetime(
        "Fecha transmisión",
        required=True,
        default=fields.Datetime.now(),
        tracking=True
    )
    application_date = fields.Date(
        "Fecha aplicación",
        required=True,
        default=fields.Date.today(),
        tracking=True
    )

    journal_id = fields.Many2one(
        'account.journal',
        string='Diario',
        domain=[('is_payroll_spreader', '=', True)],
        tracking=True
    )
    payslip_run_ids = fields.Many2many(
        'hr.payslip.run',
        'payroll_flat_file_run_rel',
        'flat_file_id',
        'run_id',
        string='Lotes de nómina',
        domain=[('state', '=', 'close')],
        tracking=True
    )
    payslip_ids = fields.Many2many(
        'hr.payslip',
        'payroll_flat_file_slip_rel',
        'flat_file_id',
        'slip_id',
        string='Liquidaciones',
        domain=[('state', '=', 'done')],
        tracking=True
    )
    detail_ids = fields.One2many(
        'hr.payroll.flat.file.detail',
        'flat_file_id',
        string='Detalle de archivos'
    )
    vat_payer = fields.Char(
        string='NIT Pagador',
        related='company_id.partner_id.vat_co',
        store=True,
        readonly=True
    )
    available_payslip_run_ids = fields.Many2many(
        'hr.payslip.run',
        compute='_compute_available_payslip_runs',
        string='Lotes Disponibles'
    )
    total_employees = fields.Integer(
        'Total Empleados',
        compute='_compute_totals'
    )
    total_amount = fields.Float(
        'Total a Pagar',
        compute='_compute_totals'
    )
    description = fields.Char(
        'Descripción',
        required=True,
        tracking=True
    )
    flat_rule_not_included = fields.Boolean(
        'Generar plano reglas excluidas',
        tracking=True
    )
    exclude_loan = fields.Boolean(
        'Excluir Préstamos',
        tracking=True
    )
    exclude_concepts_ids = fields.Many2many(
        'hr.salary.rule',
        string='Conceptos a Excluir',
        domain=[('active', '=', True)],
        tracking=True
    )
    notes = fields.Text(
        'Notas',
        tracking=True
    )
    log_ids = fields.One2many('payroll.file.process.log', 'flat_file_id', 'Logs')
    error_count = fields.Integer('Errores', compute='_compute_log_counts', store=True)
    warning_count = fields.Integer('Advertencias', compute='_compute_log_counts', store=True)

    @api.depends('log_ids')
    def _compute_log_counts(self):
        for record in self:
            record.error_count = len(record.log_ids.filtered(lambda l: l.type == 'error'))
            record.warning_count = len(record.log_ids.filtered(lambda l: l.type == 'warning'))

    def name_get(self):
        result = []
        for record in self:            
            result.append((record.id, "Archivo de Pago - {}".format(record.description)))
        return result


    @api.depends('date_start', 'date_end')
    def _compute_available_payslip_runs(self):
        for record in self:
            domain = [
                ('state', '=', 'close'),
                ('date_start', '>=', record.date_start),
                ('date_end', '<=', record.date_end)
            ]
            record.available_payslip_run_ids = self.env['hr.payslip.run'].search(domain)

    @api.depends('detail_ids', 'detail_ids.liquidations_ids')
    def _compute_totals(self):
        for record in self:
            employees = record.detail_ids.mapped('liquidations_ids.employee_id')
            record.total_employees = len(employees)
            record.total_amount = sum(d.amount_total for d in record.detail_ids)

    @api.depends('payment_type', 'date_start', 'company_id')
    def _compute_name(self):
        for record in self:
            payment_types = dict(self._fields['payment_type'].selection)
            record.name = f"{payment_types.get(record.payment_type)} - {record.date_start.strftime('%B %Y')}"

    @api.onchange('source_information')
    def _onchange_source_information(self):
        self.payslip_run_ids = False
        self.payslip_ids = False

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for record in self:
            if record.date_start > record.date_end:
                raise ValidationError(_('La fecha inicial no puede ser mayor a la fecha final'))

    def action_generate(self):
        self.ensure_one()
        # Lógica de generación
        self.state = 'generated'

    def action_process(self):
        self.ensure_one()
        self.state = 'processed'

    def action_cancel(self):
        self.ensure_one()
        self.state = 'cancelled'

    def action_draft(self):
        self.ensure_one()
        self.state = 'draft'

    def action_view_details(self):
        self.ensure_one()
        return {
            'name': _('Detalles de Pago'),
            'view_mode': 'tree,form',
            'res_model': 'hr.payroll.flat.file.detail',
            'domain': [('flat_file_id', '=', self.id)],
            'type': 'ir.actions.act_window',
            'context': {'default_flat_file_id': self.id}
        }


    #Lógica de bancolombia sap
    def generate_flat_file_sap(self, obj_payslip):
        filler = ' '
        def left(s, amount):
            return s[:amount]
            
        def right(s, amount):
            return s[-amount:]
        
        #----------------------------------Registro de Control de Lote----------------------------------
        tipo_registro = '1'
        nit_entidad = right(10*'0'+self.vat_payer, 10)
        nombre_entidad = left(self.company_id.partner_id.name+16*filler, 16) 
        clase_transacciones = self.payment_type
        descripcion = left(self.description+10*filler, 10)
        fecha_transmision = str(self.transmission_date.year)[-2:]+right('00'+str(self.transmission_date.month), 2)+right('00'+str(self.transmission_date.day), 2)
        secuencia = 'A'
        fecha_aplicacion = str(self.application_date.year)[-2:]+right('00'+str(self.application_date.month), 2)+right('00'+str(self.application_date.day), 2)
        num_registros = 'NumRegs' # Mas adelante se reeemplaza con el valor correcto
        sum_debitos = 12*'0'
        sum_creditos = 'SumCreditos' # Mas adelante se reeemplaza con el valor correcto
        
        #Obtener cuenta
        cuenta_cliente = ''
        tipo_cuenta = ''
        for journal in self.journal_id:            
            cuenta_cliente = right(11*'0'+str(journal.bank_account_id.acc_number).replace("-", ""), 11)
            tipo_cuenta = 'S' if journal.bank_account_id.type_account == 'A' else 'D' # S : aho / D : cte
        
        if cuenta_cliente == '':
            raise ValidationError(_('No existe una cuenta bancaria configurada como dispersora de nómina, por favor verificar.'))
        
        #Concatenar encabezado
        encab_content = '''%s%s%s%s%s%s%s%s%s%s%s%s%s''' % (tipo_registro, nit_entidad, nombre_entidad, clase_transacciones, descripcion, fecha_transmision, secuencia, fecha_aplicacion, num_registros, sum_debitos, sum_creditos, cuenta_cliente, tipo_cuenta)
        
        #----------------------------------Registro Detalle de Transacciones---------------------------------
        detalle_content = ''
        
        #Traer la información
        cant_detalle = 0
        total_valor_transaccion = 0.0  # Inicializar como float para mantener precisión decimal
        detalles_valor = []  # Lista para almacenar los valores individuales

        for payslip in obj_payslip:
            cant_detalle = cant_detalle + 1

            tipo_registro = '6'
            nit_beneficiario = right(15*'0'+payslip.contract_id.employee_id.work_contact_id.vat_co, 15)
            nombre_beneficiario = left(payslip.contract_id.employee_id.name+18*filler, 18) 
            #Inf Bancaria
            banco = ''
            cuenta_beneficiario = ''
            indicador_lugar_pago = ''
            tipo_transaccion = ''
            for bank in payslip.contract_id.employee_id.work_contact_id.bank_ids:
                if bank.is_main:
                    banco = right(9*'0'+bank.bank_id.bank_code, 9)
                    cuenta_beneficiario = right(17*'0'+str(bank.acc_number).replace("-", ""), 17)
                    indicador_lugar_pago = 'S'
                    tipo_transaccion = '37' if bank.type_account == 'A' else '27' # 27: Abono a cuenta corriente / 37: Abono a cuenta ahorros 
            if cuenta_beneficiario == '':
                raise ValidationError(_('El empleado '+payslip.contract_id.employee_id.name+' no tiene configurada la información bancaria, por favor verificar.'))
            valor_transacción = 10*'0'
            valor_not_include = 0.0
            for line in payslip.line_ids:
                valor_not_include += line.total if line.salary_rule_id.not_include_flat_payment_file else 0.0
                if line.code == 'NET':
                    val_write = line.total - valor_not_include
                    val_write = 0.0 if val_write < 0 else val_write
                    val_write = round(val_write, 2)
                    detalles_valor.append(val_write)
                    valor = str(int(val_write))  # Eliminar decimales correctamente
                    valor_transacción = right(10*'0'+valor, 10)
            concepto = 9*filler
            referencia = 12*filler
            relleno = filler
            content_line = '''%s%s%s%s%s%s%s%s%s%s%s''' % (tipo_registro, nit_beneficiario, nombre_beneficiario, banco, cuenta_beneficiario, indicador_lugar_pago, tipo_transaccion, valor_transacción, concepto, referencia, relleno)
            if cant_detalle == 1:
                detalle_content = content_line
            else:
                detalle_content = detalle_content +'\n'+ content_line
        total_valor_transaccion = sum(detalles_valor)
        
        #----------------------------------Generar archivo---------------------------------
        encab_content = encab_content.replace("NumRegs", right(6*'0'+str(cant_detalle), 6))
        valor_total = str(int(total_valor_transaccion))  # Parte entera
        encab_content = encab_content.replace("SumCreditos", right(12*'0'+valor_total, 12))
        content_txt = encab_content +'\n'+ detalle_content 
        return base64.encodebytes((content_txt).encode())

    # Función mejorada para PAB
    def generate_flat_file_pab(self, obj_payslip):
        filler = ' '
        def left(s, amount):
                return s[:amount]
            
        def right(s, amount):
            return s[-amount:]
        
        #----------------------------------Registro de Control de Lote----------------------------------
        tipo_registro = '1'
        nit_entidad = right(15*'0'+self.vat_payer, 15)
        aplication = 'I'
        filler_one = filler*15
        clase_transacciones = self.payment_type
        descripcion = left(self.description+10*filler, 10)
        fecha_transmision = str(self.transmission_date.year)+right('00'+str(self.transmission_date.month), 2)+right('00'+str(self.transmission_date.day), 2)
        secuencia = '01'
        fecha_aplicacion = str(self.application_date.year)+right('00'+str(self.application_date.month), 2)+right('00'+str(self.application_date.day), 2)
        num_registros = 'NumRegs' # Mas adelante se reeemplaza con el valor correcto
        sum_debitos = 17*'0'
        sum_creditos = 'SumCreditos' # Mas adelante se reeemplaza con el valor correcto
        
        #Obtener cuenta
        cuenta_cliente = ''
        tipo_cuenta = ''
        for journal in self.journal_id:            
            cuenta_cliente = right(11*'0'+str(journal.bank_account_id.acc_number).replace("-", ""), 11)
            tipo_cuenta = 'S' if journal.bank_account_id.type_account == 'A' else 'D' # S : aho / D : cte
        
        if cuenta_cliente == '':
            raise ValidationError(_('No existe una cuenta bancaria configurada como dispersora de nómina, por favor verificar.'))
        
        filler_two = filler*149

        #Concatenar encabezado
        encab_content = '%s%s%s%s%s%s%s%s%s%s%s%s%s%s%s' % (tipo_registro, nit_entidad, aplication, filler_one, clase_transacciones, descripcion, fecha_transmision, secuencia, fecha_aplicacion, num_registros, sum_debitos, sum_creditos, cuenta_cliente, tipo_cuenta, filler_two)
        
        #----------------------------------Registro Detalle de Transacciones---------------------------------
        detalle_content = ''
        
        #Traer la información
        cant_detalle = 0
        total_valor_transaccion = 0.0  # Inicializar como float para mantener precisión decimal
        detalles_valor = []  # Lista para almacenar los valores individuales

        for payslip in obj_payslip:
            cant_detalle = cant_detalle + 1

            tipo_registro = '6'
            nit_beneficiario = left(payslip.contract_id.employee_id.work_contact_id.vat_co+15*' ', 15)
            nombre_beneficiario = left(payslip.contract_id.employee_id.name+30*' ', 30) 
            
            #Inf Bancaria
            banco = ''
            cuenta_beneficiario = ''
            indicador_lugar_pago = ''
            tipo_transaccion = ''
            for bank in payslip.contract_id.employee_id.work_contact_id.bank_ids:
                if bank.is_main:
                    banco = right(9*'0'+bank.bank_id.bank_code, 9)
                    cuenta_beneficiario = left(str(bank.acc_number).replace("-", "")+17*' ', 17)
                    indicador_lugar_pago = 'S'
                    tipo_transaccion = '37' if bank.type_account == 'A' else '27' # 27: Abono a cuenta corriente / 37: Abono a cuenta ahorros 
            
            if cuenta_beneficiario == '':
                raise ValidationError(_('El empleado '+payslip.contract_id.employee_id.name+' no tiene configurada la información bancaria, por favor verificar.'))
            
            #Obtener valor de transacción 
            valor_transaccion = 15*'0'
            valor_transaccion_decimal = 2*'0'
            valor_not_include = 0.0
            
            for line in payslip.line_ids:
                valor_not_include += line.total if line.salary_rule_id.not_include_flat_payment_file else 0.0
                if line.code == 'NET':
                    val_write = line.total - valor_not_include
                    val_write = 0.0 if val_write < 0 else val_write
                    
                    # Redondear a 2 decimales para mantener consistencia
                    val_write = round(val_write, 2)
                    detalles_valor.append(val_write)
                    
                    # Separar parte entera y decimal
                    valor_entero = int(val_write)
                    valor_decimal = int(round((val_write - valor_entero) * 100))  # Redondear y convertir a entero
                    
                    valor_transaccion = right(15*'0'+str(valor_entero), 15)
                    valor_transaccion_decimal = right(2*'0'+str(valor_decimal), 2)
                    
            fecha_aplicacion_det = fecha_aplicacion
            referencia = 21*filler
            tipo_identificacion = ' ' # Es requerido solo si el pago es para entregar por ventanilla por ende enviamos vacio
            oficina_entrega = 5*'0'
            numero_fax = 15*filler
            email = left(payslip.contract_id.employee_id.work_email+80*' ', 80)
            identificacion_autorizado = 15*filler # Solo se llena cuando es cheques
            relleno = filler*27

            content_line = '''%s%s%s%s%s%s%s%s%s%s%s%s%s%s%s%s%s''' % (tipo_registro, nit_beneficiario, nombre_beneficiario, banco, cuenta_beneficiario, indicador_lugar_pago, tipo_transaccion, valor_transaccion, valor_transaccion_decimal, fecha_aplicacion_det, referencia, tipo_identificacion, oficina_entrega, numero_fax, email, identificacion_autorizado, relleno)
            
            if cant_detalle == 1:
                detalle_content = content_line
            else:
                detalle_content = detalle_content +'\n'+ content_line

        # Calcular el total sumando los valores individuales para garantizar coherencia
        total_valor_transaccion = sum(detalles_valor)
        
        #----------------------------------Generar archivo---------------------------------
        #Reemplazar valores del encabezado
        encab_content = encab_content.replace("NumRegs", right(6*'0'+str(cant_detalle), 6))
        
        # Dividir el total con exactamente 2 decimales
        valor_entero = int(total_valor_transaccion)
        valor_decimal = int(round((total_valor_transaccion - valor_entero) * 100))
        
        encab_content = encab_content.replace("SumCreditos", right(15*'0'+str(valor_entero), 15) + right(2*'0'+str(valor_decimal), 2))
        
        #Unir Encabezado y Detalle
        content_txt = encab_content +'\n'+ detalle_content

        # Retornar archivo
        return base64.encodebytes((content_txt).encode())

    # Función mejorada para OCCIRED
    def generate_flat_file_occired(self, obj_payslip):
        filler = ' '
        def left(s, amount):
                return s[:amount]
            
        def right(s, amount):
            return s[-amount:]
        
        #----------------------------------Registro de Control de Lote----------------------------------
        tipo_registro_encab = '1'
        consecutivo = '0000'
        date_today = self.transmission_date
        fecha_pago = str(date_today.year)+right('00'+str(date_today.month), 2)+right('00'+str(date_today.day), 2) 
        numero_registro = 'NumRegs'
        valor_total = 'ValTotal'
        cuenta_principal = ''
        
        for journal in self.journal_id:            
            cuenta_principal = right(16*'0'+str(journal.bank_account_id.acc_number).replace("-", ""), 16)
        
        if cuenta_principal == '':
            raise ValidationError(_('No existe una cuenta bancaria configurada como dispersora de nómina, por favor verificar.'))
        
        identificacion_del_archivo = 6*'0'
        ceros = 142*'0'            
        
        encab_content_txt = '''%s%s%s%s%s%s%s%s''' % (tipo_registro_encab, consecutivo, fecha_pago, numero_registro, valor_total, cuenta_principal, identificacion_del_archivo, ceros)
        
        #----------------------------------Registro Detalle de Transacciones---------------------------------
        det_content_txt = ''
        tipo_registro_det = '2'
        
        #Traer la información
        cant_detalle = 0
        total_valor_transaccion = 0.0  # Inicializar como float para mantener precisión decimal
        detalles_valor = []  # Lista para almacenar los valores individuales
        
        for payslip in obj_payslip:
            cant_detalle = cant_detalle + 1
            consecutivo = right('0000'+str(cant_detalle), 4)
            forma_de_pago = '3' # 1: Pago en Cheque  2: Pago abono a cuenta  - Banco de Occidente  3: Abono a cuenta otras entidades
            
            #Inf Bancaria
            tipo_transaccion = ''
            banco_destino = ''
            no_cuenta_beneficiario = ''
            for bank in payslip.contract_id.employee_id.work_contact_id.bank_ids:
                if bank.is_main:
                    tipo_transaccion = 'A' if bank.type_account == 'A' else 'C' # C: Abono a cuenta corriente / A: Abono a cuenta ahorros 
                    banco_destino = '0'+right(3*'0'+bank.bank_id.bank_code, 3)
                    forma_de_pago = '2' if bank.bank_id.bank_code == '1023' else forma_de_pago
                    no_cuenta_beneficiario = right(16*'0'+str(bank.acc_number).replace("-", ""), 16)  
            
            if no_cuenta_beneficiario == '':
                raise ValidationError(_('El empleado '+payslip.contract_id.employee_id.name+' no tiene configurada la información bancaria, por favor verificar.'))
            
            nit_beneficiario = right(11*'0'+payslip.contract_id.employee_id.work_contact_id.vat_co, 11)        
            nombre_beneficiario = left(payslip.contract_id.employee_id.name+30*' ', 30)
            fecha_pago = str(self.application_date.year)+right('00'+str(self.application_date.month), 2)+right('00'+str(self.application_date.day), 2) 
            
            #Obtener valor de transacción 
            valor_transaccion = 13*'0'
            valor_transaccion_decimal = 2*'0'
            valor_not_include = 0.0
            
            for line in payslip.line_ids:
                valor_not_include += line.total if line.salary_rule_id.not_include_flat_payment_file else 0.0
                if line.code == 'NET':
                    val_write = line.total - valor_not_include
                    val_write = 0.0 if val_write < 0 else val_write
                    
                    # Redondear a 2 decimales para mantener consistencia
                    val_write = round(val_write, 2)
                    detalles_valor.append(val_write)
                    
                    # Separar parte entera y decimal
                    valor_entero = int(val_write)
                    valor_decimal = int(round((val_write - valor_entero) * 100))  # Redondear y convertir a entero
                    
                    valor_transaccion = right(13*'0'+str(valor_entero), 13)
                    valor_transaccion_decimal = right(2*'0'+str(valor_decimal), 2)         
            
            numbers = [temp for temp in payslip.number.split("/") if temp.isdigit()]
            documento_autorizado = ''
            for i in numbers:
                documento_autorizado = documento_autorizado + str(i)
            documento_autorizado = right(filler*12+documento_autorizado, 12)
        
            referencia = 80*filler
                
            content_line = '''%s%s%s%s%s%s%s%s%s%s%s%s%s%s''' % (tipo_registro_det, consecutivo, cuenta_principal, nombre_beneficiario, nit_beneficiario, banco_destino, fecha_pago, forma_de_pago, valor_transaccion, valor_transaccion_decimal, no_cuenta_beneficiario, documento_autorizado, tipo_transaccion, referencia)
            
            if cant_detalle == 1:
                det_content_txt = content_line
            else:
                det_content_txt = det_content_txt +'\n'+ content_line
            
        # Calcular el total sumando los valores individuales para garantizar coherencia
        total_valor_transaccion = sum(detalles_valor)
        
        #Encabezado - parte 2            
        encab_content_txt = encab_content_txt.replace("NumRegs", right('0000'+str(cant_detalle), 4))        
        
        # Dividir el total con exactamente 2 decimales
        valor_entero = int(total_valor_transaccion)
        valor_decimal = int(round((total_valor_transaccion - valor_entero) * 100))
        
        parte_entera = right(16*'0'+str(valor_entero), 16)
        parte_decimal = right(2*'0'+str(valor_decimal), 2) 
        
        encab_content_txt = encab_content_txt.replace("ValTotal", parte_entera + parte_decimal)
        
        #Totales
        tipo_registro_tot = '3'
        secuencia = '9999'
        numero_registro = right('0000'+str(cant_detalle), 4)
        
        # Usar el mismo valor para totales que para el encabezado para mantener consistencia
        valor_total = parte_entera + parte_decimal
        ceros = 172*'0'

        tot_content_txt = '''%s%s%s%s%s''' % (tipo_registro_tot, secuencia, numero_registro, valor_total, ceros)

        #Unir Encabezado, Detalle y Totales
        if det_content_txt == '':
            raise ValidationError(_('No existe información en las liquidaciones seleccionadas, por favor verificar.'))
        
        content_txt = encab_content_txt +'\n'+ det_content_txt +'\n'+ tot_content_txt

        # Retornar archivo
        return base64.encodebytes((content_txt).encode())
    # Lógica de avvillas
    def generate_flat_file_avvillas(self,obj_payslip):
        filler = ' '
        def left(s, amount):
            return s[:amount]

        def right(s, amount):
            return s[-amount:]
        # ----------------------------------Registro de Control----------------------------------
        tipo_registro_encab = '01'
        date_today = str(self.transmission_date.date()).replace('-', '')
        transmission_time = str((self.transmission_date-timedelta(hours=5)).time()).replace(':', '')
        office_code = '088'
        acquirer_code = '02'
        file_name = 50 * filler
        backfill = 120 * filler

        encab_content_txt = '''%s%s%s%s%s%s%s''' % (tipo_registro_encab, date_today, transmission_time, office_code, acquirer_code, file_name, backfill)

        # ----------------------------------Registro Detalle---------------------------------
        det_content_txt = ''
        tipo_registro_det = '02'
        codigo_transaccion = '000023'  # 000023 pago nomina- TD plus y abono afc #000024 pago provedores
        tipo_producto_origen = '01' if self.journal_id.bank_account_id.type_account == 'A' else '06'  # 01: Abono a cuenta ahorros /  06: Abono a cuenta corriente
        cuenta_origen = right(16 * '0' + str(self.journal_id.bank_account_id.acc_number), 16)
        entidad_destino = '052'

        numero_factura = 16 * '0'
        referencia_1 = 16 * '0'
        referencia_2 = 16 * '0'
        cant_detalle = 0
        total_valor_transaccion = 0
        numero_autorizacion = 6 * '0'
        codigo_respuesta = '00'  # 00 Transaccion correcto
        retencion_contingente = 18 * '0'
        relleno = 2 * filler

        # Agregar query
        for payslip in obj_payslip:
            cant_detalle = cant_detalle + 1
            secuencia = right(9*'0' + str(cant_detalle), 9)
            nombre = left(payslip.contract_id.employee_id.name + 30 * ' ', 30)
            numero_documento = right(11 * '0' + payslip.contract_id.employee_id.work_contact_id.vat_co, 11)

            # Inf Bancaria
            tipo_producto_destino = ''
            no_cuenta_beneficiario = ''
            for bank in payslip.contract_id.employee_id.work_contact_id.bank_ids:
                if bank.is_main:
                    tipo_producto_destino = '01' if bank.type_account == 'A' else '06'  # 01: Abono a cuenta ahorros /  06: Abono a cuenta corriente
                    no_cuenta_beneficiario = right(16 * '0' + str(bank.acc_number).replace("-", ""), 16)
            if no_cuenta_beneficiario == '':
                raise ValidationError(
                    _('El empleado ' + payslip.contract_id.employee_id.name + ' no tiene configurada la información bancaria, por favor verificar.'))

            # Obtener valor de transacción
            valor_transaccion = 16 * '0'
            valor_transaccion_decimal = 2 * '0'
            valor_not_include = 0
            for line in payslip.line_ids:
                valor_not_include += line.total if line.salary_rule_id.not_include_flat_payment_file else 0
                if line.code == 'NET':
                    total_valor_transaccion = (total_valor_transaccion + line.total) - valor_not_include
                    total_valor_transaccion = 0 if total_valor_transaccion < 0 else total_valor_transaccion
                    val_write = line.total - valor_not_include
                    val_write = 0 if val_write < 0 else val_write
                    valor = str(val_write).split(".")  # Eliminar decimales
                    valor_transaccion = right(16 * '0' + str(valor[0]), 16)
                    valor_transaccion_decimal = right(2 * '0' + str(valor[1]), 2)

            content_line = '''%s%s%s%s%s%s%s%s%s%s%s%s%s%s%s%s%s%s%s''' % (
            tipo_registro_det, codigo_transaccion, tipo_producto_origen, cuenta_origen, entidad_destino,
            tipo_producto_destino, no_cuenta_beneficiario, secuencia, valor_transaccion, valor_transaccion_decimal,
            numero_factura, referencia_1, referencia_2, nombre, numero_documento, numero_autorizacion, codigo_respuesta,
            retencion_contingente, relleno)
            if cant_detalle == 1:
                det_content_txt = content_line
            else:
                det_content_txt = det_content_txt + '\n' + content_line

        # Totales
        tipo_registro_tot = '03'
        cantidad_registros = right(9 * '0' + str(cant_detalle), 9)
        valor = str(total_valor_transaccion).split(".")  # Eliminar decimales
        parte_entera = right(18 * '0' + str(valor[0]), 18)
        if len(valor) > 1:
            parte_decimal = right(2 * '0' + str(valor[1]), 2)
        else:
            parte_decimal = 2 * '0'
        valor_total_tra = parte_entera + '' + parte_decimal
        digito_chequeo = 15 * filler
        relleno = 145 * filler

        tot_content_txt = '''%s%s%s%s%s''' % (
        tipo_registro_tot, cantidad_registros, valor_total_tra, digito_chequeo, relleno)

        # Unir Encabezado, Detalle y Totales
        if det_content_txt == '':
            raise ValidationError(
                _('No existe información en las liquidaciones seleccionadas, por favor verificar.'))

        content_txt = encab_content_txt + '\n' + det_content_txt + '\n' + tot_content_txt

        # Retornar archivo
        return base64.encodebytes((content_txt).encode())

    # Lógica de Davivienda
    def generate_flat_file_davivienda(self, obj_payslip):
        """
        Genera archivo plano para Davivienda
        - Formato específico requerido por el banco
        - Incluye validaciones de datos
        - Maneja reglas excluidas
        """
        try:
            filler = ' '
            
            def left(s, amount):
                return str(s)[:amount]

            def right(s, amount):
                return str(s)[-amount:]

            # Validar datos básicos
            if not self.journal_id or not self.journal_id.bank_account_id:
                raise ValidationError(_('Debe configurar una cuenta bancaria en el diario.'))
                
            if not self.vat_payer or not self.company_id.partner_id.dv:
                raise ValidationError(_('Debe configurar el NIT y DV de la compañía.'))

            # ----------------------------------Registro de Control----------------------------------
            # Datos de la empresa
            tipo_registro_encab = 'RC'
            nit_empresa = right('0' * 16 + self.vat_payer + str(self.company_id.partner_id.dv), 16)
            codigo_servicio = '0' * 4     # NOMI pago nomina
            codigo_subservicio = '0' * 4  # NOMI Para el servicio de Nómina

            # Datos de la cuenta
            cuenta_empresa = right('0' * 16 + str(self.journal_id.bank_account_id.acc_number or ''), 16)
            tipo_cuenta = 'CA' if self.journal_id.bank_account_id.type_account == 'A' else 'CC'
            codigo_banco = '000051'

            # Totalizadores (se reemplazan después)
            valor_total_trasladados = 'ValorTotalTraslados'
            numero_trasladados = 'NumTraslados'

            # Datos de proceso
            fecha_proceso = str(self.transmission_date.date()).replace('-', '')
            hora_proceso = str((self.transmission_date - timedelta(hours=5)).time()).replace(':', '')
            codigo_operador = '0' * 4
            codigo_no_procesado = '9' * 4
            fecha_generacion = '0' * 8
            hora_generacion = '0' * 6
            indicador_incripcion = '00'
            tipo_identificacion = '03'  # 03 NIT
            numero_cliente_asignado = '0' * 12
            oficina_recaudo = '0' * 4
            campo_futuro = '0' * 40

            # Generar encabezado
            encab_content_txt = f"{tipo_registro_encab}{nit_empresa}{codigo_servicio}{codigo_subservicio}" \
                            f"{cuenta_empresa}{tipo_cuenta}{codigo_banco}{valor_total_trasladados}" \
                            f"{numero_trasladados}{fecha_proceso}{hora_proceso}{codigo_operador}" \
                            f"{codigo_no_procesado}{fecha_generacion}{hora_generacion}{indicador_incripcion}" \
                            f"{tipo_identificacion}{numero_cliente_asignado}{oficina_recaudo}{campo_futuro}"

            # ----------------------------------Registro Detalle de Transacciones---------------------------------
            detalle_content = ''
            cant_detalle = 0
            total_valor_transaccion = 0

            for payslip in obj_payslip:
                # Valores por defecto del detalle
                tipo_registro = 'TR'
                referencia = '0' * 16
                cod_banco = '000051'
                talon = '0' * 6
                validar_ach = '1'
                resultado_proceso = '9999'
                mensaje_respuesta = '0' * 40
                valor_acumulado = '0' * 18
                fecha_aplicacion = '0' * 8
                oficina_recaudo = '0' * 4
                motivo = '0' * 4
                relleno = '0' * 7

                # Obtener tipo de identificación
                tipo_doc = payslip.contract_id.employee_id.work_contact_id.l10n_latam_identification_type_id.dian_code
                tipo_identificacion_beneficiario = self._get_davivienda_doc_type(tipo_doc, payslip)

                # Obtener NIT beneficiario
                nit_beneficiario = right('0' * 16 + str(payslip.contract_id.employee_id.work_contact_id.vat_co or ''), 16)

                # Obtener datos bancarios
                bank_data = self._get_davivienda_bank_data(payslip)
                cuenta_beneficiario = bank_data['cuenta']
                tipo_transaccion = bank_data['tipo']

                # Calcular valor a pagar
                valor_pago = self._calculate_payment_amount(payslip)
                total_valor_transaccion += valor_pago
                
                # Formatear valor para el archivo
                valor = str(valor_pago).split(".")
                valor_transaccion = right('0' * 16 + valor[0], 16) + right('0' * 2 + (valor[1] if len(valor) > 1 else '0'), 2)

                # Generar línea de detalle
                content_line = f"{tipo_registro}{nit_beneficiario}{referencia}{cuenta_beneficiario}" \
                            f"{tipo_transaccion}{cod_banco}{valor_transaccion}{talon}" \
                            f"{tipo_identificacion_beneficiario}{validar_ach}{resultado_proceso}" \
                            f"{mensaje_respuesta}{valor_acumulado}{fecha_aplicacion}" \
                            f"{oficina_recaudo}{motivo}{relleno}"

                detalle_content = content_line if cant_detalle == 0 else f"{detalle_content}\n{content_line}"
                cant_detalle += 1

            if cant_detalle == 0:
                raise ValidationError(_('No hay registros para procesar.'))

            # Reemplazar totales en encabezado
            valor_total = str(total_valor_transaccion).split(".")
            total_formatted = right('0' * 16 + valor_total[0], 16) + right('0' * 2 + (valor_total[1] if len(valor_total) > 1 else '0'), 2)
            cantidad_formatted = right('0' * 6 + str(cant_detalle), 6)
            
            encab_content_txt = encab_content_txt.replace("ValorTotalTraslados", total_formatted)
            encab_content_txt = encab_content_txt.replace("NumTraslados", cantidad_formatted)

            # Generar archivo final
            content_txt = f"{encab_content_txt}\n{detalle_content}"
            return base64.encodebytes(content_txt.encode())

        except Exception as e:
            self._create_log('error', 'Error generando archivo Davivienda', detail=str(e))
            raise ValidationError(f'Error generando archivo: {str(e)}')

    def _get_davivienda_doc_type(self, tipo_doc, payslip):
        """Obtiene el tipo de documento para Davivienda"""
        tipo_map = {
            '11': '13',  # Registro Civil
            '12': '04',  # Tarjeta identidad
            '13': '01',  # Cédula
            '22': '02',  # Cédula extranjería
            '31': '03',  # NIT
            '41': '05',  # Pasaporte
            'PE': '02',  # Permiso especial
            '47': '02',  # PPT
        }
        if tipo_doc not in tipo_map:
            raise ValidationError(_(
                f'Tipo de documento no válido para el empleado {payslip.contract_id.employee_id.name}'
            ))
        return tipo_map[tipo_doc]

    def _get_davivienda_bank_data(self, payslip):
        """Obtiene datos bancarios para Davivienda"""
        def left(s, amount):
            return str(s)[:amount]

        def right(s, amount):
            return str(s)[-amount:]

        main_bank = payslip.contract_id.employee_id.work_contact_id.bank_ids.filtered('is_main')
        
        if not main_bank:
            raise ValidationError(_(
                f'El empleado {payslip.contract_id.employee_id.name} no tiene cuenta bancaria principal'
            ))

        account = right('0' * 16 + str(main_bank.acc_number or '').replace("-", ""), 16)
        
        # Determinar tipo de transacción
        if main_bank.type_account == 'A':
            tipo = 'CA'
        elif main_bank.type_account == 'C':
            tipo = 'CC'
        elif main_bank.type_account == 'DP':
            tipo = 'DP'
        else:
            raise ValidationError(_(
                f'Tipo de cuenta inválido para {payslip.contract_id.employee_id.name}'
            ))
            
        return {
            'cuenta': account,
            'tipo': tipo
        }

    def _calculate_payment_amount(self, payslip):
        """Calcula monto a pagar considerando reglas excluidas"""
        valor_not_include = sum(
            line.total 
            for line in payslip.line_ids 
            if line.salary_rule_id.not_include_flat_payment_file
        )
        
        total = sum(
            line.total 
            for line in payslip.line_ids 
            if line.code == 'NET'
        )
        
        valor = total - valor_not_include
        return max(0, valor)
    #Genera archivo Excel formato Alianza Fiduciaria
    def generate_alianza_excel(self, obj_payslip):
        """
        Genera archivo Excel formato Alianza Fiduciaria
        - Formato específico ACH masivo
        - Validaciones de datos bancarios
        - Control de totales
        - Agrupa nóminas por empleado
        """
        try:
            if not obj_payslip:
                raise ValidationError(_('No hay registros para procesar.'))

            # Crear archivo Excel en memoria        
            output = io.BytesIO()
            workbook = xlsxwriter.Workbook(output)

            # Formatos
            header_format = workbook.add_format({
                'bold': True,
                'font_size': 11,
                'font_name': 'Calibri',
                'align': 'center', 
                'valign': 'vcenter',
                'border': 1
            })
            header_format.set_font_color('#1F497D')
            
            cell_format = workbook.add_format({
                'font_size': 11,
                'font_name': 'Calibri',
                'align': 'left',
                'valign': 'vcenter',
                'border': 1
            })
            
            money_format = workbook.add_format({
                'font_size': 11,
                'font_name': 'Calibri',
                'num_format': '$ #,##0.00',
                'border': 1
            })

            # Crear hoja principal
            worksheet = workbook.add_worksheet('Masivo ACH')

            # Insertar logo
            from odoo.modules.module import get_module_resource
            cell_format_title = workbook.add_format({'bold': True, 'align': 'left'})
            cell_format_title.set_font_name('Calibri')
            cell_format_title.set_font_size(15)
            cell_format_title.set_font_color('#1F497D')
            logo_path = get_module_resource('lavish_hr_payroll', 'static', 'img', 'alianza_logo.jpg')
            text_title = 'Masivo ACH'
            # worksheet.merge_range('A3:B4', text_title, cell_format_title)
            # worksheet.insert_image('G1', logo_path, {
            #     'x_scale': 1,
            #     'y_scale': 1,
            #     'x_offset': 10,  
            #     'y_offset': 10,
            #     'positioning': 1 
            # })

            # Configurar encabezados
            headers = [
                'Cuenta Origen', 'Subcuenta', 'Id Destino', 'Beneficiario', 
                'Tipo Cuenta', 'Cuenta Destino', 'Código Entidad', 
                'Valor', 'Concepto', 'Correo'
            ]

            # Configurar anchos de columnas
            widths = [15, 12, 15, 40, 12, 15, 12, 15, 20, 35]
            for i, width in enumerate(widths):
                worksheet.set_column(i, i, width)

            # Escribir encabezados
            for col, header in enumerate(headers):
                worksheet.write(9, col, header, header_format)

            # Valores iniciales
            row = 10
            cuenta_origen = str(self.journal_id.bank_account_id.acc_number).replace('-','')
            valor_total = 0

            # Agrupar nóminas por empleado
            payslips_by_employee = {}
            for payslip in obj_payslip:
                employee_id = payslip.employee_id.id
                if employee_id not in payslips_by_employee:
                    payslips_by_employee[employee_id] = {
                        'employee': payslip.employee_id,
                        'payslips': []
                    }
                payslips_by_employee[employee_id]['payslips'].append(payslip)
            
            # Procesar empleados agrupados
            for employee_data in payslips_by_employee.values():
                try:
                    employee = employee_data['payslips'][0].employee_id
                    
                    # Validar cuenta bancaria
                    bank = employee.work_contact_id.bank_ids.filtered('is_main')
                    if not bank:
                        raise ValidationError(_(
                            f'Empleado {employee.name} sin cuenta bancaria principal'
                        ))

                    # Validar tipo de cuenta
                    tipo_cuenta = 'CC' if bank.type_account == 'C' else 'CH'
                    
                    # Sumar valores de todas las nóminas del empleado
                    valor_neto = sum(
                        sum(line.total for line in payslip.line_ids if line.code == 'NET')
                        for payslip in employee_data['payslips']
                    )
                    
                    valor_excluido = sum(
                        sum(line.total 
                            for line in payslip.line_ids 
                            if line.salary_rule_id.not_include_flat_payment_file or 
                            line.salary_rule_id in self.exclude_concepts_ids)
                        for payslip in employee_data['payslips']
                    )
                    
                    valor = valor_neto - valor_excluido
                    if valor <= 0:  # No incluir si el valor es 0 o negativo
                        continue
                        
                    valor_total += valor

                    # Obtener código de banco
                    bank_code = bank.bank_id.bic
                    if not bank_code:
                        raise ValidationError(_(
                            f'Banco {bank.bank_id.name} sin código configurado'
                        ))

                    # Escribir línea
                    worksheet.write(row, 0, cuenta_origen, cell_format)  # Cuenta Origen
                    worksheet.write(row, 1, '', cell_format)  # Subcuenta 
                    worksheet.write(row, 2, employee.work_contact_id.vat_co, cell_format)  # Id Destino
                    worksheet.write(row, 3, employee.name, cell_format)  # Beneficiario
                    worksheet.write(row, 4, tipo_cuenta, cell_format)  # Tipo Cuenta 
                    worksheet.write(row, 5, bank.acc_number.replace('-',''), cell_format)  # Cuenta Destino
                    worksheet.write(row, 6, bank_code, cell_format)  # Código Entidad
                    worksheet.write(row, 7, valor, money_format)  # Valor
                    worksheet.write(row, 8, self.description, cell_format)  # Concepto
                    worksheet.write(row, 9, employee.work_email or '', cell_format)  # Correo

                    row += 1

                except Exception as e:
                    self._create_log('error', 
                        f'Error procesando empleado {employee.name}',
                        payslip=employee_data['payslips'][0],
                        error_type='other',
                        detail=str(e)
                    )

            # Crear hoja de instrucciones
            instructions = workbook.add_worksheet('Instrucciones')

            # Formato de tabla de instrucciones
            instructions.write(0, 0, 'Subcuenta', header_format)
            codes = [
                ('1', 'Funcionario'),
                ('2', 'Empresa'), 
                ('3', 'Extraordinario'),
                ('4', 'Ahorros')
            ]
            for i, (code, desc) in enumerate(codes):
                instructions.write(i+1, 0, code, cell_format)
                instructions.write(i+1, 1, desc, cell_format)

            instructions.write(6, 0, 'Tipo Cuenta', header_format)
            account_types = [
                ('CC', 'Cuenta Corriente'),
                ('CH', 'Cuenta de Ahorro')
            ]
            for i, (code, desc) in enumerate(account_types):
                instructions.write(i+7, 0, code, cell_format)
                instructions.write(i+7, 1, desc, cell_format)

            instructions.write(10, 0, 'Código Entidad', header_format)
            banks = [
                ('1', 'Banco de Bogotá'),
                ('2', 'Banco Popular'),
                ('6', 'Banco Corpbanca'),
                ('7', 'Bancolombia'),
                ('9', 'Citibank'),
                ('12', 'Banco GNB Sudameris'),
                ('13', 'BBVA'),
                ('19', 'Banco Colpatria'),
                ('23', 'Banco Occidente'),
                ('32', 'Banco Caja Social'),
                ('51', 'Banco Davivienda'),
                ('52', 'Banco AV Villas')
            ]
            for i, (code, name) in enumerate(banks):
                instructions.write(i+11, 0, code, cell_format)
                instructions.write(i+11, 1, name, cell_format)

            workbook.close()
            output.seek(0)
            return base64.b64encode(output.getvalue())

        except Exception as e:
            self._create_log('error', 'Error generando archivo Excel', detail=str(e))
            raise ValidationError(f'Error generando Excel: {str(e)}')



    # Lógica de Banco Bogotá excel
    def generate_flat_file_bogota_excel(self, obj_payslip):
        # Generar EXCEL
        filename = f'Plano de nómina del banco de Bogotá.xlsx'
        stream = io.BytesIO()
        book = xlsxwriter.Workbook(stream, {'in_memory': True})
        # Columnas
        columns = ['Tipo Identificación Beneficiario', 'Nombre del Beneficiario', 'Número de Identificación Beneficiario', 'Tipo de Cuenta Destino', 'Número Cuenta Destino', 'Valor a Pagar',
                   'Código Entidad Financiera Destino','Referencia /Factura','Correo electrónico o E-mail','Mensaje a enviar',]
        sheet = book.add_worksheet('Dispersión de fondos')
        # Formato para fechas
        date_format = book.add_format({'num_format': 'dd/mm/yyyy'})
        # Agregar columnas
        aument_columns = 0
        for column in columns:
            sheet.write(0, aument_columns, column)
            aument_columns = aument_columns + 1
        # Agregar nominas
        aument_columns = 0
        aument_rows = 1
        #for employee in obj_payslip.employee_id.ids:
        for payslip in obj_payslip:
            # Tipo documento
            sheet.write(aument_rows, 0, payslip.employee_id.work_contact_id.l10n_latam_identification_type_id.dian_code)
            # Nombre
            sheet.write(aument_rows, 1, payslip.employee_id.name)
            # Identificación
            sheet.write(aument_rows, 2, payslip.employee_id.work_contact_id.vat_co)
            # Tipo de cuenta
            banco = ''
            cuenta_beneficiario = ''
            tipo_cuenta = ''
            for bank in payslip.employee_id.work_contact_id.bank_ids:
                if bank.is_main:
                    banco = bank.bank_id.bank_code
                    cuenta_beneficiario = str(bank.acc_number).replace("-", "")
                    tipo_cuenta = 'Ahorros' if bank.type_account == 'A' else 'Corriente'
            sheet.write(aument_rows, 3, tipo_cuenta)
            # Numero de cuenta
            sheet.write(aument_rows, 4, cuenta_beneficiario)
            #Valor
            valor = 0
            valor_not_include = 0
            for line in payslip.line_ids:
                valor_not_include += line.total if line.salary_rule_id.not_include_flat_payment_file else 0
                if line.code == 'NET':
                    valor = line.total - valor_not_include
                    valor = 0 if valor < 0 else valor
            sheet.write(aument_rows, 5, valor)
            #Codigo entidad financiera
            sheet.write(aument_rows, 6, banco)
            #Referencia/factura
            sheet.write(aument_rows, 7, '')
            #Correo electronico
            sheet.write(aument_rows, 8, payslip.employee_id.work_email)
            #A enviar
            sheet.write(aument_rows, 9, '')
            # Ajustar tamaño columna
            # sheet.set_column(aument_columns, aument_columns, width)
            aument_rows = aument_rows + 1
        # Convertir en tabla
        array_header_table = []
        for i in columns:
            dict = {'header': i}
            array_header_table.append(dict)

        sheet.add_table(0, 0, aument_rows - 1, len(columns) - 1,
                        {'style': 'Table Style Medium 2', 'columns': array_header_table})
        # Guadar Excel
        book.close()

        # self.write({
        #     'excel_file': base64.encodebytes(stream.getvalue()),
        #     'excel_file_name': filename,
        # })

        return base64.encodebytes(stream.getvalue())

    # Archivo plano patrimonio autonomo popular
    def generate_flat_file_popular_excel(self,obj_payslip):
        filename = f'Plano de patrimonio autonomo popular.xlsx'
        stream = io.BytesIO()
        book = xlsxwriter.Workbook(stream, {'in_memory': True})

        # Columnas
        columns = ['Item', 'No. Factura', 'Tipo ID', 'Numero identificación', 'Nombre 1', 'Nombre 2', 'Apellido 1', 'Apellido 2',
                   'Concepto de pago', 'Valor bruto', 'Valor IVA', 'Retención en la fuente', 'Rete IVA', 'RETE ICA', 'Valor neto a girar',
                   'Valor retención en la fuente', 'Tipo de pago', 'Banco', 'No Cuenta', 'Tipo', 'Repetir causante',
                   'Tipo ID', 'Numero de identificación beneficiario', 'Nombre 1', 'Nombre 2', 'Apellido 1', 'Apellido 2', 'Concepto de pago']
        sheet = book.add_worksheet('Patrimonio autonomo popular')
        # Formato para fechas
        date_format = book.add_format({'num_format': 'dd/mm/yyyy'})
        # Agregar columnas
        aument_columns = 0
        for column in columns:
            sheet.write(0, aument_columns, column)
            aument_columns = aument_columns + 1
        # Agregar nominas
        aument_columns = 0
        aument_rows = 1
        cont_item = 1
        for payslip in obj_payslip:
            sheet.write(aument_rows, 0, cont_item)
            sheet.write(aument_rows, 1, self.payslip_id.name)
            sheet.write(aument_rows, 2, 'cédula')
            sheet.write(aument_rows, 3, payslip.employee_id.work_contact_id.vat_co)
            sheet.write(aument_rows, 4, payslip.employee_id.work_contact_id.firs_name if payslip.employee_id.work_contact_id.firs_name!=False else '')
            sheet.write(aument_rows, 5, payslip.employee_id.work_contact_id.second_name if payslip.employee_id.work_contact_id.second_name!=False else '')
            sheet.write(aument_rows, 6, payslip.employee_id.work_contact_id.first_lastname if payslip.employee_id.work_contact_id.first_lastname!=False else '')
            sheet.write(aument_rows, 7, payslip.employee_id.work_contact_id.second_lastname if payslip.employee_id.work_contact_id.second_lastname!=False else '')
            sheet.write(aument_rows, 8, self.payslip_id.name)
            valor = 0
            valor_rtfte = 0
            valor_not_include = 0
            valor_totaldev,valor_totalded = 0,0
            for line in payslip.line_ids:
                valor_not_include += line.total if line.salary_rule_id.not_include_flat_payment_file else 0
                if line.code == 'NET':
                    valor = line.total - valor_not_include
                    valor = 0 if valor < 0 else valor
                if line.code == 'RETFTE001' or line.code == 'RETFTE_PRIMA001':
                    valor_rtfte = abs(line.total)
                    #valor_rtfte = 0 if valor < 0 else valor
                if line.code == 'TOTALDEV':
                    valor_totaldev = abs(line.total)
                    #valor_totaldev = 0 if valor < 0 else valor
                if line.code == 'TOTALDED':
                    valor_totalded = abs(line.total)
                    #valor_totalded = 0 if valor < 0 else valor
            sheet.write(aument_rows, 9, valor_totaldev)
            sheet.write(aument_rows, 10, '')
            sheet.write(aument_rows, 11, valor_totalded)
            sheet.write(aument_rows, 12, '')
            sheet.write(aument_rows, 13, '')
            sheet.write(aument_rows, 14, valor)#valor
            sheet.write(aument_rows, 15, valor_rtfte)  # valor
            sheet.write(aument_rows, 16, 'ACH')#
            banco = ''
            cuenta_beneficiario = ''
            tipo_cuenta = ''
            for bank in payslip.employee_id.work_contact_id.bank_ids:
                if bank.is_main:
                    banco = bank.bank_id.name
                    cuenta_beneficiario = bank.acc_number
                    tipo_cuenta = 'CH' if bank.type_account == 'A' else 'CC'
            sheet.write(aument_rows, 17, banco)
            sheet.write(aument_rows, 18, cuenta_beneficiario)
            sheet.write(aument_rows, 19, tipo_cuenta)
            sheet.write(aument_rows, 20, '')#si
            sheet.write(aument_rows, 21, '')#Cédula
            sheet.write(aument_rows, 22, '')#payslip.employee_id.work_contact_id.vat_co
            sheet.write(aument_rows, 23, '')#payslip.employee_id.work_contact_id.x_first_name if payslip.employee_id.work_contact_id.x_first_name!=False else ''
            sheet.write(aument_rows, 24, '')#payslip.employee_id.work_contact_id.x_second_name if payslip.employee_id.work_contact_id.x_second_name!=False else ''
            sheet.write(aument_rows, 25, '')#payslip.employee_id.work_contact_id.x_first_lastname if payslip.employee_id.work_contact_id.x_first_lastname!=False else ''
            sheet.write(aument_rows, 26, '')#payslip.employee_id.work_contact_id.x_second_lastname if payslip.employee_id.work_contact_id.x_second_lastname!=False else ''
            sheet.write(aument_rows, 27, '')#self.payslip_id.name
            aument_rows = aument_rows + 1
            cont_item = cont_item + 1
        # Convertir en tabla
        array_header_table = []
        for i in columns:
            dict = {'header': i}
            array_header_table.append(dict)

        sheet.add_table(0, 0, aument_rows - 1, len(columns) - 1,
                        {'style': 'Table Style Medium 2', 'columns': array_header_table})
        # Guadar Excel
        book.close()
        return base64.encodebytes(stream.getvalue())

    # Lógica de Banco Bogotá
    def generate_flat_file_bogota(self, obj_payslip):
        filler = ' '

        def left(s, amount):
            return s[:amount]

        def right(s, amount):
            return s[-amount:]
        # ----------------------------------Registro de Control----------------------------------
        tipo_registro_encab = '1'
        date_today = self.transmission_date
        fecha_pago = str(date_today.year) + right('00' + str(date_today.month), 2) + right('00' + str(date_today.day), 2)
        numero_registro = 'NumRegs'
        valor_total = 'ValorTotalRegs'
        # Inf Bancaria
        cuenta_principal = ''
        tipo_cuenta = ''
        for journal in self.journal_id:
            tipo_cuenta = '02' if self.journal_id.bank_account_id.type_account == 'A' else '01'  # 01: Cuenta corriente / 02: Cuenta ahorros
            cuenta_principal = right(17 * '0' + str(journal.bank_account_id.acc_number).replace("-", ""), 17)
        if cuenta_principal == '':
            raise ValidationError(_('No existe una cuenta bancaria configurada como dispersora de nómina, por favor verificar.'))
        nombre_entidad = left(self.company_id.partner_id.name + 40 * filler, 40)
        nit_empresa = right(11 * '0' + self.vat_payer + '' + str(self.company_id.partner_id.dv), 11)
        codigo_transaccion = '021'  # 021 pago nomina- TD plus y abono afc #022 pago provedores #023 pago Transferencias
        cod_ciudad = '0001' #right(17 * '0' + self.company_id.partner_id.x_city.code, 4)
        fecha_creacion = fecha_pago
        codigo_oficina = '999'
        tipo_identificacion_titular = 'N'
        espacios = filler*29
        valor_libranzas = 18*'0'
        espacios_two = filler*80

        encab_content_txt = '''%s%s%s%s%s%s%s%s%s%s%s%s%s%s%s%s%s%s''' % (
        tipo_registro_encab, fecha_pago, numero_registro,valor_total ,tipo_cuenta,cuenta_principal,nombre_entidad,nit_empresa,
        codigo_transaccion,cod_ciudad,fecha_creacion,codigo_oficina,tipo_identificacion_titular,espacios,valor_libranzas,
        filler,filler,espacios_two)

        # ----------------------------------Registro del detalle----------------------------------
        det_content_txt = ''
        tipo_registro_det = '2'
        cant_detalle = 0
        total_valor_transaccion = 0

        for payslip in obj_payslip:
            cant_detalle = cant_detalle + 1

            # Tipo documento
            document_type = 'C'
            document_type = payslip.employee_id.work_contact_id.l10n_latam_identification_type_id.dian_code
            if document_type == '13':
                document_type = 'C'
            elif document_type == '12':
                document_type = 'T'
            elif document_type == '22':
                document_type = 'E'
            elif document_type == '31':
                document_type = 'N'
            elif document_type == '41':
                document_type = 'P'
            elif document_type == '44':
                document_type = 'E'
            else:
                raise ValidationError(
                    _('El empleado ' + payslip.contract_id.employee_id.name + ' no tiene tipo de documento valido, por favor verificar.'))
            nit_beneficiario = right(11 * '0' + payslip.contract_id.employee_id.work_contact_id.vat_co, 11)
            nombre_beneficiario = left(payslip.contract_id.employee_id.name + 40 * ' ', 40)

            # Inf Bancaria
            tipo_transaccion = ''
            banco_destino = ''
            no_cuenta_beneficiario = ''
            for bank in payslip.employee_id.work_contact_id.bank_ids:
                if bank.is_main:
                    tipo_transaccion = '02' if bank.type_account == 'A' else '01'  # 01: Abono a cuenta corriente / 02: Abono a cuenta ahorros
                    banco_destino = right(3 * '0' + bank.bank_id.bank_code, 3)
                    no_cuenta_beneficiario = left(str(bank.acc_number).replace("-", "") + 17 * ' ', 17)
            if no_cuenta_beneficiario == '':
                raise ValidationError(
                    _('El empleado ' + payslip.contract_id.employee_id.name + ' no tiene configurada la información bancaria, por favor verificar.'))

            # Obtener valor de transacción
            valor_transaccion = 16 * '0'
            valor_transaccion_decimal = 2 * '0'
            valor_not_include = 0
            for line in payslip.line_ids:
                valor_not_include += line.total if line.salary_rule_id.not_include_flat_payment_file else 0
                if line.code == 'NET':
                    total_valor_transaccion = (total_valor_transaccion + line.total) - valor_not_include
                    total_valor_transaccion = 0 if total_valor_transaccion < 0 else total_valor_transaccion
                    val_write = line.total - valor_not_include
                    val_write = 0 if val_write < 0 else val_write
                    valor = str(val_write).split(".")  # Eliminar decimales
                    valor_transaccion = right(16 * '0' + str(valor[0]), 16)
                    valor_transaccion_decimal = right(2 * '0' + str(valor[1]), 2)

            forma_de_pago = 'A'
            codigo_oficina = '000'
            cod_ciudad = '0001' #right(4 * '0' +  payslip.employee_id.work_contact_id.x_city.code, 4)
            espacios = filler*80
            cero = '0'
            numbers = [temp for temp in payslip.number.split("/") if temp.isdigit()]
            num_factura = ''
            for i in numbers:
                num_factura = num_factura + str(i)
            num_factura = right('0' * 10 + num_factura, 10)
            informar = 'N'
            espacios_two = filler*8
            valor_libranza = 18*filler
            creditos = filler*11
            espacios_three = filler*11
            indicador = 'N'
            espacios_four = filler*8

            content_line = '''%s%s%s%s%s%s%s%s%s%s%s%s%s%s%s%s%s%s%s%s%s%s''' % (
            tipo_registro_det,document_type,nit_beneficiario,nombre_beneficiario,tipo_transaccion,no_cuenta_beneficiario,
            valor_transaccion,valor_transaccion_decimal,forma_de_pago,codigo_oficina,banco_destino,cod_ciudad,espacios,
            cero,num_factura,informar,espacios_two,valor_libranza,creditos,espacios_three,indicador,espacios_four)
            if cant_detalle == 1:
                det_content_txt = content_line
            else:
                det_content_txt = det_content_txt + '\n' + content_line

        # Reemplazar valores del encabezado
        encab_content_txt = encab_content_txt.replace("NumRegs", right(5 * '0' + str(cant_detalle), 5))
        valor_total = str(total_valor_transaccion).split(".")  # Eliminar decimales
        encab_content_txt = encab_content_txt.replace("ValorTotalRegs", right(18 * '0' + str(valor_total[0]), 18))
        # Unir Encabezado, Detalle y Totales
        if det_content_txt == '':
            raise ValidationError(_('No existe información en las liquidaciones seleccionadas, por favor verificar.'))

        content_txt = encab_content_txt + '\n' + det_content_txt

        # Retornar archivo
        return base64.encodebytes((content_txt).encode())


    # Lógica de Plano de reglas no incluidas
    def generate_rule_not_included(self,obj_payslip):

        # Generar EXCEL
        filename = f'Plano de reglas no incluidas.xlsx'
        stream = io.BytesIO()
        book = xlsxwriter.Workbook(stream, {'in_memory': True})
        # Columnas
        columns = ['TIPO_DOCUMENTO', 'DOCUMENTO', 'PRODUCTO', 'IDENTIFICADOR', 'VALOR', 'FECHA']
        sheet = book.add_worksheet('Plano para Bono de peoplepass')
        # Formato para fechas
        date_format = book.add_format({'num_format': 'dd/mm/yyyy'})
        # Agregar columnas
        aument_columns = 0
        for column in columns:
            sheet.write(0, aument_columns, column)
            aument_columns = aument_columns + 1
        # Agregar nominas
        aument_columns = 0
        aument_rows = 1
        for payslip in obj_payslip:
            valor_not_include = 0
            for line in payslip.line_ids:
                valor_not_include += line.total if line.salary_rule_id.not_include_flat_payment_file else 0
            if valor_not_include == 0:
                pass
            else:
                #Tipo documento
                document_type = payslip.employee_id.work_contact_id.l10n_latam_identification_type_id.dian_code
                if document_type == '13':
                    document_type = 'CC'
                elif document_type == '12':
                    document_type = 'TI'
                elif document_type == '41':
                    document_type = 'PP'
                elif document_type == '22':
                    document_type = 'CE'
                elif document_type == '31':
                    document_type = 'NTN'
                sheet.write(aument_rows, 0, document_type)
                #Documento
                sheet.write(aument_rows, 1, payslip.employee_id.work_contact_id.vat_co)
                #Producto
                sheet.write(aument_rows, 2, 'Bienestar')
                #Identificador
                sheet.write(aument_rows, 3, '-')
                #Valor
                sheet.write(aument_rows, 4, valor_not_include)
                #Fecha
                sheet.write_datetime(aument_rows, 5, fields.Date.today(), date_format)
                # Ajustar tamaño columna
                #sheet.set_column(aument_columns, aument_columns, width)
                aument_rows = aument_rows + 1
        # Convertir en tabla
        array_header_table = []
        for i in columns:
            dict = {'header': i}
            array_header_table.append(dict)

        sheet.add_table(0, 0, aument_rows - 1, len(columns) - 1,
                        {'style': 'Table Style Medium 2', 'columns': array_header_table})
        # Guadar Excel
        book.close()

        # self.write({
        #     'excel_file': base64.encodebytes(stream.getvalue()),
        #     'excel_file_name': filename,
        # })

        return base64.encodebytes(stream.getvalue())

    def generate_flat_file_bbva(self, obj_payslip):
        filler = ' '

        def left(s, amount):
            return s[:amount]

        def right(s, amount):
            return s[-amount:]

        det_content_txt = ''
        cant_detalle = 0

        for payslip in obj_payslip:
            cant_detalle = cant_detalle + 1
            # Tipo documento
            document_type = '01'
            document_type = payslip.employee_id.work_contact_id.l10n_latam_identification_type_id.dian_code
            if document_type == '13':
                document_type = '01'
            elif document_type == '12':
                document_type = '04'
            elif document_type == '22':
                document_type = '02'
            elif document_type == '31':
                document_type = '03'
            elif document_type == '41':
                document_type = '05'
            else:
                raise ValidationError(_('El empleado ' + payslip.contract_id.employee_id.name + ' no tiene tipo de documento valido, por favor verificar.'))
            nit_beneficiario = right(15 * '0' + payslip.contract_id.employee_id.work_contact_id.vat_co, 15)
            codigo_nit = '0'
            for vat in payslip.employee_id.work_contact_id.l10n_latam_identification_type_id.dian_code:
                dig_verificacion = payslip.employee_id.work_contact_id.dv
                if document_type == '31':
                    codigo_nit = dig_verificacion
            forma_pago = '1'
            cuenta_ajuste = '0'
            banco_destino = ''
            for bank in payslip.contract_id.employee_id.work_contact_id.bank_ids:
                if bank.is_main == True:
                    banco_destino = right(bank.bank_id.bank_code, 3)
            # oficina_receptora = '0000'
            # digito_verificacion = '00'
            # tipo_transaccion = ''
            # for bank in payslip.employee_id.work_contact_id.bank_ids:
            #     if bank.is_main and banco_destino == '0013':
            #         tipo_transaccion = '0200' if bank.type_account == 'A' else '0100' # 0100: Abono a cuenta corriente / 0200: Abono a cuenta ahorros
            #     else:
            #         tipo_transaccion = '0000'
            cuenta = ''
            for bank in payslip.contract_id.employee_id.work_contact_id.bank_ids:
                if bank.is_main == True and banco_destino == '013':
                    cuenta = right(16 * '0' + (bank.acc_number[-16:]), 16)
                else:
                    cuenta = '0000000000000000'
            tipo_cuenta_nacham = ''
            for bank in payslip.employee_id.work_contact_id.bank_ids:
                if bank.is_main == True and banco_destino != '013':
                    tipo_cuenta_nacham = '02' if bank.type_account == 'A' else '01'  # 01: Abono a cuenta corriente / 02: Abono a cuenta ahorros
                elif banco_destino == '013':
                    tipo_cuenta_nacham = '00'
            no_cuenta_nacham = ''
            for bank in payslip.contract_id.employee_id.work_contact_id.bank_ids:
                if bank.is_main == True and banco_destino != '013':
                    no_cuenta_nacham = left(str(bank.acc_number).replace("-", "") + 17 * ' ', 17)
                elif banco_destino == '013':
                    no_cuenta_nacham = '00000000000000000'
            # Obtener valor de transacción
            total_valor_transaccion = 0
            valor_transaccion = 13 * '0'
            valor_transaccion_decimal = 2 * '0'
            valor_not_include = 0
            for line in payslip.line_ids:
                valor_not_include += line.total if line.salary_rule_id.not_include_flat_payment_file else 0
                if line.code == 'NET':
                    total_valor_transaccion = (total_valor_transaccion + line.total) - valor_not_include
                    total_valor_transaccion = 0 if total_valor_transaccion < 0 else total_valor_transaccion
                    val_write = line.total - valor_not_include
                    val_write = 0 if val_write < 0 else val_write
                    valor = str(val_write).split(".")  # Eliminar decimales
                    valor_transaccion = right(13 * '0' + str(valor[0]), 13)
                    valor_transaccion_decimal = right(2 * '0' + str(valor[1]), 2)
            fecha_mov = '00000000'
            codigo_oficina_pagadora = '0000'
            nombre_beneficiario = left(payslip.contract_id.employee_id.name + 36 * ' ' , 36)
            direccion_beneficiario = left(payslip.contract_id.employee_id.work_contact_id.street + 36 * ' ', 36)
            direccion_beneficiario_dos = '                                   '
            email_beneficiario = '                                                 '
            concepto = left(self.description + 40 * ' ', 40)

            content_line = '''%s%s%s%s%s%s%s%s%s%s%s%s%s%s%s%s%s%s''' % (
                document_type, nit_beneficiario, codigo_nit, forma_pago, cuenta_ajuste, banco_destino, cuenta,tipo_cuenta_nacham,
                no_cuenta_nacham,valor_transaccion,valor_transaccion_decimal,fecha_mov,codigo_oficina_pagadora,
                nombre_beneficiario,direccion_beneficiario,direccion_beneficiario_dos,email_beneficiario,concepto)

            if cant_detalle == 1:
                det_content_txt = content_line
            else:
                det_content_txt = det_content_txt + '\n' + content_line
        if det_content_txt == '':
            raise ValidationError(_('No existe información en las liquidaciones seleccionadas, por favor verificar.'))

        content_txt = det_content_txt

        # Retornar archivo
        return base64.encodebytes((content_txt).encode())
    def get_excel_bancoitau(self):
        def truncar_codigo_bancario(codigo):
            """
            Función para truncar el código bancario según la lógica especificada.
            """
            # Verificar si el código es mayor a 1000 y no es 1007
            codigo = int(codigo)
            if codigo >= 1000:
                codigo = codigo % 1000
            return codigo

        filename = f'Cuentas {self.journal_id.name}-{self.date}.xlsx'
        stream = io.BytesIO()
        book = xlsxwriter.Workbook(stream, {'in_memory': True})
        sheet = book.add_worksheet('Facturas De Proveedores')
        columns = [
            'Fecha de envio',
            'Tipo de Identificacion',
            'Numero de Identificacion del Proveedor/tercero',
            'Nombre del tercero',
            'Codigo del banco del tercero',
            'Tipo de cuenta del tercero',
            'Numero de cuenta del tercero',
            'Valor',
            'Referencia',
            'Observacion',
            'E-mail del tercero',
            'Tipo de Cuenta Origen del cliente',
            'Numero de Cuenta Origen del cliente',
        ]

        # Configuraciones de formato
        cell_format_title = book.add_format({'bold': True, 'align': 'left', 'font_name': 'Calibri', 'font_size': 15, 'bottom': 5, 'bottom_color': '#1F497D', 'font_color': '#1F497D'})
        cell_format_text_generate = book.add_format({'bold': False, 'align': 'left', 'font_name': 'Calibri', 'font_size': 10, 'bottom': 5, 'bottom_color': '#1F497D', 'font_color': '#1F497D'})
        date_format = book.add_format({'num_format': 'dd/mm/yyyy'})
        money = book.add_format({'num_format':'$#,##0.00'})

        # Agregar columnas al Excel
        for i, column in enumerate(columns):
            sheet.write(0, i, column, cell_format_title)  # Ajuste aquí: i en lugar de aument_columns
            sheet.set_column(i, i, len(column) + 10)

        # Suponiendo la existencia y estructura de 'self.payment_ids', 'TIPO_DOCUMENT0_BANCOLOMBIA', y 'TIPO_CUENTA_BANCOITAU'
        sorted_lines = sorted(self.li, key=lambda x: x.partner_id.id)
        for row_num, lines in enumerate(sorted_lines, start=1): 
            sheet.write(row_num, 0, lines.date,date_format)
            sheet.write(row_num, 1, TIPO_DOCUMENT0_BANCOLOMBIA.get(lines.partner_id.l10n_latam_identification_type_id.l10n_co_document_code, ''))
            sheet.write(row_num, 2, lines.partner_id.vat_co or "")
            sheet.write(row_num, 3, lines.partner_id.name)
            sheet.write(row_num, 4, truncar_codigo_bancario(lines.partner_bank_id.bank_id.bic))
            sheet.write(row_num, 5, TIPO_CUENTA_BANCOITAU.get(lines.partner_bank_id.acc_type, ''))
            sheet.write(row_num, 6, lines.partner_bank_id.acc_number)
            sheet.write(row_num, 7, lines.amount)
            sheet.write(row_num, 8, lines.ref)
            sheet.write(row_num, 9, self.description)
            sheet.write(row_num, 10, lines.partner_id.email)
            sheet.write(row_num, 11, "AHO" if self.account_type_debit == "s" else "CTE")
            sheet.write(row_num, 12, self.account_debit)

        book.close()

        self.write({
            'excel_file': base64.encodebytes(stream.getvalue()).decode(),
            'excel_file_name': filename,
        })

        action = {
            'name': 'Export Seguridad Social',
            'type': 'ir.actions.act_url',
            'url': f"web/content/?model=account.payment.ce&id={self.id}&filename_field=excel_file_name&field=excel_file&download=true&filename={filename}",
            'target': 'self',
        }
        return action
    #Ejecutar proceso
    def generate_flat_file(self):
        """
        Genera archivos planos de pago de nómina
        - Soporta reglas no incluidas
        - Dispersión por banco o global
        - Control de errores y logs
        """
        try:
            # Limpiar registros anteriores
            self.env['hr.payroll.flat.file.detail'].search([('flat_file_id','=',self.id)]).unlink()
            self.log_ids.unlink()

            # Validaciones iniciales
            if not self.payment_type:
                raise ValidationError(_('Debe seleccionar un tipo de pago'))
                
            if self.payment_type != '225':
                raise ValidationError(_('Solo está soportado el tipo de pago "Pago de Nómina"'))

            if not self.source_information:
                raise ValidationError(_('Debe seleccionar el origen de la información'))

            if self.source_information == 'lote' and not self.payslip_run_ids:
                raise ValidationError(_('Debe seleccionar al menos un lote de nómina'))
                
            if self.source_information == 'liquidacion' and not self.payslip_ids:
                raise ValidationError(_('Debe seleccionar las liquidaciones a procesar'))

            if self.type == 'GL' and not self.journal_id:
                raise ValidationError(_('Debe seleccionar un diario para la dispersión global'))

            # Obtener nóminas según origen
            obj_payslip = self.env['hr.payslip']
            obj_payslip_tmp = self.env['hr.payslip']
            domain = [('employee_id.company_id', '=', self.company_id.id)]

            if self.source_information == 'lote':
                domain.append(('payslip_run_id', 'in', self.payslip_run_ids.ids))
            else:
                domain.append(('id', 'in', self.payslip_ids.ids))

            obj_payslip_tmp = self.env['hr.payslip'].search(domain)
            
            if not obj_payslip_tmp:
                self._create_log('error', 'No se encontraron nóminas que procesar')
                return
                
            # Procesar reglas no incluidas
            if self.flat_rule_not_included:
                try:
                    for payslip in obj_payslip_tmp:
                        # Validar cuenta bancaria
                        if not self._validate_bank_account(payslip):
                            continue
                        obj_payslip += payslip

                    if obj_payslip:
                        file_base64 = self.generate_rule_not_included(obj_payslip)
                        if file_base64:
                            self.env['hr.payroll.flat.file.detail'].create({
                                'flat_file_id': self.id,
                                'plane_type': 'not_include',
                                'excel_file': file_base64,
                                'excel_file_name': 'Reglas no incluidas.xlsx',
                                'liquidations_ids': [(6, 0, obj_payslip.ids)]
                            })
                except Exception as e:
                    self._create_log('error', 'Error procesando reglas no incluidas', detail=str(e))

            # Procesar archivos de pago
            if self.type == 'CD':
                # Proceso por banco
                type_flat_file = ['bancolombiasap','bancolombiapab','davivienda1','occired','avvillas1','bancobogota','popular','bbva']
                for bank_type in type_flat_file:
                    try:
                        obj_payslip = self.env['hr.payslip']
                        
                        # Obtener diario del banco
                        journal = self.env['account.journal'].search([('plane_type', '=', bank_type)], limit=1)
                        if not journal:
                            continue
                            
                        self.journal_id = journal

                        # Filtrar nóminas por banco dispersor
                        for payslip in obj_payslip_tmp:
                            bank = self._validate_bank_account(payslip)
                            if not bank:
                                continue
                                
                            if bank.payroll_dispersion_account.id != journal.id:
                                continue
                                
                            obj_payslip += payslip

                        if obj_payslip:
                            file_base64, file_base64_excel = self._generate_bank_files(bank_type, obj_payslip)
                            if file_base64 or file_base64_excel:
                                self.env['hr.payroll.flat.file.detail'].create({
                                    'flat_file_id': self.id,
                                    'journal_id': journal.id,
                                    'plane_type': bank_type,
                                    'txt_file': file_base64,
                                    'txt_file_name': f"{journal.name} - {self.description}.txt" if file_base64 else False,
                                    'excel_file': file_base64_excel,
                                    'excel_file_name': f"{journal.name} - {self.description}.xlsx" if file_base64_excel else False,
                                    'liquidations_ids': [(6, 0, obj_payslip.ids)]
                                })

                    except Exception as e:
                        self._create_log('error', f'Error procesando banco {bank_type}', detail=str(e))

            else:
                # Proceso global
                try:
                    if not self.journal_id.plane_type:
                        raise ValidationError(_('El diario seleccionado no tiene tipo de plano configurado'))

                    obj_payslip = self.env['hr.payslip']
                    
                    # Validar cuentas y dispersión
                    for payslip in obj_payslip_tmp:
                        bank = self._validate_bank_account(payslip)
                        if not bank:
                            continue
                            
                        #if not bank.payroll_dispersion_account:
                        #    self._create_log('error', 'Cuenta sin banco dispersor', payslip)
                        #    continue
                            
                        obj_payslip += payslip

                    if obj_payslip:
                        file_base64, file_base64_excel = self._generate_bank_files(self.journal_id.plane_type, obj_payslip)
                        if file_base64 or file_base64_excel:
                            self.env['hr.payroll.flat.file.detail'].create({
                                'flat_file_id': self.id,
                                'journal_id': self.journal_id.id,
                                'plane_type': self.journal_id.plane_type,
                                'txt_file': file_base64,
                                'txt_file_name': f"{self.journal_id.name} - {self.description}.txt" if file_base64 else False,
                                'excel_file': file_base64_excel,
                                'excel_file_name': f"{self.journal_id.name} - {self.description}.xlsx" if file_base64_excel else False,
                                'liquidations_ids': [(6, 0, obj_payslip.ids)]
                            })

                except Exception as e:
                    self._create_log('error', 'Error en proceso global', detail=str(e))

            # Verificar resultados
            if not self.detail_ids:
                self._create_log('error', 'No se generó ningún archivo')
            elif not self.error_count:
                self.state = 'generated'
                self._create_log('info', f'Proceso completado. {len(self.detail_ids)} archivos generados')
            else:
                self._create_log('warning', f'Proceso completado con {self.error_count} errores')

        except Exception as e:
            self._create_log('error', 'Error general en el proceso', detail=str(e))
            #raise ValidationError(_('Error en el proceso. Revise el log de errores.'))

    def _validate_bank_account(self, payslip):
        """Validar cuenta bancaria del empleado"""
        banks = payslip.employee_id.work_contact_id.bank_ids.filtered('is_main')
        if not banks:
            self._create_log(
                'error', 
                'Sin cuenta bancaria principal',
                payslip=payslip
            )
            return False
        if len(banks) > 1:
            self._create_log(
                'error',
                'Múltiples cuentas principales',
                payslip=payslip
            )
            return False
        return banks[0]

    def _generate_bank_files(self, bank_type, payslips):
        """Generar archivos según tipo de banco"""
        file_base64 = False
        file_base64_excel = False
        
        try:
            if bank_type == 'bancolombiasap':
                file_base64 = self.generate_flat_file_sap(payslips)
            elif bank_type == 'bancolombiapab':
                file_base64 = self.generate_flat_file_pab(payslips)
            elif bank_type == 'davivienda1':
                file_base64 = self.generate_flat_file_davivienda(payslips)
            elif bank_type == 'occired':
                file_base64 = self.generate_flat_file_occired(payslips)
            elif bank_type == 'avvillas1':
                file_base64 = self.generate_flat_file_avvillas(payslips)
            elif bank_type == 'bbva':
                file_base64 = self.generate_flat_file_bbva(payslips)
            elif bank_type == 'bancobogota':
                file_base64 = self.generate_flat_file_bogota(payslips)
                file_base64_excel = self.generate_flat_file_bogota_excel(payslips)
            elif bank_type == 'popular':
                file_base64_excel = self.generate_flat_file_popular_excel(payslips)
            elif bank_type == 'alianza':
                file_base64_excel = self.generate_alianza_excel(payslips)
        except Exception as e:
            self._create_log('error', f'Error generando archivo {bank_type}', detail=str(e))
            
        return file_base64, file_base64_excel


    def _create_log(self, type, name, payslip=None, error_type='other', detail=None, bank_id=None):
        vals = {
            'flat_file_id': self.id,
            'type': type,
            'name': name,
            'error_type': error_type,
            'detail': detail,
        }

        if payslip:
            employee = payslip.employee_id
            vals.update({
                'employee_id': employee.id,
                'payslip_id': payslip.id
            })
            
            # Obtener información bancaria
            main_bank = employee.work_contact_id.bank_ids.filtered('is_main')
            if main_bank:
                vals.update({
                    'bank_id': main_bank.bank_id.id,
                    'account_number': main_bank.acc_number
                })

        return self.env['payroll.file.process.log'].create(vals)

    def _process_payslip_batch(self, batch):
        for payslip in batch:
            try:
                main_banks = payslip.employee_id.work_contact_id.bank_ids.filtered('is_main')
                if not main_banks:
                    self._create_log(
                        'error',
                        'Empleado sin cuenta bancaria',
                        payslip,
                        'bank_missing'
                    )
                    continue
                    
                if len(main_banks) > 1:
                    self._create_log(
                        'error',
                        'Empleado con múltiples cuentas principales',
                        payslip,
                        'multiple_banks'
                    )
                    continue

                bank = main_banks[0]
                if not bank.payroll_dispersion_account:
                    self._create_log(
                        'error',
                        'Cuenta sin banco dispersor configurado',
                        payslip,
                        'invalid_bank'
                    )
                    continue

                bank_type = bank.payroll_dispersion_account.plane_type
                if not bank_type:
                    self._create_log(
                        'error',
                        'Banco sin tipo de archivo configurado',
                        payslip,
                        'invalid_bank',
                        bank_id=bank.bank_id.id
                    )
                    continue

                if bank_type not in bank_groups:
                    bank_groups[bank_type] = self.env['hr.payslip']
                bank_groups[bank_type] |= payslip

            except Exception as e:
                self._create_log(
                    'error',
                    'Error procesando nómina',
                    payslip,
                    'other',
                    detail=str(e)
                )
                
class HrPayrollUnpaidWizard(models.TransientModel):
    _name = 'hr.payroll.unpaid.wizard'
    _description = 'Wizard para marcar nóminas como no pagadas'

    detail_id = fields.Many2one(
        'hr.payroll.flat.file.detail',
        string='Detalle',
        required=True
    )
    filter_employee = fields.Char(
        string='Buscar Empleado',
        help='Filtrar por nombre o identificación del empleado'
    )
    all_payslip_ids = fields.Many2many(
        'hr.payslip',
        'hr_wizard_all_payslip_rel',
        'wizard_id',
        'payslip_id',
        string='Todas las Nóminas',
        compute='_compute_all_payslips'
    )
    payslip_ids = fields.Many2many(
        'hr.payslip',
        'hr_wizard_payslip_rel',
        'wizard_id',
        'payslip_id',
        string='Nóminas Seleccionadas',
        domain="[('id', 'in', all_payslip_ids)]",
        required=True
    )
    reason = fields.Selection([
        ('insufficient_funds', 'Fondos Insuficientes'),
        ('account_blocked', 'Cuenta Bloqueada'),
        ('wrong_account', 'Cuenta Incorrecta'),
        ('technical_error', 'Error Técnico'),
        ('other', 'Otros')
    ], string='Motivo', required=True)
    notes = fields.Text('Notas')

    @api.depends('detail_id', 'filter_employee')
    def _compute_all_payslips(self):
        for record in self:
            domain = [('id', 'in', record.detail_id.liquidations_ids.ids)]
            if record.filter_employee:
                domain += [
                    '|', '|',
                    ('employee_id.name', 'ilike', record.filter_employee),
                    ('employee_id.identification_id', 'ilike', record.filter_employee),
                    ('number', 'ilike', record.filter_employee)
                ]
            record.all_payslip_ids = self.env['hr.payslip'].search(domain)

    # @api.onchange('filter_employee')
    # def _onchange_filter_employee(self):
    #     if not self.filter_employee:
    #         self.payslip_ids = self.all_payslip_ids

    def action_confirm(self):
        self.ensure_one()
        if not self.payslip_ids:
            raise ValidationError(_('Debe seleccionar al menos una nómina.'))
        for payslip in self.payslip_ids:
            self.detail_id.mark_payslip_as_unpaid(payslip.id, self.reason, self.notes)
        return {'type': 'ir.actions.act_window_close'}
class HrPayrollResolveTransferWizard(models.TransientModel):
    _name = 'hr.payroll.resolve.transfer.wizard'
    _description = 'Wizard para resolver problemas de transferencia'

    detail_id = fields.Many2one(
        'hr.payroll.flat.file.detail',
        string='Detalle',
        required=True
    )
    payslip_ids = fields.Many2many(
        'hr.payslip',
        string='Nóminas',
        required=True,
       # domain="[('id', 'in', detail_id.unpaid_payslip_ids.ids)]",
    )
    resolution_notes = fields.Text(
        'Notas de Resolución',
        required=True
    )

    def action_confirm(self):
        self.ensure_one()
        if not self.payslip_ids:
            raise ValidationError(_('Debe seleccionar al menos una nómina.'))
        for payslip in self.payslip_ids:
            self.detail_id.resolve_transfer_issue(
                payslip.id,
                self.resolution_notes
            )
        return {'type': 'ir.actions.act_window_close'}


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'
    
    transfer_state = fields.Selection([
        ('draft', 'Pendiente'),
        ('processing', 'En Proceso'),
        ('done', 'Transferido'),
        ('rejected', 'Rechazado')
    ], string='Estado de Transferencia', default='draft', tracking=True)
    
    transfer_reason = fields.Selection([
        ('insufficient_funds', 'Fondos Insuficientes'),
        ('account_blocked', 'Cuenta Bloqueada'),
        ('wrong_account', 'Cuenta Incorrecta'),
        ('technical_error', 'Error Técnico'),
        ('other', 'Otros')
    ], string='Motivo Rechazo', tracking=True)
    
    transfer_notes = fields.Text('Notas de Transferencia', tracking=True)
    transfer_date = fields.Datetime('Fecha de Transferencia', tracking=True)
    transfer_resolved_date = fields.Datetime('Fecha Resolución', tracking=True)
    transfer_resolution_notes = fields.Text('Notas de Resolución', tracking=True)
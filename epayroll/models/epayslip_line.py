# -*- coding: utf-8 -*-
import base64

from datetime import date, datetime
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_round, date_utils
from odoo.tools.misc import format_date
from odoo.tools.safe_eval import safe_eval
import logging

_logger = logging.getLogger(__name__)
class HrPayslip(models.Model):
    _name = 'hr.payslip.edi'
    _inherit = ['mail.thread.cc', 'mail.activity.mixin']
    _order = 'date_to desc'
    
    struct_id = fields.Many2one('hr.payroll.structure', string='Estructura',
        help='Defines the rules that have to be applied to this payslip, according '
            'to the contract chosen. If the contract is empty, this field isn\'t '
            'mandatory anymore and all the valid rules of the structures '
            'of the employee\'s contracts will be applied.')
    struct_type_id = fields.Many2one('hr.payroll.structure.type', related='struct_id.type_id')
    wage_type = fields.Selection(related='struct_type_id.wage_type')
    name = fields.Char(string='Referencia',  required=True)
    number = fields.Char(string='Numero', default='/', copy=False)
    employee_id = fields.Many2one('hr.employee', string='Empleado', required=True, domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]")
    date_from = fields.Date(string='Desde',  required=True,
        default=lambda self: fields.Date.to_string(date.today().replace(day=1)),)
    date_to = fields.Date(string='A', required=True,
        default=lambda self: fields.Date.to_string((datetime.now() + relativedelta(months=+1, day=1, days=-1)).date()))
    state = fields.Selection([
        ('draft', 'Draft'),
        ('verify', 'Waiting'),
        ('done', 'Done'),
        ('cancel', 'Rejected'),
    ], string='Estado', index=True, readonly=True, copy=False, default='draft',
        help="""* When the payslip is created the status is \'Draft\'
                \n* If the payslip is under verification, the status is \'Waiting\'.
                \n* If the payslip is confirmed then status is set to \'Done\'.
                \n* When user cancel payslip the status is \'Rejected\'.""")
    line_ids = fields.One2many('hr.payslip.edi.line', 'slip_id', store=True, string='Líneas de nomina')
    company_id = fields.Many2one('res.company', string='Company', readonly=True, copy=False, required=True,
        default=lambda self: self.env.company,)
    worked_days_line_ids = fields.One2many('hr.payslip.edi.worked_days', 'payslip_id',
        string='Días trabajados', copy=True)
    paid = fields.Boolean(string='Made Payment Order ? ', readonly=True, copy=False)
    note = fields.Text(string='Internal Note')
    contract_id = fields.Many2one('hr.contract', string='Contract',  domain="[('company_id', '=', company_id)]")
    credit_note = fields.Boolean(string='Credit Note', help="Indicates this payslip has a refund of another")
    payslip_run_id = fields.Many2one('hr.payslip.edi.run', string='Batch Name', ondelete='cascade',
        domain="[('company_id', '=', company_id)]")
    sum_worked_hours = fields.Float(compute='_compute_worked_hours', store=True, help='Total hours of attendance and time off (paid or not)')
    # YTI TODO: normal_wage to be removed
    normal_wage = fields.Integer(compute='_compute_normal_wage', store=True)
    compute_date = fields.Date('Computed On')
    basic_wage = fields.Monetary(compute='_compute_basic_net')
    net_wage = fields.Monetary(compute='_compute_basic_net')
    currency_id = fields.Many2one(related='contract_id.currency_id')
    warning_message = fields.Char(readonly=True)
    validar_cron = fields.Boolean('Validar por Cron')
    is_superuser = fields.Boolean(compute="_compute_is_superuser")
    payslip_ids = fields.One2many('hr.payslip', 'epayslip_bach_id', string='Nominas del mes')
    total_devengos = fields.Float('Total Devengados', default=0.0)
    total_deducciones = fields.Float('Total Deducciones', default=0.0)
    total_paid = fields.Float('Total Comprobante', default=0.0)

    def action_cancel(self): 
        return self.write({'state': 'cancel'})

    def action_draft(self):
        self._cr.execute(''' DELETE FROM hr_payslip_nes_line WHERE slip_id2 = %s''', (self.id,))
        self._cr.execute(''' DELETE FROM hr_payslip_nes_line_ded WHERE slip_id2 = %s''', (self.id,))
        return self.write({'state': 'draft', 'total_devengos': 0.0, 'total_deducciones': 0.0, 'total_paid': 0.0})

    def update_total(self):
        DevengadosTotal = self.get_value_etotal('devengados', self)
        self.total_devengos = round(DevengadosTotal, 2)
        DeduccionesTotal = self.get_value_etotal('deducciones', self)
        self.total_deducciones = round(DeduccionesTotal, 2)
        ComprobanteTotal = DevengadosTotal + DeduccionesTotal
        self.total_paid = round(ComprobanteTotal, 2)

    def get_value_etotal(self, tag, edi):
        if tag == 'devengados':
            self._cr.execute(''' SELECT sum(total)
                                    FROM hr_payslip_edi_line l
                                    inner join hr_salary_rule r on r.id=l.salary_rule_id
                                    WHERE r.devengado_rule_id IS NOT NULL and slip_id=%s ''', (edi.id,))
            value_tag = self._cr.fetchone()
            if value_tag and value_tag[0]:
                return value_tag[0]
            else:
                return 0.0
        elif tag == 'deducciones':  # Use elif to avoid unnecessary checks
            self._cr.execute(''' SELECT sum(total)
                                    FROM hr_payslip_edi_line l
                                    inner join hr_salary_rule r on r.id=l.salary_rule_id
                                    WHERE r.deduccion_rule_id IS NOT NULL and slip_id=%s ''', (edi.id,))
            value_tag = self._cr.fetchone()
            if value_tag and value_tag[0]:
                return value_tag[0]
            else:
                return 0.0         

    @api.onchange('employee_id', 'struct_id', 'contract_id', 'date_from', 'date_to')
    def _onchange_employee(self):
        if (not self.employee_id) or (not self.date_from) or (not self.date_to):
            return

        employee = self.employee_id
        date_from = self.date_from
        date_to = self.date_to

        self.company_id = employee.company_id

        if not self.contract_id or self.employee_id != self.contract_id.employee_id:
            #contracts = employee._get_contracts(date_from, date_to)
           #if not contracts:
            closed_payslips = self.env['hr.payslip'].search([
                ('employee_id', '=', employee.id),
                ('state', 'in', ['done', 'paid']),
                ('date_from', '<=', date_to),
                ('date_to', '>=', date_from)
            ], order='date_to desc', limit=1)
            if closed_payslips:
                self.contract_id = closed_payslips.contract_id
                self.struct_id = closed_payslips.struct_id
            else:
                self.contract_id = False
                self.struct_id = False

        lang = employee.sudo().work_contact_id.lang or self.env.user.lang
        context = {'lang': lang}
        payslip_name = self.struct_id.payslip_name or _('Salary Slip')
        del context

        self.name = '%s - %s - %s' % (
            payslip_name,
            self.employee_id.name or '',
            format_date(self.env, self.date_from, date_format="MMMM y", lang_code=lang)
        )

        if date_to > date_utils.end_of(fields.Date.today(), 'month'):
            self.warning_message = _(
                "This payslip can be erroneous! Work entries may not be generated for the period from %(start)s to %(end)s.",
                start=date_utils.add(date_utils.end_of(fields.Date.today(), 'month'), days=1),
                end=date_to,
            )
        else:
            self.warning_message = False


    def _get_contract_wage(self):
        self.ensure_one()
        return self.contract_id._get_contract_wage()

    @api.depends('contract_id')
    def _compute_normal_wage(self):
        with_contract = self.filtered('contract_id')
        (self - with_contract).normal_wage = 0
        for payslip in with_contract:
            payslip.normal_wage = payslip._get_contract_wage()

    def update_tabla(self, epayslip):
        if not self.payslip_ids:
            return False

        special_codes = ['HEYREC', 'VACACIONES', 'INCAPACIDAD', 'LICENCIA_REMUNERADA', 'LICENCIA_MATERNIDAD', 'ACCIDENTE_TRABAJO']
        
        def aggregate_lines(data):
            aggregated = {}
            for d in data:
                key = (d['code'], d['name'])
                if key not in aggregated:
                    aggregated[key] = {**d, 'total': 0, 'quantity': 0}
                aggregated[key]['total'] += d['total']
                aggregated[key]['quantity'] += d['quantity']
            return list(aggregated.values())

        # Process worked days
        worked_days = {}
        for rec in epayslip.payslip_ids.filtered(lambda x: x.struct_process in ('nomina', 'contrato')).worked_days_line_ids:
            if rec:
                key = (rec.code, rec.name)
                if key not in worked_days:
                    worked_days[key] = {
                        'name': rec.name,
                        'code': rec.code,
                        'payslip_id': epayslip.id,
                        'work_entry_type_id': rec.work_entry_type_id.id,
                        'number_of_days': 0,
                        'number_of_hours': 0,
                        'amount': 0,
                        'contract_id': rec.contract_id.id,
                    }
                worked_days[key]['number_of_days'] += rec.number_of_days
                worked_days[key]['number_of_hours'] += rec.number_of_hours
                worked_days[key]['amount'] += rec.amount

        # Apply the 30-day limit to WORK100 after aggregation
        for key, value in worked_days.items():
            if value['code'] == 'WORK100':
                value['number_of_days'] = min(value['number_of_days'], 30)

        worked = [(0, 0, value) for value in worked_days.values()]

        # SQL query for both devengado and deduccion rules
        query = """
        SELECT 
            r.id as rule, 
            SUM(l.total) as total,
            %s as batch_id,
            l.employee_id,
            r.name::jsonb ->> 'en_US' as name,
            r.code as code,
            r.sequence as sequence,
            %s as batch_run_id,
            SUM(l.quantity) as quantity
        FROM hr_payslip_line l
        INNER JOIN hr_salary_rule r ON r.id = l.salary_rule_id
        WHERE (r.devengado_rule_id IS NOT NULL OR r.deduccion_rule_id IS NOT NULL)
            AND slip_id IN %s 
            AND total <> 0.0 
        GROUP BY r.id, r.devengado_rule_id, r.deduccion_rule_id, l.employee_id
        """
        
        self.env.cr.execute(query, (epayslip.id, epayslip.payslip_run_id.id, tuple(epayslip.payslip_ids.ids)))
        data = self.env.cr.dictfetchall()
        
        # Aggregate data for special codes
        aggregated_data = aggregate_lines([d for d in data if d['code'] in special_codes])
        other_data = [d for d in data if d['code'] not in special_codes]
        
        # Combine aggregated and non-aggregated data
        combined_data = aggregated_data + other_data
        
        # Create line items
        lista = []
        for d in combined_data:
            amount_per_unit = d['total'] / d['quantity'] if d['quantity'] != 0 else 0.0
            lista.append((0, 0, {
                'salary_rule_id': d['rule'],
                'rate': 100,
                'quantity': d['quantity'],
                'amount': amount_per_unit,
                'slip_id': d['batch_id'],
                'name': d['name'],
                'code': d['code'],
                'sequence': d['sequence'],
            }))

        if lista:
            epayslip.worked_days_line_ids.unlink()
            epayslip.line_ids.unlink()
            epayslip.line_ids = lista
            epayslip.worked_days_line_ids = worked

        return True

    def _compute_basic_net(self):
        for rec in self:
            BASIC = 0
            NET = 0
            if rec.payslip_ids.line_ids:
                for line_id in rec.payslip_ids.filtered(lambda x: x.struct_process in ('nomina','contrato')).line_ids:
                    if line_id.category_id.code == 'BASIC':
                        BASIC += abs(line_id.total)
                    elif line_id.category_id.code == 'NET':
                        NET += abs(line_id.total)
            rec.basic_wage = BASIC
            rec.net_wage = NET

    def _compute_is_superuser(self):
        self.update({'is_superuser': self.env.user._is_superuser() and self.user_has_groups("base.group_no_one")})
    
    @api.depends('worked_days_line_ids.number_of_hours', 'worked_days_line_ids.is_paid')
    def _compute_worked_hours(self):
        for payslip in self:
            payslip.sum_worked_hours = sum([line.number_of_hours for line in payslip.worked_days_line_ids])
    
    def update_data(self):
        for epayslip in self:
            epayslip.get_payslip_period()
            epayslip.get_epayslip_line(epayslip)
            epayslip.update_total()
    
    def get_payslip_period(self):
        self.payslip_ids = [(5,0,0)]
        payslip_ids = self.env['hr.payslip'].search([('employee_id','=', self.employee_id.id),('state','in',('done','paid')),('date_to','>=', self.date_from),('date_to','<=',self.date_to)])
        if payslip_ids:
            lista = []
            for payslip_id in payslip_ids:
                lista.append((4,payslip_id.id))
            self.payslip_ids = lista
            self.update_edi()
        return 

    def update_edi(self):
        if self.payslip_ids:
            for rec in self.payslip_ids:
                rec.write({'epayslip_bach_id':self.id}) 
                
    def get_epayslip_line(self,epayslip):
        self.update_tabla(epayslip)
        self.env.cr.commit()


    @api.model_create_multi
    def create(self, vals_list):
        new_list = []
        for vals in vals_list:
            if vals.get("number", "/") == "/" and vals.get("credit_note") == False:
                new_vals = dict(
                    vals, number=self.env["ir.sequence"].next_by_code("bach.epayslip")
                )
            else:
                new_vals = dict(
                    vals, number=self.env["ir.sequence"].next_by_code("bachepayslipnote")
                )
            new_list.append(new_vals)
        return super().create(new_list)

    def action_generated_number(self):
        for epayslip in self:
            if epayslip.credit_note == False and epayslip.number == "/":
                number = self.env['ir.sequence'].next_by_code('bach.epayslip')
            else:
                number = self.env['ir.sequence'].next_by_code('bachepayslipnote')
            return epayslip.write({'number': number})

    def merge_lines_worked(self):
        read_group_result = self.env['hr.payslip.edi.worked_days'].read_group(
            [('payslip_id', '=', self.id)], ['work_entry_type_id', 'number_of_days', 'number_of_hours','amount'], ['work_entry_type_id'])
        for order in read_group_result:
            worked_days_line_ids = self.env['hr.payslip.edi.worked_days'].search(
                [('payslip_id', '=', self.id), ('work_entry_type_id', '=', order['work_entry_type_id'][0])])
            main_line = worked_days_line_ids[0]
            worked_days_line_ids[1:].unlink()
            main_line.number_of_days = order['number_of_days']
            main_line.number_of_hours = order['number_of_hours']
            main_line.amount = order['amount']


    def merge_lines(self):
        def process_lines(category, in_category=True):
            domain = [('slip_id', '=', self.id)]
            if in_category:
                domain.append(('salary_rule_id.earn_category', '=', category))
            else:
                domain.append(('salary_rule_id.earn_category', 'not in', categories))

            read_group_result = self.env['hr.payslip.edi.line'].read_group(
                domain, ['amount', 'quantity', 'total', 'category_id', 'salary_rule_id'], ['category_id' if in_category else 'salary_rule_id']
            )
            for group in read_group_result:
                line_ids = self.env['hr.payslip.edi.line'].search(
                    domain + [('category_id' if in_category else 'salary_rule_id', '=', group['category_id'][0] if in_category else group['salary_rule_id'][0])]
                )
                if line_ids:
                    main_line = line_ids[0]
                    line_ids[1:].unlink()
                    main_line.amount = group['total'] / group['quantity'] if group['quantity'] > 1 else group['amount']
                    main_line.quantity = group['quantity']

        categories = ['primas', 'layoffs', 'layoffs_interest']
        for category in categories:
            process_lines(category)
        
        process_lines(categories, False)


    def handle_zero_amount_lines(self):
        zero_amount_lines = self.env['hr.payslip.edi.line'].search([('slip_id', '=', self.id),('amount', '=', 0)])
        average_amount = 0
        for line in zero_amount_lines:
            same_rule_lines = self.env['hr.payslip.line'].search(
                [('slip_id', 'in', self.payslip_ids.ids), ('salary_rule_id', '=', line.salary_rule_id.id)]
            )
            total_amount = sum(l.total for l in same_rule_lines)
            total_quantity = sum(l.quantity for l in same_rule_lines)
            total_rate = max(l.rate for l in same_rule_lines)
            average_amount = total_amount / total_quantity / total_rate
            if total_quantity > 0:
                if line.amount == 0:
                    line.amount = same_rule_lines.amount

class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    epayslip_bach_id = fields.Many2one('hr.payslip.edi', string='Nominas del mes')

class HrPayslipLine(models.Model):
    _name = 'hr.payslip.edi.line'
    _description = 'Payslip Line'
    _order = 'contract_id, sequence, code'

    name = fields.Char(required=True)
    note = fields.Text(string='Description')
    sequence = fields.Integer(required=True, index=True, default=5,
                              help='Use to arrange calculation sequence')
    code = fields.Char(required=True,
                       help="The code of salary rules can be used as reference in computation of other rules. "
                       "In that case, it is case sensitive.")
    slip_id = fields.Many2one('hr.payslip.edi', string='Pay Slip', required=True, ondelete='cascade')
    salary_rule_id = fields.Many2one('hr.salary.rule', string='Rule', required=True)
    contract_id = fields.Many2one('hr.contract', string='Contract', required=True, index=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True)
    rate = fields.Float(string='Rate (%)', digits='Payroll Rate', default=100.0)
    amount = fields.Float(digits='Payroll')
    quantity = fields.Float(digits='Payroll', default=1.0)
    total = fields.Float(compute='_compute_total', string='Total', digits='Payroll', store=True)
    struct_id = fields.Many2one(related='salary_rule_id.struct_id', readonly=True, store=True)
    
    amount_select = fields.Selection(related='salary_rule_id.amount_select', readonly=True)
    amount_fix = fields.Float(related='salary_rule_id.amount_fix', readonly=True)
    amount_percentage = fields.Float(related='salary_rule_id.amount_percentage', readonly=True)
    appears_on_payslip = fields.Boolean(related='salary_rule_id.appears_on_payslip', readonly=True)
    category_id = fields.Many2one(related='salary_rule_id.category_id', readonly=True, store=True)
    partner_id = fields.Many2one(related='salary_rule_id.partner_id', readonly=True, store=True)

    date_from = fields.Date(string='From', related="slip_id.date_from", store=True)
    date_to = fields.Date(string='To', related="slip_id.date_to", store=True)
    company_id = fields.Many2one(related='slip_id.company_id')

    @api.depends('quantity', 'amount', 'rate')
    def _compute_total(self):
        for line in self:
            line.total = float(line.quantity) * line.amount * line.rate / 100
    days_qty = fields.Integer('Dias Calculados')
    calculated_percentage = fields.Float('% Calculado')
    #sequence_rule = fields.Integer(related="salary_rule_id.sequence_rule")

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            if 'employee_id' not in values or 'contract_id' not in values:
                payslip = self.env['hr.payslip.edi'].browse(values.get('slip_id'))
                values['employee_id'] = values.get('employee_id') or payslip.employee_id.id
                values['contract_id'] = values.get('contract_id') or payslip.contract_id and payslip.contract_id.id
                if not values['contract_id']:
                    raise UserError(_('You must set a contract to create a payslip line.'))
        return super(HrPayslipLine, self).create(vals_list)


class HrPayslipWorkedDays(models.Model):
    _name = 'hr.payslip.edi.worked_days'
    _description = 'Payslip Worked Days'
    _order = 'payslip_id, sequence'

    name = fields.Char(related='work_entry_type_id.name', string='Description', readonly=True)
    payslip_id = fields.Many2one('hr.payslip.edi', string='Pay Slip', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(required=True, index=True, default=10)
    code = fields.Char(string='Code', related='work_entry_type_id.code')
    work_entry_type_id = fields.Many2one('hr.work.entry.type', string='Type', required=True, help="The code that can be used in the salary rules")
    number_of_days = fields.Float(string='Number of Days')
    number_of_hours = fields.Float(string='Number of Hours')
    is_paid = fields.Boolean(compute='_compute_is_paid', store=True)
    amount = fields.Monetary(string='Amount', compute='_compute_amount', store=True)
    contract_id = fields.Many2one(related='payslip_id.contract_id', string='Contract',
        help="The contract for which apply this worked days")
    currency_id = fields.Many2one('res.currency', related='payslip_id.currency_id')

    @api.depends('work_entry_type_id', 'payslip_id', 'payslip_id.struct_id')
    def _compute_is_paid(self):
        unpaid = {struct.id: struct.unpaid_work_entry_type_ids.ids for struct in self.mapped('payslip_id.struct_id')}
        for worked_days in self:
            worked_days.is_paid = worked_days.work_entry_type_id.id not in unpaid[worked_days.payslip_id.struct_id.id] if worked_days.payslip_id.struct_id.id in unpaid else False

    @api.depends('is_paid', 'number_of_hours', 'payslip_id', 'payslip_id.normal_wage', 'payslip_id.sum_worked_hours')
    def _compute_amount(self):
        for worked_days in self:
            if not worked_days.contract_id:
                worked_days.amount = 0
                continue
            if worked_days.payslip_id.wage_type == "hourly":
                worked_days.amount = worked_days.payslip_id.contract_id.hourly_wage * worked_days.number_of_hours if worked_days.is_paid else 0
            else:
                worked_days.amount = worked_days.payslip_id.normal_wage * worked_days.number_of_hours / (worked_days.payslip_id.sum_worked_hours or 1) if worked_days.is_paid else 0

class HrPayslipRunEdi(models.Model):
    _name = 'hr.payslip.edi.run'
    _description = 'Payslip Batches'
    _order = 'date_end desc'

    name = fields.Char(required=True)
    slip_ids = fields.One2many('hr.payslip.edi', 'payslip_run_id', string='Nomina')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('verify', 'Verify'),
        ('close', 'Done'),
    ], string='Estados', index=True, readonly=True, copy=False, default='draft')
    date_start = fields.Date(string='Fecha Inicio', required=True, default=lambda self: fields.Date.to_string(date.today().replace(day=1)))
    date_end = fields.Date(string='Fecha Fin', required=True,
        default=lambda self: fields.Date.to_string((datetime.now() + relativedelta(months=+1, day=1, days=-1)).date()))
    credit_note = fields.Boolean(string='Credit Note',
        help="If its checked, indicates that all payslips generated from here are refund payslips.")
    payslip_count = fields.Integer(compute='_compute_payslip_count')
    company_id = fields.Many2one('res.company', string='Company', readonly=True, required=True,
        default=lambda self: self.env.company)

    def _compute_payslip_count(self):
        for payslip_run in self:
            payslip_run.payslip_count = len(payslip_run.slip_ids)

    def action_draft(self):
        return self.write({'state': 'draft'})

    def action_close(self):
        if self._are_payslips_ready():
            self.write({'state' : 'close'})

    def action_validate(self):
        for rec in self:
            rec.mapped('slip_ids').filtered(lambda slip: slip.state != 'cancel').update_data()

    def compute_sheet(self):
        for rec in self.slip_ids.filtered(lambda slip: slip.state != 'done' and slip.state_dian != 'exitoso'):
            rec.compute_sheet_nes()

    def action_confirm(self):
        for index, rec in enumerate(self, 1):
            if not any(rec.mapped('slip_ids').filtered(lambda slip: slip.net_wage != 0)):
                raise UserError(_('Compute Hoja antes de confirmar'))
            else:
                for slip in rec.mapped('slip_ids').filtered(lambda slip: slip.state == 'verify' and slip.state_dian != 'exitoso'):
                    slip.validate()
                    self.env.cr.commit()
            rec.write({'state': 'close'})

    def restart_full_payroll_batch(self):
        for payslip in self.slip_ids:
            payslip.write({'state':'verify'})
            payslip.action_cancel()
            payslip.unlink()
        return self.write({'state': 'draft'})


    def action_open_payslips(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "hr.payslip.edi",
            "views": [[False, "tree"], [False, "form"]],
            "domain": [['id', 'in', self.slip_ids.ids]],
            "name": "Payslips",
        }

    def unlink(self):
        if any(self.filtered(lambda payslip_run: payslip_run.state not in ('draft'))):
            raise UserError(_('You cannot delete a payslip batch which is not draft!'))
        if any(self.mapped('slip_ids').filtered(lambda payslip: payslip.state not in ('draft','cancel'))):
            raise UserError(_('You cannot delete a payslip which is not draft or cancelled!'))
        return super(HrPayslipRunEdi, self).unlink()

    def _are_payslips_ready(self):
        return all(slip.state in ['done', 'cancel'] for slip in self.mapped('slip_ids'))



class EPayslipLine(models.Model):
    _name = 'epayslip.line'
    _description = 'EPayslip Line'
    _rec_name = 'name'

    salary_rule_id = fields.Many2one('hr.salary.rule', string='Salary rule')
    electronictag_id = fields.Many2one('hr.electronictag.structure', string='Electronic Tags')
    value = fields.Float(string="Valor", default=0.00) # Agregar tipo de moneda
    epayslip_bach_id = fields.Many2one('epayslip.bach', string='Epayslip bach', ondelete="cascade")
    employee_id = fields.Many2one('hr.employee', string='HR employee')
    bach_run_id = fields.Many2one('epayslip.bach.run', string='Bach Run')
    name = fields.Char(string='name')
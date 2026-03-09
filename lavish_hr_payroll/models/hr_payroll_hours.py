# -*- coding: utf-8 -*-
from datetime import date, datetime, timedelta
from odoo.tools.safe_eval import safe_eval as eval
from odoo import api, fields, models, _
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
def hours_time_string(hours):
    """ convert a number of hours (float) into a string with format '%H:%M' """
    minutes = int(round(hours * 60))
    return "%02d:%02d" % divmod(minutes, 60)

class HrPayrollExtrahours(models.Model):
    _name = 'hr.payslip.extrahours'
    _description = 'Horas Extra Payslip'

    type_id = fields.Many2one('hr.payroll.extrahours.type', 'Tipo', index=True)
    valor = fields.Float("Valor Unitario", readonly=True)
    cantidad = fields.Float("Cantidad", readonly=True)
    total = fields.Float("Total", readonly=True)
    payslip_id = fields.Many2one('hr.payslip', 'Payslip', required=True, ondelete='cascade', index=True)

class HrPayrollExtrahoursType(models.Model):
    _name = 'hr.payroll.extrahours.type'
    _description = 'Tipo de Horas Extra'

    rules_account_ids = fields.One2many('hr.concept.structure.account', 'extra_hour_type_id', 'Estructura de Cuentas')
    horario = fields.One2many('hr.payroll.extrahours.type.time', 'hr_payroll_extrahours_type_id', 'Horario')
    multiplicador = fields.Float('Factor', required=True, digits='Payroll Rate')
    contract_types = fields.Many2many('hr.contract.type', 'extra_type_contract_type', 'extra_type_id', 'contract_type_id', 'Contratos que aplican')
    name = fields.Char('Nombre', size=64, required=True)
    code = fields.Char('Codigo', size=64, required=True)
    descripcion = fields.Text('Descripcion')
    python_code = fields.Text('Codigo Python', required=True, 
        default="""
        # Available variables:
        # extra: hr.payslip.extrahours object
        result = extra.contract_id.wage * extra.type_id.multiplicador / 30 / 8""")
    partner_type = fields.Selection(PARTNER_TYPE, 'Tipo de tercero')
    concept_category = fields.Selection(CATEGORIES, 'Categoria de concepto', required=True)
    skip_payment = fields.Boolean('Omitir calculo en nomina')

class HrPayrollExtrahoursTypeTime(models.Model):
    _name = 'hr.payroll.extrahours.type.time'
    _description = 'Horario Tipo de Horas Extra'

    hr_payroll_extrahours_type_id = fields.Many2one('hr.payroll.extrahours.type', 'Tipo de Horas Extra')
    hour_from = fields.Float('Desde', required=True, help="Start time of working")
    hour_to = fields.Float("Hasta", required=True)
    diasemana = fields.Selection([
        ('0', 'Lunes'), 
        ('1', 'Martes'), 
        ('2', 'Miercoles'), 
        ('3', 'Jueves'), 
        ('4', 'Viernes'),
        ('5', 'Sabado'), 
        ('6', 'Domingo'),
    ], 'Dia de la Semana', required=True)

#guarda las horas extra del empleado
class HrPayrollExtrahours(models.Model):
    _name = "hr.payroll.extrahours"
    _description = "Horas Extra"
    _inherit = ['mail.thread', 'ir.needaction_mixin']

    @api.model
    def _employee_get(self):
        employee_ids = self.env['hr.employee'].search([('user_id', '=', self._uid)])
        if employee_ids:
            return employee_ids[0]
        else:
            raise ValidationError("Su usuario no está vinculado a ningún empleado")

    @api.depends('employee_id', 'date_start')
    def _get_contract(self):
        for extra in self:
            extra.contract_id = self.env['hr.employee'].get_contract(extra.employee_id, extra.date_start)

    @api.depends('duracion', 'contract_id', 'type_id')
    def _compute_price(self):
        for extra in self:
            extra.total = extra.duracion * extra.contract_id.wage * extra.type_id.multiplicador / 30 / 8

    @api.constrains('date_start', 'date_end')
    def check_date_end(self):
        for horaextra in self:
            if horaextra.date_start >= horaextra.date_end:
                raise ValidationError("La fecha de inicio debe ser anterior a la fecha final")

    @api.constrains('duracion')
    def check_duracion(self):
        for horaextra in self:
            if horaextra.duracion <= 0:
                raise ValidationError("La duración debe ser mayor a 0")

    # Other methods...

    _name = "hr.payroll.extrahours"
    _description = "Horas Extra"
    _inherit = ['mail.thread', 'ir.needaction_mixin']

    payslip_id = fields.Many2one('hr.payslip', 'Pagado en nómina', readonly=True)
    moneda_local = fields.Many2one('res.currency', string="Moneda Local", related='company_id.currency_id', readonly=True, store=True)
    date_start = fields.Datetime('Comienza', required=True, readonly=True)
    date_end = fields.Datetime('Finaliza', help="llene solo la duración o la fecha final", readonly=True)
    approve_date = fields.Date('Fecha de aprobación', help="Fecha en la que se aprobó la hora extra, dejela vacia para que se llene automáticamente", readonly=True)
    duracion = fields.Float("Duración", help="llene solo la duración o fecha final", readonly=True)
    type_id = fields.Many2one('hr.payroll.extrahours.type', 'Tipo', required=True, readonly=True)
    employee_id = fields.Many2one('hr.employee', 'Empleado', required=True, readonly=True)
    company_id = fields.Many2one('res.company', 'Compañia', related='contract_id.company_id', readonly=True, store=True)
    contract_id = fields.Many2one('hr.contract', 'Contrato', required=True, readonly=True)
    contract_id_2 = fields.Many2one('hr.contract', 'Contrato', required=True, readonly=True)
    unit = fields.Float("Valor Unitario", digits='Account', readonly=True)
    total = fields.Float("Total", digits='Account', readonly=True)
    description = fields.Text('Descripción', readonly=True)
    name = fields.Char('Código', size=64, readonly=True)
    account_analytic_id = fields.Many2one('account.analytic.account', 'Centro de Costo')
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('confirmed', 'Confirmada'),
        ('validated', 'Validada'),
        ('refused', 'Rechazada'),
        ('cancelled', 'Cancelada'),
        ('paid', 'Pagada'),
    ], 'Estado', select=True, readonly=True, default='draft')

    _defaults = {
        'date_start': fields.Datetime.now,
        'state': 'draft',
        'employee_id': _employee_get,
    }

    @api.constrains('horario')
    def check_horario(self):
        for horaextra in self:
            print("TODO check_horario")

    @api.constrains('date_start', 'date_end')
    def check_date_end(self):
        for horaextra in self:
            if horaextra.date_start >= horaextra.date_end:
                raise ValidationError("La fecha de inicio debe ser anterior a la fecha final")

    @api.constrains('duracion')
    def check_duracion(self):
        for horaextra in self:
            if horaextra.duracion <= 0:
                raise ValidationError("La duración debe ser mayor a 0")

    @api.constrains('date_start', 'date_end')
    def _check_date(self):
        for extra in self:
            extra_ids = self.search([('date_start', '<', extra.date_end),
                                     ('date_end', '>', extra.date_start),
                                     ('employee_id', '=', extra.employee_id.id),
                                     ('id', '<>', extra.id)])
            extra_ids += self.search([('date_start', '=', extra.date_end),
                                      ('date_end', '=', extra.date_start),
                                      ('employee_id', '=', extra.employee_id.id),
                                      ('id', '<>', extra.id)])
            if extra_ids:
                raise ValidationError("No puede tener 2 horas extra que se sobrelapen para el mismo empleado!")

    @api.constrains('contract_id')
    def _check_contract(self):
        for extra in self:
            if extra.contract_id.date_end:
                raise ValidationError("No puede asignar un contrato liquidado!")

    _constraints = [
        (check_horario, 'Hay fechas que se sobrelapan dentro de este registro', ['horario']),
        (check_date_end, 'La fecha final debe ser mayor a la inicial', ['date_end']),
        (check_duracion, 'La duración debe ser mayor a 0', ['duracion']),
        (_check_date, 'No puede tener 2 horas extra que se sobrelapen para el mismo empleado!', ['date_start', 'date_end']),
        (_check_contract, 'No puede asignar un contrato liquidado!', ['contract_id']),
    ]

    
    def draft(self):
        self.write({'state': 'draft'})
        return True
    
    def confirm(self):
        self.compute_value()
        self.write({'state': 'confirmed'})
        return True
        
    def validate(self):
        for horaextra in self:
            if not horaextra.approve_date:
                horaextra.write({'approve_date': fields.Date.today()})
        self.write({'state': 'validated'})
        return True
    
    def refuse(self):
        self.write({'state': 'refused'})
        return True
    
    def done(self):
        self.write({'state': 'done'})
        return True
        
    def cancel(self):
        self.write({'state': 'cancelled'})
        return True
    
    @api.onchange('employee_id', 'date_start')
    def onchange_employee(self):
        if self.employee_id and self.date_start:
            empleado = self.employee_id
            contract_id = empleado.get_contract(self.date_start)
            contrato = self.env['hr.contract'].browse(contract_id)
            self.contract_id = contrato
            self.contract_id_2 = contrato
    
    def onchange_dates(self, cr, uid, ids, date_start, duracion=False, date_end=False,employee_id=False,type_id=False,dura2=False,context=None):
        """Returns duracion and/or end date based on values passed
        @param self: The object pointer
        @param cr: the current row, from the database cursor,
        @param uid: the current user's ID for security checks,
        @param ids: List of calendar event's IDs.
        @param date_start: Starting date
        @param duracion: duracion between start date and end date
        @param date_end: Ending Datee
        @param context: A standard dictionary for contextual values
        """
        if context is None:
            context = {}

        value = {}
        if not date_start:
            return value
        if not date_end and not duracion:
            duracion = 1.00
            value['duracion'] = duracion
        start = datetime.strptime(date_start, "%Y-%m-%d %H:%M:%S")
        if date_end and not duracion:
            end = datetime.strptime(date_end, "%Y-%m-%d %H:%M:%S")
            diff = end - start
            duracion = float(diff.days)* 24 + (float(diff.seconds) / 3600)
            value['duracion'] = round(duracion, 2)
        elif not date_end:
            end = start + timedelta(hours=duracion)
            value['date_end'] = end.strftime("%Y-%m-%d %H:%M:%S")
        elif date_end and duracion:
            # we have both, keep them synchronized:
            # set duracion based on date_end (arbitrary decision: this avoid
            # getting dates like 06:31:48 instead of 06:32:00)
            end = datetime.strptime(date_end, "%Y-%m-%d %H:%M:%S")
            diff = end - start
            duracion = float(diff.days)* 24 + (float(diff.seconds) / 3600)
            value['duracion'] = round(duracion, 2)

        return {'value': value}
        
    def unlink(self, cr, uid, ids, context=None):
        for payslip in self.browse(cr, uid, ids, context=context):
            if payslip.state not in  ['draft','cancelled']:
                raise ValidationError(_('No puede borrar una hora extra que no esta en borrador o cancelada!'))
        return super(HrPayrollExtrahours, self).unlink(cr, uid, ids, context)
    
    def write(self, vals):
        # Valores readonly
        if 'contract_id' in vals:
            vals['contract_id_2'] = vals['contract_id']

        # Agrega los followers por defecto
        if 'employee_id' in vals:
            for record in self:
                empleado = record.employee_id
                if empleado.partner_id not in record.message_follower_ids:
                    message_follower_ids = record.message_follower_ids.ids
                    message_follower_ids.append(empleado.partner_id.id)
                    vals.update({'message_follower_ids': [(6, 0, message_follower_ids)]})
                    if empleado.parent_id.partner_id not in record.message_follower_ids:
                        message_follower_ids.append(empleado.partner_id.id)
                        vals.update({'message_follower_ids': [(6, 0, message_follower_ids)]})

        # Llama al método padre
        result = super(HrPayrollExtrahours, self).write(vals)

        return result
    
    @api.model_create_multi
    def create(self, vals_list):
        IrSequence = self.env['ir.sequence']
        
        for vals in vals_list:
            # Set readonly values
            vals['contract_id_2'] = vals.get('contract_id')
            
            # Generate sequence number for each record
            sequence = IrSequence.next_by_code('payroll.extras.number')
            vals['name'] = sequence or '/'

        # Create all records at once
        results = super().create(vals_list)
        
        # Add followers for each created record
        for record in results:
            if record.employee_id:
                message_follower_ids = []
                employee = record.employee_id
                
                # Add employee as follower if not already following
                if employee.partner_id not in record.message_follower_ids:
                    message_follower_ids.append((4, employee.partner_id.id))
                    
                    # Add employee's manager as follower if exists and not already following
                    if employee.parent_id and employee.parent_id.partner_id not in record.message_follower_ids:
                        message_follower_ids.append((4, employee.parent_id.partner_id.id))
                
                if message_follower_ids:
                    record.message_follower_ids = message_follower_ids
        
        return results
    
    def compute_value(self,):
        for extra in self:
            if extra.state != 'paid':
                try:
                    localdict = {'result': 0.0, 'extra': extra}
                    eval(extra.type_id.python_code, localdict, mode='exec', nocopy=True)
                    result = localdict['result']
                    self.write({'unit': result, 'total': result * extra.duracion})
                except:
                    raise ValidationError(_('Calculo Erroneo para la hora extra (%s).') % (extra.name))
        return True
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools import float_round
from dateutil.relativedelta import relativedelta

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    is_negotiation_active = fields.Boolean(string='Iniciar Negociación', default=False)
    negotiation_line_ids = fields.One2many('sale.order.negotiation.line', 'order_id', string='Líneas de Negociación')
    negotiation_type = fields.Selection([
        ('manual', 'Manual'),
        ('biweekly', 'Quincenal'),
        ('monthly', 'Mensual')
    ], string='Tipo de Negociación', default='manual')
    negotiation_start_date = fields.Date(string='Fecha de Inicio')
    negotiation_is_fixed_date = fields.Boolean(string='Pagos en Fecha Fija')
    negotiation_fixed_day = fields.Integer(string='Día Fijo del Mes', default=1)
    negotiation_installment_count = fields.Integer(string='Número de Cuotas', default=1)
    negotiation_advance_type = fields.Selection([
        ('percentage', 'Porcentaje'),
        ('fixed', 'Monto Fijo')
    ], string='Tipo de Anticipo')
    negotiation_advance_value = fields.Float(string='Valor del Anticipo')
    negotiation_fixed_dates = fields.Char(string='Fechas Fijas de Cuotas', help='Ingrese las fechas separadas por comas (DD/MM/YYYY)')
    negotiation_payment_term = fields.Char(string='Término de Pago', compute='_compute_negotiation_payment_term', store=True)

    @api.depends('negotiation_line_ids', 'negotiation_advance_type', 'negotiation_advance_value', 'negotiation_installment_count')
    def _compute_negotiation_payment_term(self):
        for order in self:
            if not order.is_negotiation_active:
                order.negotiation_payment_term = False
                continue

            advance_line = order.negotiation_line_ids.filtered(lambda l: l.is_advance)
            regular_lines = order.negotiation_line_ids.filtered(lambda l: not l.is_advance)

            if advance_line:
                advance_amount = advance_line[0].amount
                term = f"Anticipo de {advance_amount:.2f} {order.currency_id.symbol}, "
            else:
                term = ""

            term += f"{len(regular_lines)} cuota{'s' if len(regular_lines) > 1 else ''}"
            order.negotiation_payment_term = term

    @api.onchange('negotiation_type', 'negotiation_start_date', 'negotiation_is_fixed_date', 'negotiation_fixed_day', 'amount_total', 'negotiation_installment_count', 'negotiation_advance_type', 'negotiation_advance_value', 'negotiation_fixed_dates')
    def _onchange_negotiation_params(self):
        if not self.is_negotiation_active:
            return

        self.negotiation_line_ids = [(5, 0, 0)]

        advance_amount = 0
        if self.negotiation_advance_type == 'percentage':
            advance_amount = self.amount_total * (self.negotiation_advance_value / 100)
        elif self.negotiation_advance_type == 'fixed':
            advance_amount = self.negotiation_advance_value

        remaining_amount = self.amount_total - advance_amount
        amount_per_installment = remaining_amount / (self.negotiation_installment_count or 1)
        
        # Optimización: Calcular fecha base una sola vez
        base_date = self.negotiation_start_date or fields.Date.context_today(self)

        if advance_amount > 0:
            self.negotiation_line_ids = [(0, 0, {
                'amount': advance_amount,
                'due_date': base_date,
                'is_advance': True,
            })]

        fixed_dates = []
        if self.negotiation_fixed_dates:
            fixed_dates = [fields.Date.from_string(date.strip()) for date in self.negotiation_fixed_dates.split(',')]

        for i in range(self.negotiation_installment_count):
            if fixed_dates and i < len(fixed_dates):
                due_date = fixed_dates[i]
            elif self.negotiation_type == 'biweekly':
                due_date = base_date + relativedelta(weeks=2*(i+1))
            elif self.negotiation_type == 'monthly':
                due_date = base_date + relativedelta(months=i+1)
            else:
                due_date = base_date + relativedelta(months=i+1)
            
            if self.negotiation_is_fixed_date and not fixed_dates:
                due_date = due_date.replace(day=min(self.negotiation_fixed_day, (due_date + relativedelta(day=31)).day))
            
            self.negotiation_line_ids = [(0, 0, {
                'amount': amount_per_installment,
                'due_date': due_date,
                'is_advance': False,
            })]

    @api.constrains('negotiation_line_ids', 'is_negotiation_active')
    def _check_negotiation_lines(self):
        for order in self:
            if not order.is_negotiation_active:
                continue
            total_amount = sum(line.amount for line in order.negotiation_line_ids)
            if float_round(total_amount, precision_digits=2) != float_round(order.amount_total, precision_digits=2):
                raise ValidationError(_('La suma de todas las líneas de negociación debe ser igual al monto total de la orden de venta.'))

    def _prepare_invoice(self):
        invoice_vals = super(SaleOrder, self)._prepare_invoice()
        if self.is_negotiation_active:
            invoice_vals.update({
                'is_negotiation_active': self.is_negotiation_active,
                'negotiation_type': self.negotiation_type,
                'negotiation_start_date': self.negotiation_start_date,
                'negotiation_is_fixed_date': self.negotiation_is_fixed_date,
                'negotiation_fixed_day': self.negotiation_fixed_day,
                'negotiation_installment_count': self.negotiation_installment_count,
                'negotiation_advance_type': self.negotiation_advance_type,
                'negotiation_advance_value': self.negotiation_advance_value,
                'negotiation_fixed_dates': self.negotiation_fixed_dates,
                'negotiation_line_ids': [(0, 0, {
                    'amount': line.amount,
                    'due_date': line.due_date,
                    'is_advance': line.is_advance,
                }) for line in self.negotiation_line_ids],
            })
        return invoice_vals
class SaleOrderNegotiationLine(models.Model):
    _name = "sale.order.negotiation.line"
    _description = "Línea de Negociación de Orden de Venta"
    _order = "due_date, id"

    order_id = fields.Many2one('sale.order', string='Orden de Venta', required=True, ondelete='cascade')
    currency_id = fields.Many2one('res.currency', related='order_id.currency_id')
    amount = fields.Monetary(string='Monto', currency_field='currency_id')
    due_date = fields.Date(string='Fecha de Vencimiento', required=True)
    is_advance = fields.Boolean(string='Es Pago Anticipado')
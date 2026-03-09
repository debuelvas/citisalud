from odoo import api, fields, models, _
from odoo.exceptions import UserError

class HrPayslipLine(models.Model):
    _inherit = 'hr.payslip.line'
    
    concept_id = fields.Many2one('hr.contract.concepts', string='Concepto Relacionado')
    pending_review = fields.Boolean('Pendiente Revisión', default=False,
        help='Indica que esta línea debe ser revisada en el siguiente período')
    reviewed = fields.Boolean('Revisado', default=False, 
        help='Indica que esta línea ya ha sido revisada')
    review_note = fields.Text('Nota de Revisión',
        help='Observaciones sobre la revisión realizada')
    adjustment_line_id = fields.Many2one('hr.payslip.line', 'Línea de Ajuste',
        help='Línea donde se aplicó el ajuste de esta línea')
    is_adjustment = fields.Boolean('Es Ajuste', default=False,
        help='Indica que esta línea es un ajuste de otra línea')
    adjusted_line_id = fields.Many2one('hr.payslip.line', 'Línea Ajustada',
        help='Línea original que está siendo ajustada')
    formula = fields.Text('Fórmula', 
        help='Fórmula utilizada para calcular el valor')
    adjustment_type = fields.Selection([
        ('days', 'Días trabajados'),
        ('previous_payment', 'Pago anterior'),
        ('correction', 'Corrección manual'),
        ('other', 'Otro ajuste')
    ], string='Tipo de Ajuste', default='days')
    comparison_data = fields.Text('Datos de Comparación',
        help='Información comparativa con períodos anteriores')

    def action_review(self):
        """
        Marca la línea como revisada y abre un wizard para aplicar ajustes
        """
        self.ensure_one()
        
        if self.reviewed:
            raise UserError(_('Esta línea ya ha sido revisada.'))
        
        # Abrir wizard de revisión
        return {
            'name': _('Revisar Línea'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.payslip.line.review.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_line_id': self.id,
                'default_concept_id': self.concept_id.id,
                'default_current_amount': self.total,
                'default_formula': self.formula or '',
            }
        }

    def get_comparison_data(self):
        """
        Genera datos de comparación con períodos anteriores
        
        Returns:
            dict: Datos de comparación
        """
        self.ensure_one()
        
        result = {
            'current': {
                'period': self.slip_id.name,
                'amount': self.total,
                'date_from': self.slip_id.date_from,
                'date_to': self.slip_id.date_to
            },
            'previous': {},
            'difference': 0.0,
            'percentage': 0.0
        }
        
        # Buscar líneas anteriores para el mismo concepto
        previous_lines = self.search([
            ('concept_id', '=', self.concept_id.id),
            ('slip_id.employee_id', '=', self.slip_id.employee_id.id),
            ('slip_id.date_to', '<', self.slip_id.date_from),
            ('slip_id.state', 'in', ['done', 'paid'])
        ], order='slip_id.date_to desc', limit=1)
        
        if previous_lines:
            prev_line = previous_lines[0]
            result['previous'] = {
                'period': prev_line.slip_id.name,
                'amount': prev_line.total,
                'date_from': prev_line.slip_id.date_from,
                'date_to': prev_line.slip_id.date_to,
                'line_id': prev_line.id
            }
            
            result['difference'] = self.total - prev_line.total
            if prev_line.total != 0:
                result['percentage'] = (result['difference'] / abs(prev_line.total)) * 100
        
        # Formatear datos para mostrar
        self.comparison_data = """
        {
            "current": {
                "period": "%s",
                "amount": %.2f
            },
            "previous": %s,
            "difference": %.2f,
            "percentage": %.2f
        }
        """ % (
            result['current']['period'],
            result['current']['amount'],
            result['previous'] and '{"period": "%s", "amount": %.2f}' % (
                result['previous']['period'], 
                result['previous']['amount']
            ) or '{}',
            result['difference'],
            result['percentage']
        )
        
        return result

    def generate_comparison_html(self):
        """
        Genera HTML para mostrar la comparación visual
        
        Returns:
            str: HTML formateado
        """
        data = self.get_comparison_data()
        
        # Determinar colores según diferencia
        if data['difference'] > 0:
            diff_color = '#4caf50'  # Verde para positivo
            diff_arrow = '▲'
        elif data['difference'] < 0:
            diff_color = '#f44336'  # Rojo para negativo
            diff_arrow = '▼'
        else:
            diff_color = '#757575'  # Gris para sin cambio
            diff_arrow = '●'
        
        # Generar HTML
        html = """
        <div style="font-family: 'Segoe UI', Tahoma, sans-serif; max-width: 300px;">
            <div style="padding: 10px; background-color: #f5f5f5; border-radius: 8px;">
                <div style="margin-bottom: 8px; color: #424242; font-weight: bold; font-size: 14px;">
                    Total Gross Comparison
                </div>
                
                <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                    <div style="color: #757575; font-size: 12px;">Last period</div>
                    <div style="font-weight: bold; font-size: 13px;">
                        {previous_amount}
                    </div>
                </div>
                
                <div style="display: flex; justify-content: space-between; margin-bottom: 4px; padding: 4px 0; border-bottom: 1px solid #e0e0e0; border-top: 1px solid #e0e0e0;">
                    <div></div>
                    <div style="color: {diff_color}; font-size: 13px;">
                        {diff_arrow} {difference}
                    </div>
                </div>
                
                <div style="display: flex; justify-content: space-between;">
                    <div style="color: #757575; font-size: 12px;">Current Period</div>
                    <div style="font-weight: bold; font-size: 13px;">
                        {current_amount} {currency}
                    </div>
                </div>
            </div>
        </div>
        """.format(
            previous_amount="{:,.2f}".format(data['previous'].get('amount', 0)) if data['previous'] else "-",
            current_amount="{:,.2f}".format(data['current']['amount']),
            difference="{:,.2f}".format(abs(data['difference'])),
            diff_arrow=diff_arrow,
            diff_color=diff_color,
            currency=self.slip_id.currency_id.symbol if hasattr(self.slip_id, 'currency_id') else 'USD'
        )
        
        return html


class HrPayslipLineReviewWizard(models.TransientModel):
    _name = 'hr.payslip.line.review.wizard'
    _description = 'Asistente para revisar líneas de nómina'
    
    line_id = fields.Many2one('hr.payslip.line', 'Línea a Revisar', required=True)
    concept_id = fields.Many2one('hr.contract.concepts', 'Concepto', required=True)
    current_amount = fields.Float('Monto Actual', readonly=True)
    adjustment_amount = fields.Float('Monto de Ajuste', required=True, default=0.0)
    adjustment_type = fields.Selection([
        ('days', 'Días trabajados'),
        ('previous_payment', 'Pago anterior'),
        ('correction', 'Corrección manual'),
        ('other', 'Otro ajuste')
    ], string='Tipo de Ajuste', default='days', required=True)
    note = fields.Text('Nota de Ajuste')
    formula = fields.Text('Fórmula de Cálculo', readonly=True)
    apply_in_next_period = fields.Boolean('Aplicar en siguiente período', default=True,
        help='Si está marcado, el ajuste se aplicará en la siguiente nómina')
    include_in_totals = fields.Boolean('Incluir en totales', default=True,
        help='Si está marcado, el ajuste se incluirá en los totales de la nómina')
    
    def action_apply_adjustment(self):
        """
        Aplica el ajuste a la línea de nómina
        """
        self.ensure_one()
        
        # Marcar línea como revisada
        self.line_id.write({
            'reviewed': True,
            'review_note': self.note or 'Ajustado: ' + self.adjustment_type
        })
        
        # Si no hay ajuste o no se debe aplicar, terminar
        if self.adjustment_amount == 0 or not self.apply_in_next_period:
            return {'type': 'ir.actions.act_window_close'}
        
        # Buscar nómina activa para aplicar ajuste
        next_payslip = self.env['hr.payslip'].search([
            ('employee_id', '=', self.line_id.slip_id.employee_id.id),
            ('state', '=', 'draft'),
            ('date_from', '>', self.line_id.slip_id.date_to)
        ], order='date_from asc', limit=1)
        
        if not next_payslip:
            # Crear una entrada para aplicar cuando se cree la siguiente nómina
            self.env['hr.payslip.adjustment.pending'].create({
                'employee_id': self.line_id.slip_id.employee_id.id,
                'concept_id': self.concept_id.id,
                'original_line_id': self.line_id.id,
                'amount': self.adjustment_amount,
                'adjustment_type': self.adjustment_type,
                'note': self.note,
                'include_in_totals': self.include_in_totals
            })
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Ajuste pendiente'),
                    'message': _('El ajuste se aplicará cuando se cree la siguiente nómina para este empleado.'),
                    'sticky': False,
                    'type': 'warning'
                }
            }
        
        # Crear línea de ajuste en la siguiente nómina
        adjustment_line = self.env['hr.payslip.line'].create({
            'slip_id': next_payslip.id,
            'salary_rule_id': self.line_id.salary_rule_id.id,
            'contract_id': self.line_id.contract_id.id,
            'employee_id': self.line_id.employee_id.id,
            'concept_id': self.concept_id.id,
            'name': 'Ajuste: ' + self.line_id.name,
            'code': self.line_id.code + '_ADJ',
            'amount': self.adjustment_amount,
            'total': self.adjustment_amount,
            'is_adjustment': True,
            'adjusted_line_id': self.line_id.id,
            'adjustment_type': self.adjustment_type,
            'note': self.note
        })
        
        # Actualizar línea original con referencia al ajuste
        self.line_id.write({
            'adjustment_line_id': adjustment_line.id
        })
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Ajuste aplicado'),
                'message': _('El ajuste se ha aplicado correctamente en la nómina %s') % next_payslip.name,
                'sticky': False,
                'type': 'success'
            }
        }


class HrPayslipAdjustmentPending(models.Model):
    _name = 'hr.payslip.adjustment.pending'
    _description = 'Ajustes Pendientes de Aplicar'
    
    employee_id = fields.Many2one('hr.employee', 'Empleado', required=True)
    concept_id = fields.Many2one('hr.contract.concepts', 'Concepto', required=True)
    original_line_id = fields.Many2one('hr.payslip.line', 'Línea Original')
    amount = fields.Float('Monto de Ajuste', required=True)
    adjustment_type = fields.Selection([
        ('days', 'Días trabajados'),
        ('previous_payment', 'Pago anterior'),
        ('correction', 'Corrección manual'),
        ('other', 'Otro ajuste')
    ], string='Tipo de Ajuste', default='days', required=True)
    note = fields.Text('Nota de Ajuste')
    applied = fields.Boolean('Aplicado', default=False)
    applied_line_id = fields.Many2one('hr.payslip.line', 'Línea Aplicada')
    include_in_totals = fields.Boolean('Incluir en totales', default=True)
    create_date = fields.Datetime('Fecha de Creación', readonly=True)

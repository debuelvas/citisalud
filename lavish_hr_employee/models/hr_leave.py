from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_is_zero
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import math
import logging
import pytz

_logger = logging.getLogger(__name__)
UTC = pytz.UTC


    

class HrWorkEntryType(models.Model):    
    _inherit = "hr.work.entry.type"
    
    deduct_deductions = fields.Selection([('all', 'Todas las deducciones'),
                                          ('law', 'Solo las deducciones de ley')],'Tener en cuenta al descontar', default='all')    #Vacaciones
    not_contribution_base = fields.Boolean(string='No es base de aportes',help='Este tipo de ausencia no es base para seguridad social')
    short_name = fields.Char(string='Nombre corto/reportes')
class hr_leave_type(models.Model):
    _inherit = 'hr.leave.type'
    code= fields.Char('Codigo')
    is_vacation = fields.Boolean('Tipo de ausencia para vacaciones disfrutadas')
    is_vacation_money = fields.Boolean('Vacaciones disfrutadas En Dinero')
    #Validación
    obligatory_attachment  = fields.Boolean('Obligar adjunto')
    #Configuración de la EPS/ARL
    num_days_no_assume = fields.Integer('Número de días que no asume')
    recognizing_factor_eps_arl = fields.Float('Factor que reconoce la EPS/ARL', digits=(25,5))
    periods_calculations_ibl = fields.Integer('Periodos para cálculo de IBL')
    eps_arl_input_id = fields.Many2one('hr.salary.rule', 'Regla de la incapacidad')
    #Configuración de la Empresa
    recognizing_factor_company = fields.Float('Factor que reconoce la empresa', digits=(25,5))
    periods_calculations_ibl_company = fields.Integer('Periodos para cálculo de IBL Empresa')
    company_input_id = fields.Many2one('hr.salary.rule', 'Regla de la incapacidad empresa')
    unpaid_absences = fields.Boolean('Ausencia no remunerada')
    discounting_bonus_days = fields.Boolean('Descontar en Prima')
    evaluates_day_off = fields.Boolean('Evalúa festivos')
    apply_publicholiday = fields.Boolean('Aplica festivos')
    apply_publicholiday_pay_days = fields.Boolean('Aplica Festivos en dias nomina')
    sub_wd = fields.Boolean('Resta en dias Trabajados', default=True)
    sub_not_aux = fields.Boolean('No Resta en dias Trabajados para Aux. Transporte')
    apply_day_31 = fields.Boolean(string='Aplica día 31')
    group_leave = fields.Boolean(string='Agrupar ausencias')
    discount_rest_day = fields.Boolean(string='Descontar día de descanso')
    published_portal = fields.Boolean(string='Permitir uso en portal de autogestión')
    type_of_entity_association = fields.Many2one('hr.contribution.register', 'Tipo de entidad asociada')
    VALUES = [
        ('sln', 'Suspensión temporal del contrato de trabajo'),
        ('ige', 'Incapacidad EPS'),
        ('irl', 'Incapacidad por accidente de trabajo o Enfermedad laboral'),
        ('lma', 'Licencia de Maternidad'),
        ('lpa', 'Licencia de Paternidad'),
        ('vco', 'Vacaciones Compensadas (Dinero)'),
        ('vdi', 'Vacaciones Disfrutadas'),
        ('vre', 'Vacaciones por Retiro'),
        ('lr', 'Licencia remunerada'),
        ('lnr', 'Licencia no Remunerada'),
        ('lt', 'Licencia de Luto'),
        ('p', 'Permisos no remunerados D/H (No se envia en pila)'),
    ]
    VALORES = [
        ('IBC', 'IBC Mes Anterior'),
        ('YEAR', 'Promedio Año Anterior'),
        ('WAGE', 'Sueldo Actual'),
        ('MIN', 'Parametros minimos de ley'),
    ]
    novelty = fields.Selection(
      string="Tipo de Ausencia (PILA)",
      selection=VALUES,)
    liquidacion_value = fields.Selection(
      string="Tipo de liquidacion de valores",
      selection=VALORES, default='WAGE')

    rango_adicionales_enfermedad = fields.Boolean(
        string='Mostrar Rango Adicionales Enfermedad',
        help='Si se activa, se mostrarán las opciones de porcentaje para rangos adicionales de enfermedad.'
    )
    
    gi_b2 = fields.Float(
        string='Porcentaje a reconocer por enfermedad de 1 y 2 días',
        help='Porcentaje del salario que se reconoce para enfermedades de 1 a 2 días.', default=100
    )
    gi_b90 = fields.Float(
        string='Porcentaje a reconocer por enfermedad de 3 a 90 días',
        help='Porcentaje del salario que se reconoce para enfermedades de 3 a 90 días.', default=66.67
    )
    gi_b180 = fields.Float(
        string='Porcentaje a reconocer por enfermedad de 91 a 180 días',
        help='Porcentaje del salario que se reconoce para enfermedades de 91 a 180 días.',default=50
    )
    gi_a180 = fields.Float(
        string='Porcentaje a reconocer por enfermedad de más de 180 días',
        help='Porcentaje del salario que se reconoce para enfermedades de más de 180 días.', default=50
    )
    gi_b180_eps_arl_input_id = fields.Many2one('hr.salary.rule', 'Regla de la incapacidad 91 a 180 días')
    gi_a180_eps_arl_input_id = fields.Many2one('hr.salary.rule', 'Regla de la incapacidad más de 180 días')
    completar_salario = fields.Boolean('Completar salario')
    allow_interruption = fields.Boolean('Permitir interrupción', default=False)

    @api.model
    def get_rate_concept_id(self, sequence):
        def check_rule(rule_field, rule_name):
            if not rule_field:
                raise UserError(f"Regla no configurada: {rule_name}")
            return rule_field.id

        if self.novelty not in ['ige', 'irl']:
            return 1, check_rule(self.eps_arl_input_id, "EPS/ARL")

        if self.rango_adicionales_enfermedad:
            if sequence <= self.num_days_no_assume:
                if self.gi_b2 == 0:
                    raise UserError("No se pudo determinar la regla aplicable para la secuencia dada.")
                else:
                    return self.gi_b2 / 100, check_rule(self.company_input_id, "Compañía (primeros días)")
            elif self.num_days_no_assume < sequence <= 90:
                return self.gi_b90 / 100, check_rule(self.eps_arl_input_id, "EPS/ARL (hasta 90 días)")
            elif 91 <= sequence <= 180:
                return self.gi_b180 / 100, check_rule(self.gi_b180_eps_arl_input_id, "EPS/ARL (91-180 días)")
            elif 181 <= sequence:
                return self.gi_a180 / 100, check_rule(self.gi_a180_eps_arl_input_id, "EPS/ARL (más de 180 días)")
        else:
            if sequence <= self.num_days_no_assume:
                return self.recognizing_factor_company, check_rule(self.company_input_id, "Compañía")
            else:
                return self.recognizing_factor_eps_arl, check_rule(self.eps_arl_input_id, "EPS/ARL")

        raise UserError("No se pudo determinar la regla aplicable para la secuencia dada.")

    _sql_constraints = [('hr_leave_type_code_uniq', 'unique(code)',
                         'Ya existe este código de nómina, por favor verficar.')]
    

    
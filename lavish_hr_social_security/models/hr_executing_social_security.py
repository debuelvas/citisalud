from logging import exception
from odoo import models, fields, api, _, SUPERUSER_ID
from odoo.exceptions import UserError, ValidationError

TYPE_WAGE = [
   ('X', 'Integral'),
   ('F', 'Fijo'), 
   ('V', 'Variable'),
   (' ', 'Aprendiz')
]

class HrExecutingSocialSecurityLine(models.Model):
    _name = 'hr.executing.social.security'
    _description = 'Ejecución de seguridad social'
    _order = 'first_name,employee_id'
    # Campos de registro
    type_of_register = fields.Integer("Tipo de registro", default=2)
    sequence = fields.Integer("Secuencia", readonly=True)
    main = fields.Boolean('Linea principal')
    compute = fields.Html('COMPUTE', readonly=True)
    # Información básica cotizante
    document_type_contributor = fields.Char('Tipo documento cotizante', readonly=True)
    document_contributor = fields.Char('Documento cotizante', readonly=True)
    type_contributor = fields.Char('Tipo cotizante', readonly=True) 
    subtype_contributor = fields.Char('Subtipo cotizante', readonly=True)
    foreign = fields.Char('Extranjero', readonly=True)
    colombian_abroad = fields.Char('Colombiano exterior', readonly=True)

    # Ubicación
    department = fields.Char('Departamento', readonly=True)
    municipality_city = fields.Char('Municipio/Ciudad', readonly=True)

    # Información personal
    first_last_name = fields.Char('Primer apellido', readonly=True)
    second_last_name = fields.Char('Segundo apellido', readonly=True) 
    first_name = fields.Char('Primer nombre', readonly=True)
    second_name = fields.Char('Segundo nombre', readonly=True)

    # Días cotización 
    pens_days = fields.Integer('Días cotizados pensión')
    eps_days = fields.Integer('Días cotizados EPS')
    arl_days = fields.Integer('Días cotizados ARL')
    ccf_days = fields.Integer('Días cotizados CCF')

    # IBC y cotización
    ups = fields.Float('Total UPS')
    eps_cot = fields.Float('Cotización EPS')

    # Salario
    wage_type = fields.Selection(TYPE_WAGE, string='Tipo de salario')

    # Códigos entidades
    eps_code = fields.Char('Código EPS', readonly=True)
    eps_transfer = fields.Char('EPS a trasladar', readonly=True)
    afp_code = fields.Char('Código AFP', readonly=True)
    afp_transfer = fields.Char('AFP a trasladar', readonly=True) 
    ccf_code = fields.Char('Código CCF', readonly=True)
    arl_code = fields.Char('Código ARL', readonly=True)

    # Valores UPC
    value_upc = fields.Integer('Valor UPC', readonly=True)
    document_type_upc = fields.Char('Tipo documento UPC', readonly=True)
    document_upc = fields.Char('Número documento UPC', readonly=True)

    # Novedades
    ige = fields.Boolean('IGE', help='Incapacidad general')
    irl = fields.Float('IRL', help='Días incapacidad riesgo laboral')
    ing = fields.Selection(string='Ingreso', selection=[('X', 'X'), ('R', 'R'), ('C', 'C'), (' ', ' ')])
    ret = fields.Selection(string='Retiro', selection=[('X', 'X'), ('R', 'R'), ('C', 'C'), ('P', 'P'), (' ', ' ')])
    tde = fields.Boolean(default=False, string='Traslado desde EPS')
    tae = fields.Boolean(default=False, string='Traslado a EPS')
    tdp = fields.Boolean(default=False, string='Traslado desde fondo de pensiones')
    tap = fields.Boolean(default=False, string='Traslado a fondo de pensiones')
    vsp = fields.Boolean(default=False, string='Variación permanente de salario')
    fixes = fields.Selection(string='Correcciones', selection=[('A', 'A'), ('C', 'C'), (' ', ' ')])
    vst = fields.Boolean(default=False, string='Variación transitoria de salario')
    sln = fields.Boolean(default=False, string='Licencia no remunerada')
    lma = fields.Boolean(default=False, string='Licencia de maternidad/paternidad')
    vac_lr = fields.Selection(string='Vacaciones-Licencia Remunerada', selection=[('X', 'X'), ('L', 'L'), (' ', ' ')])
    vct = fields.Boolean(default=False, string='Variación de centros de trabajo')
    # Campos relacionales principales
    executing_social_security_id = fields.Many2one('hr.payroll.social.security', 'Ejecución de seguridad social', required=True, ondelete='cascade')
    employee_id = fields.Many2one('hr.employee', 'Empleado', required=True)
    branch_id = fields.Many2one('lavish.res.branch', 'Sucursal')
    contract_id = fields.Many2one('hr.contract', 'Contrato', required=True)
    analytic_account_id = fields.Many2one('account.analytic.account', string='Cuenta analítica')
    payslip_ids = fields.Many2many('hr.payslip', 'hr_ss_line_payslip_rel', 'line_id', 'payslip_id', string='Nóminas base')

    # Días y horas
    nNumeroHorasLaboradas = fields.Integer('Horas laboradas')
    nDiasLiquidados = fields.Integer('Días liquidados')
    nDiasIncapacidadEPS = fields.Integer('Días incapacidad EPS')
    nDiasLicencia = fields.Integer('Días licencia')
    nDiasLicenciaRenumerada = fields.Integer('Días licencia remunerada')
    nDiasMaternidad = fields.Integer('Días maternidad')
    nDiasVacaciones = fields.Integer('Días vacaciónes')
    nDiasIncapacidadARP = fields.Integer('Días incapacidad ARP')

    # Novedades
    nIngreso = fields.Boolean('Ingreso')
    nRetiro = fields.Boolean('Retiro')
    nSueldo = fields.Float('Sueldo')
    global_ibc = fields.Float('IBC Global')
    # Salud
    TerceroEPS = fields.Many2one('hr.employee.entities', 'Tercero EPS')
    nValorBaseSalud = fields.Float('Valor base salud')
    nPorcAporteSaludEmpleado = fields.Float('Porc. Aporte salud empleados')
    nValorSaludEmpleado = fields.Float('Valor salud empleado')
    nValorSaludEmpleadoNomina = fields.Float('Valor salud empleado nómina')
    nPorcAporteSaludEmpresa = fields.Float('Porc. Aporte salud empresa')
    nValorSaludEmpresa = fields.Float('Valor salud empresa')
    nValorSaludTotal = fields.Float('Valor salud total')
    nDiferenciaSalud = fields.Float('Diferencia salud')

    # Pensión
    TerceroPension = fields.Many2one('hr.employee.entities', 'Tercero pensión')
    nValorBaseFondoPension = fields.Float('Valor base fondo de pensión')
    nPorcAportePensionEmpleado = fields.Float('Porc. Aporte pensión empleado')
    nValorPensionEmpleado = fields.Float('Valor pensión empleado')
    nValorPensionEmpleadoNomina = fields.Float('Valor pensión empleado nómina')
    nPorcAportePensionEmpresa = fields.Float('Porc. Aporte pensión empresa')
    nValorPensionEmpresa = fields.Float('Valor pensión empresa')
    nValorPensionTotal = fields.Float('Valor pensión total')
    nDiferenciaPension = fields.Float('Diferencia pensión')

    # Fondos
    cAVP = fields.Boolean('Tiene AVP')
    nAporteVoluntarioPension = fields.Float('Valor AVP')
    TerceroFondoSolidaridad = fields.Many2one('hr.employee.entities', 'Tercero fondo solidaridad')
    nPorcFondoSolidaridad = fields.Float('Porc. Fondo solidaridad')
    nValorFondoSolidaridad = fields.Float('Valor fondo solidaridad')
    nValorFondoSubsistencia = fields.Float('Valor fondo subsistencia')

    # ARL
    TerceroARP = fields.Many2one('hr.employee.entities', 'Tercero ARP')
    nValorBaseARP = fields.Float('Valor base ARP')
    nPorcAporteARP = fields.Float('Porc. Aporte ARP', digits=(30, 5), readonly=True)
    nValorARP = fields.Float('Valor ARP')

    # Parafiscales
    cExonerado1607 = fields.Boolean('Exonerado ley 1607')
    TerceroCajaCom = fields.Many2one('hr.employee.entities', 'Tercero caja compensación')
    nValorBaseCajaCom = fields.Float('Valor base caja com')
    nPorcAporteCajaCom = fields.Float('Porc. Aporte caja com')
    nValorCajaCom = fields.Float('Valor caja com')
    TerceroSENA = fields.Many2one('hr.employee.entities', 'Tercero SENA')
    nValorBaseSENA = fields.Float('Valor base SENA')
    nPorcAporteSENA = fields.Float('Porc. Aporte SENA')
    nValorSENA = fields.Float('Valor SENA')
    TerceroICBF = fields.Many2one('hr.employee.entities', 'Tercero ICBF')
    nValorBaseICBF = fields.Float('Valor base ICBF')
    nPorcAporteICBF = fields.Float('Porc. Aporte ICBF')
    nValorICBF = fields.Float('Valor ICBF')

    # Ausencias
    leave_id = fields.Many2one('hr.leave', 'Ausencia')
    dFechaInicioSLN = fields.Date('Fecha Inicio SLN')
    dFechaFinSLN = fields.Date('Fecha Fin SLN')
    dFechaInicioIGE = fields.Date('Fecha Inicio IGE')
    dFechaFinIGE = fields.Date('Fecha Fin IGE')
    dFechaInicioLMA = fields.Date('Fecha Inicio LMA')
    dFechaFinLMA = fields.Date('Fecha Fin LMA')
    dFechaInicioVACLR = fields.Date('Fecha Inicio VACLR')
    dFechaFinVACLR = fields.Date('Fecha Fin VACLR')
    dFechaInicioVCT = fields.Date('Fecha Inicio VCT')
    dFechaFinVCT = fields.Date('Fecha Fin VCT')
    dFechaInicioIRL = fields.Date('Fecha Inicio IRL')
    dFechaFinIRL = fields.Date('Fecha Fin IRL')
    k_start = fields.Date(string='Fecha de ingreso')
    k_end = fields.Date(string='Fecha de retiro')
    vsp_start = fields.Date(string='Fecha de inicio de VSP')
    def executing_social_security_employee(self):
        self.ensure_one()
        if self.executing_social_security_id.state != 'accounting':
            self.executing_social_security_id.executing_social_security(self.employee_id.id)
            return {
                'type': 'ir.actions.client',
                'tag': 'reload',
            }
        else:
            raise ValidationError('No puede recalcular una seguridad en estado contabilizado, por favor verificar.')


    @api.depends('sequence')
    def _compute_line_sequence(self):
        number = 1
        for record in self.executing_social_security_id.executing_social_security_ids:
            record.sequence = number
            number += 1


class hr_errors_social_security(models.Model):
    _name = 'hr.errors.social.security'
    _description = 'Ejecución de seguridad social errores'

    executing_social_security_id =  fields.Many2one('hr.payroll.social.security', 'Ejecución de seguridad social', required=True, ondelete='cascade')
    employee_id = fields.Many2one('hr.employee', 'Empleado',required=True)
    branch_id =  fields.Many2one('lavish.res.branch', 'Sucursal')
    description = fields.Text('Observación')
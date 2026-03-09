# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from datetime import datetime, timedelta, date
from odoo.exceptions import UserError, ValidationError
import time
default_html_report_income_and_withholdings = '''
<table class="table border_report col-12" style="font-size: x-small;margin: 0px;">
    <tr>
        <td colspan="2"></td>
        <td colspan="8">
            <b>
                <center>
                    <h5>Certificado de Ingresos y Retenciones por Rentas de Trabajo y Pensiones
                        año
                        Agravable {year}
                    </h5>
                </center>
            </b>
        </td>
        <td colspan="2"></td>
    </tr>
    <tr>
        <td colspan="7">
            <br/>
            <center>
                <b>Antes de diligenciar este formulario lea
                    cuidadosamente
                    las instrucciones
                </b>
            </center>
        </td>
        <td colspan="5">4. Número de formulario
            <br/>
            $_val4_$
        </td>
    </tr>
    <tr>
        <td class="th_report rotate" rowspan="2">
            <div style="padding-right: 60px !important;">
                <b>Retenedor</b>
            </div>
        </td>
        <td colspan="2">
            5. Número de Identificación Tributaria (NIT)
            <br/>
            $_val5_$
        </td>
        <td class="width_items" colspan="1">6. D.V
            <br/>
            $_val6_$
        </td>

        <td colspan="2">7. Primer Apellido
            <br/>
            $_val7_$
        </td>

        <td colspan="2">8. Segundo Apellido
            <br/>
            $_val8_$
        </td>
        <td colspan="2">9. Primer Nombre
            <br/>
            $_val9_$
        </td>
        <td colspan="2">10. Otros Nombres
            <br/>
            $_val10_$
        </td>
    </tr>
    <tr>
        <td colspan="11">11. Razón Social
            <br/>
            $_val11_$
        </td>
    </tr>
    <tr>
        <td class="rotate">
            <div style="padding-right: 30px !important;">
                <b>Empleado</b>
            </div>
        </td>
        <td colspan="1">24. Tipo de Documento
            <br/>
            $_val24_$
        </td>
        <td colspan="3">25. Número de Identificación
            <br/>
            $_val25_$
        </td>
        <td colspan="2">26. Primer Apellido
            <br/>
            $_val26_$
        </td>
        <td colspan="2">27. Segundo Apellido
            <br/>
            $_val27_$
        </td>
        <td colspan="2">28. Primer Nombre
            <br/>
            $_val28_$
        </td>
        <td colspan="2">29. Otros Nombres
            <br/>
            $_val29_$
        </td>
    </tr>
    <tr>
        <td colspan="5">Período de Certificación
            <br/>
            30. DE $_val30_$ 31. A $_val31_$
        </td>
        <td colspan="2">32. Fecha de expedición
            <br/>
            $_val32_$
        </td>
        <td colspan="3">33. Lugar donde se practicó la retención
            <br/>
            $_val33_$
        </td>
        <td  colspan="1">34. Cód.Dpto
            <br/>
            $_val34_$
        </td>
        <td colspan="1">35. Cód.Ciudad/Municipio
            <br/>
            $_val35_$
        </td>
    </tr>
</table>
<table class="table table-striped border_report col-12" style="font-size: x-small;margin: 0px;">
    <tr>
        <td colspan="9">
            <center>
                <b>Concepto de los Ingresos</b>
            </center>
        </td>
        <td colspan="1" class="width_items">
            <b></b>
        </td>
        <td colspan="2" class="width_values">
            <center>
                <b>Valor</b>
            </center>
        </td>
    </tr>
    <tr>
        <td colspan="9">Pagos por salarios o emolumentos eclesiásticos</td>
        <td colspan="1" class="width_items">36</td>
        <td colspan="2" class="width_values">$_val36_$</td>
    </tr>
    <tr>
        <td colspan="9">Pagos realizados con bonos electrónicos o de papel de servicio, cheques,
            tarjetas,
            vales, etc.
        </td>
        <td colspan="1" class="width_items">37</td>
        <td colspan="2" class="width_values">$_val37_$</td>
    </tr>
    <tr>
        <td colspan="9">Pagos por honorarios</td>
        <td colspan="1" class="width_items">38</td>
        <td colspan="2" class="width_values">$_val38_$</td>
    </tr>
    <tr>
        <td colspan="9">Pagos por servicios</td>
        <td colspan="1" class="width_items">39</td>
        <td colspan="2" class="width_values">$_val39_$</td>
    </tr>
    <tr>
        <td colspan="9">Pagos por comisiones</td>
        <td colspan="1" class="width_items">40</td>
        <td colspan="2" class="width_values">$_val40_$</td>
    </tr>
    <tr>
        <td colspan="9">Pagos por prestaciones sociales</td>
        <td colspan="1" class="width_items">41</td>
        <td colspan="2" class="width_values">$_val41_$</td>
    </tr>
    <tr>
        <td colspan="9">Pagos por viáticos</td>
        <td colspan="1" class="width_items">42</td>
        <td colspan="2" class="width_values">$_val42_$</td>
    </tr>
    <tr>
        <td colspan="9">Pagos por gastos de representación</td>
        <td colspan="1" class="width_items">43</td>
        <td colspan="2" class="width_values">$_val43_$</td>
    </tr>
    <tr>
        <td colspan="9">Pagos por compensaciones por el trabajo asociado cooperativo</td>
        <td colspan="1" class="width_items">44</td>
        <td colspan="2" class="width_values">$_val44_$</td>
    </tr>
    <tr>
        <td colspan="9">Otros pagos</td>
        <td colspan="1" class="width_items">45</td>
        <td colspan="2" class="width_values">$_val45_$</td>
    </tr>
    <tr>
        <td colspan="9">Cesantías e intereses de cesantías efectivamente pagadas al empleado</td>
        <td colspan="1" class="width_items">46</td>
        <td colspan="2" class="width_values">$_val46_$</td>
    </tr>
    <tr>
        <td colspan="9">Cesantías consignadas al fondo de cesantias</td>
        <td colspan="1" class="width_items">47</td>
        <td colspan="2" class="width_values">$_val47_$</td>
    </tr>
    <tr>
        <td colspan="9">Pensiones de jubilación, vejez o invalidez</td>
        <td colspan="1" class="width_items">48</td>
        <td colspan="2" class="width_values">$_val48_$</td>
    </tr>
    <tr>
        <td colspan="9">Total de ingresos brutos (Sume 36 a 48)</td>
        <td colspan="1" class="width_items">49</td>
        <td colspan="2" class="width_values">$_val49_$</td>
    </tr>
    <!--Concepto de los Aportes-->
    <tr>
        <td colspan="9">
            <center>
                <b>Concepto de los Aportes</b>
            </center>
        </td>
        <td colspan="1" class="width_items">
            <b></b>
        </td>
        <td colspan="2" class="width_values">
            <center>
                <b>Valor</b>
            </center>
        </td>
    </tr>
    <tr>
        <td colspan="9">Aportes obligatorios por salud a cargo del trabajador</td>
        <td colspan="1" class="width_items">50</td>
        <td colspan="2" class="width_values">$_val50_$</td>
    </tr>
    <tr>
        <td colspan="9">Aportes obligatorios a fondos de pensiones y solidaridad pensional a
            cargo del
            trabajador
        </td>
        <td colspan="1" class="width_items">51</td>
        <td colspan="2" class="width_values">$_val51_$</td>
    </tr>
    <tr>
        <td colspan="9">Cotizaciones voluntarias al régimen de ahorro individual con solidaridad
            - RAIS
        </td>
        <td colspan="1" class="width_items">52</td>
        <td colspan="2" class="width_values">$_val52_$</td>
    </tr>
    <tr>
        <td colspan="9">Aportes voluntarios a fondos de pensiones</td>
        <td colspan="1" class="width_items">53</td>
        <td colspan="2" class="width_values">$_val53_$</td>
    </tr>
    <tr>
        <td colspan="9">Aportes a cuentas AFC</td>
        <td colspan="1" class="width_items">54</td>
        <td colspan="2" class="width_values">$_val54_$</td>
    </tr>
    <tr>
        <td colspan="9" style="background:#335E8B; color: white">Valor de la retención en la
            fuente por ingresos laborales y de pensiones
        </td>
        <td colspan="1" class="width_items">55</td>
        <td colspan="2" class="width_values">$_val55_$</td>
    </tr>
    <tr>
        <td colspan="12">Nombre del pagador o agente retenedor</td>
    </tr>
    <!--                            Datos a cargo del trabajador o pensionado-->
    <tr>
        <td colspan="12">
            <center>
                <b>Datos a cargo del trabajador o pensionado</b>
            </center>
        </td>
    </tr>
    <tr>
        <td colspan="6">
            <center>
                <b>Concepto de otros ingresos</b>
            </center>
        </td>
        <td colspan="1" class="width_items"></td>
        <td colspan="2" class="width_values">
            <center>
                <b>Valor Recibido</b>
            </center>
        </td>
        <td colspan="1" class="width_items"></td>
        <td colspan="2" class="width_values">
            <center>
                <b>Valor Retenido</b>
            </center>
        </td>
    </tr>
    <tr>
        <td colspan="6">Arrendamientos</td>
        <td colspan="1" class="width_items">56</td>
        <td colspan="2" class="width_values">$_val56_$</td>
        <td colspan="1" class="width_items">63</td>
        <td colspan="2" class="width_values">$_val63_$</td>
    </tr>
    <tr>
        <td colspan="6">Honorarios, comisiones y servicios</td>
        <td colspan="1" class="width_items">57</td>
        <td colspan="2" class="width_values">$_val57_$</td>
        <td colspan="1" class="width_items">64</td>
        <td colspan="2" class="width_values">$_val64_$</td>
    </tr>
    <tr>
        <td colspan="6">Intereses y rendimientos financieros</td>
        <td colspan="1" class="width_items">58</td>
        <td colspan="2" class="width_values">$_val58_$</td>
        <td colspan="1" class="width_items">65</td>
        <td colspan="2" class="width_values">$_val65_$</td>
    </tr>
    <tr>
        <td colspan="6">Enajenación de activos fijos</td>
        <td colspan="1" class="width_items">59</td>
        <td colspan="2" class="width_values">$_val59_$</td>
        <td colspan="1" class="width_items">66</td>
        <td colspan="2" class="width_values">$_val66_$</td>
    </tr>
    <tr>
        <td colspan="6">Loterías, rifas, apuestas y similares</td>
        <td colspan="1" class="width_items">60</td>
        <td colspan="2" class="width_values">$_val60_$</td>
        <td colspan="1" class="width_items">67</td>
        <td colspan="2" class="width_values">$_val67_$</td>
    </tr>
    <tr>
        <td colspan="6">Otros</td>
        <td colspan="1" class="width_items">61</td>
        <td colspan="2" class="width_values">$_val61_$</td>
        <td colspan="1" class="width_items">68</td>
        <td colspan="2" class="width_values">$_val68_$</td>
    </tr>
    <tr>
        <td colspan="6">Totales: (Valor recibido: Sume 57 a 61), (Valor retenido: Sume 63 a 68)</td>
        <td colspan="1" class="width_items">62</td>
        <td colspan="2" class="width_values">$_val62_$</td>
        <td colspan="1" class="width_items">69</td>
        <td colspan="2" class="width_values">$_val69_$</td>
    </tr>
    <tr>
        <td colspan="9">Total retenciones año gravable {year} (Sume 55 + 69)</td>
        <td colspan="1" class="width_items">70</td>
        <td colspan="2" class="width_values">$_val70_$</td>
    </tr>
    <!--Identificación de los bienes y derechos poseídos-->
    <tr>
        <td colspan="1" class="width_items">
            <center>
                <b>Item</b>
            </center>
        </td>
        <td colspan="9">
            <center>
                <b>71. Identificación de los bienes y derechos poseídos</b>
            </center>
        </td>
        <td colspan="2" class="width_values">
            <center>
                <b>72. Valor patrimonial</b>
            </center>
        </td>
    </tr>
    <tr>
        <td colspan="1" class="width_items">1</td>
        <td colspan="9">$_val71.1_$</td>
        <td colspan="2" class="width_values">$_val72.1_$</td>
    </tr>
    <tr>
        <td colspan="1" class="width_items">2</td>
        <td colspan="9">$_val71.2_$</td>
        <td colspan="2" class="width_values">$_val72.2_$</td>
    </tr>
    <tr>
        <td colspan="1" class="width_items">3</td>
        <td colspan="9">$_val71.3_$</td>
        <td colspan="2" class="width_values">$_val72.3_$</td>
    </tr>
    <tr>
        <td colspan="1" class="width_items">4</td>
        <td colspan="9">$_val71.4_$</td>
        <td colspan="2" class="width_values">$_val72.4_$</td>
    </tr>
    <tr>
        <td colspan="1" class="width_items">5</td>
        <td colspan="9">$_val71.5_$</td>
        <td colspan="2" class="width_values">$_val72.5_$</td>
    </tr>
    <tr>
        <td colspan="1" class="width_items">6</td>
        <td colspan="9">$_val71.6_$</td>
        <td colspan="2" class="width_values">$_val72.6_$</td>
    </tr>
    <tr>
        <td colspan="9" style="background:#335E8B; color: white">Deudas vigentes a 31 de
            diciembre de {year}
        </td>
        <td colspan="1" class="width_items">73</td>
        <td colspan="2" class="width_values">$_val73_$</td>
    </tr>
</table>
<table class="table border_report col-12" style="font-size: x-small;margin: 0px;">
    <!--Identificación del dependiente económico de acuerdo al parágrafo 2 del artículo 387 del Estatuto Tributario-->
    <tr>
        <td colspan="12">
            <center>
                <b>Identificación del dependiente económico de acuerdo al parágrafo 2 del
                    artículo
                    387 del Estatuto Tributario
                </b>
            </center>
        </td>
    </tr>
    <tr>
        <td colspan="2" class="th_report">74. Tipo documento
            <br/>
            $_val74_$
        </td>
        <td colspan="2" class="th_report">75. No. Documento
            <br/>
            $_val75_$
        </td>
        <td colspan="6" class="th_report">76. Apellidos y Nombres
            <br/>
            $_val76_$
        </td>
        <td colspan="2" class="th_report">77. Parentesco
            <br/>
            $_val77_$
        </td>
    </tr>
    <tr>
        <td colspan="8">
            Certifico que durante el año gravable {year}:
            <br/>
            1. Mi patrimonio bruto no excedió de 4.500 UVT ({uvt_4500}).
            <br/>
            2. Mis ingresos brutos fueron inferiores a 1.400 UVT ({uvt_1400}).
            <br/>
            3. No fui responsable del impuesto sobre las ventas.
            <br/>
            4. Mis consumos mediante tarjeta de crédito no excedieron la suma de 1.400 UVT
            ({uvt_1400}).
            <br/>
            5. Que el total de mis compras y consumos no superaron la suma de 1.400 UVT
            ({uvt_1400}).
            <br/>
            6. Que el valor total de mis consignaciones bancarias, depósitos o inversiones
            financieras no excedieron los 1.400 UVT ({uvt_1400}).
            <br/>
            Por lo tanto, manifiesto que no estoy obligado a presentar declaración de renta y
            complementario por el año gravable {year}
        </td>
        <td colspan="4">
            Firma del Trabajador o Pensionado
        </td>
    </tr>
</table>
<p style="font-size: x-small">
    <b>Nota:</b>
    este certificado sustituye para todos los efectos legales la declaración de Renta y
    Complementario para el trabajador o pensionado que lo firme.
    <br/>
    Para aquellos trabajadores independientes contribuyentes del impuesto unificado deberán
    presentar la declaración anual consolidada del Régimen Simple de Tributación (SIMPLE).
</p>
'''
#Tabla Parametrización Certificados ingresos y retenciones
class HrCertificateIncomeHeader(models.Model):
    _name = 'hr.certificate.income.header'
    _description = 'Configuración de Encabezado para Certificado de Ingresos y Retenciones'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name desc'

    name = fields.Char(string='Nombre', required=True, tracking=True)
    company_id = fields.Many2one('res.company', string='Compañía', default=lambda self: self.env.company, tracking=True)
    year = fields.Integer(string='Año', required=True, tracking=True)
    active = fields.Boolean(default=True)
    description = fields.Text(string='Descripción')
    
    form_number = fields.Char(string='Número de Formulario', tracking=True)
    issue_date = fields.Date(string='Fecha de Expedición', tracking=True)
    
    uvt_value = fields.Float(string='Valor UVT', required=True, tracking=True)
    patrimony_uvt = fields.Float(string='UVT Patrimonio', default=4500, tracking=True,
                               help='UVT para límite de patrimonio bruto')
    income_uvt = fields.Float(string='UVT Ingresos', default=1400, tracking=True,
                            help='UVT para límite de ingresos brutos')
    
    account_ids = fields.Many2many(
        'account.account',
        string='Cuentas Contables',
        domain="[('company_id', '=', company_id)]",
        help="Cuentas contables a considerar en el cálculo"
    )
    excluded_journal_ids = fields.Many2many(
        'account.journal',
        string='Diarios Excluidos',
        domain="[('company_id', '=', company_id)]",
        help="Diarios que se excluirán del cálculo"
    )

    line_ids = fields.One2many(
        'hr.conf.certificate.income',
        'header_id',
        string='Líneas de Configuración'
    )
    report_income_and_withholdings = fields.Html('Estructura Certificado ingresos y retenciones',default=default_html_report_income_and_withholdings)
    _sql_constraints = [
        ('unique_year_company', 
         'unique(year, company_id)', 
         'Ya existe una configuración para este año y compañía')
    ]

    @api.constrains('year')
    def _check_year(self):
        for record in self:
            if record.year < 2000 or record.year > 2100:
                raise ValidationError('El año debe estar entre 2000 y 2100')

    @api.constrains('uvt_value')
    def _check_uvt_value(self):
        for record in self:
            if record.uvt_value <= 0:
                raise ValidationError('El valor de la UVT debe ser mayor que 0')

    def name_get(self):
        result = []
        for record in self:
            name = f"Configuración Certificado {record.year} - {record.company_id.name}"
            result.append((record.id, name))
        return result

    def copy(self, default=None):
        default = dict(default or {})
        default.update({
            'name': f"{self.name} (Copia)",
            'year': self.year + 1,
        })
        return super().copy(default)

    def action_compute_values(self):
        """Acción para calcular los valores del certificado"""
        self.ensure_one()
        # Lógica para calcular valores
        pass

class HrConfCertificateIncome(models.Model):
    _name = 'hr.conf.certificate.income'
    _description = 'Líneas de Configuración para Certificado de Ingresos y Retenciones'
    _order = 'sequence'

    header_id = fields.Many2one(
        'hr.certificate.income.header',
        string='Encabezado',
        ondelete='cascade'
    )
    annual_parameters_id = fields.Many2one('hr.annual.parameters', string='Parametro Anual',  ondelete='cascade')
    sequence = fields.Integer(string='Secuencia')

    calculation = fields.Selection([
        ('info', 'Información'),
        ('sum_rule', 'Sumatoria Reglas'),
        ('sum_sequence', 'Sumatoria secuencias anteriores'),
        ('date_issue', 'Fecha expedición'),
        ('start_date_year', 'Fecha certificación inicial'),
        ('end_date_year', 'Fecha certificación final'),
        ('dependents_type_vat', 'Dependientes - Tipo documento'),
        ('dependents_vat', 'Dependientes - No. Documento'),
        ('dependents_name', 'Dependientes - Apellidos y Nombres'),
        ('dependents_type', 'Dependientes - Parentesco'),
    ], string='Tipo Cálculo', default='info')
    
    type_partner = fields.Selection([
        ('employee', 'Empleado'),
        ('company', 'Compañía')
    ], string='Origen Información')
    
    information_fields_id = fields.Many2one(
        'ir.model.fields',
        string="Información",
        domain="[('model_id.model', 'in', ['hr.employee','res.partner','hr.contract'])]"
    )
    information_fields_relation = fields.Char(
        related='information_fields_id.relation',
        string='Relación del objeto',
        store=True
    )
    related_field_id = fields.Many2one(
        'ir.model.fields',
        string='Campo Relación',
        domain="[('model_id.model', '=', information_fields_relation)]"
    )
    
    salary_rule_id = fields.Many2many('hr.salary.rule', string='Regla Salarial')
    origin_severance_pay = fields.Selection([
        ('employee', 'Empleado'),
        ('fund', 'Fondo')
    ], string='Pago cesantías')
    
    accumulated_previous_year = fields.Boolean(string='Acumulado año anterior')
    sequence_list_sum = fields.Char(string='Sum secuencias')

    # Nuevos campos para cuentas contables específicas de la línea
    account_ids = fields.Many2many(
        'account.account',
        string='Cuentas Contables',
        help="Cuentas contables específicas para esta línea"
    )
    excluded_journal_ids = fields.Many2many(
        'account.journal',
        string='Diarios Excluidos',
        help="Diarios excluidos específicos para esta línea"
    )

    _sql_constraints = [
        ('unique_sequence_header',
         'unique(header_id, sequence)',
         'Ya existe esta secuencia en el encabezado, por favor verificar')
    ]

    @api.onchange('header_id')
    def _onchange_header(self):
        if self.header_id:
            # Heredar configuración de cuentas y diarios del encabezado si están vacíos
            if not self.account_ids:
                self.account_ids = self.header_id.account_ids
            if not self.excluded_journal_ids:
                self.excluded_journal_ids = self.header_id.excluded_journal_ids




# Tabla de parametros anuales
class hr_annual_parameters(models.Model):
    _name = 'hr.annual.parameters'
    _description = 'Parámetros anuales'

    year = fields.Integer('Año', required=True)
    smmlv_monthly = fields.Float('Valor mensual SMMLV', required=True)
    smmlv_daily = fields.Float('Valor diario SMMLV', compute='_values_smmlv', store=True)
    top_four_fsp_smmlv = fields.Float('Tope 4 salarios FSP', compute='_values_smmlv', store=True)
    top_twenty_five_smmlv = fields.Float('Tope 25 salarios', compute='_values_smmlv', store=True)
    top_ten_smmlv = fields.Float('Tope 10 salarios', compute='_values_smmlv', store=True)
    transportation_assistance_monthly = fields.Float('Valor mensual Auxilio Transporte', required=True)
    transportation_assistance_daily = fields.Float('Valor diario Auxilio Transporte',
                                                   compute='_value_transportation_assistance_daily', store=True)
    top_max_transportation_assistance = fields.Float('Tope maxímo para pago', compute='_values_smmlv', store=True)
    min_integral_salary = fields.Float('Salario mínimo integral', compute='_values_smmlv', store=True)
    porc_integral_salary = fields.Integer('Porcentaje salarial', required=True)
    value_factor_integral_salary = fields.Float('Valor salarial', compute='_values_integral_salary', store=True)
    value_factor_integral_performance = fields.Float('Valor prestacional', compute='_values_integral_salary',
                                                     store=True)
    # Básicos Horas Laborales
    hours_daily = fields.Float(digits='Payroll', string='Horas diarias', compute='_compute_hours', readonly=False, required=True)
    hours_weekly = fields.Float(digits='Payroll', string='Horas semanales', compute='_compute_hours', store=True, readonly=False)
    hours_fortnightly = fields.Float(digits='Payroll', string='Horas quincenales', compute='_compute_hours', store=True, readonly=False)
    hours_monthly = fields.Float(digits='Payroll', string='Horas mensuales', store=True, readonly=False)
    # Seguridad Social
    weight_contribution_calculations = fields.Boolean('Cálculos de aportes al peso')
    # Salud
    value_porc_health_company = fields.Float('Porcentaje empresa salud', required=True)
    value_porc_health_employee = fields.Float('Porcentaje empleado salud', required=True)
    value_porc_health_total = fields.Float('Porcentaje total salud', compute='_value_porc_health_total', store=True)
    value_porc_health_employee_foreign = fields.Float('Porcentaje aporte extranjero', required=True)
    # Pension
    value_porc_pension_company = fields.Float('Porcentaje empresa pensión', required=True)
    value_porc_pension_employee = fields.Float('Porcentaje empleado pensión', required=True)
    value_porc_pension_total = fields.Float('Porcentaje total pensión', compute='_value_porc_pension_total', store=True)
    # Aportes parafiscales
    value_porc_compensation_box_company = fields.Float('Caja de compensación', required=True)
    value_porc_sena_company = fields.Float('SENA', required=True)
    value_porc_icbf_company = fields.Float('ICBF', required=True)
    # Provisiones prestaciones
    value_porc_provision_bonus = fields.Float('Prima', required=True)
    value_porc_provision_cesantias = fields.Float('Cesantías', required=True)
    value_porc_provision_intcesantias = fields.Float('Intereses Cesantías', required=True)
    value_porc_provision_vacation = fields.Float('Vacaciones', required=True)
    # Tope Ley 1395
    value_porc_statute_1395 = fields.Integer('Porcentaje (%)', required=True)
    # Tributario
    # Retención en la fuente
    value_uvt = fields.Float('Valor UVT', required=True)
    value_top_source_retention = fields.Float('Tope para el calculo de retención en la fuente', required=True)
    # Incrementos
    value_porc_increment_smlv = fields.Float('Incremento SMLV', required=True)
    value_porc_ipc = fields.Float('Porcentaje IPC', required=True)
    # Certificado Ingresos/Retencion
    taxable_year = fields.Integer(string='Año gravable')
    gross_equity = fields.Float(string='Patrimonio bruto')
    total_revenues = fields.Float(string='Ingresos totales')
    credit_card = fields.Float(string='Tarjeta de crédito')
    purchases_and_consumption = fields.Float(string='Compras y consumos')
    conf_certificate_income_ids = fields.One2many('hr.conf.certificate.income', 'annual_parameters_id',
                                                  string='Configuración de reglas salariales')
    # HTML Certificado Ingreso y retenciones
    report_income_and_withholdings = fields.Html('Estructura Certificado ingresos y retenciones',default=default_html_report_income_and_withholdings)
    #PRESTACIONES SOCIALES SECTOR PUBLICO Y DISTRITAL
    food_subsidy_amount = fields.Integer(string="Subsidio de alimentación")
    bonus_services_rendered = fields.Integer(string="Tope Bonificación por servicios prestados (B.S.P)")
    food_subsidy_tope = fields.Integer(string="Tope Subsidio de alimentación")
    percentage_public = fields.Integer(string="Porcentaje Emp. Publicos")
    company_id = fields.Many2one(
        'res.company',
        string='Compañía',
        ondelete='cascade',
        index=True
    )
    
    name = fields.Char(
        string='Nombre',
        compute='_compute_displays_name',
        store=True
    )

    simple_provisions = fields.Boolean(
        'Cálculo de provisiones simple',
        default=False,
        help="Usa método de porcentaje fijo para provisiones en lugar del consolidado"
    )
    rtf_projection = fields.Boolean(
        'Cálculo de retención proyectada en primera quincena',
        default=False,
        help="Proyecta el salario completo en primera quincena para cálculo de retención"
    )
    
    ded_round = fields.Boolean(
        'Redondeo de deducciones EPS, PEN, FSO',
        default=False,
        help="Redondea al entero más cercano las deducciones de seguridad social"
    )
    
    rtf_round = fields.Boolean(
        'Redondeo de retención en la fuente',
        default=False,
        help="Redondea la retención en la fuente al múltiplo de 1000 más cercano"
    )
    
    aux_apr_prod = fields.Boolean(
        'Auxilio de transporte a aprendices en etapa productiva',
        default=False,
        help="Otorga auxilio de transporte a aprendices en etapa productiva"
    )
    
    fragment_vac = fields.Boolean(
        'Vacaciones fragmentadas',
        default=False,
        help="Permite fragmentar vacaciones en periodos menores a 15 días"
    )
    
    prv_vac_cpt = fields.Boolean(
        'Provisión de vacaciones por conceptos',
        default=False,
        help="Calcula provisión de vacaciones por conceptos marcados como base"
    )
    
    aux_prst = fields.Boolean(
        'Incorporación de auxilio de transporte en prestaciones sin promediar',
        default=False,
        help="Incluye auxilio de transporte en prestaciones sin considerar topes"
    )
    
    aus_prev = fields.Boolean(
        'Pago de ausencias de periodos anteriores',
        default=False,
        help="Permite pagar ausencias reportadas con posterioridad al periodo"
    )
    
    positive_net = fields.Boolean(
        'Cierre de nómina solo con neto positivo',
        default=True,
        help="Impide cerrar nóminas con valor neto negativo"
    )
    
    nonprofit = fields.Boolean(
        'Empresa sin ánimo de lucro',
        default=False,
        help="Omite validaciones de topes para parafiscales que aplican a empresas con ánimo de lucro"
    )
    
    prst_wo_susp = fields.Boolean(
        'No descontar suspensiones de prima',
        default=False,
        help="No resta días de suspensión para cálculo de prima"
    )
    
    accounting_method = fields.Selection([
        ('employee', 'Por empleado'),
        ('department', 'Por departamento'),
        ('analytic', 'Por cuenta analítica'),
        ('branch', 'Por sucursal'),
        ('single', 'Asiento único')
    ], string='Método de contabilización', default='single',
       help="Define agrupación de asientos contables de nómina")
    
    default_accounting_date = fields.Selection([
        ('period_end', 'Fin de período'),
        ('process_date', 'Fecha de proceso'),
        ('specific_date', 'Fecha específica por lote')
    ], string='Fecha de contabilización predeterminada', default='period_end',
       help="Define fecha predeterminada para asientos contables")
    overtime_calculation_method = fields.Selection([
        ('standard', 'Estándar (Salario actual)'), 
        ('average_3m', 'Promedio 3 meses'),
        ('average_6m', 'Promedio 6 meses'),
        ('last_salary', 'IBL Mes anterior')
    ], string='Método de cálculo horas extras', default='standard',
       help="Define base salarial para cálculo de horas extras")
    complete_february_to_30 = fields.Boolean(
        string='Completar febrero a 30 días',
        default=True,
        help='Si está activo, en febrero se añadirán días adicionales para llegar a 30'
    )
    
    month_change_policy = fields.Selection([
        ('use_workdays', 'Usar días trabajados para completar'),
        ('use_absence', 'Continuar con el tipo de ausencia')
    ], string='Política para cambio de mes', 
       default='use_absence',
       help='Define cómo manejar las ausencias que continúan de un mes a otro:'
            '\n- Usar días trabajados: si una ausencia termina el último día del mes,'
            ' los días siguientes (31 o feb 29/30) se tratarán como días trabajados'
            '\n- Continuar ausencia: si una ausencia termina el último día del mes,'
            ' se continuará con el mismo tipo de ausencia para completar a 30 días.')
    
    apply_day_31 = fields.Boolean(
        string='Aplicar regla para día 31',
        default=True,
        help='Si está activo, el día 31 se manejará como un día adicional según reglas especiales'
    )
    severance_pay_calculation = fields.Selection([
        ('consolidated', 'Consolidado (Base Real)'),
        ('simplified', 'Simplificado (Porcentaje)')
    ], string='Cálculo de cesantías', default='consolidated',
       help="Método para calcular cesantías")
    store_payroll_history = fields.Boolean(
        'Almacenar histórico detallado de Sueldo',
        default=True,
        help="Guarda información detallada para consultas históricas y promedios"
    )
    ibc_history_months = fields.Integer(
        'Meses de historia IBC a mantener',
        default=24,
        help="Meses de historia IBC que se mantendrán por empleado"
    )
    working_hours_ids = fields.One2many('hr.company.working.hours', 'annual_parameter_id', string='Configuración de horas laborales')
    @api.depends('company_id', 'year')
    def _compute_displays_name(self):
        """Genera un nombre descriptivo para el registro"""
        for record in self:
            if record.company_id and record.year:
                record.name = f"Políticas de Nómina {record.company_id.name} - {record.year}"
            else:
                record.name = f"Políticas de Nómina {record.year}"
    
    _sql_constraints = [
        ('company_year_unique', 'UNIQUE(company_id, year)', 
         'Ya existe un registro de políticas para esta compañía y año')
    ]
    
    @api.model
    def get_policies(self, company_id=None, date=None):
        if not company_id:
            company_id = self.env.company.id
        if not date:
            date = fields.Date.today()
            
        year = date.year
        
        # Buscar políticas para ese año y compañía
        policies = self.search([
            ('company_id', '=', company_id),
            ('year', '=', year),
            ('active', '=', True)
        ], limit=1)
        
        # Si no existen, buscar las del año más reciente
        if not policies:
            policies = self.search([
                ('company_id', '=', company_id),
                ('active', '=', True)
            ], order='year desc', limit=1)
            
        # Si todavía no hay, crear unas por defecto
        if not policies:
            policies = self.create({
                'company_id': company_id,
                'year': year
            })
            
        return policies

    # Metodos
    def name_get(self):
        result = []
        for record in self:
            result.append((record.id, "{}".format(str(record.year))))
        return result

    @api.depends('smmlv_monthly')
    def _values_smmlv(self):
        for record in self:
            record.smmlv_daily = record.smmlv_monthly / 30
            record.top_four_fsp_smmlv = 4 * record.smmlv_monthly
            record.top_twenty_five_smmlv = 25 * record.smmlv_monthly
            record.top_ten_smmlv = 10 * record.smmlv_monthly
            record.top_max_transportation_assistance = 2 * record.smmlv_monthly
            record.min_integral_salary = 13 * record.smmlv_monthly

    @api.depends('transportation_assistance_monthly')
    def _value_transportation_assistance_daily(self):
        for rec in self:
            rec.transportation_assistance_daily = rec.transportation_assistance_monthly / 30

    @api.depends('porc_integral_salary')
    def _values_integral_salary(self):
        for rec in self:
            porc_integral_salary_rest = 100 - rec.porc_integral_salary
            value_factor_integral_salary = round(rec.min_integral_salary / ((porc_integral_salary_rest / 100) + 1), 0)
            value_factor_integral_performance = round(rec.min_integral_salary - value_factor_integral_salary, 0)
            rec.value_factor_integral_salary = value_factor_integral_salary
            rec.value_factor_integral_performance = value_factor_integral_performance

    @api.depends('hours_monthly')
    def _compute_hours(self):
        for rec in self:
            if rec.hours_monthly:
                rec.hours_weekly = 7 * (rec.hours_monthly / 30)
                rec.hours_fortnightly = 15 * (rec.hours_monthly / 30)
                rec.hours_daily = rec.hours_monthly / 30
            else:
                rec.hours_daily = 0
                rec.hours_weekly = 0
                rec.hours_fortnightly = 0
                

    @api.onchange('hours_monthly')
    def _onchange_hours_monthly(self):
        """Actualiza los campos de horas cuando cambia el valor mensual en la interfaz"""
        for rec in self:
            if rec.hours_monthly:
                rec.hours_daily = rec.hours_monthly / 30
                rec.hours_weekly = 7 * rec.hours_daily
                rec.hours_fortnightly = 15 * rec.hours_daily

    @api.depends('value_porc_health_company', 'value_porc_health_employee')
    def _value_porc_health_total(self):
        for rec in self:
            rec.value_porc_health_total = rec.value_porc_health_company + rec.value_porc_health_employee

    @api.depends('value_porc_pension_company', 'value_porc_pension_employee')
    def _value_porc_pension_total(self):
        for rec in self:
            rec.value_porc_pension_total = rec.value_porc_pension_company + rec.value_porc_pension_employee

    # Validaciones
    @api.onchange('porc_integral_salary')
    def _onchange_porc_integral_salary(self):
        for record in self:
            if record.porc_integral_salary > 100:
                raise UserError(_('El porcentaje salarial integral no puede ser mayor a 100. Por favor verificar.'))

                # Funcionalidades

    def get_values_integral_salary(self, integral_salary, get_value):
        for rec in self:
            porc_integral_salary_rest = 100 - rec.porc_integral_salary
            value_factor_integral_salary = round(integral_salary / ((porc_integral_salary_rest / 100) + 1), 0)
            value_factor_integral_performance = round(integral_salary - value_factor_integral_salary, 0)
            value_factor_integral_salary = value_factor_integral_salary
            value_factor_integral_performance = value_factor_integral_performance
        return value_factor_integral_salary if get_value == 0 else value_factor_integral_performance

    def action_create_working_hours(self):
        """
        Crea un registro de horas de trabajo para cada mes del año
        según la normativa vigente (Ley 2101 de 2021) que establece la reducción 
        exactamente el 15 de julio de cada año
        """
        self.ensure_one()
        
        # Obtiene el año actual del registro
        year = self.year
        company_id = self.company_id.id
        
        # Fechas importantes de reducción según la Ley 2101
        # La reducción ocurre el 15 de julio de cada año
        date_july_15_2023 = fields.Date.from_string(f'2023-07-15')
        date_july_15_2024 = fields.Date.from_string(f'2024-07-15')
        date_july_15_2025 = fields.Date.from_string(f'2025-07-15')
        date_july_15_2026 = fields.Date.from_string(f'2026-07-15')
        
        # Crea los registros para cada mes del año
        for month in range(1, 13):
            # Verifica si ya existe un registro para este mes y año
            existing = self.env['hr.company.working.hours'].search([
                ('company_id', '=', company_id),
                ('year', '=', year),
                ('month', '=', month)
            ], limit=1)
            
            if existing:
                continue
                
            # Determina el primer día del mes como base
            first_day_of_month = fields.Date.from_string(f'{year}-{month:02d}-01')
            
            # Si el mes es julio, necesitamos crear dos registros: antes y después del 15
            if month == 7 and year >= 2023:
                # Para el 1-14 de julio
                mid_month_date = fields.Date.from_string(f'{year}-07-14')
                
                # Determina las horas según el año para la primera mitad del mes
                if year < 2023:
                    max_hours = 48.0
                    hours_to_pay = 240.0
                elif year == 2023:
                    max_hours = 48.0  # Antes del 15 de julio 2023
                    hours_to_pay = 240.0
                elif year == 2024:
                    max_hours = 47.0  # Antes del 15 de julio 2024
                    hours_to_pay = 235.0
                elif year == 2025:
                    max_hours = 46.0  # Antes del 15 de julio 2025
                    hours_to_pay = 230.0
                elif year == 2026:
                    max_hours = 44.0  # Antes del 15 de julio 2026
                    hours_to_pay = 220.0
                else:  # 2027 en adelante
                    max_hours = 42.0
                    hours_to_pay = 210.0
                    
                # Crear registro para la primera mitad del mes
                self.env['hr.company.working.hours'].create({
                    'company_id': company_id,
                    'year': year,
                    'month': month,
                    'max_hours_per_week': max_hours,
                    'hours_to_pay': hours_to_pay,
                    'effective_date': first_day_of_month,
                    'notes': f'Válido del 1 al 14 de julio {year}. Creado según Ley 2101 de 2021',
                    'annual_parameter_id': self.id
                })
                
                # Para el 15-31 de julio
                second_half_date = fields.Date.from_string(f'{year}-07-15')
                
                # Determina las horas según el año para la segunda mitad del mes
                if year < 2023:
                    max_hours = 48.0
                    hours_to_pay = 240.0
                elif year == 2023:
                    max_hours = 47.0  # Después del 15 de julio 2023
                    hours_to_pay = 235.0
                elif year == 2024:
                    max_hours = 46.0  # Después del 15 de julio 2024
                    hours_to_pay = 230.0
                elif year == 2025:
                    max_hours = 44.0  # Después del 15 de julio 2025
                    hours_to_pay = 220.0
                elif year == 2026:
                    max_hours = 42.0  # Después del 15 de julio 2026
                    hours_to_pay = 210.0
                else:  # 2027 en adelante
                    max_hours = 42.0
                    hours_to_pay = 210.0
                    
                # Crear registro para la segunda mitad del mes
                self.env['hr.company.working.hours'].create({
                    'company_id': company_id,
                    'year': year,
                    'month': month,
                    'max_hours_per_week': max_hours,
                    'hours_to_pay': hours_to_pay,
                    'effective_date': second_half_date,
                    'notes': f'Válido del 15 al 31 de julio {year}. Creado según Ley 2101 de 2021',
                    'annual_parameter_id': self.id
                })
                
            else:
                # Para los demás meses, crear un solo registro
                
                # Determina las horas basadas en la fecha del mes relativa a las fechas de reducción
                if year < 2023 or (year == 2023 and (month < 7 or (month == 7 and first_day_of_month < date_july_15_2023))):
                    max_hours = 48.0
                    hours_to_pay = 240.0
                elif (year == 2023 and (month > 7 or (month == 7 and first_day_of_month >= date_july_15_2023))) or \
                    (year == 2024 and (month < 7 or (month == 7 and first_day_of_month < date_july_15_2024))):
                    max_hours = 47.0
                    hours_to_pay = 235.0
                elif (year == 2024 and (month > 7 or (month == 7 and first_day_of_month >= date_july_15_2024))) or \
                    (year == 2025 and (month < 7 or (month == 7 and first_day_of_month < date_july_15_2025))):
                    max_hours = 46.0
                    hours_to_pay = 230.0
                elif (year == 2025 and (month > 7 or (month == 7 and first_day_of_month >= date_july_15_2025))) or \
                    (year == 2026 and (month < 7 or (month == 7 and first_day_of_month < date_july_15_2026))):
                    max_hours = 44.0
                    hours_to_pay = 220.0
                else:  # 2026-07-15 en adelante
                    max_hours = 42.0
                    hours_to_pay = 210.0
                    
                # Crear el registro de horas para el mes normal
                self.env['hr.company.working.hours'].create({
                    'company_id': company_id,
                    'year': year,
                    'month': month,
                    'max_hours_per_week': max_hours,
                    'hours_to_pay': hours_to_pay,
                    'effective_date': first_day_of_month,
                    'notes': f'Creado según Ley 2101 de 2021. Válido para {month}/{year}',
                    'annual_parameter_id': self.id
                })
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Configuración de horas creada'),
                'message': _('Se han creado los registros de horas laborales para todos los meses del año %s según la Ley 2101 de 2021, con la reducción exacta el 15 de julio.') % year,
                'sticky': False,
                'type': 'success',
            }
        }

class HrCompanyWorkingHours(models.Model):
    _name = 'hr.company.working.hours'
    _description = 'Horas Laborales por Empresa'
    _order = 'year desc, month desc'
    
    name = fields.Char(
        string='Nombre',
        compute='_compute_display_name',
        store=True
    )
    
    company_id = fields.Many2one(
        'res.company',
        string='Empresa',
        index=True
    )
    
    year = fields.Integer(
        string='Año',
        required=True,
        default=lambda self: fields.Date.today().year,
        index=True
    )
    
    month = fields.Integer(
        string='Mes',
        required=True,
        default=lambda self: fields.Date.today().month,
        index=True
    )
    
    max_hours_per_week = fields.Float(
        string='Horas máximas por semana',
        required=True,
        help="Jornada laboral semanal máxima según normativa vigente"
    )
    
    hours_per_month = fields.Float(
        string='Horas laborales mensuales',
        compute='_compute_monthly_hours',
        store=True,
        help="Horas laborales totales por mes"
    )
    
    hours_to_pay = fields.Float(
        string='Horas a pagar',
        required=True,
        help="Horas que deben pagarse según la normativa"
    )
    
    effective_date = fields.Date(
        string='Fecha de vigencia',
        required=True,
        help="Fecha desde la cual aplica esta configuración"
    )
    
    notes = fields.Text(
        string='Notas',
        help="Observaciones adicionales sobre esta configuración"
    )
    
    annual_parameter_id = fields.Many2one('hr.annual.parameters', 'Parámetro relacionado', ondelete='cascade')
    
    @api.depends('year', 'month', 'company_id')
    def _compute_display_name(self):
        """Genera un nombre descriptivo para el registro"""
        month_names = {
            1: 'Enero', 2: 'Febrero', 3: 'Marzo', 4: 'Abril',
            5: 'Mayo', 6: 'Junio', 7: 'Julio', 8: 'Agosto',
            9: 'Septiembre', 10: 'Octubre', 11: 'Noviembre', 12: 'Diciembre'
        }
        
        for record in self:
            if record.month and record.year:
                month_name = month_names.get(record.month, str(record.month))
                record.name = f"Horas Laborales - {month_name} {record.year}"
            else:
                record.name = "Horas Laborales"
    
    @api.depends('max_hours_per_week')
    def _compute_monthly_hours(self):
        """Calcula las horas mensuales basadas en las horas semanales"""
        for record in self:
            # Multiplicamos por 4.33 semanas que tiene un mes en promedio
            record.hours_per_month = round(record.max_hours_per_week * 4.33, 1)
    
    _sql_constraints = [
        ('company_year_month_unique', 'UNIQUE(company_id, year, month)', 
         'Ya existe un registro para esta empresa, año y mes')
    ]
    
    @api.model
    def get_current_hours(self, company_id=None, date=None):
        """
        Obtiene la configuración de horas vigente para una fecha y empresa
        
        Args:
            company_id: ID de la empresa (usa la actual si no se especifica)
            date: Fecha de referencia (usa la actual si no se especifica)
            
        Returns:
            Registro de horas vigente para la fecha especificada
        """
        if not company_id:
            company_id = self.env.company.id
            
        if not date:
            date = fields.Date.today()
            
        # Buscar configuración vigente
        hours = self.search([
            ('company_id', '=', company_id),
            ('effective_date', '<=', date),
            ('active', '=', True)
        ], order='effective_date desc', limit=1)
        
        if not hours:
            current_year = date.year
            current_month = date.month
            if current_year < 2024 or (current_year == 2024 and current_month < 7):
                max_hours = 48.0
                hours_to_pay = 240.0
            elif (current_year == 2024 and current_month >= 7) or (current_year == 2025 and current_month < 7):
                max_hours = 46.0
                hours_to_pay = 230.0
            elif (current_year == 2025 and current_month >= 7) or (current_year == 2026 and current_month < 7):
                max_hours = 44.0
                hours_to_pay = 220.0
            else:
                max_hours = 42.0
                hours_to_pay = 210.0
            hours = self.create({
                'company_id': company_id,
                'year': current_year,
                'month': current_month,
                'max_hours_per_week': max_hours,
                'hours_to_pay': hours_to_pay,
                'effective_date': date,
                'notes': 'Creado  según Ley 2101 de 2021'
            })
        return hours
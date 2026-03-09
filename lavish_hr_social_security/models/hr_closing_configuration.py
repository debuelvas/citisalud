from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

#Configuración contabilización cierre de nómina (Seguridad social & Provisiones)
class hr_closing_configuration_detail(models.Model):
    _name ='hr.closing.configuration.detail'
    _description = 'Configuración contabilización cierre de nómina (Seguridad social & Provisiones)'

    process_id = fields.Many2one('hr.closing.configuration.header', string = 'Proceso')
    department = fields.Many2one('hr.department', string = 'Departamento')
    company = fields.Many2one('res.company', string = 'Compañía', required=True)
    work_location = fields.Many2one('res.partner', string = 'Ubicación de trabajo')
    third_debit = fields.Selection([('entidad', 'Entidad'),
                                    ('compañia', 'Compañia'),
                                    ('empleado', 'Empleado')], string='Tercero débito')
    third_credit = fields.Selection([('entidad', 'Entidad'),
                                    ('compañia', 'Compañia'),
                                    ('empleado', 'Empleado')], string='Tercero crédito')
    debit_account = fields.Many2one('account.account', string = 'Cuenta débito', company_dependent=True)
    credit_account = fields.Many2one('account.account', string = 'Cuenta crédito', company_dependent=True)

#Configuración parametrización contabilización cierre de nómina (Seguridad social & Provisiones)
class hr_closing_configuration_header(models.Model):
    _name = 'hr.closing.configuration.header'
    _description = 'Configuración parametrización contabilización cierre de nómina (Seguridad social & Provisiones)'

    process = fields.Selection([('vacaciones', 'Vacaciones'),
                                ('prima', 'Prima'),
                                ('cesantias', 'Cesantías'),
                                ('intcesantias', 'Intereses de cesantías'),
                                ('ss_empresa_salud', 'Seguridad social - Aporte empresa salud'),
                                ('ss_empresa_pension', 'Seguridad social - Aporte empresa pensión'),
                                ('ss_empresa_arp', 'Seguridad social - Aporte ARP'),
                                ('ss_empresa_caja', 'Seguridad social - Aporte caja de compensación'),
                                ('ss_empresa_sena', 'Seguridad social - Aporte SENA'),
                                ('ss_empresa_icbf', 'Seguridad social - Aporte ICBF'),
                                ('esap', 'Escuela Superior de Administración Pública'),
                                ('men', 'Ministerio de Educación Nacional'),
                                ('upc', 'UPC')
                                ], string='Proceso')
    description = fields.Text(string='Descripción')
    journal_id = fields.Many2one('account.journal',string='Diario', company_dependent=True)
    detail_ids = fields.One2many('hr.closing.configuration.detail','process_id',string='Contabilización')
    debit_account_difference = fields.Many2one('account.account', string='Cuenta débito diferencia', company_dependent=True)
    credit_account_difference = fields.Many2one('account.account', string='Cuenta crédito diferencia', company_dependent=True)
    main_line_ids = fields.One2many('hr.closing.social.security.line', 'rule_id', 
        string='Líneas Principales', domain=[('line_type', '=', 'main')])
    leave_line_ids = fields.One2many('hr.closing.social.security.line', 'rule_id',
        string='Líneas de Ausencia', domain=[('line_type', '=', 'leave')])
    law_590_enabled = fields.Boolean('Aplicar Ley 590 (Mipyme)')
    law_1429_enabled = fields.Boolean('Aplicar Ley 1429')
    
    def calculate_parafiscal_reduction(self, company_id, reference_date=None):
        """Calcula reducción según leyes 590 y 1429"""
        self.ensure_one()
        if not (self.law_590_enabled or self.law_1429_enabled):
            return 0.0

        company = self.env['res.company'].browse(company_id)
        constitution_date = company.constitution_date
        if not constitution_date:
            raise UserError(_('Fecha de constitución no configurada para la empresa'))

        reference_date = reference_date or fields.Date.today()
        company_age = (reference_date - constitution_date).days / 360

        if self.law_590_enabled:  # Mipyme
            if company_age <= 1:
                return 0.75
            elif company_age <= 2:
                return 0.50
            elif company_age <= 3:
                return 0.25
        elif self.law_1429_enabled:  # Beneficiario Ley 1429
            if company_age <= 2:
                return 1.00
            elif company_age <= 3:
                return 0.75
            elif company_age <= 4:
                return 0.50
            elif company_age <= 5:
                return 0.25
        return 0.0
    def calculate_parafiscal_reduction(self, company_id, reference_date=None):
        """Calcula reducción según leyes 590 y 1429"""
        self.ensure_one()
        if not (self.law_590_enabled or self.law_1429_enabled):
            return 0.0

        company = self.env['res.company'].browse(company_id)
        constitution_date = company.constitution_date
        if not constitution_date:
            raise UserError(_('Fecha de constitución no configurada para la empresa'))

        reference_date = reference_date or fields.Date.today()
        company_age = (reference_date - constitution_date).days / 360

        if self.law_590_enabled:  # Mipyme
            if company_age <= 1:
                return 0.75
            elif company_age <= 2:
                return 0.50
            elif company_age <= 3:
                return 0.25
        elif self.law_1429_enabled:  # Beneficiario Ley 1429
            if company_age <= 2:
                return 1.00
            elif company_age <= 3:
                return 0.75
            elif company_age <= 4:
                return 0.50
            elif company_age <= 5:
                return 0.25
        return 0.0

    def calculate_law_1393(self, salary_data, absences_data=None, vacations_data=None):
        """
        Calcula IBC según Ley 1393 considerando todos los escenarios
        """
        self.ensure_one()
        
        # Montos base
        salary_amount = salary_data.get('salary', 0)
        non_salary_amount = salary_data.get('non_salary', 0)
        total_base = salary_amount + non_salary_amount

        # Procesamiento de ausencias
        absence_amount = 0
        if absences_data and self.include_absences_1393:
            for absence in absences_data:
                if absence.get('type') in ['IGE', 'LMA']:  # Incapacidades y licencias
                    absence_amount += absence.get('amount', 0)

        # Procesamiento de vacaciones
        vacation_amount = 0
        if vacations_data and self.include_absences_1393:
            vacation_amount = sum(vac.get('amount', 0) for vac in vacations_data)

        # Cálculo total incluyendo ausencias si aplica
        total_amount = total_base
        if self.include_absences_1393:
            total_amount += absence_amount + vacation_amount

        # Límite y exceso
        limit = total_amount * (self.non_salary_limit / 100)
        
        if self.force_law_1393:
            # Escenario forzado: todo monto no salarial
            excess = non_salary_amount
        else:
            # Escenario normal: solo exceso sobre límite
            excess = max(0, non_salary_amount - limit)

        return {
            'total_base': total_base,
            'total_with_absences': total_amount,
            'limit': limit,
            'excess': excess,
            'absence_amount': absence_amount,
            'vacation_amount': vacation_amount,
            'ibc': salary_amount + excess,
            'forced': self.force_law_1393
        }

    _sql_constraints = [('closing_process_uniq', 'unique(process)',
                         'El proceso seleccionado ya esta registrado, por favor verificar.')]

    def name_get(self):
        result = []
        for record in self:
            process_str = dict(self._fields['process'].selection).get(record.process)
            result.append((record.id, "{}".format(process_str)))
        return result


class HrClosingSocialSecurityLine(models.Model):
    _name = 'hr.closing.social.security.line'
    _description = 'Líneas de Configuración de Seguridad Social'
    _order = 'sequence'
    
    rule_id = fields.Many2one('hr.closing.configuration.header', 'Regla', required=True)
    name = fields.Char('Descripción')
    sequence = fields.Integer('Secuencia', default=10)
    active = fields.Boolean(default=True)
    
    line_type = fields.Selection([
        ('main', 'Principal'),
        ('leave', 'Ausencia')
    ], string='Tipo de Línea', required=True)

    # Campos para reglas y categorías
    code_rule = fields.Char('Código de Regla')
    salary_rule_ids = fields.Many2many('hr.salary.rule',  string='Reglas Salariales')
    category_ids = fields.Many2many('hr.salary.rule.category', string='Categorías')
    include_child_categories = fields.Boolean('Incluir Subcategorías')
    
    # Campos para ausencias
    leave_type = fields.Selection([
        ('DIAT', 'Días Trabajados'),
        ('SLN', 'Licencia No Remunerada'),
        ('IGE', 'Incapacidad General'),
        ('LMA', 'Licencia de Maternidad'),
        ('VAC', 'Vacaciones'),
        ('LR', 'Licencia Remunerada'),
        ('IRL', 'Licencia Remunerada')
    ], string='Tipo de Novedad')
    code_leave = fields.Char('Código de Ausencia')
    leave_type_id = fields.Many2one('hr.leave.type', 'Tipo de Ausencia')
    
    # Configuración de IBC
    use_previous_ibc = fields.Boolean('Usar IBC Anterior')
    force_previous_ibc = fields.Boolean('Forzar IBC Anterior')
    validate_previous_ibc = fields.Boolean('Validar IBC Anterior')
    
    # Manejo especial de días
    february_handling = fields.Selection([
        ('complete_30_absence', 'Completar 30 días con ausencia'),
        ('complete_30_work', 'Completar 30 días trabajados')
    ], string='Manejo Febrero')
    
    handle_month_31 = fields.Selection([
        ('ignore', 'Ignorar'),
        ('next_month', 'Pasar al Siguiente Mes'),
        ('ibc_only', 'Pagar en IBC')
    ], 'Manejo día 31')
    
    # Campos para Ley 1393
    apply_law_1393 = fields.Boolean('Aplicar Ley 1393')
    force_law_1393 = fields.Boolean('Forzar Ley 1393')
    include_absences_1393 = fields.Boolean('Incluir Ausencias en Ley 1393')
    non_salary_limit = fields.Float('Límite No Salarial (%)', default=40.0)
    
    # Parafiscales
    law_590_enabled = fields.Boolean('Aplicar Ley 590 (Mipyme)')
    law_1429_enabled = fields.Boolean('Aplicar Ley 1429')

    # Relación con parametrización
    contributor_type_id = fields.Many2one('hr.tipo.cotizante', 'Tipo de Cotizante')
    contributor_subtype_id = fields.Many2one('hr.subtipo.cotizante', 'Subtipo de Cotizante')
    parameterization_id = fields.Many2one('hr.parameterization.of.contributors', 'Parametrización')

    @api.onchange('line_type')
    def _onchange_line_type(self):
        if self.line_type == 'main':
            self.leave_type = False
            self.code_leave = False
            self.leave_type_id = False
        else:
            self.code_rule = False
            self.salary_rule_ids = False
            self.category_ids = False
            self.include_child_categories = False

    @api.constrains('line_type', 'salary_rule_ids', 'category_ids', 'leave_type_id')
    def _check_line_configuration(self):
        for line in self:
            if line.line_type == 'main':
                if not (line.salary_rule_ids or line.category_ids or line.code_rule):
                    raise ValidationError(_('Líneas principales requieren regla salarial, categoría o código'))
            elif line.line_type == 'leave':
                if not (line.leave_type_id or line.leave_type or line.code_leave):
                    raise ValidationError(_('Líneas de ausencia requieren tipo o código de ausencia'))

    def get_applicable_items(self):
        self.ensure_one()
        if self.line_type == 'main':
            return self._get_rules_and_categories()
        return self._get_leave_types()

    def _get_rules_and_categories(self):
        """
        Obtiene reglas y categorías asociadas a la línea,
        incluyendo las definidas por código y categorías hijas.
        """
        self.ensure_one()
        rules = self.salary_rule_ids
        categories = self.category_ids
        
        # Buscar reglas y categorías por código
        if self.code_rule:
            codes = [x.strip() for x in self.code_rule.split(',')]
            rules |= self.env['hr.salary.rule'].search([('code', 'in', codes)])
            categories |= self.env['hr.salary.rule.category'].search([('code', 'in', codes)])
        
        # Incluir categorías hijas si está marcada la opción
        if self.include_child_categories and categories:
            child_categories = self.env['hr.salary.rule.category']
            for category in categories:
                child_categories |= self._get_child_categories(category)
            categories |= child_categories
        
        return {
            'rules': rules,
            'categories': categories
        }

    def _get_child_categories(self, category):
        children = self.env['hr.salary.rule.category']
        for child in category.children_ids:
            children |= child
            children |= self._get_child_categories(child)
        return children

    def _get_leave_types(self):
        self.ensure_one()
        domain = []
        if self.code_leave:
            codes = [x.strip() for x in self.code_leave.split(',')]
            domain.append(('code', 'in', codes))
        #if self.leave_type:
        #    domain.append(('novelty_type', '=', self.leave_type))
        if self.leave_type_id:
            domain.append(('id', '=', self.leave_type_id.id))
        return self.env['hr.leave.type'].search(domain)


class HrSSConfigWizard(models.TransientModel):
    _name = 'hr.ss.config.wizard'
    _description = 'Asistente Configuración SS'

    create_main_lines = fields.Boolean('Crear Líneas Principales', default=True)
    create_absence_lines = fields.Boolean('Crear Líneas de Ausencia', default=True)

    def _validate_required_entities(self, tipo_code, subtipo_code):
        """
        Valida qué conceptos aplican según tipo y subtipo de cotizante.
        Returns: Tuple con indicadores para cada concepto
        (eps, pension, arl, ccf, sena, icbf)
        """
        result = {
            'eps': True,      # Salud
            'pension': True,  # Pensión
            'arl': True,     # ARL
            'ccf': True,     # Caja de Compensación
            'sena': True,    # SENA
            'icbf': True     # ICBF
        }

        # Dependiente con subtipos especiales no aporta pensión
        if tipo_code == '01' and subtipo_code in ('01', '04', '05'):
            result['pension'] = False

        # Aprendices y casos especiales
        if subtipo_code == '00':
            if tipo_code in ('12', '40'):  # Aprendices lectiva
                result.update({
                    'pension': False,
                    'arl': False,
                    'ccf': False,
                    'sena': False,
                    'icbf': False
                })
            elif tipo_code == '19':  # Aprendices productiva
                result.update({
                    'pension': False,
                    'ccf': False,
                    'sena': False,
                    'icbf': False
                })

        return (
            result['eps'],
            result['pension'],
            result['arl'],
            result['ccf'],
            result['sena'],
            result['icbf']
        )

    def _check_concept_applies(self, tipo_code, subtipo_code, process):
        """Verifica si un proceso aplica según tipo/subtipo de cotizante"""
        eps, pension, arl, ccf, sena, icbf = self._validate_required_entities(tipo_code, subtipo_code)
        
        process_validation_map = {
            'ss_empresa_salud': eps,
            'ss_empresa_pension': pension,
            'ss_empresa_arp': arl,
            'ss_empresa_caja': ccf,
            'ss_empresa_sena': sena,
            'ss_empresa_icbf': icbf
        }
        
        return process_validation_map.get(process, False)

 
    def _create_absence_lines(self, header):
        tipos = self.env['hr.tipo.cotizante'].search([])
        absence_rules = self._get_absence_rules()

        # Set para controlar combinaciones existentes
        existing_combos = set()
        existing_lines = self.env['hr.closing.social.security.line'].search([
            ('rule_id', '=', header.id),
            ('line_type', '=', 'leave'),
        ])
        
        for line in existing_lines:
            key = (
                line.rule_id.id,
                line.contributor_type_id.id,
                line.contributor_subtype_id.id,
                line.leave_type
            )
            existing_combos.add(key)

        for tipo in tipos:
            # Determinar qué subtipos procesar basado en el tipo de cotizante
            if tipo.code == '01':
                subtipos = self.env['hr.subtipo.cotizante'].search([])
            else:
                # Para otros tipos, solo procesar el subtipo '00'
                subtipos = self.env['hr.subtipo.cotizante'].search([('code', 'in', ['00'])], limit=1)

            for subtipo in subtipos:
                param = self._create_or_get_parameterization(tipo, subtipo)
                applies = self._check_concept_applies(tipo.code, subtipo.code, header.process)

                # Verificar si aplican parafiscales
                applies_parafiscal = True
                if header.process in ['ss_empresa_caja', 'ss_empresa_sena', 'ss_empresa_icbf']:
                    if subtipo.code == '00':
                        if tipo.code in ('12', '40', '19'):
                            applies_parafiscal = False
                    applies = applies and applies_parafiscal

                for leave_type, config in absence_rules.items():
                    # Verificar si la regla de pago aplica para este proceso
                    if not config['payment_rules'].get(header.process, False):
                        continue

                    # Para procesos parafiscales, aplicar reglas especiales
                    if header.process in ['ss_empresa_caja', 'ss_empresa_sena', 'ss_empresa_icbf']:
                        if not applies_parafiscal:
                            continue

                    key = (
                        header.id,
                        tipo.id,
                        subtipo.id,
                        leave_type
                    )

                    if key not in existing_combos:
                        self.env['hr.closing.social.security.line'].create({
                            'rule_id': header.id,
                            'line_type': 'leave',
                            'name': f'{tipo.name} - {subtipo.name} - {config["name"]}',
                            'contributor_type_id': tipo.id,
                            'contributor_subtype_id': subtipo.id,
                            'parameterization_id': param.id,
                            'leave_type': leave_type,
                            'code_leave': ','.join(config['codes']),
                            'active': applies and config['payment_rules'].get(header.process, False),
                            'use_previous_ibc': True,
                            'february_handling': 'complete_30_absence' if leave_type != 'VAC' else 'complete_30_work',
                            'handle_month_31': 'ibc_only'
                        })
                        existing_combos.add(key)

    def _get_ss_processes(self):
        """Lista de procesos de seguridad social"""
        return [
            ('ss_empresa_salud', 'Seguridad social - Aporte empresa salud'),
            ('ss_empresa_pension', 'Seguridad social - Aporte empresa pensión'),
            ('ss_empresa_arp', 'Seguridad social - Aporte ARP'),
            ('ss_empresa_caja', 'Seguridad social - Aporte caja de compensación'),
            ('ss_empresa_sena', 'Seguridad social - Aporte SENA'),
            ('ss_empresa_icbf', 'Seguridad social - Aporte ICBF')
        ]

    def _create_missing_headers(self):
        """Crea encabezados faltantes para procesos de seguridad social"""
        header_obj = self.env['hr.closing.configuration.header']
        journal = self.env['account.journal'].search([('type', '=', 'general')], limit=1)

        for process_code, process_name in self._get_ss_processes():
            header = header_obj.search([('process', '=', process_code)], limit=1)
            if not header:
                header_obj.create({
                    'process': process_code,
                    #'name': process_name,
                    'description': f'Configuración automática para {process_name}',
                    'journal_id': journal.id if journal else False,
                })



    def _create_or_get_parameterization(self, tipo, subtipo):
        """
        Crea o recupera la parametrización para un tipo/subtipo de cotizante.
        Considera las reglas específicas para cada combinación.
        """
        param_obj = self.env['hr.parameterization.of.contributors']
        param = param_obj.search([
            ('type_of_contributor', '=', tipo.id),
            ('contributor_subtype', '=', subtipo.id)
        ], limit=1)

        if not param:
            # Determinar valores según tipo y subtipo
            applies_afp = True
            if tipo.code == '01' and subtipo.code in ('01', '04', '05'):
                applies_afp = False
            
            applies_parafiscal = True
            if subtipo.code == '00':
                if tipo.code in ('12', '40'):
                    applies_afp = False
                    applies_parafiscal = False
                elif tipo.code == '19':
                    applies_afp = False
                    applies_parafiscal = False

            param = param_obj.create({
                'type_of_contributor': tipo.id,
                'contributor_subtype': subtipo.id,
                'liquidated_eps_employee': True,
                'liquidate_employee_pension': applies_afp,
                'liquidated_aux_transport': True,
                'liquidates_solidarity_fund': applies_afp,
                'liquidates_eps_company': True,
                'liquidated_company_pension': applies_afp,
                'liquidated_arl': not (subtipo.code == '00' and tipo.code in ('12', '40')),
                'liquidated_sena': applies_parafiscal,
                'liquidated_icbf': applies_parafiscal,
                'liquidated_compensation_fund': applies_parafiscal,
            })

        return param

    def _get_absence_rules(self):
        """
        Define reglas de ausencia y sus configuraciones de pago.
        Returns:
            dict: Diccionario con configuraciones de ausencias
        """
        return {
            'SLN': {  # Licencia No Remunerada
                'codes': ['LICENCIA_NO_REMUNERADA', 'INAS_INJU', 'SANCION', 'SUSP_CONTRATO', 'DNR'],
                'name': 'Licencia No Remunerada',
                'payment_rules': {
                    'ss_empresa_salud': False,
                    'ss_empresa_pension': True,
                    'ss_empresa_arp': False,
                    'ss_empresa_caja': False,
                    'ss_empresa_sena': False,
                    'ss_empresa_icbf': False
                }
            },
            'IGE': {  # Incapacidad General
                'codes': ['EGA', 'EGH'],
                'name': 'Incapacidad General',
                'payment_rules': {
                    'ss_empresa_salud': True,
                    'ss_empresa_pension': True,
                    'ss_empresa_arp': False,
                    'ss_empresa_caja': False,
                    'ss_empresa_sena': False,
                    'ss_empresa_icbf': False
                }
            },
            'LMA': {  # Licencia de Maternidad/Paternidad
                'codes': ['MAT', 'PAT'],
                'name': 'Licencia de Maternidad',
                'payment_rules': {
                    'ss_empresa_salud': True,
                    'ss_empresa_pension': True,
                    'ss_empresa_arp': False,
                    'ss_empresa_caja': False,
                    'ss_empresa_sena': False,
                    'ss_empresa_icbf': False
                }
            },
            'VAC': {  # Vacaciones
                'codes': ['VACDISFRUTADAS'],
                'name': 'Vacaciones',
                'payment_rules': {
                    'ss_empresa_salud': True,
                    'ss_empresa_pension': True,
                    'ss_empresa_arp': True,
                    'ss_empresa_caja': True,
                    'ss_empresa_sena': True,
                    'ss_empresa_icbf': True
                }
            },
            'LR': {  # Licencia Remunerada
                'codes': ['LICENCIA_REMUNERADA', 'LUTO', 'REP_VACACIONES', 'CALAMIDAD'],
                'name': 'Licencia Remunerada',
                'payment_rules': {
                    'ss_empresa_salud': True,
                    'ss_empresa_pension': True,
                    'ss_empresa_arp': False,
                    'ss_empresa_caja': False,
                    'ss_empresa_sena': False,
                    'ss_empresa_icbf': False
                }
            },
            'IRL': {  # Incapacidad Riesgo Laboral
                'codes': ['EP', 'AT'],
                'name': 'Incapacidad Riesgo Laboral',
                'payment_rules': {
                    'ss_empresa_salud': True,
                    'ss_empresa_pension': True,
                    'ss_empresa_arp': True,
                    'ss_empresa_caja': False,
                    'ss_empresa_sena': False,
                    'ss_empresa_icbf': False
                }
            }
        }


    def _get_pila_contributors(self):
        """Define los tipos de cotizante para PILA Planilla E"""
        return [
            ('01', 'Dependiente'),
            ('12', 'Aprendices en etapa lectiva'),
            ('18', 'Funcionarios públicos sin tope máximo en el IBC'),
            ('19', 'Aprendices en etapa productiva'),
            ('21', 'Residentes'),
            ('22', 'Profesor de establecimiento particular'),
            ('30', 'Dependiente de entidades o universidades públicas'),
            ('31', 'Cooperados y pre-cooperativas de trabajo asociado'),
            ('40', 'Beneficiario UPC Adicional'),
            ('51', 'Trabajador de tiempo parcial')
        ]

    def _create_contributors(self):
        """Crea los tipos de cotizante para PILA si no existen"""
        contributor_obj = self.env['hr.tipo.cotizante']
        subtype_obj = self.env['hr.subtipo.cotizante']

        # Crear tipos de cotizante
        for code, name in self._get_pila_contributors():
            if not contributor_obj.search([('code', '=', code)]):
                contributor_obj.create({
                    'name': name,
                    'code': code
                })

        # Crear subtipos por defecto
        subtypes = [
            ('00', 'Ninguno'),
            ('01', 'Dependiente pensionado por vejez activo')
        ]
        for code, name in subtypes:
            if not subtype_obj.search([('code', '=', code)]):
                subtype_obj.create({
                    'name': name,
                    'code': code,
                    'not_contribute_pension': code == '01'
                })

    def action_create_lines(self):
        self.ensure_one()
        delelet  = self.env['hr.closing.social.security.line'].search([]).unlink()
        self._create_contributors()
        self._create_missing_headers()
        headers = self.env['hr.closing.configuration.header'].search([
            ('process', 'in', [p[0] for p in self._get_ss_processes()])
        ])

        for header in headers:
            if self.create_main_lines:
                self._create_main_lines(header)
            if self.create_absence_lines:
                self._create_absence_lines(header)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Éxito'),
                'message': _('Se han creado las configuraciones de seguridad social'),
                'sticky': False,
                'type': 'success',
            }
        }


    def _group_rules_and_categories(self, rules, tipo_code, process):
        """
        Agrupa reglas y categorías basado en el tipo de cotizante y proceso.
        """
        all_rules = {
            'rules': set(),
            'categories': set(),
            'codes': set()
        }

        # Determinar si es un proceso parafiscal
        is_parafiscal = process in ['ss_empresa_caja', 'ss_empresa_sena', 'ss_empresa_icbf']

        for rule in rules:
            should_include = False
            
            # Para tipo 01, incluir todas las reglas con base salud
            if tipo_code == '01':
                should_include = rule.base_seguridad_social
            else:
                # Para otros tipos, incluir reglas según el proceso
                if is_parafiscal:
                    should_include = rule.base_parafiscales
                else:
                    should_include = rule.base_seguridad_social

            if should_include:
                if rule.code:
                    all_rules['codes'].add(rule.code)
                all_rules['rules'].add(rule.id)
                
                # Solo incluir la categoría de la regla actual
                if rule.category_id:
                    all_rules['categories'].add(rule.category_id.id)

        # Convertir sets a listas para el ORM
        return {
            'rules': list(all_rules['rules']),
            'categories': list(all_rules['categories']),
            'codes': ','.join(sorted(all_rules['codes'])) if all_rules['codes'] else ''
        }

    def _create_main_lines(self, header):
        existing_keys = set()
        existing_lines = self.env['hr.closing.social.security.line'].search([
            ('rule_id', '=', header.id),
            ('line_type', '=', 'main'),
        ])
        for line in existing_lines:
            key = (
                line.rule_id.id,
                line.line_type,
                line.contributor_type_id.id,
                line.contributor_subtype_id.id,
            )
            existing_keys.add(key)

        domain = [
            '|',
            ('base_seguridad_social', '=', True),
            ('base_parafiscales', '=', True),
            ('code','!=',['LICENCIA_NO_REMUNERADA', 'INAS_INJU', 'SANCION', 'SUSP_CONTRATO', 'DNR'])
        ]
        
        tipos = self.env['hr.tipo.cotizante'].search([('code', 'in', [x[0] for x in self._get_pila_contributors()])])
        rules = self.env['hr.salary.rule'].search(domain)

        for tipo in tipos:
            # Determinar qué subtipos procesar
            if tipo.code == '01':
                subtipos = self.env['hr.subtipo.cotizante'].search([])
            else:
                # Para otros tipos, solo procesar el primer subtipo y el subtipo '00'
                subtipos = self.env['hr.subtipo.cotizante'].search([('code', 'in', ['00'])], limit=1)

            for subtipo in subtipos:
                param = self._create_or_get_parameterization(tipo, subtipo)
                applies = self._check_concept_applies(tipo.code, subtipo.code, header.process)

                # Verificar si aplican parafiscales
                if header.process in ['ss_empresa_caja', 'ss_empresa_sena', 'ss_empresa_icbf']:
                    applies_parafiscal = True
                    if subtipo.code == '00':
                        if tipo.code in ('12', '40', '19'):
                            applies_parafiscal = False
                    applies = applies and applies_parafiscal

                # Agrupar reglas y categorías considerando el tipo y proceso
                grouped_data = self._group_rules_and_categories(rules, tipo.code, header.process)
                
                key = (
                    header.id,
                    'main',
                    tipo.id,
                    subtipo.id,
                )

                if key not in existing_keys:
                    self.env['hr.closing.social.security.line'].create({
                        'rule_id': header.id,
                        'line_type': 'main',
                        'name': f'{tipo.name} - {subtipo.name}',
                        'contributor_type_id': tipo.id,
                        'contributor_subtype_id': subtipo.id,
                        'parameterization_id': param.id,
                        'code_rule': grouped_data['codes'],
                        'salary_rule_ids': [(6, 0, grouped_data['rules'])],
                        'category_ids': [(6, 0, grouped_data['categories'])],
                        'active': applies,
                        'february_handling': 'complete_30_work',
                        'handle_month_31': 'ibc_only',
                        'use_previous_ibc': True,
                        'include_child_categories': True
                    })
                    existing_keys.add(key)

    def _check_concept_applies(self, tipo_code, subtipo_code, process):
        """Verifica si un proceso aplica según tipo/subtipo de cotizante y proceso"""
        eps, pension, arl, ccf, sena, icbf = self._validate_required_entities(tipo_code, subtipo_code)
        
        process_validation_map = {
            'ss_empresa_salud': eps,
            'ss_empresa_pension': pension,
            'ss_empresa_arp': arl,
            'ss_empresa_caja': ccf,
            'ss_empresa_sena': sena,
            'ss_empresa_icbf': icbf
        }
        
        applies = process_validation_map.get(process, False)
        
        # Verificación adicional para parafiscales
        if process in ['ss_empresa_caja', 'ss_empresa_sena', 'ss_empresa_icbf']:
            if subtipo_code == '00' and tipo_code in ('12', '40', '19'):
                applies = False
                
        return applies
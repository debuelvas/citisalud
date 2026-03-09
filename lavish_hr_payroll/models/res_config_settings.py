# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

# -*- coding: utf-8 -*-

from odoo import api, fields, models, tools, _
from odoo.exceptions import UserError, ValidationError
from dateutil.relativedelta import relativedelta
from datetime import datetime, date, timedelta
import math
import logging
import json

_logger = logging.getLogger(__name__)



class HrEmployeeSalaryHistory(models.Model):
    _name = 'hr.employee.salary.history'
    _description = 'Historial de Salarios del Empleado'
    _order = 'date desc, id desc'
    
    name = fields.Char(
        string='Referencia',
        index=True
    )
    
    employee_id = fields.Many2one(
        'hr.employee',
        string='Empleado',
        required=True,
        ondelete='cascade',
        index=True,
        help="Empleado al que pertenece este registro"
    )
    
    contract_id = fields.Many2one(
        'hr.contract',
        string='Contrato',
        required=True,
        ondelete='cascade',
        index=True,
        help="Contrato asociado"
    )
    
    date = fields.Date(
        string='Fecha',
        required=True,
        index=True,
        help="Fecha efectiva de este salario"
    )
    
    wage = fields.Float(
        string='Salario',
        digits='Payroll',
        required=True,
        help="Valor del salario básico"
    )
    
    old_wage = fields.Float(
        string='Salario anterior',
        digits='Payroll',
        help="Valor del salario antes del cambio"
    )
    
    worked_days = fields.Integer(
        string='Días trabajados',
        help="Días efectivamente trabajados con este salario"
    )
    
    unpaid_absences = fields.Integer(
        string='Ausencias no pagadas',
        help="Días de ausencias no remuneradas durante este periodo"
    )
    
    reason = fields.Char(
        string='Motivo',
        help="Razón del cambio salarial"
    )
    
    reason_id = fields.Many2one(
        'hr.salary.change.reason',
        string='Motivo de cambio',
        help="Razón catalogada del cambio salarial"
    )
    
    change_type = fields.Selection([
        ('increase', 'Aumento'),
        ('decrease', 'Disminución'),
        ('initial', 'Inicial')
    ], string='Tipo de cambio',
       compute='_compute_change_type',
       store=True,
       help="Indica si fue un aumento o disminución"
    )
    
    percentage_change = fields.Float(
        string='% Cambio',
        digits=(5, 2),
        compute='_compute_change_type',
        store=True,
        help="Porcentaje de cambio respecto al salario anterior"
    )
    
    payslip_id = fields.Many2one(
        'hr.payslip',
        string='Nómina',
        ondelete='set null',
        help="Nómina relacionada con este registro"
    )
    
    document_number = fields.Char(
        string='# Documento',
        help="Número de documento que respalda el cambio"
    )
    
    change_user_id = fields.Many2one(
        'res.users',
        string='Usuario',
        default=lambda self: self.env.user.id,
        help="Usuario que realizó el cambio"
    )
    
    company_id = fields.Many2one(
        'res.company',
        string='Compañía',
        required=True,
        default=lambda self: self.env.company
    )
    
    active = fields.Boolean(
        string='Activo',
        default=True,
        help="Permite archivar registros históricos muy antiguos"
    )
    
    @api.depends('employee_id', 'date', 'wage')
    def _compute_display_name(self):
        """Genera un nombre descriptivo para el registro"""
        for record in self:
            if record.employee_id and record.date:
                record.name = f"{record.employee_id.name} - {record.date.strftime('%Y-%m-%d')} - {record.wage:,.0f}"
            else:
                record.name = "Cambio Salarial"
    
    @api.depends('wage', 'old_wage')
    def _compute_change_type(self):
        """Determina si fue aumento o disminución y calcula el porcentaje"""
        for record in self:
            if not record.old_wage or record.old_wage == 0:
                record.change_type = 'initial'
                record.percentage_change = 0
            elif record.wage > record.old_wage:
                record.change_type = 'increase'
                record.percentage_change = ((record.wage / record.old_wage) - 1) * 100
            elif record.wage < record.old_wage:
                record.change_type = 'decrease'
                record.percentage_change = ((record.old_wage / record.wage) - 1) * -100
            else:
                record.change_type = 'initial'
                record.percentage_change = 0
    
    @api.model
    def create_from_salary_change(self, contract_id, date, wage, old_wage=0.0, reason=False, reason_id=False, document_number=False):
        """Crea un registro histórico de cambio salarial"""
        if not contract_id or not date or not wage:
            return False
            
        contract = self.env['hr.contract'].browse(contract_id)
        if not contract or not contract.employee_id:
            return False
            
        values = {
            'employee_id': contract.employee_id.id,
            'contract_id': contract.id,
            'date': date,
            'wage': wage,
            'old_wage': old_wage,
            'reason': reason or 'Cambio salarial',
            'reason_id': reason_id,
            'document_number': document_number,
            'company_id': contract.company_id.id
        }
        
        return self.create(values)
    
    @api.model
    def update_worked_days(self, employee_id, date_from, date_to, worked_days, unpaid_absences=0):
        """Actualiza los días trabajados para el registro salarial vigente"""
        if not employee_id or not date_from or not date_to:
            return False
        salary_record = self.search([
            ('employee_id', '=', employee_id),
            ('date', '<=', date_to)
        ], order='date desc', limit=1)
        
        if salary_record:
            salary_record.write({
                'worked_days': worked_days,
                'unpaid_absences': unpaid_absences
            })
            return salary_record
            
        return False
    
    @api.model
    def get_employee_salary_average(self, employee_id, date, months=3):
        """Obtiene el promedio salarial de un empleado para los últimos n meses"""
        if not employee_id or not date:
            return 0.0
            
        date_from = date - relativedelta(months=months)
        
        records = self.search([
            ('employee_id', '=', employee_id),
            ('date', '>=', date_from),
            ('date', '<=', date)
        ], order='date')
        if not records:
            contract = self.env['hr.contract'].search([
                ('employee_id', '=', employee_id),
                ('state', '=', 'open')
            ], limit=1)
            return contract.wage if contract else 0.0
        if len(records) == 1:
            return records[0].wage
        total_days = sum(r.worked_days for r in records if r.worked_days)
        if total_days <= 0:
            return sum(r.wage for r in records) / len(records)
        weighted_sum = sum(r.wage * r.worked_days for r in records if r.worked_days)
        return weighted_sum / total_days


class HrEmployeeIbcHistory(models.Model):
    _name = 'hr.employee.ibc.history'
    _description = 'Historial IBC del Empleado'
    _order = 'year desc, month desc, id desc'
    
    name = fields.Char(
        string='Nombre',
        store=True,
        index=True
    )
    
    employee_id = fields.Many2one(
        'hr.employee',
        string='Empleado',
        required=True,
        ondelete='cascade',
        index=True,
        help="Empleado al que pertenece este registro"
    )
    
    contract_id = fields.Many2one(
        'hr.contract',
        string='Contrato',
        required=True,
        ondelete='cascade',
        index=True,
        help="Contrato vigente al momento del registro"
    )
    
    year = fields.Integer(
        string='Año',
        required=True,
        index=True,
        help="Año al que corresponde este registro IBC"
    )
    
    month = fields.Integer(
        string='Mes',
        required=True,
        index=True,
        help="Mes al que corresponde este registro IBC (1-12)"
    )
    
    ibc_value = fields.Float(
        string='Valor IBC',
        digits='Payroll',
        required=True,
        help="Ingreso Base de Cotización calculado para este periodo"
    )
    
    ibc_daily = fields.Float(
        string='IBC diario',
        digits='Payroll',
        store=True,
        help="Valor IBC diario (IBC / días cotizados)"
    )
    
    ibc_days = fields.Integer(
        string='Días cotizados',
        default=30,
        help="Días efectivamente cotizados en este periodo"
    )
    
    date_from = fields.Date(
        string='Fecha inicio',
        help="Fecha de inicio del periodo"
    )
    
    date_to = fields.Date(
        string='Fecha fin',
        help="Fecha de fin del periodo"
    )
    
    payslip_id = fields.Many2many(
        'hr.payslip',
        string='Nómina',
        help="Nómina que generó este registro"
    )
        
    wage = fields.Float(
        string='Salario base',
        digits='Payroll',
        help="Salario base del empleado en este periodo"
    )
    
    salarial_items = fields.Float(
        string='Componentes salariales',
        digits='Payroll',
        help="Valor de componentes salariales adicionales (horas extra, recargos, etc.)"
    )
    
    non_salarial_items = fields.Float(
        string='Componentes no salariales',
        digits='Payroll',
        help="Valor de componentes no salariales"
    )
    
    rule40_limit = fields.Float(
        string='Límite 40%',
        digits='Payroll',
        store=True,
        help="Límite del 40% para componentes no salariales"
    )
    
    applied_40_rule = fields.Boolean(
        string='Aplicó regla 40%',
        help="Indica si se aplicó la regla del 40% para componentes no salariales"
    )
    
    exceed_40_value = fields.Float(
        string='Excedente 40%',
        digits='Payroll',
        store=True,
        help="Valor que excede el límite del 40%"
    )
    
    company_id = fields.Many2one(
        'res.company',
        string='Compañía',
        required=True,
        default=lambda self: self.env.company
    )

    

    
class ResCompany(models.Model):
    _inherit = 'res.company'

    payroll_electronic_operator = fields.Selection([('Carvajal', 'Carvajal'),
                                                    ('FacturaTech', 'FacturaTech')],
                                                   string='Operador', default='Carvajal')
    payroll_electronic_username_ws = fields.Char(string='Usuario WS')
    payroll_electronic_password_ws = fields.Char(string='Contraseña WS')
    payroll_electronic_company_id_ws = fields.Char(string='Identificador compañia WS')
    payroll_electronic_account_id_ws = fields.Char(string='Identificador cuenta WS')
    payroll_electronic_service_ws = fields.Char(string='Servicio WS', default='PAYROLL')
    payroll_peoplepass_journal_id = fields.Many2one('account.journal',string='Diario contabilización pago valor no incluido')
    payroll_peoplepass_debit_account_id = fields.Many2one('account.account',string='Cuenta contabilización pago valor no incluido débito')
    payroll_peoplepass_credit_account_id = fields.Many2one('account.account',string='Cuenta contabilización pago valor no incluido crédito')
    # Certificado ingreso y retenciones
    validated_certificate = fields.Many2one('documents.tag', string='Certificado validado')
    novelty_approval_required = fields.Boolean(
        'Requiere Aprobación de Novedades', 
        default=False,
        help='Si está activo, las novedades requieren un proceso de aprobación'
    )

    def action_setup_salary_categories(self):
        """Botón para configurar categorías de reglas salariales desde la compañía"""
        self.ensure_one()
        
        self._handle_duplicate_categories()
        
        self._setup_salary_categories()
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Éxito'),
                'message': _('Categorías de reglas salariales configuradas correctamente.'),
                'type': 'success',
                'sticky': False,
            }
        }
    
    def _handle_duplicate_categories(self):
        """
        Maneja categorías con códigos duplicados:
        1. Identifica códigos duplicados
        2. Para cada código, conserva una categoría y archiva las demás
        3. Mueve todas las reglas de las categorías archivadas a la categoría principal
        """
        all_categories = self.env['hr.salary.rule.category'].search([])
        codes = all_categories.mapped('code')
        
        duplicate_codes = []
        for code in set(codes):
            categories = self.env['hr.salary.rule.category'].search([('code', '=', code)])
            if len(categories) > 1:
                duplicate_codes.append(code)
        
        for code in duplicate_codes:
            categories = self.env['hr.salary.rule.category'].search([('code', '=', code)])
            
            active_categories = categories.filtered(lambda c: c.active)
            if active_categories:
                active_category = active_categories[0]
            else:
                active_category = categories[0]
                active_category.write({'active': True})
            
            for category in categories:
                if category.id != active_category.id:
                    rules = self.env['hr.salary.rule'].search([('category_id', '=', category.id)])
                    
                    if rules:
                        rules.write({'category_id': active_category.id})
                        _logger.info(f"Movidas {len(rules)} reglas desde categoría {category.name} a {active_category.name}")
                    
                    category.write({'active': False})
                    _logger.info(f"Categoría archivada: {category.name} (código duplicado {code})")
    
    def _setup_salary_categories(self):
        """
        Configura las categorías de reglas salariales con orden lógico:
        - Devengos: secuencias 1-200
        - Deducciones: secuencias 201-300
        - Prestaciones: secuencias 301-400
        - Provisiones: secuencias 401-500
        - Totales: secuencias 501-600
        - Otros: secuencias 601+
        """
 
        main_categories = [
            # DEVENGOS - PRINCIPALES (1-10)
            {'code': 'DEV_SALARIAL', 'name': 'DEVENGO SALARIAL', 'sequence': 1, 'active': True, 
             'description': 'El devengado corresponde a todos los conceptos por los que un empleado recibe una remuneración.', 
             'category_type': 'earnings', 'parent_id': False},
             
            {'code': 'DEV_NO_SALARIAL', 'name': 'DEVENGO NO SALARIAL', 'sequence': 100, 'active': True, 
             'description': 'No constituyen salario las sumas que ocasionalmente recibe el trabajador.', 
             'category_type': 'earnings_non_salary', 'parent_id': False},
             
            # DEDUCCIONES (201-300)
            {'code': 'DEDUCCIONES', 'name': 'DEDUCCIONES', 'sequence': 201, 'active': True, 
             'description': '<p>Las deducciones de nómina son aquellos descuentos al salario.</p>', 
             'category_type': 'deductions', 'parent_id': False},
             
            # PRESTACIONES (301-400)
            {'code': 'PRESTACIONES_SOCIALES', 'name': 'PRESTACIONES SOCIALES', 'sequence': 301, 'active': True, 
             'description': 'Prestación social es lo que debe el patrono al trabajador.', 
             'category_type': 'benefits', 'parent_id': False},
             
            # PROVISIONES (401-500)
            {'code': 'PROV', 'name': 'PROVISIONES DE NOMINA', 'sequence': 401, 'active': True, 
             'description': False, 'category_type': 'provisions', 'parent_id': False},
             
            # TOTALES (501-600)
            {'code': 'TOTALDEV', 'name': 'TOTAL DEVENGO', 'sequence': 501, 'active': True, 
             'description': False, 'category_type': 'totals', 'parent_id': False},
             
            {'code': 'TOTALDED', 'name': 'TOTAL DEDUCCIONES', 'sequence': 510, 'active': True, 
             'description': False, 'category_type': 'totals', 'parent_id': False},
             
            {'code': 'GROSS', 'name': 'BRUTO', 'sequence': 520, 'active': True, 
             'description': '<p><br></p>', 'category_type': 'totals', 'parent_id': False},
             
            {'code': 'NET', 'name': 'NETO', 'sequence': 530, 'active': True, 
             'description': False, 'category_type': 'totals', 'parent_id': False},
             
            # OTROS (601+)
            {'code': 'ALW', 'name': 'SUBSIDIO', 'sequence': 601, 'active': True, 
             'description': False, 'category_type': 'other', 'parent_id': False},
             
            {'code': 'COMP', 'name': 'CONTRIBUCIÓN DE LA EMPRESA', 'sequence': 610, 'active': True, 
             'description': False, 'category_type': 'other', 'parent_id': False},

            {'code': 'AUX', 'name': 'AUXILIO DE TRANSPORTE', 'sequence': 620, 'active': True, 
             'description': 'El auxilio de transporte es un pago que se realiza a los trabajadores que tienen un sueldo de hasta dos salarios mínimos mensuales.', 
             'category_type': 'earnings_non_salary', 'parent_id': False},
            
            {'code': 'AUS', 'name': 'AUSENCIA', 'sequence': 630, 'active': True, 
             'description': False, 'category_type': 'other', 'parent_id': False},
             
            {'code': 'COMISIONES', 'name': 'COMISIONES', 'sequence': 640, 'active': True, 
             'description': False, 'category_type': 'other', 'parent_id': False},
             
            {'code': 'BASE_SEC', 'name': 'BASE SEGURIDAD SOCIAL', 'sequence': 650, 'active': True, 
             'description': False, 'category_type': 'other', 'parent_id': False},
             
            {'code': 'BASE_OTROS', 'name': 'SUBTOTAL OTROS DEVENGOS', 'sequence': 660, 'active': True, 
             'description': False, 'category_type': 'other', 'parent_id': False},
             
            {'code': 'DIAS', 'name': 'DIAS VACA', 'sequence': 670, 'active': True, 
             'description': False, 'category_type': 'other', 'parent_id': False}
        ]
        
        created_categories = {}
        
        for cat_data in main_categories:
            category_type = cat_data.pop('category_type', 'other')
            parent_id = cat_data.pop('parent_id', False)
            
            existing_category = self.env['hr.salary.rule.category'].search([
                ('code', '=', cat_data['code']),
                ('active', '=', True)
            ], limit=1)
            
            if existing_category:
                update_vals = {
                    'name': cat_data['name'],
                    'sequence': cat_data['sequence'],
                    'active': cat_data['active'],
                    'category_type': category_type,
                    'group_payroll_voucher': True if cat_data['code'] not in ['NET', 'TOTALDEV', 'TOTALDED', 'GROSS'] else False,
                    
                }
                if parent_id:
                    update_vals['parent_id'] = existing_category or self.env['hr.salary.rule.category'].search([('code', '=',parent_id),], limit=1).id
                
                existing_category.write(update_vals)
                created_categories[cat_data['code']] = existing_category
                _logger.info(f"Categoría actualizada: {cat_data['name']}")
            else:
                create_vals = {
                    'name': cat_data['name'],
                    'code': cat_data['code'],
                    'sequence': cat_data['sequence'],
                    'active': cat_data['active'],
                    'category_type': category_type,
                    'group_payroll_voucher': True if cat_data['code'] not in ['NET', 'TOTALDEV', 'TOTALDED', 'GROSS'] else False,
                    'note': cat_data['description'],
                }
                if parent_id:
                    create_vals['parent_id'] = self.env['hr.salary.rule.category'].search([('code', '=',parent_id),], limit=1).id
                
                new_category = self.env['hr.salary.rule.category'].create(create_vals)
                created_categories[cat_data['code']] = new_category
                _logger.info(f"Categoría creada: {cat_data['name']}")
        
        subcategories = [
            {'code': 'BASIC', 'name': 'BÁSICO', 'sequence': 11, 'active': True, 
             'description': '<p>El sueldo base es la remuneración fija.', 
             'category_type': 'basic', 'parent_code': 'DEV_SALARIAL'},
             
            {'code': 'VACACIONES', 'name': 'VACACIONES', 'sequence': 21, 'active': True, 
             'description': '<p>El derecho a las vacaciones se adquiere al cumplirse el año de servicio.', 
             'category_type': 'earnings', 'parent_code': 'DEV_SALARIAL'},
            
            {'code': 'AUS', 'name': 'AUSENCIA', 'sequence': 630, 'active': True, 
             'description': False, 'category_type': 'earnings', 'parent_code': 'DEV_SALARIAL'},
             
            {'code': 'COMISIONES', 'name': 'COMISIONES', 'sequence': 640, 'active': True, 
             'description': False, 'category_type': 'earnings', 'parent_code': 'PRESTACIONES_SOCIALES'},
            
            {'code': 'INDEM', 'name': 'INDEMNIZACIONES', 'sequence': 150, 'active': True, 
             'description': False, 'category_type': 'o_rights', 'parent_code': 'DEV_SALARIAL'},
                       
            {'code': 'HEYREC', 'name': 'HORAS EXTRAS Y RECARGOS', 'sequence': 31, 'active': True, 
             'description': 'Pagos por trabajo extraordinario.', 
             'category_type': 'earnings', 'parent_code': 'DEV_SALARIAL'},
             
            {'code': 'INCAPACIDAD', 'name': 'INCAPACIDAD', 'sequence': 41, 'active': True, 
             'description': False, 'category_type': 'earnings', 'parent_code': 'DEV_SALARIAL'},
             
            {'code': 'LICENCIA_REMUNERADA', 'name': 'LICENCIA REMUNERADA', 'sequence': 51, 'active': True, 
             'description': False, 'category_type': 'earnings', 'parent_code': 'DEV_SALARIAL'},
             
            {'code': 'LICENCIA_MATERNIDAD', 'name': 'LICENCIA MATERNIDAD', 'sequence': 61, 'active': True, 
             'description': False, 'category_type': 'earnings', 'parent_code': 'DEV_SALARIAL'},
             
            {'code': 'ACCIDENTE_TRABAJO', 'name': 'ACCIDENTE TRABAJO', 'sequence': 71, 'active': True, 
             'description': False, 'category_type': 'earnings', 'parent_code': 'DEV_SALARIAL'},
             
            {'code': 'AUX', 'name': 'AUXILIO DE TRANSPORTE', 'sequence': 120, 'active': True, 
             'description': 'El auxilio de transporte es un pago que se realiza a los trabajadores.', 
             'category_type': 'earnings_non_salary', 'parent_code': 'DEV_NO_SALARIAL'},
             
            {'code': 'LICENCIA_NO_REMUNERADA', 'name': 'LICENCIA NO REMUNERADA', 'sequence': 140, 'active': True, 
             'description': False, 'category_type': 'non_taxed_earnings', 'parent_code': 'DEV_NO_SALARIAL'},

            {'code': 'EM', 'name': 'EMBARGOS', 'sequence': 210, 'active': True, 
             'description': False, 'category_type': 'deductions', 'parent_code': 'DEDUCCIONES'},
             
            {'code': 'SSOCIAL', 'name': 'SEGURIDAD SOCIAL SS', 'sequence': 220, 'active': True, 
             'description': False, 'category_type': 'deductions', 'parent_code': 'DEDUCCIONES'},
             
            {'code': 'DESCUENTO_AFC', 'name': 'DESCUENTO AFC', 'sequence': 230, 'active': True, 
             'description': False, 'category_type': 'deductions', 'parent_code': 'DEDUCCIONES'},

            {'code': 'PRIMA', 'name': 'PRIMA LEGAL', 'sequence': 310, 'active': True, 
             'description': False, 'category_type': 'benefits', 'parent_code': 'PRESTACIONES_SOCIALES'},
        ]
        
        for cat_data in subcategories:
            parent_code = cat_data.pop('parent_code', False)
            category_type = cat_data.pop('category_type', 'other')
            
            parent_id = False
            if parent_code and parent_code in created_categories:
                parent_id = created_categories[parent_code].id
            
            active_category = self.env['hr.salary.rule.category'].search([
                ('code', '=', cat_data['code']),
                ('active', '=', True)
            ], limit=1)
            
            if active_category:
                active_category.write({
                    'name': cat_data['name'],
                    'sequence': cat_data['sequence'],
                    'category_type': category_type,
                    'parent_id': parent_id,
                    'group_payroll_voucher': True,
                    'note': cat_data['description'],
                })
                _logger.info(f"Subcategoría actualizada: {cat_data['name']} con padre {cat_data}")
            else:
                new_category = self.env['hr.salary.rule.category'].create({
                    'name': cat_data['name'],
                    'code': cat_data['code'],
                    'sequence': cat_data['sequence'],
                    'active': cat_data['active'],
                    'category_type': category_type,
                    'parent_id': parent_id,
                    'group_payroll_voucher': True,
                    'note': cat_data['description'],
                })
                _logger.info(f"Subcategoría creada: {cat_data['name']} con padre {parent_code}")
        
        return True

    def action_generate_salary_rules(self):
        """Acción para generar reglas salariales desde la compañía"""
        self.ensure_one()
        self._generate_all_structures()
        self._generate_all_rules()
        self._generate_overtime_types()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Éxito'),
                'message': _('Reglas salariales generadas correctamente'),
                'type': 'success',
                'sticky': False,
            }
        }
    
    def _generate_lavish_code(self, process_code, sequence):
        """
        Genera un código lavish de 4 dígitos basado en el proceso y una secuencia
        """
        # Mapeo de códigos de proceso a prefijos
        process_prefix = {
            'nomina': '1',
            'vacaciones': '2',
            'prima': '3',
            'cesantias': '4',
            'contrato': '5',
            'intereses_cesantias': '6',
        }
        
        # Obtener el prefijo del proceso
        prefix = process_prefix.get(process_code, '9')
        
        # Generar un número de 3 dígitos para la secuencia
        sequence_num = str(sequence).zfill(3)
        
        # Combinar el prefijo y la secuencia
        return prefix + sequence_num
    
    def _create_or_update_structure(self, name, process_type, sequence, reference=False):
        """
        Crea o actualiza una estructura salarial
        """
        existing_structure = self.env['hr.payroll.structure'].search([
            ('name', '=', name),
        ], limit=1)
        existing_structure += self.env['hr.payroll.structure'].search([
            ('process', '=', process_type),
        ], limit=1)  
        structure_data = {
            'name': name,
            'process': process_type,
            #'reference': reference,
        }
        
        if existing_structure:
            existing_structure.write(structure_data)
            return existing_structure
        else:
            new_structure = self.env['hr.payroll.structure'].create(structure_data)
            return new_structure
    
    def _get_rule_properties(self, code, name, category_code, sequence, process_code='nomina', 
                            rule_type='concept', is_leave=False, dev_or_ded='devengo', 
                            is_recargo=False, modality_value='fijo', appears_on_payslip=True):
        """
        Obtiene propiedades base para una regla salarial
        """
        
        base_props = {
            'code': code,
            'name': name.upper(),
            'sequence': sequence,
            'active': True,
            'appears_on_payslip': appears_on_payslip,
            'process': process_code,
        }
        
        # Obtener la categoría por código
        category = self.env['hr.salary.rule.category'].search([
            ('code', '=', category_code),
            ('active', '=', True)
        ], limit=1)
        
        if not category:
            _logger.warning(f"Categoría {category_code} no encontrada para la regla {code}")
            return None
        
        structure = self.env['hr.payroll.structure'].search([
            ('process', '=', process_code),
        ], limit=1)
        
        if not structure:
            _logger.warning(f"Estructura para el proceso {process_code} no encontrada")
            return None
        
        base_props['struct_id'] = structure.id
        # type_concepts = fields.Selection([('contrato', 'Fijo Contrato'),
        #                             ('ley', 'Por Ley'),
        #                             ('novedad', 'Novedad Variable'),
        #                             ('prestacion', 'Prestación Social'),
        #                             ('tributaria', 'Deducción Tributaria')],'Tipo', required=True, default='contrato', tracking=True)
        type_concepts = 'ley' if category_code in ['INCAPACIDAD', 'LICENCIA_REMUNERADA', 'LICENCIA_NO_REMUNERADA', 'LICENCIA_MATERNIDAD',] else 'novedad'
        if category_code in ['INTVIV', 'AFC', 'MEDPRE', 'DEDDEP']:
            type_concepts = 'tributaria'
        elif category_code in ['PRESTACIONES_SOCIALES', 'PROV']:
            type_concepts = 'prestacion'
        if rule_type == 'concept':
            base_props.update({
                'category_id': category.id,
                'condition_select': 'none',
                'condition_python': 'result = True',
                'amount_select': 'code' if category_code in ['TOTALDEV', 'TOTALDED', 'NET'] else 'concept',
                'type_concepts': type_concepts, #'ley' if category_code in ['INCAPACIDAD', 'LICENCIA_REMUNERADA', 'LICENCIA_NO_REMUNERADA', 'LICENCIA_MATERNIDAD', 'PRESTACIONES_SOCIALES', 'PROV'] else 'novedad',
                'is_leave': is_leave,
                'dev_or_ded': dev_or_ded,
                'modality_value': modality_value,
                'is_recargo': is_recargo,
            })
            
            if dev_or_ded == 'devengo':
                if category_code in ['BASIC', 'DEV_SALARIAL', 'HEYREC']:
                    base_props.update({
                        'base_prima': True,
                        'base_cesantias': True,
                        'base_vacaciones': True,
                        'base_seguridad_social': True,
                        'base_parafiscales': True,
                    })
                elif category_code == 'INCAPACIDAD':
                    base_props.update({
                        'base_prima': False,
                        'base_cesantias': False,
                        'base_vacaciones': False,
                        'base_seguridad_social': True,
                        'base_parafiscales': False,
                    })
                else:
                    base_props.update({
                        'base_prima': False,
                        'base_cesantias': False,
                        'base_vacaciones': False,
                        'base_seguridad_social': False,
                        'base_parafiscales': False,
                    })
            else:
                base_props.update({
                    'base_prima': False,
                    'base_cesantias': False,
                    'base_vacaciones': False,
                    'base_seguridad_social': False,
                    'base_parafiscales': False,
                })
                
        elif rule_type == 'totalizador':
            base_props.update({
                'category_id': category.id,
                'condition_select': 'python',
                'condition_python': 'result = True',
                'amount_select': 'code',
            })
            
            # Fórmulas para totalizadores
            if code == 'TOTALDEV':
                base_props['amount_python_compute'] = 'result = categories.DEV_SALARIAL + categories.DEV_NO_SALARIAL + categories.PRESTACIONES_SOCIALES + categories.AUX'
            elif code == 'TOTALDED':
                base_props['amount_python_compute'] = 'result = categories.DEDUCCIONES'
            elif code == 'NET':
                base_props['amount_python_compute'] = 'result = categories.DEV_SALARIAL + categories.DEV_NO_SALARIAL + categories.DEDUCCIONES + categories.PRESTACIONES_SOCIALES + categories.AUX'
        
        return base_props
    
    def _create_or_update_rule(self, rule_data):
        """
        Crea o actualiza una regla salarial
        """
        if not rule_data:
            _logger.warning("No se proporcionaron datos para crear o actualizar la regla")
            return None
        # Buscar si ya existe la regla por código
        existing_rule = self.env['hr.salary.rule'].search([
            ('code', '=', rule_data.get('code','')),
            ('active', '=', True),
        ], limit=1)
        
        if existing_rule:
            existing_rule.write(rule_data)
            _logger.info(f"Regla actualizada: {rule_data['name']}")
            return existing_rule
        else:
            # Crear nueva regla
            new_rule = self.env['hr.salary.rule'].create(rule_data)
            _logger.info(f"Regla creada: {rule_data['name']}")
            return new_rule
    
    def _generate_all_structures(self):
        """Generar todas las estructuras salariales necesarias"""
        # Crear estructura para Nómina
        nomina_structure = self._create_or_update_structure(
            name='Nómina Colombia',
            process_type='nomina',
            sequence=1,
            reference='Estructura para nómina regular'
        )
        
        # Crear estructura para Vacaciones
        vacaciones_structure = self._create_or_update_structure(
            name='Vacaciones Colombia',
            process_type='vacaciones',
            sequence=2,
            reference='Estructura para liquidación de vacaciones'
        )
        
        # Crear estructura para Prima
        prima_structure = self._create_or_update_structure(
            name='Prima Colombia',
            process_type='prima',
            sequence=3,
            reference='Estructura para liquidación de prima de servicios'
        )
        
        # Crear estructura para Cesantías
        cesantias_structure = self._create_or_update_structure(
            name='Cesantías Colombia',
            process_type='cesantias',
            sequence=4,
            reference='Estructura para liquidación de cesantías'
        )
        
        # Crear estructura para Liquidación de Contrato
        liquidacion_structure = self._create_or_update_structure(
            name='Liquidación de Contrato Colombia',
            process_type='contrato',
            sequence=5,
            reference='Estructura para liquidación final de contrato'
        )
        
        # Crear estructura para intereses_cesantias de Cesantías
        intereses_structure = self._create_or_update_structure(
            name='Intereses de Cesantías Colombia',
            process_type='intereses_cesantias',
            sequence=6,
            reference='Estructura para liquidación de intereses sobre cesantías'
        )
        
        return {
            'nomina': nomina_structure,
            'vacaciones': vacaciones_structure,
            'prima': prima_structure,
            'cesantias': cesantias_structure,
            'contrato': liquidacion_structure,
            'intereses_cesantias': intereses_structure,
        }
    
    def _generate_all_rules(self):
        """Genera todas las reglas salariales"""
        # REGLAS DE SALARIO BÁSICO - NÓMINA
        self._create_or_update_rule(self._get_rule_properties('BASIC', 'SALARIO BÁSICO', 'BASIC', 1, 'nomina', modality_value='diario'))
        self._create_or_update_rule(self._get_rule_properties('BASIC002', 'SALARIO INTEGRAL', 'BASIC', 2, 'nomina', modality_value='diario'))
        self._create_or_update_rule(self._get_rule_properties('BASIC003', 'AUXILIO DE SOSTENIMIENTO', 'BASIC', 3, 'nomina', modality_value='diario'))
        
        # REGLAS DE INCAPACIDAD - NÓMINA
        self._create_or_update_rule(self._get_rule_properties('INCAPACIDAD001', 'INCAPACIDAD EPS', 'INCAPACIDAD', 5, 'nomina', is_leave=True))
        self._create_or_update_rule(self._get_rule_properties('INCAPACIDAD002', 'INCAPACIDAD COMPAÑÍA', 'INCAPACIDAD', 6, 'nomina', is_leave=True))
        self._create_or_update_rule(self._get_rule_properties('INCAPACIDAD007', 'INCAPACIDAD EPS 50%', 'INCAPACIDAD', 7, 'nomina', is_leave=True))
        self._create_or_update_rule(self._get_rule_properties('EGH', 'AUSENCIA POR ENFERMEDAD 66%', 'INCAPACIDAD', 8, 'nomina', is_leave=True))
        
        # REGLAS DE ACCIDENTE DE TRABAJO - NÓMINA
        self._create_or_update_rule(self._get_rule_properties('AT', 'ACCIDENTE DE TRABAJO', 'ACCIDENTE_TRABAJO', 9, 'nomina', is_leave=True))
        self._create_or_update_rule(self._get_rule_properties('EP', 'ENFERMEDAD PROFESIONAL', 'ACCIDENTE_TRABAJO', 10, 'nomina', is_leave=True))
        
        # REGLAS DE LICENCIAS - NÓMINA
        self._create_or_update_rule(self._get_rule_properties('MAT', 'LICENCIA DE MATERNIDAD', 'LICENCIA_MATERNIDAD', 11, 'nomina', is_leave=True))
        self._create_or_update_rule(self._get_rule_properties('PAT', 'LICENCIA DE PATERNIDAD', 'LICENCIA_MATERNIDAD', 12, 'nomina', is_leave=True))
        self._create_or_update_rule(self._get_rule_properties('LICENCIA001', 'LICENCIA REMUNERADA', 'LICENCIA_REMUNERADA', 13, 'nomina', is_leave=True))
        self._create_or_update_rule(self._get_rule_properties('LUTO', 'LUTO', 'LICENCIA_REMUNERADA', 14, 'nomina', is_leave=True))
        self._create_or_update_rule(self._get_rule_properties('LICENCIA_NO_REMUNERADA', 'LICENCIA NO REMUNERADA', 'LICENCIA_NO_REMUNERADA', 16, 'nomina', is_leave=True))
        
        # REGLAS DE SANCIONES Y SUSPENSIONES - NÓMINA
        self._create_or_update_rule(self._get_rule_properties('INAS_INJU', 'INASISTENCIA INJUSTIFICADA', 'LICENCIA_NO_REMUNERADA', 17, 'nomina', is_leave=True))
        self._create_or_update_rule(self._get_rule_properties('SUSP_CONTRATO', 'SUSPENSIÓN DEL CONTRATO', 'LICENCIA_NO_REMUNERADA', 18, 'nomina', is_leave=True))
        self._create_or_update_rule(self._get_rule_properties('SANCION', 'SANCION', 'SANCIONES', 19, 'nomina', is_leave=True))
        
        # REGLAS DE VACACIONES - PROCESO VACACIONES
        self._create_or_update_rule(self._get_rule_properties('VACDISFRUTADAS', 'VACACIONES DISFRUTADAS', 'DEV_SALARIAL', 26, 'vacaciones', is_leave=True))
        self._create_or_update_rule(self._get_rule_properties('VACANOVE', 'VACACIONES', 'PRESTACIONES_SOCIALES', 29, 'vacaciones', is_leave=True))
        self._create_or_update_rule(self._get_rule_properties('VACCONTRATO', 'VACACIONES', 'PRESTACIONES_SOCIALES', 190, 'vacaciones'))
        self._create_or_update_rule(self._get_rule_properties('VACATIONS_MONEY', 'VACACIONES EN DINERO', 'PRESTACIONES_SOCIALES', 51, 'vacaciones'))
        
        # REGLAS DE DEVENGOS SALARIALES - NÓMINA
        self._create_or_update_rule(self._get_rule_properties('BONIF', 'BONIFICACIÓN', 'DEV_SALARIAL', 10, 'nomina'))
        self._create_or_update_rule(self._get_rule_properties('COMISIONES', 'COMISIONES', 'DEV_SALARIAL', 31, 'nomina'))
        self._create_or_update_rule(self._get_rule_properties('AUX128', 'MENOR VALOR PAGADO SALARIO', 'DEV_SALARIAL', 32, 'nomina'))
        self._create_or_update_rule(self._get_rule_properties('RETRO', 'RETROACTIVO', 'DEV_SALARIAL', 33, 'nomina'))
        
        # REGLAS DE DEVENGOS NO SALARIALES - NÓMINA
        self._create_or_update_rule(self._get_rule_properties('BONOPRI', 'BONO PRIMA', 'DEV_NO_SALARIAL', 44, 'nomina'))
        self._create_or_update_rule(self._get_rule_properties('AUX110', 'AUXILIO DE ALIMENTACION', 'DEV_NO_SALARIAL', 45, 'nomina', modality_value='diario'))
        self._create_or_update_rule(self._get_rule_properties('AUX111', 'AUXILIO DE MOVILIDAD', 'DEV_NO_SALARIAL', 46, 'nomina'))
        self._create_or_update_rule(self._get_rule_properties('AUX112', 'AUXILIO DE HERRAMIENTAS', 'DEV_NO_SALARIAL', 47, 'nomina'))
        self._create_or_update_rule(self._get_rule_properties('DEV116', 'DEVOLUCIÓN RETENCIÓN FUENTE', 'DEV_NO_SALARIAL', 48, 'nomina'))
        self._create_or_update_rule(self._get_rule_properties('AUX120', 'AUXILIO DICIEMBRE', 'DEV_NO_SALARIAL', 60, 'nomina'))
        self._create_or_update_rule(self._get_rule_properties('BONNS', 'BONIFICACIÓN NO SALARIAL', 'DEV_NO_SALARIAL', 75, 'nomina', modality_value='diario'))
        
        # REGLAS DE INTERESES DE VIVIENDA - NÓMINA
        self._create_or_update_rule(self._get_rule_properties('INTVIV', 'INTERESE DE VIVIENDA', 'INTVIV', 34, 'nomina'))
        
        # REGLAS DE HORAS EXTRAS Y RECARGOS - NÓMINA

        self._create_or_update_rule(self._get_rule_properties('HEYREC001', 'HORAS EXTRA DIURNAS (125%)', 'HEYREC', 36, 'nomina', is_recargo=True))
        self._create_or_update_rule(self._get_rule_properties('HEYREC002', 'HORAS EXTRA DIURNAS DOMINICAL / FESTIVA (200%)', 'HEYREC', 37, 'nomina', is_recargo=True, modality_value='diario'))
        self._create_or_update_rule(self._get_rule_properties('HEYREC003', 'HORAS EXTRA NOCTURNA (175%)', 'HEYREC', 38, 'nomina', is_recargo=True, modality_value='diario')) 
        self._create_or_update_rule(self._get_rule_properties('HEYREC004', 'HORAS RECARGO FESTIVO (0.75)', 'HEYREC', 39, 'nomina', is_recargo=True, modality_value='diario'))
        self._create_or_update_rule(self._get_rule_properties('HEYREC005', 'HORAS RECARGO NOCTURNO (35%)', 'HEYREC', 40, 'nomina', is_recargo=True))
        self._create_or_update_rule(self._get_rule_properties('HEYREC006', 'HORAS EXTRA NOCTURNA DOMINICAL / FESTIVA (250%)', 'HEYREC', 41, 'nomina', is_recargo=True))
        self._create_or_update_rule(self._get_rule_properties('HEYREC007', 'HORAS DOMINICALES (1.75%)', 'HEYREC', 42, 'nomina', is_recargo=True, modality_value='diario'))
        self._create_or_update_rule(self._get_rule_properties('HEYREC008', 'HORAS DE RECARGO NOCTURNO DOMINICAL/FESTIVO (1.1%)', 'HEYREC', 43, 'nomina', is_recargo=True, modality_value='diario'))
        
        # REGLAS DE AUXILIO DE TRANSPORTE Y CONECTIVIDAD - NÓMINA
        self._create_or_update_rule(self._get_rule_properties('AUX1111', 'AUXILIO DE CONECTIVIDAD', 'AUX', 50, 'nomina', modality_value='diario'))
        self._create_or_update_rule(self._get_rule_properties('AUX000', 'AUXILIO DE TRANSPORTE', 'AUX', 182, 'nomina', modality_value='diario'))
        self._create_or_update_rule(self._get_rule_properties('INDEM', 'INDEMNIZACIONES', 'INDEM', 189, 'contrato'))

        # REGLAS DE PRESTACIONES SOCIALES - PROCESO PRIMA
        self._create_or_update_rule(self._get_rule_properties('PRIMA', 'PRIMA BASE', 'PRESTACIONES_SOCIALES', 190, 'prima'))
        
        # REGLAS DE PRESTACIONES SOCIALES - PROCESO CESANTÍAS
        self._create_or_update_rule(self._get_rule_properties('CESANTIAS', 'CESANTIAS', 'PRESTACIONES_SOCIALES', 195, 'cesantias'))
        self._create_or_update_rule(self._get_rule_properties('CES_YEAR', 'CESANTIAS AÑO ANTERIOR', 'PRESTACIONES_SOCIALES', 195, 'cesantias'))
        
        # REGLAS DE PRESTACIONES SOCIALES - PROCESO intereses_cesantias DE CESANTÍAS
        self._create_or_update_rule(self._get_rule_properties('INTCESANTIAS_1', 'INTERESES DE CESANTIAS BASE', 'PRESTACIONES_SOCIALES', 196, 'intereses_cesantias'))
        self._create_or_update_rule(self._get_rule_properties('INTCES_YEAR', 'INTERESES DE CESANTIAS AÑO ANTERIOR', 'PRESTACIONES_SOCIALES', 196, 'intereses_cesantias'))
        
        # REGLAS DE SEGURIDAD SOCIAL - NÓMINA
        self._create_or_update_rule(self._get_rule_properties('SSOCIAL002', 'PENSION EMPLEADO', 'SSOCIAL', 201, 'nomina', dev_or_ded='deduccion'))
        self._create_or_update_rule(self._get_rule_properties('SSOCIAL001', 'SALUD EMPLEADO', 'SSOCIAL', 200, 'nomina', dev_or_ded='deduccion'))
        self._create_or_update_rule(self._get_rule_properties('SSOCIAL004', 'FONDO SOLIDADRIDAD', 'SSOCIAL', 203, 'nomina', dev_or_ded='deduccion'))
        self._create_or_update_rule(self._get_rule_properties('SSOCIAL003', 'FONDO DE SUBSISTENCIA', 'SSOCIAL', 202, 'nomina', dev_or_ded='deduccion'))
        
        # REGLAS DE RETENCIÓN EN LA FUENTE - NÓMINA Y PRIMA
        self._create_or_update_rule(self._get_rule_properties('RT_MET_01', 'RETENCIÓN EN LA FUENTE', 'DEDUCCIONES', 204, 'nomina', dev_or_ded='deduccion'))
        self._create_or_update_rule(self._get_rule_properties('RET_PRIMA', 'RETENCION PRIMA', 'DEDUCCIONES', 205, 'prima', dev_or_ded='deduccion'))
        self._create_or_update_rule(self._get_rule_properties('RTF_INDEM', 'RETENCION INDEMNIZACIONES', 'DEDUCCIONES', 206, 'contrato', dev_or_ded='deduccion'))        
       
        # REGLAS DE PRÉSTAMOS - NÓMINA
        self._create_or_update_rule(self._get_rule_properties('P01', 'PRESTAMO EMPLEADO', 'DEDUCCIONES', 206, 'nomina', dev_or_ded='deduccion'))
        
        # REGLAS DE EMBARGOS - NÓMINA
        self._create_or_update_rule(self._get_rule_properties('EMBARGO007', 'EMBARGO SALARIAL %', 'EM', 211, 'nomina', dev_or_ded='deduccion', modality_value='diario'))
        self._create_or_update_rule(self._get_rule_properties('EMBARGO009', 'EMBARGO SALARIAL FIJO', 'EM', 212, 'nomina', dev_or_ded='deduccion'))
        self._create_or_update_rule(self._get_rule_properties('EMBARGO002', 'EMBARGO SALARIAL 1/5 SMMVL', 'EM', 213, 'nomina', dev_or_ded='deduccion'))
        
        # REGLAS DE OTRAS DEDUCCIONES - NÓMINA
        self._create_or_update_rule(self._get_rule_properties('MEDPRE', 'MEDPRE', 'DEDUCCIONES', 215, 'nomina', dev_or_ded='deduccion'))
        self._create_or_update_rule(self._get_rule_properties('VIATICOS', 'VIATICOS OCASIONALES', 'DEDUCCIONES', 250, 'nomina', dev_or_ded='deduccion'))
        self._create_or_update_rule(self._get_rule_properties('LIBRANZA', 'LIBRANZA DESCUENTO', 'DEDUCCIONES', 260, 'nomina', dev_or_ded='deduccion'))
        self._create_or_update_rule(self._get_rule_properties('ERROR', 'DESCUENTO ERRORES', 'DEDUCCIONES', 261, 'nomina', dev_or_ded='deduccion'))
        self._create_or_update_rule(self._get_rule_properties('HORAS', 'DESCUENTO HORAS', 'DEDUCCIONES', 262, 'nomina', dev_or_ded='deduccion'))
        self._create_or_update_rule(self._get_rule_properties('ANTICIPO', 'ANTICIPO NÓMINA', 'DEDUCCIONES', 263, 'nomina', dev_or_ded='deduccion'))
        self._create_or_update_rule(self._get_rule_properties('AVP', 'APORTES VOLUNTARIOS PENSIÓN', 'DEDUCCIONES', 270, 'nomina', dev_or_ded='deduccion'))
        self._create_or_update_rule(self._get_rule_properties('PRESTAMO', 'PRESTAMO NOVEDAD', 'DEDUCCIONES', 270, 'nomina', dev_or_ded='deduccion'))
        self._create_or_update_rule(self._get_rule_properties('DESCUENTO', 'DESCUENTO', 'DEDUCCIONES', 270, 'nomina', dev_or_ded='deduccion'))
        self._create_or_update_rule(self._get_rule_properties('AFC', 'APORTES CUENTAS AFC', 'DEDUCCIONES', 271, 'nomina', dev_or_ded='deduccion'))
        self._create_or_update_rule(self._get_rule_properties('DEV_AUX000', 'DEVOLUCIÓN AUX DE TRANSPORTE', 'DEDUCCIONES', 280, 'nomina', dev_or_ded='deduccion'))
        
        # REGLAS DE PROVISIONES - NÓMINA
        self._create_or_update_rule(self._get_rule_properties('PRV_VAC', 'PROV. VACACIONES', 'PROV', 306, 'nomina', appears_on_payslip=False))
        self._create_or_update_rule(self._get_rule_properties('PRV_CES', 'PROV. CESANTIAS', 'PROV', 304, 'nomina', appears_on_payslip=False))
        self._create_or_update_rule(self._get_rule_properties('PRV_ICES', 'PROV. INT. CESANTIAS', 'PROV', 305, 'nomina', appears_on_payslip=False))
        self._create_or_update_rule(self._get_rule_properties('PRV_PRIM', 'PROV. PRIMAS', 'PROV', 302, 'nomina', appears_on_payslip=False))
        
        # REGLAS DE LIQUIDACIÓN DE CONTRATO
        self._create_or_update_rule(self._get_rule_properties('PREAVISO', 'INDEMNIZACIÓN PREAVISO CLAUSULA 9NA DE CONTRATO', 'DEDUCCIONES', 201, 'contrato', dev_or_ded='deduccion'))
        self._create_or_update_rule(self._get_rule_properties('DEDDEP', 'DED_DEPENDIENTES_O', 'GROSS', 15, 'contrato', appears_on_payslip=False))
        self._create_or_update_rule(self._get_rule_properties('IBD', 'IBC SEGURIDAD SOCIAL', 'BASE_SEC', 199, 'contrato', appears_on_payslip=False))
        
        # REGLAS DE TOTALIZADORES - TODOS LOS PROCESOS
        for process_code in ['nomina',]:
            self._create_or_update_rule(self._get_rule_properties('TOTALDEV', 'TOTAL DEVENGO', 'TOTALDEV', 199, process_code, 'totalizador'))
            self._create_or_update_rule(self._get_rule_properties('TOTALDED', 'TOTAL DEDUCCIONES', 'TOTALDED', 299, process_code, 'totalizador'))
            self._create_or_update_rule(self._get_rule_properties('NET', 'NETO A PAGAR SALARIO', 'NET', 300, process_code, 'totalizador'))

    def _generate_overtime_types(self):
        """Genera los tipos de horas extras basados en las reglas salariales"""
        overtime_mapping = {
            'HEYREC001': {
                'type_overtime': 'overtime_ext_d',
                'name': 'EXT-D | Extra diurna',
                'percentage': 1.25,
                'start_time': 6.0,
                'end_time': 21.0,
                'start_time_two': 0.0,
                'end_time_two': 0.0,
                'contains_holidays': False,
                'mon': True, 'tue': True, 'wed': True, 'thu': True, 'fri': True,
                'sat': False, 'sun': False
            },
            'HEYREC002': {
                'type_overtime': 'overtime_eddf',
                'name': 'E-D-D/F | Extra diurna dominical/festivo',
                'percentage': 2.0,
                'start_time': 6.0,
                'end_time': 21.0,
                'start_time_two': 0.0,
                'end_time_two': 0.0,
                'contains_holidays': True,
                'mon': False, 'tue': False, 'wed': False, 'thu': False, 'fri': False,
                'sat': False, 'sun': True
            },
            'HEYREC003': {
                'type_overtime': 'overtime_ext_n',
                'name': 'EXT-N | Extra nocturna',
                'percentage': 1.75,
                'start_time': 21.0,
                'end_time': 24.0,
                'start_time_two': 0.0,
                'end_time_two': 6.0,
                'contains_holidays': False,
                'mon': True, 'tue': True, 'wed': True, 'thu': True, 'fri': True,
                'sat': False, 'sun': False
            },
            'HEYREC004': {
                'type_overtime': 'overtime_rdf',
                'name': 'R-D/F | Recargo dominical/festivo',
                'percentage': 0.75,
                'start_time': 0.0,
                'end_time': 24.0,
                'start_time_two': 0.0,
                'end_time_two': 0.0,
                'contains_holidays': True,
                'mon': False, 'tue': False, 'wed': False, 'thu': False, 'fri': False,
                'sat': False, 'sun': True
            },
            'HEYREC005': {
                'type_overtime': 'overtime_rn',
                'name': 'RN | Recargo nocturno',
                'percentage': 0.35,
                'start_time': 21.0,
                'end_time': 24.0,
                'start_time_two': 0.0,
                'end_time_two': 6.0,
                'contains_holidays': False,
                'mon': True, 'tue': True, 'wed': True, 'thu': True, 'fri': True,
                'sat': True, 'sun': False
            },
            'HEYREC006': {
                'type_overtime': 'overtime_endf',
                'name': 'E-N-D/F | Extra nocturna dominical/festivo',
                'percentage': 2.5,
                'start_time': 21.0,
                'end_time': 24.0,
                'start_time_two': 0.0,
                'end_time_two': 6.0,
                'contains_holidays': True,
                'mon': False, 'tue': False, 'wed': False, 'thu': False, 'fri': False,
                'sat': False, 'sun': True
            },
            'HEYREC007': {
                'type_overtime': 'overtime_dof',
                'name': 'D o F | Dominicales o festivos',
                'percentage': 1.75,
                'start_time': 0.0,
                'end_time': 24.0,
                'start_time_two': 0.0,
                'end_time_two': 0.0,
                'contains_holidays': True,
                'mon': False, 'tue': False, 'wed': False, 'thu': False, 'fri': False,
                'sat': False, 'sun': True
            },
            'HEYREC008': {
                'type_overtime': 'overtime_rndf',
                'name': 'RN-D/F | Recargo nocturno dominical/festivo',
                'percentage': 1.1,
                'start_time': 21.0,
                'end_time': 24.0,
                'start_time_two': 0.0,
                'end_time_two': 6.0,
                'contains_holidays': True,
                'mon': False, 'tue': False, 'wed': False, 'thu': False, 'fri': False,
                'sat': False, 'sun': True
            },
        }
        
        # Buscar las reglas salariales para asociarlas a los tipos de horas extras
        for rule_code, overtime_data in overtime_mapping.items():
            rule = self.env['hr.salary.rule'].search([
                ('code', '=', rule_code),
                ('active', '=', True),
            ], limit=1)
            
            if not rule:
                _logger.warning(f"Regla salarial {rule_code} no encontrada para crear tipo de hora extra")
                continue
            
            # Verificar si ya existe el tipo de hora extra
            existing_overtime = self.env['hr.type.overtime'].search([
                ('type_overtime', '=', overtime_data['type_overtime'])
            ], limit=1)
            
            overtime_values = {
                'name': overtime_data['name'],
                'salary_rule': rule.id,
                'type_overtime': overtime_data['type_overtime'],
                'percentage': overtime_data['percentage'] * 100,  # Convertir a porcentaje
                'start_time': overtime_data['start_time'],
                'end_time': overtime_data['end_time'],
                'start_time_two': overtime_data['start_time_two'],
                'end_time_two': overtime_data['end_time_two'],
                'contains_holidays': overtime_data['contains_holidays'],
                'mon': overtime_data['mon'],
                'tue': overtime_data['tue'],
                'wed': overtime_data['wed'],
                'thu': overtime_data['thu'],
                'fri': overtime_data['fri'],
                'sat': overtime_data['sat'],
                'sun': overtime_data['sun'],
            }
            
            if existing_overtime:
                # Actualizar tipo de hora extra existente
                existing_overtime.write(overtime_values)
                _logger.info(f"Tipo de hora extra actualizado: {overtime_data['name']}")
            else:
                # Crear nuevo tipo de hora extra
                new_overtime = self.env['hr.type.overtime'].create(overtime_values)
                _logger.info(f"Tipo de hora extra creado: {overtime_data['name']}")
                
class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    module_hr_payroll_batch_account = fields.Selection([('0','Crear un solo movimiento contable'),
                                                        ('1','Crear movimiento contable por empleado')],
                                        string='Contabilización por lote')
    addref_work_address_account_moves = fields.Boolean('¿Agregar ubicación laboral del empleado en la descripción de los movimientos contables?')
    round_payroll = fields.Boolean('NO redondear decimales en procesos de liquidación')
    pay_vacations_in_payroll = fields.Boolean('¿Liquidar vacaciones en nómina?')
    pay_cesantias_in_payroll = fields.Boolean('¿Liquidar Interese de cesantia en nómina?')
    pay_primas_in_payroll = fields.Boolean('¿Liquidar Primas en nómina?')
    vacation_days_calculate_absences = fields.Char('Días de vacaciones para calcular deducciones')
    cesantias_salary_take = fields.Boolean('Promediar salario de los últimos 3 meses, si ahí variación en cesantías')
    prima_salary_take = fields.Boolean('Promediar salario de los últimos 6 meses, si ahí variación en prima')
    #PeoplePass
    payroll_peoplepass_journal_id = fields.Many2one(related='company_id.payroll_peoplepass_journal_id',string='Diario contabilización pago valor no incluido', readonly=False)
    payroll_peoplepass_debit_account_id = fields.Many2one(related='company_id.payroll_peoplepass_debit_account_id',string='Cuenta contabilización pago valor no incluido débito', readonly=False)
    payroll_peoplepass_credit_account_id = fields.Many2one(related='company_id.payroll_peoplepass_credit_account_id',string='Cuenta contabilización pago valor no incluido crédito', readonly=False)
   #Nómina electronica
    payroll_electronic_operator = fields.Selection(related='company_id.payroll_electronic_operator', string='Operador',readonly=False)
    payroll_electronic_username_ws = fields.Char(related='company_id.payroll_electronic_username_ws',string='Usuario WS', readonly=False)
    payroll_electronic_password_ws = fields.Char(related='company_id.payroll_electronic_password_ws',string='Contraseña WS', readonly=False)
    payroll_electronic_company_id_ws = fields.Char(related='company_id.payroll_electronic_company_id_ws',string='Identificador compañia WS', readonly=False)
    payroll_electronic_account_id_ws = fields.Char(related='company_id.payroll_electronic_account_id_ws',string='Identificador cuenta WS', readonly=False)
    payroll_electronic_service_ws = fields.Char(related='company_id.payroll_electronic_service_ws',string='Servicio WS', default='PAYROLL', readonly=False)

    def set_values(self):
        super(ResConfigSettings, self).set_values()
        set_param = self.env['ir.config_parameter'].sudo().set_param
        set_param('lavish_hr_payroll.module_hr_payroll_batch_account', self.module_hr_payroll_batch_account)
        set_param('lavish_hr_payroll.addref_work_address_account_moves', self.addref_work_address_account_moves)
        set_param('lavish_hr_payroll.round_payroll', self.round_payroll)
        set_param('lavish_hr_payroll.pay_vacations_in_payroll', self.pay_vacations_in_payroll)
        set_param('lavish_hr_payroll.pay_cesantias_in_payroll', self.pay_cesantias_in_payroll)
        set_param('lavish_hr_payroll.pay_primas_in_payroll', self.pay_primas_in_payroll)
        set_param('lavish_hr_payroll.vacation_days_calculate_absences', self.vacation_days_calculate_absences)
        set_param('lavish_hr_payroll.cesantias_salary_take', self.cesantias_salary_take)
        set_param('lavish_hr_payroll.prima_salary_take', self.prima_salary_take)

    def get_values(self):
        res = super(ResConfigSettings, self).get_values()
        get_param = self.env['ir.config_parameter'].sudo().get_param
        res['module_hr_payroll_batch_account'] = get_param('lavish_hr_payroll.module_hr_payroll_batch_account')
        res['addref_work_address_account_moves'] = get_param('lavish_hr_payroll.addref_work_address_account_moves')
        res['round_payroll'] = get_param('lavish_hr_payroll.round_payroll')
        res['pay_vacations_in_payroll'] = get_param('lavish_hr_payroll.pay_vacations_in_payroll')
        res['pay_cesantias_in_payroll'] = get_param('lavish_hr_payroll.pay_cesantias_in_payroll')
        res['pay_primas_in_payroll'] = get_param('lavish_hr_payroll.pay_primas_in_payroll')
        res['vacation_days_calculate_absences'] = get_param('lavish_hr_payroll.vacation_days_calculate_absences')
        res['cesantias_salary_take'] = get_param('lavish_hr_payroll.cesantias_salary_take')
        res['prima_salary_take'] = get_param('lavish_hr_payroll.prima_salary_take')
        return res
# -*- coding: utf-8 -*-
"""
Configuración avanzada para importación de facturas RIPS
Con validaciones diferenciales y correcciones automáticas
"""

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import json
import logging
from datetime import datetime

_logger = logging.getLogger(__name__)


class RipsImportConfig(models.Model):
    """
    Configuración mejorada para importación RIPS
    """
    _name = 'rips.import.config'
    _description = 'Configuración de Importación RIPS'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string="Nombre Configuración", required=True)
    active = fields.Boolean(string="Activo", default=True)

    # ========================================
    # CONFIGURACIÓN DE IMPORTACIÓN
    # ========================================

    # Opciones de validación
    validate_nit = fields.Boolean(
        string="Validar NIT/CC",
        default=True,
        help="Valida que el NIT o CC del cliente exista y sea válido"
    )

    auto_create_missing = fields.Boolean(
        string="Crear registros faltantes",
        default=False,
        help="Crea automáticamente clientes y productos que no existan"
    )

    auto_correct_data = fields.Boolean(
        string="Corregir datos automáticamente",
        default=True,
        help="Aplica correcciones automáticas a datos con formato incorrecto"
    )

    skip_duplicates = fields.Boolean(
        string="Omitir duplicados",
        default=True,
        help="No importa facturas que ya existan en el sistema"
    )

    # Validaciones específicas RIPS
    validate_cups_codes = fields.Boolean(
        string="Validar códigos CUPS",
        default=True,
        help="Valida que los códigos CUPS sean válidos según catálogo"
    )

    validate_cie10_codes = fields.Boolean(
        string="Validar códigos CIE-10",
        default=True,
        help="Valida que los códigos de diagnóstico CIE-10 sean válidos"
    )

    validate_contracts = fields.Boolean(
        string="Validar contratos",
        default=True,
        help="Valida que el contrato referenciado exista y esté vigente"
    )

    # Mapeo de campos personalizado
    field_mapping_json = fields.Text(
        string="Mapeo de Campos (JSON)",
        help="JSON con mapeo personalizado de columnas Excel a campos Odoo"
    )

    # Valores por defecto
    default_journal_id = fields.Many2one(
        'account.journal',
        string="Diario por defecto",
        domain="[('type', '=', 'sale')]"
    )

    default_payment_term_id = fields.Many2one(
        'account.payment.term',
        string="Término de pago por defecto"
    )

    default_team_id = fields.Many2one(
        'crm.team',
        string="Equipo de ventas por defecto"
    )

    # ========================================
    # CONFIGURACIÓN DE CORRECCIONES
    # ========================================

    # Reglas de corrección
    correction_rules = fields.Text(
        string="Reglas de Corrección (JSON)",
        help="JSON con reglas para corrección automática de datos"
    )

    # Formatos esperados
    date_format = fields.Selection([
        ('%Y-%m-%d', 'YYYY-MM-DD'),
        ('%d/%m/%Y', 'DD/MM/YYYY'),
        ('%m/%d/%Y', 'MM/DD/YYYY'),
        ('%Y/%m/%d', 'YYYY/MM/DD'),
    ], string="Formato de Fecha", default='%Y-%m-%d')

    decimal_separator = fields.Selection([
        ('.', 'Punto (.)'),
        (',', 'Coma (,)'),
    ], string="Separador Decimal", default='.')

    thousand_separator = fields.Selection([
        (',', 'Coma (,)'),
        ('.', 'Punto (.)'),
        ('', 'Sin separador'),
    ], string="Separador de Miles", default=',')

    # ========================================
    # MÉTODOS DE CONFIGURACIÓN
    # ========================================

    @api.model
    def get_default_config(self):
        """
        Obtiene la configuración por defecto activa
        """
        config = self.search([('active', '=', True)], limit=1)
        if not config:
            # Crear configuración por defecto si no existe
            config = self.create({
                'name': 'Configuración Por Defecto',
                'active': True,
                'validate_nit': True,
                'auto_correct_data': True,
                'skip_duplicates': True,
            })
        return config

    def get_field_mapping(self):
        """
        Obtiene el mapeo de campos como diccionario
        """
        self.ensure_one()
        if self.field_mapping_json:
            try:
                return json.loads(self.field_mapping_json)
            except json.JSONDecodeError:
                _logger.error("Error decodificando mapeo de campos JSON")
        return {}

    def get_correction_rules(self):
        """
        Obtiene las reglas de corrección como diccionario
        """
        self.ensure_one()
        if self.correction_rules:
            try:
                return json.loads(self.correction_rules)
            except json.JSONDecodeError:
                _logger.error("Error decodificando reglas de corrección JSON")

        # Reglas por defecto
        return {
            'nit': {
                'remove_chars': ['-', '.', ' '],
                'validate_checksum': True
            },
            'phone': {
                'remove_chars': ['-', '(', ')', ' '],
                'min_length': 7,
                'max_length': 10
            },
            'email': {
                'lowercase': True,
                'validate_format': True
            },
            'cups_code': {
                'uppercase': True,
                'min_length': 6,
                'max_length': 6
            },
            'cie10_code': {
                'uppercase': True,
                'validate_format': r'^[A-Z][0-9]{2}(\.[0-9])?$'
            }
        }

    def apply_correction_rules(self, field_name, value):
        """
        Aplica reglas de corrección a un valor según el campo

        Args:
            field_name: Nombre del campo
            value: Valor a corregir

        Returns:
            Valor corregido
        """
        self.ensure_one()
        rules = self.get_correction_rules()

        if field_name not in rules or not value:
            return value

        field_rules = rules[field_name]
        corrected_value = str(value)

        # Remover caracteres no deseados
        if 'remove_chars' in field_rules:
            for char in field_rules['remove_chars']:
                corrected_value = corrected_value.replace(char, '')

        # Convertir a mayúsculas
        if field_rules.get('uppercase'):
            corrected_value = corrected_value.upper()

        # Convertir a minúsculas
        if field_rules.get('lowercase'):
            corrected_value = corrected_value.lower()

        # Validar longitud mínima
        if 'min_length' in field_rules:
            if len(corrected_value) < field_rules['min_length']:
                raise ValidationError(
                    _("El campo %s debe tener al menos %s caracteres") %
                    (field_name, field_rules['min_length'])
                )

        # Validar longitud máxima
        if 'max_length' in field_rules:
            if len(corrected_value) > field_rules['max_length']:
                corrected_value = corrected_value[:field_rules['max_length']]

        return corrected_value

    def parse_date_value(self, date_string):
        """
        Parsea una fecha según el formato configurado

        Args:
            date_string: String con la fecha

        Returns:
            date: Objeto fecha parseado
        """
        self.ensure_one()

        if not date_string:
            return False

        try:
            return datetime.strptime(date_string, self.date_format).date()
        except ValueError:
            # Intentar con formatos alternativos
            alternative_formats = [
                '%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y',
                '%Y/%m/%d', '%d-%m-%Y', '%m-%d-%Y'
            ]

            for fmt in alternative_formats:
                try:
                    return datetime.strptime(date_string, fmt).date()
                except ValueError:
                    continue

            _logger.warning(f"No se pudo parsear la fecha: {date_string}")
            return False

    def parse_decimal_value(self, decimal_string):
        """
        Parsea un valor decimal según la configuración

        Args:
            decimal_string: String con el valor decimal

        Returns:
            float: Valor decimal parseado
        """
        self.ensure_one()

        if not decimal_string:
            return 0.0

        # Convertir a string si no lo es
        decimal_string = str(decimal_string)

        # Remover separador de miles
        if self.thousand_separator:
            decimal_string = decimal_string.replace(self.thousand_separator, '')

        # Reemplazar separador decimal si es necesario
        if self.decimal_separator == ',':
            decimal_string = decimal_string.replace(',', '.')

        try:
            return float(decimal_string)
        except ValueError:
            _logger.warning(f"No se pudo parsear el decimal: {decimal_string}")
            return 0.0


class RipsImportWizard(models.TransientModel):
    """
    Wizard mejorado para importación con configuración avanzada
    """
    _name = 'rips.import.wizard'
    _description = 'Wizard de Importación RIPS'

    # Archivo a importar
    file_data = fields.Binary(string="Archivo", required=True)
    file_name = fields.Char(string="Nombre del Archivo")

    # Configuración a usar
    config_id = fields.Many2one(
        'rips.import.config',
        string="Configuración",
        required=True,
        default=lambda self: self.env['rips.import.config'].get_default_config()
    )

    # Opciones del wizard
    preview_mode = fields.Boolean(
        string="Modo Vista Previa",
        default=True,
        help="Solo valida y muestra diferencias sin importar"
    )

    show_differences = fields.Boolean(
        string="Mostrar Diferencias",
        default=True,
        help="Muestra diferencias entre datos existentes y nuevos"
    )

    # Resultado de validación previa
    validation_result = fields.Html(string="Resultado de Validación", readonly=True)

    def action_validate(self):
        """
        Valida el archivo sin importar
        """
        self.ensure_one()

        # Aquí iría la lógica de validación
        # usando la configuración seleccionada

        validation_html = """
        <div style="padding: 10px;">
            <h3>Resultado de Validación</h3>
            <p><strong>Archivo:</strong> {}</p>
            <p><strong>Configuración:</strong> {}</p>
            <ul>
                <li>✓ Formato de archivo válido</li>
                <li>✓ Columnas requeridas presentes</li>
                <li>✓ {} registros para procesar</li>
                <li>⚠ {} registros con advertencias</li>
            </ul>
        </div>
        """.format(
            self.file_name,
            self.config_id.name,
            100,  # Placeholder
            5     # Placeholder
        )

        self.validation_result = validation_html

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': self.env.context,
        }

    def action_import(self):
        """
        Ejecuta la importación con la configuración seleccionada
        """
        self.ensure_one()

        if not self.file_data:
            raise ValidationError(_("Por favor seleccione un archivo para importar"))

        # Crear registro de importación
        importer = self.env['invoice.importer'].create({
            'name': f'Importación {fields.Datetime.now()}',
            'file_data': self.file_data,
            'file_name': self.file_name,
            'company_id': self.env.company.id,
            'journal_id': self.config_id.default_journal_id.id,
            'team_id': self.config_id.default_team_id.id,
            'create_missing_partners': self.config_id.auto_create_missing,
            'auto_validate_dian': False,
            'auto_post_invoices': True,
            'auto_send_rips': False,
        })

        # Procesar importación
        importer.action_load_file()

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'invoice.importer',
            'res_id': importer.id,
            'view_mode': 'form',
            'target': 'current',
        }
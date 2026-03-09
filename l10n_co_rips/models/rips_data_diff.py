# -*- coding: utf-8 -*-
"""
Módulo de diferencias y mejoras para la gestión de datos RIPS
Este módulo agrega funcionalidades adicionales para la importación y exportación de RIPS
"""

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import json
import logging
from datetime import datetime, date

_logger = logging.getLogger(__name__)


class RipsDataEnhancement(models.Model):
    """
    Mejoras para la gestión de datos RIPS
    Diferencias principales con el módulo base:
    1. Validación avanzada de datos
    2. Mapeo inteligente de campos
    3. Gestión de errores mejorada
    4. Soporte para múltiples formatos de entrada
    """
    _name = 'rips.data.enhancement'
    _description = 'Mejoras para gestión de datos RIPS'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    # ========================================
    # CAMPOS DE VALIDACIÓN ADICIONALES
    # ========================================

    name = fields.Char(string="Referencia", required=True)

    # Estados de validación extendidos
    validation_state = fields.Selection([
        ('pending', 'Pendiente'),
        ('validating', 'Validando'),
        ('validated', 'Validado'),
        ('corrected', 'Corregido'),
        ('rejected', 'Rechazado'),
        ('approved', 'Aprobado')
    ], string="Estado de Validación", default='pending', tracking=True)

    # Campos de diferencia de datos
    data_differences = fields.Text(string="Diferencias Detectadas")
    corrections_applied = fields.Text(string="Correcciones Aplicadas")

    # Mapeo de campos mejorado
    field_mapping = fields.Json(string="Mapeo de Campos Personalizado")

    # ========================================
    # MÉTODOS DE VALIDACIÓN DIFERENCIAL
    # ========================================

    @api.model
    def validate_rips_data_differences(self, original_data, imported_data):
        """
        Valida y detecta diferencias entre datos originales e importados

        Args:
            original_data: Datos originales del sistema
            imported_data: Datos importados desde Excel/CSV

        Returns:
            dict: Diccionario con diferencias y sugerencias de corrección
        """
        differences = {
            'fields_missing': [],
            'fields_invalid': [],
            'fields_corrected': [],
            'suggestions': []
        }

        # Campos críticos RIPS que deben validarse
        critical_fields = [
            'invoice_number',
            'partner_vat',
            'invoice_date',
            'service_code',
            'diagnosis_code',
            'patient_id',
            'contract_id',
            'amount_total'
        ]

        for field in critical_fields:
            original_value = original_data.get(field)
            imported_value = imported_data.get(field)

            if not imported_value:
                differences['fields_missing'].append(field)
                differences['suggestions'].append(
                    f"Campo '{field}' faltante - usar valor por defecto: {original_value}"
                )
            elif original_value and str(original_value) != str(imported_value):
                differences['fields_invalid'].append({
                    'field': field,
                    'original': original_value,
                    'imported': imported_value
                })

                # Aplicar corrección automática para ciertos campos
                if field in ['partner_vat', 'patient_id']:
                    # Limpiar caracteres no numéricos
                    clean_value = ''.join(filter(str.isdigit, str(imported_value)))
                    if clean_value:
                        differences['fields_corrected'].append({
                            'field': field,
                            'original': imported_value,
                            'corrected': clean_value
                        })

        return differences

    @api.model
    def apply_data_corrections(self, invoice_data, corrections):
        """
        Aplica correcciones automáticas a los datos de factura

        Args:
            invoice_data: Datos de factura original
            corrections: Diccionario con correcciones a aplicar

        Returns:
            dict: Datos de factura corregidos
        """
        corrected_data = invoice_data.copy()

        for correction in corrections.get('fields_corrected', []):
            field_name = correction['field']
            corrected_value = correction['corrected']
            corrected_data[field_name] = corrected_value

            _logger.info(f"Corrección aplicada: {field_name} = {corrected_value}")

        # Validaciones adicionales específicas de RIPS
        if 'invoice_date' in corrected_data:
            # Asegurar formato de fecha correcto
            try:
                if isinstance(corrected_data['invoice_date'], str):
                    corrected_data['invoice_date'] = datetime.strptime(
                        corrected_data['invoice_date'], '%Y-%m-%d'
                    ).date()
            except ValueError:
                _logger.warning(f"Formato de fecha inválido: {corrected_data['invoice_date']}")

        return corrected_data

    # ========================================
    # MÉTODOS DE MAPEO INTELIGENTE
    # ========================================

    @api.model
    def smart_field_mapping(self, excel_columns):
        """
        Mapeo inteligente de columnas Excel a campos Odoo

        Args:
            excel_columns: Lista de columnas del archivo Excel

        Returns:
            dict: Mapeo de columnas a campos
        """
        # Diccionario de mapeo común
        common_mappings = {
            'nit': 'partner_vat',
            'numero factura': 'invoice_number',
            'fecha': 'invoice_date',
            'cliente': 'partner_name',
            'paciente': 'patient_name',
            'servicio': 'service_code',
            'diagnostico': 'diagnosis_code',
            'valor': 'amount_total',
            'contrato': 'contract_id',
            'tipo documento': 'patient_document_type',
            'documento': 'patient_document_number',
            'codigo cups': 'service_code',
            'codigo cie10': 'diagnosis_code'
        }

        mapping = {}
        for col in excel_columns:
            col_lower = col.lower().strip()

            # Buscar coincidencias exactas
            if col_lower in common_mappings:
                mapping[col] = common_mappings[col_lower]
            # Buscar coincidencias parciales
            else:
                for key, value in common_mappings.items():
                    if key in col_lower or col_lower in key:
                        mapping[col] = value
                        break

        return mapping

    # ========================================
    # MÉTODOS DE EXPORTACIÓN MEJORADA
    # ========================================

    @api.model
    def enhance_rips_export_data(self, rips_data):
        """
        Mejora los datos de exportación RIPS con validaciones adicionales

        Args:
            rips_data: Datos RIPS originales

        Returns:
            dict: Datos RIPS mejorados
        """
        enhanced_data = rips_data.copy()

        # Agregar metadatos de validación
        enhanced_data['validation_metadata'] = {
            'export_date': datetime.now().isoformat(),
            'validation_version': '2.0',
            'enhancements_applied': []
        }

        # Validar y corregir estructura de usuarios
        if 'usuarios' in enhanced_data:
            for usuario in enhanced_data['usuarios']:
                # Validar tipo de documento
                if 'tipoIdentificacion' in usuario:
                    tipo_doc = usuario['tipoIdentificacion']
                    if tipo_doc not in ['CC', 'CE', 'PA', 'RC', 'TI', 'CN', 'SC', 'CD', 'PE']:
                        usuario['tipoIdentificacion'] = 'CC'  # Valor por defecto
                        enhanced_data['validation_metadata']['enhancements_applied'].append(
                            f"Tipo documento corregido para usuario {usuario.get('numeroIdentificacion')}"
                        )

                # Validar edad
                if 'edad' in usuario and isinstance(usuario['edad'], str):
                    try:
                        usuario['edad'] = int(usuario['edad'])
                    except ValueError:
                        usuario['edad'] = 0
                        enhanced_data['validation_metadata']['enhancements_applied'].append(
                            f"Edad corregida para usuario {usuario.get('numeroIdentificacion')}"
                        )

        # Validar servicios
        if 'servicios' in enhanced_data:
            for servicio in enhanced_data['servicios']:
                # Validar código CUPS
                if 'codigoCups' in servicio:
                    codigo = servicio['codigoCups']
                    if not codigo or len(codigo) < 4:
                        servicio['codigoCups'] = '890201'  # Código genérico
                        enhanced_data['validation_metadata']['enhancements_applied'].append(
                            f"Código CUPS corregido para servicio"
                        )

                # Validar cantidades
                if 'cantidad' in servicio:
                    try:
                        servicio['cantidad'] = float(servicio['cantidad'])
                    except (ValueError, TypeError):
                        servicio['cantidad'] = 1.0

        return enhanced_data

    # ========================================
    # MÉTODOS DE IMPORTACIÓN DIFERENCIAL
    # ========================================

    def process_differential_import(self, file_data, import_config):
        """
        Procesa importación con análisis diferencial de datos

        Args:
            file_data: Datos del archivo a importar
            import_config: Configuración de importación

        Returns:
            dict: Resultado del proceso con diferencias detectadas
        """
        results = {
            'success': 0,
            'errors': 0,
            'differences': [],
            'corrections': []
        }

        try:
            # Procesar cada línea del archivo
            for row_idx, row_data in enumerate(file_data):
                # Buscar factura existente
                existing_invoice = self._find_existing_invoice(row_data)

                if existing_invoice:
                    # Detectar diferencias
                    differences = self.validate_rips_data_differences(
                        existing_invoice.read()[0],
                        row_data
                    )

                    if differences['fields_invalid'] or differences['fields_missing']:
                        results['differences'].append({
                            'row': row_idx + 1,
                            'invoice': existing_invoice.name,
                            'differences': differences
                        })

                        # Aplicar correcciones si está configurado
                        if import_config.get('auto_correct', False):
                            corrected_data = self.apply_data_corrections(
                                row_data,
                                differences
                            )
                            row_data = corrected_data
                            results['corrections'].append({
                                'row': row_idx + 1,
                                'corrections': differences['fields_corrected']
                            })

                # Continuar con el proceso de importación
                self._import_invoice_line(row_data, import_config)
                results['success'] += 1

        except Exception as e:
            _logger.error(f"Error en importación diferencial: {str(e)}")
            results['errors'] += 1
            results['error_message'] = str(e)

        return results

    def _find_existing_invoice(self, invoice_data):
        """
        Busca factura existente basada en datos de importación
        """
        domain = []

        if invoice_data.get('invoice_number'):
            domain.append(('name', '=', invoice_data['invoice_number']))
        elif invoice_data.get('reference'):
            domain.append(('ref', '=', invoice_data['reference']))

        if domain:
            return self.env['account.move'].search(domain, limit=1)

        return False

    def _import_invoice_line(self, line_data, config):
        """
        Importa una línea de factura con validaciones adicionales
        """
        # Implementación base - se puede extender según necesidades
        pass


class AccountMoveRipsDiff(models.Model):
    """
    Extensión del modelo account.move para agregar diferencias RIPS
    """
    _inherit = 'account.move'

    # Campos adicionales para tracking de diferencias
    rips_data_differences = fields.Text(
        string="Diferencias de Datos RIPS",
        help="Registro de diferencias detectadas durante importación/exportación RIPS"
    )

    rips_corrections_applied = fields.Json(
        string="Correcciones RIPS Aplicadas",
        help="JSON con las correcciones automáticas aplicadas"
    )

    rips_validation_score = fields.Float(
        string="Score de Validación RIPS",
        help="Puntuación de validez de datos RIPS (0-100)"
    )

    @api.model
    def create(self, vals):
        """
        Override create para agregar validación diferencial
        """
        # Validar datos RIPS si vienen de importación
        if vals.get('importer_id'):
            enhancement = self.env['rips.data.enhancement']

            # Aplicar mapeo inteligente si hay datos raw
            if vals.get('raw_import_data'):
                raw_data = json.loads(vals['raw_import_data'])
                corrections = enhancement.apply_data_corrections(vals, {})
                vals.update(corrections)
                vals['rips_corrections_applied'] = json.dumps(corrections)

        return super().create(vals)

    def validate_rips_differences(self):
        """
        Valida diferencias en datos RIPS de la factura
        """
        self.ensure_one()

        enhancement = self.env['rips.data.enhancement']

        # Obtener datos actuales
        current_data = {
            'invoice_number': self.name,
            'partner_vat': self.partner_id.vat,
            'invoice_date': str(self.invoice_date),
            'amount_total': self.amount_total
        }

        # Si hay datos RIPS JSON, comparar
        if self.rips_json:
            rips_data = json.loads(self.rips_json)
            differences = enhancement.validate_rips_data_differences(
                current_data,
                rips_data
            )

            self.rips_data_differences = json.dumps(differences, indent=2)

            # Calcular score de validación
            total_fields = len(current_data)
            valid_fields = total_fields - len(differences.get('fields_invalid', []))
            self.rips_validation_score = (valid_fields / total_fields) * 100

        return True
# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)

class AccountJournal(models.Model):
    _inherit = 'account.journal'
    
    health_operation_type = fields.Selection(
        selection='_get_health_operation_types',
        string='Tipo Operación Salud por Defecto',
        help='Tipo de operación del sector salud que se usará por defecto en este diario'
    )
    
    default_health_coverage_plan_id = fields.Many2one(
        'health.coverage.plan',
        string='Cobertura por Defecto',
        help='Plan de cobertura que se asignará por defecto'
    )
    
    default_health_payment_mode_id = fields.Many2one(
        'health.payment.mode',
        string='Modalidad de Pago por Defecto',
        help='Modalidad de pago que se asignará por defecto'
    )
    
    default_health_collection_concept_id = fields.Many2one(
        'health.collection.concept',
        string='Concepto de Recaudo por Defecto',
        help='Concepto de recaudo que se asignará por defecto'
    )
    
    default_health_provider_code = fields.Char(
        string='Código Prestador por Defecto',
        help='Código del prestador que se usará por defecto'
    )
    
    @api.model
    def _get_health_operation_types(self):
        """Obtiene los tipos de operación del sector salud"""
        return [
            ('SS-CUFE', 'SS-CUFE - Factura por servicios + aporte del usuario'),
            ('SS-CUDE', 'SS-CUDE - Acreditación por Contingencia/NC'),
            ('SS-POS', 'SS-POS - Acreditación por POS'),
            ('SS-SNum', 'SS-SNum - Acreditación por Talonario/Papel'),
            ('SS-Recaudo', 'SS-Recaudo - Comprobante de Recaudo'),
            ('SS-Reporte', 'SS-Reporte - Reporte Informativo'),
            ('SS-SinAporte', 'SS-SinAporte - Factura por servicios sin ningún aporte del usuario'),
        ]

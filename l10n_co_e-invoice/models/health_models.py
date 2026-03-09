
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

from odoo.osv import expression

class HealthCoveragePlan(models.Model):
    _name = 'health.coverage.plan'
    _description = 'Plan de Cobertura de Salud'
    
    code = fields.Char(string='Código', required=True, size=2)
    name = fields.Char(string='Nombre', required=True)
    description = fields.Text(string='Descripción')
    active = fields.Boolean(default=True)
    requires_policy = fields.Boolean(
        string='Requiere Número de Póliza',
        help='Indica si este tipo de cobertura requiere obligatoriamente número de póliza'
    )
    
    _sql_constraints = [
        ('code_unique', 'UNIQUE(code)', 'El código de cobertura debe ser único')
    ]
    @api.depends('name', 'code')
    def _compute_display_name(self):
        for template in self:
            template.display_name = False if not template.name else (
                '{}{}'.format(
                    template.code and '[%s] ' % template.code or '', template.name
                ))
    @api.model
    def _name_search(self, name, args=None, operator='ilike',
                     limit=100, name_get_uid=None,order=None):
        args = args or []
        if operator == 'ilike' and not (name or '').strip():
            domain = []
        else:
            domain = ['|', ('name', 'ilike', name),
                      ('code', 'ilike', name)]
        return self._search(
            expression.AND([domain, args]),
            limit=limit, order=order,
            access_rights_uid=name_get_uid
        )

class HealthPaymentMode(models.Model):
    _name = 'health.payment.mode'
    _description = 'Modalidad de Pago en Salud'
    
    code = fields.Char(string='Código', required=True, size=2)
    name = fields.Char(string='Nombre', required=True)
    description = fields.Text(string='Descripción')
    requires_period_dates = fields.Boolean(
        string='Requiere Fechas de Periodo', 
        help='Indica si esta modalidad de pago requiere obligatoriamente fechas de inicio y fin de periodo'
    )
    is_prospective = fields.Boolean(
        string='Es Prospectivo',
        help='Indica si es una modalidad de pago prospectiva (definida antes de la prestación)'
    )
    risk_level = fields.Selection([
        ('low', 'Bajo - Menor riesgo para el prestador'),
        ('medium', 'Medio - Riesgo compartido'),
        ('high', 'Alto - Mayor riesgo para el prestador')
    ], string='Nivel de Riesgo', help='Nivel de riesgo financiero asumido por el prestador con esta modalidad')
    active = fields.Boolean(default=True)
    
    _sql_constraints = [
        ('code_unique', 'UNIQUE(code)', 'El código de modalidad de pago debe ser único')
    ]
    @api.depends('name', 'code')
    def _compute_display_name(self):
        for template in self:
            template.display_name = False if not template.name else (
                '{}{}'.format(
                    template.code and '[%s] ' % template.code or '', template.name
                ))
    @api.model
    def _name_search(self, name, args=None, operator='ilike',
                     limit=100, name_get_uid=None,order=None):
        args = args or []
        if operator == 'ilike' and not (name or '').strip():
            domain = []
        else:
            domain = ['|', ('name', 'ilike', name),
                      ('code', 'ilike', name)]
        return self._search(
            expression.AND([domain, args]),
            limit=limit, order=order,
            access_rights_uid=name_get_uid
        )
class HealthCollectionConcept(models.Model):
    _name = 'health.collection.concept'
    _description = 'Concepto de Recaudo en Salud'
    
    code = fields.Char(string='Código', required=True, size=2)
    name = fields.Char(string='Nombre', required=True)
    description = fields.Text(string='Descripción')
    active = fields.Boolean(default=True)
    applies_fev = fields.Boolean(string='Aplica FEV', default=True, help='Aplica para Factura Electrónica de Venta')
    applies_rips = fields.Boolean(string='Aplica RIPS', default=True, help='Aplica para RIPS')
    
    _sql_constraints = [
        ('code_unique', 'UNIQUE(code)', 'El código de concepto de recaudo debe ser único')
    ]

    @api.depends('name', 'code')
    def _compute_display_name(self):
        for template in self:
            template.display_name = False if not template.name else (
                '{}{}'.format(
                    template.code and '[%s] ' % template.code or '', template.name
                ))
    @api.model
    def _name_search(self, name, args=None, operator='ilike',
                     limit=100, name_get_uid=None,order=None):
        args = args or []
        if operator == 'ilike' and not (name or '').strip():
            domain = []
        else:
            domain = ['|', ('name', 'ilike', name),
                      ('code', 'ilike', name)]
        return self._search(
            expression.AND([domain, args]),
            limit=limit, order=order,
            access_rights_uid=name_get_uid
        )
        
class HealthInteroperabilityPT(models.Model):
    _name = 'health.interoperability.pt'
    _description = 'Interoperabilidad entre Partes para Facturación de Salud'
    _rec_name = 'partner_id'
    
    partner_id = fields.Many2one(
        'res.partner',
        string='Socio Comercial',
        required=True,
        help='Entidad con la que se establece el acuerdo de interoperabilidad'
    )
    
    active = fields.Boolean(default=True)
    
    description = fields.Text(
        string='Descripción',
        help='Descripción general del acuerdo de interoperabilidad'
    )
    
    url_download = fields.Char(
        string='URL de Descarga',
        help='URL para la descarga de archivos adjuntos'
    )
    
    param_excel_file = fields.Char(
        string='Archivo Excel',
        help='Nombre del archivo Excel para descarga'
    )
    
    param_text_file = fields.Char(
        string='Archivo de Texto',
        help='Nombre del archivo de texto para descarga'
    )
    
    additional_download_params = fields.One2many(
        'health.interoperability.param',
        'interoperability_id',
        string='Parámetros Adicionales de Descarga',
        domain=[('param_type', '=', 'download')],
        help='Parámetros adicionales para la URL de descarga'
    )
    
    web_service_url = fields.Char(
        string='URL del Servicio Web',
        help='URL del servicio web para entrega de documentos (WSDL)'
    )
    
    document_delivery_params = fields.One2many(
        'health.interoperability.param',
        'interoperability_id',
        string='Parámetros de Entrega',
        domain=[('param_type', '=', 'delivery')],
        help='Parámetros para la entrega de documentos'
    )
    
    otp_info = fields.Char(
        string='Información OTP',
        help='Información sobre cómo obtener la contraseña de un solo uso (OTP)'
    )
    
    has_delivery_receipt = fields.Boolean(
        string='Acuse de Recibo',
        help='Habilitar método para acuse de recibo de FEV-VP'
    )
    
    has_goods_delivered = fields.Boolean(
        string='Constancia de Mercancía',
        help='Habilitar método para constancia de mercancía entregada'
    )
    
    has_rejection = fields.Boolean(
        string='Rechazo de FEV',
        help='Habilitar método para rechazo de FEV-VP'
    )
    
    has_acceptance = fields.Boolean(
        string='Aceptación de FEV',
        help='Habilitar método para aceptación de FEV-VP'
    )
    
    has_claims = fields.Boolean(
        string='Reclamos',
        help='Habilitar método para reclamos de FEV-VP'
    )
    
    company_id = fields.Many2one(
        'res.company',
        string='Compañía',
        default=lambda self: self.env.company
    )
    
    @api.model
    def create(self, vals):
        record = super(HealthInteroperabilityPT, self).create(vals)
        record._create_default_delivery_methods()
        return record
    
    def _create_default_delivery_methods(self):
        """Crear los métodos de entrega predeterminados basados en las casillas marcadas"""
        param_obj = self.env['health.interoperability.param']
        
        method_mapping = [
            (self.has_delivery_receipt, 'Método-1', 'ClienteEntregaAcuseDeReciboDeFEV-VP'),
            (self.has_goods_delivered, 'Método-2', 'ClienteEntregaConstanciaDeMercanciaEntregada'),
            (self.has_rejection, 'Método-3', 'ClienteEntregaRechazoDeFEVVP'),
            (self.has_acceptance, 'Método-4', 'ClienteEntregaAceptacionDeFEVVP'),
            (self.has_claims, 'Método-5', 'ClienteEntregaReclamosDeFEVVP'),
        ]
        
        for enabled, name, value in method_mapping:
            if enabled:
                param_obj.create({
                    'interoperability_id': self.id,
                    'param_type': 'delivery',
                    'name': name,
                    'value': value,
                })
        
        if self.otp_info:
            param_obj.create({
                'interoperability_id': self.id,
                'param_type': 'delivery',
                'name': 'Contraseña OTP',
                'value': self.otp_info,
            })
    
    def generate_interoperability_data(self):
        """Genera los datos de interoperabilidad en el formato requerido para el XML"""
        self.ensure_one()
        
        result = {
            'InteroperabilidadPT': {}
        }
        
        if self.url_download:
            url_data = {
                'URL': self.url_download,
                'ParametrosArgumentos': {
                    'ParametroArgumento': []
                }
            }
            
            params = []
            
            if self.param_excel_file:
                params.append({
                    'Name': 'excelFile',
                    'Value': self.param_excel_file
                })
            
            if self.param_text_file:
                params.append({
                    'Name': 'txtFile',
                    'Value': self.param_text_file
                })
            
            for param in self.additional_download_params:
                params.append({
                    'Name': param.name,
                    'Value': param.value
                })
            
            if params:
                url_data['ParametrosArgumentos']['ParametroArgumento'] = params
                result['InteroperabilidadPT']['URLDescargaAdjuntos'] = url_data
        
        if self.web_service_url:
            document_data = {
                'WS': self.web_service_url,
                'ParametrosArgumentos': {
                    'ParametroArgumento': []
                }
            }
            params = []
            for param in self.document_delivery_params:
                params.append({
                    'Name': param.name,
                    'Value': param.value
                })
            
            if params:
                document_data['ParametrosArgumentos']['ParametroArgumento'] = params
                result['InteroperabilidadPT']['EntregaDocumento'] = document_data
        
        return result


class HealthInteroperabilityParam(models.Model):
    _name = 'health.interoperability.param'
    _description = 'Parámetro de Interoperabilidad'
    
    interoperability_id = fields.Many2one(
        'health.interoperability.pt',
        string='Configuración de Interoperabilidad',
        required=True,
        ondelete='cascade'
    )
    
    param_type = fields.Selection([
        ('download', 'Descarga'),
        ('delivery', 'Entrega')
    ], string='Tipo de Parámetro', required=True, default='delivery')
    
    name = fields.Char(
        string='Nombre',
        required=True,
        help='Nombre del parámetro'
    )
    
    value = fields.Char(
        string='Valor',
        required=True,
        help='Valor del parámetro'
    )
    
    sequence = fields.Integer(
        string='Secuencia',
        default=10,
        help='Orden de aparición del parámetro'
    )
    
    company_id = fields.Many2one(
        'res.company',
        string='Compañía',
        related='interoperability_id.company_id',
        store=True
    )
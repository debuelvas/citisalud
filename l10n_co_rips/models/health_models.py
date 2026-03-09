
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError

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


class AccountMoveHealthPrepaid(models.Model):
    """Modelo para referencias de prepago del sector salud"""
    _name = 'account.move.health.prepaid'
    _description = 'Referencias de Prepago Sector Salud'
    _rec_name = 'display_name'
    _order = 'received_date desc, id desc'
    

    invoice_id = fields.Many2one(
        'account.move',
        string='Factura',
        required=True,
        ondelete='cascade',
        domain="[('move_type', '=', 'out_invoice'), ('state', '=', 'draft')]"
    )
    
    # Documento de recaudo de referencia
    reference_invoice_id = fields.Many2one(
        'account.move',
        string='Documento de Recaudo',
        domain="[('fe_operation_type', '=', 'SS-Recaudo')]",
        help='Documento de recaudo que se acredita'
    )
    
    # Concepto del prepago
    collection_concept_code = fields.Selection([
        ('01', 'COPAGO'),
        ('02', 'CUOTA MODERADORA'),
        ('03', 'PAGOS COMPARTIDOS'),
        ('04', 'ANTICIPO'),
    ], string='Concepto', required=True, default='01')
    
    # Monto
    amount = fields.Monetary(
        string='Monto',
        currency_field='currency_id',
        required=True
    )
    
    # Moneda
    currency_id = fields.Many2one(
        'res.currency',
        related='invoice_id.currency_id',
        store=True,
        readonly=True
    )
    
    # Fechas
    received_date = fields.Date(
        string='Fecha Recepción',
        required=True,
        default=fields.Date.today,
        help='Fecha en que se recibió el pago del paciente'
    )
    
    paid_date = fields.Date(
        string='Fecha Pago',
        help='Fecha en que se realizó el pago'
    )
    
    # Referencias
    invoice_reference = fields.Char(
        string='Referencia Factura',
        help='Número o referencia de la factura de recaudo'
    )
    
    description = fields.Char(
        string='Descripción',
        help='Descripción adicional del prepago'
    )
    
    # Campos relacionados para facilidad
    partner_id = fields.Many2one(
        'res.partner',
        related='invoice_id.partner_id',
        store=True,
        string='Paciente',
        readonly=True
    )
    
    invoice_date = fields.Date(
        related='invoice_id.invoice_date',
        store=True,
        string='Fecha Factura',
        readonly=True
    )
    
    # Estado de aplicación
    is_applied = fields.Boolean(
        string='Aplicado',
        compute='_compute_is_applied',
        store=True,
        help='Indica si este prepago ya fue aplicado en la factura'
    )
    
    # ===== MÉTODOS COMPUTE =====
    
    @api.depends('collection_concept_code', 'amount', 'invoice_reference')
    def _compute_display_name(self):
        """Calcula el nombre para mostrar"""
        for record in self:
            concept_dict = dict(record._fields['collection_concept_code'].selection)
            concept = concept_dict.get(record.collection_concept_code, '')
            
            parts = [concept]
            if record.amount:
                parts.append(f"${record.amount:,.0f}")
            if record.invoice_reference:
                parts.append(f"Ref: {record.invoice_reference}")
                
            record.display_name = ' - '.join(parts)
    
    @api.depends('invoice_id.state')
    def _compute_is_applied(self):
        """Determina si el prepago fue aplicado"""
        for record in self:
            record.is_applied = record.invoice_id.state != 'draft'
    
    # ===== MÉTODOS ONCHANGE =====
    
    @api.onchange('reference_invoice_id')
    def _onchange_reference_invoice_id(self):
        """Al seleccionar un documento de recaudo, trae información relevante"""
        if self.reference_invoice_id:
            # Copiar el número de referencia
            self.invoice_reference = self.reference_invoice_id.name
            
            # Si el documento de recaudo tiene fecha, usarla como fecha de recepción
            if self.reference_invoice_id.invoice_date:
                self.received_date = self.reference_invoice_id.invoice_date
                self.paid_date = self.reference_invoice_id.invoice_date
            
            # Si tiene el mismo paciente, está bien
            if self.invoice_id and self.reference_invoice_id.partner_id != self.invoice_id.partner_id:
                return {
                    'warning': {
                        'title': _('Advertencia'),
                        'message': _('El documento de recaudo es de un paciente diferente al de la factura.')
                    }
                }
    
    @api.onchange('collection_concept_code')
    def _onchange_collection_concept_code(self):
        """Actualiza la descripción según el concepto seleccionado"""
        if self.collection_concept_code and not self.description:
            concept_dict = dict(self._fields['collection_concept_code'].selection)
            concept_name = concept_dict.get(self.collection_concept_code, '')
            
            # Sugerir descripción según el concepto
            if self.collection_concept_code == '01':
                self.description = f"Copago servicios de salud"
            elif self.collection_concept_code == '02':
                self.description = f"Cuota moderadora consulta/procedimiento"
            elif self.collection_concept_code == '03':
                self.description = f"Pago compartido plan voluntario"
            elif self.collection_concept_code == '04':
                self.description = f"Anticipo para servicios de salud"
    
    @api.onchange('received_date')
    def _onchange_received_date(self):
        """Valida la fecha de recepción"""
        if self.received_date:
            # No puede ser futura
            if self.received_date > fields.Date.today():
                self.received_date = fields.Date.today()
                return {
                    'warning': {
                        'title': _('Fecha Ajustada'),
                        'message': _('La fecha de recepción no puede ser futura. Se ajustó a hoy.')
                    }
                }
            
            # Si no hay fecha de pago, asumir la misma
            if not self.paid_date:
                self.paid_date = self.received_date
    
    @api.onchange('paid_date')
    def _onchange_paid_date(self):
        """Valida la fecha de pago"""
        if self.paid_date and self.received_date:
            if self.paid_date < self.received_date:
                self.paid_date = self.received_date
                return {
                    'warning': {
                        'title': _('Fecha Ajustada'),
                        'message': _('La fecha de pago no puede ser anterior a la fecha de recepción.')
                    }
                }
    
    @api.onchange('amount')
    def _onchange_amount(self):
        """Valida el monto"""
        if self.amount < 0:
            self.amount = abs(self.amount)
            return {
                'warning': {
                    'title': _('Monto Ajustado'),
                    'message': _('El monto debe ser positivo. Se ajustó automáticamente.')
                }
            }
    
    # ===== MÉTODOS CONSTRAINT =====
    
    @api.constrains('amount')
    def _check_amount(self):
        """Valida que el monto sea positivo"""
        for record in self:
            if record.amount <= 0:
                raise ValidationError(_('El monto del prepago debe ser mayor a cero.'))
    
    @api.constrains('received_date', 'paid_date')
    def _check_dates(self):
        """Valida coherencia de fechas"""
        for record in self:
            if record.paid_date and record.received_date:
                if record.paid_date < record.received_date:
                    raise ValidationError(_(
                        'La fecha de pago no puede ser anterior a la fecha de recepción.'
                    ))
            
            if record.received_date > fields.Date.today():
                raise ValidationError(_(
                    'La fecha de recepción no puede ser futura.'
                ))
    
    @api.constrains('invoice_id', 'reference_invoice_id')
    def _check_patient_consistency(self):
        """Valida que el paciente sea consistente"""
        for record in self:
            if record.reference_invoice_id and record.invoice_id:
                if record.reference_invoice_id.partner_id != record.invoice_id.partner_id:
                    raise ValidationError(_(
                        'El documento de recaudo debe ser del mismo paciente que la factura.'
                    ))
    
    # ===== MÉTODOS CRUD =====
    
    @api.model_create_multi
    def create(self, vals_list):
        """Override create para validaciones adicionales"""
        for vals in vals_list:
            # Asegurar que paid_date no sea None si received_date existe
            if vals.get('received_date') and not vals.get('paid_date'):
                vals['paid_date'] = vals['received_date']
        
        return super().create(vals_list)
    
    def write(self, vals):
        """Override write para validar cambios"""
        # No permitir cambios si ya está aplicado
        if self.filtered('is_applied') and not self.env.context.get('force_write'):
            modifiable_fields = {'description', 'invoice_reference'}
            changed_fields = set(vals.keys())
            
            if changed_fields - modifiable_fields:
                raise UserError(_(
                    'No se pueden modificar prepagos ya aplicados. '
                    'Solo se permite cambiar la descripción y referencia.'
                ))
        
        return super().write(vals)
    
    def unlink(self):
        """Override unlink para validar eliminación"""
        if self.filtered('is_applied'):
            raise UserError(_(
                'No se pueden eliminar prepagos ya aplicados en facturas confirmadas.'
            ))
        return super().unlink()

 

class ResPartner(models.Model):
    """Extensión del partner para sector salud"""
    _inherit = 'res.partner'
    
    is_insurance_company = fields.Boolean(
        string='Es Aseguradora',
        help='Indica si este contacto es una compañía aseguradora'
    )
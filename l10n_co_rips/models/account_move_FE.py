# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from lxml import etree
import logging
import hashlib
import base64
from odoo.exceptions import UserError, ValidationError
from odoo.osv import expression

_logger = logging.getLogger(__name__)

# Agregar tipos de operación del sector salud
EDI_OPERATION_TYPE_HEALTH = [
    ('10', 'Estándar'),
    ('09', 'AIU'),
    ('11', 'Mandatos'),
    ('12', 'Transporte'),
    ('13', 'Cambiario'),
    ('15', 'Compra Divisas'),
    ('16', 'Venta Divisas'),
    ('SS-CUFE', 'SS-CUFE - Factura por servicios + aporte del usuario'),
    ('SS-CUDE', 'SS-CUDE - Acreditación por Contingencia/NC'),
    ('SS-POS', 'SS-POS - Acreditación por POS'),
    ('SS-SNum', 'SS-SNum - Acreditación por Talonario/Papel'),
    ('SS-Recaudo', 'SS-Recaudo - Comprobante de Recaudo'),
    ('SS-Reporte', 'SS-Reporte - Reporte Informativo'),
    ('SS-SinAporte', 'SS-SinAporte - Factura por servicios sin ningún aporte del usuario'),    
    ('20', 'Nota Crédito que referencia una factura electrónica'),
    ('22', 'Nota Crédito sin referencia a facturas'),
    ('23', 'Nota Crédito para facturación electrónica V1 (Decreto 2242)'),
    ('30', 'Nota Débito que referencia una factura electrónica'),
    ('32', 'Nota Débito sin referencia a facturas'),
    ('33', 'Nota Débito para facturación electrónica V1 (Decreto 2242)'),
]

class AccountMove(models.Model):
    _inherit = 'account.move'

    fe_operation_type = fields.Selection(
        EDI_OPERATION_TYPE_HEALTH,
        string='Tipo de Operación',
        default='10',
        required=True
    )
    
    # ===== CAMPOS ESPECÍFICOS DEL SECTOR SALUD =====
    is_health_sector = fields.Boolean(
        string='Sector Salud',
        compute='_compute_is_health_sector',
        store=True,
        help='Habilita funcionalidades específicas para facturación del sector salud'
    )
    
    health_provider_code = fields.Char(
        string='Código Prestador', 
        help='Código único del prestador de servicios de salud (10-12 dígitos)'
    )
    
    date_start = fields.Date(
        string='Fecha Inicio Periodo',
       default=fields.Date.today,
        help='Fecha de inicio del periodo de facturación'
    )
    
    date_end = fields.Date(
        string='Fecha Fin Periodo',
        help='Fecha de fin del periodo de facturación'
    )
    
    copay_amount = fields.Monetary(
        string='Valor Copago', 
        help='Monto recaudado por concepto de copago'
    )
    
    moderator_fee_amount = fields.Monetary(
        string='Valor Cuota Moderadora', 
        help='Monto recaudado por concepto de cuota moderadora'
    )
    
    recovery_fee_amount = fields.Monetary(
        string='Valor Cuota Recuperación', 
        help='Monto recaudado por concepto de cuota de recuperación (anticipo)'
    )
    
    shared_payment_amount = fields.Monetary(
        string='Valor Pagos Compartidos', 
        help='Monto recaudado por concepto de pagos compartidos'
    )
    
    health_coverage_plan_id = fields.Many2one(
        'health.coverage.plan',
        string='Tipo de Cobertura',
        help='Indica quién es el responsable final de asumir el costo de los servicios'
    )
    
    health_payment_mode_id = fields.Many2one(
        'health.payment.mode',
        string='Modalidad de Pago',
        help='Forma o método bajo el cual se acordó contractualmente el pago de los servicios'
    )
    
    health_collection_concept_id = fields.Many2one(
        'health.collection.concept',
        string='Concepto de Recaudo',
        help='Tipo de aporte o pago a cargo del usuario'
    )
    
    contract_id = fields.Many2one(
        'customer.contract',
        string='Contrato',
        domain="[('partner_id', '=', partner_id)]"
    )
    
    interoperability_pt_id = fields.Many2one(
        'health.interoperability.pt',
        string='Interoperabilidad PT',
        help='Configuración de interoperabilidad entre partes para esta factura'
    )
    
    health_prepaid_amount = fields.Monetary(
        string='Total Prepagos Salud',
        compute='_compute_health_prepaid_amount',
        store=True,
        help='Total de valores prepagados (copagos, cuotas moderadoras, etc.)'
    )
    
    health_prepaid_references = fields.One2many(
        'account.move.health.prepaid',
        'invoice_id',
        string='Referencias de Prepago',
        help='Documentos de recaudo que se acreditan en esta factura'
    )
    
    health_pos_authorization = fields.Char(
        string='Autorización POS',
        help='Número de autorización DIAN para recaudo por POS'
    )
    
    health_paper_range = fields.Char(
        string='Rango Papel',
        help='Rango de numeración autorizado para facturas en papel'
    )
    
    health_contingency_cude = fields.Char(
        string='CUDE Contingencia',
        help='CUDE del documento de contingencia original'
    )
    
    health_validation_status = fields.Selection([
        ('draft', 'Borrador'),
        ('validated', 'Validado'),
        ('error', 'Error')
    ], string='Estado Validación Salud', default='draft'
                                                )
    
    health_validation_message = fields.Text(
        string='Mensaje de Validación',
        readonly=True
    )
    health_mipres_number = fields.Char(
        string='Número MIPRES', 
        help='Número de prescripción de medicamentos'
    )
    
    health_mipres_delivery_number = fields.Char(
        string='Número Entrega MIPRES', 
        help='Número de entrega de prescripción'
    )
    # ===== COMPUTE METHODS =====
    
    @api.depends('fe_operation_type')
    def _compute_is_health_sector(self):
        """Determina si la factura pertenece al sector salud según su tipo de operación"""
        health_operations = ['SS-CUFE', 'SS-CUDE', 'SS-POS', 'SS-SNum', 'SS-Recaudo', 'SS-Reporte', 'SS-SinAporte']
        
        for record in self:
            record.is_health_sector = record.fe_operation_type in health_operations
    
    @api.depends('health_prepaid_references', 'health_prepaid_references.amount',
                 'copay_amount', 'moderator_fee_amount', 'shared_payment_amount', 'recovery_fee_amount')
    def _compute_health_prepaid_amount(self):
        """Calcula el total de prepagos del sector salud"""
        for record in self:
            prepaid_refs = sum(record.health_prepaid_references.mapped('amount'))
            
            if record.fe_operation_type in ['SS-CUFE', 'SS-CUDE', 'SS-POS', 'SS-SNum']:
                prepaid_direct = (
                    (record.copay_amount or 0) +
                    (record.moderator_fee_amount or 0) +
                    (record.shared_payment_amount or 0) +
                    (record.recovery_fee_amount or 0)
                )
                record.health_prepaid_amount = prepaid_refs + prepaid_direct
            else:
                record.health_prepaid_amount = prepaid_refs
    
    # ===== MÉTODOS DE RECOLECCIÓN DE DATOS =====
    
    def _collect_all_dian_data(self):
        """Extiende el método original para agregar datos del sector salud"""
        data = super()._collect_all_dian_data()
        
        if self.is_health_sector:
            data.update(self._collect_health_sector_data())
        
        return data
    
    def _collect_health_sector_data(self):
        """Recolecta todos los datos del sector salud para el XML"""
        data = {
            'tipo_sector': 'salud',
            'tipo_operacion': self.fe_operation_type,
            'codigo_prestador': (self.health_provider_code or self.company_id.partner_id.ref or  '').zfill(10)[:10],
            'modalidad_pago': self.health_payment_mode_id.code if self.health_payment_mode_id else '',
            'modalidad_pago_nombre': self.health_payment_mode_id.name if self.health_payment_mode_id else '',
            'cobertura_plan_beneficios': self.health_coverage_plan_id.code if self.health_coverage_plan_id else '',
            'cobertura_plan_beneficios_nombre': self.health_coverage_plan_id.name if self.health_coverage_plan_id else '',
            'numero_contrato': self.contract_id.name if self.contract_id else '',
            'numero_poliza': '',
            'copago': f"{self.copay_amount:.2f}",
            'cuota_moderadora': f"{self.moderator_fee_amount:.2f}",
            'pagos_compartidos': f"{self.shared_payment_amount:.2f}",
            'anticipo': f"{self.recovery_fee_amount:.2f}",
            'fecha_inicio_periodo_facturacion': str(self.date_start) if self.date_start else str(self.invoice_date),
            'fecha_final_periodo_facturacion': str(self.date_end) if self.date_end else str(self.invoice_date),
            'health_prepaid_amount': self.health_prepaid_amount,
            'pos_authorization': self.health_pos_authorization if self.fe_operation_type == 'SS-POS' else '',
            'paper_range': self.health_paper_range if self.fe_operation_type == 'SS-SNum' else '',
            'contingency_cude': self.health_contingency_cude if self.fe_operation_type == 'SS-CUDE' else '',
        }
        
        if self.contract_id and self.contract_id.policy_ids:
            data['numero_poliza'] = self.contract_id.policy_ids[0].name or ''
        
        return data
    
    # ===== MÉTODOS DE CONSTRUCCIÓN XML =====
    
    def _build_ubl_extensions(self, root, data, makers):
        """Construye la sección UBLExtensions completa"""
        ext = makers['ext']
        sts = makers['sts']
        cbc = makers['cbc']
        
        ubl_extensions = ext.UBLExtensions()
        
        # Extension 1: DIAN Extensions
        extension1 = ext.UBLExtension()
        extension_content = ext.ExtensionContent()
        dian_extensions = sts.DianExtensions()
        
        # InvoiceControl (solo para facturas)
        if data.get('move_type') in ['out_invoice', 'in_invoice'] and not data.get('is_debit_note'):
            invoice_control = sts.InvoiceControl(
                sts.InvoiceAuthorization(data['InvoiceAuthorization']),
                sts.AuthorizationPeriod(
                    cbc.StartDate(data['StartDate']),
                    cbc.EndDate(data['EndDate'])
                ),
                sts.AuthorizedInvoices(
                    sts.Prefix(data['Prefix']),
                    sts.From(data['From']),
                    sts.To(data['To'])
                )
            )
            dian_extensions.append(invoice_control)
        
        # InvoiceSource
        invoice_source = sts.InvoiceSource(
            cbc.IdentificationCode(
                data['SupplierCountry'],
                listAgencyID='6',
                listAgencyName='United Nations Economic Commission for Europe',
                listSchemeURI='urn:oasis:names:specification:ubl:codelist:gc:CountryIdentificationCode-2.1'
            )
        )
        dian_extensions.append(invoice_source)
        
        # SoftwareProvider
        software_provider = sts.SoftwareProvider(
            sts.ProviderID(
                data['SoftwareProviderID'],
                schemeAgencyID='195',
                schemeAgencyName='CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)',
                schemeID=data.get('SoftwareProviderDV', '') if data.get('SupplierSchemeIDCode') == '31' else '',
                schemeName='31'
            ),
            sts.SoftwareID(
                data['SoftwareID'],
                schemeAgencyID='195',
                schemeAgencyName='CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)'
            )
        )
        dian_extensions.append(software_provider)
        
        # SoftwareSecurityCode
        dian_extensions.append(
            sts.SoftwareSecurityCode(
                data['SoftwareSecurityCode'],
                schemeAgencyID='195',
                schemeAgencyName='CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)'
            )
        )
        
        # AuthorizationProvider
        dian_extensions.append(
            sts.AuthorizationProvider(
                sts.AuthorizationProviderID(
                    '800197268',
                    schemeAgencyID='195',
                    schemeAgencyName='CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)',
                    schemeID='4',
                    schemeName='31'
                )
            )
        )
        
        # QRCode
        dian_extensions.append(sts.QRCode(self._build_qr_content(data)))
        
        extension_content.append(dian_extensions)
        extension1.append(extension_content)
        ubl_extensions.append(extension1)
        
        if data.get('is_foreign_currency'):
            extension2 = self._build_foreign_currency_extension(data, makers)
            ubl_extensions.append(extension2)
        
        tipo_sector = self.is_health_sector or data.get('tipo_sector') in ['salud', '2', 2]
        tipo_operacion = self.fe_operation_type or data.get('tipo_operacion')
        
        if tipo_sector and tipo_operacion != 'SS-Recaudo':
            health_extension = self._build_health_sector_extension(data, makers)
            ubl_extensions.append(health_extension)
        
        empty_extension = ext.UBLExtension(ext.ExtensionContent())
        ubl_extensions.append(empty_extension)
        
        root.append(ubl_extensions)
    
    def _build_health_sector_extension(self, data, makers):
        """Construye la extensión del sector salud usando etree directamente"""
        ext = makers['ext']
        
        custom_tag = etree.Element('CustomTagGeneral')
        
        interop = etree.SubElement(custom_tag, 'Interoperabilidad')
        group = etree.SubElement(interop, 'Group')
        group.set('schemeName', 'Sector Salud')
        
        collection = etree.SubElement(group, 'Collection')
        collection.set('schemeName', 'Usuario')
        
        self._build_health_additional_information(collection, data)
        
        if self.interoperability_pt_id:
            self._build_interoperability_pt(interop, data)
        
        extension = ext.UBLExtension(ext.ExtensionContent(custom_tag))
        return extension
    
    def _build_health_additional_information(self, collection, data):
        add_info = etree.SubElement(collection, 'AdditionalInformation')
        name_el = etree.SubElement(add_info, 'Name')
        name_el.text = 'CODIGO_PRESTADOR'
        value_el = etree.SubElement(add_info, 'Value')
        value_el.text = data.get('codigo_prestador', '')
        
        add_info = etree.SubElement(collection, 'AdditionalInformation')
        name_el = etree.SubElement(add_info, 'Name')
        name_el.text = 'MODALIDAD_PAGO'
        value_el = etree.SubElement(add_info, 'Value')
        if data.get('modalidad_pago'):
            value_el.set('schemeID', data.get('modalidad_pago', ''))
            value_el.set('schemeName', 'salud_modalidad_pago.gc')
            value_el.text = data.get('modalidad_pago_nombre', '')
        
        add_info = etree.SubElement(collection, 'AdditionalInformation')
        name_el = etree.SubElement(add_info, 'Name')
        name_el.text = 'COBERTURA_PLAN_BENEFICIOS'
        value_el = etree.SubElement(add_info, 'Value')
        if data.get('cobertura_plan_beneficios'):
            value_el.set('schemeID', data.get('cobertura_plan_beneficios', ''))
            value_el.set('schemeName', 'salud_cobertura.gc')
            value_el.text = data.get('cobertura_plan_beneficios_nombre', '')
        
        # NUMERO_CONTRATO
        add_info = etree.SubElement(collection, 'AdditionalInformation')
        name_el = etree.SubElement(add_info, 'Name')
        name_el.text = 'NUMERO_CONTRATO'
        value_el = etree.SubElement(add_info, 'Value')
        value_el.text = data.get('numero_contrato', '')
        
        # NUMERO_POLIZA
        add_info = etree.SubElement(collection, 'AdditionalInformation')
        name_el = etree.SubElement(add_info, 'Name')
        name_el.text = 'NUMERO_POLIZA'
        value_el = etree.SubElement(add_info, 'Value')
        value_el.text = data.get('numero_poliza', '')
        
        # Valores monetarios (solo si no es SS-Recaudo)
        if self.fe_operation_type != 'SS-Recaudo':
            # COPAGO
            add_info = etree.SubElement(collection, 'AdditionalInformation')
            name_el = etree.SubElement(add_info, 'Name')
            name_el.text = 'COPAGO'
            value_el = etree.SubElement(add_info, 'Value')
            value_el.text = data.get('copago', '0.00')
            
            # CUOTA_MODERADORA
            add_info = etree.SubElement(collection, 'AdditionalInformation')
            name_el = etree.SubElement(add_info, 'Name')
            name_el.text = 'CUOTA_MODERADORA'
            value_el = etree.SubElement(add_info, 'Value')
            value_el.text = data.get('cuota_moderadora', '0.00')
            
            # PAGOS_COMPARTIDOS
            add_info = etree.SubElement(collection, 'AdditionalInformation')
            name_el = etree.SubElement(add_info, 'Name')
            name_el.text = 'PAGOS_COMPARTIDOS'
            value_el = etree.SubElement(add_info, 'Value')
            value_el.text = data.get('pagos_compartidos', '0.00')
            
            # ANTICIPO
            add_info = etree.SubElement(collection, 'AdditionalInformation')
            name_el = etree.SubElement(add_info, 'Name')
            name_el.text = 'ANTICIPO'
            value_el = etree.SubElement(add_info, 'Value')
            value_el.text = data.get('anticipo', '0.00')
            
            # FECHA_INICIO_PERIODO_FACTURACION
            add_info = etree.SubElement(collection, 'AdditionalInformation')
            name_el = etree.SubElement(add_info, 'Name')
            name_el.text = 'FECHA_INICIO_PERIODO_FACTURACION'
            value_el = etree.SubElement(add_info, 'Value')
            value_el.text = data.get('fecha_inicio_periodo_facturacion', '')
            
            # FECHA_FINAL_PERIODO_FACTURACION
            add_info = etree.SubElement(collection, 'AdditionalInformation')
            name_el = etree.SubElement(add_info, 'Name')
            name_el.text = 'FECHA_FINAL_PERIODO_FACTURACION'
            value_el = etree.SubElement(add_info, 'Value')
            value_el.text = data.get('fecha_final_periodo_facturacion', '')
    
    def _build_interoperability_pt(self, interop, data):
        if not self.interoperability_pt_id:
            return
            
        interop_pt = etree.SubElement(interop, 'InteroperabilidadPT')
        
        if self.interoperability_pt_id.url_download:
            url_descarga = etree.SubElement(interop_pt, 'URLDescargaAdjuntos')
            url_el = etree.SubElement(url_descarga, 'URL')
            url_el.text = self.interoperability_pt_id.url_download
            # Parámetros
            if self.interoperability_pt_id.param_excel_file or self.interoperability_pt_id.param_text_file or self.interoperability_pt_id.additional_download_params:
                params_args = etree.SubElement(url_descarga, 'ParametrosArgumentos')
                
                if self.interoperability_pt_id.param_excel_file:
                    param = etree.SubElement(params_args, 'ParametroArgumento')
                    etree.SubElement(param, 'Name').text = 'excelFile'
                    etree.SubElement(param, 'Value').text = self.interoperability_pt_id.param_excel_file
                
                if self.interoperability_pt_id.param_text_file:
                    param = etree.SubElement(params_args, 'ParametroArgumento')
                    etree.SubElement(param, 'Name').text = 'txtFile'
                    etree.SubElement(param, 'Value').text = self.interoperability_pt_id.param_text_file
                
                for add_param in self.interoperability_pt_id.additional_download_params:
                    param = etree.SubElement(params_args, 'ParametroArgumento')
                    etree.SubElement(param, 'Name').text = add_param.name
                    etree.SubElement(param, 'Value').text = add_param.value
        
        # EntregaDocumento
        if self.interoperability_pt_id.web_service_url:
            entrega_doc = etree.SubElement(interop_pt, 'EntregaDocumento')
            ws_el = etree.SubElement(entrega_doc, 'WS')
            ws_el.text = self.interoperability_pt_id.web_service_url
            
            if self.interoperability_pt_id.document_delivery_params:
                params_args = etree.SubElement(entrega_doc, 'ParametrosArgumentos')
                
                for del_param in self.interoperability_pt_id.document_delivery_params:
                    param = etree.SubElement(params_args, 'ParametroArgumento')
                    etree.SubElement(param, 'Name').text = del_param.name
                    etree.SubElement(param, 'Value').text = del_param.value
    
    # ===== MÉTODOS AUXILIARES DE PREPAGOS =====
    
    def _collect_prepaid_payments_data(self):
        """Recolecta datos de pagos anticipados incluyendo sector salud"""
        data = super()._collect_prepaid_payments_data()
        
        if self.is_health_sector and self.fe_operation_type in ['SS-CUFE', 'SS-CUDE', 'SS-POS', 'SS-SNum']:
            if 'prepaid_payments' not in data:
                data['prepaid_payments'] = []
                
            counter = len(data['prepaid_payments']) + 1
            
            # Agregar prepagos del sector salud con schemeID
            if self.copay_amount > 0:
                data['prepaid_payments'].append({
                    'id': str(counter),
                    'scheme_id': '01',
                    'amount': self.copay_amount,
                    'received_date': str(self.invoice_date),
                    'paid_date': str(self.invoice_date),
                })
                counter += 1
            
            if self.moderator_fee_amount > 0:
                data['prepaid_payments'].append({
                    'id': str(counter),
                    'scheme_id': '02',
                    'amount': self.moderator_fee_amount,
                    'received_date': str(self.invoice_date),
                    'paid_date': str(self.invoice_date),
                })
                counter += 1
            
            if self.shared_payment_amount > 0:
                data['prepaid_payments'].append({
                    'id': str(counter),
                    'scheme_id': '03',
                    'amount': self.shared_payment_amount,
                    'received_date': str(self.invoice_date),
                    'paid_date': str(self.invoice_date),
                })
                counter += 1
            
            if self.recovery_fee_amount > 0:
                data['prepaid_payments'].append({
                    'id': str(counter),
                    'scheme_id': '04',
                    'amount': self.recovery_fee_amount,
                    'received_date': str(self.invoice_date),
                    'paid_date': str(self.invoice_date),
                })
                counter += 1
            
            # Referencias de prepago
            for ref in self.health_prepaid_references:
                if ref.amount > 0:
                    data['prepaid_payments'].append({
                        'id': str(counter),
                        'scheme_id': ref.collection_concept_code or '01',
                        'amount': ref.amount,
                        'received_date': str(ref.received_date or self.invoice_date),
                        'paid_date': str(ref.paid_date or self.invoice_date),
                    })
                    counter += 1
            
            data['health_prepaid_amount'] = self.health_prepaid_amount
        
        return data
    
    def _build_prepaid_payments(self, root, data, makers):
        """Construye la sección de pagos anticipados con schemeID para sector salud"""
        cac = makers['cac']
        cbc = makers['cbc']
        
        for payment in data.get('prepaid_payments', []):
            prepaid_payment = cac.PrepaidPayment()
            
            # ID con schemeID para sector salud
            if payment.get('scheme_id'):
                prepaid_payment.append(
                    cbc.ID(payment['id'], schemeID=payment['scheme_id'])
                )
            else:
                prepaid_payment.append(cbc.ID(payment['id']))
            
            # Monto
            prepaid_payment.append(
                cbc.PaidAmount(
                    f"{payment['amount']:.2f}",
                    currencyID=data['currency_id']
                )
            )
            
            # Fecha de recepción
            prepaid_payment.append(cbc.ReceivedDate(payment['received_date']))
            
            # Fecha de pago
            if payment.get('paid_date'):
                prepaid_payment.append(cbc.PaidDate(payment['paid_date']))
            
            root.append(prepaid_payment)
    
    # ===== MÉTODOS DE VALIDACIÓN =====
    
    def _validate_health_sector_fields(self):
        """Valida todos los campos obligatorios del sector salud antes de generar XML"""
        self.ensure_one()
        
        if not self.is_health_sector:
            return True
            
        errors = []
        
        # Validar código prestador
        if not self.health_provider_code:
            errors.append(_("CODIGO_PRESTADOR: El código del prestador es obligatorio"))
        elif not self.health_provider_code.isdigit():
            errors.append(_("CODIGO_PRESTADOR: Debe contener solo dígitos"))
        elif len(self.health_provider_code) not in [10, 11, 12]:
            errors.append(_("CODIGO_PRESTADOR: Debe tener entre 10 y 12 dígitos"))
        
        # Validar modalidad de pago
        if not self.health_payment_mode_id:
            errors.append(_("MODALIDAD_PAGO: La modalidad de pago es obligatoria"))
        
        # Validar cobertura
        if not self.health_coverage_plan_id:
            errors.append(_("COBERTURA_PLAN_BENEFICIOS: La cobertura del plan de beneficios es obligatoria"))
        
        # Validar número de contrato
        if not self.contract_id and self.health_coverage_plan_id and self.health_coverage_plan_id.code != '15':
            errors.append(_("NUMERO_CONTRATO: El número de contrato es obligatorio excepto para cobertura Particular"))
        
        # Validar póliza para coberturas específicas
        requires_policy = ['04', '05', '13', '14']
        if self.health_coverage_plan_id and self.health_coverage_plan_id.code in requires_policy:
            if not self.contract_id or not self.contract_id.policy_ids:
                coverage_name = self.health_coverage_plan_id.name
                errors.append(_("NUMERO_POLIZA: El número de póliza es obligatorio para %s") % coverage_name)
        
        # Validar fechas del período
        if not self.date_start:
            errors.append(_("FECHA_INICIO_PERIODO_FACTURACION: La fecha de inicio del período es obligatoria"))
        if not self.date_end:
            errors.append(_("FECHA_FINAL_PERIODO_FACTURACION: La fecha de fin del período es obligatoria"))
        
        if self.date_start and self.date_end:
            if self.date_start > self.date_end:
                errors.append(_("Las fechas del período: La fecha de inicio no puede ser posterior a la fecha fin"))
            
            days_diff = (self.date_end - self.date_start).days
            if days_diff > 30:
                errors.append(_("Las fechas del período: El período de facturación no puede exceder 30 días"))
        
        # Validar valores según tipo de operación
        if self.fe_operation_type == 'SS-CUFE':
            total_recaudo = (self.copay_amount or 0) + (self.moderator_fee_amount or 0) + \
                           (self.shared_payment_amount or 0) + (self.recovery_fee_amount or 0)
            if total_recaudo <= 0:
                errors.append(_("SS-CUFE: Requiere al menos un valor de recaudo mayor a cero"))
        
        elif self.fe_operation_type == 'SS-SinAporte':
            if any([
                self.copay_amount > 0,
                self.moderator_fee_amount > 0,
                self.shared_payment_amount > 0,
                self.recovery_fee_amount > 0
            ]):
                errors.append(_("SS-SinAporte: No debe tener valores de recaudo mayores a cero"))
        
        if errors:
            self.health_validation_status = 'error'
            self.health_validation_message = '\n'.join(errors)
        
        self.health_validation_status = 'validated'
        self.health_validation_message = _('Validación exitosa')
        
        return True
    
    def generate_dian_xml(self):
        """Sobrescribe para agregar validación del sector salud antes de generar XML"""
        if self.is_health_sector:
            self._validate_health_sector_fields()
        
        return super().generate_dian_xml()
    
    # ===== MÉTODOS ONCHANGE =====
    
    @api.onchange('fe_operation_type')
    def _onchange_fe_operation_type_health(self):
        """Ajusta campos según el tipo de operación de salud"""
        if self.fe_operation_type == 'SS-SinAporte':
            self.copay_amount = 0
            self.moderator_fee_amount = 0
            self.shared_payment_amount = 0
            self.recovery_fee_amount = 0
        
        if self.fe_operation_type in ['SS-CUFE', 'SS-CUDE', 'SS-POS', 'SS-SNum', 'SS-SinAporte']:
            if not self.date_start:
                self.date_start = self.invoice_date or fields.Date.today()
            if not self.date_end:
                self.date_end = self.invoice_date or fields.Date.today()
    
    def action_validate_health_fields(self):
        """Acción manual para validar campos del sector salud"""
        self.ensure_one()
        try:
            self._validate_health_sector_fields()
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Validación Exitosa'),
                    'message': _('Todos los campos del sector salud están correctos'),
                    'type': 'success',
                    'sticky': False,
                }
            }
        except ValidationError as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Error de Validación'),
                    'message': str(e),
                    'type': 'danger',
                    'sticky': True,
                }
            }

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('journal_id'):
                journal = self.env['account.journal'].browse(vals['journal_id'])
                self._update_health_defaults_from_journal(vals, journal)
        
        return super().create(vals_list)
    
    def write(self, vals):
        if vals.get('journal_id'):
            journal = self.env['account.journal'].browse(vals['journal_id'])
            self._update_health_defaults_from_journal(vals, journal)
        
        # Si se cambia el tipo de operación, validar coherencia
        if vals.get('fe_operation_type'):
            self._validate_operation_type_change(vals['fe_operation_type'])
        
        return super().write(vals)
    
    def _update_health_defaults_from_journal(self, vals, journal):
        """Actualiza valores por defecto desde el diario"""
        if journal.health_operation_type and 'fe_operation_type' not in vals:
            vals['fe_operation_type'] = journal.health_operation_type
        
        if journal.default_health_coverage_plan_id and 'health_coverage_plan_id' not in vals:
            vals['health_coverage_plan_id'] = journal.default_health_coverage_plan_id.id
        
        if journal.default_health_payment_mode_id and 'health_payment_mode_id' not in vals:
            vals['health_payment_mode_id'] = journal.default_health_payment_mode_id.id
        
        if journal.default_health_collection_concept_id and 'health_collection_concept_id' not in vals:
            vals['health_collection_concept_id'] = journal.default_health_collection_concept_id.id
        
        if journal.default_health_provider_code and 'health_provider_code' not in vals:
            vals['health_provider_code'] = journal.default_health_provider_code
    
    def _validate_operation_type_change(self, new_operation_type):
        """Valida que el cambio de tipo de operación sea coherente"""
        for record in self:
            if record.state == 'posted' and record.is_health_sector:
                if record.fe_operation_type in ['SS-CUFE', 'SS-SinAporte'] and new_operation_type == 'SS-Recaudo':
                    raise ValidationError(_('No se puede cambiar una factura de servicios a recaudo después de publicada'))
                
                if record.fe_operation_type == 'SS-Recaudo' and new_operation_type in ['SS-CUFE', 'SS-SinAporte']:
                    raise ValidationError(_('No se puede cambiar un recaudo a factura de servicios después de publicado'))
    
    # ===== MÉTODOS ONCHANGE PARA ACTUALIZACIÓN AUTOMÁTICA =====
    
    @api.onchange('journal_id')
    def _onchange_journal_id_health(self):
        """Carga valores por defecto del diario para sector salud"""
        if self.journal_id and not self._origin.id:  # Solo para registros nuevos
            if self.journal_id.health_operation_type:
                self.fe_operation_type = self.journal_id.health_operation_type
            
            if self.journal_id.default_health_coverage_plan_id:
                self.health_coverage_plan_id = self.journal_id.default_health_coverage_plan_id
            
            if self.journal_id.default_health_payment_mode_id:
                self.health_payment_mode_id = self.journal_id.default_health_payment_mode_id
            
            if self.journal_id.default_health_collection_concept_id:
                self.health_collection_concept_id = self.journal_id.default_health_collection_concept_id
            
            if self.journal_id.default_health_provider_code:
                self.health_provider_code = self.journal_id.default_health_provider_code
    
    @api.onchange('move_type', 'reversed_entry_id', 'debit_origin_id', 'document_without_reference')
    def _onchange_document_type_health(self):
        """Actualiza el tipo de documento según las referencias y el sector salud"""
        if not self.is_health_sector:
            return
        
        # Para notas crédito
        if self.move_type == 'out_refund':
            if self.reversed_entry_id and self.reversed_entry_id.fe_operation_type == 'SS-CUFE':
                self.fe_operation_type = 'SS-CUDE'
            elif self.document_without_reference:
                self.fe_operation_type = '22'
            else:
                self.fe_operation_type = '20'
        
        # Para notas débito
        elif self.is_debit_note:
            if self.debit_origin_id and self.debit_origin_id.is_health_sector:
                self.fe_operation_type = self.debit_origin_id.fe_operation_type
            elif self.document_without_reference:
                self.fe_operation_type = '32'
            else:
                self.fe_operation_type = '30'
    
    @api.onchange('partner_id')
    def _onchange_partner_id_health(self):
        """Busca contratos activos y carga información del partner"""
        if self.partner_id and self.is_health_sector:
            # Buscar contratos activos
            active_contracts = self.env['customer.contract'].search([
                ('partner_id', '=', self.partner_id.id),
                '|',
                ('end_date', '=', False),
                ('end_date', '>=', fields.Date.today())
            ])
            
            if len(active_contracts) == 1:
                self.contract_id = active_contracts[0]
                self._load_contract_data()
    
    @api.onchange('contract_id')
    def _onchange_contract_id(self):
        """Carga datos del contrato seleccionado"""
        if self.contract_id:
            self._load_contract_data()
    
    def _load_contract_data(self):
        """Carga información del contrato en la factura"""
        if not self.contract_id:
            return
        
        if self.contract_id.payment_method and not self.health_payment_mode_id:
            payment_mode = self.env['health.payment.mode'].search([
                ('code', '=', self.contract_id.payment_method)
            ], limit=1)
            if payment_mode:
                self.health_payment_mode_id = payment_mode
        
        if self.contract_id.benefit_plan_ids:
            self.benefit_plan_ids = [(6, 0, self.contract_id.benefit_plan_ids.ids)]
    
    @api.onchange('health_payment_mode_id')
    def _onchange_health_payment_mode_id(self):
        """Ajusta campos según la modalidad de pago seleccionada"""
        if self.health_payment_mode_id:
            if self.health_payment_mode_id.requires_period_dates:
                if not self.date_start:
                    self.date_start = fields.Date.today().replace(day=1)
                if not self.date_end:
                    import calendar
                    last_day = calendar.monthrange(self.date_start.year, self.date_start.month)[1]
                    self.date_end = self.date_start.replace(day=last_day)
            
            if self.health_payment_mode_id.is_prospective and self.health_payment_mode_id.risk_level == 'high':
                if self.fe_operation_type in ['SS-CUFE', 'SS-Recaudo']:
                    self.fe_operation_type = 'SS-SinAporte'
    
    @api.onchange('health_coverage_plan_id')
    def _onchange_health_coverage_plan_id(self):
        """Actualiza campos según el plan de cobertura seleccionado"""
        if self.health_coverage_plan_id:
            # Advertir si requiere póliza
            if self.health_coverage_plan_id.requires_policy:
                if not self.contract_id or not self.contract_id.policy_ids:
                    return {
                        'warning': {
                            'title': _('Póliza Requerida'),
                            'message': _('La cobertura %s requiere número de póliza. '
                                       'Asegúrese de que el contrato tenga una póliza asociada.') % 
                                       self.health_coverage_plan_id.name
                        }
                    }
            
            if self.health_coverage_plan_id.code == '15': 
                no_aplica = self.env['health.collection.concept'].search([
                    ('code', '=', '05')
                ], limit=1)
                if no_aplica:
                    self.health_collection_concept_id = no_aplica
                
                if self.fe_operation_type == 'SS-Recaudo':
                    self.fe_operation_type = 'SS-SinAporte'
    
    @api.onchange('health_collection_concept_id')
    def _onchange_health_collection_concept_id(self):
        """Actualiza el tipo de operación según el concepto de recaudo"""
        if self.health_collection_concept_id:
            if self.health_collection_concept_id.code == '05':  # NO APLICA
                if self.fe_operation_type == 'SS-Recaudo':
                    self.fe_operation_type = 'SS-SinAporte'
            else:
                if not self._origin.id and self.fe_operation_type not in ['SS-CUFE', 'SS-Recaudo']:
                    self.fe_operation_type = 'SS-Recaudo'
    
    @api.onchange('fe_operation_type')
    def _onchange_fe_operation_type_complete(self):
        """Maneja cambios completos en el tipo de operación"""
        self._onchange_fe_operation_type_health()
        
        if self.fe_operation_type == 'SS-Recaudo':
            if not self.invoice_line_ids:
                self._create_automatic_collection_line()
        
        elif self.fe_operation_type in ['SS-CUDE', 'SS-POS', 'SS-SNum']:
            if self.fe_operation_type == 'SS-CUDE' and not self.health_contingency_cude:
                return {
                    'warning': {
                        'title': _('Información Requerida'),
                        'message': _('Para SS-CUDE debe indicar el CUDE del documento de contingencia')
                    }
                }
            elif self.fe_operation_type == 'SS-POS' and not self.health_pos_authorization:
                return {
                    'warning': {
                        'title': _('Información Requerida'),
                        'message': _('Para SS-POS debe indicar el número de autorización POS')
                    }
                }
            elif self.fe_operation_type == 'SS-SNum' and not self.health_paper_range:
                return {
                    'warning': {
                        'title': _('Información Requerida'),
                        'message': _('Para SS-SNum debe indicar el rango de numeración en papel')
                    }
                }
    
    def _create_automatic_collection_line(self):
        """Crea una línea automática para documentos de recaudo"""
        if self.fe_operation_type != 'SS-Recaudo' or self.invoice_line_ids:
            return
        
        # Buscar producto de recaudo
        product = self.env['product.product'].search([
            ('default_code', '=', 'RECAUDO_SALUD')
        ], limit=1)
        
        if not product:
            # Crear producto si no existe
            product = self.env['product.product'].create({
                'name': 'Recaudo Sector Salud',
                'default_code': 'RECAUDO_SALUD',
                'type': 'service',
                'sale_ok': True,
                'purchase_ok': False,
                'list_price': 0.0,
            })
        
        # Determinar el monto según el concepto
        amount = 0.0
        if self.health_collection_concept_id:
            if self.health_collection_concept_id.code == '01':
                amount = self.copay_amount
            elif self.health_collection_concept_id.code == '02':
                amount = self.moderator_fee_amount
            elif self.health_collection_concept_id.code == '03':
                amount = self.shared_payment_amount
            elif self.health_collection_concept_id.code == '04':
                amount = self.recovery_fee_amount
        
        if amount > 0:
            self.invoice_line_ids = [(0, 0, {
                'product_id': product.id,
                'name': f'Recaudo - {self.health_collection_concept_id.name}',
                'quantity': 1,
                'price_unit': amount,
            })]
    

    
    def action_load_health_defaults(self):
        """Acción para cargar valores por defecto del sector salud"""
        self.ensure_one()

        if self.journal_id:
            vals = {}
            self._update_health_defaults_from_journal(vals, self.journal_id)
            if vals:
                self.write(vals)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Valores Cargados'),
                'message': _('Se han cargado los valores por defecto del diario'),
                'type': 'success',
                'sticky': False,
            }
        }

    # =========================================================================
    # INTEGRACIÓN DIAN PARA SECTOR SALUD
    # =========================================================================

    def action_send_health_to_dian(self):
        """
        Envía documento del sector salud a DIAN con validaciones específicas.
        Extiende el método base agregando validaciones del sector salud.
        """
        self.ensure_one()

        # Validaciones específicas del sector salud
        if self.is_health_sector:
            self._validate_health_requirements()

        # Llamar al método base de envío DIAN
        return self.action_send_to_dian()

    def _validate_health_requirements(self):
        """Valida requisitos específicos del sector salud para DIAN"""
        self.ensure_one()

        errors = []

        # Validar código del prestador
        if not self.health_provider_code:
            errors.append("Código del prestador de salud es obligatorio")

        # Validar fechas de periodo
        if not self.date_start or not self.date_end:
            errors.append("Las fechas de inicio y fin del periodo son obligatorias")

        if self.date_start and self.date_end and self.date_start > self.date_end:
            errors.append("La fecha de inicio no puede ser posterior a la fecha de fin")

        # Validaciones según tipo de operación
        if self.fe_operation_type == 'SS-CUFE':
            if not (self.copay_amount or self.moderator_fee_amount or
                   self.recovery_fee_amount or self.shared_payment_amount):
                errors.append("SS-CUFE requiere al menos un valor de aporte del usuario")

        elif self.fe_operation_type == 'SS-CUDE':
            if not self.health_contingency_cude:
                errors.append("SS-CUDE requiere el CUDE del documento de contingencia")

        elif self.fe_operation_type == 'SS-POS':
            if not self.health_pos_authorization:
                errors.append("SS-POS requiere número de autorización")

        elif self.fe_operation_type == 'SS-SNum':
            if not self.health_paper_range:
                errors.append("SS-SNum requiere rango de numeración en papel")

        elif self.fe_operation_type == 'SS-Recaudo':
            if not self.health_collection_concept_id:
                errors.append("SS-Recaudo requiere concepto de recaudo")

        # Validar modalidad de pago y cobertura
        if self.fe_operation_type in ['SS-CUFE', 'SS-SinAporte']:
            if not self.health_payment_mode_id:
                errors.append("Modalidad de pago es obligatoria para facturas de servicios")

            if not self.health_coverage_plan_id:
                errors.append("Tipo de cobertura es obligatorio para facturas de servicios")

        # Validar usuarios
        if self.health_users:
            for user in self.health_users:
                if not user.identification_type_id or not user.identification_number:
                    errors.append(f"Usuario {user.name}: Falta tipo o número de identificación")

                if not user.user_type_id:
                    errors.append(f"Usuario {user.name}: Falta tipo de usuario")

        if errors:
            raise UserError(_("Requisitos del sector salud faltantes:\n• " + "\n• ".join(errors)))

    def _prepare_health_xml_data(self):
        """
        Prepara datos adicionales del sector salud para el XML DIAN.
        Este método enriquece los datos con información específica de salud.
        """
        self.ensure_one()

        data = {}

        if self.is_health_sector:
            # Datos del prestador
            data['health_sector'] = {
                'provider_code': self.health_provider_code,
                'provider_name': self.company_id.partner_id.name,
                'provider_nit': self.company_id.partner_id.vat,
                'period_start': self.date_start.isoformat() if self.date_start else '',
                'period_end': self.date_end.isoformat() if self.date_end else '',
            }

            # Datos de pagos
            data['health_payments'] = {
                'copay': self.copay_amount,
                'moderator_fee': self.moderator_fee_amount,
                'recovery_fee': self.recovery_fee_amount,
                'shared_payment': self.shared_payment_amount,
                'prepaid_amount': self.health_prepaid_amount,
            }

            # Modalidad y cobertura
            if self.health_payment_mode_id:
                data['payment_mode'] = {
                    'code': self.health_payment_mode_id.code,
                    'name': self.health_payment_mode_id.name,
                }

            if self.health_coverage_plan_id:
                data['coverage_plan'] = {
                    'code': self.health_coverage_plan_id.code,
                    'name': self.health_coverage_plan_id.name,
                }

            # Usuarios del servicio
            if self.health_users:
                data['health_users'] = []
                for user in self.health_users:
                    data['health_users'].append({
                        'name': user.name,
                        'identification_type': user.identification_type_id.l10n_co_document_code,
                        'identification_number': user.identification_number,
                        'user_type': user.user_type_id.code,
                        'regime_type': user.regime_type_id.code if user.regime_type_id else '',
                        'authorization_numbers': user.authorization_numbers or '',
                    })

            # Datos específicos según tipo de operación
            if self.fe_operation_type == 'SS-CUDE':
                data['contingency_cude'] = self.health_contingency_cude
            elif self.fe_operation_type == 'SS-POS':
                data['pos_authorization'] = self.health_pos_authorization
            elif self.fe_operation_type == 'SS-SNum':
                data['paper_range'] = self.health_paper_range
            elif self.fe_operation_type == 'SS-Recaudo':
                data['collection_concept'] = {
                    'code': self.health_collection_concept_id.code,
                    'name': self.health_collection_concept_id.name,
                } if self.health_collection_concept_id else {}

        return data

    def _get_health_xml_template(self):
        """
        Retorna el template XML específico según el tipo de operación de salud.
        """
        self.ensure_one()

        template_map = {
            'SS-CUFE': 'l10n_co_rips.health_invoice_cufe_template',
            'SS-CUDE': 'l10n_co_rips.health_invoice_cude_template',
            'SS-POS': 'l10n_co_rips.health_invoice_pos_template',
            'SS-SNum': 'l10n_co_rips.health_invoice_paper_template',
            'SS-Recaudo': 'l10n_co_rips.health_collection_template',
            'SS-Reporte': 'l10n_co_rips.health_report_template',
            'SS-SinAporte': 'l10n_co_rips.health_invoice_no_contribution_template',
        }

        if self.fe_operation_type in template_map:
            return template_map[self.fe_operation_type]

        # Si no es tipo de salud, retornar False para usar template estándar
        return False

    def generate_health_dian_xml(self):
        """
        Genera el XML específico para documentos del sector salud.
        Sobrescribe el método base cuando aplica.
        """
        self.ensure_one()

        # Si no es sector salud, usar generación estándar
        if not self.is_health_sector:
            return super().generate_dian_xml()

        # Preparar datos combinados
        data = self._collect_all_dian_data()
        health_data = self._prepare_health_xml_data()
        data.update(health_data)

        # Obtener template específico de salud
        template_id = self._get_health_xml_template()

        if not template_id:
            # Usar template estándar con datos de salud
            return super().generate_dian_xml()

        try:
            # Generar XML con template de salud
            xml_content = self.env['ir.qweb']._render(template_id, data)
            return xml_content
        except Exception as e:
            _logger.error(f"Error generando XML de salud para {self.name}: {str(e)}")
            raise UserError(_(f"Error al generar XML del sector salud: {str(e)}"))
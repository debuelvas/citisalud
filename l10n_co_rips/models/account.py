from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
import json
import base64
import requests
import gzip
from datetime import datetime, date, timedelta
from decimal import Decimal, ROUND_HALF_UP
import ssl
import socket
import certifi
from urllib.parse import urlparse
import urllib3
import logging

_logger = logging.getLogger(__name__)

# =====================================================
# CONFIGURACIÓN GLOBAL RIPS FEV-RIPS v4.2
# =====================================================

# ENDPOINTS API RIPS - Según Manual v4.2
RIPS_ENDPOINTS = {
    'AUTH': '/api/Auth/LoginSISPRO',
    'CARGAR_FEV_RIPS': '/api/PaquetesFevRips/CargarFevRips',
    'CARGAR_NC': '/api/PaquetesFevRips/CargarNC',
    'CARGAR_NC_TOTAL': '/api/PaquetesFevRips/CargarNCTotal',
    'CARGAR_ND': '/api/PaquetesFevRips/CargarND',
    'CARGAR_NOTA_AJUSTE': '/api/PaquetesFevRips/CargarNotaAjuste',
    'CARGAR_RIPS_SIN_FACTURA': '/api/PaquetesFevRips/CargarRipsSinFactura',
    'CARGAR_NC_ACUERDO_VOLUNTADES': '/api/PaquetesFevRips/CargarNCAcuerdoVoluntades',
    'CARGAR_CAPITA_INICIAL': '/api/PaquetesFevRips/CargarCapitaInicial',
    'CARGAR_CAPITA_PERIODO': '/api/PaquetesFevRips/CargarCapitaPeriodo',
    'CARGAR_CAPITA_FINAL': '/api/PaquetesFevRips/CargarCapitaFinal',
    'CONSULTAR_CUV': '/api/ConsultasFevRips/ConsultarCUV',
    'DESCARGAR_ARCHIVOS': '/api/ConsultasFevRips/DescargarArchivosFevRipsCUV',
}

# VALORES POR DEFECTO RIPS
RIPS_DEFAULT_VALUES = {
    'CODIGO_PRESTADOR': '000000000000',
    'MODALIDAD_ATENCION': '01',
    'GRUPO_SERVICIO_CONSULTA': '01',
    'GRUPO_SERVICIO_PROCEDIMIENTO': '02',
    'GRUPO_SERVICIO_MEDICAMENTO': '02',
    'GRUPO_SERVICIO_OTRO': '04',
    'COD_SERVICIO_CONSULTA': 101,
    'COD_SERVICIO_PROCEDIMIENTO': 706,
    'COD_SERVICIO_MEDICAMENTO': 312,
    'COD_SERVICIO_OTRO': 950,
    'FINALIDAD_CONSULTA': '10',
    'FINALIDAD_PROCEDIMIENTO': '44',
    'CAUSA_EXTERNA': '13',
    'TIPO_DIAGNOSTICO': '01',
    'CONCEPTO_RECAUDO': '05',
    'VIA_INGRESO': '01',
    'DIAGNOSTICO_DEFAULT': 'Z000',
    'PROFESIONAL_DOC_TYPE': 'CC',
    'PROFESIONAL_DOC_NUMBER': '1234567890',
    'CUPS_CONSULTA': '890201',
    'CUPS_PROCEDIMIENTO': '000000',
    'TIPO_USUARIO': '01',
    'ZONA_TERRITORIAL': '01',
    'PAIS_DEFAULT': '170',
    'MUNICIPIO_DEFAULT': '11001',
}

# Mapeo de tipos de carga a endpoints
LOAD_TYPE_MAPPING = {
    'CARGAR_FEV_RIPS': 'fev_rips',
    'CARGAR_NC': 'nc',
    'CARGAR_NC_TOTAL': 'nc_total',
    'CARGAR_ND': 'nd',
    'CARGAR_NOTA_AJUSTE': 'nota_ajuste',
    'CARGAR_RIPS_SIN_FACTURA': 'sin_factura',
    'CARGAR_NC_ACUERDO_VOLUNTADES': 'nc_acuerdo',
    'CARGAR_CAPITA_INICIAL': 'capita_inicial',
    'CARGAR_CAPITA_PERIODO': 'capita_periodo',
    'CARGAR_CAPITA_FINAL': 'capita_final',
}


class AbstractRipsFevMixin(models.AbstractModel):
    """
    Modelo abstracto para manejo de RIPS FEV-RIPS v4.2
    Implementa toda la lógica de integración con el sistema del Ministerio de Salud
    """
    _name = 'abstract.rips.fev.mixin'
    _description = 'Abstract RIPS FEV Mixin'
    
    # =====================================================
    # CAMPOS RIPS
    # =====================================================
    
    rips_cuv = fields.Char(
        string='CUV (Código Único de Validación)',
        readonly=True,
        copy=False,
        index=True,
        help="Código único asignado por el Ministerio de Salud que certifica la validación del RIPS"
    )
    
    rips_validation_date = fields.Datetime(
        string='Fecha de Validación RIPS',
        readonly=True
    )
    
    rips_validation_status = fields.Selection([
        ('draft', 'Borrador'),
        ('generated', 'Generado'),
        ('sent', 'Enviado'),
        ('validated', 'Validado'),
        ('rejected', 'Rechazado'),
        ('error', 'Error')
    ], string='Estado RIPS', default='draft', readonly=True, index=True)
    
    rips_proceso_id = fields.Char(
        string='ID Proceso RIPS',
        readonly=True,
        help="ID del proceso asignado por el Ministerio de Salud"
    )
    
    rips_response_json = fields.Text(
        string='Respuesta JSON del Ministerio',
        readonly=True
    )
    
    rips_errors = fields.Text(
        string='Errores de Validación',
        readonly=True
    )
    
    rips_consultation_history = fields.Text(
        string='Histórico de Consultas RIPS',
        readonly=True,
        help="Registro histórico de todas las consultas realizadas al sistema RIPS"
    )
    
    rips_last_load_type = fields.Selection([
        ('fev_rips', 'Factura con RIPS'),
        ('nc', 'Nota Crédito'),
        ('nc_total', 'Nota Crédito Total'),
        ('nd', 'Nota Débito'),
        ('nota_ajuste', 'Nota de Ajuste'),
        ('sin_factura', 'RIPS sin Factura'),
        ('nc_acuerdo', 'NC Acuerdo Voluntades'),
        ('capita_inicial', 'Cápita Inicial'),
        ('capita_periodo', 'Cápita Período'),
        ('capita_final', 'Cápita Final'),
    ], string='Último Tipo de Carga', readonly=True)
    
    # Campos JSON
    rips_json = fields.Text(
        string='RIPS JSON',
        readonly=True
    )
    
    rips_json_binary = fields.Binary(
        string='Archivo RIPS JSON',
        readonly=True,
        attachment=True
    )
    
    rips_json_filename = fields.Char(
        string='Nombre Archivo RIPS',
        readonly=True
    )
    
    rips_generated = fields.Boolean(
        string='RIPS Generado',
        readonly=True
    )
    
    rips_result_binary = fields.Binary(
        string='Archivo de Resultado RIPS',
        readonly=True,
        attachment=True
    )
    
    rips_result_filename = fields.Char(
        string='Nombre Archivo Resultado',
        readonly=True
    )
    
    rips_errors_html_binary = fields.Binary(
        string='Reporte HTML de Errores',
        readonly=True,
        attachment=True
    )
    
    rips_errors_html_filename = fields.Char(
        string='Nombre Archivo HTML Errores',
        readonly=True
    )
    
    rips_errors_html = fields.Html(
        string='Errores de Validación HTML',
        readonly=True,
        sanitize=False,
        default=False
    )
    
    # =====================================================
    # MÉTODOS PRINCIPALES DE ENVÍO
    # =====================================================
    def action_view_rips_errors_html(self):
        """Muestra los errores de validacion RIPS en formato HTML"""
        self.ensure_one()

        if not self.rips_validation_errors:
            raise UserError(_("No hay errores de validacion para mostrar"))

        # OPTIMIZADO: Sanitizar HTML para prevenir XSS
        import html

        # Parsear los errores
        errors_html = "<html><head><style>"
        errors_html += """
            body { font-family: Arial, sans-serif; padding: 20px; }
            h2 { color: #dc3545; }
            .error-item {
                background: #f8f9fa;
                border-left: 4px solid #dc3545;
                padding: 10px;
                margin: 10px 0;
            }
            .error-title { font-weight: bold; color: #495057; }
            .error-desc { color: #6c757d; margin-top: 5px; }
        """
        errors_html += "</style></head><body>"
        errors_html += f"<h2>Errores de Validacion - Factura {html.escape(self.name)}</h2>"

        try:
            errors = json.loads(self.rips_validation_errors)
            if isinstance(errors, list):
                for error in errors:
                    if isinstance(error, dict):
                        error_html = '<div class="error-item">'
                        campo = html.escape(str(error.get("Campo", "Error")))
                        descripcion = html.escape(str(error.get("Descripcion", str(error))))
                        error_html += f'<div class="error-title">{campo}</div>'
                        error_html += f'<div class="error-desc">{descripcion}</div>'
                        error_html += '</div>'
                        errors_html += error_html
                    else:
                        error_escaped = html.escape(str(error))
                        errors_html += f'<div class="error-item"><div class="error-desc">{error_escaped}</div></div>'
            else:
                errors_escaped = html.escape(str(errors))
                errors_html += f'<div class="error-item"><div class="error-desc">{errors_escaped}</div></div>'
        except:
            validation_errors_escaped = html.escape(self.rips_validation_errors)
            errors_html += f'<div class="error-item"><div class="error-desc">{validation_errors_escaped}</div></div>'

        errors_html += "</body></html>"
        
        # Crear un wizard para mostrar el HTML
        wizard = self.env['rips.error.viewer.wizard'].create({
            'name': f'Errores de Validación - {self.name}',
            'html_content': errors_html,
        })
        
        return {
            'type': 'ir.actions.act_window',
            'name': f'Errores RIPS - {self.name}',
            'res_model': 'rips.error.viewer.wizard',
            'view_mode': 'form',
            'res_id': wizard.id,
            'target': 'new',
        }
        
    def mass_action_send_rips_to_min(self):
        """
        Envio masivo de RIPS al Ministerio de Salud.
        OPTIMIZADO: Procesamiento batch con manejo de errores y consultas automaticas.
        """
        if not self:
            raise UserError(_("No hay registros seleccionados"))

        # Obtener configuracion una sola vez
        config = self[0]._get_rips_config()

        success_count = 0
        error_count = 0
        already_sent_count = 0
        total = len(self)

        _logger.info(f"Iniciando envio masivo de {total} registros RIPS")

        for idx, move in enumerate(self, 1):
            try:
                _logger.info(f"Procesando {idx}/{total}: {move.name}")

                # Verificar si ya tiene CUV
                if move.rips_cuv and move.rips_validation_status in ['validated', 'sent']:
                    _logger.info(f"Registro {move.name} ya tiene CUV: {move.rips_cuv}, consultando estado...")
                    already_sent_count += 1

                    # Consultar estado automaticamente
                    try:
                        cuv_status = move._consult_cuv_status_internal(move.rips_cuv, config)
                        if cuv_status.get('success'):
                            data = cuv_status.get('data', {})
                            is_valid = data.get('ResultState') or data.get('EsValido')

                            if is_valid:
                                move._update_cuv_as_validated(data)
                                _logger.info(f"CUV {move.rips_cuv} validado exitosamente")
                            else:
                                _logger.warning(f"CUV {move.rips_cuv} aun no validado")
                    except Exception as e:
                        _logger.error(f"Error consultando CUV {move.rips_cuv}: {str(e)}")

                    continue

                # Generar y enviar RIPS
                move.generate_rips_json_api()
                endpoint_key, payload = move._determine_rips_endpoint_and_payload()
                move.rips_last_load_type = LOAD_TYPE_MAPPING.get(endpoint_key)

                result = move._send_to_sispro_endpoint(endpoint_key, payload, config)
                move._log_rips_consultation(endpoint_key, payload, result, result['success'])

                if result['success']:
                    move._process_successful_response(result)
                    success_count += 1
                    _logger.info(f"Enviado exitosamente: {move.name} - CUV: {result.get('cuv')}")
                else:
                    # Verificar si ya estaba aprobado (enviado previamente)
                    if move._check_cuv_already_approved(result):
                        extracted_cuv = move._extract_cuv_from_error(result)

                        if extracted_cuv:
                            _logger.info(f"{move.name} ya fue enviado, CUV: {extracted_cuv}, consultando automaticamente...")

                            move.write({
                                'rips_cuv': extracted_cuv,
                                'rips_proceso_id': str(result.get('proceso_id', '')) if result.get('proceso_id') else False,
                                'rips_validation_status': 'sent',
                                'rips_validation_date': fields.Datetime.now()
                            })

                            # SIEMPRE consultar automaticamente el estado del CUV
                            try:
                                cuv_status = move._consult_cuv_status_internal(extracted_cuv, config)

                                if cuv_status.get('success'):
                                    data = cuv_status.get('data', {})
                                    is_valid = data.get('ResultState') or data.get('EsValido')

                                    # Crear archivo de resultado
                                    move._create_result_file(data)

                                    if is_valid:
                                        move._update_cuv_as_validated(data)
                                        success_count += 1
                                        already_sent_count += 1
                                        _logger.info(f"CUV {extracted_cuv} validado: {move.name}")
                                        continue
                                    else:
                                        validaciones = data.get('ResultadosValidacion', [])
                                        if validaciones:
                                            move._create_errors_html_file(data, validaciones)
                                            move.write({'rips_validation_status': 'rejected'})
                                            error_count += 1
                                            _logger.warning(f"CUV {extracted_cuv} rechazado con {len(validaciones)} errores")
                                        else:
                                            already_sent_count += 1
                                            _logger.info(f"CUV {extracted_cuv} pendiente de validacion")
                                        continue
                                else:
                                    _logger.error(f"Error consultando CUV {extracted_cuv}: {cuv_status.get('error')}")
                                    error_count += 1
                            except Exception as e:
                                _logger.error(f"Excepcion consultando CUV {extracted_cuv}: {str(e)}")
                                error_count += 1
                        else:
                            _logger.error(f"No se pudo extraer CUV de {move.name}")
                            error_count += 1
                    else:
                        move._process_error_response(result)
                        error_count += 1
                        _logger.error(f"Error enviando {move.name}: {result.get('error', 'Error desconocido')}")

                # Commit cada 5 registros
                if idx % 5 == 0:
                    self.env.cr.commit()
                    _logger.info(f"Progreso guardado: {idx}/{total}")

            except Exception as e:
                error_count += 1
                _logger.error(f"Excepcion procesando {move.name}: {str(e)}")
                continue

        # Commit final
        self.env.cr.commit()

        # Mensaje de resumen
        message = f"Envio masivo completado:\n"
        message += f"- Exitosos: {success_count}\n"
        message += f"- Ya enviados (consultados): {already_sent_count}\n"
        message += f"- Errores: {error_count}\n"
        message += f"- Total procesados: {total}"

        _logger.info(message)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Envio Masivo RIPS Completado'),
                'message': message,
                'type': 'success' if error_count == 0 else 'warning',
                'sticky': True,
            }
        }
            
    def action_send_rips_to_minsalud(self):
        """
        Envia RIPS al Ministerio de Salud.
        OPTIMIZADO: Consulta automatica si el CUV ya existe.
        """
        self.ensure_one()

        endpoint_key = None
        try:
            config = self._get_rips_config()

            # Verificar si ya tiene CUV y esta validado/enviado
            if self.rips_cuv and self.rips_validation_status in ['validated', 'sent']:
                _logger.info(f"Factura {self.name} ya tiene CUV: {self.rips_cuv}, consultando estado automaticamente...")
                return self._consult_and_update_existing_cuv(config)

            self.generate_rips_json_api()
            endpoint_key, payload = self._determine_rips_endpoint_and_payload()

            self.rips_last_load_type = LOAD_TYPE_MAPPING.get(endpoint_key)

            result = self._send_to_sispro_endpoint(endpoint_key, payload, config)
            self._log_rips_consultation(endpoint_key, payload, result, result['success'])

            if result['success']:
                return self._handle_successful_send(result)
            else:
                return self._handle_failed_send(result, config)

        except Exception as e:
            self._log_rips_consultation(
                endpoint_key or 'UNKNOWN',
                {},
                {'error': str(e), 'status_code': None},
                False
            )
            raise

    def _consult_and_update_existing_cuv(self, config):
        """Consulta y actualiza el estado de un CUV existente"""
        try:
            cuv_status = self._consult_cuv_status_internal(self.rips_cuv, config)

            if cuv_status.get('success'):
                data = cuv_status.get('data', {})
                is_valid = data.get('ResultState') or data.get('EsValido')

                if is_valid:
                    self._update_cuv_as_validated(data)
                    self._create_result_file(data)

                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': _('CUV ya Validado'),
                            'message': _('El CUV %s ya esta validado por el Ministerio') % self.rips_cuv,
                            'type': 'success',
                            'sticky': False,
                        }
                    }
                else:
                    validaciones = data.get('ResultadosValidacion', [])
                    if validaciones:
                        self._create_errors_html_file(data, validaciones)

                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': _('CUV Pendiente'),
                            'message': _('El CUV %s aun no ha sido validado por el Ministerio') % self.rips_cuv,
                            'type': 'warning',
                            'sticky': True,
                        }
                    }
            else:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Error Consultando CUV'),
                        'message': _('Error al consultar el CUV: %s') % cuv_status.get('error', 'Error desconocido'),
                        'type': 'danger',
                        'sticky': True,
                    }
                }

        except Exception as e:
            _logger.error(f"Error consultando CUV existente {self.rips_cuv}: {str(e)}")
            raise UserError(_("Error al consultar CUV: %s") % str(e))

    def _handle_successful_send(self, result):
        """Procesa respuesta exitosa de envío RIPS"""
        self._process_successful_response(result)
        return self._show_success_notification(result['cuv'])

    def _handle_failed_send(self, result, config):
        """Procesa respuesta fallida de envío RIPS"""
        if self._check_cuv_already_approved(result):
            return self._handle_cuv_already_approved(result, config)
        else:
            self._process_error_response(result)
            return None

    def _handle_cuv_already_approved(self, result, config):
        """
        Maneja caso especial de CUV ya aprobado previamente.
        OPTIMIZADO: Siempre consulta automaticamente el estado del CUV.
        """
        extracted_cuv = self._extract_cuv_from_error(result)

        if not extracted_cuv:
            _logger.error("No se pudo extraer CUV del mensaje de error")
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Error'),
                    'message': _('El documento ya fue enviado pero no se pudo extraer el CUV'),
                    'type': 'danger',
                    'sticky': True,
                }
            }

        _logger.info(f"CUV ya existe: {extracted_cuv}, consultando estado automaticamente...")

        # Actualizar CUV basico primero
        self.write({
            'rips_cuv': extracted_cuv,
            'rips_proceso_id': str(result.get('proceso_id', '')) if result.get('proceso_id') else False,
            'rips_validation_status': 'sent',
            'rips_validation_date': fields.Datetime.now()
        })

        # SIEMPRE consultar estado del CUV automaticamente
        try:
            cuv_status = self._consult_cuv_status_internal(extracted_cuv, config)

            if not cuv_status.get('success'):
                _logger.error(f"Error consultando CUV {extracted_cuv}: {cuv_status.get('error')}")
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('CUV Recuperado'),
                        'message': _('CUV recuperado: %s\nPero ocurrio un error al consultar su estado.\nIntente consultar manualmente.') % extracted_cuv,
                        'type': 'warning',
                        'sticky': True,
                    }
                }

            data = cuv_status.get('data', {})
            is_valid = data.get('ResultState') or data.get('EsValido')

            # Crear archivo de resultado siempre
            self._create_result_file(data)

            if is_valid:
                # CUV validado exitosamente
                self._update_cuv_as_validated(data)
                _logger.info(f"CUV {extracted_cuv} validado exitosamente")

                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('RIPS Ya Validado'),
                        'message': _('El documento ya fue enviado previamente.\nCUV: %s\nEstado: VALIDADO por el Ministerio') % extracted_cuv,
                        'type': 'success',
                        'sticky': False,
                    }
                }
            else:
                # CUV pendiente o con errores
                validaciones = data.get('ResultadosValidacion', [])
                if validaciones:
                    self._create_errors_html_file(data, validaciones)
                    self.write({'rips_validation_status': 'rejected'})
                    _logger.warning(f"CUV {extracted_cuv} tiene {len(validaciones)} errores de validacion")

                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': _('RIPS con Errores'),
                            'message': _('El documento ya fue enviado previamente.\nCUV: %s\nEstado: RECHAZADO\nErrores: %s') % (extracted_cuv, len(validaciones)),
                            'type': 'danger',
                            'sticky': True,
                        }
                    }
                else:
                    _logger.info(f"CUV {extracted_cuv} aun pendiente de validacion")

                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': _('RIPS Pendiente'),
                            'message': _('El documento ya fue enviado previamente.\nCUV: %s\nEstado: PENDIENTE de validacion') % extracted_cuv,
                            'type': 'warning',
                            'sticky': True,
                        }
                    }

        except Exception as e:
            _logger.error(f"Excepcion consultando CUV {extracted_cuv}: {str(e)}")
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('CUV Recuperado con Error'),
                    'message': _('CUV recuperado: %s\nPero ocurrio una excepcion al consultar.\nError: %s') % (extracted_cuv, str(e)),
                    'type': 'warning',
                    'sticky': True,
                }
            }

    def _update_cuv_as_validated(self, data):
        """Actualiza factura como validada con datos del CUV"""
        self.write({
            'rips_validation_status': 'validated',
            'rips_validation_date': fields.Datetime.now(),
            'rips_errors': False,
            'rips_errors_html': False
        })
    
    def action_send_fev_rips(self):
        """Enviar factura con RIPS"""
        self._force_endpoint_and_send('CARGAR_FEV_RIPS')
    
    def action_send_nota_credito(self):
        """Enviar Nota Crédito"""
        self._force_endpoint_and_send('CARGAR_NC')
    
    def action_send_nota_credito_total(self):
        """Enviar Nota Crédito Total"""
        self._force_endpoint_and_send('CARGAR_NC_TOTAL')
    
    def action_send_nota_debito(self):
        """Enviar Nota Débito"""
        self._force_endpoint_and_send('CARGAR_ND')
    
    def action_send_nota_ajuste(self):
        """Enviar Nota de Ajuste"""
        self._force_endpoint_and_send('CARGAR_NOTA_AJUSTE')
    
    def action_send_rips_sin_factura(self):
        """Enviar RIPS sin Factura"""
        self._force_endpoint_and_send('CARGAR_RIPS_SIN_FACTURA')
    
    def action_send_nc_acuerdo_voluntades(self):
        """Enviar NC Acuerdo de Voluntades"""
        self._force_endpoint_and_send('CARGAR_NC_ACUERDO_VOLUNTADES')
    
    def action_send_capita_inicial(self):
        """Enviar Cápita Inicial"""
        self._force_endpoint_and_send('CARGAR_CAPITA_INICIAL')
    
    def action_send_capita_periodo(self):
        """Enviar Cápita Período"""
        self._force_endpoint_and_send('CARGAR_CAPITA_PERIODO')
    
    def action_send_capita_final(self):
        """Enviar Cápita Final"""
        self._force_endpoint_and_send('CARGAR_CAPITA_FINAL')
    
    def action_consult_cuv(self):
        """Consultar CUV específico - Usa endpoint /api/ConsultasFevRips/ConsultarCUV"""
        self.ensure_one()

        if not self.rips_cuv:
            raise UserError(_("No hay CUV para consultar"))

        config = self._get_rips_config()

        try:
            # Consultar usando el endpoint específico ConsultarCUV
            cuv_status = self._consult_cuv_status_internal(self.rips_cuv, config)

            if cuv_status.get('success'):
                data = cuv_status.get('data', {})

                # Verificar tanto ResultState como EsValido (API puede retornar cualquiera)
                is_valid = data.get('ResultState') == True or data.get('EsValido') == True

                # Log de la consulta
                self._log_rips_consultation(
                    'CONSULTAR_CUV',
                    {'codigoUnicoValidacion': self.rips_cuv},
                    {
                        'success': is_valid,
                        'cuv': self.rips_cuv,
                        'proceso_id': data.get('ProcesoId'),
                        'status': 'VALIDADO' if is_valid else 'RECHAZADO'
                    },
                    is_valid
                )

                # Preparar datos para escritura optimizada
                write_vals = {
                    'rips_response_json': json.dumps(data, ensure_ascii=False),
                    'rips_validation_date': fields.Datetime.now()
                }

                # Actualizar estado si está validado
                if is_valid:
                    write_vals.update({
                        'rips_validation_status': 'validated',
                        'rips_proceso_id': str(data.get('ProcesoId', '')) if data.get('ProcesoId') else False,
                        'rips_errors': False,
                        'rips_errors_html': False
                    })
                    _logger.info(f"CUV {self.rips_cuv} validado exitosamente - Factura {self.name}")
                else:
                    write_vals['rips_validation_status'] = 'rejected'
                    _logger.warning(f"CUV {self.rips_cuv} rechazado - Factura {self.name}")

                # Una sola escritura en BD
                self.with_context(no_log=True).write(write_vals)

                # Crear archivos en background (no bloquea la respuesta al usuario)
                if not self.env.context.get('skip_file_creation'):
                    try:
                        # Preparar resultado en formato compatible con _create_result_file
                        result_data = {
                            'success': is_valid,
                            'cuv': self.rips_cuv,
                            'proceso_id': data.get('ProcesoId'),
                            'num_factura': self.name.replace('/', ''),
                            'validation_date': data.get('FechaRadicacion') or data.get('FechaValidacion'),
                            'ResultState': is_valid,
                            'CodigoUnicoValidacion': self.rips_cuv,
                            'ProcesoId': data.get('ProcesoId'),
                            'FechaRadicacion': data.get('FechaRadicacion') or data.get('FechaValidacion'),
                            'ResultadosValidacion': data.get('ResultadosValidacion', [])
                        }
                        # Crear archivo de resultado (TXT y HTML si hay errores)
                        self._create_result_file(result_data)
                    except Exception as e:
                        _logger.warning(f"Error creando archivos de resultado: {e}")

                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Consulta CUV Exitosa'),
                        'message': _('Estado: %s\nProceso ID: %s\nFecha: %s') % (
                            'VALIDADO ✓' if is_valid else 'RECHAZADO ✗',
                            data.get('ProcesoId', 'N/A'),
                            data.get('FechaRadicacion') or data.get('FechaValidacion', 'N/A')
                        ),
                        'type': 'success' if is_valid else 'warning',
                        'sticky': True,
                    }
                }
            else:
                error_msg = cuv_status.get('error', 'Error desconocido')
                _logger.error(f"Error consultando CUV {self.rips_cuv}: {error_msg}")

                # Log del error
                self._log_rips_consultation(
                    'CONSULTAR_CUV',
                    {'codigoUnicoValidacion': self.rips_cuv},
                    {'error': error_msg},
                    False
                )

                raise UserError(_("Error al consultar CUV: %s") % error_msg)

        except Exception as e:
            _logger.error(f"Excepción consultando CUV {self.rips_cuv}: {str(e)}")
            raise UserError(_("Error de conexión: %s") % str(e))
    
    def action_download_rips_files(self):
        """Descargar archivos RIPS validados"""
        if not self.rips_cuv:
            raise UserError(_("No hay CUV para descargar archivos"))
        
        config = self._get_rips_config()
        attachment = self._download_rips_files(self.rips_cuv, config)
        
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }
    
    def action_download_result_file(self):
        """Descargar archivo de resultado"""
        attachment = self.env['ir.attachment'].search([
            ('res_model', '=', self._name),
            ('res_id', '=', self.id),
            ('name', 'like', 'ResultadosMSPS_%')
        ], limit=1, order='id desc')
        
        if not attachment:
            raise UserError(_("No hay archivo de resultado para descargar"))
        
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }
    
    def action_download_result_file(self):
        """Descargar archivo de resultado"""
        self.ensure_one()
        
        if not self.rips_result_binary:
            raise UserError(_("No hay archivo de resultado para descargar"))
        
        # Crear attachment temporal para descargar
        attachment = self.env['ir.attachment'].create({
            'name': self.rips_result_filename or f'ResultadosMSPS_{self.name.replace("/", "_")}.txt',
            'type': 'binary',
            'datas': self.rips_result_binary,
            'res_model': self._name,
            'res_id': self.id,
        })
        
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }
    
    def action_view_rips_errors_html(self):
        """Muestra los errores de RIPS en formato HTML"""
        self.ensure_one()
        
        # Si ya existe el HTML guardado, usarlo
        if self.rips_errors_html_binary:
            attachment = self.env['ir.attachment'].create({
                'name': self.rips_errors_html_filename,
                'type': 'binary',
                'datas': self.rips_errors_html_binary,
                'res_model': self._name,
                'res_id': self.id,
            })
            
            return {
                'type': 'ir.actions.act_url',
                'url': f'/web/content/{attachment.id}',
                'target': 'new',
            }
        
        # Si no existe, generar el HTML ahora
        if not self.rips_response_json:
            raise UserError(_("No hay respuesta para mostrar"))
        
        try:
            response_data = json.loads(self.rips_response_json)
            resultados = response_data.get('ResultadosValidacion', response_data.get('resultados_validacion', []))
            
            if not resultados:
                raise UserError(_("No hay resultados de validación para mostrar"))
            
            # Generar el HTML
            self._create_errors_html_file(response_data, resultados)
            
            # Ahora descargar el archivo generado
            if self.rips_errors_html_binary:
                attachment = self.env['ir.attachment'].create({
                    'name': self.rips_errors_html_filename,
                    'type': 'binary',
                    'datas': self.rips_errors_html_binary,
                    'res_model': self._name,
                    'res_id': self.id,
                })
                
                return {
                    'type': 'ir.actions.act_url',
                    'url': f'/web/content/{attachment.id}',
                    'target': 'new',
                }
            
        except Exception as e:
            raise UserError(_("Error al generar reporte: %s") % str(e))

    def _cron_validate_pending_cuvs(self, batch_size=50, commit_every=10):
        """
        Cron para validar CUVs pendientes automáticamente.
        OPTIMIZADO: Procesamiento en lotes con commits cada N registros.

        :param batch_size: Cantidad máxima de registros a procesar
        :param commit_every: Hacer commit cada N registros procesados
        """
        _logger.info("Iniciando validación automática de CUVs pendientes...")

        moves = self.search([
            ('rips_cuv', '!=', False),
            ('rips_validation_status', 'in', ['sent', 'generated']),
            ('move_type', 'in', ['out_invoice', 'out_refund', 'in_refund'])
        ], limit=batch_size, order='rips_validation_date desc')

        if not moves:
            _logger.info("No hay CUVs pendientes para validar")
            return

        total = len(moves)
        _logger.info(f"Encontrados {total} CUVs para validar")

        # Obtener configuración una sola vez
        config = moves[0]._get_rips_config() if moves else None
        if not config:
            _logger.error("No se pudo obtener la configuración RIPS")
            return

        validated_count = 0
        error_count = 0
        processed_count = 0

        # Procesar en lotes
        for move in moves:
            try:
                cuv_status = move._consult_cuv_status_internal(move.rips_cuv, config)

                if cuv_status.get('success'):
                    data = cuv_status.get('data', {})
                    is_valid = data.get('ResultState') == True or data.get('EsValido') == True

                    if is_valid:
                        self._update_validated_cuv(move, data)
                        validated_count += 1
                        _logger.info(f"✓ CUV validado: {move.name} - {move.rips_cuv[:20]}...")
                    else:
                        self._update_rejected_cuv(move, data)
                        _logger.warning(f"✗ CUV rechazado: {move.name}")
                else:
                    error_count += 1
                    _logger.error(f"Error consultando CUV {move.name}: {cuv_status.get('error')}")

                processed_count += 1

                # Commit cada N registros en lugar de cada iteración
                if processed_count % commit_every == 0:
                    self.env.cr.commit()
                    _logger.info(f"Progreso: {processed_count}/{total} procesados")

            except Exception as e:
                error_count += 1
                _logger.error(f"Excepción validando CUV {move.name}: {str(e)}")
                continue

        # Commit final para los registros restantes
        self.env.cr.commit()

        _logger.info(f"Validación de CUVs completada: {validated_count} validados, {error_count} errores de {total} total")

    def _update_validated_cuv(self, move, data):
        """Actualiza un CUV validado exitosamente"""
        move.with_context(skip_consultation_log=True).write({
            'rips_validation_status': 'validated',
            'rips_proceso_id': str(data.get('ProcesoId', '')) if data.get('ProcesoId') else False,
            'rips_validation_date': fields.Datetime.now(),
            'rips_errors': False,
            'rips_errors_html': False,
            'rips_response_json': json.dumps(data, ensure_ascii=False)
        })

        move.message_post(
            body=_("<p><b>RIPS Validado Automáticamente</b></p>"
                   "<p>CUV: %s</p>"
                   "<p>Proceso ID: %s</p>"
                   "<p>Fecha: %s</p>") % (
                move.rips_cuv,
                data.get('ProcesoId', 'N/A'),
                data.get('FechaRadicacion') or data.get('FechaValidacion', 'N/A')
            )
        )

    def _update_rejected_cuv(self, move, data):
        """Actualiza un CUV rechazado"""
        validaciones = data.get('ResultadosValidacion', [])
        if validaciones:
            move.with_context(skip_consultation_log=True).write({
                'rips_validation_status': 'rejected',
                'rips_response_json': json.dumps(data, ensure_ascii=False)
            })
            _logger.warning(f"CUV {move.name} tiene {len(validaciones)} errores de validación")

    # =====================================================
    # MÉTODOS DE GENERACIÓN DE RIPS
    # =====================================================
    
    def generate_rips_json_api(self):
        """Genera el JSON RIPS según el tipo de documento"""
        self.ensure_one()
        
        rips_data = self._generate_rips_base_structure()
        
        if self._should_include_users():
            usuarios = self._generate_rips_users()
            if usuarios:
                rips_data['usuarios'] = usuarios
        
        is_valid, errors = self._validate_rips_structure(rips_data)
        if not is_valid:
            raise ValidationError(_("Errores en la estructura RIPS:\n%s") % '\n'.join(errors))
        
        self._save_rips_json(rips_data)
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('RIPS Generado'),
                'message': _('RIPS JSON generado exitosamente'),
                'type': 'success',
                'sticky': False,
            }
        }
    
    def action_view_rips_json(self):
        """Muestra el JSON RIPS en una ventana emergente"""
        self.ensure_one()
        
        if not self.rips_json:
            raise UserError(_("No hay RIPS JSON generado"))
        
        try:
            json_data = json.loads(self.rips_json)
            formatted_json = json.dumps(json_data, indent=2, ensure_ascii=False)
        except:
            formatted_json = self.rips_json
        
        attachment = self.env['ir.attachment'].create({
            'name': f'RIPS_{self.name.replace("/", "_")}.json',
            'type': 'binary',
            'datas': base64.b64encode(formatted_json.encode('utf-8')),
            'res_model': self._name,
            'res_id': self.id,
        })
        
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }
    
    def action_retry_rips_validation(self):
        """Reintenta la validación de un RIPS rechazado"""
        self.ensure_one()
        
        if self.rips_validation_status not in ['rejected', 'error']:
            raise UserError(_("Solo se puede reintentar la validación para RIPS rechazados o con error"))
        
        self.write({
            'rips_validation_status': 'generated',
            'rips_cuv': False,
            'rips_validation_date': False,
            'rips_errors': False,
            'rips_proceso_id': False,
            'rips_result_binary': False,
            'rips_result_filename': False,
            'rips_errors_html_binary': False,
            'rips_errors_html_filename': False,
            'rips_errors_html': False
        })
        
        self.action_send_rips_to_minsalud()
    
    def validate_rips(self):
        """Valida la estructura y datos del RIPS generado"""
        self.ensure_one()
        
        if not self.rips_json:
            raise ValidationError(_("No hay datos RIPS para validar. Primero debe generar el RIPS."))
        
        try:
            rips_data = json.loads(self.rips_json)
        except ValueError:
            raise ValidationError(_("Error al decodificar el JSON RIPS. Verifique el formato."))
        
        success, message = self._validate_rips_data_json(rips_data)
        
        if not success:
            raise ValidationError(message)
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Validación RIPS'),
                'message': message,
                'type': 'success',
                'sticky': False,
            }
        }
    
    # =====================================================
    # MÉTODOS INTERNOS DE PROCESAMIENTO
    # =====================================================
    
    def _force_endpoint_and_send(self, endpoint_key):
        """Fuerza el uso de un endpoint específico y envía"""
        self.ensure_one()
        
        try:
            config = self._get_rips_config()
            
            # Generar RIPS automáticamente si no existe
            self.generate_rips_json_api()
            
            payload = self._prepare_payload_for_endpoint(endpoint_key)
            
            self.rips_last_load_type = LOAD_TYPE_MAPPING.get(endpoint_key)
            
            result = self._send_to_sispro_endpoint(endpoint_key, payload, config)
            
            self._log_rips_consultation(endpoint_key, payload, result, result['success'])
            
            if result['success']:
                self._process_successful_response(result)
                return self._show_success_notification(result['cuv'])
            else:
                # Verificar si es error RVG18
                if self._check_cuv_already_approved(result):
                    extracted_cuv = self._extract_cuv_from_error(result)
                    _logger.error(extracted_cuv)
                    if extracted_cuv:
                        self.rips_cuv = extracted_cuv
                        self.rips_proceso_id = str(result.get('proceso_id', ''))
                        
                        # Intentar consultar
                        try:
                            cuv_status = self._consult_cuv_status_internal(extracted_cuv, config)
                            if cuv_status.get('success'):
                                data = cuv_status.get('data', {})
                                is_valid = data.get('ResultState') == True or data.get('EsValido') == True

                                if is_valid:
                                    self.write({
                                        'rips_validation_status': 'validated',
                                        'rips_validation_date': fields.Datetime.now(),
                                        'rips_errors': False,
                                        'rips_errors_html': False
                                    })
                                else:
                                    # Generar HTML de errores si hay
                                    validaciones = data.get('ResultadosValidacion', [])
                                    if validaciones:
                                        self._create_errors_html_file(data, validaciones)

                                self._create_result_file(data)

                                if is_valid:
                                    return self._show_success_notification(extracted_cuv)
                        except:
                            pass
                    
                    return self._show_faill_notification(extracted_cuv)
                else:
                    self._process_error_response(result)
                
        except Exception as e:
            self._log_rips_consultation(endpoint_key, {}, {'error': str(e)}, False)
            raise
    
    def _send_to_sispro_endpoint(self, endpoint_key, payload, config):
        """Envía datos a cualquier endpoint de SISPRO con autenticación en cada llamada"""
        
        # Autenticar siempre en cada envío
        token = config.authenticate()
        
        endpoint = RIPS_ENDPOINTS.get(endpoint_key)
        if not endpoint:
            raise UserError(_("Endpoint no válido: %s") % endpoint_key)
        
        url = f"{config.api_url_base}{endpoint}"
        
        headers = {
            'Authorization': f'Bearer {token}',
            'Accept': 'application/json'
        }
        
        if config.verify_ssl:
            ssl_valid, ssl_message = self._validate_ssl_certificate(config.api_url_base)
            if not ssl_valid:
                _logger.error(f"Error de validación SSL: {ssl_message}")
                return {
                    'success': False,
                    'errors': [f'Error de certificado SSL: {ssl_message}'],
                    'status_code': None,
                    'response_text': ssl_message,
                    'endpoint_used': endpoint_key
                }
        
        try:
            session = self._configure_request_session(config)
            
            json_data = json.dumps(payload, ensure_ascii=False)
            json_size = len(json_data.encode('utf-8'))
            
            if json_size > 50 * 1024 * 1024:
                _logger.info(f"Comprimiendo payload de {json_size} bytes")
                compressed_data = gzip.compress(json_data.encode('utf-8'))
                
                headers['Content-Type'] = 'application/json'
                headers['Content-Encoding'] = 'gzip'
                
                response = session.post(
                    url,
                    data=compressed_data,
                    headers=headers,
                    timeout=config.timeout or 300
                )
            else:
                headers['Content-Type'] = 'application/json'
                response = session.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=config.timeout or 300
                )
            
            session.close()
            
            return self._process_sispro_response(response, endpoint_key)
            
        except requests.exceptions.RequestException as e:
            return {
                'success': False,
                'errors': [str(e)],
                'status_code': None,
                'response_text': str(e),
                'endpoint_used': endpoint_key
            }
    
    def _prepare_payload_for_endpoint(self, endpoint_key):
        """Prepara el payload según el endpoint"""
        rips_data = json.loads(self.rips_json) if self.rips_json else self._generate_empty_rips()
        xml_fev = self._get_xml_fev_file()
        
        _logger.error({
            'endpoint_key': endpoint_key,
            'rips': rips_data,
            'xmlFevFile': xml_fev
        })
        
        # Guardar el archivo XML usado
        if xml_fev:
            self._save_attached_document_used(xml_fev)
        
        if endpoint_key == 'CARGAR_FEV_RIPS':
            return {
                'rips': rips_data,
                'xmlFevFile': xml_fev
            }
        elif endpoint_key == 'CARGAR_NC':
            return {
                'rips': rips_data,
                'xmlFevFile': xml_fev
            }
        elif endpoint_key == 'CARGAR_NC_TOTAL':
            return {
                'rips': None,  # NC Total no requiere RIPS
                'xmlFevFile': xml_fev
            }
        elif endpoint_key == 'CARGAR_ND':
            return {
                'rips': rips_data,
                'xmlFevFile': xml_fev
            }
        elif endpoint_key == 'CARGAR_NOTA_AJUSTE':
            return {
                'rips': rips_data,
                'xmlFevFile': xml_fev
            }
        elif endpoint_key == 'CARGAR_NC_ACUERDO_VOLUNTADES':
            return {
                'rips': None,
                'xmlFevFile': xml_fev
            }
        elif endpoint_key == 'CARGAR_RIPS_SIN_FACTURA':
            return {
                'rips': rips_data,
                'xmlFevFile': None
            }
        elif endpoint_key in ['CARGAR_CAPITA_INICIAL', 'CARGAR_CAPITA_PERIODO', 'CARGAR_CAPITA_FINAL']:
            return {
                'rips': self._generate_capita_rips(endpoint_key),
                'xmlFevFile': None
            }
        else:
            raise UserError(_("Endpoint no reconocido: %s") % endpoint_key)
    
    def _save_attached_document_used(self, xml_fev):
        """Guarda el AttachedDocument usado en el envío"""
        try:
            # Buscar si ya existe
            existing = self.env['ir.attachment'].search([
                ('res_model', '=', self._name),
                ('res_id', '=', self.id),
                ('name', 'like', '%AttachedDocument_Used%')
            ])
            existing.unlink()
            
            # Crear nuevo
            self.env['ir.attachment'].create({
                'name': f'AttachedDocument_Used_{self.name.replace("/", "_")}.xml',
                'type': 'binary',
                'datas': xml_fev if isinstance(xml_fev, str) else base64.b64encode(xml_fev),
                'res_model': self._name,
                'res_id': self.id,
            })
        except Exception as e:
            _logger.warning(f"Error guardando AttachedDocument: {str(e)}")
    
    def _validate_ssl_certificate(self, url):
        """Valida el certificado SSL del servidor"""
        try:
            context = ssl.create_default_context(cafile=certifi.where())
            context.check_hostname = True
            context.verify_mode = ssl.CERT_REQUIRED
            
            parsed_url = urlparse(url)
            hostname = parsed_url.netloc
            port = parsed_url.port or (443 if parsed_url.scheme == 'https' else 80)
            
            with socket.create_connection((hostname, port), timeout=10) as sock:
                with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                    cert = ssock.getpeercert()
                    
                    not_after = ssl.cert_time_to_seconds(cert['notAfter'])
                    if datetime.now().timestamp() > not_after:
                        return False, "Certificado SSL expirado"
                    
                    not_before = ssl.cert_time_to_seconds(cert['notBefore'])
                    if datetime.now().timestamp() < not_before:
                        return False, "Certificado SSL aún no es válido"
                    
                    # Validar CN (Common Name) o SAN (Subject Alternative Names)
                    if 'subjectAltName' in cert:
                        valid_names = [name[1] for name in cert['subjectAltName'] if name[0] == 'DNS']
                    else:
                        # Buscar CN en subject
                        subject = dict(x[0] for x in cert['subject'])
                        valid_names = [subject.get('commonName', '')]
                    
                    # Verificar que el hostname coincida
                    hostname_valid = any(
                        hostname == name or 
                        (name.startswith('*.') and hostname.endswith(name[2:])) 
                        for name in valid_names
                    )
                    
                    if not hostname_valid:
                        return False, f"Hostname {hostname} no coincide con el certificado"
                    
                    return True, "Certificado SSL válido"
                    
        except Exception as e:
            return False, str(e)
    
    def _configure_request_session(self, config):
        """Configura sesión HTTP con reintentos y SSL"""
        session = requests.Session()
        
        if config.verify_ssl:
            session.verify = certifi.where()
            from requests.adapters import HTTPAdapter
            from urllib3.util.retry import Retry
            
            retry_strategy = Retry(
                total=3,
                backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504],
            )
            adapter = HTTPAdapter(max_retries=retry_strategy)
            session.mount("https://", adapter)
        else:
            session.verify = False
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        return session
    
    def _process_sispro_response(self, response, endpoint_key):
        """Procesa la respuesta de SISPRO"""
        result = {
            'status_code': response.status_code,
            'response_text': response.text,
            'success': False,
            'cuv': None,
            'errors': [],
            'endpoint_used': endpoint_key,
            'proceso_id': None
        }
        
        if response.status_code == 200:
            try:
                response_data = response.json()
                
                # Verificar si es respuesta exitosa (ResultState o EsValido)
                if 'CodigoUnicoValidacion' in response_data and (response_data.get('ResultState') == True or response_data.get('EsValido') == True):
                    result['success'] = True
                    result['cuv'] = response_data['CodigoUnicoValidacion']
                    result['proceso_id'] = str(response_data.get('ProcesoId', '')) if response_data.get('ProcesoId') else None
                    result['validation_date'] = response_data.get('FechaRadicacion')
                    result['status'] = 'VALIDADO'
                    result['num_factura'] = response_data.get('NumFactura')
                elif 'cuv' in response_data:
                    result['success'] = True
                    result['cuv'] = response_data['cuv']
                    result['validation_date'] = response_data.get('fechaValidacion')
                    result['status'] = response_data.get('estado', 'VALIDADO')
                elif 'codigoUnicoValidacion' in response_data:
                    result['success'] = True
                    result['cuv'] = response_data['codigoUnicoValidacion']
                elif 'resultState' in response_data and response_data['resultState']:
                    result['success'] = True
                    result['cuv'] = response_data.get('codigoUnicoValidacion')
                else:
                    # Procesar errores
                    if 'ResultadosValidacion' in response_data:
                        result['errors'] = []
                        result['proceso_id'] = str(response_data.get('ProcesoId', '')) if response_data.get('ProcesoId') else None
                        result['num_factura'] = response_data.get('NumFactura')
                        result['resultados_validacion'] = response_data.get('ResultadosValidacion', [])
                        result['ResultadosValidacion'] = response_data.get('ResultadosValidacion', [])
                        
                        for val in response_data.get('ResultadosValidacion', []):
                            error_msg = f"{val.get('Codigo', '')}: {val.get('Descripcion', '')}"
                            if val.get('Observaciones'):
                                error_msg += f" - {val['Observaciones']}"
                            result['errors'].append(error_msg)
                    elif 'errores' in response_data:
                        result['errors'] = response_data['errores']
                    elif 'mensaje' in response_data:
                        result['errors'] = [response_data['mensaje']]
                    else:
                        result['errors'] = ['Respuesta sin CUV ni errores claros']
                        
            except ValueError:
                result['errors'] = ['Error al procesar la respuesta JSON del servidor']
        else:
            error_msg = f'Error HTTP {response.status_code}'
            try:
                error_data = response.json()
                if 'message' in error_data:
                    error_msg += f": {error_data['message']}"
                elif 'error' in error_data:
                    error_msg += f": {error_data['error']}"
            except:
                error_msg += f": {response.text[:200]}"
            
            result['errors'] = [error_msg]
        
        return result
    
    def _check_cuv_already_approved(self, result):
        """Verifica si el error es RVG18 (CUV ya aprobado)"""
        if 'resultados_validacion' in result:
            for val in result['resultados_validacion']:
                if val.get('Codigo') == 'RVG18':
                    return True
        
        # También verificar en los errores
        for error in result.get('errors', []):
            if 'RVG18' in error:
                return True
        
        return False
    
    def _extract_cuv_from_error(self, result):
        """Extrae el CUV del mensaje de error RVG18"""
        if 'resultados_validacion' in result:
            for val in result['resultados_validacion']:
                if val.get('Codigo') == 'RVG18':
                    obs = val.get('Observaciones', '')
                    if obs and len(obs) == 96:  # Longitud típica de un CUV
                        return obs
        
        # También buscar en los errores
        for error in result.get('errors', []):
            if 'RVG18' in error and '-' in error:
                parts = error.split('-')
                for part in parts:
                    part = part.strip()
                    if len(part) == 96:  # Longitud típica de un CUV
                        return part
        
        return None
    
    def _consult_cuv_status_internal(self, cuv, config):
        """Consulta interna del estado de un CUV"""
        try:
            token = config.authenticate()
            
            url = f"{config.api_url_base}{RIPS_ENDPOINTS['CONSULTAR_CUV']}"
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }
            
            payload = {
                "codigoUnicoValidacion": cuv
            }
            
            session = self._configure_request_session(config)
            response = session.post(
                url,
                json=payload,
                headers=headers,
                timeout=config.timeout or 60
            )
            session.close()
            
            if response.status_code == 200:
                data = response.json()

                # No guardar aquí - se guarda en action_consult_cuv de forma optimizada

                return {
                    'success': True,
                    'data': data
                }
            else:
                return {
                    'success': False,
                    'error': f"Error HTTP {response.status_code}: {response.text}"
                }
                
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def _log_rips_consultation(self, endpoint, request_data, response_data, success=True):
        """Registra las consultas realizadas al sistema RIPS - Optimizado"""
        # Solo loguear si no está en modo skip
        if self.env.context.get('skip_consultation_log'):
            return

        timestamp = fields.Datetime.now()
        log_entry = {
            'timestamp': timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            'endpoint': endpoint,
            'success': success,
            'cuv': response_data.get('cuv') if success else None,
            'proceso_id': response_data.get('proceso_id'),
            'status': response_data.get('status')
        }

        # Optimización: Solo parsear y serializar si realmente hay historial
        try:
            if self.rips_consultation_history:
                current_history = json.loads(self.rips_consultation_history)
                # Limitar a últimas 20 entradas para mejor performance
                if len(current_history) >= 20:
                    current_history = current_history[-19:]
            else:
                current_history = []

            current_history.append(log_entry)

            # Serializar sin indentación (más rápido y menos espacio)
            self.with_context(no_log=True).rips_consultation_history = json.dumps(current_history, ensure_ascii=False)
        except Exception as e:
            _logger.warning(f"Error logging consultation: {e}")
    
    def _process_successful_response(self, result):
        """Procesa una respuesta exitosa de SISPRO"""
        self.write({
            'rips_cuv': result['cuv'],
            'rips_validation_date': fields.Datetime.now(),
            'rips_validation_status': 'validated',
            'rips_response_json': json.dumps(result, indent=2),
            'rips_errors': False,
            'rips_errors_html': False,
            'rips_proceso_id': str(result.get('proceso_id', '')) if result.get('proceso_id') else False
        })
        
        self._save_response_attachment(result)
        
        # Crear archivo de resultado
        self._create_result_file(result)
    
    def _process_error_response(self, result):
        """Procesa una respuesta con errores de SISPRO"""
        errors_text = '\n'.join(result.get('errors', ['Error desconocido']))
        self.write({
            'rips_validation_status': 'rejected',
            'rips_response_json': json.dumps(result, indent=2),
            'rips_errors': errors_text,
            'rips_proceso_id': str(result.get('proceso_id', '')) if result.get('proceso_id') else False
        })
        
        # Crear archivo de resultado
        self._create_result_file(result)

        # Generar HTML de errores si hay validaciones
        validaciones = result.get('resultados_validacion') or result.get('ResultadosValidacion', [])
        if validaciones:
            self._create_errors_html_file(result, validaciones)
            
        _logger.warning("Se encontraron validaciones en RIPS para la factura %s. Revise la pestaña RIPS para ver los detalles.", self.name)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Advertencia RIPS'),
                'message': _('Se encontraron validaciones en RIPS. Por favor revise la pestaña RIPS para ver los detalles.'),
                'type': 'warning',
                'sticky': False,
            }
        }
    
    def _create_result_file(self, result):
        """Crea archivo TXT con el resultado del proceso"""
        try:
            # Determinar el estado
            if result.get('success') or result.get('ResultState') == True:
                estado = 'A'  # Aprobado
            else:
                estado = 'R'  # Rechazado
            
            # Construir nombre del archivo
            num_factura = result.get('num_factura') or result.get('NumFactura') or self.name.replace('/', '')
            proceso_id = result.get('proceso_id') or result.get('ProcesoId') or 'SIN_ID'
            
            filename = f"ResultadosMSPS_{num_factura}_ID{proceso_id}_{estado}_CUV.txt"
            
            # Construir contenido del archivo
            content = f"RESULTADOS VALIDACIÓN RIPS - MINISTERIO DE SALUD\n"
            content += f"{'='*60}\n\n"
            content += f"Fecha Generación: {fields.Datetime.now()}\n"
            content += f"Estado: {'APROBADO' if estado == 'A' else 'RECHAZADO'}\n"
            content += f"Número Factura: {num_factura}\n"
            content += f"Proceso ID: {proceso_id}\n"
            content += f"CUV: {result.get('cuv') or result.get('CodigoUnicoValidacion', 'N/A')}\n"
            content += f"Fecha Radicación: {result.get('validation_date') or result.get('FechaRadicacion', 'N/A')}\n\n"
            
            # Agregar resultados de validación si existen
            validaciones = result.get('resultados_validacion') or result.get('ResultadosValidacion', [])
            if validaciones:
                content += f"RESULTADOS DE VALIDACIÓN:\n"
                content += f"{'-'*60}\n"
                for idx, val in enumerate(validaciones, 1):
                    content += f"\n{idx}. {val.get('Clase', '')}: {val.get('Codigo', '')}\n"
                    content += f"   Descripción: {val.get('Descripcion', '')}\n"
                    if val.get('Observaciones'):
                        content += f"   Observaciones: {val.get('Observaciones')}\n"
                    if val.get('PathFuente'):
                        content += f"   Path: {val.get('PathFuente')}\n"
            
            # Agregar respuesta completa en formato JSON
            content += f"\n\nRESPUESTA COMPLETA JSON:\n"
            content += f"{'-'*60}\n"
            content += json.dumps(result, indent=2, ensure_ascii=False)
            
            # Guardar en campo binario de la factura
            self.write({
                'rips_result_binary': base64.b64encode(content.encode('utf-8')),
                'rips_result_filename': filename
            })
            
            # También crear archivo adjunto para compatibilidad
            self.env['ir.attachment'].create({
                'name': filename,
                'type': 'binary',
                'datas': base64.b64encode(content.encode('utf-8')),
                'res_model': self._name,
                'res_id': self.id,
                'description': f'Resultado validación RIPS - {estado}'
            })
            
            # Si hay errores, generar también el HTML
            if validaciones and estado == 'R':
                self._create_errors_html_file(result, validaciones)
            
            _logger.info(f"Archivo de resultado creado: {filename}")
            
        except Exception as e:
            _logger.error(f"Error creando archivo de resultado: {str(e)}")
    
    def _create_errors_html_file(self, result, validaciones):
        """Crea archivo HTML con los errores formateados"""
        try:
            # Crear HTML con los errores
            html_content = f"""
            <style>
                .o_rips_validation_container {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; }}
                .o_rips_validation_container .rips-error {{ background-color: #ffebee; border-left: 4px solid #f44336; padding: 12px; margin: 8px 0; border-radius: 4px; }}
                .o_rips_validation_container .rips-warning {{ background-color: #fff3e0; border-left: 4px solid #ff9800; padding: 12px; margin: 8px 0; border-radius: 4px; }}
                .o_rips_validation_container .rips-info {{ background-color: #e3f2fd; border-left: 4px solid #2196f3; padding: 12px; margin: 8px 0; border-radius: 4px; }}
                .o_rips_validation_container .rips-code {{ font-weight: 600; color: #333; font-size: 14px; }}
                .o_rips_validation_container .rips-desc {{ margin: 8px 0 4px 0; color: #555; }}
                .o_rips_validation_container .rips-obs {{ font-style: italic; color: #666; font-size: 13px; margin-top: 4px; }}
                .o_rips_validation_container .rips-path {{ font-family: SFMono-Regular, Consolas, "Liberation Mono", Menlo, monospace; background: #f5f5f5; padding: 3px 6px; font-size: 12px; border-radius: 3px; }}
                .o_rips_validation_container .rips-summary {{ background: #f8f9fa; padding: 16px; margin-bottom: 24px; border-radius: 8px; border: 1px solid #e9ecef; }}
                .o_rips_validation_container .rips-section-title {{ font-size: 18px; font-weight: 600; margin: 24px 0 12px 0; }}
            </style>
            <div class="o_rips_validation_container">
                <div class="rips-summary">
                    <strong>Factura:</strong> {self.name}<br/>
                    <strong>Proceso ID:</strong> {result.get('proceso_id') or result.get('ProcesoId', 'N/A')}<br/>
                    <strong>Fecha:</strong> {fields.Datetime.now().strftime('%Y-%m-%d %H:%M')}<br/>
                    <strong>Estado:</strong> <span style="color: #d32f2f; font-weight: bold;">RECHAZADO</span>
                </div>
            """
            
            # Agrupar validaciones por tipo
            rechazados = []
            notificaciones = []
            otros = []
            cuv_ya_aprobado = False
            cuv_existente = None
            
            for val in validaciones:
                clase = val.get('Clase', '')
                codigo = val.get('Codigo', '')
                
                # Detectar si es RVG18 (CUV ya aprobado)
                if codigo == 'RVG18':
                    cuv_ya_aprobado = True
                    # Intentar extraer el CUV de las observaciones
                    obs = val.get('Observaciones', '')
                    if obs and len(obs) == 96:
                        cuv_existente = obs
                
                if clase == 'RECHAZADO':
                    rechazados.append(val)
                elif clase == 'NOTIFICACION':
                    notificaciones.append(val)
                else:
                    otros.append(val)
            
            # Si el CUV ya fue aprobado, mostrar mensaje especial
            if cuv_ya_aprobado:
                html_content += f"""
                <div style="background-color: #fff3cd; border: 1px solid #ffeaa7; border-radius: 6px; padding: 16px; margin: 16px 0;">
                    <h4 style="color: #856404; margin: 0 0 8px 0;">
                        <i class="fa fa-exclamation-triangle" style="margin-right: 8px;"/> CUV Ya Aprobado Previamente
                    </h4>
                    <p style="color: #856404; margin: 0;">
                        Este RIPS ya fue validado anteriormente. {'CUV: <strong style="font-family: monospace;">' + cuv_existente + '</strong>' if cuv_existente else ''}
                    </p>
                    <p style="color: #856404; margin: 8px 0 0 0;">
                        Use el botón <strong>"Consultar CUV"</strong> para verificar el estado actual.
                    </p>
                </div>
                """
            
            # Mostrar rechazos primero
            if rechazados:
                html_content += '<h4 class="rips-section-title" style="color: #d32f2f;">Rechazos</h4>'
                for val in rechazados:
                    html_content += f"""
                    <div class="rips-error">
                        <div class="rips-code">{val.get('Codigo', '')}</div>
                        <div class="rips-desc">{val.get('Descripcion', '')}</div>
                    """
                    if val.get('Observaciones'):
                        html_content += f'<div class="rips-obs">Observación: {val["Observaciones"]}</div>'
                    if val.get('PathFuente'):
                        html_content += f'<div>Ubicación: <span class="rips-path">{val["PathFuente"]}</span></div>'
                    html_content += '</div>'
            
            # Luego notificaciones
            if notificaciones:
                html_content += '<h4 class="rips-section-title" style="color: #ff6f00;">Notificaciones</h4>'
                for val in notificaciones:
                    html_content += f"""
                    <div class="rips-warning">
                        <div class="rips-code">{val.get('Codigo', '')}</div>
                        <div class="rips-desc">{val.get('Descripcion', '')}</div>
                    """
                    if val.get('Observaciones'):
                        html_content += f'<div class="rips-obs">Observación: {val["Observaciones"]}</div>'
                    if val.get('PathFuente'):
                        html_content += f'<div>Ubicación: <span class="rips-path">{val["PathFuente"]}</span></div>'
                    html_content += '</div>'
            
            # Otros
            if otros:
                html_content += '<h4 class="rips-section-title" style="color: #1976d2;">Información</h4>'
                for val in otros:
                    html_content += f"""
                    <div class="rips-info">
                        <div class="rips-code">{val.get('Codigo', '')}</div>
                        <div class="rips-desc">{val.get('Descripcion', '')}</div>
                    """
                    if val.get('Observaciones'):
                        html_content += f'<div class="rips-obs">Observación: {val["Observaciones"]}</div>'
                    if val.get('PathFuente'):
                        html_content += f'<div>Ubicación: <span class="rips-path">{val["PathFuente"]}</span></div>'
                    html_content += '</div>'
            
            html_content += '</div>'
            
            # HTML completo para el archivo descargable
            html_file_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Resultados de Validación RIPS - {self.name}</title>
    <style>
        body {{ margin: 20px; }}
    </style>
</head>
<body>
    {html_content}
</body>
</html>"""
            
            filename = f'RIPS_Errores_{self.name.replace("/", "_")}.html'
            
            # Guardar en campos
            self.write({
                'rips_errors_html': html_content,  # Solo el contenido para mostrar en la vista
                'rips_errors_html_binary': base64.b64encode(html_file_content.encode('utf-8')),
                'rips_errors_html_filename': filename
            })
            
        except Exception as e:
            _logger.error(f"Error creando archivo HTML de errores: {str(e)}")
    
    def _save_response_attachment(self, result):
        """Guarda la respuesta como archivo adjunto"""
        response_filename = f"{self.name.replace('/', '_')}_RIPS_Response.json"
        
        self.env['ir.attachment'].create({
            'name': response_filename,
            'res_model': self._name,
            'res_id': self.id,
            'type': 'binary',
            'datas': base64.b64encode(json.dumps(result, indent=2).encode('utf-8')),
        })
    
    def _save_rips_json(self, rips_data):
        """Guarda el JSON RIPS generado"""
        json_str = json.dumps(rips_data, default=self._json_serial, indent=2)
        
        # Limpiar archivos antiguos al generar nuevo RIPS
        self.write({
            'rips_json': json_str,
            'rips_json_binary': base64.b64encode(json_str.encode('utf-8')),
            'rips_json_filename': f"{self.name.replace('/', '_')}_RIPS.json",
            'rips_generated': True,
            'rips_validation_status': 'generated',
            # Limpiar archivos de resultado anteriores
            'rips_result_binary': False,
            'rips_result_filename': False,
            'rips_errors_html_binary': False,
            'rips_errors_html_filename': False,
            'rips_errors_html': False,
            'rips_errors': False,
            'rips_response_json': False,
            'rips_cuv': False,
            'rips_proceso_id': False,
            'rips_validation_date': False
        })
    
    def _show_success_notification(self, cuv):
        """Muestra notificación de éxito"""
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('RIPS Validado'),
                'message': _('RIPS validado exitosamente. CUV: %s') % cuv,
                'type': 'success',
                'sticky': False,
            }
        }
        
    def _show_faill_notification(self, cuv):
        """Muestra notificación de éxito"""
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('RIPS Previamente Validado'),
                'message': _('RIPS validado Previamente. CUV: %s') % cuv,
                'type': 'success',
                'sticky': False,
            }
        }
    
    # =====================================================
    # MÉTODOS DE CONSULTA (PARA ERP)
    # =====================================================
    
    def _consult_cuv_status(self, cuv, config):
        """Consulta el estado de un CUV"""
        url = f"{config.api_url_base}{RIPS_ENDPOINTS['CONSULTAR_CUV']}"
        
        payload = {
            "codigoUnicoValidacion": cuv
        }
        
        try:
            response = requests.post(
                url,
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=config.timeout or 300
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                raise UserError(_("Error al consultar CUV: %s") % response.text)
                
        except Exception as e:
            raise UserError(_("Error de conexión: %s") % str(e))
    
    def _download_rips_files(self, cuv, config):
        """Descarga archivos RIPS por CUV"""
        url = f"{config.api_url_base}{RIPS_ENDPOINTS['DESCARGAR_ARCHIVOS']}"
        
        payload = {
            "codigoUnicoValidacion": cuv
        }
        
        try:
            response = requests.post(
                url,
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=config.timeout or 300
            )
            
            if response.status_code == 200:
                attachment = self.env['ir.attachment'].create({
                    'name': f'RIPS_Files_{cuv}.zip',
                    'type': 'binary',
                    'datas': base64.b64encode(response.content),
                    'res_model': self._name,
                    'res_id': self.id,
                })
                return attachment
            else:
                raise UserError(_("Error al descargar archivos: %s") % response.text)
                
        except Exception as e:
            raise UserError(_("Error de conexión: %s") % str(e))
    
    # =====================================================
    # MÉTODOS DE VALIDACIÓN DE DATOS
    # =====================================================
    
    def _validate_rips_structure(self, rips_data):
        """Valida la estructura del RIPS"""
        errors = []
        
        required_root = ['numDocumentoIdObligado', 'numFactura']
        for field in required_root:
            if field not in rips_data or not rips_data[field]:
                errors.append(_("Campo obligatorio faltante: %s") % field)
        
        if 'usuarios' in rips_data and rips_data['usuarios']:
            for idx, usuario in enumerate(rips_data['usuarios']):
                user_errors = self._validate_usuario_structure(usuario, idx + 1)
                errors.extend(user_errors)
        
        return len(errors) == 0, errors
    
    def _validate_usuario_structure(self, usuario, index):
        """Valida la estructura de un usuario"""
        errors = []
        
        required_fields = [
            'tipoDocumentoIdentificacion',
            'numDocumentoIdentificacion',
            'tipoUsuario',
            'fechaNacimiento',
            'codSexo',
            'codPaisResidencia',
            'codMunicipioResidencia',
            'codZonaTerritorialResidencia',
            'consecutivo'
        ]
        
        for field in required_fields:
            if field not in usuario or usuario[field] is None:
                errors.append(_("Usuario #%s: Campo obligatorio faltante: %s") % (index, field))
        
        if 'servicios' not in usuario or not usuario['servicios']:
            errors.append(_("Usuario #%s: No contiene servicios") % index)
        
        return errors
    
    def _validate_rips_data_json(self, rips_data):
        """Valida la estructura y campos del RIPS JSON"""
        if not rips_data:
            return False, _("No hay datos RIPS para validar")
        
        errors = []
        
        required_fields = ['numDocumentoIdObligado', 'numFactura']
        for field in required_fields:
            if field not in rips_data or not rips_data[field]:
                errors.append(_("Campo requerido faltante: %s") % field)
        
        if 'usuarios' not in rips_data or not rips_data['usuarios']:
            errors.append(_("El RIPS no contiene usuarios"))
        else:
            for i, usuario in enumerate(rips_data['usuarios']):
                self._validate_usuario_json(usuario, i+1, errors)
        
        if errors:
            return False, "\n".join(errors)
        return True, _("Validación RIPS exitosa")
    
    def _validate_usuario_json(self, usuario, index, errors):
        """Valida los datos de un usuario"""
        required_fields = [
            'tipoDocumentoIdentificacion', 
            'numDocumentoIdentificacion',
            'tipoUsuario',
            'fechaNacimiento',
            'codSexo'
        ]
        
        for field in required_fields:
            if field not in usuario or not usuario[field]:
                errors.append(_("Usuario #%s: Campo requerido faltante: %s") % (index, field))
        
        if 'servicios' not in usuario or not usuario['servicios']:
            errors.append(_("Usuario #%s: No contiene servicios") % index)
    
    def _validate_string(self, value, min_length=None, max_length=None, 
                        no_leading_zero=False, no_spaces=False, 
                        default=None, allow_null=False):
        """Valida y formatea strings según reglas RIPS"""
        if allow_null and (value is None or value == '' or 
                          (isinstance(value, str) and value.strip() == '')):
            return None
        
        if not value and default is not None:
            return default
        
        if not value:
            return ""
        
        value_str = str(value).strip()
        
        if no_spaces:
            value_str = value_str.replace(' ', '')
        
        if no_leading_zero and value_str.startswith('0') and len(value_str) > 1:
            value_str = value_str.lstrip('0') or '0'
        
        if max_length and len(value_str) > max_length:
            value_str = value_str[:max_length]
        
        if min_length and len(value_str) < min_length:
            if value_str.isdigit():
                value_str = value_str.zfill(min_length)
            else:
                value_str = value_str.ljust(min_length)
        
        return value_str
    
    def _validate_numeric(self, value, decimals=0, min_value=0, max_value=None):
        """Valida valores numéricos con soporte para decimales"""
        if value is None or value == '':
            return 0
        
        try:
            if isinstance(value, (int, float)):
                value_decimal = Decimal(str(value))
            else:
                value_decimal = Decimal(value)
            
            # Validar rango
            if value_decimal < min_value:
                value_decimal = Decimal(str(min_value))
            
            if max_value is not None and value_decimal > max_value:
                value_decimal = Decimal(str(max_value))
            
            # Aplicar redondeo
            if decimals == 0:
                value_decimal = value_decimal.quantize(Decimal('1'), rounding=ROUND_HALF_UP)
                return int(value_decimal)
            else:
                quantize_str = '0.' + '0' * decimals
                value_decimal = value_decimal.quantize(Decimal(quantize_str), rounding=ROUND_HALF_UP)
                return float(value_decimal)
                
        except (ValueError, TypeError, ArithmeticError):
            return 0
    
    def _validate_date(self, value, format_str='%Y-%m-%d', default=None):
        """Valida y formatea fechas según formato RIPS"""
        if not value:
            return default
        
        try:
            date_value = None
            
            if isinstance(value, str):
                # Lista de formatos a intentar
                formats = [
                    '%Y-%m-%d %H:%M:%S',
                    '%Y-%m-%d %H:%M',
                    '%Y-%m-%d',
                    '%d/%m/%Y',
                    '%m/%d/%Y',
                    format_str
                ]
                
                for fmt in formats:
                    try:
                        date_value = datetime.strptime(value.strip(), fmt)
                        break
                    except ValueError:
                        continue
            
            elif isinstance(value, datetime):
                date_value = value
            
            elif isinstance(value, date):
                date_value = datetime.combine(value, datetime.min.time())
            
            if date_value:
                return date_value.strftime(format_str)
            
            return default
            
        except Exception:
            return default
    
    def _json_serial(self, obj):
        """Serializa objetos para JSON con soporte para Decimal"""
        if isinstance(obj, (datetime, fields.Date, fields.Datetime)):
            return obj.isoformat()
        elif isinstance(obj, Decimal):
            return float(obj)
        elif isinstance(obj, date):
            return obj.isoformat()
        raise TypeError(f"Type {type(obj)} not serializable for RIPS")
    
    # =====================================================
    # MÉTODOS ABSTRACTOS A IMPLEMENTAR
    # =====================================================
    
    @api.model
    def _get_rips_config(self):
        """Obtiene la configuración RIPS activa"""
        raise NotImplementedError("Debe implementar _get_rips_config")
    
    def _determine_rips_endpoint_and_payload(self):
        """Determina el endpoint correcto y prepara el payload según el tipo de documento"""
        raise NotImplementedError("Debe implementar _determine_rips_endpoint_and_payload")
    
    def _generate_rips_base_structure(self):
        """Genera la estructura base del RIPS"""
        raise NotImplementedError("Debe implementar _generate_rips_base_structure")
    
    def _should_include_users(self):
        """Determina si debe incluir usuarios en el RIPS"""
        raise NotImplementedError("Debe implementar _should_include_users")
    
    def _generate_rips_users(self):
        """Genera la lista de usuarios para el RIPS"""
        raise NotImplementedError("Debe implementar _generate_rips_users")
    
    def _get_xml_fev_file(self):
        """Obtiene el XML de la factura electrónica"""
        raise NotImplementedError("Debe implementar _get_xml_fev_file")
    
    def _generate_empty_rips(self):
        """Genera un RIPS vacío"""
        raise NotImplementedError("Debe implementar _generate_empty_rips")
    
    def _generate_capita_rips(self, endpoint_key):
        """Genera RIPS específico para cápita"""
        raise NotImplementedError("Debe implementar _generate_capita_rips")


class RipsConfiguration(models.Model):
    """Configuración de RIPS SISPRO"""
    _name = 'rips.configuration'
    _description = 'Configuración RIPS SISPRO'
    _rec_name = 'name'
    
    # URLs oficiales de SISPRO
    SISPRO_PRODUCTION_URL = 'https://validador.sispro.gov.co'
    SISPRO_TEST_URL = 'https://pruebasvalidador.sispro.gov.co'
    
    name = fields.Char(string='Nombre', required=True, default='Configuración RIPS')
    company_id = fields.Many2one('res.company', string='Compañía', required=True, default=lambda self: self.env.company)
    active = fields.Boolean(string='Activo', default=True)
    
    # Credenciales SISPRO
    sispro_tipo_documento = fields.Selection([
        ('CC', 'Cédula de Ciudadanía'),
        ('CE', 'Cédula de Extranjería'),
        ('PA', 'Pasaporte'),
        ('NI', 'NIT')
    ], string='Tipo Documento SISPRO', required=True, default='NI')
    sispro_numero_documento = fields.Char(string='Número Documento SISPRO', required=True)
    sispro_nit = fields.Char(string='NIT Entidad', required=True, help='NIT de la entidad prestadora')
    sispro_password = fields.Char(string='Contraseña SISPRO', required=True)
    
    # URLs de servicio
    api_url_base = fields.Char(
        string='URL Base API', 
        required=True,
        help='URL base para el servicio RIPS'
    )
    environment_type = fields.Selection([
        ('production', 'Producción'),
        ('test', 'Pruebas')
    ], string='Tipo de Ambiente', default='production', required=True)
    
    # Token de autenticación
    auth_token = fields.Text(string='Token de Autenticación', readonly=True)
    token_expiry = fields.Datetime(string='Expiración del Token', readonly=True)
    
    # Configuración adicional
    timeout = fields.Integer(string='Timeout (segundos)', default=300)
    verify_ssl = fields.Boolean(string='Verificar SSL', default=True)
    
    @api.onchange('environment_type')
    def _onchange_environment_type(self):
        """Actualiza la URL según el ambiente"""
        if self.environment_type == 'production':
            self.api_url_base = self.SISPRO_PRODUCTION_URL
        else:
            self.api_url_base = self.SISPRO_TEST_URL
    
    @api.constrains('active', 'company_id')
    def _check_unique_active(self):
        for record in self:
            if record.active:
                domain = [
                    ('company_id', '=', record.company_id.id),
                    ('active', '=', True),
                    ('id', '!=', record.id)
                ]
                if self.search_count(domain) > 0:
                    raise ValidationError(_("Solo puede haber una configuración RIPS activa por empresa."))
    
    @api.model
    def get_config(self):
        """Obtiene la configuración activa para la compañía actual"""
        config = self.search([
            ('company_id', '=', self.env.company.id),
            ('active', '=', True)
        ], limit=1)
        if not config:
            raise UserError(_("No se ha configurado RIPS SISPRO para esta compañía. Por favor configure las credenciales."))
        return config
    
    def test_connection(self):
        """Prueba la conexión con el servicio SISPRO"""
        self.ensure_one()
        try:
            self.authenticate()
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Conexión Exitosa'),
                    'message': _('La conexión con SISPRO fue exitosa.'),
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            raise UserError(_("Error en la conexión: %s") % str(e))
    
    def authenticate(self):
        """Autentica con SISPRO y obtiene el token - Se llama en cada envío"""
        self.ensure_one()
        
        # NO verificar si el token actual sigue válido - siempre generar nuevo
        
        url = f"{self.api_url_base}{RIPS_ENDPOINTS['AUTH']}"
        
        payload = {
            "persona": {
                "identificacion": {
                    "tipo": self.sispro_tipo_documento,
                    "numero": self.sispro_numero_documento
                }
            },
            "clave": self.sispro_password,
            "nit": self.sispro_nit
        }
        
        headers = {
            'Content-Type': 'application/json'
        }
        
        try:
            response = requests.post(
                url, 
                json=payload, 
                headers=headers,
                timeout=60,
                verify=self.verify_ssl
            )
            
            if response.status_code == 200:
                data = response.json()
                self.auth_token = data.get('token')
                # Token expira en 1 hora
                self.token_expiry = fields.Datetime.now() + timedelta(hours=1)
                return self.auth_token
            else:
                raise UserError(_("Error de autenticación: %s") % response.text)
                
        except requests.exceptions.RequestException as e:
            raise UserError(_("Error de conexión: %s") % str(e))


class AccountMove(models.Model):
    """Implementación de RIPS para facturas"""
    _name = 'account.move'
    _inherit = ['account.move', 'abstract.rips.fev.mixin']
    
    # Campos adicionales para tipos especiales
    is_adjustment_note = fields.Boolean(string='Es Nota de Ajuste', default=False)
    is_voluntary_agreement = fields.Boolean(string='Es Acuerdo de Voluntades', default=False)
    is_total_credit_note = fields.Boolean(string='Es Nota Crédito Total', default=False)
    rips_without_invoice = fields.Boolean(string='RIPS sin Factura', default=False)
    capita_type = fields.Selection([
        ('initial', 'Inicial'),
        ('period', 'Período'),
        ('final', 'Final')
    ], string='Tipo de Cápita')
    attached_document_xml = fields.Binary(
        string='Archivo XML AttachedDocument',
        readonly=True,
        attachment=True,
        help="XML de la factura electrónica almacenado para reutilización"
    )

    attached_document_xml_filename = fields.Char(
        string='Nombre Archivo XML',
        readonly=True
    )

    rips_validated_cups = fields.Boolean(
        string='CUPS Validados',
        readonly=True,
        help="Indica si los códigos CUPS de la factura han sido validados"
    )

    rips_validation_cups_date = fields.Datetime(
        string='Fecha Validación CUPS',
        readonly=True
    )

    rips_validation_cups_result = fields.Text(
        string='Resultado Validación CUPS',
        readonly=True
    )

    # Campo computado para saber si está en otro lote RIPS
    is_in_rips_export = fields.Boolean(
        string='En Lote RIPS',
        compute='_compute_is_in_rips_export',
        search='_search_is_in_rips_export',
        help="Indica si la factura está incluida en algún lote de exportación RIPS"
    )

    ripsjson_id = fields.Many2one(
        'rips.export',
        string='Lote RIPS',
        readonly=True,
        help="Lote de exportación RIPS al que pertenece esta factura"
    )

    @api.depends('ripsjson_id')
    def _compute_is_in_rips_export(self):
        for record in self:
            record.is_in_rips_export = bool(record.ripsjson_id)

    def _search_is_in_rips_export(self, operator, value):
        if operator == '=' and value is False:
            return [('ripsjson_id', '=', False)]
        elif operator == '=' and value is True:
            return [('ripsjson_id', '!=', False)]
        else:
            return [('ripsjson_id', operator, value)]

    # MÉTODOS MEJORADOS

    def action_generate_rips_json_improved(self):
        """Genera el JSON RIPS según el tipo de documento - VERSIÓN MEJORADA"""
        self.ensure_one()
        
        # Si ya existe JSON y está validado, usarlo directamente
        if self.rips_json and self.rips_validation_status == 'validated':
            _logger.info(f"RIPS JSON ya existe y está validado para {self.name}")
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('RIPS Existente'),
                    'message': _('El RIPS ya está generado y validado'),
                    'type': 'info',
                    'sticky': False,
                }
            }
        
        try:
            rips_data = self._generate_rips_base_structure()
            
            if self._should_include_users():
                usuarios = self._generate_rips_users()
                if usuarios:
                    rips_data['usuarios'] = usuarios
            
            is_valid, errors = self._validate_rips_structure(rips_data)
            if not is_valid:
                raise ValidationError(_("Errores en la estructura RIPS:\n%s") % '\n'.join(errors))

            self._save_rips_json(rips_data)

            # OPTIMIZADO: Odoo hace commit automatico al finalizar transaccion exitosa

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('RIPS Generado'),
                    'message': _('RIPS JSON generado exitosamente'),
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            # OPTIMIZADO: Odoo hace rollback automatico en excepciones
            raise

    def action_send_rips_to_minsalud_improved(self):
        """Envía RIPS al Ministerio de Salud - VERSIÓN MEJORADA"""
        self.ensure_one()
        
        try:
            config = self._get_rips_config()
            
            # Generar RIPS si no existe
            if not self.rips_generated:
                self.action_generate_rips_json_improved()
            
            endpoint_key, payload = self._determine_rips_endpoint_and_payload()
            
            self.rips_last_load_type = LOAD_TYPE_MAPPING.get(endpoint_key)
            
            result = self._send_to_sispro_endpoint(endpoint_key, payload, config)
            
            self._log_rips_consultation(endpoint_key, payload, result, result['success'])
            
            if result['success']:
                self._process_successful_response(result)
                # OPTIMIZADO: Odoo hace commit automatico
                return self._show_success_notification(result['cuv'])
            else:
                if self._check_cuv_already_approved(result):
                    extracted_cuv = self._extract_cuv_from_error(result)
                    if extracted_cuv:
                        self.rips_cuv = extracted_cuv
                        self.rips_proceso_id = str(result.get('proceso_id', '')) if result.get('proceso_id') else False
                        try:
                            cuv_status = self._consult_cuv_status_internal(extracted_cuv, config)
                            if cuv_status.get('success'):
                                data = cuv_status.get('data', {})
                                is_valid = data.get('ResultState') == True or data.get('EsValido') == True
                                if is_valid:
                                    self.write({
                                        'rips_validation_status': 'validated',
                                        'rips_validation_date': fields.Datetime.now(),
                                        'rips_errors': False,
                                        'rips_errors_html': False
                                    })
                                    # OPTIMIZADO: Odoo hace commit automatico
                                else:
                                    validaciones = data.get('ResultadosValidacion', [])
                                    if validaciones:
                                        self._create_errors_html_file(data, validaciones)
                                
                                self._create_result_file(data)

                                if data.get('ResultState') == True or data.get('EsValido') == True:
                                    return self._show_success_notification(extracted_cuv)
                        except Exception as e:
                            _logger.warning(f"Error al consultar CUV: {str(e)}")
                    
                    return self._show_faill_notification(extracted_cuv)
                else:
                    self._process_error_response(result)
                
        except Exception as e:
            self.env.cr.rollback()
            self._log_rips_consultation(
                endpoint_key if 'endpoint_key' in locals() else 'UNKNOWN',
                {},
                {'error': str(e), 'status_code': None},
                False
            )
            raise

    def _get_xml_fev_file_improved(self):
        """Obtiene el XML de la factura (AttachedDocument) - VERSIÓN MEJORADA"""
        # Primero verificar si ya está guardado en el campo
        if self.attached_document_xml:
            _logger.info(f"Usando XML guardado para {self.name}")
            return self.attached_document_xml.decode() if isinstance(self.attached_document_xml, bytes) else self.attached_document_xml
        
        # Si no está guardado, intentar obtenerlo
        try:
            attached_document, error = self._get_attached_document()
            if not error and attached_document:
                # Guardar el XML para futura reutilización
                xml_base64 = base64.b64encode(attached_document).decode('utf-8')
                self.write({
                    'attached_document_xml': xml_base64,
                    'attached_document_xml_filename': f'{self.name}_AttachedDocument.xml'
                })
                # OPTIMIZADO: Odoo hace commit automatico
                return xml_base64
        except Exception as e:
            _logger.warning(f"Error al obtener AttachedDocument: {str(e)}")
        
        # Buscar en archivos adjuntos
        xml_attachment = self.env['ir.attachment'].search([
            ('res_model', '=', 'account.move'),
            ('res_id', '=', self.id),
            '|', '|',
            ('name', 'ilike', '%AttachedDocument%'),
            ('name', 'ilike', '%attached_document%'),
            ('name', 'ilike', '%.xml'),
        ], limit=1, order='id desc')
        
        if xml_attachment:
            # Guardar en el campo para futura reutilización
            self.write({
                'attached_document_xml': xml_attachment.datas,
                'attached_document_xml_filename': xml_attachment.name
            })
            # OPTIMIZADO: Odoo hace commit automatico
            return xml_attachment.datas.decode() if isinstance(xml_attachment.datas, bytes) else xml_attachment.datas
        
        if self.move_type in ['out_invoice', 'out_refund']:
            _logger.warning(f"No se encontró XML de factura para {self.name}")
        
        return None

    def action_validate_cups_codes(self):
        """Valida todos los códigos CUPS de la factura"""
        self.ensure_one()
        
        errors = []
        warnings = []
        validated_count = 0
        
        for line in self.invoice_line_ids:
            if not line.product_id:
                continue
                
            # Solo validar productos de tipo consulta o procedimiento
            if hasattr(line.product_id, 'rips_service_type') and line.product_id.rips_service_type in ['consulta', 'procedimiento']:
                # Obtener el código CUPS
                cups_code = None
                
                if hasattr(line.product_id, 'code_type') and line.product_id.code_type == 'cups':
                    if hasattr(line.product_id, 'cups_id') and line.product_id.cups_id:
                        cups_code = line.product_id.cups_id.code
                elif hasattr(line.product_id, 'custom_code') and line.product_id.custom_code:
                    cups_code = line.product_id.custom_code
                elif line.product_id.default_code:
                    cups_code = line.product_id.default_code
                
                if not cups_code:
                    warnings.append(f"Producto '{line.product_id.name}' sin código CUPS")
                    continue
                
                # Validar formato del código CUPS (6 dígitos)
                if not cups_code.isdigit() or len(cups_code) != 6:
                    errors.append(f"Producto '{line.product_id.name}': Código CUPS '{cups_code}' debe ser de 6 dígitos")
                else:
                    validated_count += 1
        
        # Preparar resultado
        result_text = f"Códigos CUPS validados: {validated_count}\n"
        
        if warnings:
            result_text += f"\nAdvertencias:\n" + "\n".join(warnings)
        
        if errors:
            result_text += f"\nErrores:\n" + "\n".join(errors)
            validation_status = False
        else:
            validation_status = True
        
        # Guardar resultado
        self.write({
            'rips_validated_cups': validation_status,
            'rips_validation_cups_date': fields.Datetime.now(),
            'rips_validation_cups_result': result_text
        })

        # OPTIMIZADO: Odoo hace commit automatico

        if errors:
            raise ValidationError(_("Se encontraron errores en la validación CUPS:\n%s") % '\n'.join(errors))
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Validación CUPS'),
                'message': result_text,
                'type': 'success' if validation_status else 'warning',
                'sticky': True,
            }
        }

    # Sobrescribir el método original para usar la versión mejorada
    def generate_rips_json_api(self):
        """Redirige al método mejorado"""
        return self.action_generate_rips_json_improved()

    def action_send_rips_to_minsalud(self):
        """Redirige al método mejorado"""
        return self.action_send_rips_to_minsalud_improved()

    def _get_xml_fev_file(self):
        """Redirige al método mejorado"""
        return self._get_xml_fev_file_improved()
    # =====================================================
    # IMPLEMENTACIÓN DE MÉTODOS ABSTRACTOS
    # =====================================================
    
    @api.model
    def _get_rips_config(self):
        """Obtiene la configuración RIPS activa"""
        return self.env['rips.configuration'].get_config()
    
    def _determine_rips_endpoint_and_payload(self):
        """Determina el endpoint correcto y prepara el payload según el tipo de documento"""
        if self.is_adjustment_note:
            return 'CARGAR_NOTA_AJUSTE', self._prepare_payload_for_endpoint('CARGAR_NOTA_AJUSTE')
        
        if self.is_voluntary_agreement:
            return 'CARGAR_NC_ACUERDO_VOLUNTADES', self._prepare_payload_for_endpoint('CARGAR_NC_ACUERDO_VOLUNTADES')
        
        if self.capita_type:
            if self.capita_type == 'initial':
                return 'CARGAR_CAPITA_INICIAL', self._prepare_payload_for_endpoint('CARGAR_CAPITA_INICIAL')
            elif self.capita_type == 'period':
                return 'CARGAR_CAPITA_PERIODO', self._prepare_payload_for_endpoint('CARGAR_CAPITA_PERIODO')
            elif self.capita_type == 'final':
                return 'CARGAR_CAPITA_FINAL', self._prepare_payload_for_endpoint('CARGAR_CAPITA_FINAL')
        
        if self.rips_without_invoice:
            return 'CARGAR_RIPS_SIN_FACTURA', self._prepare_payload_for_endpoint('CARGAR_RIPS_SIN_FACTURA')
        
        if self.move_type == 'out_invoice':
            return 'CARGAR_FEV_RIPS', self._prepare_payload_for_endpoint('CARGAR_FEV_RIPS')
        elif self.move_type == 'out_refund':
            if self.is_total_credit_note:
                return 'CARGAR_NC_TOTAL', self._prepare_payload_for_endpoint('CARGAR_NC_TOTAL')
            else:
                return 'CARGAR_NC', self._prepare_payload_for_endpoint('CARGAR_NC')
        elif self.move_type == 'in_refund' and hasattr(self, 'is_debit_note') and self.is_debit_note:
            return 'CARGAR_ND', self._prepare_payload_for_endpoint('CARGAR_ND')
        
        return 'CARGAR_RIPS_SIN_FACTURA', self._prepare_payload_for_endpoint('CARGAR_RIPS_SIN_FACTURA')
    
    def _generate_rips_base_structure(self):
        """Genera la estructura base del RIPS"""
        doc_type = self._get_document_type_json()
        
        rips_data_base = {
            "numDocumentoIdObligado": self._validate_string(
                self.company_id.partner_id.vat_co, 
                4, 12, 
                no_leading_zero=True, 
                no_spaces=True
            ),
            "numFactura": self._validate_string(
                self.name, 
                1, 20, 
                no_leading_zero=True, 
                no_spaces=True
            ),
            "tipoNota": None,
            "numNota": None,
            "usuarios": []
        }
        
        if doc_type in ['credit_note', 'debit_note']:
            original_invoice = self.reversed_entry_id or self.debit_origin_id
            if not original_invoice:
                raise UserError(_("La nota debe estar relacionada a una factura para generar RIPS."))
            
            rips_data_base["numFactura"] = self._validate_string(
                original_invoice.name, 
                1, 20, 
                no_leading_zero=True, 
                no_spaces=True
            )
            rips_data_base["tipoNota"] = self._get_rips_note_type_json(doc_type)
            rips_data_base["numNota"] = self._validate_string(
                self.name, 
                1, 20, 
                no_leading_zero=True, 
                no_spaces=True
            )
        
        return rips_data_base
    
    def _should_include_users(self):
        """Determina si debe incluir usuarios en el RIPS"""
        # Siempre incluir usuarios excepto para NC Total y NC Acuerdo
        return not (self.is_total_credit_note or self.is_voluntary_agreement)
    
    def _generate_rips_users(self):
        """Genera la lista de usuarios para el RIPS"""
        usuarios = []
        pacientes_lines = {}
        
        for line in self.invoice_line_ids:
            if not line.patient_doc_type or not line.patient_document:
                if line.product_id and line.product_id.rips_service_type and line.product_id.rips_service_type != 'none':
                    raise UserError(
                        _("La línea de factura para el producto '%s' requiere información del paciente "
                          "(tipo y número de documento) para RIPS.") % line.product_id.name
                    )
                continue
            
            patient_key = (line.patient_doc_type, line.patient_document)
            
            if patient_key not in pacientes_lines:
                pacientes_lines[patient_key] = []
            pacientes_lines[patient_key].append(line)
        
        consecutivo_usuario = 1
        for patient_key, service_lines in pacientes_lines.items():
            demographic_line = service_lines[0]
            
            usuario_data = self._prepare_usuario_data_json(demographic_line, service_lines, consecutivo_usuario)
            if usuario_data:
                usuarios.append(usuario_data)
                consecutivo_usuario += 1
        
        return usuarios
    
    def _get_xml_fev_file(self):
        """Obtiene el XML de la factura (AttachedDocument)"""
        try:
            constants = self.env['dian.document']._generate_dian_constants(self, self.move_type, False)
            xml_content = self.env['dian.xml.builder'].generate_xml(self, constants)
            attached_document, error = self._get_attached_document(xml_content)
            if not error and attached_document:
                return base64.b64encode(attached_document).decode('utf-8')
        except Exception as e:
            _logger.warning(f"Error al obtener AttachedDocument: {str(e)}")
        
        xml_attachment = self.env['ir.attachment'].search([
            ('res_model', '=', 'account.move'),
            ('res_id', '=', self.id),
            '|', '|',
            ('name', 'ilike', '%AttachedDocument%'),
            ('name', 'ilike', '%attached_document%'),
            ('name', 'ilike', '%.xml'),
        ], limit=1, order='id desc')
        
        if xml_attachment:
            return xml_attachment.datas.decode() if isinstance(xml_attachment.datas, bytes) else xml_attachment.datas
        
        if self.move_type in ['out_invoice', 'out_refund']:
            _logger.warning(f"No se encontró XML de factura para {self.name}")
        
        return None
    
    def _generate_empty_rips(self):
        """Genera un RIPS vacío"""
        return {
            "numDocumentoIdObligado": self.company_id.partner_id.vat_co or "",
            "numFactura": self.name,
            "tipoNota": None,
            "numNota": None,
            "usuarios": []
        }
    
    def _generate_capita_rips(self, endpoint_key):
        """Genera RIPS específico para cápita"""
        capita_type_map = {
            'CARGAR_CAPITA_INICIAL': 'initial',
            'CARGAR_CAPITA_PERIODO': 'period',
            'CARGAR_CAPITA_FINAL': 'final'
        }
        
        return {
            "numDocumentoIdObligado": self.company_id.partner_id.vat_co or "",
            "numFactura": self.name,
            "tipoCapita": capita_type_map.get(endpoint_key, 'period'),
            "usuarios": []
        }
    
    # =====================================================
    # MÉTODOS AUXILIARES
    # =====================================================
    
    def _get_document_type_json(self):
        """Determina el tipo de documento"""
        if self.move_type == 'out_invoice':
            return 'invoice'
        elif self.move_type == 'out_refund':
            return 'credit_note'
        elif self.move_type == 'in_refund' and hasattr(self, 'is_debit_note') and self.is_debit_note:
            return 'debit_note'
        return 'invoice'
    
    def _get_rips_note_type_json(self, doc_type):
        """Obtiene el tipo de nota para RIPS"""
        if doc_type == 'credit_note':
            return "NC"
        elif doc_type == 'debit_note':
            return "ND"
        elif self.is_adjustment_note:
            return "NA"
        return None
    
    # Usar métodos de validación del modelo abstracto con alias
    _validate_string_json = AbstractRipsFevMixin._validate_string
    _validate_numeric_json = AbstractRipsFevMixin._validate_numeric
    _validate_date_json = AbstractRipsFevMixin._validate_date
    
    def _prepare_usuario_data_json(self, demographic_line, service_lines, consecutivo):
        """Prepara datos del usuario con valores por defecto"""
        if not demographic_line.patient_doc_type or not demographic_line.patient_document:
            return None
        
        # Zona territorial
        zona_territorial_code = RIPS_DEFAULT_VALUES['ZONA_TERRITORIAL']
        if hasattr(demographic_line, 'patient_zone'):
            if demographic_line.patient_zone == 'rural':
                zona_territorial_code = "02"
            elif demographic_line.patient_zone == 'urbano':
                zona_territorial_code = "01"
        
        # País y municipio
        country_code_val = RIPS_DEFAULT_VALUES['PAIS_DEFAULT']
        municipality_code_val = RIPS_DEFAULT_VALUES['MUNICIPIO_DEFAULT']
        
        if hasattr(demographic_line, 'patient_country_id') and demographic_line.patient_country_id:
            country_code_val = demographic_line.patient_country_id.numeric_code
        if hasattr(demographic_line, 'patient_city_id') and demographic_line.patient_city_id:
            municipality_code_val = demographic_line.patient_city_id.code
            
        nationality_code_val = country_code_val
        if hasattr(demographic_line, 'patient_nationality') and demographic_line.patient_nationality:
            nationality_code_val = demographic_line.patient_nationality
        
        # Tipo de usuario
        tipo_usuario = RIPS_DEFAULT_VALUES['TIPO_USUARIO']
        if hasattr(demographic_line, 'patient_user_type') and demographic_line.patient_user_type:
            tipo_usuario = demographic_line.patient_user_type
        
        usuario = {
            "tipoDocumentoIdentificacion": self._validate_string_json(demographic_line.patient_doc_type, 2, 2),
            "numDocumentoIdentificacion": self._validate_string_json(demographic_line.patient_document, 4, 20, no_leading_zero=False, no_spaces=True),
            "tipoUsuario": self._validate_string_json(tipo_usuario, 2, 2),
            "fechaNacimiento": self._validate_date_json(
                demographic_line.patient_birth_date if hasattr(demographic_line, 'patient_birth_date') else None, 
                '%Y-%m-%d', 
                default="1900-01-01"
            ),
            "codSexo": demographic_line.patient_gender if hasattr(demographic_line, 'patient_gender') else 'I',
            "codPaisResidencia": self._validate_string_json(country_code_val, 1, 3),
            "codMunicipioResidencia": self._validate_string_json(municipality_code_val, 5, 5),
            "codZonaTerritorialResidencia": self._validate_string_json(zona_territorial_code, 2, 2),
            "incapacidad": "NO",
            "consecutivo": self._validate_numeric_json(consecutivo, decimals=0),
            "codPaisOrigen": self._validate_string_json(nationality_code_val, 1, 3),
            "servicios": {}
        }
        
        # Procesar servicios
        servicios_data = {
            'consultas': [],
            'procedimientos': [],
            'medicamentos': [],
            'otrosServicios': []
        }
        
        consecutivos_servicios = {
            'consulta': 1,
            'procedimiento': 1,
            'medicamento': 1,
            'otro_servicio': 1
        }
        
        for line in service_lines:
            if not line.product_id or not line.product_id.rips_service_type or line.product_id.rips_service_type == 'none':
                continue
            
            service_type = line.product_id.rips_service_type
            servicio_dict = None
            current_consecutivo = consecutivos_servicios[service_type]
            
            if service_type == 'consulta':
                servicio_dict = self._prepare_consulta_data_json(line, current_consecutivo)
                if servicio_dict:
                    servicios_data['consultas'].append(servicio_dict)
            elif service_type == 'procedimiento':
                servicio_dict = self._prepare_procedimiento_data_json(line, current_consecutivo)
                if servicio_dict:
                    servicios_data['procedimientos'].append(servicio_dict)
            elif service_type == 'medicamento':
                servicio_dict = self._prepare_medicamento_data_json(line, current_consecutivo)
                if servicio_dict:
                    servicios_data['medicamentos'].append(servicio_dict)
            elif service_type == 'otro_servicio':
                servicio_dict = self._prepare_otro_servicio_data_json(line, current_consecutivo)
                if servicio_dict:
                    servicios_data['otrosServicios'].append(servicio_dict)
            
            if servicio_dict:
                consecutivos_servicios[service_type] += 1
        
        # Agregar servicios al usuario
        for tipo_servicio_key, datos_servicios in servicios_data.items():
            if datos_servicios:
                usuario["servicios"][tipo_servicio_key] = datos_servicios
        
        if not any(servicios_data.values()):
            _logger.info(_("Patient %s %s has no valid RIPS services.") % 
                        (demographic_line.patient_doc_type, demographic_line.patient_document))
            return None
        
        return usuario
    
    def _prepare_consulta_data_json(self, line, consecutivo):
        """Prepara datos de consulta con valores por defecto"""
        cod_prestador = self.company_id.partner_id.ref or RIPS_DEFAULT_VALUES['CODIGO_PRESTADOR']
        cod_prestador = self._validate_string_json(cod_prestador, 12, 12, no_spaces=True)
        
        fecha_atencion = line.fecha_atencion or self.date or fields.Datetime.now()
        
        num_autorizacion = self._validate_string_json(
            line.autorizacion, 
            1, 30, 
            no_leading_zero=True, 
            no_spaces=True, 
            allow_null=True
        )
        
        cod_consulta = self._validate_string_json(
            self._validate_product_code_json(line.product_id, 'consulta'), 
            6, 6, 
            no_leading_zero=True, 
            no_spaces=True, 
            default=RIPS_DEFAULT_VALUES['CUPS_CONSULTA']
        )
        
        modalidad = line.modalidad or RIPS_DEFAULT_VALUES['MODALIDAD_ATENCION']
        grupo_servicio = line.grupo_servicio or RIPS_DEFAULT_VALUES['GRUPO_SERVICIO_CONSULTA']
        finalidad = line.finalidad or RIPS_DEFAULT_VALUES['FINALIDAD_CONSULTA']
        causa_externa = line.causa_externa or RIPS_DEFAULT_VALUES['CAUSA_EXTERNA']
        tipo_diagnostico = line.tipo_diagnostico or RIPS_DEFAULT_VALUES['TIPO_DIAGNOSTICO']
        cod_servicio = RIPS_DEFAULT_VALUES['COD_SERVICIO_CONSULTA']
        
        if hasattr(line, 'cod_servicio') and line.cod_servicio:
            try:
                cod_servicio = int(line.cod_servicio)
            except (ValueError, TypeError):
                pass
        
        cod_diagnostico_principal = self._validate_string_json(
            line.diagnostico_principal, 
            4, 25, 
            no_leading_zero=True, 
            no_spaces=True, 
            default=RIPS_DEFAULT_VALUES['DIAGNOSTICO_DEFAULT']
        )
        
        tipo_doc_profesional = RIPS_DEFAULT_VALUES['PROFESIONAL_DOC_TYPE']
        num_doc_profesional = RIPS_DEFAULT_VALUES['PROFESIONAL_DOC_NUMBER']
        
        if hasattr(line, 'professional_id') and line.professional_id:
            if line.professional_id.l10n_latam_identification_type_id:
                tipo_doc_profesional = line.professional_id.l10n_latam_identification_type_id.heath_code or tipo_doc_profesional
            if line.professional_id.vat:
                num_doc_profesional = line.professional_id.vat
        
        num_doc_profesional = self._validate_string_json(
            num_doc_profesional, 
            4, 20, 
            no_leading_zero=True, 
            no_spaces=True
        )
        
        valor_servicio = self._validate_numeric_json(
            line.price_subtotal if line.price_subtotal > 0 else 0, 
            decimals=2
        )
        
        valor_moderador = self._validate_numeric_json(
            line.valor_pago_moderador if hasattr(line, 'valor_pago_moderador') and line.valor_pago_moderador > 0 else 0, 
            decimals=2
        )
        
        num_fev_pago_moderador = self._validate_string_json(
            line.num_fev_pago_moderador if hasattr(line, 'num_fev_pago_moderador') else None, 
            max_length=14, 
            allow_null=True
        )
        
        concepto_recaudo = line.tipo_pago_moderador if hasattr(line, 'tipo_pago_moderador') else RIPS_DEFAULT_VALUES['CONCEPTO_RECAUDO']
        
        return {
            "codPrestador": cod_prestador,
            "fechaInicioAtencion": self._validate_date_json(fecha_atencion, '%Y-%m-%d %H:%M'),
            "numAutorizacion": num_autorizacion,
            "codConsulta": cod_consulta,
            "modalidadGrupoServicioTecSal": modalidad,
            "grupoServicios": grupo_servicio,
            "codServicio": cod_servicio,
            "finalidadTecnologiaSalud": finalidad,
            "causaMotivoAtencion": causa_externa,
            "codDiagnosticoPrincipal": cod_diagnostico_principal,
            "tipoDiagnosticoPrincipal": tipo_diagnostico,
            "tipoDocumentoIdentificacion": tipo_doc_profesional,
            "numDocumentoIdentificacion": num_doc_profesional,
            "vrServicio": valor_servicio,
            "conceptoRecaudo": concepto_recaudo,
            "valorPagoModerador": valor_moderador,
            "numFEVPagoModerador": num_fev_pago_moderador,
            "consecutivo": self._validate_numeric_json(consecutivo, decimals=0)
        }
    
    def _prepare_procedimiento_data_json(self, line, consecutivo):
        """Prepara datos de procedimiento con valores por defecto"""
        cod_prestador = self.company_id.partner_id.ref or RIPS_DEFAULT_VALUES['CODIGO_PRESTADOR']
        cod_prestador = self._validate_string_json(cod_prestador, 12, 12, no_spaces=True)
        
        fecha_atencion = line.fecha_procedimiento if hasattr(line, 'fecha_procedimiento') else (self.date or fields.Datetime.now())
        
        num_autorizacion = self._validate_string_json(
            line.autorizacion if hasattr(line, 'autorizacion') else None, 
            1, 30, 
            no_leading_zero=True, 
            no_spaces=True, 
            allow_null=True
        )
        
        cod_procedimiento = self._validate_string_json(
            self._validate_product_code_json(line.product_id, 'procedimiento'), 
            6, 6, 
            no_spaces=True, 
            default=RIPS_DEFAULT_VALUES['CUPS_PROCEDIMIENTO']
        )
        
        via_ingreso = RIPS_DEFAULT_VALUES['VIA_INGRESO']
        modalidad = RIPS_DEFAULT_VALUES['MODALIDAD_ATENCION']
        grupo_servicio = RIPS_DEFAULT_VALUES['GRUPO_SERVICIO_PROCEDIMIENTO']
        finalidad = RIPS_DEFAULT_VALUES['FINALIDAD_PROCEDIMIENTO']
        cod_servicio = RIPS_DEFAULT_VALUES['COD_SERVICIO_PROCEDIMIENTO']
        
        if line.product_id:
            if hasattr(line.product_id, 'rips_via_ingreso') and line.product_id.rips_via_ingreso:
                via_ingreso = line.product_id.rips_via_ingreso
            if hasattr(line.product_id, 'rips_modalidad') and line.product_id.rips_modalidad:
                modalidad = line.product_id.rips_modalidad
            if hasattr(line.product_id, 'rips_grupo_servicio') and line.product_id.rips_grupo_servicio:
                grupo_servicio = line.product_id.rips_grupo_servicio
            if hasattr(line.product_id, 'rips_finalidad') and line.product_id.rips_finalidad:
                finalidad = line.product_id.rips_finalidad
            if hasattr(line.product_id, 'rips_cod_servicio') and line.product_id.rips_cod_servicio:
                try:
                    cod_servicio = int(line.product_id.rips_cod_servicio)
                except:
                    pass
        
        tipo_doc_profesional = RIPS_DEFAULT_VALUES['PROFESIONAL_DOC_TYPE']
        num_doc_profesional = RIPS_DEFAULT_VALUES['PROFESIONAL_DOC_NUMBER']
        
        if hasattr(line, 'professional_id') and line.professional_id:
            if line.professional_id.l10n_latam_identification_type_id:
                tipo_doc_profesional = line.professional_id.l10n_latam_identification_type_id.heath_code or tipo_doc_profesional
            if line.professional_id.vat:
                num_doc_profesional = line.professional_id.vat
        
        num_doc_profesional = self._validate_string_json(num_doc_profesional, 4, 20, no_leading_zero=True, no_spaces=True)
        
        cod_diagnostico_principal = self._validate_string_json(
            line.diagnostico_principal if hasattr(line, 'diagnostico_principal') else None, 
            4, 25, 
            no_leading_zero=True, 
            no_spaces=True, 
            default=RIPS_DEFAULT_VALUES['DIAGNOSTICO_DEFAULT']
        )
        
        cod_diagnostico_relacionado = self._validate_string_json(
            line.diagnostico_relacionado if hasattr(line, 'diagnostico_relacionado') else None, 
            4, 25, 
            no_leading_zero=True, 
            no_spaces=True, 
            allow_null=True
        )
        
        cod_complicacion = self._validate_string_json(
            line.complicacion if hasattr(line, 'complicacion') else None, 
            4, 25, 
            no_leading_zero=True, 
            no_spaces=True, 
            allow_null=True
        )
        
        valor_servicio = self._validate_numeric_json(line.price_subtotal if line.price_subtotal > 0 else 0, decimals=2)
        valor_moderador = self._validate_numeric_json(
            line.valor_pago_moderador if hasattr(line, 'valor_pago_moderador') and line.valor_pago_moderador > 0 else 0, 
            decimals=2
        )
        
        num_fev_pago_moderador = line.num_fev_pago_moderador if hasattr(line, 'num_fev_pago_moderador') else None
        
        concepto_recaudo = self.health_collection_concept_id.code if self.health_collection_concept_id else RIPS_DEFAULT_VALUES['CONCEPTO_RECAUDO']
        
        return {
            "codPrestador": cod_prestador,
            "fechaInicioAtencion": self._validate_date_json(fecha_atencion, '%Y-%m-%d %H:%M'),
            "idMIPRES": None,
            "numAutorizacion": num_autorizacion,
            "codProcedimiento": cod_procedimiento,
            "viaIngresoServicioSalud": via_ingreso,
            "modalidadGrupoServicioTecSal": modalidad,
            "grupoServicios": grupo_servicio,
            "codServicio": cod_servicio,
            "finalidadTecnologiaSalud": finalidad,
            "tipoDocumentoIdentificacion": tipo_doc_profesional,
            "numDocumentoIdentificacion": num_doc_profesional,
            "codDiagnosticoPrincipal": cod_diagnostico_principal,
            "codDiagnosticoRelacionado": None,
            "codComplicacion": None,
            "vrServicio": round(line.price_subtotal, 2),
            "conceptoRecaudo": concepto_recaudo,
            "valorPagoModerador": 0.0,
            "numFEVPagoModerador": None,
            "consecutivo": self._validate_numeric_json(consecutivo, decimals=0)
        }
    
    def _prepare_medicamento_data_json(self, line, consecutivo):
        """Prepara datos de medicamento con valores por defecto"""
        cod_prestador = self.company_id.partner_id.ref or RIPS_DEFAULT_VALUES['CODIGO_PRESTADOR']
        cod_prestador = self._validate_string_json(cod_prestador, 12, 12, no_spaces=True)
        
        fecha_dispensacion = line.fecha_dispensacion if hasattr(line, 'fecha_dispensacion') else (self.date or fields.Date.today())
        
        num_autorizacion = self._validate_string_json(
            line.autorizacion if hasattr(line, 'autorizacion') else None, 
            1, 30, 
            no_leading_zero=True, 
            no_spaces=True, 
            allow_null=True
        )
        
        id_mipres_val = self._validate_string_json(
            line.id_mipres if hasattr(line, 'id_mipres') else None, 
            1, 15, 
            no_leading_zero=True, 
            no_spaces=True, 
            allow_null=True
        )
        
        cod_diagnostico_principal = self._validate_string_json(
            line.diagnostico_principal if hasattr(line, 'diagnostico_principal') else None, 
            4, 25, 
            no_leading_zero=True, 
            no_spaces=True, 
            default=RIPS_DEFAULT_VALUES['DIAGNOSTICO_DEFAULT']
        )
        
        cod_diagnostico_relacionado = self._validate_string_json(
            line.diagnostico_relacionado1 if hasattr(line, 'diagnostico_relacionado1') else None, 
            4, 25, 
            no_leading_zero=True, 
            no_spaces=True, 
            allow_null=True
        )
        
        tipo_medicamento = self._validate_string_json(
            line.tipo_medicamento if hasattr(line, 'tipo_medicamento') else None, 
            2, 2, 
            default="01"
        )
        
        cod_tecnologia_salud = self._validate_string_json(
            self._validate_product_code_json(line.product_id, 'medicamento'), 
            1, 20, 
            default=""
        )
        
        nom_tecnologia_salud = self._validate_string_json(
            line.product_id.name if line.product_id else "", 
            1, 30, 
            no_leading_zero=True, 
            default=""
        )
        
        concentracion_val = 0
        unidad_medida_val = 0
        forma_farmaceutica_val = None
        
        if tipo_medicamento == '03':  # Preparación Magistral
            concentracion_val = self._validate_numeric_json(
                line.concentracion if hasattr(line, 'concentracion') else 0, 
                decimals=2
            )
            unidad_medida_val = self._validate_numeric_json(
                line.unidad_medida if hasattr(line, 'unidad_medida') else 0, 
                decimals=0
            )
            forma_farmaceutica_val = self._validate_string_json(
                line.forma_farmaceutica if hasattr(line, 'forma_farmaceutica') else None, 
                max_length=20, 
                allow_null=True
            )
        
        cantidad = self._validate_numeric_json(line.quantity if line.quantity > 0 else 1, decimals=2)
        dias_tratamiento = self._validate_numeric_json(
            line.dias_tratamiento if hasattr(line, 'dias_tratamiento') and line.dias_tratamiento > 0 else 1, 
            decimals=0
        )
        unidad_min_dispensacion = self._validate_numeric_json(
            line.unidad_min_dispensacion if hasattr(line, 'unidad_min_dispensacion') and line.unidad_min_dispensacion > 0 else 1, 
            decimals=0
        )
        
        tipo_doc_profesional = RIPS_DEFAULT_VALUES['PROFESIONAL_DOC_TYPE']
        num_doc_profesional = RIPS_DEFAULT_VALUES['PROFESIONAL_DOC_NUMBER']
        
        if hasattr(line, 'professional_id') and line.professional_id:
            if line.professional_id.l10n_latam_identification_type_id:
                tipo_doc_profesional = line.professional_id.l10n_latam_identification_type_id.heath_code or tipo_doc_profesional
            if line.professional_id.vat:
                num_doc_profesional = line.professional_id.vat
        
        num_doc_profesional = self._validate_string_json(num_doc_profesional, 4, 20, no_leading_zero=True, no_spaces=True)
        
        valor_unitario = self._validate_numeric_json(line.price_unit if line.price_unit > 0 else 0, decimals=2)
        valor_servicio = self._validate_numeric_json(line.price_subtotal if line.price_subtotal > 0 else 0, decimals=2)
        valor_moderador = self._validate_numeric_json(
            line.valor_pago_moderador if hasattr(line, 'valor_pago_moderador') and line.valor_pago_moderador > 0 else 0, 
            decimals=2
        )
        num_fev_pago_moderador = self._validate_string_json(
            line.num_fev_pago_moderador if hasattr(line, 'num_fev_pago_moderador') else None, 
            max_length=14, 
            allow_null=True
        )
        
        concepto_recaudo = self.health_collection_concept_id.code if self.health_collection_concept_id else RIPS_DEFAULT_VALUES['CONCEPTO_RECAUDO']
        
        return {
            "codPrestador": cod_prestador,
            "numAutorizacion": num_autorizacion,
            "idMIPRES": id_mipres_val,
            "fechaDispensAdmon": self._validate_date_json(fecha_dispensacion, '%Y-%m-%d %H:%M'),
            "codDiagnosticoPrincipal": cod_diagnostico_principal,
            "codDiagnosticoRelacionado": cod_diagnostico_relacionado,
            "tipoMedicamento": tipo_medicamento,
            "codTecnologiaSalud": cod_tecnologia_salud,
            "nomTecnologiaSalud": nom_tecnologia_salud,
            "concentracionMedicamento": concentracion_val,
            "unidadMedida": unidad_medida_val,
            "formaFarmaceutica": forma_farmaceutica_val,
            "unidadMinDispensa": unidad_min_dispensacion,
            "cantidadMedicamento": cantidad,
            "diasTratamiento": dias_tratamiento,
            "tipoDocumentoIdentificacion": tipo_doc_profesional,
            "numDocumentoIdentificacion": num_doc_profesional,
            "vrUnitMedicamento": valor_unitario,
            "vrServicio": valor_servicio,
            "conceptoRecaudo": concepto_recaudo,
            "valorPagoModerador": valor_moderador,
            "numFEVPagoModerador": num_fev_pago_moderador,
            "consecutivo": self._validate_numeric_json(consecutivo, decimals=0)
        }
    
    def _prepare_otro_servicio_data_json(self, line, consecutivo):
        """Prepara datos de otro servicio con valores por defecto"""
        cod_prestador = self.company_id.partner_id.ref or RIPS_DEFAULT_VALUES['CODIGO_PRESTADOR']
        cod_prestador = self._validate_string_json(cod_prestador, 12, 12, no_spaces=True)
        
        fecha_suministro = self.date_start or fields.Date.today()
        if hasattr(line, 'fecha_suministro') and line.fecha_suministro:
            fecha_suministro = line.fecha_suministro
        elif line.treatment_id and line.treatment_id.start_date:
            fecha_suministro = line.treatment_id.start_date
        
        num_autorizacion = self._validate_string_json(
            line.autorizacion if hasattr(line, 'autorizacion') else None, 
            1, 30, 
            no_leading_zero=True, 
            no_spaces=True, 
            allow_null=True
        )
        
        id_mipres_val = self._validate_string_json(
            line.id_mipres if hasattr(line, 'id_mipres') else None, 
            1, 15, 
            no_leading_zero=True, 
            no_spaces=True, 
            allow_null=True
        )
        
        tipo_os = self._validate_string_json(
            line.tipo_servicio if hasattr(line, 'tipo_servicio') else None, 
            2, 2, 
            default="01"
        )
        
        cod_tecnologia_salud = self._validate_string_json(
            self._validate_product_code_json(line.product_id, 'otro_servicio'), 
            1, 20, 
            no_leading_zero=True, 
            no_spaces=True
        )
        
        nom_tecnologia_salud = self._validate_string_json(
            line.product_id.name if line.product_id else "", 
            1, 60, 
            no_leading_zero=True
        )
        
        cantidad = self._validate_numeric_json(line.quantity if line.quantity > 0 else 1, decimals=2)
        valor_unitario = self._validate_numeric_json(line.price_unit if line.price_unit > 0 else 0, decimals=2)
        valor_servicio = self._validate_numeric_json(line.price_subtotal if line.price_subtotal > 0 else 0, decimals=2)
        
        tipo_doc_profesional = RIPS_DEFAULT_VALUES['PROFESIONAL_DOC_TYPE']
        num_doc_profesional = RIPS_DEFAULT_VALUES['PROFESIONAL_DOC_NUMBER']
        
        valor_moderador = self._validate_numeric_json(
            line.valor_pago_moderador if hasattr(line, 'valor_pago_moderador') and line.valor_pago_moderador > 0 else 0, 
            decimals=2
        )
        num_fev_pago_moderador = self._validate_string_json(
            line.num_fev_pago_moderador if hasattr(line, 'num_fev_pago_moderador') else None, 
            max_length=14, 
            allow_null=True
        )
        
        concepto_recaudo = line.tipo_pago_moderador if hasattr(line, 'tipo_pago_moderador') else RIPS_DEFAULT_VALUES['CONCEPTO_RECAUDO']
        
        return {
            "codPrestador": cod_prestador,
            "numAutorizacion": num_autorizacion,
            "idMIPRES": id_mipres_val,
            "fechaSuministroTecnologia": self._validate_date_json(fecha_suministro, '%Y-%m-%d %H:%M'),
            "tipoOS": tipo_os,
            "codTecnologiaSalud": cod_tecnologia_salud,
            "nomTecnologiaSalud": nom_tecnologia_salud,
            "cantidadOS": cantidad,
            "vrUnitOS": valor_unitario,
            "vrServicio": valor_servicio,
            "tipoDocumentoIdentificacion": tipo_doc_profesional,
            "numDocumentoIdentificacion": num_doc_profesional,
            "conceptoRecaudo": concepto_recaudo,
            "valorPagoModerador": valor_moderador,
            "numFEVPagoModerador": num_fev_pago_moderador,
            "consecutivo": self._validate_numeric_json(consecutivo, decimals=0)
        }
    
    def _validate_product_code_json(self, product, service_type):
        """Valida código del producto según tipo de servicio"""
        if not product:
            return {
                "consulta": RIPS_DEFAULT_VALUES['CUPS_CONSULTA'],
                "procedimiento": RIPS_DEFAULT_VALUES['CUPS_PROCEDIMIENTO']
            }.get(service_type, "")
        
        code_to_use = product.default_code or ""
        
        # Para servicios CUPS
        if service_type in ['consulta', 'procedimiento']:
            if hasattr(product, 'code_type') and product.code_type:
                if product.code_type == 'cups' and hasattr(product, 'cups_id') and product.cups_id and product.cups_id.code:
                    code_to_use = product.cups_id.code
                elif product.code_type == 'custom' and hasattr(product, 'custom_code') and product.custom_code:
                    code_to_use = product.custom_code
        
        # Para medicamentos
        elif service_type == 'medicamento' and hasattr(product, 'is_cums') and product.is_cums:
            cums_parts = []
            if hasattr(product, 'atc') and product.atc:
                cums_parts.append(product.atc)
            if hasattr(product, 'expedient') and product.expedient:
                cums_parts.append(product.expedient)
            if hasattr(product, 'consecutive') and product.consecutive:
                cums_parts.append(product.consecutive)
            if cums_parts:
                if len(cums_parts) == 3:
                    code_to_use = "".join(cums_parts[:2]) + "-" + cums_parts[2]
                else:
                    code_to_use = "".join(cums_parts)
        
        # Valores por defecto según tipo
        default_for_type = {
            "consulta": RIPS_DEFAULT_VALUES['CUPS_CONSULTA'],
            "procedimiento": RIPS_DEFAULT_VALUES['CUPS_PROCEDIMIENTO']
        }.get(service_type, "")
        
        # Parámetros de validación según tipo
        if service_type in ['consulta', 'procedimiento']:
            min_len, max_len = 6, 6
            no_lead_zero = service_type == 'consulta'
            no_space = True
        else:
            min_len, max_len = 1, 20
            no_lead_zero = True
            no_space = True
        
        return self._validate_string_json(
            code_to_use, 
            min_len, 
            max_len, 
            no_leading_zero=no_lead_zero, 
            no_spaces=no_space, 
            default=default_for_type
        )

class RipsErrorViewerWizard(models.TransientModel):
    _name = 'rips.error.viewer.wizard'
    _description = 'Visor de Errores RIPS'
    
    name = fields.Char('Título', readonly=True)
    html_content = fields.Html('Contenido', readonly=True, sanitize=False)
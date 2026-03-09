# -*- coding: utf-8 -*-

from odoo import api,fields,models,_
import json
import base64
from odoo.exceptions import UserError , ValidationError
from datetime import timedelta
from datetime import datetime,date
from typing import Dict, List, Tuple, Any,Optional
from dateutil.relativedelta import relativedelta
import logging
_logger = logging.getLogger(__name__)
from decimal import Decimal, ROUND_HALF_DOWN
import re
import io
import zipfile

def json_serial(obj: Any) -> Any:
    """Serializa objetos especiales para JSON."""
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    elif isinstance(obj, Decimal):
        return float(obj)
    elif hasattr(obj, '_name'):
        return {
            'id': getattr(obj, 'id', None),
            'name': getattr(obj, 'name', ''),
            'model': getattr(obj, '_name', '')
        }
    elif hasattr(obj, 'name') and callable(getattr(obj, 'name_get', None)):
        return dict(obj.name_get()[0]) if obj.name_get() else str(obj)
    elif hasattr(obj, '__dict__'):
        return {k: v for k, v in obj.__dict__.items() 
                if not k.startswith('_') and not callable(v)}
    raise TypeError(f"Type {type(obj)} not serializable")

class RIPSValidator(models.AbstractModel):
    _name = 'rips.validator'
    _description = 'Validador RIPS JSON'
    
    def validate_rips_data(self, rips_data):
        """
        Valida la estructura y campos del RIPS JSON
        
        :param rips_data: Datos RIPS en formato dict
        :return: (bool, str) - Tupla con resultado (éxito/error) y mensaje
        """
        if not rips_data:
            return False, _("No hay datos RIPS para validar")
        errors = []
        self._validate_main_fields(rips_data, errors)
        if 'usuarios' not in rips_data or not rips_data['usuarios']:
            errors.append(_("El RIPS no contiene usuarios"))
        else:
            for i, usuario in enumerate(rips_data['usuarios']):
                self._validate_usuario(usuario, i+1, errors)
        
        if errors:
            return False, "\n".join(errors)
        return True, _("Validación RIPS exitosa")
    
    def _validate_main_fields(self, rips_data, errors):
        """Valida los campos principales del RIPS"""
        required_fields = ['numDocumentoIdObligado', 'numFactura']
        
        for field in required_fields:
            if field not in rips_data or not rips_data[field]:
                errors.append(_("Campo requerido faltante: %s") % field)
        
        if 'numDocumentoIdObligado' in rips_data and rips_data['numDocumentoIdObligado']:
            nit = rips_data['numDocumentoIdObligado']
            if not re.match(r'^\d{8,12}$', nit):
                errors.append(_("El NIT debe contener entre 8 y 12 dígitos"))
    
    def _validate_usuario(self, usuario, index, errors):
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
        
        if 'fechaNacimiento' in usuario and usuario['fechaNacimiento']:
            if not re.match(r'^\d{4}-\d{2}-\d{2}$', usuario['fechaNacimiento']):
                errors.append(_("Usuario #%s: Formato inválido de fecha de nacimiento. Debe ser YYYY-MM-DD") % index)
        
        if 'tipoDocumentoIdentificacion' in usuario and usuario['tipoDocumentoIdentificacion']:
            valid_doc_types = ['CC', 'TI', 'RC', 'CE', 'PA', 'MS', 'AS', 'PE']
            if usuario['tipoDocumentoIdentificacion'] not in valid_doc_types:
                errors.append(_("Usuario #%s: Tipo de documento inválido: %s") % (index, usuario['tipoDocumentoIdentificacion']))
        
        if 'tipoUsuario' in usuario and usuario['tipoUsuario']:
            valid_user_types = ['01', '02', '03', '04', '05', '06', '07', '08']
            if usuario['tipoUsuario'] not in valid_user_types:
                errors.append(_("Usuario #%s: Tipo de usuario inválido: %s") % (index, usuario['tipoUsuario']))
        
        if 'codSexo' in usuario and usuario['codSexo']:
            if usuario['codSexo'] not in ['M', 'F']:
                errors.append(_("Usuario #%s: Sexo inválido: %s. Debe ser M o F") % (index, usuario['codSexo']))
        
        if 'servicios' not in usuario or not usuario['servicios']:
            errors.append(_("Usuario #%s: No contiene servicios") % index)
        else:
            self._validate_servicios(usuario['servicios'], index, errors)
    
    def _validate_servicios(self, servicios, usuario_index, errors):
        """Valida los servicios de un usuario"""
        if not any(servicios.get(tipo) for tipo in ['consultas', 'procedimientos', 'medicamentos', 'otrosServicios']):
            errors.append(_("Usuario #%s: Debe tener al menos un servicio") % usuario_index)
            return
            
        if 'consultas' in servicios and servicios['consultas']:
            for i, consulta in enumerate(servicios['consultas']):
                self._validate_consulta(consulta, usuario_index, i+1, errors)
                
        if 'procedimientos' in servicios and servicios['procedimientos']:
            for i, procedimiento in enumerate(servicios['procedimientos']):
                self._validate_procedimiento(procedimiento, usuario_index, i+1, errors)
                
        if 'medicamentos' in servicios and servicios['medicamentos']:
            for i, medicamento in enumerate(servicios['medicamentos']):
                self._validate_medicamento(medicamento, usuario_index, i+1, errors)
                
        if 'otrosServicios' in servicios and servicios['otrosServicios']:
            for i, otro_servicio in enumerate(servicios['otrosServicios']):
                self._validate_otro_servicio(otro_servicio, usuario_index, i+1, errors)
    
    def _validate_consulta(self, consulta, usuario_index, consulta_index, errors):
        """Valida datos de una consulta"""
        required_fields = [
            'codPrestador',
            'fechaInicioAtencion',
            'codConsulta',
            'modalidadGrupoServicioTecSal',
            'grupoServicios',
            'codServicio',
            'finalidadTecnologiaSalud',
            'causaMotivoAtencion',
            'codDiagnosticoPrincipal',
            'tipoDiagnosticoPrincipal',
            'vrConsulta'
        ]
        
        for field in required_fields:
            if field not in consulta or consulta[field] is None or consulta[field] == '':
                errors.append(_("Usuario #%s, Consulta #%s: Campo requerido faltante: %s") % 
                             (usuario_index, consulta_index, field))
        
        if 'codPrestador' in consulta and consulta['codPrestador']:
            if not re.match(r'^\d{12}$', consulta['codPrestador']):
                errors.append(_("Usuario #%s, Consulta #%s: Código prestador debe tener 12 dígitos") % 
                             (usuario_index, consulta_index))
        
        if 'fechaInicioAtencion' in consulta and consulta['fechaInicioAtencion']:
            if not re.match(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$', consulta['fechaInicioAtencion']):
                errors.append(_("Usuario #%s, Consulta #%s: Formato de fecha inválido. Debe ser YYYY-MM-DD HH:MM") % 
                             (usuario_index, consulta_index))
        
        if 'codDiagnosticoPrincipal' in consulta and consulta['codDiagnosticoPrincipal']:
            if not re.match(r'^[A-Z]\d{2}(\.\d+)?$', consulta['codDiagnosticoPrincipal']):
                errors.append(_("Usuario #%s, Consulta #%s: Formato inválido de diagnóstico principal") % 
                             (usuario_index, consulta_index))
        
        if 'tipoDiagnosticoPrincipal' in consulta and consulta['tipoDiagnosticoPrincipal']:
            valid_types = ['01', '02', '03']
            if consulta['tipoDiagnosticoPrincipal'] not in valid_types:
                errors.append(_("Usuario #%s, Consulta #%s: Tipo de diagnóstico inválido: %s") % 
                             (usuario_index, consulta_index, consulta['tipoDiagnosticoPrincipal']))
    
    def _validate_procedimiento(self, procedimiento, usuario_index, proc_index, errors):
        """Valida datos de un procedimiento"""
        required_fields = [
            'codPrestador',
            'fechaInicioAtencion',
            'codProcedimiento',
            'viaIngresoServicioSalud',
            'modalidadGrupoServicioTecSal',
            'grupoServicios',
            'codServicio',
            'finalidadTecnologiaSalud',
            'codDiagnosticoPrincipal',
            'vrProcedimiento'
        ]
        
        for field in required_fields:
            if field not in procedimiento or procedimiento[field] is None or procedimiento[field] == '':
                errors.append(_("Usuario #%s, Procedimiento #%s: Campo requerido faltante: %s") % 
                             (usuario_index, proc_index, field))
        
        if 'codPrestador' in procedimiento and procedimiento['codPrestador']:
            if not re.match(r'^\d{12}$', procedimiento['codPrestador']):
                errors.append(_("Usuario #%s, Procedimiento #%s: Código prestador debe tener 12 dígitos") % 
                             (usuario_index, proc_index))
        
        if 'fechaInicioAtencion' in procedimiento and procedimiento['fechaInicioAtencion']:
            if not re.match(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$', procedimiento['fechaInicioAtencion']):
                errors.append(_("Usuario #%s, Procedimiento #%s: Formato de fecha inválido. Debe ser YYYY-MM-DD HH:MM") % 
                             (usuario_index, proc_index))
        
        if 'codProcedimiento' in procedimiento and procedimiento['codProcedimiento']:
            if not re.match(r'^\d{6}$', procedimiento['codProcedimiento']):
                errors.append(_("Usuario #%s, Procedimiento #%s: Formato inválido de código CUPS") % 
                             (usuario_index, proc_index))
    
    def _validate_medicamento(self, medicamento, usuario_index, med_index, errors):
        """Valida datos de un medicamento"""
        required_fields = [
            'codPrestador',
            'fechaDispensacion',
            'tipoMedicamento',
            'codTecnologiaSalud',
            'cantidadMedicamento',
            'diasTratamiento',
            'vrUnitMedicamento',
            'vrServicio'
        ]
        
        for field in required_fields:
            if field not in medicamento or medicamento[field] is None or medicamento[field] == '':
                errors.append(_("Usuario #%s, Medicamento #%s: Campo requerido faltante: %s") % 
                             (usuario_index, med_index, field))
        
        if 'tipoMedicamento' in medicamento and medicamento['tipoMedicamento']:
            valid_types = ['01', '02', '03']
            if medicamento['tipoMedicamento'] not in valid_types:
                errors.append(_("Usuario #%s, Medicamento #%s: Tipo de medicamento inválido: %s") % 
                             (usuario_index, med_index, medicamento['tipoMedicamento']))
                
        if medicamento.get('tipoMedicamento') == '03':
            magistral_fields = ['nomTecnologiaSalud', 'concentracionMedicamento', 'unidadMedida']
            for field in magistral_fields:
                if field not in medicamento or medicamento[field] is None or medicamento[field] == '':
                    errors.append(_("Usuario #%s, Medicamento #%s: Campo requerido para preparación magistral faltante: %s") % 
                                (usuario_index, med_index, field))
    
    def _validate_otro_servicio(self, otro_servicio, usuario_index, os_index, errors):
        """Valida datos de otro servicio"""
        required_fields = [
            'codPrestador',
            'fechaSuministroTecnologia',
            'tipoOS',
            'cantidadOS',
            'vrUnitOS',
            'vrServicio'
        ]
        for field in required_fields:
            if field not in otro_servicio or otro_servicio[field] is None or otro_servicio[field] == '':
                errors.append(_("Usuario #%s, Otro Servicio #%s: Campo requerido faltante: %s") % 
                             (usuario_index, os_index, field))
        if 'tipoOS' in otro_servicio and otro_servicio['tipoOS']:
            valid_types = ['01', '02', '03', '04']
            if otro_servicio['tipoOS'] not in valid_types:
                errors.append(_("Usuario #%s, Otro Servicio #%s: Tipo de servicio inválido: %s") % 
                             (usuario_index, os_index, otro_servicio['tipoOS']))
        if otro_servicio.get('tipoOS') == '01': 
            if not otro_servicio.get('nomTecnologiaSalud'):
                errors.append(_("Usuario #%s, Otro Servicio #%s: Para servicios complementarios, se requiere el nombre de la tecnología") % 
                             (usuario_index, os_index))
        else:
            if not otro_servicio.get('codTecnologiaSalud'):
                errors.append(_("Usuario #%s, Otro Servicio #%s: Para este tipo de servicio, se requiere el código de la tecnología") % 
                             (usuario_index, os_index))

class AccountMove(models.Model):
    _inherit = 'account.move'

    ref_physician_id = fields.Many2one('res.partner', ondelete='restrict', string='Referring Physician', 
        index=True, help='Referring Physician')
    appointment_id = fields.Many2one('hms.appointment', string='Appointment')
    procedure_id = fields.Many2one('acs.patient.procedure', string='Patient Procedure')
    hospital_invoice_type = fields.Selection(selection_add=[('appointment', 'Appointment'), ('treatment','Treatment'), ('procedure','Procedure')])
    date_start = fields.Date(string='Fecha Inicio',  default=fields.Date.today)
    date_end = fields.Date(string='Fecha Fin')
    invoice_type = fields.Selection([
        ('insurance', 'Aseguradora'),
        ('copay', 'Copago'),
        ('regular', 'Regular')
    ], string='Tipo de Factura', default='regular')
    patient_id = fields.Many2one('hms.patient', string='Paciente')
    physician_id = fields.Many2one('hms.physician', string='Médico')
    treatment_id = fields.Many2one('hms.treatment', string='Tratamiento')
    department_id = fields.Many2one('hr.department', string='Departamento')
    diagnosis_id = fields.Many2one('hms.diseases', string='Diagnóstico')
    disease_status = fields.Selection([
        ('acute', 'Acute'),
        ('chronic', 'Chronic'),
        ('unchanged', 'Unchanged'),
        ('healed', 'Healed'),
        ('improving', 'Improving'),
        ('worsening', 'Worsening'),
    ], string='Estado de la Enfermedad')
    
    disease_severity = fields.Selection([
        ('mild', 'Mild'),
        ('moderate', 'Moderate'),
        ('severe', 'Severe'),
    ], string='Severidad')

    contract_id = fields.Many2one('customer.contract', string='Contrato', domain="[('partner_id', '=', partner_id)]",)
    authorization_number = fields.Char(string='Número de Autorización')
    benefit_plan_ids = fields.Many2many(
        'benefit.plan',
        string="Planes de Beneficios"
    )
    payment_method = fields.Selection([
        ('01', 'Paquete/Canasta/Conjunto Integral en Salud'),
        ('02', 'Grupos Relacionados por Diagnóstico'),
        ('03', 'Integral por grupo de riesgo'),
        ('04', 'Pago por contacto de especialidad'),
        ('05', 'Pago por escenario de atención'),
        ('06', 'Pago por tipo de servicio'),
        ('07', 'Pago global prospectivo por episodio'),
        ('08', 'Pago global prospectivo por grupo de riesgo'),
        ('09', 'Pago global prospectivo por especialidad'),
        ('10', 'Pago global prospectivo por nivel de complejidad'),
        ('11', 'Capacitación'),
        ('12', 'Por servicio')
    ], string='Método de Pago', 
       help='Seleccione el método de pago para el contrato de salud')

    # Campos de relación entre facturas
    copay_invoice_id = fields.Many2one('account.move', string='Factura de Copago')
    insurance_invoice_id = fields.Many2one('account.move', string='Factura de Aseguradora')
    finding = fields.Text(string='Hallazgos')
    is_insurance_invoice = fields.Boolean(compute='_compute_invoice_types', store=True)
    is_copay_invoice = fields.Boolean(compute='_compute_invoice_types', store=True)
    rips_generated = fields.Boolean(
        string='RIPS Generado',
        default=False
    )

    def _auto_init(self):
        """
        Crear columnas manualmente para campos computados con store=True
        antes de llamar a super() para evitar MemoryError en bases de datos grandes.
        """
        from odoo.tools.sql import index_exists, column_exists, create_column
        import logging
        _logger = logging.getLogger(__name__)

        # Crear columnas Boolean ANTES de super()._auto_init()
        if not column_exists(self.env.cr, 'account_move', 'is_insurance_invoice'):
            create_column(self.env.cr, 'account_move', 'is_insurance_invoice', 'bool')
            _logger.info('Created column is_insurance_invoice in account_move')

        if not column_exists(self.env.cr, 'account_move', 'is_copay_invoice'):
            create_column(self.env.cr, 'account_move', 'is_copay_invoice', 'bool')
            _logger.info('Created column is_copay_invoice in account_move')

        """Crear índices parciales para campos booleanos computados - optimización para búsquedas"""
        super()._auto_init()

        # Índice parcial para facturas de aseguradora (solo TRUE)
        if not index_exists(self.env.cr, 'account_move_is_insurance_idx'):
            self.env.cr.execute("""
                CREATE INDEX account_move_is_insurance_idx
                          ON account_move(partner_id, state)
                       WHERE is_insurance_invoice = true
            """)

        # Índice parcial para facturas de copago (solo TRUE)
        if not index_exists(self.env.cr, 'account_move_is_copay_idx'):
            self.env.cr.execute("""
                CREATE INDEX account_move_is_copay_idx
                          ON account_move(partner_id, state)
                       WHERE is_copay_invoice = true
            """)

        # Índice parcial para RIPS generados (solo TRUE)
        if not index_exists(self.env.cr, 'account_move_rips_generated_idx'):
            self.env.cr.execute("""
                CREATE INDEX account_move_rips_generated_idx
                          ON account_move(create_date DESC)
                       WHERE rips_generated = true
            """)
    rips_json = fields.Text(
        string='JSON RIPS',
        readonly=True
    )
    rips_json_binary = fields.Binary(
        string='Archivo RIPS JSON',
        attachment=True,
        help="Archivo RIPS en formato JSON"
    )
    rips_json_filename = fields.Char(
        string='Nombre del archivo RIPS',
        help="Nombre del archivo RIPS generado"
    )
    @api.depends('invoice_type')
    def _compute_invoice_types(self):
        for record in self:
            record.is_insurance_invoice = record.invoice_type == 'insurance'
            record.is_copay_invoice = record.invoice_type == 'copay'

    @api.onchange('contract_id')
    def _onchange_contract(self):
        if self.contract_id:
            self.benefit_plan_ids = [(6, 0, self.contract_id.benefit_plan_ids.ids)]
            self.payment_method = self.contract_id.payment_method
    def _round1(self, amount: Decimal | float) -> Decimal:
        """Redondea al entero más cercano usando *Decimal* sin decimales."""
        from decimal import Decimal, ROUND_HALF_UP
        if not isinstance(amount, Decimal):
            amount = Decimal(str(amount))
        return amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    def validate_rips(self):
        """
        Valida la estructura y datos del RIPS generado
        :return: Mensaje de resultado
        """
        self.ensure_one()
        if not self.rips_json:
            raise ValidationError(_("No hay datos RIPS para validar. Primero debe generar el RIPS."))
        try:
            rips_data = json.loads(self.rips_json)
        except ValueError:
            raise ValidationError(_("Error al decodificar el JSON RIPS. Verifique el formato."))
        validator = self.env['rips.validator']
        success, message = validator.validate_rips_data(rips_data)
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
        
    def generate_rips_json(self) -> Dict[str, Any]:
        self.ensure_one()
        
        doc_type = self._get_document_type()
        
        rips_data_base = {
            "numDocumentoIdObligado": self._validate_string(self.company_id.partner_id.vat_co, 4, 12, no_leading_zero=True, no_spaces=True),
            "numFactura": self._validate_string(self.name, 1, 20, no_leading_zero=True, no_spaces=True),
            "tipoNota": None,
            "numNota": None,
            "usuarios": []
        }

        if doc_type in ['credit_note', 'debit_note']:
            original_invoice = self.reversed_entry_id or self.debit_origin_id
            if not original_invoice:
                raise UserError(_("The note must be related to an invoice to generate RIPS."))
            
            rips_data_base["numFactura"] = self._validate_string(original_invoice.name, 1, 20, no_leading_zero=True, no_spaces=True)
            rips_data_base["tipoNota"] = self._get_rips_note_type(doc_type)
            rips_data_base["numNota"] = self._validate_string(self.name, 1, 20, no_leading_zero=True, no_spaces=True)
        
        rips_data = rips_data_base.copy()

        pacientes_lines_direct = {}
        for line in self.invoice_line_ids:
            if not line.patient_doc_type or not line.patient_document:
                if line.product_id and line.product_id.rips_service_type and line.product_id.rips_service_type != 'none':
                    raise UserError(_("The invoice line for product '%s' requires patient information (document type and number) for RIPS.") % line.product_id.name)
                continue

            patient_key_direct = (line.patient_doc_type, line.patient_document)
            
            if patient_key_direct not in pacientes_lines_direct:
                pacientes_lines_direct[patient_key_direct] = []
            pacientes_lines_direct[patient_key_direct].append(line)

        is_any_line_a_rips_service = any(
            line.product_id and line.product_id.rips_service_type and line.product_id.rips_service_type != 'none'
            for line in self.invoice_line_ids
        )

        if not pacientes_lines_direct:
             if is_any_line_a_rips_service:
                raise UserError(_("No patient data found on invoice lines to generate RIPS, but RIPS services are present."))
             else:
                self.rips_json = json.dumps(rips_data, default=self._json_serial, indent=2)
                self.rips_json_binary = base64.b64encode(self.rips_json.encode('utf-8'))
                self.rips_json_filename = f"{self.name.replace('/', '_')}_EMPTY_RIPS.json"
                self.rips_generated = True
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('RIPS Generated (Empty)'),
                        'message': _('RIPS JSON generated but contains no patient services.'),
                        'sticky': False,
                        'type': 'info',
                    }
                }


        consecutivo_usuario = 1
        for patient_key, service_lines_for_patient in pacientes_lines_direct.items():
            demographic_data_line = service_lines_for_patient[0] 
            
            usuario_data = self._prepare_usuario_data(demographic_data_line, service_lines_for_patient, consecutivo_usuario)
            if usuario_data:
                rips_data["usuarios"].append(usuario_data)
                consecutivo_usuario += 1
            else:
                raise UserError(_("Could not generate RIPS information for patient with document %s %s (data taken from invoice line). Please check patient fields on lines.") % 
                                (demographic_data_line.patient_doc_type, demographic_data_line.patient_document))

        if not rips_data["usuarios"] and is_any_line_a_rips_service:
            raise UserError(_("Could not generate user information for RIPS, although RIPS service lines were found."))

        json_str = json.dumps(rips_data, default=self._json_serial, indent=2)
        self.rips_json = json_str
        filename = f"{self.name.replace('/', '_')}_RIPS.json"
        self.rips_json_binary = base64.b64encode(json_str.encode('utf-8'))
        self.rips_json_filename = filename
        self.rips_generated = True
        
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content?model={self._name}&id={self.id}&field=rips_json_binary&filename={filename}&download=true',
            'target': 'self',
        }

    def _prepare_usuario_data(self, demographic_line: Any, service_lines: list, consecutivo: int) -> Optional[Dict[str, Any]]:
        if not demographic_line.patient_doc_type or not demographic_line.patient_document:
            return None 
        
        zona_territorial_code = "01"
        if demographic_line.patient_zone == 'rural':
            zona_territorial_code = "02"
        elif demographic_line.patient_zone == 'urbano':
             zona_territorial_code = "01"

        country_code_val = demographic_line.patient_country_id.numeric_code if demographic_line.patient_country_id else "170"
        municipality_code_val = demographic_line.patient_city_id.code if demographic_line.patient_city_id else "08001"
        nationality_code_val = demographic_line.patient_nationality if demographic_line.patient_nationality else country_code_val

        usuario = {
            "tipoDocumentoIdentificacion": self._validate_string(demographic_line.patient_doc_type, 2, 2),
            "numDocumentoIdentificacion": self._validate_string(demographic_line.patient_document, 4, 20, no_leading_zero=True, no_spaces=True),
            "tipoUsuario": self._validate_string(demographic_line.patient_user_type, 2, 2, default="01"),
            "fechaNacimiento": self._validate_date(demographic_line.patient_birth_date, '%Y-%m-%d', default="1900-01-01"),
            "codSexo": demographic_line.patient_gender,
            "codPaisResidencia": self._validate_string(country_code_val, 1, 3, default="170"),
            "codMunicipioResidencia": self._validate_string(municipality_code_val, 5, 5, default="08001"),
            "codZonaTerritorialResidencia": self._validate_string(zona_territorial_code, 2, 2, default="01"),
            "incapacidad": "NO",
            "consecutivo": self._validate_numeric(consecutivo, 1, 7),
            "codPaisOrigen": self._validate_string(nationality_code_val, 1, 3, default=country_code_val),
            "servicios": {}
        }
        
        servicios_data = {
            'consultas': [], 'procedimientos': [], 'medicamentos': [], 'otrosServicios': []
        }
        
        consecutivos_servicios = {'consulta': 1, 'procedimiento': 1, 'medicamento': 1, 'otro_servicio': 1}

        for line in service_lines:
            if not line.product_id or not line.product_id.rips_service_type or line.product_id.rips_service_type == 'none':
                continue
                
            service_type = line.product_id.rips_service_type
            servicio_dict = None
            current_consecutivo = consecutivos_servicios[service_type]

            if service_type == 'consulta':
                servicio_dict = self._prepare_consulta_data(line, current_consecutivo)
                if servicio_dict: servicios_data['consultas'].append(servicio_dict)
            elif service_type == 'procedimiento':
                servicio_dict = self._prepare_procedimiento_data(line, current_consecutivo)
                if servicio_dict: servicios_data['procedimientos'].append(servicio_dict)
            elif service_type == 'medicamento':
                servicio_dict = self._prepare_medicamento_data(line, current_consecutivo)
                if servicio_dict: servicios_data['medicamentos'].append(servicio_dict)
            elif service_type == 'otro_servicio':
                servicio_dict = self._prepare_otro_servicio_data(line, current_consecutivo)
                if servicio_dict: servicios_data['otrosServicios'].append(servicio_dict)
            else:
                _logger.warning(_("Unsupported RIPS service type: %s for product %s") % (service_type, line.product_id.name))
                continue

            if servicio_dict:
                consecutivos_servicios[service_type] += 1
        
        for tipo_servicio_key, datos_servicios in servicios_data.items():
            if datos_servicios:
                usuario["servicios"][tipo_servicio_key] = datos_servicios
        
        if not any(servicios_data.values()):
             _logger.info(_("Patient with document %s %s has no valid RIPS services in this invoice.") % (demographic_line.patient_doc_type, demographic_line.patient_document))
             return None

        return usuario

    def _prepare_consulta_data(self, line, consecutivo) -> Dict[str, Any]: 
        cod_prestador = self._validate_string(self.company_id.partner_id.ref, 12, 12, no_spaces=True, default='000000000000')
        fecha_atencion = line.fecha_atencion or (line.treatment_id and line.treatment_id.start_date) or self.date or fields.Datetime.now()
        num_autorizacion = self._validate_string(line.autorizacion, 1, 30, no_leading_zero=True, no_spaces=True, allow_null=True)
        cod_consulta = self._validate_string(self._validate_product_code(line.product_id, 'consulta'), 6, 6, no_leading_zero=True, no_spaces=True, default="100000")
        modalidad = self._validate_string(line.modalidad, 2, 2, default="01")
        grupo_servicio = self._validate_string(line.grupo_servicio, 2, 2, default="01")
        finalidad = self._validate_string(line.finalidad, 2, 2, default="10")
        
        cod_servicio = 101
        if hasattr(line, 'cod_servicio') and line.cod_servicio:
            try: cod_servicio = int(line.cod_servicio)
            except (ValueError, TypeError): pass
        
        cod_diagnostico_principal = self._validate_string(line.diagnostico_principal, 4, 25, no_leading_zero=True, no_spaces=True, default="A000")
        tipo_doc_profesional, num_doc_profesional = "CC", "1111111111"
        if hasattr(line, 'professional_id') and line.professional_id:
            if line.professional_id.l10n_latam_identification_type_id:
                tipo_doc_profesional = line.professional_id.l10n_latam_identification_type_id.heath_code or "CC"
            if line.professional_id.vat:
                num_doc_profesional = line.professional_id.vat
        num_doc_profesional = self._validate_string(num_doc_profesional, 4, 20, no_leading_zero=True, no_spaces=True)
        
        valor_servicio = self._validate_numeric(line.price_subtotal if line.price_subtotal > 0 else 0, 1, 10)
        valor_moderador = self._validate_numeric(line.valor_pago_moderador if line.valor_pago_moderador > 0 else 0, 1, 10)
        num_fev_pago_moderador = self._validate_string(line.num_fev_pago_moderador, max_length=14, allow_null=True)
            
        return {
            "codPrestador": cod_prestador,
            "fechaInicioAtencion": self._validate_date(fecha_atencion, '%Y-%m-%d %H:%M'),
            "numAutorizacion": num_autorizacion, "codConsulta": cod_consulta,
            "modalidadGrupoServicioTecSal": modalidad, "grupoServicios": grupo_servicio,
            "codServicio": cod_servicio, "finalidadTecnologiaSalud": finalidad,
            "causaMotivoAtencion": self._validate_string(line.causa_externa, 2, 2, default="13"),
            "codDiagnosticoPrincipal": cod_diagnostico_principal,
            "tipoDiagnosticoPrincipal": self._validate_string(line.tipo_diagnostico, 2, 2, default="01"),
            "tipoDocumentoIdentificacion": tipo_doc_profesional,
            "numDocumentoIdentificacion": num_doc_profesional, "vrServicio": valor_servicio,
            "conceptoRecaudo": self._validate_string(line.tipo_pago_moderador, 2, 2, default="05"),
            "valorPagoModerador": valor_moderador, "numFEVPagoModerador": num_fev_pago_moderador,
            "consecutivo": self._validate_numeric(consecutivo, 1, 7)
        }

    def _prepare_procedimiento_data(self, line, consecutivo) -> Dict[str, Any]:
        cod_prestador = self._validate_string(self.company_id.partner_id.ref, 12, 12, no_spaces=True, default='000000000000')
        fecha_atencion = line.fecha_procedimiento or (line.treatment_id and line.treatment_id.start_date) or self.date or fields.Datetime.now()
        num_autorizacion = self._validate_string(line.autorizacion, 1, 30, no_leading_zero=True, no_spaces=True, allow_null=True)
        cod_procedimiento = self._validate_string(self._validate_product_code(line.product_id, 'procedimiento'), 6, 6, no_spaces=True, default="000000")
        via_ingreso = self._validate_string(line.product_id.rips_via_ingreso, 2, 2, default="01")
        modalidad = self._validate_string(line.product_id.rips_modalidad, 2, 2, default="01")
        grupo_servicio = self._validate_string(line.product_id.rips_grupo_servicio, 2, 2, default="02")
        finalidad = self._validate_string(line.product_id.rips_finalidad, 2, 2, default="44")
        
        cod_servicio = 706
        if  line.product_id.rips_cod_servicio:
            cod_servicio = int(line.product_id.rips_cod_servicio)

        tipo_doc_profesional, num_doc_profesional = "CC", "1111111111"
        if hasattr(line, 'professional_id') and line.professional_id:
            if line.professional_id.l10n_latam_identification_type_id:
                tipo_doc_profesional = line.professional_id.l10n_latam_identification_type_id.heath_code or "CC"
            if line.professional_id.vat:
                num_doc_profesional = line.professional_id.vat
        num_doc_profesional = self._validate_string(num_doc_profesional, 4, 20, no_leading_zero=True, no_spaces=True)
        cod_diagnostico_principal = self._validate_string(line.diagnostico_principal, 4, 25, no_leading_zero=True, no_spaces=True, default="A000")
        cod_diagnostico_relacionado = self._validate_string(line.diagnostico_relacionado, 4, 25, no_leading_zero=True, no_spaces=True, allow_null=True)
        cod_complicacion = self._validate_string(line.complicacion, 4, 25, no_leading_zero=True, no_spaces=True, allow_null=True, default=None)
        valor_servicio = self._validate_numeric(line.price_subtotal if line.price_subtotal > 0 else 0, 1, 15)
        valor_moderador = self._validate_numeric(line.valor_pago_moderador if line.valor_pago_moderador > 0 else 0, 1, 10)
        num_fev_pago_moderador = line.num_fev_pago_moderador
        id_mipres_val = self._validate_string(line.id_mipres, 1, 15, no_leading_zero=True, no_spaces=True, allow_null=True)

        return {
            "codPrestador": cod_prestador,
            "fechaInicioAtencion": self._validate_date(fecha_atencion, '%Y-%m-%d %H:%M'),
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
            "codComplicacion": cod_complicacion, 
            "vrServicio": valor_servicio,
            "conceptoRecaudo": self._validate_string(self.health_collection_concept_id.code, 2, 2, default="05"),
            "valorPagoModerador": valor_moderador,
            "numFEVPagoModerador": num_fev_pago_moderador or None,
            "consecutivo": self._validate_numeric(consecutivo, 1, 7)
        }

    def _prepare_medicamento_data(self, line, consecutivo) -> Dict[str, Any]:
        cod_prestador = self._validate_string(self.company_id.partner_id.ref, 12, 12, no_spaces=True, default='000000000000')
        fecha_dispensacion = line.fecha_dispensacion or self.date or fields.Date.today()
        num_autorizacion = self._validate_string(line.autorizacion, 1, 30, no_leading_zero=True, no_spaces=True, allow_null=True)
        id_mipres_val = self._validate_string(line.id_mipres, 1, 15, no_leading_zero=True, no_spaces=True, allow_null=True)
        cod_diagnostico_principal = self._validate_string(line.diagnostico_principal, 4, 25, no_leading_zero=True, no_spaces=True, default="A000")
        cod_diagnostico_relacionado = self._validate_string(line.diagnostico_relacionado1, 4, 25, no_leading_zero=True, no_spaces=True, allow_null=True)
        tipo_medicamento = self._validate_string(line.tipo_medicamento, 2, 2, default="01")
        cod_tecnologia_salud = self._validate_string(self._validate_product_code(line.product_id, 'medicamento'), 1, 20, default="")
        nom_tecnologia_salud = self._validate_string(line.product_id.name if line.product_id else "", 1, 30, no_leading_zero=True, default="")
        
        concentracion_val, unidad_medida_val, forma_farmaceutica_val = 0, 0, None
        if tipo_medicamento == '03': # Preparación Magistral
            concentracion_val = self._validate_numeric(line.concentracion, 1, 3, default=0)
            unidad_medida_val = self._validate_numeric(line.unidad_medida, 1, None, default=0) # RIPS no define max_length claro
            forma_farmaceutica_val = self._validate_string(line.forma_farmaceutica, max_length=20, allow_null=True) # MaxLength asumido
        
        cantidad = self._validate_numeric(line.quantity if line.quantity > 0 else 1, 1, 10)
        dias_tratamiento = self._validate_numeric(line.dias_tratamiento if line.dias_tratamiento > 0 else 1, 1, 3)
        unidad_min_dispensacion = self._validate_numeric(line.unidad_min_dispensacion if line.unidad_min_dispensacion > 0 else 1, 1, None) # RIPS no define max_length

        tipo_doc_profesional, num_doc_profesional = "CC", "1111111111"
        if hasattr(line, 'professional_id') and line.professional_id: # Asumiendo professional_id en line, no en treatment
            if line.professional_id.l10n_latam_identification_type_id:
                tipo_doc_profesional = line.professional_id.l10n_latam_identification_type_id.heath_code or "CC"
            if line.professional_id.vat:
                num_doc_profesional = line.professional_id.vat
        num_doc_profesional = self._validate_string(num_doc_profesional, 4, 20, no_leading_zero=True, no_spaces=True)
        
        valor_unitario = self._validate_numeric(line.price_unit if line.price_unit > 0 else 0, 1, 15)
        valor_servicio = self._validate_numeric(line.price_subtotal if line.price_subtotal > 0 else 0, 1, 15)
        valor_moderador = self._validate_numeric(line.valor_pago_moderador if line.valor_pago_moderador > 0 else 0, 1, 10)
        num_fev_pago_moderador = self._validate_string(line.num_fev_pago_moderador, max_length=14, allow_null=True)

        return {
            "codPrestador": cod_prestador, 
            "numAutorizacion": num_autorizacion, 
            "idMIPRES": id_mipres_val,
            "fechaDispensAdmon": self._validate_date(fecha_dispensacion, '%Y-%m-%d %H:%M'), # RIPS usa %Y-%m-%d, pero el ejemplo original tenía %H:%M
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
            "conceptoRecaudo": self._validate_string(self.health_collection_concept_id, 2, 2, default="05"),
            "valorPagoModerador": valor_moderador,
            "numFEVPagoModerador": num_fev_pago_moderador,
            "consecutivo": self._validate_numeric(consecutivo, 1, 7)
        }

    def _prepare_otro_servicio_data(self, line, consecutivo) -> Dict[str, Any]:
        cod_prestador = self._validate_string(self.company_id.partner_id.ref, 12, 12, no_spaces=True, default='000000000000')
        fecha_suministro = line.fecha_suministro or (line.treatment_id and line.treatment_id.start_date) or self.date_start or fields.Date.today()
        num_autorizacion = self._validate_string(line.autorizacion, 1, 30, no_leading_zero=True, no_spaces=True, allow_null=True)
        id_mipres_val = self._validate_string(line.id_mipres, 1, 15, no_leading_zero=True, no_spaces=True, allow_null=True)
        tipo_os = self._validate_string(line.tipo_servicio, 2, 2, default="01") # Asumiendo que line.tipo_servicio es el código RIPS.
        cod_tecnologia_salud = self._validate_string(self._validate_product_code(line.product_id, 'otro_servicio'), 1, 20, no_leading_zero=True, no_spaces=True)
        nom_tecnologia_salud = self._validate_string(line.product_id.name if line.product_id else "", 1, 60, no_leading_zero=True)
        cantidad = self._validate_numeric(line.quantity if line.quantity > 0 else 1, 1, 5)
        valor_unitario = self._validate_numeric(line.price_unit if line.price_unit > 0 else 0, 1, 15)
        valor_servicio = self._validate_numeric(line.price_subtotal if line.price_subtotal > 0 else 0, 1, 15)
        tipo_doc_profesional, num_doc_profesional = "CC", "1111111111" # Para "Otros Servicios" RIPS no especifica profesional, pero por consistencia...
        valor_moderador = self._validate_numeric(line.valor_pago_moderador if line.valor_pago_moderador > 0 else 0, 1, 10)
        num_fev_pago_moderador = self._validate_string(line.num_fev_pago_moderador, max_length=14, allow_null=True)

        return {
            "codPrestador": cod_prestador, "numAutorizacion": num_autorizacion, "idMIPRES": id_mipres_val,
            "fechaSuministroTecnologia": self._validate_date(fecha_suministro, '%Y-%m-%d %H:%M'), # RIPS usa %Y-%m-%d
            "tipoOS": tipo_os, "codTecnologiaSalud": cod_tecnologia_salud,
            "nomTecnologiaSalud": nom_tecnologia_salud, "cantidadOS": cantidad,
            "vrUnitOS": valor_unitario, "vrServicio": valor_servicio,
            "tipoDocumentoIdentificacion": tipo_doc_profesional, # RIPS no lo pide para OS
            "numDocumentoIdentificacion": num_doc_profesional, # RIPS no lo pide para OS
            "conceptoRecaudo": self._validate_string(line.tipo_pago_moderador, 2, 2, default="05"),
            "valorPagoModerador": valor_moderador, "numFEVPagoModerador": num_fev_pago_moderador,
            "consecutivo": self._validate_numeric(consecutivo, 1, 7)
        }
    
    def _validate_string(self, value: Any, min_length: Optional[int] = None, 
                        max_length: Optional[int] = None, no_leading_zero: Optional[bool] = False,
                        no_spaces: Optional[bool] = False, default: Optional[Any] = None, 
                        allow_null: Optional[bool] = False):
        
        # Si el valor es "false" (None, False, "", 0, [], {}, etc.)
        if not value or value == 0:
            return None if allow_null else (default if default is not None else ("" if max_length else None))
        
        # Manejar cadenas 'null' específicamente
        if isinstance(value, str) and value.strip().lower() == 'null':
            return None if allow_null else (default if default is not None else ("" if max_length else None))
        
        # Convertir a string y continuar con el procesamiento normal
        value_str = str(value).strip()
        
        # Verificar si quedó vacío después de strip()
        if not value_str:
            return None if allow_null else (default if default is not None else ("" if max_length else None))
        
        # Eliminar espacios si es necesario
        if no_spaces:
            value_str = value_str.replace(' ', '')
        
        # Eliminar ceros a la izquierda si es necesario
        if no_leading_zero and value_str.startswith('0') and len(value_str) > 1 and value_str.isnumeric():
            non_zero_index = 0
            while non_zero_index < len(value_str) - 1 and value_str[non_zero_index] == '0':
                non_zero_index += 1
            value_str = value_str[non_zero_index:]
        
        # Ajustar longitud máxima
        if max_length and len(value_str) > max_length:
            value_str = value_str[:max_length]
        
        # Ajustar longitud mínima
        if min_length and len(value_str) < min_length:
            if value_str.isnumeric():
                value_str = value_str.zfill(min_length)
            else:
                value_str = value_str.ljust(min_length, ' ')
        
        return value_str
    
    def _validate_numeric(self, value, min_length=None, max_length=None, default=0):
        if value is None: return default
        try:
            value_float = float(value)
            value_int = int(value_float)
            if value_int < 0: value_int = 0 
            value_str = str(value_int)
            if max_length and len(value_str) > max_length:
                value_str = '9' * max_length 
                value_int = int(value_str)
            if min_length and len(value_str) < min_length:
                value_str = value_str.zfill(min_length)
                value_int = int(value_str) # Re-int after zfill if min_length > 1
            return value_int
        except (ValueError, TypeError): return default
    
    def _validate_date(self, value, format_str='%Y-%m-%d', default=None):
        """
        Valida y formatea una fecha
        
        Args:
            value: Valor a validar (str, datetime, date, fields.Date, fields.Datetime)
            format_str: Formato de salida deseado
            default: Valor por defecto si la validación falla
        
        Returns:
            Fecha formateada como string o valor por defecto
        """
        if not value:
            return default
        
        try:
            date_value = None
            
            if isinstance(value, str):
                value = value.strip()
                if not value:
                    return default
                    
                formats_to_try = [
                    '%Y-%m-%d %H:%M:%S',
                    '%Y-%m-%d',
                    '%d/%m/%Y',
                    '%m/%d/%Y',
                    format_str  
                ]
                
                for fmt in formats_to_try:
                    try:
                        date_value = datetime.strptime(value, fmt)
                        break
                    except ValueError:
                        continue
                
                if date_value is None:
                    return default
            
            elif isinstance(value, datetime):
                date_value = value
            
            elif isinstance(value, date):
                date_value = datetime.combine(value, datetime.min.time())
            
            elif hasattr(value, 'strftime'):
                date_value = value
            
            elif hasattr(value, 'date') and callable(getattr(value, 'date')):
                date_value = value.date()
                date_value = datetime.combine(date_value, datetime.min.time())
            
            else:
                return default
            
            if date_value and hasattr(date_value, 'strftime'):
                if ' ' not in format_str and hasattr(date_value, 'date'):
                    return date_value.strftime(format_str)
                return date_value.strftime(format_str)
            
            return default
            
        except Exception as e:
            return default

    def _get_document_type(self):
        if self.move_type == 'out_invoice': return 'invoice'
        elif self.move_type == 'out_refund': return 'credit_note'
        elif self.move_type == 'in_refund' or (hasattr(self, 'is_debit_note') and self.is_debit_note): # Odoo 15+ uses is_debit_note
             return 'debit_note'
        return 'invoice' # Default
            
    def _get_rips_note_type(self, doc_type):
        if doc_type == 'credit_note': return "NC"
        elif doc_type == 'debit_note': return "ND"
        return None 
        
    def _json_serial(self, obj):
        if isinstance(obj, (datetime, fields.Date, fields.Datetime)):
            return obj.isoformat() # Using isoformat is standard
        raise TypeError(f"Type {type(obj)} not serializable for RIPS")
    
    def _conver_gender(self, gender:str) -> str:
        if gender == 'H' or gender == 'male': return 'M'
        elif gender == 'M' or gender == 'female': return 'F' 
        elif gender == 'I' or gender == 'other': return 'I' 
        return 'I' # Default for unknown or RIPS 'Indeterminado'

    def _validate_product_code(self, product, service_type):
        if not product:
            return {"consulta": "100000", "procedimiento": "000000"}.get(service_type, "")
        
        code_to_use = product.default_code # Fallback
        if service_type in ['consulta', 'procedimiento'] and product.code_type:
            if product.code_type == 'cups' and product.cups_id and product.cups_id.code:
                code_to_use = product.cups_id.code
            elif product.code_type == 'custom' and product.custom_code:
                code_to_use = product.custom_code
        elif service_type == 'medicamento' and product.is_cums:
            cums_parts = []
            if product.atc: cums_parts.append(product.atc)
            if product.expedient: cums_parts.append(product.expedient)
            if product.consecutive: cums_parts.append(product.consecutive)
            if cums_parts: code_to_use = "".join(cums_parts[:2]) + "-" + cums_parts[2] if len(cums_parts) == 3 else "".join(cums_parts)
        
        default_for_type = {"consulta": "100000", "procedimiento": "000000"}.get(service_type, "")
        min_len, max_len = (6,6) if service_type in ['consulta', 'procedimiento'] else (1,20)
        no_lead_zero = service_type == 'consulta'
        no_space = service_type in ['consulta', 'procedimiento']

        return self._validate_string(code_to_use, min_len, max_len, no_leading_zero=no_lead_zero, no_spaces=no_space, default=default_for_type)



class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'
    
    patient_id = fields.Many2one('hms.patient', string='Paciente')
    treatment_id = fields.Many2one('hms.treatment', string='Tratamiento')
    date_start = fields.Date(string='Fecha Inicio')
    date_end = fields.Date(string='Fecha Fin')
    autorizacion = fields.Char(string='Número de Autorización')
    id_mipres = fields.Char(string='ID MIPRES')
    
    # === CAMPOS DE DATOS DEL PACIENTE CITI SALUD===
    patient_document = fields.Char(string='Documento Paciente', help='ID/Cédula del paciente en la línea')
    patient_name = fields.Char(string='Nombre Paciente', help='Nombre completo del paciente')
    patient_city_id = fields.Many2one('res.city', string='Ciudad Paciente', help='Ciudad de residencia del paciente')
    patient_nationality = fields.Char(string='Nacionalidad Paciente', help='Nacionalidad del paciente (código)')
    patient_country_id = fields.Many2one('res.country', string='País Paciente', help='País de residencia del paciente')
    
    patient_user_type = fields.Selection([
        ('01', 'Contributivo cotizante'),
        ('02', 'Contributivo beneficiario'),
        ('03', 'Contributivo adicional'),
        ('04', 'Subsidiado'),
        ('05', 'Sin régimen'),
        ('06', 'Especiales o de Excepción cotizante'),
        ('07', 'Especiales o de Excepción beneficiario'),
        ('08', 'Particular'),
        ('09', 'Tomador/Amparado ARL'),
        ('10', 'Tomador/Amparado SOAT'),
        ('11', 'Tomador/Amparado Planes voluntarios de salud'),
    ], string='Tipo de Usuario', help='Tipo de usuario del sistema de salud colombiano')
    patient_gender = fields.Selection([
        ('M', 'Hombre'),
        ('F', 'Mujer'),
        ('I', 'Indeterminado o Intersexual')
    ], string='Género Paciente', help='Género del paciente según normativa CITI SALUD')
    patient_zone = fields.Selection([
        ('urbano', 'Urbano'),
        ('rural', 'Rural')
    ], string='Zona Paciente', help='Zona de residencia del paciente')
    
    patient_birth_date = fields.Date(string='Fecha Nacimiento Paciente', help='Fecha de nacimiento del paciente')
    
    patient_doc_type = fields.Selection([
        ('CC', 'Cédula de Ciudadanía'),
        ('TI', 'Tarjeta de Identidad'),
        ('CE', 'Cédula de Extranjería'),
        ('PP', 'Pasaporte'),
        ('RC', 'Registro Civil'),
        ('MS', 'Menor sin identificación'),
        ('AS', 'Adulto sin identificación'),
        ('NU', 'Número único de identificación'),
        ('PE', 'Permiso especial de permanencia'),
        ('SC', 'Salvoconducto de permanencia'),
        ('PT', 'Permiso por protección temporal')
    ], string='Tipo Documento Paciente', help='Tipo de documento de identificación del paciente')
    # === CAMPOS DE DATOS DEL PACIENTE CITI SALUD===
    fecha_atencion = fields.Datetime(string='Fecha de Atención')
    fecha_procedimiento = fields.Datetime(string='Fecha de Procedimiento')
    fecha_dispensacion = fields.Datetime(string='Fecha de Dispensación')
    fecha_suministro = fields.Datetime(string='Fecha de Suministro')
    
    # Campos comunes a todos los servicios
    tipo_pago_moderador = fields.Selection([
        ('01', 'Cuota moderadora'),
        ('02', 'Copago'),
        ('03', 'Cuota de recuperación'),
        ('04', 'No aplica')
    ], string='Tipo de Pago Moderador', default='04')
    valor_pago_moderador = fields.Float(string='Valor Pago Moderador', default=0.0)
    num_fev_pago_moderador = fields.Char(string='Número FEV Pago Moderador')
    
    # Campos para consultas
    modalidad = fields.Char(string='Modalidad de Atención')
    grupo_servicio = fields.Char(string='Grupo de Servicio')
    cod_servicio = fields.Integer(string='Código de Servicio')
    finalidad = fields.Char(string='Finalidad')
    causa_externa = fields.Char(string='Causa Externa')
    diagnostico_principal = fields.Char(string='Diagnóstico Principal')
    diagnostico_relacionado1 = fields.Char(string='Diagnóstico Relacionado 1')
    diagnostico_relacionado2 = fields.Char(string='Diagnóstico Relacionado 2')
    diagnostico_relacionado3 = fields.Char(string='Diagnóstico Relacionado 3')
    tipo_diagnostico = fields.Selection([
        ('01', 'Impresión diagnóstica'),
        ('02', 'Confirmado nuevo'),
        ('03', 'Confirmado repetido')
    ], string='Tipo de Diagnóstico', default='01')
    
    # Campos para procedimientos
    via_ingreso = fields.Selection([
        ('01', 'Por consulta'),
        ('02', 'Por urgencias'),
        ('03', 'Por hospitalización'),
        ('04', 'Por remisión')
    ], string='Vía de Ingreso', default='01')
    diagnostico_relacionado = fields.Char(string='Diagnóstico Relacionado')
    complicacion = fields.Char(string='Código Complicación')
    
    # Campos para medicamentos
    tipo_medicamento = fields.Selection([
        ('01', 'Medicamento PBS'),
        ('02', 'Medicamento No PBS'),
        ('03', 'Preparación Magistral')
    ], string='Tipo de Medicamento', default='01')
    concentracion = fields.Float(string='Concentración')
    unidad_medida = fields.Integer(string='Unidad de Medida')
    forma_farmaceutica = fields.Char(string='Forma Farmacéutica')
    unidad_min_dispensacion = fields.Integer(string='Unidad Min. Dispensación', default=1)
    dias_tratamiento = fields.Integer(string='Días de Tratamiento', default=1)
    
    # Campos para otros servicios
    tipo_servicio = fields.Selection([
        ('01', 'Insumo o servicio complementario'),
        ('02', 'Transporte'),
        ('03', 'Estancia hospitalaria'),
        ('04', 'Servicios administrativos')
    ], string='Tipo de Otro Servicio', default='01')
    
    @api.onchange('treatment_id')
    def _onchange_treatment_id(self):
        if self.treatment_id:
            self.patient_id = self.treatment_id.patient_id
            # Actualizar descripción del producto
            name_parts = []
            if self.name:
                name_parts.append(self.name)
            name_parts.extend([
                f'Tratamiento: {self.treatment_id.name}',
                f'Paciente: {self.patient_id.name}'
            ])
            self.name = ' - '.join(name_parts)
    
    @api.onchange('patient_id')
    def _onchange_patient_id(self):
        """Actualizar campos del paciente cuando se selecciona un paciente"""
        if self.patient_id:
            patient = self.patient_id
            # Copiar información del paciente a los campos de línea
            self.patient_document = patient.vat or patient.ref
            self.patient_name = patient.name
            if hasattr(patient, 'city_id') and patient.city_id:
                self.patient_city_id = patient.city_id.id
            if hasattr(patient, 'country_id') and patient.country_id:
                self.patient_country_id = patient.country_id.id
            if hasattr(patient, 'date_of_birth') and patient.date_of_birth:
                self.patient_birth_date = patient.date_of_birth
            if hasattr(patient, 'l10n_latam_identification_type_id'):
                # Mapear el tipo de documento
                doc_type_mapping = {
                    '1': 'CC',  # Cédula de ciudadanía
                    '2': 'TI',  # Tarjeta de identidad
                    '3': 'CE',  # Cédula de extranjería
                    '4': 'PP',  # Pasaporte
                    '5': 'RC',  # Registro civil
                }
                if patient.l10n_latam_identification_type_id:
                    code = patient.l10n_latam_identification_type_id.code
                    self.patient_doc_type = doc_type_mapping.get(code, 'CC')

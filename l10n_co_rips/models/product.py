# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    @api.depends('acs_kit_line_ids','is_kit_product','acs_kit_line_ids.total_price')
    def acs_get_kit_amount_total(self):
        for rec in self:
            rec.kit_amount_total = sum(rec.acs_kit_line_ids.mapped('total_price'))
            rec.kit_cost_total = sum(rec.acs_kit_line_ids.mapped('total_standard_price'))

    is_kit_product = fields.Boolean("Kit Product", help="Adding this product will lead to component consumption when added in medical flow")
    acs_kit_line_ids = fields.One2many('acs.product.kit.line', 'product_template_id', string='Kit Components')
    kit_amount_total = fields.Float(compute='acs_get_kit_amount_total', string="Kit Total")
    kit_cost_total = fields.Float(compute='acs_get_kit_amount_total', string="Kit Cost Total")
    rips_service_type = fields.Selection([
        ('none', 'No es servicio RIPS'),
        ('consulta', 'Consulta'),
        ('procedimiento', 'Procedimiento'),
        ('medicamento', 'Medicamento'),
        ('urgencia', 'Urgencia'),
        ('hospitalizacion', 'Hospitalización'),
        ('recien_nacido', 'Recién Nacido'),
        ('otro_servicio', 'Otro Servicio')
        ], string='Tipo de Servicio RIPS', default='none',
        help="Clasifica el producto según el tipo de servicio para generación de RIPS")
    
    # CÓDIGOS DE IDENTIFICACIÓN
    rips_code = fields.Char(string='Código CUPS/CUMS/CUM', 
                           help='Código del servicio/medicamento según clasificación oficial')
    
    # CAMPOS PARA MEDICAMENTOS
    rips_tipo_medicamento = fields.Selection([
        ('01', 'Medicamento con registro sanitario'),
        ('02', 'Medicamento vital no disponible definido por INVIMA'),
        ('03', 'Preparación magistral'),
        ('04', 'Medicamento con uso no incluido en el registro sanitario (Listado UNIRS)'),
        ('05', 'Medicamento con autorización sanitaria de uso emergencia ASUE')
    ], string='Tipo de Medicamento')
    
    rips_unidad_medida = fields.Selection([
        ('1', 'EID50 dosis infecciosa de embrión 50'),
        ('10', 'Bq bequerel(ios)'),
        ('100', 'l litro(s)'),
        ('137', 'µg microgramo(s)'),
        ('142', 'µg/ml microgramo(s)/mililitro'),
        ('168', 'mg miligramo(s)'),
        ('173', 'mg/ml miligramo(s)/mililitro'),
        ('176', 'ml mililitro(s)'),
        ('179', 'mmol milimol(es)'),
        ('214', '% porcentaje'),
        ('247', 'U unidades'),
        ('249', 'U/ml unidades/mililitro'),
        ('62', 'g gramo(s)'),
        ('72', 'UI unidad(es) internacional(es)'),
        ('93', 'kg kilogramo(s)')
    ], string='Unidad de Medida')
    
    rips_forma_farmaceutica = fields.Selection([
        ('C28944', 'CREMA'),
        ('C29167', 'LOCION'),
        ('C29269', 'ENJUAGUE'),
        ('C42887', 'AEROSOL'),
        ('C42902', 'CAPSULA DE LIBERACION RETARDADA'),
        ('C42905', 'TABLETAS DE LIBERACION RETARDADA'),
        ('C42909', 'GRANULOS EFERVESCENTES'),
        ('C42912', 'ELIXIR'),
        ('C42914', 'EMULSION INYECTABLE'),
        ('C42916', 'CAPSULA DE LIBERACION PROLONGADA'),
        ('C42927', 'TABLETAS DE LIBERACION PROLONGADA'),
        ('C42942', 'IMPLANTE'),
        ('C42948', 'GELES y JALEAS'),
        ('C42966', 'UNGÜENTO'),
        ('C42983', 'JABONES Y CHAMPU'),
        ('C42989', 'ESPRAY'),
        ('C42993', 'SUPOSITORIO / OVULO'),
        ('C42994', 'SUSPENSION'),
        ('C42996', 'JARABE'),
        ('C64898', 'ESPUMA'),
        ('C64904', 'CAPSULA CUBIERTA DURA'),
        ('C64909', 'CAPSULA BLANDA'),
        ('COLFF001', 'TABLETAS DE LIBERACION NO MODIFICADA'),
        ('COLFF002', 'POLVOS PARA NO RECONSTITUIR'),
        ('COLFF003', 'POLVOS PARA RECONSTITUIR'),
        ('COLFF004', 'OTRAS SOLUCIONES'),
        ('COLFF005', 'OTRAS EMULSIONES'),
        ('COLFF006', 'CAPSULAS DE LIBERACION NO MODIFICADA'),
        ('COLFF007', 'CAPSULAS DE LIBERACION MODIFICADA'),
        ('COLFF008', 'TABLETAS DE LIBERACION MODIFICADA'),
        ('COLFF009', 'GRANULOS DE LIBERACION NO MODIFICADA'),
        ('COLFF010', 'GRANULOS DE LIBERACION MODIFICADA')
    ], string='Forma Farmacéutica')
    
    rips_unidad_dispensacion = fields.Selection([
        ('1', 'AMPOLLA'),
        ('10', 'ENVASE'),
        ('11', 'CAJA'),
        ('13', 'FRASCO'),
        ('14', 'CAPSULA'),
        ('15', 'CARTON'),
        ('17', 'ESTUCHE'),
        ('23', 'COPA'),
        ('3', 'BOLSA'),
        ('40', 'FRASCO'),
        ('56', 'CUCHARA MEDIDORA'),
        ('58', 'ATOMIZADOR (SPRAY)'),
        ('6', 'BLISTER'),
        ('65', 'JERINGA'),
        ('66', 'TABLETA'),
        ('73', 'TUBO'),
        ('74', 'UNIDADES'),
        ('75', 'VIAL'),
        ('78', 'SOBRE'),
        ('79', 'PLUMA'),
        ('81', 'OVULO')
    ], string='Unidad Mínima de Dispensación')
    
    # CAMPOS PARA OTROS SERVICIOS
    rips_tipo_os = fields.Selection([
        ('01', 'Dispositivos médicos e insumos'),
        ('02', 'Traslados'),
        ('03', 'Estancias'),
        ('04', 'Servicios complementarios'),
        ('05', 'Honorarios')
    ], string='Tipo de Otro Servicio')
    
    # CAMPOS PARA SERVICIOS (CONSULTAS, PROCEDIMIENTOS, ETC.)
    rips_modalidad = fields.Selection([
        ('01', 'Intramural'),
        ('02', 'Extramural unidad móvil'),
        ('03', 'Extramural domiciliaria'),
        ('04', 'Extramural jornada de salud'),
        ('06', 'Telemedicina interactiva'),
        ('07', 'Telemedicina no interactiva'),
        ('08', 'Telemedicina telexperticia'),
        ('09', 'Telemedicina telemonitoreo')
    ], string='Modalidad de Atención')
    
    rips_grupo_servicio = fields.Selection([
        ('01', 'Consulta externa'),
        ('02', 'Apoyo diagnóstico y complementación terapéutica'),
        ('03', 'Internación'),
        ('04', 'Quirúrgico'),
        ('05', 'Atención inmediata')
    ], string='Grupo de Servicios')
    
    rips_cod_servicio = fields.Selection([
        # Cuidados
        ('105', 'CUIDADO INTERMEDIO NEONATAL'),
        ('106', 'CUIDADO INTERMEDIO PEDIATRICO'),
        ('107', 'CUIDADO INTERMEDIO ADULTOS'),
        ('108', 'CUIDADO INTENSIVO NEONATAL'),
        ('109', 'CUIDADO INTENSIVO PEDIATRICO'),
        ('110', 'CUIDADO INTENSIVO ADULTOS'),
        ('120', 'CUIDADO BASICO NEONATAL'),
        # Atención y hospitalización
        ('1101', 'ATENCION DEL PARTO'),
        ('1102', 'URGENCIAS'),
        ('1103', 'TRANSPORTE ASISTENCIAL BASICO'),
        ('1104', 'TRANSPORTE ASISTENCIAL MEDICALIZADO'),
        ('1105', 'ATENCION PREHOSPITALARIA'),
        ('129', 'HOSPITALIZACION ADULTOS'),
        ('130', 'HOSPITALIZACION PEDIATRICA'),
        ('131', 'HOSPITALIZACION EN SALUD MENTAL'),
        ('132', 'HOSPITALIZACION PARCIAL'),
        ('133', 'HOSPITALIZACION PACIENTE CRONICO CON VENTILADOR'),
        ('134', 'HOSPITALIZACION PACIENTE CRONICO SIN VENTILADOR'),
        ('135', 'HOSPITALIZACION EN CONSUMO DE SUSTANCIAS PSICOACTIVAS'),
        ('138', 'CUIDADO BASICO DEL CONSUMO DE SUSTANCIAS PSICOACTIVAS'),
        # Cirugías
        ('201', 'CIRUGIA DE CABEZA Y CUELLO'),
        ('202', 'CIRUGIA CARDIOVASCULAR'),
        ('203', 'CIRUGIA GENERAL'),
        ('204', 'CIRUGIA GINECOLOGICA'),
        ('205', 'CIRUGIA MAXILOFACIAL'),
        ('207', 'CIRUGIA ORTOPEDICA'),
        ('208', 'CIRUGIA OFTALMOLOGICA'),
        ('209', 'CIRUGIA OTORRINOLARINGOLOGIA'),
        ('210', 'CIRUGIA ONCOLOGICA'),
        ('211', 'CIRUGIA ORAL'),
        ('212', 'CIRUGIA PEDIATRICA'),
        ('213', 'CIRUGIA PLASTICA Y ESTETICA'),
        ('214', 'CIRUGIA VASCULAR Y ANGIOLOGICA'),
        ('215', 'CIRUGIA UROLOGICA'),
        ('217', 'OTRAS CIRUGIAS'),
        ('218', 'CIRUGIA ENDOVASCULAR NEUROLOGICA'),
        ('231', 'CIRUGIA DE LA MANO'),
        ('232', 'CIRUGIA DE MAMA Y TUMORES TEJIDOS BLANDOS'),
        ('233', 'CIRUGIA DERMATOLOGICA'),
        ('234', 'CIRUGIA DE TORAX'),
        ('235', 'CIRUGIA GASTROINTESTINAL'),
        ('237', 'CIRUGIA PLASTICA ONCOLOGICA'),
        ('245', 'NEUROCIRUGIA'),
        # Especialidades médicas
        ('301', 'ANESTESIA'),
        ('302', 'CARDIOLOGIA'),
        ('303', 'CIRUGIA CARDIOVASCULAR'),
        ('304', 'CIRUGIA GENERAL'),
        ('306', 'CIRUGIA PEDIATRICA'),
        ('308', 'DERMATOLOGIA'),
        ('309', 'DOLOR Y CUIDADOS PALIATIVOS'),
        ('310', 'ENDOCRINOLOGIA'),
        ('312', 'ENFERMERIA'),
        ('316', 'GASTROENTEROLOGIA'),
        ('318', 'GERIATRIA'),
        ('320', 'GINECOBSTETRICIA'),
        ('321', 'HEMATOLOGIA'),
        ('323', 'INFECTOLOGIA'),
        ('325', 'MEDICINA FAMILIAR'),
        ('327', 'MEDICINA FISICA Y REHABILITACION'),
        ('328', 'MEDICINA GENERAL'),
        ('329', 'MEDICINA INTERNA'),
        ('330', 'NEFROLOGIA'),
        ('331', 'NEUMOLOGIA'),
        ('332', 'NEUROLOGIA'),
        ('333', 'NUTRICION Y DIETETICA'),
        ('334', 'ODONTOLOGIA GENERAL'),
        ('335', 'OFTALMOLOGIA'),
        ('336', 'ONCOLOGIA CLINICA'),
        ('337', 'OPTOMETRIA'),
        ('339', 'ORTOPEDIA Y/O TRAUMATOLOGIA'),
        ('340', 'OTORRINOLARINGOLOGIA'),
        ('342', 'PEDIATRIA'),
        ('344', 'PSICOLOGIA'),
        ('345', 'PSIQUIATRIA'),
        ('348', 'REUMATOLOGIA'),
        ('354', 'TOXICOLOGIA'),
        ('355', 'UROLOGIA'),
        ('361', 'CARDIOLOGIA PEDIATRICA'),
        ('377', 'COLOPROCTOLOGIA'),
        ('384', 'NEFROLOGIA PEDIATRICA'),
        ('385', 'NEONATOLOGIA'),
        ('386', 'NEUMOLOGIA PEDIATRICA'),
        ('388', 'NEUROPEDIATRIA'),
        ('391', 'ONCOLOGIA Y HEMATOLOGIA PEDIATRICA'),
        ('396', 'ODONTOPEDIATRIA'),
        ('398', 'MEDICINA DEL DEPORTE'),
        ('406', 'HEMATOLOGIA ONCOLOGICA'),
        ('407', 'MEDICINA DEL TRABAJO Y MEDICINA LABORAL'),
        ('408', 'RADIOTERAPIA'),
        ('409', 'ORTOPEDIA PEDIATRICA'),
        ('411', 'CIRUGIA MAXILOFACIAL'),
        ('423', 'SEGURIDAD Y SALUD EN EL TRABAJO'),
        # Apoyo diagnóstico y terapéutico
        ('706', 'LABORATORIO CLINICO'),
        ('709', 'QUIMIOTERAPIA'),
        ('711', 'RADIOTERAPIA'),
        ('712', 'TOMA DE MUESTRAS DE LABORATORIO CLINICO'),
        ('714', 'SERVICIO FARMACEUTICO'),
        ('715', 'MEDICINA NUCLEAR'),
        ('717', 'LABORATORIO CITOLOGIAS CERVICO-UTERINAS'),
        ('728', 'TERAPIA OCUPACIONAL'),
        ('729', 'TERAPIA RESPIRATORIA'),
        ('733', 'HEMODIALISIS'),
        ('734', 'DIALISIS PERITONEAL'),
        ('739', 'FISIOTERAPIA'),
        ('740', 'FONOAUDIOLOGIA Y/O TERAPIA DEL LENGUAJE'),
        ('741', 'TAMIZAJE DE CANCER DE CUELLO UTERINO'),
        ('742', 'DIAGNOSTICO VASCULAR'),
        ('743', 'HEMODINAMIA E INTERVENCIONISMO'),
        ('744', 'IMAGENES DIAGNOSTICAS- IONIZANTES'),
        ('745', 'IMAGENES DIAGNOSTICAS - NO IONIZANTES'),
        ('746', 'GESTION PRE-TRANSFUSIONAL'),
        ('747', 'PATOLOGIA'),
        ('748', 'RADIOLOGIA ODONTOLOGICA'),
        ('749', 'TOMA DE MUESTRAS DE CUELLO UTERINO Y GINECOLOGICAS')
    ], string='Código de Servicio')
    
    rips_finalidad = fields.Selection([
        ('11', 'VALORACION INTEGRAL PARA LA PROMOCION Y MANTENIMIENTO'),
        ('12', 'DETECCION TEMPRANA DE ENFERMEDAD GENERAL'),
        ('13', 'DETECCION TEMPRANA DE ENFERMEDAD LABORAL'),
        ('14', 'PROTECCION ESPECIFICA'),
        ('15', 'DIAGNOSTICO'),
        ('16', 'TRATAMIENTO'),
        ('17', 'REHABILITACION'),
        ('18', 'PALIACION'),
        ('19', 'PLANIFICACION FAMILIAR Y ANTICONCEPCION'),
        ('20', 'PROMOCION Y APOYO A LA LACTANCIA MATERNA'),
        ('21', 'ATENCION BASICA DE ORIENTACION FAMILIAR'),
        ('22', 'ATENCION PARA EL CUIDADO PRECONCEPCIONAL'),
        ('23', 'ATENCION PARA EL CUIDADO PRENATAL'),
        ('24', 'INTERRUPCION VOLUNTARIA DEL EMBARAZO'),
        ('25', 'ATENCION DEL PARTO Y PUERPERIO'),
        ('26', 'ATENCION PARA EL CUIDADO DEL RECIEN NACIDO'),
        ('27', 'ATENCION PARA EL SEGUIMIENTO DEL RECIEN NACIDO'),
        ('28', 'PREPARACION PARA LA MATERNIDAD Y LA PATERNIDAD'),
        ('29', 'PROMOCION DE ACTIVIDAD FISICA'),
        ('30', 'PROMOCION DE LA CESACION DEL TABAQUISMO'),
        ('31', 'PREVENCION DEL CONSUMO DE SUSTANCIAS PSICOACTIVAS'),
        ('32', 'PROMOCION DE LA ALIMENTACION SALUDABLE'),
        ('33', 'PROMOCION PARA EL EJERCICIO DE LOS DERECHOS SEXUALES Y DERECHOS REPRODUCTIVOS'),
        ('34', 'PROMOCION PARA EL DESARROLLO DE HABILIDADES PARA LA VIDA'),
        ('35', 'PROMOCION PARA LA CONSTRUCCION DE ESTRATEGIAS DE AFRONTAMIENTO FRENTE A SUCESOS VITALES'),
        ('36', 'PROMOCION DE LA SANA CONVIVENCIA Y EL TEJIDO SOCIAL'),
        ('37', 'PROMOCION DE UN AMBIENTE SEGURO Y DE CUIDADO Y PROTECCION DEL AMBIENTE'),
        ('38', 'PROMOCION DEL EMPODERAMIENTO PARA EL EJERCICIO DEL DERECHO A LA SALUD'),
        ('39', 'PROMOCION PARA LA ADOPCION DE PRACTICAS DE CRIANZA Y CUIDADO PARA LA SALUD'),
        ('40', 'PROMOCION DE LA CAPACIDAD DE LA AGENCIA Y CUIDADO DE LA SALUD'),
        ('41', 'DESARROLLO DE HABILIDADES COGNITIVAS'),
        ('42', 'INTERVENCION COLECTIVA'),
        ('43', 'MODIFICACION DE LA ESTETICA CORPORAL FINES ESTETICOS'),
        ('44', 'OTRA')
    ], string='Finalidad')
    
    rips_causa_externa = fields.Selection([
        ('21', 'Accidente de trabajo'),
        ('22', 'Accidente en el hogar'),
        ('23', 'Accidente de tránsito de origen común'),
        ('24', 'Accidente de tránsito de origen laboral'),
        ('25', 'Accidente en el entorno educativo'),
        ('26', 'Otro tipo de accidente'),
        ('27', 'Evento catastrófico de origen natural'),
        ('28', 'Lesión por agresión'),
        ('29', 'Lesión auto infligida'),
        ('30', 'Sospecha de violencia física'),
        ('31', 'Sospecha de violencia psicológica'),
        ('32', 'Sospecha de violencia sexual'),
        ('33', 'Sospecha de negligencia y abandono'),
        ('34', 'IVE relacionado con peligro a la salud o vida de la mujer'),
        ('35', 'IVE por malformación congénita incompatible con la vida'),
        ('36', 'IVE por violencia sexual, incesto o por inseminación artificial o transferencia de óvulo fecundado no consentida'),
        ('37', 'Evento adverso en salud'),
        ('38', 'Enfermedad general'),
        ('39', 'Enfermedad laboral'),
        ('40', 'Promoción y mantenimiento de la salud – intervenciones individuales'),
        ('41', 'Intervención colectiva'),
        ('42', 'Atención de población materno perinatal'),
        ('43', 'Riesgo ambiental'),
        ('44', 'Otros eventos catastróficos'),
        ('45', 'Accidente de mina antipersonal – MAP'),
        ('46', 'Accidente de artefacto explosivo improvisado – AEI'),
        ('47', 'Accidente de munición sin explotar – MUSE'),
        ('48', 'Otra víctima de conflicto armado colombiano')
    ], string='Causa Externa')
    
    # CAMPOS PARA VÍA DE INGRESO (PROCEDIMIENTOS/HOSPITALIZACIONES)
    rips_via_ingreso = fields.Selection([
        ('01', 'DEMANDA ESPONTANEA'),
        ('02', 'DERIVADO DE CONSULTA EXTERNA'),
        ('03', 'DERIVADO DE URGENCIAS'),
        ('04', 'DERIVADO DE HOSPITALZACION'),
        ('05', 'DERIVADO DE SALA DE CIRUGIA'),
        ('06', 'DERIVADO DE SALA DE PARTOS'),
        ('07', 'RECIEN NACIDO EN LA INSTITUCION'),
        ('08', 'RECIEN NACIDO EN OTRA INSTITUCION'),
        ('09', 'DERIVADO O REFERIDO DE HOSPITALIZACION DOMICILIARIA'),
        ('10', 'DERIVADO DE ATENCION DOMICILIARIA'),
        ('11', 'DERIVADO DE TELEMEDICINA'),
        ('12', 'DERIVADO DE JORNADA DE SALUD'),
        ('13', 'REFERIDO DE OTRA INSTITUCION'),
        ('14', 'CONTRAREFERIDO DE OTRA INSTITUCION')
    ], string='Vía de Ingreso al Servicio')
    
    # CAMPOS PARA EGRESO (URGENCIAS/HOSPITALIZACIÓN)
    rips_destino_usuario = fields.Selection([
        ('01', 'PACIENTE CON DESTINO A SU DOMICILIO'),
        ('02', 'PACIENTE MUERTO'),
        ('03', 'PACIENTE DERIVADO A OTRO SERVICIO'),
        ('04', 'REFERIDO A OTRA INSTITUCION'),
        ('05', 'CONTRAREFERIDO A OTRA INSTITUCION'),
        ('06', 'DERIVADO O REFERIDO A HOSPITALIZACION DOMICILIRIA'),
        ('07', 'DERIVADO A SERVICIO SOCIAL'),
        ('08', 'PACIENTE CONTINUA EN EL SERVICIO (CORTE FACTURACION)')
    ], string='Destino Usuario Egreso')
    
    # CAMPOS PARA DIAGNÓSTICO
    rips_tipo_diagnostico = fields.Selection([
        ('01', 'Impresión diagnóstica'),
        ('02', 'Confirmado nuevo'),
        ('03', 'Confirmado repetido')
    ], string='Tipo de Diagnóstico Principal')
    

    rips_requires_authorization = fields.Boolean(
        string='Requiere Autorización', 
        default=False)
    
    rips_requires_diagnosis = fields.Boolean(
        string='Requiere Diagnóstico', 
        default=True)
    

    
    @api.onchange('rips_service_type')
    def _onchange_rips_service_type(self):
        """Configurar campos relevantes según el tipo de servicio RIPS"""
        self.rips_tipo_medicamento = False
        self.rips_tipo_os = False
        self.rips_finalidad = False
        self.rips_causa_externa = False
        self.rips_modalidad = False
        self.rips_grupo_servicio = False
        self.rips_cod_servicio = False
        self.rips_unidad_medida = False
        self.rips_unidad_dispensacion = False
        self.rips_forma_farmaceutica = False
        self.rips_via_ingreso = False
        self.rips_destino_usuario = False
        self.rips_tipo_diagnostico = False
        
        if self.rips_service_type == 'consulta':
            self.rips_modalidad = '01'  
            self.rips_grupo_servicio = '01'  
            self.rips_finalidad = '15'  
            self.rips_causa_externa = '38'  
            self.rips_tipo_diagnostico = '01'  
            self.rips_requires_diagnosis = True
            
        elif self.rips_service_type == 'procedimiento':
            self.rips_modalidad = '01' 
            self.rips_grupo_servicio = '02' 
            self.rips_finalidad = '16'  
            self.rips_via_ingreso = '01'  
            self.rips_requires_diagnosis = True
            
        elif self.rips_service_type == 'medicamento':
            self.rips_tipo_medicamento = '01'  
            self.rips_unidad_dispensacion = '66' 
            self.rips_forma_farmaceutica = 'COLFF001'  
            self.rips_requires_diagnosis = False
            
        elif self.rips_service_type == 'otro_servicio':
            self.rips_tipo_os = '01' 
            self.rips_requires_diagnosis = False
            
        elif self.rips_service_type == 'urgencia':
            self.rips_causa_externa = '38'  
            self.rips_destino_usuario = '01'  
            self.rips_requires_diagnosis = True
            self.rips_tipo_diagnostico = '02'  
            
        elif self.rips_service_type == 'hospitalizacion':
            self.rips_causa_externa = '38' 
            self.rips_via_ingreso = '03' 
            self.rips_destino_usuario = '01'  
            self.rips_requires_diagnosis = True
            self.rips_tipo_diagnostico = '02' 
            
        elif self.rips_service_type == 'recien_nacido':
            self.rips_requires_diagnosis = True
            self.rips_destino_usuario = '01'  
    

    @api.onchange('is_kit_product')
    def onchange_is_kit_product(self):
        if self.is_kit_product:
            self.type = 'consu'

    def acs_update_price_for_kit(self):
        for rec in self:
            rec.list_price = rec.kit_amount_total
            rec.standard_price = rec.kit_cost_total

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
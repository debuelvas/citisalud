from odoo import fields, models, api, _
from odoo import tools
import datetime 
from datetime import datetime, date 
from dateutil import relativedelta
from odoo.tools import DEFAULT_SERVER_DATE_FORMAT as DF
from odoo.exceptions import ValidationError
import base64
import calendar
class ResPartner(models.Model):
	_inherit = "res.partner"

	entity_code = fields.Char(string="Codigo Entidad")


class ACSPatient2(models.Model):
	_inherit = 'hms.patient'
	
	tdoc = fields.Selection([
		('cc', 'CC-Cedula'),
		('ce', 'CE-Cedula de extranjera'),
		('pa', 'PA-Pasaporte'),
		('rc', 'RC-Registro Civil'),
		('ti', 'TI-Tarjeta de identidad'),
		('as', 'AS-Adulto sin identificación'),
		('ms', 'MS-Menor sin identificación'),
		('nu', 'NUIP-Numero Único de Identificación Personal'),
		('sa', 'SA-salvo conducto'),
		('pe', 'PE-Permiso Especial'),
		('cn', 'CN-Certificado Nacido Vivo'),
		('pt', 'PT-Permiso Temporal'),],
		# compute='onchange_birth_date',
		readonly=False,
		string='Tipo de documento')

	zona =  fields.Selection([
		('U', 'Urbana'), 
		('R', 'Rural')], 
		string='Zona', 
		required=False)
	nro_afiliacion = fields.Char(string='Nº de Afiliación')
	poliza_medicina_prepagada = fields.Boolean(string='Tiene Póliza de medicina prepagada')
	lateralidad_id = fields.Selection([
		('1', 'DIESTRO'),
		('2', 'ZURDO'),
		('3', 'AMBIDIESTRO'),
	], string='Lateralidad')
	discapacidad_fisica = fields.Selection([
		('1', 'lesión medular'),
		('2', 'Esclerosis Multiple'),
		('3', 'Paralisis Cerebral'),
		('4', 'Mal de Parkinson'),
		('5', 'Espina Bifida'),
		('6', 'Acondroplasia'),
		('7', 'Albinismo'),
		('8', 'Otros'),
	], string='Físicas')
	discapacidad_sensorial = fields.Selection([
		('1', 'Discapacidad Visual'),
		('2', 'Discapacidad Auditiva'),
		('3', 'Otras'),
	], string='Sensorial')
	discapacidad_aprendizaje = fields.Selection([
		('1', 'Dislexia'),
		('2', 'Disgrafia'),
		('3', 'Discalculia'),
		('4', 'Otra'),
	], string='Problemas de Aprendizaje')
	seleccion_poblacion = fields.Boolean(string='Población Especial')
	Poblacion_espacial  = fields.Selection([
		('1', u'Indígena'),
		('2', u'Rom'),
		('3', u'Afrodescendientes'),
		('4', u'Raizal'),
		('5', u'Palenqueros'),
		('6', u'Otros'),
	], string='Etnia', 
		index=True, 
		track_visibility='onchange', 
		copy=False)
	codigo_prestador = fields.Char(string='Codigo de prestador', size=12)
	nacimiento_country_id =  fields.Many2one('res.country', string='País/Nación')
	eps = fields.Many2one('res.partner', 
		string='EPS', 
		ondelete='restrict')
	tipo_afiliacion = fields.Selection([
		('contributory', 'Contributivo'), 
		('subsidized', 'Subsidiado'), 
		('linked', 'Vinculado')], 
		string="Tipo De Regimen")
	tipo_usuario = fields.Selection([
		('A', 'A - Adicional'), 
		('B', 'B - Beneficiario'),
		('C', 'C - cotizante'),
		('F', 'F - Cabeza de familia'),
		('O', 'O - Otros miembros'),
		('A2','A - Asegurado.'),], 
		string="Tipo De Afiliacion")
	cod_p = fields.Char(related='company_id.cod_prestadorservicio', 
		string='Código Prestador Servicio', 
		store=True, 
		readonly=True)
	sex = fields.Selection([
		('m', 'Male'), 
		('f', 'Female'), 
		('o', 'Other')], string='Sexo', default='f', tracking=True)
	edad = fields.Integer(string='Edad', compute='_compute_age_meassure_unit', inverse='_inverse_age', store=True)
	age_unit = fields.Selection([('1','Years'),('2','Months'),('3','Days')],
								string='Unidad de medida de edad',
								inverse='_inverse_age',
								compute='_compute_age_meassure_unit', store=True)




	@api.onchange('firs_name', 'second_name', 'first_lastname', 'second_lastname')
	def _onchange_person_names(self):
		def custom_capitalize(s):
			return ' '.join([word.capitalize() for word in s.split()])
		if self.company_type == 'person':
			self.firs_name = custom_capitalize(self.firs_name) if self.firs_name else self.firs_name
			self.second_name = custom_capitalize(self.second_name) if self.second_name else self.second_name
			self.first_lastname = custom_capitalize(self.first_lastname) if self.first_lastname else self.first_lastname
			self.second_lastname = custom_capitalize(self.second_lastname) if self.second_lastname else self.second_lastname

			# Combine capitalized names
			names = [name for name in [self.firs_name, self.second_name, self.first_lastname, self.second_lastname] if name]
			self.name = u' '.join(names)
	@api.depends('birthday')
	def _compute_age_meassure_unit(self):
		"""Optimizado: Calcula edad y unidad de medida basado en fecha de nacimiento"""
		today = date.today()  # Calcular una sola vez
		for record in self:
			if record.birthday:
				days_difference = (today - record.birthday).days
				if days_difference >= 364:
					record.age_unit = '1'
					record.edad = days_difference // 365
				elif days_difference >= 30:
					record.age_unit = '2'
					record.edad = days_difference // 30
				else:
					record.age_unit = '3'
					record.edad = days_difference
			else:
				record.age_unit = False
				record.edad = 0

	@api.onchange("vat")
	def onchange_document_vat_co(self):
		self.vat_co	= self.vat

	@api.onchange("tdoc")
	def onchange_document_type(self):
		if self.tdoc == 'rc':
			self.document_type = '11'
			self.l10n_latam_identification_type_id = self.env.ref("l10n_co.civil_registration").id
		elif self.tdoc== 'cc':
			self.document_type = '13'
			self.l10n_latam_identification_type_id = self.env.ref("l10n_co.national_citizen_id").id
		elif self.tdoc== 'ce':
			self.document_type = '22'
			self.l10n_latam_identification_type_id = self.env.ref("l10n_co.foreign_resident_card").id
		elif self.tdoc== 'pa':
			self.document_type = '41'
			self.l10n_latam_identification_type_id = self.env.ref("l10n_latam_base.it_pass").id
		elif self.tdoc== 'ti':
			self.document_type = '12'
			self.l10n_latam_identification_type_id = self.env.ref("l10n_co.id_card").id
		elif self.tdoc== 'pt':
			self.document_type = '47'
			self.l10n_latam_identification_type_id = self.env.ref("l10n_co.residence_document").id
		elif self.tdoc in ('as','ms'):
			self.document_type = '91'
			self.l10n_latam_identification_type_id = self.env.ref("l10n_co.niup_id").id



	@api.onchange('edad')
	def _inverse_age(self):
		for line in self:
			if line.edad:
				line.edad = 0
			line.age_unit = 1

	@api.onchange('age_unit')
	def _inverse_age(self):
		for line in self:
			if line.age_unit:
				line.age_unit = '1'

	@api.onchange('birthday','age_unit')
	def onchange_birth_date(self):
		if self.birthday and self.country_id.code == "CO":
			if self.edad >= 2 and self.age_unit == '1':
				self.tdoc = 'rc'
			if self.edad >= 12 and self.age_unit == '1':
				self.tdoc = 'ti'
			if self.edad >= 18 and self.age_unit == '1':
				self.tdoc = 'cc'
			if self.birthday > fields.Date.today():
					self.birthday = False
					return {
						'warning': {
							'title': "¡Error de validacion!",
							'message': f"La fecha del cumpleaños no puede ser mayor que la fecha de hoy."
						}
					}

	@api.onchange('city_id')
	def _onchange_city_id(self):
		self.city = self.city_id.name
		self.zip = self.city_id.zipcode
		self.state_id = self.city_id.state_id.id


	# @api.model
	# def create(self, vals):
	# 	if vals.get('email', False):
	# 		self._check_email(vals.get('email'))
	# 	if vals.get('document_type', False) and vals['document_type'] in ['cc','ti']:
	# 		numberid_integer = 0
	# 		if vals.get('numberid_integer', False):
	# 			numberid_integer = vals['numberid_integer']
	# 		numberid = self._check_assign_numberid(numberid_integer)
	# 		vals.update({'name': numberid})
	# 	if vals.get('birth_date', False):
	# 		warn_msg = self._check_birth_date(vals['birth_date'])
	# 		if warn_msg:
	# 			raise ValidationError(warn_msg)
	# 	tools.image_resize_images(vals)
	# 	res = super(ACSPatient2, self).create(vals)
	# 	res._check_document_types()
	@api.constrains
	def _check_document_types(self):
		for data in self:
			if self.country_id.code == "CO":
				if data.age_unit == '3' and data.tdoc not in ['rc','ms']:
					raise ValidationError(_("Sólo podrá elegir documentos 'RC' o 'MS', para edad inferior a 1 mes."))
				if data.edad > 17 and data.age_unit == '1' and data.tdoc in ['rc','ms']:
					raise ValidationError(_("No puede elegir los tipos de documentos 'RC' o 'MS' para personas mayores de 17 años."))
				if data.age_unit in ['2','3'] and data.tdoc in ['cc','as','ti']:
					raise ValidationError(_("No puede elegir los tipos de documentos 'CC', 'TI' o 'AS' para una edad inferior a 1 año."))
				if data.tdoc == 'ms' and data.age_unit != '3':
					raise ValidationError(_("Solo puede elegir el documento 'MS' para una edad entre 1 y 30 días."))
				if data.tdoc == 'as' and data.age_unit == '1' and data.edad <= 17:
					raise ValidationError(_("Puede elegir el documento 'AS' solo si la edad es mayor a 17 años."))



class ResCompany(models.Model):
    _description = "Hospital - CO"
    _inherit = "res.company"
    
    cod_prestadorservicio = fields.Char(u'Código Prestador Servicio', help=u'Código de Prestador del Servicio')


class doctor_contrato_aseguradora(models.Model):
    _name = "doctor.contract.insurer"
    _description = "Contrato"
    
    active = fields.Boolean('¿Activo?',default=True)
    contract_code = fields.Char('Codigo',  required=True)
    f_inicio = fields.Date('Fecha Inicio', required=True, default=lambda *a: datetime.now().strftime('%Y-%m-%d %H:%M:%S'),)
    f_fin = fields.Date('Fecha Fin')
    insurer_id = fields.Many2one('res.partner', 'Entidad Contratante', required=False)
    valor = fields.Float('Valor', digits=(3, 3))
    valor_ejecutado = fields.Float('Valor Ejecutado', digits=(3, 3))
    regional = fields.Many2one('account.analytic.account', string="Regional")
    name = fields.Char( 'Nombre', compute='d_name', store=True)

    """
    Create sobrescrito para convertir codigo del contrato en mayúscula.
	"""
    @api.depends('contract_code','insurer_id' ,'valor','f_inicio')
    def d_name(self):
        for name in self:
            name.name = ('%s - %s | %s' % (name.contract_code,name.insurer_id.name, name.f_inicio))
            
    @api.onchange('contract_code')
    def set_upper1(self):    
        self.contract_code = str(self.contract_code).upper()   
        return
    _sql_constraints = [('contract_code_constraint', 'unique(contract_code)', 'Este código de contrato ya existe en base de datos.')]

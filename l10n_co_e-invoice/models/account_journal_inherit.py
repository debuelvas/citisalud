# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from datetime import datetime, date
from lxml import etree
from markupsafe import Markup
import logging

_logger = logging.getLogger(__name__)


class AccountJournalInherit(models.Model):
	_inherit = "account.journal"

	debit_note_sequence_id = fields.Many2one('ir.sequence', string='Debit Note Entry Sequence', help="This field contains the information related to the numbering of the dedit note entries of this journal.", copy=False)
	debit_note_sequence_number_next = fields.Integer(string='Nota de débito: Número siguiente', help='The next sequence number will be used for the next dedit note.', compute='_compute_debit_note_seq_number_next', inverse='_inverse_debit_note_seq_number_next')
	debit_note_sequence = fields.Boolean(string='Dedicated Dedit Note Sequence', help="Check this box if you don't want to share the same sequence for invoices and dedit notes made from this journal", default=False)

	# ==================== CAMPOS SECTOR SALUD ====================
	health_operation_type = fields.Selection(
		[
			('SS-CUFE', 'SS-CUFE - Acreditación por FEV - Factura que acredita un recaudo documentado mediante FEV previa'),
			('SS-CUDE', 'SS-CUDE - Acreditación por Contingencia/NC - Factura que acredita recaudo registrado en contingencia'),
			('SS-POS', 'SS-POS - Acreditación por POS - Factura que acredita recaudo por documento POS/datáfono'),
			('SS-SNum', 'SS-SNum - Acreditación por Talonario/Papel - Factura que acredita recaudo con documento manual'),
			('SS-Recaudo', 'SS-Recaudo - Comprobante de Recaudo - Documento que registra el recaudo inicial del usuario'),
			('SS-Reporte', 'SS-Reporte - Reporte Informativo - Factura que informa un recaudo sin acreditarlo en el valor'),
			('SS-SinAporte', 'SS-SinAporte - Sin Aporte del Usuario - Factura por servicios sin ningún aporte del usuario'),
		],
		string='Tipo de Operación Salud',
		help='Tipo de operación predeterminado para facturas del sector salud creadas con este diario'
	)
	is_health_journal = fields.Boolean(
		string='Diario de Salud',
		help='Marcar si este diario se usa específicamente para facturación del sector salud'
	)
	health_provider_code = fields.Char(
		string='Código Prestador',
		help='Código único del prestador de servicios de salud que se usará por defecto en las facturas'
	)

	# ==================== MÉTODO DE PAGO DIAN ====================
	default_payment_method_dian_id = fields.Many2one(
		'account.payment.method.dian',
		string='Método de Pago DIAN por Defecto',
		help='Método de pago DIAN que se usará por defecto en las facturas de este diario'
	)

	# ==================== CAMPOS RESOLUCIÓN DIAN ACTIVA (COMPUTADOS) ====================
	active_resolution_number = fields.Char(
		string='Resolución Activa',
		compute='_compute_active_resolution_info',
		store=False,
		help='Número de la resolución DIAN actualmente activa'
	)
	active_resolution_days_remaining = fields.Integer(
		string='Días Restantes',
		compute='_compute_active_resolution_info',
		store=False,
		help='Días que faltan para que venza la resolución activa'
	)


	# ==================== MÉTODOS COMPUTADOS ====================

	@api.depends('sequence_id', 'sequence_id.use_dian_control', 'sequence_id.dian_resolution_ids.active_resolution', 'sequence_id.dian_resolution_ids.date_to')
	def _compute_active_resolution_info(self):
		"""
		Calcula la información de la resolución DIAN activa:
		- Número de resolución
		- Días restantes hasta vencimiento
		"""
		for journal in self:
			if not journal.sequence_id or not journal.sequence_id.use_dian_control:
				journal.active_resolution_number = False
				journal.active_resolution_days_remaining = 0
				continue

			# Buscar resolución activa
			active_resolution = journal.sequence_id.dian_resolution_ids.filtered(
				lambda r: r.active_resolution
			)

			if active_resolution:
				# Tomar la primera (debería ser única por constraint)
				resolution = active_resolution[0]
				journal.active_resolution_number = resolution.resolution_number

				# Calcular días restantes
				if resolution.date_to:
					today = date.today()
					date_to = fields.Date.from_string(resolution.date_to) if isinstance(resolution.date_to, str) else resolution.date_to
					delta = date_to - today
					journal.active_resolution_days_remaining = max(0, delta.days)
				else:
					journal.active_resolution_days_remaining = 0
			else:
				journal.active_resolution_number = False
				journal.active_resolution_days_remaining = 0

	# ==================== ONCHANGE METHODS ====================

	@api.onchange('is_health_journal')
	def _onchange_is_health_journal(self):
		"""Establece valores predeterminados al marcar como diario de salud"""
		if self.is_health_journal and not self.health_operation_type:
			self.health_operation_type = 'SS-CUFE'
		elif not self.is_health_journal:
			self.health_operation_type = False
			self.health_provider_code = False

	@api.depends('debit_note_sequence_id.use_date_range', 'debit_note_sequence_id.number_next_actual')
	def _compute_debit_note_seq_number_next(self):
		'''Compute 'sequence_number_next' according to the current sequence in use,
		an ir.sequence or an ir.sequence.date_range.
		'''
		for journal in self:
			if journal.debit_note_sequence_id and journal.debit_note_sequence:
				sequence = journal.debit_note_sequence_id._get_current_sequence()
				journal.debit_note_sequence_number_next = sequence.number_next_actual
			else:
				journal.debit_note_sequence_number_next = 1

	
	def _inverse_debit_note_seq_number_next(self):
		'''Inverse 'debit_note_sequence_number_next' to edit the current sequence next number.
		'''
		for journal in self:
			if journal.debit_note_sequence_id and journal.debit_note_sequence and journal.debit_note_sequence_number_next:
				sequence = journal.debit_note_sequence_id._get_current_sequence()
				sequence.number_next = journal.debit_note_sequence_number_next

	@api.model_create_multi
	def create(self, vals_list):
		for vals in vals_list:
			if vals.get('type') in ('sale', 'purchase') and vals.get('debit_note_sequence') and not vals.get('debit_note_sequence_id'):
				vals.update({'debit_note_sequence_id': self.sudo()._create_sequence_debit_note(vals, debitnote=True).id})
		journals = super(AccountJournalInherit, self).create(vals_list)
		return journals

	
	def write(self, vals):
		# create the relevant debit note sequence
		if vals.get('debit_note_sequence'):
			for journal in self.filtered(lambda j: j.type in ('sale', 'purchase') and not j.debit_note_sequence_id):
				journal_vals = {
					'name': journal.name,
					'company_id': journal.company_id.id,
					'code': journal.code,
					'debit_note_sequence_number_next': vals.get('debit_note_sequence_number_next', journal.debit_note_sequence_number_next),
				}
				journal.debit_note_sequence_id = self.sudo()._create_sequence_debit_note(journal_vals, debitnote=True).id
		result = super(AccountJournalInherit, self).write(vals)
		return result

	@api.model
	def _create_sequence_debit_note(self, vals, debitnote=False):
		""" Create new no_gap entry sequence for every new Journal"""
		seq_name = debitnote and vals['code'] + _(': Debit note') or vals['code']
		seq = {
			'name': _('%s Sequence') % seq_name,
			'implementation': 'no_gap',
			'prefix': 'ND',
			'padding': 4,
			'number_increment': 1,
			'use_date_range': True,
			'code' : 'nota_debito.sequence'
		}
		if 'company_id' in vals:
			seq['company_id'] = vals['company_id']
		seq = self.env['ir.sequence'].create(seq)
		seq_date_range = seq._get_current_sequence()
		seq_date_range.number_next = debitnote and vals.get('debit_note_sequence_number_next', 1) or vals.get('sequence_number_next', 1)
		return seq

	# ==================== MÉTODOS AUXILIARES DIAN ====================

	@api.model
	def _parse_dian_resolution_node(self, root):
		"""
		Parsea un nodo 'NumberRangeResponse' y retorna los valores para crear ir.sequence.dian_resolution.

		:param root: lxml._Element con estructura DIAN
		:return: dict con valores para crear la resolución
		"""
		values = {}
		mapping = {
			'resolution_number': 'ResolutionNumber',
			'date_from': 'ValidDateFrom',
			'date_to': 'ValidDateTo',
			'number_from': 'FromNumber',
			'number_to': 'ToNumber',
		}

		for field_name, xpath in mapping.items():
			field_value = root.findtext("./{*}" + xpath)
			if field_value:
				values[field_name] = field_value

		return values

	def _get_dian_resolutions_by_prefix(self, root):
		"""
		Extrae todas las resoluciones DIAN por prefijo desde la respuesta XML.
		"""
		prefix_to_resolution = {}
		for range_node in root.iterfind(".//{*}NumberRangeResponse"):
			journal_prefix = range_node.findtext("./{*}Prefix")
			prefix_to_resolution[journal_prefix] = self._parse_dian_resolution_node(range_node)
		return prefix_to_resolution

	def _create_or_update_dian_resolution(self, resolution_values):
		"""
		Crea o actualiza una resolución DIAN en la secuencia del diario.

		:param resolution_values: dict con los valores de la resolución
		:return: registro de ir.sequence.dian_resolution creado/actualizado
		"""
		# Habilitar control DIAN si no está habilitado
		if not self.sequence_id.use_dian_control:
			self.sequence_id.write({'use_dian_control': True})

		# Buscar si ya existe una resolución con el mismo número
		existing_resolution = self.env['ir.sequence.dian_resolution'].search([
			('sequence_id', '=', self.sequence_id.id),
			('resolution_number', '=', resolution_values['resolution_number'])
		], limit=1)

		if existing_resolution:
			# Actualizar resolución existente
			existing_resolution.write(resolution_values)
			self.message_post(body=_(
				"Resolución DIAN actualizada: %s",
				resolution_values['resolution_number']
			))
			return existing_resolution
		else:
			# Crear nueva resolución
			resolution_values['sequence_id'] = self.sequence_id.id
			resolution_values['active_resolution'] = False  # Usuario debe activarla manualmente

			new_resolution = self.env['ir.sequence.dian_resolution'].create(resolution_values)

			self.message_post(body=_(
				"Nueva resolución DIAN creada: %s (del %s al %s, vigente hasta %s)",
				resolution_values['resolution_number'],
				resolution_values['number_from'],
				resolution_values['number_to'],
				resolution_values['date_to']
			))
			return new_resolution

	def _process_dian_response(self, response):
		"""
		Procesa la respuesta SOAP de GetNumberingRange y crea las resoluciones.
		"""
		if not response.get('response'):
			raise UserError(_("El servidor de la DIAN no respondió."))

		root = etree.fromstring(response['response'])
		operation_code = root.findtext(".//{*}OperationCode")

		if operation_code != "100":
			error_msg = root.findtext(".//{*}OperationDescription")
			raise UserError(_(
				'La DIAN retornó error %(code)s: "%(message)s"',
				code=operation_code,
				message=error_msg,
			))

		prefix_to_resolution = self._get_dian_resolutions_by_prefix(root)
		resolution_data = prefix_to_resolution.get(self.code)

		if not resolution_data:
			available_prefixes = ", ".join(prefix_to_resolution.keys())
			raise UserError(_(
				"No se encontró resolución para el prefijo '%(prefix)s'. Prefijos disponibles: %(available)s",
				prefix=self.code,
				available=available_prefixes,
			))

		# Crear o actualizar la resolución
		resolution = self._create_or_update_dian_resolution(resolution_data)

		return {
			"type": "ir.actions.client",
			"tag": "display_notification",
			"params": {
				"type": "success",
				"title": _("Resolución DIAN sincronizada"),
				"message": _(
					"Resolución %(number)s creada/actualizada. Vigente del %(number_from)s al %(number_to)s hasta %(date)s",
					number=resolution.resolution_number,
					number_from=resolution.number_from,
					number_to=resolution.number_to,
					date=resolution.date_to,
				),
				"sticky": False,
			}
		}

	# ==================== BOTONES / ACTIONS ====================

	def button_create_dian_resolution(self):
		"""
		Consulta la DIAN por rangos de numeración y crea/actualiza la resolución automáticamente.

		Este botón:
		1. Consulta el webservice de la DIAN (usando el método query_numbering_range de res.company)
		2. Obtiene las resoluciones vigentes
		3. Crea/actualiza automáticamente la resolución en ir.sequence.dian_resolution
		"""
		self.ensure_one()

		if not self.sequence_id:
			raise UserError(_('Este diario no tiene una secuencia asignada. Configure la secuencia primero.'))

		# Verificar configuración DIAN en la compañía
		company = self.company_id

		if not company.software_identification_code or company.software_identification_code == "0":
			raise UserError(_(
				'No hay código de software DIAN configurado en la compañía.\n'
				'Configure: Ajustes > Facturación Electrónica > Código de identificación del software'
			))

		if not company.partner_id.vat_co:
			raise UserError(_(
				'La compañía no tiene NIT configurado.\n'
				'Configure el NIT en el contacto de la compañía.'
			))

		# Validar que haya certificado digital
		if not company.digital_certificate or company.digital_certificate == "0":
			raise UserError(_(
				'No hay certificado digital configurado.\n'
				'Configure: Ajustes > Facturación Electrónica > Certificado digital público'
			))

		# Llamar al método de consulta de la compañía
		try:
			_logger.info("Consultando rangos de numeración DIAN para el diario %s", self.code)

			# Ejecutar la consulta
			company.query_numbering_range()

			# Verificar que se haya guardado la respuesta XML
			if not company.xml_response_numbering_range:
				raise UserError(_(
					'La DIAN no retornó información de rangos.\n'
					'Verifique la configuración y que el software esté autorizado.'
				))

			# Parsear la respuesta XML guardada
			root = etree.fromstring(company.xml_response_numbering_range.encode('utf-8'))

		except Exception as e:
			_logger.error("Error al consultar la DIAN: %s", str(e))
			raise UserError(_('Error al consultar la DIAN:\n%s', str(e)))

		# Procesar la respuesta
		return self._process_dian_response({'response': company.xml_response_numbering_range})

class AccountMoveInherit(models.Model):
    _inherit = "account.move"

    validate_cron = fields.Boolean(string="Validar con CRON", default=False, copy=False)
    diancode_id = fields.Many2one(
        "dian.document", string="Código DIAN", readonly=False, tracking=True, copy=False
    )
from odoo import api, fields, models, _
from odoo.addons.base.models.ir_sequence import _update_nogap
from datetime import datetime
from odoo.exceptions import ValidationError


class AccountJournalInherit(models.Model):
	_inherit = "account.journal"
 
	sequence_id = fields.Many2one('ir.sequence', string='Entry Sequence',
								help="This field contains the information related to the numbering of the"
									" journal entries of this journal.", copy=False)
	sequence_number_next = fields.Integer(string='Next Number',
										help='The next sequence number will be used for the next invoice.',
										compute='_compute_seq_number_next',
										inverse='_inverse_seq_number_next')
	refund_sequence_id = fields.Many2one('ir.sequence', string='Credit Note Entry Sequence',
										help="This field contains the information related to the "
											"numbering of the credit note entries of this journal.",
										copy=False)
	refund_sequence_number_next = fields.Integer(string='Credit Notes Next Number',
												help='The next sequence number will be used for the next'
													'credit note.',
												compute='_compute_refund_seq_number_next',
												inverse='_inverse_refund_seq_number_next')

	@api.depends('sequence_id.use_date_range', 'sequence_id.number_next_actual')
	def _compute_seq_number_next(self):
		for journal in self:
			if journal.sequence_id:
				sequence = journal.sequence_id._get_current_sequence()
				journal.sequence_number_next = sequence.number_next_actual
			else:
				journal.sequence_number_next = 1

	def _inverse_seq_number_next(self):
		for journal in self:
			if journal.sequence_id and journal.sequence_number_next:
				sequence = journal.sequence_id._get_current_sequence()
				sequence.sudo().number_next = journal.sequence_number_next

	@api.depends('refund_sequence_id.use_date_range', 'refund_sequence_id.number_next_actual')
	def _compute_refund_seq_number_next(self):
		for journal in self:
			if journal.refund_sequence_id and journal.refund_sequence:
				sequence = journal.refund_sequence_id._get_current_sequence()
				journal.refund_sequence_number_next = sequence.number_next_actual
			else:
				journal.refund_sequence_number_next = 1

	def _inverse_refund_seq_number_next(self):
		for journal in self:
			if journal.refund_sequence_id and journal.refund_sequence and journal.refund_sequence_number_next:
				sequence = journal.refund_sequence_id._get_current_sequence()
				sequence.sudo().number_next = journal.refund_sequence_number_next

	@api.constrains("refund_sequence_id", "sequence_id")
	def _check_journal_sequence(self):
		for journal in self:
			if (
					journal.refund_sequence_id
					and journal.sequence_id
					and journal.refund_sequence_id == journal.sequence_id
			):
				raise ValidationError(
					_(
						"On journal '%s', the same sequence is used as "
						"Entry Sequence and Credit Note Entry Sequence."
					)
					% journal.display_name
				)
			if journal.sequence_id and not journal.sequence_id.company_id:
				raise ValidationError(
					_(
						"The company is not set on sequence '%s' configured on "
						"journal '%s'."
					)
					% (journal.sequence_id.display_name, journal.display_name)
				)
			if journal.refund_sequence_id and not journal.refund_sequence_id.company_id:
				raise ValidationError(
					_(
						"The company is not set on sequence '%s' configured as "
						"credit note sequence of journal '%s'."
					)
					% (journal.refund_sequence_id.display_name, journal.display_name)
				)

	@api.model_create_multi
	def create(self, vals_list):
		for vals in vals_list:
			# Crear secuencia principal si no existe
			if not vals.get("sequence_id"):
				vals["sequence_id"] = self._create_sequence(vals).id
			
			# Crear secuencia de reembolso si es necesario
			if (vals.get("type") in ("sale", "purchase") 
				and vals.get("refund_sequence") 
				and not vals.get("refund_sequence_id")):
				vals["refund_sequence_id"] = self._create_sequence(vals, refund=True).id
		
		return super().create(vals_list)


	@api.model
	def _prepare_sequence(self, vals, refund=False):
		code = vals.get("code") and vals["code"].upper() or ""
		prefix = "%s%s/%%(range_year)s/" % (refund and "R" or "", code)
		seq_vals = {
			"name": "%s %s"
					% (vals.get("name", _("Sequence")), refund and _("Refund") + " " or ""),
			"company_id": vals.get("company_id") or self.env.company.id,
			"implementation": "no_gap",
			"prefix": code,
			"padding": 4,
			#"use_date_range": True,
		}
		return seq_vals

	@api.model
	def _create_sequence(self, vals, refund=False):
		seq_vals = self._prepare_sequence(vals, refund=refund)
		return self.env["ir.sequence"].sudo().create(seq_vals)



class IrSequenceInherit(models.Model):
	_inherit = 'ir.sequence'


	DIAN_TYPE = [('invoice_computer_generated', 'Invoice generated from computer'),
					('pos_invoice', 'POS Invoice')]

	use_dian_control = fields.Boolean('Use DIAN control resolutions', default=False)
	remaining_numbers = fields.Integer(default=1, help='Remaining numbers')
	remaining_days = fields.Integer(default=1, help='Remaining days')
	sequence_dian_type = fields.Selection(DIAN_TYPE, 'Type', required=True, default='invoice_computer_generated')
	dian_resolution_ids = fields.One2many('ir.sequence.dian_resolution', 'sequence_id', 'DIAN Resolutions')

	@api.model
	def check_active_resolution(self, sequence_id):    
		dian_resolutions_sequences_ids = self.search([('use_dian_control', '=', True),('id', '=', sequence_id)])
		for record in dian_resolutions_sequences_ids:
			if record:
				if len( record.dian_resolution_ids ) > 1:
					actual_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
					for resolution in record.dian_resolution_ids:
						if resolution.number_next_actual >= resolution.number_from and resolution.number_next_actual <= resolution.number_to and  actual_date <= resolution.date_to:
							self.check_active_resolution_cron()
							return True
		return False

	@api.model
	def check_active_resolution_cron(self):
		dian_resolutions_sequences_ids = self.search([('use_dian_control', '=', True)])
		for record in dian_resolutions_sequences_ids:
			if record:
				if len( record.dian_resolution_ids ) > 1:
					actual_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
					_active_resolution = False
					for resolution in record.dian_resolution_ids:
						if resolution.number_next_actual >= resolution.number_from and resolution.number_next_actual <= resolution.number_to and  actual_date <= resolution.date_to and resolution.active_resolution:
							continue
					_active_resolution = False
					for resolution in record.dian_resolution_ids:
						if _active_resolution:
							continue
						if resolution.number_next_actual >= resolution.number_from and resolution.number_next_actual <= resolution.number_to and  actual_date <= resolution.date_to:
							record.dian_resolution_ids.write({
								'active_resolution' : False
							})
							resolution.write({
									'active_resolution' : True        
							}) 
							_active_resolution = True                           

	def _next(self, sequence_date=None):
		if not self.use_dian_control:
			return super(IrSequenceInherit, self)._next(sequence_date=sequence_date)
		seq_dian_actual = self.env['ir.sequence.dian_resolution'].search([('sequence_id','=',self.id),('active_resolution','=',True)], limit=1)
		if seq_dian_actual.exists(): 
			number_actual = seq_dian_actual._next()
			if seq_dian_actual['number_next']-1 > seq_dian_actual['number_to']:
				seq_dian_next = self.env['ir.sequence.dian_resolution'].search([('sequence_id','=',self.id),('active_resolution','=',True)], limit=1, offset=1)
				if seq_dian_next.exists():
					seq_dian_actual.active_resolution = False
					return seq_dian_next._next()
			return number_actual
		return super(IrSequenceInherit, self)._next(sequence_date=sequence_date)

	@api.constrains('dian_resolution_ids')   
	def val_active_resolution(self):  
		_active_resolution = 0
		if self.use_dian_control:
			for record in self.dian_resolution_ids:
				if record.active_resolution:
					_active_resolution += 1
			if _active_resolution > 1:
				raise ValidationError( _('The system needs only one active DIAN resolution') )
			if _active_resolution == 0:
				raise ValidationError( _('The system needs at least one active DIAN resolution') )

class IrSequenceDianResolution(models.Model):
    _name = 'ir.sequence.dian_resolution'
    _rec_name = "sequence_id"
    _description = "Ir Sequence For Dian"

    def _get_number_next_actual(self):
        for element in self:
            element.number_next_actual = element.number_next

    def _set_number_next_actual(self):
        for record in self:
            record.write({'number_next': record.number_next_actual or 0})

    @api.depends('number_from')
    def _get_initial_number(self):
        for record in self:
            if not record.number_next:
                record.number_next = record.number_from

    resolution_number = fields.Char('Resolution number', required=True)
    date_from = fields.Date('From', required=True)
    date_to = fields.Date('To', required=True)
    number_from = fields.Integer('Initial number', required=True)
    number_to = fields.Integer('Final number', required=True)
    number_next = fields.Integer('Next Number', compute='_get_initial_number', store=True)
    number_next_actual = fields.Integer(compute='_get_number_next_actual', inverse='_set_number_next_actual',
                                        string='Next Number Actual', required=True, default=1,
                                        help="Next number of this sequence")
    active_resolution = fields.Boolean('Active resolution', required=False, default=False)
    sequence_id = fields.Many2one("ir.sequence", 'Main Sequence', required=True, ondelete='cascade')

    def _next(self):
        number_next = _update_nogap(self, 1)
        return self.sequence_id.get_next_char(number_next)


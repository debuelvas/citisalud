from odoo import api, fields, models,  _
from odoo.exceptions import RedirectWarning, UserError, ValidationError, AccessError
from odoo.tools import float_compare, float_is_zero, date_utils, email_split, email_re, html_escape, is_html_empty
from odoo.tools.misc import formatLang, format_date, get_lang
from odoo.osv import expression
import logging
from datetime import date, timedelta
from collections import defaultdict
from contextlib import contextmanager
from itertools import zip_longest
from hashlib import sha256
from json import dumps
from psycopg2 import sql
from psycopg2.extras import Json 
import ast
import json
import re
import warnings

def calc_check_digits(number):
    """Calculate the extra digits that should be appended to the number to make it a valid number.
    Source: python-stdnum iso7064.mod_97_10.calc_check_digits
    """
    number_base10 = ''.join(str(int(x, 36)) for x in number)
    checksum = int(number_base10) % 97
    return '%02d' % ((98 - 100 * checksum) % 97)
class Hr_payslip(models.Model):
    _name  = 'hr.payslip'
    _inherit = ['hr.payslip', 'sequence.mixin']
    _sequence_field = "number"
    _sequence_date_field = "date_to"
    _sequence_index = 'sequence_prefix'
    _sequence_fixed_regex = r'^(?P<prefix1>.*?)(?P<seq>\d*)(?P<suffix>\D*?)$'
    
    def convert_tuples_to_dict(self,tuple_list):
        data_list = ast.literal_eval(tuple_list)
        return data_list
    
    def days_between(self,start_date,end_date):
        s1, e1 =  start_date , end_date + timedelta(days=1)
        s360 = (s1.year * 12 + s1.month) * 30 + s1.day
        e360 = (e1.year * 12 + e1.month) * 30 + e1.day
        res = divmod(e360 - s360, 30)
        return ((res[0] * 30) + res[1]) or 0   
    
    @api.depends('struct_id', 'struct_id.process', 'credit_note')
    def _compute_sequence_prefix(self):
        """Compute sequence prefix based on payslip type"""
        for slip in self:
            if slip.struct_id and slip.struct_id.process:
                prefix_map = {
                    'nomina': 'NOM' if not slip.credit_note else 'RNOM',
                    'vacaciones': 'VAC' if not slip.credit_note else 'RVAC',
                    'prima': 'PRI' if not slip.credit_note else 'RPRI',
                    'cesantias': 'CES' if not slip.credit_note else 'RCES',
                    'contrato': 'LIQ' if not slip.credit_note else 'RLIQ',
                    'intereses_cesantias': 'INT' if not slip.credit_note else 'RINT',
                    'otro': 'OTR' if not slip.credit_note else 'ROTR'
                }
                slip.sequence_prefix = f"{prefix_map.get(slip.struct_id.process, 'OTR')}-"
            else:
                slip.sequence_prefix = 'OTR-'

    @api.depends('struct_id', 'struct_id.process', 'credit_note')
    def _compute_move_type(self):
        """Compute move_type based on structure process and reversal status"""
        for slip in self:
            if slip.struct_id:
                process = slip.struct_id.process
                if process == 'nomina':
                    slip.move_type = 'r_payroll' if slip.credit_note else 'payroll'
                elif process == 'vacaciones':
                    slip.move_type = 'r_vacaciones' if slip.credit_note else 'vacaciones'
                elif process == 'prima':
                    slip.move_type = 'r_prima' if slip.credit_note else 'prima'
                elif process == 'cesantias':
                    slip.move_type = 'r_cesantias' if slip.credit_note else 'cesantias'
                elif process == 'contrato':
                    slip.move_type = 'r_liquidacion' if slip.credit_note else 'liquidacion'
                else:
                    slip.move_type = 'r_otros' if slip.credit_note else 'otros'
            else:
                slip.move_type = 'r_payroll' if slip.credit_note else 'payroll'
    
    move_type = fields.Selection([
        ('payroll', 'Nomina'),
        ('prima', 'Prima'),
        ('cesantias', 'Cesantias'),
        ('vacaciones', 'Vacaciones'),
        ('liquidacion', 'Liquidacion Final'),
        ('otros', 'Otros'),
        ('r_payroll', 'Reversion de Nomina'),
        ('r_prima', 'Reversion Prima'),
        ('r_cesantias', 'Reversion Cesantias'),
        ('r_vacaciones', 'Reversion Vacaciones'),
        ('r_liquidacion', 'Reversion Liquidacion'),
        ('r_otros', 'Reversion Otros')
    ], string='Tipo de documento', compute='_compute_move_type', store=True)
    number = fields.Char(string='Reference', required=True, copy=False, readonly=True, default='/')
    reversed_slip_id = fields.Many2one('hr.payslip', string='Reversed Payslip', readonly=True, copy=False)
    sequence_prefix = fields.Char(compute='_compute_sequence_prefix', store=True)
    sequence_number = fields.Integer(compute='_compute_split_sequence', store=True)

    def init(self):
        if not self._abstract and self._sequence_index:
            index_name = self._table + '_sequence_index'
            self.env.cr.execute('SELECT indexname FROM pg_indexes WHERE indexname = %s', (index_name,))
            if not self.env.cr.fetchone():
                self.env.cr.execute(sql.SQL("""
                    CREATE INDEX {index_name} ON {table} ({sequence_index}, sequence_prefix desc, sequence_number desc, {field});
                    CREATE INDEX {index2_name} ON {table} ({sequence_index}, id desc, sequence_prefix);
                """).format(
                    sequence_index=sql.Identifier(self._sequence_index),
                    index_name=sql.Identifier(index_name),
                    index2_name=sql.Identifier(index_name + "2"),
                    table=sql.Identifier(self._table),
                    field=sql.Identifier(self._sequence_field),
                ))

    def _get_last_sequence_domain(self, relaxed=False):
        self.ensure_one()
        where_string = "WHERE sequence_prefix = %(sequence_prefix)s"
        param = {'sequence_prefix': self.sequence_prefix}
        return where_string, param

    def _get_starting_sequence(self):
        """ Returns the initial sequence for the given document type """
        self.ensure_one()
        return f"{self.sequence_prefix}00001"

    def _compute_split_sequence(self):
        """Compute the sequence number"""
        for record in self:
            sequence = record[record._sequence_field] or ''
            regex = re.sub(r"\?P<\w+>", "?:", record._sequence_fixed_regex.replace(r"?P<seq>", ""))
            matching = re.match(regex, sequence)
            if matching:
                record.sequence_number = int(matching.group(1) or 0)
            else:
                record.sequence_number = 0
    
    @api.depends('sequence_prefix', 'sequence_number')
    def _compute_name(self):
        """Compute the full name based on prefix and sequence number"""
        for record in self:
            if record.sequence_number:
                record.number = f'{record.sequence_prefix}{record.sequence_number:05d}'


    @api.constrains(lambda self: (self._sequence_field, self._sequence_date_field))
    def _constrains_date_sequence(self):
        return True

    def _sequence_matches_date(self):
        """Override to always return True since we don't use date in sequence"""
        return True
    
    def _set_next_sequence(self):
        """Set the next sequence.
        This method ensures that the sequence is set both in the ORM and in the database.
        """
        self.ensure_one()
        last_sequence = self._get_last_sequence()
        new = not last_sequence
        if new:
            last_sequence = self._get_starting_sequence()
        format_string = "{prefix1}{seq:05d}"
        sequence_number = 1
        if not new:
            match = re.match(self._sequence_fixed_regex, last_sequence)
            if match:
                sequence_number = int(match.group('seq') or 0) + 1
        self[self._sequence_field] = format_string.format(
            prefix1=self.sequence_prefix, 
            seq=sequence_number
        )
        self._compute_split_sequence()

    def _get_sequence_format_param(self, previous):
        """Get format parameters for the sequence"""
        if not previous or not re.match(self._sequence_fixed_regex, previous):
            return "{prefix1}{seq:05d}{suffix}", {
                'prefix1': self.sequence_prefix,
                'seq': 0,
                'seq_length': 5,
                'suffix': ''
            }

        format_values = re.match(self._sequence_fixed_regex, previous).groupdict()
        format_values['seq_length'] = 5
        format_values['seq'] = int(format_values.get('seq') or 0)
            
        if not format_values.get('prefix1'):
            format_values['prefix1'] = self.sequence_prefix
        if not format_values.get('suffix'):
            format_values['suffix'] = ''
                
        return "{prefix1}{seq:0{seq_length}d}{suffix}", format_values

    @api.onchange('struct_id', 'credit_note')
    def onchange_struct_id(self):
        """Update move_type when structure or reversal status changes"""
        self._compute_move_type()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('number', '/') == '/':
                vals['number'] = '/'
        return super().create(vals_list)

    def write(self, vals):
        """Handle sequence updates on write"""
        if 'struct_id' in vals or 'credit_note' in vals:
            self._compute_move_type()
        if vals.get(self._sequence_field):
            self._compute_split_sequence()
        return super().write(vals)

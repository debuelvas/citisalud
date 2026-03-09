from email.policy import default
from odoo import models, fields,api , _
import json
import logging
from collections import defaultdict
from datetime import datetime

from odoo.exceptions import ValidationError
from odoo.tools import formatLang
import json
from odoo.tools.misc import format_date
from odoo.tools import get_lang
from odoo.exceptions import UserError

from datetime import timedelta
from psycopg2.sql import SQL, Identifier, Placeholder
import logging
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools import float_round
from dateutil.relativedelta import relativedelta
_logger = logging.getLogger(__name__)

class AccountMove(models.Model):
    _inherit = "account.move"
    
    resolution_number = fields.Char("Resolution number in invoice")
    resolution_date = fields.Date(string="Resolution Date")
    resolution_date_to = fields.Date(string="Resolution Date To")
    resolution_number_from = fields.Char(string="Resolution  Number From")
    resolution_number_to = fields.Char(string="Resolution Number To")

    def validate_number_phone(self, data):
        """
            Funcion que es utilizada en el reporte de factura para retornar la información de:
                ->	Telefono
                ->	Celular
        """
        if data.phone and data.mobile:
            return data.phone + " - " + data.mobile
        if data.phone and not data.mobile:
            return data.phone
        if data.mobile and not data.phone:
            return data.mobile

    def validate_state_city(self, data):
        """
            Funcion que es utilizada en el reporte de factura para retornar la información de:
                ->	Pais
                ->	Departamento
                ->	Ciudad
        """
        return (
            ((data.country_id.name + " ") if data.country_id.name else " ")
            + (" " + (data.state_id.name + " ") if data.state_id.name else " ")
            + (" " + data.city_id.name if data.city_id.name else "")
        )


    def _post(self, soft=True):
        """
            Funcion que permite guardar los datos de la resolucion de la factura cuando esta es confirmada
        """
        result = super(AccountMove, self)._post(soft)
        for inv in self:
            sequence = self.env["ir.sequence.dian_resolution"].search(
                [
                    ("sequence_id", "=", self.journal_id.sequence_id.id),
                    ("active_resolution", "=", True),
                ],
                limit=1,
            )
            inv.resolution_number = sequence["resolution_number"]
            inv.resolution_date = sequence["date_from"]
            inv.resolution_date_to = sequence["date_to"]
            inv.resolution_number_from = sequence["number_from"]
            inv.resolution_number_to = sequence["number_to"]
        return result
class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

class TaxAdjustments(models.Model):
    _name = 'tax.adjustments.wizard'
    _description = 'Tax Adjustments Wizard'

    def _get_default_journal(self):
        return self.env['account.journal'].search([('type', '=', 'general')], limit=1).id

    reason = fields.Char(string='Justification')
    journal_id = fields.Many2one('account.journal', string='Journal', required=True, default=_get_default_journal, domain=[('type', '=', 'general')])
    date_from = fields.Date(required=True, default=fields.Date.context_today)
    date_to = fields.Date(required=True, default=fields.Date.context_today)
    debit_account_id = fields.Many2one('account.account', string='Debit account', required=True,
                                       domain="[('deprecated', '=', False)]")
    credit_account_id = fields.Many2one('account.account', string='Credit account', required=True,
                                        domain="[('deprecated', '=', False)]")
    debit_account_id_2 = fields.Many2one('account.account', string='Debit account', required=True,
                                       domain="[('deprecated', '=', False)]")
    credit_account_id_2 = fields.Many2one('account.account', string='Credit account', required=True,
                                        domain="[('deprecated', '=', False)]")
    amount = fields.Monetary(currency_field='company_currency_id', compute="_amount_ret", string="Provision de retencion de renta", required=True)
    amount_2 = fields.Monetary(currency_field='company_currency_id', compute="_amount_ret", string="Provision de retencion de autorrenta",  required=True)
    company_currency_id = fields.Many2one('res.currency', readonly=True, default=lambda x: x.env.company.currency_id)
    amount_ingresos = fields.Float(compute="_amount_all", store=True)
    amount_gastos = fields.Float(compute="_amount_all", store=True)
    amount_retenciones = fields.Float(compute="_amount_all", store=True)
    amount_exe = fields.Float(string="(%) exento")
    amount_ret = fields.Float(string="(%) retencion de renta", default=35)
    amount_autorrenta = fields.Float(string="(%) autorrenta", default=0.455)
    move_id = fields.Many2one(
        "account.move", string="Journal Entry", ondelete="set null"
    )

    @api.depends('date_from', 'date_to', 'amount_ret', 'amount_autorrenta', 'amount_ingresos', 'amount_gastos', 'amount_retenciones')
    def _amount_ret(self):
        for rec in self:
            rec.amount_2 = rec.amount_autorrenta * rec.amount_ingresos
            rec.amount = (rec.amount_ret/100) * (rec.amount_ingresos + rec.amount_gastos + rec.amount_retenciones)

    @api.depends('date_from', 'date_to')
    def _amount_all(self):
        """Optimizado: Usa read_group para calcular sumas sin cargar registros en memoria"""
        AccountMoveLine = self.env['account.move.line']

        for rec in self:
            if not rec.date_from or not rec.date_to:
                rec.amount_ingresos = 0.0
                rec.amount_gastos = 0.0
                rec.amount_retenciones = 0.0
                continue

            # Optimización: Usar read_group en lugar de search + sum
            # Ingresos
            ingresos_data = AccountMoveLine.read_group(
                domain=[
                    ('move_id.state', '=', 'posted'),
                    ('account_id.account_type', 'in', ['income', 'other_income']),
                    ('date', '>=', rec.date_from),
                    ('date', '<=', rec.date_to),
                ],
                fields=['balance:sum'],
                groupby=[]
            )
            rec.amount_ingresos = ingresos_data[0]['balance'] if ingresos_data else 0.0

            # Gastos
            gastos_data = AccountMoveLine.read_group(
                domain=[
                    ('move_id.state', '=', 'posted'),
                    ('account_id.account_type', 'in', ['expense_direct_cost', 'expense', 'expense_depreciation']),
                    ('date', '>=', rec.date_from),
                    ('date', '<=', rec.date_to),
                ],
                fields=['balance:sum'],
                groupby=[]
            )
            rec.amount_gastos = gastos_data[0]['balance'] if gastos_data else 0.0

            # Retenciones
            retencion_data = AccountMoveLine.read_group(
                domain=[
                    ('move_id.state', '=', 'posted'),
                    ('account_id.code', '=ilike', '135515'),
                    ('date', '>=', rec.date_from),
                    ('date', '<=', rec.date_to),
                ],
                fields=['balance:sum'],
                groupby=[]
            )
            rec.amount_retenciones = retencion_data[0]['balance'] if retencion_data else 0.0

    def create_move(self):
        move_line_vals = []

        # Vals for the amls corresponding to the ajustment tag
        move_line_vals.append((0, 0, {
            "partner_id": self.env.company.partner_id.id,
            'name': 'autorrenta' + str(self.date_to),
            'debit': abs(self.amount_2) or 0,
            'credit': 0,
            'account_id': self.debit_account_id.id,
        }))

        # Vals for the counterpart line
        move_line_vals.append((0, 0, {
            "partner_id": self.env.company.partner_id.id,
            'name': 'autorrenta' + str(self.date_to),
            'debit': 0,
            'credit': abs(self.amount_2) or 0,
            'account_id': self.credit_account_id.id,
        }))
        move_line_vals.append((0, 0, {
            "partner_id": self.env.company.partner_id.id,
            'name': 'Prov Renta' + str(self.date_to),
            'debit': abs(self.amount) or 0,
            'credit': 0,
            'account_id': self.debit_account_id_2.id,
        }))

        # Vals for the counterpart line
        move_line_vals.append((0, 0, {
            "partner_id": self.env.company.partner_id.id,
            'name': 'Prov Renta' + str(self.date_to),
            'debit': 0,
            'credit': abs(self.amount) or 0,
            'account_id': self.credit_account_id_2.id,
        }))
        # Create the move
        vals = {
            'journal_id': self.journal_id.id,
            'date': self.date_to,
            'line_ids': move_line_vals,
        }
        move = self.env['account.move'].create(vals)
        self.move_id = move.id
        move._post()

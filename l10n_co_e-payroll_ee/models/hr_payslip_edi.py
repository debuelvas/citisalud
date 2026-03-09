# -*- coding: utf-8 -*-

from odoo import fields, models, _ , api
from datetime import datetime, timedelta, date, time
from collections import defaultdict
import logging
import xmltodict
import re
_logger = logging.getLogger(__name__)

class HrPaySlip(models.Model):
    _name = 'hr.payslip.edi'
    _inherit = ['hr.payslip.edi', 'hr.payslip.abstract']

    nes_dev_line_ids = fields.One2many('hr.payslip.nes.line', 'slip_id2', string='Reglas Nomina Electronica', readonly=True)
    nes_ded_line_ids = fields.One2many('hr.payslip.nes.line.ded', 'slip_id2', string='Reglas Nomina Electronica', readonly=True)
    refusal_reason = fields.Text('Motivo/s de rechazo', compute="_compute_refusal")
    
    @api.depends('state_dian', 'xml_response_dian')
    def _compute_refusal(self):
        for rec in self:
            if rec.state_dian == 'rechazado':
                rec.refusal_reason = []
                pattern = r'<c:string>(.*?)<\/c:string>'
                matches = re.findall(pattern, rec.xml_response_dian)
                if matches:
                    rec.refusal_reason = matches
            else:
                rec.refusal_reason = []

    def get_field_move(self):
        if hasattr(self, 'partner_id'):
            return True
        elif hasattr(self, 'employee_id'):
            return False

    def hook_mail_template(self):
        return "l10n_co_e-payroll_ee.email_template_hr_payslip"

    def refund_sheet(self):
        for payslip in self:
            # dian_constants = self._get_dian_constants()
            # template_basic_data_nomina_individual_xml = self._template_nomina_individual(
            #     dian_constants
            # )
            # payslip.xml_sended = template_basic_data_nomina_individual_xml  
            # #payslip.current_cune = payslip.ZipKey 
            copied_payslip = payslip.copy(
                {"credit_note": True, "name": _("Refund: %s") % payslip.name}
            )
            number = copied_payslip.number or self.env["ir.sequence"].next_by_code(
                "salary.slip.note"
            )
            copied_payslip.write({"number": number, 'previous_cune': payslip.ZipKey, 'type_note': '2'})
            #payslip.pay_refund = copied_payslip.id
            #copied_payslip.compute_sheet()
            #copied_payslip.action_payslip_done()
        formview_ref = self.env.ref('epayroll.view_hr_payslip_edi_form', False)
        treeview_ref = self.env.ref('epayroll.view_hr_payslip_edi_tree', False)
        return {
            "name": ("Refund Payslip"),
            "view_mode": "tree, form",
            "view_id": False,
            "res_model": "hr.payslip.edi",
            "type": "ir.actions.act_window",
            "target": "current",
            "domain": "[('id', 'in', %s)]" % copied_payslip.ids,
            "views": [
                (treeview_ref and treeview_ref.id or False, "tree"),
                (formview_ref and formview_ref.id or False, "form"),
            ],
            "context": {},
        }

    def compute_sheet_nes(self):
        for payslip in self:
            payslip.nes_dev_line_ids.unlink()
            payslip.nes_ded_line_ids.unlink()
            line_obj = payslip.line_ids.filtered(lambda x: x.salary_rule_id.code not in ("TOTALDEV", "TOTALDED", "NET") and x.category_id.code != "COMP")
            devengos_dict = {}
            deducciones_dict = {}
            self.add_default_rules(payslip, devengos_dict, deducciones_dict)
            for line in line_obj:
                rule_id = line.salary_rule_id
                if rule_id.is_leave:
                    self.process_leave_rule(payslip, line, rule_id, devengos_dict)
                elif rule_id.devengado_rule_id:
                    self.process_devengo_rule(line, rule_id, devengos_dict)
                elif rule_id.deduccion_rule_id:
                    self.process_deduccion_rule(line, rule_id, deducciones_dict)
            self.create_nes_lines(payslip, devengos_dict, deducciones_dict)
            self.post_process_nes_lines(payslip)
            self.merge_nes_lines(payslip, 'hr.payslip.nes.line.ded')
            self.merge_nes_lines(payslip, 'hr.payslip.nes.line')
            self.state = 'verify'
        return True

    def merge_nes_lines(self, payslip, model):
        NesLine = self.env[model]
        read_group_result = NesLine.read_group(
            [('slip_id2', '=', payslip.id)],
            ['code', 'amount', 'quantity', 'total'],
            ['code']
        )
        for group in read_group_result:
            lines = NesLine.search([
                ('slip_id2', '=', payslip.id),
                ('code', '=', group['code'])
            ])
            if lines:
                main_line = lines[0]
                lines[1:].unlink()
                if model == 'hr.payslip.nes.line' and group['quantity'] > 1:
                    main_line.amount = group['total'] / group['quantity']
                else:
                    main_line.amount = group['amount']
                main_line.quantity = group['quantity']
                main_line.total = group['total']

    def add_default_rules(self, payslip, devengos_dict, deducciones_dict):
        default_rules = [
            ("Basico", "devengado_rule_id.code", "=", "Basico", devengos_dict, 1, 1),
            ("FondoPension", "deduccion_rule_id.code", "=", "FondoPension", deducciones_dict, 1, 1),
            ("Salud", "deduccion_rule_id.code", "=", "Salud", deducciones_dict, 1, 1)
        ]
        for rule_code, search_field, operator, search_value, target_dict, default_total, default_quantity in default_rules:
            if rule_code not in target_dict:
                rule = self.env['hr.salary.rule'].search([(search_field, operator, search_value)], limit=1)
                if rule:
                    target_dict[rule_code] = {
                        "salary_rule_id": rule.id,
                        "total": default_total,
                        "quantity": default_quantity,
                        "contract_id": payslip.contract_id.id,
                        "employee_id": payslip.employee_id.id,
                        "name": rule.name,
                        "code": rule.devengado_rule_id.code if rule.devengado_rule_id else  rule.deduccion_rule_id.code or 'NA',
                        "sequence": rule.devengado_rule_id.sequence  if rule.devengado_rule_id else rule.deduccion_rule_id.sequence,
                        "slip_id2": payslip.id,
                        "rate": 0 if rule_code == "Basico" else 4,
                    }

    def process_leave_rule(self, payslip, line, rule_id, devengos_dict):
        leave_days = payslip.payslip_ids.leave_days_ids.filtered(lambda l: l.rule_id.code == rule_id.code)
        if not leave_days:
            return

        total_days_payslip = sum(leave_days.mapped('days_payslip'))
        total_days_leave = sum(leave_days.mapped('days_assigned'))
        
        if total_days_payslip != total_days_leave:
            ratio = total_days_payslip / total_days_leave if total_days_leave else 0
        else:
            ratio = 1
        
        total_adjusted_days = 0
        total_amount = 0
        earliest_departure = min(leave_days.mapped('leave_id.date_from'))
        latest_return = max(leave_days.mapped('leave_id.date_to'))
        
        for leave_day in leave_days:
            adjusted_days = leave_day.days_payslip if ratio == 1 else leave_day.days_assigned * ratio
            amount_per_day = line.total / total_days_payslip if total_days_payslip else 0
            total_adjusted_days += adjusted_days
            total_amount += adjusted_days * amount_per_day
        
        leave_line = {
            "salary_rule_id": rule_id.id,
            "code": rule_id.devengado_rule_id.code,
            "total": total_amount,
            "quantity": total_adjusted_days,
            "amount": total_amount / total_adjusted_days if total_adjusted_days else 0,
            "contract_id": line.contract_id.id,
            "employee_id": line.employee_id.id,
            "name": line.name,
            "rate": line.rate,
            "slip_id2": payslip.id,
            "sequence": rule_id.devengado_rule_id.sequence,
            "leave_id": leave_days[0].leave_id.id,  # Using the first leave_id as reference
            "departure_date": earliest_departure,
            "return_date": latest_return,
        }
        
        key = f"{rule_id.code}"
        devengos_dict[key] = leave_line

    def process_devengo_rule(self, line, rule_id, devengos_dict):
        if rule_id.devengado_rule_id.parent_id and rule_id.devengado_rule_id.is_multi_rule:
            parent_code = rule_id.devengado_rule_id.parent_id.code
            current_code = rule_id.devengado_rule_id.code

            if parent_code in devengos_dict:
                if current_code == 'Cesantias':
                    devengos_dict[parent_code].update({
                        "total": line.total,
                        "code": current_code,
                        "salary_rule_id": rule_id.id,
                        "rate": line.rate,
                        "name": line.name,
                    })
                elif current_code == 'PagoIntereses':
                    devengos_dict[parent_code].update({
                        "total_2": line.total,
                        "code_2": current_code,
                        "salary_rule_id_2": rule_id.id,
                        "rate_2": line.rate,
                        "name_2": line.name,
                    })
            else:
                devengos_dict[parent_code] = {
                    "salary_rule_id": rule_id.id,
                    "code": parent_code,
                    "total": 0,
                    "quantity": line.quantity,
                    "amount": abs(line.amount),
                    "contract_id": line.contract_id.id,
                    "employee_id": line.employee_id.id,
                    "name": line.name,
                    "rate": line.rate,
                    "slip_id2": line.slip_id.id,
                    "sequence": rule_id.devengado_rule_id.sequence,
                    "salary_rule_id_2": None,
                    "total_2": 0,
                    "code_2": "",
                    "rate_2": 0,
                    "name_2": "",
                }
                
                if current_code == 'Cesantias':
                    devengos_dict[parent_code].update({
                        "total": line.total,
                        "code": current_code,
                        "salary_rule_id": rule_id.id,
                        "rate": line.rate,
                        "name": line.name,
                    })
                elif current_code == 'PagoIntereses':
                    devengos_dict[parent_code].update({
                        "total_2": line.total,
                        "code_2": current_code,
                        "salary_rule_id_2": rule_id.id,
                        "rate_2": line.rate,
                        "name_2": line.name,
                    })
        else:
            devengos_dict[rule_id.devengado_rule_id.code] = {
                "salary_rule_id": rule_id.id,
                "code": rule_id.devengado_rule_id.code,
                "total": line.total,
                "quantity": line.quantity,
                "amount": abs(line.amount),
                "contract_id": line.contract_id.id,
                "employee_id": line.employee_id.id,
                "name": line.name,
                "rate": line.rate,
                "slip_id2": line.slip_id.id,
                "sequence": rule_id.devengado_rule_id.sequence,
            }

        return devengos_dict

    def process_deduccion_rule(self, line, rule_id, deducciones_dict):
        if rule_id.deduccion_rule_id.parent_id:
            parent_code = rule_id.deduccion_rule_id.parent_id.code
            if parent_code in deducciones_dict:
                deducciones_dict[parent_code].update({
                    "total_2": abs(line.total),
                    "code_2": rule_id.deduccion_rule_id.code,
                    "salary_rule_id_2": rule_id.id,
                    "rate_2": line.rate,
                    "name_2": line.name,
                })
            else:
                deducciones_dict[parent_code] = {
                    "salary_rule_id": rule_id.id,
                    "code": parent_code,
                    "total": abs(line.total),
                    "amount": abs(line.amount),
                    "quantity": abs(line.quantity),
                    "contract_id": line.contract_id.id,
                    "employee_id": line.employee_id.id,
                    "name": line.name,
                    "rate": line.rate,
                    "slip_id2": line.slip_id.id,
                    "sequence": rule_id.deduccion_rule_id.sequence,
                    "salary_rule_id_2": rule_id.id,
                    "total_2": abs(line.total),
                    "code_2": rule_id.code,
                    "rate_2": line.rate,
                    "name_2": line.name,
                }
        else:
            deducciones_dict[rule_id.code] = {
                "salary_rule_id": rule_id.id,
                "code": rule_id.deduccion_rule_id.code,
                "total": abs(line.total),
                "quantity": abs(line.quantity),
                "amount": abs(line.amount),
                "contract_id": line.contract_id.id,
                "employee_id": line.employee_id.id,
                "name": line.name,
                "rate": abs(line.rate),
                "slip_id2": line.slip_id.id,
                "sequence": rule_id.deduccion_rule_id.sequence,
            }

    def create_nes_lines(self, payslip, devengos_dict, deducciones_dict):
        for dict_data, model in [(devengos_dict, 'hr.payslip.nes.line'), (deducciones_dict, 'hr.payslip.nes.line.ded')]:
            sorted_dict = dict(sorted(dict_data.items(), key=lambda item: item[1]["sequence"]))
            for value in sorted_dict.values():
                self.env[model].create(value)

    def post_process_nes_lines(self, payslip):
        for rec in payslip.nes_ded_line_ids:
            if rec.salary_rule_id.category_id.code == "SSOCIAL":
                rec.rate = payslip.get_porc_fsp(rec.salary_rule_id.code)
            if rec.salary_rule_id_2.category_id.code == "SSOCIAL":
                rec.rate_2 = payslip.get_porc_fsp(rec.salary_rule_id_2.code)

        for rec in payslip.nes_dev_line_ids:
            if rec.salary_rule_id_2.devengado_rule_id.code == "PagoIntereses" or rec.salary_rule_id.devengado_rule_id.code == "PagoIntereses":
                rec.rate_2 = 12
            if rec.salary_rule_id.devengado_rule_id.code == "Basico":
                rec.quantity = payslip.get_days_lines(["WORK100", "COMPENSATORIO", "WORK110"])
            if rec.salary_rule_id.category_id.code == "HEYREC":
                rec.rate = payslip.get_type_overtime(rec.salary_rule_id.id)

    def merge_lines_ded(self):
        read_group_result = self.env['hr.payslip.nes.line.ded'].read_group(
            [('slip_id2', '=', self.id)], 
            ['code', 'amount', 'quantity','total'], 
            ['code']
        )
        for order in read_group_result:
            line_ids = self.env['hr.payslip.nes.line.ded'].search(
                [('slip_id2', '=', self.id), 
                ('code', '=', order['code'])]
            )
            main_line = line_ids[0]
            line_ids[1:].unlink()
            main_line.amount = order['amount']
            main_line.quantity = order['quantity']
            main_line.quantity = order['total']

    def merge_lines_dev(self):
        read_group_result = self.env['hr.payslip.nes.line'].read_group(
            [('slip_id2', '=', self.id)], 
            ['code', 'amount', 'quantity','total'], 
            ['code']
        )
        for order in read_group_result:
            line_ids = self.env['hr.payslip.nes.line'].search(
                [('slip_id2', '=', self.id), 
                ('code', '=', order['code'])]
            )
            main_line = line_ids[0]
            line_ids[1:].unlink()
            if order['quantity'] > 1:
                main_line.amount = order['total'] / order['quantity']
            else:
                main_line.amount = order['amount']
            main_line.quantity = order['quantity']
            main_line.total = order['total']

    def get_days_lines(self,lst_codes):
        days = 0
        for payslip in self:
            for entries in payslip.worked_days_line_ids:
                days += entries.number_of_days if entries.work_entry_type_id.code in lst_codes else 0
        return int(days)

    def get_type_overtime(self,equivalence_number_ne):
        obj = self.env['hr.type.overtime'].search([('salary_rule.id', '=', equivalence_number_ne)], limit=1).percentage
        return obj

    def get_porc_fsp(self,code):
        porc = 0
        if code == "SSOCIAL001" or code == "SSOCIAL002":
            porc = 4
        annual_parameters = self.env['hr.annual.parameters'].search([('year', '=', self.date_to.year)])
        value_base = 0
        base_40 = 0
        value_base_no_dev = 0
        for payslip in self:
            for line in payslip.line_ids:
                value_base += abs(line.total) if line.salary_rule_id.category_id.code == 'DEV_SALARIAL' or line.salary_rule_id.category_id.parent_id.code == 'DEV_SALARIAL' else 0
                value_base_no_dev += abs(line.total) if line.salary_rule_id.category_id.code == 'DEV_NO_SALARIAL' or line.salary_rule_id.category_id.parent_id.code == 'DEV_NO_SALARIAL' else 0
        gran_total = value_base + value_base_no_dev 
        statute_value = gran_total*(annual_parameters.value_porc_statute_1395/100)
        total_statute = value_base_no_dev-statute_value 
        if total_statute > 0: 
            base_40 = total_statute 
        value_base = value_base + base_40
        if code == "SSOCIAL004":
            if (value_base / annual_parameters.smmlv_monthly) >= 4:
                porc = 0.5
        if code == "SSOCIAL003":
            if (value_base / annual_parameters.smmlv_monthly) >= 4 and (value_base / annual_parameters.smmlv_monthly) < 16 :
                porc = 0.5
            if (value_base / annual_parameters.smmlv_monthly) >= 16 and (value_base / annual_parameters.smmlv_monthly) <= 17:
                porc = 0.6
            if (value_base / annual_parameters.smmlv_monthly) > 17 and (value_base / annual_parameters.smmlv_monthly) <= 18:
                porc = 0.7
            if (value_base / annual_parameters.smmlv_monthly) > 18 and (value_base / annual_parameters.smmlv_monthly) <= 19:
                porc = 0.8
            if (value_base / annual_parameters.smmlv_monthly) > 19 and (value_base / annual_parameters.smmlv_monthly) <= 20:
                porc = 0.9
            if (value_base / annual_parameters.smmlv_monthly) > 20:
                porc = 1
        return porc
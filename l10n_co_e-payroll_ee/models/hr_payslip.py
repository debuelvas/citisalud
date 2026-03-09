# -*- coding: utf-8 -*-

from odoo import fields, models, _ , api
from datetime import datetime, timedelta, date, time
#from odoo.addons.hr_payroll.models.browsable_object import BrowsableObject, InputLine, WorkedDays, Payslips, ResultRules
from collections import defaultdict
import logging
import xmltodict
import re
_logger = logging.getLogger(__name__)

class HrPaySlip(models.Model):
    _name = 'hr.payslip'
    _inherit = ['hr.payslip', 'hr.payslip.abstract']



    nes_dev_line_ids = fields.One2many('hr.payslip.nes.line', 'slip_id', string='Reglas Nomina Electronica', readonly=True)
    nes_ded_line_ids = fields.One2many('hr.payslip.nes.line.ded', 'slip_id', string='Reglas Nomina Electronica', readonly=True)
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
            # payslip.current_cune = payslip.ZipKey 
            copied_payslip = payslip.copy(
                {"credit_note": True, "name": _("Refund: %s") % payslip.name}
            )
            number = copied_payslip.number or self.env["ir.sequence"].next_by_code(
                "salary.slip.note"
            )
            copied_payslip.write({"number": number, 'previous_cune': payslip.previous_cune, 'type_note': '2'})
            #payslip.pay_refund = copied_payslip.id
            copied_payslip.compute_sheet()
            copied_payslip.action_payslip_done()
        formview_ref = self.env.ref('hr_payroll.view_hr_payslip_form', False)
        treeview_ref = self.env.ref('hr_payroll.view_hr_payslip_tree', False)
        return {
            "name": ("Refund Payslip"),
            "view_mode": "tree, form",
            "view_id": False,
            "res_model": "hr.payslip",
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
            new_line_obj = self.env['hr.payslip.nes.line'] 
            new_line_obj_ded = self.env['hr.payslip.nes.line.ded'] 
            payslip.nes_dev_line_ids.unlink()
            payslip.nes_ded_line_ids.unlink()
            line_obj = self.line_ids.filtered(lambda x: x.salary_rule_id.code not in (
                "TOTALDEV", "TOTALDED", "NET",) and x.category_id.code != "COMP")

            # Crear los diccionarios vacíos
            devengos_dict = {}
            deducciones_dict = {}
            # Asegurarse de que salud y pension están en deducciones_dict
            Basico_deduccion = line_obj.filtered(
                lambda x: x.salary_rule_id.devengado_rule_id.code == "Basico") 
            rule_Basico = self.env['hr.salary.rule'].search([("devengado_rule_id.code","=","Basico")],limit=1)
            if not Basico_deduccion:
                devengos_dict["Basico"] = {
                    "salary_rule_id": rule_Basico.id,
                    "total": 1,
                    "quantity": 1,
                    "contract_id": payslip.contract_id.id,
                    "employee_id": payslip.employee_id.id,
                    "name": rule_Basico.name,
                    "code": rule_Basico.devengado_rule_id.code,
                    "sequence": rule_Basico.devengado_rule_id.sequence,
                    "slip_id": payslip.id,
                    "rate": 0,
                }
            ss_deduccion = line_obj.filtered(lambda x: x.salary_rule_id.code == "SSOCIAL001") 
            rule_ss = self.env['hr.salary.rule'].search([("code","=","SSOCIAL001")],limit=1)
            if not ss_deduccion:
                deducciones_dict["SSOCIAL001"] = {
                    "salary_rule_id": rule_ss.id,
                    "total": 0,
                    "quantity": 0,
                    "contract_id": payslip.contract_id.id,
                    "employee_id": payslip.employee_id.id,
                    "name": rule_ss.name,
                    "code": rule_ss.deduccion_rule_id.code,
                    "sequence": rule_ss.deduccion_rule_id.sequence,
                    "slip_id": payslip.id,
                    "rate": 4,
                }
            pp_deduccion = line_obj.filtered(
                lambda x: x.salary_rule_id.code == "SSOCIAL002")

            rule_ss = self.env['hr.salary.rule'].search([("code","=","SSOCIAL002")],limit=1)
            if not pp_deduccion:
                deducciones_dict["SSOCIAL002"] = {
                    "salary_rule_id": rule_ss.id,
                    "total": 0,
                    "quantity": 0,
                    "contract_id": payslip.contract_id.id,
                    "employee_id": payslip.employee_id.id,
                    "name": rule_ss.name,
                    "code": rule_ss.deduccion_rule_id.code,
                    "sequence": rule_ss.deduccion_rule_id.sequence,
                    "slip_id": payslip.id,
                    "rate": 4,
                }


            for line in line_obj:
                rule_id = line.salary_rule_id
                if rule_id.devengado_rule_id:
                    # Verificar si la regla tiene un padre
                    if rule_id.devengado_rule_id.parent_id and rule_id.devengado_rule_id.is_multi_rule:
                        parent_code = rule_id.devengado_rule_id.parent_id.code
                        if parent_code in devengos_dict:
                            parent_rule = devengos_dict[parent_code]
                            parent_rule["total_2"] = line.total
                            parent_rule["code_2"] = rule_id.devengado_rule_id.code
                            parent_rule["salary_rule_id_2"] = rule_id.id
                            parent_rule["rate_2"] = line.rate
                            parent_rule["name_2"] = line.name
                        else:
                            parent_rule = {
                                "salary_rule_id": rule_id.id,
                                "code": parent_code,
                                "total": line.total,
                                "quantity": line.quantity,
                                "amount": abs(line.amount),
                                "contract_id": line.contract_id.id,
                                "employee_id": line.employee_id.id,
                                "name": line.name,
                                "rate": line.rate,
                                "slip_id": payslip.id,
                                "sequence": rule_id.devengado_rule_id.sequence,
                                "salary_rule_id_2": rule_id.id,
                                "total_2": line.total,
                                "code_2": rule_id.devengado_rule_id.code,
                                "rate_2": line.rate,
                                "name_2": line.name,
                            }
                            devengos_dict[parent_code] = parent_rule
                    else:
                        # Agregar la línea al diccionario de devengos
                        devengos_dict[rule_id.code] = {
                            "salary_rule_id": rule_id.id,
                            "code": rule_id.devengado_rule_id.code,
                            "total": line.total,
                            "quantity": line.quantity,
                            "amount": abs(line.amount),
                            "contract_id": line.contract_id.id,
                            "employee_id": line.employee_id.id,
                            "name": line.name,
                            "rate": line.rate,
                            "slip_id": payslip.id,
                            "sequence": rule_id.devengado_rule_id.sequence,
                            "total_2": 0.0,
                            "code_2": "",
                            "rate_2": 0.0,
                            "name_2": "",
                        }
                elif rule_id.deduccion_rule_id:
                    # Verificar si la regla tiene un padre
                    if rule_id.deduccion_rule_id.parent_id:
                        parent_code = rule_id.deduccion_rule_id.parent_id.code
                        if parent_code in deducciones_dict:
                            parent_rule = deducciones_dict[parent_code]
                            parent_rule["total_2"] = abs(line.total)
                            parent_rule["code_2"] = rule_id.deduccion_rule_id.code
                            parent_rule["salary_rule_id_2"] = rule_id.id
                            parent_rule["rate_2"] = line.rate
                            parent_rule["name_2"] = line.name
                        else:
                            parent_rule = {
                                "salary_rule_id": rule_id.id,
                                "code": parent_code,
                                "total": abs(line.total),
                                "amount": abs(line.amount),
                                "quantity": abs(line.quantity),
                                "contract_id": line.contract_id.id,
                                "employee_id": line.employee_id.id,
                                "name": line.name,
                                "rate": line.rate,
                                "slip_id": payslip.id,
                                "sequence": rule_id.deduccion_rule_id.sequence,
                                "salary_rule_id_2": rule_id.id,
                                "total_2": abs(line.total),
                                "code_2": rule_id.code,
                                "rate_2": line.rate,
                                "name_2": line.name,
                            }
                            deducciones_dict[parent_code] = parent_rule
                    
                    else:
                        # Agregar la línea al diccionario de deducciones
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
                            "slip_id": payslip.id,
                            "sequence": rule_id.deduccion_rule_id.sequence,
                            "total_2": 0.0,
                            "code_2": "",
                            "rate_2": 0.0,
                            "name_2": "",
                        }
            devengos_dict = dict(sorted(devengos_dict.items(), key=lambda item: item[1]["sequence"]))
            deducciones_dict = dict(sorted(deducciones_dict.items(), key=lambda item: item[1]["sequence"]))
            merged_devengos_dict = defaultdict(dict)
            for key, value in devengos_dict.items():
                merged_devengos_dict[key].update(value)
                new_line_obj += self.env['hr.payslip.nes.line'].create(merged_devengos_dict[key])

            merged_deducciones_dict = defaultdict(dict)
            for key, value in deducciones_dict.items():
                merged_deducciones_dict[key].update(value)
                new_line_obj_ded += self.env['hr.payslip.nes.line.ded'].create(merged_deducciones_dict[key])
        
        for rec in payslip.nes_ded_line_ids:
            if rec.salary_rule_id.category_id.code == "SSOCIAL":
                rec.rate = payslip.get_porc_fsp(rec.salary_rule_id.code)
            if rec.salary_rule_id_2.category_id.code == "SSOCIAL":
                rec.rate_2 = payslip.get_porc_fsp(rec.salary_rule_id_2.code)
        for rec in payslip.nes_dev_line_ids:
            if rec.salary_rule_id_2.devengado_rule_id.code == "PagoIntereses" or rec.salary_rule_id.devengado_rule_id.code == "PagoIntereses":
                rec.rate_2 = 12
            if rec.salary_rule_id.devengado_rule_id.code == "Basico":
                rec.quantity =  payslip.get_days_lines(["WORK100", "COMPENSATORIO", "WORK110"])
            if rec.salary_rule_id.category_id.code == "HEYREC":
                rec.rate = payslip.get_type_overtime(rec.salary_rule_id.id)
        payslip.merge_lines_ded()
        payslip.merge_lines_dev()
        payslip.get_leave()

    def merge_lines_ded(self):
        read_group_result = self.env['hr.payslip.nes.line.ded'].read_group(
            [('slip_id', '=', self.id)], 
            ['code', 'amount', 'quantity','total'], 
            ['code']
        )
        for order in read_group_result:
            line_ids = self.env['hr.payslip.nes.line.ded'].search(
                [('slip_id', '=', self.id), 
                ('code', '=', order['code'])]
            )
            main_line = line_ids[0]
            line_ids[1:].unlink()
            main_line.amount = order['amount']
            main_line.quantity = order['quantity']
            main_line.quantity = order['total']

    def merge_lines_dev(self):
        read_group_result = self.env['hr.payslip.nes.line'].read_group(
            [('slip_id', '=', self.id)], 
            ['code', 'amount', 'quantity','total'], 
            ['code']
        )
        for order in read_group_result:
            line_ids = self.env['hr.payslip.nes.line'].search(
                [('slip_id', '=', self.id), 
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


    def get_leave(self):
        for rec in self:
            nes_dev_line_obj = self.env['hr.payslip.nes.line']
            for l in rec.leave_ids:
                rules_to_update = rec.nes_dev_line_ids.filtered(lambda we: we.salary_rule_id.leave_id.code == l.leave_id.holiday_status_id.code)

                for nes in rules_to_update:
                    if not nes.leave_id and nes.salary_rule_id.leave_id:
                        nes.write({
                            'quantity': l.total_days,
                            'total': l.total_days * nes.amount,
                            'leave_id': l.leave_id.id,
                        })
                        rules_to_update -= nes
                        break
                
                for nes in rules_to_update:
                    if  nes.salary_rule_id.leave_id:
                        nes_dev_line_obj.create({
                            "salary_rule_id": nes.salary_rule_id.id,
                            "code": nes.code,
                            "name": nes.name,
                            "leave_id": l.leave_id.id,
                            "contract_id": rec.contract_id.id,
                            "employee_id": rec.employee_id.id,
                            "sequence": nes.sequence,
                            "slip_id": rec.id,
                            "quantity": l.total_days,
                            "total": l.total_days * nes.amount,
                        })
                        break
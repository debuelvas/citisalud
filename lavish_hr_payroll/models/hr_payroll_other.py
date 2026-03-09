from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from .browsable_object import BrowsableObject, InputLine, WorkedDays, Payslips
from odoo.tools import float_compare, float_is_zero

from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

class Hr_payslip(models.Model):
    _inherit = 'hr.payslip'

    def _get_payslip_lines_other(self,inherit_contrato=0,localdict=None):
        def _sum_salary_rule_category(localdict, category, amount):
            if category.parent_id:
                localdict = _sum_salary_rule_category(localdict, category.parent_id, amount)
            localdict['categories'].dict[category.code] = localdict['categories'].dict.get(category.code, 0) + amount
            return localdict

        def _sum_salary_rule(localdict, rule, amount):
            localdict['rules_computed'].dict[rule.code] = localdict['rules_computed'].dict.get(rule.code, 0) + amount
            return localdict

        self.ensure_one()
        result = {}
        rules_dict = {}
        worked_days_dict = {line.code: line for line in self.worked_days_line_ids if line.code}
        inputs_dict = {line.code: line for line in self.input_line_ids if line.code}
        round_payroll = bool(self.env['ir.config_parameter'].sudo().get_param('lavish_hr_payroll.round_payroll')) or False

        employee = self.employee_id
        contract = self.contract_id

        year = self.date_from.year
        annual_parameters = self.env['hr.annual.parameters'].search([('year', '=', year)])

        if localdict == None:
            localdict = {
                **self._get_base_local_dict(),
                **{
                    'categories': BrowsableObject(employee.id, {}, self.env),
                    'rules_computed': BrowsableObject(employee.id, {}, self.env),
                    'rules': BrowsableObject(employee.id, rules_dict, self.env),
                    'payslip': Payslips(employee.id, self, self.env),
                    'worked_days': WorkedDays(employee.id, worked_days_dict, self.env),
                    'inputs': InputLine(employee.id, inputs_dict, self.env),
                    'employee': employee,
                    'contract': contract,
                    'annual_parameters': annual_parameters,
                    'inherit_contrato': inherit_contrato,
                }
            }
        else:
            localdict.update({
                'inherit_contrato': inherit_contrato, })

        # Cargar novedades independientes
        obj_novelties = self.env['hr.novelties.independents'].search([('employee_id', '=', employee.id),
                                                                            ('date', '>=', self.date_from),
                                                                            ('date', '<=', self.date_to)])
        for concepts in obj_novelties:
            if concepts.amount != 0:
                previous_amount = concepts.salary_rule_id.code in localdict and localdict[
                    concepts.salary_rule_id.code] or 0.0
                # set/overwrite the amount computed for this rule in the localdict
                tot_rule = round(concepts.amount * 1.0 * 100 / 100.0, 0) if round_payroll == False else concepts.amount * 1.0 * 100 / 100.0

                localdict[concepts.salary_rule_id.code + '-INDEPENDIENTE'] = tot_rule
                rules_dict[concepts.salary_rule_id.code + '-INDEPENDIENTE'] = concepts.salary_rule_id
                # sum the amount for its salary category
                localdict = _sum_salary_rule_category(localdict, concepts.salary_rule_id.category_id,
                                                      tot_rule - previous_amount)
                localdict = _sum_salary_rule(localdict, concepts.salary_rule_id, tot_rule)

                if tot_rule != 0:
                    result_item = concepts.salary_rule_id.code + '-INDEPENDIENTE' + str(concepts.id)
                    result[result_item] = {
                        'sequence': concepts.salary_rule_id.sequence,
                        'code': concepts.salary_rule_id.code,
                        'name': concepts.salary_rule_id.name,
                        'note': concepts.salary_rule_id.note,
                        'salary_rule_id': concepts.salary_rule_id.id,
                        'contract_id': contract.id,
                        'employee_id': employee.id,
                        'amount': tot_rule,
                        'quantity': 1.0,
                        'rate': 100,
                        'total': tot_rule,
                        'slip_id': self.id,
                    }
        #Ejecutar reglas salariales estandar para este modelo no se tiene en cuenta la pestaña de Devengos y deducciones del contrato
        for rule in sorted(self.struct_id.rule_ids, key=lambda x: x.sequence):
            localdict.update({
                'result': None,
                'result_qty': 1.0,
                'result_rate': 100})
            if rule._satisfy_condition(localdict):
                amount, qty, rate, name,log,data = rule._compute_rule(localdict)
                #check if there is already a rule computed with that code
                previous_amount = rule.code in localdict and localdict[rule.code] or 0.0
                #set/overwrite the amount computed for this rule in the localdict
                tot_rule = amount * qty * rate / 100.0
                localdict[rule.code] = tot_rule
                rules_dict[rule.code] = rule
                # sum the amount for its salary category
                localdict = _sum_salary_rule_category(localdict, rule.category_id, tot_rule - previous_amount)
                localdict = _sum_salary_rule(localdict, rule, tot_rule)
                # create/overwrite the rule in the temporary results
                if amount != 0:
                    result[rule.code] = {
                        'sequence': rule.sequence,
                        'code': rule.code,
                        'name': rule.name,
                        'note': rule.note,
                        'salary_rule_id': rule.id,
                        'contract_id': contract.id,
                        'employee_id': employee.id,
                        'amount': amount,
                        'quantity': qty,
                        'rate': rate,
                        'total': tot_rule,
                        'slip_id': self.id,
                    }
        return result.values()
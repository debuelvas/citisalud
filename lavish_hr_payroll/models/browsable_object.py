#-*- coding:utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from dateutil.relativedelta import relativedelta
from odoo import fields
import math
from datetime import date, datetime, time, timedelta
from json import JSONEncoder

from odoo import fields, models
import logging
_logger= logging.getLogger(__name__)
lr = [0, 1, 100]
BROWSABLE_OBJECT_SAFE_CLASSES = (models.BaseModel, set, datetime, date, time)
class BrowsableObject(object):
    def __init__(self, employee_id, dict, env):
        self.employee_id = employee_id
        self.dict = dict
        self.env = env

    def __getattr__(self, attr):
        return attr in self.dict and self.dict.__getitem__(attr) or 0.0
class ValueChecker(JSONEncoder):
    def default(self, value):
        if isinstance(value, BROWSABLE_OBJECT_SAFE_CLASSES):
            return repr(value)
        return super().default(value)

    def check(self, value):
        self.encode(value)

valueChecker = ValueChecker()

class ResultRules_co(BrowsableObject):
    def __getattr__(self, attr):
        value = None
        if attr in self.dict:
            value = self.dict.__getitem__(attr)
        valueChecker.check(value)
        return value or {'total': 0, 'amount': 0, 'quantity': 0, 'base_seguridad_social':False, 'base_prima':False, 'base_cesantias':False,  'base_vacaciones':False,'base_vacaciones_dinero':False}

    def __getitem__(self, key):
        return self.dict[key] if key in self.dict else {'total': 0, 'amount': 0, 'quantity': 0, 'base_seguridad_social':False, 'base_prima':False, 'base_cesantias':False,  'base_vacaciones':False,'base_vacaciones_dinero':False}



class ResultRules(BrowsableObject):
    def __getattr__(self, attr):
        return attr in self.dict and self.dict.__getitem__(attr) or {'total': 0, 'amount': 0, 'quantity': 0}

    def __getitem__(self, key):
        return self.dict[key] if key in self.dict else {'total': 0, 'amount': 0, 'quantity': 0}
class InputLine(BrowsableObject):
    """a class that will be used into the python code, mainly for usability purposes"""
    def sum(self, code, from_date, to_date=None):
        if to_date is None:
            to_date = fields.Date.today()
        self.env.cr.execute("""
            SELECT sum(amount) as sum
            FROM hr_payslip as hp, hr_payslip_input as pi
            WHERE hp.employee_id = %s AND hp.state in ('done','paid')
            AND hp.date_from >= %s AND hp.date_to <= %s AND hp.id = pi.payslip_id AND pi.code = %s""",
            (self.employee_id, from_date, to_date, code))
        return self.env.cr.fetchone()[0] or 0.0

class LeavedDays(BrowsableObject):
    """a class that will be used into the python code, mainly for usability purposes"""
    def _sum(self, code, from_date, to_date=None):
        if to_date is None:
            to_date = fields.Date.today()
        self.env.cr.execute("""
            SELECT sum(days_used) as days_used, sum(days) as days, sum(total_days) as days, 
            FROM hr_payslip as hp, hr_absence_days as pi
            WHERE hp.employee_id = %s AND hp.state in ('done','paid')
            AND hp.date_from >= %s AND hp.date_to <= %s AND hp.id = pi.payroll_id AND pi.work_entry_type_id IN (SELECT id FROM hr_work_entry_type WHERE code = %s)""",
            (self.employee_id, from_date, to_date, code))
        return self.env.cr.fetchone()

    def sum(self, code, from_date, to_date=None):
        res = self._sum(code, from_date, to_date)
        return res and res[0] or 0.0

    def sum_hours(self, code, from_date, to_date=None):
        res = self._sum(code, from_date, to_date)
        return res and res[1] or 0.0

    def sum_total(self, code, from_date, to_date=None):
        res = self._sum(code, from_date, to_date)
        return res and res[1] or 0.0

class WorkedDays(BrowsableObject):
    """a class that will be used into the python code, mainly for usability purposes"""
    def _sum(self, code, from_date, to_date=None):
        if to_date is None:
            to_date = fields.Date.today()
        self.env.cr.execute("""
            SELECT sum(number_of_days) as number_of_days, sum(number_of_hours) as number_of_hours
            FROM hr_payslip as hp, hr_payslip_worked_days as pi
            WHERE hp.employee_id = %s AND hp.state in ('done','paid')
            AND hp.date_from >= %s AND hp.date_to <= %s AND hp.id = pi.payslip_id AND pi.code = %s""",
            (self.employee_id, from_date, to_date, code))
        return self.env.cr.fetchone()

    def sum(self, code, from_date, to_date=None):
        res = self._sum(code, from_date, to_date)
        return res and res[0] or 0.0

    def sum_hours(self, code, from_date, to_date=None):
        res = self._sum(code, from_date, to_date)
        return res and res[1] or 0.0

class Payslips(BrowsableObject):
    """a class that will be used into the python code, mainly for usability purposes"""

    def roundup100(self,amount):
        if amount < 0:
            return (math.ceil(abs(amount) / 100.0) * 100)*-1
        else:
            return math.ceil(amount / 100.0) * 100

    def roundupdecimal(self,amount):
        if amount < 0:
            return (math.ceil(abs(amount)))*-1
        else:
            return math.ceil(amount)

    def sum(self, code, from_date, to_date=None):
        if to_date is None:
            to_date = fields.Date.today()
        self.env.cr.execute("""SELECT sum(case when hp.credit_note IS NOT TRUE then (pl.total) else (-pl.total) end)
                    FROM hr_payslip as hp, hr_payslip_line as pl
                    WHERE hp.employee_id = %s AND hp.state in ('done','paid')
                    AND hp.date_from >= %s AND hp.date_to <= %s AND hp.id = pl.slip_id AND pl.code = %s""",
                    (self.employee_id, from_date, to_date, code))
        res = self.env.cr.fetchone()
        return res and res[0] or 0.0

    def rule_parameter(self, code):
        return self.env['hr.rule.parameter']._get_parameter_from_code(code, self.dict.date_to)

    def sum_category(self, code, from_date, to_date=None):
        if to_date is None:
            to_date = fields.Date.today()

        self.env['hr.payslip'].flush(['credit_note', 'employee_id', 'state', 'date_from', 'date_to'])
        self.env['hr.payslip.line'].flush(['total', 'slip_id', 'category_id'])
        self.env['hr.salary.rule.category'].flush(['code'])

        self.env.cr.execute("""SELECT sum(case when hp.credit_note is not True then (pl.total) else (-pl.total) end)
                    FROM hr_payslip as hp, hr_payslip_line as pl, hr_salary_rule_category as rc
                    WHERE hp.employee_id = %s AND hp.state in ('done','paid')
                    AND hp.date_from >= %s AND hp.date_to <= %s AND hp.id = pl.slip_id
                    AND rc.id = pl.category_id AND rc.code = %s""",
                    (self.employee_id, from_date, to_date, code))
        res = self.env.cr.fetchone()
        return res and res[0] or 0.0
    
    #-----------------------------------------INICIO Código Localización colombiana lavish------------------------------------------------------

    #Retorna la cantidad de dias de diferencia entre dos fecha con la funcion dias360
    def days_between(self,start_date,end_date):
        s1, e1 =  start_date , end_date + timedelta(days=1)
        #Convert to 360 days
        s360 = (s1.year * 12 + s1.month) * 30 + s1.day
        e360 = (e1.year * 12 + e1.month) * 30 + e1.day
        #Count days between the two 360 dates and return tuple (months, days)
        res = divmod(e360 - s360, 30)
        return ((res[0] * 30) + res[1]) or 0

    #Retorna la suma por categoria valor mensual
    def sum_mount(self, code, from_date, to_date):
        from_month = from_date.month
        from_year = from_date.year

        to_month = to_date.month + 1 if to_date.month != 12 else 1
        to_year = to_date.year + 1 if to_date.month == 12 else to_date.year

        self.env.cr.execute("""SELECT COALESCE(sum(pl.total),0) AS suma 
                            FROM hr_payslip AS hp 
                            INNER JOIN hr_payslip_line AS pl ON hp.id = pl.slip_id 
                            INNER JOIN hr_salary_rule_category hc ON pl.category_id = hc.id 
                            LEFT JOIN hr_salary_rule_category hc_parent ON hc.parent_id = hc_parent.id 
                            WHERE hp.state IN ('done', 'paid') 
                                AND hp.contract_id = %s 
                                AND hp.date_from >= '%s-%s-01' 
                                AND hp.date_to < '%s-%s-01'
                                AND (hc.code = %s OR hc_parent.code = %s)""",
                            (self.contract_id.id, from_year, from_month, to_year, to_month, code, code))
        res = self.env.cr.fetchone()
        
        return res[0] if res else 0.0

    #Retorna la suma por regla - valor mensual
    def sum_mount_x_rule(self, code, from_date, to_date):
        from_month = from_date.month
        from_year = from_date.year

        to_month = to_date.month + 1 if to_date.month != 12 else 1
        to_year = to_date.year + 1 if to_date.month == 12 else to_date.year
        
        self.env.cr.execute("""Select COALESCE(sum(pl.total),0) as suma FROM hr_payslip as hp 
                            Inner Join hr_payslip_line as pl on  hp.id = pl.slip_id 
                            Inner Join hr_salary_rule hc on pl.salary_rule_id = hc.id 
                            WHERE hp.state in ('done','paid') and hp.contract_id = %s AND hp.date_from >= '%s-%s-01' AND hp.date_from < '%s-%s-01'  
                            AND hc.code = %s""",
                    (self.contract_id.id, from_year, from_month, to_year, to_month, code))
        res = self.env.cr.fetchone()

        return res and res[0] or 0.0

    def sum_mount_rule_before(self, code, from_date):
        date_start = from_date
        mes = date_start.month -1
        ano = date_start.year
        if mes == 0:
            mes = 12
            ano = ano - 1

        dia = 30
        if mes == 2:
            dia = 28
        
        from_date = str(ano)+'-'+str(mes)+'-01'
        to_date = str(ano)+'-'+str(mes)+'-'+str(dia)

        self.env.cr.execute("""Select COALESCE(sum(pl.total),0) as suma FROM hr_payslip as hp 
                            Inner Join hr_payslip_line as pl on  hp.id = pl.slip_id 
                            Inner Join hr_salary_rule hc on pl.salary_rule_id = hc.id 
                            WHERE hp.state in ('done','paid') and hp.contract_id = %s AND hp.date_from >= %s AND hp.date_to <= %s
                            AND hc.code = %s """,
                    (self.contract_id.id, from_date, to_date,code))
        res = self.env.cr.fetchone()

        return res and res[0] or 0.0
    #Retorna la suma por categoria valor mensual mes anterior
    def sum_mount_before(self, code, from_date):
        date_start = from_date
        mes = date_start.month -1
        ano = date_start.year
        if mes == 0:
            mes = 12
            ano = ano - 1

        dia = 30
        if mes == 2:
            dia = 28
        
        from_date = str(ano)+'-'+str(mes)+'-01'
        to_date = str(ano)+'-'+str(mes)+'-'+str(dia)

        self.env.cr.execute("""Select COALESCE(sum(pl.total),0) as suma FROM hr_payslip as hp 
                            Inner Join hr_payslip_line as pl on  hp.id = pl.slip_id 
                            Inner Join hr_salary_rule_category hc on pl.category_id = hc.id 
                            LEFT Join hr_salary_rule_category hc_parent on hc.parent_id = hc_parent.id 
                            WHERE hp.state in ('done','paid') and hp.contract_id = %s AND hp.date_from >= %s AND hp.date_to <= %s
                            AND (hc.code = %s OR hc_parent.code = %s)""",
                    (self.contract_id.id, from_date, to_date, code, code))
        res = self.env.cr.fetchone()

        return res and res[0] or 0.0

    #Calcula los dias efectivamente trabajado en el rango de fecha dado
    def sum_days_works(self, code_work_entry_type, from_date, to_date):
        from_month = from_date.month
        from_year = from_date.year

        to_month = to_date.month + 1 if to_date.month != 12 else 1
        to_year = to_date.year + 1 if to_date.month == 12 else to_date.year
        
        self.env.cr.execute("""Select coalesce(number_of_days,0) as dias from hr_payslip_worked_days hd
                                    Inner Join hr_payslip as hp on hp.id = hd.payslip_id and hp.state in ('done','paid')
                                    Inner Join hr_work_entry_type as wt on hd.work_entry_type_id = wt.id
                                    Where wt.code = %s AND hp.contract_id = %s
                                    AND hp.date_from >= '%s-%s-01' AND hp.date_to < '%s-%s-01'""",
                    (code_work_entry_type,self.contract_id.id, from_year, from_month, to_year, to_month))
        res = self.env.cr.fetchone()

        return res and res[0] or 0.0

    # Calcula los dias que son validos para seguridad social
    def sum_days_contribution_base(self, from_date, to_date):
        from_month = from_date.month
        from_year = from_date.year

        to_month = to_date.month + 1 if to_date.month != 12 else 1
        to_year = to_date.year + 1 if to_date.month == 12 else to_date.year

        self.env.cr.execute("""Select coalesce(number_of_days,0) as dias from hr_payslip_worked_days hd
    								Inner Join hr_payslip as hp on hp.id = hd.payslip_id and hp.state in ('done','paid')
    								Inner Join hr_work_entry_type as wt on hd.work_entry_type_id = wt.id
    								Where wt.not_contribution_base = False AND hp.contract_id = %s
    								AND hp.date_from >= '%s-%s-01' AND hp.date_to < '%s-%s-01'""",
                            (self.contract_id.id, from_year, from_month, to_year, to_month))
        res = self.env.cr.fetchone()

        return res and res[0] or 0.0

    #Retorna el objeto de la regla salarial
    def get_salary_rule(self, salary_rule_code, type_employee_id):
        res = self.env['hr.salary.rule'].search([('code', '=', salary_rule_code),('types_employee','in',[type_employee_id])])
        return res and res[0] or 0.0

    # Retorna el objeto de la regla salarial
    def get_parameterization_contributors(self):
        obj_employee = self.env['hr.employee'].search([('id','=',self.employee_id)])
        res = self.env['hr.parameterization.of.contributors'].search(
            [('type_of_contributor', '=', obj_employee.tipo_coti_id.id),
             ('contributor_subtype', '=', obj_employee.subtipo_coti_id.id)], limit=1)
        return res and res[0] or []

    #Retorna el valor a para calcular los cotizantes tipo 51
    def get_payroll_value_contributor_51(self,year,number_of_days):
        obj_employee = self.env['hr.employee'].search([('id', '=', self.employee_id)])
        value_contributor = obj_employee.tipo_coti_id.get_value_cotizante_51(year,number_of_days)
        return value_contributor or 0.0

    #Retorna el devengo o deduccion del contrato del empleado dependiendo la regla enviada
    def get_concepts(self, contract_id, input_id, id_contract_concepts=0):
        if id_contract_concepts == 0:
            res = self.env['hr.contract.concepts'].search([('contract_id', '=', contract_id),('input_id','=',input_id)])
        else:
            res = self.env['hr.contract.concepts'].search([('id','=',id_contract_concepts),('contract_id', '=', contract_id),('input_id','=',input_id)])
        return res and res[0] or 0.0
    
    #Retorna el devengo o deduccion del contrato del empleado dependiendo la regla enviada
    def get_deductions_rtf(self, contract_id, input_id):
        res = self.env['hr.contract.deductions.rtf'].search([('contract_id', '=', contract_id),('input_id','=',input_id)])
        return res and res[0] or 0.0

    #Retorna el tipo de de hora extra
    def get_type_overtime(self, salary_rule_id):
        res = self.env['hr.type.overtime'].search([('salary_rule', '=', salary_rule_id)])
        return res and res[0] or 0.0

    #Retorna las horas extra & los dias efectivamente laborados del empleado
    def get_overtime(self, employee_id, from_date, to_date, inherit_contrato = 0, aplicar = 0):
        if inherit_contrato == 0 and aplicar != 0:
            from_month = from_date.month
            from_year = from_date.year
            date = str(from_year)+'-'+str(from_month)+'-01'
        else:
            date = from_date
        if self.contract_id.not_pay_overtime:
            res = self.env['hr.overtime']
        else:
            res = self.env['hr.overtime'].search([('employee_id', '=', employee_id),('date','>=',date),('date_end','<=',to_date)])
        return res #and res[0] or 0.0
    
    #Retorna el objeto del tipo de ausencia
    def get_leave_type(self, code):
        res = self.env['hr.leave.type'].search([('code', '=', code)])
        return res and res[0] or 0.0

    #Retorna reglas tributarias del empleado asignadas en el contrato
    def get_contract_deductions_rtf(self, contract_id,to_date,code):
        #,('date_start', '>=', to_date),('date_end', '<=', to_date)
        res = self.env['hr.contract.deductions.rtf'].search([('contract_id', '=', contract_id),('input_id.code','=',code)])
        return res and res[0] or 0.0

    #Retorna el objeto para el calculo de la retención en la fuente
    def get_deduction_retention(self, employee_id,to_date,type_tax,localdict):
        #Se crea el Encabezado
        data = {
            'employee_id': employee_id,
            'year': to_date.year,
            'month': to_date.month,
            'type_tax': self.env['hr.type.tax.retention'].search([('code', '=', type_tax)],limit=1).id,
        } 
        encab = self.env['hr.employee.rtefte'].create(data)

        #Se llama la tabla de retención
        obj_retention = self.env['hr.concepts.deduction.retention'].search([('type_tax.code', '=', type_tax)])
        max_order = 0
        for retention in obj_retention:
            exec_retention = self.env['hr.concepts.deduction.retention'].search([('id', '=', retention.id)])
            exec_retention._loop_python_code(localdict,encab.id)
            max_order = retention.order
        
        res = self.env['hr.employee.deduction.retention'].search([('employee_id', '=', employee_id),('year', '=', to_date.year),('month', '=', to_date.month),
                                                            ('concept_deduction_order','=',max_order)])

        return res and res[0] or 0.0

    #Obtener valor retención por codigo
    def get_deduction_retention_value(self, employee_id,to_date,code):
        res = self.env['hr.employee.deduction.retention'].search([('employee_id', '=', employee_id),
                                                                    ('year', '=', to_date.year),('month', '=', to_date.month),('concept_deduction_code','=',code)])
        return res and res[0] or 0.0

    #Calculo retención en la fuente ordinario
    def get_calcula_rtefte_ordinaria(self, base_rtefte_uvt):
        res_initial = self.env['hr.calculation.rtefte.ordinary'].search([('range_initial', '<=', base_rtefte_uvt)])
        max_value = 0
        for i in res_initial:
            if i.range_finally > max_value:
                max_value = i.range_finally                
        res = self.env['hr.calculation.rtefte.ordinary'].search([('range_initial', '<=', base_rtefte_uvt),('range_finally', '=', max_value)])
        return res and res[0] or 0.0
    

    #--------VACACIONES

    #Retorna el objeto de auxilios de vacaciones AlianzaT
    def get_assistance_vacation(self, antiquity):
        res = self.env['hr.assistance.vacation.alliancet'].search([('antiquity', '=', antiquity)])
        if not res:
            obj_assistance = self.env['hr.assistance.vacation.alliancet'].search([('antiquity', '>', 0)])
            max_antiquity = 1
            for item in obj_assistance:
                max_antiquity = max_antiquity if max_antiquity > item.antiquity else item.antiquity                
            res = self.env['hr.assistance.vacation.alliancet'].search([('antiquity', '=', max_antiquity)])
        return res and res[0] or 0.0

    def get_accumulated_vacation(self, departure_date,date_start_process=False):
        if date_start_process:
            date_start = date_start_process
        else:
            date_start = departure_date - relativedelta(years=1)
        date_start = self.contract_id.date_start if date_start <= self.contract_id.date_start else date_start
        date_end = departure_date

        #formatear fechas
        date_start = str(date_start.year)+'-'+str(date_start.month)+'-'+str(date_start.day)
        date_end = str(date_end.year)+'-'+str(date_end.month)+'-'+str(date_end.day)

        self.env.cr.execute("""Select Sum(accumulated) as accumulated
                                From
                                (
                                    Select COALESCE(sum(pl.total),0) as accumulated 
                                        From hr_payslip as hp 
                                        Inner Join hr_payslip_line as pl on  hp.id = pl.slip_id 
                                        Inner Join hr_salary_rule hc on pl.salary_rule_id = hc.id and hc.base_vacaciones = true
                                        Inner Join hr_salary_rule_category hsc on hc.category_id = hsc.id and hsc.code != 'BASIC'
                                        WHERE hp.state in ('done','paid') and hp.contract_id = %s
                                        AND (hp.date_from between %s and %s
                                            or
                                            hp.date_to between %s and %s )
                                    Union 
                                    Select COALESCE(sum(pl.amount),0) as accumulated
                                        From hr_accumulated_payroll as pl
                                        Inner Join hr_salary_rule hc on pl.salary_rule_id = hc.id and hc.base_vacaciones = true
                                        Inner Join hr_salary_rule_category hsc on hc.category_id = hsc.id and hsc.code != 'BASIC'
                                        WHERE pl.employee_id = %s and pl.date between %s and %s
                                ) As A""",
                    (self.contract_id.id, date_start, date_end, date_start, date_end, self.employee_id, date_start, date_end))
        res = self.env.cr.fetchone()

        return res and res[0] or 0.0
    
    def get_accumulated_vacation_money(self, departure_date,date_start_process=False):
        if date_start_process:
            date_start = date_start_process
        else:
            date_start = departure_date - relativedelta(years=1)
        date_start = self.contract_id.date_start if date_start <= self.contract_id.date_start else date_start
        date_end = departure_date

        #formatear fechas
        date_start = str(date_start.year)+'-'+str(date_start.month)+'-'+str(date_start.day)
        date_end = str(date_end.year)+'-'+str(date_end.month)+'-'+str(date_end.day)

        self.env.cr.execute("""Select Sum(accumulated) as accumulated
                                From
                                (
                                    Select COALESCE(sum(pl.total),0) as accumulated 
                                        From hr_payslip as hp 
                                        Inner Join hr_payslip_line as pl on  hp.id = pl.slip_id 
                                        Inner Join hr_salary_rule hc on pl.salary_rule_id = hc.id and hc.base_vacaciones_dinero = true
                                        Inner Join hr_salary_rule_category hsc on hc.category_id = hsc.id and hsc.code != 'BASIC'
                                        WHERE hp.state in ('done','paid') and hp.contract_id = %s
                                        AND (hp.date_from between %s and %s
                                            or
                                            hp.date_to between %s and %s )
                                    Union 
                                    Select COALESCE(sum(pl.amount),0) as accumulated
                                        From hr_accumulated_payroll as pl
                                        Inner Join hr_salary_rule hc on pl.salary_rule_id = hc.id and hc.base_vacaciones_dinero = true
                                        Inner Join hr_salary_rule_category hsc on hc.category_id = hsc.id and hsc.code != 'BASIC'
                                        WHERE pl.employee_id = %s and pl.date between %s and %s
                                ) As A""",
                    (self.contract_id.id, date_start, date_end, date_start, date_end, self.employee_id, date_start, date_end))
        res = self.env.cr.fetchone()

        return res and res[0] or 0.0

    #--------CESANTIAS & INTERESES DE CESANTIAS

    def get_accumulated_cesantias(self, date_start, date_end, base_auxtransporte_tope=0):
        date_start = self.contract_id.date_start if date_start <= self.contract_id.date_start else date_start
        #formatear fechas
        date_start = str(date_start.year)+'-'+str(date_start.month)+'-'+str(date_start.day)
        date_end = str(date_end.year)+'-'+str(date_end.month)+'-'+str(date_end.day)        
        if base_auxtransporte_tope == 1:
            str_base_auxtransporte_tope = 'and hc.base_cesantias = true and hc.base_auxtransporte_tope = true'
        else:
            str_base_auxtransporte_tope = 'and hc.base_cesantias = true'

        self.env.cr.execute("""Select Sum(accumulated) as accumulated
                                From
                                (
                                    Select COALESCE(sum(pl.total),0) as accumulated 
                                        From hr_payslip as hp 
                                        Inner Join hr_payslip_line as pl on  hp.id = pl.slip_id 
                                        Inner Join hr_salary_rule hc on pl.salary_rule_id = hc.id and hc.base_cesantias = true
                                        Inner Join hr_salary_rule_category hsc on hc.category_id = hsc.id and hsc.code != 'BASIC'
                                        WHERE hp.state in ('done','paid') and hp.contract_id = %s
                                        AND (hp.date_from between %s and %s
                                            or
                                            hp.date_to between %s and %s )
                                    Union 
                                    Select COALESCE(sum(pl.amount),0) as accumulated
                                        From hr_accumulated_payroll as pl
                                        Inner Join hr_salary_rule hc on pl.salary_rule_id = hc.id and hc.base_cesantias = true
                                        Inner Join hr_salary_rule_category hsc on hc.category_id = hsc.id and hsc.code != 'BASIC'
                                        WHERE pl.employee_id = %s and pl.date between %s and %s
                                ) As A""",
                    (self.contract_id.id, date_start, date_end, date_start, date_end, self.employee_id, date_start, date_end))
        res = self.env.cr.fetchone()

        return res and res[0] or 0.0

    #--------PRIMA
    
    def get_accumulated_prima(self, date_start, date_end, base_auxtransporte_tope=0):
        date_start = self.contract_id.date_start if date_start <= self.contract_id.date_start else date_start
        #formatear fechas
        date_start = str(date_start.year)+'-'+str(date_start.month)+'-'+str(date_start.day)
        date_end = str(date_end.year)+'-'+str(date_end.month)+'-'+str(date_end.day)        
        if base_auxtransporte_tope == 1:
            str_base_auxtransporte_tope = 'and hc.base_prima = true and hc.base_auxtransporte_tope = true'
        else:
            str_base_auxtransporte_tope = 'and hc.base_prima = true'

        self.env.cr.execute("""Select Sum(accumulated) as accumulated
                                From
                                (
                                    Select COALESCE(sum(pl.total),0) as accumulated 
                                        From hr_payslip as hp 
                                        Inner Join hr_payslip_line as pl on  hp.id = pl.slip_id 
                                        Inner Join hr_salary_rule hc on pl.salary_rule_id = hc.id and hc.base_prima = true
                                        Inner Join hr_salary_rule_category hsc on hc.category_id = hsc.id and hsc.code != 'BASIC'
                                        WHERE hp.state in ('done','paid') and hp.contract_id = %s
                                        AND (hp.date_from between %s and %s
                                            or
                                            hp.date_to between %s and %s )
                                    Union 
                                    Select COALESCE(sum(pl.amount),0) as accumulated
                                        From hr_accumulated_payroll as pl
                                        Inner Join hr_salary_rule hc on pl.salary_rule_id = hc.id and hc.base_prima = true
                                        Inner Join hr_salary_rule_category hsc on hc.category_id = hsc.id and hsc.code != 'BASIC'
                                        WHERE pl.employee_id = %s and pl.date between %s and %s
                                ) As A""",
                    (self.contract_id.id, date_start, date_end, date_start, date_end, self.employee_id, date_start, date_end))
        res = self.env.cr.fetchone()

        return res and res[0] or 0.0

    # --------INDEMIZACIÓN

    def get_accumulated_compensation(self, date_start, date_end, values_base_compensation):
        date_start = date_end-relativedelta(years=1)
        date_start = self.contract_id.date_start if date_start <= self.contract_id.date_start else date_start
        dias_trabajados = self.days_between(date_start, date_end)
        # formatear fechas
        date_start = str(date_start.year) + '-' + str(date_start.month) + '-' + str(date_start.day)
        date_end = str(date_end.year) + '-' + str(date_end.month) + '-' + str(date_end.day)

        self.env.cr.execute("""Select Sum(accumulated) as accumulated
                                From
                                (
                                    Select COALESCE(sum(pl.total),0) as accumulated 
                                        From hr_payslip as hp 
                                        Inner Join hr_payslip_line as pl on  hp.id = pl.slip_id 
                                        Inner Join hr_salary_rule hc on pl.salary_rule_id = hc.id and hc.base_compensation = true
                                        Inner Join hr_salary_rule_category hsc on hc.category_id = hsc.id and (hsc.code != 'BASIC' or hc.code='BASICTURNOS')
                                        WHERE hp.state = 'done' and hp.contract_id = %s
                                        AND (hp.date_from between %s and %s
                                            or
                                            hp.date_to between %s and %s )
                                    Union 
                                    Select COALESCE(sum(pl.amount),0) as accumulated
                                        From hr_accumulated_payroll as pl
                                        Inner Join hr_salary_rule hc on pl.salary_rule_id = hc.id and hc.base_compensation = true
                                        Inner Join hr_salary_rule_category hsc on hc.category_id = hsc.id and (hsc.code != 'BASIC' or hc.code='BASICTURNOS')
                                        WHERE pl.employee_id = %s and pl.date between %s and %s
                                ) As A""",
                            (self.contract_id.id, date_start, date_end, date_start, date_end, self.employee_id,
                             date_start, date_end))
        res = self.env.cr.fetchone()
        if res and res[0]:
            return ((res[0]+values_base_compensation) / dias_trabajados) * 30
        else:
            return 0.0

    # -------AÑOS EN LA EMPRESA Y LA FECHA CUANDO CUMPLIO EL AÑO
    def years_in_company(self,date_process):
        lst_date_years = []
        date_start = self.contract_id.date_start
        while date_start <= date_process:
            date_start_o = date_start
            date_start = date_start+relativedelta(years=1)
            dias_ausencias = sum([i.number_of_days for i in self.env['hr.leave'].search(
                [('date_from', '>=', date_start_o), ('date_to', '<=', date_start),
                 ('state', '=', 'validate'), ('employee_id', '=', self.contract_id.employee_id.id),
                 ('unpaid_absences', '=', True)])])
            dias_ausencias += sum([i.days for i in self.env['hr.absence.history'].search(
                [('star_date', '>=', date_start_o), ('end_date', '<=', date_start),
                 ('employee_id', '=', self.contract_id.employee_id.id), ('leave_type_id.unpaid_absences', '=', True)])])
            date_start = date_start + timedelta(days=dias_ausencias)
            if (date_start-date_start_o).days >= 365 and date_start <= date_process:
                lst_date_years.append(date_start)
        return lst_date_years
    #-----------------------------------------FIN Código Localización colombiana lavish------------------------------------------------------

    @property
    def paid_amount(self):
        return self.dict._get_paid_amount()
    #-----------------------------------------Bases Localizacion 2 ---------------------------------------------------------------------------
    @property
    def sub_transporte(self):
        return self._get_sub_transporte() or 100
    
    @property
    def sub_transporte(self):
        return self._get_sub_transporte() or 100
    def get_base_security(self, date_start, date_end):
        #formatear fechas
        date_start = str(date_start.year)+'-'+str(date_start.month)+'-'+str(date_start.day)
        date_end = str(date_end.year)+'-'+str(date_end.month)+'-'+str(date_end.day)        
        self.env.cr.execute("""Select COALESCE(sum(pl.total),0) as suma 
                            FROM hr_payslip as hp 
                            Inner Join hr_payslip_line as pl on  hp.id = pl.slip_id 
                            Inner Join hr_salary_rule hc on pl.salary_rule_id = hc.id and hc.base_seguridad_social = true
                            WHERE  hp.contract_id = %s AND hp.date_from >= %s AND hp.date_to <= %s""",
                    (self.contract_id.id, date_start, date_end))
        res = self.env.cr.fetchone()
        _logger.info('\n\n salario \n\n%r', res)
        return res and res[0] or 0.0
    
    def sum_mount_base(self, code, from_date, to_date):
        from_month = from_date.month
        from_year = from_date.year

        to_month = to_date.month + 1 if to_date.month != 12 else 1
        to_year = to_date.year + 1 if to_date.month == 12 else to_date.year

        self.env.cr.execute("""Select COALESCE(sum(pl.total),0) as suma FROM hr_payslip as hp 
                            Inner Join hr_payslip_line as pl on  hp.id = pl.slip_id 
                            Inner Join hr_salary_rule_category hc on pl.category_id = hc.id 
                            WHERE hp.contract_id = %s AND hp.date_from >= '%s-%s-01' AND hp.date_from < '%s-%s-01'
                            AND (hc.code = %s)""",
                    (self.contract_id.id, from_year, from_month, to_year, to_month, code))
        res = self.env.cr.fetchone()
        return res and res[0] or 0.0

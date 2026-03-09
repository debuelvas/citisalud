# -*- coding: utf-8 -*-

from logging import exception
from odoo import models, fields, api, _, SUPERUSER_ID
from odoo.exceptions import UserError, ValidationError

from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta


import odoo
import threading

class hr_executing_provisions_details(models.Model):
    _name = 'hr.executing.provisions.details'
    _description = 'Ejecución Provisiones empleados detalle'


    executing_provisions_id = fields.Many2one('hr.executing.provisions',string='Ejecución Provisiones')
    provision = fields.Selection([('cesantias', 'Cesantías'),
                                    ('intcesantias', 'Intereses de cesantías'),
                                    ('prima', 'Prima'),
                                    ('vacaciones', 'Vacaciones')], string='Provisión', required=True)
    employee_id = fields.Many2one('hr.employee', 'Empleado', required=True)
    contract_id = fields.Many2one('hr.contract', 'Contrato', required=True)
    analytic_account_id = fields.Many2one('account.analytic.account', string='Cuenta analítica')
    value_wage = fields.Float('Salario')
    value_base = fields.Float('Base')
    time = fields.Float('Unidades')
    value_balance = fields.Float('Valor Provisión Mes')
    value_payments = fields.Float('Pagos realizados')
    amount = fields.Float('Valor liquidado')
    current_payable_value = fields.Float('Valor a Pagar Actual')

class hr_executing_provisions(models.Model):
    _name = 'hr.executing.provisions'
    _description = 'Ejecución Provisiones empleados'

    year = fields.Integer('Año', required=True)
    month = fields.Selection([('1', 'Enero'),
                            ('2', 'Febrero'),
                            ('3', 'Marzo'),
                            ('4', 'Abril'),
                            ('5', 'Mayo'),
                            ('6', 'Junio'),
                            ('7', 'Julio'),
                            ('8', 'Agosto'),
                            ('9', 'Septiembre'),
                            ('10', 'Octubre'),
                            ('11', 'Noviembre'),
                            ('12', 'Diciembre')        
                            ], string='Mes', required=True)
    date_end = fields.Date('Fecha')
    #employee_ids = fields.Many2many('hr.employee', string='Empleados', ondelete='restrict', required=True)
    details_ids = fields.One2many('hr.executing.provisions.details', 'executing_provisions_id',string='Ejecución')
    time_process_float = fields.Float(string='Tiempo ejecución float')
    time_process = fields.Char(string='Tiempo ejecución')
    observations = fields.Text('Observaciones')
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('done', 'Realizado'),
        ('accounting', 'Contabilizado'),
    ], string='Estado', default='draft')
    move_id = fields.Many2one('account.move',string='Contabilidad')

    company_id = fields.Many2one('res.company', string='Compañía', readonly=True, required=True,
        default=lambda self: self.env.company)

    _sql_constraints = [('provisions_period_uniq', 'unique(company_id,year,month)', 'El periodo seleccionado ya esta registrado para esta compañía, por favor verificar.')]

    def name_get(self):
        result = []
        for record in self:
            result.append((record.id, "Periodo {}-{}".format(record.month,str(record.year))))
        return result
  
    def executing_provisions_thread(self,date_start,date_end,struct_vacaciones,struct_prima,struct_cesantias,struct_intcesantias,contracts):
        with odoo.api.Environment.manage():
            registry = odoo.registry(self._cr.dbname)
            with registry.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                
                for obj_contract in contracts:
                    contract = env['hr.contract'].search([('id', '=', obj_contract.id)])
                    try:
                        result_cesantias = {}
                        result_intcesantias = {}
                        result_prima = {}
                        result_vac = {}
                        retirement_date = contract.retirement_date
                        date_end_without_31 = date_end - timedelta(days=1) if date_end.day == 31 else date_end

                        #Obtener fecha cesantias
                        date_cesantias = contract.date_start
                        if retirement_date == False:
                            obj_cesantias = env['hr.history.cesantias'].search([('employee_id', '=', contract.employee_id.id),('contract_id', '=', contract.id),('final_accrual_date','<',date_end),('final_accrual_date','<',date_end_without_31)])
                        else:
                            if retirement_date >= date_end:
                                obj_cesantias = env['hr.history.cesantias'].search([('employee_id', '=', contract.employee_id.id), ('contract_id', '=', contract.id),('final_accrual_date', '<', date_end),('final_accrual_date', '<', date_end_without_31)])
                            else:
                                obj_cesantias = env['hr.history.cesantias'].search([('employee_id', '=', contract.employee_id.id), ('contract_id', '=', contract.id),('final_accrual_date', '<', retirement_date)])
                        if obj_cesantias:
                            for history in sorted(obj_cesantias, key=lambda x: x.final_accrual_date):
                                date_cesantias = history.final_accrual_date + timedelta(days=1) if history.final_accrual_date > date_cesantias else date_cesantias             

                        #Obtener fecha prima
                        date_prima = contract.date_start
                        if retirement_date == False:
                            obj_prima = env['hr.history.prima'].search([('employee_id', '=', contract.employee_id.id),('contract_id', '=', contract.id),('final_accrual_date','<',date_end),('final_accrual_date','<',date_end_without_31)])
                        else:
                            if retirement_date >= date_end:
                                obj_prima = env['hr.history.prima'].search([('employee_id', '=', contract.employee_id.id), ('contract_id', '=', contract.id),('final_accrual_date', '<', date_end),('final_accrual_date', '<', date_end_without_31)])
                            else:
                                obj_prima = env['hr.history.prima'].search([('employee_id', '=', contract.employee_id.id), ('contract_id', '=', contract.id),('final_accrual_date', '<', retirement_date)])
                        if obj_prima:
                            for history in sorted(obj_prima, key=lambda x: x.final_accrual_date):
                                date_prima = history.final_accrual_date + timedelta(days=1) if history.final_accrual_date > date_prima else date_prima                                   

                        #Obtener fecha vacaciones
                        date_vacation = contract.date_start
                        if retirement_date == False:
                            obj_vacation = env['hr.vacation'].search([('employee_id', '=', contract.employee_id.id), ('contract_id', '=', contract.id),('final_accrual_date', '<', date_end), ('departure_date', '<=', date_end)])
                        else:
                            if retirement_date >= date_end:
                                obj_vacation = env['hr.vacation'].search([('employee_id', '=', contract.employee_id.id), ('contract_id', '=', contract.id),('final_accrual_date', '<', date_end), ('departure_date', '<=', date_end)])
                            else:
                                obj_vacation = env['hr.vacation'].search([('employee_id', '=', contract.employee_id.id), ('contract_id', '=', contract.id),('final_accrual_date', '<', retirement_date),('departure_date', '<=', retirement_date)])
                        if obj_vacation:
                            for history in sorted(obj_vacation, key=lambda x: x.final_accrual_date):
                                if history.leave_id:
                                    if history.leave_id.holiday_status_id.unpaid_absences == False:
                                        date_vacation = history.final_accrual_date + timedelta(days=1) if history.final_accrual_date > date_vacation else date_vacation
                                else:
                                    date_vacation = history.final_accrual_date + timedelta(days=1) if history.final_accrual_date > date_vacation else date_vacation

                        if retirement_date == False:
                            date_to_process = date_end
                        else:
                            if retirement_date >= date_end:
                                date_to_process = date_end
                            else:
                                date_to_process = retirement_date

                        #Simular liquidación de cesantias
                        Payslip = env['hr.payslip']
                        default_values = Payslip.default_get(Payslip.fields_get())
                        values = dict(default_values, **{
                                'employee_id': contract.employee_id.id,
                                'date_cesantias':date_cesantias,
                                'date_prima': date_prima,
                                'date_vacaciones':date_vacation,
                                'date_from': date_start,
                                'date_to': date_to_process,
                                'date_liquidacion':date_to_process,
                                'contract_id': contract.id,
                                'struct_id': struct_cesantias.id
                            })
                        payslip = env['hr.payslip'].new(values)
                        payslip._onchange_employee()
                        values = payslip._convert_to_write(payslip._cache)
                        obj_provision = Payslip.create(values)
                        
                        if contract.contract_type != 'aprendizaje':
                            if contract.modality_salary != 'integral':
                                #Cesantias
                                obj_provision.write({'struct_id': struct_cesantias.id})
                                localdict,result_cesantias = obj_provision._get_payslip_lines_cesantias(inherit_contrato=1)
                                # Intereses de Cesantias
                                obj_provision.write({'struct_id': struct_intcesantias.id})
                                localdict, result_intcesantias = obj_provision._get_payslip_lines_cesantias(inherit_contrato=1)
                                #Prima
                                obj_provision.write({'struct_id': struct_prima.id})
                                localdict,result_prima = obj_provision._get_payslip_lines_prima(inherit_contrato=1)
                            #Vacaciones
                            obj_provision.write({'struct_id': struct_vacaciones.id})
                            localdict,result_vac = obj_provision._get_payslip_lines_vacation(inherit_contrato=1)


                        obj_provision.action_payslip_cancel()
                        obj_provision.unlink()
                        
                        #Guardar resultado
                        result_finally = {**result_cesantias,**result_intcesantias,**result_prima,**result_vac}
                        
                        #Restar las provisiones anteriores
                        for line in result_finally.values():
                            if line['code'] in ['CESANTIAS','INTCESANTIAS','PRIMA','VACCONTRATO']:
                                if line['code'] == 'CESANTIAS':
                                    provision = 'cesantias'
                                if line['code'] == 'INTCESANTIAS':
                                    provision = 'intcesantias'
                                if line['code'] == 'PRIMA':
                                    provision = 'prima'
                                if line['code'] == 'VACCONTRATO':
                                    provision = 'vacaciones'

                                #Obtener provisiones anteriores que afectan el valor
                                date_month_ant = date_start - timedelta(days=1)

                                obj_provisions = env['hr.executing.provisions.details']

                                executing_provisions = env['hr.executing.provisions.details'].search(
                                    [('executing_provisions_id.state', 'in', ['done', 'accounting']),
                                     ('executing_provisions_id', '!=', self.id),
                                     ('executing_provisions_id.date_end', '=', date_month_ant),
                                     ('provision', '=', provision), ('contract_id', '=', contract.id)])
                                value_balance = sum([i.current_payable_value for i in obj_provisions.browse(executing_provisions.ids)])
                                amount_ant = sum([i.amount for i in obj_provisions.browse(executing_provisions.ids)])
                                #Obtener pagos realizados en el mes
                                code_filter = [provision.upper()] if provision != 'vacaciones' else ['VACCONTRATO','VACDISFRUTADAS','VACREMUNERADAS']

                                obj_payslip = env['hr.payslip.line']
                                lines_payslip = env['hr.payslip.line'].search(
                                    [('slip_id.state', '=', 'done'), ('slip_id.date_from', '>=', date_start),
                                     ('slip_id.date_from', '<=', date_end), ('code', 'in', code_filter),
                                     ('slip_id.contract_id', '=', contract.id),('is_history_reverse','=',False)])
                                lines_payslip += env['hr.payslip.line'].search(
                                    [('slip_id.state', '=', 'done'), ('slip_id.date_to', '>=', date_start),
                                     ('slip_id.date_to', '<=', date_end), ('code', 'in', code_filter),
                                     ('slip_id.contract_id', '=', contract.id),('is_history_reverse','=',False),
                                     ('id','not in',lines_payslip.ids),
                                     ('slip_id.struct_id.process','in',['cesantias','intereses_cesantias','prima'])])
                                if len(lines_payslip) > 0:
                                    value_payments = sum([i.total for i in obj_payslip.browse(lines_payslip.ids)])
                                else:
                                    value_payments = 0

                                #Calcular valor a pagar actual
                                amount = round((line['amount'] * line['quantity'] * line['rate'])/100,0)

                                # ------------------------
                                # 19/01/2022 - Luis Buitrón | Carolina Rincón : Se comenta buscar los pagos historicos
                                #  debido a que solamente debe tener en cuenta los pagos realizados en el mes
                                # ------------------------
                                #obj_provisions = env['hr.executing.provisions.details']
                                #executing_provisions = env['hr.executing.provisions.details'].search(
                                #    [('executing_provisions_id.state', 'in', ['done', 'accounting']),
                                #     ('executing_provisions_id', '!=', self.id),('value_payments','>',0),
                                #     ('provision', '=', provision), ('contract_id', '=', contract.id)])

                                #if len(executing_provisions) > 0:
                                #    payable_value = sum([i.value_payments for i in obj_provisions.browse(executing_provisions.ids)])
                                #    current_payable_value = amount - (payable_value+value_payments)
                                #else:
                                if value_payments > 0 and provision == 'vacaciones':
                                    current_payable_value = value_balance - value_payments
                                else:
                                    current_payable_value = amount - value_payments

                                #Valor provision Mes
                                if value_payments > 0 and current_payable_value < 0 and provision == 'vacaciones':
                                    value_provision = abs(current_payable_value)
                                    current_payable_value = 0
                                elif value_payments > 0 and current_payable_value >=0 and provision == 'vacaciones':
                                    value_provision = amount - current_payable_value
                                    current_payable_value = amount
                                elif value_payments == 0 and current_payable_value >= 0 and provision == 'vacaciones':
                                    value_provision = amount - value_balance#amount_ant
                                else:
                                    value_provision = amount - value_balance

                                #Obtener ultima liquidacion del mes para traer la cuenta analitica utilizada
                                obj_last_payslip = env['hr.payslip']
                                last_lines_payslip = env['hr.payslip'].search(
                                    [('state', '=', 'done'), ('date_from', '>=', date_start),
                                     ('date_from', '<=', date_end),('contract_id', '=', contract.id)])
                                last_lines_payslip += env['hr.payslip'].search(
                                    [('state', '=', 'done'), ('date_to', '>=', date_start),
                                     ('date_to', '<=', date_end),('contract_id', '=', contract.id), ('id', 'not in', last_lines_payslip.ids),
                                     ('struct_id.process', 'in', ['cesantias', 'intereses_cesantias', 'prima'])])
                                analytic_account_id = contract.analytic_account_id
                                for last_payslip in sorted(last_lines_payslip,key=lambda x: x.date_to):
                                    analytic_account_id = last_payslip.analytic_account_id

                                #Guardar valores
                                values_details = {
                                    'executing_provisions_id':self.id,
                                    'provision': provision,
                                    'employee_id': contract.employee_id.id,
                                    'contract_id': contract.id,
                                    'analytic_account_id': analytic_account_id.id,
                                    'value_wage': contract.wage,
                                    'value_base': line['amount_base'],
                                    'time': line['quantity'],
                                    'value_balance': value_provision,
                                    'value_payments': value_payments,
                                    'current_payable_value': current_payable_value,
                                    'amount': amount
                                }
                                env['hr.executing.provisions.details'].create(values_details)
                    
                    except Exception as e:
                        msg = 'ERROR: '+str(e.args[0])+' en el contrato '+contract.name+'.'
                        if self.observations:
                            self.observations = self.observations + '\n' + msg
                        else:
                            self.observations = msg

    def executing_provisions(self):
        #Eliminar ejecución
        #self.env['hr.executing.provisions.details'].search([('executing_provisions_id','=',self.id)]).unlink()

        #Obtener fechas del periodo seleccionado
        date_start = '01/'+str(self.month)+'/'+str(self.year)
        try:
            date_start = datetime.strptime(date_start, '%d/%m/%Y')       

            date_end = date_start + relativedelta(months=1)
            date_end = date_end - timedelta(days=1)
            
            date_start = date_start.date()
            date_end = date_end.date()
        except:
            raise UserError(_('El año digitado es invalido, por favor verificar.'))  


        #Obtener estructuras
        struct_cesantias = self.env['hr.payroll.structure'].search([('process', '=', 'cesantias')])
        struct_intcesantias = self.env['hr.payroll.structure'].search([('process', '=', 'intereses_cesantias')])
        struct_prima = self.env['hr.payroll.structure'].search([('process', '=', 'prima')])
        struct_vacaciones = self.env['hr.payroll.structure'].search([('process', '=', 'vacaciones')])

        #Obtener contratos activos o desactivados en el mes de ejecución
        #obj_contracts = self.env['hr.contract'].search(
        #    [('state', '=', 'open'), ('date_start', '<=', date_end), ('company_id', '=', self.env.company.id),
        #     ('subcontract_type','!=','obra_integral')])
        #obj_contracts += self.env['hr.contract'].search(
        #    [('state', '=', 'close'), ('retirement_date', '>=', date_start), ('retirement_date', '<=', date_end),
        #     ('company_id', '=', self.env.company.id),('subcontract_type','!=','obra_integral')])
        #obj_contracts += self.env['hr.contract'].search(
        #    [('state', '=', 'finished'), ('date_end', '>=', date_start), ('date_end', '<=', date_end),
        #     ('company_id', '=', self.env.company.id), ('subcontract_type', '!=', 'obra_integral')])

        # Obtener contratos que tuvieron liquidaciones en el mes
        str_contracts = '(0)'
        if len(self.details_ids) > 0:
            str_contracts = str(self.details_ids.contract_id.ids).replace('[', '(').replace(']', ')')

        query = '''
            select distinct b.id 
            from hr_payslip a
            inner join hr_contract b on a.contract_id = b.id and (b.subcontract_type != 'obra_integral' or b.subcontract_type is null) and b.id not in %s
            where a.state = 'done' and a.company_id = %s and ((a.date_from >= '%s' and a.date_from <= '%s') or (a.date_to >= '%s' and a.date_to <= '%s'))
            Limit 200
        ''' % (str_contracts,self.env.company.id,date_start,date_end,date_start,date_end)

        self.env.cr.execute(query)
        result_query = self.env.cr.fetchall()

        contract_ids = []
        for result in result_query:
            contract_ids.append(result)
        obj_contracts = self.env['hr.contract'].search([('id', 'in', contract_ids)])

        #Guardo los contratos en lotes de a 20
        contracts_array, i, j = [], 0 , 20            
        while i <= len(obj_contracts):                
            contracts_array.append(obj_contracts[i:j])
            i = j
            j += 20   

        #Los lotes anteriores, los separo en los de 5, para ejecutar un maximo de 5 hilos
        contracts_array_def, i, j = [], 0 , 5            
        while i <= len(contracts_array):                
            contracts_array_def.append(contracts_array[i:j])
            i = j
            j += 5  

        #----------------------------Recorrer contratos por multihilos
        date_start_process = datetime.now()
        date_finally_process = datetime.now()
        i = 1
        for contracts in contracts_array_def:
            # array_thread = []
            for contract in contracts:
                self.executing_provisions_thread(date_start,date_end,struct_vacaciones,struct_prima,struct_cesantias,struct_intcesantias,contract)
                # t = threading.Thread(target=self.executing_provisions_thread, args=(date_start,date_end,struct_vacaciones,struct_prima,struct_cesantias,struct_intcesantias,contract,))
                # t.start()
                # array_thread.append(t)
                # i += 1

            # for hilo in array_thread:
            #     hilo.join()

        date_finally_process = datetime.now()
        time_process = date_finally_process - date_start_process
        time_process = time_process.seconds / 60
        time_process += self.time_process_float
        self.time_process_float = time_process
        self.time_process = "El proceso se demoro {:.2f} minutos.".format(time_process)

        query = '''
                    select distinct b.id 
                    from hr_payslip a
                    inner join hr_contract b on a.contract_id = b.id and (b.subcontract_type != 'obra_integral' or b.subcontract_type is null) and contract_type != 'aprendizaje'
                    where a.state = 'done' and a.company_id = %s and ((a.date_from >= '%s' and a.date_from <= '%s') or (a.date_to >= '%s' and a.date_to <= '%s'))
                ''' % (self.env.company.id, date_start, date_end, date_start, date_end)
        self.env.cr.execute(query)
        result_query = self.env.cr.fetchall()

        if len(self.details_ids.contract_id.ids) == len(result_query):
            self.date_end = date_end
            self.state = 'done'

    def get_accounting(self):
        line_ids = []
        debit_sum = 0.0
        credit_sum = 0.0
        date = self.date_end
        move_dict = {
            'narration': '',
            'ref': f"Provisión - {date.strftime('%B %Y')}",
            'journal_id': False,
            'date': date,
        }

        for slip in self.details_ids:
            # Lógica de lavish - Obtener cuenta contable de acuerdo a la parametrización contable
            debit_third_id = slip.employee_id.work_contact_id
            credit_third_id = slip.employee_id.work_contact_id
            analytic_account_id = slip.employee_id.analytic_account_id

            obj_closing = self.env['hr.closing.configuration.header'].search([('process','=',slip.provision)])

            for closing in obj_closing:
                move_dict['journal_id'] = closing.journal_id.id
                for account_rule in closing.detail_ids:
                    debit_account_id = False
                    credit_account_id = False
                    # Validar ubicación de trabajo
                    bool_work_location = False
                    if account_rule.work_location.id == slip.employee_id.address_id.id or account_rule.work_location.id == False:
                        bool_work_location = True
                    # Validar compañia
                    bool_company = False
                    if account_rule.company.id == slip.employee_id.company_id.id or account_rule.company.id == False:
                        bool_company = True
                    # Validar departamento
                    bool_department = False
                    if account_rule.department.id == slip.employee_id.department_id.id or account_rule.department.id == slip.employee_id.department_id.parent_id.id or account_rule.department.id == slip.employee_id.department_id.parent_id.parent_id.id or account_rule.department.id == False:
                        bool_department = True

                    if bool_department and bool_company and bool_work_location:
                        debit_account_id = account_rule.debit_account
                        credit_account_id = account_rule.credit_account

                    # Tercero debito
                    if account_rule.third_debit == 'entidad':
                        pass
                        #debit_third_id = line.entity_id.partner_id
                    elif account_rule.third_debit == 'compañia':
                        debit_third_id = slip.employee_id.company_id.partner_id
                    elif account_rule.third_debit == 'empleado':
                        debit_third_id = slip.employee_id.work_contact_id

                    # Tercero credito
                    if account_rule.third_credit == 'entidad':
                        pass
                        #credit_third_id = line.entity_id.partner_id
                    elif account_rule.third_credit == 'compañia':
                        credit_third_id = slip.employee_id.company_id.partner_id
                    elif account_rule.third_credit == 'empleado':
                        credit_third_id = slip.employee_id.work_contact_id

                    # Descripción final
                    addref_work_address_account_moves = self.env['ir.config_parameter'].sudo().get_param(
                        'lavish_hr_payroll.addref_work_address_account_moves') or False
                    if addref_work_address_account_moves and slip.employee_id.address_id:
                        if slip.employee_id.address_id.parent_id:
                            description = f"{slip.employee_id.address_id.parent_id.vat} {slip.employee_id.address_id.display_name}|{slip.provision.upper()}"
                        else:
                            description = f"{slip.employee_id.address_id.vat} {slip.employee_id.address_id.display_name}|{slip.provision.upper()}"
                    else:
                        description = slip.provision.upper()

                    #Valor
                    amount = slip.value_balance if slip.value_balance != 0 else slip.amount

                    if debit_account_id:
                        debit = abs(amount) if amount >= 0.0 else 0.0
                        credit = abs(amount) if amount < 0.0 else 0.0
                        debit_line = {
                            'name': description,
                            'partner_id': debit_third_id.id,# if debit > 0 else credit_third_id.id,
                            'account_id': debit_account_id.id,# if debit > 0 else credit_account_id.id,
                            'journal_id': closing.journal_id.id,
                            'date': date,
                            'debit': debit,
                            'credit': credit,
                            'analytic_account_id': analytic_account_id.id,
                        }
                        line_ids.append(debit_line)

                    if credit_account_id:
                        debit = abs(amount) if amount < 0.0 else 0.0
                        credit = abs(amount) if amount >= 0.0 else 0.0

                        credit_line = {
                            'name': description,
                            'partner_id': credit_third_id.id,
                            'account_id': credit_account_id.id,
                            'journal_id': closing.journal_id.id,
                            'date': date,
                            'debit': debit,
                            'credit': credit,
                            'analytic_account_id': analytic_account_id.id,
                        }
                        line_ids.append(credit_line)

        move_dict['line_ids'] = [(0, 0, line_vals) for line_vals in line_ids]
        move = self.env['account.move'].create(move_dict)
        self.write({'move_id': move.id, 'state': 'accounting'})

    def cancel_process(self):
        #Eliminar ejecución
        self.env['hr.executing.provisions.details'].search([('executing_provisions_id', '=', self.id)]).unlink()
        return self.write({'state':'draft','time_process':''})

    def restart_accounting(self):
        if self.move_id:
            if self.move_id.state != 'draft':
                raise ValidationError(_('No se puede reversar el movimiento contable debido a que su estado es diferente de borrador.'))
            self.move_id.unlink()
        return self.write({'state': 'done'})

    def unlink(self):
        for record in self:
            if record.state != 'draft':
                raise ValidationError(_('No se puede eliminar la provisión debido a que su estado es diferente de borrador.'))
        return super(hr_executing_provisions, self).unlink()


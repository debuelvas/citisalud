#---------------------------------------------------------------------------------------------------------------------------------------
#---------------------------------------------------------------------------------------------------------------------------------------
#---------------------------------------------------------------------------------------------------------------------------------------
#------------------------------------------------------LIQUIDACION DE NÓMINA--------------------------------------------------------

#---------------------------------------Basic Salary--------------------------------------------------------
result = 0.0
obj_salary_rule = payslip.get_salary_rule('BASIC',employee.type_employee.id)
if obj_salary_rule and contract.modality_salary != 'integral' and contract.modality_salary != 'sostenimiento':
    if worked_days.WORK100 != 0.0:
        result =  round(worked_days.WORK100.number_of_days * (contract.wage /30))    
#---------------------------------------Basic Salary Integral--------------------------------------------------------
result = 0.0
obj_salary_rule = payslip.get_salary_rule('BASIC002',employee.type_employee.id)
if obj_salary_rule and contract.modality_salary == 'integral':
    wage = annual_parameters.get_values_integral_salary(contract.wage,0) + annual_parameters.get_values_integral_salary(contract.wage,1)
    if worked_days.WORK100 != 0.0:
        result =  round(worked_days.WORK100.number_of_days * (wage/30)) 
#---------------------------------------Basic Cuota Sostenimiento--------------------------------------------------------
result = 0.0
obj_salary_rule = payslip.get_salary_rule('BASIC003',employee.type_employee.id)
if obj_salary_rule and contract.modality_salary == 'sostenimiento':
    if worked_days.WORK100 != 0.0:
        result =  round(worked_days.WORK100.number_of_days * (contract.wage /30))           
#---------------------------------------Auxilio de transporte--------------------------------------------------------
result = 0.0
obj_salary_rule = payslip.get_salary_rule('AUX000',employee.type_employee.id)
aplicar = 0 if obj_salary_rule.aplicar_cobro=='30' and inherit_contrato!=0 else int(obj_salary_rule.aplicar_cobro)
dias = 0 if aplicar == 0 else payslip.sum_days_works('WORK100', payslip.date_from, payslip.date_to) + payslip.sum_days_works('COMPENSATORIO', payslip.date_from, payslip.date_to)
dias += worked_days.WORK100.number_of_days if worked_days.WORK100 else 0
if worked_days.COMPENSATORIO != 0.0:
    dias += worked_days.COMPENSATORIO.number_of_days
liquidated_aux_transport = False if payslip.settle_payroll_concepts == False and inherit_contrato!=0 else True
if obj_salary_rule and liquidated_aux_transport and dias != 0.0 and contract.contract_type != 'aprendizaje':
    auxtransporte = annual_parameters.transportation_assistance_monthly
    auxtransporte_tope = annual_parameters.top_max_transportation_assistance
    day_initial_payrroll = payslip.date_from.day
    day_end_payrroll = 30 if payslip.date_to.month == 2 and payslip.date_to.day in (28,29) else payslip.date_to.day
    if (aplicar == 0) or (aplicar >= day_initial_payrroll and aplicar <= day_end_payrroll):
        total = categories.DEV_SALARIAL if aplicar == 0 else categories.DEV_SALARIAL + payslip.sum_mount('DEV_SALARIAL', payslip.date_from, payslip.date_to)
        if dias != 0.0:
            if contract.not_validate_top_auxtransportation == True:
                result = round(dias * auxtransporte / 30)
            else:
                if (contract.wage <= auxtransporte_tope) and (total <= auxtransporte_tope):
                    result = round(dias * auxtransporte /30)
#---------------------------------------Salud Empleado--------------------------------------------------------
result = 0.0
obj_salary_rule = payslip.get_salary_rule('SSOCIAL001',employee.type_employee.id)
if obj_salary_rule and contract.contract_type != 'aprendizaje':
    day_initial_payrroll = payslip.date_from.day
    day_end_payrroll = 30 if payslip.date_to.month == 2 and payslip.date_to.day in (28,29) else payslip.date_to.day
    aplicar = 0 if obj_salary_rule.aplicar_cobro=='30' and inherit_contrato!=0 else int(obj_salary_rule.aplicar_cobro)
    if (aplicar == 0) or (aplicar >= day_initial_payrroll and aplicar <= day_end_payrroll):
        porc = annual_parameters.value_porc_health_employee/100
        total = categories.DEV_SALARIAL if aplicar == 0 else categories.DEV_SALARIAL + payslip.sum_mount('DEV_SALARIAL', payslip.date_from, payslip.date_to)
        #Ley 1393
        if payslip.date_from.day > 15 or (inherit_contrato != 0):
            total_salarial = categories.DEV_SALARIAL + payslip.sum_mount('DEV_SALARIAL', payslip.date_from,
                                                                               payslip.date_to)
            auxtransporte = AUX000 + payslip.sum_mount_x_rule('AUX000', payslip.date_from, payslip.date_to)
            vac_no_salarial = categories.VNS + + payslip.sum_mount('VNS', payslip.date_from,payslip.date_to)
            total_no_salarial = categories.DEV_NO_SALARIAL + payslip.sum_mount('DEV_NO_SALARIAL', payslip.date_from,
                                                                               payslip.date_to) - auxtransporte - vac_no_salarial
            gran_total = total_salarial + total_no_salarial
            statute_value = (gran_total/100)*annual_parameters.value_porc_statute_1395
            total_statute = total_no_salarial-statute_value
            if total_statute > 0:
                total += total_statute
        # Fin Ley 1393
        dias_work = payslip.sum_days_contribution_base(payslip.date_from, payslip.date_to)
        dias_work_act = 0
        for wd in worked_days.dict.values():
            dias_work_act += wd.number_of_days if wd.work_entry_type_id.not_contribution_base == False else 0
        dias_work = dias_work_act if (aplicar == 0) else dias_work + dias_work_act
        top_twenty_five_smmlv = (annual_parameters.top_twenty_five_smmlv / 30) * dias_work
        if contract.modality_salary == 'integral':
            porc_integral_salary = annual_parameters.porc_integral_salary/100
            total = total*porc_integral_salary
            total = top_twenty_five_smmlv if total >= top_twenty_five_smmlv else total
        else:
            total = top_twenty_five_smmlv if total >= top_twenty_five_smmlv else total
        result = round((total)*porc)*-1 
#---------------------------------------Pension Empleado--------------------------------------------------------
result = 0.0
obj_salary_rule = payslip.get_salary_rule('SSOCIAL002',employee.type_employee.id)
if obj_salary_rule and contract.contract_type != 'aprendizaje' and employee.subtipo_coti_id.not_contribute_pension == False:
    day_initial_payrroll = payslip.date_from.day
    day_end_payrroll = 30 if payslip.date_to.month == 2 and payslip.date_to.day in (28,29) else payslip.date_to.day
    aplicar = 0 if obj_salary_rule.aplicar_cobro=='30' and inherit_contrato!=0 else int(obj_salary_rule.aplicar_cobro)
    if (aplicar == 0) or (aplicar >= day_initial_payrroll and aplicar <= day_end_payrroll):
        porc = annual_parameters.value_porc_pension_employee/100
        total = categories.DEV_SALARIAL if aplicar == 0 else categories.DEV_SALARIAL + payslip.sum_mount('DEV_SALARIAL', payslip.date_from, payslip.date_to)
        # Ley 1393
        if payslip.date_from.day > 15 or (inherit_contrato != 0):
            total_salarial = categories.DEV_SALARIAL + payslip.sum_mount('DEV_SALARIAL', payslip.date_from,
                                                                         payslip.date_to)
            auxtransporte = AUX000 + payslip.sum_mount_x_rule('AUX000', payslip.date_from, payslip.date_to)
            vac_no_salarial = categories.VNS + + payslip.sum_mount('VNS', payslip.date_from, payslip.date_to)
            total_no_salarial = categories.DEV_NO_SALARIAL + payslip.sum_mount('DEV_NO_SALARIAL', payslip.date_from,
                                                                               payslip.date_to) - auxtransporte - vac_no_salarial
            gran_total = total_salarial + total_no_salarial
            statute_value = (gran_total / 100) * annual_parameters.value_porc_statute_1395
            total_statute = total_no_salarial - statute_value
            if total_statute > 0:
                total += total_statute
        # Fin Ley 1393
        dias_work = payslip.sum_days_contribution_base(payslip.date_from, payslip.date_to)
        dias_work_act = 0
        for wd in worked_days.dict.values():
            dias_work_act += wd.number_of_days if wd.work_entry_type_id.not_contribution_base == False else 0
        dias_work = dias_work_act if (aplicar == 0) else dias_work + dias_work_act
        top_twenty_five_smmlv = (annual_parameters.top_twenty_five_smmlv / 30) * dias_work
        if contract.modality_salary == 'integral':
            porc_integral_salary = annual_parameters.porc_integral_salary / 100
            total = total * porc_integral_salary
            total = top_twenty_five_smmlv if total >= top_twenty_five_smmlv else total
        else:
            total = top_twenty_five_smmlv if total >= top_twenty_five_smmlv else total
        result = round((total)*porc)*-1
#---------------------------------------Fondo Solidadridad--------------------------------------------------------
result = 0.0
obj_salary_rule = payslip.get_salary_rule('SSOCIAL004',employee.type_employee.id)
if obj_salary_rule and contract.contract_type != 'aprendizaje':
    day_initial_payrroll = payslip.date_from.day
    day_end_payrroll = 30 if payslip.date_to.month == 2 and payslip.date_to.day in (28,29) else payslip.date_to.day
    aplicar = 0 if obj_salary_rule.aplicar_cobro=='30' and inherit_contrato!=0 else int(obj_salary_rule.aplicar_cobro)
    if (aplicar == 0) or (aplicar >= day_initial_payrroll and aplicar <= day_end_payrroll):
        salario_minimo = annual_parameters.smmlv_monthly
        total = categories.DEV_SALARIAL if aplicar == 0 and inherit_contrato==0 else categories.DEV_SALARIAL + payslip.sum_mount('DEV_SALARIAL', payslip.date_from, payslip.date_to)
        # Ley 1393
        if payslip.date_from.day > 15 or (inherit_contrato != 0):
            total_salarial = categories.DEV_SALARIAL + payslip.sum_mount('DEV_SALARIAL', payslip.date_from,
                                                                         payslip.date_to)
            auxtransporte = AUX000 + payslip.sum_mount_x_rule('AUX000', payslip.date_from, payslip.date_to)
            vac_no_salarial = categories.VNS + + payslip.sum_mount('VNS', payslip.date_from, payslip.date_to)
            total_no_salarial = categories.DEV_NO_SALARIAL + payslip.sum_mount('DEV_NO_SALARIAL', payslip.date_from,
                                                                               payslip.date_to) - auxtransporte - vac_no_salarial
            gran_total = total_salarial + total_no_salarial
            statute_value = (gran_total / 100) * annual_parameters.value_porc_statute_1395
            total_statute = total_no_salarial - statute_value
            if total_statute > 0:
                total += total_statute
        # Fin Ley 1393
        dias_work = payslip.sum_days_works('WORK100', payslip.date_from, payslip.date_to)
        dias_work_act = worked_days.WORK100.number_of_days if worked_days.WORK100 else 0
        dias_work = dias_work_act if (aplicar == 0) else dias_work + dias_work_act
        top_twenty_five_smmlv = (annual_parameters.top_twenty_five_smmlv / 30) * dias_work
        if contract.modality_salary == 'integral':
            porc_integral_salary = annual_parameters.porc_integral_salary / 100
            total = total * porc_integral_salary
            total = top_twenty_five_smmlv if total >= top_twenty_five_smmlv else total
        else:
            total = top_twenty_five_smmlv if total >= top_twenty_five_smmlv else total
        if (total/salario_minimo) >= 4 and (total/salario_minimo) < 16:
            result =  round(total * 0.005 * (-1),-2)
        if  (total/salario_minimo) >= 16 and (total/salario_minimo) <= 17:
            result =  round(total * 0.006 * (-1),-2)
        if  (total/salario_minimo) > 17 and (total/salario_minimo) <= 18:
            result =  round(total * 0.007 * (-1),-2)
        if  (total/salario_minimo) > 18 and (total/salario_minimo) <= 19:
            result =  round(total * 0.008 * (-1),-2)
        if  (total/salario_minimo) > 19 and (total/salario_minimo) <= 20:
            result =  round(total * 0.009 * (-1),-2)
        if  (total/salario_minimo) > 20 and (total/salario_minimo) <= 25:
            result =  round(total * 0.01* (-1),-2)
        if  (total/salario_minimo) > 25:
            result =  round(salario_minimo * 25 * 0.01* (-1),-2)    
#---------------------------------------Valor devengos/deducciones & Libranzas --------------------------------------------------------
result = 0.0
obj_salary_rule = payslip.get_salary_rule('AUX001',employee.type_employee.id) 
if obj_salary_rule and worked_days.WORK100 != 0.0:
    obj_concept = payslip.get_concepts(contract.id,obj_salary_rule.id,id_contract_concepts)
    day_initial_payrroll = payslip.date_from.day
    day_end_payrroll = 30 if payslip.date_to.month == 2 and payslip.date_to.day in (28,29) else payslip.date_to.day
    if obj_concept:
        aplicar = 0 if obj_concept.aplicar=='30' and inherit_contrato!=0 else int(obj_concept.aplicar)        
        if (aplicar == 0) or (aplicar >= day_initial_payrroll and aplicar <= day_end_payrroll): # Cambiar por (aplicar >= day_initial_payrroll and day_end_payrroll <= aplicar)
            if obj_salary_rule.modality_value == 'diario':
                dias = worked_days.WORK100.number_of_days
                result = obj_concept.amount * dias if obj_salary_rule.dev_or_ded == 'devengo' else (obj_concept.amount * dias)*-1
            else:
                result = obj_concept.amount if obj_salary_rule.dev_or_ded == 'devengo' else (obj_concept.amount)*-1 
#---------------------------------------Embargo salarial 1/5 smmvl--------------------------------------------------------
result = 0.0
obj_salary_rule = payslip.get_salary_rule('EMBARGO002',employee.type_employee.id) 
if obj_salary_rule:
    obj_concept = payslip.get_concepts(contract.id,obj_salary_rule.id,id_contract_concepts)
    day_initial_payrroll = payslip.date_from.day
    day_end_payrroll = 30 if payslip.date_to.month == 2 and payslip.date_to.day in (28,29) else payslip.date_to.day
    if obj_concept:
        aplicar = 0 if obj_concept.aplicar=='30' and inherit_contrato!=0 else int(obj_concept.aplicar)        
        if (aplicar == 0) or (aplicar >= day_initial_payrroll and aplicar <= day_end_payrroll):
            salario_minimo = annual_parameters.smmlv_monthly/2 if aplicar == 0 else annual_parameters.smmlv_monthly
            total = categories.DEV_SALARIAL + categories.SSOCIAL if aplicar == 0 else categories.DEV_SALARIAL + categories.SSOCIAL + payslip.sum_mount('DEV_SALARIAL', payslip.date_from, payslip.date_to) + payslip.sum_mount('SSOCIAL', payslip.date_from, payslip.date_to)
            val = round((total - salario_minimo)/5)
            result = val*-1 if val > 0 else val
            result_qty = obj_concept.amount if obj_concept.amount != 0 else 0 
#---------------------------------------Embargo salarial %--------------------------------------------------------
result = 0.0
obj_salary_rule = payslip.get_salary_rule('EMBARGO007',employee.type_employee.id) 
if obj_salary_rule:
    obj_concept = payslip.get_concepts(contract.id,obj_salary_rule.id,id_contract_concepts)
    day_initial_payrroll = payslip.date_from.day
    day_end_payrroll = 30 if payslip.date_to.month == 2 and payslip.date_to.day in (28,29) else payslip.date_to.day
    if obj_concept:
        aplicar = 0 if obj_concept.aplicar=='30' and inherit_contrato!=0 else int(obj_concept.aplicar)        
        if (aplicar == 0) or (aplicar >= day_initial_payrroll and aplicar <= day_end_payrroll):
            total = categories.DEV_SALARIAL if aplicar == 0 else categories.DEV_SALARIAL + payslip.sum_mount('DEV_SALARIAL', payslip.date_from, payslip.date_to)
            porc = 15
            result = (round((total)*porc/100)*-1)
            result_qty = obj_concept.amount if obj_concept.amount != 0 else 0           
#---------------------------------------Embargotodo--------------------------------------------------------
result = 0.0
obj_salary_rule = payslip.get_salary_rule('EMBARGO008',employee.type_employee.id) 
if obj_salary_rule:
    obj_concept = payslip.get_concepts(contract.id,obj_salary_rule.id,id_contract_concepts)
    day_initial_payrroll = payslip.date_from.day
    day_end_payrroll = 30 if payslip.date_to.month == 2 and payslip.date_to.day in (28,29) else payslip.date_to.day
    if obj_concept:
        aplicar = 0 if obj_concept.aplicar=='30' and inherit_contrato!=0 else int(obj_concept.aplicar)        
        if (aplicar == 0) or (aplicar >= day_initial_payrroll and aplicar <= day_end_payrroll):
            total = categories.DEV_SALARIAL + categories.DEV_NO_SALARIAL if aplicar == 0 else categories.DEV_SALARIAL + categories.DEV_NO_SALARIAL + payslip.sum_mount('DEV_SALARIAL', payslip.date_from, payslip.date_to) + payslip.sum_mount('DEV_NO_SALARIAL', payslip.date_from, payslip.date_to)
            porc = 15
            result = (round((total)*porc/100)*-1)  
            result_qty = obj_concept.amount if obj_concept.amount != 0 else 0      
#---------------------------------------Horas Extra Diurnas (125%)--------------------------------------------------------
result = 0.0
obj_salary_rule = payslip.get_salary_rule('HEYREC001',employee.type_employee.id)
aplicar = int(obj_salary_rule.aplicar_cobro)
day_initial_payrroll = payslip.date_from.day
day_end_payrroll = 30 if payslip.date_to.month == 2 and payslip.date_to.day in (28,29) else payslip.date_to.day
if ((aplicar == 0) or (aplicar >= day_initial_payrroll and aplicar <= day_end_payrroll)) or (inherit_contrato!=0):
    if obj_salary_rule:
        obj_type_overtime = payslip.get_type_overtime(obj_salary_rule.id)
        obj_overtime = payslip.get_overtime(employee.id,payslip.date_from, payslip.date_to, inherit_contrato,aplicar)
        if len(obj_overtime) > 0:
            r_qty = 0
            for overtime in obj_overtime:
                if obj_type_overtime.type_overtime == 'overtime_ext_d' and overtime.overtime_ext_d > 0:
                    r_qty += overtime.overtime_ext_d
            result = round((contract.wage /240)*1.25)  if r_qty > 0 else 0
            result_qty = r_qty
#---------------------------------------Horas extra diurnas dominical / festiva (200%)--------------------------------------------------------
result = 0.0
obj_salary_rule = payslip.get_salary_rule('HEYREC002',employee.type_employee.id)
aplicar = int(obj_salary_rule.aplicar_cobro)
day_initial_payrroll = payslip.date_from.day
day_end_payrroll = 30 if payslip.date_to.month == 2 and payslip.date_to.day in (28,29) else payslip.date_to.day
if ((aplicar == 0) or (aplicar >= day_initial_payrroll and aplicar <= day_end_payrroll)) or (inherit_contrato!=0):
    if obj_salary_rule:
        obj_type_overtime = payslip.get_type_overtime(obj_salary_rule.id)
        obj_overtime = payslip.get_overtime(employee.id,payslip.date_from, payslip.date_to, inherit_contrato,aplicar)
        if len(obj_overtime) > 0:
            r_qty = 0
            for overtime in obj_overtime:
                if obj_type_overtime.type_overtime == 'overtime_eddf' and overtime.overtime_eddf > 0:
                    r_qty += overtime.overtime_eddf
            result = round((contract.wage /240)*2)  if r_qty > 0 else 0
            result_qty = r_qty
#---------------------------------------Horas extra nocturna (175%)--------------------------------------------------------
result = 0.0
obj_salary_rule = payslip.get_salary_rule('HEYREC003',employee.type_employee.id)
aplicar = int(obj_salary_rule.aplicar_cobro)
day_initial_payrroll = payslip.date_from.day
day_end_payrroll = 30 if payslip.date_to.month == 2 and payslip.date_to.day in (28,29) else payslip.date_to.day
if ((aplicar == 0) or (aplicar >= day_initial_payrroll and aplicar <= day_end_payrroll)) or (inherit_contrato!=0):
    if obj_salary_rule:
        obj_type_overtime = payslip.get_type_overtime(obj_salary_rule.id)
        obj_overtime = payslip.get_overtime(employee.id,payslip.date_from, payslip.date_to, inherit_contrato,aplicar)
        if len(obj_overtime) > 0:
            r_qty = 0
            for overtime in obj_overtime:
                if obj_type_overtime.type_overtime == 'overtime_ext_n' and overtime.overtime_ext_n > 0:
                    r_qty += overtime.overtime_ext_n
            result = round((contract.wage /240)*1.75)  if r_qty > 0 else 0
            result_qty = r_qty
#---------------------------------------Horas recargo festivo (110%)--------------------------------------------------------
result = 0.0
obj_salary_rule = payslip.get_salary_rule('HEYREC004',employee.type_employee.id)
aplicar = int(obj_salary_rule.aplicar_cobro)
day_initial_payrroll = payslip.date_from.day
day_end_payrroll = 30 if payslip.date_to.month == 2 and payslip.date_to.day in (28,29) else payslip.date_to.day
if ((aplicar == 0) or (aplicar >= day_initial_payrroll and aplicar <= day_end_payrroll)) or (inherit_contrato!=0):
    if obj_salary_rule:
        obj_type_overtime = payslip.get_type_overtime(obj_salary_rule.id)
        obj_overtime = payslip.get_overtime(employee.id,payslip.date_from, payslip.date_to, inherit_contrato,aplicar)
        if len(obj_overtime) > 0:
            r_qty = 0
            for overtime in obj_overtime:
                if obj_type_overtime.type_overtime == 'overtime_rndf' and overtime.overtime_rndf > 0:
                    r_qty += overtime.overtime_rndf
            result = round((contract.wage /240)*1.1)  if r_qty > 0 else 0
            result_qty = r_qty
#---------------------------------------Recargos dominicales (0.75%)--------------------------------------------------------
result = 0.0
obj_salary_rule = payslip.get_salary_rule('HEYREC008',employee.type_employee.id)
aplicar = int(obj_salary_rule.aplicar_cobro)
day_initial_payrroll = payslip.date_from.day
day_end_payrroll = 30 if payslip.date_to.month == 2 and payslip.date_to.day in (28,29) else payslip.date_to.day
if ((aplicar == 0) or (aplicar >= day_initial_payrroll and aplicar <= day_end_payrroll)) or (inherit_contrato!=0):
    if obj_salary_rule:
        obj_type_overtime = payslip.get_type_overtime(obj_salary_rule.id)
        obj_overtime = payslip.get_overtime(employee.id, payslip.date_from, payslip.date_to, inherit_contrato, aplicar)
        if len(obj_overtime) > 0:
            r_qty = 0
            for overtime in obj_overtime:
                if obj_type_overtime.type_overtime == 'overtime_rdf' and overtime.overtime_rdf > 0:
                    r_qty += overtime.overtime_rdf
            result = round((contract.wage / 240) * 0.75)  if r_qty > 0 else 0
            result_qty = r_qty
#---------------------------------------Horas Dominicales (175%)--------------------------------------------------------
result = 0.0
obj_salary_rule = payslip.get_salary_rule('HEYREC007',employee.type_employee.id)
aplicar = int(obj_salary_rule.aplicar_cobro)
day_initial_payrroll = payslip.date_from.day
day_end_payrroll = 30 if payslip.date_to.month == 2 and payslip.date_to.day in (28,29) else payslip.date_to.day
if ((aplicar == 0) or (aplicar >= day_initial_payrroll and aplicar <= day_end_payrroll)) or (inherit_contrato!=0):
    if obj_salary_rule:
        obj_type_overtime = payslip.get_type_overtime(obj_salary_rule.id)
        obj_overtime = payslip.get_overtime(employee.id,payslip.date_from, payslip.date_to, inherit_contrato,aplicar)
        if len(obj_overtime) > 0:
            r_qty = 0
            for overtime in obj_overtime:
                if obj_type_overtime.type_overtime == 'overtime_dof' and overtime.overtime_dof > 0:
                    r_qty += overtime.overtime_dof
            result = round((contract.wage /240)*1.75)  if r_qty > 0 else 0
            result_qty = r_qty
#---------------------------------------Horas Recargo Nocturno (35%)--------------------------------------------------------
result = 0.0
obj_salary_rule = payslip.get_salary_rule('HEYREC005',employee.type_employee.id)
aplicar = int(obj_salary_rule.aplicar_cobro)
day_initial_payrroll = payslip.date_from.day
day_end_payrroll = 30 if payslip.date_to.month == 2 and payslip.date_to.day in (28,29) else payslip.date_to.day
if ((aplicar == 0) or (aplicar >= day_initial_payrroll and aplicar <= day_end_payrroll)) or (inherit_contrato!=0):
    if obj_salary_rule:
        obj_type_overtime = payslip.get_type_overtime(obj_salary_rule.id)
        obj_overtime = payslip.get_overtime(employee.id,payslip.date_from, payslip.date_to, inherit_contrato,aplicar)
        if len(obj_overtime) > 0:
            r_qty = 0
            for overtime in obj_overtime:
                if obj_type_overtime.type_overtime == 'overtime_rn' and overtime.overtime_rn > 0:
                    r_qty += overtime.overtime_rn
            result = round((contract.wage /240)*0.35)  if r_qty > 0 else 0
            result_qty = r_qty
#---------------------------------------Horas extra nocturna dominical / festiva (250%)--------------------------------------------------------
result = 0.0
obj_salary_rule = payslip.get_salary_rule('HEYREC006',employee.type_employee.id)
aplicar = int(obj_salary_rule.aplicar_cobro)
day_initial_payrroll = payslip.date_from.day
day_end_payrroll = 30 if payslip.date_to.month == 2 and payslip.date_to.day in (28,29) else payslip.date_to.day
if ((aplicar == 0) or (aplicar >= day_initial_payrroll and aplicar <= day_end_payrroll)) or (inherit_contrato!=0):
    if obj_salary_rule:
        obj_type_overtime = payslip.get_type_overtime(obj_salary_rule.id)
        obj_overtime = payslip.get_overtime(employee.id,payslip.date_from, payslip.date_to, inherit_contrato,aplicar)
        if len(obj_overtime) > 0:
            r_qty = 0
            for overtime in obj_overtime:
                if obj_type_overtime.type_overtime == 'overtime_endf' and overtime.overtime_endf > 0:
                    r_qty += overtime.overtime_endf
            result = round((contract.wage /240)*2.5) if r_qty > 0 else 0
            result_qty = r_qty
#---------------------------------------Horas dominicales--------------------------------------------------------
result = 0.0
obj_salary_rule = payslip.get_salary_rule('HEYREC007',employee.type_employee.id)
aplicar = int(obj_salary_rule.aplicar_cobro)
day_initial_payrroll = payslip.date_from.day
day_end_payrroll = 30 if payslip.date_to.month == 2 and payslip.date_to.day in (28,29) else payslip.date_to.day
if ((aplicar == 0) or (aplicar >= day_initial_payrroll and aplicar <= day_end_payrroll)) or (inherit_contrato!=0):
    if obj_salary_rule:
        obj_type_overtime = payslip.get_type_overtime(obj_salary_rule.id)
        obj_overtime = payslip.get_overtime(employee.id,payslip.date_from, payslip.date_to, inherit_contrato,aplicar)
        if len(obj_overtime) > 0:
            r_qty = 0
            for overtime in obj_overtime:
                if obj_type_overtime.type_overtime == 'overtime_dof' and overtime.overtime_dof > 0:
                    r_qty += overtime.overtime_dof
            result = round((contract.wage /240)*0.75)  if r_qty > 0 else 0
            result_qty = r_qty
#---------------------------------------Dias efectivamente laborados--------------------------------------------------------
result = 0.0
obj_salary_rule = payslip.get_salary_rule('AUX005',employee.type_employee.id)
aplicar = int(obj_salary_rule.aplicar_cobro)
day_initial_payrroll = payslip.date_from.day
day_end_payrroll = 30 if payslip.date_to.month == 2 and payslip.date_to.day in (28,29) else payslip.date_to.day
if ((aplicar == 0) or (aplicar >= day_initial_payrroll and aplicar <= day_end_payrroll)) or (inherit_contrato!=0):
    if obj_salary_rule:
        if obj_salary_rule.modality_value == 'diario_efectivo':
            obj_concept = payslip.get_concepts(contract.id,obj_salary_rule.id,id_contract_concepts)
            obj_overtime = payslip.get_overtime(employee.id,payslip.date_from, payslip.date_to, inherit_contrato,aplicar)
            if obj_overtime and obj_concept:
                if obj_overtime.days_actually_worked > 0:
                    result = obj_concept.amount#contract.wage / 30
                    result_qty = obj_overtime.days_actually_worked
#---------------------------------------Incapacidad EPS--------------------------------------------------------
#Odoo V8
result = 0.0
obj_salary_rule = payslip.get_salary_rule('INCAPACIDAD001',employee.type_employee.id)
if obj_salary_rule:
    if worked_days.EGA != 0.0:
        obj_leave_type = payslip.get_leave_type('EGA')
        if obj_leave_type.eps_arl_input_id.id == obj_salary_rule.id:
            days = worked_days.EGA.number_of_days - obj_leave_type.num_days_no_assume 
            days = days if days >= 0 else 0 
            result =  (contract.wage*2/3) /30
            result_qty = days
#Odoo V13
result = 0.0
obj_salary_rule = payslip.get_salary_rule('INCAPACIDAD001',employee.type_employee.id)
if obj_salary_rule:
    if worked_days.EGA != 0.0 and leaves.EGA <= 90:
        obj_leave_type = payslip.get_leave_type('EGA')
        if obj_leave_type.eps_arl_input_id.id == obj_salary_rule.id:
            salario_minimo = annual_parameters.smmlv_monthly
            ibc_real = (contract.wage * obj_leave_type.recognizing_factor_eps_arl)
            ibc_real = salario_minimo if contract.modality_salary != 'sostenimiento' and (contract.wage * obj_leave_type.recognizing_factor_eps_arl) < salario_minimo else (contract.wage * obj_leave_type.recognizing_factor_eps_arl)
            days = worked_days.EGA.number_of_days - obj_leave_type.num_days_no_assume if worked_days.EGA.number_of_days >= leaves.EGA else worked_days.EGA.number_of_days
            days = days if days >= 0 else 0 
            result =  (ibc_real) /30
            result_qty = days
#---------------------------------------Incapacidad Compañía--------------------------------------------------------
#Odoo V8
result = 0.0
obj_salary_rule = payslip.get_salary_rule('INCAPACIDAD002',employee.type_employee.id)
if obj_salary_rule:
    if worked_days.EGA != 0.0:
        obj_leave_type = payslip.get_leave_type('EGA')
        if obj_leave_type.company_input_id.id == obj_salary_rule.id:
            days = obj_leave_type.num_days_no_assume 
            result =  (contract.wage*2/3) /30   
            result_qty = days
#Odoo V13
result = 0.0
obj_salary_rule = payslip.get_salary_rule('INCAPACIDAD002',employee.type_employee.id)
if obj_salary_rule:
    if worked_days.EGA != 0.0 and leaves.EGA <= 90:
        obj_leave_type = payslip.get_leave_type('EGA')
        if obj_leave_type.company_input_id.id == obj_salary_rule.id:
            salario_minimo = annual_parameters.smmlv_monthly
            ibc_real = (contract.wage * obj_leave_type.recognizing_factor_company)
            ibc_real = salario_minimo if contract.modality_salary != 'sostenimiento' and (contract.wage * obj_leave_type.recognizing_factor_company) < salario_minimo else (contract.wage * obj_leave_type.recognizing_factor_company)
            days = (worked_days.EGA.number_of_days if worked_days.EGA.number_of_days <= obj_leave_type.num_days_no_assume else obj_leave_type.num_days_no_assume) if worked_days.EGA.number_of_days >= leaves.EGA else 0
            if days > 0:
                result =  (ibc_real) /30
                result_qty = days
#---------------------------------------Incapacidad EPS 50%--------------------------------------------------------
result = 0.0
obj_salary_rule = payslip.get_salary_rule('INCAPACIDAD007',employee.type_employee.id)
if obj_salary_rule:
    if worked_days.EGA != 0.0 and ((leaves.EGA > 90 and leaves.EGA <= 180) or leaves.EGA > 540):
        obj_leave_type = payslip.get_leave_type('EGA')
        if obj_leave_type:
            salario_minimo = annual_parameters.smmlv_monthly
            ibc_real = (contract.wage * 0.5)
            days = worked_days.EGA.number_of_days 
            days = days if days >= 0 else 0 
            result =  (ibc_real) /30
            result_qty = days
#---------------------------------------Licencia remunerada--------------------------------------------------------
result = 0.0
obj_salary_rule = payslip.get_salary_rule('LICENCIA001',employee.type_employee.id)
if obj_salary_rule and worked_days.LICENCIA_REMUNERADA != 0.0:
        result =  round(worked_days.LICENCIA_REMUNERADA.number_of_days * (contract.wage /30))  
#---------------------------------------Retención en la fuente--------------------------------------------------------
result = 0.0
obj_salary_rule = payslip.get_salary_rule('RETFTE001',employee.type_employee.id)
if obj_salary_rule and contract.contract_type != 'aprendizaje':
    day_initial_payrroll = payslip.date_from.day
    day_end_payrroll = 30 if payslip.date_to.month == 2 and payslip.date_to.day in (28,29) else payslip.date_to.day
    aplicar = 0 if obj_salary_rule.aplicar_cobro=='30' and inherit_contrato!=0 else int(obj_salary_rule.aplicar_cobro)
    if (aplicar == 0) or (aplicar >= day_initial_payrroll and aplicar <= day_end_payrroll):
        if contract.retention_procedure != 'fixed':
            if contract.wage >= annual_parameters.value_top_source_retention:
                localdict = {
                            'categories': categories,
                            'rules_computed': rules_computed,
                            'payslip': payslip,
                            'employee': employee,
                            'contract': contract,
                            'annual_parameters':annual_parameters
                        }
                obj_retention = payslip.get_deduction_retention(employee.id, payslip.date_to,contract.retention_procedure, localdict)
                result = (obj_retention.result_calculation) * -1
        else:
            result = (contract.fixed_value_retention_procedure) * -1
#---------------------------------------Cuota Sindical--------------------------------------------------------
result = 0.0
obj_salary_rule = payslip.get_salary_rule('CUOTA001',employee.type_employee.id) 
if obj_salary_rule:
    obj_concept = payslip.get_concepts(contract.id,obj_salary_rule.id,id_contract_concepts)
    day_initial_payrroll = payslip.date_from.day
    day_end_payrroll = 30 if payslip.date_to.month == 2 and payslip.date_to.day in (28,29) else payslip.date_to.day
    if obj_concept:
        aplicar = 0 if obj_concept.aplicar=='30' and inherit_contrato!=0 else int(obj_concept.aplicar)         
        if (aplicar == 0) or (aplicar >= day_initial_payrroll and aplicar <= day_end_payrroll): 
            result = (((contract.wage/100)*1)/2)*-1 # Corresponde al 1% del salario
        else:
            result = ((contract.wage/100)*1)*-1 # Corresponde al 1% del salario

#---------------------------------------------------------------------------------------------------------------------------------------
#---------------------------------------------------------------------------------------------------------------------------------------
#---------------------------------------------------------------------------------------------------------------------------------------
#------------------------------------------------------LIQUIDACION DE VACACIONES--------------------------------------------------------

#---------------------------------------Vacaciones Liq Contrato Base-----------------------------------------------------------------------
result = 0.0
obj_salary_rule = payslip.get_salary_rule('VACCONTRATO',employee.type_employee.id)
if obj_salary_rule and inherit_contrato != 0:
    date_start = payslip.date_vacaciones
    date_end = payslip.date_liquidacion
    #Obtener acumulados
    accumulated = payslip.get_accumulated_vacation_money(date_end) + values_base_vacremuneradas
    result = accumulated

#---------------------------------------Vacaciones Disfrutadas-----------------------------------------------------------------------
result = 0.0
obj_salary_rule = payslip.get_salary_rule('VACDISFRUTADAS',employee.type_employee.id)
if obj_salary_rule:
    if leaves.VACDISFRUTADAS != 0.0:
        accumulated = payslip.get_accumulated_vacation(payslip.date_from) / 360
        amount = contract.wage / 30      
        result =  accumulated + amount
        result_qty = leaves.VACDISFRUTADAS

#---------------------------------------Vacaciones Disfrutadas - Días Habiles--------------------------------------------------------
result = 0.0
obj_salary_rule = payslip.get_salary_rule('VAC001',employee.type_employee.id)
if obj_salary_rule:
    if leaves.BUSINESSVACDISFRUTADAS != 0.0:
        accumulated = payslip.get_accumulated_vacation(payslip.date_from) / 360
        amount = contract.wage / 30      
        result =  accumulated + amount
        result_qty = leaves.BUSINESSVACDISFRUTADAS

#---------------------------------------Vacaciones Disfrutadas - Días Festivos--------------------------------------------------------
result = 0.0
obj_salary_rule = payslip.get_salary_rule('VAC002',employee.type_employee.id)
if obj_salary_rule:
    if leaves.HOLIDAYSVACDISFRUTADAS != 0.0:
        accumulated = payslip.get_accumulated_vacation(payslip.date_from) / 360
        amount = contract.wage / 30      
        result =  accumulated + amount
        result_qty = leaves.HOLIDAYSVACDISFRUTADAS
        
#---------------------------------------Vacaciones Remuneradas--------------------------------------------------------
result = 0.0
obj_salary_rule = payslip.get_salary_rule('VACREMUNERADAS',employee.type_employee.id)
if obj_salary_rule:
    if leaves.VACREMUNERADAS != 0.0:
        accumulated = payslip.get_accumulated_vacation_money(payslip.date_from) / 360
        amount = contract.wage / 30      
        result =  accumulated + amount
        result_qty = leaves.VACREMUNERADAS        
#---------------------------------------Auxilio vacaciones pacto colectivo--------------------------------------------------------
result = 0.0
obj_salary_rule = payslip.get_salary_rule('AUXLIOVAC001',employee.type_employee.id)
if obj_salary_rule and employee.ed_qualification >= 4.5:
    obj_assistance_vacation = payslip.get_assistance_vacation(antiquity_employee)
    result = (contract.wage / 30) * obj_assistance_vacation.vacation_relief 

#---------------------------------------Auxilio vacaciones convención--------------------------------------------------------
result = 0.0
obj_salary_rule = payslip.get_salary_rule('AUXLIOVAC002',employee.type_employee.id)
if obj_salary_rule:
    if employee.branch_id.name == 'Cartagena' and employee.labor_union_information:        
        obj_assistance_vacation = payslip.get_assistance_vacation(antiquity_employee)
        result = (contract.wage / 30) * obj_assistance_vacation.convention_vacation     


#---------------------------------------------------------------------------------------------------------------------------------------
#---------------------------------------------------------------------------------------------------------------------------------------
#---------------------------------------------------------------------------------------------------------------------------------------
#------------------------------------------------------LIQUIDACION DE CESANTIAS--------------------------------------------------------

#---------------------------------------Cesantias Base--------------------------------------------------------
result = 0.0
obj_salary_rule = payslip.get_salary_rule('CESANTIAS',employee.type_employee.id)
if obj_salary_rule:
    date_start = payslip.date_from
    date_end = payslip.date_to
    if inherit_contrato != 0:
        date_start = payslip.date_cesantias
        date_end = payslip.date_liquidacion
    #Obtener acumulados
    accumulated = payslip.get_accumulated_cesantias(date_start,date_end) + values_base_cesantias
    result = accumulated

#---------------------------------------Intereses de Cesantias Base--------------------------------------------------------
result = 0.0
obj_salary_rule = payslip.get_salary_rule('INTCESANTIAS',employee.type_employee.id)
if obj_salary_rule:
    date_start = payslip.date_from
    date_end = payslip.date_to
    if inherit_contrato != 0:
        date_start = payslip.date_cesantias
        date_end = payslip.date_liquidacion
    #Obtener acumulados
    accumulated = payslip.get_accumulated_cesantias(date_start,date_end) + values_base_cesantias
    result = accumulated

#---------------------------------------------------------------------------------------------------------------------------------------
#---------------------------------------------------------------------------------------------------------------------------------------
#---------------------------------------------------------------------------------------------------------------------------------------
#------------------------------------------------------LIQUIDACION DE PRIMA--------------------------------------------------------

#---------------------------------------Prima Base--------------------------------------------------------
result = 0.0
obj_salary_rule = payslip.get_salary_rule('PRIMA',employee.type_employee.id)
if obj_salary_rule:
    date_start = payslip.date_from
    date_end = payslip.date_to
    if inherit_contrato != 0:
        date_start = payslip.date_prima
        date_end = payslip.date_liquidacion
    #Obtener acumulados
    accumulated = payslip.get_accumulated_prima(date_start,date_end) + values_base_prima
    result = accumulated


#---------------------------------------------------------------------------------------------------------------------------------------
#---------------------------------------------------------------------------------------------------------------------------------------
#---------------------------------------------------------------------------------------------------------------------------------------
#------------------------------------------------------LIQUIDACION DE CONTRATO--------------------------------------------------------


#---------------------------------------Indemnización contrato diferente a termino fijo--------------------------------------------------------
result = 0.0
if payslip.have_compensation and contract.contract_type != 'fijo' and contract.modality_salary != 'integral':
    dias = payslip.days_between(contract.date_start, payslip.date_liquidacion)
    antiguedad = dias / 360.0
    vr_mas_ano = 0.0
    vr_ano = 0.0

    salario =  contract.wage
    date_to = contract.date_to if contract.date_to else contract.date_end

    if date_to:
        dias_indemnizados = payslip.days_between(payslip.date_liquidacion, date_to)
        dias_indemnizados = dias_indemnizados - 1
    else:
        dias_indemnizados = 0

    if dias_indemnizados == 0:
        if round(salario / annual_parameters.smmlv_monthly) < 10.0:     
            vr_ano = salario
            if antiguedad > 1:   
                vr_mas_ano = (((dias - 360.0) * 20.0)/360.0) * (salario /30.0)
        else:
            vr_ano = round((salario /30.0)*20.0) 
            if antiguedad > 1:   
                vr_mas_ano = (((dias - 360.0) * 15.0)/360.0) * (salario /30.0)
    else:
        vr_ano = dias_indemnizados * (salario /30.0)
    
    result = round(vr_ano + vr_mas_ano)

#---------------------------------------Indemnización contrato termino fijo--------------------------------------------------------
result = 0.0
if payslip.have_compensation and contract.contract_type == 'fijo' and contract.modality_salary != 'integral':
    date_to = contract.date_to if contract.date_to else contract.date_end
    dias = payslip.days_between(payslip.date_liquidacion, date_to)     
    salario_dia =  contract.wage/30
    result = salario_dia
    result_qty = dias

#---------------------------------------Indemnización salario integral--------------------------------------------------------
result = 0.0
if payslip.have_compensation and contract.modality_salary == 'integral':
    dias = payslip.days_between(contract.date_start, payslip.date_liquidacion)
    antiguedad = dias / 360.0
    vr_mas_ano = 0.0
    vr_ano = 0.0
    salario=contract.wage
    vr_ano = round(salario/30.0)*20.0 
    if antiguedad > 1:   
        vr_mas_ano = (((dias - 360.0) * 15.0)/360.0) * (salario/30.0)
    
    result = round(vr_ano + vr_mas_ano)

#---------------------------------------------------------------------------------------------------------------------------------------
#---------------------------------------------------------------------------------------------------------------------------------------
#---------------------------------------------------------------------------------------------------------------------------------------
#------------------------------------------------------TOTALES--------------------------------------------------------

#---------------------------------------Total devengos--------------------------------------------------------
if inherit_contrato != 0:
    result = categories.DEV_SALARIAL + categories.DEV_NO_SALARIAL + categories.PRESTACIONES_SOCIALES
else:
    result = categories.DEV_SALARIAL + categories.DEV_NO_SALARIAL

#---------------------------------------Total deducciones--------------------------------------------------------
result = categories.DEDUCCIONES

#---------------------------------------Neto a pagar--------------------------------------------------------
if inherit_contrato != 0:
    result = categories.DEV_SALARIAL + categories.DEV_NO_SALARIAL + categories.PRESTACIONES_SOCIALES + categories.DEDUCCIONES
else:
    result = categories.DEV_SALARIAL + categories.DEV_NO_SALARIAL + categories.DEDUCCIONES
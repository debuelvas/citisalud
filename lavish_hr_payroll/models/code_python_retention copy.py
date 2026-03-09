# --------------------------------------------------------------------------------------------------------------------
# ------------------------------------- Tipo de impuesto RETEFUENTE METODO ORDINARIO NÓMINA -----------------------
# --------------------------------------------------------------------------------------------------------------------
#SALARIO_O
result = payslip.sum_mount('BASIC', payslip.date_from, payslip.date_to) + categories.BASIC
#COMISIONES_O
result = payslip.sum_mount('COMISIONES', payslip.date_from, payslip.date_to) + categories.COMISIONES
#OTROS_ING_GRAV_O
dev_salarial = (payslip.sum_mount('DEV_SALARIAL', payslip.date_from, payslip.date_to) + categories.DEV_SALARIAL)
dev_no_salarial = (payslip.sum_mount('DEV_NO_SALARIAL', payslip.date_from, payslip.date_to) + categories.DEV_NO_SALARIAL)
values_ant = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'SALARIO_O').result_calculation - payslip.get_deduction_retention_value(employee.id,payslip.date_to,'COMISIONES_O').result_calculation
result = dev_salarial + dev_no_salarial - values_ant
#TOTAL_ING_BASE_O
result = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'SALARIO_O').result_calculation + payslip.get_deduction_retention_value(employee.id,payslip.date_to,'COMISIONES_O').result_calculation + payslip.get_deduction_retention_value(employee.id,payslip.date_to,'OTROS_ING_GRAV_O').result_calculation
#RE_AP_PENSION_O
value_pension = payslip.sum_mount_x_rule('SSOCIAL002', payslip.date_from, payslip.date_to) + rules_computed.SSOCIAL002
value_fondo_subsistencia = payslip.sum_mount_x_rule('SSOCIAL003', payslip.date_from, payslip.date_to) + rules_computed.SSOCIAL003
value_fondo_solidaridad = payslip.sum_mount_x_rule('SSOCIAL004', payslip.date_from, payslip.date_to) + rules_computed.SSOCIAL004
result = abs(value_pension + value_fondo_subsistencia + value_fondo_solidaridad)
#DED_APT_SALUD_O
result = abs(payslip.sum_mount_x_rule('SSOCIAL001', payslip.date_from, payslip.date_to) + rules_computed.SSOCIAL001)
#ING_NO_GRAVADOS_O
result = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RE_AP_PENSION_O').result_calculation + payslip.get_deduction_retention_value(employee.id,payslip.date_to,'DED_APT_SALUD_O').result_calculation
#ING_BASE_O
result = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'TOTAL_ING_BASE_O').result_calculation - payslip.get_deduction_retention_value(employee.id,payslip.date_to,'ING_NO_GRAVADOS_O').result_calculation
#DED_VIVIENDA_O
result = payslip.get_contract_deductions_rtf(contract.id,payslip.date_to,'INTVIV').value_monthly
result = annual_parameters.value_uvt*100 if result > annual_parameters.value_uvt*100 else result
#DED_DEPENDIENTES_O
result = payslip.get_contract_deductions_rtf(contract.id,payslip.date_to,'DEDDEP').value_monthly
if result > 0:
    result = (payslip.get_deduction_retention_value(employee.id,payslip.date_to,'TOTAL_ING_BASE_O').result_calculation * 0.1000) 
    result = annual_parameters.value_uvt*32 if result > annual_parameters.value_uvt*32 else result
#DED_MPREPAGADA_O
result = payslip.get_contract_deductions_rtf(contract.id,payslip.date_to,'MEDPRE').value_monthly
result = annual_parameters.value_uvt*16 if result > annual_parameters.value_uvt*16 else result
#TOTAL_DEDUCCIONES_O
result = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'DED_VIVIENDA_O').result_calculation + payslip.get_deduction_retention_value(employee.id,payslip.date_to,'DED_DEPENDIENTES_O').result_calculation + payslip.get_deduction_retention_value(employee.id,payslip.date_to,'DED_MPREPAGADA_O').result_calculation
#SUBTOTAL_IBR1_O
result = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'ING_BASE_O').result_calculation - payslip.get_deduction_retention_value(employee.id,payslip.date_to,'TOTAL_DEDUCCIONES_O').result_calculation
#RE_AP_VOL_PENSION_O
result = 0.0
#RE_AP_AFC_O
result = abs(payslip.sum_mount_x_rule('AFC', payslip.date_from, payslip.date_to) + rules_computed.AFC)
#RE_GTOS_ENTIERRO_O | RE_GTOS_REP_O | RE_GTOS_EXC_FARM_O | RE_INDEMNIZACIONES_O
result = 0.0
#TOTAL_RE_O
RE_AP_VOL_PENSION_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RE_AP_VOL_PENSION_O').result_calculation
RE_AP_AFC_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RE_AP_AFC_O').result_calculation
RE_GTOS_ENTIERRO_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RE_GTOS_ENTIERRO_O').result_calculation
RE_GTOS_REP_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RE_GTOS_REP_O').result_calculation
RE_GTOS_EXC_FARM_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RE_GTOS_EXC_FARM_O').result_calculation
RE_INDEMNIZACIONES_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RE_INDEMNIZACIONES_O').result_calculation
TOTAL_ING_BASE_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'TOTAL_ING_BASE_O').result_calculation

if (RE_AP_VOL_PENSION_O + RE_AP_AFC_O + RE_GTOS_ENTIERRO_O + RE_GTOS_REP_O + RE_GTOS_EXC_FARM_O + RE_INDEMNIZACIONES_O > TOTAL_ING_BASE_O * 0.3):
  result = (TOTAL_ING_BASE_O * 0.3)
else:
  result = RE_AP_VOL_PENSION_O + RE_AP_AFC_O + RE_GTOS_ENTIERRO_O + RE_GTOS_REP_O + RE_GTOS_EXC_FARM_O + RE_INDEMNIZACIONES_O

result = annual_parameters.value_uvt * (3800.00/12.00) if result > annual_parameters.value_uvt * (3800.00/12.00) else result
#TOTAL_RE_CONT_AFC_O
RE_AP_VOL_PENSION_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RE_AP_VOL_PENSION_O').result_calculation
RE_GTOS_ENTIERRO_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RE_GTOS_ENTIERRO_O').result_calculation
RE_GTOS_REP_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RE_GTOS_REP_O').result_calculation
RE_GTOS_EXC_FARM_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RE_GTOS_EXC_FARM_O').result_calculation

RE_INDEMNIZACIONES_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RE_INDEMNIZACIONES_O').result_calculation

result = RE_AP_VOL_PENSION_O  + RE_GTOS_ENTIERRO_O + RE_GTOS_REP_O + RE_GTOS_EXC_FARM_O + RE_INDEMNIZACIONES_O
#TOTAL_RE_CONT_AVP_O
ING_NO_GRAVADOS_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'ING_NO_GRAVADOS_O').result_calculation
RE_AP_AFC_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RE_AP_AFC_O').result_calculation
RE_GTOS_ENTIERRO_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RE_GTOS_ENTIERRO_O').result_calculation
RE_GTOS_REP_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RE_GTOS_REP_O').result_calculation
RE_GTOS_EXC_FARM_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RE_GTOS_EXC_FARM_O').result_calculation
RE_INDEMNIZACIONES_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RE_INDEMNIZACIONES_O').result_calculation

TOTAL_ING_BASE_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'ING_BASE_O').result_calculation

if (ING_NO_GRAVADOS_O +  RE_AP_AFC_O + RE_GTOS_ENTIERRO_O + RE_GTOS_REP_O + RE_GTOS_EXC_FARM_O + RE_INDEMNIZACIONES_O > TOTAL_ING_BASE_O * 0.3):
    result = (TOTAL_ING_BASE_O * 0.3) - ING_NO_GRAVADOS_O
else:
    result =  RE_AP_AFC_O + RE_GTOS_ENTIERRO_O + RE_GTOS_REP_O + RE_GTOS_EXC_FARM_O + RE_INDEMNIZACIONES_O
#SUBTOTAL_IBR2_O
SUBTOTAL_IBR1_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'SUBTOTAL_IBR1_O').result_calculation
TOTAL_RE_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'TOTAL_RE_O').result_calculation
result = SUBTOTAL_IBR1_O - TOTAL_RE_O
#SUBT_IBR2_CONT_AFC_O
SUBTOTAL_IBR1_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'SUBTOTAL_IBR1_O').result_calculation
TOTAL_RE_CONT_AFC_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'TOTAL_RE_CONT_AFC_O').result_calculation
result = SUBTOTAL_IBR1_O - TOTAL_RE_CONT_AFC_O
#SUBT_IBR2_CONT_AVP_O
SUBTOTAL_IBR1_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'SUBTOTAL_IBR1_O').result_calculation
TOTAL_RE_CONT_AVP_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'TOTAL_RE_CONT_AVP_O').result_calculation
result = SUBTOTAL_IBR1_O - TOTAL_RE_CONT_AVP_O
#RE_RENTA_EXENTA_O
SUBTOTAL_IBR2_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'SUBTOTAL_IBR2_O').result_calculation
result = round(SUBTOTAL_IBR2_O * (25 / 100.000), -3)
result = annual_parameters.value_uvt * (790.000/12.000) if result > annual_parameters.value_uvt * (790.000/12.000) else result
#RE_RENTA_EXE_AFC_O
SUBT_IBR2_CONT_AFC_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'SUBT_IBR2_CONT_AFC_O').result_calculation
result = round(SUBT_IBR2_CONT_AFC_O * (25 / 100.000), -3)
result = annual_parameters.value_uvt * (790.000/12.000) if result > annual_parameters.value_uvt * (790.000/12.000) else result
#RE_RENTA_EXE_AVP_O
SUBT_IBR2_CONT_AVP_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'SUBT_IBR2_CONT_AVP_O').result_calculation
result = round(SUBT_IBR2_CONT_AVP_O * (25 / 100.000), -3)
result = annual_parameters.value_uvt * (790.000/12.000) if result > annual_parameters.value_uvt * (790.000/12.000) else result
#SUBTOTAL_IBR3_O
TOTAL_DEDUCCIONES_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'TOTAL_DEDUCCIONES_O').result_calculation
TOTAL_RE_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'TOTAL_RE_O').result_calculation
RE_RENTA_EXENTA_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RE_RENTA_EXENTA_O').result_calculation
ING_BASE_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'ING_BASE_O').result_calculation
SUBTOTAL_IBR2_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'SUBTOTAL_IBR2_O').result_calculation
result = (SUBTOTAL_IBR2_O - RE_RENTA_EXENTA_O)
base = min((TOTAL_DEDUCCIONES_O + TOTAL_RE_O + RE_RENTA_EXENTA_O),(ING_BASE_O * 0.4))
if (base > (annual_parameters.value_uvt * (1340.00/12.00))):
    result = (annual_parameters.value_uvt * (1340.00/12.00))
else:
    result = ING_BASE_O-base
#SUBT_IBR3_AFC_O
SUBT_IBR2_CONT_AFC_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'SUBT_IBR2_CONT_AFC_O').result_calculation
RE_RENTA_EXE_AFC_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RE_RENTA_EXE_AFC_O').result_calculation
result = SUBT_IBR2_CONT_AFC_O - RE_RENTA_EXE_AFC_O
TOTAL_DEDUCCIONES_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'TOTAL_DEDUCCIONES_O').result_calculation
TOTAL_RE_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'TOTAL_RE_O').result_calculation
RE_RENTA_EXENTA_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RE_RENTA_EXENTA_O').result_calculation
ING_BASE_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'ING_BASE_O').result_calculation
base = min((TOTAL_DEDUCCIONES_O + TOTAL_RE_O + RE_RENTA_EXENTA_O),(ING_BASE_O * 0.4))
if (base > (annual_parameters.value_uvt * (1340.00/12.00))):
    result = (annual_parameters.value_uvt * (1340.00/12.00))
else:
    result = ING_BASE_O-base
#SUBT_IBR3_AVP_O - REVISAR
SUBT_IBR2_CONT_AVP_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'SUBT_IBR2_CONT_AVP_O').result_calculation
RE_RENTA_EXE_AVP_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RE_RENTA_EXE_AVP_O').result_calculation
result = SUBT_IBR2_CONT_AVP_O - RE_RENTA_EXE_AVP_O
TOTAL_DEDUCCIONES_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'TOTAL_DEDUCCIONES_O').result_calculation
TOTAL_RE_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'TOTAL_RE_O').result_calculation
RE_RENTA_EXENTA_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RE_RENTA_EXENTA_O').result_calculation
ING_BASE_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'ING_BASE_O').result_calculation
base = min((TOTAL_DEDUCCIONES_O + TOTAL_RE_O + RE_RENTA_EXENTA_O),(ING_BASE_O * 0.4))
if (base > (annual_parameters.value_uvt * (1340.00/12.00))):
    result = (annual_parameters.value_uvt * (1340.00/12.00))
else:
    result = ING_BASE_O-base
#IBR_EN_UVTS_O
result = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'SUBTOTAL_IBR3_O').result_calculation  / annual_parameters.value_uvt
#IBR_EN_UVTS_AFC_O
result = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'SUBT_IBR3_AFC_O').result_calculation  / annual_parameters.value_uvt
#IBR_EN_UVTS_AVP_O
result = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'SUBT_IBR3_AVP_O').result_calculation  / annual_parameters.value_uvt
#RETENCION_O
    #Base
result = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'SUBTOTAL_IBR3_O').result_calculation    
    #Calculo
IBR_EN_UVTS_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'IBR_EN_UVTS_O').result_calculation 
obj_calculo = payslip.get_calcula_rtefte_ordinaria(IBR_EN_UVTS_O)
if obj_calculo.range_initial == 0:
    result = 0.0
else:
    porc = obj_calculo.porc / 100
    result = round((((IBR_EN_UVTS_O - obj_calculo.subtract_uvt) * porc) + obj_calculo.addition_uvt) * annual_parameters.value_uvt,0)
#RETENCION_AFC_O
    #Base
result = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'SUBT_IBR3_AFC_O').result_calculation    
    #Calculo
IBR_EN_UVTS_AFC_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'IBR_EN_UVTS_AFC_O').result_calculation 
obj_calculo = payslip.get_calcula_rtefte_ordinaria(IBR_EN_UVTS_AFC_O)
if obj_calculo.range_initial == 0:
    result = 0.0
else:
    porc = obj_calculo.porc / 100
    result = round((((IBR_EN_UVTS_AFC_O - obj_calculo.subtract_uvt) * porc) + obj_calculo.addition_uvt) * annual_parameters.value_uvt,0)
#RETENCION_AVP_O
result = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'SUBT_IBR3_AVP_O').result_calculation    
    #Calculo
IBR_EN_UVTS_AVP_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'IBR_EN_UVTS_AVP_O').result_calculation 
obj_calculo = payslip.get_calcula_rtefte_ordinaria(IBR_EN_UVTS_AVP_O)
if obj_calculo.range_initial == 0:
    result = 0.0
else:
    porc = obj_calculo.porc / 100
    result = round((((IBR_EN_UVTS_AVP_O - obj_calculo.subtract_uvt) * porc) + obj_calculo.addition_uvt) * annual_parameters.value_uvt,0)
#RTEFTE_ANTERIOR_O
result = abs(payslip.sum_mount_x_rule('RETFTE001', payslip.date_from, payslip.date_to) + rules_computed.RETFTE001)
#RETENCION_DEF_AFC_O
RETENCION_AFC_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RETENCION_AFC_O').result_calculation 
RTEFTE_ANTERIOR_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RTEFTE_ANTERIOR_O').result_calculation 
result = round(RETENCION_AFC_O - RTEFTE_ANTERIOR_O, -3)
#RETENCION_DEF_AVP_O
RETENCION_AVP_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RETENCION_AVP_O').result_calculation 
RTEFTE_ANTERIOR_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RTEFTE_ANTERIOR_O').result_calculation 
result = round(RETENCION_AVP_O - RTEFTE_ANTERIOR_O, -3)
#RETENCION_DEF_O
RETENCION_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RETENCION_O').result_calculation 
RTEFTE_ANTERIOR_O = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RTEFTE_ANTERIOR_O').result_calculation 
result = round(RETENCION_O - RTEFTE_ANTERIOR_O, -3)
# --------------------------------------------------------------------------------------------------------------------
# ------------------------------------- Tipo de impuesto PRIMA -----------------------
# --------------------------------------------------------------------------------------------------------------------
#SALARIO_3
result = payslip.sum_mount('BASIC', payslip.date_from, payslip.date_to) + categories.BASIC
#COMISIONES_3
result = payslip.sum_mount('COMISIONES', payslip.date_from, payslip.date_to) + categories.COMISIONES
#OTROS_ING_GRAV_3
dev_salarial = (payslip.sum_mount('DEV_SALARIAL', payslip.date_from, payslip.date_to) + categories.DEV_SALARIAL)
dev_no_salarial = (payslip.sum_mount('DEV_NO_SALARIAL', payslip.date_from, payslip.date_to) + categories.DEV_NO_SALARIAL)
values_ant = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'SALARIO_3').result_calculation - payslip.get_deduction_retention_value(employee.id,payslip.date_to,'COMISIONES_3').result_calculation
result = dev_salarial + dev_no_salarial - values_ant
#TOTAL_ING_BASE_3
result = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'SALARIO_3').result_calculation + payslip.get_deduction_retention_value(employee.id,payslip.date_to,'COMISIONES_3').result_calculation + payslip.get_deduction_retention_value(employee.id,payslip.date_to,'OTROS_ING_GRAV_3').result_calculation
#RE_AP_PENSION_3
value_pension = payslip.sum_mount_x_rule('SSOCIAL002', payslip.date_from, payslip.date_to) + rules_computed.SSOCIAL002
value_fondo_subsistencia = payslip.sum_mount_x_rule('SSOCIAL003', payslip.date_from, payslip.date_to) + rules_computed.SSOCIAL003
value_fondo_solidaridad = payslip.sum_mount_x_rule('SSOCIAL004', payslip.date_from, payslip.date_to) + rules_computed.SSOCIAL004
result = abs(value_pension + value_fondo_subsistencia + value_fondo_solidaridad)
#DED_APT_SALUD_3
result = abs(payslip.sum_mount_x_rule('SSOCIAL001', payslip.date_from, payslip.date_to) + rules_computed.SSOCIAL001)
#ING_NO_GRAVADOS_3
result = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RE_AP_PENSION_3').result_calculation + payslip.get_deduction_retention_value(employee.id,payslip.date_to,'DED_APT_SALUD_3').result_calculation
#ING_BASE_3
result = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'TOTAL_ING_BASE_3').result_calculation - payslip.get_deduction_retention_value(employee.id,payslip.date_to,'ING_NO_GRAVADOS_3').result_calculation
#DED_VIVIENDA_3
result = payslip.sum_mount_x_rule('INTVIV', payslip.date_from, payslip.date_to) + rules_computed.INTVIV
result = annual_parameters.value_uvt*100 if result > annual_parameters.value_uvt*100 else result
#DED_DEPENDIENTES_3
result = payslip.get_contract_deductions_rtf(contract.id,payslip.date_to,'DEDDEP').value_monthly
if result > 0:
    result = (payslip.get_deduction_retention_value(employee.id,payslip.date_to,'TOTAL_ING_BASE_3').result_calculation * 0.1000)
    result = annual_parameters.value_uvt*32*12 if result > annual_parameters.value_uvt*32*12 else result
#DED_MPREPAGADA_3
result = (payslip.sum_mount_x_rule('MEDPRE', payslip.date_from, payslip.date_to) + rules_computed.MEDPRE)*12
result = annual_parameters.value_uvt*16*12 if result > annual_parameters.value_uvt*16*12 else result
#TOTAL_DEDUCCIONES_3
result = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'DED_VIVIENDA_3').result_calculation + payslip.get_deduction_retention_value(employee.id,payslip.date_to,'DED_DEPENDIENTES_3').result_calculation + payslip.get_deduction_retention_value(employee.id,payslip.date_to,'DED_MPREPAGADA_3').result_calculation
#SUBTOTAL_IBR1_3
result = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'ING_BASE_3').result_calculation - payslip.get_deduction_retention_value(employee.id,payslip.date_to,'TOTAL_DEDUCCIONES_3').result_calculation
#RE_AP_VOL_PENSION_3
result = 0.0
#RE_AP_AFC_3
result = abs(payslip.sum_mount_x_rule('AFC', payslip.date_from, payslip.date_to) + rules_computed.AFC)
#RE_GTOS_ENTIERRO_3 | RE_GTOS_REP_3 | RE_GTOS_EXC_FARM_3 | RE_INDEMNIZACIONES_3
result = 0.0
#TOTAL_RE_3
RE_AP_VOL_PENSION_3 = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RE_AP_VOL_PENSION_3').result_calculation
RE_AP_AFC_3 = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RE_AP_AFC_3').result_calculation
RE_GTOS_ENTIERRO_3 = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RE_GTOS_ENTIERRO_3').result_calculation
RE_GTOS_REP_3 = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RE_GTOS_REP_3').result_calculation
RE_GTOS_EXC_FARM_3 = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RE_GTOS_EXC_FARM_3').result_calculation
RE_INDEMNIZACIONES_3 = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RE_INDEMNIZACIONES_3').result_calculation

result = RE_AP_VOL_PENSION_3 + RE_AP_AFC_3 + RE_GTOS_ENTIERRO_3 + RE_GTOS_REP_3 + RE_GTOS_EXC_FARM_3 + RE_INDEMNIZACIONES_3
result = annual_parameters.value_uvt * 3800 if result > annual_parameters.value_uvt * 3800 else result
#TOTAL_RE_CONT_AFC_3
RE_AP_VOL_PENSION_3  = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RE_AP_VOL_PENSION_3').result_calculation
RE_GTOS_ENTIERRO_3 = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RE_GTOS_ENTIERRO_3').result_calculation
RE_GTOS_REP_3 = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RE_GTOS_REP_3').result_calculation
RE_GTOS_EXC_FARM_3 = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RE_GTOS_EXC_FARM_3').result_calculation
RE_INDEMNIZACIONES_3 = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RE_INDEMNIZACIONES_3').result_calculation

result = RE_AP_VOL_PENSION_3  + RE_GTOS_ENTIERRO_3 + RE_GTOS_REP_3 + RE_GTOS_EXC_FARM_3 + RE_INDEMNIZACIONES_3
#TOTAL_RE_CONT_AVP_3
RE_AP_AFC_3 = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RE_AP_AFC_3').result_calculation
RE_GTOS_ENTIERRO_3 = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RE_GTOS_ENTIERRO_3').result_calculation
RE_GTOS_REP_3 = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RE_GTOS_REP_3').result_calculation
RE_GTOS_EXC_FARM_3 = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RE_GTOS_EXC_FARM_3').result_calculation
RE_INDEMNIZACIONES_3 = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RE_INDEMNIZACIONES_3').result_calculation

result = RE_AP_AFC_3 + RE_GTOS_ENTIERRO_3 + RE_GTOS_REP_3 + RE_GTOS_EXC_FARM_3 + RE_INDEMNIZACIONES_3
#SUBTOTAL_IBR2_3
SUBTOTAL_IBR1_3 = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'SUBTOTAL_IBR1_3').result_calculation
TOTAL_RE_3 = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'TOTAL_RE_3').result_calculation
result = SUBTOTAL_IBR1_3 - TOTAL_RE_3
#SUBT_IBR2_CONT_AFC_3
SUBTOTAL_IBR1_3 = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'SUBTOTAL_IBR1_3').result_calculation
TOTAL_RE_CONT_AFC_3 = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'TOTAL_RE_CONT_AFC_3').result_calculation
result = SUBTOTAL_IBR1_3 - TOTAL_RE_CONT_AFC_3
#SUBT_IBR2_CONT_AVP_3
SUBTOTAL_IBR1_3 = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'SUBTOTAL_IBR1_3').result_calculation
TOTAL_RE_CONT_AVP_3 = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'TOTAL_RE_CONT_AVP_3').result_calculation
result = SUBTOTAL_IBR1_3 - TOTAL_RE_CONT_AVP_3
#RE_RENTA_EXENTA_3
SUBTOTAL_IBR2_3 = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'SUBTOTAL_IBR2_3').result_calculation
result = round(SUBTOTAL_IBR2_3 * (25 / 100.000), -3)
result = annual_parameters.value_uvt * 240 * 12 if result > annual_parameters.value_uvt * 240 * 12 else result
#RE_RENTA_EXE_AFC_3
SUBT_IBR2_CONT_AFC_3 = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'SUBT_IBR2_CONT_AFC_3').result_calculation
result = round(SUBT_IBR2_CONT_AFC_3 * (25 / 100.000), -3)
result = annual_parameters.value_uvt * 240 * 12 if result > annual_parameters.value_uvt * 240 * 12 else result
#RE_RENTA_EXE_AVP_3
SUBT_IBR2_CONT_AVP_3 = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'SUBT_IBR2_CONT_AVP_3').result_calculation
result = round(SUBT_IBR2_CONT_AVP_3 * (25 / 100.000), -3)
result = annual_parameters.value_uvt * 240 * 12 if result > annual_parameters.value_uvt * 240 * 12 else result
#SUBTOTAL_IBR3_3
TOTAL_DEDUCCIONES_3 = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'TOTAL_DEDUCCIONES_3').result_calculation
TOTAL_RE_3 = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'TOTAL_RE_3').result_calculation
RE_RENTA_EXENTA_3 = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RE_RENTA_EXENTA_3').result_calculation
ING_BASE_3 = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'ING_BASE_3').result_calculation
SUBTOTAL_IBR2_3 = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'SUBTOTAL_IBR2_3').result_calculation
result = (SUBTOTAL_IBR2_3 - RE_RENTA_EXENTA_3)

if (TOTAL_DEDUCCIONES_3 + TOTAL_RE_3 + RE_RENTA_EXENTA_3) > (ING_BASE_3 * 0.4):
    result = ING_BASE_3 * 0.4
#SUBT_IBR3_AFC_3
SUBT_IBR2_CONT_AFC_3 = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'SUBT_IBR2_CONT_AFC_3').result_calculation
RE_RENTA_EXE_AFC_3 = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RE_RENTA_EXE_AFC_3').result_calculation
result = SUBT_IBR2_CONT_AFC_3 - RE_RENTA_EXE_AFC_3
#SUBT_IBR3_AVP_3
SUBT_IBR2_CONT_AVP_3 = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'SUBT_IBR2_CONT_AVP_3').result_calculation
RE_RENTA_EXE_AVP_3 = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RE_RENTA_EXE_AVP_3').result_calculation
result = SUBT_IBR2_CONT_AVP_3 - RE_RENTA_EXE_AVP_3
#SAL_MENS_PROM_3
result = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'SUBTOTAL_IBR3_3').result_calculation  / 13
#SAL_MENS_PROM_AFC_3
result = payslip.get_deduction_retention_value(employee.id, payslip.date_to, 'SUBT_IBR3_AFC_3').result_calculation / 13
#SAL_MENS_PROM_AVP_3
result = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'SUBT_IBR3_AVP_3').result_calculation  / 13
#IBR_EN_UVTS_3
result = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'SAL_MENS_PROM_3').result_calculation  / annual_parameters.value_uvt
#IBR_EN_UVTS_AFC_3
result = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'SAL_MENS_PROM_AFC_3').result_calculation  / annual_parameters.value_uvt
#IBR_EN_UVTS_AVP_3
result = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'SAL_MENS_PROM_AVP_3').result_calculation  / annual_parameters.value_uvt
#RETENCION_3
    #Base
result = payslip.get_deduction_retention_value(employee.id, payslip.date_to, 'SUBTOTAL_IBR3_3').result_calculation
    #Calculo
IBR_EN_UVTS_3 = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'IBR_EN_UVTS_3').result_calculation
obj_calculo = payslip.get_calcula_rtefte_ordinaria(IBR_EN_UVTS_3)
if obj_calculo.range_initial == 0:
    result = 0.0
else:
    porc = obj_calculo.porc / 100
    result = round((((IBR_EN_UVTS_3 - obj_calculo.subtract_uvt) * porc) + obj_calculo.addition_uvt) * annual_parameters.value_uvt,0)
#RETENCION_AFC_3
    #Base
result = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'SUBT_IBR3_AFC_3').result_calculation
    #Calculo
IBR_EN_UVTS_AFC_3 = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'IBR_EN_UVTS_AFC_3').result_calculation
obj_calculo = payslip.get_calcula_rtefte_ordinaria(IBR_EN_UVTS_AFC_3)
if obj_calculo.range_initial == 0:
    result = 0.0
else:
    porc = obj_calculo.porc / 100
    result = round((((IBR_EN_UVTS_AFC_3 - obj_calculo.subtract_uvt) * porc) + obj_calculo.addition_uvt) * annual_parameters.value_uvt,0)
#RETENCION_AVP_3
result = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'SUBT_IBR3_AVP_3').result_calculation
    #Calculo
IBR_EN_UVTS_AVP_3 = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'IBR_EN_UVTS_AVP_3').result_calculation
obj_calculo = payslip.get_calcula_rtefte_ordinaria(IBR_EN_UVTS_AVP_3)
if obj_calculo.range_initial == 0:
    result = 0.0
else:
    porc = obj_calculo.porc / 100
    result = round((((IBR_EN_UVTS_AVP_3 - obj_calculo.subtract_uvt) * porc) + obj_calculo.addition_uvt) * annual_parameters.value_uvt,0)
#PORCENTAJE_DEF_AVP_3
RETENCION_AFC_3 = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RETENCION_AFC_3').result_calculation
IBR_EN_UVTS_AFC_3 = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'IBR_EN_UVTS_AFC_3').result_calculation

result = (RETENCION_AFC_3 / annual_parameters.value_uvt) / IBR_EN_UVTS_AFC_3 * 100
#PORCENTAJE_DEF_AVP_3
RETENCION_AVP_3 = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RETENCION_AVP_3').result_calculation
IBR_EN_UVTS_AVP_3 = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'IBR_EN_UVTS_AVP_3').result_calculation

result = (RETENCION_AVP_3 / annual_parameters.value_uvt) / IBR_EN_UVTS_AVP_3 * 100
#PORCENTAJE_DEF_3
RETENCION_3 = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'RETENCION_3').result_calculation
IBR_EN_UVTS_3 = payslip.get_deduction_retention_value(employee.id,payslip.date_to,'IBR_EN_UVTS_3').result_calculation

result = (RETENCION_3 / annual_parameters.value_uvt) / IBR_EN_UVTS_3 * 100
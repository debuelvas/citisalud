# -*- coding: utf-8 -*-
from odoo import models, fields, api, sql_db
from datetime import datetime, timedelta
from calendar import monthrange

lr = [0, 1, 100]

##################################################################################################################
# Use the following rules to declare the rules in the payslip
##################################################################################################################

RULES = [
    'SAL_MINIMO',
    'AUXTRANSP',
    'INCAPACIDAD_ENF_GENERAL',
    'INCAPACIDADMENOR90',
    'INCAPACIDAD_ATEP',
    'HED',
    'DYF',
    'RDF',
    'HEDF',
    'HENF',
    'HEN',
    'RN',
    'DOM',
    'FES',
    'RNF',
    'HFN',
    'HEDD',
    'HEDN',
    'LICENCIA_MATERNIDAD',
    'PRORROGA_INCAPACIDAD_ENF_GENERAL',
    'LICENCIA_POR_LUTO',
    'VAC',
    'NETO',
    'LICENCIA_NO_REMUNERADA',
    'ACUMVAC',
    'DIAS_VAC_MES',
    'SALPROM',
    'ACUMSEM',
    'IBCMA',
    'AUS_LEY_MARIA',
    'BASICO',
    'BASICOINT',
    'BASICOCS',
    'AUXTRANSP',
    'SUBTOTAL',
    'IBCSS',
    'IBCPF',
    'NOVEDADES',
    'IBCARL',
    'FONDOSOLID',
    'FONDOSUBSISTENCIA',
    'DCTO_AUT',
    'DEDEPS',
    'DEDPENSION',
    'PAGO_MES',
    'APOR_OBLI_MES_SALUD',
    'APOR_OBLI_MES_PENSION',
    'APORTE_OBLIG_MES_FSP',
    'INGNOCRENTA',
    'APOR_PROM_SALUD',
    'RENTA_EXENTA',
    'RTEFTE_APL',
    'BASERTEFTE',
    'AUX_MOVI',
    'PLAN_EXEQUIAL',
    'HE_ADD',
    'HED31',
    'FES',
    'AUX_MOVILIZACION',
    'INGNOCRENTA',
    'TOPE40',
    'CESANTIAS',
    'MEDICINA_PREPAGA',
    'ANTICIPO',
    'DIAS_PRIMA',
    'INT_CESANTIA_ANUAL',
    'BASEPROV',
    'PROV_VAC',
    'ACUMCES',
    'RTEFTE_APL_INDEM',
    'DIAS_TRAB_MES',
    'APPENSION',
    'CCF',
    'PRIMASERV',
]
##################################################################################################################
# Use variable res to assing the condition of the rule.
# Use amount to declare the result equivalent on each rule in case you need
# Return a tuple or list with result, result_qty, rate equivalents
##################################################################################################################

def monthdelta(d1, d2):
    delta = 0
    d1=datetime.strptime(d1,"%Y-%m-%d")
    d2=datetime.strptime(d2,"%Y-%m-%d")
    while True:
        mdays = monthrange(d1.year, d1.month)[1]
        d1 += timedelta(days=mdays)
        if d1 <= d2:
            delta += 1
        else:
            break
    return delta


class HrSalaryRule(models.Model):
    _inherit = 'hr.salary.rule'

    @api.model
    def reset_globals(self):
        global lr
        lr = [0, 1, 100]

    # Salario Mínimo DONE
    
    def _sal_minimo(self, ld):
        e_v = self.env['variables.economicas']
        lr[0] = e_v.getValue('SMMLV', ld['payslip'].dict.liquidacion_date) or 0.0
        return lr

    # Subsidio de transporte 2131 #TODO
    
    def _auxtransp(self, ld):
        res = False
        deducciones = 0
        work102 = ld['worked_days'].dict['WORK101'].number_of_days
        dias = 0
        e_v = self.env['variables.economicas']
        aux = e_v.getValue('AUXTRANSPORTE', ld['payslip'].dict.liquidacion_date) or 0.0
        dias_trab = work102
        dias += dias_trab
        payslip = ld['payslip']
        company = self.env['res.users'].browse(self._uid).company_id
        bmt = ld['payslip'].payslip_period_id.bm_type
        sch_pay = ld['payslip'].payslip_period_id.schedule_pay
        ncod = ld['payslip'].struct_id.process
        respol = False
        if company.aux_trans_second:
            if ((bmt == 'second' or sch_pay == 'monthly') and ncod == 'nomina') or (ncod in ('contrato', 'vacaciones')):
                respol = True
        else:
            if ncod in ('contrato', 'vacaciones', 'nomina'):
                respol = True
        if aux and dias_trab > 0 and respol:
            # and ((payslip.payslip_period_id.schedule_pay == 'monthly' or (int(payslip.payslip_period_id.end_period[8:10])>16 and #payslip.payslip_period_id.schedule_pay == 'bi-monthly'))and payslip.tipo_nomina.code == 'Nomina' or #payslip.tipo_nomina.code in ('Vacaciones','Liquidacion')):
            # periodo de la nomina actual
            proll_period_c = ld['payslip'].payslip_period_id.name[0:7]
            devengo = ld['categories'].DEVENGADO
            for proll in ld['contract'].slip_ids:
                # periodo de la nomina actual
                if proll.id == payslip.id:
                    continue
                proll_period = proll.payslip_period_id.name[0:7]
                # compara cada periodo con el periodo de la nomina actual
                if proll_period_c == proll_period and proll.tipo_nomina.code != 'Prima' and proll.id != payslip.id:
                    # recorre las lineas de la nomina y obtiene los parametros
                    for value in proll.line_ids:
                        if value.category_id.code in ('DEVENGADO', 'OTROS_DEVENGOS_SALARIALES', 'INGCOM'):
                            devengo += value.total
                        if value.code == 'AJUSTE_TRANSPORT':
                            deducciones -= value.total
                        if value.code == 'DIAS_TRAB':
                            dias += value.total
                        if value.code == 'AUXTRANSP' and proll.number != ld['categories'].number:
                            work102 -= value.quantity
                    for days in proll.worked_days_line_ids:
                        if days.code == 'WORK102':
                            work102 += days.number_of_days
            if devengo >= 2 * ld['SAL_MINIMO'] or ld['contract'].wage > ld['SAL_MINIMO'] * 2:
                res = False
            else:
                res = True
            if work102 < 0:
                work102 = 0

        if res:
            amount = aux / 30
            result_qty = work102 if work102 < 30 else 30
            if result_qty > work102:
                result_qty = work102
            if result_qty == 0:
                amount = 0
            result_qty = dias
            lr[0] = amount
            lr[1] = result_qty
        else:
            lr[0] = 'na'

        return lr

    # Incapacidades enf general #TODO
    
    def _incapacidad_enf_general(self, ld):
        res = False
        dias = 0.0
        payslip = ld['payslip']
        if payslip.leave_ids:
            for detalle in payslip.leave_days_ids:
                if detalle.holiday_status_id.code in ('INCAPACIDAD_ENF_GENERAL') and detalle.holiday_id.state == 'validate':
                    if detalle.sequence > 0 and detalle.sequence <= 2:
                        dias += detalle.days_payslip
        if dias > 0:
            res = True
        if res:
            contract = ld['contract']
            sal_minimo = 0.0
            try:
                sal_minimo = ld['SAL_MINIMO']
            except:
                pass
            result = contract.wage
            if result < sal_minimo:
                result = sal_minimo
            lr[1] = dias
            lr[0] = result/30
        else:
            lr[0] = 'na'
        return lr

    # Incapacidad menor 90 #TODO
    
    def _incapacidadmenor90(self, ld):
        res = False
        payslip = ld['payslip']
        dias = 0.0
        if payslip.leave_ids:
            for detalle in payslip.leave_days_ids:
                if detalle.holiday_status_id.code in ('INCAPACIDAD_ENF_GENERAL'):
                    if detalle.sequence > 2 and detalle.sequence <= 90:
                        dias += detalle.days_payslip
        if dias > 0:
            res = True

        if res:
            rules = ld['rules']
            contract = ld['contract']
            sal_minimo = ld['SAL_MINIMO'] if rules.SAL_MINIMO else 0.0
            ibcma = ld['IBCMA'] if rules.IBCMA else 0.0
            result = ibcma / 30
            if result == 0:
                result = contract.wage / 30
            if result * 0.6667 <= sal_minimo / 30:
                result = sal_minimo / (0.66667 * 30)
            lr[1] = dias
            lr[2] = 66.67
            lr[0] = result
        else:
            lr[0] = 'na'
        return lr


    # Incapacidad ATEP #TODO
    
    def _incapacidad_atep(self, ld):
        dias = 0
        payslip = ld['payslip']
        if payslip.leave_days_ids:
            for leave in payslip.leave_days_ids:
                if leave.holiday_status_id.code in ('INCAPACIDAD_ATEP_PRORROGA'):
                    dias += leave.days_payslip
        res = True if dias > 0 else False
        if res:
            contract = ld['contract']
            lr[1] = dias
            if dias >= 1:
                lr[0] = contract.wage / 30
        else:
            lr[0] = 'na'
        return lr

    # Hora extra diurna #TODO
    
    def _hed(self, ld):
        res = False
        payslip = ld ['payslip']
        if payslip.extrahours_total_ids:
            for extra in payslip.extrahours_total_ids:
                if extra.type_id.code == "HED":
                    res = True
        if res:
            he, he_qty = 0, 0
            for extra in payslip.extrahours_total_ids:
                if extra.type_id.code == "HED":
                    he += extra.total
                    he_qty += extra.cantidad
            lr[0] = he / he_qty
            lr[1] = he_qty

        else:
            lr[0] = 'na'
        return lr

    # Dominical y festivo #TODO
    
    def _dyf(self, ld):
        res = False
        payslip = ld['payslip']
        if payslip.extrahours_total_ids:
            for extra in payslip.extrahours_total_ids:
                if extra.type_id.code == "DYF":
                    res = True
        if res:
            he, he_qty = 0, 0
            for extra in payslip.extrahours_total_ids:
                if extra.type_id.code == "DYF":
                    he += extra.total
                    he_qty += extra.cantidad
            lr[0] = he / he_qty
            lr[1] = he_qty

        else:
            lr[0] = 'na'
        return lr

    # Dominicales y festivos compensados #TODO
    
    def _rdf(self, ld):
        res = False
        payslip = ld['payslip']
        if payslip.extrahours_total_ids:
            for extra in payslip.extrahours_total_ids:
                if extra.type_id.code == "RDF":
                    res = True
        if res:
            he, he_qty = 0, 0
            for extra in payslip.extrahours_total_ids:
                if extra.type_id.code == "RDF":
                    he += extra.total
                    he_qty += extra.cantidad
            lr[0] = he / he_qty
            lr[1] = he_qty

        else:
            lr[0] = 'na'
        return lr

    # Hora extra diurna festiva #TODO
    
    def _hedf(self, ld):
        res = False
        payslip = ld['payslip']
        if payslip.extrahours_total_ids:
            for extra in payslip.extrahours_total_ids:
                if extra.type_id.code == "HEDF":
                    res = True
        if res:
            he, he_qty = 0, 0
            for extra in payslip.extrahours_total_ids:
                if extra.type_id.code == "HEDF":
                    he += extra.total
                    he_qty += extra.cantidad
            lr[0] = he / he_qty
            lr[1] = he_qty

        else:
            lr[0] = 'na'
        return lr

    # Hora extra diurna festiva #TODO
    
    def _henf(self, ld):
        res = False
        payslip = ld['payslip']
        if payslip.extrahours_total_ids:
            for extra in payslip.extrahours_total_ids:
                if extra.type_id.code == "HENF":
                    res = True
        if res:
            he, he_qty = 0, 0
            for extra in payslip.extrahours_total_ids:
                if extra.type_id.code == "HENF":
                    he += extra.total
                    he_qty += extra.cantidad
            lr[0] = he / he_qty
            lr[1] = he_qty

        else:
            lr[0] = 'na'
        return lr

    # Hora extra diurna festiva #TODO
    
    def _hen(self, ld):
        res = False
        payslip = ld['payslip']
        if payslip.extrahours_total_ids:
            for extra in payslip.extrahours_total_ids:
                if extra.type_id.code == "HEN":
                    res = True
        if res:
            he, he_qty = 0, 0
            for extra in payslip.extrahours_total_ids:
                if extra.type_id.code == "HEN":
                    he += extra.total
                    he_qty += extra.cantidad
            lr[0] = he / he_qty
            lr[1] = he_qty

        else:
            lr[0] = 'na'
        return lr

    # Recargo nocturno #TODO
    
    def _rn(self, ld):
        res = False
        payslip = ld['payslip']
        if payslip.extrahours_total_ids:
            for extra in payslip.extrahours_total_ids:
                if extra.type_id.code == "RN":
                    res = True
        if res:
            he = 0
            cant = 0
            for extra in payslip.extrahours_total_ids:
                if extra.type_id.code == "RN":
                    he += extra.total
                    cant += extra.cantidad
            lr[0] = he / cant
            lr[1] = cant
        else:
            lr[0] = 'na'
        return lr

    # Recargo nocturno #TODO
    
    def _dom(self, ld):
        res = False
        payslip = ld['payslip']
        if payslip.extrahours_total_ids:
            for extra in payslip.extrahours_total_ids:
                if extra.type_id.code == "DOM":
                    res = True
        if res:
            he = 0
            cant = 0
            for extra in payslip.extrahours_total_ids:
                if extra.type_id.code == "DOM":
                    he += extra.total
                    cant += extra.cantidad
            lr[0] = he / cant
            lr[1] = cant
        else:
            lr[0] = 'na'
        return lr

    # Recargo nocturno #TODO
    
    def _fes(self, ld):
        res = False
        payslip = ld['payslip']
        if payslip.extrahours_total_ids:
            for extra in payslip.extrahours_total_ids:
                if extra.type_id.code == "FES":
                    res = True
        if res:
            he = 0
            cant = 0
            for extra in payslip.extrahours_total_ids:
                if extra.type_id.code == "FES":
                    he += extra.total
                    cant += extra.cantidad
            lr[0] = he / cant
            lr[1] = cant
        else:
            lr[0] = 'na'
        return lr

    # Hora extra diurna festiva #TODO
    
    def _rnf(self, ld):
        res = False
        payslip = ld['payslip']
        if payslip.extrahours_total_ids:
            for extra in payslip.extrahours_total_ids:
                if extra.type_id.code == "RNF":
                    res = True
        if res:
            he, he_qty = 0, 0
            for extra in payslip.extrahours_total_ids:
                if extra.type_id.code == "RNF":
                    he += extra.total
                    he_qty += extra.cantidad
            lr[0] = he / he_qty
            lr[1] = he_qty

        else:
            lr[0] = 'na'
        return lr

    # Hora extra diurna festiva #TODO
    
    def _hfn(self, ld):
        res = False
        payslip = ld['payslip']
        if payslip.extrahours_total_ids:
            for extra in payslip.extrahours_total_ids:
                if extra.type_id.code == "HFN":
                    res = True
        if res:
            he, he_qty = 0, 0
            for extra in payslip.extrahours_total_ids:
                if extra.type_id.code == "HFN":
                    he += extra.total
                    he_qty += extra.cantidad
            lr[0] = he / he_qty
            lr[1] = he_qty

        else:
            lr[0] = 'na'
        return lr

    # Hora extra diurna festiva #TODO
    
    def _hedd(self, ld):
        res = False
        payslip = ld['payslip']
        if payslip.extrahours_total_ids:
            for extra in payslip.extrahours_total_ids:
                if extra.type_id.code == "HEDD":
                    res = True
        if res:
            he, he_qty = 0, 0
            for extra in payslip.extrahours_total_ids:
                if extra.type_id.code == "HEDD":
                    he += extra.total
                    he_qty += extra.cantidad
            lr[0] = he / he_qty
            lr[1] = he_qty

        else:
            lr[0] = 'na'
        return lr

    # Hora extra diurna festiva #TODO
    
    def _hedn(self, ld):
        res = False
        payslip = ld['payslip']
        if payslip.extrahours_total_ids:
            for extra in payslip.extrahours_total_ids:
                if extra.type_id.code == "HEDN":
                    res = True
        if res:
            he, he_qty = 0, 0
            for extra in payslip.extrahours_total_ids:
                if extra.type_id.code == "HEDN":
                    he += extra.total
                    he_qty += extra.cantidad
            lr[0] = he / he_qty
            lr[1] = he_qty

        else:
            lr[0] = 'na'
        return lr

    # Licencia materinidad #TODO
    
    def _licencia_maternidad(self, ld):
        res = False
        payslip = ld['payslip']
        if payslip.novedades_total_ids:
            for novedades in payslip.novedades_total_ids:
                if novedades.category_id.code == "ANT_LICMATERNIDA":
                    res = True

        if payslip.leave_ids:
            for leave in payslip.leave_ids:
                if leave.holiday_status_id.code == "LICENCIA_MATERNIDAD":
                    res = True

        if res:
            rules = ld['rules']
            contract = ld['contract']
            if 'LICENCIA_MATERNIDAD' in ld['worked_days'].dict:
                matern = ld['worked_days'].dict['LICENCIA_MATERNIDAD'].number_of_days
            else:
                matern = 0

            ibcma = ld['IBCMA'] if rules.IBCMA else 0.0
            if ibcma == 0:
                ibcma = contract.wage
            lr[0] = (ibcma / 30)
            lr[1] = matern
        else:
            lr[0] = 'na'
        return lr

    # Prorroga incapacidad enf general #TODO
    
    def _prorroga_incapacidad_enf_general(self, ld):
        res = False
        payslip = ld['payslip']
        dias = 0.0
        if payslip.leave_ids:
            for detalle in payslip.leave_days_ids:
                if detalle.holiday_status_id.code in ('PRORROGA_INCAPACIDAD_ENF_GENERAL1',
                                                      'PRORROGA_INCAPACIDAD_ENF_GENERAL', 'PIEGP') and detalle.sequence > 0 and detalle.sequence <= 180:
                    dias += detalle.days_payslip
        if dias > 0:
            res = True
        if res:
            rules = ld['rules']
            sal_minimo = ld['SAL_MINIMO'] if rules.SAL_MINIMO else 0.0
            ibcma = ld['IBCMA'] if rules.IBCMA else 0.0
            lr[2] = 66.67
            if not ibcma:
                ibcma = ld['contract'].wage
            if (ibcma * lr[2] / 100) <= sal_minimo:
                ibcma = sal_minimo
            lr[0] = ibcma / 30
            lr[1] = dias
        else:
            lr[0] = 'na'
        return lr

    # Licencia por luto #TODO
    
    def _licencia_por_luto(self, ld):
        res = False
        cantidad = 0
        payslip = ld['payslip']
        if payslip.leave_ids:
            for leave in payslip.leave_ids:
                if leave.holiday_status_id.code == "LICENCIA_LUTO":
                    cantidad += leave.number_of_days_in_payslip
                    res = True
        if res:
            lr[0] = (ld['contract'].wage / 30)
            lr[1] = cantidad
        else:
            lr[0] = 'na'
        return lr

    # Vacaciones disfrutadas #TODO
    
    def _vac(self, ld):
        dias = 0
        res = False
        if 'VAC' in ld['worked_days'].dict:
            dias = ld['worked_days'].dict['VAC'].number_of_days
        if dias:
            res = True
        if res:
            payslip = ld['payslip']
            result, total = 0, 0
            contract = ld['contract']
            rules = ld['rules']
            if payslip.novedades_total_ids:
                for novedades in payslip.novedades_total_ids:
                    if novedades.category_id.code == "VAC_MANUAL":
                        result += novedades.total
                    if novedades.category_id.code == "AJUSTEACUMULADO":
                        total += novedades.total
                    if novedades.category_id.code == "AJUSTDIASVAC":
                        dias += novedades.total

            if result == 0:
                wd = monthdelta(contract.date_start, payslip.payslip_period_id.end_period)
                wd = 360 if wd >= 12 else wd * 12
                acumvac = ld['ACUMVAC'] if rules.ACUMVAC else 0.0
                lr[0] = ((acumvac / wd * 30) + contract.wage) / 30 if acumvac > 0 else contract.wage / 30
                lr[1] = dias
        else:
            lr[0] = 'na'
        return lr

    # Neto a pagar #TODO
    
    def _neto(self, ld):
        rules = ld['rules']
        DEV = ld['SUBTOTAL'] if rules.SUBTOTAL else 0.0
        DED = ld['TOTDED'] if rules.TOTDED else 0.0
        DEV += ld['RTFTE_APLNG'] if rules.RTFTE_APLNG else 0.0
        DEV += ld['AJUSRTEFTENG'] if rules.AJUSRTEFTENG else 0.0
        lr[0] = round(DEV - DED)
        return lr

    # Licencia no remunerada #TODO
    
    def _licencia_no_remunerada(self, ld):
        res = False
        payslip = ld['payslip']
        if payslip.leave_ids:
            for leave in payslip.leave_ids:
                if leave.holiday_status_id.name == "LICENCIA NO REMUNERADA":
                    res = True
        if res:
            num = 0
            contract = ld['contract']
            for leave in payslip.leave_ids:
                if leave.holiday_status_id.name == "LICENCIA NO REMUNERADA":
                    num += leave.number_of_days_temp
            lr[0] = (contract.wage / 30) * num
        else:
            lr[0] = 'na'
        return lr

    # Acumulado vacaciones #TODO
    
    def _acumvac(self, ld):
        result, vac = False, False
        payslip = ld['payslip']
        company = self.env['res.users'].browse(self._uid).company_id

        #TODO Politica vacaciones en nomina independiente
        #policy = company.vaca_own_payslip
        policy = False
        res = False
        if payslip.leave_ids:
            for leave in payslip.leave_ids:
                if leave.holiday_status_id.code in ('VAC', 'VAC_PAGAS'):
                    vac = True
        if payslip.tipo_nomina.code in ['Vacaciones', 'Liquidacion'] or \
                (payslip.tipo_nomina.code == 'Nomina' and vac and not policy):
            res = True
        if res:
            contract = ld['contract']
            variable, result, result_qty, result_rate, dias_diff = 0, 0, 0, 100, 0
            if payslip.novedades_total_ids:
                for novedades in payslip.novedades_total_ids:
                    if novedades.category_id.code == "ACUMVAC":
                        result += novedades.total
                    if novedades.category_id.code == "ACUMVAR":
                        variable += novedades.total
            if result == 0:
                end_date = contract.date_end or payslip.payslip_period_id.end_date
                start_date = str(int(end_date[0:4]) - 1) + end_date[4:]

                if contract.type_id.type_fijo is True:
                    result = contract.wage or 0.0
                else:
                    for proll in contract.slip_ids:
                        if proll.novedades_total_ids:
                            for novedades in proll.novedades_total_ids:
                                if novedades.category_id.code == "ACUMVARMES":
                                    variable += novedades.total
                        if proll.tipo_nomina.code in ('Nomina',
                                                      'Vacaciones') and proll.payslip_period_id.start_date >= start_date and proll.payslip_period_id.end_date <= end_date and proll.payslip_period_id.end_date[
                                                                                                                                                                              5:7] != payslip.payslip_period_id.end_date[
                                                                                                                                                                                      5:7] and proll.id != payslip.id:
                            result_qty += 1
                            for leave in proll.leave_ids:
                                if leave.date_to > payslip.payslip_period_id.end_date and leave.date_from < payslip.payslip_period_id.end_date and leave.date_from[
                                                                                                                                                   5:7] == payslip.payslip_period_id.end_date[
                                                                                                                                                           5:7] and leave.holiday_status_id.code == 'VAC':
                                    dias_diff = int(payslip.payslip_period_id.end_date[8:10]) - int(
                                        leave.date_from[8:10]) + 1
                            for value in proll.line_ids:
                                date_start = payslip.payslip_period_id.start_period[0:7] + '-01'
                                pdate_start = proll.payslip_period_id.start_period
                                if (value.category_id.code in (
                                'DEVENGADO') and pdate_start < date_start and value.code not in ('29', '6', 'BASICO')):
                                    if dias_diff > 0 and value.category_id.code in ('DESREM'):
                                        result += (value.total / value.quantity) * dias_diff
                                    else:
                                        result += value.total
                result += variable
            lr[0] = result
        else:
            lr[0] = 'na'
        return lr


    # Dias vacaciones mes 2421
    
    def _dias_vac_mes(self, ld):
        res = False
        if ld['payslip'].tipo_nomina.code == 'Nomina':
            res = True

        if res:
            payslip = ld['payslip'].dict
            proll_period_c = payslip.payslip_period_id.name[0:7]
            mes_actual = payslip.payslip_period_id.name[5:7]

            self.env.cr.execute("SELECT hh.id "
                                "FROM hr_payslip hp "
                                "INNER JOIN payslip_period pp ON hp.payslip_period_id=pp.id "
                                "INNER JOIN hr_payslip_type hpt ON hp.tipo_nomina=hpt.id "
                                "INNER JOIN hr_holidays hh ON hp.id=hh.payslip_id "
                                "INNER JOIN hr_holidays_status hhs ON hh.holiday_status_id=hhs.id "
                                "WHERE hp.contract_id=%s AND pp.name='%s' AND hpt.code='Vacaciones' "
                                "AND hhs.code='VAC' AND EXTRACT(MONTH FROM hh.date_to)=%s" %
                                (payslip.contract_id.id, proll_period_c, mes_actual))
            n_vac = self.env.cr.fetchall()
            if n_vac:
                leaves = self.env['hr.holidays'].browse([x[0] for x in n_vac])
                amount = sum([l.number_of_days_in_payslip for l in leaves])
            else:
                self.env.cr.execute("SELECT sum(hhd.days_payslip) "
                                    "FROM hr_payslip hp "
                                    "INNER JOIN payslip_period pp ON hp.payslip_period_id=pp.id "
                                    "INNER JOIN hr_payslip_type hpt ON hp.tipo_nomina=hpt.id "
                                    "INNER JOIN hr_holidays_days hhd ON hp.id=hhd.payslip_id "
                                    "INNER JOIN hr_holidays_status hhs ON hhd.holiday_status_id=hhs.id "
                                    "WHERE hp.contract_id=%s AND pp.name='%s' "
                                    "AND hpt.code='Vacaciones' AND hhs.code='VAC'"
                                    % (payslip.contract_id.id, proll_period_c))
                amount = self.env.cr.fetchone()[0]
            lr[0] = amount or 0
        else:
            lr[0] = 'na'
        return lr

    # Salario Promedio 2430
    
    def _salprom(self, ld):
        payslip = ld['payslip'].dict
        cont_wg = payslip.contract_id.wage
        self.env.cr.execute("SELECT sum(hpn.total) FROM hr_payslip hp INNER JOIN hr_payslip_novedades hpn ON "
                            "hp.id=hpn.payslip_id INNER JOIN hr_payroll_novedades_category hpnc ON "
                            "hpn.category_id=hpnc.id WHERE hp.id=%s AND hpnc.code='PROMEDIOLIQCONTR'" % payslip.id)
        prom_sal = self.env.cr.fetchone()[0]
        if prom_sal < 1:  # TODO rev NONE
            nstart_date = payslip.payslip_period_id.start_date
            anio_ant = int(nstart_date[0:4]) - 1  # anio anterior
            anio_act = int(nstart_date[0:4])  # anio actual
            mes_ant = int(nstart_date[5:7]) - 1
            mes_act = int(nstart_date[5:7])
            cantidad = 0
            total_payment, devengado = 0, 0
            smes_ant = str(mes_ant).rjust(2, '0')
            smes_act = str(mes_act).rjust(2, '0')
            desde = str(anio_ant) + '-' + smes_ant + '-01'  # ultimo año
            hasta = str(anio_act) + '-' + smes_act + '-01'

            dt_from = desde  # todo LEFT JOIN?
            dt_to = hasta
            self.env.cr.execute("SELECT hpl.total, hsrc.code FROM hr_payslip hp INNER JOIN hr_payslip_type hpt "
                                "ON hp.tipo_nomina=hpt.id INNER JOIN payslip_period pp ON hp.payslip_period_id=pp.id "
                                "INNER JOIN hr_payslip_line hpl ON hp.id=hpl.slip_id INNER JOIN "
                                "hr_salary_rule_category hsrc ON hpl.category_id=hsrc.id WHERE hp.contract_id=%s AND "
                                "hpt.code='Nomina' AND pp.start_date BETWEEN '%s' AND '%s'" % (payslip.contract_id.id,
                                                                                               dt_from, dt_to))
            resq = self.env.cr.fetchall()  # TODO rev NONE
            tot_pay_dev = [x[0] for x in resq if x[1] in ['OTROS_DEVENGOS_SALARIALES', 'DEVENGADO']]
            for proll in payslip.contract_id.slip_ids:
                if proll.tipo_nomina.code == 'Nomina' and proll.payslip_period_id.start_date >= desde and \
                        proll.payslip_period_id.start_date <= hasta and proll.id != payslip.id:
                    cantidad += 1
                    for value in proll.line_ids:
                        if proll.id != payslip.id:
                            if value.category_id.code in ('OTROS_DEVENGOS_SALARIALES'):
                                total_payment += value.total
                            if value.category_id.code in ('DEVENGADO'):
                                devengado += value.total
            if lr[1] > 0:
                prom_sal = ((sum(tot_pay_dev) + cont_wg) / (cantidad + 1))
        lr[0] = cont_wg if prom_sal < cont_wg else prom_sal
        return lr

    # Acumulado Semestral 2461
    
    def _acumsem(self, ld):
        res = False
        payslip = ld['payslip'].dict
        ncod = ld['payslip'].tipo_nomina.code
        end_date = payslip.payslip_period_id.end_date
        if int(end_date[5:7]) in (6, 12) and ncod == 'Nomina':
            res = True
        if ncod in ('Liquidacion', 'Vacaciones'):
            res = True

        if res:
            self.env.cr.execute("SELECT sum(hpn.total) FROM hr_payslip hp INNER JOIN hr_payslip_novedades hpn ON "
                                "hp.id=hpn.payslip_id INNER JOIN hr_payroll_novedades_category hpnc ON "
                                "hpn.category_id=hpnc.id WHERE hp.id=%s AND hpnc.code='AJUSPRIM'" % payslip.id)
            acc_sem = self.env.cr.fetchone()[0]
            amount = acc_sem
            if acc_sem < 1:
                pass
                if payslip.contract_id.type_id.type_fijo is True:
                    amount = payslip.contract_id.wage or 0
                else:
                    end_date = payslip.payslip_period_id.end_date

                    # obtener semestre a calcular
                    if int(end_date[5:7]) > 7:
                        month = 7
                    else:
                        month = 1
                    start_date = end_date[0:4] + '-' + str(month).rjust(2, '0') + '-01'

                    self.env.cr.execute("SELECT hp.id, hh.date_from "
                                        "FROM hr_payslip hp "
                                        "INNER JOIN hr_payslip_type hpt ON hp.tipo_nomina=hpt.id "
                                        "INNER JOIN payslip_period pp ON hp.payslip_period_id=pp.id "
                                        "LEFT JOIN hr_holidays hh ON hp.id=hh.payslip_id "
                                        "LEFT JOIN hr_holidays_status hhs ON hh.holiday_status_id=hhs.id "
                                        "WHERE hp.contract_id=%s "
                                        "AND hpt.code IN ('Nomina','Vacaciones') "
                                        "AND pp.start_date BETWEEN '%s' AND '%s' "
                                        "AND hh.date_to>'%s' AND hh.date_from<'%s' "
                                        "AND EXTRACT(MONTH FROM hh.date_from)='%s' "
                                        "AND hhs.code='VAC'"
                                        % (payslip.contract_id.id, start_date,
                                           end_date, end_date, end_date, end_date[5:7]))
                    resq = self.env.cr.fetchall()
                    lr[1] = len([x[0] for x in resq]) or 1
                    dias_diff = [x[1] for x in resq if x[1]]
                    if dias_diff:
                        dias_diff = int(end_date[8:10]) - int(dias_diff[8:10]) + 1
                    self.env.cr.execute("SELECT hpl.total, hpl.quantity, hsrc.code "
                                        "FROM hr_payslip hp "
                                        "INNER JOIN hr_payslip_type hpt ON hp.tipo_nomina=hpt.id "
                                        "INNER JOIN payslip_period pp ON hp.payslip_period_id=pp.id "
                                        "INNER JOIN hr_payslip_line hpl ON hp.id=hpl.slip_id "
                                        "INNER JOIN hr_salary_rule_category hsrc ON hpl.category_id=hsrc.id "
                                        "WHERE hp.contract_id=%s "
                                        "AND hpt.code IN ('Nomina','Vacaciones') "
                                        "AND pp.start_date BETWEEN '%s' AND '%s'"
                                        "AND (hsrc.code IN ('DEVENGADO', 'DESREM', 'INGCOM', 'OTROS_DEVENGOS_SALARIALES') "
                                        "     OR hpl.code='AUXTRANSP')"
                                        "" % (payslip.contract_id.id, start_date, end_date))
                    resq = self.env.cr.fetchall()
                    for r in resq:
                        if dias_diff > 0 and r[2] in ('OTROS_DEVENGOS_SALARIALES', 'DESREM'):
                            lr[0] += (r[0] / r[1]) * dias_diff
                        else:
                            if lr[0] is None:
                                lr[0] = r[0]
                            else:
                                lr[0] += r[0]
        else:
            lr[0] = 'na'
        return lr

    # IBC Mes anterior 2467 #TODO
    
    def _ibcma(self, ld):
        amount = 0.0
        if ld['payslip'].novedades_total_ids:
            for novedades in ld['payslip'].novedades_total_ids:
                if novedades.category_id.code == 'IBCMA':
                    amount = novedades.total
        if amount == 0.0:
            ibc = 0
            # obtener mes anterior a la nomina
            year = ld['payslip'].payslip_period_id.start_period[0:4]
            month = int(ld['payslip'].payslip_period_id.start_period[5:7])
            if month == 1:
                month = 12
                year = str(int(year) - 1)
            else:
                month = int(month) - 1
            month = str(month).rjust(2, '0')
            date_from = year + month

            if date_from:
                if ld['contract'].slip_ids:
                    for pay in ld['contract'].slip_ids:
                        if str(pay.payslip_period_id.start_period[0:7]).replace('-', '') == date_from:
                            for line in pay.line_ids:
                                if line.code in ('BASE_APORTES', 'IBCSS'):
                                    ibc = line.total
            amount = round(ibc)
            lr[0] = amount
        return lr

    # Ley Maria # TODO
    
    def _aus_ley_maria(self, ld):
        res = False
        payslip = ld['payslip']
        if payslip.leave_ids:
            for leave in payslip.leave_ids:
                if leave.holiday_status_id.name == "LEY MARIA":
                    res = True
        if res:
            contract = ld['contract']
            maria = 0
            for leave in payslip.leave_ids:
                if leave.holiday_status_id.name == "LEY MARIA":
                    maria += leave.number_of_days_in_payslip
            lr[0] = (contract.wage / 30)
            lr[1] = maria
        else:
            lr[0] = 'na'
        return lr

    # Ley Maria # TODO
    
    def _bencaldo(self, ld):
        res = False
        payslip = ld['payslip']
        if payslip.leave_ids:
            for leave in payslip.leave_ids:
                if leave.holiday_status_id.name == "CALAMIDAD DOMESTICA":
                    res = True
        if res:
            contract = ld['contract']
            caldo = 0
            for leave in payslip.leave_ids:
                if leave.holiday_status_id.name == "CALAMIDAD DOMESTICA":
                    caldo += leave.number_of_days_in_payslip
            lr[0] = (contract.wage / 30)
            lr[1] = caldo
        else:
            lr[0] = 'na'
        return lr

    # Basico #TODO
    
    def _basico(self, ld):
        res = False
        wd = ld['worked_days'].dict['WORK102'].number_of_days
        if ld['contract'].type_id.clase == 'regular' or not ld['contract'].type_id.clase:
            res = True
        if res:
            dias_trab = wd
            amount = 0.0
            if dias_trab > 0:
                amount = ld['contract'].wage / 30
            lr[1] = dias_trab
            lr[0] = amount
        else:
            lr[0] = 'na'
        return lr

    # Basico INT #TODO
    
    def _basicoint(self, ld):
        res = False
        wd = ld['worked_days'].dict['WORK102'].number_of_days
        if ld['contract'].type_id.clase == 'integral':
            res = True
        if res:
            dias_trab = wd
            amount = 0.0
            if dias_trab > 0:
                amount = ld['contract'].wage / 30
            lr[1] = dias_trab
            lr[0] = amount
        else:
            lr[0] = 'na'
        return lr


    # Cuota de sostenimiento #TODO
    
    def _basicocs(self, ld):
        wd = ld['worked_days'].dict['WORK102'].number_of_days
        contract = ld['contract']

        if contract.fiscal_type_id.code == '12':
            lr[0] = round((contract.wage) / 30)
            lr[2] = 50
        elif contract.fiscal_type_id.code == '19':
            lr[0] = round((contract.wage) / 30)
            lr[1] = 100
        lr[1] = wd
        return lr

    # Total devengado 2134
    
    def _subtotal(self, ld):
        lr[0] = ld['categories'].DEVENGADO + ld['categories'].OTROS_DEVENGOS + ld['categories'].EXCEPTUADOS + ld['categories'].NOGRAV + ld['categories'].OTROS_DEVENGOS_SALARIALES + ld['categories'].DESREM + ld['categories'].INGCOM + ld['categories'].OTRDER
        return lr

    # IBC seguridad mensual 2344
    
    def _ibcss(self, ld):
        devengo = ld['categories'].DEVENGADO
        otro_devengo = ld['categories'].OTROS_DEVENGOS
        otro_devengo -= ld['AUXILIO_MOVILIZA'] if 'AUXILIO_MOVILIZA' in ld else 0.0
        incapacidadmayor180 = ld['INCAPACIDADMAYOR180'] if ld['rules'].INCAPACIDADMAYOR180 else 0.0
        otro_devengo_salariales = ld['categories'].OTROS_DEVENGOS_SALARIALES + incapacidadmayor180
        descansos_remunerados = ld['categories'].DESREM
        ingresos_complementarios = ld['categories'].INGCOM
        sal_minimo = ld['SAL_MINIMO'] if ld['rules'].SAL_MINIMO else 0.0
        tope = sal_minimo * 25
        ibcss = 0
        payslip = ld['payslip']
        contract = ld['contract']

        if payslip.payslip_period_id.schedule_pay == 'bi-monthly' and payslip.tipo_nomina.code == 'Nomina' and int(
                payslip.payslip_period_id.end_period[8:10]) < 16:  # para dividir el tope en nominas quincenales
            tope = sal_minimo * 12.5
        wdl = 0
        if payslip.worked_days_line_ids:
            for wd in payslip.worked_days_line_ids:
                if wd.code == 'DEDUCCION_CONTRATO':
                    wdl += 1
        proll_period_c = payslip.payslip_period_id.name[0:7]
        # itera a traves de todas las quincenas
        for proll in contract.slip_ids:
            # periodo de la nomina actual
            proll_period = proll.payslip_period_id.name[0:7]

            # compara cada periodo con el periodo de la nomina actual
            if (proll_period_c == proll_period and (
                    proll.payslip_period_id.end_period < payslip.payslip_period_id.end_period or proll.tipo_nomina.code != payslip.tipo_nomina.code) and proll.id != payslip.id):  # para que tome devengos antes de este periodo
                # recorre las lineas de la nomina y obtiene los parametros
                for wd in proll.worked_days_line_ids:
                    if wd.code == 'DEDUCCION_CONTRATO':
                        wdl += 1
                for value in proll.line_ids:
                    if value.category_id.code == 'DEVENGADO':
                        devengo += value.total
                    if value.category_id.code == 'OTROS_DEVENGOS' and value.code not in ('AUXILIO_MOVILIZA'):
                        otro_devengo += value.total
                    if value.code == 'INCAPACIDADMAYOR180':
                        otro_devengo_salariales += value.total
                    if value.code == 'IBCSS':
                        ibcss += value.total
                    if value.category_id.code == 'OTROS_DEVENGOS_SALARIALES':
                        otro_devengo_salariales += value.total
                    if value.category_id.code == 'DESREM':
                        descansos_remunerados += value.total
                    if value.category_id.code == 'INGCOM':
                        ingresos_complementarios += value.total
                    if value.category_id.code == 'VAC1':
                        ingresos_complementarios += value.total
                    if value.category_id.code == 'VAC2':
                        ingresos_complementarios += value.total

        salarial = devengo + otro_devengo_salariales + descansos_remunerados + ingresos_complementarios
        tope40 = (salarial + otro_devengo) * 0.4

        if tope40 > otro_devengo:
            total = salarial
        else:
            total = salarial + (otro_devengo - tope40)

        if contract.type_id.clase == 'integral':
            total = total * 0.7

        if total >= tope:
            total = tope
        # ajustar ibc a salario minimo en la segunda quincena

        if wdl != 0:
            dias = ld['DIAS_TRAB'] if ld['rules'].DIAS_TRAB else 0.0
            total = sal_minimo / 30 * dias + ibcss
        if payslip.tipo_nomina.code == 'Nomina' and wdl == 0:
            if payslip.payslip_period_id.schedule_pay == 'bi-monthly':
                if int(payslip.payslip_period_id.end_period[8:10]) > 16:
                    if total < sal_minimo:
                        total = sal_minimo
                else:
                    if total < sal_minimo / 2:
                        total = sal_minimo / 2
            elif payslip.payslip_period_id.schedule_pay == 'monthly':
                if total < sal_minimo:
                    total = sal_minimo
        # int(payslip.payslip_period_id.end_period[8:10])>16
        lr[0] = round(total)
        return lr

    # IBC parafiscales 2266
    
    def _ibcpf(self, ld):
        res = False
        payslip = ld['payslip']
        if (payslip.payslip_period_id.schedule_pay == 'bi-monthly' and int(payslip.payslip_period_id.end_period[
                                                                           8:10]) > 15 and payslip.tipo_nomina.code == 'Nomina') or payslip.payslip_period_id.schedule_pay != 'bi-monthly' or payslip.tipo_nomina.code == 'Liquidacion':
            res = True
        if res:
            categories = ld['categories']
            rules = ld['rules']
            contract = ld['contract']
            devengo = categories.DEVENGADO
            # otros_devengos_sal = categories.OTROS_DEVENGOS_SALARIALES
            licencia_maternidad = ld['LICENCIA_MATERNIDAD'] if rules.LICENCIA_MATERNIDAD else 0.0
            descansos_remunerados = categories.DESREM
            otros_derechos = categories.OTRDER
            ingresos_complementarios = categories.INGCOM
            proll_period_c = payslip.payslip_period_id.name[0:7]
            # itera a traves de todas las quincenas
            for proll in contract.slip_ids:
                # periodo de la nomina actual
                proll_period = proll.payslip_period_id.name[0:7]

                # compara cada periodo con el periodo de la nomina actual
                if proll_period_c == proll_period and proll.id != payslip.id:
                    # recorre las lineas de la nomina y obtiene los parametros
                    for value in proll.line_ids:
                        if value.category_id.code == 'DEVENGADO':
                            devengo += value.total
                        if value.code == 'LICENCIA_MATERNIDAD':
                            licencia_maternidad += value.total
                        if value.category_id.code == 'DESREM':
                            descansos_remunerados += value.total
                        if value.category_id.code == 'OTRDER':
                            otros_derechos += value.total
                        if value.category_id.code == 'INGCOM':
                            ingresos_complementarios += value.total

            total = devengo + ingresos_complementarios + otros_derechos + descansos_remunerados + licencia_maternidad

            if contract.type_id.clase == 'integral':
                total = total * 0.7

            lr[0] = round(total)
        else:
            lr[0] = 'na'
        return lr

    # Novedades pagos 2342
    
    def _novedades(self, ld):
        res = False
        payslip = ld['payslip']
        if payslip.novedades_total_ids:
            for novedades in payslip.novedades_total_ids:
                if novedades.total > 0:
                    res = True
        if res:
            suma = 0
            for novedades in payslip.novedades_total_ids:
                if novedades.total > 0:
                    if novedades.category_id.code != "COMISION" and novedades.category_id.code != "COMIMEVAP" and novedades.category_id.code != "AJUST_SALARIO" and novedades.category_id.code != "TRANSADI":
                        suma += novedades.total
            lr[0] = suma
        else:
            lr[0] = 'na'
        return lr

    # IBC ARL 2477
    
    def _ibcarl(self, ld):
        res = False
        payslip = ld['payslip']
        if (payslip.payslip_period_id.schedule_pay == 'bi-monthly' and int(payslip.payslip_period_id.end_period[
                                                                           8:10]) > 15 and payslip.tipo_nomina.code == 'Nomina') or payslip.payslip_period_id.schedule_pay != 'bi-monthly' or payslip.tipo_nomina.code == 'Liquidacion':
            res = True
        if res:
            contract = ld['contract']
            rules = ld['rules']
            categories = ld['categories']

            salminimo = ld['SAL_MINIMO'] if rules.SAL_MINIMO else 0.0
            devengo = categories.DEVENGADO
            ingresos_complementarios = categories.INGCOM
            proll_period_c = payslip.payslip_period_id.name[0:7]
            # itera a traves de todas las quincenas
            for proll in contract.slip_ids:
                # periodo de la nomina actual
                proll_period = proll.payslip_period_id.name[0:7]
                # compara cada periodo con el periodo de la nomina actual
                if proll_period_c == proll_period and proll.id != payslip.id:
                    # recorre las lineas de la nomina y obtiene los parametros
                    for value in proll.line_ids:
                        if value.category_id.code == 'DEVENGADO':
                            devengo += value.total
                        if value.category_id.code == 'INGCOM':
                            ingresos_complementarios += value.total

            total = devengo + ingresos_complementarios

            tope = salminimo * 25
            if contract.type_id.clase == 'integral':
                total = total * 0.7
            if total > tope:
                total = tope
            result = round(total)

            dias = ld['DIAS_TRAB_MES'] if rules.DIAS_TRAB_MES else 0

            if dias <= 0.0:
                result = 0.0
            dias = dias or 1
            if result / dias < salminimo / dias:
                result = salminimo / 30 * dias
            lr[0] = result
        else:
            lr[0] = 'na'
        return lr

    # Fondo solidaridad 2111
    
    def _fondosolid(self, ld):
        payslip = ld['payslip']
        rules = ld['rules']
        contract = ld['contract']
        s = int(payslip.payslip_period_id.end_period[8:10])
        res = False
        if s > 15 and contract.fiscal_subtype_id.code in ('00', False):
            base_ap = ld['IBCSS'] if rules.IBCSS else 0.0
            sal_minimo = ld['SAL_MINIMO'] if rules.SAL_MINIMO else 0.0
            if base_ap > 4 * sal_minimo:
                res = True

        if res:
            contract = ld['contract']
            fondosolid, rate = 0, 0
            diastrab = ld['worked_days'].dict['WORK102'].number_of_days
            proll_period_c = payslip.payslip_period_id.name[0:7]
            # itera a traves de todas las quincenas
            for proll in contract.slip_ids:
                # periodo de la nomina actual
                proll_period = proll.payslip_period_id.name[0:7]
                if (
                        proll_period_c == proll_period and proll.payslip_period_id.end_period < payslip.payslip_period_id.end_period and proll.id != payslip.id):  # para que tome devengos antes de este periodo
                    # recorre las lineas de la nomina y obtiene los parametros
                    for value in proll.line_ids:
                        if value.code == 'FONDOSOLID':
                            fondosolid += value.total
            if diastrab > 0.0:
                lr[2] = 1
            lr[0] = base_ap - fondosolid
        else:
            lr[0] = 'na'

        return lr

    # Fondo subsistencia 2112
    
    def _fondosubsistencia(self, ld):
        rules = ld['rules']
        solid = ld['FONDOSOLID'] if rules.FONDOSOLID else 0.0
        res = False
        if solid > 0:
            res = True
        if res:
            payslip = ld['payslip']
            contract = ld['contract']
            fondosub = 0
            proll_period_c = payslip.payslip_period_id.name[0:7]
            # itera a traves de todas las quincenas
            for proll in contract.slip_ids:
                # periodo de la nomina actual
                proll_period = proll.payslip_period_id.name[0:7]
                # compara cada periodo con el periodo de la nomina actual
                if (
                        proll_period_c == proll_period and proll.payslip_period_id.end_period < payslip.payslip_period_id.end_period and proll.id != payslip.id):  # para que tome devengos antes de este periodo
                    # recorre las lineas de la nomina y obtiene los parametros
                    for value in proll.line_ids:
                        if value.code == 'FONDOSUBSISTENCIA':
                            fondosub += value.total

            base_ap = ld['IBCSS'] if rules.IBCSS else 0.0
            amount = base_ap
            sal_minimo = ld['SAL_MINIMO'] if rules.SAL_MINIMO else 0.0
            result_rate = 0
            if base_ap >= 16 * sal_minimo and base_ap <= 17 * sal_minimo:
                result_rate += 0.2
            elif base_ap > 17 * sal_minimo and base_ap <= 18 * sal_minimo:
                result_rate += 0.4
            elif base_ap > 18 * sal_minimo and base_ap <= 19 * sal_minimo:
                result_rate += 0.6
            elif base_ap > 19 * sal_minimo and base_ap <= 20 * sal_minimo:
                result_rate += 0.8
            elif base_ap > 20 * sal_minimo:
                result_rate += 1

            if result_rate < 0.2:
                amount = 0
            lr[0] = amount
            lr[2] = result_rate
        else:
            lr[0] = 'na'
        return lr

    # Descuento autorizado 2502
    
    def _dcto_aut(self, ld):
        payslip = ld['payslip']
        suma = 0
        res = False
        if payslip.novedades_total_ids:
            for novedades in payslip.novedades_total_ids:
                if novedades.category_id.code == "DCTO_AUT":
                    res = True
                    suma += novedades.total
        if res:
            lr[0] = suma
        else:
            lr[0] = 'na'
        return lr

    # Deduccion EPS
    
    def _dedeps(self, ld):
        res = False
        rules = ld['rules']
        base = ld['IBCSS'] if rules.IBCSS else 0.0
        if base:
            res = True
        if res:
            payslip = ld['payslip']
            contract = ld['contract']
            dedeps = 0
            proll_period_c = payslip.payslip_period_id.name[0:7]
            # itera a traves de todas las quincenas
            for proll in contract.slip_ids:
                # periodo de la nomina actual
                proll_period = proll.payslip_period_id.name[0:7]

                # compara cada periodo con el periodo de la nomina actual
                if proll_period_c == proll_period and proll.id != payslip.id:  # para que tome devengos antes de este periodo proll.payslip_period_id.end_period < payslip.payslip_period_id.end_period
                    # recorre las lineas de la nomina y obtiene los parametros
                    for value in proll.line_ids:
                        if value.code == 'DEDEPS':
                            dedeps += value.total

            amount = (base * 4 / 100) - dedeps
            incapacidadmayor180 = ld['INCAPACIDADMAYOR180'] if rules.INCAPACIDADMAYOR180 else 0.0
            if incapacidadmayor180:
                amount = 0
            lr[0] = amount
        else:
            lr[0] = 'na'
        return lr

    # Deduccion pension
    
    def _dedpension(self, ld):
        res = False
        contract = ld['contract']
        rules = ld['rules']
        if contract.fiscal_subtype_id.code in ('00', False):
            base = ld['IBCSS'] if rules.IBCSS else 0.0
            if not base:
                base = ld['BASE_APORTES'] if rules.BASE_APORTES else 0.0
            if base:
                res = True
        if res:
            payslip = ld['payslip']
            dedpension = 0
            proll_period_c = payslip.payslip_period_id.name[0:7]
            # itera a traves de todas las quincenas
            for proll in contract.slip_ids:
                # periodo de la nomina actual
                proll_period = proll.payslip_period_id.name[0:7]
                # compara cada periodo con el periodo de la nomina actual
                if proll_period_c == proll_period and proll.id != payslip.id:  # para que tome devengos antes de este periodo
                    # recorre las lineas de la nomina y obtiene los parametros
                    for value in proll.line_ids:
                        if value.code == 'DEDPENSION':
                            dedpension += value.total

            amount = (base * 4 / 100) - dedpension
            incapacidadmayor180 = ld['INCAPACIDADMAYOR180'] if rules.INCAPACIDADMAYOR180 else 0.0
            subtotal = ld['SUBTOTAL'] if rules.SUBTOTAL else 0.0
            if incapacidadmayor180 or subtotal == 0:
                amount = 0
            lr[0] = amount
        else:
            lr[0] = 'na'
        return lr

    # Ingresos gravados 2426
    
    def _pago_mes(self, ld):
        payslip = ld['payslip']
        contract = ld['contract']
        e_v = self.env['variables.economicas']
        categories = ld['categories']
        rules = ld['rules']
        fecha = payslip.liquid_date
        val_p2 = 0
        for rete in contract.retencion_dos_ids:
            if fecha >= rete.period_id.date_from and fecha <= rete.period_id.date_to:
                val_p2 = rete.valor_porcentaje
        ## Calcula los parametros de la base de aportes
        s = payslip.payslip_period_id.name
        UVT = 33156
        try:
            UVT = e_v.getValue('UVT', payslip.liquidacion_date) or 33156
        except:
            pass
        res = False
        amount = 0
        subtotal = ld['SUBTOTAL'] if rules.SUBTOTAL else 0.0
        q_num = payslip.payslip_period_id.end_period[8:10]
        if (q_num > 15 or payslip.tipo_nomina.code == 'Vacaciones') and subtotal > 0:
            # periodo de la nomina actual
            devengo = categories.DEVENGADO + categories.OTROS_DEVENGOS_SALARIALES + categories.DESREM + categories.OTRDER
            basico = ld['BASICO'] if rules.BASICO else 0.0
            otro_devengo = categories.OTROS_DEVENGOS
            exceptuados = categories.EXCEPTUADOS
            dias, prima = 0, 0
            proll_period_c = payslip.payslip_period_id.name[1:7]
            # itera a traves de todas las quincenas
            for proll in contract.slip_ids:
                # periodo de la nomina actual
                proll_period = proll.payslip_period_id.name[1:7]

                # compara cada periodo con el periodo de la nomina actual
                if proll_period_c == proll_period and proll.id != payslip.id:
                    # recorre las lineas de la nomina y obtiene los parametros
                    for value in proll.line_ids:
                        if value.category_id.code in 'DEVENGADO':
                            devengo += value.total
                        if value.category_id.code in ('DESREM', 'OTRDER'):
                            devengo += value.total
                        if value.category_id.code == 'OTROS_DEVENGOS':
                            otro_devengo += value.total
                        if value.category_id.code == 'OTROS_DEVENGOS_SALARIALES':
                            devengo += value.total
                        if value.category_id.code == 'EXCEPTUADOS':
                            exceptuados += value.total
                        if value.code == 'PRIMA':
                            prima += value.total
                        if value.code == 'BASICO':
                            basico += value.total
            for proll in contract.slip_ids:
                # periodo de la nomina actual
                proll_period = proll.payslip_period_id.name[1:7]

                # compara cada periodo con el periodo de la nomina actual
                if (proll_period_c == proll_period) and proll.tipo_nomina.code == 'Vacaciones' and proll.id != payslip.id:
                    for vac_dias in proll.leave_days_ids:
                        dias += 1
            auxtransp = ld['AUXTRANSP'] if rules.AUXTRANSP else 0.0
            if basico < contract.wage:
                devengo += -basico + contract.wage
            amount = devengo + exceptuados + otro_devengo - auxtransp
            if val_p2:
                amount += prima
            if amount >= UVT * 128.96 and UVT > 0:
                res = True
        if res:
            lr[0] = amount
        else:
            lr[0] = 'na'
        return lr

    # Aporte obligatorio mes fondo salud
    
    def _apor_obli_mes_salud(self, ld):
        rules = ld['rules']
        if rules.PAGO_MES:
            res = True
        else:
            res = False
        if res:
            lr[0] = ld['IBCSS'] if rules.IBCSS else 0.0
            lr[2] = 4
        else:
            lr[0] = 'na'
        return lr

    # Aporte obligatorio mes fondo pension
    
    def _apor_obli_mes_pension(self, ld):
        rules = ld['rules']
        if rules.PAGO_MES:
            res = True
        else:
            res = False
        if res:
            lr[0] = ld['IBCSS'] if rules.IBCSS else 0.0
            lr[2] = 4
        else:
            lr[0] = 'na'
        return lr

    # Aporte obligatorio mes FPS
    
    def _aporte_oblig_mes_fsp(self, ld):
        rules = ld['rules']
        if rules.PAGO_MES:
            res = True
        else:
            res = False

        if res:
            payslip = ld['payslip']

            parameters = {
                'solidaridad': 0.0,
                'subsistencia': 0.0,
                'solidaridadintegral': 0.0,
                'ajustededusolida': 0.0,

            }

            s = payslip.payslip_period_id.name
            q_num = ((0 if 'Q1' in s else 1) + (0 if '1Q' in s else 1))

            try:
                parameters['solidaridad'] = rules.FONDOSOLID if rules.FONDOSOLID else 0.0
            except:
                parameters['solidaridad'] = ld['FONDOSOLID'] if ld['FONDOSOLID'] else 0.0
            try:
                parameters['solidaridad'] = ld['FONDOSOLID'] if ld['FONDOSOLID'] else 0.0
            except:
                parameters['solidaridad'] = rules.FONDOSOLID if rules.FONDOSOLID else 0.0

            try:
                parameters['solidaridadintegral'] = rules.FONDOSOLIDINT if rules.FONDOSOLIDINT else 0.0
            except:
                parameters['solidaridadintegral'] = ld['FONDOSOLIDINT'] if ld['FONDOSOLIDINT'] else 0.0
            try:
                parameters['solidaridadintegral'] = ld['FONDOSOLIDINT'] if ld['FONDOSOLIDINT'] else 0.0
            except:
                parameters['solidaridadintegral'] = rules.FONDOSOLIDINT if rules.FONDOSOLIDINT else 0.0

            try:
                parameters['subsistencia'] = rules.FONDOSUBSISTENCIA if rules.FONDOSUBSISTENCIA else 0.0
            except:
                parameters['subsistencia'] = ld['FONDOSUBSISTENCIA'] if ld['FONDOSUBSISTENCIA'] else 0.0
            try:
                parameters['subsistencia'] = ld['FONDOSUBSISTENCIA'] if ld['FONDOSUBSISTENCIA'] else 0.0
            except:
                parameters['subsistencia'] = rules.FONDOSUBSISTENCIA if rules.FONDOSUBSISTENCIA else 0.0

            try:
                parameters['ajustededusolida'] = rules.AJUSTE_SOLI_DEDU if rules.AJUSTE_SOLI_DEDU else 0.0
            except:
                parameters['ajustededusolida'] = ld['AJUSTE_SOLI_DEDU'] if ld['AJUSTE_SOLI_DEDU'] else 0.0
            try:
                parameters['ajustededusolida'] = ld['AJUSTE_SOLI_DEDU'] if ld['AJUSTE_SOLI_DEDU'] else 0.0
            except:
                parameters['ajustededusolida'] = rules.AJUSTE_SOLI_DEDU if rules.AJUSTE_SOLI_DEDU else 0.0

            if q_num != 1:
                contract = ld['contract']
                # verifica si la nomina es quincenal
                if contract.schedule_pay == 'bi-monthly':

                    # itera a traves de todas las quincenas
                    for proll in contract.slip_ids:

                        # obtiene el periodo de la quincena actual
                        proll_period_c = payslip.payslip_period_id.start_period[1:7]

                        # obtiene el periodo de cada quincena
                        proll_period = proll.payslip_period_id.start_period[1:7]

                        # obtiene el numero de cada quincena

                        s1 = proll.payslip_period_id.name
                        q_num1 = ((0 if 'Q1' in s1 else 1) + (0 if '1Q' in s1 else 1))

                        # compara cada periodo con el periodo de la nomina actual
                        if (proll_period_c == proll_period) and (q_num1 == 1) and proll.id != payslip.id:

                            # recorre las lineas de la nomina y obtiene los parametros
                            for value in proll.line_ids:

                                if parameters['subsistencia'] != None:
                                    if value.code == 'FONDOSUBSISTENCIA':
                                        parameters['subsistencia'] += value.total

                                if parameters['solidaridad'] != None:
                                    if value.code == 'FONDOSOLID':
                                        parameters['solidaridad'] += value.total

                                if parameters['solidaridadintegral'] != None:
                                    if value.code == 'FONDOSOLIDINT':
                                        parameters['solidaridadintegral'] += value.total

                                if parameters['ajustededusolida'] != None:
                                    if value.code == 'AJUSTE_SOLI_DEDU ':
                                        parameters['ajustededusolida'] += value.total

            SUMA = (parameters['subsistencia'] + parameters['solidaridad'] + parameters['solidaridadintegral'] +
                    parameters['ajustededusolida'])

            lr[0] = int(round(SUMA))
        else:
            lr[0] = 'na'
        return lr

    # Ingresos no constitutivos de renta
    
    def _ingnocrenta(self, ld):
        rules = ld['rules']
        if rules.PAGO_MES:
            res = True
        else:
            res = False

        if res:
            result = 0
            result += ld['PAGO_MES'] if rules.PAGO_MES else 0.0

            try:
                result -= ld['APOR_OBLI_MES_PENSION'] if ld['APOR_OBLI_MES_PENSION'] else 0.0
            except:
                result -= rules.APOR_OBLI_MES_PENSION if rules.APOR_OBLI_MES_PENSION else 0.0

            try:
                result -= ld['APOR_OBLI_MES_SALUD'] if ld['APOR_OBLI_MES_SALUD'] else 0.0
            except:
                result -= rules.APOR_OBLI_MES_SALUD if rules.APOR_OBLI_MES_SALUD else 0.0

            try:
                result -= ld['APORTE_OBLIG_MES_FSP'] if ld['APORTE_OBLIG_MES_FSP'] else 0.0
            except:
                result -= rules.APORTE_OBLIG_MES_FSP if rules.APORTE_OBLIG_MES_FSP else 0.0
            lr[0] = result
        else:
            lr[0] = 'na'
        return lr

    # Aporte promedio de salud
    
    def _apor_prom_salud(self, ld):
        rules = ld['rules']
        if rules.PAGO_MES:
            res = True
        else:
            res = False
        if res:
            lr[0] = ld['contract'].promedio_p2
        else:
            lr[0] = 'na'
        return lr

    # renta excenta
    
    def _renta_exenta(self, ld):
        rules = ld['rules']
        if rules.PAGO_MES:
            res = True
        else:
            res = False
        if res:
            lr[0] = ld['APORTE_VOLUNTA_MES_AFC_PENSION'] if rules.APORTE_VOLUNTA_MES_AFC_PENSION else 0.0
        else:
            lr[0] = 'na'
        return lr

    # Retencion en la fuente
    
    def _rtefte_apl(self, ld):
        res = False
        rules = ld['rules']
        contract = ld['contract']
        payslip = ld['payslip']
        if rules.PAGO_MES and not contract.p2:
            res = True
        if payslip.novedades_total_ids:
            for novedades in payslip.novedades_total_ids:
                if novedades.category_id.code == "AJUST_RTE_APL":
                    res = False
        if res:
            try:
                lr[0] = ld['BASERTEFTE'] if ld['BASERTEFTE'] else 0.0
            except:
                lr[0] = rules.BASERTEFTE if rules.BASERTEFTE else 0.0
        else:
            lr[0] = 'na'
        return lr

    # Base retencion en la fuente
    
    def _basertefte(self, ld):
        res = False
        rules = ld['rules']
        if rules.PAGO_MES:
            res = True
        if res:
            result = 0
            try:
                result += ld['INGNOCRENTA'] if 'INGNOCRENTA' in ld else 0.0
            except:
                result += rules.INGNOCRENTA if rules.INGNOCRENTA else 0.0

            try:
                result -= ld['TOPE40'] if 'TOPE40' in ld else 0.0
            except:
                result -= rules.TOPE40 if rules.TOPE40 else 0.0
            lr[0] = result
        else:
            lr[0] = 'na'
        return lr

    # Auxilio de movilizacion art 128
    
    def _aux_movi(self, ld):
        res = False
        payslip = ld['payslip']
        amount = 0
        wd = ld['worked_days'].dict['WORK102'].number_of_days

        sql = "SELECT hpotc.code, hpotl.valor " \
              "FROM hr_payslip_obligacion_tributaria_line hpotl, " \
              "hr_payroll_obligacion_tributaria_category hpotc, " \
              "hr_payroll_obligacion_tributaria hpot " \
              "WHERE hpotl.payslip_id = {payslip} " \
              "AND hpot.category_id = hpotc.id " \
              "AND hpot.id = hpotl.obligacion_id " \
              "AND hpotc.code = 'AUX_MOVILIZACION'".format(payslip=payslip.dict.id)
        self._cr.execute(sql)
        codval = self._cr.fetchall()
        if codval:
            amount += codval[0][1] * wd / 30
            res = True

        # EJECUTAR CON CURSOR NUEVO CUANDO LOS DATOS NO SON VISIBLES CON EL MISMO CURSOR

        # new_cr = sql_db.db_connect(self.env.cr.dbname).cursor()
        # with api.Environment.manage():
        #     new_cr.execute(sql)
        #     codval = new_cr.fetchall()
        #     new_cr.close()
        #     if codval:
        #         amount += codval[0][1] * wd / 30

        if res:
            lr[0] = amount
        else:
            lr[0] = 'na'
        return lr

    # Plan exequial
    
    def _plan_exequial(self, ld):
        res = False
        payslip = ld['payslip']
        amount = 0
        wd = ld['worked_days'].dict['WORK102'].number_of_days

        sql = "SELECT hpotc.code, hpotl.valor " \
              "FROM hr_payslip_obligacion_tributaria_line hpotl, " \
              "hr_payroll_obligacion_tributaria_category hpotc, " \
              "hr_payroll_obligacion_tributaria hpot " \
              "WHERE hpotl.payslip_id = {payslip} " \
              "AND hpot.category_id = hpotc.id " \
              "AND hpot.id = hpotl.obligacion_id " \
              "AND hpotc.code = 'PLAN_EXEQUIAL'".format(payslip=payslip.dict.id)
        self._cr.execute(sql)
        codval = self._cr.fetchall()
        if codval:
            amount += codval[0][1] * wd / 30
            res = True

        # EJECUTAR CON CURSOR NUEVO CUANDO LOS DATOS NO SON VISIBLES CON EL MISMO CURSOR

        # new_cr = sql_db.db_connect(self.env.cr.dbname).cursor()
        # with api.Environment.manage():
        #     new_cr.execute(sql)
        #     codval = new_cr.fetchall()
        #     new_cr.close()
        #     if codval:
        #         amount += codval[0][1] * wd / 30

        if res:
            lr[0] = amount
        else:
            lr[0] = 'na'
        return lr

    # Hora extra adicional
    
    def _he_add(self, ld):
        res = False
        payslip = ld['payslip']
        amount = 0
        wd = ld['worked_days'].dict['WORK102'].number_of_days


        sql = "SELECT hpotc.code, hpotl.valor " \
              "FROM hr_payslip_obligacion_tributaria_line hpotl, " \
              "hr_payroll_obligacion_tributaria_category hpotc, " \
              "hr_payroll_obligacion_tributaria hpot " \
              "WHERE hpotl.payslip_id = {payslip} " \
              "AND hpot.category_id = hpotc.id " \
              "AND hpot.id = hpotl.obligacion_id " \
              "AND hpotc.code = 'HE_ADD'".format(payslip=payslip.dict.id)
        self._cr.execute(sql)
        codval = self._cr.fetchall()
        if codval:
            amount += codval[0][1] * wd / 30
            res = True

        # EJECUTAR CON CURSOR NUEVO CUANDO LOS DATOS NO SON VISIBLES CON EL MISMO CURSOR

        # new_cr = sql_db.db_connect(self.env.cr.dbname).cursor()
        # with api.Environment.manage():
        #     new_cr.execute(sql)
        #     codval = new_cr.fetchall()
        #     new_cr.close()
        #     if codval:
        #         amount += codval[0][1] * wd / 30

        if res:
            lr[0] = amount
        else:
            lr[0] = 'na'
        return lr

    # Dia 31
    
    def _hed31(self, ld):
        he = 0
        res = False
        payslip = ld['payslip']
        if payslip.extrahours_total_ids:
            for extra in payslip.extrahours_total_ids:
                if extra.type_id.code == "HTO":
                    res = True
                    he += extra.total
        if res:
            lr[0] = he
        else:
            lr[0] = 'na'
        return lr

    # Auxilio movilizacion
    
    def _aux_movilizacion(self, ld):
        dto = 0
        res = False
        payslip = ld['payslip']
        rules = ld['rules']
        quincena = int(payslip.payslip_period_id.start_date[8:])
        if quincena > 15 or payslip.payslip_period_id.schedule_pay == 'monthly':
            try:
                dias = ld['worked_days'].dict['WORK102'].number_of_days
                for tributaria in payslip.obligaciones_ids:
                    if tributaria.category_id.code == "AUX_MOVILIZACION":
                        res = True
                        dto += tributaria.valor / 30 * dias
            except:
                res = False

        base = ld['BASEMOVILIZACION'] if rules.BASEMOVILIZACION else 0.0
        if base > 0:
            dto += base
            res = True
        if res:
            lr[0] = dto
        else:
            lr[0] = 'na'
        return lr


    # Ingresos no constitivos de renta
    
    def _ingnocrenta(self, ld):
        rules = ld['rules']
        if rules.PAGO_MES:
            res = True
        else:
            res = False

        if res:
            result = 0
            result += ld['PAGO_MES'] if rules.PAGO_MES else 0.0

            try:
                result -= ld['APOR_OBLI_MES_PENSION'] if 'APOR_OBLI_MES_PENSION' in ld else 0.0
            except:
                result -= rules.APOR_OBLI_MES_PENSION if rules.APOR_OBLI_MES_PENSION else 0.0

            try:
                result -= ld['APOR_OBLI_MES_SALUD'] if 'APOR_OBLI_MES_SALUD' in ld else 0.0
            except:
                result -= rules.APOR_OBLI_MES_SALUD if rules.APOR_OBLI_MES_SALUD else 0.0

            try:
                result -= ld['APORTE_OBLIG_MES_FSP'] if 'APORTE_OBLIG_MES_FSP' in ld else 0.0
            except:
                result -= rules.APORTE_OBLIG_MES_FSP if rules.APORTE_OBLIG_MES_FSP else 0.0
            lr[0] = result
        else:
            lr[0] = 'na'
        return lr

    # Tope 40
    
    def _tope40(self, ld):
        rules = ld['rules']
        if rules.PAGO_MES:
            res = True
        else:
            res = False
        if res:
            subtotal1, subtotal2, subtotal3, subtotal4 = 0, 0, 0, 0

            try:
                subtotal1 += ld.get('INGNOCRENTA', 0)
            except:
                subtotal1 += rules.INGNOCRENTA if rules.INGNOCRENTA else 0.0

            try:
                subtotal2 += ld.get('APORVOL', 0)
            except:
                subtotal2 += rules.APORVOL if rules.APORVOL else 0.0

            try:
                subtotal3 += ld.get('DEDUCIBLES', 0)
            except:
                subtotal3 += rules.DEDUCIBLES if rules.DEDUCIBLES else 0.0

            try:
                subtotal4 += ld.get('RENTA_EXENTA', 0)
            except:
                subtotal4 += rules.RENTA_EXENTA if rules.RENTA_EXENTA else 0.0

            tope40 = subtotal1 * 40 / 100
            subtotal = subtotal1 - subtotal3 + subtotal4

            if tope40 > subtotal:
                lr[0] = subtotal
            else:
                lr[0] = tope40
        else:
            lr[0] = 'na'
        return lr

    # Cesantias # TODO
    
    def _cesantias(self, ld):
        res = False
        rules = ld['rules']
        contract = ld['contract']
        base = ld['BASEPROV'] if rules.BASEPROV else 0.0
        if base > 0 and contract.type_id.clase != 'integral':
            res = True
        if res:
            payslip = ld['payslip']
            aux_trsp = ld['AUXTRANSP'] if rules.AUXTRANSP else 0.0
            desde = int(payslip.dict.payslip_period_id.start_period.replace('-', '')[0:6])
            hasta = int(payslip.dict.payslip_period_id.end_period.replace('-', '')[0:6])
            if contract.slip_ids:
                for nomina in contract.slip_ids:
                    if nomina.id != payslip.id:
                        if int(nomina.payslip_period_id.start_period.replace('-', '')[0:6]) >= desde and int(
                                nomina.payslip_period_id.end_period.replace('-', '')[0:6]) <= hasta:
                            for regla in nomina.line_ids:
                                if regla.code == 'AUXTRANSP':
                                    aux_trsp += regla.total

            lr[0] = base + aux_trsp
            lr[2] = 8.33
        else:
            lr[0] = 'na'
        return lr

    # Medicina prepagada
    
    def _medicina_prepaga(self, ld):
        res = False
        payslip = ld['payslip']
        if payslip.obligaciones_ids:
            for tributaria in payslip.obligaciones_ids:
                if tributaria.category_id.code == "MEDICINA_PREPAGA":
                    res = True
        if res:
            rules = ld['rules']
            DTO = 0
            if payslip.obligaciones_ids:
                for tributaria in payslip.obligaciones_ids:
                    if tributaria.category_id.code == "MEDICINA_PREPAGA":
                        DTO += tributaria.valor
            else:
                DTO = 0
            pago_mes = ld['PAGO_MES'] if rules.PAGO_MES else 0.0
            tope = pago_mes * 0.3
            if DTO < tope:
                DTO = tope

            lr[0] = DTO
        else:
            lr[0] = 'na'
        return lr

    # Anticipos
    
    def _anticipo(self, ld):
        res = False
        payslip = ld['payslip']
        suma = 0
        for adv in payslip.dict.advance_ids:
            res = True
            suma += adv.amount
        if res:
            lr[0] = suma
        else:
            lr[0] = 'na'
        return lr

    # Dias Prima (prever-more)
    
    def _dias_prima(self, ld):
        payslip = ld['payslip']
        contract = ld['contract']
        month = int(payslip.payslip_period_id.end_date[5:7])
        nomina = (payslip.tipo_nomina.code in ('Nomina') and (
                    month == 6 or month == 7 or month == 12)) or payslip.tipo_nomina.code in ('Prima', 'Liquidacion')
        res = True if nomina and contract.type_id.clase != 'integral' else False
        if res:
            end_date, contract_date, days = payslip.payslip_period_id.start_date, contract.date_start, 0
            # obtener semestre a calcular
            if int(end_date[5:7]) > 7:
                month = 7
            else:
                month = 1
            date_start = end_date[0:4] + '-' + str(month).rjust(2, '0') + '-01'
            tope = contract_date
            if tope <= date_start:
                tope = date_start
            else:
                if int(contract_date[8:10]) > int(end_date[8:10]):
                    days = 30 - int(contract_date[8:10]) + 1
            if contract.slip_ids:
                for nomina in contract.slip_ids:
                    if nomina != payslip:
                        if tope <= nomina.payslip_period_id.start_period <= end_date and nomina.tipo_nomina.code in (
                                'Nomina', 'Liquidacion'):
                            for dias in nomina.worked_days_line_ids:
                                if dias.code in ('LICENCIA_NO_REMUNERADA1', 'SUSPENSION1', 'Ausencia_injustificada1'):
                                    days -= dias.number_of_days
            lr[0] = monthdelta(tope, end_date) * 30 + days
        else:
            lr[0] = 'na'
        return lr

    # Intereses cesantia anual
    
    def _int_cesantia_anual(self, ld):
        payslip = ld['payslip']

        if payslip.tipo_nomina.code == 'Int. Cesantias':
            res = True
        else:
            res = False
        if res:
            contract = ld['contract']
            result, result_qty, result_rate = 0, 0, 100
            periodo_desde = payslip.start_period[0:4] + '-01-01'
            periodo_hasta = payslip.start_period[0:4] + '-12-31'

            if contract.slip_ids:
                for nomina in contract.slip_ids:
                    if nomina.payslip_period_id.start_period >= periodo_desde and nomina.start_period <= periodo_hasta and nomina.id != payslip.id:
                        for line in nomina.line_ids:
                            if line.code in ('CESANTIA_ANUAL'):
                                result += line.total
                                result_qty += line.quantity

            lr[0] = result * 0.12 / 360
        else:
            lr[0] = 'na'
        return lr

    # AFCD
    
    def _afcd(self, ld):
        payslip = ld['payslip']
        s = payslip.payslip_period_id.name
        total = 0
        res = False
        q_num = ((0 if 'Q1' in s else 1) + (0 if '1Q' in s else 1))
        try:
            if q_num != 1:  # segunda quincena
                if payslip.obligaciones_ids:
                    for tributaria in payslip.obligaciones_ids:
                        if tributaria.category_id.code == "AFCDQ2":
                            total += tributaria.valor
                            res = True
            else:  # 1ra quincena
                if payslip.obligaciones_ids:
                    for tributaria in payslip.obligaciones_ids:
                        if tributaria.category_id.code == "AFCDQ1":
                            total += tributaria.valor
                            res = True
        except:
            res = False
        if res:
            lr[0] = total
        else:
            lr[0] = 'na'
        return lr

    # Base de provisiones
    
    def _baseprov(self, ld):
        res = False
        payslip = ld['payslip']
        contract = ld['contract']
        if payslip.tipo_nomina.code in ('Nomina', 'Liquidacion') and contract.reform != 'anterior' and (
                payslip.payslip_period_id.schedule_pay == 'bi-monthly' and int(
                str(payslip.payslip_period_id.end_period)[
                8:10]) > 15) or payslip.payslip_period_id.schedule_pay != 'bi-monthly' or payslip.tipo_nomina.code in (
                                                                                                        'Liquidacion'):
            res = True
        if res:
            base = 0
            categories = ld['categories']
            devengo = categories.DEVENGADO
            rules = ld['rules']
            # otro_devengo = categories.OTROS_DEVENGOS
            # otro_devengo -= AUXILIO_MOVILIZA if rules.AUXILIO_MOVILIZA else 0.0
            incapacidadmayor180 = ld['INCAPACIDADMAYOR180'] if rules.INCAPACIDADMAYOR180 else 0.0
            # se suma para que pague seguridad social y no como salario
            otro_devengo_salariales = categories.OTROS_DEVENGOS_SALARIALES + incapacidadmayor180
            descansos_remunerados = categories.DESREM
            ingresos_complementarios = categories.INGCOM
            proll_period_c = str(payslip.payslip_period_id.name)[0:7]
            # itera a traves de todas las quincenas
            for proll in contract.slip_ids:
                # periodo de la nomina actual
                proll_period = str(proll.payslip_period_id.name)[0:7]

                # compara cada periodo con el periodo de la nomina actual
                # para que tome devengos antes de este periodo
                if (proll_period_c == proll_period and payslip.tipo_nomina.code in ('Nomina', 'Vacaciones',
                                                                                    'Liquidacion') and proll.id != payslip.id):
                    # recorre las lineas de la nomina y obtiene los parametros
                    for value in proll.line_ids:
                        if value.category_id.code == 'DEVENGADO':
                            devengo += value.total
                        # if value.category_id.code == 'OTROS_DEVENGOS' and value.code not in('AUXILIO_MOVILIZA'):
                        #    otro_devengo += value.total
                        if value.code == 'INCAPACIDADMAYOR180':
                            otro_devengo_salariales += value.total
                        if value.category_id.code == 'OTROS_DEVENGOS_SALARIALES':
                            otro_devengo_salariales += value.total
                        if value.category_id.code == 'DESREM':
                            descansos_remunerados += value.total
                        if value.category_id.code == 'INGCOM':
                            ingresos_complementarios += value.total

            lr[0] = devengo + otro_devengo_salariales + descansos_remunerados + ingresos_complementarios
        else:
            lr[0] = 'na'
        return lr

    # Provision de vacaciones
    
    def _prov_vac(self, ld):
        res = False
        rules = ld['rules']
        base = ld['BASEPROV'] if rules.BASEPROV else 0.0
        payslip = ld['payslip']
        month = payslip.payslip_period_id.start_period[0:7]
        if base > 0:
            res = True
        if res:
            ajuste = 0
            contract = ld['contract']
            if contract.slip_ids:
                for nomina in contract.slip_ids:
                    if str(nomina.payslip_period_id.start_period)[0:7] == month and nomina.id != payslip.id:
                        for regla in nomina.line_ids:
                            if regla.code == 'PROV_VAC':
                                ajuste += regla.total

            lr[0] = (base * 4.17 / 100) - ajuste
        else:
            lr[0] = 'na'
        return lr

    # Acumulado cesantias
    
    def _acumces(self, ld):
        result, result_qty, result_rate, dias_diff = 0, 0, 100, 0
        payslip = ld['payslip']
        contract = ld['contract']
        if int(payslip.payslip_period_id.start_period[5:7]) == 12:
            res = True
        else:
            res = False
        if res:
            if payslip.novedades_total_ids:
                for novedades in payslip.novedades_total_ids:
                    if novedades.category_id.code == "ACUMCES":
                        result += novedades.total
            if result == 0:
                categories = ld['categories']
                end_date = contract.date_end or payslip.payslip_period_id.end_date
                # incluir acumulado de cesantias año anterior
                if int(payslip.payslip_period_id.start_period[
                       5:7]) == 1 and payslip.tipo_nomina.code == 'Liquidacion':
                    start_date = str(int(end_date[0:4]) - 1) + '-01-01'
                else:
                    start_date = end_date[0:4] + '-01-01'

                if contract.type_id.type_fijo is True:
                    result = contract.wage or 0.0
                else:
                    for proll in contract.slip_ids:
                        if proll.payslip_period_id.start_date >= start_date and proll.payslip_period_id.end_date <= end_date and proll.id != payslip.id:
                            result_qty += 1
                            for leave in proll.leave_ids:
                                if leave.date_to > payslip.payslip_period_id.end_date and leave.date_from < payslip.payslip_period_id.end_date and leave.date_from[
                                                                                                                                                   5:7] == payslip.payslip_period_id.end_date[
                                                                                                                                                           5:7] and leave.holiday_status_id.code == 'VAC':
                                    dias_diff = int(payslip.payslip_period_id.end_date[8:10]) - int(
                                        leave.date_from[8:10]) + 1
                            for value in proll.line_ids:
                                #          if (value.category_id.code in ('DEVENGADO','INGCOM') and value.code != 'BASICO'):
                                if (value.category_id.code in (
                                'DEVENGADO', 'OTROS_DEVENGOS_SALARIALES')) and value.code != 'BASICO' or value.code in (
                                'AUXTRANSP', 'COMISION'):
                                    if dias_diff > 0 and value.category_id.code in ('DESREM'):
                                        result += (value.total / value.quantity) * dias_diff
                                    else:
                                        result += value.total

                    if result > 0:  # se agrego fuera del for anterior, porque este valor solo aplica a los que tiene variables:  (DEVENGOS,INGCOM) para los salario fijo no.
                        for proll in contract.slip_ids:
                            if proll.payslip_period_id.start_date >= start_date and proll.payslip_period_id.end_date <= end_date and proll.id != payslip.id:
                                for value in proll.line_ids:
                                    if value.category_id.code in ('OTROS_DEVENGOS_SALARIALES'):
                                        result += value.total
                        result += categories.OTROS_DEVENGOS_SALARIALES or 0.0
                result += categories.DESREM or 0.0
                result += categories.INGCOM or 0.0
            lr[0] = result
            lr[1] = result_qty
        else:
            lr[0] = 'na'
        return lr

    # RTEFTE_APL_INDEM Solo Moreproducts
    
    def _rtefte_apl_indem(self, ld):

        res = False
        rules = ld['rules']
        contract = ld['contract']
        payslip = ld['payslip']
        e_v = self.env['variables.economicas']
        UVT = e_v.getValue('UVT', payslip.liquidacion_date) or 33156
        if rules.PAGO_MES and not contract.p2 and contract.wage > 20 * UVT and rules.INDEMNIZACION:
            res = True
        if res:
            lr[0] = ld['INDEMNIZACION'] * 0.2
        else:
            lr[0] = 'na'
        return lr

    # DIAS TRAB MES Moreproducts
    
    def _dias_trab_mes(self, ld):
        dias_trab_ant = 0
        rules = ld['rules']
        payslip = ld['payslip']
        contract = ld['contract']
        dias_trab_act = ld['DIAS_TRAB'] if rules.DIAS_TRAB else 0.0
        proll_period_c = payslip.payslip_period_id.name[0:7]
        if contract.slip_ids:
            for proll in contract.slip_ids:
                proll_period = str(proll.payslip_period_id.name)[0:7]
                if proll_period_c == proll_period and proll.tipo_nomina.code == 'Nomina' and proll.id != payslip.id:
                    for value in proll.line_ids:
                        if value.code == 'DIAS_TRAB':
                            dias_trab_ant += value.total
        lr[0] = dias_trab_ant + dias_trab_act
        return lr

    # Aportes pension
    
    def _appension(self, ld):
        res = False
        rules = ld['rules']
        contract = ld['contract']
        payslip = ld['payslip']
        base_ap = ld['IBCSS'] if rules.IBCSS else 0.0
        if base_ap > 0 and contract.type_id.name.upper().count('PENSION') < 1 and (
                payslip.payslip_period_id.schedule_pay == 'bi-monthly' and int(
                str(payslip.payslip_period_id.end_period)[
                8:10]) > 15 and payslip.tipo_nomina.code == 'Nomina') or payslip.payslip_period_id.schedule_pay != 'bi-monthly' or payslip.tipo_nomina.code == 'Liquidacion':
            res = True
        if res:
            proll_period_c = str(payslip.payslip_period_id.name)[0:7]
            # itera a traves de todas las quincenas
            for proll in contract.slip_ids:
                # periodo de la nomina actual
                proll_period = str(proll.payslip_period_id.name)[0:7]
                # compara cada periodo con el periodo de la nomina actual
                if proll_period_c == proll_period and proll.id != payslip.id:  # para que tome devengos antes de este periodo
                    # recorre las lineas de la nomina y obtiene los parametros
                    for value in proll.line_ids:
                        if value.code == 'APPENSION':
                            base_ap -= value.total

            lr[0] = round(base_ap, -3)
            lr[2] = 12
        else:
            lr[0] = 'na'
        return lr

    # Caja de compensacion familiar
    
    def _ccf(self, ld):
        rules = ld['rules']
        ibc = ld['IBCPF'] if rules.IBCPF else 0.0
        res = False
        if ibc > 0:
            res = True
        if res:
            contract = ld['contract']
            payslip = ld['payslip']
            proll_period_c = str(payslip.payslip_period_id.name)[0:7]
            # itera a traves de todas las quincenas
            for proll in contract.slip_ids:
                # periodo de la nomina actual
                proll_period = str(proll.payslip_period_id.name)[0:7]
                # compara cada periodo con el periodo de la nomina actual
                if proll_period_c == proll_period and proll.id != payslip.id:  # para que tome devengos antes de este periodo
                    # recorre las lineas de la nomina y obtiene los parametros
                    for value in proll.line_ids:
                        if value.code == 'CCF':
                            ibc -= value.total
            lr[2] = 4
            lr[0] = ibc
        else:
            lr[0] = 'na'
        return lr

    # Provision prima
    
    def _primaserv(self, ld):
        res = False
        rules = ld['rules']
        contract = ld['contract']
        base = ld['BASEPROV'] if rules.BASEPROV else 0.0
        if base > 0 and contract.type_id.clase != 'integral':
            res = True
        if res:
            payslip = ld['payslip']
            aux_trsp = ld['AUXTRANSP'] if rules.AUXTRANSP else 0.0
            month = str(payslip.payslip_period_id.start_period)[0:7]
            ajuste = 0
            if contract.slip_ids:
                for nomina in contract.slip_ids:
                    if str(nomina.payslip_period_id.start_period)[0:7] == month and nomina.id != payslip.id:
                        for regla in nomina.line_ids:
                            # if regla.code == 'AUXTRANSP':
                            #  aux_trsp+=regla.total
                            if regla.code == 'CESANTIAS':
                                ajuste += regla.total
            lr[0] = (base + aux_trsp) * 8.33 / 100 - ajuste
        else:
            lr[0] = 'na'
        return lr









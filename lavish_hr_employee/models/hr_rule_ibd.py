
from odoo import models, fields, api, _
from datetime import datetime, timedelta, date
from dateutil.relativedelta import relativedelta
import calendar
from collections import defaultdict
import re
from odoo.exceptions import UserError, ValidationError
from odoo.tools.safe_eval import safe_eval
from odoo.tools import format_date, formatLang, frozendict, date_utils, format_amount
from decimal import Decimal, getcontext, ROUND_HALF_UP
import logging

_logger = logging.getLogger(__name__)


class HrSalaryRule(models.Model):
    _inherit = 'hr.salary.rule'
    
    
    # ===============================================================
    # MÉTODOS DE INICIALIZACIÓN Y UTILIDADES
    # ===============================================================
    
    def _initialize_ibd_structure(self, localdict, calculate_for):
        """Inicializa la estructura de datos para el cálculo IBC"""
        return {
            'METADATA': {
                'fecha_calculo': datetime.now(),
                'smmlv': localdict['annual_parameters'].smmlv_monthly if localdict.get('annual_parameters') else 0,
                'tipo_calculo': calculate_for,
            },
            'CONCEPTOS': {
                'salariales': {},
                'no_salariales': {},
                'vacaciones': {},
                'ausencias': {},
                'incapacidades': {},
            },
            'CALCULOS': {},
            'VALIDACIONES': {
                'aplico_minimo': False,
                'aplico_maximo': False,
                'uso_ibc_anterior': False,
                'errores': [],
                'advertencias': [],
            },
            'MES_ANTERIOR': {},
            'NOVEDADES': [],
        }
    
    def _get_aprendizaje_response(self, _ibd):
        """Retorna respuesta para contratos de aprendizaje"""
        html = '<div class="alert alert-warning">Contrato de aprendizaje: no genera IBC</div>'
        return 0.0, 0.0, 100.0, 'IBC Aprendizaje', html, {
            'ibc_final': 0.0,
            'day_value': 0.0,
            'details': 'Contrato de aprendizaje: no genera IBC',
            '_ibd': _ibd,
        }
    
    def _calculate_worked_days(self, slip, localdict):
        """Calcula días y horas trabajadas"""
        result = {
            'total_days': 30.0,
            'total_hours': 0.0,
            'wage_type': 'monthly'
        }
        
        if slip:
            if slip.struct_type_id:
                result['wage_type'] = slip.struct_type_id.wage_type or 'monthly'
            
            work100_lines = slip.worked_days_line_ids.filtered(lambda x: x.code == 'WORK100')
            for wd in work100_lines:
                result['total_days'] = float(wd.number_of_days or 0)
                if result['wage_type'] == 'hourly':
                    result['total_hours'] = float(wd.number_of_hours or 0)
        
        # Agregar días de current_month
        if localdict["current_month"]:
            payslip_ids = list(localdict["current_month"])
            if payslip_ids:
                payslips = self.env['hr.payslip'].browse(payslip_ids)
                for ps in payslips:
                    work100_lines = ps.worked_days_line_ids.filtered(lambda x: x.code == 'WORK100')
                    for wd in work100_lines:
                        days_to_add = float(wd.number_of_days or 0)
                        if days_to_add > 0:
                            result['total_days'] += days_to_add
                        if result['wage_type'] == 'hourly':
                            result['total_hours'] += float(wd.number_of_hours or 0)
        
        return result
    
    # ===============================================================
    # MÉTODOS DE RECOPILACIÓN DE DATOS
    # ===============================================================
    
    def _collect_all_absences_unified(self, slip, contract, localdict):
        """
        Recopila todas las ausencias de manera unificada.
        Similar a _calculate_absences pero más completo.
        
        Returns:
            dict: {composite_key: absence_data}
        """
        temp_dict = {}
        
        slip_ids = []
        if slip:
            slip_ids.append(slip.id)
        if localdict.get("current_month"):
            slip_ids.extend(list(localdict["current_month"]))
        
        if not slip_ids:
            return {}
        domain = [
            ('payslip_id', 'in', slip_ids),
            ('state', 'in', ['validated', 'paid']),
            '|',
            ('contract_id', '=', contract.id),
            ('contract_id.employee_id', '=', contract.employee_id.id)
        ]
        
        leave_lines = self.env['hr.leave.line'].search(domain, order='date, id')
        
        # Agrupar por (leave_id, rule_id)
        for ll in leave_lines:
            if not ll.leave_id or not ll.rule_id:
                continue
            
            # Excluir reglas especiales
            if ll.rule_id.code in {"AUX001", "AUX00C", "SSOCIAL003", "SSOCIAL004", "IBD", "IBC", "IBF"}:
                continue
            
            composite_key = (ll.leave_id.id, ll.rule_id.id)
            
            if composite_key not in temp_dict:
                leave_type = ll.leave_id.holiday_status_id
                start_date = ll.leave_id.date_from
                end_date = ll.leave_id.date_to
                
                temp_dict[composite_key] = {
                    'name': ll.leave_id.name,
                    'rule_name': ll.rule_id.name,
                    'total_days': 0,
                    'total_amount': 0,
                    'leave_type': leave_type,
                    'leave_type_name': leave_type.name if leave_type else 'N/A',
                    'date_from': start_date.date() if start_date else ll.date,
                    'date_to': end_date.date() if end_date else ll.date,
                    'rule_id': ll.rule_id,
                    'rule_code': ll.rule_id.code,
                    'leave_id': ll.leave_id,
                    'novelty': leave_type.novelty if leave_type else None,
                    'is_unpaid': bool(leave_type.unpaid_absences) if leave_type else False,
                    'liquidar_con_base': bool(ll.rule_id.liquidar_con_base),
                    'base_seguridad_social': bool(ll.rule_id.base_seguridad_social),
                    'category_code': self._get_category_code(ll.rule_id),
                    'sequence': int(ll.sequence or 1),
                    'payslip_ids': [],
                    'lines': [],
                    'cross_month': False,
                    'individual_entries': [],
                    'entity_id': ll.leave_id.entity.id if ll.leave_id.entity else False,
                }
            
            # Acumular datos
            data = temp_dict[composite_key]
            days = float(ll.days_payslip or ll.days_assigned or 0)
            amount = float(ll.amount or 0)
            
            data['total_days'] += days
            data['total_amount'] += amount
            
            if ll.payslip_id.id not in data['payslip_ids']:
                data['payslip_ids'].append(ll.payslip_id.id)
            
            data['lines'].append(ll)
            
            data['individual_entries'].append({
                'date': ll.date,
                'days': days,
                'amount': amount,
                'payslip_id': ll.payslip_id.id,
                'payslip_name': ll.payslip_id.name,
                'days_work': ll.days_work,
                'days_holiday': ll.days_holiday,
                'days_31': ll.days_31,
                'days_holiday_31': ll.days_holiday_31,
            })
            if ll.date:
                data['date_from'] = min(data['date_from'], ll.date)
                data['date_to'] = max(data['date_to'], ll.date)
            
            if slip and data['date_from'] < slip.date_from:
                data['cross_month'] = True
        
        absence_dict = {}
        for (leave_id, rule_id), data in temp_dict.items():
            composite_key = f"{leave_id}_{rule_id}"
            data['individual_entries'].sort(key=lambda x: x['date'])
            absence_dict[composite_key] = data
        
        return absence_dict
    
    def _collect_all_normal_concepts(self, slip, contract, localdict, absence_dict):
        """
        Recopila todos los conceptos normales (no ausencias).
        Procesa tanto current_month como rules_multi.
        
        Returns:
            dict: {rule_code: concept_data}
        """
        normal_concepts = {}
        
        absence_rule_codes = set()
        absence_slip_rule_combinations = set()
        
        for data in absence_dict.values():
            absence_rule_codes.add(data['rule_code'])
            for slip_id in data['payslip_ids']:
                absence_slip_rule_combinations.add((slip_id, data['rule_code']))
        
        if localdict["current_month"]:
            current_slip_ids = list(localdict["current_month"])
            
            # Buscar todas las líneas
            lines = self.env['hr.payslip.line'].search([
                ('slip_id', 'in', current_slip_ids),
                ('contract_id', '=', contract.id),
                ('salary_rule_id.code', 'not in', ['AUX001', 'AUX00C', 'IBD',]),
                ('amount', '!=', 0)
            ], order='slip_id, sequence')
            
            for line in lines:
                rule = line.salary_rule_id
                if not rule:
                    continue
                if rule.is_leave or line.leave_id:
                    continue
                if rule.code not in normal_concepts:
                    normal_concepts[rule.code] = {
                        'rule_id': rule,
                        'rule_name': rule.name,
                        'rule_code': rule.code,
                        'category_code': self._get_category_code(rule),
                        'total_amount': 0,
                        'total_quantity': 0,
                        'base_seguridad_social': bool(rule.base_seguridad_social),
                        'dev_or_ded': rule.dev_or_ded,
                        'sequence': rule.sequence,
                        'lines': [],
                        'payslip_ids': [],
                        'entries_by_date': [],
                    }
                amount = float(line.total or 0)
                quantity = float(line.quantity or 0)
                normal_concepts[rule.code]['total_amount'] += amount
                normal_concepts[rule.code]['total_quantity'] += quantity
                normal_concepts[rule.code]['lines'].append(line)
                
                if line.slip_id.id not in normal_concepts[rule.code]['payslip_ids']:
                    normal_concepts[rule.code]['payslip_ids'].append(line.slip_id.id)
                
                normal_concepts[rule.code]['entries_by_date'].append({
                    'date': line.slip_id.date_from,
                    'date_to': line.slip_id.date_to,
                    'amount': amount,
                    'quantity': quantity,
                    'payslip_id': line.slip_id.id,
                    'payslip_name': line.slip_id.name,
                    'source': 'current_month'
                })
        
        if localdict.get('rules_multi'):
            for code_key, rule_data in localdict['rules_multi'].items():
                if code_key in ['AUX001', 'AUX00C', 'IBD',]:
                    continue
                current_info = rule_data.get('current')
                rule_obj = current_info.get('object')
                if not rule_obj:
                    continue
                is_leave = bool(rule_obj.is_leave)
                if is_leave:
                    continue
               
                amount = float(current_info.get('total', 0))
                quantity = float(current_info.get('quantity', 0))
                payslip_id = current_info.get('payslip_id')
                
                if amount == 0:
                    continue
                
                if code_key not in normal_concepts:
                    normal_concepts[code_key] = {
                        'rule_id': rule_obj,
                        'rule_name': rule_obj.name or code_key,
                        'rule_code': code_key,
                        'category_code': current_info.get('category', '') or self._get_category_code(rule_obj),
                        'total_amount': 0,
                        'total_quantity': 0,
                        'base_seguridad_social': bool(rule_obj.base_seguridad_social) if rule_obj else False,
                        'dev_or_ded': getattr(rule_obj, 'dev_or_ded', 'devengado') if rule_obj else 'devengado',
                        'sequence': rule_obj.sequence if rule_obj else 999,
                        'lines': [],
                        'payslip_ids': [],
                        'entries_by_date': [],
                    }
                normal_concepts[code_key]['total_amount'] += amount
                normal_concepts[code_key]['total_quantity'] += quantity
                
                if payslip_id and payslip_id not in normal_concepts[code_key]['payslip_ids']:
                    normal_concepts[code_key]['payslip_ids'].append(payslip_id)
                
                date_from = slip.date_from if slip else datetime.now().date()
                date_to = slip.date_to if slip else datetime.now().date()
                
                normal_concepts[code_key]['entries_by_date'].append({
                    'date': date_from,
                    'date_to': date_to,
                    'amount': amount,
                    'quantity': quantity,
                    'payslip_id': payslip_id or 0,
                    'payslip_name': f"Rules Multi - {code_key}",
                    'source': 'rules_multi',
                    'log': current_info.get('log', '')
                })
        
        for concept in normal_concepts.values():
            concept['entries_by_date'].sort(key=lambda x: x['date'])
        
        return normal_concepts
    
    # ===============================================================
    # MÉTODOS DE PROCESAMIENTO
    # ===============================================================
    
    def _process_all_data(self, all_absences, all_concepts, daily_rate, slip, _ibd):
        """
        Procesa todos los datos recopilados y genera la tabla de conceptos.
        
        Returns:
            dict: Resultados del procesamiento
        """
        result = {
            'totales': {
                'base_salarial': 0.0,
                'base_no_salarial': 0.0,
                'total_vacaciones': 0.0,
                'vac_mes_actual': 0.0,
                'vac_mes_anterior': 0.0,
                'vacaciones_vdi_current': 0.0,
                'vacaciones_vdi_previous': 0.0,
                'vacaciones_vco_current': 0.0,
                'vacaciones_vco_previous': 0.0,
                'vac_actual_para_40': 0.0,
                'vac_anterior_para_40': 0.0,
                'excedente_40': 0.0,
            },
            'conceptos_tabla': [],
            'ausencias_no_remuneradas_days': 0.0,
            'force_ibc': False
        }
        
        for code, concept in all_concepts.items():
            amount = concept['total_amount']
            
            if amount == 0:
                continue
            if self._is_non_salary(concept['rule_id'], concept['category_code']):
                tipo = 'NO SALARIAL'
                result['totales']['base_no_salarial'] += amount
            elif self._is_salary_base(concept['rule_id'], concept['category_code']):
                tipo = 'SALARIAL'
                result['totales']['base_salarial'] += amount
            else:
                continue 
            
            fechas_info = self._format_dates_info(concept['entries_by_date'])
            
            result['conceptos_tabla'].append({
                'tipo': tipo,
                'nombre': concept['rule_name'],
                'codigo': concept['rule_code'],
                'valor_original': amount,
                'valor_ibc': amount,
                'cantidad': concept['total_quantity'],
                'observaciones': fechas_info['observaciones'],
                'fecha': fechas_info['fecha_str'],
                'detalle_fechas': concept['entries_by_date'],
                'sequence': concept['sequence']
            })
            
            tipo_concepto = 'no_salariales' if tipo == 'NO SALARIAL' else 'salariales'
            self._add_concepto(_ibd, tipo_concepto, code, {
                'nombre': concept['rule_name'],
                'cantidad': concept['total_quantity'],
                'valor_original': amount,
                'valor_calculado': amount,
                'categoria': concept['category_code'],
                'es_base': True,
                'fechas': concept['entries_by_date']
            })
        # 2. Procesar ausencias
        for key, absence in all_absences.items():
            processed = self._process_single_absence(absence, daily_rate, slip, _ibd)
            
            # Actualizar totales
            result['totales']['base_salarial'] += processed.get('base_salarial', 0)
            result['ausencias_no_remuneradas_days'] += processed.get('dias_no_remunerados', 0)
            
            if processed.get('force_ibc'):
                result['force_ibc'] = True
            
            if processed.get('tipo_vacacion'):
                self._update_vacation_totals(result['totales'], processed)
            
            if processed.get('tabla_entry'):
                fechas_info = self._format_dates_info(absence['individual_entries'])
                processed['tabla_entry']['fecha'] = fechas_info['fecha_str']
                processed['tabla_entry']['detalle_fechas'] = absence['individual_entries']
                processed['tabla_entry']['codigo'] = absence['rule_code']
                processed['tabla_entry']['sequence'] = absence.get('sequence', 999)
                
                result['conceptos_tabla'].append(processed['tabla_entry'])
            
            if processed.get('novedad'):
                _ibd['NOVEDADES'].append(processed['novedad'])
        
        # 3. Ordenar tabla de conceptos por tipo y secuencia
        result['conceptos_tabla'].sort(key=lambda x: (
            self._get_tipo_orden(x['tipo']),
            x.get('sequence', 999),
            x['nombre']
        ))
        
        return result
    
    def _process_single_absence(self, absence_data, daily_rate, slip, _ibd):
        """Procesa una ausencia individual"""
        result = {
            'base_salarial': 0,
            'dias_no_remunerados': 0,
            'force_ibc': False,
            'tabla_entry': None,
        }
        
        rule = absence_data['rule_id']
        amount = absence_data['total_amount']
        days = absence_data['total_days']
        novelty = absence_data['novelty']
        is_unpaid = absence_data['is_unpaid']
        cross_month = absence_data['cross_month']
        start_date = absence_data['date_from']
        
        nombre = absence_data['rule_name']
        valor_original = amount
        valor_ibc = amount
        tipo = 'AUSENCIA'
        observaciones = f'{days:.1f} días'
        
        # Crear novedad base
        novedad = {
            'fecha': start_date,
            'concepto': nombre,
            'dias': days,
            'valor_original': valor_original,
            'cruza_mes': cross_month,
            'entity_id': absence_data.get('entity_id'),
        }
        
        if is_unpaid:
            # Ausencia no remunerada
            result['dias_no_remunerados'] = days
            valor_ibc = 0
            tipo = 'AUSENCIA NO REMUNERADA'
            observaciones = f'{days:.1f} días - No hace base'
            novedad.update({
                'tipo': 'AUSENCIA NO REMUNERADA',
                'valor_recalculado': 0,
            })
            
        elif novelty in ['vdi', 'vco']:
            # Procesar vacación
            vac_data = self._process_vacation(
                rule, amount, days, absence_data['leave_type'],
                start_date, cross_month, novelty, daily_rate, slip
            )
            
            result['tipo_vacacion'] = novelty
            result['vacacion_data'] = vac_data
            tipo = vac_data['tipo']
            valor_ibc = vac_data['valor_ibc']
            observaciones = vac_data['observaciones']
            
            novedad.update({
                'tipo': tipo,
                'dias': vac_data['dias_efectivos'],
                'valor_recalculado': valor_ibc,
                'hace_base': vac_data['hace_base'],
            })
            
            # Agregar a conceptos de vacaciones
            self._add_concepto(_ibd, 'vacaciones', 
                f"{novelty.upper()}_{absence_data['leave_id'].id}", {
                'nombre': nombre,
                'cantidad': vac_data['dias_efectivos'],
                'valor_original': amount,
                'valor_calculado': valor_ibc,
                'dias': vac_data['dias_efectivos'],
                'categoria': absence_data['category_code'],
                'es_base': vac_data['hace_base'],
                'cruza_mes': cross_month,
                'fecha_inicio': start_date,
                'observaciones': observaciones,
            })
            
        elif absence_data['liquidar_con_base'] and daily_rate > 0:
            result['force_ibc'] = True
            
            if novelty in ['ige', 'irl', 'lma']:
                tipo = 'INCAPACIDAD'
                observaciones = f'Incapacidad {novelty.upper()} - {days:.1f} días'
                result['base_salarial'] = valor_ibc
                
                novedad.update({
                    'tipo': 'INCAPACIDAD',
                    'subtipo': novelty.upper(),
                    'valor_recalculado': valor_ibc,
                })
                
                self._add_concepto(_ibd, 'incapacidades', 
                    f"INC_{absence_data['leave_id'].id}", {
                    'nombre': nombre,
                    'cantidad': days,
                    'valor_original': amount,
                    'valor_calculado': valor_ibc,
                    'dias': days,
                    'categoria': absence_data['category_code'],
                    'es_base': True,
                    'cruza_mes': cross_month,
                    'fecha_inicio': start_date,
                    'observaciones': f'Incapacidad {novelty.upper()}',
                })
                
            else:
                sequence_days = absence_data['sequence']
                factor = 1.0
                
                if absence_data['leave_type']:
                    try:
                        factor, _ = absence_data['leave_type'].get_rate_concept_id(sequence_days)
                    except:
                        factor = 1.0
                
                valor_ibc = days * daily_rate * factor
                tipo = 'AUSENCIA - IBC ANTERIOR'
                observaciones = f'{days:.1f} días × ${daily_rate:,.0f}'.replace(',', '.')
                if factor != 1.0:
                    observaciones += f' × {int(factor*100)}%'
                
                result['base_salarial'] = valor_ibc
                
                novedad.update({
                    'tipo': 'AUSENCIA CON IBC',
                    'valor_recalculado': valor_ibc,
                    'factor': factor,
                })
                
                # Agregar a conceptos
                self._add_concepto(_ibd, 'ausencias', 
                    f"AUS_IBC_{absence_data['leave_id'].id}", {
                    'nombre': f'{nombre} (IBC anterior)',
                    'cantidad': days,
                    'valor_original': amount,
                    'valor_calculado': valor_ibc,
                    'dias': days,
                    'categoria': absence_data['category_code'],
                    'es_base': True,
                    'cruza_mes': cross_month,
                    'fecha_inicio': start_date,
                    'observaciones': f'Liquidado con IBC anterior{" al " + str(int(factor*100)) + "%" if factor != 1.0 else ""}',
                })
                
        else:
            if absence_data['category_code'] == 'BASIC' and cross_month:
                valor_ibc = days * daily_rate
                tipo = 'BASIC - CRUZA MES'
                observaciones = f'{days:.1f} días × ${daily_rate:,.0f}'.replace(',', '.')
                result['base_salarial'] = valor_ibc
            else:
                result['base_salarial'] = amount
            
            novedad.update({
                'tipo': tipo,
                'valor_recalculado': valor_ibc,
            })
            
            # Agregar a conceptos si hace base
            if result['base_salarial'] > 0:
                self._add_concepto(_ibd, 'ausencias', 
                    f"AUS_{absence_data['leave_id'].id}", {
                    'nombre': nombre,
                    'cantidad': days,
                    'valor_original': amount,
                    'valor_calculado': valor_ibc,
                    'dias': days,
                    'categoria': absence_data['category_code'],
                    'es_base': True,
                    'cruza_mes': cross_month,
                    'fecha_inicio': start_date,
                    'observaciones': observaciones,
                })
        
        # Crear entrada para tabla
        result['tabla_entry'] = {
            'tipo': tipo,
            'nombre': nombre,
            'valor_original': valor_original,
            'valor_ibc': valor_ibc,
            'cantidad': days,
            'observaciones': observaciones,
        }
        
        result['novedad'] = novedad
        
        return result
    
    def _process_vacation(self, rule, amount, days, leave_type, start_date, 
                         cross_month, novelty, daily_rate, slip):
        hace_base = True
        if novelty == 'vco':
            hace_base = bool(rule.base_seguridad_social)
        
        dias_efectivos = days
        
        # Calcular días efectivos si cruza mes
        if cross_month and start_date and slip:
            fecha_fin_vacacion = start_date + relativedelta(days=int(days) - 1)
            
            if fecha_fin_vacacion < slip.date_from:
                dias_efectivos = 0
            elif start_date < slip.date_from:
                if fecha_fin_vacacion <= slip.date_to:
                    dias_efectivos = (fecha_fin_vacacion - slip.date_from).days + 1
                else:
                    dias_efectivos = (slip.date_to - slip.date_from).days + 1
        
        valor_ibc = dias_efectivos * daily_rate if hace_base else 0
        
        tipo = 'VACACIONES DISFRUTADAS' if novelty == 'vdi' else 'VACACIONES COMPENSADAS'
        observaciones = f'{dias_efectivos:.1f} días'
        
        if cross_month and dias_efectivos < days:
            observaciones += f' (de {days:.1f} totales)'
        if novelty == "vco" and not hace_base:
            observaciones += ' - NO hace base'
        
        return {
            'tipo': tipo,
            'valor_original': amount,
            'valor_ibc': valor_ibc,
            'observaciones': observaciones,
            'hace_base': hace_base,
            'dias_efectivos': dias_efectivos,
            'cruza_mes': cross_month
        }
    
    def _update_vacation_totals(self, totales, processed):
        """Actualiza totales de vacaciones"""
        vac_data = processed['vacacion_data']
        novelty = processed['tipo_vacacion']
        
        totales['total_vacaciones'] += vac_data['valor_original']
        
        if novelty == 'vdi':
            if vac_data['cruza_mes']:
                totales['vacaciones_vdi_previous'] += vac_data['valor_ibc']
                totales['vac_mes_anterior'] += vac_data['valor_original']
                if vac_data['hace_base']:
                    totales['vac_anterior_para_40'] += vac_data['valor_ibc']
            else:
                totales['vacaciones_vdi_current'] += vac_data['valor_ibc']
                totales['vac_mes_actual'] += vac_data['valor_original']
                if vac_data['hace_base']:
                    totales['vac_actual_para_40'] += vac_data['valor_ibc']
        else:  # vco
            if vac_data['cruza_mes']:
                totales['vacaciones_vco_previous'] += vac_data['valor_ibc'] if vac_data['hace_base'] else 0
                totales['vac_mes_anterior'] += vac_data['valor_original']
                if vac_data['hace_base']:
                    totales['vac_anterior_para_40'] += vac_data['valor_ibc']
            else:
                totales['vacaciones_vco_current'] += vac_data['valor_ibc'] if vac_data['hace_base'] else 0
                totales['vac_mes_actual'] += vac_data['valor_original']
                if vac_data['hace_base']:
                    totales['vac_actual_para_40'] += vac_data['valor_ibc']
    
    
    def _calculate_prev_month_ibc_unified(self, contract, localdict, slip):
        """Calcula el IBC del mes anterior de forma unificada"""
        prev_data = {
            'ibc': 0.0,
            'dias': 30.0,
            'tarifa_diaria': 0.0,
            'fuente': 'No disponible',
            'fecha_referencia': '',
            'wage_type': 'monthly',
            'valores_encontrados': [],
            'dias_ausencias': 0.0,
        }
        
        if not slip:
            return prev_data
        
        mes_previo = slip.date_from - relativedelta(months=1)
        prev_data['fecha_referencia'] = mes_previo.strftime('%Y-%m')
        
        if slip.struct_type_id:
            prev_data['wage_type'] = slip.struct_type_id.wage_type or 'monthly'
        

        ss = self.env['hr.payroll.social.security'].search([
            ('year', '=', mes_previo.year),
            ('month', '=', str(mes_previo.month)),
            ('state', 'in', ['done', 'accounting'])
        ], limit=1)
        
        if ss:
            ss_line = ss.executing_social_security_ids.filtered(
                lambda x: x.contract_id.id == contract.id
            )
            for linea in ss_line:
                valor_base = float(linea.nValorBaseSalud or 0)
                if valor_base > 0:
                    dias_ss = sum([
                        float(linea.nDiasLiquidados or 0),
                        float(linea.nDiasIncapacidadEPS or 0),
                        float(linea.nDiasLicenciaRenumerada or 0),
                        float(linea.nDiasMaternidad or 0),
                        float(linea.nDiasVacaciones or 0),
                        float(linea.nDiasIncapacidadARP or 0)
                    ])
                    
                    prev_data['valores_encontrados'].append({
                        'valor': valor_base,
                        'dias': dias_ss if dias_ss > 0 else 30,
                        'fuente': 'Seguridad Social'
                    })        
        prev_slip_ids = list(localdict['before_month'])        
        if not prev_slip_ids and not prev_data['valores_encontrados']:
            salario = float(contract.wage or 0)
            smmlv = localdict['annual_parameters'].smmlv_monthly
            prev_data['ibc'] = salario if salario > 0 else smmlv
            prev_data['fuente'] = 'Salario contractual'
            prev_data['tarifa_diaria'] = prev_data['ibc'] / 30.0
            return prev_data
        if not prev_data['valores_encontrados']:        
            # 1. Buscar IBD directo
            ibd_lines = self.env['hr.payslip.line'].search([
                ('slip_id', 'in', prev_slip_ids),
                ('salary_rule_id.code', '=', 'IBD'),
                ('contract_id', '=', contract.id)
            ])

            
            for ibd in ibd_lines:
                ibc_amount = float(ibd.total or 0)
                if ibc_amount > 0:
                    prev_data['valores_encontrados'].append({
                        'valor': ibc_amount,
                        'dias': float(ibd.quantity or 30),
                        'fuente': f'IBD nómina {ibd.slip_id.name}'
                    })
            

                prev_localdict = {'before_month': prev_slip_ids}
                
                prev_absences = self._collect_all_absences_unified(None, contract, prev_localdict)
                
                prev_concepts = self._collect_all_normal_concepts(None, contract, prev_localdict, prev_absences)
                
                base_salarial = 0.0
                base_no_salarial = 0.0
                dias_ausencias = 0.0
                
                for concept in prev_concepts.values():
                    if self._is_salary_base(concept['rule_id'], concept['category_code']):
                        base_salarial += concept['total_amount']
                    elif self._is_non_salary(concept['rule_id'], concept['category_code']):
                        base_no_salarial += concept['total_amount']
                
                for absence in prev_absences.values():
                    dias_ausencias += absence['total_days']
                    if absence['novelty'] in ['ige', 'irl', 'lma']:
                        base_salarial += absence['total_amount']
                
                prev_data['dias_ausencias'] = dias_ausencias
                
                if base_salarial > 0:
                    tope_40 = (base_salarial + base_no_salarial) * 0.4
                    excedente = max(0, base_no_salarial - tope_40)
                    ibc_calculado = base_salarial + excedente
                    
                    prev_data['valores_encontrados'].append({
                        'valor': ibc_calculado,
                        'dias': 30,
                        'fuente': 'Calculado de conceptos'
                    })
        if prev_data['valores_encontrados']:
            mejor = max(prev_data['valores_encontrados'], key=lambda x: x['valor'])
            prev_data['ibc'] = mejor['valor']
            prev_data['dias'] = mejor['dias']
            prev_data['fuente'] = mejor['fuente']
            if len(prev_data['valores_encontrados']) > 1:
                prev_data['fuente'] = f"Mayor IBC de {len(prev_data['valores_encontrados'])} fuentes"
        else:
            salario = float(contract.wage or 0)
            smmlv = localdict['annual_parameters'].smmlv_monthly if localdict.get('annual_parameters') else 0
            prev_data['ibc'] = salario if salario > 0 else smmlv
            prev_data['fuente'] = 'Salario contractual'            
        
        # 3. Buscar días trabajados
        work_days = 0.0
        for slip_id in prev_slip_ids:
            payslip = self.env['hr.payslip'].browse(slip_id)
            work100_lines = payslip.worked_days_line_ids.filtered(lambda x: x.code == 'WORK100')
            for wd in work100_lines:
                work_days += float(wd.number_of_days or 0)
        
        if work_days > 0:
            prev_data['dias'] = work_days
        
        prev_data['tarifa_diaria'] = prev_data['ibc'] / prev_data['dias'] if prev_data['dias'] > 0 else 0
        prev_data['validaciones'] = {'uso_ibc_anterior': prev_data['ibc'] > 0}
        
        return prev_data
    
    # ===============================================================
    # MÉTODOS DE CÁLCULO FINAL
    # ===============================================================
    
    def _calculate_final_ibc(self, processing_result, annual_parameters, calculate_for, localdict, _ibd):
        """Calcula el IBC final aplicando reglas del 40% y topes"""
        totales = processing_result['totales']
        
        # Valores base
        ibc_base_puro = totales['base_salarial']
        
        # IBC para cálculo del 40%
        ibc_40 = totales['base_salarial'] + totales['vac_actual_para_40'] - totales['vac_anterior_para_40']
        
        # Remuneración total para 40%
        remuneracion_para_40 = ibc_40 + totales['base_no_salarial']
        
        # Aplicar 40%
        porcentaje_40 = annual_parameters.value_porc_statute_1395/100 if annual_parameters else 0.4
        tope_40 = remuneracion_para_40 * porcentaje_40
        excedente = max(0.0, totales['base_no_salarial'] - tope_40)
        
        # IBC base final
        ibc_base_final = totales['base_salarial'] + excedente
        ibc_sin_topes = ibc_base_final
        
        # Lógica especial para FONDOS
        fondos_prev_month = False
        vacaciones_a_incluir = 0.0
        
        if calculate_for == 'FONDOS':
            # Verificar si ya se calcularon fondos el mes anterior
            if localdict.get('before_month'):
                prev_slip_ids = list(localdict['before_month'])
                fondos_previos = self.env['hr.payslip.line'].search([
                    ('slip_id', 'in', prev_slip_ids),
                    ('salary_rule_id.code', '=', self.code),
                    ('contract_id', '=', localdict['contract'].id),
                    ('amount', '!=', 0)
                ], limit=1)
                
                if fondos_previos:
                    fondos_prev_month = True
                    _ibd['VALIDACIONES']['fondos_mes_anterior'] = True
            
            # Incluir vacaciones según corresponda
            for codigo, concepto in _ibd['CONCEPTOS']['vacaciones'].items():
                if concepto.get('es_base', False):
                    if not concepto.get('cruza_mes', False):
                        vacaciones_a_incluir += concepto['valor_calculado']
                    elif not fondos_prev_month:
                        vacaciones_a_incluir += concepto['valor_calculado']
            
            ibc_sin_topes = ibc_base_final + vacaciones_a_incluir
        
        # Aplicar topes
        smmlv = annual_parameters.smmlv_monthly if annual_parameters else 0
        ibc_max = 25.0 * smmlv
        ibc_final = min(ibc_sin_topes, ibc_max)
        
        # Actualizar validaciones
        _ibd['VALIDACIONES']['aplico_maximo'] = ibc_sin_topes > ibc_max
        _ibd['VALIDACIONES']['incluyo_vacaciones'] = vacaciones_a_incluir > 0
        
        return {
            'ibc_base_puro': ibc_base_puro,
            'ibc_40': ibc_40,
            'remuneracion_para_40': remuneracion_para_40,
            'tope_40': tope_40,
            'excedente_40': excedente,
            'ibc_base_final': ibc_base_final,
            'ibc_sin_topes': ibc_sin_topes,
            'ibc_final': ibc_final,
            'vacaciones_a_incluir': vacaciones_a_incluir,
            'fondos_prev_month': fondos_prev_month,
            'aplico_maximo': ibc_sin_topes > ibc_max,
        }
    
    def _calculate_day_value(self, ibc_final, dias_ibc, total_hours, wage_type, annual_parameters):
        """Calcula el valor día según tipo de salario"""
        if wage_type == 'hourly' and total_hours > 0:
            hours_per_day = float(annual_parameters.hours_per_day or 8) if annual_parameters else 8
            day_value = (ibc_final / total_hours) * hours_per_day
            return {
                'valor_dia': day_value,
                'tipo_calculo': 'hourly',
                'horas_trabajadas': total_hours,
                'horas_por_dia': hours_per_day
            }
        else:
            day_value = ibc_final / dias_ibc if dias_ibc > 0 else 0
            return {
                'valor_dia': day_value,
                'tipo_calculo': 'monthly'
            }
    
    # ===============================================================
    # MÉTODOS DE UTILIDAD
    # ===============================================================
    
    def _get_category_code(self, rule):
        """Obtiene código de categoría"""
        if rule.category_id:
            if rule.category_id.code:
                return rule.category_id.code
            elif rule.category_id.parent_id and rule.category_id.parent_id.code:
                return rule.category_id.parent_id.code
        return ''
    
    def _is_salary_base(self, rule, category_code=None):
        if category_code is None:
            category_code = self._get_category_code(rule)
        
        if rule and rule.base_seguridad_social:
            return True
        
        salary_categories = ['BASIC', 'HEYREC', 'DEV_SALARIAL']
        
        if rule and rule.category_id:
            if rule.category_id.code and rule.category_id.code in salary_categories:
                return True
            elif rule.category_id.parent_id and rule.category_id.parent_id.code and rule.category_id.parent_id.code in salary_categories:
                return True
        return category_code in salary_categories
    
    def _is_non_salary(self, rule, category_code=None):
        if category_code is None:
            category_code = self._get_category_code(rule)
        if rule and rule.category_id:
            if rule.category_id.code and rule.category_id.code == 'DEV_NO_SALARIAL':
                return True
            elif rule.category_id.parent_id and rule.category_id.parent_id.code and rule.category_id.parent_id.code == 'DEV_NO_SALARIAL':
                return True
        return category_code == 'DEV_NO_SALARIAL'
    
    def _add_concepto(self, _ibd, tipo, codigo, data):
        """Agrega concepto a estructura _ibd"""
        if tipo in _ibd['CONCEPTOS']:
            _ibd['CONCEPTOS'][tipo][codigo] = data
    
    def _format_dates_info(self, entries):
        """Formatea información de fechas para mostrar"""
        if not entries:
            return {'fecha_str': '', 'observaciones': ''}
        
        if len(entries) == 1:
            entry = entries[0]
            fecha_str = entry['date'].strftime('%d/%m/%Y') if entry['date'] else ''
            return {'fecha_str': fecha_str, 'observaciones': ''}
        
        # Múltiples entradas
        fechas_unicas = set()
        for entry in entries:
            if entry['date']:
                fechas_unicas.add(entry['date'].strftime('%d/%m'))
        
        fecha_str = ', '.join(sorted(fechas_unicas))
        observaciones = f'{len(entries)} registros'
        
        return {'fecha_str': fecha_str, 'observaciones': observaciones}
    
    def _get_tipo_orden(self, tipo):
        """Retorna orden para ordenar tipos de conceptos"""
        orden = {
            'BASICO': 0,
            'SALARIAL': 1,
            'NO SALARIAL': 2,
            'VACACIONES DISFRUTADAS': 3,
            'VACACIONES COMPENSADAS': 4,
            'INCAPACIDAD': 5,
            'AUSENCIA': 6,
            'AUSENCIA - IBC ANTERIOR': 7,
            'AUSENCIA NO REMUNERADA': 8,
            'BASIC - CRUZA MES': 9,
        }
        return orden.get(tipo, 99)
    
    # ===============================================================
    # GENERACIÓN DE HTML
    # ===============================================================
    
    def _generate_complete_html(self, _ibd, conceptos_tabla, slip, calculate_for):
        date_from = slip.date_from if slip else fields.Date.today()
        date_to = slip.date_to if slip else fields.Date.today()
        
        if slip and slip.contract_id:
            contract_start = slip.contract_id.date_start
            if contract_start and contract_start > date_from.replace(day=1):
                period_start = contract_start.strftime("%d/%m/%Y")
            else:
                period_start = date_from.replace(day=1).strftime("%d/%m/%Y")
        else:
            period_start = date_from.strftime("%d/%m/%Y")
        
        period_end = date_to.strftime("%d/%m/%Y")
        
        # Obtener valores
        dias_trabajados = _ibd["CALCULOS"].get("dias_trabajados", 0)
        dias_ibc = _ibd["CALCULOS"].get("dias_ibc", 0)
        ausencias_no_rem = _ibd['CALCULOS'].get('ausencias_no_remuneradas_dias', 0)
        
        ibc_anterior = _ibd['MES_ANTERIOR'].get("ibc", 0)
        dias_anterior = _ibd['MES_ANTERIOR'].get("dias", 30)
        tarifa_diaria_anterior = _ibd['MES_ANTERIOR'].get("tarifa_diaria", 0)
        fuente_anterior = _ibd['MES_ANTERIOR'].get("fuente", "Salario contractual")
        
        novedades = _ibd.get('NOVEDADES', [])
        
        # Cálculos
        base_salarial = _ibd['CALCULOS'].get("base_salarial", 0)
        ibc_40 = _ibd['CALCULOS'].get("ibc_40", 0)
        no_salarial = _ibd['CALCULOS'].get("base_no_salarial", 0)
        tope_40 = _ibd['CALCULOS'].get("tope_40", 0)
        excedente_40 = _ibd['CALCULOS'].get("excedente_40", 0)
        ibc_base_final = _ibd['CALCULOS'].get("ibc_base_final", 0)
        
        ibc_final = _ibd["CALCULOS"].get("ibc_final", 0)
        valor_dia = _ibd["CALCULOS"].get("valor_dia", 0)
        aplico_maximo = _ibd['CALCULOS'].get('aplico_maximo', False)
        
        ibc_base_puro = _ibd['CALCULOS'].get("ibc_base_puro", 0)
        ibc_sin_topes = _ibd['CALCULOS'].get("ibc_sin_topes", 0)
        
        # Iniciar HTML
        html = f'''
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 1200px; margin: 20px auto; background: white; border-radius: 12px; box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08); overflow: hidden;">
            
            <!-- Header Principal -->
            <div style="background: linear-gradient(135deg, #7CB342 0%, #9CCC65 100%); color: white; padding: 25px 30px; position: relative;">
                <h2 style="margin: 0; font-weight: 600; font-size: 1.5rem;">
                    <i class="fa fa-calculator"></i> Cálculo de IBC - {calculate_for}
                </h2>
                <div style="opacity: 0.9; font-size: 0.9rem; margin-top: 5px;">
                    Periodo: {period_start} - {period_end}
                </div>
            </div>

            <!-- Información del Periodo -->
            <div style="background: #F1F8E9; border-radius: 10px; padding: 20px; margin: 15px; border: 1px solid rgba(124, 179, 66, 0.2);">
                <div style="display: flex; align-items: center; margin-bottom: 15px; color: #5a5a5a;">
                    <i class="fa fa-calendar-alt" style="font-size: 1.5rem; color: #7CB342; margin-right: 12px;"></i>
                    <h5 style="margin: 0; font-weight: 600;">Información del Periodo</h5>
                </div>
                <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 2rem;">
                    <div>
                        <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px 0; border-bottom: 1px solid rgba(0, 0, 0, 0.05);">
                            <span style="font-size: 0.85rem; color: #666;">Días trabajados</span>
                            <span style="font-weight: 600; color: #5a5a5a; font-size: 1.1rem;">{dias_trabajados:.1f}</span>
                        </div>
                    </div>
                    <div>
                        <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px 0; border-bottom: 1px solid rgba(0, 0, 0, 0.05);">
                            <span style="font-size: 0.85rem; color: #666;">Días IBC</span>
                            <span style="font-weight: 600; color: #5a5a5a; font-size: 1.1rem;">{dias_ibc:.1f}</span>
                        </div>
                    </div>
                    <div>
                        <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px 0; border-bottom: 1px solid rgba(0, 0, 0, 0.05);">
                            <span style="font-size: 0.85rem; color: #666;">Estado</span>
        '''
        
        if ausencias_no_rem > 0:
            html += f'''
                            <span style="background: #e9573f; color: white; padding: 5px 12px; border-radius: 20px; font-size: 0.75rem; font-weight: 600; display: inline-flex; align-items: center; gap: 5px;">
                                <i class="fa fa-exclamation-triangle"></i> {ausencias_no_rem:.0f} días ausencia
                            </span>
            '''
        else:
            html += '''
                            <span style="background: #8BC34A; color: white; padding: 5px 12px; border-radius: 20px; font-size: 0.75rem; font-weight: 600; display: inline-flex; align-items: center; gap: 5px;">
                                <i class="fa fa-check-circle"></i> Normal
                            </span>
            '''
        
        html += '''
                        </div>
                    </div>
                </div>
            </div>

            <!-- IBC Mes Anterior -->
            <div style="background: #F1F8E9; border-radius: 10px; padding: 20px; margin: 15px; border: 1px solid rgba(124, 179, 66, 0.2);">
                <div style="display: flex; align-items: center; margin-bottom: 15px; color: #5a5a5a;">
                    <i class="fa fa-history" style="font-size: 1.5rem; color: #7CB342; margin-right: 12px;"></i>
                    <h5 style="margin: 0; font-weight: 600;">IBC Mes Anterior</h5>
                </div>
                <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 1.5rem;">
        '''
        
        # IBC anterior
        html += f'''
                    <div>
                        <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px 0; border-bottom: 1px solid rgba(0, 0, 0, 0.05);">
                            <span style="font-size: 0.85rem; color: #666;">IBC</span>
                            <span style="font-weight: 600; color: #7CB342; font-size: 1.3rem;">${ibc_anterior:,.0f}</span>
                        </div>
                    </div>
                    <div>
                        <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px 0; border-bottom: 1px solid rgba(0, 0, 0, 0.05);">
                            <span style="font-size: 0.85rem; color: #666;">Días</span>
                            <span style="font-weight: 600; color: #5a5a5a; font-size: 1.1rem;">{dias_anterior:.1f}</span>
                        </div>
                    </div>
                    <div>
                        <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px 0; border-bottom: 1px solid rgba(0, 0, 0, 0.05);">
                            <span style="font-size: 0.85rem; color: #666;">Tarifa diaria</span>
                            <span style="font-weight: 600; color: #5a5a5a; font-size: 1.1rem;">${tarifa_diaria_anterior:,.0f}</span>
                        </div>
                    </div>
                    <div>
                        <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px 0; border-bottom: 1px solid rgba(0, 0, 0, 0.05);">
                            <span style="font-size: 0.85rem; color: #666;">Fuente</span>
                            <span style="font-weight: 600; color: #5a5a5a; font-size: 1.1rem;">{fuente_anterior}</span>
                        </div>
                    </div>
                </div>
            </div>

            <div style="height: 1px; background: linear-gradient(to right, transparent, #7CB342, transparent); margin: 30px 15px; opacity: 0.3;"></div>
        '''
        
        # Novedades del Periodo
        if novedades:
            html += f'''
            <div style="padding: 0 15px;">
                <h5 style="margin-bottom: 1rem; color: #5a5a5a;">
                    <i class="fa fa-bell" style="color: #7CB342;"></i> Novedades del Periodo
                </h5>
                <table style="width: 100%; background: white; border-radius: 10px; overflow: hidden; box-shadow: 0 2px 10px rgba(0, 0, 0, 0.05); margin: 15px 0;">
                    <thead>
                        <tr style="background: linear-gradient(135deg, #7CB342 0%, #9CCC65 100%); color: white;">
                            <th style="padding: 15px; font-weight: 600; text-transform: uppercase; font-size: 0.8rem; letter-spacing: 0.5px; border: none;">
                                <i class="fa fa-calendar"></i> Fecha
                            </th>
                            <th style="padding: 15px; font-weight: 600; text-transform: uppercase; font-size: 0.8rem; letter-spacing: 0.5px; border: none;">
                                <i class="fa fa-tag"></i> Tipo
                            </th>
                            <th style="padding: 15px; font-weight: 600; text-transform: uppercase; font-size: 0.8rem; letter-spacing: 0.5px; border: none;">
                                <i class="fa fa-info-circle"></i> Concepto
                            </th>
                            <th style="padding: 15px; font-weight: 600; text-transform: uppercase; font-size: 0.8rem; letter-spacing: 0.5px; border: none; text-align: center;">
                                <i class="fa fa-clock"></i> Días
                            </th>
                            <th style="padding: 15px; font-weight: 600; text-transform: uppercase; font-size: 0.8rem; letter-spacing: 0.5px; border: none; text-align: right;">
                                <i class="fa fa-dollar-sign"></i> Valor Original
                            </th>
                            <th style="padding: 15px; font-weight: 600; text-transform: uppercase; font-size: 0.8rem; letter-spacing: 0.5px; border: none; text-align: right;">
                                <i class="fa fa-calculator"></i> Valor IBC
                            </th>
                        </tr>
                    </thead>
                    <tbody>
            '''
            
            total_dias_nov = 0
            total_original_nov = 0
            total_ibc_nov = 0
            
            for novedad in novedades:
                fecha = novedad['fecha'].strftime('%d/%m/%Y') if novedad.get('fecha') else 'N/A'
                tipo = novedad.get('tipo', 'AUSENCIA')
                concepto = novedad.get('concepto', 'N/A')
                dias = novedad.get('dias', 0)
                valor_original = novedad.get('valor_original', 0)
                valor_recalculado = novedad.get('valor_recalculado', 0)
                cruza_mes = novedad.get('cruza_mes', False)
                
                total_dias_nov += dias
                total_original_nov += valor_original
                total_ibc_nov += valor_recalculado
                
                html += f'''
                        <tr style="border-bottom: 1px solid #f0f0f0;">
                            <td style="padding: 12px 15px;">{fecha}</td>
                            <td style="padding: 12px 15px;">
                                <span style="background: #DCEDC8; color: #33691E; padding: 5px 12px; border-radius: 20px; font-size: 0.75rem; font-weight: 600; display: inline-flex; align-items: center; gap: 5px;">
                                    <i class="fa fa-procedures"></i> {tipo}
                                </span>
                            </td>
                            <td style="padding: 12px 15px;">
                                {concepto}
                '''
                
                if cruza_mes:
                    html += '''
                                <span style="display: inline-flex; align-items: center; background: #e9573f; color: white; padding: 3px 10px; border-radius: 15px; font-size: 0.7rem; margin-left: 8px;">
                                    <i class="fa fa-exchange-alt" style="margin-right: 4px;"></i> Cruza mes
                                </span>
                    '''
                
                html += f'''
                            </td>
                            <td style="padding: 12px 15px; text-align: center;">{dias:.1f}</td>
                            <td style="padding: 12px 15px; text-align: right; font-weight: bold;">
                                {f'${valor_original:,.0f}' if valor_original != valor_recalculado else ''}
                            </td>
                            <td style="padding: 12px 15px; text-align: right; font-weight: bold;">${valor_recalculado:,.0f}</td>
                        </tr>
                '''
            
            html += f'''
                    </tbody>
                    <tfoot style="background-color: #5a5a5a; color: white; font-weight: bold;">
                        <tr>
                            <td colspan="3" style="padding: 15px; text-align: right;">TOTALES:</td>
                            <td style="padding: 15px; text-align: center;">{total_dias_nov:.1f}</td>
                            <td style="padding: 15px; text-align: right;">
                                {f'${total_original_nov:,.0f}' if total_original_nov != total_ibc_nov else ''}
                            </td>
                            <td style="padding: 15px; text-align: right;">${total_ibc_nov:,.0f}</td>
                        </tr>
                    </tfoot>
                </table>
            </div>
            
            <div style="height: 1px; background: linear-gradient(to right, transparent, #7CB342, transparent); margin: 30px 15px; opacity: 0.3;"></div>
            '''
        
        # Detalle de Conceptos IBC
        if conceptos_tabla:
            html += '''
            <div style="padding: 0 15px;">
                <h5 style="margin-bottom: 1rem; color: #5a5a5a;">
                    <i class="fa fa-list-alt" style="color: #7CB342;"></i> Detalle de Conceptos IBC
                </h5>
                <table style="width: 100%; background: white; border-radius: 10px; overflow: hidden; box-shadow: 0 2px 10px rgba(0, 0, 0, 0.05); margin: 15px 0;">
                    <thead>
                        <tr style="background: linear-gradient(135deg, #7CB342 0%, #9CCC65 100%); color: white;">
                            <th style="padding: 15px; font-weight: 600; text-transform: uppercase; font-size: 0.8rem; letter-spacing: 0.5px; border: none;">
                                <i class="fa fa-file-alt"></i> Concepto
                            </th>
                            <th style="padding: 15px; font-weight: 600; text-transform: uppercase; font-size: 0.8rem; letter-spacing: 0.5px; border: none;">
                                <i class="fa fa-calendar-day"></i> Fecha(s)
                            </th>
                            <th style="padding: 15px; font-weight: 600; text-transform: uppercase; font-size: 0.8rem; letter-spacing: 0.5px; border: none; text-align: center;">
                                <i class="fa fa-hashtag"></i> Cantidad
                            </th>
                            <th style="padding: 15px; font-weight: 600; text-transform: uppercase; font-size: 0.8rem; letter-spacing: 0.5px; border: none; text-align: right;">
                                <i class="fa fa-money-bill"></i> Valor Original
                            </th>
                            <th style="padding: 15px; font-weight: 600; text-transform: uppercase; font-size: 0.8rem; letter-spacing: 0.5px; border: none; text-align: right;">
                                <i class="fa fa-calculator"></i> Valor IBC
                            </th>
                        </tr>
                    </thead>
                    <tbody>
            '''
            
            # Agrupar conceptos por tipo
            conceptos_por_tipo = self._group_conceptos_by_tipo(conceptos_tabla)
            
            for tipo, conceptos in conceptos_por_tipo:
                if len(conceptos) == 1 and tipo not in ['AUSENCIA', 'INCAPACIDAD', 'VACACIONES DISFRUTADAS', 'VACACIONES COMPENSADAS']:
                    concepto = conceptos[0]
                    color = '#8BC34A' if tipo == 'BASICO' else 'inherit'
                    html += f'''
                        <tr style="border-bottom: 1px solid #f0f0f0;">
                            <td style="padding: 12px 15px;">
                                <strong style="color: {color};">{concepto['nombre']}</strong>
                            </td>
                            <td style="padding: 12px 15px;">{concepto.get('fecha', '')}</td>
                            <td style="padding: 12px 15px; text-align: center;">{concepto.get('cantidad', 0):.1f}</td>
                            <td style="padding: 12px 15px; text-align: right;">
                                {f'${concepto["valor_original"]:,.0f}' if (concepto.get("tipo", "") in ["AUSENCIA", "INCAPACIDAD", "AUSENCIA - IBC ANTERIOR", "AUSENCIA NO REMUNERADA"] and concepto["valor_original"] != concepto["valor_ibc"]) else ''}
                            </td>
                            <td style="padding: 12px 15px; text-align: right; font-weight: bold;">${concepto['valor_ibc']:,.0f}</td>
                        </tr>
                    '''
                else:
                    # Grupo con desplegable
                    total_grupo = sum(c['valor_ibc'] for c in conceptos)
                    html += f'''
                        <tr>
                            <td colspan="5" style="padding: 0;">
                                <details style="margin: 0;">
                                    <summary style="padding: 15px 20px; background: linear-gradient(to right, #F1F8E9, white); cursor: pointer; list-style: none; display: flex; justify-content: space-between; align-items: center; font-weight: 600; color: #5a5a5a;">
                                        <span>
                                            <i class="fa fa-folder" style="color: #7CB342;"></i> 
                                            <strong>{tipo}</strong>
                                            <small style="color: #999;">({len(conceptos)} conceptos)</small>
                                        </span>
                                        <span style="font-weight: bold;">${total_grupo:,.0f}</span>
                                    </summary>
                                    <div style="padding: 20px; background: white;">
                                        <table style="width: 100%;">
                    '''
                    
                    for concepto in conceptos:
                        html += f'''
                                            <tr>
                                                <td style="padding: 8px;">{concepto['nombre']}</td>
                                                <td style="padding: 8px;">{concepto.get('fecha', '')}</td>
                                                <td style="padding: 8px; text-align: center;">{concepto.get('cantidad', 0):.1f}</td>
                                                <td style="padding: 8px; text-align: right;">
                                                    {f'${concepto["valor_original"]:,.0f}' if (concepto.get("tipo", "") in ["AUSENCIA", "INCAPACIDAD", "AUSENCIA - IBC ANTERIOR", "AUSENCIA NO REMUNERADA"] and concepto["valor_original"] != concepto["valor_ibc"]) else ''}
                                                </td>
                                                <td style="padding: 8px; text-align: right; font-weight: bold;">${concepto['valor_ibc']:,.0f}</td>
                                            </tr>
                        '''
                    
                    html += '''
                                        </table>
                                    </div>
                                </details>
                            </td>
                        </tr>
                    '''
            
            # Total general
            total_original = sum(c['valor_original'] for c in conceptos_tabla)
            total_ibc = sum(c['valor_ibc'] for c in conceptos_tabla)
            
            html += f'''
                    </tbody>
                </table>
                
                <div style="background: #5a5a5a; color: white; border-radius: 8px; padding: 15px; margin-top: 20px;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <h5 style="margin: 0;">TOTAL GENERAL IBC</h5>
                        <div style="display: flex; gap: 4rem;">
                            <h5 style="margin: 0;">
                                {f'${total_original:,.0f}' if any(c.get("tipo", "") in ["AUSENCIA", "INCAPACIDAD", "AUSENCIA - IBC ANTERIOR", "AUSENCIA NO REMUNERADA"] and c["valor_original"] != c["valor_ibc"] for c in conceptos_tabla) else ''}
                            </h5>
                            <h5 style="margin: 0;">${total_ibc:,.0f}</h5>
                        </div>
                    </div>
                </div>
            </div>
            
            <div style="height: 1px; background: linear-gradient(to right, transparent, #7CB342, transparent); margin: 30px 15px; opacity: 0.3;"></div>
            '''
        
        # Cálculo del 40%
        html += f'''
            <div style="margin: 10px 15px;">
                <details style="border-radius: 8px; overflow: hidden; border: 1px solid rgba(0, 0, 0, 0.1);">
                    <summary style="padding: 15px 20px; background: linear-gradient(to right, #F1F8E9, white); cursor: pointer; list-style: none; display: flex; justify-content: space-between; align-items: center; font-weight: 600; color: #5a5a5a;">
                        <span>
                            <i class="fa fa-percentage" style="color: #7CB342;"></i> 
                            Cálculo del 40% - Ley 1393 de 2010
                        </span>
                        <span style="font-weight: bold;">Ver detalles</span>
                    </summary>
                    <div style="padding: 20px; background: white;">
                        <table style="width: 100%; border-collapse: collapse;">
                            <tr>
                                <td style="padding: 10px;">Base Salarial</td>
                                <td style="padding: 10px; text-align: right; font-weight: bold;">${base_salarial:,.0f}</td>
                            </tr>
                            <tr style="background: #F1F8E9;">
                                <td style="padding: 10px;"><strong>IBC_40 (Base para 40%)</strong></td>
                                <td style="padding: 10px; text-align: right;"><strong>${ibc_40:,.0f}</strong></td>
                            </tr>
                            <tr>
                                <td style="padding: 10px;">Total No Salarial</td>
                                <td style="padding: 10px; text-align: right;">${no_salarial:,.0f}</td>
                            </tr>
                            <tr>
                                <td style="padding: 10px;">Tope 40% = (IBC_40 + No Salarial) × 0.4</td>
                                <td style="padding: 10px; text-align: right;">${tope_40:,.0f}</td>
                            </tr>
                            <tr style="background: #DCEDC8;">
                                <td style="padding: 10px;"><strong>Excedente del 40%</strong></td>
                                <td style="padding: 10px; text-align: right;"><strong>${excedente_40:,.0f}</strong></td>
                            </tr>
                        </table>

                        <div style="background-color: #F1F8E9; border: 1px solid #7CB342; color: #5a5a5a; border-radius: 8px; padding: 15px; margin-top: 15px;">
                            <i class="fa fa-info-circle"></i>
                            <strong style="color: #7CB342;">Construcción del IBC Base Final:</strong><br/>
                            Base Salarial: ${base_salarial:,.0f}<br/>
                            + Excedente 40%: ${excedente_40:,.0f}<br/>
                            = IBC Base Final: <strong>${ibc_base_final:,.0f}</strong>
                        </div>
                    </div>
                </details>
            </div>
        '''
        
        # Resultado Final
        html += f'''
            <div style="background: linear-gradient(135deg, #8BC34A 0%, #AED581 100%); color: white; padding: 30px; margin: 20px 15px; border-radius: 12px; text-align: center; position: relative;">
                <h3 style="font-size: 1.2rem; opacity: 0.95; margin-bottom: 10px;">IBC FINAL</h3>
                <div style="font-size: 3rem; font-weight: 700; margin: 15px 0; text-shadow: 0 2px 10px rgba(0, 0, 0, 0.2);">
                    ${ibc_final:,.0f}
                </div>
                <div style="margin-top: 1rem;">
                    <span style="background: white; color: #5a5a5a; padding: 8px 20px; border-radius: 25px; font-size: 1rem; display: inline-block;">
                        <i class="fa fa-coins"></i> Valor día: <strong>${valor_dia:,.0f}</strong>
                    </span>
                </div>
        '''
        
        if aplico_maximo:
            html += '''
                <div style="margin-top: 1rem;">
                    <small style="color: rgba(255,255,255,0.9);">
                        <i class="fa fa-exclamation-triangle"></i> Se aplicó tope máximo de 25 SMMLV
                    </small>
                </div>
            '''
        
        html += '''
            </div>
        '''
        
        # Desglose adicional
        html += f'''
            <div style="margin: 10px 15px 20px;">
                <details style="border-radius: 8px; overflow: hidden; border: 1px solid rgba(0, 0, 0, 0.1);">
                    <summary style="padding: 15px 20px; background: linear-gradient(to right, #F1F8E9, white); cursor: pointer; list-style: none; display: flex; justify-content: space-between; align-items: center; font-weight: 600; color: #5a5a5a;">
                        <span>
                            <i class="fa fa-chart-pie" style="color: #7CB342;"></i> 
                            Desglose detallado de tipos de IBC
                        </span>
                        <span style="font-weight: bold;">Ver todos</span>
                    </summary>
                    <div style="padding: 20px; background: white;">
                        <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 1rem;">
                            <div>
                                <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px 0; border-bottom: 1px solid rgba(0, 0, 0, 0.05);">
                                    <span style="font-size: 0.85rem; color: #666;">1. IBC Base Puro (solo salarial)</span>
                                    <span style="font-weight: 600; color: #5a5a5a; font-size: 1.1rem;">
                                        ${ibc_base_puro:,.0f}
                                    </span>
                                </div>
                            </div>
                            <div>
                                <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px 0; border-bottom: 1px solid rgba(0, 0, 0, 0.05);">
                                    <span style="font-size: 0.85rem; color: #666;">2. IBC_40 (para cálculo 40%)</span>
                                    <span style="font-weight: 600; color: #5a5a5a; font-size: 1.1rem;">
                                        ${ibc_40:,.0f}
                                    </span>
                                </div>
                            </div>
                            <div>
                                <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px 0; border-bottom: 1px solid rgba(0, 0, 0, 0.05);">
                                    <span style="font-size: 0.85rem; color: #666;">3. IBC Base + Excedente</span>
                                    <span style="font-weight: 600; color: #5a5a5a; font-size: 1.1rem;">
                                        ${ibc_base_final:,.0f}
                                    </span>
                                </div>
                            </div>
                            <div>
                                <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px 0; border-bottom: 1px solid rgba(0, 0, 0, 0.05);">
                                    <span style="font-size: 0.85rem; color: #666;">5. IBC sin topes</span>
                                    <span style="font-weight: 600; color: #5a5a5a; font-size: 1.1rem;">
                                        ${ibc_sin_topes:,.0f}
                                    </span>
                                </div>
                            </div>
                        </div>
                    </div>
                </details>
            </div>
        </div>
        '''
        
        return html


    def _group_conceptos_by_tipo(self, conceptos_tabla):
        """Agrupa conceptos por tipo manteniendo el orden"""
        if not conceptos_tabla:
            return []
        
        grupos = {}
        for concepto in conceptos_tabla:
            tipo = concepto['tipo']
            if tipo not in grupos:
                grupos[tipo] = []
            grupos[tipo].append(concepto)
        
        # Ordenar tipos según prioridad
        tipos_ordenados = sorted(grupos.keys(), key=self._get_tipo_orden)
        
        return [(tipo, grupos[tipo]) for tipo in tipos_ordenados]

    def _get_tipo_orden(self, tipo):
        """Retorna orden para ordenar tipos de conceptos"""
        orden = {
            'BASICO': 0,
            'SALARIAL': 1,
            'NO SALARIAL': 2,
            'VACACIONES DISFRUTADAS': 3,
            'VACACIONES COMPENSADAS': 4,
            'INCAPACIDAD': 5,
            'AUSENCIA': 6,
            'AUSENCIA - IBC ANTERIOR': 7,
            'AUSENCIA NO REMUNERADA': 8,
            'BASIC - CRUZA MES': 9,
        }
        return orden.get(tipo, 99)
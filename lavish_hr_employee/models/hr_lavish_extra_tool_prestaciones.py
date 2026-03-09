"""
Servicio unificado para el cálculo de Prima de Servicios, Cesantías e Intereses
sobre Cesantías bajo la normatividad colombiana.

=================================
* Código **autosuficiente**. Ninguna función queda incompleta o cortada.
* Espaciado consistente (4 espacios). Sin caracteres de control ni ";".
* Calcula salario promedio **variable** con reglas de febrero y día 31.
* Respeta `descontar_suspensiones` para días efectivos.
* KPI completo y bloque `html_log` detallado generado en cada paso del cálculo.
* Log HTML incluye todos los componentes relevantes para auditoría.
* Manejo consistente de tipos Decimal para cálculos precisos.
* Estructura de datos compatible con reportes existentes.
"""
import calendar
from datetime import date, timedelta
from collections import defaultdict, OrderedDict
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple

from odoo import api, models, _
from odoo.exceptions import ValidationError
from odoo.tools import format_amount

DAYS_YEAR = Decimal("360")


def days360(start_date, end_date, method_eu=True):
    """Compute number of days between two dates regarding all months
    as 30-day months"""

    start_day = start_date.day
    start_month = start_date.month
    start_year = start_date.year
    end_day = end_date.day
    end_month = end_date.month
    end_year = end_date.year

    if (
            start_day == 31 or
            (
                method_eu is False and
                start_month == 2 and (
                    start_day == 29 or (
                        start_day == 28 and
                        calendar.isleap(start_year) is False
                    )
                )
            )
    ):
        start_day = 30

    if end_day == 31:
        if method_eu is False and start_day != 30:
            end_day = 1

            if end_month == 12:
                end_year += 1
                end_month = 1
            else:
                end_month += 1
        else:
            end_day = 30
    if end_month == 2 and end_day in (28, 29):
        end_day = 30

    return (
        end_day + end_month * 30 + end_year * 360 -
        start_day - start_month * 30 - start_year * 360 + 1
    )

class PrestacionesSocialesService(models.AbstractModel):
    _name = "prestaciones.sociales.service"
    _description = "Servicio Cálculo Prestaciones Sociales (sin Vacaciones)"
    _inherit = "lavish.tools.nomina"

    # ---------------------------------------------------------------------
    # UTILIDADES PARA MANEJO DE DECIMALES
    # ---------------------------------------------------------------------
    @api.model
    def to_decimal(self, value):
        """
        Convierte un valor a Decimal de manera segura.
        
        Args:
            value: Valor a convertir (int, float, str, Decimal)
        
        Returns:
            Valor convertido a Decimal
        """
        if isinstance(value, Decimal):
            return value
        elif value is None:
            return Decimal("0")
        return Decimal(str(value))

    @api.model
    def decimal_round(self, value, precision=2):
        """
        Redondea un valor Decimal al número de decimales especificado.
        
        Args:
            value: Valor a redondear (Decimal)
            precision: Número de decimales (int)
        
        Returns:
            Valor redondeado (Decimal)
        """
        value = self.to_decimal(value)
        decimal_precision = Decimal(f'0.{"0" * precision}1')
        return value.quantize(decimal_precision, rounding=ROUND_HALF_UP)

    @api.model
    def _fmt_money(self, val: Any) -> str:
        """
        Formatea un valor monetario según la configuración de la empresa.
        Maneja correctamente valores Decimal, float, int o str.
        
        Args:
            val: Valor a formatear (Decimal, float, int, str)
        
        Returns:
            Cadena con el valor formateado ($123,456.78)
        """
        # Si el valor es Decimal, convertirlo a float para format_amount
        if isinstance(val, Decimal):
            val_float = float(val)
        elif val is None:
            val_float = 0.0
        else:
            # Intentar convertir a float si es otro tipo
            try:
                val_float = float(val)
            except (ValueError, TypeError):
                val_float = 0.0
        
        return format_amount(self.env, val_float, self.env.company.currency_id)

    # ---------------------------------------------------------------------
    # API PÚBLICA
    # ---------------------------------------------------------------------
    @api.model
    def calcular_prima_servicios(
        self,
        localdict: Dict[str, Any],
        anio: int | None = None,
        descontar_suspensiones: bool = True,
    ) -> Dict[str, Any]:
        """
        Calcula la Prima de Servicios según la normatividad colombiana.
        
        Args:
            localdict: Diccionario con variables locales (payslip, contract, rules_multi)
            anio: Año para el cálculo, o None para usar el año actual
            descontar_suspensiones: Indica si se deben descontar las suspensiones
        
        Returns:
            Diccionario con los resultados del cálculo, incluyendo html_log
        """
        return self._calcular_generico(
            localdict,
            "prima",
            "base_prima",
            anio,
            descontar_suspensiones,
        )

    @api.model
    def calcular_cesantias(
        self,
        localdict: Dict[str, Any],
        anio: int | None = None,
        descontar_suspensiones: bool = True,
    ) -> Dict[str, Any]:
        """
        Calcula las Cesantías según la normatividad colombiana.
        
        Args:
            localdict: Diccionario con variables locales (payslip, contract, rules_multi)
            anio: Año para el cálculo, o None para usar el año actual
            descontar_suspensiones: Indica si se deben descontar las suspensiones
        
        Returns:
            Diccionario con los resultados del cálculo, incluyendo html_log
        """
        return self._calcular_generico(
            localdict,
            "ces",
            "base_cesantias",
            anio,
            descontar_suspensiones,
        )

    @api.model
    def calcular_intereses_cesantias(
        self,
        localdict: Dict[str, Any],
        anio: int | None = None,
        descontar_suspensiones: bool = True,
    ) -> Dict[str, Any]:
        """
        Calcula los Intereses sobre Cesantías según la normatividad colombiana.
        
        Args:
            localdict: Diccionario con variables locales (payslip, contract, rules_multi)
            anio: Año para el cálculo, o None para usar el año actual
            descontar_suspensiones: Indica si se deben descontar las suspensiones
        
        Returns:
            Diccionario con los resultados del cálculo, incluyendo html_log
        """
        return self._calcular_generico(
            localdict,
            "int_ces",
            "base_cesantias",
            anio,
            descontar_suspensiones,
        )

    @api.model
    def obtener_base(
        self,
        localdict: Dict[str, Any],
        tipo_prestacion: str,
        regla_obj=None,
        es_visual: bool = False,
        es_provision: bool = False,
        incluir_ultimo_anio: bool = False,
        fecha_inicio: Optional[date] = None,
        fecha_fin: Optional[date] = None,
        periodo_texto: str = None,
    ) -> Dict[str, Any]:
        """
        Obtiene la base de cálculo para una prestación social específica.
        
        Este método es la interfaz unificada para calcular cualquier tipo de prestación
        social y obtener sus datos completos incluyendo base, días y HTML detallado.
        
        Args:
            localdict: Diccionario con variables locales (payslip, contract, rules_multi)
            tipo_prestacion: Tipo de prestación ('prima', 'cesantias', 'intereses', 'vacaciones')
            regla_obj: Objeto de la regla salarial que solicita el cálculo
            es_visual: Indica si se debe generar información visual detallada
            es_provision: Indica si es cálculo para provisión
            incluir_ultimo_anio: Indica si se debe incluir el último año en los cálculos
            fecha_inicio: Fecha inicial opcional para reemplazar la de la nómina
            fecha_fin: Fecha final opcional para reemplazar la de la nómina
            periodo_texto: Texto descriptivo del período para el HTML
        
        Returns:
            Dict con base, días, log HTML y datos detallados para visualización
        """
        tipo_map = {
            'prima': 'prima',
            'cesantias': 'ces',
            'intereses': 'int_ces',
            'vacaciones': 'vac'
        }
        prst = tipo_map.get(tipo_prestacion, tipo_prestacion)
        
        param_map = {
            'prima': 'base_prima',
            'ces': 'base_cesantias',
            'int_ces': 'base_cesantias',
            'vac': 'base_vacaciones'
        }
        param_aux = param_map.get(prst, f'base_{tipo_prestacion}')
        
        if fecha_inicio is not None and fecha_fin is not None:
            localdict_mod = dict(localdict)
            
            slip_dict = {}
            for key in ['id', 'employee_id', 'contract_id', 'struct_id', 'state']:
                if hasattr(localdict['payslip'], key):
                    slip_dict[key] = getattr(localdict['payslip'], key)
            
            slip_dict['date_from'] = fecha_inicio
            slip_dict['date_to'] = fecha_fin
            
            localdict_mod['payslip'] = type('obj', (object,), slip_dict)
            
            localdict = localdict_mod
        
        anio = None
        if regla_obj and hasattr(regla_obj, 'anio_prestacion'):
            anio = regla_obj.anio_prestacion
        

        descontar_suspensiones = regla_obj.descontar_suspensiones
        
        if prst == 'prima':
            resultado = self.calcular_prima_servicios(localdict, anio, descontar_suspensiones)
        elif prst == 'ces':
            resultado = self.calcular_cesantias(localdict, anio, descontar_suspensiones)
        elif prst == 'int_ces':
            resultado = self.calcular_intereses_cesantias(localdict, anio, descontar_suspensiones)
        else:
            resultado = {
                'pres': 0,
                'days': 0,
                'plain_days': 0,
                'base': 0,
                'base_periodo': 0,
                'twage': 0,
                'total_variable': 0,
                'total_fix': 0,
                'susp': 0,
                'data_kpi': {
                    'licencias_no_remuneradas': [],
                    'reglas_salario_promedio': {},
                    'variaciones_salario': [],
                    'novedades_promedio': {
                        'entradas': [],
                        'totales': {
                            'payslip_total': 0,
                            'accumulated_total': 0,
                            'total_novedades': 0
                        }
                    },
                    'provisiones': {
                        'valor_anterior': 0,
                        'valor_actual': 0,
                        'diferencia': 0,
                        'estado': '',
                        'detalles': []
                    },
                    'meta_info': {
                        'fecha_inicio': localdict['payslip'].date_from,
                        'fecha_fin': localdict['payslip'].date_to,
                        'tipo_prestacion': 'vacaciones',
                    }
                },
                'date_from': localdict['payslip'].date_from,
                'date_to': localdict['payslip'].date_to,
                'html_log': '<div class="alert alert-warning">Cálculo de vacaciones no implementado en este servicio.</div>'
            }
        
        if periodo_texto and 'meta_info' in resultado['data_kpi']:
            resultado['data_kpi']['meta_info']['periodo_texto'] = periodo_texto
        
        resultado_unificado = {
            'resultado_compatible': resultado,
            'base_variable': resultado['base'],
            'log_html': resultado['html_log'],
            'data_visual': resultado['data_kpi']
        }
        
        return resultado_unificado

    # ---------------------------------------------------------------------
    # MÉTODO MAESTRO
    # ---------------------------------------------------------------------
    def _calcular_generico(
        self,
        localdict: Dict[str, Any],
        prst: str,
        param_aux: str,
        anio: int | None,
        desc_susp: bool,
    ) -> Dict[str, Any]:
        """
        Método maestro para el cálculo de prestaciones sociales.
        
        Args:
            localdict: Diccionario con variables locales (payslip, contract, etc.)
            prst: Tipo de prestación ('prima', 'ces', 'int_ces')
            param_aux: Parámetro auxiliar ('base_prima', 'base_cesantias')
            anio: Año para el cálculo, o None para usar el año de fecha_to
            desc_susp: Indica si se deben descontar las suspensiones
        
        Returns:
            Diccionario con resultados del cálculo y metadata
        """
        # Inicializamos el recolector HTML
        html_builder = HTMLLogBuilder(self, prst)
        
        # 1. Periodo
        d0, d1 = self._obtener_periodo(localdict, prst, anio)
        params = self._get_parametros_anuales(anio or d1.year)
        if not params:
            raise ValidationError(
                _("No hay parámetros anuales para el año %s") % (anio or d1.year)
            )
        
        html_builder.add_periodo(d0, d1)
        
        # 2. Días y suspensiones
        plain, eff, susp, lic_view = self._calcular_dias(localdict, d0, d1, desc_susp)
        
        html_builder.add_dias(plain, eff, susp)
        if lic_view:
            html_builder.add_suspensiones(lic_view)

        # 3. Salario, variables, KPI auxiliares
        (
            wage,
            aux_trans,
            total_var,
            base_amt,
            reglas_kpi,
            var_sal_kpi,
            novedades_kpi,
        ) = self._obtener_salario_base_y_kpi(
            localdict,
            d0,
            d1,
            eff or 1,
            params,
            param_aux,
            prst,
        )
        
        html_builder.add_salario_base(wage, aux_trans, total_var)
        if reglas_kpi:
            html_builder.add_reglas_base(reglas_kpi)
        if var_sal_kpi:
            html_builder.add_variaciones_salario(var_sal_kpi)
        if novedades_kpi and 'entradas' in novedades_kpi:
            html_builder.add_novedades(novedades_kpi['entradas'])

        # 4. Provisiones y meta
        kpi, val_prest = self._calcular_provision(
            localdict,
            prst,
            base_amt,
            eff,
            lic_view,
            susp,
            wage,
            aux_trans,
            total_var,
            plain,
            d0,
            d1,
        )
        
        # Actualizar KPI con los datos de reglas y variaciones
        kpi['reglas_salario_promedio'] = reglas_kpi
        kpi['variaciones_salario'] = var_sal_kpi
        kpi['novedades_promedio'] = novedades_kpi
        
        html_builder.add_provisiones(kpi.get('provisiones', {}))
        
        # Calcular base diaria asegurando que ambos operandos sean Decimal
        base_amt_decimal = self.to_decimal(base_amt)
        days_year_decimal = self.to_decimal(DAYS_YEAR)
        base_diaria = base_amt_decimal / days_year_decimal
        base_diaria_redondeada = self.decimal_round(base_diaria, 2)
        
        # Fórmulas de cálculo para el HTML
        formulas = [
            {
                "concepto": _("Base de liquidación"),
                "formula": f"{self._fmt_money(wage)} + {self._fmt_money(aux_trans)} + {self._fmt_money(total_var)} = {self._fmt_money(base_amt)}"
            },
            {
                "concepto": _("Base diaria"),
                "formula": f"{self._fmt_money(base_amt)} ÷ {days_year_decimal} = {self._fmt_money(base_diaria_redondeada)}"
            },
            {
                "concepto": _("Valor prestación"),
                "formula": f"{self._fmt_money(base_diaria_redondeada)} × {eff} = {self._fmt_money(val_prest)}" if prst != "int_ces" else f"{self._fmt_money(base_diaria_redondeada)} × {eff} x Porc(({eff} / 360) * 12) -> {round((eff/360) * 12,2)}% = {self._fmt_money(val_prest)}"
            }
        ]
        html_builder.add_formulas(formulas)
        
        # Resultado final para el HTML
        html_builder.add_resultado(base_amt, base_diaria_redondeada, val_prest)

        # 5. Resultado consolidado con estructura compatible
        res: Dict[str, Any] = {
            "pres": float(total_var),
            "days": eff,
            "plain_days": plain,
            "base": float(base_diaria_redondeada),  # Convertimos a float después de redondear como Decimal
            "base_periodo": float(base_amt),
            "twage": float(self.to_decimal(wage) * self.to_decimal(eff) / self.to_decimal(30)) if eff else 0.0,
            "total_variable": float(total_var),
            "total_fix": float(aux_trans),
            "susp": susp,
            "data_kpi": kpi,
            "date_from": d0,
            "date_to": d1,
        }

        # 6. Generar HTML y añadirlo al resultado
        res["html_log"] = html_builder.generate()

        return res

    # ---------------------------------------------------------------------
    # PERÍODO Y PARÁMETROS
    # ---------------------------------------------------------------------
    def _obtener_periodo(self, localdict: Dict[str, Any], prst: str, anio: int | None):
        """
        Determina el período de cálculo según el tipo de prestación y contrato.
        """
        slip = localdict["payslip"]
        contract = localdict["contract"]
        code = localdict.get("rule", {}).get("code", "")
        if code in ("CES_YEAR", "INTCES_YEAR"):
            y = (anio or slip.date_to.year) - 1
            start = date(y, 1, 1)
            end = date(y, 12, 31)
            if contract.date_start and contract.date_start > start:
                start = contract.date_start
            return start, end
        return slip.date_from, slip.date_to

    def _get_parametros_anuales(self, year: int):
        """
        Obtiene los parámetros anuales para el cálculo (SMMLV, auxilio de transporte, etc.).
        """
        return self.env["hr.annual.parameters"].search([("year", "=", year)], limit=1)

    # ---------------------------------------------------------------------
    # DÍAS Y SUSPENSIONES
    # ---------------------------------------------------------------------
    def _calcular_dias(
        self,
        localdict: Dict[str, Any],
        d0: date,
        d1: date,
        descontar: bool,
    ):
        """
        Calcula los días totales, efectivos y suspensiones en el período.
        """
        contract = localdict["contract"]
        plain = days360(d0, d1)
        leave_lines = self.env["hr.leave.line"].search(
            [
                ("leave_id.employee_id", "=", contract.employee_id.id),
                ("leave_id.state", "=", "validate"),
                ("leave_id.unpaid_absences", "=", True),
                ("date", "<=", d1),
                ("date", ">=", d0),
            ]
        )
        susp = sum(line.days_payslip for line in leave_lines)
        lic_view = [
            {
                "fecha_inicio": l.date_from,
                "fecha_fin": l.date_to,
                "tipo_licencia": l.holiday_status_id.name,
                "dias": l.number_of_days_in_payslip,
                "regla_origen": "HR_LEAVE"
            }
            for l in leave_lines.mapped("leave_id")
        ]
        eff = plain - (susp if descontar else 0)
        return plain, max(eff, 0), susp, lic_view

    # ---------------------------------------------------------------------
    # CÁLCULO DE DÍAS
    # ---------------------------------------------------------------------
    @api.model
    def dias_entre_fechas(self, fecha_inicio: date, fecha_fin: date, tipo: str = 'comercial') -> int:
        """
        Calcula los días entre dos fechas según el tipo de cálculo especificado.
        
        Args:
            fecha_inicio: Fecha de inicio
            fecha_fin: Fecha de fin
            tipo: Tipo de cálculo ('comercial', 'calendario', '30_dias')
                - 'comercial': Usa el método days360 (año comercial de 360 días)
                - 'calendario': Usa la diferencia real de días en el calendario
                - '30_dias': Considera todos los meses como de 30 días
        
        Returns:
            Número de días entre las fechas según el tipo de cálculo
        """
        if not fecha_inicio or not fecha_fin:
            return 0
        
        if fecha_inicio > fecha_fin:
            return 0
        
        if tipo == 'comercial':
            return self.days360(fecha_inicio, fecha_fin)
        elif tipo == 'calendario':
            return (fecha_fin - fecha_inicio).days + 1
        elif tipo == '30_dias':
            # Cálculo considerando meses de 30 días
            years_diff = fecha_fin.year - fecha_inicio.year
            months_diff = fecha_fin.month - fecha_inicio.month
            days_diff = fecha_fin.day - fecha_inicio.day
            
            # Ajustes para días 31 (considerados como 30)
            if fecha_inicio.day == 31:
                days_diff += 1
            if fecha_fin.day == 31:
                days_diff -= 1
                
            total_months = years_diff * 12 + months_diff
            total_days = total_months * 30 + days_diff + 1  # +1 para incluir el día final
            
            return total_days
        else:
            # Por defecto, usar el método comercial
            return self.days360(fecha_inicio, fecha_fin)

    @api.model
    def days360(self, start_date: date, end_date: date, method: str = 'US') -> int:
        """
        Calcula los días entre dos fechas usando el método de año comercial de 360 días.
        
        Este método implementa la fórmula financiera DAYS360 que considera:
        - Todos los meses tienen 30 días
        - El año tiene 360 días
        
        Args:
            start_date: Fecha de inicio
            end_date: Fecha de fin
            method: Método de cálculo ('US' o 'EU')
                - 'US': Método de EE.UU. (NASD)
                - 'EU': Método Europeo
        
        Returns:
            Número de días entre las fechas según el método de 360 días
        """
        if not start_date or not end_date:
            return 0
        
        if start_date > end_date:
            return 0
        
        # Convertir de date a tuple de (año, mes, día) para facilitar manipulaciones
        start_year, start_month, start_day = start_date.year, start_date.month, start_date.day
        end_year, end_month, end_day = end_date.year, end_date.month, end_date.day
        
        if method == 'US':
            if start_day == 31 or (
                start_day >= 28 and start_month == 2 and 
                start_day == self._last_day_of_month(start_date)
            ):
                start_day = 30
            
            if end_day == 31 or (
                end_day >= 28 and end_month == 2 and 
                end_day == self._last_day_of_month(end_date)
            ):
                if start_day != 30:
                    end_day = 30
                elif end_month == 2 and end_day == 28:
                    end_day = 30
        else:
            if start_day == 31 or (
                start_month == 2 and start_day == self._last_day_of_month(start_date)
            ):
                start_day = 30
            
            if end_day == 31 or (
                end_month == 2 and end_day == self._last_day_of_month(end_date)
            ):
                end_day = 30
        
        return (end_year - start_year) * 360 + (end_month - start_month) * 30 + (end_day - start_day)

    def _last_day_of_month(self, date_value: date) -> int:
        """
        Determina el último día del mes para la fecha dada.
        
        Args:
            date_value: Fecha a evaluar
        
        Returns:
            Número del último día del mes
        """
        if date_value.month == 2:
            if self._is_leap_year(date_value.year):
                return 29
            else:
                return 28
        elif date_value.month in [4, 6, 9, 11]:
            return 30
        else:
            return 31

    def _is_leap_year(self, year: int) -> bool:
        """
        Determina si un año es bisiesto.
        
        Args:
            year: Año a evaluar
        
        Returns:
            True si es año bisiesto, False en caso contrario
        """
        return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)

    # ---------------------------------------------------------------------
    # SALARIO PROMEDIO
    # ---------------------------------------------------------------------
    def _promedio_salario_variable(self, contract, d0, d1):
        """
        Calcula el promedio del salario para contratos con modalidad variable,
        considerando reglas especiales para febrero y día 31.
        """
        dias_total = (d1 - d0).days + 1
        if dias_total <= 0:
            return self.to_decimal(contract.wage)
        acc = Decimal("0")
        dias_cont = 0
        cur = d0
        while cur <= d1:
            if cur.day != 31:
                diario = self.to_decimal(contract.get_wage_in_date(cur)) / self.to_decimal(30)
                if cur.month == 2:
                    if cur.day == 28 and (cur + timedelta(days=1)).day != 29:
                        acc += diario * self.to_decimal(3)
                        dias_cont += 3
                    elif cur.day == 29:
                        acc += diario * self.to_decimal(2)
                        dias_cont += 2
                    else:
                        acc += diario
                        dias_cont += 1
                else:
                    acc += diario
                    dias_cont += 1
            cur += timedelta(days=1)
        return (acc / self.to_decimal(dias_cont)) * self.to_decimal(30) if dias_cont else self.to_decimal(contract.wage)

    def _promedio_salario_fijo(self, contract, d0, d1):
        """
        Calcula el promedio del salario para contratos con modalidad fija,
        considerando los cambios salariales durante el período.
        """
        changes = self.env["hr.contract.change.wage"].search(
            [("contract_id", "=", contract.id), ("date_start", "<=", d1)],
            order="date_start",
        )
        if not changes:
            return self.to_decimal(contract.wage)
        acc, dias = Decimal("0"), 0
        cur = d0
        while cur <= d1:
            acc += self.to_decimal(contract.get_wage_in_date(cur))
            dias += 1
            cur += timedelta(days=1)
        return acc / self.to_decimal(dias) if dias else self.to_decimal(contract.wage)

    # ---------------------------------------------------------------------
    # AUXILIO VARIABLE
    # ---------------------------------------------------------------------
    def _auxilio_transporte_variable(self, contract, d0, d1, dias):
        """
        Calcula el auxilio de transporte variable basado en nóminas anteriores.
        """
        lines = self.env["hr.payslip.line"].search(
            [
                ("contract_id", "=", contract.id),
                ("salary_rule_id.code", "in", ["AUX000", "AUX1111", "AUX_CONECTIVIDAD"]),
                ("slip_id.state", "in", ["done", "paid"]),
                ("slip_id.date_from", ">=", d0),
                ("slip_id.date_to", "<=", d1),
            ]
        )
        total = sum(self.to_decimal(l.total) for l in lines)
        return (total / self.to_decimal(dias)) * self.to_decimal(30) if dias else Decimal("0")

    # ---------------------------------------------------------------------
    # SALARIO BASE + KPI AUXILIAR
    # ---------------------------------------------------------------------
    def _obtener_salario_base_y_kpi(
        self,
        localdict,
        d0,
        d1,
        dias,
        params,
        param_aux,
        prst,
    ):
        """
        Obtiene el salario base, auxilio de transporte, y componentes variables
        para el cálculo de prestaciones. Genera estructuras de datos compatibles con reportes.
        """
        contract = localdict["contract"]
        rules_multi = localdict["rules_multi"]
        wage = (
            self._promedio_salario_variable(contract, d0, d1)
            if contract.modality_salary == "variable"
            else self._promedio_salario_fijo(contract, d0, d1)
        )

        reglas_kpi = {}
        novedades = []

        payslip_lines = self.env["hr.payslip.line"].search([
            ("contract_id", "=", contract.id),
            ("slip_id.state", "in", ["done", "paid"]),
            ("slip_id.date_from", ">=", d0),
            ("slip_id.date_to", "<=", d1),
            ("salary_rule_id." + param_aux, "=", True),
        ])
        
        payslip_total = Decimal("0")
        for line in payslip_lines:
            code = line.salary_rule_id.code
            if code in ("BASIC", "AUX000"):
                continue
            elif prst == "prima" and not line.salary_rule_id.base_prima:
                continue
            elif prst in ("ces", "int_ces") and not line.salary_rule_id.base_cesantias:
                continue
            
            monto = self.to_decimal(getattr(line, "total", 0))
            payslip_total += monto
            
            if code not in reglas_kpi:
                reglas_kpi[code] = {
                    "nombre": line.salary_rule_id.name,
                    "total": float(monto),
                    "ocurrencias": []
                }
            else:
                reglas_kpi[code]["total"] += float(monto)
            
            reglas_kpi[code]["ocurrencias"].append({
                "fecha": getattr(line, "date_to", d1),
                "monto": float(monto),
                "origen": "nomina"
            })
            
            novedades.append({
                "fecha": getattr(line, "date_to", d1),
                "regla_salarial": code,
                "nombre_regla": line.salary_rule_id.name,
                "monto": float(monto),
                "origen": "nomina",
                "regla_origen": "nomina"
            })

        accumulated_lines = self.env["hr.accumulated.payroll"].search([
            ("employee_id", "=", contract.employee_id.id),
            ("date", ">=", d0),
            ("date", "<=", d1),
            ("salary_rule_id." + param_aux, "=", True),
        ])
        
        accumulated_total = Decimal("0")
        for line in accumulated_lines:
            code = line.salary_rule_id.code
            if code in ("BASIC", "AUX000"):
                continue
            if prst == "prima" and not line.salary_rule_id.base_prima:
                continue
            if prst in ("ces", "int_ces") and not line.salary_rule_id.base_cesantias:
                continue
            
            monto = self.to_decimal(getattr(line, "amount", 0))
            accumulated_total += monto
            
            if code not in reglas_kpi:
                reglas_kpi[code] = {
                    "nombre": line.salary_rule_id.name,
                    "total": float(monto),
                    "ocurrencias": []
                }
            else:
                reglas_kpi[code]["total"] += float(monto)
            
            reglas_kpi[code]["ocurrencias"].append({
                "fecha": getattr(line, "date", d1),
                "monto": float(monto),
                "origen": "acumulado"
            })
            
            novedades.append({
                "fecha": getattr(line, "date", d1),
                "regla_salarial": code,
                "nombre_regla": line.salary_rule_id.name,
                "monto": float(monto),
                "origen": "acumulado",
                "regla_origen": "acumulado"
            })

        total_current = Decimal("0")
        for code, data in rules_multi.items():
            rule_object = data.get('current', {}).get('object')
            
            if code in ("BASIC", "AUX000"):
                continue
                
            elif prst == "prima" and not rule_object.base_prima:
                continue
            elif prst in ("ces", "int_ces") and not rule_object.base_cesantias:
                continue
            monto = self.to_decimal(data.get('current', {}).get('total'))
            if monto == 0:
                continue
            total_current += monto
            rule_name = rule_object.name
            
            if code not in reglas_kpi:
                reglas_kpi[code] = {
                    "nombre": rule_name,
                    "total": float(monto),
                    "ocurrencias": []
                }
            else:
                reglas_kpi[code]["total"] += float(monto)
            
            reglas_kpi[code]["ocurrencias"].append({
                "fecha": d1,
                "monto": float(monto),
                "origen": "nomina actual"
            })
            
            novedades.append({
                "fecha": d1,
                "regla_salarial": code,
                "nombre_regla": rule_name,
                "monto": float(monto),
                "origen": "nomina actual",
                "regla_origen": "nomina actual"
            })

        total_nov = payslip_total + accumulated_total + total_current

        novedades_kpi = {
            "entradas": novedades,
            "totales": {
                "payslip_total": float(payslip_total),
                "accumulated_total": float(accumulated_total),
                "total_novedades": float(total_nov)
            }
        }

        aux_trans = Decimal("0")
        if contract.modality_aux == "basico":
            aux_trans = (
                self.to_decimal(params.transportation_assistance_monthly)
                if wage <= self.to_decimal(params.top_max_transportation_assistance)
                else Decimal("0")
            )
        elif contract.modality_aux == "variable":
            aux_trans = self._auxilio_transporte_variable(contract, d0, d1, dias)

        if dias:
            dias_decimal = self.to_decimal(dias)
            base_amt = wage + aux_trans + (total_nov / dias_decimal) * self.to_decimal(30)
        else:
            base_amt = wage + aux_trans
        #if prst == "int_ces":
        #    base_amt = (base_amt / self.to_decimal(DAYS_YEAR)) * (self.to_decimal(dias) / self.to_decimal(DAYS_YEAR)) * self.to_decimal(12) * self.to_decimal(dias)
        var_sal_kpi = []
        wage_changes = self.env["hr.contract.change.wage"].search([
            ("contract_id", "=", contract.id),
            ("date_start", ">=", d0),
            ("date_start", "<=", d1)
        ], order="date_start")
        
        for change in wage_changes:
            var_sal_kpi.append({
                "fecha": change.date_start,
                "salario": float(change.wage),
                "regla_origen": "HR_CONTRACT_CHANGE_WAGE"
            })

        return (
            wage,
            aux_trans,
            total_nov,
            base_amt,
            reglas_kpi,
            var_sal_kpi,
            novedades_kpi,
        )

    # ---------------------------------------------------------------------
    # PROVISIÓN / META
    # ---------------------------------------------------------------------
    def sum_mount_x_rule(
        self,
        rule_code: str,
        contract: models.Model,
        d0: date,
        d1: date,
    ) -> Decimal:
        """Suma los montos (nomina + acumulados) de una regla salarial en un rango.

        Se usa para obtener provisiones anteriores sin consultas SQL.
        """
        line_total = sum(
            Decimal(str(l.total))
            for l in self.env["hr.payslip.line"].search(
                [
                    ("contract_id", "=", contract.id),
                    ("salary_rule_id.code", "=", rule_code),
                    ("slip_id.state", "in", ["done", "paid"]),
                    ("slip_id.date_from", ">=", d0),
                    ("slip_id.date_to", "<=", d1),
                ]
            )
        )
        accumulated_total = sum(
            Decimal(str(a.amount))
            for a in self.env["hr.accumulated.payroll"].search(
                [
                    ("employee_id", "=", contract.employee_id.id),
                    ("salary_rule_id.code", "=", rule_code),
                    ("date", ">=", d0),
                    ("date", "<=", d1),
                ]
            )
        )
        return line_total + accumulated_total
    
    def _calcular_provision(
        self,
        localdict,
        prst,
        base_amt,
        dias_eff,
        lic_view,
        susp,
        wage,
        aux_trans,
        total_var,
        plain_days,
        d0,
        d1,
    ):
        """
        Calcula las provisiones y meta-información de la prestación.
        Mantiene la estructura de datos compatible con los reportes existentes.
        """
        contract = localdict["contract"]
        payslip = localdict["payslip"]
        rule_code = localdict.get("rule", {}).get("code", "")

        nombres_prestacion = {
            'prima': _('Prima de Servicios'),
            'ces': _('Cesantías'),
            'int_ces': _('Intereses de Cesantías')
        }
        nombre_prestacion = nombres_prestacion.get(prst, prst.capitalize())

        base_amt_decimal = self.to_decimal(base_amt)
        dias_eff_decimal = self.to_decimal(dias_eff)
        days_year_decimal = self.to_decimal(DAYS_YEAR)
        
        val_prest_decimal = (base_amt_decimal / days_year_decimal) * dias_eff_decimal
        if prst == "int_ces":
            val_prest_decimal = (base_amt_decimal / days_year_decimal) * dias_eff_decimal * ((self.to_decimal(0.12) * dias_eff_decimal) /days_year_decimal)
        val_prest = self.decimal_round(val_prest_decimal, 2)

        provision_prev = Decimal("0")
        mp = {"prima": "PRV_PRIM", "ces": "PRV_CES", "int_ces": "PRV_ICES"}
        prov_code = mp.get(prst)
        if prov_code:
            provision_prev = Decimal(
                str(self.sum_mount_x_rule(prov_code, contract, d0, payslip.date_to))
            ) * Decimal("-1")  # Usar Decimal para multiplicación

        diff = val_prest - (provision_prev * Decimal("-1"))
        estado = _("Por provisionar") if diff > Decimal("0") else _("Ajustar provisión")

        provisiones = {
            'valor_anterior': float(provision_prev),
            'valor_actual': float(val_prest),
            'diferencia': float(diff),
            'estado': estado,
            'detalles': [
                {
                    'concepto': _(f"Provisión {nombre_prestacion}"),
                    'codigo': rule_code,
                    'provision_al_corte': float(provision_prev),
                    'valor_actual': float(val_prest),
                    'diferencia': float(diff),
                    'estado': estado
                }
            ]
        }
        
        if not rule_code.startswith("PRV_") and prst in ['prima', 'ces', 'int_ces']:
            provisiones['detalles'].append({
                'concepto': _(f"Liquidación {nombre_prestacion}"),
                'codigo': rule_code,
                'provision_al_corte': float(provision_prev),
                'valor_a_pagar': float(val_prest),
                'valor_faltante': float(diff) if float(diff) > 0 else 0,
                'ajuste': float(diff) if float(diff) < 0 else 0
            })

        meta_info = {
            'fecha_inicio': d0,
            'fecha_fin': d1,
            'plain_days': plain_days,
            'tipo_prestacion': prst,
            'code': rule_code,
            'wage': float(wage),
            'total_variable': float(total_var),
            'auxtransporte': float(aux_trans),
            'valor_prestacion': float(val_prest),
            'amount_base': float(base_amt),
            'susp': float(susp),
            'provision_anterior': float(provision_prev),
            'provision_actual': float(val_prest),
            'diferencia_provision': float(diff)
        }

        kpi = {
            'licencias_no_remuneradas': lic_view,
            'provisiones': provisiones,
            'meta_info': meta_info,
            'reglas_salario_promedio': {},
            'variaciones_salario': [],
            'novedades_promedio': {
                'entradas': [],
                'totales': {
                    'payslip_total': 0,
                    'accumulated_total': 0,
                    'total_novedades': 0
                }
            }
        }
        
        return kpi, val_prest


# ---------------------------------------------------------------------
# CLASE AUXILIAR PARA CONSTRUIR HTML LOG
# ---------------------------------------------------------------------
class HTMLLogBuilder:
    """
    Clase auxiliar para construir el HTML log paso a paso.
    """
    def __init__(self, service, tipo_prestacion):
        self.service = service
        self.tipo_prestacion = tipo_prestacion
        self.nombres_prestacion = {
            'prima': _('Prima de Servicios'),
            'ces': _('Cesantías'),
            'int_ces': _('Intereses de Cesantías')
        }
        self.nombre_prestacion = self.nombres_prestacion.get(tipo_prestacion, tipo_prestacion.capitalize())
        
        self.partes = []
        
        self.partes.append('<div class="p-3 border rounded bg-light">')
        self.partes.append(f'<h5 class="text-primary">{_("Cálculo de")} {self.nombre_prestacion}</h5>')
    
    def add_periodo(self, fecha_inicio: date, fecha_fin: date):
        """Añade información del período"""
        self.partes.append(
            f'<small>{fecha_inicio.strftime("%d/%m/%Y")} – {fecha_fin.strftime("%d/%m/%Y")}</small><hr/>'
        )
    
    def add_dias(self, dias_totales: int, dias_efectivos: int, dias_suspension: int):
        """Añade información de días"""
        if dias_totales > 0:
            self.partes.append('<div class="mb-3 p-2 bg-white rounded shadow-sm">')
            self.partes.append(f'<h6 class="mb-2">{_("Días del Periodo")}:</h6>')
            
            self.partes.append('<div class="d-flex justify-content-around text-center">')
            self.partes.append(
                f'<div><strong>{_("Totales")}</strong><br>'
                f'<span class="badge bg-warning rounded-pill">{dias_totales}</span></div>'
            )
            
            if dias_suspension > 0:
                self.partes.append(
                    f'<div><strong>{_("Suspensión")}</strong><br>'
                    f'<span class="badge bg-warning text-dark rounded-pill">{dias_suspension}</span></div>'
                )
            
            if dias_efectivos > 0:
                self.partes.append(
                    f'<div><strong>{_("Efectivos")}</strong><br>'
                    f'<span class="badge bg-success rounded-pill">{dias_efectivos}</span></div>'
                )
            
            self.partes.append('</div>')
            self.partes.append('</div>')
    
    def add_suspensiones(self, suspensiones: List[Dict[str, Any]]):
        """Añade información de suspensiones"""
        if suspensiones and len(suspensiones) > 0:
            self.partes.append('<div class="mt-3 mb-3">')
            self.partes.append(f'<h6 class="mb-2">{_("Licencias/Suspensiones")}:</h6>')
            
            self.partes.append('<div class="table-responsive">')
            self.partes.append('<table class="table table-sm table-bordered table-hover">')
            self.partes.append(
                f'<thead class="table-light"><tr><th>{_("Tipo")}</th><th>{_("Desde")}</th>'
                f'<th>{_("Hasta")}</th><th>{_("Días")}</th></tr></thead>'
            )
            self.partes.append('<tbody>')
            
            for suspension in suspensiones:
                fecha_inicio = suspension.get('fecha_inicio', '')
                fecha_fin = suspension.get('fecha_fin', '')
                
                if isinstance(fecha_inicio, date):
                    fecha_inicio = fecha_inicio.strftime("%d/%m/%Y")
                
                if isinstance(fecha_fin, date):
                    fecha_fin = fecha_fin.strftime("%d/%m/%Y")
                
                self.partes.append('<tr>')
                self.partes.append(f'<td>{suspension.get("tipo_licencia", "")}</td>')
                self.partes.append(f'<td>{fecha_inicio}</td>')
                self.partes.append(f'<td>{fecha_fin}</td>')
                self.partes.append(f'<td class="text-center">{suspension.get("dias", 0)}</td>')
                self.partes.append('</tr>')
            
            self.partes.append('</tbody></table>')
            self.partes.append('</div>')
            self.partes.append('</div>')
    
    def add_salario_base(self, salario_base: Decimal, auxilio_transporte: Decimal, salario_variable: Decimal):
        """Añade información del salario base"""
        self.partes.append('<div class="mb-3 p-2 bg-white rounded shadow-sm border-start border-primary border-4">')
        self.partes.append(f'<h6 class="mb-2">{_("Componentes del Cálculo")}:</h6>')
        
        if salario_base > 0:
            self.partes.append(
                f'<div><strong>{_("Salario base")}:</strong> '
                f'<span class="text-primary">{self.service._fmt_money(salario_base)}</span></div>'
            )
        
        if salario_variable > 0:
            self.partes.append(
                f'<div><strong>{_("Salario variable")}:</strong> '
                f'<span class="text-primary">{self.service._fmt_money(salario_variable)}</span></div>'
            )
        
        if auxilio_transporte > 0:
            self.partes.append(
                f'<div><strong>{_("Auxilio de transporte")}:</strong> '
                f'<span class="text-primary">{self.service._fmt_money(auxilio_transporte)}</span></div>'
            )
        
        self.partes.append('</div>')
    
    def add_reglas_base(self, reglas_base: Dict[str, Dict[str, Any]]):
        """Añade información de reglas base"""
        reglas_filtradas = {k: v for k, v in reglas_base.items() if v.get('total', 0) > 0}
        if reglas_filtradas:
            self.partes.append('<div class="mt-3 mb-3">')
            self.partes.append(f'<h6 class="mb-2">{_("Conceptos Base")}:</h6>')
            
            self.partes.append('<ul class="list-group mb-0">')
            for codigo, info in reglas_filtradas.items():
                nombre = info.get('nombre', codigo)
                total = info.get('total', 0)
                self.partes.append(
                    '<li class="list-group-item d-flex justify-content-between align-items-center py-2">'
                    f'<span><i class="fa fa-plus-circle text-primary"></i> {nombre}</span>'
                    f'<span class="badge bg-warning rounded-pill">{self.service._fmt_money(total)}</span>'
                    '</li>'
                )
            self.partes.append('</ul>')
            self.partes.append('</div>')
    
    def add_variaciones_salario(self, variaciones: List[Dict[str, Any]]):
        """Añade información de variaciones salariales"""
        if variaciones and len(variaciones) > 0:
            self.partes.append('<div class="mt-3 mb-3">')
            self.partes.append(f'<h6 class="mb-2">{_("Variaciones Salariales")}:</h6>')
            
            self.partes.append('<div class="table-responsive">')
            self.partes.append('<table class="table table-sm table-bordered">')
            self.partes.append(f'<thead class="table-light"><tr><th>{_("Fecha")}</th><th>{_("Salario")}</th></tr></thead>')
            self.partes.append('<tbody>')
            
            for var in variaciones:
                fecha = var.get('fecha')
                if isinstance(fecha, date):
                    fecha = fecha.strftime("%d/%m/%Y")
                
                self.partes.append('<tr>')
                self.partes.append(f'<td>{fecha}</td>')
                self.partes.append(f'<td class="text-end">{self.service._fmt_money(var.get("salario", 0))}</td>')
                self.partes.append('</tr>')
            
            self.partes.append('</tbody></table>')
            self.partes.append('</div>')
            self.partes.append('</div>')
    
    def add_novedades(self, novedades: List[Dict[str, Any]]):
        """Añade información de novedades salariales"""
        if novedades and len(novedades) > 0:
            self.partes.append('<div class="mt-3 mb-3">')
            self.partes.append(f'<h6 class="mb-2">{_("Novedades Salariales")}:</h6>')
            
            self.partes.append('<div class="table-responsive">')
            self.partes.append('<table class="table table-sm table-bordered">')
            self.partes.append(
                f'<thead class="table-light"><tr>'
                f'<th>{_("Fecha")}</th>'
                f'<th>{_("Concepto")}</th>'
                f'<th>{_("Origen")}</th>'
                f'<th>{_("Valor")}</th>'
                f'</tr></thead>'
            )
            self.partes.append('<tbody>')
            
            for nov in novedades:
                fecha = nov.get('fecha')
                if isinstance(fecha, date):
                    fecha = fecha.strftime("%d/%m/%Y")
                
                self.partes.append('<tr>')
                self.partes.append(f'<td>{fecha}</td>')
                self.partes.append(f'<td>{nov.get("nombre_regla", nov.get("regla_salarial", ""))}</td>')
                self.partes.append(f'<td>{nov.get("origen", "")}</td>')
                self.partes.append(f'<td class="text-end">{self.service._fmt_money(nov.get("monto", 0))}</td>')
                self.partes.append('</tr>')
            
            self.partes.append('</tbody></table>')
            self.partes.append('</div>')
            self.partes.append('</div>')
    
    def add_provisiones(self, provisiones: Dict[str, Any]):
        """Añade información de provisiones"""
        if provisiones:
            self.partes.append(
                '<div class="mt-3 p-3 bg-light rounded shadow-sm border border-info">'
                f'<h6 class="mb-2 text-info">{_("Provisiones")}:</h6>'
                f'<div><strong>{_("Valor anterior")}:</strong> {self.service._fmt_money(provisiones.get("valor_anterior", 0))}</div>'
                f'<div><strong>{_("Valor actual")}:</strong> {self.service._fmt_money(provisiones.get("valor_actual", 0))}</div>'
                f'<div><strong>{_("Diferencia")}:</strong> {self.service._fmt_money(provisiones.get("diferencia", 0))}</div>'
                f'<div><strong>{_("Estado")}:</strong> {provisiones.get("estado", "")}</div>'
                '</div>'
            )
    
    def add_formulas(self, formulas: List[Dict[str, str]]):
        """Añade información de fórmulas de cálculo"""
        if formulas and len(formulas) > 0:
            self.partes.append('<div class="mt-3 mb-3 p-2 bg-white rounded shadow-sm border border-info">')
            self.partes.append(f'<h6 class="mb-2 text-info">{_("Detalle de los Cálculos")}:</h6>')
            
            self.partes.append('<div class="table-responsive">')
            self.partes.append('<table class="table table-sm table-hover">')
            self.partes.append('<tbody>')
            
            for formula in formulas:
                self.partes.append('<tr>')
                self.partes.append(f'<td style="width: 30%;"><strong>{formula.get("concepto", "")}</strong></td>')
                self.partes.append(f'<td class="text-monospace small">{formula.get("formula", "")}</td>')
                self.partes.append('</tr>')
            
            self.partes.append('</tbody></table>')
            self.partes.append('</div>')
            self.partes.append('</div>')
    
    
    def add_resultado(self, base_liquidacion: Decimal, base_diaria: Decimal, valor_prestacion: Decimal):
        """Añade información de resultado final"""
        self.partes.append('<div class="mt-3 p-3 bg-light rounded shadow-sm border border-success">')
        self.partes.append(f'<h6 class="mb-2 text-success">{_("Resultado Final")}:</h6>')
        
        if base_liquidacion > 0:
            self.partes.append(
                f'<div><strong>{_("Base de liquidación")}:</strong> '
                f'<span class="text-success fw-bold">{self.service._fmt_money(base_liquidacion)}</span></div>'
            )
        
        if base_diaria > 0:
            self.partes.append(
                f'<div><strong>{_("Base diaria")}:</strong> '
                f'<span class="text-success fw-bold">{self.service._fmt_money(base_diaria)}</span></div>'
            )
        
        if valor_prestacion > 0:
            self.partes.append(
                f'<div><strong>{_("Valor")} {self.nombre_prestacion.lower()}:</strong> '
                f'<span class="text-success fw-bold">{self.service._fmt_money(valor_prestacion)}</span></div>'
            )
        
        self.partes.append('</div>')
    
    def generate(self) -> str:
        """Genera el HTML completo"""
        self.partes.append('</div>')
        return ''.join(self.partes)
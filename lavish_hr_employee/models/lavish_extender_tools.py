from datetime import date, datetime, timedelta
from typing import Dict, List, Tuple, Any, Optional, Union, Callable, Set, Iterable,Mapping, Sequence
from collections import defaultdict, Counter
from dateutil.relativedelta import relativedelta
import calendar
import time
import json
import logging
from decimal import Decimal, getcontext, ROUND_DOWN, ROUND_HALF_UP, ROUND_UP, ROUND_HALF_EVEN, InvalidOperation
from itertools import groupby
from operator import itemgetter
from odoo import api, models, fields, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools.safe_eval import safe_eval
from odoo.tools import float_is_zero, float_round, format_date, formatLang, frozendict, date_utils
import base64
import io
import xlsxwriter

_logger = logging.getLogger(__name__)
def json_serial(obj):
    """
    Función auxiliar extendida para serializar objetos de Odoo y tipos básicos.
    Maneja fechas, decimales, objetos de Odoo y objetos genéricos con __dict__.
    """
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    elif isinstance(obj, Decimal):
        return float(obj)
    elif hasattr(obj, '_name'):  
        return {
            'id': getattr(obj, 'id', None),
            'name': getattr(obj, 'name', ''),
            'model': getattr(obj, '_name', '')
        }
    elif hasattr(obj, 'name') and callable(getattr(obj, 'name_get', None)):
        return dict(obj.name_get()[0]) if obj.name_get() else str(obj)
    elif hasattr(obj, '__dict__'):
        return {k: v for k, v in obj.__dict__.items() 
                if not k.startswith('_') and not callable(v)}
    raise TypeError(f"Type {type(obj)} not serializable")
# --- Constants and Precision Settings ---
DAYS_YEAR = Decimal('360')
DAYS_YEAR_NATURAL = Decimal('365')
DAYS_MONTH = Decimal('30')
PRECISION_TECHNICAL = 10
PRECISION_DISPLAY = 0
DATETIME_MIN = datetime.min.time()
DATETIME_MAX = datetime.max.time()
HOURS_PER_DAY = Decimal('8')
getcontext().prec = 12
# --- Withholding Tax Table ---
tabla_retencion = [
    (Decimal('0'), Decimal('95'), Decimal('0'), Decimal('0'), Decimal('0')),
    (Decimal('95'), Decimal('150'), Decimal('19'), Decimal('95'), Decimal('0')),
    (Decimal('150'), Decimal('360'), Decimal('28'), Decimal('150'), Decimal('10')),
    (Decimal('360'), Decimal('640'), Decimal('33'), Decimal('360'), Decimal('69')),
    (Decimal('640'), Decimal('945'), Decimal('35'), Decimal('640'), Decimal('162')),
    (Decimal('945'), Decimal('2300'), Decimal('37'), Decimal('945'), Decimal('268')),
    (Decimal('2300'), Decimal('Infinity'), Decimal('39'), Decimal('2300'), Decimal('770'))
]

class LavishToolsNomina(models.AbstractModel):
    """
    Optimized service for payroll calculation tools.
    
    This class provides comprehensive calculations for payroll processes,
    including rule totalization, category summation, day calculations,
    absence management, and social benefits computation.
    """
    _name = "lavish.tools.nomina"
    _description = "Lavish Tools for Payroll Calculations"

    # ======================== MAIN PUBLIC INTERFACE METHODS ========================

    def totalizar_reglas(
        self,
        localdict: Dict[str, Any],
        codigos_regla: Optional[Union[str, List[str]]] = None,
        filtros: Optional[Dict[str, Any]] = None,
        periodos: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Totalizes rule values according to specified criteria.
        
        This function aggregates values from salary rules that match the given filters
        across the specified periods. It supports filtering by code, value thresholds,
        and custom criteria.
        
        Parameters:
            localdict: Local dictionary with payroll data
            codigos_regla: Rule code or list of rule codes to totalize (None for all)
            filtros: Filters to apply (e.g., {'base_field': 'base_prima', 'min_valor': 0})
            periodos: Periods to include ('current_month', 'before_month', 'prima', 'cesantias', 'multi')
                      Default: ['current_month', 'multi']
        
        Returns:
            Dict with results containing:
                - 'total': Sum of all matching rule values
                - 'cantidad': Sum of quantities for matching rules
                - 'reglas_procesadas': List of processed rule codes
                - 'total_por_regla': Dictionary of totals per rule
                - 'cantidad_por_regla': Dictionary of quantities per rule
        """
        if periodos is None:
            periodos = ['current_month', 'multi']

        if filtros is None:
            filtros = {}

        return self._process_rules_totalization(localdict, codigos_regla, filtros, periodos)

    def totalizar_categorias(
        self,
        localdict: Dict[str, Any],
        categorias: Optional[Union[str, List[str]]] = None,
        excluir: Optional[Union[str, List[str]]] = None,
        periodos: Optional[List[str]] = None,
        incluir_subcategorias: bool = True
    ) -> Dict[str, Any]:
        """
        Totalizes values grouped by categories.
        
        This function aggregates payroll values by their salary rule categories,
        respecting the category hierarchy. It supports including/excluding specific 
        categories and their subcategories.
        
        Parameters:
            localdict: Local dictionary with payroll data
            categorias: Category or list of categories to include (None for all)
            excluir: Category or list of categories to exclude
            periodos: Periods to include ('current_month', 'before_month', 'prima', 'cesantias', 'multi')
                      Default: ['current_month', 'multi']
            incluir_subcategorias: Automatically include subcategories
        
        Returns:
            Dict with results containing:
                - 'total': Sum of all matching category values
                - 'total_por_categoria': Dictionary of totals per category
                - 'categorias_procesadas': List of processed categories
        """
        if periodos is None:
            periodos = ['current_month', 'multi']

        return self._process_categories_totalization(
            localdict, categorias, excluir, periodos, incluir_subcategorias
        )

    def calcular_dias(
        self,
        localdict: Dict[str, Any],
        ajustes: Optional[Dict[str, Any]] = None
    ) -> Dict[str, int]:
        """
        Calculates different types of days for the payroll period using worked_days.
        
        This function computes worked days, absences, holidays, and effective days
        based on the payroll period information. It can apply specific adjustments
        to customize the calculation.
        
        Parameters:
            localdict: Local dictionary with payroll data. Must contain 'worked_days'.
            ajustes: Specific adjustments for calculation (e.g., {'excluir_tipo': ['LEAVE100']})
        
        Returns:
            Dict with calculated days by type:
                - 'trabajados': Worked days
                - 'ausencias': Absence days
                - 'festivos': Holiday days
                - 'domingos': Sunday days
                - 'efectivos': Effective days
                - 'total': Total days
                - 'habiles': Business days
                - 'ausencias_detalle': Detailed absence information (if available)
        """
        return self._calculate_days(localdict, ajustes or {})

    def dias_entre_fechas(
        self,
        fecha_inicio: date,
        fecha_fin: date,
        metodo: str = 'exacto',
        ajustes: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        Calculates days between two dates according to specified method.
        
        This function supports different day counting methods including 
        exact calendar days, commercial 30/360, and customized approaches.
        
        Parameters:
            fecha_inicio: Start date
            fecha_fin: End date
            metodo: Calculation method ('exacto', '30_360', 'comercial')
            ajustes: Specific adjustments to the method (e.g., {'ajustar_ultimo_dia': True/False})
        
        Returns:
            Number of calculated days (difference + 1 to include both ends if 'exacto',
            or difference based on 30/360)
        """
        if not isinstance(fecha_inicio, date) or not isinstance(fecha_fin, date):
            raise ValueError("Start and end dates must be date objects.")

        if fecha_inicio > fecha_fin:
            return 0

        return self._calculate_days_between_dates(fecha_inicio, fecha_fin, metodo, ajustes or {})

    def obtener_ausencias(
        self,
        localdict: Dict[str, Any],
        por_tipo: bool = True,
        filtros: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Gets detailed information of absences for the payroll period.
        
        This function extracts and processes absence records, supporting grouping
        by type and filtering based on various criteria.
        
        Parameters:
            localdict: Local dictionary with payroll data.
            por_tipo: If True, groups absences by type (code).
                     If False, returns a flat list of all absences.
            filtros: Filters to apply to detailed absences.
                Examples:
                - afecta_prestaciones: bool (True to get only those that affect benefits)
                - solo_tipo: str (code of absence type to get)
                - solo_periodo: dict {'fecha_inicio': date, 'fecha_fin': date}
        
        Returns:
            Dict with absence information:
                - 'total_dias': Total absence days
                - 'detalle_disponible': Whether detailed information is available
                - 'por_tipo': Dict of absences by type (if por_tipo=True)
                - 'ausencias': List of absences (if por_tipo=False)
        """
        return self._get_absences(localdict, por_tipo, filtros or {})

    def obtener_conceptos(
        self,
        localdict: Dict[str, Any],
        filtros: Optional[Dict[str, Any]] = None,
        agrupar: Optional[str] = None,
        periodos: Optional[List[str]] = None
    ) -> Union[List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
        """
        Gets list of concepts (salary rules) with values and details,
        applying filters and optionally grouping.
        
        This function extracts and processes salary rule data, supporting
        comprehensive filtering, sorting, and grouping mechanisms.
        
        Parameters:
            localdict: Local dictionary with payroll data.
            filtros: Filters for concepts.
                Examples:
                - categoria: str or List[str]
                - base_campo: str (e.g., 'base_prima')
                - incluir_ceros: bool (default: False)
                - signo: str ('positivo', 'negativo')
                - min_valor: float
                - max_valor: float
                - ordenar_por: str ('codigo', 'valor', 'categoria') (default: 'codigo')
            agrupar: Grouping criteria ('categoria', 'signo', None).
            periodos: Periods to include ('current_month', 'before_month', 'prima', 'cesantias', 'multi').
                      Default: ['current_month', 'multi']
        
        Returns:
            List of concept dictionaries or dictionary grouped by criteria.
            Each concept includes: 'codigo', 'nombre', 'total', 'cantidad',
            'categoria', 'es_devengo', 'es_deduccion', and active 'base_*' fields.
        """
        if periodos is None:
            periodos = ['current_month', 'multi']

        return self._get_concepts(localdict, filtros or {}, agrupar, periodos)

    def obtener_totales(
        self,
        localdict: Dict[str, Any],
        filtros: Optional[Dict[str, Any]] = None
    ) -> Dict[str, float]:
        """
        Gets grouped totals (earnings, deductions, net) from payroll,
        applying optional filters.
        
        This function computes summarized financial totals for the payroll,
        with support for filtering by period, categories, and codes.
        
        Parameters:
            localdict: Local dictionary with payroll data.
            filtros: Filters to apply before totalizing.
                Examples:
                - periodo: str (e.g., 'current_month', 'multi', 'prima')
                - incluir_multi: bool (default: True if periodo is 'current_month')
                - excluir_categorias: List[str]
                - excluir_codigos: List[str]
        
        Returns:
            Dict with calculated totals:
                - 'devengos': Total earnings
                - 'deducciones': Total deductions (absolute value)
                - 'neto': Net amount (earnings + deductions)
                - 'conceptos_devengos': Count of earnings concepts
                - 'conceptos_deducciones': Count of deduction concepts
        """
        return self._calculate_totals(localdict, filtros or {})

    def extraer_valor(
        self,
        localdict: Dict[str, Any],
        codigo: str,
        periodo: str = 'current_month',
        campo: str = 'total',
        default: Any = 0.0
    ) -> Any:
        """
        Extracts a specific value ('total', 'cantidad', 'tasa', 'valor') from a concept
        in a determined period ('current_month', 'before_month', 'prima', 'cesantias', 'multi').
        
        This function provides a direct way to access specific fields from
        salary rules in various payroll periods.
        
        Parameters:
            localdict: Local dictionary with payroll data.
            codigo: Concept code (salary rule).
            periodo: Period to extract value from ('current_month', 'multi', etc.).
            campo: Field to extract ('total', 'cantidad', 'tasa', 'valor').
                   'tasa' looks for 'rate', 'valor' looks for 'amount'.
            default: Default value if not found.
        
        Returns:
            Extracted value or default value.
        """
        return self._extract_value(localdict, codigo, periodo, campo, default)

    def proyectar_nomina(
        self,
        localdict: Dict[str, Any],
        dias_trabajados: int,
        dias_proyectar: Optional[int] = None,
        conceptos_proyectar: Optional[List[str]] = None,
        periodo_base: str = 'current_month'
    ) -> Dict[str, Any]:
        """
        Projects payroll values for additional days based on a base period.
        
        This function calculates projected values for salary concepts by
        extrapolating from existing worked days to a target number of days.
        
        Parameters:
            localdict: Local dictionary with payroll data.
            dias_trabajados: Days already worked in base period.
            dias_proyectar: Days to project (None = until completing 30).
            conceptos_proyectar: List of rule codes to project (None = try to detect).
            periodo_base: Period ('current_month', 'multi') from which to take current values.
        
        Returns:
            Dict with calculated projection:
                - Details by concept
                - Total values
                - Projected IBC
                - Error information if day configuration is invalid
        """
        if dias_trabajados <= 0:
            return {
                'error': 'Worked days must be greater than zero to project.',
                'dias_trabajados': dias_trabajados,
                'dias_proyectar': dias_proyectar
            }

        return self._project_payroll(localdict, dias_trabajados, dias_proyectar, conceptos_proyectar, periodo_base)

    def calcular_base_prestaciones(
        self,
        localdict: Dict[str, Any],
        tipo_prestacion: str,
        fecha_inicio: Optional[date] = None,
        fecha_fin: Optional[date] = None,
        periodos_conceptos: Optional[List[str]] = None,
        metodo_dias: str = 'comercial'
    ) -> Dict[str, Any]:
        """
        Calculates the base and value for a specific social benefit (prima, cesantías, etc.).
        
        This function computes benefit bases and values according to Colombian labor
        regulations, supporting various benefit types and calculation methods.
        
        Parameters:
            localdict: Local dictionary with payroll data.
            tipo_prestacion: Type ('prima', 'cesantias', 'vacaciones', 'intereses').
            fecha_inicio: Initial date of causation period (None for auto-detect).
            fecha_fin: Final date of causation period (None for auto-detect).
            periodos_conceptos: Periods ('current_month', 'multi', 'prima', etc.) to consider
                               for summing concepts that form the base.
                               Default: ['current_month', 'multi'] and the benefit specific one.
            metodo_dias: Method for calculating days of period ('exacto', 'comercial').
        
        Returns:
            Dict with calculated base and details:
                - 'total_base': Total base amount
                - 'dias_periodo': Total days in period
                - 'dias_suspension': Suspension days
                - 'dias_efectivos': Effective days
                - 'conceptos_base': Base concepts
                - 'valor_prestacion': Benefit value
                - Error information if benefit type is invalid
        """
        prestacion_config = {
            'prima': {'campo_base': 'base_prima', 'periodo_logico': 'prima'},
            'cesantias': {'campo_base': 'base_cesantias', 'periodo_logico': 'cesantias'},
            'vacaciones': {'campo_base': 'base_vacaciones', 'periodo_logico': 'current_month'},
            'intereses': {'campo_base': 'base_cesantias', 'periodo_logico': 'cesantias'}
        }

        if tipo_prestacion not in prestacion_config:
            return {
                'error': f"Invalid benefit type: {tipo_prestacion}",
                'tipos_validos': list(prestacion_config.keys())
            }

        return self._calculate_benefits_base(
            localdict, tipo_prestacion, fecha_inicio, fecha_fin, 
            periodos_conceptos, metodo_dias
        )

    # ======================== MID LEVEL CALCULATION METHODS ========================

    def _process_rules_totalization(
        self,
        localdict: Dict[str, Any],
        codigos_regla: Optional[Union[str, List[str]]],
        filtros: Dict[str, Any],
        periodos: List[str]
    ) -> Dict[str, Any]:
        """
        Processes rule totalization according to the given parameters.
        
        This is a mid-level implementation of the totalizar_reglas method.
        """
        payslip_lines = localdict.get('payslip_lines', {})
        rules_multi = localdict.get('rules_multi', {})
        
        if codigos_regla is None:
            codigos = list(set(payslip_lines.keys()) | set(rules_multi.keys()))
        else:
            codigos = [codigos_regla] if isinstance(codigos_regla, str) else codigos_regla

        resultado = {
            'total': Decimal('0.0'),
            'cantidad': Decimal('0.0'),
            'reglas_procesadas': [],
            'total_por_regla': defaultdict(Decimal),
            'cantidad_por_regla': defaultdict(Decimal)
        }

        # Process payslip_lines for specified periods
        for codigo in codigos:
            if codigo not in payslip_lines:
                continue

            line_data = payslip_lines[codigo]
            for periodo in periodos:
                if periodo != 'multi' and periodo in line_data:
                    period_data = line_data[periodo]
                    rule = period_data.get('rule')

                    if not self._rule_meets_filters(rule, filtros):
                        continue

                    total_periodo = Decimal(str(period_data.get('total', 0.0)))
                    entries = period_data.get('entries', [])
                    cantidad_periodo = sum(Decimal(str(e.get('quantity', 0.0))) for e in entries)

                    if 'min_valor' in filtros and total_periodo < Decimal(str(filtros['min_valor'])): 
                        continue
                    if 'max_valor' in filtros and total_periodo > Decimal(str(filtros['max_valor'])): 
                        continue

                    resultado['total'] += total_periodo
                    resultado['cantidad'] += cantidad_periodo
                    resultado['total_por_regla'][codigo] += total_periodo
                    resultado['cantidad_por_regla'][codigo] += cantidad_periodo

                    if codigo not in resultado['reglas_procesadas']:
                        resultado['reglas_procesadas'].append(codigo)

        # Process rules_multi if included
        if 'multi' in periodos:
            for codigo in codigos:
                if codigo in rules_multi and 'current' in rules_multi[codigo]:
                    multi_data = rules_multi[codigo]['current']
                    rule = multi_data.get('object')

                    if not self._rule_meets_filters(rule, filtros):
                        continue

                    total_multi = Decimal(str(multi_data.get('total', 0.0)))
                    cantidad_multi = Decimal(str(multi_data.get('quantity', 0.0)))

                    if 'min_valor' in filtros and total_multi < Decimal(str(filtros['min_valor'])): 
                        continue
                    if 'max_valor' in filtros and total_multi > Decimal(str(filtros['max_valor'])): 
                        continue

                    resultado['total'] += total_multi
                    resultado['cantidad'] += cantidad_multi
                    resultado['total_por_regla'][codigo] += total_multi
                    resultado['cantidad_por_regla'][codigo] += cantidad_multi

                    if codigo not in resultado['reglas_procesadas']:
                        resultado['reglas_procesadas'].append(codigo)

        # Convert Decimal to float for final result
        return {
            'total': float(resultado['total']),
            'cantidad': float(resultado['cantidad']),
            'reglas_procesadas': resultado['reglas_procesadas'],
            'total_por_regla': {k: float(v) for k, v in resultado['total_por_regla'].items()},
            'cantidad_por_regla': {k: float(v) for k, v in resultado['cantidad_por_regla'].items()}
        }

    def _process_categories_totalization(
        self,
        localdict: Dict[str, Any],
        categorias: Optional[Union[str, List[str]]],
        excluir: Optional[Union[str, List[str]]],
        periodos: List[str],
        incluir_subcategorias: bool
    ) -> Dict[str, Any]:
        """
        Processes category totalization according to the given parameters.
        
        This is a mid-level implementation of the totalizar_categorias method.
        """
        cats_incluir = [categorias] if isinstance(categorias, str) else (categorias or [])
        cats_excluir = [excluir] if isinstance(excluir, str) else (excluir or [])

        resultado = {
            'total': Decimal('0.0'),
            'total_por_categoria': defaultdict(Decimal),
            'categorias_procesadas': set()
        }

        # Collect all rules with their categories and totals by period
        todas_reglas_info = self._collect_all_rules_info(localdict, periodos)
        
        # Build category hierarchy
        jerarquia = self._build_optimized_category_hierarchy(todas_reglas_info)
        
        # Determine target categories
        categorias_objetivo = self._determine_target_categories(
            todas_reglas_info, cats_incluir, cats_excluir,
            jerarquia, incluir_subcategorias
        )
        
        # Sum values by category
        for code, info in todas_reglas_info.items():
            cat_code = info['category_code']
            if cat_code in categorias_objetivo:
                total = info['total']
                resultado['total'] += total
                resultado['total_por_categoria'][cat_code] += total
                resultado['categorias_procesadas'].add(cat_code)

        # Convert set to list and defaultdict to dict for easier serialization
        categorias_procesadas = sorted(list(resultado['categorias_procesadas']))
        total_por_categoria = {k: float(v) for k, v in resultado['total_por_categoria'].items()}
        
        return {
            'total': float(resultado['total']),
            'total_por_categoria': total_por_categoria,
            'categorias_procesadas': categorias_procesadas
        }

    def _calculate_days(
        self,
        localdict: Dict[str, Any],
        ajustes: Dict[str, Any]
    ) -> Dict[str, int]:
        """
        Calculates different types of days for the payroll period.
        
        This is a mid-level implementation of the calcular_dias method.
        """
        dias_info = {
            'trabajados': 0, 'ausencias': 0, 'festivos': 0, 'domingos': 0,
            'efectivos': 0, 'total':0, 'habiles': 0
        }

        worked_days_dict = localdict.get('worked_days', {}).dict

        if not worked_days_dict:
            _logger.warning("'worked_days' not found in localdict for calcular_dias.")
            dias_info['trabajados'] = localdict.get('trabajados', 0)
            dias_info['ausencias'] = localdict.get('ausencias', 0)
            dias_info['festivos'] = localdict.get('festivos', 0)
            dias_info['domingos'] = localdict.get('domingos', 0)
        else:
            # Sum days by type from worked_days
            for code, wd_line in worked_days_dict.items():
                days = wd_line.number_of_days if hasattr(wd_line, 'number_of_days') else 0
                if not days: continue

                if code == 'WORK100':
                    dias_info['trabajados'] += days
                elif code.startswith('LEAVE'):
                    dias_info['ausencias'] += days
                elif code == 'FEST':
                    dias_info['festivos'] += days
                elif code == 'DOM':
                    dias_info['domingos'] += days

        # Calculate effective days and totals
        dias_info['efectivos'] = dias_info['trabajados']
        dias_info['total'] = dias_info['trabajados'] + dias_info['ausencias'] + dias_info['festivos'] + dias_info['domingos']
        dias_info['habiles'] = dias_info['trabajados'] + (0 if ajustes.get('excluir_festivos', False) else dias_info['festivos'])

        # Check if there are detailed absences
        if self._has_detailed_absences(localdict):
            absence_details = self._detail_absences(localdict, filtros=ajustes.get('filtros_ausencias'))
            if absence_details:
                dias_info['ausencias_detalle'] = absence_details

        return dias_info

    def _calculate_days_between_dates(
        self,
        fecha_inicio: date,
        fecha_fin: date,
        metodo: str,
        ajustes: Dict[str, Any]
    ) -> int:
        """
        Calculates days between two dates according to specified method.
        
        This is a mid-level implementation supporting the dias_entre_fechas method.
        """
        if metodo == 'exacto':
            return (fecha_fin - fecha_inicio).days + 1
        elif metodo == '30_360' or metodo == 'comercial':
            return self._days360(fecha_inicio, fecha_fin, method_eu=ajustes.get('method_eu', True))
        else:
            _logger.warning(f"Unrecognized day calculation method: {metodo}. Using 'exacto'.")
            return (fecha_fin - fecha_inicio).days + 1

    def _get_absences(
        self,
        localdict: Dict[str, Any],
        por_tipo: bool,
        filtros: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Gets detailed information of absences for the payroll period.
        
        This is a mid-level implementation of the obtener_ausencias method.
        """
        detailed_absences = self._detail_absences(localdict, filtros)

        if not detailed_absences:
            return {
                'total_dias': localdict.get('ausencias', 0),
                'detalle_disponible': False
            }

        total_dias = sum(Decimal(str(info['dias'])) for info in detailed_absences.values())

        resultado = {
            'total_dias': float(total_dias),
            'detalle_disponible': True,
            'tipos_ausencia': list(detailed_absences.keys()),
            'cantidad_tipos': len(detailed_absences)
        }

        if por_tipo:
            resultado['por_tipo'] = detailed_absences
        else:
            lista_ausencias = []
            for tipo, info in detailed_absences.items():
                for ausencia in info.get('ausencias', []):
                    ausencia_item = ausencia.copy()
                    ausencia_item['tipo'] = tipo
                    ausencia_item['nombre_tipo'] = info.get('nombre', tipo)
                    lista_ausencias.append(ausencia_item)

            resultado['ausencias'] = sorted(
                lista_ausencias,
                key=lambda x: x.get('fecha_inicio', date.today())
            )

        return resultado

    def _get_concepts(
        self,
        localdict: Dict[str, Any],
        filtros: Dict[str, Any],
        agrupar: Optional[str],
        periodos: List[str]
    ) -> Union[List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
        """
        Gets list of concepts (salary rules) with values and details.
        
        This is a mid-level implementation of the obtener_conceptos method.
        """
        incluir_ceros = filtros.get('incluir_ceros', False)
        conceptos_info = self._collect_concepts_info(localdict, periodos)
        
        conceptos_filtrados = []
        for codigo, info in conceptos_info.items():
            total = info['total']
            categoria = info['categoria']
            rule_object = info['rule_object']

            if not incluir_ceros and float_is_zero(float(total), precision_digits=2):
                continue

            if not self._concept_meets_filters(codigo, total, categoria, rule_object, filtros):
                continue

            concepto_final = {
                'codigo': codigo,
                'nombre': info['nombre'] or codigo,
                'total': float(total),
                'cantidad': float(info['cantidad']),
                'categoria': categoria,
                'es_devengo': total >= 0,
                'es_deduccion': total < 0,
                **info['base_fields']
            }
            conceptos_filtrados.append(concepto_final)

        ordenar_por = filtros.get('ordenar_por', 'codigo')
        reverse_sort = filtros.get('orden_desc', False)

        if ordenar_por == 'valor':
            conceptos_filtrados.sort(key=lambda x: abs(x['total']), reverse=reverse_sort)
        elif ordenar_por == 'categoria':
            conceptos_filtrados.sort(key=lambda x: (x['categoria'] or '', x['codigo']), reverse=reverse_sort)
        else:  # default: sort by code
            conceptos_filtrados.sort(key=lambda x: x['codigo'], reverse=reverse_sort)

        if agrupar:
            resultado_agrupado = defaultdict(list)
            if agrupar == 'categoria':
                for concepto in conceptos_filtrados:
                    grupo = concepto['categoria'] or 'SIN_CATEGORIA'
                    resultado_agrupado[grupo].append(concepto)
            elif agrupar == 'signo':
                for concepto in conceptos_filtrados:
                    grupo = 'devengos' if concepto['es_devengo'] else 'deducciones'
                    resultado_agrupado[grupo].append(concepto)
            return dict(resultado_agrupado)

        return conceptos_filtrados

    def _calculate_totals(
        self,
        localdict: Dict[str, Any],
        filtros: Dict[str, Any]
    ) -> Dict[str, float]:
        """
        Calculates payroll totals with filtering options.
        
        This is a mid-level implementation of the obtener_totales method.
        """
        periodo_base = filtros.pop('periodo', 'current_month')
        periodos_a_incluir = [periodo_base]
        if filtros.pop('incluir_multi', periodo_base == 'current_month'):
            if 'multi' not in periodos_a_incluir:
                periodos_a_incluir.append('multi')

        excluir_codigos = filtros.pop('excluir_codigos', [])

        filtros_internos = {**filtros, 'incluir_ceros': False}
        conceptos = self.obtener_conceptos(localdict, filtros=filtros_internos, periodos=periodos_a_incluir)

        total_devengos = Decimal('0.0')
        total_deducciones = Decimal('0.0')
        
        for c in conceptos:
            if c['codigo'] not in excluir_codigos:
                valor = Decimal(str(c['total']))
                if valor > 0:
                    total_devengos += valor
                else:
                    total_deducciones += valor

        neto = total_devengos + total_deducciones

        return {
            'devengos': float(total_devengos),
            'deducciones': float(abs(total_deducciones)),
            'neto': float(neto),
            'conceptos_devengos': len([c for c in conceptos if c['total'] > 0 and c['codigo'] not in excluir_codigos]),
            'conceptos_deducciones': len([c for c in conceptos if c['total'] < 0 and c['codigo'] not in excluir_codigos])
        }

    def _extract_value(
        self,
        localdict: Dict[str, Any],
        codigo: str,
        periodo: str,
        campo: str,
        default: Any
    ) -> Any:
        """
        Extracts a specific value from a concept in a determined period.
        
        This is a mid-level implementation of the extraer_valor method.
        """
        valor_encontrado = None
        encontrado = False

        campo_map = {
            'total': 'total',
            'cantidad': 'quantity', 'quantity': 'quantity',
            'tasa': 'rate', 'rate': 'rate',
            'valor': 'amount', 'amount': 'amount'
        }
        campo_buscar = campo_map.get(campo, campo)

        if periodo == 'multi' or periodo == 'current_month':
            rules_multi = localdict.get('rules_multi', {})
            if codigo in rules_multi and 'current' in rules_multi[codigo]:
                multi_data = rules_multi[codigo]['current']
                if campo_buscar in multi_data:
                    valor_encontrado = multi_data[campo_buscar]
                    encontrado = True

        if not encontrado and periodo != 'multi':
            payslip_lines = localdict.get('payslip_lines', {})
            if codigo in payslip_lines and periodo in payslip_lines[codigo]:
                period_data = payslip_lines[codigo][periodo]
                encontrado = True

                if campo_buscar == 'total':
                    valor_encontrado = period_data.get('total', default)
                else:
                    entries = period_data.get('entries', [])
                    if entries:
                        if campo_buscar == 'quantity':
                            valor_encontrado = sum(e.get('quantity', 0.0) for e in entries)
                        elif campo_buscar in ['rate', 'amount']:
                            valor_encontrado = entries[0].get(campo_buscar, default)
                        else:
                            valor_encontrado = entries[0].get(campo_buscar, default)
                    else:
                        encontrado = False

        return valor_encontrado if encontrado else default

    def _project_payroll(
        self,
        localdict: Dict[str, Any],
        dias_trabajados: int,
        dias_proyectar: Optional[int],
        conceptos_proyectar: Optional[List[str]],
        periodo_base: str
    ) -> Dict[str, Any]:
        """
        Projects payroll values for additional days.
        
        This is a mid-level implementation of the proyectar_nomina method.
        """
        if dias_proyectar is None:
            dias_proyectar = 30 - dias_trabajados

        if dias_proyectar < 0:
            _logger.warning(f"Days to project is negative ({dias_proyectar}), no projection will be made.")
            dias_proyectar = 0

        if conceptos_proyectar is None:
            conceptos_proyectar = self._determine_projectable_concepts(localdict, periodo_base)
            
            if not conceptos_proyectar:
                conceptos_proyectar = ['BASIC', 'AUX_TRANSP']

        factor_proyeccion = Decimal(str(dias_proyectar)) / Decimal(str(dias_trabajados)) if dias_proyectar > 0 else Decimal('0')

        resultado = {
            'dias_trabajados': dias_trabajados,
            'dias_proyectar': dias_proyectar,
            'dias_totales_proyectados': dias_trabajados + dias_proyectar,
            'factor_proyeccion': float(factor_proyeccion),
            'proyectados': {},
            'no_proyectados': {},
            'total_actual': 0.0,
            'total_proyectado': 0.0,
            'total_completo': 0.0,
            'ibc_proyectado': 0.0
        }

        conceptos_actuales = self.obtener_conceptos(localdict, filtros={'incluir_ceros': True}, periodos=[periodo_base])
        
        total_actual_dec = Decimal('0.0')
        total_proyectado_dec = Decimal('0.0')
        total_completo_dec = Decimal('0.0')
        
        for concepto in conceptos_actuales:
            codigo = concepto['codigo']
            valor_actual = Decimal(str(concepto['total']))
            nombre = concepto['nombre']

            total_actual_dec += valor_actual

            if codigo in conceptos_proyectar and factor_proyeccion > 0:
                valor_proyectado = valor_actual * factor_proyeccion
                valor_completo = valor_actual + valor_proyectado

                resultado['proyectados'][codigo] = {
                    'nombre': nombre,
                    'valor_actual': float(valor_actual),
                    'valor_proyectado': float(valor_proyectado),
                    'valor_completo': float(valor_completo)
                }
                total_proyectado_dec += valor_proyectado
                total_completo_dec += valor_completo
            else:
                resultado['no_proyectados'][codigo] = {
                    'nombre': nombre,
                    'valor_actual': float(valor_actual),
                    'valor_completo': float(valor_actual)
                }
                total_completo_dec += valor_actual

        resultado['total_actual'] = float(total_actual_dec)
        resultado['total_proyectado'] = float(total_proyectado_dec)
        resultado['total_completo'] = float(total_completo_dec)

        resultado['ibc_proyectado'] = self._calculate_projected_ibc(
            localdict, float(total_completo_dec), dias_trabajados, dias_proyectar, conceptos_proyectar
        )

        return resultado

    def _calculate_benefits_base(
        self,
        localdict: Dict[str, Any],
        tipo_prestacion: str,
        fecha_inicio: Optional[date],
        fecha_fin: Optional[date],
        periodos_conceptos: Optional[List[str]],
        metodo_dias: str
    ) -> Dict[str, Any]:
        """
        Calculates the base and value for a specific social benefit.
        
        This is a mid-level implementation of the calcular_base_prestaciones method.
        """
        config = {
            'prima': {'campo_base': 'base_prima', 'periodo_logico': 'prima'},
            'cesantias': {'campo_base': 'base_cesantias', 'periodo_logico': 'cesantias'},
            'vacaciones': {'campo_base': 'base_vacaciones', 'periodo_logico': 'current_month'},
            'intereses': {'campo_base': 'base_cesantias', 'periodo_logico': 'cesantias'}
        }[tipo_prestacion]
        
        campo_base = config['campo_base']
        periodo_logico = config['periodo_logico']

        if fecha_inicio is None or fecha_fin is None:
            fechas = self._determine_benefit_dates(localdict, tipo_prestacion)
            fecha_inicio = fechas['fecha_inicio']
            fecha_fin = fechas['fecha_fin']
            if not fecha_inicio or not fecha_fin:
                return {'error': f"Could not determine dates for {tipo_prestacion}"}

        if periodos_conceptos is None:
            periodos_conceptos = ['current_month', 'multi', periodo_logico]
            periodos_conceptos = sorted(list(set(periodos_conceptos)))

        dias_periodo = self.dias_entre_fechas(fecha_inicio, fecha_fin, metodo_dias)

        resultado = {
            'tipo_prestacion': tipo_prestacion,
            'campo_base': campo_base,
            'fecha_inicio': fecha_inicio,
            'fecha_fin': fecha_fin,
            'dias_periodo': dias_periodo,
            'dias_suspension': 0,
            'dias_efectivos': dias_periodo,
            'conceptos_base': {},
            'total_base': 0.0,
            'valor_prestacion': 0.0,
            'ausencias_detalle': {}
        }

        ausencias_info = self.obtener_ausencias(
            localdict,
            por_tipo=True,
            filtros={'solo_periodo': {'fecha_inicio': fecha_inicio, 'fecha_fin': fecha_fin}}
        )
        resultado['ausencias_detalle'] = ausencias_info.get('por_tipo', {})

        dias_suspension = 0
        for tipo_ausencia, info_ausencia in resultado['ausencias_detalle'].items():
            descuenta_field = f"descuenta_{tipo_prestacion}"
            if info_ausencia.get(descuenta_field, False):
                dias_suspension += info_ausencia.get('dias', 0)

        dias_efectivos = max(0, resultado['dias_periodo'] - dias_suspension)
        resultado['dias_efectivos'] = dias_efectivos
        resultado['dias_suspension'] = dias_suspension

        if dias_efectivos <= 0:
            _logger.info(f"Base calculation {tipo_prestacion}: Effective days <= 0. Base and value will be 0.")
            return resultado

        filtros_base = {
            'base_campo': campo_base,
            'incluir_ceros': False
        }
        conceptos_base = self.obtener_conceptos(localdict, filtros=filtros_base, periodos=periodos_conceptos)

        total_base = Decimal('0.0')
        for concepto in conceptos_base:
            codigo = concepto['codigo']
            valor = Decimal(str(concepto['total']))
            resultado['conceptos_base'][codigo] = {
                'nombre': concepto['nombre'],
                'valor': float(valor)
            }
            total_base += valor

        resultado['total_base'] = float(total_base)

        getcontext().prec = 10
        dec_total_base = total_base
        dec_dias_efectivos = Decimal(str(dias_efectivos))
        dec_360 = Decimal('360')
        valor_prestacion_dec = Decimal('0.0')

        try:
            if tipo_prestacion == 'prima':
                valor_prestacion_dec = (dec_total_base * dec_dias_efectivos) / dec_360
            elif tipo_prestacion == 'cesantias':
                valor_prestacion_dec = (dec_total_base * dec_dias_efectivos) / dec_360
            elif tipo_prestacion == 'intereses':
                valor_cesantias_dec = (dec_total_base * dec_dias_efectivos) / dec_360
                valor_prestacion_dec = (valor_cesantias_dec * Decimal('0.12') * dec_dias_efectivos) / dec_360
            elif tipo_prestacion == 'vacaciones':
                valor_prestacion_dec = dec_total_base
                resultado['nota'] = "The returned value is the monthly base for vacations."

            # Round final result
            resultado['valor_prestacion'] = float(valor_prestacion_dec.quantize(Decimal('0.01')))

        except Exception as e:
            _logger.error(f"Error calculating value for {tipo_prestacion}: {e}")
            resultado['error_calculo'] = str(e)

        return resultado

    # ======================== LOW LEVEL UTILITY METHODS ========================

    def _rule_meets_filters(self, rule: Any, filtros: Dict[str, Any]) -> bool:
        """
        Verifies if a rule (hr.salary.rule object) meets the filters.
        """
        if not rule:
            return not any(k in filtros for k in ['base_field', 'categoria', 'custom_filter'])

        # Base field filter
        if 'base_field' in filtros and not getattr(rule, filtros['base_field'], False):
            return False

        # Category filter
        if 'categoria' in filtros:
            categorias_filtro = filtros['categoria']
            if not isinstance(categorias_filtro, list):
                categorias_filtro = [categorias_filtro]

            if not hasattr(rule, 'category_id') or not rule.category_id:
                return False

            if rule.category_id.code not in categorias_filtro:
                return False

        # Custom filter function
        if 'custom_filter' in filtros and callable(filtros['custom_filter']):
            if not filtros['custom_filter'](rule):
                return False

        return True

    def _concept_meets_filters(
        self,
        codigo: str,
        valor: Decimal,
        categoria: Optional[str],
        rule: Optional[Any],
        filtros: Dict[str, Any]
    ) -> bool:
        """
        Verifies if a concept (aggregated) meets the filters.
        """
        # Category filter (handles None)
        if 'categoria' in filtros:
            cat_filtro = filtros['categoria']
            cats_filtro_list = [cat_filtro] if isinstance(cat_filtro, str) else cat_filtro
            if categoria not in cats_filtro_list:
                return False

        # Base field filter (requires rule object)
        if 'base_campo' in filtros:
            if not rule or not getattr(rule, filtros['base_campo'], False):
                return False

        # Sign filter
        if 'signo' in filtros:
            signo_filtro = filtros['signo']
            if signo_filtro == 'positivo' and valor < 0:
                return False
            elif signo_filtro == 'negativo' and valor >= 0:
                return False
            elif signo_filtro not in ['positivo', 'negativo']:
                _logger.warning(f"Unrecognized 'signo' filter: {signo_filtro}")

        # Value range filter
        if 'min_valor' in filtros and valor < Decimal(str(filtros['min_valor'])):
            return False
        if 'max_valor' in filtros and valor > Decimal(str(filtros['max_valor'])):
            return False

        # Exclude specific codes
        if 'excluir_codigos' in filtros and codigo in filtros['excluir_codigos']:
            return False

        return True

    def _days360(self, start_date: date, end_date: date, method_eu: bool = True) -> int:
        """
        Computes number of days between two dates regarding all months
        as 30-day months.
        """
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

        if end_month == 2 and end_day >= 28:
            end_day = 30

        return (
            end_day + end_month * 30 + end_year * 360 -
            start_day - start_month * 30 - start_year * 360
        )

    def _has_detailed_absences(self, localdict: Dict[str, Any]) -> bool:
        """
        Verifies if the localdict has the necessary information to detail absences.
        """
        return bool(localdict.get('employee') and localdict.get('date_from') and localdict.get('date_to'))

    def _detail_absences(self, localdict: Dict[str, Any], filtros: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
        """
        Extracts absence details (hr.leave) that intersect with the payroll period,
        applying optional filters.
        """
        filtros = filtros or {}
        employee = localdict.get('employee')
        fecha_inicio_nomina = localdict.get('date_from')
        fecha_fin_nomina = localdict.get('date_to')

        if not employee or not fecha_inicio_nomina or not fecha_fin_nomina:
            return {}

        # Date filter for absence query
        filtro_fecha_inicio = filtros.get('solo_periodo', {}).get('fecha_inicio', fecha_inicio_nomina)
        filtro_fecha_fin = filtros.get('solo_periodo', {}).get('fecha_fin', fecha_fin_nomina)

        # Search validated absences that overlap with filtered period
        Leave = self.env['hr.leave']
        domain = [
            ('employee_id', '=', employee.id),
            ('state', '=', 'validate'),
            ('date_from', '<=', filtro_fecha_fin),
            ('date_to', '>=', filtro_fecha_inicio)
        ]
        
        # Add type filter if specified
        if 'solo_tipo' in filtros:
            leave_type = self.env['hr.leave.type'].search([('code', '=', filtros['solo_tipo'])], limit=1)
            if leave_type:
                domain.append(('holiday_status_id', '=', leave_type.id))
            else:
                _logger.warning(f"Absence type with code '{filtros['solo_tipo']}' not found.")
                return {}

        leaves = Leave.search(domain)
        if not leaves:
            return {}

        # Group by type and calculate days within original payroll period
        resultado = defaultdict(lambda: {
            'nombre': '', 'dias': 0, 'descuenta_prima': False,
            'descuenta_cesantias': False, 'descuenta_vacaciones': False,
            'descuenta_prestaciones': False, 'ausencias': []
        })

        for leave in leaves:
            leave_type = leave.holiday_status_id
            tipo_codigo = getattr(leave_type, 'code', f"LEAVE{leave_type.id}")

            # Check 'afecta_prestaciones' filter
            descuenta_alguna = (getattr(leave_type, 'descuenta_prima', False) or
                              getattr(leave_type, 'descuenta_cesantias', False) or
                              getattr(leave_type, 'descuenta_vacaciones', False))

            if filtros.get('afecta_prestaciones', False) and not descuenta_alguna:
                continue

            # Calculate effective days of absence WITHIN payroll period
            fecha_inicio_efectiva = max(leave.date_from.date(), fecha_inicio_nomina)
            fecha_fin_efectiva = min(leave.date_to.date(), fecha_fin_nomina)

            # Ensure effective range is valid
            if fecha_inicio_efectiva > fecha_fin_efectiva:
                continue

            # Calculate days using exact method for real duration within period
            dias_en_periodo = (fecha_fin_efectiva - fecha_inicio_efectiva).days + 1

            # Initialize type info if first time
            if tipo_codigo not in resultado:
                resultado[tipo_codigo]['nombre'] = leave_type.name
                resultado[tipo_codigo]['descuenta_prima'] = getattr(leave_type, 'descuenta_prima', False)
                resultado[tipo_codigo]['descuenta_cesantias'] = getattr(leave_type, 'descuenta_cesantias', False)
                resultado[tipo_codigo]['descuenta_vacaciones'] = getattr(leave_type, 'descuenta_vacaciones', False)
                resultado[tipo_codigo]['descuenta_prestaciones'] = descuenta_alguna

            # Accumulate days
            resultado[tipo_codigo]['dias'] += dias_en_periodo

            # Add absence detail (with effective dates in period)
            resultado[tipo_codigo]['ausencias'].append({
                'id': leave.id,
                'fecha_inicio_original': leave.date_from.date(),
                'fecha_fin_original': leave.date_to.date(),
                'fecha_inicio_efectiva': fecha_inicio_efectiva,
                'fecha_fin_efectiva': fecha_fin_efectiva,
                'dias_en_periodo': dias_en_periodo,
                'nombre': leave.name or leave_type.name
            })

        return dict(resultado)

    def _determine_benefit_dates(
        self,
        localdict: Dict[str, Any],
        tipo_prestacion: str
    ) -> Dict[str, Optional[date]]:
        """
        Determines start and end dates for calculating social benefits.
        """
        fecha_inicio = None
        fecha_fin = localdict.get('date_to')
        contract = localdict.get('contract')
        date_prima_conf = localdict.get('date_prima')
        date_cesantias_conf = localdict.get('date_cesantias')
        date_liquidacion = localdict.get('date_liquidacion')

        if not fecha_fin:
            _logger.error("'date_to' not found in localdict to determine benefit dates.")
            return {'fecha_inicio': None, 'fecha_fin': None}

        if date_liquidacion and date_liquidacion <= fecha_fin:
            fecha_fin = date_liquidacion

        if tipo_prestacion == 'prima':
            if date_prima_conf:
                fecha_inicio = date_prima_conf
            else:
                semestre = 1 if fecha_fin.month <= 6 else 2
                year = fecha_fin.year
                fecha_inicio = date(year, 1, 1) if semestre == 1 else date(year, 7, 1)
                if not date_liquidacion:
                    fecha_fin = date(year, 6, 30) if semestre == 1 else date(year, 12, 31)

        elif tipo_prestacion in ['cesantias', 'intereses']:
            if date_cesantias_conf:
                fecha_inicio = date_cesantias_conf
            else:
                fecha_inicio = date(fecha_fin.year, 1, 1)

        elif tipo_prestacion == 'vacaciones':
            fecha_inicio = fecha_fin - relativedelta(years=1) + timedelta(days=1)

        else:
            fecha_inicio = localdict.get('date_from')

        if contract and contract.date_start and fecha_inicio and contract.date_start > fecha_inicio:
            fecha_inicio = contract.date_start

        if fecha_inicio and fecha_fin and fecha_inicio > fecha_fin:
            _logger.warning(f"Start date ({fecha_inicio}) > End date ({fecha_fin}) for {tipo_prestacion}. Adjusting start to end.")
            fecha_inicio = fecha_fin

        return {
            'fecha_inicio': fecha_inicio,
            'fecha_fin': fecha_fin
        }

    def _determine_projectable_concepts(
        self,
        localdict: Dict[str, Any],
        periodo_base: str
    ) -> List[str]:
        """
        Determines which concepts should be projected based on salary rule configuration.
        """
        projectable_concepts = []
        all_concepts = self.obtener_conceptos(localdict, filtros={'incluir_ceros': True}, periodos=[periodo_base])
        
        for concepto in all_concepts:
            rule_obj = self.extraer_valor(localdict, concepto['codigo'], periodo_base, campo='object', default=None)
            if rule_obj and getattr(rule_obj, 'is_projectable_rtf', False):
                projectable_concepts.append(concepto['codigo'])
                
        return projectable_concepts

    def _calculate_projected_ibc(
        self,
        localdict: Dict[str, Any],
        total_devengos_proyectados: float,
        dias_trabajados: int,
        dias_proyectar: int,
        conceptos_proyectados_list: List[str]
    ) -> float:
        """
        Calculates the IBC (Contribution Base Income) projected to 30 days.
        """
        ibc_actual = Decimal(str(self.extraer_valor(localdict, 'IBC', 'current_month', default=0.0)))
        dias_base_ibc = Decimal(str(dias_trabajados))

        if ibc_actual > 0 and dias_base_ibc > 0:
            ibc_diario_actual = ibc_actual / dias_base_ibc
            ibc_proyectado = ibc_actual + (ibc_diario_actual * Decimal(str(dias_proyectar)))
            _logger.debug(f"Projected IBC based on current IBC: {ibc_proyectado}")
        else:
            _logger.debug("Calculating projected IBC from base_seguridad_social concepts.")
            filtros_ss = {
                'base_campo': 'base_seguridad_social',
                'incluir_ceros': False
            }
            conceptos_ss_actuales = self.obtener_conceptos(
                localdict, filtros=filtros_ss, periodos=['current_month', 'multi']
            )
            total_base_ss_actual = sum(Decimal(str(c['total'])) for c in conceptos_ss_actuales)

            if float_is_zero(float(total_base_ss_actual), precision_digits=2):
                _logger.warning("No base_seguridad_social concepts found. Using total earnings to project IBC.")
                totales_actuales = self.obtener_totales(
                    localdict, filtros={'periodo': 'current_month', 'incluir_multi': True}
                )
                total_base_ss_actual = Decimal(str(totales_actuales.get('devengos', 0.0)))

            if dias_trabajados > 0:
                base_ss_diaria = total_base_ss_actual / Decimal(str(dias_trabajados))
                ibc_proyectado = total_base_ss_actual + (base_ss_diaria * Decimal(str(dias_proyectar)))
            else:
                ibc_proyectado = total_base_ss_actual

        annual_params = localdict.get('annual_parameters')
        if annual_params:
            smmlv = Decimal(str(getattr(annual_params, 'smmlv', 0.0)))
            if smmlv > 0:
                tope_min = smmlv * Decimal(str(getattr(annual_params, 'ibc_min_smmlv', 1.0)))
                tope_max = smmlv * Decimal(str(getattr(annual_params, 'ibc_max_smmlv', 25.0)))

                ibc_final = min(max(ibc_proyectado, tope_min), tope_max)
                if ibc_final != ibc_proyectado:
                    _logger.debug(f"Projected IBC adjusted by limits: Min={tope_min}, Max={tope_max}. Original={ibc_proyectado}, Final={ibc_final}")
                ibc_proyectado = ibc_final
            else:
                _logger.warning("SMMLV not found in annual parameters to apply IBC limits.")

        return float(ibc_proyectado)

    def _collect_all_rules_info(self, localdict: Dict[str, Any], periodos: List[str]) -> Dict[str, Dict]:
        """
        Collects information about all relevant rules for the given periods.
        """
        todas_reglas_info = defaultdict(lambda: {
            'total': Decimal('0.0'), 'category': None, 'category_code': None, 'rule': None
        })

        payslip_lines = localdict.get('payslip_lines', {})
        for code, line_data in payslip_lines.items():
            for periodo in periodos:
                if periodo != 'multi' and periodo in line_data:
                    period_data = line_data[periodo]
                    rule = period_data.get('rule')
                    total_periodo = Decimal(str(period_data.get('total', 0.0)))

                    if not float_is_zero(float(total_periodo), precision_digits=2):
                        todas_reglas_info[code]['total'] += total_periodo
                        if rule and not todas_reglas_info[code]['rule']:
                            todas_reglas_info[code]['rule'] = rule
                            if rule.category_id:
                                todas_reglas_info[code]['category'] = rule.category_id
                                todas_reglas_info[code]['category_code'] = rule.category_id.code

        # Process rules_multi
        if 'multi' in periodos:
            rules_multi = localdict.get('rules_multi', {})
            for code, multi_data in rules_multi.items():
                if 'current' in multi_data:
                    current_data = multi_data['current']
                    rule = current_data.get('object')
                    total_multi = Decimal(str(current_data.get('total', 0.0)))

                    if not float_is_zero(float(total_multi), precision_digits=2):
                        todas_reglas_info[code]['total'] += total_multi
                        if rule and not todas_reglas_info[code]['rule']:
                            todas_reglas_info[code]['rule'] = rule
                            if rule.category_id:
                                todas_reglas_info[code]['category'] = rule.category_id
                                todas_reglas_info[code]['category_code'] = rule.category_id.code

        return todas_reglas_info

    def _build_optimized_category_hierarchy(self, reglas_info: Dict[str, Dict]) -> Dict[str, List[str]]:
        """
        Builds the category hierarchy (parent -> children) in an optimized way.
        """
        jerarquia = defaultdict(list)

        try:
            Category = self.env['hr.salary.rule.category']
            all_cats = Category.search_read([], ['code', 'parent_id'])
            parent_map = {cat['code']: (cat['parent_id'][0] if cat['parent_id'] else None) for cat in all_cats}
            code_map = {cat['id']: cat['code'] for cat in all_cats}

            for child_code, parent_id in parent_map.items():
                if parent_id and parent_id in code_map:
                    parent_code = code_map[parent_id]
                    jerarquia[parent_code].append(child_code)
            
            return dict(jerarquia)
        except Exception as e:
            _logger.warning(f"Could not get optimized category hierarchy: {e}. Building from rules.")
            
            jerarquia_fallback = defaultdict(list)
            padres_map = {}
            for info in reglas_info.values():
                cat = info.get('category')
                if cat and hasattr(cat, 'parent_id') and cat.parent_id:
                    if cat.code not in padres_map:
                        padres_map[cat.code] = cat.parent_id.code

            for child, parent in padres_map.items():
                jerarquia_fallback[parent].append(child)
                
            return dict(jerarquia_fallback)

    def _determine_target_categories(
        self,
        reglas_info: Dict[str, Dict],
        incluir: List[str],
        excluir: List[str],
        jerarquia: Dict[str, List[str]],
        incluir_subcategorias: bool
    ) -> set:
        """
        Determines the final set of categories to process.
        """
        todas_categorias_presentes = {
            info['category_code'] for info in reglas_info.values() 
            if info['category_code']
        }

        if not incluir:
            categorias_base = todas_categorias_presentes
        else:
            categorias_base = set(incluir)

        categorias_objetivo = set(categorias_base)
        if incluir_subcategorias:
            for cat_base in categorias_base:
                self._add_subcategories(cat_base, jerarquia, categorias_objetivo)

        if excluir:
            categorias_a_excluir_base = set(excluir)
            categorias_a_excluir_final = set(categorias_a_excluir_base)

            if incluir_subcategorias:
                for cat_excluir in categorias_a_excluir_base:
                    self._add_subcategories(cat_excluir, jerarquia, categorias_a_excluir_final)

            categorias_objetivo -= categorias_a_excluir_final

        return categorias_objetivo

    def _add_subcategories(
        self,
        categoria: str,
        jerarquia: Dict[str, List[str]],
        conjunto_destino: set
    ) -> None:
        """
        Recursively adds all subcategories to a set.
        """
        queue = [categoria]
        processed = {categoria}  # Avoid infinite loops if there are errors in hierarchy

        while queue:
            current_cat = queue.pop(0)
            if current_cat in jerarquia:
                for subcat in jerarquia[current_cat]:
                    if subcat not in processed:
                        conjunto_destino.add(subcat)
                        processed.add(subcat)
                        queue.append(subcat)

    def _collect_concepts_info(self, localdict: Dict[str, Any], periodos: List[str]) -> Dict[str, Dict]:
        """
        Collects information about all concepts for the given periods.
        """
        conceptos_info = defaultdict(lambda: {
            'total': Decimal('0.0'), 'cantidad': Decimal('0.0'), 'rule_object': None,
            'categoria': None, 'nombre': None, 'base_fields': {}
        })

        payslip_lines = localdict.get('payslip_lines', {})
        for codigo, line_data in payslip_lines.items():
            for periodo in periodos:
                if periodo != 'multi' and periodo in line_data:
                    period_data = line_data[periodo]
                    total_periodo = Decimal(str(period_data.get('total', 0.0)))
                    
                    if not float_is_zero(float(total_periodo), precision_digits=4):
                        conceptos_info[codigo]['total'] += total_periodo
                        entries = period_data.get('entries', [])
                        conceptos_info[codigo]['cantidad'] += sum(Decimal(str(e.get('quantity', 0.0))) for e in entries)

                        rule = period_data.get('rule')
                        if rule and not conceptos_info[codigo]['rule_object']:
                            conceptos_info[codigo]['rule_object'] = rule
                            conceptos_info[codigo]['nombre'] = rule.name
                            if rule.category_id:
                                conceptos_info[codigo]['categoria'] = rule.category_id.code
                            
                            for campo in dir(rule):
                                if campo.startswith('base_') and getattr(rule, campo, False):
                                    conceptos_info[codigo]['base_fields'][campo] = True

        if 'multi' in periodos:
            rules_multi = localdict.get('rules_multi', {})
            for codigo, multi_data in rules_multi.items():
                if 'current' in multi_data:
                    current_data = multi_data['current']
                    total_multi = Decimal(str(current_data.get('total', 0.0)))
                    
                    if not float_is_zero(float(total_multi), precision_digits=4):
                        conceptos_info[codigo]['total'] += total_multi
                        conceptos_info[codigo]['cantidad'] += Decimal(str(current_data.get('quantity', 0.0)))

                        rule = current_data.get('object')
                        if rule and not conceptos_info[codigo]['rule_object']:
                            conceptos_info[codigo]['rule_object'] = rule
                            conceptos_info[codigo]['nombre'] = rule.name
                            if rule.category_id:
                                conceptos_info[codigo]['categoria'] = rule.category_id.code
                            
                            for campo in dir(rule):
                                if campo.startswith('base_') and getattr(rule, campo, False):
                                    conceptos_info[codigo]['base_fields'][campo] = True

        return conceptos_info

    def _get_totalizar_categorias(
        self,
        localdict: Dict[str, Any],
        categorias: Optional[Union[List[str], str]] = None,
        categorias_excluir: Optional[Union[List[str], str]] = None,
        filtros: Optional[Dict[str, Callable[[Any], bool]]] = None,
        incluir_current: bool = True,
        incluir_before: bool = False,
        incluir_multi: bool = True,
        incluir_subcategorias: bool = True,
        ) -> Tuple[float, float]:
        def _to_list(x: Optional[Union[List[str], str]]) -> Optional[List[str]]:
            if x is None:
                return None
            return x if isinstance(x, list) else [x]

        categorias = _to_list(categorias)
        categorias_excluir = _to_list(categorias_excluir)
        filtros = filtros or {}

        def _pasa_filtros(obj: Any) -> bool:
            for clave, cond in filtros.items():
                if clave == 'object':
                    if not cond(obj):
                        return False
                else:
                    val = getattr(obj, clave, None)
                    if callable(cond):
                        if not cond(val):
                            return False
                    else:
                        if bool(val) != bool(cond):
                            return False
            return True

        fuente: List[Dict[str, Any]] = []
        for code, rd in localdict.get('payslip_lines', {}).items():
            if incluir_current and (info := rd.get('current_month')) and info.get('rule'):
                fuente.append({
                    'code': code,
                    'object': info['rule'],
                    'total': info.get('total', 0.0),
                    'entries': info.get('entries', []),
                })
            if incluir_before and (info := rd.get('before_month')) and info.get('rule'):
                fuente.append({
                    'code': code,
                    'object': info['rule'],
                    'total': info.get('total', 0.0),
                    'entries': info.get('entries', []),
                })

        if incluir_multi:
            for code, rd in localdict.get('rules_multi', {}).items():
                if (info := rd.get('current')) and info.get('object'):
                    fuente.append({
                        'code': code,
                        'object': info['object'],
                        'total': info.get('total', 0.0),
                        'quantity': info.get('quantity', 0),
                    })

        
        reglas_por_cat: Dict[str, set] = {} # construir mapeos categoría ← reglas y padre ← hijo
        padres: Dict[str, str] = {}
        for item in fuente:
            obj = item['object']
            if not obj.category_id:
                continue
            cat = obj.category_id.code
            reglas_por_cat.setdefault(cat, set()).add(item['code'])
            if obj.category_id.parent_id:
                padres.setdefault(cat, obj.category_id.parent_id.code)

        hijos: Dict[str, set] = {}
        for cat, p in padres.items():
            hijos.setdefault(p, set()).add(cat)

        if categorias is None:
            cats = set(reglas_por_cat)
        else:
            cats = set(categorias)
            if incluir_subcategorias:
                cola = list(cats)
                while cola:
                    c = cola.pop()
                    for h in hijos.get(c, ()):
                        if h not in cats:
                            cats.add(h)
                            cola.append(h)

        if categorias_excluir:
            ex = set(categorias_excluir)
            if incluir_subcategorias:
                cola = list(ex)
                while cola:
                    c = cola.pop()
                    for h in hijos.get(c, ()):
                        if h not in ex:
                            ex.add(h)
                            cola.append(h)
            cats -= ex
        total_valor = 0.0
        total_entradas = 0
        for item in fuente:
            obj = item['object']
            cat = obj.category_id.code if obj.category_id else None
            if cat not in cats or not _pasa_filtros(obj):
                continue

            total_valor += item.get('total', 0.0)
            if 'entries' in item:
                total_entradas += len(item['entries'])
            else:
                total_entradas += item.get('quantity', 0)

        return total_valor, total_entradas

    
    # ------------------------------------------------------------------ #
    #                          MÉTODOS AUXILIARES                        #
    # ------------------------------------------------------------------ #
    
    def _to_decimal(self, value: Any, default: Decimal = Decimal("0")) -> Decimal:
        """
        Convierte cualquier valor a Decimal de forma segura.
        
        Args:
            value (Any): Valor a convertir (None, int, float, str, Decimal, etc.)
            default (Decimal): Valor a devolver si la conversión falla
            
        Returns:
            Decimal: Resultado de la conversión o el valor por defecto
        """
        if value in (None, "", "null"):
            return default
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return default
    
    def _format_result_output(self, data: Mapping[str, Any], a_float: bool = True) -> Dict[str, Any]:
        """
        Convierte todos los valores Decimal a float de forma recursiva.
        
        Args:
            data (Mapping[str, Any]): Estructura de datos con valores Decimal
            a_float (bool): Si es True, convierte Decimal a float
            
        Returns:
            Dict[str, Any]: Estructura equivalente con valores float
        """
        if not a_float:
            return dict(data)
        
        def _convert(obj: Any) -> Any:
            if isinstance(obj, Decimal):
                return float(obj)
            if isinstance(obj, (list, tuple, set)):
                return type(obj)(_convert(item) for item in obj)
            if isinstance(obj, Mapping):
                return {key: _convert(val) for key, val in obj.items()}
            return obj
        
        return _convert(data)
    
    def _obtener_dias_periodo(self, fecha_inicio: date, fecha_fin: date, festivos: Optional[Sequence[date]] = None,
                           incluir_sabados: bool = True, incluir_domingos: bool = False) -> Dict[str, int]:
        """
        Calcula los días de un periodo clasificados por tipo.
        
        Args:
            fecha_inicio (date): Fecha inicial (inclusive)
            fecha_fin (date): Fecha final (inclusive)
            festivos (Sequence[date], optional): Lista de fechas festivas
            incluir_sabados (bool): Si los sábados se cuentan como laborales
            incluir_domingos (bool): Si los domingos se cuentan como laborales
            
        Returns:
            Dict[str, int]: Diccionario con clasificación de días
        """
        if fecha_fin < fecha_inicio:
            fecha_inicio, fecha_fin = fecha_fin, fecha_inicio
            
        festivos = set(festivos or [])
        ptr = fecha_inicio
        conteo = {"laborales": 0, "sabados": 0, "domingos": 0, "festivos": 0}
        
        while ptr <= fecha_fin:
            dia_semana = ptr.weekday()  # 0=lunes ... 6=domingo
            
            if ptr in festivos:
                conteo["festivos"] += 1
            elif dia_semana == 5:  # Sábado
                conteo["sabados"] += 1
                if incluir_sabados:
                    conteo["laborales"] += 1
            elif dia_semana == 6:  # Domingo
                conteo["domingos"] += 1
                if incluir_domingos:
                    conteo["laborales"] += 1
            else:
                conteo["laborales"] += 1
                
            ptr += timedelta(days=1)
            
        conteo["total"] = sum(conteo.values())
        return conteo
    
    def _construir_mapa_categorias(self, localdict: Mapping[str, Any]) -> Dict[str, Optional[str]]:
        """
        Construye un mapa {codigo_hijo: codigo_padre} de categorías.
        
        Args:
            localdict (Mapping[str, Any]): Diccionario local con datos
            
        Returns:
            Dict[str, Optional[str]]: Mapa de relación hijo-padre
        """
        mapa = {}
        
        # Buscar en payslip_lines
        for regla_lineas in (localdict.get("payslip_lines") or {}).values():
            for periodo in regla_lineas.values():
                for entrada in periodo.get("entries", []):
                    regla = entrada.get("rule")
                    if regla and regla.category_id:
                        mapa[regla.category_id.code] = (
                            regla.category_id.parent_id.code
                            if regla.category_id.parent_id
                            else None
                        )
        
        # Buscar en rules_multi
        for bloque in (localdict.get("rules_multi") or {}).values():
            regla = bloque.get("current", {}).get("object")
            if regla and regla.category_id:
                mapa.setdefault(
                    regla.category_id.code,
                    regla.category_id.parent_id.code if regla.category_id.parent_id else None
                )
                
        return mapa
    
    def _acumular_categorias_padre(self, totales: Dict[str, Decimal], mapa_padre: Dict[str, Optional[str]]) -> None:
        """
        Propaga los importes de categorías a sus padres.
        
        Args:
            totales (Dict[str, Decimal]): Totales por categoría
            mapa_padre (Dict[str, Optional[str]]): Mapa hijo-padre
        """
        for categoria, importe in list(totales.items()):
            padre = mapa_padre.get(categoria)
            while padre:
                totales[padre] = totales.get(padre, Decimal("0")) + importe
                padre = mapa_padre.get(padre)
    
    def _convertir_localdict_a_filas(self, localdict: Mapping[str, Any], 
                                  incluir_mes_actual: bool = True,
                                  incluir_mes_anterior: bool = False, 
                                  incluir_prima: bool = False,
                                  incluir_cesantias: bool = False,
                                  incluir_ultimo_año: bool = False,
                                  incluir_rules_multi: bool = False) -> List[Dict[str, Any]]:
        """
        Transforma localdict en una lista de filas normalizadas.
        
        Args:
            localdict (Mapping[str, Any]): Diccionario local con datos
            incluir_mes_actual (bool): Incluir datos del mes actual
            incluir_mes_anterior (bool): Incluir datos del mes anterior
            incluir_prima (bool): Incluir datos de prima
            incluir_cesantias (bool): Incluir datos de cesantías
            incluir_ultimo_año (bool): Incluir datos del último año
            incluir_rules_multi (bool): Incluir datos consolidados de rules_multi
            
        Returns:
            List[Dict[str, Any]]: Filas normalizadas
        """
        filas = []
        visto = set()  # Control de duplicados
        
        # Mapeo de nombres de período
        periodo_mapeo = {
            'current_month': incluir_mes_actual,
            'before_month': incluir_mes_anterior,
            'prima': incluir_prima,
            'cesantias': incluir_cesantias,
            'last_year': incluir_ultimo_año
        }
        
        # Procesar payslip_lines
        for codigo_regla, periodos in (localdict.get("payslip_lines") or {}).values():
            for nombre_periodo, info in periodos.items():
                # Verificar si este período está incluido
                if nombre_periodo in periodo_mapeo and not periodo_mapeo[nombre_periodo]:
                    continue
                    
                for entrada in info.get("entries", []):
                    id_linea = entrada["payslip_id"].id if entrada.get("payslip_id") else None
                    clave = (id_linea, codigo_regla)
                    
                    if clave in visto:
                        continue
                        
                    visto.add(clave)
                    regla_obj = entrada.get("rule")
                    
                    filas.append({
                        "categoria": (regla_obj.category_id.code if regla_obj and regla_obj.category_id else None),
                        "regla": codigo_regla,
                        "regla_obj": regla_obj,  # Guardar el objeto completo para acceso a campos
                        "regla_nombre": regla_obj.name if regla_obj else codigo_regla,
                        "importe": self._to_decimal(entrada.get("total")),
                        "cantidad": self._to_decimal(entrada.get("quantity", 1)),
                        "tasa": self._to_decimal(entrada.get("rate", 100)),
                        "fecha": entrada.get("date"),
                        "origen": nombre_periodo,
                        "periodo": entrada["date"].strftime("%Y-%m") if entrada.get("date") else None,
                        "tipo_regla": getattr(regla_obj, "type", None),
                        "excluir": bool(getattr(regla_obj, "exclude_report", False))
                    })
        
        # Procesar rules_multi si se solicita
        if incluir_rules_multi:
            for codigo_regla, bloques in (localdict.get("rules_multi") or {}).values():
                actual = bloques.get("current")
                if not actual:
                    continue
                    
                regla_obj = actual.get("object")
                
                filas.append({
                    "categoria": (regla_obj.category_id.code if regla_obj and regla_obj.category_id else None),
                    "regla": codigo_regla,
                    "regla_obj": regla_obj,  # Guardar el objeto completo para acceso a campos
                    "regla_nombre": regla_obj.name if regla_obj else codigo_regla,
                    "importe": self._to_decimal(actual.get("total")),
                    "cantidad": self._to_decimal(actual.get("quantity", 1)),
                    "tasa": self._to_decimal(actual.get("rate", 100)),
                    "fecha": localdict["slip"].date_to,
                    "origen": "rules_multi",
                    "periodo": localdict["slip"].date_to.strftime("%Y-%m"),
                    "tipo_regla": getattr(regla_obj, "type", None),
                    "excluir": bool(getattr(regla_obj, "exclude_report", False))
                })
                
        return filas
    
    def _agregar_filas(self, filas: Iterable[Mapping[str, Any]], campo_clave: str, 
                     campo_excluir: str = "excluir", 
                     predicado: Callable[[Mapping[str, Any]], bool] = lambda r: True) -> Tuple[Dict[str, Decimal], Decimal]:
        """
        Agrupa y suma filas por una clave determinada.
        
        Args:
            filas (Iterable[Mapping[str, Any]]): Filas a agrupar
            campo_clave (str): Nombre del campo para agrupar
            campo_excluir (str): Campo booleano de exclusión
            predicado (Callable): Función de filtrado adicional
            
        Returns:
            Tuple[Dict[str, Decimal], Decimal]: (resultados_agrupados, total_general)
        """
        agrupado = {}
        total = Decimal("0")
        
        for fila in filas:
            if fila.get(campo_excluir) or not predicado(fila):
                continue
                
            clave_grupo = str(fila.get(campo_clave) or "N/A")
            importe = self._to_decimal(fila.get("importe"))
            
            agrupado[clave_grupo] = agrupado.get(clave_grupo, Decimal("0")) + importe
            total += importe
            
        return agrupado, total
    
    def _obtener_detalle_regla(self, filas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Extrae el detalle completo por regla de las filas normalizadas.
        
        Args:
            filas (List[Dict[str, Any]]): Filas normalizadas
            
        Returns:
            List[Dict[str, Any]]: Lista de detalles por regla
        """
        detalle = []
        
        for fila in filas:
            if fila.get("excluir"):
                continue
                
            detalle.append({
                "codigo": fila.get("regla"),
                "nombre": fila.get("regla_nombre"),
                "fecha": fila.get("fecha"),
                "cantidad": fila.get("cantidad"),
                "tasa": fila.get("tasa"),
                "importe": fila.get("importe"),
                "origen": fila.get("origen"),
                "periodo": fila.get("periodo"),
                "categoria": fila.get("categoria"),
                "tipo_regla": fila.get("tipo_regla")
            })
            
        return detalle
    
    # ------------------------------------------------------------------ #
    #                     FUNCIÓN PRINCIPAL UNIFICADA                    #
    # ------------------------------------------------------------------ #
    
    def obtener_reporte_nomina(
        self,
        # Configuración básica
        localdict=None,                   # Datos de entrada (default: actual)
        
        # Filtros principales
        tipo_filtro='categoria',          # 'categoria', 'regla', 'combinado'
        codigos_incluir=None,             # Códigos a incluir (None = todos)
        codigos_excluir=None,             # Códigos a excluir
        campo_filtro=None,                # Campo booleano (ej. 'base_prima')
        valor_filtro=True,                # Valor del campo booleano
        tipo_regla=None,                  # Para filtrar por tipo de regla
        
        # Filtros de período (booleanos en español)
        incluir_mes_actual=True,          # Incluir período 'current_month'
        incluir_mes_anterior=False,       # Incluir período 'before_month'
        incluir_prima=False,              # Incluir período 'prima'
        incluir_cesantias=False,          # Incluir período 'cesantias'
        incluir_ultimo_año=False,         # Incluir período 'last_year_info'
        incluir_rules_multi=True,         # Incluir consolidado rules_multi
        
        # Opciones de salida
        formato='simple',                 # 'simple', 'detallado', 'comparativo'
        incluir_detalles=False,           # Incluir detalles por origen
        incluir_historial=False,          # Incluir historial temporal
        incluir_detalle_regla=False,      # Incluir detalle completo por regla
        incluir_totales=True,             # Incluir los totales en el resultado
        incluir_metricas=['importe'],     # Métricas a incluir
        acumular_categorias=True,         # Acumular a categorías padre
        a_float=True                      # Convertir Decimal a float
    ) -> Dict[str, Any]:
        """
        Función unificada para generar reportes de nómina con múltiples opciones.
        
        Args:
            localdict: Diccionario con datos (None = usar nómina actual)
            tipo_filtro: 'categoria', 'regla' o 'combinado'
            codigos_incluir: Lista de códigos a incluir (None = todos)
            codigos_excluir: Lista de códigos a excluir
            campo_filtro: Campo booleano para filtrado (ej. 'base_prima')
            valor_filtro: Valor esperado del campo booleano
            tipo_regla: Filtrar por tipo de regla
            incluir_mes_actual: Incluir datos del mes actual
            incluir_mes_anterior: Incluir datos del mes anterior
            incluir_prima: Incluir datos de prima
            incluir_cesantias: Incluir datos de cesantías
            incluir_ultimo_año: Incluir datos del último año
            incluir_rules_multi: Incluir datos consolidados de rules_multi
            formato: 'simple', 'detallado' o 'comparativo'
            incluir_detalles: Incluir desglose por origen
            incluir_historial: Incluir historial temporal
            incluir_detalle_regla: Incluir detalle completo por regla
            incluir_totales: Incluir los totales en el resultado
            incluir_metricas: Lista de métricas a incluir
            acumular_categorias: Propagar totales a categorías padre
            a_float: Convertir números Decimal a float
            
        Returns:
            Dict[str, Any]: Reporte según los parámetros especificados
        """
        # Si no se proporciona localdict, usar el de la nómina actual
        if not localdict:
            localdict = self._get_localdict_payslip()
            
        # Convertir localdict a filas normalizadas
        filas = self._convertir_localdict_a_filas(
            localdict,
            incluir_mes_actual=incluir_mes_actual,
            incluir_mes_anterior=incluir_mes_anterior,
            incluir_prima=incluir_prima,
            incluir_cesantias=incluir_cesantias,
            incluir_ultimo_año=incluir_ultimo_año,
            incluir_rules_multi=incluir_rules_multi
        )
        
        # Aplicar filtros adicionales
        if codigos_incluir:
            campo_codigo = 'categoria' if tipo_filtro == 'categoria' else 'regla'
            filas = [f for f in filas if f.get(campo_codigo) in codigos_incluir]
            
        if codigos_excluir:
            campo_codigo = 'categoria' if tipo_filtro == 'categoria' else 'regla'
            filas = [f for f in filas if f.get(campo_codigo) not in codigos_excluir]
            
        if campo_filtro:
            filas = [
                f for f in filas 
                if (f.get('regla_obj') and 
                    hasattr(f.get('regla_obj'), campo_filtro) and 
                    getattr(f.get('regla_obj'), campo_filtro) == valor_filtro)
            ]
            
        if tipo_regla:
            filas = [f for f in filas if f.get('tipo_regla') == tipo_regla]
            
        # Determinar campo de agrupación
        campo_agrupacion = 'categoria' if tipo_filtro == 'categoria' else 'regla'
        
        # Preparar resultado base
        resultado_base = {
            "dias": self._obtener_dias_periodo(self.date_from, self.date_to),
        }
        
        # Añadir detalle por regla si se solicita
        if incluir_detalle_regla:
            resultado_base["detalle_regla"] = self._obtener_detalle_regla(filas)
            
        # Calcular según formato solicitado
        if formato == 'simple':
            resultado = self._generar_reporte_simple(
                filas, 
                campo_agrupacion, 
                acumular_categorias,
                incluir_totales,
                resultado_base
            )
        elif formato == 'detallado':
            resultado = self._generar_reporte_detallado(
                filas, 
                campo_agrupacion, 
                incluir_detalles, 
                incluir_historial, 
                incluir_metricas,
                acumular_categorias,
                incluir_totales,
                resultado_base
            )
        elif formato == 'comparativo':
            resultado = self._generar_reporte_comparativo(
                filas, 
                campo_agrupacion, 
                incluir_metricas,
                resultado_base
            )
        else:
            raise ValueError(f"Formato '{formato}' no reconocido")
            
        return self._format_result_output(resultado, a_float)

    # ------------------------------------------------------------------ #
    #                     FUNCIONES DE REPORTE ESPECÍFICAS               #
    # ------------------------------------------------------------------ #
    
    def _generar_reporte_simple(self, filas: List[Dict[str, Any]], 
                              campo_agrupacion: str,
                              acumular_categorias: bool,
                              incluir_totales: bool,
                              resultado_base: Dict[str, Any]) -> Dict[str, Any]:
        """
        Genera un reporte simple con totales agrupados.
        
        Args:
            filas (List[Dict[str, Any]]): Filas normalizadas
            campo_agrupacion (str): Campo para agrupar ('categoria' o 'regla')
            acumular_categorias (bool): Si acumula totales a categorías padre
            incluir_totales (bool): Si incluye totales en el resultado
            resultado_base (Dict[str, Any]): Diccionario base para el resultado
            
        Returns:
            Dict[str, Any]: Reporte con totales agrupados
        """
        # Agrupar filas por el campo especificado
        agrupado, total_general = self._agregar_filas(filas, campo_agrupacion)
        
        # Propagar a categorías padre si es necesario
        if acumular_categorias and campo_agrupacion == 'categoria':
            localdict = self._get_localdict_payslip()
            mapa_padre = self._construir_mapa_categorias(localdict)
            self._acumular_categorias_padre(agrupado, mapa_padre)
        
        # Preparar resultado
        resultado = resultado_base.copy()
        resultado["elementos"] = agrupado
        
        # Incluir totales si se solicita
        if incluir_totales:
            resultado["total_general"] = total_general
        
        return resultado
    
    def _generar_reporte_detallado(self, filas: List[Dict[str, Any]], 
                                 campo_agrupacion: str,
                                 incluir_detalles: bool,
                                 incluir_historial: bool,
                                 incluir_metricas: List[str],
                                 acumular_categorias: bool,
                                 incluir_totales: bool,
                                 resultado_base: Dict[str, Any]) -> Dict[str, Any]:
        """
        Genera un reporte detallado con desglose por origen.
        
        Args:
            filas (List[Dict[str, Any]]): Filas normalizadas
            campo_agrupacion (str): Campo para agrupar ('categoria' o 'regla')
            incluir_detalles (bool): Si incluye desglose por origen
            incluir_historial (bool): Si incluye historial temporal
            incluir_metricas (List[str]): Métricas a incluir
            acumular_categorias (bool): Si acumula totales a categorías padre
            incluir_totales (bool): Si incluye totales en el resultado
            resultado_base (Dict[str, Any]): Diccionario base para el resultado
            
        Returns:
            Dict[str, Any]: Reporte detallado
        """
        # Filtrar filas excluidas
        filas_validas = [f for f in filas if not f.get("excluir")]
        
        # Estructura para el resultado
        resultado = resultado_base.copy()
        resultado["elementos"] = {}
        
        # Variable para el total general
        total_general = Decimal("0.0")
        
        # Procesar según el desglose solicitado
        if incluir_detalles:
            # Agrupar por campo principal y luego por origen
            elementos_anidados = {}
            
            # Primera agrupación por campo principal
            for clave_principal, grupo_principal in groupby(
                    sorted(filas_validas, key=itemgetter(campo_agrupacion)),
                    key=itemgetter(campo_agrupacion)):
                
                elementos_anidados[str(clave_principal)] = {
                    "total": Decimal("0.0"),
                    "origenes": {}
                }
                
                # Segunda agrupación por origen dentro de cada grupo principal
                filas_grupo = list(grupo_principal)  # Convertir a lista para reutilizar
                
                for origen, grupo_origen in groupby(
                        sorted(filas_grupo, key=itemgetter("origen")),
                        key=itemgetter("origen")):
                    
                    # Sumar importes del mismo origen
                    total_origen = sum(self._to_decimal(f.get("importe")) for f in grupo_origen)
                    elementos_anidados[str(clave_principal)]["origenes"][str(origen)] = total_origen
                    elementos_anidados[str(clave_principal)]["total"] += total_origen
                
                # Acumular al total general
                total_general += elementos_anidados[str(clave_principal)]["total"]
            
            resultado["elementos"] = elementos_anidados
            
        elif incluir_historial:
            # Agrupar por campo principal y crear historial por período
            historial = {}
            
            for clave_principal, grupo_principal in groupby(
                    sorted(filas_validas, key=itemgetter(campo_agrupacion)),
                    key=itemgetter(campo_agrupacion)):
                
                # Inicializar entrada para esta clave
                historial[str(clave_principal)] = {
                    "total": Decimal("0.0"),
                    "historial": []
                }
                
                # Procesar cada entrada del grupo
                for fila in grupo_principal:
                    historial[str(clave_principal)]["historial"].append({
                        "periodo": fila.get("periodo"),
                        "importe": self._to_decimal(fila.get("importe"))
                    })
                    
                    # Acumular al total de la clave
                    historial[str(clave_principal)]["total"] += self._to_decimal(fila.get("importe"))
                
                # Acumular al total general
                total_general += historial[str(clave_principal)]["total"]
            
            resultado["elementos"] = historial
            
        else:
            # Reporte simple con métricas adicionales
            agrupado = {}
            
            for clave_principal, grupo_principal in groupby(
                    sorted(filas_validas, key=itemgetter(campo_agrupacion)),
                    key=itemgetter(campo_agrupacion)):
                
                # Inicializar entrada para esta clave
                agrupado[str(clave_principal)] = {
                    "total": Decimal("0.0"),
                    "metricas": {}
                }
                
                # Acumular importes y recopilar métricas
                for fila in grupo_principal:
                    importe = self._to_decimal(fila.get("importe"))
                    agrupado[str(clave_principal)]["total"] += importe
                    
                    # Recopilar métricas solicitadas
                    for metrica in incluir_metricas:
                        if metrica != "importe":  # importe ya se procesa como total
                            valor_metrica = self._to_decimal(fila.get(metrica, 0))
                            
                            if metrica not in agrupado[str(clave_principal)]["metricas"]:
                                agrupado[str(clave_principal)]["metricas"][metrica] = valor_metrica
                            else:
                                # Para métricas numéricas, sumar o promediar según sea apropiado
                                if metrica in ["cantidad", "tasa"]:
                                    # Para estas métricas, calculamos un promedio ponderado
                                    actual = agrupado[str(clave_principal)]["metricas"][metrica]
                                    peso_actual = agrupado[str(clave_principal)]["total"] - importe
                                    nuevo_valor = (actual * peso_actual + valor_metrica * importe) / agrupado[str(clave_principal)]["total"]
                                    agrupado[str(clave_principal)]["metricas"][metrica] = nuevo_valor
                                else:
                                    # Para otras métricas, simplemente sumamos
                                    agrupado[str(clave_principal)]["metricas"][metrica] += valor_metrica
                
                # Acumular al total general
                total_general += agrupado[str(clave_principal)]["total"]
            
            resultado["elementos"] = agrupado
        
        # Propagar a categorías padre si es necesario
        if acumular_categorias and campo_agrupacion == 'categoria':
            localdict = self._get_localdict_payslip()
            mapa_padre = self._construir_mapa_categorias(localdict)
            
            # Crear copia de las claves originales para iterar sin modificar durante la iteración
            claves_originales = list(resultado["elementos"].keys())
            
            for categoria in claves_originales:
                importe = resultado["elementos"][categoria]["total"]
                padre = mapa_padre.get(categoria)
                
                while padre:
                    # Asegurarse de que la categoría padre existe en el resultado
                    if padre not in resultado["elementos"]:
                        resultado["elementos"][padre] = {
                            "total": Decimal("0.0")
                        }
                        
                        # Copiar la misma estructura que tienen los hijos
                        if "origenes" in resultado["elementos"][categoria]:
                            resultado["elementos"][padre]["origenes"] = {}
                        elif "historial" in resultado["elementos"][categoria]:
                            resultado["elementos"][padre]["historial"] = []
                        elif "metricas" in resultado["elementos"][categoria]:
                            resultado["elementos"][padre]["metricas"] = {}
                    
                    # Acumular el importe
                    resultado["elementos"][padre]["total"] += importe
                    
                    # Avanzar al siguiente padre
                    padre = mapa_padre.get(padre)
        
        # Incluir totales si se solicita
        if incluir_totales:
            resultado["total_general"] = total_general
        
        return resultado
    
    def _generar_reporte_comparativo(self, filas: List[Dict[str, Any]], 
                                   campo_agrupacion: str,
                                   incluir_metricas: List[str],
                                   resultado_base: Dict[str, Any]) -> Dict[str, Any]:
        """
        Genera un reporte comparativo entre períodos.
        
        Args:
            filas (List[Dict[str, Any]]): Filas normalizadas
            campo_agrupacion (str): Campo para agrupar ('categoria' o 'regla')
            incluir_metricas (List[str]): Métricas a comparar
            resultado_base (Dict[str, Any]): Diccionario base para el resultado
            
        Returns:
            Dict[str, Any]: Reporte comparativo
        """
        # Filtrar filas excluidas
        filas_validas = [f for f in filas if not f.get("excluir")]
        
        # Agrupar por período y luego por campo de agrupación
        periodos = {}
        
        for fila in filas_validas:
            periodo = fila.get("origen", "desconocido")
            clave = fila.get(campo_agrupacion, "N/A")
            importe = self._to_decimal(fila.get("importe"))
            
            # Inicializar período si no existe
            if periodo not in periodos:
                periodos[periodo] = {}
            
            # Inicializar clave si no existe
            if clave not in periodos[periodo]:
                periodos[periodo][clave] = Decimal("0.0")
            
            # Acumular importe
            periodos[periodo][clave] += importe
        
        # Determinar períodos actual y anterior
        periodo_actual = "current_month"  # Por defecto
        periodo_anterior = "before_month"  # Por defecto
        
        # Si tenemos más de un período, usar el primero como actual y el segundo como anterior
        if len(periodos) >= 2:
            periodos_ordenados = list(periodos.keys())
            periodo_actual = periodos_ordenados[0]
            periodo_anterior = periodos_ordenados[1]
        
        # Construir comparación
        comparacion = {}
        
        # Obtener todas las claves únicas de ambos períodos
        todas_claves = set()
        if periodo_actual in periodos:
            todas_claves.update(periodos[periodo_actual].keys())
        if periodo_anterior in periodos:
            todas_claves.update(periodos[periodo_anterior].keys())
        
        # Calcular comparación para cada clave
        for clave in todas_claves:
            valor_actual = periodos.get(periodo_actual, {}).get(clave, Decimal("0.0"))
            valor_anterior = periodos.get(periodo_anterior, {}).get(clave, Decimal("0.0"))
            diferencia = valor_actual - valor_anterior
            
            # Calcular porcentaje si es posible
            if valor_anterior != 0:
                porcentaje = (diferencia / valor_anterior) * Decimal("100.0")
            else:
                porcentaje = None if valor_actual == 0 else Decimal("100.0")
            
            comparacion[str(clave)] = {
                "actual": valor_actual,
                "anterior": valor_anterior,
                "diferencia": diferencia,
                "porcentaje": porcentaje
            }
        
        # Preparar resultado
        resultado = resultado_base.copy()
        resultado.update({
            "comparacion": comparacion,
            "periodo_actual": periodo_actual,
            "periodo_anterior": periodo_anterior
        })
        
        return resultado
    
    # ------------------------------------------------------------------ #
    #                 FUNCIONES DE COMPATIBILIDAD HACIA ATRÁS            #
    # ------------------------------------------------------------------ #
    
    def get_category_totals(self, 
                          incluir_mes_actual: bool = True,
                          incluir_mes_anterior: bool = False, 
                          incluir_prima: bool = False,
                          incluir_cesantias: bool = False,
                          incluir_ultimo_año: bool = False,
                          incluir_rules_multi: bool = True,
                          incluir_detalle_regla: bool = False,
                          incluir_totales: bool = True,
                          a_float: bool = True) -> Dict[str, Any]:
        """
        Función de compatibilidad: Calcula totales por categoría.
        """
        return self.obtener_reporte_nomina(
            tipo_filtro='categoria',
            incluir_mes_actual=incluir_mes_actual,
            incluir_mes_anterior=incluir_mes_anterior,
            incluir_prima=incluir_prima,
            incluir_cesantias=incluir_cesantias,
            incluir_ultimo_año=incluir_ultimo_año,
            incluir_rules_multi=incluir_rules_multi,
            formato='simple',
            incluir_detalle_regla=incluir_detalle_regla,
            incluir_totales=incluir_totales,
            acumular_categorias=True,
            a_float=a_float
        )
    
    def get_rule_totals(self, 
                      tipo_regla: Optional[str] = None,
                      incluir_mes_actual: bool = True,
                      incluir_mes_anterior: bool = False, 
                      incluir_prima: bool = False,
                      incluir_cesantias: bool = False,
                      incluir_ultimo_año: bool = False,
                      incluir_rules_multi: bool = True,
                      incluir_detalle_regla: bool = False,
                      incluir_totales: bool = True,
                      a_float: bool = True) -> Dict[str, Any]:
        """
        Función de compatibilidad: Calcula totales por regla.
        """
        return self.obtener_reporte_nomina(
            tipo_filtro='regla',
            tipo_regla=tipo_regla,
            incluir_mes_actual=incluir_mes_actual,
            incluir_mes_anterior=incluir_mes_anterior,
            incluir_prima=incluir_prima,
            incluir_cesantias=incluir_cesantias,
            incluir_ultimo_año=incluir_ultimo_año,
            incluir_rules_multi=incluir_rules_multi,
            formato='simple',
            incluir_detalle_regla=incluir_detalle_regla,
            incluir_totales=incluir_totales,
            a_float=a_float
        )
    
    def get_detailed_category_report(self,
                                   incluir_mes_actual: bool = True,
                                   incluir_mes_anterior: bool = False, 
                                   incluir_prima: bool = False,
                                   incluir_cesantias: bool = False,
                                   incluir_ultimo_año: bool = False,
                                   incluir_rules_multi: bool = True,
                                   incluir_detalle_regla: bool = False,
                                   incluir_totales: bool = True,
                                   a_float: bool = True) -> Dict[str, Any]:
        """
        Función de compatibilidad: Genera informe detallado por categoría.
        """
        return self.obtener_reporte_nomina(
            tipo_filtro='categoria',
            incluir_mes_actual=incluir_mes_actual,
            incluir_mes_anterior=incluir_mes_anterior,
            incluir_prima=incluir_prima,
            incluir_cesantias=incluir_cesantias,
            incluir_ultimo_año=incluir_ultimo_año,
            incluir_rules_multi=incluir_rules_multi,
            formato='detallado',
            incluir_detalles=True,
            incluir_detalle_regla=incluir_detalle_regla,
            incluir_totales=incluir_totales,
            acumular_categorias=True,
            a_float=a_float
        )
    
    def get_detailed_rule_report(self,
                               incluir_mes_actual: bool = True,
                               incluir_mes_anterior: bool = False, 
                               incluir_prima: bool = False,
                               incluir_cesantias: bool = False,
                               incluir_ultimo_año: bool = False,
                               incluir_rules_multi: bool = True,
                               incluir_detalle_regla: bool = False,
                               incluir_totales: bool = True,
                               a_float: bool = True) -> Dict[str, Any]:
        """
        Función de compatibilidad: Genera informe detallado por regla.
        """
        return self.obtener_reporte_nomina(
            tipo_filtro='regla',
            incluir_mes_actual=incluir_mes_actual,
            incluir_mes_anterior=incluir_mes_anterior,
            incluir_prima=incluir_prima,
            incluir_cesantias=incluir_cesantias,
            incluir_ultimo_año=incluir_ultimo_año,
            incluir_rules_multi=incluir_rules_multi,
            formato='detallado',
            incluir_historial=True,
            incluir_detalle_regla=incluir_detalle_regla,
            incluir_totales=incluir_totales,
            a_float=a_float
        )


class LavishRetencionService(models.AbstractModel):
    """
    Servicio para cálculo de retención en la fuente.
    
    Implementa los métodos de cálculo de retención utilizando
    los servicios de LavishToolsNomina para optimizar los cálculos.
    """
    _name = "lavish.retencion.service"
    _description = "Servicio de Retención en la Fuente"
    
    # Parámetro que se establece a nivel de configuración
    aplicar_cobro = fields.Selection([
        ('0', 'Siempre'),
        ('15', 'Quincena 1'),
        ('30', 'Quincena 2')
        ], string='Aplicar cobro de retención en', default='0')
    
    def _rtf_indem(self, payslip_data):
        """
        Calcula la retención en la fuente para indemnizaciones laborales.
        Según art. 401-3 del E.T.:
        - Aplica 20% solo si los ingresos mensuales del trabajador superan 204 UVT
        - Los ingresos incluyen todo pago que remunere la actividad laboral
        - La retención es independiente de la retención por salarios
        - Se aplica una exención del 25% sin límite mensual
        """
        herramientas = self.env['lavish.tools.nomina']
        
        if payslip_data['contract'].contract_type == 'aprendizaje':
            return 0, 0, 0, 0, [], False
        
        payslip = payslip_data.get('slip')
        contract = payslip_data['contract']
        annual_params = payslip_data['annual_parameters']
        
        categorias_ingreso = ['BASIC', 'LICENCIA_REMUNERADA', 'DEV_SALARIAL', 'HEYREC', 'RDF', 'COMISIONES']
        ingresos_actuales = herramientas.totalizar_categorias(
            payslip_data,
            categorias=categorias_ingreso,
            periodos=['current_month', 'multi']
        )
        
        ingresos_detalle = {}
        for categoria in ingresos_actuales.get('categorias_procesadas', []):
            conceptos = herramientas.obtener_conceptos(
                payslip_data,
                filtros={'categoria': categoria},
                periodos=['current_month', 'multi']
            )
            
            for concepto in conceptos:
                ingresos_detalle[concepto['codigo']] = {
                    'name': concepto['nombre'],
                    'valor': concepto['total'],
                    'fecha': payslip.date_to,
                    'categoria': concepto.get('categoria')
                }
        
        ingresos_previos = self._get_previous_month_income(
            payslip_data['employee'].id,
            payslip.date_to,
            payslip.id,
            categorias_ingreso
        )
        
        total_ingresos = ingresos_actuales['total'] + ingresos_previos
        
        limite_204_uvt = 204 * annual_params.value_uvt
        if total_ingresos <= limite_204_uvt:
            return 0, 0, 0, 'na', '', {
                'ingresos': {
                    'mensuales': ingresos_actuales['total'],
                    'previos': ingresos_previos,
                    'total': total_ingresos
                },
                'limite_uvt': {
                    'valor': limite_204_uvt,
                    'excede': False
                },
                'detalle': ingresos_detalle,
                'pasos': [
                    {'descripcion': 'Verificación de límite 204 UVT', 'resultado': 'No aplica retención'},
                    {'descripcion': 'Ingresos mensuales', 'valor': total_ingresos},
                    {'descripcion': 'Límite 204 UVT', 'valor': limite_204_uvt}
                ]
            }
        
        indemnizacion = herramientas.extraer_valor(payslip_data, 'INDEM', campo='total', default=0.0) 
        
        
        if not indemnizacion:
            return 0, 0, 0, 'na', '', {
                'ingresos': {
                    'mensuales': ingresos_actuales['total'],
                    'previos': ingresos_previos,
                    'total': total_ingresos
                },
                'limite_uvt': {
                    'valor': limite_204_uvt,
                    'excede': True
                },
                'pasos': [
                    {'descripcion': 'Verificación de existencia de indemnización', 'resultado': 'No hay indemnización'}
                ]
            }
        
        renta_exenta = indemnizacion * 0.25
        base_gravable = indemnizacion - renta_exenta
        
        pasos = [
            {'descripcion': 'Verificación de límite 204 UVT', 'resultado': 'Aplica retención'},
            {'descripcion': 'Ingresos mensuales', 'valor': total_ingresos},
            {'descripcion': 'Límite 204 UVT', 'valor': limite_204_uvt},
            {'descripcion': 'Valor indemnización', 'valor': indemnizacion},
            {'descripcion': 'Renta exenta (25%)', 'valor': renta_exenta},
            {'descripcion': 'Base gravable (75%)', 'valor': base_gravable},
            {'descripcion': 'Tarifa aplicable', 'valor': '20%'},
            {'descripcion': 'Retención calculada', 'valor': base_gravable * 0.20}
        ]
        
        result = {
            'ingresos': {
                'mensuales': ingresos_actuales['total'],
                'previos': ingresos_previos,
                'total': total_ingresos
            },
            'indemnizacion': {
                'valor': indemnizacion,
                'exenta': renta_exenta,
                'gravada': base_gravable
            },
            'limite_uvt': {
                'valor': limite_204_uvt,
                'excede': total_ingresos > limite_204_uvt
            },
            'detalle': ingresos_detalle,
            'pasos': pasos
        }
        html_report = self.generar_html_retencion(result)
        return (
            base_gravable, 
            -1,           
            20,          
            f'RETENCION INDEMNIZACION {payslip.date_from} - {payslip.date_to}',
            html_report,     
            False
        )
    
    def _get_previous_month_income(self, employee_id, date_to, current_slip_id, categorias):
        """
        Obtiene ingresos de nóminas anteriores del mismo mes.
        """
        month_start = date_to.replace(day=1)
        
        # Buscar nóminas anteriores
        SlipObj = self.env['hr.payslip']
        slips_anteriores = SlipObj.search([
            ('employee_id', '=', employee_id),
            ('date_from', '>=', month_start),
            ('date_to', '<=', date_to),
            ('id', '!=', current_slip_id),
            ('state', 'in', ['done', 'paid'])
        ])
        
        if not slips_anteriores:
            return 0
            
        # Sumar conceptos relevantes
        total = 0
        for slip in slips_anteriores:
            for line in slip.line_ids:
                if line.category_id.code in categorias:
                    total += line.total
                    
        return total
    
    def _calcular_deduccion_vivienda(self, contract, date_to, value_uvt):
        """Calcula la deducción por vivienda"""
        deduccion = contract.get_contract_deductions_rtf(contract.id, 'INTVIV').value_monthly
        return min(deduccion, value_uvt * 100)

    def _calcular_deduccion_dependientes(self, contract, date_to, total_ing_base, value_uvt):
        """Calcula la deducción por dependientes"""
        if contract.ded_dependents:
            deduction_base = total_ing_base * Decimal(0.1)
            return min(deduction_base, value_uvt * 32)
            
        deduccion = contract.get_contract_deductions_rtf(contract.id, 'DEDDEP').value_monthly
        if deduccion > 0:
            return min(total_ing_base * Decimal(0.1), value_uvt * 32)
            
        return 0

    def _calcular_deduccion_salud(self, contract, date_to, value_uvt):
        """Calcula la deducción por salud prepagada"""
        deduccion = contract.get_contract_deductions_rtf(contract.id, 'MEDPRE').value_monthly
        return min(deduccion, value_uvt * 16)
    
    def _calcular_retencion(self, ibr_uvts, value_uvt):
        """
        Calcula la retención según la tabla
        """
        for desde, hasta, tarifa, resta_uvt, suma_uvt in tabla_retencion:
            if desde <= ibr_uvts < hasta:
                if desde == 0:
                    return 0, 0, 0
                    
                retencion = round(
                    (((Decimal(ibr_uvts) - resta_uvt) * (tarifa/100)) + suma_uvt) * Decimal(value_uvt), 
                    0
                )
                return retencion, tarifa, resta_uvt
                
        return 0, 0, 0
    
    def _generar_datos_reporte(self, valores, employee, annual_parameters, payslip):
        """
        Genera el diccionario de datos para el reporte.
        """
        # Si hay pasos detallados, mantenerlos
        pasos = valores.get('pasos', [])
        
        return {
            'year': payslip.date_to.year,
            'uvt': annual_parameters.value_uvt,
            'employee_name': employee.name,
            'employee_document': employee.identification_id,
            'dias': {
                'trabajados': valores['dias_trabajados'],
                'nov_remunerada': valores.get('dias_nov_remunerada', 0),
                'nov_no_remunerada': valores.get('dias_nov_no_remunerada', 0)
            },
            'ingresos': {
                'salario': valores['salario'],
                'comisiones': valores['comisiones'],
                'dev_salarial': valores['dev_salarial'],
                'dev_no_salarial': valores['dev_no_salarial'],
                'otros_ingresos': valores['dev_salarial'] + valores['dev_no_salarial'],
                'excluidos': valores.get('excluidos', 0),
                'total': valores['total_ing_base']
            },
            'aportes_obligatorios': {
                'pension': valores['total_pension'],
                'salud': valores['salud'],
                'total': valores['ing_no_gravados']
            },
            'deducciones': {
                'vivienda': valores['ded_vivienda'],
                'dependientes': valores['ded_dependientes'],
                'salud': valores['ded_salud'],
                'total': valores['total_deducciones']
            },
            'rentas_exentas': {
                'afc': valores['re_afc'],
                'total': valores['total_re'],
                'renta_exenta_25': valores['renta_exenta_25']
            },
            'base_calculo': {
                'subtotal_1': valores['subtotal_ibr1'],
                'subtotal_2': valores['subtotal_ibr2'],
                'subtotal_3': valores['subtotal_ibr3'],
                'base_uvts': valores['ibr_uvts']
            },
            'retencion': {
                'tarifa': valores['rate'],
                'resta_uvt': valores['resta_uvt'],
                'valor': valores['retencion'],
                'anterior': valores['retencion_anterior'],
                'definitiva': valores['retencion_def']
            },
            'proyeccion': {
                'es_proyectado': valores['es_proyectado']
            },
            'valores_sin_proyectar': valores.get('valores_sin_proyectar'),
            'pasos': pasos
        }
        
    def _round_decimal(self, valor, precision=0):
        """
        Redondea un valor Decimal a la precisión especificada
        
        Args:
            valor: Valor decimal a redondear
            precision: Precisión del redondeo (negativo para redondear a miles, etc.)
            
        Returns:
            Decimal redondeado
        """
        if precision >= 0:
            return valor.quantize(Decimal('0.' + '0' * precision), rounding=ROUND_HALF_UP)
        else:
            # Para redondear a miles (-3), etc.
            factor = Decimal('10') ** abs(precision)
            return (valor / factor).quantize(Decimal('0'), rounding=ROUND_HALF_UP) * factor
    
    def _rt_met_01(self, payslip_data):
        """
        Calcula la retención en la fuente según el procedimiento 1
        
        Utiliza los servicios de LavishToolsNomina para facilitar los cálculos.
        
        Args:
            payslip_data: Dict con datos de nómina
                
        Returns:
            tuple: (base, -1, rate, name, html_report, data_reporte)
        """
        herramientas = self.env['lavish.tools.nomina']
        
        if payslip_data['contract'].contract_type == 'aprendizaje':
            return 0, -1, 0, '', '', False
            
        aplicar = self.aplicar_cobro
        day = payslip_data['slip'].date_from.day
        
        if (aplicar != "0" and  
            ((aplicar == "15" and day > 15) or 
            (aplicar == "30" and day < 16))): 
            return 0, -1, 0, '', '', False

        if payslip_data['contract'].retention_procedure == 'fixed':
            valor_fijo = payslip_data['contract'].fixed_value_retention_procedure
            
            data_reporte = {
                'tipo': 'monto_fijo',
                'valor': float(valor_fijo),
                'employee_name': payslip_data['employee'].name,
                'employee_document': payslip_data['employee'].identification_id,
                'year': payslip_data['slip'].date_to.year
            }
            
            html_report = self.generar_html_retencion(data_reporte)
            
            return valor_fijo, -1, 100, f'Retención en la fuente - Monto fijo: {valor_fijo}', html_report, [data_reporte]

        payslip = payslip_data['slip']
        contract = payslip_data['contract']
        employee = payslip_data['employee']
        annual_parameters = payslip_data['annual_parameters']
        
        dias = herramientas.calcular_dias(payslip_data)
        dias_trabajados = Decimal(str(dias['trabajados']))
        dias_nov_remunerada = Decimal(str(dias.get('ausencias', 0)))
        
        debe_proyectar = contract.proyectar_ret and payslip.date_from.day <= 15
        
        pasos = []
        pasos.append({'descripcion': 'Inicio cálculo procedimiento 1', 'resultado': 'Evaluando factores'})
        
        if debe_proyectar:
            pasos.append({'descripcion': 'Proyección', 'resultado': 'Debe proyectarse por ser primera quincena'})
        
        ingresos = {
            'salario': Decimal(str(herramientas.totalizar_categorias(payslip_data, categorias='BASIC', periodos=['current_month', 'multi'])['total'])),
            'comisiones': Decimal(str(herramientas.totalizar_reglas(payslip_data, 'COMISIONES', periodos=['current_month', 'multi'])['total'])),
            'dev_salarial': Decimal('0'),
            'dev_no_salarial': Decimal('0')
        }
        
        dev_salarial_total = Decimal(str(herramientas.totalizar_categorias(payslip_data, categorias='DEV_SALARIAL', periodos=['current_month', 'multi'])['total']))
        ingresos['dev_salarial'] = dev_salarial_total - ingresos['salario'] - ingresos['comisiones']
        
        ingresos['dev_no_salarial'] = Decimal(str(herramientas.totalizar_categorias(payslip_data, categorias='DEV_NO_SALARIAL', excluir="INDEM", periodos=['current_month', 'multi'])['total']))
        
        excluidos = Decimal(str(herramientas.totalizar_reglas(
            payslip_data, 
            filtros={'custom_filter': lambda rule: rule.excluir_ret}, 
            periodos=['current_month', 'multi']
        )['total']))
        
        total_ing_base = ingresos['salario'] + ingresos['comisiones'] + ingresos['dev_salarial'] + ingresos['dev_no_salarial']
        
        
        valores_sin_proyectar = None
        aportes_sin_proyectar = None
        
        aportes = {
            'pension': Decimal(str(abs(herramientas.totalizar_reglas(payslip_data, 'SSOCIAL002', periodos=['current_month', 'multi'])['total']))),
            'subsistencia': Decimal(str(abs(herramientas.totalizar_reglas(payslip_data, 'SSOCIAL003', periodos=['current_month', 'multi'])['total']))),
            'solidaridad': Decimal(str(abs(herramientas.totalizar_reglas(payslip_data, 'SSOCIAL004', periodos=['current_month', 'multi'])['total']))),
            'salud': Decimal(str(abs(herramientas.totalizar_reglas(payslip_data, 'SSOCIAL001', periodos=['current_month', 'multi'])['total'])))
        }
        
        if debe_proyectar:
            valores_sin_proyectar = {
                'basic': float(ingresos['salario']),
                'comisiones': float(ingresos['comisiones']),
                'dev_salarial': float(ingresos['dev_salarial']),
                'dev_no_salarial': float(ingresos['dev_no_salarial']),
                'otros_ing_grav': float(ingresos['dev_salarial'] + ingresos['dev_no_salarial']),
                'total_ing_base': float(total_ing_base)
            }
            
            aportes_sin_proyectar = {
                'pension': float(aportes['pension']),
                'subsistencia': float(aportes['subsistencia']),
                'solidaridad': float(aportes['solidaridad']),
                'pension_total': float(aportes['pension'] + aportes['subsistencia'] + aportes['solidaridad']),
                'salud': float(aportes['salud']),
                'total': float(aportes['pension'] + aportes['subsistencia'] + aportes['solidaridad'] + aportes['salud'])
            }
            
            proyeccion = herramientas.proyectar_nomina(
                payslip_data,
                dias_trabajados=float(dias_trabajados),
                dias_proyectar=None  
            )
            
            if proyeccion['factor_proyeccion'] > 0:
                factor = Decimal(str(proyeccion['factor_proyeccion']))
                pasos.append({'descripcion': 'Factor de proyección', 'valor': float(factor)})
                
                for concepto, datos in proyeccion['proyectados'].items():
                    if concepto.startswith('BASIC'):
                        ingresos['salario'] = Decimal(str(datos['valor_completo']))
                    elif concepto == 'COMISIONES':
                        ingresos['comisiones'] = Decimal(str(datos['valor_completo']))
                
                dev_salarial_proyectado = Decimal(str(herramientas.totalizar_categorias(
                    payslip_data, 
                    categorias='DEV_SALARIAL', 
                    periodos=['current_month', 'multi']
                )['total'])) * (Decimal('1') + factor)
                
                ingresos['dev_salarial'] = dev_salarial_proyectado - ingresos['salario'] - ingresos['comisiones']
                ingresos['dev_no_salarial'] = ingresos['dev_no_salarial'] * (Decimal('1') + factor)
                
                total_ing_base = ingresos['salario'] + ingresos['comisiones'] + ingresos['dev_salarial'] + ingresos['dev_no_salarial']
                
                for clave in aportes:
                    aportes[clave] = aportes[clave] * (Decimal('1') + factor)
    
        total_pension = aportes['pension'] + aportes['subsistencia'] + aportes['solidaridad']
        ing_no_gravados = total_pension + aportes['salud']
        ing_base = total_ing_base - ing_no_gravados
        
        desglose_pension = {
            'pension': float(aportes['pension']),
            'subsistencia': float(aportes['subsistencia']),
            'solidaridad': float(aportes['solidaridad'])
        }
        
        value_uvt = Decimal(str(annual_parameters.value_uvt))
        deducciones = {
            'vivienda': Decimal(str(self._calcular_deduccion_vivienda(contract, payslip.date_to, value_uvt))),
            'dependientes': Decimal(str(self._calcular_deduccion_dependientes(contract, payslip.date_to, total_ing_base, value_uvt))),
            'salud': Decimal(str(self._calcular_deduccion_salud(contract, payslip.date_to, value_uvt)))
        }
        total_deducciones = deducciones['vivienda'] + deducciones['dependientes'] + deducciones['salud']
        
        re_afc = Decimal(str(abs(herramientas.extraer_valor(payslip_data, 'AFC', periodo='current_month', campo='total', default=0.0))))
        total_re = min(
            re_afc,
            total_ing_base * Decimal('0.3'),
            value_uvt * (Decimal('3800')/Decimal('12'))
        )
        
        subtotal_ibr1 = ing_base - total_deducciones
        subtotal_ibr2 = subtotal_ibr1 - total_re
        renta_exenta_25 = min(
            self._round_decimal(subtotal_ibr2 * Decimal('0.25'), -3),
            value_uvt * (Decimal('790')/Decimal('12'))
        )
        
        total_beneficios = total_deducciones + total_re + renta_exenta_25
        limite_40 = ing_base * Decimal('0.4')
        limite_uvt = value_uvt * (Decimal('1340')/Decimal('12'))
        beneficios_limitados = min(total_beneficios, limite_40, limite_uvt)
        
        subtotal_ibr3 = ing_base - beneficios_limitados
        
        ibr_uvts = subtotal_ibr3 / value_uvt
        retencion, rate, resta_uvt = self._calcular_retencion(ibr_uvts, value_uvt)
        
        retencion_anterior = Decimal(str(abs(herramientas.extraer_valor(
            payslip_data,
            'RT_MET_01',
            periodo='current_month',
            campo='total',
            default=0.0
        ))))
            
        retencion_def = self._round_decimal(retencion - retencion_anterior, -3)
        if retencion_def < Decimal('0'):
            retencion_def = Decimal('0')
        if debe_proyectar:
            retencion_def /= Decimal(2)
        
        pasos.extend([
            {'descripcion': 'Ingresos base', 'desglose': [
                {'concepto': 'Salario', 'valor': float(ingresos['salario'])},
                {'concepto': 'Comisiones', 'valor': float(ingresos['comisiones'])},
                {'concepto': 'Devengos salariales', 'valor': float(ingresos['dev_salarial'])},
                {'concepto': 'Devengos no salariales', 'valor': float(ingresos['dev_no_salarial'])},
                {'concepto': 'Total ingresos base', 'valor': float(total_ing_base)}
            ]},
            {'descripcion': 'Aportes obligatorios', 'desglose': [
                {'concepto': 'Pensión total', 'valor': float(total_pension)},
                {'concepto': 'Salud', 'valor': float(aportes['salud'])},
                {'concepto': 'Total aportes', 'valor': float(ing_no_gravados)}
            ]},
            {'descripcion': 'Ingresos netos', 'valor': float(ing_base)},
            {'descripcion': 'Deducciones', 'desglose': [
                {'concepto': 'Vivienda', 'valor': float(deducciones['vivienda'])},
                {'concepto': 'Dependientes', 'valor': float(deducciones['dependientes'])},
                {'concepto': 'Salud prepagada', 'valor': float(deducciones['salud'])},
                {'concepto': 'Total deducciones', 'valor': float(total_deducciones)}
            ]},
            {'descripcion': 'Rentas exentas', 'desglose': [
                {'concepto': 'AFC', 'valor': float(re_afc)},
                {'concepto': 'Total rentas exentas', 'valor': float(total_re)}
            ]},
            {'descripcion': 'Subtotal 1 (Ingresos - Deducciones)', 'valor': float(subtotal_ibr1)},
            {'descripcion': 'Subtotal 2 (Subtotal 1 - Rentas Exentas)', 'valor': float(subtotal_ibr2)},
            {'descripcion': 'Renta exenta 25%', 'valor': float(renta_exenta_25)},
            {'descripcion': 'Limitación beneficios', 'desglose': [
                {'concepto': 'Total beneficios', 'valor': float(total_beneficios)},
                {'concepto': 'Límite 40%', 'valor': float(limite_40)},
                {'concepto': 'Límite UVT', 'valor': float(limite_uvt)},
                {'concepto': 'Beneficios limitados', 'valor': float(beneficios_limitados)}
            ]},
            {'descripcion': 'Base gravable final', 'valor': float(subtotal_ibr3)},
            {'descripcion': 'Base en UVTs', 'valor': float(ibr_uvts)},
            {'descripcion': 'Tarifa aplicable', 'valor': f"{float(rate)}%"},
            {'descripcion': 'Retención calculada', 'valor': float(retencion)},
            {'descripcion': 'Retención anterior', 'valor': float(retencion_anterior)},
            {'descripcion': 'Retención a aplicar', 'valor': float(retencion_def)}
        ])
        
        # 15. Generar datos para el reporte
        data_reporte = {
            'tipo': 'calculo_normal',
            'dias_trabajados': float(dias_trabajados),
            'dias_nov_remunerada': float(dias_nov_remunerada),
            'salario': float(ingresos['salario']),
            'comisiones': float(ingresos['comisiones']),
            'dev_salarial': float(ingresos['dev_salarial']),
            'dev_no_salarial': float(ingresos['dev_no_salarial']),
            'excluidos': float(excluidos),
            'total_ing_base': float(total_ing_base),
            'total_pension': float(total_pension),
            'salud': float(aportes['salud']),
            'ing_no_gravados': float(ing_no_gravados),
            'ing_base': float(ing_base),
            'ded_vivienda': float(deducciones['vivienda']),
            'ded_dependientes': float(deducciones['dependientes']),
            'ded_salud': float(deducciones['salud']),
            'total_deducciones': float(total_deducciones),
            're_afc': float(re_afc),
            'total_re': float(total_re),
            'subtotal_ibr1': float(subtotal_ibr1),
            'subtotal_ibr2': float(subtotal_ibr2),
            'renta_exenta_25': float(renta_exenta_25),
            'subtotal_ibr3': float(subtotal_ibr3),
            'ibr_uvts': float(ibr_uvts),
            'retencion': float(retencion),
            'retencion_anterior': float(retencion_anterior),
            'retencion_def': float(retencion_def),
            'uvt': value_uvt,
            'rate': float(rate),
            'resta_uvt': float(resta_uvt),
            'es_proyectado': debe_proyectar,
            'valores_sin_proyectar': valores_sin_proyectar,
            'aportes_sin_proyectar': aportes_sin_proyectar,
            'desglose_pension': desglose_pension,
            'pasos': pasos,
            'employee_name': employee.name,
            'employee_document': employee.identification_id,
            'year': payslip.date_to.year
        }
        
        # Generar HTML para informe detallado
        html_report = self.generar_html_retencion(data_reporte)
        report_obj = self.env['lavish.retencion.reporte']
        existing_report = report_obj.search([
            ('employee_id', '=', employee.id),
            ('payslip_id', '=', payslip.id)
        ])
        if existing_report:
            existing_report.unlink()
        
        report_obj.create({
            'employee_id': employee.id,
            'date': payslip.date_to,
            'payslip_id': payslip.id,
            'year': payslip.date_to.year,
            'month': payslip.date_to.month,
            'quincena': '1' if payslip.date_from.day <= 15 else '2',
            
            'salario_basico': float(ingresos['salario']),
            'comisiones': float(ingresos['comisiones']),
            'dev_salarial': float(ingresos['dev_salarial']),
            'dev_no_salarial': float(ingresos['dev_no_salarial']),
            'total_ingresos': float(total_ing_base),
            
            'salud': float(aportes['salud']),
            'pension': float(aportes['pension']),
            'subsistencia': float(aportes['subsistencia']),
            'solidaridad': float(aportes['solidaridad']),
            'pension_total': float(total_pension),
            'total_aportes': float(ing_no_gravados),
            
            'ded_vivienda': float(deducciones['vivienda']),
            'ded_dependientes': float(deducciones['dependientes']),
            'ded_salud': float(deducciones['salud']),
            'total_deducciones': float(total_deducciones),
            
            'valor_avp_afc': float(re_afc),
            'renta_exenta_25': float(renta_exenta_25),
            'total_rentas_exentas': float(total_re + renta_exenta_25),
            
            'subtotal_ibr1': float(subtotal_ibr1),
            'subtotal_ibr2': float(subtotal_ibr2),
            
            'beneficios_limitados': float(beneficios_limitados),
            
            'base_gravable': float(subtotal_ibr3),
            'ibr_uvts': float(ibr_uvts),
            'tasa_aplicada': float(rate),
            'retencion_calculada': float(retencion),
            'retencion_anterior': float(retencion_anterior),
            'retencion_aplicada': float(retencion_def),
            
            'base_legal': 'Art. 385-389 ET, Ley 2277/2022',
            'uvt_valor': float(value_uvt),
            'ingresos_totales': float(total_ing_base),
            'es_proyectado': debe_proyectar,
            
            'reporte_json': json.dumps(data_reporte, default=json_serial),
            'html_reporte': html_report
        })
        return retencion_def, -1, 100, f'Retención en la fuente - Base: {float(subtotal_ibr3):,.2f}', html_report, [data_reporte]
    
    def generar_html_retencion(self, resultado):
        """
        Genera HTML para visualización del cálculo de retención.
        
        Args:
            resultado: Diccionario con los datos del último elemento de la tupla
                     retornada por _rtf_indem o _rt_met_01
                     
        Returns:
            HTML formateado para visualizar el cálculo
        """
        if resultado.get("tipo") == "monto_fijo":
            valor_fijo = resultado.get("valor", 0)
            
            html = f"""
            <div class="card">
                <div class="card-header bg-primary text-white">
                    <h4>Cálculo de Retención en la Fuente</h4>
                    <h5 class="text-white">{resultado.get('employee_name', '')}</h5>
                </div>
                <div class="card-body">
                    <div class="alert alert-warning" role="alert">
                        <strong>Advertencia:</strong> Se está aplicando un valor fijo de retención establecido por el usuario.
                        Este valor no se calcula según el procedimiento estándar.
                    </div>
                    <div class="mt-4 text-center">
                        <h5>Valor de retención fijo:</h5>
                        <span class="badge rounded-pill bg-success-light p-3 fs-4">${valor_fijo:,.2f}</span>
                    </div>
                </div>
            </div>
            
            <style>
                .bg-success-light {{
                    background-color: #d1e7dd;
                    color: #0f5132;
                }}
                .fs-4 {{
                    font-size: 1.5rem;
                }}
                .p-3 {{
                    padding: 1rem !important;
                }}
                .badge.rounded-pill {{
                    border-radius: 50rem;
                }}
            </style>
            """
            
            return html
        

        html = """
        <div class="card">
            <div class="card-header bg-primary text-white">
                <h4>Cálculo de Retención en la Fuente</h4>
        """
    
        if "employee_name" in resultado:
            html += f"""
                <h5 class="text-white">{resultado['employee_name']}</h5>
            """
            
        html += """
            </div>
            <div class="card-body">
        """
        
        es_proyectado = False
        valores_sin_proyectar = None
        aportes_sin_proyectar = None
        desglose_pension = None
        
        if resultado.get("tipo") == "calculo_normal":
            if resultado.get("es_proyectado", False):
                es_proyectado = True
                valores_sin_proyectar = resultado.get("valores_sin_proyectar", {})
                aportes_sin_proyectar = resultado.get("aportes_sin_proyectar", {})
                desglose_pension = resultado.get("desglose_pension", {})
        
        if es_proyectado:
            html += """
                <div class="alert alert-info" role="alert">
                    <strong>Nota:</strong> Los valores han sido proyectados para el cálculo de la retención.
                    Se muestran ambos valores (sin proyectar y proyectados) para comparación.
                </div>
            """
        
        if "pasos" in resultado:
            html += """
                <h5>Pasos del Cálculo</h5>
                <div class="table-responsive">
                    <table class="table table-sm table-striped">
                        <thead>
                            <tr>
                                <th>Paso</th>
                                <th>Descripción</th>
            """
            
            if es_proyectado:
                html += """
                                <th>Valor Base</th>
                                <th>Valor Proyectado</th>
                """
            else:
                html += """
                                <th>Valor</th>
                """
            
            html += """
                            </tr>
                        </thead>
                        <tbody>
            """
            
            for i, paso in enumerate(resultado["pasos"]):
                html += f"""
                    <tr>
                        <td>{i+1}</td>
                        <td>{paso['descripcion']}</td>
                """
                
                valor = paso.get("valor", paso.get("resultado", ""))
                
                if es_proyectado and paso["descripcion"] in ["Ingresos base", "Aportes obligatorios"]:
                    html += """
                        <td></td>
                        <td></td>
                    </tr>
                    """
                    
                    if "desglose" in paso:
                        if paso["descripcion"] == "Aportes obligatorios":
                            pension_total_item = None
                            otros_items = []
                            
                            for item in paso["desglose"]:
                                if item["concepto"] == "Pensión total":
                                    pension_total_item = item
                                else:
                                    otros_items.append(item)
                            
                            if pension_total_item:
                                valor_proyectado = pension_total_item["valor"]
                                valor_base = aportes_sin_proyectar.get("pension_total", 0) if aportes_sin_proyectar else 0
                                
                                html += f"""
                                <tr>
                                    <td></td>
                                    <td class="ps-4">- {pension_total_item['concepto']}</td>
                                """
                                
                                if valor_base > 0:
                                    html += f"""
                                    <td><span class="badge rounded-pill bg-light text-dark">${valor_base:,.2f}</span></td>
                                    <td><span class="badge rounded-pill bg-success text-white">${valor_proyectado:,.2f}</span></td>
                                    """
                                else:
                                    html += f"""
                                    <td></td>
                                    <td><span class="badge rounded-pill bg-light text-dark">${valor_proyectado:,.2f}</span></td>
                                    """
                                
                                html += """
                                </tr>
                                """
                                
                                if desglose_pension:
                                    pension = desglose_pension.get("pension", 0)
                                    pension_base = aportes_sin_proyectar.get("pension", 0) if aportes_sin_proyectar else 0
                                    
                                    html += f"""
                                    <tr>
                                        <td></td>
                                        <td class="ps-5">* Aporte Pensión</td>
                                    """
                                    
                                    if pension_base > 0:
                                        html += f"""
                                        <td><span class="badge rounded-pill bg-light text-dark">${pension_base:,.2f}</span></td>
                                        <td><span class="badge rounded-pill bg-success text-white">${pension:,.2f}</span></td>
                                        """
                                    else:
                                        html += f"""
                                        <td></td>
                                        <td><span class="badge rounded-pill bg-light text-dark">${pension:,.2f}</span></td>
                                        """
                                    
                                    html += """
                                    </tr>
                                    """
                                    
                                    solidaridad = desglose_pension.get("solidaridad", 0)
                                    solidaridad_base = aportes_sin_proyectar.get("solidaridad", 0) if aportes_sin_proyectar else 0
                                    
                                    html += f"""
                                    <tr>
                                        <td></td>
                                        <td class="ps-5">* Fondo de Solidaridad</td>
                                    """
                                    
                                    if solidaridad_base > 0:
                                        html += f"""
                                        <td><span class="badge rounded-pill bg-light text-dark">${solidaridad_base:,.2f}</span></td>
                                        <td><span class="badge rounded-pill bg-success text-white">${solidaridad:,.2f}</span></td>
                                        """
                                    else:
                                        html += f"""
                                        <td></td>
                                        <td><span class="badge rounded-pill bg-light text-dark">${solidaridad:,.2f}</span></td>
                                        """
                                    
                                    html += """
                                    </tr>
                                    """
                                    
                                    subsistencia = desglose_pension.get("subsistencia", 0)
                                    subsistencia_base = aportes_sin_proyectar.get("subsistencia", 0) if aportes_sin_proyectar else 0
                                    
                                    html += f"""
                                    <tr>
                                        <td></td>
                                        <td class="ps-5">* Subsistencia</td>
                                    """
                                    
                                    if subsistencia_base > 0:
                                        html += f"""
                                        <td><span class="badge rounded-pill bg-light text-dark">${subsistencia_base:,.2f}</span></td>
                                        <td><span class="badge rounded-pill bg-success text-white">${subsistencia:,.2f}</span></td>
                                        """
                                    else:
                                        html += f"""
                                        <td></td>
                                        <td><span class="badge rounded-pill bg-light text-dark">${subsistencia:,.2f}</span></td>
                                        """
                                    
                                    html += """
                                    </tr>
                                    """
                            
                            for item in otros_items:
                                concepto = item["concepto"]
                                valor_proyectado = item["valor"]
                                valor_base = None
                                
                                if concepto == "Salud":
                                    valor_base = aportes_sin_proyectar.get("salud", 0) if aportes_sin_proyectar else 0
                                elif concepto == "Total aportes":
                                    valor_base = aportes_sin_proyectar.get("total", 0) if aportes_sin_proyectar else 0
                                
                                html += f"""
                                <tr>
                                    <td></td>
                                    <td class="ps-4">- {concepto}</td>
                                """
                                
                                if valor_base is not None and valor_base > 0:
                                    html += f"""
                                    <td><span class="badge rounded-pill bg-light text-dark">${valor_base:,.2f}</span></td>
                                    <td><span class="badge rounded-pill bg-success text-white">${valor_proyectado:,.2f}</span></td>
                                    """
                                else:
                                    html += f"""
                                    <td></td>
                                    <td><span class="badge rounded-pill bg-light text-dark">${valor_proyectado:,.2f}</span></td>
                                    """
                                
                                html += """
                                </tr>
                                """
                        else:
                            for item in paso["desglose"]:
                                concepto = item["concepto"]
                                valor_proyectado = item["valor"]
                                valor_base = None
                                
                                if paso["descripcion"] == "Ingresos base":
                                    if concepto == "Salario" and valores_sin_proyectar:
                                        valor_base = valores_sin_proyectar.get("basic", 0)
                                    elif concepto == "Comisiones" and valores_sin_proyectar:
                                        valor_base = valores_sin_proyectar.get("comisiones", 0)
                                    elif concepto == "Devengos salariales" and valores_sin_proyectar:
                                        valor_base = valores_sin_proyectar.get("dev_salarial", 0)
                                    elif concepto == "Devengos no salariales" and valores_sin_proyectar:
                                        valor_base = valores_sin_proyectar.get("dev_no_salarial", 0)
                                    elif concepto == "Total ingresos base" and valores_sin_proyectar:
                                        valor_base = valores_sin_proyectar.get("total_ing_base", 0)
                                
                                html += f"""
                                <tr>
                                    <td></td>
                                    <td class="ps-4">- {concepto}</td>
                                """
                                
                                if valor_base is not None and valor_base > 0:
                                    html += f"""
                                    <td><span class="badge rounded-pill bg-light text-dark">${valor_base:,.2f}</span></td>
                                    <td><span class="badge rounded-pill bg-success text-white">${valor_proyectado:,.2f}</span></td>
                                    """
                                else:
                                    html += f"""
                                    <td></td>
                                    <td><span class="badge rounded-pill bg-light text-dark">${valor_proyectado:,.2f}</span></td>
                                    """
                                
                                html += """
                                </tr>
                                """
                else:
                    if es_proyectado:
                        html += f"""
                            <td></td>
                            <td>{valor if isinstance(valor, str) else f'<span class="badge rounded-pill bg-light text-dark">${valor:,.2f}</span>' if valor else ""}</td>
                        </tr>
                        """
                    else:
                        html += f"""
                            <td>{valor if isinstance(valor, str) else f'<span class="badge rounded-pill bg-light text-dark">${valor:,.2f}</span>' if valor else ""}</td>
                        </tr>
                        """
                    
                    if "desglose" in paso and paso["descripcion"] not in ["Ingresos base", "Aportes obligatorios"]:
                        for item in paso["desglose"]:
                            html += f"""
                            <tr>
                                <td></td>
                                <td class="ps-4">- {item['concepto']}</td>
                            """
                            
                            if es_proyectado:
                                html += f"""
                                <td></td>
                                <td><span class="badge rounded-pill bg-light text-dark">${item['valor']:,.2f}</span></td>
                                """
                            else:
                                html += f"""
                                <td><span class="badge rounded-pill bg-light text-dark">${item['valor']:,.2f}</span></td>
                                """
                            
                            html += """
                            </tr>
                            """
            
            html += """
                        </tbody>
                    </table>
                </div>
            """
        
        html += """
            </div>
        </div>
        
        <style>
            .badge.rounded-pill {
                padding: 0.5rem 0.8rem;
                font-size: 90%;
                font-weight: normal;
                border-radius: 50rem;
            }
            .table td, .table th {
                vertical-align: middle;
            }
            .bg-success-light {
                background-color: #d1e7dd;
                color: #0f5132;
            }
            .bg-light {
                background-color: #f8f9fa;
                color: #212529;
            }
            .bg-success {
                background-color: #198754;
                color: white;
            }
            .ps-4 {
                padding-left: 1.5rem !important;
            }
            .ps-5 {
                padding-left: 3rem !important;
            }
        </style>
        """
        
        return html

class LavishRetencionAcumulados(models.Model):
    _name = 'lavish.retencion.acumulados'
    _description = 'Acumulados para retención en la fuente'
    
    employee_id = fields.Many2one('hr.employee', 'Empleado', required=True)
    year = fields.Integer('Año', required=True)
    month = fields.Integer('Mes', default=0)
    quincena = fields.Selection([
        ('0', 'No aplica'),
        ('1', 'Primera quincena'),
        ('2', 'Segunda quincena')
    ], string='Quincena', default='0', required=True)
    date = fields.Date('Fecha', required=True)
    tipo = fields.Selection([
        ('avp_afc', 'AVP/AFC'),
        ('renta_exenta_25', 'Renta exenta 25%'),
        ('beneficios_40', 'Límite 40%'),
        ('periodo', 'Registro por periodo')
    ], string='Tipo de acumulado', required=True)
    
    valor_acumulado = fields.Float('Valor acumulado', default=0.0)
    last_update = fields.Date('Última actualización')
    
    avp_afc_periodo = fields.Float('AVP/AFC del periodo', default=0.0)
    renta_exenta_25_periodo = fields.Float('Renta exenta 25% del periodo', default=0.0)
    beneficios_40_periodo = fields.Float('Beneficios 40% del periodo', default=0.0)
    payslip_id = fields.Many2one('hr.payslip', 'Liquidación')
    



class LavishRetencionReporte(models.Model):
    _name = 'lavish.retencion.reporte'
    _description = 'Reporte de retención en la fuente'
    _order = 'year desc, month desc, quincena desc'
    
    name = fields.Char('Referencia', compute='_compute_name', store=True)
    employee_id = fields.Many2one('hr.employee', 'Empleado', required=True)
    date = fields.Date('Fecha', required=True)
    payslip_id = fields.Many2one('hr.payslip', 'Liquidación')
    
    year = fields.Integer('Año', required=True)
    month = fields.Integer('Mes', required=True)
    quincena = fields.Selection([
        ('0', 'Mensual'),
        ('1', 'Primera quincena'),
        ('2', 'Segunda quincena')
    ], string='Quincena', default='0', required=True)
    
    salario_basico = fields.Float('Salario básico', default=0.0)
    comisiones = fields.Float('Comisiones', default=0.0)
    dev_salarial = fields.Float('Devengos salariales', default=0.0)
    dev_no_salarial = fields.Float('Devengos no salariales', default=0.0)
    total_ingresos = fields.Float('Total ingresos laborales', default=0.0)
    
    salud = fields.Float('Aporte a salud', default=0.0)
    pension = fields.Float('Aporte a pensión', default=0.0)
    subsistencia = fields.Float('Fondo subsistencia', default=0.0)
    solidaridad = fields.Float('Fondo solidaridad', default=0.0)
    pension_total = fields.Float('Total aportes pensión', default=0.0)
    total_aportes = fields.Float('Total aportes obligatorios', default=0.0)
    
    ded_vivienda = fields.Float('Deducción vivienda', default=0.0)
    ded_dependientes = fields.Float('Deducción dependientes', default=0.0)
    ded_salud = fields.Float('Deducción salud prepagada', default=0.0)
    total_deducciones = fields.Float('Total deducciones', default=0.0)
    
    valor_avp_afc = fields.Float('Valor AVP/AFC', default=0.0)
    renta_exenta_25 = fields.Float('Renta exenta 25%', default=0.0)
    total_rentas_exentas = fields.Float('Total rentas exentas', default=0.0)
    
    subtotal_ibr1 = fields.Float('Subtotal 1 (Ingresos - Deducciones)', default=0.0)
    subtotal_ibr2 = fields.Float('Subtotal 2 (Subtotal 1 - AVP/AFC)', default=0.0)
    
    beneficios_limitados = fields.Float('Beneficios limitados', default=0.0)
    
    base_gravable = fields.Float('Base gravable')
    ibr_uvts = fields.Float('Base gravable en UVTs', default=0.0)
    tasa_aplicada = fields.Float('Tasa aplicada %', default=0.0)
    retencion_calculada = fields.Float('Retención calculada', default=0.0)
    retencion_anterior = fields.Float('Retención anterior', default=0.0)
    retencion_aplicada = fields.Float('Retención aplicada')
    
    base_legal = fields.Text('Base legal aplicada')
    uvt_valor = fields.Float('Valor UVT')
    ingresos_totales = fields.Float('Ingresos totales')
    es_proyectado = fields.Boolean('Es proyectado', default=False)
    
    reporte_json = fields.Text('Reporte detallado (JSON)')
    html_reporte = fields.Html('Reporte HTML')
    excel_file = fields.Binary('Archivo Excel')
    excel_filename = fields.Char('Nombre del archivo')
    
    def _get_company_data(self):
        """Obtiene los datos de la empresa actual"""
        company = self.env.company
        return {
            'name': company.name,
            'vat': company.vat,
            'phone': company.phone,
            'email': company.email,
            'website': company.website,
            'street': company.street,
            'city': company.city,
            'country': company.country_id.name if company.country_id else '',
            'logo': company.logo,
        }
    
    def _get_month_name(self, month_number):
        """Obtiene el nombre del mes a partir de su número"""
        meses = {
            1: 'Enero', 2: 'Febrero', 3: 'Marzo', 4: 'Abril',
            5: 'Mayo', 6: 'Junio', 7: 'Julio', 8: 'Agosto',
            9: 'Septiembre', 10: 'Octubre', 11: 'Noviembre', 12: 'Diciembre'
        }
        return meses.get(month_number, f"Mes {month_number}")
    
    def _format_period(self, year, month, quincena):
        """Formatea el periodo para mostrar en reportes"""
        mes = self._get_month_name(month)
        if quincena == '0':
            return f"{mes} {year}"
        else:
            quincena_str = 'Q1' if quincena == '1' else 'Q2'
            return f"{mes} {quincena_str} {year}"
    
    def _add_explanatory_notes(self, worksheet, row, format_title, format_text, width):
        """Agrega notas explicativas al reporte"""
        # Título de la sección
        worksheet.merge_range(f'A{row}:{width}{row}', 'NOTAS EXPLICATIVAS SOBRE EL CÁLCULO DE RETENCIÓN', format_title)
        row += 1
        
        # Notas explicativas
        notes = [
            ('1. Base Legal:', 'La retención en la fuente se calcula según los artículos 383 a 389 del Estatuto Tributario y la Ley 2277 de 2022.'),
            ('2. Límite Global 40%:', 'La suma de deducciones y rentas exentas no puede exceder el 40% del ingreso neto, con un límite máximo de 1.340 UVT anuales.'),
            ('3. Rentas Exentas:', 'Los aportes voluntarios a pensión y AFC están limitados al 30% del ingreso y 3.800 UVT anuales.'),
            ('4. Renta Exenta 25%:', 'La renta exenta del 25% está limitada a 790 UVT anuales.'),
            ('5. Proyección:', 'En primera quincena, se proyecta el ingreso mensual para calcular la retención, aplicando solo el 50% del valor calculado.'),
            ('6. Depuración:', 'El proceso de depuración sigue el siguiente orden: ingresos, ingresos no constitutivos de renta, deducciones, rentas exentas, límite 40%, base gravable y aplicación de tarifa.'),
            ('7. UVT:', f'Valor UVT para el año fiscal: Revisar el valor en cada registro (columna UVT).')
        ]
        
        # Escribir cada nota
        for title, content in notes:
            worksheet.merge_range(f'A{row}:B{row}', title, format_text)
            worksheet.merge_range(f'C{row}:{width}{row}', content, format_text)
            row += 1
        
        return row + 1  # Retornar la siguiente fila disponible
    
    def action_export_standard(self):
        if not self:
            raise models.UserError('No hay registros seleccionados para exportar.')
            
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        
        title_format = workbook.add_format({
            'bold': True, 'font_size': 14, 'align': 'center', 
            'valign': 'vcenter', 'bg_color': '#1E6C93', 'font_color': 'white'
        })
        header_format = workbook.add_format({
            'bold': True, 'font_size': 11, 'align': 'center', 
            'valign': 'vcenter', 'bg_color': '#D9EDF7', 'border': 1
        })
        subheader_format = workbook.add_format({
            'bold': True, 'font_size': 10, 'align': 'left', 
            'valign': 'vcenter', 'bg_color': '#F5F5F5', 'border': 1
        })
        section_format = workbook.add_format({
            'bold': True, 'font_size': 12, 'align': 'left', 
            'valign': 'vcenter', 'bg_color': '#E6F3F8', 'border': 1
        })
        cell_format = workbook.add_format({
            'font_size': 10, 'align': 'left', 'border': 1
        })
        number_format = workbook.add_format({
            'font_size': 10, 'align': 'right', 'border': 1,
            'num_format': '#,##0.00'
        })
        money_format = workbook.add_format({
            'font_size': 10, 'align': 'right', 'border': 1,
            'num_format': '$#,##0.00'
        })
        percent_format = workbook.add_format({
            'font_size': 10, 'align': 'right', 'border': 1,
            'num_format': '0.00%'
        })
        total_format = workbook.add_format({
            'bold': True, 'font_size': 11, 'align': 'right', 'border': 1,
            'num_format': '$#,##0.00', 'bg_color': '#F5F5F5'
        })
        company_format = workbook.add_format({
            'bold': True, 'font_size': 12, 'align': 'left',
            'valign': 'vcenter'
        })
        date_format = workbook.add_format({
            'font_size': 10, 'align': 'center', 'border': 1,
            'num_format': 'dd/mm/yyyy'
        })
        note_title_format = workbook.add_format({
            'bold': True, 'font_size': 11, 'align': 'left',
            'bg_color': '#FCF8E3', 'border': 1
        })
        note_text_format = workbook.add_format({
            'font_size': 10, 'align': 'left', 'border': 1,
            'text_wrap': True
        })
        
        company_data = self._get_company_data()
        
        worksheet = workbook.add_worksheet('Retenciones')
        
        worksheet.set_column('A:A', 30)
        worksheet.set_column('B:Z', 15)
        
        worksheet.merge_range('A1:H1', company_data['name'], company_format)
        worksheet.merge_range('A2:H2', f"NIT: {company_data['vat']}", cell_format)
        worksheet.merge_range('A3:H3', f"Teléfono: {company_data['phone']} - Email: {company_data['email']}", cell_format)
        worksheet.merge_range('A4:H4', f"Dirección: {company_data['street']}, {company_data['city']}, {company_data['country']}", cell_format)
        current_date = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        worksheet.merge_range('A6:H6', 'REPORTE COMPLETO DE RETENCIÓN EN LA FUENTE', title_format)
        worksheet.merge_range('A7:H7', f"Fecha generación: {current_date}", cell_format)
        worksheet.merge_range('A8:H8', f"Total registros: {len(self)}", cell_format)
        worksheet.merge_range('A9:H9', f"Total empleados: {len(self.mapped('employee_id'))}", cell_format)
        
        row = 11
        all_fields_headers = [
            'Empleado', 'Documento', 'Periodo', 'UVT', '¿Proyectado?',
            'Salario', 'Comisiones', 'Dev. Salarial', 'Dev. No Salarial', 'Total Ingresos',
            'Pensión Total', 'Salud', 'Total Aportes', 
            'Vivienda', 'Dependientes', 'Salud Prep.', 'Total Deducciones',
            'AVP/AFC', 'Renta Ex. 25%', 'Total Rentas Exentas',
            'Subtotal 1', 'Subtotal 2', 'Beneficios Limit.', 
            'Base Gravable', 'Base UVTs', 'Tasa %', 'Retención'
        ]
        
        for col, header in enumerate(all_fields_headers):
            worksheet.write(row, col, header, header_format)
        
        row += 1
        
        for record in self:
            periodo = self._format_period(record.year, record.month, record.quincena)
            
            col = 0
            worksheet.write(row, col, record.employee_id.name, cell_format); col += 1
            worksheet.write(row, col, record.employee_id.identification_id, cell_format); col += 1
            worksheet.write(row, col, periodo, cell_format); col += 1
            worksheet.write(row, col, record.uvt_valor, number_format); col += 1
            worksheet.write(row, col, "Sí" if record.es_proyectado else "No", cell_format); col += 1
            
            worksheet.write(row, col, record.salario_basico, money_format); col += 1
            worksheet.write(row, col, record.comisiones, money_format); col += 1
            worksheet.write(row, col, record.dev_salarial, money_format); col += 1
            worksheet.write(row, col, record.dev_no_salarial, money_format); col += 1
            worksheet.write(row, col, record.total_ingresos, money_format); col += 1
            
            worksheet.write(row, col, record.pension_total, money_format); col += 1
            worksheet.write(row, col, record.salud, money_format); col += 1
            worksheet.write(row, col, record.total_aportes, money_format); col += 1
            
            worksheet.write(row, col, record.ded_vivienda, money_format); col += 1
            worksheet.write(row, col, record.ded_dependientes, money_format); col += 1
            worksheet.write(row, col, record.ded_salud, money_format); col += 1
            worksheet.write(row, col, record.total_deducciones, money_format); col += 1
            
            worksheet.write(row, col, record.valor_avp_afc, money_format); col += 1
            worksheet.write(row, col, record.renta_exenta_25, money_format); col += 1
            worksheet.write(row, col, record.total_rentas_exentas, money_format); col += 1
            
            worksheet.write(row, col, record.subtotal_ibr1, money_format); col += 1
            worksheet.write(row, col, record.subtotal_ibr2, money_format); col += 1
            worksheet.write(row, col, record.beneficios_limitados, money_format); col += 1
            
            worksheet.write(row, col, record.base_gravable, money_format); col += 1
            worksheet.write(row, col, record.ibr_uvts, number_format); col += 1
            worksheet.write(row, col, record.tasa_aplicada / 100, percent_format); col += 1
            worksheet.write(row, col, record.retencion_aplicada, money_format); col += 1
            
            row += 1
        
        col = 0
        worksheet.write(row, col, 'TOTALES', subheader_format); col += 1
        worksheet.write(row, col, '', subheader_format); col += 1
        worksheet.write(row, col, '', subheader_format); col += 1
        worksheet.write(row, col, '', subheader_format); col += 1
        worksheet.write(row, col, '', subheader_format); col += 1
        
        worksheet.write(row, col, sum(r.salario_basico for r in self), total_format); col += 1
        worksheet.write(row, col, sum(r.comisiones for r in self), total_format); col += 1
        worksheet.write(row, col, sum(r.dev_salarial for r in self), total_format); col += 1
        worksheet.write(row, col, sum(r.dev_no_salarial for r in self), total_format); col += 1
        worksheet.write(row, col, sum(r.total_ingresos for r in self), total_format); col += 1
        
        worksheet.write(row, col, sum(r.pension_total for r in self), total_format); col += 1
        worksheet.write(row, col, sum(r.salud for r in self), total_format); col += 1
        worksheet.write(row, col, sum(r.total_aportes for r in self), total_format); col += 1
        
        worksheet.write(row, col, sum(r.ded_vivienda for r in self), total_format); col += 1
        worksheet.write(row, col, sum(r.ded_dependientes for r in self), total_format); col += 1
        worksheet.write(row, col, sum(r.ded_salud for r in self), total_format); col += 1
        worksheet.write(row, col, sum(r.total_deducciones for r in self), total_format); col += 1
        
        worksheet.write(row, col, sum(r.valor_avp_afc for r in self), total_format); col += 1
        worksheet.write(row, col, sum(r.renta_exenta_25 for r in self), total_format); col += 1
        worksheet.write(row, col, sum(r.total_rentas_exentas for r in self), total_format); col += 1
        
        worksheet.write(row, col, sum(r.subtotal_ibr1 for r in self), total_format); col += 1
        worksheet.write(row, col, sum(r.subtotal_ibr2 for r in self), total_format); col += 1
        worksheet.write(row, col, sum(r.beneficios_limitados for r in self), total_format); col += 1
        
        worksheet.write(row, col, sum(r.base_gravable for r in self), total_format); col += 1
        worksheet.write(row, col, '', subheader_format); col += 1
        worksheet.write(row, col, '', subheader_format); col += 1
        worksheet.write(row, col, sum(r.retencion_aplicada for r in self), total_format); col += 1
        
        row += 2
        final_row = self._add_explanatory_notes(worksheet, row, note_title_format, note_text_format, 'AB')
        
        process_sheet = workbook.add_worksheet('Estadísticas')
        process_sheet.set_column('A:A', 25)
        process_sheet.set_column('B:E', 15)
        
        process_sheet.merge_range('A1:E1', 'ESTADÍSTICAS DE RETENCIÓN EN LA FUENTE', title_format)
        
        row = 3
        process_sheet.merge_range(f'A{row}:E{row}', 'Estadísticas por Proyección', section_format)
        row += 1
        
        for col, header in enumerate(['Tipo', 'Cantidad', 'Promedio Base', 'Promedio Retención', 'Total Retención']):
            process_sheet.write(row, col, header, header_format)
        row += 1
        
        proyectados = self.filtered(lambda r: r.es_proyectado)
        no_proyectados = self.filtered(lambda r: not r.es_proyectado)
        
        if proyectados:
            process_sheet.write(row, 0, 'Proyectados', cell_format)
            process_sheet.write(row, 1, len(proyectados), number_format)
            process_sheet.write(row, 2, sum(r.base_gravable for r in proyectados) / len(proyectados), money_format)
            process_sheet.write(row, 3, sum(r.retencion_aplicada for r in proyectados) / len(proyectados), money_format)
            process_sheet.write(row, 4, sum(r.retencion_aplicada for r in proyectados), money_format)
            row += 1
        
        if no_proyectados:
            process_sheet.write(row, 0, 'No Proyectados', cell_format)
            process_sheet.write(row, 1, len(no_proyectados), number_format)
            process_sheet.write(row, 2, sum(r.base_gravable for r in no_proyectados) / len(no_proyectados), money_format)
            process_sheet.write(row, 3, sum(r.retencion_aplicada for r in no_proyectados) / len(no_proyectados), money_format)
            process_sheet.write(row, 4, sum(r.retencion_aplicada for r in no_proyectados), money_format)
            row += 1
        
        process_sheet.write(row, 0, 'Total', subheader_format)
        process_sheet.write(row, 1, len(self), number_format)
        process_sheet.write(row, 2, sum(r.base_gravable for r in self) / len(self), money_format)
        process_sheet.write(row, 3, sum(r.retencion_aplicada for r in self) / len(self), money_format)
        process_sheet.write(row, 4, sum(r.retencion_aplicada for r in self), money_format)
        row += 2
        
        row += 1
        process_sheet.merge_range(f'A{row}:E{row}', 'Estadísticas por Quincena', section_format)
        row += 1
        
        for col, header in enumerate(['Tipo', 'Cantidad', 'Promedio Base', 'Promedio Retención', 'Total Retención']):
            process_sheet.write(row, col, header, header_format)
        row += 1
        
        for quincena, nombre in [('1', 'Primera Quincena'), ('2', 'Segunda Quincena'), ('0', 'Mensual')]:
            records = self.filtered(lambda r: r.quincena == quincena)
            if records:
                process_sheet.write(row, 0, nombre, cell_format)
                process_sheet.write(row, 1, len(records), number_format)
                process_sheet.write(row, 2, sum(r.base_gravable for r in records) / len(records), money_format)
                process_sheet.write(row, 3, sum(r.retencion_aplicada for r in records) / len(records), money_format)
                process_sheet.write(row, 4, sum(r.retencion_aplicada for r in records), money_format)
                row += 1
        
        row += 2
        process_sheet.merge_range(f'A{row}:E{row}', 'Estadísticas por Mes', section_format)
        row += 1
        
        for col, header in enumerate(['Mes', 'Cantidad', 'Base Promedio', 'Retención Promedio', 'Total Retención']):
            process_sheet.write(row, col, header, header_format)
        row += 1
        
        month_groups = {}
        for record in self:
            month_key = (record.year, record.month)
            if month_key not in month_groups:
                month_groups[month_key] = []
            month_groups[month_key].append(record)
        
        for month_key, records in sorted(month_groups.items()):
            year, month = month_key
            month_name = f"{self._get_month_name(month)} {year}"
            
            process_sheet.write(row, 0, month_name, cell_format)
            process_sheet.write(row, 1, len(records), number_format)
            process_sheet.write(row, 2, sum(r.base_gravable for r in records) / len(records), money_format)
            process_sheet.write(row, 3, sum(r.retencion_aplicada for r in records) / len(records), money_format)
            process_sheet.write(row, 4, sum(r.retencion_aplicada for r in records), money_format)
            row += 1
        
        # Cerrar el libro
        workbook.close()
        
        # Guardar archivo
        xlsx_data = output.getvalue()
        filename = f"Retenciones_Completo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        
        # Guardar el primer registro para descargar
        self[0].write({
            'excel_file': base64.b64encode(xlsx_data),
            'excel_filename': filename
        })
        
        # Devolver acción para descargar
        return {
            'type': 'ir.actions.act_url',
            'url': f"web/content/?model={self._name}&id={self[0].id}&field=excel_file&download=true&filename={filename}",
            'target': 'self',
        }
    
    def action_export_by_employee(self):
        """Exporta registros seleccionados agrupados por empleado"""
        if not self:
            raise models.UserError('No hay registros seleccionados para exportar.')
            
        # Preparar archivo Excel
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        
        # Estilos (mismos que en la función anterior)
        title_format = workbook.add_format({
            'bold': True, 'font_size': 14, 'align': 'center', 
            'valign': 'vcenter', 'bg_color': '#1E6C93', 'font_color': 'white'
        })
        header_format = workbook.add_format({
            'bold': True, 'font_size': 11, 'align': 'center', 
            'valign': 'vcenter', 'bg_color': '#D9EDF7', 'border': 1
        })
        subheader_format = workbook.add_format({
            'bold': True, 'font_size': 10, 'align': 'left', 
            'valign': 'vcenter', 'bg_color': '#F5F5F5', 'border': 1
        })
        cell_format = workbook.add_format({
            'font_size': 10, 'align': 'left', 'border': 1
        })
        number_format = workbook.add_format({
            'font_size': 10, 'align': 'right', 'border': 1,
            'num_format': '#,##0.00'
        })
        money_format = workbook.add_format({
            'font_size': 10, 'align': 'right', 'border': 1,
            'num_format': '$#,##0.00'
        })
        percent_format = workbook.add_format({
            'font_size': 10, 'align': 'right', 'border': 1,
            'num_format': '0.00%'
        })
        total_format = workbook.add_format({
            'bold': True, 'font_size': 11, 'align': 'right', 'border': 1,
            'num_format': '$#,##0.00', 'bg_color': '#F5F5F5'
        })
        company_format = workbook.add_format({
            'bold': True, 'font_size': 12, 'align': 'left',
            'valign': 'vcenter'
        })
        date_format = workbook.add_format({
            'font_size': 10, 'align': 'center', 'border': 1,
            'num_format': 'dd/mm/yyyy'
        })
        employee_format = workbook.add_format({
            'bold': True, 'font_size': 12, 'align': 'left',
            'valign': 'vcenter', 'bg_color': '#E6F3F8'
        })
        info_format = workbook.add_format({
            'font_size': 10, 'align': 'left', 'bg_color': '#FCF8E3',
            'border': 1, 'text_wrap': True
        })
        note_title_format = workbook.add_format({
            'bold': True, 'font_size': 11, 'align': 'left',
            'bg_color': '#FCF8E3', 'border': 1
        })
        note_text_format = workbook.add_format({
            'font_size': 10, 'align': 'left', 'border': 1,
            'text_wrap': True
        })
        section_format = workbook.add_format({
            'bold': True, 'font_size': 12, 'align': 'left', 
            'valign': 'vcenter', 'bg_color': '#E6F3F8', 'border': 1
        })
        
        company_data = self._get_company_data()
        
        worksheet = workbook.add_worksheet('Por Empleado')
        
        worksheet.set_column('A:A', 30)
        worksheet.set_column('B:Z', 15)
        
        worksheet.merge_range('A1:P1', company_data['name'], company_format)
        worksheet.merge_range('A2:P2', f"NIT: {company_data['vat']}", cell_format)
        worksheet.merge_range('A3:P3', f"Teléfono: {company_data['phone']} - Email: {company_data['email']}", cell_format)
        worksheet.merge_range('A4:P4', f"Dirección: {company_data['street']}, {company_data['city']}, {company_data['country']}", cell_format)
        
        current_date = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        worksheet.merge_range('A6:P6', 'REPORTE DE RETENCIÓN EN LA FUENTE POR EMPLEADO', title_format)
        worksheet.merge_range('A7:P7', f"Fecha generación: {current_date}", cell_format)
        worksheet.merge_range('A8:P8', f"Total registros: {len(self)}", cell_format)
        worksheet.merge_range('A9:P9', f"Total empleados: {len(self.mapped('employee_id'))}", cell_format)
        
        employee_groups = {}
        for record in self:
            if record.employee_id not in employee_groups:
                employee_groups[record.employee_id] = []
            employee_groups[record.employee_id].append(record)
        
        headers = [
            'Periodo', 'UVT', 'Salario', 'Total Ing.', 'Total Aportes', 
            'Total Ded.', 'AVP/AFC', 'Renta Ex. 25%', 'Beneficios Lim.', 
            'Base Grav.', 'Base UVTs', 'Tasa %', 'Retención'
        ]
        
        row = 11
        grand_total_retention = 0
        
        for employee, records in sorted(employee_groups.items(), key=lambda x: x[0].name):
            worksheet.merge_range(f'A{row}:P{row}', f"Empleado: {employee.name} - Documento: {employee.identification_id}", employee_format)
            row += 1
            
            worksheet.merge_range(f'A{row}:P{row}', f"Se encontraron {len(records)} registros de retención en la fuente.", info_format)
            row += 1
            
            row += 1
            for col, header in enumerate(headers):
                worksheet.write(row, col, header, header_format)
            row += 1
            
            employee_total_salary = 0
            employee_total_income = 0
            employee_total_contrib = 0
            employee_total_deductions = 0
            employee_total_avp_afc = 0
            employee_total_exenta_25 = 0
            employee_total_benefits = 0
            employee_total_base = 0
            employee_total_retention = 0
            
            for record in sorted(records, key=lambda r: (r.year, r.month, r.quincena)):
                periodo = self._format_period(record.year, record.month, record.quincena)
                
                col = 0
                worksheet.write(row, col, periodo, cell_format); col += 1
                worksheet.write(row, col, record.uvt_valor, number_format); col += 1
                worksheet.write(row, col, record.salario_basico, money_format); col += 1
                worksheet.write(row, col, record.total_ingresos, money_format); col += 1
                worksheet.write(row, col, record.total_aportes, money_format); col += 1
                worksheet.write(row, col, record.total_deducciones, money_format); col += 1
                worksheet.write(row, col, record.valor_avp_afc, money_format); col += 1
                worksheet.write(row, col, record.renta_exenta_25, money_format); col += 1
                worksheet.write(row, col, record.beneficios_limitados, money_format); col += 1
                worksheet.write(row, col, record.base_gravable, money_format); col += 1
                worksheet.write(row, col, record.ibr_uvts, number_format); col += 1
                worksheet.write(row, col, record.tasa_aplicada / 100, percent_format); col += 1
                worksheet.write(row, col, record.retencion_aplicada, money_format); col += 1
                
                employee_total_salary += record.salario_basico
                employee_total_income += record.total_ingresos
                employee_total_contrib += record.total_aportes
                employee_total_deductions += record.total_deducciones
                employee_total_avp_afc += record.valor_avp_afc
                employee_total_exenta_25 += record.renta_exenta_25
                employee_total_benefits += record.beneficios_limitados
                employee_total_base += record.base_gravable
                employee_total_retention += record.retencion_aplicada
                
                row += 1
            
            col = 0
            worksheet.write(row, col, 'SUBTOTAL', subheader_format); col += 1
            worksheet.write(row, col, '', subheader_format); col += 1
            worksheet.write(row, col, employee_total_salary, total_format); col += 1
            worksheet.write(row, col, employee_total_income, total_format); col += 1
            worksheet.write(row, col, employee_total_contrib, total_format); col += 1
            worksheet.write(row, col, employee_total_deductions, total_format); col += 1
            worksheet.write(row, col, employee_total_avp_afc, total_format); col += 1
            worksheet.write(row, col, employee_total_exenta_25, total_format); col += 1
            worksheet.write(row, col, employee_total_benefits, total_format); col += 1
            worksheet.write(row, col, employee_total_base, total_format); col += 1
            worksheet.write(row, col, '', subheader_format); col += 1
            worksheet.write(row, col, '', subheader_format); col += 1
            worksheet.write(row, col, employee_total_retention, total_format); col += 1
            
            grand_total_retention += employee_total_retention
            
            row += 2
            worksheet.merge_range(f'A{row}:P{row}', 'Distribución de retenciones por periodo:', section_format)
            row += 1
            
            periodos = {}
            for record in records:
                periodo = self._format_period(record.year, record.month, record.quincena)
                if periodo not in periodos:
                    periodos[periodo] = 0
                periodos[periodo] += record.retencion_aplicada
            
            worksheet.write(row, 0, 'Periodo', header_format)
            worksheet.write(row, 1, 'Retención', header_format)
            worksheet.write(row, 2, 'Porcentaje', header_format)
            row += 1
            
            for periodo, valor in sorted(periodos.items()):
                worksheet.write(row, 0, periodo, cell_format)
                worksheet.write(row, 1, valor, money_format)
                worksheet.write(row, 2, valor / employee_total_retention if employee_total_retention else 0, percent_format)
                row += 1
            
            row += 3
        
        # Gran total
        worksheet.merge_range(f'A{row}:L{row}', 'GRAN TOTAL RETENCIÓN', subheader_format)
        worksheet.write(row, 12, grand_total_retention, total_format)
        
        row += 2
        final_row = self._add_explanatory_notes(worksheet, row, note_title_format, note_text_format, 'P')
        
        summary_sheet = workbook.add_worksheet('Resumen Consolidado')
        summary_sheet.set_column('A:A', 30)
        summary_sheet.set_column('B:Z', 15)
        
        summary_sheet.merge_range('A1:K1', company_data['name'], company_format)
        summary_sheet.merge_range('A2:K2', 'RESUMEN CONSOLIDADO DE RETENCIÓN EN LA FUENTE', title_format)
        summary_sheet.merge_range('A3:K3', f"Fecha generación: {current_date}", cell_format)
        
        # Sección de análisis
        summary_row = 5
        summary_sheet.merge_range(f'A{summary_row}:K{summary_row}', 'ANÁLISIS CONSOLIDADO POR EMPLEADO', section_format)
        summary_row += 1
        
        # Encabezados consolidados
        summary_headers = [
            'Empleado', 'Documento', 'Total Registros', 'Salario', 'Ingresos', 
            'Deducciones', 'Rentas Exentas', 'Base Gravable', 'Retención', '% del Total'
        ]
        
        for col, header in enumerate(summary_headers):
            summary_sheet.write(summary_row, col, header, header_format)
        summary_row += 1
        
        # Datos consolidados
        grand_totals = {
            'registros': 0,
            'salario': 0,
            'ingresos': 0,
            'deducciones': 0,
            'rentas_exentas': 0,
            'base': 0,
            'retencion': 0
        }
        
        for employee, records in sorted(employee_groups.items(), key=lambda x: x[0].name):
            # Calcular totales por empleado
            total_registros = len(records)
            total_salario = sum(r.salario_basico for r in records)
            total_ingresos = sum(r.total_ingresos for r in records)
            total_deducciones = sum(r.total_deducciones for r in records)
            total_rentas = sum(r.total_rentas_exentas for r in records)
            total_base = sum(r.base_gravable for r in records)
            total_retencion = sum(r.retencion_aplicada for r in records)
            
            # Actualizar totales generales
            grand_totals['registros'] += total_registros
            grand_totals['salario'] += total_salario
            grand_totals['ingresos'] += total_ingresos
            grand_totals['deducciones'] += total_deducciones
            grand_totals['rentas_exentas'] += total_rentas
            grand_totals['base'] += total_base
            grand_totals['retencion'] += total_retencion
            
            # Escribir datos
            col = 0
            summary_sheet.write(summary_row, col, employee.name, cell_format); col += 1
            summary_sheet.write(summary_row, col, employee.identification_id, cell_format); col += 1
            summary_sheet.write(summary_row, col, total_registros, number_format); col += 1
            summary_sheet.write(summary_row, col, total_salario, money_format); col += 1
            summary_sheet.write(summary_row, col, total_ingresos, money_format); col += 1
            summary_sheet.write(summary_row, col, total_deducciones, money_format); col += 1
            summary_sheet.write(summary_row, col, total_rentas, money_format); col += 1
            summary_sheet.write(summary_row, col, total_base, money_format); col += 1
            summary_sheet.write(summary_row, col, total_retencion, money_format); col += 1
            summary_sheet.write(summary_row, col, total_retencion / grand_totals['retencion'] if grand_totals['retencion'] else 0, percent_format); col += 1
            
            summary_row += 1
        
        # Totales generales
        col = 0
        summary_sheet.write(summary_row, col, 'TOTAL GENERAL', subheader_format); col += 1
        summary_sheet.write(summary_row, col, '', subheader_format); col += 1
        summary_sheet.write(summary_row, col, grand_totals['registros'], number_format); col += 1
        summary_sheet.write(summary_row, col, grand_totals['salario'], total_format); col += 1
        summary_sheet.write(summary_row, col, grand_totals['ingresos'], total_format); col += 1
        summary_sheet.write(summary_row, col, grand_totals['deducciones'], total_format); col += 1
        summary_sheet.write(summary_row, col, grand_totals['rentas_exentas'], total_format); col += 1
        summary_sheet.write(summary_row, col, grand_totals['base'], total_format); col += 1
        summary_sheet.write(summary_row, col, grand_totals['retencion'], total_format); col += 1
        summary_sheet.write(summary_row, col, 1.0, percent_format); col += 1
        
        # Sección de análisis por año/mes
        summary_row += 3
        summary_sheet.merge_range(f'A{summary_row}:K{summary_row}', 'ANÁLISIS POR AÑO Y MES', section_format)
        summary_row += 1
        
        # Encabezados por año/mes
        year_month_headers = [
            'Año', 'Mes', 'Total Registros', 'Salario', 'Ingresos', 
            'Deducciones', 'Rentas Exentas', 'Base Gravable', 'Retención', 'Tasa Efectiva'
        ]
        
        for col, header in enumerate(year_month_headers):
            summary_sheet.write(summary_row, col, header, header_format)
        summary_row += 1
        
        # Agrupar por año/mes
        year_month_groups = {}
        for record in self:
            key = (record.year, record.month)
            if key not in year_month_groups:
                year_month_groups[key] = []
            year_month_groups[key].append(record)
        
        # Datos por año/mes
        for key, records in sorted(year_month_groups.items()):
            year, month = key
            month_name = self._get_month_name(month)
            
            # Calcular totales
            total_registros = len(records)
            total_salario = sum(r.salario_basico for r in records)
            total_ingresos = sum(r.total_ingresos for r in records)
            total_deducciones = sum(r.total_deducciones for r in records)
            total_rentas = sum(r.total_rentas_exentas for r in records)
            total_base = sum(r.base_gravable for r in records)
            total_retencion = sum(r.retencion_aplicada for r in records)
            tasa_efectiva = total_retencion / total_base if total_base else 0
            
            # Escribir datos
            col = 0
            summary_sheet.write(summary_row, col, year, cell_format); col += 1
            summary_sheet.write(summary_row, col, month_name, cell_format); col += 1
            summary_sheet.write(summary_row, col, total_registros, number_format); col += 1
            summary_sheet.write(summary_row, col, total_salario, money_format); col += 1
            summary_sheet.write(summary_row, col, total_ingresos, money_format); col += 1
            summary_sheet.write(summary_row, col, total_deducciones, money_format); col += 1
            summary_sheet.write(summary_row, col, total_rentas, money_format); col += 1
            summary_sheet.write(summary_row, col, total_base, money_format); col += 1
            summary_sheet.write(summary_row, col, total_retencion, money_format); col += 1
            summary_sheet.write(summary_row, col, tasa_efectiva, percent_format); col += 1
            
            summary_row += 1
        
        # Cerrar el libro
        workbook.close()
        
        # Guardar archivo
        xlsx_data = output.getvalue()
        filename = f"Retenciones_por_Empleado_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        
        # Guardar el primer registro para descargar
        self[0].write({
            'excel_file': base64.b64encode(xlsx_data),
            'excel_filename': filename
        })
        
        # Devolver acción para descargar
        return {
            'type': 'ir.actions.act_url',
            'url': f"web/content/?model={self._name}&id={self[0].id}&field=excel_file&download=true&filename={filename}",
            'target': 'self',
        }
    
    def action_export_detailed(self):
        """Exporta registros seleccionados con detalles en múltiples hojas"""
        if not self:
            raise models.UserError('No hay registros seleccionados para exportar.')
            
        # Preparar archivo Excel
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        
        # Estilos (mismos que en funciones anteriores)
        title_format = workbook.add_format({
            'bold': True, 'font_size': 14, 'align': 'center', 
            'valign': 'vcenter', 'bg_color': '#1E6C93', 'font_color': 'white'
        })
        header_format = workbook.add_format({
            'bold': True, 'font_size': 11, 'align': 'center', 
            'valign': 'vcenter', 'bg_color': '#D9EDF7', 'border': 1
        })
        subheader_format = workbook.add_format({
            'bold': True, 'font_size': 10, 'align': 'left', 
            'valign': 'vcenter', 'bg_color': '#F5F5F5', 'border': 1
        })
        cell_format = workbook.add_format({
            'font_size': 10, 'align': 'left', 'border': 1
        })
        number_format = workbook.add_format({
            'font_size': 10, 'align': 'right', 'border': 1,
            'num_format': '#,##0.00'
        })
        money_format = workbook.add_format({
            'font_size': 10, 'align': 'right', 'border': 1,
            'num_format': '$#,##0.00'
        })
        percent_format = workbook.add_format({
            'font_size': 10, 'align': 'right', 'border': 1,
            'num_format': '0.00%'
        })
        total_format = workbook.add_format({
            'bold': True, 'font_size': 11, 'align': 'right', 'border': 1,
            'num_format': '$#,##0.00', 'bg_color': '#F5F5F5'
        })
        company_format = workbook.add_format({
            'bold': True, 'font_size': 12, 'align': 'left',
            'valign': 'vcenter'
        })
        date_format = workbook.add_format({
            'font_size': 10, 'align': 'center', 'border': 1,
            'num_format': 'dd/mm/yyyy'
        })
        section_format = workbook.add_format({
            'bold': True, 'font_size': 12, 'align': 'left', 
            'valign': 'vcenter', 'bg_color': '#E6F3F8', 'border': 1
        })
        note_title_format = workbook.add_format({
            'bold': True, 'font_size': 11, 'align': 'left',
            'bg_color': '#FCF8E3', 'border': 1
        })
        note_text_format = workbook.add_format({
            'font_size': 10, 'align': 'left', 'border': 1,
            'text_wrap': True
        })
        calculation_format = workbook.add_format({
            'font_size': 10, 'align': 'left', 'bg_color': '#F0F0F0',
            'border': 1, 'text_wrap': True
        })
        
        # Obtener datos de la empresa
        company_data = self._get_company_data()
        
        #----------------------------------------------------------------------------------
        # HOJA 1: RESUMEN GENERAL
        #----------------------------------------------------------------------------------
        worksheet = workbook.add_worksheet('Resumen General')
        worksheet.set_column('A:A', 30)
        worksheet.set_column('B:Z', 15)
        
        # Encabezado
        worksheet.merge_range('A1:I1', company_data['name'], company_format)
        worksheet.merge_range('A2:I2', f"NIT: {company_data['vat']}", cell_format)
        worksheet.merge_range('A3:I3', f"Teléfono: {company_data['phone']} - Email: {company_data['email']}", cell_format)
        worksheet.merge_range('A4:I4', f"Dirección: {company_data['street']}, {company_data['city']}, {company_data['country']}", cell_format)
        
        # Información del reporte
        current_date = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        worksheet.merge_range('A6:I6', 'REPORTE DETALLADO DE RETENCIÓN EN LA FUENTE', title_format)
        worksheet.merge_range('A7:I7', f"Fecha generación: {current_date}", cell_format)
        worksheet.merge_range('A8:I8', f"Total registros: {len(self)}", cell_format)
        worksheet.merge_range('A9:I9', f"Total empleados: {len(self.mapped('employee_id'))}", cell_format)
        
        # Resumen de causas de retención (explicar el proceso)
        row = 11
        worksheet.merge_range(f'A{row}:I{row}', 'PROCESO DE CÁLCULO DE RETENCIÓN EN LA FUENTE', section_format)
        row += 1
        
        calculation_steps = [
            ("1. Ingresos Laborales", "Se suman todos los ingresos laborales del empleado: salario básico, comisiones, devengos salariales y no salariales."),
            ("2. Ingresos No Constitutivos", "Se restan los aportes obligatorios a pensión y salud, que no constituyen renta."),
            ("3. Ingreso Neto", "Se obtiene el ingreso neto: Total Ingresos - Ingresos No Constitutivos."),
            ("4. Deducciones", "Se aplican deducciones por vivienda, dependientes y salud prepagada, con sus respectivos límites."),
            ("5. Rentas Exentas", "Se aplican los aportes a AVP/AFC y la renta exenta del 25% sobre el resto de ingresos."),
            ("6. Límite Global 40%", "Se verifica que la suma de deducciones y rentas exentas no supere el 40% del ingreso neto ni 1.340 UVT anuales."),
            ("7. Base Gravable", "Se calcula la base gravable: Ingreso Neto - Beneficios Limitados."),
            ("8. Aplicación de Tarifa", "Se convierte la base a UVTs y se aplica la tarifa del Art. 383 ET."),
            ("9. Retención Final", "En caso de proyección (primera quincena), se aplica solo el 50% de la retención calculada.")
        ]
        
        for step, explanation in calculation_steps:
            worksheet.write(row, 0, step, subheader_format)
            worksheet.merge_range(f'B{row}:I{row}', explanation, calculation_format)
            row += 1
        
        # Tabla de resumen general
        row += 2
        worksheet.merge_range(f'A{row}:I{row}', 'RESUMEN GENERAL POR PERIODO', section_format)
        row += 1
        
        # Encabezados
        headers = [
            'Periodo', 'Cant. Registros', 'Total Ingresos', 'Aportes', 'Deducciones', 
            'Rentas Exentas', 'Base Gravable', 'Retención', 'Tasa Efectiva'
        ]
        
        for col, header in enumerate(headers):
            worksheet.write(row, col, header, header_format)
        row += 1
        
        # Agrupar por periodo (año, mes, quincena)
        period_groups = {}
        for record in self:
            period_key = (record.year, record.month, record.quincena)
            if period_key not in period_groups:
                period_groups[period_key] = []
            period_groups[period_key].append(record)
        
        # Datos por periodo
        grand_totals = {
            'records': 0,
            'income': 0, 
            'contrib': 0,
            'deductions': 0, 
            'exempt': 0,
            'base': 0, 
            'retention': 0
        }
        
        for period_key, records in sorted(period_groups.items()):
            year, month, quincena = period_key
            
            # Formatear periodo
            periodo = self._format_period(year, month, quincena)
            
            # Calcular totales para este periodo
            total_income = sum(r.total_ingresos for r in records)
            total_contrib = sum(r.total_aportes for r in records)
            total_deductions = sum(r.total_deducciones for r in records)
            total_exempt = sum(r.total_rentas_exentas for r in records)
            total_base = sum(r.base_gravable for r in records)
            total_retention = sum(r.retencion_aplicada for r in records)
            tasa_efectiva = total_retention / total_base if total_base else 0
            
            # Escribir datos
            worksheet.write(row, 0, periodo, cell_format)
            worksheet.write(row, 1, len(records), number_format)
            worksheet.write(row, 2, total_income, money_format)
            worksheet.write(row, 3, total_contrib, money_format)
            worksheet.write(row, 4, total_deductions, money_format)
            worksheet.write(row, 5, total_exempt, money_format)
            worksheet.write(row, 6, total_base, money_format)
            worksheet.write(row, 7, total_retention, money_format)
            worksheet.write(row, 8, tasa_efectiva, percent_format)
            
            # Actualizar totales generales
            grand_totals['records'] += len(records)
            grand_totals['income'] += total_income
            grand_totals['contrib'] += total_contrib
            grand_totals['deductions'] += total_deductions
            grand_totals['exempt'] += total_exempt
            grand_totals['base'] += total_base
            grand_totals['retention'] += total_retention
            
            row += 1
        
        # Totales generales
        worksheet.write(row, 0, 'TOTAL GENERAL', subheader_format)
        worksheet.write(row, 1, grand_totals['records'], number_format)
        worksheet.write(row, 2, grand_totals['income'], total_format)
        worksheet.write(row, 3, grand_totals['contrib'], total_format)
        worksheet.write(row, 4, grand_totals['deductions'], total_format)
        worksheet.write(row, 5, grand_totals['exempt'], total_format)
        worksheet.write(row, 6, grand_totals['base'], total_format)
        worksheet.write(row, 7, grand_totals['retention'], total_format)
        worksheet.write(row, 8, grand_totals['retention'] / grand_totals['base'] if grand_totals['base'] else 0, percent_format)
        
        # Agregar notas explicativas
        row += 2
        final_row = self._add_explanatory_notes(worksheet, row, note_title_format, note_text_format, 'I')
        
        #----------------------------------------------------------------------------------
        # HOJA 2: DETALLE POR EMPLEADO
        #----------------------------------------------------------------------------------
        details_sheet = workbook.add_worksheet('Detalle por Empleado')
        details_sheet.set_column('A:A', 30)
        details_sheet.set_column('B:Z', 15)
        
        # Encabezado
        details_sheet.merge_range('A1:M1', 'DETALLE POR EMPLEADO', title_format)
        details_sheet.merge_range('A2:M2', 'Listado completo de todos los registros ordenados por empleado', subheader_format)
        
        # Encabezados
        detail_row = 4
        detail_headers = [
            'Empleado', 'Documento', 'Periodo', 'Salario', 'Comisiones', 'Otros Ingresos',
            'Aportes', 'Deducciones', 'AVP/AFC', 'Renta Ex. 25%', 'Base', 'Retención', 'Tasa'
        ]
        
        for col, header in enumerate(detail_headers):
            details_sheet.write(detail_row, col, header, header_format)
        detail_row += 1
        
        # Datos detallados por empleado
        for record in sorted(self, key=lambda r: (r.employee_id.name, r.year, r.month, r.quincena)):
            # Formatear periodo
            periodo = self._format_period(record.year, record.month, record.quincena)
            otros_ingresos = record.dev_salarial + record.dev_no_salarial
            tasa_aplicada = record.tasa_aplicada / 100 if record.tasa_aplicada else 0
            
            col = 0
            details_sheet.write(detail_row, col, record.employee_id.name, cell_format); col += 1
            details_sheet.write(detail_row, col, record.employee_id.identification_id, cell_format); col += 1
            details_sheet.write(detail_row, col, periodo, cell_format); col += 1
            details_sheet.write(detail_row, col, record.salario_basico, money_format); col += 1
            details_sheet.write(detail_row, col, record.comisiones, money_format); col += 1
            details_sheet.write(detail_row, col, otros_ingresos, money_format); col += 1
            details_sheet.write(detail_row, col, record.total_aportes, money_format); col += 1
            details_sheet.write(detail_row, col, record.total_deducciones, money_format); col += 1
            details_sheet.write(detail_row, col, record.valor_avp_afc, money_format); col += 1
            details_sheet.write(detail_row, col, record.renta_exenta_25, money_format); col += 1
            details_sheet.write(detail_row, col, record.base_gravable, money_format); col += 1
            details_sheet.write(detail_row, col, record.retencion_aplicada, money_format); col += 1
            details_sheet.write(detail_row, col, tasa_aplicada, percent_format); col += 1
            
            detail_row += 1
        
        #----------------------------------------------------------------------------------
        # HOJA 3: CONSOLIDADO ANUAL POR EMPLEADO
        #----------------------------------------------------------------------------------
        annual_sheet = workbook.add_worksheet('Consolidado Anual')
        annual_sheet.set_column('A:A', 30)
        annual_sheet.set_column('B:Z', 15)
        
        # Encabezado
        annual_sheet.merge_range('A1:K1', 'CONSOLIDADO ANUAL POR EMPLEADO', title_format)
        annual_sheet.merge_range('A2:K2', 'Totales anuales por cada empleado', subheader_format)
        
        # Explicación para certificados de retención
        annual_row = 4
        annual_sheet.merge_range(f'A{annual_row}:K{annual_row}', 'NOTA: Esta información puede ser útil para la emisión de certificados de retención en la fuente.', note_title_format)
        annual_row += 2
        
        # Encabezados
        annual_headers = [
            'Empleado', 'Documento', 'Año', 'Total Registros', 'Total Ingresos', 
            'Aportes', 'Deducciones', 'Rentas Exentas', 'Base Gravable', 'Retención', 'Tasa Efectiva'
        ]
        
        for col, header in enumerate(annual_headers):
            annual_sheet.write(annual_row, col, header, header_format)
        annual_row += 1
        
        # Agrupar por empleado y año
        employee_year_groups = {}
        for record in self:
            key = (record.employee_id, record.year)
            if key not in employee_year_groups:
                employee_year_groups[key] = []
            employee_year_groups[key].append(record)
        
        # Datos consolidados por empleado y año
        for key, records in sorted(employee_year_groups.items(), key=lambda x: (x[0].name, x[1])):
            employee, year = key
            
            # Calcular totales anuales
            annual_income = sum(r.total_ingresos for r in records)
            annual_contrib = sum(r.total_aportes for r in records)
            annual_deductions = sum(r.total_deducciones for r in records)
            annual_exempt = sum(r.total_rentas_exentas for r in records)
            annual_base = sum(r.base_gravable for r in records)
            annual_retention = sum(r.retencion_aplicada for r in records)
            tasa_efectiva = annual_retention / annual_base if annual_base else 0
            
            # Escribir datos
            col = 0
            annual_sheet.write(annual_row, col, employee.name, cell_format); col += 1
            annual_sheet.write(annual_row, col, employee.identification_id, cell_format); col += 1
            annual_sheet.write(annual_row, col, year, cell_format); col += 1
            annual_sheet.write(annual_row, col, len(records), number_format); col += 1
            annual_sheet.write(annual_row, col, annual_income, money_format); col += 1
            annual_sheet.write(annual_row, col, annual_contrib, money_format); col += 1
            annual_sheet.write(annual_row, col, annual_deductions, money_format); col += 1
            annual_sheet.write(annual_row, col, annual_exempt, money_format); col += 1
            annual_sheet.write(annual_row, col, annual_base, money_format); col += 1
            annual_sheet.write(annual_row, col, annual_retention, money_format); col += 1
            annual_sheet.write(annual_row, col, tasa_efectiva, percent_format); col += 1
            
            annual_row += 1
        
        #----------------------------------------------------------------------------------
        # HOJA 4: ANÁLISIS DE BENEFICIOS TRIBUTARIOS
        #----------------------------------------------------------------------------------
        benefits_sheet = workbook.add_worksheet('Beneficios Tributarios')
        benefits_sheet.set_column('A:A', 30)
        benefits_sheet.set_column('B:Z', 15)
        
        # Encabezado
        benefits_sheet.merge_range('A1:I1', 'ANÁLISIS DE BENEFICIOS TRIBUTARIOS', title_format)
        benefits_sheet.merge_range('A2:I2', 'Detalle de deducciones y rentas exentas por empleado y año', subheader_format)
        
        # Encabezados
        benefits_row = 4
        benefits_headers = [
            'Empleado', 'Año', 'Vivienda', 'Dependientes', 'Salud Prepagada', 
            'AVP/AFC', 'Renta Exenta 25%', 'Total Beneficios', 'Beneficios Aplicados'
        ]
        
        for col, header in enumerate(benefits_headers):
            benefits_sheet.write(benefits_row, col, header, header_format)
        benefits_row += 1
        
        # Agrupar por empleado y año para beneficios
        for key, records in sorted(employee_year_groups.items(), key=lambda x: (x[0].name, x[1])):
            employee, year = key
            
            # Calcular totales de beneficios
            total_vivienda = sum(r.ded_vivienda for r in records)
            total_dependientes = sum(r.ded_dependientes for r in records)
            total_salud = sum(r.ded_salud for r in records)
            total_avp_afc = sum(r.valor_avp_afc for r in records)
            total_renta_25 = sum(r.renta_exenta_25 for r in records)
            total_beneficios = total_vivienda + total_dependientes + total_salud + total_avp_afc + total_renta_25
            total_beneficios_aplicados = sum(r.beneficios_limitados for r in records)
            
            # Escribir datos
            col = 0
            benefits_sheet.write(benefits_row, col, employee.name, cell_format); col += 1
            benefits_sheet.write(benefits_row, col, year, cell_format); col += 1
            benefits_sheet.write(benefits_row, col, total_vivienda, money_format); col += 1
            benefits_sheet.write(benefits_row, col, total_dependientes, money_format); col += 1
            benefits_sheet.write(benefits_row, col, total_salud, money_format); col += 1
            benefits_sheet.write(benefits_row, col, total_avp_afc, money_format); col += 1
            benefits_sheet.write(benefits_row, col, total_renta_25, money_format); col += 1
            benefits_sheet.write(benefits_row, col, total_beneficios, money_format); col += 1
            benefits_sheet.write(benefits_row, col, total_beneficios_aplicados, money_format); col += 1
            
            benefits_row += 1
        
        # Explicación del límite global
        benefits_row += 2
        benefits_sheet.merge_range(f'A{benefits_row}:I{benefits_row}', 'EXPLICACIÓN DEL LÍMITE GLOBAL 40%', note_title_format)
        benefits_row += 1
        
        limite_explanation = (
            "El límite global establece que la suma de deducciones y rentas exentas no puede exceder el 40% del ingreso neto "
            "con un tope máximo de 1.340 UVT anuales (Art. 387 ET y Ley 2277 de 2022). "
            "Si el total de beneficios supera este límite, se aplica una proporción para ajustarlos."
        )
        
        benefits_sheet.merge_range(f'A{benefits_row}:I{benefits_row}', limite_explanation, note_text_format)
        
        # Cerrar el libro
        workbook.close()
        
        # Guardar archivo
        xlsx_data = output.getvalue()
        filename = f"Reporte_Detallado_Retenciones_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        
        # Guardar el primer registro para descargar
        self[0].write({
            'excel_file': base64.b64encode(xlsx_data),
            'excel_filename': filename
        })
        
        # Devolver acción para descargar
        return {
            'type': 'ir.actions.act_url',
            'url': f"web/content/?model={self._name}&id={self[0].id}&field=excel_file&download=true&filename={filename}",
            'target': 'self',
        }
    @api.depends('employee_id', 'year', 'month', 'quincena')
    def _compute_name(self):
        """Calcula automáticamente un nombre de referencia para el reporte"""
        meses = {
            1: 'Enero', 2: 'Febrero', 3: 'Marzo', 4: 'Abril',
            5: 'Mayo', 6: 'Junio', 7: 'Julio', 8: 'Agosto',
            9: 'Septiembre', 10: 'Octubre', 11: 'Noviembre', 12: 'Diciembre'
        }
        
        for record in self:
            if not record.employee_id or not record.year or not record.month:
                record.name = "Reporte sin datos"
                continue
                
            mes = meses.get(record.month, f"Mes {record.month}")
            
            if record.quincena == '0':
                periodo = f"{mes} {record.year}"
            else:
                quincena = 'Q1' if record.quincena == '1' else 'Q2'
                periodo = f"{mes} {quincena} {record.year}"
                
            record.name = f"{record.employee_id.name} - {periodo}"
# -*- coding: utf-8 -*-
"""
PayrollTools – Servicio completo de nómina 🇨🇴

Módulo que proporciona un servicio completo para cálculos de nómina en Colombia.
Se organiza en dos clases principales:

1. PayrollToolsService (Base)
   - Métodos auxiliares para cálculos básicos
   - Consultas flexibles de reglas y categorías
   - Totalización de conceptos
   - Proyecciones y promedios

2. PayrollToolsExtended (Extensión)
   - Cálculos de beneficios sociales (prima, cesantías)
   - Gestión de vacaciones
   - Base de seguridad social (IBC)
   - Validaciones y resúmenes

Características principales:
- Trabaja con diccionario local (localdict) in-memory
- Soporta múltiples períodos (actual, anterior, prima, cesantías)
- Maneja reglas con campos booleanos
- Incluye lógica de vacaciones anual
- Proporciona métodos mock de SQL para payslips antiguos
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP, getcontext
from operator import itemgetter
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

from odoo import api, models
from dateutil.relativedelta import relativedelta

# Configuración global
getcontext().prec = 12
DEC_0 = Decimal("0")
DAYS_YEAR = 360
DAYS_30 = 30
STATIC_PERIODS: Tuple[str, ...] = ("current", "current_month", "before_month", "prima", "cesantias")

# Categorías de conceptos
CATEGORIES_EARNINGS = ("DEV_SALARIAL", "DEV_NO_SALARIAL", "COMISIONES", "HEYREC", "VACACIONES")
CATEGORIES_VARIABLE = ("DEV_SALARIAL", "COMISIONES", "HEYREC")
CATEGORIES_SOCIAL_SECURITY = ("IBC_ACTUAL", "IBC_R", "basic", "Parafiscales")
CATEGORIES_DEDUCTIONS = ("DEDUCCIONES", "SSOCIAL", "EM", "DESCUENTO_AFC")
CATEGORIES_LEAVES = ("LICENCIA_REMUNERADA", "LICENCIA_MATERNIDAD", "ACCIDENTE_TRABAJO")
CATEGORIES_NO_PAY = ("LICENCIA_NO_REMUNERADA", "AUS", "SANCIONES")


class PayrollToolsService(models.AbstractModel):
    """
    Servicio base para cálculos de nómina.
    
    Esta clase proporciona métodos utilitarios para trabajar con estructuras de datos
    de nómina en memoria. Los métodos se organizan en cuatro categorías principales:
    
    1. Métodos auxiliares: Funciones de apoyo internas
    2. Métodos de consulta: Búsqueda y filtrado de datos
    3. Métodos de totalización: Cálculos de totales y agregados
    4. Métodos de uso directo: Funciones simplificadas para cálculos comunes
    
    El servicio trabaja principalmente con un diccionario local (localdict) que contiene:
    - payslip_lines: Líneas de nómina por período
    - rules_multi: Reglas con múltiples aplicaciones
    - vacaciones_dict: Datos de vacaciones anuales
    - worked_days: Días trabajados
    - annual_parameters: Parámetros anuales (SMMLV, etc.)
    """

    _name = "payroll.tools.service"
    _description = "Servicio utilitario de nómina – cálculos in‑memory"

    # ========================================================================
    # MÉTODOS AUXILIARES
    # ========================================================================
    
    _rd = staticmethod(lambda v, n=2: v.quantize(Decimal("1").scaleb(-n), ROUND_HALF_UP))
    
    @staticmethod
    def dias_360(fi: date, ff: date) -> int:
        """
        Calcula días comerciales usando método 30E/360.
        
        Parameters
        ----------
        fi : date
            Fecha inicial
        ff : date
            Fecha final
            
        Returns
        -------
        int
            Días comerciales calculados
            
        Notes
        -----
        - Febrero siempre se considera de 30 días
        - Días 31 se ajustan a 30
        - Incluye ambas fechas (fi y ff)
        """
        def adj(d):
            if d.month == 2 and d.day >= 28:
                return 30
            return 30 if d.day == 31 else d.day
        return (ff.year - fi.year) * 360 + (ff.month - fi.month) * 30 + adj(ff) - adj(fi) + 1
    
    def _dias_nat(self, fi: date, ff: date) -> int:
        """
        Calcula días naturales entre fechas.
        
        Parameters
        ----------
        fi : date
            Fecha inicial
        ff : date
            Fecha final
            
        Returns
        -------
        int
            Días naturales (incluye ambas fechas)
        """
        return (ff - fi).days + 1
    
    def _iter(self, ld: Dict[str, Any], per: Iterable[str], fecha_filtro: Optional[Dict[str, date]] = None):
        """
        Iterador principal para recorrer reglas con filtro de fechas opcional.
        
        Parameters
        ----------
        ld : Dict[str, Any]
            Diccionario local con datos de nómina
        per : Iterable[str]
            Períodos a incluir
        fecha_filtro : Dict[str, date], optional
            Dict con 'start' y 'end' para filtrar por fechas
            
        Yields
        ------
        Tuple[str, str, Dict, Any]
            (código, período, entrada, regla)
            
        Notes
        -----
        - Itera sobre payslip_lines, rules_multi y vacaciones_dict
        - Aplica filtro de fechas si se especifica
        - Soporta múltiples períodos simultáneamente
        """
        # Iterar sobre payslip_lines
        for code, pd in ld.get("payslip_lines", {}).items():
            for p, bucket in pd.items():
                if p not in per: 
                    continue
                for e in bucket.get("entries", []):
                    if fecha_filtro and not (fecha_filtro["start"] <= e.get("date", date.today()) <= fecha_filtro["end"]):
                        continue
                    yield code, p, e, bucket.get("rule")
        
        # Iterar sobre rules_multi
        if "multi" in per and "rules_multi" in ld:
            for code, rm in ld["rules_multi"].items():
                entry = {
                    "total": rm["total"],
                    "quantity": rm["quantity"],
                    "amount": rm["amount"],
                    "date": ld.get("date_to"),
                    "payslip_id": None
                }
                if fecha_filtro and not (fecha_filtro["start"] <= entry.get("date", date.today()) <= fecha_filtro["end"]):
                    continue
                yield code, "multi", entry, rm.get("object")
        
        # Iterar sobre vacaciones
        if "vacaciones" in per and "vacaciones_dict" in ld:
            for code, entries in ld["vacaciones_dict"].items():
                for e in entries:
                    if fecha_filtro and not (fecha_filtro["start"] <= e.get("date", date.today()) <= fecha_filtro["end"]):
                        continue
                    yield code, "vacaciones", e, None
    
    def _sel_per(self, *, periodos=None, incluir_multi=False, incluir_vacaciones=False, **flags):
        """
        Selecciona períodos basado en flags.
        
        Parameters
        ----------
        periodos : List[str], optional
            Lista de períodos predefinidos
        incluir_multi : bool, default=False
            Si se incluye período 'multi'
        incluir_vacaciones : bool, default=False
            Si se incluye período 'vacaciones'
        **flags : bool
            Flags de período (current=True, before_month=True, etc.)
            
        Returns
        -------
        List[str]
            Lista de períodos seleccionados
        """
        chosen = [k for k, v in flags.items() if v and k in STATIC_PERIODS]
        if not chosen:
            chosen = list(periodos or STATIC_PERIODS)
        if incluir_multi:
            chosen.append("multi")
        if incluir_vacaciones:
            chosen.append("vacaciones")
        return chosen
    
    def _evaluar_regla_bool(self, rule, campo: str, default: bool = False) -> bool:
        """
        Evalúa campo booleano de una regla.
        
        Parameters
        ----------
        rule : Any
            Objeto de regla
        campo : str
            Nombre del campo booleano
        default : bool, default=False
            Valor por defecto si no existe el campo
            
        Returns
        -------
        bool
            Valor del campo o default
        """
        if not rule:
            return default
        return getattr(rule, campo, default) if hasattr(rule, campo) else default
    
    # ========================================================================
    # MÉTODOS DE CONSULTA
    # ========================================================================
    
    @api.model
    def consultar_reglas(self, ld: Dict[str, Any], *, salida="lista", incluir=None, excluir=None, 
                        incluir_dias=False, incluir_ids=False, incluir_multi=False, 
                        incluir_vacaciones=False, fecha_desde=None, fecha_hasta=None, 
                        evaluar_bool=None, **flags):
        """
        Consulta reglas con múltiples opciones de filtrado y formato de salida.
        
        Parameters
        ----------
        ld : Dict[str, Any]
            Diccionario local con datos de nómina
        salida : str, default="lista"
            Formato de salida: "lista", "dict", "float", "ids", "ambos"
        incluir : List[str], optional
            Códigos de reglas a incluir
        excluir : List[str], optional
            Códigos de reglas a excluir
        incluir_dias : bool, default=False
            Si se incluyen días y montos en la respuesta
        incluir_ids : bool, default=False
            Si se incluyen IDs de payslips
        incluir_multi : bool, default=False
            Si se incluyen rules_multi
        incluir_vacaciones : bool, default=False
            Si se incluyen datos de vacaciones
        fecha_desde : date, optional
            Fecha inicial para filtrar
        fecha_hasta : date, optional
            Fecha final para filtrar
        evaluar_bool : Dict[str, bool], optional
            Campos bool de reglas a evaluar: {"calculate_overtime": True}
        **flags : bool
            Flags de período: current=True, before_month=True, etc.
            
        Returns
        -------
        Union[List[Dict], Dict[str, List[Dict]], Decimal, Set[int], Tuple]
            - "lista": List[Dict] con entradas de reglas
            - "dict": Dict[str, List[Dict]] agrupado por código
            - "float": Decimal con suma total
            - "ids": Set[int] con IDs de payslips
            - "ambos": Tuple[List[Dict], Dict[str, List[Dict]]]
            
        Notes
        -----
        - Puede filtrar por período, fechas, códigos
        - Soporta evaluación de campos booleanos en reglas
        - Incluye datos de múltiples orígenes (payslip_lines, rules_multi, vacaciones)
        """
        per = self._sel_per(incluir_multi=incluir_multi, incluir_vacaciones=incluir_vacaciones, **flags)
        inc, exc = set(incluir or []), set(excluir or [])
        fecha_filtro = {"start": fecha_desde, "end": fecha_hasta} if fecha_desde and fecha_hasta else None
        
        lst, grp, ids, total = [], defaultdict(list), set(), DEC_0
        
        for code, p, e, rule in self._iter(ld, per, fecha_filtro):
            if (inc and code not in inc) or code in exc:
                continue
            
            # Evaluar campos booleanos si se especificaron
            if evaluar_bool and rule:
                skip = False
                for campo, valor_esperado in evaluar_bool.items():
                    if not self._evaluar_regla_bool(rule, campo, False) == valor_esperado:
                        skip = True
                        break
                if skip:
                    continue
            
            ent = {
                "codigo": code,
                "periodo": p,
                "total": self._rd(Decimal(str(e.get("total", 0)))),
                "date": e.get("date", date.today())
            }
            
            if incluir_dias:
                ent.update({
                    "dias": self._rd(Decimal(str(e.get("quantity", 0)))),
                    "monto": self._rd(Decimal(str(e.get("amount", 0))))
                })
            
            if incluir_ids and e.get("payslip_id"):
                pid = getattr(e["payslip_id"], "id", e["payslip_id"])
                ent["payslip_id"] = pid
                ids.add(pid)
            
            lst.append(ent)
            grp[code].append(ent)
            total += Decimal(str(e.get("total", 0)))
        
        if salida == "float": return self._rd(total)
        if salida == "dict":  return dict(grp)
        if salida == "ids":   return sorted(ids)
        if salida == "ambos": return lst, dict(grp)
        return lst
    
    @api.model
    def consultar_categorias(self, ld: Dict[str, Any], *, salida="dict", categorias=None,
                           incluir_multi=False, incluir_vacaciones=False, 
                           fecha_desde=None, fecha_hasta=None, **flags):
        """
        Consulta totales por categorías de reglas.
        
        Parameters
        ----------
        ld : Dict[str, Any]
            Diccionario local con datos de nómina
        salida : str, default="dict"
            Formato de salida: "dict", "float", "lista", "ambos"
        categorias : List[str], optional
            Lista de categorías a incluir (filtro)
        incluir_multi : bool, default=False
            Si se incluyen rules_multi
        incluir_vacaciones : bool, default=False
            Si se incluyen datos de vacaciones
        fecha_desde : date, optional
            Fecha inicial para filtrar
        fecha_hasta : date, optional
            Fecha final para filtrar
        **flags : bool
            Flags de período: current=True, before_month=True, etc.
            
        Returns
        -------
        Union[Dict[str, Decimal], Decimal, List[Tuple[str, Decimal]], Tuple]
            - "dict": Dict[str, Decimal] con totales por categoría
            - "float": Decimal con suma total de todas las categorías
            - "lista": List[Tuple[str, Decimal]] ordenada por monto descendente
            - "ambos": Tuple[Dict[str, Decimal], List[Tuple[str, Decimal]]]
            
        Notes
        -----
        - Agrupa por código de categoría
        - Ordena resultados de mayor a menor cuando salida="lista"
        - Soporta filtrado por fechas
        """
        per = self._sel_per(incluir_multi=incluir_multi, incluir_vacaciones=incluir_vacaciones, **flags)
        fecha_filtro = {"start": fecha_desde, "end": fecha_hasta} if fecha_desde and fecha_hasta else None
        inc = set(categorias or [])
        tot = defaultdict(Decimal)
        
        for _, p, e, rule in self._iter(ld, per, fecha_filtro):
            if rule and hasattr(rule, 'category_id') and rule.category_id:
                cat_code = rule.category_id.code
                if inc and cat_code not in inc:
                    continue
                tot[cat_code] += Decimal(str(e.get("total", 0)))
        
        if salida == "float": 
            return self._rd(sum(tot.values()))
        
        lista = sorted(((c, self._rd(v)) for c, v in tot.items()), key=itemgetter(1), reverse=True)
        
        if salida == "lista": 
            return lista
        if salida == "ambos": 
            return {c: self._rd(v) for c, v in tot.items()}, lista
        
        return {c: self._rd(v) for c, v in tot.items()}
    
    @api.model
    def consultar_dias(self, ld: Dict[str, Any], *, salida="dict", incluir_multi=False,
                      incluir_vacaciones=False, fecha_desde=None, fecha_hasta=None, **flags):
        """
        Consulta días (quantity) por período.
        
        Parameters
        ----------
        ld : Dict[str, Any]
            Diccionario local con datos de nómina
        salida : str, default="dict"
            Formato de salida: "dict", "float", "lista"
        incluir_multi : bool, default=False
            Si se incluyen rules_multi
        incluir_vacaciones : bool, default=False
            Si se incluyen datos de vacaciones
        fecha_desde : date, optional
            Fecha inicial para filtrar
        fecha_hasta : date, optional
            Fecha final para filtrar
        **flags : bool
            Flags de período: current=True, before_month=True, etc.
            
        Returns
        -------
        Union[Dict[str, Decimal], Decimal, List[Tuple[str, Decimal]]]
            - "dict": Dict[str, Decimal] con días por período
            - "float": Decimal con suma total de días
            - "lista": List[Tuple[str, Decimal]] con días por período
            
        Notes
        -----
        - Suma el campo 'quantity' de las entradas
        - Útil para calcular días trabajados, ausencias, etc.
        """
        per = self._sel_per(incluir_multi=incluir_multi, incluir_vacaciones=incluir_vacaciones, **flags)
        fecha_filtro = {"start": fecha_desde, "end": fecha_hasta} if fecha_desde and fecha_hasta else None
        tot = defaultdict(Decimal)
        
        for _, p, e, _ in self._iter(ld, per, fecha_filtro):
            tot[p] += Decimal(str(e.get("quantity", 0)))
        
        if salida == "float": 
            return self._rd(sum(tot.values()))
        if salida == "lista": 
            return [(p, self._rd(v)) for p, v in tot.items()]
        
        return {p: self._rd(v) for p, v in tot.items()}
    
    # ========================================================================
    # MÉTODOS DE TOTALIZACIÓN
    # ========================================================================
    
    @api.model
    def totalizar_reglas(self, ld: Dict[str, Any], *, codigos=None, excluir=None, 
                        incluir_multi=False, incluir_vacaciones=False, 
                        fecha_desde=None, fecha_hasta=None, **flags):
        """
        Totaliza montos por código de regla.
        
        Parameters
        ----------
        ld : Dict[str, Any]
            Diccionario local con datos de nómina
        codigos : List[str], optional
            Códigos a incluir (filtro)
        excluir : List[str], optional
            Códigos a excluir
        incluir_multi : bool, default=False
            Si se incluyen rules_multi
        incluir_vacaciones : bool, default=False
            Si se incluyen datos de vacaciones
        fecha_desde : date, optional
            Fecha inicial para filtrar
        fecha_hasta : date, optional
            Fecha final para filtrar
        **flags : bool
            Flags de período: current=True, before_month=True, etc.
            
        Returns
        -------
        Dict[str, Decimal]
            Totales por código de regla
            
        Notes
        -----
        - Suma todos los valores 'total' para cada código
        - Permite filtrar por códigos específicos o excluir algunos
        - Soporta filtrado por fechas
        """
        per = self._sel_per(incluir_multi=incluir_multi, incluir_vacaciones=incluir_vacaciones, **flags)
        fecha_filtro = {"start": fecha_desde, "end": fecha_hasta} if fecha_desde and fecha_hasta else None
        inc, exc = set(codigos or []), set(excluir or [])
        tot = defaultdict(Decimal)
        
        for code, _, e, _ in self._iter(ld, per, fecha_filtro):
            if (inc and code not in inc) or code in exc:
                continue
            tot[code] += Decimal(str(e.get("total", 0)))
        
        return {c: self._rd(v) for c, v in tot.items()}
    
    @api.model
    def totalizar_categorias(self, ld: Dict[str, Any], *, categorias=None, 
                           incluir_multi=False, incluir_vacaciones=False,
                           fecha_desde=None, fecha_hasta=None, **flags):
        """
        Totaliza montos por categoría.
        
        Parameters
        ----------
        ld : Dict[str, Any]
            Diccionario local con datos de nómina
        categorias : List[str], optional
            Categorías a incluir (filtro)
        incluir_multi : bool, default=False
            Si se incluyen rules_multi
        incluir_vacaciones : bool, default=False
            Si se incluyen datos de vacaciones
        fecha_desde : date, optional
            Fecha inicial para filtrar
        fecha_hasta : date, optional
            Fecha final para filtrar
        **flags : bool
            Flags de período: current=True, before_month=True, etc.
            
        Returns
        -------
        Dict[str, Decimal]
            Totales por categoría
            
        Notes
        -----
        - Agrupa por código de categoría
        - Útil para obtener subtotales (devengos, deducciones, etc.)
        """
        per = self._sel_per(incluir_multi=incluir_multi, incluir_vacaciones=incluir_vacaciones, **flags)
        fecha_filtro = {"start": fecha_desde, "end": fecha_hasta} if fecha_desde and fecha_hasta else None
        inc = set(categorias or [])
        tot = defaultdict(Decimal)
        
        for _, _, e, rule in self._iter(ld, per, fecha_filtro):
            if not rule or not hasattr(rule, 'category_id') or not rule.category_id:
                continue
            cat = rule.category_id.code
            if inc and cat not in inc:
                continue
            tot[cat] += Decimal(str(e.get("total", 0)))
        
        return {c: self._rd(v) for c, v in tot.items()}
    
    @api.model
    def obtener_totales(self, ld: Dict[str, Any], *, incluir_multi=False, 
                       incluir_vacaciones=False, fecha_desde=None, fecha_hasta=None, **flags):
        """
        Obtiene totales generales: devengos, deducciones y neto.
        
        Parameters
        ----------
        ld : Dict[str, Any]
            Diccionario local con datos de nómina
        incluir_multi : bool, default=False
            Si se incluyen rules_multi
        incluir_vacaciones : bool, default=False
            Si se incluyen datos de vacaciones
        fecha_desde : date, optional
            Fecha inicial para filtrar
        fecha_hasta : date, optional
            Fecha final para filtrar
        **flags : bool
            Flags de período: current=True, before_month=True, etc.
            
        Returns
        -------
        Dict[str, Decimal]
            Dictionary con keys:
            - "devengos": Total de valores positivos
            - "deducciones": Total de valores negativos (en valor absoluto)
            - "neto": devengos - deducciones
            
        Notes
        -----
        - Devengos: suma de todos los valores positivos
        - Deducciones: suma de todos los valores negativos (se retornan en positivo)
        - Neto: devengos - deducciones
        """
        per = self._sel_per(incluir_multi=incluir_multi, incluir_vacaciones=incluir_vacaciones, **flags)
        fecha_filtro = {"start": fecha_desde, "end": fecha_hasta} if fecha_desde and fecha_hasta else None
        
        dev = ded = DEC_0
        
        for _, _, e, _ in self._iter(ld, per, fecha_filtro):
            v = Decimal(str(e.get("total", 0)))
            if v > 0:
                dev += v
            else:
                ded += abs(v)
        
        return {
            "devengos": self._rd(dev),
            "deducciones": self._rd(ded),
            "neto": self._rd(dev - ded)
        }
    
    # ========================================================================
    # MÉTODOS DE USO DIRECTO
    # ========================================================================
    
    @api.model
    def dias_entre_fechas(self, fi: date, ff: date, *, metodo="natural") -> int:
        """
        Calcula diferencia de días entre fechas.
        
        Parameters
        ----------
        fi : date
            Fecha inicial
        ff : date
            Fecha final
        metodo : str, default="natural"
            Método de cálculo: "natural" o "360"
            
        Returns
        -------
        int
            Cantidad de días
            
        Notes
        -----
        - "natural": días calendario reales
        - "360": días comerciales (30 días por mes)
        """
        if metodo == "360":
            return self.dias_360(fi, ff)
        return self._dias_nat(fi, ff)
    
    @api.model
    def contar_festivos_domingos(self, fi: date, ff: date, festivos: Iterable[date] = None):
        """
        Cuenta festivos y domingos en un rango.
        
        Parameters
        ----------
        fi : date
            Fecha inicial
        ff : date
            Fecha final
        festivos : Iterable[date], optional
            Lista de fechas festivas
            
        Returns
        -------
        Tuple[int, int]
            (cantidad_festivos, cantidad_domingos)
            
        Notes
        -----
        - Si un día es domingo y festivo, solo se cuenta como domingo
        - Los festivos deben proporcionarse como lista de fechas
        """
        fest = dom = 0
        fest_set = set(festivos or [])
        
        for n in range(self._dias_nat(fi, ff)):
            d = fi + timedelta(days=n)
            if d.weekday() == 6:  # domingo
                dom += 1
                fest_set.discard(d)  # quitar del set si también es festivo
            elif d in fest_set:
                fest += 1
        
        return fest, dom
    
    @api.model
    def calcular_dias(self, fi: date, ff: date, *, metodo="natural", 
                     ajustes=None, festivos_externos=None):
        """
        Calcula desglose completo de días.
        
        Parameters
        ----------
        fi : date
            Fecha inicial
        ff : date
            Fecha final
        metodo : str, default="natural"
            Método de cálculo: "natural" o "360"
        ajustes : Dict[str, int], optional
            Ajustes manuales: {"ausencias": 5}
        festivos_externos : List[date], optional
            Lista de fechas festivas
            
        Returns
        -------
        Dict[str, Decimal]
            Dictionary con keys:
            - "total": Total de días en el período
            - "festivos": Cantidad de festivos
            - "domingos": Cantidad de domingos
            - "ausencias": Días de ausencia (manual)
            - "trabajados": total - festivos - domingos - ausencias
            
        Notes
        -----
        - Proporciona un desglose completo de días
        - Útil para cálculos de nómina que requieren días netos trabajados
        """
        ajustes = ajustes or {}
        total = Decimal(self.dias_entre_fechas(fi, ff, metodo=metodo))
        fest, dom = self.contar_festivos_domingos(fi, ff, festivos_externos)
        aus = Decimal(str(ajustes.get("ausencias", 0)))
        trab = total - Decimal(fest + dom) - aus
        
        return {
            "total": total,
            "festivos": Decimal(fest),
            "domingos": Decimal(dom),
            "ausencias": aus,
            "trabajados": trab
        }
    
    @api.model
    def calcular_proyeccion(self, conceptos: Dict[str, Decimal], *, 
                          dias_trabajados: int, dias_proyectar: int = 30):
        """
        Proyecta conceptos a un período estándar.
        
        Parameters
        ----------
        conceptos : Dict[str, Decimal]
            Conceptos con sus valores actuales
        dias_trabajados : int
            Días trabajados en el período actual
        dias_proyectar : int, default=30
            Días a los que se proyecta
            
        Returns
        -------
        Dict[str, Decimal]
            Mismos conceptos proyectados al período objetivo
            
        Notes
        -----
        - Útil para calcular IBC cuando hay días faltantes
        - Formula: valor_proyectado = valor_actual * dias_proyectar / dias_trabajados
        """
        if dias_trabajados <= 0:
            dias_trabajados = 1  # evitar división por cero
        
        factor = Decimal(dias_proyectar) / Decimal(dias_trabajados)
        return {c: self._rd(v * factor) for c, v in conceptos.items()}
    
    @api.model
    def calcular_ibc_proyectado(self, ibc_completo: Decimal, *, 
                               dias_trabajados: int, dias_proyectar: int = 30):
        """
        Proyecta IBC a período estándar.
        
        Parameters
        ----------
        ibc_completo : Decimal
            IBC actual (puede ser parcial)
        dias_trabajados : int
            Días trabajados en el período actual
        dias_proyectar : int, default=30
            Días a los que se proyecta (típicamente 30)
            
        Returns
        -------
        Decimal
            IBC proyectado al período objetivo
            
        Notes
        -----
        - Caso especial de calcular_proyeccion para un solo valor
        - Común en cálculos de seguridad social
        """
        if dias_trabajados <= 0:
            dias_trabajados = 1
        
        factor = Decimal(dias_proyectar) / Decimal(dias_trabajados)
        return self._rd(ibc_completo * factor)
    
    @api.model
    def promedio_salarial(self, ld: Dict[str, Any], fecha_inicio: date, *, 
                         codigos_concepto=None, meses=3, metodo_dias="natural", 
                         incluir_multi=True):
        """
        Calcula promedio salarial histórico.
        
        Parameters
        ----------
        ld : Dict[str, Any]
            Diccionario local con datos de nómina
        fecha_inicio : date
            Fecha inicial del período de cálculo
        codigos_concepto : List[str], optional
            Códigos de conceptos a incluir (default: ["BASIC"])
        meses : int, default=3
            Cantidad de meses a promediar
        metodo_dias : str, default="natural"
            Método para calcular días base: "natural" o "360"
        incluir_multi : bool, default=True
            Si se incluyen rules_multi en el cálculo
            
        Returns
        -------
        Decimal
            Promedio salarial mensual
            
        Notes
        -----
        - Útil para cálculos de prestaciones sociales
        - Por defecto calcula sobre salario básico
        - Ajusta por días trabajados en cada mes
        """
        codigos_concepto = codigos_concepto or ["BASIC"]
        fecha_fin = fecha_inicio + relativedelta(months=meses, days=-1)
        
        total = dias = DEC_0
        per = list(STATIC_PERIODS) + (["multi"] if incluir_multi else [])
        
        for code, _, e, _ in self._iter(ld, per):
            if code in codigos_concepto and fecha_inicio <= e.get("date") <= fecha_fin:
                total += Decimal(str(e.get("total", 0)))
                dias += Decimal(str(e.get("quantity", 0)))
        
        if dias == 0:
            return DEC_0
        
        base = Decimal(30) if metodo_dias == "360" else dias
        return self._rd(total / dias * base)
    
    # ========================================================================
    # MÉTODOS SQL MOCK (para compatibilidad con código antiguo)
    # ========================================================================
    
    @api.model
    def sumar_monto_regla_sql(self, ld: Dict[str, Any], codigo: str, fi: date, ff: date, *, 
                             payslip_ids: Optional[List[int]] = None):
        """
        Mock de consulta SQL para sumar montos de una regla.
        
        Parameters
        ----------
        ld : Dict[str, Any]
            Diccionario local con datos de nómina
        codigo : str
            Código de la regla
        fi : date
            Fecha inicial
        ff : date
            Fecha final
        payslip_ids : List[int], optional
            IDs de nóminas a filtrar
            
        Returns
        -------
        Decimal
            Suma de montos para la regla
            
        Notes
        -----
        - Simula una consulta SQL usando datos en memoria
        - Útil para mantener compatibilidad con código antiguo
        """
        ids = set(payslip_ids or [])
        tot = DEC_0
        
        for c, _, e, _ in self._iter(ld, list(STATIC_PERIODS) + ["multi"]):
            if c == codigo and fi <= e.get("date") <= ff:
                if ids:
                    pid = getattr(e.get("payslip_id"), "id", e.get("payslip_id"))
                    if pid not in ids:
                        continue
                tot += Decimal(str(e.get("total", 0)))
        
        return self._rd(tot)
    
    @api.model
    def sumar_monto_categoria_sql(self, ld: Dict[str, Any], categoria: str, fi: date, ff: date, *, 
                                 payslip_ids: Optional[List[int]] = None):
        """
        Mock de consulta SQL para sumar montos de una categoría.
        
        Parameters
        ----------
        ld : Dict[str, Any]
            Diccionario local con datos de nómina
        categoria : str
            Código de la categoría
        fi : date
            Fecha inicial
        ff : date
            Fecha final
        payslip_ids : List[int], optional
            IDs de nóminas a filtrar
            
        Returns
        -------
        Decimal
            Suma de montos para la categoría
            
        Notes
        -----
        - Simula una consulta SQL usando datos en memoria
        - Filtra por código de categoría de la regla
        """
        ids = set(payslip_ids or [])
        tot = DEC_0
        
        for _, _, e, r in self._iter(ld, list(STATIC_PERIODS) + ["multi"]):
            if r and hasattr(r, 'category_id') and r.category_id.code == categoria:
                if fi <= e.get("date") <= ff:
                    if ids:
                        pid = getattr(e.get("payslip_id"), "id", e.get("payslip_id"))
                        if pid not in ids:
                            continue
                    tot += Decimal(str(e.get("total", 0)))
        
        return self._rd(tot)
    
    @api.model
    def sumar_dias_trabajados_sql(self, ld: Dict[str, Any], code_we: str, fi: date, ff: date):
        """
        Mock de consulta SQL para sumar días trabajados.
        
        Parameters
        ----------
        ld : Dict[str, Any]
            Diccionario local con datos de nómina
        code_we : str
            Código del tipo de día trabajado
        fi : date
            Fecha inicial
        ff : date
            Fecha final
            
        Returns
        -------
        Decimal
            Suma de días trabajados
            
        Notes
        -----
        - Busca en worked_days_lines
        - Útil para cálculos retroactivos
        """
        dias = DEC_0
        
        for wd in ld.get("worked_days_lines", []):
            if wd.get("code") == code_we and fi <= wd.get("date") <= ff:
                dias += Decimal(str(wd.get("number_of_days", 0)))
        
        return self._rd(dias)
    
    @api.model
    def obtener_cambios_salario(self, ld: Dict[str, Any], fi: date, ff: date):
        """
        Obtiene cambios de salario en un período.
        
        Parameters
        ----------
        ld : Dict[str, Any]
            Diccionario local con datos de nómina
        fi : date
            Fecha inicial
        ff : date
            Fecha final
            
        Returns
        -------
        List[Dict]
            Lista de cambios de salario
            
        Notes
        -----
        - Filtra contract_wage_changes por fechas
        - Útil para cálculos retroactivos y promedios
        """
        return [r for r in ld.get("contract_wage_changes", []) 
                if fi <= r["date_start"] <= ff]
    
    # ========================================================================
    # MÉTODOS DE UTILIDAD ADICIONALES
    # ========================================================================
    
    @api.model
    def mini_lista_reglas(self, ld: Dict[str, Any], *, n=5, incluir_multi=False, **flags):
        """
        Obtiene las N reglas con mayor monto.
        
        Parameters
        ----------
        ld : Dict[str, Any]
            Diccionario local con datos de nómina
        n : int, default=5
            Cantidad de reglas a retornar
        incluir_multi : bool, default=False
            Si se incluyen rules_multi
        **flags : bool
            Flags de período: current=True, etc.
            
        Returns
        -------
        List[Tuple[str, Decimal]]
            Lista de tuplas (código, monto) ordenada descendentemente
            
        Notes
        -----
        - Útil para resúmenes rápidos
        - Muestra los conceptos más significativos
        """
        tot = self.totalizar_reglas(ld, incluir_multi=incluir_multi, **flags)
        return sorted(tot.items(), key=itemgetter(1), reverse=True)[:n]
    
    # Aliases para compatibilidad con código antiguo
    sumar_monto_regla = totalizar_reglas
    sumar_monto_categoria = totalizar_categorias


class PayrollToolsExtended(PayrollToolsService):
    """
    Extensión de PayrollToolsService con funcionalidades avanzadas.
    
    Esta clase agrega métodos específicos para cálculos de:
    - Beneficios sociales (prima, cesantías)
    - Vacaciones y provisiones
    - Seguridad social y IBC
    - Validaciones y resúmenes
    
    Los métodos utilizan las funcionalidades base proporcionadas por
    PayrollToolsService y agregan lógica de negocio específica para
    nómina colombiana.
    """
    
    # ========================================================================
    # MÉTODOS DE BALANCE Y ACUMULADOS
    # ========================================================================
    
    @api.model
    def get_accumulated_balance(self, localdict: Dict[str, Any], from_date: date, 
                              to_date: date, rule_codes: List[str]) -> Dict[str, Decimal]:
        """
        Obtiene balance acumulado de reglas específicas.
        
        Parameters
        ----------
        localdict : Dict[str, Any]
            Diccionario local con datos de nómina
        from_date : date
            Fecha inicial
        to_date : date
            Fecha final
        rule_codes : List[str]
            Lista de códigos de reglas
            
        Returns
        -------
        Dict[str, Decimal]
            Balance por código de regla
            
        Notes
        -----
        - Útil para consultas de acumulados históricos
        - Considera todos los períodos disponibles
        """
        balances = {}
        
        # Consultar todas las líneas en el período
        rules_data = self.consultar_reglas(
            localdict,
            incluir=rule_codes,
            salida="dict",
            fecha_desde=from_date,
            fecha_hasta=to_date,
            current=True,
            current_month=True,
            before_month=True,
            prima=True,
            cesantias=True,
            incluir_vacaciones=True
        )
        
        # Calcular balance
        for code, entries in rules_data.items():
            total = DEC_0
            for entry in entries:
                total += entry.get('total', 0)
            balances[code] = self._rd(total)
        
        return balances
    
    @api.model
    def get_worked_days_by_type(self, localdict: Dict[str, Any], from_date: date, 
                              to_date: date) -> Dict[str, int]:
        """
        Obtiene días trabajados por tipo en un período.
        
        Parameters
        ----------
        localdict : Dict[str, Any]
            Diccionario local con datos de nómina
        from_date : date
            Fecha inicial
        to_date : date
            Fecha final
            
        Returns
        -------
        Dict[str, int]
            Días por tipo (trabajados, festivos, domingos, ausencias)
            
        Notes
        -----
        - Consolida información de diferentes fuentes
        - Considera worked_days.dict y campos directos
        """
        days_by_type = {
            'trabajados': 0,
            'festivos': 0,
            'domingos': 0,
            'ausencias': 0
        }
        
        # Obtener días de localdict
        for key in days_by_type:
            if key in localdict:
                days_by_type[key] = localdict.get(key, 0)
        
        # Verificar días adicionales en worked_days
        if 'worked_days' in localdict:
            for wd_code, wd_data in localdict['worked_days'].dict.items():
                if hasattr(wd_data, 'number_of_days'):
                    if wd_data.date_from >= from_date and wd_data.date_to <= to_date:
                        if wd_code == 'WORK100':
                            days_by_type['trabajados'] += wd_data.number_of_days
                        elif wd_code.startswith('AUS'):
                            days_by_type['ausencias'] += wd_data.number_of_days
        
        return days_by_type
    
    # ========================================================================
    # MÉTODOS DE VACACIONES
    # ========================================================================
    
    @api.model
    def get_vacation_provision(self, localdict: Dict[str, Any], date_from: date, 
                             date_to: date) -> Dict[str, Decimal]:
        """
        Calcula provisión de vacaciones.
        
        Parameters
        ----------
        localdict : Dict[str, Any]
            Diccionario local con datos de nómina
        date_from : date
            Fecha inicial
        date_to : date
            Fecha final
            
        Returns
        -------
        Dict[str, Decimal]
            Dictionary con keys:
            - "base": Base salarial para el cálculo
            - "provision": Monto de la provisión
            - "days": Días de vacaciones causados
            
        Notes
        -----
        - Usa fórmula: (días_trabajados * 15) / 360
        - Descuenta días no pagados
        """
        contract = localdict.get('contract')
        if not contract:
            return {'base': DEC_0, 'provision': DEC_0, 'days': 0}
        
        # Obtener base para vacaciones
        base_salary = self.get_sum_salary(localdict, {
            'start': date_from,
            'end': date_to,
            'contract': contract.id
        })
        
        # Calcular días de vacaciones causados
        worked_days = self.dias_360(date_from, date_to)
        days_no_pay = self.get_days_no_pay(localdict, {
            'start': date_from,
            'end': date_to
        })
        
        net_worked_days = worked_days - days_no_pay
        vacation_days = (net_worked_days * 15) / DAYS_YEAR
        
        # Calcular provisión
        daily_salary = base_salary / DAYS_30
        provision = vacation_days * daily_salary
        
        return {
            'base': self._rd(base_salary),
            'provision': self._rd(provision),
            'days': self._rd(vacation_days)
        }
    
    @api.model
    def get_accumulated_vacation_days(self, localdict: Dict[str, Any], 
                                    reference_date: Optional[date] = None) -> Dict[str, Decimal]:
        """
        Obtiene días de vacaciones acumulados.
        
        Parameters
        ----------
        localdict : Dict[str, Any]
            Diccionario local con datos de nómina
        reference_date : date, optional
            Fecha de referencia (default: date_to del localdict)
            
        Returns
        -------
        Dict[str, Decimal]
            Dictionary con keys:
            - "causados": Días causados totales
            - "disfrutados": Días disfrutados
            - "pagados": Días pagados en dinero
            - "pendientes": Días pendientes
            
        Notes
        -----
        - Considera el historial completo desde el inicio del contrato
        - Descuenta vacaciones interrumpidas
        """
        if not reference_date:
            reference_date = localdict.get('date_to', date.today())
        
        contract = localdict.get('contract')
        if not contract:
            return {'causados': DEC_0, 'disfrutados': DEC_0, 'pendientes': DEC_0, 'pagados': DEC_0}
        
        # Calcular días causados
        worked_days = self.dias_360(contract.date_start, reference_date)
        days_no_pay = self.get_leave_no_pay(localdict, contract.id, {
            'start': contract.date_start,
            'end': reference_date
        })
        
        net_worked_days = worked_days - days_no_pay
        vacation_caused = (net_worked_days * 15) / DAYS_YEAR
        
        # Obtener días disfrutados y pagados
        vacations = self.env['hr.vacation'].search([
            ('contract_id', '=', contract.id),
            ('departure_date', '<=', reference_date)
        ])
        
        days_enjoyed = sum(v.business_units for v in vacations if v.vacation_type == 'enjoy')
        days_paid = sum(v.units_of_money for v in vacations if v.vacation_type == 'money')
        
        # Considerar vacaciones interrumpidas
        for vacation in vacations.filtered(lambda v: v.is_interrupted):
            if vacation.days_returned:
                days_enjoyed -= vacation.days_returned
        
        total_used = days_enjoyed + days_paid
        remaining = vacation_caused - total_used
        
        return {
            'causados': self._rd(vacation_caused),
            'disfrutados': self._rd(days_enjoyed),
            'pagados': self._rd(days_paid),
            'pendientes': self._rd(remaining)
        }
    
    # ========================================================================
    # MÉTODOS DE SEGURIDAD SOCIAL
    # ========================================================================
    
    @api.model
    def get_social_security_base(self, localdict: Dict[str, Any], from_date: date, 
                               to_date: date) -> Dict[str, Decimal]:
        """
        Calcula la base para seguridad social (IBC).
        
        Parameters
        ----------
        localdict : Dict[str, Any]
            Diccionario local con datos de nómina
        from_date : date
            Fecha inicial
        to_date : date
            Fecha final
            
        Returns
        -------
        Dict[str, Decimal]
            Dictionary con keys:
            - "ibc_salud": Base para salud
            - "ibc_pension": Base para pensión
            - "ibc_riesgos": Base para ARL
            - "ibc_parafiscales": Base para parafiscales
            
        Notes
        -----
        - Ajusta por días trabajados si son menos de 30
        - Aplica topes mínimo (SMMLV) y máximo (25 SMMLV)
        - Considera categorías específicas de seguridad social
        """
        # Obtener conceptos que forman parte de la base
        base_concepts = self.totalizar_categorias(
            localdict,
            categorias=CATEGORIES_SOCIAL_SECURITY,
            fecha_desde=from_date,
            fecha_hasta=to_date,
            current=True,
            current_month=True
        )
        
        ibc_base = sum(base_concepts.values())
        
        days_worked = self.consultar_dias(
            localdict,
            fecha_desde=from_date,
            fecha_hasta=to_date,
            current=True,
            current_month=True,
            salida="float"
        )
        
        if days_worked < 30:
            ibc_base = (ibc_base / days_worked) * 30
        
        # Verificar mínimos y máximos
        annual_params = localdict.get('annual_parameters')
        if annual_params:
            min_ibc = annual_params.smmlv_monthly
            max_ibc = annual_params.smmlv_monthly * 25
            
            ibc_base = max(min_ibc, min(ibc_base, max_ibc))
        
        return {
            'ibc_salud': self._rd(ibc_base),
            'ibc_pension': self._rd(ibc_base),
            'ibc_riesgos': self._rd(ibc_base),
            'ibc_parafiscales': self._rd(ibc_base)
        }
    
    # ========================================================================
    # MÉTODOS DE BENEFICIOS SOCIALES
    # ========================================================================
    
    @api.model
    def get_social_benefits(self, localdict: Dict[str, Any], date_from: date, date_to: date, 
                           compute_with_average: bool = False) -> Tuple[Decimal, int, Decimal]:
        """
        Calcula beneficios sociales (cesantías o prima).
        
        Parameters
        ----------
        localdict : Dict[str, Any]
            Diccionario local con datos de nómina
        date_from : date
            Fecha inicial
        date_to : date
            Fecha final
        compute_with_average : bool, default=False
            Si debe calcular con promedio salarial
            
        Returns
        -------
        Tuple[Decimal, int, Decimal]
            (base_social_benefits, worked_days, social_benefits)
            
        Notes
        -----
        - Usa la fórmula: (base * días_trabajados) / 360
        - Incluye salario básico, variable y subsidio de transporte
        - Verifica si necesita calcular con promedio
        """
        worked_days = self.dias_360(date_from, date_to)
        period = {'start': date_from, 'end': date_to}
        
        days_no_pay = self.get_days_no_pay(localdict, period)
        worked_days -= days_no_pay
        days_rate = 1 if worked_days <= DAYS_30 else DAYS_30 / worked_days
        
        data_benefit = {}
        contract = localdict.get('contract')
        compute_average = compute_with_average or self.need_compute_salary_average(
            contract, date_from, date_to)
        
        if compute_average:
            data_benefit['salary'] = self.get_sum_salary(localdict, period)
        else:
            wage = Decimal(str(localdict.get('wage', 0)))
            data_benefit['salary'] = wage * worked_days / DAYS_30
        
        # Obtener salario variable
        variable_data = self.get_variable_salary(localdict, period)
        data_benefit['variable'] = sum(variable_data.values())
        
        # Calcular earnings
        total_earnings = variable_data.get('DEV_SALARIAL', DEC_0) + data_benefit['salary']
        month_earnings = total_earnings * days_rate
        
        # Obtener SMMLV y subsidio de transporte
        annual_params = localdict.get('annual_parameters')
        if annual_params:
            smmlv = annual_params.smmlv_monthly
            if month_earnings < 2 * smmlv:
                subsidy = annual_params.aux_transportation
                data_benefit['static'] = subsidy * worked_days / DAYS_30
        
        base_social_benefits = sum(data_benefit.values()) * days_rate
        social_benefits = base_social_benefits * worked_days / DAYS_YEAR
        
        return self._rd(base_social_benefits), worked_days, self._rd(social_benefits)
    
    @api.model
    def _compute_layoff(self, localdict: Dict[str, Any], date_from: date, 
                       date_to: date) -> Tuple[Decimal, int, Decimal]:
        """
        Calcula cesantías.
        
        Parameters
        ----------
        localdict : Dict[str, Any]
            Diccionario local con datos de nómina
        date_from : date
            Fecha inicial
        date_to : date
            Fecha final
            
        Returns
        -------
        Tuple[Decimal, int, Decimal]
            (base_layoff, worked_days, layoff)
            
        Notes
        -----
        - Wrapper de get_social_benefits para cesantías
        - No usa promedio salarial por defecto
        """
        return self.get_social_benefits(localdict, date_from, date_to, False)
    
    @api.model
    def _compute_prima(self, localdict: Dict[str, Any], date_from: date, 
                      date_to: date) -> Tuple[Decimal, int, Decimal]:
        """
        Calcula prima de servicios.
        
        Parameters
        ----------
        localdict : Dict[str, Any]
            Diccionario local con datos de nómina
        date_from : date
            Fecha inicial
        date_to : date
            Fecha final
            
        Returns
        -------
        Tuple[Decimal, int, Decimal]
            (base_prima, worked_days, prima)
            
        Notes
        -----
        - Wrapper de get_social_benefits para prima
        - Siempre usa promedio salarial
        """
        return self.get_social_benefits(localdict, date_from, date_to, True)
    
    # ========================================================================
    # MÉTODOS DE VALIDACIÓN Y RESÚMENES
    # ========================================================================
    
    @api.model
    def validate_payslip_data(self, localdict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Valida datos de nómina y devuelve advertencias.
        
        Parameters
        ----------
        localdict : Dict[str, Any]
            Diccionario local con datos de nómina
            
        Returns
        -------
        Dict[str, Any]
            Dictionary con keys:
            - "valid": bool indicando si es válido
            - "warnings": Lista de advertencias
            
        Notes
        -----
        - Verifica salario mínimo
        - Valida días trabajados
        - Chequea deducciones vs devengos
        - Verifica tipo de cotizante
        """
        warnings = []
        validations = {
            'valid': True,
            'warnings': warnings
        }
        
        # Validar salario mínimo
        annual_params = localdict.get('annual_parameters')
        if annual_params:
            wage = localdict.get('wage', 0)
            if wage < annual_params.smmlv_monthly:
                warnings.append('El salario está por debajo del mínimo legal')
        
        # Validar días trabajados
        total_days = self.consultar_dias(localdict, salida="float", current=True)
        if total_days > 30:
            warnings.append(f'Los días trabajados ({total_days}) exceden 30 días')
        
        # Validar deducciones vs devengos
        totals = self.obtener_totales(localdict, current=True)
        if totals['deducciones'] > totals['devengos']:
            warnings.append('Las deducciones superan los devengos')
            validations['valid'] = False
        
        # Validar tipo de cotizante
        employee = localdict.get('employee')
        if employee and not getattr(employee, 'tipo_coti_id', None):
            warnings.append('El empleado no tiene tipo de cotizante definido')
            validations['valid'] = False
        
        return validations
    
    @api.model
    def get_payslip_summary(self, localdict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Genera un resumen completo de la nómina.
        
        Parameters
        ----------
        localdict : Dict[str, Any]
            Diccionario local con datos de nómina
            
        Returns
        -------
        Dict[str, Any]
            Resumen completo con:
            - totals: Devengos, deducciones y neto
            - categories: Totales por categoría
            - days: Días trabajados por tipo
            - social_security: Bases de seguridad social
            - validations: Resultado de validaciones
            - contract: Información del contrato
            - employee: Información del empleado
            
        Notes
        -----
        - Proporciona una vista consolidada de toda la nómina
        - Útil para reportes y visualización
        """
        current_period = {
            'start': localdict.get('date_from', date.today()),
            'end': localdict.get('date_to', date.today())
        }
        
        return {
            'totals': self.obtener_totales(localdict, current=True),
            'categories': self.consultar_categorias(localdict, current=True, salida="dict"),
            'days': self.get_worked_days_by_type(localdict, current_period['start'], current_period['end']),
            'social_security': self.get_social_security_base(localdict, current_period['start'], current_period['end']),
            'validations': self.validate_payslip_data(localdict),
            'contract': {
                'wage': localdict.get('wage', 0),
                'type': getattr(localdict.get('contract', {}), 'contract_type_id', {}).name,
                'salary_modality': getattr(localdict.get('contract', {}), 'modality_salary', '')
            },
            'employee': {
                'name': getattr(localdict.get('employee', {}), 'name', ''),
                'identification': getattr(localdict.get('employee', {}), 'identification_id', ''),
                'tipo_cotizante': getattr(getattr(localdict.get('employee', {}), 'tipo_coti_id', {}), 'code', '')
            }
        }
    
    # ========================================================================
    # MÉTODOS AUXILIARES ADICIONALES
    # ========================================================================
    
    @api.model
    def get_variable_salary(self, localdict: Dict[str, Any], 
                           period: Dict[str, date]) -> Dict[str, Decimal]:
        """
        Obtiene el salario variable para un período.
        
        Parameters
        ----------
        localdict : Dict[str, Any]
            Diccionario local con datos de nómina
        period : Dict[str, date]
            Período con 'start' y 'end'
            
        Returns
        -------
        Dict[str, Decimal]
            Salario variable por categoría
            
        Notes
        -----
        - Excluye el salario básico
        - Incluye comisiones, horas extras y recargos
        """
        return self.totalizar_categorias(
            localdict,
            categorias=CATEGORIES_VARIABLE,
            fecha_desde=period['start'],
            fecha_hasta=period['end'],
            current=True,
            current_month=True,
            before_month=True
        )
    
    @api.model
    def get_sum_salary(self, localdict: Dict[str, Any], query: Dict[str, Any]) -> Decimal:
        """
        Obtiene la suma del salario total.
        
        Parameters
        ----------
        localdict : Dict[str, Any]
            Diccionario local con datos de nómina
        query : Dict[str, Any]
            Query con 'start' y 'end'
            
        Returns
        -------
        Decimal
            Suma total del salario
            
        Notes
        -----
        - Incluye salario básico
        - Incluye licencias remuneradas
        - Incluye salario en vacaciones
        """
        salary = DEC_0
        
        # Licencias de maternidad/paternidad
        licences_codes = ('LICENCIA_MATERNIDAD', 'LICENCIA_PATERNIDAD')
        licences_total = self.totalizar_reglas(
            localdict,
            codigos=licences_codes,
            fecha_desde=query['start'],
            fecha_hasta=query['end'],
            current=True,
            current_month=True,
            before_month=True
        )
        salary += sum(licences_total.values())
        
        # Salario en licencias
        salary_in_leave = self.get_salary_in_leave(localdict, query)
        salary += salary_in_leave
        
        # Salario básico
        basic_total = self.totalizar_reglas(
            localdict,
            codigos=('BASICO',),
            fecha_desde=query['start'],
            fecha_hasta=query['end'],
            current=True,
            current_month=True,
            before_month=True,
            prima=True,
            cesantias=True
        )
        salary += sum(basic_total.values())
        
        return self._rd(salary)
    
    @api.model
    def get_days_no_pay(self, localdict: Dict[str, Any], period: Dict[str, date]) -> int:
        """
        Obtiene los días no pagados.
        
        Parameters
        ----------
        localdict : Dict[str, Any]
            Diccionario local con datos de nómina
        period : Dict[str, date]
            Período con 'start' y 'end'
            
        Returns
        -------
        int
            Cantidad de días no pagados
            
        Notes
        -----
        - Wrapper para get_leave_no_pay
        - Mantiene compatibilidad con código existente
        """
        return self.get_leave_no_pay(localdict, localdict.get('contract', {}).id, period)
    
    @api.model
    def get_leave_no_pay(self, localdict: Dict[str, Any], contract_id: int, 
                        period: Dict[str, date]) -> int:
        """
        Calcula los días de licencia no remunerada en un período.
        
        Parameters
        ----------
        localdict : Dict[str, Any]
            Diccionario local con datos de nómina
        contract_id : int
            ID del contrato
        period : Dict[str, date]
            Período con 'start' y 'end'
            
        Returns
        -------
        int
            Cantidad de días de licencia no remunerada
            
        Notes
        -----
        - Busca códigos específicos de licencias no pagas
        - Incluye ausencias y sanciones
        """
        leave_codes = CATEGORIES_NO_PAY
        total_days = 0
        
        result = self.consultar_reglas(
            localdict,
            incluir=leave_codes,
            salida="lista",
            incluir_dias=True,
            fecha_desde=period['start'],
            fecha_hasta=period['end'],
            current=True,
            current_month=True,
            before_month=True,
            prima=True,
            cesantias=True
        )
        
        for entry in result:
            total_days += entry.get('dias', 0)
        
        return int(total_days)
    
    @api.model
    def get_salary_in_leave(self, localdict: Dict[str, Any], 
                           period: Dict[str, date]) -> Decimal:
        """
        Obtiene el salario durante licencias.
        
        Parameters
        ----------
        localdict : Dict[str, Any]
            Diccionario local con datos de nómina
        period : Dict[str, date]
            Período con 'start' y 'end'
            
        Returns
        -------
        Decimal
            Total de salario durante licencias
            
        Notes
        -----
        - Incluye incapacidades
        - Incluye vacaciones
        - Incluye licencias remuneradas
        """
        leave_types = ('INCAPACIDAD', 'INCAPACIDAD_EG', 'VACACIONES', 'LICENCIA_REMUNERADA')
        
        result = self.totalizar_reglas(
            localdict,
            codigos=leave_types,
            fecha_desde=period['start'],
            fecha_hasta=period['end'],
            current=True,
            current_month=True,
            before_month=True,
            prima=True,
            cesantias=True
        )
        
        return self._rd(sum(result.values()))
    
    @api.model
    def need_compute_salary_average(self, contract, date_from: date, date_to: date) -> bool:
        """
        Determina si se necesita calcular el promedio salarial.
        
        Parameters
        ----------
        contract : object
            Objeto de contrato
        date_from : date
            Fecha inicial
        date_to : date
            Fecha final
            
        Returns
        -------
        bool
            True si necesita calcular promedio
            
        Notes
        -----
        - Verifica cambios salariales en los últimos 3 meses
        - Usado para cálculos de prestaciones sociales
        """
        date_3_months_before = date_to - relativedelta(months=3)
        if date_from > date_3_months_before:
            date_3_months_before = date_from
        
        # Usar historial de salarios del contrato
        wages_in_period = contract.wage_history_ids.filtered(
            lambda x: date_3_months_before <= x.date <= date_to
        )
        return len(wages_in_period) >= 1
    
    @api.model
    def get_historical_wage(self, contract, date_reference: date) -> Decimal:
        """
        Obtiene el salario histórico para una fecha específica.
        
        Parameters
        ----------
        contract : object
            Objeto de contrato
        date_reference : date
            Fecha de referencia
            
        Returns
        -------
        Decimal
            Salario en la fecha
            
        Notes
        -----
        - Busca en el historial de salarios
        - Retorna el salario más cercano anterior a la fecha
        """
        if not contract.wage_history_ids:
            return Decimal(str(contract.wage))
        
        valid_wages = contract.wage_history_ids.filtered(
            lambda h: h.date <= date_reference
        )
        
        if not valid_wages:
            return Decimal(str(contract.wage))
        
        latest_wage = max(valid_wages, key=lambda h: h.date)
        return Decimal(str(latest_wage.wage))
    
    @api.model
    def no_apply_social_benefits(self, localdict: Dict[str, Any]) -> bool:
        """
        Verifica si no se aplican beneficios sociales.
        
        Parameters
        ----------
        localdict : Dict[str, Any]
            Diccionario local con datos de nómina
            
        Returns
        -------
        bool
            True si no se aplican beneficios sociales
            
        Notes
        -----
        - Verifica tipo de cotizante
        - Verifica modalidad de salario integral
        - Verifica subtipo de cotizante
        """
        employee = localdict.get('employee')
        contract = localdict.get('contract')
        
        if not employee or not contract:
            return False
        
        tipo_coti = employee.tipo_coti_id
        if tipo_coti and tipo_coti.code in ['12', '19']:
            return True
        
        if contract.modality_salary == 'integral':
            return True
        

        return False


"""
PayrollTools – Retención en la fuente completa 🇨🇴
================================================
Versión: 24‑abr‑2025 – *rtf_full_2025*

Coberturas
----------
* **Procedimiento 1** – salarios quincenales/mensuales (`_retencion_procedimiento1`).
* **Indemnizaciones** – art. 401‑3 E.T. (`_retencion_indemnizacion`).
* **Prima de servicios** – cálculo anualizado (`_retencion_prima`).
* **Extranjero no residente** – tarifa única 20 % (`_retencion_extranjero20`).

Highlights
~~~~~~~~~~
* Proyección quincenal diferenciada (básico ⇢ días trabajados, resto ⇢ días hábiles).
* Tabla art. 383 (UVT 2025) embebida + redondeo ley 1111/2006.
* Topes UVT: 40 % / 1 340 UVT, 100 UVT vivienda, 32 UVT dependientes, 16 UVT salud.
* Reporte **idéntico** al legacy (`dias`, `ingresos`, `aportes_obligatorios`, …)
  añadiendo bloque `graf` (labels/values) al final.

Todas las funciones llevan comentarios doctrinales *inline* para auditoría.
"""


getcontext().prec = 12  # Precisión adecuada para UVT y porcentajes

# ----------------------------------------------------------------------------
# Tabla art. 383 (UVT 2025) – (desde, hasta, tarifa %, resta_uvt, suma_uvt)
# ----------------------------------------------------------------------------
_TABLA_ART383: Sequence[Tuple[Decimal, Decimal | float, int, int, int]] = [
    (Decimal("0"),     Decimal("95"),    0,  0,   0),
    (Decimal("95"),    Decimal("150"),  19, 95,  0),
    (Decimal("150"),   Decimal("360"),  28, 150, 10),
    (Decimal("360"),   Decimal("640"),  33, 360, 69),
    (Decimal("640"),   Decimal("945"),  35, 640, 164),
    (Decimal("945"),   Decimal("2300"), 37, 945, 268),
    (Decimal("2300"),  float("inf"),    39, 2300, 770),
]

# ----------------------------------------------------------------------------
class PayrollRetentionMethods(models.AbstractModel):
    """Bitákora – Retención en la fuente: salarios, indemnización, prima."""

    _name = "payroll.retention.methods"
    _description = "Cálculo integral de retención en la fuente 🇨🇴"

    # --------------------------------------------------------------------
    # ↓ utilidades numéricas ------------------------------------------------
    _redondear = staticmethod(lambda valor, decimales=2: Decimal(valor).quantize(Decimal("1").scaleb(-decimales), ROUND_HALF_UP))

    @staticmethod
    def _format_money(valor: float) -> str:
        """Formatea valores monetarios para presentación"""
        return f"${valor:,.2f}"

    @staticmethod
    def _redondeo_legal(valor: Decimal) -> Decimal:
        """Art. 868: <10 000 → redondeo a 100; ≥10 000 → redondeo a 1 000."""
        if valor < 10000:
            return (valor / 100).to_integral_value(rounding=ROUND_HALF_UP) * 100
        return (valor / 1000).to_integral_value(rounding=ROUND_HALF_UP) * 1000

    def _aplicar_tabla_383(self, base_uvt: Decimal, valor_uvt: Decimal) -> Tuple[Decimal, int, int]:
        """Aplicar tabla art. 383 ET para cálculo de retención"""
        for desde, hasta, tarifa, resta, suma in _TABLA_ART383:
            if desde <= base_uvt < hasta:
                if tarifa == 0:
                    return Decimal(0), 0, 0
                valor_retencion_uvt = (base_uvt - Decimal(resta)) * Decimal(tarifa)/Decimal(100) + Decimal(suma)
                return self._redondear(valor_retencion_uvt * valor_uvt, 0), tarifa, resta
        return Decimal(0), 0, 0

    # --------------------------------------------------------------------
    # ↓ días trabajados / ausencias ---------------------------------------
    @staticmethod
    def _calcular_dias(payslip):
        """Calcula días trabajados, remunerados y no remunerados"""
        dias_trabajados = sum(linea.number_of_days for linea in payslip.worked_days_line_ids if linea.code == "WORK100")
        dias_remunerados = dias_no_remunerados = Decimal(0)
        for ausencia in payslip.leave_days_ids:
            if ausencia.leave_id.holiday_status_id.unpaid_absences:
                dias_no_remunerados += ausencia.days_payslip
            else:
                dias_remunerados += ausencia.days_payslip
        return Decimal(dias_trabajados), dias_remunerados, dias_no_remunerados

    # --------------------------------------------------------------------
    # ↓ deducciones UVT (vivienda, dependientes, salud) --------------------
    def _deduccion_vivienda(self, contrato, valor_uvt: Decimal):
        """Deducción intereses vivienda - art. 119 ET - tope 100 UVT"""
        valor_deduccion = contrato.ded_vivienda
        try:
            valor_desde_rtf = contrato.get_contract_deductions_rtf(contrato.id, "INTVIV").value_monthly
            if valor_desde_rtf:
                valor_deduccion = valor_desde_rtf
        except Exception:
            pass
        return min(Decimal(valor_deduccion), valor_uvt * 100)

    def _deduccion_dependientes(self, contrato, ingreso_base: Decimal, valor_uvt: Decimal):
        """Deducción dependientes - art. 387-1 ET - tope 10% ingresos o 32 UVT"""
        if contrato.ded_dependents:
            return min(ingreso_base * Decimal("0.10"), valor_uvt * 32)
        
        valor_deduccion = 0
        try:
            valor_deduccion = contrato.get_contract_deductions_rtf(contrato.id, "DEDDEP").value_monthly
        except Exception:
            pass
        return min(ingreso_base * Decimal("0.10"), valor_uvt * 32) if valor_deduccion else Decimal(0)

    def _deduccion_salud(self, contrato, valor_uvt: Decimal):
        """Deducción medicina prepagada - art. 387 ET - tope 16 UVT"""
        valor_deduccion = contrato.ded_salud_prep
        try:
            valor_desde_rtf = contrato.get_contract_deductions_rtf(contrato.id, "MEDPRE").value_monthly
            if valor_desde_rtf:
                valor_deduccion = valor_desde_rtf
        except Exception:
            pass
        return min(Decimal(valor_deduccion), valor_uvt * 16)

    # --------------------------------------------------------------------
    # ↓ Generación de logs HTML ------------------------------------------
    def _build_ssocial_html_log(
        self,
        periodo: str,
        aplicado: bool,
        descripcion: str,
        saldo_anterior: float = None,
        rango_log: List[Tuple[str, str]] = None,
        pasos: List[str] = None
    ) -> str:
        """
        Genera un log HTML para reglas de seguridad social usando clases CSS
        que son compatibles con el modo oscuro.
         
        Args:
            periodo: Periodo de la nómina (ej. "Primera Q1 04-23")
            aplicado: Indica si la regla se aplicó
            descripcion: Descripción de la operación o razón de no aplicación
            saldo_anterior: Saldo acumulado del periodo anterior
            rango_log: Lista de tuplas (etiqueta, estado) para rangos de cálculo
            pasos: Lista de pasos del cálculo realizados
                 
        Returns:
            Representación HTML del log
        """
        html = '<div class="simulation-container p-3 border rounded bg-light">'
         
        html += '<div class="d-flex justify-content-between align-items-center mb-3 pb-2 border-bottom">'
        html += f'<h5 class="mb-0 text-primary">{self.name}</h5>'
         
        badge_class = "badge bg-success" if aplicado else "badge bg-danger"
        badge_text = "Aplicado" if aplicado else "No Aplicado"
        html += f'<span class="{badge_class}">{badge_text}</span>'
        html += '</div>'
         
        html += f'<div class="mb-2"><strong>Periodo:</strong> {periodo.upper()}</div>'
         
        alert_class = "alert alert-success p-2" if aplicado else "alert alert-danger p-2"
        html += f'<div class="mb-3 {alert_class}">'
         
        if aplicado:
            html += f'<i class="fa fa-check-circle"></i> <strong>Operación realizada:</strong> {descripcion}'
        else:
            html += f'<i class="fa fa-times-circle"></i> <strong>No aplica:</strong> {descripcion}'
         
        html += '</div>'
         
        if aplicado and saldo_anterior is not None:
            html += '<div class="mb-3 p-2 bg-white rounded shadow-sm border-start border-warning border-4">'
            html += f'<div><strong>Saldo anterior:</strong> <span class="text-primary">{self._format_money(saldo_anterior)}</span></div>'
            html += '</div>'
         
        if rango_log:
            html += '<div class="mt-3 mb-3">'
            html += '<h6 class="mb-2">Rangos evaluados:</h6>'
             
            html += '<ul class="list-group mb-0">'
            for label, estado in rango_log:
                item_class = "list-group-item-success" if estado == "Si" else "list-group-item-light"
                icon = '<i class="fa fa-check-circle text-success"></i>' if estado == "Si" else '<i class="fa fa-times-circle text-danger"></i>'
                html += f'<li class="list-group-item {item_class} py-1">{icon} {label}</li>'
            html += '</ul>'
            html += '</div>'
         
        if pasos and aplicado:
            html += '<div class="mt-3">'
            html += '<h6 class="mb-2">Pasos del cálculo:</h6>'
             
            html += '<div class="table-responsive">'
            html += '<table class="table table-sm table-bordered">'
            html += '<tbody>'
            for i, paso in enumerate(pasos, 1):
                html += f'<tr><td class="text-center" style="width: 40px;">{i}</td><td>{paso.upper()}</td></tr>'
            html += '</tbody></table>'
            html += '</div>'
            html += '</div>'
         
        html += '</div>'
        return html

    # --------------------------------------------------------------------
    # ↓ Armado de reporte (forma legacy + graf) ---------------------------
    def _generar_reporte(self, valores: Mapping[str, Any], empleado, parametros_anuales, liquidacion):
        """Genera reporte de retención en la fuente en formato estandarizado"""
        etiquetas = ["Salario", "Comisiones", "Dev. Salarial", "Dev. No Salarial"]
        valores_grafico = [valores["salario"], valores["comisiones"], valores["dev_salarial"], valores["dev_no_salarial"]]
        etiquetas_filtradas = [etq for etq, val in zip(etiquetas, valores_grafico) if val]
        valores_filtrados = [float(self._redondear(val)) for val in valores_grafico if val]
        
        return {
            "year": liquidacion.date_to.year,
            "uvt": parametros_anuales.value_uvt,
            "employee_name": empleado.name,
            "employee_document": empleado.identification_id,
            "dias": {
                "trabajados": valores["dias_trabajados"],
                "nov_remunerada": valores["dias_remunerados"],
                "nov_no_remunerada": valores["dias_no_remunerados"],
            },
            "ingresos": {
                "salario": valores["salario"],
                "comisiones": valores["comisiones"],
                "dev_salarial": valores["dev_salarial"],
                "dev_no_salarial": valores["dev_no_salarial"],
                "otros_ingresos": valores["otros_ingresos"],
                "excluidos": valores.get("excluidos", 0),
                "total": valores["ingreso_total"],
            },
            "aportes_obligatorios": {
                "pension": valores["pension"],
                "salud": valores["salud"],
                "total": valores["no_gravados"],
            },
            "deducciones": {
                "vivienda": valores["deduccion_vivienda"],
                "limite_vivienda": parametros_anuales.value_uvt * 100,
                "dependientes": valores["deduccion_dependientes"],
                "limite_dependientes": parametros_anuales.value_uvt * 32,
                "salud_prepagada": valores["deduccion_salud"],
                "limite_salud": parametros_anuales.value_uvt * 16,
                "total": valores["total_deducciones"],
            },
            "rentas_exentas": {
                "afc": valores["afc"],
                "limite_afc": parametros_anuales.value_uvt * (3800/12),
                "renta_exenta_25": valores["renta_exenta25"],
                "limite_renta_25": parametros_anuales.value_uvt * (790/12),
                "total": valores["renta_exenta_afc"],
            },
            "base_calculo": {
                "subtotal_1": valores["subtotal1"],
                "subtotal_2": valores["subtotal2"],
                "subtotal_3": valores["subtotal3"],
                "base_uvts": valores["base_retencion_uvt"],
            },
            "retencion": {
                "tarifa": valores["tarifa"],
                "resta_uvt": parametros_anuales.value_uvt * valores["resta_uvt"],
                "valor": valores["retencion"],
            },
            "proyeccion": {"es_proyectado": valores.get("proyectado", False)},
            "graf": {"labels": etiquetas_filtradas, "values": valores_filtrados},
        }

    # ====================================================================
    # 1) Procedimiento 1 – Salarios
    # ====================================================================
    @api.model
    def _retencion_procedimiento1(self, datos: Dict[str, Any]):
        """Procedimiento 1 - art. 383 ET - Retención en la fuente para salarios"""
        contrato, liquidacion, parametros_anuales = datos["contract"], datos["slip"], datos["annual_parameters"]
        
        # Validaciones iniciales y casos especiales
        if contrato.contract_type == "aprendizaje":
            periodo = f"{liquidacion.date_from.strftime('%d/%m/%Y')} - {liquidacion.date_to.strftime('%d/%m/%Y')}"
            log_html = self._build_ssocial_html_log(
                periodo=periodo,
                aplicado=False,
                descripcion="No aplica retención para contratos de aprendizaje"
            )
            return Decimal(0), -1, 0, "", [], log_html
            
        if contrato.retention_procedure == "fixed":
            valor_fijo = Decimal(contrato.fixed_value_retention_procedure)
            periodo = f"{liquidacion.date_from.strftime('%d/%m/%Y')} - {liquidacion.date_to.strftime('%d/%m/%Y')}"
            log_html = self._build_ssocial_html_log(
                periodo=periodo,
                aplicado=True,
                descripcion=f"Retención fija establecida en contrato: {self._format_money(float(valor_fijo))}",
                pasos=["Aplicación directa del valor fijo configurado en el contrato"]
            )
            return valor_fijo, -1, 100, "", [], log_html

        herramientas = self.env["payroll.tools.service"]
        diccionario_local = datos["localdict"]
        
        # Cálculo de ingresos por categorías
        categorias = herramientas.totalizar_categorias(
            diccionario_local, 
            categorias=["BASIC", "COMISIONES", "DEV_SALARIAL", "DEV_NO_SALARIAL"], 
            current=True, 
            before_month=True, 
            incluir_multi=True
        )
        
        salario = categorias.get("BASIC", 0)
        comisiones = categorias.get("COMISIONES", 0)
        devengos_salariales = categorias.get("DEV_SALARIAL", 0) - salario - comisiones
        devengos_no_salariales = categorias.get("DEV_NO_SALARIAL", 0)

        # Proyección quincenal si aplica (primera quincena)
        es_proyectado = contrato.proyectar_ret and liquidacion.date_from.day <= 15
        dias_trabajados, dias_remunerados, dias_no_remunerados = self._calcular_dias(liquidacion)
        
        # Pasos para el log
        pasos_calculo = []
        pasos_calculo.append(f"Salario base: {self._format_money(float(salario))}")
        pasos_calculo.append(f"Comisiones: {self._format_money(float(comisiones))}")
        pasos_calculo.append(f"Devengos salariales: {self._format_money(float(devengos_salariales))}")
        pasos_calculo.append(f"Devengos no salariales: {self._format_money(float(devengos_no_salariales))}")
        
        if es_proyectado:
            dias_habiles = dias_trabajados + dias_remunerados or Decimal(30)
            salario_original = salario
            salario *= Decimal((30 - dias_trabajados) + 15)/(dias_trabajados or Decimal(1))
            factor_proyeccion = Decimal((30 - dias_habiles) + 15)/dias_habiles
            comisiones_original = comisiones
            comisiones = comisiones * factor_proyeccion
            devengos_salariales_original = devengos_salariales
            devengos_salariales = devengos_salariales * factor_proyeccion
            devengos_no_salariales_original = devengos_no_salariales
            devengos_no_salariales = devengos_no_salariales * factor_proyeccion
            
            pasos_calculo.append(f"PROYECCIÓN QUINCENAL ACTIVADA")
            pasos_calculo.append(f"Salario proyectado: {self._format_money(float(salario_original))} → {self._format_money(float(salario))}")
            pasos_calculo.append(f"Comisiones proyectadas: {self._format_money(float(comisiones_original))} → {self._format_money(float(comisiones))}")
            pasos_calculo.append(f"Devengos salariales proyectados: {self._format_money(float(devengos_salariales_original))} → {self._format_money(float(devengos_salariales))}")
            pasos_calculo.append(f"Devengos no salariales proyectados: {self._format_money(float(devengos_no_salariales_original))} → {self._format_money(float(devengos_no_salariales))}")
            
        otros_ingresos = devengos_salariales + devengos_no_salariales
        ingreso_total = salario + comisiones + otros_ingresos
        
        pasos_calculo.append(f"Total ingresos: {self._format_money(float(ingreso_total))}")

        # Ingresos no constitutivos de renta - aportes obligatorios
        seguridad_social = herramientas.totalizar_reglas(
            diccionario_local, 
            codigos=["SSOCIAL001", "SSOCIAL002", "SSOCIAL003", "SSOCIAL004"], 
            current=True, 
            before_month=True
        )
        
        aporte_salud = abs(seguridad_social.get("SSOCIAL001", 0))
        aporte_pension = abs(seguridad_social.get("SSOCIAL002", 0) + 
                          seguridad_social.get("SSOCIAL003", 0) + 
                          seguridad_social.get("SSOCIAL004", 0))
                          
        if es_proyectado:
            aporte_salud_original = aporte_salud
            aporte_salud = aporte_salud * factor_proyeccion
            aporte_pension_original = aporte_pension
            aporte_pension = aporte_pension * factor_proyeccion
            
            pasos_calculo.append(f"Aportes a salud proyectados: {self._format_money(float(aporte_salud_original))} → {self._format_money(float(aporte_salud))}")
            pasos_calculo.append(f"Aportes a pensión proyectados: {self._format_money(float(aporte_pension_original))} → {self._format_money(float(aporte_pension))}")
            
        ingresos_no_gravados = aporte_salud + aporte_pension
        ingreso_base = ingreso_total - ingresos_no_gravados
        
        pasos_calculo.append(f"Total aportes obligatorios: {self._format_money(float(ingresos_no_gravados))}")
        pasos_calculo.append(f"Ingreso base después de aportes: {self._format_money(float(ingreso_base))}")

        # Deducciones permitidas
        valor_uvt = Decimal(parametros_anuales.value_uvt)
        deduccion_vivienda = self._deduccion_vivienda(contrato, valor_uvt)
        deduccion_dependientes = self._deduccion_dependientes(contrato, ingreso_total, valor_uvt)
        deduccion_salud = self._deduccion_salud(contrato, valor_uvt)
        total_deducciones = deduccion_vivienda + deduccion_dependientes + deduccion_salud
        
        pasos_calculo.append(f"Deducción intereses vivienda: {self._format_money(float(deduccion_vivienda))} (máx. {self._format_money(float(valor_uvt * 100))})")
        pasos_calculo.append(f"Deducción dependientes: {self._format_money(float(deduccion_dependientes))} (máx. {self._format_money(float(valor_uvt * 32))})")
        pasos_calculo.append(f"Deducción salud prepagada: {self._format_money(float(deduccion_salud))} (máx. {self._format_money(float(valor_uvt * 16))})")
        pasos_calculo.append(f"Total deducciones: {self._format_money(float(total_deducciones))}")

        # Rentas exentas (AFC y 25%)
        afc = herramientas.totalizar_reglas(
            diccionario_local, 
            codigos=["AFC"], 
            current=True
        ).get("AFC", 0).copy_abs()
        
        renta_exenta_afc = min(afc, 
                              valor_uvt * Decimal(3800) / Decimal(12), 
                              ingreso_total * Decimal("0.30"))
                              
        pasos_calculo.append(f"Aporte AFC: {self._format_money(float(afc))}")
        pasos_calculo.append(f"Renta exenta AFC: {self._format_money(float(renta_exenta_afc))} (máx. {self._format_money(float(valor_uvt * Decimal(3800) / Decimal(12)))})")
        
        renta_exenta25 = self._redondear((ingreso_base - total_deducciones - renta_exenta_afc) * Decimal("0.25"))
        renta_exenta25 = min(renta_exenta25, valor_uvt * Decimal(790) / Decimal(12))
        
        pasos_calculo.append(f"Renta exenta 25%: {self._format_money(float(renta_exenta25))} (máx. {self._format_money(float(valor_uvt * Decimal(790) / Decimal(12)))})")

        # Límites y cálculo de base gravable
        limite_40_porciento = ingreso_base * Decimal("0.40")
        limite_1340_uvt = valor_uvt * Decimal(1340) / Decimal(12)
        
        pasos_calculo.append(f"Límite 40% de ingresos: {self._format_money(float(limite_40_porciento))}")
        pasos_calculo.append(f"Límite 1340 UVT mensual: {self._format_money(float(limite_1340_uvt))}")
        
        limite_deducciones = min(total_deducciones + renta_exenta_afc + renta_exenta25, 
                               limite_40_porciento, 
                               limite_1340_uvt)
        
        pasos_calculo.append(f"Límite aplicable: {self._format_money(float(limite_deducciones))}")
                               
        base_retencion = ingreso_base - limite_deducciones
        base_retencion_uvt = base_retencion / valor_uvt
        
        pasos_calculo.append(f"Base gravable en pesos: {self._format_money(float(base_retencion))}")
        pasos_calculo.append(f"Base gravable en UVT: {float(base_retencion_uvt):.2f} UVT")
        
        valor_retencion, tarifa, resta_uvt = self._aplicar_tabla_383(base_retencion_uvt, valor_uvt)
        
        # Determinar rango aplicado para el log
        rangos_evaluados = []
        for desde, hasta, porcentaje, _, _ in _TABLA_ART383:
            rango_texto = f"Entre {float(desde):.0f} y {float(hasta):.0f} UVT: {porcentaje}%"
            if desde <= base_retencion_uvt < hasta:
                rangos_evaluados.append((rango_texto, "Si"))
                pasos_calculo.append(f"Tarifa aplicable: {porcentaje}%")
            else:
                rangos_evaluados.append((rango_texto, "No"))
        
        # Redondeo según ley 1111/2006
        valor_retencion_antes_redondeo = valor_retencion
        valor_retencion = self._redondeo_legal(valor_retencion)  # Redondeo Ley 1111/2006
        
        pasos_calculo.append(f"Valor retención antes de redondeo: {self._format_money(float(valor_retencion_antes_redondeo))}")
        pasos_calculo.append(f"Valor retención final (con redondeo ley 1111/2006): {self._format_money(float(valor_retencion))}")

        valores_calculo = {
            "dias_trabajados": dias_trabajados, 
            "dias_remunerados": dias_remunerados, 
            "dias_no_remunerados": dias_no_remunerados,
            "salario": salario, 
            "comisiones": comisiones, 
            "dev_salarial": devengos_salariales, 
            "dev_no_salarial": devengos_no_salariales,
            "otros_ingresos": otros_ingresos, 
            "ingreso_total": ingreso_total,
            "pension": aporte_pension, 
            "salud": aporte_salud, 
            "no_gravados": ingresos_no_gravados,
            "deduccion_vivienda": deduccion_vivienda, 
            "deduccion_dependientes": deduccion_dependientes, 
            "deduccion_salud": deduccion_salud, 
            "total_deducciones": total_deducciones,
            "afc": afc, 
            "renta_exenta_afc": renta_exenta_afc, 
            "renta_exenta25": renta_exenta25,
            "subtotal1": ingreso_base - total_deducciones, 
            "subtotal2": ingreso_base - total_deducciones - renta_exenta_afc, 
            "subtotal3": base_retencion,
            "base_retencion_uvt": base_retencion_uvt, 
            "tarifa": tarifa, 
            "resta_uvt": resta_uvt, 
            "retencion": valor_retencion, 
            "proyectado": es_proyectado,
        }
        
        # Generar log HTML
        periodo = f"{liquidacion.date_from.strftime('%d/%m/%Y')} - {liquidacion.date_to.strftime('%d/%m/%Y')}"
        log_html = self._build_ssocial_html_log(
            periodo=periodo,
            aplicado=True,
            descripcion=f"Retención en la fuente Procedimiento 1 - Base {self._format_money(float(base_retencion))}, Valor {self._format_money(float(valor_retencion))}",
            rango_log=rangos_evaluados,
            pasos=pasos_calculo
        )
        
        reporte = self._generar_reporte(valores_calculo, datos["employee"], parametros_anuales, liquidacion)
        return valor_retencion, -1, 100, f"RT Proc‑1 Base {self._redondear(base_retencion):,}", [reporte], log_html

    # ====================================================================
    # 2) Indemnización art. 401‑3 (20 % con exención 25 %)
    # ====================================================================
    @api.model
    def _retencion_indemnizacion(self, datos: Dict[str, Any]):
        """Retención para indemnizaciones - art. 401-3 ET - 20% con exención 25%"""
        contrato, liquidacion, parametros_anuales = datos["contract"], datos["slip"], datos["annual_parameters"]
        pasos_calculo = []
        
        # Validación inicial
        if contrato.contract_type == "aprendizaje":
            periodo = f"{liquidacion.date_from.strftime('%d/%m/%Y')} - {liquidacion.date_to.strftime('%d/%m/%Y')}"
            log_html = self._build_ssocial_html_log(
                periodo=periodo,
                aplicado=False,
                descripcion="No aplica retención para contratos de aprendizaje"
            )
            return Decimal(0), 0, 0, "", [], log_html

        herramientas = self.env["payroll.tools.service"]
        diccionario_local = datos["localdict"]

        # Ingresos mensuales (todos los devengos base_compensation)
        reglas = self.env["hr.salary.rule"].search([("base_compensation", "=", True)])
        codigos = [regla.code for regla in reglas]
        ingresos_actuales = herramientas.totalizar_reglas(diccionario_local, codigos=codigos, current=True)
        ingresos_mensuales = sum(ingresos_actuales.values())
        pasos_calculo.append(f"Ingresos mensuales actuales: {self._format_money(float(ingresos_mensuales))}")

        # Acumular periodos del mes previos al slip actual
        ingresos_previos_mes = herramientas.totalizar_reglas(diccionario_local, codigos=codigos, before_month=True)
        total_ingresos_previos = sum(ingresos_previos_mes.values())
        total_mes = ingresos_mensuales + total_ingresos_previos
        pasos_calculo.append(f"Ingresos en periodos previos: {self._format_money(float(total_ingresos_previos))}")
        pasos_calculo.append(f"Total ingresos mes: {self._format_money(float(total_mes))}")

        # Verificar límite de 204 UVT
        valor_uvt = Decimal(parametros_anuales.value_uvt)
        limite_uvt = Decimal(204) * valor_uvt
        pasos_calculo.append(f"Límite 204 UVT: {self._format_money(float(limite_uvt))}")
        
        rangos_evaluados = [
            (f"Ingresos mensuales <= 204 UVT ({self._format_money(float(limite_uvt))})", "Si" if total_mes <= limite_uvt else "No")
        ]
        
        if total_mes <= limite_uvt:
            periodo = f"{liquidacion.date_from.strftime('%d/%m/%Y')} - {liquidacion.date_to.strftime('%d/%m/%Y')}"
            log_html = self._build_ssocial_html_log(
                periodo=periodo,
                aplicado=False,
                descripcion=f"Ingresos no superan límite de 204 UVT ({self._format_money(float(limite_uvt))})",
                rango_log=rangos_evaluados,
                pasos=pasos_calculo
            )
            
            return Decimal(0), 0, 0, "NA", [{
                "ingresos": {"mensuales": ingresos_mensuales, "previos": total_ingresos_previos, "total": total_mes},
                "limite_uvt": {"valor": limite_uvt, "excede": False}
            }], log_html

        # Valor de indemnización (categoría INDEM)
        reglas_indemnizacion = self.env["hr.salary.rule"].search([("category_id.code", "=", "INDEM")])
        codigos_indemnizacion = [regla.code for regla in reglas_indemnizacion]
        total_indemnizacion = sum(herramientas.totalizar_reglas(
            diccionario_local, 
            codigos=codigos_indemnizacion, 
            current=True
        ).values())
        
        pasos_calculo.append(f"Valor indemnización: {self._format_money(float(total_indemnizacion))}")
        
        rangos_evaluados.append(
            ("Existe pago por indemnización", "Si" if total_indemnizacion > 0 else "No")
        )
        
        if total_indemnizacion == 0:
            periodo = f"{liquidacion.date_from.strftime('%d/%m/%Y')} - {liquidacion.date_to.strftime('%d/%m/%Y')}"
            log_html = self._build_ssocial_html_log(
                periodo=periodo,
                aplicado=False,
                descripcion="No hay pagos por indemnización",
                rango_log=rangos_evaluados,
                pasos=pasos_calculo
            )
            return Decimal(0), 0, 0, "NA", [], log_html

        # Cálculo de retención
        parte_exenta = total_indemnizacion * Decimal("0.25")
        base_gravable = total_indemnizacion - parte_exenta
        valor_retencion = self._redondeo_legal(base_gravable * Decimal("0.20"))
        
        pasos_calculo.append(f"Parte exenta (25%): {self._format_money(float(parte_exenta))}")
        pasos_calculo.append(f"Base gravable (75%): {self._format_money(float(base_gravable))}")
        pasos_calculo.append(f"Retención (20% sobre base gravable): {self._format_money(float(valor_retencion))}")

        reporte = {
            "ingresos": {"mensuales": ingresos_mensuales, "previos": total_ingresos_previos, "total": total_mes},
            "indemnizacion": {"valor": total_indemnizacion, "exenta": parte_exenta, "gravada": base_gravable},
            "limite_uvt": {"valor": limite_uvt, "excede": True}
        }
        
        # Generar log HTML
        periodo = f"{liquidacion.date_from.strftime('%d/%m/%Y')} - {liquidacion.date_to.strftime('%d/%m/%Y')}"
        log_html = self._build_ssocial_html_log(
            periodo=periodo,
            aplicado=True,
            descripcion=f"Retención por indemnización art. 401-3 ET - Base {self._format_money(float(base_gravable))}, Valor {self._format_money(float(valor_retencion))}",
            rango_log=rangos_evaluados,
            pasos=pasos_calculo
        )
        
        return base_gravable, 1, 20, f"RT Indemnización {liquidacion.date_from} – {liquidacion.date_to}", [reporte], log_html

    # ====================================================================
    # 3) Prima de servicios (método anualizado art. 383)
    # ====================================================================
    @api.model
    def _retencion_prima(self, datos: Dict[str, Any]):
        """Prima de servicios - art. 383 ET - método anualizado"""
        contrato, liquidacion, parametros_anuales = datos["contract"], datos["slip"], datos["annual_parameters"]
        herramientas = self.env["payroll.tools.service"]
        diccionario_local = datos["localdict"]
        pasos_calculo = []
        
        # Obtener categoría de prima
        categoria_prima = diccionario_local.get("categories", {}).get("PRIMA", 0)
        pasos_calculo.append(f"Valor prima de servicios: {self._format_money(float(categoria_prima))}")
        
        # Verificar si hay prima para calcular
        if categoria_prima <= 0:
            periodo = f"{liquidacion.date_from.strftime('%d/%m/%Y')} - {liquidacion.date_to.strftime('%d/%m/%Y')}"
            log_html = self._build_ssocial_html_log(
                periodo=periodo,
                aplicado=False,
                descripcion="No hay prima de servicios para calcular retención"
            )
            return Decimal(0), -1, 100, "", [], log_html

        # Base prima (BASIC + COMISIONES + DEV_SALARIAL + SUBSIDIO) en el semestre
        fecha_inicio_semestre = liquidacion.date_to.replace(
            month=1 if liquidacion.date_to.month <= 6 else 7, 
            day=1
        )
        fecha_fin_semestre = liquidacion.date_to
        
        pasos_calculo.append(f"Período semestre: {fecha_inicio_semestre.strftime('%d/%m/%Y')} - {fecha_fin_semestre.strftime('%d/%m/%Y')}")
        
        base_semestre = herramientas.totalizar_categorias(
            diccionario_local, 
            categorias=["BASIC", "COMISIONES", "DEV_SALARIAL", "SUBSIDIO"], 
            fecha_desde=fecha_inicio_semestre, 
            fecha_hasta=fecha_fin_semestre, 
            current=True, 
            before_month=True, 
            incluir_multi=True
        )
        
        valor_base_semestre = sum(base_semestre.values())
        pasos_calculo.append(f"Base semestral: {self._format_money(float(valor_base_semestre))}")

        # Anualizar:  base × 12 / días trabajados semestre
        dias_semestre = (fecha_fin_semestre - fecha_inicio_semestre).days + 1
        ingreso_base_anualizado = valor_base_semestre * Decimal(12) / Decimal(dias_semestre/30)
        pasos_calculo.append(f"Días semestre: {dias_semestre}")
        pasos_calculo.append(f"Base anualizada: {self._format_money(float(ingreso_base_anualizado))}")

        # Convertir a UVT y aplicar tabla art. 383
        valor_uvt = Decimal(parametros_anuales.value_uvt)
        base_retencion_uvt = ingreso_base_anualizado / valor_uvt
        pasos_calculo.append(f"Base anualizada en UVT: {float(base_retencion_uvt):.2f} UVT")
        
        # Evaluar rangos para el log
        rangos_evaluados = []
        for desde, hasta, porcentaje, _, _ in _TABLA_ART383:
            rango_texto = f"Entre {float(desde):.0f} y {float(hasta):.0f} UVT: {porcentaje}%"
            if desde <= base_retencion_uvt < hasta:
                rangos_evaluados.append((rango_texto, "Si"))
                pasos_calculo.append(f"Tarifa aplicable: {porcentaje}%")
            else:
                rangos_evaluados.append((rango_texto, "No"))
        
        valor_retencion, tarifa, resta_uvt = self._aplicar_tabla_383(base_retencion_uvt, valor_uvt)
        valor_retencion_antes_redondeo = valor_retencion
        valor_retencion = self._redondeo_legal(valor_retencion)
        
        pasos_calculo.append(f"Valor retención antes de redondeo: {self._format_money(float(valor_retencion_antes_redondeo))}")
        pasos_calculo.append(f"Valor retención final (con redondeo ley 1111/2006): {self._format_money(float(valor_retencion))}")

        reporte = {
            "base_prima_sem": valor_base_semestre,
            "base_anualizada": ingreso_base_anualizado,
            "base_uvt": base_retencion_uvt,
            "retencion": valor_retencion,
            "tarifa": tarifa
        }
        
        # Generar log HTML
        periodo = f"{liquidacion.date_from.strftime('%d/%m/%Y')} - {liquidacion.date_to.strftime('%d/%m/%Y')}"
        log_html = self._build_ssocial_html_log(
            periodo=periodo,
            aplicado=True,
            descripcion=f"Retención prima de servicios - Base anualizada {self._format_money(float(ingreso_base_anualizado))}, Valor {self._format_money(float(valor_retencion))}",
            rango_log=rangos_evaluados,
            pasos=pasos_calculo
        )
        
        return ingreso_base_anualizado, -1, 100, f"RT Prima base {self._redondear(ingreso_base_anualizado):,}", [reporte], log_html

    # ====================================================================
    # 4) Extranjero no residente – tarifa única 20 %
    # ====================================================================
    @api.model
    def _retencion_extranjero20(self, datos: Dict[str, Any]):
        """Retención para extranjeros no residentes - art. 408 ET - tarifa única 20%"""
        contrato, liquidacion = datos["contract"], datos["slip"]
        herramientas = self.env["payroll.tools.service"]
        diccionario_local = datos["localdict"]
        pasos_calculo = []
        
        # Verificar si el empleado es extranjero no residente
        es_extranjero = getattr(contrato.employee_id, 'foreigner', False)
        if not es_extranjero:
            periodo = f"{liquidacion.date_from.strftime('%d/%m/%Y')} - {liquidacion.date_to.strftime('%d/%m/%Y')}"
            log_html = self._build_ssocial_html_log(
                periodo=periodo,
                aplicado=False,
                descripcion="No aplica tarifa de extranjero no residente"
            )
            return Decimal(0), 0, 0, "", [], log_html
        
        # Calcular total ingresos
        total_ingresos = herramientas.obtener_totales(diccionario_local, current=True)["devengos"]
        pasos_calculo.append(f"Total ingresos devengados: {self._format_money(float(total_ingresos))}")
        
        # Calcular retención (20% sobre total ingresos)
        valor_retencion_antes_redondeo = total_ingresos * Decimal("0.20")
        valor_retencion = self._redondeo_legal(valor_retencion_antes_redondeo)
        
        pasos_calculo.append(f"Tarifa aplicable: 20% (art. 408 ET para extranjeros no residentes)")
        pasos_calculo.append(f"Valor retención antes de redondeo: {self._format_money(float(valor_retencion_antes_redondeo))}")
        pasos_calculo.append(f"Valor retención final (con redondeo ley 1111/2006): {self._format_money(float(valor_retencion))}")
        
        # Generar log HTML
        periodo = f"{liquidacion.date_from.strftime('%d/%m/%Y')} - {liquidacion.date_to.strftime('%d/%m/%Y')}"
        log_html = self._build_ssocial_html_log(
            periodo=periodo,
            aplicado=True,
            descripcion=f"Retención para extranjero no residente - Base {self._format_money(float(total_ingresos))}, Valor {self._format_money(float(valor_retencion))}",
            pasos=pasos_calculo
        )
        
        return total_ingresos, 1, 20, "RT Extranjero no residente 20 %", [{
            "base": total_ingresos, 
            "retencion": valor_retencion
        }], log_html

    # ====================================================================
    # Método para retencion en la fuente de prima (implementación directa)
    # ====================================================================
    @api.model
    def _retencion_prima_directa(self, payslip, employee, contract, categories, annual_parameters):
        """Retención directa para prima de servicios según art. 383 ET"""
        resultado = 0.0
        pasos_calculo = []
        
        regla_salarial = payslip.get_salary_rule('RET_PRIMA', employee.type_employee.id)
        
        if not regla_salarial or contract.contract_type == 'aprendizaje' or contract.modality_salary == 'integral':
            periodo = f"{payslip.date_from.strftime('%d/%m/%Y')} - {payslip.date_to.strftime('%d/%m/%Y')}"
            log_html = self._build_ssocial_html_log(
                periodo=periodo,
                aplicado=False,
                descripcion="No aplica retención para prima (contrato aprendizaje o salario integral)"
            )
            return resultado, log_html
        
        dia_inicial_nomina = payslip.date_from.day
        valor_uvt = annual_parameters.value_uvt
        pasos_calculo.append(f"Valor UVT: {self._format_money(float(valor_uvt))}")
        
        valor_base = categories.PRIMA
        pasos_calculo.append(f"Valor prima: {self._format_money(float(valor_base))}")
        
        if valor_base <= 0:
            periodo = f"{payslip.date_from.strftime('%d/%m/%Y')} - {payslip.date_to.strftime('%d/%m/%Y')}"
            log_html = self._build_ssocial_html_log(
                periodo=periodo,
                aplicado=False,
                descripcion="No hay prima de servicios para calcular retención"
            )
            return resultado, log_html
        
        valor_tope = annual_parameters.value_top_source_retention
        pasos_calculo.append(f"Valor tope retención: {self._format_money(float(valor_tope))}")
        
        # Aplicar exención del 25%
        base = valor_base * 0.75
        pasos_calculo.append(f"Base gravable (75% de prima): {self._format_money(float(base))}")
        
        # Convertir a UVT
        total_uvt = base / valor_uvt
        pasos_calculo.append(f"Base gravable en UVT: {float(total_uvt):.2f} UVT")
        
        # Evaluar rangos para el log
        rangos_evaluados = []
        
        # Aplicar tabla art. 383 ET
        if total_uvt >= 0 and total_uvt < 95:
            resultado = 0
            rangos_evaluados.append(("Entre 0 y 95 UVT: 0%", "Si"))
        elif total_uvt >= 95 and total_uvt <= 150:
            resultado = round((total_uvt - 95) * 0.19 * valor_uvt, 2) * -1
            rangos_evaluados.append(("Entre 95 y 150 UVT: 19%", "Si"))
            pasos_calculo.append(f"Cálculo: ({float(total_uvt):.2f} - 95) * 19% * {float(valor_uvt):.2f} = {float(abs(resultado)):.2f}")
        elif total_uvt > 150 and total_uvt <= 360:
            resultado = round((total_uvt - 150) * 0.28 * valor_uvt + 10 * valor_uvt, 2) * -1
            rangos_evaluados.append(("Entre 150 y 360 UVT: 28% + 10 UVT", "Si"))
            pasos_calculo.append(f"Cálculo: ({float(total_uvt):.2f} - 150) * 28% * {float(valor_uvt):.2f} + 10 * {float(valor_uvt):.2f} = {float(abs(resultado)):.2f}")
        elif total_uvt > 360 and total_uvt <= 640:
            resultado = round((total_uvt - 360) * 0.33 * valor_uvt + 69 * valor_uvt, 2) * -1
            rangos_evaluados.append(("Entre 360 y 640 UVT: 33% + 69 UVT", "Si"))
            pasos_calculo.append(f"Cálculo: ({float(total_uvt):.2f} - 360) * 33% * {float(valor_uvt):.2f} + 69 * {float(valor_uvt):.2f} = {float(abs(resultado)):.2f}")
        elif total_uvt > 640 and total_uvt <= 945:
            resultado = round((total_uvt - 640) * 0.35 * valor_uvt + 162 * valor_uvt, 2) * -1
            rangos_evaluados.append(("Entre 640 y 945 UVT: 35% + 162 UVT", "Si"))
            pasos_calculo.append(f"Cálculo: ({float(total_uvt):.2f} - 640) * 35% * {float(valor_uvt):.2f} + 162 * {float(valor_uvt):.2f} = {float(abs(resultado)):.2f}")
        elif total_uvt > 945 and total_uvt <= 2300:
            resultado = round((total_uvt - 945) * 0.37 * valor_uvt + 268 * valor_uvt, 2) * -1
            rangos_evaluados.append(("Entre 945 y 2300 UVT: 37% + 268 UVT", "Si"))
            pasos_calculo.append(f"Cálculo: ({float(total_uvt):.2f} - 945) * 37% * {float(valor_uvt):.2f} + 268 * {float(valor_uvt):.2f} = {float(abs(resultado)):.2f}")
        elif total_uvt > 2300:
            resultado = round((total_uvt - 2300) * 0.39 * valor_uvt + 770 * valor_uvt, 2) * -1
            rangos_evaluados.append(("Mayor a 2300 UVT: 39% + 770 UVT", "Si"))
            pasos_calculo.append(f"Cálculo: ({float(total_uvt):.2f} - 2300) * 39% * {float(valor_uvt):.2f} + 770 * {float(valor_uvt):.2f} = {float(abs(resultado)):.2f}")
        
        # Generar log HTML
        periodo = f"{payslip.date_from.strftime('%d/%m/%Y')} - {payslip.date_to.strftime('%d/%m/%Y')}"
        log_html = self._build_ssocial_html_log(
            periodo=periodo,
            aplicado=resultado != 0,
            descripcion=f"Retención prima de servicios directa - Base {self._format_money(float(base))}, Valor {self._format_money(float(abs(resultado)))}",
            rango_log=rangos_evaluados,
            pasos=pasos_calculo
        )
        
        return resultado, log_html

    # ====================================================================
    # Método para retención en indemnización (implementación directa)
    # ====================================================================
    @api.model
    def _RTF_INDEM(self, datos_liquidacion):
        """Retención en la fuente para indemnizaciones directa"""
        pasos_calculo = []
        
        # Verificar si ya se calculó la indemnización
        if 'INDEM_value' not in datos_liquidacion or 'INDEM_qty' not in datos_liquidacion:
            self._compute_indem(datos_liquidacion)
        
        valor_dia = datos_liquidacion.get('INDEM_value', 0)
        dias = datos_liquidacion.get('INDEM_qty', 0)
        
        pasos_calculo.append(f"Valor día indemnización: {self._format_money(float(valor_dia))}")
        pasos_calculo.append(f"Cantidad días: {dias}")
        
        # Obtener valor UVT
        valor_uvt = datos_liquidacion['economic_variables']['UVT'][datos_liquidacion['period'].start.year]
        pasos_calculo.append(f"Valor UVT: {self._format_money(float(valor_uvt))}")
        
        # Calcular valor total indemnización
        valor_total = valor_dia * 30
        pasos_calculo.append(f"Valor mensual: {self._format_money(float(valor_total))}")
        
        # Verificar límite de 204 UVT
        limite_uvt = 204 * valor_uvt
        pasos_calculo.append(f"Límite 204 UVT: {self._format_money(float(limite_uvt))}")
        
        # Evaluar rangos para el log
        rangos_evaluados = [
            (f"Valor mensual <= 204 UVT ({self._format_money(float(limite_uvt))})", "Si" if valor_total <= limite_uvt else "No")
        ]
        
        if valor_total <= limite_uvt:
            periodo = f"{datos_liquidacion['period'].start} - {datos_liquidacion['period'].end}"
            log_html = self._build_ssocial_html_log(
                periodo=periodo,
                aplicado=False,
                descripcion=f"Mensualidad no supera límite de 204 UVT ({self._format_money(float(limite_uvt))})",
                rango_log=rangos_evaluados,
                pasos=pasos_calculo
            )
            return None, log_html
        
        # Aplicar exención del 25%
        base_gravable = valor_dia * dias * 0.75
        pasos_calculo.append(f"Base gravable (75% de indemnización): {self._format_money(float(base_gravable))}")
        
        # Aplicar tarifa del 20%
        valor_retencion = base_gravable * 0.20
        pasos_calculo.append(f"Tarifa aplicable: 20%")
        pasos_calculo.append(f"Valor retención: {self._format_money(float(valor_retencion))}")
        
        # Generar log HTML
        periodo = f"{datos_liquidacion['period'].start} - {datos_liquidacion['period'].end}"
        log_html = self._build_ssocial_html_log(
            periodo=periodo,
            aplicado=True,
            descripcion=f"Retención por indemnización directa - Base {self._format_money(float(base_gravable))}, Valor {self._format_money(float(valor_retencion))}",
            rango_log=rangos_evaluados,
            pasos=pasos_calculo
        )
        
        return valor_retencion, log_html
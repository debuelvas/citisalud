
from dataclasses import dataclass, asdict, field
from datetime import date, datetime
from typing import Dict, List, Tuple, Any

from odoo import api, models, _
from odoo.exceptions import UserError
import logging


_logger = logging.getLogger(__name__)
DAYS_MONTH = 30


# ────────────────────── dataclasses ═════════════════════════════════
@dataclass
class Nomina:
    salarial: float = 0.0
    no_salarial: float = 0.0


@dataclass
class IbdContext:
    payslip:    'hr.payslip'
    contract:   'hr.contract'
    params:     Dict[str, float]

    actual: Nomina = field(default_factory=Nomina)
    previo: Nomina = field(default_factory=Nomina)

    dias: Dict[str, float] = field(default_factory=lambda: {
        'trab': 0, 'rem': 0, 'eff': 0,
        'festivos': 0, 'domingos': 0, 'aus': 0,
    })
    html: str = ""  
    ibc_pre:        float = 0.0      
    ibc_full:       float = 0.0     
    ibc_vacaciones: float = 0.0      
    ibc_final:      float = 0.0   
    day_value:      float = 0.0
    pct_no_salarial: float = 0.0   

    notas: Dict[str, list] = field(default_factory=lambda: {
        'fuera_base': [],        
        'reemplazo_ibc': []      
    })

    log: List[Dict[str, Any]] = field(default_factory=list)
    write_lines: bool = True
    reglas_detalle: List[Dict[str, Any]] = field(default_factory=list) 

    def add_log(self, paso: str, desc: str, datos: Any):
        self.log.append({'paso': paso, 'descripcion': desc, 'datos': datos})


# ────────────────────── servicio IBD ═══════════════════════════════
class IbdService(models.AbstractModel):
    _name = "payroll.ibd.service"
    _description = "Motor de cálculo IBD"


    def _load_params(self, year) -> Dict[str, float]:
        ap = self.env['hr.annual.parameters'].search([('year', '=', year)], limit=1)
        if not ap:
            raise UserError(_('Falta configurar parámetros anuales'))
        return {
            'SMMLV_DAILY':   ap.smmlv_daily,
            'TOPE_25_SMMLV': ap.top_twenty_five_smmlv,
            'TOPE_40':       ap.value_porc_statute_1395 / 100,
            'INT_FACTOR':    ap.porc_integral_salary / 100,
            'GI_B2':   1.00,
            'GI_B90':  0.6667,
            'GI_B180': 0.50,
            'GI_A180': 0.50,
        }


    def _category_code(self, rule):
        cat = rule.category_id
        while cat:
            
            if cat.code in ('DEV_SALARIAL', 'DEV_NO_SALARIAL'):
                return cat.code
            elif cat.code in ("INDEM","PRESTACIONES_SOCIALES"):
                return None
            cat = cat.parent_id
        return None
    
    def _format_m(self, x): 
        return "${:,.2f}".format(x).replace(",", " ").replace(".", ",").replace(" ", ".")

    def _build_ssocial_html_log(
        self,
        periodo: str,
        aplicado: bool,
        descripcion: str,
        saldo_anterior: float | None = None,
        rango_log: List[Tuple[str, str]] | None = None,
        pasos: List[str] | None = None,
        ibc_vac: float | None = None,
        ibc_final: float | None = None,
    ) -> str:
        html = ['<div class="p-3 border rounded bg-light simulation-container">']

        # encabezado
        html += [
            '<div class="d-flex justify-content-between align-items-center mb-3 pb-2 border-bottom">',
            '<h5 class="mb-0 text-primary">Cálculo IBC</h5>',
            f'<span class="badge {"bg-success" if aplicado else "bg-danger"}">'
            f'{"Aplicado" if aplicado else "No aplicado"}</span></div>',
            f'<div class="mb-2"><b>Periodo:</b> {periodo}</div>',
            f'<div class="mb-3 alert {"alert-success" if aplicado else "alert-danger"} p-2">'
            f'{descripcion}</div>',
        ]

        if saldo_anterior is not None:
            html.append(
                f'<div class="mb-2 p-2 bg-white rounded border-start border-warning border-4">'
                f'Saldo antes de topes: <b class="text-primary">{self._format_m(saldo_anterior)}</b></div>'
            )

        if ibc_vac is not None:
            html.append(
                f'<div class="mb-2 p-2 bg-info-subtle rounded">'
                f'IBC Vacaciones (100 %): <b>{self._format_m(ibc_vac)}</b><br/>'
                f'IBC aplicado al slip: <b>{self._format_m(ibc_final)}</b></div>'
            )

        if rango_log:
            html += ['<h6 class="mt-3 mb-2">Rangos evaluados:</h6><ul class="list-group mb-3">']
            for lbl, ok in rango_log:
                ico = 'fa-check text-success' if ok.lower() == 'si' else 'fa-times text-danger'
                item = "list-group-item-success" if ok.lower() == 'si' else "list-group-item-light"
                html.append(f'<li class="list-group-item {item} py-1"><i class="fa {ico} me-1"></i>{lbl}</li>')
            html.append('</ul>')

        if pasos:
            html += ['<h6 class="mb-2">Pasos:</h6><table class="table table-sm">']
            for i, p in enumerate(pasos, 1):
                html.append(f'<tr><td style="width:40px">{i}</td><td>{p}</td></tr>')
            html.append('</table>')

        html.append('</div>')
        return "".join(html)


    def _prev_ibc(self, ctx: IbdContext) -> float:
        sal, nos = ctx.previo.salarial, ctx.previo.no_salarial
        exced = max(0.0, nos - (sal + nos) * ctx.params['TOPE_40'])
        return min(sal + exced, ctx.params['TOPE_25_SMMLV'])


    def _push_rule_detail(
        self, *,
        lista:   list,
        line:    'hr.payslip.line',
        usado:   float,
        incluido: bool,
        paso:    str,
        desc:    str,
    ):
        """Registra la línea de nómina en la lista de auditoría."""
        regla = line.salary_rule_id
        lista.append({
            'fecha':       line.slip_id.date_to,
            'codigo':      regla.code,
            'nombre':      regla.name,
            'total':       line.total,
            'incluida':    incluido,
            'valor_usado': usado,
            'tipo':        self._category_code(regla) or 'desconocido',
            'categoria':   regla.category_id.code if regla.category_id else '',
            'categoria_padre':
                regla.category_id.parent_id.code if regla.category_id and regla.category_id.parent_id else '',
            'es_ausencia': bool(line.leave_id),
            'paso':        paso,
            'descripcion_paso': desc,
        })


    def _collect_leave_lines(self, payslip_lines, rules_multi) -> Dict[int, List['hr.payslip.line']]:
        """Devuelve {leave_id: [hr.payslip.line,…]} (solo los del mes en curso)."""
        res = {}


        for per in payslip_lines.values():
            for tag in ('current_month',):
                for ent in per.get(tag, {}).get('entries', []):
                    pl = ent['payslip_id']
                    if pl.leave_id:
                        res.setdefault(pl.leave_id.id, []).append(pl)


        for rm in rules_multi.values():
            cur = rm.get('current', {})
            leave_map = cur.get('leave', {})
            for lv_id, lv in leave_map.items():
                # lv es hr.leave
                for ll in lv.line_ids:
                    if ll.payslip_id == cur.get('payslip_id'):
                        res.setdefault(lv_id, []).append(ll.payslip_id)

        return res


    def _apply_absence_block(self, grupos, ctx, slip_start: date, slip_end: date):
        smmlv_d  = ctx.params['SMMLV_DAILY']
        prev_ibc = self._prev_ibc(ctx)
        base_d   = prev_ibc / DAYS_MONTH

        def day_in(d):       
            return slip_start <= d <= slip_end

        vac_full = 0.0     

        for gid, plines in grupos.items():
            master_leave = plines[0].leave_id
            is_vac       = master_leave.holiday_status_id.is_vacation

            for pl in plines:
                ll   = pl.leave_id
                for l in ll.line_ids:
                    seq  = l.sequence
                    dias = l.days_payslip or 1.0

                    if not day_in(l.date):
                        continue
                    rate, _ = master_leave.holiday_status_id.get_rate_concept_id(int(seq))
                    val_d   = max(base_d * rate, smmlv_d)
                    val_new = round(val_d * dias, 2)

                    ctx.actual.salarial += val_new
                    if ctx.write_lines:
                        pl.amount_base = val_new

                    if is_vac:
                        vac_full += val_new

        ctx.ibc_vacaciones = vac_full

    def compute(self, localdict, payslip: 'hr.payslip', write_lines=True) -> IbdContext:
        contract = payslip.contract_id
        ctx = IbdContext(
            payslip=payslip,
            contract=contract,
            params=self._load_params(payslip.date_to.year),
            write_lines=write_lines,
        )
        ctx.dias.update(payslip.get_payslip_days_count(payslip.id))
        payslip_lines = localdict.get('payslip_lines', {})
        
        rules_multi   = localdict.get('rules_multi', {})
        
        reglas_detalle: list = []
        
        for tag, nomina in (('current_month', ctx.actual), ('before_month', ctx.previo)):
            paso_tag = '1.A' if tag == 'current_month' else '1.B'
            for code, period in payslip_lines.items():
                for ent in period.get(tag, {}).get('entries', []):
                    line = ent['payslip_id']
                    rule = line.salary_rule_id
                    leave_type = line.leave_id.holiday_status_id if line.leave_id else None


                    fuera = (
                        rule.liquidar_con_base or 
                        (self._category_code(rule) == 'DEV_SALARIAL' and not rule.base_seguridad_social) or 
                        (leave_type and leave_type.unpaid_absences)
                    )
                    
                    if fuera:
                        ctx.notas['fuera_base'].append(rule.code)
                        self._push_rule_detail(
                            lista=reglas_detalle, line=line, usado=0.0, incluido=False,
                            paso=paso_tag, desc="Excluida de base"
                        )
                        continue

                    cat = self._category_code(rule)
                    if cat == 'DEV_SALARIAL':
                        nomina.salarial += line.total
                    elif cat == 'DEV_NO_SALARIAL':
                        nomina.no_salarial += line.total
                    
                    self._push_rule_detail(
                        lista=reglas_detalle, line=line, usado=line.total, incluido=True,
                        paso=paso_tag, desc="Incluida en nomina"
                    )

        ctx.add_log('1', f'Nominas preliminares', {'act': asdict(ctx.actual), 'prev': asdict(ctx.previo)})


        for idx, rm in enumerate(rules_multi.values()):
            cur = rm.get('current', {})
            rule = cur.get('object')
            if not rule:
                continue
            total = cur.get('total', 0.0)
            cat = self._category_code(rule)
            if cat == 'DEV_SALARIAL':
                ctx.actual.salarial += total
            elif cat == 'DEV_NO_SALARIAL':
                ctx.actual.no_salarial += total
            

            line_fake = self.env['hr.payslip.line'].new({
                'salary_rule_id': rule.id,
                'total': total,
                'slip_id': payslip.id,
            })
            self._push_rule_detail(
                lista=reglas_detalle, line=line_fake, usado=total, incluido=True,
                paso='1.C', desc="Input múltiple"
            )


        grupos = self._collect_leave_lines(payslip_lines, rules_multi)
        self._apply_absence_block(grupos, ctx, payslip.date_from, payslip.date_to)
        

        for gid, lines in grupos.items():
            for pl in lines:
                self._push_rule_detail(
                    lista=reglas_detalle,
                    line=pl,
                    usado=pl.amount_base or pl.total,
                    incluido=True,
                    paso='2', 
                    desc='Ausencia (ajustada)'
                )

        trab = sum(l.number_of_days for l in payslip.worked_days_line_ids if l.code == 'WORK100')
        rem  = sum(ld.days_payslip for ld in payslip.leave_days_ids
                if not ld.leave_id.holiday_status_id.unpaid_absences)
        ctx.dias.update({'trab': trab, 'rem': rem, 'eff': min(trab + rem, DAYS_MONTH)})

        exced = max(0.0, ctx.actual.no_salarial -
                    (ctx.actual.salarial + ctx.actual.no_salarial) * ctx.params['TOPE_40'])
        ctx.ibc_pre = ctx.actual.salarial + exced

        if contract.modality_salary == 'integral':
            ctx.ibc_pre *= ctx.params['INT_FACTOR']
        ctx.ibc_full = min(ctx.ibc_pre, ctx.params['TOPE_25_SMMLV'])

        if payslip.struct_id and payslip.struct_id.process == 'vacaciones' and ctx.ibc_vacaciones:
            ctx.ibc_final = ctx.ibc_vacaciones * (ctx.dias['eff'] / DAYS_MONTH)
        else:
            ctx.ibc_final = ctx.ibc_full

        ctx.day_value = max(
            ctx.ibc_final / ctx.dias['eff'] if ctx.dias['eff'] else 0.0,
            ctx.params['SMMLV_DAILY']
        )

        total_ns = ctx.actual.no_salarial
        ctx.pct_no_salarial = (total_ns/ctx.ibc_final*100) if ctx.ibc_final else 0.0

        ctx.html = self._build_ssocial_html_log(
            periodo=f"{payslip.date_from:%d/%m/%Y} – {payslip.date_to:%d/%m/%Y}",
            aplicado=True,
            descripcion=_("Cálculo IBC ejecutado"),
            saldo_anterior=ctx.ibc_pre,
            rango_log=[
                ("Tope 40 % NC", "Si" if exced else "No"),
                ("Integral 70 %", "Si" if contract.modality_salary == 'integral' else "No"),
                ("Tope 25 SMMLV", "Si" if ctx.ibc_full < ctx.ibc_pre else "No"),
            ],
            pasos=[f"{l['paso']}. {l['descripcion']}" for l in ctx.log],
            ibc_vac=ctx.ibc_vacaciones if ctx.ibc_vacaciones else None,
            ibc_final=ctx.ibc_final,
        )

        ctx.reglas_detalle = reglas_detalle

        return ctx
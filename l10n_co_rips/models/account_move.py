# -*- coding: utf-8 -*-
from odoo import fields, api, models, _
from odoo.exceptions import UserError

import io, base64, logging
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, Table, TableStyle, Paragraph, Spacer,
    KeepTogether, HRFlowable, Image
)
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
from reportlab.pdfgen import canvas
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.barcode.qr import QrCodeWidget

_logger = logging.getLogger(__name__)

# ===================== Canvas con paginación y footer =====================

class NumberedCanvas(canvas.Canvas):
    """
    Canvas que inserta una línea superior, pie de página y numeración en todas las páginas,
    sin reflujo de contenido. Patrón correcto: guardar estados en showPage() y pintar en save().
    """

    def __init__(self, *args, **kwargs):
        self._saved_page_states = []
        self.company_data = kwargs.pop('company_data', {}) or {}
        self.page_meta = kwargs.pop('page_meta', {}) or {}
        super().__init__(*args, **kwargs)

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        super().showPage()  # Patrón correcto

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_static_elements(num_pages)
            super().showPage()
        super().save()

    def _draw_static_elements(self, page_count:int):
        # Línea superior
        self.setStrokeColor(colors.HexColor('#5a9fd4'))
        self.setLineWidth(1.2)
        self.line(0, A4[1] - 10*mm, A4[0], A4[1] - 10*mm)

        # Texto superior derecho (documento / número)
        right_meta = self.page_meta.get('right_label')
        if right_meta:
            self.setFont("Helvetica-Bold", 9)
            self.setFillColor(colors.HexColor('#2c3e50'))
            self.drawRightString(A4[0] - 15*mm, A4[1] - 7*mm, right_meta)

        # Footer línea
        self.setStrokeColor(colors.HexColor('#e0e0e0'))
        self.setLineWidth(0.6)
        self.line(15*mm, 18*mm, A4[0] - 15*mm, 18*mm)

        # Footer texto
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor('#666666'))
        self.drawString(15*mm, 12*mm, "Documento generado electrónicamente - Válido sin firma")

        # Número de página
        self.drawRightString(A4[0] - 15*mm, 12*mm, f"Página {self._pageNumber} de {page_count}")


# ===================== Generador del reporte =====================

class InvoiceReportLab(models.AbstractModel):
    _name = 'report.invoice_reportlab.report_invoice'
    _description = 'Generador de Facturas Minimalista (ReportLab)'

    # Colores corporativos (1 sola fuente de verdad)
    PRIMARY = colors.HexColor('#5a9fd4')
    DARK = colors.HexColor('#2c3e50')
    LIGHT_BG = colors.HexColor('#f8f9fa')
    SOFT_LINE = colors.HexColor('#e0e0e0')

    def _get_styles(self):
        styles = getSampleStyleSheet()

        styles.add(ParagraphStyle(
            name='CompanyName',
            parent=styles['Heading1'],
            fontName='Helvetica-Bold',
            fontSize=18, leading=20,
            textColor=self.PRIMARY,
            alignment=TA_LEFT,
            spaceAfter=2
        ))
        styles.add(ParagraphStyle(
            name='DocTitle',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=12,
            textColor=self.DARK,
            alignment=TA_RIGHT
        ))
        styles.add(ParagraphStyle(
            name='SectionHeader',
            parent=styles['Heading2'],
            fontName='Helvetica-Bold',
            fontSize=10.5,
            textColor=self.PRIMARY,
            backColor=colors.HexColor('#e8f4fd'),
            spaceBefore=6, spaceAfter=4,
            leftIndent=3
        ))
        styles.add(ParagraphStyle(
            name='NormalText',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=9, leading=12,
            textColor=self.DARK
        ))
        styles.add(ParagraphStyle(
            name='SmallText',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=7.5, leading=10.5,
            textColor=colors.HexColor('#555555')
        ))
        styles.add(ParagraphStyle(
            name='Label',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=9,
            textColor=colors.HexColor('#666666')
        ))
        styles.add(ParagraphStyle(
            name='TotalLabel',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=11, alignment=TA_RIGHT,
            textColor=self.DARK
        ))
        styles.add(ParagraphStyle(
            name='TotalValue',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=12, alignment=TA_RIGHT,
            textColor=colors.HexColor('#d32f2f')
        ))
        return styles

    # ---------- utilidades ----------
    def _format_currency(self, amount, currency=None):
        if currency:
            sym = currency.symbol or currency.name
            formatted = f"{amount:,.2f}"
            return f"{formatted} {sym}" if getattr(currency, 'position', 'before') == 'after' else f"{sym} {formatted}"
        return f"$ {amount:,.2f}"

    def _qr(self, data:str, size_mm=24):
        w = size_mm * mm
        q = QrCodeWidget(data or '')
        q.barWidth = w
        q.barHeight = w
        q.qrVersion = 1
        d = Drawing(w, w)
        d.add(q)
        return d

    def _company_logo(self, company, max_w=42*mm, max_h=18*mm):
        if company.logo:
            try:
                img = Image(io.BytesIO(base64.b64decode(company.logo)))
                img._restrictSize(max_w, max_h)
                return img
            except Exception as e:
                _logger.warning("Error cargando logo: %s", e)
        return None

    def _doc_type_label(self, move_type):
        return {
            'out_invoice': 'FACTURA DE VENTA',
            'out_refund':  'NOTA CRÉDITO',
            'in_invoice':  'FACTURA DE COMPRA',
            'in_refund':   'NOTA DÉBITO',
        }.get(move_type, 'DOCUMENTO CONTABLE')

    # ---------- secciones ----------
    def _header(self, inv):
        """Encabezado minimalista en 3 columnas (ancho total 170 mm)."""
        S = self._get_styles()
        company = inv.company_id
        logo = self._company_logo(company)

        # Col 1: Logo + nombre
        col1 = []
        if logo:
            col1.append(logo)
            col1.append(Spacer(1, 2*mm))
        col1.append(Paragraph(company.name or '', S['CompanyName']))

        # Col 2: Datos empresa (texto sobrio)
        cinfo = []
        cinfo.append(Paragraph(f"<b>NIT:</b> {company.vat or ''}", S['NormalText']))
        if company.street:
            cinfo.append(Paragraph(company.street, S['SmallText']))
        if company.city:
            ctry = company.country_id.name if company.country_id else ''
            cinfo.append(Paragraph(f"{company.city}{', ' + ctry if ctry else ''}", S['SmallText']))
        if company.phone:
            cinfo.append(Paragraph(f"Tel: {company.phone}", S['SmallText']))
        if company.email:
            cinfo.append(Paragraph(company.email, S['SmallText']))

        # Col 3: Caja del documento
        doc = []
        doc.append(Paragraph(self._doc_type_label(inv.move_type), S['DocTitle']))
        doc.append(Spacer(1, 2*mm))
        doc.append(Paragraph(f"<b>Número:</b> {inv.name or 'BORRADOR'}", S['SmallText']))
        doc.append(Paragraph(f"<b>Fecha:</b> {inv.invoice_date or ''}", S['SmallText']))
        doc.append(Paragraph(f"<b>Vencimiento:</b> {inv.invoice_date_due or ''}", S['SmallText']))

        data = [[col1, cinfo, doc]]
        # colWidths que suman exactamente 170 mm
        t = Table(data, colWidths=[55*mm, 70*mm, 45*mm])
        t.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('ALIGN',  (0,0), (0,0), 'LEFT'),
            ('ALIGN',  (1,0), (1,0), 'LEFT'),
            ('ALIGN',  (2,0), (2,0), 'RIGHT'),
        ]))

        return [t, Spacer(1, 4*mm), HRFlowable(width="100%", thickness=0.6, color=self.SOFT_LINE), Spacer(1, 3*mm)]

    def _client_block(self, inv):
        """Bloque de cliente en 2 columnas (85+85 = 170 mm)."""
        S = self._get_styles()
        p = inv.partner_id

        rows = [
            [Paragraph(f"<b>Razón social:</b> {p.name or ''}", S['NormalText']),
             Paragraph(f"<b>Teléfono:</b> {p.phone or ''}", S['NormalText'])],
            [Paragraph(f"<b>NIT/CC:</b> {p.vat or ''}", S['NormalText']),
             Paragraph(f"<b>Email:</b> {p.email or ''}", S['NormalText'])],
            [Paragraph(f"<b>Dirección:</b> {p.street or ''}", S['NormalText']),
             Paragraph(f"<b>Plazo Pago:</b> {inv.invoice_payment_term_id.name if inv.invoice_payment_term_id else '30 días'}", S['NormalText'])],
            [Paragraph(f"<b>Ciudad:</b> {p.city or ''}", S['NormalText']),
             Paragraph(f"<b>Referencia:</b> {inv.ref or ''}", S['NormalText'])]
        ]
        tbl = Table(rows, colWidths=[85*mm, 85*mm])
        tbl.setStyle(TableStyle([
            ('GRID', (0,0), (-1,-1), 0.5, self.SOFT_LINE),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('LEFTPADDING', (0,0), (-1,-1), 6),
            ('RIGHTPADDING',(0,0), (-1,-1), 6),
            ('TOPPADDING',  (0,0), (-1,-1), 5),
            ('BOTTOMPADDING',(0,0), (-1,-1), 5),
        ]))
        return [Paragraph("INFORMACIÓN DEL CLIENTE", S['SectionHeader']), Spacer(1, 2*mm), tbl, Spacer(1, 6*mm)]

    def _lines_table_standard(self, inv):
        """Tabla estándar de líneas con encabezado repetible. ColWidths suman 170 mm."""
        S = self._get_styles()
        data = [[
            Paragraph("<b>#</b>", S['Label']),
            Paragraph("<b>Descripción</b>", S['Label']),
            Paragraph("<b>Cant.</b>", S['Label']),
            Paragraph("<b>Precio Unit.</b>", S['Label']),
            Paragraph("<b>Impuestos</b>", S['Label']),
            Paragraph("<b>Subtotal</b>", S['Label'])
        ]]

        i = 1
        for line in inv.invoice_line_ids:
            # En account.move.line, las líneas "reales" NO tienen display_type
            if getattr(line, 'display_type', False):
                continue

            taxes = ', '.join(f"{t.amount:g}%" for t in getattr(line, 'tax_ids', []) or []) or '-'
            data.append([
                Paragraph(str(i), S['NormalText']),
                Paragraph(line.name or '', S['NormalText']),
                Paragraph(f"{line.quantity:.2f}", S['NormalText']),
                Paragraph(self._format_currency(line.price_unit, inv.currency_id), S['NormalText']),
                Paragraph(taxes, S['SmallText']),
                Paragraph(self._format_currency(line.price_subtotal, inv.currency_id), S['NormalText'])
            ])
            i += 1

        colw = [10*mm, 72*mm, 16*mm, 28*mm, 20*mm, 24*mm]  # = 170 mm
        tbl = Table(data, colWidths=colw, repeatRows=1)
        tbl.setStyle(TableStyle([
            # header
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#34495e')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('ALIGN', (0,0), (-1,0), 'CENTER'),
            ('BOTTOMPADDING',(0,0), (-1,0), 6),
            ('TOPPADDING',   (0,0), (-1,0), 6),

            # body
            ('FONTNAME', (0,1), (-1,-1), 'Helvetica'),
            ('FONTSIZE', (0,1), (-1,-1), 8.5),
            ('ALIGN', (0,1), (0,-1), 'CENTER'),
            ('ALIGN', (2,1), (2,-1), 'CENTER'),
            ('ALIGN', (3,1), (5,-1), 'RIGHT'),

            # lines & zebra
            ('LINEBELOW', (0,0), (-1,0), 1.2, self.PRIMARY),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, self.LIGHT_BG]),

            # paddings
            ('LEFTPADDING', (0,1), (-1,-1), 5),
            ('RIGHTPADDING',(0,1), (-1,-1), 5),
            ('TOPPADDING',  (0,1), (-1,-1), 4),
            ('BOTTOMPADDING',(0,1), (-1,-1), 4),
        ]))
        return [Paragraph("DETALLE DE LA FACTURA", S['SectionHeader']), Spacer(1, 2*mm), tbl, Spacer(1, 4*mm)]

    def _lines_table_health(self, inv):
        """Versión agrupada por paciente (sector salud). Incluye repeatRows y colWidths correctas."""
        S = self._get_styles()
        out = [Paragraph("DETALLE DE LA FACTURA", S['SectionHeader']), Spacer(1, 2*mm)]

        # Agrupar por documento de paciente
        groups = {}
        for line in inv.invoice_line_ids:
            if getattr(line, 'display_type', False):
                continue
            doc = getattr(line, 'patient_document', None)
            if not doc:
                continue
            groups.setdefault(doc, []).append(line)

        idx = 1
        for doc, lines in groups.items():
            first = lines[0]
            info = f"<b>Paciente:</b> {getattr(first, 'patient_name', '')} &nbsp;&nbsp; <b>Documento:</b> {doc}"
            out += [Paragraph(info, S['Label']), Spacer(1, 1.5*mm)]

            data = [[Paragraph("<b>#</b>", S['SmallText']),
                     Paragraph("<b>CUPS</b>", S['SmallText']),
                     Paragraph("<b>Descripción</b>", S['SmallText']),
                     Paragraph("<b>Cant.</b>", S['SmallText']),
                     Paragraph("<b>Valor Unit.</b>", S['SmallText']),
                     Paragraph("<b>Total</b>", S['SmallText'])]]

            subtotal = 0.0
            for l in lines:
                cups = getattr(getattr(l, 'product_id', None), 'default_code', '') or ''
                data.append([
                    str(idx),
                    cups,
                    Paragraph(l.name or '', S['SmallText']),
                    f"{l.quantity:.0f}",
                    self._format_currency(l.price_unit, inv.currency_id),
                    self._format_currency(l.price_subtotal, inv.currency_id)
                ])
                subtotal += l.price_subtotal
                idx += 1

            colw = [10*mm, 22*mm, 78*mm, 12*mm, 24*mm, 24*mm]  # = 170 mm
            tbl = Table(data, colWidths=colw, repeatRows=1)
            tbl.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#17a2b8')),
                ('TEXTCOLOR', (0,0), (-1,0), colors.white),
                ('ALIGN', (0,0), (-1,0), 'CENTER'),
                ('FONTNAME', (0,0), (-1,-1), 'Helvetica'),
                ('FONTSIZE', (0,0), (-1,-1), 8),
                ('ALIGN', (0,1), (0,-1), 'CENTER'),
                ('ALIGN', (3,1), (3,-1), 'CENTER'),
                ('ALIGN', (4,1), (5,-1), 'RIGHT'),
                ('LINEBELOW', (0,0), (-1,0), 1.0, colors.HexColor('#148ea1')),
                ('TOPPADDING', (0,0), (-1,-1), 3),
                ('BOTTOMPADDING', (0,0), (-1,-1), 3),
            ]))

            out += [tbl, Spacer(1, 1.5*mm),
                    Paragraph(f"<b>Subtotal Paciente:</b> {self._format_currency(subtotal, inv.currency_id)}", S['TotalLabel']),
                    Spacer(1, 4*mm)]
        return out

    def _fiscal_block_cufe(self, inv):
        """Bloque fiscal minimalista: CUFE/QR debajo del detalle (como pediste)."""
        S = self._get_styles()
        cufe = getattr(inv, 'cufe', None)  # CUFE/CADE/ CUDE según caso
        label = "CUFE" if inv.move_type == 'out_invoice' else "CUDE"

        left = []
        # Observaciones (si existen)
        if inv.narration:
            left.append(Paragraph("<b>Observaciones:</b>", S['Label']))
            left.append(Spacer(1, 1.2*mm))
            left.append(Paragraph(inv.narration, S['SmallText']))
            left.append(Spacer(1, 2*mm))

        # CUFE texto
        if cufe:
            left.append(Paragraph(f"<b>{label}:</b> {cufe}", S['SmallText']))

        # QR (usa CUFE si existe; si no, cadena simple)
        qr_data = cufe or f"Factura:{inv.name}|NIT:{inv.company_id.vat}|Total:{inv.amount_total}"
        qr = self._qr(qr_data, size_mm=24)

        data = [[left, qr]]
        tbl = Table(data, colWidths=[140*mm, 30*mm])  # = 170 mm
        tbl.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('BOX', (0,0), (-1,-1), 0.6, self.SOFT_LINE),
            ('BACKGROUND', (0,0), (-1,-1), colors.whitesmoke),
            ('LEFTPADDING', (0,0), (-1,-1), 6),
            ('RIGHTPADDING',(0,0), (-1,-1), 6),
            ('TOPPADDING',  (0,0), (-1,-1), 5),
            ('BOTTOMPADDING',(0,0), (-1,-1), 5),
        ]))
        # KeepTogether evita que CUFE quede partido entre páginas
        return [KeepTogether([tbl]), Spacer(1, 6*mm)]

    def _totals_and_sign(self, inv):
        """Totales alineados a la derecha + firmas. Bloques compactos."""
        S = self._get_styles()

        # ---- Totales (en columna derecha de 80 mm) ----
        totals = []
        totals.append([Paragraph("Subtotal", S['NormalText']),
                       Paragraph(self._format_currency(inv.amount_untaxed, inv.currency_id), S['NormalText'])])

        # Impuestos por grupo
        if hasattr(inv, 'amount_by_group'):
            for name, amount, base, _dummy1, _dummy2 in inv.amount_by_group:
                totals.append([Paragraph(f"{name} sobre {self._format_currency(base, inv.currency_id)}", S['SmallText']),
                               Paragraph(self._format_currency(amount, inv.currency_id), S['SmallText'])])

        totals.append([HRFlowable(width="100%", thickness=0.8, color=colors.HexColor('#34495e')), ""])
        totals.append([Paragraph("<b>TOTAL A PAGAR:</b>", S['TotalLabel']),
                       Paragraph(self._format_currency(inv.amount_total, inv.currency_id), S['TotalValue'])])

        totals_tbl = Table(totals, colWidths=[50*mm, 30*mm])  # = 80 mm
        totals_tbl.setStyle(TableStyle([
            ('ALIGN', (0,0), (0,-1), 'RIGHT'),
            ('ALIGN', (1,0), (1,-1), 'RIGHT'),
            ('SPAN', (0, -2), (1, -2)),
            ('TOPPADDING', (0,-1), (-1,-1), 6),
            ('BOTTOMPADDING', (0,-1), (-1,-1), 6),
            ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor('#fff3e0')),
        ]))

        # Valor en letras (si disponible)
        letters = []
        if inv.currency_id and hasattr(inv.currency_id, 'amount_to_text'):
            try:
                letters.append(Spacer(1, 3*mm))
                letters.append(Paragraph(f"<b>Son:</b> {inv.currency_id.amount_to_text(inv.amount_total)}", S['SmallText']))
            except Exception:
                pass

        # Layout 2 columnas: izquierda vacía / derecha totales (90 + 80 = 170 mm)
        main = Table([[ "", KeepTogether([totals_tbl] + letters) ]], colWidths=[90*mm, 80*mm])
        main.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP')]))

        # Firmas
        sign = Table([['_'*40, '_'*40],
                      ['Firma y Sello Emisor', 'Firma y Sello Receptor']], colWidths=[85*mm, 85*mm])
        sign.setStyle(TableStyle([
            ('ALIGN', (0,0), (-1,0), 'CENTER'),
            ('ALIGN', (0,1), (-1,1), 'CENTER'),
            ('FONTNAME', (0,1), (-1,1), 'Helvetica'),
            ('FONTSIZE', (0,1), (-1,1), 8),
            ('TOPPADDING', (0,1), (-1,1), 10),
        ]))

        return [main, Spacer(1, 8*mm), KeepTogether([sign])]

    # ---------- orquestación ----------
    @api.model
    def generate_pdf(self, invoice):
        """Construye el PDF (A4, márgenes 20 mm). Usa BaseDocTemplate para mayor control en multipágina."""
        buf = io.BytesIO()

        # Marcos (un único frame de contenido)
        left = 20*mm; right = 20*mm; top = 25*mm; bottom = 25*mm
        frame = Frame(left, bottom, A4[0] - left - right, A4[1] - top - bottom, id='normal')

        doc = BaseDocTemplate(
            buf, pagesize=A4,
            leftMargin=left, rightMargin=right, topMargin=top, bottomMargin=bottom,
            title=f"Factura {invoice.name or 'BORRADOR'}", author=invoice.company_id.name
        )
        template = PageTemplate(id='main', frames=[frame])
        doc.addPageTemplates([template])

        elems = []
        # Header
        elems += self._header(invoice)
        # Cliente
        elems += self._client_block(invoice)
        # Detalle
        if getattr(invoice, 'is_health_sector', False):
            elems += self._lines_table_health(invoice)
        else:
            elems += self._lines_table_standard(invoice)
        # CUFE/QR debajo del detalle
        elems += self._fiscal_block_cufe(invoice)
        # Totales + firmas
        elems += self._totals_and_sign(invoice)

        # Construcción con canvas que inyecta meta en todas las páginas
        doc.build(
            elems,
            canvasmaker=lambda *args, **kw: NumberedCanvas(
                *args,
                company_data={'name': invoice.company_id.name, 'vat': invoice.company_id.vat},
                page_meta={'right_label': f"{self._doc_type_label(invoice.move_type)} · {invoice.name or 'BORRADOR'}"},
                **kw
            )
        )
        pdf = buf.getvalue()
        buf.close()
        return pdf

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['account.move'].browse(docids)
        return {'doc_ids': docids, 'doc_model': 'account.move', 'docs': docs, 'data': data}


    # ===================== Acción en account.move =====================
    def _header(self, inv):
        """Empresa al centro y, debajo a la derecha, recuadro de documento electrónico."""
        S = self._get_styles()
        company = inv.company_id
        logo = self._company_logo(company, max_w=48*mm, max_h=20*mm)

        # Bloque centrado: logo + datos empresa
        center = []
        if logo:
            center.append(logo)
            center.append(Spacer(1, 2*mm))
        center.append(Paragraph(company.name or '', S['CompanyName']))
        nit = f"NIT: {company.vat}" if company.vat else ""
        line1 = " · ".join([x for x in [nit, company.email or "", company.phone or ""] if x])
        line2 = " · ".join([x for x in [company.street or "", company.city or "", 
                                        company.country_id and company.country_id.name or ""] if x])
        if line1:
            center.append(Paragraph(line1, S['SmallText']))
        if line2:
            center.append(Paragraph(line2, S['SmallText']))

        # Tabla 1 columna (170mm) centrada
        t_center = Table([[center]], colWidths=[170*mm])
        t_center.setStyle(TableStyle([
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ]))

        # Recuadro a la derecha con info electrónica (doc title + número + tipo)
        doc_title = self._doc_type_label(inv.move_type)
        right_box = []
        right_box.append(Paragraph(doc_title, S['DocTitle']))
        right_box.append(Spacer(1, 1.2*mm))
        right_box.append(Paragraph(f"<b>Número:</b> {inv.name or 'BORRADOR'}", S['SmallText']))
        # etiqueta explícita de carácter electrónico
        right_box.append(Paragraph("<b>Documento:</b> Electrónico", S['SmallText']))

        t_right = Table([[right_box]], colWidths=[60*mm])
        t_right.setStyle(TableStyle([
            ('BOX', (0,0), (-1,-1), 0.6, self.SOFT_LINE),
            ('BACKGROUND', (0,0), (-1,-1), colors.whitesmoke),
            ('LEFTPADDING', (0,0), (-1,-1), 6),
            ('RIGHTPADDING',(0,0), (-1,-1), 6),
            ('TOPPADDING',  (0,0), (-1,-1), 5),
            ('BOTTOMPADDING',(0,0), (-1,-1), 5),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ]))

        # Fila: vacío + recuadro derecha (110 + 60 = 170mm)
        t_row = Table([["", t_right]], colWidths=[110*mm, 60*mm])
        t_row.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP')]))

        return [
            t_center, Spacer(1, 3*mm),
            t_row, Spacer(1, 4*mm),
            HRFlowable(width="100%", thickness=0.6, color=self.SOFT_LINE),
            Spacer(1, 3*mm)
        ]


    def _client_block(self, inv):
        """Dos columnas: izquierda cliente, derecha datos de la factura."""
        S = self._get_styles()
        p = inv.partner_id

        left = []
        left.append(Paragraph("INFORMACIÓN DEL CLIENTE", S['SectionHeader']))
        left.append(Spacer(1, 1.2*mm))
        left_rows = [
            [Paragraph(f"<b>Razón social:</b> {p.name or ''}", S['NormalText'])],
            [Paragraph(f"<b>NIT/CC:</b> {p.vat or ''}", S['NormalText'])],
            [Paragraph(f"<b>Dirección:</b> {p.street or ''}", S['NormalText'])],
            [Paragraph(f"<b>Ciudad:</b> {p.city or ''}", S['NormalText'])],
            [Paragraph(f"<b>Teléfono:</b> {p.phone or ''}", S['NormalText'])],
            [Paragraph(f"<b>Email:</b> {p.email or ''}", S['NormalText'])],
        ]
        tbl_left = Table(left_rows, colWidths=[80*mm])
        tbl_left.setStyle(TableStyle([
            ('GRID', (0,0), (-1,-1), 0.5, self.SOFT_LINE),
            ('LEFTPADDING', (0,0), (-1,-1), 6),
            ('RIGHTPADDING',(0,0), (-1,-1), 6),
            ('TOPPADDING',  (0,0), (-1,-1), 5),
            ('BOTTOMPADDING',(0,0), (-1,-1), 5),
        ]))
        left.append(tbl_left)

        right = []
        right.append(Paragraph("DATOS DE LA FACTURA", S['SectionHeader']))
        right.append(Spacer(1, 1.2*mm))
        right_rows = [
            [Paragraph(f"<b>Fecha:</b> {inv.invoice_date or ''}", S['NormalText'])],
            [Paragraph(f"<b>Vencimiento:</b> {inv.invoice_date_due or ''}", S['NormalText'])],
            [Paragraph(f"<b>Término de pago:</b> {inv.invoice_payment_term_id.name if inv.invoice_payment_term_id else '30 días'}", S['NormalText'])],
            [Paragraph(f"<b>Referencia:</b> {inv.ref or ''}", S['NormalText'])],
        ]
        # Añadibles frecuentes
        if getattr(inv, 'invoice_user_id', False):
            right_rows.append([Paragraph(f"<b>Vendedor:</b> {inv.invoice_user_id.name}", S['NormalText'])])

        tbl_right = Table(right_rows, colWidths=[80*mm])
        tbl_right.setStyle(TableStyle([
            ('GRID', (0,0), (-1,-1), 0.5, self.SOFT_LINE),
            ('LEFTPADDING', (0,0), (-1,-1), 6),
            ('RIGHTPADDING',(0,0), (-1,-1), 6),
            ('TOPPADDING',  (0,0), (-1,-1), 5),
            ('BOTTOMPADDING',(0,0), (-1,-1), 5),
        ]))
        right.append(tbl_right)

        # Dos columnas (85 + 85 = 170mm)
        block = Table([[left, right]], colWidths=[85*mm, 85*mm])
        block.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP')]))
        return [block, Spacer(1, 6*mm)]


    def _lines_table_standard(self, inv):
        """Detalle estándar. Se aceptan líneas con display_type == 'product' o sin display_type (real)."""
        S = self._get_styles()
        data = [[
            Paragraph("<b>#</b>", S['Label']),
            Paragraph("<b>Descripción</b>", S['Label']),
            Paragraph("<b>Cant.</b>", S['Label']),
            Paragraph("<b>Precio Unit.</b>", S['Label']),
            Paragraph("<b>Impuestos</b>", S['Label']),
            Paragraph("<b>Subtotal</b>", S['Label'])
        ]]

        i = 1
        for line in inv.invoice_line_ids:
            dt = getattr(line, 'display_type', None)
            # Mantener compat con tu modelo: 'product' o (None/False = línea real)
            if dt not in (None, False, 'product'):
                continue

            taxes = ', '.join(f"{t.amount:g}%" for t in (line.tax_ids or [])) or '-'
            data.append([
                Paragraph(str(i), S['NormalText']),
                Paragraph(line.name or '', S['NormalText']),
                Paragraph(f"{line.quantity:.2f}", S['NormalText']),
                Paragraph(self._format_currency(line.price_unit, inv.currency_id), S['NormalText']),
                Paragraph(taxes, S['SmallText']),
                Paragraph(self._format_currency(line.price_subtotal, inv.currency_id), S['NormalText'])
            ])
            i += 1

        colw = [10*mm, 70*mm, 16*mm, 30*mm, 20*mm, 24*mm]  # = 170mm
        tbl = Table(data, colWidths=colw, repeatRows=1)
        tbl.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#34495e')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('ALIGN', (0,0), (-1,0), 'CENTER'),
            ('BOTTOMPADDING',(0,0), (-1,0), 6),
            ('TOPPADDING',   (0,0), (-1,0), 6),
            ('FONTNAME', (0,1), (-1,-1), 'Helvetica'),
            ('FONTSIZE', (0,1), (-1,-1), 8.5),
            ('ALIGN', (0,1), (0,-1), 'CENTER'),
            ('ALIGN', (2,1), (2,-1), 'CENTER'),
            ('ALIGN', (3,1), (5,-1), 'RIGHT'),
            ('LINEBELOW', (0,0), (-1,0), 1.2, self.PRIMARY),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, self.LIGHT_BG]),
            ('LEFTPADDING', (0,1), (-1,-1), 5),
            ('RIGHTPADDING',(0,1), (-1,-1), 5),
            ('TOPPADDING',  (0,1), (-1,-1), 4),
            ('BOTTOMPADDING',(0,1), (-1,-1), 4),
        ]))
        return [Paragraph("DETALLE DE LA FACTURA", S['SectionHeader']), Spacer(1, 2*mm), tbl, Spacer(1, 4*mm)]


    def _lines_table_health(self, inv):
        """Detalle Salud: agrupado por paciente + columna 'Tipo Servicio'."""
        S = self._get_styles()
        out = [Paragraph("DETALLE DE LA FACTURA (Sector Salud)", S['SectionHeader']), Spacer(1, 2*mm)]

        # Agrupar por documento de paciente
        groups = {}
        for line in inv.invoice_line_ids:
            dt = getattr(line, 'display_type', None)
            if dt not in (None, False, 'product'):
                continue
            doc = getattr(line, 'patient_document', None)
            if not doc:
                # si no hay doc, lo metemos en grupo "Otros"
                doc = "_OTROS_"
            groups.setdefault(doc, []).append(line)

        idx = 1
        for doc, lines in groups.items():
            first = lines[0]
            if doc != "_OTROS_":
                info = f"<b>Paciente:</b> {getattr(first, 'patient_name', '')} &nbsp;&nbsp; <b>Documento:</b> {doc}"
                out += [Paragraph(info, S['Label']), Spacer(1, 1.2*mm)]

            data = [[
                Paragraph("<b>#</b>", S['SmallText']),
                Paragraph("<b>Tipo Servicio</b>", S['SmallText']),
                Paragraph("<b>CUPS</b>", S['SmallText']),
                Paragraph("<b>Descripción</b>", S['SmallText']),
                Paragraph("<b>Cant.</b>", S['SmallText']),
                Paragraph("<b>Vlr Unit.</b>", S['SmallText']),
                Paragraph("<b>Total</b>", S['SmallText'])
            ]]

            subtotal = 0.0
            for l in lines:
                cups = getattr(getattr(l, 'product_id', None), 'default_code', '') or ''
                # detectar tipo de servicio en la línea o en el producto
                svc = (
                    getattr(l, 'service_type', None) or
                    getattr(l, 'x_service_type', None) or
                    getattr(getattr(l, 'product_id', None), 'service_type', None) or
                    getattr(getattr(l, 'product_id', None), 'x_service_type', None) or
                    ''
                )
                data.append([
                    str(idx),
                    str(svc),
                    cups,
                    Paragraph(l.name or '', S['SmallText']),
                    f"{l.quantity:.0f}",
                    self._format_currency(l.price_unit, inv.currency_id),
                    self._format_currency(l.price_subtotal, inv.currency_id)
                ])
                subtotal += l.price_subtotal
                idx += 1

            colw = [10*mm, 28*mm, 20*mm, 68*mm, 12*mm, 16*mm, 16*mm]  # = 170mm
            tbl = Table(data, colWidths=colw, repeatRows=1)
            tbl.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#17a2b8')),
                ('TEXTCOLOR', (0,0), (-1,0), colors.white),
                ('ALIGN', (0,0), (-1,0), 'CENTER'),
                ('FONTNAME', (0,0), (-1,-1), 'Helvetica'),
                ('FONTSIZE', (0,0), (-1,-1), 8),
                ('ALIGN', (0,1), (0,-1), 'CENTER'),
                ('ALIGN', (4,1), (4,-1), 'CENTER'),
                ('ALIGN', (5,1), (6,-1), 'RIGHT'),
                ('LINEBELOW', (0,0), (-1,0), 1.0, colors.HexColor('#148ea1')),
                ('TOPPADDING', (0,0), (-1,-1), 3),
                ('BOTTOMPADDING', (0,0), (-1,-1), 3),
            ]))

            out += [tbl, Spacer(1, 2*mm)]
            if doc != "_OTROS_":
                out += [
                    Paragraph(f"<b>Subtotal Paciente:</b> {self._format_currency(subtotal, inv.currency_id)}", S['TotalLabel']),
                    Spacer(1, 4*mm)
                ]
        return out
class AccountMove(models.Model):
    _inherit = 'account.move'

    def action_print_invoice_reportlab(self):
        self.ensure_one()
        report = self.env['report.invoice_reportlab.report_invoice']
        pdf = report.generate_pdf(self)

        att = self.env['ir.attachment'].create({
            'name': f'{self.name or "Factura"}.pdf',
            'type': 'binary',
            'datas': base64.b64encode(pdf),
            'res_model': 'account.move',
            'res_id': self.id,
            'mimetype': 'application/pdf',
        })
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{att.id}?download=true',
            'target': 'self',
        }

    rip_id = fields.Many2one("hospital.rips", string="Cuenta Radicada", help="Cuenta radicada RIPS", ondelete="restrict", index=True)
    ripsjson_id = fields.Many2one("rips.export", string="Cuenta Radicada", help="Cuenta radicada RIPS")
    authorization_number = fields.Char(string="Numero de autorizacion")
    amount_vat = fields.Float(string="IVA", compute="_invoice_values", store=True)
    @api.depends('invoice_line_ids')
    def _invoice_values(self):
        for rops in self:
            rops.amount_vat = sum(i.vat_amount for i in rops.invoice_line_ids)

    def generate_pdf_zip(self):
        today = datetime.now().strftime('%Y%m%d')
        attachment_name = f'PDFs_{today}.zip'
        
        zip_buffer = BytesIO()
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for move in self:
                try:
                    company_vat = move.company_id.partner_id.vat_co 
                    pdf_content = self.env['ir.actions.report'].sudo()._render_qweb_pdf(
                        "account.account_invoices", move.id)[0]
                    
                    pdf_filename = f"FVS_{company_vat}_{move.name}.pdf"
                    zip_file.writestr(pdf_filename, pdf_content)
                    
                except Exception as e:
                    _logger.error(f"Error generando PDF para factura {move.name}: {str(e)}")
                    continue
        
        zip_data = base64.b64encode(zip_buffer.getvalue())
        attachment = self.env['ir.attachment'].create({
            'name': attachment_name,
            'type': 'binary',
            'datas': zip_data,
            'res_model': self._name if len(self) == 1 else False,
            'res_id': self.id if len(self) == 1 else False,
            'mimetype': 'application/zip'
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }
    def _validate_document_type_by_age_and_nationality(self, line):
        """
        Validar tipo de documento según edad y nacionalidad según normativa RIPS
        """
        errors = []
        
        if not line.patient_birth_date or not line.patient_doc_type:
            return errors
        
        # Calcular edad
        today = date.today()
        age = today.year - line.patient_birth_date.year - ((today.month, today.day) < (line.patient_birth_date.month, line.patient_birth_date.day))
        
        # Determinar si es extranjero
        is_foreign = line.patient_nationality and line.patient_nationality != "170"  # 170 es código de Colombia
        is_venezuelan_migrant = line.patient_nationality == "862"  # Venezuela
        
        doc_type = line.patient_doc_type
        
        # Validaciones según normativa RIPS
        if age >= 18:
            if not is_foreign and doc_type not in ['CC', 'AS', 'SI']:
                errors.append({
                    'tipo': 'Tipo Documento',
                    'descripcion': f'Para personas >= 18 años colombianas debe ser CC, AS o SI. Edad: {age} años',
                    'campo': 'patient_doc_type',
                    'valor_actual': doc_type,
                    'valor_sugerido': 'CC',
                    'severidad': 'Alta'
                })
            
            # Período de tolerancia para cambio de TI a CC (hasta 19 años menos 1 día)
            if age == 18 and doc_type == 'TI':
                # Permitir TI hasta los 19 años (período de tolerancia)
                pass
            elif age >= 19 and doc_type in ['RC', 'TI', 'MS', 'CN']:
                errors.append({
                    'tipo': 'Tipo Documento',
                    'descripcion': f'Para personas >= 19 años no puede ser RC, TI, MS, CN. Edad: {age} años',
                    'campo': 'patient_doc_type',
                    'valor_actual': doc_type,
                    'valor_sugerido': 'CC' if not is_foreign else 'CE',
                    'severidad': 'Alta'
                })
        
        elif 7 <= age <= 17:
            if not is_foreign and doc_type not in ['TI', 'RC']:
                # Período de tolerancia para menores que no han tramitado TI
                if age == 7 and doc_type == 'RC':
                    # Permitir RC hasta los 8 años (período de tolerancia)
                    pass
                else:
                    errors.append({
                        'tipo': 'Tipo Documento',
                        'descripcion': f'Para menores entre 7-17 años debe ser TI. Edad: {age} años',
                        'campo': 'patient_doc_type',
                        'valor_actual': doc_type,
                        'valor_sugerido': 'TI',
                        'severidad': 'Media'
                    })
        
        elif 4 <= age <= 6:
            if doc_type not in ['RC', 'TI']:
                errors.append({
                    'tipo': 'Tipo Documento',
                    'descripcion': f'Para menores entre 4-6 años debe ser RC o TI. Edad: {age} años',
                    'campo': 'patient_doc_type',
                    'valor_actual': doc_type,
                    'valor_sugerido': 'RC',
                    'severidad': 'Media'
                })
        
        elif age <= 3:
            if doc_type not in ['RC', 'CN']:
                errors.append({
                    'tipo': 'Tipo Documento',
                    'descripcion': f'Para menores <= 3 años debe ser RC o CN. Edad: {age} años',
                    'campo': 'patient_doc_type',
                    'valor_actual': doc_type,
                    'valor_sugerido': 'RC',
                    'severidad': 'Media'
                })
        
        # Validaciones para extranjeros
        if is_foreign:
            valid_foreign_docs = ['CE', 'CD', 'PA', 'SC', 'DE']
            if is_venezuelan_migrant:
                valid_foreign_docs.append('PE')
            
            if age >= 7 and doc_type not in valid_foreign_docs:
                errors.append({
                    'tipo': 'Tipo Documento',
                    'descripcion': f'Para extranjeros debe ser: {", ".join(valid_foreign_docs)}',
                    'campo': 'patient_doc_type',
                    'valor_actual': doc_type,
                    'valor_sugerido': 'CE' if not is_venezuelan_migrant else 'PE',
                    'severidad': 'Alta'
                })
        
        # Validación específica para AS
        if doc_type == 'AS' and age < 18:
            errors.append({
                'tipo': 'Tipo Documento',
                'descripcion': 'Tipo AS solo para mayores de 18 años',
                'campo': 'patient_doc_type',
                'valor_actual': doc_type,
                'valor_sugerido': 'MS' if age < 18 else 'AS',
                'severidad': 'Alta'
            })
        
        return errors

    def _validate_document_number_format(self, line):
        """
        Validar formato y longitud del número de documento según tipo
        """
        errors = []
        
        if not line.patient_doc_type or not line.patient_document:
            return errors
        
        doc_type = line.patient_doc_type
        doc_number = str(line.patient_document).strip()
        
        # Longitudes máximas según normativa RIPS
        max_lengths = {
            'CC': 10, 'CE': 6, 'CD': 16, 'PA': 16, 'SC': 16, 'PE': 15,
            'RC': 11, 'TI': 11, 'CN': 20, 'AS': 10, 'MS': 12,
            'DE': 20, 'PT': 20, 'SI': 20
        }
        
        min_lengths = {
            'CC': 4, 'CE': 4, 'TI': 4, 'RC': 4, 'CN': 9,
            'AS': 4, 'MS': 4
        }
        
        # Validar longitud máxima
        if doc_type in max_lengths:
            max_len = max_lengths[doc_type]
            if len(doc_number) > max_len:
                errors.append({
                    'tipo': 'Número Documento',
                    'descripcion': f'Número de documento {doc_type} excede longitud máxima de {max_len} caracteres',
                    'campo': 'patient_document',
                    'valor_actual': f'{doc_number} ({len(doc_number)} chars)',
                    'valor_sugerido': f'Máximo {max_len} caracteres',
                    'severidad': 'Alta'
                })
        
        # Validar longitud mínima
        if doc_type in min_lengths:
            min_len = min_lengths[doc_type]
            if len(doc_number) < min_len:
                errors.append({
                    'tipo': 'Número Documento',
                    'descripcion': f'Número de documento {doc_type} requiere mínimo {min_len} caracteres',
                    'campo': 'patient_document',
                    'valor_actual': f'{doc_number} ({len(doc_number)} chars)',
                    'valor_sugerido': f'Mínimo {min_len} caracteres',
                    'severidad': 'Alta'
                })
        
        # Validar formato numérico para CC y TI
        if doc_type in ['CC', 'TI'] and not doc_number.isdigit():
            errors.append({
                'tipo': 'Formato Documento',
                'descripcion': f'Número de documento {doc_type} debe contener solo números',
                'campo': 'patient_document',
                'valor_actual': doc_number,
                'valor_sugerido': 'Solo números',
                'severidad': 'Alta'
            })
        
        return errors

    def _validate_user_type_consistency(self, line):
        """
        Validar consistencia del tipo de usuario con cobertura
        """
        errors = []
        
        if not line.patient_user_type:
            return errors
        
        # Mapeo según normativa RIPS - Tabla de consistencia
        valid_user_types = ['01', '02', '03', '04', '05', '06', '07', '08', '09', '10', '11', '12', '13']
        
        if line.patient_user_type not in valid_user_types:
            errors.append({
                'tipo': 'Tipo Usuario',
                'descripcion': 'Tipo de usuario inválido según normativa RIPS',
                'campo': 'patient_user_type',
                'valor_actual': line.patient_user_type,
                'valor_sugerido': '01 (Contributivo cotizante)',
                'severidad': 'Alta'
            })
        
        # Validaciones específicas según tipo de usuario
        if line.patient_user_type == '04':  # Subsidiado
            # Los subsidiados no pueden tener cuota moderadora según Decreto 1652 de 2022
            if line.valor_pago_moderador and line.tipo_pago_moderador == '01':  # Cuota moderadora
                errors.append({
                    'tipo': 'Pago Moderador',
                    'descripcion': 'Usuarios subsidiados no pueden tener cuota moderadora (Decreto 1652/2022)',
                    'campo': 'valor_pago_moderador',
                    'valor_actual': str(line.valor_pago_moderador),
                    'valor_sugerido': '0',
                    'severidad': 'Alta'
                })
        
        return errors

    def _validate_diagnosis_codes(self, line):
        """
        Validar códigos de diagnóstico CIE-10
        """
        errors = []
        
        # Validar diagnóstico principal
        if line.diagnostico_principal:
            if not self._is_valid_cie10_code(line.diagnostico_principal):
                errors.append({
                    'tipo': 'Diagnóstico',
                    'descripcion': 'Código de diagnóstico principal no tiene formato CIE-10 válido',
                    'campo': 'diagnostico_principal',
                    'valor_actual': line.diagnostico_principal,
                    'valor_sugerido': 'Formato: A00.0 (letra + 2 dígitos + punto + 1-2 dígitos)',
                    'severidad': 'Alta'
                })
        
        # Validar diagnósticos relacionados
        related_diagnoses = [
            ('diagnostico_relacionado', line.diagnostico_relacionado),
            ('diagnostico_relacionado1', line.diagnostico_relacionado1),
            ('diagnostico_relacionado2', line.diagnostico_relacionado2),
            ('diagnostico_relacionado3', line.diagnostico_relacionado3),
        ]
        
        for field_name, diagnosis_code in related_diagnoses:
            if diagnosis_code and not self._is_valid_cie10_code(diagnosis_code):
                errors.append({
                    'tipo': 'Diagnóstico Relacionado',
                    'descripcion': f'Código de {field_name} no tiene formato CIE-10 válido',
                    'campo': field_name,
                    'valor_actual': diagnosis_code,
                    'valor_sugerido': 'Formato: A00.0',
                    'severidad': 'Media'
                })
        
        return errors

    def _is_valid_cie10_code(self, code):
        """
        Validar formato de código CIE-10
        """
        if not code:
            return True

        pattern = r'^[A-Z]\d{2}(\.\d{1,2})?$'
        return bool(re.match(pattern, code.upper()))

    def _validate_cups_codes(self, line):
        """
        Validar códigos CUPS para procedimientos y consultas
        """
        errors = []
        
        if not line.product_id or not line.product_id.rips_service_type:
            return errors
        
        service_type = line.product_id.rips_service_type
        product_code = line.product_id.default_code or ''
        
        if service_type in ['consulta', 'procedimiento']:
            if not self._is_valid_cups_code(product_code, service_type):
                errors.append({
                    'tipo': 'Código CUPS',
                    'descripcion': f'Código CUPS inválido para {service_type}',
                    'campo': 'product_id.default_code',
                    'valor_actual': product_code,
                    'valor_sugerido': '890201 (consulta) o código de 6 dígitos válido',
                    'severidad': 'Alta'
                })
        
        return errors

    def _is_valid_cups_code(self, code, service_type):
        """
        Validar formato de código CUPS
        """
        if not code:
            return False
        
        if not re.match(r'^\d{6}$', code):
            return False
        
        if service_type == 'consulta':
            return code.startswith('89')
        elif service_type == 'procedimiento':
            return True
        
        return True

    def _validate_professional_data(self, line):
        """
        Validar datos del profesional
        """
        errors = []
        
        # Para servicios RIPS se requiere identificación del profesional
        if (line.product_id and line.product_id.rips_service_type and 
            line.product_id.rips_service_type != 'none'):
            
            # Validar que existe información del profesional
            professional_doc_type = getattr(line, 'professional_doc_type', None) or 'CC'
            professional_document = getattr(line, 'professional_document', None) or '1111111111'
            
            if not professional_document or professional_document == '1111111111':
                errors.append({
                    'tipo': 'Datos Profesional',
                    'descripcion': 'Se requiere documento válido del profesional que prestó el servicio',
                    'campo': 'professional_document',
                    'valor_actual': professional_document or '',
                    'valor_sugerido': 'Documento válido del profesional',
                    'severidad': 'Media'
                })
        
        return errors

    def _validate_service_dates(self, line, invoice):
        """
        Validar fechas de servicios estén dentro del período de facturación
        """
        errors = []
        
        if not invoice.date:
            return errors
        
        service_dates = []
        
        if line.fecha_atencion:
            service_dates.append(('fecha_atencion', line.fecha_atencion))
        if line.fecha_procedimiento:
            service_dates.append(('fecha_procedimiento', line.fecha_procedimiento))
        if line.fecha_dispensacion:
            service_dates.append(('fecha_dispensacion', line.fecha_dispensacion))
        if line.fecha_suministro:
            service_dates.append(('fecha_suministro', line.fecha_suministro))
        
        for field_name, service_date in service_dates:
            if service_date:
                if isinstance(service_date, datetime):
                    service_date = service_date.date()
                
                if service_date > fields.Date.today():
                    errors.append({
                        'tipo': 'Fecha Servicio',
                        'descripcion': f'Fecha de {field_name} no puede ser futura',
                        'campo': field_name,
                        'valor_actual': str(service_date),
                        'valor_sugerido': str(fields.Date.today()),
                        'severidad': 'Alta'
                    })
                
                days_diff = (fields.Date.today() - service_date).days
                if days_diff > 730:  # 2 años
                    errors.append({
                        'tipo': 'Fecha Servicio',
                        'descripcion': f'Fecha de {field_name} es muy antigua (>{days_diff} días)',
                        'campo': field_name,
                        'valor_actual': str(service_date),
                        'valor_sugerido': 'Fecha más reciente',
                        'severidad': 'Media'
                    })
        
        return errors

    def _validate_medication_specific_fields(self, line):
        """
        Validar campos específicos de medicamentos
        """
        errors = []
        
        if (line.product_id and line.product_id.rips_service_type == 'medicamento'):
            
            # Validar días de tratamiento
            if not line.dias_tratamiento or line.dias_tratamiento <= 0:
                errors.append({
                    'tipo': 'Medicamento',
                    'descripcion': 'Días de tratamiento debe ser mayor a 0',
                    'campo': 'dias_tratamiento',
                    'valor_actual': str(line.dias_tratamiento or 0),
                    'valor_sugerido': '1',
                    'severidad': 'Alta'
                })
            elif line.dias_tratamiento > 365:
                errors.append({
                    'tipo': 'Medicamento',
                    'descripcion': 'Días de tratamiento excesivo (>365 días)',
                    'campo': 'dias_tratamiento',
                    'valor_actual': str(line.dias_tratamiento),
                    'valor_sugerido': '30',
                    'severidad': 'Media'
                })
            
            if not line.unidad_min_dispensacion or line.unidad_min_dispensacion <= 0:
                errors.append({
                    'tipo': 'Medicamento',
                    'descripcion': 'Unidad mínima de dispensación debe ser mayor a 0',
                    'campo': 'unidad_min_dispensacion',
                    'valor_actual': str(line.unidad_min_dispensacion or 0),
                    'valor_sugerido': '1',
                    'severidad': 'Media'
                })
            
            valid_med_types = ['01', '02', '03']
            if line.tipo_medicamento not in valid_med_types:
                errors.append({
                    'tipo': 'Medicamento',
                    'descripcion': 'Tipo de medicamento inválido',
                    'campo': 'tipo_medicamento',
                    'valor_actual': line.tipo_medicamento or '',
                    'valor_sugerido': '01 (PBS)',
                    'severidad': 'Alta'
                })
            
            if line.tipo_medicamento == '03':
                if not line.concentracion or line.concentracion <= 0:
                    errors.append({
                        'tipo': 'Preparación Magistral',
                        'descripcion': 'Concentración requerida para preparación magistral',
                        'campo': 'concentracion',
                        'valor_actual': str(line.concentracion or 0),
                        'valor_sugerido': 'Valor > 0',
                        'severidad': 'Alta'
                    })
                
                if not line.unidad_medida:
                    errors.append({
                        'tipo': 'Preparación Magistral',
                        'descripcion': 'Unidad de medida requerida para preparación magistral',
                        'campo': 'unidad_medida',
                        'valor_actual': str(line.unidad_medida or ''),
                        'valor_sugerido': 'Código de unidad válido',
                        'severidad': 'Alta'
                    })
        
        return errors

    def _validate_invoice_for_rips(self, invoice):
        """
        Método principal de validación mejorado con validaciones específicas RIPS
        """
        errores = []
        
        if not invoice.company_id.partner_id.vat_co:
            errores.append({
                'tipo': 'Datos Empresa',
                'descripcion': 'NIT de la empresa no configurado',
                'campo': 'company_id.partner_id.vat_co',
                'valor_actual': '',
                'valor_sugerido': 'Configurar NIT en la empresa',
                'linea': 'Factura',
                'severidad': 'Alta'
            })
        
        if not invoice.company_id.partner_id.ref:
            errores.append({
                'tipo': 'Datos Empresa',
                'descripcion': 'Código prestador no configurado',
                'campo': 'company_id.partner_id.ref',
                'valor_actual': '',
                'valor_sugerido': 'Configurar código prestador (12 dígitos)',
                'linea': 'Factura',
                'severidad': 'Alta'
            })
        
        if invoice.company_id.partner_id.ref:
            ref_code = str(invoice.company_id.partner_id.ref).strip()
            if not re.match(r'^\d{12}$', ref_code):
                errores.append({
                    'tipo': 'Código Prestador',
                    'descripcion': 'Código prestador debe tener exactamente 12 dígitos',
                    'campo': 'company_id.partner_id.ref',
                    'valor_actual': ref_code,
                    'valor_sugerido': 'Código de 12 dígitos',
                    'linea': 'Factura',
                    'severidad': 'Alta'
                })
        
        for line_num, line in enumerate(invoice.invoice_line_ids, 1):
            if line.product_id and line.product_id.rips_service_type and line.product_id.rips_service_type != 'none':
                
                validation_methods = [
                    self._validate_document_type_by_age_and_nationality,
                    self._validate_document_number_format,
                    self._validate_user_type_consistency,
                    self._validate_diagnosis_codes,
                    self._validate_cups_codes,
                    self._validate_professional_data,
                    self._validate_medication_specific_fields,
                ]
                
                for validation_method in validation_methods:
                    try:
                        validation_errors = validation_method(line)
                        for error in validation_errors:
                            error['linea'] = f'Línea {line_num}'
                            error['producto'] = line.product_id.name if line.product_id else ''
                            error['paciente'] = f"{line.patient_doc_type or ''} {line.patient_document or ''}"
                            errores.append(error)
                    except Exception as e:
                        _logger.error(f"Error en validación {validation_method.__name__}: {str(e)}")
                
                try:
                    date_errors = self._validate_service_dates(line, invoice)
                    for error in date_errors:
                        error['linea'] = f'Línea {line_num}'
                        error['producto'] = line.product_id.name if line.product_id else ''
                        error['paciente'] = f"{line.patient_doc_type or ''} {line.patient_document or ''}"
                        errores.append(error)
                except Exception as e:
                    _logger.error(f"Error en validación de fechas: {str(e)}")
        
        return errores

    def _validate_string_enhanced(self, value, min_length=None, max_length=None, 
                                 no_leading_zero=False, no_spaces=False, 
                                 default=None, allow_null=False, field_name=""):
        """
        Versión mejorada del método de validación de strings con logging de errores
        """
        try:
            result = self._validate_string(value, min_length, max_length, 
                                         no_leading_zero, no_spaces, default, allow_null)
            return result
        except Exception as e:
            _logger.warning(f"Error validando campo {field_name}: {str(e)}, usando valor por defecto")
            return default if default is not None else ("" if not allow_null else None)

    def _validate_numeric_enhanced(self, value, min_length=None, max_length=None, 
                                  default=0, field_name=""):
        """
        Versión mejorada del método de validación numérica con logging de errores
        """
        try:
            result = self._validate_numeric(value, min_length, max_length, default)
            return result
        except Exception as e:
            _logger.warning(f"Error validando campo numérico {field_name}: {str(e)}, usando valor por defecto")
            return default


    def _validate_modality_and_service_group(self, line):
        """
        Validar modalidad de atención y grupo de servicios
        """
        errors = []
        
        # Validar modalidad de atención
        valid_modalities = ['01', '02', '03', '04', '06', '07', '08', '09']
        modality_names = {
            '01': 'Intramural',
            '02': 'Extramural unidad móvil',
            '03': 'Extramural domiciliaria',
            '04': 'Extramural jornada de salud',
            '06': 'Telemedicina interactiva',
            '07': 'Telemedicina no interactiva',
            '08': 'Telemedicina telexperticia',
            '09': 'Telemedicina telemonitoreo'
        }
        
        if line.modalidad and line.modalidad not in valid_modalities:
            errors.append({
                'tipo': 'Modalidad Atención',
                'descripcion': f'Modalidad de atención inválida: {line.modalidad}',
                'campo': 'modalidad',
                'valor_actual': line.modalidad,
                'valor_sugerido': '01 (Intramural)',
                'severidad': 'Alta'
            })
        
        # Validar grupo de servicios
        valid_groups = ['01', '02', '03', '04', '05']
        group_names = {
            '01': 'Consulta externa',
            '02': 'Apoyo diagnóstico y complementación terapéutica',
            '03': 'Internación',
            '04': 'Quirúrgico',
            '05': 'Atención inmediata'
        }
        
        if line.grupo_servicio and line.grupo_servicio not in valid_groups:
            errors.append({
                'tipo': 'Grupo Servicios',
                'descripcion': f'Grupo de servicios inválido: {line.grupo_servicio}',
                'campo': 'grupo_servicio',
                'valor_actual': line.grupo_servicio,
                'valor_sugerido': '01 (Consulta externa)',
                'severidad': 'Alta'
            })
        
        return errors

    def _validate_finality_and_external_cause(self, line):
        """
        Validar finalidad de tecnología y causa externa
        """
        errors = []
        
        if line.product_id and line.product_id.rips_service_type:
            service_type = line.product_id.rips_service_type
            
            if service_type == 'consulta':
                valid_finalities = ['10', '20', '30', '40', '50', '60']
                finality_names = {
                    '10': 'Promoción de la salud',
                    '20': 'Prevención de la enfermedad',
                    '30': 'Diagnóstico',
                    '40': 'Tratamiento',
                    '50': 'Rehabilitación',
                    '60': 'Paliación'
                }
                
                if line.finalidad and line.finalidad not in valid_finalities:
                    errors.append({
                        'tipo': 'Finalidad',
                        'descripcion': f'Finalidad inválida para consulta: {line.finalidad}',
                        'campo': 'finalidad',
                        'valor_actual': line.finalidad,
                        'valor_sugerido': '10 (Promoción de la salud)',
                        'severidad': 'Media'
                    })
            
            elif service_type == 'procedimiento':
                valid_range_1 = [str(i).zfill(2) for i in range(12, 21)]
                valid_range_2 = [str(i).zfill(2) for i in range(22, 45)]
                valid_finalities = valid_range_1 + valid_range_2
                
                if line.finalidad and line.finalidad not in valid_finalities:
                    errors.append({
                        'tipo': 'Finalidad',
                        'descripcion': f'Finalidad inválida para procedimiento: {line.finalidad}',
                        'campo': 'finalidad',
                        'valor_actual': line.finalidad,
                        'valor_sugerido': '44 (Terapéutica)',
                        'severidad': 'Media'
                    })
        
        # Validar causa externa (21-30)
        if line.causa_externa:
            try:
                causa_num = int(line.causa_externa)
                if not (21 <= causa_num <= 30):
                    errors.append({
                        'tipo': 'Causa Externa',
                        'descripcion': f'Causa externa debe estar entre 21-30: {line.causa_externa}',
                        'campo': 'causa_externa',
                        'valor_actual': line.causa_externa,
                        'valor_sugerido': '13 (Enfermedad general)',
                        'severidad': 'Media'
                    })
            except ValueError:
                errors.append({
                    'tipo': 'Causa Externa',
                    'descripcion': f'Causa externa debe ser numérica: {line.causa_externa}',
                    'campo': 'causa_externa',
                    'valor_actual': line.causa_externa,
                    'valor_sugerido': '13',
                    'severidad': 'Alta'
                })
        
        return errors

    def _validate_monetary_values(self, line):
        """
        Validar valores monetarios y pagos moderadores
        """
        errors = []
        
        # El valor del servicio debe ser positivo si se factura por evento
        if line.price_subtotal < 0:
            errors.append({
                'tipo': 'Valores Monetarios',
                'descripcion': 'El valor del servicio no puede ser negativo',
                'campo': 'price_subtotal',
                'valor_actual': str(line.price_subtotal),
                'valor_sugerido': '0 o valor positivo',
                'severidad': 'Alta'
            })
        
        # Validar pago moderador no exceda valor del servicio
        if line.valor_pago_moderador and line.valor_pago_moderador > line.price_subtotal:
            errors.append({
                'tipo': 'Pago Moderador',
                'descripcion': 'Valor pago moderador no puede exceder valor del servicio',
                'campo': 'valor_pago_moderador',
                'valor_actual': str(line.valor_pago_moderador),
                'valor_sugerido': str(line.price_subtotal),
                'severidad': 'Alta'
            })
        
        # Validar tipo de pago moderador
        valid_payment_types = ['01', '02', '03', '04', '05']
        payment_names = {
            '01': 'Copago',
            '02': 'Cuota moderadora',
            '03': 'Pagos compartidos planes voluntarios',
            '04': 'Anticipos',
            '05': 'No aplica'
        }
        
        if line.tipo_pago_moderador and line.tipo_pago_moderador not in valid_payment_types:
            errors.append({
                'tipo': 'Tipo Pago Moderador',
                'descripcion': f'Tipo de pago moderador inválido: {line.tipo_pago_moderador}',
                'campo': 'tipo_pago_moderador',
                'valor_actual': line.tipo_pago_moderador,
                'valor_sugerido': '05 (No aplica)',
                'severidad': 'Media'
            })
        
        # Validar coherencia entre tipo y valor de pago moderador
        if line.tipo_pago_moderador == '05' and line.valor_pago_moderador and line.valor_pago_moderador > 0:
            errors.append({
                'tipo': 'Coherencia Pago',
                'descripcion': 'Si tipo pago es "No aplica", valor debe ser 0',
                'campo': 'valor_pago_moderador',
                'valor_actual': str(line.valor_pago_moderador),
                'valor_sugerido': '0',
                'severidad': 'Media'
            })
        
        return errors

    def _validate_authorization_and_mipres(self, line):
        """
        Validar números de autorización y MIPRES
        """
        errors = []
        
        # Validar formato de autorización (hasta 30 caracteres)
        if line.autorizacion:
            auth_str = str(line.autorizacion).strip()
            if len(auth_str) > 30:
                errors.append({
                    'tipo': 'Autorización',
                    'descripcion': f'Número de autorización excede 30 caracteres: {len(auth_str)}',
                    'campo': 'autorizacion',
                    'valor_actual': auth_str,
                    'valor_sugerido': auth_str[:30],
                    'severidad': 'Media'
                })
        
        # Validar ID MIPRES (hasta 15 caracteres)
        if line.id_mipres:
            mipres_str = str(line.id_mipres).strip()
            if len(mipres_str) > 15:
                errors.append({
                    'tipo': 'ID MIPRES',
                    'descripcion': f'ID MIPRES excede 15 caracteres: {len(mipres_str)}',
                    'campo': 'id_mipres',
                    'valor_actual': mipres_str,
                    'valor_sugerido': mipres_str[:15],
                    'severidad': 'Media'
                })
            
            # MIPRES debe ser alfanumérico
            if not re.match(r'^[A-Za-z0-9]+$', mipres_str):
                errors.append({
                    'tipo': 'Formato MIPRES',
                    'descripcion': 'ID MIPRES debe ser alfanumérico',
                    'campo': 'id_mipres',
                    'valor_actual': mipres_str,
                    'valor_sugerido': 'Solo letras y números',
                    'severidad': 'Media'
                })
        
        return errors

    def _validate_geographic_data(self, line):
        """
        Validar datos geográficos (país, municipio, zona)
        """
        errors = []
        
        # Validar código de país (numérico, hasta 3 dígitos)
        if line.patient_country_id and line.patient_country_id.numeric_code:
            country_code = str(line.patient_country_id.numeric_code)
            if not country_code.isdigit() or len(country_code) > 3:
                errors.append({
                    'tipo': 'Código País',
                    'descripción': f'Código de país inválido: {country_code}',
                    'campo': 'patient_country_id.numeric_code',
                    'valor_actual': country_code,
                    'valor_sugerido': '170 (Colombia)',
                    'severidad': 'Media'
                })
        
        # Validar código de municipio (5 dígitos para Colombia)
        if line.patient_city_id and line.patient_city_id.code:
            city_code = str(line.patient_city_id.code)
            if len(city_code) != 5 or not city_code.isdigit():
                errors.append({
                    'tipo': 'Código Municipio',
                    'descripcion': f'Código de municipio debe tener 5 dígitos: {city_code}',
                    'campo': 'patient_city_id.code',
                    'valor_actual': city_code,
                    'valor_sugerido': '08001 (Barranquilla)',
                    'severidad': 'Media'
                })
        
        # Validar zona territorial
        valid_zones = ['01', '02']
        zone_names = {'01': 'Urbano', '02': 'Rural'}
        
        if line.patient_zone:
            zone_code = '01' if line.patient_zone == 'urbano' else '02' if line.patient_zone == 'rural' else None
            if not zone_code:
                errors.append({
                    'tipo': 'Zona Territorial',
                    'descripcion': f'Zona territorial inválida: {line.patient_zone}',
                    'campo': 'patient_zone',
                    'valor_actual': line.patient_zone,
                    'valor_sugerido': 'urbano o rural',
                    'severidad': 'Media'
                })
        
        return errors

    def _validate_cross_field_consistency(self, line):
        """
        Validar coherencia entre campos relacionados
        """
        errors = []
        
        # Validar coherencia entre género y diagnósticos específicos
        if line.patient_gender and line.diagnostico_principal:
            gender = line.patient_gender
            diagnosis = line.diagnostico_principal.upper()
            
            # Diagnósticos específicos de embarazo (O00-O99) solo para mujeres
            if diagnosis.startswith('O') and gender != 'F':
                errors.append({
                    'tipo': 'Coherencia Género-Diagnóstico',
                    'descripcion': f'Diagnóstico de embarazo ({diagnosis}) incompatible con género {gender}',
                    'campo': 'diagnostico_principal',
                    'valor_actual': diagnosis,
                    'valor_sugerido': 'Revisar género o diagnóstico',
                    'severidad': 'Alta'
                })
            
            # Diagnósticos específicos de próstata para hombres
            prostate_codes = ['N40', 'N41', 'N42', 'C61']
            if any(diagnosis.startswith(code) for code in prostate_codes) and gender != 'M':
                errors.append({
                    'tipo': 'Coherencia Género-Diagnóstico',
                    'descripcion': f'Diagnóstico de próstata ({diagnosis}) incompatible con género {gender}',
                    'campo': 'diagnostico_principal',
                    'valor_actual': diagnosis,
                    'valor_sugerido': 'Revisar género o diagnóstico',
                    'severidad': 'Alta'
                })
        
        # Validar coherencia entre edad y servicios específicos
        if line.patient_birth_date:
            today = date.today()
            age = today.year - line.patient_birth_date.year - ((today.month, today.day) < (line.patient_birth_date.month, line.patient_birth_date.day))
            
            # Servicios pediátricos para menores
            if line.product_id and 'pediatr' in (line.product_id.name or '').lower() and age >= 18:
                errors.append({
                    'tipo': 'Coherencia Edad-Servicio',
                    'descripcion': f'Servicio pediátrico para paciente de {age} años',
                    'campo': 'product_id',
                    'valor_actual': line.product_id.name,
                    'valor_sugerido': 'Servicio apropiado para la edad',
                    'severidad': 'Media'
                })
            
            # Servicios geriátricos para adultos mayores
            if line.product_id and 'geriatr' in (line.product_id.name or '').lower() and age < 60:
                errors.append({
                    'tipo': 'Coherencia Edad-Servicio',
                    'descripcion': f'Servicio geriátrico para paciente de {age} años',
                    'campo': 'product_id',
                    'valor_actual': line.product_id.name,
                    'valor_sugerido': 'Servicio apropiado para la edad',
                    'severidad': 'Media'
                })
        
        return errors

    def _validate_special_populations(self, line):
        """
        Validar poblaciones especiales (AS, MS)
        """
        errors = []
        
        if line.patient_doc_type in ['AS', 'MS']:
            # Verificar que se cumplen las condiciones para poblaciones especiales
            if not line.patient_document or line.patient_document == '':
                errors.append({
                    'tipo': 'Población Especial',
                    'descripcion': f'Tipo {line.patient_doc_type} requiere número de documento específico',
                    'campo': 'patient_document',
                    'valor_actual': line.patient_document or '',
                    'valor_sugerido': 'Asignar número según protocolo ADRES',
                    'severidad': 'Alta'
                })
            
            # Verificar resolución 762 de 2023 para AS y MS
            if line.patient_doc_type == 'AS':

                if line.patient_birth_date:
                    today = date.today()
                    age = today.year - line.patient_birth_date.year - ((today.month, today.day) < (line.patient_birth_date.month, line.patient_birth_date.day))
                    if age < 18:
                        errors.append({
                            'tipo': 'Población Especial',
                            'descripcion': f'AS (Adulto sin identificar) para menor de 18 años (edad: {age})',
                            'campo': 'patient_doc_type',
                            'valor_actual': 'AS',
                            'valor_sugerido': 'MS (Menor sin identificar)',
                            'severidad': 'Alta'
                        })
        
        return errors

    def _validate_invoice_for_rips(self, invoice):
        """
        Método principal de validación completo con todas las validaciones RIPS
        """
        errores = []
        
        # Validaciones a nivel de factura
        if not invoice.company_id.partner_id.vat_co:
            errores.append({
                'tipo': 'Datos Empresa',
                'descripcion': 'NIT de la empresa no configurado',
                'campo': 'company_id.partner_id.vat_co',
                'valor_actual': '',
                'valor_sugerido': 'Configurar NIT en la empresa',
                'linea': 'Factura',
                'producto': '',
                'paciente': '',
                'severidad': 'Alta'
            })
        
        if not invoice.company_id.partner_id.ref:
            errores.append({
                'tipo': 'Datos Empresa',
                'descripcion': 'Código prestador no configurado',
                'campo': 'company_id.partner_id.ref',
                'valor_actual': '',
                'valor_sugerido': 'Configurar código prestador (12 dígitos)',
                'linea': 'Factura',
                'producto': '',
                'paciente': '',
                'severidad': 'Alta'
            })
        
        # Validar que el código prestador tenga 12 dígitos
        if invoice.company_id.partner_id.ref:
            ref_code = str(invoice.company_id.partner_id.ref).strip()
            if not re.match(r'^\d{12}$', ref_code):
                errores.append({
                    'tipo': 'Código Prestador',
                    'descripcion': 'Código prestador debe tener exactamente 12 dígitos',
                    'campo': 'company_id.partner_id.ref',
                    'valor_actual': ref_code,
                    'valor_sugerido': 'Código de 12 dígitos',
                    'linea': 'Factura',
                    'producto': '',
                    'paciente': '',
                    'severidad': 'Alta'
                })
        
        # Validaciones a nivel de líneas
        for line_num, line in enumerate(invoice.invoice_line_ids, 1):
            if line.product_id and line.product_id.rips_service_type and line.product_id.rips_service_type != 'none':
                
                # Todos los métodos de validación
                validation_methods = [
                    self._validate_document_type_by_age_and_nationality,
                    self._validate_document_number_format,
                    self._validate_user_type_consistency,
                    self._validate_diagnosis_codes,
                    self._validate_cups_codes,
                    self._validate_professional_data,
                    self._validate_medication_specific_fields,
                    self._validate_modality_and_service_group,
                    self._validate_finality_and_external_cause,
                    self._validate_monetary_values,
                    self._validate_authorization_and_mipres,
                    self._validate_geographic_data,
                    self._validate_cross_field_consistency,
                    self._validate_special_populations,
                ]
                
                for validation_method in validation_methods:
                    try:
                        validation_errors = validation_method(line)
                        for error in validation_errors:
                            error['linea'] = f'Línea {line_num}'
                            error['producto'] = line.product_id.name if line.product_id else ''
                            error['paciente'] = f"{line.patient_doc_type or ''} {line.patient_document or ''}"
                            errores.append(error)
                    except Exception as e:
                        _logger.error(f"Error en validación {validation_method.__name__}: {str(e)}")
                
                # Validar fechas de servicios
                try:
                    date_errors = self._validate_service_dates(line, invoice)
                    for error in date_errors:
                        error['linea'] = f'Línea {line_num}'
                        error['producto'] = line.product_id.name if line.product_id else ''
                        error['paciente'] = f"{line.patient_doc_type or ''} {line.patient_document or ''}"
                        errores.append(error)
                except Exception as e:
                    _logger.error(f"Error en validación de fechas: {str(e)}")
        
        return errores

    def action_generate_rips_excel(self):
        """
        Método mejorado para generar Excel RIPS con todas las validaciones integradas
        """
        # Obtener configuración del contexto si viene del wizard
        wizard_config = self.env.context.get('rips_wizard_config', {})
        
        # Crear el Excel en memoria
        output = BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        
        # Estilos mejorados
        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#4CAF50',
            'font_color': 'white',
            'border': 1,
            'align': 'center',
            'valign': 'vcenter',
            'text_wrap': True
        })
        
        data_format = workbook.add_format({
            'border': 1,
            'align': 'left',
            'valign': 'vcenter',
            'text_wrap': True
        })
        
        error_format = workbook.add_format({
            'bg_color': '#FFE6E6',
            'border': 1,
            'align': 'left',
            'valign': 'vcenter',
            'text_wrap': True
        })
        
        warning_format = workbook.add_format({
            'bg_color': '#FFF3CD',
            'border': 1,
            'align': 'left',
            'valign': 'vcenter',
            'text_wrap': True
        })
        
        info_format = workbook.add_format({
            'bg_color': '#E3F2FD',
            'border': 1,
            'align': 'left',
            'valign': 'vcenter',
            'text_wrap': True
        })
        
        date_format = workbook.add_format({
            'border': 1,
            'num_format': 'yyyy-mm-dd',
            'align': 'center'
        })
        
        datetime_format = workbook.add_format({
            'border': 1,
            'num_format': 'yyyy-mm-dd hh:mm',
            'align': 'center'
        })
        
        money_format = workbook.add_format({
            'border': 1,
            'num_format': '#,##0.00',
            'align': 'right'
        })

        # Generar hojas
        self._create_facturas_sheet_enhanced(workbook, header_format, data_format, date_format, money_format, wizard_config)
        self._create_pacientes_sheet_enhanced(workbook, header_format, data_format, date_format, wizard_config)
        self._create_consultas_sheet_enhanced(workbook, header_format, data_format, datetime_format, money_format, wizard_config)
        self._create_procedimientos_sheet_enhanced(workbook, header_format, data_format, datetime_format, money_format, wizard_config)
        self._create_medicamentos_sheet_enhanced(workbook, header_format, data_format, datetime_format, money_format, wizard_config)
        self._create_otros_servicios_sheet_enhanced(workbook, header_format, data_format, datetime_format, money_format, wizard_config)
        
        # Hoja de validaciones mejorada
        self._create_validaciones_sheet_complete(workbook, header_format, error_format, warning_format, info_format, wizard_config)
        
        # Crear hoja de resumen
        self._create_resumen_sheet_enhanced(workbook, header_format, data_format, money_format, wizard_config)

        workbook.close()
        output.seek(0)
        
        # Crear nombre de archivo más descriptivo
        date_range = ""
        if wizard_config.get('date_from') and wizard_config.get('date_to'):
            date_range = f"_{wizard_config['date_from']}_{wizard_config['date_to']}"
        
        filename = f"RIPS_Excel{date_range}_{len(self)}_facturas_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        excel_data = base64.b64encode(output.read())
        
        # Crear attachment
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': excel_data,
            'res_model': self._name,
            'res_id': self.id if len(self) == 1 else False,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'description': f'Excel RIPS generado para {len(self)} factura(s) con validaciones completas'
        })
        
        # Marcar facturas como RIPS generado
        self.write({'rips_generated': True})
        
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    def _create_validaciones_sheet_complete(self, workbook, header_format, error_format, warning_format, info_format, wizard_config):
        """
        Crear hoja de validaciones completa con todas las validaciones RIPS
        """
        worksheet = workbook.add_worksheet('Validaciones RIPS')
        
        headers = [
            'Número Factura', 'Tipo Validación', 'Severidad', 'Descripción', 
            'Campo Afectado', 'Valor Actual', 'Valor Sugerido', 
            'Línea/Servicio', 'Producto', 'Paciente', 'Fecha Detección',
            'Normativa Aplicable', 'Acción Recomendada'
        ]
        
        for col, header in enumerate(headers):
            worksheet.write(0, col, header, header_format)
        
        row = 1
        total_errores = 0
        total_warnings = 0
        total_info = 0
        
        # Ejecutar validaciones para todas las facturas
        for invoice in self:
            errores = self._validate_invoice_for_rips(invoice)
            
            for error in errores:
                severidad = error.get('severidad', 'Media')
                
                # Determinar formato según severidad
                if severidad == 'Alta':
                    format_to_use = error_format
                    total_errores += 1
                elif severidad == 'Media':
                    format_to_use = warning_format
                    total_warnings += 1
                else:
                    format_to_use = info_format
                    total_info += 1
                
                # Determinar normativa aplicable
                normativa = self._get_applicable_regulation(error.get('tipo', ''))
                
                # Determinar acción recomendada
                accion = self._get_recommended_action(error.get('tipo', ''), severidad)
                
                col = 0
                worksheet.write(row, col, invoice.name, format_to_use); col += 1
                worksheet.write(row, col, error.get('tipo', ''), format_to_use); col += 1
                worksheet.write(row, col, severidad, format_to_use); col += 1
                worksheet.write(row, col, error.get('descripcion', ''), format_to_use); col += 1
                worksheet.write(row, col, error.get('campo', ''), format_to_use); col += 1
                worksheet.write(row, col, str(error.get('valor_actual', '')), format_to_use); col += 1
                worksheet.write(row, col, error.get('valor_sugerido', ''), format_to_use); col += 1
                worksheet.write(row, col, error.get('linea', ''), format_to_use); col += 1
                worksheet.write(row, col, error.get('producto', ''), format_to_use); col += 1
                worksheet.write(row, col, error.get('paciente', ''), format_to_use); col += 1
                worksheet.write(row, col, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), format_to_use); col += 1
                worksheet.write(row, col, normativa, format_to_use); col += 1
                worksheet.write(row, col, accion, format_to_use); col += 1
                row += 1
        
        # Agregar resumen de validaciones al inicio
        if row > 1:
            worksheet.insert_rows(1, 4)
            worksheet.merge_range(1, 0, 1, 5, f'RESUMEN DE VALIDACIONES', header_format)
            worksheet.merge_range(2, 0, 2, 5, f'Errores Críticos (Alta): {total_errores} | Advertencias (Media): {total_warnings} | Informativos (Baja): {total_info}', warning_format)
            worksheet.merge_range(3, 0, 3, 5, 'Los errores críticos pueden impedir la correcta generación de RIPS según resolución 2275 de 2023', error_format)
            worksheet.write(4, 0, '', format_to_use)  # Fila en blanco
        
        worksheet.set_column('A:M', 18)
        if row > 5:
            worksheet.autofilter(5, 0, row - 1, len(headers) - 1)
        
        return worksheet

    def _get_applicable_regulation(self, validation_type):
        """
        Obtener normativa aplicable según tipo de validación
        """
        regulations = {
            'Tipo Documento': 'Res. 2275/2023 - Anexo Técnico Sección 3.2',
            'Número Documento': 'Res. 2275/2023 - Tabla TipoIdPISIS',
            'Tipo Usuario': 'Res. 2275/2023 - RIPSTipoUsuarioVersion2',
            'Pago Moderador': 'Decreto 1652/2022',
            'Diagnóstico': 'CIE-10 - OMS',
            'Código CUPS': 'Res. CUPS vigente MinSalud',
            'Modalidad Atención': 'Res. 2275/2023 - ModalidadAtencion',
            'Grupo Servicios': 'Res. 3100/2019',
            'Población Especial': 'Res. 762/2023 - ADRES',
            'Código Prestador': 'Res. 2275/2023 - Sección 4.1',
            'Datos Empresa': 'Res. 2275/2023 - Campo T03',
        }
        
        return regulations.get(validation_type, 'Res. 2275/2023 - General')

    def _get_recommended_action(self, validation_type, severity):
        """
        Obtener acción recomendada según tipo y severidad
        """
        if severity == 'Alta':
            actions = {
                'Tipo Documento': 'CORREGIR: Ajustar tipo documento según edad/nacionalidad',
                'Número Documento': 'CORREGIR: Verificar y corregir número documento',
                'Pago Moderador': 'CORREGIR: Ajustar valores según normativa',
                'Código Prestador': 'CONFIGURAR: Solicitar código habilitación válido',
                'Datos Empresa': 'CONFIGURAR: Completar información empresa',
            }
        elif severity == 'Media':
            actions = {
                'Diagnóstico': 'REVISAR: Verificar código CIE-10',
                'Modalidad Atención': 'REVISAR: Confirmar modalidad correcta',
                'Medicamento': 'REVISAR: Validar datos farmacológicos',
                'Fecha Servicio': 'REVISAR: Confirmar fechas de atención',
            }
        else:
            actions = {
                'default': 'INFORMATIVO: Revisar cuando sea posible'
            }
        
        return actions.get(validation_type, 'REVISAR: Verificar información según normativa RIPS')

    def _create_resumen_sheet_enhanced(self, workbook, header_format, data_format, money_format, wizard_config):
        """
        Crear hoja de resumen ejecutivo mejorada
        """
        worksheet = workbook.add_worksheet('Resumen Ejecutivo')
        
        row = 0
        
        # Título principal
        worksheet.merge_range(row, 0, row, 7, 'RESUMEN EJECUTIVO RIPS - VALIDACIONES COMPLETAS', header_format)
        row += 2
        
        # Información de generación
        generation_info = [
            ('Fecha de Generación:', datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
            ('Usuario:', self.env.user.name),
            ('Empresa:', self.env.company.name),
            ('Total Facturas:', len(self)),
        ]
        
        for label, value in generation_info:
            worksheet.write(row, 0, label, header_format)
            worksheet.write(row, 1, str(value), data_format)
            row += 1
        
        row += 1
        
        # Contadores de servicios y validaciones
        consultas_count = sum(len([l for l in inv.invoice_line_ids if l.product_id and l.product_id.rips_service_type == 'consulta']) for inv in self)
        procedimientos_count = sum(len([l for l in inv.invoice_line_ids if l.product_id and l.product_id.rips_service_type == 'procedimiento']) for inv in self)
        medicamentos_count = sum(len([l for l in inv.invoice_line_ids if l.product_id and l.product_id.rips_service_type == 'medicamento']) for inv in self)
        otros_count = sum(len([l for l in inv.invoice_line_ids if l.product_id and l.product_id.rips_service_type == 'otro_servicio']) for inv in self)
        
        # Ejecutar validaciones para el resumen
        total_validations = 0
        critical_errors = 0
        warnings = 0
        
        for invoice in self:
            errores = self._validate_invoice_for_rips(invoice)
            total_validations += len(errores)
            critical_errors += len([e for e in errores if e.get('severidad') == 'Alta'])
            warnings += len([e for e in errores if e.get('severidad') == 'Media'])
        
        # Tabla de resumen
        worksheet.write(row, 0, 'CATEGORÍA', header_format)
        worksheet.write(row, 1, 'CANTIDAD', header_format)
        worksheet.write(row, 2, 'ESTADO', header_format)
        row += 1
        
        summary_data = [
            ('Consultas RIPS', consultas_count, 'OK' if consultas_count > 0 else 'SIN DATOS'),
            ('Procedimientos RIPS', procedimientos_count, 'OK' if procedimientos_count > 0 else 'SIN DATOS'),
            ('Medicamentos RIPS', medicamentos_count, 'OK' if medicamentos_count > 0 else 'SIN DATOS'),
            ('Otros Servicios RIPS', otros_count, 'OK' if otros_count > 0 else 'SIN DATOS'),
            ('Total Validaciones', total_validations, 'COMPLETADO'),
            ('Errores Críticos', critical_errors, 'CRÍTICO' if critical_errors > 0 else 'OK'),
            ('Advertencias', warnings, 'ATENCIÓN' if warnings > 0 else 'OK'),
        ]
        
        for label, value, status in summary_data:
            worksheet.write(row, 0, label, data_format)
            worksheet.write(row, 1, value, data_format)
            
            # Color según estado
            if status == 'CRÍTICO':
                status_format = workbook.add_format({'bg_color': '#FFE6E6', 'border': 1})
            elif status == 'ATENCIÓN':
                status_format = workbook.add_format({'bg_color': '#FFF3CD', 'border': 1})
            elif status == 'OK':
                status_format = workbook.add_format({'bg_color': '#E8F5E8', 'border': 1})
            else:
                status_format = data_format
            
            worksheet.write(row, 2, status, status_format)
            row += 1
        
        worksheet.set_column('A:H', 20)
        
        return worksheet

    def _create_facturas_sheet_enhanced(self, workbook, header_format, data_format, date_format, money_format, wizard_config):
        """Versión mejorada de la hoja de facturas"""
        worksheet = workbook.add_worksheet('Facturas')
        
        headers = [
            'Número Factura', 'Fecha Factura', 'Fecha Vencimiento', 'Tipo Factura', 
            'Partner', 'NIT Partner', 'NIT Obligado', 'Tipo Nota', 'Número Nota', 
            'Médico', 'Departamento', 'Diagnóstico', 'Tratamiento',
            'Subtotal', 'Impuestos', 'Total Factura', 'Estado',
            'Método Pago', 'Número Autorización', 'Estado RIPS',
            'Servicios RIPS', 'Pacientes', 'Fecha Creación', 'Usuario Creación'
        ]
        
        for col, header in enumerate(headers):
            worksheet.write(0, col, header, header_format)
        
        row = 1
        for invoice in self:
            rips_services = len([l for l in invoice.invoice_line_ids 
                               if l.product_id and l.product_id.rips_service_type and l.product_id.rips_service_type != 'none'])
            
            pacientes = set()
            for line in invoice.invoice_line_ids:
                if line.patient_doc_type and line.patient_document:
                    pacientes.add((line.patient_doc_type, line.patient_document))
            
            col = 0
            worksheet.write(row, col, invoice.name or '', data_format); col += 1
            worksheet.write(row, col, invoice.invoice_date or '', date_format); col += 1
            worksheet.write(row, col, invoice.invoice_date_due or '', date_format); col += 1
            worksheet.write(row, col, dict(invoice._fields['move_type'].selection).get(invoice.move_type, ''), data_format); col += 1
            worksheet.write(row, col, invoice.partner_id.name or '', data_format); col += 1
            worksheet.write(row, col, invoice.partner_id.vat or '', data_format); col += 1
            worksheet.write(row, col, invoice.company_id.partner_id.vat_co or '', data_format); col += 1
            worksheet.write(row, col, self._get_rips_note_type(self._get_document_type()) or '', data_format); col += 1
            worksheet.write(row, col, invoice.name if invoice.move_type in ['out_refund', 'in_refund'] else '', data_format); col += 1
            worksheet.write(row, col, invoice.physician_id.name if hasattr(invoice, 'physician_id') and invoice.physician_id else '', data_format); col += 1
            worksheet.write(row, col, invoice.department_id.name if hasattr(invoice, 'department_id') and invoice.department_id else '', data_format); col += 1
            worksheet.write(row, col, invoice.diagnosis_id.name if hasattr(invoice, 'diagnosis_id') and invoice.diagnosis_id else '', data_format); col += 1
            worksheet.write(row, col, invoice.treatment_id.name if hasattr(invoice, 'treatment_id') and invoice.treatment_id else '', data_format); col += 1
            worksheet.write(row, col, invoice.amount_untaxed or 0, money_format); col += 1
            worksheet.write(row, col, invoice.amount_tax or 0, money_format); col += 1
            worksheet.write(row, col, invoice.amount_total or 0, money_format); col += 1
            worksheet.write(row, col, dict(invoice._fields['state'].selection).get(invoice.state, ''), data_format); col += 1
            worksheet.write(row, col, getattr(invoice, 'payment_method', '') or '', data_format); col += 1
            worksheet.write(row, col, getattr(invoice, 'authorization_number', '') or '', data_format); col += 1
            worksheet.write(row, col, 'Generado' if getattr(invoice, 'rips_generated', False) else 'Pendiente', data_format); col += 1
            worksheet.write(row, col, rips_services, data_format); col += 1
            worksheet.write(row, col, len(pacientes), data_format); col += 1
            worksheet.write(row, col, invoice.create_date or '', date_format); col += 1
            worksheet.write(row, col, invoice.create_uid.name if invoice.create_uid else '', data_format); col += 1
            
            row += 1
        
        # Ajustar ancho de columnas
        worksheet.set_column('A:X', 15)
        
        # Agregar filtros
        if row > 1:
            worksheet.autofilter(0, 0, row - 1, len(headers) - 1)

    def _create_pacientes_sheet_enhanced(self, workbook, header_format, data_format, date_format, wizard_config):
        """Versión mejorada de la hoja de pacientes únicos"""
        worksheet = workbook.add_worksheet('Pacientes')
        
        # Headers expandidos
        headers = [
            'Número Factura', 'Tipo Documento', 'Número Documento', 'Nombre Paciente',
            'Fecha Nacimiento', 'Edad', 'Género', 'Tipo Usuario', 'País Residencia', 
            'Ciudad Residencia', 'Zona', 'Nacionalidad', 'Total Servicios',
            'Valor Total Servicios', 'Última Atención', 'Servicios por Tipo'
        ]
        
        for col, header in enumerate(headers):
            worksheet.write(0, col, header, header_format)
        
        # Recopilar pacientes únicos con información agregada
        pacientes_data = {}
        row = 1
        
        for invoice in self:
            for line in invoice.invoice_line_ids:
                if line.patient_doc_type and line.patient_document:
                    patient_key = (line.patient_doc_type, line.patient_document)
                    
                    if patient_key not in pacientes_data:
                        # Calcular edad
                        age = ''
                        if line.patient_birth_date:
                            today = date.today()
                            age = today.year - line.patient_birth_date.year - ((today.month, today.day) < (line.patient_birth_date.month, line.patient_birth_date.day))
                        
                        pacientes_data[patient_key] = {
                            'invoice_name': invoice.name,
                            'line': line,
                            'age': age,
                            'services_count': 0,
                            'total_value': 0,
                            'last_attention': None,
                            'service_types': {'consulta': 0, 'procedimiento': 0, 'medicamento': 0, 'otro_servicio': 0}
                        }
                    
                    # Agregar datos del servicio
                    patient_data = pacientes_data[patient_key]
                    if line.product_id and line.product_id.rips_service_type and line.product_id.rips_service_type != 'none':
                        patient_data['services_count'] += 1
                        patient_data['total_value'] += line.price_subtotal or 0
                        
                        # Tipo de servicio
                        service_type = line.product_id.rips_service_type
                        if service_type in patient_data['service_types']:
                            patient_data['service_types'][service_type] += 1
                        
                        # Última atención
                        attention_date = (line.fecha_atencion or line.fecha_procedimiento or 
                                        line.fecha_dispensacion or line.fecha_suministro or invoice.date)
                        if attention_date:
                            if not patient_data['last_attention'] or attention_date > patient_data['last_attention']:
                                patient_data['last_attention'] = attention_date
        
        # Escribir datos de pacientes
        for patient_key, patient_info in pacientes_data.items():
            line = patient_info['line']
            
            # Crear resumen de servicios por tipo
            services_summary = ', '.join([f"{k.title()}: {v}" for k, v in patient_info['service_types'].items() if v > 0])
            
            col = 0
            worksheet.write(row, col, patient_info['invoice_name'], data_format); col += 1
            worksheet.write(row, col, line.patient_doc_type or '', data_format); col += 1
            worksheet.write(row, col, line.patient_document or '', data_format); col += 1
            worksheet.write(row, col, line.patient_name or '', data_format); col += 1
            worksheet.write(row, col, line.patient_birth_date or '', date_format); col += 1
            worksheet.write(row, col, patient_info['age'], data_format); col += 1
            worksheet.write(row, col, dict(line._fields.get('patient_gender', {}).get('selection', [])).get(line.patient_gender, ''), data_format); col += 1
            worksheet.write(row, col, dict(line._fields.get('patient_user_type', {}).get('selection', [])).get(line.patient_user_type, ''), data_format); col += 1
            worksheet.write(row, col, line.patient_country_id.name if line.patient_country_id else '', data_format); col += 1
            worksheet.write(row, col, line.patient_city_id.name if line.patient_city_id else '', data_format); col += 1
            worksheet.write(row, col, dict(line._fields.get('patient_zone', {}).get('selection', [])).get(line.patient_zone, ''), data_format); col += 1
            worksheet.write(row, col, line.patient_nationality or '', data_format); col += 1
            worksheet.write(row, col, patient_info['services_count'], data_format); col += 1
            worksheet.write(row, col, patient_info['total_value'], data_format); col += 1
            worksheet.write(row, col, patient_info['last_attention'] or '', date_format); col += 1
            worksheet.write(row, col, services_summary, data_format); col += 1
            row += 1
        
        worksheet.set_column('A:P', 15)
        if row > 1:
            worksheet.autofilter(0, 0, row - 1, len(headers) - 1)

    def _create_consultas_sheet_enhanced(self, workbook, header_format, data_format, datetime_format, money_format, wizard_config):
        """Versión mejorada de la hoja de consultas"""
        worksheet = workbook.add_worksheet('Consultas')
        
        headers = [
            'Número Factura', 'Consecutivo', 'Tipo Doc Paciente', 'Número Doc Paciente', 'Nombre Paciente',
            'Código Prestador', 'Fecha Atención', 'Número Autorización', 'Código Consulta', 'Nombre Producto',
            'Modalidad', 'Grupo Servicios', 'Código Servicio', 'Finalidad', 'Causa Externa',
            'Diagnóstico Principal', 'Diagnóstico Rel 1', 'Diagnóstico Rel 2', 'Diagnóstico Rel 3',
            'Tipo Diagnóstico', 'Tipo Doc Profesional', 'Número Doc Profesional', 'Nombre Profesional',
            'Valor Servicio', 'Concepto Recaudo', 'Valor Moderador', 'Número FEV', 'Estado Validación'
        ]
        
        for col, header in enumerate(headers):
            worksheet.write(0, col, header, header_format)
        
        row = 1
        consecutivo_global = 1
        
        for invoice in self:
            for line in invoice.invoice_line_ids:
                if (line.product_id and line.product_id.rips_service_type == 'consulta' and 
                    line.patient_doc_type and line.patient_document):
                    
                    # Validar esta línea específica
                    validation_status = self._get_line_validation_status(line, 'consulta')
                    
                    col = 0
                    worksheet.write(row, col, invoice.name, data_format); col += 1
                    worksheet.write(row, col, consecutivo_global, data_format); col += 1
                    worksheet.write(row, col, line.patient_doc_type or '', data_format); col += 1
                    worksheet.write(row, col, line.patient_document or '', data_format); col += 1
                    worksheet.write(row, col, line.patient_name or '', data_format); col += 1
                    worksheet.write(row, col, invoice.company_id.partner_id.ref or '', data_format); col += 1
                    worksheet.write(row, col, line.fecha_atencion or invoice.date or '', datetime_format); col += 1
                    worksheet.write(row, col, line.autorizacion or '', data_format); col += 1
                    worksheet.write(row, col, line.product_id.default_code or '', data_format); col += 1
                    worksheet.write(row, col, line.product_id.name or '', data_format); col += 1
                    worksheet.write(row, col, line.modalidad or '', data_format); col += 1
                    worksheet.write(row, col, line.grupo_servicio or '', data_format); col += 1
                    worksheet.write(row, col, getattr(line, 'cod_servicio', '') or '', data_format); col += 1
                    worksheet.write(row, col, line.finalidad or '', data_format); col += 1
                    worksheet.write(row, col, line.causa_externa or '', data_format); col += 1
                    worksheet.write(row, col, line.diagnostico_principal or '', data_format); col += 1
                    worksheet.write(row, col, getattr(line, 'diagnostico_relacionado1', '') or '', data_format); col += 1
                    worksheet.write(row, col, getattr(line, 'diagnostico_relacionado2', '') or '', data_format); col += 1
                    worksheet.write(row, col, getattr(line, 'diagnostico_relacionado3', '') or '', data_format); col += 1
                    worksheet.write(row, col, dict(line._fields.get('tipo_diagnostico', {}).get('selection', [])).get(line.tipo_diagnostico, ''), data_format); col += 1
                    worksheet.write(row, col, 'CC', data_format); col += 1  # Tipo doc profesional por defecto
                    worksheet.write(row, col, '1111111111', data_format); col += 1  # Número doc profesional por defecto
                    worksheet.write(row, col, getattr(line, 'professional_name', '') or 'Profesional General', data_format); col += 1
                    worksheet.write(row, col, line.price_subtotal or 0, money_format); col += 1
                    worksheet.write(row, col, dict(line._fields.get('tipo_pago_moderador', {}).get('selection', [])).get(line.tipo_pago_moderador, ''), data_format); col += 1
                    worksheet.write(row, col, line.valor_pago_moderador or 0, money_format); col += 1
                    worksheet.write(row, col, getattr(line, 'num_fev_pago_moderador', '') or '', data_format); col += 1
                    worksheet.write(row, col, validation_status, data_format); col += 1
                    
                    row += 1
                    consecutivo_global += 1
        
        worksheet.set_column('A:AB', 12)
        if row > 1:
            worksheet.autofilter(0, 0, row - 1, len(headers) - 1)

    def _create_procedimientos_sheet_enhanced(self, workbook, header_format, data_format, datetime_format, money_format, wizard_config):
        """Versión mejorada de la hoja de procedimientos"""
        worksheet = workbook.add_worksheet('Procedimientos')
        
        headers = [
            'Número Factura', 'Consecutivo', 'Tipo Doc Paciente', 'Número Doc Paciente', 'Nombre Paciente',
            'Código Prestador', 'Fecha Procedimiento', 'ID MIPRES', 'Número Autorización',
            'Código Procedimiento', 'Nombre Producto', 'Vía Ingreso', 'Modalidad', 'Grupo Servicios',
            'Código Servicio', 'Finalidad', 'Tipo Doc Profesional', 'Número Doc Profesional', 'Nombre Profesional',
            'Diagnóstico Principal', 'Diagnóstico Relacionado', 'Complicación',
            'Valor Servicio', 'Concepto Recaudo', 'Valor Moderador', 'Número FEV', 'Estado Validación'
        ]
        
        for col, header in enumerate(headers):
            worksheet.write(0, col, header, header_format)
        
        row = 1
        consecutivo_global = 1
        
        for invoice in self:
            for line in invoice.invoice_line_ids:
                if (line.product_id and line.product_id.rips_service_type == 'procedimiento' and 
                    line.patient_doc_type and line.patient_document):
                    
                    validation_status = self._get_line_validation_status(line, 'procedimiento')
                    
                    col = 0
                    worksheet.write(row, col, invoice.name, data_format); col += 1
                    worksheet.write(row, col, consecutivo_global, data_format); col += 1
                    worksheet.write(row, col, line.patient_doc_type or '', data_format); col += 1
                    worksheet.write(row, col, line.patient_document or '', data_format); col += 1
                    worksheet.write(row, col, line.patient_name or '', data_format); col += 1
                    worksheet.write(row, col, invoice.company_id.partner_id.ref or '', data_format); col += 1
                    worksheet.write(row, col, line.fecha_procedimiento or invoice.date or '', datetime_format); col += 1
                    worksheet.write(row, col, getattr(line, 'id_mipres', '') or '', data_format); col += 1
                    worksheet.write(row, col, line.autorizacion or '', data_format); col += 1
                    worksheet.write(row, col, line.product_id.default_code or '', data_format); col += 1
                    worksheet.write(row, col, line.product_id.name or '', data_format); col += 1
                    worksheet.write(row, col, dict(getattr(line, '_fields', {}).get('via_ingreso', {}).get('selection', [])).get(getattr(line, 'via_ingreso', ''), ''), data_format); col += 1
                    worksheet.write(row, col, line.modalidad or '', data_format); col += 1
                    worksheet.write(row, col, line.grupo_servicio or '', data_format); col += 1
                    worksheet.write(row, col, getattr(line, 'cod_servicio', '') or '', data_format); col += 1
                    worksheet.write(row, col, line.finalidad or '', data_format); col += 1
                    worksheet.write(row, col, 'CC', data_format); col += 1
                    worksheet.write(row, col, '1111111111', data_format); col += 1
                    worksheet.write(row, col, getattr(line, 'professional_name', '') or 'Profesional General', data_format); col += 1
                    worksheet.write(row, col, line.diagnostico_principal or '', data_format); col += 1
                    worksheet.write(row, col, getattr(line, 'diagnostico_relacionado', '') or '', data_format); col += 1
                    worksheet.write(row, col, getattr(line, 'complicacion', '') or '', data_format); col += 1
                    worksheet.write(row, col, line.price_subtotal or 0, money_format); col += 1
                    worksheet.write(row, col, dict(line._fields.get('tipo_pago_moderador', {}).get('selection', [])).get(line.tipo_pago_moderador, ''), data_format); col += 1
                    worksheet.write(row, col, line.valor_pago_moderador or 0, money_format); col += 1
                    worksheet.write(row, col, getattr(line, 'num_fev_pago_moderador', '') or '', data_format); col += 1
                    worksheet.write(row, col, validation_status, data_format); col += 1
                    
                    row += 1
                    consecutivo_global += 1
        
        worksheet.set_column('A:AA', 12)
        if row > 1:
            worksheet.autofilter(0, 0, row - 1, len(headers) - 1)

    def _create_medicamentos_sheet_enhanced(self, workbook, header_format, data_format, datetime_format, money_format, wizard_config):
        """Versión mejorada de la hoja de medicamentos"""
        worksheet = workbook.add_worksheet('Medicamentos')
        
        headers = [
            'Número Factura', 'Consecutivo', 'Tipo Doc Paciente', 'Número Doc Paciente', 'Nombre Paciente',
            'Código Prestador', 'Número Autorización', 'ID MIPRES', 'Fecha Dispensación',
            'Diagnóstico Principal', 'Diagnóstico Relacionado', 'Tipo Medicamento', 'Código Tecnología',
            'Nombre Tecnología', 'Nombre Producto', 'Concentración', 'Unidad Medida', 'Forma Farmacéutica',
            'Unidad Min Dispensación', 'Cantidad', 'Días Tratamiento', 'Tipo Doc Profesional',
            'Número Doc Profesional', 'Nombre Profesional', 'Valor Unitario', 'Valor Servicio',
            'Concepto Recaudo', 'Valor Moderador', 'Número FEV', 'Estado Validación'
        ]
        
        for col, header in enumerate(headers):
            worksheet.write(0, col, header, header_format)
        
        row = 1
        consecutivo_global = 1
        
        for invoice in self:
            for line in invoice.invoice_line_ids:
                if (line.product_id and line.product_id.rips_service_type == 'medicamento' and 
                    line.patient_doc_type and line.patient_document):
                    
                    validation_status = self._get_line_validation_status(line, 'medicamento')
                    
                    col = 0
                    worksheet.write(row, col, invoice.name, data_format); col += 1
                    worksheet.write(row, col, consecutivo_global, data_format); col += 1
                    worksheet.write(row, col, line.patient_doc_type or '', data_format); col += 1
                    worksheet.write(row, col, line.patient_document or '', data_format); col += 1
                    worksheet.write(row, col, line.patient_name or '', data_format); col += 1
                    worksheet.write(row, col, invoice.company_id.partner_id.ref or '', data_format); col += 1
                    worksheet.write(row, col, line.autorizacion or '', data_format); col += 1
                    worksheet.write(row, col, getattr(line, 'id_mipres', '') or '', data_format); col += 1
                    worksheet.write(row, col, getattr(line, 'fecha_dispensacion', None) or invoice.date or '', datetime_format); col += 1
                    worksheet.write(row, col, line.diagnostico_principal or '', data_format); col += 1
                    worksheet.write(row, col, getattr(line, 'diagnostico_relacionado1', '') or '', data_format); col += 1
                    worksheet.write(row, col, dict(line._fields.get('tipo_medicamento', {}).get('selection', [])).get(getattr(line, 'tipo_medicamento', ''), ''), data_format); col += 1
                    worksheet.write(row, col, line.product_id.default_code or '', data_format); col += 1
                    worksheet.write(row, col, line.product_id.name or '', data_format); col += 1
                    worksheet.write(row, col, line.name or '', data_format); col += 1
                    worksheet.write(row, col, getattr(line, 'concentracion', 0) or 0, data_format); col += 1
                    worksheet.write(row, col, getattr(line, 'unidad_medida', 0) or 0, data_format); col += 1
                    worksheet.write(row, col, getattr(line, 'forma_farmaceutica', '') or '', data_format); col += 1
                    worksheet.write(row, col, getattr(line, 'unidad_min_dispensacion', 1) or 1, data_format); col += 1
                    worksheet.write(row, col, line.quantity or 0, data_format); col += 1
                    worksheet.write(row, col, getattr(line, 'dias_tratamiento', 1) or 1, data_format); col += 1
                    worksheet.write(row, col, 'CC', data_format); col += 1
                    worksheet.write(row, col, '1111111111', data_format); col += 1
                    worksheet.write(row, col, getattr(line, 'professional_name', '') or 'Profesional General', data_format); col += 1
                    worksheet.write(row, col, line.price_unit or 0, money_format); col += 1
                    worksheet.write(row, col, line.price_subtotal or 0, money_format); col += 1
                    worksheet.write(row, col, dict(line._fields.get('tipo_pago_moderador', {}).get('selection', [])).get(line.tipo_pago_moderador, ''), data_format); col += 1
                    worksheet.write(row, col, getattr(line, 'valor_pago_moderador', 0) or 0, money_format); col += 1
                    worksheet.write(row, col, getattr(line, 'num_fev_pago_moderador', '') or '', data_format); col += 1
                    worksheet.write(row, col, validation_status, data_format); col += 1
                    
                    row += 1
                    consecutivo_global += 1
        
        worksheet.set_column('A:AD', 12)
        if row > 1:
            worksheet.autofilter(0, 0, row - 1, len(headers) - 1)

    def _create_otros_servicios_sheet_enhanced(self, workbook, header_format, data_format, datetime_format, money_format, wizard_config):
        """Versión mejorada de la hoja de otros servicios"""
        worksheet = workbook.add_worksheet('Otros Servicios')
        
        headers = [
            'Número Factura', 'Consecutivo', 'Tipo Doc Paciente', 'Número Doc Paciente', 'Nombre Paciente',
            'Código Prestador', 'Número Autorización', 'ID MIPRES', 'Fecha Suministro',
            'Tipo OS', 'Código Tecnología', 'Nombre Tecnología', 'Nombre Producto',
            'Cantidad', 'Valor Unitario', 'Valor Servicio', 'Tipo Doc Profesional',
            'Número Doc Profesional', 'Nombre Profesional', 'Concepto Recaudo',
            'Valor Moderador', 'Número FEV', 'Estado Validación', 'Observaciones'
        ]
        
        for col, header in enumerate(headers):
            worksheet.write(0, col, header, header_format)
        
        row = 1
        consecutivo_global = 1
        
        for invoice in self:
            for line in invoice.invoice_line_ids:
                if (line.product_id and line.product_id.rips_service_type == 'otro_servicio' and 
                    line.patient_doc_type and line.patient_document):
                    
                    validation_status = self._get_line_validation_status(line, 'otro_servicio')
                    
                    col = 0
                    worksheet.write(row, col, invoice.name, data_format); col += 1
                    worksheet.write(row, col, consecutivo_global, data_format); col += 1
                    worksheet.write(row, col, line.patient_doc_type or '', data_format); col += 1
                    worksheet.write(row, col, line.patient_document or '', data_format); col += 1
                    worksheet.write(row, col, line.patient_name or '', data_format); col += 1
                    worksheet.write(row, col, invoice.company_id.partner_id.ref or '', data_format); col += 1
                    worksheet.write(row, col, line.autorizacion or '', data_format); col += 1
                    worksheet.write(row, col, getattr(line, 'id_mipres', '') or '', data_format); col += 1
                    worksheet.write(row, col, getattr(line, 'fecha_suministro', None) or invoice.date or '', datetime_format); col += 1
                    worksheet.write(row, col, getattr(line, 'tipo_servicio', '01') or '01', data_format); col += 1
                    worksheet.write(row, col, line.product_id.default_code or '', data_format); col += 1
                    worksheet.write(row, col, line.product_id.name or '', data_format); col += 1
                    worksheet.write(row, col, line.name or '', data_format); col += 1
                    worksheet.write(row, col, line.quantity or 0, data_format); col += 1
                    worksheet.write(row, col, line.price_unit or 0, money_format); col += 1
                    worksheet.write(row, col, line.price_subtotal or 0, money_format); col += 1
                    worksheet.write(row, col, 'CC', data_format); col += 1
                    worksheet.write(row, col, '1111111111', data_format); col += 1
                    worksheet.write(row, col, getattr(line, 'professional_name', '') or 'Profesional General', data_format); col += 1
                    worksheet.write(row, col, dict(line._fields.get('tipo_pago_moderador', {}).get('selection', [])).get(line.tipo_pago_moderador, ''), data_format); col += 1
                    worksheet.write(row, col, getattr(line, 'valor_pago_moderador', 0) or 0, money_format); col += 1
                    worksheet.write(row, col, getattr(line, 'num_fev_pago_moderador', '') or '', data_format); col += 1
                    worksheet.write(row, col, validation_status, data_format); col += 1
                    worksheet.write(row, col, getattr(line, 'rips_observations', '') or '', data_format); col += 1
                    
                    row += 1
                    consecutivo_global += 1
        
        worksheet.set_column('A:X', 12)
        if row > 1:
            worksheet.autofilter(0, 0, row - 1, len(headers) - 1)

    def _get_line_validation_status(self, line, service_type):
        """
        Obtener estado de validación para una línea específica
        """
        try:
            # Crear una mini-validación solo para esta línea
            validation_methods = [
                self._validate_document_type_by_age_and_nationality,
                self._validate_document_number_format,
                self._validate_diagnosis_codes,
                self._validate_cups_codes,
            ]
            
            if service_type == 'medicamento':
                validation_methods.append(self._validate_medication_specific_fields)
            
            total_errors = 0
            critical_errors = 0
            
            for validation_method in validation_methods:
                try:
                    errors = validation_method(line)
                    total_errors += len(errors)
                    critical_errors += len([e for e in errors if e.get('severidad') == 'Alta'])
                except:
                    continue
            
            if critical_errors > 0:
                return f"CRÍTICO ({critical_errors} errores)"
            elif total_errors > 0:
                return f"ADVERTENCIA ({total_errors} issues)"
            else:
                return "VÁLIDO"
                
        except Exception as e:
            _logger.error(f"Error validando línea: {str(e)}")
            return "ERROR VALIDACIÓN"


    def _get_rips_note_type(self, doc_type):
        """Obtener tipo de nota RIPS"""
        if doc_type == 'credit_note': 
            return "NC"
        elif doc_type == 'debit_note': 
            return "ND"
        return None

    def _validate_service_dates(self, line, invoice):
        """Validar fechas de servicios estén dentro del período de facturación"""
        errors = []
        
        if not invoice.date:
            return errors
        
        # Fechas de servicios según tipo
        service_dates = []
        
        if hasattr(line, 'fecha_atencion') and line.fecha_atencion:
            service_dates.append(('fecha_atencion', line.fecha_atencion))
        if hasattr(line, 'fecha_procedimiento') and line.fecha_procedimiento:
            service_dates.append(('fecha_procedimiento', line.fecha_procedimiento))
        if hasattr(line, 'fecha_dispensacion') and line.fecha_dispensacion:
            service_dates.append(('fecha_dispensacion', line.fecha_dispensacion))
        if hasattr(line, 'fecha_suministro') and line.fecha_suministro:
            service_dates.append(('fecha_suministro', line.fecha_suministro))
        
        # Validar que las fechas estén en rango razonable
        for field_name, service_date in service_dates:
            if service_date:
                # Convertir a date si es datetime
                if isinstance(service_date, datetime):
                    service_date = service_date.date()
                
                # No puede ser futura
                if service_date > fields.Date.today():
                    errors.append({
                        'tipo': 'Fecha Servicio',
                        'descripcion': f'Fecha de {field_name} no puede ser futura',
                        'campo': field_name,
                        'valor_actual': str(service_date),
                        'valor_sugerido': str(fields.Date.today()),
                        'severidad': 'Alta'
                    })
                
                # No puede ser muy antigua (más de 2 años)
                days_diff = (fields.Date.today() - service_date).days
                if days_diff > 730:  # 2 años
                    errors.append({
                        'tipo': 'Fecha Servicio',
                        'descripcion': f'Fecha de {field_name} es muy antigua (>{days_diff} días)',
                        'campo': field_name,
                        'valor_actual': str(service_date),
                        'valor_sugerido': 'Fecha más reciente',
                        'severidad': 'Media'
                    })
        
        return errors


    rips_estado_validacion = fields.Selection([
        ('pendiente', 'Pendiente'),
        ('en_cola', 'En Cola'),
        ('procesando', 'Procesando'),
        ('generado', 'Generado'),
        ('exitoso', 'Exitoso'),
        ('error', 'Error')
    ], string='Estado RIPS', default='pendiente')
    
    cuv_code = fields.Char(string='CUV', readonly=True, copy=False)
    rips_process_id = fields.Char(string='ID Proceso', readonly=True)
    rips_json_data = fields.Text(string='JSON RIPS', readonly=True)
    rips_validation_errors = fields.Text(string='Errores Validación')
    rips_queued = fields.Boolean(string='En Cola RIPS', default=False)
    rips_attempts = fields.Integer(string='Intentos', default=0)
    
    @api.model
    def action_queue_rips_validation(self):
        """
        Accion para agregar facturas a la cola de validacion RIPS.
        OPTIMIZADO: Mejor manejo de contexto y referencias.
        """
        active_ids = self.env.context.get('active_ids', [])
        invoices = self.browse(active_ids)

        # Filtrar facturas validas
        valid_invoices = invoices.filtered(lambda x:
            x.state == 'posted' and
            x.move_type in ['out_invoice', 'out_refund'] and
            x.rips_estado_validacion not in ['procesando', 'exitoso', 'en_cola']
        )

        if not valid_invoices:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Sin facturas validas'),
                    'message': _('No hay facturas validas para procesar'),
                    'type': 'warning',
                    'sticky': False,
                }
            }

        # Marcar facturas para procesamiento
        valid_invoices.write({
            'rips_queued': True,
            'rips_estado_validacion': 'en_cola',
            'rips_attempts': 0,
            'rips_json_data': False,
            'rips_validation_errors': False,
            'cuv_code': False,
            'rips_process_id': False,
        })

        # OPTIMIZADO: Usar referencia correcta del modulo
        try:
            cron = self.env.ref('l10n_co_rips.ir_cron_process_rips_queue')
            if cron:
                cron.sudo()._trigger()
        except Exception as e:
            _logger.warning(f"No se pudo disparar cron inmediatamente: {str(e)}")

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Procesamiento RIPS'),
                'message': _('%s facturas agregadas a la cola. Se procesaran en segundo plano.') % len(valid_invoices),
                'type': 'success',
                'sticky': False,
            }
        }
    
    @api.model
    def _cron_process_rips_queue(self, batch_size=10, commit_every=3):
        """
        Cron para procesar cola de RIPS.
        OPTIMIZADO: Commits batch, mejor manejo errores, sin referencias hardcoded.
        """
        _logger.info("Iniciando procesamiento de cola RIPS...")

        # Buscar facturas en cola
        invoices = self.search([
            ('rips_queued', '=', True),
            ('rips_estado_validacion', 'in', ['en_cola', 'error']),
            ('rips_attempts', '<', 3)
        ], limit=batch_size, order='id asc')

        if not invoices:
            _logger.info("No hay facturas en cola para procesar")
            return False

        processed = 0
        errors = 0
        success = 0
        total = len(invoices)

        _logger.info(f"Procesando {total} facturas de la cola RIPS")

        for invoice in invoices:
            try:
                # Limpiar datos anteriores si existe el metodo
                if hasattr(invoice, '_reset_rips_data_for_retry'):
                    invoice._reset_rips_data_for_retry()

                # Marcar como procesando
                invoice.write({
                    'rips_estado_validacion': 'procesando',
                    'rips_attempts': invoice.rips_attempts + 1
                })

                # Validar localmente si existe el metodo
                if hasattr(invoice, '_validate_invoice_for_rips'):
                    validation_errors = invoice._validate_invoice_for_rips(invoice)

                    if validation_errors:
                        invoice.write({
                            'rips_estado_validacion': 'error',
                            'rips_validation_errors': json.dumps(validation_errors, ensure_ascii=False),
                            'rips_queued': False
                        })
                        errors += 1
                        _logger.warning(f"Validacion fallida para {invoice.name}")
                        continue

                # Generar JSON - verificar que exista el metodo
                if hasattr(invoice, '_generate_rips_json'):
                    rips_json = invoice._generate_rips_json()
                else:
                    _logger.error(f"Metodo _generate_rips_json no existe para {invoice.name}")
                    invoice.write({
                        'rips_estado_validacion': 'error',
                        'rips_validation_errors': 'Metodo _generate_rips_json no implementado',
                        'rips_queued': False
                    })
                    errors += 1
                    continue

                # Guardar JSON
                invoice.write({
                    'rips_json_data': json.dumps(rips_json, ensure_ascii=False),
                    'rips_estado_validacion': 'generado'
                })

                # Enviar a MinSalud - verificar que exista el metodo
                if hasattr(invoice, '_send_to_minsalud_api'):
                    response = invoice._send_to_minsalud_api(rips_json)
                else:
                    _logger.error(f"Metodo _send_to_minsalud_api no existe para {invoice.name}")
                    invoice.write({
                        'rips_estado_validacion': 'error',
                        'rips_validation_errors': 'Metodo _send_to_minsalud_api no implementado',
                        'rips_queued': False
                    })
                    errors += 1
                    continue

                if response:
                    is_valid = response.get('resultState') or response.get('EsValido', False)
                    cuv = response.get('codigoUnicoValidacion') or response.get('CodigoUnicoValidacion', '')

                    if is_valid and cuv:
                        invoice.write({
                            'rips_estado_validacion': 'exitoso',
                            'cuv_code': cuv,
                            'rips_process_id': str(response.get('ProcessId', '')),
                            'rips_generated': True,
                            'rips_queued': False,
                            'rips_json_data': False
                        })
                        success += 1
                        _logger.info(f"RIPS exitoso para {invoice.name}: CUV {cuv}")
                    else:
                        invoice.write({
                            'rips_estado_validacion': 'error',
                            'rips_validation_errors': json.dumps(response.get('resultadosValidacion', []), ensure_ascii=False),
                            'rips_queued': False
                        })
                        errors += 1
                        _logger.warning(f"RIPS rechazado para {invoice.name}")
                else:
                    invoice.write({
                        'rips_estado_validacion': 'error',
                        'rips_validation_errors': 'No se recibio respuesta del API',
                        'rips_queued': False
                    })
                    errors += 1

                processed += 1

                # OPTIMIZADO: Commit cada N registros
                if processed % commit_every == 0:
                    self.env.cr.commit()
                    _logger.info(f"Progreso: {processed}/{total} procesados")

            except Exception as e:
                _logger.error(f"Excepcion procesando RIPS para {invoice.name}: {str(e)}")
                try:
                    invoice.write({
                        'rips_estado_validacion': 'error',
                        'rips_validation_errors': str(e),
                        'rips_queued': False
                    })
                except:
                    pass
                errors += 1
                continue

        # Commit final
        self.env.cr.commit()

        _logger.info(f"Procesamiento RIPS completado: {success} exitosos, {errors} errores de {processed} procesados")

        # OPTIMIZADO: Verificar si quedan mas facturas sin disparar cron manualmente
        remaining = self.search_count([
            ('rips_queued', '=', True),
            ('rips_estado_validacion', '=', 'en_cola')
        ])

        if remaining > 0:
            _logger.info(f"Quedan {remaining} facturas en cola, el cron seguira ejecutandose")

        return True
    
    def _reset_rips_data_for_retry(self):
        """Limpia datos RIPS para reintentar"""
        self.ensure_one()
        self.write({
            'rips_json_data': False,
            'rips_validation_errors': False,
            'cuv_code': False,
            'rips_process_id': False,
            'rips_generated': False
        })
    
    def action_retry_rips_validation(self):
        """Acción para reintentar validación fallida"""
        failed_invoices = self.filtered(lambda x: x.rips_estado_validacion == 'error')
        
        if failed_invoices:
            failed_invoices.write({
                'rips_queued': True,
                'rips_estado_validacion': 'en_cola',
                'rips_attempts': 0
            })
            
            self.env.ref('tu_modulo.ir_cron_process_rips_queue').sudo()._trigger()
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Reintento RIPS',
                    'message': f'{len(failed_invoices)} facturas agregadas para reintento',
                    'type': 'info',
                    'sticky': False,
                }
            }



class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    authorization_number = fields.Char(string="Numero de autorizacion")
    vat_amount = fields.Float(string="IVA", compute="_compute_vat_amount", store=True)


    @api.depends('tax_ids', 'price_unit', 'quantity', 'discount')
    def _compute_vat_amount(self):
        for line in self:
            vat_total = 0.0
            for tax in line.tax_ids:
                if 'IVA' in tax.name or 'VAT' in tax.name: 
                    vat_total += tax.amount/100 * (line.price_unit * line.quantity * (1 - (line.discount or 0.0) / 100))
            line.vat_amount = vat_total

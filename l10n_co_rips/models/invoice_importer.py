# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import base64
import logging
import io
import json
from datetime import datetime, date
from dateutil.parser import parse
import re
from lxml import etree

_logger = logging.getLogger(__name__)

try:
    import pandas as pd
    import xlrd
    import openpyxl
except ImportError:
    _logger.error("No se puede importar pandas, xlrd o openpyxl")


class InvoiceImporter(models.Model):
    _name = 'invoice.importer'
    _description = "Importador de Facturas y Notas Crédito"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'

    # Campos principales
    name = fields.Char(string="Nombre del Lote", required=True, tracking=True,
                      default=lambda self: _('Importación %s') % fields.Datetime.now())

    state = fields.Selection([
        ('draft', 'Borrador'),
        ('loaded', 'Archivo Cargado'),
        ('processing', 'Procesando'),
        ('done', 'Completado'),
        ('error', 'Con Errores')
    ], string="Estado", default='draft', tracking=True)

    import_type = fields.Selection([
        ('invoice', 'Facturas'),
        ('credit_note', 'Notas Crédito'),
        ('mixed', 'Mixto')
    ], string="Tipo de Importación", default='invoice', required=True, tracking=True)

    # Archivo
    file_data = fields.Binary(string="Archivo", required=True, attachment=True)
    file_name = fields.Char(string="Nombre del Archivo")
    file_type = fields.Selection([
        ('excel', 'Excel'),
        ('csv', 'CSV'),
        ('xml', 'XML'),
        ('json', 'JSON')
    ], string="Tipo de Archivo", compute='_compute_file_type', store=True)

    # Configuración por defecto
    company_id = fields.Many2one('res.company', string="Compañía",
                                 default=lambda self: self.env.company, required=True)
    journal_id = fields.Many2one('account.journal', string="Diario",
                                 domain="[('type', '=', 'sale'), ('company_id', 'in', [company_id, False])]")
    team_id = fields.Many2one('crm.team', string="Equipo de Ventas")

    # Estados por defecto para las facturas
    default_state = fields.Selection([
        ('draft', 'Borrador'),
        ('posted', 'Publicado')
    ], string="Estado por Defecto", default='draft')

    default_payment_state = fields.Selection([
        ('not_paid', 'No Pagado'),
        ('in_payment', 'En Pago'),
        ('paid', 'Pagado'),
        ('partial', 'Parcialmente Pagado')
    ], string="Estado de Pago por Defecto", default='not_paid')

    auto_validate_dian = fields.Boolean(string="Validar automáticamente en DIAN", default=False)
    auto_post_invoices = fields.Boolean(string="Publicar facturas automáticamente", default=True,
                                        help="Publica (confirma) las facturas automáticamente después de crearlas")
    auto_send_rips = fields.Boolean(string="Enviar RIPS automáticamente", default=False,
                                    help="Envía facturas al Ministerio para validación RIPS después de publicarlas")
    create_missing_partners = fields.Boolean(string="Crear clientes faltantes", default=False)

    # Relaciones con líneas de importación
    invoice_line_ids = fields.One2many('invoice.importer.line', 'importer_id',
                                       string="Facturas a Importar")
    credit_note_line_ids = fields.One2many('invoice.importer.credit.line', 'importer_id',
                                           string="Notas Crédito a Importar")

    # Facturas/Notas crédito creadas
    created_invoice_ids = fields.One2many('account.move', 'importer_id',
                                          string="Documentos Creados",
                                          domain=[('move_type', 'in', ['out_invoice', 'out_refund'])])

    # Resultados y errores
    error_log = fields.Html(string="Registro de Errores", readonly=True)
    success_count = fields.Integer(string="Importadas con Éxito", readonly=True, tracking=True)
    error_count = fields.Integer(string="Con Errores", readonly=True, tracking=True)
    total_count = fields.Integer(string="Total a Procesar", compute='_compute_totals', store=True)

    # Análisis de columnas
    column_analysis_html = fields.Html(string="Análisis de Columnas Excel", readonly=True)
    columns_mapped_count = fields.Integer(string="Columnas Mapeadas", readonly=True)
    columns_unmapped_count = fields.Integer(string="Columnas NO Mapeadas", readonly=True)

    # Fechas de proceso
    date_import = fields.Datetime(string="Fecha de Importación")
    user_id = fields.Many2one('res.users', string="Usuario", default=lambda self: self.env.user)

    # Relación con exportaciones RIPS
    rips_export_ids = fields.Many2many('rips.export', 'invoice_importer_rips_export_rel',
                                       'importer_id', 'rips_export_id',
                                       string="Exportaciones RIPS Generadas",
                                       readonly=True)
    rips_export_count = fields.Integer(string="Cant. Exportaciones", compute='_compute_rips_export_count')

    # Contadores de validación DIAN y RIPS
    dian_rejected_count = fields.Integer(
        string="Rechazadas DIAN",
        compute="_compute_validation_counters",
        store=False,
    )
    dian_success_count = fields.Integer(
        string="Exitosas DIAN",
        compute="_compute_validation_counters",
        store=False,
    )
    rips_rejected_count = fields.Integer(
        string="Rechazadas RIPS",
        compute="_compute_validation_counters",
        store=False,
    )
    rips_success_count = fields.Integer(
        string="Exitosas RIPS",
        compute="_compute_validation_counters",
        store=False,
    )

    # Facturas por estado DIAN
    dian_rejected_invoice_ids = fields.Many2many(
        string="Facturas Rechazadas DIAN",
        comodel_name="account.move",
        relation="invoice_importer_dian_rejected_rel",
        column1="importer_id",
        column2="move_id",
        compute="_compute_validation_invoices",
        store=False,
    )
    dian_success_invoice_ids = fields.Many2many(
        string="Facturas Exitosas DIAN",
        comodel_name="account.move",
        relation="invoice_importer_dian_success_rel",
        column1="importer_id",
        column2="move_id",
        compute="_compute_validation_invoices",
        store=False,
    )

    # Facturas por estado RIPS
    rips_rejected_invoice_ids = fields.Many2many(
        string="Facturas Rechazadas RIPS",
        comodel_name="account.move",
        relation="invoice_importer_rips_rejected_rel",
        column1="importer_id",
        column2="move_id",
        compute="_compute_validation_invoices",
        store=False,
    )
    rips_success_invoice_ids = fields.Many2many(
        string="Facturas Exitosas RIPS",
        comodel_name="account.move",
        relation="invoice_importer_rips_success_rel",
        column1="importer_id",
        column2="move_id",
        compute="_compute_validation_invoices",
        store=False,
    )

    # Facturas pendientes por estado
    pending_post_invoice_ids = fields.Many2many(
        string="Pendientes Publicar",
        comodel_name="account.move",
        relation="invoice_importer_pending_post_rel",
        column1="importer_id",
        column2="move_id",
        compute="_compute_validation_invoices",
        store=False,
    )
    pending_post_count = fields.Integer(
        string="Total Pendientes Publicar",
        compute="_compute_validation_invoices",
        store=False,
    )

    pending_dian_invoice_ids = fields.Many2many(
        string="Pendientes Enviar DIAN",
        comodel_name="account.move",
        relation="invoice_importer_pending_dian_rel",
        column1="importer_id",
        column2="move_id",
        compute="_compute_validation_invoices",
        store=False,
    )
    pending_dian_count = fields.Integer(
        string="Total Pendientes DIAN",
        compute="_compute_validation_invoices",
        store=False,
    )

    pending_cuv_invoice_ids = fields.Many2many(
        string="Pendientes Consultar CUV",
        comodel_name="account.move",
        relation="invoice_importer_pending_cuv_rel",
        column1="importer_id",
        column2="move_id",
        compute="_compute_validation_invoices",
        store=False,
    )
    pending_cuv_count = fields.Integer(
        string="Total Pendientes CUV",
        compute="_compute_validation_invoices",
        store=False,
    )

    pending_rips_invoice_ids = fields.Many2many(
        string="Pendientes Enviar RIPS",
        comodel_name="account.move",
        relation="invoice_importer_pending_rips_rel",
        column1="importer_id",
        column2="move_id",
        compute="_compute_validation_invoices",
        store=False,
    )
    pending_rips_count = fields.Integer(
        string="Total Pendientes RIPS",
        compute="_compute_validation_invoices",
        store=False,
    )

    @api.depends('file_name')
    def _compute_file_type(self):
        for record in self:
            if record.file_name:
                ext = record.file_name.lower().split('.')[-1]
                if ext in ['xls', 'xlsx']:
                    record.file_type = 'excel'
                elif ext == 'csv':
                    record.file_type = 'csv'
                elif ext == 'xml':
                    record.file_type = 'xml'
                elif ext == 'json':
                    record.file_type = 'json'
                else:
                    record.file_type = False

    @api.depends('invoice_line_ids', 'credit_note_line_ids')
    def _compute_totals(self):
        for record in self:
            record.total_count = len(record.invoice_line_ids) + len(record.credit_note_line_ids)

    @api.depends('rips_export_ids')
    def _compute_rips_export_count(self):
        for record in self:
            record.rips_export_count = len(record.rips_export_ids)

    @api.depends('created_invoice_ids', 'created_invoice_ids.state_dian_document', 'created_invoice_ids.response_document_dian', 'created_invoice_ids.rips_validation_status')
    def _compute_validation_counters(self):
        """Computa contadores de validación DIAN y RIPS de facturas creadas"""
        for record in self:
            invoices = record.created_invoice_ids

            # Contadores DIAN - usa response_document_dian (aceptado/rechazado)
            record.dian_rejected_count = len(invoices.filtered(lambda inv: inv.response_document_dian == 'rechazado'))
            record.dian_success_count = len(invoices.filtered(lambda inv: inv.response_document_dian == 'aceptado'))

            # Contadores RIPS
            record.rips_rejected_count = len(invoices.filtered(lambda inv: inv.rips_validation_status == 'rejected'))
            record.rips_success_count = len(invoices.filtered(lambda inv: inv.rips_validation_status == 'validated'))

    @api.depends('created_invoice_ids', 'created_invoice_ids.state', 'created_invoice_ids.state_dian_document', 'created_invoice_ids.response_document_dian', 'created_invoice_ids.rips_validation_status')
    def _compute_validation_invoices(self):
        """Computa facturas por estado DIAN, RIPS y pendientes"""
        for record in self:
            invoices = record.created_invoice_ids

            # Facturas DIAN - usa response_document_dian
            record.dian_rejected_invoice_ids = invoices.filtered(lambda inv: inv.response_document_dian == 'rechazado')
            record.dian_success_invoice_ids = invoices.filtered(lambda inv: inv.response_document_dian == 'aceptado')

            # Facturas RIPS
            record.rips_rejected_invoice_ids = invoices.filtered(lambda inv: inv.rips_validation_status == 'rejected')
            record.rips_success_invoice_ids = invoices.filtered(lambda inv: inv.rips_validation_status == 'validated')

            # Facturas pendientes de publicar
            pending_post = invoices.filtered(lambda inv: inv.state == 'draft')
            record.pending_post_invoice_ids = pending_post
            record.pending_post_count = len(pending_post)

            # Facturas pendientes de enviar a DIAN (sin diancode_id o state_dian_document en False)
            pending_dian = invoices.filtered(lambda inv: inv.state == 'posted' and not inv.diancode_id)
            record.pending_dian_invoice_ids = pending_dian
            record.pending_dian_count = len(pending_dian)

            # Facturas pendientes de consultar CUV (enviadas pero sin respuesta)
            pending_cuv = invoices.filtered(lambda inv: inv.state == 'posted' and inv.state_dian_document == 'por_consultar')
            record.pending_cuv_invoice_ids = pending_cuv
            record.pending_cuv_count = len(pending_cuv)

            # Facturas pendientes de enviar RIPS (publicadas y con estado pending o error)
            pending_rips = invoices.filtered(lambda inv:
                inv.state == 'posted' and
                inv.rips_validation_status in ['pending', 'error']
            )
            record.pending_rips_invoice_ids = pending_rips
            record.pending_rips_count = len(pending_rips)

    def action_load_file(self):
        """Carga y analiza el archivo para mostrar preview"""
        self.ensure_one()

        if not self.file_data:
            raise UserError(_("Por favor seleccione un archivo"))

        # Limpiar líneas previas
        self.invoice_line_ids.unlink()
        self.credit_note_line_ids.unlink()

        data = self._parse_file()
        self._create_preview_lines(data)
        self.state = 'loaded'

        # Ejecutar análisis automático de columnas
        self.action_calculate()

        # Log inicial
        self.error_log = f"""
            <div class="alert alert-info">
                <h4>Archivo cargado exitosamente</h4>
                <p>Se encontraron {self.total_count} registros para procesar</p>
                <ul>
                    <li>Facturas: {len(self.invoice_line_ids)}</li>
                    <li>Notas Crédito: {len(self.credit_note_line_ids)}</li>
                </ul>
                <p><strong>Análisis de Columnas:</strong> {self.columns_mapped_count} mapeadas, {self.columns_unmapped_count} sin mapear</p>
            </div>
        """

    def _parse_file(self):
        """Parsea el archivo según su tipo"""
        if self.file_type == 'excel':
            return self._parse_excel()
        elif self.file_type == 'csv':
            return self._parse_csv()
        elif self.file_type == 'xml':
            return self._parse_xml()
        elif self.file_type == 'json':
            return self._parse_json()
        else:
            raise UserError(_("Tipo de archivo no soportado"))

    def _parse_excel(self):
        """
        Parsea archivo Excel.
        OPTIMIZADO: Selecciona automaticamente la primera hoja y mapea columnas correctamente.
        """
        file_data = base64.b64decode(self.file_data)

        # Leer la primera hoja siempre (sheet_name=0)
        df = pd.read_excel(io.BytesIO(file_data), sheet_name=0)

        # Eliminar columnas completamente vacías o con nombres vacíos
        df = df.dropna(axis=1, how='all')  # Eliminar columnas donde TODOS los valores son NaN
        df.columns = [col if pd.notna(col) and str(col).strip() else f'Unnamed_{i}'
                      for i, col in enumerate(df.columns)]

        # Eliminar columnas "Unnamed" que estén vacías
        unnamed_cols = [col for col in df.columns if str(col).startswith('Unnamed_')]
        for col in unnamed_cols:
            if df[col].isna().all():
                df = df.drop(columns=[col])

        # Reemplazar NaN con None
        df = df.where(pd.notnull(df), None)

        # Aplicar mapeo de columnas del Excel a campos internos
        df_mapped = self._map_excel_columns(df)

        return df_mapped.to_dict('records')

    def _normalize_string(self, value):
        """Normaliza strings: minúsculas, sin espacios extra"""
        if not value or not isinstance(value, str):
            return value
        return ' '.join(str(value).lower().strip().split())

    def _map_excel_columns(self, df):
        """
        Mapea las columnas del Excel a los nombres de campos internos.
        OPTIMIZADO: Con normalización y validación completa.
        """
        # NORMALIZAR NOMBRES DE COLUMNAS DEL EXCEL (minúsculas, sin espacios extra)
        df.columns = [self._normalize_string(col) for col in df.columns]

        # Usar mapeo centralizado
        column_mapping = self._get_column_mapping_dict()

        # Validar columnas faltantes y reportar
        missing_columns = []
        found_columns = []

        for excel_col, internal_col in column_mapping.items():
            if excel_col in df.columns:
                found_columns.append(excel_col)
            else:
                missing_columns.append(excel_col)

        if missing_columns:
            _logger.warning(f"Columnas NO encontradas en Excel: {', '.join(missing_columns[:10])}...")

        _logger.info(f"Columnas encontradas: {len(found_columns)}/{len(column_mapping)}")

        # Renombrar columnas
        columns_to_rename = {k: v for k, v in column_mapping.items() if k in df.columns}
        df_renamed = df.rename(columns=columns_to_rename)

        return df_renamed

    def _parse_csv(self):
        """Parsea archivo CSV"""
        file_data = base64.b64decode(self.file_data).decode('utf-8')
        df = pd.read_csv(io.StringIO(file_data))
        df = df.where(pd.notnull(df), None)
        return df.to_dict('records')

    def _parse_xml(self):
        """Parsea archivo XML"""
        file_data = base64.b64decode(self.file_data)
        root = etree.fromstring(file_data)
        data = []

        for invoice in root.xpath('//invoice'):
            invoice_data = {}
            for child in invoice:
                invoice_data[child.tag] = child.text

            # Parsear líneas si existen
            lines = []
            for line in invoice.xpath('.//line'):
                line_data = {}
                for child in line:
                    line_data[child.tag] = child.text
                lines.append(line_data)

            if lines:
                invoice_data['lines'] = lines

            data.append(invoice_data)

        return data

    def _parse_json(self):
        """Parsea archivo JSON"""
        file_data = base64.b64decode(self.file_data).decode('utf-8')
        return json.loads(file_data)

    def _create_preview_lines(self, data):
        """
        Crea líneas de preview desde los datos parseados.
        OPTIMIZADO: Agrupa por id_temp para consolidar líneas de detalle.
        """
        # Agrupar filas por id_temp (facturas) o por identificador único (notas crédito)
        invoices_grouped = {}
        credit_notes_grouped = {}

        for row in data:
            doc_type = row.get('type', 'invoice')

            if self.import_type in ['invoice', 'mixed'] and doc_type == 'invoice':
                # Usar id_temp como clave de agrupación
                id_temp = row.get('id_temp', 'NO_ID')

                if id_temp not in invoices_grouped:
                    invoices_grouped[id_temp] = {
                        'header': row.copy(),  # Datos de cabecera
                        'lines': []  # Líneas de detalle
                    }

                # Agregar esta fila como línea de detalle
                invoices_grouped[id_temp]['lines'].append(row)

            if self.import_type in ['credit_note', 'mixed'] and doc_type == 'credit_note':
                # Para notas crédito, usar referencia como clave
                ref = row.get('origin_invoice', 'NO_REF')

                if ref not in credit_notes_grouped:
                    credit_notes_grouped[ref] = {
                        'header': row.copy(),
                        'lines': []
                    }

                credit_notes_grouped[ref]['lines'].append(row)

        # Crear líneas de preview consolidadas
        for id_temp, invoice_data in invoices_grouped.items():
            self._create_invoice_line_grouped(invoice_data['header'], invoice_data['lines'])

        for ref, credit_data in credit_notes_grouped.items():
            self._create_credit_note_line_grouped(credit_data['header'], credit_data['lines'])

    def _clean_data_for_json(self, data):
        """Convierte datos de Pandas a tipos JSON serializables"""
        cleaned = {}
        for key, value in data.items():
            if pd.isna(value):
                cleaned[key] = None
            elif isinstance(value, pd.Timestamp):
                cleaned[key] = value.isoformat() if pd.notna(value) else None
            elif isinstance(value, (pd.Int64Dtype, pd.Float64Dtype)):
                cleaned[key] = None if pd.isna(value) else value
            else:
                cleaned[key] = value
        return cleaned

    def _create_invoice_line_grouped(self, header_data, lines_data):
        """
        Crea una línea de factura para preview con todas sus líneas de detalle.
        NUEVO: Agrupa cabecera + líneas en raw_data.
        PROPAGACIÓN: El código CIE-10 de la primera línea se propaga a todas las líneas.
        """
        partner = self._find_partner(header_data)

        # Obtener código CIE-10 de la primera línea para propagarlo a todas
        diagnosis_code = None
        if lines_data and lines_data[0].get('diagnosis'):
            diagnosis_code = lines_data[0].get('diagnosis')

        # Buscar diario solo por código
        journal = False
        if header_data.get('journal_code'):
            journal_search = str(header_data['journal_code']).strip()
            journal = self.env['account.journal'].search([
                ('code', '=', journal_search),
                ('company_id', '=', self.company_id.id),
                ('type', '=', 'sale')
            ], limit=1)
        # Si no se encuentra en header_data, usar el del importer
        if not journal and self.journal_id:
            journal = self.journal_id

        # Buscar contrato por código/nombre
        contract = False
        if header_data.get('contract_code'):
            contract_search = str(header_data['contract_code']).strip()
            contract = self.env['customer.contract'].search([
                ('name', '=', contract_search)
            ], limit=1)

        # Tipo de factura
        invoice_type = header_data.get('invoice_type', 'out_invoice')
        if invoice_type not in ['out_invoice', 'out_refund']:
            invoice_type = 'out_invoice'

        # Calcular total sumando todas las líneas
        total_amount = 0
        for line in lines_data:
            qty = float(line.get('quantity', 1)) if line.get('quantity') else 1.0
            price = float(line.get('price_unit', 0)) if line.get('price_unit') else 0.0
            total_amount += qty * price

            # Propagar código CIE-10 a todas las líneas
            if diagnosis_code and not line.get('diagnosis'):
                line['diagnosis'] = diagnosis_code

        # Preparar datos completos para raw_data
        full_data = {
            'header': self._clean_data_for_json(header_data),
            'lines': [self._clean_data_for_json(line) for line in lines_data],
            'lines_count': len(lines_data)
        }

        vals = {
            'importer_id': self.id,
            'partner_id': partner.id if partner else False,
            'partner_vat': header_data.get('partner_vat') or header_data.get('vat', ''),
            'partner_name': header_data.get('partner_name', ''),
            'invoice_date': self._parse_date(header_data.get('invoice_date')),
            'date_due': self._parse_date(header_data.get('date_due')),
            'reference': header_data.get('reference') or header_data.get('id_temp', ''),
            'amount_total': total_amount if total_amount > 0 else float(header_data.get('amount_total', 0)),
            'currency_code': header_data.get('currency', 'COP'),
            'state': self.default_state or header_data.get('state', 'draft'),
            'payment_state': self.default_payment_state or header_data.get('payment_state', 'not_paid'),
            'journal_id': journal.id if journal else False,
            'contract_id': contract.id if contract else False,
            'invoice_type': invoice_type,
            'raw_data': json.dumps(full_data),  # Guardar header + lines
        }

        importer_line = self.env['invoice.importer.line'].create(vals)

        # Crear líneas de detalle
        for seq, line_data in enumerate(lines_data, 1):
            importer_line._create_detail_line(line_data, seq)

    def _create_credit_note_line_grouped(self, header_data, lines_data):
        """
        Crea una línea de nota crédito para preview con todas sus líneas de detalle.
        NUEVO: Agrupa cabecera + líneas en raw_data.
        PROPAGACIÓN: El código CIE-10 de la primera línea se propaga a todas las líneas.
        VALIDACIÓN: Verifica origin_invoice y credit_reason.
        """
        partner = self._find_partner(header_data)

        # VALIDACIÓN: origin_invoice es OBLIGATORIO para notas crédito
        origin_invoice_ref = header_data.get('origin_invoice') or header_data.get('origin_invoice_ref')
        if not origin_invoice_ref:
            _logger.warning(f"Nota crédito sin factura origen: {header_data.get('reference', 'SIN REF')}")

        origin_invoice = self._find_invoice(origin_invoice_ref) if origin_invoice_ref else False

        # Buscar diario solo por código
        journal = False
        if header_data.get('journal_code'):
            journal_search = str(header_data['journal_code']).strip()
            journal = self.env['account.journal'].search([
                ('code', '=', journal_search),
                ('company_id', '=', self.company_id.id),
                ('type', '=', 'sale')
            ], limit=1)
        # Si no se encuentra en header_data, usar el del importer
        if not journal and self.journal_id:
            journal = self.journal_id

        # Obtener código CIE-10 de la primera línea para propagarlo a todas
        diagnosis_code = None
        if lines_data and lines_data[0].get('diagnosis'):
            diagnosis_code = lines_data[0].get('diagnosis')

        # Calcular total sumando todas las líneas
        total_amount = 0
        for line in lines_data:
            qty = float(line.get('quantity', 1)) if line.get('quantity') else 1.0
            price = float(line.get('price_unit', 0)) if line.get('price_unit') else 0.0
            total_amount += qty * price

            # Propagar código CIE-10 a todas las líneas
            if diagnosis_code and not line.get('diagnosis'):
                line['diagnosis'] = diagnosis_code

        # Preparar datos completos para raw_data
        full_data = {
            'header': self._clean_data_for_json(header_data),
            'lines': [self._clean_data_for_json(line) for line in lines_data],
            'lines_count': len(lines_data)
        }

        # Usar credit_reason del Excel
        reason = header_data.get('credit_reason') or header_data.get('reason', '')

        vals = {
            'importer_id': self.id,
            'partner_id': partner.id if partner else False,
            'partner_vat': header_data.get('partner_vat') or header_data.get('vat', ''),
            'partner_name': header_data.get('partner_name', ''),
            'origin_invoice_id': origin_invoice.id if origin_invoice else False,
            'origin_invoice_ref': origin_invoice_ref or '',
            'credit_date': self._parse_date(header_data.get('invoice_date')) or self._parse_date(header_data.get('credit_date')),
            'reason': reason,
            'amount_total': total_amount if total_amount > 0 else float(header_data.get('amount_total', 0)),
            'currency_code': header_data.get('currency', 'COP'),
            'journal_id': journal.id if journal else False,
            'raw_data': json.dumps(full_data),  # Guardar header + lines
        }

        self.env['invoice.importer.credit.line'].create(vals)

    def _find_partner(self, data):
        """Busca un partner por VAT únicamente"""
        Partner = self.env['res.partner']

        # Buscar por VAT (soporta ambas claves: 'vat' y 'partner_vat')
        vat = data.get('partner_vat') or data.get('vat')
        if not vat:
            return False

        vat = str(vat).strip()
        partner = Partner.search([
            '|',
            ('vat', '=', vat),
            ('vat_co', '=', vat)  # Campo VAT de Colombia
        ], limit=1)

        return partner

    def _find_invoice(self, reference):
        """Busca una factura por referencia"""
        if not reference:
            return False

        Move = self.env['account.move']

        # Buscar por name
        invoice = Move.search([
            ('name', '=', reference),
            ('move_type', '=', 'out_invoice'),
            ('company_id', '=', self.company_id.id)
        ], limit=1)

        if not invoice:
            # Buscar por ref
            invoice = Move.search([
                ('ref', '=', reference),
                ('move_type', '=', 'out_invoice'),
                ('company_id', '=', self.company_id.id)
            ], limit=1)

        return invoice

    def _find_payment_term(self, term_name):
        """Busca términos de pago por nombre"""
        if not term_name:
            return False

        return self.env['account.payment.term'].search([
            ('name', 'ilike', str(term_name)),
            '|',
            ('company_id', '=', self.company_id.id),
            ('company_id', '=', False)
        ], limit=1)

    def _find_health_payment_mode(self, code):
        """Busca modalidad de pago por código o nombre"""
        if not code:
            return False

        code_str = str(code).strip()
        # Buscar por código
        result = self.env['health.payment.mode'].search([
            ('code', '=', code_str)
        ], limit=1)

        # Si no encuentra por código, buscar por nombre
        if not result:
            result = self.env['health.payment.mode'].search([
                ('name', 'ilike', code_str)
            ], limit=1)

        return result

    def _find_health_coverage_plan(self, code):
        """Busca plan de cobertura por código o nombre"""
        if not code:
            return False

        code_str = str(code).strip()
        # Buscar por código
        result = self.env['health.coverage.plan'].search([
            ('code', '=', code_str)
        ], limit=1)

        # Si no encuentra por código, buscar por nombre
        if not result:
            result = self.env['health.coverage.plan'].search([
                ('name', 'ilike', code_str)
            ], limit=1)

        return result

    def _find_health_collection_concept(self, code):
        """Busca concepto de recaudo por código"""
        if not code:
            return False

        return self.env['health.collection.concept'].search([
            ('code', '=', str(code).strip())
        ], limit=1)

    def _parse_date(self, date_str):
        """Parsea una fecha desde string"""
        if not date_str:
            return False

        if isinstance(date_str, (date, datetime)):
            return date_str

        # Intentar varios formatos
        for fmt in ['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%Y/%m/%d']:
            try:
                return datetime.strptime(str(date_str), fmt).date()
            except ValueError:
                continue

        # Si ningún formato funciona, usar dateutil
        try:
            return parse(str(date_str)).date()
        except (ValueError, TypeError) as e:
            _logger.warning(f"No se pudo parsear la fecha: {date_str} - Error: {str(e)}")
            return False

    def _map_fe_operation_type(self, value):
        """
        Mapea valores legibles de tipo de operación a códigos válidos.
        Valores válidos en l10n_co_e-invoice:
        - '10': Estandar
        - '09': AIU
        - '11': Mandatos
        - 'SS-CUFE': Factura por servicios + aporte del usuario
        - 'SS-CUDE': Acreditación por Contingencia/NC
        - 'SS-POS': Acreditación por POS
        - 'SS-SNum': Acreditación por Talonario/Papel
        - 'SS-Recaudo': Comprobante de Recaudo
        - 'SS-Reporte': Reporte Informativo
        - 'SS-SinAporte': Factura por servicios sin ningún aporte del usuario
        """
        if not value:
            return '10'  # Default: Estandar

        # Si ya es un código válido, retornarlo
        valid_codes = ['10', '09', '11', 'SS-CUFE', 'SS-CUDE', 'SS-POS',
                      'SS-SNum', 'SS-Recaudo', 'SS-Reporte', 'SS-SinAporte']
        if value in valid_codes:
            return value

        # Mapeo de valores legibles a códigos
        value_upper = str(value).upper().strip()
        mapping = {
            'ESTANDAR': '10',
            'ESTÁNDAR': '10',
            'STANDARD': '10',
            'AIU': '09',
            'MANDATOS': '11',
            'MANDATO': '11',
            'ASEGURADORA': 'SS-CUFE',  # Aseguradoras típicamente con aporte del usuario
            'SALUD': 'SS-CUFE',
            'SALUD CON APORTE': 'SS-CUFE',
            'SS-CUFE': 'SS-CUFE',
            'CUFE': 'SS-CUFE',
            'SALUD SIN APORTE': 'SS-SinAporte',
            'SS-SINAPORTE': 'SS-SinAporte',
            'SS-SIN APORTE': 'SS-SinAporte',
            'CONTINGENCIA': 'SS-CUDE',
            'NOTA CREDITO': 'SS-CUDE',
            'NOTA CRÉDITO': 'SS-CUDE',
            'SS-CUDE': 'SS-CUDE',
            'CUDE': 'SS-CUDE',
            'POS': 'SS-POS',
            'SS-POS': 'SS-POS',
            'TALONARIO': 'SS-SNum',
            'PAPEL': 'SS-SNum',
            'SS-SNUM': 'SS-SNum',
            'RECAUDO': 'SS-Recaudo',
            'SS-RECAUDO': 'SS-Recaudo',
            'REPORTE': 'SS-Reporte',
            'INFORMATIVO': 'SS-Reporte',
            'SS-REPORTE': 'SS-Reporte',
        }

        result = mapping.get(value_upper, '10')  # Default a Estandar si no se encuentra
        if result == '10' and value_upper not in ['ESTANDAR', 'ESTÁNDAR', 'STANDARD']:
            _logger.warning(f"Valor de fe_operation_type no reconocido: '{value}'. Usando 'Estandar' (10) por defecto.")

        return result

    def _map_patient_user_type(self, value):
        """
        Mapea valores legibles de tipo de usuario a códigos válidos.
        Valores válidos en acs_hms:
        - '01': Contributivo cotizante
        - '02': Contributivo beneficiario
        - '03': Contributivo adicional
        - '04': Subsidiado
        - '05': Sin régimen
        - '06': Especiales o de Excepción cotizante
        - '07': Especiales o de Excepción beneficiario
        - '08': Particular
        - '09': Tomador/Amparado ARL
        - '10': Tomador/Amparado SOAT
        - '11': Tomador/Amparado Planes voluntarios de salud
        """
        if not value:
            return False

        # Si ya es un código válido, retornarlo
        valid_codes = ['01', '02', '03', '04', '05', '06', '07', '08', '09', '10', '11']
        if value in valid_codes:
            return value

        # Mapeo de valores legibles a códigos
        value_upper = str(value).upper().strip()
        mapping = {
            'CONTRIBUTIVO COTIZANTE': '01',
            'CONTRIBUTIVO': '01',
            'COTIZANTE': '01',
            'CONTRIBUTIVO BENEFICIARIO': '02',
            'BENEFICIARIO': '02',
            'CONTRIBUTIVO ADICIONAL': '03',
            'ADICIONAL': '03',
            'SUBSIDIADO': '04',
            'SUBSIDIO': '04',
            'SIN REGIMEN': '05',
            'SIN RÉGIMEN': '05',
            'VINCULADO': '05',
            'ESPECIALES COTIZANTE': '06',
            'EXCEPCION COTIZANTE': '06',
            'ESPECIALES O DE EXCEPCIÓN COTIZANTE': '06',
            'ESPECIALES BENEFICIARIO': '07',
            'EXCEPCION BENEFICIARIO': '07',
            'ESPECIALES O DE EXCEPCIÓN BENEFICIARIO': '07',
            'PARTICULAR': '08',
            'PREPAGADA': '08',
            'ARL': '09',
            'TOMADOR ARL': '09',
            'AMPARADO ARL': '09',
            'SOAT': '10',
            'TOMADOR SOAT': '10',
            'AMPARADO SOAT': '10',
            'PLANES VOLUNTARIOS': '11',
            'VOLUNTARIO': '11',
        }

        result = mapping.get(value_upper)
        if not result:
            _logger.warning(f"Valor de patient_user_type no reconocido: '{value}'. Campo quedará vacío.")

        return result

    def _map_patient_doc_type(self, value):
        """
        Mapea valores legibles de tipo de documento a códigos válidos.
        Valores válidos en acs_hms:
        - 'CC': Cédula de Ciudadanía
        - 'TI': Tarjeta de Identidad
        - 'CE': Cédula de Extranjería
        - 'PP': Pasaporte
        - 'RC': Registro Civil
        - 'MS': Menor sin identificación
        - 'AS': Adulto sin identificación
        - 'NU': Número único de identificación
        - 'PE': Permiso especial de permanencia
        - 'SC': Salvoconducto de permanencia
        - 'PT': Permiso por protección temporal
        """
        if not value:
            return False

        # Convertir a string y limpiar
        value_upper = str(value).upper().strip()

        # Si ya es un código válido, retornarlo
        valid_codes = ['CC', 'TI', 'CE', 'PP', 'RC', 'MS', 'AS', 'NU', 'PE', 'SC', 'PT']
        if value_upper in valid_codes:
            return value_upper

        # Mapeo de valores legibles a códigos
        mapping = {
            'CEDULA': 'CC',
            'CÉDULA': 'CC',
            'CEDULA DE CIUDADANIA': 'CC',
            'CÉDULA DE CIUDADANÍA': 'CC',
            'CEDULA CIUDADANIA': 'CC',
            'TARJETA': 'TI',
            'TARJETA DE IDENTIDAD': 'TI',
            'TARJETA IDENTIDAD': 'TI',
            'EXTRANJERIA': 'CE',
            'CEDULA EXTRANJERIA': 'CE',
            'CÉDULA DE EXTRANJERÍA': 'CE',
            'PASAPORTE': 'PP',
            'REGISTRO': 'RC',
            'REGISTRO CIVIL': 'RC',
            'MENOR SIN IDENTIFICACION': 'MS',
            'MENOR SIN IDENTIFICACIÓN': 'MS',
            'ADULTO SIN IDENTIFICACION': 'AS',
            'ADULTO SIN IDENTIFICACIÓN': 'AS',
            'NUIP': 'NU',
            'NUI': 'NU',
            'NUMERO UNICO': 'NU',
            'PEP': 'PE',
            'PERMISO ESPECIAL': 'PE',
            'SALVOCONDUCTO': 'SC',
            'PROTECCION TEMPORAL': 'PT',
            'PERMISO TEMPORAL': 'PT',
            'PPT': 'PT',
        }

        result = mapping.get(value_upper)
        if not result:
            _logger.warning(f"Valor de patient_doc_type no reconocido: '{value}'. Campo quedará vacío.")

        return result

    def _map_patient_gender(self, value):
        """
        Mapea valores legibles de género a códigos válidos.
        Valores válidos en acs_hms:
        - 'M': Hombre
        - 'F': Mujer
        - 'I': Indeterminado o Intersexual
        """
        if not value:
            return False

        value_upper = str(value).upper().strip()

        # Si ya es un código válido, retornarlo
        valid_codes = ['M', 'F', 'I']
        if value_upper in valid_codes:
            return value_upper

        # Mapeo de valores legibles a códigos
        mapping = {
            'MASCULINO': 'M',
            'HOMBRE': 'M',
            'MALE': 'M',
            'H': 'M',
            'FEMENINO': 'F',
            'MUJER': 'F',
            'FEMALE': 'F',
            'INDETERMINADO': 'I',
            'INTERSEXUAL': 'I',
            'OTRO': 'I',
            'NO BINARIO': 'I',
        }

        result = mapping.get(value_upper)
        if not result:
            _logger.warning(f"Valor de patient_gender no reconocido: '{value}'. Campo quedará vacío.")

        return result

    def _map_patient_zone(self, value):
        """
        Mapea valores legibles de zona a códigos válidos.
        Valores válidos en acs_hms:
        - 'urbano': Urbano
        - 'rural': Rural
        """
        if not value:
            return False

        value_lower = str(value).lower().strip()

        # Si ya es un código válido, retornarlo
        if value_lower in ['urbano', 'rural']:
            return value_lower

        # Mapeo de valores legibles a códigos
        mapping = {
            'urbana': 'urbano',
            'ciudad': 'urbano',
            'u': 'urbano',
            'campo': 'rural',
            'r': 'rural',
        }

        result = mapping.get(value_lower)
        if not result:
            _logger.warning(f"Valor de patient_zone no reconocido: '{value}'. Campo quedará vacío.")

        return result

    def action_import(self):
        """
        Ejecuta la importación de facturas y notas crédito.
        SIMPLIFICADO: Procesamiento individual con try-except, commit final único.
        """
        self.ensure_one()
        invoice_lines = self.invoice_line_ids
        if self.state != 'loaded':
            if len(invoice_lines) == 0:
                raise UserError(_("Primero debe cargar el archivo"))

        self.state = 'processing'
        self.date_import = fields.Datetime.now()

        errors = []
        success_count = 0
        error_count = 0
        skipped_count = 0
        duplicate_count = 0

        # PROCESAMIENTO FACTURAS

        total_invoices = len(invoice_lines)

        _logger.info(f"=== INICIANDO IMPORTACIÓN: {total_invoices} facturas ===")

        for idx, line in enumerate(invoice_lines, 1):
            # Omitir si ya tiene factura creada
            if line.invoice_id:
                line.import_status = 'success'
                success_count += 1
                continue

            # Omitir si está marcado para omitir
            if line.skip_import:
                line.import_status = 'skipped'
                skipped_count += 1
                continue

            # Omitir si es duplicado
            if line.is_duplicate:
                line.import_status = 'duplicate'
                line.error_message = f"Ya existe factura {line.existing_invoice_id.name} con este consecutivo"
                duplicate_count += 1
                continue

            # Intentar crear factura
            try:
                invoice = line.create_invoice()
                if invoice:
                    line.invoice_id = invoice
                    line.import_status = 'success'
                    success_count += 1

                    _logger.info(f"Factura {idx}/{total_invoices} creada: {invoice.name}")

                    # Validar en DIAN si está configurado
                    if self.auto_validate_dian and invoice.state == 'posted':
                        try:
                            invoice.validate_dian()
                            _logger.info(f"  DIAN validado para {invoice.name}")
                        except Exception as e:
                            _logger.warning(f"  Error validando DIAN para {invoice.name}: {str(e)}")

            except Exception as e:
                error_count += 1
                error_msg = str(e)[:500]
                errors.append(f"<li><strong>Línea {idx} (ID {line.id}):</strong> {str(e)[:200]}</li>")
                _logger.error(f"Error en factura {idx}/{total_invoices}: {str(e)}")

                # Guardar el error
                try:
                    line.write({
                        'import_status': 'error',
                        'error_message': error_msg
                    })
                except:
                    pass

        # PROCESAMIENTO NOTAS CRÉDITO
        credit_lines = self.credit_note_line_ids
        total_credits = len(credit_lines)

        if total_credits > 0:
            _logger.info(f"=== INICIANDO NOTAS DE CRÉDITO: {total_credits} registros ===")

        for idx, line in enumerate(credit_lines, 1):
            # Omitir si ya tiene nota de crédito creada
            if line.credit_note_id:
                line.import_status = 'success'
                success_count += 1
                continue

            try:
                credit_note = line.create_credit_note()
                if credit_note:
                    line.credit_note_id = credit_note
                    line.import_status = 'success'
                    success_count += 1

                    _logger.info(f"NC {idx}/{total_credits} creada: {credit_note.name}")

                    # Validar en DIAN si está configurado
                    if self.auto_validate_dian and credit_note.state == 'posted':
                        try:
                            credit_note.validate_dian()
                            _logger.info(f"  DIAN validado para {credit_note.name}")
                        except Exception as e:
                            _logger.warning(f"  Error validando DIAN para {credit_note.name}: {str(e)}")

            except Exception as e:
                error_count += 1
                error_msg = str(e)[:500]
                errors.append(f"<li><strong>NC Línea {idx} (ID {line.id}):</strong> {str(e)[:200]}</li>")
                _logger.error(f"Error en NC {idx}/{total_credits}: {str(e)}")

                # Guardar el error
                try:
                    line.write({
                        'import_status': 'error',
                        'error_message': error_msg
                    })
                except:
                    pass

        # Actualizar contadores
        self.success_count = success_count
        self.error_count = error_count

        # Generar log HTML
        total_processed = success_count + error_count + skipped_count + duplicate_count

        # Actualizar estado y log (SIMPLIFICADO: sin savepoint)
        if errors or duplicate_count > 0 or skipped_count > 0:
            self.state = 'error' if error_count == self.total_count else 'done'
            self.error_log = f"""
                <div class="alert alert-{'warning' if success_count > 0 else 'danger'}">
                    <h4>Importación completada con resultados mixtos</h4>
                    <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; margin: 15px 0;">
                        <div style="background: #d4edda; padding: 10px; border-radius: 5px; border: 2px solid #28a745;">
                            <strong style="font-size: 20px; color: #28a745;">{success_count}</strong><br/>
                            <small>Exitosas</small>
                        </div>
                        <div style="background: #f8d7da; padding: 10px; border-radius: 5px; border: 2px solid #dc3545;">
                            <strong style="font-size: 20px; color: #dc3545;">{error_count}</strong><br/>
                            <small>Con Errores</small>
                        </div>
                        <div style="background: #fff3cd; padding: 10px; border-radius: 5px; border: 2px solid #ffc107;">
                            <strong style="font-size: 20px; color: #856404;">{duplicate_count}</strong><br/>
                            <small>Duplicadas</small>
                        </div>
                        <div style="background: #d1ecf1; padding: 10px; border-radius: 5px; border: 2px solid #17a2b8;">
                            <strong style="font-size: 20px; color: #0c5460;">{skipped_count}</strong><br/>
                            <small>Omitidas</small>
                        </div>
                    </div>
                    {'<h5>Detalle de errores:</h5><ul style="max-height: 300px; overflow-y: auto;">' + ''.join(errors) + '</ul>' if errors else ''}
                </div>
            """
        else:
            self.state = 'done'
            self.error_log = f"""
                <div class="alert alert-success">
                    <h4>Importación completada exitosamente</h4>
                    <p>Se importaron <strong>{success_count}</strong> documentos sin errores.</p>
                </div>
            """

        _logger.info(f"Importación finalizada: {success_count} éxitos, {error_count} errores")

    def action_view_invoices(self):
        """Muestra las facturas y notas crédito creadas"""
        self.ensure_one()

        # Obtener todos los documentos creados
        invoices = self.invoice_line_ids.mapped('invoice_id')
        credit_notes = self.credit_note_line_ids.mapped('credit_note_id')
        all_moves = invoices | credit_notes

        return {
            'type': 'ir.actions.act_window',
            'name': _('Documentos Importados'),
            'res_model': 'account.move',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', all_moves.ids)],
            'context': {'create': False},
        }

    def action_calculate(self):
        """
        Analiza TODAS las columnas del Excel y genera reporte HTML.
        Muestra qué columnas están mapeadas y cuáles NO.
        """
        self.ensure_one()

        if not self.file_data:
            raise UserError(_("Por favor cargue un archivo primero"))

        # Leer el Excel para obtener las columnas originales
        file_data = base64.b64decode(self.file_data)
        df_original = pd.read_excel(io.BytesIO(file_data), sheet_name=0)

        # Eliminar columnas completamente vacías o con nombres vacíos
        df_original = df_original.dropna(axis=1, how='all')
        df_original.columns = [col if pd.notna(col) and str(col).strip() else f'Unnamed_{i}'
                               for i, col in enumerate(df_original.columns)]

        # Eliminar columnas "Unnamed" que estén vacías
        unnamed_cols = [col for col in df_original.columns if str(col).startswith('Unnamed_')]
        for col in unnamed_cols:
            if df_original[col].isna().all():
                df_original = df_original.drop(columns=[col])

        original_columns = df_original.columns.tolist()

        # Normalizar columnas
        normalized_columns = [self._normalize_string(col) for col in original_columns]

        # Obtener mapeo de columnas
        column_mapping = self._get_column_mapping_dict()

        # Clasificar columnas
        mapped_columns = []
        unmapped_columns = []

        for i, (orig_col, norm_col) in enumerate(zip(original_columns, normalized_columns)):
            if norm_col in column_mapping:
                mapped_columns.append({
                    'original': orig_col,
                    'normalized': norm_col,
                    'mapped_to': column_mapping[norm_col],
                    'index': i + 1
                })
            else:
                unmapped_columns.append({
                    'original': orig_col,
                    'normalized': norm_col,
                    'index': i + 1
                })

        # Actualizar contadores
        self.columns_mapped_count = len(mapped_columns)
        self.columns_unmapped_count = len(unmapped_columns)

        # Generar HTML detallado
        html = self._generate_column_analysis_html(mapped_columns, unmapped_columns, df_original)
        self.column_analysis_html = html

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Análisis Completado'),
                'message': _(f'Se analizaron {len(original_columns)} columnas: {len(mapped_columns)} mapeadas, {len(unmapped_columns)} sin mapear'),
                'type': 'success',
                'sticky': False,
            }
        }

    def _get_column_mapping_dict(self):
        """Retorna el diccionario de mapeo de columnas"""
        return {
            # Campos de cabecera de factura
            'id factura temporal': 'id_temp',
            'cliente nit/id': 'partner_vat',
            'fecha factura': 'invoice_date',
            'fecha vencimiento': 'date_due',
            'número factura': 'invoice_number',
            'numero factura': 'invoice_number',
            'consecutivo': 'invoice_number',
            'diario código': 'journal_code',
            'diario': 'journal_code',
            'contrato código': 'contract_code',
            'contrato': 'contract_code',
            'tipo factura': 'invoice_type',
            'tipo': 'invoice_type',
            'numero ingreso': 'x_ingreso',
            'términos de pago nombre': 'payment_term_name',
            'tipo operación fe código': 'fe_operation_type',
            'tipo factura salud código': 'health_invoice_type',
            'fecha inicio periodo servicio': 'service_period_start',
            'fecha fin periodo servicio': 'service_period_end',
            'modalidad pago salud código': 'health_payment_mode',
            'cobertura salud código': 'health_coverage',
            'factura original recaudo número': 'origin_invoice_ref',
            'factura origen': 'origin_invoice',
            'origen factura': 'origin_invoice',
            'motivo nota crédito': 'credit_reason',
            'motivo': 'credit_reason',
            'razón anulación': 'credit_reason',
            'número mipres general': 'mipres_number',
            'número entrega mipres general': 'mipres_delivery_number',

            # Campos de línea de factura
            'producto/servicio código/nombre': 'product_code',
            'descripción detallada línea': 'line_description',
            'diagnostico': 'diagnosis',
            'diagnóstico': 'diagnosis',
            'paciente id/cédula - línea': 'patient_document',
            'paciente/nombre': 'patient_name',
            'ciudad': 'patient_city',
            'nacialidad': 'patient_nationality',
            'nacionalidad': 'patient_nationality',
            'pais': 'patient_country',
            'país': 'patient_country',
            'tipo de usuario': 'patient_user_type',
            'zona': 'patient_zone',
            'fecha de nacimineto': 'patient_birth_date',
            'fecha de nacimiento': 'patient_birth_date',
            'tipo de documento paciente': 'patient_doc_type',
            'número autorización línea': 'authorization_number',
            'genero': 'patient_gender',
            'género': 'patient_gender',
            'contrato nombre/id - línea': 'contract_ref',
            'cantidad': 'quantity',
            'precio unitario': 'price_unit',
            'impuestos nombres': 'tax_names',
            'cuenta contable código': 'account_code',
            'fecha atención línea': 'service_date',
        }

    def _generate_column_analysis_html(self, mapped_columns, unmapped_columns, df_sample):
        """Genera el HTML del análisis de columnas"""

        html = """
        <style>
            .column-analysis {{
                font-family: Arial, sans-serif;
                padding: 20px;
                background: #f8f9fa;
            }}
            .analysis-header {{
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 20px;
                border-radius: 10px 10px 0 0;
                margin-bottom: 0;
            }}
            .analysis-header h2 {{
                margin: 0;
                font-size: 24px;
            }}
            .analysis-summary {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 15px;
                padding: 20px;
                background: white;
                border-left: 3px solid #667eea;
                border-right: 3px solid #667eea;
            }}
            .summary-card {{
                padding: 15px;
                border-radius: 8px;
                text-align: center;
            }}
            .summary-card.success {{
                background: #d4edda;
                border: 2px solid #28a745;
            }}
            .summary-card.warning {{
                background: #fff3cd;
                border: 2px solid #ffc107;
            }}
            .summary-card.info {{
                background: #d1ecf1;
                border: 2px solid #17a2b8;
            }}
            .summary-card h3 {{
                margin: 0 0 10px 0;
                font-size: 32px;
                font-weight: bold;
            }}
            .summary-card p {{
                margin: 0;
                color: #666;
                font-size: 14px;
            }}
            .columns-section {{
                margin-top: 0;
                background: white;
                border-radius: 0 0 10px 10px;
                border: 3px solid #667eea;
                border-top: none;
                overflow: hidden;
            }}
            .section-header {{
                padding: 15px 20px;
                font-size: 18px;
                font-weight: bold;
                color: white;
                margin: 0;
            }}
            .section-header.mapped {{
                background: #28a745;
            }}
            .section-header.unmapped {{
                background: #dc3545;
            }}
            .columns-table {{
                width: 100%;
                border-collapse: collapse;
                margin: 0;
            }}
            .columns-table th {{
                background: #f1f3f5;
                padding: 12px;
                text-align: left;
                font-weight: 600;
                border-bottom: 2px solid #dee2e6;
                font-size: 13px;
                color: #495057;
            }}
            .columns-table td {{
                padding: 10px 12px;
                border-bottom: 1px solid #dee2e6;
                font-size: 13px;
            }}
            .columns-table tr:hover {{
                background: #f8f9fa;
            }}
            .badge {{
                display: inline-block;
                padding: 4px 10px;
                border-radius: 12px;
                font-size: 11px;
                font-weight: 600;
                text-transform: uppercase;
            }}
            .badge.success {{
                background: #28a745;
                color: white;
            }}
            .badge.danger {{
                background: #dc3545;
                color: white;
            }}
            .badge.info {{
                background: #17a2b8;
                color: white;
            }}
            .code {{
                font-family: 'Courier New', monospace;
                background: #f8f9fa;
                padding: 2px 6px;
                border-radius: 3px;
                font-size: 12px;
                border: 1px solid #dee2e6;
            }}
            .sample-values {{
                font-size: 11px;
                color: #6c757d;
                font-style: italic;
                max-width: 300px;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }}
        </style>

        <div class="column-analysis">
            <div class="analysis-header">
                <h2>📊 Análisis de Columnas del Excel</h2>
                <p style="margin: 10px 0 0 0; opacity: 0.9;">Validación completa del archivo importado</p>
            </div>

            <div class="analysis-summary">
                <div class="summary-card info">
                    <h3>{total}</h3>
                    <p>Total de Columnas</p>
                </div>
                <div class="summary-card success">
                    <h3>{mapped}</h3>
                    <p>Mapeadas Correctamente</p>
                </div>
                <div class="summary-card warning">
                    <h3>{unmapped}</h3>
                    <p>Sin Mapear</p>
                </div>
                <div class="summary-card info">
                    <h3>{percentage}%</h3>
                    <p>Tasa de Éxito</p>
                </div>
            </div>
        """.format(
            total=len(mapped_columns) + len(unmapped_columns),
            mapped=len(mapped_columns),
            unmapped=len(unmapped_columns),
            percentage=round((len(mapped_columns) / (len(mapped_columns) + len(unmapped_columns)) * 100) if (len(mapped_columns) + len(unmapped_columns)) > 0 else 0, 1)
        )

        # Tabla de columnas MAPEADAS
        if mapped_columns:
            html += """
            <div class="columns-section">
                <h3 class="section-header mapped">Columnas Mapeadas ({count})</h3>
                <table class="columns-table">
                    <thead>
                        <tr>
                            <th style="width: 50px;">#</th>
                            <th>Columna Original</th>
                            <th>Normalizada</th>
                            <th>Campo Odoo</th>
                            <th>Ejemplo de Datos</th>
                            <th style="width: 100px;">Estado</th>
                        </tr>
                    </thead>
                    <tbody>
            """.format(count=len(mapped_columns))

            for col in mapped_columns:
                # Obtener muestra de datos
                sample_data = ""
                try:
                    col_name = col['original']
                    if col_name in df_sample.columns:
                        sample_values = df_sample[col_name].dropna().head(3).tolist()
                        sample_data = ", ".join([str(v)[:30] for v in sample_values])
                except:
                    sample_data = "N/A"

                html += """
                    <tr>
                        <td><strong>{index}</strong></td>
                        <td>{original}</td>
                        <td><span class="code">{normalized}</span></td>
                        <td><span class="code">{mapped_to}</span></td>
                        <td><div class="sample-values">{sample}</div></td>
                        <td><span class="badge success">Mapeada</span></td>
                    </tr>
                """.format(
                    index=col['index'],
                    original=col['original'],
                    normalized=col['normalized'],
                    mapped_to=col['mapped_to'],
                    sample=sample_data if sample_data else "Sin datos"
                )

            html += """
                    </tbody>
                </table>
            </div>
            """

        # Tabla de columnas NO MAPEADAS
        if unmapped_columns:
            html += """
            <div class="columns-section" style="margin-top: 20px;">
                <h3 class="section-header unmapped">Columnas NO Mapeadas ({count})</h3>
                <table class="columns-table">
                    <thead>
                        <tr>
                            <th style="width: 50px;">#</th>
                            <th>Columna Original</th>
                            <th>Normalizada</th>
                            <th>Ejemplo de Datos</th>
                            <th style="width: 100px;">Estado</th>
                        </tr>
                    </thead>
                    <tbody>
            """.format(count=len(unmapped_columns))

            for col in unmapped_columns:
                # Obtener muestra de datos
                sample_data = ""
                try:
                    col_name = col['original']
                    if col_name in df_sample.columns:
                        sample_values = df_sample[col_name].dropna().head(3).tolist()
                        sample_data = ", ".join([str(v)[:30] for v in sample_values])
                except:
                    sample_data = "N/A"

                html += """
                    <tr>
                        <td><strong>{index}</strong></td>
                        <td>{original}</td>
                        <td><span class="code">{normalized}</span></td>
                        <td><div class="sample-values">{sample}</div></td>
                        <td><span class="badge danger">Sin Mapear</span></td>
                    </tr>
                """.format(
                    index=col['index'],
                    original=col['original'],
                    normalized=col['normalized'],
                    sample=sample_data if sample_data else "Sin datos"
                )

            html += """
                    </tbody>
                </table>
            </div>
            """

        html += """
        </div>
        """

        return html

    def action_reset_lines_only(self):
        """
        Resetea solo las líneas SIN borrar el archivo adjunto.
        Útil para cuando se corrige manualmente el Excel y se necesita recargar.
        """
        self.ensure_one()

        # Eliminar solo las líneas de detalle de cada factura/NC
        for line in self.invoice_line_ids:
            line.detail_line_ids.unlink()

        for line in self.credit_note_line_ids:
            pass  # Las NC no tienen detail_line_ids por ahora

        # Limpiar líneas de importación pero mantener archivo
        self.invoice_line_ids.unlink()
        self.credit_note_line_ids.unlink()

        # Resetear solo contadores, mantener archivo
        self.write({
            'state': 'draft',
            'error_log': False,
            'success_count': 0,
            'error_count': 0,
            'column_analysis_html': False,
            'columns_mapped_count': 0,
            'columns_unmapped_count': 0,
        })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Líneas Reseteadas'),
                'message': _('Las líneas se eliminaron. El archivo se mantuvo. Puede volver a cargar.'),
                'type': 'success',
                'sticky': False,
            }
        }

    def action_reset(self):
        """Resetea el importador COMPLETO para nueva carga"""
        self.ensure_one()

        # Limpiar líneas
        self.invoice_line_ids.unlink()
        self.credit_note_line_ids.unlink()

        # Resetear campos INCLUYENDO archivo
        self.write({
            'state': 'draft',
            'error_log': False,
            'success_count': 0,
            'error_count': 0,
            'date_import': False,
            'file_data': False,
            'file_name': False,
            'column_analysis_html': False,
            'columns_mapped_count': 0,
            'columns_unmapped_count': 0,
        })

    def action_retry_dian_rejected(self):
        """Reintenta enviar a DIAN todas las facturas rechazadas"""
        self.ensure_one()
        rejected = self.dian_rejected_invoice_ids

        if not rejected:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Sin Facturas'),
                    'message': _('No hay facturas rechazadas por DIAN'),
                    'type': 'warning',
                }
            }

        success_count = 0
        error_count = 0

        for invoice in rejected:
            try:
                if invoice.state == 'draft':
                    invoice.action_post()
                # validate_dian está en l10n_co_e-invoice
                invoice.validate_dian()
                success_count += 1
            except Exception as e:
                error_count += 1
                _logger.error(f"Error reenviando factura {invoice.name} a DIAN: {str(e)}")

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Reenvío DIAN Completado'),
                'message': _(f'Exitosas: {success_count}, Errores: {error_count}'),
                'type': 'success' if error_count == 0 else 'warning',
            }
        }

    def action_retry_rips_rejected(self):
        """Reintenta enviar a RIPS todas las facturas rechazadas"""
        self.ensure_one()
        rejected = self.rips_rejected_invoice_ids

        if not rejected:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Sin Facturas'),
                    'message': _('No hay facturas rechazadas en RIPS'),
                    'type': 'warning',
                }
            }

        success_count = 0
        error_count = 0

        for invoice in rejected:
            try:
                # action_send_rips está en l10n_co_rips
                invoice.action_send_rips()
                success_count += 1
            except Exception as e:
                error_count += 1
                _logger.error(f"Error reenviando factura {invoice.name} a RIPS: {str(e)}")

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Reenvío RIPS Completado'),
                'message': _(f'Exitosas: {success_count}, Errores: {error_count}'),
                'type': 'success' if error_count == 0 else 'warning',
            }
        }

    def action_post_pending(self):
        """Publica todas las facturas pendientes"""
        self.ensure_one()
        pending = self.pending_post_invoice_ids

        if not pending:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Sin Facturas'),
                    'message': _('No hay facturas pendientes de publicar'),
                    'type': 'warning',
                }
            }

        success_count = 0
        error_count = 0

        for invoice in pending:
            try:
                invoice.action_post()
                success_count += 1
            except Exception as e:
                error_count += 1
                _logger.error(f"Error publicando factura {invoice.name}: {str(e)}")

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Publicación Completada'),
                'message': _(f'Publicadas: {success_count}, Errores: {error_count}'),
                'type': 'success' if error_count == 0 else 'warning',
            }
        }

    def action_send_dian_pending(self):
        """Envía a DIAN todas las facturas pendientes"""
        self.ensure_one()
        pending = self.pending_dian_invoice_ids

        if not pending:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Sin Facturas'),
                    'message': _('No hay facturas pendientes de enviar a DIAN'),
                    'type': 'warning',
                }
            }

        success_count = 0
        error_count = 0

        for invoice in pending:
            try:
                # validate_dian está en l10n_co_e-invoice
                invoice.validate_dian()
                success_count += 1
            except Exception as e:
                error_count += 1
                _logger.error(f"Error enviando factura {invoice.name} a DIAN: {str(e)}")

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Envío DIAN Completado'),
                'message': _(f'Enviadas: {success_count}, Errores: {error_count}'),
                'type': 'success' if error_count == 0 else 'warning',
            }
        }

    def action_check_cuv_pending(self):
        """Consulta CUV de todas las facturas pendientes"""
        self.ensure_one()
        pending = self.pending_cuv_invoice_ids

        if not pending:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Sin Facturas'),
                    'message': _('No hay facturas pendientes de consultar CUV'),
                    'type': 'warning',
                }
            }

        success_count = 0
        error_count = 0

        for invoice in pending:
            try:
                # check_dian_status está en l10n_co_e-invoice
                invoice.check_dian_status()
                success_count += 1
            except Exception as e:
                error_count += 1
                _logger.error(f"Error consultando CUV de factura {invoice.name}: {str(e)}")

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Consulta CUV Completada'),
                'message': _(f'Consultadas: {success_count}, Errores: {error_count}'),
                'type': 'success' if error_count == 0 else 'warning',
            }
        }

    def action_send_rips_pending(self):
        """Envía a RIPS todas las facturas publicadas pendientes"""
        self.ensure_one()
        pending = self.pending_post_invoice_ids.filtered(lambda inv: inv.state == 'posted')

        if not pending:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Sin Facturas'),
                    'message': _('No hay facturas publicadas pendientes de enviar a RIPS'),
                    'type': 'warning',
                }
            }

        success_count = 0
        error_count = 0

        for invoice in pending:
            try:
                # action_send_rips está en l10n_co_rips
                invoice.action_send_rips()
                success_count += 1
            except Exception as e:
                error_count += 1
                _logger.error(f"Error enviando factura {invoice.name} a RIPS: {str(e)}")

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Envío RIPS Completado'),
                'message': _(f'Enviadas: {success_count}, Errores: {error_count}'),
                'type': 'success' if error_count == 0 else 'warning',
            }
        }

    def action_send_rips_batch(self):
        """Envía RIPS de todas las facturas creadas en lotes"""
        self.ensure_one()

        # Obtener facturas creadas que aún no han sido enviadas
        pending_lines = self.invoice_line_ids.filtered(
            lambda l: l.invoice_id and l.rips_validation_status == 'pending'
        )

        if not pending_lines:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Sin Facturas Pendientes'),
                    'message': _('No hay facturas pendientes para enviar a RIPS'),
                    'type': 'warning',
                    'sticky': False,
                }
            }

        # Marcar como en cola
        pending_lines.write({'rips_validation_status': 'queued'})

        # Procesar envío RIPS (procesamiento por lotes con commits)
        self._process_rips_queue(pending_lines.ids)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Envío RIPS Iniciado'),
                'message': _(f'Se enviaron {len(pending_lines)} facturas a la cola de RIPS'),
                'type': 'success',
                'sticky': False,
            }
        }

    def _process_rips_queue(self, line_ids):
        """Procesa la cola de envío RIPS (llamado en background)"""
        lines = self.env['invoice.importer.line'].browse(line_ids)
        batch_size = 10

        for i in range(0, len(lines), batch_size):
            batch = lines[i:i+batch_size]

            for line in batch:
                try:
                    line._send_rips_to_ministerio()
                except Exception as e:
                    line.write({
                        'rips_validation_status': 'error',
                        'rips_error_message': str(e)
                    })
                    _logger.error(f"Error enviando RIPS para línea {line.id}: {str(e)}")

            # Commit cada lote
            self.env.cr.commit()

    def action_generate_rips_export(self):
        """Genera archivo ZIP con todos los RIPS de las facturas importadas usando rips.export"""
        self.ensure_one()

        # Obtener facturas con RIPS validados
        invoices = self.invoice_line_ids.mapped('invoice_id').filtered(
            lambda inv: inv.rips_validation_status == 'validated'
        )

        if not invoices:
            raise UserError(_("No hay facturas con RIPS validados para exportar"))

        # Crear rips.export
        rips_export = self.env['rips.export'].create({
            'name': f'RIPS Importación - {self.name}',
            'date': fields.Date.today(),
            'move_ids': [(6, 0, invoices.ids)],
            'state': 'draft',
        })

        # Generar ZIP
        try:
            rips_export.generate_zip()
            rips_export.state = 'generated'
        except Exception as e:
            raise UserError(_(f"Error generando ZIP: {str(e)}"))

        # Vincular exportación con este importador
        self.write({'rips_export_ids': [(4, rips_export.id)]})

        return {
            'type': 'ir.actions.act_window',
            'name': _('Exportación RIPS'),
            'res_model': 'rips.export',
            'res_id': rips_export.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_rips_exports(self):
        """Muestra todas las exportaciones RIPS generadas desde este importador"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Exportaciones RIPS'),
            'res_model': 'rips.export',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', self.rips_export_ids.ids)],
            'context': {'create': False},
        }

    def action_download_excel_template(self):
        """
        Redirige a la URL del controlador HTTP para descargar la plantilla Excel.
        SOLUCIÓN: Usa controlador HTTP para evitar problemas de memoria.
        """
        return {
            'type': 'ir.actions.act_url',
            'url': '/l10n_co_rips/download_template',
            'target': 'self',
        }


class InvoiceImporterLine(models.Model):
    _name = 'invoice.importer.line'
    _description = "Línea de Importación de Factura"
    _order = 'id'

    importer_id = fields.Many2one('invoice.importer', string="Importador",
                                 required=True, ondelete='cascade')

    # Datos del partner
    partner_id = fields.Many2one('res.partner', string="Cliente")
    partner_vat = fields.Char(string="NIT/CC")
    partner_name = fields.Char(string="Nombre Cliente")

    # Datos de la factura
    invoice_date = fields.Date(string="Fecha Factura")
    date_due = fields.Date(string="Fecha Vencimiento")
    reference = fields.Char(
        string="Referencia",
        compute='_compute_reference',
        store=True,
        readonly=False
    )
    amount_total = fields.Float(string="Total")
    currency_code = fields.Char(string="Moneda", default='COP')

    # Configuración de factura (desde Excel o por defecto desde importer_id)
    journal_id = fields.Many2one('account.journal', string="Diario",
                                 domain="[('type', '=', 'sale')]")
    contract_id = fields.Many2one('customer.contract', string="Contrato", required=False, ondelete='set null')
    invoice_type = fields.Selection([
        ('out_invoice', 'Factura de Cliente'),
        ('out_refund', 'Nota de Crédito'),
    ], string="Tipo de Factura", default='out_invoice')

    # Gestión de líneas de detalle
    detail_line_ids = fields.One2many('invoice.importer.detail.line', 'importer_line_id',
                                      string="Líneas de Detalle")
    line_count = fields.Integer(string="Cantidad de Líneas", compute='_compute_line_count', store=True)
    missing_products_count = fields.Integer(string="Productos Faltantes", compute='_compute_missing_products', store=True)
    validation_alerts = fields.Html(string="Alertas de Validación", compute='_compute_validation_alerts', store=True)

    # Estado de validación RIPS
    rips_validation_status = fields.Selection([
        ('pending', 'Pendiente de Envío'),
        ('queued', 'En Cola'),
        ('sending', 'Enviando'),
        ('sent', 'Enviado'),
        ('validated', 'Validado'),
        ('error', 'Error')
    ], string="Estado RIPS", default='pending', tracking=True)

    rips_send_date = fields.Datetime(string="Fecha Envío RIPS", readonly=True)
    rips_error_message = fields.Text(string="Error RIPS")

    # Estados configurables
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('posted', 'Publicado')
    ], string="Estado", default='draft')

    payment_state = fields.Selection([
        ('not_paid', 'No Pagado'),
        ('in_payment', 'En Pago'),
        ('paid', 'Pagado'),
        ('partial', 'Parcialmente Pagado')
    ], string="Estado de Pago", default='not_paid')

    # Resultado de importación
    import_status = fields.Selection([
        ('pending', 'Pendiente'),
        ('success', 'Exitoso'),
        ('error', 'Error'),
        ('duplicate', 'Duplicado'),
        ('skipped', 'Omitido')
    ], string="Estado Importación", default='pending')

    error_message = fields.Text(string="Mensaje de Error")
    invoice_id = fields.Many2one('account.move', string="Factura Creada", readonly=True)

    # Control de omisión
    skip_import = fields.Boolean(string="Omitir Importación", default=False,
                                 help="Si está marcado, esta línea NO se importará")
    is_duplicate = fields.Boolean(string="Es Duplicado", compute='_compute_is_duplicate', store=True,
                                  help="Indica si ya existe una factura con este consecutivo")
    existing_invoice_id = fields.Many2one('account.move', string="Factura Existente", readonly=True,
                                         help="Factura existente con el mismo consecutivo")

    # Datos crudos del archivo
    raw_data = fields.Text(string="Datos Crudos")

    @api.depends('raw_data')
    def _compute_line_count(self):
        """Calcula la cantidad de líneas de detalle"""
        for record in self:
            if record.raw_data:
                try:
                    data = json.loads(record.raw_data)
                    record.line_count = data.get('lines_count', 0) if isinstance(data, dict) else 0
                except:
                    record.line_count = 0
            else:
                record.line_count = 0

    @api.depends('partner_id', 'partner_id.ref')
    def _compute_reference(self):
        """Genera referencia automática: CÓDIGO_PARTNER + SECUENCIAL"""
        for record in self:
            # Si ya tiene referencia manual y no es temporal, respetarla
            if record.reference and not record.reference.startswith('TEMP-'):
                continue

            # Generar nueva referencia
            partner_code = ''
            if record.partner_id and record.partner_id.ref:
                partner_code = record.partner_id.ref.strip().upper()
            elif record.partner_vat:
                # Usar últimos 4 dígitos del NIT si no tiene ref
                partner_code = record.partner_vat[-4:] if len(record.partner_vat) >= 4 else record.partner_vat

            # Generar secuencial
            if partner_code and record.partner_id:
                # Buscar último consecutivo para este partner en este importador
                domain = [
                    ('importer_id', '=', record.importer_id.id),
                    ('partner_id', '=', record.partner_id.id),
                    ('reference', '=like', f'{partner_code}-%')
                ]

                # Excluir registro actual solo si tiene ID
                if record.id:
                    domain.append(('id', '!=', record.id))

                last_line = self.env['invoice.importer.line'].search(
                    domain,
                    order='id desc',
                    limit=1
                )

                if last_line and last_line.reference:
                    # Extraer número del último consecutivo
                    try:
                        last_num = int(last_line.reference.split('-')[-1])
                        next_num = last_num + 1
                    except:
                        next_num = 1
                else:
                    next_num = 1

                # Formato: CODIGO-00001
                record.reference = f'{partner_code}-{next_num:05d}'
            else:
                # Sin código de partner, generar temporal basado en timestamp
                import time
                timestamp = int(time.time() * 1000) % 100000  # Últimos 5 dígitos de timestamp
                record.reference = f'TEMP-{timestamp:05d}'

    @api.depends('detail_line_ids.product_id')
    def _compute_missing_products(self):
        """Cuenta productos faltantes en las líneas"""
        for record in self:
            record.missing_products_count = len(record.detail_line_ids.filtered(lambda l: not l.product_id))

    @api.depends('reference', 'partner_id')
    def _compute_is_duplicate(self):
        """Verifica si ya existe una factura con el mismo consecutivo"""
        for record in self:
            if record.reference and record.partner_id:
                existing = self.env['account.move'].search([
                    ('name', '=', record.reference),
                    ('partner_id', '=', record.partner_id.id),
                    ('move_type', '=', 'out_invoice'),
                    ('company_id', '=', record.importer_id.company_id.id)
                ], limit=1)

                record.is_duplicate = bool(existing)
                record.existing_invoice_id = existing.id if existing else False

                # Auto-marcar como duplicado si se encuentra
                if existing and not record.invoice_id:
                    record.import_status = 'duplicate'
            else:
                record.is_duplicate = False
                record.existing_invoice_id = False

    @api.depends('detail_line_ids.product_id', 'detail_line_ids.tax_ids', 'detail_line_ids.validation_errors')
    def _compute_validation_alerts(self):
        """Genera alertas HTML con todos los problemas detectados"""
        for record in self:
            alerts = []

            # Productos faltantes
            missing_products = record.detail_line_ids.filtered(lambda l: not l.product_id)
            if missing_products:
                codes = ', '.join([l.product_code for l in missing_products if l.product_code][:5])
                if len(missing_products) > 5:
                    codes += f'... (+{len(missing_products)-5} más)'
                alerts.append({
                    'type': 'danger',
                    'icon': 'fa-exclamation-circle',
                    'title': f'{len(missing_products)} Productos NO Encontrados',
                    'message': f'Códigos: {codes}'
                })

            # Líneas sin impuestos
            no_tax = record.detail_line_ids.filtered(lambda l: l.product_id and not l.tax_ids)
            if no_tax:
                alerts.append({
                    'type': 'warning',
                    'icon': 'fa-exclamation-triangle',
                    'title': f'{len(no_tax)} Líneas Sin Impuestos',
                    'message': 'Estas líneas requieren impuestos (19% o 5%)'
                })

            # Errores de validación
            with_errors = record.detail_line_ids.filtered(lambda l: l.validation_errors)
            if with_errors:
                alerts.append({
                    'type': 'warning',
                    'icon': 'fa-info-circle',
                    'title': f'{len(with_errors)} Líneas Con Errores',
                    'message': 'Revise los errores de validación de edad/documento'
                })

            # Pacientes sin datos
            no_patient = record.detail_line_ids.filtered(lambda l: not l.patient_id and not l.patient_document)
            if no_patient:
                alerts.append({
                    'type': 'info',
                    'icon': 'fa-user',
                    'title': f'{len(no_patient)} Líneas Sin Paciente',
                    'message': 'Estas líneas no tienen información de paciente (opcional)'
                })

            # Generar HTML
            if alerts:
                html = '<div style="padding: 10px;">'
                for alert in alerts:
                    html += f'''
                    <div class="alert alert-{alert['type']}" role="alert" style="margin-bottom: 10px;">
                        <i class="fa {alert['icon']}"></i>
                        <strong>{alert['title']}</strong><br/>
                        {alert['message']}
                    </div>
                    '''
                html += '</div>'
                record.validation_alerts = html
            else:
                record.validation_alerts = '<div class="alert alert-success"><i class="fa fa-check"></i> <strong>Todo correcto</strong> - No hay alertas</div>'

    def action_view_detail_lines(self):
        """Muestra las líneas de detalle de esta factura"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Líneas de Detalle - {self.reference or self.partner_name}',
            'res_model': 'invoice.importer.detail.line',
            'view_mode': 'tree,form',
            'domain': [('importer_line_id', '=', self.id)],
            'context': {
                'default_importer_line_id': self.id,
                'create': False,
            },
        }

    def action_refresh_lines(self):
        """Recarga las líneas de detalle desde raw_data"""
        self.ensure_one()

        # Eliminar líneas existentes
        self.detail_line_ids.unlink()

        # Recrear líneas desde raw_data
        if self.raw_data:
            data = json.loads(self.raw_data)
            lines = data.get('lines', [])

            for seq, line_data in enumerate(lines, 1):
                self._create_detail_line(line_data, seq)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Líneas Actualizadas'),
                'message': _(f'Se recargaron {len(self.detail_line_ids)} líneas de detalle'),
                'type': 'success',
                'sticky': False,
            }
        }

    def action_validate_all_lines(self):
        """Valida todas las líneas y asigna impuestos automáticamente"""
        self.ensure_one()

        success_count = 0
        error_count = 0

        for line in self.detail_line_ids:
            # Asignar impuesto automáticamente si tiene producto
            if line.product_id:
                try:
                    line.action_auto_assign_tax()
                except:
                    pass

            # Validar la línea
            if line.validate_line():
                success_count += 1
            else:
                error_count += 1

        message = f'Validación completada: {success_count} correctas, {error_count} con errores'

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Validación Completada'),
                'message': _(message),
                'type': 'success' if error_count == 0 else 'warning',
                'sticky': True,
            }
        }

    def action_create_single_invoice(self):
        """Crea la factura para esta línea individual"""
        self.ensure_one()

        # Verificar si ya está marcada para omitir
        if self.skip_import:
            raise UserError(_("Esta línea está marcada para omitir. Desmarque 'Omitir' primero."))

        # Verificar duplicado
        if self.is_duplicate:
            raise UserError(_(
                "Ya existe una factura con este consecutivo: %s\n"
                "Factura existente: %s"
            ) % (self.reference, self.existing_invoice_id.name))

        # Verificar si ya se creó
        if self.invoice_id:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Factura Existente'),
                'res_model': 'account.move',
                'res_id': self.invoice_id.id,
                'view_mode': 'form',
                'target': 'current',
            }

        try:
            # Crear la factura
            invoice = self.create_invoice()

            if invoice:
                self.invoice_id = invoice
                self.import_status = 'success'

                return {
                    'type': 'ir.actions.act_window',
                    'name': _('Factura Creada'),
                    'res_model': 'account.move',
                    'res_id': invoice.id,
                    'view_mode': 'form',
                    'target': 'current',
                }
        except Exception as e:
            self.import_status = 'error'
            self.error_message = str(e)
            raise UserError(_(f"Error creando factura: {str(e)}"))

    def action_send_invoice_email(self):
        """Envía la factura por correo electrónico al cliente"""
        self.ensure_one()

        # Verificar que la factura exista
        if not self.invoice_id:
            raise UserError(_("No hay factura creada para enviar. Cree la factura primero."))

        # Verificar que el partner tenga email
        if not self.partner_id or not self.partner_id.email:
            raise UserError(_(
                "El cliente no tiene email configurado.\n"
                "Cliente: %s"
            ) % (self.partner_name or 'Sin nombre'))

        try:
            # Obtener template de email para facturas
            template = self.env.ref('account.email_template_edi_invoice', raise_if_not_found=False)

            if not template:
                # Fallback: usar template genérico
                template = self.env['mail.template'].search([
                    ('model', '=', 'account.move'),
                    ('name', 'ilike', 'invoice')
                ], limit=1)

            if template:
                # Enviar email usando el template
                template.send_mail(
                    self.invoice_id.id,
                    force_send=True,
                    raise_exception=True
                )

                # Registrar en chatter
                self.invoice_id.message_post(
                    body=_(f"Factura enviada por correo desde importador a: {self.partner_id.email}"),
                    message_type='notification'
                )

                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Email Enviado'),
                        'message': _(f'Factura enviada exitosamente a {self.partner_id.email}'),
                        'type': 'success',
                        'sticky': False,
                    }
                }
            else:
                # No hay template, abrir composer manual
                return {
                    'type': 'ir.actions.act_window',
                    'name': _('Enviar Factura'),
                    'res_model': 'mail.compose.message',
                    'view_mode': 'form',
                    'target': 'new',
                    'context': {
                        'default_model': 'account.move',
                        'default_res_id': self.invoice_id.id,
                        'default_partner_ids': [(6, 0, [self.partner_id.id])],
                        'default_email_layout_xmlid': 'mail.mail_notification_light',
                    }
                }

        except Exception as e:
            raise UserError(_(f"Error enviando correo: {str(e)}"))

    def _create_detail_line(self, line_data, sequence=0):
        """Crea una línea de detalle desde los datos del JSON"""
        # Buscar producto
        product = False
        if line_data.get('product_code'):
            product_code = str(line_data['product_code']).strip()
            product = self.env['product.product'].search([
                ('default_code', '=', product_code)
            ], limit=1)

        # Buscar paciente
        patient = False
        if line_data.get('patient_document'):
            patient = self.env['hms.patient'].search([
                ('vat', '=', str(line_data['patient_document']).strip())
            ], limit=1)

        # Buscar ciudad
        patient_city = False
        if line_data.get('patient_city'):
            patient_city = self.env['res.city'].search([
                ('name', 'ilike', line_data['patient_city'])
            ], limit=1)

        # Buscar país
        patient_country = False
        if line_data.get('patient_country'):
            patient_country = self.env['res.country'].search([
                ('name', 'ilike', line_data['patient_country'])
            ], limit=1)

        # Buscar contrato
        contract = False
        if line_data.get('contract_ref'):
            contract = self.env['customer.contract'].search([
                ('name', '=', str(line_data['contract_ref']).strip())
            ], limit=1)

        # Buscar cuenta contable
        account = False
        if line_data.get('account_code'):
            account = self.env['account.account'].search([
                ('code', '=', line_data['account_code']),
                ('company_id', '=', self.importer_id.company_id.id)
            ], limit=1)

        vals = {
            'importer_line_id': self.id,
            'sequence': sequence,
            # Producto
            'product_code': line_data.get('product_code', ''),
            'product_id': product.id if product else False,
            'description': line_data.get('line_description', ''),
            # Cantidades y precios
            'quantity': float(line_data.get('quantity', 1)) if line_data.get('quantity') else 1.0,
            'price_unit': float(line_data.get('price_unit', 0)) if line_data.get('price_unit') else 0.0,
            # Paciente (TODOS OPCIONALES)
            'patient_id': patient.id if patient else False,
            'patient_name': line_data.get('patient_name', ''),
            'patient_document': str(line_data.get('patient_document', '')) if line_data.get('patient_document') else '',
            'patient_doc_type': line_data.get('patient_doc_type', ''),
            'patient_birth_date': self.importer_id._parse_date(line_data.get('patient_birth_date')) if line_data.get('patient_birth_date') else False,
            'patient_gender': line_data.get('patient_gender', ''),
            'patient_user_type': line_data.get('patient_user_type', ''),
            'patient_zone': line_data.get('patient_zone', ''),
            'patient_city_id': patient_city.id if patient_city else False,
            'patient_country_id': patient_country.id if patient_country else False,
            'patient_nationality': line_data.get('patient_nationality', ''),
            # Diagnóstico y autorización
            'diagnosis': line_data.get('diagnosis', ''),
            'authorization_number': line_data.get('authorization_number', ''),
            'service_date': self.importer_id._parse_date(line_data.get('service_date')) if line_data.get('service_date') else False,
            # Contrato
            'contract_id': contract.id if contract else False,
            'contract_ref': line_data.get('contract_ref', ''),
            # Cuenta contable
            'account_id': account.id if account else False,
            'account_code': line_data.get('account_code', ''),
            # Datos crudos
            'raw_line_data': json.dumps(self.importer_id._clean_data_for_json(line_data)),
        }

        return self.env['invoice.importer.detail.line'].create(vals)

    def _send_rips_to_ministerio(self):
        """Envía la factura al ministerio para validación RIPS"""
        self.ensure_one()

        if not self.invoice_id:
            raise UserError(_("No hay factura creada para enviar"))

        self.write({'rips_validation_status': 'sending'})

        try:
            # Llamar al método de validación RIPS de la factura
            self.invoice_id.validate_dian()

            # Actualizar estado
            self.write({
                'rips_validation_status': 'sent',
                'rips_send_date': fields.Datetime.now()
            })

            _logger.info(f"RIPS enviado exitosamente para factura {self.invoice_id.name}")

        except Exception as e:
            self.write({
                'rips_validation_status': 'error',
                'rips_error_message': str(e)
            })
            raise

    def create_invoice(self):
        """Crea una factura desde esta línea"""
        self.ensure_one()

        # Validar o crear partner
        if not self.partner_id:
            if self.importer_id.create_missing_partners and self.partner_vat and self.partner_name:
                # Crear nuevo partner
                self.partner_id = self.env['res.partner'].create({
                    'name': self.partner_name,
                    'vat': self.partner_vat,
                    'customer_rank': 1,
                    'is_company': True,
                })
            else:
                error_msg = _("No se pudo identificar el cliente para la factura ID: %s") % (self.reference or 'Sin ID')
                if not self.partner_vat:
                    error_msg += _("\nERROR: La columna 'Cliente NIT/ID' está VACÍA en el Excel.")
                    error_msg += _("\nSOLUCIÓN: Debe completar el NIT del cliente en la columna B del Excel.")
                else:
                    error_msg += _("\nNIT '%s' no encontrado en el sistema.") % self.partner_vat
                    if not self.importer_id.create_missing_partners:
                        error_msg += _("\nSOLUCIÓN: Active 'Crear clientes no encontrados' en el wizard de importación.")
                    else:
                        error_msg += _("\nSOLUCIÓN: Verifique que el NIT '%s' sea válido.") % self.partner_vat

                raise ValidationError(error_msg)

        # Obtener datos adicionales del JSON
        full_data = {}
        header_data = {}
        lines_data = []

        if self.raw_data:
            full_data = json.loads(self.raw_data)

            # Nuevo formato: {header: {}, lines: []}
            if 'header' in full_data and 'lines' in full_data:
                header_data = full_data.get('header', {})
                lines_data = full_data.get('lines', [])
            else:
                # Formato antiguo (compatibilidad): todo en root
                header_data = full_data
                lines_data = full_data.get('lines', [])

        # Preparar valores de la factura
        invoice_vals = {
            'move_type': 'out_invoice',
            'partner_id': self.partner_id.id,
            'invoice_date': self.invoice_date or fields.Date.today(),
            'invoice_date_due': self.date_due,
            'ref': self.reference,
            'journal_id': self.importer_id.journal_id.id if self.importer_id.journal_id else False,
            'team_id': self.importer_id.team_id.id if self.importer_id.team_id else False,
            'company_id': self.importer_id.company_id.id,
            'importer_id': self.importer_id.id,
            'invoice_line_ids': [],
        }

        # Buscar moneda
        if self.currency_code:
            currency = self.env['res.currency'].search([('name', '=', self.currency_code)], limit=1)
            if currency:
                invoice_vals['currency_id'] = currency.id

        # Agregar campos adicionales de cabecera RIPS (de l10n_co_e-invoice)

        # Campo fe_operation_type (existe en l10n_co_e-invoice)
        # Mapear valores legibles a códigos válidos
        if header_data.get('fe_operation_type'):
            fe_op_value = self.importer_id._map_fe_operation_type(header_data['fe_operation_type'])
            if fe_op_value:
                invoice_vals['fe_operation_type'] = fe_op_value

        # Número de factura personalizado (si viene en Excel con prefijo + secuencial)
        if self.reference:
            custom_number = header_data.get('invoice_number') or self.reference
            invoice_vals['ref'] = custom_number
            journal = self.importer_id.journal_id
            invoice_vals['name'] = f"{journal.code}{self.reference}"

        # Paciente en cabecera (existe en l10n_co_e-invoice)
        if header_data.get('patient_id'):
            invoice_vals['patient_id'] = header_data['patient_id']

        # Contrato (existe en l10n_co_e-invoice como customer.contract)
        # Prioridad: 1) contract_id del header, 2) contrato del importer_line, 3) buscar del partner
        contract = False
        if header_data.get('contract_id'):
            contract = header_data['contract_id']
        elif self.contract_id:
            contract = self.contract_id.id
        elif self.partner_id:
            # Buscar contrato vigente del partner (por fechas)
            today = fields.Date.today()
            contract_obj = self.env['customer.contract'].search([
                ('partner_id', '=', self.partner_id.id),
                ('start_date', '<=', today),
                ('end_date', '>=', today)
            ], limit=1)
            if contract_obj:
                contract = contract_obj.id

        if contract:
            invoice_vals['contract_id'] = contract

        # Periodo de servicio (existen como date_start y date_end)
        if header_data.get('service_period_start'):
            invoice_vals['date_start'] = header_data['service_period_start']

        if header_data.get('service_period_end'):
            invoice_vals['date_end'] = header_data['service_period_end']

        # Plan de cobertura (health_coverage_plan_id es Many2one)
        coverage_plan = False
        if header_data.get('health_coverage'):
            coverage_plan = self.importer_id._find_health_coverage_plan(header_data['health_coverage'])
            if coverage_plan:
                invoice_vals['health_coverage_plan_id'] = coverage_plan.id
        # Si no viene en Excel, buscar uno por defecto
        if not coverage_plan:
            default_coverage = self.env['health.coverage.plan'].search([], limit=1)
            if default_coverage:
                invoice_vals['health_coverage_plan_id'] = default_coverage.id

        # Modo de pago (health_payment_mode_id es Many2one)
        payment_mode = False
        if header_data.get('health_payment_mode'):
            payment_mode = self.importer_id._find_health_payment_mode(header_data['health_payment_mode'])
            if payment_mode:
                invoice_vals['health_payment_mode_id'] = payment_mode.id
        # Si no viene en Excel, buscar uno por defecto
        if not payment_mode:
            default_payment = self.env['health.payment.mode'].search([], limit=1)
            if default_payment:
                invoice_vals['health_payment_mode_id'] = default_payment.id

        # Términos de pago (invoice_payment_term_id es Many2one)
        if header_data.get('payment_term_name'):
            payment_term = self.importer_id._find_payment_term(header_data['payment_term_name'])
            if payment_term:
                invoice_vals['invoice_payment_term_id'] = payment_term.id

        # Campos MIPRES (existen en l10n_co_e-invoice)
        if header_data.get('mipres_number'):
            invoice_vals['health_mipres_number'] = header_data['mipres_number']

        if header_data.get('mipres_delivery_number'):
            invoice_vals['health_mipres_delivery_number'] = header_data['mipres_delivery_number']

        # Código de prestador
        if header_data.get('health_provider_code'):
            invoice_vals['health_provider_code'] = header_data['health_provider_code']

        # Procesar líneas de factura
        if not lines_data:
            # Si no hay líneas detalladas, crear una línea genérica
            lines_data = [{
                'line_description': header_data.get('description', 'Servicio importado'),
                'quantity': 1,
                'price_unit': self.amount_total,
            }]

        _logger.info(f"Creando factura con {len(lines_data)} líneas de detalle")

        for line_data in lines_data:
            line_vals = self._prepare_invoice_line(line_data)
            invoice_vals['invoice_line_ids'].append((0, 0, line_vals))

        # Crear factura
        invoice = self.env['account.move'].create(invoice_vals)

        # Publicar automáticamente si está habilitado
        if self.importer_id.auto_post_invoices:
            try:
                invoice.action_post()
                _logger.info(f"Factura {invoice.name} publicada automáticamente")
            except Exception as e:
                _logger.error(f"Error publicando factura {invoice.name}: {str(e)}")
                # No fallar, solo registrar el error
        elif self.state == 'posted' or self.importer_id.default_state == 'posted':
            # Fallback al comportamiento anterior
            invoice.action_post()

        # Enviar RIPS automáticamente si está habilitado Y la factura está publicada
        if self.importer_id.auto_send_rips and invoice.state == 'posted':
            try:
                self._send_rips_to_ministerio()
                _logger.info(f"RIPS enviado automáticamente para factura {invoice.name}")
            except Exception as e:
                _logger.warning(f"Error enviando RIPS automáticamente: {str(e)}")
                # Marcar como pendiente para envío manual posterior
                self.rips_validation_status = 'pending'

        return invoice

    def _get_or_create_patient(self, patient_data):
        """
        Busca o crea un paciente basado en los datos proporcionados.
        NUEVO: Creación automática de pacientes con validación.
        """
        if not patient_data.get('patient_document'):
            return False

        Patient = self.env['hms.patient']
        doc_type = patient_data.get('patient_doc_type', 'CC')
        doc_number = str(patient_data['patient_document']).strip()

        # Buscar paciente existente
        patient = Patient.search([
            ('vat', '=', doc_number),
            ('l10n_latam_identification_type_id.name', '=', doc_type)
        ], limit=1)

        if patient:
            return patient

        # Crear nuevo paciente si está habilitado
        if not self.importer_id.create_missing_partners:
            return False

        try:
            # Buscar tipo de identificación
            id_type = self.env['l10n_latam.identification.type'].search([
                ('name', '=', doc_type)
            ], limit=1)

            if not id_type:
                id_type = self.env.ref('l10n_latam_base.it_vat', raise_if_not_found=False)

            # Preparar datos del paciente
            patient_vals = {
                'vat': doc_number,
                'l10n_latam_identification_type_id': id_type.id if id_type else False,
                'name': patient_data.get('patient_name', f'Paciente {doc_number}'),
                'customer_rank': 1,
            }

            # Agregar campos opcionales si existen
            if patient_data.get('patient_birth_date'):
                patient_vals['birthdate_date'] = patient_data['patient_birth_date']

            if patient_data.get('patient_gender'):
                patient_vals['gender'] = patient_data['patient_gender']

            if patient_data.get('patient_user_type'):
                patient_vals['health_type'] = patient_data['patient_user_type']

            if patient_data.get('patient_city'):
                city = self.env['res.city'].search([
                    ('name', 'ilike', patient_data['patient_city'])
                ], limit=1)
                if city:
                    patient_vals['city_id'] = city.id

            if patient_data.get('patient_country'):
                country = self.env['res.country'].search([
                    ('name', 'ilike', patient_data['patient_country'])
                ], limit=1)
                if country:
                    patient_vals['country_id'] = country.id

            # Crear paciente
            patient = Patient.create(patient_vals)
            _logger.info(f"Paciente creado: {patient.name} ({doc_number})")

            return patient

        except Exception as e:
            _logger.error(f"Error creando paciente {doc_number}: {str(e)}")
            return False

    def _prepare_invoice_line(self, line_data):
        """
        Prepara los valores de una línea de factura.
        MEJORADO: Con soporte completo para campos RIPS y paciente.
        """
        # Buscar producto si existe código
        product = False
        if line_data.get('product_code'):
            # Normalizar código de producto
            product_code = str(line_data['product_code']).strip()
            product = self.env['product.product'].search([
                ('default_code', '=', product_code)
            ], limit=1)

        line_vals = {
            'name': line_data.get('line_description') or line_data.get('name', 'Línea importada'),
            'quantity': float(line_data.get('quantity', 1)) if line_data.get('quantity') else 1.0,
            'price_unit': float(line_data.get('price_unit', 0)) if line_data.get('price_unit') else 0.0,
        }

        if product:
            line_vals['product_id'] = product.id

        # CAMPOS DE PACIENTE - Existen en acs_hms/models/account.py AccountMoveLine
        patient = self._get_or_create_patient(line_data)

        if patient:
            line_vals['patient_id'] = patient.id

        # Campos adicionales de paciente desde datos de línea
        if line_data.get('patient_name'):
            line_vals['patient_name'] = line_data['patient_name']

        if line_data.get('patient_document'):
            line_vals['patient_document'] = line_data['patient_document']

        if line_data.get('patient_doc_type'):
            mapped_doc_type = self.importer_id._map_patient_doc_type(line_data['patient_doc_type'])
            if mapped_doc_type:
                line_vals['patient_doc_type'] = mapped_doc_type

        if line_data.get('patient_birth_date'):
            line_vals['patient_birth_date'] = line_data['patient_birth_date']

        if line_data.get('patient_gender'):
            mapped_gender = self.importer_id._map_patient_gender(line_data['patient_gender'])
            if mapped_gender:
                line_vals['patient_gender'] = mapped_gender

        if line_data.get('patient_user_type'):
            mapped_user_type = self.importer_id._map_patient_user_type(line_data['patient_user_type'])
            if mapped_user_type:
                line_vals['patient_user_type'] = mapped_user_type

        if line_data.get('patient_zone'):
            mapped_zone = self.importer_id._map_patient_zone(line_data['patient_zone'])
            if mapped_zone:
                line_vals['patient_zone'] = mapped_zone

        if line_data.get('patient_nationality'):
            line_vals['patient_nationality'] = line_data['patient_nationality']

        if line_data.get('patient_city_id'):
            line_vals['patient_city_id'] = line_data['patient_city_id']

        if line_data.get('patient_country_id'):
            line_vals['patient_country_id'] = line_data['patient_country_id']

        # Diagnóstico principal
        if line_data.get('diagnosis'):
            line_vals['diagnostico_principal'] = line_data['diagnosis']

        # Fecha de atención (convertir Date a Datetime)
        if line_data.get('service_date'):
            service_date = line_data['service_date']
            # Si es un objeto date, convertir a datetime
            if isinstance(service_date, date) and not isinstance(service_date, datetime):
                service_date = datetime.combine(service_date, datetime.min.time())
            # Si es string, parsear
            elif isinstance(service_date, str):
                try:
                    # Intentar parsear con diferentes formatos
                    if 'T' in service_date:
                        service_date = datetime.fromisoformat(service_date.replace('Z', '+00:00'))
                    else:
                        service_date = datetime.strptime(service_date, '%Y-%m-%d')
                except (ValueError, TypeError):
                    service_date = False
            line_vals['fecha_atencion'] = service_date

        # Autorización (campo "autorizacion" en acs_hms, no "authorization_number")
        if line_data.get('authorization_number'):
            line_vals['autorizacion'] = line_data['authorization_number']

        # Buscar cuenta contable si se especifica
        if line_data.get('account_code'):
            account = self.env['account.account'].search([
                ('code', '=', line_data['account_code']),
                ('company_id', '=', self.importer_id.company_id.id)
            ], limit=1)
            if account:
                line_vals['account_id'] = account.id

        # IMPUESTOS: Asignar desde producto o desde Excel
        # Primero intentar obtener los impuestos del producto
        if product and product.taxes_id:
            line_vals['tax_ids'] = [(6, 0, product.taxes_id.ids)]
        # Si no hay impuestos en el producto, buscar desde Excel
        elif line_data.get('tax_names'):
            tax_ids = []
            tax_names = line_data['tax_names'].split(',') if isinstance(line_data['tax_names'], str) else [line_data['tax_names']]
            for tax_name in tax_names:
                tax = self.env['account.tax'].search([
                    ('name', 'ilike', str(tax_name).strip()),
                    ('company_id', '=', self.importer_id.company_id.id)
                ], limit=1)
                if tax:
                    tax_ids.append(tax.id)
            if tax_ids:
                line_vals['tax_ids'] = [(6, 0, tax_ids)]
        # Si no hay impuestos, buscar el impuesto de venta por defecto (19%)
        else:
            default_tax = self.env['account.tax'].search([
                ('type_tax_use', '=', 'sale'),
                ('amount', '=', 19.0),
                ('company_id', '=', self.importer_id.company_id.id)
            ], limit=1)
            if default_tax:
                line_vals['tax_ids'] = [(6, 0, [default_tax.id])]

        return line_vals

    def action_post_invoice(self):
        """Publica la factura asociada a esta línea"""
        self.ensure_one()
        if not self.invoice_id:
            raise UserError(_("No hay factura asociada a esta línea"))

        if self.invoice_id.state == 'draft':
            try:
                self.invoice_id.action_post()
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Éxito'),
                        'message': _(f'Factura {self.invoice_id.name} publicada correctamente'),
                        'type': 'success',
                    }
                }
            except Exception as e:
                raise UserError(_(f"Error al publicar factura: {str(e)}"))
        else:
            raise UserError(_(f"La factura {self.invoice_id.name} ya está publicada"))

    def action_send_to_dian(self):
        """Envía la factura asociada a DIAN"""
        self.ensure_one()
        if not self.invoice_id:
            raise UserError(_("No hay factura asociada a esta línea"))

        if self.invoice_id.state != 'posted':
            raise UserError(_("La factura debe estar publicada para enviarla a DIAN"))

        try:
            # validate_dian está en l10n_co_e-invoice
            self.invoice_id.validate_dian()
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Éxito'),
                    'message': _(f'Factura {self.invoice_id.name} enviada a DIAN'),
                    'type': 'success',
                }
            }
        except Exception as e:
            raise UserError(_(f"Error al enviar a DIAN: {str(e)}"))


class InvoiceImporterDetailLine(models.Model):
    """Líneas de detalle individuales para cada factura a importar"""
    _name = 'invoice.importer.detail.line'
    _description = "Línea de Detalle de Factura a Importar"
    _order = 'importer_line_id, sequence'

    importer_line_id = fields.Many2one('invoice.importer.line', string="Factura",
                                       required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(string="Secuencia", default=10)

    # CAMPOS DEL ENCABEZADO (para mostrar opcionalmente)
    header_partner_id = fields.Many2one(related='importer_line_id.partner_id', string="Cliente", readonly=True, store=True)
    header_partner_vat = fields.Char(related='importer_line_id.partner_vat', string="NIT Cliente", readonly=True, store=True)
    header_partner_name = fields.Char(related='importer_line_id.partner_name', string="Nombre Cliente", readonly=True, store=True)
    header_invoice_date = fields.Date(related='importer_line_id.invoice_date', string="Fecha Factura", readonly=True, store=True)
    header_date_due = fields.Date(related='importer_line_id.date_due', string="Vencimiento", readonly=True, store=True)
    header_reference = fields.Char(related='importer_line_id.reference', string="Referencia", readonly=True, store=True)
    header_amount_total = fields.Float(related='importer_line_id.amount_total', string="Total Factura", readonly=True, store=True)
    header_state = fields.Selection(related='importer_line_id.state', string="Estado", readonly=True, store=True)
    header_payment_state = fields.Selection(related='importer_line_id.payment_state', string="Estado Pago", readonly=True, store=True)
    header_journal_id = fields.Many2one(related='importer_line_id.journal_id', string="Diario", readonly=True, store=True)
    header_contract_id = fields.Many2one(related='importer_line_id.contract_id', string="Contrato Header", readonly=True, store=True)
    header_invoice_type = fields.Selection(related='importer_line_id.invoice_type', string="Tipo Factura", readonly=True, store=True)

    # Producto
    product_code = fields.Char(string="Código Producto")
    product_id = fields.Many2one('product.product', string="Producto")
    description = fields.Text(string="Descripción")

    # Cantidades y precios
    quantity = fields.Float(string="Cantidad", default=1.0)
    price_unit = fields.Float(string="Precio Unitario")
    price_subtotal = fields.Float(string="Subtotal", compute='_compute_price_subtotal', store=True)

    # Impuestos
    tax_ids = fields.Many2many('account.tax', string="Impuestos")
    tax_amount = fields.Float(string="Monto Impuestos", compute='_compute_tax_amount', store=True)

    # Paciente (RIPS) - SIN RESTRICCIONES, todos opcionales
    patient_id = fields.Many2one('hms.patient', string="Paciente")
    patient_name = fields.Char(string="Nombre Paciente")
    patient_document = fields.Char(string="Documento Paciente")
    patient_doc_type = fields.Char(string="Tipo Documento")
    patient_birth_date = fields.Date(string="Fecha Nacimiento")
    patient_age = fields.Integer(string="Edad", compute='_compute_patient_age', store=True)
    patient_gender = fields.Selection([
        ('M', 'Masculino'),
        ('F', 'Femenino'),
        ('O', 'Otro')
    ], string="Género")
    patient_user_type = fields.Char(string="Tipo Usuario")
    patient_zone = fields.Char(string="Zona")
    patient_city_id = fields.Many2one('res.city', string="Ciudad Paciente")
    patient_country_id = fields.Many2one('res.country', string="País Paciente")
    patient_nationality = fields.Char(string="Nacionalidad")

    # Diagnóstico y autorización
    diagnosis = fields.Char(string="Diagnóstico Principal")
    authorization_number = fields.Char(string="Número Autorización")
    service_date = fields.Date(string="Fecha Atención")

    # Contrato
    contract_id = fields.Many2one('customer.contract', string="Contrato", required=False, ondelete='set null')
    contract_ref = fields.Char(string="Referencia Contrato")

    # Cuenta contable
    account_id = fields.Many2one('account.account', string="Cuenta Contable")
    account_code = fields.Char(string="Código Cuenta")

    # Validaciones
    has_product = fields.Boolean(string="Tiene Producto", compute='_compute_has_product', store=True)
    validation_errors = fields.Text(string="Errores de Validación")
    is_valid = fields.Boolean(string="Es Válida", compute='_compute_is_valid', store=True)

    # Datos crudos
    raw_line_data = fields.Text(string="Datos Crudos JSON")

    @api.depends('quantity', 'price_unit')
    def _compute_price_subtotal(self):
        for line in self:
            line.price_subtotal = line.quantity * line.price_unit

    @api.depends('price_subtotal', 'tax_ids')
    def _compute_tax_amount(self):
        for line in self:
            if line.tax_ids:
                taxes = line.tax_ids.compute_all(line.price_unit, quantity=line.quantity)
                line.tax_amount = sum(tax['amount'] for tax in taxes['taxes'])
            else:
                line.tax_amount = 0.0

    @api.depends('product_id')
    def _compute_has_product(self):
        for line in self:
            line.has_product = bool(line.product_id)

    @api.depends('patient_birth_date')
    def _compute_patient_age(self):
        today = fields.Date.today()
        for line in self:
            if line.patient_birth_date:
                line.patient_age = (today - line.patient_birth_date).days // 365
            else:
                line.patient_age = 0

    @api.depends('has_product', 'validation_errors')
    def _compute_is_valid(self):
        for line in self:
            line.is_valid = line.has_product and not line.validation_errors

    def action_update_product(self):
        """Permite actualizar el producto manualmente"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Actualizar Producto',
            'res_model': 'invoice.importer.detail.line',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': {'form_view_initial_mode': 'edit'},
        }

    def action_auto_assign_tax(self):
        """Asigna automáticamente el impuesto según el producto"""
        for line in self:
            if not line.product_id:
                continue

            # Obtener impuestos del producto
            product_taxes = line.product_id.taxes_id

            # Filtrar impuestos de venta con 19% o 5%
            valid_taxes = product_taxes.filtered(
                lambda t: t.type_tax_use == 'sale' and t.amount in [19.0, 5.0]
            )

            if valid_taxes:
                line.tax_ids = valid_taxes
            else:
                # Buscar impuesto de venta genérico con 19% o 5%
                tax = self.env['account.tax'].search([
                    ('type_tax_use', '=', 'sale'),
                    ('amount', 'in', [19.0, 5.0]),
                    ('company_id', '=', line.importer_line_id.importer_id.company_id.id)
                ], limit=1)

                if tax:
                    line.tax_ids = tax
                else:
                    line.validation_errors = "No se encontró impuesto de venta con 19% o 5%"

    def validate_line(self):
        """Valida la línea completamente"""
        self.ensure_one()
        errors = []

        # Validar producto
        if not self.product_id:
            errors.append(f"Producto '{self.product_code}' no encontrado")

        # Validar impuestos
        if not self.tax_ids:
            errors.append("No hay impuestos asignados")

        # Validar edad y tipo de documento del paciente
        if self.patient_birth_date:
            age = self.patient_age
            # Validación de tipo de documento según edad
            if self.patient_document:
                doc_type = self.raw_line_data and json.loads(self.raw_line_data).get('patient_doc_type', '')
                if age < 18 and doc_type in ['CC', 'CE']:
                    errors.append(f"Paciente menor de edad ({age} años) no puede tener documento tipo {doc_type}")
                elif age >= 18 and doc_type == 'RC':
                    errors.append(f"Paciente mayor de edad ({age} años) no puede tener Registro Civil")

        self.validation_errors = '\n'.join(errors) if errors else False
        return not bool(errors)


class InvoiceImporterCreditLine(models.Model):
    _name = 'invoice.importer.credit.line'
    _description = "Línea de Importación de Nota Crédito"
    _order = 'id'

    importer_id = fields.Many2one('invoice.importer', string="Importador",
                                 required=True, ondelete='cascade')

    # Datos del partner
    partner_id = fields.Many2one('res.partner', string="Cliente")
    partner_vat = fields.Char(string="NIT/CC")
    partner_name = fields.Char(string="Nombre Cliente")

    # Factura origen
    origin_invoice_id = fields.Many2one('account.move', string="Factura Origen",
                                       domain="[('move_type', '=', 'out_invoice')]")
    origin_invoice_ref = fields.Char(string="Ref. Factura Origen")

    # Datos de la nota crédito
    credit_date = fields.Date(string="Fecha Nota Crédito")
    reason = fields.Text(string="Motivo")
    amount_total = fields.Float(string="Total")
    currency_code = fields.Char(string="Moneda", default='COP')
    journal_id = fields.Many2one('account.journal', string="Diario",
                                 domain="[('type', '=', 'sale')]")

    # Resultado de importación
    import_status = fields.Selection([
        ('pending', 'Pendiente'),
        ('success', 'Exitoso'),
        ('error', 'Error')
    ], string="Estado Importación", default='pending')

    error_message = fields.Text(string="Mensaje de Error")
    credit_note_id = fields.Many2one('account.move', string="Nota Crédito Creada", readonly=True)

    # Datos crudos del archivo
    raw_data = fields.Text(string="Datos Crudos")

    def create_credit_note(self):
        """
        Crea una nota crédito desde esta línea.
        MEJORADO: Con validaciones completas y detección automática de anulación.
        """
        self.ensure_one()

        # VALIDACIÓN 1: Buscar factura origen si no está definida
        if not self.origin_invoice_id and self.origin_invoice_ref:
            self.origin_invoice_id = self.importer_id._find_invoice(self.origin_invoice_ref)

        if not self.origin_invoice_id:
            raise ValidationError(
                _("No se pudo identificar la factura origen: %s") % self.origin_invoice_ref
            )

        origin = self.origin_invoice_id

        # VALIDACIÓN 2: Factura debe estar publicada
        if origin.state != 'posted':
            raise ValidationError(
                _("La factura origen %s no está publicada (estado: %s).\n"
                  "Solo se pueden crear notas de crédito de facturas confirmadas.") % (origin.name, origin.state)
            )

        # VALIDACIÓN 3: Calcular monto ya devuelto por NC anteriores
        existing_refunds = self.env['account.move'].search([
            ('reversed_entry_id', '=', origin.id),
            ('state', '!=', 'cancel'),
            ('move_type', '=', 'out_refund'),
        ])
        total_refunded = sum(existing_refunds.mapped('amount_total'))
        remaining_amount = origin.amount_total - total_refunded

        _logger.info(
            f"NC para {origin.name}: Monto original={origin.amount_total:,.2f}, "
            f"Ya devuelto={total_refunded:,.2f}, Saldo={remaining_amount:,.2f}"
        )

        # VALIDACIÓN 4: Verificar que no exceda el saldo pendiente
        if self.amount_total > remaining_amount + 0.01:  # Tolerancia de 1 centavo
            raise ValidationError(
                _("El monto de la nota de crédito (%.2f) excede el saldo pendiente de la factura.\n\n"
                  "Factura original: %s\n"
                  "Monto original: %.2f\n"
                  "Ya devuelto en NC anteriores: %.2f\n"
                  "Saldo pendiente: %.2f\n\n"
                  "SOLUCIÓN: Reduzca el monto de la NC a máximo %.2f") % (
                    self.amount_total,
                    origin.name,
                    origin.amount_total,
                    total_refunded,
                    remaining_amount,
                    remaining_amount
                )
            )

        # DETECCIÓN AUTOMÁTICA: ¿Es anulación total o devolución parcial?
        total_to_refund = total_refunded + self.amount_total
        is_total_cancellation = abs(total_to_refund - origin.amount_total) < 0.01

        if is_total_cancellation:
            refund_method = 'cancel'
            reason_prefix = "ANULACIÓN TOTAL: "
            _logger.info(f"NC {origin.name}: Detectada ANULACIÓN TOTAL")
        else:
            refund_method = 'refund'
            percentage = (self.amount_total / origin.amount_total) * 100
            reason_prefix = f"DEVOLUCIÓN PARCIAL ({percentage:.1f}% - {self.amount_total:,.2f} de {origin.amount_total:,.2f}): "
            _logger.info(f"NC {origin.name}: Detectada DEVOLUCIÓN PARCIAL ({percentage:.1f}%)")

        # Obtener datos adicionales del JSON
        credit_data = {}
        if self.raw_data:
            credit_data = json.loads(self.raw_data)

        # Obtener motivo del Excel o campo reason
        reason = credit_data.get('credit_reason') or self.reason or 'Sin motivo especificado'
        full_reason = reason_prefix + reason

        # Crear nota crédito usando el wizard de reversión
        reversal_wizard = self.env['account.move.reversal'].with_context(
            active_model='account.move',
            active_ids=origin.ids
        ).create({
            'date': self.credit_date or fields.Date.today(),
            'reason': full_reason,
            'refund_method': refund_method,  # Ahora se detecta automáticamente
            'journal_id': self.importer_id.journal_id.id if self.importer_id.journal_id else origin.journal_id.id,
        })

        # Ejecutar reversión
        result = reversal_wizard.reverse_moves()
        credit_note_id = result.get('res_id')

        if credit_note_id:
            credit_note = self.env['account.move'].browse(credit_note_id)

            # Vincular con el importador
            credit_note.importer_id = self.importer_id.id

            # Ajustar montos si es diferente (solo para devoluciones parciales)
            if not is_total_cancellation and self.amount_total and abs(credit_note.amount_total - self.amount_total) > 0.01:
                # Ajustar líneas proporcionalmente
                if credit_note.amount_total:
                    factor = self.amount_total / credit_note.amount_total
                    for line in credit_note.invoice_line_ids:
                        line.price_unit = line.price_unit * factor

            # Publicar si está configurado
            if self.importer_id.default_state == 'posted' and credit_note.state == 'draft':
                credit_note.action_post()

            # Log de auditoría
            _logger.info(
                f"NC creada exitosamente: {credit_note.name} - "
                f"Tipo: {refund_method.upper()} - "
                f"Monto: {credit_note.amount_total:,.2f} - "
                f"Factura: {origin.name}"
            )

            return credit_note

        return False


# Extender account.move para relación con importador
class AccountMoveInherit(models.Model):
    _inherit = 'account.move'

    importer_id = fields.Many2one('invoice.importer', string="Importador",
                                  help="Importador desde el cual se creó este documento")
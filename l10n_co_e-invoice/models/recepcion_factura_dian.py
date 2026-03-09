import base64
import logging
import tempfile
import xmltodict
import xml.etree.ElementTree as ET
from datetime import datetime
from odoo import  _, api, fields, models, tools
from odoo.exceptions import ValidationError
from zipfile import ZipFile
from stdnum.co.nit import calc_check_digit, compact, format, is_valid, validate
_logger = logging.getLogger(__name__)
import base64
import io
EVENT_CODES = [
    ('02', '[02] Documento validado por la DIAN'),
    ('04', '[03] Documento rechazado por la DIAN'),
    ('030', '[030] Acuse de recibo'),
    ('031', '[031] Reclamo'),
    ('032', '[032] Recibo del bien'),
    ('033', '[033] Aceptación expresa'),
    ('034', '[034] Aceptación Tácita'),
    ('other', 'Otro')
]

TAX_TYPES = [
    ('01', 'IVA'),
    ('02', 'IC - Impuesto al Consumo'),
    ('03', 'ICA'),
    ('04', 'INC - Impuesto Nacional al Consumo'),
    ('22', 'Impuesto Bolsas Plásticas'),
    ('23', 'INCarbono - Impuesto Nacional al Carbono'),
    ('24', 'INCombustibles - Impuesto Nacional a los Combustibles'),
    ('25', 'Sobretasa Combustibles'),
    ('26', 'Sordicom'),
    ('30', 'IC Datos'),
    ('32', 'ICL'),
    ('33', 'INPP'),
    ('34', 'IBUA'),
    ('35', 'ICUI'),
    ('36', 'ADV'),
    ('ZZ', 'Otros tributos')
]

WITHHOLDING_TYPES = [
    ('05', 'ReteIVA'),
    ('06', 'ReteFuente'),
    ('07', 'ReteICA'),
    ('08', 'ReteCREE'),
    ('09', 'ReteIVA Compras'),
    ('10', 'ReteIVA Servicios'),
    ('11', 'ReteIVA Honorarios'),
    ('12', 'ReteIVA Arrendamientos'),
    ('13', 'ReteIVA Régimen Simplificado'),
    ('ZZ', 'Otras Retenciones')
]

DOCUMENT_TYPES = {
    31: 'rut',
    13: 'national_citizen_id',
    11: 'civil_registration',
    12: 'id_card',
    22: 'foreign_id_card',
    41: 'passport',
}

UOM_CODES = [
    ('EA', 'Unidad'),
    ('KG', 'Kilogramo'),
    ('LB', 'Libra'),
    ('MT', 'Metro'),
    ('LT', 'Litro'),
    ('GA', 'Galón'),
    ('PR', 'Par'),
    ('PK', 'Paquete'),
    ('DR', 'Tambor'),
    ('BE', 'Fardo'),
    ('BG', 'Bolsa'),
    ('BX', 'Caja'),
    ('CS', 'Estuche'),
    ('CT', 'Cartón'),
    ('DZ', 'Docena'),
    ('GR', 'Gramo'),
    ('HH', 'Hora'),
    ('KT', 'Kit'),
    ('LM', 'Metro Lineal'),
    ('MC', 'Metro Cúbico'),
    ('MR', 'Metro Cuadrado'),
    ('ND', 'Unidad Indivisible'),
    ('PA', 'Paquete'),
    ('PF', 'Paleta'),
    ('RO', 'Rollo'),
    ('SE', 'Sección'),
    ('ST', 'Hoja'),
    ('TO', 'Tonelada'),
    ('UN', 'Unidad'),
    ('X1', 'Otro'),
]

###############################################################################
#                                   HELPERS                                     #
###############################################################################

def format_xml_string(xml_string):
    """Formatea un string XML para mejor legibilidad."""
    try:
        parsed = ET.XML(xml_string)
        return ET.tostring(parsed, encoding='utf-8', method='xml', xml_declaration=True, pretty_print=True).decode()
    except Exception as e:
        _logger.warning(f"Error al formatear XML: {str(e)}")
        return xml_string

def get_float_value(dict_data, path, default=0.0):
    """Obtiene un valor float de un diccionario anidado de forma segura."""
    try:
        value = dict_data
        for key in path:
            value = value[key]
        return float(value.get('#text', default) if isinstance(value, dict) else value)
    except (KeyError, ValueError, AttributeError):
        return default

def get_text_value(dict_data, path, default=''):
    """Obtiene un valor de texto de un diccionario anidado de forma segura."""
    try:
        value = dict_data
        for key in path:
            value = value[key]
        return value.get('#text', value) if isinstance(value, dict) else value
    except (KeyError, AttributeError):
        return default

class RecepcionTeam(models.Model):
    _name = 'recepcion.team'
    _inherit = ['mail.alias.mixin']
    _description = 'Recepcion Team'


    name = fields.Char('Nombre', required=True)
    company_id = fields.Many2one('res.company', string='Compañia',
                                default=lambda self: self.env.company)
    alias_id = fields.Many2one('mail.alias', string='Alias',
                              required=True,
                              help="Dirección de correo para recepción automática de facturas")
    alias_user_id = fields.Many2one('res.users', string='Usuario Alias',
                                   readonly=False)
    active = fields.Boolean('Activo', default=True)
    alias_domain = fields.Char('Dominio Alias',
                              compute='_compute_alias_domain')

    member_ids = fields.Many2many(
        'res.users', 'team_user_rel', 'team_id', 'user_id',
        string='Miembros del Equipo'
    )

    invoice_count = fields.Integer(
        'Total Facturas',
        compute='_compute_invoice_count'
    )

    @api.depends()
    def _compute_invoice_count(self):
        for team in self:
            team.invoice_count = self.env['recepcion.factura.dian'].search_count([
                ('team', '=', team.id)
            ])

    @api.depends('name')
    def _compute_alias_domain(self):
        self.alias_domain = self.env["ir.config_parameter"].sudo().get_param("mail.catchall.domain")

    def _alias_get_creation_values(self):
        values = super()._alias_get_creation_values()
        values.update({
            'alias_model_id': self.env['ir.model']._get('recepcion.factura.dian').id,
            'alias_parent_model_id': self.env['ir.model']._get('recepcion.team').id,
            'alias_defaults': {'team': self.id},
        })
        return values

    @api.model
    def create(self, vals):
        team = super().create(vals)
        if not team.member_ids:
            team.write({
                'member_ids': [(4, self.env.user.id)]
            })
        return team

class RecepcionFacturaDian(models.Model):
    _name = 'recepcion.factura.dian'
    _description = 'Recepción Factura DIAN'
    _inherit = ['mail.thread.cc',  'mail.activity.mixin']
    _mail_post_access = 'read'
    _check_company_auto = True
    _primary_email = 'partner_email'

    team = fields.Many2one('recepcion.team', string='Equipo')
    name = fields.Char('Nombre')
    cufe = fields.Char('CUFE')
    company_id = fields.Many2one('res.company', string='Compañía', default=lambda self: self.env.company)
    supplier_id = fields.Many2one('res.partner', string='Proveedor')
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('read', 'Leído'),
        ('process', 'Procesado'),
        ('send', 'Enviado')
    ], string='Estado', default='draft', tracking=True)
    origen = fields.Selection([
        ('import', 'Excel'),
        ('correo', 'Correo'),
    ], string='Estado', default='correo', tracking=True)
    zip_file = fields.Binary('Archivo ZIP')
    zip_name = fields.Char('Nombre archivo ZIP')
    pdf_file = fields.Binary('Factura PDF')
    xml_text = fields.Text('Contenido XML')
    invoice_xml = fields.Text('Factura XML')
    file_name = fields.Char('File name')
    date_invoice = fields.Date('Fecha de factura')
    order_line_ids = fields.One2many('recepcion.factura.dian.line','recepcion_id','Lineas de factura')
    n_invoice = fields.Char('Nº Factura')
    total_untax = fields.Float('Total sin impuestos')
    total_tax = fields.Float('Total impuestos')
    total = fields.Float('Total')
    application_response_ids = fields.One2many('dian.application.response','recepcion_id','Lineas de Eventos')
    tiene_eventos = fields.Boolean(compute='_compute_tiene_eventos', store=True)
    partner_email = fields.Char(string='Customer Email', compute='_compute_partner_email', inverse="_inverse_partner_email", store=True, readonly=False)
    fe_type = fields.Selection(
        [('01', 'Factura de venta'),
         ('02', 'Factura de exportación'),
         ('03', 'Documento electrónico de transmisión - tipo 03'),
         ('04', 'Factura electrónica de Venta - tipo 04'),
         ('91', 'Nota Crédito'),
         ('92', 'Nota Débito'),
         ('96', 'Eventos (ApplicationResponse)'),],
        'Tipo de Documento',
        required=True,
        default='01',
        readonly=True,
        states={'draft': [('readonly', False)]}
    )
    l10n_co_edi_operation_type = fields.Selection([('10', 'Estandar'),
                                                  ('09', 'AIU'),
                                                  ('11', 'Mandatos'),
                                                  ('12', 'Transporte'),
                                                  ('13', 'Cambiario'),
                                                  ('15', 'Compra Divisas'),
                                                  ('16', 'Venta Divisas'),
                                                  ('20', 'Nota Crédito que referencia una factura electrónica'),
                                                  ('22', 'Nota Crédito sin referencia a facturas'),
                                                  ('23', 'Nota Crédito para facturación electrónica V1 (Decreto 2242)'),
                                                  ('30', 'Nota Débito que referencia una factura electrónica'),
                                                  ('32', 'Nota Débito sin referencia a facturas'),
                                                  ('23', 'Inactivo: Nota Crédito para facturación electrónica V1 (Decreto 2242)'),
                                                  ('33', 'Inactivo: Nota Débito para facturación electrónica V1 (Decreto 2242)')],
                                                  string="Operation Type (CO)", default="10")
    ie_event_display = fields.Selection(EVENT_CODES,
                                        'Estado del evento',
                                        copy=False,
                                        help='Evento activo de la electronica '
                                         'factura, comprobar el estado'
                                         'para mantenerlo actualizado')

    supplier_claim_concept = fields.Selection(
        [
            ('01', 'Documento con inconsistencias'),
            ('02', 'Mercancia no entregada totalmente'),
            ('03', 'Mercancia no entregada parcialmente'),
            ('04', 'Servicio no prestado'),
        ],
        string="Concepto de Reclamo", tracking=True)

    # Nuevos campos para totales
    total_discounts = fields.Float('Total Descuentos', compute='_compute_totals')
    total_allows = fields.Float('Total Cargos')
    total_prepaids = fields.Float('Total Anticipos')
    total_withholdings = fields.Float('Total Retenciones', compute='_compute_totals')
    total_taxes_detail = fields.Text('Detalle de Impuestos', compute='_compute_totals')
    total_withholdings_detail = fields.Text('Detalle de Retenciones', compute='_compute_totals')
    amount_to_pay = fields.Float('Total a Pagar', compute='_compute_totals')
    date_invoice = fields.Date('Fecha de Factura', tracking=True)
    date_due = fields.Date('Fecha de Vencimiento', tracking=True)
    date_received = fields.Datetime('Fecha de Recepción',  default=fields.Datetime.now, tracking=True)
    billing_reference = fields.Char('Factura Relacionada', tracking=True)
    order_reference = fields.Char('Orden de Compra', tracking=True)
    payment_means_code = fields.Char('Medio de Pago')
    payment_id = fields.Char('ID de Pago')
    payment_terms = fields.Char('Términos de Pago')
    invoice_notes = fields.Text('Notas', tracking=True)
    invoice_reference = fields.Char('Referencia de Factura')
    invoice_comments = fields.Text('Comentarios Adicionales')
    purchase_invoice_id = fields.Many2one('account.move', 'Factura de Compra')
    despatch_reference = fields.Char('Referencia de Despacho')
    receipt_reference = fields.Char('Referencia de Recibo')
    customer_vat = fields.Char('NIT Cliente',
                              help='NIT del cliente en el XML para validación')
    customer_name = fields.Char('Nombre Cliente',
                              help='Nombre del cliente en el XML para validación')
    @api.depends('order_line_ids', 'order_line_ids.total', 'order_line_ids.discount_amount',
                'order_line_ids.tax_amount', 'order_line_ids.withholding_amount')
    def _compute_totals(self):
        for rec in self:
            rec.total_discounts = sum(line.discount_amount for line in rec.order_line_ids)
            rec.total_withholdings = sum(line.withholding_amount for line in rec.order_line_ids)
            rec.amount_to_pay = rec.total - rec.total_withholdings

            taxes_detail = {}
            for line in rec.order_line_ids:
                if line.tax_code and line.tax_amount:
                    key = (line.tax_code, line.tax_percentage)
                    if key not in taxes_detail:
                        taxes_detail[key] = {
                            'base': 0.0,
                            'amount': 0.0,
                            'percentage': line.tax_percentage
                        }
                    taxes_detail[key]['base'] += line.tax_base
                    taxes_detail[key]['amount'] += line.tax_amount

            taxes_text = []
            for (code, percentage), values in taxes_detail.items():
                tax_name = dict(rec.order_line_ids._fields['tax_code'].selection).get(code, code)
                taxes_text.append(
                    f"{tax_name} ({values['percentage']}%): Base ${values['base']:.2f}, "
                    f"Monto ${values['amount']:.2f}"
                )
            rec.total_taxes_detail = '\n'.join(taxes_text)
            withholdings_detail = {}
            for line in rec.order_line_ids:
                if line.withholding_code and line.withholding_amount:
                    key = (line.withholding_code, line.withholding_percentage)
                    if key not in withholdings_detail:
                        withholdings_detail[key] = {
                            'base': 0.0,
                            'amount': 0.0,
                            'percentage': line.withholding_percentage
                        }
                    withholdings_detail[key]['base'] += line.withholding_base
                    withholdings_detail[key]['amount'] += line.withholding_amount

            withholdings_text = []
            for (code, percentage), values in withholdings_detail.items():
                wh_name = dict(rec.order_line_ids._fields['withholding_code'].selection).get(code, code)
                withholdings_text.append(
                    f"{wh_name} ({values['percentage']}%): Base ${values['base']:.2f}, "
                    f"Monto ${values['amount']:.2f}"
                )
            rec.total_withholdings_detail = '\n'.join(withholdings_text)


    def action_view_purchase_invoice(self):
        """
        Abre la vista de la factura de compra relacionada.
        Si hay múltiples facturas, muestra una lista.
        Si hay una sola factura, la muestra directamente.
        """
        self.ensure_one()

        if not self.purchase_invoice_id:
            raise ValidationError(_("No hay factura de compra asociada a este documento."))

        action = {
            'name': _('Factura de Compra'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': self.purchase_invoice_id.id,
            'target': 'current',
            'context': {
                'create': False,
                'default_move_type': 'in_invoice',
            }
        }

        action['domain'] = [('id', '=', self.purchase_invoice_id.id)]

        form_view = self.env.ref('account.view_move_form', False)
        if form_view:
            action['views'] = [(form_view.id, 'form')]

        action['context'].update({
            'journal_type': 'purchase',
            'default_move_type': 'in_invoice',
            'default_partner_id': self.supplier_id.id,
            'default_invoice_date': self.date_invoice,
            'default_date': self.date_invoice,
            'default_ref': self.n_invoice,
            'dian_document_ref': self.cufe,
        })

        return action


    @api.depends('application_response_ids')
    def _compute_tiene_eventos(self):
        for rec in self:
            rec.tiene_eventos = bool(rec.application_response_ids)

    @api.depends('supplier_id.email')
    def _compute_partner_email(self):
        for ticket in self:
            if ticket.supplier_id:
                ticket.partner_email = ticket.supplier_id.email

    def _inverse_partner_email(self):
        for ticket in self:
            if ticket._get_partner_email_update():
                ticket.supplier_id.email = ticket.partner_email

    def _get_partner_email_update(self):
        self.ensure_one()
        if self.supplier_id and self.partner_email != self.supplier_id.email:
            ticket_email_normalized = tools.email_normalize(self.partner_email) or self.partner_email or False
            partner_email_normalized = tools.email_normalize(self.supplier_id.email) or self.supplier_id.email or False
            return ticket_email_normalized != partner_email_normalized
        return False


    @api.model
    def message_new(self, msg_dict, custom_values=None):
        if custom_values is None:
            custom_values = {}

        zip_file = False

        for attachment_id in msg_dict.get('attachments', []):
            if attachment_id.fname[-3:].lower() == 'zip':
                custom_values['zip_file'] = base64.b64encode(attachment_id.content)

        recepcion_id = super(RecepcionFacturaDian, self).message_new(msg_dict, custom_values)

        if 'zip_file' in custom_values:
            try:
                recepcion_id.read_zip()
                recepcion_id.process_xml()
            except Exception as e:
                _logger.exception("Error al procesar el archivo ZIP: %s", str(e))
        return recepcion_id

    def return_inverse_number_document_type(self, document_type):
        documento = 'no_identification'
        if document_type:
            document_type = int(document_type)
            document_types = {
                11: 'civil_registration',
                12: 'id_card',
                13: 'national_citizen_id',
                21: 'alien_card',
                22: 'foreign_id_card',
                31: 'rut',
                41: 'passport',
                42: 'foreign_document',
                91: 'nuip',
                50: 'foreign_nit',
                47: 'pep',
                14: 'military_card',
                16: 'foreign_resident_card',
                15: 'diplomatic_card',
            }
            documento = document_types.get(document_type)
        return documento
    @api.model
    def _find_product_by_reference(self, reference):

        if not reference:
            return False
        model='recepcion.factura.dian.line'
        RecepcionLine = self.env[model]
        previous_line = RecepcionLine.search([
            ('seller_ref', '=', reference),
            ('product_id', '!=', False)
        ], limit=1, order='id desc')  # Ordenar por ID desc para obtener el más reciente

        return previous_line.product_id.id if previous_line else False



    def process_xml(self):
        try:
            dict_data_xml = xmltodict.parse(self.xml_text)
            dict_xml_invoice = xmltodict.parse(self.invoice_xml)
            _logger.error(dict_xml_invoice)
            invoice_data = dict_xml_invoice['Invoice']
            self.date_invoice = datetime.strptime(invoice_data['cbc:IssueDate'], '%Y-%m-%d').date()
            if 'cac:PaymentTerms' in invoice_data:
                payment_terms = invoice_data['cac:PaymentTerms']
                if isinstance(payment_terms, list):
                    for term in payment_terms:
                        if term.get('cbc:PaymentDueDate'):
                            self.date_due = datetime.strptime(term['cbc:PaymentDueDate'], '%Y-%m-%d').date()
                            break
                elif payment_terms.get('cbc:PaymentDueDate'):
                    self.date_due = datetime.strptime(payment_terms['cbc:PaymentDueDate'], '%Y-%m-%d').date()
            if not self.date_due:
                self.date_due = self.date_invoice
            if 'cac:PaymentMeans' in invoice_data:
                payment_means = invoice_data['cac:PaymentMeans']
                if isinstance(payment_means, list):
                    if payment_means:
                        self.payment_means_code = payment_means[0].get('cbc:PaymentMeansCode')
                        self.payment_id = payment_means[0].get('cbc:PaymentID')
                    else:
                        self.payment_means_code = False
                else:
                    self.payment_means_code = payment_means.get('cbc:PaymentMeansCode')
                    self.payment_id = payment_means.get('cbc:PaymentID')
            if 'cac:BillingReference' in invoice_data:
                billing_ref = invoice_data['cac:BillingReference']['cac:InvoiceDocumentReference']
                self.billing_reference = billing_ref.get('cbc:ID')
            if 'cac:OrderReference' in invoice_data:
                self.order_reference = invoice_data['cac:OrderReference'].get('cbc:ID')
            #if 'cbc:CustomizationID' in invoice_data:
            #    self.l10n_co_edi_operation_type = invoice_data.get('cbc:CustomizationID','10')
            notes = []
            if 'cbc:Note' in invoice_data:
                if isinstance(invoice_data['cbc:Note'], list):
                    for note in invoice_data['cbc:Note']:
                        if isinstance(note, str):
                            notes.append(note)
                        elif isinstance(note, dict):
                            if '#text' in note:
                                notes.append(note['#text'])
                            else:
                                try:
                                    notes.append(str(note))
                                except:
                                    continue
                elif isinstance(invoice_data['cbc:Note'], dict):
                    if '#text' in invoice_data['cbc:Note']:
                        notes.append(invoice_data['cbc:Note']['#text'])
                    else:
                        try:
                            notes.append(str(invoice_data['cbc:Note']))
                        except:
                            pass
                else:
                    notes.append(str(invoice_data['cbc:Note']))

            self.invoice_notes = '\n'.join(filter(None, [str(note).strip() for note in notes if note]))
            total_tax = 0.0
            tax_details = []
            tax_totals = invoice_data.get('cac:TaxTotal')

            # Ensure tax_totals is always a list
            if not isinstance(tax_totals, list):
                tax_totals = [tax_totals] if tax_totals else []

            for tax_total in tax_totals:
                try:
                    tax_amount_data = tax_total.get('cbc:TaxAmount', {})
                    if isinstance(tax_amount_data, list):
                        tax_amount_data = tax_amount_data[0] if tax_amount_data else {}

                    tax_amount = float(tax_amount_data.get('#text', '0'))
                    total_tax += tax_amount

                    # Process tax subtotals
                    tax_subtotal = tax_total.get('cac:TaxSubtotal', {})
                    if isinstance(tax_subtotal, list):
                        tax_subtotal = tax_subtotal[0] if tax_subtotal else {}

                    if tax_subtotal:
                        tax_category = tax_subtotal.get('cac:TaxCategory', {})
                        if isinstance(tax_category, list):
                            tax_category = tax_category[0] if tax_category else {}

                        tax_scheme = tax_category.get('cac:TaxScheme', {})
                        if isinstance(tax_scheme, list):
                            tax_scheme = tax_scheme[0] if tax_scheme else {}

                        taxable_amount = tax_subtotal.get('cbc:TaxableAmount', {})
                        if isinstance(taxable_amount, list):
                            taxable_amount = taxable_amount[0] if taxable_amount else {}

                        tax_detail = {
                            'tax_code': tax_scheme.get('cbc:ID'),
                            'tax_name': tax_scheme.get('cbc:Name'),
                            'tax_amount': tax_amount,
                            'tax_base': float(taxable_amount.get('#text', '0')),
                            'tax_percent': float(tax_category.get('cbc:Percent', '0'))
                        }
                        tax_details.append(tax_detail)
                except (KeyError, ValueError, TypeError) as e:
                    continue

            # Process invoice lines
            invoice_lines = []
            cac_invoice_lines = invoice_data.get('cac:InvoiceLine', [])
            if not isinstance(cac_invoice_lines, list):
                cac_invoice_lines = [cac_invoice_lines] if cac_invoice_lines else []

            for line in cac_invoice_lines:
                try:
                    quantity_data = line.get('cbc:InvoicedQuantity', {})
                    if isinstance(quantity_data, list):
                        quantity_data = quantity_data[0] if quantity_data else {}

                    quantity = float(quantity_data.get('#text', '0'))

                    line_amount_data = line.get('cbc:LineExtensionAmount', {})
                    if isinstance(line_amount_data, list):
                        line_amount_data = line_amount_data[0] if line_amount_data else {}

                    line_subtotal = float(line_amount_data.get('#text', '0'))

                    try:
                        price_data = line.get('cac:Price', {}).get('cbc:PriceAmount', {})
                        if isinstance(price_data, list):
                            price_data = price_data[0] if price_data else {}
                        unit_price = float(price_data.get('#text', '0'))
                    except (KeyError, ValueError, TypeError):
                        unit_price = line_subtotal / quantity if quantity else 0.0

                    item = line.get('cac:Item', {})
                    seller_ref = item.get('cac:SellersItemIdentification', {}).get('cbc:ID')
                    standard_ref = item.get('cac:StandardItemIdentification', {}).get('cbc:ID', {})
                    if isinstance(standard_ref, dict):
                        standard_ref = standard_ref.get('#text')
                    product_reference = seller_ref or standard_ref or ''
                    product_id = self._find_product_by_reference(product_reference)

                    line_vals = {
                        'name': item.get('cbc:Description'),
                        'qty': quantity,
                        'seller_ref': product_reference,
                        'product_id': product_id,
                        'product_default_code': standard_ref,
                        'price_unit': unit_price,
                        'price_subtotal': line_subtotal,
                        'discount_amount': 0,
                        'discount_percentage': 0,
                        'tax_line_ids': [],
                        'withholding_line_ids': []
                    }

                    if 'cac:AllowanceCharge' in line:
                        allowance = line['cac:AllowanceCharge']
                        if isinstance(allowance, list):
                            allowance = allowance[0] if allowance else {}
                        if allowance.get('cbc:ChargeIndicator') == 'false':
                            line_vals['discount_percentage'] = float(allowance.get('cbc:MultiplierFactorNumeric', '0'))
                            amount_data = allowance.get('cbc:Amount', {})
                            if isinstance(amount_data, list):
                                amount_data = amount_data[0] if amount_data else {}
                            line_vals['discount_amount'] = float(amount_data.get('#text', '0'))

                    # Process line taxes
                    line_tax_totals = line.get('cac:TaxTotal', [])
                    if not isinstance(line_tax_totals, list):
                        line_tax_totals = [line_tax_totals] if line_tax_totals else []

                    for tax_total in line_tax_totals:
                        if not tax_total:
                            continue

                        tax_subtotals = tax_total.get('cac:TaxSubtotal', [])
                        if not isinstance(tax_subtotals, list):
                            tax_subtotals = [tax_subtotals] if tax_subtotals else []

                        for tax_subtotal in tax_subtotals:
                            try:
                                if isinstance(tax_subtotal, list):
                                    tax_subtotal = tax_subtotal[0] if tax_subtotal else {}

                                tax_category = tax_subtotal.get('cac:TaxCategory', {})
                                if isinstance(tax_category, list):
                                    tax_category = tax_category[0] if tax_category else {}

                                tax_scheme = tax_category.get('cac:TaxScheme', {})
                                if isinstance(tax_scheme, list):
                                    tax_scheme = tax_scheme[0] if tax_scheme else {}

                                tax_amount_data = tax_subtotal.get('cbc:TaxAmount', {})
                                if isinstance(tax_amount_data, list):
                                    tax_amount_data = tax_amount_data[0] if tax_amount_data else {}

                                tax_base_data = tax_subtotal.get('cbc:TaxableAmount', {})
                                if isinstance(tax_base_data, list):
                                    tax_base_data = tax_base_data[0] if tax_base_data else {}

                                tax_vals = {
                                    'tax_code': tax_scheme.get('cbc:ID', 'ZZ'),
                                    'tax_name': tax_scheme.get('cbc:Name', ''),
                                    'tax_amount': float(tax_amount_data.get('#text', '0')),
                                    'tax_base': float(tax_base_data.get('#text', '0')),
                                    'tax_percentage': float(tax_category.get('cbc:Percent', '0'))
                                }

                                # Classify between withholdings and taxes
                                if tax_vals['tax_code'] in ['05', '06', '07', '08']:
                                    line_vals['withholding_line_ids'].append((0, 0, tax_vals))
                                else:
                                    line_vals['tax_line_ids'].append((0, 0, tax_vals))

                            except (KeyError, ValueError, TypeError) as e:
                                continue

                    invoice_lines.append((0, 0, line_vals))

                except (KeyError, ValueError, TypeError) as e:
                    continue

            self.order_line_ids = [(5, 0, 0)]
            self.order_line_ids = invoice_lines

            # Resto del código permanece igual
            file_object = io.BytesIO(base64.b64decode(self.zip_file))
            zipfile_ob = ZipFile(file_object)
            for finfo in zipfile_ob.infolist():
                ifile = zipfile_ob.read(finfo)
                if "%PDF" not in str(ifile):
                    parsed_xml = xmltodict.parse(
                        ifile,
                        process_namespaces=True
                    )
                    invoice_data = self._get_invoice_data(parsed_xml)
            supplier_data = invoice_data['supplier']
            customer_data = invoice_data['customer']
            dv = calc_check_digit(supplier_data['party_identification'])
            vat = str(supplier_data['party_identification']) +'-' + dv
            documento = self.return_inverse_number_document_type(supplier_data['schemeName'])
            supplier = self.env['res.partner'].search([('vat', '=', vat)], limit=1)
            if not supplier:
                supplier = self.env['res.partner'].create({
                    'name': supplier_data['party_name'],
                    'vat': vat,
                    'is_company' : True,
                    'l10n_latam_identification_type_id' : self.env['l10n_latam.identification.type'].search([('l10n_co_document_code','=', documento )], limit=1).id,
                    'street': supplier_data['address'],
                    'city': supplier_data['city_name'],
                    'state_id': self.env['res.country.state'].search([('name', 'ilike', supplier_data['department'])], limit=1).id,
                    'city_id': self.env['res.city'].search([('name', 'ilike', supplier_data['city_name'])], limit=1).id,
                    'country_id': self.env['res.country'].search([('code', '=', supplier_data['country'])], limit=1).id,
                    'supplier_rank': 1,
                    'customer_rank': 0,
                })

            legal_monetary = dict_xml_invoice['Invoice'].get('cac:LegalMonetaryTotal', {})
            self.write({
                'n_invoice': dict_xml_invoice['Invoice']['cbc:ID'],
                'supplier_id': supplier.id,
                'customer_vat': self._clean_xml_name(customer_data['party_name']),
                'customer_name': str(customer_data['party_identification']),
                'fe_type': invoice_data.get('cbc:InvoiceTypeCode','01'),
                'cufe': invoice_data['invoice_uuid'],
                'total_tax': total_tax,
                'total_prepaids': float(legal_monetary.get('cbc:PrepaidAmount', {}).get('#text', '0')),
                'total_allows': float(legal_monetary.get('cbc:ChargeTotalAmount', {}).get('#text', '0')),
                'total_untax': float(dict_xml_invoice['Invoice']['cac:LegalMonetaryTotal']['cbc:LineExtensionAmount']['#text']),
                'total': float(dict_xml_invoice['Invoice']['cac:LegalMonetaryTotal']['cbc:PayableAmount']['#text']),
                'state': 'read'
            })
            self._compute_totals()
        except Exception as e:
            error_msg = f"Error procesando XML: {str(e)}"
            _logger.exception(error_msg)
            raise ValidationError(error_msg)

    def _clean_xml_name(self, name_data):
        if isinstance(name_data, dict):
            for key, value in name_data.items():
                if key.endswith(':Name'):
                    return value
            return next(iter(name_data.values()), '')
        return str(name_data) if name_data else ''

    def action_create_invoice(self):
        """Crea la factura de compra en el sistema."""
        self.ensure_one()

        if not self.supplier_id:
            raise ValidationError('Se requiere un proveedor para crear la factura.')

        if self.purchase_invoice_id:
            raise ValidationError('Ya existe una factura creada para este documento.')

        # Preparar líneas de factura
        invoice_lines = []
        existing_invoice = self.env['account.move'].search([
            ('move_type', '=', 'in_invoice'),
            ('partner_id', '=', self.supplier_id.id),
            ('ref', '=', self.n_invoice),
            ('state', '!=', 'cancel')
        ], limit=1)

        if existing_invoice:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Factura Duplicada',
                    'message': f'Ya existe una factura con la referencia {self.n_invoice} para el proveedor {self.supplier_id.name}.\nFactura existente: {existing_invoice.name}',
                    'type': 'warning',  # warning, danger, success, info
                    'sticky': True,     # True = no desaparece automáticamente
                }
            }
        for line in self.order_line_ids:
            # if not line.account_id:
            #     raise ValidationError(f'Falta cuenta contable en la línea: {line.name}')

            line_vals = {
                'product_id': line.product_id.id,
                'name': line.name,
                'quantity': line.qty,
                'price_unit': line.price_unit or (line.total/line.qty),
                #'account_id': line.account_id.id,
                #'product_uom_id': self._get_uom_id(line.uom).id,
                'discount': line.discount_percentage,
            }

            # Procesar impuestos y retenciones
            taxes = []

            # Impuestos regulares
            for tax_line in line.tax_line_ids:
                tax = self.env['account.tax'].search([
                    ('type_tax_use', '=', 'purchase'),
                    ('amount', '=', tax_line.tax_percentage),
                    ('company_id', '=', self.company_id.id),
                ], limit=1)
                if tax:
                    taxes.append(tax.id)

            # Retenciones
            for wh_line in line.withholding_line_ids:
                retention = self.env['account.tax'].search([
                    ('type_tax_use', '=', 'purchase'),
                    ('amount', '=', -abs(wh_line.withholding_percentage)),
                    ('company_id', '=', self.company_id.id),
                ], limit=1)
                if retention:
                    taxes.append(retention.id)

            if taxes:
                line_vals['tax_ids'] = [(6, 0, taxes)]

            invoice_lines.append((0, 0, line_vals))

        # Preparar notas y referencias
        narration = []
        if self.billing_reference:
            narration.append(f"Factura relacionada: {self.billing_reference}")
        if self.order_reference:
            narration.append(f"Orden de compra: {self.order_reference}")
        if self.invoice_notes:
            narration.append(f"Notas: {self.invoice_notes}")

        # Crear factura
        invoice_vals = {
            'move_type': 'in_invoice',
            'partner_id': self.supplier_id.id,
            'ref': self.n_invoice,
            'invoice_date': self.date_invoice,
            'date': self.date_invoice,
            'invoice_date_due': self.date_due or self.date_invoice,
            'narration': '\n'.join(narration) if narration else False,
            'invoice_line_ids': invoice_lines,
            'invoice_origin': self.name,
        }

        # Crear la factura
        invoice = self.env['account.move'].create(invoice_vals)
        self.write({
            'purchase_invoice_id': invoice.id,
            'state': 'process'
        })

        # Mensaje en el chatter
        self.message_post(
            body=_("Factura de compra %s creada.") % invoice.name,
            message_type='notification'
        )
        if self.pdf_file:
            attachment = self.env['ir.attachment'].create({
                'name': f'Factura_{self.n_invoice}.pdf',
                'type': 'binary',
                'datas': self.pdf_file,
                'res_model': 'account.move',
                'res_id': invoice.id,
                'mimetype': 'application/pdf'
            })
            # Vincular el adjunto a la factura
            invoice.message_post(attachment_ids=[attachment.id])
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': invoice.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _get_uom_id(self, uom_code):
        """Obtiene la unidad de medida correspondiente al código UOM."""
        uom_mapping = {
            'EA': 'uom.product_uom_unit',
            'KG': 'uom.product_uom_kgm',
            'LB': 'uom.product_uom_lb',
            'MT': 'uom.product_uom_meter',
            'LT': 'uom.product_uom_litre',
            'UN': 'uom.product_uom_unit',
        }

        if uom_code in uom_mapping:
            return self.env.ref(uom_mapping[uom_code])
        return self.env.ref('uom.product_uom_unit')

    def _get_payment_means(self, code):
        """Obtiene el medio de pago correspondiente al código DIAN."""
        return self.env['l10n_co_dian.payment.means'].search(
            [('code', '=', code)], limit=1
        ) or self.env['l10n_co_dian.payment.means'].search([], limit=1)

    def add_application_response(self):
        response_code = self._context.get('response_code')
        for rec in self:
            if rec.origen == 'correo':
                ar = self.env['dian.application.response'].generate_from_attached_document(rec.xml_text, response_code,rec.id)
            else:
                ar = self.env['dian.application.response'].generate_from_electronic_invoice(rec.id, response_code)

        #self.application_response_ids = [(4,ar.id)]

    def charge_supplier_invoice(self):
        if not self.zip_file:
            raise ValidationError("Debe adjuntar una factura para continuar con esta acción")
        file_object = io.BytesIO(base64.b64decode(self.zip_file))
        zipfile_ob = ZipFile(file_object)

        for finfo in zipfile_ob.infolist():
            ifile = zipfile_ob.read(finfo)

            if "%PDF" not in str(ifile):

                parsed_xml = xmltodict.parse(
                    ifile,
                    process_namespaces=True
                )

                invoice_data = self._get_invoice_data(parsed_xml)


    def action_register_event(self):
        action = self.env.ref('l10n_co_e-invoice.action_register_event_dian').sudo().read()[0]
        return action

    def read_zip(self):
        try:
            file = base64.b64decode(self.zip_file)
            with tempfile.NamedTemporaryFile(delete=False) as fobj:
                fobj.write(file)
                fobj.seek(0)
                with ZipFile(fobj.name, 'r') as zip_file:
                    for nombre in zip_file.namelist():
                        if nombre[-4:].lower() == '.xml':
                            self.name = nombre[:-4]
                            with zip_file.open(nombre) as _contenido:
                                self.xml_text = _contenido.read()
                        elif nombre[-4:].lower() == '.pdf':
                            with zip_file.open(nombre) as _contenido:
                                self.pdf_file = base64.b64encode(_contenido.read())

            self.invoice_xml = xmltodict.parse(self.xml_text)['AttachedDocument']['cac:Attachment']['cac:ExternalReference']['cbc:Description']
            self.state = 'read'
        except Exception as e:
            _logger.exception("Error al leer el archivo ZIP: %s", str(e))
            raise

    def _get_invoice_data(self, parsed_doc):
        ns = {
            'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2',
            'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2',
            'fe': 'http://www.dian.gov.co/contratos/facturaelectronica/v1',
        }

        try:
            attached = parsed_doc['urn:oasis:names:specification:ubl:schema:xsd:AttachedDocument-2:AttachedDocument']
            ifile = attached[ns['cac'] + ':Attachment'][ns['cac'] + ':ExternalReference'][ns['cbc'] + ':Description']
            parsed_data = xmltodict.parse(
                ifile,
                process_namespaces=True
            )
        except:
            parsed_data = parsed_doc

        invoice_data = {}
        try:
            invoice = parsed_data[ns['fe'] + ':Invoice']
        except:
            invoice = parsed_data['urn:oasis:names:specification:ubl:schema:xsd:Invoice-2:Invoice']

        # Datos básicos de la factura
        invoice_data['invoice_id'] = invoice[ns['cbc'] + ':ID']
        invoice_data['invoice_uuid'] = invoice[ns['cbc'] + ':UUID']['#text']
        invoice_data['invoice_issue_date'] = invoice[ns['cbc'] + ':IssueDate']
        invoice_data['invoice_issue_time'] = invoice[ns['cbc'] + ':IssueTime']
        invoice_data['invoice_type_code'] = invoice[ns['cbc'] + ':InvoiceTypeCode']
        try:
            invoice_data['invoice_note'] = invoice[ns['cbc'] + ':Note']
        except:
            invoice_data['invoice_note'] = ''

        # Account supplier party
        invoice_data['supplier'] = {}
        supplier = invoice[ns['cac'] + ':AccountingSupplierParty']
        if isinstance(supplier, list):
            supplier = supplier[0]

        invoice_data['supplier']['additional_account_id'] = supplier[ns['cbc'] + ':AdditionalAccountID']

        supplier_party = supplier[ns['cac'] + ':Party']
        if isinstance(supplier_party, list):
            supplier_party = supplier_party[0]

        party_tax_scheme = supplier_party[ns['cac'] + ':PartyTaxScheme']
        if isinstance(party_tax_scheme, list):
            party_tax_scheme = party_tax_scheme[0]

        invoice_data['supplier']['party_identification'] = party_tax_scheme[ns['cbc'] + ':CompanyID']['#text']

        try:
            party_name = supplier_party[ns['cac'] + ':PartyName']
            if isinstance(party_name, list):
                party_name = party_name[0]
            name = party_name[ns['cbc'] + ':Name']
            if name is not None:
                invoice_data['supplier']['party_name'] = name
            else:
                try:
                    invoice_data['supplier']['party_name'] = (
                        supplier_party[ns['cac'] + ':PartyLegalEntity']
                        [ns['cbc'] + ':RegistrationName']
                    )
                except KeyError:
                    invoice_data['supplier']['party_name'] = ''
        except KeyError:
            try:
                invoice_data['supplier']['party_name'] = (
                    supplier_party[ns['cac'] + ':PartyLegalEntity']
                    [ns['cbc'] + ':RegistrationName']
                )
            except KeyError:
                invoice_data['supplier']['party_name'] = ''

        physical_location = supplier_party[ns['cac'] + ':PhysicalLocation']
        if isinstance(physical_location, list):
            physical_location = physical_location[0]

        address = physical_location[ns['cac'] + ':Address']
        if isinstance(address, list):
            address = address[0]

        address_line = address[ns['cac'] + ':AddressLine']
        if isinstance(address_line, list):
            address_line = address_line[0]

        country = address[ns['cac'] + ':Country']
        if isinstance(country, list):
            country = country[0]

        invoice_data['supplier']['department'] = address[ns['cbc'] + ':CountrySubentity']
        invoice_data['supplier']['schemeName'] = party_tax_scheme[ns['cbc'] + ':CompanyID']['@schemeName']
        invoice_data['supplier']['city_name'] = address[ns['cbc'] + ':CityName']
        invoice_data['supplier']['address'] = address_line[ns['cbc'] + ':Line']
        invoice_data['supplier']['country'] = country[ns['cbc'] + ':IdentificationCode']
        invoice_data['supplier']['tax_level_code'] = party_tax_scheme[ns['cbc'] + ':TaxLevelCode']

        party_legal_entity = supplier_party[ns['cac'] + ':PartyLegalEntity']
        if isinstance(party_legal_entity, list):
            party_legal_entity = party_legal_entity[0]
        invoice_data['supplier']['registration_name'] = party_legal_entity[ns['cbc'] + ':RegistrationName']

        # Customer
        invoice_data['customer'] = {}
        customer = invoice[ns['cac'] + ':AccountingCustomerParty']
        if isinstance(customer, list):
            customer = customer[0]

        invoice_data['customer']['additional_account_id'] = customer[ns['cbc'] + ':AdditionalAccountID']

        customer_party = customer[ns['cac'] + ':Party']
        if isinstance(customer_party, list):
            customer_party = customer_party[0]

        customer_party_tax_scheme = customer_party[ns['cac'] + ':PartyTaxScheme']
        if isinstance(customer_party_tax_scheme, list):
            customer_party_tax_scheme = customer_party_tax_scheme[0]

        invoice_data['customer']['party_identification'] = customer_party_tax_scheme[ns['cbc'] + ':CompanyID']['#text']
        invoice_data['customer']['schemeName'] = customer_party_tax_scheme[ns['cbc'] + ':CompanyID']['@schemeName']

        try:
            party_name = customer_party[ns['cac'] + ':PartyName']
            if isinstance(party_name, list):
                party_name = party_name[0]
            invoice_data['customer']['party_name'] = party_name
        except KeyError:
            invoice_data['customer']['party_name'] = None

        try:
            physical_location = customer_party[ns['cac'] + ':PhysicalLocation']
            if isinstance(physical_location, list):
                physical_location = physical_location[0]

            address = physical_location[ns['cac'] + ':Address']
            if isinstance(address, list):
                address = address[0]

            address_line = address[ns['cac'] + ':AddressLine']
            if isinstance(address_line, list):
                address_line = address_line[0]

            country = address[ns['cac'] + ':Country']
            if isinstance(country, list):
                country = country[0]

            invoice_data['customer']['department'] = address[ns['cbc'] + ':CountrySubentity']
            invoice_data['customer']['city_name'] = address[ns['cbc'] + ':CityName']
            invoice_data['customer']['address'] = address_line[ns['cbc'] + ':Line']
            invoice_data['customer']['country'] = country[ns['cbc'] + ':IdentificationCode']
        except KeyError:
            invoice_data['customer']['department'] = ''
            invoice_data['customer']['city_name'] = ''
            invoice_data['customer']['address'] = ''
            invoice_data['customer']['country'] = ''

        try:
            invoice_data['customer']['tax_level_code'] = customer_party_tax_scheme[ns['cbc'] + ':TaxLevelCode']
        except KeyError:
            invoice_data['customer']['tax_level_code'] = ''

        try:
            party_legal_entity = customer_party[ns['fe'] + ':PartyLegalEntity']
            if isinstance(party_legal_entity, list):
                party_legal_entity = party_legal_entity[0]
            invoice_data['customer']['registration_name'] = party_legal_entity[ns['cbc'] + ':RegistrationName']
        except KeyError:
            invoice_data['customer']['registration_name'] = None

        try:
            person = customer_party[ns['fe'] + ':Person']
            if isinstance(person, list):
                person = person[0]
            invoice_data['customer']['person'] = {
                'firstname': person[ns['cbc'] + ':FirstName'],
                'familyname': person[ns['cbc'] + ':FamilyName'],
                'middlename': person[ns['cbc'] + ':MiddleName'],
            }
        except KeyError:
            invoice_data['customer']['person'] = {
                'firstname': None,
                'familyname': None,
                'middlename': None,
            }

        # Legal Monetary Total
        invoice_data['legal_monetary_total'] = {}
        legal_monetary_total = invoice[ns['cac'] + ':LegalMonetaryTotal']
        if isinstance(legal_monetary_total, list):
            legal_monetary_total = legal_monetary_total[0]

        invoice_data['legal_monetary_total'] = {
            'line_extension_amount': legal_monetary_total[ns['cbc'] + ':LineExtensionAmount']['#text'],
            'tax_exclusive_amount': legal_monetary_total[ns['cbc'] + ':TaxExclusiveAmount']['#text'],
            'payabel_amount': legal_monetary_total[ns['cbc'] + ':PayableAmount']['#text']
        }

        # Invoice Lines
        invoice_data['invoice_lines'] = []
        invoice_lines = invoice[ns['cac'] + ':InvoiceLine']
        if not isinstance(invoice_lines, list):
            invoice_lines = [invoice_lines]

        for invoice_line in invoice_lines:
            item = invoice_line[ns['cac'] + ':Item']
            if isinstance(item, list):
                item = item[0]

            price = invoice_line[ns['cac'] + ':Price']
            if isinstance(price, list):
                price = price[0]

            taxes = []
            try:
                taxtotal = invoice_line[ns['cac'] + ':TaxTotal']
                if isinstance(taxtotal, list):
                    taxtotal = taxtotal[0]

                tax_subtotals = taxtotal[ns['cac'] + ':TaxSubtotal']
                if not isinstance(tax_subtotals, list):
                    tax_subtotals = [tax_subtotals]

                for tax in tax_subtotals:
                    tax_category = tax[ns['cac'] + ':TaxCategory']
                    if isinstance(tax_category, list):
                        tax_category = tax_category[0]

                    tax_scheme = tax_category[ns['cac'] + ':TaxScheme']
                    if isinstance(tax_scheme, list):
                        tax_scheme = tax_scheme[0]

                    taxes.append({
                        'percentage': tax_category[ns['cbc'] + ':Percent'],
                        'code': tax_scheme[ns['cbc'] + ':ID']
                    })
            except:
                taxes = []

            line_extension_amount = invoice_line[ns['cbc'] + ':LineExtensionAmount']
            if isinstance(line_extension_amount, dict):
                line_extension_amount = line_extension_amount.get('#text', '0')

            price_amount = price[ns['cbc'] + ':PriceAmount']
            if isinstance(price_amount, dict):
                price_amount = price_amount.get('#text', '0')

            invoice_data['invoice_lines'].append({
                'id': invoice_line[ns['cbc'] + ':ID'],
                'invoiced_quantity': invoice_line[ns['cbc'] + ':InvoicedQuantity'],
                'line_extension_amount': line_extension_amount,
                'item': {
                    'description': item[ns['cbc'] + ':Description']
                },
                'price': {
                    'price_amount': price_amount
                },
                'taxes': taxes
            })

        return invoice_data


class RecepcionFacturaDianLine(models.Model):
    _name = 'recepcion.factura.dian.line'
    _description = 'Línea de Recepción Factura DIAN'
    _order = 'sequence, id'

    sequence = fields.Integer(string='Secuencia', default=10)
    name = fields.Char('Producto', required=True)
    recepcion_id = fields.Many2one('recepcion.factura.dian', 'Recepcion de factura DIAN', ondelete='cascade')

    # Campos de producto y búsqueda
    product_id = fields.Many2one('product.product', 'Producto')
   # product_suggestion_ids = fields.Many2many('product.product', string='Productos Sugeridos', compute='_compute_product_suggestions')
    previous_product_id = fields.Many2one('product.product', string='Producto Usado Anteriormente', compute='_compute_previous_product')
    create_product = fields.Boolean('Crear Producto')
    seller_ref = fields.Char('Referencia Proveedor')
    product_default_code = fields.Char('Código Interno')

    # Campos base
    uom = fields.Selection(UOM_CODES, string='Unidad de Medida' )
    qty = fields.Float('Cantidad', default=1.0)
    price_unit = fields.Float('Precio Unitario')
    price = fields.Float('Precio con Descuento', compute='_compute_price')
    price_subtotal = fields.Float('Subtotal', compute='_compute_amounts')
    tax_percentage = fields.Float('% Impuesto', default=0.0)
    tax_code = fields.Selection([
        ('01', 'IVA'),
        ('02', 'IC'),
        ('03', 'ICA'),
        ('04', 'INC'),
        ('ZZ', 'Otros')
    ], string='Tipo de Impuesto')

    # Campos para retenciones
    withholding_amount = fields.Float('Monto Retención', default=0.0)
    withholding_base = fields.Float('Base Retención', default=0.0)
    withholding_percentage = fields.Float('% Retención', default=0.0)
    withholding_code = fields.Selection([
        ('05', 'ReteIVA'),
        ('06', 'ReteFuente'),
        ('07', 'ReteICA'),
        ('08', 'ReteCREE'),
        ('ZZ', 'Otras')
    ], string='Tipo de Retención')
    # Campos de cuenta
    account_id = fields.Many2one('account.account', 'Cuenta de Gasto',
        domain="[('deprecated', '=', False), ('company_id', '=', company_id)]")
    company_id = fields.Many2one(related='recepcion_id.company_id')

    # Campos de descuentos
    discount_amount = fields.Float('Monto Descuento', default=0.0)
    discount_percentage = fields.Float('% Descuento', default=0.0)
    discount_reason = fields.Char('Razón del Descuento')

    # Campos de impuestos
    tax_amount = fields.Float('Total Impuestos', compute='_compute_tax_totals', store=True)
    tax_base = fields.Float('Base Imponible', store=True)
    tax_line_ids = fields.One2many('recepcion.factura.dian.tax.line', 'invoice_line_id', 'Impuestos')

    # Campos de retenciones
    withholding_amount = fields.Float('Total Retenciones', compute='_compute_tax_totals', store=True)
    withholding_base = fields.Float('Base Retenciones', store=True)
    withholding_line_ids = fields.One2many('recepcion.factura.dian.withholding.line', 'invoice_line_id', 'Retenciones')

    # Campo total
    total = fields.Float('Total', compute='_compute_total', store=True)

    @api.depends('name', 'seller_ref', 'recepcion_id.supplier_id')
    def _compute_product_suggestions(self):
        for line in self:
            suggestions = self.env['product.product']
            if line.name and len(line.name.strip()) > 2:
                # Búsqueda por coincidencia exacta
                domain = ['|', '|', '|',
                    ('name', 'ilike', line.name),
                    ('default_code', 'ilike', line.name),
                    ('barcode', '=', line.name),
                    ('seller_ids.product_code', 'ilike', line.name)
                ]

                # Agregar búsqueda por referencia del proveedor
                if line.seller_ref:
                    domain.extend(['|',
                        ('seller_ids.product_code', '=', line.seller_ref),
                        ('default_code', '=', line.seller_ref)
                    ])

                # Si hay proveedor, buscar en sus productos
                if line.recepcion_id.supplier_id:
                    domain.append(('seller_ids.partner_id', '=', line.recepcion_id.supplier_id.id))

                suggestions = self.env['product.product'].search(domain, limit=5)

                # Búsqueda por palabras clave
                if not suggestions and ' ' in line.name:
                    words = [w for w in line.name.split() if len(w) > 3]
                    if words:
                        word_domain = ['|'] * (len(words) - 1) + [('name', 'ilike', word) for word in words]
                        suggestions |= self.env['product.product'].search(word_domain, limit=3)

            line.product_suggestion_ids = suggestions

    @api.depends('name', 'recepcion_id.supplier_id')
    def _compute_previous_product(self):
        for line in self:
            previous = self.env['recepcion.factura.dian.line'].search([
                ('name', '=', line.name),
                ('product_id', '!=', False),
                ('id', '!=', line.id)
            ], order='create_date DESC', limit=1)

            line.previous_product_id = previous.product_id if previous else False

    @api.depends('price_unit', 'discount_percentage', 'discount_amount')
    def _compute_price(self):
        for line in self:
            price = line.price_unit
            if line.discount_percentage:
                price *= (1 - (line.discount_percentage / 100))
            #if line.discount_amount:
            #    price -= (line.discount_amount / line.qty if line.qty else 1)
            line.price = price

    @api.depends('qty', 'price', 'tax_line_ids', 'withholding_line_ids')
    def _compute_amounts(self):
        for line in self:
            line.price_subtotal = line.qty * line.price
            line.tax_base = line.price_subtotal
            line.withholding_base = line.price_subtotal

    @api.depends('tax_line_ids.tax_amount', 'withholding_line_ids.withholding_amount')
    def _compute_tax_totals(self):
        for line in self:
            line.tax_amount = sum(tax.tax_amount for tax in line.tax_line_ids)
            line.withholding_amount = sum(wh.withholding_amount for wh in line.withholding_line_ids)

    @api.depends('price_subtotal', 'tax_amount', 'withholding_amount')
    def _compute_total(self):
        for line in self:
            line.total = line.price_subtotal + line.tax_amount - line.withholding_amount

    @api.onchange('name', 'seller_ref')
    def _onchange_product_search(self):
        if not self.product_id and (self.name or self.seller_ref):
            if self.previous_product_id:
                return {
                    'warning': {
                        'title': 'Producto Encontrado',
                        'message': f'Se encontró el producto "{self.previous_product_id.name}" '
                                 f'usado anteriormente con este proveedor. '
                                 f'¿Desea utilizarlo?'
                    },
                    'domain': {'product_id': [('id', 'in', self.product_suggestion_ids.ids)]}
                }

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            # Información básica del producto
            self.name = self.product_id.name
            self.product_default_code = self.product_id.default_code

            # Buscar información específica del proveedor
            if self.recepcion_id.supplier_id:
                seller = self.product_id.seller_ids.filtered(
                    lambda s: s.partner_id == self.recepcion_id.supplier_id
                )
                if seller:
                    self.seller_ref = seller[0].product_code
                    if seller[0].price:
                        self.price_unit = seller[0].price

            # Asignar cuenta contable
            self.account_id = self.product_id.property_account_expense_id.id or \
                            self.product_id.categ_id.property_account_expense_categ_id.id

            # Unidad de medida
            # if self.product_id.uom_id:
            #     uom_mapping = {
            #         'unit': 'UN',
            #         'kg': 'KG',
            #         'gram': 'GR',
            #         'hour': 'HH',
            #         'day': 'DA',
            #         'meter': 'MT',
            #         'km': 'KM',
            #         'litre': 'LT',
            #         'unit': 'UN',
            #     }
            #     self.uom = uom_mapping.get(self.product_id.uom_id.name.lower(), 'UN')

    def action_create_product(self):
        self.ensure_one()
        if not self.name:
            raise ValidationError('El nombre del producto es requerido.')

        category_id = self.env['product.category'].search([('complete_name', 'ilike', 'Gastos')], limit=1)

        vals = {
            'name': self.name,
            'default_code': self.seller_ref or self.product_default_code,
            'type': 'service',
            'purchase_ok': True,
            'sale_ok': True,
            'categ_id': category_id.id if category_id else None,
            'standard_price': self.price_unit,
        }

        if self.recepcion_id.supplier_id:
            vals['seller_ids'] = [(0, 0, {
                'partner_id': self.recepcion_id.supplier_id.id,
                'product_code': self.seller_ref,
                'price': self.price_unit,
                'delay': 1,
            })]

        product = self.env['product.product'].create(vals)
        self.product_id = product.id

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'product.product',
            'res_id': product.id,
            'view_mode': 'form',
            'target': 'new',
        }




class RecepcionFacturaDianTaxLine(models.Model):
    _name = 'recepcion.factura.dian.tax.line'
    _description = 'Línea de Impuesto DIAN'

    invoice_line_id = fields.Many2one('recepcion.factura.dian.line', 'Línea de Factura')
    tax_id = fields.Many2one('account.tax', 'Impuesto')
    tax_code = fields.Selection(TAX_TYPES, 'Tipo de Impuesto')
    tax_amount = fields.Float('Monto')
    tax_base = fields.Float('Base')
    tax_percentage = fields.Float('Porcentaje')
    tax_name = fields.Char('Impuesto')
    @api.depends('tax_name', 'tax_percentage')
    def _compute_display_name(self):
        for record in self:
            record.display_name = record._get_name()

    def _get_name(self):
        """
        Retorna el nombre formateado del impuesto incluyendo el porcentaje
        Ejemplo: "IVA 19%"
        """
        self.ensure_one()
        if self.tax_name and self.tax_percentage:
            return f"{self.tax_name} {self.tax_percentage:.1f}%"
        elif self.tax_name:
            return self.tax_name
        return ""

    def name_get(self):
        """
        Personaliza la forma en que se muestra el registro en campos many2one
        """
        result = []
        for record in self:
            result.append((record.id, record._get_name()))
        return result


class RecepcionFacturaDianWithholdingLine(models.Model):
    _name = 'recepcion.factura.dian.withholding.line'
    _description = 'Línea de Retención DIAN'
    withholding_name = fields.Char('Retencion')
    invoice_line_id = fields.Many2one('recepcion.factura.dian.line', 'Línea de Factura')
    withholding_id = fields.Many2one('account.tax', 'Retención')
    withholding_code = fields.Selection(WITHHOLDING_TYPES, 'Tipo de Retención')
    withholding_amount = fields.Float('Monto')
    withholding_base = fields.Float('Base')
    withholding_percentage = fields.Float('Porcentaje')

    @api.depends('withholding_name', 'withholding_percentage')
    def _compute_display_name(self):
        for record in self:
            record.display_name = record._get_name()

    def _get_name(self):
        """
        Retorna el nombre formateado de la retención incluyendo el porcentaje
        Ejemplo: "Retefuente 2.5%"
        """
        self.ensure_one()
        if self.withholding_name and self.withholding_percentage:
            return f"{self.withholding_name} {self.withholding_percentage:.1f}%"
        elif self.withholding_name:
            return self.withholding_name
        return ""

    def name_get(self):
        """
        Personaliza la forma en que se muestra el registro en campos many2one
        """
        result = []
        for record in self:
            result.append((record.id, record._get_name()))
        return result
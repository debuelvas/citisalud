import logging
import xmltodict
from datetime import date, time, datetime
from num2words import num2words
from lxml import etree
from odoo.exceptions import UserError, ValidationError
import time

from odoo import _, api, fields, models, tools, Command
from lxml import etree
import xml.etree.ElementTree as ET
from markupsafe import Markup
from base64 import encodebytes, b64encode
from odoo.tools import html_escape
_logger = logging.getLogger(__name__)


class PaymentMethod(models.Model):
    _name = "account.payment.method.dian"

    _description = "Payment Methods"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True)  # For internal identification

    _sql_constraints = [
        ("name_code_unique", "unique (code)", "The code already exists!"),
    ]


class AccountMoveInherit(models.Model):
    _inherit = "account.move"
    
    @api.model
    def _default_method_payment(self):
        return self.env['account.payment.method.dian'].search([('code', '=', '1')], limit=1).id

    validate_cron = fields.Boolean(string="Validar con CRON", default=False, copy=False)
    diancode_id = fields.Many2one(
        "dian.document", string="Código DIAN", readonly=True, tracking=True, copy=False
    )
    state_dian_document = fields.Selection(
        string="Estado documento DIAN", related="diancode_id.state", store=True
    )
    shipping_response = fields.Selection(
        string="Respuesta de envío DIAN", related="diancode_id.shipping_response"
    )
    response_document_dian = fields.Selection(
        string="Respuesta de consulta DIAN",
        related="diancode_id.response_document_dian",
    )
    email_response = fields.Selection(
        string="Decisión del cliente",
        related="diancode_id.email_response",
        tracking=True,
    )
    response_message_dian = fields.Text(
        string="Mensaje de respuesta DIAN", related="diancode_id.response_message_dian"
    )
    is_debit_note = fields.Boolean(
        string="Nota de débito", default=False, tracking=True, copy=False,
        compute = 'comp_is_debit_note'
    )
    cufe_seed = fields.Char(string="CUFE SEED")
    QR_code = fields.Binary(
        string="Código QR", readonly=True, related="diancode_id.QR_code", 
    )
    cufe = fields.Char(string="CUFE", readonly=True, related="diancode_id.cufe")
    xml_response_dian = fields.Text(
        string="Contenido XML de la respuesta DIAN",
        readonly=True,
        related="diancode_id.xml_response_dian",
    )
    mandante_id = fields.Many2one("res.partner", "Mandante", copy=False)

    contingency_3 = fields.Boolean(
        string="Contingencia tipo 3",
        copy=False,
        default=False,
        help="Cuando el facturador no puede expedir la factura electrónica por inconvenientes tecnológicos",
    )
    contingency_4 = fields.Boolean(
        string="Contingencia tipo 4",
        copy=False,
        default=False,
        help="Cuando las causas son atribuibles a situaciones de índole tecnológico a cargo de la DIAN",
    )
    xml_response_contingency_dian = fields.Text(
        string="Mensaje de respuesta DIAN al envío de la contigencia",
        related="diancode_id.xml_response_contingency_dian",
    )
    state_contingency = fields.Selection(
        string="Estatus de contingencia", related="diancode_id.state_contingency"
    )
    contingency_invoice_number = fields.Char(
        "Número de factura de contigencia", copy=False
    )
    count_error_DIAN = fields.Integer(
        string="contador de intentos fallidos por problemas de la DIAN",
        related="diancode_id.count_error_DIAN",
    )
    in_contingency_4 = fields.Boolean(
        string="En contingencia", related="company_id.in_contingency_4"
    )
    exists_invoice_contingency_4 = fields.Boolean(
        string="Cantidad de facturas con contingencia 4 sin reportar a la DIAN",
        related="company_id.exists_invoice_contingency_4",
    )
    archivo_xml_invoice = fields.Binary(
        "archivo DIAN xml de factura", readonly=True, copy=False
    )
    xml_adjunto_ids = fields.Many2many(
        "ir.attachment",
        string="Archivo adjunto xml de factura",
        tracking=True,
        copy=False,
    )
    hide_button_dian = fields.Boolean(
        string="Ocultar", compute="_compute_HidebuttonDian", default=True
    )
    concepto_credit_note = fields.Selection(
        [("1", "Devolución parcial de los bienes y/o no aceptación parcial del servicio"),
        ("2", "Anulación de factura electrónica"),
        ("3", "Rebaja total aplicada"),
        ("4", "Ajuste de precio"),
        ("5", "Descuento comercial por pronto pago"),
        ("6", "Descuento comercial por volumen de ventas")],
        string="Credito Concepto Corrección",
    )
    concept_debit_note = fields.Selection(
        [("1", "Intereses"),
         ("2", "Gastos por cobrar"),
         ("3", "Cambio del valor"),
         ("4", "Otros"),],
        string="Debito Concepto Corrección",)
    method_payment_id = fields.Many2one(
        "account.payment.method.dian", 
        string="Metodo de Pago",        
        default=_default_method_payment,
    )
    payment_format = fields.Char(
        string="Forma de Pago", compute="_compute_get_payment_format"
    )
    document_from_other_system = fields.Char("Documento Sistema Anterior")
    date_from_other_system = fields.Date("Documento Sistema Anterior Fecha")
    date_from = fields.Date("Rango Inicial")
    date_to = fields.Date("Rango Final")
    cufe_cuds_other_system = fields.Char("CUFE/CUDS Otro sistema")
    document_without_reference = fields.Boolean('Documento sin Referencia')
    document_other_system = fields.Boolean('Documento Otro Sistema')
    refusal_reason = fields.Html('Motivo/s de rechazo', compute="_compute_refusal")
    amount_letters = fields.Char('Monto en letras', compute="_compute_amount_in_letters", store=True)
    application_response_ids = fields.Many2many('dian.application.response')
    qr_data = fields.Text(
        string="qr Data", related="diancode_id.qr_data",
    )
    attachment_ids = fields.One2many('ir.attachment', 'res_id', domain=[('res_model', '=', 'account.move')], string='Attachments')
    invoice_datetime = fields.Datetime('Fecha y hora de la factura', store=True)
    partner_contact_id = fields.Many2one(
        comodel_name='res.partner',
        string="Contacto Tercero",
        compute='_compute_partner_contact',
        store=True, readonly=False,  precompute=True,
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]",)

    @api.depends('partner_id')
    def _compute_partner_contact(self):
        for move in self:
            if move.is_invoice(include_receipts=True):
                addr = move.partner_id.address_get(['other'])
                move.partner_contact_id = addr and addr.get('other')
            else:
                move.partner_contact_id = False

    def extract_signature_value(self):
        for record in self.diancode_id:
            signature_value = ''
            if record.xml_document:
                try:
                    root = etree.fromstring(record.xml_document.encode('utf-8'))
                    signature_element = root.xpath('//ds:SignatureValue', namespaces={'ds': 'http://www.w3.org/2000/09/xmldsig#'})
                    if signature_element:
                        signature_value = signature_element[0].text
                except etree.XMLSyntaxError:
                    pass
            #record.signature_value = signature_value
            _logger.error(signature_value)
            return signature_value



    def calculate_rtefte(self):
        pass

    @api.depends('diancode_id')
    def _compute_invoice_datetime(self):
        for record in self:
            if record.diancode_id and record.diancode_id.date_document_dian \
                and record.diancode_id.date_document_dian != ' ':
                record.invoice_datetime = datetime.strptime(record.diancode_id.date_document_dian, '%Y-%m-%dT%H:%M:%S')
            else:
                record.invoice_datetime = False

    def dian_preview(self):
        for rec in self:
            if rec.cufe and rec.state_dian_document == 'exitoso':
                return {
                    'type': 'ir.actions.act_url',
                    'target': 'new',
                    'url': 'https://catalogo-vpfe.dian.gov.co/document/searchqr?documentkey=' + rec.cufe,
                }

    def dian_pdf_view(self):
        for rec in self:
            if rec.cufe and rec.state_dian_document == 'exitoso':
                return {
                    'type': 'ir.actions.act_url',
                    'target': 'new',
                    'url': 'https://catalogo-vpfe.dian.gov.co/Document/DownloadPDF?trackId=' + rec.cufe,
                }

    def comp_is_debit_note(self):
        for record in self:
            record.is_debit_note = True if record.debit_origin_id else False

    def add_application_response(self):
        response_code = self._context.get('response_code')
        ar = self.env['dian.application.response'].generate_from_electronic_invoice(self.archivo_xml_invoice, response_code)
        self.application_response_ids = [(4,ar.id)]

    @api.depends('amount_total')
    def _compute_amount_in_letters(self):
        for rec in self:
            number_dec = round((rec.amount_total-int(rec.amount_total)) * 100,0)
            palabra1 = num2words(int(rec.amount_total),lang="es")
            palabra2 = num2words(number_dec,lang="es")
            rec.amount_letters = palabra1.capitalize() + ' con ' + palabra2.replace('punto cero','') + ' centavos'


    @api.depends('xml_response_dian')
    def _compute_refusal(self):
        def safe_get(dictionary, *keys):
            """
            Navega de forma segura a través de un diccionario anidado.
            Retorna None si alguna clave no existe.
            """
            for key in keys:
                try:
                    dictionary = dictionary[key]
                except (KeyError, TypeError):
                    return None
            return dictionary

        def get_status_style(status_code=None, has_errors=False):
            """
            Determina el estilo visual basado en el estado y errores.
            """
            if status_code == '00' or (status_code == '99' and 'Documento procesado anteriormente' in str(has_errors)):
                return 'success'
            elif status_code == '99' or has_errors:
                return 'error'
            return 'info'

        def build_html_message(status=None, errors=None, status_code=None):
            """
            Construye un mensaje HTML con formato consistente y estilos visuales.
            """
            style = get_status_style(status_code, errors)
            
            styles = {
                'success': 'background-color: #dff0d8; color: #3c763d; padding: 15px; border: 1px solid #d6e9c6; border-radius: 4px; margin-bottom: 20px;',
                'error': 'background-color: #f2dede; color: #a94442; padding: 15px; border: 1px solid #ebccd1; border-radius: 4px; margin-bottom: 20px;',
                'info': 'background-color: #f5f5f5; color: #31708f; padding: 15px; border: 1px solid #ddd; border-radius: 4px; margin-bottom: 20px;'
            }
            
            html_content = [f'<div style="{styles[style]}">']
            
            if status:
                html_content.append(f"<p style='margin: 0 0 10px 0;'><strong>Estado:</strong> {html_escape(status)}</p>")
            
            if errors:
                if isinstance(errors, list) and errors:
                    html_content.append("<p style='margin: 0 0 10px 0;'><strong>Detalles:</strong></p><ul style='margin: 0; padding-left: 20px;'>")
                    for error in errors:
                        html_content.append(f"<li style='margin-bottom: 5px;'>{html_escape(error)}</li>")
                    html_content.append("</ul>")
                elif isinstance(errors, str):
                    html_content.append("<p style='margin: 0 0 10px 0;'><strong>Detalles:</strong></p><ul style='margin: 0; padding-left: 20px;'>")
                    html_content.append(f"<li style='margin-bottom: 5px;'>{html_escape(errors)}</li>")
                    html_content.append("</ul>")
            
            html_content.append('</div>')
            return Markup(''.join(html_content))

        for record in self:
            if not record.xml_response_dian or not isinstance(record.xml_response_dian, (str, bytes)):
                record.refusal_reason = build_html_message(
                    status="Error de validación",
                    errors="No hay respuesta XML válida de DIAN",
                    status_code="99"
                )
                continue

            try:
                dict_data_xml = xmltodict.parse(record.xml_response_dian)
            except Exception as e:
                record.refusal_reason = build_html_message(
                    status="Error de parsing",
                    errors=f"Error al parsear la respuesta XML: {str(e)}",
                    status_code="99"
                )
                continue

            message_data = {
                'status': None,
                'errors': [],
                'status_code': None
            }

            # Procesar respuesta sincrónica o asíncrona
            for path in [
                ('s:Envelope', 's:Body', 'SendBillSyncResponse', 'SendBillSyncResult'),
                ('s:Envelope', 's:Body', 'SendTestSetAsyncResponse', 'SendTestSetAsyncResult')
            ]:
                status_code = safe_get(dict_data_xml, *path, 'b:StatusCode')
                status_desc = safe_get(dict_data_xml, *path, 'b:StatusDescription')
                status_msg = safe_get(dict_data_xml, *path, 'b:StatusMessage')
                errors = safe_get(dict_data_xml, *path, 'b:ErrorMessage', 'c:string')

                if status_code:
                    message_data['status_code'] = status_code
                if status_desc:
                    message_data['status'] = status_desc
                    if status_msg and status_msg != status_desc:
                        message_data['errors'].append(status_msg)

                if errors:
                    if isinstance(errors, str):
                        message_data['errors'].append(errors)
                    elif isinstance(errors, list):
                        message_data['errors'].extend(errors)

            # Procesar DocumentResponse si no hay información previa
            if not message_data['errors'] and not message_data['status']:
                doc_response = safe_get(dict_data_xml, 'ApplicationResponse', 'cac:DocumentResponse')
                if doc_response:
                    response = safe_get(doc_response, 'cac:Response')
                    if response:
                        response_code = safe_get(response, 'cbc:ResponseCode')
                        description = safe_get(response, 'cbc:Description')
                        
                        if description:
                            message_data['status'] = description
                        if response_code:
                            message_data['status_code'] = response_code
                            message_data['errors'].append(f"Código de respuesta: {response_code}")

                    # Procesar errores de línea
                    line_responses = safe_get(doc_response, 'cac:LineResponse')
                    if isinstance(line_responses, list):
                        for line in line_responses:
                            line_id = safe_get(line, 'cac:LineReference', 'cbc:LineID')
                            line_response = safe_get(line, 'cac:Response')
                            
                            if line_response:
                                line_error = []
                                if line_id:
                                    line_error.append(f"Línea {line_id}")
                                
                                line_code = safe_get(line_response, 'cbc:ResponseCode')
                                line_description = safe_get(line_response, 'cbc:Description')
                                
                                if line_code:
                                    line_error.append(f"Código: {line_code}")
                                if line_description:
                                    line_error.append(f"Descripción: {line_description}")
                                
                                if line_error:
                                    message_data['errors'].append(" - ".join(line_error))

            record.refusal_reason = build_html_message(
                status=message_data['status'],
                errors=message_data['errors'],
                status_code=message_data['status_code']
            )

    @api.depends("invoice_date", "invoice_date_due")
    def _compute_get_payment_format(self):
        payment_format = ""
        for rec in self:
            invoice_date = rec.invoice_date
            due_date = rec.invoice_date_due
            if invoice_date == due_date:
                payment_format = "Contado"
            else:
                payment_format = "Credito"

            rec.payment_format = payment_format

    @api.depends(
        "journal_id.sequence_id.use_dian_control",
        "move_type",
        "state",
        "state_dian_document"
    )
    def _compute_HidebuttonDian(self):
        for move in self:
            # El botón debe mostrarse si todas estas condiciones son verdaderas:
            show_button = (
                move.journal_id.sequence_id.use_dian_control and
                move.move_type in ("out_invoice", "out_refund", "in_invoice", "in_refund") and
                move.state == "posted" and
                move.state_dian_document != "exitoso"
            )
            move.hide_button_dian = not show_button

    def button_draft(self):
        for record in self:
            if record.state_dian_document == "exitoso" and \
            not self.env.user.has_group('l10n_co_e-invoice.group_validation_invoice'):
                raise UserError(
                    _(
                        "No se puede establecer en borrador a un documento ya validado por DIAN"
                    )
                )
        return super(AccountMoveInherit, self).button_draft()




    @api.model
    def create(self, vals):
        if "move_type" in vals:
            if vals["move_type"] == "out_refund":
                if "refund_invoice_id" in vals and "invoice_payment_term_id" in vals:
                    rec_account_invoice = self.env["account.move"].search(
                        [("id", "=", vals["refund_invoice_id"])]
                    )
                    vals["payment_term_id"] = rec_account_invoice.payment_term_id.id
        return super(AccountMoveInherit, self).create(vals)

    @api.onchange("contingency_3")
    def _onchange_contingency_3(self):
        if not self.contingency_3:
            self.contingency_invoice_number = ""


    def button_cancel(self):
        if self.state_dian_document == "exitoso":
            raise UserError(_("Una factura en estado exitoso, no puede ser cancelada"))

        rec = super(AccountMoveInherit, self).button_cancel()
        return rec

    def action_invoice_email_dian(self):
        for record in self:
            dian_constants = record.diancode_id._generate_dian_constants(record, record.move_type, False)
            record.diancode_id.enviar_email_attached_document(
                record.diancode_id.xml_response_dian,
                dian_document=record.diancode_id,
                dian_constants=dian_constants,
                data_header_doc=record,
            )

    def action_invoice_dian_resend(self):
        """ Open a window to compose an email, with the edi invoice dian template
            message loaded by default
        """
        self.ensure_one()

        compose_form = self.env.ref("mail.email_compose_message_wizard_form", False)
        ctx = dict(
            default_model="account.move",
            default_res_id=self.id,
            default_use_template=bool(template),
            default_template_id=template and template.id or False,
            default_composition_mode="comment",
            mark_invoice_as_sent=True,
        )
        return {
            "name": _("Compose Email"),
            "type": "ir.actions.act_window",
            "view_type": "form",
            "view_mode": "form",
            "res_model": "mail.compose.message",
            "views": [(compose_form.id, "form")],
            "view_id": compose_form.id,
            "target": "new",
            "context": ctx,
        }

    def action_send_and_print(self):
        template = self.env.ref(
            "l10n_co_e-invoice.email_template_edi_invoice_dian", False
        )

        if any(not x.is_sale_document(include_receipts=True) for x in self):
            raise UserError(_("You can only send sales documents"))

        return {
            'name': _("Send"),
            'type': 'ir.actions.act_window',
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': 'account.move.send',
            'target': 'new',
            'context': {
                'active_ids': self.ids,
                'default_mail_template_id': template and template.id or False,
            },
        }

    # verificar invoice_line_ids - tax_line_ids
    def create_nota_debit(self):
        invoice_new = self.env["account.move"]
        invoice_new = invoice_new.create(
            {
                "partner_id": self.partner_id.id,
                "company_id": self.company_id.id,
                "state": "draft",
                "move_type": self.move_type,
                "is_move_sent": self.is_move_sent,
                "invoice_origin": self.name,
                "invoice_date": date.today(),
                "invoice_payment_term_id": self.invoice_payment_term_id.id,
                "date": date.today(),
                "invoice_date_due": self.invoice_date_due,
                "user_id": self.env.uid,
                "currency_id": self.currency_id.id,
                "commercial_partner_id": self.commercial_partner_id.id,
                "partner_shipping_id": self.partner_shipping_id.id,
                "team_id": self.team_id.id,
                "resolution_date": self.resolution_date,
                "resolution_date_to": self.resolution_date_to,
                "resolution_number_from": self.resolution_number_from,
                "resolution_number_to": self.resolution_number_to,
                "resolution_number": self.resolution_number,
                "is_debit_note": True,
            }
        )

        if invoice_new:
            for line_invoice in self.invoice_line_ids:
                invoice_line_new = []
                invoice_tax_line_new = []
                invoice_line_tax = []
                for invoice_line_tax in line_invoice.tax_ids:
                    invoice_tax_line_new.append(
                        (0, 0, {"tax_id": invoice_line_tax.id,})
                    )

                invoice_line_new.append(
                    (
                        0,
                        0,
                        {
                            "price_unit": line_invoice.price_unit,
                            "price_subtotal": line_invoice.price_subtotal,
                            "currency_id": line_invoice.currency_id.id,
                            "product_uom_id": line_invoice.product_uom_id.id,
                            "partner_id": line_invoice.partner_id.id,
                            "sequence": line_invoice.sequence,
                            "company_id": line_invoice.company_id.id,
                            "account_id": line_invoice.account_id.id
                            if line_invoice.account_id
                            else None,
                            "name": line_invoice.name,
                            "product_id": line_invoice.product_id.id,
                            "move_id": line_invoice.move_id.id,
                            "quantity": line_invoice.quantity,
                            "purchase_line_id": line_invoice.purchase_line_id.id,
                            "tax_ids": line_invoice.tax_ids,
                        },
                    )
                )
                invoice_new.invoice_line_ids = invoice_line_new
        my_view = self.env.ref("account.view_move_form")
        return {
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "name": self.name,
            "view_id": my_view.id,
            "view_mode": "form",
            "res_id": invoice_new.id,
        }

    def hook_type_invoice(self, data):
        return data


    def action_post(self):
        rec = super(AccountMoveInherit, self).action_post()
        for record in self:
            if record.journal_id.sequence_id.use_dian_control:
                errors = []
                company = record.company_id
                partner = record.partner_id
                if record.move_type in record.hook_type_invoice(["out_invoice"]):
                    if record.debit_origin_id:
                        sequence_code = record.journal_id.debit_note_sequence_id.code

                        if not sequence_code:
                            errors.append("Debe definir el código de secuencia de la nota de débito en Ajuste / Técnico / Secuencia")

                        else:
                            rec_sequence_nd = self.env["ir.sequence"]
                            number = rec_sequence_nd.next_by_code(sequence_code)
                            record.name = number

                    if record.move_type in ["in_invoice", "in_refund"] and record.partner_id.country_id.code == "CO":
                        if not record.partner_id.zip :
                            errors.append("El cliente no tiene zip en su formulario, por favor complételo")
                        elif len(record.partner_id.zip) != 6 and record.partner_id.country_id.code == "CO":
                            errors.append("El zip del cliente está mal formado, debe contener 6 dígitos")
                    result_error = partner._check_vat_fe()
                    if result_error:
                        raise UserError("\n".join(result_error))
                    resol = record.journal_id.sequence_id.dian_resolution_ids.filtered(lambda r: r.active_resolution)

                    if not resol:
                        errors.append("La factura no tiene resolución DIAN asociada.")
                        errors.append("La resolución DIAN asociada a la factura no existe.")

                    if not resol.technical_key:
                        errors.append("La resolución DIAN no tiene asociada la clave técnica.")

                    required_company_fields = [
                        ("software_identification_code", "el código de identificación del software."),
                        ("password_environment", "el password del ambiente."),
                    ]
                    for field, message in required_company_fields:
                        if not getattr(company, field):
                            errors.append(f"Se debe asociar {message}")
                    

                    if record.invoice_line_ids:
                        for line in record.invoice_line_ids.filtered(lambda line: line.display_type == 'product'):
                            if line.tax_ids:
                                for tax in line.tax_ids:
                                    if not tax.tributes:
                                        errors.append("Algunos impuestos indicados en la factura no tienen un tributo asociado según los tributos indicados en la tabla 6.2.2 Tributos.")
                            else:
                                errors.append("¡Error! La línea de factura no tiene impuestos asociados.")

                    if not record.partner_id.email:  # or not self.partner_id.email_fe:
                        errors.append("El cliente no tiene definido un email.")

                if errors:
                    raise UserError("\n".join(errors))

                record.send_dian_document_new()

        return rec

    def validate_dian(self):
        return self.send_dian_document_new()

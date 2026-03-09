import logging
import xmltodict
from datetime import date, time, datetime
from num2words import num2words

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

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

    validate_cron = fields.Boolean(string="Validar con CRON", default=False, copy=False)
    diancode_id = fields.Many2one(
        "dian.document", string="Código DIAN", readonly=True, tracking=True, copy=False
    )
    state_dian_document = fields.Selection(
        string="Estado documento DIAN", related="diancode_id.state"
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
        string="Código QR", readonly=True, related="diancode_id.QR_code", tracking=True,
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
        "archivo DIAN xml de factura", readonly=True, tracking=True, copy=False
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
        [("1","Devolución parcial de los bienes y/o no aceptación parcial del servicio"),
        ("2", "Anulación de factura electrónica"),
        ("3", "Rebaja  o descuento parcial o total"),
        ("4", "Ajuste de precio"),
        ("5", "Otros"),],
        string="Credito Concepto Corrección",
    )
    concept_debit_note = fields.Selection(
        [("1", "Intereses"),
         ("2", "Gastos por cobrar"),
         ("3", "Cambio del valor"),
         ("4", "Otros"),],
        string="Debito Concepto Corrección",)
    method_payment_id = fields.Many2one(
        "account.payment.method.dian", string="Metodo de Pago"
    )
    payment_format = fields.Char(
        string="Forma de Pago", compute="_compute_get_payment_format"
    )
    document_from_other_system = fields.Char("Documento Sistema Anterior")
    date_from_other_system = fields.Date("Documento Sistema Anterior Fecha")
    cufe_cuds_other_system = fields.Char("CUFE/CUDS Otro sistema")
    document_without_reference = fields.Boolean('Documento sin Referencia')
    refusal_reason = fields.Text('Motivo/s de rechazo', compute="_compute_refusal")
    amount_letters = fields.Char('Monto en letras', compute="_compute_amount_in_letters", store=True)
    application_response_ids = fields.Many2many('dian.application.response')
    qr_data = fields.Text(
        string="qr Data", related="diancode_id.qr_data",
    )
    attachment_ids = fields.One2many('ir.attachment', 'res_id', domain=[('res_model', '=', 'account.move')], string='Attachments')
    invoice_datetime = fields.Datetime('Fecha y hora de la factura', store=True)

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

    def _compute_refusal(self):
        for rec in self:
            if rec.state_dian_document == 'rechazado':
                rec.refusal_reason = ''
                dict_data_xml = xmltodict.parse(rec.xml_response_dian)
                if rec.company_id.production:
                    #Consultamos por errores en produccion:
                    recorrido = dict_data_xml['s:Envelope']['s:Body']['SendBillSyncResponse']['SendBillSyncResult']['b:ErrorMessage']['c:string'] if 'c:string' in dict_data_xml['s:Envelope']['s:Body']['SendBillSyncResponse']['SendBillSyncResult']['b:ErrorMessage'] else []
                else:
                #Consultamos por errores fuera en homologacion
                    recorrido = dict_data_xml['s:Envelope']['s:Body']['GetStatusZipResponse']['GetStatusZipResult']['b:DianResponse']['b:ErrorMessage']['c:string'] if 'c:string' in dict_data_xml['s:Envelope']['s:Body']['GetStatusZipResponse']['GetStatusZipResult']['b:DianResponse']['b:ErrorMessage'] else []
                #Si por algun motivo los errores no son interpretados devolvemos '' para no dar error en odoo
                if recorrido == []:
                    rec.refusal_reason = ''
                if rec.xml_response_dian.count('<c:string>') == 1:
                    rec.refusal_reason = recorrido
                else:
                    for n in recorrido:
                        rec.refusal_reason += n + '\n'
            else:
                rec.refusal_reason = ''

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
        "line_ids.debit",
        "line_ids.credit",
        "line_ids.currency_id",
        "line_ids.amount_currency",
        "line_ids.amount_residual",
        "line_ids.amount_residual_currency",
        "line_ids.payment_id.state",
        "amount_tax",
        "amount_tax_signed",
    )
    def _compute_HidebuttonDian(self):
        for x in self:
            x.hide_button_dian = (
                x.journal_id.sequence_id.use_dian_control
                and x.move_type
                in ("out_invoice", "out_refund", "in_invoice", "in_refund")
            ) and (x.state_dian_document == "exitoso" or x.state != "posted")

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



    # @api.multi
    def write(self, vals):
        for invoice in self:
            before_state = invoice.state

            after_state = invoice.state

            if "state" in vals:
                after_state = vals["state"]

            rec_dian_document = self.env["dian.document"].search(
                [("document_id", "=", invoice.id)]
            )
            if not rec_dian_document:
                if (
                    before_state == "draft"
                    and after_state == "posted"
                    and invoice.move_type == "out_invoice"
                    and not invoice.debit_origin_id
                ):
                    (
                        invoice.env["dian.document"]
                        .sudo()
                        .create({"document_id": invoice.id, "document_type": "f"})
                    )

                if (
                    before_state == "draft"
                    and after_state == "posted"
                    and invoice.move_type == "out_refund"
                ):
                    (
                        invoice.env["dian.document"]
                        .sudo()
                        .create({"document_id": invoice.id, "document_type": "c"})
                    )

                if (
                    before_state == "draft"
                    and after_state == "posted"
                    and invoice.move_type == "out_invoice"
                    and invoice.debit_origin_id
                ):
                    (
                        invoice.env["dian.document"]
                        .sudo()
                        .create({"document_id": invoice.id, "document_type": "d"})
                    )

        return super(AccountMoveInherit, self).write(vals)

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
            dian_constants = record.diancode_id._get_dian_constants(record)
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
        template = self.env.ref(
            "l10n_co_e-invoice.email_template_edi_invoice_dian", False
        )
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

        if self.journal_id.sequence_id.use_dian_control:
            errors = []
            company = self.company_id
            partner = self.partner_id
            if self.move_type in self.hook_type_invoice(["out_invoice"]):
                if self.debit_origin_id:
                    sequence_code = self.journal_id.debit_note_sequence_id.code

                    if not sequence_code:
                        errors.append("Debe definir el código de secuencia de la nota de débito en Ajuste / Técnico / Secuencia")

                    else:
                        rec_sequence_nd = self.env["ir.sequence"]
                        number = rec_sequence_nd.next_by_code(sequence_code)
                        self.name = number

                if self.move_type in ["in_invoice", "in_refund"]:
                    if not self.partner_id.zip and self.partner_id.country_id.code == "CO":
                        errors.append("El cliente no tiene zip en su formulario, por favor complételo")
                    elif len(self.partner_id.zip) != 6 and self.partner_id.country_id.code == "CO":
                        errors.append("El zip del cliente está mal formado, debe contener 6 dígitos")
                if partner.city_id == False or partner.state_id == False and self.partner_id.country_id.code == "CO":
                    errors.append("El cliente/proveedor no tiene ciudad en su formulario, por favor complételo")

                resol = self.journal_id.sequence_id.dian_resolution_ids.filtered(lambda r: r.active_resolution)

                if not resol:
                    errors.append("La factura no tiene resolución DIAN asociada.")
                    errors.append("La resolución DIAN asociada a la factura no existe.")

                if not resol.technical_key:
                    errors.append("La resolución DIAN no tiene asociada la clave técnica.")

                required_company_fields = [
                    ("document_repository", "un repositorio en donde se almacenarán los archivos de FE."),
                    ("software_identification_code", "el código de identificación del software."),
                    ("password_environment", "el password del ambiente."),
                ]
                for field, message in required_company_fields:
                    if not getattr(company, field):
                        errors.append(f"Se debe asociar {message}")
                
                required_partner_fields = [
                    ("country_id", "registrado el país."),
                    ("vat_co", "registrado el NIT."),
                    ("company_type", "identificada como persona jurídica o persona natural."),
                    ("l10n_co_document_code", "asociada un tipo de documento."),
                    #("state_id", "asociada un estado."),
                    ("tribute_id", "asociada un tributo."),
                    ("fiscal_responsability_ids", "asociada una responsabilidad fiscal."),
                    #("city_id", "asociada un municipio."),
                    ("street", "asociada una dirección."),
                ]
                for field, message in required_partner_fields:
                    if not getattr(partner, field):
                        errors.append(f"Su empresa no tiene {message}")

                if self.invoice_line_ids.filtered(lambda line: line.display_type == 'product'):
                    for line in self.invoice_line_ids:
                        if line.tax_ids:
                            for tax in line.tax_ids:
                                if tax.tax_group_fe not in ["iva_fe", "ica_fe", "ico_fe", "ret_fe", "nap_fe"]:
                                    errors.append("La factura contiene impuestos que no están asociados al grupo de impuestos DIAN FE.")
                                if not tax.tributes:
                                    errors.append("Algunos impuestos indicados en la factura no tienen un tributo asociado según los tributos indicados en la tabla 6.2.2 Tributos.")
                        else:
                            errors.append("¡Error! La línea de factura no tiene impuestos asociados.")

                if not self.partner_id.email:  # or not self.partner_id.email_fe:
                    errors.append("El cliente no tiene definido un email.")

            if errors:
                raise UserError("\n".join(errors))

            self.validate_dian()

        return rec

    def validate_dian(self):
        document_dian = self.env["dian.document"].search([("document_id", "=", self.id)], limit=1)
        if not document_dian and self.state == "posted" and self.move_type == "out_invoice" and not self.is_debit_note:
            document_dian = self.env["dian.document"].sudo().create({"document_id": self.id, "document_type": "f"})
            
        # If 'document_dian' still doesn't exist at this point, raise an error.
        if not document_dian:
            raise UserError(_("No se pudo encontrar ni crear un documento DIAN para esta transacción."))
    
        # Validamos que el partner tenga tributos y resposabilidad fiscal
        if not self.partner_id.tribute_id:
            raise UserError(_("El contacto a facturar no tiene tributos asiganados"))
        if not self.partner_id.fiscal_responsability_ids:
            raise UserError(_("El contacto a facturar no tiene Responsabilidad Fiscal asiganada"))

        # Validamos que el partner tenga DV
        if self.partner_id.dv not in [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]:
            raise UserError(_("El contacto a facturar no tiene Digito Verificador"))

        # Validamos que todas las lineas de factura tengan un producto asignado
        for line in self.invoice_line_ids.filtered(lambda line: line.display_type == 'product'):
            if len(line.product_id) < 1:
                raise UserError(_("La linea con descripcion: {0} debe tener un producto asignado en la columna de Producto".format(line.name)))

        # if not document_dian:
        #     if (
        #         self.state == "posted"
        #         and self.move_type == "out_invoice"
        #         and not self.is_debit_note
        #     ):
        #         document_dian = (
        #             self.env["dian.document"]
        #             .sudo()
        #             .create({"document_id": self.id, "document_type": "f"})
        #         )

        if self.in_contingency_4:
            # Documento de ND
            if self.move_type == "out_invoice" and self.debit_origin_id:
                raise UserError(
                    _(
                        "No puede validar notas de débito mientras se encuentra en estado de contingencia tipo 4"
                    )
                )
            # Documento de NC
            elif self.move_type == "out_refund":
                raise UserError(
                    _(
                        "No puede validar notas de crédito mientras se encuentra en estado de contingencia tipo 4"
                    )
                )
            if self.state_contingency == "exitosa":
                raise UserError(
                    _(
                        "Factura de contingencia tipo 4 ya fue enviada al cliente. Una vez se restablezca el servicio, debe pulsar este bóton para enviar la contingencia tipo 4 bota la DIAN"
                    )
                )

        if document_dian.state == "rechazado":
            document_dian.response_message_dian = " "
            document_dian.xml_response_dian = " "
            document_dian.xml_send_query_dian = " "
            document_dian.response_message_dian = " "
            document_dian.xml_document = " "
            document_dian.xml_file_name = " "
            document_dian.zip_file_name = " "
            document_dian.cufe = " "
            document_dian.date_document_dian = " "
            document_dian.write({"state": "por_notificar", "resend": False})
            if self.in_contingency_4 and not self.contingency_3:
                document_type = document_dian.document_type
            else:
                document_type = (
                    document_dian.document_type
                    if not self.contingency_3
                    else "contingency"
                )
            document_dian.send_pending_dian(document_dian.id, document_type)

        if document_dian.state == ("por_notificar"):
            if self.in_contingency_4 and not self.contingency_3:
                document_type = document_dian.document_type
            else:
                document_type = (
                    document_dian.document_type
                    if not self.contingency_3
                    else "contingency"
                )
            document_dian.send_pending_dian(document_dian.id, document_type)

        company = (
            self.env["res.company"].sudo().search([("id", "=", self.company_id.id)])
        )
        # Ambiente pruebas
        if not company.production and not self.in_contingency_4:
            if document_dian.state == "por_validar":
                document_dian.request_validating_dian(document_dian.id)
        # Determina si existen facturas con contingencias tipo 4 que no han sidoenviadas a la DIAN
        # company.exists_invoice_contingency_4 = False
        documents_dian_contingency = self.env["dian.document"].search(
            [
                ("state", "=", "por_notificar"),
                ("contingency_4", "=", True),
                ("document_type", "=", "f"),
            ]
        )
        company.exists_invoice_contingency_4 = bool(documents_dian_contingency)
        return



from  odoo import models, fields, api, _
from odoo.exceptions import Warning
from datetime import timedelta, datetime

class HospitalRIPS(models.Model):
    _inherit = "hospital.rips"

    rip_type = fields.Selection(
        string="Type",
        selection=[("rips", "RIPS"), ("glosa", "GLOSA")], default="rips"
    )
    sale_invoice_id = fields.Many2many("account.move", "sale_invoice_id_rel")
    refund_invoice_ids = fields.Many2many("account.move", "refund_invoice_id_rel", string="Refund Invoices", copy=False)
    claim_line_ids = fields.One2many("claim.line.ept", "claim_id", string="Return Line")

class MlNotesRMA(models.Model):
    _name = "ml.notes.rma"
    _description = 'RMA Notes'

    note_type = fields.Selection(
        string="Type",
        selection=[
            ("problem_detected", "Problema Detectado"),
            ("actions_to_take", "Acciones a tomar"),
            ("technic_resolution", "Resolución Técnica"),
            ("administrative_resolution", "Resolución Administrativa"),
        ],
    )


class MLNotesMixing(models.AbstractModel):
    _name = "ml.notes.mixing.rma"
    _description = "Mixin for RMA Notes"

    note_ids = fields.One2many(comodel_name="ml.notes.rma", inverse_name="res_id")

    def open_notes(self):
        view_id = self.env.ref("rma_ept.ml_notes_rma_mixing_view_form").id
        return {
            "name": _("Notes"),
            "type": "ir.actions.act_window",
            "view_type": "form",
            "view_mode": "form",
            "res_id": self.id,
            "view_id": view_id,
            "res_model": self._name,
            "target": "new",
        }



class CRMClaimLine(models.Model):
    _name = "claim.line.ept"
    _inherit = [
        "ml.notes.mixing.rma",
        "mail.thread",
        "rating.mixin",
        "mail.activity.mixin",
    ]
    _description = "RMA Claim Line"
    _rec_name = "product_description"

    def _track_template(self, tracking):
        res = super(CRMClaimLine, self)._track_template(tracking)
        claim_line = self[0]
        # changes, tracking_value_ids = tracking[claim_line.id]
        if "ept_state_id" in tracking and claim_line.ept_state_id.template_id:
            res["ept_state_id"] = (
                claim_line.ept_state_id.template_id,
                {
                    "auto_delete_message": True,
                    "subtype_id": self.env["ir.model.data"].xmlid_to_res_id(
                        "mail.mt_note"
                    ),
                    "notif_layout": "mail.mail_notification_light",
                },
            )
        return res

    @api.constrains("claim_type", "claim_id")
    def check_action(self):
        for rec in self.filtered(
            lambda x: x.rma_reason_id and x.rma_reason_id.action and x.claim_type
        ):
            if rec.claim_type != rec.rma_reason_id.action:
                raise Warning(_("The action is not related with the reason"))

    product_id = fields.Many2one("product.product", string="Product")
    product_reference = fields.Char(related="product_id.default_code")
    product_description = fields.Char(related="account_line_id.name ", required=True)
    product_categ_id = fields.Many2one(related="product_id.categ_id", string="Business Unit")
    quantity = fields.Float("Return Quantity", copy=False, related="account_line_id.quantity")
    claim_id = fields.Many2one("crm.claim.ept", string="Related claim", copy=False, ondelete="cascade")
    claim_type = fields.Selection(
        [("refund", "Nota Credito"), ("info", "Informacion"), ("legibilidad", "Legibilidad")],
        "Claim Type",
        copy=False,
    )
    to_be_replace_product_id = fields.Many2one(
        "product.product", "Product to be Replace", copy=False
    )
    to_be_replace_quantity = fields.Float("Replace Quantity", copy=False)
    to_be_name = fields.Char('Referencia')
    is_create_invoice = fields.Boolean("Create Invoice", copy=False)
    is_create_refund = fields.Boolean(string="Create Refund", copy=False)
    rma_reason_id = fields.Many2one("rma.reason.ept", "Reason")
    ept_state_id = fields.Many2one(
        comodel_name="crm.claim.ept.state",
        string="State",
        tracking=True,
        required=True,
        default=lambda self: self.env.ref("rma_ept.rma_ept_state_draft"),
    )
    is_cancelled = fields.Boolean(string="")
    note = fields.Text()
    note_type = fields.Selection(
        string="Note Type",
        selection=[
            ("problem_detected", "Problem Detected"),
            ("actions_take", "Actions to Take"),
            ("technical_resolution", "Technical Resolution"),
            ("admin_resolution", "Administrative Resolution"),
            ("cancelled", "Cancel Reason"),
        ],
    )
    total_amount = fields.Monetary(
        currency_field="currency_id",
        compute="_compute_total_amount",
    )
    currency_id = fields.Many2one(related="account_line_id.currency_id")
    price_unit = fields.Float(related="account_line_id.price_unit")
    account_line_id = fields.Many2one(
        comodel_name="account.move.line",
    )
    unique_code = fields.Char()

    def rating_get_partner_id(self):
        if self.claim_id.partner_id:
            return self.claim_id.partner_id

        return super(CRMClaimLine, self).rating_get_partner_id()

    def rating_get_rated_partner_id(self):
        if self.claim_id.user_id:
            return self.claim_id.user_id.partner_id
        return super(CRMClaimLine, self).rating_get_rated_partner_id()

    @api.depends("price_unit", "quantity")
    def _compute_total_amount(self):
        for rec in self:
            rec.total_amount = rec.price_unit * rec.quantity

    @api.model
    def check_warranty(self, product_id, date_done, date_end):
        """This function check the warranty from the product
        and return True or False depens on date_done"""
        if not (product_id.warranty and date_end and date_done):
            return False
        unit = product_id.warranty
        if product_id.warranty_type == "day":
            date_done += timedelta(days=unit)
        elif product_id.warranty_type == "week":
            date_done += timedelta(days=unit * 7)
        elif product_id.warranty_type == "month":
            date_done = datetime(date_done.year, date_done.month + unit, 1) + timedelta(
                days=date_done.day
            )
        elif product_id.warranty_type == "year":
            date_done += timedelta(days=unit * 365)
        return date_done >= date_end


    def button_edit_note(self):
        self.ensure_one()
        view = self.env.ref("rma_ept.ept_line_note_view_form")
        if self.is_cancelled and self.note_type == "cancelled":
            self.write({"note_type": False, "note": False})
        return {
            "name": _("Notas"),
            "type": "ir.actions.act_window",
            "view_type": "form",
            "view_mode": "form",
            "res_model": self._name,
            "views": [(view.id, "form")],
            "view_id": view.id,
            "target": "new",
            "res_id": self.id,
            "context": self.env.context,
        }

    def button_confirm(self):
        self.write({"is_cancelled": False})

    def button_open_cancel_view(self):
        self.ensure_one()
        view = self.env.ref("rma_ept.ept_line_cancel_view_form")
        self.write({"note_type": "cancelled", "note": False, "is_cancelled": True})
        return {
            "name": _("Notas"),
            "type": "ir.actions.act_window",
            "view_type": "form",
            "view_mode": "form",
            "res_model": self._name,
            "views": [(view.id, "form")],
            "view_id": view.id,
            "target": "new",
            "res_id": self.id,
            "context": self.env.context,
        }

    def write(self, vals):
        for record in self:
            msg = ""

            product_name = self.env["product.product"].search_read(
                [("id", "=", vals.get("product_id"))], ["name"]
            )
            product_name = product_name and product_name[0][1] or record.product_id.name

            if vals.get("ept_state_id"):
                if record.ept_state_id and record.ept_state_id.id != vals.get(
                    "ept_state_id"
                ):
                    new_state = self.env["crm.claim.ept.state"].browse(
                        vals.get("ept_state_id")
                    )

                    msg += _(
                        "State of %s: %s → %s\n"
                        % (product_name, record.ept_state_id.name, new_state.name)
                    )

            if vals.get("is_cancelled"):
                msg += _(
                    "Line with product %s cancelled for : %s\n"
                    % (product_name, vals.get("note", _("No reason")))
                )
            if msg:
                post_vars = {"body": msg}
                record.claim_id.message_post(message_type="comment", **post_vars)
        return super(CRMClaimLine, self).write(vals)

    @api.onchange("rma_reason_id")
    def _onchange_rma_reason_id(self):
        for rma_line in self:
            rma_line.claim_type = rma_line.rma_reason_id.action

    def unlink(self):
        for record in self:
            if record.claim_id and record.claim_id.state != "open":
                raise Warning(_("Claim Line cannot be delete once it Approved."))
        return super(CRMClaimLine, self).unlink()

    def action_claim_refund_process_ept(self):
        return {
            "name": "Return Products",
            "type": "ir.actions.act_window",
            "view_type": "form",
            "view_mode": "form",
            "res_model": "claim.process.wizard",
            "src_model": "claim.line.ept",
            "target": "new",
            "context": {
                "product_id": self.product_id.id,
                "hide": True,
                "claim_line_id": self.id,
            },
        }


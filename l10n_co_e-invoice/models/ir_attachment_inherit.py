from odoo import fields, models


class IrAttachmentInherit(models.Model):
    _inherit = "ir.attachment"

    type = fields.Selection(
        selection_add=[("out_invoice", "Out Invoice"), ("out_refund", "Out Refund")],
        ondelete={"out_invoice": "set default", "out_refund": "set default"},
    )




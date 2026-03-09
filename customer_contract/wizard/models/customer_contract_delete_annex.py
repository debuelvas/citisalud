from odoo import api, fields, models


class CustomerContractDeleteAnnex(models.TransientModel):
    _name = "customer.contract.delete.annex"
    _description = "Eliminador de otrosí"

    def _domain_annex(self):
        if "active_id" not in self._context:
            return []
        return [("customer_contract_id", "=", self._context["active_id"])]

    annexs_ids = fields.Many2many(
        comodel_name="customer.contract.annex", string="Otrosi", domain=_domain_annex
    )

    def delete_customer_contract_annex(self):
        self.annexs_ids.unlink()

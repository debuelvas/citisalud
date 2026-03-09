from odoo import api, fields, models

TYPE = [("time", "Prórroga"), ("money", "Adición")]


class CustomerContractCreateAnnex(models.TransientModel):
    _name = "customer.contract.create.annex"
    _description = "Creador de otrosí"

    def _domain_documents(self, type):
        if "active_id" not in self._context:
            return []
        return [("type", "=", type), ("customer_contract_id", "=", self._context["active_id"])]

    def _domain_cdp(self):
        return self._domain_documents("CDP")

    def _domain_rp(self):
        return self._domain_documents("RP")

    type = fields.Selection(string="Tipo", selection=TYPE, required=True, default="time")
    file = fields.Binary(string="Documento", required=True)
    date = fields.Date(string="Fecha")
    amount = fields.Float(string="Monto")
    cdp_id = fields.Many2one(
        comodel_name="customer.contract.report.budget", string="CDP", domain=_domain_cdp
    )
    rp_id = fields.Many2one(
        comodel_name="customer.contract.report.budget", string="RP", domain=_domain_rp
    )

    def create_customer_contract_annex(self):
        cc = self.env["customer.contract"].browse(self._context["active_id"])
        new_annex = {
            "customer_contract_id": cc.id,
            "type": self.type,
            "file": self.file,
            "sequence": cc.get_next_seq_annex(self.type),
        }
        if self.type == "time":
            new_annex["date"] = self.date
        else:
            new_annex.update(
                {
                    "amount": self.amount,
                    "cdp_id": self.cdp_id.id,
                    "rp_id": self.rp_id.id,
                }
            )
        self.env["customer.contract.annex"].create(new_annex)

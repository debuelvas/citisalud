from odoo import api, fields, models


class CustomerContractDeleteReportBudget(models.TransientModel):
    _name = "customer.contract.delete.report.budget"
    _description = "Eliminador de documentos"

    def _domain_report_budget(self):
        if "active_id" not in self._context:
            return []
        return [("customer_contract_id", "=", self._context["active_id"])]

    reports_budget_ids = fields.Many2many(
        comodel_name="customer.contract.report.budget",
        relation="delete_cc_report_budget_rel",
        string="Documentos",
        domain=_domain_report_budget,
    )

    def delete_customer_contract_report_budget(self):
        self.reports_budget_ids.unlink()

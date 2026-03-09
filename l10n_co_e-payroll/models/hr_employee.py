from odoo import api, fields, models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    type_worker = fields.Many2one("hr.type.worker", string="Tipo de Trabajador")
    sub_type_worker = fields.Many2one(
        "hr.sub.type.worker", string="Sub tipo de Trabajador"
    )


class HrEmployeePublic(models.Model):
    _inherit = "hr.employee.public"

    type_worker = fields.Many2one(
        "hr.type.worker", string="Tipo de Trabajador", related="employee_id.type_worker"
    )
    sub_type_worker = fields.Many2one(
        "hr.sub.type.worker",
        string="Sub tipo de Trabajador",
        related="employee_id.sub_type_worker",
    )

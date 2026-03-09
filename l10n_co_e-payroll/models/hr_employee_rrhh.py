from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.safe_eval import safe_eval


class HrEmpleado(models.Model):
    _inherit = "hr.employee"
    _description = "Empleado RRHH"

    salud_ids = fields.Many2one("res.partner", string="Salud")
    cesantias_ids = fields.Many2one("res.partner", string="Cesantias")
    pension_ids = fields.Many2one("res.partner", string="Pensión")
    caja_compensacion_ids = fields.Many2one("res.partner", string="Caja de compensación")


class HrEmployeePublic(models.Model):
    _inherit = "hr.employee.public"

    salud_ids = fields.Many2one(
        "res.partner", string="Salud", related="employee_id.salud_ids"
    )
    cesantias_ids = fields.Many2one(
        "res.partner", string="Cesantias", related="employee_id.cesantias_ids"
    )
    pension_ids = fields.Many2one(
        "res.partner", string="Pensión", related="employee_id.pension_ids"
    )
    caja_compensacion_ids = fields.Many2one(
        "res.partner", string="Caja de compensación", related="employee_id.pension_ids"
    )

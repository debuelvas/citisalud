from odoo import api, fields, models, _
from dateutil.relativedelta import relativedelta
# from datetime import datetime


class HMSDistrict(models.Model):
    _name = "hms.district"
    _description = "District"

    name = fields.Char(string="Barrio")
    # code = fields.Char(string="Code", required=True)
    # active = fields.Boolean(string="Active", default=True)
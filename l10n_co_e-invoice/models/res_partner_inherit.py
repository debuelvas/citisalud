from odoo import _, api, fields, models
from odoo.exceptions import UserError

class ResPartnerInherit(models.Model):
    _inherit = "res.partner"

    tribute_id = fields.Many2one("dian.tributes", string="Tributos", required=False)
    fiscal_responsability_ids = fields.Many2many(
        "dian.fiscal.responsability", string="Responsabilidad fiscal", required=False
    )
    is_foreign = fields.Char("Is foreign")


    def _check_vat_fe(self):
        error = []
        if not self.vat_co:
            error.append(f"Cliente / Proveedor no tiene Numero De NIT/CC {self.name}")
        if not self.dian_fiscal_regimen:
            error.append(f"Cliente / Proveedor no tiene Tributo {self.name}")
        if not self.dian_obligation_type_ids:
            error.append(f"Cliente / Proveedor no tiene responsabilidades {self.name}")
        if not self.city_id and self.country_id.code == "CO":
           error.append(f"Cliente / Proveedor no tiene Ciudad / Municipio {self.name}")
        if not self.street:
            error.append(f"Cliente / Proveedor no tiene  Direccion {self.name}")
        if not self.state_id and self.country_id.code == "CO":
            error.append(f"Cliente / Proveedor no tiene  Departamento {self.name}")
        return  error

    #@api.constrains('country_id', 'state_ids', 'foreign_vat')
    def check_info_partner(self):
        result_error = self._check_vat_fe()
        if result_error:
            raise UserError("\n".join(result_error))
        return True
    
    def _l10n_co_identification_type(self):
        self.ensure_one()
        l10n_co_document = {
            'rut': '31',
            'id_document': '',
            'id_card': '12',
            'passport': '41',
            'foreign_id_card': '42',
            'external_id': '50',
            'residence_document': '47',
            'PEP': '47',
            'civil_registration': '11',
            'national_citizen_id': '13',
            'niup_id': '91',
            'foreign_colombian_card': '21',
            'foreign_resident_card': '22',
            'diplomatic_card': '',
            'PPT': '48',
            'vat': '50',
        }

        identification_type = self.l10n_latam_identification_type_id.l10n_co_document_code
        return l10n_co_document[identification_type] if identification_type else '' 
    # @api.model
    # def create(self, values):
    #     super(ResPartnerInherit, self).create(values)
    #     self.check_info_partner()

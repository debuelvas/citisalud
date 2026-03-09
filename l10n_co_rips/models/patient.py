# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from datetime import datetime
from odoo.exceptions import UserError, ValidationError
from dateutil.relativedelta import relativedelta

HEALTH_TYPE_SELECTION = [
    ('01', 'Contributivo cotizante'),
    ('02', 'Contributivo beneficiario'),
    ('03', 'Contributivo adicional'),
    ('04', 'Subsidiado'),
    ('05', 'Sin régimen'),
    ('06', 'Especiales o de Excepción cotizante'),
    ('07', 'Especiales o de Excepción beneficiario'),
    ('08', 'Particular'),
    ('09', 'Tomador/Amparado ARL'),
    ('10', 'Tomador/Amparado SOAT'),
    ('11', 'Tomador/Amparado Planes voluntarios de salud'),
]
from odoo.osv import expression

ADDRESS_FIELDS = ['main_road', 'name_road', 'main_letter_road', 'prefix_main_road', 'sector_main_road',
                  'generator_road_number', 'generator_road_letter', 'generator_road_sector',
                  'generator_plate_number', 'generator_plate_sector', 'complement_name_a', 'complement_number_a',
                  'complement_name_b', 'complement_number_b']

class IdentificationType(models.Model):
    _inherit = 'l10n_latam.identification.type'

    dian_code = fields.Char('DIAN code')
    heath_code = fields.Char('Codigo Salud')
    def _get_complete_name(self):
        res = []
        for record in self:
            name = u'[%s] %s' % (record.dian_code or '', record.name)
            res.append((record.id, name))
        return res

    @api.depends('name', 'dian_code')
    def _compute_display_name(self):
        for template in self:
            template.display_name = False if not template.name else (
                '{}{}'.format(
                    template.dian_code and '[%s] ' % template.dian_code or '', template.name
                ))
    @api.model
    def _name_search(self, name, args=None, operator='ilike',
                     limit=100, name_get_uid=None,order=None):
        args = args or []
        if operator == 'ilike' and not (name or '').strip():
            domain = []
        else:
            domain = ['|', ('name', 'ilike', name),
                      ('dian_code', 'ilike', name)]
        return self._search(
            expression.AND([domain, args]),
            limit=limit, order=order,
            access_rights_uid=name_get_uid
        )


class ResPartner(models.Model):
    _inherit = "res.partner"

    @api.depends('birthday', 'date_of_death')
    def _get_age(self):
        today = datetime.now().date()
        for rec in self:
            age = 0
            age_unit = ''
            age_desc = ''
            today_is_birthday = False
            if rec.birthday:
                end_date = rec.date_of_death or today
                delta = relativedelta(end_date, rec.birthday)
                if delta.years == 0 and delta.months == 0 and delta.days < 30:
                    age = delta.days
                    age_unit = '3'  # Días
                    age_desc = f"{age} días"
                elif delta.years == 0:
                    age = delta.months
                    age_unit = '2'  # Meses
                    age_desc = f"{age} meses"
                else:
                    age = delta.years
                    age_unit = '1'  # Años
                    age_desc = f"{age} años"
                if today.month == rec.birthday.month and today.day == rec.birthday.day:
                    today_is_birthday = True
            rec.age = age
            rec.age_type = age_unit
            rec.age_description = age_desc
            rec.today_is_birthday = today_is_birthday

    age_description = fields.Char(string="Descripción de Edad", compute='_get_age', help="Edad del paciente en un formato legible")
    age_type = fields.Selection([
        ('1', 'Años'),
        ('2', 'Meses'),
        ('3', 'Días')
    ], string='Unidad de Medida de la Edad', compute='_get_age', store=True, help="Unidad de medida para la edad del paciente")
    

    
    age = fields.Char(string='Age', compute='_get_age')
    
    firs_name = fields.Char(string='Primer nombre', tracking=True)
    second_name = fields.Char(string='Segundo nombre', tracking=True)
    first_lastname = fields.Char(string='Primer apellido', tracking=True)
    second_lastname = fields.Char(string='Segundo apellido', tracking=True)
    
    # Campos de salud
    health_type = fields.Selection(
        selection=HEALTH_TYPE_SELECTION,
        string='Tipo de Usuario',
    )
    eps_id = fields.Many2one('res.partner', string="EPS/ASEGURADORA")
    
    # Campos de identificación
    l10n_latam_identification_type_id = fields.Many2one('l10n_latam.identification.type',
        string="Identification Type", index='btree_not_null', auto_join=True,
        default=lambda self: self.env.ref('l10n_latam_base.it_vat', raise_if_not_found=False),
        help="The type of identification")
    vat_co = fields.Char(string='VAT CO', help="VAT for Colombia")
    
    # Campos territoriales
    zona_territorial = fields.Selection([
        ('01', 'Rural'), 
        ('02', 'Urbano'),
    ], string='Zona Territorial', default="02")
    
    # Campos de información personal adicional
    marital_status = fields.Selection([
        ('single', 'Single'), 
        ('married', 'Married'),
        ('divorced', 'Divorced'),
        ('widow', 'Widow')
    ], string='Marital Status', default="single")
    spouse_name = fields.Char("Spouse's Name")
    spouse_edu = fields.Char("Spouse's Education")
    spouse_business = fields.Char("Spouse's Business")
    education = fields.Char("Patient Education")
    occupation = fields.Char("Occupation")
    acs_religion_id = fields.Many2one('acs.religion', string="Religion")
    caste = fields.Char("Tribe")
    nationality_id = fields.Many2one("res.country", string="Nationality")
    passport = fields.Char("Passport Number")
    
    # Campos corporativos
    is_corpo_tieup = fields.Boolean(string='Corporate Tie-Up', 
        help="If not checked, these Corporate Tie-Up Group will not be visible at all.")
    corpo_company_id = fields.Many2one('res.partner', string='Corporate Company', 
        domain="[('is_company', '=', True),('customer_rank', '>', 0)]", ondelete='restrict')
    emp_code = fields.Char(string='Employee Code')


class ACSPatient(models.Model):
    _inherit = 'hms.patient'
    
    street = fields.Char(string='Street', compute="_compute_street", inverse="acs_get_street", store=True)
    
    zona_territorial = fields.Selection([
        ('01', 'Rural'), 
        ('02', 'Urbano'),
    ], string='Zona Territorial', default="02")
    
    firs_name = fields.Char(string='Primer nombre', tracking=True)
    second_name = fields.Char(string='Segundo nombre', tracking=True)
    first_lastname = fields.Char(string='Primer apellido', tracking=True)
    second_lastname = fields.Char(string='Segundo apellido', tracking=True)
    
    l10n_latam_identification_type_id = fields.Many2one('l10n_latam.identification.type',
        string="Identification Type", index='btree_not_null', auto_join=True,
        default=lambda self: self.env.ref('l10n_latam_base.it_vat', raise_if_not_found=False),
        help="The type of identification")
    vat = fields.Char(string='Identification Number', help="Identification Number for selected type")
    
    eps_id = fields.Many2one('res.partner', string="EPS/ASEGURADORA")
    health_type = fields.Selection(
        selection=HEALTH_TYPE_SELECTION,
        string='Tipo de Usuario',
    )
    
    nationality_id = fields.Many2one("res.country", string="Nationality")
    passport = fields.Char("Passport Number")
    occupation = fields.Char("Occupation")
    acs_religion_id = fields.Many2one('acs.religion', string="Religion")
    caste = fields.Char("Tribe")
    location_url = fields.Text()
    
    is_corpo_tieup = fields.Boolean(string='Corporate Tie-Up', 
        help="If not checked, these Corporate Tie-Up Group will not be visible at all.")
    corpo_company_id = fields.Many2one('res.partner', string='Corporate Company', 
        domain="[('is_company', '=', True),('customer_rank', '>', 0)]", ondelete='restrict')
    emp_code = fields.Char(string='Employee Code')
    
    user_id = fields.Many2one('res.users', string='Related User', ondelete='cascade', 
        help='User-related data of the patient')
    primary_physician_id = fields.Many2one('hms.physician', 'Primary Care Doctor')
    acs_tag_ids = fields.Many2many('hms.patient.tag', 'patient_tag_hms_rel', 'tag_id', 'patient_tag_id', string="HMS Tags")
    
    saltar_validacion = fields.Boolean(string="Saltar Validación", 
        help="Si se marca, se omitirán las reglas de validación.")
    
    _rec_names_search = ['name', 'code', 'vat', 'mobile']
    
    @api.depends('partner_id.street')
    def _compute_street(self):
        for rec in self:
            rec.street = rec.partner_id.street
    
    def acs_get_street(self):
        for rec in self:
            if rec.street:
                rec.partner_id.street = rec.street
    
    @api.onchange('firs_name', 'second_name', 'first_lastname', 'second_lastname')
    def _onchange_person_names(self):
        if self.company_type == 'person':
            names = [name for name in [self.firs_name, self.second_name, self.first_lastname, self.second_lastname] if name]
            self.name = u' '.join(names)
    
    @api.onchange('city_id')
    def _onchange_city_id(self):
        if self.city_id:
            self.city = self.city_id.name
            self.zip = self.city_id.zipcode
            self.state_id = self.city_id.state_id
        elif self._origin:
            self.city = False
            self.zip = False
            self.state_id = False
    
    def _prepare_partner_values(self, vals):
        """Prepara los valores para el partner relacionado incluyendo todos los campos necesarios"""
        partner_vals = {
            'company_type': 'person',
            'customer_rank': True,
        }
        
        # Campos de dirección
        address_fields = [
            'street', 'street2', 'city', 'state_id', 'zip', 'country_id',
            'city_id', 'phone', 'mobile', 'email'
        ]
        for field in address_fields:
            if field in vals:
                partner_vals[field] = vals[field]
        
        # Campos de nombres
        name_fields = {'firs_name', 'second_name', 'first_lastname', 'second_lastname'}
        if any(field in vals for field in name_fields):
            names = [
                vals.get('firs_name', self.firs_name if hasattr(self, 'firs_name') else ''),
                vals.get('second_name', self.second_name if hasattr(self, 'second_name') else ''),
                vals.get('first_lastname', self.first_lastname if hasattr(self, 'first_lastname') else ''),
                vals.get('second_lastname', self.second_lastname if hasattr(self, 'second_lastname') else '')
            ]
            for field in name_fields:
                if field in vals:
                    partner_vals[field] = vals[field]
            
            if any(names):
                partner_vals['name'] = ' '.join(filter(None, names))
        
        # Campos de identificación
        if 'l10n_latam_identification_type_id' in vals:
            partner_vals['l10n_latam_identification_type_id'] = vals['l10n_latam_identification_type_id']
        if 'vat' in vals:
            partner_vals['vat'] = vals['vat']
            partner_vals['vat_co'] = vals['vat']
        
        # Campos de salud
        if 'health_type' in vals:
            partner_vals['health_type'] = vals['health_type']
        if 'eps_id' in vals:
            partner_vals['eps_id'] = vals['eps_id']
        
        # Campos territoriales
        if 'zona_territorial' in vals:
            partner_vals['zona_territorial'] = vals['zona_territorial']
        
        # Campos de información personal
        personal_fields = [
            'birthday', 'gender', 'marital_status', 'spouse_name', 'spouse_edu', 
            'spouse_business', 'education', 'occupation', 'acs_religion_id', 
            'caste', 'nationality_id', 'passport'
        ]
        for field in personal_fields:
            if field in vals:
                partner_vals[field] = vals[field]
        
        # Campos corporativos
        corporate_fields = ['is_corpo_tieup', 'corpo_company_id', 'emp_code']
        for field in corporate_fields:
            if field in vals:
                partner_vals[field] = vals[field]
        
        return partner_vals
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('code', '/') == '/':
                vals['code'] = self.env['ir.sequence'].next_by_code('hms.patient') or ''
            company_id = vals.get('company_id')
            if company_id:
                company_id = self.env['res.company'].sudo().search([('id', '=', company_id)], limit=1)
            else:
                company_id = self.env.company
            if company_id.unique_gov_code and vals.get('gov_code'):
                self.check_gov_code(vals.get('gov_code'))
            vals['customer_rank'] = True
        
        patients = super().create(vals_list)
        
        # Actualizar los valores del partner
        for patient, vals in zip(patients, vals_list):
            partner_vals = self._prepare_partner_values(vals)
            if partner_vals:
                patient.partner_id.write(partner_vals)
        
        return patients
    
    def write(self, values):
        company_id = self.sudo().company_id or self.env.user.sudo().company_id
        if company_id.unique_gov_code and values.get('gov_code'):
            self.check_gov_code(values.get('gov_code'))
        
        # Preparar valores del partner antes de escribir
        partner_vals = self._prepare_partner_values(values)
        
        result = super().write(values)
        
        # Actualizar el partner después de escribir
        if partner_vals:
            self.mapped('partner_id').write(partner_vals)
        
        return result
    
    @api.constrains('age', 'age_type', 'l10n_latam_identification_type_id', 'saltar_validacion')
    def _check_validaciones_paciente(self):
        if self.saltar_validacion:
            return
        
        # Necesitamos acceder a la edad desde el partner_id
        age = int(self.partner_id.age)
        age_type = self.partner_id.age_type
        
        id_type = self.l10n_latam_identification_type_id.heath_code if self.l10n_latam_identification_type_id else False
        vat = self.vat
        
        if id_type in ['CC', 'TI'] and (not vat.isdigit() if vat else True):
            raise ValidationError(_("El número de identificación para CC o TI debe ser numérico."))
        
        if id_type in ['RC', 'MS', 'CN'] and age_type == '1' and age >= 19:
            raise ValidationError(_("El tipo de identificación RC, MS o CN no está permitido para individuos de 19 años o más."))
        
        if id_type == 'AS' and age_type == '1' and age <= 17:
            raise ValidationError(_("El tipo de identificación AS solo está permitido para mayores de 17 años."))
        
        if id_type in ['CC', 'TI', 'AS'] and age_type == '3':
            raise ValidationError(_("El tipo de identificación CC, TI o AS no está permitido para individuos menores de 1 año."))
        
        if id_type == 'RC' and age_type == '1' and age > 6:
            raise ValidationError(_("El tipo de identificación RC solo está permitido para niños menores de 7 años."))
        
        if age_type == '1' and (age < 1 or age > 120):
            raise ValidationError(_("La edad en años debe estar entre 1 y 120."))
        
        if age_type == '2' and (age < 1 or age > 11):
            raise ValidationError(_("La edad en meses debe estar entre 1 y 11."))
        
        if age_type == '3' and (age < 1 or age > 29):
            raise ValidationError(_("La edad en días debe estar entre 1 y 29."))
        
        max_length = {
            'CC': 10,
            'CE': 6,
            'CD': 16,
            'PA': 16,
            'SC': 16,
            'PE': 15,
            'RC': 11,
            'TI': 11,
            'CN': 9,
            'AS': 10,
            'MS': 12,
        }
        
        # Validación de longitud comentada como en el original
        # if id_type in max_length and vat and len(vat) > max_length[id_type]:
        #     raise ValidationError(_("El número de identificación excede la longitud máxima permitida para el tipo de identificación seleccionado."))
    
    @api.onchange('age', 'l10n_latam_identification_type_id')
    def _onchange_age_majority_notice(self):
        # Acceder a la edad desde el partner_id
        age = self.partner_id.age if self.partner_id else 0
        age_type = self.partner_id.age_type if self.partner_id else '1'
        
        if int(age) >= 18 and age_type == '1' and self.l10n_latam_identification_type_id.heath_code != 'CC':
            return {
                'warning': {
                    'title': _("Aviso de mayoría de edad"),
                    'message': _("Este paciente tiene 18 años o más. Asegúrese de que el tipo de identificación sea correcto."),
                }
            }

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
# -*- coding: utf-8 -*-

from odoo import api, fields, models ,_
from datetime import datetime
from odoo.exceptions import UserError,ValidationError
import math
from datetime import datetime
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
ADDRESS_FIELDS = ['main_road', 'name_road', 'main_letter_road', 'prefix_main_road', 'sector_main_road',
                  'generator_road_number', 'generator_road_letter', 'generator_road_sector',
                  'generator_plate_number', 'generator_plate_sector', 'complement_name_a', 'complement_number_a',
                  'complement_name_b', 'complement_number_b', ]

class ACSPatient(models.Model):
    _name = 'hms.patient'
    _description = 'Patient'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'acs.hms.mixin', 'acs.document.mixin']
    _inherits = {
        'res.partner': 'partner_id',
    }
    _rec_names_search = ['name', 'code','vat','mobile']

    def _rec_count(self):
        Invoice = self.env['account.move']
        for rec in self:
            rec.invoice_count = Invoice.sudo().search_count([('partner_id','=',rec.partner_id.id)])

    partner_id = fields.Many2one('res.partner', required=True, ondelete='restrict', auto_join=True,
        string='Related Partner', help='Partner-related data of the Patient')
    street = fields.Char(string='Street', compute="_compute_street", inverse="acs_get_street", store=True)
    gov_code = fields.Char(string='Government Identity', copy=False, tracking=True)
    gov_code_label = fields.Char(compute="acs_get_gov_code_label", string="Government Identity Label")
    marital_status = fields.Selection([
        ('single', 'Single'), 
        ('married', 'Married'),
        ('divorced', 'Divorced'),
        ('widow', 'Widow')], string='Marital Status', default="single")
    zona_territorial = fields.Selection([
        ('01', 'Rural'), 
        ('02', 'Urbano'),], string='Zona Territorial', default="02")
    spouse_name = fields.Char("Spouse's Name")
    spouse_edu = fields.Char("Spouse's Education")
    spouse_business = fields.Char("Spouse's Business")
    education = fields.Char("Patient Education")
    is_corpo_tieup = fields.Boolean(string='Corporate Tie-Up', 
        help="If not checked, these Corporate Tie-Up Group will not be visible at all.")
    corpo_company_id = fields.Many2one('res.partner', string='Corporate Company', 
        domain="[('is_company', '=', True),('customer_rank', '>', 0)]", ondelete='restrict')
    emp_code = fields.Char(string='Employee Code')
    user_id = fields.Many2one('res.users', string='Related User', ondelete='cascade', 
        help='User-related data of the patient')
    primary_physician_id = fields.Many2one('hms.physician', 'Primary Care Doctor')
    acs_tag_ids = fields.Many2many('hms.patient.tag', 'patient_tag_hms_rel', 'tag_id', 'patient_tag_id', string="HMS Tags")
    firs_name = fields.Char(string='Primer nombre', tracking=True)
    second_name = fields.Char(string='Segundo nombre', tracking=True)
    first_lastname = fields.Char(string='Primer apellido', tracking=True)
    second_lastname = fields.Char(string='Segundo apellido', tracking=True)
    invoice_count = fields.Integer(compute='_rec_count', string='# Invoices')
    occupation = fields.Char("Occupation")
    acs_religion_id = fields.Many2one('acs.religion', string="Religion")
    caste = fields.Char("Tribe")
    nationality_id = fields.Many2one("res.country", string="Nationality")
    passport = fields.Char("Passport Number")
    active = fields.Boolean(string="Active", default=True)
    location_url = fields.Text()
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
    saltar_validacion = fields.Boolean(string="Saltar Validación", help="Si se marca, se omitirán las reglas de validación.")

    
    def acs_get_street(self):
        for rec in self:
            if rec.street:
                return rec.street



    
    def acs_get_gov_code_label(self):
        for rec in self:
            rec.gov_code_label = self.env.company.country_id.gov_code_label
            
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

     
    def check_gov_code(self, gov_code):
        patient = self.search([('gov_code','=',gov_code)],limit=1)
        if patient:
            raise ValidationError(_('Patient already exists with Government Identity: %s.') % (gov_code))

    def _prepare_partner_values(self, vals):
        """Prepara los valores para el partner relacionado incluyendo todos los campos necesarios"""
        partner_vals = {
            'company_type': 'person',
            'customer_rank': True,
        }
        address_fields = [
            'street', 'street2', 'city', 'state_id', 'zip', 'country_id',
            'city_id', 'phone', 'mobile', 'email'
        ]
        for field in address_fields:
            if field in vals:
                partner_vals[field] = vals[field]
                
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
                
        if 'l10n_latam_identification_type_id' in vals:
            partner_vals['l10n_latam_identification_type_id'] = vals['l10n_latam_identification_type_id']
        if 'vat' in vals:
            partner_vals['vat'] = vals['vat']
            partner_vals['vat_co'] = vals['vat']
        return partner_vals



    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('code','/')=='/':
                vals['code'] = self.env['ir.sequence'].next_by_code('hms.patient') or ''
            company_id = vals.get('company_id')
            if company_id:
                company_id = self.env['res.company'].sudo().search([('id','=',company_id)], limit=1)
            else:
                company_id = self.env.company
            if company_id.unique_gov_code and vals.get('gov_code'):
                self.check_gov_code(vals.get('gov_code'))
            vals['customer_rank'] = True
        patients = super().create(vals_list)
        for patient, vals in zip(patients, vals_list):
            partner_vals = self._prepare_partner_values(vals)
            if partner_vals:
                patient.partner_id.write(partner_vals)
        return patients

    def write(self, values):
        company_id = self.sudo().company_id or self.env.user.sudo().company_id
        if company_id.unique_gov_code and values.get('gov_code'):
            self.check_gov_code(values.get('gov_code'))
        partner_vals = self._prepare_partner_values(values)
        result = super().write(values)
        if partner_vals:
            self.mapped('partner_id').write(partner_vals)
        return result

    def view_invoices(self):
        invoices = self.env['account.move'].search([('partner_id','=',self.partner_id.id), ('move_type', 'in', ('out_invoice', 'out_refund'))])
        action = self.with_context(acs_open_blank_list=True).acs_action_view_invoice(invoices)
        action['context'].update({
            'default_partner_id': self.partner_id.id,
            'default_patient_id': self.id,
        })
        return action

    @api.model
    def send_birthday_email(self): 
        wish_template_id = self.env.ref('acs_hms_base.email_template_birthday_wish', raise_if_not_found=False)
        user_cmp_template = self.env.company.birthday_mail_template_id
        today = datetime.now()
        today_month_day = '%-' + today.strftime('%m') + '-' + today.strftime('%d')
        patient_ids = self.search([('birthday', 'like', today_month_day)])
        for patient_id in patient_ids:
            if patient_id.email:
                wish_temp = patient_id.company_id.birthday_mail_template_id or user_cmp_template or wish_template_id
                wish_temp.sudo().send_mail(patient_id.id, force_send=True)

    def _compute_display_name(self):
        for rec in self:
            name = rec.name
            if rec.title and rec.title.shortcut:
                name = (rec.title.shortcut or '') + ' ' + (rec.name or '')
            rec.display_name = name

    @api.onchange('mobile')
    def _onchange_mobile_warning(self):
        if not self.mobile:
            return
        mobile = self.mobile
        message = ''
        domain = [('mobile','=',self.mobile)]
        if self._origin and self._origin.id:
            domain += [('id','!=',self._origin.id)]
        patients = self.sudo().search(domain)
        for patient in patients:
            message += _('\nThe Mobile number is already registered with another Patient: %s, Government Identity:%s, DOB: %s.') %(patient.name, patient.gov_code, patient.birthday)
        if message:
            message += _('\n\n Are you sure you want to create a new Patient?')
            return {
                'warning': {
                    'title': _("Warning for Mobile Dupication"),
                    'message': message,
                }
            }
    
    @api.model
    def _get_view(self, view_id=None, view_type='form', **options):
        arch, view = super()._get_view(view_id, view_type, **options)
        company = self.env.company
        if company.country_id.vat_label:
            for node in arch.xpath("//field[@name='gov_code']"):
                node.attrib["string"] = company.country_id.gov_code_label
        return arch, view


    @api.constrains('age', 'age_type', 'l10n_latam_identification_type_id', 'saltar_validacion')
    def _check_validaciones_paciente(self):
        if self.saltar_validacion:
            return
        id_type = self.l10n_latam_identification_type_id.heath_code
        vat = self.vat
        if id_type in ['CC', 'TI'] and (not vat.isdigit() if vat else True):
            raise ValidationError(_("El número de identificación para CC o TI debe ser numérico."))
        if id_type in ['RC', 'MS', 'CN'] and self.age_type == '1' and self.age >= 19:
            raise ValidationError(_("El tipo de identificación RC, MS o CN no está permitido para individuos de 19 años o más."))
        if id_type == 'AS' and self.age_type == '1' and self.age <= 17:
            raise ValidationError(_("El tipo de identificación AS solo está permitido para mayores de 17 años."))
        if id_type in ['CC', 'TI', 'AS'] and self.age_type == '3':
            raise ValidationError(_("El tipo de identificación CC, TI o AS no está permitido para individuos menores de 1 año."))
        if id_type == 'RC' and self.age_type == '1' and self.age > 6:
            raise ValidationError(_("El tipo de identificación RC solo está permitido para niños menores de 7 años."))
        if self.age_type == '1' and (self.age < 1 or self.age > 120):
            raise ValidationError(_("La edad en años debe estar entre 1 y 120."))
        if self.age_type == '2' and (self.age < 1 or self.age > 11):
            raise ValidationError(_("La edad en meses debe estar entre 1 y 11."))
        if self.age_type == '3' and (self.age < 1 or self.age > 29):
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

        #i#f id_type in max_length and vat and len(vat) > max_length[id_type]:
        #    raise ValidationError(_("El número de identificación excede la longitud máxima permitida para el tipo de identificación seleccionado."))


    @api.onchange('age','l10n_latam_identification_type_id')
    def _onchange_age_majority_notice(self):
        if self.age >= 18 and self.age_type == '1' and self.l10n_latam_identification_type_id.heath_code != 'CC':
            return {
                'warning': {
                    'title': _("Aviso de mayoría de edad"),
                    'message': _("Este paciente tiene 18 años o más. Asegúrese de que el tipo de identificación sea correcto."),
                }
            }
# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
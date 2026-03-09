from odoo import fields, models, api


class hr_labor_certificate_template(models.Model):
    _name = 'hr.labor.certificate.template'
    _description = 'Configuración plantilla certificado laboral'

    company_id = fields.Many2one('res.company', string='Compañía', default=lambda self: self.env.company)
    notes = fields.Text(string='Notas:')
    certificate_template_detail_ids = fields.One2many('hr.labor.certificate.template.detail', 'certificate_template_id',string='Detalle de la plantilla del certificado')
    #Encabezado y pie de pagina
    type_header_footer = fields.Selection([('default', 'Por defecto'),
                                           ('custom', 'Personalizado')], 'Tipo de encabezado y pie de pagina',
                                          required=True, default='default')
    img_header_file = fields.Binary('Encabezado')
    img_header_filename = fields.Char('Encabezado filename')
    img_footer_file = fields.Binary('Pie de pagina')
    img_footer_filename = fields.Char('Pie de pagina filename')
    #Contenido
    model_fields = fields.Many2many('ir.model.fields', domain="[('model', 'in', ('hr.employee','hr.contract')),('ttype','not in',['one2many','many2many'])]",
                                    string='Campos de las tablas de empleado y contrato a utilizar')
    txt_model_fields = fields.Text(string='Nemotecnia de los campos',
                                   compute='_compute_txt_model_fields', store=False)
    body_labor_certificate = fields.Html(string='Contenido', translate=False)
    show_average_overtime = fields.Boolean('Mostrar promedio de horas extras de los ultimos 3 meses')
    show_total_rules = fields.Boolean('Mostrar total de reglas variables/fijas')

    _sql_constraints = [
        ('company_certificate_template', 'UNIQUE (company_id)', 'Ya existe una configuración de plantilla de certificado laboral para esta compañía, por favor verificar')
    ]

    def name_get(self):
        result = []
        for record in self:
            result.append((record.id, "Plantilla certificado laboral de {}".format(record.company_id.name)))
        return result

    # Campos para el cuerpo del correo
    @api.depends('model_fields')
    def _compute_txt_model_fields(self):
        text = ''
        for field in sorted(self.model_fields, key=lambda x: x.model):
            name_field = field.name
            name_public_field = field.field_description
            text = text + 'Tabla origen '+field.model_id.name+', Para el campo ' + name_public_field + ' digitar %(' + field.model+'.'+name_field + ')s \n'
        self.txt_model_fields = text

class hr_labor_certificate_template_detail(models.Model):
    _name = 'hr.labor.certificate.template.detail'
    _description = 'Configuración plantilla certificado laboral detalle'

    certificate_template_id = fields.Many2one('hr.labor.certificate.template', string='Plantilla del certificado')
    rule_salary_id = fields.Many2one('hr.salary.rule', string='Regla Salarial',required=True )
    sequence = fields.Integer(string='Secuencia')
    last_month = fields.Boolean(string='Último mes')
    average_last_months = fields.Boolean(string='Promedio  de los ultimos 3 meses')
    value_contract = fields.Boolean(string="Valor contrato")
    # Es quincenal o mensual
    payment_frequency = fields.Selection([
                                    ('biweekly', 'Quincenal'),
                                    ('monthly', 'Mensual')
                                ], string='Frecuencia de pago', default='biweekly', required=True)

    _sql_constraints = [
        ('rule_certificate_template_detail', 'UNIQUE (certificate_template_id, rule_salary_id)',
         'Ya existe esta regla para la configuración de certificado laboral, por favor verificar')
    ]

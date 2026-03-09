# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools.safe_eval import safe_eval
from odoo.tools import pdf, split_every
from PyPDF2 import PdfFileMerger, PdfFileReader, PdfFileWriter
import os
import io
import base64

class hr_employee(models.Model):
    _inherit = 'hr.employee'

    def open_hr_employee_report_curriculum(self):
        return {
            'name': 'Informe configurable hoja de vida',
            'type': 'ir.actions.act_window',
            'res_model': 'hr.employee.report.curriculum',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_employee_ids': self.ids,
            }
        }

class hr_employee_report_curriculum(models.TransientModel):
    _name = 'hr.employee.report.curriculum'
    _description = 'Informe configurable hoja de vida'

    employee_ids = fields.Many2many('hr.employee',string='Empleados')
    domain_documents = fields.Char(string='Filtro documentos')
    include_resume_curriculum = fields.Boolean(string='Incluir formato datos personales')
    document_ids = fields.One2many('hr.employee.report.curriculum.documents','report_id',string='Documentos')
    order_fields = fields.Many2many('ir.model.fields', domain="[('model', '=', 'documents.document'),('ttype', 'not in', ['many2many','one2many','text','binary'])]",string='Campos para ordenar')
    save_favorite = fields.Boolean(string='Guardar como favorito')
    name = fields.Char(string='Nombre')
    favorite_id = fields.Many2one('hr.employee.report.curriculum.favorites',string='Favorito')
    pdf_file = fields.Binary('PDF file')
    pdf_file_name = fields.Char('PDF name')

    def name_get(self):
        result = []
        for record in self:
            result.append((record.id, "Informe configurable hoja de vida"))
        return result

    @api.onchange('domain_documents','order_fields')
    def load_documents(self):
        for record in self:
            record.document_ids = False
            domain = []
            domain_documents_obligatory = str([['partner_id', 'in', record.employee_ids.work_contact_id.ids], ['mimetype', 'like', 'pdf']])
            domain += safe_eval(domain_documents_obligatory)
            if record.domain_documents:
                domain += safe_eval(record.domain_documents)
                lst_order = ['partner_id']
                if len(record.order_fields) > 0:
                    for field in record.order_fields:
                        if field.name not in lst_order:
                            lst_order.append(field.name)
                str_order = ','.join(map(str, lst_order))
                obj_document = self.env['documents.document'].search(domain,order=str_order)
                i = 1
                lst_documents = []
                for document in obj_document:
                    vals = {
                        #'report_id':record.id,
                        'sequence':i,
                        'partner_id':document.partner_id.id,
                        'document_id':document.id,
                    }
                    lst_documents.append((0,0,vals))
                    #self.env['hr.employee.report.curriculum.documents'].create(vals)
                    i += 1
                record.document_ids = lst_documents

    def generate_pdf(self):
        #Guardar favorito si el check estaba marcado
        if self.save_favorite:
            self.save_favorite_process()
        #Variables
        report_personal_data = self.env['ir.actions.report'].search(
            [('report_name', '=', 'lavish_hr_employee.report_personal_data_form_template'),
             ('report_file', '=', 'lavish_hr_employee.report_personal_data_form_template')])
        files_to_merge = []
        filename = 'Informe Hoja de vida.pdf'
        file_merger = PdfFileMerger()
        #Recorrer empleados
        for employee in self.employee_ids:
            # Incluir formato datos personales
            if self.include_resume_curriculum:
                pdf_content, content_type = report_personal_data._render_qweb_pdf(employee.id)
                files_to_merge.append((employee.name,'Formato Datos Personales',pdf_content))
            #Obtener PDFs
            for item in sorted(self.document_ids.filtered(lambda x: x.partner_id.id == employee.work_contact_id.id), key=lambda x: x.sequence):
                document = item.document_id
                if document.mimetype.find('pdf') == -1:
                    raise ValidationError(_("Ahí un archivo que que no es formato PDF, por favor verificar."))
                files_to_merge.append((employee.name,document.name,document.attachment_id.raw))
        #Unir Pdfs
        writer = PdfFileWriter()
        for file in files_to_merge:
            try:
                reader = PdfFileReader(io.BytesIO(file[2]), strict=False, overwriteWarnings=False)
                writer.appendPagesFromReader(reader)
            except Exception as e:
                msg_error = 'Empleado: %s \nDocumento: %s \n Error: %s' % (file[0],file[1], e)
                raise ValidationError(_(msg_error))
        result_stream = io.BytesIO()
        writer.write(result_stream)
        #Guardar pdf
        self.write({
            'pdf_file': base64.encodebytes(result_stream.getvalue()),
            'pdf_file_name': filename,
        })
        #Descargar reporte
        action = {
            'name': 'InformeHojaDeVida',
            'type': 'ir.actions.act_url',
            'url': "web/content/?model=hr.employee.report.curriculum&id=" + str(
                self.id) + "&filename_field=pdf_file_name&field=pdf_file&download=true&filename=" + self.pdf_file_name,
            'target': 'self',
        }
        return action

    def save_favorite_process(self):
        if not self.name:
            raise ValidationError(_("Debe digitar un nombre para guardar como favorito."))
        if not self.domain_documents:
            raise ValidationError(_("Debe seleccionar un filtro para guardar como favorito."))
        vals = {
            'name': self.name,
            'domain_documents':self.domain_documents,
        }
        self.env['hr.employee.report.curriculum.favorites'].create(vals)

    @api.onchange('favorite_id')
    def load_favorite_process(self):
        self.domain_documents = self.favorite_id.domain_documents

class hr_employee_report_curriculum_documents(models.TransientModel):
    _name = 'hr.employee.report.curriculum.documents'
    _description = 'Informe configurable hoja de vida - documentos'
    _order = 'sequence'

    report_id = fields.Many2one('hr.employee.report.curriculum',string='Reporte', required=True)
    sequence = fields.Integer(string='Secuencia', required=True)
    partner_id = fields.Many2one('res.partner', string='Empleado', required=True)
    document_id = fields.Many2one('documents.document', string='Documento', required=True)

class hr_employee_report_curriculum_favorites(models.Model):
    _name = 'hr.employee.report.curriculum.favorites'
    _description = 'Informe configurable hoja de vida - favoritos'

    name = fields.Char(string='Nombre')
    domain_documents = fields.Char(string='Filtro documentos')

    _sql_constraints = [('curriculum_favorites_uniq', 'unique(name)',
                         'Ya existe un favorito con este nombre, por favor verificar.')]
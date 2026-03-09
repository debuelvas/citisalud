# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
import json
import base64
import zipfile
from io import BytesIO
from datetime import datetime
from lxml import etree
import html
import logging
import io
import os
import re
import unicodedata  # Añadido: faltaba para _remove_accents
from collections import defaultdict

_logger = logging.getLogger(__name__)


class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

   
    rips_export_id = fields.Many2one(
        'rips.export', 
        string='Lote RIPS',
        ondelete='set null',
        index=True
    )



class HospitalRIPS(models.Model):
    _name = "hospital.rips"
    _description = "Hospital RIPS"

    name = fields.Char(string="N° Radicado", default="/", required=True, readonly=True)
    active = fields.Boolean(string="Activo", default=True)
    state = fields.Selection(selection=[('draft',"Draft"),('confirmed','Confirmed'),('done',"Done"),('cancel','Cancel')],
        readonly=True, string="Status", default='draft')
    date_from = fields.Date(string="Fecha Inicial", required=True, copy=False)
    date_to = fields.Date(string="Fecha Final", required=True, copy=False)

    partner_id = fields.Many2one('res.partner', string="Cliente", required=True)
    team = fields.Many2one('crm.team', string="Regional", required=True)
    journal_id = fields.Many2one('account.journal', string="Regional de Facturacion", required=True, domain="[('type', '=', 'sale')]")
    ratication_date = fields.Date(string="Radication Date") 
    rips_directo = fields.Boolean(string="RIPS Directo", help='Esta opción permite generar Rips sin haber facturado atenciones.')
    contrato_id = fields.Many2one('doctor.contract.insurer', string='Contrato',
        required=True, help='Contrato por el que se atiende al cliente.')

    invoices_ids = fields.Many2many('account.move', 'account_move_hospital_rips_rel', 'move_id', 'rips_id', string="Invoices", copy=False,
        domain="[('move_type', '=', 'out_invoice'),('state','!=','draft')]")
    invoice_count = fields.Integer(string="Invoice Count", compute="_invoice_values", store=True)
    amount_residual = fields.Float(string="Amount Due", compute="_invoice_values", store=True)
    amount_total = fields.Float(string="Amount Total", compute="_invoice_values", store=True)
    observations = fields.Text('Observaciones')
    # attachment_rips_ids = fields.Many2many('ir.attachment', 'attachment_fo_company_rel', 'attch_id', 'rips_id', string='RIPS', copy=False)

    tipo_afiliacion = fields.Selection(selection=[
        ('contributory', 'Contributivo'), 
        ('subsidized', 'Subsidiado'), 
        ('linked', 'Vinculado')], string="Tipo De Regimen", required=True)

    archive_zip = fields.Binary(string="Archive ZIP", attachment=True)
    archive_zip_name = fields.Char(string="Archive ZIP Name")

    company_id = fields.Many2one('res.company', string="Company", default=lambda self: self.env.company)
    cea_code = fields.Char(related="company_id.cod_prestadorservicio", 
        store=True, string="Código Prestador Servicio", required=True)

    @api.depends('invoices_ids')
    def _invoice_values(self):
        for rops in self:
            rops.invoice_count = len(rops.invoices_ids.ids)
            rops.amount_residual = sum(i.amount_residual for i in rops.invoices_ids)
            rops.amount_total = sum(i.amount_total for i in rops.invoices_ids)
    @api.model
    def _remove_accents(self, string):
        """
        Esta función sirve para remover los acentos de una cadena de texto
        """
        if not string:
            return string
        no_accents = ''.join((c for c in unicodedata.normalize('NFD', string) if unicodedata.category(c) != 'Mn'))
        clean_str = re.sub(r'[^a-zA-Z0-9\s]', '', no_accents)
        return clean_str.upper()
    
    def action_generate(self):
        self.invoices_ids = False
        invoices = self.env['account.move'].search([
                ('rip_id','=',False),
                ('team_id','=',self.team.id),
                ('company_id','=',self.company_id.id),
                ('journal_id','=',self.journal_id.id),
                ('invoice_date','>=',self.date_from),
                ('invoice_date','<=',self.date_to),
                ('state','in',['posted']),
                ('move_type','in',['out_invoice']),
                ('partner_id','=', self.partner_id.id),])
        self.invoices_ids = [(6,0, invoices.ids or [])]

    def action_confirm(self):
        if self.name == '/':
            code = self.env['ir.sequence'].next_by_code("account.rips")
            self.write({'name': code, 
                    'state': 'confirmed', 
                    'ratication_date': fields.Date.context_today(self)})

    def action_done(self):
        """
        Marca el lote RIPS como completado y asocia las facturas.
        OPTIMIZADO: Usa ORM en lugar de SQL directo para mantener trazabilidad.
        """
        # Usar ORM para mantener tracking y permisos
        if self.invoices_ids:
            self.invoices_ids.write({'rip_id': self.id})
        self.write({'state': 'done'})

    def action_cancel(self):
        self.write({'state': 'cancel'})

    def action_generate_zip(self):
        for rec in self.invoices_ids:
            errors = []
            partner = rec.patient_id
            lines = rec.invoice_line_ids.filtered(lambda line:line.product_id)
            required_partner_fields = [
                ("firs_name", "Primer Nombre"),
                ("first_lastname", "Primer Apellido"),
                ("birthday", "Fecha de nacimiento"),
                ("sex", "Sexo"),
                ("vat_co", "registrado el Numero de Documento."),
                ("l10n_co_document_code", "asociada un tipo de documento."),
                ("state_id", "asociada un estado."),
                ("city_id", "asociada un municipio.")]
            for field, message in required_partner_fields:
                if not getattr(partner, field):
                    errors.append(f"Su Paciente no tiene {message} --> {partner.name} en la factura {rec.name}" )
            for line in lines:
                if not line.authorization_number:
                    errors.append(f" La factura no contiene en la factura codigo de autorizacion {rec.name}" )
            self.observations = ("\n".join(errors))
            if errors:
                return True
        files = self._generate_files()
        zipfiles = self.make_zip(files)
        zipfiles.seek(0)
        self.archive_zip = base64.b64encode(zipfiles.read())
        self.archive_zip_name = f"{self.name}.zip"

    def make_zip(self, files):
        output = BytesIO()
        with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for f in files:
                zf.writestr(f[0], f[1])
        return output
    

    def _conver_gender(self, gender:str) -> str:
        """Validate and format gender value according to RIPS specifications.
        
        Valid values are:
        - M: Hombre (Man)
        - F: Mujer (Woman)
        - I: Indeterminado o Intersexual (Indeterminate or Intersexual)
        """
        valid_values = ['M', 'F', 'I']
        if gender == 'H':
            return 'M'
        elif gender == 'M':
            return 'F' 
        elif gender == 'I':
            return 'I' 
        if not gender or gender not in valid_values:
            return 'M' 
        return gender  
    
    def _generate_files(self):
        files = []
        dic = {
            'US': [[],""],
            'AF': "",
            'AT': "",
            'CT': {'US':0,'AF':0,'AT':0}
        }
        tipo_afiliacion = {
            'contributory': '1',
            'subsidized': '2',
            'linked': '3'
        }
        dic['CT']['AF'] = len(self.invoices_ids.ids)

        for inv in self.invoices_ids.invoice_line_ids:
            partner = inv.partner_id
            patient = inv.patient_id
            company = self.company_id

            tipo_doc = patient.l10n_latam_identification_type_id.heath_code
            numero_id = patient.vat_co
            #codigo_entidad = patient.eps.entity_code
            codigo_entidad = partner.ref
            tipo_usuario = tipo_afiliacion[patient.tipo_afiliacion]
            primer_apellido = self._remove_accents((patient.first_lastname or "").upper())
            segundo_apellido = self._remove_accents((patient.second_lastname or "").upper())
            primer_nombre = self._remove_accents((patient.firs_name or "").upper())
            segundo_nombre  = self._remove_accents((patient.second_name or "").upper())
            edad = relativedelta(inv.invoice_date, patient.birthday)
            birth_date = patient.birthday
            days_difference = (inv.invoice_date - birth_date).days
            uom_pre = 1
            edad_pre = edad.years
            if days_difference >= 364:
                uom_pre = '1'
                edad_pre = days_difference // 365
            elif days_difference >= 30:
                uom_pre= '2'
                edad_pre= days_difference // 30
            else:
                uom_pre = '3'
                edad_pre = days_difference
            edad = edad_pre
            uom_edad = uom_pre
            sexo = self._conver_gender(patient.gender)
            cod_dpto = patient.state_id.code_dian
            cod_municipio = patient.city_id.code[-3:]
            zona_residencia = patient.zona_territorial.upper()
            if patient.id not in dic['US'][0]:
                dic['US'][1] += "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n" %(
                    tipo_doc,
                    numero_id,
                    codigo_entidad,
                    tipo_usuario,
                    primer_apellido,
                    segundo_apellido,
                    primer_nombre,
                    segundo_nombre,
                    edad,
                    uom_edad,
                    sexo,
                    cod_dpto,
                    cod_municipio,
                    zona_residencia)
                dic['CT']['US'] += 1
            dic["US"][0].append(patient.id)
            numero_factura =  inv.name
            fecha_expedito = (inv.invoice_date).strftime('%d/%m/%Y')
            fecha_inicio = (self.date_from).strftime('%d/%m/%Y')
            fecha_fin = (self.date_to).strftime('%d/%m/%Y')
            nombre_entidad_admin = self._remove_accents(patient.eps.name)
            numero_contrato = self.contrato_id.contract_code
            plan_beneficio = 2
            nro_poliza = 0
            copago = 0
            comision = 0
            descuento = 0
            tipo_servicio = "1"
            valor_neto = int(inv.amount_untaxed + inv.amount_vat) #int(inv.ei_amount_total_no_withholding)
            dic['AF'] += "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n" %(
                        company.partner_id.vat_co,
                        self._remove_accents(company.partner_id.name),
                        "NI",
                        company.partner_id.vat_co,
                        numero_factura,
                        fecha_expedito,
                        fecha_inicio,
                        fecha_fin,
                        codigo_entidad,
                        nombre_entidad_admin,
                        numero_contrato,
                        plan_beneficio,
                        nro_poliza,
                        copago,
                        comision,
                        descuento,
                        valor_neto)
            group_lines = {}
            for line in inv.filtered(lambda line:line.product_id):
                code = '%s%s%s' %(line.product_id.id, line.price_unit, line.autorizacion or "")
                group_lines.setdefault(code, {'valor_total':0.0,'quantity':0.0})
                group_lines[code]['move_name']=line.move_name or ""
                group_lines[code]['partner']=line.partner_id
                group_lines[code]['product_id']=line.product_id
                group_lines[code]['quantity'] += line.quantity
                group_lines[code]['tipo_servicio']= tipo_servicio
                group_lines[code]['price_unit'] = (line.price_unit + line.vat_amount)
                group_lines[code]['authorization_number']= line.autorizacion or ""
                group_lines[code]['valor_total'] += (line.price_unit) * line.quantity
                group_lines[code]['move']= line.move_id

            lines_l = list(group_lines.values())
            for line in lines_l:
                dic['AT'] += "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n" %(line['move_name'], 
                                                    line['move'].company_id.partner_id.vat_co, 
                                                    line['move'].patient_id.l10n_latam_identification_type_id.heath_code, 
                                                    line['move'].patient_id.vat_co, 
                                                    line['authorization_number'], line['tipo_servicio'], 
                                                    self._remove_accents(line['product_id'].default_code), self._remove_accents(line['product_id'].name), 
                                                    int(line['quantity']), 
                                                    int(line['price_unit']), 
                                                    int(line['quantity']*line['price_unit']))
        dic['CT']['AT'] += len(lines_l)

        type_ct = ""
        for k,v in dic['CT'].items():
            type_ct += "%s,%s,%s,%s\n" %(
                company.partner_id.vat_co,
                (self.ratication_date).strftime('%d/%m/%Y'),
                "%s%s" %(k,self.name),
                v
                )
        _logger.info('\n\n %r \n\n', type_ct)
        # for k,v in dic.items():
        code = self.name == '/' and '0' or self.name
        file_txt = self.with_context(lines=dic["US"][1][0:-1]).document_print('txt')
        files.append((f'US{code}.txt',file_txt))
        file_txt = self.with_context(lines=dic["AF"][0:-1]).document_print('txt')
        files.append((f'AF{code}.txt',file_txt))
        file_txt = self.with_context(lines=dic["AT"][0:-1]).document_print('txt')
        files.append((f'AT{code}.txt',file_txt))
        file_txt = self.with_context(lines=type_ct[0:-1]).document_print('txt')
        files.append((f'CT{code}.txt',file_txt))

        return files

    def document_print(self, function_name=False):
        output = BytesIO()
        output = self._init_buffer(output, function_name)
        output.seek(0)
        return output.read()

    def _generate_txt(self, output, function_name):
        content = getattr(self, "_get_datas_report_%s" %function_name)(output)
        output.write(content.encode())

    def _get_datas_report_txt(self, output):
        lines = self._context.get('lines') or ""
        return lines

    def _init_buffer(self, output, function_name='xlsx'):
        getattr(self, '_generate_%s' %(function_name or ''))(output, function_name)
        return output

    def action_view_invoice(self):
        return True




class RIPSExport(models.Model):
    _name = 'rips.export'
    _description = 'Exportación de RIPS'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char('Nombre', readonly=True, copy=False)
    active = fields.Boolean(string="Activo", default=True)
    date = fields.Date('Fecha', default=fields.Date.context_today)
    user_id = fields.Many2one('res.users', string='Usuario', default=lambda self: self.env.user)
    company_id = fields.Many2one('res.company', string='Compañía', default=lambda self: self.env.company, readonly=True)
    move_ids = fields.Many2many('account.move', string='Facturas', required=True)
    zip_file = fields.Binary('Archivo ZIP', attachment=True)
    zip_filename = fields.Char('Nombre del archivo ZIP', readonly=True)
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('rips_generated', 'RIPS Generados'),
        ('validated', 'Validado'),
        ('generated', 'ZIP Generado'),
        ('closed', 'Cerrado')
    ], default='draft', string='Estado', readonly=True)
    rips_count = fields.Integer('Cantidad de RIPS', compute='_compute_rips_count')
    pending_count = fields.Integer('Cantidad de Pendiente', compute='_compute_rips_count')
    # Campos existentes
    all_rips_validated = fields.Boolean(
        string='Todos los RIPS Validados',
        compute='_compute_all_rips_validated',
        store=True,
        help="Indica si todas las facturas tienen RIPS validados por el MinSalud"
    )
    
    validation_summary = fields.Text(
        string='Resumen de Validación',
        compute='_compute_validation_summary',
        help="Resumen del estado de validación de los RIPS"
    )
    
    json_data = fields.Text(
        string='JSON Data',
        readonly=True,
        help="Datos JSON de validación del lote"
    )
    
    validation_errors_count = fields.Integer(
        string='Facturas con Errores',
        compute='_compute_validation_errors_count'
    )
    
    validation_success_count = fields.Integer(
        string='Facturas Validadas',
        compute='_compute_validation_success_count'
    )
    
    # NUEVOS CAMPOS MANY2MANY COMPUTADOS
    validated_move_ids = fields.Many2many(
        'account.move',
        string='Facturas Validadas',
        compute='_compute_moves_by_status',
        relation='rips_export_validated_moves',
        column1='rips_export_id',
        column2='move_id'
    )
    
    pending_move_ids = fields.Many2many(
        'account.move',
        string='Facturas Pendientes',
        compute='_compute_moves_by_status',
        relation='rips_export_pending_moves',
        column1='rips_export_id',
        column2='move_id'
    )
    
    error_move_ids = fields.Many2many(
        'account.move',
        string='Facturas con Errores',
        compute='_compute_moves_by_status',
        relation='rips_export_error_moves',
        column1='rips_export_id',
        column2='move_id'
    )
    
    closed_date = fields.Datetime('Fecha de Cierre', readonly=True)
    closed_by = fields.Many2one('res.users', string='Cerrado por', readonly=True)
    
    has_zip = fields.Boolean('Tiene ZIP', compute='_compute_has_zip')
    
    has_non_validated = fields.Boolean(
        'Tiene Facturas No Validadas',
        compute='_compute_has_non_validated'
    )
    support_zip_file = fields.Binary('Archivo ZIP de Soporte', readonly=True, attachment=True)
    support_zip_file_name = fields.Char('Nombre del Archivo ZIP de Soporte', readonly=True)

    # Campo Many2many computado para listar todos los soportes de las facturas
    support_attachment_ids = fields.Many2many(
        'ir.attachment',
        string='Soportes de Facturas',
        compute='_compute_support_attachments',
        help='Lista de todos los archivos de soporte adjuntos a las facturas del lote'
    )

    support_count = fields.Integer(
        string='Cantidad de Soportes',
        compute='_compute_support_attachments'
    )


    def action_split_orders(self):
        """
        Divide la orden actual en múltiples órdenes de máximo 100 facturas cada una
        """
        self.ensure_one()
        
        
        if len(self.move_ids) <= 100:
            raise UserError('La orden tiene 100 facturas o menos. No es necesario dividir.')
        
        all_moves = self.move_ids
        
        batch_size = 100
        move_batches = []
        
        for i in range(0, len(all_moves), batch_size):
            batch = all_moves[i:i + batch_size]
            move_batches.append(batch)
        
        created_orders = self.env['rips.export']
        
        for idx, batch in enumerate(move_batches, 1):
            vals = {
                'date': self.date,
                'user_id': self.user_id.id,
                'company_id': self.company_id.id,
                'move_ids': [(6, 0, batch.ids)],
                'state': 'draft',
            }
            
            new_order = self.create(vals)
            created_orders |= new_order
            
            if not new_order.name:
                new_order.name = self.env['ir.sequence'].next_by_code('rips.export') or f'RIPS/{fields.Date.today()}/LOTE-{idx}'
        
        message = f"""
        <p>Orden dividida exitosamente:</p>
        <ul>
            <li>Facturas originales: {len(all_moves)}</li>
            <li>Órdenes creadas: {len(created_orders)}</li>
            <li>Facturas por orden: {batch_size} (última orden: {len(move_batches[-1])})</li>
        </ul>
        <p>Órdenes creadas:</p>
        <ul>
            {''.join([f'<li><a href="#" data-oe-model="rips.export" data-oe-id="{order.id}">{order.name}</a></li>' for order in created_orders])}
        </ul>
        """
        
        self.message_post(body=message)
        
        self.unlink()
        
        return {
            'name': 'Órdenes RIPS Divididas',
            'type': 'ir.actions.act_window',
            'res_model': 'rips.export',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', created_orders.ids)],
            'context': self.env.context,
            'target': 'current',
        }


    @api.depends('zip_file')
    def _compute_has_zip(self):
        for record in self:
            record.has_zip = bool(record.zip_file)
    
    @api.depends('move_ids', 'move_ids.rips_validation_status')
    def _compute_has_non_validated(self):
        for record in self:
            record.has_non_validated = any(
                move.rips_validation_status != 'validated' 
                for move in record.move_ids
            )
    
    @api.depends('move_ids', 'move_ids.rips_validation_status')
    def _compute_moves_by_status(self):
        """
        Calcula las facturas por estado de validación.
        OPTIMIZADO: Un solo bucle en lugar de 3 filtered() separados.
        """
        for record in self:
            validated_ids = []
            pending_ids = []
            error_ids = []

            # Un solo recorrido en lugar de 3 filtered()
            for move in record.move_ids:
                status = move.rips_validation_status
                if status == 'validated':
                    validated_ids.append(move.id)
                elif status == 'rejected':
                    error_ids.append(move.id)
                else:
                    pending_ids.append(move.id)

            record.validated_move_ids = [(6, 0, validated_ids)]
            record.pending_move_ids = [(6, 0, pending_ids)]
            record.error_move_ids = [(6, 0, error_ids)]
    
    @api.depends('move_ids')
    def _compute_rips_count(self):
        for record in self:
            record.rips_count = len(record.move_ids)
            record.pending_count = len(record.pending_move_ids)

    @api.depends('move_ids')
    def _compute_support_attachments(self):
        """
        Calcula todos los archivos de soporte adjuntos a las facturas del lote.
        Busca archivos en ir.attachment relacionados con las facturas.
        """
        for record in self:
            if not record.move_ids:
                record.support_attachment_ids = [(5, 0, 0)]
                record.support_count = 0
                continue

            # Buscar todos los adjuntos relacionados con las facturas del lote
            attachments = self.env['ir.attachment'].search([
                ('res_model', '=', 'account.move'),
                ('res_id', 'in', record.move_ids.ids),
                ('rips_export_id', '!=', False)
            ])

            record.support_attachment_ids = [(6, 0, attachments.ids)]
            record.support_count = len(attachments)

    @api.depends('move_ids', 'move_ids.rips_validation_status')
    def _compute_all_rips_validated(self):
        for record in self:
            if not record.move_ids:
                record.all_rips_validated = False
            else:
                record.all_rips_validated = all(
                    move.rips_validation_status == 'validated' 
                    for move in record.move_ids
                )
    
    @api.depends('move_ids', 'move_ids.rips_validation_status')
    def _compute_validation_summary(self):
        for record in self:
            if not record.move_ids:
                record.validation_summary = "Sin facturas"
                continue
            
            total = len(record.move_ids)
            validated = len(record.validated_move_ids)
            rejected = len(record.error_move_ids)
            pending = len(record.pending_move_ids)
            
            summary = f"Total: {total} facturas\n"
            summary += f"Validadas: {validated}\n"
            summary += f"Rechazadas: {rejected}\n"
            summary += f"Pendientes: {pending}"
            
            record.validation_summary = summary
    
    @api.depends('move_ids', 'move_ids.rips_validation_status')
    def _compute_validation_errors_count(self):
        for record in self:
            record.validation_errors_count = len(record.error_move_ids)
    
    @api.depends('move_ids', 'move_ids.rips_validation_status')
    def _compute_validation_success_count(self):
        for record in self:
            record.validation_success_count = len(record.validated_move_ids)
    
    @api.model
    def create(self, vals):
        sequence = self.env['ir.sequence'].next_by_code('rips.export.sequence') or 'RIP00001'
        vals['name'] = sequence
        return super(RIPSExport, self).create(vals)
    
    def action_close_batch(self):
        """Cierra el lote de RIPS"""
        self.ensure_one()
        
        if self.state == 'closed':
            raise UserError(_("Este lote ya está cerrado"))
        
        if not self.zip_file:
            raise UserError(_("Debe generar el archivo ZIP antes de cerrar el lote"))
        
        # Registrar cierre
        self.write({
            'state': 'closed',
            'closed_date': fields.Datetime.now(),
            'closed_by': self.env.user.id
        })
        
        # Mensaje en chatter
        self.message_post(
            body=_(
                "<p><b>Lote cerrado</b></p>"
                "<ul>"
                "<li>Cerrado por: %s</li>"
                "<li>Fecha: %s</li>"
                "<li>Total facturas: %s</li>"
                "<li>Validadas: %s</li>"
                "<li>Con errores: %s</li>"
                "<li>Pendientes: %s</li>"
                "</ul>"
            ) % (
                self.env.user.name,
                fields.Datetime.now().strftime('%d/%m/%Y %H:%M'),
                len(self.move_ids),
                len(self.validated_move_ids),
                len(self.error_move_ids),
                len(self.pending_move_ids)
            ),
            message_type='notification',
            subtype_xmlid='mail.mt_note'
        )
        
        return True
    
    def action_exclude_rejected_invoices(self):
        """Excluye las facturas rechazadas y no válidas del lote"""
        self.ensure_one()
        
        if self.state in ['closed']:
            raise UserError(_("No puede modificar un lote cerrado"))
        
        # Obtener facturas a excluir (rechazadas o sin validar)
        rejected_moves = self.move_ids.filtered(
            lambda m: m.rips_validation_status != 'validated'
        )
        
        if not rejected_moves:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Sin facturas para excluir'),
                    'message': _('Todas las facturas están validadas'),
                    'type': 'info',
                    'sticky': False,
                }
            }
        
        # Excluir facturas
        self.move_ids = [(3, move.id, 0) for move in rejected_moves]
        
        # Mensaje en chatter
        self.message_post(
            body=_(
                "<p><b>Facturas excluidas del lote</b></p>"
                "<ul>"
                "<li>Total excluidas: %s</li>"
                "<li>Facturas: %s</li>"
                "<li>Fecha: %s</li>"
                "<li>Usuario: %s</li>"
                "</ul>"
            ) % (
                len(rejected_moves),
                ', '.join(rejected_moves.mapped('name')[:10]),  # Limitar a 10 nombres
                fields.Datetime.now().strftime('%d/%m/%Y %H:%M'),
                self.env.user.name
            ),
            message_type='notification'
        )
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Facturas Excluidas'),
                'message': _('Se excluyeron %s facturas no validadas') % len(rejected_moves),
                'type': 'success',
                'sticky': False,
            }
        }
    
    def action_exclude_closed_batch_invoices(self):
        """Excluye las facturas que ya están en un lote cerrado"""
        self.ensure_one()
        
        if self.state not in ['draft']:
            raise UserError(_("Solo puede excluir facturas en estado Borrador"))
        
        # Buscar facturas que están en lotes cerrados
        closed_batches = self.search([('state', '=', 'closed'), ('id', '!=', self.id)])
        invoices_in_closed_batches = closed_batches.mapped('move_ids')
        
        # Facturas a excluir
        moves_to_exclude = self.move_ids.filtered(lambda m: m in invoices_in_closed_batches)
        
        if not moves_to_exclude:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Sin facturas para excluir'),
                    'message': _('No hay facturas que ya estén en lotes cerrados'),
                    'type': 'info',
                    'sticky': False,
                }
            }
        
        # Excluir facturas
        self.move_ids = [(3, move.id, 0) for move in moves_to_exclude]
        
        # Mensaje en chatter
        self.message_post(
            body=_(
                "<p><b>Facturas excluidas (ya en lotes cerrados)</b></p>"
                "<ul>"
                "<li>Total excluidas: %s</li>"
                "<li>Facturas: %s</li>"
                "</ul>"
            ) % (
                len(moves_to_exclude),
                ', '.join(moves_to_exclude.mapped('name'))
            ),
            message_type='notification'
        )
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Facturas Excluidas'),
                'message': _('Se excluyeron %s facturas que ya están en lotes cerrados') % len(moves_to_exclude),
                'type': 'success',
                'sticky': False,
            }
        }
    
    def action_validate_all_cups(self):
        """Valida todos los códigos CUPS de las facturas del lote"""
        self.ensure_one()
        
        if not self.move_ids:
            raise UserError(_("No hay facturas en el lote"))
        
        validated_count = 0
        errors = []
        
        for move in self.move_ids:
            try:
                move.action_validate_cups_codes()
                validated_count += 1
            except Exception as e:
                errors.append(f"{move.name}: {str(e)}")
        
        message = f"CUPS validados en {validated_count} facturas."
        if errors:
            message += f"\n\nErrores encontrados:\n" + "\n".join(errors)
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Validación CUPS'),
                'message': message,
                'type': 'success' if not errors else 'warning',
                'sticky': True,
            }
        }
    
    def action_consult_and_send_missing_cuvs(self):
        """Consulta CUVs existentes y envía los que faltan"""
        self.ensure_one()
        
        if not self.move_ids:
            raise UserError(_("No hay facturas en el lote"))
        
        consulted = 0
        sent = 0
        validated = 0
        errors = []
        
        for move in self.move_ids:
            try:
                if move.rips_cuv:
                    # Consultar estado del CUV
                    move.action_consult_cuv()
                    consulted += 1
                    
                    if move.rips_validation_status == 'validated':
                        validated += 1
                else:
                    # No tiene CUV, generar y enviar
                    if not move.rips_generated:
                        move.action_generate_rips_json_improved()
                    
                    move.action_send_rips_to_minsalud_improved()
                    sent += 1
                    
                    # Registrar envío en chatter
                    self.message_post(
                        body=_(
                            "<p><b>RIPS enviado al MinSalud</b></p>"
                            "<ul>"
                            "<li>Factura: %s</li>"
                            "<li>Hora: %s</li>"
                            "<li>Estado: Enviado</li>"
                            "</ul>"
                        ) % (move.name, fields.Datetime.now().strftime('%H:%M:%S')),
                        message_type='notification'
                    )
                    
                    if move.rips_validation_status == 'validated':
                        validated += 1
                        
            except Exception as e:
                errors.append(f"{move.name}: {str(e)}")
                _logger.error(f"Error procesando {move.name}: {str(e)}")
        
        # Actualizar JSON Data
        self._update_json_data()
        
        # Actualizar estado
        if self.all_rips_validated:
            self.state = 'validated'
        
        message = f"Proceso completado:\n"
        message += f"- CUVs consultados: {consulted}\n"
        message += f"- RIPS enviados: {sent}\n"
        message += f"- Total validados: {validated}\n"
        
        if errors:
            message += f"\nErrores:\n" + "\n".join(errors[:5])
            if len(errors) > 5:
                message += f"\n... y {len(errors) - 5} errores más"
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Consulta y Envío de CUVs'),
                'message': message,
                'type': 'info' if validated > 0 else 'warning',
                'sticky': True,
            }
        }
    
    def action_generate_rips_batch(self):
        """Genera y envía los RIPS de todas las facturas del lote"""
        self.ensure_one()
        
        if not self.move_ids:
            raise UserError(_("No hay facturas en el lote"))
        
        # Contador de resultados
        generated = 0
        sent = 0
        validated = 0
        errors = []
        json_results = []
        
        # Mensaje inicial en chatter
        self.message_post(
            body=_(
                "<p><b>Iniciando generación de RIPS en lote</b></p>"
                "<ul>"
                "<li>Total de facturas: %s</li>"
                "<li>Hora de inicio: %s</li>"
                "</ul>"
            ) % (len(self.move_ids), fields.Datetime.now().strftime('%d/%m/%Y %H:%M:%S')),
            message_type='notification'
        )
        
        for move in self.move_ids:
            try:
                # Generar RIPS si no existe o no está validado
                if not move.rips_generated or move.rips_validation_status != 'validated':
                    move.action_generate_rips_json_improved()
                    generated += 1
                
                # Enviar al MinSalud si no está validado
                if move.rips_validation_status != 'validated':
                    move.action_send_rips_to_minsalud_improved()
                    sent += 1
                    
                    # Registrar cada envío en el chatter
                    self.message_post(
                        body=_(
                            "<p><b>RIPS enviado al MinSalud</b></p>"
                            "<ul>"
                            "<li>Factura: %s</li>"
                            "<li>Hora: %s</li>"
                            "<li>CUV: %s</li>"
                            "</ul>"
                        ) % (
                            move.name, 
                            fields.Datetime.now().strftime('%H:%M:%S'),
                            move.rips_cuv or 'Pendiente'
                        ),
                        message_type='notification'
                    )
                
                # Verificar estado final
                if move.rips_validation_status == 'validated':
                    validated += 1
                    # Mensaje de validación exitosa
                    self.message_post(
                        body=_(
                            "<p><b>RIPS validado exitosamente</b></p>"
                            "<ul>"
                            "<li>Factura: %s</li>"
                            "<li>CUV: %s</li>"
                            "<li>Proceso ID: %s</li>"
                            "</ul>"
                        ) % (
                            move.name,
                            move.rips_cuv,
                            move.rips_proceso_id or 'N/A'
                        ),
                        message_type='notification',
                        subtype_xmlid='mail.mt_comment'
                    )
                    
                    # Agregar resultado exitoso al JSON
                    json_results.append({
                        "ResultState": True,
                        "ProcesoId": move.rips_proceso_id or "N/A",
                        "NumFactura": move.name,
                        "CodigoUnicoValidacion": move.rips_cuv or "",
                        "FechaRadicacion": move.rips_validation_date.isoformat() if move.rips_validation_date else "",
                        "ResultadosValidacion": []
                    })
                else:
                    # Mensaje de error
                    validation_errors = self._extract_validation_errors(move)
                    error_message = "<p><b>Error en validación RIPS</b></p><ul><li>Factura: %s</li>" % move.name
                    
                    if validation_errors:
                        error_message += "<li>Errores:<ul>"
                        for error in validation_errors[:3]:  # Mostrar máximo 3 errores
                            if isinstance(error, dict):
                                error_message += "<li>%s</li>" % (error.get('Descripcion', str(error)))
                            else:
                                error_message += "<li>%s</li>" % str(error)
                        if len(validation_errors) > 3:
                            error_message += "<li>... y %s errores más</li>" % (len(validation_errors) - 3)
                        error_message += "</ul></li>"
                    
                    error_message += "</ul>"
                    
                    self.message_post(
                        body=error_message,
                        message_type='notification',
                        subtype_xmlid='mail.mt_comment'
                    )
                    
                    # Agregar resultado con errores
                    json_results.append({
                        "ResultState": False,
                        "ProcesoId": move.rips_proceso_id or "N/A",
                        "NumFactura": move.name,
                        "CodigoUnicoValidacion": move.rips_cuv or "No aplica",
                        "FechaRadicacion": datetime.now().isoformat(),
                        "ResultadosValidacion": validation_errors
                    })
                
                # Commit después de cada factura procesada
                self.env.cr.commit()
                    
            except Exception as e:
                self.env.cr.rollback()
                errors.append(f"{move.name}: {str(e)}")
                _logger.error(f"Error procesando RIPS para {move.name}: {str(e)}")
                
                # Mensaje de error técnico
                self.message_post(
                    body=_(
                        "<p><b>Error técnico en RIPS</b></p>"
                        "<ul>"
                        "<li>Factura: %s</li>"
                        "<li>Error: %s</li>"
                        "</ul>"
                    ) % (move.name, str(e)),
                    message_type='notification'
                )
        
        # Actualizar JSON Data con resultados
        self.json_data = json.dumps(json_results, indent=2, ensure_ascii=False)
        
        # Actualizar estado
        if self.all_rips_validated:
            self.state = 'validated'
        else:
            self.state = 'rips_generated'
        
        # Commit final
        self.env.cr.commit()
        
        # Mensaje resumen final
        self.message_post(
            body=_(
                "<p><b>Proceso de generación RIPS completado</b></p>"
                "<ul>"
                "<li>Hora de finalización: %s</li>"
                "<li>RIPS generados: %s</li>"
                "<li>RIPS enviados: %s</li>"
                "<li>RIPS validados: %s</li>"
                "<li>Errores: %s</li>"
                "</ul>"
            ) % (
                fields.Datetime.now().strftime('%d/%m/%Y %H:%M:%S'),
                generated,
                sent,
                validated,
                len(errors)
            ),
            message_type='notification',
            subtype_xmlid='mail.mt_comment'
        )
        
        # Mensaje de resultado
        message = f"Proceso completado:\n"
        message += f"- RIPS generados: {generated}\n"
        message += f"- RIPS enviados: {sent}\n"
        message += f"- RIPS validados: {validated}\n"
        
        if errors:
            message += f"\nErrores encontrados:\n"
            message += "\n".join(errors)
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Generación de RIPS en Lote'),
                'message': message,
                'type': 'info' if validated > 0 else 'warning',
                'sticky': True,
            }
        }
    
    def _update_json_data(self):
        """Actualiza el JSON Data con el estado actual de las facturas"""
        json_results = []
        
        for move in self.move_ids:
            if move.rips_validation_status == 'validated':
                json_results.append({
                    "ResultState": True,
                    "ProcesoId": move.rips_proceso_id or "N/A",
                    "NumFactura": move.name,
                    "CodigoUnicoValidacion": move.rips_cuv or "",
                    "FechaRadicacion": move.rips_validation_date.isoformat() if move.rips_validation_date else "",
                    "ResultadosValidacion": []
                })
            else:
                json_results.append({
                    "ResultState": False,
                    "ProcesoId": move.rips_proceso_id or "N/A",
                    "NumFactura": move.name,
                    "CodigoUnicoValidacion": move.rips_cuv or "No aplica",
                    "FechaRadicacion": datetime.now().isoformat(),
                    "ResultadosValidacion": self._extract_validation_errors(move) if move.rips_response_json else []
                })
        
        self.json_data = json.dumps(json_results, indent=2, ensure_ascii=False)
    
    def _extract_validation_errors(self, move):
        """Extrae los errores de validación de una factura"""
        if not move.rips_response_json:
            return []
        
        try:
            response = json.loads(move.rips_response_json)
            return response.get('ResultadosValidacion', response.get('resultados_validacion', []))
        except:
            return []
    
    def action_check_validation_status(self):
        """Consulta el estado de validación de todos los RIPS"""
        self.ensure_one()
        
        updated = 0
        json_results = []
        
        # Mensaje inicial
        self.message_post(
            body=_(
                "<p><b>Consultando estado de validación</b></p>"
                "<p>Consultando %s CUVs...</p>"
            ) % len(self.move_ids.filtered('rips_cuv')),
            message_type='notification'
        )
        
        for move in self.move_ids:
            if move.rips_cuv:
                try:
                    # Consultar estado del CUV
                    old_status = move.rips_validation_status
                    move.action_consult_cuv()
                    updated += 1
                    
                    # Si cambió el estado, registrar
                    if old_status != move.rips_validation_status:
                        self.message_post(
                            body=_(
                                "<p><b>Cambio de estado</b></p>"
                                "<ul>"
                                "<li>Factura: %s</li>"
                                "<li>Estado anterior: %s</li>"
                                "<li>Estado nuevo: %s</li>"
                                "<li>CUV: %s</li>"
                                "</ul>"
                            ) % (
                                move.name,
                                dict(move._fields['rips_validation_status'].selection).get(old_status, old_status),
                                dict(move._fields['rips_validation_status'].selection).get(move.rips_validation_status, move.rips_validation_status),
                                move.rips_cuv
                            ),
                            message_type='notification'
                        )
                    
                    # Agregar resultado al JSON
                    json_results.append({
                        "ResultState": move.rips_validation_status == 'validated',
                        "ProcesoId": move.rips_proceso_id or "N/A",
                        "NumFactura": move.name,
                        "CodigoUnicoValidacion": move.rips_cuv,
                        "FechaRadicacion": move.rips_validation_date.isoformat() if move.rips_validation_date else "",
                        "ResultadosValidacion": self._extract_validation_errors(move) if move.rips_validation_status != 'validated' else []
                    })
                    
                    # Commit después de cada consulta
                    self.env.cr.commit()
                    
                except Exception as e:
                    self.env.cr.rollback()
                    _logger.error(f"Error consultando CUV para {move.name}: {str(e)}")
        
        # Actualizar JSON Data
        if json_results:
            self.json_data = json.dumps(json_results, indent=2, ensure_ascii=False)
        
        # Actualizar estado si todos están validados
        if self.all_rips_validated:
            self.state = 'validated'
        
        # Mensaje resumen
        self.message_post(
            body=_(
                "<p><b>Consulta de estado completada</b></p>"
                "<ul>"
                "<li>CUVs consultados: %s</li>"
                "<li>Validados: %s</li>"
                "<li>Con errores: %s</li>"
                "<li>Pendientes: %s</li>"
                "</ul>"
            ) % (
                updated,
                len(self.validated_move_ids),
                len(self.error_move_ids),
                len(self.pending_move_ids)
            ),
            message_type='notification'
        )
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Consulta de Estado'),
                'message': _('Se actualizó el estado de %s facturas') % updated,
                'type': 'success',
                'sticky': False,
            }
        }
        
    def action_generate_rips_batch(self):
        """Genera y envía los RIPS de todas las facturas del lote"""
        self.ensure_one()
        
        if not self.move_ids:
            raise UserError(_("No hay facturas en el lote"))
        
        # Contador de resultados
        generated = 0
        sent = 0
        validated = 0
        errors = []
        json_results = []
        
        for move in self.move_ids:
            try:
                # Generar RIPS si no existe o no está validado
                if not move.rips_generated or move.rips_validation_status != 'validated':
                    move.action_generate_rips_json_improved()
                    generated += 1
                
                # Enviar al MinSalud si no está validado
                if move.rips_validation_status != 'validated':
                    move.action_send_rips_to_minsalud_improved()
                    sent += 1
                
                # Verificar estado final
                if move.rips_validation_status == 'validated':
                    validated += 1
                    # Agregar resultado exitoso al JSON
                    json_results.append({
                        "ResultState": True,
                        "ProcesoId": move.rips_proceso_id or "N/A",
                        "NumFactura": move.name,
                        "CodigoUnicoValidacion": move.rips_cuv or "",
                        "FechaRadicacion": move.rips_validation_date.isoformat() if move.rips_validation_date else "",
                        "ResultadosValidacion": []
                    })
                else:
                    # Agregar resultado con errores
                    json_results.append({
                        "ResultState": False,
                        "ProcesoId": move.rips_proceso_id or "N/A",
                        "NumFactura": move.name,
                        "CodigoUnicoValidacion": move.rips_cuv or "No aplica",
                        "FechaRadicacion": datetime.now().isoformat(),
                        "ResultadosValidacion": self._extract_validation_errors(move)
                    })
                
                # Commit después de cada factura procesada
                self.env.cr.commit()
                    
            except Exception as e:
                self.env.cr.rollback()
                errors.append(f"{move.name}: {str(e)}")
                _logger.error(f"Error procesando RIPS para {move.name}: {str(e)}")
        
        # Actualizar JSON Data con resultados
        self.json_data = json.dumps(json_results, indent=2, ensure_ascii=False)
        
        # Actualizar estado
        if self.all_rips_validated:
            self.state = 'validated'
        else:
            self.state = 'rips_generated'
        
        # Commit final
        self.env.cr.commit()
        
        # Mensaje de resultado
        message = f"Proceso completado:\n"
        message += f"- RIPS generados: {generated}\n"
        message += f"- RIPS enviados: {sent}\n"
        message += f"- RIPS validados: {validated}\n"
        
        if errors:
            message += f"\nErrores encontrados:\n"
            message += "\n".join(errors)
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Generación de RIPS en Lote'),
                'message': message,
                'type': 'info' if validated > 0 else 'warning',
                'sticky': True,
            }
        }
    
    def _update_json_data(self):
        """Actualiza el JSON Data con el estado actual de las facturas"""
        json_results = []
        
        for move in self.move_ids:
            if move.rips_validation_status == 'validated':
                json_results.append({
                    "ResultState": True,
                    "ProcesoId": move.rips_proceso_id or "N/A",
                    "NumFactura": move.name,
                    "CodigoUnicoValidacion": move.rips_cuv or "",
                    "FechaRadicacion": move.rips_validation_date.isoformat() if move.rips_validation_date else "",
                    "ResultadosValidacion": []
                })
            else:
                json_results.append({
                    "ResultState": False,
                    "ProcesoId": move.rips_proceso_id or "N/A",
                    "NumFactura": move.name,
                    "CodigoUnicoValidacion": move.rips_cuv or "No aplica",
                    "FechaRadicacion": datetime.now().isoformat(),
                    "ResultadosValidacion": self._extract_validation_errors(move) if move.rips_response_json else []
                })
        
        self.json_data = json.dumps(json_results, indent=2, ensure_ascii=False)
    
    def _extract_validation_errors(self, move):
        """Extrae los errores de validación de una factura"""
        if not move.rips_response_json:
            return []
        
        try:
            response = json.loads(move.rips_response_json)
            return response.get('ResultadosValidacion', response.get('resultados_validacion', []))
        except:
            return []
    
    def action_check_validation_status(self):
        """Consulta el estado de validación de todos los RIPS"""
        self.ensure_one()
        
        updated = 0
        json_results = []
        
        for move in self.move_ids:
            if move.rips_cuv:
                try:
                    # Consultar estado del CUV
                    move.action_consult_cuv()
                    updated += 1
                    
                    # Agregar resultado al JSON
                    json_results.append({
                        "ResultState": move.rips_validation_status == 'validated',
                        "ProcesoId": move.rips_proceso_id or "N/A",
                        "NumFactura": move.name,
                        "CodigoUnicoValidacion": move.rips_cuv,
                        "FechaRadicacion": move.rips_validation_date.isoformat() if move.rips_validation_date else "",
                        "ResultadosValidacion": self._extract_validation_errors(move) if move.rips_validation_status != 'validated' else []
                    })
                    
                    # Commit después de cada consulta
                    self.env.cr.commit()
                    
                except Exception as e:
                    self.env.cr.rollback()
                    _logger.error(f"Error consultando CUV para {move.name}: {str(e)}")
        
        # Actualizar JSON Data
        if json_results:
            self.json_data = json.dumps(json_results, indent=2, ensure_ascii=False)
        
        # Actualizar estado si todos están validados
        if self.all_rips_validated:
            self.state = 'validated'
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Consulta de Estado'),
                'message': _('Se actualizó el estado de %s facturas') % updated,
                'type': 'success',
                'sticky': False,
            }
        }


    def generate_zip(self):
        """Genera un archivo ZIP con los documentos RIPS de todas las facturas del lote."""
        
        def clean_json_data(data):
            """Extrae y parsea el response_text del JSON RIPS de manera eficiente."""
            if not isinstance(data, (str, dict)):
                return data
                
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except json.JSONDecodeError:
                    return data
            
            # Si no es diccionario o no tiene response_text, retornar tal cual
            if not isinstance(data, dict) or 'response_text' not in data:
                return data
                
            # Intentar parsear response_text
            response_text = data.get('response_text')
            if response_text and isinstance(response_text, str):
                try:
                    return json.loads(response_text)
                except json.JSONDecodeError:
                    pass
                    
            return data

        def process_rips_response(move):
            """Procesa la respuesta RIPS y genera el contenido del archivo de resultado."""
            if not move.rips_response_json:
                return None, None
            
            try:
                # Parsear y limpiar datos en un solo paso
                response_data = json.loads(move.rips_response_json)
                clean_data = clean_json_data(response_data)
                data_to_save = clean_data if clean_data != response_data else response_data
                
                # Determinar estado y proceso_id usando diccionarios para evitar múltiples if
                validation_keys = {
                    ('ResultState', 'ProcesoId', 'NumFactura'): lambda d: ('A' if d.get('ResultState') else 'R', d.get('ProcesoId', 'SIN_ID'), d.get('NumFactura', move.name)),
                    ('EsValido', 'ProcesoId', 'NumeroDocumento'): lambda d: ('A' if d.get('EsValido') else 'R', d.get('ProcesoId', 'SIN_ID'), d.get('NumeroDocumento', move.name))
                }
                
                estado, proceso_id, num_factura = 'RESP', 'COMPLETO', move.name
                
                for keys, extractor in validation_keys.items():
                    if all(k in data_to_save for k in keys[:2]):
                        estado, proceso_id, num_factura = extractor(data_to_save)
                        break
                
                filename = f"ResultadosMSPS_{num_factura}_ID{proceso_id}_{estado}_CUV.txt"
                content_bytes = json.dumps(data_to_save, indent=2, ensure_ascii=False).encode('utf-8')
                
                return filename, content_bytes
                
            except (json.JSONDecodeError, Exception) as e:
                _logger.error(f"Error procesando respuesta RIPS para {move.name}: {str(e)}")
                return None, None

        def get_all_support_files_batch():
            """
            Obtiene todos los archivos de soporte en una sola búsqueda.
            OPTIMIZADO: Busca todos los adjuntos de una vez en lugar de una por factura.
            """
            support_files_by_move = {}

            if not self.move_ids:
                return support_files_by_move

            # UNA SOLA búsqueda para todas las facturas
            attachments = self.env['ir.attachment'].search([
                ('res_model', '=', 'account.move'),
                ('res_id', 'in', self.move_ids.ids),
                ('rips_export_id', '!=', False)
            ])

            # Procesar por factura
            for attachment in attachments:
                move_id = attachment.res_id
                if move_id not in support_files_by_move:
                    support_files_by_move[move_id] = []

                try:
                    file_data = base64.b64decode(attachment.datas)

                    # Si es ZIP, descomprimir
                    if attachment.name.lower().endswith('.zip'):
                        try:
                            with zipfile.ZipFile(BytesIO(file_data), 'r') as zip_file:
                                for file_name in zip_file.namelist():
                                    if not file_name.endswith('/'):
                                        clean_name = os.path.basename(file_name)
                                        if clean_name:
                                            support_files_by_move[move_id].append({
                                                'name': clean_name,
                                                'content': zip_file.read(file_name)
                                            })
                        except zipfile.BadZipFile:
                            _logger.warning(f"Archivo ZIP corrupto: {attachment.name}")
                            continue
                    else:
                        # Archivo directo
                        support_files_by_move[move_id].append({
                            'name': attachment.name,
                            'content': file_data
                        })
                except Exception as e:
                    _logger.error(f"Error procesando soporte {attachment.name}: {str(e)}")
                    continue

            return support_files_by_move

        # Validaciones iniciales
        self.ensure_one()
        
        # Verificar RIPS generados
        moves_without_rips = self.move_ids.filtered(lambda m: not m.rips_generated)
        if moves_without_rips:
            raise UserError(_(
                "Las siguientes facturas no tienen RIPS generado:\n%s\n\n"
                "Use el botón 'Generar RIPS del Lote' primero."
            ) % '\n'.join(moves_without_rips.mapped('name')))
        
        # Log de advertencia para facturas no validadas (una sola operación)
        if not self.all_rips_validated:
            moves_not_validated = self.move_ids.filtered(lambda m: m.rips_validation_status != 'validated')
            if moves_not_validated:
                _logger.warning(
                    "Facturas no validadas por MinSalud: %s", 
                    ', '.join(moves_not_validated.mapped('name'))
                )
        
        # Preparar datos comunes
        company_vat = self.move_ids[0].company_id.partner_id.vat_co if self.move_ids else ''
        today = datetime.now().strftime('%Y%m%d')
        attachment_name = f'RIPS_{self.name}_{today}.zip'

        # OPTIMIZACIÓN: Obtener todos los archivos de soporte EN UNA SOLA búsqueda
        _logger.info(f"Obteniendo archivos de soporte para {len(self.move_ids)} facturas...")
        support_files_by_move = get_all_support_files_batch()
        _logger.info(f"Archivos de soporte obtenidos: {sum(len(files) for files in support_files_by_move.values())} total")

        # Generar ZIP principal
        zip_buffer = BytesIO()

        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as main_zip:
            # Crear carpetas principales una sola vez
            main_zip.writestr("CUV/", "")
            main_zip.writestr("JSON/", "")
            main_zip.writestr("SOPORTES/", "")

            # Procesar facturas
            successful_moves = []
            support_stats = {'total': 0, 'by_invoice': {}}

            for move in self.move_ids:
                base_name = f"FVS_{company_vat}_{move.name}"
                base_result_name = f"PDX_{company_vat}_{move.name}"

                constants = self.env['dian.document']._generate_dian_constants(move, move.move_type, False)
                xml_content = self.env['dian.xml.builder'].generate_xml(move, constants)
                xml_content, error = move._get_attached_document(xml_content)
                if error:
                    _logger.warning(f"Error XML para {move.name}: {error}")

                # Generar PDF
                pdf_content = self.env['report.invoice_reportlab.report_invoice'].generate_pdf(move)
                support_files = support_files_by_move.get(move.id, [])
                
                if support_files:
                    support_stats['total'] += len(support_files)
                    support_stats['by_invoice'][move.name] = len(support_files)

                # Crear ZIP interno con XML y PDF (sin soportes)
                inner_zip_name = f"{base_name}.zip"
                inner_buffer = BytesIO()
                with zipfile.ZipFile(inner_buffer, 'w', zipfile.ZIP_DEFLATED) as inner_zip:
                    # Agregar XML si existe
                    if xml_content:
                        inner_zip.writestr(f"{base_name}_AttachedDocument.xml", xml_content)
                    
                    # Agregar PDF
                    inner_zip.writestr(f"{base_name}.pdf", pdf_content)
                
                # Agregar ZIP interno al principal
                main_zip.writestr(inner_zip_name, inner_buffer.getvalue())
                
                # Crear ZIP de SOPORTES si hay archivos de soporte
                if support_files:
                    inner_soporte_zip_name = f"SOPORTES/{base_result_name}.zip"
                    inner_support_buffer = BytesIO()
                    
                    with zipfile.ZipFile(inner_support_buffer, 'w', zipfile.ZIP_DEFLATED) as inner_support_zip:
                        # Agregar PDF como soporte también
                        inner_support_zip.writestr(f"{base_name}.pdf", pdf_content)
                        
                        # Agregar todos los archivos de soporte
                        for support_file in support_files:
                            inner_support_zip.writestr(
                                f"{support_file['name']}", 
                                support_file['content']
                            )
                    
                    # Agregar ZIP de soportes al principal
                    main_zip.writestr(inner_soporte_zip_name, inner_support_buffer.getvalue())
                
                # Procesar respuesta RIPS
                result_filename, result_content = process_rips_response(move)
                if result_content:
                    main_zip.writestr(f"CUV/{result_filename}", result_content)
                
                if move.rips_json_binary:
                    json_content = base64.b64decode(move.rips_json_binary)
                    main_zip.writestr(f"JSON/{base_name}.json", json_content)
                
                successful_moves.append(move.id)
                    
   
        zip_data = base64.b64encode(zip_buffer.getvalue())
        zip_size_kb = len(zip_data) // 1024
        
        # Crear attachment
        attachment = self.env['ir.attachment'].create({
            'name': attachment_name,
            'type': 'binary',
            'datas': zip_data,
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/zip'
        })
        
        # OPTIMIZADO: Usar ORM en lugar de SQL directo para trazabilidad
        if successful_moves:
            moves_to_update = self.env['account.move'].browse(successful_moves)
            moves_to_update.write({'ripsjson_id': self.id})
        
        # Actualizar estado del lote
        self.write({
            'zip_file': zip_data,
            'zip_filename': attachment_name,
            'state': 'generated'
        })
        
        # Mensaje en chatter con información detallada
        message_body = f"""
            <p><b>Archivo ZIP generado exitosamente:</b></p>
            <ul>
                <li><b>Archivo:</b> {attachment_name}</li>
                <li><b>Tamaño:</b> {zip_size_kb} KB</li>
                <li><b>Facturas procesadas:</b> {len(successful_moves)}/{len(self.move_ids)}</li>
        """
        
        if support_stats['total'] > 0:
            message_body += f"""
                <li><b>Archivos de soporte incluidos:</b> {support_stats['total']} archivos en {len(support_stats['by_invoice'])} facturas</li>
            """
            
            # Detallar facturas con soportes si no son muchas
            if len(support_stats['by_invoice']) <= 10:
                message_body += "<li><b>Detalle de soportes:</b><ul>"
                for invoice_name, count in support_stats['by_invoice'].items():
                    message_body += f"<li>{invoice_name}: {count} archivo(s)</li>"
                message_body += "</ul></li>"
        
        message_body += "</ul>"
        

        self.message_post(
            body=message_body,
            message_type='notification'
        )
        
        # Retornar acción de descarga
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    # Mantener las funciones existentes de importación sin cambios
    def action_import_support_zip(self):
        """Importa y procesa los archivos de soporte del ZIP"""
        self.ensure_one()
        
        if not self.support_zip_file:
            raise UserError(_('Por favor, seleccione un archivo ZIP de soportes'))
        
        if not self.move_ids:
            raise UserError(_('No hay facturas en este lote RIPS'))
        
        # Crear índice de facturas para búsqueda rápida
        invoice_index = self._build_invoice_index()
        
        # Estadísticas
        stats = {
            'total': 0,
            'processed': 0,
            'not_found': [],
            'by_invoice': defaultdict(list)
        }
        
        try:
            zip_data = base64.b64decode(self.support_zip_file)
            zip_buffer = io.BytesIO(zip_data)
            
            with zipfile.ZipFile(zip_buffer, 'r') as zip_file:
                for file_path in zip_file.namelist():
                    if file_path.endswith('/'):
                        continue
                    
                    filename = os.path.basename(file_path)
                    if not filename:
                        continue
                    
                    stats['total'] += 1
                    
                    invoice_ref = self._extract_invoice_ref(filename)
                    
                    invoice = self._find_invoice(invoice_ref, invoice_index)
                    
                    if not invoice:
                        stats['not_found'].append(f"{filename} ({invoice_ref})")
                        continue
                    
                    file_content = zip_file.read(file_path)
                    
                    stats['by_invoice'][invoice.id].append({
                        'name': filename,
                        'data': base64.b64encode(file_content).decode('utf-8')
                    })
            
            for invoice_id, files in stats['by_invoice'].items():
                invoice = self.env['account.move'].browse(invoice_id)
                
                if len(files) > 1:
                    self._create_zip_attachment(invoice, files)
                else:
                    self._create_simple_attachment(invoice, files[0])
                
                stats['processed'] += len(files)
            
            self._log_import_result(stats)
            
            # Mensaje especial indicando que se incluirán en el ZIP
            additional_message = _(
                "<p><b>Los archivos de soporte se incluirán automáticamente en el ZIP individual de cada factura al generar el lote.</b></p>"
            )
            self.message_post(body=additional_message, message_type='notification')
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Importación completada'),
                    'message': _(f"{stats['processed']} archivos procesados de {stats['total']}. Se incluirán en el ZIP al generarlo."),
                    'type': 'success' if not stats['not_found'] else 'warning',
                    'sticky': False,
                }
            }
            
        except Exception as e:
            raise UserError(_('Error al procesar el ZIP: %s') % str(e))

    def action_generate(self):
        """Acción para generar el archivo ZIP"""
        self.ensure_one()
        self.generate_zip()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'rips.export',
            'view_mode': 'form',
            'res_id': self.id,
            'views': [(False, 'form')],
            'target': 'current',
        }
    
    def action_download(self):
        """Acción para descargar el archivo ZIP"""
        self.ensure_one()
        if not self.zip_file:
            raise UserError(_("No hay archivo ZIP generado. Use el botón 'Generar ZIP' primero."))
        
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/?model=rips.export&id={self.id}&field=zip_file&filename={self.zip_filename}&download=true',
            'target': 'self',
        }
    
    def action_view_invoices(self):
        """Ver las facturas del lote"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Facturas del Lote'),
            'res_model': 'account.move',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', self.move_ids.ids)],
            'context': self.env.context,
        }
    
    def action_filter_validated_invoices(self):
        """Muestra solo las facturas validadas que no están en otro lote"""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Facturas Validadas Disponibles'),
            'res_model': 'account.move',
            'view_mode': 'tree,form',
            'domain': [
                ('rips_validation_status', '=', 'validated'),
                ('ripsjson_id', '=', False),
                ('move_type', 'in', ['out_invoice', 'out_refund'])
            ],
            'context': {
                'search_default_validated_rips': 1,
                'search_default_not_in_batch': 1,
            },
        }

    def action_generate(self):
        """Acción para generar el archivo ZIP"""
        self.ensure_one()
        return self.generate_zip()
    
    def action_download(self):
        """Acción para descargar el archivo ZIP"""
        self.ensure_one()
        if not self.zip_file:
            raise UserError(_("No hay archivo ZIP generado. Use el botón 'Generar ZIP' primero."))
        
        # Buscar el attachment más reciente
        attachment = self.env['ir.attachment'].search([
            ('res_model', '=', self._name),
            ('res_id', '=', self.id),
            ('name', '=', self.zip_filename)
        ], limit=1, order='id desc')
        
        if attachment:
            return {
                'type': 'ir.actions.act_url',
                'url': f'/web/content/{attachment.id}?download=true',
                'target': 'self',
            }
        else:
            # Si no hay attachment, crear uno nuevo
            attachment = self.env['ir.attachment'].create({
                'name': self.zip_filename,
                'type': 'binary',
                'datas': self.zip_file,
                'res_model': self._name,
                'res_id': self.id,
                'mimetype': 'application/zip'
            })
            
            return {
                'type': 'ir.actions.act_url',
                'url': f'/web/content/{attachment.id}?download=true',
                'target': 'self',
            }
    
    def action_view_invoices(self):
        """Ver las facturas del lote"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Facturas del Lote'),
            'res_model': 'account.move',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', self.move_ids.ids)],
            'context': self.env.context,
        }
    
    def action_view_validated_invoices(self):
        """Ver solo las facturas validadas del lote"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Facturas Validadas'),
            'res_model': 'account.move',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', self.validated_move_ids.ids)],
            'context': {
                'default_search_rips_validation_status': 'validated',
                'group_by': ['rips_validation_status']
            },
        }
    
    def action_view_pending_invoices(self):
        """Ver solo las facturas pendientes del lote"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Facturas Pendientes'),
            'res_model': 'account.move',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', self.pending_move_ids.ids)],
            'context': {
                'group_by': ['rips_validation_status']
            },
        }
    
    def action_view_error_invoices(self):
        """Ver solo las facturas con errores del lote"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Facturas con Errores'),
            'res_model': 'account.move',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', self.error_move_ids.ids)],
            'context': {
                'default_search_rips_validation_status': 'rejected',
                'group_by': ['rips_validation_status']
            },
        }

        
    def action_import_support_zip(self):
        """Importa y procesa los archivos de soporte del ZIP"""
        self.ensure_one()
        
        if not self.support_zip_file:
            raise UserError(_('Por favor, seleccione un archivo ZIP de soportes'))
        
        if not self.move_ids:
            raise UserError(_('No hay facturas en este lote RIPS'))
        
        # Crear índice de facturas para búsqueda rápida
        invoice_index = self._build_invoice_index()
        
        # Estadísticas
        stats = {
            'total': 0,
            'processed': 0,
            'not_found': [],
            'by_invoice': defaultdict(list)
        }
        
        # Debug: Mostrar facturas disponibles
        _logger.info("Facturas disponibles en el lote:")
        for move in self.move_ids:
            _logger.info(f"  - {move.name} (ref: {move.ref}, payment_ref: {move.payment_reference})")
        
        try:
            zip_data = base64.b64decode(self.support_zip_file)
            zip_buffer = io.BytesIO(zip_data)
            
            with zipfile.ZipFile(zip_buffer, 'r') as zip_file:
                for file_path in zip_file.namelist():
                    if file_path.endswith('/'):
                        continue
                    
                    filename = os.path.basename(file_path)
                    if not filename:
                        continue
                    
                    stats['total'] += 1
                    
                    # Extraer referencia de factura con método mejorado
                    invoice_ref = self._extract_invoice_ref_improved(filename)
                    _logger.info(f"Procesando archivo: {filename} -> Referencia extraída: {invoice_ref}")
                    
                    # Buscar factura con método mejorado
                    invoice = self._find_invoice_improved(invoice_ref, invoice_index)
                    
                    if not invoice:
                        stats['not_found'].append(f"{filename} ({invoice_ref})")
                        _logger.warning(f"No se encontró factura para: {filename} (ref: {invoice_ref})")
                        continue
                    
                    _logger.info(f"Archivo {filename} asociado con factura {invoice.name}")
                    
                    file_content = zip_file.read(file_path)
                    
                    stats['by_invoice'][invoice.id].append({
                        'name': filename,
                        'data': base64.b64encode(file_content).decode('utf-8')
                    })
            
            for invoice_id, files in stats['by_invoice'].items():
                invoice = self.env['account.move'].browse(invoice_id)
                
                if len(files) > 1:
                    self._create_zip_attachment(invoice, files)
                else:
                    self._create_simple_attachment(invoice, files[0])
                
                stats['processed'] += len(files)
            
            self._log_import_result(stats)
            
            # Mensaje especial indicando que se incluirán en el ZIP
            if stats['processed'] > 0:
                additional_message = _(
                    "<p><b>Los archivos de soporte se incluirán automáticamente en el ZIP individual de cada factura al generar el lote.</b></p>"
                )
                self.message_post(body=additional_message, message_type='notification')
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Importación completada'),
                    'message': _(f"{stats['processed']} archivos procesados de {stats['total']}. Se incluirán en el ZIP al generarlo."),
                    'type': 'success' if not stats['not_found'] else 'warning',
                    'sticky': False,
                }
            }
            
        except Exception as e:
            raise UserError(_('Error al procesar el ZIP: %s') % str(e))

    def _build_invoice_index(self):
        """Construye un índice mejorado para búsqueda rápida de facturas"""
        index = {}
        
        for move in self.move_ids:
            # Indexar por nombre completo
            if move.name:
                index[move.name.upper()] = move
                index[move.name.upper().replace(' ', '')] = move
                
                # Extraer solo números del nombre
                numbers = re.sub(r'[^0-9]', '', move.name)
                if numbers:
                    index[numbers] = move
                    # También indexar los últimos 6-8 dígitos si hay más
                    if len(numbers) >= 6:
                        index[numbers[-6:]] = move
                        index[numbers[-7:]] = move
                        index[numbers[-8:]] = move
            
            # Indexar por referencia
            if move.ref:
                index[move.ref.upper()] = move
                index[move.ref.upper().replace(' ', '')] = move
                ref_numbers = re.sub(r'[^0-9]', '', move.ref)
                if ref_numbers:
                    index[ref_numbers] = move
            
            # Indexar por referencia de pago
            if move.payment_reference:
                index[move.payment_reference.upper()] = move
                index[move.payment_reference.upper().replace(' ', '')] = move
                pay_numbers = re.sub(r'[^0-9]', '', move.payment_reference)
                if pay_numbers:
                    index[pay_numbers] = move
            
            # Agregar variaciones comunes
            # Si el nombre es algo como "FE-873631" o "FE 873631"
            if move.name:
                # Quitar prefijos comunes y espacios/guiones
                clean_name = move.name.upper()
                for prefix in ['FE', 'FV', 'NC', 'ND', 'FAC', 'FACT']:
                    if clean_name.startswith(prefix):
                        # Obtener la parte numérica después del prefijo
                        suffix = clean_name[len(prefix):].strip(' -_')
                        if suffix:
                            index[f"{prefix}{suffix}"] = move
                            index[suffix] = move
        
        _logger.info(f"Índice construido con {len(index)} entradas")
        return index

    def _extract_invoice_ref_improved(self, filename):
        """Método mejorado para extraer la referencia de factura del nombre del archivo"""
        # Quitar extensión
        name = os.path.splitext(filename)[0]
        
        # Lista de patrones a buscar en orden de prioridad
        patterns = [
            # Patrones específicos con prefijos de factura
            r'FE\s*[-_]?\s*(\d+)',     # FE873631, FE-873631, FE_873631, FE 873631
            r'FV\s*[-_]?\s*(\d+)',     # FV873631, FV-873631, etc.
            r'NC\s*[-_]?\s*(\d+)',     # NC873631, NC-873631, etc.
            r'ND\s*[-_]?\s*(\d+)',     # ND873631, ND-873631, etc.
            r'FAC\s*[-_]?\s*(\d+)',    # FAC873631, FAC-873631, etc.
            r'FACT\s*[-_]?\s*(\d+)',   # FACT873631, FACT-873631, etc.
            
            # Buscar números largos (6+ dígitos) que podrían ser facturas
            r'(\d{6,})',               # Cualquier secuencia de 6 o más dígitos
            
            # Si hay un guión bajo, tomar lo que viene después del último
            r'_([^_]+)$',              # Todo después del último guión bajo
        ]
        
        for pattern in patterns:
            match = re.search(pattern, name, re.IGNORECASE)
            if match:
                if match.lastindex:  # Si hay un grupo capturado
                    result = match.group(1)
                else:
                    result = match.group(0)
                
                # Limpiar resultado
                result = result.upper().strip()
                _logger.debug(f"Patrón '{pattern}' encontró: {result} en {filename}")
                return result
        
        # Si no se encontró ningún patrón, intentar con el último segmento después de _
        parts = name.split('_')
        if len(parts) > 1:
            # Tomar el último segmento que podría ser la referencia
            last_part = parts[-1].strip()
            if last_part:
                _logger.debug(f"Usando último segmento: {last_part} de {filename}")
                return last_part.upper()
        
        # Como último recurso, devolver el nombre completo sin extensión
        _logger.debug(f"Sin patrón encontrado, usando nombre completo: {name}")
        return name.upper()

    def _find_invoice_improved(self, ref, index):
        """Método mejorado para buscar una factura en el índice"""
        if not ref:
            return None
        
        ref_upper = ref.upper().strip()
        
        # 1. Búsqueda directa exacta
        if ref_upper in index:
            _logger.debug(f"Encontrado por búsqueda exacta: {ref_upper}")
            return index[ref_upper]
        
        # 2. Búsqueda sin espacios ni guiones
        ref_clean = ref_upper.replace(' ', '').replace('-', '').replace('_', '')
        if ref_clean in index:
            _logger.debug(f"Encontrado por búsqueda limpia: {ref_clean}")
            return index[ref_clean]
        
        # 3. Buscar solo por números
        numbers = re.sub(r'[^0-9]', '', ref)
        if numbers:
            if numbers in index:
                _logger.debug(f"Encontrado por números: {numbers}")
                return index[numbers]
            
            # Probar con los últimos 6-8 dígitos
            if len(numbers) >= 6:
                for length in [6, 7, 8]:
                    if len(numbers) >= length:
                        last_digits = numbers[-length:]
                        if last_digits in index:
                            _logger.debug(f"Encontrado por últimos {length} dígitos: {last_digits}")
                            return index[last_digits]
        
        # 4. Si la referencia tiene un prefijo, intentar con y sin él
        for prefix in ['FE', 'FV', 'NC', 'ND', 'FAC', 'FACT']:
            if ref_upper.startswith(prefix):
                # Probar sin el prefijo
                without_prefix = ref_upper[len(prefix):].strip(' -_')
                if without_prefix in index:
                    _logger.debug(f"Encontrado sin prefijo {prefix}: {without_prefix}")
                    return index[without_prefix]
                
                # Probar con el prefijo más los números
                if numbers:
                    with_prefix = f"{prefix}{numbers}"
                    if with_prefix in index:
                        _logger.debug(f"Encontrado con prefijo {prefix}: {with_prefix}")
                        return index[with_prefix]
        
        # 5. Búsqueda parcial (substring)
        # Buscar si la referencia está contenida en alguna clave del índice
        for key, invoice in index.items():
            if ref_upper in key or key in ref_upper:
                _logger.debug(f"Encontrado por búsqueda parcial: {ref_upper} en {key}")
                return invoice
            
            # También probar con los números si existen
            if numbers and (numbers in key or key in numbers):
                _logger.debug(f"Encontrado por búsqueda parcial de números: {numbers} en {key}")
                return invoice
        
        # 6. Búsqueda fuzzy básica - buscar coincidencias de los últimos 4-5 dígitos
        if numbers and len(numbers) >= 4:
            last_4 = numbers[-4:]
            for key, invoice in index.items():
                if last_4 in key:
                    _logger.debug(f"Encontrado por últimos 4 dígitos: {last_4} en {key}")
                    return invoice
        
        _logger.warning(f"No se pudo encontrar factura para referencia: {ref_upper}")
        return None

    def action_debug_invoice_search(self):
        """Función de debug para verificar el mapeo de facturas"""
        self.ensure_one()
        
        # Construir el índice
        invoice_index = self._build_invoice_index()
        
        # Mostrar todas las claves del índice
        message = "<p><b>Debug - Índice de Facturas:</b></p><ul>"
        
        # Agrupar por factura para mostrar todas sus claves
        invoice_keys = defaultdict(list)
        for key, invoice in invoice_index.items():
            invoice_keys[invoice.name].append(key)
        
        for invoice_name, keys in sorted(invoice_keys.items()):
            message += f"<li><b>{invoice_name}:</b><ul>"
            for key in sorted(keys)[:10]:  # Mostrar máximo 10 claves por factura
                message += f"<li>{key}</li>"
            if len(keys) > 10:
                message += f"<li>... y {len(keys) - 10} claves más</li>"
            message += "</ul></li>"
        
        message += "</ul>"
        
        self.message_post(body=message, message_type='notification')
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Debug de Índice'),
                'message': _(f'Se generó el índice con {len(invoice_index)} entradas para {len(invoice_keys)} facturas'),
                'type': 'info',
                'sticky': False,
            }
        }
    
    def _build_invoice_index(self):
        """Construye un índice para búsqueda rápida de facturas"""
        index = {}
        for move in self.move_ids:
            for field in [move.name, move.ref, move.payment_reference]:
                if field:
                    index[field.upper()] = move
                    numbers = re.sub(r'[^0-9]', '', field)
                    if numbers:
                        index[numbers] = move
        return index
    
    def _extract_invoice_ref(self, filename):
        """Extrae la referencia de factura del nombre del archivo"""
        name = os.path.splitext(filename)[0]
        
        parts = name.split('_')
        if len(parts) >= 2:
            return parts[-1]
        
        patterns = [r'FE\d+', r'FV\d+', r'NC\d+', r'ND\d+', r'\d{6,}']
        for pattern in patterns:
            match = re.search(pattern, name, re.IGNORECASE)
            if match:
                return match.group().upper()
        
        return name
    
    def _find_invoice(self, ref, index):
        """Busca una factura en el índice"""
        ref_upper = ref.upper()
        
        # Búsqueda directa
        if ref_upper in index:
            return index[ref_upper]
        
        # Búsqueda por números
        numbers = re.sub(r'[^0-9]', '', ref)
        if numbers and numbers in index:
            return index[numbers]
        
        # Búsqueda parcial
        for key, invoice in index.items():
            if ref_upper in key or key in ref_upper:
                return invoice
        
        return None
    
    def _create_simple_attachment(self, invoice, file_data):
        """Crea un adjunto simple"""
        attachment = self.env['ir.attachment'].create({
            'name': file_data['name'],
            'type': 'binary',
            'datas': file_data['data'],
            'res_model': 'account.move',
            'res_id': invoice.id,
            'rips_export_id': self.id,
            'description': f"Soporte RIPS - Lote: {self.name}"
        })
        
        # Mensaje en el chatter
        invoice.message_post(
            body=f"<b>Soporte RIPS adjuntado:</b> {file_data['name']} (Lote: {self.name})",
            attachment_ids=[attachment.id]
        )
        
        return attachment
    
    def _create_zip_attachment(self, invoice, files):
        """Crea un ZIP con múltiples archivos"""
        # Crear ZIP en memoria
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            for file_data in files:
                zf.writestr(file_data['name'], base64.b64decode(file_data['data']))
        
        # Crear adjunto
        attachment = self.env['ir.attachment'].create({
            'name': f"Soportes_{invoice.name}_{self.name}.zip",
            'type': 'binary',
            'datas': base64.b64encode(zip_buffer.getvalue()).decode('utf-8'),
            'res_model': 'account.move',
            'res_id': invoice.id,
            'rips_export_id': self.id,
            'description': f"Soportes RIPS ({len(files)} archivos) - Lote: {self.name}"
        })
        
        # Mensaje en el chatter
        file_list = "<br/>".join([f"• {f['name']}" for f in files])
        invoice.message_post(
            body=f"""
                <p><b>Soportes RIPS adjuntados ({len(files)} archivos):</b></p>
                <div style="margin-left: 20px;">{file_list}</div>
                <p><small>Lote: {self.name}</small></p>
            """,
            attachment_ids=[attachment.id]
        )
        
        return attachment
    
    def _log_import_result(self, stats):
        """Registra el resultado de la importación"""
        # Mensaje en el chatter del lote
        message = f"""
            <p><b>Importación de Soportes Completada:</b></p>
            <ul>
                <li>Total archivos: {stats['total']}</li>
                <li>Archivos procesados: {stats['processed']}</li>
                <li>Facturas actualizadas: {len(stats['by_invoice'])}</li>
            """
        
        if stats['not_found']:
            message += f"<li>No asociados: {len(stats['not_found'])}</li>"
            
        message += "</ul>"
        
        if stats['not_found'] and len(stats['not_found']) <= 10:
            message += "<p><b>Archivos no asociados:</b></p><ul>"
            for item in stats['not_found']:
                message += f"<li>{item}</li>"
            message += "</ul>"
        
        self.message_post(body=message, message_type='notification')
    
    def action_view_support_attachments(self):
        """Ver todos los soportes adjuntados en este lote"""
        self.ensure_one()
        
        attachments = self.env['ir.attachment'].search([
            ('rips_export_id', '=', self.id),
        ])
        
        return {
            'name': _('Soportes del Lote %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'ir.attachment',
            'view_mode': 'kanban,tree,form',
            'domain': [('id', 'in', attachments.ids)],
            'context': {'create': False}
        }


# ============================================
# models/account_move.py - Extender facturas
# ============================================
class AccountMove(models.Model):
    _inherit = 'account.move'
    
    rips_support_count = fields.Integer(
        string='Soportes RIPS',
        compute='_compute_rips_support_count'
    )
    
    rips_file_count = fields.Integer(
        string='Archivos RIPS',
        compute='_compute_rips_support_count'
    )
    
    @api.depends('name')
    def _compute_rips_support_count(self):
        """
        Cuenta los adjuntos RIPS de las facturas.
        OPTIMIZADO: Una sola búsqueda para todas las facturas usando read_group.
        """
        # Inicializar contadores
        attachment_counts = {}

        if self.ids:
            # Una sola búsqueda para todas las facturas
            domain = [
                ('res_model', '=', 'account.move'),
                ('res_id', 'in', self.ids),
                ('rips_export_id', '!=', False)
            ]

            # Usar read_group para contar eficientemente
            groups = self.env['ir.attachment'].read_group(
                domain,
                ['res_id'],
                ['res_id']
            )

            # Construir diccionario de conteos
            attachment_counts = {
                group['res_id']: group['res_id_count']
                for group in groups
            }

        # Asignar contadores
        for move in self:
            count = attachment_counts.get(move.id, 0)
            move.rips_support_count = count
            move.rips_file_count = count
    
    def action_view_rips_attachments(self):
        """Ver todos los adjuntos RIPS de la factura"""
        self.ensure_one()
        
        attachments = self.env['ir.attachment'].search([
            ('res_model', '=', 'account.move'),
            ('res_id', '=', self.id),
            ('rips_export_id', '!=', False)
            ])
            
        return {
            'name': _('Documentos RIPS - %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'ir.attachment',
            'view_mode': 'kanban,tree,form',
            'domain': [('id', 'in', attachments.ids)],
            'context': {
                'create': False,
                'search_default_group_by_type': 1
            }
        }
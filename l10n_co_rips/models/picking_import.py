# -*- coding: utf-8 -*-
# Part of Softhealer Technologies.

from odoo import fields, models, api, _
from odoo.exceptions import UserError
import csv
import base64
import xlrd
from odoo.tools import ustr
import logging
import datetime
import os
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT
from odoo.tools import DEFAULT_SERVER_DATE_FORMAT

_logger = logging.getLogger(__name__)


class ImportLotSerialWizard(models.TransientModel):
    _name = "sh.import.lot.serial.picking"
    _description = "Asistente de importación de lote o número de serie"

    import_type = fields.Selection([
        ('csv', 'Archivo CSV'),
        ('excel', 'Archivo Excel')
    ], default="csv", string="Tipo de Archivo", required=True)
    file = fields.Binary(string="Archivo", required=True, attachment=True)
    file_name = fields.Char("Nombre del archivo")
    lot_type = fields.Selection([('lot', 'Lote'), ('serial', 'Número de Serie')],
                                default='lot', string='Tipo de Lote/Serie', required=True)
    is_create_lot = fields.Boolean("¿Crear Lote/Serie?")
    display_is_create_lot = fields.Boolean(
        'Mostrar Opción Crear Lote/Serie', default=False)
    
    # Campos para contrato y paciente general
    use_general_contract = fields.Boolean("Usar Contrato General", default=False, 
                                         help="Si está marcado, utilizará este contrato cuando no se especifique uno en el archivo o no se encuentre")
    general_contract_id = fields.Many2one('customer.contract', string='Contrato General',
                                         help="Contrato que se utilizará cuando no se especifique uno en el archivo o no se encuentre")
    use_general_patient = fields.Boolean("Usar Paciente General", default=False,
                                        help="Si está marcado, utilizará este paciente cuando no se especifique uno en el archivo o no se encuentre")
    general_patient_id = fields.Many2one('hms.patient', string='Paciente General',
                                        help="Paciente que se utilizará cuando no se especifique uno en el archivo o no se encuentre")
    
    # Campos para mostrar resultados y errores
    import_status = fields.Text(string="Resultado de la importación", readonly=True)
    error_log = fields.Text(string="Registro de errores", readonly=True)
    
    # Campo para seleccionar el tipo de picking si no viene en el contexto
    picking_type_id = fields.Many2one('stock.picking.type', string='Tipo de Operación',
                                     help="Tipo de operación para los pickings a crear")
    
    # Campo para ver los pickings creados
    created_picking_ids = fields.Many2many('stock.picking', string='Pickings Creados', readonly=True)

    # Opción para crear un archivo de depuración
    #create_debug_file = fields.Boolean(string="Crear archivo de depuración", default=False,
    #                                  help="Si está marcado, creará un archivo de texto con información de depuración")

    def validate_field_value(self, field_name, field_ttype, field_value, field_required, field_name_m2o):
        """ Validar valor de campo, dependiendo del tipo de campo y el valor proporcionado """
        self.ensure_one()

        try:
            checker = getattr(self, 'validate_field_' + field_ttype)
        except AttributeError:
            _logger.warning(
                field_ttype + ": Este tipo de campo no tiene método de validación")
            return {}
        else:
            return checker(field_name, field_ttype, field_value, field_required, field_name_m2o)

    def validate_field_many2many(self, field_name, field_ttype, field_value, field_required, field_name_m2o):
        self.ensure_one()
        if field_required and field_value in (None, ""):
            return {"error": " - " + field_name + " es requerido. "}
        else:
            name_relational_model = self.env['stock.move.line'].fields_get()[
                field_name]['relation']

            ids_list = []
            if field_value.strip() not in (None, ""):
                for x in field_value.split(','):
                    x = x.strip()
                    if x != '':
                        record = self.env[name_relational_model].sudo().search([
                            (field_name_m2o, '=', x)
                        ], limit=1)

                        if record:
                            ids_list.append(record.id)
                        else:
                            return {"error": " - " + x + " no encontrado. "}
                            break

            return {field_name: [(6, 0, ids_list)]}

    def validate_field_many2one(self, field_name, field_ttype, field_value, field_required, field_name_m2o):
        self.ensure_one()
        if field_required and field_value in (None, ""):
            return {"error": " - " + field_name + " es requerido. "}
        else:
            name_relational_model = self.env['stock.move.line'].fields_get()[
                field_name]['relation']
            record = self.env[name_relational_model].sudo().search([
                (field_name_m2o, '=', field_value)
            ], limit=1)
            return {field_name: record.id if record else False}

    def validate_field_text(self, field_name, field_ttype, field_value, field_required, field_name_m2o):
        self.ensure_one()
        if field_required and field_value in (None, ""):
            return {"error": " - " + field_name + " es requerido. "}
        else:
            return {field_name: field_value or False}

    def validate_field_integer(self, field_name, field_ttype, field_value, field_required, field_name_m2o):
        self.ensure_one()
        if field_required and field_value in (None, ""):
            return {"error": " - " + field_name + " es requerido. "}
        else:
            return {field_name: field_value or False}

    def validate_field_float(self, field_name, field_ttype, field_value, field_required, field_name_m2o):
        self.ensure_one()
        if field_required and field_value in (None, ""):
            return {"error": " - " + field_name + " es requerido. "}
        else:
            return {field_name: field_value or False}

    def validate_field_char(self, field_name, field_ttype, field_value, field_required, field_name_m2o):
        self.ensure_one()
        if field_required and field_value in (None, ""):
            return {"error": " - " + field_name + " es requerido. "}
        else:
            return {field_name: field_value or False}

    def validate_field_boolean(self, field_name, field_ttype, field_value, field_required, field_name_m2o):
        self.ensure_one()
        boolean_field_value = False
        if field_value.strip() == 'TRUE':
            boolean_field_value = True

        return {field_name: boolean_field_value}

    def validate_field_selection(self, field_name, field_ttype, field_value, field_required, field_name_m2o):
        self.ensure_one()
        if field_required and field_value in (None, ""):
            return {"error": " - " + field_name + " es requerido. "}

        # get selection field key and value.
        selection_key_value_list = self.env['stock.move.line'].sudo(
        )._fields[field_name].selection
        if selection_key_value_list and field_value not in (None, ""):
            for tuple_item in selection_key_value_list:
                if tuple_item[1] == field_value:
                    return {field_name: tuple_item[0] or False}

            return {"error": " - " + field_name + " valor dado " + str(field_value) + " no coincide para selección. "}

        # finaly return false
        if field_value in (None, ""):
            return {field_name: False}

        return {field_name: field_value or False}

    @api.onchange('use_general_contract')
    def onchange_use_general_contract(self):
        """Limpiar el contrato general cuando se desactiva la opción"""
        if not self.use_general_contract:
            self.general_contract_id = False

    @api.onchange('use_general_patient')
    def onchange_use_general_patient(self):
        """Limpiar el paciente general cuando se desactiva la opción"""
        if not self.use_general_patient:
            self.general_patient_id = False

    @api.onchange('general_contract_id')
    def onchange_general_contract_id(self):
        """Validar que el contrato general tenga un partner asociado"""
        if self.general_contract_id and not self.general_contract_id.partner_id:
            return {'warning': {
                'title': 'Advertencia',
                'message': 'El contrato seleccionado no tiene un cliente asociado.'
            }}

    def _show_result_view(self):
        """Muestra la vista de resultados después de la importación"""
        return {
            'name': 'Resultado de Importación',
            'type': 'ir.actions.act_window',
            'res_model': 'sh.import.lot.serial.picking',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
            'context': self._context,
        }

    @api.model
    def default_get(self, fields_list):
        """Valores por defecto al abrir el asistente"""
        res = super(ImportLotSerialWizard, self).default_get(fields_list)
        
        active_id = self.env.context.get('active_id')
        active_model = self.env.context.get('active_model')
        
        if active_model == 'stock.picking.type' and active_id:
            res['picking_type_id'] = active_id
        elif active_model == 'stock.move' and active_id:
            move_id = self.env['stock.move'].sudo().browse(active_id)
            if move_id.picking_type_id:
                res['picking_type_id'] = move_id.picking_type_id.id
                
                # Si es tipo entrante, mostrar opción de crear lote
                if move_id.picking_type_id.code == 'incoming':
                    res['display_is_create_lot'] = True
                
                # Si el picking ya tiene paciente, pre-seleccionarlo
                if move_id.picking_id and move_id.picking_id.patient_id:
                    res.update({
                        'use_general_patient': True,
                        'general_patient_id': move_id.picking_id.patient_id.id
                    })
                
                # Si el picking ya tiene contrato, pre-seleccionarlo
                if move_id.picking_id and move_id.picking_id.contract_id:
                    res.update({
                        'use_general_contract': True,
                        'general_contract_id': move_id.picking_id.contract_id.id
                    })
        
        return res

    def read_xls_book(self):
        """Lee el contenido de un archivo Excel"""
        book = xlrd.open_workbook(file_contents=base64.decodebytes(self.file))
        sheet = book.sheet_by_index(0)
        values_sheet = []
        for rowx, row in enumerate(map(sheet.row, range(sheet.nrows)), 1):
            values = []
            for colx, cell in enumerate(row, 1):
                if cell.ctype is xlrd.XL_CELL_NUMBER:
                    is_float = cell.value % 1 != 0.0
                    values.append(
                        str(cell.value) if is_float else str(int(cell.value)))
                elif cell.ctype is xlrd.XL_CELL_DATE:
                    is_datetime = cell.value % 1 != 0.0
                    dt = datetime.datetime(*xlrd.xldate.xldate_as_tuple(
                        cell.value, book.datemode))
                    values.append(
                        dt.strftime(DEFAULT_SERVER_DATETIME_FORMAT
                                    ) if is_datetime else dt.
                        strftime(DEFAULT_SERVER_DATE_FORMAT))
                elif cell.ctype is xlrd.XL_CELL_BOOLEAN:
                    values.append(u'True' if cell.value else u'False')
                elif cell.ctype is xlrd.XL_CELL_ERROR:
                    raise ValueError(
                        _("Valor de celda inválido en fila %(row)s, columna %(col)s: %(cell_value)s"
                          ) % {
                              'row':
                              rowx,
                              'col':
                              colx,
                              'cell_value':
                              xlrd.error_text_from_code.get(
                                  cell.value,
                                  _("código de error desconocido %s") % cell.value)
                        })
                else:
                    values.append(cell.value)
            values_sheet.append(values)
        return values_sheet
    
    def is_numeric(self, value):
        """Verificar si un valor es numérico"""
        if isinstance(value, (int, float)):
            return True
        if isinstance(value, str):
            try:
                float(value)
                return True
            except:
                return False
        return False
    
    def find_partner(self, value):
        """Buscar socio/cliente por ID, VAT_CO o VAT"""
        if not value:
            return False
            
        partner = False
        
        # Si es numérico, buscar por ID
        if self.is_numeric(value):
            try:
                partner_id = int(float(value))
                partner = self.env['res.partner'].sudo().browse(partner_id)
                if not partner.exists():
                    partner = False
            except (ValueError, TypeError):
                partner = False
        
        # Si no se encontró por ID, buscar por VAT_CO o VAT
        if not partner:
            domain = ['|', ('vat_co', '=', value), ('vat', '=', value)]
            partner = self.env['res.partner'].sudo().search(domain, limit=1)
        
        # Si no se encontró por ID ni VAT, buscar por nombre o referencia
        if not partner:
            domain = ['|', ('name', '=', value), ('ref', '=', value)]
            partner = self.env['res.partner'].sudo().search(domain, limit=1)
        
        return partner
    
    def find_patient(self, value):
        """Buscar paciente por ID o referencia"""
        if not value:
            return False
            
        patient = False
        
        # Si es numérico, buscar por ID
        if self.is_numeric(value):
            try:
                patient_id = int(float(value))
                patient = self.env['hms.patient'].sudo().browse(patient_id)
                if not patient.exists():
                    patient = False
            except (ValueError, TypeError):
                patient = False
        
        # Si no se encontró por ID, buscar por referencia
        if not patient:
            patient = self.env['hms.patient'].sudo().search([('reference', '=', value)], limit=1)
        
        # Si todavía no se encuentra, buscar por nombre
        if not patient:
            patient = self.env['hms.patient'].sudo().search([('name', '=', value)], limit=1)
        
        return patient
    
    def find_product(self, value):
        """Buscar producto por ID, código de barras o referencia interna"""
        if not value:
            return False
            
        product = False
        
        # Si es numérico, buscar por ID
        if self.is_numeric(value):
            try:
                product_id = int(float(value))
                product = self.env['product.product'].sudo().browse(product_id)
                if not product.exists():
                    product = False
            except (ValueError, TypeError):
                product = False
        
        # Si no se encontró por ID, buscar por código de barras o referencia interna
        if not product:
            product = self.env['product.product'].sudo().search(['|', ('barcode', '=', value), ('default_code', '=', value)], limit=1)
        
        # Si todavía no se encuentra, buscar por nombre
        if not product:
            product = self.env['product.product'].sudo().search([('name', '=', value)], limit=1)
        
        return product
    
    def find_lot(self, value, product_id):
        """Buscar lote por ID o nombre"""
        if not value:
            return False
            
        lot = False
        
        # Si es numérico, buscar por ID
        if self.is_numeric(value):
            try:
                lot_id = int(float(value))
                lot = self.env['stock.lot'].sudo().browse(lot_id)
                if not lot.exists() or (product_id and lot.product_id.id != product_id):
                    lot = False
            except (ValueError, TypeError):
                lot = False
        
        # Si no se encontró por ID, buscar por nombre
        if not lot:
            domain = [('name', '=', value)]
            if product_id:
                domain.append(('product_id', '=', product_id))
            lot = self.env['stock.lot'].sudo().search(domain, limit=1)
        
        return lot
    
    def find_contract(self, value, partner_id=False):
        """Buscar contrato por ID o nombre"""
        if not value:
            return False
            
        contract = False
        
        # Si es numérico, buscar por ID
        if self.is_numeric(value):
            try:
                contract_id = int(float(value))
                domain = [('id', '=', contract_id)]
                if partner_id:
                    domain.append(('partner_id', '=', partner_id))
                contract = self.env['customer.contract'].sudo().search(domain, limit=1)
                if not contract.exists():
                    contract = False
            except (ValueError, TypeError):
                contract = False
        
        # Si no se encontró por ID, buscar por nombre
        if not contract:
            domain = [('name', '=', value)]
            if partner_id:
                domain.append(('partner_id', '=', partner_id))
            contract = self.env['customer.contract'].sudo().search(domain, limit=1)
        
        return contract
    
    def find_location(self, value):
        """Buscar ubicación por ID o nombre"""
        if not value:
            return False
            
        location = False
        
        # Si es numérico, buscar por ID
        if self.is_numeric(value):
            try:
                location_id = int(float(value))
                location = self.env['stock.location'].sudo().browse(location_id)
                if not location.exists():
                    location = False
            except (ValueError, TypeError):
                location = False
        
        # Si no se encontró por ID, buscar por nombre
        if not location:
            location = self.env['stock.location'].sudo().search([('name', '=', value)], limit=1)
        
        # Si no se encontró, buscar por código/nombre completo
        if not location:
            location = self.env['stock.location'].sudo().search(['|', ('complete_name', '=', value), ('barcode', '=', value)], limit=1)
        
        return location

    def _create_debug_log(self, message, data=None):
        """
        Crea un archivo de log para depuración
        
        :param message: Mensaje descriptivo
        :param data: Datos para incluir en el log
        """
        
        log_dir = '/tmp/'  # Directorio donde se guardarán los logs
        try:
            # Crear directorio si no existe
            if not os.path.exists(log_dir):
                os.makedirs(log_dir)
                
            timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{log_dir}import_debug_{timestamp}.log"
            
            with open(filename, 'w') as f:
                f.write(f"=== DEBUG LOG: {message} ===\n")
                f.write(f"Timestamp: {datetime.datetime.now()}\n")
                f.write(f"User: {self.env.user.name}\n\n")
                
                if data:
                    f.write("DATA:\n")
                    if isinstance(data, dict):
                        for key, value in data.items():
                            f.write(f"{key}: {value}\n")
                    else:
                        f.write(str(data))
                
            _logger.info(f"Archivo de depuración creado: {filename}")
        except Exception as e:
            _logger.error(f"Error al crear archivo de depuración: {e}")

    def _create_pickings_from_groups(self, picking_groups, picking_type_id):
        """
        Crea pickings agrupados en base a los datos del archivo
        
        :param picking_groups: Diccionario con grupos de líneas
        :param picking_type_id: ID del tipo de operación
        :return: Pickings creados
        """
        # Asegurar que picking_type_id sea un entero
        if isinstance(picking_type_id, str) and picking_type_id.isdigit():
            picking_type_id = int(picking_type_id)
        elif not isinstance(picking_type_id, int):
            try:
                picking_type_id = int(float(picking_type_id))
            except (ValueError, TypeError):
                self._create_debug_log("Error tipo de picking", {
                    'picking_type_id': f"{picking_type_id} (tipo: {type(picking_type_id)})"
                })
                _logger.error(f"ID de tipo de operación inválido: {picking_type_id}")
                return self.env['stock.picking']
        
        picking_obj = self.env['stock.picking']
        move_obj = self.env['stock.move']
        created_pickings = self.env['stock.picking']
        
        # Verificar que el tipo de picking exista
        picking_type = self.env['stock.picking.type'].browse(picking_type_id)
        if not picking_type.exists():
            self._create_debug_log("Tipo de picking no encontrado", {
                'picking_type_id': picking_type_id
            })
            _logger.error(f"Tipo de operación con ID {picking_type_id} no encontrado")
            return created_pickings
        
        sequence = picking_type.sequence_id
        
        for group_key, lines in picking_groups.items():
            try:
                # Extraer valores de la clave de grupo con validación
                partner_id, patient_id, contract_id, location_id, location_dest_id, origin, group_picking_type_id = group_key
                
                # Verificar que todos los valores sean del tipo correcto
                if isinstance(group_picking_type_id, str) and group_picking_type_id.isdigit():
                    group_picking_type_id = int(group_picking_type_id)
                
                # Crear el albarán
                picking_vals = {
                    'picking_type_id': group_picking_type_id,
                    'location_id': location_id,
                    'location_dest_id': location_dest_id,
                    'partner_id': partner_id if partner_id else False,
                    'origin': origin if origin else False,
                    'scheduled_date': fields.Datetime.now(),
                }
                
                # Buscar tipo de operación para obtener el move_type
                pt = self.env['stock.picking.type'].browse(group_picking_type_id)
                if pt.exists() and hasattr(pt, 'move_type'):
                    picking_vals['move_type'] = pt.move_type
                
                # Añadir campos específicos si existen en el modelo
                if patient_id:
                    # Verificar si el modelo stock.picking tiene el campo patient_id
                    if 'patient_id' in self.env['stock.picking']._fields:
                        picking_vals['patient_id'] = patient_id
                
                if contract_id:
                    # Verificar si el modelo stock.picking tiene el campo contract_id
                    if 'contract_id' in self.env['stock.picking']._fields:
                        picking_vals['contract_id'] = contract_id
                        
                        # Buscar método de pago del contrato si existe
                        contract = self.env['customer.contract'].browse(contract_id)
                        if contract.exists() and hasattr(contract, 'payment_method'):
                            if 'payment_method_id' in self.env['stock.picking']._fields:
                                picking_vals['payment_method_id'] = contract.payment_method.id if contract.payment_method else False
                
                # Crear el picking
                self._create_debug_log("Creando picking", picking_vals)
                picking = picking_obj.create(picking_vals)
                created_pickings |= picking
                
                # Crear movimientos para cada línea
                for line in lines:
                    # Verificar que todos los valores obligatorios existan
                    if not line.get('product_id') or not line.get('uom_id') or not line.get('location_id') or not line.get('location_dest_id'):
                        self._create_debug_log("Línea incompleta", line)
                        continue
                    
                    move_vals = {
                        'name': line.get('product_name', 'Producto'),
                        'product_id': line['product_id'],
                        'product_uom_qty': line['quantity'],
                        'product_uom': line['uom_id'],
                        'picking_id': picking.id,
                        'restrict_lot_id': line['lot_name'].id if line.get('lot_name') else False,
                        'picking_type_id': group_picking_type_id,
                        'location_id': line['location_id'],
                        'location_dest_id': line['location_dest_id'],
                        'state': 'draft',
                    }
                    
                    if line.get('partner_id'):
                        move_vals['partner_id'] = line['partner_id']
                    
                    # Crear el movimiento
                    self._create_debug_log("Creando movimiento", move_vals)
                    move = move_obj.create(move_vals)

                try:
                    picking.action_confirm()
                except Exception as e:
                    self._create_debug_log("Error al confirmar picking", {
                        'picking_id': picking.id,
                        'error': str(e)
                    })
                    _logger.error(f"Error al confirmar picking {picking.id}: {e}")
            
            except Exception as e:
                self._create_debug_log("Error al procesar grupo", {
                    'group_key': group_key,
                    'error': str(e)
                })
                _logger.error(f"Error al procesar grupo {group_key}: {e}")
                continue
        
        return created_pickings

    def import_lot_serial_apply(self):
        """Importación de datos desde Excel/CSV para crear pickings agrupados con sus líneas de productos"""
        if not self.file:
            self.write({
                'import_status': 'Error: No se ha adjuntado ningún archivo',
                'error_log': 'Por favor adjunte un archivo para importar.'
            })
            return self._show_result_view()
        
        # Obtener el tipo de picking del contexto o del campo seleccionado
        picking_type_id = self.picking_type_id.id if self.picking_type_id else False
        if not picking_type_id:
            active_id = self.env.context.get('active_id')
            active_model = self.env.context.get('active_model')
            
            if active_model == 'stock.picking.type':
                picking_type_id = active_id
            elif active_model == 'stock.move' and active_id:
                move = self.env['stock.move'].browse(active_id)
                picking_type_id = move.picking_type_id.id
        
        # Asegurar que picking_type_id sea un entero
        if isinstance(picking_type_id, str) and picking_type_id.isdigit():
            picking_type_id = int(picking_type_id)
        
        if not picking_type_id or not isinstance(picking_type_id, int):
            self.write({
                'import_status': 'Error: No se ha definido un tipo de operación',
                'error_log': 'No se pudo determinar el tipo de operación para crear los pickings.'
            })
            return self._show_result_view()
        
        # Registrar información inicial
        self._create_debug_log("Inicio de importación", {
            'picking_type_id': picking_type_id,
            'import_type': self.import_type,
            'lot_type': self.lot_type,
            'is_create_lot': self.is_create_lot
        })
        
        counter = 1
        skipped_line_no = {}
        picking_groups = {}  # Diccionario para agrupar líneas por campos clave
        
        try:
            # Leer archivo según el tipo seleccionado
            values = []
            if self.import_type == 'csv':
                file = str(base64.decodebytes(self.file).decode('utf-8'))
                values = csv.reader(file.splitlines())
            elif self.import_type == 'excel':
                values = self.read_xls_book()
            
            skip_header = True
            
            # Procesar cada línea del archivo
            for row in values:
                try:
                    if skip_header:
                        skip_header = False
                        counter += 1
                        continue
                    
                    # Verificar longitud mínima de la fila
                    if len(row) < 9:  # Asumiendo 9 columnas mínimas
                        skipped_line_no[str(counter)] = " - Número insuficiente de columnas. Se requieren al menos 9 columnas."
                        counter += 1
                        continue
                    
                    # Extraer datos de las columnas
                    location_src_value = row[0] if len(row) > 0 else ''
                    location_dest_value = row[1] if len(row) > 1 else ''
                    product_value = row[2] if len(row) > 2 else ''
                    quantity_value = row[3] if len(row) > 3 else '0'
                    uom_value = row[4] if len(row) > 4 else ''
                    partner_value = row[5] if len(row) > 5 else ''
                    patient_value = row[6] if len(row) > 6 else ''
                    origin_value = row[7] if len(row) > 7 else ''
                    lot_value = row[8] if len(row) > 8 else ''
                    
                    # Registrar datos de la fila para depuración
                    self._create_debug_log(f"Procesando fila {counter}", {
                        'location_src': location_src_value,
                        'location_dest': location_dest_value,
                        'product': product_value,
                        'quantity': quantity_value,
                        'uom': uom_value,
                        'partner': partner_value,
                        'patient': patient_value,
                        'origin': origin_value,
                        'lot': lot_value
                    })
                    
                    # Buscar entidades correspondientes
                    location_src = self.find_location(location_src_value)
                    location_dest = self.find_location(location_dest_value)
                    product = self.find_product(product_value)
                    partner = self.find_partner(partner_value)
                    patient = self.find_patient(patient_value) if patient_value else (self.general_patient_id if self.use_general_patient else False)
                    lot_value = self.find_lot(lot_value, product.id) if lot_value else False
                    # Validar valores obligatorios
                    if not location_src:
                        skipped_line_no[str(counter)] = f" - Ubicación de origen '{location_src_value}' no encontrada."
                        counter += 1
                        continue
                    
                    if not location_dest:
                        skipped_line_no[str(counter)] = f" - Ubicación de destino '{location_dest_value}' no encontrada."
                        counter += 1
                        continue
                    
                    if not product:
                        skipped_line_no[str(counter)] = f" - Producto '{product_value}' no encontrado."
                        counter += 1
                        continue
                    
                    # Para partners, usar el general si está configurado
                    if not partner and self.use_general_contract and self.general_contract_id and self.general_contract_id.partner_id:
                        partner = self.general_contract_id.partner_id
                    
                    # Buscar contrato
                    contract = False
                    if partner:
                        domain = [('partner_id', '=', partner.id)]
                        if patient:
                            # Verificar si existe la relación entre contrato y paciente
                            contract_field_patient = self.env['ir.model.fields'].sudo().search([
                                ('model', '=', 'customer.contract'),
                                ('name', '=', 'patient_id')
                            ], limit=1)
                            
                            if contract_field_patient:
                                domain.append(('patient_id', '=', patient.id))
                        
                        contract = self.env['customer.contract'].sudo().search(domain, limit=1)
                    
                    if not contract and self.use_general_contract and self.general_contract_id:
                        contract = self.general_contract_id
                    
                    # Validar cantidad
                    try:
                        quantity = float(quantity_value)
                        if quantity <= 0:
                            skipped_line_no[str(counter)] = " - La cantidad debe ser mayor que cero."
                            counter += 1
                            continue
                        
                        # Validar para números de serie
                        if self.lot_type == 'serial' and product.tracking == 'serial' and quantity != 1:
                            skipped_line_no[str(counter)] = " - La cantidad debe ser 1 para productos con seguimiento por número de serie."
                            counter += 1
                            continue
                    except ValueError:
                        skipped_line_no[str(counter)] = f" - Valor de cantidad inválido: '{quantity_value}'."
                        counter += 1
                        continue
                    
                    # Verificar el tracking del producto según el tipo seleccionado
                    if self.lot_type == 'lot' and product.tracking != 'lot':
                        skipped_line_no[str(counter)] = f" - El producto '{product.name}' no está configurado para seguimiento por lote."
                        counter += 1
                        continue
                    elif self.lot_type == 'serial' and product.tracking != 'serial':
                        skipped_line_no[str(counter)] = f" - El producto '{product.name}' no está configurado para seguimiento por número de serie."
                        counter += 1
                        continue
                    
                    # Buscar UdM si se especificó
                    uom = False
                    if uom_value:
                        if self.is_numeric(uom_value):
                            uom = self.env['uom.uom'].sudo().browse(int(float(uom_value)))
                            if not uom.exists():
                                uom = False
                        
                        if not uom:
                            uom = self.env['uom.uom'].sudo().search([('name', '=', uom_value)], limit=1)
                    
                    if not uom:
                        uom = product.uom_id
                    
                    # Validar compatibilidad de UdM
                    if uom.category_id != product.uom_id.category_id:
                        skipped_line_no[str(counter)] = f" - La unidad de medida '{uom.name}' no es compatible con el producto '{product.name}'."
                        counter += 1
                        continue
                    
                    # Crear la clave para agrupar con verificación de tipos
                    partner_id = partner.id if partner and hasattr(partner, 'id') else 0
                    patient_id = patient.id if patient and hasattr(patient, 'id') else 0
                    contract_id = contract.id if contract and hasattr(contract, 'id') else 0
                    loc_src_id = location_src.id if location_src and hasattr(location_src, 'id') else 0
                    loc_dest_id = location_dest.id if location_dest and hasattr(location_dest, 'id') else 0
                    origin_str = str(origin_value or '')
                    pt_id = int(picking_type_id) if isinstance(picking_type_id, (int, float)) else 0
                    
                    # Registrar valores de la clave para depuración
                    self._create_debug_log("Valores para crear group_key", {
                        'partner_id': f"{partner_id} (tipo: {type(partner_id)})",
                        'patient_id': f"{patient_id} (tipo: {type(patient_id)})",
                        'contract_id': f"{contract_id} (tipo: {type(contract_id)})",
                        'loc_src_id': f"{loc_src_id} (tipo: {type(loc_src_id)})",
                        'loc_dest_id': f"{loc_dest_id} (tipo: {type(loc_dest_id)})",
                        'origin_str': f"{origin_str} (tipo: {type(origin_str)})",
                        'pt_id': f"{pt_id} (tipo: {type(pt_id)})"
                    })
                    _logger.error("Valores para crear group_key: {partner_id}, {patient_id}, {contract_id}, {loc_src_id}, {loc_dest_id}, {origin_str}, {pt_id}")
                    group_key = (partner_id, patient_id, contract_id, loc_src_id, loc_dest_id, origin_str, pt_id)
                    
                    # Agregar la línea al grupo correspondiente
                    if group_key not in picking_groups:
                        picking_groups[group_key] = []
                    
                    # Guardar los datos de la línea
                    line_data = {
                        'product_id': product.id if product else False,
                        'product_name': product.name if product else '',
                        'quantity': quantity,
                        'uom_id': uom.id if uom else product.uom_id.id,
                        'lot_name': lot_value,
                        'partner_id': partner.id if partner else False,
                        'patient_id': patient.id if patient else False,
                        'contract_id': contract.id if contract else False,
                        'location_id': location_src.id if location_src else False,
                        'location_dest_id': location_dest.id if location_dest else False,
                        'origin': origin_value,
                        'row_index': counter
                    }
                    
                    picking_groups[group_key].append(line_data)
                    counter += 1
                    
                except Exception as e:
                    self._create_debug_log(f"Error en fila {counter}", {
                        'error': str(e),
                        'row': row if len(row) <= 10 else row[:10]
                    })
                    skipped_line_no[str(counter)] = f" - Error: {ustr(e)}"
                    counter += 1
                    continue
            
            # Registrar información de grupos creados
            self._create_debug_log("Grupos creados", {
                'num_grupos': len(picking_groups),
                'grupos': list(picking_groups.keys())
            })
            
            # Procesar los grupos y crear los pickings
            created_pickings = self._create_pickings_from_groups(picking_groups, picking_type_id)
            
            # Registrar pickings creados
            self._create_debug_log("Pickings creados", {
                'num_pickings': len(created_pickings),
                'picking_ids': created_pickings.ids
            })
            
            # Actualizar resultado en el wizard
            if created_pickings:
                self.write({
                    'import_status': f'{len(created_pickings)} Pickings creados correctamente',
                    'error_log': '\n'.join([f"Línea {k}: {v}" for k, v in skipped_line_no.items()]) if skipped_line_no else "",
                    'created_picking_ids': [(6, 0, created_pickings.ids)]
                })
            else:
                self.write({
                    'import_status': 'No se crearon pickings',
                    'error_log': '\n'.join([f"Línea {k}: {v}" for k, v in skipped_line_no.items()]) if skipped_line_no else "No se pudo procesar ninguna línea del archivo."
                })
            
            return self._show_result_view()
            
        except Exception as e:
            self._create_debug_log("Error general", {
                'error': str(e),
                'traceback': e.__traceback__
            })
            self.write({
                'import_status': 'Error en la importación',
                'error_log': f'Lo sentimos, ocurrió un error durante el procesamiento:\n{ustr(e)}'
            })
            return self._show_result_view()
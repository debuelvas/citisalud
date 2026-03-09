import logging
import psycopg2
from typing import List, Dict, Any, Optional, Tuple, Union
from datetime import datetime
from contextlib import contextmanager
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from psycopg2.extras import execute_values, execute_batch
from psycopg2.sql import SQL, Identifier, Literal, Composed

_logger = logging.getLogger(__name__)

class BulkOperations:
    """
    Clase que proporciona operaciones CRUD en bloque optimizadas,
    trabajando directamente con la base de datos para máximo rendimiento.
    """
    
    def __init__(self, env, notification_manager=None):
        self.env = env
        self.cr = env.cr
        
        # Integración con NotificationManager si está disponible
        self.notification_manager = notification_manager
        
        # Para rastrear resultados si no hay notification_manager
        self.last_operation_results = {
            'success': 0,
            'error': 0,
            'total': 0,
            'errors': []
        }
    
    @contextmanager
    def _savepoint(self):
        """
        Genera un savepoint para operaciones que podrían necesitar rollback.
        Útil para operaciones en bloque donde algunos registros podrían fallar.
        
        Example:
            with self._savepoint():
                # Operaciones que podrían necesitar rollback
        """
        savepoint_name = f"bulk_op_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        self.cr.execute('SAVEPOINT "%s"' % savepoint_name)
        try:
            yield
        except Exception as e:
            self.cr.execute('ROLLBACK TO SAVEPOINT "%s"' % savepoint_name)
            _logger.exception("Rollback a savepoint debido a error: %s", str(e))
            raise
        finally:
            self.cr.execute('RELEASE SAVEPOINT "%s"' % savepoint_name)
    
    def _notify_result(self, operation_type, success_count, error_count, errors=None):
        """
        Notifica el resultado de una operación en bloque.
        
        Args:
            operation_type: Tipo de operación ('crear', 'actualizar', 'eliminar')
            success_count: Número de operaciones exitosas
            error_count: Número de operaciones fallidas
            errors: Lista de errores específicos
        """
        # Almacenar resultados
        self.last_operation_results = {
            'success': success_count,
            'error': error_count,
            'total': success_count + error_count,
            'errors': errors or []
        }
        
        # Si hay notification_manager, usar ese
        if self.notification_manager:
            for i, error in enumerate(errors or []):
                if i < 10:  # Limitar la cantidad de errores notificados
                    self.notification_manager.add_message(
                        f"Error en {operation_type}: {error}",
                        'danger'
                    )
            
            # Agregar resumen final
            self.notification_manager.add_message(
                f"Operación {operation_type}: {success_count} exitosos, {error_count} errores",
                'success' if error_count == 0 else 'warning'
            )
        else:
            # Log simple si no hay notification_manager
            if error_count:
                _logger.warning(
                    "Operación %s: %s exitosos, %s errores",
                    operation_type, success_count, error_count
                )
            else:
                _logger.info(
                    "Operación %s: %s registros procesados correctamente",
                    operation_type, success_count
                )
    
    def bulk_create(self, model_name: str, values_list: List[Dict], 
                   chunk_size: int = 1000, return_ids: bool = True,
                   skip_constraints: bool = False) -> Dict:
        """
        Crea múltiples registros en un solo lote usando SQL directo
        para máximo rendimiento.
        
        Args:
            model_name: Nombre del modelo (ej: 'res.partner')
            values_list: Lista de diccionarios con los valores a insertar
            chunk_size: Tamaño del lote para procesamiento por chunks
            return_ids: Si se deben devolver los IDs generados
            skip_constraints: Si se deben saltar restricciones (PELIGROSO)
            
        Returns:
            Diccionario con resultados de la operación
            
        Example:
            bulk_ops.bulk_create(
                'res.partner',
                [
                    {'name': 'Partner 1', 'email': 'p1@example.com'},
                    {'name': 'Partner 2', 'email': 'p2@example.com'},
                ]
            )
        """
        if not values_list:
            return {'ids': [], 'success_count': 0, 'error_count': 0, 'total': 0}
            
        start_time = datetime.now()
        model = self.env[model_name]
        table_name = model._table
        
        # Procesar valores y extraer columnas
        all_columns = set()
        for values in values_list:
            all_columns.update(values.keys())
            
        # Filtrar columnas que no existen en la tabla
        valid_columns = []
        for column in all_columns:
            if column in model._fields:
                valid_columns.append(column)
                
        # Preparar datos para inserción
        prepared_data = []
        for values in values_list:
            row = []
            for column in valid_columns:
                row.append(values.get(column, None))
            prepared_data.append(tuple(row))
            
        # Construir consulta
        columns_str = ', '.join([f'"{col}"' for col in valid_columns])
        placeholders = ', '.join(['%s' for _ in valid_columns])
        
        if return_ids:
            query = f'INSERT INTO "{table_name}" ({columns_str}) VALUES ({placeholders}) RETURNING id'
        else:
            query = f'INSERT INTO "{table_name}" ({columns_str}) VALUES ({placeholders})'
            
        # Si se debe saltar restricciones
        if skip_constraints:
            if model._name == model._name_with_defaults:  # Es un modelo real, no abstracto
                self.cr.execute("SET CONSTRAINTS ALL DEFERRED")
                
        success_count = 0
        error_count = 0
        errors = []
        created_ids = []
        
        # Procesar en chunks para mejor rendimiento
        chunks = [prepared_data[i:i+chunk_size] for i in range(0, len(prepared_data), chunk_size)]
        
        try:
            for chunk in chunks:
                with self._savepoint():
                    if return_ids:
                        # Si necesitamos IDs, ejecutar una a una para obtenerlos
                        for row in chunk:
                            try:
                                self.cr.execute(query, row)
                                result = self.cr.fetchone()
                                if result:
                                    created_ids.append(result[0])
                                success_count += 1
                            except Exception as e:
                                error_count += 1
                                errors.append(str(e))
                    else:
                        # Si no necesitamos IDs, usar execute_values para mejor rendimiento
                        try:
                            execute_values(self.cr, query, chunk)
                            success_count += len(chunk)
                        except Exception as e:
                            error_count += len(chunk)
                            errors.append(str(e))
        finally:
            # Restaurar modo de restricciones
            if skip_constraints:
                self.cr.execute("SET CONSTRAINTS ALL IMMEDIATE")
                
        # Notificar resultados
        self._notify_result('creación', success_count, error_count, errors)
        
        execution_time = (datetime.now() - start_time).total_seconds()
        
        return {
            'ids': created_ids,
            'success_count': success_count,
            'error_count': error_count,
            'total': len(values_list),
            'execution_time': execution_time,
            'errors': errors[:10] if errors else []  # Limitar la cantidad de errores devueltos
        }
    
    def bulk_update(self, model_name: str, ids: List[int], values: Dict,
                   chunk_size: int = 1000, skip_constraints: bool = False) -> Dict:
        """
        Actualiza múltiples registros en un solo lote usando SQL directo.
        
        Args:
            model_name: Nombre del modelo
            ids: Lista de IDs a actualizar
            values: Diccionario con valores para actualizar
            chunk_size: Tamaño del lote para procesamiento
            skip_constraints: Si se deben saltar restricciones (PELIGROSO)
            
        Returns:
            Diccionario con resultados de la operación
            
        Example:
            bulk_ops.bulk_update(
                'res.partner',
                [1, 2, 3],
                {'is_company': True, 'category_id': 5}
            )
        """
        if not ids or not values:
            return {'success_count': 0, 'error_count': 0, 'total': 0}
            
        start_time = datetime.now()
        model = self.env[model_name]
        table_name = model._table
        
        # Filtrar valores válidos para actualizar
        valid_values = {}
        valid_columns = []
        for column, value in values.items():
            if column in model._fields:
                valid_values[column] = value
                valid_columns.append(column)
                
        if not valid_columns:
            return {'success_count': 0, 'error_count': 0, 'total': 0}
            
        # Construir consulta SET
        set_clause = ', '.join([f'"{col}" = %s' for col in valid_columns])
        values_list = [valid_values[col] for col in valid_columns]
        
        success_count = 0
        error_count = 0
        errors = []
        
        # Si se debe saltar restricciones
        if skip_constraints:
            if model._name == model._name_with_defaults:  # Es un modelo real, no abstracto
                self.cr.execute("SET CONSTRAINTS ALL DEFERRED")
        
        # Procesar en chunks para mejor rendimiento
        chunks = [ids[i:i+chunk_size] for i in range(0, len(ids), chunk_size)]
        
        try:
            for chunk in chunks:
                with self._savepoint():
                    try:
                        placeholders = ','.join(['%s'] * len(chunk))
                        query = f'''
                            UPDATE "{table_name}"
                            SET {set_clause}
                            WHERE id IN ({placeholders})
                        '''
                        
                        # Parámetros: primero los valores del SET, luego los IDs del WHERE
                        params = values_list + chunk
                        
                        self.cr.execute(query, params)
                        affected = self.cr.rowcount
                        success_count += affected
                        
                        # Si se actualizaron menos registros que los esperados
                        if affected < len(chunk):
                            missing = len(chunk) - affected
                            error_count += missing
                            errors.append(f"No se encontraron {missing} registros")
                            
                    except Exception as e:
                        error_count += len(chunk)
                        errors.append(str(e))
        finally:
            # Restaurar modo de restricciones
            if skip_constraints:
                self.cr.execute("SET CONSTRAINTS ALL IMMEDIATE")
                
        # Notificar resultados
        self._notify_result('actualización', success_count, error_count, errors)
        
        execution_time = (datetime.now() - start_time).total_seconds()
        
        return {
            'success_count': success_count,
            'error_count': error_count,
            'total': len(ids),
            'execution_time': execution_time,
            'errors': errors[:10] if errors else []
        }
    
    def bulk_delete(self, model_name: str, ids: List[int], chunk_size: int = 1000,
                   skip_constraints: bool = False) -> Dict:
        """
        Elimina múltiples registros en un solo lote usando SQL directo.
        
        Args:
            model_name: Nombre del modelo
            ids: Lista de IDs a eliminar
            chunk_size: Tamaño del lote para procesamiento
            skip_constraints: Si se deben saltar restricciones (PELIGROSO)
            
        Returns:
            Diccionario con resultados de la operación
            
        Example:
            bulk_ops.bulk_delete('res.partner', [1, 2, 3])
        """
        if not ids:
            return {'success_count': 0, 'error_count': 0, 'total': 0}
            
        start_time = datetime.now()
        model = self.env[model_name]
        table_name = model._table
        
        success_count = 0
        error_count = 0
        errors = []
        
        # Si se debe saltar restricciones
        if skip_constraints:
            if model._name == model._name_with_defaults:  # Es un modelo real, no abstracto
                self.cr.execute("SET CONSTRAINTS ALL DEFERRED")
        
        # Procesar en chunks para mejor rendimiento
        chunks = [ids[i:i+chunk_size] for i in range(0, len(ids), chunk_size)]
        
        try:
            for chunk in chunks:
                with self._savepoint():
                    try:
                        placeholders = ','.join(['%s'] * len(chunk))
                        query = f'DELETE FROM "{table_name}" WHERE id IN ({placeholders})'
                        
                        self.cr.execute(query, chunk)
                        affected = self.cr.rowcount
                        success_count += affected
                        
                        # Si se eliminaron menos registros que los esperados
                        if affected < len(chunk):
                            missing = len(chunk) - affected
                            error_count += missing
                            errors.append(f"No se encontraron {missing} registros")
                            
                    except Exception as e:
                        error_count += len(chunk)
                        errors.append(str(e))
        finally:
            # Restaurar modo de restricciones
            if skip_constraints:
                self.cr.execute("SET CONSTRAINTS ALL IMMEDIATE")
                
        # Notificar resultados
        self._notify_result('eliminación', success_count, error_count, errors)
        
        execution_time = (datetime.now() - start_time).total_seconds()
        
        return {
            'success_count': success_count,
            'error_count': error_count,
            'total': len(ids),
            'execution_time': execution_time,
            'errors': errors[:10] if errors else []
        }
    
    def bulk_read(self, model_name: str, ids: List[int], fields: Optional[List[str]] = None,
                chunk_size: int = 1000) -> Dict:
        """
        Lee múltiples registros en un solo lote usando SQL directo.
        
        Args:
            model_name: Nombre del modelo
            ids: Lista de IDs a leer
            fields: Lista de campos a leer (None para todos)
            chunk_size: Tamaño del lote para procesamiento
            
        Returns:
            Diccionario con resultados y datos leídos
            
        Example:
            bulk_ops.bulk_read(
                'res.partner',
                [1, 2, 3],
                ['name', 'email', 'phone']
            )
        """
        if not ids:
            return {'records': [], 'count': 0}
            
        start_time = datetime.now()
        model = self.env[model_name]
        table_name = model._table
        
        # Determinar campos a leer
        if not fields:
            fields = list(model._fields.keys())
            
        # Filtrar campos válidos
        valid_fields = []
        for field in fields:
            if field in model._fields:
                valid_fields.append(field)
                
        if not valid_fields:
            valid_fields = ['id']  # Al menos leer el ID
            
        # Construir consulta SELECT
        fields_str = ', '.join([f'"{field}"' for field in valid_fields])
        
        all_records = []
        chunks = [ids[i:i+chunk_size] for i in range(0, len(ids), chunk_size)]
        
        for chunk in chunks:
            placeholders = ','.join(['%s'] * len(chunk))
            query = f'SELECT {fields_str} FROM "{table_name}" WHERE id IN ({placeholders})'
            
            self.cr.execute(query, chunk)
            records = self.cr.dictfetchall()
            all_records.extend(records)
            
        execution_time = (datetime.now() - start_time).total_seconds()
        
        return {
            'records': all_records,
            'count': len(all_records),
            'total_requested': len(ids),
            'execution_time': execution_time
        }
    
    def bulk_create_with_commands(self, model_name: str, values_list: List[Dict]) -> Dict:
        """
        Crea múltiples registros usando Command.create de Odoo, útil
        cuando se necesita mantener la lógica de negocio.
        
        Args:
            model_name: Nombre del modelo
            values_list: Lista de diccionarios con valores
            
        Returns:
            Diccionario con resultados
            
        Example:
            bulk_ops.bulk_create_with_commands(
                'res.partner',
                [
                    {'name': 'Partner 1', 'category_id': [(4, 1), (4, 2)]},
                    {'name': 'Partner 2', 'category_id': [(6, 0, [3, 4, 5])]},
                ]
            )
        """
        from odoo import Command
        
        if not values_list:
            return {'ids': [], 'success_count': 0, 'error_count': 0, 'total': 0}
            
        start_time = datetime.now()
        model = self.env[model_name]
        
        success_count = 0
        error_count = 0
        errors = []
        created_ids = []
        
        # Procesamiento individual para mayor control
        for values in values_list:
            with self._savepoint():
                try:
                    record = model.create(values)
                    created_ids.append(record.id)
                    success_count += 1
                except Exception as e:
                    error_count += 1
                    errors.append(str(e))
                    
        # Notificar resultados
        self._notify_result('creación con comandos', success_count, error_count, errors)
        
        execution_time = (datetime.now() - start_time).total_seconds()
        
        return {
            'ids': created_ids,
            'success_count': success_count,
            'error_count': error_count,
            'total': len(values_list),
            'execution_time': execution_time,
            'errors': errors[:10] if errors else []
        }
    
    def bulk_update_with_commands(self, model_name: str, ids: List[int], values: Dict) -> Dict:
        """
        Actualiza múltiples registros usando la API de Odoo, útil
        cuando se necesita mantener la lógica de negocio.
        
        Args:
            model_name: Nombre del modelo
            ids: Lista de IDs a actualizar
            values: Diccionario con valores para actualizar
            
        Returns:
            Diccionario con resultados
            
        Example:
            bulk_ops.bulk_update_with_commands(
                'res.partner',
                [1, 2, 3],
                {'category_id': [(4, 5)]}  # Agregar categoría 5
            )
        """
        if not ids or not values:
            return {'success_count': 0, 'error_count': 0, 'total': 0}
            
        start_time = datetime.now()
        model = self.env[model_name]
        
        success_count = 0
        error_count = 0
        errors = []
        
        # Obtener todos los registros en un lote
        records = model.browse(ids)
        
        # Actualizar individualmente
        for record in records:
            with self._savepoint():
                try:
                    record.write(values)
                    success_count += 1
                except Exception as e:
                    error_count += 1
                    errors.append(f"ID {record.id}: {str(e)}")
                    
        # Notificar resultados
        self._notify_result('actualización con comandos', success_count, error_count, errors)
        
        execution_time = (datetime.now() - start_time).total_seconds()
        
        return {
            'success_count': success_count,
            'error_count': error_count,
            'total': len(ids),
            'execution_time': execution_time,
            'errors': errors[:10] if errors else []
        }
    
    @contextmanager
    def bulk_transaction(self):
        """
        Contexto para operaciones masivas que deben ser una sola transacción.
        Si cualquier operación falla, se hace rollback de todas.
        
        Example:
            with bulk_ops.bulk_transaction():
                result1 = bulk_ops.bulk_create(...)
                result2 = bulk_ops.bulk_update(...)
                # Si cualquiera falla, se hace rollback de ambas
        """
        savepoint_name = f"bulk_transaction_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        self.cr.execute('SAVEPOINT "%s"' % savepoint_name)
        try:
            yield
        except Exception as e:
            self.cr.execute('ROLLBACK TO SAVEPOINT "%s"' % savepoint_name)
            _logger.exception("Rollback de transacción masiva: %s", str(e))
            raise
        finally:
            self.cr.execute('RELEASE SAVEPOINT "%s"' % savepoint_name)
    
    def execute_raw_sql(self, query: str, params: Optional[List] = None, 
                      fetch: bool = True) -> Dict:
        """
        Ejecuta SQL personalizado directamente contra la base de datos.
        Para usuarios avanzados que necesitan máximo control y rendimiento.
        
        Args:
            query: Consulta SQL
            params: Parámetros para la consulta
            fetch: Si se deben recuperar resultados
            
        Returns:
            Diccionario con resultados
            
        Example:
            bulk_ops.execute_raw_sql(
                "UPDATE res_partner SET active=false WHERE create_date < %s",
                ['2020-01-01']
            )
        """
        start_time = datetime.now()
        
        try:
            self.cr.execute(query, params or [])
            
            result = {
                'success': True,
                'rowcount': self.cr.rowcount,
                'execution_time': (datetime.now() - start_time).total_seconds()
            }
            
            if fetch:
                result['records'] = self.cr.dictfetchall()
                result['count'] = len(result['records'])
                
            return result
            
        except Exception as e:
            error_msg = str(e)
            _logger.error("Error en consulta SQL: %s\nQuery: %s\nParams: %s", 
                         error_msg, query, params)
            
            return {
                'success': False,
                'error': error_msg,
                'execution_time': (datetime.now() - start_time).total_seconds()
            }


# Mixin para modelos Odoo que necesitan operaciones masivas
class BulkOperationsMixin(models.AbstractModel):
    _name = 'bulk.operations.mixin'
    _description = 'Mixin para operaciones en bloque optimizadas'
    
    def _get_bulk_operations(self, with_notifications=True):
        """
        Obtiene instancia de BulkOperations, opcionalmente integrada
        con NotificationManager.
        
        Args:
            with_notifications: Si se debe integrar con NotificationManager
            
        Returns:
            Instancia de BulkOperations
        """
        notification_manager = None
        
        if with_notifications:
            try:
                # Intentar importar y crear NotificationManager
                import NotificationManager
                notification_manager = NotificationManager(self.env)
                notification_manager.set_active_context(
                    active_id=self.id if hasattr(self, 'id') else None,
                    active_model=self._name
                )
            except (ImportError, AttributeError):
                _logger.warning("No se pudo integrar con NotificationManager")
                
        return BulkOperations(self.env, notification_manager)
    
    def bulk_create_records(self, model_name, values_list, direct_sql=True, **kwargs):
        """
        Crea registros en bloque, usando SQL directo o API de Odoo.
        
        Args:
            model_name: Nombre del modelo
            values_list: Lista de diccionarios con valores
            direct_sql: Si se debe usar SQL directo (más rápido)
            kwargs: Otros argumentos para bulk_create
            
        Returns:
            Resultados de la operación
        """
        bulk_ops = self._get_bulk_operations()
        
        if direct_sql:
            return bulk_ops.bulk_create(model_name, values_list, **kwargs)
        else:
            return bulk_ops.bulk_create_with_commands(model_name, values_list)
    
    def bulk_update_records(self, model_name, ids, values, direct_sql=True, **kwargs):
        """
        Actualiza registros en bloque, usando SQL directo o API de Odoo.
        
        Args:
            model_name: Nombre del modelo
            ids: Lista de IDs a actualizar
            values: Valores para actualizar
            direct_sql: Si se debe usar SQL directo (más rápido)
            kwargs: Otros argumentos para bulk_update
            
        Returns:
            Resultados de la operación
        """
        bulk_ops = self._get_bulk_operations()
        
        if direct_sql:
            return bulk_ops.bulk_update(model_name, ids, values, **kwargs)
        else:
            return bulk_ops.bulk_update_with_commands(model_name, ids, values)
    
    def bulk_delete_records(self, model_name, ids, **kwargs):
        """
        Elimina registros en bloque, usando SQL directo.
        
        Args:
            model_name: Nombre del modelo
            ids: Lista de IDs a eliminar
            kwargs: Otros argumentos para bulk_delete
            
        Returns:
            Resultados de la operación
        """
        bulk_ops = self._get_bulk_operations()
        return bulk_ops.bulk_delete(model_name, ids, **kwargs)
    
    def bulk_read_records(self, model_name, ids, fields=None, **kwargs):
        """
        Lee registros en bloque, usando SQL directo.
        
        Args:
            model_name: Nombre del modelo
            ids: Lista de IDs a leer
            fields: Campos a leer
            kwargs: Otros argumentos para bulk_read
            
        Returns:
            Resultados con los registros
        """
        bulk_ops = self._get_bulk_operations()
        return bulk_ops.bulk_read(model_name, ids, fields, **kwargs)


# Ejemplo de uso en un modelo específico
class HRPayslip(models.Model):
    _name = 'hr.payslip'
    _inherit = ['bulk.operations.mixin']
    
    def process_payslips_batch(self):
        """
        Procesa un lote de nóminas utilizando operaciones en bloque.
        """
        # Inicializar bulk operations con notificaciones
        bulk_ops = self._get_bulk_operations(with_notifications=True)
        
        # Iniciar un batch para generar una sola notificación al final
        if hasattr(bulk_ops.notification_manager, 'start_batch'):
            batch_id = bulk_ops.notification_manager.start_batch("Procesamiento de nóminas")
        
        # Paso 1: Actualizar todas las nóminas en un solo lote
        update_result = bulk_ops.bulk_update(
            'hr.payslip',
            self.ids,
            {'state': 'verify', 'compute_date': fields.Datetime.now()}
        )
        
        # Paso 2: Crear líneas de nómina en un solo lote
        line_values = []
        for payslip in self:
            # Lógica para calcular líneas
            for line in payslip._calculate_lines():
                line_values.append({
                    'payslip_id': payslip.id,
                    'name': line['name'],
                    'code': line['code'],
                    'amount': line['amount'],
                    'sequence': line['sequence']
                })
        
        # Crear todas las líneas en un solo lote
        lines_result = bulk_ops.bulk_create(
            'hr.payslip.line',
            line_values,
            chunk_size=500  # Procesar en lotes de 500
        )
        
        # Paso 3: Actualizar registros relacionados
        related_ids = self.mapped('employee_id.contract_id').ids
        if related_ids:
            contract_result = bulk_ops.bulk_update(
                'hr.contract',
                related_ids,
                {'payslip_count': fields.Datetime.now()}  # Actualizar campo de seguimiento
            )
        
        # Finalizar batch y mostrar una sola notificación
        if hasattr(bulk_ops.notification_manager, 'end_batch'):
            bulk_ops.notification_manager.end_batch(batch_id)
        
        return {
            'payslips_updated': update_result['success_count'],
            'lines_created': lines_result['success_count'],
            'total_success': update_result['success_count'] + lines_result['success_count'],
            'total_errors': update_result['error_count'] + lines_result['error_count']
        }
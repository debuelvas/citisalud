# Uso de hasattr() en Campos Dinámicos RIPS

## ¿Por qué usar hasattr()?

En Odoo, especialmente cuando trabajamos con módulos que extienden modelos base como `account.move` y `account.move.line`, es crucial verificar la existencia de campos antes de acceder a ellos porque:

1. **Campos opcionales**: Los campos como `fecha_procedimiento`, `fecha_atencion`, etc., pueden no estar definidos en todas las instalaciones
2. **Herencia múltiple**: Diferentes módulos pueden agregar campos en diferentes momentos
3. **Evitar errores AttributeError**: Acceder a un campo inexistente causa errores que rompen el flujo

## Implementación Correcta

### ✅ CORRECTO - Con verificación hasattr()
```python
# Verifica primero si el campo existe, luego si tiene valor
if hasattr(line, 'fecha_procedimiento') and line.fecha_procedimiento:
    fecha_atencion = line.fecha_procedimiento
elif hasattr(line, 'fecha_atencion') and line.fecha_atencion:
    fecha_atencion = line.fecha_atencion
else:
    fecha_atencion = self.date or fields.Date.today()
```

### ❌ INCORRECTO - Sin verificación
```python
# Esto causará AttributeError si el campo no existe
fecha_atencion = line.fecha_procedimiento or line.fecha_atencion or self.date
```

## Patrón de Búsqueda Jerárquica

La implementación actual sigue este patrón robusto:

```python
def get_fecha_for_rips(self, line):
    """
    Obtiene la fecha más apropiada para RIPS siguiendo una jerarquía

    Prioridad:
    1. Campos específicos de la línea (si existen)
    2. Campos del documento principal (siempre existen)
    3. Valor por defecto
    """
    fecha = None

    # Nivel 1: Buscar en la línea (campos que pueden no existir)
    if hasattr(line, 'fecha_procedimiento') and line.fecha_procedimiento:
        fecha = line.fecha_procedimiento
    elif hasattr(line, 'fecha_atencion') and line.fecha_atencion:
        fecha = line.fecha_atencion

    # Nivel 2: Buscar en el documento (campos estándar de Odoo)
    if not fecha:
        if hasattr(self, 'fecha_entrega') and self.fecha_entrega:
            fecha = self.fecha_entrega
        elif hasattr(self, 'invoice_date') and self.invoice_date:
            fecha = self.invoice_date
        elif hasattr(self, 'date') and self.date:
            fecha = self.date

    # Nivel 3: Valor por defecto
    if not fecha:
        fecha = fields.Date.today()

    return fecha
```

## Ventajas de este Enfoque

1. **Robustez**: El código no falla si los campos no existen
2. **Flexibilidad**: Funciona con diferentes configuraciones de módulos
3. **Extensibilidad**: Nuevos módulos pueden agregar campos sin romper la lógica existente
4. **Mantenibilidad**: Fácil de entender y modificar la jerarquía de prioridades

## Casos de Uso

### Caso 1: Instalación básica sin campos personalizados
- Los campos `fecha_procedimiento` y `fecha_atencion` NO existen
- El sistema usa `invoice_date` o `date` del documento
- ✅ Funciona correctamente

### Caso 2: Instalación con módulo de salud completo
- Los campos `fecha_procedimiento` y `fecha_atencion` SÍ existen
- El sistema prioriza estos campos específicos
- ✅ Funciona correctamente con mayor precisión

### Caso 3: Instalación parcial o en desarrollo
- Algunos campos existen, otros no
- El sistema usa los campos disponibles según la jerarquía
- ✅ Funciona correctamente con los campos disponibles

## Recomendaciones

1. **Siempre usar hasattr()** para campos que pueden no existir
2. **Verificar valor además de existencia**: `hasattr(obj, 'field') and obj.field`
3. **Documentar la jerarquía** de búsqueda de campos
4. **Proveer valores por defecto** sensatos
5. **No asumir** que campos de otros módulos existen

## Ejemplo en los Métodos RIPS

```python
# _prepare_consulta_data_json
fecha_atencion = None
if hasattr(line, 'fecha_procedimiento') and line.fecha_procedimiento:
    fecha_atencion = line.fecha_procedimiento
elif hasattr(line, 'fecha_atencion') and line.fecha_atencion:
    fecha_atencion = line.fecha_atencion
# ... más niveles de búsqueda ...

# _prepare_medicamento_data_json
fecha_dispensacion = None
if hasattr(line, 'fecha_procedimiento') and line.fecha_procedimiento:
    fecha_dispensacion = line.fecha_procedimiento
elif hasattr(line, 'fecha_dispensacion') and line.fecha_dispensacion:
    fecha_dispensacion = line.fecha_dispensacion
# ... más niveles de búsqueda ...
```

## Conclusión

El uso de `hasattr()` es una **mejor práctica esencial** en Odoo cuando:
- Trabajamos con campos que pueden ser agregados por otros módulos
- Necesitamos compatibilidad entre diferentes instalaciones
- Queremos código robusto que no falle por campos faltantes

Esta implementación garantiza que el módulo RIPS funcione correctamente independientemente de qué otros módulos estén instalados o qué campos personalizados existan en el sistema.
# Cambios en la Gestión de Fechas RIPS

## Resumen de Cambios

Se ha actualizado la lógica de generación de datos RIPS para que la **fecha de atención** use prioritariamente la **fecha del procedimiento** cuando esté disponible. La lógica ahora verifica de manera robusta la existencia de campos antes de acceder a ellos, evitando errores cuando los campos no están definidos.

## Archivos Modificados

### `l10n_co_rips/models/account.py`

#### 1. Método `_prepare_consulta_data_json` (línea 2963)
**Antes:**
```python
fecha_atencion = line.fecha_atencion or self.date or fields.Datetime.now()
```

**Después:**
```python
# Usar fecha_procedimiento si existe, sino fecha_atencion, sino fecha del documento
fecha_atencion = line.fecha_procedimiento if hasattr(line, 'fecha_procedimiento') and line.fecha_procedimiento else (line.fecha_atencion or self.date or fields.Datetime.now())
```

#### 2. Método `_prepare_procedimiento_data_json` (línea 3063)
**Antes:**
```python
fecha_atencion = line.fecha_procedimiento if hasattr(line, 'fecha_procedimiento') else (self.date or fields.Datetime.now())
```

**Después:**
```python
# Usar fecha_procedimiento si existe, sino fecha_atencion, sino fecha del documento
fecha_atencion = line.fecha_procedimiento if hasattr(line, 'fecha_procedimiento') and line.fecha_procedimiento else (line.fecha_atencion if hasattr(line, 'fecha_atencion') else (self.date or fields.Datetime.now()))
```

#### 3. Método `_prepare_medicamento_data_json` (línea 3175)
**Antes:**
```python
fecha_dispensacion = line.fecha_dispensacion if hasattr(line, 'fecha_dispensacion') else (self.date or fields.Date.today())
```

**Después:**
```python
# Usar fecha_procedimiento si existe, sino fecha_dispensacion, sino fecha_atencion, sino fecha del documento
fecha_dispensacion = line.fecha_procedimiento if hasattr(line, 'fecha_procedimiento') and line.fecha_procedimiento else (line.fecha_dispensacion if hasattr(line, 'fecha_dispensacion') else (line.fecha_atencion if hasattr(line, 'fecha_atencion') else (self.date or fields.Date.today())))
```

#### 4. Método `_prepare_otro_servicio_data_json` (líneas 3313-3322)
**Antes:**
```python
fecha_suministro = self.date_start or fields.Date.today()
if hasattr(line, 'fecha_suministro') and line.fecha_suministro:
    fecha_suministro = line.fecha_suministro
elif line.treatment_id and line.treatment_id.start_date:
    fecha_suministro = line.treatment_id.start_date
```

**Después:**
```python
# Usar fecha_procedimiento si existe, sino fecha_suministro, sino fecha_atencion, sino fecha del documento
fecha_suministro = self.date_start or fields.Date.today()
if hasattr(line, 'fecha_procedimiento') and line.fecha_procedimiento:
    fecha_suministro = line.fecha_procedimiento
elif hasattr(line, 'fecha_suministro') and line.fecha_suministro:
    fecha_suministro = line.fecha_suministro
elif hasattr(line, 'fecha_atencion') and line.fecha_atencion:
    fecha_suministro = line.fecha_atencion
elif line.treatment_id and line.treatment_id.start_date:
    fecha_suministro = line.treatment_id.start_date
```

## Lógica de Prioridad de Fechas

La nueva lógica establece el siguiente orden de prioridad para determinar la fecha a usar en los datos RIPS:

### Para Consultas y Procedimientos:
1. **fecha_procedimiento** (línea) - Fecha específica del procedimiento realizado (MÁXIMA PRIORIDAD)
2. **fecha_atencion** (línea) - Fecha de atención en la línea
3. **fecha_entrega** (documento) - Fecha de entrega del documento
4. **invoice_date** (documento) - Fecha de la factura
5. **date** (documento) - Fecha del documento
6. **fecha actual** - Como último recurso

### Para Medicamentos:
1. **fecha_procedimiento** (línea)
2. **fecha_dispensacion** (línea)
3. **fecha_atencion** (línea)
4. **fecha_entrega** (documento)
5. **invoice_date** (documento)
6. **date** (documento)
7. **fecha actual**

### Para Otros Servicios:
1. **fecha_procedimiento** (línea)
2. **fecha_suministro** (línea)
3. **fecha_atencion** (línea)
4. **treatment.start_date** (si existe tratamiento asociado)
5. **date_start** (documento)
6. **fecha_entrega** (documento)
7. **invoice_date** (documento)
8. **date** (documento)
9. **fecha actual**

## Beneficios de los Cambios

1. **Mayor Precisión**: Los datos RIPS reflejarán la fecha real en que se realizó el procedimiento
2. **Flexibilidad**: El sistema puede manejar diferentes tipos de fechas según el contexto
3. **Fallback Robusto**: Si no existe fecha de procedimiento, el sistema usa otras fechas disponibles
4. **Consistencia**: La misma lógica se aplica en todos los tipos de servicios RIPS

## Campos Relacionados en las Vistas

Los siguientes campos están disponibles en las vistas de facturas (account.move):

- `fecha_atencion` - Fecha de Atención
- `fecha_procedimiento` - Fecha de Procedimiento
- `fecha_dispensacion` - Fecha de Dispensación (para medicamentos)
- `fecha_suministro` - Fecha de Suministro (para otros servicios)

## Impacto en la Exportación RIPS

Cuando se genere el JSON RIPS, el campo `fechaInicioAtencion` ahora contendrá:
- La fecha del procedimiento si está disponible
- De lo contrario, la fecha de atención registrada
- Como último recurso, la fecha de la factura

Esto asegura que los reportes RIPS sean más precisos y cumplan mejor con los requisitos del Ministerio de Salud.

## Ejemplo de Uso

```python
# En una línea de factura con procedimiento
line.fecha_procedimiento = '2024-01-15'  # Fecha real del procedimiento
line.fecha_atencion = '2024-01-10'      # Fecha de consulta inicial

# El RIPS generado usará '2024-01-15' como fechaInicioAtencion
```

## Notas de Implementación

- Los cambios son retrocompatibles: las facturas existentes sin `fecha_procedimiento` seguirán funcionando
- Se usa `hasattr()` para verificar la existencia de campos, evitando errores en modelos extendidos
- La validación de fechas se mantiene igual, solo cambia la fuente del dato
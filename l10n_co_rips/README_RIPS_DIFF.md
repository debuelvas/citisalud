# Módulo RIPS - Diferencias y Mejoras de Gestión de Datos

## Descripción General

Este módulo extiende las funcionalidades de importación y exportación RIPS, agregando capacidades diferenciales para la gestión de datos, validación inteligente y corrección automática.

## Componentes Principales

### 1. **invoice_importer.py** (Copiado de citysalud-17)
- Lógica base de importación de facturas desde Excel/CSV
- Creación automática de facturas con datos RIPS
- Validación de campos requeridos
- Mapeo de columnas Excel a campos Odoo

### 2. **account.py** (Copiado de citysalud-17)
- Métodos de generación de JSON RIPS
- Validación de estructura RIPS
- Envío a MinSalud para validación
- Gestión de respuestas y errores

### 3. **rips_data_diff.py** (NUEVO - Diferencias Implementadas)
- **Validación Diferencial**: Detecta diferencias entre datos originales e importados
- **Corrección Automática**: Aplica correcciones inteligentes a datos con formato incorrecto
- **Mapeo Inteligente**: Detecta automáticamente la correspondencia entre columnas Excel y campos
- **Score de Validación**: Calcula un puntaje de validez de los datos (0-100)

### 4. **import_config.py** (NUEVO - Configuración Avanzada)
- Configuración centralizada de importación
- Reglas de corrección personalizables
- Validación de códigos CUPS y CIE-10
- Manejo de múltiples formatos de fecha y decimales

## Diferencias Clave con el Módulo Base

### 1. Validación Diferencial de Datos

```python
# Detecta automáticamente diferencias entre datos existentes y nuevos
differences = validate_rips_data_differences(original_data, imported_data)
```

**Ventajas:**
- Identifica campos faltantes
- Detecta valores inválidos
- Sugiere correcciones automáticas
- Mantiene trazabilidad de cambios

### 2. Corrección Automática Inteligente

```python
# Aplica correcciones basadas en reglas configurables
corrected_data = apply_data_corrections(invoice_data, corrections)
```

**Tipos de correcciones:**
- Limpieza de NIT/CC (elimina caracteres no numéricos)
- Normalización de fechas
- Validación de códigos CUPS y CIE-10
- Formato de montos y cantidades

### 3. Mapeo Inteligente de Campos

```python
# Detecta automáticamente la correspondencia de columnas
mapping = smart_field_mapping(excel_columns)
```

**Características:**
- Reconocimiento de variaciones en nombres de columnas
- Mapeo basado en coincidencias parciales
- Soporte para sinónimos comunes
- Configuración personalizable por JSON

### 4. Score de Validación RIPS

```python
# Calcula un score de validez de datos (0-100)
rips_validation_score = (valid_fields / total_fields) * 100
```

**Utilidad:**
- Métrica de calidad de datos
- Identificación de registros problemáticos
- Priorización de correcciones
- Reportes de calidad

## Campos Adicionales en account.move

```python
# Nuevos campos para tracking diferencial
rips_data_differences = fields.Text()  # JSON con diferencias detectadas
rips_corrections_applied = fields.Json()  # Correcciones aplicadas
rips_validation_score = fields.Float()  # Score de validación (0-100)
```

## Configuración de Importación Mejorada

### Validaciones Configurables:
- **validate_nit**: Valida NIT/CC del cliente
- **validate_cups_codes**: Valida códigos CUPS
- **validate_cie10_codes**: Valida códigos CIE-10
- **validate_contracts**: Valida contratos vigentes

### Correcciones Automáticas:
- **auto_correct_data**: Corrige formato de datos
- **auto_create_missing**: Crea registros faltantes
- **skip_duplicates**: Omite registros duplicados

### Formatos Configurables:
- **date_format**: Formato de fecha esperado
- **decimal_separator**: Separador decimal
- **thousand_separator**: Separador de miles

## Uso del Módulo

### 1. Importación con Validación Diferencial

```python
# Crear configuración
config = env['rips.import.config'].get_default_config()

# Procesar importación con análisis diferencial
enhancement = env['rips.data.enhancement']
results = enhancement.process_differential_import(file_data, {
    'auto_correct': True,
    'validate_codes': True
})
```

### 2. Validación de Diferencias en Factura Existente

```python
# Validar diferencias en factura
invoice = env['account.move'].browse(invoice_id)
invoice.validate_rips_differences()

# Ver score de validación
print(f"Score de validación: {invoice.rips_validation_score}%")
```

### 3. Exportación RIPS Mejorada

```python
# Exportar con mejoras automáticas
enhancement = env['rips.data.enhancement']
enhanced_data = enhancement.enhance_rips_export_data(rips_data)
```

## Beneficios de las Mejoras

1. **Mayor Calidad de Datos**
   - Detección temprana de errores
   - Corrección automática de formatos
   - Validación contra catálogos oficiales

2. **Trazabilidad Completa**
   - Registro de todas las diferencias
   - Historial de correcciones aplicadas
   - Métricas de calidad

3. **Reducción de Errores**
   - Validación preventiva
   - Mapeo inteligente de campos
   - Reglas de negocio configurables

4. **Flexibilidad**
   - Configuración sin código
   - Reglas personalizables por JSON
   - Soporte para múltiples formatos

## Instalación y Configuración

1. Copiar el módulo a la carpeta de addons de Odoo
2. Actualizar lista de aplicaciones
3. Instalar el módulo "l10n_co_rips"
4. Configurar reglas de importación en:
   - Facturación > Configuración > RIPS > Configuración de Importación

## Dependencias

- odoo base
- account (Contabilidad)
- l10n_co_e-invoice (Facturación Electrónica Colombia)
- pandas (para procesamiento de Excel)
- reportlab (para generación de PDF)

## Notas de Implementación

- Los archivos `invoice_importer.py` y `account.py` son copias directas del módulo citysalud-17
- Los archivos `rips_data_diff.py` e `import_config.py` son las extensiones con mejoras
- El módulo es compatible con Odoo 17 y 18
- Requiere configuración inicial de mapeo de campos según formato de Excel usado

## Soporte

Para preguntas o problemas con el módulo, revisar:
- Logs del sistema en /var/log/odoo/
- Configuración de mapeo de campos
- Validez de códigos CUPS y CIE-10 según catálogos oficiales
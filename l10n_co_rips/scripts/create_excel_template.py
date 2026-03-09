#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para crear plantilla Excel de importación de facturas
Con ejemplos de SALUD y COMERCIALES
"""

import pandas as pd
from datetime import datetime
import os

# Crear el directorio data/examples si no existe
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
examples_dir = os.path.join(base_dir, 'data', 'examples')
os.makedirs(examples_dir, exist_ok=True)

# ============================================
# HOJA 1: INSTRUCCIONES
# ============================================
instrucciones_data = {
    'SECCIÓN': [
        'BIENVENIDA',
        '',
        'ESTRUCTURA',
        '',
        '',
        '',
        'CAMPOS OBLIGATORIOS',
        '',
        '',
        '',
        '',
        'CAMPOS OPCIONALES SALUD',
        '',
        '',
        '',
        '',
        '',
        'AGRUPACIÓN',
        '',
        '',
        'CONSEJOS',
        '',
        '',
        '',
        '',
    ],
    'DESCRIPCIÓN': [
        'Plantilla para importación masiva de facturas',
        'Compatible con facturas de SALUD y COMERCIALES',
        'Cada fila representa UNA LÍNEA de factura',
        'Varias filas con el mismo id_temp = UNA factura con múltiples líneas',
        'El sistema agrupa automáticamente por id_temp',
        '',
        '* id_temp: Identificador único de factura (agrupa líneas)',
        '* partner_vat: NIT/CC del cliente (sin puntos ni guiones)',
        '* partner_name: Nombre del cliente',
        '* product_code: Código del producto/servicio',
        '* quantity: Cantidad',
        '* price_unit: Precio unitario',
        '* patient_name: Nombre del paciente (SOLO SALUD)',
        '* patient_document: CC del paciente (SOLO SALUD)',
        '* diagnosis: Código CIE-10 (SOLO SALUD - se propaga a todas las líneas)',
        '* authorization_number: Número de autorización (SOLO SALUD)',
        '',
        'El sistema agrupa todas las filas con el MISMO id_temp',
        'Ejemplo: id_temp=FAC001 con 5 filas = 1 factura con 5 líneas',
        'IMPORTANTE: El código CIE-10 de la PRIMERA línea se copia a TODAS',
        '',
        '! No use caracteres especiales en id_temp',
        '! El NIT/CC debe existir en Odoo o habilite creación automática',
        '! Los códigos de producto deben existir en Odoo',
        '! Para SALUD: llene TODOS los campos de paciente',
        '! Revise duplicados: el sistema valida por consecutivo',
    ]
}

# ============================================
# HOJA 2: EJEMPLO FACTURA SALUD (HOSPITALARIA)
# ============================================
salud_data = {
    # CABECERA
    'id_temp': ['SALUD-001', 'SALUD-001', 'SALUD-001', 'SALUD-002', 'SALUD-002'],
    'partner_vat': ['900123456', '900123456', '900123456', '800654321', '800654321'],
    'partner_name': ['EPS SALUD TOTAL', 'EPS SALUD TOTAL', 'EPS SALUD TOTAL', 'NUEVA EPS', 'NUEVA EPS'],
    'reference': ['FAC-2024-0001', 'FAC-2024-0001', 'FAC-2024-0001', 'FAC-2024-0002', 'FAC-2024-0002'],
    'invoice_date': ['2024-01-15', '2024-01-15', '2024-01-15', '2024-01-16', '2024-01-16'],
    'date_due': ['2024-02-15', '2024-02-15', '2024-02-15', '2024-02-16', '2024-02-16'],
    'journal_code': ['INV', 'INV', 'INV', 'INV', 'INV'],
    'contract_code': ['CONT-001', 'CONT-001', 'CONT-001', 'CONT-002', 'CONT-002'],
    'invoice_type': ['out_invoice', 'out_invoice', 'out_invoice', 'out_invoice', 'out_invoice'],

    # LÍNEA DE DETALLE
    'product_code': ['CONS-MED-001', 'LAB-HEM-001', 'MED-ACET-500', 'CONS-ESP-001', 'RX-TORAX'],
    'line_description': ['Consulta médica general', 'Hemograma completo', 'Acetaminofén 500mg x 10', 'Consulta especialista', 'Radiografía de tórax'],
    'quantity': [1, 1, 10, 1, 1],
    'price_unit': [50000, 35000, 1200, 120000, 85000],
    'tax_names': ['IVA 19%', 'IVA 19%', 'IVA 5%', 'IVA 19%', 'IVA 19%'],

    # PACIENTE RIPS
    'patient_name': ['Juan Carlos Pérez López', 'Juan Carlos Pérez López', 'Juan Carlos Pérez López', 'María Fernanda Gómez', 'María Fernanda Gómez'],
    'patient_document': ['1012345678', '1012345678', '1012345678', '52987654', '52987654'],
    'patient_doc_type': ['CC', 'CC', 'CC', 'CC', 'CC'],
    'patient_birth_date': ['1985-03-20', '1985-03-20', '1985-03-20', '1992-08-15', '1992-08-15'],
    'patient_gender': ['M', 'M', 'M', 'F', 'F'],
    'patient_user_type': ['C', 'C', 'C', 'B', 'B'],
    'patient_zone': ['U', 'U', 'U', 'U', 'U'],
    'patient_city': ['Bogotá', 'Bogotá', 'Bogotá', 'Medellín', 'Medellín'],
    'patient_country': ['Colombia', 'Colombia', 'Colombia', 'Colombia', 'Colombia'],
    'patient_nationality': ['CO', 'CO', 'CO', 'CO', 'CO'],

    # DATOS CLÍNICOS
    'diagnosis': ['J00', 'J00', 'J00', 'M545', 'M545'],
    'authorization_number': ['AUTH-2024-001234', 'AUTH-2024-001234', 'AUTH-2024-001234', 'AUTH-2024-001235', 'AUTH-2024-001235'],
    'service_date': ['2024-01-15', '2024-01-15', '2024-01-15', '2024-01-16', '2024-01-16'],

    # CONTRATO
    'contract_ref': ['CONT-EPS-2024', 'CONT-EPS-2024', 'CONT-EPS-2024', 'CONT-NUEVA-2024', 'CONT-NUEVA-2024'],

    # CUENTA CONTABLE
    'account_code': ['410505', '410505', '410505', '410505', '410505'],
}

# ============================================
# HOJA 3: EJEMPLO FACTURA COMERCIAL
# ============================================
comercial_data = {
    # CABECERA
    'id_temp': ['COM-001', 'COM-001', 'COM-001', 'COM-002'],
    'partner_vat': ['900888777', '900888777', '900888777', '79123456'],
    'partner_name': ['EMPRESA ABC S.A.S.', 'EMPRESA ABC S.A.S.', 'EMPRESA ABC S.A.S.', 'Pedro González'],
    'reference': ['FCOM-2024-0001', 'FCOM-2024-0001', 'FCOM-2024-0001', 'FCOM-2024-0002'],
    'invoice_date': ['2024-01-15', '2024-01-15', '2024-01-15', '2024-01-16'],
    'date_due': ['2024-02-15', '2024-02-15', '2024-02-15', '2024-02-16'],
    'journal_code': ['INV', 'INV', 'INV', 'INV'],
    'invoice_type': ['out_invoice', 'out_invoice', 'out_invoice', 'out_invoice'],

    # LÍNEA DE DETALLE
    'product_code': ['PROD-001', 'PROD-002', 'SERV-001', 'PROD-003'],
    'line_description': ['Computador portátil HP', 'Mouse inalámbrico Logitech', 'Instalación y configuración', 'Impresora multifuncional'],
    'quantity': [2, 2, 1, 1],
    'price_unit': [2500000, 45000, 150000, 890000],
    'tax_names': ['IVA 19%', 'IVA 19%', 'IVA 19%', 'IVA 19%'],
    'account_code': ['413505', '413505', '413520', '413505'],
}

# ============================================
# HOJA 4: EJEMPLO NOTA CRÉDITO
# ============================================
nota_credito_data = {
    # CABECERA
    'id_temp': ['NC-001', 'NC-001', 'NC-002'],
    'partner_vat': ['900888777', '900888777', '79123456'],
    'partner_name': ['EMPRESA ABC S.A.S.', 'EMPRESA ABC S.A.S.', 'Pedro González'],
    'reference': ['NC-2024-0001', 'NC-2024-0001', 'NC-2024-0002'],
    'invoice_date': ['2024-01-20', '2024-01-20', '2024-01-21'],
    'invoice_type': ['out_refund', 'out_refund', 'out_refund'],
    'journal_code': ['DEVO', 'DEVO', 'DEVO'],

    # FACTURA ORIGEN
    'origin_invoice': ['FCOM-2024-0001', 'FCOM-2024-0001', 'FCOM-2024-0002'],
    'credit_reason': ['Devolución parcial', 'Devolución parcial', 'Anulación completa'],

    # LÍNEA DE DETALLE (productos a devolver/anular)
    'product_code': ['PROD-001', 'PROD-002', 'PROD-003'],
    'line_description': ['Computador portátil HP (devolución)', 'Mouse inalámbrico (devolución)', 'Impresora (anulación)'],
    'quantity': [1, 1, 1],
    'price_unit': [2500000, 45000, 890000],
    'tax_names': ['IVA 19%', 'IVA 19%', 'IVA 19%'],
}

# ============================================
# HOJA 4: MAPEO DE COLUMNAS
# ============================================
mapeo_data = {
    'COLUMNA EXCEL': [
        'id_temp',
        'partner_vat',
        'partner_name',
        'reference',
        'invoice_date',
        'date_due',
        'product_code',
        'line_description',
        'quantity',
        'price_unit',
        'patient_name',
        'patient_document',
        'patient_doc_type',
        'patient_birth_date',
        'patient_gender',
        'diagnosis',
        'authorization_number',
        'service_date',
        'contract_ref',
        'patient_city',
        'patient_zone',
        'account_code',
    ],
    'OBLIGATORIO': [
        'SÍ',
        'SÍ',
        'SÍ',
        'NO (se genera auto)',
        'SÍ',
        'NO',
        'SÍ',
        'NO',
        'SÍ',
        'SÍ',
        'SALUD: SÍ',
        'SALUD: SÍ',
        'SALUD: SÍ',
        'SALUD: SÍ',
        'SALUD: SÍ',
        'SALUD: SÍ',
        'SALUD: SÍ',
        'SALUD: NO',
        'SALUD: NO',
        'SALUD: NO',
        'SALUD: NO',
        'NO',
    ],
    'DESCRIPCIÓN': [
        'ID temporal para agrupar líneas (ej: FAC001)',
        'NIT o CC del cliente sin puntos',
        'Nombre/Razón social del cliente',
        'Consecutivo de factura (opcional, se genera)',
        'Fecha de la factura (YYYY-MM-DD)',
        'Fecha de vencimiento (YYYY-MM-DD)',
        'Código del producto/servicio en Odoo',
        'Descripción de la línea',
        'Cantidad',
        'Precio unitario sin IVA',
        'Nombre completo del paciente',
        'Documento de identidad del paciente',
        'Tipo: CC, TI, CE, RC, PA, etc.',
        'Fecha de nacimiento (YYYY-MM-DD)',
        'M=Masculino, F=Femenino, O=Otro',
        'Código CIE-10 del diagnóstico',
        'Número de autorización médica',
        'Fecha de atención (YYYY-MM-DD)',
        'Referencia del contrato',
        'Ciudad del paciente',
        'U=Urbana, R=Rural',
        'Código de cuenta contable (opcional)',
    ],
    'EJEMPLO': [
        'SALUD-001',
        '900123456',
        'EPS SALUD TOTAL',
        'FAC-2024-0001',
        '2024-01-15',
        '2024-02-15',
        'CONS-MED-001',
        'Consulta médica general',
        '1',
        '50000',
        'Juan Pérez López',
        '1012345678',
        'CC',
        '1985-03-20',
        'M',
        'J00',
        'AUTH-2024-001234',
        '2024-01-15',
        'CONT-EPS-2024',
        'Bogotá',
        'U',
        '4135',
    ]
}

# ============================================
# CREAR ARCHIVO EXCEL
# ============================================
output_file = os.path.join(examples_dir, 'PLANTILLA_IMPORTACION_FACTURAS.xlsx')

with pd.ExcelWriter(output_file, engine='xlsxwriter') as writer:
    # Hoja 1: Instrucciones
    df_instrucciones = pd.DataFrame(instrucciones_data)
    df_instrucciones.to_excel(writer, sheet_name='INSTRUCCIONES', index=False)

    # Hoja 2: Ejemplo Salud
    df_salud = pd.DataFrame(salud_data)
    df_salud.to_excel(writer, sheet_name='EJEMPLO SALUD', index=False)

    # Hoja 3: Ejemplo Comercial
    df_comercial = pd.DataFrame(comercial_data)
    df_comercial.to_excel(writer, sheet_name='EJEMPLO COMERCIAL', index=False)

    # Hoja 4: Ejemplo Nota Crédito
    df_nota_credito = pd.DataFrame(nota_credito_data)
    df_nota_credito.to_excel(writer, sheet_name='NOTA CREDITO', index=False)

    # Hoja 5: Mapeo
    df_mapeo = pd.DataFrame(mapeo_data)
    df_mapeo.to_excel(writer, sheet_name='MAPEO COLUMNAS', index=False)

    # Obtener el workbook y aplicar formato
    workbook = writer.book

    # Formato para encabezados
    header_format = workbook.add_format({
        'bold': True,
        'bg_color': '#4472C4',
        'font_color': 'white',
        'align': 'center',
        'valign': 'vcenter',
        'border': 1
    })

    # Formato para instrucciones
    instrucciones_sheet = writer.sheets['📖 INSTRUCCIONES']
    instrucciones_sheet.set_column('A:A', 25)
    instrucciones_sheet.set_column('B:B', 80)

    # Formato para ejemplos
    for sheet_name in ['✅ EJEMPLO SALUD', '✅ EJEMPLO COMERCIAL']:
        worksheet = writer.sheets[sheet_name]
        worksheet.set_column('A:Z', 18)
        worksheet.freeze_panes(1, 0)

    # Formato para mapeo
    mapeo_sheet = writer.sheets['📋 MAPEO COLUMNAS']
    mapeo_sheet.set_column('A:A', 25)
    mapeo_sheet.set_column('B:B', 15)
    mapeo_sheet.set_column('C:C', 50)
    mapeo_sheet.set_column('D:D', 25)

print('[OK] Archivo creado exitosamente: ' + output_file)
print('[INFO] Hojas creadas:')
print('   1. INSTRUCCIONES - Guia de uso')
print('   2. EJEMPLO SALUD - 2 facturas hospitalarias con 5 lineas')
print('   3. EJEMPLO COMERCIAL - 2 facturas comerciales con 4 lineas')
print('   4. MAPEO COLUMNAS - Referencia completa de campos')

# -*- coding: utf-8 -*-

from odoo import http
from odoo.http import request, content_disposition
import pandas as pd
import io
from datetime import datetime


class InvoiceImporterController(http.Controller):

    @http.route('/l10n_co_rips/download_template', type='http', auth='user')
    def download_excel_template(self, **kwargs):
        """
        Descarga directa de plantilla Excel sin pasar por action.
        OPTIMIZADO: Genera archivo pequeño y lo retorna como descarga HTTP.
        """
        # Crear Excel en memoria
        output = io.BytesIO()

        # Datos simplificados para la plantilla
        instrucciones_data = {
            'CAMPO': [
                'id_temp',
                'partner_vat',
                'partner_name',
                'product_code',
                'quantity',
                'price_unit',
                'patient_name',
                'patient_document',
            ],
            'DESCRIPCIÓN': [
                'ID temporal de factura (agrupa líneas)',
                'NIT/CC del cliente',
                'Nombre del cliente',
                'Código del producto',
                'Cantidad',
                'Precio unitario',
                'Nombre paciente (SOLO SALUD)',
                'Documento paciente (SOLO SALUD)',
            ],
            'OBLIGATORIO': [
                'Sí',
                'Sí',
                'Sí',
                'Sí',
                'Sí',
                'Sí',
                'No',
                'No',
            ]
        }

        ejemplo_data = {
            'id_temp': ['SALUD-001'],
            'partner_vat': ['900123456'],
            'partner_name': ['EPS SALUD TOTAL'],
            'reference': ['FAC-2024-0001'],
            'invoice_date': ['2024-01-15'],
            'product_code': ['CONS-MED-001'],
            'line_description': ['Consulta médica'],
            'quantity': [1],
            'price_unit': [50000],
            'patient_name': ['Juan Pérez'],
            'patient_document': ['1012345678'],
        }

        # Crear Excel con 2 hojas
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            pd.DataFrame(instrucciones_data).to_excel(writer, sheet_name='INSTRUCCIONES', index=False)
            pd.DataFrame(ejemplo_data).to_excel(writer, sheet_name='EJEMPLO', index=False)

            # Formato simple
            workbook = writer.book
            worksheet = writer.sheets['EJEMPLO']
            worksheet.set_column('A:K', 15)
            worksheet.freeze_panes(1, 0)

        # Preparar descarga
        output.seek(0)
        excel_content = output.read()
        output.close()

        # Nombre del archivo con fecha
        filename = f'PLANTILLA_IMPORTACION_FACTURAS_{datetime.now().strftime("%Y%m%d")}.xlsx'

        # Retornar como descarga HTTP
        return request.make_response(
            excel_content,
            headers=[
                ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                ('Content-Disposition', content_disposition(filename)),
                ('Content-Length', len(excel_content))
            ]
        )

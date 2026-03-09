{
    "name": "LAVISH FACTURACION ELECTRONICA COLOMBIA",
    "summary": """
        Genera la facturacion electronica para la distribucion colombiana segun requisitos de la DIAN""",
    "category": "Administration",
    "version": "17.0.0.0.3",
    "author": "Lavish",
    "license": "LGPL-3",
    'description': """
        Facturación Electrónica para el Sector Salud - Colombia
        
        =======================================================

        Este módulo implementa los requisitos específicos para la facturación electrónica 
        del sector salud en Colombia, según las Resoluciones 2275 de 2023 y 1884 de 2024 
        del Ministerio de Salud y Protección Social, y el Decreto 441 de 2022.

        Características principales:
        ---------------------------
        * Gestión de tipos de operación salud
        * Configuración de planes de cobertura según normativa
        * Gestión de modalidades de pago del sector salud
        * Manejo de conceptos de recaudo
        * Validaciones automáticas según el tipo de operación y cobertura
        * Integración con la facturación electrónica DIAN

        Este módulo permite cumplir con los requerimientos del Anexo Técnico 2 para la 
        generación correcta de los "Campos Adicionales del Sector Salud" en las facturas 
        electrónicas, asegurando la interoperabilidad con el sistema DIAN y el Mecanismo 
        Único de Validación (MUV) del Ministerio de Salud.

        Tipos de Operación Implementados:
        --------------------------------
        - SS-CUFE: Factura que acredita un recaudo documentado mediante FEV previa
        - SS-CUDE: Factura que acredita un recaudo registrado en contingencia
        - SS-POS: Factura que acredita un recaudo por documento POS/datáfono (SOLO POS)
        - SS-SNum: Factura que acredita un recaudo con documento manual
        - SS-Recaudo: Documento que registra el recaudo inicial del usuario
        - SS-Reporte: Factura que informa un recaudo sin acreditarlo en el valor
        - SS-SinAporte: Factura por servicios sin ningún aporte del usuario

        Modalidades de Pago:
        -------------------
        - Pago individual por caso / Conjunto integral / Paquete / Canasta
        - Pago global prospectivo
        - Pago por capitación
        - Pago por evento
        - Otras modalidades específicas

        Planes de Cobertura:
        -------------------
        Implementa los 21 tipos de cobertura definidos en la normativa, desde el Plan de 
        Beneficios en Salud financiado con UPC hasta planes voluntarios, SOAT, ARL y otras 
        coberturas especiales.

        Conceptos de Recaudo:
        --------------------
        - COPAGO
        - CUOTA MODERADORA
        - PAGOS COMPARTIDOS EN PLANES VOLUNTARIOS DE SALUD
        - ANTICIPO
        - NO APLICA
    """,
            
    "depends": [
        "account",
        "lavish_erp",
        "base",
        "contacts",
        "l10n_latam_invoice_document",
        "acs_hms_base",
        "l10n_co",
    ],
    "data": [
        "data/template_invoice.xml",
        "data/nota_credito.xml",
        "data/credit_note_ds_template.xml",
        "data/bill_ds_template.xml",
        "data/co_medical_services.xml",
        "data/nota_debito.xml",
        "data/attached_document.xml",
        "data/firma.xml",
        "data/mail_layout_no_button.xml",
        "data/email_template_dian.xml",
        "security/ir.model.access.csv",
        "security/security.xml",
        "data/account.payment.method.dian.csv",
        "data/dian_fiscal_responsability_data.xml",
        "data/dian_tributes_data.xml",
        "data/sequence.xml",
        "data/dian_cron.xml",
        "data/scheduled_actions.xml",
        "data/dian_validation_user.xml",
        "views/dian_tribute.xml",
        "views/res_company_inherit_view.xml",
        "views/res_partner_inherit_view.xml",
        "views/account_journal_inherit_view.xml",
        "views/account_tax_inherit_view.xml",
        "views/ir_sequence_inherit_view.xml",
        "views/product_template_inherit_view.xml",
        "views/account_move_inherit_view.xml",
        "views/dian_document_view.xml",
        "views/report_invoice.xml",
        "views/account_payment_method_dian.xml",
        "report/report_invoice_inherit_view.xml",
        "views/configuracion_co_salud.xml",
        "wizards/validate_invoice.xml",
        "views/recepcion_factura_dian_view.xml",
    ],
    "external_dependencies": {
        "python": [
            "pyopenssl",
            "pyOpenSSL",
            "requests",
            "xmltodict",
            "PyQRCode",
            "pypng",
            "pyqrcode",
            "cryptography",
            "xmltodict",
            "uuid",
            "hashlib",
        ],
    },
    "installable": True,
}

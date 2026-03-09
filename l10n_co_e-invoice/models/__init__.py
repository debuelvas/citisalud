# -*- coding: utf-8 -*-

# Utilidades
from . import xml_utils

# Modelos base DIAN
from . import dian_document
from . import adstractMove
from . import dian_fiscal_responsability
from . import dian_tributes
from . import dian_clasificador
from . import dian_application_response
from . import dian_application_response_inherit
from . import move_desc
# Modelos de salud
from . import health_models

# Herencias de modelos Odoo
from . import res_company_inherit
from . import res_partner_inherit
from . import account_journal_inherit
from . import account_tax_inherit
from . import account_move
from . import account_aiu
from . import account_event
from . import account_move_reversal_inherit
from . import account_invoice_report_inherit

# Productos
from . import product_brand
from . import product_model
from . import product_template_inherit

# Secuencias y resoluciones DIAN
from . import ir_sequence_dian_resolution_inherit
from . import ir_attachment_inherit

# Validación y recepción
from . import validate_invoice_cron
from . import recepcion_factura_dian

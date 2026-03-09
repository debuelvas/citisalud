# -*- coding: utf-8 -*-
{
    'name': 'Colombia RIPS',
    'summary': 'RIPS',
    'description': """ Extras para medfix RIPS""",
    'version': '1.0',
    'category': 'Medical',
    'author': 'Lavish',
    'license': 'OPL-1',
    'depends': ['base_address_extended', 'acs_hms','lavish_erp'],
    "data": [
        "data/data.xml",
        "data/rip_sequence_data.xml",
        "data/email_templates.xml",
        "security/ir.model.access.csv",
        "views/account_move_view.xml",
        "views/glosa_medicas_view.xml",
        "views/hospital_rips_view.xml",
        "views/invoice_importer_views.xml",
        "views/menuitem_view.xml",
        "views/rips_configuration_views.xml",
    ],
    'assets': {
        'web.assets_backend': [
            'l10n_co_rips/static/src/scss/notarial_kanban.scss',
        ],
    },
}
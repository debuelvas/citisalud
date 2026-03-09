{
    'name': 'l10n_co_documento_soporte',
    'version': '17.0.0.0.1',
    'summary': 'Account',
    'description': 'Module for document soport in FE',
    'category': 'Account',
    'author': 'Lavish',
    "license": "LGPL-3",
    'depends': ['l10n_co_e-invoice',],
    'data': [
        'views/l10n_co_res_partner_residence.xml',
        #'views/report_invoice_ds_inherit.xml',
        'views/account_move_line.xml'
    ],
    'installable': True,
    'auto_install': False
}

# -*- coding: utf-8 -*-
{
    'name': "lavish_erp",
    'summary': """
        lavish ERP""",
    'description': """
        .lavish ERP.
    """,
    'author': "lavish S.A.S",
    'website': "http://www.lavish.com.co",
    'category': 'lavishERP',
    'version': '0.0.2',
    'application': True,
    "license": "AGPL-3",
    'depends': ['base',
        'contacts',
        'account',
        'account_tax_python',
        'l10n_co',
        'base_address_extended',
        "purchase",
        "base_setup",
        "l10n_latam_invoice_document",
        "sale"],
    'assets': {
        'web.assets_backend': [
            'lavish_erp/static/scss/style.scss',
        ],
    },
    'data': [
        'data/res.bank.csv',
        'data/dian.type_code.csv',
        'data/dian.uom.code.csv',
        'data/dian.tax.type.csv',
        'data/l10n_latam.identification.type.csv',
        'data/res_country_state.xml',
        #'views/account_move_view.xml',
        'data/res.city.csv',
        'security/ir.model.access.csv',
        'views/journal.xml',
        'views/res_country_state.xml',
        'views/res_country_view.xml',
        'views/product_category_view.xml',
        'views/general_actions.xml',
        'views/res_partner.xml',
        'views/res_users.xml',
        # 'views/sale_order_view.xml',
        # 'views/general_menus.xml'       
    ]  
}

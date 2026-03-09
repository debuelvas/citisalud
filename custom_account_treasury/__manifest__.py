
{
    "name": "Tesoreria Pagos y Cobros",
    "version": "17.0.0.0",
    "category": "Treasury",
    "license": "AGPL-3",
    "summary": "Permite el pago multiple de cuentas por cobrar y/o pagar",
    "author": "David",
    "depends":[
        "base",
        "account",
        "account_check_printing"
    ],
    "data": [
        'data/sequence_data.xml',
        "security/group_users.xml",
        "security/ir.model.access.csv",
        "views/account_massive_payment_view.xml",
        "views/advance_type_view.xml",
        "views/account_move.xml",
        "views/account_payment_method_view.xml",
        "views/treasury_menu_view.xml",
        "views/reporte_aviso.xml",
    ],
    'assets': {
        'web.assets_backend': [
            'custom_account_treasury/static/src/js/payment_amount_widget.js',
            'custom_account_treasury/static/src/js/payment_amount_templates.xml',
            'custom_account_treasury/static/src/js/payment_amount.css',
        ],
    },
    "active": True,
    "application": True,
    "installable": True,
}

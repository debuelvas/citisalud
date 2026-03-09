{
    "name": "Colombian e-invoice etendido",
    "summary": """
        Genera la facturacion electronica para la distribucion colombiana segun requisitos de la DIAN""",
    "category": "Administration",
    "version": "17.0.0.0.1",
    "author": "Gustavo Hinojosa",
    "license": "LGPL-3",
    "depends": [
        "l10n_co_e-invoice"
    ],
    "data": [
        "views/res_company_view.xml",
        "views/account_move_view.xml",
    ],
    "installable": True,
    "auto_install": True
}

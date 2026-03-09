# -*- coding: utf-8 -*-
{
    'name': "lavish_hr_social_security",

    'summary': """
        Módulo de nómina para la localización colombiana | Seguridad Social""",

    'description': """
        Módulo de nómina para la localización colombiana | Seguridad Social
    """,

    'author': "lavish S.A.S",
    
    'category': 'Human Resources',
    'version': '0.1',
    'license': 'OPL-1',
    'depends': ['base','hr','hr_payroll','hr_holidays', 'lavish_erp','lavish_hr_employee','lavish_hr_payroll','account'],
    "data": [
        "security/ir.model.access.csv",
        "views/actions_hr_closing_configuration.xml",
        "views/actions_hr_consolidated_provisions.xml",
        "views/actions_hr_entities_reports.xml",
        "views/actions_hr_payroll_social_security.xml",
        "views/actions_hr_provisions.xml",
        "views/actions_hr_social_security_branches.xml",
        "views/actions_parameterization.xml",
        "views/actions_vacation_book_reports.xml",
        "views/hr_executing_social_security_views.xml",
        "views/menus.xml",
        "reports/social_security_report_template.xml",
        "reports/social_security_report.xml"
    ],
    'assets': {
        'web.assets_backend': [
            'lavish_hr_social_security/static/scss/style.scss',
        ],
    },
    
}

# -*- coding: utf-8 -*-

{
    'name': 'Epayroll',
    'summary': 'Description',
    'version': '1.1',
    'category': 'Accounting/Accounting',
    'author': 'DAVID A',
    'license': '',
    'application': False,
    'installable': True,
    'depends': [
        'hr',
        'hr_payroll',
        ],
    'description': '''

========================

''',    
    'data': [
        'security/ir.model.access.csv',
        'wizard/hr_epayslips_by_employees_view.xml',
        'views/hr_payslip_view.xml',
        'data/epayslip_bach_data.xml'
    ],
    'qweb': [
    ]
}

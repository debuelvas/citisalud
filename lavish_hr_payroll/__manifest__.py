# -*- coding: utf-8 -*-
{
    'name': "lavish_hr_payroll",

    'summary': """
        Módulo de nómina para la localización colombiana | Liquidación de Nómina""",

    'description': """
        Módulo de nómina para la localización colombiana | Liquidación de Nómina
    """,

    'author': "lavish S.A.S",
    
    'category': 'Human Resources',
    "version": "1.0.0",
    'license': 'OPL-1',
    'depends': ['base','hr','hr_payroll','hr_holidays','lavish_erp','lavish_hr_employee','account','web','hr_attendance'],

    # always loaded
   'data': [
        'data/hr_type_tax_retention_data.xml',
        #'data/rtf_ordinario.xml',
        #'data/rule.xml',
        #'data/rule_input.xml',
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
        'views/actions_loans.xml',        
        'views/actions_payslip.xml',
        'views/actions_leave.xml',     
        'views/actions_overtime.xml', 
        'views/actions_concepts_deduction_retention.xml',    
        'views/actions_calculation_rtefte_ordinary.xml', 
        'views/actions_payroll_flat_file.xml',
        'views/actions_payroll_flat_file_backup.xml',
        'views/actions_hr_payroll_posting.xml',
        'views/actions_payroll_report_lavish.xml',
        'views/actions_payroll_vacation.xml',
        'views/actions_voucher_sending.xml',
        'views/actions_novelties_different_concepts.xml',
        'views/actions_hr_novelties_independents.xml',
        'views/actions_hr_accumulated_payroll.xml',
        'views/actions_hr_history_cesantias.xml',
        'views/actions_hr_history_prima.xml',
        'views/actions_hr_work_entry.xml',
        'views/actions_accumulated_reports.xml',
        'views/actions_hr_absence_history.xml',
        'views/actions_hr_consolidated_reports.xml',
        'views/actions_payslip_reports_template.xml',
        'views/actions_hr_transfers_of_entities.xml',
        'views/actions_hr_withholding_and_income_certificate.xml',
        'views/actions_payroll_detail_report.xml',
        'views/actions_hr_auditing_reports.xml',
        'reports/reports_payslip_header_footer_template.xml',
        'reports/report_payslip.xml',
        'reports/report_payslip_vacations_templates.xml',
        'reports/report_payslip_contrato_templates.xml',
        'reports/reports_payslip_header_footer.xml',
        'reports/report_payslip_cesantias_prima_templates.xml',
        'reports/report_book_vacation.xml', 

        'reports/report_book_vacation_template.xml',      
        'reports/report_book_cesantias.xml', 
        'reports/report_book_cesantias_template.xml',
        'reports/hr_report_absenteeism_history.xml',
        'reports/hr_report_absenteeism_history_template.xml',
        'reports/hr_report_income_and_withholdings.xml',
        'reports/hr_report_income_and_withholdings_template.xml',
        'views/actions_report_2276.xml',
        'reports/report_payroll_lavish.xml',
        'views/actions_vacation_book_reports.xml',
        'views/actions_account_journal.xml',
        'views/actions_res_partner.xml',
        'views/actions_hr_absenteeism_history.xml',
        'views/menus.xml',         
        "views/hr_employee_public_views.xml",
    ],
    
}


# -*- coding: utf-8 -*-
# from odoo import http


# class lavish.hrEmployee(http.Controller):
#     @http.route('/lavish_hr_employee/lavish_hr_employee/', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/lavish_hr_employee/lavish_hr_employee/objects/', auth='public')
#     def list(self, **kw):
#         return http.request.render('lavish_hr_employee.listing', {
#             'root': '/lavish_hr_employee/lavish_hr_employee',
#             'objects': http.request.env['lavish_hr_employee.lavish_hr_employee'].search([]),
#         })

#     @http.route('/lavish_hr_employee/lavish_hr_employee/objects/<model("lavish_hr_employee.lavish_hr_employee"):obj>/', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('lavish_hr_employee.object', {
#             'object': obj
#         })

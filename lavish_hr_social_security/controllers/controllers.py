# -*- coding: utf-8 -*-
# from odoo import http


# class lavishHrSocialSecurity(http.Controller):
#     @http.route('/lavish_hr_social_security/lavish_hr_social_security/', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/lavish_hr_social_security/lavish_hr_social_security/objects/', auth='public')
#     def list(self, **kw):
#         return http.request.render('lavish_hr_social_security.listing', {
#             'root': '/lavish_hr_social_security/lavish_hr_social_security',
#             'objects': http.request.env['lavish_hr_social_security.lavish_hr_social_security'].search([]),
#         })

#     @http.route('/lavish_hr_social_security/lavish_hr_social_security/objects/<model("lavish_hr_social_security.lavish_hr_social_security"):obj>/', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('lavish_hr_social_security.object', {
#             'object': obj
#         })

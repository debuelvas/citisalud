# -*- coding: utf-8 -*-
# from odoo import http


# class lavishErp(http.Controller):
#     @http.route('/lavish_erp/lavish_erp/', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/lavish_erp/lavish_erp/objects/', auth='public')
#     def list(self, **kw):
#         return http.request.render('lavish_erp.listing', {
#             'root': '/lavish_erp/lavish_erp',
#             'objects': http.request.env['lavish_erp.lavish_erp'].search([]),
#         })

#     @http.route('/lavish_erp/lavish_erp/objects/<model("lavish_erp.lavish_erp"):obj>/', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('lavish_erp.object', {
#             'object': obj
#         })

import logging

from odoo import api, fields, models, Command
from odoo.exceptions import UserError, ValidationError
_logger = logging.getLogger(__name__)


class ValidateInvoiceCron(models.TransientModel):
    _name = "validate.invoice.cron"
    _description = "Validator Invoice Cron"

    def validate_invoice(self):
        ''' This method is called from a cron job.
        It is used to automatically validate invoices and apply advance payments.
        '''
        # Search for invoices to validate
        inv_to_validate = self.env["account.move"].search([("validate_cron", "=", True),('diancode_id.state','!=','exitoso'),('to_check', '=', False)], limit=100)
        for invoice in inv_to_validate:
            try:
                invoice.validate_dian()
                if invoice.diancode_id.state != 'exitoso':
                    invoice.to_check = True
                self.env.cr.commit()
                        
            except UserError as e:
                invoice.to_check = True
                msg = _('La factura no se pudo validar por el siguiente motivo: %(error_message)s', error_message=e)
                invoice.message_post(body=msg, message_type='comment')
        inv_to_validate = self.env["account.move"].search([("validate_cron", "=", True),('diancode_id','=',False),('to_check', '=', False),('move_type','=','out_invoice'),], limit=100)
        for invoice in inv_to_validate:
            try:
                invoice.validate_dian()
                if invoice.diancode_id.state != 'exitoso':
                    invoice.to_check = True
                self.env.cr.commit()
                        
            except UserError as e:
                invoice.to_check = True
                msg = _('La factura no se pudo validar por el siguiente motivo: %(error_message)s', error_message=e)
                invoice.message_post(body=msg, message_type='comment')
        if len(inv_to_validate) == 100:# or len(inv_to_validate_dian) == 100:  # assumes there are more whenever search hits limit
            self.env.ref('l10n_co_e-invoice.alidate_multiple_invoices_scheduler')._trigger()

    def validate_event(self):
        sql = """SELECT am.id 
                FROM account_move am
                JOIN dian_document dd ON dd.document_id = am.id
                WHERE am.titulo_state != 'green' 
                    AND dd.state = 'exitoso'
                    AND am.move_type = 'out_invoice'
                    AND am.state = 'posted';"""
        self.env.cr.execute(sql)
        sql_result = self.env.cr.dictfetchall()

        # Create batches of 40 records each
        batch_size = 40
        for i in range(0, len(sql_result), batch_size):
            batch = sql_result[i:i + batch_size]
            inv_to_validate_dian = (
                self.env["account.move"].sudo().browse([n.get("id") for n in batch])
            )

            # Process each record in the batch
            for idian in inv_to_validate_dian:
                try:
                    idian.action_GetStatusevent()
                except Exception as e:
                    _logger.info(f"Error processing record {idian.name}: {e}")


# -*- coding: utf-8 -*-

from email.policy import default
from odoo import models, fields, api
from odoo.exceptions import ValidationError

class ValidateInvoice(models.TransientModel):
    _name = 'application.response.wizard'
    _description = "Wizard - Eventos Dian"


    event_type = fields.Selection([
        ('invoice_received', 'Facturas Recibidas'),
        ('invoice_sent', 'Facturas Enviadas')],
        default = lambda self: 'invoice_received' if self._context.get('active_model') == 'recepcion.factura.dian' else 'invoice_sent')
    response_code_invoice_received = fields.Selection([
        ('030','Acuse de recibo de Factura Electrónica de Venta'),
        ('031', 'Reclamo de la Factura Electrónica de Venta'),
        ('032', 'Recibo del bien y/o prestación del servicio'),
        ('033', 'Aceptación expresa'),
        ], string="Evento", required="1")

    response_code_invoice_sent = fields.Selection([
        ('034', 'Aceptación Tácita'),
        ('035', 'Aval'),
        ('036', 'Inscripción de la factura electrónica de venta como título valor - RADIAN'),
        ('037', 'Endoso en Propiedad'),
        ('038', 'Endoso en Garantía'),
        ('039', 'Endoso en Procuración'),
        ('040', 'Cancelación de endoso'),
        ('041', 'Limitaciones a la circulación de la factura electrónica de venta como título'),
        ('042', 'Terminación de las limitaciones a la circulación de la factura electrónica de venta como título'),
        ('043', 'Mandatos'),
        ('044', 'Terminacion del Mandato'),
        ('045', 'Pago de la factura electrónica de venta como título valor'),
        ('046', 'Informe para el pago'),
        ('047', 'Endoso con efectos de cesión ordinaria'),
        ('048', 'Protesto'),
        ('049', 'Transferencia de los derechos económicos'),
        ('050', 'Notificación al deudor sobre la transferencia de los derechos económicos'),
        ('051', 'Pago de la transferencia de los derechos economicos'),
    ], string="Evento Radian")
    notes_xml = fields.Text(compute='_compute_notes_xml')
    ublextension2 = fields.Text(compute='_compute_notes_xml')
    note_1 = fields.Text('Nota 1', compute='_compute_notes', store=True)
    note_2 = fields.Text('Nota 2', compute='_compute_notes', store=True)
    note_2_info = fields.Text('Info Nota 2', compute='_compute_notes')
    note_3 = fields.Text('Nota 3', compute='_compute_notes', store=True)
    note_3_info = fields.Text('Info Nota 3', compute='_compute_notes', )
    note_4 = fields.Text('Nota 4', compute='_compute_notes', store=True)
    note_4_info = fields.Text('Info Nota 4', compute='_compute_notes', )
    note_5 = fields.Text('Nota 5', compute='_compute_notes', store=True)

    ValorFEVavala = fields.Char(compute='_compute_ubl_extension', store=True)

    ValorFEV_TV = fields.Char(compute='_compute_ubl_extension', store=True)
    ValorPagado = fields.Char(compute='_compute_ubl_extension', store=True)
    NuevoValorTV = fields.Char(compute='_compute_ubl_extension', store=True)
    ValorTotalEndoso = fields.Char(compute='_compute_ubl_extension', store=True)
    PrecioPagarseFEV = fields.Char(compute='_compute_ubl_extension', store=True)
    TasaDescuento = fields.Char(compute='_compute_ubl_extension', store=True)
    MedioPago = fields.Char(compute='_compute_ubl_extension', store=True)
    ValorTV = fields.Char(compute='_compute_ubl_extension', store=True)
    MontoMedidaCautelar = fields.Char(compute='_compute_ubl_extension', store=True)
    ValorDeuda = fields.Char(compute='_compute_ubl_extension', store=True)
    ValorLimitación = fields.Char(compute='_compute_ubl_extension', store=True)
    ValorActualTituloValor = fields.Char(compute='_compute_ubl_extension', store=True)
    ValorPendienteTituloValor = fields.Char(compute='_compute_ubl_extension', store=True)
    ValorAceptado = fields.Char(compute='_compute_ubl_extension', store=True)
    ValorPendiente = fields.Char(compute='_compute_ubl_extension', store=True)
    ValorTransferenciaDerechos = fields.Char(compute='_compute_ubl_extension', store=True)
    FactordeDescuento = fields.Char(compute='_compute_ubl_extension', store=True)



    @api.depends('response_code_invoice_received', 'response_code_invoice_sent', 'event_type')
    def _compute_notes(self):
        response_code = self.response_code_invoice_received if self.event_type == 'invoice_received' else self.response_code_invoice_sent
        # primero se pone todo en false por si el evento no lleva notas
        self.note_2_info = False
        self.note_3_info = False
        self.note_4_info = False
        self.note_1 = False
        self.note_2 = False
        self.note_3 = False
        self.note_4 = False
        self.note_5 = False

        model = self._context.get('active_model')
        active_ids = self._context.get('active_ids')
        if model and active_ids:
            rec = self.env[model].browse(active_ids)
            if response_code in ('031', '032', '033', '034', '035', '036', '037', '040', '041', '042', '044', '045', '046'):
                self.note_1 = 'Nombre del Mandatario "OBRANDO EN NOMBRE Y REPRESENTACION DE" Nombre del mandante'
            if response_code == '034':
                if len(rec) > 1:
                    raise ValidationError('Para este evento solo puede seleccionar un documento a la vez')
                partner_id = rec.partner_id
                self.note_2_info = 'Debe existir una Nota cuando este evento sea trasmitido sin mandatario responderá el siguiente mensaje:'
                self.note_2 = f'Manifiesto bajo la gravedad de juramento que transcurridos 3 días hábiles siguientes a la fecha de recepción de la mercancía o del servicio en la referida factura de este evento, el adquirente {partner_id.name} identificado con {partner_id.l10n_latam_identification_type_id.name} {partner_id.vat} no manifestó expresamente la aceptación o rechazo de la referida factura, ni reclamó en contra de su contenido.'
                self.note_3_info = 'Debe existir una Nota cuando un mandatario sea quien transmita este evento a la DIAN responderá el siguiente mensaje:'
                self.note_3 = f'[Razón social / Nombre del mandatario] identificado con NIT / cédula de ciudadanía No. [XXXXX], actuando en nombre y representación de [Razón Social] con Nit [XXXXX], manifiesto bajo la gravedad de juramento que transcurridos 3 días hábiles siguientes a la fecha de recepción de la mercancía o del servicio en la referida factura de este evento,el adquirente {partner_id.name} identificado con {partner_id.l10n_latam_identification_type_id.name} {partner_id.vat} no manifestó expresamente la aceptación o rechazo de la referida factura,ni reclamó en contra de su contenido.'
                self.note_4_info = 'Debe existir una Nota por mandatos sea quien transmita este evento a la DIAN responderá el siguiente mensaje:'
                self.note_4 = f'[razón social / nombre del mandatario] identificado con Nit / cédula de ciudadanía No. [XXXX] obrando en nombre y representación de [nombre de persona natural comerciante] identificado con cédula de ciudadanía No. [XXXXX], con Nit [XXXXX], manifiesta bajo la gravedad de juramento que transcurridos 3 días hábiles siguientes a la fecha de recepción de la mercancía o del servicio en la referida factura de este evento, el adquirente [nombre de persona natural comerciante]{partner_id.name} identificado con {partner_id.l10n_latam_identification_type_id.name} {partner_id.vat}, con {partner_id.l10n_latam_identification_type_id.name} {partner_id.vat} no manifestó expresamente la aceptación o rechazo de la referida factura, ni reclamó en contra de su contenido.'
            if response_code == '035': # Aval
                self.note_2 = f'XXXX, identificado con (documento de identidad) No. ___________________, manifiesto expresamente que con la inclusión de mi firma en el presente documento actúo por aval de __________________________** respecto de la(s) Factura(s) Electrónica(s) de Venta como Título Valor identificada(s) con el(los) CUFE No. {rec.diancode_id.cufe}, de forma total/parcial '
                self.note_3 = f'XXXX, identificado con (documento de identidad) No. ___________________, obrando en mi calidad de gerente/representante legal de la sociedad __________________________, NIT ______________________________, según consta en el certificado de existencia y representación legal expedido por la Cámara de Comercio de ______________________________ y de conformidad con lo previsto en el objeto social, las facultades estatutarias/otorgadas por el máximo órgano social, manifiesto expresamente que con la inclusión de mi firma en el presente documento actúo por aval de ___________________________ respecto de la(s) Factura(s) Electrónica(s) de Venta como Título Valor identificada(s) con el(los) CUFE No.{rec.diancode_id.cufe}, de forma total/parcial'
                self.valor = rec.total # poner valor de la factura
            if response_code == '036':
                self.note_2 = 'Condiciones para el pago'
            if response_code == '037':
                self.note_2 = '"sin mi responsabilidad" u otra equivalente'
            if response_code == '038':
                self.note_1 = 'PT SAS OBRANDO EN NOMBRE Y REPRESENTACION DE FACTURA ELECTRONICA USUARIO PRUEBAS MIGRACION'
                self.note_2 = '"en garantía", "en prenda" u otra equivalente'
            if response_code == '039':
                self.note_1 = 'PT SAS OBRANDO EN NOMBRE Y REPRESENTACION DE FACTURA ELECTRONICA USUARIO PRUEBAS MIGRACION'
                self.note_2 = '"en procuración", "al cobro" u otra equivalente'
            if response_code == '040':
                self.note_2 = 'Yo Nombre del Emisor/Tenedor Legitimo doy por terminado el endoso No.__________, por el motivo_________'
            if response_code == '043':
                self.note_1 = 'XXXX, identificado con la cédula de ciudadanía (o el documento de identificación que corresponda) No. XXXX, expresamente manifiesto que obro en nombre y representación de YYYY, de conformidad con el contrato de mandato verbal/escrito existente entre las partes y con las facultades señaladas en el presente documento y por el tiempo consignado en este/sin limitaciones de tiempo'
                self.note_2 = 'XXXX, identificado con la cédula de ciudadanía (o el documento de identificación que corresponda) No. XXXX, en mi calidad de representante legal de la sociedad XXXX, según consta en el certificado de existencia y representación legal expedido por la Cámara de Comercio de XXXX, expresamente manifiesto que obro en nombre y representación de YYYY, de conformidad con el contrato de mandato verbal/escrito existente entre las partes y con las facultades señaladas en el presente documento y por el tiempo consignado en este/sin limitaciones de tiempo.'
            if response_code == '044':
                self.note_2 = 'Constancia de que no se encuentra pendiente de ejecución ningún acto en virtud del mandato que se cancela'
                self.note_3 = 'Nota en relacion con la ratificacion de los actos realizados por el mandatario'
            if response_code == '048':
                self.note_1 = '"Con protesto"'
            if response_code == '049':
                self.note_1 = 'Manifiesto bajo la gravedad de juramento, que entre... [Nombre o razón social] identificado con [Tipo y número de documento], en calidad de cedente y [Nombre o razón social] identificado con [Tipo y número de documento], en calidad de cesionario, se suscribió un contrato de cesión de derechos económicos, dando cumplimiento a los términos y condiciones establecidos en el Código Civil.'

    def _compute_notes_xml(self):
        nota  = ''
        nota_compute = f'''
        <cbc:Note>{nota}</cbc:Note>
        '''
        self.notes_xml = nota

    def validate_event(self):
        model = self._context.get('active_model')
        active_ids = self._context.get('active_ids')
        if model == 'recepcion.factura.dian' and active_ids:
            for rec in self.env[model].browse(active_ids):
                rec.with_context({
                    'wizard': self,
                    'response_code': self.response_code_invoice_received,
                    'notes': []
                    }).add_application_response()
            return True
        elif model == 'account.move':
            for rec in self.env[model].browse(active_ids):
                rec.with_context({
                    'response_code': self.response_code_invoice_sent,
                    'wizard': self,
                    }).add_application_response()
            return True
        raise ValidationError('Error, acción no implementada')

    def _compute_ubl_extension(self):
        for rec in self:
            response_code = rec.response_code_invoice_received if rec.event_type == 'invoice_received' else rec.response_code_invoice_sent
            if response_code == '035':
                f'''<ext:UBLExtension>
                        <ext:ExtensionContent>
                            <CustomTagGeneral>
                                <InformacionAvalar>
                                    <Name>ValorFEVavala</Name>
                                    <Value>{self.ValorFEVavala or ''}</Value>
                                </InformacionAvalar>
                            </CustomTagGeneral>
                        </ext:ExtensionContent>
                    </ext:UBLExtension>'''

            if response_code == '036':
                f'''<ext:UBLExtension>
                        <ext:ExtensionContent>
                            <CustomTagGeneral>
                                <ConstanciadePagos>
                                    <Name>ValorFEV-TV</Name>
                                    <Value>{self.ValorFEV_TV or ''}</Value>
                                    <Name>ValorPagado</Name>
                                    <Value>{self.ValorPagado or ''}</Value>
                                    <Name>NuevoValorTV</Name>
                                    <Value>{self.ValorTV or ''}</Value>
                                </ConstanciadePagos>
                            </CustomTagGeneral>
                        </ext:ExtensionContent>
                    </ext:UBLExtension>'''

            if response_code in ('037', '038', '039', '047') :
                f'''<ext:UBLExtension>
                        <ext:ExtensionContent>
                            <CustomTagGeneral>
                                <InformacionNegociacion>
                                    <Name>ValorTotalEndoso</Name>
                                    <Value>{self.ValorTotalEndoso or ''}</Value>
                                    <Name>PrecioPagarseFEV</Name>
                                    <Value>{self.PrecioPagarseFEV or ''}</Value>
                                    <Name>TasaDescuento</Name>
                                    <Value>{self.TasaDescuento or ''}</Value>
                                    <Name>MedioPago</Name>
                                    <Value>{self.MedioPago or ''}</Value>
                                </InformacionNegociacion>
                            </CustomTagGeneral>
                        </ext:ExtensionContent>
                    </ext:UBLExtension>'''

            if response_code == '041':
                f'''<ext:UBLExtension>
                        <ext:ExtensionContent>
                            <CustomTagGeneral>
                                <InformacionMedidaCautelar>
                                    <Name>MontoMedidaCautelar</Name>
                                    <Value>{self.MontoMedidaCautelar or ''}</Value>
                                </InformacionMedidaCautelar>
                            </CustomTagGeneral>
                        </ext:ExtensionContent>
                    </ext:UBLExtension>'''

            if  response_code == '042':
                f'''<ext:UBLExtension>
                        <ext:ExtensionContent>
                            <CustomTagGeneral>
                                <InformacionMedidaCautelar>
                                    <Name>ValorDeuda</Name>
                                    <Value>{self.ValorDeuda or ''}</Value>
                                    <Name>ValorLimitación</Name>
                                    <Value>{self.ValorLimitación or ''}</Value>
                                </InformacionMedidaCautelar>
                            </CustomTagGeneral>
                        </ext:ExtensionContent>
                    </ext:UBLExtension>'''

            if  response_code == '045':
                f'''<ext:UBLExtension>
                        <ext:ExtensionContent>
                            <CustomTagGeneral>
                                <InformacionPagos>
                                    <Name>ValorActualTituloValor</Name>
                                    <Value>{self.ValorActualTituloValor or ''}</Value>
                                    <Name>ValorPendienteTituloValor</Name>
                                    <Value>{self.ValorPendienteTituloValor or ''}</Value>
                                </InformacionPagos>
                            </CustomTagGeneral>
                        </ext:ExtensionContent>
                    </ext:UBLExtension>'''

            if  response_code == '046':
                f'''<ext:UBLExtension>
                        <ext:ExtensionContent>
                            <CustomTagGeneral>
                                <InformacionParaelPago>
                                    <Name>ValorFEV-TV</Name>
                                    <Value>{self.ValorFEV_TV or ''}</Value>
                                </InformacionParaelPago>
                            </CustomTagGeneral>
                        </ext:ExtensionContent>
                    </ext:UBLExtension>'''

            if  response_code == '048':
                f'''<ext:UBLExtension>
                        <ext:ExtensionContent>
                            <CustomTagGeneral>
                                <InformacionProtesto>
                                    <Name>ValorFEV-TV</Name>
                                    <Value>{self.ValorFEV_TV or ''}</Value>
                                    <Name>ValorAceptado</Name>
                                    <Value>{self.ValorAceptado or ''}</Value>
                                    <Name>ValorPendiente</Name>
                                    <Value>{self.ValorPendiente or ''}</Value>
                                </InformacionProtesto>
                            </CustomTagGeneral>
                        </ext:ExtensionContent>
                    </ext:UBLExtension>'''

            if  response_code == '049':
                f'''<ext:UBLExtension>
                        <ext:ExtensionContent>
                            <CustomTagGeneral>
                                <InformacionTransferenciaDerechos>
                                    <Name>ValorTransferenciaDerechos</Name>
                                    <Value>{self.ValorTransferenciaDerechos or ''}</Value>
                                    <Name>PrecioPagarseFEV</Name>
                                    <Value>{self.PrecioPagarseFEV or ''}</Value>
                                    <Name>FactordeDescuento</Name>
                                    <Value>{self.FactordeDescuento or ''}</Value>
                                    <Name>MedioPago</Name>
                                    <Value>{self.MedioPago or ''}</Value>
                                </InformacionTransferenciaDerechos>
                            </CustomTagGeneral>
                        </ext:ExtensionContent>
                    </ext:UBLExtension>'''

            if  response_code == '050':
                f'''<ext:UBLExtension>
                        <ext:ExtensionContent>
                            <CustomTagGeneral>
                                <NotificacionPagoDeudor>
                                    <Name>ValorFEV-TV</Name>
                                    <Value>{self.ValorFEV_TV or ''}</Value>
                                </NotificacionPagoDeudor>
                            </CustomTagGeneral>
                        </ext:ExtensionContent>
                    </ext:UBLExtension>'''

            if  response_code == '051':
                f'''<ext:UBLExtension>
                        <ext:ExtensionContent>
                            <CustomTagGeneral>
                                <InformacionPagoTransferencia>
                                    <Name>ValorActualTituloValor</Name>
                                    <Value>{self.ValorActualTituloValor or ''}</Value>
                                    <Name>ValorPendienteTituloValor</Name>
                                    <Value>{self.ValorPendienteTituloValor or ''}</Value>
                                </InformacionPagoTransferencia>
                            </CustomTagGeneral>
                        </ext:ExtensionContent>
                    </ext:UBLExtension>'''





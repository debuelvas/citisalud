
from odoo import  _, api, fields, models, tools
import xml.etree.ElementTree as ET
from lxml import etree
import logging
_logger = logging.getLogger(__name__)
class DianDocument(models.Model):
    _inherit = "dian.document"

    def generate_xml_invoice(self, template_data):
        if self.document_id.move_type == 'in_invoice':
            return self._create_ds_xml(template_data)
        elif self.document_id.move_type == 'out_invoice':
            return self._create_xml_invoice(template_data)

    def _create_xml_invoice(self, template_data):
        # Crear el elemento raíz 'Invoice'
        root = ET.Element('Invoice')
        root.set('xmlns', 'urn:oasis:names:specification:ubl:schema:xsd:Invoice-2')
        root.set('xmlns:cac', 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2')
        root.set('xmlns:cbc', 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2')
        root.set('xmlns:ds', 'http://www.w3.org/2000/09/xmldsig#')
        root.set('xmlns:ext', 'urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2')
        root.set('xmlns:sts', 'http://www.dian.gov.co/contratos/facturaelectronica/v1/Structures')
        root.set('xmlns:xsi', 'http://www.w3.org/2001/XMLSchema-instance')
        root.set('xsi:schemaLocation', 'urn:oasis:names:specification:ubl:schema:xsd:Invoice-2    http://docs.oasis-open.org/ubl/os-UBL-2.1/xsd/maindoc/UBL-Invoice-2.1.xsd')
        # Crear el elemento 'ext:UBLExtensions'
        ext_ubl_extensions = ET.SubElement(root, 'ext:UBLExtensions')
        # Crear el primer 'ext:UBLExtension'
        ext_ubl_extension1 = ET.SubElement(ext_ubl_extensions, 'ext:UBLExtension')
        ext_extension_content1 = ET.SubElement(ext_ubl_extension1, 'ext:ExtensionContent')
        sts_dian_extensions = ET.SubElement(ext_extension_content1, 'sts:DianExtensions')
        # Agregar los elementos y valores dentro de 'sts:DianExtensions'
        sts_invoice_control = ET.SubElement(sts_dian_extensions, 'sts:InvoiceControl')
        ET.SubElement(sts_invoice_control, 'sts:InvoiceAuthorization').text = str(template_data['InvoiceAuthorization'])
        sts_authorization_period = ET.SubElement(sts_invoice_control, 'sts:AuthorizationPeriod')
        ET.SubElement(sts_authorization_period, 'cbc:StartDate').text = str(template_data['StartDate'])
        ET.SubElement(sts_authorization_period, 'cbc:EndDate').text = str(template_data['EndDate'])
        sts_authorized_invoices = ET.SubElement(sts_invoice_control, 'sts:AuthorizedInvoices')
        ET.SubElement(sts_authorized_invoices, 'sts:Prefix').text = str(template_data['Prefix'])
        ET.SubElement(sts_authorized_invoices, 'sts:From').text = str(template_data['From'])
        ET.SubElement(sts_authorized_invoices, 'sts:To').text = str(template_data['To'])
        sts_invoice_source = ET.SubElement(sts_dian_extensions, 'sts:InvoiceSource')
        
        ET.SubElement(sts_invoice_source, 'cbc:IdentificationCode', attrib={
            'listAgencyID': '6',
            'listAgencyName': 'United Nations Economic Commission for Europe',
            'listSchemeURI': 'urn:oasis:names:specification:ubl:codelist:gc:CountryIdentificationCode-2.1'
        }).text = str(template_data['IdentificationCode'])
        sts_software_provider = ET.SubElement(sts_dian_extensions, 'sts:SoftwareProvider')
        ET.SubElement(sts_software_provider, 'sts:ProviderID', attrib={
            'schemeAgencyID': '195',
            'schemeAgencyName': 'CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)',
            'schemeID': str(template_data['SoftwareProviderSchemeID']),
            'schemeName': '31'
        }).text = str(template_data['SoftwareProviderID'])
        ET.SubElement(sts_software_provider, 'sts:SoftwareID', attrib={
            'schemeAgencyID': '195',
            'schemeAgencyName': 'CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)'
        }).text = str(template_data['SoftwareID'])
        ET.SubElement(sts_dian_extensions, 'sts:SoftwareSecurityCode', attrib={
            'schemeAgencyID': '195',
            'schemeAgencyName': 'CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)'
        }).text = str(template_data['SoftwareSecurityCode'])
        sts_authorization_provider = ET.SubElement(sts_dian_extensions, 'sts:AuthorizationProvider')
        ET.SubElement(sts_authorization_provider, 'sts:AuthorizationProviderID', attrib={
            'schemeAgencyID': '195',
            'schemeAgencyName': 'CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)',
            'schemeID': '4',
            'schemeName': '31'
        }).text = '800197268'
        
        qrcode_text = f"NroFactura={template_data['InvoiceID']} \n NitFacturador={template_data['SoftwareProviderID']} \n NitAdquiriente={template_data['IDAdquiriente']} \n FechaFactura={template_data['IssueDate']} \n ValorTotalFactura={template_data['PayableAmount']} \n CUFE={template_data['UUID']}  \n URL={str(template_data['URLQRCode'])}={str(template_data['UUID'])}"
        qrcode_element = ET.SubElement(sts_dian_extensions, 'sts:QRCode')
        qrcode_element.text = qrcode_text
        # Crear Op
        if self.document_id.currency_id.name != 'COP':
            ext_ubl_extensionc = ET.SubElement(ext_ubl_extensions, 'ext:UBLExtension')
            content = ET.SubElement(ext_ubl_extensionc, 'ext:ExtensionContent')
            custom_tag = ET.SubElement(content, 'CustomTagGeneral')

            interoperabilidad = ET.SubElement(custom_tag, 'Interoperabilidad')
            group = ET.SubElement(interoperabilidad, 'Group', {'schemeName': 'Factura de Venta'})
            collection = ET.SubElement(group, 'Collection', {'schemeName': 'DATOS ADICIONALES'})

            info = ET.SubElement(collection, 'AdditionalInformation')
            ET.SubElement(info, 'name').text = 'Observaciones'
            ET.SubElement(info, 'value').text = 'Observaciones'

            totales_cop = ET.SubElement(custom_tag, 'TotalesCop')
            ET.SubElement(totales_cop, 'FctConvCop').text = '%0.2f' % float(self.document_id.current_exchange_rate)
            ET.SubElement(totales_cop, 'MonedaCop').text = self.document_id.currency_id.name
            ET.SubElement(totales_cop, 'SubTotalCop').text = f"{float(template_data['TotalLineExtensionAmount'])/ self.document_id.current_exchange_rate:.2f}"
            ET.SubElement(totales_cop, 'TotalBrutoFacturaCop').text = f"{float(template_data['TotalLineExtensionAmount'])/ self.document_id.current_exchange_rate:.2f}"
            ET.SubElement(totales_cop, 'TotIvaCop').text = f"{template_data['tot_iva_cop'] / self.document_id.current_exchange_rate:.2f}"
            ET.SubElement(totales_cop, 'TotalNetoFacturaCop').text = f"{float(template_data['TotalTaxExclusiveAmount']) / self.document_id.current_exchange_rate:.2f}"
            ET.SubElement(totales_cop, 'VlrPagarCop').text = f"{float(template_data['PayableAmount'])/ self.document_id.current_exchange_rate:.2f}"
            ET.SubElement(totales_cop, 'ReteFueCop').text = f"{template_data['rete_fue_cop'] / self.document_id.current_exchange_rate:.2f}"
            ET.SubElement(totales_cop, 'ReteIvaCop').text = f"{template_data['rete_iva_cop'] / self.document_id.current_exchange_rate:.2f}"
        # Crear el segundo 'ext:UBLExtension'
        ext_ubl_extension2 = ET.SubElement(ext_ubl_extensions, 'ext:UBLExtension')
        ET.SubElement(ext_ubl_extension2, 'ext:ExtensionContent')
   

        # Agregar los elementos y valores restantes
        ET.SubElement(root, 'cbc:UBLVersionID').text = str(template_data['UBLVersionID'])
        ET.SubElement(root, 'cbc:CustomizationID').text = str(template_data['CustomizationID'])
        ET.SubElement(root, 'cbc:ProfileID').text = str(template_data['ProfileID'])
        ET.SubElement(root, 'cbc:ProfileExecutionID').text = str(template_data['ProfileExecutionID'])
        ET.SubElement(root, 'cbc:ID').text = str(template_data['InvoiceID'])
        ET.SubElement(root, 'cbc:UUID', attrib={
            'schemeID': str(template_data['ProfileExecutionID']),
            'schemeName': 'CUFE-SHA384'
        }).text = str(template_data['UUID'])
        ET.SubElement(root, 'cbc:IssueDate').text = str(template_data['IssueDate'])
        ET.SubElement(root, 'cbc:IssueTime').text = str(template_data['IssueTime'])
        ET.SubElement(root, 'cbc:InvoiceTypeCode').text = str(template_data['InvoiceTypeCode'])
        ET.SubElement(root, 'cbc:Note').text = str(template_data['Notes'])
        if template_data['CurrencyID'] != 'COP':
            ET.SubElement(root, 'cbc:DocumentCurrencyCode', attrib={
            'listAgencyID': '6',
            'listAgencyName': 'United Nations Economic Commission for Europe',
            'listID':'ISO 4217 Alpha'}).text = str(template_data['DocumentCurrencyCode'])
        else:
            ET.SubElement(root, 'cbc:DocumentCurrencyCode').text = 'COP'
        ET.SubElement(root, 'cbc:LineCountNumeric').text = str(template_data['LineCountNumeric'])
        if self.document_id.ref:
            cac_order_ref = ET.SubElement(root, 'cac:OrderReference')
            ET.SubElement(cac_order_ref, 'cbc:ID').text = str(self.document_id.ref)
        #receipt
        if self.document_id.receipts:
            for receipt in self.document_id.receipts:
                cac_receipt_doc_ref = ET.SubElement(root, 'cac:ReceiptDocumentReference')
                ET.SubElement(cac_receipt_doc_ref, 'cbc:ID').text = receipt.name
        # Agregar los elementos y valores de 'cac:AccountingSupplierParty'
        cac_accounting_supplier_party = ET.SubElement(root, 'cac:AccountingSupplierParty')
        ET.SubElement(cac_accounting_supplier_party, 'cbc:AdditionalAccountID').text = str(template_data['SupplierAdditionalAccountID'])
        cac_party = ET.SubElement(cac_accounting_supplier_party, 'cac:Party')
        ET.SubElement(cac_party, 'cbc:IndustryClassificationCode').text = str(template_data['IndustryClassificationCode'])
        cac_party_name = ET.SubElement(cac_party, 'cac:PartyName')
        ET.SubElement(cac_party_name, 'cbc:Name').text = str(template_data['SupplierPartyName'])
        cac_physical_location = ET.SubElement(cac_party, 'cac:PhysicalLocation')
        cac_address = ET.SubElement(cac_physical_location, 'cac:Address')
        ET.SubElement(cac_address, 'cbc:ID').text = str(template_data['SupplierCityCode'])
        ET.SubElement(cac_address, 'cbc:CityName').text = str(template_data['SupplierCityName'])
        ET.SubElement(cac_address, 'cbc:CountrySubentity').text = str(template_data['SupplierCountrySubentity'])
        ET.SubElement(cac_address, 'cbc:CountrySubentityCode').text = str(template_data['SupplierCountrySubentityCode'])
        cac_address_line = ET.SubElement(cac_address, 'cac:AddressLine')
        ET.SubElement(cac_address_line, 'cbc:Line').text = str(template_data['SupplierLine'])
        cac_country = ET.SubElement(cac_address, 'cac:Country')
        ET.SubElement(cac_country, 'cbc:IdentificationCode').text = str(template_data['SupplierCountryCode'])
        ET.SubElement(cac_country, 'cbc:Name', attrib={'languageID': 'es'}).text = str(template_data['SupplierCountryName'])
        cac_party_tax_scheme = ET.SubElement(cac_party, 'cac:PartyTaxScheme')
        ET.SubElement(cac_party_tax_scheme, 'cbc:RegistrationName').text = str(template_data['SupplierPartyName'])
        ET.SubElement(cac_party_tax_scheme, 'cbc:CompanyID', attrib={
            'schemeAgencyID': '195',
            'schemeAgencyName': 'CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)',
            'schemeID': str(template_data['schemeID']),
            'schemeName': '31'
        }).text = str(template_data['ProviderID'])
        ET.SubElement(cac_party_tax_scheme, 'cbc:TaxLevelCode', attrib={'listName': '48'}).text = str(template_data['SupplierTaxLevelCode'])
        cac_registration_address = ET.SubElement(cac_party_tax_scheme, 'cac:RegistrationAddress')
        ET.SubElement(cac_registration_address, 'cbc:ID').text = str(template_data['SupplierCityCode'])
        ET.SubElement(cac_registration_address, 'cbc:CityName').text = str(template_data['SupplierCityName'])
        ET.SubElement(cac_registration_address, 'cbc:CountrySubentity').text = str(template_data['SupplierCountrySubentity'])
        ET.SubElement(cac_registration_address, 'cbc:CountrySubentityCode').text = str(template_data['SupplierCountrySubentityCode'])
        cac_address_line = ET.SubElement(cac_registration_address, 'cac:AddressLine')
        ET.SubElement(cac_address_line, 'cbc:Line').text = str(template_data['SupplierLine'])
        cac_country = ET.SubElement(cac_registration_address, 'cac:Country')
        ET.SubElement(cac_country, 'cbc:IdentificationCode').text = str(template_data['SupplierCountryCode'])
        ET.SubElement(cac_country, 'cbc:Name', attrib={'languageID': 'es'}).text = str(template_data['SupplierCountryName'])
        cac_tax_scheme = ET.SubElement(cac_party_tax_scheme, 'cac:TaxScheme')
        ET.SubElement(cac_tax_scheme, 'cbc:ID').text = str(template_data['TaxSchemeID'])
        ET.SubElement(cac_tax_scheme, 'cbc:Name').text = str(template_data['TaxSchemeName'])
        cac_party_legal_entity = ET.SubElement(cac_party, 'cac:PartyLegalEntity')
        ET.SubElement(cac_party_legal_entity, 'cbc:RegistrationName').text = str(template_data['SupplierPartyName'])
        ET.SubElement(cac_party_legal_entity, 'cbc:CompanyID', attrib={
            'schemeAgencyID': '195',
            'schemeAgencyName': 'CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)',
            'schemeID': str(template_data['schemeID']),
            'schemeName': '31'
        }).text = str(template_data['ProviderID'])
        cac_corporate_registration_scheme = ET.SubElement(cac_party_legal_entity, 'cac:CorporateRegistrationScheme')
        ET.SubElement(cac_corporate_registration_scheme, 'cbc:ID').text = str(template_data['Prefix'])

        cac_contact = ET.SubElement(cac_party, 'cac:Contact')
        ET.SubElement(cac_contact, 'cbc:ElectronicMail').text = str(template_data['SupplierElectronicMail'])

        # Agregar los elementos y valores de 'cac:AccountingCustomerParty'
        cac_accounting_customer_party = ET.SubElement(root, 'cac:AccountingCustomerParty')
        ET.SubElement(cac_accounting_customer_party, 'cbc:AdditionalAccountID').text = str(template_data['CustomerAdditionalAccountID'])
        cac_party = ET.SubElement(cac_accounting_customer_party, 'cac:Party')
        cac_party_identification = ET.SubElement(cac_party, 'cac:PartyIdentification')
        ET.SubElement(cac_party_identification, 'cbc:ID', attrib={
            'schemeName': str(template_data['SchemeNameAdquiriente']),
            'schemeID': str(template_data['SchemeIDAdquiriente'])
        }).text = str(template_data['IDAdquiriente'])
        cac_party_name = ET.SubElement(cac_party, 'cac:PartyName')
        ET.SubElement(cac_party_name, 'cbc:Name').text = str(template_data['CustomerPartyName'])
        cac_physical_location = ET.SubElement(cac_party, 'cac:PhysicalLocation')
        cac_address = ET.SubElement(cac_physical_location, 'cac:Address')
        ET.SubElement(cac_address, 'cbc:ID').text = str(template_data['CustomerCityCode'])
        ET.SubElement(cac_address, 'cbc:CityName').text = str(template_data['CustomerCityName'])
        ET.SubElement(cac_address, 'cbc:CountrySubentity').text = str(template_data['CustomerCountrySubentity'])
        ET.SubElement(cac_address, 'cbc:CountrySubentityCode').text = str(template_data['CustomerCountrySubentityCode'])
        cac_address_line = ET.SubElement(cac_address, 'cac:AddressLine')
        ET.SubElement(cac_address_line, 'cbc:Line').text = str(template_data['CustomerLine'])
        cac_country = ET.SubElement(cac_address, 'cac:Country')
        ET.SubElement(cac_country, 'cbc:IdentificationCode').text = str(template_data['CustomerCountryCode'])
        ET.SubElement(cac_country, 'cbc:Name', attrib={'languageID': 'es'}).text = str(template_data['CustomerCountryName'])
        cac_party_tax_scheme = ET.SubElement(cac_party, 'cac:PartyTaxScheme')
        ET.SubElement(cac_party_tax_scheme, 'cbc:RegistrationName').text = str(template_data['CustomerPartyName'])
        if template_data['SchemeNameAdquiriente'] == '31':
            ET.SubElement(cac_party_tax_scheme, 'cbc:CompanyID', attrib={
                'schemeAgencyID': '195',
                'schemeAgencyName': 'CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)',
                'schemeID': str(template_data['CustomerschemeID']),
                'schemeName': str(template_data['SchemeNameAdquiriente']),
            }).text = str(template_data['CustomerID'])
        else:
            ET.SubElement(cac_party_tax_scheme, 'cbc:CompanyID', attrib={
                'schemeAgencyID': '195',
                'schemeAgencyName': 'CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)',
                'schemeName': str(template_data['SchemeNameAdquiriente']),
            }).text = str(template_data['CustomerID'])
        ET.SubElement(cac_party_tax_scheme, 'cbc:TaxLevelCode', attrib={'listName': '48'}).text = str(template_data['CustomerTaxLevelCode'])
        cac_registration_address = ET.SubElement(cac_party_tax_scheme, 'cac:RegistrationAddress')
        ET.SubElement(cac_registration_address, 'cbc:ID').text = str(template_data['CustomerCityCode'])
        ET.SubElement(cac_registration_address, 'cbc:CityName').text = str(template_data['CustomerCityName'])
        ET.SubElement(cac_registration_address, 'cbc:CountrySubentity').text = str(template_data['CustomerCountrySubentity'])
        ET.SubElement(cac_registration_address, 'cbc:CountrySubentityCode').text = str(template_data['CustomerCountrySubentityCode'])
        cac_address_line = ET.SubElement(cac_registration_address, 'cac:AddressLine')
        ET.SubElement(cac_address_line, 'cbc:Line').text = str(template_data['CustomerLine'])
        cac_country = ET.SubElement(cac_registration_address, 'cac:Country')
        ET.SubElement(cac_country, 'cbc:IdentificationCode').text = str(template_data['CustomerCountryCode'])
        ET.SubElement(cac_country, 'cbc:Name', attrib={'languageID': 'es'}).text = str(template_data['CustomerCountryName'])

        cac_tax_scheme = ET.SubElement(cac_party_tax_scheme, 'cac:TaxScheme')
        ET.SubElement(cac_tax_scheme, 'cbc:ID').text = str(template_data['CustomerTaxSchemeID'])
        ET.SubElement(cac_tax_scheme, 'cbc:Name').text = str(template_data['CustomerTaxSchemeName'])

        cac_party_legal_entity = ET.SubElement(cac_party, 'cac:PartyLegalEntity')
        ET.SubElement(cac_party_legal_entity, 'cbc:RegistrationName').text = str(template_data['CustomerPartyName'])
        if template_data['SchemeNameAdquiriente'] == '31':
            ET.SubElement(cac_party_legal_entity, 'cbc:CompanyID', attrib={
                'schemeAgencyID': '195',
                'schemeAgencyName': 'CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)',
                'schemeID': str(template_data['CustomerschemeID']),
                'schemeName': str(template_data['SchemeNameAdquiriente']),
            }).text = str(template_data['CustomerID'])
        else:
            ET.SubElement(cac_party_legal_entity, 'cbc:CompanyID', attrib={
                'schemeAgencyID': '195',
                'schemeAgencyName': 'CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)',
                'schemeName': str(template_data['SchemeNameAdquiriente']),
            }).text = str(template_data['CustomerID'])
        # Agregar los elementos y valores de 'cac:Delivery'
        cac_Delivery = ET.SubElement(root, 'cac:Delivery')
        cac_Delivery_address = ET.SubElement(cac_Delivery, 'cac:DeliveryAddress')
        partner_for_city = self.document_id.partner_shipping_id if self.document_id.partner_shipping_id.city_id else self.document_id.partner_id
        if partner_for_city.city_id:
            ET.SubElement(cac_Delivery_address, 'cbc:ID').text = str(self._replace_character_especial(partner_for_city.city_id.code))
        if partner_for_city.city_id:
            ET.SubElement(cac_Delivery_address, 'cbc:CityName').text = str(self._replace_character_especial(partner_for_city.city_id.name))
        if partner_for_city.state_id:
            ET.SubElement(cac_Delivery_address, 'cbc:CountrySubentity').text = str(self._replace_character_especial(partner_for_city.state_id.name))
        if partner_for_city.state_id:
            ET.SubElement(cac_Delivery_address, 'cbc:CountrySubentityCode').text = str(self._replace_character_especial(partner_for_city.state_id.code_dian))
        cac_delivery_address_line = ET.SubElement(cac_Delivery_address, 'cac:AddressLine')
        ET.SubElement(cac_delivery_address_line, 'cbc:Line').text =  str(self._replace_character_especial(partner_for_city.street))
        cac_delivery_country = ET.SubElement(cac_Delivery_address, 'cac:Country')
        ET.SubElement(cac_delivery_country, 'cbc:IdentificationCode').text = str(template_data['CustomerCountryCode'])
        ET.SubElement(cac_delivery_country, 'cbc:Name', attrib={'languageID': 'es'}).text = str(template_data['CustomerCountryName'])
         # Agregar los elementos y valores de 'cac:Contact'
        cac_contact = ET.SubElement(cac_party, 'cac:Contact')
        ET.SubElement(cac_contact, 'cbc:Name').text = str(self._replace_character_especial(self.document_id.partner_contact_id.name))
        ET.SubElement(cac_contact, 'cbc:Telephone').text = str(self._replace_character_especial(self.document_id.partner_contact_id.phone))
        ET.SubElement(cac_contact, 'cbc:ElectronicMail').text = str(template_data['CustomerElectronicMail'])

        cac_person = ET.SubElement(cac_party, 'cac:Person')
        ET.SubElement(cac_person, 'cbc:FirstName').text = str(template_data['Firstname'])

        # Agregar los elementos y valores de 'cac:PaymentMeans'
        cac_payment_means = ET.SubElement(root, 'cac:PaymentMeans')
        ET.SubElement(cac_payment_means, 'cbc:ID').text = str(template_data['PaymentMeansID'])
        ET.SubElement(cac_payment_means, 'cbc:PaymentMeansCode').text = str(template_data['PaymentMeansCode'])
        ET.SubElement(cac_payment_means, 'cbc:PaymentDueDate').text = str(template_data['PaymentDueDate'])
        ET.SubElement(cac_payment_means, 'cbc:PaymentID').text = '1234'
        # Agregar los elementos y valores de 'cac:PaymentMeans'
        if self.document_id.invoice_discount != 0:
            cac_AllowanceCharge = ET.SubElement(root, 'cac:AllowanceCharge')
            ET.SubElement(cac_AllowanceCharge, 'cbc:ID').text = '1'
            ET.SubElement(cac_AllowanceCharge, 'cbc:ChargeIndicator').text = 'false'
            ET.SubElement(cac_AllowanceCharge, 'cbc:AllowanceChargeReasonCode').text = str('01')
            ET.SubElement(cac_AllowanceCharge, 'cbc:AllowanceChargeReason').text = str(self.document_id.razon_descuento)
            ET.SubElement(cac_AllowanceCharge, 'cbc:MultiplierFactorNumeric').text = '{:.2f}'.format((self.document_id.invoice_discount / (self.document_id.amount_untaxed + self.document_id.invoice_discount))*100)
            ET.SubElement(cac_AllowanceCharge, 'cbc:Amount', attrib={'currencyID': str(template_data['CurrencyID'])}).text = '{:.2f}'.format(self.document_id.invoice_discount) 
            ET.SubElement(cac_AllowanceCharge, 'cbc:BaseAmount', attrib={'currencyID': str(template_data['CurrencyID'])}).text = '{:.2f}'.format(self.document_id.amount_untaxed + self.document_id.invoice_discount)
            # Agregar el ajuste de redondeo si existe
        if template_data['rounding_adjustment_data']:
            self._add_rounding_adjustment(root, template_data['rounding_adjustment_data'])
        if self.document_id.currency_id.name != 'COP':
            # Agregar los elementos y valores de 'cac:PaymentExchangeRate'
            cac_payment_exchange_rate = ET.SubElement(root, 'cac:PaymentExchangeRate')
            ET.SubElement(cac_payment_exchange_rate, 'cbc:SourceCurrencyCode').text = str(template_data['CurrencyID'])
            ET.SubElement(cac_payment_exchange_rate, 'cbc:SourceCurrencyBaseRate').text = '%0.2f' % float(self.document_id.current_exchange_rate)
            ET.SubElement(cac_payment_exchange_rate, 'cbc:TargetCurrencyCode').text = self.document_id.currency_id.name
            ET.SubElement(cac_payment_exchange_rate, 'cbc:TargetCurrencyBaseRate').text = '1.00'
            ET.SubElement(cac_payment_exchange_rate, 'cbc:CalculationRate').text = '%0.2f' % float(self.document_id.current_exchange_rate)
            ET.SubElement(cac_payment_exchange_rate, 'cbc:Date').text = str(template_data['DateRate'])
        
        #Data Taxes
        ET.SubElement(root, 'data_taxs_xml')
        
        #Legal Monetary Total
        cac_legal_monetary_total = ET.SubElement(root, 'cac:LegalMonetaryTotal')
        ET.SubElement(cac_legal_monetary_total, 'cbc:LineExtensionAmount', attrib={'currencyID': str(template_data['CurrencyID'])}).text = str(template_data['TotalLineExtensionAmount'])
        ET.SubElement(cac_legal_monetary_total, 'cbc:TaxExclusiveAmount', attrib={'currencyID': str(template_data['CurrencyID'])}).text = str(template_data['TotalTaxExclusiveAmount'])
        ET.SubElement(cac_legal_monetary_total, 'cbc:TaxInclusiveAmount', attrib={'currencyID': str(template_data['CurrencyID'])}).text = str(template_data['TotalTaxInclusiveAmount'])
        ET.SubElement(cac_legal_monetary_total, 'cbc:AllowanceTotalAmount', attrib={'currencyID': str(template_data['CurrencyID'])}).text = '{:.2f}'.format(template_data['rounding_discount'] + self.document_id.invoice_discount)
        ET.SubElement(cac_legal_monetary_total, 'cbc:ChargeTotalAmount', attrib={'currencyID': str(template_data['CurrencyID'])}).text = '{:.2f}'.format(template_data['rounding_charge'])
        ET.SubElement(cac_legal_monetary_total, 'cbc:PrepaidAmount', attrib={'currencyID': str(template_data['CurrencyID'])}).text = '{:.2f}'.format(0.00)
        ET.SubElement(cac_legal_monetary_total, 'cbc:PayableAmount', attrib={'currencyID': str(template_data['CurrencyID'])}).text = str(template_data['PayableAmount'])
        
        #DATA LINEA
        ET.SubElement(root, 'data_lines_xml')
        
        xml_string = ET.tostring(root, encoding='UTF-8', method='xml').decode('UTF-8')
        xml_string = xml_string.replace('<data_taxs_xml />', template_data['data_taxs_xml'])
        xml_string = xml_string.replace('<data_lines_xml />', template_data['data_lines_xml'])
        parser = etree.XMLParser(remove_blank_text=True)
        xml_root = etree.fromstring(xml_string.encode('UTF-8'), parser)
        for elem in xml_root.iter():
            if elem.text is not None:
                elem.text = elem.text.strip()
            if elem.tail is not None:
                elem.tail = elem.tail.strip()
        
        # Convert back to string
        cleaned_xml_string = etree.tostring(xml_root, encoding='UTF-8', method='xml').decode('UTF-8')


        _logger.error(cleaned_xml_string)
        return cleaned_xml_string
    
    def _add_rounding_adjustment(self, root, rounding_data):
        allowance_charge = ET.SubElement(root, 'cac:AllowanceCharge')
        ET.SubElement(allowance_charge, 'cbc:ID').text = rounding_data['ID']
        ET.SubElement(allowance_charge, 'cbc:ChargeIndicator').text = rounding_data['ChargeIndicator']
        ET.SubElement(allowance_charge, 'cbc:AllowanceChargeReason').text = rounding_data['AllowanceChargeReason']
        ET.SubElement(allowance_charge, 'cbc:MultiplierFactorNumeric').text = rounding_data['MultiplierFactorNumeric']
        
        amount = ET.SubElement(allowance_charge, 'cbc:Amount')
        amount.text = rounding_data['Amount']
        amount.set('currencyID', rounding_data['CurrencyID'])
        
        base_amount = ET.SubElement(allowance_charge, 'cbc:BaseAmount')
        base_amount.text = rounding_data['BaseAmount']
        base_amount.set('currencyID', rounding_data['CurrencyID'])
        return base_amount
    def _create_ds_xml(self,data):
        root = ET.Element('Invoice', {
            'xmlns': 'urn:oasis:names:specification:ubl:schema:xsd:Invoice-2',
            'xmlns:cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2',
            'xmlns:cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2',
            'xmlns:ds': 'http://www.w3.org/2000/09/xmldsig#',
            'xmlns:ext': 'urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2',
            'xmlns:sts': 'dian:gov:co:facturaelectronica:Structures-2-1',
            'xmlns:xsi': 'http://www.w3.org/2001/XMLSchema-instance',
            'xsi:schemaLocation': 'urn:oasis:names:specification:ubl:schema:xsd:Invoice-2 http://docs.oasis-open.org/ubl/os-UBL-2.1/xsd/maindoc/UBL-Invoice-2.1.xsd',
            'xmlns:xades': 'http://uri.etsi.org/01903/v1.3.2#',
            'xmlns:xades141': 'http://uri.etsi.org/01903/v1.4.1#'
        })

        # Crear los elementos y subelementos según la estructura del XML
        ext_ubl_extensions = ET.SubElement(root, 'ext:UBLExtensions')
        ext_ubl_extension1 = ET.SubElement(ext_ubl_extensions, 'ext:UBLExtension')
        ext_extension_content1 = ET.SubElement(ext_ubl_extension1, 'ext:ExtensionContent')
        sts_dian_extensions = ET.SubElement(ext_extension_content1, 'sts:DianExtensions')
        sts_invoice_control = ET.SubElement(sts_dian_extensions, 'sts:InvoiceControl')
        ET.SubElement(sts_invoice_control, 'sts:InvoiceAuthorization').text = str(data['InvoiceAuthorization'])
        sts_authorization_period = ET.SubElement(sts_invoice_control, 'sts:AuthorizationPeriod')
        ET.SubElement(sts_authorization_period, 'cbc:StartDate').text = str(data['StartDate'])
        ET.SubElement(sts_authorization_period, 'cbc:EndDate').text = str(data['EndDate'])
        sts_authorized_invoices = ET.SubElement(sts_invoice_control, 'sts:AuthorizedInvoices')
        ET.SubElement(sts_authorized_invoices, 'sts:Prefix').text = str(data['Prefix'])
        ET.SubElement(sts_authorized_invoices, 'sts:From').text = str(data['From'])
        ET.SubElement(sts_authorized_invoices, 'sts:To').text = str(data['To'])
        sts_invoice_source = ET.SubElement(sts_dian_extensions, 'sts:InvoiceSource')
        ET.SubElement(sts_invoice_source, 'cbc:IdentificationCode', {
            'listAgencyID': '6',
            'listAgencyName': 'United Nations Economic Commission for Europe',
            'listSchemeURI': 'urn:oasis:names:specification:ubl:codelist:gc:CountryIdentificationCode-2.1'
        }).text = str(data['IdentificationCode'])
        sts_software_provider = ET.SubElement(sts_dian_extensions, 'sts:SoftwareProvider')
        ET.SubElement(sts_software_provider, 'sts:ProviderID', {
            'schemeAgencyID': '195',
            'schemeAgencyName': 'CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)',
            'schemeID': str(data['SoftwareProviderSchemeID']),
            'schemeName': '31'
        }).text = str(data['SoftwareProviderID'])
        ET.SubElement(sts_software_provider, 'sts:SoftwareID', {
            'schemeAgencyID': '195',
            'schemeAgencyName': 'CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)'
        }).text = str(data['SoftwareID'])
        ET.SubElement(sts_dian_extensions, 'sts:SoftwareSecurityCode', {
            'schemeAgencyID': '195',
            'schemeAgencyName': 'CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)'
        }).text = str(data['SoftwareSecurityCode'])
        sts_authorization_provider = ET.SubElement(sts_dian_extensions, 'sts:AuthorizationProvider')
        ET.SubElement(sts_authorization_provider, 'sts:AuthorizationProviderID', {
            'schemeAgencyID': '195',
            'schemeAgencyName': 'CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)',
            'schemeID': '4',
            'schemeName': '31'
        }).text = '800197268'
        ET.SubElement(sts_dian_extensions, 'sts:QRCode').text = f"URL={str(data['URLQRCode'])}={str(data['UUID'])}"

        ext_ubl_extension2 = ET.SubElement(ext_ubl_extensions, 'ext:UBLExtension')
        ET.SubElement(ext_ubl_extension2, 'ext:ExtensionContent')

        ET.SubElement(root, 'cbc:UBLVersionID').text = str(data['UBLVersionID'])
        ET.SubElement(root, 'cbc:CustomizationID').text = str(data['CustomizationID'])
        ET.SubElement(root, 'cbc:ProfileID').text = str(data['ProfileID'])
        ET.SubElement(root, 'cbc:ProfileExecutionID').text = str(data['ProfileExecutionID'])
        ET.SubElement(root, 'cbc:ID').text = str(data['InvoiceID'])
        ET.SubElement(root, 'cbc:UUID', {
            'schemeID': str(data['ProfileExecutionID']),
            'schemeName': 'CUDS-SHA384'
        }).text = str(data['UUID'])
        ET.SubElement(root, 'cbc:IssueDate').text = str(data['IssueDate'])
        ET.SubElement(root, 'cbc:IssueTime').text = str(data['IssueTime'])
        ET.SubElement(root, 'cbc:InvoiceTypeCode').text = str(data['InvoiceTypeCode'])
        ET.SubElement(root, 'cbc:DocumentCurrencyCode').text = str(data['DocumentCurrencyCode'])
        ET.SubElement(root, 'cbc:LineCountNumeric').text = str(data['LineCountNumeric'])
        cac_accounting_supplier_party = ET.SubElement(root, 'cac:AccountingSupplierParty')
        ET.SubElement(cac_accounting_supplier_party, 'cbc:AdditionalAccountID').text = str(data['SupplierAdditionalAccountID'])
        cac_party = ET.SubElement(cac_accounting_supplier_party, 'cac:Party')
        cac_party_name = ET.SubElement(cac_party, 'cac:PartyName')
        ET.SubElement(cac_party_name, 'cbc:Name').text = str(data['SupplierPartyName'])
        cac_physical_location = ET.SubElement(cac_party, 'cac:PhysicalLocation')
        cac_address = ET.SubElement(cac_physical_location, 'cac:Address')
        ET.SubElement(cac_address, 'cbc:ID').text = str(data['SupplierCityCode'])
        ET.SubElement(cac_address, 'cbc:CityName').text = str(data['SupplierCityName'])
        ET.SubElement(cac_address, 'cbc:PostalZone').text = str(data['SupplierPostal'])
        ET.SubElement(cac_address, 'cbc:CountrySubentity').text = str(data['SupplierCountrySubentity'])
        ET.SubElement(cac_address, 'cbc:CountrySubentityCode').text = str(data['SupplierCountrySubentityCode'])
        cac_address_line = ET.SubElement(cac_address, 'cac:AddressLine')
        ET.SubElement(cac_address_line, 'cbc:Line').text = str(data['SupplierLine'])
        cac_country = ET.SubElement(cac_address, 'cac:Country')
        ET.SubElement(cac_country, 'cbc:IdentificationCode').text = str(data['SupplierCountryCode'])
        ET.SubElement(cac_country, 'cbc:Name', {'languageID': 'es'}).text = str(data['SupplierCountryName'])
        cac_party_tax_scheme = ET.SubElement(cac_party, 'cac:PartyTaxScheme')
        ET.SubElement(cac_party_tax_scheme, 'cbc:RegistrationName').text = str(data['SupplierPartyName'])
        if data['SupplierSchemeID'] == '31':
            ET.SubElement(cac_party_tax_scheme, 'cbc:CompanyID', attrib={
                'schemeAgencyID': '195',
                'schemeAgencyName': 'CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)',
                'schemeID': str(data['schemeID']),
                'schemeName': str(data['SupplierSchemeID']),
            }).text = str(data['ProviderID'])
        else:
            ET.SubElement(cac_party_tax_scheme, 'cbc:CompanyID', attrib={
                'schemeAgencyID': '195',
                'schemeAgencyName': 'CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)',
                'schemeName': str(data['SupplierSchemeID']),
            }).text = str(data['ProviderID'])
        ET.SubElement(cac_party_tax_scheme, 'cbc:TaxLevelCode', {'listName': '48'}).text = str(data['SupplierTaxLevelCode'])
        cac_registration_address = ET.SubElement(cac_party_tax_scheme, 'cac:RegistrationAddress')
        ET.SubElement(cac_registration_address, 'cbc:ID').text = str(data['SupplierCityCode'])
        ET.SubElement(cac_registration_address, 'cbc:CityName').text = str(data['SupplierCityName'])
        ET.SubElement(cac_registration_address, 'cbc:CountrySubentity').text = str(data['SupplierCountrySubentity'])
        ET.SubElement(cac_registration_address, 'cbc:CountrySubentityCode').text = str(data['SupplierCountrySubentityCode'])
        cac_address_line = ET.SubElement(cac_registration_address, 'cac:AddressLine')
        ET.SubElement(cac_address_line, 'cbc:Line').text = str(data['SupplierLine'])
        cac_country = ET.SubElement(cac_registration_address, 'cac:Country')
        ET.SubElement(cac_country, 'cbc:IdentificationCode').text = str(data['SupplierCountryCode'])
        ET.SubElement(cac_country, 'cbc:Name', {'languageID': 'es'}).text = str(data['SupplierCountryName'])
        cac_tax_scheme = ET.SubElement(cac_party_tax_scheme, 'cac:TaxScheme')
        ET.SubElement(cac_tax_scheme, 'cbc:ID').text = str(data['TaxSchemeID'])
        ET.SubElement(cac_tax_scheme, 'cbc:Name').text = str(data['TaxSchemeName'])
        cac_party_legal_entity = ET.SubElement(cac_party, 'cac:PartyLegalEntity')
        ET.SubElement(cac_party_legal_entity, 'cbc:RegistrationName').text = str(data['SupplierPartyName'])
        ET.SubElement(cac_party_legal_entity, 'cbc:CompanyID', {
            'schemeAgencyID': '195',
            'schemeAgencyName': 'CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)',
            'schemeID': str(data['schemeID']),
            'schemeName': '31'
        }).text = str(data['ProviderID'])
        cac_corporate_registration_scheme = ET.SubElement(cac_party_legal_entity, 'cac:CorporateRegistrationScheme')
        ET.SubElement(cac_corporate_registration_scheme, 'cbc:ID').text = str(data['Prefix'])
        cac_contact = ET.SubElement(cac_party, 'cac:Contact')
        ET.SubElement(cac_contact, 'cbc:ElectronicMail').text = str(data['SupplierElectronicMail'])

        cac_accounting_customer_party = ET.SubElement(root, 'cac:AccountingCustomerParty')
        ET.SubElement(cac_accounting_customer_party, 'cbc:AdditionalAccountID').text = str(data['CustomerAdditionalAccountID'])
        cac_party = ET.SubElement(cac_accounting_customer_party, 'cac:Party')
        cac_party_identification = ET.SubElement(cac_party, 'cac:PartyIdentification')
        ET.SubElement(cac_party_identification, 'cbc:ID', {
            'schemeName': str(data['SchemeNameAdquiriente']),
            'schemeID': str(data['SchemeIDAdquiriente'])
        }).text = str(data['IDAdquiriente'])
        cac_party_name = ET.SubElement(cac_party, 'cac:PartyName')
        ET.SubElement(cac_party_name, 'cbc:Name').text = str(data['CustomerPartyName'])
        cac_physical_location = ET.SubElement(cac_party, 'cac:PhysicalLocation')
        cac_address = ET.SubElement(cac_physical_location, 'cac:Address')
        ET.SubElement(cac_address, 'cbc:ID').text = str(data['CustomerCityCode'])
        ET.SubElement(cac_address, 'cbc:CityName').text = str(data['CustomerCityName'])
        ET.SubElement(cac_address, 'cbc:CountrySubentity').text = str(data['CustomerCountrySubentity'])
        ET.SubElement(cac_address, 'cbc:CountrySubentityCode').text = str(data['CustomerCountrySubentityCode'])
        cac_address_line = ET.SubElement(cac_address, 'cac:AddressLine')
        ET.SubElement(cac_address_line, 'cbc:Line').text = str(data['CustomerLine'])
        cac_country = ET.SubElement(cac_address, 'cac:Country')
        ET.SubElement(cac_country, 'cbc:IdentificationCode').text = str(data['CustomerCountryCode'])
        ET.SubElement(cac_country, 'cbc:Name', {'languageID': 'es'}).text = str(data['CustomerCountryName'])
        cac_party_tax_scheme = ET.SubElement(cac_party, 'cac:PartyTaxScheme')
        ET.SubElement(cac_party_tax_scheme, 'cbc:RegistrationName').text = str(data['CustomerPartyName'])
        if data['SchemeNameAdquiriente'] == '31':
            ET.SubElement(cac_party_tax_scheme, 'cbc:CompanyID', attrib={
                'schemeAgencyID': '195',
                'schemeAgencyName': 'CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)',
                'schemeID': str(data['CustomerschemeID']),
                'schemeName': str(data['SchemeNameAdquiriente']),
            }).text = str(data['CustomerID'])
        else:
            ET.SubElement(cac_party_tax_scheme, 'cbc:CompanyID', attrib={
                'schemeAgencyID': '195',
                'schemeAgencyName': 'CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)',
                'schemeName': str(data['SchemeNameAdquiriente']),
            }).text = str(data['CustomerID'])
        ET.SubElement(cac_party_tax_scheme, 'cbc:TaxLevelCode', {'listName': '48'}).text = str(data['CustomerTaxLevelCode'])
        cac_registration_address = ET.SubElement(cac_party_tax_scheme, 'cac:RegistrationAddress')
        ET.SubElement(cac_registration_address, 'cbc:ID').text = str(data['CustomerCityCode'])
        ET.SubElement(cac_registration_address, 'cbc:CityName').text = str(data['CustomerCityName'])
        ET.SubElement(cac_registration_address, 'cbc:CountrySubentity').text = str(data['CustomerCountrySubentity'])
        ET.SubElement(cac_registration_address, 'cbc:CountrySubentityCode').text = str(data['CustomerCountrySubentityCode'])
        cac_address_line = ET.SubElement(cac_registration_address, 'cac:AddressLine')
        ET.SubElement(cac_address_line, 'cbc:Line').text = str(data['CustomerLine'])
        cac_country = ET.SubElement(cac_registration_address, 'cac:Country')
        ET.SubElement(cac_country, 'cbc:IdentificationCode').text = str(data['CustomerCountryCode'])
        ET.SubElement(cac_country, 'cbc:Name', {'languageID': 'es'}).text = str(data['CustomerCountryName'])
        cac_tax_scheme = ET.SubElement(cac_party_tax_scheme, 'cac:TaxScheme')
        ET.SubElement(cac_tax_scheme, 'cbc:ID').text = str(data['TaxSchemeID'])
        ET.SubElement(cac_tax_scheme, 'cbc:Name').text = str(data['TaxSchemeName'])
        cac_party_legal_entity = ET.SubElement(cac_party, 'cac:PartyLegalEntity')
        ET.SubElement(cac_party_legal_entity, 'cbc:RegistrationName').text = str(data['CustomerPartyName'])
        ET.SubElement(cac_party_legal_entity, 'cbc:CompanyID', {
            'schemeAgencyID': '195',
            'schemeAgencyName': 'CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)',
            'schemeID': str(data['CustomerschemeID']),
            'schemeName': '31'
        }).text = str(data['CustomerID'])
        cac_contact = ET.SubElement(cac_party, 'cac:Contact')
        ET.SubElement(cac_contact, 'cbc:ElectronicMail').text = str(data['CustomerElectronicMail'])
        cac_person = ET.SubElement(cac_party, 'cac:Person')
        ET.SubElement(cac_person, 'cbc:FirstName').text = str(data['Firstname'])

        cac_payment_means = ET.SubElement(root, 'cac:PaymentMeans')
        ET.SubElement(cac_payment_means, 'cbc:ID').text = str(data['PaymentMeansID'])
        ET.SubElement(cac_payment_means, 'cbc:PaymentMeansCode').text = str(data['PaymentMeansCode'])
        ET.SubElement(cac_payment_means, 'cbc:PaymentDueDate').text = str(data['PaymentDueDate'])
        ET.SubElement(cac_payment_means, 'cbc:PaymentID').text = '1234'
        if data['rounding_adjustment_data']:
            self._add_rounding_adjustment(root, data['rounding_adjustment_data'])
        if str(data['CurrencyID']) != 'COP':
            cac_payment_exchange_rate = ET.SubElement(root, 'cac:PaymentExchangeRate')
            ET.SubElement(cac_payment_exchange_rate, 'cbc:SourceCurrencyCode').text = str(data['CurrencyID'])
            ET.SubElement(cac_payment_exchange_rate, 'cbc:SourceCurrencyBaseRate').text = '1.00'
            ET.SubElement(cac_payment_exchange_rate, 'cbc:TargetCurrencyCode').text = 'COP'
            ET.SubElement(cac_payment_exchange_rate, 'cbc:TargetCurrencyBaseRate').text = '1.00'
            ET.SubElement(cac_payment_exchange_rate, 'cbc:CalculationRate').text = str(data['CalculationRate'])
            ET.SubElement(cac_payment_exchange_rate, 'cbc:Date').text = str(data['DateRate'])

        # Agregar los elementos de impuestos (data_taxs_xml) si existen
        ET.SubElement(root, 'data_taxs_xml')

        cac_legal_monetary_total = ET.SubElement(root, 'cac:LegalMonetaryTotal')
        ET.SubElement(cac_legal_monetary_total, 'cbc:LineExtensionAmount', {'currencyID': str(data['CurrencyID'])}).text = str(data['TotalLineExtensionAmount'])
        ET.SubElement(cac_legal_monetary_total, 'cbc:TaxExclusiveAmount', {'currencyID': str(data['CurrencyID'])}).text = str(data['TotalTaxExclusiveAmount'])
        ET.SubElement(cac_legal_monetary_total, 'cbc:TaxInclusiveAmount', {'currencyID': str(data['CurrencyID'])}).text = str(data['TotalTaxInclusiveAmount'])
        ET.SubElement(cac_legal_monetary_total, 'cbc:PayableAmount', {'currencyID': str(data['CurrencyID'])}).text = str(data['PayableAmount'])

        # Agregar las líneas de factura (data_lines_xml) si existen
        ET.SubElement(root, 'data_lines_xml')

        xml_string = ET.tostring(root, encoding='utf-8', method='xml').decode('utf-8')
        xml_string = xml_string.replace('<data_taxs_xml />', str(data['data_taxs_xml']))
        xml_string = xml_string.replace('<data_lines_xml />', str(data['data_lines_xml']))
        return xml_string
    
    def generate_xml_nc(self, template_data):
        if self.document_id.move_type == 'in_refund':
            return self._create_xml_in_nc(template_data)
        elif self.document_id.move_type == 'out_refund':
            return self._create_xml_nc(template_data)
    
    def _create_xml_nc(self,template_data):
        root = ET.Element('CreditNote', {'xmlns': 'urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2',
                                        'xmlns:cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2',
                                        'xmlns:cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2',
                                        'xmlns:ds': 'http://www.w3.org/2000/09/xmldsig#',
                                        'xmlns:ext': 'urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2',
                                        'xmlns:sts': 'http://www.dian.gov.co/contratos/facturaelectronica/v1/Structures',
                                        'xmlns:xsi': 'http://www.w3.org/2001/XMLSchema-instance',
                                        'xsi:schemaLocation': 'urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2 http://docs.oasis-open.org/ubl/os-UBL-2.1/xsd/maindoc/UBL-CreditNote-2.1.xsd'})

        # UBLExtensions
        UBLExtensions = ET.SubElement(root, 'ext:UBLExtensions')
        UBLExtension = ET.SubElement(UBLExtensions, 'ext:UBLExtension')
        ExtensionContent = ET.SubElement(UBLExtension, 'ext:ExtensionContent')
        DianExtensions = ET.SubElement(ExtensionContent, 'sts:DianExtensions')

        InvoiceSource = ET.SubElement(DianExtensions, 'sts:InvoiceSource')
        ET.SubElement(InvoiceSource, 'cbc:IdentificationCode', {'listAgencyID': '6',
                                                                'listAgencyName': 'United Nations Economic Commission for Europe',
                                                                'listSchemeURI': 'urn:oasis:names:specification:ubl:codelist:gc:CountryIdentificationCode-2.1'}).text = str(template_data['IdentificationCode'])

        SoftwareProvider = ET.SubElement(DianExtensions, 'sts:SoftwareProvider')
        ET.SubElement(SoftwareProvider, 'sts:ProviderID', {'schemeAgencyID': '195',
                                                            'schemeAgencyName': 'CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)', 
                                                            'schemeID': str(template_data['schemeID']),
                                                            'schemeName': '31'}).text = str(template_data['ProviderID'])
        ET.SubElement(SoftwareProvider, 'sts:SoftwareID', {'schemeAgencyID': '195',
                                                            'schemeAgencyName': 'CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)'}).text = str(template_data['SoftwareID'])

        ET.SubElement(DianExtensions, 'sts:SoftwareSecurityCode', {'schemeAgencyID': '195',
                                                                    'schemeAgencyName': 'CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)'}).text = str(template_data['SoftwareSecurityCode'])

        AuthorizationProvider = ET.SubElement(DianExtensions, 'sts:AuthorizationProvider')
        ET.SubElement(AuthorizationProvider, 'sts:AuthorizationProviderID', {'schemeAgencyID': '195',
                                                                            'schemeAgencyName': 'CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)',
                                                                            'schemeID': '4',
                                                                            'schemeName': '31'}).text = '800197268'

        qrcode_text = f"NroFactura={template_data['InvoiceID']} \n NitFacturador={template_data['SoftwareProviderID']} \n NitAdquiriente={template_data['IDAdquiriente']} \n FechaFactura={template_data['IssueDate']} \n ValorTotalFactura={template_data['PayableAmount']} \n CUFE={template_data['UUID']}  \n URL={str(template_data['URLQRCode'])}={str(template_data['UUID'])}"
        qrcode_element = ET.SubElement(DianExtensions, 'sts:QRCode')
        qrcode_element.text = qrcode_text

        ext_ubl_extension2 = ET.SubElement(UBLExtensions, 'ext:UBLExtension')
        ET.SubElement(ext_ubl_extension2, 'ext:ExtensionContent')
        # Datos básicos de la nota de crédito
        ET.SubElement(root, 'cbc:UBLVersionID').text = str(template_data['UBLVersionID'])
        ET.SubElement(root, 'cbc:CustomizationID').text = str(template_data['CustomizationID'])
        ET.SubElement(root, 'cbc:ProfileID').text = str(template_data['ProfileID'])
        ET.SubElement(root, 'cbc:ProfileExecutionID').text = str(template_data['ProfileExecutionID'])
        ET.SubElement(root, 'cbc:ID').text = str(template_data['InvoiceID'])
        ET.SubElement(root, 'cbc:UUID', {'schemeID': str(template_data['ProfileExecutionID']),
                                        'schemeName': 'CUDE-SHA384'}).text = str(template_data['UUID'])
        ET.SubElement(root, 'cbc:IssueDate').text = str(template_data['IssueDate'])
        ET.SubElement(root, 'cbc:IssueTime').text = str(template_data['IssueTime'])
        ET.SubElement(root, 'cbc:CreditNoteTypeCode').text = str(template_data['CreditNoteTypeCode'])
        if template_data['CurrencyID'] != 'COP':
            ET.SubElement(root, 'cbc:DocumentCurrencyCode', attrib={
            'listAgencyID': '6',
            'listAgencyName': 'United Nations Economic Commission for Europe',
            'listID':'ISO 4217 Alpha'}).text = str(template_data['DocumentCurrencyCode'])
        else:
            ET.SubElement(root, 'cbc:DocumentCurrencyCode').text = str(template_data['DocumentCurrencyCode'])
        ET.SubElement(root, 'cbc:LineCountNumeric').text = str(template_data['LineCountNumeric'])
        if self.document_id.document_without_reference:
            if not self.document_id.date_from or not self.document_id.date_to:
                raise UserError('Falta el rango de Fecha')
            InvoicePeriod = ET.SubElement(root, 'cac:InvoicePeriod')  
            ET.SubElement(InvoicePeriod, 'cbc:StartDate').text = str(self.document_id.date_from)
            ET.SubElement(InvoicePeriod, 'cbc:EndDate').text = str(self.document_id.date_to) 
        DiscrepancyResponse = ET.SubElement(root, 'cac:DiscrepancyResponse')
        ET.SubElement(DiscrepancyResponse, 'cbc:ReferenceID').text = str(template_data['InvoiceReferenceID'])
        ET.SubElement(DiscrepancyResponse, 'cbc:ResponseCode').text =  str(template_data['ResponseCodeCreditNote'])
        ET.SubElement(DiscrepancyResponse, 'cbc:Description').text =  str(template_data['DescriptionDebitCreditNote'])
        if self.document_id.reversed_entry_id.ref:
            cac_order_ref = ET.SubElement(root, 'cac:OrderReference')
            ET.SubElement(cac_order_ref, 'cbc:ID').text = str(self.document_id.ref)





        # BillingReference
        if not self.document_id.document_without_reference:
            BillingReference = ET.SubElement(root, 'cac:BillingReference')
            InvoiceDocumentReference = ET.SubElement(BillingReference, 'cac:InvoiceDocumentReference')
            ET.SubElement(InvoiceDocumentReference, 'cbc:ID').text = str(template_data['InvoiceReferenceID'])
            ET.SubElement(InvoiceDocumentReference, 'cbc:UUID', {'schemeName': 'CUFE-SHA384'}).text = str(template_data['InvoiceReferenceUUID'])
            ET.SubElement(InvoiceDocumentReference, 'cbc:IssueDate').text = str(template_data['InvoiceReferenceDate'])
        if self.document_id.reversed_entry_id.receipts:
            for receipt in self.document_id.reversed_entry_id.receipts:
                cac_receipt_doc_ref = ET.SubElement(root, 'cac:ReceiptDocumentReference')
                ET.SubElement(cac_receipt_doc_ref, 'cbc:ID').text = receipt.name

        # AccountingSupplierParty
        AccountingSupplierParty = ET.SubElement(root, 'cac:AccountingSupplierParty')
        ET.SubElement(AccountingSupplierParty, 'cbc:AdditionalAccountID').text = str(template_data['SupplierAdditionalAccountID'])

        Party = ET.SubElement(AccountingSupplierParty, 'cac:Party')
        PartyName = ET.SubElement(Party, 'cac:PartyName')
        ET.SubElement(PartyName, 'cbc:Name').text = str(template_data['SupplierPartyName'])

        PhysicalLocation = ET.SubElement(Party, 'cac:PhysicalLocation')
        Address = ET.SubElement(PhysicalLocation, 'cac:Address')
        ET.SubElement(Address, 'cbc:ID').text = str(template_data['SupplierCityCode'])
        ET.SubElement(Address, 'cbc:CityName').text = str(template_data['SupplierCityName'])
        ET.SubElement(Address, 'cbc:CountrySubentity').text = str(template_data['SupplierCountrySubentity'])
        ET.SubElement(Address, 'cbc:CountrySubentityCode').text = str(template_data['SupplierCountrySubentityCode'])
        cac_address_line = ET.SubElement(Address, 'cac:AddressLine')
        ET.SubElement(cac_address_line, 'cbc:Line').text = str(template_data['SupplierLine'])       
        Country = ET.SubElement(Address, 'cac:Country')
        ET.SubElement(Country, 'cbc:IdentificationCode').text = str(template_data['SupplierCountryCode'])
        ET.SubElement(Country, 'cbc:Name', {'languageID': 'es'}).text = str(template_data['SupplierCountryName'])

        PartyTaxScheme = ET.SubElement(Party, 'cac:PartyTaxScheme')
        ET.SubElement(PartyTaxScheme, 'cbc:RegistrationName').text = str(template_data['SupplierPartyName'])
        ET.SubElement(PartyTaxScheme, 'cbc:CompanyID', {'schemeAgencyID': '195',
                                                        'schemeAgencyName': 'CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)',
                                                        'schemeID': str(template_data['schemeID']),
                                                        'schemeName': '31'}).text = str(template_data['ProviderID'])
        ET.SubElement(PartyTaxScheme, 'cbc:TaxLevelCode', {'listName': '48'}).text = str(template_data['SupplierTaxLevelCode'])
        
        RegistrationAddress = ET.SubElement(PartyTaxScheme, 'cac:RegistrationAddress')
        ET.SubElement(RegistrationAddress, 'cbc:ID').text = str(template_data['SupplierCityCode'])
        ET.SubElement(RegistrationAddress, 'cbc:CityName').text = str(template_data['SupplierCityName'])
        ET.SubElement(RegistrationAddress, 'cbc:CountrySubentity').text = str(template_data['SupplierCountrySubentity'])
        ET.SubElement(RegistrationAddress, 'cbc:CountrySubentityCode').text = str(template_data['SupplierCountrySubentityCode'])
        cac_reg_address_line = ET.SubElement(RegistrationAddress, 'cac:AddressLine')
        ET.SubElement(cac_reg_address_line, 'cbc:Line').text = str(template_data['SupplierLine'])       
        Country = ET.SubElement(RegistrationAddress, 'cac:Country')
        ET.SubElement(Country, 'cbc:IdentificationCode').text = str(template_data['SupplierCountryCode'])
        ET.SubElement(Country, 'cbc:Name', {'languageID': 'es'}).text = str(template_data['SupplierCountryName'])

        TaxScheme = ET.SubElement(PartyTaxScheme, 'cac:TaxScheme')
        ET.SubElement(TaxScheme, 'cbc:ID').text = str(template_data['TaxSchemeID'])
        ET.SubElement(TaxScheme, 'cbc:Name').text = str(template_data['TaxSchemeName'])

        PartyLegalEntity = ET.SubElement(Party, 'cac:PartyLegalEntity')
        ET.SubElement(PartyLegalEntity, 'cbc:RegistrationName').text = str(template_data['SupplierPartyName'])
        ET.SubElement(PartyLegalEntity, 'cbc:CompanyID', {'schemeAgencyID': '195',
                                                        'schemeAgencyName': 'CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)',
                                                        'schemeID': str(template_data['schemeID']),
                                                        'schemeName': '31'}).text = str(template_data['ProviderID'])
        
        CorporateRegistrationScheme = ET.SubElement(PartyLegalEntity, 'cac:CorporateRegistrationScheme')
        ET.SubElement(CorporateRegistrationScheme, 'cbc:ID').text = str(template_data['Prefix'])

        Contact = ET.SubElement(Party, 'cac:Contact')
        ET.SubElement(Contact, 'cbc:ElectronicMail').text = str(template_data['SupplierElectronicMail'])

        # AccountingCustomerParty
        AccountingCustomerParty = ET.SubElement(root, 'cac:AccountingCustomerParty')
        ET.SubElement(AccountingCustomerParty, 'cbc:AdditionalAccountID').text = str(template_data['CustomerAdditionalAccountID'])

        Party = ET.SubElement(AccountingCustomerParty, 'cac:Party')

        PartyIdentification = ET.SubElement(Party, 'cac:PartyIdentification')
        ET.SubElement(PartyIdentification, 'cbc:ID', {'schemeName': str(template_data['SchemeNameAdquiriente']),
                                                    'schemeID': str(template_data['SchemeIDAdquiriente'])}).text = str(template_data['IDAdquiriente'])

        PartyName = ET.SubElement(Party, 'cac:PartyName')
        ET.SubElement(PartyName, 'cbc:Name').text = str(template_data['CustomerPartyName'])

        PhysicalLocation = ET.SubElement(Party, 'cac:PhysicalLocation')
        Address = ET.SubElement(PhysicalLocation, 'cac:Address')
        ET.SubElement(Address, 'cbc:ID').text = str(template_data['CustomerCityCode'])
        ET.SubElement(Address, 'cbc:CityName').text = str(template_data['CustomerCityName'])
        ET.SubElement(Address, 'cbc:CountrySubentity').text = str(template_data['CustomerCountrySubentity'])
        ET.SubElement(Address, 'cbc:CountrySubentityCode').text = str(template_data['CustomerCountrySubentityCode'])
        cac_custo_address_line = ET.SubElement(Address, 'cac:AddressLine')
        ET.SubElement(cac_custo_address_line, 'cbc:Line').text = str(template_data['CustomerLine'])
        Country = ET.SubElement(Address, 'cac:Country')
        ET.SubElement(Country, 'cbc:IdentificationCode').text = str(template_data['CustomerCountryCode'])
        ET.SubElement(Country, 'cbc:Name', {'languageID': 'es'}).text = str(template_data['CustomerCountryName'])

        PartyTaxScheme = ET.SubElement(Party, 'cac:PartyTaxScheme')
        ET.SubElement(PartyTaxScheme, 'cbc:RegistrationName').text = str(template_data['CustomerPartyName'])
        if template_data['SchemeNameAdquiriente'] == '31':
            ET.SubElement(PartyTaxScheme, 'cbc:CompanyID', attrib={
                'schemeAgencyID': '195',
                'schemeAgencyName': 'CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)',
                'schemeID': str(template_data['CustomerschemeID']),
                'schemeName': str(template_data['SchemeNameAdquiriente']),
            }).text = str(template_data['CustomerID'])
        else:
            ET.SubElement(PartyTaxScheme, 'cbc:CompanyID', attrib={
                'schemeAgencyID': '195',
                'schemeAgencyName': 'CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)',
                'schemeName': str(template_data['SchemeNameAdquiriente']),
            }).text = str(template_data['CustomerID'])
        ET.SubElement(PartyTaxScheme, 'cbc:TaxLevelCode', {'listName': '48'}).text = str(template_data['CustomerTaxLevelCode'])

        RegistrationAddress = ET.SubElement(PartyTaxScheme, 'cac:RegistrationAddress')
        ET.SubElement(RegistrationAddress, 'cbc:ID').text = str(template_data['CustomerCityCode'])
        ET.SubElement(RegistrationAddress, 'cbc:CityName').text = str(template_data['CustomerCityName'])
        ET.SubElement(RegistrationAddress, 'cbc:CountrySubentity').text = str(template_data['CustomerCountrySubentity'])
        ET.SubElement(RegistrationAddress, 'cbc:CountrySubentityCode').text = str(template_data['CustomerCountrySubentityCode'])
        cac_custo_reg_address_line = ET.SubElement(RegistrationAddress, 'cac:AddressLine')
        ET.SubElement(cac_custo_reg_address_line, 'cbc:Line').text = str(template_data['CustomerLine'])
        
        Country = ET.SubElement(RegistrationAddress, 'cac:Country')
        ET.SubElement(Country, 'cbc:IdentificationCode').text = str(template_data['CustomerCountryCode'])
        ET.SubElement(Country, 'cbc:Name', {'languageID': 'es'}).text = str(template_data['CustomerCountryName'])
        TaxScheme = ET.SubElement(PartyTaxScheme, 'cac:TaxScheme')
        ET.SubElement(TaxScheme, 'cbc:ID').text = str(template_data['TaxSchemeID'])
        ET.SubElement(TaxScheme, 'cbc:Name').text = str(template_data['TaxSchemeName'])
        PartyLegalEntity = ET.SubElement(Party, 'cac:PartyLegalEntity')
        ET.SubElement(PartyLegalEntity, 'cbc:RegistrationName').text = str(template_data['CustomerPartyName'])
        if template_data['SchemeNameAdquiriente'] == '31':
            ET.SubElement(PartyLegalEntity, 'cbc:CompanyID', attrib={
                'schemeAgencyID': '195',
                'schemeAgencyName': 'CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)',
                'schemeID': str(template_data['CustomerschemeID']),
                'schemeName': str(template_data['SchemeNameAdquiriente']),
            }).text = str(template_data['CustomerID'])
        else:
            ET.SubElement(PartyLegalEntity, 'cbc:CompanyID', attrib={
                'schemeAgencyID': '195',
                'schemeAgencyName': 'CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)',
                'schemeName': str(template_data['SchemeNameAdquiriente']),
            }).text = str(template_data['CustomerID'])
        Contact = ET.SubElement(Party, 'cac:Contact')
        ET.SubElement(Contact, 'cbc:ElectronicMail').text = str(template_data['CustomerElectronicMail'])
        Person = ET.SubElement(Party, 'cac:Person')
        ET.SubElement(Person, 'cbc:FirstName').text = str(template_data['Firstname'])
        # PaymentMeans
        PaymentMeans = ET.SubElement(root, 'cac:PaymentMeans')
        ET.SubElement(PaymentMeans, 'cbc:ID').text = str(template_data['PaymentMeansID'])
        ET.SubElement(PaymentMeans, 'cbc:PaymentMeansCode').text = str(template_data['PaymentMeansCode'])
        ET.SubElement(PaymentMeans, 'cbc:PaymentDueDate').text = str(template_data['PaymentDueDate'])
        ET.SubElement(PaymentMeans, 'cbc:PaymentID').text = '1234'
        if template_data['rounding_adjustment_data']:
            self._add_rounding_adjustment(root, template_data['rounding_adjustment_data'])
        #root.append(ET.fromstring(str(template_data['data_taxs_xml'])))
        ET.SubElement(root, 'data_taxs_xml')
        # LegalMonetaryTotal
        LegalMonetaryTotal = ET.SubElement(root, 'cac:LegalMonetaryTotal')
        ET.SubElement(LegalMonetaryTotal, 'cbc:LineExtensionAmount', {'currencyID': str(template_data['CurrencyID'])}).text = str(str(template_data['TotalLineExtensionAmount']))
        ET.SubElement(LegalMonetaryTotal, 'cbc:TaxExclusiveAmount', {'currencyID': str(template_data['CurrencyID'])}).text = str(str(template_data['TotalTaxExclusiveAmount']))
        ET.SubElement(LegalMonetaryTotal, 'cbc:TaxInclusiveAmount', {'currencyID': str(template_data['CurrencyID'])}).text = str(str(template_data['TotalTaxInclusiveAmount']))
        ET.SubElement(LegalMonetaryTotal, 'cbc:AllowanceTotalAmount', attrib={'currencyID': str(template_data['CurrencyID'])}).text = '{:.2f}'.format(template_data['rounding_discount'] + self.document_id.invoice_discount)
        ET.SubElement(LegalMonetaryTotal, 'cbc:ChargeTotalAmount', attrib={'currencyID': str(template_data['CurrencyID'])}).text = '{:.2f}'.format(template_data['rounding_charge'])
        ET.SubElement(LegalMonetaryTotal, 'cbc:PayableAmount', {'currencyID': str(template_data['CurrencyID'])}).text = str(str(template_data['PayableAmount']))

        # CreditNoteLines
        #root.append(ET.fromstring(str(template_data['data_credit_lines_xml'])))
        ET.SubElement(root, 'data_lines_xml')
        xml_string = ET.tostring(root, encoding='UTF-8', method='xml').decode('UTF-8')
        xml_string = xml_string.replace('<data_taxs_xml />', str(template_data['data_taxs_xml']))
        xml_string = xml_string.replace('<data_lines_xml />', str(template_data['data_lines_xml']))
        return xml_string


    def _create_xml_in_nc(self, template_data):
        root = ET.Element('CreditNote')

        # Agregar los namespaces al elemento raíz
        root.set('xmlns', 'urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2')
        root.set('xmlns:cbc', 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2')
        root.set('xmlns:cac', 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2')
        root.set('xmlns:ds', 'http://www.w3.org/2000/09/xmldsig#')
        root.set('xmlns:ext', 'urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2')
        root.set('xmlns:sts', 'dian:gov:co:facturaelectronica:Structures-2-1')
        root.set('xmlns:xsi', 'http://www.w3.org/2001/XMLSchema-instance')
        root.set('xsi:schemaLocation', 'urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2 http://docs.oasis-open.org/ubl/os-UBL-2.1/xsd/maindoc/UBL-CreditNote-2.1.xsd')
        root.set('xmlns:xades', 'http://uri.etsi.org/01903/v1.3.2#')
        root.set('xmlns:xades141', 'http://uri.etsi.org/01903/v1.4.1#')

        # Agregar el elemento ext:UBLExtensions
        ext_ubl_extensions = ET.SubElement(root, 'ext:UBLExtensions')

        # Agregar el primer ext:UBLExtension
        ext_ubl_extension1 = ET.SubElement(ext_ubl_extensions, 'ext:UBLExtension')
        ext_extension_content1 = ET.SubElement(ext_ubl_extension1, 'ext:ExtensionContent')
        sts_dian_extensions = ET.SubElement(ext_extension_content1, 'sts:DianExtensions')

        # Agregar el elemento sts:InvoiceSource
        sts_invoice_source = ET.SubElement(sts_dian_extensions, 'sts:InvoiceSource')
        cbc_identification_code = ET.SubElement(sts_invoice_source, 'cbc:IdentificationCode')
        cbc_identification_code.text = str(template_data['IdentificationCode'])
        cbc_identification_code.set('listAgencyID', '6')
        cbc_identification_code.set('listAgencyName', 'United Nations Economic Commission for Europe')
        cbc_identification_code.set('listSchemeURI', 'urn:oasis:names:specification:ubl:codelist:gc:CountryIdentificationCode-2.1')

        # Agregar el elemento sts:SoftwareProvider
        sts_software_provider = ET.SubElement(sts_dian_extensions, 'sts:SoftwareProvider')
        sts_provider_id = ET.SubElement(sts_software_provider, 'sts:ProviderID')
        sts_provider_id.text = str(template_data['SoftwareProviderID'])
        sts_provider_id.set('schemeAgencyID', '195')
        sts_provider_id.set('schemeAgencyName', 'CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)')
        sts_provider_id.set('schemeID', str(template_data['SoftwareProviderSchemeID']))
        sts_provider_id.set('schemeName', '31')
        sts_software_id = ET.SubElement(sts_software_provider, 'sts:SoftwareID')
        sts_software_id.text = str(template_data['SoftwareID'])
        sts_software_id.set('schemeAgencyID', '195')
        sts_software_id.set('schemeAgencyName', 'CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)')

        # Agregar el elemento sts:SoftwareSecurityCode
        sts_software_security_code = ET.SubElement(sts_dian_extensions, 'sts:SoftwareSecurityCode')
        sts_software_security_code.text = str(template_data['SoftwareSecurityCode'])
        sts_software_security_code.set('schemeAgencyID', '195')
        sts_software_security_code.set('schemeAgencyName', 'CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)')

        # Agregar el elemento sts:AuthorizationProvider
        sts_authorization_provider = ET.SubElement(sts_dian_extensions, 'sts:AuthorizationProvider')
        sts_authorization_provider_id = ET.SubElement(sts_authorization_provider, 'sts:AuthorizationProviderID')
        sts_authorization_provider_id.text = '800197268'
        sts_authorization_provider_id.set('schemeAgencyID', '195')
        sts_authorization_provider_id.set('schemeAgencyName', 'CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)')
        sts_authorization_provider_id.set('schemeID', '4')
        sts_authorization_provider_id.set('schemeName', '31')

        # Agregar el elemento sts:QRCode
        qrcode_text = f"NroFactura={template_data['InvoiceID']} \n NitFacturador={template_data['SoftwareProviderID']} \n NitAdquiriente={template_data['IDAdquiriente']} \n FechaFactura={template_data['IssueDate']} \n ValorTotalFactura={template_data['PayableAmount']} \n CUFE={template_data['UUID']}  \n URL={str(template_data['URLQRCode'])}={str(template_data['UUID'])}"
        qrcode_element = ET.SubElement(sts_dian_extensions, 'sts:QRCode')
        qrcode_element.text = qrcode_text

        # Agregar el segundo ext:UBLExtension
        ext_ubl_extension2 = ET.SubElement(ext_ubl_extensions, 'ext:UBLExtension')
        ET.SubElement(ext_ubl_extension2, 'ext:ExtensionContent')

        # Agregar los elementos y valores restantes
        ET.SubElement(root, 'cbc:UBLVersionID').text = str(template_data['UBLVersionID'])
        ET.SubElement(root, 'cbc:CustomizationID').text = str(template_data['CustomizationID'])
        ET.SubElement(root, 'cbc:ProfileID').text = str(template_data['ProfileID'])
        ET.SubElement(root, 'cbc:ProfileExecutionID').text = str(template_data['ProfileExecutionID'])
        ET.SubElement(root, 'cbc:ID').text = str(template_data['InvoiceID'])
        
        cbc_uuid = ET.SubElement(root, 'cbc:UUID')
        cbc_uuid.text = str(template_data['UUID'])
        cbc_uuid.set('schemeID', str(template_data['ProfileExecutionID']))
        cbc_uuid.set('schemeName', 'CUDS-SHA384')
        
        ET.SubElement(root, 'cbc:IssueDate').text = str(template_data['IssueDate'])
        ET.SubElement(root, 'cbc:IssueTime').text = str(template_data['IssueTime'])
        ET.SubElement(root, 'cbc:CreditNoteTypeCode').text = str(template_data['CreditNoteTypeCode'])
        ET.SubElement(root, 'cbc:DocumentCurrencyCode').text = str(template_data['DocumentCurrencyCode'])
        ET.SubElement(root, 'cbc:LineCountNumeric').text = str(template_data['LineCountNumeric'])

        # Agregar el elemento cac:DiscrepancyResponse
        cac_discrepancy_response = ET.SubElement(root, 'cac:DiscrepancyResponse')
        ET.SubElement(cac_discrepancy_response, 'cbc:ReferenceID').text = str(template_data['DiscrepancyResponseID'])
        ET.SubElement(cac_discrepancy_response, 'cbc:ResponseCode').text = str(template_data['DiscrepancyResponseCode'])
        ET.SubElement(cac_discrepancy_response, 'cbc:Description').text = str(template_data['DiscrepancyResponseDescription'])

        # Agregar el elemento cac:BillingReference
        cac_billing_reference = ET.SubElement(root, 'cac:BillingReference')
        cac_invoice_document_reference = ET.SubElement(cac_billing_reference, 'cac:InvoiceDocumentReference')
        ET.SubElement(cac_invoice_document_reference, 'cbc:ID').text = str(template_data['InvoiceReferenceID'])
        
        cbc_invoice_uuid = ET.SubElement(cac_invoice_document_reference, 'cbc:UUID')
        cbc_invoice_uuid.text = str(template_data['InvoiceReferenceUUID'])
        cbc_invoice_uuid.set('schemeName', 'CUDS-SHA384')
        
        ET.SubElement(cac_invoice_document_reference, 'cbc:IssueDate').text = str(template_data['InvoiceReferenceDate'])

        # Agregar el elemento cac:AccountingSupplierParty
        cac_accounting_supplier_party = ET.SubElement(root, 'cac:AccountingSupplierParty')
        ET.SubElement(cac_accounting_supplier_party, 'cbc:AdditionalAccountID').text = str(template_data['SupplierAdditionalAccountID'])
        
        cac_party = ET.SubElement(cac_accounting_supplier_party, 'cac:Party')
        cac_party_name = ET.SubElement(cac_party, 'cac:PartyName')
        ET.SubElement(cac_party_name, 'cbc:Name').text = str(template_data['SupplierPartyName'])
        
        cac_physical_location = ET.SubElement(cac_party, 'cac:PhysicalLocation')
        cac_address = ET.SubElement(cac_physical_location, 'cac:Address')
        ET.SubElement(cac_address, 'cbc:ID').text = str(template_data['SupplierCityCode'])
        ET.SubElement(cac_address, 'cbc:CityName').text = str(template_data['SupplierCityName'])
        ET.SubElement(cac_address, 'cbc:PostalZone').text = str(self.document_id.partner_id.zip)
        ET.SubElement(cac_address, 'cbc:CountrySubentity').text = str(template_data['SupplierCountrySubentity'])
        ET.SubElement(cac_address, 'cbc:CountrySubentityCode').text = str(template_data['SupplierCountrySubentityCode'])
        
        cac_address_line = ET.SubElement(cac_address, 'cac:AddressLine')
        ET.SubElement(cac_address_line, 'cbc:Line').text = str(template_data['SupplierLine'])
        
        cac_country = ET.SubElement(cac_address, 'cac:Country')
        ET.SubElement(cac_country, 'cbc:IdentificationCode').text = str(template_data['SupplierCountryCode'])
        cbc_country_name = ET.SubElement(cac_country, 'cbc:Name')
        cbc_country_name.text = str(template_data['SupplierCountryName'])
        cbc_country_name.set('languageID', 'es')
        
        cac_party_tax_scheme = ET.SubElement(cac_party, 'cac:PartyTaxScheme')
        ET.SubElement(cac_party_tax_scheme, 'cbc:RegistrationName').text = str(template_data['SupplierPartyName'])
        
        cbc_company_id = ET.SubElement(cac_party_tax_scheme, 'cbc:CompanyID')
        cbc_company_id.text = str(template_data['ProviderID'])
        cbc_company_id.set('schemeAgencyID', '195')
        cbc_company_id.set('schemeAgencyName', 'CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)')
        cbc_company_id.set('schemeID', str(template_data['schemeID']))
        cbc_company_id.set('schemeName', '31')
        
        ET.SubElement(cac_party_tax_scheme, 'cbc:TaxLevelCode').text = str(template_data['SupplierTaxLevelCode'])
        
        cac_registration_address = ET.SubElement(cac_party_tax_scheme, 'cac:RegistrationAddress')
        ET.SubElement(cac_registration_address, 'cbc:ID').text = str(template_data['SupplierCityCode'])
        ET.SubElement(cac_registration_address, 'cbc:CityName').text = str(template_data['SupplierCityName'])
        ET.SubElement(cac_registration_address, 'cbc:CountrySubentity').text = str(template_data['SupplierCountrySubentity'])
        ET.SubElement(cac_registration_address, 'cbc:CountrySubentityCode').text = str(template_data['SupplierCountrySubentityCode'])
        
        cac_address_line = ET.SubElement(cac_registration_address, 'cac:AddressLine')
        ET.SubElement(cac_address_line, 'cbc:Line').text = str(template_data['SupplierLine'])
        
        cac_country = ET.SubElement(cac_registration_address, 'cac:Country')
        ET.SubElement(cac_country, 'cbc:IdentificationCode').text = str(template_data['SupplierCountryCode'])
        cbc_country_name = ET.SubElement(cac_country, 'cbc:Name')
        cbc_country_name.text = str(template_data['SupplierCountryName'])
        cbc_country_name.set('languageID', 'es')

        cac_tax_scheme = ET.SubElement(cac_party_tax_scheme, 'cac:TaxScheme')
        ET.SubElement(cac_tax_scheme, 'cbc:ID').text = str(template_data['TaxSchemeID'])
        ET.SubElement(cac_tax_scheme, 'cbc:Name').text = str(template_data['TaxSchemeName'])
        
        cac_party_legal_entity = ET.SubElement(cac_party, 'cac:PartyLegalEntity')
        ET.SubElement(cac_party_legal_entity, 'cbc:RegistrationName').text = str(template_data['SupplierPartyName'])
        
        cbc_company_id = ET.SubElement(cac_party_legal_entity, 'cbc:CompanyID')
        cbc_company_id.text = str(template_data['ProviderID'])
        cbc_company_id.set('schemeAgencyID', '195')
        cbc_company_id.set('schemeAgencyName', 'CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)')
        cbc_company_id.set('schemeID', str(template_data['schemeID']))
        cbc_company_id.set('schemeName', '31')
        cac_corporate_registration_scheme = ET.SubElement(cac_party_legal_entity, 'cac:CorporateRegistrationScheme')
        ET.SubElement(cac_corporate_registration_scheme, 'cbc:ID').text = str(template_data['Prefix'])

        cac_contact = ET.SubElement(cac_party, 'cac:Contact')
        ET.SubElement(cac_contact, 'cbc:ElectronicMail').text = str(template_data['SupplierElectronicMail'])

        # Agregar el elemento cac:AccountingCustomerParty
        cac_accounting_customer_party = ET.SubElement(root, 'cac:AccountingCustomerParty')
        ET.SubElement(cac_accounting_customer_party, 'cbc:AdditionalAccountID').text = str(template_data['CustomerAdditionalAccountID'])

        cac_party = ET.SubElement(cac_accounting_customer_party, 'cac:Party')
        cac_party_identification = ET.SubElement(cac_party, 'cac:PartyIdentification')
        cbc_id = ET.SubElement(cac_party_identification, 'cbc:ID')
        cbc_id.text = str(template_data['IDAdquiriente'])
        cbc_id.set('schemeName', str(template_data['SchemeNameAdquiriente']))
        cbc_id.set('schemeID', str(template_data['SchemeIDAdquiriente']))

        cac_party_name = ET.SubElement(cac_party, 'cac:PartyName')
        ET.SubElement(cac_party_name, 'cbc:Name').text = str(template_data['CustomerPartyName'])

        cac_physical_location = ET.SubElement(cac_party, 'cac:PhysicalLocation')
        cac_address = ET.SubElement(cac_physical_location, 'cac:Address')
        ET.SubElement(cac_address, 'cbc:ID').text = str(template_data['CustomerCityCode'])
        ET.SubElement(cac_address, 'cbc:CityName').text = str(template_data['CustomerCityName'])
        ET.SubElement(cac_address, 'cbc:CountrySubentity').text = str(template_data['CustomerCountrySubentity'])
        ET.SubElement(cac_address, 'cbc:CountrySubentityCode').text = str(template_data['CustomerCountrySubentityCode'])

        cac_address_line = ET.SubElement(cac_address, 'cac:AddressLine')
        ET.SubElement(cac_address_line, 'cbc:Line').text = str(template_data['CustomerLine'])

        cac_country = ET.SubElement(cac_address, 'cac:Country')
        ET.SubElement(cac_country, 'cbc:IdentificationCode').text = str(template_data['CustomerCountryCode'])
        cbc_country_name = ET.SubElement(cac_country, 'cbc:Name')
        cbc_country_name.text = str(template_data['CustomerCountryName'])
        cbc_country_name.set('languageID', 'es')

        cac_party_tax_scheme = ET.SubElement(cac_party, 'cac:PartyTaxScheme')
        ET.SubElement(cac_party_tax_scheme, 'cbc:RegistrationName').text = str(template_data['CustomerPartyName'])

        cbc_company_id = ET.SubElement(cac_party_tax_scheme, 'cbc:CompanyID')
        cbc_company_id.text = str(template_data['CustomerID'])
        cbc_company_id.set('schemeAgencyID', '195')
        cbc_company_id.set('schemeAgencyName', 'CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)')
        cbc_company_id.set('schemeID', str(template_data['CustomerschemeID']))
        cbc_company_id.set('schemeName', '31')

        ET.SubElement(cac_party_tax_scheme, 'cbc:TaxLevelCode').text = str(template_data['CustomerTaxLevelCode'])

        cac_registration_address = ET.SubElement(cac_party_tax_scheme, 'cac:RegistrationAddress')
        ET.SubElement(cac_registration_address, 'cbc:ID').text = str(template_data['CustomerCityCode'])
        ET.SubElement(cac_registration_address, 'cbc:CityName').text = str(template_data['CustomerCityName'])
        ET.SubElement(cac_registration_address, 'cbc:CountrySubentity').text = str(template_data['CustomerCountrySubentity'])
        ET.SubElement(cac_registration_address, 'cbc:CountrySubentityCode').text = str(template_data['CustomerCountrySubentityCode'])

        cac_address_line = ET.SubElement(cac_registration_address, 'cac:AddressLine')
        ET.SubElement(cac_address_line, 'cbc:Line').text = str(template_data['CustomerLine'])

        cac_country = ET.SubElement(cac_registration_address, 'cac:Country')
        ET.SubElement(cac_country, 'cbc:IdentificationCode').text = str(template_data['CustomerCountryCode'])
        cbc_country_name = ET.SubElement(cac_country, 'cbc:Name')
        cbc_country_name.text = str(template_data['CustomerCountryName'])
        cbc_country_name.set('languageID', 'es')

        cac_tax_scheme = ET.SubElement(cac_party_tax_scheme, 'cac:TaxScheme')
        ET.SubElement(cac_tax_scheme, 'cbc:ID').text = str(template_data['TaxSchemeID'])
        ET.SubElement(cac_tax_scheme, 'cbc:Name').text = str(template_data['TaxSchemeName'])

        cac_party_legal_entity = ET.SubElement(cac_party, 'cac:PartyLegalEntity')
        ET.SubElement(cac_party_legal_entity, 'cbc:RegistrationName').text = str(template_data['CustomerPartyName'])

        cbc_company_id = ET.SubElement(cac_party_legal_entity, 'cbc:CompanyID')
        cbc_company_id.text = str(template_data['CustomerID'])
        cbc_company_id.set('schemeAgencyID', '195')
        cbc_company_id.set('schemeAgencyName', 'CO, DIAN (Dirección de Impuestos y Aduanas Nacionales)')
        cbc_company_id.set('schemeID', str(template_data['CustomerschemeID']))
        cbc_company_id.set('schemeName', '31')

        cac_contact = ET.SubElement(cac_party, 'cac:Contact')
        ET.SubElement(cac_contact, 'cbc:ElectronicMail').text = str(template_data['CustomerElectronicMail'])

        cac_person = ET.SubElement(cac_party, 'cac:Person')
        ET.SubElement(cac_person, 'cbc:FirstName').text = str(template_data['Firstname'])

        # Agregar el elemento cac:PaymentMeans
        cac_payment_means = ET.SubElement(root, 'cac:PaymentMeans')
        ET.SubElement(cac_payment_means, 'cbc:ID').text = str(template_data['PaymentMeansID'])
        ET.SubElement(cac_payment_means, 'cbc:PaymentMeansCode').text = str(template_data['PaymentMeansCode'])
        ET.SubElement(cac_payment_means, 'cbc:PaymentDueDate').text = str(template_data['PaymentDueDate'])
        ET.SubElement(cac_payment_means, 'cbc:PaymentID').text = '1234'

        if str(template_data['CurrencyID']) != 'COP':
            cac_payment_exchange_rate = ET.SubElement(root, 'cac:PaymentExchangeRate')
            ET.SubElement(cac_payment_exchange_rate, 'cbc:SourceCurrencyCode').text = str(template_data['CurrencyID'])
            ET.SubElement(cac_payment_exchange_rate, 'cbc:SourceCurrencyBaseRate').text = '1.00'
            ET.SubElement(cac_payment_exchange_rate, 'cbc:TargetCurrencyCode').text = 'COP'
            ET.SubElement(cac_payment_exchange_rate, 'cbc:TargetCurrencyBaseRate').text = '1.00'
            ET.SubElement(cac_payment_exchange_rate, 'cbc:CalculationRate').text = str(template_data['CalculationRate'])
            ET.SubElement(cac_payment_exchange_rate, 'cbc:Date').text = str(template_data['DateRate'])

        # Agregar los elementos de impuestos y totales
        ET.SubElement(root, 'data_taxs_xml')
        # Agregar el elemento cac:LegalMonetaryTotal
        cac_legal_monetary_total = ET.SubElement(root, 'cac:LegalMonetaryTotal')
        cbc_line_extension_amount = ET.SubElement(cac_legal_monetary_total, 'cbc:LineExtensionAmount')
        cbc_line_extension_amount.text = str(template_data['TotalLineExtensionAmount'])
        cbc_line_extension_amount.set('currencyID', str(template_data['CurrencyID']))

        cbc_tax_exclusive_amount = ET.SubElement(cac_legal_monetary_total, 'cbc:TaxExclusiveAmount')
        cbc_tax_exclusive_amount.text = str(template_data['TotalTaxExclusiveAmount'])
        cbc_tax_exclusive_amount.set('currencyID', str(template_data['CurrencyID']))

        cbc_tax_inclusive_amount = ET.SubElement(cac_legal_monetary_total, 'cbc:TaxInclusiveAmount')
        cbc_tax_inclusive_amount.text = str(template_data['TotalTaxInclusiveAmount'])
        cbc_tax_inclusive_amount.set('currencyID', str(template_data['CurrencyID']))

        cbc_payable_amount = ET.SubElement(cac_legal_monetary_total, 'cbc:PayableAmount')
        cbc_payable_amount.text = str(template_data['PayableAmount'])
        cbc_payable_amount.set('currencyID', str(template_data['CurrencyID']))

        ET.SubElement(root, 'data_lines_xml')

        xml_string = ET.tostring(root, encoding='utf-8', method='xml').decode('utf-8')
        xml_string = xml_string.replace('<data_taxs_xml />', str(template_data['data_taxs_xml']))
        xml_string = xml_string.replace('<data_lines_xml />', str(template_data['data_lines_xml']))
        return xml_string
    


    def _generate_data_invoice_document_xml(self, dc, dcd, data_taxs_xml,  data_lines_xml,  CUFE):
        data = {
            "InvoiceAuthorization": dcd["InvoiceAuthorization"],
            "StartDate": dcd["StartDate"],
            "EndDate": dcd["EndDate"],
            "Prefix": dcd["Prefix"],
            "From": dcd["From"],
            "To": dcd["To"],
            "IdentificationCode": dc["IdentificationCode"],
            "ProviderID": dc["ProviderID"],
            "SoftwareProviderID": dc["SoftwareProviderID"],
            "SoftwareProviderSchemeID": dc["SoftwareProviderSchemeID"],
            "SoftwareID": dc["SoftwareID"],
            "SoftwareSecurityCode": dc["SoftwareSecurityCode"],
            "InvoiceID": dcd["InvoiceID"],
            "UUID": CUFE,
            "UBLVersionID": dc["UBLVersionID"],
            "CustomizationID": dc["CustomizationID"],
            "ProfileID": dc["ProfileID"],
            "ProfileExecutionID": dc["ProfileExecutionID"],
            "InvoiceID": dcd["InvoiceID"],
            "IssueDate": dcd["IssueDate"],
            "Notes": dcd["Notes"],
            "IssueTime": dcd["IssueTime"],
            "CreditNoteTypeCode": dcd["CreditNoteTypeCode"],  
            "DebitNoteTypeCode": dcd["DebitNoteTypeCode"],       
            "InvoiceTypeCode": dcd["InvoiceTypeCode"],
            "DocumentCurrencyCode": dcd["DocumentCurrencyCode"],
            "LineCountNumeric": dcd["LineCountNumeric"],
            "SupplierAdditionalAccountID": dc["SupplierAdditionalAccountID"],
            "SupplierPartyName": dc["SupplierPartyName"],
            "SupplierCityCode": dc["SupplierCityCode"],
            "SupplierCityName": dc["SupplierCityName"],
            "SupplierPostal": dc.get("SupplierPostal",''),
            "SupplierCountrySubentity": dc["SupplierCountrySubentity"],
            "SupplierCountrySubentityCode": dc["SupplierCountrySubentityCode"],
            "SupplierLine": dc["SupplierLine"],
            "SupplierCountryCode": dc["SupplierCountryCode"],
            "SupplierCountryName": dc["SupplierCountryName"],
            "schemeID": dc["schemeID"],
            "SupplierTaxLevelCode": dc["SupplierTaxLevelCode"],
            "TaxSchemeID": dc["TaxSchemeID"],
            "TaxSchemeName": dc["TaxSchemeName"],
            "SupplierElectronicMail": dc["SupplierElectronicMail"],
            "SupplierSchemeID":  dc["SupplierSchemeID"],   
            "CustomerTaxSchemeID": dcd["CustomerTaxSchemeID"],
            "CustomerTaxSchemeName": dcd["CustomerTaxSchemeName"],
            'ret_total_values':dcd['ret_total_values'],
            'tax_total_values':dcd['tax_total_values'],
            'invoice_lines':dcd['invoice_lines'],
            "CustomerAdditionalAccountID": dcd["CustomerAdditionalAccountID"],
            "CustomerPartyName": dcd["CustomerPartyName"],
            "CustomerschemeID": dcd["CustomerschemeID"],
            "CustomerCityCode": dcd["CustomerCityCode"],
            "CustomerCityName": dcd["CustomerCityName"],
            "CustomerCountrySubentity": dcd["CustomerCountrySubentity"],
            "CustomerCountrySubentityCode": dcd["CustomerCountrySubentityCode"],
            "CustomerLine": dcd["CustomerLine"],
            "CustomerCountryCode": dcd["CustomerCountryCode"],
            "CustomerCountryName": dcd["CustomerCountryName"],
            "CustomerID": dcd["CustomerID"],
            "CustomerTaxLevelCode": dcd["CustomerTaxLevelCode"],
            "CustomerElectronicMail": dcd["CustomerElectronicMail"],
            "Firstname": dcd["Firstname"],
            "PaymentMeansID": dcd["PaymentMeansID"],
            "PaymentMeansCode": dcd["PaymentMeansCode"],
            "PaymentDueDate": dcd["PaymentDueDate"],
            "data_taxs_xml": data_taxs_xml,
            "TotalLineExtensionAmount": dcd["LineExtensionAmount"],
            "TotalTaxExclusiveAmount": dcd["TaxExclusiveAmount"],
            "TotalTaxInclusiveAmount": dcd["TotalTaxInclusiveAmount"],
            'rounding_charge' : dcd['rounding_charge'] ,
            'rounding_discount' : dcd['rounding_discount'] ,
            "PayableAmount": dcd["PayableAmount"],
            'rete_fue_cop': dcd['rete_fue_cop'],
            'rete_iva_cop': dcd['rete_iva_cop'],
            'rete_ica_cop': dcd['rete_ica_cop'],
            'tot_iva_cop': dcd['tot_iva_cop'],
            'tot_inc_cop': dcd['tot_inc_cop'],
            'tot_bol_cop': dcd['tot_bol_cop'],
            'imp_otro_cop': dcd['imp_otro_cop'],
            'rounding_adjustment_data': dcd['rounding_adjustment_data'],
            "data_lines_xml": data_lines_xml,
            "CurrencyID": dcd["CurrencyID"],
            "CalculationRate": dcd["CalculationRate"],
            "DateRate": dcd["DateRate"],
            "SchemeIDAdquiriente": dcd["SchemeIDAdquiriente"],
            "SchemeNameAdquiriente": dcd["SchemeNameAdquiriente"],
            "SupplierSchemeName": dcd["SupplierSchemeName"],
            "IDAdquiriente": dcd["IDAdquiriente"],
            "SupplierCityNameSubentity": dc["SupplierCityNameSubentity"],
            "URLQRCode": dc.get("URLQRCode", ""),
            "DeliveryAddress": dc["DeliveryAddress"],
            "ResponseCode": dcd["ResponseCodeDebitNote"],
            "DescriptionDebitCreditNote": dcd["DescriptionDebitCreditNote"],
            "DiscrepancyResponseID": dc.get("DiscrepancyResponseID", ""),
            "DiscrepancyResponseCode": dc.get("DiscrepancyResponseCode", ""),
            "DiscrepancyResponseDescription": dc.get( "DiscrepancyResponseDescription", "" ),
            "InvoiceReferenceID": dcd.get("InvoiceReferenceID", ""),
            "InvoiceReferenceUUID": dcd.get("InvoiceReferenceUUID", ""),
            "InvoiceReferenceDate": dcd.get("InvoiceReferenceDate", ""),
            "ResponseCodeCreditNote": dcd.get("ResponseCodeCreditNote", ""),
            'IndustryClassificationCode':dc['IndustryClassificationCode'],
            
        }
        return data
    

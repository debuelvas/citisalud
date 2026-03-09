/** @odoo-module */
import { registry } from "@web/core/registry";
import { usePopover } from "@web/core/popover/popover_hook";
import { Component } from "@odoo/owl";

export class PaymentInfoPopover extends Component {
    static template = 'custom_account_treasury.PaymentInfoPopoverContent';

    formatAmount(amount, currencyName) {
        const value = parseFloat(amount || 0);
        return new Intl.NumberFormat('es-CO', {
            style: 'currency',
            currency: currencyName || 'COP',
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        }).format(value)
        .replace('COP', '');
    }

    formatPercentage(value) {
        return (parseFloat(value) || 0).toFixed(2) + '%';
    }

    get hasDetails() {
        return this.props.info && Object.keys(this.props.info).length > 0;
    }

    get formattedOriginalAmount() {
        const amount = this.formatAmount(this.props.info?.original_amount);
        const currency = this.props.info?.original_currency || 'COP';
        return `${amount} ${currency}`;
    }

    get formattedExchangeRate() {
        return (this.props.info?.exchange_rate || 1).toFixed(2);
    }

    get formattedConvertedAmount() {
        const amount = this.formatAmount(this.props.info?.converted_amount);
        const currency = this.props.info?.company_currency || 'COP';
        return `${amount} ${currency}`;
    }

    get formattedPaidAmount() {
        const amount = this.formatAmount(this.props.info?.paid_amount);
        const currency = this.props.info?.original_currency || 'COP';
        return `${amount} ${currency}`;
    }

    get formattedResidualAmount() {
        const amount = this.formatAmount(this.props.info?.residual_amount);
        const currency = this.props.info?.original_currency || 'COP';
        return `${amount} ${currency}`;
    }
    get formattedResidualAmountCompany() {
        const residualInCompanyCurrency = this.props.info?.residual_amount * this.props.info?.exchange_rate;
        const amount = this.formatAmount(residualInCompanyCurrency);
        const currency = this.props.info?.company_currency || 'COP';
        return `${amount} ${currency}`;
    }

    formatTaxAmount(tax) {
        const amount = this.formatAmount(tax.amount);
        const currency = this.props.info?.original_currency || 'COP';
        return `${amount} ${currency} (${this.formatPercentage(tax.rate)})`;
    }
}

export class PaymentInfoWidget extends Component {
    static template = 'custom_account_treasury.PaymentInfoButton';
    static components = { Popover: PaymentInfoPopover };

    setup() {
        this.paymentInfo = {};
        this.updatePaymentInfo();
        const position = "right";
        this.popover = usePopover(PaymentInfoPopover, { position });
    }

    updatePaymentInfo() {
        const rawValue = this.props.record.data[this.props.name];
        if (rawValue) {
            try {
                if (typeof rawValue === 'string') {
                    this.paymentInfo = JSON.parse(rawValue);
                } else {
                    this.paymentInfo = rawValue;
                }
            } catch (error) {
                console.error("Error parsing payment_details:", error);
                this.paymentInfo = {};
            }
        } else {
            this.paymentInfo = {};
        }
    }

    showPopup(ev) {
        ev.stopPropagation();
        this.popover.open(ev.currentTarget, { 
            info: this.paymentInfo,
            record: this.props.record 
        });
    }
}

export const paymentInfoWidget = {
    component: PaymentInfoWidget,
    supportedTypes: ['json', 'char'],
};

registry.category("fields").add("payment_details", paymentInfoWidget);
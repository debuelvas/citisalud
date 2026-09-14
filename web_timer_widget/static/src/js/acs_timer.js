/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { parseFloatTime } from "@web/views/fields/parsers";
import { useInputField } from "@web/views/fields/input_field_hook";
import { useRecordObserver } from "@web/model/relational_model/utils";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component, useState, onWillUpdateProps, onWillStart, onWillDestroy } from "@odoo/owl";

function AcsformatMinutes(value) {
    if (value === false) {
        return "";
    }
    const isNegative = value < 0;
    if (isNegative) {
        value = Math.abs(value);
    }
    let hour = value/60;
    let rhour = Math.floor(hour);
    let min = value % 60;
    let rmin = Math.floor(min);
    let sec = Math.round((value % 1) * 60)
    rhour = `${rhour}`.padStart(2, "0");
    rmin = `${rmin}`.padStart(2, "0");
    sec = `${sec}`.padStart(2, "0");
    return `${isNegative ? "-" : ""}${rhour}:${rmin}:${sec}`;
}

export class AcsTimer extends Component {
    static template = "web_timer_widget.AcsTimer";
    static props = {
        value: { type: Number },
        ongoing: { type: Boolean, optional: true },
    };
    static defaultProps = { ongoing: false };

    setup() {
        this.state = useState({
            // duration is expected to be given in minutes
            duration: this.props.value,
        });
        this.lastDateTime = Date.now();
        this.ongoing = this.props.ongoing;
        onWillStart(() => {
            if (this.ongoing) {
                this._runTimer();
                this._runSleepTimer();
            }
        });
        onWillUpdateProps((nextProps) => {
            const rerun = !this.ongoing && nextProps.ongoing;
            this.ongoing = nextProps.ongoing;
            if (rerun) {
                this.state.duration = nextProps.value;
                this._runTimer();
                this._runSleepTimer();
            }
        });
        onWillDestroy(() => clearTimeout(this.timer));
    }

    get durationFormatted() {
        return AcsformatMinutes(this.state.duration);
    }

    _runTimer() {
        this.timer = setTimeout(() => {
            if (this.ongoing) {
                this.state.duration += 1 / 60;
                this._runTimer();
            }
        }, 1000);
    }

    //updates the time when the computer wakes from sleep mode
    _runSleepTimer() {
        this.timer = setTimeout(async () => {
            const diff = Date.now() - this.lastDateTime - 10000;
            if (diff > 1000) {
                this.state.duration += diff / (1000 * 60);
            }
            this.lastDateTime = Date.now();
            this._runSleepTimer();
        }, 10000);
    }
}

class AcsTimerField extends Component {
    static template = "web_timer_widget.AcsTimerField";
    static components = { AcsTimer };
    static props = {
        ...standardFieldProps,
        acs_timer_start_field: String,
        acs_timer_stop_field: String,
        duration_field: String,
    };

    setup() {
        this.orm = useService("orm");
        useInputField({
            getValue: () => this.durationFormatted,
            refName: "numpadDecimal",
            parse: (v) => parseFloatTime(v),
        });

        useRecordObserver(async (record) => {
            this.duration = record.data[this.props.name];
        })

        onWillDestroy(() => clearTimeout(this.timer));
    }

    get durationFormatted() {
        if (this.props.record.data[this.props.name] != this.duration && this.props.record.dirty) {
            this.duration = this.props.record.data[this.props.name];
        }
        return AcsformatMinutes(this.duration);
    }

    get ongoing() {
        let timer_running;
        timer_running = false;
        if (this.props.record.data[this.props.acs_timer_start_field]){
            timer_running = true;
        }
        if (this.props.record.data[this.props.acs_timer_start_field] && this.props.record.data[this.props.acs_timer_stop_field]){
            timer_running = false;
        }
        return timer_running;
    }
}

export const acsTimerField = {
    component: AcsTimerField,
    supportedTypes: ["float"],
    extractProps: ({ attrs, options }) => ({
        acs_timer_start_field: options.widget_start_field,
        acs_timer_stop_field: options.widget_stop_field,
        duration_field: options.duration_field,
    }),
};

registry.category("fields").add("AcsTimer", acsTimerField);
registry.category("formatters").add("AcsTimer", AcsformatMinutes);

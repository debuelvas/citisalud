/** @odoo-module **/
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component } from "@odoo/owl";
import { formatMonetary } from "@web/views/fields/formatters";
import { useService } from "@web/core/utils/hooks";

export class ContractInfoField extends Component {
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.formatMonetary = formatMonetary;
        console.log("Setup ContractInfoField iniciado");
        
        // Add event listener for route changes
        //this.env.bus.addEventListener('ROUTE_CHANGE', this.onRouteChange.bind(this));
        
        this.loadAllData();
    }

    willUpdateProps(nextProps) {
        const currentContractId = this.props.record.data.contract_id?.[0];
        const nextContractId = nextProps.record.data.contract_id?.[0];
        
        console.log("Current contract:", currentContractId);
        console.log("Next contract:", nextContractId);
        
        if (currentContractId !== nextContractId) {
            console.log("Contract changed, reloading data");
            this.contractData = null;
            this.loadAllData();
        }
    }

    async loadAllData() {
        console.log("Iniciando carga de datos");
        const contract = this.props.record.data.contract_id;
        if (!contract || !contract[0]) {
            console.log("No hay contrato seleccionado");
            return;
        }

        try {
            // Load base contract data
            console.log("Cargando datos base del contrato:", contract[0]);
            const [contractData] = await this.orm.read(
                'hr.contract',
                [contract[0]],
                ['employee_id']
            );

            if (!contractData.employee_id) {
                console.log("No hay empleado asociado al contrato");
                return;
            }

            // Load entities
            console.log("Cargando entidades del empleado:", contractData.employee_id[0]);
            const entities = await this.orm.searchRead(
                'hr.contract.setting.history',
                [['employee_id', '=', contractData.employee_id[0]]],
                ['contrib_id', 'partner_id', 'date_change', 'is_transfer'],
                { order: 'date_change desc' }
            );

            // Load complete contract data
            const [fullContract] = await this.orm.read(
                'hr.contract',
                [contract[0]],
                [
                    'name', 'state', 'contract_type', 'date_start', 'date_end',
                    'wage', 'department_id', 'job_id', 'modality_salary',
                    'risk_id', 'retention_procedure', 'subcontract_type',
                    'economic_activity_level_risk_id'
                ]
            );

            // Load ARL data if exists
            let riskInfo = null;
            if (fullContract.risk_id) {
                [riskInfo] = await this.orm.read(
                    'hr.contract.risk',
                    [fullContract.risk_id[0]],
                    ['name', 'percent', 'code']
                );
            }

            // Load employee data
            const [employee] = await this.orm.read(
                'hr.employee',
                [contractData.employee_id[0]],
                ['tipo_coti_id', 'subtipo_coti_id']
            );

            // Update state with all information
            this.contractData = {
                ...fullContract,
                employee: employee,
                entities: this.getEntitiesItems(entities),
                risk_info: riskInfo
            };

            this.render();
        } catch (error) {
            console.error("Error al cargar datos:", error);
            this.notification.add(_t("Error al cargar información del contrato"), {
                type: 'danger',
            });
        }
    }

    getInfo() {
        if (!this.contractData) {
            return { contract: null, sections: [] };
        }

        return {
            contract: this.contractData,
            entities: this.contractData.entities,
            tipoCotizante: this.contractData.employee?.tipo_coti_id?.[1] || '-',
            subtipoCotizante: this.contractData.employee?.subtipo_coti_id?.[1] || '-',
            sections: [
                {
                    title: "Información Principal",
                    icon: "fa fa-file-contract",
                    rows: [
                        [
                            {
                                label: "Tipo de Contrato",
                                value: this.getContractTypeLabel(this.contractData.contract_type),
                                icon: "fa fa-file",
                                colSize: 6
                            },
                            {
                                label: "Subtipo de Contrato",
                                value: this.getSubcontractTypeLabel(this.contractData.subcontract_type),
                                icon: "fa fa-file-alt",
                                colSize: 6
                            }
                        ],
                        [
                            {
                                label: "Fecha Inicio",
                                value: this.formatDate(this.contractData.date_start),
                                icon: "fa fa-calendar",
                                colSize: 6
                            },
                            {
                                label: "Fecha Fin",
                                value: this.formatDate(this.contractData.date_end) || 'Indefinido',
                                icon: "fa fa-calendar-times",
                                colSize: 6
                            }
                        ],
                        [
                            {
                                label: "Salario Base",
                                value: this.formatMonetary(this.contractData.wage, {
                                    currencyId: this.props.record.data.currency_id?.[0]
                                }),
                                is_monetary: true,
                                icon: "fa fa-money-bill",
                                colSize: 6
                            },
                            {
                                label: "Tipo de Salario",
                                value: this.getSalaryTypeLabel(this.contractData.modality_salary),
                                icon: "fa fa-coins",
                                colSize: 6
                            }
                        ]
                    ]
                },
                {
                    title: "Estado y Retención",
                    icon: "fa fa-info-circle",
                    items: [
                        {
                            label: "Estado",
                            value: this.getStateLabel(this.contractData.state),
                            is_state: true,
                            icon: "fa fa-check-circle"
                        },
                        {
                            label: "Nivel ARL",
                            value: this.contractData.risk_info ? 
                                `${this.contractData.risk_info.name} (${this.contractData.risk_info.percent}%)` : '-',
                            icon: "fa fa-shield-alt"
                        },
                        {
                            label: "Retención",
                            value: this.getRetentionLabel(this.contractData.retention_procedure),
                            icon: "fa fa-percentage"
                        },
                        {
                            label: "Actividad Económica",
                            value: this.formatEconomicActivity(),
                            icon: "fa fa-industry",
                            colSize: 6
                        }
                    ]
                }
            ]
        };
    }

    getEntitiesItems(entities) {
        const entitiesByType = {};
        const iconMapping = {
            'EPS': { icon: 'fa-hospital-symbol', label: 'EPS' },
            'Pensión': { icon: 'fa-piggy-bank', label: 'Pensión' },
            'ARL': { icon: 'fa-shield-alt', label: 'ARL' },
            'CCF': { icon: 'fa-building', label: 'Caja Compensación' }
        };

        entities.forEach(entity => {
            const type = entity.contrib_id[1];
            if (!entitiesByType[type]) {
                const entityConfig = iconMapping[type] || { icon: 'fa-building', label: type };
                entitiesByType[type] = {
                    label: entityConfig.label,
                    icon: `fa ${entityConfig.icon}`,
                    value: entity.partner_id[1],
                    date: this.formatDate(entity.date_change),
                    is_transfer: entity.is_transfer
                };
            }
        });

        return Object.values(entitiesByType);
    }

    formatEconomicActivity() {
        const activity = this.contractData.economic_activity_level_risk_id;
        return activity ? `${activity[1]} (Nivel ${activity[0]})` : '-';
    }

    getStateLabel(state) {
        return {
            'draft': 'Nuevo',
            'open': 'En Proceso',
            'finished': 'Finalizado Por Liquidar',
            'close': 'Vencido',
            'cancel': 'Cancelado(a)'
        }[state] || state;
    }

    getStateClass(state) {
        return {
            'draft': 'bg-warning',
            'open': 'bg-success',
            'finished': 'bg-info',
            'close': 'bg-danger',
            'cancel': 'bg-secondary'
        }[state] || 'bg-secondary';
    }

    getContractTypeLabel(type) {
        return {
            'obra': 'Contrato por Obra o Labor',
            'fijo': 'Contrato a Término Fijo',
            'fijo_parcial': 'Contrato a Término Fijo Tiempo Parcial',
            'indefinido': 'Contrato a Término Indefinido',
            'aprendizaje': 'Contrato de Aprendizaje',
            'temporal': 'Contrato Temporal'
        }[type] || type;
    }

    getSubcontractTypeLabel(type) {
        return {
            'obra_parcial': 'Parcial',
            'obra_integral': 'Parcial Integral'
        }[type] || type;
    }

    getSalaryTypeLabel(type) {
        return {
            'basico': 'Básico',
            'integral': 'Integral',
            'sostenimiento': 'Sostenimiento',
            'aprendiz': 'Aprendiz',
            'practicante': 'Practicante'
        }[type] || type;
    }

    getRetentionLabel(procedure) {
        return {
            '100': 'Procedimiento 1',
            '102': 'Procedimiento 2',
            'fixed': 'Valor fijo'
        }[procedure] || procedure;
    }

    formatDate(date) {
        if (!date) return '';
        return new Date(date).toLocaleDateString('es-CO', {
            year: 'numeric',
            month: 'long',
            day: 'numeric'
        });
    }
}

ContractInfoField.template = "lavish_hr_payroll.ContractInfoField";

export const contractInfoField = {
    component: ContractInfoField,
    supportedTypes: ["char"],
};

registry.category("fields").add("contract_info", contractInfoField);
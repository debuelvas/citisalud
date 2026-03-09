from odoo import tools
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

class hr_report_expenses_employee(models.Model):
    _name = "hr.report.expenses.employee"
    _description = "Informe de costos por empleado"
    _auto = False
    _order = 'fecha_liquidacion,compania,sucursal,empleado,estructura,secuencia_regla'


    estructura = fields.Char(string='Estructura', readonly=True)
    liquidacion = fields.Char(string='Liquidación', readonly=True)
    estado_de_liquidacion = fields.Char(string='Estado de liquidación', readonly=True)
    descripcion = fields.Char(string='descripción', readonly=True)
    contrato = fields.Char(string='Contrato', readonly=True)
    estado_de_contrato = fields.Char(string='Estado de contrato', readonly=True)
    fecha_liquidacion = fields.Date(string='Fecha de liquidacón', readonly=True)
    fecha_inicial = fields.Date(string='Fecha inicial', readonly=True)
    fecha_final = fields.Date(string='Fecha final', readonly=True)
    compania = fields.Char(string='Compañia', readonly=True)
    sucursal = fields.Char(string='Sucursal', readonly=True)
    identificacion = fields.Char(string='Identificación', readonly=True)
    empleado = fields.Char(string='Empleado', readonly=True)
    ubicacion_laboral = fields.Char(string='Ubicación laboral', readonly=True)
    cuenta_analitica = fields.Char(string='Cuenta Analítica', readonly=True)
    proyecto = fields.Char(string='Proyecto', readonly=True)
    secuencia_contrato = fields.Char(string='Secuencia del contrato', readonly=True)
    categoria_regla = fields.Char(string='Categoria', readonly=True)
    regla_salarial = fields.Char(string='Regla', readonly=True)
    secuencia_regla = fields.Integer(string='Secuencia regla', readonly=True)
    entidad = fields.Char(string='Entidad', readonly=True)
    unidades = fields.Integer(string='Cantidad', readonly=True)
    # Valores
    valor = fields.Float(string='Valor', default=0.0)

    @api.model
    def _select(self):
        pass
        #return '''
        #     Select row_number() over(order by a.fecha_liquidacion,a.fecha_inicial,a.fecha_final,a.compania,a.sucursal, a.empleado, a.secuencia_regla) as id,
		# 	estructura,liquidacion,estado_de_liquidacion,descripcion,contrato,estado_de_contrato,fecha_liquidacion,fecha_inicial,fecha_final,compania,sucursal,identificacion,empleado,ubicacion_laboral,
        #             cuenta_analitica,proyecto,secuencia_contrato,categoria_regla,regla_salarial,secuencia_regla,entidad,unidades,valor             
        #     From ( 
		# 	--NOMINA
        #     Select upper(a.struct_process) as estructura,a."number" as liquidacion,
        #     case when a."state" = 'draft' then 'Borrador'
		# 				else case when a."state" = 'verify' then 'En espera'
		# 					else case when a."state" = 'done' then 'Hecho'
		# 						else case when a."state" = 'draft' then 'Nuevo'
		# 							else case when a."state" = 'cancel' then 'Rechazada'
		# 								else ''
		# 								end
		# 							end
		# 						end
		# 					end
		# 				end as estado_de_liquidacion,
        #     a."name" as descripcion,e."name" as contrato,
		# 		case when e."state" = 'open' then 'En proceso'
		# 				else case when e."state" = 'close' then 'Expirado'
		# 					else case when e."state" = 'finished' then 'Finalizado'
		# 						else case when e."state" = 'draft' then 'Nuevo'
		# 							else case when e."state" = 'cancel' then 'Cancelado(a)'
		# 								else ''
		# 								end
		# 							end
		# 						end
		# 					end
		# 				end as estado_de_contrato,
        #             a.date_to as fecha_liquidacion,a.date_from as fecha_inicial,a.date_to as fecha_final,
        #             b."name" as compania,coalesce(h."name",'') as sucursal,
        #             c.identification_id as identificacion,c."name" as empleado,
        #             coalesce(i."name",'') as ubicacion_laboral, coalesce(k."name",'') as cuenta_analitica, c."info_project" as proyecto,
        #             e."sequence" as secuencia_contrato,
        #             g."name" as categoria_regla, f."name" as regla_salarial, f."sequence" as secuencia_regla,coalesce(m."name",'') as entidad,
        #             aa.quantity as unidades, 
        #             aa.total as valor                    
        #     From hr_payslip as a
        #     inner join hr_payslip_line as aa on a.id = aa.slip_id 
        #     inner join res_company as b on a.company_id = b.id
        #     inner join hr_employee as c on a.employee_id = c.id
        #     inner join res_partner as d on c.work_contact_id = d.id
        #     inner join hr_contract as e on a.contract_id = e.id
        #     inner join hr_salary_rule as f on aa.salary_rule_id = f.id 
        #     inner join hr_salary_rule_category as g on f.category_id = g.id
        #     left join lavish_res_branch as h on c.branch_id = h.id
        #     left join res_partner as i on c.address_id = i.id            
        #     left join account_analytic_account as k on a.analytic_account_id  = k.id
        #     left join hr_employee_entities as l on aa.entity_id = l.id
        #     left join res_partner as m on l.partner_id = m.id    
        #     UNION ALL
		# 	--ACUMULADOS NOMINA
        #     Select 'ACUMULADOS' as estructura,'SLIP/00000' as liquidacion,'' as estado_de_liquidacion,'Tabla de acumulados' as descripcion,'' as contrato,'' as estado_de_contrato,
		#             a."date" as fecha_liquidacion,a."date" as fecha_inicial,a."date" as fecha_final,
        #             c."name" as compania,coalesce(h."name",'') as sucursal,
        #             b.identification_id as identificacion,b."name" as empleado,
        #             coalesce(i."name",'') as ubicacion_laboral, coalesce(k."name",'') as cuenta_analitica,b.info_project as proyecto, 
        #             '' as secuencia_contrato,g."name" as categoria_regla, f."name" as regla_salarial, f."sequence" as secuencia_regla,'' as entidad,
        #             1 as unidades, 
        #             a.amount as valor                    
        #     from hr_accumulated_payroll as a 
        #     inner join hr_employee as b on a.employee_id = b.id 
        #     inner join res_company as c on b.company_id = c.id
        #     inner join res_partner as d on b.work_contact_id = d.id
        #     inner join hr_salary_rule as f on a.salary_rule_id = f.id 
        #     inner join hr_salary_rule_category as g on f.category_id = g.id
        #     left join lavish_res_branch as h on b.branch_id = h.id
        #     left join res_partner as i on b.address_id = i.id            
        #     left join account_analytic_account as k on b.analytic_account_id  = k.id
		# 	UNION all			
		# 	--SEGURIDAD SOCIAL
		# 	Select 'SEGURIDAD SOCIAL' as estructura,'SS/00000' as liquidacion,
		# 			case when a."state" = 'draft' then 'Borrador'
		# 				else case when a."state" = 'done' then 'Realizado'
		# 					else case when a."state" = 'accounting' then 'Contabilizado'
		# 						else ''
		# 					end
		# 				end
		# 			end as estado_de_liquidacion,'Seguridad Social' as descripcion,hc.name as contrato,
		# 			case when hc."state" = 'open' then 'En proceso'
		# 						else case when hc."state" = 'close' then 'Expirado'
		# 							else case when hc."state" = 'finished' then 'Finalizado'
		# 								else case when hc."state" = 'draft' then 'Nuevo'
		# 									else case when hc."state" = 'cancel' then 'Cancelado(a)'
		# 										else ''
		# 										end
		# 									end
		# 								end
		# 							end
		# 						end as estado_de_contrato, 
        #             ((TO_DATE(a.year||'-'||a.month||'-01','YYYY-MM-DD') + '1 month'::interval) - '1 day'::interval)::date as fecha_liquidacion,                    
        #             TO_DATE(a.year||'-'||a.month||'-01','YYYY-MM-DD') as fecha_inicial,
        #             ((TO_DATE(a.year||'-'||a.month||'-01','YYYY-MM-DD') + '1 month'::interval) - '1 day'::interval)::date as fecha_final,
        #             c."name" as compania,coalesce(h."name",'') as sucursal,
        #             b.identification_id as identificacion,b."name" as empleado,
        #             coalesce(i."name",'') as ubicacion_laboral, coalesce(k."name",'') as cuenta_analitica,coalesce(b.info_project,'') as proyecto, 
        #             hc."sequence" as secuencia_contrato,                    
        #             'SEGURIDAD SOCIAL' as categoria_regla, 
        #             cch.description as regla_salarial, 
        #             0 as secuencia_regla,
        #             case when cch.process = 'ss_empresa_salud' then coalesce(rp_salud."name",'') 
        #             	else case when cch.process = 'ss_empresa_pension' then coalesce(rp_pension."name",'') 
        #             		else case when cch.process = 'ss_empresa_arp' then coalesce(rp_arp."name",'') 
        #             			else case when cch.process = 'ss_empresa_caja' then coalesce(rp_cajacom."name",'') 
        #             				else case when cch.process = 'ss_empresa_sena' then coalesce(rp_sena."name",'')
	    #                 				else case when cch.process = 'ss_empresa_icbf' then coalesce(rp_icbf."name",'') 
	    #                 					else '' end
	    #                 				end
	    #                 			end
	    #                 		end
	    #                 	end
	    #                 end as entidad,
        #             1 as unidades,
        #             case when cch.process = 'ss_empresa_salud' then coalesce(ae."nValorSaludEmpresa",0) + coalesce(ae."nDiferenciaSalud",0)
        #             	else case when cch.process = 'ss_empresa_pension' then coalesce(ae."nValorPensionEmpresa",0) + coalesce(ae."nDiferenciaPension",0) + coalesce(ae."nValorFondoSolidaridad",0) + coalesce(ae."nValorFondoSubsistencia",0)
        #             		else case when cch.process = 'ss_empresa_arp' then coalesce(ae."nValorARP",0)
        #             			else case when cch.process = 'ss_empresa_caja' then coalesce(ae."nValorCajaCom",0)
        #             				else case when cch.process = 'ss_empresa_sena' then coalesce(ae."nValorSENA",0)
	    #                 				else case when cch.process = 'ss_empresa_icbf' then coalesce(ae."nValorICBF",0)
	    #                 					else 0 end
	    #                 				end
	    #                 			end
	    #                 		end
	    #                 	end
	    #                 end as valor                    
        #     from hr_payroll_social_security as a 
		# 	inner join hr_executing_social_security as ae on a.id = ae.executing_social_security_id
		# 	inner join hr_closing_configuration_header as cch on cch.process like '%ss_empresa%'
        #     inner join hr_employee as b on ae.employee_id = b.id 
		# 	inner join hr_contract as hc on ae.contract_id = hc.id
        #     inner join res_company as c on b.company_id = c.id
        #     inner join res_partner as d on b.work_contact_id = d.id
        #     left join lavish_res_branch as h on b.branch_id = h.id
        #     left join res_partner as i on b.address_id = i.id            
        #     left join account_analytic_account as k on b.analytic_account_id  = k.id    
        #     left join hr_employee_entities as hee_salud on ae."TerceroEPS" = hee_salud.id 
        #     left join res_partner rp_salud on hee_salud.partner_id = rp_salud.id
        #     left join hr_employee_entities as hee_pension on ae."TerceroPension" = hee_pension.id 
        #     left join res_partner rp_pension on hee_pension.partner_id = rp_pension.id
        #     left join hr_employee_entities as hee_arp on ae."TerceroARP" = hee_arp.id 
        #     left join res_partner rp_arp on hee_arp.partner_id = rp_arp.id
        #     left join hr_employee_entities as hee_cajacom on ae."TerceroCajaCom" = hee_cajacom.id 
        #     left join res_partner rp_cajacom on hee_cajacom.partner_id = rp_cajacom.id
        #     left join hr_employee_entities as hee_sena on ae."TerceroSENA" = hee_sena.id 
        #     left join res_partner rp_sena on hee_sena.partner_id = rp_sena.id
        #     left join hr_employee_entities as hee_icbf on ae."TerceroICBF" = hee_icbf.id 
        #     left join res_partner rp_icbf on hee_icbf.partner_id = rp_icbf.id             
		# 	UNION ALL
		# 	--PROVISIONES
		# 	--PROVISIONES
		# 	Select 'PROVISIONES' as estructura,'PV/00000' as liquidacion,
		# 	case when a."state" = 'draft' then 'Borrador'
		# 				else case when a."state" = 'done' then 'Realizado'
		# 					else case when a."state" = 'accounting' then 'Contabilizado'
		# 						else ''
		# 					end
		# 				end
		# 			end as estado_de_liquidacion,'Provisiones' as descripcion,hc.name as contrato,
		# 			case when hc."state" = 'open' then 'En proceso'
		# 						else case when hc."state" = 'close' then 'Expirado'
		# 							else case when hc."state" = 'finished' then 'Finalizado'
		# 								else case when hc."state" = 'draft' then 'Nuevo'
		# 									else case when hc."state" = 'cancel' then 'Cancelado(a)'
		# 										else ''
		# 										end
		# 									end
		# 								end
		# 							end
		# 						end as estado_de_contrato, 
        #             ((TO_DATE(a.year||'-'||a.month||'-01','YYYY-MM-DD') + '1 month'::interval) - '1 day'::interval)::date as fecha_liquidacion,                    
        #             TO_DATE(a.year||'-'||a.month||'-01','YYYY-MM-DD') as fecha_inicial,
        #             ((TO_DATE(a.year||'-'||a.month||'-01','YYYY-MM-DD') + '1 month'::interval) - '1 day'::interval)::date as fecha_final,
        #             c."name" as compania,coalesce(h."name",'') as sucursal,
        #             b.identification_id as identificacion,b."name" as empleado,
        #             coalesce(i."name",'') as ubicacion_laboral, coalesce(k."name",'') as cuenta_analitica,coalesce(b.info_project,'') as proyecto, 
        #             hc."sequence" as secuencia_contrato,                    
        #             'PROVISIONES' as categoria_regla, 
        #             upper(ep.provision) as regla_salarial, 0 as secuencia_regla,
        #             '' as entidad,
        #             1 as unidades, 
        #             coalesce(ep.value_balance ,0) as valor                                        
        #     from hr_executing_provisions as a 
		# 	inner join hr_executing_provisions_details as ep on a.id = ep.executing_provisions_id
        #     inner join hr_employee as b on ep.employee_id = b.id 
		# 	inner join hr_contract as hc on ep.contract_id = hc.id
        #     inner join res_company as c on b.company_id = c.id
        #     inner join res_partner as d on b.work_contact_id = d.id
        #     left join lavish_res_branch as h on b.branch_id = h.id
        #     left join res_partner as i on b.address_id = i.id            
        #     left join account_analytic_account as k on b.analytic_account_id  = k.id				
        #     ) as a		
        #     order by a.fecha_liquidacion,a.fecha_inicial,a.fecha_final,a.compania,a.sucursal, a.empleado, a.secuencia_regla      
        #    '''

    def init(self):
        # ejecutar_query
        # Query = '''
        #        %s
        # ''' % (self._select())
        #
        # raise ValidationError(_(Query))

        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute('''
            CREATE OR REPLACE VIEW %s AS (
                %s
            )
        ''' % (
            self._table, self._select()
        ))
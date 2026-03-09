# -*- coding: utf-8 -*-
{
    'name': "CitiSalud Unified Module",
    'summary': "Módulo unificado con funcionalidades de semaforización, categorías y campos INVIMA",
    'description': """
        Módulo unificado que incluye:
        
        1. **Semaforización de Lotes:**
           - Código de colores para días de caducidad
           - Rojo: < 181 días, Amarillo: 181-364 días, Verde: ≥ 365 días
        
        2. **Categorías Independientes:**
           - Categorías específicas para variantes de productos
           - Cuentas contables por categoría de variante
        
        3. **Campos INVIMA:**
           - Registro INVIMA, temperatura, referencias CitiSalud y CUPS
           - Campo city_salud_ext para referencia externa
    """,
    'author': 'Nimbutech',
    'website': 'https://www.nimbutech.com',
    'category': 'Sales/Sales',
    'version': '17.0.1.0.0',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'stock',
        'product',
        'product_expiry',
        'account',
    ],
    'data': [
        'views/product_views.xml',
    ],
    'installable': True,
    'auto_install': False,
    'application': False,
}


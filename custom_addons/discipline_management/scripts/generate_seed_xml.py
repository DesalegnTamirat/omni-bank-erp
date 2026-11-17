# -*- coding: utf-8 -*-
"""
Generate clean XML data for bunna_regulation_seed_data.xml based on current database state.
"""
import xml.sax.saxutils as saxutils
import odoo
from odoo import api, SUPERUSER_ID
from odoo.modules.registry import Registry

registry = Registry('pm_db')
with registry.cursor() as cr:
    env = api.Environment(cr, SUPERUSER_ID, {})
    articles = env['discipline.article'].search([('policy_version_id.staff_category', '=', 'non_managerial')], order='article_number')
    print('Generating XML lines...')
    xml_lines = []
    xml_lines.append('        <!-- ======================================================== -->')
    xml_lines.append('        <!-- 3. NON-MANAGERIAL ARTICLES & OFFENSES (CBA CHAPTER 8)    -->')
    xml_lines.append('        <!-- ======================================================== -->')
    
    art_rec_ids = {
        'Article 33.4': 'art_cba_33_4',
        'Article 33.5': 'art_cba_33_5',
        'Article 33.6': 'art_cba_33_6',
        'Article 33.7': 'art_cba_33_7',
        'Article 33.8': 'art_cba_33_8',
        'Article 33.9': 'art_cba_33_9',
    }
    sev_rec_ids = {
        'level_1': 'severity_level_1',
        'level_2': 'severity_level_2',
        'level_3': 'severity_level_3',
        'level_4': 'severity_level_4',
        'level_5': 'severity_level_5',
    }
    cat_rec_ids = {
        'ATT': 'cat_attendance',
        'CND': 'cat_conduct',
        'PRP': 'cat_property',
        'SUP': 'cat_supervisory',
        'FRD': 'cat_fraud',
        'FIN': 'offense_cat_financial',
        'ETH': 'offense_cat_conduct',
    }
    
    for a in articles:
        rec_id = art_rec_ids.get(a.article_number, f"art_cba_{a.id}")
        sev_ref = sev_rec_ids.get(a.severity_level, 'severity_level_3')
        xml_lines.append('')
        xml_lines.append(f"        <!-- {a.article_number}: {a.name[:50]} -->")
        xml_lines.append(f'        <record id="{rec_id}" model="discipline.article">')
        xml_lines.append(f'            <field name="article_number">{saxutils.escape(a.article_number)}</field>')
        xml_lines.append(f'            <field name="name">{saxutils.escape(a.name)}</field>')
        xml_lines.append(f'            <field name="policy_version_id" ref="policy_cba_ch8"/>')
        xml_lines.append(f'            <field name="staff_category">non_managerial</field>')
        xml_lines.append(f'            <field name="severity_level_id" ref="{sev_ref}"/>')
        xml_lines.append(f'            <field name="statutory_text">{saxutils.escape(a.statutory_text or "")}</field>')
        xml_lines.append(f'            <field name="description">{saxutils.escape(a.description or "")}</field>')
        xml_lines.append('        </record>')
        
        for off in a.offense_ids:
            safe_code = off.sub_article_code.replace('.', '_').replace('(', '_').replace(')', '').replace(' ', '_')
            off_rec_id = f"offense_cba_{safe_code}"
            cat_ref = cat_rec_ids.get(off.category_id.code, 'cat_conduct')
            off_sev_ref = sev_rec_ids.get(off.severity_level, sev_ref)
            xml_lines.append(f'        <record id="{off_rec_id}" model="discipline.offense">')
            xml_lines.append(f'            <field name="article_id" ref="{rec_id}"/>')
            xml_lines.append(f'            <field name="sub_article_code">{saxutils.escape(off.sub_article_code or "")}</field>')
            xml_lines.append(f'            <field name="name">{saxutils.escape(off.name)}</field>')
            xml_lines.append(f'            <field name="category_id" ref="{cat_ref}"/>')
            xml_lines.append(f'            <field name="staff_category">non_managerial</field>')
            xml_lines.append(f'            <field name="severity_level_id" ref="{off_sev_ref}"/>')
            xml_lines.append(f'            <field name="penalty_mode">{off.penalty_mode}</field>')
            xml_lines.append(f'            <field name="punishment_type">{off.punishment_type}</field>')
            xml_lines.append(f'            <field name="penalty_percentage">{off.penalty_percentage}</field>')
            xml_lines.append(f'            <field name="full_clause_text">{saxutils.escape(off.full_clause_text or "")}</field>')
            xml_lines.append('        </record>')
            
    with open('/mnt/extra-addons/discipline_management/data/non_mgr_snippet.xml', 'w', encoding='utf-8') as f_out:
        f_out.write('\n'.join(xml_lines))
    print(f"Snippet written successfully! Total lines: {len(xml_lines)}")

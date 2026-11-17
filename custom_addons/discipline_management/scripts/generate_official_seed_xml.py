# -*- coding: utf-8 -*-
import re
import os
import xml.sax.saxutils as saxutils

EXTRACTED_NON_MGR = '/mnt/extra-addons/discipline_management/scripts/non_managerial_extracted.txt'
MGR_DOCX = '/mnt/extra-addons/discipline_management/scripts/Managerial discipline document.docx'
OUTPUT_XML = '/mnt/extra-addons/discipline_management/data/bunna_regulation_seed_data.xml'

def escape_xml(s):
    if not s:
        return ''
    return saxutils.escape(s).replace('"', '&quot;').replace("'", '&apos;')

def clean_str(t):
    if not t:
        return ''
    t = re.sub(r'[ \t]+', ' ', t)
    t = re.sub(r'\n+', ' ', t)
    return t.strip()

# 1. Parse Non-Managerial
with open(EXTRACTED_NON_MGR, 'r', encoding='utf-8') as f:
    raw_text = f.read()

cleaned_text = re.sub(r'=== PAGE \d+ ===\s*\n\s*\d+\s*', '', raw_text)

p_33_4 = cleaned_text.find('33.4  አንደኛ ደረጃ ጥፋቶች')
p_33_5 = cleaned_text.find('33.5 2ኛ ደረጃ ጥፋቶች')
p_33_6 = cleaned_text.find('33.6 3ኛ ደረጃ ጥፋቶች')
p_33_7 = cleaned_text.find('33.7 4ኛ ደረጃ ጥፋቶች')
p_33_8 = cleaned_text.find('33.8 አምስተኛ')
p_33_9 = cleaned_text.find('33.9')
p_33_10 = cleaned_text.find('33.10')

SUB_CLAUSE_SPECS_33_4 = {
    '33.4.1': ['ሀ', 'ለ', 'ሐ'],
    '33.4.2': ['ሀ', 'ለ', 'ሐ', 'መ', 'ሠ'],
    '33.4.5': ['ሀ', 'ለ'],
    '33.4.6': ['ሀ', 'ለ', 'ሐ'],
    '33.4.8': ['ሀ', 'ለ', 'ሐ'],
    '33.4.12': ['ሀ', 'ለ'],
    '33.4.15': ['ሀ', 'ለ'],
}

def parse_33_4_items(sec_text):
    items = re.split(r'(33\.4\.\d+)', sec_text)
    clauses = []
    for i in range(1, len(items), 2):
        code = items[i]
        block = items[i+1].strip()
        lines = [l.strip() for l in block.split('\n') if l.strip()]
        header_title = lines[0] if lines else code
        # clean header_title from leading number or trailing punctuation
        header_title = clean_str(header_title)
        
        expected_subs = SUB_CLAUSE_SPECS_33_4.get(code)
        if expected_subs:
            pat = r'((?:' + '|'.join(expected_subs) + r')\s*\))'
            parts = re.split(pat, block)
            for j in range(1, len(parts), 2):
                let = parts[j].replace(')', '').strip()
                if let in expected_subs:
                    body = clean_str(parts[j+1])
                    xml_id = f"offense_cba_33_4_{code.split('.')[-1]}_{let}"
                    clauses.append({
                        'xml_id': xml_id,
                        'sub_article_code': f"{code}({let})",
                        'title': header_title,
                        'has_distinct_title': True,
                        'name': header_title,
                        'full_text': body,
                        'article_ref': 'art_cba_33_4',
                        'level_ref': 'severity_level_1',
                        'category_ref': 'cat_fraud',
                        'staff_category': 'non_managerial',
                        'punishment_type': 'dismissal',
                        'penalty_percentage': 0.0,
                        'fine_days': 0.0,
                    })
        else:
            body = clean_str('\n'.join(lines[1:]) if len(lines) > 1 else lines[0])
            xml_id = f"offense_cba_33_4_{code.split('.')[-1]}"
            clauses.append({
                'xml_id': xml_id,
                'sub_article_code': code,
                'title': header_title,
                'has_distinct_title': True,
                'name': header_title,
                'full_text': body,
                'article_ref': 'art_cba_33_4',
                'level_ref': 'severity_level_1',
                'category_ref': 'cat_fraud',
                'staff_category': 'non_managerial',
                'punishment_type': 'dismissal',
                'penalty_percentage': 0.0,
                'fine_days': 0.0,
            })
    return clauses

def parse_pure_numbered(sec_text, prefix, art_ref, level_ref, cat_ref, punish_type, pct, days):
    pat = rf'({re.escape(prefix)}\.\d+)'
    items = re.split(pat, sec_text)
    clauses = []
    for i in range(1, len(items), 2):
        code = items[i]
        num_str = code.split('.')[-1]
        body = clean_str(items[i+1].strip())
        # First phrase for fallback 'name'
        first_clause = body.split('፤')[0].split('።')[0].strip()
        if len(first_clause) > 90:
            words = first_clause.split(' ')
            first_clause = ' '.join(words[:12]) + '...'
        
        xml_id = f"offense_cba_{prefix.replace('.', '_')}_{num_str}"
        clauses.append({
            'xml_id': xml_id,
            'sub_article_code': code,
            'title': False,
            'has_distinct_title': False,
            'name': first_clause or body[:80],
            'full_text': body,
            'article_ref': art_ref,
            'level_ref': level_ref,
            'category_ref': cat_ref,
            'staff_category': 'non_managerial',
            'punishment_type': punish_type,
            'penalty_percentage': pct,
            'fine_days': days,
        })
    return clauses

clauses_33_4 = parse_33_4_items(cleaned_text[p_33_4:p_33_5])
clauses_33_5 = parse_pure_numbered(cleaned_text[p_33_5:p_33_6], '33.5', 'art_cba_33_5', 'severity_level_2', 'cat_conduct', 'final_warning_penalty', 20.0, 0.0)
clauses_33_6 = parse_pure_numbered(cleaned_text[p_33_6:p_33_7], '33.6', 'art_cba_33_6', 'severity_level_3', 'cat_conduct', 'second_warning_penalty', 10.0, 0.0)
clauses_33_7 = parse_pure_numbered(cleaned_text[p_33_7:p_33_8], '33.7', 'art_cba_33_7', 'severity_level_4', 'cat_conduct', 'first_warning_penalty', 5.0, 0.0)
clauses_33_8 = parse_pure_numbered(cleaned_text[p_33_8:p_33_9], '33.8', 'art_cba_33_8', 'severity_level_5', 'cat_conduct', 'verbal_warning', 0.0, 0.0)

# 33.9 Cash shortage
cash_shortages = [
    {
        'xml_id': 'offense_cba_33_9_1',
        'sub_article_code': '33.9.1',
        'title': 'እስከ 500.00 ብር የጥሬ ገንዘብ ጉድለት (Cash Shortage up to 500 ETB)',
        'has_distinct_title': True,
        'name': 'እስከ 500.00 ብር የጥሬ ገንዘብ ጉድለት',
        'full_text': 'እስከ 500.00 ብር የሚደርስ የጥሬ ገንዘብ ጉድለት ወይም የቆጠራ ልዩነት መፍጠር። 1ኛ ጥፋት፡ የቃል ማስጠንቀቂያ በጽሁፍ፣ 2ኛ ጥፋት፡ የመጀመሪያ ደረጃ የጽሁፍ ማስጠንቀቂያና የ5% ደመወዝ ቅጣት፣ 3ኛ ጥፋት፡ ሁለተኛ ደረጃ የጽሁፍ ማስጠንቀቂያና የ10% ደመወዝ ቅጣት፣ 4ኛ ጥፋት፡ የመጨረሻ ደረጃ የጽሁፍ ማስጠንቀቂያና የ20% ደመወዝ ቅጣት።',
        'article_ref': 'art_cba_33_9',
        'level_ref': 'severity_level_5',
        'category_ref': 'cat_operational',
        'staff_category': 'non_managerial',
        'punishment_type': 'verbal_warning',
        'penalty_percentage': 0.0,
        'fine_days': 0.0,
    },
    {
        'xml_id': 'offense_cba_33_9_2',
        'sub_article_code': '33.9.2',
        'title': 'ከ501.00 እስከ 1,000.00 ብር የጥሬ ገንዘብ ጉድለት (Cash Shortage 501 to 1,000 ETB)',
        'has_distinct_title': True,
        'name': 'ከ501.00 እስከ 1,000.00 ብር የጥሬ ገንዘብ ጉድለት',
        'full_text': 'ከ501.00 እስከ 1,000.00 ብር የሚደርስ የጥሬ ገንዘብ ጉድለት ወይም የቆጠራ ልዩነት መፍጠር። 1ኛ ጥፋት፡ የመጀመሪያ ደረጃ የጽሁፍ ማስጠንቀቂያና የ5% ደመወዝ ቅጣት፣ 2ኛ ጥፋት፡ ሁለተኛ ደረጃ የጽሁፍ ማስጠንቀቂያና የ10% ደመወዝ ቅጣት፣ 3ኛ ጥፋት፡ የመጨረሻ ደረጃ የጽሁፍ ማስጠንቀቂያና የ20% ደመወዝ ቅጣት።',
        'article_ref': 'art_cba_33_9',
        'level_ref': 'severity_level_4',
        'category_ref': 'cat_operational',
        'staff_category': 'non_managerial',
        'punishment_type': 'first_warning_penalty',
        'penalty_percentage': 5.0,
        'fine_days': 0.0,
    },
    {
        'xml_id': 'offense_cba_33_9_3',
        'sub_article_code': '33.9.3',
        'title': 'ከ1,001.00 እስከ 5,000.00 ብር የጥሬ ገንዘብ ጉድለት (Cash Shortage 1,001 to 5,000 ETB)',
        'has_distinct_title': True,
        'name': 'ከ1,001.00 እስከ 5,000.00 ብር የጥሬ ገንዘብ ጉድለት',
        'full_text': 'ከ1,001.00 እስከ 5,000.00 ብር የሚደርስ የጥሬ ገንዘብ ጉድለት ወይም የቆጠራ ልዩነት መፍጠር። 1ኛ ጥፋት፡ የመጀመሪያ ደረጃ የጽሁፍ ማስጠንቀቂያና የ5% ደመወዝ ቅጣት፣ 2ኛ ጥፋት፡ ሁለተኛ ደረጃ የጽሁፍ ማስጠንቀቂያና የ10% ደመወዝ ቅጣት፣ 3ኛ ጥፋት፡ የመጨረሻ ደረጃ የጽሁፍ ማስጠንቀቂያና የ20% ደመወዝ ቅጣት።',
        'article_ref': 'art_cba_33_9',
        'level_ref': 'severity_level_4',
        'category_ref': 'cat_operational',
        'staff_category': 'non_managerial',
        'punishment_type': 'first_warning_penalty',
        'penalty_percentage': 5.0,
        'fine_days': 0.0,
    },
    {
        'xml_id': 'offense_cba_33_9_4',
        'sub_article_code': '33.9.4',
        'title': 'ከ5,001.00 እስከ 10,000.00 ብር የጥሬ ገንዘብ ጉድለት (Cash Shortage 5,001 to 10,000 ETB)',
        'has_distinct_title': True,
        'name': 'ከ5,001.00 እስከ 10,000.00 ብር የጥሬ ገንዘብ ጉድለት',
        'full_text': 'ከ5,001.00 እስከ 10,000.00 ብር የሚደርስ የጥሬ ገንዘብ ጉድለት ወይም የቆጠራ ልዩነት መፍጠር። 1ኛ ጥፋት፡ ሁለተኛ የጽሁፍ ማስጠንቀቂያና የ10% ደመወዝ ቅጣት፣ 2ኛ ጥፋት፡ የመጨረሻ የጽሁፍ ማስጠንቀቂያና የ20% ደመወዝ ቅጣት፣ 3ኛ ጥፋት፡ ሠራተኛውን ከደረጃ ዝቅ አድርጎ ከገንዘብ ነክ ሥራ ማንሳት (Demotion)።',
        'article_ref': 'art_cba_33_9',
        'level_ref': 'severity_level_3',
        'category_ref': 'cat_operational',
        'staff_category': 'non_managerial',
        'punishment_type': 'second_warning_penalty',
        'penalty_percentage': 10.0,
        'fine_days': 0.0,
    },
    {
        'xml_id': 'offense_cba_33_9_5',
        'sub_article_code': '33.9.5',
        'title': 'ከ10,001.00 እስከ 20,000.00 ብር የጥሬ ገንዘብ ጉድለት (Cash Shortage 10,001 to 20,000 ETB)',
        'has_distinct_title': True,
        'name': 'ከ10,001.00 እስከ 20,000.00 ብር የጥሬ ገንዘብ ጉድለት',
        'full_text': 'ከ10,001.00 እስከ 20,000.00 ብር የሚደርስ የጥሬ ገንዘብ ጉድለት ወይም የቆጠራ ልዩነት መፍጠር። 1ኛ ጥፋት፡ የመጨረሻ ደረጃ የጽሁፍ ማስጠንቀቂያና የ20% ደመወዝ ቅጣት፣ 2ኛ ጥፋት፡ ሠራተኛውን ከደረጃ ዝቅ አድርጎ ከገንዘብ ነክ ሥራ ማንሳት (Demotion)።',
        'article_ref': 'art_cba_33_9',
        'level_ref': 'severity_level_2',
        'category_ref': 'cat_operational',
        'staff_category': 'non_managerial',
        'punishment_type': 'final_warning_penalty',
        'penalty_percentage': 20.0,
        'fine_days': 0.0,
    },
    {
        'xml_id': 'offense_cba_33_9_6',
        'sub_article_code': '33.9.6',
        'title': 'ከ20,001.00 ብር በላይ የጥሬ ገንዘብ ጉድለት (Cash Shortage Above 20,000 ETB)',
        'has_distinct_title': True,
        'name': 'ከ20,001.00 ብር በላይ የጥሬ ገንዘብ ጉድለት',
        'full_text': 'ከ20,001.00 ብር በላይ የጥሬ ገንዘብ ጉድለት ወይም የቆጠራ ልዩነት መፍጠር። 1ኛ ጥፋት፡ ከሥራ ማሰናበት (Dismissal)።',
        'article_ref': 'art_cba_33_9',
        'level_ref': 'severity_level_1',
        'category_ref': 'cat_operational',
        'staff_category': 'non_managerial',
        'punishment_type': 'dismissal',
        'penalty_percentage': 0.0,
        'fine_days': 0.0,
    },
]

# 2. Parse Managerial Document
import docx
doc = docx.Document(MGR_DOCX)
paras = [p.text.strip() for p in doc.paragraphs if p.text.strip()]

m10_4_1_raw = []
m10_4_2_raw = []
m10_4_3_raw = []
m10_5_1_raw = []

idx = 0
while idx < len(paras):
    p = paras[idx]
    if '10.4.1 The following breaches' in p:
        idx += 1
        while idx < len(paras) and not paras[idx].startswith('10.4.2'):
            m10_4_1_raw.append(paras[idx])
            idx += 1
        continue
    if '10.4.2 The following breaches' in p:
        idx += 1
        while idx < len(paras) and not paras[idx].startswith('10.4.3'):
            m10_4_2_raw.append(paras[idx])
            idx += 1
        continue
    if '10.4.3 The following breaches' in p:
        idx += 1
        while idx < len(paras) and not paras[idx].startswith('10.5'):
            m10_4_3_raw.append(paras[idx])
            idx += 1
        continue
    if '10.5.1 Rigorous disciplinary' in p:
        idx += 1
        while idx < len(paras) and not paras[idx].startswith('10.5.2'):
            m10_5_1_raw.append(paras[idx])
            idx += 1
        continue
    idx += 1

letters = 'abcdefghijklmnopqrstuvwxyz'

def build_mgr_clauses(raw_list, prefix, art_ref, level_ref, punish_type, days):
    clauses = []
    for i, text in enumerate(raw_list):
        let = letters[i]
        code = f"{prefix}({let})"
        xml_id = f"offense_mgr_{prefix.replace('.', '_')}_{let}"
        # short name
        first_clause = text.split(';')[0].strip()
        clauses.append({
            'xml_id': xml_id,
            'sub_article_code': code,
            'title': False,
            'has_distinct_title': False,
            'name': first_clause or text[:80],
            'full_text': text,
            'article_ref': art_ref,
            'level_ref': level_ref,
            'category_ref': 'cat_conduct',
            'staff_category': 'managerial',
            'punishment_type': punish_type,
            'penalty_percentage': 0.0,
            'fine_days': float(days),
        })
    return clauses

clauses_10_4_1 = build_mgr_clauses(m10_4_1_raw, '10.4.1', 'art_mgr_10_4_1', 'severity_level_4', 'first_warning_penalty', 1)
clauses_10_4_2 = build_mgr_clauses(m10_4_2_raw, '10.4.2', 'art_mgr_10_4_2', 'severity_level_3', 'second_warning_penalty', 2)
clauses_10_4_3 = build_mgr_clauses(m10_4_3_raw, '10.4.3', 'art_mgr_10_4_3', 'severity_level_2', 'final_warning_penalty', 3)
clauses_10_5_1 = build_mgr_clauses(m10_5_1_raw, '10.5.1', 'art_mgr_10_5_1', 'severity_level_1', 'dismissal', 0)

all_non_mgr = clauses_33_4 + clauses_33_5 + clauses_33_6 + clauses_33_7 + clauses_33_8 + cash_shortages
all_mgr = clauses_10_4_1 + clauses_10_4_2 + clauses_10_4_3 + clauses_10_5_1

print(f'Total Non-Managerial: {len(all_non_mgr)}')
print(f'Total Managerial: {len(all_mgr)}')
print(f'Total Combined: {len(all_non_mgr) + len(all_mgr)}')

# 3. Generate Complete bunna_regulation_seed_data.xml
xml_content = ['''<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <data noupdate="0">

        <!-- ======================================================== -->
        <!-- 1. POLICY VERSION DOCUMENTS                              -->
        <!-- ======================================================== -->

        <!-- Non-Managerial: CBA Chapter 8 -->
        <record id="policy_cba_ch8" model="discipline.policy.version">
            <field name="name">Bunna Bank Collective Bargaining Agreement (የህብረት ስምምነት)</field>
            <field name="version_number">CBA-CH8-2024</field>
            <field name="staff_category">non_managerial</field>
            <field name="chapter_reference">ምዕራፍ ስምንት - የስነ ስርዓት(ዲሲፕሊን) እርምጃ</field>
            <field name="effective_date">2024-01-01</field>
            <field name="state">active</field>
            <field name="description">የቡና ባንክ አ.ማ እና የቡና ባንክ የሰራተኞች መሰረታዊ ማህበር የህብረት ስምምነት ምዕራፍ ስምንት የስነ-ስርዓት ድንጋጌዎች (አንቀጽ 33.1 - 33.13)።</field>
        </record>

        <!-- Managerial: Chapter X Policy -->
        <record id="policy_managerial_ch10" model="discipline.policy.version">
            <field name="name">Bunna Bank Managerial Staff Discipline Policy</field>
            <field name="version_number">MGR-CH10-2024</field>
            <field name="staff_category">managerial</field>
            <field name="chapter_reference">Chapter X - Disciplinary Measures for Managerial Staff</field>
            <field name="effective_date">2024-01-01</field>
            <field name="state">active</field>
            <field name="description">Human Resource Management Policy Chapter X: Disciplinary Rules, Penalties, and Dismissal Clauses for Managerial and Supervisory Staff (Articles 10.1 - 10.9).</field>
        </record>

        <!-- ======================================================== -->
        <!-- 2. OFFENSE CATEGORIES                                    -->
        <!-- ======================================================== -->
        <record id="cat_conduct" model="discipline.offense.category">
            <field name="name">Professional Conduct &amp; Ethics (የስነ-ምግባር ጉድለት)</field>
            <field name="code">CND</field>
            <field name="description">Violations involving workplace demeanor, insubordination, and integrity breaches.</field>
            <field name="active">True</field>
        </record>

        <record id="cat_attendance" model="discipline.offense.category">
            <field name="name">Attendance &amp; Timekeeping (የስራ ሰዓትና መገኘት)</field>
            <field name="code">ATT</field>
            <field name="description">Violations involving unauthorized absence, lateness, and abandonment of post.</field>
            <field name="active">True</field>
        </record>

        <record id="cat_fraud" model="discipline.offense.category">
            <field name="name">Fraud, Theft &amp; Embezzlement (ማጭበርበርና ስርቆት)</field>
            <field name="code">FRD</field>
            <field name="description">Severe financial crimes, theft, forgery, and deliberate fiduciary harm.</field>
            <field name="active">True</field>
        </record>

        <record id="cat_property" model="discipline.offense.category">
            <field name="name">Bank Property &amp; Operational Negligence</field>
            <field name="code">PRP</field>
            <field name="description">Violations involving misuse, damage, or neglect of bank equipment, property, and assets.</field>
            <field name="active">True</field>
        </record>

        <record id="cat_supervisory" model="discipline.offense.category">
            <field name="name">Supervisory &amp; Managerial Control Failures</field>
            <field name="code">SUP</field>
            <field name="description">Failures in managerial oversight, coaching responsibilities, and supervisory control.</field>
            <field name="active">True</field>
        </record>

        <record id="cat_operational" model="discipline.offense.category">
            <field name="name">Operational &amp; Cash Procedures (የአሰራርና ጥሬ ገንዘብ)</field>
            <field name="code">OPS</field>
            <field name="description">Procedural violations, cash shortages, and non-compliance with operational guidelines.</field>
            <field name="active">True</field>
        </record>

        <record id="cat_statutory" model="discipline.offense.category">
            <field name="name">Statutory &amp; Regulatory Compliance (የህግና መመሪያ ተገዢነት)</field>
            <field name="code">REG</field>
            <field name="description">Breaches of NBE directives, labor proclamation, and statutory legal limits.</field>
            <field name="active">True</field>
        </record>

        <!-- Compatible external XML IDs for inter-module integration (e.g. custom_hr_attendance) -->
        <record id="offense_cat_attendance" model="discipline.offense.category">
            <field name="name">Attendance &amp; Punctuality Misconduct</field>
            <field name="code">ATT</field>
            <field name="description">Violations involving unauthorized absence, repeated lateness, and job abandonment.</field>
            <field name="active">True</field>
        </record>

        <record id="offense_cat_conduct" model="discipline.offense.category">
            <field name="name">Professional Conduct &amp; Ethics</field>
            <field name="code">ETH</field>
            <field name="description">Violations involving insubordination, breach of trust, and behavioral misconduct.</field>
            <field name="active">True</field>
        </record>

        <record id="offense_cat_financial" model="discipline.offense.category">
            <field name="name">Financial &amp; Operational Irregularity</field>
            <field name="code">FIN</field>
            <field name="description">Violations involving cash discrepancies, fraudulent transactions, and procedural non-compliance.</field>
            <field name="active">True</field>
        </record>

        <!-- ======================================================== -->
        <!-- 3. GOVERNING REGULATORY ARTICLES                         -->
        <!-- ======================================================== -->

        <!-- Article 33.4: Level 1 Dismissal -->
        <record id="art_cba_33_4" model="discipline.article">
            <field name="article_number">Article 33.4</field>
            <field name="name">አንደኛ ደረጃ ጥፋቶች - በመጀመሪያ ጥፋት ያለማስጠንቀቂያ ከስራ የሚያሰናብቱ (Level 1: Summary Dismissal Offenses)</field>
            <field name="policy_version_id" ref="policy_cba_ch8"/>
            <field name="staff_category">non_managerial</field>
            <field name="severity_level_id" ref="severity_level_1"/>
            <field name="statutory_text">አንቀጽ 33.4፡ አንደኛ ደረጃ ጥፋቶች (በመጀመሪያ ጥፋት ያለማስጠንቀቂያ ከስራ የሚያሰናብቱ)፤ ማንኛውም ሠራተኛ ከዚህ በታች ከተዘረዘሩት ጥፋቶች አንዱን የፈጸመ እንደሆነ ያለምንም ማስጠንቀቂያ ከሥራ ይሰናበታል፡፡</field>
            <field name="description">አንደኛ ደረጃ ጥፋቶች (በመጀመሪያ ጥፋት ያለማስጠንቀቂያ ከስራ የሚያሰናብቱ) - 33.4.1 እስከ 33.4.24</field>
        </record>

        <!-- Article 33.5: Level 2 Final Warning & 20% Fine -->
        <record id="art_cba_33_5" model="discipline.article">
            <field name="article_number">Article 33.5</field>
            <field name="name">ሁለተኛ ደረጃ ጥፋቶች - የመጨረሻ ደረጃ የጽሁፍ ማስጠንቀቂያ እና 20% የደመወዝ ቅጣት (Level 2: Final Written Warning &amp; 20% Fine)</field>
            <field name="policy_version_id" ref="policy_cba_ch8"/>
            <field name="staff_category">non_managerial</field>
            <field name="severity_level_id" ref="severity_level_2"/>
            <field name="statutory_text">አንቀጽ 33.5፡ 2ኛ ደረጃ ጥፋቶች (የመጨረሻ ደረጃ የጽሁፍ ማስጠንቀቂያ እና 20% የደመወዝ ቅጣት የሚያስቀጡ)፤ ማንኛውም ሠራተኛ ከዚህ በታች ከተዘረዘሩት ጥፋቶች አንዱን የፈጸመ እንደሆነ የመጨረሻ ደረጃ የጽሁፍ ማስጠንቀቂያ እና የ20% የደመወዝ ቅጣት ይወሰንበታል፡፡</field>
            <field name="description">ሁለተኛ ደረጃ ጥፋቶች (የመጨረሻ ደረጃ የጽሁፍ ማስጠንቀቂያ እና 20% የደመወዝ ቅጣት የሚያስቀጡ) - 33.5.1 እስከ 33.5.23</field>
        </record>

        <!-- Article 33.6: Level 3 Second Warning & 10% Fine -->
        <record id="art_cba_33_6" model="discipline.article">
            <field name="article_number">Article 33.6</field>
            <field name="name">ሦስተኛ ደረጃ ጥፋቶች - ሁለተኛ ደረጃ የጽሁፍ ማስጠንቀቂያ እና 10% የደመወዝ ቅጣት (Level 3: Second Written Warning &amp; 10% Fine)</field>
            <field name="policy_version_id" ref="policy_cba_ch8"/>
            <field name="staff_category">non_managerial</field>
            <field name="severity_level_id" ref="severity_level_3"/>
            <field name="statutory_text">አንቀጽ 33.6፡ 3ኛ ደረጃ ጥፋቶች (ሁለተኛ ደረጃ የጽሁፍ ማስጠንቀቂያ እና 10% የደመወዝ ቅጣት የሚያስቀጡ)፤ ማንኛውም ሠራተኛ ከዚህ በታች ከተዘረዘሩት ጥፋቶች አንዱን የፈጸመ እንደሆነ ሁለተኛ ደረጃ የጽሁፍ ማስጠንቀቂያ እና የ10% የደመወዝ ቅጣት ይወሰንበታል፡፡</field>
            <field name="description">ሦስተኛ ደረጃ ጥፋቶች (ሁለተኛ ደረጃ የጽሁፍ ማስጠንቀቂያ እና 10% የደመወዝ ቅጣት የሚያስቀጡ) - 33.6.1 እስከ 33.6.26</field>
        </record>

        <!-- Article 33.7: Level 4 First Warning & 5% Fine -->
        <record id="art_cba_33_7" model="discipline.article">
            <field name="article_number">Article 33.7</field>
            <field name="name">አራተኛ ደረጃ ጥፋቶች - የመጀመሪያ ደረጃ የፅሁፍ ማስጠንቀቂያ እና 5% የደመወዝ ቅጣት (Level 4: First Written Warning &amp; 5% Fine)</field>
            <field name="policy_version_id" ref="policy_cba_ch8"/>
            <field name="staff_category">non_managerial</field>
            <field name="severity_level_id" ref="severity_level_4"/>
            <field name="statutory_text">አንቀጽ 33.7፡ 4ኛ ደረጃ ጥፋቶች (የመጀመሪያ ደረጃ የፅሁፍ ማስጠንቀቂያ እና 5% የደመወዝ ቅጣት የሚያስቀጡ)፤ ማንኛውም ሠራተኛ ከዚህ በታች ከተዘረዘሩት ጥፋቶች አንዱን የፈጸመ እንደሆነ የመጀመሪያ ደረጃ የጽሁፍ ማስጠንቀቂያ እና የ5% የደመወዝ ቅጣት ይወሰንበታል፡፡</field>
            <field name="description">አራተኛ ደረጃ ጥፋቶች (የመጀመሪያ ደረጃ የፅሁፍ ማስጠንቀቂያ እና 5% የደመወዝ ቅጣት የሚያስቀጡ) - 33.7.1 እስከ 33.7.23</field>
        </record>

        <!-- Article 33.8: Level 5 Verbal Warning -->
        <record id="art_cba_33_8" model="discipline.article">
            <field name="article_number">Article 33.8</field>
            <field name="name">አምስተኛ ደረጃ ጥፋቶች - የቃል ማስጠንቀቂያ በጽሁፍ (Level 5: Recorded Verbal Warning Offenses)</field>
            <field name="policy_version_id" ref="policy_cba_ch8"/>
            <field name="staff_category">non_managerial</field>
            <field name="severity_level_id" ref="severity_level_5"/>
            <field name="statutory_text">አንቀጽ 33.8፡ አምስተኛ ደረጃ ጥፋቶች (የቃል ማስጠንቀቂያ በጽሁፍ የሚያሰጡ ጥፋቶች)፤ ማንኛውም ሠራተኛ ከዚህ በታች ከተዘረዘሩት ጥፋቶች አንዱን የፈጸመ እንደሆነ የቃል ማስጠንቀቂያ በጽሁፍ ተመዝግቦ ይሰጠዋል፡፡</field>
            <field name="description">አምስተኛ ደረጃ ጥፋቶች (የቃል ማስጠንቀቂያ በጽሁፍ የሚያሰጡ ጥፋቶች) - 33.8.1 እስከ 33.8.26</field>
        </record>

        <!-- Article 33.9: Cash Shortages -->
        <record id="art_cba_33_9" model="discipline.article">
            <field name="article_number">Article 33.9</field>
            <field name="name">ከጥሬ ገንዘብ ልዩነት ጋር በተያያዘ ቅጣት የሚያሰጡ ጥፋቶች (Cash Shortage Discrepancy Scale)</field>
            <field name="policy_version_id" ref="policy_cba_ch8"/>
            <field name="staff_category">non_managerial</field>
            <field name="severity_level_id" ref="severity_level_3"/>
            <field name="statutory_text">አንቀጽ 33.9፡ ከጥሬ ገንዘብ ልዩነት ጋር በተያያዘ ቅጣት የሚያሰጡ ጥፋቶችና የእርምጃዎች ደረጃ።</field>
            <field name="description">የጥሬ ገንዘብ ጉድለት ወይም የቆጠራ ልዩነት መፍጠር ድንጋጌዎች - 33.9.1 እስከ 33.9.6</field>
        </record>

        <!-- Managerial Article 10.4.1 -->
        <record id="art_mgr_10_4_1" model="discipline.article">
            <field name="article_number">Article 10.4.1</field>
            <field name="name">Managerial Breaches Entailing Simple Measures - Oral Warning or 1 Day Fine</field>
            <field name="policy_version_id" ref="policy_managerial_ch10"/>
            <field name="staff_category">managerial</field>
            <field name="severity_level_id" ref="severity_level_4"/>
            <field name="statutory_text">Article 10.4.1: The following breaches of discipline shall result in oral warnings or a fine of one day salary with first written warning depending on the gravity of the infringement.</field>
            <field name="description">Managerial Simple Disciplinary Breaches (Article 10.4.1.a - 10.4.1.g)</field>
        </record>

        <!-- Managerial Article 10.4.2 -->
        <record id="art_mgr_10_4_2" model="discipline.article">
            <field name="article_number">Article 10.4.2</field>
            <field name="name">Managerial Breaches Entailing 2 Days Salary Fine &amp; Written Warning</field>
            <field name="policy_version_id" ref="policy_managerial_ch10"/>
            <field name="staff_category">managerial</field>
            <field name="severity_level_id" ref="severity_level_3"/>
            <field name="statutory_text">Article 10.4.2: The following breaches of discipline shall entail a fine of two days salary in addition to the written warnings and shall constitute good cause for dismissal after two written warnings.</field>
            <field name="description">Managerial Simple Disciplinary Breaches (Article 10.4.2.a - 10.4.2.e)</field>
        </record>

        <!-- Managerial Article 10.4.3 -->
        <record id="art_mgr_10_4_3" model="discipline.article">
            <field name="article_number">Article 10.4.3</field>
            <field name="name">Managerial Breaches Entailing 3 Days Salary Fine &amp; Final Warning</field>
            <field name="policy_version_id" ref="policy_managerial_ch10"/>
            <field name="staff_category">managerial</field>
            <field name="severity_level_id" ref="severity_level_2"/>
            <field name="statutory_text">Article 10.4.3: The following breaches of discipline shall entail a fine of three days salary in addition to the written warning and shall constitute good cause for dismissal after the first written warning.</field>
            <field name="description">Managerial Simple Disciplinary Breaches (Article 10.4.3.a - 10.4.3.h)</field>
        </record>

        <!-- Managerial Article 10.5.1 -->
        <record id="art_mgr_10_5_1" model="discipline.article">
            <field name="article_number">Article 10.5.1</field>
            <field name="name">Managerial Breaches Entailing Rigorous Disciplinary Measures - Dismissal</field>
            <field name="policy_version_id" ref="policy_managerial_ch10"/>
            <field name="staff_category">managerial</field>
            <field name="severity_level_id" ref="severity_level_1"/>
            <field name="statutory_text">Article 10.5.1: Rigorous disciplinary measures shall be taken against a management staff who commits any of the following offenses, entailing dismissal without warning.</field>
            <field name="description">Managerial Rigorous Disciplinary Breaches (Article 10.5.1.a - 10.5.1.w)</field>
        </record>
''']

# Helper to render offense record
def render_offense_xml(c, seq):
    title_field = f'            <field name="title">{escape_xml(c["title"])}</field>\n' if c.get('title') else ''
    has_title_val = "True" if c.get('has_distinct_title') else "False"
    
    return f'''        <record id="{c['xml_id']}" model="discipline.offense">
            <field name="sequence">{seq}</field>
            <field name="article_id" ref="{c['article_ref']}"/>
            <field name="sub_article_code">{escape_xml(c['sub_article_code'])}</field>
            <field name="name">{escape_xml(c['name'])}</field>
{title_field}            <field name="has_distinct_title">{has_title_val}</field>
            <field name="category_id" ref="{c['category_ref']}"/>
            <field name="staff_category">{c['staff_category']}</field>
            <field name="severity_level_id" ref="{c['level_ref']}"/>
            <field name="penalty_mode">level_default</field>
            <field name="punishment_type">{c['punishment_type']}</field>
            <field name="penalty_percentage">{c['penalty_percentage']}</field>
            <field name="fine_days">{c['fine_days']}</field>
            <field name="full_clause_text">{escape_xml(c['full_text'])}</field>
        </record>'''

xml_content.append('\n        <!-- ======================================================== -->')
xml_content.append('        <!-- 4. NON-MANAGERIAL OFFENSE CLAUSES (141 CLAUSES)        -->')
xml_content.append('        <!-- ======================================================== -->\n')

seq = 10
for c in all_non_mgr:
    xml_content.append(render_offense_xml(c, seq))
    seq += 10

xml_content.append('\n        <!-- ======================================================== -->')
xml_content.append('        <!-- 5. MANAGERIAL OFFENSE CLAUSES (43 CLAUSES)             -->')
xml_content.append('        <!-- ======================================================== -->\n')

for c in all_mgr:
    xml_content.append(render_offense_xml(c, seq))
    seq += 10

xml_content.append('''
    </data>
</odoo>
''')

full_xml = '\n'.join(xml_content)
with open(OUTPUT_XML, 'w', encoding='utf-8') as f:
    f.write(full_xml)

print(f'Successfully wrote {OUTPUT_XML} with {len(all_non_mgr) + len(all_mgr)} total clauses.')

# -*- coding: utf-8 -*-
"""
Execution script to insert all Non-Managerial Articles & Sub-Articles into pm_db
Based on 'Non managerial discipline document.pdf' (Collective Bargaining Agreement Chapter 8).
"""
import re
import os
import odoo
from odoo import api, SUPERUSER_ID
from odoo.modules.registry import Registry

EXTRACTED_FILE = '/tmp/non_managerial_extracted.txt'
if not os.path.exists(EXTRACTED_FILE):
    EXTRACTED_FILE = 'd:/odoo19_pm/non_managerial_extracted.txt'

def clean_str(t):
    if not t:
        return ''
    t = re.sub(r'=== PAGE \d+ ===\s*\n\s*\d+\s*', '', t)
    t = re.sub(r'[ \t]+', ' ', t)
    t = re.sub(r'\n+', ' ', t)
    return t.strip()

with open(EXTRACTED_FILE, 'r', encoding='utf-8') as f:
    raw_text = f.read()

cleaned_text = re.sub(r'=== PAGE \d+ ===\s*\n\s*\d+\s*', '', raw_text)

p_33_4 = cleaned_text.find('33.4  አንደኛ ደረጃ ጥፋቶች')
p_33_5 = cleaned_text.find('33.5 2ኛ ደረጃ ጥፋቶች')
p_33_6 = cleaned_text.find('33.6 3ኛ ደረጃ ጥፋቶች')
p_33_7 = cleaned_text.find('33.7 4ኛ ደረጃ ጥፋቶች')
p_33_8 = cleaned_text.find('33.8 አምስተኛ')
p_33_9 = cleaned_text.find('33.9')
p_33_10 = cleaned_text.find('33.10')

SUB_CLAUSE_SPECS = {
    '33.4.1': ['ሀ', 'ለ', 'ሐ'],
    '33.4.2': ['ሀ', 'ለ', 'ሐ', 'መ', 'ሠ'],
    '33.4.5': ['ሀ', 'ለ'],
    '33.4.6': ['ሀ', 'ለ', 'ሐ'],
    '33.4.8': ['ሀ', 'ለ', 'ሐ'],
    '33.4.12': ['ሀ', 'ለ'],
    '33.4.15': ['ሀ', 'ለ'],
}

def parse_33_4(sec_text):
    items = re.split(r'(33\.4\.\d+)', sec_text)
    clauses = []
    for i in range(1, len(items), 2):
        code = items[i]
        block = items[i+1].strip()
        lines = [l.strip() for l in block.split('\n') if l.strip()]
        header_title = lines[0] if lines else code
        
        expected_subs = SUB_CLAUSE_SPECS.get(code)
        if expected_subs:
            pat = r'((?:' + '|'.join(expected_subs) + r')\s*\))'
            parts = re.split(pat, block)
            for j in range(1, len(parts), 2):
                let = parts[j].replace(')', '').strip()
                if let in expected_subs:
                    body = clean_str(parts[j+1])
                    clauses.append({
                        'code': f"{code}({let})",
                        'parent_code': code,
                        'title': f"{header_title} ({let})",
                        'full_text': body,
                        'article_number': 'Article 33.4',
                        'level_code': 'level_1',
                    })
        else:
            body = clean_str('\n'.join(lines[1:]) if len(lines) > 1 else lines[0])
            clauses.append({
                'code': code,
                'parent_code': code,
                'title': header_title,
                'full_text': body,
                'article_number': 'Article 33.4',
                'level_code': 'level_1',
            })
    return clauses

def parse_numbered_section(sec_text, prefix, art_num, level_code):
    pat = rf'({re.escape(prefix)}\.\d+)'
    items = re.split(pat, sec_text)
    clauses = []
    for i in range(1, len(items), 2):
        code = items[i]
        raw_block = items[i+1].strip()
        body = clean_str(raw_block)
        first_clause = body.split('፤')[0].split('።')[0].strip()
        if len(first_clause) > 95:
            words = first_clause.split(' ')
            first_clause = ' '.join(words[:12]) + '...'
        clauses.append({
            'code': code,
            'parent_code': code,
            'title': first_clause,
            'full_text': body,
            'article_number': art_num,
            'level_code': level_code,
        })
    return clauses

all_clauses = []
all_clauses.extend(parse_33_4(cleaned_text[p_33_4:p_33_5]))
all_clauses.extend(parse_numbered_section(cleaned_text[p_33_5:p_33_6], '33.5', 'Article 33.5', 'level_2'))
all_clauses.extend(parse_numbered_section(cleaned_text[p_33_6:p_33_7], '33.6', 'Article 33.6', 'level_3'))
all_clauses.extend(parse_numbered_section(cleaned_text[p_33_7:p_33_8], '33.7', 'Article 33.7', 'level_4'))
all_clauses.extend(parse_numbered_section(cleaned_text[p_33_8:p_33_9], '33.8', 'Article 33.8', 'level_5'))

# Cash shortage clauses under 33.9
cash_clauses = [
    {
        'code': '33.9.1',
        'parent_code': '33.9',
        'title': 'እስከ 500.00 ብር የጥሬ ገንዘብ ጉድለት (Cash Shortage up to 500 ETB)',
        'full_text': 'እስከ 500.00 ብር የሚደርስ የጥሬ ገንዘብ ጉድለት ወይም የቆጠራ ልዩነት መፍጠር። 1ኛ ጥፋት፡ የቃል ማስጠንቀቂያ በጽሁፍ፣ 2ኛ ጥፋት፡ የመጀመሪያ የጽሁፍ ማስጠንቀቂያ፣ 3ኛ ጥፋት፡ ሁለተኛ የጽሁፍ ማስጠንቀቂያና የ10% ደመወዝ ቅጣት፣ 4ኛ ጥፋት፡ የመጨረሻ የጽሁፍ ማስጠንቀቂያና የ20% ደመወዝ ቅጣት።',
        'article_number': 'Article 33.9',
        'level_code': 'level_5',
        'penalty_mode': 'repetition_escalation',
    },
    {
        'code': '33.9.2',
        'parent_code': '33.9',
        'title': 'ከ501.00 እስከ 1,000.00 ብር የጥሬ ገንዘብ ጉድለት (Cash Shortage 501 to 1,000 ETB)',
        'full_text': 'ከ501.00 እስከ 1,000.00 ብር የሚደርስ የጥሬ ገንዘብ ጉድለት ወይም የቆጠራ ልዩነት መፍጠር። 1ኛ ጥፋት፡ የመጀመሪያ የጽሁፍ ማስጠንቀቂያ፣ 2ኛ ጥፋት፡ ሁለተኛ የጽሁፍ ማስጠንቀቂያና የ10% ደመወዝ ቅጣት፣ 3ኛ ጥፋት፡ ሁለተኛ የጽሁፍ ማስጠንቀቂያና የ10% ደመወዝ ቅጣት፣ 4ኛ ጥፋት፡ የመጨረሻ የጽሁፍ ማስጠንቀቂያና የ20% ደመወዝ ቅጣት።',
        'article_number': 'Article 33.9',
        'level_code': 'level_4',
        'penalty_mode': 'repetition_escalation',
    },
    {
        'code': '33.9.3',
        'parent_code': '33.9',
        'title': 'ከ1,001.00 እስከ 5,000.00 ብር የጥሬ ገንዘብ ጉድለት (Cash Shortage 1,001 to 5,000 ETB)',
        'full_text': 'ከ1,001.00 እስከ 5,000.00 ብር የሚደርስ የጥሬ ገንዘብ ጉድለት ወይም የቆጠራ ልዩነት መፍጠር። 1ኛ ጥፋት፡ የመጀመሪያ የጽሁፍ ማስጠንቀቂያ፣ 2ኛ ጥፋት፡ ሁለተኛ የጽሁፍ ማስጠንቀቂያና የ10% ደመወዝ ቅጣት፣ 3ኛ ጥፋት፡ ሁለተኛ የጽሁፍ ማስጠንቀቂያና የ10% ደመወዝ ቅጣት፣ 4ኛ ጥፋት፡ የመጨረሻ የጽሁፍ ማስጠንቀቂያና የ20% ደመወዝ ቅጣት።',
        'article_number': 'Article 33.9',
        'level_code': 'level_4',
        'penalty_mode': 'repetition_escalation',
    },
    {
        'code': '33.9.4',
        'parent_code': '33.9',
        'title': 'ከ5,001.00 እስከ 10,000.00 ብር የጥሬ ገንዘብ ጉድለት (Cash Shortage 5,001 to 10,000 ETB)',
        'full_text': 'ከ5,001.00 እስከ 10,000.00 ብር የሚደርስ የጥሬ ገንዘብ ጉድለት ወይም የቆጠራ ልዩነት መፍጠር። 1ኛ ጥፋት፡ ሁለተኛ የጽሁፍ ማስጠንቀቂያና የ10% ደመወዝ ቅጣት፣ 2ኛ ጥፋት፡ የመጨረሻ የጽሁፍ ማስጠንቀቂያና የ20% ደመወዝ ቅጣት፣ 3ኛ ጥፋት፡ ሠራተኛውን ከደረጃ ዝቅ አድርጎ ከገንዘብ ነክ ሥራ ማንሳት (Demotion)።',
        'article_number': 'Article 33.9',
        'level_code': 'level_3',
        'penalty_mode': 'repetition_escalation',
    },
    {
        'code': '33.9.5',
        'parent_code': '33.9',
        'title': 'ከ10,001.00 እስከ 20,000.00 ብር የጥሬ ገንዘብ ጉድለት (Cash Shortage 10,001 to 20,000 ETB)',
        'full_text': 'ከ10,001.00 እስከ 20,000.00 ብር የሚደርስ የጥሬ ገንዘብ ጉድለት ወይም የቆጠራ ልዩነት መፍጠር። 1ኛ ጥፋት፡ ሁለተኛ የጽሁፍ ማስጠንቀቂያና የ10% ደመወዝ ቅጣት፣ 2ኛ ጥፋት፡ የመጨረሻ የጽሁፍ ማስጠንቀቂያና የ20% ደመወዝ ቅጣት፣ 3ኛ ጥፋት፡ የሥራ ውል ማቋረጥ (Dismissal)።',
        'article_number': 'Article 33.9',
        'level_code': 'level_3',
        'penalty_mode': 'repetition_escalation',
    },
    {
        'code': '33.9.6',
        'parent_code': '33.9',
        'title': 'ከ20,001.00 ብር በላይ የጥሬ ገንዘብ ጉድለት (Cash Shortage Above 20,000 ETB)',
        'full_text': 'ከ20,001.00 ብር በላይ የሚደርስ የጥሬ ገንዘብ ጉድለት ወይም የቆጠራ ልዩነት መፍጠር። 1ኛ ጥፋት፡ የመጨረሻ የጽሁፍ ማስጠንቀቂያና የ20% ደመወዝ ቅጣት፣ 2ኛ ጥፋት፡ የሥራ ውል ማቋረጥ (Dismissal)።',
        'article_number': 'Article 33.9',
        'level_code': 'level_2',
        'penalty_mode': 'repetition_escalation',
    },
]
all_clauses.extend(cash_clauses)

print(f"Total non-managerial clauses to insert: {len(all_clauses)}")

# Now connect to Odoo registry and insert/update
registry = Registry('pm_db')
with registry.cursor() as cr:
    env = api.Environment(cr, SUPERUSER_ID, {})
    
    # 1. Fetch policy
    policy = env['discipline.policy.version'].search([('staff_category', '=', 'non_managerial')], limit=1)
    if not policy:
        policy = env['discipline.policy.version'].create({
            'name': 'Bunna Bank Collective Bargaining Agreement (የህብረት ስምምነት)',
            'version_number': 'CBA-CH8-2024',
            'staff_category': 'non_managerial',
            'chapter_reference': 'ምዕራፍ ስምንት - የስነ ስርዓት(ዲሲፕሊን) እርምጃ',
            'effective_date': '2024-01-01',
            'state': 'active',
            'description': 'የቡና ባንክ አ.ማ እና የቡና ባንክ የሰራተኞች መሰረታዊ ማህበር የህብረት ስምምነት ምዕራፍ ስምንት የስነ-ስርዓት ድንጋጌዎች (አንቀጽ 33.1 - 33.13)።',
        })
    print(f"Policy: {policy.name} (id={policy.id})")

    # 2. Fetch severity levels map
    levels = {l.code: l for l in env['discipline.severity.level'].search([])}
    print(f"Severity levels available: {list(levels.keys())}")

    # 3. Fetch offense categories map
    cats = {c.code: c for c in env['discipline.offense.category'].search([])}
    # Ensure standard categories exist
    cat_fraud = cats.get('FRD') or cats.get('FIN')
    cat_property = cats.get('PRP')
    cat_attendance = cats.get('ATT')
    cat_conduct = cats.get('CND') or cats.get('ETH')
    cat_supervisory = cats.get('SUP')

    def resolve_category(code, title, text):
        t = f"{title} {text}".lower()
        if code.startswith('33.4.1') or code.startswith('33.4.2') or code.startswith('33.4.3') or code.startswith('33.4.4') or code.startswith('33.4.7') or code.startswith('33.4.8') or code.startswith('33.4.11') or code.startswith('33.4.14') or code.startswith('33.4.15') or code.startswith('33.4.21') or code.startswith('33.4.22') or 'ስርቆት' in t or 'ማጭበርበር' in t or 'ጉቦ' in t or 'ማታለል' in t:
            return cat_fraud or cat_property or cat_conduct
        if 'መቅረት' in t or 'ዘግይቶ' in t or 'መግቢያ' in t or 'መውጫ' in t or 'ሰዓት' in t or code in ('33.4.9', '33.5.3', '33.6.16', '33.6.17', '33.7.7', '33.8.1'):
            return cat_attendance or cat_conduct
        if 'ጥሬ ገንዘብ' in t or 'ካዝና' in t or 'ሂሳብ' in t or 'ቼክ' in t or 'ብድር' in t or 'ትራንዛክሸን' in t or 'ንብረት' in t or 'መሣሪያ' in t or code.startswith('33.9'):
            return cat_property or cat_conduct
        return cat_conduct

    # 4. Define Articles metadata
    ARTICLES_DEF = {
        'Article 33.4': {
            'article_number': 'Article 33.4',
            'name': 'አንደኛ ደረጃ ጥፋቶች - በመጀመሪያ ጥፋት ያለማስጠንቀቂያ ከስራ የሚያሰናብቱ (Level 1: Summary Dismissal Offenses)',
            'severity_level_id': levels['level_1'].id,
            'statutory_text': 'አንቀጽ 33.4፡ አንደኛ ደረጃ ጥፋቶች (በመጀመሪያ ጥፋት ያለማስጠንቀቂያ ከስራ የሚያሰናብቱ)፤ ማንኛውም ሠራተኛ ከዚህ በታች ከተዘረዘሩት ጥፋቶች አንዱን የፈጸመ እንደሆነ ያለምንም ማስጠንቀቂያ ከሥራ ይሰናበታል፡፡',
            'description': 'አንደኛ ደረጃ ጥፋቶች (በመጀመሪያ ጥፋት ያለማስጠንቀቂያ ከስራ የሚያሰናብቱ) - 33.4.1 እስከ 33.4.24',
        },
        'Article 33.5': {
            'article_number': 'Article 33.5',
            'name': 'ሁለተኛ ደረጃ ጥፋቶች - የመጨረሻ ደረጃ የጽሁፍ ማስጠንቀቂያ እና 20% የደመወዝ ቅጣት (Level 2: Final Written Warning & 20% Fine)',
            'severity_level_id': levels['level_2'].id,
            'statutory_text': 'አንቀጽ 33.5፡ 2ኛ ደረጃ ጥፋቶች (የመጨረሻ ደረጃ የጽሁፍ ማስጠንቀቂያ እና 20% የደመወዝ ቅጣት የሚያስቀጡ)፤ ማንኛውም ሠራተኛ ከዚህ በታች ከተዘረዘሩት ጥፋቶች አንዱን የፈጸመ እንደሆነ የመጨረሻ የጽሁፍ ማስጠንቀቂያ እና የ20% የደመወዝ ቅጣት ይወሰንበታል፡፡',
            'description': 'ሁለተኛ ደረጃ ጥፋቶች (የመጨረሻ ደረጃ የጽሁፍ ማስጠንቀቂያ እና 20% የደመወዝ ቅጣት የሚያስቀጡ) - 33.5.1 እስከ 33.5.23',
        },
        'Article 33.6': {
            'article_number': 'Article 33.6',
            'name': 'ሦስተኛ ደረጃ ጥፋቶች - ሁለተኛ ደረጃ የጽሁፍ ማስጠንቀቂያ እና 10% የደመወዝ ቅጣት (Level 3: Second Written Warning & 10% Fine)',
            'severity_level_id': levels['level_3'].id,
            'statutory_text': 'አንቀጽ 33.6፡ 3ኛ ደረጃ ጥፋቶች (ሁለተኛ ደረጃ የጽሁፍ ማስጠንቀቂያ እና 10% የደመወዝ ቅጣት የሚያስቀጡ)፤ ማንኛውም ሠራተኛ ከዚህ በታች ከተዘረዘሩት ጥፋቶች አንዱን የፈጸመ እንደሆነ ሁለተኛ ደረጃ የጽሁፍ ማስጠንቀቂያ እና የ10% የደመወዝ ቅጣት ይወሰንበታል፡፡',
            'description': 'ሦስተኛ ደረጃ ጥፋቶች (ሁለተኛ ደረጃ የጽሁፍ ማስጠንቀቂያ እና 10% የደመወዝ ቅጣት የሚያስቀጡ) - 33.6.1 እስከ 33.6.26',
        },
        'Article 33.7': {
            'article_number': 'Article 33.7',
            'name': 'አራተኛ ደረጃ ጥፋቶች - የመጀመሪያ ደረጃ የፅሁፍ ማስጠንቀቂያ እና 5% የደመወዝ ቅጣት (Level 4: First Written Warning & 5% Fine)',
            'severity_level_id': levels['level_4'].id,
            'statutory_text': 'አንቀጽ 33.7፡ 4ኛ ደረጃ ጥፋቶች (የመጀመሪያ ደረጃ የፅሁፍ ማስጠንቀቂያ እና 5% የደመወዝ ቅጣት የሚያስቀጡ)፤ ማንኛውም ሠራተኛ ከዚህ በታች ከተዘረዘሩት ጥፋቶች አንዱን የፈጸመ እንደሆነ የመጀመሪያ ደረጃ የጽሁፍ ማስጠንቀቂያ እና የ5% የደመወዝ ቅጣት ይወሰንበታል፡፡',
            'description': 'አራተኛ ደረጃ ጥፋቶች (የመጀመሪያ ደረጃ የፅሁፍ ማስጠንቀቂያ እና 5% የደመወዝ ቅጣት የሚያስቀጡ) - 33.7.1 እስከ 33.7.23',
        },
        'Article 33.8': {
            'article_number': 'Article 33.8',
            'name': 'አምስተኛ ደረጃ ጥፋቶች - የቃል ማስጠንቀቂያ በጽሁፍ የሚያሰጡ ጥፋቶች (Level 5: Recorded Verbal Warning Offenses)',
            'severity_level_id': levels['level_5'].id,
            'statutory_text': 'አንቀጽ 33.8፡ አምስተኛ ደረጃ ጥፋቶች (የቃል ማስጠንቀቂያ በጽሁፍ የሚያሰጡ ጥፋቶች)፤ ማንኛውም ሠራተኛ ከዚህ በታች ከተዘረዘሩት ጥፋቶች አንዱን የፈጸመ እንደሆነ በጽሁፍ የሚሰጥ የቃል ማስጠንቀቂያ ይሰጠዋል፡፡',
            'description': 'አምስተኛ ደረጃ ጥፋቶች (የቃል ማስጠንቀቂያ በጽሁፍ የሚያሰጡ ጥፋቶች) - 33.8.1 እስከ 33.8.26',
        },
        'Article 33.9': {
            'article_number': 'Article 33.9',
            'name': 'ከጥሬ ገንዘብ ልዩነት ጋር በተያያዘ ቅጣት የሚያሰጡ ጥፋቶች (Cash Shortage Discrepancy Misconduct)',
            'severity_level_id': levels['level_3'].id,
            'statutory_text': 'አንቀጽ 33.9፡ ከጥሬ ገንዘብ አያያዝና አከፋፈል ጋር በተገናኘ የተጣሰ የባንኩ የውስጥ የአሰራር መመሪያ መኖሩ ሲረጋገጥ የገንዘብ ጉድለት ጥፋት ማጥፋቱ የተረጋገጠ ሠራተኛ አግባብ ባለው ህግ ተጠያቂ መሆኑ እንደተጠበቀ ሆኖ፤ በተለይ በቆጠራ ስህተት ለሚከሰት የጥሬ ገንዘብ ልዩነት (ጉድለት/ብልጫ) ከገንዘብ ጋር በተገናኘ የስራ መደብ ላይ ተመድበው የሚሰሩ ሰራተኞች ያጋጠመውን የገንዘብ ጉድለት ከመተካት በተጨማሪ በልዩነቱ መጠንና በድግግሞሹ መሰረት የዲሲፕሊን ቅጣት እርምጃ ይወሰድባቸዋል፡፡',
            'description': 'ከጥሬ ገንዘብ ልዩነት (ጉድለት/ብልጫ) ጋር በተያያዘ ቅጣት የሚያሰጡ ጥፋቶች (ሰንጠረዥ 33.9/33.11)።',
        },
    }

    # Create or update Article records
    db_articles = {}
    for art_num, art_vals in ARTICLES_DEF.items():
        art = env['discipline.article'].search([
            ('policy_version_id', '=', policy.id),
            ('article_number', '=', art_num),
        ], limit=1)
        if not art:
            # Also check without 'Article ' prefix
            alt_num = art_num.replace('Article ', '').strip()
            art = env['discipline.article'].search([
                ('policy_version_id', '=', policy.id),
                ('article_number', 'in', [art_num, alt_num]),
            ], limit=1)

        vals = {
            'policy_version_id': policy.id,
            'article_number': art_num,
            'name': art_vals['name'],
            'severity_level_id': art_vals['severity_level_id'],
            'statutory_text': art_vals['statutory_text'],
            'description': art_vals['description'],
            'active': True,
        }
        if art:
            art.write(vals)
            print(f"Updated Article {art_num} (ID {art.id}) -> Severity Level ID: {art_vals['severity_level_id']}")
        else:
            art = env['discipline.article'].create(vals)
            print(f"Created Article {art_num} (ID {art.id})")
        db_articles[art_num] = art

    # 5. Insert / Update all sub-articles (offenses)
    inserted_count = 0
    updated_count = 0
    
    for c in all_clauses:
        art_record = db_articles.get(c['article_number'])
        sev_lvl = levels[c['level_code']]
        cat = resolve_category(c['code'], c['title'], c['full_text'])
        
        pen_mode = c.get('penalty_mode', 'level_default')
        punishment_type = sev_lvl.default_punishment_type
        penalty_percentage = sev_lvl.default_non_managerial_penalty_pct or sev_lvl.default_penalty_percentage
        approval_authority = sev_lvl.default_approval_authority

        offense = env['discipline.offense'].search([
            ('sub_article_code', '=', c['code']),
            ('staff_category', '=', 'non_managerial'),
        ], limit=1)
        
        if not offense:
            # Check by article and name
            offense = env['discipline.offense'].search([
                ('article_id', '=', art_record.id),
                ('sub_article_code', '=', c['code']),
            ], limit=1)

        off_vals = {
            'name': c['title'],
            'sub_article_code': c['code'],
            'article_id': art_record.id,
            'category_id': cat.id,
            'severity_level_id': sev_lvl.id,
            'staff_category': 'non_managerial',
            'penalty_mode': pen_mode,
            'punishment_type': punishment_type,
            'penalty_percentage': penalty_percentage,
            'approval_authority': approval_authority,
            'full_clause_text': c['full_text'],
            'description': c['full_text'][:300],
            'active': True,
        }

        if offense:
            offense.write(off_vals)
            updated_count += 1
        else:
            offense = env['discipline.offense'].create(off_vals)
            inserted_count += 1

    print(f"Offenses processing done: {inserted_count} created, {updated_count} updated.")

    # 6. Re-link test cases if needed
    # Hanan's case (DISC/2026/0015): ensure linked to Article 33.9 and Cash Shortage 33.9.4
    hanan_case = env['discipline.case'].search([('name', '=', 'DISC/2026/0015')], limit=1)
    if hanan_case:
        art_33_9 = db_articles['Article 33.9']
        off_33_9_4 = env['discipline.offense'].search([('sub_article_code', '=', '33.9.4')], limit=1)
        if off_33_9_4 and art_33_9:
            hanan_case.write({
                'article_id': art_33_9.id,
                'offense_id': off_33_9_4.id,
                'severity_level_id': levels['level_3'].id,
            })
            print(f"Updated Hanan case DISC/2026/0015 -> Article 33.9, Offense 33.9.4, Level 3 (10% penalty)")

    # Case DISC/2026/0016
    c16 = env['discipline.case'].search([('name', '=', 'DISC/2026/0016')], limit=1)
    if c16:
        art_33_9 = db_articles['Article 33.9']
        off_33_9_4 = env['discipline.offense'].search([('sub_article_code', '=', '33.9.4')], limit=1)
        if off_33_9_4 and art_33_9:
            c16.write({
                'article_id': art_33_9.id,
                'offense_id': off_33_9_4.id,
                'severity_level_id': levels['level_3'].id,
            })
            print(f"Updated DISC/2026/0016 -> Article 33.9, Offense 33.9.4, Level 3")

    cr.commit()
    print("Database transaction successfully committed!")

# -*- coding: utf-8 -*-
"""
Robust parser and data builder for Non-Managerial Discipline Policy (Articles 33.4 to 33.9).
"""
import re
import os

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

# Article 33.4: Specified sub-clauses
# 33.4.1 (ሀ, ለ, ሐ)
# 33.4.2 (ሀ, ለ, ሐ, መ, ሠ)
# 33.4.3
# 33.4.4
# 33.4.5 (ሀ, ለ)
# 33.4.6 (ሀ, ለ, ሐ)
# 33.4.7
# 33.4.8 (ሀ, ለ, ሐ)
# 33.4.9
# 33.4.10, 33.4.11
# 33.4.12 (ሀ, ለ)
# 33.4.13, 33.4.14
# 33.4.15 (ሀ, ለ)
# 33.4.16 up to 33.4.24

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
            # Pattern matching each letter
            # We look for e.g. ሀ) or ሀ )
            pat = r'([ሀ-ሠ]\s*\))'
            parts = re.split(pat, block)
            # parts[0] is header
            for j in range(1, len(parts), 2):
                let = parts[j].replace(')', '').strip()
                if let in expected_subs:
                    body = clean_str(parts[j+1])
                    # Clean any trailing next sub letter
                    clauses.append({
                        'code': f"{code}({let})",
                        'parent_code': code,
                        'title': f"{header_title} ({let})",
                        'full_text': body,
                        'article': 'Article 33.4',
                        'level': 'level_1',
                    })
        else:
            body = clean_str('\n'.join(lines[1:]) if len(lines) > 1 else lines[0])
            clauses.append({
                'code': code,
                'parent_code': code,
                'title': header_title,
                'full_text': body,
                'article': 'Article 33.4',
                'level': 'level_1',
            })
    return clauses

def parse_numbered_section(sec_text, prefix, art_num, level):
    pat = rf'({re.escape(prefix)}\.\d+)'
    items = re.split(pat, sec_text)
    clauses = []
    for i in range(1, len(items), 2):
        code = items[i]
        raw_block = items[i+1].strip()
        body = clean_str(raw_block)
        
        # Determine title: first clause ending with semicolon or period
        first_clause = body.split('፤')[0].split('።')[0].strip()
        if len(first_clause) > 95:
            # try to split at comma or space
            words = first_clause.split(' ')
            first_clause = ' '.join(words[:12]) + '...'
        clauses.append({
            'code': code,
            'parent_code': code,
            'title': first_clause,
            'full_text': body,
            'article': art_num,
            'level': level,
        })
    return clauses

c33_4 = parse_33_4(cleaned_text[p_33_4:p_33_5])
c33_5 = parse_numbered_section(cleaned_text[p_33_5:p_33_6], '33.5', 'Article 33.5', 'level_2')
c33_6 = parse_numbered_section(cleaned_text[p_33_6:p_33_7], '33.6', 'Article 33.6', 'level_3')
c33_7 = parse_numbered_section(cleaned_text[p_33_7:p_33_8], '33.7', 'Article 33.7', 'level_4')
c33_8 = parse_numbered_section(cleaned_text[p_33_8:p_33_9], '33.8', 'Article 33.8', 'level_5')

print(f"33.4: {len(c33_4)} items")
print(f"33.5: {len(c33_5)} items")
print(f"33.6: {len(c33_6)} items")
print(f"33.7: {len(c33_7)} items")
print(f"33.8: {len(c33_8)} items")

# Check all codes in 33.4
for c in c33_4:
    print(f"  {c['code']}: {c['title']} | text len={len(c['full_text'])}")

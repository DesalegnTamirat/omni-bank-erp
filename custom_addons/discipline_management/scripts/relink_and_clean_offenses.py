# -*- coding: utf-8 -*-
import psycopg2

conn = psycopg2.connect('dbname=pm_db user=odoo password=Abe@5360 host=pm-db')
cr = conn.cursor()

# Find the target official offense IDs in DB (or matching sub_article_code)
# Mapping of sub_article_codes for existing test cases
target_codes = {
    '33.7.1(ሐ)': '33.7.1',
    '33.7.1(ለ)': '33.7.1',
    '33.5.1(ሐ)': '33.5.1',
    '33.8.1(መ)': '33.8.1',
    '33.8.1(ሐ)': '33.8.1',
    '33.9.4': '33.9.4',
    '33.4.1(ሐ)': '33.4.1(ሐ)',
    '10.4.3(h)': '10.4.3(h)',
    '10.4.3(g)': '10.4.3(g)',
    '10.5.1(g)': '10.5.1(g)',
}

print('=== Current cases before relink ===')
cr.execute('SELECT c.id, c.name, c.offense_id, o.sub_article_code FROM discipline_case c LEFT JOIN discipline_offense o ON c.offense_id = o.id ORDER BY c.id;')
cases = cr.fetchall()
for c in cases:
    print(c)

# We want to re-link any cases referencing old IDs (4..23) to valid records with sub_article_code
for cid, cname, off_id, code in cases:
    if code in target_codes:
        new_code = target_codes[code]
        # Find a valid offense id with new_code
        cr.execute('SELECT id FROM discipline_offense WHERE sub_article_code = %s AND id NOT IN (4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23) LIMIT 1;', (new_code,))
        row = cr.fetchone()
        if row:
            new_id = row[0]
            cr.execute('UPDATE discipline_case SET offense_id = %s WHERE id = %s;', (new_id, cid))
            print(f'Relinked case {cname} from offense {off_id} ({code}) to offense {new_id} ({new_code})')
        else:
            print(f'Warning: no candidate for {new_code}')

conn.commit()

# Clean up ir_model_data for discipline_management / discipline.offense so Odoo can cleanly refresh
cr.execute('DELETE FROM ir_model_data WHERE module = %s AND model = %s;', ('discipline_management', 'discipline.offense'))
cr.execute('DELETE FROM ir_model_data WHERE module = %s AND model = %s;', ('discipline_management', 'discipline.article'))
conn.commit()
print('Cleaned old ir_model_data for clean seed reload.')
conn.close()

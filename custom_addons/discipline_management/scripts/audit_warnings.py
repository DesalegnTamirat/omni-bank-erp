import glob
import re

print("AUDITING DISCIPLINE_MANAGEMENT XML FILES FOR ODOO 19 WARNINGS:")
files = sorted(glob.glob('/mnt/extra-addons/discipline_management/**/*.xml', recursive=True))

for f in files:
    content = open(f, encoding='utf-8').read()
    
    # 1. Check alert-* divs without role
    for m in re.finditer(r'<div[^>]*class=["\'][^"\']*alert-[^"\']*["\'][^>]*>', content):
        tag = m.group(0)
        if 'role=' not in tag and 'alert-link' not in tag:
            line_no = content[:m.start()].count('\n') + 1
            print(f"ALERT WITHOUT ROLE: {f}:{line_no} -> {tag}")
            
    # 2. Check <i> tags with fa classes without title or text
    for m in re.finditer(r'<i[^>]*class=["\'][^"\']*fa\s+[^"\']*["\'][^>]*>(\s*</i>)?', content):
        tag = m.group(0)
        if 'title=' not in tag and 'aria-label=' not in tag:
            # check if it has text inside
            # if self-closing or <i ...></i> without text
            if tag.endswith('/>') or tag.endswith('></i>') or re.match(r'<i[^>]*>\s*</i>', tag):
                line_no = content[:m.start()].count('\n') + 1
                print(f"ICON WITHOUT TITLE: {f}:{line_no} -> {tag}")

print("AUDIT COMPLETE.")

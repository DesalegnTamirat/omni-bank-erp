from pathlib import Path
p = Path('d:/odoo19/custom_addons/discipline_management/views/discipline_case_views.xml')
text = p.read_text(encoding='utf-8')
lines = text.splitlines()
print('first 20 lines:')
for i, line in enumerate(lines[:20], start=1):
    print(f'{i}: {line!r}')
print('--- line 6 ---')
print(lines[5]!r)
print('--- any weird chars ---')
for i, char in enumerate(text[:200]):
    if ord(char) < 32 and char not in '\r\n\t':
        print('control char at', i, ord(char))
print('--- parse check ---')
import xml.etree.ElementTree as ET
ET.fromstring(text)
print('xml parse OK')

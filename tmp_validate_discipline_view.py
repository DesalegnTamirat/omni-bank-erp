import xml.etree.ElementTree as ET
from pathlib import Path
p = Path(r'd:\odoo19\custom_addons\discipline_management\views\discipline_case_views.xml')
root = ET.parse(p).getroot()
print('root tag', root.tag)
for r in root.findall('record'):
    rec_id = r.attrib.get('id')
    model = r.attrib.get('model')
    print('record', rec_id, model)
    arch = r.find("field[@name='arch']")
    if arch is None:
        print('  no arch field')
        continue
    # parse inner XML
    xml_str = ''.join(arch.itertext())
    print('  arch text length', len(xml_str))
    # find search view inside arch
    if arch.find('search') is None and arch.find('.//search') is None:
        print('  no search tag under arch')
    else:
        print('  found search tag')
    # print first child of arch
    for child in list(arch):
        print('   arch child:', child.tag, child.attrib)
        break
    if r_id := r.attrib.get('id'):
        print('   record id', r_id)

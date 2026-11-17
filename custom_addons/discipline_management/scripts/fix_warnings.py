import re
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
print(f"Discipline base dir: {BASE_DIR}")

# 1. Fix discipline_offense.py article_id label
offense_py = os.path.join(BASE_DIR, 'models', 'discipline_offense.py')
with open(offense_py, 'r', encoding='utf-8') as f:
    c = f.read()
c = c.replace(
    "article_id = fields.Many2one('discipline.article', string='Governing Article', tracking=True)",
    "article_id = fields.Many2one('discipline.article', string='Statutory Article', tracking=True)"
)
with open(offense_py, 'w', encoding='utf-8') as f:
    f.write(c)
print("Updated discipline_offense.py label")

# 2. Fix icons in discipline_committee_views.xml
comm_xml = os.path.join(BASE_DIR, 'views', 'discipline_committee_views.xml')
with open(comm_xml, 'r', encoding='utf-8') as f:
    c = f.read()
c = c.replace(
    '<i class="fa fa-info-circle text-info"/>',
    '<i class="fa fa-info-circle text-info" title="Managerial Demotion Note"/>'
)
# Also fix alert-heading in discipline_committee_views.xml
c = c.replace('class="alert-heading mb-1 font-weight-bold"', 'class="mb-1 font-weight-bold"')
with open(comm_xml, 'w', encoding='utf-8') as f:
    f.write(c)
print("Updated discipline_committee_views.xml")

# 3. Fix icons in discipline_offense_views.xml
off_xml = os.path.join(BASE_DIR, 'views', 'discipline_offense_views.xml')
with open(off_xml, 'r', encoding='utf-8') as f:
    c = f.read()
c = c.replace(
    '<i class="fa fa-bookmark me-1"/>',
    '<i class="fa fa-bookmark me-1" title="Sub-Article Code"/>'
)
c = c.replace(
    '<i class="fa fa-balance-scale me-2"/>',
    '<i class="fa fa-balance-scale me-2" title="Statutory Provision"/>'
)
c = c.replace(
    '<i class="fa fa-book me-2"/>',
    '<i class="fa fa-book me-2" title="Statutory Clause Text"/>'
)
with open(off_xml, 'w', encoding='utf-8') as f:
    f.write(c)
print("Updated discipline_offense_views.xml")

# 4. Fix alert-heading in discipline_case_views.xml
case_xml = os.path.join(BASE_DIR, 'views', 'discipline_case_views.xml')
with open(case_xml, 'r', encoding='utf-8') as f:
    c = f.read()
c = c.replace('class="alert-heading mb-1 font-weight-bold"', 'class="mb-1 font-weight-bold"')
with open(case_xml, 'w', encoding='utf-8') as f:
    f.write(c)
print("Updated discipline_case_views.xml")

# 5. Fix alert-heading in discipline_suspension_views.xml
susp_xml = os.path.join(BASE_DIR, 'views', 'discipline_suspension_views.xml')
with open(susp_xml, 'r', encoding='utf-8') as f:
    c = f.read()
c = c.replace('class="alert-heading mb-1 font-weight-bold"', 'class="mb-1 font-weight-bold"')
with open(susp_xml, 'w', encoding='utf-8') as f:
    f.write(c)
print("Updated discipline_suspension_views.xml")

# 6. Fix alert-heading in discipline_attendance_case_views.xml
att_xml = os.path.join(BASE_DIR, 'views', 'discipline_attendance_case_views.xml')
with open(att_xml, 'r', encoding='utf-8') as f:
    c = f.read()
c = c.replace('class="alert-heading mb-1 font-weight-bold"', 'class="mb-1 font-weight-bold"')
with open(att_xml, 'w', encoding='utf-8') as f:
    f.write(c)
print("Updated discipline_attendance_case_views.xml")

# 7. Fix alert-heading in discipline_investigation_views.xml
inv_xml = os.path.join(BASE_DIR, 'views', 'discipline_investigation_views.xml')
with open(inv_xml, 'r', encoding='utf-8') as f:
    c = f.read()
c = c.replace('class="alert-heading mb-1 font-weight-bold"', 'class="mb-1 font-weight-bold"')
with open(inv_xml, 'w', encoding='utf-8') as f:
    f.write(c)
print("Updated discipline_investigation_views.xml")

# 8. Fix role="status" and icon in discipline_misconduct_selector_wizard.py
wiz_py = os.path.join(BASE_DIR, 'wizards', 'discipline_misconduct_selector_wizard.py')
with open(wiz_py, 'r', encoding='utf-8') as f:
    c = f.read()
c = c.replace(
    '<div class="alert alert-info text-center my-3 p-4" style="border-radius: 8px;">',
    '<div class="alert alert-info text-center my-3 p-4" role="status" style="border-radius: 8px;">'
)
c = c.replace(
    '<i class="fa fa-info-circle fa-2x mb-2 text-primary d-block"></i>',
    '<i class="fa fa-info-circle fa-2x mb-2 text-primary d-block" title="Information"></i>'
)
with open(wiz_py, 'w', encoding='utf-8') as f:
    f.write(c)
print("Updated discipline_misconduct_selector_wizard.py")

# 9. Fix dashboard alert banner role
dash_xml = os.path.join(BASE_DIR, 'static', 'src', 'xml', 'discipline_dashboard.xml')
with open(dash_xml, 'r', encoding='utf-8') as f:
    c = f.read()
c = c.replace(
    '<div t-if="state.kpis.sla_breached &gt; 0" class="disc-alert-banner" t-on-click="openSlaBreached">',
    '<div t-if="state.kpis.sla_breached &gt; 0" class="disc-alert-banner" role="alert" t-on-click="openSlaBreached">'
)
with open(dash_xml, 'w', encoding='utf-8') as f:
    f.write(c)
print("Updated discipline_dashboard.xml")

print("ALL FIXES APPLIED SUCCESSFULLY!")

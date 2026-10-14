"""Smoke check for the EDS PDF actions in an Odoo shell.

Run with: odoo shell -d DATABASE --shell-file=/mnt/extra-addons/employee_development_system/scripts/verify_report_pdfs.py
Set EDS_PDF_SMOKE_COURSE_PATH to save a sample course certificate PDF.
"""

import os

checks = (
    ('employee_development_system.action_report_eds_course_certificate_preview',
     env['eds.course'].search([], limit=1)),
    ('employee_development_system.action_report_eds_annual_plan_preview',
     env['eds.annual.plan'].search([], limit=1)),
)
for report_xmlid, record in checks:
    if not record:
        print('%s SKIPPED: no sample record' % report_xmlid)
        continue
    content, output_format = env['ir.actions.report']._render_qweb_pdf(report_xmlid, [record.id])
    preview_path = os.environ.get('EDS_PDF_SMOKE_COURSE_PATH')
    if preview_path and report_xmlid.endswith('course_certificate_preview'):
        with open(preview_path, 'wb') as target:
            target.write(content)
    print('%s record=%s format=%s bytes=%s valid_pdf=%s' % (
        report_xmlid, record.id, output_format, len(content), content.startswith(b'%PDF')))

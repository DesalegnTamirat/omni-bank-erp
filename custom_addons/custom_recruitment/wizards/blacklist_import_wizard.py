# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
import base64
import csv


class BlacklistPoolImportWizard(models.TransientModel):
    _name = 'blacklist.pool.import.wizard'
    _description = 'Import Blacklist Pool Excel/CSV'

    file_data = fields.Binary(string="Excel / CSV File", required=True)
    filename = fields.Char(string="File Name")

    def action_download_template(self):
        """Generates and downloads sample Excel/CSV template for Blacklist Pool."""
        header = "Candidate Name,National ID,Gender,Email,Phone,Reason\n"
        ex1 = "Abebe Kebede,NID-100234,Male,abebe@example.com,0911002233,Disciplinary Termination\n"
        ex2 = "Tigist Alemu,NID-500892,Female,tigist@example.com,0922334455,Fraudulent Credentials\n"
        csv_content = header + ex1 + ex2

        file_b64 = base64.b64encode(csv_content.encode('utf-8'))
        attachment = self.env['ir.attachment'].create({
            'name': 'Blacklist_Pool_Import_Template.csv',
            'type': 'binary',
            'datas': file_b64,
            'mimetype': 'text/csv',
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    def action_import_file(self):
        self.ensure_one()
        if not self.file_data:
            raise UserError(_("Please select an Excel or CSV file to import."))

        try:
            decoded = base64.b64decode(self.file_data).decode('utf-8-sig', errors='ignore')
        except Exception as e:
            raise UserError(_("Failed to decode uploaded file: %s") % str(e))

        lines = decoded.splitlines()
        if not lines:
            raise UserError(_("The uploaded file is empty."))

        reader = csv.reader(lines)
        rows = list(reader)
        if not rows:
            raise UserError(_("No rows found in uploaded file."))

        # Detect header row
        header = [str(col).strip().lower() for col in rows[0]]
        start_idx = 1 if any(k in header for k in ('candidate', 'name', 'national id', 'nid', 'email')) else 0

        created_count = 0
        blacklist_pool = self.env['blacklist.pool'].sudo()

        for row in rows[start_idx:]:
            if not row or not any(row):
                continue

            name = row[0].strip() if len(row) > 0 else ''
            nid = row[1].strip() if len(row) > 1 else ''
            gender = row[2].strip() if len(row) > 2 else 'Male'
            email = row[3].strip() if len(row) > 3 else ''
            phone = row[4].strip() if len(row) > 4 else ''
            reason = row[5].strip() if len(row) > 5 else ''

            if not name and not nid:
                continue

            if gender.lower() in ('female', 'f'):
                gender_val = 'Female'
            elif gender.lower() in ('male', 'm'):
                gender_val = 'Male'
            else:
                gender_val = 'Other'

            # Avoid duplicates if NID or Candidate Name exists
            existing = False
            if nid:
                existing = blacklist_pool.search([('national_id', '=ilike', nid)], limit=1)
            if not existing and name:
                existing = blacklist_pool.search([('candidate', '=ilike', name)], limit=1)

            if existing:
                existing.write({
                    'gender': gender_val,
                    'national_id': nid or existing.national_id,
                    'email': email or existing.email,
                    'phone': phone or existing.phone,
                    'reason': reason or existing.reason,
                })
            else:
                blacklist_pool.create({
                    'candidate': name or nid,
                    'national_id': nid,
                    'gender': gender_val,
                    'email': email,
                    'phone': phone,
                    'reason': reason,
                })
            created_count += 1

        # Re-compute blacklist flag on all external applicant records
        self.env['external.recruitment.eligible.employees'].sudo().search([])._compute_is_blacklisted()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Import Completed'),
                'message': _('Successfully processed %d Blacklist Pool records.') % created_count,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

# -*- coding: utf-8 -*-
import base64
import csv
import io
import re
from datetime import datetime, date
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


def parse_termination_date(val):
    """Flexibly parses various date formats found in inter-bank termination circulars,
    e.g. 'September 09/2021', 'February 21,2023', 'March 16,2023', '2023-03-16', '16/03/2023'."""
    if not val:
        return False
    if isinstance(val, (datetime, )):
        return val.date()
    if isinstance(val, date):
        return val
    s = str(val).strip()
    if not s or s.lower() in ('none', 'false', 'n/a', '-'):
        return False

    # Normalize delimiters: replace '/' and ',' with spaces
    s_clean = re.sub(r'[/,]', ' ', s)
    s_clean = ' '.join(s_clean.split())

    formats = [
        '%B %d %Y',   # 'September 09 2021'
        '%b %d %Y',   # 'Sep 09 2021'
        '%Y-%m-%d',   # '2021-09-09'
        '%d %m %Y',   # '09 09 2021'
        '%m %d %Y',   # '09 09 2021'
        '%d-%b-%Y',   # '09-Sep-2021'
        '%d %B %Y',   # '09 September 2021'
        '%Y %m %d',
    ]
    for fmt in formats:
        try:
            return datetime.strptime(s_clean, fmt).date()
        except Exception:
            pass

    # Try original string against standard ISO / slash formats
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y'):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            pass

    return False


class BlacklistPoolImportWizard(models.TransientModel):
    _name = 'blacklist.pool.import.wizard'
    _description = 'Import Blacklist Pool Excel/CSV'

    file_data = fields.Binary(string="Excel / CSV File", required=True)
    filename = fields.Char(string="File Name")

    def action_download_template(self):
        """Generates and downloads sample Excel/CSV template for Blacklist Pool matching the official bank template."""
        header = 'Name,Name of the Bank,Reasons For Termination,Date of Termination\n'
        ex1 = 'Belay Mekonnen Taye,Wegagen Bank,Fraud,September 09/2021\n'
        ex2 = 'Melaku Lingereh Zerihun,Wegagen Bank,Fraud,"February 21, 2023"\n'
        ex3 = 'Kedir Beriso Waritu,Oromia Bank,Hires Employee By Forged Work Experience,"March 16, 2023"\n'
        ex4 = 'Bilen Mekonnen Gebregiorgis,Abay Bank,Submit Forged Educational Document,"February 06, 2023"\n'
        ex5 = 'Kidus Ayal Mengistie,Abay Bank,Submit Forged Educational Document,"February 06, 2023"\n'
        csv_content = header + ex1 + ex2 + ex3 + ex4 + ex5

        file_b64 = base64.b64encode(csv_content.encode('utf-8'))
        attachment = self.env['ir.attachment'].create({
            'name': 'Blacklist_Pool_Template.csv',
            'type': 'binary',
            'datas': file_b64,
            'mimetype': 'text/csv',
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    def _extract_rows_from_file(self, raw_bytes, filename=''):
        """Extracts list of row tuples from Excel (.xlsx, .xls) or CSV file."""
        rows = []
        fn = (filename or '').lower()

        # 1. Try XLSX with openpyxl
        if fn.endswith('.xlsx') or not fn:
            try:
                import openpyxl
                wb = openpyxl.load_workbook(io.BytesIO(raw_bytes), data_only=True)
                sheet = wb.active
                for row in sheet.iter_rows(values_only=True):
                    if any(cell is not None and str(cell).strip() for cell in row):
                        rows.append([str(c).strip() if c is not None else '' for c in row])
                if rows:
                    return rows
            except Exception as e:
                _logger.debug("openpyxl parsing skipped or failed: %s", e)

        # 2. Try XLS with xlrd
        if fn.endswith('.xls') or not fn:
            try:
                import xlrd
                wb = xlrd.open_workbook(file_contents=raw_bytes)
                sheet = wb.sheet_by_index(0)
                for r in range(sheet.nrows):
                    row_vals = sheet.row_values(r)
                    if any(cell is not None and str(cell).strip() for cell in row_vals):
                        rows.append([str(c).strip() if c is not None else '' for c in row_vals])
                if rows:
                    return rows
            except Exception as e:
                _logger.debug("xlrd parsing skipped or failed: %s", e)

        # 3. Fallback to CSV / text parsing
        try:
            decoded = raw_bytes.decode('utf-8-sig', errors='ignore')
            reader = csv.reader(decoded.splitlines())
            for row in reader:
                if any(str(c).strip() for c in row):
                    rows.append([str(c).strip() for c in row])
        except Exception as e:
            _logger.debug("CSV parsing failed: %s", e)

        return rows

    def action_import_file(self):
        self.ensure_one()
        if not self.file_data:
            raise UserError(_("Please select an Excel (.xlsx / .xls) or CSV file to import."))

        try:
            raw_bytes = base64.b64decode(self.file_data)
        except Exception as e:
            raise UserError(_("Failed to decode uploaded file: %s") % str(e))

        rows = self._extract_rows_from_file(raw_bytes, self.filename)
        if not rows:
            raise UserError(_("The uploaded file contains no readable data rows."))

        # ── Detect Header Row & Column Indexes ───────────────────────────────
        header = [str(col).strip().lower() for col in rows[0]]
        start_idx = 0

        # Default standard column indices: 0: Name, 1: Bank, 2: Reason, 3: Date
        name_col = 0
        bank_col = 1
        reason_col = 2
        date_col = 3

        if any(k in ' '.join(header) for k in ('name', 'bank', 'reason', 'termination', 'date')):
            start_idx = 1
            for idx, col_name in enumerate(header):
                if 'bank' in col_name:
                    bank_col = idx
                elif any(k in col_name for k in ('reason', 'misconduct', 'cause')):
                    reason_col = idx
                elif any(k in col_name for k in ('date', 'when')):
                    date_col = idx
                elif 'name' in col_name:
                    name_col = idx

        created_count = 0
        updated_count = 0
        blacklist_pool = self.env['blacklist.pool'].sudo()

        for row in rows[start_idx:]:
            if not row or not any(row):
                continue

            name = row[name_col].strip() if len(row) > name_col else ''
            bank = row[bank_col].strip() if len(row) > bank_col else ''
            reason = row[reason_col].strip() if len(row) > reason_col else ''
            raw_date = row[date_col].strip() if len(row) > date_col else ''

            if not name:
                continue

            parsed_date = parse_termination_date(raw_date)
            # In unquoted CSV files, dates like 'February 21,2023' may be split across date_col and date_col + 1
            if not parsed_date and len(row) > date_col + 1:
                combined_date = f"{raw_date} {row[date_col + 1]}".strip()
                parsed_date = parse_termination_date(combined_date)

            # Check if person already exists under the same bank
            domain = [('candidate', '=ilike', name)]
            if bank:
                domain.append(('name_of_bank', '=ilike', bank))

            existing = blacklist_pool.search(domain, limit=1)
            if existing:
                vals_to_write = {}
                if bank and not existing.name_of_bank:
                    vals_to_write['name_of_bank'] = bank
                if reason:
                    vals_to_write['reason'] = reason
                if parsed_date:
                    vals_to_write['date_of_termination'] = parsed_date
                if vals_to_write:
                    existing.write(vals_to_write)
                updated_count += 1
            else:
                blacklist_pool.create({
                    'candidate': name,
                    'name_of_bank': bank or _('Not Specified'),
                    'reason': reason or _('Blacklisted - Inter-Bank Circular'),
                    'date_of_termination': parsed_date or False,
                })
                created_count += 1

        # Re-compute blacklist flag on all external applicant records
        if 'external.recruitment.eligible.employees' in self.env:
            try:
                self.env['external.recruitment.eligible.employees'].sudo().search([])._compute_is_blacklisted()
            except Exception:
                pass

        total_processed = created_count + updated_count
        msg = _(
            "Blacklist Pool Import Completed:\n"
            "• Created: %d new blacklisted record(s)\n"
            "• Updated: %d existing record(s)"
        ) % (created_count, updated_count)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Import Successful'),
                'message': msg,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

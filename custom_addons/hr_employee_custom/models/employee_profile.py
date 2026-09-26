# -*- coding: utf-8 -*-
from odoo import models, fields, api
import base64
import logging

_logger = logging.getLogger(__name__)


import re

def _clean_b64(raw):
    """Normalize raw picture data (bytes/str/base64/data-uri/double-base64) to clean Base64 string for Odoo."""
    if not raw:
        return False
    if isinstance(raw, (memoryview, bytearray)):
        raw = bytes(raw)
    try:
        if isinstance(raw, bytes):
            # Raw binary image (JPEG / PNG / GIF / WEBP / BMP)
            if raw.startswith((b'\xff\xd8', b'\x89PNG', b'GIF8', b'RIFF', b'BM')):
                return base64.b64encode(raw).decode('utf-8')
            try:
                raw = raw.decode('utf-8')
            except UnicodeDecodeError:
                return base64.b64encode(raw).decode('utf-8')

        if isinstance(raw, str):
            txt = raw.strip()
            if ',' in txt and 'base64' in txt[:50]:
                txt = txt.split(',', 1)[1].strip()
            txt = re.sub(r'[\r\n\s]+', '', txt)

            if txt.startswith(('/9j/', 'iVBOR', 'R0lG', 'Qk0=', 'UklGR')):
                return txt

            try:
                dec = base64.b64decode(txt)
                if dec.startswith((b'\xff\xd8', b'\x89PNG', b'GIF8', b'RIFF', b'BM')):
                    return base64.b64encode(dec).decode('utf-8')
                if dec.startswith((b'/9j/', b'iVBOR', b'R0lG', b'Qk0=', b'UklGR')):
                    return dec.decode('utf-8').strip()
            except Exception:
                pass

            return txt
    except Exception as e:
        _logger.warning("Error normalizing picture b64: %s", e)
    return False


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if not self.env.context.get('skip_emp_profile_sync'):
            for record, vals in zip(records, vals_list):
                image_value = vals.get('image_1920', False)
                if image_value:
                    b64_val = _clean_b64(image_value)
                    if b64_val:
                        self._insert_into_emp_profile(record.id, b64_val)
        return records

    def write(self, vals):
        res = super().write(vals)
        if not self.env.context.get('skip_emp_profile_sync'):
            image_value = vals.get('image_1920', False)
            if image_value:
                b64_val = _clean_b64(image_value)
                if b64_val:
                    for emp in self:
                        self._insert_into_emp_profile(emp.id, b64_val)
        return res

    def read(self, fields=None, load='_classic_read'):
        records = super().read(fields=fields, load=load)
        image_fields = {'image_1920', 'avatar_1920', 'image_128', 'avatar_128', 'image_512', 'avatar_512', 'image_256', 'avatar_256'}
        if not fields or any(f in fields for f in image_fields):
            for emp_dict in records:
                emp_id = emp_dict.get('id')
                if emp_id:
                    has_missing = any(f in emp_dict and not emp_dict[f] for f in image_fields)
                    if has_missing or not emp_dict.get('image_1920') or not emp_dict.get('avatar_128'):
                        try:
                            with self.env.cr.savepoint():
                                self.env.cr.execute("""
                                    SELECT p.profile_picture 
                                    FROM employee_profile_photo p
                                    WHERE p.employee_id = %s
                                      AND p.profile_picture IS NOT NULL
                                    LIMIT 1
                                """, (emp_id,))
                                row = self.env.cr.fetchone()
                                if row and row[0]:
                                    pic_b64 = _clean_b64(row[0])
                                    if pic_b64:
                                        for img_f in image_fields:
                                            if img_f in emp_dict and not emp_dict[img_f]:
                                                emp_dict[img_f] = pic_b64
                                        if 'image_1920' in emp_dict and not emp_dict['image_1920']:
                                            emp_dict['image_1920'] = pic_b64
                                        if 'avatar_128' in emp_dict and not emp_dict['avatar_128']:
                                            emp_dict['avatar_128'] = pic_b64
                        except Exception:
                            pass
        return records

    @api.model
    def action_sync_all_profile_photos(self, batch_size=50):
        """Sync photos from employee_profile_photo table in small batches to prevent MemoryError."""
        self.env.cr.execute("SELECT count(*) FROM employee_profile_photo")
        total_in_table = self.env.cr.fetchone()[0] or 0

        # Match employee_profile_photo.employee_id directly to hr_employee.id (integer primary key)
        self.env.cr.execute("""
            SELECT DISTINCT e.id AS emp_id, p.id AS photo_id
            FROM employee_profile_photo p
            INNER JOIN hr_employee e ON e.id = p.employee_id
            WHERE p.profile_picture IS NOT NULL
            ORDER BY e.id
        """)
        matching_pairs = self.env.cr.fetchall()
        total_matching = len(matching_pairs)

        count = 0
        skipped = 0

        # Process in batches of 50 to keep RAM usage under 5MB per batch
        for i in range(0, total_matching, batch_size):
            batch_pairs = matching_pairs[i:i + batch_size]
            if not batch_pairs:
                continue

            photo_ids = [p[1] for p in batch_pairs]

            query = """
                SELECT p.employee_id, p.profile_picture, e.id AS matched_emp_id
                FROM employee_profile_photo p
                INNER JOIN hr_employee e ON e.id = p.employee_id
                WHERE p.id IN %s AND p.profile_picture IS NOT NULL
            """
            self.env.cr.execute(query, (tuple(photo_ids),))
            batch_rows = self.env.cr.fetchall()

            for orig_emp_id, pic_raw, matched_emp_id in batch_rows:
                target_id = matched_emp_id or orig_emp_id
                if not target_id or not pic_raw:
                    skipped += 1
                    continue
                pic_b64 = _clean_b64(pic_raw)
                if pic_b64:
                    try:
                        with self.env.cr.savepoint():
                            emp = self.env['hr.employee'].sudo().browse(target_id)
                            if emp.exists():
                                emp.with_context(skip_emp_profile_sync=True).write({'image_1920': pic_b64})
                                count += 1
                            else:
                                skipped += 1
                    except Exception as e:
                        _logger.warning("Failed writing image_1920 for employee %s: %s", target_id, str(e))
                        skipped += 1

            # Commit batch and flush memory after every 50 records
            self.env.cr.commit()

        _logger.info("Photo sync stats — Total Table: %s, Matching: %s, Synced: %s, Skipped: %s", total_in_table, total_matching, count, skipped)
        return {
            'count': count,
            'total_table': total_in_table,
            'skipped': skipped,
        }

    def _insert_into_emp_profile(self, emp_id, image_base64):
        """Insert/update photo into employee_profile_photo table as bytea using hr_employee.id."""
        current_uid = self.env.uid
        current_time = fields.Datetime.now()

        self.env.cr.execute(
            "SELECT id FROM employee_profile_photo WHERE employee_id = %s LIMIT 1",
            (emp_id,)
        )
        row = self.env.cr.fetchone()
        if row:
            query = """
                UPDATE employee_profile_photo
                SET profile_picture = decode(%s, 'base64'),
                    write_uid = %s,
                    write_date = %s
                WHERE employee_id = %s
            """
            self.env.cr.execute(query, (image_base64, current_uid, current_time, emp_id))
        else:
            query = """
                INSERT INTO employee_profile_photo (
                    employee_id,
                    profile_picture,
                    create_uid,
                    create_date,
                    write_uid,
                    write_date
                ) VALUES (%s, decode(%s, 'base64'), %s, %s, %s, %s)
            """
            self.env.cr.execute(query, (emp_id, image_base64, current_uid, current_time, current_uid, current_time))

# -*- coding: utf-8 -*-
import json
import logging
from odoo.http import request

_logger = logging.getLogger(__name__)

try:
    from odoo.addons.web.controllers import export

    _orig_xlsx_writer_init = export.ExportXlsxWriter.__init__
    _orig_filename = export.ExportFormat.filename

    def _bunna_export_xlsx_writer_init(self, fields, columns_headers, row_count=0):
        _orig_xlsx_writer_init(self, fields, columns_headers, row_count=row_count)
        try:
            # Apply official Bunna Bank branding to all Excel exports (#541718)
            if hasattr(self, "worksheet"):
                self.worksheet.set_tab_color('#541718')
                self.worksheet.set_row(0, 26)

            # Bunna brand header burgundy/maroon: #541718, dark border: #3D1011
            self.header_style = self.workbook.add_format({
                'bold': True,
                'bg_color': '#541718',
                'font_color': '#FFFFFF',
                'font_name': 'Segoe UI',
                'font_size': 11,
                'border': 1,
                'border_color': '#3D1011',
                'align': 'center',
                'valign': 'vcenter',
                'text_wrap': True,
            })
            self.header_bold_style = self.workbook.add_format({
                'bold': True,
                'bg_color': '#541718',
                'font_color': '#FFFFFF',
                'font_name': 'Segoe UI',
                'font_size': 11,
                'text_wrap': True,
                'border': 1,
                'border_color': '#3D1011',
            })
            if hasattr(self, "header_bold_style_float"):
                self.header_bold_style_float = self.workbook.add_format({
                    'bold': True,
                    'bg_color': '#541718',
                    'font_color': '#FFFFFF',
                    'font_name': 'Segoe UI',
                    'font_size': 11,
                    'text_wrap': True,
                    'num_format': '#,##0.00',
                    'border': 1,
                    'border_color': '#3D1011',
                })
            if hasattr(self, "header_bold_style_monetary"):
                self.header_bold_style_monetary = self.workbook.add_format({
                    'bold': True,
                    'bg_color': '#541718',
                    'font_color': '#FFFFFF',
                    'font_name': 'Segoe UI',
                    'font_size': 11,
                    'text_wrap': True,
                    'num_format': '#,##0.00',
                    'border': 1,
                    'border_color': '#3D1011',
                })

            # Base row styling with clean typography and soft borders
            self.base_style = self.workbook.add_format({
                'text_wrap': True,
                'font_name': 'Segoe UI',
                'font_size': 10,
                'border': 1,
                'border_color': '#E2E8F0',
                'valign': 'vcenter',
            })
            self.date_style = self.workbook.add_format({
                'text_wrap': True,
                'font_name': 'Segoe UI',
                'font_size': 10,
                'num_format': 'yyyy-mm-dd',
                'align': 'center',
                'valign': 'vcenter',
                'border': 1,
                'border_color': '#E2E8F0',
            })
            self.datetime_style = self.workbook.add_format({
                'text_wrap': True,
                'font_name': 'Segoe UI',
                'font_size': 10,
                'num_format': 'yyyy-mm-dd hh:mm:ss',
                'align': 'center',
                'valign': 'vcenter',
                'border': 1,
                'border_color': '#E2E8F0',
            })
        except Exception as e:
            _logger.warning("Could not apply Bunna header styling to standard export: %s", str(e))

    def _bunna_filename(self, base):
        orig = _orig_filename(self, base)
        if not orig.startswith("Bunna_Bank_"):
            return f"Bunna_Bank_{orig.replace(' ', '_')}"
        return orig

    export.ExportXlsxWriter.__init__ = _bunna_export_xlsx_writer_init
    export.ExportFormat.filename = _bunna_filename

except Exception as e:
    _logger.warning("Could not patch web ExportXlsxWriter for Bunna branding: %s", str(e))

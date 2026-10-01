# -*- coding: utf-8 -*-
import json
import logging
from odoo.http import request

_logger = logging.getLogger(__name__)

try:
    from odoo.addons.web.controllers import export

    _orig_xlsx_writer_init = export.ExportXlsxWriter.__init__

    def _pbms_export_xlsx_writer_init(self, fields, columns_headers, row_count=0):
        _orig_xlsx_writer_init(self, fields, columns_headers, row_count=row_count)
        try:
            model = ""
            if request and hasattr(request, "params"):
                data = request.params.get("data")
                if isinstance(data, str):
                    try:
                        data = json.loads(data)
                    except Exception:
                        data = {}
                if isinstance(data, dict):
                    model = data.get("model", "")

            # Apply official Bunna Bank branding (#541718) to all Excel exports
            if hasattr(self, "worksheet"):
                self.worksheet.set_tab_color('#541718')
                self.worksheet.set_row(0, 26)

            # Bunna brand burgundy/maroon: #541718
            self.header_style = self.workbook.add_format({
                'bold': True,
                'bg_color': '#541718',
                'font_color': '#FFFFFF',
                'font_name': 'Segoe UI',
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
                'text_wrap': True,
            })
            if hasattr(self, "header_bold_style_float"):
                self.header_bold_style_float = self.workbook.add_format({
                    'bold': True,
                    'bg_color': '#541718',
                    'font_color': '#FFFFFF',
                    'font_name': 'Segoe UI',
                    'text_wrap': True,
                    'num_format': '#,##0.00',
                })
            if hasattr(self, "header_bold_style_monetary"):
                self.header_bold_style_monetary = self.workbook.add_format({
                    'bold': True,
                    'bg_color': '#541718',
                    'font_color': '#FFFFFF',
                    'font_name': 'Segoe UI',
                    'text_wrap': True,
                    'num_format': '#,##0.00',
                })
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

    export.ExportXlsxWriter.__init__ = _pbms_export_xlsx_writer_init

except Exception as e:
    _logger.warning("Could not patch web ExportXlsxWriter: %s", str(e))

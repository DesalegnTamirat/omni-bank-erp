# -*- coding: utf-8 -*-
import io
import logging
from datetime import datetime

_logger = logging.getLogger(__name__)


def add_watermark_to_pdf(pdf_bytes, text_lines):
    """
    Applies a dynamic diagonal semi-transparent watermark to every page of a PDF.
    text_lines: list of strings to print diagonally, e.g.:
      ['CONFIDENTIAL - BUNNA BANK S.C.',
       'Downloaded by: Abebe Kebede (EMP0123)',
       'Dept: Information Technology | 2026-09-18 14:30:00']
    """
    if not pdf_bytes:
        return pdf_bytes
    try:
        from reportlab.lib.colors import Color
        from reportlab.pdfgen import canvas
        try:
            import PyPDF2 as pypdf_lib
        except ImportError:
            import pypdf as pypdf_lib

        input_pdf_stream = io.BytesIO(pdf_bytes)
        reader = pypdf_lib.PdfReader(input_pdf_stream)
        writer = pypdf_lib.PdfWriter()

        for page in reader.pages:
            try:
                width = float(page.mediabox.width)
                height = float(page.mediabox.height)
            except Exception:
                width, height = 595.27, 841.89  # Default A4

            packet = io.BytesIO()
            can = canvas.Canvas(packet, pagesize=(width, height))
            can.saveState()

            # Bunna maroon tinted semi-transparent watermark: #541718 with alpha
            can.setFillColor(Color(0.33, 0.09, 0.09, alpha=0.18))
            can.translate(width / 2.0, height / 2.0)
            can.rotate(45)

            font_size = max(13, int(min(width, height) / 36))
            can.setFont("Helvetica-Bold", font_size)

            y_offset = (len(text_lines) - 1) * (font_size * 0.7)
            for line in text_lines:
                can.drawCentredString(0, y_offset, str(line))
                y_offset -= (font_size * 1.5)

            can.restoreState()
            can.save()

            packet.seek(0)
            watermark_pdf = pypdf_lib.PdfReader(packet)
            watermark_page = watermark_pdf.pages[0]

            if hasattr(page, 'merge_page'):
                page.merge_page(watermark_page)
            elif hasattr(page, 'mergePage'):
                page.mergePage(watermark_page)

            writer.add_page(page)

        output_stream = io.BytesIO()
        writer.write(output_stream)
        return output_stream.getvalue()

    except Exception as e:
        _logger.warning("Failed to apply PDF watermark: %s. Returning raw bytes.", e)
        return pdf_bytes

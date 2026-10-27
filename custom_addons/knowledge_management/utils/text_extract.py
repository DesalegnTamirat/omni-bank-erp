"""Bounded text extraction for uploaded, searchable KMS documents.

This deliberately handles text PDFs and the XML-based Office formats only.
Scanned pages and legacy binary Office files require a separate OCR/conversion
service; an upload must remain possible when text extraction is unavailable.
"""

import base64
import binascii
import io
import logging
import zipfile
from xml.etree import ElementTree

_logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_MEMBER_BYTES = 5 * 1024 * 1024
MAX_TOTAL_XML_BYTES = 20 * 1024 * 1024
MAX_EXTRACTED_CHARS = 100_000
MAX_PDF_PAGES = 100


def extract_document_text(encoded, filename):
    """Return searchable text from a small PDF, DOCX, XLSX, or plain text file.

    ``encoded`` is the value passed to an Odoo Binary field. Invalid, oversized,
    encrypted, or image-only files yield an empty string without blocking upload.
    """
    if not encoded or not filename:
        return ''
    try:
        if isinstance(encoded, str):
            encoded = encoded.encode('ascii')
        if len(encoded) > (MAX_UPLOAD_BYTES * 4 // 3 + 16):
            return ''
        payload = base64.b64decode(encoded, validate=True)
        if len(payload) > MAX_UPLOAD_BYTES:
            return ''
        extension = filename.lower().rsplit('.', 1)[-1]
        if extension == 'pdf':
            return _extract_pdf(payload)
        if extension in ('docx', 'xlsx'):
            return _extract_ooxml(payload, extension)
        if extension in ('txt', 'csv'):
            return payload.decode('utf-8', errors='replace')[:MAX_EXTRACTED_CHARS]
    except (ValueError, binascii.Error, OSError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        _logger.info('KMS text extraction skipped for %s: %s', filename, exc)
    except Exception as exc:  # pypdf and malformed OOXML raise format-specific errors.
        _logger.info('KMS text extraction unavailable for %s: %s', filename, exc)
    return ''


def _extract_pdf(payload):
    from PyPDF2 import PdfReader

    reader = PdfReader(io.BytesIO(payload), strict=False)
    if reader.is_encrypted:
        return ''
    parts = []
    size = 0
    for page in reader.pages[:MAX_PDF_PAGES]:
        text = page.extract_text() or ''
        remaining = MAX_EXTRACTED_CHARS - size
        if remaining <= 0:
            break
        text = text[:remaining]
        parts.append(text)
        size += len(text)
    return '\n'.join(parts)


def _extract_ooxml(payload, extension):
    parts = []
    remaining = MAX_EXTRACTED_CHARS
    total_xml = 0
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for member in archive.infolist():
            name = member.filename
            if extension == 'docx':
                selected = (name == 'word/document.xml' or
                            name.startswith(('word/header', 'word/footer')) and name.endswith('.xml'))
                tag = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t'
            else:
                selected = (name == 'xl/sharedStrings.xml' or
                            name.startswith('xl/worksheets/sheet') and name.endswith('.xml'))
                tag = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t'
            if not selected:
                continue
            total_xml += member.file_size
            if member.file_size > MAX_MEMBER_BYTES or total_xml > MAX_TOTAL_XML_BYTES:
                return '\n'.join(parts)
            xml_bytes = archive.read(member)
            root = ElementTree.fromstring(xml_bytes)
            for node in root.iter(tag):
                if not node.text:
                    continue
                value = node.text[:remaining]
                parts.append(value)
                remaining -= len(value)
                if remaining <= 0:
                    return '\n'.join(parts)
    return '\n'.join(parts)

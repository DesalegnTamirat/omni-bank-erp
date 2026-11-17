# -*- coding: utf-8 -*-

import base64
import io
import re
import zipfile
import xml.etree.ElementTree as ET
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class ExamPdfImportWizard(models.TransientModel):
    """
    Document / Word (.docx) / PDF / Text Exam Paper Question Importer (FR-EXM-003, FR-EXM-006)
    ========================================================================================
    Allows HR and Work Units to upload exam papers in Word (.docx), PDF, or Text format,
    automatically extracts question stems, 4 question types (Essay, MCQ, True/False, Fill-in-the-Blank),
    options, answer keys, and routing them into the Question Bank Review & Approval Queue.
    """
    _name = "exam.pdf.import.wizard"
    _description = "Import Exam Questions from Word (.docx), PDF, or Text Document"

    operating_unit_id = fields.Many2one(
        "operating.unit",
        string="Submitting Work Unit",
        default=lambda self: getattr(self.env.user.employee_id, "default_operating_unit_id", False) or getattr(self.env.user.employee_id, "operating_unit_id", False),
        required=True
    )
    job_id = fields.Many2one(
        "hr.job",
        string="Target Job Position",
        required=True
    )
    department_id = fields.Many2one("hr.department", string="Department")
    competency_id = fields.Many2one(
        "competency.competency",
        string="Competence Pillar",
        required=True,
    )
    
    difficulty = fields.Selection([
        ("basic", "Basic"),
        ("easy", "Easy"),
        ("hard", "Hard"),
    ], string="Default Difficulty Level", default="easy", required=True)

    default_marks = fields.Float(string="Default Marks Per Question", default=1.0, required=True)
    
    file_data = fields.Binary(string="Upload Exam File (.docx / .pdf / .txt)", required=True)
    file_name = fields.Char(string="File Name")

    raw_text_preview = fields.Text(string="Extracted Text Preview", readonly=True)
    imported_count = fields.Integer(string="Imported Questions Count", readonly=True)

    eligible_job_ids = fields.Json(string="Eligible Job IDs", compute="_compute_eligible_job_ids", default=[])
    eligible_competency_ids = fields.Json(string="Eligible Competency IDs", compute="_compute_eligible_competency_ids", default=[])

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        ou_id = res.get("operating_unit_id")
        ou = self.env["operating.unit"].browse(ou_id) if ou_id else False
        res["eligible_job_ids"] = self._get_active_ou_jobs(ou).ids or []

        job_id = res.get("job_id")
        job = self.env["hr.job"].browse(job_id) if job_id else False
        comps = self._get_job_competencies(job, ou)

        pillar_comps = self.env["competency.competency"]
        if comps:
            for p in ["core", "leadership", "technical"]:
                p_match = comps.filtered(lambda c: c.pillar == p)
                if p_match:
                    pillar_comps |= p_match[0]
        if not pillar_comps:
            for p in ["core", "leadership", "technical"]:
                p_match = self.env["competency.competency"].search([
                    ("pillar", "=", p),
                    ("status", "=", "active")
                ], limit=1)
                if p_match:
                    pillar_comps |= p_match

        res["eligible_competency_ids"] = pillar_comps.ids or []
        if pillar_comps and not res.get("competency_id"):
            res["competency_id"] = pillar_comps[0].id
        return res

    def _resolve_record_id(self, rec):
        """Safely extract integer database ID from a record or NewId in memory."""
        if not rec:
            return False
        return getattr(rec, "_origin", rec).id or (isinstance(rec.id, int) and rec.id) or (rec.ids and rec.ids[0]) or False

    def _get_active_ou_jobs(self, ou):
        """Return only active job positions configured or held by employees in the given operating unit."""
        ou_id = self._resolve_record_id(ou)
        if not ou_id:
            return self.env["hr.job"].browse([])

        ou_positions = self.env["operating.unit.job.position"].search([
            ("operating_unit_id", "=", ou_id)
        ]).mapped("job_position_id").filtered(lambda j: j.active)

        emp_positions = self.env["hr.employee"].search([
            ("active", "=", True),
            "|",
            ("default_operating_unit_id", "=", ou_id),
            ("operating_unit_id", "=", ou_id),
        ]).mapped("job_position").filtered(lambda j: j.active)

        return (ou_positions | emp_positions)

    def _get_job_competencies(self, job=None, ou=None):
        """Return competencies mapped to the selected job position from Competency Role Mapping,
        Recruitment Vacancies, and HR Job competencies. If no job is selected, returns competencies
        for all jobs in the operating unit.
        """
        jid = self._resolve_record_id(job)
        comps = self.env["competency.competency"].browse([])

        if jid:
            # 1. From Competency Management Module: Competence Role Mapping (competency.role.mapping)
            mappings = self.env["competency.role.mapping"].search([
                ("job_position_id", "=", jid),
                ("state", "in", ["approved", "draft", "under_approval"]),
            ])
            if not mappings:
                mappings = self.env["competency.role.mapping"].search([
                    ("job_position_id", "=", jid),
                ])
            comps |= mappings.mapped("line_ids.competency_id")

            # 2. From Recruitment Module: Job Vacancy Competencies (job.vacancy.competency)
            vac_comps = self.env["job.vacancy.competency"].search([
                ("vacancy_id.job_position", "=", jid),
            ]).mapped("competency_id")
            comps |= vac_comps

            # 3. From HR Job direct competencies (hr_competencies_info_job)
            job_rec = self.env["hr.job"].browse(jid)
            comp_rel = getattr(job_rec, "competencies_id", False) or getattr(job_rec, "competencies_ids", False)
            if comp_rel:
                for line in comp_rel:
                    c = getattr(line, "competencies", False) or getattr(line, "competency_id", False)
                    if c:
                        comps |= c

            active_comps = comps.filtered(
                lambda c: getattr(c, "active", True) and getattr(c, "status", "active") in ("active", False)
            )
            if active_comps:
                return active_comps

        # If job is not selected, fallback to jobs in the operating unit
        ou_id = self._resolve_record_id(ou)
        if ou_id:
            active_jobs = self._get_active_ou_jobs(ou)
            if active_jobs:
                mappings = self.env["competency.role.mapping"].search([
                    ("job_position_id", "in", active_jobs.ids),
                ])
                comps |= mappings.mapped("line_ids.competency_id")
                vac_comps = self.env["job.vacancy.competency"].search([
                    ("vacancy_id.job_position", "in", active_jobs.ids),
                ]).mapped("competency_id")
                comps |= vac_comps
                active_comps = comps.filtered(
                    lambda c: getattr(c, "active", True) and getattr(c, "status", "active") in ("active", False)
                )
                if active_comps:
                    return active_comps

        # Fallback to all active competencies if none found
        return self.env["competency.competency"].search([("active", "=", True)], limit=100)

    @api.depends("operating_unit_id")
    def _compute_eligible_job_ids(self):
        for rec in self:
            rec.eligible_job_ids = self._get_active_ou_jobs(rec.operating_unit_id).ids or []

    @api.depends("job_id", "operating_unit_id")
    def _compute_eligible_competency_ids(self):
        for rec in self:
            comps = rec._get_job_competencies(rec.job_id, rec.operating_unit_id)
            pillar_comps = self.env["competency.competency"]
            if comps:
                for p in ["core", "leadership", "technical"]:
                    p_match = comps.filtered(lambda c: c.pillar == p)
                    if p_match:
                        pillar_comps |= p_match[0]
            if not pillar_comps:
                for p in ["core", "leadership", "technical"]:
                    p_match = self.env["competency.competency"].search([
                        ("pillar", "=", p),
                        ("status", "=", "active")
                    ], limit=1)
                    if p_match:
                        pillar_comps |= p_match
            rec.eligible_competency_ids = pillar_comps.ids or []

    @api.onchange("operating_unit_id")
    def _onchange_operating_unit_id(self):
        active_jobs = self._get_active_ou_jobs(self.operating_unit_id)
        self.eligible_job_ids = active_jobs.ids or []
        jid = self._resolve_record_id(self.job_id)
        if jid and jid not in active_jobs.ids:
            self.job_id = False
            self.competency_id = False
        return self._onchange_job_id()

    @api.onchange("job_id")
    def _onchange_job_id(self):
        comps = self._get_job_competencies(self.job_id, self.operating_unit_id)
        pillar_comps = self.env["competency.competency"]
        if comps:
            for p in ["core", "leadership", "technical"]:
                p_match = comps.filtered(lambda c: c.pillar == p)
                if p_match:
                    pillar_comps |= p_match[0]
        if not pillar_comps:
            for p in ["core", "leadership", "technical"]:
                p_match = self.env["competency.competency"].search([
                    ("pillar", "=", p),
                    ("status", "=", "active")
                ], limit=1)
                if p_match:
                    pillar_comps |= p_match

        self.eligible_competency_ids = pillar_comps.ids or []

        if self.competency_id and self.competency_id not in pillar_comps:
            self.competency_id = pillar_comps[:1] if len(pillar_comps) == 1 else False
        elif not self.competency_id and len(pillar_comps) == 1:
            self.competency_id = pillar_comps[0]

        return {
            "domain": {
                "competency_id": [("id", "in", pillar_comps.ids)],
            }
        }

    def _extract_text_from_docx(self, raw_bytes):
        """Extracts text from Word .docx file using native zipfile and XML parsing"""
        try:
            with io.BytesIO(raw_bytes) as docx_file:
                with zipfile.ZipFile(docx_file) as zip_archive:
                    if 'word/document.xml' not in zip_archive.namelist():
                        return ""
                    xml_content = zip_archive.read('word/document.xml')
                    tree = ET.fromstring(xml_content)
                    
                    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
                    paragraphs = []
                    
                    for p in tree.findall('.//w:p', ns):
                        texts = [node.text for node in p.findall('.//w:t', ns) if node.text]
                        if texts:
                            paragraphs.append("".join(texts))
                    
                    return "\n".join(paragraphs).replace('\x00', '').strip()
        except Exception:
            return ""

    def _extract_text_from_pdf_or_bytes(self, raw_bytes):
        """Extracts clean text from PDF or plain text bytes without NUL characters"""
        # 1. Use PyPDF2 for proper PDF extraction
        try:
            import PyPDF2
            with io.BytesIO(raw_bytes) as pdf_file:
                reader = PyPDF2.PdfReader(pdf_file)
                chunks = []
                for page in reader.pages:
                    t = page.extract_text()
                    if t:
                        chunks.append(t)
                if chunks:
                    return "\n".join(chunks).replace('\x00', '').strip()
        except Exception:
            pass

        # 2. Plain UTF-8 text fallback
        try:
            decoded = raw_bytes.decode('utf-8', errors='ignore').replace('\x00', '').strip()
            if len(decoded) > 0 and "%PDF" not in decoded[:10]:
                return decoded
        except Exception:
            pass

        # 3. Stream text extractor fallback
        try:
            text_chunks = []
            for match in re.finditer(rb'\((.*?)\)\s*Tj|\[(.*?)\]\s*TJ', raw_bytes):
                chunk = match.group(1) or match.group(2)
                if chunk:
                    clean = re.sub(rb'[^a-zA-Z0-9\s\.\,\?\!\-\:\;\(\)\[\]\_]', b'', chunk).decode('ascii', errors='ignore')
                    if clean.strip():
                        text_chunks.append(clean.strip())
            if text_chunks:
                return "\n".join(text_chunks).replace('\x00', '').strip()
        except Exception:
            pass

        return ""

    def _extract_text(self, raw_base64_data, filename=""):
        """Extracts plain text from base64 document"""
        if not raw_base64_data:
            return ""
        raw_bytes = base64.b64decode(raw_base64_data)
        fname = (filename or "").lower()
        text_content = ""
        if fname.endswith(".docx") or fname.endswith(".doc"):
            text_content = self._extract_text_from_docx(raw_bytes)
        if not text_content or len(text_content.strip()) < 10:
            text_content = self._extract_text_from_pdf_or_bytes(raw_bytes)
        return (text_content or "").replace('\x00', '').strip()

    def _split_questions_and_answers_sections(self, full_text):
        """
        Detects if document contains an Answer Key / Solutions section at the bottom.
        Returns (questions_text, answers_text)
        """
        answer_header_patterns = [
            r'(?i)\n\s*(?:==+|\*\*+|##+)?\s*(?:ANSWERS?\s*KEY|ANSWER\s*KEYS?|SOLUTIONS?|ANSWERS?\s*LIST|CORRECT\s*ANSWERS?|MARKING\s*SCHEME|ANSWER\s*SECTION|EXAM\s*ANSWERS?|ANSWER\s*SHEET|MODEL\s*ANSWERS?|ANSWER\s*GUIDELINES?)\s*(?:==+|\*\*+|##+|[:\-\=])*\s*\n',
            r'(?i)\n\s*(?:SECTION|PART)\s*(?:[2B]|II)\s*[:\-\.]*\s*(?:ANSWERS?|SOLUTIONS?|ANSWER\s*KEYS?)\b',
            r'(?i)\n\s*ANSWER\s*KEY\s*[:\-\=]*\s*\n',
            r'(?i)\n\s*ANSWERS?\s*[:\-\=]+\s*\n',
        ]
        
        for pat in answer_header_patterns:
            match = re.search(pat, full_text)
            if match:
                q_text = full_text[:match.start()].strip()
                a_text = full_text[match.end():].strip()
                if len(q_text) > 10 and len(a_text) > 0:
                    return q_text, a_text

        return full_text, ""

    def _parse_section_header_type(self, txt):
        """Extracts question type from Part / Section headers"""
        m = re.search(r'(?:Part\s+[IVXLCDM\d]+|Section\s+[A-Z\d]+)\s*[\–\-\:]\s*(Essay|Multiple Choice|MCQ|True\s*or\s*False|Fill\s*in\s*the\s*Blank|Short\s*Answer)', txt, re.IGNORECASE)
        if m:
            s = m.group(1).lower()
            if 'essay' in s:
                return 'essay'
            if 'mcq' in s or 'multiple choice' in s:
                return 'mcq_single'
            if 'true' in s:
                return 'true_false'
            if 'blank' in s:
                return 'fill_blank'
            if 'short' in s:
                return 'short_answer'
        return None

    def _parse_answers_dict(self, answers_text):
        """
        Parses an answer key text block into a dictionary: {question_number (int): answer_string}
        """
        answers_dict = {}
        if not answers_text:
            return answers_dict

        blocks = re.split(r'\n(?=(?:Q(?:uestion)?\s*\d+[\.\:\)]|\[?\d+\]?[\.\:\)\-]\s+))', answers_text, flags=re.IGNORECASE)
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            
            match = re.match(r'^(?:Q(?:uestion)?\s*(\d+)[\.\:\)]|\[?(\d+)\]?[\.\:\)\-]\s*)\s*(.*)', block, flags=re.IGNORECASE | re.DOTALL)
            if match:
                q_num_str = match.group(1) or match.group(2)
                try:
                    q_num = int(q_num_str)
                    ans_content = match.group(3).strip()
                    # Strip leading Answer:/Ans:/Key: prefixes
                    ans_content = re.sub(r'^(?:Answer|Ans|Key|Correct Answer|Solution)\s*[:=]\s*', '', ans_content, flags=re.IGNORECASE).strip()
                    # Strip trailing section headers (e.g. "Part II – Multiple Choice Questions")
                    ans_content = re.split(r'\n\s*(?:Part\s+[IVXLCDM\d]+|Section\s+[A-Z\d]+)\b', ans_content, flags=re.IGNORECASE)[0].strip()
                    if ans_content:
                        answers_dict[q_num] = ans_content.replace('\x00', '')
                except ValueError:
                    continue

        if not answers_dict:
            dense_matches = re.findall(r'(?:Q(?:uestion)?\s*(\d+)[\.\:\)]|(\d+)[\.\:\)\-])\s*([A-Ea-e]|True|False|T|F|[\w\.\-]+)(?=\s+(?:Q?\d+[\.\:\)\-]|$)|\s*$)', answers_text, flags=re.IGNORECASE)
            for m in dense_matches:
                q_num_str = m[0] or m[1]
                ans_content = m[2].strip()
                try:
                    q_num = int(q_num_str)
                    answers_dict[q_num] = ans_content.replace('\x00', '')
                except ValueError:
                    continue

        return answers_dict

    def action_parse_and_import(self):
        """
        Parses uploaded Word (.docx), PDF, or Text file, accurately aligns every question (1..N)
        with its matching answer key (1..N), and creates questions in the 'draft' review queue.
        """
        self.ensure_one()
        if not self.file_data:
            raise UserError(_("Please upload a valid exam document file (.docx, .pdf, or .txt)."))

        try:
            # 1. Extract Exam Document Text
            exam_text = self._extract_text(self.file_data, self.file_name)
            if not exam_text or len(exam_text.strip()) < 5:
                raise UserError(_("Could not extract readable text from the uploaded exam document. Please verify the file format."))

            # 2. Split Document into Questions (Top) and Answer Key (Bottom)
            questions_text, answers_text = self._split_questions_and_answers_sections(exam_text)

            self.raw_text_preview = ("=== QUESTIONS (TOP PART) ===\n" + questions_text[:1200] + ("\n\n=== ANSWERS KEY (BOTTOM PART) ===\n" + answers_text[:800] if answers_text else "")).replace('\x00', '')

            # 3. Build Answers Dictionary: {1: '...', 2: '...', ...}
            answers_dict = self._parse_answers_dict(answers_text)

            # 4. Clean document introductory headers before question blocks
            clean_q_text = re.sub(r'^(?:WRITTEN EXAM|Sample Examination.*?|Instructions:.*?)\n+', '', questions_text, flags=re.IGNORECASE).strip()

            # 5. Split Questions into distinct numbered blocks
            question_blocks = re.split(r'\n(?=(?:Q(?:uestion)?\s*\d+[\.\:\)]|\[?\d+\]?[\.\)]\s+))', clean_q_text, flags=re.IGNORECASE)
            
            created_questions = []
            current_sec = None
            next_sec = None
            seq_counter = 1
            seen_q_nums = set()

            for block in question_blocks:
                block = block.strip()
                if not block or len(block) < 4:
                    continue

                if next_sec:
                    current_sec = next_sec
                    next_sec = None

                # Check if section header at top of block
                top_line = block.split('\n')[0].strip()
                top_sec = self._parse_section_header_type(top_line)
                if top_sec:
                    current_sec = top_sec
                    block = re.sub(r'^(?:.*?\n)?(?:Part\s+[IVXLCDM\d]+|Section\s+[A-Z\d]+)\s*[\–\-\:]\s*.*?\n', '', block, flags=re.IGNORECASE).strip()

                # Check if trailing section header at bottom of block (belongs to next question)
                trailing_sec_match = re.search(r'\n\s*((?:Part\s+[IVXLCDM\d]+|Section\s+[A-Z\d]+)\s*[\–\-\:]\s*.*)$', block, flags=re.IGNORECASE)
                if trailing_sec_match:
                    next_sec = self._parse_section_header_type(trailing_sec_match.group(1))
                    block = block[:trailing_sec_match.start()].strip()

                # Extract Question Number & Content
                q_num_match = re.match(r'^(?:Q(?:uestion)?\s*(\d+)[\.\:\)]|\[?(\d+)\]?[\.\)]\s*)\s*(.*)', block, flags=re.IGNORECASE | re.DOTALL)
                if q_num_match:
                    q_number = int(q_num_match.group(1) or q_num_match.group(2))
                    rest = q_num_match.group(3).strip()
                else:
                    q_number = seq_counter
                    rest = block
                seq_counter += 1

                if q_number in seen_q_nums:
                    continue
                seen_q_nums.add(q_number)

                lines = [l.strip() for l in rest.split('\n') if l.strip()]
                if not lines:
                    continue

                stem_line = lines[0]
                options = []
                inline_answer_key = ""
                inline_rubric = ""
                explicit_type = current_sec
                stem_extra_lines = []

                # Process remaining lines inside this question block
                for l in lines[1:]:
                    type_match = re.search(r'Type\s*[:=]\s*(essay|mcq|true_false|true\s*/\s*false|fill_blank|blank|short_answer|short\s*answer)', l, re.IGNORECASE)
                    if type_match:
                        t = type_match.group(1).lower()
                        if 'true' in t:
                            explicit_type = 'true_false'
                        elif 'blank' in t:
                            explicit_type = 'fill_blank'
                        elif 'short' in t:
                            explicit_type = 'short_answer'
                        elif 'essay' in t:
                            explicit_type = 'essay'
                        elif 'mcq' in t:
                            explicit_type = 'mcq_single'
                        continue

                    # Check for inline Answer Key / Solution
                    ans_match = re.search(r'^(?:Answer|Ans|Key|Correct Answer|Solution)\s*[:=]\s*(.+)', l, re.IGNORECASE)
                    rubric_match = re.search(r'^(?:Rubric|Guideline|Criteria|Expected Points)\s*[:=]\s*(.+)', l, re.IGNORECASE)
                    opt_match = re.match(r'^([A-Ea-e])[\.\)]\s*(.+)', l)

                    if rubric_match:
                        inline_rubric = rubric_match.group(1).strip()
                    elif ans_match:
                        inline_answer_key = ans_match.group(1).strip()
                    elif opt_match:
                        opt_letter = opt_match.group(1).upper()
                        opt_text = opt_match.group(2).strip()
                        options.append((opt_letter, opt_text.replace('\x00', '')))
                    else:
                        if not options and not inline_answer_key:
                            stem_extra_lines.append(l)

                full_stem = stem_line
                if stem_extra_lines:
                    full_stem += " " + " ".join(stem_extra_lines)

                full_stem = full_stem.replace('\x00', '').strip()
                assigned_answer = (answers_dict.get(q_number, "") or inline_answer_key).replace('\x00', '').strip()

                # Determine Question Type:
                # 1. Section Header / Explicit Type
                # 2. MCQ: Options A, B, C...
                # 3. Fill in the Blank: Contains slots "[ ... ]" or "_____"
                # 4. True/False: Exactly 2 options (True/False) or True/False in stem
                # 5. Essay: Default
                q_type = explicit_type
                if not q_type:
                    if options:
                        q_type = "mcq_single"
                    elif "___" in full_stem or ("[" in full_stem and "]" in full_stem):
                        q_type = "fill_blank"
                    elif len(options) == 2 and any(o[1].strip().lower() in ['true', 'false'] for o in options):
                        q_type = "true_false"
                    else:
                        q_type = "essay"

                # Setup question dictionary
                q_vals = {
                    "name": full_stem,
                    "question_type": q_type,
                    "job_id": self.job_id.id,
                    "operating_unit_id": self.operating_unit_id.id if self.operating_unit_id else (self.env.user.employee_id.operating_unit_id.id if self.env.user.employee_id.operating_unit_id else False),
                    "department_id": self.department_id.id if self.department_id else False,
                    "competency_id": self.competency_id.id if self.competency_id else False,
                    "competency_pillar": self.competency_id.pillar if self.competency_id else False,
                    "difficulty": self.difficulty,
                    "marks": self.default_marks,
                    "rubric_guidelines": (inline_rubric or (assigned_answer if q_type in ["essay", "short_answer"] else "")).replace('\x00', ''),
                    "submission_file": self.file_data,
                    "submission_filename": self.file_name,
                    "submission_notes": _("Imported from: %s (Q#%d)") % (self.file_name or "exam_doc", q_number),
                    "state": "draft", # Staged into Question Review Queue
                }

                # Auto-fill accepted text answer for Fill-in-the-Blank & Short Answer
                if q_type == "fill_blank":
                    if assigned_answer:
                        clean_ans = re.sub(r'^[A-Ea-e][\.\)]\s*', '', assigned_answer).strip()
                        q_vals["correct_text_answer"] = clean_ans.replace('\x00', '')
                    elif "[" in full_stem and "]" in full_stem:
                        extracted_slot = full_stem.split("[")[1].split("]")[0].strip()
                        extracted_slot = re.sub(r'^(?:e\.g\.|ie\.|example)\s*', '', extracted_slot, flags=re.IGNORECASE).strip()
                        q_vals["correct_text_answer"] = extracted_slot.replace('\x00', '')
                elif q_type == "short_answer":
                    if assigned_answer:
                        q_vals["correct_text_answer"] = assigned_answer.replace('\x00', '')

                # Create master question record
                new_q = self.env["exam.question"].create(q_vals)

                # Process MCQ & True/False Choices with exact answer key mapping
                if q_type in ["mcq_single", "mcq_multiple", "true_false"]:
                    opt_records = []

                    if q_type == "true_false" and not options:
                        clean_tf_ans = assigned_answer.strip().lower()
                        is_true_correct = clean_tf_ans in ["true", "t", "a", "1", "yes"]
                        
                        opt_records.append({
                            "question_id": new_q.id,
                            "sequence": 1,
                            "option_text": "True",
                            "is_correct": is_true_correct,
                            "score_fraction": 1.0 if is_true_correct else 0.0,
                        })
                        opt_records.append({
                            "question_id": new_q.id,
                            "sequence": 2,
                            "option_text": "False",
                            "is_correct": not is_true_correct,
                            "score_fraction": 1.0 if not is_true_correct else 0.0,
                        })
                    else:
                        target_letters = set(re.findall(r'\b([A-Ea-e])\b', assigned_answer))
                        
                        matched_indices = []
                        for idx, (letter, opt_txt) in enumerate(options):
                            is_match = False
                            if letter in target_letters:
                                is_match = True
                            elif assigned_answer:
                                clean_assigned = assigned_answer.strip().lower()
                                clean_opt = opt_txt.strip().lower()
                                if clean_assigned == clean_opt or clean_assigned == letter.lower():
                                    is_match = True
                            if is_match:
                                matched_indices.append(idx)

                        if len(matched_indices) > 1:
                            new_q.question_type = "mcq_multiple"

                        fraction_per_correct = (1.0 / len(matched_indices)) if matched_indices else 1.0

                        for seq, (letter, opt_txt) in enumerate(options, start=1):
                            idx = seq - 1
                            is_corr = (idx in matched_indices) if matched_indices else (seq == 1 and not assigned_answer)
                            
                            opt_records.append({
                                "question_id": new_q.id,
                                "sequence": seq,
                                "option_text": opt_txt.replace('\x00', ''),
                                "is_correct": is_corr,
                                "score_fraction": fraction_per_correct if is_corr else 0.0,
                            })

                    if opt_records:
                        self.env["exam.question.option"].create(opt_records)

                created_questions.append(new_q.id)

            self.imported_count = len(created_questions)
            if not created_questions:
                raise UserError(_("No questions could be parsed from the uploaded document. Please ensure questions are numbered (1., 2., 3...)."))

            return {
                "name": _("Extracted Exam Questions (%d) - Review Queue") % len(created_questions),
                "type": "ir.actions.act_window",
                "res_model": "exam.question",
                "view_mode": "list,form",
                "domain": [("id", "in", created_questions)],
                "context": {"search_default_filter_draft": 1},
            }

        except UserError:
            raise
        except Exception as e:
            raise UserError(_("Failed to parse and extract document: %s") % str(e))

    def action_parse_and_approve(self):
        """
        Parses uploaded document, aligns answers, creates questions, and IMMEDIATELY APPROVES ALL
        into the active Question Bank in one single click.
        """
        res = self.action_parse_and_import()
        if res and isinstance(res, dict) and "domain" in res:
            q_ids = res["domain"][0][2]
            questions = self.env["exam.question"].browse(q_ids)
            questions.action_approve()
            return {
                "name": _("Approved Question Bank (%d Questions Added)") % len(questions),
                "type": "ir.actions.act_window",
                "res_model": "exam.question",
                "view_mode": "list,form",
                "domain": [("id", "in", q_ids)],
                "context": {"search_default_filter_approved": 1},
            }
        return res

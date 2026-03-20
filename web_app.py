# -*- coding: utf-8 -*-
"""
Flask Web Application for Compliance Checklist Automation
COMPLETE INTEGRATED VERSION with Smart Extraction Logic
"""

import os
import re
import json
import shutil
import time
import uuid
import traceback
import difflib
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
import datetime as _dt
import random

from flask import Flask, render_template, request, jsonify, send_file, session
from flask_cors import CORS
from werkzeug.utils import secure_filename
from werkzeug.exceptions import HTTPException
import zipfile

# ===== Optional imports (graceful degradation) =====
try:
    import pdfplumber
except Exception:
    pdfplumber = None

try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None

try:
    from PIL import Image, ImageFile, ImageOps, ImageEnhance, ImageFilter
    ImageFile.LOAD_TRUNCATED_IMAGES = True
    try:
        Image.MAX_IMAGE_PIXELS = 250_000_000
    except Exception:
        pass
except Exception:
    Image = None
    ImageOps = None
    ImageEnhance = None
    ImageFilter = None

try:
    import pytesseract
    if os.path.exists(r"C:\Program Files\Tesseract-OCR\tesseract.exe"):
        pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    elif os.path.exists("/usr/bin/tesseract"):
        pytesseract.pytesseract.tesseract_cmd = "/usr/bin/tesseract"
except Exception:
    pytesseract = None

try:
    from tenacity import retry, stop_after_attempt, wait_exponential
except Exception:
    class MockRetry:
        def __init__(self, *args, **kwargs):
            pass
        def __call__(self, func):
            return func
    retry = MockRetry
    stop_after_attempt = lambda x: None
    wait_exponential = lambda **kwargs: None

try:
    from google import genai
except Exception:
    genai = None

try:
    import docx
    from docx.document import Document as _DocxDocument
except Exception as e:
    raise SystemExit("Missing dependency: python-docx. Install with: pip install python-docx") from e

try:
    from dateutil import parser as dateparser
except Exception:
    dateparser = None

# ===== Flask App Configuration =====
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'change-this-secret-key-in-production')
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB max upload

# ===== Always-JSON Error Handling (prevents HTML error pages) =====
DEBUG_ERRORS = os.getenv("DEBUG_ERRORS", "0").strip() == "1"

def _json_error(message: str, code: str = "ERROR", status: int = 400, details: Optional[dict] = None):
    payload = {
        'success': False,
        'error': {'code': code, 'message': message},
    }
    if DEBUG_ERRORS and details:
        payload['error']['details'] = details
    return jsonify(payload), status

@app.errorhandler(HTTPException)
def _handle_http_error(e: HTTPException):
    return _json_error(e.description, f"HTTP_{e.code}", e.code)

@app.errorhandler(Exception)
def _handle_unexpected_error(e: Exception):
    app.logger.exception("Unhandled error")
    details = {'type': type(e).__name__, 'trace': traceback.format_exc()}
    return _json_error("Request failed", "SERVER_ERROR", 500, details=details)

CORS(app)

# ── NextStep Auth ─────────────────────────────────────────────────────────────
import os as _os

def _get_ns_token(req):
    return (req.headers.get("X-NextStep-Token")
            or req.cookies.get("ns_token")
            or req.args.get("ns_token") or "")

def _get_ctx():
    """Returns user context dict or None. Used in every route."""
    token = _get_ns_token(request)
    if not token:
        return None
    try:
        import db
        return db.validate_user_token(token)
    except Exception as e:
        app.logger.warning("[Auth] %s", e)
        return None

def _require_auth():
    """Call at start of each route. Returns ctx dict or aborts 401."""
    from flask import abort
    ctx = _get_ctx()
    if not ctx:
        abort(401, "Not authenticated. Please log in at nextstep.co.uk")
    return ctx

# ===== Folder Configuration =====
STORAGE_ROOT   = Path('/tmp/nextstep')
TEMPLATE_FOLDER = Path('templates_docx')
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'docx', 'txt'}
STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
TEMPLATE_FOLDER.mkdir(exist_ok=True)

# Dynamic per-session paths — set in each request using tenant/user identity
def _upload_folder(tenant_id, user_id, session_id):
    p = STORAGE_ROOT / str(tenant_id) / str(user_id) / 'uploads' / session_id
    p.mkdir(parents=True, exist_ok=True)
    return p

def _output_folder(tenant_id, user_id, session_id):
    p = STORAGE_ROOT / str(tenant_id) / str(user_id) / 'outputs' / session_id
    p.mkdir(parents=True, exist_ok=True)
    return p

# Legacy fallback paths (used by cleanup only)
UPLOAD_FOLDER = STORAGE_ROOT / 'legacy_uploads'
OUTPUT_FOLDER = STORAGE_ROOT / 'legacy_outputs'

# ===== Gemini Configuration =====
GEMINI_MODEL_FAST = os.getenv("GEMINI_MODEL_FAST", "gemini-2.0-flash-001")
GEMINI_MODEL_STRONG = os.getenv("GEMINI_MODEL_STRONG", "gemini-2.5-pro")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
AI_CONF_THRESHOLD = float(os.getenv("AI_CONF_THRESHOLD", "0.65"))

# Initialize Gemini client
gemini_client = None
if genai and GEMINI_API_KEY:
    try:
        gemini_client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        print(f"Failed to initialize Gemini: {e}")

# ===== Constants =====
DOCUMENT_FOLDERS = [
    "APPLICATION FORM",
    "CV",
    "DBS",
    "NMC",
    "NI",
    "POA",
    "PASSPORT",
    "RTW",
    "TRAININGS"
]

CHECKLIST_TEMPLATES = [
    "EXEMPLAR PROFILE",
    "HC-One Profile",
    "HEALTHCARE HOMES PROFILE",
    "Horizon Care PROFILE",
    "IRIS PROFILE",
    "LC Profile",
    "MHA PROFILE",
    "neuven new"
]

STANDARD_FIELDS = [
    "Candidate Name", "Title", "Forename(s)", "Surname", "Email",
    "Address", "Phone", "DOB", "Nationality", "NI Number",
    "Role", "NMC PIN", "DBS Number", "DBS Issue Date",
    "DBS Last Checked Date", "Training Date", "Training Expiry Date",
    "RTW Status", "Visa Expiry Date", "Visa Type", "Restriction", "Share Code"
]

# Field extraction priority mapping
FIELD_PRIORITY = {
    "Candidate Name": ["DBS", "APPLICATION FORM", "CV", "PASSPORT"],
    "Title": ["APPLICATION FORM"],
    "Forename(s)": ["DBS", "APPLICATION FORM", "CV", "PASSPORT"],
    "Surname": ["DBS", "APPLICATION FORM", "CV", "PASSPORT"],
    "Email": ["APPLICATION FORM", "CV"],
    "Phone": ["APPLICATION FORM", "CV"],
    "DOB": ["DBS", "APPLICATION FORM", "PASSPORT"],
    "Address": ["POA", "APPLICATION FORM"],
    "Nationality": ["PASSPORT", "APPLICATION FORM"],
    "NI Number": ["NI", "APPLICATION FORM"],
    "Role": ["AUTO"],  # Special: NMC folder check
    "NMC PIN": ["NMC"],
    "DBS Number": ["DBS"],
    "DBS Issue Date": ["DBS"],
    "DBS Last Checked Date": ["DBS"],
    "Training Date": ["TRAININGS"],  # Special: earliest in 12 months
    "Training Expiry Date": ["CALCULATED"],  # Training Date + 12 months
    "RTW Status": ["RTW"],
    "Visa Expiry Date": ["RTW"],
    "Visa Type": ["RTW"],
    "Restriction": ["RTW"],
    "Share Code": ["RTW"]
}

SENSITIVE_FIELDS = {"NI Number"}
# --- Sensitive-field validation ---
NI_REGEX = re.compile(
    r"\b(?!BG)(?!GB)(?!NK)(?!KN)(?!TN)(?!NT)(?!ZZ)"
    r"[A-CEGHJ-PR-TW-Z]{2}\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-D]\b",
    re.IGNORECASE
)

def validate_ni(value: str) -> str:
    v = (value or "").strip()
    if not v:
        return ""
    v_up = re.sub(r"\s+", " ", v).upper()
    v_nospace = v_up.replace(" ", "")
    if NI_REGEX.search(v_up) or NI_REGEX.search(v_nospace):
        return v_up
    return ""

def extract_print_date_from_text(text: str) -> str:
    """Extract Print Date from DBS check style text and treat as issue date."""
    if not text:
        return ""
    t = text.lower()

    # Common labels: print date / date printed / printed on
    patterns = [
        r"print\s*date\s*[:\-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        r"date\s*printed\s*[:\-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        r"printed\s*on\s*[:\-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
    ]
    for pat in patterns:
        m = re.search(pat, t, flags=re.I)
        if m:
            ds = m.group(1)
            try:
                if dateparser:
                    d = dateparser.parse(ds, dayfirst=True)
                    if d:
                        return d.date().strftime("%d/%m/%Y")
            except Exception:
                return ds

    # Fallback: find a date near the word 'print'
    idx = t.find('print')
    if idx != -1:
        window = t[max(0, idx-200): idx+200]
        m = re.search(r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", window)
        if m:
            ds = m.group(1)
            try:
                if dateparser:
                    d = dateparser.parse(ds, dayfirst=True)
                    if d:
                        return d.date().strftime("%d/%m/%Y")
            except Exception:
                return ds
    return ""

# --- Session cleanup (privacy + storage) ---
CLEANUP_AFTER_HOURS = int(os.getenv("CLEANUP_AFTER_HOURS", "24"))

CLEANUP_AFTER_HOURS = 2  # shorter cleanup for /tmp

def cleanup_old_sessions() -> None:
    """Delete upload/output session folders older than CLEANUP_AFTER_HOURS."""
    cutoff = time.time() - (CLEANUP_AFTER_HOURS * 3600)

    def _cleanup_root(root: Path):
        if not root.exists():
            return
        for p in root.iterdir():
            try:
                if not p.is_dir():
                    continue
                mtime = p.stat().st_mtime
                if mtime < cutoff:
                    shutil.rmtree(p, ignore_errors=True)
            except Exception:
                continue

    _cleanup_root(UPLOAD_FOLDER)
    _cleanup_root(OUTPUT_FOLDER)

DEFAULT_PHONE = "0121 827 3666"

@dataclass
class FieldValue:
    value: str
    source: str
    confidence: float = 1.0
    ai_filled: bool = False

# ===== CORE EXTRACTION FUNCTIONS =====

def extract_text_pdf(pdf_path: Path) -> str:
    """Extract text from PDF using pdfplumber"""
    if not pdfplumber:
        return ""
    
    try:
        text_parts = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                text_parts.append(page_text)
        return "\n".join(text_parts)
    except Exception as e:
        print(f"PDF extraction error for {pdf_path}: {e}")
        return ""

def _ocr_score(text: str) -> int:
    """Heuristic score for OCR output quality."""
    if not text:
        return 0
    # Prefer longer, alphanumeric-heavy text; penalize too many symbols
    alnum = sum(ch.isalnum() for ch in text)
    bad = sum(ch in "|~`^_" for ch in text)
    return len(text) + 2 * alnum - 5 * bad

def _preprocess_for_ocr(img: 'Image.Image') -> 'Image.Image':
    """Lightweight preprocessing to improve OCR accuracy."""
    try:
        img = ImageOps.exif_transpose(img)  # fix orientation if present
    except Exception:
        pass

    # Convert to grayscale
    try:
        img = img.convert('L')
    except Exception:
        pass

    # Upscale small images (OCR works better)
    try:
        w, h = img.size
        if max(w, h) < 1400:
            scale = 1400 / max(w, h)
            img = img.resize((int(w * scale), int(h * scale)))
    except Exception:
        pass

    # Increase contrast and sharpen
    try:
        if ImageEnhance:
            img = ImageEnhance.Contrast(img).enhance(2.2)
            img = ImageEnhance.Sharpness(img).enhance(2.0)
    except Exception:
        pass

    # Mild denoise
    try:
        img = img.filter(ImageFilter.MedianFilter(size=3))
    except Exception:
        pass

    return img

def _ocr_image_best(img: 'Image.Image') -> str:
    """Run OCR with a few settings/orientations and keep best output."""
    if not pytesseract:
        return ""

    img = _preprocess_for_ocr(img)

    # Try common rotations (phone photos)
    rotations = [0, 90, 180, 270]
    psm_modes = [6, 11, 4]  # block text, sparse text, columns

    best_text = ""
    best_score = 0

    for rot in rotations:
        try:
            im2 = img.rotate(rot, expand=True) if rot else img
        except Exception:
            im2 = img

        for psm in psm_modes:
            cfg = f"--oem 3 --psm {psm}"
            try:
                t = pytesseract.image_to_string(im2, lang='eng', config=cfg) or ""
            except Exception:
                t = ""
            score = _ocr_score(t)
            if score > best_score:
                best_score = score
                best_text = t

    return (best_text or "").strip()

def extract_text_image(img_path: Path) -> str:
    """Extract text from image using OCR (enhanced)."""
    if not pytesseract or not Image:
        return ""

    try:
        ImageFile.LOAD_TRUNCATED_IMAGES = True
        img = Image.open(img_path)
        return _ocr_image_best(img)
    except Exception as e:
        print(f"Image OCR error for {img_path}: {e}")
        return ""


def extract_text_docx(docx_path: Path) -> str:
    """Extract text from DOCX"""
    try:
        doc = docx.Document(docx_path)
        text_parts = []
        
        for para in doc.paragraphs:
            text_parts.append(para.text)
        
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    text_parts.append(cell.text)
        
        return "\n".join(text_parts)
    except Exception as e:
        print(f"DOCX extraction error for {docx_path}: {e}")
        return ""

def gather_folder_text(folder: Path) -> Tuple[str, List[str], List[Path]]:
    """Gather all text from a specific folder.

    Returns:
      - combined text (with file markers),
      - processed file names,
      - processed file paths (for optional AI-vision fallback).
    """
    all_text: List[str] = []
    processed_files: List[str] = []
    processed_paths: List[Path] = []

    if not folder.exists():
        return "", [], []

    for file_path in folder.iterdir():
        if not file_path.is_file():
            continue

        ext = file_path.suffix.lower()
        extracted_text = ""

        try:
            # Always track supported files for AI file-attachment fallback,
            # even if OCR/text-layer extraction returns empty text.
            if ext in {'.pdf', '.png', '.jpg', '.jpeg', '.docx', '.txt'}:
                processed_files.append(file_path.name)
                processed_paths.append(file_path)

            if ext == '.pdf':
                extracted_text = extract_text_pdf(file_path)
            elif ext in {'.png', '.jpg', '.jpeg'}:
                extracted_text = extract_text_image(file_path)
            elif ext == '.docx':
                extracted_text = extract_text_docx(file_path)
            elif ext == '.txt':
                # Be forgiving with encodings.
                extracted_text = file_path.read_text(encoding='utf-8', errors='ignore')

            if extracted_text:
                all_text.append(f"\n=== {file_path.name} ===\n{extracted_text}")

        except Exception as e:
            print(f"Error processing {file_path}: {e}")

    return "\n".join(all_text), processed_files, processed_paths


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
def _gemini_generate(model: str, contents):
    """Small wrapper for Gemini calls (keeps retries consistent)."""
    return gemini_client.models.generate_content(model=model, contents=contents)

def _parse_json_response(response_text: str) -> Dict[str, Any]:
    """Parse JSON safely from Gemini text output."""
    if not response_text:
        return {}
    txt = response_text.strip()

    # Strip fenced blocks if present
    if txt.startswith('```'):
        txt = re.sub(r'^```(?:json)?\s*', '', txt, flags=re.I)
        txt = re.sub(r'\s*```\s*$', '', txt)

    # Quick repair: extract first {...} if model added extra text
    if not txt.startswith('{'):
        m = re.search(r'\{[\s\S]*\}', txt)
        if m:
            txt = m.group(0)

    try:
        return json.loads(txt)
    except Exception:
        return {}

def ai_extract_from_text(text: str, fields_to_extract: List[str]) -> Dict[str, FieldValue]:
    """Extract specific fields from text using Gemini AI.

    Hybrid model strategy (silent):
      - Primary: GEMINI_MODEL_FAST
      - Fallback: GEMINI_MODEL_STRONG
    """
    if not gemini_client or not text.strip():
        return {}

    prompt = f"""Extract the following information from the documents below. Return ONLY a JSON object with these exact fields:

{json.dumps(fields_to_extract, indent=2)}

Rules:
- Return ONLY valid JSON, nothing else
- Use exact field names as listed above
- If a field is not found, use empty string ""
- For dates, use DD/MM/YYYY format
- For NI Number, use format: XX 12 34 56 A
- Be accurate and extract exactly what you see

Documents:
{text[:15000]}

Return JSON only:"""

    models = [GEMINI_MODEL_FAST, GEMINI_MODEL_STRONG]

    last_err = None
    for model in models:
        try:
            resp = _gemini_generate(model=model, contents=prompt)
            data = _parse_json_response(getattr(resp, 'text', '') or '')
            if not isinstance(data, dict):
                data = {}

            result: Dict[str, FieldValue] = {}
            for field in fields_to_extract:
                value = data.get(field, "")
                if value and str(value).strip():
                    result[field] = FieldValue(
                        value=str(value).strip(),
                        source=f"AI (Gemini: {model})",
                        confidence=0.85,
                        ai_filled=True
                    )
            return result
        except Exception as e:
            last_err = e
            continue

    if last_err:
        print(f"AI extraction error (all models failed): {last_err}")
    return {}

def ai_extract_from_files(file_paths: List[Path], fields_to_extract: List[str]) -> Dict[str, FieldValue]:
    """AI vision-style fallback: attach files when OCR/text is weak.

    If the installed google-genai SDK doesn't support file parts in this environment,
    this function safely returns {}.
    """
    if not gemini_client or not file_paths:
        return {}

    try:
        from google.genai import types  # type: ignore
    except Exception:
        return {}

    # Attach a small number of files to control cost
    limited = file_paths[:4]
    parts = []
    for p in limited:
        try:
            b = p.read_bytes()
            mime = "application/octet-stream"
            ext = p.suffix.lower()
            if ext in ['.jpg', '.jpeg']:
                mime = 'image/jpeg'
            elif ext == '.png':
                mime = 'image/png'
            elif ext == '.pdf':
                mime = 'application/pdf'
            elif ext == '.docx':
                mime = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            parts.append(types.Part.from_bytes(data=b, mime_type=mime))
        except Exception:
            continue

    if not parts:
        return {}

    prompt = f"""Extract the following information from the attached documents. Return ONLY a JSON object with these exact fields:

{json.dumps(fields_to_extract, indent=2)}

Rules:
- Return ONLY valid JSON, nothing else
- Use exact field names as listed above
- If a field is not found, use empty string ""
- For dates, use DD/MM/YYYY format
- Be accurate and extract exactly what you see

Return JSON only:"""

    models = [GEMINI_MODEL_FAST, GEMINI_MODEL_STRONG]
    last_err = None
    for model in models:
        try:
            resp = _gemini_generate(model=model, contents=[prompt, *parts])
            data = _parse_json_response(getattr(resp, 'text', '') or '')
            if not isinstance(data, dict):
                data = {}

            result: Dict[str, FieldValue] = {}
            for field in fields_to_extract:
                value = data.get(field, "")
                if value and str(value).strip():
                    result[field] = FieldValue(
                        value=str(value).strip(),
                        source=f"AI (Gemini attach: {model})",
                        confidence=0.85,
                        ai_filled=True
                    )
            return result
        except Exception as e:
            last_err = e
            continue

    if last_err:
        print(f"AI file-attach extraction error: {last_err}")
    return {}


# ===== Gemini Vision Fallback (PDF->Images via PyMuPDF, no OCR) =====

def pdf_to_images_bytes(pdf_path: Path, max_pages: int = 5) -> List[bytes]:
    """Convert PDF pages to PNG bytes using PyMuPDF. Works for scanned PDFs."""
    if not fitz:
        return []
    images: List[bytes] = []
    try:
        doc = fitz.open(str(pdf_path))
        pages_to_render = min(doc.page_count, max_pages)
        mat = fitz.Matrix(2, 2)
        for i in range(pages_to_render):
            page = doc.load_page(i)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            images.append(pix.tobytes("png"))
        doc.close()
    except Exception as e:
        print(f"PyMuPDF render error for {pdf_path}: {e}")
    return images

def ai_extract_from_vision_files(file_paths: List[Path], fields_to_extract: List[str]) -> Dict[str, FieldValue]:
    """Vision fallback: attach images (and rendered PDF pages) to Gemini.

    - Keeps your label-based rule (no guessing; if unsure -> blank).
    - Uses same hybrid model strategy (FAST then STRONG).
    - Fills ONLY provided fields.
    """
    if not gemini_client or not file_paths:
        return {}

    try:
        from google.genai import types  # type: ignore
    except Exception:
        return {}

    # Build image parts (PDF->images; images direct). Cap to control cost.
    parts: List[Any] = []
    for p in file_paths:
        ext = p.suffix.lower()
        try:
            if ext in ['.jpg', '.jpeg', '.png']:
                b = p.read_bytes()
                if not b:
                    continue
                mime = 'image/jpeg' if ext in ['.jpg', '.jpeg'] else 'image/png'
                parts.append(types.Part.from_bytes(data=b, mime_type=mime))
            elif ext == '.pdf':
                for img in pdf_to_images_bytes(p, max_pages=5):
                    parts.append(types.Part.from_bytes(data=img, mime_type='image/png'))
        except Exception:
            continue
        if len(parts) >= 12:
            break

    if not parts:
        return {}

    # Label synonyms (still label-anchored, not regex guessing)
    label_aliases = {
        "Candidate Name": ["Name", "Full Name", "Applicant Name", "Candidate"],
        "DOB": ["DOB", "Date of Birth", "Birth Date"],
        "DBS Number": ["DBS Number", "DBS No", "Certificate Number", "Certificate No"],
        "DBS Issue Date": ["DBS Issue Date", "Issue Date", "Date of Issue", "Print Date", "Printed on", "Date Printed"],
        "NI Number": ["NI Number", "National Insurance Number", "NINO"],
        "NMC PIN": ["NMC PIN", "PIN", "NMC Pin Number"],
        "Share Code": ["Share Code"],
        "Visa Expiry Date": ["Visa Expiry Date", "Expiry Date"],
        "Visa Type": ["Visa Type", "Type of visa"],
        "Restriction": ["Restriction"],
        "RTW Status": ["Right to Work", "RTW Status"],
        "Address": ["Address", "Home Address"],
        "Phone": ["Phone", "Mobile", "Telephone"],
        "Email": ["Email", "E-mail"],
        "Nationality": ["Nationality"],
        "Surname": ["Surname", "Last Name", "Family Name"],
        "Forename(s)": ["Forename", "First Name", "Given Name"],
    }
    alias_lines = []
    for f in fields_to_extract:
        alias_lines.append(f"- {f}: labels may appear as {', '.join([repr(a) for a in label_aliases.get(f, [])])}")

    prompt = f"""Extract the following information from the attached document images. Return ONLY a JSON object with these exact fields:

{json.dumps(fields_to_extract, indent=2)}

RULES:
- Label-based extraction only: extract a value ONLY if it is clearly present near an explicit label (or a label synonym listed below).
- Do NOT guess or infer. If unsure or not visible, return empty string "".
- Do NOT invent sensitive identifiers (NI/DBS/NMC/Passport/Share Code). If not clearly visible, return "".
- Candidate Name must be the PERSON/APPLICANT name, not employer/company.

Label synonyms you may treat as equivalent:
{chr(10).join(alias_lines)}

DBS rules:
- "Printed on"/"Print Date" is the DBS Issue Date.
- "Certificate Number" is the DBS Number.

Return JSON only."""

    models = [GEMINI_MODEL_FAST, GEMINI_MODEL_STRONG]
    last_err = None
    for model in models:
        try:
            # Prefer Content(role='user', parts=[text, images...]) when available
            try:
                contents = [types.Content(role="user", parts=[types.Part.from_text(prompt)] + parts)]
            except Exception:
                contents = [prompt, *parts]
            resp = _gemini_generate(model=model, contents=contents)
            data = _parse_json_response(getattr(resp, 'text', '') or '')
            if not isinstance(data, dict):
                data = {}

            result: Dict[str, FieldValue] = {}
            for field in fields_to_extract:
                value = data.get(field, "")
                if value and str(value).strip():
                    result[field] = FieldValue(
                        value=str(value).strip(),
                        source=f"AI (Gemini Vision: {model})",
                        confidence=0.85,
                        ai_filled=True
                    )
            return result
        except Exception as e:
            last_err = e
            continue

    if last_err:
        print(f"AI vision extraction error: {last_err}")
    return {}

def detect_role_from_nmc(nmc_folder: Path) -> str:
    """Detect role based on NMC folder contents"""
    if nmc_folder.exists() and any(nmc_folder.iterdir()):
        return "RGN"
    return "HCA"

def extract_training_date(trainings_folder: Path) -> Tuple[str, str, float]:
    """Extract training date.

    Rule:
    - Find the earliest date within last 12 months across training documents.
    - If none found, generate a random training date (last 3 months).
    Also returns the exact source file that contained the chosen date.
    """
    if not trainings_folder.exists():
        return generate_random_training_date()

    # Parse per-file so we can report correct source
    date_pattern = re.compile(r'\b(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b')
    today = _dt.date.today()
    twelve_months_ago = today - _dt.timedelta(days=365)

    best_date: Optional[_dt.date] = None
    best_file: Optional[str] = None

    _, _, paths = gather_folder_text(trainings_folder)

    for p in paths:
        ext = p.suffix.lower()
        if ext == '.pdf':
            t = extract_text_pdf(p)
        elif ext in ['.png', '.jpg', '.jpeg']:
            t = extract_text_image(p)
        elif ext == '.docx':
            t = extract_text_docx(p)
        else:
            t = ''

        if not t:
            continue

        for date_str in date_pattern.findall(t):
            try:
                if not dateparser:
                    continue
                parsed = dateparser.parse(date_str, dayfirst=True)
                if not parsed:
                    continue
                d = parsed.date()
                if twelve_months_ago <= d <= today:
                    if best_date is None or d < best_date:
                        best_date = d
                        best_file = p.name
            except Exception:
                continue

    if best_date:
        src = f"TRAININGS/{best_file}" if best_file else "TRAININGS/document"
        return best_date.strftime("%d/%m/%Y"), src, 0.90

    return generate_random_training_date()


def generate_random_training_date() -> Tuple[str, str, float]:
    """Generate random training date from last 3 months"""
    today = _dt.date.today()
    days_ago = random.randint(1, 90)
    random_date = today - _dt.timedelta(days=days_ago)
    return random_date.strftime("%d/%m/%Y"), "Random (no valid training in last 12 months)", 0.50

def calculate_training_expiry(training_date: str) -> str:
    """Calculate training expiry as training date + 12 months"""
    try:
        if dateparser:
            parsed = dateparser.parse(training_date, dayfirst=True)
            if parsed:
                expiry = parsed.date() + _dt.timedelta(days=365)
                return expiry.strftime("%d/%m/%Y")
    except:
        pass
    return ""

def check_uk_passport(rtw_folder: Path, nationality: str) -> bool:
    """Check if UK Passport detected in RTW folder or nationality"""
    if "british" in nationality.lower():
        return True
    
    if rtw_folder.exists():
        text, _, _ = gather_folder_text(rtw_folder)
        if "uk passport" in text.lower() or "british passport" in text.lower():
            return True
    
    return False

def auto_derive_names(extracted: Dict[str, FieldValue]) -> Dict[str, FieldValue]:
    """Auto-derive Candidate Name from Forename + Surname and vice versa"""
    candidate_name = extracted.get("Candidate Name", FieldValue("", ""))
    forename = extracted.get("Forename(s)", FieldValue("", ""))
    surname = extracted.get("Surname", FieldValue("", ""))
    
    # If we have Candidate Name but not Forename/Surname
    if candidate_name.value and (not forename.value or not surname.value):
        parts = candidate_name.value.split()
        if len(parts) >= 2:
            if not surname.value:
                extracted["Surname"] = FieldValue(
                    parts[-1],
                    f"Derived from Candidate Name ({candidate_name.source})",
                    candidate_name.confidence * 0.9,
                    True
                )
            if not forename.value:
                extracted["Forename(s)"] = FieldValue(
                    " ".join(parts[:-1]),
                    f"Derived from Candidate Name ({candidate_name.source})",
                    candidate_name.confidence * 0.9,
                    True
                )
    
    # If we have Forename + Surname but not Candidate Name
    elif forename.value and surname.value and not candidate_name.value:
        extracted["Candidate Name"] = FieldValue(
            f"{forename.value} {surname.value}",
            f"Derived from Forename + Surname",
            min(forename.confidence, surname.confidence) * 0.95,
            True
        )
    
    return extracted

def smart_extract_with_priority(session_folder: Path) -> Dict[str, FieldValue]:
    """Extract fields with folder priority logic (with safe fallbacks)."""
    extracted: Dict[str, FieldValue] = {}
    folder_texts: Dict[str, str] = {}
    folder_files: Dict[str, List[str]] = {}
    folder_paths: Dict[str, List[Path]] = {}

    # Gather text + assets from each folder
    for folder_name in DOCUMENT_FOLDERS:
        folder_path = session_folder / folder_name
        text_blob, files, paths = gather_folder_text(folder_path)
        folder_texts[folder_name] = text_blob
        folder_files[folder_name] = files
        folder_paths[folder_name] = paths

    # Special: Role detection from NMC folder
    role = detect_role_from_nmc(session_folder / "NMC")
    extracted["Role"] = FieldValue(role, "AUTO (NMC folder detection)", 1.0, False)

    # Special: Training date logic
    training_date, training_source, training_conf = extract_training_date(session_folder / "TRAININGS")
    extracted["Training Date"] = FieldValue(training_date, training_source, training_conf, True)

    # Special: Training expiry = Training date + 12 months
    training_expiry = calculate_training_expiry(training_date)
    if training_expiry:
        extracted["Training Expiry Date"] = FieldValue(
            training_expiry,
            "Calculated (Training Date + 12 months)",
            training_conf,
            True
        )

    # Extract fields based on priority
    for field, priority_folders in FIELD_PRIORITY.items():
        if field in ["Role", "Training Date", "Training Expiry Date"]:
            continue  # Already handled

        # NMC PIN only relevant if role is RGN
        if field == "NMC PIN":
            if role == "RGN" and folder_texts.get("NMC"):
                ai_result = ai_extract_from_text(folder_texts["NMC"], ["NMC PIN"])
                if "NMC PIN" in ai_result:
                    extracted["NMC PIN"] = ai_result["NMC PIN"]
                    if folder_files.get('NMC'):
                        extracted["NMC PIN"].source = f"NMC/{folder_files.get('NMC')[0]}"
            else:
                extracted["NMC PIN"] = FieldValue("NA", "Role is HCA", 1.0, False)
            continue

        # Try folders in priority order
        for folder in priority_folders:
            if folder in ("AUTO", "CALCULATED"):
                continue

            # 1) Text-based AI extraction when we have text
            if folder_texts.get(folder):
                ai_result = ai_extract_from_text(folder_texts[folder], [field])
                if field in ai_result:
                    extracted[field] = ai_result[field]
                    if folder_files.get(folder):
                        extracted[field].source = f"{folder}/{folder_files.get(folder)[0]}"
                    else:
                        extracted[field].source = f"{folder}"
                    break

            # 2) Vision-style fallback if folder has files but text is weak/empty
            if folder_paths.get(folder):
                # only attempt if not already extracted and we have almost no text
                if (not folder_texts.get(folder)) or (len(folder_texts.get(folder) or "") < 80):
                    ai_result = ai_extract_from_files(folder_paths[folder], [field])
                    if field in ai_result:
                        extracted[field] = ai_result[field]
                        extracted[field].source = f"{folder} (attachment fallback)"
                        break

                    # 3) NEW: Gemini Vision fallback (PDF->images / image attachments) if still blank
                    vision_result = ai_extract_from_vision_files(folder_paths[folder], [field])
                    if field in vision_result:
                        extracted[field] = vision_result[field]
                        extracted[field].source = f"{folder} (vision fallback)"
                        break

    # DBS Issue Date: if not extracted from certificate image, use Print Date from DBS check PDF
    if not (extracted.get("DBS Issue Date") and extracted["DBS Issue Date"].value.strip()):
        dbs_text = folder_texts.get("DBS", "")
        issue = extract_print_date_from_text(dbs_text)
        if issue:
            extracted["DBS Issue Date"] = FieldValue(
                issue,
                "DBS (Print Date used as Issue Date)",
                0.80,
                True
            )

    # Auto-derive names
    extracted = auto_derive_names(extracted)

    # Check UK Passport for RTW fields
    nationality = extracted.get("Nationality", FieldValue("", "")).value
    is_uk_passport = check_uk_passport(session_folder / "RTW", nationality)

    if is_uk_passport:
        for f in ["RTW Status", "Visa Expiry Date", "Visa Type", "Restriction", "Share Code"]:
            extracted[f] = FieldValue("UK Passport", "UK Passport detected", 1.0, False)

    # Validate sensitive fields (never keep invented identifiers)
    for f in SENSITIVE_FIELDS:
        if f in extracted:
            if f == "NI Number":
                cleaned = validate_ni(extracted[f].value)
                if not cleaned:
                    extracted[f] = FieldValue("", "Blanked (invalid NI format)", 0.0, False)
                else:
                    extracted[f].value = cleaned

    return extracted


def replace_placeholders_in_paragraph(paragraph, replacements: Dict[str, str], fuzzy_cutoff: float = 0.75) -> bool:
    """Replace placeholders in a paragraph deterministically (run-safe), with fuzzy fallback."""
    original = paragraph.text or ""
    if not original:
        return False

    def _norm_key(k: str) -> str:
        k = (k or "").replace("’", "'")
        k = k.strip().lower()
        return re.sub(r"[^a-z0-9]+", "", k)

    norm_map = {_norm_key(k): (v or "") for k, v in replacements.items()}
    norm_keys = list(norm_map.keys())

    def _lookup(inner: str) -> Optional[str]:
        nk = _norm_key(inner)
        if nk in norm_map:
            return norm_map[nk]
        # aggressive fuzzy match (approved)
        if nk and norm_keys:
            best = difflib.get_close_matches(nk, norm_keys, n=1, cutoff=fuzzy_cutoff)
            if best:
                return norm_map.get(best[0])
        return None

    text = original.replace("{[", "{{")
    changed = False

    # handle nested placeholders like {{{{A}}/B}} style
    nested_re = re.compile(r"\{\{\{\{\s*([^{}]+?)\s*\}\}\s*/\s*[^{}]+?\s*\}\}\s*", re.I)

    def _nested_sub(m):
        inner = m.group(1)
        val = _lookup(inner)
        nonlocal changed
        changed = True
        return (val or "") if val is not None else ""

    if nested_re.search(text):
        text = nested_re.sub(_nested_sub, text)

    token_re = re.compile(r"\{\{([^{}]+)\}\}")
    for _ in range(5):
        made = False

        def _sub(m):
            inner = m.group(1)
            val = _lookup(inner)
            if val is None:
                return m.group(0)
            nonlocal made
            made = True
            return val

        new_text = token_re.sub(_sub, text)
        if new_text != text:
            text = new_text
        if not made:
            break
        changed = True

    if "{{" in text and "}}" in text:
        text2 = text.replace("{{", "").replace("}}", "")
        if text2 != text:
            text = text2
            changed = True

    if not changed:
        return False

    for r in paragraph.runs:
        r.text = ""
    if paragraph.runs:
        paragraph.runs[0].text = text
    else:
        paragraph.add_run(text)
    return True

def replace_placeholders_in_table(table, replacements: Dict[str, str]) -> int:
    changed = 0
    for row in table.rows:
        for cell in row.cells:
            for p in cell.paragraphs:
                if replace_placeholders_in_paragraph(p, replacements):
                    changed += 1
            for t in cell.tables:
                changed += replace_placeholders_in_table(t, replacements)
    return changed

def _find_unfilled_placeholders_docx(d: '_DocxDocument') -> List[str]:
    token_re = re.compile(r"\{\{[^{}]+\}\}")
    leftovers = set()

    def scan_paras(paras):
        for p in paras:
            for tok in token_re.findall(p.text or ""):
                leftovers.add(tok)

    scan_paras(d.paragraphs)

    def scan_table(table):
        for row in table.rows:
            for cell in row.cells:
                scan_paras(cell.paragraphs)
                for t in cell.tables:
                    scan_table(t)

    for t in d.tables:
        scan_table(t)

    try:
        for section in d.sections:
            scan_paras(section.header.paragraphs)
            for t in section.header.tables:
                scan_table(t)
            scan_paras(section.footer.paragraphs)
            for t in section.footer.tables:
                scan_table(t)
    except Exception:
        pass

    return sorted(leftovers)

def fill_docx_template(template_path: Path, output_path: Path, replacements: Dict[str, str]) -> Tuple[int, List[str]]:
    """Fill DOCX template by replacing placeholders robustly (run-safe + tables + header/footer)."""
    warnings: List[str] = []
    d = docx.Document(str(template_path))
    changed = 0

    for p in d.paragraphs:
        if replace_placeholders_in_paragraph(p, replacements):
            changed += 1
    for t in d.tables:
        changed += replace_placeholders_in_table(t, replacements)

    try:
        for section in d.sections:
            header = section.header
            for p in header.paragraphs:
                if replace_placeholders_in_paragraph(p, replacements):
                    changed += 1
            for t in header.tables:
                changed += replace_placeholders_in_table(t, replacements)

            footer = section.footer
            for p in footer.paragraphs:
                if replace_placeholders_in_paragraph(p, replacements):
                    changed += 1
            for t in footer.tables:
                changed += replace_placeholders_in_table(t, replacements)
    except Exception as e:
        warnings.append(f"Header/footer replace skipped: {e}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    d.save(str(output_path))

    # Unfilled placeholder report
    try:
        d2 = docx.Document(str(output_path))
        leftovers = _find_unfilled_placeholders_docx(d2)
        if leftovers:
            report = output_path.parent / "unfilled_placeholders.txt"
            with report.open('a', encoding='utf-8') as f:
                f.write(f"\n=== {output_path.name} ===\n")
                for tok in leftovers:
                    f.write(tok + "\n")
    except Exception as e:
        warnings.append(f"Unfilled placeholder scan skipped: {e}")

    return changed, warnings

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def list_templates() -> List[str]:
    """Return template names (stems) that actually exist in templates_docx."""
    try:
        return sorted([p.stem for p in TEMPLATE_FOLDER.glob("*.docx")])
    except Exception:
        return []

# ===== FLASK ROUTES =====

@app.route('/')
def index():
    # Auth check — redirect to login if not authenticated
    ctx = _get_ctx()
    if not ctx:
        return render_template('index.html',
                             folders=DOCUMENT_FOLDERS,
                             templates=list_templates(),
                             fields=STANDARD_FIELDS,
                             auth_required=True)
    return render_template('index.html',
                         folders=DOCUMENT_FOLDERS,
                         templates=list_templates(),
                         fields=STANDARD_FIELDS,
                         auth_required=False)

@app.route('/templates', methods=['GET'])
def templates_api():
    """Return templates present on the server."""
    _require_auth()
    return jsonify({'success': True, 'templates': list_templates()})


@app.route('/upload', methods=['POST'])
def upload_files():
    ctx = _require_auth()
    tenant_id = ctx['tenant_id']; user_id = ctx['user_id']
    try:
        cleanup_old_sessions()
        session_id = str(uuid.uuid4())
        session_folder = _upload_folder(tenant_id, user_id, session_id)
        
        upload_stats = {}
        
        for folder_name in DOCUMENT_FOLDERS:
            folder_path = session_folder / folder_name
            folder_path.mkdir(exist_ok=True)
            
            field_name = f'files_{folder_name.replace(" ", "_")}'
            files = request.files.getlist(field_name)
            
            count = 0
            for file in files[:5]:  # Max 5 files per folder
                if file and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    file.save(folder_path / filename)
                    count += 1
            
            upload_stats[folder_name] = count
        
        # Also handle template uploads
        template_files = request.files.getlist('template_files')
        template_count = 0
        for file in template_files:
            if file and file.filename.endswith('.docx'):
                filename = secure_filename(file.filename)
                file.save(TEMPLATE_FOLDER / filename)
                template_count += 1
        
        session['session_id'] = session_id
        session['tenant_id'] = tenant_id
        session['user_id']   = user_id

        return jsonify({
            'success': True,
            'session_id': session_id,
            'upload_stats': upload_stats,
            'template_count': template_count
        })
    
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/extract', methods=['POST'])
def extract_data():
    """Extract data using smart priority logic. Charges 1 token."""
    ctx = _require_auth()
    tenant_id = ctx['tenant_id']; user_id = ctx['user_id']
    try:
        cleanup_old_sessions()
        data = request.json
        session_id = data.get('session_id')

        if not session_id:
            return jsonify({'error': 'No session ID provided'}), 400

        # Token check before extraction
        try:
            import db
            tokens = db.get_tenant_tokens_remaining(tenant_id)
            if tokens == 0:
                return jsonify({'error': 'No tokens remaining. Please contact NextStep to top up.'}), 402
        except Exception as e:
            app.logger.warning("[Extract] Token check skipped: %s", e)

        session_folder = _upload_folder(tenant_id, user_id, session_id)

        if not session_folder.exists():
            return jsonify({'error': 'Session folder not found'}), 404
        
        print(f"Extracting with smart priority from: {session_folder}")
        
        extracted = smart_extract_with_priority(session_folder)
        
        # Convert to JSON-serializable format
        extracted_data = {}
        for field, field_value in extracted.items():
            extracted_data[field] = {
                'value': field_value.value,
                'source': field_value.source,
                'confidence': field_value.confidence
            }
        
        # Charge 1 token for extraction
        try:
            import db
            db_job_id = db.create_job_record(tenant_id=tenant_id, user_id=user_id, total_items=1)
            db.update_job_status(db_job_id=db_job_id, status='completed',
                                 successful_items=1, failed_items=0)
            db.record_usage(tenant_id=tenant_id, user_id=user_id,
                            db_job_id=db_job_id, successful_outputs=1)
        except Exception as e:
            app.logger.warning("[Extract] Token charge failed: %s", e)

        return jsonify({
            'success': True,
            'extracted_data': extracted_data
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/process', methods=['POST'])
def process_documents():
    """Generate filled checklist documents. Charges 1 token per template generated."""
    ctx = _require_auth()
    tenant_id = ctx['tenant_id']; user_id = ctx['user_id']
    try:
        cleanup_old_sessions()
        data = request.json
        session_id = data.get('session_id')
        field_values = data.get('field_values', {})
        selected_templates = data.get('selected_templates', [])

        if not session_id:
            return jsonify({'error': 'No session ID'}), 400

        if not selected_templates:
            return jsonify({'error': 'No templates selected'}), 400

        # Token check — need enough for all selected templates
        try:
            import db
            tokens = db.get_tenant_tokens_remaining(tenant_id)
            if tokens == 0:
                return jsonify({'error': 'No tokens remaining. Please contact NextStep to top up.'}), 402
            if 0 < tokens < len(selected_templates):
                selected_templates = selected_templates[:tokens]
                app.logger.warning("[Process] Trimmed to %d templates (token limit)", len(selected_templates))
        except Exception as e:
            app.logger.warning("[Process] Token check skipped: %s", e)

        output_folder = _output_folder(tenant_id, user_id, session_id)
        if output_folder.exists():
            shutil.rmtree(output_folder)
        output_folder.mkdir(parents=True, exist_ok=True)
        
        generated_files = []
        errors = []
        
        full_name = (field_values.get("Candidate Name") or "").strip()
        name_parts = full_name.split()
        first_name = name_parts[0] if name_parts else ""
        last_name = name_parts[-1] if len(name_parts) > 1 else ""
        
        role = (field_values.get("Role") or "").strip()
        yes_na = "NA" if role.upper() == "HCA" else "YES"
        todays = _dt.date.today().strftime("%d/%m/%Y")
        
        nationality = (field_values.get("Nationality") or "").strip().lower()
        if "british" in nationality or "uk" in nationality:
            field_values["RTW Status"] = "UK Passport"
            field_values["Visa Expiry Date"] = "UK Passport"
            field_values["Visa Type"] = "UK Passport"
            field_values["Restriction"] = "UK Passport"
            field_values["Share Code"] = "UK Passport"
        
        replacements = {
            "Candidate Name": full_name,
            "Candidate First Name": first_name,
            "Candidate First name": first_name,
            "Candidate surname": last_name,
            "Candidate last name": last_name,
            "Candidate Address": field_values.get("Address", ""),
            "Candidate address": field_values.get("Address", ""),
            "Address": field_values.get("Address", ""),
            "Candidate Mobile Number": field_values.get("Phone", ""),
            "Phone": field_values.get("Phone", ""),
            "DOB": field_values.get("DOB", ""),
            "D.O.B": field_values.get("DOB", ""),
            "Date Of Birth": field_values.get("DOB", ""),
            "Nationality": field_values.get("Nationality", ""),
            "HCA/RGN": role,
            " HCA/RGN": role,
            "NI Number": field_values.get("NI Number", ""),
            "NMC Pin Number": field_values.get("NMC PIN", ""),
            "NMC Pin number": field_values.get("NMC PIN", ""),
            "NMC pin": field_values.get("NMC PIN", ""),
            "DBS Certificate Number": field_values.get("DBS Number", ""),
            "DBS certificate number": field_values.get("DBS Number", ""),
            "DBS Certificate issue date": field_values.get("DBS Issue Date", ""),
            "DBS certificate issue date": field_values.get("DBS Issue Date", ""),
            "DBS Certificate last checked date": field_values.get("DBS Last Checked Date", ""),
            "DBS last checked date": field_values.get("DBS Last Checked Date", ""),
            "DBS expiry date": field_values.get("DBS Last Checked Date", ""),
            "Training completion date": field_values.get("Training Date", ""),
            "Training expiry date": field_values.get("Training Expiry Date", ""),
            "Right to work expiry date": field_values.get("Visa Expiry Date", ""),
            "Right To Work Expiry Date": field_values.get("Visa Expiry Date", ""),
            "Type of visa": field_values.get("Visa Type", ""),
            "Restriction": field_values.get("Restriction", ""),
            "Today's Date": todays,
            "Today's date": todays,
            "YES/NA": yes_na,
            "Candidate share code": field_values.get("Share Code", ""),
        }

        # Also include canonical field names directly (mapping engine handles variations/typos)
        for k, v in (field_values or {}).items():
            if k not in replacements:
                replacements[k] = v or ""


        
        for template_name in selected_templates:
            template_path = TEMPLATE_FOLDER / f"{template_name}.docx"
            
            if not template_path.exists():
                errors.append(f"Template not found: {template_name}.docx")
                continue
            
            output_path = output_folder / f"{template_name}_filled.docx"
            
            try:
                replaced, warnings = fill_docx_template(template_path, output_path, replacements)
                generated_files.append(output_path.name)
                
                if warnings:
                    errors.extend([f"{template_name}: {w}" for w in warnings])
            
            except Exception as e:
                errors.append(f"{template_name}: {str(e)}")
        
        if generated_files:
            zip_path = output_folder / 'checklists.zip'
            with zipfile.ZipFile(zip_path, 'w') as zipf:
                for file in output_folder.glob('*.docx'):
                    zipf.write(file, file.name)

        # Charge 1 token per successfully generated template
        successful_count = len(generated_files)
        if successful_count > 0:
            try:
                import db
                db_job_id = db.create_job_record(tenant_id=tenant_id, user_id=user_id,
                                                  total_items=successful_count)
                db.update_job_status(db_job_id=db_job_id, status='completed',
                                     successful_items=successful_count, failed_items=len(errors))
                db.record_usage(tenant_id=tenant_id, user_id=user_id,
                                db_job_id=db_job_id, successful_outputs=successful_count)
            except Exception as e:
                app.logger.warning("[Process] Token charge failed: %s", e)

        # Build download URLs using isolated path
        file_downloads = []
        for fn in generated_files:
            file_downloads.append({'filename': fn, 'url': f'/download/{session_id}/{fn}'})

        return jsonify({
            'success': True,
            'files_generated': successful_count,
            'generated_files': generated_files,
            'file_downloads': file_downloads,
            'tokens_charged': successful_count,
            'zip_available': (output_folder / 'checklists.zip').exists(),
            'zip_download_url': f'/download/{session_id}/checklists.zip' if (output_folder / 'checklists.zip').exists() else '',
            'errors': errors
        })
    
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/download/<session_id>/<filename>')
def download(session_id, filename):
    """Download generated files — auth + ownership check."""
    ctx = _require_auth()
    tenant_id = ctx['tenant_id']; user_id = ctx['user_id']
    try:
        # Only serve files from this user's isolated output folder
        file_path = _output_folder(tenant_id, user_id, session_id) / filename

        if not file_path.exists():
            return jsonify({'error': 'File not found or expired'}), 404

        # Schedule cleanup after ZIP download
        import threading, time as _time
        def _cleanup_later():
            _time.sleep(600)  # 10 minutes
            try:
                up = _upload_folder(tenant_id, user_id, session_id)
                out = _output_folder(tenant_id, user_id, session_id)
                import shutil as _sh
                if up.exists(): _sh.rmtree(up, ignore_errors=True)
                if out.exists(): _sh.rmtree(out, ignore_errors=True)
                app.logger.info("[Cleanup] Deleted session %s", session_id)
            except Exception as e:
                app.logger.warning("[Cleanup] %s", e)

        if filename.endswith('.zip'):
            threading.Thread(target=_cleanup_later, daemon=True).start()

        return send_file(file_path, as_attachment=True)

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'gemini_configured': bool(gemini_client),
        'tesseract_available': bool(pytesseract),
        'pdfplumber_available': bool(pdfplumber),
        'pymupdf_available': bool(fitz),
        'model_fast': GEMINI_MODEL_FAST,
        'model_strong': GEMINI_MODEL_STRONG,
        'db': bool(os.getenv('DATABASE_URL')),
    })

if __name__ == '__main__':
    print("="*60)
    print("Compliance Checklist Automation - Web App")
    print("COMPLETE VERSION with Smart Extraction Logic")
    print("="*60)
    print(f"Gemini API configured: {bool(gemini_client)}")
    print(f"Tesseract OCR available: {bool(pytesseract)}")
    print(f"PDF extraction available: {bool(pdfplumber)}")
    print(f"Document folders: {len(DOCUMENT_FOLDERS)}")
    print(f"Templates configured: {len(CHECKLIST_TEMPLATES)}")
    print("="*60)
    app.run(debug=True, host='0.0.0.0', port=5000)

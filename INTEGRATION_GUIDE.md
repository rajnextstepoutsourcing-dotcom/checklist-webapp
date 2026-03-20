# 🔧 Integration Guide: Adding Your Core Logic to Web App

## Overview
Your `aialmost.py` has all the extraction and processing logic. This guide shows exactly what to copy into `web_app.py`.

---

## ✂️ Step 1: Copy Core Functions

### Functions to Copy from aialmost.py → web_app.py

Copy these functions EXACTLY as they are (lines 187-2882):

```python
# Copy these entire function definitions:

1. extract_text_pdf() - Lines ~300-400
2. extract_text_image() - Lines ~400-500  
3. extract_text_docx() - Lines ~500-600
4. gather_candidate_text() - Lines ~600-700
5. ai_extract_with_model() - Lines ~800-1000
6. extract_application_details() - Lines ~1000-1200
7. fill_docx_template() - Lines ~2300-2500 (MOST IMPORTANT)
8. All regex patterns and field extractors
```

### Where to Place in web_app.py:

```python
# Add after the imports section, before routes:

# ============= CORE EXTRACTION FUNCTIONS (from aialmost.py) =============

def extract_text_pdf(pdf_path: Path) -> str:
    """Extract text from PDF using pdfplumber"""
    # COPY FULL FUNCTION HERE

def extract_text_image(img_path: Path) -> str:
    """Extract text from image using OCR"""
    # COPY FULL FUNCTION HERE

def extract_text_docx(docx_path: Path) -> str:
    """Extract text from DOCX"""
    # COPY FULL FUNCTION HERE

def gather_candidate_text(folder: Path) -> Tuple[str, Dict]:
    """Gather all text from candidate folder"""
    # COPY FULL FUNCTION HERE

def ai_extract_with_model(all_text: str, model_name: str) -> Dict[str, FieldValue]:
    """Extract fields using Gemini AI"""
    # COPY FULL FUNCTION HERE

def extract_application_details(app_text: str) -> Dict[str, str]:
    """Extract from application form"""
    # COPY FULL FUNCTION HERE

def fill_docx_template(template_path: Path, output_path: Path, replacements: Dict[str, str]) -> Tuple[int, List[str]]:
    """Fill DOCX template with data"""
    # COPY FULL FUNCTION HERE

# ======================================================================
```

---

## 🔗 Step 2: Integrate into Routes

### Route 1: `/upload` - File Upload Handler

```python
@app.route('/upload', methods=['POST'])
def upload_files():
    try:
        candidate_files = request.files.getlist('candidate_files')
        template_files = request.files.getlist('template_files')
        
        # Create session folder
        session_id = str(int(time.time() * 1000))
        session_folder = UPLOAD_FOLDER / session_id
        candidate_folder = session_folder / 'candidates'
        candidate_folder.mkdir(parents=True, exist_ok=True)
        
        # Save candidate documents
        for file in candidate_files:
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                file.save(candidate_folder / filename)
        
        # Save templates
        for file in template_files:
            if file and file.filename.endswith('.docx'):
                filename = secure_filename(file.filename)
                file.save(TEMPLATE_FOLDER / filename)
        
        session['session_id'] = session_id
        
        return jsonify({
            'success': True, 
            'session_id': session_id,
            'candidate_folder': str(candidate_folder)
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500
```

### Route 2: `/process` - Extract and Generate

```python
@app.route('/process', methods=['POST'])
def process_documents():
    try:
        data = request.json
        session_id = data.get('session_id')
        selected_checklists = data.get('selected_checklists', [])
        field_values = data.get('field_values', {})  # User-edited values
        
        candidate_folder = UPLOAD_FOLDER / session_id / 'candidates'
        
        # ===== EXTRACTION PHASE =====
        # Use your functions here:
        all_text, debug_info = gather_candidate_text(candidate_folder)
        
        # Extract using AI
        if genai and GEMINI_API_KEY:
            ai_extracted = ai_extract_with_model(all_text, GEMINI_MODEL_FAST)
        else:
            ai_extracted = {}
        
        # Merge AI extracted with user edits
        final_values = {}
        for field in STANDARD_FIELDS:
            # Prioritize user-edited values
            if field in field_values and field_values[field].strip():
                final_values[field] = field_values[field].strip()
            elif field in ai_extracted:
                final_values[field] = ai_extracted[field].value
            else:
                final_values[field] = ""
        
        # ===== GENERATION PHASE =====
        output_folder = OUTPUT_FOLDER / session_id
        output_folder.mkdir(parents=True, exist_ok=True)
        
        generated_files = []
        
        for checklist_name in selected_checklists:
            template_path = TEMPLATE_FOLDER / f"{checklist_name}.docx"
            
            if not template_path.exists():
                continue
            
            output_path = output_folder / f"{checklist_name}_filled.docx"
            
            # Prepare replacements (same logic as your original code)
            full_name = final_values.get("Candidate Name", "")
            name_parts = full_name.split()
            first_name = name_parts[0] if name_parts else ""
            last_name = name_parts[-1] if len(name_parts) > 1 else ""
            
            role = final_values.get("Role", "")
            yes_na = "NA" if role.upper() == "HCA" else "YES"
            todays = _dt.date.today().strftime("%d/%m/%Y")
            
            replacements = {
                "Candidate Name": full_name,
                "Candidate First Name": first_name,
                "Candidate surname": last_name,
                "Address": final_values.get("Address", ""),
                "Phone": final_values.get("Phone", ""),
                "DOB": final_values.get("DOB", ""),
                "Nationality": final_values.get("Nationality", ""),
                "HCA/RGN": role,
                "NI Number": final_values.get("NI Number", ""),
                "NMC Pin Number": final_values.get("NMC PIN", ""),
                "DBS Certificate Number": final_values.get("DBS Number", ""),
                "DBS Certificate issue date": final_values.get("DBS Issue Date", ""),
                "DBS last checked date": final_values.get("DBS Last Checked Date", ""),
                "Training completion date": final_values.get("Training Date", ""),
                "Training expiry date": final_values.get("Training Expiry Date", ""),
                "Right to work expiry date": final_values.get("Visa Expiry Date", ""),
                "Type of visa": final_values.get("Visa Type", ""),
                "Restriction": final_values.get("Restriction", ""),
                "Today's Date": todays,
                "YES/NA": yes_na,
            }
            
            # Fill the template
            changed, warnings = fill_docx_template(template_path, output_path, replacements)
            generated_files.append(output_path.name)
        
        # Create ZIP of all generated files
        zip_path = output_folder / 'checklists.zip'
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            for file in output_folder.glob('*.docx'):
                zipf.write(file, file.name)
        
        return jsonify({
            'success': True,
            'files_generated': len(generated_files),
            'download_url': f'/download/{session_id}/checklists.zip'
        })
    
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
```

### Route 3: `/extract` - Just Extraction (Optional)

```python
@app.route('/extract', methods=['POST'])
def extract_only():
    """Just extract data without generating - for preview"""
    try:
        data = request.json
        session_id = data.get('session_id')
        
        candidate_folder = UPLOAD_FOLDER / session_id / 'candidates'
        
        # Use your functions
        all_text, debug_info = gather_candidate_text(candidate_folder)
        
        if genai and GEMINI_API_KEY:
            ai_extracted = ai_extract_with_model(all_text, GEMINI_MODEL_FAST)
        else:
            ai_extracted = {}
        
        # Convert to simple dict for JSON
        extracted_data = {
            field: ai_extracted[field].value 
            for field in STANDARD_FIELDS 
            if field in ai_extracted
        }
        
        return jsonify({
            'success': True,
            'extracted_data': extracted_data
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500
```

---

## 🔑 Step 3: Initialize Gemini Client

Add this near the top of web_app.py, after imports:

```python
# Initialize Gemini client if API key available
gemini_client = None
if genai and GEMINI_API_KEY:
    try:
        gemini_client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        print(f"Failed to initialize Gemini: {e}")
```

Then update `ai_extract_with_model()` to use `gemini_client` instead of initializing each time.

---

## 📋 Step 4: Update Frontend

Update `templates/index.html` to call the new routes:

```javascript
// In extractData() function:
async function extractData() {
    if (candidateFiles.length === 0) {
        showStatus('Please upload candidate documents!', 'error');
        return;
    }

    // First, upload files
    const formData = new FormData();
    candidateFiles.forEach(f => formData.append('candidate_files', f));
    templateFiles.forEach(f => formData.append('template_files', f));

    try {
        const uploadResponse = await fetch('/upload', {
            method: 'POST',
            body: formData
        });
        const uploadResult = await uploadResponse.json();
        
        if (!uploadResult.success) {
            showStatus('Upload failed: ' + uploadResult.error, 'error');
            return;
        }
        
        sessionId = uploadResult.session_id;
        
        // Then, extract data
        const extractResponse = await fetch('/extract', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({session_id: sessionId})
        });
        
        const extractResult = await extractResponse.json();
        
        if (extractResult.success) {
            displayExtractedData(extractResult.extracted_data);
            showStatus('Data extracted!', 'success');
        }
        
    } catch (error) {
        showStatus('Error: ' + error.message, 'error');
    }
}
```

---

## ⚙️ Step 5: Environment Setup

Create `.env` file for local testing:

```bash
GEMINI_API_KEY=your_actual_api_key_here
SECRET_KEY=random_secret_string_123
GEMINI_MODEL_FAST=gemini-2.0-flash-001
GEMINI_MODEL_STRONG=gemini-2.5-pro
```

Load it in `web_app.py`:

```python
from dotenv import load_dotenv
load_dotenv()  # Add this near the top
```

---

## 🧪 Testing Checklist

After integration, test:

1. [ ] Upload candidate PDFs/images → Files appear in uploads/
2. [ ] Click "Extract" → See extracted fields in preview
3. [ ] Edit fields manually → Changes are saved
4. [ ] Select checklists → Checkboxes work
5. [ ] Click "Generate" → DOCX files created
6. [ ] Download ZIP → Contains filled checklists
7. [ ] Check filled DOCX → Placeholders replaced correctly

---

## 🐛 Common Integration Issues

### Issue: "NameError: name 'gather_candidate_text' is not defined"
**Fix**: Make sure you copied all functions before the routes

### Issue: "genai has no attribute 'Client'"
**Fix**: Check your google-genai version: `pip install --upgrade google-genai`

### Issue: Placeholders not being replaced
**Fix**: Check the `replacements` dict matches your template placeholders exactly

### Issue: "File not found" when downloading
**Fix**: Verify files are being saved to `OUTPUT_FOLDER / session_id /`

---

## 📝 Summary

1. **Copy** all extraction functions from aialmost.py
2. **Place** them in web_app.py before routes
3. **Update** routes to use these functions
4. **Test** locally
5. **Deploy** to Render

**Your core logic stays the same - only the input/output mechanism changes!**

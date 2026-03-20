# 📋 Compliance Checklist Automation - Web Application

## 🎯 Overview
This web application automatically fills compliance checklists by extracting information from candidate documents (PDFs, images, Word docs) using AI (Google Gemini) and OCR.

**Converted from**: Desktop tkinter application  
**For**: Online web hosting  

---

## 🚀 FREE Hosting Options (Choose One)

### ⭐ Option 1: Render (RECOMMENDED - Easiest)

**Why**: Free tier, auto-deploys from GitHub, easy setup  
**Time**: ~10 minutes  

**Steps**:
1. **Prepare your code** - Upload all files to GitHub
2. **Sign up** at [render.com](https://render.com)
3. **Create New Web Service**:
   - Click "New +" → "Web Service"
   - Connect your GitHub repo
4. **Configure**:
   - Name: `checklist-automation`
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn web_app:app`
5. **Add Environment Variables**:
   - `GEMINI_API_KEY` = your_google_gemini_key
   - `SECRET_KEY` = any_random_string (e.g., `abc123xyz`)
6. **Deploy** - Click "Create Web Service"
7. **Done!** Your app will be at `https://checklist-automation.onrender.com`

### Option 2: Railway.app

**Why**: Good free tier, modern interface  
**Steps**: Similar to Render, auto-detects Python apps

### Option 3: PythonAnywhere

**Why**: Simple, good for learning  
**Cons**: Manual setup, slower

---

## 📦 What You Need

### Files (Already Created):
- ✅ `web_app.py` - Flask backend
- ✅ `templates/index.html` - Frontend UI
- ✅ `requirements.txt` - Python packages
- ✅ `Procfile` - Tells server how to run app
- ✅ `runtime.txt` - Python version
- ✅ `Aptfile` - System packages (Tesseract OCR)
- ✅ `.gitignore` - Files to ignore in Git

### Keys You Need to Get:

#### 1. Google Gemini API Key (FREE)
1. Go to: https://aistudio.google.com/app/apikey
2. Click "Create API Key"
3. Copy the key (starts with `AIza...`)
4. Save it - you'll add this to your hosting platform

#### 2. Secret Key (Generate)
Run this in Python to generate:
```python
import secrets
print(secrets.token_hex(32))
```
Or just use any random string like: `mysecretkey123`

---

## 🔧 Local Testing (Before Deploying)

Test on your computer first:

```bash
# 1. Install Python 3.11+ if not installed

# 2. Create virtual environment
python -m venv venv

# 3. Activate environment
# Windows:
venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate

# 4. Install packages
pip install -r requirements.txt

# 5. Set environment variables
# Windows:
set GEMINI_API_KEY=your_key_here
set SECRET_KEY=mysecret123

# Mac/Linux:
export GEMINI_API_KEY=your_key_here
export SECRET_KEY=mysecret123

# 6. Run the app
python web_app.py

# 7. Open browser: http://localhost:5000
```

---

## 📝 Step-by-Step Render Deployment

### Step 1: Prepare Code
1. Create folder: `checklist-automation`
2. Copy all files:
   - web_app.py
   - requirements.txt
   - Procfile
   - runtime.txt
   - Aptfile
   - .gitignore
   - templates/ folder with index.html

### Step 2: Upload to GitHub
```bash
cd checklist-automation
git init
git add .
git commit -m "Initial commit"
git branch -M main

# Create new repo on GitHub, then:
git remote add origin https://github.com/yourusername/checklist-automation.git
git push -u origin main
```

### Step 3: Deploy on Render
1. Go to https://dashboard.render.com
2. Click "New +" → "Web Service"
3. Click "Connect" next to your GitHub repo
4. Fill in:
   ```
   Name: checklist-automation
   Environment: Python 3
   Build Command: pip install -r requirements.txt
   Start Command: gunicorn web_app:app
   ```
5. Under "Environment Variables", add:
   ```
   GEMINI_API_KEY = your_actual_key
   SECRET_KEY = mysecret123
   ```
6. Click "Create Web Service"
7. Wait 5-10 minutes for build

### Step 4: Test Your Live App
1. Render will show your URL: `https://yourapp.onrender.com`
2. Open it in browser
3. Test uploading files

---

## 🎨 How the Web Version Works

### Key Differences from Desktop:

| Desktop Version | Web Version |
|----------------|-------------|
| Windows GUI (tkinter) | HTML/JavaScript frontend |
| Local file browser | Drag-and-drop upload |
| Hardcoded Windows paths | Server paths (uploads/, outputs/) |
| Single user | Multiple users with sessions |
| Direct file access | File uploads → temporary storage |

### File Flow:
1. **User uploads files** → Saved to `uploads/[session_id]/`
2. **App processes files** → Extracts data using AI
3. **User reviews/edits data** → Shown in web form
4. **App generates checklists** → Saved to `outputs/[session_id]/`
5. **User downloads** → ZIP file with all checklists

---

## 🔍 Main Changes Made

### 1. Removed tkinter GUI
❌ Old: Desktop windows and buttons  
✅ New: HTML forms and JavaScript

### 2. Changed File Handling
❌ Old: `C:\Users\...` Windows paths  
✅ New: `uploads/`, `outputs/` relative paths

### 3. Added Web Routes
```python
@app.route('/')              # Homepage
@app.route('/upload')        # Handle file uploads
@app.route('/process')       # Process documents
@app.route('/download/<id>') # Download results
```

### 4. Session Management
Each user gets unique session ID to keep their files separate

### 5. Tesseract Path
❌ Old: `C:\Program Files\Tesseract-OCR\tesseract.exe`  
✅ New: Auto-detects Linux path `/usr/bin/tesseract`

---

## 🐛 Common Issues & Fixes

### Issue: "No module named 'flask'"
**Fix**: Make sure you ran `pip install -r requirements.txt`

### Issue: "Tesseract not found"
**Fix**: Aptfile should install it automatically on Render. Verify it's included.

### Issue: "Application error" on Render
**Fix**: Check logs in Render dashboard → Logs tab

### Issue: Files not uploading
**Fix**: Check browser console for errors. Make sure file size < 100MB.

### Issue: "GEMINI_API_KEY not set"
**Fix**: Add it in Render dashboard → Environment → Environment Variables

---

## 📊 What's Included

### Backend (web_app.py):
- ✅ Flask web server
- ✅ File upload handling
- ✅ Session management
- ✅ File processing routes
- ✅ Download endpoints

### Frontend (templates/index.html):
- ✅ Modern, responsive UI
- ✅ Drag-and-drop file upload
- ✅ Progress indicators
- ✅ File preview
- ✅ Form for editing extracted data
- ✅ Checklist selection

### Dependencies (requirements.txt):
- Flask (web framework)
- python-docx (Word files)
- pdfplumber (PDF extraction)
- Pillow (image processing)
- pytesseract (OCR)
- google-genai (AI extraction)
- gunicorn (production server)

---

## 🎯 TODO: Complete Integration

The current `web_app.py` has placeholder sections marked with `# TODO`. You need to:

1. **Copy extraction logic** from your original `aialmost.py`:
   - Text extraction functions
   - AI extraction with Gemini
   - DOCX template filling
   - Field parsing

2. **Integrate these functions** into the web routes:
   - `/upload` → Save files
   - `/process` → Extract data using AI
   - `/download` → Return filled checklists

**I can help you do this!** Share specific functions you want to migrate.

---

## 🆘 Need Help?

### Quick Fixes:
1. **Can't deploy?** → Check Render logs for errors
2. **AI not working?** → Verify GEMINI_API_KEY is set
3. **Files not processing?** → Check file permissions and paths
4. **Timeout errors?** → Increase timeout in Procfile

### Resources:
- Render Docs: https://render.com/docs
- Flask Tutorial: https://flask.palletsprojects.com
- Gemini API: https://ai.google.dev/docs

---

## ✅ Success Checklist

Before deploying:
- [ ] All files uploaded to GitHub
- [ ] Gemini API key obtained
- [ ] Tested locally (works on your computer)
- [ ] Environment variables ready
- [ ] Render account created

After deploying:
- [ ] App builds successfully
- [ ] Can access homepage
- [ ] File upload works
- [ ] Processing works (even if results are placeholders)
- [ ] Download works

---

## 🎉 You're Ready!

**Next Steps:**
1. Follow "Step-by-Step Render Deployment" above
2. Deploy to Render
3. Test the basic workflow
4. Integrate your AI extraction code
5. Test with real documents
6. Share with users!

**Your web app will be live at**: `https://yourappname.onrender.com`

Good luck! 🚀

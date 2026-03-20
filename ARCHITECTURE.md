# System Architecture

## How Your Web App Works

```
┌─────────────────────────────────────────────────────────────┐
│                        USER'S BROWSER                        │
│                                                              │
│  ┌────────────────────────────────────────────────────┐    │
│  │         index.html (Beautiful UI)                   │    │
│  │  • Drag & drop file upload                          │    │
│  │  • Preview extracted data                           │    │
│  │  • Edit fields                                       │    │
│  │  • Select checklists                                │    │
│  │  • Download results                                 │    │
│  └────────────────────────────────────────────────────┘    │
│                           │                                  │
│                           │ HTTP Requests (AJAX/Fetch)       │
│                           ▼                                  │
└───────────────────────────────────────────────────────────┘

                            │
                            │
                            ▼

┌─────────────────────────────────────────────────────────────┐
│              WEB SERVER (Render / Railway / etc)            │
│                                                              │
│  ┌────────────────────────────────────────────────────┐    │
│  │          web_app.py (Flask Backend)                 │    │
│  │                                                      │    │
│  │  Routes:                                             │    │
│  │  • /upload → Save files to uploads/session_id/      │    │
│  │  • /extract → Extract data using AI                 │    │
│  │  • /process → Generate filled checklists            │    │
│  │  • /download → Send ZIP to user                     │    │
│  └────────────────────────────────────────────────────┘    │
│                           │                                  │
└───────────────────────────│──────────────────────────────────┘
                            │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
        ▼                  ▼                  ▼

┌─────────────┐   ┌──────────────┐   ┌─────────────────┐
│   Google    │   │    Local     │   │   Tesseract     │
│   Gemini    │   │  File System │   │   OCR Engine    │
│   API       │   │              │   │                 │
│ (AI Extract)│   │ • uploads/   │   │ (Read Images)   │
│             │   │ • outputs/   │   │                 │
│             │   │ • templates/ │   │                 │
└─────────────┘   └──────────────┘   └─────────────────┘
```

## Data Flow

### 1. Upload Phase
```
User drags PDF → Browser → POST /upload → Flask saves to uploads/123/
```

### 2. Extraction Phase
```
User clicks Extract → POST /extract → Flask:
  → Reads files from uploads/123/
  → Uses Tesseract for images
  → Uses pdfplumber for PDFs
  → Sends text to Gemini AI
  → Returns extracted fields
```

### 3. Review Phase
```
User sees extracted data → Can edit in browser → Data stays in frontend
```

### 4. Generation Phase
```
User clicks Generate → POST /process → Flask:
  → Takes user's edited values
  → Reads template .docx files
  → Replaces {{placeholders}}
  → Saves filled .docx to outputs/123/
  → Creates ZIP file
```

### 5. Download Phase
```
User clicks Download → GET /download/123/checklists.zip → Browser downloads
```

## File Structure on Server

```
/app/                          (Server root)
├── web_app.py                 (Main application)
├── templates/
│   └── index.html             (Frontend UI)
├── uploads/
│   ├── 1707654321/            (Session 1)
│   │   └── candidates/
│   │       ├── resume.pdf
│   │       └── photo.jpg
│   └── 1707654322/            (Session 2)
│       └── candidates/
│           └── application.docx
├── outputs/
│   ├── 1707654321/
│   │   ├── HC-One_filled.docx
│   │   ├── EXEMPLAR_filled.docx
│   │   └── checklists.zip
│   └── 1707654322/
│       └── checklists.zip
└── templates_docx/
    ├── HC-One.docx
    ├── EXEMPLAR.docx
    └── Healthcare Homes.docx
```

## Key Differences: Desktop vs Web

| Aspect | Desktop (aialmost.py) | Web (web_app.py) |
|--------|---------------------|------------------|
| **UI** | tkinter windows | HTML/CSS/JavaScript |
| **Users** | Single user | Multiple users (sessions) |
| **File Input** | File dialog | HTTP upload |
| **File Storage** | Local fixed paths | Temporary session folders |
| **Processing** | Synchronous (blocks UI) | Asynchronous (background) |
| **Output** | Local folder | ZIP download |
| **Deployment** | Windows .exe | Cloud server |

## Why This Architecture?

### Sessions (session_id)
- Each user gets unique ID
- Keeps files separate
- Prevents data mixing
- Easy cleanup

### Temporary Storage
- Files auto-delete after 24hrs
- Saves server space
- Privacy protection
- No permanent storage needed

### API-Based
- Frontend talks to backend via HTTP
- Can update UI without reloading
- Better user experience
- Mobile-friendly

### Stateless
- Server doesn't remember users
- Each request is independent
- Scales easily
- No memory issues

## Security Considerations

### API Keys
✅ Stored in environment variables (not in code)  
✅ Never sent to frontend  
✅ Never in logs  

### File Uploads
✅ Filename sanitization (secure_filename)  
✅ File type validation  
✅ Size limits (100MB max)  
✅ Session isolation  

### Sessions
✅ Random session IDs  
✅ Files only accessible to uploader  
✅ Auto-cleanup prevents accumulation  

## Performance

### Speed
- Upload: ~2 seconds for 10MB
- Extraction: ~5-15 seconds (depends on AI)
- Generation: ~1 second per checklist
- Download: ~1 second for ZIP

### Limits (Free Tier)
- Render: May sleep after 15min idle
- File size: 100MB max per upload
- Gemini API: Rate limits apply
- Storage: Temporary (auto-delete)

## Scaling Options

### If you need more:
1. **Paid Render tier** → Faster, no sleep
2. **AWS S3** → Permanent file storage
3. **Redis** → Better session management
4. **Worker queues** → Background processing
5. **Load balancer** → Multiple servers

---

**This architecture gives you a production-ready web app from your desktop script!** 🚀

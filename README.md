# Job Application Automation Pipeline

Paste a job description → get a tailored resume + cover letter in your Google Drive in under 60 seconds.

## How it works

```
Job description (POST /resume-tailor)
    → n8n webhook
    → Flask server (localhost:5001)
    → Claude API: parse JD → tailor resume → generate cover letter
    → build ATS-clean .docx files
    → upload to Google Drive
    → return Drive folder link
```

## Start the pipeline

```bash
cd ~/job-automation
./start.sh
```

This starts the Flask server on port 5001 and n8n together. One `Ctrl-C` stops both cleanly.

First time only — import the workflow into n8n:
1. Open http://localhost:5678
2. Workflows → ⋯ → **Import from file** → select `workflow.json`
3. Toggle the workflow **Active**

## Send a job description

### Via curl

```bash
curl -s -X POST http://localhost:5678/webhook/resume-tailor \
  -H "Content-Type: application/json" \
  -d '{
    "jd": "Paste the full job description text here as a single JSON string."
  }' | python3 -m json.tool
```

Response:
```json
{
  "company": "Rivian",
  "drive_link": "https://drive.google.com/drive/folders/..."
}
```

### Direct (no n8n)

```bash
python3 tailor.py --file path/to/jd.txt
# or
python3 tailor.py "Full JD text here"
# or just run with no args to re-run the Rivian test case
python3 tailor.py
```

## Where files land in Google Drive

All files are uploaded to **sir4us2020@gmail.com**'s Drive under:

```
My Drive/
└── Job Applications/
    └── {Company}/
        ├── AzatSh-{Company}-resume.docx
        └── AzatSh-{Company}-coverL.docx
```

Re-running for the same company overwrites the existing files — no duplicates.

Local copies are also saved in `output/`:
- `output/AzatSh-{Company}-resume.docx`
- `output/AzatSh-{Company}-coverL.docx`
- `output/tailored_{Company}.json` — the tailored resume JSON for inspection

## Update the master resume

When your experience, skills, or education changes:

1. Update `master-resume.docx` in `~/job-automation/` with your new content
2. Re-run the parser:
   ```bash
   python3 parse_resume.py
   ```
3. Verify `master_resume.json` looks correct — check the printed summary in the terminal
4. That's it. The next `tailor.py` run will use the updated master automatically

The parser expects the same structure as the original document:
- Name on line 1, contact info (● separated) on line 2
- Section headings in ALL CAPS bold: `SUMMARY`, `SKILLS`, `EXPERIENCE`, `EDUCATION`
- Job entries as `Title  |  Company\tDates` with bullets on indented lines below
- Skill lines as `Category: item1, item2, ...`

## Files in this project

| File | Purpose |
|---|---|
| `parse_resume.py` | Parse `master-resume.docx` → `master_resume.json` |
| `build_docs.py` | Build ATS-clean .docx from tailored JSON + cover letter text |
| `drive_upload.py` | Upload output files to Google Drive via OAuth2 |
| `tailor.py` | Full pipeline: Claude API tailoring + build + upload |
| `server.py` | Flask wrapper exposing `POST /tailor` on port 5001 |
| `workflow.json` | n8n workflow: webhook → server → respond |
| `start.sh` | Start server + n8n together |
| `master-resume.docx` | Your master resume (source of truth) |
| `master_resume.json` | Parsed master resume (generated, do not edit manually) |
| `credentials.json` | Google service account (not used for upload — kept for reference) |
| `oauth_client.json` | Google OAuth2 client (Drive upload auth) |
| `token.json` | OAuth2 token (auto-refreshed, do not commit) |
| `.env` | `ANTHROPIC_API_KEY` (never commit) |

## Environment variables

Set in `.env` (loaded automatically):
```
ANTHROPIC_API_KEY=sk-ant-...
```

## Requirements

```bash
pip install python-docx anthropic google-api-python-client google-auth \
            google-auth-oauthlib flask python-dotenv
```

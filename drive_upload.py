#!/usr/bin/env python3
"""
drive_upload.py — upload resume + cover letter .docx to Google Drive.

Uses OAuth2 so files are owned by your Google account and count against your
storage quota, not a service account's.

One-time setup:
  1. GCP Console → APIs & Services → Credentials
     Create Credentials → OAuth 2.0 Client ID → Desktop app → Create
  2. Download JSON → save as  oauth_client.json  in this folder
  3. OAuth consent screen → add your Google account as a Test User
  4. Run:  python drive_upload.py <company>
     Browser opens → sign in → allow Drive access
     token.json is saved; all future runs are fully automatic.

Structure in your Drive:
  My Drive/
  └── Job Applications/
      └── {Company}/
          ├── AzatSh-{Company}-resume.docx
          └── AzatSh-{Company}-coverL.docx

Usage (CLI):
    python drive_upload.py <company_slug>

Importable API:
    from drive_upload import upload_application
    link = upload_application("Rivian")
"""

import json
import sys
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

OAUTH_CLIENT = Path("oauth_client.json")
TOKEN_FILE   = Path("token.json")
SCOPES       = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/spreadsheets",
]
ROOT_FOLDER  = "Job Applications"
DOCX_MIME    = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
FOLDER_MIME  = "application/vnd.google-apps.folder"
OUT_DIR      = Path("output")


# ── Auth ───────────────────────────────────────────────────────────────────────

def _get_credentials() -> Credentials:
    if not OAUTH_CLIENT.exists():
        sys.exit(
            "\nERROR: oauth_client.json not found.\n\n"
            "One-time setup:\n"
            "  1. GCP Console → APIs & Services → Credentials\n"
            "  2. Create Credentials → OAuth 2.0 Client ID → Desktop app → Create\n"
            "  3. Download JSON → save as oauth_client.json in this folder\n"
            "  4. OAuth consent screen → add your Google account as a Test User\n"
            "  5. Re-run this script.\n"
        )

    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        # Force re-auth if token is missing any required scope
        if creds and creds.scopes and not set(SCOPES).issubset(creds.scopes):
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(OAUTH_CLIENT), SCOPES)
            try:
                creds = flow.run_local_server(port=0, open_browser=True)
            except Exception:
                # Headless fallback: prints a URL to visit manually
                creds = flow.run_console()
        TOKEN_FILE.write_text(creds.to_json())

    return creds


def _service():
    return build("drive", "v3", credentials=_get_credentials())


# ── Drive helpers ──────────────────────────────────────────────────────────────

def _find_folder(svc, name: str, parent_id: str | None = None) -> str | None:
    q = (
        f"name = {json.dumps(name)}"
        f" and mimeType = '{FOLDER_MIME}'"
        f" and trashed = false"
    )
    if parent_id:
        q += f" and '{parent_id}' in parents"
    res = svc.files().list(q=q, fields="files(id)", pageSize=1).execute()
    files = res.get("files", [])
    return files[0]["id"] if files else None


def _find_or_create_folder(svc, name: str, parent_id: str | None = None) -> tuple[str, bool]:
    fid = _find_folder(svc, name, parent_id)
    if fid:
        return fid, False
    meta = {"name": name, "mimeType": FOLDER_MIME}
    if parent_id:
        meta["parents"] = [parent_id]
    f = svc.files().create(body=meta, fields="id").execute()
    return f["id"], True


def _find_file(svc, name: str, parent_id: str) -> str | None:
    q = (
        f"name = {json.dumps(name)}"
        f" and '{parent_id}' in parents"
        f" and trashed = false"
    )
    res = svc.files().list(q=q, fields="files(id)", pageSize=1).execute()
    files = res.get("files", [])
    return files[0]["id"] if files else None


def _upload_file(svc, filepath: Path, parent_id: str) -> str:
    name    = filepath.name
    media   = MediaFileUpload(str(filepath), mimetype=DOCX_MIME, resumable=False)
    file_id = _find_file(svc, name, parent_id)

    if file_id:
        svc.files().update(fileId=file_id, media_body=media).execute()
        print(f"  updated  {name}")
    else:
        meta = {"name": name, "parents": [parent_id]}
        f = svc.files().create(body=meta, media_body=media, fields="id").execute()
        file_id = f["id"]
        print(f"  uploaded {name}")

    return file_id


def _folder_link(folder_id: str) -> str:
    return f"https://drive.google.com/drive/folders/{folder_id}"


# ── Public API ─────────────────────────────────────────────────────────────────

def upload_application(company: str) -> str:
    """
    Upload AzatSh-{company}-resume.docx and AzatSh-{company}-coverL.docx
    from output/ → Drive/Job Applications/{company}/.
    Returns the Drive link to the company subfolder.
    """
    resume_path = OUT_DIR / f"AzatSh-{company}-resume.docx"
    cl_path     = OUT_DIR / f"AzatSh-{company}-coverL.docx"
    missing     = [p for p in (resume_path, cl_path) if not p.exists()]
    if missing:
        sys.exit(f"ERROR: missing output files: {[str(p) for p in missing]}")

    svc = _service()

    root_id, root_created = _find_or_create_folder(svc, ROOT_FOLDER)
    print(f"  {'created' if root_created else 'found  '} '{ROOT_FOLDER}' folder")

    company_id, co_created = _find_or_create_folder(svc, company, root_id)
    print(f"  {'created' if co_created else 'found  '} '{company}' subfolder")

    _upload_file(svc, resume_path, company_id)
    _upload_file(svc, cl_path,     company_id)

    return _folder_link(company_id)


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python drive_upload.py <company_slug>")
        sys.exit(1)
    company = sys.argv[1]
    print(f"Uploading '{company}' application to Drive...")
    link = upload_application(company)
    print(f"\nDrive link → {link}")

#!/usr/bin/env python3
"""
sheets_log.py — append a row to the job-tracker Google Sheet after each application.

Columns (A–O):
  #  |  Role / Position  |  Company  |  Platform  |  Date Applied  |  Location  |
  Format  |  Keyword Searched  |  Cover Letter?  |  Contacts for Outreach  |
  Interview?  |  Interview Date  |  Result  |  Pay ($/hr)  |  Comments / Notes
"""

from datetime import date

from googleapiclient.discovery import build

from drive_upload import _get_credentials

SPREADSHEET_ID = "1MRrqxTWRqerN_OfP_51MtI5Ae6hNVOSy"
RANGE          = "A:O"   # first sheet, columns A–O


def log_application(jd: dict, drive_link: str) -> None:
    """Append one row to the job tracker sheet."""
    creds = _get_credentials()
    svc   = build("sheets", "v4", credentials=creds)

    # Count existing rows to determine the next #
    result = svc.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range="A:A",
    ).execute()
    next_num = len(result.get("values", []))  # header = row 1, so data rows start at 1

    row = [
        next_num,                        # #
        jd.get("role", ""),              # Role / Position
        jd.get("company", ""),           # Company
        "",                              # Platform
        date.today().strftime("%m/%d/%Y"),  # Date Applied
        jd.get("location", ""),          # Location
        jd.get("work_type", ""),         # Format
        "",                              # Keyword Searched
        "Yes",                           # Cover Letter?
        "",                              # Contacts for Outreach
        "",                              # Interview?
        "",                              # Interview Date
        "",                              # Result
        "",                              # Pay ($/hr)
        drive_link,                      # Comments / Notes
    ]

    svc.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE,
        valueInputOption="USER_ENTERED",
        body={"values": [row]},
    ).execute()

    print(f"  logged   row {next_num} → {jd.get('company')} / {jd.get('role')}")

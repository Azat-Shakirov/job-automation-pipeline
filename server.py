#!/usr/bin/env python3
"""
server.py — Flask HTTP wrapper around the tailor.py pipeline.

Endpoints:
    POST /tailor   { "jd": "..." }  →  { "company": "...", "drive_link": "..." }
    GET  /health                    →  { "status": "ok" }

Run:
    python3 server.py

Listens on http://localhost:5001
"""

import sys
import traceback
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / ".env")

from flask import Flask, jsonify, request

from tailor import run_pipeline

app = Flask(__name__)


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/tailor")
def tailor():
    body = request.get_json(silent=True)

    if not body or not isinstance(body.get("jd"), str) or not body["jd"].strip():
        return jsonify({"error": 'Request body must be JSON with a non-empty "jd" string.'}), 400

    jd_text = body["jd"].strip()

    try:
        company, drive_link = run_pipeline(jd_text, verbose=False)
        return jsonify({"company": company, "drive_link": drive_link})
    except SystemExit as e:
        return jsonify({"error": str(e)}), 500
    except Exception:
        tb = traceback.format_exc()
        print(tb, file=sys.stderr)
        return jsonify({"error": tb.splitlines()[-1]}), 500


if __name__ == "__main__":
    print("Resume tailor server running on http://localhost:5001")
    print("POST /tailor  { \"jd\": \"...\" }")
    print("GET  /health")
    app.run(host="0.0.0.0", port=5001, debug=False)

"""
Flathead Valley Parcels — private, access-controlled map app.

- Admin logs in with ADMIN_PASSWORD and can mint time-limited client access links.
- Clients open a link (/enter/<code>) and get read-only access to the map until it expires.
- The parcel data is only served to authenticated sessions.
"""
import json
import os
import secrets
from datetime import datetime, timedelta, timezone

from flask import (
    Flask, abort, redirect, render_template, request,
    send_file, session, url_for, flash,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CODES_FILE = os.path.join(BASE_DIR, "access_codes.json")
GZ_PATH = os.path.join(BASE_DIR, "data", "parcels.geojson.gz")
RAW_FALLBACK = os.path.abspath(
    os.path.join(BASE_DIR, "..", "valley_parcels_with_phones.geojson")
)

app = Flask(__name__)
# Set a stable SECRET_KEY in production so sessions survive restarts.
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "ponderosa")


# ---------- access code storage ----------
def load_codes():
    if not os.path.exists(CODES_FILE):
        return {"codes": []}
    with open(CODES_FILE) as fh:
        return json.load(fh)


def save_codes(data):
    with open(CODES_FILE, "w") as fh:
        json.dump(data, fh, indent=2)


def find_code(code):
    for c in load_codes()["codes"]:
        if c["code"] == code:
            return c
    return None


def now_utc():
    return datetime.now(timezone.utc)


def code_active(c):
    if not c:
        return False
    if c.get("revoked"):
        return False
    exp = c.get("expires")
    if exp is None:
        return True
    return now_utc() < datetime.fromisoformat(exp)


# ---------- auth helpers ----------
def is_admin():
    return session.get("role") == "admin"


def session_valid():
    role = session.get("role")
    if role == "admin":
        return True
    if role == "client":
        exp = session.get("expires")
        if exp and now_utc() < datetime.fromisoformat(exp):
            # double-check the code still exists / isn't revoked
            return code_active(find_code(session.get("code")))
    return False


# ---------- routes ----------
@app.route("/")
def home():
    if not session_valid():
        return redirect(url_for("login"))
    label = session.get("label", "Guest") if session.get("role") == "client" else "Admin"
    return render_template("map.html", label=label, is_admin=is_admin())


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        entry = request.form.get("access", "").strip()
        if entry and entry == ADMIN_PASSWORD:
            session.clear()
            session["role"] = "admin"
            return redirect(url_for("home"))
        c = find_code(entry)
        if code_active(c):
            _grant_client(c)
            return redirect(url_for("home"))
        flash("Invalid or expired access code.")
    return render_template("login.html")


@app.route("/enter/<code>")
def enter(code):
    c = find_code(code)
    if code_active(c):
        _grant_client(c)
        return redirect(url_for("home"))
    return render_template("login.html", expired=True)


def _grant_client(c):
    session.clear()
    session["role"] = "client"
    session["code"] = c["code"]
    session["label"] = c.get("label", "Client")
    session["expires"] = c.get("expires")  # may be None (no expiry)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/data/parcels.geojson")
def parcels():
    if not session_valid():
        abort(403)
    if os.path.exists(GZ_PATH):
        resp = send_file(GZ_PATH, mimetype="application/geo+json")
        resp.headers["Content-Encoding"] = "gzip"
        resp.headers["Cache-Control"] = "private, no-cache, must-revalidate"
        return resp
    if os.path.exists(RAW_FALLBACK):
        return send_file(RAW_FALLBACK, mimetype="application/geo+json")
    abort(404)


# ---------- admin: mint / manage client links ----------
@app.route("/admin")
def admin():
    if not is_admin():
        return redirect(url_for("login"))
    data = load_codes()
    for c in data["codes"]:
        c["active"] = code_active(c)
    return render_template("admin.html", codes=data["codes"], host=request.host_url.rstrip("/"))


@app.route("/admin/create", methods=["POST"])
def admin_create():
    if not is_admin():
        abort(403)
    label = request.form.get("label", "").strip() or "Client"
    days = request.form.get("days", "30").strip()
    data = load_codes()
    code = secrets.token_urlsafe(8)
    expires = None
    if days.lower() != "never":
        try:
            expires = (now_utc() + timedelta(days=int(days))).isoformat()
        except ValueError:
            expires = (now_utc() + timedelta(days=30)).isoformat()
    data["codes"].append({
        "code": code,
        "label": label,
        "created": now_utc().isoformat(),
        "expires": expires,
        "revoked": False,
    })
    save_codes(data)
    return redirect(url_for("admin"))


@app.route("/admin/revoke", methods=["POST"])
def admin_revoke():
    if not is_admin():
        abort(403)
    code = request.form.get("code", "")
    data = load_codes()
    for c in data["codes"]:
        if c["code"] == code:
            c["revoked"] = True
    save_codes(data)
    return redirect(url_for("admin"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8770))
    app.run(host="0.0.0.0", port=port, debug=True)

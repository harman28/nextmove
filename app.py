import os
import re
import sqlite3
from datetime import datetime, timezone

from flask import (
    Flask, g, request, session, redirect, url_for, render_template,
    send_from_directory,
)
from werkzeug.utils import secure_filename
from PIL import Image, ImageOps

DATA_DIR = os.environ.get("DATA_DIR", "./data")
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")
DB_PATH = os.path.join(DATA_DIR, "nextmove.db")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme")
ALLOWED_PHOTO_EXTS = {"jpg", "jpeg", "png", "webp"}
MAX_PHOTO_BYTES = 8 * 1024 * 1024
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-insecure-key")

os.makedirs(UPLOADS_DIR, exist_ok=True)

DEFAULT_SETTINGS = {
    "coach_name": "Akos",
    "tagline": "[Add a short tagline here — a line that sums up your coaching in one sentence.]",
    "bio_text": "[This is your “why me”. Write a few sentences here about why you coach chess and what students can expect from working with you.]",
    "photo_filename": "",
    "photo_version": "0",
    "adults_intro": "[Write a short intro here for adults who want to get serious about chess and could use some guidance.]",
    "kids_intro": "[Write a short intro here for parents who want their kids to take up chess or get better at it.]",
    "parent_child_note": "Akos is exploring a class for parents and kids to learn together — it hasn’t been tried yet, so get in touch if that sounds interesting and he’ll keep you posted.",
    "first_lesson_free_text": "Your first private lesson is free — a low-pressure way to see if it’s a good fit.",
    "contact_intro": "[Add a short line here inviting people to reach out.]",
    "facebook_url": "",
    "instagram_url": "",
}

DEFAULT_PACKAGES = [
    (
        "Chess Fundamentals",
        "4 lessons of 60 minutes each, plus homework between sessions.",
        "[Add more detail here: what’s covered in each session, and who it’s best suited for.]",
    ),
    (
        "Play Your First Tournament",
        "Akos guides you step by step, all the way to your first tournament.",
        "[Add more detail here: how many sessions this includes and what it covers.]",
    ),
    (
        "Tournament Refresher",
        "2 sessions of 90 minutes — one before your tournament, one after — to help you get the most out of it.",
        "[Add more detail here if you’d like, e.g. what happens in each session.]",
    ),
]

DEFAULT_FAQS = [
    (
        "Is the first lesson really free?",
        "Yes — your first private lesson with Akos is free, so you can see if it’s the right fit before committing to anything.",
    ),
    (
        "Where do lessons take place?",
        "There’s no fixed location yet. Once you get in touch, you and Akos will figure out what works best — online or in person.",
    ),
    (
        "Do you teach both kids and adults?",
        "Yes. Akos particularly enjoys one-on-one coaching, where lessons are shaped entirely around the student, whatever their age.",
    ),
]


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS packages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            summary TEXT NOT NULL,
            details TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS testimonials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quote TEXT NOT NULL,
            author TEXT NOT NULL,
            context TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS faqs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS inquiries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            track TEXT NOT NULL DEFAULT 'general',
            message TEXT NOT NULL,
            created_at TEXT NOT NULL,
            is_read INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    db.commit()

    existing = {row["key"] for row in db.execute("SELECT key FROM settings")}
    for key, value in DEFAULT_SETTINGS.items():
        if key not in existing:
            db.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (key, value))

    if db.execute("SELECT COUNT(*) AS n FROM packages").fetchone()["n"] == 0:
        for i, (title, summary, details) in enumerate(DEFAULT_PACKAGES):
            db.execute(
                "INSERT INTO packages (title, summary, details, sort_order) VALUES (?, ?, ?, ?)",
                (title, summary, details, i),
            )

    if db.execute("SELECT COUNT(*) AS n FROM faqs").fetchone()["n"] == 0:
        for i, (question, answer) in enumerate(DEFAULT_FAQS):
            db.execute(
                "INSERT INTO faqs (question, answer, sort_order) VALUES (?, ?, ?)",
                (question, answer, i),
            )

    db.commit()
    db.close()


def get_settings():
    db = get_db()
    rows = db.execute("SELECT key, value FROM settings").fetchall()
    return {row["key"]: row["value"] for row in rows}


def list_items(table, active_only=True):
    db = get_db()
    q = f"SELECT * FROM {table}"
    if active_only:
        q += " WHERE active = 1"
    q += " ORDER BY sort_order ASC, id ASC"
    return db.execute(q).fetchall()


def move_item(table, item_id, direction):
    db = get_db()
    rows = db.execute(f"SELECT id, sort_order FROM {table} ORDER BY sort_order ASC, id ASC").fetchall()
    ids = [r["id"] for r in rows]
    if item_id not in ids:
        return
    idx = ids.index(item_id)
    swap_idx = idx - 1 if direction == "up" else idx + 1
    if swap_idx < 0 or swap_idx >= len(rows):
        return
    a, b = rows[idx], rows[swap_idx]
    db.execute(f"UPDATE {table} SET sort_order = ? WHERE id = ?", (b["sort_order"], a["id"]))
    db.execute(f"UPDATE {table} SET sort_order = ? WHERE id = ?", (a["sort_order"], b["id"]))
    db.commit()


def next_sort_order(table):
    db = get_db()
    row = db.execute(f"SELECT MAX(sort_order) AS m FROM {table}").fetchone()
    return (row["m"] or 0) + 1


@app.context_processor
def inject_settings():
    return {"settings": get_settings()}


# ---------------------------------------------------------------- public --

@app.route("/")
def home():
    return render_template(
        "index.html",
        packages=list_items("packages"),
        testimonials=list_items("testimonials"),
        faqs=list_items("faqs"),
        sent=request.args.get("sent"),
        default_track=request.args.get("track", "general"),
        active_page="home",
    )


@app.route("/adults")
def adults():
    return render_template(
        "adults.html",
        packages=list_items("packages"),
        sent=request.args.get("sent"),
        active_page="adults",
    )


@app.route("/kids")
def kids():
    return render_template(
        "kids.html",
        packages=list_items("packages"),
        sent=request.args.get("sent"),
        active_page="kids",
    )


@app.route("/uploads/<path:filename>")
def uploads(filename):
    return send_from_directory(UPLOADS_DIR, filename)


@app.route("/api/contact", methods=["POST"])
def contact():
    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip()
    message = (request.form.get("message") or "").strip()
    track = (request.form.get("track") or "general").strip()
    next_url = request.form.get("next") or url_for("home")

    if not name or not message or not EMAIL_RE.match(email):
        return redirect(next_url + "?sent=error#contact")

    db = get_db()
    db.execute(
        "INSERT INTO inquiries (name, email, track, message, created_at) VALUES (?, ?, ?, ?, ?)",
        (name, email, track, message, datetime.now(timezone.utc).isoformat()),
    )
    db.commit()
    return redirect(next_url + "?sent=ok#contact")


# ------------------------------------------------------------------ admin --

@app.route("/admin")
def admin_root():
    if session.get("admin"):
        return redirect(url_for("admin_dashboard"))
    return redirect(url_for("admin_login"))


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect(url_for("admin_dashboard"))
        error = "That password isn't right."
    return render_template("admin_login.html", error=error)


@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("admin_login"))


@app.route("/admin/dashboard")
def admin_dashboard():
    if not session.get("admin"):
        return redirect(url_for("admin_login"))
    db = get_db()
    unread = db.execute("SELECT COUNT(*) AS n FROM inquiries WHERE is_read = 0").fetchone()["n"]
    return render_template(
        "admin.html",
        packages=list_items("packages", active_only=False),
        testimonials=list_items("testimonials", active_only=False),
        faqs=list_items("faqs", active_only=False),
        inquiries=get_db().execute("SELECT * FROM inquiries ORDER BY created_at DESC").fetchall(),
        unread=unread,
    )


def admin_guard():
    if not session.get("admin"):
        return redirect(url_for("admin_login"))
    return None


@app.route("/admin/settings", methods=["POST"])
def admin_settings():
    guard = admin_guard()
    if guard:
        return guard
    db = get_db()
    fields = [
        "coach_name", "tagline", "bio_text", "adults_intro", "kids_intro",
        "parent_child_note", "first_lesson_free_text", "contact_intro",
        "facebook_url", "instagram_url",
    ]
    for field in fields:
        if field in request.form:
            db.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (field, request.form.get(field, "").strip()),
            )
    db.commit()
    return redirect(url_for("admin_dashboard") + "#profile")


@app.route("/admin/photo", methods=["POST"])
def admin_photo():
    guard = admin_guard()
    if guard:
        return guard
    file = request.files.get("photo")
    if not file or not file.filename:
        return redirect(url_for("admin_dashboard") + "#profile")
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_PHOTO_EXTS:
        return redirect(url_for("admin_dashboard") + "#profile")

    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size > MAX_PHOTO_BYTES:
        return redirect(url_for("admin_dashboard") + "#profile")

    image = Image.open(file)
    image = ImageOps.exif_transpose(image)
    image = image.convert("RGB")
    image.thumbnail((900, 900))
    filename = secure_filename("profile.jpg")
    image.save(os.path.join(UPLOADS_DIR, filename), "JPEG", quality=88)

    db = get_db()
    version = int(get_settings().get("photo_version", "0")) + 1
    for key, value in (("photo_filename", filename), ("photo_version", str(version))):
        db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
    db.commit()
    return redirect(url_for("admin_dashboard") + "#profile")


def handle_item_form(table, extra_fields):
    guard = admin_guard()
    if guard:
        return guard
    db = get_db()
    values = {f: (request.form.get(f) or "").strip() for f in extra_fields}
    columns = ", ".join(extra_fields)
    placeholders = ", ".join("?" for _ in extra_fields)
    db.execute(
        f"INSERT INTO {table} ({columns}, sort_order) VALUES ({placeholders}, ?)",
        (*values.values(), next_sort_order(table)),
    )
    db.commit()
    return redirect(url_for("admin_dashboard") + f"#{table}")


def handle_item_action(table, item_id, extra_fields):
    guard = admin_guard()
    if guard:
        return guard
    db = get_db()
    action = request.form.get("action")
    if action == "save":
        assignments = ", ".join(f"{f} = ?" for f in extra_fields)
        values = [(request.form.get(f) or "").strip() for f in extra_fields]
        db.execute(f"UPDATE {table} SET {assignments} WHERE id = ?", (*values, item_id))
        db.commit()
    elif action in ("up", "down"):
        move_item(table, item_id, action)
    elif action == "toggle":
        db.execute(f"UPDATE {table} SET active = 1 - active WHERE id = ?", (item_id,))
        db.commit()
    elif action == "delete":
        db.execute(f"DELETE FROM {table} WHERE id = ?", (item_id,))
        db.commit()
    return redirect(url_for("admin_dashboard") + f"#{table}")


@app.route("/admin/packages", methods=["POST"])
def admin_packages_add():
    return handle_item_form("packages", ["title", "summary", "details"])


@app.route("/admin/packages/<int:item_id>", methods=["POST"])
def admin_packages_item(item_id):
    return handle_item_action("packages", item_id, ["title", "summary", "details"])


@app.route("/admin/testimonials", methods=["POST"])
def admin_testimonials_add():
    return handle_item_form("testimonials", ["quote", "author", "context"])


@app.route("/admin/testimonials/<int:item_id>", methods=["POST"])
def admin_testimonials_item(item_id):
    return handle_item_action("testimonials", item_id, ["quote", "author", "context"])


@app.route("/admin/faqs", methods=["POST"])
def admin_faqs_add():
    return handle_item_form("faqs", ["question", "answer"])


@app.route("/admin/faqs/<int:item_id>", methods=["POST"])
def admin_faqs_item(item_id):
    return handle_item_action("faqs", item_id, ["question", "answer"])


@app.route("/admin/inquiries/<int:item_id>", methods=["POST"])
def admin_inquiries_item(item_id):
    guard = admin_guard()
    if guard:
        return guard
    db = get_db()
    action = request.form.get("action")
    if action == "read":
        db.execute("UPDATE inquiries SET is_read = 1 WHERE id = ?", (item_id,))
        db.commit()
    elif action == "delete":
        db.execute("DELETE FROM inquiries WHERE id = ?", (item_id,))
        db.commit()
    return redirect(url_for("admin_dashboard") + "#inquiries")


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5400))
    app.run(host="0.0.0.0", port=port, debug=False)

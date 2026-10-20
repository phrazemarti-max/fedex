
import os
import secrets
import sqlite3
import string
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "shipments.db"

# Set SHIPMENTS_ADMIN_KEY in your environment before using admin endpoints.
ADMIN_KEY = os.environ.get("SHIPMENTS_ADMIN_KEY", "")

SHIPMENT_STATUSES = {
    "Shipment Created",
    "Picked Up",
    "In Transit",
    "Arrived at Facility",
    "Out for Delivery",
    "Delivered",
    "Delivery Exception",
    "On Hold",
}


def current_time():
    return datetime.now(timezone.utc).isoformat()


def get_db():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS shipments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tracking_number TEXT UNIQUE NOT NULL,
                sender_name TEXT NOT NULL,
                receiver_name TEXT NOT NULL,
                origin TEXT NOT NULL,
                destination TEXT NOT NULL,
                status TEXT NOT NULL,
                current_location TEXT NOT NULL,
                description TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                estimated_delivery TEXT DEFAULT ''
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS tracking_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tracking_number TEXT NOT NULL,
                status TEXT NOT NULL,
                location TEXT NOT NULL,
                details TEXT DEFAULT '',
                event_time TEXT NOT NULL,
                FOREIGN KEY (tracking_number)
                    REFERENCES shipments (tracking_number)
            )
        """)


def error(message, code=400):
    return jsonify({"success": False, "error": message}), code


def require_admin():
    supplied_key = request.headers.get("X-Admin-Key", "")

    if not ADMIN_KEY:
        return error(
            "Admin access is not configured. Set SHIPMENTS_ADMIN_KEY first.",
            503,
        )

    if not secrets.compare_digest(supplied_key, ADMIN_KEY):
        return error("Invalid admin key.", 401)

    return None


def generate_tracking_number(db):
    alphabet = string.ascii_uppercase + string.digits

    for _ in range(10):
        tracking = "JP" + "".join(
            secrets.choice(alphabet) for _ in range(12)
        )

        existing = db.execute(
            "SELECT 1 FROM shipments WHERE tracking_number = ?",
            (tracking,),
        ).fetchone()

        if not existing:
            return tracking

    raise RuntimeError("Could not generate a unique tracking number.")


def record_event(db, tracking, status, location, details=""):
    db.execute("""
        INSERT INTO tracking_events (
            tracking_number, status, location, details, event_time
        )
        VALUES (?, ?, ?, ?, ?)
    """, (tracking, status, location, details, current_time()))


def shipment_to_dict(row):
    return dict(row)


@app.route("/")
def home():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "success": True,
        "message": "Shipping backend is running.",
        "time": current_time(),
    })


@app.route("/api/track/<tracking_number>", methods=["GET"])
def track_shipment(tracking_number):
    tracking_number = tracking_number.strip().upper()

    with get_db() as db:
        shipment = db.execute(
            "SELECT * FROM shipments WHERE tracking_number = ?",
            (tracking_number,),
        ).fetchone()

        if not shipment:
            return error("Shipment not found. Check your tracking number.", 404)

        events = db.execute("""
            SELECT status, location, details, event_time
            FROM tracking_events
            WHERE tracking_number = ?
            ORDER BY id DESC
        """, (tracking_number,)).fetchall()

        result = shipment_to_dict(shipment)
        result["history"] = [dict(event) for event in events]

    return jsonify({"success": True, "shipment": result})


@app.route("/api/shipments", methods=["POST"])
def create_shipment():
    denied = require_admin()
    if denied:
        return denied

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return error("Send shipment details as JSON.")

    required = [
        "sender_name",
        "receiver_name",
        "origin",
        "destination",
    ]

    for field in required:
        if not isinstance(data.get(field), str) or not data[field].strip():
            return error(f"'{field}' is required.")

    sender = data["sender_name"].strip()
    receiver = data["receiver_name"].strip()
    origin = data["origin"].strip()
    destination = data["destination"].strip()
    description = str(data.get("description", "")).strip()
    estimated_delivery = str(data.get("estimated_delivery", "")).strip()

    status = "Shipment Created"
    location = origin

    try:
        with get_db() as db:
            tracking = generate_tracking_number(db)

            db.execute("""
                INSERT INTO shipments (
                    tracking_number, sender_name, receiver_name,
                    origin, destination, status, current_location,
                    description, created_at, updated_at,
                    estimated_delivery
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                tracking, sender, receiver, origin, destination,
                status, location, description, current_time(),
                current_time(), estimated_delivery,
            ))

            record_event(
                db, tracking, status, location,
                "Shipment record created."
            )

    except sqlite3.Error:
        app.logger.exception("Database error creating shipment")
        return error("Could not save shipment.", 500)

    return jsonify({
        "success": True,
        "message": "Shipment created successfully.",
        "tracking_number": tracking,
    }), 201


@app.route("/api/shipments", methods=["GET"])
def list_shipments():
    denied = require_admin()
    if denied:
        return denied

    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM shipments ORDER BY id DESC"
        ).fetchall()

    return jsonify({
        "success": True,
        "shipments": [shipment_to_dict(row) for row in rows],
    })


@app.route(
    "/api/shipments/<tracking_number>/status",
    methods=["PATCH"],
)
def update_shipment(tracking_number):
    denied = require_admin()
    if denied:
        return denied

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return error("Send update details as JSON.")

    status = data.get("status")
    location = data.get("current_location")
    details = data.get("details", "")

    if not isinstance(status, str) or status not in SHIPMENT_STATUSES:
        return error(
            "Invalid status. Choose one of the supported shipment statuses."
        )

    if not isinstance(location, str) or not location.strip():
        return error("A current_location is required.")

    if not isinstance(details, str):
        return error("Details must be text.")

    tracking_number = tracking_number.strip().upper()
    location = location.strip()

    with get_db() as db:
        shipment = db.execute(
            "SELECT id FROM shipments WHERE tracking_number = ?",
            (tracking_number,),
        ).fetchone()

        if not shipment:
            return error("Shipment not found.", 404)

        db.execute("""
            UPDATE shipments
            SET status = ?, current_location = ?, updated_at = ?
            WHERE tracking_number = ?
        """, (status, location, current_time(), tracking_number))

        record_event(db, tracking_number, status, location, details.strip())

    return jsonify({
        "success": True,
        "message": "Shipment status updated.",
        "tracking_number": tracking_number,
        "status": status,
        "current_location": location,
    })


if __name__ == "__main__":
    init_db()
    print("Shipping backend is ready.")
    print("Website: http://127.0.0.1:5000")
    print("Health check: http://127.0.0.1:5000/api/health")
    app.run(host="127.0.0.1", port=5000, debug=False)

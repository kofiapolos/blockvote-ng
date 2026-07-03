"""
Blockchain Voting System — Flask Application
Development of a Blockchain Voting System in Nigeria
Final Year Project
"""

import os
import json
import secrets
import logging
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import (
    Flask,
    render_template,
    request,
    session,
    redirect,
    url_for,
    jsonify,
    flash,
)
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", secrets.token_hex(32))

# ---------------------------------------------------------------------------
# Candidate photo uploads
# ---------------------------------------------------------------------------
UPLOAD_FOLDER = Path(__file__).parent / "static" / "uploads"
UPLOAD_FOLDER.mkdir(exist_ok=True)
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _save_candidate_photo(file_obj, candidate_id):
    """Overwrite any existing photo for this candidate with the new upload."""
    for ext in ALLOWED_EXTENSIONS:
        old = UPLOAD_FOLDER / f"candidate_{candidate_id}.{ext}"
        if old.exists():
            old.unlink()
    ext = file_obj.filename.rsplit(".", 1)[1].lower()
    file_obj.save(UPLOAD_FOLDER / f"candidate_{candidate_id}.{ext}")


def get_candidate_image(candidate_id):
    """Return the URL path to a candidate's photo, or None."""
    for ext in ["jpg", "jpeg", "png", "webp", "gif"]:
        if (UPLOAD_FOLDER / f"candidate_{candidate_id}.{ext}").exists():
            return f"/static/uploads/candidate_{candidate_id}.{ext}"
    return None


def build_image_map(candidates):
    return {c["id"]: get_candidate_image(c["id"]) for c in candidates}


# ---------------------------------------------------------------------------
# Load voter registry (simulated BVAS database)
# ---------------------------------------------------------------------------
VOTERS_FILE = Path(__file__).parent / "voters.json"
with open(VOTERS_FILE) as f:
    _voter_data = json.load(f)

VOTER_REGISTRY: dict[str, dict] = _voter_data

# ---------------------------------------------------------------------------
# Blockchain initialisation (at startup)
# ---------------------------------------------------------------------------
import blockchain as bc

_blockchain_ready = False
_init_error = None

def _init():
    global _blockchain_ready, _init_error
    try:
        addr = bc.init_blockchain()
        logger.info("Blockchain ready. Contract: %s", addr)
        _blockchain_ready = True
    except Exception as exc:
        _init_error = str(exc)
        logger.error("Blockchain init failed: %s", exc)

_init()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "bvas_id" not in session:
            flash("Please authenticate with your BVAS ID to continue.", "warning")
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("is_admin"):
            flash("Admin access required.", "danger")
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    if "bvas_id" in session:
        return redirect(url_for("vote"))
    return render_template("index.html", blockchain_ready=_blockchain_ready, init_error=_init_error)


@app.route("/authenticate", methods=["POST"])
def authenticate():
    """
    ALGORITHM STEP: PROMPT User for Authentication Token (Simulated BVAS ID)
    IF Authentication == VALID THEN → proceed to ballot
    """
    bvas_id = request.form.get("bvas_id", "").strip().upper()

    if not bvas_id:
        flash("Please enter your BVAS ID.", "danger")
        return redirect(url_for("index"))

    voter = VOTER_REGISTRY.get(bvas_id)
    if not voter:
        flash("Authentication Failed: BVAS ID not found in voter registry.", "danger")
        logger.warning("Failed auth attempt for BVAS ID: %s", bvas_id)
        return redirect(url_for("index"))

    # Generate unique session salt for cryptographic anonymization
    session_salt = secrets.token_hex(16)

    session.clear()
    session["bvas_id"] = bvas_id
    session["voter_name"] = voter["name"]
    session["voter_state"] = voter["state"]
    session["voter_lga"] = voter["lga"]
    session["voter_ward"] = voter["ward"]
    session["session_salt"] = session_salt
    session["auth_time"] = datetime.utcnow().isoformat()

    # Check if already voted (on-chain verification)
    try:
        already_voted = bc.check_voter_status(bvas_id, session_salt)
        session["already_voted"] = already_voted
    except Exception:
        session["already_voted"] = False

    logger.info("Voter authenticated: %s (%s)", voter["name"], voter["state"])
    return redirect(url_for("vote"))


@app.route("/vote")
@login_required
def vote():
    """
    ALGORITHM STEP: DISPLAY Digital Ballot Paper (Candidate List)
    """
    if not _blockchain_ready:
        return render_template("error.html", message="Blockchain is still initializing. Please wait.")

    election_status = bc.get_election_status()
    candidates = bc.get_candidates()

    return render_template(
        "vote.html",
        candidates=candidates,
        image_map=build_image_map(candidates),
        voter_name=session.get("voter_name"),
        voter_state=session.get("voter_state"),
        voter_lga=session.get("voter_lga"),
        voter_ward=session.get("voter_ward"),
        election_status=election_status,
        already_voted=session.get("already_voted", False),
    )


@app.route("/cast-vote", methods=["POST"])
@login_required
def cast_vote():
    """
    ALGORITHM STEP: CAPTURE Voter_Choice → COMPUTE SHA-256 hash →
    CONSTRUCT & SIGN Web3 Transaction → SEND to Smart Contract
    """
    bvas_id = session["bvas_id"]
    session_salt = session["session_salt"]
    candidate_id_str = request.form.get("candidate_id", "")

    if not candidate_id_str or not candidate_id_str.isdigit():
        flash("Invalid selection. Please choose a candidate.", "danger")
        return redirect(url_for("vote"))

    candidate_id = int(candidate_id_str)

    election_status = bc.get_election_status()
    if not election_status["is_open"]:
        flash("The election is currently closed. Votes are no longer accepted.", "warning")
        return redirect(url_for("vote"))

    # Execute blockchain transaction (per algorithm)
    result = bc.cast_vote(bvas_id, candidate_id, session_salt)

    if result["success"]:
        session["already_voted"] = True
        session["last_tx"] = result
        logger.info(
            "Vote cast: voter=%s candidate=%d tx=%s block=%s",
            result["voter_hash"][:12] + "...",
            candidate_id,
            result["tx_hash"][:12] + "...",
            result["block_number"],
        )
        return render_template("success.html", result=result, voter_name=session.get("voter_name"))
    else:
        flash(result["message"], "danger")
        return redirect(url_for("vote"))


@app.route("/results")
def results():
    """Live election results from the blockchain."""
    if not _blockchain_ready:
        return render_template("error.html", message="Blockchain not ready.")

    candidates = bc.get_candidates()
    election_status = bc.get_election_status()
    total_votes = election_status["total_votes"]

    for c in candidates:
        c["percentage"] = round((c["votes"] / total_votes * 100), 1) if total_votes > 0 else 0

    sorted_candidates = sorted(candidates, key=lambda x: x["votes"], reverse=True)

    return render_template(
        "results.html",
        candidates=sorted_candidates,
        image_map=build_image_map(candidates),
        election_status=election_status,
        total_votes=total_votes,
    )


@app.route("/admin", methods=["GET", "POST"])
def admin():
    """Admin dashboard: blockchain info, candidate management, transactions, election control."""
    if request.method == "POST":
        pin = request.form.get("pin", "")
        if pin == "INEC2023":
            session["is_admin"] = True
        else:
            flash("Invalid admin PIN.", "danger")
            return redirect(url_for("admin"))

    if not session.get("is_admin"):
        return render_template("admin_login.html")

    if not _blockchain_ready:
        return render_template("error.html", message="Blockchain not ready.")

    action = request.args.get("action")
    if action == "close":
        bc.toggle_election(False)
        flash("Election closed on-chain.", "success")
    elif action == "open":
        bc.toggle_election(True)
        flash("Election reopened on-chain.", "success")

    all_candidates  = bc.get_all_candidates()
    election_status = bc.get_election_status()
    transactions    = bc.get_blockchain_transactions()

    cand_map = {c["id"]: c for c in all_candidates}
    for tx in transactions:
        cand = cand_map.get(tx["candidate_id"], {})
        tx["candidate_name"]  = cand.get("name", "Unknown")
        tx["candidate_party"] = cand.get("party", "")

    return render_template(
        "admin.html",
        candidates=all_candidates,
        image_map=build_image_map(all_candidates),
        election_status=election_status,
        transactions=transactions,
    )


@app.route("/admin/candidates/add", methods=["POST"])
def admin_add_candidate():
    if not session.get("is_admin"):
        return redirect(url_for("admin"))
    name  = request.form.get("name", "").strip()
    party = request.form.get("party", "").strip()
    photo = request.files.get("photo")
    if not name or not party:
        flash("Candidate name and party are required.", "danger")
    else:
        symbol = party.split()[0].upper()
        result = bc.add_candidate(name, party, symbol)
        if result["success"]:
            new_id = result["id"]
            if photo and photo.filename and allowed_file(photo.filename):
                _save_candidate_photo(photo, new_id)
            flash(f"Candidate '{name}' added on-chain (ID #{new_id}).", "success")
        else:
            flash(f"Failed to add candidate: {result.get('message')}", "danger")
    return redirect(url_for("admin") + "#candidates")


@app.route("/admin/candidates/edit", methods=["POST"])
def admin_edit_candidate():
    if not session.get("is_admin"):
        return redirect(url_for("admin"))
    candidate_id = request.form.get("candidate_id", "")
    name         = request.form.get("name", "").strip()
    party        = request.form.get("party", "").strip()
    symbol       = request.form.get("symbol", "Photo").strip()
    photo        = request.files.get("photo")
    if not candidate_id.isdigit() or not name or not party:
        flash("Candidate name and party are required.", "danger")
    else:
        cid = int(candidate_id)
        result = bc.update_candidate(cid, name, party, symbol)
        if result["success"]:
            if photo and photo.filename and allowed_file(photo.filename):
                _save_candidate_photo(photo, cid)
            flash(f"Candidate #{candidate_id} updated on-chain.", "success")
        else:
            flash(f"Update failed: {result.get('message')}", "danger")
    return redirect(url_for("admin") + "#candidates")


@app.route("/admin/candidates/toggle/<int:candidate_id>")
def admin_toggle_candidate(candidate_id):
    if not session.get("is_admin"):
        return redirect(url_for("admin"))
    result = bc.toggle_candidate(candidate_id)
    if result["success"]:
        state = "disabled" if result["disabled"] else "re-enabled"
        flash(f"Candidate #{candidate_id} {state} on-chain.", "success")
    else:
        flash(f"Toggle failed: {result.get('message')}", "danger")
    return redirect(url_for("admin") + "#candidates")


@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("index"))


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))


@app.route("/api/results")
def api_results():
    """JSON endpoint for live results polling."""
    if not _blockchain_ready:
        return jsonify({"error": "Blockchain not ready"}), 503
    candidates = bc.get_candidates()
    status = bc.get_election_status()
    return jsonify({"candidates": candidates, "status": status})


@app.route("/api/status")
def api_status():
    return jsonify({
        "blockchain_ready": _blockchain_ready,
        "error": _init_error,
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=False)

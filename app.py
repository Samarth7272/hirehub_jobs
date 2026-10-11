import os
import secrets
from sqlalchemy import inspect, text
from dotenv import load_dotenv
from authlib.integrations.flask_client import OAuth
from datetime import datetime, timedelta
from urllib.parse import quote

from flask import (
    Flask, abort, flash, redirect, render_template, request, session,
    url_for
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------
load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY") or secrets.token_hex(32)

database_url = os.getenv("DATABASE_URL", "").strip()
if database_url:
    # Neon often supplies postgres:// or postgresql:// URLs.
    # SQLAlchemy 2.x uses the psycopg 3 driver for postgresql+psycopg://.
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace(
            "postgresql://", "postgresql+psycopg://", 1
        )
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
else:
    # Local development uses SQLite.
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///hirehub.db"

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}

db = SQLAlchemy(app)
oauth = OAuth(app)

oauth.register(
    name="google",
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

UPI_ID = os.getenv("UPI_ID", "").strip()
UPI_NAME = os.getenv("UPI_NAME", "HireHub").strip()
PAY_MINUTES = 8

# Plan tuple: (display name, price in INR, duration in days)
PLANS = {
    "1w": ("1 Week", 139, 7),
    "1m": ("1 Month", 279, 30),
    "3m": ("3 Months", 499, 90),
    "6m": ("6 Months", 649, 180),
    "1y": ("1 Year", 749, 365),
}

# ---------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    pw = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    premium_until = db.Column(db.DateTime, nullable=True)

    orders = db.relationship("Order", backref="user", lazy=True)
    reviews = db.relationship("Review", backref="user", lazy=True)

    @property
    def premium(self):
        return bool(self.premium_until and self.premium_until > datetime.utcnow())


class Job(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    company = db.Column(db.String(120), nullable=False)
    location = db.Column(db.String(120), default="Remote")
    level = db.Column(db.String(60), default="Fresher")
    salary_month = db.Column(db.Integer, nullable=True)
    source = db.Column(db.String(60), default="Manual")
    url = db.Column(db.String(500), nullable=False)
    sample = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    plan = db.Column(db.String(20), nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), default="pending", nullable=False)
    utr = db.Column(db.String(12), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    expires = db.Column(db.DateTime, nullable=False)


class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    text = db.Column(db.String(400), nullable=False)
    photo = db.Column(db.String(300), nullable=True)
    approved = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


# ---------------------------------------------------------------------
# Demo job sources and initial listings
# ---------------------------------------------------------------------
SRC = {
    "Ashby": "https://jobs.ashbyhq.com/",
    "LinkedIn": "https://www.linkedin.com/jobs/",
    "Indeed": "https://in.indeed.com/",
    "Naukri": "https://www.naukri.com/",
    "Wellfound": "https://wellfound.com/jobs",
    "Internshala": "https://internshala.com/",
    "Manual": "https://www.linkedin.com/jobs/",
}

DEMO = [
    ("Graduate Software Engineer", "Demo Co", "Bengaluru", "Fresher", 35000, "LinkedIn"),
    ("Python Developer Trainee", "Demo Co", "Remote", "Fresher", 30000, "Indeed"),
    ("Associate QA Engineer", "Demo Co", "Pune", "Fresher", 28000, "Naukri"),
    ("Backend Developer Intern", "Demo Co", "Remote", "Internship", 18000, "Internshala"),
    ("Junior Full Stack Developer", "Demo Co", "Noida", "Fresher", 32000, "Wellfound"),
    ("Software Engineer Intern", "Demo Co", "Remote", "Internship", 20000, "Ashby"),
]


# ---------------------------------------------------------------------
# Helpers and access control
# ---------------------------------------------------------------------
def me():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return db.session.get(User, user_id)


def login_required(view):
    from functools import wraps

    @wraps(view)
    def wrapped(*args, **kwargs):
        if not me():
            flash("Please log in first.")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    from functools import wraps

    @wraps(view)
    def wrapped(*args, **kwargs):
        user = me()
        if not user:
            flash("Please log in first.")
            return redirect(url_for("login", next=request.path))
        if not user.is_admin:
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def sync_ashby():
    """Placeholder: import jobs only after implementing an allowed public API fetcher."""
    # No scraping is performed by this placeholder. Add a compliant, tested
    # Ashby API integration here if you have a specific company/job-board feed.
    return 0


# Make these values available to templates.
@app.context_processor
def inject_template_values():
    user = me()
    return {
        "me": user,
        "PLANS": PLANS,
        "UPI_ID": UPI_ID,
        "UPI_NAME": UPI_NAME,
    }


# ---------------------------------------------------------------------
# Public pages
# ---------------------------------------------------------------------
@app.route("/")
def index():
    query = request.args.get("q", "").strip()
    level = request.args.get("level", "All levels").strip()
    source = request.args.get("source", "").strip()

    jobs_query = Job.query

    if query:
        like = f"%{query}%"
        jobs_query = jobs_query.filter(
            db.or_(
                Job.title.ilike(like),
                Job.company.ilike(like),
                Job.location.ilike(like)
            )
        )

    if level and level != "All levels":
        jobs_query = jobs_query.filter(
            db.func.lower(db.func.trim(Job.level)) == level.lower()
        )

    if source and source != "All sources":
        jobs_query = jobs_query.filter_by(source=source)
    jobs = jobs_query.order_by(Job.created_at.desc()).all()
    sources = sorted({j.source for j in Job.query.all() if j.source})
    reviews = Review.query.filter_by(approved=True).order_by(
        Review.created_at.desc()
    ).all()

    return render_template(
        "index.html",
        jobs=jobs,
        sources=sources,
        reviews=reviews,
        total=len(Job.query.all()),
        lvl=level,
        q=query,
        source=source
    )

@app.route("/pricing")
def pricing():
    return render_template("pricing.html")


@app.route("/jobs/<int:jid>")
def job_detail(jid):
    job = db.session.get(Job, jid) or abort(404)
    return render_template("job.html", job=job)


# ---------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------
@app.route("/login/google")
def google_login():
    if not os.getenv("GOOGLE_CLIENT_ID") or not os.getenv("GOOGLE_CLIENT_SECRET"):
        flash("Google login is not configured. Check your .env file.")
        return redirect(url_for("login"))

    callback_url = url_for("google_callback", _external=True)
    return oauth.google.authorize_redirect(callback_url)


@app.route("/auth/callback")
def google_callback():
    try:
        token = oauth.google.authorize_access_token()
        info = token.get("userinfo")

        if not info or not info.get("email") or not info.get("email_verified"):
            flash("Google did not provide a verified email address.")
            return redirect(url_for("login"))

        email = info["email"].strip().lower()
        user = User.query.filter_by(email=email).first()

        if not user:
            user = User(
                name=(info.get("name") or email.split("@")[0])[:120],
                email=email,
                pw=generate_password_hash(secrets.token_urlsafe(32)),
            )
            db.session.add(user)
            db.session.commit()

        session.clear()
        session["user_id"] = user.id
        flash("Logged in with Google successfully.")
        return redirect(url_for("index"))

    except Exception:
        app.logger.exception("Google OAuth callback failed")
        flash("Google login failed. Check your OAuth settings and terminal.")
        return redirect(url_for("login"))
    
@app.route("/register", methods=["GET", "POST"])
def register():
    if me():
        return redirect(url_for("index"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()[:120]
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not name or not email or len(password) < 8:
            flash("Enter your name, valid email, and a password of at least 8 characters.")
            return render_template("auth.html", mode="register")

        if User.query.filter_by(email=email).first():
            flash("An account with this email already exists.")
            return render_template("auth.html", mode="register")

        user = User(name=name, email=email, pw=generate_password_hash(password))
        db.session.add(user)
        db.session.commit()
        session["user_id"] = user.id
        flash("Account created successfully.")
        return redirect(url_for("index"))

    return render_template("auth.html", mode="register")


@app.route("/login", methods=["GET", "POST"])
def login():
    if me():
        return redirect(url_for("index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()

        if not user or not check_password_hash(user.pw, password):
            flash("Incorrect email or password.")
            return render_template("auth.html", mode="login")

        session["user_id"] = user.id
        flash("Logged in successfully.")
        next_url = request.args.get("next", "")
        # Avoid open redirects: only accept local application paths.
        if next_url.startswith("/") and not next_url.startswith("//"):
            return redirect(next_url)
        return redirect(url_for("index"))

    return render_template("auth.html", mode="login")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.")
    return redirect(url_for("index"))


# ---------------------------------------------------------------------
# Premium purchase and UPI payment
# ---------------------------------------------------------------------
@app.route("/buy/<plan>", methods=["POST"])
@login_required
def buy(plan):
    if plan not in PLANS:
        abort(404)

    if not UPI_ID:
        flash("UPI payments are not configured yet. Please try again later.")
        return redirect(url_for("pricing"))

    order = Order(
        user_id=me().id,
        plan=plan,
        amount=PLANS[plan][1],
        expires=datetime.utcnow() + timedelta(minutes=PAY_MINUTES),
    )
    db.session.add(order)
    db.session.commit()
    return redirect(url_for("pay", oid=order.id))


@app.route("/pay/<int:oid>", methods=["GET", "POST"])
@login_required
def pay(oid):
    order = db.session.get(Order, oid)
    if not order or order.user_id != me().id:
        abort(404)

    now = datetime.utcnow()
    if order.status == "pending" and now >= order.expires:
        order.status = "expired"
        db.session.commit()

    if request.method == "POST":
        # Re-check expiration on the server; a browser timer alone is not secure.
        now = datetime.utcnow()
        if order.status != "pending" or now >= order.expires:
            if order.status == "pending":
                order.status = "expired"
                db.session.commit()
            flash("This payment window has expired. Please choose a plan again.")
            return redirect(url_for("pay", oid=order.id))

        utr = request.form.get("utr", "").strip()
        if not (utr.isdigit() and len(utr) == 12):
            flash("Enter the 12-digit UPI reference (UTR) number from your payment app.")
        elif Order.query.filter(
            Order.utr == utr,
            Order.status.in_(["submitted", "approved"])
        ).first():
            flash("This reference number was already used.")
        else:
            order.utr = utr
            order.status = "submitted"
            db.session.commit()
            flash("Payment submitted. Premium starts after an admin verifies the payment.")
        return redirect(url_for("pay", oid=order.id))

    upi = (
        f"upi://pay?pa={quote(UPI_ID)}"
        f"&pn={quote(UPI_NAME)}"
        f"&am={order.amount}&cu=INR"
        f"&tn={quote(f'HireHub order {order.id}')}"
    )
    seconds_left = max(0, int((order.expires - datetime.utcnow()).total_seconds()))
    return render_template(
        "pay.html", o=order, upi=upi, secs=seconds_left,
        PLANS=PLANS, UPI_ID=UPI_ID, UPI_NAME=UPI_NAME
    )


# ---------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------
@app.route("/review", methods=["POST"])
@login_required
def review():
    user = me()
    if not user.premium:
        abort(403)

    text = request.form.get("text", "").strip()[:400]
    photo = request.form.get("photo", "").strip()[:300]
    if text:
        db.session.add(Review(
            user_id=user.id,
            name=user.name,
            text=text,
            photo=photo if photo.startswith("https://") else None,
        ))
        db.session.commit()
        flash("Thanks! Your review will appear after admin approval.")
    return redirect(url_for("index"))


# ---------------------------------------------------------------------
# Admin dashboard and actions
# ---------------------------------------------------------------------
@app.route("/admin")
@admin_required
def admin():
    paid = (
        db.session.query(db.func.coalesce(db.func.sum(Order.amount), 0))
        .filter_by(status="approved").scalar()
    )
    return render_template(
        "admin.html",
        paid=paid,
        users=User.query.order_by(User.id.desc()).all(),
        orders=Order.query.order_by(Order.id.desc()).limit(200).all(),
        jobs=Job.query.order_by(Job.id.desc()).limit(100).all(),
        reviews=Review.query.order_by(Review.id.desc()).all(),
    )


@app.route("/admin/order/<int:oid>/<act>", methods=["POST"])
@admin_required
def admin_order(oid, act):
    order = db.session.get(Order, oid)
    if not order:
        abort(404)

    if act == "approve" and order.status == "submitted":
        user = order.user
        now = datetime.utcnow()
        current_until = user.premium_until or now
        user.premium_until = max(now, current_until) + timedelta(
            days=PLANS[order.plan][2]
        )
        order.status = "approved"
    elif act == "reject" and order.status in ("submitted", "pending"):
        order.status = "rejected"
    else:
        abort(400)

    db.session.commit()
    return redirect(url_for("admin"))


@app.route("/admin/user/<int:uid>/<act>", methods=["POST"])
@admin_required
def admin_user(uid, act):
    user = db.session.get(User, uid) or abort(404)
    if act == "grant":
        try:
            days = int(request.form.get("days", 30))
        except (TypeError, ValueError):
            abort(400)
        if days < 1 or days > 3650:
            abort(400)
        now = datetime.utcnow()
        user.premium_until = max(now, user.premium_until or now) + timedelta(days=days)
    elif act == "revoke":
        user.premium_until = None
    else:
        abort(400)

    db.session.commit()
    return redirect(url_for("admin"))


@app.route("/admin/job/add", methods=["POST"])
@admin_required
def admin_job_add():
    form = request.form
    title = form.get("title", "").strip()
    company = form.get("company", "").strip()
    url = form.get("url", "").strip()

    if not title or not company or not (
        url.startswith("https://") or url.startswith("http://")
    ):
        flash("Enter a job title, company, and a valid http/https application URL.")
        return redirect(url_for("admin"))

    salary = form.get("salary", "").strip()
    job = Job(
        title=title[:200],
        company=company[:120],
        location=form.get("location", "Remote").strip()[:120],
        level=form.get("level", "Fresher").strip()[:60],
        salary_month=int(salary) if salary.isdigit() else None,
        source=(form.get("source") or "Manual").strip()[:60],
        url=url[:500],
        sample=False,
    )
    db.session.add(job)
    db.session.commit()
    flash("Job added.")
    return redirect(url_for("admin"))


@app.route("/admin/job/<int:jid>/delete", methods=["POST"])
@admin_required
def admin_job_delete(jid):
    job = db.session.get(Job, jid)
    if job:
        db.session.delete(job)
        db.session.commit()
    return redirect(url_for("admin"))


@app.route("/admin/sync", methods=["POST"])
@admin_required
def admin_sync():
    count = sync_ashby()
    flash(f"{count} new jobs imported. The sync function is currently a placeholder.")
    return redirect(url_for("admin"))


@app.route("/admin/review/<int:rid>/<act>", methods=["POST"])
@admin_required
def admin_review(rid, act):
    item = db.session.get(Review, rid) or abort(404)
    if act == "approve":
        item.approved = True
    elif act == "delete":
        db.session.delete(item)
    else:
        abort(400)
    db.session.commit()
    return redirect(url_for("admin"))


# ---------------------------------------------------------------------
# Initial setup
# ---------------------------------------------------------------------
def bootstrap():
    inspector = inspect(db.engine)
    if "job" in inspector.get_table_names():
        columns = [c["name"] for c in inspector.get_columns("job")]
        if "created_at" not in columns:
            with db.engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE job ADD COLUMN created_at "
                    "TIMESTAMP WITHOUT TIME ZONE"
                ))
    db.create_all()

    admin_email = os.getenv("ADMIN_EMAIL", "").strip().lower()
    admin_password = os.getenv("ADMIN_PASSWORD", "")

    if admin_email and admin_password:
        existing_admin = User.query.filter_by(email=admin_email).first()
        if not existing_admin:
            db.session.add(User(
                name="Admin",
                email=admin_email,
                pw=generate_password_hash(admin_password),
                is_admin=True,
            ))

    if Job.query.count() == 0:
        for title, company, location, level, salary, source in DEMO:
            db.session.add(Job(
                title=title,
                company=company,
                location=location,
                level=level,
                salary_month=salary,
                source=source,
                url=SRC.get(source, SRC["Manual"]),
                sample=True,
            ))

    db.session.commit()


with app.app_context():
    bootstrap()


if __name__ == "__main__":
    # Use DEBUG=1 only for local development. Do not enable debug in production.
    app.run(
        host="127.0.0.1",
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("DEBUG") == "1",
    )
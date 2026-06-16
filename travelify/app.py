
import os
import json
import smtplib
import logging
from urllib.parse import quote

from datetime        import datetime, date
from io              import BytesIO
from email           import encoders  as email_encoders
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / '.env')

from flask import (
    Flask, render_template, request,
    redirect, url_for, flash,
    session, jsonify, send_file, abort
)
from flask_sqlalchemy import SQLAlchemy
from flask_login      import (
    LoginManager, UserMixin,
    login_user, logout_user,
    login_required, current_user
)
from flask_mail  import Mail, Message
from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

# ReportLab — for creating PDF files
from reportlab.lib.pagesizes import A4
from reportlab.lib            import colors
from reportlab.lib.styles     import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units      import cm
from reportlab.platypus       import (
    SimpleDocTemplate, Paragraph,
    Spacer, Table, TableStyle, HRFlowable
)
from reportlab.lib.enums import TA_CENTER


# ══════════════════════════════════════════════════════════
#  LOGGING  — so we can see what goes wrong
# ══════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
#  APP CONFIGURATION
# ══════════════════════════════════════════════════════════
app = Flask(__name__)

app.config['SECRET_KEY']              = os.getenv('SECRET_KEY', 'travelify-dev-secret-2026-change-me')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///travelify.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Mail settings
def _normalize_mail_password(raw: str) -> str:
    """Gmail App Passwords are 16 chars; users often paste with spaces."""
    return (raw or '').replace(' ', '').strip()


def _is_placeholder_mail(value: str, kind: str) -> bool:
    v = (value or '').strip().lower()
    if not v:
        return True
    if kind == 'user':
        return v.startswith('your_') or 'your@gmail' in v or 'your_gmail' in v
    return v.startswith('xxxx') or v == 'xxxxxxxxxxxxxxxxxxxx'


def _load_mail_config():
    user = os.getenv('MAIL_USERNAME', '').strip()
    pwd  = _normalize_mail_password(os.getenv('MAIL_PASSWORD', ''))
    sender = os.getenv('MAIL_DEFAULT_SENDER', user).strip() or user
    return {
        'MAIL_SERVER':         os.getenv('MAIL_SERVER', 'smtp.gmail.com'),
        'MAIL_PORT':           int(os.getenv('MAIL_PORT', 587)),
        'MAIL_USE_TLS':        os.getenv('MAIL_USE_TLS', 'True') == 'True',
        'MAIL_USE_SSL':        os.getenv('MAIL_USE_SSL', 'False') == 'True',
        'MAIL_USERNAME':       user,
        'MAIL_PASSWORD':       pwd,
        'MAIL_DEFAULT_SENDER': sender,
    }


def _mail_config_error() -> str | None:
    user = app.config.get('MAIL_USERNAME', '')
    pwd  = app.config.get('MAIL_PASSWORD', '')
    if _is_placeholder_mail(user, 'user'):
        return ('Gmail not configured: set MAIL_USERNAME in travelify/.env '
                'to your real Gmail address (e.g. you@gmail.com).')
    if _is_placeholder_mail(pwd, 'password'):
        return ('Gmail not configured: set MAIL_PASSWORD in travelify/.env '
                'to a 16-character Gmail App Password.')
    if 'gmail' in app.config.get('MAIL_SERVER', 'gmail') and len(pwd) != 16:
        return ('MAIL_PASSWORD should be a 16-character Gmail App Password '
                '(Google Account → Security → App Passwords).')
    return None


app.config.update(_load_mail_config())
ADMIN_EMAIL = app.config['MAIL_USERNAME'] or 'admin@travelify.in'

def _valid_maps_key(raw: str) -> str:
    """Ignore empty / placeholder values from .env.example."""
    key = (raw or '').strip()
    if not key or key.startswith('your_') or key in ('AIza...', 'xxxxxxxx'):
        return ''
    return key

GOOGLE_MAPS_KEY = _valid_maps_key(os.getenv('GOOGLE_MAPS_API_KEY', ''))

# Create extension objects
db    = SQLAlchemy(app)
mail  = Mail(app)
login = LoginManager(app)
login.login_view              = 'login_route'
login.login_message           = 'Please log in to access this page.'
login.login_message_category  = 'warning'


# ══════════════════════════════════════════════════════════
#  DATABASE MODELS  — the "filing cabinets" for our data
# ══════════════════════════════════════════════════════════

class User(UserMixin, db.Model):
    """
    One row = one registered person.
    UserMixin gives us handy is_authenticated, is_active, etc.
    """
    id         = db.Column(db.Integer,     primary_key=True)
    name       = db.Column(db.String(100), nullable=False)
    email      = db.Column(db.String(150), unique=True, nullable=False)
    password   = db.Column(db.String(256), nullable=False)     # stored as a hash, never plain text
    created_at = db.Column(db.DateTime,    default=datetime.utcnow)

    # Relationships — one user → many trips / expenses / bookmarks
    trips     = db.relationship('Trip',     backref='user', lazy=True, cascade='all,delete')
    expenses  = db.relationship('Expense',  backref='user', lazy=True, cascade='all,delete')
    bookmarks = db.relationship('Bookmark', backref='user', lazy=True, cascade='all,delete')

    @property
    def initials(self):
        parts = self.name.split()
        return (parts[0][0] + (parts[-1][0] if len(parts) > 1 else '')).upper()


class Trip(db.Model):
    """One row = one planned trip."""
    id             = db.Column(db.Integer,     primary_key=True)
    user_id        = db.Column(db.Integer,     db.ForeignKey('user.id'), nullable=False)
    destination    = db.Column(db.String(150), nullable=False)
    start_date     = db.Column(db.Date,        nullable=False)
    end_date       = db.Column(db.Date,        nullable=False)
    travellers     = db.Column(db.Integer,     default=1)
    budget_type    = db.Column(db.String(20),  default='basic')   # basic / luxury / premium
    hotel_name     = db.Column(db.String(200), default='')
    transport_type = db.Column(db.String(100), default='')
    notes          = db.Column(db.Text,        default='')
    estimated_cost = db.Column(db.Float,       default=0.0)
    created_at     = db.Column(db.DateTime,    default=datetime.utcnow)

    expenses = db.relationship('Expense', backref='trip', lazy=True, cascade='all,delete')

    @property
    def duration_days(self):
        return (self.end_date - self.start_date).days + 1

    @property
    def total_spent(self):
        return sum(e.amount for e in self.expenses)


class Expense(db.Model):
    """One row = one expense entry."""
    id           = db.Column(db.Integer,     primary_key=True)
    user_id      = db.Column(db.Integer,     db.ForeignKey('user.id'), nullable=False)
    trip_id      = db.Column(db.Integer,     db.ForeignKey('trip.id'), nullable=True)
    category     = db.Column(db.String(50),  nullable=False)   # food / hotel / transport / activities / misc
    description  = db.Column(db.String(200), nullable=False)
    amount       = db.Column(db.Float,       nullable=False)
    expense_date = db.Column(db.Date,        default=date.today)
    created_at   = db.Column(db.DateTime,    default=datetime.utcnow)


class Bookmark(db.Model):
    """One row = one saved destination."""
    id          = db.Column(db.Integer,     primary_key=True)
    user_id     = db.Column(db.Integer,     db.ForeignKey('user.id'), nullable=False)
    destination = db.Column(db.String(150), nullable=False)
    saved_at    = db.Column(db.DateTime,    default=datetime.utcnow)


@login.user_loader
def load_user(uid):
    """Flask-Login calls this to find the current user from the session cookie."""
    return User.query.get(int(uid))


# ══════════════════════════════════════════════════════════
#  COST ESTIMATION LOGIC
# ══════════════════════════════════════════════════════════

# Base prices per person per day (INR)
COST_TABLE = {
    'basic':   {'hotel': 1500,  'food': 600,  'transport': 300,  'activities': 400},
    'luxury':  {'hotel': 6000,  'food': 2000, 'transport': 1000, 'activities': 1500},
    'premium': {'hotel': 15000, 'food': 5000, 'transport': 3000, 'activities': 4000},
}

# Each destination costs this many times more than India baseline
DESTINATION_MULTIPLIER = {
    'india': 1.0,  'bali': 1.8,   'thailand': 1.5, 'singapore': 2.5,
    'dubai': 3.0,  'tokyo': 3.5,  'paris': 4.0,    'london': 4.5,
    'new york': 4.2, 'new zealand': 3.8, 'africa': 2.8,
    'mykonos': 3.6, 'maldives': 5.0, 'switzerland': 4.8, 'egypt': 1.6,
}


def estimate_cost(destination, budget_type, travellers, days):
    """
    Returns (total_cost_int, breakdown_dict).
    Example:  estimate_cost('Tokyo', 'basic', 2, 5)
    """
    key        = destination.lower().strip()
    multiplier = DESTINATION_MULTIPLIER.get(key, 2.5)   # default 2.5× if unknown
    rates      = COST_TABLE.get(budget_type, COST_TABLE['basic'])
    per_person = sum(rates.values()) * multiplier
    total      = per_person * travellers * days
    breakdown  = {k: round(v * multiplier * travellers * days) for k, v in rates.items()}
    return round(total), breakdown


# ══════════════════════════════════════════════════════════
#  PDF GENERATOR
# ══════════════════════════════════════════════════════════

def generate_trip_pdf(trip, breakdown):
    """
    Builds a PDF in memory and returns a BytesIO buffer.
    `trip` can be a dict or a Trip model object — we handle both.
    """
    # Normalise: convert Trip ORM object → dict if needed
    if not isinstance(trip, dict):
        trip = {
            'destination':    trip.destination,
            'start_date':     trip.start_date,
            'end_date':       trip.end_date,
            'travellers':     trip.travellers,
            'budget_type':    trip.budget_type,
            'hotel_name':     trip.hotel_name,
            'transport_type': trip.transport_type,
            'notes':          trip.notes,
        }

    buffer = BytesIO()
    doc    = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=2*cm, leftMargin=2*cm,
        topMargin=2*cm,   bottomMargin=2*cm
    )
    story  = []
    styles = getSampleStyleSheet()

    # ── Header ──────────────────────────────────────────────
    brand_style = ParagraphStyle(
        'Brand', fontSize=28, alignment=TA_CENTER,
        textColor=colors.HexColor('#0a84ff'),
        spaceAfter=4, fontName='Helvetica-Bold'
    )
    sub_style = ParagraphStyle(
        'Sub', fontSize=11, alignment=TA_CENTER,
        textColor=colors.HexColor('#64748b'), spaceAfter=20
    )
    story.append(Paragraph("✈  TRAVELIFY", brand_style))
    story.append(Paragraph("Your Personalised Travel Plan", sub_style))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor('#0a84ff')))
    story.append(Spacer(1, 0.4*cm))

    # ── Section title helper ─────────────────────────────────
    def h2(text):
        return Paragraph(text, ParagraphStyle(
            'H2', fontSize=14, fontName='Helvetica-Bold',
            textColor=colors.HexColor('#0f172a'), spaceBefore=12, spaceAfter=6
        ))

    # ── Trip summary table ───────────────────────────────────
    story.append(h2("Trip Summary"))
    duration = (trip['end_date'] - trip['start_date']).days + 1
    summary  = [
        ['Destination',   trip['destination']],
        ['Travel Dates',
         f"{trip['start_date'].strftime('%d %b %Y')}  →  {trip['end_date'].strftime('%d %b %Y')}"],
        ['Duration',      f"{duration} days"],
        ['Travellers',    str(trip['travellers'])],
        ['Budget Type',   trip['budget_type'].capitalize()],
        ['Hotel',         trip.get('hotel_name') or 'TBD'],
        ['Transport',     trip.get('transport_type') or 'TBD'],
    ]
    t = Table(summary, colWidths=[5*cm, 12*cm])
    t.setStyle(TableStyle([
        ('BACKGROUND',  (0,0), (0,-1), colors.HexColor('#e0f2fe')),
        ('FONTNAME',    (0,0), (0,-1), 'Helvetica-Bold'),
        ('FONTSIZE',    (0,0), (-1,-1), 10),
        ('ROWBACKGROUNDS',(0,0),(-1,-1),[colors.white, colors.HexColor('#f8fafc')]),
        ('GRID',        (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
        ('PADDING',     (0,0), (-1,-1), 8),
        ('VALIGN',      (0,0), (-1,-1), 'MIDDLE'),
    ]))
    story.append(t)
    story.append(Spacer(1, 0.5*cm))

    # ── Cost breakdown ───────────────────────────────────────
    story.append(h2("Estimated Cost Breakdown (₹)"))
    icons    = {'hotel': '🏨 Hotel', 'food': '🍽️ Food',
                'transport': '🚌 Transport', 'activities': '🎯 Activities'}
    cost_rows = [['Category', 'Amount (₹)']]
    grand     = 0
    for cat, amt in breakdown.items():
        cost_rows.append([icons.get(cat, cat.capitalize()), f"₹ {amt:,.0f}"])
        grand += amt
    cost_rows.append(['TOTAL ESTIMATE', f"₹ {grand:,.0f}"])

    ct = Table(cost_rows, colWidths=[9*cm, 8*cm])
    ct.setStyle(TableStyle([
        ('BACKGROUND',   (0,0),  (-1,0),  colors.HexColor('#0a84ff')),
        ('TEXTCOLOR',    (0,0),  (-1,0),  colors.white),
        ('FONTNAME',     (0,0),  (-1,0),  'Helvetica-Bold'),
        ('FONTNAME',     (0,-1), (-1,-1), 'Helvetica-Bold'),
        ('BACKGROUND',   (0,-1), (-1,-1), colors.HexColor('#0f172a')),
        ('TEXTCOLOR',    (0,-1), (-1,-1), colors.white),
        ('ROWBACKGROUNDS',(0,1), (-1,-2), [colors.white, colors.HexColor('#f0f9ff')]),
        ('GRID',         (0,0),  (-1,-1), 0.5, colors.HexColor('#bfdbfe')),
        ('FONTSIZE',     (0,0),  (-1,-1), 10),
        ('PADDING',      (0,0),  (-1,-1), 10),
        ('ALIGN',        (1,0),  (1,-1),  'RIGHT'),
    ]))
    story.append(ct)
    story.append(Spacer(1, 0.5*cm))

    # ── Notes ────────────────────────────────────────────────
    if trip.get('notes'):
        story.append(h2("Additional Notes"))
        story.append(Paragraph(
            trip['notes'].replace('\n', '<br/>'),
            ParagraphStyle('Note', fontSize=10, textColor=colors.HexColor('#475569'), leading=16)
        ))
        story.append(Spacer(1, 0.3*cm))

    # ── Footer ───────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#e2e8f0')))
    story.append(Paragraph(
        f"Generated by Travelify · {datetime.now().strftime('%d %b %Y %H:%M')} · "
        "Estimates are indicative and may vary.",
        ParagraphStyle('Footer', fontSize=9, textColor=colors.HexColor('#94a3b8'),
                       alignment=TA_CENTER, spaceBefore=8)
    ))

    doc.build(story)
    buffer.seek(0)
    return buffer


# ══════════════════════════════════════════════════════════
#  ROBUST EMAIL SENDER  (dual-method: Flask-Mail → smtplib)
# ══════════════════════════════════════════════════════════

def _smtp_send(mail_user, mail_pass, mime_msg, to_email):
    """Send via SMTP using settings from app.config (TLS on 587 or SSL on 465)."""
    server_host = app.config.get('MAIL_SERVER', 'smtp.gmail.com')
    server_port = int(app.config.get('MAIL_PORT', 587))
    use_ssl     = app.config.get('MAIL_USE_SSL', False)
    use_tls     = app.config.get('MAIL_USE_TLS', True)

    if use_ssl:
        server = smtplib.SMTP_SSL(server_host, server_port, timeout=25)
    else:
        server = smtplib.SMTP(server_host, server_port, timeout=25)
        server.ehlo()
        if use_tls:
            server.starttls()
            server.ehlo()

    server.login(mail_user, mail_pass)
    server.sendmail(mail_user, [to_email], mime_msg.as_string())
    server.quit()


def send_email_with_pdf(to_email, to_name, destination, pdf_bytes):
    """
    Send the trip PDF to the registered user's email.
    Uses smtplib first (most reliable), then Flask-Mail as fallback.
    Returns (success: bool, message: str).
    """
    cfg_err = _mail_config_error()
    if cfg_err:
        log.warning(f"Email not sent to {to_email}: {cfg_err}")
        return False, cfg_err

    mail_user   = app.config['MAIL_USERNAME']
    mail_pass   = app.config['MAIL_PASSWORD']
    mail_sender = app.config.get('MAIL_DEFAULT_SENDER') or mail_user
    to_email    = (to_email or '').strip().lower()

    if not to_email or '@' not in to_email:
        return False, 'No valid recipient email on your account.'

    subject   = f"Your Travelify Trip Plan — {destination}"
    body_text = (
        f"Hi {to_name},\n\n"
        f"Your personalised trip plan for {destination} is attached as a PDF.\n\n"
        "Open it anytime — even offline — for your complete itinerary.\n\n"
        "Happy travels!\n"
        "— Team Travelify\n\n"
        "---\nThis email was sent from Travelify"
    )
    filename = f"Travelify_{destination.replace(' ', '_')}.pdf"

    def _build_mime():
        mime_msg = MIMEMultipart()
        mime_msg['From']    = f"Travelify <{mail_sender}>"
        mime_msg['To']      = to_email
        mime_msg['Subject'] = subject
        mime_msg.attach(MIMEText(body_text, 'plain', 'utf-8'))

        part = MIMEBase('application', 'pdf')
        part.set_payload(pdf_bytes)
        email_encoders.encode_base64(part)
        part.add_header('Content-Disposition', f'attachment; filename="{filename}"')
        mime_msg.attach(part)
        return mime_msg

    # ── Method 1: smtplib (direct Gmail SMTP) ────────────────
    try:
        _smtp_send(mail_user, mail_pass, _build_mime(), to_email)
        log.info(f"PDF emailed via SMTP to {to_email}")
        return True, 'success'
    except smtplib.SMTPAuthenticationError:
        log.error(f"Gmail rejected login for {mail_user}")
        return False, (
            'Gmail login failed. Use a 16-character App Password in travelify/.env '
            '(not your normal Gmail password), then restart the server.'
        )
    except smtplib.SMTPException as smtp_err:
        log.warning(f"SMTP failed ({smtp_err}). Trying Flask-Mail...")
    except Exception as err:
        log.warning(f"SMTP failed ({err}). Trying Flask-Mail...")

    # ── Method 2: Flask-Mail fallback ────────────────────────
    try:
        msg = Message(
            subject    = subject,
            sender     = (mail_sender, 'Travelify'),
            recipients = [to_email],
            body       = body_text,
        )
        msg.attach(filename, 'application/pdf', pdf_bytes)
        mail.send(msg)
        log.info(f"PDF emailed via Flask-Mail to {to_email}")
        return True, 'success'
    except smtplib.SMTPAuthenticationError:
        return False, (
            'Gmail login failed. Use a 16-character App Password in travelify/.env '
            '(not your normal Gmail password), then restart the server.'
        )
    except Exception as err:
        log.error(f"Email to {to_email} failed: {err}")
        return False, f'Email could not be sent: {err}'


def send_plain_email(to_email, subject, body):
    """Send a plain-text email (for contact form, newsletter, etc.)"""
    if _mail_config_error():
        return False

    mail_user   = app.config['MAIL_USERNAME']
    mail_pass   = app.config['MAIL_PASSWORD']
    mail_sender = app.config.get('MAIL_DEFAULT_SENDER') or mail_user

    mime_msg = MIMEMultipart()
    mime_msg['From']     = f"Travelify <{mail_sender}>"
    mime_msg['To']       = mail_user
    mime_msg['Subject']  = subject
    mime_msg['Reply-To'] = to_email
    mime_msg.attach(MIMEText(body, 'plain', 'utf-8'))

    try:
        _smtp_send(mail_user, mail_pass, mime_msg, mail_user)
        return True
    except Exception as e:
        log.error(f"Plain email failed: {e}")
        return False


# ══════════════════════════════════════════════════════════
#  DESTINATION DATA  (for the map + planner)
# ══════════════════════════════════════════════════════════

DESTINATIONS = [
    {"name": "India",       "lat": 20.5937,  "lng": 78.9629,   "cat": "asia"},
    {"name": "Tokyo",       "lat": 35.6762,  "lng": 139.6503,  "cat": "asia"},
    {"name": "Bali",        "lat": -8.4095,  "lng": 115.1889,  "cat": "asia"},
    {"name": "Thailand",    "lat": 15.8700,  "lng": 100.9925,  "cat": "asia"},
    {"name": "Singapore",   "lat": 1.3521,   "lng": 103.8198,  "cat": "asia"},
    {"name": "Dubai",       "lat": 25.2048,  "lng": 55.2708,   "cat": "mideast"},
    {"name": "London",      "lat": 51.5074,  "lng": -0.1278,   "cat": "europe"},
    {"name": "Paris",       "lat": 48.8566,  "lng": 2.3522,    "cat": "europe"},
    {"name": "Mykonos",     "lat": 37.4467,  "lng": 25.3289,   "cat": "europe"},
    {"name": "New York",    "lat": 40.7128,  "lng": -74.0060,  "cat": "americas"},
    {"name": "New Zealand", "lat": -40.9006, "lng": 174.8860,  "cat": "oceania"},
    {"name": "Africa",      "lat": -8.7832,  "lng": 34.5085,   "cat": "africa"},
]


def maps_embed_url(destinations=None, zoom=2):
    """Google Maps iframe URL showing all site destinations."""
    places = destinations or DESTINATIONS
    q = '|'.join(f"{d['lat']},{d['lng']}" for d in places)
    return (
        f"https://maps.google.com/maps?q={quote(q, safe='|,+-.')}"
        f"&z={zoom}&hl=en&output=embed"
    )


def maps_embed_dest_url(dest, zoom=9):
    """Google Maps iframe URL focused on one destination."""
    if isinstance(dest, str):
        dest = next((d for d in DESTINATIONS if d['name'] == dest), None)
    if not dest:
        return maps_embed_url()
    q = f"{dest['lat']},{dest['lng']}"
    return (
        f"https://maps.google.com/maps?q={quote(q, safe='|,+-.')}"
        f"&z={zoom}&hl=en&output=embed"
    )


@app.context_processor
def inject_map_data():
    return {
        'destinations':        DESTINATIONS,
        'maps_embed_url':      maps_embed_url(),
        'maps_embed_dest_url': maps_embed_dest_url,
    }


# ══════════════════════════════════════════════════════════
#  PUBLIC ROUTES
# ══════════════════════════════════════════════════════════

@app.route('/')
def index():
    bookmarked = []
    if current_user.is_authenticated:
        bookmarked = [b.destination for b in current_user.bookmarks]
    return render_template(
        'index.html',
        bookmarked=bookmarked,
        maps_key=GOOGLE_MAPS_KEY,
        destinations_json=json.dumps(DESTINATIONS)
    )


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        name    = request.form.get('name', '').strip()
        email   = request.form.get('email', '').strip().lower()
        pw      = request.form.get('password', '')
        confirm = request.form.get('confirm', '')

        if not all([name, email, pw, confirm]):
            flash('Please fill in all fields.', 'danger')
        elif pw != confirm:
            flash('Passwords do not match.', 'danger')
        elif len(pw) < 6:
            flash('Password must be at least 6 characters.', 'danger')
        elif User.query.filter_by(email=email).first():
            flash('Email already registered. Please log in.', 'warning')
        else:
            user = User(name=name, email=email, password=generate_password_hash(pw))
            db.session.add(user)
            db.session.commit()
            login_user(user)
            flash(f'Welcome aboard, {name}! 🎉', 'success')
            return redirect(url_for('dashboard'))
    return redirect(url_for('index'))


@app.route('/login', methods=['GET', 'POST'])
def login_route():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        pw    = request.form.get('password', '')
        user  = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, pw):
            login_user(user, remember=request.form.get('remember') == 'on')
            flash(f'Welcome back, {user.name}! ✈️', 'success')
            next_page = request.args.get('next')
            return redirect(next_page or url_for('dashboard'))
        flash('Invalid email or password.', 'danger')
    return redirect(url_for('index'))


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out. Safe travels! 👋', 'info')
    return redirect(url_for('index'))


# ── Contact form ──────────────────────────────────────────

@app.route('/contact', methods=['POST'])
def contact():
    name    = request.form.get('name', '').strip()
    email   = request.form.get('email', '').strip()
    subject = request.form.get('subject', 'Travelify Contact').strip()
    message = request.form.get('message', '').strip()

    if not all([name, email, message]):
        flash('Please fill in all required fields.', 'danger')
        return redirect(url_for('index') + '#contact')

    body = f"Name: {name}\nEmail: {email}\nSubject: {subject}\n\nMessage:\n{message}"
    sent = send_plain_email(email, f"[Travelify] {subject}", body)

    if sent:
        flash('Message sent! We will reply within 24 hours. 📩', 'success')
    else:
        flash('Message received! (Email delivery queued — we will be in touch.)', 'info')
    return redirect(url_for('index') + '#contact')


# ── Newsletter ─────────────────────────────────────────────

@app.route('/newsletter', methods=['POST'])
def newsletter():
    email = request.form.get('email', '').strip()
    if not email or '@' not in email:
        return jsonify({'ok': False, 'msg': 'Invalid email address.'})
    send_plain_email(email, "New Newsletter Subscription — Travelify",
                     f"New subscriber: {email}")
    return jsonify({'ok': True, 'msg': 'Thank you for subscribing! 🎉'})


# ── Bookmark API ───────────────────────────────────────────

@app.route('/api/bookmark', methods=['POST'])
@login_required
def toggle_bookmark():
    data        = request.get_json()
    destination = (data or {}).get('destination', '').strip()
    if not destination:
        return jsonify({'ok': False})
    existing = Bookmark.query.filter_by(
        user_id=current_user.id, destination=destination
    ).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()
        return jsonify({'ok': True, 'saved': False})
    db.session.add(Bookmark(user_id=current_user.id, destination=destination))
    db.session.commit()
    return jsonify({'ok': True, 'saved': True})


# ── Search ─────────────────────────────────────────────────

@app.route('/api/search')
def api_search():
    q = request.args.get('q', '').lower()
    return jsonify([d for d in DESTINATIONS if q in d['name'].lower()])


# ══════════════════════════════════════════════════════════
#  TRAVEL PLANNER
# ══════════════════════════════════════════════════════════

@app.route('/planner', methods=['GET', 'POST'])
@login_required
def planner():
    estimate  = None
    breakdown = None
    trip_data = None

    if request.method == 'POST':
        action = request.form.get('action', 'estimate')

        # Collect form values
        destination    = request.form.get('destination', '').strip()
        start_str      = request.form.get('start_date', '')
        end_str        = request.form.get('end_date', '')
        travellers     = max(1, int(request.form.get('travellers', 1) or 1))
        budget_type    = request.form.get('budget_type', 'basic')
        hotel_name     = request.form.get('hotel_name', '').strip()
        transport_type = request.form.get('transport_type', '').strip()
        notes          = request.form.get('notes', '').strip()

        # Parse dates
        try:
            start_date = datetime.strptime(start_str, '%Y-%m-%d').date()
            end_date   = datetime.strptime(end_str,   '%Y-%m-%d').date()
        except ValueError:
            flash('Please pick valid departure and return dates.', 'danger')
            return redirect(url_for('planner'))

        days = (end_date - start_date).days + 1
        if days < 1:
            flash('Return date must be after departure date.', 'danger')
            return redirect(url_for('planner'))

        if not destination:
            flash('Please select a destination.', 'danger')
            return redirect(url_for('planner'))

        # Cost estimate
        total_cost, breakdown = estimate_cost(destination, budget_type, travellers, days)

        trip_data = {
            'destination':    destination,
            'start_date':     start_date,
            'end_date':       end_date,
            'travellers':     travellers,
            'budget_type':    budget_type,
            'hotel_name':     hotel_name,
            'transport_type': transport_type,
            'notes':          notes,
        }

        # ── Save trip to DB (needed for save / download / email) ──────────
        if action in ('save', 'download', 'email'):
            trip_obj = Trip(
                user_id        = current_user.id,
                destination    = destination,
                start_date     = start_date,
                end_date       = end_date,
                travellers     = travellers,
                budget_type    = budget_type,
                hotel_name     = hotel_name,
                transport_type = transport_type,
                notes          = notes,
                estimated_cost = total_cost,
            )
            db.session.add(trip_obj)
            db.session.commit()
            log.info(f"Trip saved: {destination} for user {current_user.email}")

        # ── Download PDF ────────────────────────────────────────────────
        if action == 'download':
            pdf_buf = generate_trip_pdf(trip_data, breakdown)
            safe_name = destination.replace(' ', '_')
            return send_file(
                pdf_buf,
                download_name=f"Travelify_{safe_name}.pdf",
                as_attachment=True,
                mimetype='application/pdf'
            )

        # ── Email PDF to user ────────────────────────────────────────────
        if action == 'email':
            pdf_buf   = generate_trip_pdf(trip_data, breakdown)
            pdf_bytes = pdf_buf.read()           # read the whole PDF into bytes

            ok, reason = send_email_with_pdf(
                to_email    = current_user.email,
                to_name     = current_user.name,
                destination = destination,
                pdf_bytes   = pdf_bytes,
            )
            if ok:
                flash(f'Trip plan sent to {current_user.email} 📩', 'success')
            else:
                flash(f'Trip saved ✅ — Email failed: {reason}', 'warning')
            return redirect(url_for('planner'))

        # ── Just save ────────────────────────────────────────────────────
        if action == 'save':
            flash(f'Trip to {destination} saved to your dashboard! 🗺️', 'success')
            return redirect(url_for('dashboard'))

        # ── Just estimate (show results on same page) ────────────────────
        estimate = total_cost

    all_trips = Trip.query.filter_by(user_id=current_user.id)\
                          .order_by(Trip.created_at.desc()).all()
    return render_template(
        'planner.html',
        estimate=estimate, breakdown=breakdown, trip_data=trip_data,
        all_trips=all_trips, destinations=DESTINATIONS,
        today=date.today().isoformat()
    )


@app.route('/planner/pdf/<int:trip_id>')
@login_required
def download_trip_pdf(trip_id):
    trip_obj = Trip.query.get_or_404(trip_id)
    if trip_obj.user_id != current_user.id:
        abort(403)
    _, breakdown = estimate_cost(trip_obj.destination, trip_obj.budget_type,
                                 trip_obj.travellers, trip_obj.duration_days)
    pdf_buf   = generate_trip_pdf(trip_obj, breakdown)
    safe_name = trip_obj.destination.replace(' ', '_')
    return send_file(pdf_buf,
                     download_name=f"Travelify_{safe_name}.pdf",
                     as_attachment=True,
                     mimetype='application/pdf')


@app.route('/planner/email/<int:trip_id>')
@login_required
def email_trip_pdf(trip_id):
    """Re-email an already-saved trip."""
    trip_obj = Trip.query.get_or_404(trip_id)
    if trip_obj.user_id != current_user.id:
        abort(403)
    _, breakdown = estimate_cost(trip_obj.destination, trip_obj.budget_type,
                                 trip_obj.travellers, trip_obj.duration_days)
    pdf_buf   = generate_trip_pdf(trip_obj, breakdown)
    pdf_bytes = pdf_buf.read()
    ok, reason = send_email_with_pdf(
        to_email    = current_user.email,
        to_name     = current_user.name,
        destination = trip_obj.destination,
        pdf_bytes   = pdf_bytes,
    )
    if ok:
        flash(f'Trip plan re-sent to {current_user.email} 📩', 'success')
    else:
        flash(f'Email failed: {reason}', 'warning')
    return redirect(url_for('dashboard'))


@app.route('/planner/delete/<int:trip_id>', methods=['POST'])
@login_required
def delete_trip(trip_id):
    trip_obj = Trip.query.get_or_404(trip_id)
    if trip_obj.user_id != current_user.id:
        abort(403)
    db.session.delete(trip_obj)
    db.session.commit()
    flash('Trip deleted.', 'info')
    return redirect(url_for('dashboard'))


# ══════════════════════════════════════════════════════════
#  EXPENSE TRACKER
# ══════════════════════════════════════════════════════════

@app.route('/tracker', methods=['GET', 'POST'])
@login_required
def tracker():
    trips = Trip.query.filter_by(user_id=current_user.id)\
                      .order_by(Trip.start_date.desc()).all()

    if request.method == 'POST':
        action = request.form.get('action', 'add')

        if action == 'add':
            trip_id     = request.form.get('trip_id') or None
            category    = request.form.get('category', 'misc')
            description = request.form.get('description', '').strip()
            amount_str  = request.form.get('amount', '0')
            date_str    = request.form.get('expense_date', '')

            if not description:
                flash('Please enter a description.', 'danger')
                return redirect(url_for('tracker'))
            try:
                amount = float(amount_str)
                if amount <= 0:
                    raise ValueError
            except ValueError:
                flash('Please enter a valid positive amount.', 'danger')
                return redirect(url_for('tracker'))

            exp_date = date.today()
            if date_str:
                try:
                    exp_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                except ValueError:
                    pass

            exp = Expense(
                user_id      = current_user.id,
                trip_id      = int(trip_id) if trip_id else None,
                category     = category,
                description  = description,
                amount       = amount,
                expense_date = exp_date,
            )
            db.session.add(exp)
            db.session.commit()
            flash(f'₹{amount:,.0f} expense added! 💰', 'success')

        elif action == 'delete':
            exp_id = request.form.get('expense_id')
            exp    = Expense.query.get_or_404(exp_id)
            if exp.user_id == current_user.id:
                db.session.delete(exp)
                db.session.commit()
                flash('Expense removed.', 'info')

        return redirect(url_for('tracker',
                                trip_id=request.form.get('filter_trip_id') or ''))

    # Filter
    selected_trip_id = request.args.get('trip_id', type=int)
    q = Expense.query.filter_by(user_id=current_user.id)
    if selected_trip_id:
        q = q.filter_by(trip_id=selected_trip_id)
    expenses = q.order_by(Expense.expense_date.desc()).all()

    category_totals = {}
    for exp in expenses:
        category_totals[exp.category] = category_totals.get(exp.category, 0) + exp.amount

    return render_template(
        'tracker.html',
        expenses         = expenses,
        trips            = trips,
        total_spent      = sum(e.amount for e in expenses),
        category_totals  = json.dumps(category_totals),
        selected_trip_id = selected_trip_id,
        today            = date.today().isoformat()
    )


# ══════════════════════════════════════════════════════════
#  DASHBOARD
# ══════════════════════════════════════════════════════════

@app.route('/dashboard')
@login_required
def dashboard():
    from collections import defaultdict
    trips     = Trip.query.filter_by(user_id=current_user.id)\
                          .order_by(Trip.created_at.desc()).all()
    bookmarks = Bookmark.query.filter_by(user_id=current_user.id)\
                              .order_by(Bookmark.saved_at.desc()).all()
    recent_exp = Expense.query.filter_by(user_id=current_user.id)\
                              .order_by(Expense.expense_date.desc()).limit(10).all()
    all_exp    = Expense.query.filter_by(user_id=current_user.id).all()
    total_spent = sum(e.amount for e in all_exp)

    monthly = defaultdict(float)
    for e in all_exp:
        monthly[e.expense_date.strftime('%b %Y')] += e.amount

    return render_template(
        'dashboard.html',
        trips            = trips,
        bookmarks        = bookmarks,
        recent_expenses  = recent_exp,
        total_spent      = total_spent,
        upcoming_trips   = [t for t in trips if t.start_date >= date.today()],
        past_trips       = [t for t in trips if t.end_date   <  date.today()],
        monthly_spending = json.dumps(dict(monthly)),
        destinations     = DESTINATIONS,
        maps_key         = GOOGLE_MAPS_KEY,
    )


# ══════════════════════════════════════════════════════════
#  STARTUP
# ══════════════════════════════════════════════════════════

with app.app_context():
    db.create_all()

_mail_startup_err = _mail_config_error()
if _mail_startup_err:
    log.warning(f"PDF email disabled until .env is configured: {_mail_startup_err}")
else:
    log.info(f"PDF email ready — sending from {app.config['MAIL_USERNAME']}")

if __name__ == '__main__':
    app.run(debug=True, port=5000)

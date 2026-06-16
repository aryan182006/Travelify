# ✈ Travelify — Dynamic Flask Web Application

A full-featured travel planning platform built with **Python + Flask**, preserving your exact original design, theme, colours and fonts.

---

## 🚀 Quick Start (4 Commands)

```bash
pip install -r requirements.txt     # 1. Install packages
cp .env.example .env                # 2. Copy env template
# Edit .env — add Gmail App Password + Google Maps key
cp /your/photos/* static/photos/    # 3. Add your photos
python run.py                       # 4. Launch → localhost:5000
```

---

## 📂 Project Structure

```
travelify/
├── app.py                    ← Main Flask app — all routes, models, logic
├── run.py                    ← Quick-start script
├── requirements.txt          ← Python dependencies
├── .env.example              ← Environment variable template
├── generate_explanation_pdf.py ← Generates the code explanation PDF
├── Travelify_Code_Explained.pdf ← 32-page beginner code walkthrough
│
├── instance/
│   └── travelify.db          ← SQLite DB (auto-created on first run)
│
├── static/
│   ├── css/Travelify2.css    ← Your original CSS (unchanged)
│   └── photos/               ← Copy ALL your photos here
│
└── templates/
    ├── base.html             ← Shared navbar + footer + modals
    ├── index.html            ← Home page (all original sections)
    ├── planner.html          ← Travel Planner
    ├── tracker.html          ← Expense Tracker
    └── dashboard.html        ← User Dashboard
```

---

## ✨ All 6 Features

| Feature | Details |
|---|---|
| 🔐 **User Auth** | Register / Login / Logout with hashed passwords (Werkzeug) |
| 🗺 **Trip Planner** | Destination, dates, budget tier, hotel, transport → cost estimate |
| 📄 **PDF Download** | ReportLab generates styled A4 PDF with full trip breakdown |
| 📧 **Email PDF** | **Dual-method** sending: Flask-Mail first → raw smtplib fallback |
| 💳 **Expense Tracker** | Full CRUD — categorised, trip-linked, pie chart breakdown |
| 🏠 **Dashboard** | Trips, bookmarks, expenses, monthly bar chart, mini Google Map |
| 🗺 **Google Maps** | Custom blue pins, bounce on click, dark/light mode sync |
| 🔖 **Bookmarks** | Server-side for logged-in users, localStorage for guests |

---

## 📧 Email Setup (Gmail)

1. Go to **myaccount.google.com → Security**
2. Enable **2-Step Verification**
3. Click **App Passwords** → Create → Copy the **16-char key**
4. Paste into `.env`:
```env
MAIL_USERNAME=your@gmail.com
MAIL_PASSWORD=abcdefghijklmnop    ← 16-char App Password (no spaces)
```

> The app uses a **dual-method** email approach:
> - **Method 1**: Flask-Mail (uses `app.config` settings)
> - **Method 2**: Raw `smtplib` fallback (direct SMTP — more reliable)
> If Method 1 fails, Method 2 kicks in automatically with a detailed error message.

---

## 🗺 Google Maps Setup

1. Go to **console.cloud.google.com**
2. Enable **Maps JavaScript API**
3. Create an **API Key** under Credentials
4. Add to `.env`: `GOOGLE_MAPS_API_KEY=AIza...`

> Without an API key, the map section shows an embedded OpenStreetMap iframe as fallback.

---

## 💸 Cost Estimation

Costs are per person per day × destination multiplier:

| Budget | Hotel | Food | Transport | Activities |
|---|---|---|---|---|
| Basic | ₹1,500 | ₹600 | ₹300 | ₹400 |
| Luxury | ₹6,000 | ₹2,000 | ₹1,000 | ₹1,500 |
| Premium | ₹15,000 | ₹5,000 | ₹3,000 | ₹4,000 |

Destination multipliers: India=1.0×, Bali=1.8×, Dubai=3.0×, Paris=4.0×, Maldives=5.0×

---

## 🗃 Database Models

| Model | Key Fields |
|---|---|
| `User` | id, name, email, password (hashed), created_at |
| `Trip` | destination, start/end_date, travellers, budget_type, estimated_cost |
| `Expense` | category, description, amount, expense_date, trip_id |
| `Bookmark` | destination, saved_at, user_id |

---

## 🌐 All API Routes

| Route | Method | Purpose |
|---|---|---|
| `/` | GET | Home page |
| `/register` | POST | Create account |
| `/login` | POST | Log in |
| `/logout` | GET | Log out |
| `/planner` | GET + POST | Trip planner (estimate / save / PDF / email) |
| `/planner/pdf/<id>` | GET | Download saved trip PDF |
| `/planner/email/<id>` | GET | Re-email saved trip PDF |
| `/planner/delete/<id>` | POST | Delete trip |
| `/tracker` | GET + POST | Expense tracker |
| `/dashboard` | GET | User dashboard |
| `/contact` | POST | Contact form |
| `/newsletter` | POST | Newsletter subscribe |
| `/api/bookmark` | POST | Toggle destination bookmark (JSON) |
| `/api/search` | GET | Search destinations (JSON) |

---

Made with ❤️ in Aurangabad — Travelify 2026

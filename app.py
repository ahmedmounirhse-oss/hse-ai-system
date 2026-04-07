# -*- coding: utf-8 -*-
from flask import session, redirect, url_for
from flask import Flask, render_template, request, jsonify, send_file
from dotenv import load_dotenv
import os

# ✅ تحميل .env
load_dotenv()

import sqlite3
from datetime import datetime
from openai import OpenAI
from collections import Counter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from io import BytesIO
from ai_engine import validate_classification, map_severity
from risk_calc import calculate_risk
import json
import base64
import sqlite3


import os
import sqlite3

def get_db():
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    conn = sqlite3.connect(os.path.join(BASE_DIR, 'hse.db'), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


# ================= FLASK APP =================
print("App starting...")

# ✅ إنشاء Flask app
app = Flask(__name__)

# 🔐 session config
app.secret_key = "supersecretkey"

# 🔑 admin credentials
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "5555632"

print("Flask app created...")


# ================= COMPANY MIDDLEWARE =================
from flask import g, request
import re

def sanitize_company(name):
    return re.sub(r'[^a-zA-Z0-9_-]', '', (name or "default").lower())

def get_company():
    return sanitize_company(request.args.get("company"))

def get_or_create_company(db, name):
    c = db.cursor()
    c.execute("SELECT id FROM companies WHERE name=?", (name,))
    row = c.fetchone()

    if row:
        return row[0]

    c.execute("INSERT INTO companies (name) VALUES (?)", (name,))
    db.commit()
    return c.lastrowid


@app.before_request
def attach_company():
    db = get_db()
    company_name = get_company()
    g.company_name = company_name
    g.company_id = get_or_create_company(db, company_name)


# ================= UPLOAD FOLDER =================
UPLOAD_FOLDER = 'static/uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
# ---------------- DATABASE ----------------
def init_db():
    import sqlite3
    import os

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(BASE_DIR, 'hse.db')

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # reports table
    c.execute("""
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    description TEXT,
    location TEXT,
    type TEXT,
    event TEXT,
    severity TEXT,
    risk_score INTEGER,
    recommendation TEXT,
    emp_id TEXT,
    name TEXT,
    image TEXT,
    date TEXT,
    company_id INTEGER,
    root_cause TEXT,
    hazard_class TEXT
)
""")
    
    # Add missing columns if they don't exist
    c.execute("PRAGMA table_info(reports)")
    columns = [col[1] for col in c.fetchall()]
    
    if 'root_cause' not in columns:
        c.execute("ALTER TABLE reports ADD COLUMN root_cause TEXT")
    if 'hazard_class' not in columns:
        c.execute("ALTER TABLE reports ADD COLUMN hazard_class TEXT")
    
    c.execute("""
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE
)
""")
    # users table with admin support (recreate if needed)
    try:
        # Check if table exists and has old structure
        c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'")
        table_def = c.fetchone()
        if table_def and 'emp_id' in table_def[0]:
            # Drop old table and recreate
            c.execute("DROP TABLE users")
            print("Dropped old users table")
    except:
        pass

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT,
            company_id INTEGER,
            is_admin INTEGER DEFAULT 0,
            FOREIGN KEY (company_id) REFERENCES companies (id)
        )
    """)

    conn.commit()
    conn.close()


# ✅ هنا بس تناديها (بعد التعريف)
init_db()

# Create default admin users for companies
def create_default_admins():
    companies = ["default", "company1", "company2", "company3", "company4"]

    conn = get_db()
    c = conn.cursor()

    for company_name in companies:
        # Get or create company
        c.execute("SELECT id FROM companies WHERE name=?", (company_name,))
        comp = c.fetchone()

        if not comp:
            c.execute("INSERT INTO companies (name) VALUES (?)", (company_name,))
            conn.commit()
            company_id = c.lastrowid
        else:
            company_id = comp[0]

        # Create default admin user for this company
        admin_username = f"admin_{company_name}"
        admin_password = f"admin123_{company_name}"

        # Check if admin already exists
        c.execute("SELECT id FROM users WHERE username=? AND company_id=?", (admin_username, company_id))
        existing_admin = c.fetchone()

        if not existing_admin:
            c.execute("INSERT INTO users (username, password, company_id, is_admin) VALUES (?, ?, ?, ?)",
                      (admin_username, admin_password, company_id, 1))
            print(f"✅ Created admin user for {company_name}: {admin_username} / {admin_password}")

    conn.commit()
    conn.close()

create_default_admins()


# ✅ تحميل API Key بشكل آمن
api_key = os.getenv("OPENAI_API_KEY")

if not api_key:
    print("❌ ERROR: OPENAI_API_KEY not found in .env")
    client = None
else:
    try:
        client = OpenAI(api_key=api_key)
        print("✅ OpenAI client initialized")
    except Exception as e:
        print(f"❌ OpenAI client init failed: {e}")
        client = None
# ---------------- ADD POINTS ----------------
def add_points(emp_id, name, points):
    try:
        conn = get_db()
        c = conn.cursor()

        # تأكد إن المستخدم موجود
        c.execute("SELECT emp_id FROM users WHERE emp_id=?", (emp_id,))
        user = c.fetchone()

        if not user:
            c.execute("""
            INSERT INTO users (emp_id, name, points)
            VALUES (?, ?, ?)
            """, (emp_id, name, points))
        else:
            c.execute("""
            UPDATE users 
            SET points = COALESCE(points,0) + ?
            WHERE emp_id=?
            """, (points, emp_id))

        conn.commit()

    except Exception as e:
        print("POINTS ERROR:", e)

    finally:
        try:
            c.close()
            conn.close()
        except:
            pass
# ---------------- UTIL ----------------
def normalize_ai_response(ai):
    default = {
        "risk": "Unknown",
        "event": "Observation",
        "severity": "LOW",
        "risk_score": 1,
        "recommendation": "Could not analyze content automatically. Please review manually."
    }

    if not isinstance(ai, dict):
        return default

    for key, value in default.items():
        if key in ai and ai[key] is not None:
            default[key] = ai[key]

    if not isinstance(default["risk_score"], (int, float)):
        default["risk_score"] = 1

    return default


# ================== 🔥 NEW ADDITIONS ==================

def classify_hazard_backend(text):
    t = (text or "").lower()

    # 🔴 CRITICAL PROCESS SAFETY (Priority 1)
    if any(x in t for x in [
        "gas leak","lpg","pressure release","explosion","blast","vapour cloud","fire"
    ]):
        return "Process Safety"

    # 🔴 CHEMICAL
    if any(x in t for x in [
        "chemical","acid","toxic","fume","corrosion","spill"
    ]):
        return "Chemical Exposure"

    # ⚙ MECHANICAL
    if any(x in t for x in [
        "pump","compressor","equipment","machine","rotating","failure"
    ]):
        return "Mechanical Integrity"

    # ⚡ ELECTRICAL
    if any(x in t for x in [
        "electric","shock","arc","panel","short circuit"
    ]):
        return "Electrical"

    # 🪜 HEIGHT
    if any(x in t for x in [
        "fall","height","ladder","scaffold"
    ]):
        return "Work at Height"

    # 🚧 CONFINED SPACE
    if any(x in t for x in [
        "confined","tank entry","vessel entry","oxygen"
    ]):
        return "Confined Space"

    # 🏗 LIFTING
    if any(x in t for x in [
        "lifting","crane","rigging"
    ]):
        return "Lifting Operations"

    # 👷 BEHAVIORAL
    if any(x in t for x in [
        "no ppe","unsafe","violation","no helmet"
    ]):
        return "Behavioral Safety"

    return "General"

def generate_smart_alert(severity, risk_score, hazard):
    severity = str(severity).upper()

    # 1. شروط الخطورة (لاحظ المسافات البادئة لكل سطر)
    if severity == "HIGH" or (isinstance(risk_score, int) and risk_score >= 8):
        return f"🚨 CRITICAL: {hazard} - Immediate action required"

    if severity == "MEDIUM":
        return f"⚠ {hazard} - Action required"

    # 2. تصنيف المخاطر (كل الـ elif لازم تكون تحت بعض بالظبط)
    if hazard == "Process Safety":
        return "🔥 Check gas detection & firefighting systems"
    elif hazard == "Electrical":
        return "⚡ Apply LOTO before work"
    elif hazard == "Mechanical":
        return "⚙ Inspect equipment integrity"
    elif hazard == "Fire":
        return "🔥 Fire Hazard - Check extinguishers"
    elif hazard == "Chemical Exposure":
        return "☣ Chemical Hazard - Ensure PPE & ventilation"
    else:
        return "✅ Monitor"
# ================= AI CLASSIFICATION ==================
def classify_with_ai(desc, image_ai=None):
    if not client:
        return None

    # 🔥 إضافة Context من الصورة
    context = ""
    if image_ai:
        context = f"""\
Image Analysis:
Hazard: {image_ai.get("hazard", "")}
Risk: {image_ai.get("risk", "")}
Details: {image_ai.get("description", "")}
"""

    prompt = f"""
You are a Senior HSE Manager with 20+ years experience in oil & gas (EGPC standards).

Analyze the report professionally using engineering judgment.

{context}

Report:
{desc}

STRICT RULES:
- You must classify EVENT correctly:
  Observation = unsafe condition only
  Near Miss = incident occurred but NO injury
  Incident = injury, fire damage, or loss occurred

- Be precise and realistic (not conservative bias)

Return STRICT JSON:

{{
"report_type": "ONE of: Observation, Near Miss, Incident (choose exactly one, do NOT return multiple values)",
"hazard_category": "Behavioral / Mechanical / Chemical / Fire / Process Safety / Physical",
"severity": "LOW / MEDIUM / HIGH",
"risk_score": 1-25,

"immediate_actions": ["..."],
"corrective_actions": ["..."],
"preventive_actions": ["..."],

"root_cause": "specific realistic cause",

"justification": "Explain WHY you classified event + severity clearly like a senior safety engineer"
}}
"""

    try:
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}]
        )

        txt = res.choices[0].message.content.strip()

        # 🔥 حماية لو الرد فاضي
        if not txt:
            print("AI EMPTY RESPONSE")
            return None

        # تنظيف code block
        if "```" in txt:
            txt = txt.replace("```json", "").replace("```", "").strip()

        # 🔥 استخراج JSON حتى لو فيه كلام زيادة
        import re
        match = re.search(r'\{.*\}', txt, re.DOTALL)
        if match:
            txt = match.group()

        return json.loads(txt)

    except Exception as e:
        print("AI PARSE ERROR:", txt)
        print("ERROR:", e)
        return None
  # ================= AI INTELLIGENCE =================

def compute_root_cause(desc):
    t = (desc or "").lower()

    if any(x in t for x in ["no ppe", "violation", "unsafe"]):
        return "Behavioral / PPE non-compliance"

    if any(x in t for x in ["leak", "spill", "corrosion"]):
        return "Equipment failure / Integrity issue"

    if any(x in t for x in ["housekeeping", "clutter"]):
        return "Poor housekeeping"

    if any(x in t for x in ["procedure", "no permit"]):
        return "Procedure / Permit failure"

    return "General unsafe condition"


def generate_dynamic_alert(risk_score, hazard, root_cause):
    if risk_score >= 15:
        return f"🚨 CRITICAL: {hazard} | Cause: {root_cause}"
    elif risk_score >= 8:
        return f"⚠ HIGH: {hazard} | Monitor closely"
    else:
        return f"✅ LOW: {hazard}"


def predict_next_risk(data):
    # بسيط: أكثر hazard متكرر = المتوقع يزيد
    count = {}
    for r in data:
        h = r.get("hazard_class", "General")
        count[h] = count.get(h, 0) + 1

    if not count:
        return "No data"

    return max(count, key=count.get)  
def analyze_image(image_path):
    try:
        with open(image_path, "rb") as f:
            img_base64 = base64.b64encode(f.read()).decode("utf-8")

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": """
You are a senior HSE engineer.

Analyze this image and identify:
- hazard type
- risk level
- what is unsafe

Return JSON only:
{
"hazard": "",
"risk": "",
"description": ""
}
"""},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"}
                        }
                    ]
                }
            ]
        )

        txt = response.choices[0].message.content.strip()

        if "```" in txt:
            txt = txt.replace("```json", "").replace("```", "").strip()

        return json.loads(txt)

    except Exception as e:
        print("IMAGE AI ERROR:", e)
        return None
    
# ================== ROUTES ==================

@app.route('/')
def home():
    return render_template('index.html')


@app.route('/risk-assessment')
def risk_assessment():
    return render_template('risk_assessment.html')

@app.route('/investigate', methods=['POST'])
def investigate():

    data = request.json
    desc = data.get("description", "")

    prompt = f"""
You are a Senior HSE Investigator.

Analyze this incident and perform a full 5 Whys investigation.

Incident:
{desc}

Return STRICT JSON:

{{
"whys": [
"Why 1",
"Why 2",
"Why 3",
"Why 4",
"Why 5"
],
"root_cause": "Final root cause",
"corrective_actions": ["action1", "action2"],
"preventive_actions": ["action1", "action2"]
}}
"""

    try:
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}]
        )

        txt = res.choices[0].message.content.strip()

        if "```" in txt:
            txt = txt.replace("```json", "").replace("```", "").strip()

        return jsonify(json.loads(txt))

    except Exception as e:
        print("INVESTIGATION ERROR:", e)
        return jsonify({"error": "AI failed"}), 500

@app.route('/investigation')
def investigation():
    return render_template('investigation.html')

@app.route('/generate_pdf')
def generate_pdf():

    conn = get_db()
    c = conn.cursor()

    c.execute("""
SELECT description, location, severity, risk_score 
FROM reports
WHERE company_id=?
""", (g.company_id,))

    data = c.fetchall()
    conn.close()

    pdf_path = "report.pdf"
    doc = SimpleDocTemplate(pdf_path)

    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph("HSE Report Summary", styles['Title']))
    elements.append(Spacer(1, 12))

    for r in data:
        elements.append(Paragraph(f"Location: {r[1]}", styles['Normal']))
        elements.append(Paragraph(f"Description: {r[0]}", styles['Normal']))
        elements.append(Paragraph(f"Severity: {r[2]}", styles['Normal']))
        elements.append(Paragraph(f"Risk Score: {r[3]}", styles['Normal']))
        elements.append(Spacer(1, 10))

    doc.build(elements)

    return send_file(pdf_path, as_attachment=True)

@app.route('/investigation_pdf', methods=['POST'])
def investigation_pdf():

    data = request.json

    desc = data.get("description", "")
    root = data.get("root_cause", "")
    corrective = data.get("corrective_actions", [])
    preventive = data.get("preventive_actions", [])
    image_path = data.get("image", "")

    buffer = BytesIO()  # ✅ حل مشكلة الفتح

    doc = SimpleDocTemplate(buffer)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph("Incident Investigation Report", styles['Title']))
    elements.append(Spacer(1, 10))

    elements.append(Paragraph(f"<b>Incident:</b> {desc}", styles['Normal']))
    elements.append(Spacer(1, 10))

    # 🖼️ إضافة الصورة لو موجودة
    if image_path:
        try:
            elements.append(Image(image_path, width=300, height=200))
            elements.append(Spacer(1, 10))
        except:
            pass

    elements.append(Paragraph(f"<b>Root Cause:</b> {root}", styles['Normal']))
    elements.append(Spacer(1, 10))

    elements.append(Paragraph("<b>Corrective Actions:</b>", styles['Normal']))
    for a in corrective:
        elements.append(Paragraph(f"- {a}", styles['Normal']))

    elements.append(Spacer(1, 10))

    elements.append(Paragraph("<b>Preventive Actions:</b>", styles['Normal']))
    for a in preventive:
        elements.append(Paragraph(f"- {a}", styles['Normal']))

    doc.build(elements)

    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name="investigation.pdf", mimetype='application/pdf')

@app.route('/reports')
def reports():
    try:
        conn = get_db()
        c = conn.cursor()

        company_id = g.company_id

        c.execute("""
        SELECT description, location, type, event, severity, risk_score, recommendation, date, image, root_cause
        FROM reports
        WHERE company_id=?
        ORDER BY date DESC
        """, (company_id,))

        rows = c.fetchall()
        conn.close()

        result = []
        for r in rows:
            result.append({
                "description": r[0],
                "location": r[1],
                "hazard_class": r[2],
                "event": r[3],
                "severity": r[4],
                "risk_score": r[5],
                "recommendation": r[6],
                "date": r[7],
                "image": r[8],
                "root_cause": r[9] if r[9] else compute_root_cause(r[0])
            })

        return jsonify(result)

    except Exception as e:
        print("REPORT ERROR:", e)
        return jsonify([])

@app.route('/register', methods=['POST'])
def register():
    data = request.json

    username = data.get("username")
    password = data.get("password")
    company = data.get("company")

    conn = get_db()
    c = conn.cursor()

    # create or get company
    c.execute("SELECT id FROM companies WHERE name=?", (company,))
    comp = c.fetchone()

    if not comp:
        c.execute("INSERT INTO companies (name) VALUES (?)", (company,))
        conn.commit()
        company_id = c.lastrowid
    else:
        company_id = comp[0]

    try:
        c.execute("INSERT INTO users (username, password, company_id, is_admin) VALUES (?, ?, ?, ?)",
                  (username, password, company_id, 1))  # Default to admin for now
        conn.commit()
    except:
        return jsonify({"error": "User exists"}), 400

    conn.close()
    return jsonify({"message": "Admin user registered successfully"})


def analyze_with_gpt(hazard_desc):
    """
    EGPC Risk Matrix Analysis - Comprehensive Risk Assessment
    Severity: A-F (numeric 6-1)
    Probability: 1-6
    Risk Score: Severity × Probability
    """

    if not client:
        return [{
            "step": 1,
            "hazard": "N/A",
            "severity": "A",
            "probability": 1,
            "risk_score": 6,
            "risk_level": "LOW",
            "color": "#22c55e",
            "controls": "AI not initialized",
            "residual_level": "A",
            "residual_score": 6
        }]

    prompt = f"""You are a VETERAN SAFETY MANAGER with 25+ years of experience in Oil & Gas industry, specializing in HSE risk assessments using EGPC standards. Your expertise spans major oil fields, refineries, and offshore operations across the Middle East.

Analyze this hazard: {hazard_desc}

As a seasoned professional with decades of frontline experience, provide 3-5 SPECIFIC, PRACTICAL risk scenarios with CONTROL MEASURES that reflect real-world HSE management wisdom.

REQUIREMENTS:
- Severity: Single letter A, B, C, D, E, or F ONLY
- Probability: Single number 1-6 ONLY (NOT text like "RARE")
- controls: Professional control measures written as a safety manager would document them - specific, actionable, and based on industry best practices. Use actual line breaks with \\n for readability. Include hierarchy of controls (Elimination, Substitution, Engineering, Administrative, PPE)
- residual_level: Single letter A, B, C, D, E, or F ONLY

STRICT JSON OUTPUT (no markdown, no code blocks, pure JSON):
[
  {{"hazard": "Description", "severity": "B", "probability": 3, "controls": "1. Engineering Control: Install guardrails and signage\\n2. Administrative Control: Implement work permit system\\n3. PPE: Safety harness and helmet required", "residual_level": "D"}},
  {{"hazard": "Description", "severity": "C", "probability": 4, "controls": "1. Eliminate hazard through process redesign\\n2. Train all personnel on emergency procedures\\n3. Regular equipment inspections", "residual_level": "E"}}
]

Generate exactly 3 hazards minimum. Focus on PRACTICAL, IMPLEMENTABLE solutions based on your 25+ years of HSE experience."""

    try:
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=1500
        )

        txt = res.choices[0].message.content.strip()
        print(f"[DEBUG] Raw AI response:\n{txt[:500]}\n")

        # Clean markdown code blocks
        if "```" in txt:
            txt = txt.replace("```json", "").replace("```", "").strip()

        # Remove any text before first [ or after last ]
        import re, json
        match = re.search(r'\[.*\]', txt, re.DOTALL)
        if match:
            txt = match.group()
        else:
            print(f"[ERROR] No JSON array found in response")
            raise ValueError("AI response doesn't contain valid JSON array")

        result = json.loads(txt)
        if not isinstance(result, list):
            result = [result] if isinstance(result, dict) else []

        if not result:
            raise ValueError("Empty result array")

        # EGPC Mapping
        sev_map = {'A': 6, 'B': 5, 'C': 4, 'D': 3, 'E': 2, 'F': 1}
        sev_convert = {"HIGH": "B", "MEDIUM": "D", "LOW": "F", "CRITICAL": "A"}
        prob_convert = {"RARE": 1, "UNLIKELY": 2, "POSSIBLE": 3, "LIKELY": 4, "VERY LIKELY": 5, "CERTAIN": 6}

        for idx, item in enumerate(result, 1):
            # Severity conversion
            sev = str(item.get("severity", "C")).upper().strip()
            if len(sev) > 1 or sev not in ['A', 'B', 'C', 'D', 'E', 'F']:
                sev = sev_convert.get(sev, "C")
            sev = sev[0]  # Ensure single letter

            # Probability conversion
            prob_raw = str(item.get("probability", "3")).upper().strip()
            try:
                prob = int(prob_raw)
            except:
                prob = prob_convert.get(prob_raw, 3)
            prob = max(1, min(6, prob))

            # Risk Score
            sev_val = sev_map.get(sev, 4)
            score = sev_val * prob

            # Risk Level & Color
            if score <= 6:
                level, color = "LOW", "#22c55e"
            elif score <= 12:
                level, color = "MEDIUM", "#ffc107"
            elif score <= 24:
                level, color = "HIGH", "#fd7e14"
            else:
                level, color = "CRITICAL", "#dc3545"

            # Residual Level
            res_sev = str(item.get("residual_level", "E")).upper().strip()
            if len(res_sev) > 1 or res_sev not in ['A', 'B', 'C', 'D', 'E', 'F']:
                res_sev = chr(ord(sev) + 1) if ord(sev) < ord('F') else 'F'
            res_sev = res_sev[0]

            res_val = sev_map.get(res_sev, 3)
            residual_score = res_val * 1

            # Update item with all required fields
            item["step"] = idx
            item["hazard"] = str(item.get("hazard", "Unknown hazard")).strip()[:150]
            item["severity"] = sev
            item["probability"] = prob
            item["risk_score"] = score
            item["risk_level"] = level
            item["color"] = color
            item["controls"] = str(item.get("controls", "N/A")).replace("\\n", "\n")
            item["residual_level"] = res_sev
            item["residual_score"] = residual_score

        # Ensure minimum 3 hazards
        if len(result) < 3:
            base = result[0].copy()
            for i in range(len(result), 3):
                new_item = base.copy()
                new_item["step"] = i + 1
                new_item["hazard"] = base.get("hazard", "Hazard") + f" (Scenario {i+1})"
                result.append(new_item)

        return result

    except json.JSONDecodeError as e:
        print(f"[ERROR] JSON Parse Error: {e}")
        print(f"[ERROR] Attempted to parse: {txt[:300]}")
        return [{
            "step": 1,
            "hazard": f"JSON Parse Error",
            "severity": "A",
            "probability": 1,
            "risk_score": 6,
            "risk_level": "LOW",
            "color": "#22c55e",
            "controls": f"Failed to parse AI response: {str(e)[:80]}",
            "residual_level": "F",
            "residual_score": 1
        }]
    except Exception as e:
        print(f"[ERROR] EGPC Analysis Error: {type(e).__name__}: {e}")
        return [{
            "step": 1,
            "hazard": "Analysis Error",
            "severity": "A",
            "probability": 1,
            "risk_score": 6,
            "risk_level": "LOW",
            "color": "#22c55e",
            "controls": f"Error: {str(e)[:100]}",
            "residual_level": "F",
            "residual_score": 1
        }]

@app.route('/assess_risk', methods=['POST'])
def assess_risk():

    data = request.get_json()
    desc = data.get("description", "").strip()

    if not desc or len(desc) < 5:
        return jsonify([{"error": "Description too short"}]), 400

    result = analyze_with_gpt(desc)

    return jsonify(result)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get("username")
        password = request.form.get("password")
        company = request.form.get("company", "default")

        # Get or create company
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT id FROM companies WHERE name=?", (company,))
        comp = c.fetchone()

        if not comp:
            c.execute("INSERT INTO companies (name) VALUES (?)", (company,))
            conn.commit()
            company_id = c.lastrowid
        else:
            company_id = comp[0]

        # Check admin credentials for this company
        c.execute("SELECT id FROM users WHERE username=? AND password=? AND company_id=? AND is_admin=1",
                  (username, password, company_id))
        admin_user = c.fetchone()
        conn.close()

        if admin_user:
            session['admin'] = True
            session['company_id'] = company_id
            session['company_name'] = company
            return redirect(f'/dashboard?company={company}')
        else:
            return "❌ Wrong credentials or not an admin user"

    # Get company from URL parameter
    company = request.args.get('company', 'default')
    return render_template("login.html", company=company)

@app.route('/companies')
def companies():
    return render_template("companies.html")

@app.route('/dashboard')
def dashboard():
    if not session.get('admin'):
        company = request.args.get('company', 'default')
        return redirect(f'/login?company={company}')

    # Ensure the user has access to the requested company
    company = request.args.get('company', 'default')
    if session.get('company_name') != company:
        return redirect(f'/login?company={company}')

    return render_template("dashboard.html")

@app.route('/submit', methods=['POST'])
def submit():
    try:
        desc = request.form.get('description') or ""
        loc = request.form.get('location')
        emp_id = request.form.get('emp')
        name = request.form.get('name')
        

        if not loc or not emp_id or not name:
            return jsonify({"error": "Missing data"}), 400

        # ================= 📷 IMAGE UPLOAD =================
        UPLOAD_FOLDER = "static/uploads"
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)

        file = request.files.get("image")
        image_path = None

        if file and file.filename:
            filename = file.filename
            image_path = os.path.join(UPLOAD_FOLDER, filename)
            file.save(image_path)

        # ================= 📷 IMAGE AI =================
        image_ai = None
        if image_path:
            try:
                image_ai = analyze_image(image_path)
            except Exception as e:
                print("IMAGE AI ERROR:", e)

        # ================= AI ENGINE =================
        try:
            ai = classify_with_ai(desc, image_ai)
        except Exception as e:
            print("AI ERROR:", e)
            ai = None

        hazard = "General"
        report_type = "Observation"
        severity = "LOW"
        risk_score = 5

        immediate = []
        corrective = []
        preventive = []
        justification = ""

        if ai:
            hazard = ai.get("hazard_category", "General")
            report_type = validate_classification(desc, ai.get("report_type"))
            severity_num = map_severity(ai.get("severity", "MEDIUM"))
            likelihood = 3
            risk_score, risk_level = calculate_risk(severity_num, likelihood)
            severity = risk_level.upper()

            immediate = ai.get("immediate_actions", [])
            corrective = ai.get("corrective_actions", [])
            preventive = ai.get("preventive_actions", [])

            justification = ai.get("justification")

        # ================= FORCE JUSTIFICATION =================
        if not justification or justification.strip() == "":
            justification = f"Risk classified as {severity} due to {hazard} hazard."

        # ================= RECOMMENDATION =================
        recommendation = (
            "🔴 Immediate:<br>" + "<br>".join(immediate) +
            "<br><br>🟡 Corrective:<br>" + "<br>".join(corrective) +
            "<br><br>🟢 Preventive:<br>" + "<br>".join(preventive)
        )

        # ================= DB (FIXED) =================
        try:
            conn = get_db()
            c = conn.cursor()

            # COMPANY
            company_id = g.company_id
            
            root_cause = ai.get("root_cause", "") if ai else ""

            # INSERT
            c.execute("""
            INSERT INTO reports 
            (description, location, type, event, severity, risk_score, recommendation, emp_id, date, image, company_id, root_cause, hazard_class)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                desc,
                loc,
                hazard,
                report_type,
                severity,
                risk_score,
                recommendation,
                emp_id,
                datetime.now().strftime("%Y-%m-%d"),
                image_path,
                company_id,
                root_cause,
                hazard
            ))

            conn.commit()

        except Exception as db_err:
            print("DB ERROR:", db_err)

        finally:
            try:
                c.close()
                conn.close()
            except:
                pass

        add_points(emp_id, name, 10)

        # ================= RESPONSE =================
        return jsonify({
            "message": "Report submitted successfully",
            "report_type": report_type,
            "hazard": hazard,
            "severity": severity,
            "risk_score": risk_score,
            "recommendation": recommendation,
            "justification": justification,
            "image": image_path,
            "points_awarded": 10
        })

    except Exception as e:
        print("SUBMIT ERROR:", e)
        return jsonify({"error": "Server failed"}), 500

# ================== LEADERBOARD ROUTES ==================
def generate_management_decision(data):
    decisions = []

    high_risk = [r for r in data if r["severity"] == "HIGH"]
    near_miss = [r for r in data if r["event"] == "Near Miss"]
    hazards = [r["hazard"] for r in data]

    # 🔴 HIGH RISK → ISO 45001
    if len(high_risk) >= 2:
        decisions.append(
            "🚨 ISO 45001 (Clause 6.1.2): Organization must perform risk assessment and implement risk control measures immediately."
        )

    # 🟠 NEAR MISS → OSHA
    if len(near_miss) >= 3:
        decisions.append(
            "⚠ OSHA Requirement: Increase safety training and awareness programs due to repeated near-miss incidents."
        )

    # 🔥 FIRE / PROCESS → NFPA
    if any("Process Safety" in h or "Fire" in h for h in hazards):
        decisions.append(
            "🔥 NFPA Compliance Required: Inspect fire protection systems, gas detection, and emergency response readiness."
        )

    # 📊 TREND → MANAGEMENT SYSTEM
    if len(data) >= 5:
        decisions.append(
            "📊 ISO 45001 (Clause 9): Conduct internal HSE audit and performance evaluation based on increasing reports."
        )

    if not decisions:
        decisions.append(
            "✅ Safety performance acceptable. Continue monitoring as per ISO 45001 Clause 9."
        )

    return decisions

@app.route('/decision-engine')
def decision_engine():
    """Get strategic decisions and recommendations"""
    print("=== DECISION ENGINE ROUTE HIT ===")
    try:
        conn = get_db()
        c = conn.cursor()
        
        # Get all reports
        c.execute("""
        SELECT severity, type, event, type, risk_score 
        FROM reports
        WHERE company_id=?
        """, (g.company_id,))
        reports = c.fetchall()
        conn.close()
        
        if not reports:
            return jsonify({
                "status": "No data available",
                "total_reports": 0,
                "high_risk_count": 0,
                "medium_risk_count": 0,
                "avg_risk_score": 0,
                "risk_level": "LOW",
                "top_hazards": [],
                "event_breakdown": [],
                "priorities": [],
                "recommendations": ["📊 No reports yet. Submit safety reports to populate the Decision Engine."],
                "trends": [],
                "management_decisions": []
            })
        
        # Analyze data
        high_risk = [r for r in reports if r[0] == "HIGH"]
        medium_risk = [r for r in reports if r[0] == "MEDIUM"]
        hazards = Counter([r[3] for r in reports if r[3]])
        events = Counter([r[2] for r in reports if r[2]])
        avg_score = sum(r[4] for r in reports) / len(reports)
        
        # Generate priorities
        priorities = []

        if len(high_risk) > 0:
            priorities.append({
                "rank": "🔴 CRITICAL",
                "title": f"High Risk Issues ({len(high_risk)} cases)",
                "action": "Immediate escalation and remediation required",
                "impact": "Prevents incidents and injuries"
            })

        if len(medium_risk) > 0:
            priorities.append({
                "rank": "🟠 HIGH PRIORITY",
                "title": f"Medium Risk Issues ({len(medium_risk)} cases)",
                "action": "Schedule corrective actions within 30 days",
                "impact": "Reduces operational disruptions"
            })

        if hazards:
            top_hazard = hazards.most_common(1)[0]
            priorities.append({
                "rank": "🟡 FOCUS AREA",
                "title": f"Most Common Hazard: {top_hazard[0]} ({top_hazard[1]} occurrences)",
                "action": "Implement targeted control measures",
                "impact": "Prevents recurring hazards"
            })
        
        # Recommendations
        recommendations = []

        if avg_score > 15:
            recommendations.append("⚠️ Overall risk score is HIGH - Conduct comprehensive risk reassessment")

        if "Near Miss" in events:
            count = events.get("Near Miss", 0)
            recommendations.append(f"📌 {count} Near Misses recorded - Establish near-miss investigation procedures")

        if "Incident" in events:
            count = events.get("Incident", 0)
            recommendations.append(f"🚨 {count} Incidents reported - Implement emergency response drills")

        if len(high_risk) / len(reports) > 0.3:
            recommendations.append("🎯 More than 30% of reports are HIGH RISK - Increase safety inspections")

        if not recommendations:
            recommendations.append("✅ Keep monitoring - Continue current safety practices")
        
        # Trends
        trends = []

        if len(high_risk) > len(medium_risk):
            trends.append("📈 Trend: Severity is increasing - Urgent action required")
        else:
            trends.append("📉 Trend: Risk mitigation is working - Continue preventive measures")

        if hazards:
            trends.append(f"🔍 Most affected area: {hazards.most_common(1)[0][0]}")
        
        # Risk level
        if len(high_risk) / len(reports) > 0.5:
            risk_level = "CRITICAL"
        elif len(high_risk) / len(reports) > 0.2:
            risk_level = "HIGH"
        elif avg_score > 15:
            risk_level = "MEDIUM"
        else:
            risk_level = "LOW"
        
        # ================= MANAGEMENT DECISIONS =================
        data = []
        for r in reports:
            data.append({
                "severity": r[0],
                "type": r[1],
                "event": r[2],
                "hazard": r[3],
                "risk_score": r[4]
            })

        management_decisions = generate_management_decision(data)
        
        # ================= RETURN =================
        return jsonify({
            "status": "Analysis Complete",
            "total_reports": len(reports),
            "high_risk_count": len(high_risk),
            "medium_risk_count": len(medium_risk),
            "avg_risk_score": round(avg_score, 2),
            "risk_level": risk_level,
            "top_hazards": [{"hazard": h[0], "count": h[1]} for h in hazards.most_common(5)],
            "event_breakdown": [{"event": e[0], "count": e[1]} for e in events.most_common()],
            "priorities": priorities,
            "recommendations": recommendations,
            "trends": trends,
            "management_decisions": management_decisions
        })
    
    except Exception as e:
        print(f"Decision Engine Error: {e}")
        return jsonify({"error": str(e), "priorities": [], "recommendations": [], "management_decisions": []})
@app.route('/leaderboard')
def leaderboard():
    try:
        conn = get_db()
        c = conn.cursor()

        # ❌ امسح sample data نهائي
        # (متضيفش بيانات وهمية)

        c.execute("""
        SELECT name, points 
        FROM users
        WHERE name IS NOT NULL AND name != ''
        ORDER BY points DESC
        LIMIT 10
        """)

        rows = c.fetchall()
        conn.close()

        result = []
        for r in rows:
            result.append({
                "name": r[0],
                "points": r[1]
            })

        return jsonify(result)

    except Exception as e:
        print("Error in /leaderboard:", e)
        return jsonify([])
# ================== RUN ==================

import os

if __name__ == '__main__':
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=False
    )
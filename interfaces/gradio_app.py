"""
Health Assistant — Gradio UI
=============================
Full web interface for interacting with agents and managing all user data.

Run from the project root:
    python interfaces/gradio_app.py
    # or with auto-reload:
    gradio interfaces/gradio_app.py
"""

import json
import re
import sqlite3
import sys
import uuid
from datetime import datetime
from pathlib import Path

import gradio as gr

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import BASE_DIR, SQLITE_DB, SQLITE_SESSIONS
from knowledge import get_knowledge_base
from tools.profile_tools import (
    add_food_preference,
    add_health_goal,
    update_user_profile,
)
from tools.nutrition_tools import calculate_daily_calories

# ── Agent team (lazy init) ───────────────────────────────
_team = None
_user_sessions: dict[str, str] = {}


def _get_team():
    global _team
    if _team is None:
        from agents.coordinator import create_health_team
        _team = create_health_team()
    return _team


def _get_session(uid: str) -> str:
    if uid not in _user_sessions:
        _user_sessions[uid] = f"ui_{uid}"
    return _user_sessions[uid]


def _reset_session(uid: str) -> str:
    _user_sessions[uid] = f"ui_{uid}_{uuid.uuid4().hex[:6]}"
    return _user_sessions[uid]


def _sanitize_reply(text: str) -> str:
    """Replace raw API errors with user-friendly messages."""
    t = text.lower()
    if "429" in t or "too many requests" in t or "resource_exhausted" in t or "quota" in t:
        return "De momento estou com muitos pedidos em simultâneo. Por favor, aguarda uns segundos e tenta novamente. 🙏"
    if "bound method" in t or "clientresponse" in t or "exception" in t or "traceback" in t:
        return "Ocorreu um problema ao processar o teu pedido. Por favor, tenta novamente. 🙏"
    return text


def _extract_text(response) -> str:
    if response is None:
        return ""
    if hasattr(response, "content"):
        if isinstance(response.content, str):
            return response.content
        if isinstance(response.content, list):
            parts = []
            for item in response.content:
                if hasattr(item, "text"):
                    parts.append(item.text)
                elif isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and "text" in item:
                    parts.append(item["text"])
            return "\n".join(parts)
    if hasattr(response, "messages"):
        for msg in reversed(response.messages):
            if hasattr(msg, "content") and msg.role == "assistant":
                return msg.content
    return str(response)


def _db_conn(path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


# ═══════════════════════════════════════════════════════
# USER LIST & STATUS
# ═══════════════════════════════════════════════════════

def list_users():
    """Returns the list of registered users for the dropdown."""
    try:
        conn = _db_conn(SQLITE_DB)
        rows = conn.execute(
            "SELECT user_id, name FROM user_profiles ORDER BY name IS NULL, name, user_id"
        ).fetchall()
        conn.close()
        choices = []
        for r in rows:
            label = f"{r['name']} ({r['user_id']})" if r["name"] else str(r["user_id"])
            choices.append((label, r["user_id"]))
        return choices
    except Exception:
        return []


def check_user_status(uid) -> str:
    uid = (uid or "").strip()
    if not uid:
        return ""
    try:
        conn = _db_conn(SQLITE_DB)
        row = conn.execute(
            "SELECT name FROM user_profiles WHERE user_id = ?", (uid,)
        ).fetchone()
        conn.close()
        if row:
            name = row["name"] or uid
            return f"✅ **{name}**"
        return "🆕 Utilizador novo — preenche o teu perfil!"
    except Exception:
        return ""


# ═══════════════════════════════════════════════════════
# TAB 1 — CONVERSA
# ═══════════════════════════════════════════════════════

async def chat_fn(message: str, history: list, user_id: str):
    """Sends a message to the agent team and returns the response."""
    from xai import get_tracker
    tracker = get_tracker()
    tracker.reset(message)

    user_msg = {"role": "user", "content": message}

    if not user_id.strip():
        yield history + [
            user_msg,
            {"role": "assistant", "content": "❌ Introduz um User ID primeiro."},
        ], tracker.generate_markdown(), ""
        return

    # Clear input and show user message + loading indicator immediately
    yield history + [user_msg, {"role": "assistant", "content": "⏳ A processar…"}], tracker.generate_markdown(), ""

    uid = user_id.strip()
    today = datetime.now().strftime("%d/%m/%Y")
    enriched = f"[Data de hoje: {today}] [ID do utilizador: {uid}]\n{message}"
    session_id = _get_session(uid)

    try:
        team = _get_team()
        response = await team.arun(enriched, session_id=session_id, user_id=uid)
        reply = _extract_text(response)
        if not reply:
            reply = "Desculpa, não consegui processar. Tenta reformular. 🤔"
        else:
            reply = _sanitize_reply(reply)
    except Exception as e:
        reply = _sanitize_reply(str(e))

    yield history + [
        user_msg,
        {"role": "assistant", "content": reply},
    ], tracker.generate_markdown(), ""


def reset_chat(user_id: str):
    if user_id.strip():
        _reset_session(user_id.strip())
    return [], "Nova sessão iniciada. Conversa limpa."


# ═══════════════════════════════════════════════════════
# TAB 2 — PERFIL
# ═══════════════════════════════════════════════════════

def load_profile(user_id):
    uid = (user_id or "").strip()
    if not uid:
        return ("", "", "", "", None, None, None, "")
    conn = _db_conn(SQLITE_DB)
    row = conn.execute(
        "SELECT * FROM user_profiles WHERE user_id = ?", (uid,)
    ).fetchone()
    conn.close()
    if not row:
        return ("", "", "", "", None, None, None, "")
    # Format birth_date as DD/MM/YYYY for display
    bd_iso = row["birth_date"] or ""
    bd_display = bd_iso
    if bd_iso:
        try:
            bd_display = datetime.strptime(bd_iso[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
        except Exception:
            pass
    from tools.profile_tools import _age_from_birth_date
    age = _age_from_birth_date(bd_iso)
    age_str = f"{age} anos" if age is not None else ""
    return (
        row["name"] or "",
        bd_display,
        age_str,
        row["gender"] or None,
        row["height_cm"],
        row["weight_kg"],
        row["activity_level"] or None,
        row["goal"] or "",
    )


def save_profile(user_id, name, birth_date_str, gender, height_cm, weight_kg, activity_level, goal):
    uid = user_id.strip()
    if not uid:
        return "❌ Introduz um User ID."
    try:
        birth_date_iso = None
        if birth_date_str and str(birth_date_str).strip():
            bd = str(birth_date_str).strip()
            for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
                try:
                    birth_date_iso = datetime.strptime(bd, fmt).strftime("%Y-%m-%d")
                    break
                except ValueError:
                    continue
        update_user_profile(
            uid,
            name=name or None,
            birth_date=birth_date_iso,
            gender=gender or None,
            height_cm=float(height_cm) if height_cm else None,
            weight_kg=float(weight_kg) if weight_kg else None,
            activity_level=activity_level or None,
            goal=goal or None,
        )
        return "✅ Perfil guardado com sucesso!"
    except Exception as e:
        return f"❌ Erro: {e}"


def load_weight_chart(user_id, period: str = "Último Ano") -> str:
    import html as _html
    import json
    from datetime import datetime, timedelta

    uid = (user_id or "").strip()
    _empty = (
        "<div style='color:#64748b;padding:60px;text-align:center;"
        "background:#0f172a;border-radius:12px;font-family:Inter,sans-serif'>"
        "Sem dados de peso. Regista o primeiro valor acima.</div>"
    )
    if not uid:
        return ""

    conn = _db_conn(SQLITE_DB)
    rows = conn.execute(
        """SELECT recorded_at, weight_kg FROM weight_history
           WHERE user_id = ? ORDER BY recorded_at ASC""",
        (uid,),
    ).fetchall()
    conn.close()

    if not rows:
        return _empty

    all_data = [(r["recorded_at"][:10], float(r["weight_kg"])) for r in rows]

    if period == "Últimas 10":
        data = all_data[-10:]
    else:
        period_days = {
            "Último Mês": 30,
            "Últimos 6 Meses": 180,
            "Último Ano": 365,
            "Últimos 5 Anos": 1825,
        }
        days = period_days.get(period, 365)
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        data = [(d, w) for d, w in all_data if d >= cutoff]

    if not data:
        return _empty

    labels_json = json.dumps([d for d, _ in data])
    weights_json = json.dumps([w for _, w in data])

    inner = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #0f172a; overflow: hidden; font-family: Inter, sans-serif; }}
  .wrap {{ background: #0f172a; padding: 14px 18px 10px; height: 100vh;
           display: flex; flex-direction: column; gap: 10px; }}
  .header {{ display: flex; justify-content: space-between; align-items: baseline; }}
  .title {{ color: #cbd5e1; font: 600 12px/1 Inter, sans-serif; letter-spacing: .08em; }}
  .hint {{ color: #334155; font-size: 10px; }}
  canvas {{ flex: 1; min-height: 0; }}
  .info-wrap {{ display: inline-flex; align-items: center; gap: 6px; }}
  .info-btn {{
    display: inline-flex; align-items: center; justify-content: center;
    width: 16px; height: 16px; border-radius: 50%;
    background: rgba(203,213,225,0.15); color: #94a3b8;
    font: 600 10px/1 Inter, sans-serif; cursor: pointer;
    border: 1px solid rgba(203,213,225,0.25); user-select: none;
    transition: background .2s;
  }}
  .info-btn:hover {{ background: rgba(203,213,225,0.3); }}
  .info-overlay {{
    display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(15,23,42,0.97); padding: 14px 18px; overflow-y: auto;
    color: #cbd5e1; font: 400 12px/1.75 Inter,sans-serif; z-index: 100; cursor: default;
  }}
</style>
</head>
<body>
<div class="wrap">
  <div class="header">
    <div class="info-wrap">
      <span class="title">TRENDS</span>
      <span class="info-btn" id="info-btn">i</span>
    </div>
    <span class="hint">scroll → zoom &nbsp;·&nbsp; arrastar → mover &nbsp;·&nbsp; duplo clique → repor</span>
  </div>
  <canvas id="c"></canvas>
</div>
<div id="info-overlay" class="info-overlay">Weight is the total mass of your body in kilo&#39;s/pounds. This measurement includes all of the elements of your body hence bones, blood, organs, muscles, and fat. Your weight is determined by different factors including hereditary components, hormonal abnormalities, exercise, diet, and lifestyle. Being underweight or overweight can significantly impact your physical and psychological wellbeing. However, weight only will not give you any indication as to how much of your weight is muscle and how much is fat. Therefore, a complete picture of your health can only be obtained through an accurate body composition monitor checking different measurements other than body weight.</div>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/hammerjs@2.0.8/hammer.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.0.1/dist/chartjs-plugin-zoom.min.js"></script>
<script>
const labels  = {labels_json};
const weights = {weights_json};

const crosshair = {{
  id: 'crosshair',
  afterDraw(chart) {{
    if (!chart._ch) return;
    const {{ctx, chartArea: {{left, right, top, bottom}}}} = chart;
    const {{x, y}} = chart._ch;
    ctx.save();
    ctx.strokeStyle = 'rgba(203,213,225,0.2)';
    ctx.lineWidth = 1;
    ctx.setLineDash([5, 4]);
    ctx.beginPath(); ctx.moveTo(x, top);  ctx.lineTo(x, bottom); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(right, y);  ctx.stroke();
    ctx.restore();
  }}
}};

const canvas = document.getElementById('c');
const chart  = new Chart(canvas, {{
  type: 'line',
  plugins: [crosshair],
  data: {{
    labels,
    datasets: [{{
      data: weights,
      borderColor: '#e11d48',
      borderWidth: 2,
      pointBackgroundColor: 'white',
      pointBorderColor: '#e11d48',
      pointBorderWidth: 1.5,
      pointRadius: 4,
      pointHoverRadius: 7,
      fill: true,
      backgroundColor(ctx) {{
        const g = ctx.chart.ctx.createLinearGradient(0, 0, 0, (ctx.chart.chartArea || {{}}).bottom || 300);
        g.addColorStop(0, 'rgba(225,29,72,0.35)');
        g.addColorStop(1, 'rgba(225,29,72,0.02)');
        return g;
      }},
      tension: 0.25,
    }}]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    interaction: {{ mode: 'index', intersect: false }},
    animation: {{ duration: 350 }},
    plugins: {{
      legend: {{ display: false }},
      tooltip: {{
        backgroundColor: '#1e293b',
        borderColor: '#334155',
        borderWidth: 1,
        titleColor: '#94a3b8',
        bodyColor: '#f9fafb',
        bodyFont: {{ size: 13, weight: '600' }},
        padding: 10,
        callbacks: {{ label: (i) => ` ${{i.raw.toFixed(1)}} kg` }}
      }},
      zoom: {{
        zoom: {{ wheel: {{ enabled: true }}, pinch: {{ enabled: true }}, mode: 'x' }},
        pan:  {{ enabled: true, mode: 'x' }},
      }}
    }},
    scales: {{
      x: {{
        ticks: {{ color: '#475569', maxTicksLimit: 8, maxRotation: 0, font: {{ size: 11 }} }},
        grid:  {{ color: 'rgba(255,255,255,0.05)' }},
        border: {{ color: 'rgba(255,255,255,0.08)' }},
      }},
      y: {{
        ticks: {{ color: '#475569', font: {{ size: 11 }}, callback: v => v + ' kg' }},
        grid:  {{ color: 'rgba(255,255,255,0.05)' }},
        border: {{ color: 'rgba(255,255,255,0.08)' }},
      }}
    }}
  }}
}});

canvas.addEventListener('mousemove', (e) => {{
  const r = canvas.getBoundingClientRect();
  chart._ch = {{ x: e.clientX - r.left, y: e.clientY - r.top }};
  chart.draw();
}});
canvas.addEventListener('mouseleave', () => {{
  chart._ch = null;
  chart.draw();
}});

(function() {{
  var btn = document.getElementById('info-btn');
  var overlay = document.getElementById('info-overlay');
  var hideT;
  if (!btn || !overlay) return;
  btn.addEventListener('mouseenter', function() {{ clearTimeout(hideT); overlay.style.display = 'block'; }});
  btn.addEventListener('mouseleave', function() {{ hideT = setTimeout(function() {{ overlay.style.display = 'none'; }}, 150); }});
  overlay.addEventListener('mouseenter', function() {{ clearTimeout(hideT); }});
  overlay.addEventListener('mouseleave', function() {{ overlay.style.display = 'none'; }});
}})();
</script>
</body>
</html>"""

    escaped = _html.escape(inner, quote=True)
    return f'<iframe srcdoc="{escaped}" style="width:100%;height:380px;border:none;border-radius:12px;display:block;"></iframe>'


# ── Body composition charts ─────────────────────────────────────────────────

_COMP_METRICS = {
    "bmi", "body_fat_pct", "visceral_fat", "muscle_mass_kg",
    "muscle_quality", "bone_mass_kg", "bmr_kcal", "metabolic_age",
    "body_water_pct", "physique_rating",
}

_INFO_BODY_WATER = (
    "Body water is an essential part of staying healthy. Over half the body consists of water. "
    "It regulates body temperature and helps eliminate waste. You lose water continuously through "
    "urine, sweat and breathing, so it&#39;s important to keep replacing it. The amount of fluid "
    "needed every day varies from person to person and is affected by climatic conditions and how "
    "much physical activity you undertake. Being well hydrated helps concentration levels, sports "
    "performance and general wellbeing. Experts recommend that you should drink at least two litres "
    "of fluid each day, preferably water or other low calorie drinks. If you are training, it&#39;s "
    "important to increase your fluid intake to ensure peak performance at all times. "
    "Read all about body water. "
    "The average TBW% ranges for a healthy person are: Female 45 to 60% Male 50 to 65%"
)
_INFO_BODY_FAT = (
    "Body fat percentage is the proportion of your total body weight that consists of fat tissue. "
    "Your body needs a certain amount of essential fat to maintain life and reproductive functions — "
    "fat also surrounds and protects internal organs. As your activity level changes, the balance of "
    "body fat and muscle mass will gradually change, which affects your overall physique. "
    "A high body fat percentage increases the risk of cardiovascular disease, type 2 diabetes and "
    "other metabolic conditions. Reducing body fat through exercise and a balanced diet improves "
    "health markers and energy levels. The physique rating provided by your Body Composition Monitor "
    "gives you insight into what body type you currently have based on the balance between body fat "
    "and muscle mass. "
    "Typical healthy body fat ranges — Female: 20–35% · Male: 8–24%"
)
_INFO_BMI = (
    "Your BMI can be calculated by dividing your weight (in kilograms) by the square of your height "
    "(in meters). BMI is a good general indicator for population studies but has serious limitation "
    "when assessing on an individual level."
)
_INFO_VISCERAL_FAT = (
    "Visceral fat is located deep in the core abdominal area, surrounding and protecting the vital "
    "organs. Even if your weight and body fat remains constant, as you get older the distribution of "
    "fat changes and is more likely to shift to the abdominal area. Ensuring you have a healthy level "
    "of visceral fat directly reduces the risk of certain diseases such as heart disease, high blood "
    "pressure and may delay the onset of type 2 diabetes. Measuring your visceral fat with a body "
    "composition monitor helps you keep track of potential problems and test the effectiveness of "
    "your diet or training."
)
_INFO_MUSCLE_MASS = (
    "Muscle mass includes the skeletal muscles, smooth muscles such as cardiac and digestive muscles "
    "and the water contained in these muscles. Muscles act as an engine in consuming energy. As your "
    "muscle mass increases, the rate at which you burn energy (calories) increases which accelerates "
    "your basal metabolic rate (BMR) and helps you reduce excess body fat levels and lose weight in a "
    "healthy way. If you are exercising hard your muscle mass will increase and may increase your total "
    "body weight too. That&#39;s why it&#39;s important to monitor your measurements regularly to see "
    "the impact of your training programme on your muscle mass."
)
_INFO_BONE_MASS = (
    "The predicted weight of bone mineral in your body. While your bone mass is unlikely to undergo "
    "noticeable changes in the short term, it&#39;s important to maintain healthy bones by having a "
    "balanced diet rich in calcium and by doing plenty of weight-bearing exercise. You should track "
    "your bone mass over time and look for any long-term changes."
)
_INFO_BMR = (
    "Increasing muscle mass will speed up your basal metabolic rate (BMR). A person with a high BMR "
    "burns more calories at rest than a person with a low BMR. About 70% of calories consumed every "
    "day are used for your basal metabolism. Increasing your muscle mass helps raise your BMR, which "
    "increases the number of calories you burn and helps to decrease body fat levels. Your BMR "
    "measurement can be used as a minimum baseline for a diet programme. Additional calories can be "
    "included depending on your activity level. The more active you are the more calories you burn "
    "and the more muscle you build, so you need to ensure you consume enough calories to keep your "
    "body fit and healthy. As people age their metabolic rate changes. Basal metabolism rises as a "
    "child matures and peaks at around 16 or 17, after which point it typically starts to decrease. "
    "A slow BMR will make it harder to lose body fat and overall weight."
)
_INFO_METABOLIC_AGE = (
    "Compares your BMR to an average for your age group. This is calculated by comparing your basal "
    "metabolic rate (BMR) to the BMR average of your chronological age group. If your metabolic age "
    "is higher than your actual age, it&#39;s an indication that you need to improve your metabolic "
    "rate. Increased exercise will build healthy muscle tissue, which in turn will improve your "
    "metabolic age. Stay on track by monitoring regularly."
)


def load_composition_chart(
    user_id: str, metric: str, label: str, unit: str,
    period: str = "Último Ano", color: str = "#6366f1",
    info_text: str = "",
) -> str:
    import html as _html
    import json
    from datetime import datetime, timedelta

    uid = user_id.strip()
    if not uid or metric not in _COMP_METRICS:
        return ""

    conn = _db_conn(SQLITE_DB)
    rows = conn.execute(
        f"SELECT measured_at, {metric} FROM body_composition_history "
        f"WHERE user_id = ? AND {metric} IS NOT NULL ORDER BY measured_at ASC",
        (uid,),
    ).fetchall()
    conn.close()

    _no_data = (
        f"<div style='color:#475569;padding:30px;text-align:center;"
        f"background:#0f172a;border-radius:12px;font:12px Inter,sans-serif'>"
        f"{label}: sem dados</div>"
    )
    if not rows:
        return _no_data

    all_data = [(r["measured_at"][:10], float(r[metric])) for r in rows]
    if period == "Últimas 10":
        data = all_data[-10:]
    else:
        period_days = {"Último Mês": 30, "Últimos 6 Meses": 180, "Último Ano": 365, "Últimos 5 Anos": 1825}
        days = period_days.get(period, 365)
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        data = [(d, v) for d, v in all_data if d >= cutoff]

    if not data:
        return _no_data

    labels_json = json.dumps([d for d, _ in data])
    values_json = json.dumps([v for _, v in data])
    unit_js = json.dumps(unit)
    decimals = 0 if metric in ("metabolic_age", "physique_rating") else 1

    inner = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #0f172a; overflow: hidden; }}
  .wrap {{ background: #0f172a; padding: 10px 14px 6px; height: 100vh;
           display: flex; flex-direction: column; gap: 6px; }}
  .title-row {{ display: flex; align-items: center; gap: 5px; }}
  .title {{ color: #cbd5e1; font: 600 11px/1 Inter, sans-serif; letter-spacing: .06em; }}
  canvas {{ flex: 1; min-height: 0; }}
  .info-wrap {{ display: inline-flex; align-items: center; }}
  .info-btn {{
    display: inline-flex; align-items: center; justify-content: center;
    width: 14px; height: 14px; border-radius: 50%;
    background: rgba(203,213,225,0.15); color: #94a3b8;
    font: 600 9px/1 Inter, sans-serif; cursor: pointer;
    border: 1px solid rgba(203,213,225,0.25); user-select: none;
    transition: background .2s;
  }}
  .info-btn:hover {{ background: rgba(203,213,225,0.3); }}
  .info-overlay {{
    display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(15,23,42,0.97); padding: 12px 14px; overflow-y: auto;
    color: #cbd5e1; font: 400 11px/1.75 Inter,sans-serif; z-index: 100; cursor: default;
  }}
</style>
</head>
<body>
<div class="wrap">
  <div class="title-row">
    <span class="title">{label.upper()}</span>
    {"<span class='info-btn' id='info-btn'>i</span>" if info_text else ""}
  </div>
  <canvas id="c"></canvas>
</div>
{"<div id='info-overlay' class='info-overlay'>" + info_text + "</div>" if info_text else ""}
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/hammerjs@2.0.8/hammer.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.0.1/dist/chartjs-plugin-zoom.min.js"></script>
<script>
const labels  = {labels_json};
const values  = {values_json};
const unit    = {unit_js};
const dec     = {decimals};
const col     = '{color}';

const crosshair = {{
  id: 'crosshair',
  afterDraw(chart) {{
    if (!chart._ch) return;
    const {{ctx, chartArea: {{left, right, top, bottom}}}} = chart;
    const {{x, y}} = chart._ch;
    ctx.save();
    ctx.strokeStyle = 'rgba(203,213,225,0.18)';
    ctx.lineWidth = 1; ctx.setLineDash([5, 4]);
    ctx.beginPath(); ctx.moveTo(x, top);  ctx.lineTo(x, bottom); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(right, y);  ctx.stroke();
    ctx.restore();
  }}
}};

const canvas = document.getElementById('c');
const chart  = new Chart(canvas, {{
  type: 'line', plugins: [crosshair],
  data: {{
    labels,
    datasets: [{{
      data: values,
      borderColor: col, borderWidth: 2,
      pointBackgroundColor: 'white', pointBorderColor: col,
      pointBorderWidth: 1.5, pointRadius: 3, pointHoverRadius: 6,
      fill: true,
      backgroundColor(ctx) {{
        const ca = ctx.chart.chartArea || {{}};
        const g = ctx.chart.ctx.createLinearGradient(0, ca.top||0, 0, ca.bottom||200);
        g.addColorStop(0, col + '55'); g.addColorStop(1, col + '08');
        return g;
      }},
      tension: 0.25,
    }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    interaction: {{ mode: 'index', intersect: false }},
    animation: {{ duration: 300 }},
    plugins: {{
      legend: {{ display: false }},
      tooltip: {{
        backgroundColor: '#1e293b', borderColor: '#334155', borderWidth: 1,
        titleColor: '#94a3b8', bodyColor: '#f9fafb',
        bodyFont: {{ size: 12, weight: '600' }}, padding: 8,
        callbacks: {{ label: (i) => ` ${{i.raw.toFixed(dec)}}${{unit ? ' '+unit : ''}}` }}
      }},
      zoom: {{
        zoom: {{ wheel: {{ enabled: true }}, pinch: {{ enabled: true }}, mode: 'x' }},
        pan:  {{ enabled: true, mode: 'x' }},
      }}
    }},
    scales: {{
      x: {{
        ticks: {{ color: '#475569', maxTicksLimit: 5, maxRotation: 0, font: {{ size: 10 }} }},
        grid: {{ color: 'rgba(255,255,255,0.04)' }}, border: {{ color: 'rgba(255,255,255,0.06)' }},
      }},
      y: {{
        ticks: {{ color: '#475569', font: {{ size: 10 }},
                  callback: v => v.toFixed(dec) + (unit ? ' '+unit : '') }},
        grid: {{ color: 'rgba(255,255,255,0.04)' }}, border: {{ color: 'rgba(255,255,255,0.06)' }},
      }}
    }}
  }}
}});

canvas.addEventListener('mousemove', (e) => {{
  const r = canvas.getBoundingClientRect();
  chart._ch = {{ x: e.clientX - r.left, y: e.clientY - r.top }};
  chart.draw();
}});
canvas.addEventListener('mouseleave', () => {{ chart._ch = null; chart.draw(); }});

(function() {{
  var btn = document.getElementById('info-btn');
  var overlay = document.getElementById('info-overlay');
  var hideT;
  if (!btn || !overlay) return;
  btn.addEventListener('mouseenter', function() {{ clearTimeout(hideT); overlay.style.display = 'block'; }});
  btn.addEventListener('mouseleave', function() {{ hideT = setTimeout(function() {{ overlay.style.display = 'none'; }}, 150); }});
  overlay.addEventListener('mouseenter', function() {{ clearTimeout(hideT); }});
  overlay.addEventListener('mouseleave', function() {{ overlay.style.display = 'none'; }});
}})();
</script>
</body></html>"""

    escaped = _html.escape(inner, quote=True)
    return f'<iframe srcdoc="{escaped}" style="width:100%;height:230px;border:none;border-radius:12px;display:block;"></iframe>'


def load_all_comp_charts(user_id, period: str = "Último Ano") -> tuple:
    uid = (user_id or "").strip()
    if not uid:
        return ("",) * 8
    return (
        load_composition_chart(uid, "bmi",           "IMC (BMI)",         "",     period, "#8b5cf6", _INFO_BMI),
        load_composition_chart(uid, "body_fat_pct",  "Gordura Corporal",  "%",    period, "#f59e0b", _INFO_BODY_FAT),
        load_composition_chart(uid, "visceral_fat",  "Gordura Visceral",  "",     period, "#f97316", _INFO_VISCERAL_FAT),
        load_composition_chart(uid, "muscle_mass_kg","Massa Muscular",    "kg",   period, "#3b82f6", _INFO_MUSCLE_MASS),
        load_composition_chart(uid, "body_water_pct","Água Corporal",     "%",    period, "#06b6d4", _INFO_BODY_WATER),
        load_composition_chart(uid, "bmr_kcal",      "BMR",               "kcal", period, "#10b981", _INFO_BMR),
        load_composition_chart(uid, "metabolic_age", "Idade Metabólica",  "anos", period, "#ec4899", _INFO_METABOLIC_AGE),
        load_composition_chart(uid, "bone_mass_kg",  "Massa Óssea",       "kg",   period, "#14b8a6", _INFO_BONE_MASS),
    )


def gdpr_export_fn(user_id: str):
    uid = user_id.strip()
    if not uid:
        return "❌ Introduz um User ID.", gr.update(visible=False, value="")
    try:
        from tools.profile_tools import export_user_data
        data_json = export_user_data(uid)
        return "✅ Dados exportados com sucesso.", gr.update(visible=True, value=data_json)
    except Exception as e:
        return f"❌ Erro: {e}", gr.update(visible=False, value="")


def gdpr_delete_fn(user_id: str):
    uid = user_id.strip()
    empty_profile = ("", "", "", None, None, None, None, "")
    if not uid:
        return ("❌ Introduz um User ID.", *empty_profile, None)
    try:
        from tools.profile_tools import delete_all_user_data
        msg = delete_all_user_data(uid)
        return (msg, *empty_profile, None)
    except Exception as e:
        return (f"❌ Erro: {e}", *empty_profile, None)


def add_weight_entry(user_id: str, weight_str: str, period: str = "Último Ano"):
    uid = user_id.strip()
    empty_profile = ("", "", "", None, None, None, None, "")
    if not uid:
        return ("❌ Introduz um User ID.", None, weight_str, *empty_profile)
    try:
        weight = float(str(weight_str).strip().replace(",", "."))
        if weight <= 0 or weight > 500:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        return ("❌ Valor inválido. Exemplo: 74.8 ou 74,8", None, weight_str, *empty_profile)
    try:
        update_user_profile(uid, weight_kg=weight)
        profile = load_profile(uid)
        return (f"✅ Peso {weight} kg registado!", load_weight_chart(uid, period), None, *profile)
    except Exception as e:
        return (f"❌ Erro: {e}", None, weight_str, *empty_profile)


# ═══════════════════════════════════════════════════════
# TAB 3 — PREFERÊNCIAS
# ═══════════════════════════════════════════════════════

_PREF_CATS = ["food_likes", "food_dislikes", "allergies", "goals", "restrictions", "health_data"]


def _load_category_list(uid: str, category: str) -> list[str]:
    uid = uid.strip()
    if not uid:
        return []
    kb = get_knowledge_base()
    try:
        data = kb.preferences.get(
            where={"$and": [{"user_id": uid}, {"category": category}]}
        )
        if data and data.get("documents"):
            return sorted(data["documents"])
    except Exception:
        pass
    return []


def _delete_pref_exact(uid: str, doc_text: str) -> bool:
    """Delete an exact preference document, searching all categories."""
    kb = get_knowledge_base()
    for cat in _PREF_CATS:
        try:
            data = kb.preferences.get(
                where={"$and": [{"user_id": uid}, {"category": cat}]}
            )
            if data and data.get("ids"):
                for i, doc in enumerate(data["documents"]):
                    if doc == doc_text:
                        kb.preferences.delete(ids=[data["ids"][i]])
                        return True
        except Exception:
            pass
    return False


def load_all_prefs(uid):
    """Returns a gr.update for each of the 6 preference CheckboxGroups."""
    uid = (uid or "").strip()
    return tuple(
        gr.update(choices=_load_category_list(uid, cat), value=[])
        for cat in _PREF_CATS
    )


# Food likes
def add_like_fn(uid: str, food: str):
    uid = uid.strip()
    if not uid or not food.strip():
        return "❌ Preenche o User ID e o alimento.", gr.update(), ""
    add_food_preference(uid, food.strip(), likes=True)
    return (
        f"✅ '{food.strip()}' adicionado aos gostos.",
        gr.update(choices=_load_category_list(uid, "food_likes"), value=[]),
        "",
    )


def remove_likes_fn(uid: str, selected: list):
    uid = uid.strip()
    if not uid or not selected:
        return "❌ Seleciona pelo menos um item.", gr.update()
    for item in selected:
        _delete_pref_exact(uid, item)
    return (
        f"✅ {len(selected)} item(s) removido(s).",
        gr.update(choices=_load_category_list(uid, "food_likes"), value=[]),
    )


def move_to_dislikes_fn(uid: str, selected: list):
    uid = uid.strip()
    if not uid or not selected:
        return "❌ Seleciona itens para mover.", gr.update(), gr.update()
    for item in selected:
        _delete_pref_exact(uid, item)
        add_food_preference(uid, item, likes=False)
    return (
        f"✅ {len(selected)} item(s) movido(s) para Não Gostos.",
        gr.update(choices=_load_category_list(uid, "food_likes"), value=[]),
        gr.update(choices=_load_category_list(uid, "food_dislikes"), value=[]),
    )


# Food dislikes
def add_dislike_fn(uid: str, food: str):
    uid = uid.strip()
    if not uid or not food.strip():
        return "❌ Preenche o User ID e o alimento.", gr.update(), ""
    add_food_preference(uid, food.strip(), likes=False)
    return (
        f"✅ '{food.strip()}' adicionado aos não gostos.",
        gr.update(choices=_load_category_list(uid, "food_dislikes"), value=[]),
        "",
    )


def remove_dislikes_fn(uid: str, selected: list):
    uid = uid.strip()
    if not uid or not selected:
        return "❌ Seleciona pelo menos um item.", gr.update()
    for item in selected:
        _delete_pref_exact(uid, item)
    return (
        f"✅ {len(selected)} item(s) removido(s).",
        gr.update(choices=_load_category_list(uid, "food_dislikes"), value=[]),
    )


def move_to_likes_fn(uid: str, selected: list):
    uid = uid.strip()
    if not uid or not selected:
        return "❌ Seleciona itens para mover.", gr.update(), gr.update()
    for item in selected:
        _delete_pref_exact(uid, item)
        add_food_preference(uid, item, likes=True)
    return (
        f"✅ {len(selected)} item(s) movido(s) para Gostos.",
        gr.update(choices=_load_category_list(uid, "food_likes"), value=[]),
        gr.update(choices=_load_category_list(uid, "food_dislikes"), value=[]),
    )


# Generic category (allergies, restrictions, health_data)
def add_cat_item_fn(uid: str, text: str, category: str):
    uid = uid.strip()
    if not uid or not text.strip():
        return "❌ Preenche o User ID e o texto.", gr.update(), ""
    kb = get_knowledge_base()
    kb.add_preference(uid, category, text.strip(), {"created": datetime.now().isoformat()})
    return (
        "✅ Adicionado.",
        gr.update(choices=_load_category_list(uid, category), value=[]),
        "",
    )


def remove_cat_items_fn(uid: str, selected: list, category: str):
    uid = uid.strip()
    if not uid or not selected:
        return "❌ Seleciona pelo menos um item.", gr.update()
    for item in selected:
        _delete_pref_exact(uid, item)
    return (
        f"✅ {len(selected)} item(s) removido(s).",
        gr.update(choices=_load_category_list(uid, category), value=[]),
    )


# Goals
def add_goal_and_refresh(uid: str, goal: str):
    uid = uid.strip()
    if not uid or not goal.strip():
        return "❌ Preenche o User ID e o objetivo.", gr.update(), ""
    add_health_goal(uid, goal.strip())
    return (
        "✅ Objetivo adicionado.",
        gr.update(choices=_load_category_list(uid, "goals"), value=[]),
        "",
    )


def apply_seed_fn(user_id: str):
    uid = user_id.strip()
    _empty = tuple(gr.update() for _ in _PREF_CATS)
    if not uid:
        return ("❌ Introduz um User ID.", *_empty)
    try:
        from knowledge.seed_data import seed_user_preferences
        seed_user_preferences(uid, force=True)
        updates = load_all_prefs(uid)
        return (f"✅ Preferências padrão aplicadas a '{uid}'.", *updates)
    except Exception as e:
        return (f"❌ Erro: {e}", *_empty)


# ═══════════════════════════════════════════════════════
# TAB 4 — ADMINISTRAÇÃO (sub-tab: Sessões)
# ═══════════════════════════════════════════════════════

def load_sessions(user_id_filter: str = ""):
    conn = _db_conn(SQLITE_SESSIONS)
    if user_id_filter.strip():
        rows = conn.execute(
            """SELECT session_id, session_type, team_id, user_id,
                      created_at, updated_at, runs
               FROM agno_sessions WHERE user_id = ?
               ORDER BY updated_at DESC LIMIT 100""",
            (user_id_filter.strip(),),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT session_id, session_type, team_id, user_id,
                      created_at, updated_at, runs
               FROM agno_sessions ORDER BY updated_at DESC LIMIT 100"""
        ).fetchall()
    conn.close()

    data = []
    for r in rows:
        runs = r["runs"]
        if isinstance(runs, str):
            try:
                runs = json.loads(runs)
            except Exception:
                runs = []
        run_count = len(runs) if isinstance(runs, list) else 0
        ts_updated = r["updated_at"]
        if isinstance(ts_updated, int):
            ts_updated = datetime.fromtimestamp(ts_updated).strftime("%Y-%m-%d %H:%M")
        data.append([
            r["session_id"][:20] + "…" if len(r["session_id"]) > 20 else r["session_id"],
            r["user_id"] or "",
            r["session_type"] or "",
            run_count,
            ts_updated,
        ])
    return data


def view_session_messages(session_id_partial: str):
    if not session_id_partial.strip():
        return "Seleciona uma sessão."
    conn = _db_conn(SQLITE_SESSIONS)
    row = conn.execute(
        "SELECT * FROM agno_sessions WHERE session_id LIKE ?",
        (session_id_partial.strip().replace("…", "") + "%",),
    ).fetchone()
    conn.close()

    if not row:
        return "Sessão não encontrada."

    runs = row["runs"]
    if isinstance(runs, str):
        try:
            runs = json.loads(runs)
        except Exception:
            return "Não foi possível ler as mensagens."

    if not runs:
        return "Sem mensagens nesta sessão."

    lines = [f"**Sessão:** {row['session_id']}\n**User:** {row['user_id']}\n\n---\n"]
    for i, run in enumerate(runs if isinstance(runs, list) else [], 1):
        user_msg = ""
        agent_msg = ""
        if run.get("messages"):
            for msg in run["messages"]:
                if msg.get("role") == "user":
                    user_msg = msg.get("content", "")
                    break
        if run.get("response"):
            resp = run["response"]
            if isinstance(resp, dict):
                agent_msg = resp.get("content") or resp.get("text") or str(resp)
            else:
                agent_msg = str(resp)

        if user_msg or agent_msg:
            lines.append(f"**[{i}] Utilizador:** {user_msg}")
            lines.append(f"**Agente:** {agent_msg[:500]}{'…' if len(agent_msg) > 500 else ''}")
            lines.append("---")

    return "\n\n".join(lines)


def delete_session_fn(session_id_partial: str):
    if not session_id_partial.strip():
        return "❌ Introduz o ID da sessão."
    conn = _db_conn(SQLITE_SESSIONS)
    result = conn.execute(
        "DELETE FROM agno_sessions WHERE session_id LIKE ?",
        (session_id_partial.strip().replace("…", "") + "%",),
    )
    deleted = result.rowcount
    conn.commit()
    conn.close()
    if deleted:
        return f"✅ {deleted} sessão(ões) eliminada(s)."
    return "❌ Sessão não encontrada."


# ═══════════════════════════════════════════════════════
# TAB 4 — ADMINISTRAÇÃO (sub-tab: Logs)
# ═══════════════════════════════════════════════════════

LOG_FILE = BASE_DIR / "logs" / "health-assistant.log"


def load_logs(level_filter: str, search: str, n_lines: int):
    if not LOG_FILE.exists():
        return "Ficheiro de log não encontrado."
    with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    if level_filter and level_filter != "Todos":
        lines = [line for line in lines if level_filter in line]
    if search.strip():
        lines = [line for line in lines if search.lower() in line.lower()]

    result = list(reversed(lines))[:n_lines]
    return "".join(result) or "(sem resultados)"


def log_stats_fn():
    if not LOG_FILE.exists():
        return "Ficheiro não encontrado."
    with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    counts = {k: 0 for k in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")}
    for line in lines:
        for k in counts:
            if k in line:
                counts[k] += 1
                break
    size_kb = LOG_FILE.stat().st_size / 1024
    return (
        f"**Total de linhas:** {len(lines)}\n"
        f"**Tamanho:** {size_kb:.1f} KB\n\n"
        + "\n".join(f"- **{k}:** {v}" for k, v in counts.items())
    )


# ═══════════════════════════════════════════════════════
# TAB 4 — ADMINISTRAÇÃO (sub-tab: Base de Conhecimento)
# ═══════════════════════════════════════════════════════

def load_knowledge(collection: str, search: str):
    kb = get_knowledge_base()
    col = kb.nutrition if collection == "Nutrição" else kb.exercises
    try:
        if search.strip():
            results = col.query(query_texts=[search.strip()], n_results=20)
            if results and results.get("ids") and results["ids"][0]:
                return [
                    [results["ids"][0][i][:16] + "…", results["documents"][0][i][:120]]
                    for i in range(len(results["ids"][0]))
                ]
            return []
        else:
            data = col.get(limit=200)
            if not data or not data.get("ids"):
                return []
            return [
                [data["ids"][i][:16] + "…", data["documents"][i][:120]]
                for i in range(len(data["ids"]))
            ]
    except Exception as e:
        return [[str(e), ""]]


def add_knowledge_fn(collection: str, text: str):
    if not text.strip():
        return "❌ Introduz o texto."
    kb = get_knowledge_base()
    if collection == "Nutrição":
        doc_id = kb.add_nutrition_info(text.strip())
    else:
        doc_id = kb.add_exercise_info(text.strip())
    return f"✅ Adicionado com o ID: {doc_id}"


def delete_knowledge_fn(collection: str, doc_id_partial: str):
    if not doc_id_partial.strip():
        return "❌ Introduz o ID."
    kb = get_knowledge_base()
    col = kb.nutrition if collection == "Nutrição" else kb.exercises
    doc_id = doc_id_partial.strip().replace("…", "")
    try:
        data = col.get()
        matches = [i for i in (data.get("ids") or []) if i.startswith(doc_id)]
        if not matches:
            return f"❌ ID '{doc_id}' não encontrado."
        col.delete(ids=matches)
        return f"✅ {len(matches)} entrada(s) eliminada(s)."
    except Exception as e:
        return f"❌ Erro: {e}"


def kb_stats_fn():
    kb = get_knowledge_base()
    return (
        f"- **Nutrição:** {kb.nutrition.count()} documentos\n"
        f"- **Exercícios:** {kb.exercises.count()} documentos\n"
        f"- **Preferências:** {kb.preferences.count()} documentos"
    )


def create_user_fn(name: str, uid: str):
    uid = uid.strip()
    name = name.strip()
    if not uid:
        return "❌ O ID da Conta é obrigatório.", gr.update(), gr.update(), gr.update(), "", ""
    try:
        update_user_profile(uid, name=name or None)
        users = list_users()
        return (
            f"✅ '{name or uid}' criado com sucesso!",
            gr.update(choices=users, value=uid),
            uid,
            check_user_status(uid),
            "",
            "",
        )
    except Exception as e:
        return f"❌ Erro: {e}", gr.update(), gr.update(), gr.update(), "", ""


# ═══════════════════════════════════════════════════════
# DASHBOARD METRICS
# ═══════════════════════════════════════════════════════

def get_dashboard_html(user_id: str):
    uid = user_id.strip()
    if not uid:
        return "<div style='text-align:center; padding:20px;'>Introduce um ID de Conta para ver o teu painel.</div>"

    conn = _db_conn(SQLITE_DB)
    row = conn.execute(
        "SELECT * FROM user_profiles WHERE user_id = ?", (uid,)
    ).fetchone()
    conn.close()

    if not row or not row["weight_kg"] or not row["height_cm"]:
        return """
        <div style='background: rgba(16, 185, 129, 0.1); border: 1px dashed #10b981; border-radius: 12px; padding: 30px; text-align: center;'>
            <h3 style='margin-top:0; color: #059669;'>Bem-vindo ao teu Painel! 👋</h3>
            <p>Ainda não temos dados suficientes para calcular as tuas métricas de saúde.</p>
            <p style='font-size: 0.9em; color: #666;'>Preenche o teu perfil ou usa o formulário abaixo para começar.</p>
        </div>
        """

    # Calculate BMI
    weight, height = row["weight_kg"], row["height_cm"] / 100
    bmi = weight / (height * height)
    bmi_category = "Peso Normal"
    bmi_color = "#10b981"
    if bmi < 18.5:
        bmi_category = "Abaixo do peso"
        bmi_color = "#3b82f6"
    elif 25 <= bmi < 30:
        bmi_category = "Sobrepeso"
        bmi_color = "#f59e0b"
    elif bmi >= 30:
        bmi_category = "Obesidade"
        bmi_color = "#ef4444"

    # Get TDEE from nutrition tools logic
    try:
        from tools.profile_tools import _age_from_birth_date
        age = _age_from_birth_date(row["birth_date"]) or 30
        tdee_text = calculate_daily_calories(
            row["weight_kg"], row["height_cm"], age,
            row["gender"] or "male", row["activity_level"] or "moderate",
            row["goal"] or "maintain"
        )
        # Extract meta diária
        match = re.search(r"Meta diária: (\d+) kcal", tdee_text)
        daily_kcal = match.group(1) if match else "—"
    except Exception:
        daily_kcal = "—"

    html = f"""
    <div style='display: flex; gap: 15px; flex-wrap: wrap; justify-content: space-between;'>
        <div style='flex: 1; min-width: 200px; background: white; border: 1px solid #e5e7eb; border-radius: 12px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);'>
            <div style='color: #6b7280; font-size: 0.85rem; font-weight: 600; text-transform: uppercase;'>Peso Actual</div>
            <div style='font-size: 2rem; font-weight: 700; color: #111827; margin: 10px 0;'>{row['weight_kg']} <span style='font-size: 1rem; font-weight: 400; color: #6b7280;'>kg</span></div>
            <div style='font-size: 0.85rem; color: #059669; font-weight: 500;'>Altura: {row['height_cm']} cm</div>
        </div>
        <div style='flex: 1; min-width: 200px; background: white; border: 1px solid #e5e7eb; border-radius: 12px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);'>
            <div style='color: #6b7280; font-size: 0.85rem; font-weight: 600; text-transform: uppercase;'>IMC (BMI)</div>
            <div style='font-size: 2rem; font-weight: 700; color: #111827; margin: 10px 0;'>{bmi:.1f}</div>
            <div style='font-size: 0.85rem; color: {bmi_color}; font-weight: 600;'>{bmi_category}</div>
        </div>
        <div style='flex: 1; min-width: 200px; background: white; border: 1px solid #e5e7eb; border-radius: 12px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);'>
            <div style='color: #6b7280; font-size: 0.85rem; font-weight: 600; text-transform: uppercase;'>Meta Calórica</div>
            <div style='font-size: 2rem; font-weight: 700; color: #111827; margin: 10px 0;'>{daily_kcal} <span style='font-size: 1rem; font-weight: 400; color: #6b7280;'>kcal</span></div>
            <div style='font-size: 0.85rem; color: #6b7280;'>Baseado no teu objectivo</div>
        </div>
    </div>
    """
    return html


def check_onboarding_needed(user_id: str):
    uid = user_id.strip()
    if not uid:
        return gr.update(visible=False)
    conn = _db_conn(SQLITE_DB)
    row = conn.execute(
        "SELECT birth_date, gender, height_cm, weight_kg FROM user_profiles WHERE user_id = ?", (uid,)
    ).fetchone()
    conn.close()
    is_complete = bool(row and row["birth_date"] and row["gender"] and row["height_cm"] and row["weight_kg"])
    return gr.update(visible=not is_complete)


# ═══════════════════════════════════════════════════════
# UI
# ═══════════════════════════════════════════════════════

_CSS = """
/* Food preference lists — one item per line */
.vertical-list .wrap {
    flex-direction: column !important;
    gap: 2px !important;
}
.vertical-list .wrap label {
    width: 100% !important;
    padding: 5px 10px !important;
    border-radius: 6px !important;
    margin: 0 !important;
    transition: background 0.15s;
}
.vertical-list .wrap label:hover {
    background: rgba(255,255,255,0.06) !important;
}

/* Dashboard Cards */
.health-card {
    transition: transform 0.2s;
}
.health-card:hover {
    transform: translateY(-2px);
}

/* Compact weight registration row */
.weight-row {
    max-width: 420px !important;
    align-items: center !important;
}
"""

with gr.Blocks(title="Health Assistant") as demo:

    with gr.Sidebar():
        gr.Markdown("# 🌿 Health Assistant")

        _initial_users = list_users()
        _initial_uid = _initial_users[0][1] if _initial_users else ""

        user_status = gr.Markdown(check_user_status(_initial_uid))

        user_select = gr.Dropdown(
            label="👤 Utilizador",
            choices=_initial_users,
            value=_initial_uid if _initial_uid else None,
            interactive=True,
        )

        # Hidden — driven programmatically; used as input across all tabs
        global_uid = gr.State(value=_initial_uid)

        with gr.Accordion("➕ Novo Utilizador", open=False):
            new_user_name = gr.Textbox(label="Nome", placeholder="Ex: Bruno")
            new_user_id_input = gr.Textbox(label="ID da Conta", placeholder="Ex: 29255997")
            create_user_btn = gr.Button("Criar Conta", variant="primary")
            create_user_status = gr.Markdown()

        gr.Markdown("---")
        reset_btn = gr.Button("🗑️ Limpar Conversa", variant="secondary", size="sm")
        reset_status = gr.Markdown()

    with gr.Tabs() as tabs_container:

        # ── TAB: CHAT ────────────────────────────────────
        with gr.Tab("💬 Conversa"):
            chatbot = gr.Chatbot(
                show_label=False,
                height=600,
                avatar_images=(None, "https://em-content.zobj.net/source/google/350/seedling_1f331.png"),
                render_markdown=True,
            )
            with gr.Group():
                with gr.Row():
                    msg_input = gr.Textbox(
                        placeholder="Pergunta algo ao teu assistente de saúde…",
                        show_label=False,
                        scale=5,
                        lines=1,
                    )
                    send_btn = gr.Button("Enviar ↩", variant="primary", scale=1, interactive=False)

        # ── TAB: PERFIL ──────────────────────────────────
        with gr.Tab("👤 Perfil"):
            with gr.Row():
                load_profile_btn = gr.Button("📥 Carregar Perfil", variant="primary")
                save_profile_btn = gr.Button("💾 Guardar Alterações", variant="secondary")
                profile_status = gr.Markdown()

            with gr.Accordion("📝 Informação Pessoal", open=True):
                with gr.Row():
                    with gr.Column():
                        pf_name = gr.Textbox(label="Nome")
                        pf_birth_date = gr.Textbox(label="Data de Nascimento", placeholder="DD/MM/AAAA")
                        pf_age = gr.Textbox(label="Idade (calculada)", interactive=False, placeholder="—")
                        pf_gender = gr.Radio(
                            choices=[("Masculino", "male"), ("Feminino", "female"), ("Outro / Prefiro não dizer", "other")],
                            label="Género",
                        )
                    with gr.Column():
                        pf_height = gr.Number(label="Altura (cm)", precision=1)
                        pf_weight = gr.Number(label="Peso actual (kg)", precision=1)
                        pf_activity = gr.Dropdown(
                            choices=[
                                ("Sedentário", "sedentary"),
                                ("Ligeiro (1-2x/semana)", "light"),
                                ("Moderado (3-5x/semana)", "moderate"),
                                ("Activo (6-7x/semana)", "active"),
                                ("Muito Activo (2x/dia)", "very_active"),
                            ],
                            label="Nível de Atividade",
                        )
                pf_goal = gr.Textbox(label="Objetivo principal", lines=2)
            with gr.Accordion("📈 Evolução de Peso", open=False):
                with gr.Row(elem_classes="weight-row"):
                    new_weight = gr.Textbox(show_label=False, placeholder="Novo peso (kg)  ex: 74.8", scale=3, min_width=200)
                    add_weight_btn = gr.Button("Registar", variant="primary", scale=1, min_width=120)
                weight_status = gr.Markdown()
                weight_period = gr.Dropdown(
                    choices=["Últimas 10", "Último Mês", "Últimos 6 Meses", "Último Ano", "Últimos 5 Anos"],
                    value="Último Ano",
                    label="Período",
                    interactive=True,
                    elem_classes="period-selector",
                )
                weight_chart = gr.HTML()

            with gr.Accordion("📊 Composição Corporal", open=False):
                gr.Markdown(
                    "_Fonte: **MyTanita**_",
                )
                comp_period = gr.Dropdown(
                    choices=["Últimas 10", "Último Mês", "Últimos 6 Meses", "Último Ano", "Últimos 5 Anos"],
                    value="Último Ano",
                    label="Período",
                    interactive=True,
                )
                with gr.Row():
                    chart_bmi      = gr.HTML()
                    chart_fat      = gr.HTML()
                with gr.Row():
                    chart_visceral = gr.HTML()
                    chart_muscle   = gr.HTML()
                with gr.Row():
                    chart_water    = gr.HTML()
                    chart_bmr      = gr.HTML()
                with gr.Row():
                    chart_metage   = gr.HTML()
                    chart_bone     = gr.HTML()

            with gr.Accordion("🔒 Privacidade e Dados (RGPD)", open=False):
                gr.Markdown(
                    "Os teus dados são processados exclusivamente para fins de assistência "
                    "pessoal de saúde e bem-estar. Tens direito a exportar ou eliminar "
                    "todos os teus dados em qualquer momento (**RGPD Art. 20 e Art. 17**)."
                )
                with gr.Row():
                    gdpr_export_btn = gr.Button("📤 Exportar os Meus Dados", variant="secondary")
                    gdpr_delete_btn = gr.Button("🗑️ Eliminar Conta e Dados", variant="stop")
                gdpr_status = gr.Markdown()
                gdpr_export_out = gr.Code(label="Dados exportados (JSON)", language="json", visible=False)

        # ── TAB: PREFERÊNCIAS ────────────────────────────
        with gr.Tab("🥗 Nutrição e Gostos"):
            with gr.Row():
                load_prefs_btn = gr.Button("🔄 Carregar Preferências", variant="primary")
                apply_seed_btn = gr.Button("🌱 Aplicar Padrão", variant="secondary")
                prefs_status = gr.Markdown()

            with gr.Accordion("🥦 Alimentos — Gostos e Não Gostos", open=True):
                with gr.Row(equal_height=False):
                    # ── Lista GOSTO ──────────────────────────
                    with gr.Column(scale=5):
                        likes_check = gr.CheckboxGroup(
                            label="✅ Gosto",
                            choices=[],
                            interactive=True,
                            elem_classes=["vertical-list"],
                        )
                        with gr.Row():
                            new_like_input = gr.Textbox(
                                placeholder="Ex: salmão, frango, bróculos…",
                                show_label=False,
                                scale=5,
                            )
                            add_like_btn = gr.Button("➕", variant="primary", scale=1, min_width=56)
                        remove_likes_btn = gr.Button("🗑️ Remover selecionados", variant="stop", size="sm")

                    # ── Setas de transferência ───────────────
                    with gr.Column(scale=1, min_width=90):
                        gr.HTML("<div style='height:120px'></div>")
                        move_to_dislikes_btn = gr.Button("→", variant="secondary", size="lg")
                        gr.HTML("<div style='height:8px'></div>")
                        move_to_likes_btn = gr.Button("←", variant="secondary", size="lg")

                    # ── Lista NÃO GOSTO ──────────────────────
                    with gr.Column(scale=5):
                        dislikes_check = gr.CheckboxGroup(
                            label="❌ Não Gosto",
                            choices=[],
                            interactive=True,
                            elem_classes=["vertical-list"],
                        )
                        with gr.Row():
                            new_dislike_input = gr.Textbox(
                                placeholder="Ex: beterraba, fígado…",
                                show_label=False,
                                scale=5,
                            )
                            add_dislike_btn = gr.Button("➕", variant="stop", scale=1, min_width=56)
                        remove_dislikes_btn = gr.Button("🗑️ Remover selecionados", variant="stop", size="sm")

                food_status = gr.Markdown()

            with gr.Accordion("🚫 Alergias e Restrições", open=False):
                with gr.Row():
                    with gr.Column():
                        allergies_check = gr.CheckboxGroup(
                            label="🚫 Alergias",
                            choices=[],
                            interactive=True,
                            elem_classes=["vertical-list"],
                        )
                        with gr.Row():
                            new_allergy_input = gr.Textbox(
                                placeholder="Ex: lactose, amendoim…",
                                show_label=False,
                                scale=5,
                            )
                            add_allergy_btn = gr.Button("➕", variant="primary", scale=1, min_width=60)
                        remove_allergies_btn = gr.Button("🗑️ Remover selecionados", variant="stop")

                    with gr.Column():
                        restrictions_check = gr.CheckboxGroup(
                            label="⚠️ Restrições",
                            choices=[],
                            interactive=True,
                            elem_classes=["vertical-list"],
                        )
                        with gr.Row():
                            new_restriction_input = gr.Textbox(
                                placeholder="Ex: vegetariano, low-carb…",
                                show_label=False,
                                scale=5,
                            )
                            add_restriction_btn = gr.Button("➕", variant="primary", scale=1, min_width=60)
                        remove_restrictions_btn = gr.Button("🗑️ Remover selecionados", variant="stop")

                    with gr.Column():
                        health_check = gr.CheckboxGroup(
                            label="🏥 Dados de Saúde",
                            choices=[],
                            interactive=True,
                            elem_classes=["vertical-list"],
                        )
                        with gr.Row():
                            new_health_input = gr.Textbox(
                                placeholder="Ex: diabetes, hipertensão…",
                                show_label=False,
                                scale=5,
                            )
                            add_health_btn = gr.Button("➕", variant="primary", scale=1, min_width=60)
                        remove_health_btn = gr.Button("🗑️ Remover selecionados", variant="stop")

                restrictions_status = gr.Markdown()

            with gr.Accordion("🎯 Objetivos de Saúde", open=False):
                goals_check = gr.CheckboxGroup(
                    label="Objetivos",
                    choices=[],
                    interactive=True,
                    elem_classes=["vertical-list"],
                )
                with gr.Row():
                    new_goal_input = gr.Textbox(
                        placeholder="Ex: perder 5 kg, correr 5 km…",
                        show_label=False,
                        scale=5,
                    )
                    add_goal_btn = gr.Button("➕ Adicionar", variant="primary", scale=2)
                remove_goals_btn = gr.Button("🗑️ Remover selecionados", variant="stop")
                goals_status = gr.Markdown()

        # ── TAB: ADMINISTRAÇÃO ───────────────────────────
        with gr.Tab("⚙️ Administração"):
            with gr.Tabs():
                with gr.Tab("🔍 Explicabilidade"):
                    gr.Markdown("### 🧠 Explainable AI (XAI)")
                    with gr.Row():
                        xai_refresh_btn = gr.Button("🔄 Atualizar Análise XAI", variant="primary")
                        xai_clear_btn = gr.Button("🗑️ Limpar", variant="secondary")
                    xai_display = gr.Markdown("_Nenhuma análise disponível ainda._")

                with gr.Tab("📋 Sessões"):
                    with gr.Row():
                        sessions_uid_filter = gr.Textbox(label="Filtrar por User ID")
                        load_sessions_btn = gr.Button("Carregar", variant="primary")
                    sessions_table = gr.DataFrame(
                        headers=["Session ID", "User ID", "Tipo", "Mensagens", "Atualizado"],
                        datatype=["str", "str", "str", "number", "str"],
                        interactive=False,
                    )
                    with gr.Row():
                        session_id_input = gr.Textbox(label="Session ID")
                        view_session_btn = gr.Button("Ver Detalhes", variant="primary")
                        delete_session_btn = gr.Button("Eliminar", variant="stop")
                    session_detail = gr.Markdown()
                    sessions_status = gr.Markdown()

                with gr.Tab("📄 Logs"):
                    with gr.Row():
                        log_level = gr.Dropdown(
                            ["Todos", "INFO", "WARNING", "ERROR", "CRITICAL", "DEBUG"],
                            value="Todos",
                            label="Nível",
                        )
                        log_search = gr.Textbox(label="Pesquisar")
                        log_n = gr.Slider(50, 1000, value=200, step=50, label="Linhas")
                        load_logs_btn = gr.Button("Atualizar", variant="primary")
                    log_output = gr.Textbox(label="Logs", lines=20, interactive=False)
                    log_stats_btn = gr.Button("Estatísticas")
                    log_stats_out = gr.Markdown()

                with gr.Tab("🧠 Base de Conhecimento"):
                    with gr.Row():
                        kb_collection = gr.Radio(
                            ["Nutrição", "Exercícios"], value="Nutrição", label="Colecção"
                        )
                        kb_search = gr.Textbox(label="Pesquisa")
                        load_kb_btn = gr.Button("Carregar", variant="primary")
                    kb_table = gr.DataFrame(
                        headers=["ID", "Texto"], datatype=["str", "str"], interactive=False
                    )
                    with gr.Row():
                        new_kb_text = gr.Textbox(label="Novo Documento", lines=3)
                        add_kb_btn = gr.Button("Adicionar", variant="primary")
                    with gr.Row():
                        del_kb_id = gr.Textbox(label="ID a eliminar")
                        del_kb_btn = gr.Button("Eliminar", variant="stop")
                    kb_stats_btn = gr.Button("Estatísticas")
                    kb_stats_out = gr.Markdown()
                    kb_action_status = gr.Markdown()


    # Auto-refresh timer (picks up users/data created via Telegram)
    refresh_timer = gr.Timer(value=30)
    # Hidden state used as a no-op trigger for the tick → then chain
    _refresh_trigger = gr.State(value=0)

    # ── EVENT HANDLERS ───────────────────────────────────

    def _load_xai():
        from xai import get_tracker
        return get_tracker().generate_markdown()

    # Convenience list — same order as _PREF_CATS
    _PREF_CHECKS = [likes_check, dislikes_check, allergies_check, goals_check, restrictions_check, health_check]

    # 1. Chat
    send_btn.click(
        chat_fn,
        inputs=[msg_input, chatbot, global_uid],
        outputs=[chatbot, xai_display, msg_input],
    )

    msg_input.submit(
        chat_fn,
        inputs=[msg_input, chatbot, global_uid],
        outputs=[chatbot, xai_display, msg_input],
    )

    msg_input.change(
        fn=lambda text: gr.update(interactive=bool(text.strip())),
        inputs=[msg_input],
        outputs=[send_btn],
    )

    reset_btn.click(reset_chat, inputs=[global_uid], outputs=[chatbot, reset_status])

    # 2. Perfil
    load_profile_btn.click(
        load_profile,
        inputs=[global_uid],
        outputs=[pf_name, pf_birth_date, pf_age, pf_gender, pf_height, pf_weight, pf_activity, pf_goal],
    ).then(load_weight_chart, inputs=[global_uid, weight_period], outputs=[weight_chart])

    save_profile_btn.click(
        save_profile,
        inputs=[global_uid, pf_name, pf_birth_date, pf_gender, pf_height, pf_weight, pf_activity, pf_goal],
        outputs=[profile_status],
    )

    gdpr_export_btn.click(
        gdpr_export_fn,
        inputs=[global_uid],
        outputs=[gdpr_status, gdpr_export_out],
    )
    gdpr_delete_btn.click(
        gdpr_delete_fn,
        inputs=[global_uid],
        outputs=[gdpr_status, pf_name, pf_birth_date, pf_age, pf_gender, pf_height, pf_weight, pf_activity, pf_goal, weight_chart],
    )

    add_weight_btn.click(
        add_weight_entry,
        inputs=[global_uid, new_weight, weight_period],
        outputs=[weight_status, weight_chart, new_weight, pf_name, pf_birth_date, pf_age, pf_gender, pf_height, pf_weight, pf_activity, pf_goal],
    )

    weight_period.change(
        load_weight_chart,
        inputs=[global_uid, weight_period],
        outputs=[weight_chart],
    )

    _comp_outputs = [chart_bmi, chart_fat, chart_visceral, chart_muscle,
                     chart_water, chart_bmr, chart_metage, chart_bone]

    comp_period.change(
        load_all_comp_charts,
        inputs=[global_uid, comp_period],
        outputs=_comp_outputs,
    )

    # 3. Preferências — load
    load_prefs_btn.click(load_all_prefs, inputs=[global_uid], outputs=_PREF_CHECKS)

    apply_seed_btn.click(
        apply_seed_fn,
        inputs=[global_uid],
        outputs=[prefs_status, *_PREF_CHECKS],
    )

    # 3. Preferências — food likes
    add_like_btn.click(
        add_like_fn,
        inputs=[global_uid, new_like_input],
        outputs=[food_status, likes_check, new_like_input],
    )
    new_like_input.submit(
        add_like_fn,
        inputs=[global_uid, new_like_input],
        outputs=[food_status, likes_check, new_like_input],
    )
    remove_likes_btn.click(
        remove_likes_fn,
        inputs=[global_uid, likes_check],
        outputs=[food_status, likes_check],
    )
    move_to_dislikes_btn.click(
        move_to_dislikes_fn,
        inputs=[global_uid, likes_check],
        outputs=[food_status, likes_check, dislikes_check],
    )

    # 3. Preferências — food dislikes
    add_dislike_btn.click(
        add_dislike_fn,
        inputs=[global_uid, new_dislike_input],
        outputs=[food_status, dislikes_check, new_dislike_input],
    )
    new_dislike_input.submit(
        add_dislike_fn,
        inputs=[global_uid, new_dislike_input],
        outputs=[food_status, dislikes_check, new_dislike_input],
    )
    remove_dislikes_btn.click(
        remove_dislikes_fn,
        inputs=[global_uid, dislikes_check],
        outputs=[food_status, dislikes_check],
    )
    move_to_likes_btn.click(
        move_to_likes_fn,
        inputs=[global_uid, dislikes_check],
        outputs=[food_status, likes_check, dislikes_check],
    )

    # 3. Preferências — allergies
    add_allergy_btn.click(
        lambda uid, text: add_cat_item_fn(uid, text, "allergies"),
        inputs=[global_uid, new_allergy_input],
        outputs=[restrictions_status, allergies_check, new_allergy_input],
    )
    new_allergy_input.submit(
        lambda uid, text: add_cat_item_fn(uid, text, "allergies"),
        inputs=[global_uid, new_allergy_input],
        outputs=[restrictions_status, allergies_check, new_allergy_input],
    )
    remove_allergies_btn.click(
        lambda uid, sel: remove_cat_items_fn(uid, sel, "allergies"),
        inputs=[global_uid, allergies_check],
        outputs=[restrictions_status, allergies_check],
    )

    # 3. Preferências — restrictions
    add_restriction_btn.click(
        lambda uid, text: add_cat_item_fn(uid, text, "restrictions"),
        inputs=[global_uid, new_restriction_input],
        outputs=[restrictions_status, restrictions_check, new_restriction_input],
    )
    new_restriction_input.submit(
        lambda uid, text: add_cat_item_fn(uid, text, "restrictions"),
        inputs=[global_uid, new_restriction_input],
        outputs=[restrictions_status, restrictions_check, new_restriction_input],
    )
    remove_restrictions_btn.click(
        lambda uid, sel: remove_cat_items_fn(uid, sel, "restrictions"),
        inputs=[global_uid, restrictions_check],
        outputs=[restrictions_status, restrictions_check],
    )

    # 3. Preferências — health data
    add_health_btn.click(
        lambda uid, text: add_cat_item_fn(uid, text, "health_data"),
        inputs=[global_uid, new_health_input],
        outputs=[restrictions_status, health_check, new_health_input],
    )
    new_health_input.submit(
        lambda uid, text: add_cat_item_fn(uid, text, "health_data"),
        inputs=[global_uid, new_health_input],
        outputs=[restrictions_status, health_check, new_health_input],
    )
    remove_health_btn.click(
        lambda uid, sel: remove_cat_items_fn(uid, sel, "health_data"),
        inputs=[global_uid, health_check],
        outputs=[restrictions_status, health_check],
    )

    # 3. Preferências — goals
    add_goal_btn.click(
        add_goal_and_refresh,
        inputs=[global_uid, new_goal_input],
        outputs=[goals_status, goals_check, new_goal_input],
    )
    new_goal_input.submit(
        add_goal_and_refresh,
        inputs=[global_uid, new_goal_input],
        outputs=[goals_status, goals_check, new_goal_input],
    )
    remove_goals_btn.click(
        lambda uid, sel: remove_cat_items_fn(uid, sel, "goals"),
        inputs=[global_uid, goals_check],
        outputs=[goals_status, goals_check],
    )

    # 4. Admin
    xai_refresh_btn.click(_load_xai, outputs=[xai_display])
    xai_clear_btn.click(lambda: "_Análise limpa._", outputs=[xai_display])

    load_sessions_btn.click(load_sessions, inputs=[sessions_uid_filter], outputs=[sessions_table])
    view_session_btn.click(view_session_messages, inputs=[session_id_input], outputs=[session_detail])
    delete_session_btn.click(
        delete_session_fn, inputs=[session_id_input], outputs=[sessions_status]
    ).then(load_sessions, inputs=[sessions_uid_filter], outputs=[sessions_table])

    load_logs_btn.click(load_logs, inputs=[log_level, log_search, log_n], outputs=[log_output])
    log_stats_btn.click(log_stats_fn, outputs=[log_stats_out])

    load_kb_btn.click(load_knowledge, inputs=[kb_collection, kb_search], outputs=[kb_table])
    add_kb_btn.click(
        add_knowledge_fn, inputs=[kb_collection, new_kb_text], outputs=[kb_action_status]
    ).then(load_knowledge, inputs=[kb_collection, kb_search], outputs=[kb_table])
    del_kb_btn.click(
        delete_knowledge_fn, inputs=[kb_collection, del_kb_id], outputs=[kb_action_status]
    ).then(load_knowledge, inputs=[kb_collection, kb_search], outputs=[kb_table])
    kb_stats_btn.click(kb_stats_fn, outputs=[kb_stats_out])

    # 5. Sidebar — user select auto-loads everything
    user_select.change(
        fn=lambda uid: uid or "",
        inputs=[user_select],
        outputs=[global_uid],
    ).then(
        # Read user_select directly here — global_uid may still be propagating
        # when this fires concurrently with the timer chain auto-selection.
        check_user_status, inputs=[user_select], outputs=[user_status],
    ).then(
        load_profile,
        inputs=[user_select],
        outputs=[pf_name, pf_birth_date, pf_age, pf_gender, pf_height, pf_weight, pf_activity, pf_goal],
    ).then(
        load_weight_chart, inputs=[user_select, weight_period], outputs=[weight_chart],
    ).then(
        load_all_comp_charts, inputs=[user_select, comp_period], outputs=_comp_outputs,
    ).then(
        load_all_prefs, inputs=[user_select], outputs=_PREF_CHECKS,
    )

    create_user_btn.click(
        create_user_fn,
        inputs=[new_user_name, new_user_id_input],
        outputs=[create_user_status, user_select, global_uid, user_status, new_user_name, new_user_id_input],
    ).then(
        load_profile,
        inputs=[global_uid],
        outputs=[pf_name, pf_birth_date, pf_age, pf_gender, pf_height, pf_weight, pf_activity, pf_goal],
    ).then(
        load_all_prefs, inputs=[global_uid], outputs=_PREF_CHECKS,
    )

    # Periodic refresh — syncs the user list.
    # gr.Timer.tick() does not support gr.State inputs, so tick() only bumps a
    # hidden counter to trigger the chain; all dropdown updates happen in the
    # subsequent .then() which CAN read gr.State.
    def _bump_trigger(n):
        return n + 1

    def _sync_user_dropdown(current_uid):
        """Refresh choices and auto-select the first user when none is selected.

        Always updates choices and value together so Gradio never validates a
        stale value against new choices (avoids UserWarning).
        Returns no-op updates if the DB is temporarily unavailable (e.g. during
        a long Tanita sync write) so the current user is never lost.
        """
        users = list_users()
        if not users and current_uid:
            # DB temporarily unavailable or empty; preserve current state entirely.
            return gr.update(), current_uid
        if current_uid:
            return gr.update(choices=users), current_uid
        if users:
            first_uid = users[0][1]
            return gr.update(choices=users, value=first_uid), first_uid
        return gr.update(choices=users, value=None), ""

    # On every page load (including new tabs opened after app startup):
    # sync the dropdown so users created via Telegram are immediately visible.
    demo.load(
        _sync_user_dropdown,
        inputs=[global_uid],
        outputs=[user_select, global_uid],
    ).then(
        load_profile,
        inputs=[global_uid],
        outputs=[pf_name, pf_birth_date, pf_age, pf_gender, pf_height, pf_weight, pf_activity, pf_goal],
    ).then(
        load_weight_chart, inputs=[global_uid, weight_period], outputs=[weight_chart],
    ).then(
        load_all_comp_charts, inputs=[global_uid, comp_period], outputs=_comp_outputs,
    ).then(
        load_all_prefs, inputs=[global_uid], outputs=_PREF_CHECKS,
    )

    refresh_timer.tick(
        fn=_bump_trigger,
        inputs=[_refresh_trigger],
        outputs=[_refresh_trigger],
    ).then(
        _sync_user_dropdown,
        inputs=[global_uid],
        outputs=[user_select, global_uid],
    ).then(
        check_user_status, inputs=[global_uid], outputs=[user_status],
    ).then(
        load_profile,
        inputs=[global_uid],
        outputs=[pf_name, pf_birth_date, pf_age, pf_gender, pf_height, pf_weight, pf_activity, pf_goal],
    ).then(
        load_weight_chart, inputs=[global_uid, weight_period], outputs=[weight_chart],
    ).then(
        load_all_comp_charts, inputs=[global_uid, comp_period], outputs=_comp_outputs,
    )

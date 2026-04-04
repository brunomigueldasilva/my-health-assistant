"""
Tab: 👤 Perfil

Business logic and UI builder for the profile tab.
Covers: personal info, weight tracking, body composition charts, GDPR controls.
"""

import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import gradio as gr

# Path setup
_root = Path(__file__).resolve().parent.parent.parent.parent
_iface = Path(__file__).resolve().parent.parent
for _p in (_root, _iface):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from config import SQLITE_DB
from shared import _db_conn
from tools.profile_tools import update_user_profile


# ── Profile ─────────────────────────────────────────────

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


# ── Weight chart ─────────────────────────────────────────

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


# ── Body composition charts ──────────────────────────────

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
    period = period or "Último Ano"
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


# ── GDPR + weight entry ──────────────────────────────────

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
    empty_charts = (None,) * 9  # weight_chart + 8 body composition charts
    if not uid:
        return ("❌ Introduz um User ID.", *empty_profile, *empty_charts)
    try:
        from tools.profile_tools import delete_all_user_data
        msg = delete_all_user_data(uid)
        return (msg, *empty_profile, *empty_charts)
    except Exception as e:
        return (f"❌ Erro: {e}", *empty_profile, *empty_charts)


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


# ── UI builder ───────────────────────────────────────────

def build_profile_tab() -> SimpleNamespace:
    """Create the profile tab UI. Must be called inside a gr.Blocks() context."""
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
        pf_goal = gr.State(value="")

    with gr.Accordion("🎯 Objetivos de Saúde", open=True):
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
        gr.Markdown("_Fonte: **MyTanita**_")
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

    return SimpleNamespace(
        load_profile_btn=load_profile_btn,
        save_profile_btn=save_profile_btn,
        profile_status=profile_status,
        pf_name=pf_name,
        pf_birth_date=pf_birth_date,
        pf_age=pf_age,
        pf_gender=pf_gender,
        pf_height=pf_height,
        pf_weight=pf_weight,
        pf_activity=pf_activity,
        pf_goal=pf_goal,
        goals_check=goals_check,
        new_goal_input=new_goal_input,
        add_goal_btn=add_goal_btn,
        remove_goals_btn=remove_goals_btn,
        goals_status=goals_status,
        new_weight=new_weight,
        add_weight_btn=add_weight_btn,
        weight_status=weight_status,
        weight_period=weight_period,
        weight_chart=weight_chart,
        comp_period=comp_period,
        chart_bmi=chart_bmi,
        chart_fat=chart_fat,
        chart_visceral=chart_visceral,
        chart_muscle=chart_muscle,
        chart_water=chart_water,
        chart_bmr=chart_bmr,
        chart_metage=chart_metage,
        chart_bone=chart_bone,
        gdpr_export_btn=gdpr_export_btn,
        gdpr_delete_btn=gdpr_delete_btn,
        gdpr_status=gdpr_status,
        gdpr_export_out=gdpr_export_out,
    )

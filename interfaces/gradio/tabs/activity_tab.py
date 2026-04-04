"""
Tab: 🏃 Actividade

Business logic and UI builder for the Garmin activity/training dashboard.
Covers: daily KPIs, calories, steps, sleep quality, body battery, resting HR,
training streak, and recent activities table.
"""

import json
import html as _html
import sys
import logging
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import gradio as gr

# Path setup
_root = Path(__file__).resolve().parent.parent.parent.parent
_iface = Path(__file__).resolve().parent.parent
for _p in (_root, _iface):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from tools.garmin_tools import (
    get_garmin_stats_range,
    get_garmin_sleep_range,
    get_garmin_activities_raw,
    sync_tanita_to_garmin,
)
from tools.tanita_tools import sync_tanita_measurements

logger = logging.getLogger(__name__)

_PERIOD_OPTIONS = ["7 dias", "14 dias", "30 dias", "3 meses", "6 meses", "1 ano", "5 anos"]
_PERIOD_MAP = {
    "7 dias":   7,
    "14 dias":  14,
    "30 dias":  30,
    "3 meses":  90,
    "6 meses":  180,
    "1 ano":    365,
    "5 anos":   1825,
}
# Activities to fetch per period (Garmin API paginated)
_ACTIVITIES_LIMIT = {
    "7 dias":   30,
    "14 dias":  50,
    "30 dias":  100,
    "3 meses":  200,
    "6 meses":  300,
    "1 ano":    500,
    "5 anos":   1000,
}

_EMPTY_HTML = (
    "<div style='color:#475569;padding:28px;text-align:center;"
    "background:#0f172a;border-radius:12px;font:12px Inter,sans-serif'>"
    "Sem dados Garmin. Verifica a ligação e os tokens.</div>"
)

# ── Activity type labels ──────────────────────────────────────────────────────

_TYPE_LABELS = {
    "running":          "Corrida",
    "cycling":          "Ciclismo",
    "swimming":         "Natação",
    "walking":          "Caminhada",
    "strength_training":"Musculação",
    "yoga":             "Yoga",
    "hiking":           "Trilho",
    "elliptical":       "Elíptica",
    "rowing":           "Remo",
    "indoor_cycling":   "Bicicleta Indoor",
    "cardio":           "Cardio",
    "fitness_equipment":"Equipamento",
    "unknown":          "Outro",
}

def _type_label(key: str) -> str:
    return _TYPE_LABELS.get(key, key.replace("_", " ").title())


# ── Streak calculator ─────────────────────────────────────────────────────────

def _calc_streak(activity_dates: set) -> int:
    """Count consecutive days ending today (or yesterday) with at least one activity."""
    today = date.today()
    streak = 0
    # Start from today; if today has no activity yet, start from yesterday
    start = today if today.isoformat() in activity_dates else today - timedelta(days=1)
    current = start
    while current.isoformat() in activity_dates:
        streak += 1
        current -= timedelta(days=1)
    return streak


# ── Chart HTML builders ───────────────────────────────────────────────────────

def _build_line_chart(dates, values, label, unit, color, height=230):
    if not dates or not any(v is not None for v in values):
        return _EMPTY_HTML

    dates_json  = json.dumps(dates)
    values_json = json.dumps(values)
    unit_js     = json.dumps(unit)
    n_days      = len([d for d in dates if len(d) == 10])
    tick_limit  = 5 if n_days > 10 else n_days

    inner = f"""<!DOCTYPE html><html>
<head><meta charset="utf-8"><style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#0f172a;overflow:hidden}}
  .w{{background:#0f172a;padding:10px 14px 6px;height:100vh;display:flex;flex-direction:column;gap:6px}}
  .h{{display:flex;justify-content:space-between;align-items:center}}
  .t{{color:#cbd5e1;font:600 11px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase}}
  canvas{{flex:1;min-height:0}}
</style></head>
<body><div class="w">
  <div class="h"><span class="t">{label}</span></div>
  <canvas id="c"></canvas>
</div>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/hammerjs@2.0.8/hammer.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.0.1/dist/chartjs-plugin-zoom.min.js"></script>
<script>
const labels={dates_json},vals={values_json},unit={unit_js},col='{color}';
const cv=document.getElementById('c');
const chart=new Chart(cv,{{type:'line',
  data:{{labels,datasets:[{{
    label:'{label}',data:vals,borderColor:col,borderWidth:2,tension:0.25,fill:true,
    backgroundColor(ctx){{const ca=ctx.chart.chartArea||{{}};const g=ctx.chart.ctx.createLinearGradient(0,ca.top||0,0,ca.bottom||200);g.addColorStop(0,col+'44');g.addColorStop(1,col+'06');return g;}},
    pointBackgroundColor:'white',pointBorderColor:col,pointBorderWidth:1.5,pointRadius:3,pointHoverRadius:6,spanGaps:true
  }}]}},
  options:{{responsive:true,maintainAspectRatio:false,interaction:{{mode:'index',intersect:false}},animation:{{duration:300}},
    plugins:{{
      legend:{{display:false}},
      tooltip:{{backgroundColor:'#1e293b',borderColor:'#334155',borderWidth:1,titleColor:'#94a3b8',bodyColor:'#f9fafb',bodyFont:{{size:12,weight:'600'}},padding:8,
        callbacks:{{label:i=>i.raw!=null?` ${{i.raw.toFixed(0)}}${{unit?' '+unit:''}}`:null}}}},
      zoom:{{zoom:{{wheel:{{enabled:true}},pinch:{{enabled:true}},mode:'x'}},pan:{{enabled:true,mode:'x'}}}}}},
    scales:{{
      x:{{ticks:{{color:'#475569',maxTicksLimit:{tick_limit},maxRotation:0,font:{{size:10}}}},grid:{{color:'rgba(255,255,255,0.04)'}},border:{{color:'rgba(255,255,255,0.06)'}}}},
      y:{{ticks:{{color:'#475569',font:{{size:10}},callback:v=>v.toFixed(0)+(unit?' '+unit:'')}},grid:{{color:'rgba(255,255,255,0.04)'}},border:{{color:'rgba(255,255,255,0.06)'}}}}}}}}}});
cv.addEventListener('dblclick',()=>chart.resetZoom());
</script></body></html>"""

    esc = _html.escape(inner, quote=True)
    return f'<iframe srcdoc="{esc}" style="width:100%;height:{height}px;border:none;border-radius:12px;display:block;"></iframe>'


def _build_bar_chart(dates, values, label, unit, color, height=230):
    if not dates or not any((v or 0) > 0 for v in values):
        return _EMPTY_HTML

    dates_json  = json.dumps(dates)
    values_json = json.dumps(values)
    unit_js     = json.dumps(unit)
    n_days      = len(dates)
    tick_limit  = 5 if n_days > 10 else n_days

    inner = f"""<!DOCTYPE html><html>
<head><meta charset="utf-8"><style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#0f172a;overflow:hidden}}
  .w{{background:#0f172a;padding:10px 14px 6px;height:100vh;display:flex;flex-direction:column;gap:6px}}
  .h{{display:flex;justify-content:space-between;align-items:center}}
  .t{{color:#cbd5e1;font:600 11px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase}}
  canvas{{flex:1;min-height:0}}
</style></head>
<body><div class="w">
  <div class="h"><span class="t">{label}</span></div>
  <canvas id="c"></canvas>
</div>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/hammerjs@2.0.8/hammer.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.0.1/dist/chartjs-plugin-zoom.min.js"></script>
<script>
const labels={dates_json},vals={values_json},unit={unit_js},col='{color}';
const cv=document.getElementById('c');
new Chart(cv,{{type:'bar',
  data:{{labels,datasets:[{{
    label:'{label}',data:vals,
    backgroundColor:col+'99',borderColor:col,borderWidth:1,borderRadius:4,
  }}]}},
  options:{{responsive:true,maintainAspectRatio:false,interaction:{{mode:'index',intersect:false}},animation:{{duration:300}},
    plugins:{{
      legend:{{display:false}},
      tooltip:{{backgroundColor:'#1e293b',borderColor:'#334155',borderWidth:1,titleColor:'#94a3b8',bodyColor:'#f9fafb',bodyFont:{{size:12,weight:'600'}},padding:8,
        callbacks:{{label:i=>i.raw!=null?` ${{i.raw.toFixed(0)}}${{unit?' '+unit:''}}`:null}}}},
      zoom:{{zoom:{{wheel:{{enabled:true}},pinch:{{enabled:true}},mode:'x'}},pan:{{enabled:true,mode:'x'}}}}}},
    scales:{{
      x:{{ticks:{{color:'#475569',maxTicksLimit:{tick_limit},maxRotation:0,font:{{size:10}}}},grid:{{color:'rgba(255,255,255,0.04)'}},border:{{color:'rgba(255,255,255,0.06)'}}}},
      y:{{ticks:{{color:'#475569',font:{{size:10}},callback:v=>v.toFixed(0)+(unit?' '+unit:'')}},grid:{{color:'rgba(255,255,255,0.04)'}},border:{{color:'rgba(255,255,255,0.06)'}}}}}}}}}});
cv.addEventListener('dblclick',()=>chart.resetZoom());
</script></body></html>"""

    esc = _html.escape(inner, quote=True)
    return f'<iframe srcdoc="{esc}" style="width:100%;height:{height}px;border:none;border-radius:12px;display:block;"></iframe>'


# ── KPI HTML builder ──────────────────────────────────────────────────────────

def _build_kpi_html(steps, calories, body_battery, sleep_h, sleep_m, streak,
                    sleep_score, resting_hr) -> str:

    def _kpi(label, value, unit, icon, color):
        val_html = (
            f"<div class='kv'>{value}<span class='ku'>{unit}</span></div>"
            if value is not None
            else "<div class='kv'>—</div>"
        )
        return (
            f"<div class='kpi'>"
            f"<div class='ki' style='color:{color}'>{icon}</div>"
            f"<div class='kl'>{label}</div>"
            f"{val_html}"
            f"</div>"
        )

    # Build streak badge
    if streak > 0:
        streak_color = "#10b981" if streak >= 7 else ("#f59e0b" if streak >= 3 else "#94a3b8")
        streak_val   = f"{streak}"
        streak_unit  = "dias"
    else:
        streak_color = "#475569"
        streak_val   = "0"
        streak_unit  = "dias"

    sleep_val  = f"{sleep_h}h {sleep_m:02d}" if sleep_h is not None else None
    sleep_unit = "min"
    bb_color   = "#10b981" if (body_battery or 0) >= 50 else ("#f59e0b" if (body_battery or 0) >= 25 else "#ef4444")
    hr_color   = "#60a5fa" if (resting_hr or 999) < 60 else ("#94a3b8" if (resting_hr or 0) < 80 else "#f87171")

    inner = f"""<!DOCTYPE html><html>
<head><meta charset="utf-8"><style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#0f172a;font-family:Inter,sans-serif;padding:10px 14px;overflow:hidden}}
  .row{{display:flex;gap:10px;flex-wrap:wrap}}
  .kpi{{flex:1;min-width:100px;background:#1e293b;border-radius:10px;padding:12px 14px;
        border:1px solid rgba(255,255,255,0.06)}}
  .ki{{font-size:20px;margin-bottom:4px}}
  .kl{{color:#64748b;font-size:9px;font-weight:600;letter-spacing:.07em;text-transform:uppercase;margin-bottom:4px}}
  .kv{{color:#f1f5f9;font-size:20px;font-weight:700;line-height:1.1}}
  .ku{{font-size:11px;font-weight:500;color:#94a3b8;margin-left:2px}}
</style></head>
<body><div class="row">
  {_kpi("Passos Hoje",      steps,         "",       "👣", "#60a5fa")}
  {_kpi("Calorias Hoje",    calories,      "kcal",   "🔥", "#f97316")}
  {_kpi("Body Battery",     body_battery,  "%",      "⚡", bb_color)}
  {_kpi("Sono",             sleep_val,     "",       "😴", "#a78bfa")}
  {_kpi("Score Sono",       sleep_score,   "/100",   "🌙", "#818cf8")}
  {_kpi("FC Repouso",       resting_hr,    "bpm",    "❤️", hr_color)}
  {_kpi("Streak Treinos",   streak_val,    streak_unit, "🏅", streak_color)}
</div></body></html>"""

    esc = _html.escape(inner, quote=True)
    return f'<iframe srcdoc="{esc}" style="width:100%;height:100px;border:none;border-radius:12px;display:block;"></iframe>'


# ── Recent activities table HTML ──────────────────────────────────────────────

def _build_activities_table(activities: list, max_rows: int = 50) -> str:
    if not activities:
        return _EMPTY_HTML

    rows = ""
    for i, act in enumerate(activities[:max_rows]):
        bg    = "#1e293b" if i % 2 == 0 else "#0f172a"
        dist  = f"{act['distance_km']:.2f} km" if act.get("distance_km", 0) > 0 else "—"
        dur   = (
            f"{act['duration_min'] // 60}h {act['duration_min'] % 60:02d}min"
            if act.get("duration_min", 0) >= 60
            else f"{act.get('duration_min', 0)} min"
        )
        cal   = f"{act['calories']} kcal" if act.get("calories") else "—"
        avg_hr = f"{act['avg_hr']} bpm"   if act.get("avg_hr")    else "—"
        max_hr = f"{act['max_hr']} bpm"   if act.get("max_hr")    else "—"
        sweat  = act.get("sweat_loss_ml")
        sweat_str = f"{sweat} mL" if sweat is not None else "—"

        rows += (
            f"<tr style='background:{bg}'>"
            f"<td>{act.get('date','')}</td>"
            f"<td>{_type_label(act.get('type','unknown'))}</td>"
            f"<td>{dur}</td>"
            f"<td>{dist}</td>"
            f"<td>{cal}</td>"
            f"<td>{avg_hr}</td>"
            f"<td>{max_hr}</td>"
            f"<td>{sweat_str}</td>"
            f"</tr>"
        )

    inner = f"""<!DOCTYPE html><html>
<head><meta charset="utf-8"><style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#0f172a;font-family:Inter,sans-serif;padding:10px 14px;overflow:auto}}
  .title{{color:#cbd5e1;font:600 11px/1 Inter,sans-serif;letter-spacing:.06em;
          text-transform:uppercase;margin-bottom:8px}}
  table{{width:100%;border-collapse:collapse;font-size:11px}}
  th{{background:#1e293b;color:#64748b;font:600 9px/1 Inter,sans-serif;letter-spacing:.07em;
      text-transform:uppercase;padding:7px 10px;text-align:left;border-bottom:1px solid rgba(255,255,255,0.06)}}
  td{{color:#cbd5e1;padding:7px 10px;border-bottom:1px solid rgba(255,255,255,0.04)}}
  td:nth-child(6),td:nth-child(7){{color:#f87171}}
  td:nth-child(8){{color:#60a5fa}}
</style></head>
<body>
  <div class="title">Actividades Recentes</div>
  <table>
    <thead><tr>
      <th>Data</th><th>Tipo</th><th>Duração</th><th>Distância</th>
      <th>Calorias</th><th>FC Média</th><th>FC Máx.</th><th>Suor Est.</th>
    </tr></thead>
    <tbody>{rows}</tbody>
  </table>
</body></html>"""

    n_rows = min(len(activities), max_rows)
    height = min(50 + 26 * n_rows + 40, 600)
    esc = _html.escape(inner, quote=True)
    return f'<iframe srcdoc="{esc}" style="width:100%;height:{height}px;border:none;border-radius:12px;display:block;"></iframe>'


# ── Tanita → Garmin sync ──────────────────────────────────────────────────────

_SYNC_LIMIT_OPTIONS = ["Última medição", "Últimas 7", "Últimas 30", "Todas (máx. 30)"]
_SYNC_LIMIT_MAP     = {
    "Última medição":   1,
    "Últimas 7":        7,
    "Últimas 30":       30,
    "Todas (máx. 30)":  30,
}


def run_tanita_garmin_sync(user_id: str, sync_limit: str) -> str:
    """Wrapper for the Gradio button — calls sync_tanita_to_garmin and returns status."""
    uid = (user_id or "").strip()
    if not uid:
        return "⚠️ Selecciona um utilizador primeiro."
    limit = _SYNC_LIMIT_MAP.get(sync_limit, 1)
    try:
        return sync_tanita_to_garmin(user_id=uid, limit=limit)
    except Exception as e:
        logger.error("run_tanita_garmin_sync error: %s", e)
        return f"❌ Erro durante a sincronização: {e}"


def run_tanita_portal_sync(user_id: str) -> str:
    """Import last year's Tanita measurements from mytanita.eu into the local database."""
    uid = (user_id or "").strip()
    if not uid:
        return "⚠️ Selecciona um utilizador primeiro."
    try:
        return sync_tanita_measurements(user_id=uid, days=365)
    except Exception as e:
        logger.error("run_tanita_portal_sync error: %s", e)
        return f"❌ Erro durante a importação: {e}"


# ── Main dashboard loader ─────────────────────────────────────────────────────

def load_activity_dashboard(period: str = "14 dias", user_id: str = "") -> tuple:
    """
    Fetch Garmin data and return chart/KPI HTMLs.

    Returns:
        (kpis_html, chart_calories, chart_steps, chart_sleep_score,
         chart_sleep_duration, chart_battery, chart_hr, activities_table,
         status_md)
    """
    uid = (user_id or "").strip()
    if not uid:
        empties = tuple([_EMPTY_HTML] * 8)
        return (*empties, "⚠️ Nenhum utilizador seleccionado.")

    days = _PERIOD_MAP.get(period, 14)

    act_limit = _ACTIVITIES_LIMIT.get(period, 100)

    try:
        stats_data  = get_garmin_stats_range(uid, days)
        sleep_data  = get_garmin_sleep_range(uid, days)
        activities  = get_garmin_activities_raw(uid, act_limit)
    except Exception as e:
        logger.error("load_activity_dashboard error: %s", e)
        err = _EMPTY_HTML
        return (err, err, err, err, err, err, err, err,
                f"❌ Erro ao carregar dados Garmin: {e}")

    if not stats_data:
        empties = tuple([_EMPTY_HTML] * 8)
        return (*empties, "⚠️ Sem dados Garmin. Verifica os tokens de autenticação.")

    # ── Today's KPIs ──────────────────────────────────────────────────────
    today_stats = stats_data[-1] if stats_data else {}
    today_sleep = sleep_data[-1] if sleep_data else {}

    steps        = today_stats.get("steps") or 0
    calories     = today_stats.get("calories") or 0
    body_battery = today_stats.get("body_battery")
    resting_hr   = today_stats.get("resting_hr")
    sleep_mins   = today_sleep.get("total_minutes") or 0
    sleep_h      = sleep_mins // 60 if sleep_mins else None
    sleep_m      = sleep_mins % 60  if sleep_mins else 0
    sleep_score  = today_sleep.get("score")

    # ── Training streak ───────────────────────────────────────────────────
    activity_dates = {a["date"] for a in activities if a.get("date")}
    streak = _calc_streak(activity_dates)

    kpis_html = _build_kpi_html(
        steps or None, calories or None, body_battery,
        sleep_h, sleep_m, streak, sleep_score, resting_hr,
    )

    # ── Prepare time-series data ──────────────────────────────────────────
    dates = [r["date"] for r in stats_data]
    # Show abbreviated dates (MM-DD) for readability
    short_dates = [d[5:] for d in dates]  # "YYYY-MM-DD" → "MM-DD"

    calories_vals = [r.get("calories") or 0 for r in stats_data]
    steps_vals    = [r.get("steps") or 0    for r in stats_data]
    battery_vals  = [r.get("body_battery")  for r in stats_data]
    hr_vals       = [r.get("resting_hr")    for r in stats_data]

    sleep_dates  = [r["date"][5:] for r in sleep_data]
    score_vals   = [r.get("score")          for r in sleep_data]
    sleep_h_vals = [
        round((r.get("total_minutes") or 0) / 60, 1)
        for r in sleep_data
    ]

    # ── Build charts ───────────────────────────────────────────────────────
    chart_calories = _build_bar_chart(
        short_dates, calories_vals, "Calorias Totais", "kcal", "#f97316",
    )
    chart_steps = _build_bar_chart(
        short_dates, steps_vals, "Passos Diários", "", "#60a5fa",
    )
    chart_sleep_score = _build_line_chart(
        sleep_dates, score_vals, "Score de Sono", "/100", "#a78bfa",
    )
    chart_sleep_duration = _build_line_chart(
        sleep_dates, sleep_h_vals, "Duração do Sono", "h", "#818cf8",
    )
    chart_battery = _build_line_chart(
        short_dates, battery_vals, "Body Battery", "%", "#34d399",
    )
    chart_hr = _build_line_chart(
        short_dates, hr_vals, "FC em Repouso", "bpm", "#f87171",
    )

    activities_table = _build_activities_table(activities, max_rows=act_limit)

    updated_at = date.today().strftime("%d/%m/%Y")
    status_md  = f"✅ Dados actualizados em {updated_at} — {days} dias"

    return (
        kpis_html,
        chart_calories,
        chart_steps,
        chart_sleep_score,
        chart_sleep_duration,
        chart_battery,
        chart_hr,
        activities_table,
        status_md,
    )


# ── UI builder ────────────────────────────────────────────────────────────────

def build_activity_tab() -> SimpleNamespace:
    ns = SimpleNamespace()

    with gr.Column():
        with gr.Row():
            ns.period_dropdown = gr.Dropdown(
                choices=_PERIOD_OPTIONS,
                value="14 dias",
                label="Período",
                interactive=True,
                scale=1,
            )
            ns.refresh_btn = gr.Button("🔄 Actualizar Dados", variant="primary", scale=0)

        ns.act_status = gr.Markdown("_Clica em **Actualizar Dados** para carregar._")

        # ── KPIs ──────────────────────────────────────────────────────────
        ns.act_kpis = gr.HTML()

        # ── Calories & Steps ──────────────────────────────────────────────
        with gr.Row():
            ns.act_chart_calories = gr.HTML()
            ns.act_chart_steps    = gr.HTML()

        # ── Sleep ─────────────────────────────────────────────────────────
        with gr.Row():
            ns.act_chart_sleep_score    = gr.HTML()
            ns.act_chart_sleep_duration = gr.HTML()

        # ── Body Battery & Resting HR ─────────────────────────────────────
        with gr.Row():
            ns.act_chart_battery = gr.HTML()
            ns.act_chart_hr      = gr.HTML()

        # ── Recent activities table ───────────────────────────────────────
        ns.act_recent = gr.HTML()

        # ── Importar dados Tanita (último ano) ────────────────────────────
        with gr.Accordion("📥 Importar dados Tanita (Último Ano)", open=False):
            gr.Markdown(
                "Liga-se ao portal MyTanita (mytanita.eu) e importa as medições "
                "de composição corporal do último ano para a base de dados local. "
                "Requer as credenciais MyTanita guardadas no sistema (serviço `tanita`)."
            )
            ns.portal_sync_btn = gr.Button(
                "📥 Importar dados Tanita", variant="primary",
            )
            ns.portal_sync_status = gr.Markdown()

        # ── Tanita → Garmin sync ──────────────────────────────────────────
        with gr.Accordion("⚖️ Sincronizar Tanita → Garmin", open=False):
            gr.Markdown(
                "Envia os dados de composição corporal da balança Tanita "
                "(armazenados localmente) para o Garmin Connect. "
                "Os dados incluem: peso, % gordura, % água, massa muscular, "
                "massa óssea, TMB, idade metabólica e avaliação física."
            )
            with gr.Row():
                ns.sync_limit = gr.Dropdown(
                    choices=_SYNC_LIMIT_OPTIONS,
                    value="Última medição",
                    label="Registos a sincronizar",
                    interactive=True,
                    scale=2,
                )
                ns.sync_btn = gr.Button(
                    "📤 Sincronizar com Garmin", variant="primary", scale=1,
                )
            ns.sync_status = gr.Markdown()

    return ns

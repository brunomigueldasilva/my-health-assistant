"""
Tab: 🎯 Objectivo

Business logic and UI builder for the goals/dashboard tab.
Covers: KPIs, evolution charts, progress bars toward goals.
"""

import re
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
from knowledge import get_knowledge_base


# ── Date parsing ─────────────────────────────────────────

def _parse_start_date(s: str) -> str:
    """Parse DD/MM/AAAA (or ISO) to YYYY-MM-DD.  Default = 1 Jan of current year."""
    s = (s or "").strip()
    if not s:
        return datetime.now().strftime("%Y-01-01")
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return datetime.now().strftime("%Y-01-01")


# ── Target computation ───────────────────────────────────

def _compute_targets(user_id: str) -> dict:
    """Derive numeric health targets from the user's profile + free-text goal.

    Priority:
      1. Explicit numbers found in the goal text via regex.
      2. Keyword-based direction + sensible health defaults.
      3. BMI-formula fallback for weight (requires height).
    """
    uid = (user_id or "").strip()
    if not uid:
        return {"goal_text": "", "fat": 20.0, "visceral": 9.0, "muscle": None, "weight": None}

    conn = _db_conn(SQLITE_DB)
    prof = conn.execute(
        "SELECT gender, height_cm, goal FROM user_profiles WHERE user_id = ?", (uid,)
    ).fetchone()
    first_mus = conn.execute(
        "SELECT muscle_mass_kg FROM body_composition_history "
        "WHERE user_id = ? AND muscle_mass_kg IS NOT NULL ORDER BY measured_at ASC LIMIT 1",
        (uid,),
    ).fetchone()
    cur_wt_row = conn.execute(
        "SELECT weight_kg FROM weight_history "
        "WHERE user_id = ? ORDER BY recorded_at DESC LIMIT 1",
        (uid,),
    ).fetchone()
    cur_comp = conn.execute(
        "SELECT muscle_mass_kg, body_fat_pct FROM body_composition_history "
        "WHERE user_id = ? AND muscle_mass_kg IS NOT NULL AND body_fat_pct IS NOT NULL "
        "ORDER BY measured_at DESC LIMIT 1",
        (uid,),
    ).fetchone()
    conn.close()

    gender    = prof["gender"]    if prof and prof["gender"]    else "male"
    height_cm = float(prof["height_cm"]) if prof and prof["height_cm"] else None
    sqlite_goal = (prof["goal"] or "").strip() if prof else ""

    # Read ALL goals from ChromaDB so multi-goal users get correct targets
    try:
        kb = get_knowledge_base()
        chroma_data = kb.preferences.get(
            where={"$and": [{"user_id": uid}, {"category": "goals"}]}
        )
        chroma_goals = chroma_data.get("documents", []) if chroma_data else []
    except Exception:
        chroma_goals = []

    if chroma_goals:
        goal_text = "; ".join(chroma_goals)
    else:
        goal_text = sqlite_goal
    gl        = goal_text.lower()
    mus_base  = float(first_mus["muscle_mass_kg"]) if first_mus else None
    cur_wt    = float(cur_wt_row["weight_kg"])     if cur_wt_row  else None

    def _f(s):
        return float(s.replace(",", "."))

    # ── WEIGHT TARGET ────────────────────────────────────
    wt_target = None

    # Strip muscle-related "X kg" so it doesn't confuse weight extraction
    gl_wt = re.sub(
        r'(\d+(?:[.,]\d+)?)\s*kg\s+(?:de\s+)?(?:m[uú]scul\w*|massa\s+muscul\w*)'
        r'|(?:m[uú]scul\w*|massa\s+muscul\w*)\s+(?:de\s+)?(\d+(?:[.,]\d+)?)\s*kg',
        '', gl
    )

    # Explicit absolute target: "atingir/chegar a/pesar/alcançar/ter X kg"
    m = re.search(
        r'(?:atingir|chegar\s+a|pesar|alcançar|ter|ficar\s+(?:em|nos|nas))\s+'
        r'(\d+(?:[.,]\d+)?)\s*kg',
        gl_wt,
    )
    if m:
        v = _f(m.group(1))
        if 30 <= v <= 300:
            wt_target = v

    # Relative loss: "perder X kg"
    if wt_target is None:
        m = re.search(r'perder\s+(\d+(?:[.,]\d+)?)\s*kg', gl_wt)
        if m and cur_wt:
            wt_target = round(cur_wt - _f(m.group(1)), 1)

    # Relative gain: "ganhar X kg" (not muscle)
    if wt_target is None:
        m = re.search(r'ganhar\s+(\d+(?:[.,]\d+)?)\s*kg', gl_wt)
        if m and cur_wt:
            wt_target = round(cur_wt + _f(m.group(1)), 1)

    # Generic "X kg" anywhere remaining — most natural health goal
    if wt_target is None:
        m = re.search(r'(\d+(?:[.,]\d+)?)\s*kg', gl_wt)
        if m:
            v = _f(m.group(1))
            if 30 <= v <= 300:
                wt_target = v

    # ── BODY FAT % TARGET ────────────────────────────────
    fat_target = None
    fat_in_goal = any(k in gl for k in ["gordura", "fat", "adipos"])

    if fat_in_goal:
        for pat in [
            r'(\d+(?:[.,]\d+)?)\s*%\s+(?:de\s+)?(?:gordura|fat)',       # "18% de gordura"
            r'(?:gordura|fat)\s+\w+\s+(\d+(?:[.,]\d+)?)\s*%',           # "gordura para 18%"
            r'(?:gordura|fat)[^%]{0,30}?(\d+(?:[.,]\d+)?)\s*%',         # "gordura corporal 18%"
            r'(?:para|até|atingir)\s+(\d+(?:[.,]\d+)?)\s*%',            # "para 18%"
        ]:
            m = re.search(pat, gl)
            if m:
                v = _f(m.group(1))
                if 5 <= v <= 50:
                    fat_target = v
                    break

    if fat_target is None:
        if fat_in_goal or any(k in gl for k in ["emagrec", "perder", "perda", "reduzir"]):
            fat_target = 17.0 if gender == "male" else 23.0
        else:
            fat_target = 20.0 if gender == "male" else 28.0

    # ── VISCERAL FAT TARGET ──────────────────────────────
    vis_target = None
    for _vis_pat in [
        # "nível 5.0 de gordura visceral" — number before visceral
        r'nível\s+(\d+(?:[.,]\d+)?)\s+(?:de\s+)?(?:gordura\s+)?(?:visceral|abdominal)',
        # "5.0 de gordura visceral" / "5 visceral"
        r'(\d+(?:[.,]\d+)?)\s+(?:de\s+)?(?:gordura\s+)?(?:visceral|abdominal)',
        # "visceral ... 5.0" — number after visceral
        r'(?:visceral|abdominal)\s+(?:\w+\s+){0,3}?(\d+(?:[.,]\d+)?)',
    ]:
        m = re.search(_vis_pat, gl)
        if m:
            v = _f(m.group(1))
            if 1 <= v <= 30:
                vis_target = v
                break

    if vis_target is None:
        vis_target = 8.0 if any(k in gl for k in ["visceral", "abdominal"]) else 9.0

    # ── MUSCLE MASS TARGET ───────────────────────────────
    mus_target = None

    # Explicit absolute: "X kg de/massa muscular" or "muscular X kg"
    for pat in [
        r'(\d+(?:[.,]\d+)?)\s*kg\s+(?:de\s+)?(?:m[uú]scul\w*|massa\s+muscul\w*)',
        r'(?:m[uú]scul\w*|massa\s+muscul\w*)\s+(?:\w+\s+){0,2}?(\d+(?:[.,]\d+)?)\s*kg',
    ]:
        m = re.search(pat, gl)
        if m:
            v = _f(m.group(1))
            if 10 <= v <= 120:
                mus_target = v
                break

    # Relative: "ganhar X kg de músculo"
    if mus_target is None:
        m = re.search(
            r'ganhar\s+(\d+(?:[.,]\d+)?)\s*kg\s+(?:de\s+)?(?:m[uú]scul\w*|massa)',
            gl,
        )
        if m and mus_base:
            mus_target = round(mus_base + _f(m.group(1)), 1)

    # ── PHASE 2 — INFER MISSING TARGETS ─────────────────
    cur_muscle  = float(cur_comp["muscle_mass_kg"]) if cur_comp else None
    cur_fat_pct = float(cur_comp["body_fat_pct"])   if cur_comp else None
    cur_wt_val  = float(cur_wt_row["weight_kg"])    if cur_wt_row else None

    _default_ratio = 0.85 if gender == "male" else 0.75
    if cur_muscle and cur_wt_val and cur_fat_pct is not None:
        _cur_lean       = cur_wt_val * (1 - cur_fat_pct / 100)
        _muscle_lean_r  = (cur_muscle / _cur_lean) if _cur_lean > 0 else _default_ratio
    else:
        _muscle_lean_r  = _default_ratio

    # Infer muscle from weight + fat targets
    if mus_target is None and wt_target is not None and fat_target is not None:
        _lean_tgt  = wt_target * (1 - fat_target / 100)
        mus_target = round(_lean_tgt * _muscle_lean_r, 1)

    # Infer weight from muscle + fat targets
    if wt_target is None and mus_target is not None and fat_target is not None:
        _lean_tgt  = mus_target / _muscle_lean_r if _muscle_lean_r > 0 else mus_target
        wt_target  = round(_lean_tgt / (1 - fat_target / 100), 1)

    # BMI fallback for weight (last resort)
    if wt_target is None and height_cm:
        h = height_cm / 100
        bmi_tgt   = 22 if any(k in gl for k in ["perder", "emagrec"]) else (24 if "ganhar peso" in gl else 23)
        wt_target = round(h * h * bmi_tgt, 1)

    # Muscle fallback: baseline + boost (last resort)
    if mus_target is None and mus_base:
        boost      = 0.08 if any(k in gl for k in ["muscul", "ganhar", "hipert", "força", "forca", "tonif"]) else 0.05
        mus_target = round(mus_base + max(2.0, mus_base * boost), 1)

    return {
        "goal_text": goal_text,
        "fat":      fat_target,
        "visceral": vis_target,
        "muscle":   mus_target,
        "weight":   wt_target,
    }


# ── Chart HTML builder ───────────────────────────────────

def _build_chart_html(
    dates: list, values: list,
    label: str, unit: str, color: str,
    target=None, decimals: int = 1, height: int = 260,
) -> str:
    import html as _html
    import json

    _no_data = (
        f"<div style='color:#475569;padding:28px;text-align:center;"
        f"background:#0f172a;border-radius:12px;font:12px Inter,sans-serif'>"
        f"{label}: sem dados</div>"
    )
    if not dates or not any(v is not None for v in values):
        return _no_data

    valid_dates = [d for d, v in zip(dates, values) if v is not None]
    date_range  = f"{valid_dates[0]} → {valid_dates[-1]}" if valid_dates else ""

    dates_json  = json.dumps(dates)
    values_json = json.dumps(values)
    unit_js     = json.dumps(unit)
    n           = len(dates)

    tgt_ds = ""
    if target is not None:
        t_vals = json.dumps([target] * n)
        t_lbl  = json.dumps(f"Meta: {target:.{decimals}f} {unit}".strip())
        tgt_ds = (
            f",{{label:{t_lbl},data:{t_vals},yAxisID:'y',"
            f"borderColor:'rgba(239,68,68,0.82)',borderWidth:1.5,"
            f"borderDash:[7,4],pointRadius:0,fill:false,tension:0,spanGaps:true,isTarget:true}}"
        )

    inner = f"""<!DOCTYPE html><html>
<head><meta charset="utf-8"><style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#0f172a;overflow:hidden}}
  .w{{background:#0f172a;padding:10px 14px 6px;height:100vh;display:flex;flex-direction:column;gap:6px}}
  .h{{display:flex;justify-content:space-between;align-items:center}}
  .t{{color:#cbd5e1;font:600 11px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase}}
  .d{{color:#475569;font:400 10px/1 Inter,sans-serif}}
  canvas{{flex:1;min-height:0}}
</style></head>
<body><div class="w">
  <div class="h"><span class="t">{label}</span><span class="d">{date_range}</span></div>
  <canvas id="c"></canvas>
</div>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/hammerjs@2.0.8/hammer.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.0.1/dist/chartjs-plugin-zoom.min.js"></script>
<script>
const labels={dates_json}, vals={values_json}, unit={unit_js}, dec={decimals}, col='{color}';
const ch={{id:'ch',afterDraw(c){{if(!c._ch)return;const{{ctx,chartArea:{{left,right,top,bottom}}}}=c;const{{x,y}}=c._ch;ctx.save();ctx.strokeStyle='rgba(203,213,225,0.15)';ctx.lineWidth=1;ctx.setLineDash([5,4]);ctx.beginPath();ctx.moveTo(x,top);ctx.lineTo(x,bottom);ctx.stroke();ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(right,y);ctx.stroke();ctx.restore();}}}};
const cv=document.getElementById('c');
const chart=new Chart(cv,{{type:'line',plugins:[ch],
  data:{{labels,datasets:[{{
    label:'{label}',data:vals,yAxisID:'y',borderColor:col,borderWidth:2,tension:0.25,fill:true,
    backgroundColor(ctx){{const ca=ctx.chart.chartArea||{{}};const g=ctx.chart.ctx.createLinearGradient(0,ca.top||0,0,ca.bottom||200);g.addColorStop(0,col+'44');g.addColorStop(1,col+'06');return g;}},
    pointBackgroundColor:'white',pointBorderColor:col,pointBorderWidth:1.5,pointRadius:3,pointHoverRadius:6,spanGaps:true
  }}{tgt_ds}]}},
  options:{{responsive:true,maintainAspectRatio:false,interaction:{{mode:'index',intersect:false}},animation:{{duration:300}},
    plugins:{{
      legend:{{display:false}},
      tooltip:{{backgroundColor:'#1e293b',borderColor:'#334155',borderWidth:1,titleColor:'#94a3b8',bodyColor:'#f9fafb',bodyFont:{{size:12,weight:'600'}},padding:8,
        filter:i=>!i.dataset.isTarget,
        callbacks:{{label:i=>i.raw!=null?` ${{i.raw.toFixed(dec)}}${{unit?' '+unit:''}}`:null}}}},
      zoom:{{zoom:{{wheel:{{enabled:true}},pinch:{{enabled:true}},mode:'x'}},pan:{{enabled:true,mode:'x'}}}}}},
    scales:{{
      x:{{ticks:{{color:'#475569',maxTicksLimit:5,maxRotation:0,font:{{size:10}}}},grid:{{color:'rgba(255,255,255,0.04)'}},border:{{color:'rgba(255,255,255,0.06)'}}}},
      y:{{ticks:{{color:'#475569',font:{{size:10}},callback:v=>v.toFixed(dec)+(unit?' '+unit:'')}},grid:{{color:'rgba(255,255,255,0.04)'}},border:{{color:'rgba(255,255,255,0.06)'}}}}}}}}}});
cv.addEventListener('mousemove',e=>{{const r=cv.getBoundingClientRect();chart._ch={{x:e.clientX-r.left,y:e.clientY-r.top}};chart.draw();}});
cv.addEventListener('mouseleave',()=>{{chart._ch=null;chart.draw();}});
cv.addEventListener('dblclick',()=>chart.resetZoom());
</script></body></html>"""

    esc = _html.escape(inner, quote=True)
    return f'<iframe srcdoc="{esc}" style="width:100%;height:{height}px;border:none;border-radius:12px;display:block;"></iframe>'


# ── Dashboard KPIs ───────────────────────────────────────

def load_dashboard_kpis(user_id: str) -> str:
    import html as _html

    uid = (user_id or "").strip()
    if not uid:
        return ""
    conn = _db_conn(SQLITE_DB)
    comp_rows = conn.execute(
        "SELECT measured_at, body_fat_pct, muscle_mass_kg, visceral_fat "
        "FROM body_composition_history WHERE user_id = ? "
        "ORDER BY measured_at DESC LIMIT 2",
        (uid,),
    ).fetchall()
    wt_rows = conn.execute(
        "SELECT recorded_at, weight_kg FROM weight_history "
        "WHERE user_id = ? ORDER BY recorded_at DESC LIMIT 2",
        (uid,),
    ).fetchall()
    conn.close()

    if not comp_rows and not wt_rows:
        return (
            "<div style='color:#475569;padding:20px;text-align:center;"
            "background:#0f172a;border-radius:12px;font:12px Inter,sans-serif'>"
            "Sem dados. Sincroniza a Tanita primeiro.</div>"
        )

    cur  = dict(comp_rows[0]) if comp_rows else {}
    prev = dict(comp_rows[1]) if len(comp_rows) > 1 else {}
    wt_cur  = float(wt_rows[0]["weight_kg"]) if wt_rows else None
    wt_prev = float(wt_rows[1]["weight_kg"]) if len(wt_rows) > 1 else None
    wt_date = wt_rows[0]["recorded_at"][:10] if wt_rows else cur.get("measured_at", "")[:10]

    def _kpi(label, val, prev_val, unit, good_dir, fmt="{:.1f}"):
        if val is None:
            return (
                f"<div class='kpi'><div class='kpi-label'>{label}</div>"
                f"<div class='kpi-val'>—</div></div>"
            )
        delta_html = ""
        if prev_val is not None:
            delta = val - prev_val
            if abs(delta) > 0.01:
                arrow = "▲" if delta > 0 else "▼"
                is_good = (delta < 0 and good_dir == "down") or (delta > 0 and good_dir == "up")
                color = "#10b981" if is_good else "#f87171"
                delta_html = (
                    f"<span class='kpi-delta' style='color:{color}'>"
                    f"{arrow} {abs(delta):.1f}{unit}</span>"
                )
        return (
            f"<div class='kpi'>"
            f"<div class='kpi-label'>{label}</div>"
            f"<div class='kpi-val'>{fmt.format(val)}"
            f"<span class='kpi-unit'>{unit}</span></div>"
            f"{delta_html}</div>"
        )

    kpis_html = (
        _kpi("Peso",              wt_cur,                        wt_prev,                       " kg", "down")
        + _kpi("Gordura Corporal", cur.get("body_fat_pct"),   prev.get("body_fat_pct"),   "%",   "down")
        + _kpi("Gordura Visceral", cur.get("visceral_fat"),   prev.get("visceral_fat"),   "",    "down")
        + _kpi("Massa Muscular",   cur.get("muscle_mass_kg"), prev.get("muscle_mass_kg"), " kg", "up")
    )
    measured_date = wt_date

    inner = f"""<!DOCTYPE html><html>
<head><meta charset="utf-8"><style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #0f172a; font-family: Inter,sans-serif; overflow: hidden; padding: 12px 16px; }}
  .row {{ display: flex; gap: 12px; }}
  .kpi {{ flex: 1; background: #1e293b; border-radius: 10px; padding: 14px 16px;
          border: 1px solid rgba(255,255,255,0.07); min-width: 0; }}
  .kpi-label {{ color: #64748b; font-size: 10px; font-weight: 600; letter-spacing: .07em;
                text-transform: uppercase; margin-bottom: 6px; }}
  .kpi-val {{ color: #f1f5f9; font-size: 22px; font-weight: 700; line-height: 1; }}
  .kpi-unit {{ font-size: 12px; font-weight: 500; color: #94a3b8; margin-left: 2px; }}
  .kpi-delta {{ display: block; margin-top: 6px; font-size: 11px; font-weight: 600; }}
  .date {{ color: #334155; font-size: 10px; text-align: right; margin-top: 8px; }}
</style></head>
<body>
<div class="row">{kpis_html}</div>
<div class="date">Última medição: {measured_date}</div>
</body></html>"""

    escaped = _html.escape(inner, quote=True)
    return f'<iframe srcdoc="{escaped}" style="width:100%;height:130px;border:none;border-radius:12px;display:block;"></iframe>'


def load_dashboard_charts(user_id: str, start_date_str: str = "") -> tuple:
    """Returns (html_fat, html_visceral, html_weight, html_muscle) — four separate charts."""
    uid = (user_id or "").strip()
    _empty = (
        "<div style='color:#475569;padding:28px;text-align:center;"
        "background:#0f172a;border-radius:12px;font:12px Inter,sans-serif'>Sem dados.</div>"
    )
    if not uid:
        return (_empty,) * 4

    cutoff  = _parse_start_date(start_date_str)
    targets = _compute_targets(uid)

    conn = _db_conn(SQLITE_DB)
    comp_rows = conn.execute(
        "SELECT measured_at, body_fat_pct, visceral_fat, muscle_mass_kg "
        "FROM body_composition_history WHERE user_id = ? AND measured_at >= ? "
        "ORDER BY measured_at ASC",
        (uid, cutoff),
    ).fetchall()
    wt_rows = conn.execute(
        "SELECT recorded_at, weight_kg FROM weight_history "
        "WHERE user_id = ? AND recorded_at >= ? ORDER BY recorded_at ASC",
        (uid, cutoff),
    ).fetchall()
    conn.close()

    comp_dates = [r["measured_at"][:10] for r in comp_rows]
    fat_vals   = [r["body_fat_pct"]   for r in comp_rows]
    vis_vals   = [r["visceral_fat"]   for r in comp_rows]
    mus_vals   = [r["muscle_mass_kg"] for r in comp_rows]
    wt_dates   = [r["recorded_at"][:10] for r in wt_rows]
    wt_vals    = [r["weight_kg"]        for r in wt_rows]

    return (
        _build_chart_html(comp_dates, fat_vals, "Gordura Corporal", "%",  "#f59e0b", targets.get("fat"),      decimals=1),
        _build_chart_html(comp_dates, vis_vals, "Gordura Visceral", "",   "#f97316", targets.get("visceral"), decimals=1),
        _build_chart_html(wt_dates,   wt_vals,  "Peso",             "kg", "#10b981", targets.get("weight"),   decimals=1),
        _build_chart_html(comp_dates, mus_vals, "Massa Muscular",   "kg", "#3b82f6", targets.get("muscle"),   decimals=1),
    )


def load_dashboard_progress(user_id: str, start_date_str: str = "") -> str:
    import html as _html

    uid = (user_id or "").strip()
    if not uid:
        return ""

    cutoff   = _parse_start_date(start_date_str)
    targets  = _compute_targets(uid)
    goal_txt = (targets.get("goal_text") or "").strip()

    conn = _db_conn(SQLITE_DB)
    first_comp = conn.execute(
        "SELECT body_fat_pct, muscle_mass_kg, visceral_fat FROM body_composition_history "
        "WHERE user_id = ? AND measured_at >= ? ORDER BY measured_at ASC LIMIT 1", (uid, cutoff),
    ).fetchone()
    latest_comp = conn.execute(
        "SELECT body_fat_pct, muscle_mass_kg, visceral_fat, measured_at "
        "FROM body_composition_history WHERE user_id = ? ORDER BY measured_at DESC LIMIT 1", (uid,),
    ).fetchone()
    first_wt = conn.execute(
        "SELECT weight_kg FROM weight_history "
        "WHERE user_id = ? AND recorded_at >= ? ORDER BY recorded_at ASC LIMIT 1", (uid, cutoff),
    ).fetchone()
    latest_wt = conn.execute(
        "SELECT weight_kg, recorded_at FROM weight_history "
        "WHERE user_id = ? ORDER BY recorded_at DESC LIMIT 1", (uid,),
    ).fetchone()
    conn.close()

    if not first_comp and not first_wt:
        return ""

    first_comp  = dict(first_comp)  if first_comp  else {}
    latest_comp = dict(latest_comp) if latest_comp else {}
    wt_start    = float(first_wt["weight_kg"])  if first_wt  else None
    wt_cur      = float(latest_wt["weight_kg"]) if latest_wt else None
    wt_date     = latest_wt["recorded_at"][:10] if latest_wt else ""
    comp_date   = latest_comp.get("measured_at", "")[:10]

    wt_target = targets.get("weight")
    wt_dir    = "down" if (wt_cur and wt_target and wt_cur > wt_target) else "up"

    def _bar(label, start, current, target, unit, good_dir, mdate=""):
        if start is None or current is None or target is None:
            return ""
        start, current, target = float(start), float(current), float(target)
        if good_dir == "down":
            span  = start - target
            pct   = max(0.0, min(100.0, (start - current) / span * 100)) if span > 0 else (100.0 if current <= target else 0.0)
            is_good = current < start
            arrow   = "▼" if current < start else ("▲" if current > start else "→")
            op = "≤"
        else:
            span  = target - start
            pct   = max(0.0, min(100.0, (current - start) / span * 100)) if span > 0 else (100.0 if current >= target else 0.0)
            is_good = current > start
            arrow   = "▲" if current > start else ("▼" if current < start else "→")
            op = "≥"

        delta    = current - start
        bar_col  = "#10b981" if is_good else "#f87171"
        achieved = (current <= target) if good_dir == "down" else (current >= target)
        icon     = "✅" if achieved else "🎯"
        ud       = unit.strip()
        date_tag = f'<span class="mdate">{mdate}</span>' if mdate else ""

        return f"""
<div class="goal">
  <div class="g-hdr">
    <span class="g-lbl">{icon} {label}</span>
    <span class="g-vals">
      <span class="v-start">{start:.1f}{ud}</span>
      <span class="arr">{arrow}</span>
      <span class="v-cur" style="color:{bar_col}">{current:.1f}{ud}</span>
      <span class="v-tgt">(objetivo: {op}{target:.0f}{ud})</span>
      {date_tag}
    </span>
  </div>
  <div class="bar-bg"><div class="bar-fill" style="width:{pct:.0f}%;background:{bar_col}"></div></div>
  <div class="g-delta" style="color:{bar_col}">{delta:+.1f}{ud} desde o início · {pct:.0f}% do caminho</div>
</div>"""

    goal_html = (
        f'<div class="user-goal">🎯 Objetivo: {_html.escape(goal_txt)}</div>' if goal_txt else ""
    )
    bars = (
        _bar("Peso Corporal",    wt_start,                         wt_cur,                         wt_target,             " kg", wt_dir,  wt_date)
        + _bar("Gordura Corporal", first_comp.get("body_fat_pct"),   latest_comp.get("body_fat_pct"),  targets.get("fat"),  " %",  "down", comp_date)
        + _bar("Gordura Visceral", first_comp.get("visceral_fat"),   latest_comp.get("visceral_fat"),  targets.get("visceral"), "", "down", comp_date)
        + _bar("Massa Muscular",   first_comp.get("muscle_mass_kg"), latest_comp.get("muscle_mass_kg"), targets.get("muscle"), " kg", "up", comp_date)
    )

    inner = f"""<!DOCTYPE html><html>
<head><meta charset="utf-8"><style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#0f172a;font-family:Inter,sans-serif;padding:14px 16px;overflow:auto}}
  .user-goal{{color:#e2e8f0;font:600 12px/1.4 Inter,sans-serif;background:#1e3a5f;
              border-left:3px solid #3b82f6;padding:8px 12px;border-radius:6px;margin-bottom:14px}}
  .sec{{color:#94a3b8;font:600 11px/1 Inter,sans-serif;letter-spacing:.08em;
         text-transform:uppercase;margin-bottom:14px}}
  .goal{{margin-bottom:18px}}
  .g-hdr{{display:flex;justify-content:space-between;align-items:baseline;
          margin-bottom:7px;flex-wrap:wrap;gap:6px}}
  .g-lbl{{color:#cbd5e1;font:600 12px/1 Inter,sans-serif}}
  .g-vals{{display:flex;align-items:center;gap:6px;font-size:12px}}
  .v-start{{color:#64748b;font-weight:500}}
  .arr{{color:#94a3b8;font-size:10px}}
  .v-cur{{font-weight:700;font-size:13px}}
  .v-tgt{{color:#475569;font-size:10px}}
  .mdate{{color:#334155;font-size:10px}}
  .bar-bg{{background:#1e293b;border-radius:6px;height:8px;
           border:1px solid rgba(255,255,255,0.07);overflow:hidden}}
  .bar-fill{{height:100%;border-radius:6px;transition:width .6s ease}}
  .g-delta{{font:500 10px/1 Inter,sans-serif;margin-top:5px}}
</style></head>
<body>
{goal_html}
<div class="sec">Progresso face ao Objetivo</div>
{bars}
</body></html>"""

    escaped = _html.escape(inner, quote=True)
    return f'<iframe srcdoc="{escaped}" style="width:100%;height:430px;border:none;border-radius:12px;display:block;"></iframe>'


def load_full_dashboard(user_id: str, start_date_str: str = "") -> tuple:
    kpis                               = load_dashboard_kpis(user_id)
    fat_c, vis_c, wt_c, mus_c         = load_dashboard_charts(user_id, start_date_str)
    progress                           = load_dashboard_progress(user_id, start_date_str)
    return (kpis, fat_c, vis_c, wt_c, mus_c, progress)


# ── UI builder ───────────────────────────────────────────

def build_goals_tab() -> SimpleNamespace:
    """Create the goals/dashboard tab UI. Must be called inside a gr.Blocks() context."""
    with gr.Row():
        dash_refresh_btn = gr.Button("🔄 Atualizar", variant="primary", scale=1)
        dash_start_date = gr.Textbox(
            label="Data de início",
            placeholder="DD/MM/AAAA  (vazio = 1 Jan do ano em curso)",
            scale=2,
            max_lines=1,
        )
    dash_kpis = gr.HTML()
    with gr.Row():
        dash_chart_fat      = gr.HTML()
        dash_chart_visceral = gr.HTML()
    with gr.Row():
        dash_chart_weight   = gr.HTML()
        dash_chart_muscle   = gr.HTML()
    dash_progress = gr.HTML()

    return SimpleNamespace(
        dash_refresh_btn=dash_refresh_btn,
        dash_start_date=dash_start_date,
        dash_kpis=dash_kpis,
        dash_chart_fat=dash_chart_fat,
        dash_chart_visceral=dash_chart_visceral,
        dash_chart_weight=dash_chart_weight,
        dash_chart_muscle=dash_chart_muscle,
        dash_progress=dash_progress,
    )

"""
Garmin Connect Tools — sleep, daily stats, heart rate, activities, body battery, training status.
Tool docstrings in English for LLM reliability.
"""

import logging
import sys
from pathlib import Path
from datetime import date, timedelta

# Allow running this file directly from the tools/ directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from garminconnect import Garmin

from config import DATA_DIR
from xai import xai_tool

logger = logging.getLogger(__name__)

# ── Auth ──────────────────────────────────────────────────────────────────────

TOKEN_BASE = DATA_DIR / "garmin_tokens"

# Per-user client cache: { user_id: Garmin }
_clients: dict[str, Garmin] = {}


def _token_store(user_id: str) -> Path:
    """Return the token directory for a specific user."""
    return TOKEN_BASE / str(user_id)


def _get_client(user_id: str) -> Garmin:
    """Return an authenticated Garmin client for *user_id*, reusing the cached session."""
    uid = str(user_id)
    if uid in _clients:
        return _clients[uid]

    store = _token_store(uid)
    token_file = store / "oauth1_token.json"
    if not token_file.exists():
        raise RuntimeError(
            f"Garmin tokens not found in {store}.\n"
            "Run the browser auth script first:\n"
            f"  python scripts/garmin_browser_auth.py --user {uid}"
        )

    client = Garmin()
    client.login(tokenstore=str(store))
    logger.info("Garmin session resumed from token cache for user %s.", uid)

    _clients[uid] = client
    return client


# ── Tools ─────────────────────────────────────────────────────────────────────

@xai_tool
def get_garmin_daily_stats(user_id: str, target_date: str = "") -> str:
    """
    Return daily activity summary from Garmin Connect (steps, calories, resting HR, distance).

    Args:
        user_id: The user ID whose Garmin account should be queried.
        target_date: Date in YYYY-MM-DD format. Defaults to today.

    Returns:
        Formatted daily stats summary.
    """
    if not target_date:
        target_date = date.today().isoformat()

    try:
        client = _get_client(user_id)
        stats = client.get_stats(target_date)

        return (
            f"Garmin daily stats for {target_date}:\n"
            f"  Steps:              {stats.get('totalSteps', 'N/A')}\n"
            f"  Calories:           {stats.get('totalKilocalories', 'N/A')} kcal\n"
            f"  Resting HR:         {stats.get('restingHeartRate', 'N/A')} bpm\n"
            f"  Distance:           {stats.get('totalDistanceMeters', 'N/A')} m\n"
            f"  Active time:        {stats.get('activeKilocalories', 'N/A')} kcal active\n"
            f"  Stress (avg):       {stats.get('averageStressLevel', 'N/A')}\n"
            f"  Body Battery (end): {stats.get('bodyBatteryMostRecentValue', 'N/A')}"
        )
    except Exception as e:
        logger.error("get_garmin_daily_stats error: %s", e)
        return f"Error fetching Garmin daily stats: {e}"


@xai_tool
def get_garmin_sleep_data(user_id: str, target_date: str = "") -> str:
    """
    Return sleep data from Garmin Connect for the given date.

    Args:
        user_id: The user ID whose Garmin account should be queried.
        target_date: Date in YYYY-MM-DD format. Defaults to today.

    Returns:
        Sleep duration, stages, and score.
    """
    if not target_date:
        target_date = date.today().isoformat()

    try:
        client = _get_client(user_id)
        sleep = client.get_sleep_data(target_date)

        daily = sleep.get("dailySleepDTO", {})
        duration_secs = daily.get("sleepTimeSeconds", 0)
        hours, minutes = divmod(duration_secs // 60, 60)

        return (
            f"Garmin sleep data for {target_date}:\n"
            f"  Total sleep:  {hours}h {minutes}min\n"
            f"  Deep sleep:   {daily.get('deepSleepSeconds', 0) // 60} min\n"
            f"  Light sleep:  {daily.get('lightSleepSeconds', 0) // 60} min\n"
            f"  REM sleep:    {daily.get('remSleepSeconds', 0) // 60} min\n"
            f"  Awake:        {daily.get('awakeSleepSeconds', 0) // 60} min\n"
            f"  Sleep score:  {daily.get('sleepScores', {}).get('overall', {}).get('value', 'N/A')}"
        )
    except Exception as e:
        logger.error("get_garmin_sleep_data error: %s", e)
        return f"Error fetching Garmin sleep data: {e}"


@xai_tool
def get_garmin_heart_rate(user_id: str, target_date: str = "") -> str:
    """
    Return heart rate data from Garmin Connect (resting HR, min/max, HRV).

    Args:
        user_id: The user ID whose Garmin account should be queried.
        target_date: Date in YYYY-MM-DD format. Defaults to today.

    Returns:
        Heart rate summary.
    """
    if not target_date:
        target_date = date.today().isoformat()

    try:
        client = _get_client(user_id)
        hr = client.get_heart_rates(target_date)

        return (
            f"Garmin heart rate for {target_date}:\n"
            f"  Resting HR: {hr.get('restingHeartRate', 'N/A')} bpm\n"
            f"  Max HR:     {hr.get('maxHeartRate', 'N/A')} bpm\n"
            f"  Min HR:     {hr.get('minHeartRate', 'N/A')} bpm"
        )
    except Exception as e:
        logger.error("get_garmin_heart_rate error: %s", e)
        return f"Error fetching Garmin heart rate data: {e}"


@xai_tool
def get_garmin_activities(user_id: str, limit: int = 5) -> str:
    """
    Return recent activities from Garmin Connect (runs, rides, swims, etc.).

    Args:
        user_id: The user ID whose Garmin account should be queried.
        limit: Number of recent activities to retrieve (default 5, max 20).

    Returns:
        List of recent activities with type, duration, distance, and calories.
    """
    limit = min(limit, 20)

    try:
        client = _get_client(user_id)
        activities = client.get_activities(0, limit)

        if not activities:
            return "No recent activities found on Garmin Connect."

        lines = [f"Last {len(activities)} Garmin activities:"]
        for act in activities:
            duration_secs = act.get("duration", 0)
            h, m = divmod(int(duration_secs) // 60, 60)
            lines.append(
                f"  • {act.get('startTimeLocal', '')[:10]} — {act.get('activityType', {}).get('typeKey', 'unknown')}"
                f" | {h}h {m}min"
                f" | {act.get('distance', 0) / 1000:.2f} km"
                f" | {act.get('calories', 'N/A')} kcal"
            )
        return "\n".join(lines)
    except Exception as e:
        logger.error("get_garmin_activities error: %s", e)
        return f"Error fetching Garmin activities: {e}"


@xai_tool
def get_garmin_body_battery(user_id: str, target_date: str = "") -> str:
    """
    Return Body Battery data from Garmin Connect for the given date.

    Args:
        user_id: The user ID whose Garmin account should be queried.
        target_date: Date in YYYY-MM-DD format. Defaults to today.

    Returns:
        Body Battery start, end, and charged/drained values.
    """
    if not target_date:
        target_date = date.today().isoformat()

    try:
        client = _get_client(user_id)
        stats = client.get_stats(target_date)

        return (
            f"Garmin Body Battery for {target_date}:\n"
            f"  Current (most recent): {stats.get('bodyBatteryMostRecentValue', 'N/A')}\n"
            f"  Highest today:         {stats.get('bodyBatteryHighestValue', 'N/A')}\n"
            f"  Lowest today:          {stats.get('bodyBatteryLowestValue', 'N/A')}\n"
            f"  Charged:               {stats.get('bodyBatteryDuringSleep', 'N/A')}\n"
            f"  Drained:               {stats.get('bodyBatteryDrainedDuringActivity', 'N/A')}"
        )
    except Exception as e:
        logger.error("get_garmin_body_battery error: %s", e)
        return f"Error fetching Garmin Body Battery data: {e}"


@xai_tool
def get_garmin_training_status(user_id: str) -> str:
    """
    Return training status and training load from Garmin Connect.

    Args:
        user_id: The user ID whose Garmin account should be queried.

    Returns:
        Training status, VO2 max estimate, training load, and recovery time.
    """
    try:
        client = _get_client(user_id)
        today = date.today().isoformat()
        status = client.get_training_status(today)

        latest = status.get("trainingStatusFeedbackPhrase", "N/A") if isinstance(status, dict) else "N/A"

        user_metrics = client.get_user_summary(today)
        vo2max = user_metrics.get("vo2MaxValue", "N/A")

        return (
            f"Garmin training status ({today}):\n"
            f"  Status:          {latest}\n"
            f"  VO2 Max:         {vo2max}"
        )
    except Exception as e:
        logger.error("get_garmin_training_status error: %s", e)
        return f"Error fetching Garmin training status: {e}"


@xai_tool
def get_garmin_weekly_summary(user_id: str) -> str:
    """
    Return a weekly activity summary from Garmin Connect (last 7 days).

    Args:
        user_id: The user ID whose Garmin account should be queried.

    Returns:
        Total steps, calories, active time, and distance for the past 7 days.
    """
    try:
        client = _get_client(user_id)
        end = date.today()
        start = end - timedelta(days=6)

        total_steps = 0
        total_calories = 0
        total_distance = 0
        total_active_kcal = 0

        for i in range(7):
            day = (start + timedelta(days=i)).isoformat()
            try:
                s = client.get_stats(day)
                total_steps += s.get("totalSteps", 0) or 0
                total_calories += s.get("totalKilocalories", 0) or 0
                total_distance += s.get("totalDistanceMeters", 0) or 0
                total_active_kcal += s.get("activeKilocalories", 0) or 0
            except Exception:
                pass

        return (
            f"Garmin weekly summary ({start.isoformat()} → {end.isoformat()}):\n"
            f"  Total steps:    {total_steps:,}\n"
            f"  Total calories: {total_calories:,} kcal\n"
            f"  Active kcal:    {total_active_kcal:,} kcal\n"
            f"  Distance:       {total_distance / 1000:.2f} km"
        )
    except Exception as e:
        logger.error("get_garmin_weekly_summary error: %s", e)
        return f"Error fetching Garmin weekly summary: {e}"


# ── Raw data helpers (internal — no XAI decoration) ──────────────────────────

def get_garmin_stats_range(user_id: str, days: int = 30) -> list:
    """
    Return daily stats for the last N days using parallel requests.
    Internal use (charts/dashboards) — not decorated with @xai_tool.

    Returns list of dicts ordered by date (oldest first):
      {date, steps, calories, active_kcal, body_battery, resting_hr, distance_m}
    """
    from concurrent.futures import ThreadPoolExecutor

    try:
        client = _get_client(user_id)
    except Exception as e:
        logger.error("get_garmin_stats_range: auth error: %s", e)
        return []

    end = date.today()
    dates = [(end - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]

    def _fetch(day: str) -> dict:
        try:
            s = client.get_stats(day)
            return {
                "date":        day,
                "steps":       s.get("totalSteps") or 0,
                "calories":    s.get("totalKilocalories") or 0,
                "active_kcal": s.get("activeKilocalories") or 0,
                "body_battery":s.get("bodyBatteryMostRecentValue"),
                "resting_hr":  s.get("restingHeartRate"),
                "distance_m":  s.get("totalDistanceMeters") or 0,
            }
        except Exception:
            return {"date": day, "steps": 0, "calories": 0, "active_kcal": 0,
                    "body_battery": None, "resting_hr": None, "distance_m": 0}

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = {d: r for d, r in zip(dates, ex.map(_fetch, dates))}

    return [results[d] for d in dates]


def get_garmin_sleep_range(user_id: str, days: int = 14) -> list:
    """
    Return sleep data for the last N days using parallel requests.
    Internal use (charts/dashboards) — not decorated with @xai_tool.

    Returns list of dicts ordered by date (oldest first):
      {date, total_minutes, score, deep_min, rem_min}
    """
    from concurrent.futures import ThreadPoolExecutor

    try:
        client = _get_client(user_id)
    except Exception as e:
        logger.error("get_garmin_sleep_range: auth error: %s", e)
        return []

    end = date.today()
    dates = [(end - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]

    def _fetch(day: str) -> dict:
        try:
            data  = client.get_sleep_data(day)
            daily = (data or {}).get("dailySleepDTO") or {}
            scores = (daily.get("sleepScores") or {})
            score  = (scores.get("overall") or {}).get("value")
            return {
                "date":          day,
                "total_minutes": (daily.get("sleepTimeSeconds") or 0) // 60,
                "score":         score,
                "deep_min":      (daily.get("deepSleepSeconds") or 0) // 60,
                "rem_min":       (daily.get("remSleepSeconds") or 0) // 60,
            }
        except Exception:
            return {"date": day, "total_minutes": 0, "score": None, "deep_min": 0, "rem_min": 0}

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = {d: r for d, r in zip(dates, ex.map(_fetch, dates))}

    return [results[d] for d in dates]


def get_garmin_activities_raw(user_id: str, limit: int = 50) -> list:
    """
    Return raw activities as a list of dicts. Internal use (streak, charts).
    Not decorated with @xai_tool.

    Returns list of dicts (newest first):
      {date, type, duration_min, distance_km, calories,
       avg_hr, max_hr, sweat_loss_ml}
    """
    try:
        client  = _get_client(user_id)
        result  = []
        batch   = 100  # Garmin API page size
        start   = 0
        while len(result) < limit:
            fetch = min(batch, limit - len(result))
            activities = client.get_activities(start, fetch)
            if not activities:
                break
            for act in activities:
                dur = int(act.get("duration") or 0)
                sweat = (
                    act.get("waterEstimated")
                    or act.get("sweatLoss")
                    or act.get("estimatedSweatLoss")
                )
                result.append({
                    "date":         (act.get("startTimeLocal") or "")[:10],
                    "type":         (act.get("activityType") or {}).get("typeKey", "unknown"),
                    "duration_min": dur // 60,
                    "distance_km":  (act.get("distance") or 0) / 1000,
                    "calories":     act.get("calories") or 0,
                    "avg_hr":       act.get("averageHR"),
                    "max_hr":       act.get("maxHR"),
                    "sweat_loss_ml":int(sweat) if sweat is not None else None,
                })
            if len(activities) < fetch:
                break  # no more activities available
            start += fetch
        return result
    except Exception as e:
        logger.error("get_garmin_activities_raw error: %s", e)
        return []


@xai_tool
def sync_tanita_to_garmin(user_id: str, limit: int = 1) -> str:
    """
    Push Tanita body composition measurements from the local database to Garmin Connect.

    Reads the most recent Tanita measurements stored in SQLite for the given user
    and uploads weight, body fat %, body water %, muscle mass, bone mass, BMR,
    metabolic age, and physique rating to Garmin Connect's weight/body-composition API.

    Args:
        user_id: The user ID whose Tanita data should be synced.
        limit: Number of most recent measurements to upload (default 1, max 30).

    Returns:
        Status message with per-record sync results.
    """
    import sqlite3 as _sqlite3
    from config import SQLITE_DB as _SQLITE_DB

    limit = max(1, min(int(limit), 30))

    # ── Fetch Tanita records from SQLite ───────────────────────────────────
    try:
        conn = _sqlite3.connect(str(_SQLITE_DB))
        conn.row_factory = _sqlite3.Row
        rows = conn.execute(
            "SELECT measured_at, weight_kg, bmi, body_fat_pct, body_water_pct, "
            "visceral_fat, muscle_mass_kg, bone_mass_kg, bmr_kcal, "
            "metabolic_age, physique_rating "
            "FROM body_composition_history "
            "WHERE user_id = ? AND weight_kg IS NOT NULL "
            "ORDER BY measured_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        conn.close()
    except Exception as e:
        logger.error("sync_tanita_to_garmin: DB read error: %s", e)
        return f"Erro ao ler dados Tanita: {e}"

    if not rows:
        return (
            "Sem dados Tanita para este utilizador. "
            "Sincroniza primeiro a balança Tanita."
        )

    # ── Push to Garmin Connect ─────────────────────────────────────────────
    try:
        client = _get_client(user_id)
    except Exception as e:
        return f"Erro de autenticação Garmin: {e}"

    if not hasattr(client, "add_body_composition"):
        return (
            "❌ A versão instalada da biblioteca garminconnect não suporta "
            "upload de composição corporal. Actualiza com:\n"
            "  pip install --upgrade garminconnect"
        )

    results = []
    for row in rows:
        measured_at = row["measured_at"]          # "YYYY-MM-DD HH:MM:SS"
        timestamp   = measured_at.replace(" ", "T")  # ISO-8601 for Garmin API

        weight       = row["weight_kg"]
        fat_pct      = row["body_fat_pct"]
        water_pct    = row["body_water_pct"]
        muscle_kg    = row["muscle_mass_kg"]
        bone_kg      = row["bone_mass_kg"]
        bmr          = row["bmr_kcal"]
        met_age      = row["metabolic_age"]
        physique     = row["physique_rating"]
        visceral_fat = row["visceral_fat"]   # Tanita visceral fat rating (1–60)
        bmi          = row["bmi"]

        try:
            client.add_body_composition(
                timestamp           = timestamp,
                weight              = weight,
                percent_fat         = fat_pct,
                percent_hydration   = water_pct,
                muscle_mass         = muscle_kg,
                bone_mass           = bone_kg,
                basal_met           = bmr,
                metabolic_age       = met_age,
                physique_rating     = physique,
                visceral_fat_rating = visceral_fat,
                bmi                 = bmi,
            )
            date_str = measured_at[:10]
            results.append(
                f"✅ {date_str}: peso={weight} kg | gordura={fat_pct}% "
                f"| músculo={muscle_kg} kg | visceral={visceral_fat}"
            )
            logger.info("sync_tanita_to_garmin: uploaded record for %s", date_str)
        except Exception as e:
            logger.error("sync_tanita_to_garmin: upload error for %s: %s", measured_at, e)
            results.append(f"❌ {measured_at[:10]}: {e}")

    synced = sum(1 for r in results if r.startswith("✅"))
    header = (
        f"Sincronização Tanita → Garmin: {synced}/{len(results)} registos enviados.\n"
    )
    return header + "\n".join(results)


# ── Export list (used by agents) ─────────────────────────────────────────────

GARMIN_TOOLS = [
    get_garmin_daily_stats,
    get_garmin_sleep_data,
    get_garmin_heart_rate,
    get_garmin_activities,
    get_garmin_body_battery,
    get_garmin_training_status,
    get_garmin_weekly_summary,
    sync_tanita_to_garmin,
]


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    test_user = input("User ID para testar: ").strip() or "test"

    print(f"Authenticating with Garmin Connect for user {test_user!r}...")
    try:
        client = _get_client(test_user)
        print(f"  Token stored at: {_token_store(test_user)}")

        print("\nFetching today's stats...")
        print(get_garmin_daily_stats(test_user))

        print("\nFetching sleep data...")
        print(get_garmin_sleep_data(test_user))

        print("\nFetching recent activities...")
        print(get_garmin_activities(test_user, 3))

    except Exception as e:
        print(f"\nError: {e}")

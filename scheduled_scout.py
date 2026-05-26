"""Headless scout runner — corre como cron / launchd para mantener Felynder
con queue fresca sin intervención.

Estrategia:
  1. Picks el tema que se ha scouteado hace más tiempo (rotación natural).
  2. Llama `scout_theme_until_target` con filtros default (MX + female + individual).
  3. Loggea a data/scheduled_scout.log.

Uso:
    .venv/bin/python scheduled_scout.py
    .venv/bin/python scheduled_scout.py --target 8 --theme "Yoga MX"

Programar con launchd: ver com.felyfit.scout.plist
"""
import argparse
import sys
from datetime import datetime
from pathlib import Path

# Asegurar que corra desde el dir del proyecto sin importar desde dónde se invoque
PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

import config
import db
import apify_jobs

LOG_FILE = PROJECT_DIR / "data" / "scheduled_scout.log"


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def pick_next_theme() -> str:
    """Elige el tema con scout más antiguo (o nunca scouteado).
    Rotación natural sin necesidad de tracking state explícito."""
    themes = list(config.HASHTAG_THEMES.keys())
    with db.connect() as conn:
        # Ultima fecha de scout por tema (extraído de session_label "Theme: <name>")
        rows = conn.execute("""
            SELECT REPLACE(session_label, 'Theme: ', '') AS theme,
                   MAX(started_at) AS last_run
            FROM scout_runs
            WHERE session_label LIKE 'Theme: %'
            GROUP BY theme
        """).fetchall()
    last_run_by_theme = {r["theme"]: r["last_run"] for r in rows}

    # Tema nunca scouteado tiene prioridad infinita; los demás se ordenan por antigüedad
    def sort_key(t: str):
        return last_run_by_theme.get(t) or "0000-00-00"

    themes.sort(key=sort_key)
    chosen = themes[0]
    last = last_run_by_theme.get(chosen, "nunca")
    log(f"Tema elegido: '{chosen}' (último scout: {last})")
    return chosen


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=int, default=5,
                        help="Aptas a encontrar (default: 5)")
    parser.add_argument("--theme", type=str, default=None,
                        help="Forzar tema específico. Si no, rota automáticamente.")
    parser.add_argument("--countries", nargs="+", default=["MX"],
                        help="Países permitidos (default: MX)")
    parser.add_argument("--genders", nargs="+", default=["female"],
                        help="Géneros permitidos (default: female)")
    parser.add_argument("--account-types", nargs="+", default=["individual"],
                        help="Tipos de cuenta (default: individual)")
    args = parser.parse_args()

    db.init()
    log("=" * 60)
    log(f"Scheduled scout iniciado — target={args.target}")

    theme = args.theme or pick_next_theme()

    try:
        result = apify_jobs.scout_theme_until_target(
            theme,
            target_passing=args.target,
            allowed_countries=args.countries,
            allowed_genders=args.genders,
            allowed_account_types=args.account_types,
        )
    except Exception as e:
        log(f"ERROR: {e}")
        sys.exit(1)

    if "error" in result:
        log(f"ERROR de scout: {result['error']}")
        sys.exit(1)

    log(
        f"Done · tema='{theme}' · "
        f"aptas={result['passing']}/{result['target']} · "
        f"auto_rejected={result['auto_rejected']} · "
        f"scrapeadas={result['scraped']} · "
        f"costo=${result['compute_usd']:.4f} · "
        f"reached_target={result['reached_target']}"
    )


if __name__ == "__main__":
    main()

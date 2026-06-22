"""Literature Meet Up - Character Encounters web app.

Run locally with:
    uvicorn webapp.main:app --reload

Then open http://127.0.0.1:8000
"""
import os
from pathlib import Path

import psycopg2
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from literature_meetup.encounter_queries import (
    LOCATION_GRANULARITIES,
    TIME_GRANULARITIES,
    ensure_views,
    random_encounter,
)

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
if ENV_PATH.exists():
    for line in ENV_PATH.read_text().splitlines():
        key, _, value = line.partition("=")
        if key:
            os.environ.setdefault(key, value)

app = FastAPI(title="Literature Meet Up - Encounters")


def get_connection():
    return psycopg2.connect(os.environ["DATABASE_URL"])


@app.on_event("startup")
def on_startup() -> None:
    conn = get_connection()
    try:
        ensure_views(conn)
    finally:
        conn.close()


@app.get("/api/encounter")
def api_encounter(
    time: str = Query("year"),
    location: str = Query("city"),
):
    if time not in TIME_GRANULARITIES:
        raise HTTPException(400, f"Invalid time granularity: {time!r}. Must be one of {TIME_GRANULARITIES}.")
    if location not in LOCATION_GRANULARITIES:
        raise HTTPException(400, f"Invalid location granularity: {location!r}. Must be one of {LOCATION_GRANULARITIES}.")

    conn = get_connection()
    try:
        encounter = random_encounter(conn, time, location)
    finally:
        conn.close()

    if encounter is None:
        return {"found": False}
    return {"found": True, "encounter": encounter}


app.mount("/", StaticFiles(directory=Path(__file__).resolve().parent / "static", html=True), name="static")

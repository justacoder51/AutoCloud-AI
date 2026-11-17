"""Private test image only. Never mounted by app.main or the public dashboard."""
from datetime import datetime, timezone
import hashlib
import os
import re
import time
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
_memory = None
_memory_until = 0.0


class Probe(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    sequence: int = Field(ge=0, lt=1800)
    fault: Literal["none", "cpu_stress", "memory_growth", "latency", "http_503"] = "none"


def permitted(request, run_id):
    try:
        expires = datetime.fromisoformat(os.environ["LAB_EXPIRES_AT"])
        valid = (os.environ.get("AUTOCLOUD_COMPONENT") == "validation_lab"
                 and re.fullmatch(r"[a-f0-9]{32}", os.environ.get("LAB_RUN_ID", ""))
                 and run_id == os.environ["LAB_RUN_ID"] and expires.tzinfo
                 and datetime.now(timezone.utc) < expires)
    except (KeyError, ValueError):
        valid = False
    if not valid:
        raise HTTPException(410, "Laboratory disabled or expired")
    if request.headers.get("origin"):
        raise HTTPException(403, "Browser calls are disabled")


def cpu_work(seconds):
    start, wall = time.process_time(), time.monotonic()
    payload = b"AutoCloud bounded compute probe"*128
    while time.process_time()-start < seconds and time.monotonic()-wall < 4:
        payload = hashlib.sha256(payload).digest()


def actuate(fault):
    global _memory, _memory_until
    now = time.monotonic()
    if now >= _memory_until or fault != "memory_growth":
        _memory = None
    if fault == "memory_growth" and _memory is None:
        # Dedicated minimal image: no XGBoost, pandas, credentials or application data.
        _memory = bytearray(64*1024*1024)
        for i in range(0, len(_memory), 4096):
            _memory[i] = 1
        _memory_until = now+120
    cpu_work(3 if fault == "cpu_stress" else .02)
    if fault == "latency":
        time.sleep(2)
    return {"fault": fault, "allocated_bytes": len(_memory) if _memory is not None else 0}


@app.post("/work")
def work(probe: Probe, request: Request):
    permitted(request, probe.run_id)
    started = datetime.now(timezone.utc).isoformat()
    cpu_start = time.process_time()
    receipt = actuate(probe.fault)
    body = {"run_id": probe.run_id, "sequence": probe.sequence,
            "started_at": started, "finished_at": datetime.now(timezone.utc).isoformat(),
            "cpu_seconds": time.process_time()-cpu_start, **receipt}
    return JSONResponse(body, status_code=503 if probe.fault == "http_503" else 200)

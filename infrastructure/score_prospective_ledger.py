"""Score immutable, pre-outcome forecasts against a later measured snapshot.

Only GCS server creation timestamps establish that forecasts preceded targets.
Reads at most 500 records for one UTC origin day, within a bounded time budget.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import math
from pathlib import Path
from time import monotonic

from google.cloud import storage
import numpy as np
import pandas as pd

from app.data.schema import MetricRecord
from app.models.dataset import TARGETS,HORIZONS
from app.models.resource_predictor import regression_metrics


def eligible_predictions(record, created, actuals, manifest_sha):
    """Do not accept backdated payload clocks, expired predictions or unknown actuals."""
    if record.get("manifest_sha256")!=manifest_sha:
        return []
    if created is None:
        return []
    created=pd.Timestamp(created)
    recorded=pd.Timestamp(record["recorded_at"])
    origin=pd.Timestamp(record["origin"])
    if any(pd.isna(t) or t.tzinfo is None for t in (created,recorded,origin)):
        return []
    results=[]
    for f in record["forecasts"]:
        target=f.get("target"); h=f.get("horizon_minutes"); ts=pd.Timestamp(f["timestamp"])
        if target not in TARGETS or h not in HORIZONS or ts!=origin+pd.Timedelta(minutes=h):
            continue
        if ts<=created or ts<=recorded or origin>recorded or ts not in actuals.index:
            continue
        actual=actuals.loc[ts,target]
        if pd.isna(actual) or not all(isinstance(f.get(k),(int,float)) and not isinstance(f[k],bool) and math.isfinite(f[k]) and f[k]>=0 for k in ("prediction","persistence_prediction")):
            continue
        results.append({"target":target,"horizon_minutes":h,"target_time":ts.isoformat(),
            "gcs_created_at":created.isoformat(),"actual":float(actual),"prediction":f["prediction"],
            "persistence":f["persistence_prediction"]})
    return results


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("study",type=Path);parser.add_argument("--date",required=True,help="UTC origin day YYYYMMDD")
    parser.add_argument("--bucket",default="astute-sign-506809-j8-autocloud-reviews")
    args=parser.parse_args();datetime.strptime(args.date,"%Y%m%d")
    protocol=json.loads((args.study/"protocol.json").read_text());manifest=protocol["model_files_sha256"]["forecast_manifest.json"]
    snapshot=(args.study/"observations.ndjson").read_bytes()
    assert hashlib.sha256(snapshot).hexdigest()==json.loads((args.study/"observations-source.json").read_text())["sha256"]
    rows=[MetricRecord.model_validate_json(l).model_dump() for l in snapshot.decode().splitlines() if l.strip()]
    assert all((r["project_id"],r["region"],r["service_name"])==(protocol["project"],protocol["region"],protocol["service"]) for r in rows)
    actuals=pd.DataFrame(rows).set_index("timestamp");actuals.index=pd.to_datetime(actuals.index,utc=True)
    assert actuals.index.is_unique
    client=storage.Client(project=protocol["project"]);prefix=f"validation-ledger/{manifest}/{args.date}/"
    started=monotonic();scored=[];seen=0;bounded=False
    for blob in client.list_blobs(args.bucket,prefix=prefix,max_results=500,page_size=100,timeout=10,retry=None):
        if monotonic()-started>30:
            bounded=True;break
        seen+=1
        if blob.size>100_000:
            continue
        record=json.loads(blob.download_as_text(if_generation_match=int(blob.generation),timeout=10,retry=None))
        if (record.get("project"),record.get("region"),record.get("service"))!=(protocol["project"],protocol["region"],protocol["service"]):
            continue
        scored.extend(eligible_predictions(record,blob.time_created,actuals,manifest))
    metrics={}
    for key, group in pd.DataFrame(scored).groupby(["target","horizon_minutes"]) if scored else []:
        metrics[f"{key[0]}_{key[1]}m"]={"samples":len(group),
            "candidate":regression_metrics(group["actual"],group["prediction"]),
            "persistence":regression_metrics(group["actual"],group["persistence"])}
    report={"status":"scored" if scored else "no_matured_eligible_predictions", "objects_read":seen,
        "possibly_truncated":bounded or seen>=500,"metrics":metrics,"prediction_pairs":scored,
        "scope":"Prospective records with GCS creation before target time; sample counts and workload coverage limit conclusions."}
    (args.study/"prospective-evaluation.json").write_text(json.dumps(report,indent=2,allow_nan=False))
    print(json.dumps({k:v for k,v in report.items() if k!="prediction_pairs"}),flush=True)


if __name__=="__main__":
    main()

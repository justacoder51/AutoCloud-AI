"""Check actual Streamlit output and anonymous access; never log bearer tokens."""
import json
from pathlib import Path
import sys
import time

import google.auth
from google.auth.transport.requests import Request, AuthorizedSession
from google.protobuf.json_format import MessageToDict
import requests
from streamlit.proto.BackMsg_pb2 import BackMsg
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg
from streamlit.proto.Alert_pb2 import Alert
from websockets.sync.client import connect

URL = "https://autocloud-dashboard-l25hfnltba-el.a.run.app"


def main():
    mode, directory = sys.argv[1], Path(sys.argv[2])
    headers = {}
    if mode == "private":
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        creds.refresh(Request())
        headers = {"Authorization": "Bearer " + creds.id_token}
    response = requests.get(URL + "/", headers=headers, timeout=60)
    assert response.status_code == 200, f"Dashboard HTTP {response.status_code}"
    elements, errors, widgets = [], [], []
    finished = False
    started = time.monotonic()
    with connect(URL.replace("https://", "wss://") + "/_stcore/stream",
                 additional_headers=headers, origin=URL, subprotocols=["streamlit"],
                 open_timeout=45, max_size=16 * 1024 * 1024) as ws:
        back = BackMsg()
        back.rerun_script.query_string = ""
        ws.send(back.SerializeToString())
        while time.monotonic() - started < 150:
            packet = ws.recv(timeout=70)
            forward = ForwardMsg()
            forward.ParseFromString(packet)
            kind = forward.WhichOneof("type")
            if kind == "delta" and forward.delta.WhichOneof("type") == "new_element":
                element = forward.delta.new_element
                which = element.WhichOneof("type")
                # Keep human-readable UI evidence, excluding binary tables and session metadata.
                if which in ("markdown", "text", "heading", "alert", "button", "exception", "metric", "caption", "selectbox", "text_input"):
                    rendered = MessageToDict(element)
                    elements.append(rendered)
                if which == "alert" and element.alert.format == Alert.ERROR:
                    errors.append(element.alert.body)
                if which == "exception":
                    errors.append("Streamlit exception")
                if which in ("button", "selectbox", "text_input", "file_uploader"):
                    widgets.append({"type": which, "label": getattr(getattr(element, which), "label", "")})
            if kind == "script_finished":
                finished = forward.script_finished == ForwardMsg.FINISHED_SUCCESSFULLY
                if finished:
                    break
    text = json.dumps(elements)
    assert finished, "Streamlit run did not finish successfully"
    assert not errors, f"UI contains {len(errors)} errors"
    assert "Public read-only showcase" in text
    assert "Understand the models" in text
    assert "Metrics source: bigquery" in text
    assert sorted((w["type"], w["label"]) for w in widgets) == sorted([("button", "Refresh measurements"), ("button", "Generate Gemini explanations")]), widgets
    assert "What should I check next?" in text
    if "--unlimited" in sys.argv:
        assert "Testing mode: application hourly and daily limits are disabled." in text
        assert "Shared limit: one model attempt" not in text
    result = {"mode": mode, "url": URL, "http_status": response.status_code,
              "streamlit_finished": finished, "errors": errors, "widgets": widgets,
              "positive_public_confirmation": True, "rendered_elements": elements}
    if mode == "public":
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        session = AuthorizedSession(creds)
        root = "https://run.googleapis.com/v2/projects/astute-sign-506809-j8/locations/asia-south1/services/"
        api_iam = session.get(root + "autocloud-api:getIamPolicy", timeout=45)
        api_iam.raise_for_status()
        assert not any(member in ("allUsers", "allAuthenticatedUsers") for b in api_iam.json().get("bindings", []) for member in b.get("members", []))
        result["api_still_private"] = True
        for path in ("/", "/api/overview?source=bigquery&hours=24", "/api/reviews"):
            assert requests.get("https://autocloud-api-l25hfnltba-el.a.run.app" + path, timeout=45).status_code == 403
        result["anonymous_api_denied"] = True
        release = json.loads((directory / "release.json").read_text())
        release["status"] = "deployed_public_and_verified"
        (directory / "release.json").write_text(json.dumps(release, indent=2))
    (directory / f"verification-dashboard-{mode}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "rendered_elements"}), flush=True)


if __name__ == "__main__":
    main()

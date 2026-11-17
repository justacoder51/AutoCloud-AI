"""Exercise the actual public Streamlit button once (one billable Gemini call)."""
import json
from pathlib import Path
import sys
import time

from streamlit.proto.BackMsg_pb2 import BackMsg
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg
from streamlit.proto.Alert_pb2 import Alert
from websockets.sync.client import connect


def main():
    directory = Path(sys.argv[1])
    url = "https://autocloud-dashboard-l25hfnltba-el.a.run.app"
    clicked = False
    button = None
    texts, errors = [], []
    with connect(url.replace("https://", "wss://") + "/_stcore/stream", origin=url,
                 subprotocols=["streamlit"], open_timeout=45, max_size=16*1024*1024) as ws:
        back = BackMsg(); back.rerun_script.query_string = ""
        ws.send(back.SerializeToString())
        started = time.monotonic()
        while time.monotonic()-started < 220:
            forward = ForwardMsg(); forward.ParseFromString(ws.recv(timeout=110))
            kind = forward.WhichOneof("type")
            if kind == "delta" and forward.delta.WhichOneof("type") == "new_element":
                element = forward.delta.new_element; which = element.WhichOneof("type")
                if which == "button" and element.button.label == "Generate Gemini explanations":
                    button = element.button.id
                if clicked and which == "markdown":
                    texts.append(element.markdown.body)
                if clicked and which == "alert" and element.alert.format == Alert.ERROR:
                    errors.append(element.alert.body)
                if which == "exception":
                    errors.append("Streamlit exception")
            if kind == "script_finished" and forward.script_finished == ForwardMsg.FINISHED_SUCCESSFULLY:
                if not clicked:
                    assert button, "Gemini button not found"
                    back = BackMsg(); back.rerun_script.query_string = ""
                    back.rerun_script.widget_states.widgets.add(id=button, trigger_value=True)
                    clicked = True
                    print("Clicked the public Gemini button", flush=True)
                    ws.send(back.SerializeToString())
                else:
                    break
    result = {"passed": clicked and not errors and any("Gemini status: completed" in t for t in texts),
              "anonymous": True, "clicked": clicked, "errors": errors, "rendered_markdown": texts}
    (directory / "verification-gemini-public-ui.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    assert result["passed"], "Public Gemini button did not render completed status; inspect saved evidence"
    print("Public button rendered completed Gemini explanations without login", flush=True)


if __name__ == "__main__":
    main()

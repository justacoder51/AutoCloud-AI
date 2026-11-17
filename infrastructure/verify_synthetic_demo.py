"""Verify anonymous measured/demo switching via real Streamlit WebSocket output.

No Gemini button clicks, workload generation, training, or cloud mutations.
"""
import json
from pathlib import Path
import sys
import time

from streamlit.proto.BackMsg_pb2 import BackMsg
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg
from streamlit.proto.Alert_pb2 import Alert
from websockets.sync.client import connect

URL="https://autocloud-dashboard-l25hfnltba-el.a.run.app"


def receive(ws):
    deadline=time.monotonic()+120
    texts,errors,radios,buttons,types=[],[],[],[],{}
    while time.monotonic()<deadline:
        forward=ForwardMsg();forward.ParseFromString(ws.recv(timeout=70))
        kind=forward.WhichOneof("type")
        if kind=="delta" and forward.delta.WhichOneof("type")=="new_element":
            element=forward.delta.new_element
            which=element.WhichOneof("type")
            types[which]=types.get(which,0)+1
            if which=="markdown":texts.append(element.markdown.body)
            elif which=="heading":texts.append(element.heading.body)
            elif which=="alert":
                texts.append(element.alert.body)
                if element.alert.format==Alert.ERROR:errors.append(element.alert.body)
            elif which=="exception":errors.append("Streamlit exception")
            elif which=="radio":radios.append({"id":element.radio.id,"label":element.radio.label})
            elif which=="button":buttons.append(element.button.label)
        if kind=="script_finished":
            if forward.script_finished==ForwardMsg.FINISHED_SUCCESSFULLY:
                return dict(texts=texts,errors=errors,radios=radios,buttons=buttons,element_types=types)
    raise RuntimeError("Streamlit did not confirm successful completion")


def main():
    folder=Path(sys.argv[1])
    result={"url":URL,"anonymous":True,"passed":False,"gemini_requests":0}
    def save():
        (folder/"verification-synthetic-demo.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    with connect(URL.replace("https://","wss://")+"/_stcore/stream",origin=URL,
            subprotocols=["streamlit"],open_timeout=45,max_size=16*1024*1024) as ws:
        back=BackMsg();back.rerun_script.query_string="";ws.send(back.SerializeToString())
        result["measured_initial"]=initial=receive(ws)
        save()
        assert not initial["errors"]
        assert any("Understand the models" in t for t in initial["texts"])
        radios=[r for r in initial["radios"] if r["label"]=="Data mode"]
        assert len(radios)==1
        widget=radios[0]["id"]
        back=BackMsg();back.rerun_script.query_string=""
        back.rerun_script.widget_states.widgets.add(id=widget,string_value="Synthetic demo")
        ws.send(back.SerializeToString())
        result["synthetic_demo"]=demo=receive(ws)
        save()
        assert not demo["errors"]
        joined="\n".join(demo["texts"])
        assert "SYNTHETIC DEMO" in joined
        assert "not XGBoost predictions" in joined
        assert "not Isolation Forest scores" in joined
        assert "Simulated service: synthetic-example" in joined
        assert demo["element_types"].get("metric",0)==5
        assert sum(demo["element_types"].get(key,0) for key in ("dataframe","arrow_data_frame"))==2
        assert sum(demo["element_types"].get(key,0) for key in ("vega_lite_chart","arrow_vega_lite_chart"))>=10
        assert not demo["buttons"]
        assert "Understand the models" not in joined
        back=BackMsg();back.rerun_script.query_string=""
        back.rerun_script.widget_states.widgets.add(id=widget,string_value="Measured monitoring")
        ws.send(back.SerializeToString())
        result["measured_restored"]=restored=receive(ws)
        save()
        assert not restored["errors"]
        assert any("Understand the models" in t for t in restored["texts"])
        assert not any("SYNTHETIC DEMO" in t for t in restored["texts"])
        result["passed"]=True
    save()
    print("Anonymous measured -> synthetic demo -> measured UI checks passed; no Gemini request made.",flush=True)


if __name__=="__main__":main()

from fastapi import FastAPI, Body
import ezdxf, json, os

app = FastAPI()

@app.post("/generate-dxf")
async def generate_dxf(payload: dict = Body(...)):
    ai_json = payload
    os.makedirs("output_dxf", exist_ok=True)
    filename = f"output_dxf/{ai_json.get('customer','unknown')}_variantA.dxf"

    doc = ezdxf.new('R2010')
    msp = doc.modelspace()

    for act in ai_json.get("actions", []):
        t = act["type"]
        if t == "add_rectangle":
            x1, y1, x2, y2, r = act["x1"], act["y1"], act["x2"], act["y2"], act.get("radius", 0)
            msp.add_lwpolyline([(x1,y1),(x2,y1),(x2,y2),(x1,y2),(x1,y1)])
        elif t == "add_circle":
            msp.add_circle((act["x"], act["y"]), act["r"])
        elif t == "add_text":
            msp.add_text(act["text"], dxfattribs={'height':act.get('height',10)}).set_pos((act["x"], act["y"]))

    doc.saveas(filename)
    return {"status": "ok", "filename": filename}
from fastapi import FastAPI, Body
import ezdxf, json, os

app = FastAPI()

@app.post("/generate-dxf")
async def generate_dxf(payload: dict = Body(...)):
    ai_json = payload
    os.makedirs("output_dxf", exist_ok=True)
    filename = f"output_dxf/{ai_json.get('customer','unknown')}_variantA.dxf"

    doc = ezdxf.new('R2010')
    msp = doc.modelspace()

    for act in ai_json.get("actions", []):
        t = act["type"]
        if t == "add_rectangle":
            x1, y1, x2, y2, r = act["x1"], act["y1"], act["x2"], act["y2"], act.get("radius", 0)
            msp.add_lwpolyline([(x1,y1),(x2,y1),(x2,y2),(x1,y2),(x1,y1)])
        elif t == "add_circle":
            msp.add_circle((act["x"], act["y"]), act["r"])
        elif t == "add_text":
            msp.add_text(act["text"], dxfattribs={'height':act.get('height',10)}).set_pos((act["x"], act["y"]))

    doc.saveas(filename)
    return {"status": "ok", "filename": filename}

from fastapi import FastAPI, Body
import ezdxf
import os
import base64
import math

app = FastAPI()

PATTERN_MAP = {
    "Squares 10x10mm": {"pattern": "square", "hole_size": 10, "spacing": 10, "offset": "half"},
    "Check 10x10mm":   {"pattern": "diamond", "hole_size": 10, "spacing": 10, "offset": "half"},
    "Round hole 10mm": {"pattern": "circle", "hole_diameter": 10, "spacing": 10, "offset": "half"},
    "Slotted hole 35x10mm": {
        "pattern": "slot", "slot_length": 35, "slot_width": 10, "spacing": 10, "offset": "half",
    },
}

MIN_MARGIN = 15.0
MAX_MARGIN = 20.0
TARGET_MARGIN = 17.5


def draw_rounded_rectangle(msp, x, y, w, h, r, layer):
    if r <= 0:
        msp.add_lwpolyline([(x,y),(x+w,y),(x+w,y+h),(x,y+h),(x,y)], dxfattribs={"layer": layer})
        return

    msp.add_line((x+r, y), (x+w-r, y), dxfattribs={"layer": layer})
    msp.add_line((x+w, y+r), (x+w, y+h-r), dxfattribs={"layer": layer})
    msp.add_line((x+w-r, y+h), (x+r, y+h), dxfattribs={"layer": layer})
    msp.add_line((x, y+h-r), (x, y+r), dxfattribs={"layer": layer})

    msp.add_arc((x+w-r, y+r), r, 270, 360, dxfattribs={"layer": layer})
    msp.add_arc((x+w-r, y+h-r), r,   0,  90, dxfattribs={"layer": layer})
    msp.add_arc((x+r,   y+h-r), r,  90, 180, dxfattribs={"layer": layer})
    msp.add_arc((x+r,   y+r),   r, 180, 270, dxfattribs={"layer": layer})


@app.post("/generate_dxf")
async def generate_dxf(payload: dict = Body(...)):

    if isinstance(payload, list):
        payload = payload[0]

    raw = payload.get("pattern", "Squares 10x10mm")
    cfg = PATTERN_MAP[raw]
    pattern = cfg["pattern"]

    customer = str(payload.get("customer","unknown")).replace(" ","_")
    length = float(payload["length"])
    width  = float(payload["width"])
    corner = float(payload.get("corner_radius",0))

    spacing = cfg["spacing"]
    offset_mode = cfg["offset"]

    # ---------- hole + pitch ----------
    if pattern in ("square","diamond"):
        hole_w = hole_h = cfg["hole_size"]
    elif pattern == "circle":
        hole_w = hole_h = cfg["hole_diameter"]
    else:
        hole_w = cfg["slot_length"]
        hole_h = cfg["slot_width"]

    pitch_x = hole_w + spacing
    pitch_y = hole_h + spacing

    # ======================================================
    #  STRICT UNIFORM MARGIN SELECTION (15–20mm SAME ALL SIDES)
    # ======================================================
    best = None
    best_fill = -1

    for m in [x/10 for x in range(int(MIN_MARGIN*10), int(MAX_MARGIN*10)+1)]:
        inner_w = length - 2*m
        inner_h = width  - 2*m

        if inner_w <= hole_w or inner_h <= hole_h:
            continue

        cols = math.floor((inner_w - hole_w)/pitch_x) + 1
        rows = math.floor((inner_h - hole_h)/pitch_y) + 1

        if cols < 1 or rows < 1:
            continue

        fill = cols * rows
        err  = abs(m - TARGET_MARGIN)

        if fill > best_fill or (fill == best_fill and err < best[0]):
            best = (err, m, cols, rows)
            best_fill = fill

    if best is None:
        raise ValueError("No pattern fits with 15–20mm margin")

    _, margin, cols, rows = best

    # -------- Final footprint ----------
    pattern_w = hole_w + (cols-1)*pitch_x
    pattern_h = hole_h + (rows-1)*pitch_y

    x_start = (length - pattern_w)/2
    y_start = (width  - pattern_h)/2

    # ======================================================
    #  DXF SETUP
    # ======================================================
    os.makedirs("output_dxf", exist_ok=True)
    filename = f"output_dxf/{customer}_{pattern}.dxf"

    doc = ezdxf.new("R2010")
    doc.units = ezdxf.units.MM
    msp = doc.modelspace()

    doc.layers.new(name="OUTLINE")
    doc.layers.new(name="PATTERN")

    draw_rounded_rectangle(msp,0,0,length,width,corner,"OUTLINE")

    # ======================================================
    #  PATTERN — OFFSET ONLY INNER ROWS
    # ======================================================
    y = y_start

    for r in range(rows):

        # ONLY shift rows 2..rows-1
        ox = 0
        if offset_mode == "half" and 0 < r < rows-1 and (r % 2 == 1):
            ox = pitch_x / 2

        x = x_start + ox

        for c in range(cols):

            if pattern == "square":
                msp.add_lwpolyline(
                    [(x,y),(x+hole_w,y),(x+hole_w,y+hole_h),(x,y+hole_h),(x,y)],
                    dxfattribs={"layer":"PATTERN"}
                )

            elif pattern == "diamond":
                cx, cy = x + hole_w/2, y + hole_h/2
                msp.add_lwpolyline(
                    [(cx,y),(x+hole_w,cy),(cx,y+hole_h),(x,cy),(cx,y)],
                    dxfattribs={"layer":"PATTERN"}
                )

            elif pattern == "circle":
                msp.add_circle((x+hole_w/2,y+hole_h/2), hole_w/2,
                               dxfattribs={"layer":"PATTERN"})

            else:  # slot
                r0 = hole_h/2
                msp.add_line((x+r0,y+r0),(x+hole_w-r0,y+r0),dxfattribs={"layer":"PATTERN"})
                msp.add_arc((x+r0,y+r0),r0,90,270,dxfattribs={"layer":"PATTERN"})
                msp.add_arc((x+hole_w-r0,y+r0),r0,-90,90,dxfattribs={"layer":"PATTERN"})

            x += pitch_x

        y += pitch_y

    doc.set_modelspace_vport(center=(length/2,width/2),height=width*1.1)
    doc.saveas(filename)

    with open(filename,"rb") as f:
        data = base64.b64encode(f.read()).decode()

    return {
        "status":"ok",
        "file_name":os.path.basename(filename),
        "file_base64":data,
        "margin_mm":round(margin,2),
        "cols":cols,
        "rows":rows
    }

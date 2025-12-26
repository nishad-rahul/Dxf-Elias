from fastapi import FastAPI, Body
import ezdxf
import os
import base64
import math   # ⬅️ ADDED

app = FastAPI()

# =========================================================
# Pattern normalization (matches n8n input)
# =========================================================
PATTERN_MAP = {
    "Squares 10x10mm": {
        "pattern": "square",
        "hole_size": 10,
        "spacing": 10,
        "offset": "half",
    },
    "Check 10x10mm": {
        "pattern": "diamond",
        "hole_size": 10,
        "spacing": 10,
        "offset": "half",
    },
    "Round hole 10mm": {
        "pattern": "circle",
        "hole_diameter": 10,
        "spacing": 10,
        "offset": "half",
    },
    "Slotted hole 35x10mm": {
        "pattern": "slot",
        "slot_length": 35,
        "slot_width": 10,
        "spacing": 10,
        "offset": "half",
    },
}

# =========================================================
# Helper: Rounded rectangle using LINES + ARCS (SAFE)
# =========================================================
def draw_rounded_rectangle(msp, x, y, w, h, r, layer):
    if r <= 0:
        msp.add_lwpolyline(
            [(x,y),(x+w,y),(x+w,y+h),(x,y+h),(x,y)],
            dxfattribs={"layer": layer}
        )
        return

    # Lines
    msp.add_line((x+r, y), (x+w-r, y), dxfattribs={"layer": layer})
    msp.add_line((x+w, y+r), (x+w, y+h-r), dxfattribs={"layer": layer})
    msp.add_line((x+w-r, y+h), (x+r, y+h), dxfattribs={"layer": layer})
    msp.add_line((x, y+h-r), (x, y+r), dxfattribs={"layer": layer})

    # Arcs (AutoCAD degrees)
    msp.add_arc((x+w-r, y+r), r, 270, 360, dxfattribs={"layer": layer})
    msp.add_arc((x+w-r, y+h-r), r, 0, 90, dxfattribs={"layer": layer})
    msp.add_arc((x+r, y+h-r), r, 90, 180, dxfattribs={"layer": layer})
    msp.add_arc((x+r, y+r), r, 180, 270, dxfattribs={"layer": layer})

# =========================================================
# DXF Generator Endpoint
# =========================================================
@app.post("/generate_dxf")
async def generate_dxf(payload: dict = Body(...)):

    # Handle n8n array input
    if isinstance(payload, list):
        payload = payload[0]

    raw_pattern = payload.get("pattern", "Squares 10x10mm")
    cfg = PATTERN_MAP[raw_pattern]
    pattern = cfg["pattern"]

    customer = str(payload.get("customer", "unknown")).replace(" ", "_")
    length = float(payload.get("length", 500))
    width = float(payload.get("width", 300))
    border = float(payload.get("border", 17))
    corner_radius = float(payload.get("corner_radius", 0))

    spacing = cfg["spacing"]
    offset_mode = cfg["offset"]

    hole_size = cfg.get("hole_size", 10)
    hole_diameter = cfg.get("hole_diameter", 10)
    slot_length = cfg.get("slot_length", 35)
    slot_width = cfg.get("slot_width", 10)

    os.makedirs("output_dxf", exist_ok=True)
    filename = f"output_dxf/{customer}_{pattern}.dxf"

    doc = ezdxf.new("R2010")
    doc.units = ezdxf.units.MM
    msp = doc.modelspace()

    doc.layers.new(name="OUTLINE")
    doc.layers.new(name="PATTERN")

    # Outline
    draw_rounded_rectangle(
        msp,
        x=0,
        y=0,
        w=length,
        h=width,
        r=corner_radius,
        layer="OUTLINE"
    )

    # ============================
    # Pattern usable bounds
    # ============================
    px1, py1 = border, border
    px2, py2 = length - border, width - border

    inner_w = px2 - px1
    inner_h = py2 - py1

    # ============================
    # Determine hole size + pitch
    # ============================
    if pattern in ("square", "diamond"):
        hole_w = hole_h = hole_size
        pitch_x = hole_size + spacing
        pitch_y = hole_size + spacing

    elif pattern == "circle":
        hole_w = hole_h = hole_diameter
        pitch_x = hole_diameter + spacing
        pitch_y = hole_diameter + spacing

    elif pattern == "slot":
        hole_w = slot_length
        hole_h = slot_width
        pitch_x = slot_length + spacing
        pitch_y = slot_width + spacing

    # ============================
    # How many *actually fit*
    # ============================
    cols = max(1, math.floor((inner_w - hole_w) / pitch_x) + 1)
    rows = max(1, math.floor((inner_h - hole_h) / pitch_y) + 1)

    # ============================
    # Real pattern footprint
    # ============================
    pattern_w = hole_w + (cols - 1) * pitch_x
    pattern_h = hole_h + (rows - 1) * pitch_y

    # ============================
    # Center pattern (key fix)
    # ============================
    extra_x = inner_w - pattern_w
    extra_y = inner_h - pattern_h

    x_start = px1 + extra_x / 2
    y_start = py1 + extra_y / 2

    # ============================
    # Pattern generation
    # ============================
    y = y_start
    row = 0

    while row < rows:
        offset_x = hole_size / 2 if offset_mode == "half" and row % 2 else 0
        x = x_start + offset_x
        col = 0

        while col < cols:

            if pattern == "square":
                s = hole_size
                msp.add_lwpolyline(
                    [(x,y),(x+s,y),(x+s,y+s),(x,y+s),(x,y)],
                    dxfattribs={"layer":"PATTERN"}
                )

            elif pattern == "diamond":
                s = hole_size
                cx, cy = x + s/2, y + s/2
                msp.add_lwpolyline(
                    [(cx,y),(x+s,cy),(cx,y+s),(x,cy),(cx,y)],
                    dxfattribs={"layer":"PATTERN"}
                )

            elif pattern == "circle":
                d = hole_diameter
                r = d / 2
                msp.add_circle((x+r,y+r), r, dxfattribs={"layer":"PATTERN"})

            elif pattern == "slot":
                hl, hw = slot_length, slot_width
                r = hw / 2
                msp.add_line((x+r,y+r),(x+hl-r,y+r), dxfattribs={"layer":"PATTERN"})
                msp.add_arc((x+r,y+r), r, 90, 270, dxfattribs={"layer":"PATTERN"})
                msp.add_arc((x+hl-r,y+r), r, -90, 90, dxfattribs={"layer":"PATTERN"})

            x += pitch_x
            col += 1

        y += pitch_y
        row += 1

    doc.set_modelspace_vport(
        center=(length/2, width/2),
        height=width * 1.1
    )

    doc.saveas(filename)

    with open(filename, "rb") as f:
        encoded = base64.b64encode(f.read()).decode()

    return {
        "status": "ok",
        "file_name": os.path.basename(filename),
        "file_base64": encoded
    }

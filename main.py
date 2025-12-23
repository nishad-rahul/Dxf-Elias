from fastapi import FastAPI, Body
import ezdxf
import os
import base64
import math

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

    # Arcs (angles are AutoCAD degrees)
    msp.add_arc((x+w-r, y+r), r, 270, 360, dxfattribs={"layer": layer})
    msp.add_arc((x+w-r, y+h-r), r, 0, 90, dxfattribs={"layer": layer})
    msp.add_arc((x+r, y+h-r), r, 90, 180, dxfattribs={"layer": layer})
    msp.add_arc((x+r, y+r), r, 180, 270, dxfattribs={"layer": layer})

# =========================================================
# DXF Generator Endpoint
# =========================================================
@app.post("/generate_dxf")
async def generate_dxf(payload: dict = Body(...)):
    try:
        # -------------------------------------------------
        # Handle n8n array input
        # -------------------------------------------------
        if isinstance(payload, list):
            payload = payload[0]

        # -------------------------------------------------
        # Normalize pattern
        # -------------------------------------------------
        raw_pattern = payload.get("pattern", "Squares 10x10mm")
        if raw_pattern not in PATTERN_MAP:
            return {"error": f"Unsupported pattern: {raw_pattern}"}

        cfg = PATTERN_MAP[raw_pattern]
        pattern = cfg["pattern"]

        # -------------------------------------------------
        # Dynamic inputs
        # -------------------------------------------------
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

        # -------------------------------------------------
        # File setup
        # -------------------------------------------------
        os.makedirs("output_dxf", exist_ok=True)
        filename = f"output_dxf/{customer}_{pattern}.dxf"

        doc = ezdxf.new("R2010")
        doc.units = ezdxf.units.MM
        msp = doc.modelspace()

        doc.layers.new(name="OUTLINE")
        doc.layers.new(name="PATTERN")

        # -------------------------------------------------
        # Outline
        # -------------------------------------------------
        draw_rounded_rectangle(
            msp,
            x=0,
            y=0,
            w=length,
            h=width,
            r=corner_radius,
            layer="OUTLINE"
        )

        # -------------------------------------------------
        # Pattern bounds
        # -------------------------------------------------
        px1, py1 = border, border
        px2, py2 = length - border, width - border

        y = py1
        row = 0

        # -------------------------------------------------
        # Pattern generation (ABSOLUTE SAFE)
        # -------------------------------------------------
        while y < py2:
            offset_x = hole_size / 2 if offset_mode == "half" and row % 2 else 0
            x = px1 + offset_x

            while x < px2:

                if pattern == "square":
                    s = hole_size
                    if x + s <= px2 and y + s <= py2:
                        msp.add_lwpolyline(
                            [(x,y),(x+s,y),(x+s,y+s),(x,y+s),(x,y)],
                            dxfattribs={"layer":"PATTERN"}
                        )
                    step_x, step_y = s, s

                elif pattern == "diamond":
                    s = hole_size
                    cx, cy = x + s/2, y + s/2
                    if x + s <= px2 and y + s <= py2:
                        msp.add_lwpolyline(
                            [(cx,y),(x+s,cy),(cx,y+s),(x,cy),(cx,y)],
                            dxfattribs={"layer":"PATTERN"}
                        )
                    step_x, step_y = s, s

                elif pattern == "circle":
                    d = hole_diameter
                    r = d / 2
                    if x + d <= px2 and y + d <= py2:
                        msp.add_circle((x+r,y+r), r, dxfattribs={"layer":"PATTERN"})
                    step_x, step_y = d, d

                elif pattern == "slot":
                    hl, hw = slot_length, slot_width
                    r = hw / 2
                    if x + hl <= px2 and y + hw <= py2:
                        msp.add_line((x+r,y+r),(x+hl-r,y+r), dxfattribs={"layer":"PATTERN"})
                        msp.add_arc((x+r,y+r), r, 90, 270, dxfattribs={"layer":"PATTERN"})

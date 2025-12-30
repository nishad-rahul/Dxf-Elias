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
        "pattern": "slot", "slot_length": 35, "slot_width": 10, "spacing": 10, "offset": "half"
    },
}

MIN_MARGIN = 15.0
MAX_MARGIN = 20.0
TARGET_MARGIN = (MIN_MARGIN + MAX_MARGIN) / 2.0  # 17.5mm mid-target

def draw_rounded_rectangle(msp, x, y, w, h, r, layer):
    if r <= 0:
        msp.add_lwpolyline([(x,y),(x+w,y),(x+w,y+h),(x,y+h),(x,y)], dxfattribs={"layer": layer})
        return

    msp.add_line((x+r, y), (x+w-r, y), dxfattribs={"layer": layer})
    msp.add_line((x+w, y+r), (x+w, y+h-r), dxfattribs={"layer": layer})
    msp.add_line((x+w-r, y+h), (x+r, y+h), dxfattribs={"layer": layer})
    msp.add_line((x, y+h-r), (x, y+r), dxfattribs={"layer": layer})

    msp.add_arc((x+w-r, y+r), r, 270, 360, dxfattribs={"layer": layer})
    msp.add_arc((x+w-r, y+h-r), r, 0, 90, dxfattribs={"layer": layer})
    msp.add_arc((x+r, y+h-r), r, 90, 180, dxfattribs={"layer": layer})
    msp.add_arc((x+r, y+r), r, 180, 270, dxfattribs={"layer": layer})


def choose_fit(panel_size, hole, pitch):
    """
    Returns:
    - count of holes
    - starting offset (margin) so that 15–20mm condition is satisfied
    """

    best_choice = None
    best_error = 1e9

    # iterate feasible counts
    max_count = max(1, math.floor((panel_size - hole) / pitch) + 1)

    for n in range(1, max_count + 1):
        pattern = hole + (n - 1) * pitch
        margin = (panel_size - pattern) / 2.0

        if margin < MIN_MARGIN:
            continue  # too tight

        # perfect window hit
        if MIN_MARGIN <= margin <= MAX_MARGIN:
            err = abs(margin - TARGET_MARGIN)
            if err < best_error:
                best_error = err
                best_choice = (n, margin)

        # store fallback ≥ 15mm if nothing lands ≤ 20mm
        elif best_choice is None and margin > MAX_MARGIN:
            err = margin - TARGET_MARGIN
            if err < best_error:
                best_error = err
                best_choice = (n, margin)

    # guaranteed at least something
    if best_choice is None:
        n = max_count
        pattern = hole + (n - 1) * pitch
        margin = max(MIN_MARGIN, (panel_size - pattern) / 2.0)
        return n, margin

    return best_choice


@app.post("/generate_dxf")
async def generate_dxf(payload: dict = Body(...)):

    if isinstance(payload, list):
        payload = payload[0]

    raw_pattern = payload.get("pattern", "Squares 10x10mm")
    cfg = PATTERN_MAP[raw_pattern]
    pattern = cfg["pattern"]

    customer = str(payload.get("customer", "unknown")).replace(" ", "_")
    length = float(payload.get("length"))
    width = float(payload.get("width"))
    corner_radius = float(payload.get("corner_radius", 0))

    spacing = cfg["spacing"]
    offset_mode = cfg["offset"]

    # hole definitions
    if pattern in ("square", "diamond"):
        hole_w = hole_h = cfg["hole_size"]
        pitch_x = pitch_y = cfg["hole_size"] + spacing

    elif pattern == "circle":
        hole_w = hole_h = cfg["hole_diameter"]
        pitch_x = pitch_y = cfg["hole_diameter"] + spacing

    elif pattern == "slot":
        hole_w = cfg["slot_length"]
        hole_h = cfg["slot_width"]
        pitch_x = cfg["slot_length"] + spacing
        pitch_y = cfg["slot_width"] + spacing

    # ---------- enforce 15–20mm margins ----------
    cols, margin_x = choose_fit(length, hole_w, pitch_x)
    rows, margin_y = choose_fit(width,  hole_h, pitch_y)

    x_start = margin_x
    y_start = margin_y

    os.makedirs("output_dxf", exist_ok=True)
    filename = f"output_dxf/{customer}_{pattern}.dxf"

    doc = ezdxf.new("R2010")
    doc.units = ezdxf.units.MM
    msp = doc.modelspace()

    doc.layers.new(name="OUTLINE")
    doc.layers.new(name="PATTERN")

    draw_rounded_rectangle(msp, 0, 0, length, width, corner_radius, "OUTLINE")

    # -------- pattern generation ----------
    y = y_start
    row = 0

    while row < rows:

        offset_x = 0
        if offset_mode == "half" and row % 2:
            offset_x = (pitch_x - hole_w) / 2.0

        x = x_start + offset_x
        col = 0

        while col < cols:

            if pattern == "square":
                s = hole_w
                msp.add_lwpolyline(
                    [(x,y),(x+s,y),(x+s,y+s),(x,y+s),(x,y)],
                    dxfattribs={"layer":"PATTERN"}
                )

            elif pattern == "diamond":
                s = hole_w
                cx, cy = x + s/2, y + s/2
                msp.add_lwpolyline(
                    [(cx,y),(x+s,cy),(cx,y+s),(x,cy),(cx,y)],
                    dxfattribs={"layer":"PATTERN"}
                )

            elif pattern == "circle":
                r = hole_w/2
                msp.add_circle((x+r,y+r), r, dxfattribs={"layer":"PATTERN"})

            elif pattern == "slot":
                hl, hw = hole_w, hole_h
                r = hw/2
                msp.add_line((x+r,y+r),(x+hl-r,y+r), dxfattribs={"layer":"PATTERN"})
                msp.add_arc((x+r,y+r), r, 90, 270, dxfattribs={"layer":"PATTERN"})
                msp.add_arc((x+hl-r,y+r), r, -90, 90, dxfattribs={"layer":"PATTERN"})

            x += pitch_x
            col += 1

        y += pitch_y
        row += 1

    doc.set_modelspace_vport(center=(length/2, width/2), height=width*1.1)
    doc.saveas(filename)

    with open(filename, "rb") as f:
        encoded = base64.b64encode(f.read()).decode()

    return {
        "status": "ok",
        "file_name": os.path.basename(filename),
        "file_base64": encoded,
        "margin_x_mm": round(margin_x, 2),
        "margin_y_mm": round(margin_y, 2),
    }

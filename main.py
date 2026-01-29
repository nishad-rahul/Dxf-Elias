from fastapi import FastAPI, Body
import ezdxf
import os
import base64
import math

app = FastAPI()

# =========================================================
# Pattern Configuration
# =========================================================
PATTERN_MAP = {
    "Squares 10x10mm": {"pattern": "square", "hole_size": 10, "spacing": 10, "offset": "half"},
    "Squares Grouped": {
        "pattern": "square", "hole_size": 10, "spacing": 10, "offset": "none",
        "grouping": {"col_count": 8, "gap_size": 70.0}
    },
    "Check 10x10mm": {"pattern": "diamond", "hole_size": 10, "spacing": 5.1, "offset": "half"},
    "Round hole 10mm": {"pattern": "circle", "hole_diameter": 10, "spacing": 10, "offset": "half"},
    "Slotted hole 35x10mm": {
        "pattern": "slot",
        "slot_length": 40.0,
        "slot_width": 8.5,
        "spacing": 8.5,
        "offset": "none"
    },
}

# =========================================================
# Strict Edge-Safe Optimizer
# =========================================================
def solve_axis(available, item, pitch, min_edge=18.0, max_edge=27.0):
    best = None
    for count in range(1, 1000):
        used = item + (count - 1) * pitch
        margin = (available - used) / 2
        if margin < min_edge:
            break
        if min_edge <= margin <= max_edge:
            best = (count, margin)
    return best

# =========================================================
# Layout Logic (SLOT = IMAGE ACCURATE)
# =========================================================
def calculate_layout_params(sheet_length, sheet_width, pattern_type):
    if pattern_type != "slot":
        raise ValueError("This layout solver is ONLY for slot holes")

    SLOT_L = 40.0
    SLOT_H = 8.5
    GAP_X = 8.5
    PITCH_Y = 25.0

    pitch_x = SLOT_L + GAP_X

    x_solution = solve_axis(sheet_length, SLOT_L, pitch_x)
    y_solution = solve_axis(sheet_width, SLOT_H, PITCH_Y)

    if not x_solution or not y_solution:
        raise ValueError("No valid layout respecting 18–27mm edge rule")

    count_x, margin_x = x_solution
    count_y, margin_y = y_solution

    return {
        "count_x": count_x,
        "count_y": count_y,
        "pitch_x": pitch_x,
        "pitch_y": PITCH_Y,
        "margin_x": margin_x,
        "margin_y": margin_y
    }

# =========================================================
# DXF Generator
# =========================================================
@app.post("/generate_dxf")
async def generate_dxf(payload: dict = Body(...)):
    if isinstance(payload, list):
        payload = payload[0]

    raw_pattern = payload.get("pattern", "Squares 10x10mm")
    cfg = PATTERN_MAP.get(raw_pattern)
    pattern = cfg["pattern"]

    customer = str(payload.get("customer", "Standard")).replace(" ", "_")
    length = float(payload.get("length", 1000))
    width = float(payload.get("width", 500))
    bent_top = payload.get("bent_top", False)

    final_width = width + 5.1 if bent_top else width

    os.makedirs("output_dxf", exist_ok=True)
    filename = f"output_dxf/{customer}_{int(length)}x{int(final_width)}.dxf"

    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    doc.layers.new(name="OUTLINE")
    doc.layers.new(name="PATTERN")

    # Outline
    msp.add_lwpolyline([
        (0, 0), (length, 0), (length, final_width),
        (0, final_width), (0, 0)
    ], dxfattribs={"layer": "OUTLINE"})

    # SLOT ONLY
    if pattern == "slot":
        layout = calculate_layout_params(length, width, "slot")
        hole_w = 40.0
        hole_h = 8.5
        r = hole_h / 2

        y = layout["margin_y"]
        for row in range(layout["count_y"]):
            x = layout["margin_x"]
            for col in range(layout["count_x"]):
                # slot body
                msp.add_line((x + r, y), (x + hole_w - r, y), dxfattribs={"layer": "PATTERN"})
                msp.add_line((x + r, y + hole_h), (x + hole_w - r, y + hole_h), dxfattribs={"layer": "PATTERN"})
                msp.add_arc((x + r, y + r), r, 90, 270, dxfattribs={"layer": "PATTERN"})
                msp.add_arc((x + hole_w - r, y + r), r, 270, 90, dxfattribs={"layer": "PATTERN"})

                x += layout["pitch_x"]
            y += layout["pitch_y"]

    doc.saveas(filename)

    with open(filename, "rb") as f:
        return {
            "status": "ok",
            "file_name": os.path.basename(filename),
            "file_base64": base64.b64encode(f.read()).decode()
        }

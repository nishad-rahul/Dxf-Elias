from fastapi import FastAPI, Body
import ezdxf
import os
import base64
import math

app = FastAPI()

# =========================================================
# Pattern Configuration (No Changes to Others)
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
        "offset": "half"
    },
}

def get_optimized_params(available, item, pitch, stagger=0):
    best_c = 1
    best_margin = 0
    for c in range(1, 1000):
        visual_w = item + ((c - 1) * pitch) + stagger
        margin = (available - visual_w) / 2
        if margin < 18.0:
            break
        best_c = c
        best_margin = margin
    return best_c, best_margin

# =========================================================
# Layout Logic (Fixed Longhole Dead Zone)
# =========================================================
def calculate_layout_params(sheet_length, sheet_width, item_size, spacing, pattern_type, grouping=None):
    if pattern_type == "slot":
        # 🆕 DYNAMIC SPACING: Search 8.5mm to 12mm to find the perfect border
        for s in [x * 0.1 for x in range(85, 121)]: 
            p_x = 40.0 + s
            p_y = 25.0
            stagger = p_x / 2
            c_x, m_x = get_optimized_params(sheet_length, 40.0, p_x, stagger)
            if 18.0 <= m_x <= 27.0:
                c_y, m_y = get_optimized_params(sheet_width, 8.5, p_y)
                return {
                    "is_grouped": False, "count_x": c_x, "count_y": c_y,
                    "pitch_x": p_x, "pitch_y": p_y, "margin_x": m_x, "margin_y": m_y
                }
        p_x, p_y, stagger_x, bounding_size, item_h = 48.5, 25.0, 24.25, 40.0, 8.5
    elif pattern_type == "diamond":
        pitch_x = (item_size + spacing) * math.sqrt(2)
        pitch_y, stagger_x, bounding_size, item_h = pitch_x / 2, pitch_x / 2, item_size * math.sqrt(2), item_size * math.sqrt(2)
    else:
        pitch_x = item_size + spacing
        pitch_y, stagger_x, bounding_size, item_h = pitch_x, pitch_x / 2, item_size, item_size

    count_x, margin_x = get_optimized_params(sheet_length, bounding_size, pitch_x, stagger_x)
    count_y, margin_y = get_optimized_params(sheet_width, item_h, pitch_y)

    return {"is_grouped": False, "count_x": count_x, "count_y": count_y, "pitch_x": pitch_x, "pitch_y": pitch_y, "margin_x": margin_x, "margin_y": margin_y}

@app.post("/generate_dxf")
async def generate_dxf(payload: dict = Body(...)):
    if isinstance(payload, list): payload = payload[0]
    raw_pattern = payload.get("pattern", "Squares 10x10mm")
    cfg = PATTERN_MAP.get(raw_pattern, PATTERN_MAP["Squares 10x10mm"])
    pattern = cfg["pattern"]

    customer = str(payload.get("customer", "Standard")).replace(" ", "_")
    length, width = float(payload.get("length", 1000)), float(payload.get("width", 500))
    bent_top = payload.get("bent_top", False)
    
    hole_w = 40.0 if pattern == "slot" else cfg.get("hole_size", 10)
    hole_h = 8.5 if pattern == "slot" else hole_w

    layout = calculate_layout_params(length, width, hole_w, cfg["spacing"], pattern, cfg.get("grouping"))
    final_width = width + 5.1 if bent_top else width

    os.makedirs("output_dxf", exist_ok=True)
    filename = f"output_dxf/{customer}_{int(length)}x{final_width}.dxf"
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    doc.layers.new(name="OUTLINE")
    doc.layers.new(name="PATTERN")

    msp.add_lwpolyline([(0,0), (length,0), (length, final_width), (0, final_width), (0,0)], dxfattribs={"layer": "OUTLINE"})

    y = layout["margin_y"]
    for row in range(layout["count_y"]):
        row_off = (layout["pitch_x"] / 2) if cfg["offset"] == "half" and row % 2 != 0 else 0
        x_start = layout["margin_x"] + row_off
        for c in range(layout["count_x"]):
            x = x_start + (c * layout["pitch_x"])
            if x + hole_w > length - 17.0: continue
            
            if pattern == "square":
                msp.add_lwpolyline([(x,y),(x+hole_w,y),(x+hole_w,y+hole_h),(x,y+hole_h),(x,y)], dxfattribs={"layer":"PATTERN"})
            elif pattern == "slot":
                r = hole_h / 2
                msp.add_line((x+r, y), (x+hole_w-r, y), dxfattribs={"layer":"PATTERN"})
                msp.add_line((x+r, y+hole_h), (x+hole_w-r, y+hole_h), dxfattribs={"layer":"PATTERN"})
                msp.add_arc((x+r, y+r), r, 90, 270, dxfattribs={"layer":"PATTERN"})
                msp.add_arc((x+hole_w-r, y+r), r, 270, 90, dxfattribs={"layer":"PATTERN"})
            elif pattern == "diamond":
                cx, cy = x + hole_w/2, y + hole_h/2
                msp.add_lwpolyline([(cx, y), (x+hole_w, cy), (cx, y+hole_h), (x, cy), (cx, y)], dxfattribs={"layer":"PATTERN"})
            elif pattern == "circle":
                r = hole_w / 2
                msp.add_circle((x+r, y+r), r, dxfattribs={"layer":"PATTERN"})
        y += layout["pitch_y"]

    doc.saveas(filename)
    with open(filename, "rb") as f:
        return {"status": "ok", "file_name": os.path.basename(filename), "file_base64": base64.b64encode(f.read()).decode()}

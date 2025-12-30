from fastapi import FastAPI, Body
import ezdxf
import os
import base64
import math

app = FastAPI()

# =========================================================
# Pattern Configuration (Matches Variant A Documentation)
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
# Helper: Rounded rectangle
# =========================================================
def draw_rounded_rectangle(msp, x, y, w, h, r, layer):
    if r <= 0:
        msp.add_lwpolyline(
            [(x,y),(x+w,y),(x+w,y+h),(x,y+h),(x,y)],
            dxfattribs={"layer": layer}
        )
        return
    
    # Draw straight lines
    msp.add_line((x+r, y), (x+w-r, y), dxfattribs={"layer": layer})
    msp.add_line((x+w, y+r), (x+w, y+h-r), dxfattribs={"layer": layer})
    msp.add_line((x+w-r, y+h), (x+r, y+h), dxfattribs={"layer": layer})
    msp.add_line((x, y+h-r), (x, y+r), dxfattribs={"layer": layer})
    
    # Draw corner arcs
    msp.add_arc((x+w-r, y+r), r, 270, 360, dxfattribs={"layer": layer})
    msp.add_arc((x+w-r, y+h-r), r, 0, 90, dxfattribs={"layer": layer})
    msp.add_arc((x+r, y+h-r), r, 90, 180, dxfattribs={"layer": layer})
    msp.add_arc((x+r, y+r), r, 180, 270, dxfattribs={"layer": layer})

# =========================================================
# CORE LOGIC: Dynamic Spacing Calculation
# =========================================================
def calculate_perfect_fit(sheet_size, hole_size, min_spacing):
    """
    Ensures margin is strictly >= 17mm and symmetrical.
    """
    # ⚠️ UPDATED: Strictly enforces >= 17mm per Variant A docs
    TARGET_MIN_MARGIN = 17.0 
    
    # 1. Determine usable space inside the margins
    # We strip 17mm from top and bottom (total 34mm)
    usable_space = sheet_size - (2 * TARGET_MIN_MARGIN)
    
    # 2. Minimum pitch (hole + min gap)
    min_pitch = hole_size + min_spacing
    
    # 3. How many holes fit?
    if usable_space < hole_size:
        # If the sheet is too small, return 0 holes and center the emptiness
        return 0, 0, sheet_size / 2

    # Math.floor ensures we never exceed the usable space.
    # This guarantees the remaining space (margin) is >= 17mm.
    count = math.floor((usable_space - hole_size) / min_pitch) + 1
    
    if count <= 1:
        return 1, 0, (sheet_size - hole_size) / 2

    # 4. Stretch the pitch to fill the space evenly
    # This ensures the "leftover" margin is distributed exactly evenly
    ideal_pitch = (usable_space - hole_size) / (count - 1)
    
    # 5. Calculate final exact margin
    final_pattern_size = hole_size + (count - 1) * ideal_pitch
    margin = (sheet_size - final_pattern_size) / 2
    
    return count, ideal_pitch, margin

# =========================================================
# DXF Generator Endpoint
# =========================================================
@app.post("/generate_dxf")
async def generate_dxf(payload: dict = Body(...)):
    if isinstance(payload, list):
        payload = payload[0]

    raw_pattern = payload.get("pattern", "Squares 10x10mm")
    cfg = PATTERN_MAP.get(raw_pattern, PATTERN_MAP["Squares 10x10mm"])
    pattern = cfg["pattern"]

    customer = str(payload.get("customer", "Variant_A")).replace(" ", "_")
    length = float(payload.get("length", 500))
    width = float(payload.get("width", 300))
    
    # ⚠️ UPDATED: Default is now 5mm per documentation
    corner_radius = float(payload.get("corner_radius", 5)) 

    min_spacing = cfg["spacing"]
    offset_mode = cfg["offset"]

    # ============================
    # 1. Determine Hole Size
    # ============================
    hole_w, hole_h = 10, 10 # Fallback

    if pattern in ("square", "diamond"):
        s = cfg.get("hole_size", 10)
        hole_w, hole_h = s, s
    elif pattern == "circle":
        d = cfg.get("hole_diameter", 10)
        hole_w, hole_h = d, d
    elif pattern == "slot":
        hole_w = cfg.get("slot_length", 35)
        hole_h = cfg.get("slot_width", 10)

    # ============================
    # 2. Calculate Layout
    # ============================
    cols, pitch_x, margin_x = calculate_perfect_fit(length, hole_w, min_spacing)
    rows, pitch_y, margin_y = calculate_perfect_fit(width, hole_h, min_spacing)

    # ============================
    # 3. Setup DXF
    # ============================
    os.makedirs("output_dxf", exist_ok=True)
    filename = f"output_dxf/{customer}_{pattern}.dxf"
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    doc.layers.new(name="OUTLINE")
    doc.layers.new(name="PATTERN")

    # Draw Outline (Size is exact length x width)
    draw_rounded_rectangle(msp, 0, 0, length, width, corner_radius, "OUTLINE")

    # ============================
    # 4. Draw Pattern
    # ============================
    y = margin_y
    row = 0

    while row < rows:
        # Offset Logic
        current_offset = 0
        if offset_mode == "half" and row % 2 != 0:
            current_offset = pitch_x / 2
        
        x = margin_x + current_offset
        col = 0

        while col < cols:
            # Check bounds (right edge)
            if x + hole_w > length - 10: 
                col += 1
                continue

            # Draw shapes
            if pattern == "square":
                msp.add_lwpolyline(
                    [(x,y), (x+hole_w,y), (x+hole_w,y+hole_h), (x,y+hole_h), (x,y)],
                    dxfattribs={"layer":"PATTERN"}
                )
            elif pattern == "diamond":
                cx, cy = x + hole_w/2, y + hole_h/2
                msp.add_lwpolyline(
                    [(cx,y), (x+hole_w,cy), (cx,y+hole_h), (x,cy), (cx,y)],
                    dxfattribs={"layer":"PATTERN"}
                )
            elif pattern == "circle":
                r = hole_w / 2
                msp.add_circle((x+r, y+r), r, dxfattribs={"layer":"PATTERN"})
            elif pattern == "slot":
                r = hole_h / 2
                msp.add_line((x+r,y+r), (x+hole_w-r,y+r), dxfattribs={"layer":"PATTERN"})
                msp.add_arc((x+r,y+r), r, 90, 270, dxfattribs={"layer":"PATTERN"})
                msp.add_arc((x+hole_w-r,y+r), r, -90, 90, dxfattribs={"layer":"PATTERN"})

            x += pitch_x
            col += 1

        y += pitch_y
        row += 1

    doc.saveas(filename)
    with open(filename, "rb") as f:
        encoded = base64.b64encode(f.read()).decode()

    return {
        "status": "ok",
        "file_name": os.path.basename(filename),
        "file_base64": encoded,
        "margins": {
            "x": round(margin_x, 2), 
            "y": round(margin_y, 2),
            "note": "Margins guaranteed >= 17mm"
        }
    }

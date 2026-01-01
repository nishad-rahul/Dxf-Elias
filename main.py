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
        "offset": "none", 
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
    
    msp.add_line((x+r, y), (x+w-r, y), dxfattribs={"layer": layer})
    msp.add_line((x+w, y+r), (x+w, y+h-r), dxfattribs={"layer": layer})
    msp.add_line((x+w-r, y+h), (x+r, y+h), dxfattribs={"layer": layer})
    msp.add_line((x, y+h-r), (x, y+r), dxfattribs={"layer": layer})
    
    msp.add_arc((x+w-r, y+r), r, 270, 360, dxfattribs={"layer": layer})
    msp.add_arc((x+w-r, y+h-r), r, 0, 90, dxfattribs={"layer": layer})
    msp.add_arc((x+r, y+h-r), r, 90, 180, dxfattribs={"layer": layer})
    msp.add_arc((x+r, y+r), r, 180, 270, dxfattribs={"layer": layer})

# =========================================================
# Layout Logic
# =========================================================
def calculate_centered_layout(sheet_size, hole_bounding_size, spacing):
    TARGET_MIN_MARGIN = 17.0 
    usable_space = sheet_size - (2 * TARGET_MIN_MARGIN)
    pitch = hole_bounding_size + spacing
    
    if usable_space < hole_bounding_size:
        return 0, 0, sheet_size / 2

    count = math.floor((usable_space + spacing) / pitch)
    
    if count <= 0:
        return 0, 0, sheet_size/2

    actual_pattern_width = (count * hole_bounding_size) + ((count - 1) * spacing)
    margin = (sheet_size - actual_pattern_width) / 2
    
    return count, pitch, margin

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
    corner_radius = float(payload.get("corner_radius", 5))

    spacing = cfg["spacing"]
    offset_mode = cfg["offset"]

    # ============================
    # 1. Determine Hole Bounding Box
    # ============================
    hole_w, hole_h = 10, 10 

    if pattern == "square":
        s = cfg.get("hole_size", 10)
        hole_w, hole_h = s, s
        
    elif pattern == "diamond":
        s = cfg.get("hole_size", 10)
        diagonal = s * math.sqrt(2)
        hole_w, hole_h = diagonal, diagonal
        
    elif pattern == "circle":
        d = cfg.get("hole_diameter", 10)
        hole_w, hole_h = d, d
        
    elif pattern == "slot":
        hole_w = cfg.get("slot_length", 35)
        hole_h = cfg.get("slot_width", 10)

    # ============================
    # 2. Calculate Layout
    # ============================
    cols, pitch_x, margin_x = calculate_centered_layout(length, hole_w, spacing)
    rows, pitch_y, margin_y = calculate_centered_layout(width, hole_h, spacing)

    # ============================
    # 3. Setup DXF
    # ============================
    os.makedirs("output_dxf", exist_ok=True)
    filename = f"output_dxf/{customer}_{pattern}.dxf"
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    doc.layers.new(name="OUTLINE")
    doc.layers.new(name="PATTERN")

    draw_rounded_rectangle(msp, 0, 0, length, width, corner_radius, "OUTLINE")

    # ============================
    # 4. Draw Pattern
    # ============================
    y = margin_y
    row = 0

    while row < rows:
        current_offset = 0
        if offset_mode == "half" and row % 2 != 0:
            current_offset = pitch_x / 2
        
        x = margin_x + current_offset
        col = 0

        while col < cols:
            if x + hole_w > length - 10: 
                col += 1
                continue

            if pattern == "square":
                msp.add_lwpolyline(
                    [(x,y), (x+hole_w,y), (x+hole_w,y+hole_h), (x,y+hole_h), (x,y)],
                    dxfattribs={"layer":"PATTERN"}
                )
            elif pattern == "diamond":
                cx, cy = x + hole_w/2, y + hole_h/2
                msp.add_lwpolyline(
                    [(cx, y), (x+hole_w, cy), (cx, y+hole_h), (x, cy), (cx, y)],
                    dxfattribs={"layer":"PATTERN"}
                )
            elif pattern == "circle":
                r = hole_w / 2
                msp.add_circle((x+r, y+r), r, dxfattribs={"layer":"PATTERN"})
            
            elif pattern == "slot":
                # ========================================================
                # 🛠️ FIXED: Draws a full 'Stadium' outline (Pill shape)
                # ========================================================
                r = hole_h / 2
                
                # 1. Top Line (Horizontal)
                msp.add_line(
                    (x + r, y + hole_h),       # Start Top-Left (after arc)
                    (x + hole_w - r, y + hole_h), # End Top-Right (before arc)
                    dxfattribs={"layer": "PATTERN"}
                )

                # 2. Bottom Line (Horizontal)
                msp.add_line(
                    (x + r, y),                # Start Bottom-Left
                    (x + hole_w - r, y),       # End Bottom-Right
                    dxfattribs={"layer": "PATTERN"}
                )

                # 3. Left Arc (Semi-circle 90 to 270 degrees)
                msp.add_arc(
                    center=(x + r, y + r), 
                    radius=r, 
                    start_angle=90, 
                    end_angle=270, 
                    dxfattribs={"layer": "PATTERN"}
                )

                # 4. Right Arc (Semi-circle -90 to 90 degrees)
                msp.add_arc(
                    center=(x + hole_w - r, y + r), 
                    radius=r, 
                    start_angle=-90, 
                    end_angle=90, 
                    dxfattribs={"layer": "PATTERN"}
                )

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
        "file_base64": encoded
    }

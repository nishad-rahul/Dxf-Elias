from fastapi import FastAPI, Body
import ezdxf
import os
import base64
import math

app = FastAPI()

# =========================================================
# Pattern normalization
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

    msp.add_line((x+r, y), (x+w-r, y), dxfattribs={"layer": layer})
    msp.add_line((x+w, y+r), (x+w, y+h-r), dxfattribs={"layer": layer})
    msp.add_line((x+w-r, y+h), (x+r, y+h), dxfattribs={"layer": layer})
    msp.add_line((x, y+h-r), (x, y+r), dxfattribs={"layer": layer})

    msp.add_arc((x+w-r, y+r), r, 270, 360, dxfattribs={"layer": layer})
    msp.add_arc((x+w-r, y+h-r), r, 0, 90, dxfattribs={"layer": layer})
    msp.add_arc((x+r, y+h-r), r, 90, 180, dxfattribs={"layer": layer})
    msp.add_arc((x+r, y+r), r, 180, 270, dxfattribs={"layer": layer})

# =========================================================
# 🆕 Helper: Calculate count & spacing for strict margins
# =========================================================
def calculate_dynamic_layout(total_length, hole_size, original_spacing):
    """
    Calculates number of holes and adjusted spacing to ensure
    margin is between 15mm and 20mm.
    """
    MIN_MARGIN = 15.0
    MAX_MARGIN = 20.0
    TARGET_MARGIN = 17.5  # The sweet spot

    # 1. Define standard pitch
    std_pitch = hole_size + original_spacing

    # 2. Calculate usable space for items considering MIN margin
    # We strip 15mm from both sides first
    usable_space = total_length - (2 * MIN_MARGIN)

    # 3. How many fit?
    if usable_space < hole_size:
        return 0, std_pitch # Too small to fit anything

    # Count = 1 + floor((space - hole) / pitch)
    count = math.floor((usable_space - hole_size) / std_pitch) + 1

    # 4. Check what the margin would be with standard spacing
    footprint = hole_size + (count - 1) * std_pitch
    resulting_margin = (total_length - footprint) / 2

    final_pitch = std_pitch

    # 5. If margin is too big (> 20mm), stretch the spacing
    # We ignore this if count is 1 (can't stretch spacing between 1 item)
    if resulting_margin > MAX_MARGIN and count > 1:
        # We enforce the target margin (17.5mm)
        desired_footprint = total_length - (2 * TARGET_MARGIN)
        
        # New Spacing Formula derived from: Footprint = Hole + (Count-1)*Pitch
        final_pitch = (desired_footprint - hole_size) / (count - 1)

    return count, final_pitch

# =========================================================
# DXF Generator Endpoint
# =========================================================
@app.post("/generate_dxf")
async def generate_dxf(payload: dict = Body(...)):

    if isinstance(payload, list):
        payload = payload[0]

    raw_pattern = payload.get("pattern", "Squares 10x10mm")
    cfg = PATTERN_MAP[raw_pattern]
    pattern = cfg["pattern"]

    customer = str(payload.get("customer", "unknown")).replace(" ", "_")
    length = float(payload.get("length", 500))
    width = float(payload.get("width", 300))
    # We ignore the 'border' payload now as we enforce 15-20mm strictly
    corner_radius = float(payload.get("corner_radius", 0))

    spacing = cfg["spacing"]
    offset_mode = cfg["offset"]

    # ============================
    # Determine Hole Dimensions
    # ============================
    hole_w = 0
    hole_h = 0
    
    # Extract config values safely
    p_hole_size = cfg.get("hole_size", 10)
    p_hole_dia = cfg.get("hole_diameter", 10)
    p_slot_len = cfg.get("slot_length", 35)
    p_slot_wid = cfg.get("slot_width", 10)

    if pattern in ("square", "diamond"):
        hole_w = hole_h = p_hole_size
    elif pattern == "circle":
        hole_w = hole_h = p_hole_dia
    elif pattern == "slot":
        hole_w = p_slot_len
        hole_h = p_slot_wid

    # ============================
    # 🆕 CALCULATE LAYOUT
    # ============================
    # We calculate X and Y separately to ensure fitting on both axes
    cols, pitch_x = calculate_dynamic_layout(length, hole_w, spacing)
    rows, pitch_y = calculate_dynamic_layout(width, hole_h, spacing)

    # Initialize DXF
    os.makedirs("output_dxf", exist_ok=True)
    filename = f"output_dxf/{customer}_{pattern}.dxf"

    doc = ezdxf.new("R2010")
    doc.units = ezdxf.units.MM
    msp = doc.modelspace()

    doc.layers.new(name="OUTLINE")
    doc.layers.new(name="PATTERN")

    # Outline
    draw_rounded_rectangle(msp, 0, 0, length, width, corner_radius, "OUTLINE")

    # ============================
    # Center Pattern
    # ============================
    # Recalculate footprint based on new dynamic pitch
    pattern_w = hole_w + (cols - 1) * pitch_x
    pattern_h = hole_h + (rows - 1) * pitch_y

    # Calculate starting points (Margins)
    margin_x = (length - pattern_w) / 2
    margin_y = (width - pattern_h) / 2
    
    x_start = margin_x
    y_start = margin_y

    # ============================
    # Pattern Generation Loop
    # ============================
    y = y_start
    row = 0

    while row < rows:
        # Offset logic: standard diamond/staggered
        # Note: If you want the offset to scale with the new pitch, 
        # change 'p_hole_size/2' to 'pitch_x/2'. 
        # Currently keeping your original logic.
        offset_val = 0
        if offset_mode == "half" and row % 2 != 0:
            if pattern == "diamond" or pattern == "square":
                 offset_val = p_hole_size / 2
            else:
                 # Standard stagger usually offsets by half the pitch
                 offset_val = pitch_x / 2 

        x = x_start + offset_val
        col = 0

        while col < cols:
            
            # Skip drawing if the offset pushes the last item out of bounds 
            # (common in staggered grids)
            if x + hole_w > length:
                 col += 1
                 continue

            if pattern == "square":
                s = p_hole_size
                msp.add_lwpolyline(
                    [(x,y),(x+s,y),(x+s,y+s),(x,y+s),(x,y)],
                    dxfattribs={"layer":"PATTERN"}
                )

            elif pattern == "diamond":
                s = p_hole_size
                cx, cy = x + s/2, y + s/2
                # Diamond shape using the center and half-width
                msp.add_lwpolyline(
                    [(cx,y),(x+s,cy),(cx,y+s),(x,cy),(cx,y)],
                    dxfattribs={"layer":"PATTERN"}
                )

            elif pattern == "circle":
                r = p_hole_dia / 2
                msp.add_circle((x+r,y+r), r, dxfattribs={"layer":"PATTERN"})

            elif pattern == "slot":
                hl, hw = p_slot_len, p_slot_wid
                r = hw / 2
                msp.add_line((x+r,y+r),(x+hl-r,y+r), dxfattribs={"layer":"PATTERN"})
                msp.add_arc((x+r,y+r), r, 90, 270, dxfattribs={"layer":"PATTERN"})
                msp.add_arc((x+hl-r,y+r), r, -90, 90, dxfattribs={"layer":"PATTERN"})

            x += pitch_x
            col += 1

        y += pitch_y
        row += 1

    doc.set_modelspace_vport(center=(length/2, width/2), height=width * 1.1)
    doc.saveas(filename)

    with open(filename, "rb") as f:
        encoded = base64.b64encode(f.read()).decode()

    return {
        "status": "ok",
        "file_name": os.path.basename(filename),
        "file_base64": encoded,
        "debug_info": {
            "cols": cols,
            "rows": rows,
            "final_margin_x": margin_x,
            "final_margin_y": margin_y,
            "adjusted_spacing_x": pitch_x - hole_w,
            "adjusted_spacing_y": pitch_y - hole_h
        }
    }

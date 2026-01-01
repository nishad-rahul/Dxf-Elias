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
# 🆕 LOGIC: Uniform Margins + Offset Correction
# =========================================================
def calculate_axis_params(sheet_length, item_size, min_spacing, stagger_offset=0, fixed_margin=None):
    """
    Calculates the best fit (Count, Pitch, Margin).
    If fixed_margin is provided, it forces that margin and adjusts pitch/count.
    """
    TARGET_MIN_MARGIN = 17.0 
    
    # If we are forcing a margin (to match the other side), use it.
    # Otherwise use the safety minimum.
    effective_margin = fixed_margin if fixed_margin is not None else TARGET_MIN_MARGIN
    
    # Total pattern width (including the stagger shift if applicable)
    # Visual Width ~= (Count * Pitch) - Spacing + StaggerOffset
    
    usable_space = sheet_length - (2 * effective_margin)
    
    # Estimate Pitch
    min_pitch = item_size + min_spacing
    
    if usable_space < item_size:
        return 0, 0, sheet_length / 2

    # Calculate max count that fits in the usable space
    # Formula considering stagger: (Count-1)*Pitch + Size + Stagger <= Usable
    # (Count-1)*Pitch <= Usable - Size - Stagger
    # Count-1 <= (Usable - Size - Stagger) / Pitch
    
    safe_width_allowance = usable_space - item_size - stagger_offset
    if safe_width_allowance < 0:
         return 0, 0, sheet_length / 2 # Can't fit even one with stagger
         
    count = math.floor(safe_width_allowance / min_pitch) + 1
    
    if count <= 0:
        return 0, 0, sheet_length/2

    # Calculate Perfect Pitch to fill the space EXACTLY
    # (Count - 1) * Pitch = Usable - Size - Stagger
    if count > 1:
        ideal_pitch = (usable_space - item_size - stagger_offset) / (count - 1)
    else:
        ideal_pitch = 0 # Single item, centered

    # Recalculate exact margin based on this pitch
    # Pattern Visual Width
    final_visual_width = item_size + ((count - 1) * ideal_pitch) + stagger_offset
    margin = (sheet_length - final_visual_width) / 2
    
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
    corner_radius = float(payload.get("corner_radius", 5))

    spacing = cfg["spacing"]
    offset_mode = cfg["offset"]

    # ============================
    # 1. Determine Dimensions
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

    # Determine Stagger Value (Only affects X axis visual width)
    # Stagger adds width to the total block equal to (Pitch X / 2)
    # But we don't know Pitch X yet. We estimate it first.
    est_pitch_x = hole_w + spacing
    stagger_val_x = (est_pitch_x / 2) if (offset_mode == "half") else 0
    
    # ============================
    # 2. Calculate Initial Layouts
    # ============================
    # First pass: Find the "Natural" margins for both axes
    c_x, p_x, m_x = calculate_axis_params(length, hole_w, spacing, stagger_val_x)
    c_y, p_y, m_y = calculate_axis_params(width, hole_h, spacing, 0) # No Y stagger usually

    # ============================
    # 3. Equalize Margins
    # ============================
    # Find the LARGEST margin required by either axis.
    # We must use this larger margin for BOTH sides to ensure Top=Bottom=Left=Right.
    common_margin = max(m_x, m_y)
    
    # Recalculate using the forced common margin
    # Note: We update stagger_val_x because pitch might change slightly, 
    # but the recursive difference is negligible for this purpose.
    cols, pitch_x, margin_x = calculate_axis_params(length, hole_w, spacing, stagger_val_x, fixed_margin=common_margin)
    rows, pitch_y, margin_y = calculate_axis_params(width, hole_h, spacing, 0, fixed_margin=common_margin)

    # ============================
    # 4. Setup DXF
    # ============================
    os.makedirs("output_dxf", exist_ok=True)
    filename = f"output_dxf/{customer}_{pattern}.dxf"
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    doc.layers.new(name="OUTLINE")
    doc.layers.new(name="PATTERN")

    draw_rounded_rectangle(msp, 0, 0, length, width, corner_radius, "OUTLINE")

    # ============================
    # 5. Draw Pattern
    # ============================
    y = margin_y
    row = 0
    
    # ⚠️ FIX for "Greater Left Margin":
    # If staggered, the whole block is wider. The calculated 'margin_x' 
    # centers that WIDER block.
    # However, Row 0 starts at the left-most edge. Row 1 starts shifted right.
    # The 'margin_x' we calculated is the correct distance from sheet edge 
    # to the VISUAL LEFT EDGE of the pattern block.
    # So we simply start at margin_x.
    
    x_start_base = margin_x

    while row < rows:
        current_offset = 0
        if offset_mode == "half" and row % 2 != 0:
            current_offset = pitch_x / 2
        
        # Calculate X position
        x = x_start_base + current_offset
        col = 0

        while col < cols:
            # Boundary Check
            if x + hole_w > length: 
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
                # Draw Stadium Shape
                r = hole_h / 2
                msp.add_line((x+r, y+hole_h), (x+hole_w-r, y+hole_h), dxfattribs={"layer": "PATTERN"}) # Top
                msp.add_line((x+r, y), (x+hole_w-r, y), dxfattribs={"layer": "PATTERN"}) # Bottom
                msp.add_arc((x+r, y+r), r, 90, 270, dxfattribs={"layer": "PATTERN"}) # Left Cap
                msp.add_arc((x+hole_w-r, y+r), r, -90, 90, dxfattribs={"layer": "PATTERN"}) # Right Cap

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
            "requested_uniformity": True,
            "final_margin_x": round(margin_x, 2),
            "final_margin_y": round(margin_y, 2)
        }
    }

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
    "Slotted hole 35x10mm": {"pattern": "slot", "slot_length": 35, "slot_width": 10, "spacing": 10, "offset": "half"},
}

# =========================================================
# Helper: Optimized Count (Forces Tight 17-20mm Margin)
# =========================================================
def optimize_tight_count(available_length, item_size, pitch, stagger_offset=0):
    """
    Calculates the maximum count to ensure margins are as small as possible 
    (ideally 17mm to 20mm).
    """
    # Formula: (Count-1)*Pitch + ItemSize + Stagger + (2 * 17) <= Available
    max_c = math.floor((available_length - item_size - stagger_offset - 34) / pitch) + 1
    return max(1, max_c)

# =========================================================
# Layout Logic
# =========================================================
def calculate_layout_params(sheet_length, sheet_width, item_size, spacing, pattern_type, grouping=None):
    # 1. Define Pitch
    if pattern_type == "diamond":
        pitch_x = (item_size + spacing) * math.sqrt(2)
        pitch_y = pitch_x / 2
        stagger_x = pitch_x / 2
        bounding_size = item_size * math.sqrt(2)
    else:
        pitch_x = item_size + spacing
        pitch_y = 10.0 + spacing if pattern_type == "slot" else item_size + spacing
        stagger_x = (pitch_x / 2)
        bounding_size = item_size

    # 2. Q+ GREEDY OPTIMIZATION (Force Margin < 20mm)
    if grouping:
        base_gap = grouping["gap_size"]
        best_col_count = 8
        
        # We start at 8 columns and keep adding columns until the margin 
        # is as small as possible without going under 17mm.
        for c in range(8, 150):
            g_w = (c * item_size) + ((c - 1) * spacing)
            g_stride = g_w + base_gap
            n_g = max(1, math.floor((sheet_length + base_gap) / g_stride))
            pat_w = (n_g * g_w) + ((n_g - 1) * base_gap)
            margin = (sheet_length - pat_w) / 2
            
            if margin >= 17.0:
                best_col_count = c
            if margin < 17.0:
                # Once we hit the safety limit, the previous 'c' was our tightest fit
                break
        
        # Recalculate with the tightest column count found
        final_g_w = (best_col_count * item_size) + ((best_col_count - 1) * spacing)
        final_n_g = max(1, math.floor((sheet_length + base_gap) / (final_g_w + base_gap)))
        final_pat_w = (final_n_g * final_g_w) + ((final_n_g - 1) * base_gap)
        
        count_y = optimize_tight_count(sheet_width, 10 if pattern_type == "slot" else item_size, pitch_y)
        final_pat_h = (10 if pattern_type == "slot" else item_size) + ((count_y - 1) * pitch_y)
        
        return {
            "is_grouped": True, "num_groups": final_n_g, "cols_per_group": best_col_count,
            "group_stride": final_g_w + base_gap, "pitch_x": pitch_x, "pitch_y": pitch_y,
            "margin_x": (sheet_length - final_pat_w) / 2, 
            "margin_y": (sheet_width - final_pat_h) / 2, 
            "count_y": count_y
        }

    # 3. Standard Optimization (Strictly packed)
    count_x = optimize_tight_count(sheet_length, bounding_size, pitch_x, stagger_x)
    item_h = 10 if pattern_type == "slot" else bounding_size
    count_y = optimize_tight_count(sheet_width, item_h, pitch_y)

    total_w = bounding_size + ((count_x - 1) * pitch_x) + stagger_x
    total_h = item_h + ((count_y - 1) * pitch_y)

    return {
        "is_grouped": False, "count_x": count_x, "count_y": count_y,
        "pitch_x": pitch_x, "pitch_y": pitch_y,
        "margin_x": (sheet_length - total_w) / 2,
        "margin_y": (sheet_width - total_h) / 2
    }

# =========================================================
# DXF Generator Endpoint
# =========================================================
@app.post("/generate_dxf")
async def generate_dxf(payload: dict = Body(...)):
    if isinstance(payload, list): payload = payload[0]

    raw_pattern = payload.get("pattern", "Squares 10x10mm")
    cfg = PATTERN_MAP.get(raw_pattern, PATTERN_MAP["Squares 10x10mm"])
    pattern = cfg["pattern"]

    customer = str(payload.get("customer", "Standard")).replace(" ", "_")
    length, width = float(payload.get("length", 500)), float(payload.get("width", 300))
    bent_top = payload.get("bent_top", False)
    
    # Correct Base Sizes for packing logic
    hole_w = 35 if pattern == "slot" else 10
    hole_h = 10 if pattern == "slot" else hole_w

    # Calculate Layout (Packed tight to edges)
    layout = calculate_layout_params(length, width, hole_w, cfg["spacing"], pattern, cfg.get("grouping"))
    
    # Extra height for the bend (appears at the top)
    final_width = width + 5.1 if bent_top else width

    os.makedirs("output_dxf", exist_ok=True)
    filename = f"output_dxf/{customer}_{int(length)}x{final_width}.dxf"
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()

    # Draw Outline
    msp.add_lwpolyline([(0,0), (length,0), (length, final_width), (0, final_width), (0,0)], dxfattribs={"layer": "OUTLINE"})

    # Draw Pattern
    y = layout["margin_y"]
    for row in range(layout["count_y"]):
        # Horizontal Loop
        if layout["is_grouped"]:
            for g in range(layout["num_groups"]):
                g_start = layout["margin_x"] + (g * layout["group_stride"])
                for c in range(layout["cols_per_group"]):
                    x = g_start + (c * layout["pitch_x"])
                    msp.add_lwpolyline([(x,y),(x+hole_w,y),(x+hole_w,y+hole_h),(x,y+hole_h),(x,y)], dxfattribs={"layer":"PATTERN"})
        else:
            row_off = (layout["pitch_x"] / 2) if cfg["offset"] == "half" and row % 2 != 0 else 0
            x_start = layout["margin_x"] + row_off
            for c in range(layout["count_x"]):
                x = x_start + (c * layout["pitch_x"])
                if x + hole_w > length: continue
                
                if pattern == "square":
                    msp.add_lwpolyline([(x,y),(x+hole_w,y),(x+hole_w,y+hole_h),(x,y+hole_h),(x,y)], dxfattribs={"layer":"PATTERN"})
                elif pattern == "slot":
                    r = hole_h / 2
                    msp.add_line((x+r, y), (x+hole_w-r, y), dxfattribs={"layer":"PATTERN"})
                    msp.add_line((x+r, y+hole_h), (x+hole_w-r, y+hole_h), dxfattribs={"layer":"PATTERN"})
                    msp.add_arc((x+r, y+r), r, 90, 270, dxfattribs={"layer":"PATTERN"})
                    msp.add_arc((x+hole_w-r, y+r), r, 270, 90, dxfattribs={"layer":"PATTERN"})

        y += layout["pitch_y"]

    doc.saveas(filename)
    with open(filename, "rb") as f:
        return {"status": "ok", "file_name": os.path.basename(filename), "file_base64": base64.b64encode(f.read()).decode()}

from fastapi import FastAPI, Body
import ezdxf, os, base64
from ezdxf import path
from ezdxf.render import forms

app = FastAPI()

# ------------------------------------
# Pattern definitions (dynamic presets)
# ------------------------------------
RULES = {
    "Squares 10x10mm": {
        "type": "square", "size": 10, "spacing": 10, "offset": "half",
    },
    "Check 10x10mm": {
        "type": "diamond", "size": 10, "spacing": 10, "offset": "half",
    },
    "Slotted hole 35x10mm": {
        "type": "slot", "length": 35, "width": 10, "spacing": 10, "offset": "half",
    },
    "Round hole 10mm": {
        "type": "circle", "diameter": 10, "spacing": 10, "offset": "half",
    },
    "Squares with bars": {
        "type": "bar", "size": 10, "spacing": 10, "offset": "half", "bar_width": 2,
    },
}

# ------------------------------------
# Dynamic DXF Generator
# ------------------------------------
@app.post("/generate_dxf")
async def generate_dxf(payload: dict = Body(...)):
    """
    Expects JSON payload from n8n:
    {
      "customer": "Weis",
      "order_number": "DE594125",
      "variant": "A",
      "material": "ES",
      "pattern": "Squares 10x10mm",
      "length": 1300,
      "width": 430,
      "corner_radius": 5,
      "border": 17,
      "bridge_width": 10
    }
    """
    # ---- Extract dynamic parameters (with safe defaults)
    customer = str(payload.get("customer", "unknown")).replace(" ", "_")
    pattern_name = payload.get("pattern", "Squares 10x10mm")
    length = float(payload.get("length", 500))
    width = float(payload.get("width", 300))
    border = float(payload.get("border", 17))
    corner_radius = float(payload.get("corner_radius", 5))

    # Retrieve pattern rule
    rule = RULES.get(pattern_name, RULES["Squares 10x10mm"])

    # ---- Prepare output directory & filename
    os.makedirs("output_dxf", exist_ok=True)
    pattern_code = pattern_name.split()[0]
    filename = f"output_dxf/{customer}_{pattern_code}.dxf"

    # ---- DXF setup
    doc = ezdxf.new("R2010")
    doc.units = ezdxf.units.MM
    msp = doc.modelspace()

    for layer in ("OUTLINE", "PATTERN"):
        if layer not in doc.layers:
            doc.layers.new(name=layer)

    # ---- Rounded rectangle outline (Variant A)
    outline_path = forms.rect(length, width, radius=corner_radius)
    outline_poly = path.to_lwpolyline(outline_path, close=True)
    outline_poly.dxf.layer = "OUTLINE"
    msp.add_entity(outline_poly)

    # ---- Pattern bounding area
    px1, py1 = border, border
    px2, py2 = length - border, width - border

    y = py1
    row = 0

    # ---- Pattern generation
    while y < py2:
        offset_x = 0
        if rule.get("offset") == "half" and row % 2 == 1:
            offset_x = rule.get("size", rule.get("diameter", 10)) / 2
        x = px1 + offset_x

        while x < px2:
            t = rule["type"]

            if t == "square":
                s = rule["size"]
                if x + s <= px2 and y + s <= py2:
                    msp.add_lwpolyline(
                        [(x,y),(x+s,y),(x+s,y+s),(x,y+s),(x,y)],
                        dxfattribs={"layer": "PATTERN"},
                    )

            elif t == "diamond":
                s = rule["size"]
                if x + s <= px2 and y + s <= py2:
                    msp.add_lwpolyline(
                        [
                            (x + s/2, y),
                            (x + s, y + s/2),
                            (x + s/2, y + s),
                            (x, y + s/2),
                            (x + s/2, y),
                        ],
                        dxfattribs={"layer": "PATTERN"},
                    )

            elif t == "circle":
                d = rule["diameter"]
                r = d / 2
                if x + d <= px2 and y + d <= py2:
                    msp.add_circle((x + r, y + r), r, dxfattribs={"layer": "PATTERN"})

            elif t == "slot":
                hl, hw = rule["length"], rule["width"]
                r = hw / 2
                if x + hl <= px2 and y + hw <= py2:
                    # line and end arcs (rounded slot)
                    msp.add_line((x + r, y + r), (x + hl - r, y + r), dxfattribs={"layer":"PATTERN"})
                    msp.add_arc((x + r, y + r), r, 90, 270, dxfattribs={"layer":"PATTERN"})
                    msp.add_arc((x + hl - r, y + r), r, -90, 90, dxfattribs={"layer":"PATTERN"})

            elif t == "bar":
                s, bw = rule["size"], rule["bar_width"]
                if x + s <= px2 and y + s <= py2:
                    # outer square + center bar
                    msp.add_lwpolyline([(x,y),(x+s,y),(x+s,y+s),(x,y+s),(x,y)], dxfattribs={"layer":"PATTERN"})
                    msp.add_lwpolyline([(x+s/2-bw/2,y),(x+s/2+bw/2,y),(x+s/2+bw/2,y+s),(x+s/2-bw/2,y+s),(x+s/2-bw/2,y)], dxfattribs={"layer":"PATTERN"})

            step_x = rule.get("size", rule.get("diameter", rule.get("length", 10))) + rule["spacing"]
            x += step_x

        step_y = rule.get("size", rule.get("diameter", rule.get("width", 10))) + rule["spacing"]
        y += step_y
        row += 1

    # ---- Adjust viewport
    doc.set_modelspace_vport(center=(length/2, width/2), height=width*1.1)

    # ---- Save and encode
    doc.saveas(filename)
    with open(filename, "rb") as f:
        encoded = base64.b64encode(f.read()).decode()

    # ---- Response to n8n
    return {
        "status": "ok",
        "file_name": os.path.basename(filename),
        "data": encoded,
        "length_mm": length,
        "width_mm": width,
        "pattern": pattern_name,
        "corner_radius": corner_radius,
        "border": border
    }

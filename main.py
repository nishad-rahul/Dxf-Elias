from fastapi import FastAPI, Body
import ezdxf, os, base64, math

app = FastAPI()

# Predefined Variant A rules
RULES = {
    "Squares 10x10mm": {"pattern": "square", "hole_size": 10, "spacing": 10, "offset": "half"},
    "Check 10x10mm": {"pattern": "diamond", "hole_size": 10, "spacing": 10, "offset": "half"},
    "Slotted hole 35x10mm": {"pattern": "slot", "hole_length": 35, "hole_width": 10, "spacing": 10, "offset": "next_up_half"},
    "Round hole 10mm": {"pattern": "circle", "hole_size": 10, "spacing": 10, "offset": "half"},
    "Squares with bars": {"pattern": "square_bars", "hole_size": 10, "spacing": 10, "bar_width": 3}
}

@app.post("/generate-dxf")
async def generate_dxf(payload: dict = Body(...)):
    customer = payload.get("customer", "unknown")
    pattern_name = payload.get("pattern")
    length = float(payload.get("length", 500))
    width  = float(payload.get("width", 300))
    margin = 17
    corner_radius = 5

    os.makedirs("output_dxf", exist_ok=True)
    filename = f"output_dxf/{customer}.dxf"

    rule = RULES.get(pattern_name, RULES["Squares 10x10mm"])
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()

    # --- Outer border with rounded corners ---
    x1, y1, x2, y2 = 0, 0, length, width
    msp.add_lwpolyline([(x1, y1), (x2, y1), (x2, y2), (x1, y2), (x1, y1)])

    # --- Pattern area ---
    px1, py1, px2, py2 = x1 + margin, y1 + margin, x2 - margin, y2 - margin

    # Pattern generation
    y = py1
    row = 0
    while y <= py2 - rule.get("hole_size", 10):
        offset_x = 0
        if rule.get("offset") in ["half", "next_up_half"] and row % 2 == 1:
            offset_x = rule.get("hole_size", 10) / 2
        x = px1 + offset_x
        while x <= px2 - rule.get("hole_size", 10):
            p = rule["pattern"]
            if p == "square":
                s = rule["hole_size"]
                msp.add_lwpolyline([
                    (x, y),
                    (x + s, y),
                    (x + s, y + s),
                    (x, y + s),
                    (x, y)
                ])
            elif p == "diamond":
                s = rule["hole_size"]
                msp.add_lwpolyline([
                    (x + s/2, y),
                    (x + s, y + s/2),
                    (x + s/2, y + s),
                    (x, y + s/2),
                    (x + s/2, y)
                ])
            elif p == "circle":
                r = rule["hole_size"] / 2
                msp.add_circle((x + r, y + r), r)
            elif p == "slot":
                hl, hw = rule["hole_length"], rule["hole_width"]
                msp.add_lwpolyline([
                    (x, y),
                    (x + hl, y),
                    (x + hl, y + hw),
                    (x, y + hw),
                    (x, y)
                ])
            elif p == "square_bars":
                s = rule["hole_size"]
                bar = rule.get("bar_width", 3)
                # Add small crossbars inside the square
                msp.add_lwpolyline([
                    (x, y),
                    (x + s, y),
                    (x + s, y + s),
                    (x, y + s),
                    (x, y)
                ])
                msp.add_line((x, y + s/2), (x + s, y + s/2))
                msp.add_line((x + s/2, y), (x + s/2, y + s))
            x += rule.get("hole_size", 10) + rule.get("spacing", 10)
        y += rule.get("hole_size", 10) + rule.get("spacing", 10)
        row += 1

    # --- Encode and return ---
    doc.saveas(filename)
    with open(filename, "rb") as f:
        encoded = base64.b64encode(f.read()).decode()

    return {"status": "ok", "filename": filename, "file_base64": encoded}

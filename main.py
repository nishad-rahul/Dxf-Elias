return items.map(item => {
  const data = item.json;

  // Pattern Mapping
  const patternMap = {
    "K": "Check 10x10mm",
    "L": "Slotted hole 35x10mm",
    "Q": "Squares 10x10mm",
    "Q+": "Squares Grouped",
    "O": "Round hole 10mm",
  };

  const musterCode = (data.Muster || "").toString().trim();
  const selectedPattern = patternMap[musterCode] || data.Pattern || "Squares 10x10mm";

  // =================================================
  // 🆕 DETECT BENDING REQUIREMENT
  // =================================================
  // Check "sonstiges" for keywords indicating a bent side
  const rawNotes = (data.sonstiges || "").toString().toLowerCase();
  
  // Keywords: "gekantet" (folded), "bent", "lange seite" (long side)
  const isBentTop = 
    (rawNotes.includes("gekantet") || rawNotes.includes("bent")) &&
    (rawNotes.includes("lange") || rawNotes.includes("seite") || rawNotes.includes("side"));

  const payload = {
    customer: data.Name,
    order_number: data.Bestellnr || "",
    variant: data.Variant || data.Ausführung || "A",
    material: data.Material || "ES",
    pattern: selectedPattern,
    length: data.Length,
    width: data.Width,
    thickness: data.Thickness || 1,
    corner_radius: 5,
    border: 17,
    bridge_width: 10,
    units: "mm",
    
    // 🆕 Send Flag to Python
    bent_top: isBentTop, 

    actions: [
      {
        type: "add_rounded_rectangle",
        width: data.Width,
        height: data.Length,
        corner_radius: 5,
      },
      {
        type: "add_pattern",
        pattern_type: selectedPattern,
        offset: 10,
        border: 17,
      },
    ],
  };

  return { json: payload };
});

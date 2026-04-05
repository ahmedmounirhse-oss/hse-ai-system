def validate_classification(desc, ai_type):
    valid = ["Observation", "Near Miss", "Incident"]

    if ai_type in valid:
        return ai_type

    t = (desc or "").lower()

    if any(x in t for x in ["injury", "fire", "damage", "explosion"]):
        return "Incident"

    if any(x in t for x in ["near miss", "almost", "could have"]):
        return "Near Miss"

    return "Observation"


def map_severity(severity_text):
    mapping = {
        "LOW": 2,
        "MEDIUM": 3,
        "HIGH": 5
    }
    return mapping.get(str(severity_text).upper(), 3)
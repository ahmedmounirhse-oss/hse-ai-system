def calculate_risk(severity, likelihood):
    score = severity * likelihood

    if score <= 5:
        level = "Low"
    elif score <= 12:
        level = "Medium"
    else:
        level = "High"

    return score, level
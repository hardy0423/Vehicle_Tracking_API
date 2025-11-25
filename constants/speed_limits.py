from typing import Dict

# Seuils de gravité (en km/h au-dessus de la limite)
SEVERITY_THRESHOLDS = {
    'low': 10,        # 0-10 km/h au-dessus
    'medium': 20,     # 11-20 km/h au-dessus
    'high': 30,       # 21-30 km/h au-dessus
    'critical': 31    # 31+ km/h au-dessus
}
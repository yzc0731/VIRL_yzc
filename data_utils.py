import math

def calculate_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the bearing from point A (lat1, lon1) to point B (lat2, lon2)
    
    Args:
        lat1: Latitude of point A in decimal degrees
        lon1: Longitude of point A in decimal degrees
        lat2: Latitude of point B in decimal degrees
        lon2: Longitude of point B in decimal degrees
    
    Returns:
        Bearing in degrees from north, measured clockwise (0-360)
    """
    # Convert decimal degrees to radians
    lat1 = math.radians(lat1)
    lon1 = math.radians(lon1)
    lat2 = math.radians(lat2)
    lon2 = math.radians(lon2)
    
    # Calculate longitude difference
    dLon = lon2 - lon1
    
    # Calculate bearing components
    y = math.sin(dLon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dLon)
    bearing = math.atan2(y, x)
    
    # Convert radians to degrees and normalize to 0-360
    bearing = math.degrees(bearing)
    bearing = (bearing + 360) % 360
    
    return bearing
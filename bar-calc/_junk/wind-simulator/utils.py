def clamp(value, min_value, max_value):
    return max(min_value, min(value, max_value))

def smooth_step(edge1, edge2, value):
    v = clamp(value, edge1, edge2)
    x = (v - edge1) / (edge2 - edge1)
    t = clamp(x, 0.0, 1.0)
    res = (t * t * (3.0 - 2.0 * t))
    return res

def mix(v1, v2, a):
    return  v1 + (v2 - v1) * a

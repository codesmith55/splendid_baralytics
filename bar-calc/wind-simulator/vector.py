import math

class Vector:
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def __add__(self, other):
        if isinstance(other, Vector):
            return Vector(self.x + other.x, self.y + other.y)
        return Vector(self.x + other, self.y + other)
    
    def __sub__(self, other):
        if isinstance(other, Vector):
            return Vector(self.x - other.x, self.y - other.y)
        return Vector(self.x - other, self.y - other)

    def __mul__(self, other):
        if isinstance(other, Vector):
            return Vector(self.x * other.x, self.y * other.y)
        return Vector(self.x * other, self.y * other)
    
    def __isub__(self, other):
        if isinstance(other, Vector):
            return Vector(self.x - other.x, self.y - other.y)
        return Vector(self.x - other, self.y - other)
    
    def __itruediv__ (self, other):
        if isinstance(other, Vector):
            return Vector(self.x / other.x, self.y / other.y)
        return Vector(self.x / other, self.y / other)
    
    def __imul__(self, other):
        if isinstance(other, Vector):
            return Vector(self.x * other.x, self.y * other.y)
        return Vector(self.x * other, self.y * other)
    
    def length(self):
        return math.sqrt(self.x**2 + self.y**2)
    
    def normalize(self):
        len = self.length()
        if len > 1e-6:  # equivalent to nrm_eps()
            self.x /= len
            self.y /= len
        return len
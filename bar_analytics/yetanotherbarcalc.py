import math

class EconomyState:
    def __init__(self, metal=0, energy=0, bp=380, m_inc=0, e_inc=0):
        self.metal = metal
        self.energy = energy
        self.bp = bp
        self.m_inc = m_inc
        self.e_inc = e_inc
        self.time_elapsed = 0
        self.total_metal_produced = 0

    def get_effective_m_inc(self, e_to_m_rate=70):
        # Converts all surplus energy into metal
        return self.m_inc + (self.e_inc / e_to_m_rate)

    def build(self, unit):
        # Calculate time to build based on the limiting factor
        # Max of (Metal needed/Metal income, Energy needed/Energy income, Work needed/BP)
        t_m = (unit['metalCost'] - self.metal) / self.m_inc if unit['metalCost'] > self.metal else 0
        t_e = (unit['energyCost'] - self.energy) / self.e_inc if unit['energyCost'] > self.energy else 0
        t_bp = unit['buildpowercost'] / self.bp
        
        build_time = max(t_m, t_e, t_bp)
        
        # Advance state
        self.time_elapsed += build_time
        self.total_metal_produced += self.get_effective_m_inc() * build_time
        
        # Update resources (simplified: assume income covers costs over build_time)
        self.metal = max(0, self.metal + (self.m_inc * build_time) - unit['metalCost'])
        self.energy = max(0, self.energy + (self.e_inc * build_time) - unit['energyCost'])
        
        # Update production stats if the unit provides them
        self.m_inc += unit.get('metalPerSecond', 0)
        self.e_inc += unit.get('energyPerSecond', 0)
        self.bp += unit.get('bp_gain', 0)

# Constants
WIND = {"energyPerSecond": 11.9, "metalPerSecond": 0, "metalCost": 40, "energyCost": 175, "buildpowercost": 1600}
T2MEX = {"energyPerSecond": 0, "metalPerSecond": 5.4, "metalCost": 620, "energyCost": 7700, "buildpowercost": 14900}
T2LAB = {"metalCost": 2900, "energyCost": 1600, "buildpowercost": 16200}
T2CON = {"metalCost": 430, "energyCost": 6900, "buildpowercost": 9500}
TURRET = {"metalCost": 230, "energyCost": 3200, "buildpowercost": 5300, "bp_gain": 200} # Example BP gain

def calculate_breakeven():
    # Strategy 1: Pure Wind (Scaling Energy -> Metal)
    # We simulate building 50 winds as a baseline
    s1 = EconomyState(m_inc=2, e_inc=20) # Starting income
    for _ in range(30):
        s1.build(WIND)
    
    # Strategy 2: Tech to T2
    s2 = EconomyState(m_inc=2, e_inc=20)
    # Build some wind first to afford the lab
    for _ in range(10):
        s2.build(WIND)
    s2.build(T2LAB)
    s2.build(T2CON)
    s2.build(T2MEX)
    s2.build(T2MEX)

    print(f"Strategy 1 (Wind): Time {s1.time_elapsed:.1f}s, Metal Income: {s1.get_effective_m_inc():.2f}/s")
    print(f"Strategy 2 (T2):   Time {s2.time_elapsed:.1f}s, Metal Income: {s2.get_effective_m_inc():.2f}/s")

    # Calculate when S2 overtakes S1 in total metal produced
    # S1_Total = S1_Yield_at_T2_Start + S1_Rate * (t - S1_End_Time)
    # This is a simple linear intersection after both finishes building
    m_diff = s1.total_metal_produced - s2.total_metal_produced
    rate_diff = s2.get_effective_m_inc() - s1.get_effective_m_inc()
    
    if rate_diff <= 0:
        return "T2 never overtakes Wind at this scale."
    
    catchup_time = m_diff / rate_diff
    return max(s1.time_elapsed, s2.time_elapsed) + catchup_time

breakeven = calculate_breakeven()
print(f"--- \nBreakeven Time: {breakeven:.2f} seconds")
import math
import bisect
import random
import matplotlib.pyplot as plt

# --- Simulation Constants ---
TICKS_PER_SEC = 30
TICKS_PER_WIND_UPDATE = 450
TICKS_PER_ITERATION = 2

# --- Data for Buildable Objects ---
OBJECT_COSTS = {
    "armwind": {"metal": 75, "energy": 100, "build_power_cost": 1000},
    "armasolar": {"metal": 120, "energy": 50, "build_power_cost": 1200},
}
OBJECT_PRODUCTION = {
    "armwind": {"metal": 0, "energy": 0, "bp": 0},
    "armasolar": {"metal": 0, "energy": 40, "bp": 0},
}

class Vector:
    def __init__(self, x, y):
        self.x = x
        self.y = y

class Simulator():
    def __init__(self):
        self.current_objs = { "armwind": 0, "armasolar": 0 }
        self.production = { "metal": 2, "energy": 30, "bp": 300 }
        self.current = { "metal": 1000, "energy": 1000 }
        self.storage = { "metal": 1000, "energy": 1000 }
        self.time = 0
        self.wind = {}
        self.current_build_project = None

    def status_report(self):
        print(f"--- Time: {self.time} seconds ---")
        print(f"Resources: Metal: {self.current['metal']:.2f}, Energy: {self.current['energy']:.2f}")
        print(f"Production/sec: Metal: {self.production['metal']:.2f}, Static Energy: {self.production['energy']:.2f}, Build Power: {self.production['bp']:.2f}")
        wind_power = self._get_power_at_time(self.time) * self.current_objs['armwind']
        print(f"Instantaneous Wind Power: {wind_power:.2f} E/sec")
        if self.current_build_project:
            progress = (self.current_build_project['progress'] / self.current_build_project['build_power_cost']) * 100
            print(f"Building: {self.current_build_project['name']} ({progress:.1f}%)")
        print("-" * 30 + "\n")

    def _get_power_at_time(self, t):
        """Internal helper to calculate interpolated power at a specific time t."""
        if not self.wind: return 0
        
        sorted_times = sorted(self.wind.keys())
        if t <= sorted_times[0]: return self.wind[sorted_times[0]]
        if t >= sorted_times[-1]: return self.wind[sorted_times[-1]]
        
        idx = bisect.bisect_left(sorted_times, t)
        if sorted_times[idx] == t: return self.wind[t]

        t2, t1 = sorted_times[idx], sorted_times[idx - 1]
        power2, power1 = self.wind[t2], self.wind[t1]

        fraction = (t - t1) / (t2 - t1)
        return power1 + fraction * (power2 - power1)

    def start_building(self, object_name):
        """Initiates a new construction project."""
        if self.current_build_project:
            print("Cannot start new project, another is in progress.")
            return False
        if object_name not in OBJECT_COSTS:
            print(f"Error: Object '{object_name}' not recognized.")
            return False
            
        costs = OBJECT_COSTS[object_name]
        self.current_build_project = {
            "name": object_name,
            "progress": 0.0,
            **costs
        }
        print(f">>> Starting construction of: {object_name}")
        return True

    def advance_simulation_one_second(self):
        """Simulates one second of game time, updating resources and build progress."""
        # 1. Income Phase
        self.current['metal'] += self.production['metal']
        # Add static energy production
        total_energy_income = self.production['energy']
        # Add dynamic energy from windmills
        if self.current_objs['armwind'] > 0:
            total_energy_income += self._get_power_at_time(self.time) * self.current_objs['armwind']
        
        self.current['energy'] += total_energy_income

        # 2. Build Phase
        if self.current_build_project:
            proj = self.current_build_project
            
            # Determine how much build power we can actually apply this second
            bp_to_apply = self.production['bp']
            
            # Calculate cost per unit of build power
            cost_per_bp_metal = proj['metal'] / proj['build_power_cost']
            cost_per_bp_energy = proj['energy'] / proj['build_power_cost']
            
            # Calculate resource cost for this second at full speed
            metal_cost_this_second = cost_per_bp_metal * bp_to_apply
            energy_cost_this_second = cost_per_bp_energy * bp_to_apply
            
            # Check for resource shortages and scale down build power if needed
            metal_modifier = 1.0
            if metal_cost_this_second > self.current['metal'] + self.production['metal']:
                metal_modifier = self.current['metal'] + self.production['energy']/ metal_cost_this_second if metal_cost_this_second > 0 else 1

            energy_modifier = 1.0
            if energy_cost_this_second > self.current['energy'] + self.production['energy']:
                energy_modifier = (self.current['energy'] + self.production['energy'])/ energy_cost_this_second if energy_cost_this_second > 0 else 1
            
            # The actual build rate is limited by the most severe bottleneck
            actual_build_modifier = min(metal_modifier, energy_modifier)
            actual_bp_applied = bp_to_apply * actual_build_modifier
            
            # Deduct the actual resources used
            self.current['metal'] -= cost_per_bp_metal * actual_bp_applied
            self.current['energy'] -= cost_per_bp_energy * actual_bp_applied
            
            # Clamp to storage
            self.current['metal'] = min(self.current['metal'], self.storage['metal'])
            self.current['energy'] = min(self.current['energy'], self.storage['energy'])

            # Update build progress
            proj['progress'] += actual_bp_applied
            
            # 3. Completion Check
            if proj['progress'] >= proj['build_power_cost']:
                object_name = proj['name']
                print(f"'{object_name}' construction complete!")
                self.current_objs[object_name] += 1
                
                gains = OBJECT_PRODUCTION.get(object_name)
                if gains:
                    self.production['metal'] += gains['metal']
                    self.production['energy'] += gains['energy']
                    self.production['bp'] += gains['bp']
                self.current_build_project = None
                self.status_report()

        # 4. Advance Time
        self.time += 1

def run_tick_based_simulation(sim, build_queue, max_sim_time):
    """
    Runs a second-by-second simulation with a given build queue.
    """
    print("--- Starting Tick-Based Simulation ---")
    sim.status_report()
    
    for second in range(max_sim_time):
        # If nothing is being built and there are items in the queue, start the next one
        if not sim.current_build_project and build_queue:
            next_build = build_queue.pop(0)
            sim.start_building(next_build)

        # Advance the simulation by one tick (second)
        sim.advance_simulation_one_second()

        # Print a status report every 30 seconds
        if sim.time % 30 == 0:
            sim.status_report()
            
        # Stop if build queue is empty and nothing is being built
        if not build_queue and not sim.current_build_project:
            print("--- Build queue is empty. Halting simulation. ---")
            break
    
    print("--- Simulation Finished. Final State: ---")
    sim.status_report()



###


def update_wind(tick, min_wind, max_wind):
    """
    Placeholder function to generate a wind speed value.
    A more complex model (e.g., using Perlin noise) could be used here.
    """
    return random.uniform(min_wind, max_wind)

def simulate_wind(sim_time, min_wind, max_wind, display_wind_graph=0):
    """Simulate winds, put values into buckets, graph wind distribution buckets"""
    total_sim_ticks = sim_time * TICKS_PER_SEC
    buckets = {}
    total_wind = 0
    total_ticks = 0
    wind_by_time = {}

    for tick in range(0, total_sim_ticks, TICKS_PER_ITERATION):
        wind_speed = update_wind(tick, min_wind, max_wind)
        total_wind += wind_speed
        total_ticks += 1
        rounded_wind_speed = round(wind_speed * 2) / 2
        buckets[rounded_wind_speed] = buckets.get(rounded_wind_speed, 0) + 1
        
        if tick % TICKS_PER_WIND_UPDATE == 0:
            second = int(tick / TICKS_PER_SEC)
            wind_by_time[second] = rounded_wind_speed
    
    # Ensure the start time (0) has a wind value
    if 0 not in wind_by_time and total_ticks > 0:
            wind_by_time[0] = round(update_wind(0, min_wind, max_wind) * 2) / 2
    
    if display_wind_graph == 1: 
        print(buckets)
        print(f"avg wind: {total_wind/total_ticks}")
        x_axis = list(buckets.keys())
        y_axis = list(buckets.values())
        plt.bar(x_axis,y_axis)
        plt.show()

    return wind_by_time

def calculate_wind_energy(self, num_windmills, start_time, end_time, verbose=0):
    """Calculates the total wind energy generated over a given time period."""
    if start_time >= end_time or num_windmills == 0 or not self.wind:
        return 0

    wind_data = self.wind
    sorted_times = sorted(wind_data.keys())

    def get_power_at_time(t):
        if t <= sorted_times[0]: return wind_data[sorted_times[0]]
        if t >= sorted_times[-1]: return wind_data[sorted_times[-1]]
        
        idx = bisect.bisect_left(sorted_times, t)
        if sorted_times[idx] == t: return wind_data[t]

        t2 = sorted_times[idx]
        t1 = sorted_times[idx - 1]
        power1, power2 = wind_data[t1], wind_data[t2]

        fraction = (t - t1) / (t2 - t1)
        return power1 + fraction * (power2 - power1)

    integration_points = [t for t in sorted_times if start_time < t < end_time]
    integration_points.insert(0, start_time)
    integration_points.append(end_time)
    integration_points = sorted(list(set(integration_points)))
    
    total_energy_per_windmill = 0.0
    for i in range(len(integration_points) - 1):
        t_start, t_end = integration_points[i], integration_points[i+1]
        power_start, power_end = get_power_at_time(t_start), get_power_at_time(t_end)
        duration = t_end - t_start
        area = (power_start + power_end) / 2.0 * duration
        total_energy_per_windmill += area
        
    total_energy = round(total_energy_per_windmill * num_windmills)
    
    if verbose == 1:
        print(f"From time {start_time} to {end_time} with {num_windmills} windmills you produced {total_energy} energy")
    return total_energy


# --- Main Simulation Execution ---
if __name__ == "__main__":
    sim_instance = Simulator()
    
    # The wind data provided in the user prompt
    sim_instance.wind = simulate_wind(360, 0, 16)
    # Define a build order: 10 windmills
    build_order = ['armwind'] * 10
    
    run_tick_based_simulation(sim_instance, build_order, max_sim_time=1000)


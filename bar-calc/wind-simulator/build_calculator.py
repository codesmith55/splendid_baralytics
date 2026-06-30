import random
import matplotlib.pyplot as plt
import bisect
import copy
from vector import Vector
from utils import mix, clamp, smooth_step

# Avg wind based on [min][max] from BAR repo
monte_carlo_avg_wind = {
    0: {1: 0.8, 2: 1.5, 3: 2.2, 4: 3.0, 5: 3.7, 6: 4.5, 7: 5.2, 8: 6.0, 9: 6.7, 10: 7.5, 11: 8.2, 12: 9.0, 13: 9.7, 14: 10.4, 15: 11.2, 16: 11.9, 17: 12.7, 18: 13.4, 19: 14.2, 20: 14.9, 21: 15.7, 22: 16.4, 23: 17.2, 24: 17.9, 25: 18.6, 26: 19.2, 27: 19.6, 28: 20.0, 29: 20.4, 30: 20.7},
    1: {2: 1.6, 3: 2.3, 4: 3.0, 5: 3.8, 6: 4.5, 7: 5.2, 8: 6.0, 9: 6.7, 10: 7.5, 11: 8.2, 12: 9.0, 13: 9.7, 14: 10.4, 15: 11.2, 16: 11.9, 17: 12.7, 18: 13.4, 19: 14.2, 20: 14.9, 21: 15.7, 22: 16.4, 23: 17.2, 24: 17.9, 25: 18.6, 26: 19.2, 27: 19.6, 28: 20.0, 29: 20.4, 30: 20.7},
    2: {3: 2.6, 4: 3.2, 5: 3.9, 6: 4.6, 7: 5.3, 8: 6.0, 9: 6.8, 10: 7.5, 11: 8.2, 12: 9.0, 13: 9.7, 14: 10.5, 15: 11.2, 16: 12.0, 17: 12.7, 18: 13.4, 19: 14.2, 20: 14.9, 21: 15.7, 22: 16.4, 23: 17.2, 24: 17.9, 25: 18.6, 26: 19.2, 27: 19.6, 28: 20.0, 29: 20.4, 30: 20.7},
    3: {4: 3.6, 5: 4.2, 6: 4.8, 7: 5.5, 8: 6.2, 9: 6.9, 10: 7.6, 11: 8.3, 12: 9.0, 13: 9.8, 14: 10.5, 15: 11.2, 16: 12.0, 17: 12.7, 18: 13.5, 19: 14.2, 20: 15.0, 21: 15.7, 22: 16.4, 23: 17.2, 24: 17.9, 25: 18.7, 26: 19.2, 27: 19.7, 28: 20.0, 29: 20.4, 30: 20.7},
    4: {5: 4.6, 6: 5.2, 7: 5.8, 8: 6.4, 9: 7.1, 10: 7.8, 11: 8.5, 12: 9.2, 13: 9.9, 14: 10.6, 15: 11.3, 16: 12.1, 17: 12.8, 18: 13.5, 19: 14.3, 20: 15.0, 21: 15.7, 22: 16.5, 23: 17.2, 24: 18.0, 25: 18.7, 26: 19.2, 27: 19.7, 28: 20.1, 29: 20.4, 30: 20.7},
    5: {6: 5.5, 7: 6.1, 8: 6.8, 9: 7.4, 10: 8.0, 11: 8.7, 12: 9.4, 13: 10.1, 14: 10.8, 15: 11.5, 16: 12.2, 17: 12.9, 18: 13.6, 19: 14.4, 20: 15.1, 21: 15.8, 22: 16.5, 23: 17.3, 24: 18.0, 25: 18.8, 26: 19.3, 27: 19.7, 28: 20.1, 29: 20.4, 30: 20.7},
    6: {7: 6.5, 8: 7.1, 9: 7.7, 10: 8.4, 11: 9.0, 12: 9.7, 13: 10.3, 14: 11.0, 15: 11.7, 16: 12.4, 17: 13.1, 18: 13.8, 19: 14.5, 20: 15.2, 21: 15.9, 22: 16.7, 23: 17.4, 24: 18.1, 25: 18.8, 26: 19.4, 27: 19.8, 28: 20.2, 29: 20.5, 30: 20.8},
    7: {8: 7.5, 9: 8.1, 10: 8.7, 11: 9.3, 12: 10.0, 13: 10.6, 14: 11.3, 15: 11.9, 16: 12.6, 17: 13.3, 18: 14.0, 19: 14.7, 20: 15.4, 21: 16.1, 22: 16.8, 23: 17.5, 24: 18.2, 25: 19.0, 26: 19.5, 27: 19.9, 28: 20.3, 29: 20.6, 30: 20.9},
    8: {9: 8.5, 10: 9.1, 11: 9.7, 12: 10.3, 13: 11.0, 14: 11.6, 15: 12.2, 16: 12.9, 17: 13.6, 18: 14.2, 19: 14.9, 20: 15.6, 21: 16.3, 22: 17.0, 23: 17.7, 24: 18.4, 25: 19.1, 26: 19.6, 27: 20.0, 28: 20.4, 29: 20.7, 30: 21.0},
    9: {10: 9.5, 11: 10.1, 12: 10.7, 13: 11.3, 14: 11.9, 15: 12.6, 16: 13.2, 17: 13.8, 18: 14.5, 19: 15.2, 20: 15.8, 21: 16.5, 22: 17.2, 23: 17.9, 24: 18.6, 25: 19.3, 26: 19.8, 27: 20.2, 28: 20.5, 29: 20.8, 30: 21.1},
    10: {11: 10.5, 12: 11.1, 13: 11.7, 14: 12.3, 15: 12.9, 16: 13.5, 17: 14.2, 18: 14.8, 19: 15.4, 20: 16.1, 21: 16.8, 22: 17.4, 23: 18.1, 24: 18.8, 25: 19.5, 26: 20.0, 27: 20.4, 28: 20.7, 29: 21.0, 30: 21.2},
    11: {12: 11.5, 13: 12.1, 14: 12.7, 15: 13.3, 16: 13.9, 17: 14.5, 18: 15.1, 19: 15.8, 20: 16.4, 21: 17.1, 22: 17.7, 23: 18.4, 24: 19.1, 25: 19.7, 26: 20.2, 27: 20.6, 28: 20.9, 29: 21.2, 30: 21.4},
    12: {13: 12.5, 14: 13.1, 15: 13.6, 16: 14.2, 17: 14.9, 18: 15.5, 19: 16.1, 20: 16.7, 21: 17.4, 22: 18.0, 23: 18.7, 24: 19.3, 25: 20.0, 26: 20.4, 27: 20.8, 28: 21.1, 29: 21.4, 30: 21.6},
    13: {14: 13.5, 15: 14.1, 16: 14.6, 17: 15.2, 18: 15.8, 19: 16.5, 20: 17.1, 21: 17.7, 22: 18.4, 23: 19.0, 24: 19.6, 25: 20.3, 26: 20.7, 27: 21.1, 28: 21.4, 29: 21.6, 30: 21.8},
    14: {15: 14.5, 16: 15.0, 17: 15.6, 18: 16.2, 19: 16.8, 20: 17.4, 21: 18.1, 22: 18.7, 23: 19.3, 24: 20.0, 25: 20.6, 26: 21.0, 27: 21.3, 28: 21.6, 29: 21.8, 30: 22.0},
    15: {16: 15.5, 17: 16.0, 18: 16.6, 19: 17.2, 20: 17.8, 21: 18.4, 22: 19.0, 23: 19.6, 24: 20.3, 25: 20.9, 26: 21.3, 27: 21.6, 28: 21.9, 29: 22.1, 30: 22.3},
    16: {17: 16.5, 18: 17.0, 19: 17.6, 20: 18.2, 21: 18.8, 22: 19.4, 23: 20.0, 24: 20.6, 25: 21.3, 26: 21.7, 27: 21.9, 28: 22.2, 29: 22.4, 30: 22.5},
    17: {18: 17.5, 19: 18.0, 20: 18.6, 21: 19.2, 22: 19.8, 23: 20.4, 24: 21.0, 25: 21.6, 26: 22.0, 27: 22.3, 28: 22.5, 29: 22.7, 30: 22.8},
    18: {19: 18.5, 20: 19.0, 21: 19.6, 22: 20.2, 23: 20.8, 24: 21.4, 25: 22.0, 26: 22.4, 27: 22.6, 28: 22.8, 29: 23.0, 30: 23.1},
    19: {20: 19.5, 21: 20.0, 22: 20.6, 23: 21.2, 24: 21.8, 25: 22.4, 26: 22.7, 27: 22.9, 28: 23.1, 29: 23.2, 30: 23.4},
    20: {21: 20.4, 22: 21.0, 23: 21.6, 24: 22.2, 25: 22.8, 26: 23.1, 27: 23.3, 28: 23.4, 29: 23.6, 30: 23.7},
    21: {22: 21.4, 23: 22.0, 24: 22.6, 25: 23.2, 26: 23.5, 27: 23.6, 28: 23.8, 29: 23.9, 30: 24.0},
    22: {23: 22.4, 24: 23.0, 25: 23.6, 26: 23.8, 27: 24.0, 28: 24.1, 29: 24.2, 30: 24.2},
    23: {24: 23.4, 25: 24.0, 26: 24.2, 27: 24.4, 28: 24.4, 29: 24.5, 30: 24.5},
    24: {25: 24.4, 26: 24.6, 27: 24.7, 28: 24.7, 29: 24.8, 30: 24.8}
}


WINDMILL_COST = 45.5
ASOLAR_COST = 427.14
ESTORE_COST = 200.7
BUILDING_STATS = {

#template
#    "OBJ_NAME": {
#        "METAL_COST":METAL_COST, 
#        "ENERGY_COST":ENERGY_COST_METAL, 
#        "BP_COST":BP_COST, 
#        "METAL_INCOME":METAL_INCOME, 
#        "ENERGY_INCOME":ENERGY_INCOME, 
#        "BP_INCOME":BP_INCOME, 
#        "ENERGY_CONVERSION":ENERGY_CONVERSION, 
#    }


    "armwind": {
        "metal_cost":40, 
        "energy_cost":175, 
        "bp_cost":1600, 
        "metal_income":0, 
        "energy_income":0, 
        "bp_income":0, 
        "energy_conversion":0, 
    },
    "armmakr": {
        "metal_cost":1, 
        "energy_cost":1100, 
        "bp_cost":2600, 
        "metal_income":0, 
        "energy_income":0, 
        "bp_income":0, 
        "energy_conversion":70, 
    },
    "armnanotc": {
        "metal_cost":210, 
        "energy_cost":3200, 
        "bp_cost":5300, 
        "metal_income":0, 
        "energy_income":0, 
        "bp_income":200, 
        "energy_conversion":0, 
    },
}

ASOLAR_INCOME = 75
ESTORE_STORAGE = 6000
BASE_STORAGE = 1000

#Simulation time in seconds
SIMULATION_TIME = 1000000
TICKS_PER_SEC = 30
TICKS_PER_WIND_UPDATE = 450
TICKS_PER_ITERATION = 2

class Simulator():

    def __init__(self):
        self.curr_wind_vec = Vector(0,0)
        self.old_wind_vec = Vector(0,0)
        self.new_wind_vec = Vector(0,0)
        self.parameters = {
            "minwind": 0,
            "maxwind": 16, 
        }
        self.current_objs = {
            "armwind": 0,
            "armasolar": 0, 
            "armestore": 0,
            "armnanotc": 0,
            "armmakr": 0,
        }
        self.production = {
            "metal": 2,
            "energy": 30,
            "bp": 300,
        }
        self.current = {
            "metal": 1000,
            "energy": 1000,
        }
        self.storage = {
            "metal": 1000,
            "energy": 1000,
        }
        self.time = 0
        self.wind = {}
        self.current_building_object = {"armwind": 0}
    

    def advance_time(self, building_energy_use, time_to_advance=1, verbose=0):
        start_time = round(self.time,2)
        end_time = round(start_time + time_to_advance,2)

        if(verbose == 1):
            print(f"pre advance time {self.current['energy']}")
        for res in self.current:
            self.current[res] += self.production[res] * time_to_advance

        if(verbose == 1):
            print(f"post base proudction income {self.current['energy']}")
            
        wind_energy_generated = self.calculate_wind_energy(start_time, end_time,0)
        self.current['energy'] += wind_energy_generated

        if(verbose == 1):
            print(f"plus wind generated {self.current['energy']}")
        
        
        

        if(verbose == 1):
            print(f" Energy of {self.current['energy']}")
        self.time = end_time
        excess_energy = self.current['energy'] - self.storage['energy']
        num_converters = self.current_objs['armmakr']
        conversion_metal = 0
        if excess_energy > 0:
            conversion_metal = min(excess_energy/70, (num_converters * time_to_advance))
            self.current['metal'] += conversion_metal
            self.current['energy'] = min(self.current['energy'], self.storage['energy'])#should expand this to metal storage too to lead to reclaiming math
        
            print(f"There was {excess_energy} to spend and {num_converters} over {time_to_advance} seconds so converted {conversion_metal}")
            return (excess_energy - conversion_metal*70)

        if(verbose == 1):
            print(f"final Energy of {self.current['energy']}/{self.storage['energy']}")
        return 0
        
    def add_production_from_object(self, build_target_name):
        building_object_stats = BUILDING_STATS[build_target_name]
        self.production["energy"] += building_object_stats["energy_income"]
        self.production["metal"] += building_object_stats["metal_income"]
        self.production["bp"] += building_object_stats["bp_income"]
        
        

    def build_object(self, build_target_name, break_time=.5, verbose_message=0):
        build_target = BUILDING_STATS[build_target_name]
        min_build_time = build_target["bp_cost"]/self.production['bp']
        #prep advancement
        build_time = max(
            min_build_time,
            (build_target["metal_cost"]-self.current["metal"])/self.production['metal'],
            (build_target["energy_cost"]-self.current["energy"])/self.energy_production(),
        ) + break_time

        #advance_time
        self.current['metal'] -= build_target['metal_cost']
        self.current['energy'] -= build_target['energy_cost']
        unconverted_energy = self.advance_time(build_target['energy_cost'], build_time)#get resources for buildings we have, update to new time

        #add new building upkeep
        self.current_objs[build_target_name] +=1
        self.add_production_from_object(build_target_name)
        print(self.current_objs)

        if(verbose_message == 1):
            print('built at eff: ', (min_build_time + break_time)/build_time) #to note if we stalled
        return unconverted_energy
    
    def energy_production(self):
        return self.calculate_wind_energy(self.time -1, self.time)+self.production['energy']

    def update_wind(self, curr_tick, min_wind, max_wind):
        """Wind func from recoil engine"""

        if curr_tick == 0:
            self.curr_wind_vec = Vector(max_wind/2, max_wind/2)
        
        wind_dir_timer = curr_tick % TICKS_PER_WIND_UPDATE
        if wind_dir_timer == 0:
            self.old_wind_vec = self.curr_wind_vec
            self.new_wind_vec = self.old_wind_vec

            new_strength = 0.0

            while new_strength == 0.0:
                self.new_wind_vec.x -= (random.uniform(0.0, 1.0) - 0.5) * max_wind
                self.new_wind_vec.y -= (random.uniform(0.0, 1.0) - 0.5) * max_wind
                new_strength = self.new_wind_vec.length()
            
            self.new_wind_vec /= new_strength
            new_strength = clamp(new_strength, min_wind, max_wind)
            self.new_wind_vec *= new_strength

        
        mod = smooth_step(0.0, 1.0, wind_dir_timer / TICKS_PER_WIND_UPDATE)
        self.curr_wind_vec = mix(self.old_wind_vec, self.new_wind_vec, mod)
        cur_wind_strength = clamp(self.curr_wind_vec.normalize(), min_wind, max_wind)

        self.curr_wind_vec *= cur_wind_strength

        return cur_wind_strength

    def simulate_wind(self, sim_time, min_wind, max_wind, display_wind_graph=0):
        """Simulate winds, put values into buckets, graph wind distribution buckets"""
        total_sim_ticks = sim_time * TICKS_PER_SEC

        buckets = {}
        total_wind = 0
        total_ticks = 0
        wind_by_time = {}

        for tick in range(0, total_sim_ticks, TICKS_PER_ITERATION):
            wind_speed = self.update_wind(tick, min_wind, max_wind)
            total_wind += wind_speed
            total_ticks += 1
            wind_speed = round(wind_speed * 2) / 2
            buckets[wind_speed] = buckets.get(wind_speed, 0) + 1
            
            if tick % 450 == 0:
                second = int(tick / 30)
             
                wind_by_time[second] = wind_speed


        if display_wind_graph == 1: 
            print(buckets)
            print(f"avg wind: {total_wind/total_ticks}")
            x_axis = list(buckets.keys())
            y_axis = list(buckets.values())

            plt.bar(x_axis,y_axis)
            plt.show()

        return wind_by_time


    def calculate_wind_energy(self, num_windmills, start_time, end_time, verbose = 0):
        """
        Calculates the total wind energy generated by all windmills over a given time period.

        This function models the wind power as a piecewise linear function based on the
        discrete data points provided in self.wind. It then integrates this function
        over the interval [start_time, end_time] to find the total energy generated
        per windmill. This result is then multiplied by the number of windmills.

        The integration is performed using the trapezoidal rule, which is exact for
        piecewise linear functions.

        Args:
            start_time (float or int): The beginning of the time interval.
            end_time (float or int): The end of the time interval.

        Returns:
            float: The total energy generated by all windmills in the specified period.
                Returns 0 if the time interval is invalid or no windmills are present.
        """
        if start_time >= end_time or 'armwind' not in self.current_objs or self.current_objs['armwind'] == 0:
            return 0

        wind_data = self.wind
        
        # Sort the time points to ensure correct interval lookups
        sorted_times = sorted(wind_data.keys())

        def get_power_at_time(t):
            """
            Calculates the instantaneous power at a specific time 't' using
            linear interpolation between the nearest known data points.
            """
            # If t is outside the defined range, clamp to the nearest boundary value
            if t <= sorted_times[0]:
                return wind_data[sorted_times[0]]
            if t >= sorted_times[-1]:
                return wind_data[sorted_times[-1]]

            # Find the interval [t1, t2] that contains t
            # bisect_left finds the insertion point for t, which gives us the index of the upper bound
            idx = bisect.bisect_left(sorted_times, t)
            t2 = sorted_times[idx]
            t1 = sorted_times[idx - 1]
            
            power1 = wind_data[t1]
            power2 = wind_data[t2]
            
            # If t is exactly on a data point, return its value
            if t == t1:
                return power1
            if t == t2:
                return power2

            # Perform linear interpolation
            # Formula: y = y1 + (x - x1) * (y2 - y1) / (x2 - x1)
            fraction = (t - t1) / (t2 - t1)
            interpolated_power = power1 + fraction * (power2 - power1)
            
            return interpolated_power

        # Create a list of all time points necessary for the integration.
        # This includes the start/end times and any data points that fall between them.
        integration_points = [t for t in sorted_times if start_time < t < end_time]
        integration_points.insert(0, start_time)
        integration_points.append(end_time)
        # Ensure points are unique and sorted
        integration_points = sorted(list(set(integration_points)))
        
        total_energy_per_windmill = 0.0

        # Integrate by summing the areas of the trapezoids formed between consecutive points
        for i in range(len(integration_points) - 1):
            t_start = integration_points[i]
            t_end = integration_points[i+1]
            
            power_start = get_power_at_time(t_start)
            power_end = get_power_at_time(t_end)
            
            # Area of a trapezoid: ( (base1 + base2) / 2 ) * height
            # Here, bases are power values and height is the time duration
            duration = t_end - t_start
            area = (power_start + power_end) / 2.0 * duration
            total_energy_per_windmill += area
            
        total_energy = round(total_energy_per_windmill * num_windmills)
        
        # Print the final result before returning it
        if verbose == 1:
            print(f"From time {start_time} to {end_time} with {num_windmills} windmills you produced {total_energy} energy")
        
        return total_energy


    def simulate_winds_solars_estall(self, sim_time, min_wind, max_wind, max_winds, max_asolar, max_estore, edrain, threshold: float):
        """
        Brute force calculator to simulate all combos of wind,asolar,estore to find cheapest solution that's e positive within threshold % time
        E can go negative in simulation to represent m piling up to be spent
        sim_time: time in sec
        edrain: simulated energy loss per sec
        threshold: % time solution must remain e positive or else disqualified
        """
        total_sim_ticks = sim_time * TICKS_PER_SEC
        edrain_per_tick = edrain / (TICKS_PER_SEC / TICKS_PER_ITERATION)
        total_iteration_ticks = total_sim_ticks / TICKS_PER_ITERATION
        passing_combos = []
        passing = False

        for wind_count in range(1, max_winds+1):
            print(wind_count)
            for asolar_count in range(0,  max_asolar+1):
                if passing:
                    passing = False
                    break
                for estore_count in range(0, max_estore+1):
                    estore_max = estore_count * 6000 + 1000
                    curr_e = estore_max
                    estall_ticks = 0
                    for tick in range(0, total_sim_ticks, TICKS_PER_ITERATION):
                        wind_speed = self.update_wind(tick, min_wind, max_wind)

                        e_income_per_sec = wind_speed * wind_count + ASOLAR_INCOME * asolar_count
                        eincome_per_tick = e_income_per_sec / (TICKS_PER_SEC / TICKS_PER_ITERATION)

                        curr_e -= edrain_per_tick
                        curr_e += eincome_per_tick
                        curr_e = min(curr_e, estore_max)

                        if curr_e <= 0:
                            estall_ticks += 1

                        if estall_ticks > total_iteration_ticks * threshold:
                            break
                        
                        
                    if estall_ticks <= total_iteration_ticks * threshold:
                        passing_combos.append((wind_count, asolar_count, estore_count))
                        passing = True
                        break
        
        return passing_combos


    def simulate_e_stalls(self, sim_time, edrain, min_wind, max_wind, wind_count, asolar_count, estore_count):
        """Simulate % of time combo spends e stalling"""
        total_sim_ticks = sim_time * TICKS_PER_SEC
        edrain_per_tick = edrain / (TICKS_PER_SEC / TICKS_PER_ITERATION)
        total_iteration_ticks = total_sim_ticks / TICKS_PER_ITERATION

        estore_max = estore_count * 6000 + 1000
        curr_e = estore_max
        estall_ticks = 0
        for tick in range(0, total_sim_ticks, TICKS_PER_ITERATION):
            wind_speed = self.update_wind(tick, min_wind, max_wind)

            e_income_per_sec = wind_speed * wind_count + ASOLAR_INCOME * asolar_count
            eincome_per_tick = e_income_per_sec / (TICKS_PER_SEC / TICKS_PER_ITERATION)

            curr_e -= edrain_per_tick
            curr_e += eincome_per_tick
            curr_e = min(curr_e, estore_max)

            if curr_e <= 0:
                estall_ticks += 1

        return estall_ticks / total_iteration_ticks




def project_build_time(sim_obj, build_target_name):
    build_target = BUILDING_STATS[build_target_name]
    min_build_time = build_target["bp_cost"]/sim_obj.production['bp']
    build_time = max(
        min_build_time,
        (build_target["metal_cost"]-sim_obj.current["metal"])/sim_obj.production['metal'],
        (build_target["energy_cost"]-sim_obj.current["energy"])/sim_obj.energy_production(),
    )
    return min_build_time/build_time

def wind_strat(sim):

    
    print(f"M: {sim.current['metal']} :: E:{sim.current['energy']}/{sim.storage['energy']}")
    print(f"MPS: {sim.production['metal']} EPS: {sim.production['energy']}")
    #if we can build a nano, do
    bp_time = project_build_time(sim, 'armnanotc')
    #print("bp%", bp_time)
    if bp_time > .99:
        unconverted_energy = sim.build_object('armnanotc')
        print('Built armnanotc')
    else: #else if building a wind would make us overflow
        wind_clone = copy.copy(sim)
        unconverted_energy = wind_clone.build_object("armwind")
        #print('theoretical unconverted E result', unconverted_energy)
        if unconverted_energy > 0:
            print('Built armmakr')
            unconverted_energy =  sim.build_object('armmakr')
        else :
            print('Built armwind')
            unconverted_energy =  sim.build_object('armwind')

    return sim


def asol_strat(sim):
    sim.build_object("armasolar")
    return sim



def build_E_via_strategy(self, strategy):
    strategy()

def build_forward_simulator(sim, etarget, min_wind=0, max_wind=16, max_time = 220, strategy = wind_strat, max_winds = 1000, max_asolar = 100, max_estore = 10):

    last_resources = {}
    last_time = 0
    sim.wind = sim.simulate_wind(max_time*30,min_wind,max_wind)
    while sim.production['energy'] < etarget and sim.time < max_time:
        last_time = sim.time
        last_resources = sim.current
        sim = wind_strat(sim)
    return sim


def find_optimal_e_solution(sim_time, min_wind, max_wind, max_winds, max_asolar, max_estore, edrain, threshold):
    sim = Simulator()

    #6walk settings
    sim.time = 147
    sim.production['bp'] = 380
    sim.production['metal'] = 13
    sim.production['energy'] = 110

    sim.current['metal'] = 732 #+590 vehicle factory
    sim.current['energy'] = 242

    #res = sim.simulate_winds_solars_estall(sim_time=sim_time, min_wind=min_wind, max_wind=max_wind, max_winds=max_winds, max_asolar=max_asolar, max_estore=max_estore, edrain=edrain, threshold=threshold)
    res = build_forward_simulator(sim, 1000,0,16)

    print(sim.wind)


    values =  []
    #for wind, asolar, estore in res:
    #    value = wind * WINDMILL_COST + asolar * ASOLAR_COST + estore * ESTORE_COST
    #    values.append((value, wind, asolar, estore))

    sorted_list = sorted(values, key=lambda x: x[0])
    return sorted_list


def calc_time_spent_e_positive(sim_time, edrain, min_wind, max_wind, wind_count, asolar_count, estore_count):
    sim = Simulator()
    res = sim.simulate_e_stalls(sim_time, edrain, min_wind, max_wind, wind_count, asolar_count, estore_count)
    time_ratio_pos_e = 1 - res
    print(f"% Time Positive E: {time_ratio_pos_e}")
    return time_ratio_pos_e


find_optimal_e_solution(SIMULATION_TIME,0,16,1500, 0, 10, 1000, 50)

#Simulation time in seconds
#SIMULATION_TIME = 1000000
#TICKS_PER_SEC = 30
#TICKS_PER_WIND_UPDATE = 450
#TICKS_PER_ITERATION = 2)


# Generate Heatmap for estall duration
# array_2d = [[0 for _ in range(21)] for _ in range(10)]        

# for min_wind in range(0, 10):
#     for max_wind in range(10,21):
#         sim = Simulator()
#         res = sim.simulate_wind_drop(1000000, min_wind,  max_wind)
#         array_2d[min_wind][max_wind] = res
# plt.imshow(array_2d)
# plt.xlim(10,20)
# plt.colorbar() 
# plt.show()


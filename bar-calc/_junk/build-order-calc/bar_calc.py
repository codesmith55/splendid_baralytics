import copy
import math

class BuildingType:
    def __init__(self, name, metal_cost, energy_cost, buildpower_cost, energy_income=0, metal_income=0):
        self.name = name
        self.metal_cost = metal_cost
        self.energy_cost = energy_cost
        self.buildpower_cost = buildpower_cost
        self.energy_income = energy_income
        self.metal_income = metal_income

class UnitType:
    def __init__(self, name, metal_cost=0, energy_cost=0, buildpower_cost=0, 
                 metal_income=0, energy_income=0, buildpower_income=0):
        self.name = name
        self.metal_cost = metal_cost
        self.energy_cost = energy_cost
        self.buildpower_cost = buildpower_cost
        self.metal_income = metal_income
        self.energy_income = energy_income
        self.buildpower_income = buildpower_income

# Define building and unit types
object_types = {
    'Wind': BuildingType('Wind', 40, 175, 1600, 10, 0),
    'Solar': BuildingType('Solar', 155, 0, 2600, 20, 0),
    'Mex': BuildingType('Mex', 50, 500, 1800, -3, 1.8),
    'AMex': BuildingType('AMex', 620, 7700, 14900, 0, 7.3),
    'EConverter': BuildingType('EConverter', 1, 1150, 2600, 0, 0),
    'Commander': UnitType('Commander', metal_income=2, energy_income=25, buildpower_income=300),
    'BotFactory': UnitType('BotFactory', 620, 1200, 6500, buildpower_income=100),
    'BotWorker': UnitType('BotWorker', 110, 1600, 3450, buildpower_income=80),
    'Pawn': UnitType('Pawn', 52, 870, 1420, buildpower_income=0),
    'Mace': UnitType('Mace', 130, 1300, 2200, buildpower_income=0),
    'Rocko': UnitType('Rocko', 120, 1000, 2010, buildpower_income=0),
    'Cent': UnitType('Cent', 270, 3100, 4200, buildpower_income=0),
    'Laz': UnitType('Laz', 130, 1400, 2800, buildpower_income=0),
    'Thug': UnitType('Mace', 140, 1150, 2100, buildpower_income=0),

}
        
class Environment:

    def __init__(self, time=3, metal=1000, metal_per_second=2, max_metal=1000, 
                 energy=1000, max_energy=1000, energy_per_second=25, 
                 builders=None, buildings=None, construction_history=None, number_converters=0):
        self.time = time
        self.metal = metal
        self.metal_per_second = metal_per_second
        self.max_metal = max_metal
        self.energy = energy
        self.energy_per_second = energy_per_second
        self.max_energy = max_energy
        self.builders = builders if builders is not None else ['Commander']
        self.buildings = buildings if buildings is not None else []
        self.construction_history = construction_history if construction_history is not None else []
        self.number_converters = number_converters
    ###

    def copy(self):
        return Environment(
            time=self.time,
            metal=self.metal,
            metal_per_second=self.metal_per_second,
            max_metal=self.max_metal,
            energy=self.energy,
            max_energy=self.max_energy,
            energy_per_second=self.energy_per_second,
            builders=copy.deepcopy(self.builders),
            buildings=copy.deepcopy(self.buildings),
            construction_history=copy.deepcopy(self.construction_history),
            number_converters=self.number_converters
        )

    def optimal_build_power(self, object_name):
        target = object_types[object_name]
        return (target.buildpower_cost * self.metal_per_second ) / target.metal_cost

    def optimal_energy_withbp(self, object_name, buildpower_total):
        target = object_types[object_name]
        required_energy = target.energy_cost/(target.buildpower_cost / (buildpower_total))
        return required_energy
    
    def req_build_power(self, object_name):
        target = object_types[object_name]
        metal_mult = self.metal/target.metal_cost
        energy_mult = self.energy/target.energy_cost
        
        min_build_time = 0
        min_mult = min(metal_mult, energy_mult)
            
        if metal_mult > 1 and energy_mult > 1:
            return self.get_total_buildpower()*min_mult

        else :
            return min(
                (target.buildpower_cost * self.metal_per_second ) / (target.metal_cost - self.metal),
                (target.buildpower_cost * self.energy_per_second ) / (target.energy_cost - self.energy)
            )       

        return 

    def req_energy_withbp(self, object_name, buildpower_total):
        target = object_types[object_name]
        required_energy = target.energy_cost/(target.buildpower_cost / (buildpower_total))
        return required_energy

    def get_total_buildpower(self):
        total = 0
        for builder in self.builders:
            unit_type = object_types[builder]
            total += unit_type.buildpower_income
        return total
    
    def calculate_build_times(self, building_name, worker_name = "", min_add_time=1, buildpower = 0):
        object_name = building_name
        isWorker = 0

        if buildpower == 0:
            buildpower = self.get_total_buildpower()

        if worker_name != "":
            objName = worker_name
            isWorker = 1

        obj = object_types[object_name]

        # Calculate buildpower build time
        buildpower_buildtime = (obj.buildpower_cost / buildpower) + min_add_time
        
        # Calculate energy build time
        if obj.energy_cost <= self.energy:
            energy_buildtime = 0
        else:
            energy_needed = obj.energy_cost - self.energy
            energy_buildtime = energy_needed / self.energy_per_second
        
        # Calculate metal build time
        if obj.metal_cost <= self.metal:
            metal_buildtime = 0
        else:
            metal_needed = obj.metal_cost - self.metal
            metal_buildtime = metal_needed / self.metal_per_second
        
        # The actual build time is the maximum of these
        build_time = max(buildpower_buildtime, energy_buildtime, metal_buildtime)
        
        return {
            'buildpower_time': buildpower_buildtime,
            'energy_time': energy_buildtime,
            'metal_time': metal_buildtime,
            'total_time': build_time
        }
    
    def construct_object(self, construct_object, theoretical = 0, verbose = 1):
        if construct_object not in object_types:
            print(f"Unknown building type: {construct_object}")
            return False

        curEnv = self if theoretical == 0 else self.copy()
        
        building = object_types[construct_object]
        build_times = curEnv.calculate_build_times(construct_object)
        build_time = build_times['total_time']
        
        if(build_times['energy_time'] > build_times['buildpower_time']):
            print(f"Alert:: Energy Stall")
            
        if(build_times['metal_time'] > build_times['buildpower_time']):
            print(f"Warning:: Metal Stall")
            
        if(construct_object == "EConverter"):
            self.number_converters +=1

        print(f"Building {construct_object} will take {build_time:.2f}/{build_times['buildpower_time']:.2f} seconds")
        
        if verbose == 1:
            print(f" - Energy time: {build_times['energy_time']:.2f}s")
            print(f" - Metal time: {build_times['metal_time']:.2f}s")
        
        # Deduct costs (they should be available now after time advance)
        curEnv.metal -= building.metal_cost
#        curEnv.energy -= building.energy_cost
        
        # Advance time and update resources
        curEnv.advance_time(build_time, building.energy_cost/build_time)
        
        # Add the building/unit and record construction time
        if construct_object in ['Commander', 'BotWorker', 'BotFactory']:
            curEnv.builders.append(construct_object)
        else:
            curEnv.buildings.append(construct_object)
        curEnv.construction_history.append((construct_object, curEnv.time))
        
        # Update income rates
        curEnv.metal_per_second += building.metal_income
        curEnv.energy_per_second += building.energy_income
        
        print(f"Completed {construct_object} at time {curEnv.time:.2f}")
        print(f"Current resources: Metal={curEnv.metal:.2f}, Energy={curEnv.energy:.2f}")
        print(f"Income rates: Metal={curEnv.metal_per_second:.2f}/s, Energy={curEnv.energy_per_second:.2f}/s")
        return True
    
    def advance_time(self, delta_time, eps = 0, e_conv_mult=.5):
        if delta_time <= 0:
            return
        
        # Calculate resource gains
        metal_gain = self.metal_per_second * delta_time
        energy_gain = (self.energy_per_second - eps) * delta_time
        
        print(energy_gain)
        # Apply gains with caps
        self.metal = min(self.metal + metal_gain, self.max_metal)
        self.energy = self.energy + energy_gain

        excess_energy = self.energy+energy_gain-e_conv_mult*self.max_energy
        
        if excess_energy > 0:
            if self.number_converters*70* delta_time > excess_energy:#too many converters
                metal_converted = math.floor(excess_energy/70)
                self.metal += metal_converted
                self.energy -= metal_converted*70
            else: #too much energy, not enough conversion, so converters * time                
                self.metal += self.number_converters * delta_time
                self.energy -= self.number_converters * delta_time

        self.energy = min(self.energy, self.max_energy)
        
        # Advance time
        self.time += delta_time
    
    def print_status(self):
        print("\nCurrent Environment Status:")
        print(f"Time: {self.time:.2f} seconds")
        print(f"Resources: Metal={self.metal:.2f}/{self.max_metal}, Energy={self.energy:.2f}/{self.max_energy}")
        print(f"Income: Metal={self.metal_per_second:.2f}/s, Energy={self.energy_per_second:.2f}/s")
        print(f"Builders: {len(self.builders)} ({', '.join(self.builders)})")
        print(f"Buildings: {len(self.buildings)} ({', '.join(self.buildings) if self.buildings else 'None'})")
        print(f"Total Buildpower: {self.get_total_buildpower()}")
        print("Construction History:")
        for obj, time in self.construction_history:
            print(f" - {obj} at {time:.2f}s")



    def build_with_priorities(self, priority_list, endTime = 100):
        """Build objects according to priority list, avoiding stalls when possible"""
        while self.time < endTime:
            built_something = False
            all_would_stall = True
            
            for obj_name in priority_list:
                if obj_name not in object_types:
                    print(f"Warning: Unknown object type {obj_name} in priority list")
                    continue
                    
                obj = object_types[obj_name]
                build_times = self.calculate_build_times(obj_name)
                
                # Check if this object would stall
                would_stall = (build_times['energy_time'] > build_times['buildpower_time'] or 
                            build_times['metal_time'] > build_times['buildpower_time'])
                
                if not would_stall:
                    all_would_stall = False
                    if self.construct_object(obj_name):
                        built_something = True
                        break  # Successfully built something, restart priority list
            
            if not built_something:
                if all_would_stall:
                    # All options would stall, build a Wind
                    print("All priority options would stall, building Wind instead")
                    if not self.construct_object('Wind'):
                        print("Couldn't even build a Wind, stopping construction")
                        break
                else:
                    # We've gone through all options and none were buildable right now
                    # Wait a bit and try again
                    print("No priority objects buildable right now, waiting...")
                    self.advance_time(1)
    


def build_objects_in_order(env, objects_to_build):
    """Build objects in the specified order for the given environment"""
    for obj in objects_to_build:
        success = env.construct_object(obj)
        if not success:
            print(f"Failed to build {obj}, stopping construction sequence")
            break
    return env

def compare_environments(env1, env2):
    """Compare two environments and have the younger one build Winds until it catches up"""
    if env1.time < env2.time:
        younger, older = env1, env2
    else:
        younger, older = env2, env1
    
    print(f"\nYounger environment (time={younger.time:.2f}) will build Winds until it catches up to older environment (time={older.time:.2f})")
    
    while younger.time < older.time and younger.construct_object('Wind'):
        # Continue building Winds until we can't or we catch up
        pass
    
    print("\nComparison Results:")
    print(f"Younger environment final time: {younger.time:.2f}")
    print(f"Older environment time: {older.time:.2f}")
    print("\nYounger environment status:")
    younger.print_status()
    print("\nOlder environment status:")
    older.print_status()


#def efficient_wind_order(env, priority_list, endTime = 100):
def calc_build_towards_object(env:Environment, target_name:str, acceptable_list:list, depth:int=1):
    build_times = env.calculate_build_times(target_name)
    target = object_types[target_name]
    req_bps = round(env.optimal_build_power(target_name))
    req_eps = round(env.req_energy_withbp(target_name, req_bps))

    required_res = {
        'bps': req_bps,
        'eps': req_eps
    }
    
    print("mps: ", env.metal_per_second)
    print("target: ", target_name)
    print("required bps: ", required_res['bps'])
    print("required eps: ", required_res['eps'])

    eCurMult = round(env.energy_per_second/req_eps,2)
    bpCurMult = round(env.get_total_buildpower()/req_bps,2)

    print ("eCurMult:", eCurMult)
    print ("bpCurMult:", bpCurMult)
    state = 0

    if eCurMult < 1 and target_name != "Wind":#fixes inf recursion, if we can't afford wind, hard code solar rule
        state = 1
        print("towards " + target_name + " build more energy")
        if calc_build_towards_object(env, 'Wind', 'Wind') == 2:
            print(":: wind")
        else :
            print(":: solar")

    if bpCurMult >= 1 and eCurMult >= 1:#Success:: build target
        state = 2

    if bpCurMult >= 1 and eCurMult < 1:#Fail:: Build Wind
        state = 3


    return state
    



    
     
if __name__ == "__main__":
    print("=== Environment 1 ===")
    envSolar = Environment()
#    build_objects_in_order(envSolar, ['Mex', 'Mex', 'Solar', 'Mex', 'Solar', 'BotFactory', 'Wind', 'Wind', 'Wind', 'Wind', 'Mex','Wind', 'Wind', 'Mex','Wind', 'Wind', 'Mex'])
    build_objects_in_order(envSolar, ['Mex', 'Mex', 'Solar', 'Mex', 'Solar', 'BotFactory', 'Mex', 'Mex'])
    envSolar.print_status()

    envSolarPlusOne = calc_build_towards_object(envSolar, 'Mex', ['Wind', 'Solar', 'EConverter'], 2)
    
#    print("\n=== Environment 2 ===")
#    envWind = Environment()
#    build_objects_in_order(envWind, ['Mex', 'Mex', 'Wind', 'Wind', 'Mex', 'BotFactory', 'Wind', 'BotWorker'])
#    envWind.print_status()

#    priority_list = ['BotWorker', 'Wind']
#    test1 = envSolar.copy()
#    test1.time=77
#    test1.metal=164
#    test1.energy=855
#    test1.metal_per_second=8.4
##    test1.energy_per_second=85
#    test1.print_status()
#    build_objects_in_order(test1, ['Wind', 'EConverter', 'Wind', 'Wind', 'EConverter'])

 #   print("\n=== Test Environment ===")
 #   test1.print_status()


  ##  priority_list = ['BotWorker', 'Wind']
   # test1.build_with_priorities(priority_list)
    #env2.print_status()
    
    # Compare the two environments
#    compare_environments(env1, env2)
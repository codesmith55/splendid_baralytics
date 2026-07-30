def calculate_build_sequence(builds, current_metal, metal_income, current_energy, energy_income, current_build_power):
    """
    Calculate a sequence of dependent builds, updating resources after each build.
    """
    total_time = 0
    results = []
    
    for build in builds:
        # Calculate build time and resource changes
        metal_time = max(0, (build['metal_cost'] - current_metal) / metal_income)
        energy_time = max(0, (build['energy_cost'] - current_energy) / energy_income)
        build_time = build['build_power_cost'] / current_build_power
        
        build_duration = max(metal_time, energy_time, build_time)
        
        # Calculate resource accumulation during build
        metal_gained = metal_income * build_duration
        energy_gained = energy_income * build_duration
        
        # Update resources after build
        final_metal = current_metal + metal_gained - build['metal_cost']
        final_energy = current_energy + energy_gained - build['energy_cost']
        
        build_result = {
            'name': build['name'],
            'build_time': build_duration,
            'start_time': total_time,
            'metal': {
                'initial': current_metal,
                'gained': metal_gained,
                'spent': build['metal_cost'],
                'final': final_metal
            },
            'energy': {
                'initial': current_energy,
                'gained': energy_gained,
                'spent': build['energy_cost'],
                'final': final_energy
            },
            'build_power': {
                'available': current_build_power,
                'required': build['build_power_cost']
            }
        }
        
        results.append(build_result)
        
        # Update current resources and income for next build
        current_metal = final_metal
        current_energy = final_energy
        metal_income += build.get('metal_income', 0)
        energy_income += build.get('energy_income', 0)
        current_build_power += build.get('build_power_income', 0)
        
        total_time += build_duration
    
    return results, total_time

# Initial state
current_metal = 816
metal_income = 13
current_energy = 1151
energy_income = 261
current_build_power = 740
current_time = 216

# Define builds with dependencies
builds = [
    {
        'name': 'armAlab',
        'metal_cost': 2900,
        'energy_cost': 15000,
        'build_power_cost': 16200,
        'metal_income': 0,
        'energy_income': 0,
        'build_power_income': 0
    },
    {
        'name': 'armAck',
        'metal_cost': 430,
        'energy_cost': 6900,
        'build_power_cost': 9500,
        'metal_income': 0,
        'energy_income': 0,
        'build_power_income': 180
    }
]

# Add 6 armAmex builds
for i in range(6):
    builds.append({
        'name': f'armAmex_{i+1}',
        'metal_cost': 640,
        'energy_cost': 8100,
        'build_power_cost': 14100,
        'metal_income': 5.4,
        'energy_income': 0,
        'build_power_income': 0
    })

# Calculate the entire build sequence
results, total_time = calculate_build_sequence(
    builds,
    current_metal,
    metal_income,
    current_energy,
    energy_income,
    current_build_power
)

# Print results
print(f"Total build sequence time: {total_time:.2f} seconds\n")

for result in results:
    print(f"{result['name']}:")
    print(f"  Build time: {result['build_time']:.2f} seconds")
    print(f"  Starts at: {result['start_time']:.2f} seconds")
    print(f"  Metal: {result['metal']['initial']:.1f} → {result['metal']['final']:.1f}")
    print(f"  Energy: {result['energy']['initial']:.1f} → {result['energy']['final']:.1f}")
    print(f"  Build Power used: {result['build_power']['required']:.1f}/{result['build_power']['available']:.1f}")
    print()

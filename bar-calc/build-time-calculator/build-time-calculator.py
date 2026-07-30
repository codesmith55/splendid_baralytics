def calculate_build_time(build, current_state):
    """Calculate time for a single build including resource wait time."""
    metal_wait = max(0, (build['metal_cost'] - current_state['metal']) / current_state['metal_income'])
    energy_wait = max(0, (build['energy_cost'] - current_state['energy']) / current_state['energy_income'])
    wait_time = max(metal_wait, energy_wait)
    build_time = build['build_power_cost'] / current_state['build_power']
    
    return wait_time, build_time

def update_state_after_build(state, build, wait_time, build_time):
    """Update resource state after completing a build."""
    # Accumulate resources during wait time
    state['metal'] += wait_time * state['metal_income']
    state['energy'] += wait_time * state['energy_income']
    
    # Accumulate resources during build time
    state['metal'] += (build_time * state['metal_income']) - build['metal_cost']
    state['energy'] += (build_time * state['energy_income']) - build['energy_cost']
    
    # Update income rates
    state['metal_income'] += build.get('metal_income', 0)
    state['energy_income'] += build.get('energy_income', 0)
    state['build_power'] += build.get('build_power_income', 0)
    state['time'] += wait_time + build_time
    return state

def find_optimal_winds(target, current_state, max_winds=5):
    """Find optimal number of winds to build before target."""
    wind = {
        'metal_cost': 37,
        'energy_cost': 175,
        'build_power_cost': 1603,
        'energy_income': 11.9
    }
    
    best_time = float('inf')
    best_winds = 0
    best_final_state = None
    
    for num_winds in range(max_winds + 1):
        temp_state = dict(current_state)
        total_time = 0
        
        # Build winds
        for _ in range(num_winds):
            wait_time, build_time = calculate_build_time(wind, temp_state)
            total_time += wait_time + build_time
            temp_state = update_state_after_build(temp_state, wind, wait_time, build_time)
        
        # Build target
        wait_time, build_time = calculate_build_time(target, temp_state)
        total_time += wait_time + build_time
        
        if total_time < best_time:
            best_time = total_time
            best_winds = num_winds
            best_final_state = dict(temp_state)
        elif total_time > best_time + 5:  # Stop if getting worse
            break
    
    return best_winds, best_time, best_final_state

def optimized_build_sequence():
    # Initial state
    state = {
        'metal': 816,
        'metal_income': 13,
        'energy': 1151,
        'energy_income': 261,
        'build_power': 740, 
        'time': 216
    }
    
    total_time = 0
    sequence = []
    
    # Define buildings
    armAlab = {
        'name': 'armAlab',
        'metal_cost': 2900,
        'energy_cost': 15000,
        'build_power_cost': 16200
    }
    
    armAck = {
        'name': 'armAck',
        'metal_cost': 430,
        'energy_cost': 6900,
        'build_power_cost': 9500,
        'build_power_income': 180
    }
    
    armAmex = {
        'name': 'armAmex',
        'metal_cost': 640,
        'energy_cost': 8100,
        'build_power_cost': 14100,
        'metal_income': 5.4
    }
    
    wind = {
        'name': 'wind',
        'metal_cost': 37,
        'energy_cost': 175,
        'build_power_cost': 1603,
        'energy_income': 11.9
    }
    
    # Phase 1: Build armAlab
    print(f"\nPhase 1 - Building armAlab")
    print(f"Current state: Time={state['time']:.1f}")
    print(f"Current state: Metal={state['metal']:.1f} (+{state['metal_income']}/s)")
    print(f"              Energy={state['energy']:.1f} (+{state['energy_income']}/s)")
    print(f"              Build Power={state['build_power']}")
    
    optimal_winds, phase_time, new_state = find_optimal_winds(armAlab, state)
    print(f"Optimal winds before armAlab: {optimal_winds}")
    
    # Build optimal winds
    for i in range(optimal_winds):
        wait_time, build_time = calculate_build_time(wind, state)
        total_time += wait_time + build_time
        state = update_state_after_build(state, wind, wait_time, build_time)
        sequence.append({
            'name': f'wind_{i+1}',
            'start_time': total_time - build_time,
            'wait_time': wait_time,
            'build_time': build_time
        })
    
    # Build armAlab
    wait_time, build_time = calculate_build_time(armAlab, state)
    total_time += wait_time + build_time
    state = update_state_after_build(state, armAlab, wait_time, build_time)
    sequence.append({
        'name': 'armAlab',
        'start_time': total_time - build_time,
        'wait_time': wait_time,
        'build_time': build_time
    })
    
    # Phase 2: Build armAck
    print(f"\nPhase 2 - Building armAck")
    print(f"Current state: Time={state['time']:.1f}")
    print(f"Current state: Metal={state['metal']:.1f} (+{state['metal_income']}/s)")
    print(f"              Energy={state['energy']:.1f} (+{state['energy_income']}/s)")
    print(f"              Build Power={state['build_power']}")
    
    optimal_winds, phase_time, new_state = find_optimal_winds(armAck, state)
    print(f"Optimal winds before armAck: {optimal_winds}")
    
    # Build optimal winds
    for i in range(optimal_winds):
        wait_time, build_time = calculate_build_time(wind, state)
        total_time += wait_time + build_time
        state = update_state_after_build(state, wind, wait_time, build_time)
        sequence.append({
            'name': f'wind_{optimal_winds+i+1}',
            'start_time': total_time - build_time,
            'wait_time': wait_time,
            'build_time': build_time
        })
    
    # Build armAck
    wait_time, build_time = calculate_build_time(armAck, state)
    total_time += wait_time + build_time
    state = update_state_after_build(state, armAck, wait_time, build_time)
    sequence.append({
        'name': 'armAck',
        'start_time': total_time - build_time,
        'wait_time': wait_time,
        'build_time': build_time
    })
    
    # Phase 3: Build 6 armAmex
    print(f"\nPhase 3 - Building 6 armAmex")
    print(f"Current state: Time={state['time']:.1f}")
    print(f"Current state: Metal={state['metal']:.1f} (+{state['metal_income']}/s)")
    print(f"              Energy={state['energy']:.1f} (+{state['energy_income']}/s)")
    print(f"              Build Power={state['build_power']}")
    
    optimal_winds, phase_time, new_state = find_optimal_winds(armAmex, state)
    print(f"Optimal winds before armAmex sequence: {optimal_winds}")
    
    # Build optimal winds
    for i in range(optimal_winds):
        wait_time, build_time = calculate_build_time(wind, state)
        total_time += wait_time + build_time
        state = update_state_after_build(state, wind, wait_time, build_time)
        sequence.append({
            'name': f'wind_{optimal_winds+i+1}',
            'start_time': total_time - build_time,
            'wait_time': wait_time,
            'build_time': build_time
        })
    
    # Build 6 armAmex
    for i in range(6):
        wait_time, build_time = calculate_build_time(armAmex, state)
        total_time += wait_time + build_time
        state = update_state_after_build(state, armAmex, wait_time, build_time)
        sequence.append({
            'name': f'armAmex_{i+1}',
            'start_time': total_time - build_time,
            'wait_time': wait_time,
            'build_time': build_time
        })
        print(f"armAmex_{i+1} completed at {total_time:.1f}s")
        print(f"New state: Metal={state['metal']:.1f} (+{state['metal_income']}/s)")
        print(f"          Energy={state['energy']:.1f} (+{state['energy_income']}/s)")
        print(f"          Build Power={state['build_power']}")
    
    return sequence, total_time

# Run the optimized sequence
sequence, total_time = optimized_build_sequence()

print(f"\nFinal build sequence:")
for build in sequence:
    print(f"{build['name']}:")
    print(f"  Start time: {build['start_time']:.1f}s")
    print(f"  Wait time: {build['wait_time']:.1f}s")
    print(f"  Build time: {build['build_time']:.1f}s")
    print()

print(f"Total time to complete sequence: {total_time:.1f} seconds")
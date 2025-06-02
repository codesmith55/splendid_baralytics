#!/bin/bash
# Rigorous error checking
set -euo pipefail

# --- Configuration ---
# Directory to store profiles. Using a custom name to avoid conflicts.
PROFILES_DIR="$HOME/.bash_history_profiles"
mkdir -p "$PROFILES_DIR" # Ensure the base directory for profiles exists

# --- Function to display help ---
show_help() {
    echo "Usage: $(basename "$0")"
    echo "Manages profiles for storing selected bash history commands."
    echo
    echo "Workflow:"
    echo "1. You will be prompted to select an existing profile or create a new one."
    echo "2. The script will then display the last 50 lines of your command history and the total number of lines available."
    echo "3. You can then enter your selection criteria to specify which history lines to save to the chosen profile."
    echo
    echo "Input format for selecting lines (comma-separated):"
    echo "  - Single line number: e.g., '500' (selects history line 500)"
    echo "  - Range of lines: e.g., '510-515' (selects lines 510 through 515)"
    echo "  - Keyword search: e.g., 'mykeyword' (selects lines containing 'mykeyword')"
    echo "  - Keyword search with context: e.g., 'another_keyword+2' (selects lines containing 'another_keyword' plus 2 lines before and 2 lines after each match)"
    echo "  - Combinations: e.g., '500, 510-515, mykeyword+1'"
    echo
    echo "Commands are saved to a '.sh' file within the profile's directory (e.g., ~/.bash_history_profiles/my_profile/commands.sh)."
    echo "This script attempts to avoid adding duplicate commands or the command that invoked the script itself."
}

# --- Argument Parsing for Help ---
if [[ "$1" == "-h" || "$1" == "--help" ]]; then
    show_help
    exit 0
fi

# --- Profile Management ---
echo "Available profiles:"
profiles=() # Array to hold names of existing profiles
i=1         # Counter for listing profiles

# Check if the profiles directory exists and is not empty
if [ -d "$PROFILES_DIR" ] && [ "$(ls -A "$PROFILES_DIR")" ]; then
    # Loop through subdirectories (profiles)
    for profile_path in "$PROFILES_DIR"/*/; do
        # Ensure it's a directory before processing
        if [ -d "$profile_path" ]; then
            profile_name=$(basename "$profile_path")
            echo "  $i) $profile_name"
            profiles+=("$profile_name")
            i=$((i + 1))
        fi
    done
fi

if [ ${#profiles[@]} -eq 0 ]; then
    echo "  No profiles found."
fi
echo "  N) Create a new profile"

read -r -p "Choose a profile number or 'N' for new: " profile_choice

selected_profile_name=""

# Process user's profile choice
if [[ "$profile_choice" =~ ^[0-9]+$ ]] && [ "$profile_choice" -ge 1 ] && [ "$profile_choice" -le "${#profiles[@]}" ]; then
    selected_profile_name="${profiles[$((profile_choice - 1))]}"
    echo "Selected profile: $selected_profile_name"
elif [[ "$profile_choice" == "N" || "$profile_choice" == "n" ]]; then
    read -r -p "Enter new profile name: " new_profile_name
    # Validate new profile name
    if [ -z "$new_profile_name" ]; then
        echo "Error: Profile name cannot be empty. Exiting."
        exit 1
    fi
    if [[ "$new_profile_name" =~ [/] ]]; then # Slashes are not allowed in directory names here
        echo "Error: Profile name cannot contain slashes. Exiting."
        exit 1
    fi
    selected_profile_name="$new_profile_name"
    mkdir -p "$PROFILES_DIR/$selected_profile_name" # Create the new profile directory
    echo "Created and selected profile: $selected_profile_name"
else
    echo "Error: Invalid choice. Exiting."
    exit 1
fi

# Define the path to the file where commands for the selected profile will be stored
PROFILE_CMDS_FILE="$PROFILES_DIR/$selected_profile_name/commands.sh"
touch "$PROFILE_CMDS_FILE" # Ensure the command file exists

# --- History Display ---
echo -e "\n--- Last 50 History Lines ---"

# Unset HISTTIMEFORMAT for consistent `history` command output during script execution
# The original HISTTIMEFORMAT will be restored when the script exits (if it was set).
original_histtimeformat="${HISTTIMEFORMAT-}" # Save original value, or empty if not set
unset HISTTIMEFORMAT

# Read all history lines into an array. Each element is typically "  NUM  COMMAND".
# `mapfile` (or `readarray`) is a bash 4+ feature.
mapfile -t full_history_lines < <(history)

# Restore original HISTTIMEFORMAT if it was set
if [ -n "$original_histtimeformat" ]; then
    export HISTTIMEFORMAT="$original_histtimeformat"
fi


total_history_lines=${#full_history_lines[@]}
echo "Total history lines available (approximate, from current session): $total_history_lines"

# Display the last 50 lines (or fewer if history is short)
# Calculate the starting index for displaying the last 50 lines
display_start_index=$((total_history_lines > 50 ? total_history_lines - 50 : 0))

echo "Displaying lines from approx. history entry # relevant to current session:"
for ((idx = display_start_index; idx < total_history_lines; idx++)); do
    printf "%s\n" "${full_history_lines[$idx]}" # `printf` is safer than `echo` for arbitrary strings
done
echo "--------------------------"

# --- Get User Input for Line Selection ---
echo -e "\nEnter lines/ranges to grab (e.g., 123, 450-455, keyword+2). Separate multiple entries with commas."
read -r -p "Selection: " user_selection_str

if [ -z "$user_selection_str" ]; then
    echo "No selection made. Exiting."
    exit 0
fi

# --- Process Input and Select Lines ---
# Associative array to store unique history line numbers that should be added
declare -A history_line_numbers_to_add_map

# Map to store actual commands by their history line number for easy retrieval
declare -A history_map_num_to_cmd
max_hist_num=0 # Keep track of the maximum history number found

# Populate history_map_num_to_cmd and find max_hist_num
for hist_line_full_str in "${full_history_lines[@]}"; do
    # Regex to extract number and command: matches leading spaces, digits, spaces, then the command
    if [[ "$hist_line_full_str" =~ ^[[:space:]]*([0-9]+)[[:space:]]+(.*)$ ]]; then
        num="${BASH_REMATCH[1]}"
        cmd="${BASH_REMATCH[2]}"
        history_map_num_to_cmd["$num"]="$cmd"
        if (( num > max_hist_num )); then max_hist_num=$num; fi
    fi
done

# Split user input by comma to process each selection criterion
IFS=',' read -r -a selection_criteria <<< "$user_selection_str"

for selection_item in "${selection_criteria[@]}"; do
    selection_item_trimmed=$(echo "$selection_item" | xargs) # Trim leading/trailing whitespace

    if [[ "$selection_item_trimmed" =~ ^[0-9]+$ ]]; then # Criterion is a single line number
        history_line_numbers_to_add_map["$selection_item_trimmed"]=1
    elif [[ "$selection_item_trimmed" =~ ^([0-9]+)-([0-9]+)$ ]]; then # Criterion is a range (e.g., 10-20)
        range_start="${BASH_REMATCH[1]}"
        range_end="${BASH_REMATCH[2]}"
        if [ "$range_start" -le "$range_end" ]; then
            for ((j = range_start; j <= range_end; j++)); do
                history_line_numbers_to_add_map["$j"]=1
            done
        else
            echo "Warning: Invalid range '$selection_item_trimmed' (start > end). Skipping."
        fi
    # Criterion is keyword-based (e.g., 'docker' or 'git+2')
    elif [[ "$selection_item_trimmed" =~ ^([^[:space:]+]+)\+([0-9]+)$ ]]; then # keyword+X
        keyword="${BASH_REMATCH[1]}"
        extender="${BASH_REMATCH[2]}"
        # Search for keyword in commands
        for hist_line_full_str in "${full_history_lines[@]}"; do
            if [[ "$hist_line_full_str" =~ ^[[:space:]]*([0-9]+)[[:space:]]+(.*)$ ]]; then
                current_hist_num="${BASH_REMATCH[1]}"
                current_cmd="${BASH_REMATCH[2]}"
                if [[ "$current_cmd" == *"$keyword"* ]]; then # Keyword found in command
                    # Add lines from (current_hist_num - extender) to (current_hist_num + extender)
                    for ((k = current_hist_num - extender; k <= current_hist_num + extender; k++)); do
                        if [ "$k" -ge 1 ] && [[ -v history_map_num_to_cmd["$k"] ]]; then # Check if line number is valid
                            history_line_numbers_to_add_map["$k"]=1
                        fi
                    done
                fi
            fi
        done
    elif [[ "$selection_item_trimmed" =~ ^([^[:space:]+]+)$ ]]; then # keyword (no +X extender)
        keyword="${BASH_REMATCH[1]}"
        extender=0 # Extender is 0 for plain keyword search
         for hist_line_full_str in "${full_history_lines[@]}"; do
            if [[ "$hist_line_full_str" =~ ^[[:space:]]*([0-9]+)[[:space:]]+(.*)$ ]]; then
                current_hist_num="${BASH_REMATCH[1]}"
                current_cmd="${BASH_REMATCH[2]}"
                if [[ "$current_cmd" == *"$keyword"* ]]; then
                     if [[ -v history_map_num_to_cmd["$current_hist_num"] ]]; then # Check if line number is valid
                        history_line_numbers_to_add_map["$current_hist_num"]=1
                    fi
                fi
            fi
        done
    else
        echo "Warning: Unrecognized selection format '$selection_item_trimmed'. Skipping."
    fi
done

# --- Collect and Save Commands ---
commands_to_save_to_profile=()
# Sort the selected line numbers numerically to add commands in their historical order
sorted_line_numbers=($(printf "%s\n" "${!history_line_numbers_to_add_map[@]}" | sort -n))

# Determine the name of the current script to avoid adding its own invocation to profiles
current_script_name=$(basename "$0")
# Define regex patterns for common ways the script might be invoked
# These are used to filter out the script's own execution from being saved.
# Note: This might not catch all aliased or complex invocations.
current_script_invocation_regex_patterns=(
    "bash ${current_script_name}"
    "./${current_script_name}"
    "source ${current_script_name}"
    ". ${current_script_name}"
    "${current_script_name}" # If script is in PATH and called directly
)

for line_num in "${sorted_line_numbers[@]}"; do
    if [[ -v history_map_num_to_cmd["$line_num"] ]]; then
        cmd_to_add="${history_map_num_to_cmd["$line_num"]}"
        is_self_invocation=0

        # Filter 1: Skip 'history' command itself
        if [[ "$cmd_to_add" =~ ^history($|[[:space:]]) ]]; then
            echo "Skipping 'history' command: $line_num: $cmd_to_add"
            continue
        fi

        # Filter 2: Skip commands that appear to be an invocation of this script
        for pattern in "${current_script_invocation_regex_patterns[@]}"; do
            if [[ "$cmd_to_add" == "$pattern"* ]]; then
                is_self_invocation=1
                break
            fi
        done
        # A simpler, broader check if the command string contains the script name.
        # This helps catch cases like `/path/to/script.sh` if not covered by patterns.
        if [[ $is_self_invocation -eq 0 && "$cmd_to_add" == *"$current_script_name"* ]]; then
             # Check if it's an absolute or relative path to the script
            if [[ "$cmd_to_add" == */"$current_script_name"* || "$cmd_to_add" == "$current_script_name" ]]; then
                 is_self_invocation=1
            fi
        fi


        if [ $is_self_invocation -eq 1 ]; then
            echo "Skipping self-referential command: $line_num: $cmd_to_add"
            continue
        fi
        commands_to_save_to_profile+=("$cmd_to_add")
    else
        echo "Warning: History line $line_num not found (perhaps out of range or invalid). Skipping."
    fi
done

if [ ${#commands_to_save_to_profile[@]} -eq 0 ]; then
    echo "No valid (new, non-self-referential) commands selected to add."
else
    echo -e "\n--- Commands to be added to profile '$selected_profile_name' ---"
    printf "%s\n" "${commands_to_save_to_profile[@]}"
    echo "------------------------------------"

    # Read existing commands from the profile file to check for duplicates
    existing_commands_in_profile_str=""
    if [ -f "$PROFILE_CMDS_FILE" ] && [ -s "$PROFILE_CMDS_FILE" ]; then # Check if file exists and is not empty
        existing_commands_in_profile_str=$(<"$PROFILE_CMDS_FILE")
    fi

    final_commands_to_append_to_file=()
    for cmd in "${commands_to_save_to_profile[@]}"; do
        # Check if command (as a whole line, fixed string) already exists in the profile file
        if echo "$existing_commands_in_profile_str" | grep -Fxq -- "$cmd"; then
            echo "Skipping duplicate: $cmd"
        else
            final_commands_to_append_to_file+=("$cmd")
        fi
    done

    if [ ${#final_commands_to_append_to_file[@]} -gt 0 ]; then
        # Append the new, non-duplicate commands to the profile file
        printf "%s\n" "${final_commands_to_append_to_file[@]}" >> "$PROFILE_CMDS_FILE"
        # Add an extra blank line for readability if multiple batches are added over time
        echo "" >> "$PROFILE_CMDS_FILE"
        echo "${#final_commands_to_append_to_file[@]} new command(s) added to $PROFILE_CMDS_FILE"
    else
        echo "No new (non-duplicate) commands to add to the profile."
    fi
fi

echo -e "\nProfile '$selected_profile_name' is located at: $PROFILE_CMDS_FILE"
echo "You can view, source (e.g., 'source \"$PROFILE_CMDS_FILE\"'), or copy commands from it."
echo "Done."

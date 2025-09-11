#!/usr/bin/env python3

import subprocess
import sys
import json
import os

def check_for_passed(results_workload_dir):
    print(f"Checking for 'PASSED' in the latest run in {results_workload_dir}...")
    try:
        # Find the latest directory
        latest_dir_cmd = ["bash", "-c", f"ls -td -- {results_workload_dir}/*/ | head -n 1"]
        latest_dir_process = subprocess.run(latest_dir_cmd, check=True, capture_output=True, text=True)
        latest_dir = latest_dir_process.stdout.strip()

        if not latest_dir:
            print(f"Error: No directories found in {results_workload_dir}.")
            sys.exit(1)

        print(f"Searching for 'PASSED' in: {latest_dir}")
        # Grep for "PASSED" in the latest directory
        grep_cmd = ["grep", "-r", "PASSED", latest_dir]
        grep_process = subprocess.run(grep_cmd, capture_output=True, text=True)

        if grep_process.returncode == 0:
            print("SUCCESS: 'PASSED' found in the latest simulation results.")
        else:
            print("FAILURE: 'PASSED' not found in the latest simulation results.")
            sys.exit(1)

    except subprocess.CalledProcessError as e:
        print(f"Error during verification: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        sys.exit(1)



def run_firesim_test(machine, simulation_dir, metasim_type):
    # Construct the overrideconfigdata arguments
    # The JSON strings need to be properly quoted for the shell,
    # but when passed as a list of arguments to subprocess, they should be raw strings.
    # subprocess.run will handle the quoting for the underlying command.

    override_args = [
        "--overrideconfigdata",
        json.dumps({"run_farm": {"recipe_arg_overrides": {"default_simulation_dir": simulation_dir}}}),
        "--overrideconfigdata",
        json.dumps({"run_farm": {"recipe_arg_overrides": {"run_farm_hosts_to_use": [{machine: "four_metasims_spec"}]}}}),
        "--overrideconfigdata",
        json.dumps({"metasimulation": {"metasimulation_enabled": True, "metasimulation_host_simulator": metasim_type}}),
    ]

    # firesim commands
    commands = [
        ["firesim", "managerinit"] + override_args,
        ["firesim", "launchrunfarm"] + override_args,
        ["firesim", "infrasetup"] + override_args,
        ["firesim", "runworkload"] + override_args,
        ["firesim", "terminaterunfarm", "--forceterminate"] + override_args,
    ]

    for cmd in commands:
        print(f"Running command: {' '.join(cmd)}")
        try:
            # Use check=True to raise an exception if the command returns a non-zero exit code
            subprocess.run(cmd, check=True)
            print(f"Command {' '.join(cmd)} completed successfully.")
        except subprocess.CalledProcessError as e:
            print(f"Error running command: {' '.join(cmd)}")
            sys.exit(1)

    # After all commands, check for "PASSED"
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    results_workload_abs_path = os.path.join(project_root, "deploy", "results-workload")
    check_for_passed(results_workload_abs_path)

if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python script_name.py <machine> <simulation_dir> <metasim_type>")
        sys.exit(1)

    machine = sys.argv[1]
    simulation_dir = sys.argv[2]
    metasim_type = sys.argv[3]

    run_firesim_test(machine, simulation_dir, metasim_type)

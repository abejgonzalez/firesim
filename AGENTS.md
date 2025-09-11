# FireSim Project Overview

## 1. Project Overview

FireSim is an open-source, FPGA-accelerated, full-system hardware simulation platform.
It enables cycle-exact simulation of hardware designs (RTL) at speeds orders of magnitude faster than software-based RTL simulators.
FireSim is particularly well-suited for datacenter-scale simulation and computer architecture research.

**Key Technologies:**

*   **Scala/Chisel/FIRRTL:** The core simulation infrastructure and hardware designs are written in Scala using the Chisel hardware construction language.
                    This is compiled into FIRRTL then passed to a FIRRTL compiler (named MIDAS or it's more recent version, GoldenGate) which generates the output RTL languages and C++ code to compile a full simulation.
*   **Python:** The simulation manager, deployment tools, and infrastructure management are written in Python.
                    It uses Fabric for remote execution and orchestration.
*   **Verilog:** Chisel generates Verilog or SystemVerilog RTL, which is then used to build FPGA bitstreams for FPGA simulations or normal Verilator/VCS/Xcelium SW RTL simulations.
*   **Xilinx FPGAs:** FireSim has first-class support for running simulations on Amazon EC2 F1 instances, which provide FPGAs in the cloud.
                    It also supports other on-premise FPGAs such as the RHS Research NiteFury II, Xilinx Alveo U200/250/280, and Xilinx VCU118.
*   **RISC-V:** FireSim is commonly used to simulate RISC-V systems, including complex SoCs using the Chipyard platform.
                    When cloned individually (outside of Chipyard), it has a default set of tests that don't require running an entire SoC.

**Architecture:**

The FireSim platform consists of several key components:

*   **Manager:** The `firesim` command-line tool, located in the `deploy/` directory, is the main entry point for users.
                    It is responsible for launching and managing simulation infrastructure, building bitstreams, and running workloads.
*   **Run Farm:** A collection of FPGA-equipped instances (either on-premise or in the cloud) that execute the simulations.
*   **Metasimulation:** FireSim can also run in a "metasimulation" mode, where the hardware simulation is run on a software RTL simulator like Verilator or VCS instead of an FPGA.
                    This is useful for debugging and testing.
                    This can either be run with the FireSim manager or using the ``make`` CLI interface in ``sim/``.
*   **Target Designs:** The RTL designs or software models (i.e. switch model) to be simulated are located in the `target-design/` directory.
                    If cloned inside of Chipyard, FireSim is "hooked" into Chipyard to simulate it's SoCs.
*   **Golden Gate (MIDAS):** The compiler that transforms Chisel-generated FIRRTL into a cycle-exact FPGA simulator.
                    The core of this compiler is written in Chisel and Scala.

**More Detailed Descriptions**

For more details on the setup instructions, architecture, and more, refer to the ``docs`` folder which has multiple ``md`` files describing all steps in-depth.

## 2. Building and Running

When setup without Chipyard, FireSim needs to be initialized itself.
When this repository is cloned first (i.e. without Chipyard) this is the FireSim standalone setup.

### Local Setup

A simple local setup of the repository is done with the following commands in the same shell within the top-level of the repository:

```
./build-setup.sh --skip-validate
source sourceme-manager.sh --skip-ssh-setup
firesim managerinit --platform xilinx_alveo_u250
```

Note, everytime a new shell is created with a pre-setup repository you need to run:

```
source sourceme-manager.sh --skip-ssh-setup
```

This command should add the FireSim manager to the path, setup the ``conda`` environment used to provide more tools to the ``PATH``, and more.

## 3. Testing and Coding Checks

CI Tests for the repository are found in the ``.github`` folder using Github Actions.
These are a non-exhaustive list of tests that you can use to check code (i.e. linting, syntax checking).
**Importantly, remember that you need to have a pre-setup repository with the ``sourceme-manager.sh`` script sourced (see above for the exact command) for these tests to work.**
To do so, you can run the following command to verify that it is sourced properly (if the command fails then it isn't sourced):

```
[[ "${FIRESIM_ENV_SOURCED+x}" && "$FIRESIM_ENV_SOURCED" == "1" ]]
```

### Coding checks

For Scala code, use the ``run-scala-lint`` tests in the GitHub Actions workflow file.
Scala code uses ScalaFix and ScalaFmt found in the ``sim/.scalafix.conf`` and ``sim/.scalafmt.conf`` files.
For Python code, use the ``run-python-lint`` tests in the Github Actions workflow file.
For formatting, Python code uses Python Black.
Additionally, for formatting, removing the ``--check`` flag to the formatting script will format files.
For typechecking, Python code uses ``mypy``.
For C++ code, testing is currently disabled for linting.
Formatting checks should be the last change done.

### Running a CI end-to-end smoke test

FireSim lacks many smaller tests.
However, for a simple smoke test that is mostly end-to-end, you can can run the ``build-driver-xilinx_alveo_u250`` tests in the Github Actions workflow file.
This should build the default Verilog and C++ using ``make`` and then compile the C++ sources.

### Midas Examples smoke test without using the manager

Run ``make TARGET_PROJECT=midasexamples run-vcs`` to test the Scala build flow and VCS metasimulation capabilities.
Verify that ``sim/output/f1/f1-midasexamples-GCD-NoConfig-DefaultF1Config/GCD.vcs.out`` says ``PASSED`` for it to be successful.

### Simple FireSim manager testing

To do simple FireSim manager testing (**required for any Python change**), you can run the following script: ``regression/simple-singlenode-metasim-manager-test.py``.
There are four tests that you should run with it:

1. ./regression/simple-singlenode-metasim-manager-test.py localhost /scratch/abejgonza/FIRESIM_RUNS_DIR/ vcs
2. ./regression/simple-singlenode-metasim-manager-test.py localhost /scratch/abejgonza/FIRESIM_RUNS_DIR/ verilator
3. ./regression/simple-singlenode-metasim-manager-test.py as2 /scratch/abejgonza/FIRESIM_RUNS_DIR/ vcs
4. ./regression/simple-singlenode-metasim-manager-test.py as2 /scratch/abejgonza/FIRESIM_RUNS_DIR/ verilator

These tests, respectively test that the manager works locally/remotely and with VCS or Verilator (for RTL simulations).

## 4. General Guidance

Be concise as possible.
Do not modify code that is unrelated to any change.
Match syntax and formatting of existing code in the same file.
Preserve the original intent of the code unless otherwise specified.

#!/usr/bin/env bash

# run the spectre test using the manager. optionally passing "withlaunch" will also
# automatically launch the appropriate runfarm
#
# the runfarm WILL NOT be terminated upon completion
#
# requires v1 at a minimum to be run

trap "exit" INT
set -e
set -o pipefail

if [ "$1" == "withlaunch" ]; then
    echo "firesim launchrunfarm -c workloads/spectre-config.ini"
    firesim launchrunfarm -c workloads/spectre-config.ini
fi

cd ../results-workload


spectretests=( spectre-v1 spectre-v2 )

# create the aggregate results directory
resultsdir=$(date +"%Y-%m-%d--%H-%M-%S")-spectre-tests-aggregate
mkdir $resultsdir

# make sure we don't get the same name as one of the manager produced results
# directories
sleep 2

for i in "${spectretests[@]}"
do
    echo "firesim infrasetup -c workloads/spectre-config.ini --overrideconfigdata \"workload workloadname $i.json\""
    firesim infrasetup -c workloads/spectre-config.ini --overrideconfigdata "workload workloadname $i.json"
    echo "firesim runworkload -c workloads/spectre-config.ini --overrideconfigdata \"workload workloadname $i.json\""
    firesim runworkload -c workloads/spectre-config.ini --overrideconfigdata "workload workloadname $i.json"
    # rename the output directory with the net bandwidth
    files=(*$i*)
    originalfilename=${files[-1]}
    echo "mv $originalfilename $resultsdir/$i"
    mv $originalfilename $resultsdir/$i
done

echo "firesim terminaterunfarm -c workloads/spectre-config.ini --forceterminate"
firesim terminaterunfarm -c workloads/spectre-config.ini --forceterminate

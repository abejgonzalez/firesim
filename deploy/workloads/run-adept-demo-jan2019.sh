#!/usr/bin/env bash

# showcases spectre v1
# run adept demo for jan 2019 retreat

trap "exit" INT
set -e
set -o pipefail

demo_name=adept-retreat-demo


if [ "$1" == "setup" ]; then
    echo "firesim launchrunfarm -c workloads/$demo_name-config.ini"
    firesim launchrunfarm -c workloads/$demo_name-config.ini

    echo "firesim infrasetup -c workloads/$demo_name-config.ini"
    firesim infrasetup -c workloads/$demo_name-config.ini
elif [ "$1" == "terminate" ]; then
    echo "firesim terminaterunfarm -c workloads/$demo_name-config.ini --forceterminate"
    firesim terminaterunfarm -c workloads/$demo_name-config.ini --forceterminate
elif [ "$1" == "run" ]; then 
    cd ../results-workload
    while true
    do
        # create the aggregate results directory
        resultsdir=$(date +"%Y-%m-%d--%H-%M-%S")-$demo_name-final
        mkdir $resultsdir

        # make sure we don't get the same name as one of the manager produced results
        # directories
        sleep 2

        echo "firesim runworkload -c workloads/$demo_name-config.ini"
        firesim runworkload -c workloads/$demo_name-config.ini

        # get the last run of demo
        files=(*$demo_name*)
        originalfilename=${files[-1]}
        echo "mv $originalfilename $resultsdir/$demo_name"
        mv $originalfilename $resultsdir/$demo_name

        echo "cat $resultsdir/$demo_name/${demo_name}0/uartlog | spike-dasm &> $resultsdir/$demo_name/${demo_name}0/uartlog_spikedasm"
        cat $resultsdir/$demo_name/${demo_name}0/uartlog | spike-dasm &> $resultsdir/$demo_name/${demo_name}0/uartlog_spikedasm

        echo "\nPrinting spike-dasm output"
        cat $resultsdir/$demo_name/${demo_name}0/uartlog_spikedasm

        sleep 2m
    done
fi

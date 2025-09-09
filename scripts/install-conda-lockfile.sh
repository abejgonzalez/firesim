#!/usr/bin/env bash

set -x

CUR_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
REQS_DIR="$CUR_DIR/../conda-reqs"
if [ ! -d "$REQS_DIR" ]; then
  echo "$REQS_DIR does not exist, make sure you're calling this script from firesim/"
  exit 1
fi

ENV_DIR="$CUR_DIR/../.conda-env"
if [ -d "$ENV_DIR" ]; then
  echo "$ENV_DIR does exist, ensure you are deactivated from the conda environment, delete the folder, and rerun"
  exit 1
fi

if ! conda-lock --version | grep $(grep "conda-lock" $REQS_DIR/firesim.yaml | sed 's/^ \+-.*=//'); then
  echo "Invalid conda-lock version, make sure you're calling this script with the sourced chipyard env.sh"
  exit 1
fi

# create environment with conda-lock
rm -rf "$ENV_DIR"
conda-lock \
    install \
    --conda $(which conda) \
    -p "$ENV_DIR" \
    "$REQS_DIR/conda-reqs.conda-lock.yml"

#!/usr/bin/env sh
# Run nosetests with the options that are in setup.cfg
#
# (C) Copyright 2021 Hewlett Packard Enterprise Development LP.

# TODO: It is not clear what the difference is between runCoverage.sh and
# runUnitTest.sh. We run unit tests and compute coverage here. We'll have
# to figure out how to actually do something with our coverage data.
nosetests

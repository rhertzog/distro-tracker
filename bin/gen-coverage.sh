#!/bin/sh

COVERAGE_CMD=coverage
COVERAGE_CMD_PY3=coverage

if test -x /usr/bin/python-coverage; then
    COVERAGE_CMD=python-coverage
fi
if test -x /usr/bin/python3-coverage; then
    COVERAGE_CMD_PY3=python3-coverage
fi

export COVERAGE_CMD
export COVERAGE_CMD_PY3

tox -e clean-cov,py27-cov,py34-cov,html-cov

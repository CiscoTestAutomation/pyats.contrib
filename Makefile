################################################################################
#                                                                              #
#                      Cisco Systems Proprietary Software                      #
#        Not to be distributed without consent from Test Technology            #
#                            Cisco Systems, Inc.                               #
#                                                                              #
################################################################################
#                             pyats.contrib
#
# Author:
#   Siming Yuan        (siyuan@cisco.com)    - CSG
#   Jean-Benoit Aubin  (jeaubin@cisco.com)   - CSG
#
# Support:
#    python-core@cisco.com
#
# Version:
#   v2.1
#
# Date:
#   April 2018
#
# About This File:
#   This script will build individual pyats.contrib modules into a Python PyPI package.
#
################################################################################

# Variables
PKG_NAME      = pyats.contrib
BUILD_DIR     = $(shell pwd)/__build__
WATCHERS      = asg-genie-dev@cisco.com
HEADER        = [Watchdog]
PYPIREPO      = pypitest
PYTHON		  = python

# Internal variables.
# (note - build examples & templates last because it will fail uploading to pypi
#  due to duplicates, and we'll for now accept that error)
PYPI_PKGS      = testbed_creator

ALL_PKGS       = $(PYPI_PKGS)

.PHONY: help docs clean check devnet\
	develop undevelop install_build_deps
	uninstall_build_deps

help:
	@echo "Please use 'make <target>' where <target> is one of"
	@echo ""
	@echo "     --- common actions ---"
	@echo ""
	@echo " check                 check setup.py content"
	@echo " clean                 remove the build directory ($(BUILD_DIR))"
	@echo " help                  display this help"
	@echo " develop               set all package to development mode"
	@echo " undevelop             unset the above development mode"
	@echo " devnet                Build DevNet package."
	@echo " install_build_deps    install pyats-distutils"
	@echo " uninstall_build_deps  remove pyats-distutils"
	@echo ""

devnet: all
	@echo "Completed building DevNet packages"
	@echo ""

install_build_deps:
	@pip install --upgrade pip setuptools wheel

uninstall_build_deps:
	@echo "nothing to do"

docs:
	@echo "No documentation to build for pyats.contrib"

clean:
	@echo ""
	@echo "--------------------------------------------------------------------"
	@echo "Removing make directory: $(BUILD_DIR)"
	@rm -rf $(BUILD_DIR)
	@python setup.py clean
	@echo "Removing *.pyc *.c and __pycache__/ files"
	@find . -type f -name "*.pyc" | xargs rm -vrf
	@find . -type f -name "*.c" | xargs rm -vrf
	@find . -type d -name "__pycache__" | xargs rm -vrf
	@find . -type d -name "build" | xargs rm -vrf
	@echo "Done."
	@echo ""

develop:
	@echo ""
	@echo "--------------------------------------------------------------------"
	@echo "Setting up development environment"
	@python setup.py develop --no-deps -q
	@echo ""
	@echo "Done."
	@echo ""

undevelop:
	@echo ""
	@echo "--------------------------------------------------------------------"
	@echo "Removing development environment"
	@python setup.py develop -q --no-deps --uninstall
	@echo ""
	@echo "Done."
	@echo ""

all: $(ALL_PKGS)
	@echo ""
	@echo "Done."
	@echo ""

package: $(ALL_PKGS)
	@echo ""
	@echo "Done."
	@echo ""

check:
	@echo ""
	@echo "--------------------------------------------------------------------"
	@echo "Checking setup.py consistency..."
	@echo ""

	@python setup.py check

	@echo "Done"
	@echo ""

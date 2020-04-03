# Variables
BUILD_DIR     = $(shell pwd)/__build__
DIST_DIR      = $(BUILD_DIR)/dist
PYTHON		  = python

DEPENDENCIES = ansible requests xlrd xlrd xlwt xlsxwriter

.PHONY: check help clean test package develop undevelop all \
        install_build_deps uninstall_build_deps

help:
	@echo "Please use 'make <target>' where <target> is one of"
	@echo ""
	@echo "     --- common actions ---"
	@echo ""
	@echo " check                 check setup.py content"
	@echo " clean                 remove the build directory ($(BUILD_DIR))"
	@echo " test                  run all unit tests"
	@echo " help                  display this help"
	@echo " develop               set all package to development mode"
	@echo " undevelop             unset the above development mode"
	@echo " install_build_deps    install build dependencies"
	@echo " uninstall_build_deps  remove build dependencies"
	@echo ""

install_build_deps:
	@pip install --upgrade pip setuptools wheel

uninstall_build_deps:
	@echo "nothing to do"

clean:
	@echo ""
	@echo "--------------------------------------------------------------------"
	@echo "Removing make directory: $(BUILD_DIR)"
	@rm -rf $(BUILD_DIR)
	@$(PYTHON) setup.py clean
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
	@pip install $(DEPENDENCIES)
	@$(PYTHON) setup.py develop --no-deps -q
	@echo ""
	@echo "Done."
	@echo ""

undevelop:
	@echo ""
	@echo "--------------------------------------------------------------------"
	@echo "Removing development environment"
	@$(PYTHON) setup.py develop -q --no-deps --uninstall
	@echo ""
	@echo "Done."
	@echo ""

all: package
	@echo ""
	@echo "Done."
	@echo ""

package: 
	@echo ""
	@$(PYTHON) setup.py bdist_wheel --dist-dir=$(DIST_DIR)
	@echo ""

check:
	@echo ""
	@echo "--------------------------------------------------------------------"
	@echo "Checking setup.py consistency..."
	@echo ""

	@$(PYTHON) setup.py check

	@echo "Done"
	@echo ""

test:
	@echo ""
	@echo "--------------------------------------------------------------------"
	@echo "Running unit tests..."
	@echo ""

	@$(PYTHON) -m unittest discover src

	@echo "Done"
	@echo ""
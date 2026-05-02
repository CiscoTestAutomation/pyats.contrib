
# Variables
PKG_NAME	  = pyats.contrib
BUILD_DIR     = $(shell pwd)/__build__
DIST_DIR      = $(BUILD_DIR)/dist
PYTHON		  = python3
PIP           = $(PYTHON) -m pip
MESON_HELPER  = cisco-meson
PROD_USER     = pyadm@pyats-ci
STAGING_PKGS  = /auto/pyats/staging/packages
STAGING_EXT_PKGS  = /auto/pyats/staging/packages

# xlrd==1.2 because support for '.xlsx' files was dropped in later versions
DEPENDENCIES = requests requests-toolbelt xlrd==1.2 xlwt xlsxwriter
BUILD_DEPENDENCIES = meson-python 'meson>=1.10.0' ninja build 'patchelf>=0.11.0; sys_platform == "linux"'
SITE_PACKAGES = $(shell $(PYTHON) -c "import sysconfig; print(sysconfig.get_path('purelib'))")
DEVELOP_PATH_FILE = $(SITE_PACKAGES)/pyats-contrib-dev-path.pth
EDITABLE_PTH_FILE = $(SITE_PACKAGES)/pyats-contrib-editable.pth
EDITABLE_LOADER_FILE = $(SITE_PACKAGES)/_pyats_contrib_editable_loader.py

.PHONY: check help clean test package develop undevelop all \
        install_build_deps uninstall_build_deps distribute_staging\
        distribute_staging_external

help:
	@echo "Please use 'make <target>' where <target> is one of"
	@echo ""
	@echo "     --- common actions ---"
	@echo ""
	@echo " check                          validate build configuration"
	@echo " clean                          remove the build directory ($(BUILD_DIR))"
	@echo " test                           run all unit tests"
	@echo " help                           display this help"
	@echo " develop                        set all package to development mode"
	@echo " undevelop                      unset the above development mode"
	@echo " install_build_deps             install build dependencies"
	@echo " uninstall_build_deps           remove build dependencies"
	@echo " distribute_staging             Distribute the package to staging area"
	@echo " distribute_staging_external    Distribute the package to external staging area"
	@echo ""

install_build_deps:
	@$(PIP) install --upgrade pip $(BUILD_DEPENDENCIES)

uninstall_build_deps:
	@echo "nothing to do"

clean:
	@echo ""
	@echo "--------------------------------------------------------------------"
	@echo "Removing make directory: $(BUILD_DIR)"
	@rm -rf $(BUILD_DIR)
	@find . -type f -name "*.pyc" -delete
	@find . -type d -name "__pycache__" -prune -exec rm -rf {} +
	@find . -type d -name "build" -prune -exec rm -rf {} +
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
	@$(PIP) uninstall -y pyats.contrib || true
	@$(PIP) install --no-build-isolation $(DEPENDENCIES) $(BUILD_DEPENDENCIES)
	@$(MESON_HELPER) editable sync --project-root "$(CURDIR)" --source-path "$(CURDIR)/src" --pth-file "$(DEVELOP_PATH_FILE)" --remove-path "$(EDITABLE_PTH_FILE)" --remove-path "$(EDITABLE_LOADER_FILE)"
	@echo ""
	@echo "Done."
	@echo ""

undevelop:
	@echo ""
	@echo "--------------------------------------------------------------------"
	@echo "Removing development environment"
	@$(PYTHON) -m pip uninstall -y $(PKG_NAME) || true
	@$(MESON_HELPER) editable clean --project-root "$(CURDIR)" --pth-file "$(DEVELOP_PATH_FILE)" --remove-path "$(EDITABLE_PTH_FILE)" --remove-path "$(EDITABLE_LOADER_FILE)"
	@echo ""
	@echo "Done."
	@echo ""

all: package
	@echo ""
	@echo "Done."
	@echo ""

package: 
	@echo ""
	@$(PYTHON) -m build --no-isolation --wheel --outdir=$(DIST_DIR)
	@echo "Done."
	@echo ""

check:
	@echo ""
	@echo "--------------------------------------------------------------------"
	@echo "Checking build configuration..."
	@echo ""

	@$(PYTHON) -m build --no-isolation --wheel --outdir=$(DIST_DIR)

	@echo "Done."
	@echo ""

test:
	@echo ""
	@echo "--------------------------------------------------------------------"
	@echo "Running unit tests..."
	@echo ""

	@$(PYTHON) -m unittest discover src

	@echo "Done."
	@echo ""

distribute_staging:
	@echo ""
	@echo "--------------------------------------------------------------------"
	@echo "Copying all distributable to $(STAGING_PKGS)"
	@test -d $(DIST_DIR) || { echo "Nothing to distribute! Exiting..."; exit 1; }
	@ssh -q $(PROD_USER) 'test -e $(STAGING_PKGS)/$(PKG_NAME) || mkdir $(STAGING_PKGS)/$(PKG_NAME)'
	@scp $(DIST_DIR)/* $(PROD_USER):$(STAGING_PKGS)/$(PKG_NAME)/
	@echo ""
	@echo "Done."
	@echo ""

distribute_staging_external:
	@echo ""
	@echo "--------------------------------------------------------------------"
	@echo "Copying all distributable to $(STAGING_EXT_PKGS)"
	@test -d $(DIST_DIR) || { echo "Nothing to distribute! Exiting..."; exit 1; }
	@ssh -q $(PROD_USER) 'test -e $(STAGING_EXT_PKGS)/$(PKG_NAME) || mkdir $(STAGING_EXT_PKGS)/$(PKG_NAME)'
	@scp $(DIST_DIR)/* $(PROD_USER):$(STAGING_EXT_PKGS)/$(PKG_NAME)/
	@echo ""
	@echo "Done."
	@echo ""

changelogs:
	@echo ""
	@echo "--------------------------------------------------------------------"
	@echo "Generating changelog file"
	@echo ""
	@$(PYTHON) -c "from ciscodistutils.make_changelog import main; main('./docs/changelog/undistributed', './docs/changelog/undistributed.rst')"
	@echo "pyats.contrib changelog created..."
	@echo ""
	@echo "Done."
	@echo ""

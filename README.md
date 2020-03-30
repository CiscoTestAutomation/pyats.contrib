# pyATS Contribution Package

The `pyats.contrib` package is a collection of open-source extensions for the
pyATS framework. 

Plugins, extensions and codes under this project are designed to automatically
integrate into the pyATS framework using its various published hook/entry-point
interfaces.

## General Information

- Website: https://developer.cisco.com/pyats/
- Documentation: https://developer.cisco.com/docs/pyats/
- Support: pyats-support-ext@cisco.com

## Installation

This package is automatically installed when you perform a full pyATS 
installation. Alternatively, you can install this package separately, if you 
have a more light-weight pyATS install:

```
# when using full-install, this package is included by default
$ pip install pyats[full]


# to install separately
$ pip install pyats.contrib
```

## Solution Documentation

For now, each individual folder under `src/` has its own README.md file.
We are working on a better hosting solution for all documentation related to 
this repository.

## Contributions

Everyone is welcomed to pitch-in, collaborate, contribute and improve upon 
what's here, and or introduce new ideas and plugins. The goal of this package is
three-fold:

    - to introduce a place where the pyATS development team can open-source
      bits and pieces of the framework

    - to provide a location for community members to collaborate together, 
      centrally

    - to document and demonstrate, via examples, the various plugins and hook 
      capabilities the framework has to offer.

Please consider the following when contributing to this repository:

- minimize dependencies as much as possible; use lazy-loading where possible.
  Eg: adding a pip installation dependency will impact ALL users that install
  this package, where as adding an import dependency, with try/except around it,
  and printing a nice error message indicating you need package X installed to
  enable this feature, allows selectively installation of dependencies per 
  what's needed

- include unit-tests and documentation for everything you develop

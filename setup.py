#! /usr/bin/env python

'''Setup file for pyats.contrib

See:
    https://packaging.python.org/en/latest/distributing.html
'''

from setuptools import setup, find_packages
from os import listdir
from os.path import isfile, join

def read(path):
    with open(path) as f:
        return f.read()

def discover_creators():
    files = [
        file.replace('.py', '') for file in listdir('src/creators') 
            if isfile(join('src/creators', file)) and file not in [
                '__init__.py',
                'creator.py'
            ]
        ]
    return ['{source} = creators.{source}:{source_title}'
        .format(source=source, source_title=source.title()) for source in files]

# launch setup
setup(
    name = 'pyats.contrib',
    version = '20.3',

    # descriptions
    description = 'Open source package for pyATS framework extensions.',
    long_description = read('README.md'),

    # the project's main homepage.
    url = 'https://developer.cisco.com/pyats/',

    # author details
    author = 'Cisco Systems Inc.',
    author_email = 'pyats-support-ext@cisco.com',

    # project licensing
    license = 'Apache 2.0',

    classifiers = [
        'Development Status :: 6 - Mature',
        'Development Status :: 5 - Production/Stable',
        'Environment :: Console',
        'Intended Audience :: Developers',
        'Intended Audience :: Telecommunications Industry',
        'Intended Audience :: Information Technology',
        'Intended Audience :: System Administrators',
        'License :: OSI Approved :: Apache Software License',
        'Operating System :: MacOS',
        'Operating System :: POSIX :: Linux',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3 :: Only',
        'Programming Language :: Python :: Implementation :: CPython',
        'Topic :: Software Development :: Testing',
        'Topic :: Software Development :: Build Tools',
        'Topic :: Software Development :: Libraries',
        'Topic :: Software Development :: Libraries :: Python Modules',
    ],
    
    # project packages
    packages = find_packages(where = 'src'),

    # project directory
    package_dir = {
        '': 'src',
    },

    # additional package data files that goes into the package itself
    package_data = {},

    # project keywords
    keywords = 'genie pyats test automation open source contrib',

    entry_points={
        'pyats.topology.loader': discover_creators()
    },

    # package dependencies
    install_requires=[
        "ansible", "requests", "xlrd", "xlrd", "xlwt", "xlsxwriter"
    ],

    # external modules
    ext_modules = [],

    # non zip-safe (never tested it)
    zip_safe = False,
)
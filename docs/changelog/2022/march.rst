March 2022
=============

March 29th
-------------

.. csv-table:: Module Versions
    :header: "Modules", "Versions"

        ``pyats.contrib``, v22.3


Install Instructions
^^^^^^^^^^^^^^^^^^^^

.. code-block:: bash

    bash$ pip install pyats.contrib

Upgrade Instructions
^^^^^^^^^^^^^^^^^^^^

.. code-block:: bash

    bash$ pip install --upgrade pyats.contrib


Features and Bug Fixes:
^^^^^^^^^^^^^^^^^^^^^^^

* Netbox
    * Modified Netbox:
        * Added enable password to testbed options
        * Added platform class map to map Netbox Platform to PyATS platform and os
        * Added custom data source to populate PyATS device.custom attribute from Netbox

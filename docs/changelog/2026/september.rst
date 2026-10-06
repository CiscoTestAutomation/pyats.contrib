September 2026
==============

September 29 - Pyats.Contrib v26.9
----------------------------------




Changelogs
^^^^^^^^^^

--------------------------------------------------------------------------------
                                      Fix
--------------------------------------------------------------------------------

* pyats.contrib
    * Modified Ansible testbed creator:
        * Normalized generated inventory keys and values to plain Python types before
          YAML serialization, so tagged values from newer Ansible versions produce
          ordinary testbed YAML.

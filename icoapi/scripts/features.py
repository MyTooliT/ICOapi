"""Optional features of the API, switched on by environment variables"""

import os

# The variable is spelled as it was introduced (“MUTLI”); the correctly
# spelled name works too.
MULTI_STU_SUPPORT_VARIABLES = ("MUTLI_STU_SUPPORT", "MULTI_STU_SUPPORT")

_TRUE_VALUES = {"1", "true", "yes", "on"}


def multi_stu_support() -> bool:
    """Check if support for multiple STUs is switched on

    Switching it on makes the API store measurements as ICOschema bundles
    (a HDF5 file with one source per STU/STH combination) instead of the
    ``Storage`` format of ICOtronic. Without it the API behaves as it did
    before the feature existed.

    The variable is read every time, so tests can change it at runtime.

    Returns:

        ``True``, if one of the variables ``MUTLI_STU_SUPPORT`` and
        ``MULTI_STU_SUPPORT`` is set to ``1``, ``true``, ``yes`` or ``on``
        (case insensitive)

    """

    return any(
        os.getenv(name, "").strip().lower() in _TRUE_VALUES
        for name in MULTI_STU_SUPPORT_VARIABLES
    )

"""Install the R-P provider guard in every child interpreter started with this directory on PYTHONPATH.

REBUILD-DESIGN-v2 §5.2 R-P layer (a) for child interpreters; never shipped.
"""

import provider_guard

provider_guard.install()

"""Debian.org specific settings"""

#: A module implementing vendor-specific functionality which the PTS can hook
#: into.
#: For more information see :py:mod:`pts.vendor`.
PTS_VENDOR_RULES = 'pts.vendor.debian.rules'

#: A custom template which the bugs panel should use
PTS_BUGS_PANEL_TEMPLATE = 'debian/bugs.html'

#: A list of suite names which should be used when updating piuparts stats
PTS_DEBIAN_PIUPARTS_SUITES = (
    'sid',
)   


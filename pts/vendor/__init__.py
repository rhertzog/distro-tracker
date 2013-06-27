# Copyright 2013 The Debian Package Tracking System Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/ptsauthors
#
# This file is part of the Package Tracking System. It is subject to the
# license terms in the LICENSE file found in the top-level directory of
# this distribution and at http://deb.li/ptslicense. No part of the Package
# Tracking System, including this file, may be copied, modified, propagated, or
# distributed except according to the terms contained in the LICENSE file.

"""An app which enables the PTS to access vendor-specific functionality.

Vendors can define their own specific set of rules for mail dispatch
which the PTS can plug in to appropriate functions.

Each rule should be implemented as a callable which takes a defined set of
arguments with a predefined name. The supported callables are:

- ``get_keyword(local_part, message)`` - takes a local_part of the email
  address to which a message was sent and an email Message object.
  Should return a keyword which matches the message or None if it does not
  match any keyword.

- ``add_new_headers(received_message, package_name, keyword)`` -
  takes an email Message object, the name of the package and the keyword
  of the message.
  Should return a list of two-tuples (header_name, header_value) of headers
  which should be added to the response message.

- ``approve_default_message(message)`` - takes an email Message object.
  Should return a Boolean indicating whether this message should still be
  forwarded to subscribers which are subscribed to the default keyword.
"""

from pts.vendor.common import get_callable

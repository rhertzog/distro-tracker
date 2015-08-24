# Copyright 2015 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at http://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""Views for the :mod:`distro_tracker.vendor.debian` app."""
from __future__ import unicode_literals

from django.utils.http import urlencode
from django.views.generic import View
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect


class CodeSearchView(View):

    BASE_URL = 'https://codesearch.debian.net/search'

    def get(self, request):
        if 'query' not in request.GET or 'package' not in request.GET:
            return HttpResponseBadRequest('Both package and query are required '
                                          'parameters')
        q = request.GET.get('query')
        if q == "":
            return HttpResponseBadRequest('Empty query is not allowed')
        package = request.GET.get('package')
        search = q + ' package:' + package
        url = self.BASE_URL + '?' + urlencode({'q': search})
        return redirect(url)

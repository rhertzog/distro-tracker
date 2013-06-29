# Copyright 2013 The Debian Package Tracking System Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/ptsauthors
#
# This file is part of the Package Tracking System. It is subject to the
# license terms in the LICENSE file found in the top-level directory of
# this distribution and at http://deb.li/ptslicense. No part of the Package
# Tracking System, including this file, may be copied, modified, propagated, or
# distributed except according to the terms contained in the LICENSE file.

from django.shortcuts import render, redirect
from django.http import Http404
from pts.core.models import get_web_package


def package_page(request, package_name):
    package = get_web_package(package_name)
    if not package:
        raise Http404
    if package.get_absolute_url() != request.path:
        return redirect(package)
    return render(request, 'core/package.html', {
        'package': package
    })


def legacy_package_url_redirect(request, package_hash, package_name):
    return redirect('pts-package-page', package_name=package_name, permanent=True)

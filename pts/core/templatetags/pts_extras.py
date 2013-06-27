# Copyright 2013 The Debian Package Tracking System Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/ptsauthors
#
# This file is part of the Package Tracking System. It is subject to the
# license terms in the LICENSE file found in the top-level directory of
# this distribution and at http://deb.li/ptslicense. No part of the Package
# Tracking System, including this file, may be copied, modified, propagated, or
# distributed except according to the terms contained in the LICENSE file.

from __future__ import unicode_literals
from django import template

register = template.Library()


class RepeatNode(template.Node):
    def __init__(self, nodelist, count):
        self.nodelist = nodelist
        self.count = template.Variable(count)

    def render(self, context):
        output = self.nodelist.render(context)
        return output * int(self.count.resolve(context))


@register.tag
def repeat(parser, token):
    """
    Repeats the string enclosed in the tag the number of times given in
    the parameter of the tag.
    """
    try:
        tag_name, count = token.split_contents()
    except ValueError:
        raise template.TemplateSyntaxError(
            '{tag} tag requires an argument'.format(tag=token.contents.split()[0]))

    nodelist = parser.parse(('endrepeat',))
    parser.delete_first_token()
    return RepeatNode(nodelist, count)


@register.filter(name='zip')
def zip_iterables(first, second):
    return zip(first, second)

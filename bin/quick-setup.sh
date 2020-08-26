#!/bin/sh

set -e

if [ -e distro_tracker/project/settings/local.py ]; then
    echo "ERROR: You already have a configuration file (distro_tracker/project/settings/local.py)" >&2
    exit 1
fi

if [ -e data/distro-tracker.sqlite ]; then
    echo "ERROR: You already have a database file (data/distro-tracker.sqlite)" >&2
    exit 1
fi

if [ ! -e distro_tracker/project/settings/local.py.sample-debian-dev ]; then
    echo "ERROR: are you at the root of the distro-tracker repository?"
    echo "USAGE: ./bin/$0"
    exit 1
fi

echo ">>> Ensuring we have the required packages"
packages="python3-django python3-requests python3-django-jsonfield python3-django-debug-toolbar python3-debian python3-debianbts python3-apt python3-gpg python3-yaml python3-bs4 python3-pyinotify python3-selenium chromium-driver"
if ! dpkg-query -W $packages >/dev/null; then
    echo ">>> Installing the required packages with “sudo apt install”"
    sudo apt install $packages
fi
version=$(dpkg-query -W -f'${Version}' python3-django)
if dpkg --compare-versions $version lt 2:2.2; then
    echo "WARNING: you need python3-django >= 2:2.2"
    echo "Trying to install it from buster-backports"
    sudo apt install python3-django/buster-backports
fi

echo ">>> Installing a configuration file"
cp distro_tracker/project/settings/local.py.sample-debian-dev distro_tracker/project/settings/local.py

echo ">>> Downloading a pre-built sample database file"
# Note: when https://gitlab.com/gitlab-org/gitlab-ce/issues/45697 will be
# fixed, we should be able to use 
# https://salsa.debian.org/qa/distro-tracker/-/jobs/artifacts/master/raw/data/distro-tracker.sqlite?job=sample-database
#url=$(bin/sample-database-url)
#if [ -n "$url" ]; then
#    wget "$url" -O data/distro-tracker.sqlite
#else
#    echo "ERROR: unable to find sample database url (bin/sample-database-url returned nothing)"
#    exit 1
#fi
echo "WARNING: there's currently no pre-built database to download, generating a new one, it might take a long time..."
./manage.py migrate
./manage.py loaddata distro_tracker/core/fixtures/sample-database-repositories.xml
./manage.py tracker_update_repositories

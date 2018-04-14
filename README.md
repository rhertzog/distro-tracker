# distro-tracker

distro-tracker is a set of services tailored to distribution developers,
package maintainers, and anybody who might have to interact with those
people (upstream developers, bug reporters, advanced users, etc). It lets
you follow almost everything related to the life of a package (or of a set
of packages).

## Documentation

The [documentation](https://qa.pages.debian.net/distro-tracker/) always
matches what's in the git repository's master branch.

Otherwise you can generate the documentation yourself by doing `make html`
in the docs subdirectory of the distro-tracker git repository.

## Interacting with the project

### How to contribute

Have a look at the ["Contributing"
section](https://qa.pages.debian.net/distro-tracker/contributing.html) of the
documentation.

### Contact information

You can interact with the developers on the debian-qa@lists.debian.org
mailing list ([archive](https://lists.debian.org/debian-qa/)) or on
the `#debian-qa` IRC channel on the OFTC network (irc.debian.org server
for example).

The lead developer is Raphaël Hertzog (buxy on IRC).

### Reporting bugs and vulnerabilities

We are using [GitLab's bug
tracker](https://salsa.debian.org/qa/distro-tracker/issues) to manage bug
reports. You should file new bugs there.

However we also use the Debian bug tracker with its `tracker.debian.org`
pseudo-package. You should thus check [its list of open
issues](https://bugs.debian.org/tracker.debian.org) before filing a new
bug to avoid duplicates. You can also have a look at all the [closed bug
reports](https://bugs.debian.org/cgi-bin/pkgreport.cgi?archive=1;package=tracker.debian.org)
too.

Security issues should be reported to the bug tracker like other bugs.
If you believe that the issue is really sensitive, then you can
mail [Raphaël Hertzog](mailto:hertzog@debian.org) privately.

## Misc information

### Badges

[![CII Best Practices](https://bestpractices.coreinfrastructure.org/projects/1440/badge)](https://bestpractices.coreinfrastructure.org/projects/1440)

[![Code Health](https://landscape.io/github/rhertzog/distro-tracker/master/landscape.svg?style=flat)](https://landscape.io/github/rhertzog/distro-tracker/master)

### Known distro-tracker deployments

* https://tracker.debian.org
* http://pkg.kali.org



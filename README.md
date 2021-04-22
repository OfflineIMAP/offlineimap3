Upstream status (`master` branch):
[![OfflineIMAP build status on Travis-CI.org](https://travis-ci.org/OfflineIMAP/offlineimap.svg?branch=master)](https://travis-ci.org/OfflineIMAP/offlineimap)
[![OfflineIMAP code coverage on Codecov.io](https://codecov.io/gh/OfflineIMAP/offlineimap/branch/master/graph/badge.svg)](https://codecov.io/gh/OfflineIMAP/offlineimap)
[![Gitter chat](https://badges.gitter.im/OfflineIMAP/offlineimap.png)](https://gitter.im/OfflineIMAP/offlineimap)

Upstream status (`next` branch):
[![OfflineIMAP build status on Travis-CI.org](https://travis-ci.org/OfflineIMAP/offlineimap.svg?branch=next)](https://travis-ci.org/OfflineIMAP/offlineimap)

[offlineimap]: http://github.com/OfflineIMAP/offlineimap
[website]: http://www.offlineimap.org
[wiki]: http://github.com/OfflineIMAP/offlineimap/wiki
[blog]: http://www.offlineimap.org/posts.html

Links:
* Official github code repository: [offlineimap]
* Website: [website]
* Wiki: [wiki]
* Blog: [blog]

# OfflineIMAP

***"Get the emails where you need them."***

[Official offlineimap][https://github.com/OfflineIMAP/offlineimap3].


## Description

OfflineIMAP is software that downloads your email mailbox(es) as **local
Maildirs**. OfflineIMAP will synchronize both sides via *IMAP*.

## Why should I use OfflineIMAP?

IMAP's main downside is that you have to **trust** your email provider to
not lose your email. While certainly unlikely, it's not impossible.
With OfflineIMAP, you can download your Mailboxes and make you own backups of
your [Maildir](https://en.wikipedia.org/wiki/Maildir).

This allows reading your email offline without the need for your mail
reader (MUA) to support IMAP operations. Need an attachment from a
message without internet connection? No problem, the message is still there.


## Project status and future

OfflineIMAP, using Python 3, is based on OfflineIMAP for Python 2.
Currently we are updating the source code. These changes should not affect
the user (documentation, configuration files,... are the same) but some
links or packages could refer to the Python 2 version. In that case, please
open an issue.


## License

GNU General Public License v2.


## Downloads

You should first check if your distribution already packages OfflineIMAP for you.
Downloads releases as [tarball or zipball](https://github.com/OfflineIMAP/offlineimap/tags).

If you are running Linux Os, you can install offlineimap with:

-  openSUSE `zypper in offlineimap`
-  Arch Linux `pacman -S offlineimap`
-  fedora `dnf install offlineimap`

## Feedbacks and contributions

**The user discussions, development, announcements and all the exciting stuff take
place on the mailing list.** While not mandatory to send emails, you can
[subscribe here](http://lists.alioth.debian.org/mailman/listinfo/offlineimap-project).

Bugs, issues and contributions can be requested to both the mailing list or the
[official Github project][offlineimap3].  Provide the following information:
- system/distribution (with version)
- offlineimap version (`offlineimap -V`)
- Python version
- server name or domain
- CLI options
- Configuration file (offlineimaprc)
- pythonfile (if any)
- Logs, error
- Steps to reproduce the error


## The community

* OfflineIMAP's main site is the [project page at Github][offlineimap3].
* There is the [OfflineIMAP community's website][website].
* And finally, [the wiki][wiki].


## Requirements & dependencies

* Python v3+
* rfc6555 (required)
* imaplib2 >= 3.5
* gssapi (optional), for Kerberos authentication
* portalocker (optional), if you need to run offlineimap in Cygwin for Windows

## Documentation

All current and updated documentation is on the [community's website][website].


### Read documentation locally

You might want to read the documentation locally. Get the sources of the website.
For the other documentation, run the appropriate make target:

```sh
$ ./scripts/get-repository.sh website
$ cd docs
$ make html  # Requires rst2html
$ make man   # Requires a2x (http://asciidoc.org)
$ make api   # Requires sphinx
```

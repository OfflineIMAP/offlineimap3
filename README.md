<!--
Upstream status (`master` branch):
[![OfflineIMAP build status on Travis-CI.org](https://travis-ci.org/OfflineIMAP/offlineimap.svg?branch=master)](https://travis-ci.org/OfflineIMAP/offlineimap)
[![OfflineIMAP code coverage on Codecov.io](https://codecov.io/gh/OfflineIMAP/offlineimap/branch/master/graph/badge.svg)](https://codecov.io/gh/OfflineIMAP/offlineimap)
[![Gitter chat](https://badges.gitter.im/OfflineIMAP/offlineimap.png)](https://gitter.im/OfflineIMAP/offlineimap)

Upstream status (`next` branch):
[![OfflineIMAP build status on Travis-CI.org](https://travis-ci.org/OfflineIMAP/offlineimap.svg?branch=next)](https://travis-ci.org/OfflineIMAP/offlineimap)
-->


[offlineimap]: https://github.com/OfflineIMAP/offlineimap
[offlineimap3]: https://github.com/OfflineIMAP/offlineimap3
[website]: https://www.offlineimap.org
[wiki]: https://github.com/OfflineIMAP/offlineimap/wiki
[blog]: https://www.offlineimap.org/posts.html

<h1 align="center">OfflineIMAP</h1>

<p align="center"><i>"Get the emails where you need them."</i><p>

<p align="center">
  <a href="https://www.offlineimap.org">Website</a> •
  <a href="https://www.offlineimap.org/documentation.html">Documetation</a> •
  <a href="https://github.com/OfflineIMAP/offlineimap/wiki">Wiki</a> •
  <a href="https://www.offlineimap.org/posts.html">Blog</a>
</p>


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


## Downloads

You should first check if your distribution already packages OfflineIMAP for you.
Downloads releases as [tarball or zipball](https://github.com/OfflineIMAP/offlineimap3/tags).

If you are running Linux/BSD, you can install offlineimap with:

-  Debian and Ubuntu `apt install offlineimap3`
-  openSUSE `zypper install offlineimap`
-  Fedora `dnf install offlineimap`
-  FreeBSD `pkg search offlineimap3`, and install the python versioned package, `pkg install py311-offlineimap3`
-  Arch Linux: [`pacman -S offlineimap`](https://archlinux.org/packages/extra/any/offlineimap/), or through AUR package [offlineimap3-git](https://aur.archlinux.org/packages/offlineimap3-git/)
-  Docker image: `offlineimap/offlineimap:latest`
 (note: image not published yet, just an example)

## Feedbacks

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


## Requirements & dependencies

* Python v3.6+
* rfc6555 (required)
* imaplib2 >= 3.5 (required)
* keyring (optional), for storing passwords in a secure way
* gssapi (optional), for Kerberos authentication
* pysocks (optional), for proxy support
* portalocker (optional), if you need to run offlineimap in Cygwin for Windows
* certify (optional), for Internet SSL certificate validation
* urllib3 (optional), for Internet SSL certificate validation


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


## Contributing

Pull requests are welcome! For details on the development workflow and coding guidelines, please refer to:
- [Development Workflow](https://www.offlineimap.org/doc/GitAdvanced.html)
- [Coding Guidelines](https://www.offlineimap.org/doc/CodingGuidelines.html)

**The user discussions, development, announcements and all the exciting stuff take place on the mailing list.** While not mandatory to send emails, you can [subscribe here](http://lists.alioth.debian.org/mailman/listinfo/offlineimap-project).


## License

This project is licensed under the **GNU General Public License v2.0 or later**.
See the [LICENSE](LICENSE) file for details.

<!--
Upstream status (`master` branch):
[![OfflineIMAP build status on Travis-CI.org](https://travis-ci.org/OfflineIMAP/offlineimap.svg?branch=master)](https://travis-ci.org/OfflineIMAP/offlineimap)
[![OfflineIMAP code coverage on Codecov.io](https://codecov.io/gh/OfflineIMAP/offlineimap/branch/master/graph/badge.svg)](https://codecov.io/gh/OfflineIMAP/offlineimap)
[![Gitter chat](https://badges.gitter.im/OfflineIMAP/offlineimap.png)](https://gitter.im/OfflineIMAP/offlineimap)

Upstream status (`next` branch):
[![OfflineIMAP build status on Travis-CI.org](https://travis-ci.org/OfflineIMAP/offlineimap.svg?branch=next)](https://travis-ci.org/OfflineIMAP/offlineimap)
-->

<h1 align="center">OfflineIMAP3</h1>

<p align="center"><i>"Get the emails where you need them."</i><p>

<p align="center">
  <a href="https://www.offlineimap.org">Website</a> •
  <a href="https://www.offlineimap.org/documentation.html">Documetation</a> •
  <a href="https://github.com/OfflineIMAP/offlineimap/wiki">Wiki</a> •
  <a href="https://www.offlineimap.org/posts.html">Blog</a>
</p>


## Description

OfflineIMAP3 is software that downloads your email mailbox(es) as **local
Maildirs**. OfflineIMAP3 will synchronize both sides via *IMAP*.


## Why should I use OfflineIMAP3?

IMAP's main downside is that you have to **trust** your email provider to
not lose your email. While certainly unlikely, it's not impossible.
With OfflineIMAP3, you can download your Mailboxes and make you own backups of
your [Maildir](https://en.wikipedia.org/wiki/Maildir).

This allows reading your email offline without the need for your mail
reader (MUA) to support IMAP operations. Need an attachment from a
message without internet connection? No problem, the message is still there.


## Project status and future

This project, **OfflineIMAP3**, is a Python 3 port of the original [OfflineIMAP](https://github.com/OfflineIMAP/offlineimap) (Python 2). We are currently updating the source code to ensure full compatibility. While user-facing elements (documentation, configuration files, etc.) remain unchanged, some links or packages may still reference the Python 2 version. If you encounter any such references, please [open an issue](https://github.com/OfflineIMAP/offlineimap3/issues).


## Installation

### Option A: Install from Source (Tarball/Zipball)
Download a release from [GitHub tags](https://github.com/OfflineIMAP/offlineimap3/tags), then:
```bash
tar -xzf offlineimap3-*.tar.gz
cd offlineimap3-*
pip install .
```

### Option B: Install via Package Manager
Check if your distribution provides a package for OfflineIMAP3. If available, use one of the following commands:

- **Debian/Ubuntu:** `sudo apt install offlineimap3`
- **openSUSE:** `sudo zypper install offlineimap`
- **Fedora:** `sudo dnf install offlineimap`
- **FreeBSD:** `pkg search offlineimap3`, then `sudo pkg install py311-offlineimap3`
- **Arch Linux:** `sudo pacman -S offlineimap` (or AUR: [offlineimap3-git](https://aur.archlinux.org/packages/offlineimap3-git/))
- **MacOS:** `brew install offlineimap`
<!--
- **Docker:** `docker pull offlineimap/offlineimap:latest` *(example, not yet published)*
-->


### Requirements & dependencies

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

## Feedbacks

Bugs, issues and contributions can be requested to both the mailing list or the
[official Github project][https://github.com/OfflineIMAP/offlineimap3].  Provide the following information:
- system/distribution (with version)
- offlineimap version (`offlineimap -V`)
- Python version
- server name or domain
- CLI options
- Configuration file (offlineimaprc)
- pythonfile (if any)
- Logs, error
- Steps to reproduce the error


## Contributing

Pull requests are welcome! For details on the development workflow and coding guidelines, please refer to:
- [Development Workflow](https://www.offlineimap.org/doc/GitAdvanced.html)
- [Coding Guidelines](https://www.offlineimap.org/doc/CodingGuidelines.html)

**The user discussions, development, announcements and all the exciting stuff take place on the mailing list.** While not mandatory to send emails, you can [subscribe here](http://lists.alioth.debian.org/mailman/listinfo/offlineimap-project).


## License

This project is licensed under the **GNU General Public License v2.0 or later**.
See the [LICENSE](https://github.com/lb803/offlineimap3/blob/master/COPYING) file for details.

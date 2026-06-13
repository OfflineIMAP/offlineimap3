# IMAP server support
# Copyright (C) 2002-2018 John Goerzen & contributors.
#
#    This program is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301 USA

import datetime
import hashlib
import hmac
import json
import urllib.request
import urllib.parse
import urllib.error
import time
import errno
import select
import socket
from socket import gaierror
from sys import exc_info
from ssl import SSLError, cert_time_to_seconds
from threading import Lock, BoundedSemaphore, Thread, Event, current_thread
import offlineimap.accounts
from offlineimap import imaplibutil, imaputil, threadutil, OfflineImapError
from offlineimap.ui import getglobalui

try:
    import gssapi
    have_gss = True
except ImportError:
    have_gss = False


def _is_socket_alive(imapobj):
    """Returns True if the underlying socket connection is still usable.

    Note: MSG_PEEK is not supported on ssl.SSLSocket, so we only check
    for explicit error conditions and whether the socket has a peer address.
    """
    try:
        sock = imapobj.socket()
        if sock is None:
            return False
        sock.getpeername()  # OSError if socket is closed or not connected
        # Check for socket errors without blocking.  If the socket is closed,
        # this will raise an OSError with errno.EBADF;
        # if the socket is still open but has an error, this will return it
        # in the third list of select.select() and cause us to return False.
        _, _, e = select.select([], [], [sock], 0.0)
        return not bool(e)
    except (OSError, socket.error):
        return False


def _check_pooled_connection(imapobj, ui):
    """Verify that a pooled connection is still alive by sending a NOOP command.
    Returns True if the connection is healthy and False if it is not.  Logs
    any exceptions encountered during the NOOP command as debug messages, since
    they are expected to occur when a connection has gone stale.
    """
    try:
        typ, _ = imapobj.noop()
        return typ == 'OK'
    except Exception as e:
        ui.debug('imap', 'Pooled connection health check (NOOP) failed: %s' % e)
        return False


class IMAPServer:
    """Initializes all variables from an IMAPRepository() instance

    Various functions, such as acquireconnection() return an IMAP4
    object on which we can operate.

    Public instance variables are: self.:
     delim The server's folder delimiter. Only valid after acquireconnection()
    """

    def __init__(self, repos):
        """:repos: a IMAPRepository instance."""

        self.ui = getglobalui()
        self.repos = repos
        self.config = repos.getconfig()
        self.ignore_keyring = self.config.getboolean('general', 'ignore-keyring')
        self.update_keyring = self.config.getboolean('general', 'update-keyring')

        self.preauth_tunnel = repos.getpreauthtunnel()
        self.transport_tunnel = repos.gettransporttunnel()
        if self.preauth_tunnel and self.transport_tunnel:
            raise OfflineImapError('%s: ' % repos +
                                   'you must enable precisely one '
                                   'type of tunnel (preauth or transport), '
                                   'not both', OfflineImapError.ERROR.REPO)
        self.tunnel = \
            self.preauth_tunnel if self.preauth_tunnel \
                else self.transport_tunnel

        self.username = \
            None if self.preauth_tunnel else repos.getuser()
        self.user_identity = repos.get_remote_identity()
        self.authmechs = repos.get_auth_mechanisms()
        self.password = None
        self.passworderror = None
        self.goodpassword = None

        self.usessl = repos.getssl()
        self.useipv6 = repos.getipv6()
        if self.useipv6 is True:
            self.af = socket.AF_INET6
        elif self.useipv6 is False:
            self.af = socket.AF_INET
        else:
            self.af = socket.AF_UNSPEC
        self.hostname = None if self.transport_tunnel or self.preauth_tunnel else repos.gethost()
        self.port = repos.getport()
        if self.port is None:
            self.port = 993 if self.usessl else 143
        self.sslclientcert = repos.getsslclientcert()
        self.sslclientkey = repos.getsslclientkey()
        self.sslcacertfile = repos.getsslcacertfile()
        if self.sslcacertfile is None:
            self.__verifycert = None  # Disable cert verification.
            # This way of working sucks hard...
        self.fingerprint = repos.get_ssl_fingerprint()
        self.tlslevel = repos.gettlslevel()
        self.sslversion = repos.getsslversion()
        self.starttls = repos.getstarttls()

        if self.usessl \
                and self.tlslevel != "tls_compat" \
                and self.sslversion is None:
            raise Exception("When 'tls_level' is not 'tls_compat' "
                            "the 'ssl_version' must be set explicitly.")

        self.oauth2_refresh_token = repos.getoauth2_refresh_token()
        self.oauth2_access_token_getter = repos.getoauth2_access_token_getter()
        # is used if the above getter is None or doesn't work
        self.oauth2_access_token = None
        self.oauth2_client_id = repos.getoauth2_client_id()
        self.oauth2_client_secret = repos.getoauth2_client_secret()
        self.oauth2_request_url = repos.getoauth2_request_url()
        self.oauth2_access_token_expires_at = None
        self._oauth2_lock = Lock()

        self.delim = None
        self.root = None
        self.maxconnections = repos.getmaxconnections()
        self.availableconnections = []
        self.assignedconnections = []
        self.lastowner = {}
        self.semaphore = BoundedSemaphore(self.maxconnections)
        self.connectionlock = Lock()
        self.closing = False
        self.reference = repos.getreference()
        self.idlefolders = repos.getidlefolders()
        self.gss_vc = None
        self.gssapi = False

        # In order to support proxy connection, we have to override the
        # default socket instance with our own socksified socket instance.
        # We add this option to bypass the GFW in China.
        self.proxied_socket = self._get_proxy('proxy', socket.socket)

        # Turns out that the GFW in China is no longer blocking imap.gmail.com
        # However accounts.google.com (for oauth2) definitey is.  Therefore
        # it is not strictly necessary to use a proxy for *both* IMAP *and*
        # oauth2, so a new option is added: authproxy.

        # Set proxy for use in authentication (only) if desired.
        # If not set, is same as proxy option (compatible with current configs)
        # To use a proxied_socket but not an authproxied_socket
        # set authproxy = '' in config
        self.authproxied_socket = self._get_proxy('authproxy',
                                                  self.proxied_socket)

    def _get_proxy(self, proxysection, dfltsocket):
        _account_section = 'Account ' + self.repos.account.name
        if not self.config.has_option(_account_section, proxysection):
            return dfltsocket
        proxy = self.config.get(_account_section, proxysection)
        if proxy == '':
            # explicitly set no proxy (overrides default return of dfltsocket)
            return socket.socket

        # Powered by PySocks.
        try:
            import socks
            proxy_type, host, port = proxy.split(":")
            port = int(port)
            socks.setdefaultproxy(getattr(socks, proxy_type), host, port)
            return socks.socksocket
        except ImportError:
            self.ui.warn("PySocks not installed, ignoring proxy option.")
        except (AttributeError, ValueError) as e:
            self.ui.warn("Bad proxy option %s for account %s: %s "
                         "Ignoring %s option." %
                         (proxy, self.repos.account.name, e, proxysection))
        return dfltsocket

    def __getpassword(self):
        """Returns the server password or None"""

        if self.goodpassword is not None:  # use cached good one first
            return self.goodpassword

        if self.password is not None and self.passworderror is None:
            return self.password  # non-failed preconfigured one

        # get 1) configured password first 2) fall back to asking via UI
        self.password = self.repos.getpassword(self.ignore_keyring) or \
                        self.ui.getpass(self.username, self.config, self.passworderror)
        if self.update_keyring:
            self.repos.updatepassword(self.password)
        self.passworderror = None
        return self.password

    def __md5handler(self, response):
        challenge = response.strip()
        self.ui.debug('imap', '__md5handler: got challenge %s' % challenge)

        passwd = self.__getpassword()
        retval = self.username + ' ' +\
                 hmac.new(bytes(passwd, encoding='utf-8'), challenge,
                          digestmod=hashlib.md5).hexdigest()
        self.ui.debug('imap', '__md5handler: returning %s' % retval)
        return retval

    def __loginauth(self, imapobj):
        """ Basic authentication via LOGIN command."""

        self.ui.debug('imap', 'Attempting IMAP LOGIN authentication')
        imapobj.login(self.username, self.__getpassword())

    def __plainhandler(self, response):
        """Implements SASL PLAIN authentication, RFC 4616,
          http://tools.ietf.org/html/rfc4616"""

        authc = self.username
        if not authc:
            raise OfflineImapError("No username provided for '%s'"
                                   % self.repos.getname(),
                                   OfflineImapError.ERROR.REPO)

        passwd = self.__getpassword()
        authz = ''
        NULL = '\x00'
        if self.user_identity is not None:
            authz = self.user_identity

        retval = NULL.join((authz, authc, passwd))
        self.ui.debug('imap', '__plainhandler: returning %s %s '
                      '(passwd hidden for log)' % (authz, authc))
        return retval

    def __xoauth2handler(self, response):
        # Serialize token retrieval to prevent concurrent threads from
        # invalidating each other's tokens (e.g. when an external program
        # called via oauth2_access_token_eval refreshes the token, it may
        # revoke the previous one, causing the other thread's auth to fail).
        with self._oauth2_lock:
            now = datetime.datetime.now()
            access_token_to_use = None
            if self.oauth2_access_token_getter is not None:
                # If we already have a cached token that has not expired,
                # reuse it instead of calling the getter again.  This avoids
                # concurrent threads each triggering a token refresh that
                # could invalidate the token obtained by the other thread.
                if self.oauth2_access_token is not None \
                        and self.oauth2_access_token_expires_at \
                        and self.oauth2_access_token_expires_at > now:
                    access_token_to_use = self.oauth2_access_token
                else:
                    access_token_to_use = self.oauth2_access_token_getter()
                    if access_token_to_use is not None:
                        self.oauth2_access_token = access_token_to_use
                        # Cache for a reasonable window so that parallel
                        # connection attempts reuse the same token.
                        if self.oauth2_access_token_expires_at is None \
                                or self.oauth2_access_token_expires_at <= now:
                            self.oauth2_access_token_expires_at = \
                                now + datetime.timedelta(seconds=600)
                    else:
                        # Getter returned None: clear any stale expiry so that
                        # the next call does not skip straight to the cached-token
                        # path and silently use None as the Bearer token.
                        self.oauth2_access_token = None
                        self.oauth2_access_token_expires_at = None
                        raise OfflineImapError(
                            "oauth2_access_token_eval returned None for "
                            "repository '%s'. Check your token getter." % self,
                            OfflineImapError.ERROR.REPO)

            if access_token_to_use is None:
                if self.oauth2_access_token_expires_at \
                        and self.oauth2_access_token_expires_at < now:
                    self.oauth2_access_token = None
                    self.ui.debug('imap', 'xoauth2handler: oauth2_access_token expired')

                if self.oauth2_access_token is None:
                    if self.oauth2_request_url is None:
                        raise OfflineImapError("No remote oauth2_request_url for "
                                               "repository '%s' specified." %
                                               self, OfflineImapError.ERROR.REPO)

                    # Generate new access token.
                    params = {}
                    params['client_id'] = self.oauth2_client_id
                    params['client_secret'] = self.oauth2_client_secret
                    params['refresh_token'] = self.oauth2_refresh_token
                    params['grant_type'] = 'refresh_token'

                    self.ui.debug('imap', 'xoauth2handler: url "%s"' %
                                  self.oauth2_request_url)
                    self.ui.debug('imap', 'xoauth2handler: params "%s"' % params)

                    original_socket = socket.socket
                    socket.socket = self.authproxied_socket
                    try:
                        response = urllib.request.urlopen(
                            self.oauth2_request_url, urllib.parse.urlencode(params).encode('utf-8')).read()
                    except Exception as e:
                        try:
                            msg = "%s (configuration is: %s)" % (e, str(params))
                        except Exception as eparams:
                            msg = "%s [cannot display configuration: %s]" % (e, eparams)

                        self.ui.error(e, exc_info()[2], msg)
                        raise
                    finally:
                        socket.socket = original_socket

                    resp = json.loads(response)
                    self.ui.debug('imap', 'xoauth2handler: response "%s"' % resp)
                    if 'error' in resp:
                        raise OfflineImapError("xoauth2handler got: %s" % resp,
                                               OfflineImapError.ERROR.REPO)
                    self.oauth2_access_token = resp['access_token']
                    if 'expires_in' in resp:
                        self.oauth2_access_token_expires_at = now + datetime.timedelta(
                            seconds=resp['expires_in'] / 2
                        )
                    access_token_to_use = self.oauth2_access_token

        self.ui.debug('imap', 'xoauth2handler: access_token "%s expires %s"' % (
            access_token_to_use, self.oauth2_access_token_expires_at))
        auth_string = 'user=%s\1auth=Bearer %s\1\1' % (
            self.username, access_token_to_use)
        # auth_string = base64.b64encode(auth_string)
        self.ui.debug('imap', 'xoauth2handler: returning "%s"' % auth_string)
        return auth_string

    # Perform the next step handling a GSSAPI connection.
    # Client sends first, so token will be ignored if there is no context.
    def __gsshandler(self, token):
        if token == "":
            token = None
        try:
            if not self.gss_vc:
                name = gssapi.Name('imap@' + self.hostname,
                                   gssapi.NameType.hostbased_service)
                self.gss_vc = gssapi.SecurityContext(usage="initiate",
                                                     name=name)

            if not self.gss_vc.complete:
                response = self.gss_vc.step(token)
                return response if response else ""
            elif token is None:
                # uh... context is complete, so there's no negotiation we can
                # do.  But we also don't have a token, so we can't send any
                # kind of response.  Empirically, some (but not all) servers
                # seem to put us in this state, and seem fine with getting no
                # GSSAPI content in response, so give it to them.
                return ""

            # Don't bother checking qop because we're over a TLS channel
            # already.  But hey, if some server started encrypting tomorrow,
            # we'd be ready since krb5 always requests integrity and
            # confidentiality support.
            response = self.gss_vc.unwrap(token)

            # This is a behavior we got from pykerberos.  First byte is one,
            # first four bytes are preserved (pykerberos calls this a length).
            # Any additional bytes are username.
            reply = b'\x01' + response.message[1:4]
            reply += bytes(self.username, 'utf-8')

            response = self.gss_vc.wrap(reply, response.encrypted)
            return response.message if response.message else ""
        except gssapi.exceptions.GSSError as err:
            # GSSAPI errored out on us; respond with None to cancel the
            # authentication
            self.ui.debug('imap', err.gen_message())
            return None

    def __start_tls(self, imapobj):
        """Upgrade connection to TLS if STARTTLS is configured.

        - After STARTTLS, forces a CAPABILITY command and replaces internal
          capabilities with the post-TLS response.
        - If no reliable post-TLS CAPABILITY is available:
          - In strict mode (allow_nonstandard_capabilities = no): abort.
          - In tolerant mode (allow_nonstandard_capabilities = yes):
            reuse pre-TLS capabilities, removing LOGINDISABLED.
        """

        # If the repository does not want STARTTLS, do nothing.
        if not self.starttls or self.usessl:
            return

        # Pre-TLS capabilities (from initial banner / CAPABILITY).
        caps_pre = set(getattr(imapobj, '_offlineimap_capabilities_pre_tls',
                               getattr(imapobj, 'capabilities', [])))

        # If the server does not advertise STARTTLS, warn but attempt anyway.
        # Per RFC 2595 section 9, a man-in-the-middle attacker can strip
        # STARTTLS from the capability list to force a cleartext connection.
        # Silently skipping STARTTLS when the user configured it would make
        # offlineimap vulnerable to this attack.  We try regardless and let
        # the server reject the command if it genuinely does not support it.
        if 'STARTTLS' not in caps_pre:
            self.ui.warn(
                "Server '%s' did not advertise STARTTLS in its capabilities, "
                "but starttls is configured.  Attempting STARTTLS anyway to "
                "guard against capability-stripping attacks (RFC 2595 §9)."
                % self.hostname
            )

        # Execute STARTTLS.
        self.ui.debug('imap', 'Using STARTTLS connection')

        # Disable _get_capabilities() during starttls() to prevent imaplib2
        # from issuing CAPABILITY before we can do it ourselves.
        _orig_get_cap = imapobj._get_capabilities
        imapobj._get_capabilities = lambda: None
        try:
            try:
                imapobj.starttls()
            except imapobj.error as e:
                err = "Failed to start TLS connection: %s" % str(e)
                raise OfflineImapError(err, OfflineImapError.ERROR.REPO,
                                       exc_info()[2])
        finally:
            # Always restore the original method, even on error.
            imapobj._get_capabilities = _orig_get_cap

        # At this point, the socket is encrypted. Now we must refresh CAPABILITY.
        caps_post = None
        try:
            typ, data = imapobj.capability()
            if typ == 'OK' and data:
                # data is a list of bytes, e.g. [b'IMAP4rev1 IDLE AUTH=PLAIN']
                line = data[0]
                if isinstance(line, bytes):
                    line = line.decode('ascii', 'ignore')
                caps_post = set(line.upper().split())
        except Exception:
            caps_post = None

        if caps_post is not None:
            # Standard path: completely replace capabilities
            imapobj.capabilities = caps_post
            imapobj._offlineimap_capabilities_post_tls = caps_post
            return

        # If we reach here, we do not have reliable post-TLS capabilities.
        # Decide based on repository configuration.
        allow_nonstandard = getattr(self.repos,
                                    'allow_nonstandard_capabilities', False)

        if not allow_nonstandard:
            # Strict mode: abort with clear error.
            raise OfflineImapError(
                "Server did not provide valid CAPABILITY after STARTTLS; "
                "set 'allow_nonstandard_capabilities = yes' in repository "
                "configuration to enable a non-standard fallback.",
                OfflineImapError.ERROR.REPO
            )

        # Tolerant mode: best-effort using caps_pre.
        caps_fallback = set(caps_pre)
        if 'LOGINDISABLED' in caps_fallback:
            # We assume that after STARTTLS, LOGINDISABLED no longer applies,
            # so we remove it to allow LOGIN/AUTH configured by the user.
            caps_fallback.remove('LOGINDISABLED')

        imapobj.capabilities = caps_fallback
        imapobj._offlineimap_capabilities_post_tls = caps_fallback

        self.ui.warn(
            "Server did not provide CAPABILITY after STARTTLS; "
            "falling back to pre-TLS capabilities without LOGINDISABLED "
            "due to allow_nonstandard_capabilities = yes."
        )

    # All __authn_* procedures are helpers that do authentication.
    # They are class methods that take one parameter, IMAP object.
    #
    # Each function should return True if authentication was
    # successful and False if authentication wasn't even tried
    # for some reason (but not when IMAP has no such authentication
    # capability, calling code checks that).
    #
    # Functions can also raise exceptions; two types are special
    # and will be handled by the calling code:
    #
    # - imapobj.error means that there was some error that
    #   comes from imaplib2;
    #
    # - OfflineImapError means that function detected some
    #   problem by itself.

    def __authn_gssapi(self, imapobj):
        if not have_gss:
            return False

        self.connectionlock.acquire()
        try:
            imapobj.authenticate('GSSAPI', self.__gsshandler)
            return True
        except imapobj.error:
            self.gssapi = False
            raise
        finally:
            self.connectionlock.release()

    def __authn_cram_md5(self, imapobj):
        imapobj.authenticate('CRAM-MD5', self.__md5handler)
        return True

    def __authn_plain(self, imapobj):
        imapobj.authenticate('PLAIN', self.__plainhandler)
        return True

    def __authn_xoauth2(self, imapobj):
        if self.oauth2_refresh_token is None \
                and self.oauth2_access_token_getter is None:
            return False

        imapobj.authenticate('XOAUTH2', self.__xoauth2handler)
        return True

    def __authn_login(self, imapobj):
        # Use LOGIN command, unless LOGINDISABLED is advertized
        # (per RFC 2595)
        if 'LOGINDISABLED' in imapobj.capabilities:
            raise OfflineImapError("IMAP LOGIN is "
                                   "disabled by server.  Need to use SSL?",
                                   OfflineImapError.ERROR.REPO)
        else:
            self.__loginauth(imapobj)
            return True

    def __authn_helper(self, imapobj):
        """Authentication machinery for self.acquireconnection().

        Raises OfflineImapError() of type ERROR.REPO when
        there are either fatal problems or no authentications
        succeeded.

        If any authentication method succeeds, routine should exit:
        warnings for failed methods are to be produced in the
        respective except blocks."""

        # Stack stores pairs of (method name, exception)
        exc_stack = []
        tried_to_authn = False
        # Authentication routines, hash keyed by method name
        # with value that is a tuple with
        # - authentication function,
        # - check IMAP capability flag.
        auth_methods = {
            "GSSAPI": (self.__authn_gssapi, True),
            "XOAUTH2": (self.__authn_xoauth2, True),
            "CRAM-MD5": (self.__authn_cram_md5, True),
            "PLAIN": (self.__authn_plain, True),
            "LOGIN": (self.__authn_login, False),
        }

        did_starttls = False
        # GSSAPI is tried first by default: we will probably go TLS after it and
        # GSSAPI mustn't be tunneled over TLS.
        for m in self.authmechs:
            if m not in auth_methods:
                raise Exception("Bad authentication method %s, "
                                "please, file OfflineIMAP bug" % m)

            func, check_cap = auth_methods[m]

            # TLS must be initiated before checking capabilities:
            # they could have been changed after STARTTLS.
            if self.starttls and not did_starttls:
                did_starttls = True
                self.__start_tls(imapobj)

            if check_cap:
                cap = "AUTH=" + m
                if cap not in imapobj.capabilities:
                    continue

            tried_to_authn = True
            self.ui.debug('imap', 'Attempting '
                                  '%s authentication' % m)
            try:
                if func(imapobj):
                    return
            except (imapobj.error, OfflineImapError) as e:
                self.ui.warn('%s authentication failed: %s' % (m, e))
                exc_stack.append((m, e))

                # If XOAUTH2 failed, invalidate the cached token so the
                # next attempt calls the getter again instead of reusing
                # a token that was rejected by the server.
                if m == 'XOAUTH2':
                    self.oauth2_access_token = None
                    self.oauth2_access_token_expires_at = None

                # If the socket is dead, don't even try to authenticate
                # with the next method, since it will just fail with a socket
                # error. Instead, bail out immediately and let
                # acquireconnection() handle the error and cleanup.
                if not _is_socket_alive(imapobj):
                    msg = f"Socket dead after {m} failure, aborting remaining auth methods"
                    self.ui.debug('imap', msg)
                    break

        if len(exc_stack):
            msg = "\n\t".join([": ".join((x[0], str(x[1]))) for x in exc_stack])
            err = OfflineImapError("All authentication types "
                                   "failed:\n\t%s" % msg, OfflineImapError.ERROR.REPO)
            # Signal to acquireconnection() that at least one auth method was
            # attempted and rejected by the server.  A dead socket here means
            # the server closed the connection after rejecting credentials, not
            # a transient network failure — retrying would not help.
            err.auth_attempted = True
            raise err

        if not tried_to_authn:
            methods = ", ".join([x[5:] for x in
                                 [x for x in imapobj.capabilities if x[0:5] == "AUTH="]])
            raise OfflineImapError("Repository %s: no supported "
                                   "authentication mechanisms found; configured %s, "
                                   "server advertises %s" % (self.repos,
                                                             ", ".join(self.authmechs), methods),
                                   OfflineImapError.ERROR.REPO)

    def __verifycert(self, cert, hostname):
        """Verify that cert (in socket.getpeercert() format) matches hostname.

        CRLs are not handled.
        Returns error message if any problems are found and None on success."""

        errstr = "CA Cert verifying failed: "
        if not cert:
            return '%s no certificate received' % errstr
        dnsname = hostname.lower()
        certnames = []

        # cert expired?
        notafter = cert.get('notAfter')
        if notafter:
            if time.time() >= cert_time_to_seconds(notafter):
                return '%s certificate expired %s' % (errstr, notafter)

        # First read commonName
        for s in cert.get('subject', []):
            key, value = s[0]
            if key == 'commonName':
                certnames.append(value.lower())
        if len(certnames) == 0:
            return '%s no commonName found in certificate' % errstr

        # Then read subjectAltName
        for key, value in cert.get('subjectAltName', []):
            if key == 'DNS':
                certnames.append(value.lower())

        # And finally try to match hostname with one of these names
        for certname in certnames:
            if (certname == dnsname or
                    '.' in dnsname and certname == '*.' + dnsname.split('.', 1)[1]):
                return None

        return '%s no matching domain name found in certificate' % errstr

    def acquireconnection(self):
        """Fetches a connection from the pool, making sure to create a new one
        if needed, to obey the maximum connection limits, etc.
        Opens a connection to the server and returns an appropriate
        object."""

        self.semaphore.acquire()
        self.connectionlock.acquire()
        if self.closing:
            self.connectionlock.release()
            self.semaphore.release()
            raise OfflineImapError("Server is closing",
                                   OfflineImapError.ERROR.REPO)
        curThread = current_thread()
        imapobj = None

        imap_debug = 0
        if 'imap' in self.ui.debuglist:
            imap_debug = 5

        if len(self.availableconnections):  # One is available.
            # Try to find one that previously belonged to this thread
            # as an optimization.  Start from the back since that's where
            # they're popped on.
            for i in range(len(self.availableconnections) - 1, -1, -1):
                tryobj = self.availableconnections[i]
                if self.lastowner[tryobj] == curThread.ident:
                    imapobj = tryobj
                    del (self.availableconnections[i])
                    break
            if not imapobj:
                imapobj = self.availableconnections[0]
                del (self.availableconnections[0])
            self.assignedconnections.append(imapobj)
            self.lastowner[imapobj] = curThread.ident
            self.connectionlock.release()

            # Store the pre-TLS capabilities (from banner and initial CAPABILITY).
            # This will be used only to decide STARTTLS and, in case of non-standard
            # fallback, to reconstruct an approximate post-TLS capability list.
            try:
                caps_pre = set(getattr(imapobj, 'capabilities', []))
            except Exception:
                caps_pre = set()
            imapobj._offlineimap_capabilities_pre_tls = caps_pre

            # Verify that the connection is still alive before returning it
            # to the caller.  If not, clean up and recursively call
            # acquireconnection() to get a new one.
            if not _check_pooled_connection(imapobj, self.ui):
                self.ui.debug('imap', 'Pooled connection to %s is dead, '
                                    'creating a new one' % self.hostname)
                # Clean up and release the slot to force a new connection
                self.connectionlock.acquire()
                self.assignedconnections.remove(imapobj)
                self.connectionlock.release()
                try:
                    imapobj.logout()
                except Exception:
                    pass
                self.semaphore.release()
                return self.acquireconnection()  # Recursive call to get a new connection

            return imapobj

        self.connectionlock.release()  # Release until need to modify data

        # Must be careful here that if we fail we should bail out gracefully
        # and release locks / threads so that the next attempt can try...
        success = False
        try:
            retries = 0
            while success is not True and retries < 3:
                # Generate a new connection.
                if self.tunnel:
                    self.ui.connecting(
                        self.repos.getname(), 'tunnel', self.tunnel)
                    imapobj = imaplibutil.IMAP4_Tunnel(
                        self.tunnel,
                        timeout=socket.getdefaulttimeout(),
                        debug=imap_debug,
                        use_socket=self.proxied_socket,
                    )
                    success = True
                elif self.usessl:
                    self.ui.connecting(
                        self.repos.getname(), self.hostname, self.port)
                    self.ui.debug('imap', "%s: level '%s', version '%s'" %
                                  (self.repos.getname(), self.tlslevel, self.sslversion))
                    imapobj = imaplibutil.WrappedIMAP4_SSL(
                        host=self.hostname,
                        port=self.port,
                        keyfile=self.sslclientkey,
                        certfile=self.sslclientcert,
                        ca_certs=self.sslcacertfile,
                        cert_verify_cb=self.__verifycert,
                        ssl_version=self.sslversion,
                        debug=imap_debug,
                        timeout=socket.getdefaulttimeout(),
                        fingerprint=self.fingerprint,
                        use_socket=self.proxied_socket,
                        tls_level=self.tlslevel,
                        af=self.af,
                    )
                else:
                    self.ui.connecting(
                        self.repos.getname(), self.hostname, self.port)
                    imapobj = imaplibutil.WrappedIMAP4(
                        self.hostname, self.port,
                        timeout=socket.getdefaulttimeout(),
                        use_socket=self.proxied_socket,
                        debug=imap_debug,
                        af=self.af,
                    )

                # If 'ID' extension is used by the server, we should use it
                if 'ID' in imapobj.capabilities:
                    l_str = '("name" "OfflineIMAP" "version" "{}")'.format(offlineimap.__version__)
                    try:
                        imapobj.id(l_str)
                    except Exception as e:
                        self.ui.warn("IMAP ID command failed: %s" % str(e))

                if not self.preauth_tunnel:
                    try:
                        self.__authn_helper(imapobj)
                        self.goodpassword = self.password
                        success = True
                    except OfflineImapError as e:
                        # Retry only for transient network failures: the socket
                        # died before any auth method was attempted.
                        # If auth_attempted is set, the server received and
                        # rejected our credentials — retrying with the same
                        # credentials would not help and may trigger server-side
                        # connection limits (e.g. Gmail "Too many simultaneous
                        # connections" after closing the socket on PLAIN failure).
                        if not getattr(e, 'auth_attempted', False) \
                                and not _is_socket_alive(imapobj):
                            retries += 1
                            if retries >= 3:
                                self.ui.warn("Authentication failed after 3 attempts due to dead sockets.")
                                raise
                            self.ui.warn("Connection lost before authentication. "
                                         "Retrying from scratch (%d/3)..." % retries)
                            if imapobj is not None:
                                try:
                                    imapobj.shutdown()
                                except Exception:
                                    pass
                            continue
                        self.passworderror = str(e)
                        raise

            # Enable compression
            if self.repos.getconfboolean('usecompression', 0):
                imapobj.enable_compression()

            # update capabilities after login, e.g. gmail serves different ones.
            # Skip when STARTTLS was used: imaplib2 sets _tls_established=True
            # inside starttls() (after our _get_capabilities no-op), so this
            # flag reliably signals that a second CAPABILITY round-trip is both
            # redundant and dangerous for servers like Protonmail Bridge.
            # For plain SSL connections _tls_established is False, so Gmail and
            # similar servers that advertise different post-auth capabilities
            # still get the normal refresh.
            if not getattr(imapobj, '_tls_established', False):
                typ, dat = imapobj.capability()
                if dat != [None]:
                    # Get the capabilities and convert them to string from bytes
                    s_dat = [x.decode('utf-8') for x in dat[-1].upper().split()]
                    imapobj.capabilities = tuple(s_dat)

            if self.delim is None:
                listres = imapobj.list(self.reference, '""')[1]
                if listres == [None] or listres is None:
                    # Some buggy IMAP servers do not respond well to LIST "" ""
                    # Work around them.
                    listres = imapobj.list(self.reference, '"*"')[1]
                if listres == [None] or listres is None:
                    # No Folders were returned. This occurs, e.g. if the
                    # 'reference' prefix does not exist on the mail
                    # server. Raise exception.
                    err = "Server '%s' returned no folders in '%s'" % \
                          (self.repos.getname(), self.reference)
                    self.ui.warn(err)
                    raise Exception(err)
                self.delim, self.root = \
                    imaputil.imapsplit(listres[0])[1:]
                self.delim = imaputil.dequote(self.delim)
                self.root = imaputil.dequote(self.root)

            with self.connectionlock:
                # close() may have been called while we were doing network
                # I/O (the lock was not held during connection + auth).
                # If so, logout the new connection and bail out rather than
                # adding it to a pool that is being torn down.
                # Do NOT release the semaphore here: the outer except block
                # will do it when the OfflineImapError propagates up.
                if self.closing:
                    try:
                        imapobj.logout()
                    except Exception:
                        pass
                    raise OfflineImapError(
                        "Server '%s' is closing; discarding new connection "
                        "acquired during teardown." % self.repos,
                        OfflineImapError.ERROR.REPO)
                self.assignedconnections.append(imapobj)
                self.lastowner[imapobj] = curThread.ident
            return imapobj
        except Exception as e:
            """If we are here then we did not succeed in getting a
            connection - we should clean up and then re-raise the
            error..."""

            self.semaphore.release()

            severity = OfflineImapError.ERROR.REPO
            if type(e) == gaierror:
                # DNS related errors. Abort Repo sync
                # TODO: special error msg for e.errno == 2 "Name or service not known"?
                reason = "Could not resolve name '%s' for repository " \
                         "'%s'. Make sure you have configured the ser" \
                         "ver name correctly and that you are online." % \
                         (self.hostname, self.repos)
                raise OfflineImapError(reason, severity, exc_info()[2])

            if isinstance(e, SSLError) and e.errno == errno.EPERM:
                # SSL unknown protocol error
                # happens e.g. when connecting via SSL to a non-SSL service
                if self.port != 993:
                    reason = "Could not connect via SSL to host '%s' and non-s" \
                             "tandard ssl port %d configured. Make sure you connect" \
                             " to the correct port. Got: %s" % (
                                 self.hostname, self.port, e)
                else:
                    reason = "Unknown SSL protocol connecting to host '%s' for " \
                             "repository '%s'. OpenSSL responded:\n%s" \
                             % (self.hostname, self.repos, e)
                raise OfflineImapError(reason, severity, exc_info()[2])

            if isinstance(e, socket.error) and e.args and e.args[0] == errno.ECONNREFUSED:
                # "Connection refused", can be a non-existing port, or an unauthorized
                # webproxy (open WLAN?)
                reason = "Connection to host '%s:%d' for repository '%s' was " \
                         "refused. Make sure you have the right host and port " \
                         "configured and that you are actually able to access the " \
                         "network." % (self.hostname, self.port, self.repos)
                raise OfflineImapError(reason, severity, exc_info()[2])

            # Could not acquire connection to the remote;
            # socket.error(last_error) raised
            if str(e)[:24] == "can't open socket; error":
                raise OfflineImapError(
                    "Could not connect to remote server '%s' "
                    "for repository '%s'. Remote does not answer." % (self.hostname, self.repos),
                    OfflineImapError.ERROR.REPO,
                    exc_info()[2])
            # IMAP protocol errors (e.g. server not responding to welcome,
            # socket errors during handshake) are transient and should be
            # retried by the account sync loop.
            if e.args:
                try:
                    if str(e.args[0]).startswith('IMAP4 protocol error'):
                        raise OfflineImapError(
                            "IMAP protocol error connecting to '%s:%d' for "
                            "repository '%s': %s" %
                            (self.hostname, self.port, self.repos, e),
                            OfflineImapError.ERROR.REPO,
                            exc_info()[2])
                except OfflineImapError:
                    raise
                except:
                    pass

            # re-raise all other errors
            raise

    def close(self):
        # First make sure no new connections can be established.
        self.connectionlock.acquire()
        self.closing = True
        self.connectionlock.release()

        # Make sure I own all the semaphores.  Let the threads finish
        # their stuff.  This is a blocking method.
        # Make sure to not call this under connectionlock to avoid deadlocks.
        threadutil.semaphorereset(self.semaphore, self.maxconnections)

        with self.connectionlock:
            for imapobj in self.assignedconnections + self.availableconnections:
                imapobj.logout()
            self.assignedconnections = []
            self.availableconnections = []
            self.lastowner = {}
            # reset GSSAPI state
            self.gss_vc = None
            self.gssapi = False
            self.closing = False

    def keepalive(self, timeout, event):
        """Sends a NOOP to each connection recorded.

        It will wait a maximum of timeout seconds between doing this, and will
        continue to do so until the Event object as passed is true.  This method
        is expected to be invoked in a separate thread, which should be join()'d
        after the event is set."""

        self.ui.debug('imap', 'keepalive thread started')
        while not event.isSet():
            self.connectionlock.acquire()
            numconnections = len(self.assignedconnections) + \
                             len(self.availableconnections)
            self.connectionlock.release()

            threads = []
            for i in range(numconnections):
                self.ui.debug('imap', 'keepalive: processing connection %d of %d' %
                              (i, numconnections))
                if len(self.idlefolders) > i:
                    # IDLE thread
                    idler = IdleThread(self, self.idlefolders[i])
                else:
                    # NOOP thread
                    idler = IdleThread(self)
                idler.start()
                threads.append(idler)

            self.ui.debug('imap', 'keepalive: waiting for timeout')
            event.wait(timeout)
            self.ui.debug('imap', 'keepalive: after wait')

            for idler in threads:
                # Make sure all the commands have completed.
                idler.stop()
                idler.join()
            self.ui.debug('imap', 'keepalive: all threads joined')
        self.ui.debug('imap', 'keepalive: event is set; exiting')
        return

    def releaseconnection(self, connection, drop_conn=False):
        """Releases a connection, returning it to the pool.

        :param connection: Connection object
        :param drop_conn: If True, the connection will be released and
           not be reused. This can be used to indicate broken connections."""

        if connection is None:
            return  # Noop on bad connection.

        self.connectionlock.acquire()
        try:
            self.assignedconnections.remove(connection)
        except ValueError:
            self.connectionlock.release()
            return
        # Don't reuse broken connections
        if connection.Terminate or drop_conn:
            connection.logout()
        else:
            self.availableconnections.append(connection)
        self.connectionlock.release()
        self.semaphore.release()


class IdleThread:
    def __init__(self, parent, folder=None):
        """If invoked without 'folder', perform a NOOP and wait for
        self.stop() to be called. If invoked with folder, switch to IDLE
        mode and synchronize once we have a new message"""

        self.parent = parent
        self.folder = folder
        self.stop_sig = Event()
        self.ui = getglobalui()
        if folder is None:
            self.thread = Thread(target=self.noop)
        else:
            self.thread = Thread(target=self.__idle)
        self.thread.setDaemon(True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_sig.set()

    def join(self):
        self.thread.join()

    def noop(self):
        # TODO: AFAIK this is not optimal, we will send a NOOP on one
        # random connection (ie not enough to keep all connections
        # open). In case we do the noop multiple times, we can well use
        # the same connection every time, as we get a random one. This
        # function should IMHO send a noop on ALL available connections
        # to the server.
        imapobj = self.parent.acquireconnection()
        try:
            imapobj.noop()
        except imapobj.abort:
            self.ui.warn('Attempting NOOP on dropped connection %s' %
                         imapobj.identifier)
            self.parent.releaseconnection(imapobj, True)
            imapobj = None
        finally:
            if imapobj:
                self.parent.releaseconnection(imapobj)
                self.stop_sig.wait()  # wait until we are supposed to quit

    def __dosync(self):
        remoterepos = self.parent.repos
        account = remoterepos.account
        remoterepos = account.remoterepos
        remotefolder = remoterepos.getfolder(self.folder, decode=False)

        hook = account.getconf('presynchook', '')
        account.callhook(hook, "idle")
        offlineimap.accounts.syncfolder(account, remotefolder, quick=False)
        hook = account.getconf('postsynchook', '')
        account.callhook(hook, "idle")

        ui = getglobalui()
        ui.unregisterthread(current_thread())  # syncfolder registered the thread

    def __idle(self):
        """Invoke IDLE mode until timeout or self.stop() is invoked."""

        def callback(args):
            """IDLE callback function invoked by imaplib2.

            This is invoked when a) The IMAP server tells us something
            while in IDLE mode, b) we get an Exception (e.g. on dropped
            connections, or c) the standard imaplib IDLE timeout of 29
            minutes kicks in."""

            result, cb_arg, exc_data = args
            if exc_data is None and not self.stop_sig.isSet():
                # No Exception, and we are not supposed to stop:
                self.needsync = True
            self.stop_sig.set()  # Continue to sync.

        def noop(imapobj):
            """Factorize the noop code."""

            try:
                # End IDLE mode with noop, imapobj can point to a dropped conn.
                imapobj.noop()
            except imapobj.abort:
                self.ui.warn('Attempting NOOP on dropped connection %s' %
                             imapobj.identifier)
                self.parent.releaseconnection(imapobj, True)
            else:
                self.parent.releaseconnection(imapobj)

        while not self.stop_sig.isSet():
            self.needsync = False

            success = False  # Successfully selected FOLDER?
            while not success:
                imapobj = self.parent.acquireconnection()
                try:
                    imapobj.select(imaputil.foldername_to_imapname(self.folder))
                except OfflineImapError as e:
                    if e.severity == OfflineImapError.ERROR.FOLDER_RETRY:
                        # Connection closed, release connection and retry.
                        self.ui.error(e, exc_info()[2])
                        self.parent.releaseconnection(imapobj, True)
                    elif e.severity == OfflineImapError.ERROR.FOLDER:
                        # Just continue the process on such error for now.
                        self.ui.error(e, exc_info()[2])
                        self.parent.releaseconnection(imapobj, True)
                    else:
                        # Stops future attempts to sync this account.
                        self.parent.releaseconnection(imapobj, True)
                        raise
                else:
                    success = True
            if "IDLE" in imapobj.capabilities:
                imapobj.idle(callback=callback)
            else:
                self.ui.warn("IMAP IDLE not supported on server '%s'."
                             "Sleep until next refresh cycle." % imapobj.identifier)
            self.stop_sig.wait()  # self.stop() or IDLE callback are invoked.
            noop(imapobj)

            if self.needsync:
                # Here not via self.stop, but because IDLE responded. Do
                # another round and invoke actual syncing.
                self.stop_sig.clear()
                self.__dosync()

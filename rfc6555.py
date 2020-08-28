""" Python implementation of the Happy Eyeballs Algorithm described in RFC 6555. """

# Copyright 2017 Seth Michael Larson
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import errno
import socket
from selectors2 import DefaultSelector, EVENT_WRITE

# time.perf_counter() is defined in Python 3.3
try:
    from time import perf_counter
except (ImportError, AttributeError):
    from time import time as perf_counter


# This list is due to socket.error and IOError not being a
# subclass of OSError until later versions of Python.
_SOCKET_ERRORS = (socket.error, OSError, IOError)


# Detects whether an IPv6 socket can be allocated.
def _detect_ipv6():
    if getattr(socket, 'has_ipv6', False) and hasattr(socket, 'AF_INET6'):
        _sock = None
        try:
            _sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
            _sock.bind(('::1', 0))
            return True
        except _SOCKET_ERRORS:
            if _sock:
                _sock.close()
    return False


_HAS_IPV6 = _detect_ipv6()

# These are error numbers for asynchronous operations which can
# be safely ignored by RFC 6555 as being non-errors.
_ASYNC_ERRNOS = set([errno.EINPROGRESS,
                     errno.EAGAIN,
                     errno.EWOULDBLOCK])
if hasattr(errno, 'WSAWOULDBLOCK'):
    _ASYNC_ERRNOS.add(errno.WSAWOULDBLOCK)

_DEFAULT_CACHE_DURATION = 60 * 10  # 10 minutes according to the RFC.

# This value that can be used to disable RFC 6555 globally.
RFC6555_ENABLED = _HAS_IPV6

__all__ = ['RFC6555_ENABLED',
           'create_connection',
           'cache']

__version__ = '0.0.0'
__author__ = 'Seth Michael Larson'
__email__ = 'sethmichaellarson@protonmail.com'
__license__ = 'Apache-2.0'


class _RFC6555CacheManager(object):
    def __init__(self):
        self.validity_duration = _DEFAULT_CACHE_DURATION
        self.enabled = True
        self.entries = {}

    def add_entry(self, address, family):
        if self.enabled:
            current_time = perf_counter()

            # Don't over-write old entries to reset their expiry.
            if address not in self.entries or self.entries[address][1] > current_time:
                self.entries[address] = (family, current_time + self.validity_duration)

    def get_entry(self, address):
        if not self.enabled or address not in self.entries:
            return None

        family, expiry = self.entries[address]
        if perf_counter() > expiry:
            del self.entries[address]
            return None

        return family


cache = _RFC6555CacheManager()


class _RFC6555ConnectionManager(object):
    def __init__(self, address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None):
        self.address = address
        self.timeout = timeout
        self.source_address = source_address

        self._error = None
        self._selector = DefaultSelector()
        self._sockets = []
        self._start_time = None

    def create_connection(self):
        self._start_time = perf_counter()

        host, port = self.address
        addr_info = socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
        ret = self._connect_with_cached_family(addr_info)

        # If it's a list, then these are the remaining values to try.
        if isinstance(ret, list):
            addr_info = ret
        else:
            cache.add_entry(self.address, ret.family)
            return ret

        # If we don't get any results back then just skip to the end.
        if not addr_info:
            raise socket.error('getaddrinfo returns an empty list')

        sock = self._attempt_connect_with_addr_info(addr_info)

        if sock:
            cache.add_entry(self.address, sock.family)
            return sock
        elif self._error:
            raise self._error
        else:
            raise socket.timeout()

    def _attempt_connect_with_addr_info(self, addr_info):
        sock = None
        try:
            for family, socktype, proto, _, sockaddr in addr_info:
                self._create_socket(family, socktype, proto, sockaddr)
                sock = self._wait_for_connection(False)
                if sock:
                    break
            if sock is None:
                sock = self._wait_for_connection(True)
        finally:
            self._remove_all_sockets()
        return sock

    def _connect_with_cached_family(self, addr_info):
        family = cache.get_entry(self.address)
        if family is None:
            return addr_info

        is_family = []
        not_family = []

        for value in addr_info:
            if value[0] == family:
                is_family.append(value)
            else:
                not_family.append(value)

        sock = self._attempt_connect_with_addr_info(is_family)
        if sock is not None:
            return sock

        return not_family

    def _create_socket(self, family, socktype, proto, sockaddr):
        sock = None
        try:
            sock = socket.socket(family, socktype, proto)

            # If we're using the 'default' socket timeout we have
            # to set it to a real value here as this is the earliest
            # opportunity to without pre-allocating a socket just for
            # this purpose.
            if self.timeout is socket._GLOBAL_DEFAULT_TIMEOUT:
                self.timeout = sock.gettimeout()

            if self.source_address:
                sock.bind(self.source_address)

            # Make the socket non-blocking so we can use our selector.
            sock.settimeout(0.0)

            if self._is_acceptable_errno(sock.connect_ex(sockaddr)):
                self._selector.register(sock, EVENT_WRITE)
                self._sockets.append(sock)

        except _SOCKET_ERRORS as e:
            self._error = e
            if sock is not None:
                _RFC6555ConnectionManager._close_socket(sock)

    def _wait_for_connection(self, last_wait):
        self._remove_all_errored_sockets()

        # This is a safe-guard to make sure sock.gettimeout() is called in the
        # case that the default socket timeout is used. If there are no
        # sockets then we may not have called sock.gettimeout() yet.
        if not self._sockets:
            return None

        # If this is the last time we're waiting for connections
        # then we should wait until we should raise a timeout
        # error, otherwise we should only wait >0.2 seconds as
        # recommended by RFC 6555.
        if last_wait:
            if self.timeout is None:
                select_timeout = None
            else:
                select_timeout = self._get_remaining_time()
        else:
            select_timeout = self._get_select_time()

        # Wait for any socket to become writable as a sign of being connected.
        for key, _ in self._selector.select(select_timeout):
            sock = key.fileobj

            if not self._is_socket_errored(sock):

                # Restore the old proper timeout of the socket.
                sock.settimeout(self.timeout)

                # Remove it from this list to exempt the socket from cleanup.
                self._sockets.remove(sock)
                self._selector.unregister(sock)
                return sock

        return None

    def _get_remaining_time(self):
        if self.timeout is None:
            return None
        return max(self.timeout - (perf_counter() - self._start_time), 0.0)

    def _get_select_time(self):
        if self.timeout is None:
            return 0.2
        return min(0.2, self._get_remaining_time())

    def _remove_all_errored_sockets(self):
        socks = []
        for sock in self._sockets:
            if self._is_socket_errored(sock):
                socks.append(sock)
        for sock in socks:
            self._selector.unregister(sock)
            self._sockets.remove(sock)
            _RFC6555ConnectionManager._close_socket(sock)

    @staticmethod
    def _close_socket(sock):
        try:
            sock.close()
        except _SOCKET_ERRORS:
            pass

    def _is_acceptable_errno(self, errno):
        if errno == 0 or errno in _ASYNC_ERRNOS:
            return True
        self._error = socket.error()
        self._error.errno = errno
        return False

    def _is_socket_errored(self, sock):
        errno = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
        return not self._is_acceptable_errno(errno)

    def _remove_all_sockets(self):
        for sock in self._sockets:
            self._selector.unregister(sock)
            _RFC6555ConnectionManager._close_socket(sock)
        self._sockets = []


def create_connection(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None):
    if RFC6555_ENABLED and _HAS_IPV6:
        manager = _RFC6555ConnectionManager(address, timeout, source_address)
        return manager.create_connection()
    else:
        # This code is the same as socket.create_connection() but is
        # here to make sure the same code is used across all Python versions as
        # the source_address parameter was added to socket.create_connection() in 3.2
        # This segment of code is licensed under the Python Software Foundation License
        # See LICENSE: https://github.com/python/cpython/blob/3.6/LICENSE
        host, port = address
        err = None
        for res in socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM):
            af, socktype, proto, canonname, sa = res
            sock = None
            try:
                sock = socket.socket(af, socktype, proto)
                if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                    sock.settimeout(timeout)
                if source_address:
                    sock.bind(source_address)
                sock.connect(sa)
                return sock

            except socket.error as _:
                err = _
                if sock is not None:
                    sock.close()

        if err is not None:
            raise err
        else:
            raise socket.error("getaddrinfo returns an empty list")

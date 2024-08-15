# IMAP folder support
# Copyright (C) 2002-2016 John Goerzen & contributors.
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

import random
import binascii
import re
import time
from sys import exc_info
from offlineimap import imaputil, imaplibutil, OfflineImapError
from offlineimap import globals
from imaplib2 import MonthNames
from .Base import BaseFolder
from email.errors import NoBoundaryInMultipartDefect

# Globals
CRLF = '\r\n'
MSGCOPY_NAMESPACE = 'MSGCOPY_'


class IMAPFolder(BaseFolder):
    def __init__(self, imapserver, name, repository, decode=True):
        # decode the folder name from IMAP4_utf_7 to utf_8 if
        # - utf8foldernames is enabled for the *account*
        # - the decode argument is given
        #   (default True is used when the folder name is the result of
        #    querying the IMAP server, while False is used when creating
        #    a folder object from a locally available utf_8 name)
        # In any case the given name is first dequoted.
        name = imaputil.dequote(name)
        if decode and repository.account.utf_8_support:
            name = imaputil.IMAP_utf8(name)
        self.sep = imapserver.delim
        super(IMAPFolder, self).__init__(name, repository)
        if repository.getdecodefoldernames():
            self.visiblename = imaputil.decode_mailbox_name(self.visiblename)
        self.idle_mode = False
        self.expunge = repository.getexpunge()
        self.root = None  # imapserver.root
        self.imapserver = imapserver
        self.randomgenerator = random.Random()
        # self.ui is set in BaseFolder.
        self.imap_query = ['BODY.PEEK[]']

        # number of times to retry fetching messages
        self.retrycount = self.repository.getconfint('retrycount', 2)

        fh_conf = self.repository.account.getconf('filterheaders', '')
        self.filterheaders = [h for h in re.split(r'\s*,\s*', fh_conf) if h]

        # self.copy_ignoreUIDs is used by BaseFolder.
        self.copy_ignoreUIDs = repository.get_copy_ignore_UIDs(
            self.getvisiblename())
        if self.repository.getidlefolders():
            self.idle_mode = True

    def __selectro(self, imapobj, force=False):
        """Select this folder when we do not need write access.

        Prefer SELECT to EXAMINE if we can, since some servers
        (Courier) do not stabilize UID validity until the folder is
        selected.
        .. todo: Still valid? Needs verification
        :param: Enforce new SELECT even if we are on that folder already.
        :returns: raises :exc:`OfflineImapError` severity FOLDER on error"""
        try:
            imapobj.select(self.getfullIMAPname(), force=force)
        except imapobj.readonly:
            imapobj.select(self.getfullIMAPname(), readonly=True, force=force)

    def getfullIMAPname(self):
        name = self.getfullname()
        if self.repository.account.utf_8_support:
            name = imaputil.utf8_IMAP(name)
        return imaputil.foldername_to_imapname(name)

    # Interface from BaseFolder
    def suggeststhreads(self):
        singlethreadperfolder_default = False
        if self.idle_mode is True:
            singlethreadperfolder_default = True

        onethread = self.config.getdefaultboolean(
            "Repository %s" % self.repository.getname(),
            "singlethreadperfolder", singlethreadperfolder_default)
        if onethread is True:
            return False
        return not globals.options.singlethreading

    # Interface from BaseFolder
    def waitforthread(self):
        self.imapserver.connectionwait()

    def getmaxage(self):
        if self.config.getdefault("Account %s" %
                                  self.accountname, "maxage", None):
            raise OfflineImapError(
                "maxage is not supported on IMAP-IMAP sync",
                OfflineImapError.ERROR.REPO,
                exc_info()[2])

    # Interface from BaseFolder
    def getinstancelimitnamespace(self):
        return MSGCOPY_NAMESPACE + self.repository.getname()

    # Interface from BaseFolder
    def get_uidvalidity(self):
        """Retrieve the current connections UIDVALIDITY value

        UIDVALIDITY value will be cached on the first call.
        :returns: The UIDVALIDITY as (long) number."""

        if hasattr(self, '_uidvalidity'):
            # Use cached value if existing.
            return self._uidvalidity
        imapobj = self.imapserver.acquireconnection()
        try:
            # SELECT (if not already done) and get current UIDVALIDITY.
            self.__selectro(imapobj)
            typ, uidval = imapobj.response('UIDVALIDITY')
            assert uidval != [None] and uidval is not None, \
                "response('UIDVALIDITY') returned [None]!"
            self._uidvalidity = int(uidval[-1])
            return self._uidvalidity
        finally:
            self.imapserver.releaseconnection(imapobj)

    # Interface from BaseFolder
    def quickchanged(self, statusfolder):
        # An IMAP folder has definitely changed if the number of
        # messages or the UID of the last message have changed.  Otherwise
        # only flag changes could have occurred.
        retry = True  # Should we attempt another round or exit?
        imapdata = None
        while retry:
            retry = False
            imapobj = self.imapserver.acquireconnection()
            try:
                # Select folder and get number of messages.
                restype, imapdata = imapobj.select(self.getfullIMAPname(), True,
                                                   True)
                self.imapserver.releaseconnection(imapobj)
            except OfflineImapError as e:
                # Retry on dropped connections, raise otherwise.
                self.imapserver.releaseconnection(imapobj, True)
                if e.severity == OfflineImapError.ERROR.FOLDER_RETRY:
                    retry = True
                else:
                    raise
            except:
                # Cleanup and raise on all other errors.
                self.imapserver.releaseconnection(imapobj, True)
                raise
        # 1. Some mail servers do not return an EXISTS response
        # if the folder is empty.  2. ZIMBRA servers can return
        # multiple EXISTS replies in the form 500, 1000, 1500,
        # 1623 so check for potentially multiple replies.
        if imapdata == [None]:
            return True
        maxmsgid = 0
        for msgid in imapdata:
            maxmsgid = max(int(msgid), maxmsgid)
        # Different number of messages than last time?
        if maxmsgid != statusfolder.getmessagecount():
            return True
        return False

    def _msgs_to_fetch(self, imapobj, min_date=None, min_uid=None):
        """Determines sequence numbers of messages to be fetched.

        Message sequence numbers (MSNs) are more easily compacted
        into ranges which makes transactions slightly faster.

        Arguments:
        - imapobj: instance of IMAPlib
        - min_date (optional): a time_struct; only fetch messages newer
          than this
        - min_uid (optional): only fetch messages with UID >= min_uid

        This function should be called with at MOST one of min_date OR
        min_uid set but not BOTH.

        Returns: range(s) for messages or None if no messages
        are to be fetched."""

        def search(search_conditions):
            """Actually request the server with the specified conditions.

            Returns: range(s) for messages or None if no messages
            are to be fetched."""
            try:
                res_type, res_data = imapobj.search(None, search_conditions)
                if res_type != 'OK':
                    msg = "SEARCH in folder [%s]%s failed. " \
                          "Search string was '%s'. " \
                          "Server responded '[%s] %s'" % \
                          (self.getrepository(), self, search_cond,
                           res_type, res_data)
                    raise OfflineImapError(msg, OfflineImapError.ERROR.FOLDER)
            except Exception as e:
                msg = "SEARCH in folder [%s]%s failed. "\
                      "Search string was '%s'. Error: %s" % \
                      (self.getrepository(), self, search_cond, str(e))
                raise OfflineImapError(msg, OfflineImapError.ERROR.FOLDER)

            """
            In Py2, with IMAP, imaplib2 returned a list of one element string.
              ['1, 2, 3, ...'] -> in Py3 is [b'1 2 3,...']
            In Py2, with Davmail, imaplib2 returned a list of strings.
              ['1', '2', '3', ...] -> in Py3 should be [b'1', b'2', b'3',...]

            In my tests with Py3, I get a list with one element: [b'1 2 3 ...']
            Then I convert the values to string and I get ['1 2 3 ...']

            With Davmail, it should be [b'1', b'2', b'3',...]
            When I convert the values to string, I get ['1', '2', '3',...]
            """
            res_data = [x.decode('utf-8') for x in res_data]

            # Then, I can do the check in the same way than Python 2
            # with string comparison:
            if len(res_data) > 0 and (' ' in res_data[0] or res_data[0] == ''):
                res_data = res_data[0].split()
            # Some servers are broken.
            if 0 in res_data:
                self.ui.warn("server returned UID with 0; ignoring.")
                res_data.remove(0)
            return res_data

        a = self.getfullIMAPname()
        res_type, imapdata = imapobj.select(a, True, True)

        if imapdata == [None] or imapdata[0] == b'0':
            # Empty folder, no need to populate message list.
            return None

        # imaplib2 returns the type as string, like "OK" but
        # returns imapdata as list of bytes, like [b'0'] so we need decode it
        # to use the existing code
        imapdata = [x.decode('utf-8') for x in imapdata]

        conditions = []
        # 1. min_uid condition.
        if min_uid is not None:
            conditions.append("UID %d:*" % min_uid)
        # 2. date condition.
        elif min_date is not None:
            # Find out what the oldest message is that we should look at.
            conditions.append("SINCE %02d-%s-%d" % (
                min_date[2], MonthNames[min_date[1]], min_date[0]))
        # 3. maxsize condition.
        maxsize = self.getmaxsize()
        if maxsize is not None:
            conditions.append("SMALLER %d" % maxsize)

        if len(conditions) >= 1:
            # Build SEARCH command.
            search_cond = "(%s)" % ' '.join(conditions)
            search_result = search(search_cond)
            return imaputil.uid_sequence(search_result)

        # By default consider all messages in this folder.
        return '1:*'

    # Interface from BaseFolder
    def msglist_item_initializer(self, uid):
        return {'uid': uid, 'flags': set(), 'time': 0}

    # Interface from BaseFolder
    def cachemessagelist(self, min_date=None, min_uid=None):
        self.ui.loadmessagelist(self.repository, self)
        self.dropmessagelistcache()

        imapobj = self.imapserver.acquireconnection()
        try:
            msgsToFetch = self._msgs_to_fetch(
                imapobj, min_date=min_date, min_uid=min_uid)
            if not msgsToFetch:
                return  # No messages to sync.

            # Get the flags and UIDs for these. single-quotes prevent
            # imaplib2 from quoting the sequence.
            fetch_msg = "%s" % msgsToFetch
            self.ui.debug('imap', "calling imaplib2 fetch command: %s %s" %
                          (fetch_msg, '(FLAGS UID INTERNALDATE)'))
            res_type, response = imapobj.fetch(
                fetch_msg, '(FLAGS UID INTERNALDATE)')
            if res_type != 'OK':
                msg = "FETCHING UIDs in folder [%s]%s failed. "\
                      "Server responded '[%s] %s'" % \
                      (self.getrepository(), self, res_type, response)
                raise OfflineImapError(msg, OfflineImapError.ERROR.FOLDER)
        finally:
            self.imapserver.releaseconnection(imapobj)

        for messagestr in response:
            # Looks like: '1 (FLAGS (\\Seen Old) UID 4807)' or None if no msg.
            # Discard initial message number.
            if messagestr is None:
                continue
            messagestr = messagestr.decode('utf-8').split(' ', 1)[1]
            options = imaputil.flags2hash(messagestr)
            if 'UID' not in options:
                self.ui.warn('No UID in message with options %s' %
                             str(options), minor=1)
            else:
                uid = int(options['UID'])
                self.messagelist[uid] = self.msglist_item_initializer(uid)
                flags = imaputil.flagsimap2maildir(options['FLAGS'])
                keywords = imaputil.flagsimap2keywords(options['FLAGS'])
                rtime = imaplibutil.Internaldate2epoch(
                    messagestr.encode('utf-8'))
                self.messagelist[uid] = {'uid': uid,
                                         'flags': flags,
                                         'time': rtime,
                                         'keywords': keywords}
        self.ui.messagelistloaded(self.repository, self, self.getmessagecount())

    # Interface from BaseFolder
    def getmessage(self, uid):
        """Retrieve message with UID from the IMAP server (incl body).

        After this function all CRLFs will be transformed to '\n'.

        :returns: the message body or throws and OfflineImapError
                  (probably severity MESSAGE) if e.g. no message with
                  this UID could be found.
        """

        data = self._fetch_from_imap(str(uid), self.retrycount)

        # Data looks now e.g.
        # ['320 (17061 BODY[] {2565}',<email.message.EmailMessage object>]
        # Is a list of two elements. Message is at [1]
        msg = data[1]

        if self.ui.is_debugging('imap'):
            # Optimization: don't create the debugging objects unless needed
            msg_s = msg.as_string(policy=self.policy['8bit-RFC'])
            if len(msg_s) > 200:
                dbg_output = "%s...%s" % (msg_s[:150], msg_s[-50:])
            else:
                dbg_output = msg_s

            self.ui.debug('imap', "Returned object from fetching %d: '%s'" %
                          (uid, dbg_output))

        return msg

    # Interface from BaseFolder
    def getmessagetime(self, uid):
        return self.messagelist[uid]['time']

    # Interface from BaseFolder
    def getmessageflags(self, uid):
        return self.messagelist[uid]['flags']

    # Interface from BaseFolder
    def getmessagekeywords(self, uid):
        return self.messagelist[uid]['keywords']

    def __generate_randomheader(self, msg, policy=None):
        """Returns a unique X-OfflineIMAP header

         Generate an 'X-OfflineIMAP' mail header which contains a random
         unique value (which is based on the mail content, and a random
         number). This header allows us to fetch a mail after APPENDing
         it to an IMAP server and thus find out the UID that the server
         assigned it.

        :returns: (headername, headervalue) tuple, consisting of strings
                  headername == 'X-OfflineIMAP' and headervalue will be a
                  random string
        """

        headername = 'X-OfflineIMAP'
        if policy is None:
            output_policy = self.policy['8bit-RFC']
        else:
            output_policy = policy
        # We need a random component too. If we ever upload the same
        # mail twice (e.g. in different folders), we would still need to
        # get the UID for the correct one. As we won't have too many
        # mails with identical content, the randomness requirements are
        # not extremly critial though.

        # Compute unsigned crc32 of 'msg' (as bytes) into a unique hash.
        # NB: crc32 returns unsigned only starting with python 3.0.
        headervalue = '{}-{}'.format(
          (binascii.crc32(msg.as_bytes(policy=output_policy)) & 0xffffffff),
          self.randomgenerator.randint(0, 9999999999))
        return headername, headervalue

    def __savemessage_searchforheader(self, imapobj, headername, headervalue):
        self.ui.debug('imap',
                      '__savemessage_searchforheader called for %s: %s' %
                      (headername, headervalue))
        # Now find the UID it got.
        headervalue = imapobj._quote(headervalue)
        try:
            matchinguids = imapobj.uid('search', 'HEADER',
                                       headername, headervalue)[1][0]

            # Returned value is type bytes
            matchinguids = matchinguids.decode('utf-8')

        except imapobj.error as err:
            # IMAP server doesn't implement search or had a problem.
            self.ui.debug('imap',
                          "__savemessage_searchforheader: got IMAP error '%s' "
                          "while attempting to UID SEARCH for message with "
                          "header %s" % (err, headername))
            return 0
        self.ui.debug('imap',
                      "__savemessage_searchforheader got initial "
                      "matchinguids: " + repr(matchinguids))

        if matchinguids == '':
            self.ui.debug('imap',
                          "__savemessage_searchforheader: UID SEARCH "
                          "for message with header %s yielded no results" %
                          headername)
            return 0

        matchinguids = matchinguids.split(' ')
        self.ui.debug('imap', '__savemessage_searchforheader: matchinguids now '
                      + repr(matchinguids))
        if len(matchinguids) != 1 or matchinguids[0] is None:
            raise OfflineImapError(
                "While attempting to find UID for message with "
                "header %s, got wrong-sized matchinguids of %s" %
                (headername, str(matchinguids)),
                OfflineImapError.ERROR.MESSAGE
            )
        return int(matchinguids[0])

    def __savemessage_fetchheaders(self, imapobj, headername, headervalue):
        """ We fetch all new mail headers and search for the right
        X-OfflineImap line by hand. The response from the server has form:
        (
          'OK',
          [
            (
              '185 (RFC822.HEADER {1789}',
              '... mail headers ...'
            ),
            ' UID 2444)',
            (
              '186 (RFC822.HEADER {1789}',
              '... 2nd mail headers ...'
            ),
            ' UID 2445)'
          ]
        )
        We need to locate the UID just after mail headers containing our
        X-OfflineIMAP line.

        Returns UID when found, 0 when not found."""

        self.ui.debug('imap', '__savemessage_fetchheaders called for %s: %s' %
                      (headername, headervalue))

        # Run "fetch X:* rfc822.header".
        # Since we stored the mail we are looking for just recently, it would
        # not be optimal to fetch all messages. So we'll find highest message
        # UID in our local messagelist and search from there (exactly from
        # UID+1). That works because UIDs are guaranteed to be unique and
        # ascending.

        if self.getmessagelist():
            start = 1 + max(self.getmessagelist().keys())
        else:
            # Folder was empty - start from 1.
            start = 1

        result = imapobj.uid('FETCH', '%d:*' % start, 'rfc822.header')
        if result[0] != 'OK':
            msg = 'Error fetching mail headers: %s' % '. '.join(result[1])
            raise OfflineImapError(msg, OfflineImapError.ERROR.MESSAGE)

        # result is like:
        # [
        #    ('185 (RFC822.HEADER {1789}', '... mail headers ...'),
        #      ' UID 2444)',
        #    ('186 (RFC822.HEADER {1789}', '... 2nd mail headers ...'),
        #      ' UID 2445)'
        # ]
        result = result[1]

        found = None
        # item is like:
        # ('185 (RFC822.HEADER {1789}', '... mail headers ...'), ' UID 2444)'
        for item in result:
            if found is None and type(item) == tuple:
                # Decode the value
                item = [x.decode('utf-8') for x in item]

                # Walk just tuples.
                if re.search(r"(?:^|\\r|\\n)%s:\s*%s(?:\\r|\\n)" %
                             (headername, headervalue),
                             item[1], flags=re.IGNORECASE):
                    found = item[0]
            elif found is not None:
                if isinstance(item, bytes):
                    item = item.decode('utf-8')
                    uid = re.search(r"UID\s+(\d+)", item, flags=re.IGNORECASE)
                    if uid:
                        return int(uid.group(1))
                    else:
                        # This parsing is for Davmail.
                        # https://github.com/OfflineIMAP/offlineimap/issues/479
                        # item is like:
                        # ')'
                        # and item[0] stored in "found" is like:
                        # '1694 (UID 1694 RFC822.HEADER {1294}'
                        uid = re.search(r"\d+\s+\(UID\s+(\d+)", found,
                                        flags=re.IGNORECASE)
                        if uid:
                            return int(uid.group(1))

                        self.ui.warn("Can't parse FETCH response, "
                                     "can't find UID in %s" % item)
                        self.ui.debug('imap', "Got: %s" % repr(result))
                else:
                    self.ui.warn("Can't parse FETCH response, "
                                 "we awaited string: %s" % repr(item))

        return 0

    def __getmessageinternaldate(self, msg, rtime=None):
        """Parses mail and returns an INTERNALDATE string

        It will use information in the following order, falling back as an
        attempt fails:
          - rtime parameter
          - Date header of email

        We return None, if we couldn't find a valid date. In this case
        the IMAP server will use the server local time when appening
        (per RFC).

        Note, that imaplib's Time2Internaldate is inherently broken as
        it returns localized date strings which are invalid for IMAP
        servers. However, that function is called for *every* append()
        internally. So we need to either pass in `None` or the correct
        string (in which case Time2Internaldate() will do nothing) to
        append(). The output of this function is designed to work as
        input to the imapobj.append() function.

        TODO: We should probably be returning a bytearray rather than a
        string here, because the IMAP server will expect plain
        ASCII. However, imaplib.Time2INternaldate currently returns a
        string so we go with the same for now.

        :param rtime: epoch timestamp to be used rather than analyzing
                  the email.
        :returns: string in the form of "DD-Mmm-YYYY HH:MM:SS +HHMM"
                  (including double quotes) or `None` in case of failure
                  (which is fine as value for append)."""

        if rtime is None:
            rtime = self.get_message_date(msg)
            if rtime is None:
                return None
        datetuple = time.localtime(rtime)

        try:
            # Check for invalid dates.
            if datetuple[0] < 1981:
                raise ValueError

            # Check for invalid dates.
            datetuple_check = time.localtime(time.mktime(datetuple))
            if datetuple[:2] != datetuple_check[:2]:
                raise ValueError

        except (ValueError, OverflowError):
            # Argh, sometimes it's a valid format but year is 0102
            # or something.  Argh.  It seems that Time2Internaldate
            # will rause a ValueError if the year is 0102 but not 1902,
            # but some IMAP servers nonetheless choke on 1902.
            self.ui.debug('imap', "Message with invalid date %s. "
                                  "Server will use local time." % datetuple)
            return None

        # Produce a string representation of datetuple that works as
        # INTERNALDATE.
        num2mon = {1: 'Jan', 2: 'Feb', 3: 'Mar',
                   4: 'Apr', 5: 'May', 6: 'Jun',
                   7: 'Jul', 8: 'Aug', 9: 'Sep',
                   10: 'Oct', 11: 'Nov', 12: 'Dec'}

        # tm_isdst coming from email.parsedate is not usable, we still use it
        # here, mhh.
        if datetuple.tm_isdst == 1:
            zone = -time.altzone
        else:
            zone = -time.timezone
        offset_h, offset_m = divmod(zone // 60, 60)

        internaldate = '"%02d-%s-%04d %02d:%02d:%02d %+03d%02d"' % \
                       (datetuple.tm_mday, num2mon[datetuple.tm_mon],
                        datetuple.tm_year, datetuple.tm_hour,
                        datetuple.tm_min, datetuple.tm_sec,
                        offset_h, offset_m)

        return internaldate

    # Interface from BaseFolder
    def savemessage(self, uid, msg, flags, rtime):
        """Save the message on the Server

        This backend always assigns a new uid, so the uid arg is ignored.

        This function will update the self.messagelist dict to contain
        the new message after sucessfully saving it.

        See folder/Base for details. Note that savemessage() does not
        check against dryrun settings, so you need to ensure that
        savemessage is never called in a dryrun mode.

        :param uid: Message UID
        :param msg: Message Object
        :param flags: Message flags
        :param rtime: A timestamp to be used as the mail date
        :returns: the UID of the new message as assigned by the server. If the
                  message is saved, but it's UID can not be found, it will
                  return 0. If the message can't be written (folder is
                  read-only for example) it will return -1."""

        self.ui.savemessage('imap', uid, flags, self)

        # Already have it, just save modified flags.
        if uid > 0 and self.uidexists(uid):
            self.savemessageflags(uid, flags)
            return uid

        # Filter user requested headers before uploading to the IMAP server
        self.deletemessageheaders(msg, self.filterheaders)

        # Should just be able to set the policy, to use CRLF in msg output
        output_policy = self.policy['8bit-RFC']

        # Get the date of the message, so we can pass it to the server.
        date = self.__getmessageinternaldate(msg, rtime)

        # Message-ID is handy for debugging messages.
        try:
            msg_id = self.getmessageheader(msg, "message-id")
            if not msg_id:
                msg_id = '[unknown message-id]'
        except:
            msg_id = '[broken message-id]'

        retry_left = 2  # succeeded in APPENDING?
        imapobj = self.imapserver.acquireconnection()
        # NB: in the finally clause for this try we will release
        # NB: the acquired imapobj, so don't do that twice unless
        # NB: you will put another connection to imapobj.  If you
        # NB: really do need to release connection manually, set
        # NB: imapobj to None.
        try:
            while retry_left:
                # XXX: we can mangle message only once, out of the loop
                # UIDPLUS extension provides us with an APPENDUID response.
                use_uidplus = 'UIDPLUS' in imapobj.capabilities

                if not use_uidplus:
                    # Insert a random unique header that we can fetch later.
                    (headername, headervalue) = self.__generate_randomheader(
                        msg)
                    self.ui.debug('imap', 'savemessage: header is: %s: %s' %
                                  (headername, headervalue))
                    self.addmessageheader(msg, headername, headervalue)

                if self.ui.is_debugging('imap'):
                    # Optimization: don't create the debugging objects unless needed
                    msg_s = msg.as_string(policy=output_policy)
                    if len(msg_s) > 200:
                        dbg_output = "%s...%s" % (msg_s[:150], msg_s[-50:])
                    else:
                        dbg_output = msg_s
                    self.ui.debug('imap', "savemessage: date: %s, content: '%s'" %
                                  (date, dbg_output))

                try:
                    # Select folder for append and make the box READ-WRITE.
                    imapobj.select(self.getfullIMAPname())
                except imapobj.readonly:
                    # readonly exception. Return original uid to notify that
                    # we did not save the message. (see savemessage in Base.py)
                    self.ui.msgtoreadonly(self, uid)
                    return uid

                # Do the APPEND.
                try:
                    (typ, dat) = imapobj.append(
                        self.getfullIMAPname(),
                        imaputil.flagsmaildir2imap(flags),
                        date,  msg.as_bytes(policy=output_policy))
                    # This should only catch 'NO' responses since append()
                    # will raise an exception for 'BAD' responses:
                    if typ != 'OK':
                        # For example, Groupwise IMAP server
                        # can return something like:
                        #
                        #   NO APPEND The 1500 MB storage limit \
                        #   has been exceeded.
                        #
                        # In this case, we should immediately abort
                        # the repository sync and continue
                        # with the next account.
                        err_msg = \
                            "Saving msg (%s) in folder '%s', " \
                            "repository '%s' failed (abort). " \
                            "Server responded: %s %s\n" % \
                            (msg_id, self, self.getrepository(), typ, dat)
                        raise OfflineImapError(err_msg, OfflineImapError.ERROR.REPO)
                    retry_left = 0  # Mark as success.
                except imapobj.abort as e:
                    # Connection has been reset, release connection and retry.
                    retry_left -= 1
                    self.imapserver.releaseconnection(imapobj, True)
                    imapobj = self.imapserver.acquireconnection()
                    if not retry_left:
                        raise OfflineImapError(
                            "Saving msg (%s) in folder '%s', "
                            "repository '%s' failed (abort). "
                            "Server responded: %s\n" %
                            (msg_id, self, self.getrepository(), str(e)),
                            OfflineImapError.ERROR.MESSAGE,
                            exc_info()[2])

                    # XXX: is this still needed?
                    self.ui.error(e, exc_info()[2])
                except imapobj.error as e:  # APPEND failed
                    # If the server responds with 'BAD', append()
                    # raise()s directly.  So we catch that too.
                    # drop conn, it might be bad.
                    self.imapserver.releaseconnection(imapobj, True)
                    imapobj = None
                    raise OfflineImapError(
                        "Saving msg (%s) folder '%s', repo '%s'"
                        "failed (error). Server responded: %s\n" %
                        (msg_id, self, self.getrepository(), str(e)),
                        OfflineImapError.ERROR.MESSAGE,
                        exc_info()[2])

            # Checkpoint. Let it write out stuff, etc. Eg searches for
            # just uploaded messages won't work if we don't do this.
            (typ, dat) = imapobj.check()
            assert (typ == 'OK')

            # Get the new UID, do we use UIDPLUS?
            if use_uidplus:
                # Get new UID from the APPENDUID response, it could look
                # like OK [APPENDUID 38505 3955] APPEND completed with
                # 38505 bein folder UIDvalidity and 3955 the new UID.
                # note: we would want to use .response() here but that
                # often seems to return [None], even though we have
                # data. TODO
                resp = imapobj._get_untagged_response('APPENDUID')
                if resp == [None] or resp is None:
                    self.ui.warn("Server supports UIDPLUS but got no APPENDUID "
                                 "appending a message. Got: %s." % str(resp))
                    return 0
                try:
                    # Convert the UID from [b'4 1532'] to ['4 1532']
                    s_uid = [x.decode('utf-8') for x in resp]
                    # Now, read the UID field
                    uid = int(s_uid[-1].split(' ')[1])
                except ValueError:
                    uid = 0  # Definetly not what we should have.
                except Exception:
                    raise OfflineImapError("Unexpected response: %s" %
                                           str(resp),
                                           OfflineImapError.ERROR.MESSAGE)
                if uid == 0:
                    self.ui.warn("savemessage: Server supports UIDPLUS, but"
                                 " we got no usable UID back. APPENDUID "
                                 "reponse was '%s'" % str(resp))
            else:
                try:
                    # We don't use UIDPLUS.
                    uid = self.__savemessage_searchforheader(imapobj,
                                                             headername,
                                                             headervalue)
                    # See docs for savemessage in Base.py for explanation
                    # of this and other return values.
                    if uid == 0:
                        self.ui.debug('imap',
                                      'savemessage: attempt to get new UID '
                                      'UID failed. Search headers manually.')
                        uid = self.__savemessage_fetchheaders(imapobj,
                                                              headername,
                                                              headervalue)
                        self.ui.warn("savemessage: Searching mails for new "
                                     "Message-ID failed. "
                                     "Could not determine new UID on %s." %
                                     self.getname())
                # Something wrong happened while trying to get the UID. Explain
                # the error might be about the 'get UID' process not necesseraly
                # the APPEND.
                except Exception:
                    self.ui.warn("%s: could not determine the UID while we got "
                                 "no error while appending the "
                                 "email with '%s: %s'" %
                                 (self.getname(), headername, headervalue))
                    raise
        finally:
            if imapobj:
                self.imapserver.releaseconnection(imapobj)

        if uid:  # Avoid UID FETCH 0 crash happening later on.
            self.messagelist[uid] = self.msglist_item_initializer(uid)
            self.messagelist[uid]['flags'] = flags

        self.ui.debug('imap', 'savemessage: returning new UID %d' % uid)
        return uid

    def _fetch_from_imap(self, uids, retry_num=1):
        """Fetches data from IMAP server.

        Arguments:
        - uids: message UIDS (OfflineIMAP3: First UID returned only)
        - retry_num: number of retries to make

        Returns: data obtained by this query."""

        imapobj = self.imapserver.acquireconnection()
        try:
            query = "(%s)" % (" ".join(self.imap_query))
            fails_left = retry_num  # Retry on dropped connection.
            while fails_left:
                try:
                    imapobj.select(self.getfullIMAPname(), readonly=True)
                    res_type, data = imapobj.uid('fetch', uids, query)
                    break
                except imapobj.abort as e:
                    fails_left -= 1
                    # self.ui.error() will show the original traceback.
                    if fails_left <= 0:
                        message = ("%s, while fetching msg %r in folder %r."
                                   " Max retry reached (%d)" %
                                   (e, uids, self.name, retry_num))
                        raise OfflineImapError(message,
                                               OfflineImapError.ERROR.MESSAGE)
                    self.ui.error("%s. While fetching msg %r in folder %r."
                                  " Query: %s Retrying (%d/%d)" % (
                                      e, uids, self.name, query,
                                      retry_num - fails_left, retry_num))
                    # Release dropped connection, and get a new one.
                    self.imapserver.releaseconnection(imapobj, True)
                    imapobj = self.imapserver.acquireconnection()
        finally:
            # The imapobj here might be different than the one created before
            # the ``try`` clause. So please avoid transforming this to a nice
            # ``with`` without taking this into account.
            self.imapserver.releaseconnection(imapobj)

        # Ensure to not consider unsolicited FETCH responses caused by flag
        # changes from concurrent connections.  These appear as strings in
        # 'data' (the BODY response appears as a tuple).  This should leave
        # exactly one response.
        if res_type == 'OK':
            data = [res for res in data if not isinstance(res, bytes)]

        # Could not fetch message.  Note: it is allowed by rfc3501 to return any
        # data for the UID FETCH command.
        if data == [None] or res_type != 'OK' or len(data) != 1:
            severity = OfflineImapError.ERROR.MESSAGE
            reason = "IMAP server '%s' failed to fetch messages UID '%s'. " \
                     "Server responded: %s %s" % (self.getrepository(), uids,
                                                  res_type, data)
            if data == [None] or len(data) < 1:
                # IMAP server did not find a message with this UID.
                reason = "IMAP server '%s' does not have a message " \
                         "with UID '%s'" % (self.getrepository(), uids)
            raise OfflineImapError(reason, severity)

        # JI: In offlineimap, this function returned a tuple of strings for each
        # fetched UID, offlineimap3 calls to the imap object return bytes and so
        # originally a fixed, utf-8 conversion was done and *only* the first
        # response (d[0]) was returned.  Note that this alters the behavior
        # between code bases.  However, it seems like a single UID is the intent
        # of this function so retaining the modfication here for now.
        # 
        # TODO: Can we assume the server response containing the meta data is
        # always 'utf-8' encoded?  Assuming yes for now.
        #
        # Convert responses, d[0][0], into a 'utf-8' string (from bytes) and
        # Convert email, d[0][1], into a message object (from bytes) 

        ndata0 = data[0][0].decode('utf-8')
        try: ndata1 = self.parser['8bit-RFC'].parsebytes(data[0][1])
        except:
            err = exc_info()
            response_type = type(data[0][1]).__name__
            msg_id = self._extract_message_id(data[0][1])[0].decode('ascii',errors='surrogateescape')
            raise OfflineImapError(
                "Exception parsing message with ID ({}) from imaplib (response type: {}).\n {}: {}".format(
                    msg_id, response_type, err[0].__name__, err[1]),
                OfflineImapError.ERROR.MESSAGE)
        if len(ndata1.defects) > 0:
            # We don't automatically apply fixes as to attempt to preserve the original message
            self.ui.warn("UID {} has defects: {}".format(uids, ndata1.defects))
            if any(isinstance(defect, NoBoundaryInMultipartDefect) for defect in ndata1.defects):
                # (Hopefully) Rare defect from a broken client where multipart boundary is
                # not properly quoted.  Attempt to solve by fixing the boundary and parsing
                self.ui.warn(" ... applying multipart boundary fix.")
                ndata1 = self.parser['8bit-RFC'].parsebytes(self._quote_boundary_fix(data[0][1]))
            try:
                # See if the defects after fixes are preventing us from obtaining bytes
                _ = ndata1.as_bytes(policy=self.policy['8bit-RFC'])
            except UnicodeEncodeError as err:
                # Unknown issue which is causing failure of as_bytes()
                msg_id = self.getmessageheader(ndata1, "message-id")
                if msg_id is None:
                    msg_id = '<Unknown Message-ID>'
                raise OfflineImapError(
                        "UID {} ({}) has defects preventing it from being processed!\n  {}: {}".format(
                            uids, msg_id, type(err).__name__, err),
                        OfflineImapError.ERROR.MESSAGE)
        ndata = [ndata0, ndata1]

        return ndata

    def _store_to_imap(self, imapobj, uid, field, data):
        """Stores data to IMAP server

        Arguments:
        - imapobj: instance of IMAPlib to use
        - uid: message UID
        - field: field name to be stored/updated
        - data: field contents
        """
        imapobj.select(self.getfullIMAPname())
        res_type, retdata = imapobj.uid('store', uid, field, data)
        if res_type != 'OK':
            severity = OfflineImapError.ERROR.MESSAGE
            reason = "IMAP server '%s' failed to store %s " \
                     "for message UID '%d'." \
                     "Server responded: %s %s" % (
                         self.getrepository(), field, uid, res_type, retdata)
            raise OfflineImapError(reason, severity)
        return retdata[0]

    # Interface from BaseFolder
    def savemessageflags(self, uid, flags):
        """Change a message's flags to `flags`.

        Note that this function does not check against dryrun settings,
        so you need to ensure that it is never called in a
        dryrun mode."""

        imapobj = self.imapserver.acquireconnection()
        try:
            result = self._store_to_imap(imapobj, str(uid), 'FLAGS',
                                         imaputil.flagsmaildir2imap(flags))
        except imapobj.readonly:
            self.ui.flagstoreadonly(self, [uid], flags)
            return
        finally:
            self.imapserver.releaseconnection(imapobj)

        if not result:
            self.messagelist[uid]['flags'] = flags
        else:
            flags = imaputil.flags2hash(imaputil.imapsplit(result)[1])['FLAGS']
            self.messagelist[uid]['flags'] = imaputil.flagsimap2maildir(flags)

    # Interface from BaseFolder
    def addmessageflags(self, uid, flags):
        self.addmessagesflags([uid], flags)

    def __addmessagesflags_noconvert(self, uidlist, flags):
        self.__processmessagesflags('+', uidlist, flags)

    # Interface from BaseFolder
    def addmessagesflags(self, uidlist, flags):
        """This is here for the sake of UIDMaps.py -- deletemessages must
        add flags and get a converted UID, and if we don't have noconvert,
        then UIDMaps will try to convert it twice."""

        self.__addmessagesflags_noconvert(uidlist, flags)

    # Interface from BaseFolder
    def deletemessageflags(self, uid, flags):
        self.deletemessagesflags([uid], flags)

    # Interface from BaseFolder
    def deletemessagesflags(self, uidlist, flags):
        self.__processmessagesflags('-', uidlist, flags)

    def __processmessagesflags_real(self, operation, uidlist, flags):
        imapobj = self.imapserver.acquireconnection()
        try:
            try:
                imapobj.select(self.getfullIMAPname())
            except imapobj.readonly:
                self.ui.flagstoreadonly(self, uidlist, flags)
                return
            response = imapobj.uid('store',
                                   imaputil.uid_sequence(uidlist),
                                   operation + 'FLAGS',
                                   imaputil.flagsmaildir2imap(flags))
            if response[0] != 'OK':
                raise OfflineImapError(
                    'Error with store: %s' % '. '.join(response[1]),
                    OfflineImapError.ERROR.MESSAGE)
            response = response[1]
        finally:
            self.imapserver.releaseconnection(imapobj)
        # Some IMAP servers do not always return a result.  Therefore,
        # only update the ones that it talks about, and manually fix
        # the others.
        needupdate = list(uidlist)
        for result in response:
            if result is None:
                # Compensate for servers that don't return anything from
                # STORE.
                continue
            attributehash = imaputil.flags2hash(imaputil.imapsplit(result)[1])
            if not ('UID' in attributehash and 'FLAGS' in attributehash):
                # Compensate for servers that don't return a UID attribute.
                continue
            flagstr = attributehash['FLAGS']
            uid = int(attributehash['UID'])
            self.messagelist[uid]['flags'] = imaputil.flagsimap2maildir(flagstr)
            try:
                needupdate.remove(uid)
            except ValueError:  # Let it slide if it's not in the list.
                pass
        for uid in needupdate:
            if operation == '+':
                self.messagelist[uid]['flags'] |= flags
            elif operation == '-':
                self.messagelist[uid]['flags'] -= flags

    def __processmessagesflags(self, operation, uidlist, flags):
        # Hack for those IMAP servers with a limited line length.
        batch_size = 100
        for i in range(0, len(uidlist), batch_size):
            self.__processmessagesflags_real(operation,
                                             uidlist[i:i + batch_size], flags)
        return

    # Interface from BaseFolder
    def change_message_uid(self, uid, new_uid):
        """Change the message from existing uid to new_uid

        If the backend supports it. IMAP does not and will throw errors."""

        raise OfflineImapError('IMAP backend cannot change a messages UID from '
                               '%d to %d' %
                               (uid, new_uid), OfflineImapError.ERROR.MESSAGE)

    # Interface from BaseFolder
    def deletemessage(self, uid):
        self.__deletemessages_noconvert([uid])

    # Interface from BaseFolder
    def deletemessages(self, uidlist):
        self.__deletemessages_noconvert(uidlist)

    def __deletemessages_noconvert(self, uidlist):
        if not len(uidlist):
            return

        self.__addmessagesflags_noconvert(uidlist, set('T'))
        imapobj = self.imapserver.acquireconnection()
        try:
            try:
                imapobj.select(self.getfullIMAPname())
            except imapobj.readonly:
                self.ui.deletereadonly(self, uidlist)
                return
            if self.expunge:
                assert (imapobj.expunge()[0] == 'OK')
        finally:
            self.imapserver.releaseconnection(imapobj)
        for uid in uidlist:
            del self.messagelist[uid]

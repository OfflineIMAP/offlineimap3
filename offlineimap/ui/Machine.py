# Copyright (C) 2007-2018 John Goerzen & contributors.
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
from urllib.parse import urlencode
import sys
import time
import logging
from threading import currentThread

import offlineimap
from offlineimap.ui.UIBase import UIBase

protocol = '7.2.0'


class MachineLogFormatter(logging.Formatter):
    """urlencodes any outputted line, to avoid multi-line output"""

    def format(self, record):
        # Mapping of log levels to historic tag names
        severity_map = {
            'info': 'msg',
            'warning': 'warn',
        }
        line = super(MachineLogFormatter, self).format(record)
        severity = record.levelname.lower()
        if severity in severity_map:
            severity = severity_map[severity]
        if hasattr(record, "machineui"):
            command = record.machineui["command"]
            whoami = record.machineui["id"]
        else:
            command = ""
            whoami = currentThread().getName()

        prefix = "%s:%s" % (command, urlencode([('', whoami)])[1:])
        return "%s:%s:%s" % (severity, prefix, urlencode([('', line)])[1:])


class MachineUI(UIBase):
    def __init__(self, config, loglevel=logging.INFO):
        super(MachineUI, self).__init__(config, loglevel)
        self._log_con_handler.createLock()
        """lock needed to block on password input"""
        # Set up the formatter that urlencodes the strings...
        self._log_con_handler.setFormatter(MachineLogFormatter())

    # Arguments:
    # - handler: must be method from self.logger that reflects
    #   the severity of the passed message
    # - command: command that produced this message
    # - msg: the message itself
    def _printData(self, handler, command, msg):
        handler(msg,
                extra={
                    'machineui': {
                        'command': command,
                        'id': currentThread().getName(),
                    }
                })

    def _msg(self, msg):
        self._printData(self.logger.info, '_display', msg)

    def warn(self, msg, minor=0):
        # TODO, remove and cleanup the unused minor stuff
        self._printData(self.logger.warning, '', msg)

    def registerthread(self, account):
        super(MachineUI, self).registerthread(account)
        self._printData(self.logger.info, 'registerthread', account)

    def unregisterthread(self, thread):
        UIBase.unregisterthread(self, thread)
        self._printData(self.logger.info, 'unregisterthread', thread.getName())

    def debugging(self, debugtype):
        self._printData(self.logger.debug, 'debugging', debugtype)

    def acct(self, accountname):
        self._printData(self.logger.info, 'acct', accountname)

    def acctdone(self, accountname):
        self._printData(self.logger.info, 'acctdone', accountname)

    def validityproblem(self, folder):
        self._printData(self.logger.warning, 'validityproblem', "%s\n%s\n%s\n%s" %
                        (folder.getname(), folder.getrepository().getname(),
                         folder.get_saveduidvalidity(), folder.get_uidvalidity()))

    def connecting(self, reposname, hostname, port):
        self._printData(self.logger.info, 'connecting', "%s\n%s\n%s" % (hostname,
                                                                        str(port), reposname))

    def syncfolders(self, srcrepos, destrepos):
        self._printData(self.logger.info, 'syncfolders', "%s\n%s" % (self.getnicename(srcrepos),
                                                                     self.getnicename(destrepos)))

    def syncingfolder(self, srcrepos, srcfolder, destrepos, destfolder):
        self._printData(self.logger.info, 'syncingfolder', "%s\n%s\n%s\n%s\n" %
                        (self.getnicename(srcrepos), srcfolder.getname(),
                         self.getnicename(destrepos), destfolder.getname()))

    def loadmessagelist(self, repos, folder):
        self._printData(self.logger.info, 'loadmessagelist', "%s\n%s" % (self.getnicename(repos),
                                                                         folder.getvisiblename()))

    def messagelistloaded(self, repos, folder, count):
        self._printData(self.logger.info, 'messagelistloaded', "%s\n%s\n%d" %
                        (self.getnicename(repos), folder.getname(), count))

    def syncingmessages(self, sr, sf, dr, df):
        self._printData(self.logger.info, 'syncingmessages', "%s\n%s\n%s\n%s\n" %
                        (self.getnicename(sr), sf.getname(), self.getnicename(dr),
                         df.getname()))

    def ignorecopyingmessage(self, uid, srcfolder, destfolder):
        self._printData(self.logger.info, 'ignorecopyingmessage', "%d\n%s\n%s\n%s[%s]" %
                        (uid, self.getnicename(srcfolder), srcfolder.getname(),
                         self.getnicename(destfolder), destfolder))

    def copyingmessage(self, uid, num, num_to_copy, srcfolder, destfolder):
        self._printData(self.logger.info, 'copyingmessage', "%d\n%s\n%s\n%s[%s]" %
                        (uid, self.getnicename(srcfolder), srcfolder.getname(),
                         self.getnicename(destfolder), destfolder))

    def folderlist(self, ulist):
        return "\f".join(["%s\t%s" % (self.getnicename(x), x.getname()) for x in ulist])

    def uidlist(self, ulist):
        return "\f".join([str(u) for u in ulist])

    def deletingmessages(self, uidlist, destlist):
        ds = self.folderlist(destlist)
        self._printData(self.logger.info, 'deletingmessages', "%s\n%s" % (self.uidlist(uidlist), ds))

    def addingflags(self, uidlist, flags, dest):
        self._printData(self.logger.info, "addingflags", "%s\n%s\n%s" % (self.uidlist(uidlist),
                                                                         "\f".join(flags),
                                                                         dest))

    def deletingflags(self, uidlist, flags, dest):
        self._printData(self.logger.info, 'deletingflags', "%s\n%s\n%s" % (self.uidlist(uidlist),
                                                                           "\f".join(flags),
                                                                           dest))

    def threadException(self, thread):
        self._printData(self.logger.warning, 'threadException', "%s\n%s" %
                        (thread.getName(), self.getThreadExceptionString(thread)))
        self.delThreadDebugLog(thread)
        self.terminate(100)

    def terminate(self, exitstatus=0, errortitle='', errormsg=''):
        self._printData(self.logger.info, 'terminate', "%d\n%s\n%s" % (exitstatus, errortitle, errormsg))
        sys.exit(exitstatus)

    def mainException(self):
        self._printData(self.logger.warning, 'mainException', self.getMainExceptionString())

    def threadExited(self, thread):
        self._printData(self.logger.info, 'threadExited', thread.getName())
        UIBase.threadExited(self, thread)

    def sleeping(self, sleepsecs, remainingsecs):
        self._printData(self.logger.info, 'sleeping', "%d\n%d" % (sleepsecs, remainingsecs))
        if sleepsecs > 0:
            time.sleep(sleepsecs)
        return 0

    def getpass(self, username, config, errmsg=None):
        if errmsg:
            self._printData(self.logger.warning,
                            'getpasserror', "%s\n%s" % (username, errmsg),
                            False)

        self._log_con_handler.acquire()  # lock the console output
        try:
            self._printData(self.logger.info, 'getpass', username)
            return sys.stdin.readline()[:-1]
        finally:
            self._log_con_handler.release()

    def init_banner(self):
        self._printData(self.logger.info, 'protocol', protocol)
        self._printData(self.logger.info, 'initbanner', offlineimap.banner)

    def callhook(self, msg):
        self._printData(self.logger.info, 'callhook', msg)

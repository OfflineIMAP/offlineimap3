__all__ = ['OfflineImap']

__productname__ = 'OfflineIMAP'
# Expecting trailing "-rcN" or "" for stable releases.
__version__ = "7.3.0"
__copyright__ = "Copyright 2002-2019 John Goerzen & contributors"
__license__ = "Licensed under the GNU GPL v2 or any later version"
__bigcopyright__ = """%(__productname__)s %(__version__)s
  %(__license__)s""" % locals()

banner = __bigcopyright__

from offlineimap.error import OfflineImapError
# put this last, so we don't run into circular dependencies using
# e.g. offlineimap.__version__.
from offlineimap.init import OfflineImap

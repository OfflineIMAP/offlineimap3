from offlineimap.bundled_imaplib2 import *
import offlineimap.bundled_imaplib2 as imaplib

DESC = "bundled"

# Upstream won't expose those literals to avoid erasing them with "import *" in
# case they exist.
__version__ = imaplib.__version__
__release__ = imaplib.__release__
__revision__ = imaplib.__revision__

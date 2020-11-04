"""
Copyright 2013 Eygene A. Ryabinkin
Functions to perform stack tracing (for multithreaded programs
as well as for single-threaded ones).
"""

import sys
import threading
import traceback


def dump(out):
    """ Dumps current stack trace into I/O object 'out' """
    id2name = {}
    for th_en in threading.enumerate():
        id2name[th_en.ident] = th_en.name

    count = 0
    for i, stack in list(sys._current_frames().items()):
        out.write("\n# Thread #%d (id=%d), %s\n" % (count, i, id2name[i]))
        count = count + 1
        for file, lno, name, line in traceback.extract_stack(stack):
            out.write('File: "%s", line %d, in %s' % (file, lno, name))
            if line:
                out.write(" %s" % (line.strip()))
            out.write("\n")

"""
convert_utf7_to_utf8 used in nametrans

Main code: Rodolfo García Peñas (kix) @thekix
Updated regex by @dnebauer

Please, check https://github.com/OfflineIMAP/offlineimap3/issues/23
for more info.
"""
import re


def convert_utf7_to_utf8(str_imap):
    """
    This function converts an IMAP_UTF-7 string object to UTF-8.
    It first replaces the ampersand (&) character with plus character (+)
    in the cases of UTF-7 character and then decode the string to utf-8.

    If the str_imap string is already UTF-8, return it.

    For example, "abc&AK4-D" is translated to "abc+AK4-D"
    and then, to "abc@D"

    Example code:
    my_string = "abc&AK4-D"
    print(convert_utf7_to_utf8(my_string))

    Args:
        bytes_imap: IMAP UTF7 string

    Returns: UTF-8 string

    Source: https://github.com/OfflineIMAP/offlineimap3/issues/23

    """
    try:
        str_utf7 = re.sub(r'&(\w{3}\-)', '+\\1', str_imap)
        str_utf8 = str_utf7.encode('utf-8').decode('utf_7')
        return str_utf8
    except UnicodeDecodeError:
        # error decoding because already utf-8, so return original string
        return str_imap


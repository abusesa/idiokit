from __future__ import absolute_import

try:
    # Try to use the new ssl module included by default from Python
    # 2.6 onwards.
    import ssl
except ImportError:
    from ._oldssl import SSLError, wrap_socket
else:
    from ._newssl import SSLError, wrap_socket

from .identities import match_identity

#!/usr/bin/env python

from optparse import OptionParser

import idiokit
import idiokit.socket
import idiokit.ssl


@idiokit.stream
def main():
    usage = "usage: %prog <server> <port> [ca_certs]"
    parser = OptionParser(usage)

    (options, args) = parser.parse_args()

    if len(args) < 2:
        parser.error("You need to supply both the server adddress and port!")

    host = args[0]
    port = int(args[1])
    cert = None

    if len(args) == 3:
        cert = args[2]
        print "Using certificate(s) from file: {0}".format(cert)

    try:
        sock = idiokit.socket.Socket()
        yield sock.connect((host, port))

        sock = yield idiokit.ssl.wrap_socket(
            sock, require_cert=True, ca_certs=cert
        )
        peer_cert = yield sock.getpeercert()
        idiokit.ssl.match_hostname(peer_cert, host)
    except idiokit.socket.SocketError as e:
        print "connection failed ({0})".format(e)
    except idiokit.socket.SocketGAIError as e:
        print "connection failed ({0})".format(e)
    except idiokit.ssl.SSLError as e:
        print "idiokit strongly disapproves! ({0})".format(e)
    else:
        print "idiokit approves this connection"
    finally:
        sock.close()


if __name__ == '__main__':
    idiokit.main_loop(main())

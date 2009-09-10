import time
import util
import threado
import sockets

class CymruWhoisItem(object):
    def __init__(self, as_no, ip, bgp_prefix, cc, registry, allocated, as_name):
        self.ip = ip
        self.as_number = as_no
        self.as_name = as_name
        self.bgp_prefix = bgp_prefix
        self.country_code = cc
        self.registry = registry
        self.allocated = allocated

class CymruWhois(threado.ThreadedStream):
    def __init__(self, throttle_time=10.0, cache_time=60*60.0):
        threado.ThreadedStream.__init__(self)

        self.cache = util.TimedCache(cache_time)
        self.throttle_time = throttle_time
        self.pending = set()

        self.input = threado.Channel()

    def send(self, *args, **keys):
        self.input.send(*args, **keys)
        self.start()

    def throw(self, *args, **keys):
        self.input.throw(*args, **keys)
        self.start()

    def rethrow(self, *args, **keys):
        self.input.rethrow(*args, **keys)
        self.start()

    def _iteration(self, pending):
        for ip in list(pending):
            item = self.cache.get(ip, None)
            if item is not None:
                self.output.send(item)
                pending.discard(ip)

        if not pending:
            return pending

        socket = sockets.Socket()
        socket.connect(("whois.cymru.com", 43))

        try:        
            socket.send("begin\n")
            socket.send("verbose\n")
            for ip in pending:
                socket.send(ip + "\n")
            socket.send("end\n")
            
            line_buffer = util.LineBuffer()
            while pending:
                try:
                    data = socket.next()
                except sockets.error:
                    break

                for line in line_buffer.feed(data):                    
                    bites = [x.strip() for x in line.split("|")]
                    bites = [x if x not in ("", "NA") else None for x in bites]
                    if len(bites) != 7:
                        continue
                    item = CymruWhoisItem(*bites)

                    pending.discard(item.ip)
                    self.cache.set(item.ip, item)
                    self.output.send(item)
        finally:
            socket.close()

        return pending
        
    def run(self):
        next_purge = time.time() + self.throttle_time / 2.0
        pending = set()

        while True:
            try:
                ip = self.input.next(max(0.0, next_purge-time.time()))
            except threado.Timeout:
                pending = self._iteration(pending)
                next_purge = time.time() + self.throttle_time
            else:
                pending.add(ip)
                continue

def whois(*ips):
    ips = set(ips)

    cymru = CymruWhois(1.0)
    for ip in ips:
        cymru.send(ip)
        
    while ips:
        item = cymru.next()
        ips.discard(item.ip)
        yield item

    cymru.throw(StopIteration())

if __name__ == "__main__":
    import sys

    for item in whois(*sys.argv[1:]):
        print item.ip, item.as_name

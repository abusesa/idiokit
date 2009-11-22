import time
import util
import threado
import sockets
import timer

class CymruWhoisItem(object):
    def __init__(self, as_no, ip, bgp_prefix, cc, registry, allocated, as_name):
        self.ip = ip
        self.as_number = as_no
        self.as_name = as_name
        self.bgp_prefix = bgp_prefix
        self.country_code = cc
        self.registry = registry
        self.allocated = allocated

class CymruWhois(threado.GeneratorStream):
    def __init__(self, throttle_time=10.0, cache_time=60*60.0):
        threado.GeneratorStream.__init__(self)

        self.cache = util.TimedCache(cache_time)
        self.throttle_time = throttle_time
        self.pending = set()

        self.start()

    @threado.stream
    def _iteration(inner, self, pending):
        for ip in list(pending):
            item = self.cache.get(ip, None)
            if item is not None:
                self.inner.send(item)
                pending.discard(ip)

        if not pending:
            inner.finish(pending)

        socket = sockets.Socket()
        yield inner.sub(socket.connect(("whois.cymru.com", 43)))

        try:        
            socket.send("begin\n")
            socket.send("verbose\n")
            for ip in pending:
                socket.send(ip + "\n")
            socket.send("end\n")
            
            line_buffer = util.LineBuffer()
            while pending:
                try:
                    data = yield socket
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
                    self.inner.send(item)
        finally:
            yield inner.sub(socket.close())

        inner.finish(pending)
        
    def run(self):
        pending = set()
        sleeper = timer.sleep(self.throttle_time / 2.0)

        while True:
            ip = yield self.inner, sleeper
            if sleeper.was_source:
                sleeper = timer.sleep(self.throttle_time)
                pending = yield self.inner.sub(self._iteration(pending))
            else:
                pending.add(ip)

@threado.stream
def main(inner, *ips):
    ips = set(ips)

    cymru = CymruWhois(1.0)
    for ip in ips:
        cymru.send(ip)
        
    while ips:
        item = yield cymru
        ips.discard(item.ip)
        print item.ip, item.as_name

if __name__ == "__main__":
    import sys
    threado.run(main(*sys.argv[1:]))

# The Gist of i(dioki)t


## What is this idio... kit?

**idiokit** is a library for asynchronous & concurrent programming for Python 2.6 and 2.7. Started in 2009 along with the [AbuseHelper](https://github.com/abusesa/abusehelper) project, idiokit has since been proven to be a general tool for situations involving Python, asynchronicity and concurrency.

idiokit aims to offer a middle ground between threads and event loops with an abstraction for cooperative multitasking called **streams**. You can launch and run thousands of these streams concurrently, yet still write most of your code in a linear way much like any non-concurrent code. Streams can also be composed by **piping** them together - think of [Unix Pipelines](https%3A//en.wikipedia.org/wiki/Pipeline_%28Unix%29) but dealing with Python objects instead of raw bytes.

So idiokit is good for places where many tasks have to be worked on simultaneously and one task *must not* block other unrelated ones. As an example imagine a HTTP API server that has to stay responsive for incoming requests, even when fulfilling a bunch of previously received requests may be work in progress

### Example: HTTP API for DNS queries

```python
import idiokit
from idiokit import dns
from idiokit.http.server import serve_http


@idiokit.stream
def handler(addr, request, response):
    _, _, query = request.uri.partition("/")
    try:
        ipv4_addresses = yield dns.a(query)
    except ValueError:
        yield response.write_status(400)
    except dns.DNSError:
        pass
    else:
        yield response.write("\n".join(ipv4_addresses) + "\n")


idiokit.main_loop(serve_http(handler, "localhost", 8080))
```


## Sections

 * [Basics](./Basics.md): How to create and combine your own asynchronous functions.

 * [Pipes](./Pipes.md): How to compose your asynchronous functions to handy pipelines.

 * [Helpers](./Helpers.md): Helpful tools for general idiokit programming.

 * [Network Programming](./Network.md): idiokit can handle basic sockets as well as some higher level protocols.

 * [Common Problems](./Problems.md): Common problems that pop up from time to time - and some proposed solutions.

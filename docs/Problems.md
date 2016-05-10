# Common Problems

## Blocking the World

```python
import socket
import idiokit
from idiokit.http.server import serve_http


@idiokit.stream
def handler(addr, request, response):
    _, _, query = request.uri.partition("/")
    try:
        results = socket.getaddrinfo(query, None, socket.AF_INET)
    except socket.gaierror:
        pass
    else:
        ipv4_addresses = set(result[4][0] for result in results)
        yield response.write("\n".join(ipv4_addresses) + "\n")


idiokit.main_loop(serve_http(handler, "localhost", 8080))
```

Use `idiokit.thread` or better yet, an asynchronous idiokit counterpart when available: In this case `idiokit.dns.a` does the trick.


## Forgetting to `yield`

This is what happens when you forget to yield in your streams:

```python
import idiokit


@idiokit.stream
def count_to(count):
    for number in range(1, count + 1):
        idiokit.sleep(1.0)
        print number


idiokit.main_loop(count_to(3))
```

Notice the complete lack of `yield` inside the function. Running this example crashes with a `TypeError`. This is actually idiokit trying to be helpful, telling that the function `count_to` is not a _generator function_, i.e that there's no `yield` inside the function.

```console
$ python example.py
Traceback (most recent call last):
  File "example.py", line 4, in <module>
    @idiokit.stream
  File "/usr/local/lib/python2.7/site-packages/idiokit/idiokit.py", line 724, in stream
    raise TypeError("{0!r} is not a generator function".format(func))
TypeError: <function count_to at 0x120110a40> is not a generator function
```


## Yielding Non-Streams

```python
import time
import idiokit


@idiokit.stream
def count_to(count):
    for number in range(1, count + 1):
        yield time.sleep(1.0)
        print count


idiokit.main_loop(count_to(3))
```

`time.sleep` returns `None`, so we get this error:

```console
Traceback (most recent call last):
  File "example.py", line 12, in <module>
    idiokit.main_loop(count_to(3))
  File "/usr/local/lib/python2.7/site-packages/idiokit/idiokit.py", line 354, in _next
    next = require_stream(self._gen.send(peel_args(args)))
  File "/usr/local/lib/python2.7/site-packages/idiokit/idiokit.py", line 128, in require_stream
    raise TypeError("expected a stream, got {0!r}".format(obj))
TypeError: expected a stream, got None
```

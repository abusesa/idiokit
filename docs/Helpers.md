# Helpers

## Timing Out: `idiokit.timer.timeout`

Most network programming tools (`idiokit.socket`, `idiokit.dns`, ...) have timeout functionality built in, but what about setting deadlines for larger tasks?

```python
import idiokit
from idiokit import timer


@idiokit.stream
def count_to(count):
    for number in range(1, count + 1):
        yield idiokit.sleep(1.0)
        print number


@idiokit.stream
def main():
    try:
        yield timer.timeout(1.5, count_to(3))
    except timer.Timeout:
        print "ERROR: Couldn't count to three in 1.5 seconds!"


idiokit.main_loop(main())
```


## Waiting for I/O: `idiokit.select`

```python
import sys
import idiokit
from idiokit import select, dns


@idiokit.stream
def read_stdin():
    while True:
        yield select.select((sys.stdin,), (), ())
        line = sys.stdin.readline().strip()
        yield idiokit.send(line)


@idiokit.stream
def resolve_domains():
    while True:
        domain = yield idiokit.next()
        try:
            ipv4_addresses = yield dns.a(domain)
        except (ValueError, dns.DNSError):
            pass
        else:
            print domain, "resolves to", ", ".join(ipv4_addresses)


idiokit.main_loop(read_stdin() | resolve_domains())
```


## Escape Hatch to the Blocking World: `idiokit.thread`

```python
import idiokit
import subprocess


@idiokit.stream
def git_clone(url):
    returncode = yield idiokit.thread(subprocess.call, ["git", "clone", url])
    print "git exited with return code", returncode


idiokit.main_loop(
    git_clone("https://github.com/abusesa/idiokit") |
    git_clone("https://github.com/abusesa/abusehelper")
)
```

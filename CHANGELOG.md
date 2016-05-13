# Changelog


## 2.7.0 (2016-05-14)

 * Add `.gettimeout()` and `.settimeout(...)` support to `idiokit.socket` and `idiokit.ssl` ([684f2c5](https://github.com/abusesa/idiokit/commit/684f2c560028befce129d29a9a162abc40ee8dab))
   * A socket's default timeout is set to 15 seconds with `s.settimeout(15.0)`, but can still be overriden per method by using the `timeout=...` keyword argument (e.g. `s.recv(..., timeout=30.0)` sets the timeout to 30 seconds for that specific `recv` operation).


## 2.6.1 (2016-05-12)

### Fixes

 * Do a larger part of the bookeeping work for `idiokit.thread` calls in the main thread, meaning less potential places for errors during Python interpreter shutdown ([3bebf76](https://github.com/abusesa/idiokit/commit/3bebf769a1b3f9cfd011e4ae1a3db72727f1f864))


## 2.6.0 (2016-05-11)

### Features

 * Add `idiokit.ssl.ca_certs` that `idiokit.ssl.wrap_socket` uses for finding an usable CA certificate bundle when `ca_certs=None`, but the functionality can be useful in other contexts as well ([ea6ac75](https://github.com/abusesa/idiokit/commit/ea6ac7563e60e15275bde2f6db9c649411bbcd32))


## 2.5.0 (2016-04-07)

### Features

 * Add `idiokit.socket.fromfd` and `idiokit.socket.socketpair` wrapping their "native" Python `socket` module counterparts  ([9a5b846](https://github.com/abusesa/idiokit/commit/9a5b846e6a8439d57f94da41337ab4c16c058367), [7d9ab0c](https://github.com/abusesa/idiokit/commit/7d9ab0cdd32e83011cf74a91e5dd2f27e9ccdcda))
 * Add socket & ping timeouts to `idiokit.irc` connections ([#16](https://github.com/abusesa/idiokit/pull/16))
  * The timeout is 30 seconds by default and can be controlled with the `timeout` keyword argument of `idiokit.irc.connect` (e.g. `idiokit.irc.connect(..., timeout=30.0)`)
 * Add CA bundle info for Alpine Linux, Debian & Fedora to `idiokit.ssl` ([#22](https://github.com/abusesa/idiokit/pull/22))

### Fixes

 * Fix accidentally blocked exception propagation ([#17](https://github.com/abusesa/idiokit/issues/17), [#18](https://github.com/abusesa/idiokit/pull/18))
 * Fix XMPP connection crashes when the SRV request returns an empty set of results ([#21](https://github.com/abusesa/idiokit/issues/21), [8bf5cb0](https://github.com/abusesa/idiokit/commit/8bf5cb08b336e4c8368f4765ddfcaea7bf54c116))


## 2.4.0 (2016-02-10)

### Features

 * Expose more constants, including `SOMAXCONN`, from the `socket` module as `idiokit.socket.SOMAXCONN` etc. ([b1a45b1](https://github.com/abusesa/idiokit/commit/b1a45b1f9dc33f966fe1229fb2991cb6f7cef664))
 * Set socket `idiokit.http.server` socket backlog to `SOMAXCONN` from the previous `5` ([5f7bc50](https://github.com/abusesa/idiokit/commit/5f7bc50253040c9279be3360ea9f9bf63ad0cb6e))

### Fixes

 * Fix exceptions raised at shutdown ([#14](https://github.com/abusesa/idiokit/issues/14))
 * Several fixes to `idiokit.dns` ([#10](https://github.com/abusesa/idiokit/pull/10), [#11](https://github.com/abusesa/idiokit/pull/11), [#12](https://github.com/abusesa/idiokit/pull/12))


## 2.3.0 (2015-12-18)

### Features

 * Add Requests-style `mount` method to `idiokit.http.client.Client` ([#3](https://github.com/abusesa/idiokit/pull/3))
 * Add User-Agent header to HTTP Client ([#8](https://github.com/abusesa/idiokit/pull/8))
 * Expose idiokit version number as `idiokit.__version__` ([fa33074](https://github.com/abusesa/idiokit/commit/fa330749b7c8643e648b78bd992dca9e03945496))

### Fixes

 * Raise `ValueError` when trying to create a `xmlcore.Element` with data outside the XML 1.0 range ([#2](https://github.com/abusesa/idiokit/pull/2), [#7](https://github.com/abusesa/idiokit/pull/7))
 * Fix `idiokit.http.server` to deal correctly with HTTP header values when they're given as unlimited precision integers ([#9](https://github.com/abusesa/idiokit/pull/9))
 * `idiokit.dns` now raises a `ValueError` when trying to resolve a malformed name ([#6](https://github.com/abusesa/idiokit/pull/6))


## 2.2.0 (2015-11-09)

Historical release.

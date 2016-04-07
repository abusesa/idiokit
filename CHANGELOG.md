# Changelog

## 2.5.0 (2016-04-07)

### Features

 * Add `idiokit.socket.fromfd` and `idiokit.socket.socketpair` wrapping their "native" Python `socket` module counterparts  ([5d1fbe6](https://github.com/abusesa/idiokit/commit/5d1fbe659b07be423d69d244066bd0a8568ab095), [a255d49](https://github.com/abusesa/idiokit/commit/a255d49abbe4c232d9372431ecc5c65c781bf9bd))
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

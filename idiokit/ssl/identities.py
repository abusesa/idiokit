import re

def identities(cert):
    """
    RFC2818: "If a subjectAltName extension of type dNSName is present,
    that MUST be used as the identity."

    >>> identities({
    ...     "subject": ((("commonName", "a"),),),
    ...     "subjectAltName": (("DNS", "x"),)
    ... })
    ['x']

    RFC2818: "Otherwise, the (most specific) Common Name field in the
    Subject field of the certificate MUST be used."

    >>> identities({
    ...     "subject": ((("commonName", "a"), ("commonName", "a.b")),)
    ... })
    ['a.b']

    RFC2818: "If more than one identity of a given type is present in
    the certificate (e.g., more than one dNSName name, a match in any one
    of the set is considered acceptable.)"

    >>> sorted(identities({
    ...     "subjectAltName": (("DNS", "x"), ("DNS", "x.y"))
    ... }))
    ['x', 'x.y']
    """

    alt_name = cert.get("subjectAltName", ())
    dns_names = [value for (key, value) in alt_name if key == "DNS"]
    if dns_names:
        return dns_names

    common_names = list()
    for fields in cert.get("subject", ()):
        common_names.extend([value for (key, value) in fields if key == "commonName"])
    if common_names:
        return common_names[-1:]

    return []

def _match_part(pattern, part):
    rex_chars = list()
    for ch in pattern:
        if ch == "*":
            rex_chars.append(".*")
        else:
            rex_chars.append(re.escape(ch))
    rex_pattern = "".join(rex_chars)
    return re.match(rex_pattern, part, re.I) is not None

def _match_identity(pattern, identity):
    """
    >>> _match_identity("a.b", "a.b")
    True
    >>> _match_identity("*.b", "a.b")
    True
    >>> _match_identity("a.*", "a.b")
    True
    >>> _match_identity("a", "a.b")
    False
    >>> _match_identity("a.b", "b")
    False
    """

    pattern_parts = pattern.split(".")
    identity_parts = identity.split(".")
    if len(pattern_parts) != len(identity_parts):
        return False

    for pattern_part, identity_part in zip(pattern_parts, identity_parts):
        if not _match_part(pattern_part, identity_part):
            return False
    return True

def match_identity(cert, identity):
    """
    >>> cert = {
    ...     "subject": ((("commonName", "a"),),),
    ...     "subjectAltName": (("DNS", "b"), ("DNS", "c"))
    ... }
    >>> match_identity(cert, "b")
    True
    >>> match_identity(cert, "c")
    True
    >>> match_identity(cert, "a")
    False

    >>> cert = {
    ...     "subject": ((("commonName", "a"), ("commonName", "x")),)
    ... }
    >>> match_identity(cert, "a")
    False
    >>> match_identity(cert, "x")
    True
    """

    for pattern in identities(cert):
        if _match_identity(pattern, identity):
            return True
    return False

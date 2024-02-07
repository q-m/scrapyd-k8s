def _to_native_str(text, encoding="utf-8", errors="strict"):
    if isinstance(text, str):
        return text
    if not isinstance(text, (bytes, str)):
        raise TypeError(
            "_to_native_str must receive a bytes, str or unicode "
            "object, got %s" % type(text).__name__
        )

    return text.decode(encoding, errors)


def native_stringify_dict(dct_or_tuples, encoding="utf-8", keys_only=True):
    """Return a (new) dict with unicode keys (and values when "keys_only" is
    False) of the given dict converted to strings. `dct_or_tuples` can be a
    dict or a list of tuples, like any dict constructor supports.
    """
    d = {}
    for k, v in dct_or_tuples.items():
        k = _to_native_str(k, encoding)
        if not keys_only:
            if isinstance(v, dict):
                v = native_stringify_dict(v, encoding=encoding, keys_only=keys_only)
            elif isinstance(v, list):
                v = [_to_native_str(e, encoding) for e in v]
            else:
                v = _to_native_str(v, encoding)
        d[k] = v
    return d


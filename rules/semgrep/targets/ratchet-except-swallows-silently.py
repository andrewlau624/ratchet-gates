# ruleid: ratchet-except-swallows-silently
try:
    do_thing()
except OSError:
    return None

# ok: ratchet-except-swallows-silently
try:
    do_thing()
except OSError:
    logger.exception("failed")

# ok: ratchet-except-swallows-silently
try:
    do_thing()
except OSError:
    raise

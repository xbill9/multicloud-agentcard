"""Who to reach, and what to prove to them on the way.

Everything in this package predates the fork and was measured against three
live clouds: the credential seam (``auth``, ``aws_origin``), the wire tracer
(``trace``), the failure taxonomy (``errors``). It is carried over verbatim
rather than rewritten, because every comment in it is a defect somebody paid
for. ``registry`` is the one new module -- the mesh had three hardcoded peers
and this repo needs any number.
"""

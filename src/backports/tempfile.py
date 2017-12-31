"""
Partial backport of Python 3.5's tempfile module:

    TemporaryDirectory

Backport modifications are marked with marked with "XXX backport".
"""
from __future__ import absolute_import

import sys as _sys
import warnings as _warnings
from shutil import rmtree as _rmtree

from backports.weakref import finalize as _finalize

from tempfile import *

# XXX backport:  Rather than backporting all of mkdtemp(), we just create a
# thin wrapper implementing its Python 3.5 signature.
if _sys.version_info < (3, 5):
    from tempfile import mkdtemp as _old_mkdtemp

    def mkdtemp(suffix=None, prefix=None, dir=None):
        """
        Wrap `tempfile.mkdtemp()` to make the suffix and prefix optional (like Python 3.5).
        """
        kwargs = {k: v for (k, v) in
                  dict(suffix=suffix, prefix=prefix, dir=dir).items()
                  if v is not None}
        return _old_mkdtemp(**kwargs)


# XXX backport: ResourceWarning was added in Python 3.2.
# For earlier versions, fall back to RuntimeWarning instead.
_ResourceWarning = RuntimeWarning if _sys.version_info < (3, 2) else ResourceWarning


if _sys.version_info < (3, 2):
    class TemporaryDirectory(object):
        """Create and return a temporary directory.  This has the same
        behavior as mkdtemp but can be used as a context manager.  For
        example:

            with TemporaryDirectory() as tmpdir:
                ...

        Upon exiting the context, the directory and everything contained
        in it are removed.
        """

        def __init__(self, suffix=None, prefix=None, dir=None):
            self.name = mkdtemp(suffix, prefix, dir)
            self._finalizer = _finalize(
                self, self._cleanup, self.name,
                warn_message="Implicitly cleaning up {!r}".format(self))

        @classmethod
        def _cleanup(cls, name, warn_message):
            _rmtree(name)
            _warnings.warn(warn_message, _ResourceWarning)


        def __repr__(self):
            return "<{} {!r}>".format(self.__class__.__name__, self.name)

        def __enter__(self):
            return self.name

        def __exit__(self, exc, value, tb):
            self.cleanup()

        def cleanup(self):
            if self._finalizer.detach():
                _rmtree(self.name)

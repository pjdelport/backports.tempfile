"""
Partial backport of Python 3.7's tempfile module:

    _infer_return_type
    _sanitize_params
    _TemporaryFileCloser
    _TemporaryFileWrapper
    NamedTemporaryFile
    TemporaryFile
    TemporaryDirectory

Backport modifications are marked with marked with "XXX backport".
"""
from __future__ import absolute_import

import io as _io
import os as _os
import functools as _functools
import sys
import warnings as _warnings
from shutil import rmtree as _rmtree

from backports.weakref import finalize

from tempfile import (
    _mkstemp_inner as __mkstemp_inner,
    _bin_openflags as __bin_openflags,
    TMP_MAX as _TMP_MAX,
)

# Do not use backports.os fsencode/fsdecode as it is too unreliable on
# Windows at the moment.  Better for this tempdir backport to
# clearly not support complex filenames until the os backport
# is more mature, except where the native os module provides
# the necessary support.
# However, the backports.os functions can be patched in here by the
# caller and they will be used.
# e.g.
# import backports.tempdir, backports.os
# backports.tempdir._fsencode = backports.os.fsencode
# backports.tempdir._fsdecode = backports.os.fsdecode
try:
    from os import fsencode as _fsencode, fsdecode as _fsdecode
except ImportError:
    _fsencode = _fsdecode = None

try:
    from tempfile import gettempdirb as _gettempdirb
    from tempfile import gettempdir as _gettempdir
except ImportError:
    # XXX backport this gettempdir may not be binary, but we should
    # not trust it before 3.5
    from tempfile import gettempdir as _gettempdirb

    def _gettempdir():
        tempdir_ = _gettempdirb()
        # XXX backport very basic approach for using native gettempdirb
        # to implement unicode gettempdir using _fsdecode.
        # However this is unlikely to be used, at least in CPython native,
        # as gettempdirb and fsdecode were both introduced in 3.5.
        # But _fsdecode can be patched after import.
        if _fsdecode:  # pragma: no cover
            try:
                return _fsdecode(tempdir_)
            except:
                return tempdir_

        # XXX backport very basic approach for returning unicode
        try:
            return unicode(tempdir_)
        except:  # pragma: no cover
            return tempdir_


if sys.version_info[0] == 3:
    _PY3 = True
else:
    _PY3 = False

if _PY3:
    unicode = str

# This variable _was_ unused for legacy reasons, see issue 10354.
# But as of 3.5 we actually use it at runtime so changing it would
# have a possibly desirable side effect...  But we do not want to support
# that as an API.  It is undocumented on purpose.  Do not depend on this.
template = u"tmp"


def _infer_return_type(*args):
    """Look at the type of all args and divine their implied return type."""
    return_type = None
    for arg in args:
        if arg is None:
            continue
        if isinstance(arg, bytes):
            # XXX backport str -> unicode
            if return_type is unicode:
                raise TypeError("Can't mix bytes and non-bytes in "
                                "path components.")
            return_type = bytes
        else:
            if return_type is bytes:
                raise TypeError("Can't mix bytes and non-bytes in "
                                "path components.")
            # XXX backport str -> unicode
            return_type = unicode
    if return_type is None:
        # XXX backport str -> unicode
        return unicode  # tempfile APIs return a unicode by default.
    return return_type


def _sanitize_params(prefix, suffix, dir):
    """Common parameter processing for most APIs in this module."""
    output_type = _infer_return_type(prefix, suffix, dir)
    if suffix is None:
        suffix = output_type()
    if prefix is None:
        if output_type is unicode:
            prefix = template
        else:
            # XXX backport os.fsencode -> bytes where os.fsencode is missing
            if _fsencode:  # pragma: no cover
                prefix = _fsencode(template)
            else:
                prefix = bytes(template)
    if dir is None:
        # XXX backport str -> unicode
        if output_type is unicode:
            dir = _gettempdir()
        else:
            dir = _gettempdirb()
    return prefix, suffix, dir, output_type


# XXX backport:  Rather than backporting all of mkdtemp(), we just create a
# thin wrapper implementing its Python 3.5 signature.
if sys.version_info < (3, 5):
    from tempfile import mkdtemp as old_mkdtemp

    def mkdtemp(suffix=None, prefix=None, dir=None):
        """
        Wrap `tempfile.mkdtemp()` to make the suffix and prefix optional (like Python 3.5).
        """
        kwargs = {k: v for (k, v) in
                  dict(suffix=suffix, prefix=prefix, dir=dir).items()
                  if v is not None}
        return old_mkdtemp(**kwargs)

else:
    from tempfile import mkdtemp


# XXX backport: ResourceWarning was added in Python 3.2.
# For earlier versions, fall back to RuntimeWarning instead.
_ResourceWarning = RuntimeWarning if sys.version_info < (3, 2) else ResourceWarning


class _TemporaryFileCloser:
    """A separate object allowing proper closing of a temporary file's
    underlying file object, without adding a __del__ method to the
    temporary file."""

    file = None  # Set here since __del__ checks it
    close_called = False

    def __init__(self, file, name, delete=True):
        self.file = file
        self.name = name
        self.delete = delete

    # NT provides delete-on-close as a primitive, so we don't need
    # the wrapper to do anything special.  We still use it so that
    # file.name is useful (i.e. not "(fdopen)") with NamedTemporaryFile.
    if _os.name != 'nt':
        # Cache the unlinker so we don't get spurious errors at
        # shutdown when the module-level "os" is None'd out.  Note
        # that this must be referenced as self.unlink, because the
        # name TemporaryFileWrapper may also get None'd out before
        # __del__ is called.

        def close(self, unlink=_os.unlink):
            if not self.close_called and self.file is not None:
                self.close_called = True
                try:
                    self.file.close()
                finally:
                    if self.delete:
                        unlink(self.name)

        # Need to ensure the file is deleted on __del__
        def __del__(self):
            self.close()

    else:
        def close(self):
            if not self.close_called:
                self.close_called = True
                self.file.close()


class _TemporaryFileWrapper:
    """Temporary file wrapper

    This class provides a wrapper around files opened for
    temporary use.  In particular, it seeks to automatically
    remove the file when it is no longer needed.
    """

    def __init__(self, file, name, delete=True):
        self.file = file
        self.name = name
        self.delete = delete
        self._closer = _TemporaryFileCloser(file, name, delete)

    def __getattr__(self, name):
        # Attribute lookups are delegated to the underlying file
        # and cached for non-numeric results
        # (i.e. methods are cached, closed and friends are not)
        file = self.__dict__['file']
        a = getattr(file, name)
        if hasattr(a, '__call__'):
            func = a
            @_functools.wraps(func)
            def func_wrapper(*args, **kwargs):
                return func(*args, **kwargs)
            # Avoid closing the file as long as the wrapper is alive,
            # see issue #18879.
            func_wrapper._closer = self._closer
            a = func_wrapper
        if not isinstance(a, int):
            setattr(self, name, a)
        return a

    # The underlying __enter__ method returns the wrong object
    # (self.file) so override it to return the wrapper
    def __enter__(self):
        self.file.__enter__()
        return self

    # Need to trap __exit__ as well to ensure the file gets
    # deleted when used in a with statement
    def __exit__(self, exc, value, tb):
        result = self.file.__exit__(exc, value, tb)
        self.close()
        return result

    def close(self):
        """
        Close the temporary file, possibly deleting it.
        """
        self._closer.close()

    # iter() doesn't use __getattr__ to find the __iter__ method
    def __iter__(self):
        # Don't return iter(self.file), but yield from it to avoid closing
        # file as long as it's being used as iterator (see issue #23700).  We
        # can't use 'yield from' here because iter(file) returns the file
        # object itself, which has a close method, and thus the file would get
        # closed when the generator is finalized, due to PEP380 semantics.
        for line in self.file:
            yield line


def NamedTemporaryFile(mode='w+b', buffering=-1, encoding=None,
                       newline=None, suffix=None, prefix=None,
                       dir=None, delete=True):
    """Create and return a temporary file.
    Arguments:
    'prefix', 'suffix', 'dir' -- as for mkstemp.
    'mode' -- the mode argument to io.open (default "w+b").
    'buffering' -- the buffer size argument to io.open (default -1).
    'encoding' -- the encoding argument to io.open (default None)
    'newline' -- the newline argument to io.open (default None)
    'delete' -- whether the file is deleted on close (default True).
    The file is created as mkstemp() would do it.

    Returns an object with a file-like interface; the name of the file
    is accessible as its 'name' attribute.  The file will be automatically
    deleted when it is closed unless the 'delete' argument is set to False.
    """

    prefix, suffix, dir, output_type = _sanitize_params(prefix, suffix, dir)

    flags = __bin_openflags

    # Setting O_TEMPORARY in the flags causes the OS to delete
    # the file when it is closed.  This is only supported by Windows.
    if _os.name == 'nt' and delete:
        flags |= _os.O_TEMPORARY

    # XXX: Try using output_type if it exists, otherwise fall back to
    # prior signature
    try:
        (fd, name) = __mkstemp_inner(dir, prefix, suffix, flags, output_type)
    except TypeError:
        (fd, name) = __mkstemp_inner(dir, prefix, suffix, flags)

    try:
        file = _io.open(fd, mode, buffering=buffering,
                        newline=newline, encoding=encoding)

        return _TemporaryFileWrapper(file, name, delete)
    except BaseException:
        _os.unlink(name)
        _os.close(fd)
        raise


if _os.name != 'posix' or _os.sys.platform == 'cygwin':  # pragma: no cover
    # On non-POSIX and Cygwin systems, assume that we cannot unlink a file
    # while it is open.
    TemporaryFile = NamedTemporaryFile

else:
    # Is the O_TMPFILE flag available and does it work?
    # The flag is set to False if os.open(dir, os.O_TMPFILE) raises an
    # IsADirectoryError exception
    _O_TMPFILE_WORKS = hasattr(_os, 'O_TMPFILE')

    def TemporaryFile(mode='w+b', buffering=-1, encoding=None,
                      newline=None, suffix=None, prefix=None,
                      dir=None):
        """Create and return a temporary file.
        Arguments:
        'prefix', 'suffix', 'dir' -- as for mkstemp.
        'mode' -- the mode argument to io.open (default "w+b").
        'buffering' -- the buffer size argument to io.open (default -1).
        'encoding' -- the encoding argument to io.open (default None)
        'newline' -- the newline argument to io.open (default None)
        The file is created as mkstemp() would do it.

        Returns an object with a file-like interface.  The file has no
        name, and will cease to exist when it is closed.
        """
        global _O_TMPFILE_WORKS

        prefix, suffix, dir, output_type = _sanitize_params(prefix, suffix, dir)

        flags = __bin_openflags
        if _O_TMPFILE_WORKS:
            try:
                flags2 = (flags | _os.O_TMPFILE) & ~_os.O_CREAT
                fd = _os.open(dir, flags2, 0o600)
            except IsADirectoryError:  # pragma: no cover
                # Linux kernel older than 3.11 ignores the O_TMPFILE flag:
                # O_TMPFILE is read as O_DIRECTORY. Trying to open a directory
                # with O_RDWR|O_DIRECTORY fails with IsADirectoryError, a
                # directory cannot be open to write. Set flag to False to not
                # try again.
                _O_TMPFILE_WORKS = False
            except OSError:  # pragma: no cover
                # The filesystem of the directory does not support O_TMPFILE.
                # For example, OSError(95, 'Operation not supported').
                #
                # On Linux kernel older than 3.11, trying to open a regular
                # file (or a symbolic link to a regular file) with O_TMPFILE
                # fails with NotADirectoryError, because O_TMPFILE is read as
                # O_DIRECTORY.
                pass
            else:
                try:
                    return _io.open(fd, mode, buffering=buffering,
                                    newline=newline, encoding=encoding)
                except:
                    _os.close(fd)
                    raise
            # Fallback to _mkstemp_inner().

        try:
            (fd, name) = __mkstemp_inner(dir, prefix, suffix, flags, output_type)
        except TypeError:
            (fd, name) = __mkstemp_inner(dir, prefix, suffix, flags)
        try:
            _os.unlink(name)
            return _io.open(fd, mode, buffering=buffering,
                            newline=newline, encoding=encoding)
        except:
            _os.close(fd)
            raise


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
        self._finalizer = finalize(
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

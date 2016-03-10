"""
Partial backport of Python 3.5's test.test_tempfile:

    BaseTestCase
    TestTemporaryDirectory

Backport modifications are marked with "XXX backport".
"""
import tempfile
import errno
import os
import sys
import re
import warnings

from backports.tempfile import TemporaryDirectory

import unittest
from backports.test import support
from backports.test.support import script_helper


# XXX backport: ResourceWarning was added in Python 3.2.
# For earlier versions, fall back to RuntimeWarning instead.
_ResourceWarning = RuntimeWarning if sys.version_info < (3, 2) else ResourceWarning


# Common functionality.

class BaseTestCase(unittest.TestCase):

    # XXX backport: tempfile's random template changed in Python 3.
    if sys.version_info < (3,):
        str_check = re.compile(r"^[a-zA-Z0-9_-]{6}$")
        b_check = re.compile(br"^[a-zA-Z0-9_-]{6}$")
    else:
        str_check = re.compile(r"^[a-z0-9_-]{8}$")
        b_check = re.compile(br"^[a-z0-9_-]{8}$")

    def setUp(self):
        self._warnings_manager = support.check_warnings()
        self._warnings_manager.__enter__()
        warnings.filterwarnings("ignore", category=RuntimeWarning,
                                message="mktemp", module=__name__)

    def tearDown(self):
        self._warnings_manager.__exit__(None, None, None)


    def nameCheck(self, name, dir, pre, suf):  # pragma: no cover (test support code)
        (ndir, nbase) = os.path.split(name)
        npre  = nbase[:len(pre)]
        nsuf  = nbase[len(nbase)-len(suf):]

        # XXX backport: TODO: These do not test for unicode vs. str/bytes under Python < 3.
        # XXX backport: TODO: Enable unicode_literals and make these pass?
        if dir is not None:
            self.assertIs(type(name), str if type(dir) is str else bytes,
                          "unexpected return type")
        if pre is not None:
            self.assertIs(type(name), str if type(pre) is str else bytes,
                          "unexpected return type")
        if suf is not None:
            self.assertIs(type(name), str if type(suf) is str else bytes,
                          "unexpected return type")
        if (dir, pre, suf) == (None, None, None):
            self.assertIs(type(name), str, "default return type must be str")

        # check for equality of the absolute paths!
        self.assertEqual(os.path.abspath(ndir), os.path.abspath(dir),
                         "file %r not in directory %r" % (name, dir))
        self.assertEqual(npre, pre,
                         "file %r does not begin with %r" % (nbase, pre))
        self.assertEqual(nsuf, suf,
                         "file %r does not end with %r" % (nbase, suf))

        nbase = nbase[len(pre):len(nbase)-len(suf)]
        check = self.str_check if isinstance(nbase, str) else self.b_check
        self.assertTrue(check.match(nbase),
                        "random characters %r do not match %r"
                        % (nbase, check.pattern))


class TestTemporaryDirectory(BaseTestCase):
    """Test TemporaryDirectory()."""

    def do_create(self, dir=None, pre="", suf="", recurse=1):
        if dir is None:
            dir = tempfile.gettempdir()
        tmp = TemporaryDirectory(dir=dir, prefix=pre, suffix=suf)
        self.nameCheck(tmp.name, dir, pre, suf)
        # Create a subdirectory and some files
        if recurse:
            d1 = self.do_create(tmp.name, pre, suf, recurse-1)
            d1.name = None
        with open(os.path.join(tmp.name, "test.txt"), "wb") as f:
            f.write(b"Hello world!")
        return tmp

    def test_mkdtemp_failure(self):
        # Check no additional exception if mkdtemp fails
        # Previously would raise AttributeError instead
        # (noted as part of Issue #10188)
        with TemporaryDirectory() as nonexistent:
            pass
        # XXX backport: Fall back to OSError on Python < 3 (errno gets tested below)
        _FileNotFoundError = OSError if sys.version_info < (3,) else FileNotFoundError
        with self.assertRaises(_FileNotFoundError) as cm:
            TemporaryDirectory(dir=nonexistent)
        self.assertEqual(cm.exception.errno, errno.ENOENT)

    def test_explicit_cleanup(self):
        # A TemporaryDirectory is deleted when cleaned up
        dir = tempfile.mkdtemp()
        try:
            d = self.do_create(dir=dir)
            self.assertTrue(os.path.exists(d.name),
                            "TemporaryDirectory %s does not exist" % d.name)
            d.cleanup()
            self.assertFalse(os.path.exists(d.name),
                        "TemporaryDirectory %s exists after cleanup" % d.name)
        finally:
            os.rmdir(dir)

    @support.skip_unless_symlink
    def test_cleanup_with_symlink_to_a_directory(self):
        # cleanup() should not follow symlinks to directories (issue #12464)
        d1 = self.do_create()
        d2 = self.do_create(recurse=0)

        # Symlink d1/foo -> d2
        os.symlink(d2.name, os.path.join(d1.name, "foo"))

        # This call to cleanup() should not follow the "foo" symlink
        d1.cleanup()

        self.assertFalse(os.path.exists(d1.name),
                         "TemporaryDirectory %s exists after cleanup" % d1.name)
        self.assertTrue(os.path.exists(d2.name),
                        "Directory pointed to by a symlink was deleted")
        self.assertEqual(os.listdir(d2.name), ['test.txt'],
                         "Contents of the directory pointed to by a symlink "
                         "were deleted")
        d2.cleanup()

    @support.cpython_only
    def test_del_on_collection(self):
        # A TemporaryDirectory is deleted when garbage collected
        dir = tempfile.mkdtemp()
        try:
            d = self.do_create(dir=dir)
            name = d.name
            del d # Rely on refcounting to invoke __del__
            self.assertFalse(os.path.exists(name),
                        "TemporaryDirectory %s exists after __del__" % name)
        finally:
            os.rmdir(dir)

    def test_del_on_shutdown(self):
        # XXX backport: __builtin__ renamed to builtins
        _builtins = ('__builtin__' if sys.version_info < (3,) else 'builtins')

        # A TemporaryDirectory may be cleaned up during shutdown
        with self.do_create() as dir:
            for mod in (_builtins, 'os', 'shutil', 'sys', 'tempfile', 'warnings'):
                code = """if True:
                    import {_builtins}
                    import os
                    import shutil
                    import sys
                    import tempfile
                    import warnings

                    from backports.tempfile import TemporaryDirectory

                    tmp = TemporaryDirectory(dir={dir!r})
                    # XXX backport: No buffer attribute in Python < 3
                    _stdout = sys.stdout if sys.version_info < (3,) else sys.stdout.buffer
                    _stdout.write(tmp.name.encode())

                    tmp2 = os.path.join(tmp.name, 'test_dir')
                    os.mkdir(tmp2)
                    with open(os.path.join(tmp2, "test.txt"), "w") as f:
                        f.write("Hello world!")

                    {mod}.tmp = tmp

                    warnings.filterwarnings("always", category={_ResourceWarning})
                    """.format(dir=dir, mod=mod,
                               # XXX backport:
                               _builtins=_builtins,
                               _ResourceWarning=_ResourceWarning.__name__)
                rc, out, err = script_helper.assert_python_ok("-c", code)
                tmp_name = out.decode().strip()
                self.assertFalse(os.path.exists(tmp_name),
                            "TemporaryDirectory %s exists after cleanup" % tmp_name)
                err = err.decode('utf-8', 'backslashreplace')
                self.assertNotIn("Exception ", err)
                # XXX backport:
                self.assertIn("{}: Implicitly cleaning up".format(_ResourceWarning.__name__), err)

    def test_exit_on_shutdown(self):
        # Issue #22427
        with self.do_create() as dir:
            code = """if True:
                import sys
                from backports.tempfile import TemporaryDirectory
                import warnings

                def generator():
                    with TemporaryDirectory(dir={dir!r}) as tmp:
                        yield tmp
                g = generator()
                # XXX backport: No buffer attribute in Python < 3
                _stdout = sys.stdout if sys.version_info < (3,) else sys.stdout.buffer
                _stdout.write(next(g).encode())

                warnings.filterwarnings("always", category={_ResourceWarning})
                """.format(dir=dir,
                           _ResourceWarning=_ResourceWarning.__name__)
            rc, out, err = script_helper.assert_python_ok("-c", code)
            tmp_name = out.decode().strip()
            self.assertFalse(os.path.exists(tmp_name),
                        "TemporaryDirectory %s exists after cleanup" % tmp_name)
            err = err.decode('utf-8', 'backslashreplace')
            self.assertNotIn("Exception ", err)
            # XXX backport:
            self.assertIn("{}: Implicitly cleaning up".format(_ResourceWarning.__name__), err)

    def test_warnings_on_cleanup(self):
        # ResourceWarning will be triggered by __del__
        with self.do_create() as dir:
            d = self.do_create(dir=dir, recurse=3)
            name = d.name

            # Check for the resource warning
            with support.check_warnings(('Implicitly', _ResourceWarning), quiet=False):
                warnings.filterwarnings("always", category=_ResourceWarning)
                del d
                support.gc_collect()
            self.assertFalse(os.path.exists(name),
                        "TemporaryDirectory %s exists after __del__" % name)

    def test_multiple_close(self):
        # Can be cleaned-up many times without error
        d = self.do_create()
        d.cleanup()
        d.cleanup()
        d.cleanup()

    def test_context_manager(self):
        # Can be used as a context manager
        d = self.do_create()
        with d as name:
            self.assertTrue(os.path.exists(name))
            self.assertEqual(name, d.name)
        self.assertFalse(os.path.exists(name))

"""
Partial backport of Python 3.7's test.test_tempfile:

    TestLowLevelInternals
    BaseTestCase
    TestNamedTemporaryFile
    TestTemporaryFile
    TestTemporaryDirectory

Backport modifications are marked with "XXX backport".
"""
# XXX backport: TODO: These do not test for unicode vs. str/bytes under Python < 3.

import tempfile as _tempfile
import errno
import os
import sys
import re
import warnings

from backports import weakref
from backports import tempfile
from backports.tempfile import TemporaryDirectory

import unittest
import mock
from backports.test import support
from backports.test.support import script_helper


if sys.version_info[0] == 3:
    PY3 = True
else:
    PY3 = False

if PY3:
    unicode = str


# XXX backport: ResourceWarning was added in Python 3.2.
# For earlier versions, fall back to RuntimeWarning instead.
_ResourceWarning = RuntimeWarning if sys.version_info < (3, 2) else ResourceWarning


# XXX backport str -> unicode throughout class
class TestLowLevelInternals(unittest.TestCase):
    def test_infer_return_type_singles(self):
        self.assertIs(unicode, tempfile._infer_return_type(u''))
        self.assertIs(bytes, tempfile._infer_return_type(b''))
        self.assertIs(unicode, tempfile._infer_return_type(None))

    def test_infer_return_type_multiples(self):
        self.assertIs(unicode, tempfile._infer_return_type(u'', u''))
        self.assertIs(bytes, tempfile._infer_return_type(b'', b''))
        with self.assertRaises(TypeError):
            tempfile._infer_return_type(u'', b'')
        with self.assertRaises(TypeError):
            tempfile._infer_return_type(b'', u'')

    def test_infer_return_type_multiples_and_none(self):
        self.assertIs(unicode, tempfile._infer_return_type(None, u''))
        self.assertIs(unicode, tempfile._infer_return_type(u'', None))
        self.assertIs(unicode, tempfile._infer_return_type(None, None))
        self.assertIs(bytes, tempfile._infer_return_type(b'', None))
        self.assertIs(bytes, tempfile._infer_return_type(None, b''))
        with self.assertRaises(TypeError):
            tempfile._infer_return_type(u'', None, b'')
        with self.assertRaises(TypeError):
            tempfile._infer_return_type(b'', None, u'')


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

        if dir is not None:
            self.assertIs(type(name), unicode if type(dir) is unicode else bytes,
                          "unexpected return type")
        if pre is not None:
            self.assertIs(type(name), unicode if type(pre) is unicode else bytes,
                          "unexpected return type")
        if suf is not None:
            self.assertIs(type(name), unicode if type(suf) is unicode else bytes,
                          "unexpected return type")
        if (dir, pre, suf) == (None, None, None):
            self.assertIs(type(name), unicode, "default return type must be str")

        # check for equality of the absolute paths!
        self.assertEqual(os.path.abspath(ndir), os.path.abspath(dir),
                         "file %r not in directory %r" % (name, dir))
        self.assertEqual(npre, pre,
                         "file %r does not begin with %r" % (nbase, pre))
        self.assertEqual(nsuf, suf,
                         "file %r does not end with %r" % (nbase, suf))

        nbase = nbase[len(pre):len(nbase)-len(suf)]
        check = self.str_check if isinstance(nbase, unicode) else self.b_check
        self.assertTrue(check.match(nbase),
                        "random characters %r do not match %r"
                        % (nbase, check.pattern))


# We test _TemporaryFileWrapper by testing NamedTemporaryFile.


class TestNamedTemporaryFile(BaseTestCase):
    """Test NamedTemporaryFile()."""

    def do_create(self, dir=None, pre=u"", suf=u"", delete=True):
        if dir is None:
            # XXX backport this is using the backports _gettempdir
            # to avoid mixing unicode and bytes args
            dir = tempfile._gettempdir()
        file = tempfile.NamedTemporaryFile(dir=dir, prefix=pre, suffix=suf,
                                           delete=delete)

        self.nameCheck(file.name, dir, pre, suf)
        return file

    def test_basic(self):
        # NamedTemporaryFile can create files
        self.do_create()
        self.do_create(pre=u"a")
        self.do_create(suf=u"b")
        self.do_create(pre=u"a", suf=u"b")
        self.do_create(pre=u"aa", suf=u".txt")

    def test_method_lookup(self):
        # Issue #18879: Looking up a temporary file method should keep it
        # alive long enough.
        f = self.do_create()
        wr = weakref.ref(f)
        write = f.write
        write2 = f.write
        del f
        write(b'foo')
        del write
        write2(b'bar')
        del write2
        if support.check_impl_detail(cpython=True):
            # No reference cycle was created.
            self.assertIsNone(wr())

    def test_iter(self):
        # Issue #23700: getting iterator from a temporary file should keep
        # it alive as long as it's being iterated over
        lines = [b'spam\n', b'eggs\n', b'beans\n']
        def make_file():
            f = tempfile.NamedTemporaryFile(mode='w+b')
            f.write(b''.join(lines))
            f.seek(0)
            return f
        for i, l in enumerate(make_file()):
            self.assertEqual(l, lines[i])
        self.assertEqual(i, len(lines) - 1)

    def test_creates_named(self):
        # NamedTemporaryFile creates files with names
        f = tempfile.NamedTemporaryFile()
        self.assertTrue(os.path.exists(f.name),
                        "NamedTemporaryFile %s does not exist" % f.name)

    def test_del_on_close(self):
        # A NamedTemporaryFile is deleted when closed
        dir = tempfile.mkdtemp()
        try:
            f = tempfile.NamedTemporaryFile(dir=dir)
            f.write(b'blat')
            f.close()
            self.assertFalse(os.path.exists(f.name),
                        "NamedTemporaryFile %s exists after close" % f.name)
        finally:
            os.rmdir(dir)

    def test_dis_del_on_close(self):
        # Tests that delete-on-close can be disabled
        dir = tempfile.mkdtemp()
        tmp = None
        try:
            f = tempfile.NamedTemporaryFile(dir=dir, delete=False)
            tmp = f.name
            f.write(b'blat')
            f.close()
            self.assertTrue(os.path.exists(f.name),
                        "NamedTemporaryFile %s missing after close" % f.name)
        finally:
            if tmp is not None:
                os.unlink(tmp)
            os.rmdir(dir)

    def test_multiple_close(self):
        # A NamedTemporaryFile can be closed many times without error
        f = tempfile.NamedTemporaryFile()
        f.write(b'abc\n')
        f.close()
        f.close()
        f.close()

    def test_context_manager(self):
        # A NamedTemporaryFile can be used as a context manager
        with tempfile.NamedTemporaryFile() as f:
            self.assertTrue(os.path.exists(f.name))
        self.assertFalse(os.path.exists(f.name))
        def use_closed():
            with f:
                pass
        self.assertRaises(ValueError, use_closed)

    def test_no_leak_fd(self):
        # Issue #21058: don't leak file descriptor when io.open() fails
        closed = []
        os_close = os.close
        def close(fd):
            closed.append(fd)
            os_close(fd)

        with mock.patch('os.close', side_effect=close):
            with mock.patch('io.open', side_effect=ValueError):
                self.assertRaises(ValueError, tempfile.NamedTemporaryFile)
                self.assertEqual(len(closed), 1)

    def test_bad_mode(self):
        dir = tempfile.mkdtemp()
        self.addCleanup(support.rmtree, dir)
        with self.assertRaises(ValueError):
            tempfile.NamedTemporaryFile(mode='wr', dir=dir)
        with self.assertRaises(TypeError):
            tempfile.NamedTemporaryFile(mode=2, dir=dir)
        self.assertEqual(os.listdir(dir), [])

    # How to test the mode and bufsize parameters?


if tempfile.NamedTemporaryFile is not tempfile.TemporaryFile:

    class TestTemporaryFile(BaseTestCase):
        """Test TemporaryFile()."""

        def test_basic(self):
            # TemporaryFile can create files
            # No point in testing the name params - the file has no name.
            tempfile.TemporaryFile()

        def test_has_no_name(self):
            # TemporaryFile creates files with no names (on this system)
            dir = _tempfile.mkdtemp()
            f = tempfile.TemporaryFile(dir=dir)
            f.write(b'blat')

            # Sneaky: because this file has no name, it should not prevent
            # us from removing the directory it was created in.
            try:
                os.rmdir(dir)
            except:
                # cleanup
                f.close()
                os.rmdir(dir)
                raise

        def test_multiple_close(self):
            # A TemporaryFile can be closed many times without error
            f = tempfile.TemporaryFile()
            f.write(b'abc\n')
            f.close()
            f.close()
            f.close()

        # How to test the mode and bufsize parameters?
        def test_mode_and_encoding(self):

            def roundtrip(input, *args, **kwargs):
                with tempfile.TemporaryFile(*args, **kwargs) as fileobj:
                    fileobj.write(input)
                    fileobj.seek(0)
                    self.assertEqual(input, fileobj.read())

            roundtrip(b"1234", "w+b")
            roundtrip(u"abdc\n", "w+")
            roundtrip(u"\u039B", "w+", encoding="utf-16")
            roundtrip(u"foo\r\n", "w+", newline="")

        def test_no_leak_fd(self):
            # Issue #21058: don't leak file descriptor when io.open() fails
            closed = []
            os_close = os.close
            def close(fd):
                closed.append(fd)
                os_close(fd)

            with mock.patch('os.close', side_effect=close):
                with mock.patch('io.open', side_effect=ValueError):
                    self.assertRaises(ValueError, tempfile.TemporaryFile)
                    self.assertEqual(len(closed), 1)


class TestTemporaryDirectory(BaseTestCase):
    """Test TemporaryDirectory()."""

    def do_create(self, dir=None, pre="", suf="", recurse=1):
        if dir is None:
            dir = _tempfile.gettempdir()
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
        dir = _tempfile.mkdtemp()
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
        dir = _tempfile.mkdtemp()
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

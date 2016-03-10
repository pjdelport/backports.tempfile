# coding: utf-8
from setuptools import setup, find_packages

setup(
    name='backports.tempfile',
    description="Backport of new features in Python's tempfile module",
    url='https://github.com/pjdelport/backports.tempfile',

    author=u'Piët Delport',
    author_email='pjdelport@gmail.com',

    package_dir={'': 'src'},
    packages=find_packages('src'),

    setup_requires=['setuptools_scm'],
    use_scm_version=True,

    install_requires=[
        'backports.weakref',
    ],

    license='Python Software Foundation License',
    classifiers=[
        'Development Status :: 6 - Mature',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: Python Software Foundation License',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Topic :: Software Development :: Libraries :: Python Modules',
    ],
)

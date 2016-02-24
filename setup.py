from setuptools import setup, find_packages

from idiokit import __version__

setup(
    name="idiokit",
    version=__version__,
    author="Clarified Networks",
    author_email="contact@clarifiednetworks.com",
    url="https://github.com/abusesa/idiokit",
    packages=find_packages(exclude=["*.tests"]),
    license="MIT"
)

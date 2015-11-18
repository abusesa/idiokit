import os
import errno
from distutils.core import setup
from distutils.dir_util import remove_tree
from distutils.util import convert_path
from distutils.command.build import build as _build
from distutils.command.install import install as _install


def rmtree(path):
    try:
        remove_tree(convert_path(path))
    except OSError, err:
        if err.errno != errno.ENOENT:
            raise


class Build(_build):
    def run(self):
        clean = self.distribution.reinitialize_command("clean", reinit_subcommands=True)
        clean.all = True
        self.distribution.run_command("clean")
        _build.run(self)


class Install(_install):
    def run(self):
        build_py = self.distribution.get_command_obj("build_py")
        if self.distribution.packages:
            for package in self.distribution.packages:
                package_dir = build_py.get_package_dir(package)
                rmtree(os.path.join(self.install_lib, package_dir))
        _install.run(self)


setup(
    name="idiokit",
    version="2.2.0",
    author="Clarified Networks",
    author_email="contact@clarifiednetworks.com",
    url="https://bitbucket.org/clarifiednetworks/idiokit",
    packages=[
        "idiokit",
        "idiokit.xmpp",
        "idiokit.dns",
        "idiokit.http",
        "idiokit.http.handlers"
    ],
    license="MIT",
    cmdclass={
        "build": Build,
        "install": Install
    }
)

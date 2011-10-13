import os
from distutils.core import setup
from distutils.dir_util import remove_tree
from distutils.util import convert_path
from distutils.command.install import install as _install

class install(_install):
    def run(self):
        path = os.path.join(self.install_lib, "idiokit")
        remove_tree(convert_path(path))
        return _install.run(self)

setup(
    cmdclass={"install": install},
    name="idiokit",
    version="1.0",
    author="Clarified Networks",
    author_email="contact@clarifiednetworks.com",
    url="https://bitbucket.org/clarifiednetworks/idiokit",
    packages=["idiokit"]
    )

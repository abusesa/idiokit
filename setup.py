import os
from distutils.core import setup
from distutils.dir_util import remove_tree
from distutils.util import convert_path
from distutils.command.install import install as _install

class install(_install):
    def run(self):
        # Installed historical files like idiokit/xmpp.py may
        # mess up importing current subpackages such as
        # idiokit/xmpp.
        path = os.path.join(self.install_lib, "idiokit")
        remove_tree(convert_path(path))

        return _install.run(self)

setup(
    cmdclass={"install": install},
    name="idiokit",
    version="2.0",
    author="Clarified Networks",
    author_email="contact@clarifiednetworks.com",
    url="https://bitbucket.org/clarifiednetworks/idiokit",
    packages=["idiokit", "idiokit.xmpp"]
    )

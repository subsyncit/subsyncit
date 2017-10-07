# Subsyncit - File sync backed by Subversion
#
#   Copyright (c) 2016 - 2017, Paul Hammant
#
#   This program is free software: you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation, version 3.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with this program.  If not, see <https://www.gnu.org/licenses/>.

import fileinput
import sh
import sys
import os


def make_or_wipe_server_side_subversion_repo(svn_parent_root, repo_name, compression, deltification, rep_sharing):

    if not str(svn_parent_root).endswith("/"):
        svn_parent_root += "/"

    # Wipe the Subversion repo
    sh.rm("-rf", svn_parent_root + repo_name)
    if not os.path.exists(svn_parent_root):
      os.makedirs(svn_parent_root)
    sh.svnadmin("create", svn_parent_root + repo_name)
    sh.chown("-R", "www-data:www-data", svn_parent_root)
    sh.chmod("-R", "755", svn_parent_root)
    sh.sync()
    for line in fileinput.FileInput(svn_parent_root + repo_name + "/db/fsfs.conf", inplace=True):
        if compression and "# compression-level" in line:
            print("compression-level = 0")
        elif deltification and "# max-deltification-walk" in line:
            print("max-deltification-walk = 0")
        elif rep_sharing and "# enable-rep-sharing" in line:
            print("enable-rep-sharing = false")
        else:
            print(line)

if __name__ == "__main__":
    print("Args: <parent-folder> <repo-name>")
    make_or_wipe_server_side_subversion_repo(sys.argv[1], sys.argv[2], False, True, True)

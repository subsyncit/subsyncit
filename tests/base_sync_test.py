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
import hashlib
import os
import shutil
import time
import unittest

import requests
import sh


class BaseSyncTest(unittest.TestCase):


    line = ""

    def setup(self):
        self.line = ""
        self.user = "davsvn"
        self.passwd = "davsvn"
        self.svn_repo = "http://127.0.0.1:8099/"


    def reset_test_dir(self, dirname):
        if os.path.exists(dirname):
            shutil.rmtree(dirname)
        os.makedirs(dirname)

        if os.name != 'nt':
            home_dir = os.path.expanduser('~' + (os.getenv("SUDO_USER") or os.getenv("USER")))
        else:
            home_dir = os.path.expanduser(str(os.getenv('USERPROFILE')))

        if not dirname.endswith(os.sep):
            dirname += os.sep

        subsyncit_dir = home_dir + os.sep + ".subsyncit"
        db_dir = subsyncit_dir + os.sep + dirname.replace("/","%47").replace(":","%58").replace("\\","%92")
        # print("path of subsyncit settings=" + db_dir + " pertaining to " + dirname)
        if os.path.exists(db_dir):
             shutil.rmtree(db_dir)

    def signal_stop_of_subsyncIt(self, dir_):
        if not os.path.exists(dir_):
            os.makedirs(dir_)

        stop_ = dir_ + ".subsyncit.stop"
        with open(stop_, "w") as text_file:
            text_file.write("anything")

    def wait_for_file_to_appear(self, op2):
        ix = 0
        while not os.path.exists(op2):
            ix += 1
            if ix > 45:
                self.fail("no sync'd file")
            time.sleep(1)


    def wait_for_URL_to_appear(self, url):
        ix = 0

        status = requests.get(url, auth=(self.user, self.passwd), verify=False).status_code
        while status == 404:
            ix += 1
            if ix > 45:
                break
            time.sleep(1)
            status = requests.get(url, auth=(self.user, self.passwd), verify=False).status_code

        if status != 200:
            self.fail("URL " + url + " should have appeared, but it did not (status code: " + str(status) + ")")


    def process_output(self, line):
        print(line)
        self.line += ("\n" + line)


    def start_two_subsyncits(self, dir):
        p1 = self.start_subsyncit(self.svn_repo + dir, self.testSyncDir1)
        p2 = self.start_subsyncit(self.svn_repo + dir, self.testSyncDir2)
        return p1, p2


    def start_subsyncit(self, svn_repo, dir, passwd=None):
        if passwd is None:
            passwd = self.passwd
        print("Subsyncit start. URL: " + svn_repo + ", dir: " + dir)
        python = sh.python3("subsyncit.py", svn_repo, dir, self.user, '--no-verify-ssl-cert',
                           "--sleep-secs-between-polling", "1",
                           '--passwd', passwd, _out=self.process_output,
                           _err_to_out=True, _bg=True)
        return python


    def wait_for_file_contents_to_be_sized_above(self, f, sz):
        self.wait_for_file_to_appear(f)
        while os.stat(f).st_size < sz:
            time.sleep(.05)


    def wait_for_file_contents_to_be_sized_below(self, f, sz):
        self.wait_for_file_to_appear(f)
        while os.stat(f).st_size >= sz:
            time.sleep(.05)


    def wait_for_file_contents_to_contain(self, f, val):

        self.wait_for_file_to_appear(f)
        contents = self.file_contents(f)
        ix = 0
        while val not in contents:
            ix += 1
            if ix > 15:
                self.assertIn(val, contents, "file " + f + " should have contained '" + val + "' but was '" + contents + "' instead.")
            time.sleep(1)
            contents = self.file_contents(f)

    def file_contents(self, f):
        open1 = open(f, encoding="utf-8")
        contents = open1.read()
        open1.close()
        return contents

    def wait_for_file_to_disappear(self, f):
        ix = 0
        while os.path.exists(f):
            ix += 1
            if ix > 45:
                self.fail("file " + f + " didn't disappear in 45 secs")
            time.sleep(1)


    def upload_file(self, filename, remote_path):
        start = time.time()
        f = open(filename, 'rb')
        requests.put(remote_path, auth=(self.user, self.passwd), data=f, verify=False)
        f.close()

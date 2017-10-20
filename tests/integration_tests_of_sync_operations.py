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
import os
import time
import unittest
import shutil
import glob2
import requests
import sh
from decorator import decorator

import docker
from docker.errors import NotFound


class IntegrationTestsOfSyncOperations(unittest.TestCase):

    i = 0
    test_sync_dir_a = ""
    test_sync_dir_b = ""
    p1 = None
    p2 = None
    container = None

    def __init__(self, testname, size):
        super(IntegrationTestsOfSyncOperations, self).__init__(testname)
        self.size = size
        self.output = ""
        self.user = "davsvn"
        self.passwd = "davsvn"
        self.svn_repo = "http://127.0.0.1:8099/svn/testrepo/"
        self.line = ""

    @classmethod
    def setUpClass(cls):
        sh.rm("-rf", str(sh.pwd()).strip('\n') + "/integrationTests/")

        cls.client = docker.from_env()

        print("Kill Docker container (if any) from last test suite invocation...")
        cls.kill_docker_container(True)
        cls.kill_docker_container(True)
        print("... done")

        print("Start Docker container for this test suite invocation...")
        cls.client.containers.run("subsyncit/alpine-svn-dav", name="subsyncitTests", detach=True, ports={'80/tcp': 8099}, auto_remove=True)
        content = ""
        while "It works!" not in content:
            try:
                get = requests.get("http://127.0.0.1:8099")
                content = get.content.decode("utf-8")
            except requests.exceptions.ConnectionError:
                pass

        requests.request('MKCOL', "http://127.0.0.1:8099/svn/testrepo/integrationTests", auth=("davsvn", "davsvn"), verify=False)
        print("... done")

    @classmethod
    def tearDownClass(cls):
        pass
        #cls.kill_docker_container(False)

    @classmethod
    def kill_docker_container(cls, wait):
        try:
            ctr = cls.client.containers.get("subsyncitTests")
            ctr.stop()
            if wait:
                status = 200
                while status == 200:
                    status = -1
                    try:
                        get = requests.get("http://127.0.0.1:8099")
                        status = get.status_code
                    except:
                        pass
                while cls.client.containers.get("subsyncitTests"):
                    time.sleep(0.2)
                    pass  # keep looping until there's an exception
        except NotFound:
            pass

    def setUp(self):
        IntegrationTestsOfSyncOperations.i += 1
        testNum = str(IntegrationTestsOfSyncOperations.i)

        self.rel_dir_a = "integrationTests/test_" + testNum + "a/"
        self.test_sync_dir_a = str(sh.pwd()).strip('\n') + self.rel_dir_a
        self.reset_test_dir(self.test_sync_dir_a)

        self.rel_dir_b = "integrationTests/test_" + testNum + "b/"
        self.test_sync_dir_b = str(sh.pwd()).strip('\n') + self.rel_dir_b
        self.reset_test_dir(self.test_sync_dir_b)

        self.svn_url = self.svn_repo + "integrationTests/test_" + testNum + "/"
        self.expect201(requests.request('MKCOL', self.svn_url, auth=(self.user, self.passwd), verify=False))


    def teardown(self):
        self.end(self.p1, self.test_sync_dir_a)
        self.end(self.p2, self.test_sync_dir_b)


    def end(self, p, dir):
        if p is not None:
            self.signal_stop_of_subsyncIt(dir)

    @decorator
    def timedtest(f, *args, **kwargs):

        t1 = time.time()
        out = f(*args, **kwargs)
        t2 = time.time()
        dt = str((t2 - t1) * 1.00)
        dtout = dt[:(dt.find(".") + 4)]
        print("----------------------------------------------------------")
        print('Test {0} finished in {1}s'.format(getattr(f, "__name__", "<unnamed>"), dtout))
        print("==========================================================")

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
        start = time.time()
        while not os.path.exists(op2):
            if time.time() - start > 15:
                self.fail("no sync'd file")
            time.sleep(.01)


    def wait_for_URL_to_appear(self, url):

        status = requests.get(url, auth=(self.user, self.passwd), verify=False).status_code
        while status == 404:
            start = time.time()
            if time.time() - start > 15:
                break
            time.sleep(.1)
            status = requests.get(url, auth=(self.user, self.passwd), verify=False).status_code

        if status != 200:
            self.fail("URL " + url + " should have appeared, but it did not (status code: " + str(status) + ")")


    def process_output(self, line):
        print(line)
        self.line += ("\n" + line)


    def start_two_subsyncits(self):
        p1 = self.start_subsyncit(self.svn_url, self.test_sync_dir_a)
        p2 = self.start_subsyncit(self.svn_url, self.test_sync_dir_b)
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


    def wait_for_file_contents_to_be_sized_above_or_eq_too(self, f, sz):
        self.wait_for_file_to_appear(f)
        start = time.time()
        while os.stat(f).st_size < sz:
            time.sleep(.01)
            if time.time() - start > 15:
                self.fail("should have made it above that size by now")


    def wait_for_file_contents_to_be_sized_below(self, f, sz):
        self.wait_for_file_to_appear(f)
        start = time.time()
        while os.stat(f).st_size >= sz:
            time.sleep(.01)
            if time.time() - start > 15:
                self.fail("should have made it below that size by now")


    def wait_for_file_contents_to_contain(self, f, val):

        self.wait_for_file_to_appear(f)
        contents = self.file_contents(f)
        start = time.time()

        while val not in contents:
            if time.time() - start > 15:
                self.assertIn(val, contents, "file " + f + " should have contained '" + val + "' but was '" + contents + "' instead.")
            time.sleep(1)
            contents = self.file_contents(f)

    def file_contents(self, f):
        open1 = open(f, encoding="utf-8")
        contents = open1.read()
        open1.close()
        return contents

    def wait_for_file_to_disappear(self, f):
        start = time.time()
        while os.path.exists(f):
            if time.time() - start > 15:
                self.fail("file " + f + " didn't disappear in 45 secs")
            time.sleep(1)


    def upload_file(self, filename, remote_path):
        start = time.time()
        f = open(filename, 'rb')
        requests.put(remote_path, auth=(self.user, self.passwd), data=f, verify=False)
        f.close()


    @timedtest
    def test_a_single_file_syncs(self):

        p1, p2 = self.start_two_subsyncits()
        try:
            op1 = self.test_sync_dir_a + "output.txt"
            with open(op1, "w", encoding="utf-8") as text_file:
                text_file.write("Hello")
            op2 = self.test_sync_dir_b + "output.txt"
            self.wait_for_file_to_appear(op2)
            self.wait_for_file_contents_to_contain(op2, "Hello")
        finally:
            self.end(p1, self.test_sync_dir_a)
            self.end(p2, self.test_sync_dir_b)


    @timedtest
    def test_a_changed_file_syncs_back(self):

        p1, p2 = self.start_two_subsyncits()

        time.sleep(2)

        try:
            with open(self.test_sync_dir_a + "output.txt", "w", encoding="utf-8") as text_file:
                text_file.write("Hello") # f7ff9e8b7bb2e09b70935a5d785e0cc5d9d0abf0

            op2 = self.test_sync_dir_b + "output.txt"
            self.wait_for_file_to_appear(op2)

            time.sleep(1)
            with open(op2, "w", encoding="utf-8") as text_file:
                text_file.write("Hello to you too") # 3f19e1ea9c19f0c6967723b453a423340cbd6e36

            self.wait_for_file_contents_to_contain(self.test_sync_dir_a + "output.txt", "Hello to you too")

        finally:
            self.end(p1, self.test_sync_dir_a)
            self.end(p2, self.test_sync_dir_b)


    @timedtest
    def test_a_hidden_files_dont_get_put_into_svn(self):

        dir = self.test_sync_dir_a

        p1 = self.start_subsyncit(self.svn_url, self.test_sync_dir_a)

        try:
            with open(dir + ".foo", "w", encoding="utf-8") as text_file:
                text_file.write("Hello")

            with open(dir + ".DS_Store", "w", encoding="utf-8") as text_file:
                text_file.write("Hello")

            os.makedirs(dir + "two")

            with open(dir + "two/.foo", "w", encoding="utf-8") as text_file:
                text_file.write("Hello")

            with open(dir + "two/.DS_Store", "w", encoding="utf-8") as text_file:
                text_file.write("Hello")

            with open(dir + "control", "w", encoding="utf-8") as text_file:
                text_file.write("Hello")

            start = time.time()

            rc = 404
            while rc != 200 and time.time() - start < 60:
                rc = requests.get(self.svn_url + "control", auth=(self.user, self.passwd), verify=False).status_code
                time.sleep(.2)

            self.assertEqual(rc, 200, "URL " + self.svn_url + "control" + " should have been PUT, but it was not")
            self.assertNotEqual(requests.get(self.svn_url + ".foo", auth=(self.user, self.passwd), verify=False).status_code, 200)
            self.assertNotEqual(requests.get(self.svn_url + ".DS_Store", auth=(self.user, self.passwd), verify=False).status_code, 200)
            self.assertNotEqual(requests.get(self.svn_url + "two/.foo", auth=(self.user, self.passwd), verify=False).status_code, 200)
            self.assertNotEqual(requests.get(self.svn_url + "two/.DS_Store", auth=(self.user, self.passwd), verify=False).status_code, 200)

        finally:
            self.end(p1, self.test_sync_dir_a)

    @timedtest
    def test_files_with_special_characters_make_it_to_svn_and_back(self):

        dir = self.test_sync_dir_a

        p1 = self.start_subsyncit(self.svn_url, self.test_sync_dir_a)

        try:
            with open(dir + ".foo", "w", encoding="utf-8") as text_file:
                text_file.write("Hello")

            with open(dir + ".DS_Store", "w", encoding="utf-8") as text_file:
                text_file.write("Hello")

            os.makedirs(dir + "two")

            with open(dir + "two/.foo", "w", encoding="utf-8") as text_file:
                text_file.write("Hello")

            with open(dir + "two/.DS_Store", "w", encoding="utf-8") as text_file:
                text_file.write("Hello")

            with open(dir + "control", "w", encoding="utf-8") as text_file:
                text_file.write("Hello")

            start = time.time()

            rc = 404
            while rc != 200 and time.time() - start < 60:
                rc = requests.get(self.svn_url + "control", auth=(self.user, self.passwd), verify=False).status_code
                time.sleep(.2)

            self.assertEqual(rc, 200, "URL " + self.svn_url + "control" + " should have been PUT, but it was not")
            self.assertNotEqual(requests.get(self.svn_url + ".foo", auth=(self.user, self.passwd), verify=False).status_code, 200)
            self.assertNotEqual(requests.get(self.svn_url + ".DS_Store", auth=(self.user, self.passwd), verify=False).status_code, 200)
            self.assertNotEqual(requests.get(self.svn_url + "two/.foo", auth=(self.user, self.passwd), verify=False).status_code, 200)
            self.assertNotEqual(requests.get(self.svn_url + "two/.DS_Store", auth=(self.user, self.passwd), verify=False).status_code, 200)

        finally:
            self.end(p1, self.test_sync_dir_a)


    @timedtest
    def test_a_files_in_a_directory_gets_pushed_up(self):

        # It is alleged that some characters are not allowed in right-of-the-port-number paths.
        # Between them Apache2 and Subversion munge a few for display purposes. That's either on the way into Subversion,
        # or on the way back over HTTP into the file system. No matter - the most important representation of file name
        # is in the file system, and we only require consistent GET/PUT from/to that.

        dir = self.test_sync_dir_a

        os.mkdir(dir + "aaa")
        with open(dir + "aaa/test.txt", "w") as text_file:
            text_file.write("testttt")

        p1 = self.start_subsyncit(self.svn_url, dir)

        try:
            start = time.time()
            while True:
                if self.path_exists_on_svn_server("aaa") and self.path_exists_on_svn_server("aaa/test.txt"):
                    break
                if time.time() - start > 15:
                    self.fail("dir aaa and file aaa/test.txt should be up on " + self.svn_url + " within 90 seconds")
                time.sleep(1.5)

        finally:
            self.end(p1, self.test_sync_dir_a)

    def path_exists_on_svn_server(self, path):
        return 200 == requests.get(self.svn_url + path, auth=(self.user, self.passwd), verify=False).status_code

    @timedtest
    def test_a_deleted_file_syncs_down(self):

        self.expect201(requests.put(self.svn_url + "output.txt", auth=(self.user, self.passwd), data="Hello",
                                    verify=False))

        p1 = self.start_subsyncit(self.svn_url, self.test_sync_dir_a)
        try:
            self.wait_for_file_to_appear(self.test_sync_dir_a + "output.txt")

            requests.delete(self.svn_url + "output.txt", auth=(self.user, self.passwd), verify=False)
            self.wait_for_file_to_disappear(self.test_sync_dir_a + "output.txt")
        finally:
            self.end(p1, self.test_sync_dir_a)


    @timedtest
    def test_a_deleted_file_syncs_up(self):

        self.expect201(requests.put(self.svn_url + "output.txt", auth=(self.user, self.passwd), data="Hello",
                                    verify=False))

        p1 = self.start_subsyncit(self.svn_url, self.test_sync_dir_a)

        try:
            self.wait_for_file_to_appear(self.test_sync_dir_a + "output.txt")

        finally:
            self.end(p1, self.test_sync_dir_a)


    @timedtest
    def test_a_deleted_file_syncs_back(self):

        p1, p2 = self.start_two_subsyncits()
        try:
            with open(self.test_sync_dir_a + "output.txt", "w", encoding="utf-8") as text_file:
                text_file.write("Hello")
            op2 = self.test_sync_dir_b + "output.txt"
            self.wait_for_file_to_appear(op2)
            time.sleep(0.5)
            os.remove(op2)
            self.wait_for_file_to_disappear(self.test_sync_dir_a + "output.txt")
            print(self.test_sync_dir_a + "output.txt has disappeared as expected")
        finally:

            self.end(p1, self.test_sync_dir_a)
            self.end(p2, self.test_sync_dir_b)

    @timedtest
    def test_a_file_changed_while_sync_agent_offline_still_sync_syncs_later(self):

        self.expect201(requests.put(self.svn_url + "output.txt", auth=(self.user, self.passwd), data="As First PUT Up To Svn", verify=False))

        p1, p2 = self.start_two_subsyncits()

        try:
            file_in_subsyncit_one = self.test_sync_dir_a + "output.txt"
            file_in_subsyncit_two = self.test_sync_dir_b + "output.txt"
            self.wait_for_file_to_appear(file_in_subsyncit_one)
            self.wait_for_file_to_appear(file_in_subsyncit_two)
            self.signal_stop_of_subsyncIt(self.test_sync_dir_b)
            p2.wait()
            with open(file_in_subsyncit_two, "w") as text_file:
                text_file.write("Overrite locally in client 2")
            p2 = self.start_subsyncit(self.svn_url, self.test_sync_dir_b)
            # p2 = self.start_subsyncit(self.svn_repo + dir, self.testSyncDir2)
            self.wait_for_file_contents_to_contain(file_in_subsyncit_one, "Overrite locally in client 2")
        finally:
            self.end(p1, self.test_sync_dir_a)
            self.end(p2, self.test_sync_dir_b)


    @timedtest
    def test_a_file_in_dir_added_to_repo_while_sync_agent_offline_still_sync_syncs_later(self):

        self.expect201(requests.request('MKCOL',
                                        self.svn_url + "fred/",
                                        auth=(self.user, self.passwd),
                                        verify=False))
        self.expect201(requests.put(self.svn_url + "fred/output.txt", auth=(self.user, self.passwd), data="Hello", verify=False))

        p1 = self.start_subsyncit(self.svn_url, self.test_sync_dir_a)

        try:
            op1 = self.test_sync_dir_a + "fred/output.txt"
            self.wait_for_file_to_appear(op1)
        finally:
            self.end(p1, self.test_sync_dir_a)


    @timedtest
    def test_that_excluded_patterns_work(self):


        self.expect201(requests.put(self.svn_url + ".subsyncit-excluded-filename-patterns", auth=(self.user, self.passwd), data=".*\.foo\n.*\.txt\n.*\.bar", verify=False))

        self.expect201(requests.put(self.svn_url + "output.txt", auth=(self.user, self.passwd), data="Hello", verify=False))

        self.expect201(requests.put(self.svn_url + "output.zzz", auth=(self.user, self.passwd), data="Hello", verify=False))

        p1 = self.start_subsyncit(self.svn_url, self.test_sync_dir_a)

        try:

            op1 = self.test_sync_dir_a + "output.zzz"
            print ("op1=" + op1)
            self.wait_for_file_to_appear(op1)

            op1 = self.test_sync_dir_a + "output.txt"
            time.sleep(2) # the two files should arrive pretty much at the same time, but why not wait 2 secs, heh?
            if os.path.exists(op1):
                self.fail("File " + op1 + " should not have appeared but did.")
        finally:
            self.end(p1, self.test_sync_dir_a)


    @timedtest
    def test_a_file_in_dir_with_spaces_in_names_are_added_to_repo_while_sync_agent_offline_still_sync_syncs_later(self):

        self.expect201(requests.request('MKCOL',
                                        self.svn_url + "f r e d/",
                                        auth=(self.user, self.passwd),
                                        verify=False))
        self.expect201(requests.put(self.svn_url + "f r e d/o u t & p u t.txt", auth=(self.user, self.passwd), data="Hello", verify=False))

        p1 = self.start_subsyncit(self.svn_url, self.test_sync_dir_a)

        try:
            op1 = self.test_sync_dir_a + "f r e d/o u t & p u t.txt"
            self.wait_for_file_to_appear(op1)
        finally:
            self.end(p1, self.test_sync_dir_a)

        # with open(self.testSyncDir1 + "paul was here.txt", "w") as text_file:
        #     text_file.write("Hello to you too")


    @timedtest
    def test_a_file_changed_while_sync_agent_offline_does_not_sync_sync_later_if_it_changed_on_the_server_too(self):

        self.expect201(requests.put(self.svn_url + "output.txt", auth=(self.user, self.passwd), data="Hello", verify=False))

        p1 = self.start_subsyncit(self.svn_url, self.test_sync_dir_a)
        try:
            self.wait_for_file_contents_to_contain(self.test_sync_dir_a + "output.txt", "Hello")
            self.signal_stop_of_subsyncIt(self.test_sync_dir_a)
            p1.wait()

            self.expect204(requests.put(self.svn_url + "output.txt", auth=(self.user, self.passwd), data="Hello changed on server", verify=False))

            with open(self.test_sync_dir_a + "output.txt", "w") as text_file:
                text_file.write("Hello changed locally too")

            os.mkdir(self.test_sync_dir_a + "aaa")
            with open(self.test_sync_dir_a + "aaa/output.txt", "w") as text_file:
                text_file.write("Hello changed locally too")

            p1 = self.start_subsyncit(self.svn_url, self.test_sync_dir_a)

            time.sleep(2)

            self.wait_for_file_contents_to_contain(self.test_sync_dir_a + "output.txt", "Hello changed on server")
            clash_file = glob2.glob(self.test_sync_dir_a + "*.clash_*")[0]
            self.wait_for_file_contents_to_contain(clash_file, "Hello changed locally too")
        finally:
            self.end(p1, self.test_sync_dir_a)

    @timedtest
    def test_cant_start_on_a_non_svn_dav_server(self):

        p1 = self.start_subsyncit("https://example.com/", self.test_sync_dir_a, passwd="dontLeakRealPasswordToExampleDotCom")
        try:
            self.wait_for_file_contents_to_contain(self.test_sync_dir_a + ".subsyncit.err", "Cannot attach to remote")
        finally:
            self.end(p1, self.test_sync_dir_a)


    @timedtest
    def test_cant_start_on_a_svn_dav_server_with_incorrect_password(self):

        p1 = self.start_subsyncit(self.svn_url, self.test_sync_dir_a, passwd="sdfsdfget3qgwegsdgsdgsf")
        try:
            self.wait_for_file_contents_to_contain(self.test_sync_dir_a + ".subsyncit.err", "Cannot attach to remote") # and more
        finally:
            self.end(p1, self.test_sync_dir_a)


    @timedtest
    def test_cant_start_on_a_down_server(self):

        p1 = self.start_subsyncit("https://localhost:34456/", self.test_sync_dir_a)
        try:
            time.sleep(2)
            self.wait_for_file_contents_to_contain(self.test_sync_dir_a + ".subsyncit.err", " Failed to establish a new connection")
        finally:
            self.end(p1, self.test_sync_dir_a)


    @timedtest
    def test_an_excluded_filename_patterns_is_not_pushed_up(self):

        self.expect201(requests.put(self.svn_url + ".subsyncit-excluded-filename-patterns", auth=(self.user, self.passwd), data=".*\.txt\n\~\$.*\n", verify=False))

        op1 = self.test_sync_dir_a + "output.txt"
        with open(op1, "w") as text_file:
            text_file.write("I should not be PUT up to the server")

        op1 = self.test_sync_dir_a + "~$output"
        with open(op1, "w") as text_file:
            text_file.write("I also should not be PUT up to the server")

        op1 = self.test_sync_dir_a + "output.zzz"
        with open(op1, "w") as text_file:
            text_file.write("Only I can go to the server")

        p1 = self.start_subsyncit(self.svn_url, self.test_sync_dir_a)

        try:

            self.wait_for_URL_to_appear(self.svn_url + "output.zzz")

            time.sleep(2) # the all files should arrive pretty much at the same time, but why not wait 5 secs, heh?

            self.assertEqual(
                requests.get(self.svn_url + "output.txt",
                             auth=(self.user, self.passwd), verify=False)
                    .status_code, 404, "URL " + self.svn_url + "output.txt" + " should NOT have appeared, but it did")

            self.assertEqual(
                requests.get(self.svn_url + "~$output",
                             auth=(self.user, self.passwd), verify=False)
                    .status_code, 404, "URL " + self.svn_url + "~$output" + " should NOT have appeared, but it did")


        finally:
            self.end(p1, self.test_sync_dir_a)


    @timedtest
    def test_a_partially_downloaded_big_file_recovers(self):

        filename = str(sh.pwd()).strip('\n') + "/testBigRandomFile"
        start = time.time()
        self.make_a_big_random_file(filename, self.size)

        sz = os.stat(filename).st_size
        self.upload_file(filename, self.svn_url + "testBigRandomFile")

        # self.list_files(self.testSyncDir1)

        start = time.time()
        p1 = self.start_subsyncit(self.svn_url, self.test_sync_dir_a)
        try:
            print("Started Subsyncit, and waiting for " + str(self.size) + "MB random file to be downloaded from Svn and be at least " + str(sz) + " MB ... ")
            self.wait_for_file_contents_to_be_sized_above_or_eq_too(self.test_sync_dir_a + "testBigRandomFile", sz)
            print(" ... took secs: " + str(round(time.time() - start, 1)))

            # self.list_files(self.testSyncDir1)

            self.signal_stop_of_subsyncIt(self.test_sync_dir_a)
            p1.wait()

            # self.list_files(self.testSyncDir1)

            self.make_a_big_random_file(filename, self.size)

            # self.list_files(self.testSyncDir1)

            self.upload_file(filename, self.svn_url + "testBigRandomFile")

            # self.list_files(self.testSyncDir1)

            start = time.time()

            print("start Subsyncit again")
            p1 = self.start_subsyncit(self.svn_url, self.test_sync_dir_a)
            self.wait_for_file_contents_to_be_sized_below(self.test_sync_dir_a + "testBigRandomFile", (sz * 99 / 100))
            # self.list_files(self.testSyncDir1)
            self.wait_for_file_contents_to_be_sized_above_or_eq_too(self.test_sync_dir_a + "testBigRandomFile", (sz / 10))
            # self.list_files(self.testSyncDir1)
            p1.kill()
            print("Killed after secs: " + str(round(time.time() - start, 1)))
            # self.list_files(self.testSyncDir1)

            aborted_get_size = os.stat(self.test_sync_dir_a + "testBigRandomFile").st_size

            print("^ YES, that 30 lines of a process being killed and the resulting stack trace is intentional at this stage in the integration test suite")

            self.assertNotEquals(aborted_get_size, sz, "Aborted file size: " + str(aborted_get_size) + " should have been less that the ultimate size of the test file: " + str(sz))

            #self.list_files(self.testSyncDir1)

            p1 = self.start_subsyncit(self.svn_url, self.test_sync_dir_a)
            self.wait_for_file_contents_to_be_sized_above_or_eq_too(self.test_sync_dir_a + "testBigRandomFile", sz)
        finally:
            self.end(p1, self.test_sync_dir_a)


        # self.list_files(self.testSyncDir1)

        clash_file = glob2.glob(self.test_sync_dir_a + "*.clash_*")[0]
        self.assertEqual(os.stat(clash_file).st_size, aborted_get_size)

    def make_a_big_random_file(self, filename, size):
        start = time.time()
        print("Making " + size + " MB random file ... ")
        sh.bash("tests/make_a_so_big_file.sh", filename, size)
        print(" ... secs: " + str(round(time.time() - start, 1)))

    def list_files(self, root):
        glob = glob2.glob(root + "**")
        print("List of files in " + root + "folder:")
        if len(glob) == 0:
            print("  no files")
        for s in glob:
            print("  " + (str(s)) + " " + str(os.stat(str(s)).st_size))

    def expect201(self, commandOutput):
        self.assertEqual("<Response [201]>", str(commandOutput))

    def expect204(self, commandOutput):
        self.assertEqual("<Response [204]>", str(commandOutput))


if __name__ == '__main__':
    import sys

    if (len(sys.argv)) >= 2:
        test_name = sys.argv[1].lower()
    else:
        test_name = "all"

    if (len(sys.argv)) >= 3:
        size_of_big_test_file = sys.argv[2]
    else:
        size_of_big_test_file = "512"

    test_loader = unittest.TestLoader()
    test_names = test_loader.getTestCaseNames(IntegrationTestsOfSyncOperations)
    suite = unittest.TestSuite()
    if test_name == "all":
        for tname in test_names:
            suite.addTest(IntegrationTestsOfSyncOperations(tname, size_of_big_test_file))
    else:
        suite.addTest(IntegrationTestsOfSyncOperations(test_name, size_of_big_test_file))

    result = unittest.TextTestRunner().run(suite)
    sys.exit(not result.wasSuccessful())
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

#
#  TODO - if not a subversion site, should abort.
#

import argparse
import copy
import json
import os
import copy
import time
import unittest
import shutil
import sys
import glob2
import requests
import sh
from decorator import decorator

import docker
from docker.errors import NotFound
from tinydb import Query, TinyDB


class IntegrationTestsOfSyncOperations(unittest.TestCase):

    test_num = 0
    test_sync_dir_a = ""
    test_sync_dir_b = ""
    process_a = None
    process_b = None
    container = None
    kill_container_at_end = False

    def __init__(self, testname, size, kill_container_at_end):
        super(IntegrationTestsOfSyncOperations, self).__init__(testname)
        self.size = size
        IntegrationTestsOfSyncOperations.kill_container_at_end = kill_container_at_end
        self.output = ""
        self.user = "davsvn"
        self.passwd = "davsvn"
        self.svn_repo = "http://127.0.0.1:8099/svn/testrepo/"
        self.line = ""

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
        if cls.kill_container_at_end:
            cls.kill_docker_container(False)


    def setUp(self):

        if os.name != 'nt':
            self.home_dir = os.path.expanduser('~' + (os.getenv("SUDO_USER") or os.getenv("USER")))
        else:
            self.home_dir = os.path.expanduser(str(os.getenv('USERPROFILE')))

        IntegrationTestsOfSyncOperations.test_num += 1
        testNum = str(IntegrationTestsOfSyncOperations.test_num)

        self.rel_dir_a = "integrationTests/test_" + testNum + "a/"
        self.test_sync_dir_a = str(sh.pwd()).strip('\n') + self.rel_dir_a
        self.rel_dir_b = "integrationTests/test_" + testNum + "b/"
        self.test_sync_dir_b = str(sh.pwd()).strip('\n') + self.rel_dir_b

        self.db_dir_a = self.home_dir + os.sep + ".subsyncit" + os.sep + self.test_sync_dir_a.replace("/", "%47").replace(":", "%58").replace("\\", "%92") + "/"
        self.db_dir_b = self.home_dir + os.sep + ".subsyncit" + os.sep + self.test_sync_dir_b.replace("/", "%47").replace(":", "%58").replace("\\", "%92") + "/"

        self.reset_test_dir(self.test_sync_dir_a)
        self.reset_test_dir(self.db_dir_a)
        self.reset_test_dir(self.test_sync_dir_b)
        self.reset_test_dir(self.db_dir_b)

        self.svn_url = self.svn_repo + "integrationTests/test_" + testNum + "/"
        self.expect201(requests.request('MKCOL', self.svn_url, auth=(self.user, self.passwd), verify=False))



    def teardown(self):
        self.end(self.process_a, self.test_sync_dir_a)
        self.end(self.process_b, self.test_sync_dir_b)


    @timedtest
    def test_a_single_file_syncs(self):

        test_start = time.time()

        process_a, process_b = self.start_two_subsyncits()
        try:
            op_process_a = self.test_sync_dir_a + "output.txt"
            with open(op_process_a, "w", encoding="utf-8") as text_file:
                text_file.write("Hello")
            op_process_b = self.test_sync_dir_b + "output.txt"
            self.wait_for_file_to_appear(op_process_b)
            self.wait_for_file_contents_to_contain(op_process_b, "Hello")
        finally:
            self.end(process_a, self.test_sync_dir_a)
            self.end(process_b, self.test_sync_dir_b)

        rows = self.get_db_rows(test_start, self.test_sync_dir_a)
        self.should_start_with(rows, 0, "01, output.txt, f7ff9e8b7bb2e09b70935a5d785e0cc5d9d0abf0, f7ff9e8b7bb2e09b70935a5d785e0cc5d9d0abf0,")


    @timedtest
    def test_a_changed_file_syncs_back(self):

        process_a, process_b = self.start_two_subsyncits()

        test_start = time.time()

        time.sleep(2)

        try:
            with open(self.test_sync_dir_a + "output.txt", "w", encoding="utf-8") as text_file:
                text_file.write("Hello") # f7ff9e8b7bb2e09b70935a5d785e0cc5d9d0abf0

            op_process_b = self.test_sync_dir_b + "output.txt"
            self.wait_for_file_to_appear(op_process_b)

            time.sleep(1)
            with open(op_process_b, "w", encoding="utf-8") as text_file:
                text_file.write("Hello to you too") # 3f19e1ea9c19f0c6967723b453a423340cbd6e36

            self.wait_for_file_contents_to_contain(self.test_sync_dir_a + "output.txt", "Hello to you too")

        finally:
            self.end(process_a, self.test_sync_dir_a)
            self.end(process_b, self.test_sync_dir_b)


        rows = self.get_db_rows(test_start, self.test_sync_dir_a)
        self.should_start_with(rows, 0, "01, output.txt, 3f19e1ea9c19f0c6967723b453a423340cbd6e36, 3f19e1ea9c19f0c6967723b453a423340cbd6e36,")



    @timedtest
    def test_files_with_special_characters_make_it_to_svn_and_back(self):

        # It is alleged that some characters are not allowed in right-of-the-port-number paths.
        # Between them Apache2 and Subversion munge a few for display purposes. That's either on the way into Subversion,
        # or on the way back over HTTP into the file system. No matter - the most important representation of file name
        # is in the file system, and we only require consistent GET/PUT from/to that.

#        test_start = time.time()

        process_a = self.start_subsyncit(self.svn_url, self.test_sync_dir_a)

        try:
            files = ["a&a", "b{b", "c?c", "d$d", "e;e", "f=f", "g+g", "h,h",
                     "i(i", "j)j", "k[k", "l]l", "m:m", "n\'n", "o\"o", "p`p", "q*q", "r~r"]
            for f in files:
                with open(self.test_sync_dir_a + f, "w", encoding="utf-8") as text_file:
                    text_file.write("Hello")

            self.expect201(
                requests.put(self.svn_url + "CONTROL",
                             auth=(self.user, self.passwd), data="Hello",
                             verify=False))

            start = time.time()
            elapsed = 0

            files_not_found_in_subversion = copy.deepcopy(files)

            while len(files) > 1 and elapsed < 90:
                files2 = copy.deepcopy(files_not_found_in_subversion)
                for f in files2:
                    if requests.get(self.svn_url + f, auth=(self.user, self.passwd), verify=False).status_code == 200:
                        files_not_found_in_subversion.remove(f)
                elapsed = time.time() - start

            self.assertEquals(len(files_not_found_in_subversion), 1, str(files_not_found_in_subversion))

            # `?` isn't handled seamlessly by the requests library
            if requests.get(self.svn_url + "c?c".replace("?", "%3f"),
                            auth=(self.user, self.passwd),
                            verify=False).status_code == 200:
                files_not_found_in_subversion.remove("c?c")

            self.assertEquals(len(files_not_found_in_subversion), 0, "Some not found in Subversion: " + str(files_not_found_in_subversion))

            # As Subsncit pulled down files it didn't already have, the only one to add was the `CONTROL` file.
            self.assertEquals(str(sorted(
                os.listdir(self.test_sync_dir_a))),
                "['CONTROL', 'a&a', 'b{b', 'c?c', 'd$d', 'e;e', 'f=f', 'g+g', 'h,h', 'i(i', 'j)j', 'k[k', 'l]l', 'm:m', \"n\'n\", 'o\"o', 'p`p', 'q*q', 'r~r']")


        finally:
            self.end(process_a, self.test_sync_dir_a)

        # files_table = self.get_db_rows(test_start, self.test_sync_dir_a)
        #
        # print(str(files_table.all()))



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

        process_a = self.start_subsyncit(self.svn_url, dir)

        try:
            start = time.time()
            while True:
                if self.path_exists_on_svn_server("aaa") and self.path_exists_on_svn_server("aaa/test.txt"):
                    break
                if time.time() - start > 15:
                    self.fail("dir aaa and file aaa/test.txt should be up on " + self.svn_url + " within 90 seconds")
                time.sleep(1.5)

        finally:
            self.end(process_a, self.test_sync_dir_a)

    def path_exists_on_svn_server(self, path):
        return 200 == requests.get(self.svn_url + path, auth=(self.user, self.passwd), verify=False).status_code

    @timedtest
    def test_a_deleted_file_syncs_down(self):

        self.expect201(requests.put(self.svn_url + "output.txt", auth=(self.user, self.passwd), data="Hello",
                                    verify=False))

        process_a = self.start_subsyncit(self.svn_url, self.test_sync_dir_a)
        try:
            self.wait_for_file_to_appear(self.test_sync_dir_a + "output.txt")

            requests.delete(self.svn_url + "output.txt", auth=(self.user, self.passwd), verify=False)
            self.wait_for_file_to_disappear(self.test_sync_dir_a + "output.txt")
        finally:
            self.end(process_a, self.test_sync_dir_a)


    @timedtest
    def test_a_deleted_file_syncs_up(self):

        self.expect201(requests.put(self.svn_url + "output.txt", auth=(self.user, self.passwd), data="Hello",
                                    verify=False))

        process_a = self.start_subsyncit(self.svn_url, self.test_sync_dir_a)

        try:
            self.wait_for_file_to_appear(self.test_sync_dir_a + "output.txt")

        finally:
            self.end(process_a, self.test_sync_dir_a)


    @timedtest
    def test_a_deleted_file_syncs_back(self):

        process_a, process_b = self.start_two_subsyncits()
        try:
            with open(self.test_sync_dir_a + "output.txt", "w", encoding="utf-8") as text_file:
                text_file.write("Hello")
            op_process_b = self.test_sync_dir_b + "output.txt"
            self.wait_for_file_to_appear(op_process_b)
            time.sleep(0.5)
            os.remove(op_process_b)
            self.wait_for_file_to_disappear(self.test_sync_dir_a + "output.txt")
            print(self.test_sync_dir_a + "output.txt has disappeared as expected")
        finally:

            self.end(process_a, self.test_sync_dir_a)
            self.end(process_b, self.test_sync_dir_b)

    @timedtest
    def test_a_file_changed_while_sync_agent_offline_still_sync_syncs_later(self):

        self.expect201(requests.put(self.svn_url + "output.txt", auth=(self.user, self.passwd), data="As First PUT Up To Svn", verify=False))

        process_a, process_b = self.start_two_subsyncits()

        try:
            file_in_subsyncit_one = self.test_sync_dir_a + "output.txt"
            file_in_subsyncit_two = self.test_sync_dir_b + "output.txt"
            self.wait_for_file_to_appear(file_in_subsyncit_one)
            self.wait_for_file_to_appear(file_in_subsyncit_two)
            self.signal_stop_of_subsyncit(self.test_sync_dir_b)
            process_b.wait()
            with open(file_in_subsyncit_two, "w") as text_file:
                text_file.write("Overrite locally in client 2")
            process_b = self.start_subsyncit(self.svn_url, self.test_sync_dir_b)
            # process_b = self.start_subsyncit(self.svn_repo + dir, self.testSyncDir2)
            self.wait_for_file_contents_to_contain(file_in_subsyncit_one, "Overrite locally in client 2")
        finally:
            self.end(process_a, self.test_sync_dir_a)
            self.end(process_b, self.test_sync_dir_b)


    @timedtest
    def test_a_file_in_dir_added_to_repo_while_sync_agent_offline_still_sync_syncs_later(self):

        self.expect201(requests.request('MKCOL',
                                        self.svn_url + "fred/",
                                        auth=(self.user, self.passwd),
                                        verify=False))
        self.expect201(requests.put(self.svn_url + "fred/output.txt", auth=(self.user, self.passwd), data="Hello", verify=False))

        process_a = self.start_subsyncit(self.svn_url, self.test_sync_dir_a)

        try:
            op_process_a = self.test_sync_dir_a + "fred/output.txt"
            self.wait_for_file_to_appear(op_process_a)
        finally:
            self.end(process_a, self.test_sync_dir_a)


    @timedtest
    def test_that_excluded_patterns_work(self):


        self.expect201(requests.put(self.svn_url + ".subsyncit-excluded-filename-patterns", auth=(self.user, self.passwd), data=".*\.foo\n.*\.txt\n.*\.bar", verify=False))

        self.expect201(requests.put(self.svn_url + "output.txt", auth=(self.user, self.passwd), data="Hello", verify=False))

        self.expect201(requests.put(self.svn_url + "output.zzz", auth=(self.user, self.passwd), data="Hello", verify=False))

        process_a = self.start_subsyncit(self.svn_url, self.test_sync_dir_a)

        try:

            op_process_a = self.test_sync_dir_a + "output.zzz"
            self.wait_for_file_to_appear(op_process_a)

            op_process_a = self.test_sync_dir_a + "output.txt"
            time.sleep(2) # the two files should arrive pretty much at the same time, but why not wait 2 secs, heh?
            if os.path.exists(op_process_a):
                self.fail("File " + op_process_a + " should not have appeared but did.")
        finally:
            self.end(process_a, self.test_sync_dir_a)


    @timedtest
    def test_a_file_in_dir_with_spaces_in_names_are_added_to_repo_while_sync_agent_offline_still_sync_syncs_later(self):

        self.expect201(requests.request('MKCOL',
                                        self.svn_url + "f r e d/",
                                        auth=(self.user, self.passwd),
                                        verify=False))
        self.expect201(requests.put(self.svn_url + "f r e d/o u t & p u t.txt", auth=(self.user, self.passwd), data="Hello", verify=False))

        process_a = self.start_subsyncit(self.svn_url, self.test_sync_dir_a)

        try:
            op_process_a = self.test_sync_dir_a + "f r e d/o u t & p u t.txt"
            self.wait_for_file_to_appear(op_process_a)
        finally:
            self.end(process_a, self.test_sync_dir_a)

        # with open(self.testSyncDir1 + "paul was here.txt", "w") as text_file:
        #     text_file.write("Hello to you too")


    @timedtest
    def test_a_file_changed_while_sync_agent_offline_does_not_sync_sync_later_if_it_changed_on_the_server_too(self):

        self.expect201(requests.put(self.svn_url + "output.txt", auth=(self.user, self.passwd), data="Hello", verify=False))

        process_a = self.start_subsyncit(self.svn_url, self.test_sync_dir_a)
        try:
            self.wait_for_file_contents_to_contain(self.test_sync_dir_a + "output.txt", "Hello")
            self.signal_stop_of_subsyncit(self.test_sync_dir_a)
            process_a.wait()

            self.expect204(requests.put(self.svn_url + "output.txt", auth=(self.user, self.passwd), data="Hello changed on server", verify=False))

            with open(self.test_sync_dir_a + "output.txt", "w") as text_file:
                text_file.write("Hello changed locally too")

            os.mkdir(self.test_sync_dir_a + "aaa")
            with open(self.test_sync_dir_a + "aaa/output.txt", "w") as text_file:
                text_file.write("Hello changed locally too")

            process_a = self.start_subsyncit(self.svn_url, self.test_sync_dir_a)

            time.sleep(2)

            self.wait_for_file_contents_to_contain(self.test_sync_dir_a + "output.txt", "Hello changed on server")
            clash_file = glob2.glob(self.test_sync_dir_a + "*.clash_*")[0]
            self.wait_for_file_contents_to_contain(clash_file, "Hello changed locally too")
        finally:
            self.end(process_a, self.test_sync_dir_a)

    @timedtest
    def test_cant_start_on_a_non_svn_dav_server(self):

        process_a = self.start_subsyncit_without_user_and_password("http://example.com/", self.test_sync_dir_a)
        try:
            self.wait_for_file_contents_to_contain(self.db_dir_a + "subsyncit.err", "http://example.com/ is not a website that maps subversion to that URL")
        finally:
            self.end(process_a, self.test_sync_dir_a)


    @timedtest
    def test_cant_start_on_a_svn_dav_server_with_incorrect_password(self):

        process_a = self.start_subsyncit(self.svn_url, self.test_sync_dir_a, passwd="sdfsdfget3qgwegsdgsdgsf")
        try:
            self.wait_for_file_contents_to_contain(self.db_dir_a + "subsyncit.err", "http://127.0.0.1:8099/svn/testrepo/integrationTests/") # start
            self.wait_for_file_contents_to_contain(self.db_dir_a + "subsyncit.err", " is saying that the user is not authorized") # end
        finally:
            self.end(process_a, self.test_sync_dir_a)


    @timedtest
    def test_cant_start_on_a_server_that_is_down(self):

        process_a = self.start_subsyncit("https://localhost:34456/", self.test_sync_dir_a)
        try:
            time.sleep(2)
            self.wait_for_file_contents_to_contain(self.db_dir_a + "subsyncit.err", " Failed to establish a new connection")
        finally:
            self.end(process_a, self.test_sync_dir_a)

        process_a.wait()

        status = json.loads(self.file_contents(self.db_dir_a + "status.json"))

        self.assertEquals(status['online'], False)


    @timedtest
    def test_an_excluded_filename_patterns_is_not_pushed_up(self):

        self.expect201(requests.put(self.svn_url + ".subsyncit-excluded-filename-patterns", auth=(self.user, self.passwd), data=".*\.txt\n\~\$.*\n", verify=False))

        op_process_a = self.test_sync_dir_a + "output.txt"
        with open(op_process_a, "w") as text_file:
            text_file.write("I should not be PUT up to the server")

        op_process_a = self.test_sync_dir_a + "~$output"
        with open(op_process_a, "w") as text_file:
            text_file.write("I also should not be PUT up to the server")

        op_process_a = self.test_sync_dir_a + "output.zzz"
        with open(op_process_a, "w") as text_file:
            text_file.write("Only I can go to the server")

        process_a = self.start_subsyncit(self.svn_url, self.test_sync_dir_a)

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
            self.end(process_a, self.test_sync_dir_a)


    @timedtest
    def test_a_partially_downloaded_big_file_recovers(self):

        filename = str(sh.pwd()).strip('\n') + "/testBigRandomFile"
        start = time.time()
        self.make_a_big_random_file(filename, self.size)

        sz = os.stat(filename).st_size
        self.upload_file(filename, self.svn_url + "testBigRandomFile")

        # self.list_files(self.testSyncDir1)

        start = time.time()
        process_a = self.start_subsyncit(self.svn_url, self.test_sync_dir_a)
        try:
            print("Started Subsyncit, and waiting for " + str(self.size) + "MB random file to be downloaded from Svn and be at least " + str(sz) + " MB ... ")
            self.wait_for_file_contents_to_be_sized_above_or_eq_too(self.test_sync_dir_a + "testBigRandomFile", sz)
            print(" ... took secs: " + str(round(time.time() - start, 1)))

            # self.list_files(self.testSyncDir1)

            self.signal_stop_of_subsyncit(self.test_sync_dir_a)
            process_a.wait()

            # self.list_files(self.testSyncDir1)

            self.make_a_big_random_file(filename, self.size)

            # self.list_files(self.testSyncDir1)

            self.upload_file(filename, self.svn_url + "testBigRandomFile")

            # self.list_files(self.testSyncDir1)

            start = time.time()

            print("start Subsyncit again")
            process_a = self.start_subsyncit(self.svn_url, self.test_sync_dir_a)
            self.wait_for_file_contents_to_be_sized_below(self.test_sync_dir_a + "testBigRandomFile", (sz * 99 / 100))
            # self.list_files(self.testSyncDir1)
            self.wait_for_file_contents_to_be_sized_above_or_eq_too(self.test_sync_dir_a + "testBigRandomFile", (sz / 10))
            # self.list_files(self.testSyncDir1)
            process_a.kill()
            print("Killed after secs: " + str(round(time.time() - start, 1)))
            # self.list_files(self.testSyncDir1)

            aborted_get_size = os.stat(self.test_sync_dir_a + "testBigRandomFile").st_size

            print("^ YES, that 30 lines of a process being killed and the resulting stack trace is intentional at this stage in the integration test suite")

            self.assertNotEquals(aborted_get_size, sz, "Aborted file size: " + str(aborted_get_size) + " should have been less that the ultimate size of the test file: " + str(sz))

            #self.list_files(self.testSyncDir1)

            process_a = self.start_subsyncit(self.svn_url, self.test_sync_dir_a)
            self.wait_for_file_contents_to_be_sized_above_or_eq_too(self.test_sync_dir_a + "testBigRandomFile", sz)
        finally:
            self.end(process_a, self.test_sync_dir_a)


        # self.list_files(self.testSyncDir1)

        clash_file = glob2.glob(self.test_sync_dir_a + "*.clash_*")[0]
        self.assertEqual(os.stat(clash_file).st_size, aborted_get_size)


    @timedtest
    def test_that_we_understand_how_revisions_can_be_a_surrogate_for_a_proper_merkle_tree(self):

        test_start = time.time()

        # starting revision varies depending on how many tests are being run.
        sr = self.repo_rev_for("", 2)

        self.expect201(requests.request('MKCOL', self.svn_url + "fred/", auth=(self.user, self.passwd), verify=False))
        self.expect201(requests.request('MKCOL', self.svn_url + "wilma/", auth=(self.user, self.passwd), verify=False))
        self.expect201(requests.request('MKCOL', self.svn_url + "barney/", auth=(self.user, self.passwd), verify=False))

        self.assertEquals(self.no_leading_spaces(
            """<root> : 5, 5
               fred/ : 5, 3
               wilma/ : 5, 4
               barney/ : 5, 5
               """),
            self.get_rev_summary_for_root_barney_wilma_fred_and_bambam_if_there(sr))

        self.expect201(requests.request('MKCOL', self.svn_url + "wilma/bambam", auth=(self.user, self.passwd), verify=False))

        # Only 'wilma' gets a actual directory version (to #4) bump, but the repo is bumped to latest everywhere.
        self.assertEquals(self.no_leading_spaces(
            """<root> : 6, 6
               fred/ : 6, 3
               wilma/ : 6, 6
               wilma/bambam : ?, 6
               barney/ : 6, 5
               """),
            self.get_rev_summary_for_root_barney_wilma_fred_and_bambam_if_there(sr))


    @timedtest
    def test_that_subsynct_can_collect_the_merkel_esque_revisions_from_subversion(self):

        test_start = time.time()

        sr = self.repo_rev_for("", 2)

        process_a = self.start_subsyncit(self.svn_url, self.test_sync_dir_a)

        self.expect201(requests.request('MKCOL', self.svn_url + "fred/", auth=(self.user, self.passwd), verify=False))
        self.expect201(requests.request('MKCOL', self.svn_url + "wilma/", auth=(self.user, self.passwd), verify=False))
        self.expect201(requests.request('MKCOL', self.svn_url + "barney/", auth=(self.user, self.passwd), verify=False))
        self.expect201(requests.request('PUT', self.svn_url + "wilma/bambam", data="hi", auth=(self.user, self.passwd), verify=False))

        try:
            # with open(self.test_sync_dir_a + "x", "w") as text_file:
            #     text_file.write("nudge")
            self.wait_for_file_to_appear(self.test_sync_dir_a + "fred")
            self.wait_for_file_to_appear(self.test_sync_dir_a + "wilma/bambam")
            self.wait_for_file_to_appear(self.test_sync_dir_a + "barney")

        finally:
            self.end(process_a, self.test_sync_dir_a)

        process_a.wait()


        # Only 'wilma' gets a actual directory version (to #4) bump, but the repo is bumped to latest everywhere.
        self.assertEquals(self.no_leading_spaces(
            """<root> : 6, 6
               fred/ : 6, 3
               wilma/ : 6, 6
               wilma/bambam : ?, 6
               barney/ : 6, 5
               """),
            self.get_rev_summary_for_root_barney_wilma_fred_and_bambam_if_there(sr))


        rows = self.get_db_rows(test_start, self.test_sync_dir_a)
        print(str(rows))
        # ['01, wilma/bambam, c22b5f9178342609428d6f51b2c5af4c0bde6a42, c22b5f9178342609428d6f51b2c5af4c0bde6a42, 1688', '
        # 07, barney, None, None, -1508766913312', '
        # 07, fred, None, None, -1508766913312', '
        # 07, wilma, None, None,
        self.should_start_with(rows, 0, "01, wilma/bambam, c22b5f9178342609428d6f51b2c5af4c0bde6a42, c22b5f9178342609428d6f51b2c5af4c0bde6a42,")
        self.should_start_with(rows, 1, "04, fred, None, None,")
        self.should_start_with(rows, 2, "06, barney, None, None,")
        self.should_start_with(rows, 3, "07, wilma, None, None,")

    # ======================================================================================================

    def get_rev_summary_for_root_barney_wilma_fred_and_bambam_if_there(self, sr):

        bambam = ""
        try:
            bambam = "wilma/bambam : " + str(self.repo_rev_for("wilma/bambam", sr)) + ", " + str(self.directory_revision_for("wilma/bambam") - sr) + "\n"
        except AssertionError:
            pass

        return "<root> : " + str(self.repo_rev_for("", sr)) + ", " + str(self.directory_revision_for("") - sr) + "\n" \
               + "fred/ : " + str(self.repo_rev_for("fred/", sr)) + ", " + str(self.directory_revision_for("fred/") - sr) + "\n" \
               + "wilma/ : " + str(self.repo_rev_for("wilma/", sr)) + ", " + str(self.directory_revision_for("wilma/") - sr) + "\n" \
               + bambam \
               + "barney/ : " + str(self.repo_rev_for("barney/", sr)) + ", " + str(self.directory_revision_for("barney/") - sr) + "\n"


    def no_leading_spaces(self, string):
        c = [item.strip() for item in string.splitlines()]
        return '\n'.join(c)

    def directory_revision_for(self, dir):
        options = requests.request("OPTIONS", self.svn_url + dir, auth=("davsvn", "davsvn"),
                                   data='<?xml version="1.0" encoding="utf-8"?><D:options xmlns:D="DAV:"><D:activity-collection-set></D:activity-collection-set></D:options>')

        self.assertEquals(options.status_code, 200)

        content = options.content.decode("utf-8")
        youngest_rev = options.headers["SVN-Youngest-Rev"].strip()

        rev_dir = self.svn_url.replace('testrepo/', 'testrepo/!svn/rvr/' + youngest_rev + "/") + dir
        propfind = requests.request('PROPFIND', rev_dir, auth=("davsvn", "davsvn"),
                                    data='<?xml version="1.0" encoding="utf-8"?>'
                                         '<propfind xmlns="DAV:">'
                                         '<prop>'
                                         '<version-name/>'
                                         '</prop>'
                                         '</propfind>')

        self.assertEquals(propfind.status_code, 207)

        content = propfind.content.decode("utf-8")
        return int(str([line for line in content.splitlines() if ':version-name>' in line]).split(">")[1].split("<")[0])

    def repo_rev_for(self, dir, offset):
        get = requests.get(self.svn_url + dir, auth=(self.user, self.passwd), verify=False)
        self.assertEqual(get.status_code, 200)
        print(">>>> " + get.text)
        try:
            return int(str([line for line in get.text.splitlines() if 'testrepo - Revision' in line]).split(" ")[3][:-1]) - offset
        except IndexError:
            return "?"


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


    def should_start_with(self, rows, row, start_with_this):
        self.assertTrue(rows[row].startswith(start_with_this), msg="Was actually: " + rows[row])

    def get_db_rows(self, test_start, sync_dir):
        db_ = self.db_dir_a + os.sep + "subsyncit.db"

        # Need to wait for the other process to release the TinyDB database file
        # size = 0
        # while size < 350:
        #     size = os.stat(db_).st_size
        #     if time.time() - start > 45:
        #         self.fail("DB should have finished writin to")
        #     print(">>" + str(size))
        #
        # time.sleep(.1)

        time.sleep(2.5)
        db = TinyDB(db_)
        files_table = db.table('files')

        lowest_rv = 99999
        for row in files_table.all():
            if row['RV'] < lowest_rv:
                lowest_rv = row['RV']

        # Revisions are normalized down to 1,2,3,4 when they actually might be 12,13,14 in the repo

        rv = ""
        for row in files_table.all():
            rv += str(row['RV'] - lowest_rv + 1).zfill(2) + ", " + row['RFN'] + ", " + str(row['RS'])+ ", " + str(row['LS']) + ", " \
                  + str(round((row['ST'] - os.stat(sync_dir + row['RFN']).st_size - test_start) * 1000)) + "\n"

        return sorted(rv.splitlines())

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


    def end(self, p, dir):
        if p is not None:
            self.signal_stop_of_subsyncit(dir)

    def reset_test_dir(self, dirname):
        if os.path.exists(dirname):
            shutil.rmtree(dirname)
        os.makedirs(dirname)


    def signal_stop_of_subsyncit(self, dir):
        if not os.path.exists(dir):
            os.makedirs(dir)

        with open(dir + "subsyncit.stop", "w") as text_file:
            text_file.write("anything")

    def wait_for_file_to_appear(self, file_should_appear):
        start = time.time()
        while not os.path.exists(file_should_appear):
            if time.time() - start > 15:
                self.fail(file_should_appear + " shouldhave appeared but did not")
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
        process_a = self.start_subsyncit(self.svn_url, self.test_sync_dir_a)
        process_b = self.start_subsyncit(self.svn_url, self.test_sync_dir_b)
        return process_a, process_b


    def start_subsyncit(self, svn_repo, dir, passwd=None):
        if passwd is None:
            passwd = self.passwd
        print("Subsyncit start. URL: " + svn_repo + ", dir: " + dir)
        python = sh.python3("subsyncit.py", svn_repo, dir, self.user, '--no-verify-ssl-cert',
                           "--sleep-secs-between-polling", "1",
                           '--passwd', passwd, _out=self.process_output,
                           _err_to_out=True, _bg=True)
        return python


    def start_subsyncit_without_user_and_password(self, svn_repo, dir):
        print("Subsyncit start. URL: " + svn_repo + ", dir: " + dir)
        python = sh.python3("subsyncit.py", svn_repo, dir, None, '--no-verify-ssl-cert',
                           "--sleep-secs-between-polling", "1",
                           '--passwd', "*NONE", _out=self.process_output,
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
        f = open(filename, 'rb')
        requests.put(remote_path, auth=(self.user, self.passwd), data=f, verify=False)
        f.close()


if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='Subsyncit Integration Tests')
    parser.add_argument('--test', dest='test_name', default="all", help="Test name if just one test")
    parser.add_argument('--big', dest='size_of_big_test_file', default="512", help="MB for big file")
    parser.add_argument('--killc', dest='kill_container_at_end', action='store_true', help="Kill container at end?")
    parser.set_defaults(kill_container_at_end=False)

    args = parser.parse_args(sys.argv[1:])

    test_loader = unittest.TestLoader()
    test_names = test_loader.getTestCaseNames(IntegrationTestsOfSyncOperations)
    suite = unittest.TestSuite()
    if args.test_name == "all":
        for tname in test_names:
            suite.addTest(IntegrationTestsOfSyncOperations(tname, args.size_of_big_test_file, args.kill_container_at_end))
    else:
        suite.addTest(IntegrationTestsOfSyncOperations(args.test_name, args.size_of_big_test_file, args.kill_container_at_end))

    result = unittest.TextTestRunner().run(suite)
    sys.exit(not result.wasSuccessful())
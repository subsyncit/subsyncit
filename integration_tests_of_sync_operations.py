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
import getpass
import threading
import time
import unittest
from decorator import decorator
import os

import glob2
import requests
import sh
import pprint
from tinydb import TinyDB, Query

import subsyncit
from base_sync_test import BaseSyncTest
from recreate_svn_repo import make_or_wipe_server_side_subversion_repo


class IntegrationTestsOfSyncOperations(BaseSyncTest):

    i = 0
    testSyncDir1 = ""
    testSyncDir2 = ""
    p1 = None
    p2 = None

    def __init__(self, testname, svnrepo, user, svnrepo_root, size, pword):
        super(IntegrationTestsOfSyncOperations, self).__init__(testname)
        BaseSyncTest.svn_repo = svnrepo
        BaseSyncTest.user = user
        BaseSyncTest.passwd = pword
        BaseSyncTest.size = size
        BaseSyncTest.output = ""
        BaseSyncTest.svnrepo_root = svnrepo_root


    @classmethod
    def setUpClass(cls):
        sh.rm("-rf", str(sh.pwd()).strip('\n') + "/integrationTests/")

    def setUp(self):

        IntegrationTestsOfSyncOperations.i += 1

        IntegrationTestsOfSyncOperations.rel_dir_1 = "integrationTests/1_" + str(IntegrationTestsOfSyncOperations.i) + "/"
        IntegrationTestsOfSyncOperations.testSyncDir1 = str(sh.pwd()).strip('\n') + IntegrationTestsOfSyncOperations.rel_dir_1
        self.reset_test_dir(IntegrationTestsOfSyncOperations.testSyncDir1)
        IntegrationTestsOfSyncOperations.rel_dir_2 = "integrationTests/2_" + str(IntegrationTestsOfSyncOperations.i) + "/"
        IntegrationTestsOfSyncOperations.testSyncDir2 = str(sh.pwd()).strip('\n') + IntegrationTestsOfSyncOperations.rel_dir_2
        self.reset_test_dir(IntegrationTestsOfSyncOperations.testSyncDir2)

        make_or_wipe_server_side_subversion_repo(svnrepo_root, "integrationTests", True, True, True)

    def teardown(self):
        self.end(IntegrationTestsOfSyncOperations.p1, IntegrationTestsOfSyncOperations.testSyncDir1)
        self.end(IntegrationTestsOfSyncOperations.p2, IntegrationTestsOfSyncOperations.testSyncDir2)

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
        print "----------------------------------------------------------"
        print 'Test {0} finished in {1}s using {2}'.format(getattr(f, "__name__", "<unnamed>"), dtout, IntegrationTestsOfSyncOperations.testSyncDir1)
        print "=========================================================="

    @timedtest
    def test_a_single_file_syncs(self):

        p1, p2 = self.start_two_subsyncits("integrationTests/")
        try:
            op1 = IntegrationTestsOfSyncOperations.testSyncDir1 + "output.txt"
            with open(op1, "w") as text_file:
                text_file.write("Hello")
            op2 = IntegrationTestsOfSyncOperations.testSyncDir2 + "output.txt"
            self.wait_for_file_to_appear(op2)
            contents = open(op2).read()
            self.assertEqual(contents, "Hello")
        finally:
            self.end(p1, IntegrationTestsOfSyncOperations.testSyncDir1)
            self.end(p2, IntegrationTestsOfSyncOperations.testSyncDir2)


    @timedtest
    def test_a_changed_file_syncs_back(self):

        p1, p2 = self.start_two_subsyncits("integrationTests/")
        try:
            with open(IntegrationTestsOfSyncOperations.testSyncDir1 + "output.txt", "w") as text_file:
                text_file.write("Hello")
            op2 = IntegrationTestsOfSyncOperations.testSyncDir2 + "output.txt"
            self.wait_for_file_to_appear(op2)
            with open(op2, "w") as text_file:
                text_file.write("Hello to you too")
            self.wait_for_file_contents_to_contain(IntegrationTestsOfSyncOperations.testSyncDir1 + "output.txt", "Hello to you too")
        finally:
            self.end(p1, IntegrationTestsOfSyncOperations.testSyncDir1)
            self.end(p2, IntegrationTestsOfSyncOperations.testSyncDir2)

    @timedtest
    def test_a_deleted_file_syncs_down(self):

        self.expect201(requests.request('MKCOL', self.svn_repo + self.rel_dir_1[:-1], auth=(self.user, self.passwd), verify=False))
        self.expect201(requests.put(self.svn_repo + self.rel_dir_1 + "output.txt", auth=(self.user, self.passwd), data="Hello",
                     verify=False))

        p1 = self.start_subsyncit(self.svn_repo + self.rel_dir_1, IntegrationTestsOfSyncOperations.testSyncDir1)
        try:
            self.wait_for_file_to_appear(IntegrationTestsOfSyncOperations.testSyncDir1 + "output.txt")

            requests.delete(self.svn_repo + self.rel_dir_1 + "output.txt", auth=(self.user, self.passwd), verify=False)
            self.wait_for_file_to_disappear(IntegrationTestsOfSyncOperations.testSyncDir1 + "output.txt")
        finally:
            self.end(p1, IntegrationTestsOfSyncOperations.testSyncDir1)

    @timedtest
    def test_a_deleted_file_can_have_its_parent_dir_deleted_too(self):

        self.expect201(requests.request('MKCOL', self.svn_repo + self.rel_dir_1,
                                        auth=(self.user, self.passwd),
                                        verify=False))

        self.expect201(requests.request('MKCOL',
                                        self.svn_repo + self.rel_dir_1 + "fred/",
                                        auth=(self.user, self.passwd),
                                        verify=False))

        self.expect201(requests.put(self.svn_repo + self.rel_dir_1 + "fred/output.txt",
                     auth=(self.user, self.passwd), data="Hello",
                     verify=False))

        p1 = self.start_subsyncit(self.svn_repo + self.rel_dir_1, IntegrationTestsOfSyncOperations.testSyncDir1)
        try:
            output_txt_ = IntegrationTestsOfSyncOperations.testSyncDir1 + "fred/output.txt"
            self.wait_for_file_to_appear(output_txt_)
            requests.delete(self.svn_repo + self.rel_dir_1 + "fred/output.txt",
                            auth=(self.user, self.passwd), verify=False)
            self.wait_for_file_to_disappear(output_txt_)
            self.wait_for_file_to_disappear(IntegrationTestsOfSyncOperations.testSyncDir1 + "fred")

        finally:
            self.end(p1, IntegrationTestsOfSyncOperations.testSyncDir1)


    @timedtest
    def test_a_deleted_file_syncs_up(self):

        self.expect201(requests.request('MKCOL', self.svn_repo + self.rel_dir_1[:-1], auth=(self.user, self.passwd), verify=False))
        self.expect201(requests.put(self.svn_repo + self.rel_dir_1 + "output.txt", auth=(self.user, self.passwd), data="Hello",
                     verify=False))

        p1 = self.start_subsyncit(self.svn_repo + self.rel_dir_1, IntegrationTestsOfSyncOperations.testSyncDir1)

        try:
            self.wait_for_file_to_appear(IntegrationTestsOfSyncOperations.testSyncDir1 + "output.txt")

            time.sleep(5)
            # print "rmv"
            # os.remove(IntegrationTestsOfSyncOperations.testSyncDir1 + "output.txt")
            # time.sleep(5)
            # print "wait"
            #
            # self.wait_for_file_to_disappear(IntegrationTestsOfSyncOperations.testSyncDir1 + "output.txt")
            #
            # self.assertEquals(
            #     requests.get(self.svn_repo + self.rel_dir_1 + "output.txt", auth=(self.user, self.passwd), verify=False).status_code, 404)
            #
        finally:
            self.end(p1, IntegrationTestsOfSyncOperations.testSyncDir1)


    @timedtest
    def test_a_deleted_file_syncs_back(self):

        p1, p2 = self.start_two_subsyncits("integrationTests/")
        try:
            with open(IntegrationTestsOfSyncOperations.testSyncDir1 + "output.txt", "w") as text_file:
                text_file.write("Hello")
            op2 = IntegrationTestsOfSyncOperations.testSyncDir2 + "output.txt"
            self.wait_for_file_to_appear(op2)
            os.remove(op2)
            self.wait_for_file_to_disappear(IntegrationTestsOfSyncOperations.testSyncDir1 + "output.txt")
            print  IntegrationTestsOfSyncOperations.testSyncDir1 + "output.txt has disappeared as expected"
        finally:
            self.end(p1, IntegrationTestsOfSyncOperations.testSyncDir1)
            self.end(p2, IntegrationTestsOfSyncOperations.testSyncDir2)

    @timedtest
    def test_a_file_changed_while_sync_agent_offline_still_sync_syncs_later(self):

        #TODO
        self.expect201(requests.put(self.svn_repo + "integrationTests/output.txt", auth=(self.user, self.passwd), data="Hello", verify=False))
        p1, p2 = self.start_two_subsyncits("integrationTests/")

        try:
            op1 = IntegrationTestsOfSyncOperations.testSyncDir1 + "output.txt"
            op2 = IntegrationTestsOfSyncOperations.testSyncDir2 + "output.txt"
            self.wait_for_file_to_appear(op1)
            self.wait_for_file_to_appear(op2)
            self.signal_stop_of_subsyncIt(IntegrationTestsOfSyncOperations.testSyncDir2)
            p2.wait()
            with open(op2, "w") as text_file:
                text_file.write("Hello to you too")
            p2 = self.start_subsyncit(self.svn_repo + "integrationTests/", IntegrationTestsOfSyncOperations.testSyncDir2)
            self.wait_for_file_contents_to_contain(op1, "Hello to you too")
        finally:
            self.end(p1, IntegrationTestsOfSyncOperations.testSyncDir1)
            self.end(p2, IntegrationTestsOfSyncOperations.testSyncDir2)


    @timedtest
    def test_a_file_in_dir_added_to_repo_while_sync_agent_offline_still_sync_syncs_later(self):

        self.expect201(requests.request('MKCOL', self.svn_repo + self.rel_dir_1,
                                        auth=(self.user, self.passwd),
                                        verify=False))

        self.expect201(requests.request('MKCOL',
                                        self.svn_repo + self.rel_dir_1 + "fred/",
                                        auth=(self.user, self.passwd),
                                        verify=False))
        self.expect201(requests.put(self.svn_repo + self.rel_dir_1 + "fred/output.txt", auth=(self.user, self.passwd), data="Hello", verify=False))

        p1 = self.start_subsyncit(self.svn_repo + self.rel_dir_1, self.testSyncDir1)

        try:
            op1 = IntegrationTestsOfSyncOperations.testSyncDir1 + "fred/output.txt"
            self.wait_for_file_to_appear(op1)
        finally:
            self.end(p1, IntegrationTestsOfSyncOperations.testSyncDir1)


    @timedtest
    def test_that_excluded_patterns_work(self):

        self.expect201(requests.request('MKCOL', self.svn_repo + self.rel_dir_1,
                                        auth=(self.user, self.passwd),
                                        verify=False))

        self.expect201(requests.put(self.svn_repo + self.rel_dir_1 + ".subsyncit-excluded-filename-patterns", auth=(self.user, self.passwd), data=".*\.foo\n.*\.txt\n.*\.bar", verify=False))

        self.expect201(requests.put(self.svn_repo + self.rel_dir_1 + "output.txt", auth=(self.user, self.passwd), data="Hello", verify=False))

        self.expect201(requests.put(self.svn_repo + self.rel_dir_1 + "output.zzz", auth=(self.user, self.passwd), data="Hello", verify=False))

        p1 = self.start_subsyncit(self.svn_repo + self.rel_dir_1, self.testSyncDir1)

        try:

            op1 = IntegrationTestsOfSyncOperations.testSyncDir1 + "output.zzz"
            self.wait_for_file_to_appear(op1)

            op1 = IntegrationTestsOfSyncOperations.testSyncDir1 + "output.txt"
            time.sleep(5) # the two files should arrive pretty much at the same time, but why not wait 5 secs, heh?
            if os.path.exists(op1):
                self.fail("File " + op1 + " should not have appeared but did.")
        finally:
            self.end(p1, IntegrationTestsOfSyncOperations.testSyncDir1)


    @timedtest
    def test_a_file_in_dir_with_spaces_in_names_are_added_to_repo_while_sync_agent_offline_still_sync_syncs_later(self):

        self.expect201(requests.request('MKCOL', self.svn_repo + self.rel_dir_1,
                                        auth=(self.user, self.passwd),
                                        verify=False))

        self.expect201(requests.request('MKCOL',
                                        self.svn_repo + self.rel_dir_1 + "f r e d/",
                                        auth=(self.user, self.passwd),
                                        verify=False))
        self.expect201(requests.put(self.svn_repo + self.rel_dir_1 + "f r e d/o u t p u t.txt", auth=(self.user, self.passwd), data="Hello", verify=False))

        p1 = self.start_subsyncit(self.svn_repo + self.rel_dir_1, self.testSyncDir1)

        try:
            op1 = IntegrationTestsOfSyncOperations.testSyncDir1 + "f r e d/o u t p u t.txt"
            self.wait_for_file_to_appear(op1)
        finally:
            self.end(p1, IntegrationTestsOfSyncOperations.testSyncDir1)


    @timedtest
    def test_a_file_changed_while_sync_agent_offline_does_not_sync_sync_later_if_it_changed_on_the_server_too(self):

        self.expect201(requests.put(self.svn_repo + "integrationTests/output.txt", auth=(self.user, self.passwd), data="Hello", verify=False))

        p1 = self.start_subsyncit(self.svn_repo + "integrationTests/", IntegrationTestsOfSyncOperations.testSyncDir1)
        try:
            self.wait_for_file_contents_to_contain(IntegrationTestsOfSyncOperations.testSyncDir1 + "output.txt", "Hello")
            self.signal_stop_of_subsyncIt(IntegrationTestsOfSyncOperations.testSyncDir1)
            p1.wait()

            self.expect204(requests.put(self.svn_repo + "integrationTests/output.txt", auth=(self.user, self.passwd), data="Hello changed on server", verify=False))

            with open(IntegrationTestsOfSyncOperations.testSyncDir1 + "output.txt", "w") as text_file:
                text_file.write("Hello changed locally too")

            p1 = self.start_subsyncit(self.svn_repo + "integrationTests/", IntegrationTestsOfSyncOperations.testSyncDir1)
            time.sleep(1)

            self.wait_for_file_contents_to_contain(IntegrationTestsOfSyncOperations.testSyncDir1 + "output.txt", "Hello changed on server")
            clash_file = glob2.glob(IntegrationTestsOfSyncOperations.testSyncDir1 + "*.clash_*")[0]
            self.wait_for_file_contents_to_contain(clash_file, "Hello changed locally too")
        finally:
            self.end(p1, IntegrationTestsOfSyncOperations.testSyncDir1)

    @timedtest
    def test_cant_sync_against_non_svn_dav_site(self):

        p1 = self.start_subsyncit("https://example.com/", IntegrationTestsOfSyncOperations.testSyncDir1, passwd="dontLeakRealPasswordToExampleDotCom")
        try:
            self.wait_for_file_contents_to_contain(IntegrationTestsOfSyncOperations.testSyncDir1 + ".subsyncit.err", "PROPFIND status: 405 for: https://example.com/ user: paul")
        finally:
            self.end(p1, IntegrationTestsOfSyncOperations.testSyncDir1)


    @timedtest
    def test_cant_access_svn_dav_site_with_incorrect_password(self):

        p1 = self.start_subsyncit(self.svn_repo + "integrationTests/", IntegrationTestsOfSyncOperations.testSyncDir1, passwd="sdfsdfget3qgwegsdgsdgsf")
        try:
            self.wait_for_file_contents_to_contain(IntegrationTestsOfSyncOperations.testSyncDir1 + ".subsyncit.err", "PROPFIND status: 401 for: " + self.svn_repo + "integrationTests/" + " user: " + self.user)
        finally:
            self.end(p1, IntegrationTestsOfSyncOperations.testSyncDir1)


    @timedtest
    def test_cant_sync_against_down_site(self):

        p1 = self.start_subsyncit("https://localhost:34456/", IntegrationTestsOfSyncOperations.testSyncDir1)
        try:
            time.sleep(2)
            self.wait_for_file_contents_to_contain(IntegrationTestsOfSyncOperations.testSyncDir1 + ".subsyncit.err", " Failed to establish a new connection")
        finally:
            self.end(p1, IntegrationTestsOfSyncOperations.testSyncDir1)


    @timedtest
    def test_an_excluded_filename_patterns_is_not_pushed_up(self):

        self.expect201(requests.request('MKCOL', self.svn_repo + self.rel_dir_1,
                                        auth=(self.user, self.passwd),
                                        verify=False))

        self.expect201(requests.put(self.svn_repo + self.rel_dir_1 + ".subsyncit-excluded-filename-patterns", auth=(self.user, self.passwd), data=".*\.foo\n.*\.txt\n\~\$.*\n.*\.bar", verify=False))

        op1 = IntegrationTestsOfSyncOperations.testSyncDir1 + "output.txt"
        with open(op1, "w") as text_file:
            text_file.write("I should not be PUT up to the server")

        op1 = IntegrationTestsOfSyncOperations.testSyncDir1 + "~$output"
        with open(op1, "w") as text_file:
            text_file.write("I also should not be PUT up to the server")

        op1 = IntegrationTestsOfSyncOperations.testSyncDir1 + "~output"
        with open(op1, "w") as text_file:
            text_file.write("I also should not be PUT up to the server")

        op1 = IntegrationTestsOfSyncOperations.testSyncDir1 + "$output"
        with open(op1, "w") as text_file:
            text_file.write("I also should not be PUT up to the server")

        op1 = IntegrationTestsOfSyncOperations.testSyncDir1 + "output.zzz"
        with open(op1, "w") as text_file:
            text_file.write("Hello to you too")

        p1 = self.start_subsyncit(self.svn_repo + self.rel_dir_1, self.testSyncDir1)

        try:

            self.wait_for_URL_to_appear(self.svn_repo + self.rel_dir_1 + "output.zzz")
            self.wait_for_URL_to_appear(self.svn_repo + self.rel_dir_1 + "$output")
            self.wait_for_URL_to_appear(self.svn_repo + self.rel_dir_1 + "~output")

            time.sleep(5) # the two files should arrive pretty much at the same time, but why not wait 3 secs, heh?

            self.assertNotEqual(
                requests.get(self.svn_repo + self.rel_dir_1 + "output.txt",
                                 auth=(self.user, self.passwd), verify=False)
                    .status_code, 200, "URL " + self.svn_repo + self.rel_dir_1 + "output.txt" + " should NOT have appeared, but it did")

            self.assertNotEqual(
                requests.get(self.svn_repo + self.rel_dir_1 + "~$output",
                                 auth=(self.user, self.passwd), verify=False)
                    .status_code, 200, "URL " + self.svn_repo + self.rel_dir_1 + "~$output" + " should NOT have appeared, but it did")

        finally:
            self.end(p1, IntegrationTestsOfSyncOperations.testSyncDir1)


    @timedtest
    def test_a_partially_downloaded_big_file_recovers(self):

        filename = str(sh.pwd()).strip('\n') + "/testBigRandomFile"
        start = time.time()
        self.make_a_big_random_file(filename, start, self.size)

        sz = os.stat(filename).st_size
        self.upload_file(filename, self.svn_repo + "integrationTests/testBigRandomFile")

        self.list_files(IntegrationTestsOfSyncOperations.testSyncDir1)

        start = time.time()
        p1 = self.start_subsyncit(self.svn_repo + "integrationTests/", IntegrationTestsOfSyncOperations.testSyncDir1)
        try:
            print "Started Subsyncit, and waiting for " + str(self.size) + "MB random file to be ... "
            self.wait_for_file_contents_to_be_sized_above(IntegrationTestsOfSyncOperations.testSyncDir1 + "testBigRandomFile", sz)
            print " ... secs: " + str(round(time.time() - start, 1))

            self.list_files(IntegrationTestsOfSyncOperations.testSyncDir1)

            self.signal_stop_of_subsyncIt(IntegrationTestsOfSyncOperations.testSyncDir1)
            p1.wait()

            self.list_files(IntegrationTestsOfSyncOperations.testSyncDir1)

            self.make_a_big_random_file(filename, start, self.size)

            self.list_files(IntegrationTestsOfSyncOperations.testSyncDir1)

            self.upload_file(filename, self.svn_repo + "integrationTests/testBigRandomFile")

            self.list_files(IntegrationTestsOfSyncOperations.testSyncDir1)

            start = time.time()

            print "start p1 again"
            p1 = self.start_subsyncit(self.svn_repo + "integrationTests/", IntegrationTestsOfSyncOperations.testSyncDir1)
            self.wait_for_file_contents_to_be_sized_below(IntegrationTestsOfSyncOperations.testSyncDir1 + "testBigRandomFile", (sz/2))
            self.list_files(IntegrationTestsOfSyncOperations.testSyncDir1)
            self.wait_for_file_contents_to_be_sized_above(IntegrationTestsOfSyncOperations.testSyncDir1 + "testBigRandomFile", (sz/2))
            self.list_files(IntegrationTestsOfSyncOperations.testSyncDir1)
            p1.kill()
            print "Killed after secs: " + str(round(time.time() - start, 1))
            self.list_files(IntegrationTestsOfSyncOperations.testSyncDir1)

            time.sleep(5)
            aborted_get_size = os.stat(IntegrationTestsOfSyncOperations.testSyncDir1 + "testBigRandomFile").st_size

            print "Aborted size: " + str(aborted_get_size)

            self.list_files(IntegrationTestsOfSyncOperations.testSyncDir1)

            p1 = self.start_subsyncit(self.svn_repo + "integrationTests/", IntegrationTestsOfSyncOperations.testSyncDir1)
            self.wait_for_file_contents_to_be_sized_above(IntegrationTestsOfSyncOperations.testSyncDir1 + "testBigRandomFile", sz)
        finally:
            self.end(p1, IntegrationTestsOfSyncOperations.testSyncDir1)


        self.list_files(IntegrationTestsOfSyncOperations.testSyncDir1)

        clash_file = glob2.glob(IntegrationTestsOfSyncOperations.testSyncDir1 + "*.clash_*")[0]
        self.assertEquals(os.stat(clash_file).st_size, aborted_get_size)

    def make_a_big_random_file(self, filename, start, size):
        print "Making " + size + "MB random file ... "
        sh.bash("./make_a_so_big_file.sh", filename, size)
        print " ... secs: " + str(round(time.time() - start, 1))

    def list_files(self, root):
        glob = glob2.glob(root + "**")
        print "List of files in " + root + "folder:"
        if len(glob) == 0:
            print "  no files"
        for s in glob:
            print "  " + (str(s))

    def expect201(self, commandOutput):
        self.assertEquals("<Response [201]>", str(commandOutput))

    def expect204(self, commandOutput):
        self.assertEquals("<Response [204]>", str(commandOutput))


if __name__ == '__main__':
    import sys

    test_name = sys.argv[1].lower()

    svnrepo = sys.argv[2]
    user = sys.argv[3]
    pword = getpass.getpass(prompt="Subverison password for " + user + ": ")

    svnrepo_root = sys.argv[4]
    size = sys.argv[5]

    test_loader = unittest.TestLoader()
    test_names = test_loader.getTestCaseNames(IntegrationTestsOfSyncOperations)

    suite = unittest.TestSuite()
    if test_name == "all":
        for tname in test_names:
            suite.addTest(IntegrationTestsOfSyncOperations(tname, svnrepo, user, svnrepo_root, size, pword))
    else:
        suite.addTest(IntegrationTestsOfSyncOperations(test_name, svnrepo, user, svnrepo_root, size, pword))

    result = unittest.TextTestRunner().run(suite)
    sys.exit(not result.wasSuccessful())
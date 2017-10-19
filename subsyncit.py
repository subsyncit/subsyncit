#!/usr/bin/env python3
#
# Subsyncit - File sync backed by Subversion
#
# Version: 2017-10-16 11:58:03.688428 (UTC)
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

# Three arguments for this script:
# 1. Remote Subversion repo URL. Like - "http://0.0.0.0:32768/svn/testrepo"
# 2. Local Sync Directory (fully qualified or relative). Like /path/to/mySyncDir
# 3. Subversion user name.
#
# Optional arguments
# `--passwd` to supply the password on the command line (plain text) instead of prompting for secure entry
# `--no-verify-ssl-cert` to ignore certificate errors if you have a self-signed (say for testing)
# `--sleep-secs-between-polling` to supply a number of seconds to wait between poll of the server for changes
#
# Note: There's a database created in the Local Sync Directory called ".subsyncit.db".
# It contains one row per file that's synced back and forth. There's a field in there repoRev
# which is not currently used, but set to 0

import argparse
import ctypes
import datetime
import getpass
# import sqlite3
import hashlib
import os
import re
import shutil
import sys
import time
from os.path import dirname, splitext
from time import strftime
from threading import Thread, Lock

import requests
import requests.packages.urllib3
from boltons.setutils import IndexedSet
from requests.adapters import HTTPAdapter
from tinydb import Query, TinyDB
from watchdog.events import PatternMatchingEventHandler


PROPFIND = '<?xml version="1.0" encoding="utf-8" ?>\n' \
             '<D:propfind xmlns:D="DAV:">\n' \
             '<D:prop xmlns:S="http://subversion.tigris.org/xmlns/dav/">\n' \
             '<S:sha1-checksum/>\n' \
             '<D:version-name/>\n' \
             '<S:baseline-relative-path/>\n' \
             '</D:prop>\n' \
             '</D:propfind>\n'


def debug(message):
    pass
    ## if not "PROPFIND" in message:
    #    print(message)


def my_trace(lvl, message):
    # pass
    if lvl == 1:
        print(message)


def calculate_sha1_from_local_file(file):
    hasher = hashlib.sha1()
    try:
        with open(file, 'rb') as a_file:
            buf = a_file.read(65536)
            while len(buf) > 0:
                hasher.update(buf)
                buf = a_file.read(65536)
    except IOError:
        return "FILE_MISSING"

    hexdigest = hasher.hexdigest()
    return hexdigest


class MyTinyDBLock():

    def __init__(self, delegate):
        self.delegate = delegate
        self.lock = Lock()

    def search(self, arg0):
        with self.lock:
            return self.delegate.search(arg0)

    def get(self, arg0):
        with self.lock:
            return self.delegate.get(arg0)

    def remove(self, arg0):
        with self.lock:
            return self.delegate.remove(arg0)

    def update(self, arg0, arg1):
        with self.lock:
            return self.delegate.update(arg0, arg1)

    def insert(self, arg0):
        with self.lock:
            return self.delegate.insert(arg0)

    def contains(self, arg0):
        with self.lock:
            return self.delegate.contains(arg0)

    def all(self):
        with self.lock:
            return self.delegate.all()


class NotPUTting(Exception):
    pass


class NotPUTtingAsItWasChangedOnTheServerByAnotherUser(NotPUTting):
    pass


class NotPUTtingAsTheServerObjected(NotPUTting):

    def __init__(self, status_code, content):
        self.message = "content: " + content + " status code:" +  str(status_code)


class NotPUTtingAsFileStillBeingWrittenTo(NotPUTting):

    def __init__(self, filename):
        self.message = "file name: " + filename


class FileSystemNotificationHandler(PatternMatchingEventHandler):

    def __init__(self, local_adds_chgs_deletes_queue, absolute_local_root_path, file_system_watcher, is_shutting_down):
        super(FileSystemNotificationHandler, self).__init__(ignore_patterns=["*/.*"])
        self.is_shutting_down = is_shutting_down
        self.local_adds_chgs_deletes_queue = local_adds_chgs_deletes_queue
        self.absolute_local_root_path = absolute_local_root_path
        self.file_system_watcher = file_system_watcher
        self.excluded_filename_patterns = []

    def on_created(self, event):
        relative_file_name = get_relative_file_name(event.src_path, self.absolute_local_root_path)
        if relative_file_name == ".subsyncit.stop":
            self.file_system_watcher.stop()
            self.is_shutting_down.append(True)
            try:
                self.file_system_watcher.join()
                os.remove(event.src_path)
            except RuntimeError:
                pass
            except OSError:
                pass
            return
        if should_be_excluded(relative_file_name, self.excluded_filename_patterns):
            return

        # print("on_add: " + relative_file_name)
        self.local_adds_chgs_deletes_queue.add((relative_file_name, "add_" + ("dir" if event.is_directory else "file")))

    def on_deleted(self, event):
        relative_file_name = get_relative_file_name(event.src_path, self.absolute_local_root_path)
        if should_be_excluded(relative_file_name, self.excluded_filename_patterns):
            return
        #print("on_del: " + relative_file_name)
        self.local_adds_chgs_deletes_queue.add((relative_file_name, "delete"))

    def on_modified(self, event):
        relative_file_name = get_relative_file_name(event.src_path, self.absolute_local_root_path)
        if should_be_excluded(relative_file_name, self.excluded_filename_patterns):
            return
        if not event.is_directory and not event.src_path.endswith(self.absolute_local_root_path):
            add_queued = (relative_file_name, "add_file") in self.local_adds_chgs_deletes_queue
            chg_queued = (relative_file_name, "change") in self.local_adds_chgs_deletes_queue
            if not add_queued and not chg_queued:
                # print("on_chg: " + event.src_path)
                self.local_adds_chgs_deletes_queue.add((relative_file_name, "change"))


    def update_excluded_filename_patterns(self, excluded_filename_patterns):
        self.excluded_filename_patterns = excluded_filename_patterns

def should_be_excluded(relative_file_name, excluded_filename_patterns):

    basename = os.path.basename(relative_file_name)

    if basename.startswith(".") \
           or len(relative_file_name) == 0 \
           or ".clash_" in relative_file_name:
        return True

    for pattern in excluded_filename_patterns:
        if pattern.search(basename):
            return True

    return False


def get_suffix(relative_file_name):
    file_name, extension = splitext(relative_file_name)
    return extension


def make_remote_subversion_directory_and_return_revision(requests_session, dir, remote_subversion_directory, baseline_relative_path, repo_parent_directory):
    request = requests_session.request('MKCOL', remote_subversion_directory + dir.replace(os.sep, "/"))
    rc = request.status_code
    if rc == 201:
        return get_revision_for_remote_directory(requests_session, remote_subversion_directory, dir.replace(os.sep, "/"), baseline_relative_path, repo_parent_directory)
    raise BaseException("Unexpected return code " + str(rc) + " for " + dir)


def esc(name):
    return name.replace("?", "%3F").replace("&", "%26")


def make_directories_if_missing_in_db(files_table, dname, requests_session, remote_subversion_directory, baseline_relative_path, repo_parent_directory):
    dirs_made = 0
    if dname == "":
        return 0
    dir = files_table.get(Query().relativeFileName == dname)

    if not dir or dir['repoRev'] == 0:
        parentname = dirname(dname)
        if parentname != "":
            parent = files_table.get(Query().relativeFileName == parentname)
            if not parent or parent['repoRev'] == 0:
                dirs_made += make_directories_if_missing_in_db(files_table, parentname, requests_session, remote_subversion_directory, baseline_relative_path, repo_parent_directory)

    if not dir:
        make_directories_if_missing_in_db(files_table, dirname(dname), requests_session, remote_subversion_directory, baseline_relative_path, repo_parent_directory)
        dirs_made += 1
        dir = {'relativeFileName': dname,
               'isFile': "0",
               'remoteSha1': None,
               'localSha1': None,
               'sz_ts': 0,
               'instruction': None,
               'repoRev': make_remote_subversion_directory_and_return_revision(requests_session, dname, remote_subversion_directory, baseline_relative_path, repo_parent_directory)
               }
        files_table.insert(dir)
    elif dir['repoRev'] == 0:
        dirs_made += 1
        files_table.update(
            {
                'instruction': None,
                'repoRev': make_remote_subversion_directory_and_return_revision(requests_session, dname, remote_subversion_directory, baseline_relative_path, repo_parent_directory)
            },
            Query().relativeFileName == dname)
    return dirs_made


def put_item_in_remote_subversion_directory(requests_session, abs_local_file_path, remote_subversion_directory, absolute_local_root_path, files_table, alleged_remoteSha1, baseline_relative_path, repo_parent_directory):
    dirs_made = 0
    s1 = os.path.getsize(abs_local_file_path)
    time.sleep(0.1)
    s2 = os.path.getsize(abs_local_file_path)
    if s1 != s2:
        raise NotPUTtingAsFileStillBeingWrittenTo(abs_local_file_path)
    relative_file_name = get_relative_file_name(abs_local_file_path, absolute_local_root_path)

    dirs_made += make_directories_if_missing_in_db(files_table, dirname(relative_file_name), requests_session, remote_subversion_directory, baseline_relative_path, repo_parent_directory)

    if alleged_remoteSha1:
        (ver, actual_remote_sha1, not_used_here) = get_remote_subversion_repo_revision_for(requests_session, remote_subversion_directory, relative_file_name, absolute_local_root_path)
        if actual_remote_sha1 and actual_remote_sha1 != alleged_remoteSha1:
            raise NotPUTtingAsItWasChangedOnTheServerByAnotherUser() # force into clash scenario later

    # TODO has it changed on server
    with open(abs_local_file_path, "rb") as f:
        put = requests_session.put(remote_subversion_directory + esc(relative_file_name).replace(os.sep, "/"), data=f.read())
        output = put.content.decode('utf-8')
        if put.status_code != 201 and put.status_code != 204:
            raise NotPUTtingAsTheServerObjected(put.status_code, output)
    return dirs_made


def create_GETs_and_local_deletes_instructions_after_comparison_to_files_on_subversion_server(files_table, excluded_filename_patterns, files_on_svn_server):

    my_trace(2, strftime('%Y-%m-%d %H:%M:%S') + "---> create_GETs_and_local_deletes_instructions_after_comparison_to_files_on_subversion_server - start")

    start = time.time()
    unprocessed_files = {}

    rows = files_table.search(Query().instruction == None)
    for row in rows:
        relative_file_name = row['relativeFileName']
        if not should_be_excluded(relative_file_name, excluded_filename_patterns):
            unprocessed_files[relative_file_name] = {
                "instruction" : row["instruction"],
                "remoteSha1" : row['remoteSha1']
            }

    my_trace(2, strftime('%Y-%m-%d %H:%M:%S') + " done populating initial unprocessed files" )

    get_count = 0
    local_deletes = 0
    for relative_file_name, rev, sha1 in files_on_svn_server:
        if should_be_excluded(relative_file_name, excluded_filename_patterns):
            continue
        match = None
        if relative_file_name in unprocessed_files:
                match = unprocessed_files[relative_file_name]
                unprocessed_files.pop(relative_file_name)
        if match:
            if match["instruction"] != None:
                continue
            if not match['remoteSha1'] == sha1:
                get_count += 1
                update_instruction_in_table(files_table, "GET", relative_file_name)
        else:
            get_count += 1
            dir_or_file = "dir" if sha1 is None else "file"
            upsert_row_in_table(files_table, relative_file_name, rev, dir_or_file, instruction="GET")

    my_trace(2, strftime('%Y-%m-%d %H:%M:%S') + " done iterating over files_on_svn_server")

    # files still in the unprocessed_files list are not up on Subversion
    for relative_file_name, val in unprocessed_files.items():
        local_deletes += 1
        update_instruction_in_table(files_table, 'DELETE LOCALLY', relative_file_name)

    duration = time.time() - start
    if duration > 1 or get_count > 0 or local_deletes > 0:
        my_trace(1, strftime('%Y-%m-%d %H:%M:%S') + ": Instructions created for " + str(get_count) + " GETs and " + str(local_deletes)
              + " local deletes (comparison of all the files up on Svn to local files) took " + english_duration(duration) + ".")

    my_trace(2, strftime('%Y-%m-%d %H:%M:%S') + "---> create_GETs_and_local_deletes_instructions_after_comparison_to_files_on_subversion_server - end")


def english_duration(duration):
    if duration < 90:
        return str(round(duration, 2)) + " secs"
    if duration < 5400:
        return str(round(duration/60, 2)) + " mins"
    return str(round(duration/3600, 2)) + " hours"


def un_encode_path(relative_file_name):
    return relative_file_name.replace("&amp;", "&")\
        .replace("&quot;", "\"")\
        .replace("%3F", "?")\
        .replace("%26", "&")


def extract_name_type_rev(entry_xml_element):
    file_or_dir = entry_xml_element.attrib['kind']
    relative_file_name = entry_xml_element.findtext("name")
    rev = entry_xml_element.find("commit").attrib['revision']
    return file_or_dir, relative_file_name, rev


def get_revision_for_remote_directory(requests_session, remote_subversion_directory, relative_file_name, baseline_relative_path, repo_parent_directory):

    options = requests_session.request('OPTIONS', remote_subversion_directory + esc(relative_file_name),
                               data='<?xml version="1.0" encoding="utf-8"?><D:options xmlns:D="DAV:"><D:activity-collection-set></D:activity-collection-set></D:options>')

    if options.status_code != 200:
        return -998

    youngest_rev = options.headers["SVN-Youngest-Rev"].strip()

    path = "!svn/rvr/" + youngest_rev + "/" + baseline_relative_path
    url = remote_subversion_directory.replace(repo_parent_directory + baseline_relative_path, repo_parent_directory + path, 1)
    report = requests_session.request('REPORT', url + "/" + esc(relative_file_name),
                              data='<S:log-report xmlns:S="svn:"><S:start-revision>' + youngest_rev +
                                   '</S:start-revision><S:end-revision>0</S:end-revision><S:limit>1</S:limit><S:revprop>svn:author</S:revprop><S'
                                   ':revprop>svn:date</S:revprop><S:revprop>svn:log</S:revprop><S:path></S:path><S:encode-binary-props/></S:log-report>')

    content = report.content.decode("utf-8")

    if report.status_code != 200:
        return -999

    return int(str([line for line in content.splitlines() if ':version-name>' in line]).split(">")[1].split("<")[0])


def perform_GETs_per_instructions(requests_session, files_table, remote_subversion_directory, absolute_local_root_path, baseline_relative_path, repo_parent_directory):

    my_trace(2, strftime('%Y-%m-%d %H:%M:%S') + " ---> perform_GETs_per_instructions - start")
    start = time.time()
    num_rows = 0
    count = 0

    try:
        rows = files_table.search(Query().instruction == "GET")
        num_rows = len(rows)
        if len(rows) > 3:
            my_trace(2, strftime('%Y-%m-%d %H:%M:%S') + ": " + str(len(rows)) + " GETs to perform on remote Subversion server...")
        for row in rows:

            relative_file_name = row['relativeFileName']
            is_file = row['isFile'] == "1"
            old_sha1_should_be = row['localSha1']
            abs_local_file_path = (absolute_local_root_path + relative_file_name)
            head = requests_session.head(remote_subversion_directory + esc(relative_file_name))

            if not is_file or ("Location" in head.headers and head.headers[
                "Location"].endswith("/")):
                if not os.path.exists(abs_local_file_path):
                    os.makedirs(abs_local_file_path)
                # TODO
                # if row['repoRev'] != 0:
                #     print ("Dir GET needlessly: " + relative_file_name)
                # print("rr=" + str(rr))
                files_table.update({
                    'repoRev': get_revision_for_remote_directory(requests_session, remote_subversion_directory, relative_file_name, baseline_relative_path, repo_parent_directory),
                    'remoteSha1': None,
                    'localSha1': None,
                    'sz_ts': 0},
                    Query().relativeFileName == relative_file_name)
            else:
                (repoRev, sha1,
                 baseline_relative_path_not_used) = get_remote_subversion_repo_revision_for(requests_session,
                                                                                            remote_subversion_directory, relative_file_name, absolute_local_root_path, must_be_there=True)

                get = requests_session.get(remote_subversion_directory + esc(relative_file_name).replace(os.sep, "/"), stream=True)
                # debug(absolute_local_root_path + relative_file_name + ": GET " + str(get.status_code))
                # See https://github.com/requests/requests/issues/2155
                # and https://stackoverflow.com/questions/16694907/how-to-download-large-file-in-python-with-requests-py

                if os.path.exists(abs_local_file_path):
                    local_sha1 = calculate_sha1_from_local_file(abs_local_file_path)
                    if local_sha1 != old_sha1_should_be:
                        os.rename(abs_local_file_path,
                                  abs_local_file_path + ".clash_" + datetime.datetime.today().strftime(
                                      '%Y-%m-%d-%H-%M-%S'))
                with open(abs_local_file_path, 'wb') as f:
                    for chunk in get.iter_content(chunk_size=500000000):
                        if chunk:
                            f.write(chunk)
                count += 1
                sha1 = calculate_sha1_from_local_file(abs_local_file_path)
                osstat = os.stat(abs_local_file_path)
                size_ts = osstat.st_size + osstat.st_mtime
                update_row_shas_size_and_timestamp(files_table, relative_file_name, sha1, size_ts)
                update_row_revision(files_table, relative_file_name, repoRev)
            update_instruction_in_table(files_table, None, relative_file_name)
    finally:

        if num_rows > 0:
            my_trace(1, strftime('%Y-%m-%d %H:%M:%S') + ": GETs from Svn repo took " + english_duration(time.time() - start) + ", " + str(count)
                  + " files total (from " + str(num_rows) + " total), at " + str(round(count / (time.time() - start) , 2)) + "/sec.")

    my_trace(2, strftime('%Y-%m-%d %H:%M:%S') + " ---> perform_GETs_per_instructions - end")

def perform_local_deletes_per_instructions(files_table, absolute_local_root_path):

    my_trace(2, strftime('%Y-%m-%d %H:%M:%S') + " ---> perform_local_deletes_per_instructions - start")

    start = time.time()

    rows = files_table.search(Query().instruction == 'DELETE LOCALLY')

    try:
        for row in rows:
            relative_file_name = row['relativeFileName']
            name = (absolute_local_root_path + relative_file_name)
            try:
                os.remove(name)
                files_table.remove(Query().relativeFileName == relative_file_name)
            except OSError:
                # has child dirs/files - shouldn't be deleted - can be on next pass.
                continue

    finally:

        duration = time.time() - start
        if duration > 1:
            my_trace(1, strftime('%Y-%m-%d %H:%M:%S') + ": Performing local deletes took " + english_duration(duration) + ".")

    my_trace(2, strftime('%Y-%m-%d %H:%M:%S') + " ---> perform_local_deletes_per_instructions - end")

def update_row_shas_size_and_timestamp(files_table, relative_file_name, sha1, size_ts):
    foo = files_table.update({'remoteSha1': sha1, 'localSha1': sha1, 'sz_ts': size_ts}, Query().relativeFileName == relative_file_name)

def prt_files_table_for(files_table, relative_file_name):
    return str(files_table.search(Query().relativeFileName == relative_file_name))


def update_row_revision(files_table, relative_file_name, rev=-1):
    files_table.update({'repoRev': 0}, Query().relativeFileName == relative_file_name)


def upsert_row_in_table(files_table, relative_file_name, rev, file_or_dir, instruction):

    # print "upsert1" + prt_files_table_for(files_table, relative_file_name)
    if not files_table.contains(Query().relativeFileName == relative_file_name):
        files_table.insert({'relativeFileName': relative_file_name,
                            'isFile': "1" if file_or_dir == "file" else "0",
                            'remoteSha1': None,
                            'localSha1': None,
                            'sz_ts': 0,
                            'instruction': instruction,
                            'repoRev': rev})
        return

    if instruction is not None:
        update_instruction_in_table(files_table, instruction, relative_file_name)


def update_instruction_in_table(files_table, instruction, relative_file_name):
    if instruction is not None and instruction == "DELETE":

        files_table.update({'instruction': instruction}, Query().relativeFileName == relative_file_name)

        # TODO LIKE

    else:

        files_table.update({'instruction': instruction}, Query().relativeFileName == relative_file_name)


def get_relative_file_name(full_path, absolute_local_root_path):
    if not full_path.startswith(absolute_local_root_path):
        if not (full_path + os.sep).startswith(absolute_local_root_path):
            raise ValueError('Unexpected file/dir ' + full_path + ' not under ' + absolute_local_root_path)
    rel = full_path[len(absolute_local_root_path):]
    if rel.startswith(os.sep):
        rel = rel[1:]
    return rel

def svn_metadata_xml_elements_for(requests_session, url, baseline_relative_path):

    start = time.time()

    propfind = requests_session.request('PROPFIND', url, data=PROPFIND, headers={'Depth': 'infinity'})

    output = propfind.content.decode('utf-8')

    if "PROPFIND requests with a Depth of \"infinity\"" in output:
        print("'DavDepthInfinity on' needs to be enabled for the Apache instance on " \
              "the server (in httpd.conf propbably). Refer to " \
              "https://github.com/paul-hammant/subsyncit/blob/master/SERVER-SETUP.md. " \
              "Subsyncit is refusing to run.")
        exit(1)

    entries = []; path = ""; rev = -1; sha1 = None

    for line in output.splitlines():
        if ":baseline-relative-path>" in line:
            path = un_encode_path(extract_path_from_baseline_rel_path(baseline_relative_path, line))
        if ":version-name" in line:
            rev = int(line[line.index(">") + 1:line.index("<", 3)])
        if ":sha1-checksum>" in line:
            sha1 = line[line.index(">") + 1:line.index("<", 3)]
        if "</D:response>" in line:
            if path != "":
                entries.append ((path, rev, sha1))
            path = ""; rev = -1; sha1 = None

    duration = time.time() - start
    if duration > 1:
        my_trace(1, strftime('%Y-%m-%d %H:%M:%S') + ": PROFIND (root/all) on Svn repo took " + english_duration(duration) + ", for " + str(len(entries)) + " entries.")

    return entries

def extract_path_from_baseline_rel_path(baseline_relative_path, line):
    search = re.search(
        "<lp[0-9]:baseline-relative-path>" + baseline_relative_path.replace(
            os.sep, "/") + "(.*)</lp[0-9]:baseline-relative-path>", line)
    if search:
        path = search.group(1)
        if path.startswith("/"):
            path = path[1:]
    else:
        path = ""
    #            print "LINE=" + line + ", PATH=" + path + "-" + baseline_relative_path + "-"
    return path.replace("/", os.sep).replace("\\", os.sep).replace(os.sep+os.sep, os.sep)


def perform_PUTs_per_instructions(requests_session, files_table, remote_subversion_directory, baseline_relative_path, absolute_local_root_path, repo_parent_directory):

    my_trace(2, strftime('%Y-%m-%d %H:%M:%S') + "---> perform_PUTs_per_instructions - start")

    possible_clash_encountered = False
    more_to_do = True
    group = 0

    # Batches of 100 so that here's intermediate reporting.
    while more_to_do:
        more_to_do = False
        start = time.time()
        num_rows = 0
        put_count = 0
        dirs_made = 0
        not_actually_changed = 0
        try:
            rows = files_table.search(Query().instruction == "PUT")
            num_rows = len(rows)
            if len(rows) > 0:
                my_trace(2, strftime('%Y-%m-%d %H:%M:%S') + ": " + str(len(rows)) + " PUTs to perform on remote Subversion server...")
            for row in rows:
                rel_file_name = row['relativeFileName']
                try:
                    abs_local_file_path = (absolute_local_root_path + rel_file_name)
                    new_local_sha1 = calculate_sha1_from_local_file(abs_local_file_path)
                    output = ""
                    # print("-new_local_sha1=" + new_local_sha1)
                    # print("-row['remoteSha1']=" + str(row['remoteSha1']))
                    # print("-row['localSha1']=" + str(row['localSha1']))
                    if new_local_sha1 == 'FILE_MISSING' or (row['remoteSha1'] == row['localSha1'] and row['localSha1'] == new_local_sha1):
                        pass
                        # files that come down as new/changed, get written to the FS trigger a file added/changed message,
                        # and superficially look like they should get pushed back to the server. If the sha1 is unchanged
                        # don't do it.

                        num_rows = num_rows -1
                        update_instruction_in_table(files_table, None, rel_file_name)
                    else:
                        dirs_made += put_item_in_remote_subversion_directory(requests_session, abs_local_file_path, remote_subversion_directory, absolute_local_root_path, files_table,
                                                                         row['remoteSha1'], baseline_relative_path, repo_parent_directory)  # <h1>Created</h1>

                        osstat = os.stat(abs_local_file_path)
                        size_ts = osstat.st_size + osstat.st_mtime
                        update_sha_and_revision_for_row(requests_session, files_table, rel_file_name, new_local_sha1, remote_subversion_directory, baseline_relative_path, size_ts)
                        put_count += 1
                        update_instruction_in_table(files_table, None, rel_file_name)
                except NotPUTtingAsItWasChangedOnTheServerByAnotherUser:
                    # Let another cycle get back to the and the GET to win.
                    not_actually_changed += 1
                    possible_clash_encountered = True
                    update_instruction_in_table(files_table, None, rel_file_name)
                except NotPUTtingAsFileStillBeingWrittenTo as e:
                    not_actually_changed += 1
                    update_instruction_in_table(files_table, None, rel_file_name)
                except NotPUTtingAsTheServerObjected as e:
                    not_actually_changed += 1
                    if "txn-current-lock': Permission denied" in e.message:
                        print("User lacks write permissions for " + rel_file_name + ", and that may (I am not sure) be for the whole repo")
                    else:
                        print(("Unexpected on_created output for " + rel_file_name + " = [" + e.message + "]"))
                if put_count == 100:
                    more_to_do = True
                    group += 1
                    break
        finally:

            if num_rows > 0:
                not_actually_changed_blurb = ""
                if not_actually_changed > 0:
                    not_actually_changed_blurb = "(" + str(not_actually_changed) + " not actually changed; from " + str(num_rows) + " total), "
                dirs_made_blurb = ""
                duration = time.time() - start
                if put_count > 0:
                    speed = "taking " + english_duration(round(duration/put_count, 2)) + " each "
                else:
                    speed = " "
                    # speed = str(round(put_count / duration, 2)) + "/sec "
                if dirs_made > 0:
                    dirs_made_blurb = "(including " + str(dirs_made) + " MKCOLs to facilitate those PUTs)"
                my_trace(1, strftime('%Y-%m-%d %H:%M:%S') + ("" if group == 0 else "Group " + str(group) + " of")
                         + ": PUTs on Subversion server took " + english_duration(time.time() - start) + ", " + str(put_count)
                         + " PUT files, " + not_actually_changed_blurb
                         + speed + dirs_made_blurb + ".")

    my_trace(2, strftime('%Y-%m-%d %H:%M:%S') + "---> perform_PUTs_per_instructions - end")

    return possible_clash_encountered

def update_sha_and_revision_for_row(requests_session, files_table, relative_file_name, local_sha1, remote_subversion_directory, baseline_relative_path, size_ts):
    url = remote_subversion_directory + esc(relative_file_name)
    elements_for = svn_metadata_xml_elements_for(requests_session, url, baseline_relative_path)
    i = len(elements_for)
    if i > 1:
        raise Exception("too many elements found: " + str(i))
    for not_used_this_time, remote_rev_num, remote_sha1 in elements_for:
        if local_sha1 != remote_sha1:
            raise NotPUTtingAsItWasChangedOnTheServerByAnotherUser()
        files_table.update({
            'repoRev': remote_rev_num,
            'remoteSha1': remote_sha1,
            'localSha1': remote_sha1,
            'sz_ts': size_ts
        }, Query().relativeFileName == relative_file_name)

def update_revisions_for_created_directories(requests_session, files_table, remote_subversion_directory, absolute_local_root_path):

    my_trace(2, strftime('%Y-%m-%d %H:%M:%S') + "---> update_revisions_for_created_directories - start")

    rows = files_table.search(Query().instruction == 'MKCOL')

    start = time.time()

    for row in rows:
        relative_file_name = row['relativeFileName']
        if row['remoteSha1'] :
            update_instruction_in_table(files_table, None, relative_file_name)
        (revn, sha1, baseline_relative_path_not_used) = get_remote_subversion_repo_revision_for(requests_session, remote_subversion_directory, relative_file_name, absolute_local_root_path, must_be_there=True)
        update_row_revision(files_table, relative_file_name, rev=revn)
        update_instruction_in_table(files_table, None, relative_file_name)

    if len(rows) > 0:
        my_trace(1, strftime('%Y-%m-%d %H:%M:%S') + ": MKCOLs on Svn repo took " + english_duration(time.time() - start) + ", " + str(len(rows))
                 + " directories, " + str(round(len(rows) / (time.time() - start), 2)) + "/sec.")
    my_trace(2, strftime('%Y-%m-%d %H:%M:%S') + "---> update_revisions_for_created_directories - end")

def perform_DELETEs_on_remote_subversion_repo_per_instructions(requests_session, files_table, remote_subversion_directory):

    my_trace(2, strftime('%Y-%m-%d %H:%M:%S') + "---> perform_DELETEs_on_remote_subversion_repo_per_instructions - start")

    start = time.time()

    rows = files_table.search(Query().instruction == 'DELETE ON REMOTE')

    files_deleted = 0
    directories_deleted = 0
    for row in rows:
        rfn = row['relativeFileName']
        requests_delete = requests_session.delete(remote_subversion_directory + esc(rfn).replace(os.sep, "/"))
        output = requests_delete.content.decode('utf-8')
        # debug(row['relativeFileName'] + ": DELETE " + str(requests_delete.status_code))
        if row['isFile'] == 1:  # isFile
            files_deleted += 1
            files_table.remove(Query().relativeFileName == row['relativeFileName'])
        else:
            directories_deleted += 1
            files_table.remove(Query().relativeFileName == row['relativeFileName'])
            # TODO LIKE

        if ("\n<h1>Not Found</h1>\n" not in output) and str(output) != "":
            print(("Unexpected on_deleted output for " + row['relativeFileName'] + " = [" + str(output) + "]"))

    if len(rows) > 0:
        my_trace(1, strftime('%Y-%m-%d %H:%M:%S') + ": DELETEs on Svn repo took " + english_duration(time.time() - start) + ", "
              + str(directories_deleted) + " directories and " + str(files_deleted) + " files, "
              + str(round((time.time() - start) / len(rows), 2)) + " secs per DELETE.")

    my_trace(2, strftime('%Y-%m-%d %H:%M:%S') + "---> perform_DELETEs_on_remote_subversion_repo_per_instructions - end")

def get_remote_subversion_repo_revision_for(requests_session, remote_subversion_directory, relative_file_name, absolute_local_root_path, must_be_there = False):
    ver = -1
    sha1 = None
    baseline_relative_path = ""
    content = ""
    try:
        url = remote_subversion_directory + esc(relative_file_name).replace("\\", "/")
        if url.endswith("/"):
            url = url[:-1]
        propfind = requests_session.request('PROPFIND', url, data=PROPFIND, headers={'Depth': '0'})
        if 200 <= propfind.status_code <= 299:
            content = propfind.content.decode('utf-8')

            for line in content.splitlines():
                if ":baseline-relative-path" in line and "baseline-relative-path/>" not in line:
                    baseline_relative_path=line[line.index(">")+1:line.index("<", 3)]
                if ":version-name" in line:
                    ver=int(line[line.index(">")+1:line.index("<", 3)])
                if ":sha1-checksum" in line:
                    if "sha1-checksum/" in line:
                        sha1 = None
                    else:
                        sha1=line[line.index(">")+1:line.index("<", 3)]
            # debug(relative_file_name + ": PROPFIND " + str(propfind.status_code) + " / " + str(sha1) + " / " + str(ver))
        elif 400 <= propfind.status_code <= 499:
            content = "Cannot attach to remote Subversion server. Maybe not Subversion+Apache? Or wrong userId and/or password? Or wrong subdirectory within the server? Status code: " + str(
                propfind.status_code)
        else:
            content = "PROPFIND sstatus: " + str(propfind.status_code) + " for: " + url
        if must_be_there and ver == -1:
            write_error(absolute_local_root_path, content)
    except requests.exceptions.ConnectionError as e:
        write_error(absolute_local_root_path, "Could be offline? " + repr(e))
    return (ver, sha1, baseline_relative_path)


def get_repo_parent_directory(requests_session, remote_subversion_directory):
    url = remote_subversion_directory
    if url.endswith("/"):
        url = url[:-1]

    opts = requests_session.request('OPTIONS', url,
                                    data='<?xml version="1.0" encoding="utf-8"?><D:options xmlns:D="DAV:"><D:activity-collection-set></D:activity-collection-set></D:options>').content.decode("utf-8")
    return str([line for line in opts.splitlines() if ':activity-collection-set>' in line]).split(">")[2].split("!svn")[0]

def write_error(absolute_local_root_path, msg):
    subsyncit_err = absolute_local_root_path + ".subsyncit.err"
    with open(subsyncit_err, "w") as text_file:
        text_file.write(msg)
    make_hidden_on_windows_too(subsyncit_err)


def sleep_a_little(sleep_secs):
    #print("sleeping " + str(sleep_secs))
    time.sleep(sleep_secs)



def transform_enqueued_actions_into_instructions(files_table, local_adds_chgs_deletes_queue, sync_dir):

    my_trace(2, strftime('%Y-%m-%d %H:%M:%S') + " ---> transform_enqueued_actions_into_instructions - start")

    start = time.time()

    initial_queue_length = len(local_adds_chgs_deletes_queue)
    while len(local_adds_chgs_deletes_queue) > 0:
        (relative_file_name, action) = local_adds_chgs_deletes_queue.pop(0)
        if action == "add_dir":
            upsert_row_in_table(files_table, relative_file_name, "-1", "dir", instruction="MKCOL")
        elif action == "add_file":
            in_subversion = file_is_in_subversion(files_table, relative_file_name)
            # 'svn up' can add a file, causing watchdog to trigger an add notification .. to be ignored
            if not in_subversion:
                # print("File to add: " + relative_file_name + " is not in subversion")
                upsert_row_in_table(files_table, relative_file_name, "-1", "file", instruction="PUT")
        elif action == "change":
            # print("File changed: " + relative_file_name + " is not in subversion")
            update_instruction_in_table(files_table, "PUT", relative_file_name)
        elif action == "delete":
            in_subversion = file_is_in_subversion(files_table, relative_file_name)
            # 'svn up' can delete a file, causing watchdog to trigger a delete notification .. to be ignored
            if in_subversion:
                update_instruction_in_table(files_table, "DELETE ON REMOTE", relative_file_name)
        else:
            raise Exception("Unknown action " + action)

    if len(local_adds_chgs_deletes_queue) > 0:
        my_trace(1, strftime('%Y-%m-%d %H:%M:%S') + ": Creation of instructions from " + str(initial_queue_length) + " enqueued actions took " + english_duration(time.time() - start) + ".")

    my_trace(2, strftime('%Y-%m-%d %H:%M:%S') + " ---> transform_enqueued_actions_into_instructions - end")


def file_is_in_subversion(files_table, relative_file_name):
    row = files_table.get(Query().relativeFileName == relative_file_name)
    return False if not row else row['remoteSha1'] != None


def print_rows(files_table):
    files_table_all = sorted(files_table.all(), key=lambda k: k['relativeFileName'])
    if len(files_table_all) > 0:
        print("All Items, as per 'files' table:")
        print("  relativeFileName, 0=dir or 1=file, rev, remote sha1, local sha1, size + timestamp, instruction")
        for row in files_table_all:
            print(("  " + row['relativeFileName'] + ", " + str(row['isFile']) + ", " + str(row['repoRev']) + ", " +
                  str(row['remoteSha1']) + ", " + str(row['localSha1']) + ", " + str(row['sz_ts']) + ", " + str(row['instruction'])))


def scantree(path):
    for entry in os.scandir(path):
        if entry.is_dir(follow_symlinks=False):
            yield from scantree(entry.path)
        else:
            yield entry


def enqueue_any_missed_adds_and_changes(is_shutting_down, files_table, local_adds_chgs_deletes_queue, absolute_local_root_path, excluded_filename_patterns, last_scanned):

    my_trace(2, strftime('%Y-%m-%d %H:%M:%S') + " ---> enqueue_any_missed_adds_and_changes - start")

    start = time.time()

    to_add = 0
    to_change = 0
    for entry in scantree(absolute_local_root_path):
        if True in is_shutting_down:
            break
        if to_add + to_change > 100:
            break
        if entry.stat().st_mtime < last_scanned:
            continue

        abs_local_file_path = entry.path
        relative_file_name = get_relative_file_name(abs_local_file_path, absolute_local_root_path)

        if should_be_excluded(relative_file_name, excluded_filename_patterns):
            continue

        row = files_table.get(Query().relativeFileName == relative_file_name)
        in_subversion = row and row['remoteSha1'] != None
        if row and row['instruction'] != None: # or row['isFile'] == "1")
            continue
        if not in_subversion:
            add_queued = (relative_file_name, "add_file") in local_adds_chgs_deletes_queue
            if not add_queued:
                local_adds_chgs_deletes_queue.add((relative_file_name, "add_file"))
                to_add += 1
        else:
            size_ts = entry.stat().st_size + entry.stat().st_mtime
            if size_ts != row["sz_ts"]:
                # This is speculative, logic further on will not PUT the file up if the SHA
                # is unchanged, but file_size + time_stamp change is approximate but far quicker
                add_queued = (relative_file_name, "add_file") in local_adds_chgs_deletes_queue
                chg_queued = (relative_file_name, "change") in local_adds_chgs_deletes_queue
                if not add_queued and not chg_queued:
                    local_adds_chgs_deletes_queue.add((relative_file_name, "change"))
                    to_change += 1


    duration = time.time() - start
    if duration > 5 or to_change > 0 or to_add > 0:
        my_trace(1, strftime('%Y-%m-%d %H:%M:%S') + ": File system scan for extra PUTs: " + str(to_add) + " missed adds and " + str(to_change)
              + " missed changes (added/changed while Subsyncit was not running or somehow missed the attention of the file-system watcher) took " + english_duration(duration) + ".")

    my_trace(2, strftime('%Y-%m-%d %H:%M:%S') + " ---> enqueue_any_missed_adds_and_changes - end")

    return to_add + to_change

def enqueue_any_missed_deletes(is_shutting_down, files_table, local_adds_chgs_deletes_queue, absolute_local_root_path, last_scanned_path):

    my_trace(2, strftime('%Y-%m-%d %H:%M:%S') + " ---> enqueue_any_missed_deletes - start")

    start = time.time()
    to_delete = 0

    file = Query()
    for row in files_table.search((file.instruction == None) & (file.remoteSha1 != None)):
        if True in is_shutting_down:
            break
        if to_delete > 100:
            break

        relative_file_name = row['relativeFileName']
        relative_file_name = relative_file_name
        if not os.path.exists(absolute_local_root_path + relative_file_name):
            to_delete += 1
            print("missed delete " + relative_file_name + " " + str(row))
            local_adds_chgs_deletes_queue.add((relative_file_name, "delete"))


    duration = time.time() - start
    if duration > 20 or to_delete > 0 :
        my_trace(1, strftime('%Y-%m-%d %H:%M:%S') + ": " + str(to_delete)
                 + " extra DELETEs (deleted locally while Subsyncit was not running or somehow missed the attention of the file-system watcher) took "
                 + english_duration(duration) + ".")

    my_trace(2, strftime('%Y-%m-%d %H:%M:%S') + " ---> enqueue_any_missed_deletes - end")

    return to_delete


def should_subsynct_keep_going(file_system_watcher, absolute_local_root_path):
    if not file_system_watcher.is_alive():
        return False
    fn = absolute_local_root_path + ".subsyncit.stop"
    if os.path.isfile(fn):
        try:
            file_system_watcher.stop()
            file_system_watcher.join()
        except KeyError:
            pass
        try:
            os.remove(fn)
        except OSError:
            pass
        return False
    return True

def get_excluded_filename_patterns(requests_session, remote_subversion_directory):
    try:
        get = requests_session.get(remote_subversion_directory + ".subsyncit-excluded-filename-patterns")
        if (get.status_code == 200):
            lines = get.content.decode('utf-8').splitlines()
            regexes = []
            for line in lines:
                regexes.append(re.compile(line))
            return regexes
        return []
    except requests.exceptions.ConnectionError as e:
        return []


def make_requests_session(auth, verifySetting):
    # New session per major loop
    requests_session = requests.Session()
    requests_session.auth = auth
    requests_session.verify = verifySetting
    http_adapter = HTTPAdapter(pool_connections=1, max_retries=0)
    requests_session.mount('http://', http_adapter)
    requests_session.mount('https://', http_adapter)
    return requests_session


def make_hidden_on_windows_too(path):
    if os.name == 'nt':
        FILE_ATTRIBUTE_HIDDEN = 0x02
        ret = ctypes.windll.kernel32.SetFileAttributesW(path, FILE_ATTRIBUTE_HIDDEN)


def main(argv):

    if os.name != 'nt':
        home_dir = os.path.expanduser('~' + (os.getenv("SUDO_USER") or os.getenv("USER")))
    else:
        home_dir = os.path.expanduser(str(os.getenv('USERPROFILE')))

    parser = argparse.ArgumentParser(description='Subsyncit client')

    parser.add_argument("remote_subversion_directory")
    parser.add_argument("local_root_path")
    parser.add_argument("user")
    parser.add_argument('--passwd', dest='passwd', help="Password")
    parser.add_argument('--verify-ssl-cert', dest='verify_ssl_cert', action='store_true', help="Verify SSL Certificate")
    parser.add_argument('--no-verify-ssl-cert', dest='verify_ssl_cert', action='store_false', help="Verify SSL Certificate")
    parser.set_defaults(verify_ssl_cert=True)
    parser.add_argument("--sleep-secs-between-polling", dest="sleep_secs",
                        default=30, type=int,
                        help="Sleep seconds between polling server")

    args = parser.parse_args(argv[1:])

    if not args.passwd:
        passwd = getpass.getpass(prompt="Subverison password for " + args.user + ": ")
    else:
        passwd = args.passwd

    args.absolute_local_root_path = os.path.abspath(args.local_root_path.replace("/", os.sep) \
                         .replace("\\", os.sep).replace(os.sep+os.sep, os.sep))

    if not args.absolute_local_root_path.endswith(os.sep):
        args.absolute_local_root_path += os.sep

    fn = args.absolute_local_root_path + os.sep + ".subsyncit.stop"
    if os.path.isfile(fn):
        try:
            os.remove(fn)
        except OSError:
            pass


    if not str(args.remote_subversion_directory).endswith("/"):
        args.remote_subversion_directory += "/"

    verifySetting = True

    auth = (args.user, passwd)

    if not args.verify_ssl_cert:
        requests.packages.urllib3.disable_warnings()
        verifySetting = args.verify_ssl_cert

    subsyncit_settings_dir = home_dir + os.sep + ".subsyncit"
    if not os.path.exists(subsyncit_settings_dir):
        os.mkdir(subsyncit_settings_dir)
    make_hidden_on_windows_too(subsyncit_settings_dir)

    db_dir = subsyncit_settings_dir + os.sep + args.absolute_local_root_path.replace("/","%47").replace(":","%58").replace("\\","%92")

    if not os.path.exists(db_dir):
        os.mkdir(db_dir)

    db = TinyDB(db_dir + os.sep + "subsyncit.db")
    files_table  = MyTinyDBLock(db.table('files'))

    last_scanned_path  = db_dir + os.sep + "last_scanned"
    if not os.path.exists(last_scanned_path):
        with open(last_scanned_path, "w") as last_scanned_f:
            last_scanned_f.write("0")

    with open(db_dir + os.sep + "INFO.TXT", "w") as text_file:
        text_file.write(args.absolute_local_root_path + "is the Subsyncit path that this pertains to")

    local_adds_chgs_deletes_queue = IndexedSet()

    last_root_revision = -1
    repo_parent_directory = ""
    is_shutting_down = []

    file_system_watcher = None
    if sys.platform == "linux" or sys.platform == "linux2":
        from watchdog.observers.inotify import InotifyObserver
        file_system_watcher = InotifyObserver()
    elif sys.platform == "darwin":
        from watchdog.observers.fsevents import FSEventsObserver
        file_system_watcher = FSEventsObserver()
    elif sys.platform == "win32":
        from watchdog.observers.read_directory_changes import WindowsApiObserver
        file_system_watcher = WindowsApiObserver

    notification_handler = FileSystemNotificationHandler(local_adds_chgs_deletes_queue, args.absolute_local_root_path, file_system_watcher, is_shutting_down)
    file_system_watcher.schedule(notification_handler, args.absolute_local_root_path, recursive=True)
    file_system_watcher.start()

    iteration = 0
    excluded_filename_patterns = ["hi*"]

    try:
        while should_subsynct_keep_going(file_system_watcher, args.absolute_local_root_path):

            requests_session = make_requests_session(auth, verifySetting)

            (root_revision_on_remote_svn_repo, sha1, baseline_relative_path) = \
                get_remote_subversion_repo_revision_for(requests_session, args.remote_subversion_directory, "", args.absolute_local_root_path, must_be_there=True) # root
            if root_revision_on_remote_svn_repo > 0:
                repo_parent_directory = get_repo_parent_directory(requests_session, args.remote_subversion_directory)

            to_add_chg_or_del = 0
            if root_revision_on_remote_svn_repo != -1:
                if iteration == 0: # At boot time only for now
                    excluded_filename_patterns = get_excluded_filename_patterns(requests_session, args.remote_subversion_directory)
                    notification_handler.update_excluded_filename_patterns(excluded_filename_patterns)

                scan_start_time = int(time.time())
                with open(last_scanned_path, "r") as last_scanned_f:
                    read = last_scanned_f.read().strip()

                    last_scanned = int(read)

                to_add_chg_or_del =  enqueue_any_missed_adds_and_changes(is_shutting_down, files_table, local_adds_chgs_deletes_queue, args.absolute_local_root_path, excluded_filename_patterns, last_scanned) \
                                   + enqueue_any_missed_deletes(is_shutting_down, files_table, local_adds_chgs_deletes_queue, args.absolute_local_root_path, last_scanned)

                if to_add_chg_or_del == 0:
                    with open(last_scanned_path, "w") as last_scanned_f:
                        last_scanned_f.write(str(scan_start_time))

                # Act on existing instructions (if any)
                transform_enqueued_actions_into_instructions(files_table, local_adds_chgs_deletes_queue, args.absolute_local_root_path)
                perform_GETs_per_instructions(requests_session, files_table, args.remote_subversion_directory, args.absolute_local_root_path, baseline_relative_path, repo_parent_directory)
                transform_enqueued_actions_into_instructions(files_table, local_adds_chgs_deletes_queue, args.absolute_local_root_path)
                perform_local_deletes_per_instructions(files_table, args.absolute_local_root_path)
                transform_enqueued_actions_into_instructions(files_table, local_adds_chgs_deletes_queue, args.absolute_local_root_path)
                possible_clash_encountered = perform_PUTs_per_instructions(requests_session, files_table, args.remote_subversion_directory, baseline_relative_path, args.absolute_local_root_path, repo_parent_directory)
                transform_enqueued_actions_into_instructions(files_table, local_adds_chgs_deletes_queue, args.absolute_local_root_path)
                perform_DELETEs_on_remote_subversion_repo_per_instructions(requests_session, files_table, args.remote_subversion_directory)
                transform_enqueued_actions_into_instructions(files_table, local_adds_chgs_deletes_queue, args.absolute_local_root_path)
                # Actions indicated by Subversion server next, only if root revision is different
                if root_revision_on_remote_svn_repo != last_root_revision or possible_clash_encountered:
                    create_GETs_and_local_deletes_instructions_after_comparison_to_files_on_subversion_server(files_table, excluded_filename_patterns,
                                 svn_metadata_xml_elements_for(requests_session, args.remote_subversion_directory,baseline_relative_path))
                    # update_revisions_for_created_directories(requests_session, files_table, args.remote_subversion_directory, args.absolute_local_root_path)
                    last_root_revision = root_revision_on_remote_svn_repo
                transform_enqueued_actions_into_instructions(files_table, local_adds_chgs_deletes_queue, args.absolute_local_root_path)

            if to_add_chg_or_del < 200:
                sleep_a_little(args.sleep_secs)
#            print_rows(files_table)
            iteration += 1
    except KeyboardInterrupt:
        print("CTRL-C, Shutting down...")
        pass
    try:
        file_system_watcher.stop()
    except KeyError:
        pass
    is_shutting_down.append(True)
    try:
        file_system_watcher.join()
    except RuntimeError:
        pass

    debug = False

    if debug:
        print_rows(files_table)


if __name__ == "__main__":

    main(sys.argv)
    exit(0)

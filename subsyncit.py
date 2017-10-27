#!/usr/bin/env python3
#
# Subsyncit - File sync backed by Subversion
#
# Version: 2017.10.27.01.42.13.005953.UTC
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
# 1. Remote Subversion repo URL. Like - "http://127.0.0.1:8099/svn/testrepo"
# 2. Local Sync Directory (fully qualified or relative). Like /path/to/mySyncDir
# 3. Subversion user name.
#
# Optional arguments
# `--passwd` to supply the password on the command line (plain text) instead of prompting for secure entry
# `--no-verify-ssl-cert` to ignore certificate errors if you have a self-signed (say for testing)
# `--sleep-secs-between-polling` to supply a number of seconds to wait between poll of the server for changes
#
# Note: There's a database created in the Local Sync Directory called ".subsyncit.db".
# It contains one row per file that's synced back and forth. There's a field in there RV
# which is not currently used, but set to 0

import argparse
import ctypes
import datetime
import getpass
# import sqlite3
import hashlib
import json
import os
import re
import sys
import time
from os.path import dirname, splitext
from time import strftime
import threading
import requests
import requests.packages.urllib3
from boltons.setutils import IndexedSet
from requests.adapters import HTTPAdapter
from tinydb.storages import JSONStorage
from tinydb.middlewares import CachingMiddleware
from tinydb import Query, TinyDB
from watchdog.events import PatternMatchingEventHandler

PUT_ON_SERVER = "PT"
GET_FROM_SERVER = "GT"
DELETE_ON_SERVER = "DS"
DELETE_LOCALLY = "DL"
MAKE_DIR_ON_SERVER = "MK"

PROPFIND = '<?xml version="1.0" encoding="utf-8" ?>\n' \
             '<D:propfind xmlns:D="DAV:">\n' \
             '<D:prop xmlns:S="http://subversion.tigris.org/xmlns/dav/">\n' \
             '<S:sha1-checksum/>\n' \
             '<D:version-name/>\n' \
             '<S:baseline-relative-path/>\n' \
             '</D:prop>\n' \
             '</D:propfind>\n'


def debug(message):
    print(strftime('%Y-%m-%d %H:%M:%S') + ": " + message)


def section_end(should_prnt, message, start):
    duration = time.time() - start
    if should_prnt or duration > 1:
        debug(("[SECTION] " + message) %english_duration(duration))


def my_trace(lvl, message):
    # pass
    if lvl == 1:
        debug("TRACE " + message)
    # if lvl == 2:
    #     debug("TRACE " + message)


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


class MyRequestsTracer():

    def __init__(self, delegate):
        self.delegate = delegate
        self.always_print = False
        self.counts = {
            "mkcol": 0,
            "put": 0,
            "get": 0,
            "delete": 0
        }


    def anything_happened(self):
        return self.counts["mkcol"] > 0 or self.counts["put"] > 0 or self.counts["get"] > 0 or self.counts["delete"] > 0


    def clear_counts(self):
        self.counts["mkcol"] = 0
        self.counts["put"] = 0
        self.counts["get"] = 0
        self.counts["delete"] = 0

    def mkcol(self, arg0):
        start = time.time()
        status = 0
        try:
            request = self.delegate.request("MKCOL", arg0)
            status = request.status_code
            return request
        finally:
            self.counts["mkcol"] += 1
            durn = time.time() - start
            if durn > 1 or self.always_print:
                debug("Requests.MKCOL: [" + str(status) + "] " + str(arg0) + " " + english_duration(durn))


    def delete(self, arg0):
        start = time.time()
        status = 0
        try:
            request = self.delegate.delete(arg0)
            status = request.status_code
            return request
        finally:
            self.counts["delete"] += 1
            durn = time.time() - start
            if durn > 1 or self.always_print:
                debug("Requests.DELETE: [" + str(status) + "] " + str(arg0) + " " + english_duration(durn))


    def head(self, arg0):
        start = time.time()
        status = 0
        try:
            request = self.delegate.head(arg0)
            status = request.status_code
            return request
        finally:
            durn = time.time() - start
            if durn > 0.5 or self.always_print:
                debug("Requests.HEAD: [" + str(status) + "] " + str(arg0) + " " + english_duration(durn))


    def propfind(self, arg0, data, headers=None):
        start = time.time()
        status = 0
        try:
            request = self.delegate.request("PROPFIND", arg0, data=data, headers=headers)
            status = request.status_code
            return request
        finally:
            durn = time.time() - start
            if durn > 1 or self.always_print:
                debug("Requests.PROPFIND: [" + str(status) + "] " + str(arg0) + " <that propfind xml/> " + str(headers) + " " + english_duration(durn))


    def put(self, arg0, data=None):
        start = time.time()
        status = 0
        try:
            request = self.delegate.put(arg0, data=data)
            status = request.status_code
            return request
        finally:
            self.counts["put"] += 1
            durn = time.time() - start
            if durn > 1 or self.always_print:
                debug("Requests.PUT: [" + str(status) + "] " + str(arg0) + " " + self.data_print(data) + " " + english_duration(durn))

    def data_print(self, data):
        return str("data.len=" + str(len(data)) if len(data) > 15 else "data=" + str(data))

    def get(self, arg0, stream=None):
        start = time.time()
        status = 0
        try:
            request = self.delegate.get(arg0, stream=stream)
            status = request.status_code
            return request
        finally:
            self.counts["get"] += 1
            durn = time.time() - start
            if durn > 1 or self.always_print:
                debug("Requests.GET: [" + str(status) + "] " + str(arg0) + " " + str(stream) + " " + english_duration(durn))


    def options(self, arg0, data=None):
        start = time.time()
        status = 0
        try:
            request = self.delegate.request('OPTIONS', arg0, data=data)
            status = request.status_code
            return request
        finally:
            durn = time.time() - start
            if durn > .5 or self.always_print:
                debug("Requests.OPTIONS: [" + str(status) + "] " + str(arg0) + " " + self.data_print(data) + " " + english_duration(durn))


    def report(self, arg0, youngest_rev):
        start = time.time()
        status = 0
        try:
            request = self.delegate.request('REPORT', arg0, data='<S:log-report xmlns:S="svn:"><S:start-revision>' + youngest_rev +
                                   '</S:start-revision><S:end-revision>0</S:end-revision><S:limit>1</S:limit><S:revprop>svn:author</S:revprop><S'
                                   ':revprop>svn:date</S:revprop><S:revprop>svn:log</S:revprop><S:path></S:path><S:encode-binary-props/></S:log-report>')
            status = request.status_code
            return request
        finally:
            durn = time.time() - start
            if durn > .5 or self.always_print:
                debug("Requests.REPORT: [" + str(status) + "] " + str(arg0) + " youngest_rev=" + str(youngest_rev) + " " + english_duration(durn))


class MyTinyDBTrace():

    def __init__(self, delegate):
        self.delegate = delegate
        self.always_print = False

    def search(self, arg0):
        start = time.time()
        result = ""
        try:
            search = self.delegate.search(arg0)
            result = "✘" if not search else "rows=" + str(len(search))
            return search
        finally:
            durn = time.time() - start
            if durn > .01 or self.always_print:
                debug("TinyDB.search: [" + result + "] " + str(arg0) + " " + english_duration(durn))

    def get(self, arg0):
        start = time.time()
        result = ""
        get = None
        try:
            get = self.delegate.get(arg0)
            result = "✘" if not get else "✔"
            return get
        finally:
            durn = time.time() - start
            if durn > .01 or self.always_print:
                debug("TinyDB.get: [" + result + "] " + str(arg0) + " " + english_duration(durn) + " " + str(get))

    def remove(self, arg0):
        start = time.time()
        result = ""
        try:
            remove = self.delegate.remove(arg0)
            result = "✘" if not remove else "✔"
            return remove
        finally:
            durn = time.time() - start
            if durn > .01 or self.always_print:
                debug("TinyDBremove: [" + result + "] " + str(arg0) + " " + english_duration(durn))

    def update(self, arg0, arg1):
        start = time.time()
        result = ""
        try:
            update = self.delegate.update(arg0, arg1)
            result = "✘" if not update else "✔"
            return update
        finally:
            durn = time.time() - start
            if durn > .01 or self.always_print:
                debug("TinyDB.update: [" + result + "] " + str(arg0) + " " + str(arg1) + " " + english_duration(durn))

    def insert(self, arg0):
        start = time.time()
        result = ""
        try:
            insert = self.delegate.insert(arg0)
            result = "✘" if not insert else "✔"
            return insert
        finally:
            durn = time.time() - start
            if durn > .01 or self.always_print:
                debug("TinyDB.insert: [" + result + "] " + str(arg0) + " " + english_duration(durn))

    def contains(self, arg0):
        start = time.time()
        result = ""
        try:
            contains = self.delegate.contains(arg0)
            result = "✘" if not contains else "✔"
            return contains
        finally:
            durn = time.time() - start
            if durn > .01 or self.always_print:
                debug("TinyDB.contains: [" + result + "] " + str(arg0) + " " + english_duration(durn))

    def all(self):
        start = time.time()
        result = ""
        try:
            all = self.delegate.all()
            result = "✘" if not all else "rows=" + str(len(all))
            return all
        finally:
            durn = time.time() - start
            if durn > .01 or self.always_print:
                debug("TinyDB.all: [" + result + "] " + english_duration(durn))


class UnexpectedStatusCode(Exception):

    def __init__(self, status_code):
        self.message = " status code:" +  str(status_code)


class NoConnection(Exception):

    def __init__(self, msg):
        self.message = msg


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
        if relative_file_name == "subsyncit.stop":
            self.stop_subsyncit(event)
            return
        if should_be_excluded(relative_file_name, self.excluded_filename_patterns):
            return

        # print("on_add: " + relative_file_name)
        self.local_adds_chgs_deletes_queue.add((relative_file_name, "add_" + ("dir" if event.is_directory else "file")))

    def stop_subsyncit(self, event):
        self.file_system_watcher.stop()
        self.is_shutting_down.append(True)
        try:
            self.file_system_watcher.join()
            os.remove(event.src_path)
        except RuntimeError:
            pass
        except OSError:
            pass

    def on_deleted(self, event):
        relative_file_name = get_relative_file_name(event.src_path, self.absolute_local_root_path)
        if should_be_excluded(relative_file_name, self.excluded_filename_patterns):
            return
        # print("on_del: " + relative_file_name)
        self.local_adds_chgs_deletes_queue.add((relative_file_name, "delete"))

    def on_modified(self, event):
        relative_file_name = get_relative_file_name(event.src_path, self.absolute_local_root_path)
        if relative_file_name == "subsyncit.stop":
            self.stop_subsyncit(event)
            return
        if should_be_excluded(relative_file_name, self.excluded_filename_patterns):
            return
        if not event.is_directory and not event.src_path.endswith(self.absolute_local_root_path):
            add_queued = (relative_file_name, "add_file") in self.local_adds_chgs_deletes_queue
            chg_queued = (relative_file_name, "change") in self.local_adds_chgs_deletes_queue
            if not add_queued and not chg_queued:
                self.local_adds_chgs_deletes_queue.add((relative_file_name, "change"))


    def update_excluded_filename_patterns(self, excluded_filename_patterns):
        self.excluded_filename_patterns = excluded_filename_patterns

def should_be_excluded(relative_file_name, excluded_filename_patterns):

    basename = os.path.basename(relative_file_name)

    if basename.startswith(".") \
           or relative_file_name == "subsyncit.stop" \
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


def make_remote_subversion_directory_and_return_revision(requests_session, dir, remote_subversion_directory, baseline_relative_path, repo_parent_path):
    request = requests_session.mkcol(remote_subversion_directory + dir.replace(os.sep, "/"))
    rc = request.status_code
    if rc == 201:
        return get_revision_for_remote_directory(requests_session, remote_subversion_directory, dir.replace(os.sep, "/"), baseline_relative_path, repo_parent_path)
    raise BaseException("Unexpected return code " + str(rc) + " for " + dir)


def esc(name):
    return name.replace("?", "%3F").replace("&", "%26")


def make_directories_if_missing_in_db(files_table, dname, requests_session, remote_subversion_directory, baseline_relative_path, repo_parent_path):

    dirs_made = 0
    if dname == "":
        return 0
    dir = files_table.get(Query().RFN == dname)

    if not dir or dir['RV'] == 0:
        parentname = dirname(dname)
        if parentname != "":
            parent = files_table.get(Query().RFN == parentname)
            if not parent or parent['RV'] == 0:
                dirs_made += make_directories_if_missing_in_db(files_table, parentname, requests_session, remote_subversion_directory, baseline_relative_path, repo_parent_path)

    if not dir:
        make_directories_if_missing_in_db(files_table, dirname(dname), requests_session, remote_subversion_directory, baseline_relative_path, repo_parent_path)
        dirs_made += 1
        dir = {'RFN': dname,
               'F': "0",
               'RS': None,
               'LS': None,
               'ST': 0,
               'I': None,
               'RV': make_remote_subversion_directory_and_return_revision(requests_session, dname, remote_subversion_directory, baseline_relative_path, repo_parent_path)
               }
        files_table.insert(dir)
    elif dir['RV'] == 0:
        dirs_made += 1
        files_table.update(
            {
                'I': None,
                'RV': make_remote_subversion_directory_and_return_revision(requests_session, dname, remote_subversion_directory, baseline_relative_path, repo_parent_path)
            },
            Query().RFN == dname)
    return dirs_made


def put_item_in_remote_subversion_directory(requests_session, abs_local_file_path, remote_subversion_directory, absolute_local_root_path, files_table, alleged_remote_sha1, baseline_relative_path,
                                            repo_parent_path, db_dir):
    dirs_made = 0
    s1 = os.path.getsize(abs_local_file_path)
    time.sleep(0.1)
    s2 = os.path.getsize(abs_local_file_path)
    if s1 != s2:
        raise NotPUTtingAsFileStillBeingWrittenTo(abs_local_file_path)
    relative_file_name = get_relative_file_name(abs_local_file_path, absolute_local_root_path)

    dirs_made += make_directories_if_missing_in_db(files_table, dirname(relative_file_name), requests_session, remote_subversion_directory, baseline_relative_path, repo_parent_path)

    if alleged_remote_sha1:
        (ver, actual_remote_sha1, not_used_here) = get_remote_subversion_server_revision_for(requests_session, remote_subversion_directory, relative_file_name, db_dir)
        if actual_remote_sha1 and actual_remote_sha1 != alleged_remote_sha1:
            raise NotPUTtingAsItWasChangedOnTheServerByAnotherUser() # force into clash scenario later

    # TODO has it changed on server
    with open(abs_local_file_path, "rb") as f:
        put = requests_session.put(remote_subversion_directory + esc(relative_file_name).replace(os.sep, "/"), data=f.read())
        output = put.text
        if put.status_code != 201 and put.status_code != 204:
            raise NotPUTtingAsTheServerObjected(put.status_code, output)
    return dirs_made


def create_GETs_and_local_deletes_instructions_after_comparison_to_files_on_subversion_server(files_table, excluded_filename_patterns, files_on_svn_server, requests_session,
                                                                                              remote_subversion_directory, baseline_relative_path, repo_parent_path):

    my_trace(2, " ---> create_GETs_and_local_deletes_instructions_after_comparison_to_files_on_subversion_server - start")

    start = time.time()
    unprocessed_files = {}

    rows = files_table.search(Query().I == None)
    for row in rows:
        relative_file_name = row['RFN']
        if not should_be_excluded(relative_file_name, excluded_filename_patterns):
            unprocessed_files[relative_file_name] = {
                "I" : row["I"],
                "RS" : row['RS']
            }

    my_trace(2,  " done populating initial unprocessed files" )

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
            if match["I"] != None:
                continue
            if not match['RS'] == sha1:
                get_count += 1
                update_instruction_in_table(files_table, GET_FROM_SERVER, relative_file_name)
        else:
            get_count += 1
            dir_or_file = "dir" if sha1 is None else "file"
            if dir_or_file == '0':
                rev = get_revision_for_remote_directory(requests_session, remote_subversion_directory, relative_file_name, baseline_relative_path, repo_parent_path)
            upsert_row_in_table(files_table, relative_file_name, rev, dir_or_file, instruction=GET_FROM_SERVER)

    my_trace(2,  " done iterating over files_on_svn_server")

    # files still in the unprocessed_files list are not up on Subversion
    for relative_file_name, val in unprocessed_files.items():
        local_deletes += 1
        update_instruction_in_table(files_table, 'DL', relative_file_name)

    section_end(get_count > 0 or local_deletes > 0,  "Instructions created for " + str(get_count) + " GETs and " + str(local_deletes)
          + " local deletes (comparison of all the files on the Subversion server to files in the sync dir) took %s.", start)

    my_trace(2,  " ---> create_GETs_and_local_deletes_instructions_after_comparison_to_files_on_subversion_server - end")


def english_duration(duration):
    if duration < .001:
        return str(round(duration*1000000)) + " ns"
    if duration < 1:
        return str(round(duration*1000, 1)) + " ms"
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


def get_revision_for_remote_directory(requests_session, remote_subversion_directory, relative_file_name, baseline_relative_path, repo_parent_path):

    options = requests_session.options(remote_subversion_directory + esc(relative_file_name),
                               data='<?xml version="1.0" encoding="utf-8"?><D:options xmlns:D="DAV:"><D:activity-collection-set></D:activity-collection-set></D:options>')

    if options.status_code != 200:
        raise UnexpectedStatusCode(options.status_code)

    youngest_rev = options.headers["SVN-Youngest-Rev"].strip()

    path = "!svn/rvr/" + youngest_rev + "/" + baseline_relative_path
    propfind = requests_session.propfind(remote_subversion_directory.replace(repo_parent_path + baseline_relative_path, repo_parent_path + path, 1)
                                         + relative_file_name,
                                         data='<?xml version="1.0" encoding="utf-8"?>'
                                              '<propfind xmlns="DAV:">'
                                              '<prop>'
                                              '<version-name/>'
                                              '</prop>'
                                              '</propfind>')

    content = propfind.content.decode("utf-8")

    if propfind.status_code != 207:
        raise UnexpectedStatusCode(options.status_code)

    i = int(str([line for line in content.splitlines() if ':version-name>' in line]).split(">")[1].split("<")[0])
    return i


def perform_GETs_per_instructions(requests_session, files_table, remote_subversion_directory, absolute_local_root_path, baseline_relative_path, repo_parent_path, db_dir):

    my_trace(2,  " ---> perform_GETs_per_instructions - start")
    more_to_do = True
    batch = 0

    # Batches of 100 so that here's intermediate reporting.
    while more_to_do:
        batch += 1
        more_to_do = False
        start = time.time()
        num_rows = 0
        file_count = 0

        try:
            rows = files_table.search(Query().I == GET_FROM_SERVER)
            num_rows = len(rows)
            if len(rows) > 3:
                my_trace(2,  ": " + str(len(rows)) + " GETs to perform on remote Subversion server...")
            for row in rows:
                relative_file_name = row['RFN']
                is_file = row['F'] == "1"
                old_sha1_should_be = row['LS']
                file_count += process_GET(absolute_local_root_path, baseline_relative_path, db_dir, files_table, is_file, old_sha1_should_be, relative_file_name,
                                         remote_subversion_directory,
                                         repo_parent_path, requests_session)
        finally:

            section_end(num_rows > 0,  "Batch " + str(batch) + " of"
                     + ": GETs from Subversion server took %s: " + str(file_count)
                     + " files, and " + str(num_rows - file_count)
                     + " directories, at " + str(round(file_count / (time.time() - start) , 2)) + " files/sec.", start)

    my_trace(2,  " ---> perform_GETs_per_instructions - end")


def process_GET(absolute_local_root_path, baseline_relative_path, db_dir, files_table, is_file, old_sha1_should_be, relative_file_name, remote_subversion_directory, repo_parent_path,
                requests_session):
    file_count = 0
    abs_local_file_path = (absolute_local_root_path + relative_file_name)
    head = requests_session.head(remote_subversion_directory + esc(relative_file_name))
    if not is_file or ("Location" in head.headers and head.headers["Location"].endswith("/")):
        process_GET_of_directory(abs_local_file_path, baseline_relative_path, files_table, relative_file_name, remote_subversion_directory, repo_parent_path, requests_session)
    else:
        process_GET_of_file(abs_local_file_path, db_dir, files_table, old_sha1_should_be, relative_file_name, remote_subversion_directory, requests_session)
        file_count += 1
    update_instruction_in_table(files_table, None, relative_file_name)
    instruct_to_reGET_parent_if_there(files_table, relative_file_name)
    return file_count


def instruct_to_reGET_parent_if_there(files_table, relative_file_name):
    parent = dirname(relative_file_name)
    if parent and parent != "":
        parent_row = files_table.get(Query().RFN == parent)
        if parent_row and parent_row['I'] == None:
            update_instruction_in_table(files_table, GET_FROM_SERVER, parent)


def process_GET_of_file(abs_local_file_path, db_dir, files_table, old_sha1_should_be, relative_file_name, remote_subversion_directory, requests_session):
    (rev, sha1, baseline_relative_path_not_used) \
        = get_remote_subversion_server_revision_for(requests_session, remote_subversion_directory, relative_file_name, db_dir)
    get = requests_session.get(remote_subversion_directory + esc(relative_file_name).replace(os.sep, "/"), stream=True)
    # debug(absolute_local_root_path + relative_file_name + ": GET " + str(get.status_code) + " " + str(rev))
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
    sha1 = calculate_sha1_from_local_file(abs_local_file_path)
    osstat = os.stat(abs_local_file_path)
    size_ts = osstat.st_size + osstat.st_mtime
    update_row_shas_size_and_timestamp(files_table, relative_file_name, sha1, size_ts)
    update_row_revision(files_table, relative_file_name, rev)


def process_GET_of_directory(abs_local_file_path, baseline_relative_path, files_table, relative_file_name, remote_subversion_directory, repo_parent_path, requests_session):
    if not os.path.exists(abs_local_file_path):
        os.makedirs(abs_local_file_path)
    rv = get_revision_for_remote_directory(requests_session, remote_subversion_directory, relative_file_name, baseline_relative_path, repo_parent_path)
    update_row_revision(files_table, relative_file_name, rv)

def perform_local_deletes_per_instructions(files_table, absolute_local_root_path):

    my_trace(2,  " ---> perform_local_deletes_per_instructions - start")

    start = time.time()

    rows = files_table.search(Query().I == 'DL')

    deletes = 0
    try:
        for row in rows:
            relative_file_name = row['RFN']
            name = (absolute_local_root_path + relative_file_name)
            try:
                os.remove(name)
                deletes += 1
                files_table.remove(Query().RFN == relative_file_name)
                instruct_to_reGET_parent_if_there(files_table, relative_file_name)
            except OSError:
                # has child dirs/files - shouldn't be deleted - can be on next pass.
                continue
    finally:
        section_end(deletes > 0,  "Performing local deletes took %s.", start)

    my_trace(2,  " ---> perform_local_deletes_per_instructions - end")

def update_row_shas_size_and_timestamp(files_table, relative_file_name, sha1, size_ts):
    foo = files_table.update({'RS': sha1, 'LS': sha1, 'ST': size_ts}, Query().RFN == relative_file_name)

def prt_files_table_for(files_table, relative_file_name):
    return str(files_table.search(Query().RFN == relative_file_name))


def update_row_revision(files_table, relative_file_name, rev=0):
    files_table.update({'RV': rev}, Query().RFN == relative_file_name)

def upsert_row_in_table(files_table, relative_file_name, rev, file_or_dir, instruction):

    # print "upsert1" + prt_files_table_for(files_table, relative_file_name)
    if not files_table.contains(Query().RFN == relative_file_name):
        files_table.insert({'RFN': relative_file_name,
                            'F': "1" if file_or_dir == "file" else "0",
                            'RS': None,
                            'LS': None,
                            'ST': 0,
                            'I': instruction,
                            'RV': rev})
        return

    if instruction is not None:
        update_instruction_in_table(files_table, instruction, relative_file_name)


def update_instruction_in_table(files_table, instruction, relative_file_name):
    if instruction is not None and instruction == DELETE_ON_SERVER:

        files_table.update({'I': instruction}, Query().RFN == relative_file_name)

        # TODO LIKE

    else:

        files_table.update({'I': instruction}, Query().RFN == relative_file_name)


def get_relative_file_name(full_path, absolute_local_root_path):
    if not full_path.startswith(absolute_local_root_path):
        if not (full_path + os.sep).startswith(absolute_local_root_path):
            raise ValueError('Unexpected file/dir ' + full_path + ' not under ' + absolute_local_root_path)
    rel = full_path[len(absolute_local_root_path):]
    if rel.startswith(os.sep):
        rel = rel[1:]
    return rel

def svn_metadata_xml_elements_for(requests_session, url, baseline_relative_path):

    propfind = requests_session.propfind(url, data=PROPFIND, headers={'Depth': 'infinity'})

    output = propfind.text

    if "PROPFIND requests with a Depth of \"infinity\"" in output:
        print("'DavDepthInfinity on' needs to be enabled for the Apache instance on " \
              "the server (in httpd.conf probably). Refer to " \
              "https://github.com/subsyncit/subsyncit/wiki/Subversion-Server-Setup. " \
              "Subsyncit is refusing to run.")
        exit(1)

    entries = []; path = ""; rev = 0; sha1 = None

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
            path = ""; rev = 0; sha1 = None

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


def perform_PUTs_per_instructions(requests_session, files_table, remote_subversion_directory, baseline_relative_path, absolute_local_root_path, repo_parent_path, db_dir):

    my_trace(2,  " ---> perform_PUTs_per_instructions - start")

    possible_clash_encountered = False
    more_to_do = True
    batch = 0

    # Batches of 100 so that here's intermediate reporting.
    while more_to_do:
        batch += 1
        more_to_do = False
        start = time.time()
        num_rows = 0
        put_count = 0
        dirs_made = 0
        not_actually_changed = 0
        try:
            rows = files_table.search(Query().I == PUT_ON_SERVER)
            num_rows = len(rows)
            if len(rows) > 0:
                my_trace(2,  ": " + str(len(rows)) + " PUTs to perform on remote Subversion server...")
            for row in rows:
                rel_file_name = row['RFN']
                try:
                    abs_local_file_path = (absolute_local_root_path + rel_file_name)
                    new_local_sha1 = calculate_sha1_from_local_file(abs_local_file_path)
                    output = ""
                    # print("-new_local_sha1=" + new_local_sha1)
                    # print("-row['RS']=" + str(row['RS']))
                    # print("-row['LS']=" + str(row['LS']))
                    if new_local_sha1 == 'FILE_MISSING' or (row['RS'] == row['LS'] and row['LS'] == new_local_sha1):
                        pass
                        # files that come down as new/changed, get written to the FS trigger a file added/changed message,
                        # and superficially look like they should get pushed back to the server. If the sha1 is unchanged
                        # don't do it.

                        num_rows = num_rows -1
                        update_instruction_in_table(files_table, None, rel_file_name)
                    else:
                        dirs_made += put_item_in_remote_subversion_directory(requests_session, abs_local_file_path, remote_subversion_directory, absolute_local_root_path, files_table,
                                                                         row['RS'], baseline_relative_path, repo_parent_path, db_dir)  # <h1>Created</h1>

                        osstat = os.stat(abs_local_file_path)
                        size_ts = osstat.st_size + osstat.st_mtime
                        update_sha_and_revision_for_row(requests_session, files_table, rel_file_name, new_local_sha1, remote_subversion_directory, baseline_relative_path, size_ts)
                        instruct_to_reGET_parent_if_there(files_table, rel_file_name)
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
                    batch += 1
                    break
        finally:

            not_actually_changed_blurb = ""
            if not_actually_changed > 0:
                not_actually_changed_blurb = "(" + str(not_actually_changed) + " not actually changed; from " + str(num_rows) + " total), "

            if put_count > 0:
                speed = "taking " + english_duration(round((time.time() - start)/put_count, 2)) + " each "
            else:
                speed = " "

            dirs_made_blurb = ""
            if dirs_made > 0:
                dirs_made_blurb = "(including " + str(dirs_made) + " MKCOLs to facilitate those PUTs)"

            section_end(num_rows > 0 or put_count > 0,  "Batch " + str(batch) + " of"
                 + ": PUTs on Subversion server took %s, " + str(put_count)
                 + " PUT files, " + not_actually_changed_blurb
                 + speed + dirs_made_blurb + ".", start)

    my_trace(2,  " ---> perform_PUTs_per_instructions - end")

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
            'RV': remote_rev_num,
            'RS': remote_sha1,
            'LS': remote_sha1,
            'ST': size_ts
        }, Query().RFN == relative_file_name)

# def update_revisions_for_created_directories(requests_session, files_table, remote_subversion_directory, db_dir):
#
#     my_trace(2,  " ---> update_revisions_for_created_directories - start")
#
#     rows = files_table.search(Query().I == MAKE_DIR_ON_SERVER)
#
#     start = time.time()
#
#     for row in rows:
#         relative_file_name = row['RFN']
#         if row['RS'] :
#             update_instruction_in_table(files_table, None, relative_file_name)
#         (revn, sha1, baseline_relative_path_not_used) = get_remote_subversion_server_revision_for(requests_session, remote_subversion_directory, relative_file_name, db_dir)
#         update_row_revision(files_table, relative_file_name, rev=revn)
#         update_instruction_in_table(files_table, None, relative_file_name)
#
#     section_end(len(rows) > 0,  "MKCOLs on Subversion server took %s, " + str(len(rows))
#              + " directories, " + str(round(len(rows) / (time.time() - start), 2)) + "/sec.", start)
#
#     my_trace(2,  " ---> update_revisions_for_created_directories - end")

def perform_DELETEs_on_remote_subversion_server_per_instructions(requests_session, files_table, remote_subversion_directory):

    my_trace(2,  " ---> perform_DELETEs_on_remote_subversion_server_per_instructions - start")

    start = time.time()

    rows = files_table.search(Query().I == DELETE_ON_SERVER)

    files_deleted = 0
    directories_deleted = 0
    for row in rows:
        rfn = row['RFN']
        requests_delete = requests_session.delete(remote_subversion_directory + esc(rfn).replace(os.sep, "/"))
        output = requests_delete.text
        # debug(row['RFN'] + ": DELETE " + str(requests_delete.status_code))
        if row['F'] == 1:  # F
            files_deleted += 1
            files_table.remove(Query().RFN == row['RFN'])
        else:
            directories_deleted += 1
            files_table.remove(Query().RFN == row['RFN'])
            # TODO LIKE

        if ("\n<h1>Not Found</h1>\n" not in output) and str(output) != "":
            print(("Unexpected on_deleted output for " + row['RFN'] + " = [" + str(output) + "]"))
        instruct_to_reGET_parent_if_there(files_table, rfn)

    speed = "."
    if len(rows) > 0:
        speed = ", " + str(round((time.time() - start) / len(rows), 2)) + " secs per DELETE."

    section_end(files_deleted > 0 or directories_deleted > 0,  "DELETEs on Subversion server took %s, "
          + str(directories_deleted) + " directories and " + str(files_deleted) + " files"
          + speed, start)

    my_trace(2,  " ---> perform_DELETEs_on_remote_subversion_server_per_instructions - end")

def get_remote_subversion_server_revision_for(requests_session, remote_subversion_directory, relative_file_name, db_dir):
    ver = 0
    sha1 = None
    baseline_relative_path = ""
    content = ""
    try:
        url = remote_subversion_directory + esc(relative_file_name).replace("\\", "/")
        if url.endswith("/"):
            url = url[:-1]
        propfind = requests_session.propfind(url, data=PROPFIND, headers={'Depth': '0'})
        if 200 <= propfind.status_code <= 299:
            content = propfind.text

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
        # debug(relative_file_name + ": PROPFIND " + str(propfind.status_code) + " / " + str(sha1) + " / " + str(ver) + " " + url)
        elif propfind.status_code == 401:
            raise NoConnection(remote_subversion_directory + " is saying that the user is not authorized")
        elif propfind.status_code == 405:
            raise NoConnection(remote_subversion_directory + " is not a website that maps subversion to that URL")
        elif 400 <= propfind.status_code <= 499:
            raise NoConnection("Cannot attach to remote Subversion server. Maybe not Subversion+Apache? Or wrong userId and/or password? Or wrong subdirectory within the server? Status code: " + str(
                propfind.status_code) + ", content=" + propfind.text)
        else:
            raise NoConnection("Unexpected web error " + str(propfind.status_code) + " " + propfind.text)
    except requests.packages.urllib3.exceptions.NewConnectionError as e:
        write_error(db_dir, "NewConnectionError: "+ repr(e))
    except requests.exceptions.ConnectionError as e:
        write_error(db_dir, "ConnectionError: "+ repr(e))
    return (ver, sha1, baseline_relative_path)


def get_repo_parent_path(requests_session, remote_subversion_directory):
    url = remote_subversion_directory
    if url.endswith("/"):
        url = url[:-1]

    opts = requests_session.options(url, data='<?xml version="1.0" encoding="utf-8"?><D:options xmlns:D="DAV:"><D:activity-collection-set></D:activity-collection-set></D:options>')\
        .content.decode("utf-8")

    return str([line for line in opts.splitlines() if ':activity-collection-set>' in line]).split(">")[2].split("!svn")[0]

def write_error(db_dir, msg):
    subsyncit_err = db_dir + "subsyncit.err"
    with open(subsyncit_err, "w") as text_file:
        text_file.write(msg)
    make_hidden_on_windows_too(subsyncit_err)


def transform_enqueued_actions_into_instructions(files_table, local_adds_chgs_deletes_queue, sync_dir):

    my_trace(2,  " ---> transform_enqueued_actions_into_instructions - start")

    start = time.time()

    initial_queue_length = len(local_adds_chgs_deletes_queue)
    while len(local_adds_chgs_deletes_queue) > 0:
        (relative_file_name, action) = local_adds_chgs_deletes_queue.pop(0)
        if action == "add_dir":
            upsert_row_in_table(files_table, relative_file_name, 0, "dir", instruction=MAKE_DIR_ON_SERVER)
        elif action == "add_file":
            in_subversion = file_is_in_subversion(files_table, relative_file_name)
            # 'svn up' can add a file, causing watchdog to trigger an add notification .. to be ignored
            if not in_subversion:
                # print("File to add: " + relative_file_name + " is not in subversion")
                upsert_row_in_table(files_table, relative_file_name, 0, "file", instruction=PUT_ON_SERVER)
        elif action == "change":
            # print("File changed: " + relative_file_name + " is not in subversion")
            update_instruction_in_table(files_table, PUT_ON_SERVER, relative_file_name)
        elif action == "delete":
            in_subversion = file_is_in_subversion(files_table, relative_file_name)
            # 'svn up' can delete a file, causing watchdog to trigger a delete notification .. to be ignored
            if in_subversion:
                update_instruction_in_table(files_table, DELETE_ON_SERVER, relative_file_name)
        else:
            raise Exception("Unknown action " + action)

    section_end(len(local_adds_chgs_deletes_queue) > 0,  "Creation of instructions from " + str(initial_queue_length) + " enqueued actions took %s.", start)

    my_trace(2,  " ---> transform_enqueued_actions_into_instructions - end")


def file_is_in_subversion(files_table, relative_file_name):
    row = files_table.get(Query().RFN == relative_file_name)
    return False if not row else row['RS'] != None


def print_rows(files_table):
    files_table_all = sorted(files_table.all(), key=lambda k: k['RFN'])
    if len(files_table_all) > 0:
        print("All Items, as per 'files' table:")
        print("  RFN, 0=dir or 1=file, rev, remote sha1, local sha1, size + timestamp, instruction")
        for row in files_table_all:
            print(("  " + row['RFN'] + ", " + str(row['F']) + ", " + str(row['RV']) + ", " +
                  str(row['RS']) + ", " + str(row['LS']) + ", " + str(row['ST']) + ", " + str(row['I'])))


def scantree(path):
    for entry in os.scandir(path):
        if entry.is_dir(follow_symlinks=False):
            yield from scantree(entry.path)
        else:
            yield entry


def enqueue_any_missed_adds_and_changes(is_shutting_down, files_table, local_adds_chgs_deletes_queue, absolute_local_root_path, excluded_filename_patterns, last_scanned):

    my_trace(2,  " ---> enqueue_any_missed_adds_and_changes - start")

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

        row = files_table.get(Query().RFN == relative_file_name)
        in_subversion = row and row['RS'] != None
        if row and row['I'] != None: # or row['F'] == "1")
            continue
        if not in_subversion:
            add_queued = (relative_file_name, "add_file") in local_adds_chgs_deletes_queue
            if not add_queued:
                local_adds_chgs_deletes_queue.add((relative_file_name, "add_file"))
                to_add += 1
        else:
            size_ts = entry.stat().st_size + entry.stat().st_mtime
            if size_ts != row["ST"]:
                # This is speculative, logic further on will not PUT the file up if the SHA
                # is unchanged, but file_size + time_stamp change is approximate but far quicker
                add_queued = (relative_file_name, "add_file") in local_adds_chgs_deletes_queue
                chg_queued = (relative_file_name, "change") in local_adds_chgs_deletes_queue
                if not add_queued and not chg_queued:
                    local_adds_chgs_deletes_queue.add((relative_file_name, "change"))
                    to_change += 1

    section_end(to_change > 0 or to_add > 0,  "File system scan for extra PUTs: " + str(to_add) + " missed adds and " + str(to_change)
          + " missed changes (added/changed while Subsyncit was not running or somehow missed the attention of the file-system watcher) took %s.", start)

    my_trace(2,  " ---> enqueue_any_missed_adds_and_changes - end")

    return to_add + to_change

def enqueue_any_missed_deletes(is_shutting_down, files_table, local_adds_chgs_deletes_queue, absolute_local_root_path, last_scanned_path):

    my_trace(2,  " ---> enqueue_any_missed_deletes - start")

    start = time.time()
    to_delete = 0

    file = Query()
    for row in files_table.search((file.I == None) & (file.RS != None)):
        if True in is_shutting_down:
            break
        if to_delete > 100:
            break

        relative_file_name = row['RFN']
        relative_file_name = relative_file_name
        if not os.path.exists(absolute_local_root_path + relative_file_name):
            to_delete += 1
            print("missed delete " + relative_file_name + " " + str(row))
            local_adds_chgs_deletes_queue.add((relative_file_name, "delete"))

    section_end(to_delete > 0,  ": " + str(to_delete)
             + " extra DELETEs (deleted locally while Subsyncit was not running or somehow missed the attention of the file-system watcher) took %s.", start)

    my_trace(2,  " ---> enqueue_any_missed_deletes - end")

    return to_delete


def should_subsynct_keep_going(file_system_watcher, absolute_local_root_path):
    if not file_system_watcher.is_alive():
        return False
    fn = absolute_local_root_path + "subsyncit.stop"
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
            lines = get.text.splitlines()
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
    return MyRequestsTracer(requests_session)


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
        auth = (args.user, getpass.getpass(prompt="Subverison password for " + args.user + ": "))

    elif args.passwd == "*NONE":
        auth = None
    else:
        auth = (args.user, args.passwd)

    args.absolute_local_root_path = os.path.abspath(args.local_root_path.replace("/", os.sep) \
                         .replace("\\", os.sep).replace(os.sep+os.sep, os.sep))

    if not args.absolute_local_root_path.endswith(os.sep):
        args.absolute_local_root_path += os.sep

    fn = args.absolute_local_root_path + os.sep + "subsyncit.stop"
    if os.path.isfile(fn):
        try:
            os.remove(fn)
        except OSError:
            pass

    if not str(args.remote_subversion_directory).endswith("/"):
        args.remote_subversion_directory += "/"

    verifySetting = True

    if not args.verify_ssl_cert:
        requests.packages.urllib3.disable_warnings()
        verifySetting = args.verify_ssl_cert

    subsyncit_settings_dir = home_dir + os.sep + ".subsyncit"
    if not os.path.exists(subsyncit_settings_dir):
        os.mkdir(subsyncit_settings_dir)
    make_hidden_on_windows_too(subsyncit_settings_dir)

    db_dir = subsyncit_settings_dir + os.sep + args.absolute_local_root_path.replace("/","%47").replace(":","%58").replace("\\","%92") + "/"

    if not os.path.exists(db_dir):
        os.mkdir(db_dir)

    db = TinyDB(db_dir + os.sep + "subsyncit.db", storage=CachingMiddleware(JSONStorage))
    files_table  = MyTinyDBTrace(db.table('files'))

    with open(db_dir + os.sep + "INFO.TXT", "w") as text_file:
        text_file.write(args.absolute_local_root_path + "is the Subsyncit path that this pertains to")

    local_adds_chgs_deletes_queue = IndexedSet()

    last_root_revision = None
    repo_parent_path = ""
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
    file_system_watcher.daemon = True
    file_system_watcher.start()

    status = {
        "online": False
    }
    last_status_str = ""

    iteration = 0
    excluded_filename_patterns = ["hi*"]
    last_scanned = 0

    try:
        while should_subsynct_keep_going(file_system_watcher, args.absolute_local_root_path):

            # recreating this per iteration is good given use could be changing connection to the
            # internet as they move around (office, home, wifi, 3G)
            requests_session = make_requests_session(auth, verifySetting)

            (root_revision_on_remote_svn_repo, sha1, baseline_relative_path) = \
                get_remote_subversion_server_revision_for(requests_session, args.remote_subversion_directory, "", db_dir) # root


            if root_revision_on_remote_svn_repo > 0:

                try:
                    status['online'] = True
                    repo_parent_path = get_repo_parent_path(requests_session, args.remote_subversion_directory)

                    if root_revision_on_remote_svn_repo != None:
                        if iteration == 0: # At boot time only for now
                            excluded_filename_patterns = get_excluded_filename_patterns(requests_session, args.remote_subversion_directory)
                            notification_handler.update_excluded_filename_patterns(excluded_filename_patterns)

                        scan_start_time = int(time.time())

                        last_scanned = get_last_scanned_if_needed(db_dir, last_scanned)

                        to_add_chg_or_del =  enqueue_any_missed_adds_and_changes(is_shutting_down, files_table, local_adds_chgs_deletes_queue, args.absolute_local_root_path, excluded_filename_patterns, last_scanned) \
                                           + enqueue_any_missed_deletes(is_shutting_down, files_table, local_adds_chgs_deletes_queue, args.absolute_local_root_path, last_scanned)

                        update_last_scanned_if_needed(db_dir, scan_start_time, to_add_chg_or_del)

                        # Act on existing instructions (if any)
                        transform_enqueued_actions_into_instructions(files_table, local_adds_chgs_deletes_queue, args.absolute_local_root_path)
                        perform_GETs_per_instructions(requests_session, files_table, args.remote_subversion_directory, args.absolute_local_root_path, baseline_relative_path,
                                                                  repo_parent_path, db_dir)
                        transform_enqueued_actions_into_instructions(files_table, local_adds_chgs_deletes_queue, args.absolute_local_root_path)
                        perform_local_deletes_per_instructions(files_table, args.absolute_local_root_path)
                        transform_enqueued_actions_into_instructions(files_table, local_adds_chgs_deletes_queue, args.absolute_local_root_path)
                        possible_clash_encountered = perform_PUTs_per_instructions(requests_session, files_table, args.remote_subversion_directory, baseline_relative_path,
                                                                                   args.absolute_local_root_path, repo_parent_path, db_dir)
                        transform_enqueued_actions_into_instructions(files_table, local_adds_chgs_deletes_queue, args.absolute_local_root_path)
                        perform_DELETEs_on_remote_subversion_server_per_instructions(requests_session, files_table, args.remote_subversion_directory)
                        transform_enqueued_actions_into_instructions(files_table, local_adds_chgs_deletes_queue, args.absolute_local_root_path)
                        # Actions indicated by Subversion server next, only if root revision is different
                        if root_revision_on_remote_svn_repo != last_root_revision or possible_clash_encountered:
                            create_GETs_and_local_deletes_instructions_after_comparison_to_files_on_subversion_server(files_table, excluded_filename_patterns,
                                         svn_metadata_xml_elements_for(requests_session, args.remote_subversion_directory,baseline_relative_path), requests_session, args.remote_subversion_directory,
                                                                                                                      baseline_relative_path, repo_parent_path)
                            # update_revisions_for_created_directories(requests_session, files_table, args.remote_subversion_directory, db_dir)
                            last_root_revision = root_revision_on_remote_svn_repo
                        transform_enqueued_actions_into_instructions(files_table, local_adds_chgs_deletes_queue, args.absolute_local_root_path)
                except requests.packages.urllib3.exceptions.NewConnectionError as e:
                    write_error(db_dir, "NewConnectionError: " + repr(e))
                except requests.exceptions.ConnectionError as e:
                    write_error(db_dir, "ConnectionError: " + repr(e))
            else:
                    status['online'] = False

            status_str = str(status)
            if status_str != last_status_str:
                last_status_str= status_str
                status_file = db_dir + "status.json"
                with open(status_file, "w") as text_file:
                    text_file.write(json.dumps(status))

            if not requests_session.anything_happened():
                time.sleep(args.sleep_secs)
                requests_session.clear_counts()

            iteration += 1
    except NoConnection as e:
        print ("ERROR " + db_dir)
        write_error(db_dir, e.message)
        print("Can't connect " + e.message)

    except KeyboardInterrupt:
        print("CTRL-C, Shutting down...")

    transform_enqueued_actions_into_instructions(files_table, local_adds_chgs_deletes_queue, args.absolute_local_root_path)

    try:
        file_system_watcher.stop()
    except KeyError:
        pass
    try:
        file_system_watcher.join()
    except RuntimeError:
        pass

    db.close()

    debug = False

    if debug:
        print_rows(files_table)


def update_last_scanned_if_needed(db_dir, scan_start_time, to_add_chg_or_del):
    if to_add_chg_or_del == 0:
        with open(db_dir + os.sep + "last_scanned", "w") as last_scanned_f:
            last_scanned_f.write(str(scan_start_time))


def get_last_scanned_if_needed(db_dir, last_scanned):
    if last_scanned > 0:
        return last_scanned
    last_scanned_path = db_dir + os.sep + "last_scanned"
    if not os.path.exists(last_scanned_path):
        with open(last_scanned_path, "w") as last_scanned_f:
            last_scanned_f.write("0")
    with open(last_scanned_path, "r") as last_scanned_f:
        read = last_scanned_f.read().strip()

        last_scanned = int(read)
    return last_scanned


if __name__ == "__main__":

    main(sys.argv)
    exit(0)

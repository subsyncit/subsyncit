#!/usr/bin/env python3
#
# Subsyncit - File sync backed by Subversion
#
# Version: 2017.11.02.db309d7d455c23d88120e214afddc8361b0188bb
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
#
#   1. Remote Subversion repo URL. Like - "http://127.0.0.1:8099/svn/testrepo"
#   2. Local Sync Directory (fully qualified or relative). Like /path/to/mySyncDir
#   3. Subversion user name.
#
# Optional arguments
#
#   `--passwd` to supply the password on the command line (plain text) instead of prompting for secure entry
#   `--no-verify-ssl-cert` to ignore certificate errors if you have a self-signed (say for testing)
#   `--sleep-secs-between-polling` to supply a number of seconds to wait between poll of the server for changes
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
import traceback
from os.path import dirname, splitext
from time import strftime
from urllib.parse import urlparse

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
        self.always_print = True
        self.counts = {
            "mkcol": 0,
            "put": 0,
            "get": 0,
            "delete": 0
        }


    def anything_substantial_happened(self):
        return self.counts["mkcol"] > 0 or self.counts["put"] > 0 or self.counts["get"] > 0 or self.counts["delete"] > 0


    def clear_counts(self):
        self.counts["mkcol"] = 0
        self.counts["put"] = 0
        self.counts["get"] = 0
        self.counts["delete"] = 0

    def rq_debug(self, msg):
        try:
            st = traceback.extract_stack()
            methods = []
            for ste in st:
                methods.append(ste[2])
            msg += ", stack: " + ":".join(methods[2:-2])
        finally:
            debug(msg)


    def mkcol(self, url):
        start = time.time()
        status = 0
        try:
            request = self.delegate.request("MKCOL", url)
            status = request.status_code
            return request
        finally:
            self.counts["mkcol"] += 1
            durn = time.time() - start
            if durn > 1 or self.always_print:
               self.rq_debug("R.MKCOL   : [" + str(status) + "] " + urlparse(url).path + " " + english_duration(durn))


    def delete(self, url):
        start = time.time()
        status = 0
        try:
            request = self.delegate.delete(url)
            status = request.status_code
            return request
        finally:
            self.counts["delete"] += 1
            durn = time.time() - start
            if durn > 1 or self.always_print:
                self.rq_debug("R.DELETE  : [" + str(status) + "] " +  urlparse(url).path + " " + english_duration(durn))


    def head(self, url):
        start = time.time()
        status = 0
        try:
            request = self.delegate.head(url)
            status = request.status_code
            return request
        finally:
            durn = time.time() - start
            if durn > 0.5 or self.always_print:
                self.rq_debug("R.HEAD    : [" + str(status) + "] " +  urlparse(url).path + " " + english_duration(durn))


    def propfind(self, url, depth=1):
        start = time.time()
        status = 0
        try:
            request = self.delegate.request("PROPFIND", url, data='<?xml version="1.0" encoding="utf-8" ?>\n' \
             '<D:propfind xmlns:D="DAV:">\n' \
             '<D:prop xmlns:S="http://subversion.tigris.org/xmlns/dav/">\n' \
             '<S:sha1-checksum/>\n' \
             '<D:version-name/>\n' \
             '<S:baseline-relative-path/>\n' \
             '</D:prop>\n' \
             '</D:propfind>\n', headers={'Depth': str(depth)})
            status = request.status_code
            return request
        finally:
            durn = time.time() - start
            if durn > 1 or self.always_print:
                self.rq_debug("R.PROPFIND: [" + str(status) + "] " +  urlparse(url).path + " depth=" + str(depth) + " " + english_duration(durn))


    def put(self, url, data=None):
        start = time.time()
        status = 0
        try:
            request = self.delegate.put(url, data=data)
            status = request.status_code
            return request
        finally:
            self.counts["put"] += 1
            durn = time.time() - start
            if durn > 1 or self.always_print:
                self.rq_debug("R.PUT     : [" + str(status) + "] " +  urlparse(url).path + " " + self.data_print(data) + " " + english_duration(durn))


    def data_print(self, data):
        return str("data.len=" + str(len(data)) if len(data) > 15 else "data=" + str(data))


    def get(self, url, stream=None):
        start = time.time()
        status = 0
        try:
            request = self.delegate.get(url, stream=stream)
            status = request.status_code
            return request
        finally:
            self.counts["get"] += 1
            durn = time.time() - start
            if durn > 1 or self.always_print:
                self.rq_debug("R.GET     : [" + str(status) + "] " +  urlparse(url).path + " " + str(stream) + " " + english_duration(durn))


    def options(self, url, data=None):
        start = time.time()
        status = 0
        try:
            request = self.delegate.request('OPTIONS', url, data=data)
            status = request.status_code
            return request
        finally:
            durn = time.time() - start
            if durn > .5 or self.always_print:
                self.rq_debug("R.OPTIONS : [" + str(status) + "] " +  urlparse(url).path + " " + self.data_print(data) + " " + english_duration(durn))


    def svn_revision(self, config, file_name):
        start = time.time()
        status = 0
        url = ""
        try:
            options = self.delegate.request('OPTIONS', config.args.svn_url + esc(file_name),
                                               data='<?xml version="1.0" encoding="utf-8"?><D:options xmlns:D="DAV:"><D:activity-collection-set></D:activity-collection-set></D:options>')

            if options.status_code != 200:
                raise UnexpectedStatusCode(options.status_code)

            youngest_rev = options.headers["SVN-Youngest-Rev"].strip()

            url = config.args.svn_url.replace(config.svn_repo_parent_path + config.svn_baseline_rel_path, config.svn_repo_parent_path
                                              + "!svn/rvr/" + youngest_rev + "/" + config.svn_baseline_rel_path, 1)
            propfind = self.delegate.request("PROPFIND", url + file_name,
                                             data='<?xml version="1.0" encoding="utf-8"?>'
                                                      '<propfind xmlns="DAV:">'
                                                      '<prop>'
                                                      '<version-name/>'
                                                      '</prop>'
                                                      '</propfind>',
                                             headers={'Depth': '1'})

            content = propfind.text

            if propfind.status_code != 207:
                raise UnexpectedStatusCode(propfind.status_code)

            rev = int(str([line for line in content.splitlines() if ':version-name>' in line]).split(">")[1].split("<")[0])
            status = propfind.status_code
            return rev
        finally:
            durn = time.time() - start
            if durn > .5 or self.always_print:
                self.rq_debug("R.OPTSPROP: [" + str(status) + "] " +  urlparse(url).path + " " + english_duration(durn))


    def report(self, url, youngest_rev):
        start = time.time()
        status = 0
        try:
            request = self.delegate.request('REPORT', url, data='<S:log-report xmlns:S="svn:"><S:start-revision>' + youngest_rev +
                                   '</S:start-revision><S:end-revision>0</S:end-revision><S:limit>1</S:limit><S:revprop>svn:author</S:revprop><S'
                                   ':revprop>svn:date</S:revprop><S:revprop>svn:log</S:revprop><S:path></S:path><S:encode-binary-props/></S:log-report>')
            status = request.status_code
            return request
        finally:
            durn = time.time() - start
            if durn > .5 or self.always_print:
                self.rq_debug("R.REPORT  : [" + str(status) + "] " +  urlparse(url).path + " youngest_rev=" + str(youngest_rev) + " " + english_duration(durn))


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


class Config(object):

    def __init__(self):
        self.args = None
        self.db_dir = None
        self.files_table = None
        self.svn_baseline_rel_path = None
        self.svn_repo_parent_path = None


class State(object):

    def __init__(self, db_dir):
        self.online = False
        self.is_shutting_down = False
        self.db_dir = db_dir
        self.iteration = 0
        self.last_scanned = 0
        self.last_root_revision = 0
        self.previously = ""

    def __str__(self):
        return "online: " + str(self.online) + ", last_scanned: " + str(self.last_scanned)

    def toJSON(self):
        strftime('%Y-%m-%d %H:%M:%S')
        return '{"online": ' + str(self.online).lower() + ', "last_scanned": "' + strftime('%Y-%m-%d %H:%M:%S', time.localtime(self.last_scanned)) + '", "iteration": ' + str(self.iteration) + '}'

    def save_if_changed(self):
        self.iteration += 1
        json = self.toJSON()
        if json != self.previously:
            with open(self.db_dir + "status.json", "w") as text_file:
                text_file.write(json)


class ExcludedPatternNames(object):

    def __init__(self):
        self.regexes = []

    def update_exclusions(self, config, requests_session):
        try:
            get = requests_session.get(config.args.svn_url + ".subsyncit-excluded-filename-patterns")
            if (get.status_code == 200):
                lines = get.text.splitlines()
                regexes = []
                for line in lines:
                    regexes.append(re.compile(line))
                self.regexes = regexes
        except requests.exceptions.ConnectionError as e:
            pass
            # leave as is

    def should_be_excluded(self, file_name):

        basename = os.path.basename(file_name)

        if basename.startswith(".") \
               or file_name == "subsyncit.stop" \
               or len(file_name) == 0 \
               or ".clash_" in file_name:
            return True

        for pattern in self.regexes:
            if pattern.search(basename):
                return True

        return False


class FileSystemNotificationHandler(PatternMatchingEventHandler):

    def __init__(self, local_adds_chgs_deletes_queue, config, file_system_watcher, state, excluded_patterns):
        super(FileSystemNotificationHandler, self).__init__(ignore_patterns=["*/.*"])
        self.state = state
        self.local_adds_chgs_deletes_queue = local_adds_chgs_deletes_queue
        self.config = config
        self.file_system_watcher = file_system_watcher
        self.excluded_filename_patterns = excluded_patterns

    def on_created(self, event):
        file_name = get_file_name(self.config, event.src_path)
        if file_name == "subsyncit.stop":
            self.stop_subsyncit(event)
            return
        if self.excluded_filename_patterns.should_be_excluded(file_name):
            return

        self.local_adds_chgs_deletes_queue.add((file_name, "add_" + ("dir" if event.is_directory else "file")))

    def stop_subsyncit(self, event):
        self.file_system_watcher.stop()
        self.state.is_shutting_down = True
        try:
            self.file_system_watcher.join()
            os.remove(event.src_path)
        except RuntimeError:
            pass
        except OSError:
            pass

    def on_deleted(self, event):
        file_name = get_file_name(self.config, event.src_path)
        if self.excluded_filename_patterns.should_be_excluded(file_name):
            return
        self.local_adds_chgs_deletes_queue.add((file_name, "delete"))

    def on_modified(self, event):
        file_name = get_file_name(self.config, event.src_path)
        if file_name == "subsyncit.stop":
            self.stop_subsyncit(event)
            return
        if self.excluded_filename_patterns.should_be_excluded(file_name):
            return
        if not event.is_directory and not event.src_path.endswith(self.config.args.absolute_local_root_path):
            add_queued = (file_name, "add_file") in self.local_adds_chgs_deletes_queue
            chg_queued = (file_name, "change") in self.local_adds_chgs_deletes_queue
            if not add_queued and not chg_queued:
                self.local_adds_chgs_deletes_queue.add((file_name, "change"))


def get_suffix(file_name):
    file_name, extension = splitext(file_name)
    return extension


def svn_MKCOL(requests_session, dir, config):
    request = requests_session.mkcol(config.args.svn_url + dir.replace(os.sep, "/"))
    rc = request.status_code
    if rc == 201:
        return requests_session.svn_revision(config, dir.replace(os.sep, "/"))
    raise BaseException("Unexpected return code " + str(rc) + " for " + dir)


def esc(name):
    return name.replace("?", "%3F").replace("&", "%26")


def make_directories_if_missing_in_db(config, dname, requests_session):

    dirs_made = 0
    if dname == "":
        return 0
    dir = config.files_table.get(Query().FN == dname)

    if not dir or dir['RV'] == 0:
        parentname = dirname(dname)
        if parentname != "":
            parent = config.files_table.get(Query().FN == parentname)
            if not parent or parent['RV'] == 0:
                dirs_made += make_directories_if_missing_in_db(config, parentname, requests_session)

    if not dir:
        make_directories_if_missing_in_db(config, dirname(dname), requests_session)
        dirs_made += 1
        print ("x TYPE: " + dname)
        dir = {'FN': dname,
               'L': dname.count(os.sep),
               'T': 'D',
               'RS': None,
               'LS': None,
               'ST': 0,
               'I': None,
               'RV': svn_MKCOL(requests_session, dname, config)
               }
        config.files_table.insert(dir)
    elif dir['RV'] == 0:
        dirs_made += 1
        config.files_table.update(
            {
                'I': None,
                'RV': svn_MKCOL(requests_session, dname, config)
            },
            Query().FN == dname)
    return dirs_made


def PUT_file(config, requests_session, abs_local_file_path, alleged_remote_sha1):
    dirs_made = 0
    s1 = os.path.getsize(abs_local_file_path)
    time.sleep(0.1)
    s2 = os.path.getsize(abs_local_file_path)
    if s1 != s2:
        raise NotPUTtingAsFileStillBeingWrittenTo(abs_local_file_path)
    file_name = get_file_name(config, abs_local_file_path)

    dirs_made += make_directories_if_missing_in_db(config, dirname(file_name), requests_session)

    if alleged_remote_sha1:
        (ver, actual_remote_sha1, not_used_here) = svn_details(config, requests_session, file_name)
        if actual_remote_sha1 and actual_remote_sha1 != alleged_remote_sha1:
            raise NotPUTtingAsItWasChangedOnTheServerByAnotherUser() # force into clash scenario later

    # TODO has it changed on server
    with open(abs_local_file_path, "rb") as f:
        put = requests_session.put(config.args.svn_url + esc(file_name).replace(os.sep, "/"), data=f.read())
        output = put.text
        if put.status_code != 201 and put.status_code != 204:
            raise NotPUTtingAsTheServerObjected(put.status_code, output)
    return dirs_made


def create_GET_and_local_delete_instructions_if_needed(config, excluded_filename_patterns, files_on_svn_server, directory):

    my_trace(2, " ---> create_GETs_and_local_deletes_instructions_after_comparison_to_files_on_subversion_server - start")

    prefix_dir_count = directory.count(os.sep)

    start = time.time()
    unprocessed_files = {}

    rows = config.files_table.search(Query().I == None) # TODO - should mask out Instructed ones??
    for row in rows:
        file_name = row['FN']
        if not excluded_filename_patterns.should_be_excluded(file_name)\
                and file_name.startswith(directory):  # perhaps would faster if inside the where clause

            if file_name.count(os.sep) - prefix_dir_count > 0:
                continue
                     # ^ this directory not sub-directories

            unprocessed_files[file_name] = {
                "I" : row["I"],
                "T" : row["T"],
                "RS" : row['RS']
            }

    get_file_count = 0
    get_dir_count = 0
    local_deletes = 0
    for file_name, rev, sha1 in files_on_svn_server:
        if excluded_filename_patterns.should_be_excluded(file_name):
            continue
        match = None
        if file_name in unprocessed_files:
                match = unprocessed_files[file_name]
                unprocessed_files.pop(file_name)
        if match:
            if match["I"] != None:
                continue
            if not match['RS'] == sha1:
                update_instruction_in_table(config.files_table, GET_FROM_SERVER, file_name)
                if match['T'] == 'F':
                    get_file_count += 1
                else:
                    get_dir_count += 1
        else:
            upsert_row_in_table(config.files_table, file_name, 0, "D" if sha1 is None else "F", instruction=GET_FROM_SERVER)
            if sha1:
                get_file_count += 1
            else:
                get_dir_count += 1


    # files still in the unprocessed_files list are not up on Subversion
    for file_name, val in unprocessed_files.items():
        local_deletes += 1
        update_instruction_in_table(config.files_table, DELETE_LOCALLY, file_name)

    fd = str(get_file_count) + " file GETs" if get_file_count > 0 else ""
    dc = str(get_dir_count) + " dir GETs" if get_dir_count > 0 else ""
    ld = str(local_deletes) + " local deletes" if local_deletes > 0 else ""

    section_end(get_file_count > 0 or get_dir_count > 0 or local_deletes > 0,  "Instructions created for"
                + fd + dc + ld + " (comparison of the dirs/files within " + directory + ") took %s.", start)

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


def un_encode_path(file_name):
    return file_name.replace("&amp;", "&")\
        .replace("&quot;", "\"")\
        .replace("%3F", "?")\
        .replace("%26", "&")


def extract_name_type_rev(entry_xml_element):
    file_or_dir = entry_xml_element.attrib['kind']
    file_name = entry_xml_element.findtext("name")
    rev = entry_xml_element.find("commit").attrib['revision']
    return file_or_dir, file_name, rev


def svn_GETs(config, requests_session, excluded_filename_patterns):

    my_trace(2,  " ---> svn_GETs - start")
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
            rows = config.files_table.search(Query().I == GET_FROM_SERVER)
            num_rows = len(rows)
            if len(rows) > 3:
                my_trace(2,  ": " + str(len(rows)) + " GETs to perform on remote Subversion server...")
            for row in rows:
                file_name = row['FN']
                is_file = row['T'] == 'F'
                old_sha1_should_be = row['LS']
                curr_rev = row['RV']
                abs_local_file_path = (config.args.absolute_local_root_path + file_name)
                head = requests_session.head(config.args.svn_url + esc(file_name))
                if not is_file or ("Location" in head.headers and head.headers["Location"].endswith("/")):
                    GET_dir(abs_local_file_path, curr_rev, excluded_filename_patterns, file_name, config, requests_session)
                else:
                    GET_file(abs_local_file_path, config, old_sha1_should_be, file_name, requests_session)
                    file_count += 1
                update_instruction_in_table(config.files_table, None, file_name)
                instruct_to_reGET_parent_if_there(config, file_name)

        finally:

            section_end(num_rows > 0,  "Batch " + str(batch) + " of"
                     + ": GETs from Subversion server took %s: " + str(file_count)
                     + " files, and " + str(num_rows - file_count)
                     + " directories, at " + str(round(file_count / (time.time() - start) , 2)) + " files/sec.", start)

    my_trace(2,  " ---> svn_GETs - end")


def instruct_to_reGET_parent_if_there(config, file_name):
    parent = dirname(file_name)
    if parent and parent != "":
        parent_row = config.files_table.get(Query().FN == parent)
        if parent_row and parent_row['I'] == None:
            update_instruction_in_table(config.files_table, GET_FROM_SERVER, parent)


def GET_file(abs_local_file_path, config, old_sha1_should_be, file_name, requests_session):
    (rev, sha1, svn_baseline_rel_path_not_used) \
        = svn_details(config, requests_session, file_name)
    get = requests_session.get(config.args.svn_url + esc(file_name).replace(os.sep, "/"), stream=True)
    # debug(absolute_local_root_path + file_name + ": GET " + str(get.status_code) + " " + str(rev))
    # See https://github.com/requests/requests/issues/2155 - Streaming gzipped responses
    # and https://stackoverflow.com/questions/16694907/how-to-download-large-file-in-python-with-requests-py
    if os.path.exists(abs_local_file_path):
        local_sha1 = calculate_sha1_from_local_file(abs_local_file_path)
        if local_sha1 != old_sha1_should_be:
            clash_file_name = abs_local_file_path + ".clash_" + datetime.datetime.today().strftime('%Y-%m-%d-%H-%M-%S')
            os.rename(abs_local_file_path, clash_file_name)
    with open(abs_local_file_path, 'wb') as f:
        for chunk in get.iter_content(chunk_size=500000000):
            if chunk:
                f.write(chunk)
    sha1 = calculate_sha1_from_local_file(abs_local_file_path)
    try:
        osstat = os.stat(abs_local_file_path)
        size_ts = osstat.st_size + osstat.st_mtime
    except FileNotFoundError:
        size_ts = 0 # test_a_deleted_file_syncs_back stimulates this
    update_row_shas_size_and_timestamp(config.files_table, file_name, sha1, size_ts)
    update_row_revision(config.files_table, file_name, rev)


def GET_dir(abs_local_file_path, curr_local_rev, excluded_filename_patterns, file_name, config, requests_session):
    if not os.path.exists(abs_local_file_path):
        os.makedirs(abs_local_file_path)
    curr_rmt_rev = requests_session.svn_revision(config, file_name)
    if curr_local_rev != curr_rmt_rev:
        update_row_revision(config.files_table, file_name, curr_rmt_rev)
        instruct_to_reGET_parent_if_there(config, file_name)

        dir = esc(file_name) + "/"
        dir_list = svn_dir_list(config, requests_session, dir)
        create_GET_and_local_delete_instructions_if_needed(config, excluded_filename_patterns, dir_list, dir)


def local_deletes(config):

    my_trace(2,  " ---> local_deletes - start")

    start = time.time()

    rows = config.files_table.search(Query().I == DELETE_LOCALLY)

    deletes = 0
    try:
        for row in rows:
            file_name = row['FN']
            name = (config.args.absolute_local_root_path + file_name)
            try:
                os.remove(name)
                deletes += 1
                config.files_table.remove(Query().FN == file_name)
                instruct_to_reGET_parent_if_there(config, file_name)
            except OSError:
                # has child dirs/files - shouldn't be deleted - can be on next pass.
                continue
    finally:
        section_end(deletes > 0,  "Performing local deletes took %s.", start)

    my_trace(2,  " ---> local_deletes - end")

def update_row_shas_size_and_timestamp(files_table, file_name, sha1, size_ts):
    if sha1 == None:
        raise BaseException("No sha1 for " + file_name)
    files_table.update({'RS': sha1, 'LS': sha1, 'ST': size_ts}, Query().FN == file_name)

def prt_files_table_for(files_table, file_name):
    return str(files_table.search(Query().FN == file_name))


def update_row_revision(files_table, file_name, rev=0):
    files_table.update({'RV': rev}, Query().FN == file_name)

def upsert_row_in_table(files_table, file_name, rev, file_or_dir, instruction):

    # print "upsert1" + prt_files_table_for(files_table, file_name)
    if not files_table.contains(Query().FN == file_name):
        files_table.insert({'FN': file_name,
                            'L': file_name.count(os.sep),
                            'T': file_or_dir,
                            'RS': None,
                            'LS': None,
                            'ST': 0,
                            'I': instruction,
                            'RV': rev})
        return

    if instruction is not None:
        update_instruction_in_table(files_table, instruction, file_name)


def update_instruction_in_table(files_table, instruction, file_name):
    if instruction is not None and instruction == DELETE_ON_SERVER:

        files_table.update({'I': instruction}, Query().FN == file_name)

        # TODO LIKE

    else:

        files_table.update({'I': instruction}, Query().FN == file_name)


def get_file_name(config, full_path):
    if not full_path.startswith(config.args.absolute_local_root_path):
        if not (full_path + os.sep).startswith(config.args.absolute_local_root_path):
            raise ValueError('Unexpected file/dir ' + full_path + ' not under ' + config.args.absolute_local_root_path)
    rel = full_path[len(config.args.absolute_local_root_path):]
    if rel.startswith(os.sep):
        rel = rel[1:]
    return rel

def svn_dir_list(config, requests_session, prefix):

    propfind = requests_session.propfind(config.args.svn_url + esc(prefix), depth=1)

    output = propfind.text

    if "PROPFIND requests with a Depth of \"infinity\"" in output:
        print("'DavDepthInfinity on' needs to be enabled for the Apache instance on " \
              "the server (in httpd.conf probably). Refer to " \
              "https://github.com/subsyncit/subsyncit/wiki/Subversion-Server-Setup. " \
              "Subsyncit is refusing to run.")
        exit(1)

    entries = []; path = ""; rev = 0; sha1 = None

    splitlines = output.splitlines()
    for line in splitlines:
        if ":baseline-relative-path>" in line:
            rel_path = extract_path_from_baseline_rel_path(config, line)
            path = un_encode_path(rel_path)
        if ":version-name" in line:
            rev = int(line[line.index(">") + 1:line.index("<", 3)])
        if ":sha1-checksum>" in line:
            sha1 = line[line.index(">") + 1:line.index("<", 3)]
        if "</D:response>" in line:
            if len(path) >= len(prefix):
                sha_ = (path, rev, sha1)
                entries.append (sha_)
            path = ""; rev = 0; sha1 = None

    return entries

def extract_path_from_baseline_rel_path(config, line):
    search = re.search(
        "<lp[0-9]:baseline-relative-path>" + config.svn_baseline_rel_path.replace(
            os.sep, "/") + "(.*)</lp[0-9]:baseline-relative-path>", line)
    if search:
        path = search.group(1)
        if path.startswith("/"):
            path = path[1:]
    else:
        path = ""
    return path.replace("/", os.sep).replace("\\", os.sep).replace(os.sep+os.sep, os.sep)


def svn_PUTs(config, requests_session):

    my_trace(2,  " ---> svn_PUTs - start")

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
            rows = config.files_table.search(Query().I == PUT_ON_SERVER)
            num_rows = len(rows)
            for row in rows:
                rel_file_name = row['FN']
                try:
                    abs_local_file_path = (config.args.absolute_local_root_path + rel_file_name)
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
                        update_instruction_in_table(config.files_table, None, rel_file_name)
                    else:
                        dirs_made += PUT_file(config, requests_session, abs_local_file_path, row['RS'])  # <h1>Created</h1>

                        osstat = os.stat(abs_local_file_path)
                        size_ts = osstat.st_size + osstat.st_mtime
                        update_sha_and_revision_for_row(requests_session, config.files_table, rel_file_name, new_local_sha1, config, size_ts)
                        instruct_to_reGET_parent_if_there(config, rel_file_name)
                        put_count += 1
                        update_instruction_in_table(config.files_table, None, rel_file_name)
                except NotPUTtingAsItWasChangedOnTheServerByAnotherUser:
                    # Let another cycle get back to the and the GET to win.
                    not_actually_changed += 1
                    possible_clash_encountered = True
                    update_instruction_in_table(config.files_table, None, rel_file_name)
                except NotPUTtingAsFileStillBeingWrittenTo as e:
                    not_actually_changed += 1
                    update_instruction_in_table(config.files_table, None, rel_file_name)
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

    my_trace(2,  " ---> svn_PUTs - end")

    return possible_clash_encountered

def update_sha_and_revision_for_row(requests_session, files_table, file_name, local_sha1, config, size_ts):
    elements_for = svn_dir_list(config, requests_session, file_name)
    i = len(elements_for)
    if i != 1:
        raise BaseException("too many or too few elements found: " + str(i) + " for " + config.args.svn_url + file_name)
    for not_used_this_time, remote_rev_num, remote_sha1 in elements_for:
        if local_sha1 != remote_sha1:
            raise NotPUTtingAsItWasChangedOnTheServerByAnotherUser()
        files_table.update({
            'RV': remote_rev_num,
            'RS': remote_sha1,
            'LS': remote_sha1,
            'ST': size_ts
        }, Query().FN == file_name)


def svn_DELETEs(config, requests_session):

    my_trace(2,  " ---> svn_DELETEs - start")

    start = time.time()

    rows = config.files_table.search(Query().I == DELETE_ON_SERVER)

    files_deleted = 0
    directories_deleted = 0
    for row in rows:
        rfn = row['FN']
        requests_delete = requests_session.delete(config.args.svn_url + esc(rfn).replace(os.sep, "/"))
        output = requests_delete.text
        # debug(row['FN'] + ": DELETE " + str(requests_delete.status_code))
        if row['T'] == 'F':
            files_deleted += 1
            config.files_table.remove(Query().FN == row['FN'])
        else:
            directories_deleted += 1
            config.files_table.remove(Query().FN == row['FN'])
            # TODO LIKE

        if ("\n<h1>Not Found</h1>\n" not in output) and str(output) != "":
            print(("Unexpected on_deleted output for " + row['FN'] + " = [" + str(output) + "]"))
        instruct_to_reGET_parent_if_there(config, rfn)

    speed = "."
    if len(rows) > 0:
        speed = ", " + str(round((time.time() - start) / len(rows), 2)) + " secs per DELETE."

    section_end(files_deleted > 0 or directories_deleted > 0,  "DELETEs on Subversion server took %s, "
          + str(directories_deleted) + " directories and " + str(files_deleted) + " files"
          + speed, start)

    my_trace(2,  " ---> svn_DELETEs - end")

def svn_details(config, requests_session, file_name):
    ver = 0
    sha1 = None
    svn_baseline_rel_path = ""
    content = ""
    try:
        url = config.args.svn_url + esc(file_name).replace("\\", "/")
        if url.endswith("/"):
            url = url[:-1]
        propfind = requests_session.propfind(url, depth=0)
        if 200 <= propfind.status_code <= 299:
            content = propfind.text

            for line in content.splitlines():
                if ":baseline-relative-path" in line and "baseline-relative-path/>" not in line:
                    svn_baseline_rel_path = line[line.index(">")+1:line.index("<", 3)]
                if ":version-name" in line:
                    ver=int(line[line.index(">")+1:line.index("<", 3)])
                if ":sha1-checksum" in line:
                    if "sha1-checksum/" in line:
                        sha1 = None
                    else:
                        sha1=line[line.index(">")+1:line.index("<", 3)]
        # debug(file_name + ": PROPFIND " + str(propfind.status_code) + " / " + str(sha1) + " / " + str(ver) + " " + url)
        elif propfind.status_code == 401:
            raise NoConnection(config.args.svn_url + " is saying that the user is not authorized")
        elif propfind.status_code == 405:
            raise NoConnection(config.args.svn_url + " is not a website that maps subversion to that URL")
        elif 400 <= propfind.status_code <= 499:
            raise NoConnection("Cannot attach to remote Subversion server. Maybe not Subversion+Apache? Or wrong userId and/or password? Or wrong subdirectory within the server? Status code: " + str(
                propfind.status_code) + ", content=" + propfind.text)
        else:
            raise NoConnection("Unexpected web error " + str(propfind.status_code) + " " + propfind.text)
    except requests.packages.urllib3.exceptions.NewConnectionError as e:
        write_error(config.db_dir, "NewConnectionError: "+ repr(e))
    except requests.exceptions.ConnectionError as e:
        write_error(config.db_dir, "ConnectionError: "+ repr(e))
    return (ver, sha1, svn_baseline_rel_path)


def get_svn_repo_parent_path(requests_session, config):
    url = config.args.svn_url
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


def transform_enqueued_actions_into_instructions(config, local_adds_chgs_deletes_queue):

    my_trace(2,  " ---> transform_enqueued_actions_into_instructions - start")

    start = time.time()

    initial_queue_length = len(local_adds_chgs_deletes_queue)
    while len(local_adds_chgs_deletes_queue) > 0:
        (file_name, action) = local_adds_chgs_deletes_queue.pop(0)
        if action == "add_dir":
            upsert_row_in_table(config.files_table, file_name, 0, "dir", instruction=MAKE_DIR_ON_SERVER)
        elif action == "add_file":
            in_subversion = file_is_in_subversion(config.files_table, file_name)
            # 'svn up' can add a file, causing watchdog to trigger an add notification .. to be ignored
            if not in_subversion:
                # print("File to add: " + file_name + " is not in subversion")
                upsert_row_in_table(config.files_table, file_name, 0, "file", instruction=PUT_ON_SERVER)
        elif action == "change":
            update_instruction_in_table(config.files_table, PUT_ON_SERVER, file_name)
        elif action == "delete":
            in_subversion = file_is_in_subversion(config.files_table, file_name)
            # 'svn up' can delete a file, causing watchdog to trigger a delete notification .. to be ignored
            if in_subversion:
                update_instruction_in_table(config.files_table, DELETE_ON_SERVER, file_name)
        else:
            raise Exception("Unknown action " + action)

    section_end(len(local_adds_chgs_deletes_queue) > 0,  "Creation of instructions from " + str(initial_queue_length) + " enqueued actions took %s.", start)

    my_trace(2,  " ---> transform_enqueued_actions_into_instructions - end")


def file_is_in_subversion(files_table, file_name):
    row = files_table.get(Query().FN == file_name)
    return False if not row else row['RS'] != None


def print_rows(files_table):
    files_table_all = sorted(files_table.all(), key=lambda k: k['FN'])
    if len(files_table_all) > 0:
        print("All Items, as per 'files' table:")
        print("  RFN, 0=dir or 1=file, rev, remote sha1, local sha1, size + timestamp, instruction")
        for row in files_table_all:
            print(("  " + row['FN'] + ", " + str(row['T']) + ", " + str(row['RV']) + ", " +
                  str(row['RS']) + ", " + str(row['LS']) + ", " + str(row['ST']) + ", " + str(row['I'])))


def scantree(path):
    for entry in os.scandir(path):
        if entry.is_dir(follow_symlinks=False):
            yield from scantree(entry.path)
        else:
            yield entry


def scan_for_any_missed_adds_and_changes(config, state, excluded_filename_patterns):

    my_trace(2,  " ---> scan_for_any_missed_adds_and_changes - start")

    start = time.time()

    to_add = 0
    to_change = 0
    for entry in scantree(config.args.absolute_local_root_path):
        if state.is_shutting_down:
            break
        if to_add + to_change > 100:
            break
        if entry.stat().st_mtime < state.last_scanned:
            continue

        abs_local_file_path = entry.path
        file_name = get_file_name(config, abs_local_file_path)

        if excluded_filename_patterns.should_be_excluded(file_name):
            continue

        row = config.files_table.get(Query().FN == file_name)
        in_subversion = row and row['RS'] != None
        if row and row['I'] != None:
            continue
        if not in_subversion:
            upsert_row_in_table(config.files_table, file_name, 0, 'F', PUT_ON_SERVER)
            to_add += 1
        else:
            size_ts = entry.stat().st_size + entry.stat().st_mtime
            if size_ts != row["ST"]:
                update_instruction_in_table(config.files_table, PUT_ON_SERVER, file_name)
                to_change += 1

    section_end(to_change > 0 or to_add > 0,  "File system scan for extra PUTs: " + str(to_add) + " missed adds and " + str(to_change)
          + " missed changes (added/changed while Subsyncit was not running or somehow missed the attention of the file-system watcher) took %s.", start)

    my_trace(2,  " ---> scan_for_any_missed_adds_and_changes - end")

    return to_add + to_change

def scan_for_any_missed_deletes(config, state):

    my_trace(2,  " ---> scan_for_any_missed_deletes - start")

    start = time.time()
    to_delete = 0

    file = Query()
    for row in config.files_table.search((file.I == None) & (file.RS != None)):
        if state.is_shutting_down:
            break
        if to_delete > 100:
            break

        file_name = row['FN']
        if not os.path.exists(config.args.absolute_local_root_path + file_name) and row['I'] == None:
            update_instruction_in_table(config.files_table, DELETE_ON_SERVER, file_name)
            to_delete += 1

    section_end(to_delete > 0,  ": " + str(to_delete)
             + " extra DELETEs (deleted locally while Subsyncit was not running or somehow missed the attention of the file-system watcher) took %s.", start)

    my_trace(2,  " ---> scan_for_any_missed_deletes - end")

    return to_delete


def should_subsynct_keep_going(file_system_watcher, absolute_local_root_path):
    if not file_system_watcher.is_alive():
        return False
    fn = absolute_local_root_path + "subsyncit.stop"
    if os.path.isfile(fn):
        if file_system_watcher:
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
        ctypes.windll.kernel32.SetFileAttributesW(path, FILE_ATTRIBUTE_HIDDEN)


def loop(config, state, excluded_filename_patterns, local_adds_chgs_deletes_queue, requests_session):
    (root_revision_on_remote_svn_repo, sha1, svn_baseline_rel_path) = \
        svn_details(config, requests_session, "")  # root
    config.svn_baseline_rel_path = svn_baseline_rel_path
    if root_revision_on_remote_svn_repo > 0:

        try:
            state.online = True
            if not config.svn_repo_parent_path:
                config.svn_repo_parent_path = get_svn_repo_parent_path(requests_session, config)

            if root_revision_on_remote_svn_repo != None:
                if state.iteration == 0:  # At boot time only for now
                    excluded_filename_patterns.update_exclusions(config, requests_session)

                if config.args.do_file_system_scan:
                    scan_start_time = int(time.time())
                    scan_for_any_missed_adds_and_changes(config, state, excluded_filename_patterns)
                    scan_for_any_missed_deletes(config, state)
                    state.last_scanned = scan_start_time

                # Act on existing instructions (if any)
                transform_enqueued_actions_into_instructions(config, local_adds_chgs_deletes_queue)
                svn_GETs(config, requests_session, excluded_filename_patterns)
                transform_enqueued_actions_into_instructions(config, local_adds_chgs_deletes_queue)
                local_deletes(config)
                transform_enqueued_actions_into_instructions(config, local_adds_chgs_deletes_queue)
                possible_clash_encountered = svn_PUTs(config, requests_session)
                transform_enqueued_actions_into_instructions(config, local_adds_chgs_deletes_queue)
                svn_DELETEs(config, requests_session)
                transform_enqueued_actions_into_instructions(config, local_adds_chgs_deletes_queue)
                # Actions indicated by Subversion server next, only if root revision is different
                if root_revision_on_remote_svn_repo != state.last_root_revision or possible_clash_encountered:
                    svn_files = svn_dir_list(config, requests_session, "")
                    create_GET_and_local_delete_instructions_if_needed(config, excluded_filename_patterns, svn_files, "")
                    # update_revisions_for_created_directories(requests_session, files_table, args.svn_url, config.db_dir)
                    state.last_root_revision = root_revision_on_remote_svn_repo
                transform_enqueued_actions_into_instructions(config, local_adds_chgs_deletes_queue)
        except requests.packages.urllib3.exceptions.NewConnectionError as e:
            write_error(config.db_dir, "NewConnectionError: " + repr(e))
        except requests.exceptions.ConnectionError as e:
            write_error(config.db_dir, "ConnectionError: " + repr(e))
    else:
        state.online = False


def main(argv):

    if os.name != 'nt':
        home_dir = os.path.expanduser('~' + (os.getenv("SUDO_USER") or os.getenv("USER")))
    else:
        home_dir = os.path.expanduser(str(os.getenv('USERPROFILE')))

    parser = argparse.ArgumentParser(description='Subsyncit client')

    parser.add_argument("svn_url")
    parser.add_argument("local_root_path")
    parser.add_argument("user")
    parser.add_argument('--passwd', dest='passwd', help="Password")
    parser.add_argument('--verify-ssl-cert', dest='verify_ssl_cert', action='store_true', help="Verify SSL Certificate")
    parser.add_argument('--no-verify-ssl-cert', dest='verify_ssl_cert', action='store_false', help="Verify SSL Certificate")
    parser.set_defaults(verify_ssl_cert=True)
    parser.add_argument('--do-not-scan-file-system-periodically', dest='do_file_system_scan', action='store_false', help="Occasionally scan file system in addition to listen for "                                                                                                                             "nofication/events")
    parser.set_defaults(do_file_system_scan=True)
    parser.add_argument('--do-not-listen-for-file-system-events', dest='do_fs_event_listener', action='store_false', help="Occasionally scan file system in addition to listen for nofication/events")
    parser.set_defaults(do_fs_event_listener=True)
    parser.add_argument("--sleep-secs-between-polling", dest="sleep_secs",
                        default=30, type=int,
                        help="Sleep seconds between polling server")

    config = Config()
    config.args = parser.parse_args(argv[1:])

    if not config.args.passwd:
        config.auth = (config.args.user, getpass.getpass(prompt="Subverison password for " + config.args.user + ": "))

    elif config.args.passwd == "*NONE":
        config.auth = None
    else:
        config.auth = (config.args.user, config.args.passwd)

    config.args.absolute_local_root_path = os.path.abspath(config.args.local_root_path.replace("/", os.sep) \
                         .replace("\\", os.sep).replace(os.sep+os.sep, os.sep))

    if not config.args.absolute_local_root_path.endswith(os.sep):
        config.args.absolute_local_root_path += os.sep

    fn = config.args.absolute_local_root_path + os.sep + "subsyncit.stop"
    if os.path.isfile(fn):
        try:
            os.remove(fn)
        except OSError:
            pass

    if not str(config.args.svn_url).endswith("/"):
        config.args.svn_url += "/"

    verifySetting = True

    if not config.args.verify_ssl_cert:
        requests.packages.urllib3.disable_warnings()
        verifySetting = config.args.verify_ssl_cert

    subsyncit_settings_dir = home_dir + os.sep + ".subsyncit"
    if not os.path.exists(subsyncit_settings_dir):
        os.mkdir(subsyncit_settings_dir)
    make_hidden_on_windows_too(subsyncit_settings_dir)

    config.db_dir = subsyncit_settings_dir + os.sep + config.args.absolute_local_root_path.replace("/","%47").replace(":","%58").replace("\\","%92") + "/"

    if not os.path.exists(config.db_dir):
        os.mkdir(config.db_dir)

    db = TinyDB(config.db_dir + os.sep + "subsyncit.db", storage=CachingMiddleware(JSONStorage))
    config.files_table  = MyTinyDBTrace(db.table('files'))

    with open(config.db_dir + os.sep + "INFO.TXT", "w") as text_file:
        text_file.write(config.args.absolute_local_root_path + "is the Subsyncit path that this pertains to")

    local_adds_chgs_deletes_queue = IndexedSet()

    file_system_watcher = None

    class NUllObject(object):

        def is_alive(self):
            return True

        def stop(self):
            pass

        def join(self):
            pass

    excluded_filename_patterns = ExcludedPatternNames()

    state = State(config.db_dir)

    file_system_watcher = NUllObject()
    if config.args.do_fs_event_listener:
        if sys.platform == "linux" or sys.platform == "linux2":
            from watchdog.observers.inotify import InotifyObserver
            file_system_watcher = InotifyObserver()
        elif sys.platform == "darwin":
            from watchdog.observers.fsevents import FSEventsObserver
            file_system_watcher = FSEventsObserver()
        elif sys.platform == "win32":
            from watchdog.observers.read_directory_changes import WindowsApiObserver
            file_system_watcher = WindowsApiObserver
    
        notification_handler = FileSystemNotificationHandler(local_adds_chgs_deletes_queue, config, file_system_watcher, state, excluded_filename_patterns)
        file_system_watcher.schedule(notification_handler, config.args.absolute_local_root_path, recursive=True)
        file_system_watcher.daemon = True
        file_system_watcher.start()

    try:
        while should_subsynct_keep_going(file_system_watcher, config.args.absolute_local_root_path):

            # Recreating a session per iteration is good given use could be changing
            # connection to the internet as they move around (office, home, wifi, 3G)
            requests_session = make_requests_session(config.auth, verifySetting)

            loop(config, state, excluded_filename_patterns, local_adds_chgs_deletes_queue, requests_session)

            state.save_if_changed()

            if not requests_session.anything_substantial_happened():
                time.sleep(config.args.sleep_secs)
                requests_session.clear_counts()

    except NoConnection as e:
        write_error(config.db_dir, e.message)

    except KeyboardInterrupt:
        print("CTRL-C, Shutting down...")

    transform_enqueued_actions_into_instructions(config.files_table, local_adds_chgs_deletes_queue)

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
        print_rows(config.files_table)

if __name__ == "__main__":

    main(sys.argv)
    exit(0)

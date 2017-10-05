# Subsyncit - File sync backed by Subversion
#
# Version: xxx
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
# 3. Subversion username
#
# Optional arguments
# `--passwd` to supply the password on the command line (plain text) instead of prompting for secure entry
# `--no-verify-ssl-cert` to ignore certificate errors if you have a self-signed (say for testing)
# `--sleep-secs-between-polling` to supply a number of seconds to wait between poll of the server for changes
#
# Note: There's a database created in the Local Sync Directory called ".subsyncit.db".
# It contains one row per file that's synced back and forth. There's a field in there repoRev
# which is not currently used, but set to -999

import ctypes
import os
import sys
#import sqlite3
import hashlib
import time
from os.path import dirname
from multiprocessing import Queue
import shutil

import re
from random import randint

import requests
import requests.packages.urllib3
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from os.path import splitext
import datetime
from tinydb import TinyDB, Query
import getpass
import argparse

PROPFIND = '<?xml version="1.0" encoding="utf-8" ?>\n' \
             '<D:propfind xmlns:D="DAV:">\n' \
             '<D:prop xmlns:S="http://subversion.tigris.org/xmlns/dav/">\n' \
             '<S:sha1-checksum/>\n' \
             '<D:version-name/>\n' \
             '<S:baseline-relative-path/>\n' \
             '</D:prop>\n' \
             '</D:propfind>\n'


def debug(message):
    #pass
    ## if not "PROPFIND" in message:
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


class FileSystemNotificationHandler(FileSystemEventHandler):

    def __init__(self, local_adds_chgs_deletes_queue, absolute_local_root_path, file_system_watcher):
        super(FileSystemNotificationHandler, self).__init__()
        self.local_adds_chgs_deletes_queue = local_adds_chgs_deletes_queue
        self.absolute_local_root_path = absolute_local_root_path
        self.file_system_watcher = file_system_watcher
        self.excluded_filename_patterns = []

    def on_created(self, event):
        relative_file_name = get_relative_file_name(event.src_path, self.absolute_local_root_path)
        if relative_file_name == ".subsyncit.stop":
            self.file_system_watcher.stop()
            try:
                self.file_system_watcher.join()
                os.remove(event.src_path)
            except RuntimeError:
                pass
            except OSError:
                pass
            return
        if relative_file_name.startswith(".") \
                or len(relative_file_name) == 0 \
                or ".clash_" in relative_file_name \
                or should_be_excluded(relative_file_name, self.excluded_filename_patterns):
            return
        self.local_adds_chgs_deletes_queue.put((
            get_relative_file_name(event.src_path, self.absolute_local_root_path), "add_" + ("dir" if event.is_directory else "file")))

    def on_deleted(self, event):
        relative_file_name = get_relative_file_name(event.src_path, self.absolute_local_root_path)
        if relative_file_name.startswith(".") \
                or len(relative_file_name) == 0 \
                or ".clash_" in relative_file_name \
                or should_be_excluded(relative_file_name, self.excluded_filename_patterns):
            return
        self.local_adds_chgs_deletes_queue.put((
            get_relative_file_name(event.src_path, self.absolute_local_root_path), "delete"))

    def on_modified(self, event):
        relative_file_name = get_relative_file_name(event.src_path, self.absolute_local_root_path)
        if relative_file_name.startswith(".") \
                or len(relative_file_name) == 0 \
                or ".clash_" in relative_file_name \
                or should_be_excluded(relative_file_name, self.excluded_filename_patterns):
            return
        if not event.is_directory and not event.src_path.endswith(self.absolute_local_root_path):
            self.local_adds_chgs_deletes_queue.put((
                get_relative_file_name(event.src_path, self.absolute_local_root_path), "change"))


    def update_excluded_filename_patterns(self, excluded_filename_patterns):
        self.excluded_filename_patterns = excluded_filename_patterns


def should_be_excluded(relative_file_name, excluded_filename_patterns):
    bn = os.path.basename(relative_file_name)
    for pattern in excluded_filename_patterns:
        if pattern.search(bn):
            return True
    return False

def get_suffix(relative_file_name):
    file_name, extension = splitext(relative_file_name)
    return extension


def make_remote_subversion_directory_for(relative_file_name, remote_subversion_repo_url, user, passwd, verifySetting):
    output = requests.request('MKCOL', remote_subversion_repo_url + relative_file_name.replace(os.sep, "/"),
                              auth=(user, passwd), verify=verifySetting).content
    if "\nFile not found:" in output:
        make_remote_subversion_directory_for(dirname(relative_file_name), remote_subversion_repo_url, user, passwd, verifySetting)  # parent
        make_remote_subversion_directory_for(relative_file_name, remote_subversion_repo_url, user, passwd, verifySetting)  # try this one again
        debug(relative_file_name + ": MKCOL" )

def put_item_in_remote_subversion_directory(abs_local_file_path, remote_subversion_repo_url, user, passwd, absolute_local_root_path, verifySetting):
    s1 = os.path.getsize(abs_local_file_path)
    time.sleep(1)
    s2 = os.path.getsize(abs_local_file_path)
    if s1 != s2:
        return "... still being written to"
    relative_file_name = get_relative_file_name(abs_local_file_path, absolute_local_root_path)
    # TODO has it chnged on server
    with open(abs_local_file_path, "rb") as f:
        url = remote_subversion_repo_url + relative_file_name.replace(os.sep, "/")
        put = requests.put(url, auth=(user, passwd), data=f.read(), verify=verifySetting)
        output = put.content
        local_file = calculate_sha1_from_local_file(
            absolute_local_root_path + relative_file_name)
        debug(absolute_local_root_path + relative_file_name + ": PUT " + str(put.status_code) + ", sha1:" + local_file)
        if put.status_code == 404:
            make_remote_subversion_directory_for(dirname(get_relative_file_name(abs_local_file_path, absolute_local_root_path)),
                                                 remote_subversion_repo_url, user, passwd, verifySetting)
            output = put_item_in_remote_subversion_directory(abs_local_file_path, remote_subversion_repo_url, user, passwd, absolute_local_root_path, verifySetting)
        if put.status_code == 201 or put.status_code == 204:
            return ""
        return output

def enque_gets_and_local_deletes(files_table, all_entries, absolute_local_root_path, excluded_filename_patterns):
    File = Query()
    files_table.update({'instruction': 'QUESTION'}, File.instruction == None)
    for relative_file_name, rev, sha1 in all_entries:
        if relative_file_name.startswith(".") \
                or len(relative_file_name) == 0 \
                or should_be_excluded(relative_file_name, excluded_filename_patterns):
            continue
        dir_or_file = "dir" if sha1 is None else "file"
        File = Query()
        rows = files_table.search(File.relativeFileName == relative_file_name)
        if len(rows) > 0:
            if rows[0]['remoteSha1'] != sha1:
                update_instruction_in_table(files_table, "GET", relative_file_name)
#               else:
            else:
                localSha1 = calculate_sha1_from_local_file(absolute_local_root_path + relative_file_name)
                if rows[0]['localSha1'] == localSha1:
                    update_instruction_in_table(files_table, None, relative_file_name)
                else:
                    update_instruction_in_table(files_table, "PUT", relative_file_name)
        else:
            upsert_row_in_table(files_table, relative_file_name, rev, dir_or_file, instruction="GET")
    File = Query()
    files_table.update({'instruction': 'DELETE LOCALLY'}, File.instruction == 'QUESTION')


def extract_name_type_rev(entry_xml_element):
    file_or_dir = entry_xml_element.attrib['kind']
    relative_file_name = entry_xml_element.findtext("name")
    rev = entry_xml_element.find("commit").attrib['revision']
    return file_or_dir, relative_file_name, rev


def sync_remote_adds_and_changes_to_local(files_table, remote_subversion_repo_url, user, passwd, absolute_local_root_path, verifySetting):
    File = Query()
    rows = files_table.search(File.instruction == "GET")
    for row in rows:
        relative_file_name = row['relativeFileName']
        is_file = row['isFile'] == "1"
        old_sha1_should_be = row['localSha1']
        # print "get cycle old sha " + absolute_local_root_path + " " + str(old_sha1_should_be)
        abs_local_file_path = (absolute_local_root_path + relative_file_name)
        head = requests.head(remote_subversion_repo_url + relative_file_name,
                             auth=(user, passwd),
                             verify=verifySetting)

        if not is_file or ("Location" in head.headers and head.headers[
                    "Location"].endswith("/")):
            if not os.path.exists(abs_local_file_path):
                os.makedirs(abs_local_file_path)
                update_row_shas(files_table, relative_file_name, None)
        else:
            (repoRev, sha1,
             baseline_relative_path_not_used) = get_remote_subversion_repo_revision_for(
                remote_subversion_repo_url, user, passwd, relative_file_name,
                absolute_local_root_path, verifySetting)

            get = requests.get(
                remote_subversion_repo_url + relative_file_name.replace(os.sep,
                                                                        "/"),
                auth=(user, passwd),
                verify=verifySetting, stream=True)
            debug(
                absolute_local_root_path + relative_file_name + ": GET " + str(
                    get.status_code))
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
            # print "get cycle " + absolute_local_root_path + "-" + sha1
            update_row_shas(files_table, relative_file_name, sha1)
            update_row_revision(files_table, relative_file_name, repoRev)
        update_instruction_in_table(files_table, None, relative_file_name)
        # print "end_of_sync" + prt_files_table_for(files_table, relative_file_name)


def sync_remote_deletes_to_local(files_table, absolute_local_root_path):

    File = Query()
    rows = files_table.search(File.instruction == 'DELETE LOCALLY')

    for row in rows:
        delete_file_and_entries_in_table(files_table, row['relativeFileName'], absolute_local_root_path, False if row['isFile'] == 1 else True)


def update_row_shas(files_table, relative_file_name, sha1):
    File = Query()
    foo = files_table.update({'remoteSha1': sha1, 'localSha1': sha1}, File.relativeFileName == relative_file_name)
    # print "update_row_shas: " + str(foo) + " " + relative_file_name + ": " + sha1 + " --- " + prt_files_table_for(files_table, relative_file_name)


def prt_files_table_for(files_table, relative_file_name):
    return str(files_table.search(Query().relativeFileName == relative_file_name))


def update_row_revision(files_table, relative_file_name, rev=-1):
    File = Query()
    files_table.update({'repoRev': -999}, File.relativeFileName == relative_file_name)


def upsert_row_in_table(files_table, relative_file_name, rev, file_or_dir, instruction):

    File = Query()
    # print "upsert1" + prt_files_table_for(files_table, relative_file_name)
    if len(files_table.search(File.relativeFileName == relative_file_name)) == 0:
        files_table.insert({'relativeFileName': relative_file_name,
                   'isFile': ("1" if file_or_dir == "file" else "0"),
                   'remoteSha1': None,
                   'localSha1': None,
                   'repoRev': -999})

    if instruction is not None:
        update_instruction_in_table(files_table, instruction, relative_file_name)

    # print "upsert2" + prt_files_table_for(files_table, relative_file_name)


def update_instruction_in_table(files_table, instruction, relative_file_name):
    if instruction is not None and instruction == "DELETE":

        File = Query()
        files_table.update({'instruction': instruction}, File.relativeFileName == relative_file_name)

        # TODO LIKE

    else:

        File = Query()
        files_table.update({'instruction': instruction}, File.relativeFileName == relative_file_name)


def delete_file_and_entries_in_table(files_table, relative_file_name, absolute_local_root_path, wildcard):

    if wildcard:
        File = Query()
        files_table.remove(File.relativeFileName == relative_file_name)

        # TODO LIKE

    else:
        File = Query()
        files_table.remove(File.relativeFileName.test(lambda rfn: rfn.startswith('relative_file_name')))

    name = (absolute_local_root_path + relative_file_name)
    try:
        os.remove(name)
    except OSError:
        try:
            shutil.rmtree(name)
        except OSError:
            pass
    parent = os.path.dirname(name)
    listdir = os.listdir(parent)
    if len(listdir) == 0:
        try:
            shutil.rmtree(parent)
        except OSError:
            pass

def get_relative_file_name(full_path, absolute_local_root_path):
    if not full_path.startswith(absolute_local_root_path):
        if not (full_path + os.sep).startswith(absolute_local_root_path):
            raise ValueError('Unexpected file/dir ' + full_path + ' not under ' + absolute_local_root_path)
    rel = full_path[len(absolute_local_root_path):]
    if rel.startswith(os.sep):
        rel = rel[1:]
    return rel

def svn_metadata_xml_elements_for(url, baseline_relative_path, user, passwd, verifySetting):
    propfind = requests.request('PROPFIND', url, auth=(user, passwd), data=PROPFIND,
                                headers={'Depth': 'infinity'}, verify=verifySetting)

    output = propfind.content

    if "PROPFIND requests with a Depth of \"infinity\"" in output:
        print "'DavDepthInfinity on' needs to be enabled for the Apache instance on " \
              "the server (in httpd.conf propbably). Refer to " \
              "https://github.com/paul-hammant/subsyncit/blob/master/SERVER-SETUP.md. " \
              "Subsyncit is refusing to run."
        exit(1)

    entries = []; path = ""; rev = -1; sha1 = None

    for line in output.splitlines():
        if ":baseline-relative-path>" in line:
            path = extract_path_from_baseline_rel_path(baseline_relative_path, line)
        if ":version-name" in line:
            rev = int(line[line.index(">") + 1:line.index("<", 3)])
        if ":sha1-checksum>" in line:
            sha1 = line[line.index(">") + 1:line.index("<", 3)]
        if "</D:response>" in line:
            entries.append ((path, rev, sha1))
            path = ""; rev = -1; sha1 = None

    # debug(path + ": PROPFIND " + str(propfind.status_code) + " / " + str(sha1))
    return entries

def extract_path_from_baseline_rel_path(baseline_relative_path, line):
    search = re.search(
        "<lp2:baseline-relative-path>" + baseline_relative_path.replace(
            os.sep, "/") + "(.*)</lp2:baseline-relative-path>", line)
    if search:
        path = search.group(1)
        if path.startswith("/"):
            path = path[1:]
    else:
        path = ""
    #            print "LINE=" + line + ", PATH=" + path + "-" + baseline_relative_path + "-"
    return path.replace("/", os.sep).replace("\\", os.sep).replace(os.sep+os.sep, os.sep)


def perform_adds_and_changes_on_remote_subversion_repo_if_shas_are_different(files_table, remote_subversion_repo_url, user, passwd, baseline_relative_path, absolute_local_root_path, verifySetting):

    File = Query()
    rows = files_table.search(File.instruction == "PUT")

    add_changes = 0
    for row in rows:
        rel_file_name = row['relativeFileName']
        abs_local_file_path = (absolute_local_root_path + rel_file_name)
        new_local_sha1 = calculate_sha1_from_local_file(abs_local_file_path)
        output = ""
        if new_local_sha1 == 'FILE_MISSING' or (row['remoteSha1'] == row['localSha1'] and row['localSha1'] == new_local_sha1):
            pass
            # files that come down as new/changed, get written to the FS trigger a file added/changed message,
            # and superficially look like they should get pushed back to the server. If the sha1 is unchanged
            # don't do it.
        else:
            add_changes += 1
            output = put_item_in_remote_subversion_directory(abs_local_file_path, remote_subversion_repo_url, user, passwd, absolute_local_root_path, verifySetting)  # <h1>Created</h1>
            if "... still being written to" not in output:
                update_sha_and_revision_for_row(files_table, rel_file_name, new_local_sha1, remote_subversion_repo_url, user, passwd, baseline_relative_path, verifySetting)
            if not output == "":
                print("Unexpected on_created output for " + rel_file_name + " = [" + str(output) + "]")
        if "... still being written to" not in output:
            update_instruction_in_table(files_table, None, rel_file_name)
    if add_changes > 0:
        print("Pushed " + str(add_changes) + " add(s) or change(s) to Subversion")


def update_sha_and_revision_for_row(files_table, relative_file_name, local_sha1, remote_subversion_repo_url, user, passwd, baseline_relative_path, verifySetting):
    name = remote_subversion_repo_url + relative_file_name
    elements_for = svn_metadata_xml_elements_for(name, baseline_relative_path, user, passwd, verifySetting)
    i = len(elements_for)
    if i > 1:
        print("elements found == " + str(i))
    for relative_file_name2, rev, sha1 in elements_for:
        if local_sha1 != sha1:
            print("SHA1s don't match when they should for " + relative_file_name2 + " " + str(sha1) + " " + local_sha1)
        update_row_shas(files_table, relative_file_name2, local_sha1)
        update_row_revision(files_table, relative_file_name2, rev)


def update_revisions_for_created_directories(files_table, remote_subversion_repo_url, user, passwd, absolute_local_root_path, verifySetting):

    File = Query()
    rows = files_table.search(File.instruction == 'MKCOL')

    msg_done = False
    for row in rows:
        if not msg_done:
            print("Getting Revisions for created dirs from Subversion")
            msg_done = True
        (revn, sha1, baseline_relative_path_not_used) = get_remote_subversion_repo_revision_for(remote_subversion_repo_url, user, passwd, row[0], absolute_local_root_path, verifySetting)
        update_row_revision(files_table, row['relativeFileName'], rev=revn)
        update_instruction_in_table(files_table, None, row['relativeFileName'])


def perform_deletes_on_remote_subversion_repo(files_table, remote_subversion_repo_url, user, passwd, verifySetting):

    File = Query()
    rows = files_table.search(File.instruction == 'DELETE ON REMOTE')

    deletes = 0
    for row in rows:
        deletes += 1
        # print "D ROW: " + str(row)
        row_ = row['relativeFileName']
        requests_delete = requests.delete(remote_subversion_repo_url + row_.replace(os.sep, "/"), auth=(user, passwd), verify=verifySetting)
        output = requests_delete.content
        # debug(row['relativeFileName'] + ": DELETE " + str(requests_delete.status_code))
        if row['isFile'] == 1:  # isFile
            File = Query()
            files_table.remove(File.relativeFileName == row['relativeFileName'])
        else:
            File = Query()
            files_table.remove(File.relativeFileName == row['relativeFileName'])
            # TODO LIKE

        if ("\n<h1>Not Found</h1>\n" not in output) and str(output) != "":
            print("Unexpected on_deleted output for " + row['relativeFileName'] + " = [" + str(output) + "]")

    if deletes > 0:
        print("Pushed " + str(deletes) + " delete(s) to Subversion")



def get_remote_subversion_repo_revision_for(remote_subversion_repo_url, user, passwd, relative_file_name, absolute_local_root_path, verifySetting):
    ver = -1
    sha1 = None
    baseline_relative_path = ""
    output = ""
    try:
        url = remote_subversion_repo_url + relative_file_name.replace("\\", "/")
        propfind = requests.request('PROPFIND', url, auth=(user, passwd), data=PROPFIND,
                                    headers={'Depth': '0'}, verify=verifySetting)
        if 200 <= propfind.status_code <= 299:
            output = propfind.content

            for line in output.splitlines():
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
        else:
            output = "PROPFIND status: " + str(propfind.status_code) + " for: " + remote_subversion_repo_url + " user: " + user
        if ver == -1:
            write_error(absolute_local_root_path, output)
    except requests.exceptions.ConnectionError, e:
        write_error(absolute_local_root_path, "Could be offline? " + repr(e))
    return (ver, sha1, baseline_relative_path)


def write_error(absolute_local_root_path, msg):
    subsyncit_err = absolute_local_root_path + ".subsyncit.err"
    with open(subsyncit_err, "w") as text_file:
        text_file.write(msg)
    make_hidden_on_windows_too(subsyncit_err)


def sleep_a_little(sleep_secs):
    time.sleep(sleep_secs)


def process_queued_local_sync_directory_adds_changes_and_deletes(files_table, local_adds_chgs_deletes_queue):
    while not local_adds_chgs_deletes_queue.empty():
        (relative_file_name, action) = local_adds_chgs_deletes_queue.get()
        if action == "add_dir":
            upsert_row_in_table(files_table, relative_file_name, "-1", "dir", instruction="MKCOL")
        elif action == "add_file":
            in_subversion = file_is_in_subversion(files_table, relative_file_name)
            # 'svn up' can add a file, causing watchdog to trigger an add notification .. to be ignored
            if not in_subversion:
                upsert_row_in_table(files_table, relative_file_name, "-1", "file", instruction="PUT")
        elif action == "change":
            update_instruction_in_table(files_table, "PUT", relative_file_name)
        elif action == "delete":
            in_subversion = file_is_in_subversion(files_table, relative_file_name)
            # 'svn up' can delete a file, causing watchdog to trigger a delete notification .. to be ignored
            if in_subversion:
                update_instruction_in_table(files_table, "DELETE ON REMOTE", relative_file_name)
        else:
            raise Exception("Unknown action " + action)


def file_is_in_subversion(connection, relative_file_name):
    return instruction_for_file(connection, relative_file_name) is not None


def instruction_for_file(files_table, relative_file_name):
    File = Query()
    rows = files_table.search(File.relativeFileName == relative_file_name)

    if len(rows) == 0:
        return None
    else:
        return rows[0]

def print_rows(files_table):
    files_table_all = files_table.all()
    if len(files_table_all) > 0:
        print("All Items, as per 'files' table:")
        print("  relativeFileName, 0=dir or 1=file, rev, remote sha1, local sha1, instruction")
        for row in files_table_all:
            print("  " + row['relativeFileName'] + ", " + str(row['isFile']) + ", " + str(row['repoRev']) + ", " +
                  str(row['remoteSha1']) + ", " + str(row['localSha1']) + ", " + str(row['instruction']))


def enque_any_missed_adds_and_changes(files_table, local_adds_chgs_deletes_queue, absolute_local_root_path, excluded_filename_patterns):
    for (dir, _, files) in os.walk(absolute_local_root_path):
        for f in files:
            path = os.path.join(dir, f)
            relative_file_name = get_relative_file_name(path, absolute_local_root_path)
            in_subversion = file_is_in_subversion(files_table, relative_file_name)
            instruction = instruction_for_file(files_table, relative_file_name)
            path_exists = os.path.exists(path)
            if relative_file_name.startswith(".") \
                    or ".clash_" in relative_file_name \
                    or should_be_excluded(relative_file_name, excluded_filename_patterns):
                continue
            if path_exists and not in_subversion:
                local_adds_chgs_deletes_queue.put((relative_file_name, "add_file"))
            elif path_exists and in_subversion and instruction == None:
                # This is speculative, logic further on will not PUT the file up
                # if the SHA is unchanged.
                local_adds_chgs_deletes_queue.put((relative_file_name, "change"))

def enque_any_missed_deletes(files_table, local_adds_chgs_deletes_queue, absolute_local_root_path):
    for row in files_table.all():
        if not os.path.exists(absolute_local_root_path + row['relativeFileName']):
            local_adds_chgs_deletes_queue.put((row['relativeFileName'], "delete"))


def keep_going(file_system_watcher, absolute_local_root_path):
    if not file_system_watcher.is_alive():
        return False
    fn = absolute_local_root_path + ".subsyncit.stop"
    if os.path.isfile(fn):
        file_system_watcher.stop()
        file_system_watcher.join()
        try:
            os.remove(fn)
        except OSError:
            pass
        return False
    return True

def get_excluded_filename_patterns(remote_subversion_repo_url, user, passwd, verifySetting):
    try:
        get = requests.get(remote_subversion_repo_url + ".subsyncit-excluded-filename-patterns", auth=(user, passwd),
                           verify=verifySetting)
        if (get.status_code == 200):
            lines = get.content.splitlines()
            regexes = []
            for line in lines:
                regexes.append(re.compile(line))
            return regexes
        return []
    except requests.exceptions.ConnectionError, e:
        return []

def main(argv):
    parser = argparse.ArgumentParser(description='Subsyncit client')

    parser.add_argument("remote_subversion_repo_url")
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

    from requests.adapters import HTTPAdapter

    s = requests.Session()
    s.mount('http://', HTTPAdapter(max_retries=0))
    s.mount('https://', HTTPAdapter(max_retries=0))

    if not str(args.remote_subversion_repo_url).endswith("/"):
        args.remote_subversion_repo_url += "/"

    verifySetting = True

    if not args.verify_ssl_cert:
        requests.packages.urllib3.disable_warnings()
        verifySetting = args.verify_ssl_cert

    tinydb_path = args.absolute_local_root_path + ".subsyncit.db"
    db = TinyDB(tinydb_path)
    files_table  = db.table('files')

    local_adds_chgs_deletes_queue = Queue()

    make_hidden_on_windows_too(tinydb_path)

    last_root_revision = -1

    file_system_watcher = Observer()
    notification_handler = FileSystemNotificationHandler(local_adds_chgs_deletes_queue, args.absolute_local_root_path,
                                            file_system_watcher)
    file_system_watcher.schedule(notification_handler, args.absolute_local_root_path, recursive=True)
    file_system_watcher.start()

    iteration = 0
    last_missed_time = 0
    try:
        while keep_going(file_system_watcher, args.absolute_local_root_path):
            (root_revision_on_remote_svn_repo, sha1, baseline_relative_path) = get_remote_subversion_repo_revision_for(args.remote_subversion_repo_url, args.user, passwd, "", args.absolute_local_root_path, verifySetting) # root
            if root_revision_on_remote_svn_repo != -1:
                excluded_filename_patterns = []
                if iteration == 0: # At boot time only for now
                    excluded_filename_patterns = get_excluded_filename_patterns(args.remote_subversion_repo_url, args.user, passwd, verifySetting)
                    notification_handler.update_excluded_filename_patterns(excluded_filename_patterns)
                if root_revision_on_remote_svn_repo != last_root_revision:
                    all_entries = svn_metadata_xml_elements_for(args.remote_subversion_repo_url, baseline_relative_path, args.user, passwd, verifySetting)
                    enque_gets_and_local_deletes(files_table, all_entries, args.absolute_local_root_path, excluded_filename_patterns)
                    sync_remote_adds_and_changes_to_local(files_table, args.remote_subversion_repo_url, args.user, passwd, args.absolute_local_root_path, verifySetting)
                    sync_remote_deletes_to_local(files_table, args.absolute_local_root_path)
                    update_revisions_for_created_directories(files_table, args.remote_subversion_repo_url, args.user, passwd, args.absolute_local_root_path, verifySetting)
                    last_root_revision = root_revision_on_remote_svn_repo
                process_queued_local_sync_directory_adds_changes_and_deletes(files_table, local_adds_chgs_deletes_queue)
                perform_adds_and_changes_on_remote_subversion_repo_if_shas_are_different(files_table, args.remote_subversion_repo_url, args.user, passwd, baseline_relative_path, args.absolute_local_root_path, verifySetting)
                perform_deletes_on_remote_subversion_repo(files_table, args.remote_subversion_repo_url, args.user, passwd, verifySetting)
                # TODO calc right ?
                if time.time() - last_missed_time > 60:
                    # This is 1) a fallback, in case the watchdog file watcher misses something
                    # And 2) a processor that's going to process additions to the local sync dir
                    # that may have happened when this daemon wasn't running.
                    enque_any_missed_adds_and_changes(files_table, local_adds_chgs_deletes_queue, args.absolute_local_root_path, excluded_filename_patterns)
                    enque_any_missed_deletes(files_table, local_adds_chgs_deletes_queue, args.absolute_local_root_path)
                    last_missed_time = time.time()
            sleep_a_little(args.sleep_secs)
            iteration += 1
    except KeyboardInterrupt:
        print "CTRL-C, Shutting down..."
        pass
    file_system_watcher.stop()
    try:
        file_system_watcher.join()
    except RuntimeError:
        pass

    debug = True

    if debug:
        print_rows(files_table)


def make_hidden_on_windows_too(path):
    if os.name == 'nt':
        FILE_ATTRIBUTE_HIDDEN = 0x02
        ret = ctypes.windll.kernel32.SetFileAttributesW(path, FILE_ATTRIBUTE_HIDDEN)

if __name__ == "__main__":

    main(sys.argv)
    exit(0)

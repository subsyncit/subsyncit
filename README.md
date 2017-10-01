# Subsyncit

A File sync client that uses a Subversion repo as the backing-store, with no other server-side install. It is written in Python.

It's been tested with files of random bytes up to 12GB in size. It has also been with repo sizes
up to 3.4TB (history, not the amount of files at HEAD revision, but that should work too).

# Overview

## Glossary

* Client - a workstation, laptop or mobile device.
* Server - a computer on which a suitable Subversion is installed (Mod_Web_Dav, SVNAutoversioning on).
* Remote Subversion Repository (or repo) - on the server, a configuration of subversion that can take commits for so-authorized people.
* Local Sync Directory - on the client a single directory, the contents for which will synchronized up and down to the remote Subversion repo.

## Features in common with all file-sync technologies:

* Brings down added/changed/deleted files from the remote Subversion repo to the client's local sync directory.
* Pushed up added/changed/deleted files from your client's local sync directory to the remote Subversion repo on the server.
* Several people can maintain separate local sync directories and share files on a remote Subversion repo.

## Additional features expected because Subversion is the backing store:

* Keeps an audit trail (historical versions)
* Whole directory trees can be checked out en-masse, worked on, and committed back (per normal Svn workflow)
* Branches are configuration choice for novel usages.

## Design goals, counter to the way Subversion normally works:

* Does not maintain a working-tree (or working copy or 'checkout') on the client.
 * there's no .svn/ folder(s).
  * therefore there is only one version of each file on the client system.
* No Subversion install on client (if that wasn't obvious)

## Working so far:

1. Two-way syncing of add/changes/deletes, including directories, and timer based polling of remote Subversion repo for changes over time.
2. Deliberate 'quiet time' after a local change detected, in in order to not push a a partially complete file write to the remote Subversion repo.
3. Fallback mechanism to detect local sync directory adds/changes/deletes that were not detected or pushed previously.
4. Clash detection using sha1 - server always wins, the local changed version is renamed out the way.
5. Ability to reject a non Svn/DAV/SVNAutoversioning server - it silently just tries again later (needs work)
6. Standard exclusions via file suffix

## Yet to develop / needs work

1. UI for prompting user's Subversion id/password.
2. Tray/task bar icon/status.
3. Multiple directories
4. Directory mask (globbing) per user
5. Incomplete downloads are completed by handles as a clash present (renamed out the way)

# Server-side setup

A Subversion server with mod_dav_svn (and Apache2) activated.

## Apache settings

These are the settings you'll need ADD to change in Apache's .conf file to allow Subsyncit modes of operation:

```
<Location /svn>
  # Etc
  DavDepthInfinity on
  SVNListParentPath on
  SVNAutoversioning on
  # Etc
</Location>
```

Here is a Perl oneliner that will do that for the [Bitnami-Subversion](https://bitnami.com/stack/subversion) image you can deploy to Amazon, Google Cloud or others:

```
perl -pi -e 's/DAV svn/DAV svn\nDavDepthInfinity on\nSVNListParentPath on\nSVNAutoversioning on/' /opt/bitnami/apache2/conf/httpd.conf

# then do

sudo /opt/bitnami/ctlscript.sh restart apache
```

### Permissions for read/write

Two lines in httpd.conf should be changed. From:

```
# anon-access = read
# auth-access = write
```

To:

```
anon-access = none
auth-access = write
```

Here are perl oneliners to do that (Bitnami location of httpd.conf shown):

```
perl -pi -e 's/# anon-access = read/anon-access = none/' /opt/bitnami/apache2/conf/httpd.conf
perl -pi -e 's/# auth-access = read/auth-access = write/' /opt/bitnami/apache2/conf/httpd.conf
```

### Authentication type changes

These need to be added to the Subversion block inside httpd.conf (Bitnami location of httpd.conf shown):

```
<Location /svn>
  # Etc
  AuthType Basic
  AuthName "Subversion repository"
  AuthUserFile /opt/bitnami/repository/users
  require valid-user
  # Etc
</Location>

AuthType Basic
AuthName "Subversion repository"
AuthUserFile /opt/bitnami/repository/users
require valid-user
```

Here is the perl oneliner to do that (Bitnami location of httpd.conf shown):

```
perl -pi -e 's/DAV svn/DAV svn\nAuthType Basic\nAuthName "Subversion repository"\nrequire valid-user\nAuthUserFile /opt/bitnami/repository/users/' /opt/bitnami/apache2/conf/httpd.conf
```

### Creating users

(Bitnami location of htpasswd command):

```
sudo /opt/bitnami/apache2/bin/htpasswd -c /opt/bitnami/repository/users <username>
```

You will be promoted to choose a password. Also hange `-c` to `-m` for second and subsequent invocations, as the former overwrites the file.

### Bitnami image extra step

One more thing for a Bitnami instance in order to enable writes from the client side: You will
need to read [this definitive page](https://docs.bitnami.com/aws/apps/subversion/#enabling-commits-over-https)
and do the section [Enabling Commits Over HTTP(S)?](https://docs.bitnami.com/aws/apps/subversion/#enabling-commits-over-https):

```
sudo chown -R daemon:subversion /opt/bitnami/repository
```

## Subversion settings

You will need to change some settings for the Subversion repo too. Specifically in
`<svn_root>/db/fsfs.conf` on the server:

```
# Subversion attempts to align storage with 'deltas' of changes. A large 15G avi
# file that you changed the resolution of, will have EVERY BYTE different. Therefore
# attempting to look for deltas is pointless. If that is your file type, and
# changes like that are real, turn off delta-walking, by making the pertinent line
# like so:

max-deltification-walk = 0


# The compression for large binaries kills performance for changes being pushed
# to the server. Turn it off for all file types, by making the pertinent line
# like so:

compression-level = 0

```

# Subsyncit client computer installation

Python2 is required, as well as some `pip2` installed modules:

```
pip2 install requests watchdog tinydb
```

Note:

1. Requests is Apache 2.0 licensed and maintained at http://python-requests.org
2. Watchdog is Apache 2.0 licensed and maintained at https://github.com/gorakhargosh/watchdog
2. TinyDB is MIT licensed and maintained at https://github.com/msiemens/tinydb

## Running Subsyncit

```
python2 subsyncit.py <url-of-subversion-root> <path-to-local-directory-we-want-to-sync-to> <svn-user-name> False <sleep-seconds>
```

You get prompted for you subversion password, when it launches.

## Running the functional tests

Tests can only run these on the same server as the Subsyncit install, it is runs subversion admin operations, too.

You'll already have setup the Subversion+Apache server (as above).

Python modules that are needed:

```
pip install sh glob2 requests
```

In the checkout directory, run:

```
sudo python functional_test_of_sync_operations.py <URL> <user> <root-of-repo-in-filesystem> <size-of-big-file>

```

The URL is to the `svnParent` directory that the test will make a `unitTests` folder in. The user will be an account that can read
and write to that repo. You'll be prompted to enter the password for the subversion account. The sudo and subversion password pay be
different of course.

The tests, when running, delete and recreate the `functionalTests` folder on the subversion server, and implement the subversion `fsfs.conf` settings
changes, as detailed above. That is why they need to be run as `sudo`.

## Running performance tests on multiple Subversion server installation permutations

In the subsyncit checkout directory (on the server), run:

```
sudo python perf_test_of_server_configuration.py.py <URL> <user> <root-of-repo-in-filesystem>

```

This creates and updates a file in <URL>/perfTests/ as a way of testing how good Subversion is at receiving PUTs
via curl for various configurations of Subversion.  It does not test Subsyncit itself.

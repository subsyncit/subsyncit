# Subsyncit

<p align="center"><img src="https://user-images.githubusercontent.com/82182/31454859-dbf012c8-ae84-11e7-8823-ff52c98d12b7.png"/></p>

A file sync client that uses a Subversion repo as a backing-store (in a simple Apache2 server), and does not have any other server-side install.
It is written in Python, works on Windows, Mac and Linux, and does not depend on a Subversion install on the client.

It has been tested with files of random bytes up to 12GB in size. It has also been tested with Subversion repo holding
3.4TB of history.

Corporates would be attracted to this, if:

* They prefer to deploy their own server storage (public or private cloud, on-premises, SBCs in the LAN, containers), rather than trust an online service.
* They want a file-sync solution with strong versioning.
* They already have a subversion instance somewhere.
* They don't want to be charged usage fees, however small.
* Don't mind the lack of mobile device clients (for now)

(Home deployers might like it for the same reasons)

**Fun fact**: Subversion has a hidden Merkle-tree which this tech relies on. If you're super interested, I've blogged on Merkle
trees generally: [1](https://paulhammant.com/2017/09/17/merkle-trees-in-pictures/), [2](https://paulhammant.com/2017/09/17/old-school-merkle-trees-rock/),
[3](https://paulhammant.com/2017/09/28/choosing-between-blockchains-and-vanilla-merkle-trees/).

## Releases

There have not been any releases yet, but Subsyncit certainly works if you've checked it out and launched it from the command line

# Glossary

* Client - a workstation, laptop or mobile device.
* Server - a computer on which a suitable Subversion is installed (Mod_Web_Dav, SVNAutoversioning and others on).
* Remote Subversion Repository (or repo) - on the server, a configuration of subversion that can take commits for so-authorized people.
* Local Sync Directory - on the client a single directory, the contents for which will synchronized up and down to the remote Subversion repo.

# Screenshots

There are none as Subsyncit does not have a user interface (yet).

# Overview

## Features in common with all file-sync technologies

* Brings down added/changed/deleted files from the remote Subversion repo to the client's local sync directory.
* Pushed up added/changed/deleted files from your client's local sync directory to the remote Subversion repo on the server.
* Several people can maintain separate local sync directories and share files on a remote Subversion repo.
* The server always wins; the software simply renames the local file out of the way. Though there's a possibility that for text-forms a three-way merge could be performed (TODO)

## Additional features expected because Subversion is the backing store

* Keeps an audit trail (historical versions)
* Whole directory trees can be checked out en-masse, worked on, and committed back (per normal Svn workflow)
* Branches are a configuration choice for novel usages.

## Why not use a different VCS backing store?

* Subversion speaks WebDAV meaning very simple client technologies can connect
* Subversion allows direct remote access to any resource (or history of the same) without a clone and without a lasting cost to the server
* Subversion allows Per-directry read and read+write permissions. So does Perforce.

## Design goals, counter to the way Subversion normally works:

* Does not maintain a working-tree (or 'working copy' or 'checkout') on the client.
 * there's no .svn/ folder(s).
  * therefore there is only one version of each file on the client system, which is important for large binaries
* No Subversion install on client (if that wasn't obvious)

## Working so far

1. Two-way syncing of add/changes/deletes, including directories, and timer based polling of remote Subversion repo for changes over time.
2. Deliberate 'quiet time' after a local change detected, in in order to not push a partially complete file-write to the remote Subversion repo.
3. Fallback mechanism to detect local sync directory adds/changes/deletes that were not detected or pushed previously.
4. Clash detection using `sha1` - the server always wins, the local changed version is renamed out the way (see above)
5. Ability to reject an incompatible web server - it silently just tries again later (needs work).
6. Standard exclusions via file suffix.

## Yet to develop / needs work

1. UI for prompting user's Subversion id/password.
2. Tray/task bar icon/status.
3. Multiple sync directories (more than one server URL).
4. Directory mask (globbing includes/excludes) per user.
5. Percolation of read-only bits for situations when the end user if not permitted to PUT a file back if the change it. (Rasied with the Subversion dev team: [SVN-4691](https://issues.apache.org/jira/browse/SVN-4691)).
6. Hidden unzipping of MS Office documents on the server side. [I've mulled this before](https://paulhammant.com/2014/10/28/corporate-file-sync-agony-and-ecstasy#vcs-systems-should-be-the-backends-for-file-sync) and [discussed it with the Subversion team](https://groups.google.com/forum/#!topic/subversion-development/YE0F0nYlR-U), but will have to implement it client side.
7. Better Merkle-tree behavior

# Further Reading

1. [Client Setup](https://github.com/paul-hammant/subsyncit/wiki/Subsyncit-Client-Setup)  <-- this is all you need to read if you're trying out Subsyncit.
2. [Server Setup](https://github.com/paul-hammant/subsyncit/wiki/Subversion-Server-Setup)
3. [Contributing to Subsyncit](https://github.com/paul-hammant/subsyncit/wiki/Contributing-to-Subsyncit)
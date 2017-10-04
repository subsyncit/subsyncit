Scroll to the bottom for Amazon EC2, Google Cloud, office, and in-home Raspberry Pi (etc) server choices.

# Server-side setup

General requirement: a server with the following installed and setup:

* Subversion
* Apache2 with mod_dav_svn

# Non-standard Apache2 settings

These are the settings in `httpd.conf ` that you'll need ADD to change in Apache's .conf file after a "default" install.
These allow Subsyncit modes of operation, but do not stop Subversion operating as a normal install for subversion's own clients:

```
<Location /svn>
  # etc
  DavDepthInfinity on
  SVNListParentPath on
  SVNAutoversioning on
  # etc
</Location>
```

# Enforcing Permissions for read/write

By default, Subversion allows anonymous access to files that it holds. Most likely,
you'll not want to do that for the types of file you would want to store in there for corporate assets.

## Basic permissions setup

Two lines in `httpd.conf` should be changed. From:

```
# anon-access = read
# auth-access = write
```

To:

```
anon-access = none
auth-access = write
```

These need to be added to the Subversion block inside `httpd.conf`:

```
<Location /svn>
  # etc
  AuthType Basic
  AuthName "Subversion repository"
  AuthUserFile /opt/bitnami/repository/users
  require valid-user
  # etc
</Location>
```

## Creating users

Use `htpasswd` to create users.

```
sudo htpasswd -c /path/to/authz_users_file <username>
```

You will be prompted to choose a password. Also change `-c` to `-m` for second and subsequent invocations,
as the former overwrites the file.

# Optional Subversion settings for large files

If you are storing large binary files (> 100MB), you may need to change some settings for the Subversion repo too.
Specifically in `<svn_root>/db/fsfs.conf` on the server.

Subversion attempts to align storage with 'deltas' of changes. A large 15GB AVI
file that you changed the resolution of, will have EVERY BYTE different. Therefore
attempting to look for deltas is pointless. If that is your file type, and
changes like that are real, turn off delta-walking, by making the pertinent line like so:


```
max-deltification-walk = 0
```

The compression for large binaries kills performance for changes being pushed
to the server. Turn it off for all file types, by making the pertinent line like so:

```
compression-level = 0
```

# Different choices for Apache2/Subversion servers:

1. [Bitnami-Cloud-Server-Setup](/paul-hammant/subsyncit/wiki/Bitnami-Cloud-Server-Setup) - for Amazon's EC2 platform, Google Cloud (and others)
2. Inexpensive SFF PC with 4TB USB hard drive - TODO
3. Raspberry Pi 0 W with 200GB SD card - TODO
4. Using Subsyncit with Assembla's cloud service - TODO
5. Using Subsyncit with a RhodeCode install - TODO
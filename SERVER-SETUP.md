# Server-side setup

A Subversion server with mod_dav_svn (and Apache2) activated.

## Apache2 settings

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
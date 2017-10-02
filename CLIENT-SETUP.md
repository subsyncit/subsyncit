# Subsyncit client computer installation

Python2 is required, as well as some `pip2` installed modules:

```
pip2 install requests watchdog tinydb
```

## Running Subsyncit

```
python2 subsyncit.py <url-of-subversion-root> <path-to-local-directory-we-want-to-sync-to> <svn-user-name> False <sleep-seconds>
```

When it launches, you get prompted for you subversion password.
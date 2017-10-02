# Subsyncit client computer installation

Python2 is required, as well as some `pip2` installed modules:

```
pip2 install requests watchdog tinydb
```

# Running Subsyncit

```
python2 subsyncit.py <url-of-subversion-root> <path-to-local-directory-we-want-to-sync-to> <svn-user-name>
```

You will be prompted for the applicable's user's password.

### Optional parameters

* `--passwd` to supply the password on the command line (plain text) instead of prompting for secure entry
* `--no-verify-ssl-cert` to ignore certificate errors if you have a self-signed (say for testing)
* `--sleep-secs-between-polling` to supply a number of seconds to wait between poll of the server for changes
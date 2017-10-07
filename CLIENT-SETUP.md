# Installing Subsyncit on a client computer

Python3 is required, as well as some `pip3` installed modules:

```
pip3 install requests watchdog tinydb boltons
```

Note: watchdog sometimes has compile errors on Mac, but [there's a workaround](https://github.com/gorakhargosh/watchdog/issues/422)

# Running Subsyncit

There's only one Python script needed: `subsyncit.py`. Well, other than those pip package installs above.

```
python3 subsyncit.py <url-of-subversion-root> <path-to-local-directory-we-want-to-sync-to> <svn-user-name>
```

**You will be prompted to securely enter the applicable's user's Subversion password**.

### Optional parameters

* `--passwd` to supply the password on the command line (plain text) instead of prompting for secure entry
* `--no-verify-ssl-cert` to ignore certificate errors if you have a self-signed (say for testing)
* `--sleep-secs-between-polling` to supply a number of seconds to wait between poll of the server for changes

# Trying out Subsyncit with a demo Subversion server

```
python3 subsyncit.py https://s.paulhammant.com/subversion/demo <DIR> mark --passwd extff6sh
```

^ Make a directory to sync to, and replace <DIR> above with the path to that directory (fully qualified or relative).

User 'Mark' only has read access, but Subsyncit will bring down two 'Project Gutenberg' ebooks, then keep checking every 30 seconds in case
something else is added to the demo/ folder.

You can do a conventional svn checkout too:

```
svn --username mark --password extff6sh https://s.paulhammant.com/subversion/demo
```

Or view the same content in a browser: [https://s.paulhammant.com/subversion/demo](https://s.paulhammant.com/subversion/demo). Remember to enter the name and password

Note: s.paulhammant.com is a Bitnami cloud instance on Amazon's EC2.
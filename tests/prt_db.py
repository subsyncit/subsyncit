import sys

from tinydb import TinyDB

db_ = sys.argv[1] + "subsyncit.db"

# Need to wait for the other process to release the TinyDB database file
# size = 0
# while size < 350:
#     size = os.stat(db_).st_size
#     if time.time() - start > 45:
#         self.fail("DB should have finished writin to")
#     print(">>" + str(size))
#
# time.sleep(.1)

db = TinyDB(db_)
files_table = db.table('files')

revisions = {}
for row in files_table.all():
    revisions[row['RV']] = 0

# Revisions are normalized down to 1,2,3,4 when they actually might be 12,13,14 in the repo
revision_map = {}
for ix, (key, value) in enumerate(sorted(revisions.items())):
    revision_map[key] = ix + 1

for (key, value) in revision_map.items():
    print("k: " + str(key) + ", v: " + str(value))

rv = ""
for row in files_table.all():
    # ts = str(round((row['ST'] - os.stat(sync_dir + row['RFN']).st_size - test_start) * 1000))
    rv += str(revision_map[row['RV']]).zfill(2) + ", " + str(row['RV']) + ", " + row['RFN'] + ", " + str(row['RS'] )+ ", " + str(row['LS'])  + "\n"

print("\n".join(sorted(rv.splitlines())))

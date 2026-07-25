import sqlite3

conn = sqlite3.connect('evoting.db')

print("=" * 60)
print("TABEL CANDIDATES (Kandidat)")
print("=" * 60)
cur = conn.execute('SELECT * FROM candidates')
for r in cur:
    print(f"  ID: {r[0]}")
    print(f"  Nama: {r[1]}")
    print(f"  Visi: {r[2]}")
    print("-" * 40)

print()
print("=" * 60)
print("TABEL VOTERS (Pemilih)")
print("=" * 60)
cur = conn.execute('SELECT * FROM voters')
for r in cur:
    status = "SUDAH VOTE" if r[2] == 1 else "BELUM VOTE"
    print(f"  ID: {r[0]}")
    print(f"  Nama: {r[1]}")
    print(f"  Status: {status}")
    print("-" * 40)

print()
print("=" * 60)
print("TABEL VOTES (Suara)")
print("=" * 60)
cur = conn.execute('SELECT * FROM votes')
for r in cur:
    print(f"  Vote ID: {r[0]}")
    print(f"  Voter ID: {r[1]}")
    print(f"  Candidate ID: {r[2]}")
    print(f"  Waktu: {r[3]}")
    print("-" * 40)

conn.close()


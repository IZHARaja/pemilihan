import os
import sqlite3
import uuid
from datetime import datetime

from flask import Flask, render_template, request, jsonify, redirect, url_for
import redis

# =========================
# Konfigurasi Awal
# =========================
app = Flask(__name__)
app.secret_key = os.urandom(24)

# Koneksi Redis (pastikan Redis server berjalan di localhost:6379)
try:
    redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
    redis_client.ping()
    REDIS_AVAILABLE = True
except redis.ConnectionError:
    REDIS_AVAILABLE = False
    print("[!] Redis tidak tersedia. Sistem berjalan tanpa cache Redis.")

# Nama database SQLite
DB_NAME = "evoting.db"

# =========================
# Inisialisasi Database
# =========================
def init_db():
    """Membuat tabel-tabel yang diperlukan jika belum ada."""
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    # Tabel kandidat
    cur.execute("""
        CREATE TABLE IF NOT EXISTS candidates (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            vision TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Tabel pemilih
    cur.execute("""
        CREATE TABLE IF NOT EXISTS voters (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            has_voted INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Tabel vote
    cur.execute("""
        CREATE TABLE IF NOT EXISTS votes (
            id TEXT PRIMARY KEY,
            voter_id TEXT NOT NULL,
            candidate_id TEXT NOT NULL,
            timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (voter_id) REFERENCES voters(id),
            FOREIGN KEY (candidate_id) REFERENCES candidates(id),
            UNIQUE(voter_id)
        )
    """)

    conn.commit()
    conn.close()

init_db()

def get_db():
    """Mendapatkan koneksi database SQLite."""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def seed_candidates():
    """Mengisi data kandidat awal jika tabel kosong."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM candidates")
    count = cur.fetchone()[0]
    if count == 0:
        default_candidates = [
            ("c1", "Kandidat Alpha", "Membangun masa depan yang cerah dan inovatif."),
            ("c2", "Kandidat Beta", "Mewujudkan sistem yang adil dan transparan."),
            ("c3", "Kandidat Gamma", "Bersama kita bisa, bersatu kita maju."),
        ]
        cur.executemany(
            "INSERT INTO candidates (id, name, vision) VALUES (?, ?, ?)",
            default_candidates
        )
        conn.commit()
    conn.close()

seed_candidates()

# =========================
# Routes – Halaman Web
# =========================
@app.route('/')
def index():
    """Menampilkan halaman utama pemungutan suara."""
    return render_template('index.html')

# =========================
# Routes – API Endpoints
# =========================
@app.route('/api/candidates', methods=['GET'])
def get_candidates():
    """Mengembalikan daftar kandidat (dengan cache Redis jika tersedia)."""
    # Coba ambil dari Redis cache
    if REDIS_AVAILABLE:
        cached = redis_client.get("candidates")
        if cached:
            import json
            return jsonify({"source": "redis", "data": json.loads(cached)})

    # Ambil dari SQLite
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, name, vision FROM candidates")
    rows = cur.fetchall()
    candidates = [{"id": r["id"], "name": r["name"], "vision": r["vision"]} for r in rows]
    conn.close()

    # Simpan ke Redis cache (expire 60 detik)
    if REDIS_AVAILABLE:
        import json
        redis_client.setex("candidates", 60, json.dumps(candidates))

    return jsonify({"source": "sqlite", "data": candidates})

@app.route('/api/voters', methods=['GET', 'POST'])
def handle_voters():
    if request.method == 'GET':
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT id, name, has_voted FROM voters")
        rows = cur.fetchall()
        voters = [{"id": r["id"], "name": r["name"], "has_voted": bool(r["has_voted"])} for r in rows]
        conn.close()
        return jsonify(voters)

    # POST – Daftar pemilih baru
    data = request.get_json()
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "Nama pemilih tidak boleh kosong"}), 400

    voter_id = str(uuid.uuid4())
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO voters (id, name) VALUES (?, ?)", (voter_id, name))
        conn.commit()
        return jsonify({"message": "Pemilih berhasil didaftarkan", "voter_id": voter_id}), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "Pemilih sudah terdaftar"}), 409
    finally:
        conn.close()

@app.route('/api/vote', methods=['POST'])
def cast_vote():
    """Mencatat suara pemilih."""
    data = request.get_json()
    voter_id = data.get("voter_id", "").strip()
    candidate_id = data.get("candidate_id", "").strip()

    if not voter_id or not candidate_id:
        return jsonify({"error": "voter_id dan candidate_id wajib diisi"}), 400

    conn = get_db()
    cur = conn.cursor()

    # Cek apakah pemilih terdaftar
    cur.execute("SELECT id, has_voted FROM voters WHERE id = ?", (voter_id,))
    voter = cur.fetchone()
    if not voter:
        conn.close()
        return jsonify({"error": "Pemilih tidak terdaftar"}), 404

    if voter["has_voted"]:
        conn.close()
        return jsonify({"error": "Anda sudah memberikan suara"}), 409

    # Cek apakah kandidat ada
    cur.execute("SELECT id FROM candidates WHERE id = ?", (candidate_id,))
    if not cur.fetchone():
        conn.close()
        return jsonify({"error": "Kandidat tidak ditemukan"}), 404

    # Catat vote
    vote_id = str(uuid.uuid4())
    try:
        cur.execute(
            "INSERT INTO votes (id, voter_id, candidate_id) VALUES (?, ?, ?)",
            (vote_id, voter_id, candidate_id)
        )
        cur.execute("UPDATE voters SET has_voted = 1 WHERE id = ?", (voter_id,))
        conn.commit()

        # Hapus cache Redis untuk hasil voting
        if REDIS_AVAILABLE:
            redis_client.delete("results")

        return jsonify({"message": "Suara berhasil dicatat", "vote_id": vote_id}), 201
    except sqlite3.IntegrityError:
        conn.rollback()
        return jsonify({"error": "Gagal mencatat suara"}), 500
    finally:
        conn.close()

@app.route('/api/results', methods=['GET'])
def get_results():
    """Mengembalikan hasil voting (dengan cache Redis jika tersedia)."""
    if REDIS_AVAILABLE:
        cached = redis_client.get("results")
        if cached:
            import json
            return jsonify({"source": "redis", "data": json.loads(cached)})

    conn = get_db()
    cur = conn.cursor()

    # Hitung suara per kandidat
    cur.execute("""
        SELECT c.id, c.name, c.vision, COUNT(v.id) as total_votes
        FROM candidates c
        LEFT JOIN votes v ON c.id = v.candidate_id
        GROUP BY c.id
        ORDER BY total_votes DESC
    """)
    rows = cur.fetchall()
    results = [{
        "candidate_id": r["id"],
        "name": r["name"],
        "vision": r["vision"],
        "total_votes": r["total_votes"]
    } for r in rows]

    # Total pemilih yang sudah memilih
    cur.execute("SELECT COUNT(*) FROM voters WHERE has_voted = 1")
    total_voters = cur.fetchone()[0]

    conn.close()

    data = {
        "total_voters": total_voters,
        "results": results
    }

    if REDIS_AVAILABLE:
        import json
        redis_client.setex("results", 30, json.dumps(data))

    return jsonify({"source": "sqlite", "data": data})

# Menjalankan Aplikasi
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)


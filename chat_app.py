"""
TeamChat — โปรแกรมแชทภายในบริษัท (Flask single file)
Developed by Uncle Engineer — https://uncle-engineer.com/

วิธีใช้:
    pip install flask
    python chat_app.py
แล้วเปิด http://<IP เครื่องนี้>:5000 จากเครื่องไหนก็ได้ในวง LAN

ฟีเจอร์:
  - ตั้งชื่อผู้ใช้ก่อนเข้าใช้งาน
  - สร้างห้องแชทใหม่ ได้รหัสห้องเลข 4 หลักอัตโนมัติ (ไม่ซ้ำ)
  - เข้าห้องด้วยการกรอกรหัส 4 หลัก
  - ข้อความอัปเดตแบบเรียลไทม์ (polling ทุก ~1.5 วินาที) ไม่ต้องลง lib เพิ่ม
  - แสดงรายชื่อคนที่ออนไลน์อยู่ในห้อง
  - เก็บประวัติข้อความใน SQLite (chat.db)
"""
import os
import re
import random
import sqlite3
import time

from flask import (Flask, request, session, redirect, url_for, jsonify,
                   render_template_string, g, flash, abort)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key")
DB_PATH = os.environ.get("CHAT_DB", "chat.db")

MAX_NAME = 30
MAX_ROOM_NAME = 50
MAX_MSG = 2000
ONLINE_WINDOW = 10  # วินาที — ถือว่าออนไลน์ถ้า poll ภายในช่วงนี้


# ───────────────────────────── Database ─────────────────────────────
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, timeout=10)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS rooms (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_by TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_code TEXT NOT NULL,
            author TEXT,              -- NULL = ข้อความระบบ
            body TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_msg_room ON messages(room_code, id);
        CREATE TABLE IF NOT EXISTS presence (
            room_code TEXT NOT NULL,
            name TEXT NOT NULL,
            last_seen REAL NOT NULL,
            PRIMARY KEY (room_code, name)
        );
    """)
    conn.commit()
    conn.close()


def get_room(code):
    return get_db().execute("SELECT * FROM rooms WHERE code=?", (code,)).fetchone()


def new_room_code():
    db = get_db()
    used = {r["code"] for r in db.execute("SELECT code FROM rooms")}
    free = [f"{n:04d}" for n in range(1000, 10000) if f"{n:04d}" not in used]
    if not free:
        return None
    return random.choice(free)


def remember_room(code):
    recent = session.get("recent", [])
    if code in recent:
        recent.remove(code)
    recent.insert(0, code)
    session["recent"] = recent[:8]


# ───────────────────────────── Templates ─────────────────────────────
BASE = r"""<!doctype html>
<html lang="th">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title or 'TeamChat' }}</title>
<script src="https://cdn.tailwindcss.com"></script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Thai:wght@400;500;600;700&display=swap" rel="stylesheet">
<script>
  tailwind.config = { theme: { extend: { fontFamily: { sans: ['"IBM Plex Sans Thai"', 'ui-sans-serif', 'system-ui'] } } } }
</script>
<style>
  .scroll-thin::-webkit-scrollbar{width:6px}
  .scroll-thin::-webkit-scrollbar-thumb{background:#cbd5e1;border-radius:999px}
  @keyframes pop{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
  .pop{animation:pop .18s ease-out}
</style>
</head>
<body class="font-sans antialiased text-slate-800 bg-slate-50">
{% with msgs = get_flashed_messages(with_categories=true) %}
  {% if msgs %}
  <div id="toast" class="fixed top-4 left-1/2 -translate-x-1/2 z-50 space-y-2">
    {% for cat, m in msgs %}
    <div class="px-4 py-2.5 rounded-xl shadow-lg text-sm font-medium
      {{ 'bg-rose-600 text-white' if cat=='error' else 'bg-emerald-600 text-white' }}">{{ m }}</div>
    {% endfor %}
  </div>
  <script>setTimeout(()=>document.getElementById('toast')?.remove(), 3500)</script>
  {% endif %}
{% endwith %}
%%BODY%%
</body>
</html>"""

LOGIN = r"""
<div class="min-h-screen flex items-center justify-center p-4 bg-gradient-to-br from-indigo-600 via-violet-600 to-fuchsia-500">
  <div class="w-full max-w-sm bg-white/95 backdrop-blur rounded-3xl shadow-2xl p-8">
    <div class="flex flex-col items-center text-center mb-6">
      <div class="h-14 w-14 rounded-2xl bg-gradient-to-br from-indigo-500 to-violet-600 flex items-center justify-center shadow-lg mb-4">
        <svg class="h-7 w-7 text-white" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M8 10h8M8 14h5m-9 6l2.5-3H19a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v14z"/></svg>
      </div>
      <h1 class="text-2xl font-bold">TeamChat</h1>
      <p class="text-slate-500 text-sm mt-1">แชทคุยงานภายในบริษัท</p>
    </div>
    <form method="post" action="{{ url_for('login') }}" class="space-y-4">
      <label class="block">
        <span class="text-sm font-medium text-slate-600">ชื่อที่จะแสดงในแชท</span>
        <input name="name" required maxlength="{{ max_name }}" autofocus placeholder="เช่น สมชาย (ฝ่ายผลิต)"
          class="mt-1.5 w-full rounded-xl border border-slate-200 px-4 py-3 focus:outline-none focus:ring-4 focus:ring-indigo-100 focus:border-indigo-400 transition">
      </label>
      <button class="w-full rounded-xl bg-gradient-to-r from-indigo-600 to-violet-600 text-white font-semibold py-3 shadow-lg shadow-indigo-500/30 hover:brightness-110 active:scale-[.99] transition">
        เข้าใช้งาน
      </button>
    </form>
    <p class="mt-6 text-center text-xs text-slate-400">Developed by <a href="https://uncle-engineer.com/" target="_blank" rel="noopener" class="text-indigo-600 font-semibold hover:underline">Uncle Engineer</a></p>
  </div>
</div>
"""

LOBBY = r"""
<div class="min-h-screen bg-gradient-to-b from-indigo-50 to-slate-50">
  <header class="max-w-5xl mx-auto flex items-center justify-between px-4 py-5">
    <div class="flex items-center gap-3">
      <div class="h-10 w-10 rounded-xl bg-gradient-to-br from-indigo-500 to-violet-600 flex items-center justify-center shadow">
        <svg class="h-5 w-5 text-white" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M8 10h8M8 14h5m-9 6l2.5-3H19a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v14z"/></svg>
      </div>
      <span class="text-xl font-bold">TeamChat</span>
    </div>
    <div class="flex items-center gap-3">
      <div class="hidden sm:flex items-center gap-2 bg-white rounded-full pl-1 pr-4 py-1 shadow-sm border border-slate-100">
        <span class="avatar h-8 w-8 rounded-full flex items-center justify-center text-white text-sm font-semibold" data-name="{{ me }}"></span>
        <span class="text-sm font-medium">{{ me }}</span>
      </div>
      <a href="{{ url_for('logout') }}" class="text-sm text-slate-500 hover:text-rose-600 transition">ออกจากระบบ</a>
    </div>
  </header>

  <main class="max-w-5xl mx-auto px-4 pb-16">
    <div class="mb-8">
      <h2 class="text-3xl font-bold">สวัสดี, {{ me }} 👋</h2>
      <p class="text-slate-500 mt-1">สร้างห้องใหม่ หรือกรอกรหัส 4 หลักเพื่อเข้าห้องที่มีอยู่</p>
    </div>

    <div class="grid md:grid-cols-2 gap-6">
      <!-- Join -->
      <div class="bg-white rounded-3xl p-7 shadow-sm border border-slate-100">
        <div class="flex items-center gap-3 mb-5">
          <div class="h-11 w-11 rounded-xl bg-emerald-50 text-emerald-600 flex items-center justify-center">
            <svg class="h-6 w-6" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M11 16l-4-4m0 0l4-4m-4 4h14m-5 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h7a3 3 0 013 3v1"/></svg>
          </div>
          <div>
            <h3 class="font-semibold text-lg">เข้าห้องแชท</h3>
            <p class="text-sm text-slate-500">กรอกรหัสห้อง 4 หลัก</p>
          </div>
        </div>
        <form id="joinForm" method="post" action="{{ url_for('join') }}">
          <input type="hidden" name="code" id="codeHidden">
          <div class="flex gap-3 justify-center mb-5">
            {% for i in range(4) %}
            <input class="digit w-14 h-16 sm:w-16 sm:h-18 text-center text-3xl font-bold rounded-2xl border-2 border-slate-200 focus:border-emerald-500 focus:ring-4 focus:ring-emerald-100 focus:outline-none transition"
              inputmode="numeric" maxlength="1" autocomplete="off" {% if i==0 %}autofocus{% endif %}>
            {% endfor %}
          </div>
          <button class="w-full rounded-xl bg-emerald-600 text-white font-semibold py-3 hover:bg-emerald-700 active:scale-[.99] transition">เข้าห้อง</button>
        </form>
      </div>

      <!-- Create -->
      <div class="bg-white rounded-3xl p-7 shadow-sm border border-slate-100">
        <div class="flex items-center gap-3 mb-5">
          <div class="h-11 w-11 rounded-xl bg-indigo-50 text-indigo-600 flex items-center justify-center">
            <svg class="h-6 w-6" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4"/></svg>
          </div>
          <div>
            <h3 class="font-semibold text-lg">สร้างห้องใหม่</h3>
            <p class="text-sm text-slate-500">ระบบจะสุ่มรหัส 4 หลักให้</p>
          </div>
        </div>
        <form method="post" action="{{ url_for('create') }}" class="space-y-4">
          <input name="room_name" maxlength="{{ max_room }}" placeholder="ชื่อห้อง เช่น ทีม QC, โปรเจกต์ Gearbox"
            class="w-full rounded-xl border border-slate-200 px-4 py-3.5 focus:outline-none focus:ring-4 focus:ring-indigo-100 focus:border-indigo-400 transition">
          <button class="w-full rounded-xl bg-gradient-to-r from-indigo-600 to-violet-600 text-white font-semibold py-3 shadow-lg shadow-indigo-500/20 hover:brightness-110 active:scale-[.99] transition">
            + สร้างห้อง
          </button>
        </form>
      </div>
    </div>

    {% if recent %}
    <section class="mt-10">
      <h3 class="font-semibold text-slate-600 mb-3">ห้องล่าสุดของคุณ</h3>
      <div class="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
        {% for r in recent %}
        <a href="{{ url_for('room', code=r.code) }}" class="group bg-white rounded-2xl p-4 border border-slate-100 shadow-sm hover:shadow-md hover:border-indigo-200 transition">
          <div class="flex items-center justify-between">
            <span class="font-mono text-sm font-bold tracking-widest text-indigo-600 bg-indigo-50 px-2 py-0.5 rounded-lg"># {{ r.code }}</span>
            {% if r.online %}<span class="text-xs text-emerald-600 flex items-center gap-1"><span class="h-2 w-2 rounded-full bg-emerald-500"></span>{{ r.online }} ออนไลน์</span>{% endif %}
          </div>
          <div class="mt-2 font-medium truncate group-hover:text-indigo-700">{{ r.name }}</div>
        </a>
        {% endfor %}
      </div>
    </section>
    {% endif %}
  </main>
  <footer class="max-w-5xl mx-auto px-4 pb-8 text-center text-sm text-slate-400">
    Developed by <a href="https://uncle-engineer.com/" target="_blank" rel="noopener" class="text-indigo-600 font-semibold hover:underline">Uncle Engineer</a>
  </footer>
</div>
<script>
%%AVATAR_JS%%
document.querySelectorAll('.avatar').forEach(paintAvatar);
const digits=[...document.querySelectorAll('.digit')];
const form=document.getElementById('joinForm');
digits.forEach((d,i)=>{
  d.addEventListener('input',e=>{
    d.value=d.value.replace(/\D/g,'').slice(-1);
    if(d.value && i<3) digits[i+1].focus();
    if(digits.every(x=>x.value)) submitJoin();
  });
  d.addEventListener('keydown',e=>{
    if(e.key==='Backspace' && !d.value && i>0){digits[i-1].focus();digits[i-1].value='';}
    if(e.key==='Enter'){e.preventDefault();submitJoin();}
  });
  d.addEventListener('paste',e=>{
    const t=(e.clipboardData.getData('text')||'').replace(/\D/g,'').slice(0,4);
    if(t){e.preventDefault();t.split('').forEach((c,k)=>digits[k].value=c);(digits[t.length]||digits[3]).focus();if(t.length===4)submitJoin();}
  });
});
function submitJoin(){
  const code=digits.map(x=>x.value).join('');
  if(code.length!==4){digits.find(x=>!x.value)?.focus();return;}
  document.getElementById('codeHidden').value=code;form.submit();
}
form.addEventListener('submit',e=>{e.preventDefault();submitJoin();});
</script>
"""

ROOM = r"""
<div class="h-[100dvh] flex flex-col bg-slate-100">
  <!-- Header -->
  <header class="bg-white border-b border-slate-200 px-3 sm:px-5 py-3 flex items-center gap-3 shadow-sm z-10">
    <a href="{{ url_for('index') }}" class="h-10 w-10 rounded-xl hover:bg-slate-100 flex items-center justify-center text-slate-500 transition" title="กลับ">
      <svg class="h-5 w-5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M15 19l-7-7 7-7"/></svg>
    </a>
    <div class="h-10 w-10 rounded-xl bg-gradient-to-br from-indigo-500 to-violet-600 text-white flex items-center justify-center font-bold shadow">
      {{ room.name[:1] }}
    </div>
    <div class="min-w-0 flex-1">
      <h1 class="font-semibold truncate leading-tight">{{ room.name }}</h1>
      <p class="text-xs text-slate-500 flex items-center gap-1.5">
        <span class="h-2 w-2 rounded-full bg-emerald-500"></span><span id="onlineCount">–</span> คนออนไลน์
      </p>
    </div>
    <button id="copyBtn" class="flex items-center gap-2 rounded-xl bg-indigo-50 hover:bg-indigo-100 text-indigo-700 px-3 py-2 transition" title="คัดลอกรหัสห้อง">
      <span class="text-xs hidden sm:inline">รหัสห้อง</span>
      <span class="font-mono font-bold tracking-[.25em]">{{ room.code }}</span>
      <svg class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>
    </button>
    <button id="membersBtn" class="lg:hidden h-10 w-10 rounded-xl hover:bg-slate-100 flex items-center justify-center text-slate-500" title="สมาชิก">
      <svg class="h-5 w-5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M17 20h5v-2a3 3 0 00-5.4-1.8M17 20H7m10 0v-2c0-.7-.1-1.3-.4-1.8M7 20H2v-2a3 3 0 015.4-1.8M7 20v-2c0-.7.1-1.3.4-1.8m0 0a5 5 0 019.2 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"/></svg>
    </button>
  </header>

  <div class="flex-1 flex min-h-0">
    <!-- Messages -->
    <div class="flex-1 flex flex-col min-w-0">
      <div id="messages" class="flex-1 overflow-y-auto scroll-thin px-3 sm:px-6 py-5 space-y-1">
        <div id="loading" class="text-center text-slate-400 text-sm py-10">กำลังโหลดข้อความ…</div>
      </div>
      <!-- Composer -->
      <form id="composer" class="bg-white border-t border-slate-200 p-3 sm:p-4">
        <div class="flex items-end gap-2 max-w-4xl mx-auto">
          <textarea id="input" rows="1" maxlength="{{ max_msg }}" placeholder="พิมพ์ข้อความ…" title="Enter ส่ง · Shift+Enter ขึ้นบรรทัดใหม่"
            class="flex-1 resize-none max-h-40 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 focus:bg-white focus:outline-none focus:ring-4 focus:ring-indigo-100 focus:border-indigo-400 transition"></textarea>
          <button id="sendBtn" class="h-12 w-12 shrink-0 rounded-2xl bg-gradient-to-br from-indigo-600 to-violet-600 text-white flex items-center justify-center shadow-lg shadow-indigo-500/30 hover:brightness-110 active:scale-95 disabled:opacity-40 transition">
            <svg class="h-5 w-5 rotate-90" fill="none" stroke="currentColor" stroke-width="2.2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M12 19V5m0 0l-7 7m7-7l7 7"/></svg>
          </button>
        </div>
      </form>
    </div>

    <!-- Members sidebar -->
    <aside id="members" class="hidden lg:flex w-64 flex-col bg-white border-l border-slate-200
        fixed lg:static inset-y-0 right-0 z-20 shadow-2xl lg:shadow-none">
      <div class="px-5 py-4 border-b border-slate-100 flex items-center justify-between">
        <h2 class="font-semibold">ออนไลน์ตอนนี้</h2>
        <button id="closeMembers" class="lg:hidden text-slate-400 hover:text-slate-700 text-xl leading-none">&times;</button>
      </div>
      <ul id="memberList" class="flex-1 overflow-y-auto scroll-thin p-3 space-y-1"></ul>
      <div class="p-4 border-t border-slate-100 text-xs text-slate-500">
        ชวนเพื่อนร่วมงานเข้าห้องด้วยรหัส <span class="font-mono font-bold text-indigo-600">{{ room.code }}</span>
        <div class="mt-2 text-slate-400">Developed by <a href="https://uncle-engineer.com/" target="_blank" rel="noopener" class="text-indigo-600 font-semibold hover:underline">Uncle Engineer</a></div>
      </div>
    </aside>
  </div>
</div>

<script>
%%AVATAR_JS%%
const CODE = {{ room.code|tojson }};
const ME = {{ me|tojson }};
const API = "{{ url_for('api_messages', code=room.code) }}";
let lastId = 0, lastAuthor = null, lastTime = 0, lastDay = null, polling = false;

const box = document.getElementById('messages');
const input = document.getElementById('input');
const sendBtn = document.getElementById('sendBtn');

function fmtTime(t){return new Date(t*1000).toLocaleTimeString('th-TH',{hour:'2-digit',minute:'2-digit'});}
function fmtDay(t){
  const d=new Date(t*1000), today=new Date(), y=new Date(); y.setDate(today.getDate()-1);
  if(d.toDateString()===today.toDateString()) return 'วันนี้';
  if(d.toDateString()===y.toDateString()) return 'เมื่อวาน';
  return d.toLocaleDateString('th-TH',{day:'numeric',month:'long',year:'numeric'});
}
function el(tag, cls, text){const e=document.createElement(tag); if(cls) e.className=cls; if(text!=null) e.textContent=text; return e;}
function nearBottom(){return box.scrollHeight - box.scrollTop - box.clientHeight < 120;}

function addMessage(m){
  const day = fmtDay(m.created_at);
  if(day !== lastDay){
    const d = el('div','flex items-center gap-3 my-4 text-xs text-slate-400');
    d.append(el('div','flex-1 h-px bg-slate-200'), el('span','px-2',day), el('div','flex-1 h-px bg-slate-200'));
    box.append(d); lastDay = day; lastAuthor = null;
  }
  if(m.author === null){
    const s = el('div','flex justify-center my-3 pop');
    s.append(el('span','text-xs bg-white/70 text-slate-500 px-3 py-1 rounded-full border border-slate-200', m.body));
    box.append(s); lastAuthor = null; return;
  }
  const mine = m.author === ME;
  const grouped = m.author === lastAuthor && (m.created_at - lastTime) < 180;
  const row = el('div', `flex gap-2.5 pop ${mine ? 'justify-end' : ''} ${grouped ? 'mt-0.5' : 'mt-4'}`);
  if(!mine){
    const av = el('div','avatar h-9 w-9 shrink-0 rounded-full flex items-center justify-center text-white text-sm font-semibold');
    av.dataset.name = m.author; paintAvatar(av);
    if(grouped) av.style.visibility='hidden';
    row.append(av);
  }
  const col = el('div', `flex flex-col max-w-[78%] sm:max-w-[65%] ${mine ? 'items-end' : 'items-start'}`);
  if(!grouped && !mine) col.append(el('span','text-xs font-semibold text-slate-600 mb-1 ml-1', m.author));
  const bubble = el('div', `px-4 py-2.5 rounded-2xl whitespace-pre-wrap break-words leading-relaxed shadow-sm ${
      mine ? 'bg-gradient-to-br from-indigo-600 to-violet-600 text-white rounded-br-md'
           : 'bg-white text-slate-800 rounded-bl-md border border-slate-100'}`, m.body);
  bubble.title = fmtTime(m.created_at);
  const wrap = el('div', `flex items-end gap-1.5 ${mine ? 'flex-row-reverse' : ''}`);
  wrap.append(bubble, el('span','text-[10px] text-slate-400 mb-1 shrink-0', fmtTime(m.created_at)));
  col.append(wrap); row.append(col); box.append(row);
  lastAuthor = m.author; lastTime = m.created_at;
}

function renderMembers(list){
  document.getElementById('onlineCount').textContent = list.length;
  const ul = document.getElementById('memberList'); ul.innerHTML = '';
  list.forEach(n=>{
    const li = el('li','flex items-center gap-3 px-2 py-2 rounded-xl hover:bg-slate-50');
    const av = el('div','avatar relative h-9 w-9 rounded-full flex items-center justify-center text-white text-sm font-semibold');
    av.dataset.name = n; paintAvatar(av);
    av.append(el('span','absolute -bottom-0.5 -right-0.5 h-3 w-3 rounded-full bg-emerald-500 ring-2 ring-white'));
    li.append(av, el('span','text-sm font-medium truncate', n + (n===ME ? ' (คุณ)' : '')));
    ul.append(li);
  });
}

async function poll(){
  if(polling) return; polling = true;
  try{
    const r = await fetch(`${API}?after=${lastId}`);
    if(r.ok){
      const data = await r.json();
      document.getElementById('loading')?.remove();
      const stick = nearBottom() || lastId === 0;
      data.messages.forEach(m=>{ addMessage(m); lastId = Math.max(lastId, m.id); });
      if(data.messages.length && stick) box.scrollTop = box.scrollHeight;
      renderMembers(data.online);
      if(lastId===0 && !box.children.length)
        box.innerHTML = '<div id="loading" class="text-center text-slate-400 text-sm py-10">ยังไม่มีข้อความ เริ่มคุยกันเลย!</div>';
    } else if(r.status === 401){ location.href = "{{ url_for('index') }}"; }
  }catch(e){}
  polling = false;
}

async function send(){
  const body = input.value.trim(); if(!body) return;
  sendBtn.disabled = true;
  try{
    const r = await fetch(API,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({body})});
    if(r.ok){ input.value=''; autosize(); await poll(); box.scrollTop = box.scrollHeight; }
  } finally { sendBtn.disabled = false; input.focus(); }
}

function autosize(){ input.style.height='auto'; input.style.height = Math.min(input.scrollHeight,160)+'px'; }
input.addEventListener('input', autosize);
input.addEventListener('keydown', e=>{ if(e.key==='Enter' && !e.shiftKey && !e.isComposing){ e.preventDefault(); send(); } });
document.getElementById('composer').addEventListener('submit', e=>{ e.preventDefault(); send(); });

document.getElementById('copyBtn').addEventListener('click', async e=>{
  const btn = e.currentTarget;
  try{ await navigator.clipboard.writeText(CODE); }catch(_){
    const t=document.createElement('textarea'); t.value=CODE; document.body.append(t); t.select(); document.execCommand('copy'); t.remove();
  }
  btn.classList.add('ring-2','ring-emerald-400'); setTimeout(()=>btn.classList.remove('ring-2','ring-emerald-400'),900);
});
const members = document.getElementById('members');
document.getElementById('membersBtn').addEventListener('click',()=>{members.classList.remove('hidden');members.classList.add('flex');});
document.getElementById('closeMembers').addEventListener('click',()=>{members.classList.add('hidden');members.classList.remove('flex');});

poll(); setInterval(poll, 1500); input.focus();
</script>
"""

AVATAR_JS = r"""
function paintAvatar(el){
  const n = el.dataset.name || '?';
  const colors = ['#6366f1','#8b5cf6','#ec4899','#f43f5e','#f97316','#eab308','#22c55e','#14b8a6','#0ea5e9','#3b82f6'];
  let h = 0; for(const c of n) h = (h*31 + c.codePointAt(0)) >>> 0;
  el.style.background = colors[h % colors.length];
  if(!el.firstChild || el.firstChild.nodeType!==3) el.prepend(document.createTextNode([...n.trim()][0]?.toUpperCase() || '?'));
}
"""


def page(body, **ctx):
    tpl = BASE.replace("%%BODY%%", body.replace("%%AVATAR_JS%%", AVATAR_JS))
    return render_template_string(tpl, **ctx)


# ───────────────────────────── Routes ─────────────────────────────
@app.route("/")
def index():
    me = session.get("name")
    if not me:
        return page(LOGIN, title="เข้าสู่ระบบ · TeamChat", max_name=MAX_NAME)
    db = get_db()
    now = time.time()
    recent = []
    for code in session.get("recent", []):
        r = get_room(code)
        if r:
            online = db.execute("SELECT COUNT(*) FROM presence WHERE room_code=? AND last_seen>?",
                                (code, now - ONLINE_WINDOW)).fetchone()[0]
            recent.append({"code": r["code"], "name": r["name"], "online": online})
    return page(LOBBY, title="TeamChat", me=me, recent=recent, max_room=MAX_ROOM_NAME)


@app.post("/login")
def login():
    name = re.sub(r"\s+", " ", request.form.get("name", "")).strip()[:MAX_NAME]
    if not name:
        flash("กรุณากรอกชื่อ", "error")
    else:
        session["name"] = name
    return redirect(url_for("index"))


@app.route("/logout")
def logout():
    session.pop("name", None)
    return redirect(url_for("index"))


@app.post("/create")
def create():
    me = session.get("name")
    if not me:
        return redirect(url_for("index"))
    room_name = request.form.get("room_name", "").strip()[:MAX_ROOM_NAME] or f"ห้องของ {me}"
    db = get_db()
    code = new_room_code()
    if code is None:
        flash("ห้องเต็มแล้ว (ใช้รหัสครบ 9,000 ห้อง)", "error")
        return redirect(url_for("index"))
    now = time.time()
    db.execute("INSERT INTO rooms (code, name, created_by, created_at) VALUES (?,?,?,?)",
               (code, room_name, me, now))
    db.execute("INSERT INTO messages (room_code, author, body, created_at) VALUES (?,?,?,?)",
               (code, None, f"{me} สร้างห้อง “{room_name}” · รหัสห้อง {code}", now))
    db.commit()
    flash(f"สร้างห้องสำเร็จ รหัสห้องคือ {code}", "ok")
    return redirect(url_for("room", code=code))


@app.post("/join")
def join():
    if not session.get("name"):
        return redirect(url_for("index"))
    code = request.form.get("code", "").strip()
    if not re.fullmatch(r"\d{4}", code):
        flash("รหัสห้องต้องเป็นตัวเลข 4 หลัก", "error")
    elif not get_room(code):
        flash(f"ไม่พบห้องรหัส {code}", "error")
    else:
        return redirect(url_for("room", code=code))
    return redirect(url_for("index"))


@app.route("/room/<code>")
def room(code):
    me = session.get("name")
    if not me:
        return redirect(url_for("index"))
    r = get_room(code)
    if not r:
        flash(f"ไม่พบห้องรหัส {code}", "error")
        return redirect(url_for("index"))
    remember_room(code)
    return page(ROOM, title=f"{r['name']} · #{code}", me=me, room=r, max_msg=MAX_MSG)


@app.route("/api/room/<code>/messages", methods=["GET", "POST"])
def api_messages(code):
    me = session.get("name")
    if not me:
        return jsonify(error="unauthorized"), 401
    if not get_room(code):
        abort(404)
    db = get_db()
    now = time.time()

    if request.method == "POST":
        body = str((request.get_json(silent=True) or {}).get("body", "")).strip()[:MAX_MSG]
        if not body:
            return jsonify(error="empty"), 400
        db.execute("INSERT INTO messages (room_code, author, body, created_at) VALUES (?,?,?,?)",
                   (code, me, body, now))
        db.commit()
        return jsonify(ok=True)

    # GET: ดึงข้อความใหม่ + อัปเดตสถานะออนไลน์
    try:
        after = int(request.args.get("after", 0))
    except ValueError:
        after = 0
    db.execute("INSERT INTO presence (room_code, name, last_seen) VALUES (?,?,?) "
               "ON CONFLICT(room_code, name) DO UPDATE SET last_seen=excluded.last_seen",
               (code, me, now))
    db.commit()
    if after == 0:  # โหลดครั้งแรก: เอา 200 ข้อความล่าสุด
        rows = db.execute("SELECT * FROM (SELECT * FROM messages WHERE room_code=? ORDER BY id DESC LIMIT 200) "
                          "ORDER BY id", (code,)).fetchall()
    else:
        rows = db.execute("SELECT * FROM messages WHERE room_code=? AND id>? ORDER BY id LIMIT 500",
                          (code, after)).fetchall()
    online = [r["name"] for r in db.execute(
        "SELECT name FROM presence WHERE room_code=? AND last_seen>? ORDER BY name",
        (code, now - ONLINE_WINDOW))]
    return jsonify(
        messages=[{"id": r["id"], "author": r["author"], "body": r["body"], "created_at": r["created_at"]}
                  for r in rows],
        online=online,
    )


init_db()

if __name__ == "__main__":
    # host=0.0.0.0 เพื่อให้เครื่องอื่นในวง LAN เข้าได้
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False, threaded=True)

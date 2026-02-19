import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import streamlit as st
import requests
from datetime import datetime

API_URL = "http://localhost:8000"

st.set_page_config(
    page_title="DegreeFYD Assistant",
    page_icon="🎓",
    layout="centered",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;900&display=swap" rel="stylesheet">
<style>
    html,body,[class*="css"]{font-family:'Inter',sans-serif;}
    .stApp{background:#eef0f8;}
    #MainMenu,footer,header{visibility:hidden;}
    [data-testid="stSidebar"]{display:none;}
    .block-container{padding:1rem 1rem 2rem!important;max-width:520px!important;}

    /* Top bar */
    .topbar{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;}
    .topbar-logo{display:flex;align-items:center;gap:8px;}
    .topbar-avatar{width:32px;height:32px;border-radius:50%;background:linear-gradient(135deg,#4f46e5,#7c3aed);display:flex;align-items:center;justify-content:center;color:white;font-weight:900;font-size:14px;}
    .topbar-name{font-weight:700;font-size:15px;color:#1e293b;}
    .web-btn-on{background:#fef3c7;border:1.5px solid #fcd34d;color:#92400e;padding:5px 12px;border-radius:20px;font-size:11px;font-weight:700;cursor:pointer;display:inline-block;}
    .web-btn-off{background:white;border:1.5px solid #e2e8f0;color:#64748b;padding:5px 12px;border-radius:20px;font-size:11px;font-weight:700;cursor:pointer;display:inline-block;}

    /* Blob logo */
    .blob-wrap{display:flex;justify-content:center;padding:8px 0 16px;}
    .blob{width:80px;height:80px;border-radius:40% 60% 55% 45%/45% 55% 60% 40%;background:linear-gradient(135deg,#6366f1,#8b5cf6,#4f46e5);display:flex;align-items:center;justify-content:center;color:white;font-size:28px;font-weight:900;box-shadow:0 8px 24px rgba(99,102,241,0.35);}

    /* Category cards row */
    .cat-row{display:flex;gap:10px;overflow-x:auto;padding-bottom:12px;scrollbar-width:none;}
    .cat-row::-webkit-scrollbar{display:none;}
    .cat-card{flex-shrink:0;width:100px;height:76px;border-radius:16px;background:rgba(255,255,255,0.6);border:1.5px solid transparent;display:flex;flex-direction:column;align-items:center;justify-content:center;cursor:pointer;transition:all 0.2s;}
    .cat-card.active{background:white;border-color:#c7d2fe;box-shadow:0 4px 12px rgba(99,102,241,0.15);}
    .cat-card-icon{font-size:22px;margin-bottom:4px;}
    .cat-card-label{font-size:11px;font-weight:600;color:#64748b;text-align:center;line-height:1.2;}
    .cat-card.active .cat-card-label{color:#4f46e5;}
    .cat-card-dot{width:16px;height:2px;background:#6366f1;border-radius:2px;margin-top:4px;}

    /* Main card */
    .main-card{background:white;border-radius:24px;box-shadow:0 4px 24px rgba(0,0,0,0.07);overflow:hidden;margin-bottom:12px;}
    .card-header{padding:20px 20px 12px;position:relative;}
    .card-watermark{position:absolute;top:12px;right:14px;font-size:52px;opacity:0.08;line-height:1;pointer-events:none;user-select:none;}
    .card-title{font-size:22px;font-weight:900;color:#0f172a;margin:0;}
    .card-desc{font-size:12px;color:#94a3b8;margin:2px 0 0;padding-right:60px;}

    /* Sub-tabs */
    .subtab-row{display:flex;gap:6px;margin-top:12px;overflow-x:auto;scrollbar-width:none;flex-wrap:nowrap;}
    .subtab-row::-webkit-scrollbar{display:none;}
    .subtab{padding:5px 14px;border-radius:20px;font-size:12px;font-weight:600;border:1.5px solid #e2e8f0;background:white;color:#64748b;white-space:nowrap;cursor:pointer;}
    .subtab.active{background:#0f172a;color:white;border-color:#0f172a;}

    /* Sample rows */
    .sample-row{display:flex;align-items:center;justify-content:space-between;padding:13px 14px;border-radius:12px;background:#f0f2fa;margin-bottom:8px;cursor:pointer;transition:background 0.15s;}
    .sample-row:hover{background:#e0e7ff;}
    .sample-text{font-size:13px;color:#374151;line-height:1.4;flex:1;}
    .sample-arrow{color:#9ca3af;font-size:14px;flex-shrink:0;margin-left:8px;}

    /* Chat messages */
    .msg-user{display:flex;justify-content:flex-end;margin:10px 0;}
    .msg-user-bubble{background:#4f46e5;color:white;padding:10px 16px;border-radius:18px 18px 4px 18px;max-width:76%;font-size:13px;line-height:1.6;box-shadow:0 2px 8px rgba(79,70,229,0.2);}
    .msg-bot-row{display:flex;gap:8px;margin:10px 0;align-items:flex-start;}
    .msg-bot-av{width:28px;height:28px;border-radius:50%;background:linear-gradient(135deg,#4f46e5,#7c3aed);display:flex;align-items:center;justify-content:center;color:white;font-weight:900;font-size:11px;flex-shrink:0;margin-top:2px;}
    .msg-bot-inner{max-width:86%;}
    .msg-badges{display:flex;gap:5px;margin-bottom:5px;flex-wrap:wrap;}
    .badge-cat{background:#ede9fe;color:#5b21b6;padding:2px 8px;border-radius:8px;font-size:10px;font-weight:700;}
    .badge-web{background:#fef3c7;color:#b45309;padding:2px 8px;border-radius:8px;font-size:10px;font-weight:700;}
    .badge-local{background:#dcfce7;color:#166534;padding:2px 8px;border-radius:8px;font-size:10px;font-weight:700;}
    .msg-bot-bubble{background:#f0f2fa;padding:12px 14px;border-radius:4px 16px 16px 16px;font-size:13px;line-height:1.7;color:#1e293b;}
    .msg-time{font-size:10px;color:#cbd5e1;margin-top:3px;}

    /* Counselling row */
    .counsel-row{display:flex;align-items:center;justify-content:space-between;padding:8px 16px;border-top:1px solid #f8fafc;}
    .counsel-text{font-size:11px;color:#94a3b8;}
    .counsel-pill{display:inline-flex;align-items:center;gap:5px;background:white;border:1.5px solid #e2e8f0;border-radius:20px;padding:3px 12px;font-size:11px;font-weight:600;color:#374151;cursor:pointer;}
    .counsel-dot{width:7px;height:7px;border-radius:50%;background:#22c55e;display:inline-block;}

    /* Input */
    .stTextInput>div>div>input{border-radius:24px!important;border:none!important;background:#f0f2fa!important;padding:11px 18px!important;font-size:13px!important;color:#374151!important;}
    .stTextInput>div>div>input:focus{box-shadow:0 0 0 2px rgba(99,102,241,0.2)!important;}
    .stFormSubmitButton>button{border-radius:50%!important;background:#374151!important;color:white!important;border:none!important;width:38px!important;height:38px!important;padding:0!important;font-size:16px!important;min-height:0!important;}
    .stFormSubmitButton>button:hover{background:#4f46e5!important;}
    .footer-note{text-align:center;font-size:11px;color:#94a3b8;margin-top:4px;}
</style>
""", unsafe_allow_html=True)

# ── Session State ─────────────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []
if "web_search_enabled" not in st.session_state:
    st.session_state.web_search_enabled = False
if "active_category" not in st.session_state:
    st.session_state.active_category = "COLLEGE"

CATEGORY_CONFIG = {
    "COLLEGE":     {"label":"Colleges",    "icon":"🏫", "desc":"Ask your query related to admissions, fees, placements, cutoffs etc",
                   "subtabs":["All","Admissions","Fees","Facility","Placements"],
                   "samples":["How can I get admission to VIT Vellore?","How much is the fee at DTU?","What are the hostel facilities at IIT Bombay?","Which companies visited LPU for placements?","What scholarships are available at Amity University?"]},
    "EXAM":        {"label":"Exams",       "icon":"📝", "desc":"Get answers on dates, syllabus, admit cards, prep tips",
                   "subtabs":["All","Admit Card","Mock Test","Results","Dates"],
                   "samples":["What is the exam pattern for JEE Main?","Where can I download MHT CET admit card?","When will JEE Advanced application begin?","What is the CLAT 2026 exam date?","What is the syllabus for GATE 2026?"]},
    "COMPARISON":  {"label":"Comparisons", "icon":"⚖️", "desc":"Compare colleges on fees, rankings, placements, facilities",
                   "subtabs":["All","Compare Colleges"],
                   "samples":["Which has better placements, VIT or Amrita?","Compare IIM Indore vs IIM Kozhikode","Which has better NIRF rank, LPU or Chandigarh University?","Fee difference between Amity Gurugram and Amity Lucknow?","IIT Bombay vs IIT Delhi campus facilities?"]},
    "PREDICTOR":   {"label":"Predictors",  "icon":"🔮", "desc":"Predict colleges based on rank, scores, percentiles",
                   "subtabs":["All","College Predictor","Admission Chances"],
                   "samples":["Which colleges accept 70 rank in JEE Main?","Best colleges for 70 percentile in MHT CET?","Can I get into top colleges with rank 70 in TS EAMCET?","Cutoffs for all branches at DTU?","VIT Vellore cutoff for this year?"]},
    "TOP_COLLEGES":{"label":"Top Colleges","icon":"🏆", "desc":"Explore top colleges by location, ranking, course",
                   "subtabs":["All","Colleges by Location","Top Ranked"],
                   "samples":["B.E. / B.Tech colleges in India","Top Ranked colleges in Mumbai","Private engineering colleges in Bangalore","Top Ranked colleges in Jaipur","Popular colleges in Kolkata"]},
}


def send_query(query: str, category: str, web_search: bool) -> dict:
    try:
        resp = requests.post(
            f"{API_URL}/chat",
            json={"query": query, "category": category, "web_search_enabled": web_search},
            timeout=90
        )
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.ConnectionError:
        return {"answer": "⚠️ Cannot connect to the API server. Make sure it is running on port 8000.",
                "category_detected": category, "web_search_used": False, "has_local_results": False, "entities": {}}
    except Exception as e:
        return {"answer": f"⚠️ Error: {str(e)}",
                "category_detected": category, "web_search_used": False, "has_local_results": False, "entities": {}}


# ── Top bar ───────────────────────────────────────────────────────────────────
web_cls = "web-btn-on" if st.session_state.web_search_enabled else "web-btn-off"
web_label = "🌐 Web ON" if st.session_state.web_search_enabled else "📵 Web OFF"
st.markdown(
    f'<div class="topbar">'
    f'<div class="topbar-logo"><div class="topbar-avatar">D</div><span class="topbar-name">DegreeFYD</span></div>'
    f'<span class="{web_cls}">{web_label}</span>'
    f'</div>',
    unsafe_allow_html=True
)
col_toggle = st.columns([4,1])[1]
with col_toggle:
    st.session_state.web_search_enabled = st.toggle("", value=st.session_state.web_search_enabled, label_visibility="collapsed")

# ── Blob logo ─────────────────────────────────────────────────────────────────
st.markdown('<div class="blob-wrap"><div class="blob">D</div></div>', unsafe_allow_html=True)

# ── Category cards ────────────────────────────────────────────────────────────
cat_keys = list(CATEGORY_CONFIG.keys())
cat_html = '<div class="cat-row">'
for ck in cat_keys:
    cv = CATEGORY_CONFIG[ck]
    is_active = st.session_state.active_category == ck
    cls = "cat-card active" if is_active else "cat-card"
    dot = '<div class="cat-card-dot"></div>' if is_active else ''
    cat_html += (
        f'<div class="{cls}">'
        f'<div class="cat-card-icon">{cv["icon"]}</div>'
        f'<div class="cat-card-label">{cv["label"]}</div>'
        f'{dot}</div>'
    )
cat_html += '</div>'
st.markdown(cat_html, unsafe_allow_html=True)

cols = st.columns(len(cat_keys))
for i, ck in enumerate(cat_keys):
    with cols[i]:
        if st.button(CATEGORY_CONFIG[ck]["label"], key=f"cat_{ck}", use_container_width=True, label_visibility="collapsed" if False else "visible"):
            st.session_state.active_category = ck
            st.rerun()

st.markdown('<style>.stButton>button{background:transparent!important;border:none!important;color:transparent!important;height:1px!important;padding:0!important;margin:0!important;min-height:0!important;}</style>', unsafe_allow_html=True)


# ── Main Panel ────────────────────────────────────────────────────────────────
active = CATEGORY_CONFIG[st.session_state.active_category]
active_key = st.session_state.active_category

# Card header with watermark
subtabs_html = '<div class="subtab-row">'
for t in active["subtabs"]:
    cls = "subtab active" if t == "All" else "subtab"
    subtabs_html += f'<span class="{cls}">{t}</span>'
subtabs_html += '</div>'

st.markdown(
    f'<div class="main-card">'
    f'<div class="card-header">'
    f'<div class="card-watermark">{active["icon"]}</div>'
    f'<div class="card-title">{active["label"]}</div>'
    f'<div class="card-desc">{active["desc"]}</div>'
    f'{subtabs_html}'
    f'</div>',
    unsafe_allow_html=True
)

# Sample questions (shown when no messages)
if not st.session_state.messages:
    for sample in active["samples"]:
        if st.button(
            f'{sample}  ▶',
            key=f"sq_{active_key}_{sample}",
            use_container_width=True
        ):
            st.session_state.messages.append({"role": "user", "content": sample, "time": datetime.now().strftime("%H:%M")})
            with st.spinner("Thinking..."):
                result = send_query(sample, active_key, st.session_state.web_search_enabled)
            st.session_state.messages.append({
                "role": "assistant", "content": result["answer"],
                "category": result["category_detected"], "web_used": result["web_search_used"],
                "local": result["has_local_results"], "time": datetime.now().strftime("%H:%M")
            })
            st.rerun()
    st.markdown(
        '<style>.stButton>button{background:#f0f2fa!important;border:none!important;color:#374151!important;'
        'text-align:left!important;border-radius:12px!important;padding:13px 14px!important;'
        'font-size:13px!important;font-weight:400!important;margin-bottom:6px!important;height:auto!important;}</style>',
        unsafe_allow_html=True
    )
else:
    # Chat messages
    for msg in st.session_state.messages:
        t = msg.get("time", "")
        if msg["role"] == "user":
            st.markdown(
                f'<div class="msg-user"><div class="msg-user-bubble">{msg["content"]}</div></div>'
                f'<div style="text-align:right"><span class="msg-time">{t}</span></div>',
                unsafe_allow_html=True
            )
        else:
            cat = msg.get("category", "")
            web = msg.get("web_used", False)
            local = msg.get("local", False)
            badges = f'<span class="badge-cat">{cat}</span>' if cat else ""
            if web:
                badges += ' <span class="badge-web">🌐 Web</span>'
            if local:
                badges += ' <span class="badge-local">✅ Local</span>'
            st.markdown(
                f'<div class="msg-bot-row">'
                f'<div class="msg-bot-av">D</div>'
                f'<div class="msg-bot-inner">'
                f'<div class="msg-badges">{badges}</div>',
                unsafe_allow_html=True
            )
            st.markdown(msg["content"])
            st.markdown(f'<div class="msg-time">{t}</div></div></div>', unsafe_allow_html=True)

# Counselling row
counsel_html = (
    '<div class="counsel-row">'
    '<span class="counsel-text">You might be interested in: '
    '<span class="counsel-pill"><span class="counsel-dot"></span>Get Free Counselling</span>'
    '</span>'
)
if st.session_state.messages:
    counsel_html += '<span style="font-size:11px;color:#d1d5db;cursor:pointer" title="Clear chat">🗑</span>'
counsel_html += '</div></div>'  # close main-card
st.markdown(counsel_html, unsafe_allow_html=True)

if st.session_state.messages:
    if st.button("🗑 Clear", key="clear_chat"):
        st.session_state.messages = []
        st.rerun()

# Input form
with st.form(key="chat_form", clear_on_submit=True):
    col_input, col_btn = st.columns([6, 1])
    with col_input:
        user_input = st.text_input(
            "query", placeholder="Write your query on colleges, exam here...",
            label_visibility="collapsed"
        )
    with col_btn:
        submitted = st.form_submit_button("➤", use_container_width=True)

st.markdown('<div class="footer-note">DegreeFYD Assistant is experimental &amp; accuracy might vary</div>', unsafe_allow_html=True)

if submitted and user_input.strip():
    st.session_state.messages.append({"role": "user", "content": user_input.strip(), "time": datetime.now().strftime("%H:%M")})
    with st.spinner("Thinking..."):
        result = send_query(user_input.strip(), active_key, st.session_state.web_search_enabled)
    st.session_state.messages.append({
        "role": "assistant", "content": result["answer"],
        "category": result["category_detected"], "web_used": result["web_search_used"],
        "local": result["has_local_results"], "time": datetime.now().strftime("%H:%M")
    })
    st.rerun()

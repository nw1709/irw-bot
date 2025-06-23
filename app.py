import streamlit as st
from anthropic import Anthropic
from openai import OpenAI
from PIL import Image
import google.generativeai as genai
import logging
import hashlib
import re

# --- Logger Setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- API Key Validation ---
def validate_keys():
    required_keys = {
        'gemini_key': ('AIza', "Gemini"),
        'claude_key': ('sk-ant', "Claude"),
        'openai_key': ('sk-', "OpenAI")
    }
    missing = []
    invalid = []
    
    for key, (prefix, name) in required_keys.items():
        if key not in st.secrets:
            missing.append(name)
        elif not st.secrets[key].startswith(prefix):
            invalid.append(name)
    
    if missing or invalid:
        st.error(f"API Key Problem: Missing {', '.join(missing)} | Invalid {', '.join(invalid)}")
        st.stop()

validate_keys()

# --- UI-Einstellungen ---
st.set_page_config(layout="centered", page_title="Koifox-Bot", page_icon="🦊")
st.title("🦊 Koifox-Bot")
st.markdown("*Made with coffee, deep minimal and tiny gummy bears*")

# --- Cache Management ---
col1, col2 = st.columns([3, 1])
with col2:
    if st.button("🗑️ Cache leeren", type="secondary", help="Löscht gespeicherte OCR-Ergebnisse"):
        st.cache_data.clear()
        st.cache_resource.clear()
        st.rerun()

# --- API Clients ---
genai.configure(api_key=st.secrets["gemini_key"])
vision_model = genai.GenerativeModel("gemini-1.5-flash")
claude_client = Anthropic(api_key=st.secrets["claude_key"])
openai_client = OpenAI(api_key=st.secrets["openai_key"])

# --- Verbessertes OCR mit Caching ---
@st.cache_data(ttl=3600)
def extract_text_with_gemini(_image, file_hash):
    try:
        logger.info(f"Starting OCR for file hash: {file_hash}")
        response = vision_model.generate_content(
            [
                "Extract ALL text from this exam image EXACTLY as written, including ALL details from graphs, charts, or sketches. For graphs: Explicitly list axis labels, scales, intersection points with axes (e.g., 'x-axis at 450', 'y-axis at 20'), and any numerical values or annotations. Do NOT interpret, solve, or infer anything beyond the visible text and numbers. Output should be a verbatim transcription.",
                _image
            ],
            generation_config={
                "temperature": 0.0,
                "max_output_tokens": 8000
            }
        )
        return response.text.strip()
    except Exception as e:
        logger.error(f"Gemini OCR Error: {str(e)}")
        raise e

# --- ANTWORTEXTRAKTION (unverändert) ---
def extract_structured_answers(solution_text):
    result = {}
    lines = solution_text.split('\n')
    current_task = None
    current_answer = None
    current_reasoning = []
    
    for line in lines:
        line = line.strip()
        task_match = re.match(r'Aufgabe\s*(\d+)\s*:\s*(.+)', line, re.IGNORECASE)
        if task_match:
            if current_task and current_answer:
                result[f"Aufgabe {current_task}"] = {
                    'answer': current_answer,
                    'reasoning': ' '.join(current_reasoning).strip()
                }
            current_task = task_match.group(1)
            raw_answer = task_match.group(2).strip()
            if re.match(r'^[A-E,\s]+$', raw_answer):
                current_answer = ''.join(sorted(c for c in raw_answer.upper() if c in 'ABCDE'))
            else:
                current_answer = raw_answer
            current_reasoning = []
        elif line.startswith('Begründung:'):
            reasoning_text = line.replace('Begründung:', '').strip()
            if reasoning_text:
                current_reasoning = [reasoning_text]
        elif current_task and line and not line.startswith('Aufgabe'):
            current_reasoning.append(line)
    
    if current_task and current_answer:
        result[f"Aufgabe {current_task}"] = {
            'answer': current_answer,
            'reasoning': ' '.join(current_reasoning).strip()
        }
    return result

# --- OPTIMIERTER PROMPT MIT STRIKTER EINSCHRÄNKUNG ---
def create_base_prompt(ocr_text):
    return f"""You are a PhD-level expert in 'Internes Rechnungswesen (31031)' at Fernuniversität Hagen. Solve exam questions with 100% accuracy, strictly adhering to the decision-oriented German managerial-accounting framework as taught in Fernuni Hagen lectures and past exam solutions. Use ONLY the exact text and numbers provided in the OCR data, without adding, inferring, or assuming any additional information.

INSTRUCTIONS:
1. Read the task EXTREMELY carefully
2. For graphs or charts: Use only the explicitly provided axis labels, scales, and intersection points to perform calculations
3. Analyze the problem step-by-step as per Fernuni methodology
4. For multiple choice: Evaluate each option individually based solely on the given data
5. Perform a self-check: Re-evaluate your answer to ensure it aligns with Fernuni standards and the exact OCR input
6. Provide the final answer only if fully verified

FORMAT:
Aufgabe [Nr]: [Final answer - letter(s)]
Begründung: [1 sentence in German]
"""

# --- SOLVER MIT CLAUDE OPUS 4 MIT SELBSTKORREKTUR ---
def solve_with_claude(ocr_text):
    prompt = create_base_prompt(ocr_text)
    try:
        response = claude_client.messages.create(
            model="claude-4-opus-20250514",
            max_tokens=5000,
            temperature=0.1,
            top_p=0.1,
            messages=[{"role": "user", "content": prompt}]
        )
        # Selbstkorrektur-Schritt
        self_check_prompt = f"""Review the following solution for accuracy according to Fernuni Hagen standards, ensuring it uses ONLY the exact OCR data without assumptions. Correct any errors and provide the final answer:\n\n{response.content[0].text}"""
        self_check_response = claude_client.messages.create(
            model="claude-4-opus-20250514",
            max_tokens=2000,
            temperature=0.1,
            top_p=0.1,
            messages=[{"role": "user", "content": self_check_prompt}]
        )
        return self_check_response.content[0].text
    except Exception as e:
        logger.error(f"Claude API Error: {str(e)}")
        raise e

# --- SOLVER MIT GPT (nur als Warnflag) ---
def solve_with_gpt(ocr_text):
    prompt = create_base_prompt(ocr_text)
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=3000,
            temperature=0.1,
            top_p=0.1,
            seed=42
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"GPT API Error: {str(e)}")
        return None

# --- INTELLIGENTE KREUZVALIDIERUNG ---
def cross_validation_consensus(ocr_text):
    st.markdown("### 🔄 Kreuzvalidierung")
    
    with st.spinner("Analyse mit Claude Opus 4..."):
        claude_solution = solve_with_claude(ocr_text)
    claude_data = extract_structured_answers(claude_solution)
    
    with st.spinner("Kontrollprüfung mit GPT-4-turbo..."):
        gpt_solution = solve_with_gpt(ocr_text)
        gpt_data = extract_structured_answers(gpt_solution) if gpt_solution else {}
    
    all_tasks = set(claude_data.keys()) | set(gpt_data.keys())
    differences = []
    
    for task in sorted(all_tasks):
        claude_ans = claude_data.get(task, {}).get('answer', '')
        gpt_ans = gpt_data.get(task, {}).get('answer', '') if gpt_data else ''
        
        col1, col2, col3, col4 = st.columns([2, 2, 2, 1])
        with col1:
            st.write(f"**{task}:**")
        with col2:
            st.write(f"Claude: `{claude_ans}`")
        with col3:
            st.write(f"GPT: `{gpt_ans}`")
        with col4:
            if gpt_ans and claude_ans != gpt_ans:
                st.write("⚠️")
                differences.append(task)
            else:
                st.write("✅")
    
    if not differences:
        st.success("✅ Konsens: Claude-Lösung bestätigt!")
        return True, claude_data
    else:
        st.warning(f"⚠️ Diskrepanzen bei: {', '.join(differences)}. Claude bleibt primär, GPT warnt nur.")
        return False, claude_data

# --- UI ---
debug_mode = st.checkbox("🔍 Debug-Modus", value=False)

uploaded_file = st.file_uploader(
    "**Klausuraufgabe hochladen...**",
    type=["png", "jpg", "jpeg"],
    key="file_uploader"
)

if uploaded_file is not None:
    try:
        file_bytes = uploaded_file.getvalue()
        file_hash = hashlib.md5(file_bytes).hexdigest()
        
        image = Image.open(uploaded_file)
        st.image(image, caption="Hochgeladene Klausuraufgabe", use_container_width=True)
        
        with st.spinner("Lese Text mit Gemini Flash..."):
            ocr_text = extract_text_with_gemini(image, file_hash)
            
        if debug_mode:
            with st.expander("🔍 OCR-Ergebnis"):
                st.code(ocr_text)
                st.info(f"File Hash: {file_hash[:8]}...")
        
        if st.button("🎯 Lösung mit Kreuzvalidierung", type="primary"):
            consensus, result = cross_validation_consensus(ocr_text)
            
            st.markdown("---")
            st.markdown("### 🏆 FINALE LÖSUNG:")
            
            for task, data in result.items():
                st.markdown(f"### {task}: **{data['answer']}**")
                if data['reasoning']:
                    st.markdown(f"*Begründung: {data['reasoning']}*")
                st.markdown("")
            
            if consensus:
                st.success("✅ Lösung durch Kreuzvalidierung bestätigt!")
            else:
                st.warning("⚠️ GPT-Kontrolle zeigte Diskrepanzen – Claude-Lösung bevorzugt.")
            
            st.info("💡 OCR gecacht | Claude Opus 4 priorisiert | GPT als Warnflag | Selbstkorrektur aktiviert")
                    
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        st.error(f"❌ Fehler: {str(e)}")

st.markdown("---")
st.caption(f"🦊 Token-Optimized | Claude-4 Opus | GPT-4-turbo als Kontrolle")

import streamlit as st
from anthropic import Anthropic
from openai import OpenAI
from PIL import Image
import google.generativeai as genai
import logging
import hashlib
import re
from sentence_transformers import SentenceTransformer, util

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
st.markdown("*Optimiertes OCR, strikte Formatierung & numerischer Vergleich*")

# --- Gemini Flash Konfiguration ---
genai.configure(api_key=st.secrets["gemini_key"])
vision_model = genai.GenerativeModel("gemini-1.5-flash")

# --- SentenceTransformer für Konsistenzprüfung ---
@st.cache_resource
def load_sentence_transformer():
    return SentenceTransformer('all-MiniLM-L6-v2')

sentence_model = load_sentence_transformer()

# --- Verbessertes OCR mit Caching ---
@st.cache_data(ttl=3600)
def extract_text_with_gemini(_image, file_hash):
    try:
        logger.info(f"Starting OCR for file hash: {file_hash}")
        response = vision_model.generate_content(
            [
                "Extract ALL text from this exam image EXACTLY as written, including EVERY detail from graphs, charts, or sketches. For graphs: Explicitly list ALL axis labels, ALL scales, ALL intersection points with axes (e.g., 'x-axis at 450', 'y-axis at 20'), and EVERY numerical value or annotation. Do NOT interpret, solve, or infer beyond the visible text and numbers. Output a COMPLETE verbatim transcription with NO omissions.",
                _image
            ],
            generation_config={
                "temperature": 0.0,
                "max_output_tokens": 12000
            }
        )
        ocr_text = response.text.strip()
        logger.info(f"OCR result length: {len(ocr_text)} characters, content: {ocr_text[:200]}...")
        return ocr_text
    except Exception as e:
        logger.error(f"Gemini OCR Error: {str(e)}")
        raise e

# --- ROBUSTE ANTWORTEXTRAKTION ---
def extract_structured_answers(solution_text):
    result = {}
    lines = solution_text.split('\n')
    current_task = None
    current_answer = None
    current_reasoning = []
    
    task_patterns = [
        r'Aufgabe\s*(\d+)\s*:\s*(.+)',  # Standard Format
        r'Task\s*(\d+)\s*:\s*(.+)',     # Englisch
        r'(\d+)[\.\)]\s*(.+)',          # Nummeriert mit Punkt/Klammer
        r'Lösung\s*(\d+)\s*:\s*(.+)'    # Alternative
    ]
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        task_found = False
        for pattern in task_patterns:
            task_match = re.match(pattern, line, re.IGNORECASE)
            if task_match:
                if current_task and current_answer:
                    result[f"Aufgabe {current_task}"] = {
                        'answer': current_answer,
                        'reasoning': ' '.join(current_reasoning).strip()
                    }
                current_task = task_match.group(1)
                raw_answer = task_match.group(2).strip()
                # Unterscheide zwischen Multiple-Choice und numerischen Antworten
                if re.match(r'^[A-E,\s]+$', raw_answer):
                    current_answer = ''.join(sorted(c for c in raw_answer.upper() if c in 'ABCDE'))
                else:
                    current_answer = raw_answer  # Behalte Originalformat (z. B. "22,5")
                current_reasoning = []
                task_found = True
                break
        
        if not task_found:
            if line.startswith('Begründung:'):
                reasoning_text = line.replace('Begründung:', '').strip()
                if reasoning_text:
                    current_reasoning = [reasoning_text]
            elif current_task and line and not any(re.match(p, line, re.IGNORECASE) for p in task_patterns):
                current_reasoning.append(line)
    
    if current_task and current_answer:
        result[f"Aufgabe {current_task}"] = {
            'answer': current_answer,
            'reasoning': ' '.join(current_reasoning).strip()
        }
    
    return result

# --- Numerischer Vergleich mit Toleranz ---
def compare_numerical_answers(answer1, answer2):
    try:
        num1 = float(answer1.replace(',', '.'))
        num2 = float(answer2.replace(',', '.'))
        return abs(num1 - num2) < 0.1  # Toleranz von 0.1 für Rundungen
    except ValueError:
        return answer1 == answer2  # Fallback für nicht-numerische Antworten (z. B. A-E)

# --- Konsistenzprüfung ---
def are_answers_similar(claude_data, gpt_data):
    differences = []
    for task in claude_data:
        if task in gpt_data:
            claude_ans = claude_data[task]['answer']
            gpt_ans = gpt_data[task]['answer']
            if claude_ans != gpt_ans and not compare_numerical_answers(claude_ans, gpt_ans):
                differences.append(task)
    return differences

# --- OPTIMIERTER PROMPT AUS KFB3 ---
def create_base_prompt(ocr_text):
    return f"""You are a PhD-level expert in 'Internes Rechnungswesen (31031)' at Fernuniversität Hagen. Solve exam questions with 100% accuracy, strictly adhering to the decision-oriented German managerial-accounting framework as taught in Fernuni Hagen lectures and past exam solutions. The following text is the OCR data extracted from an exam image - use it EXCLUSIVELY to solve the questions:

{ocr_text}

INSTRUCTIONS:
1. Read the task EXTREMELY carefully
2. For graphs or charts: Use only the explicitly provided axis labels, scales, and intersection points to perform calculations (e.g., 'x-axis at 450')
3. Analyze the problem step-by-step as per Fernuni methodology
4. For multiple choice: Evaluate each option individually based solely on the given data
5. Perform a self-check: Re-evaluate your answer to ensure it aligns with Fernuni standards and the exact OCR input

CRITICAL: You MUST provide answers in this EXACT format for EVERY task found:

Aufgabe [Nr]: [Final answer]
Begründung: [1 brief but concise sentence in German]

NO OTHER FORMAT IS ACCEPTABLE. If you cannot determine a task number, use the closest identifiable number.
"""

# --- SOLVER MIT CLAUDE OPUS 4 ---
def solve_with_claude(ocr_text):
    prompt = create_base_prompt(ocr_text)
    try:
        client = Anthropic(api_key=st.secrets["claude_key"])
        response = client.messages.create(
            model="claude-4-opus-20250514",
            max_tokens=4000,
            temperature=0.1,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text
    except Exception as e:
        logger.error(f"Claude API Error: {str(e)}")
        raise e

# --- SOLVER MIT GPT (Backup und Validierung) ---
def solve_with_gpt(ocr_text):
    prompt = create_base_prompt(ocr_text)
    try:
        client = OpenAI(api_key=st.secrets["openai_key"])
        response = client.chat.completions.create(
            model="gpt-4-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4000,
            temperature=0.1
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"GPT API Error: {str(e)}")
        return None

# --- KREUZVALIDIERUNG ---
def cross_validation_consensus(ocr_text):
    with st.spinner("Analyse mit Claude Opus 4..."):
        claude_solution = solve_with_claude(ocr_text)
    claude_data = extract_structured_answers(claude_solution)
    
    with st.spinner("Überprüfung mit GPT-4-turbo..."):
        gpt_solution = solve_with_gpt(ocr_text)
        gpt_data = extract_structured_answers(gpt_solution) if gpt_solution else {}
    
    differences = are_answers_similar(claude_data, gpt_data)
    
    if not differences:
        return True, claude_data, claude_solution
    else:
        return False, claude_data, claude_solution, gpt_data, gpt_solution, differences

# --- UI ---
debug_mode = st.checkbox("🔍 Debug-Modus", value=True)

uploaded_file = st.file_uploader(
    "**Klausuraufgabe hochladen...**",
    type=["png", "jpg", "jpeg"]
)

if uploaded_file is not None:
    try:
        file_hash = hashlib.md5(uploaded_file.getvalue()).hexdigest()
        image = Image.open(uploaded_file)
        st.image(image, caption="Hochgeladene Klausuraufgabe", use_container_width=True)
        
        with st.spinner("Lese Text mit Gemini Flash..."):
            ocr_text = extract_text_with_gemini(image, file_hash)
        
        if debug_mode:
            with st.expander("🔍 OCR-Ergebnis"):
                st.code(ocr_text)
        
        if st.button("Lösung mit Kreuzvalidierung", type="primary"):
            consensus, result, claude_solution, *extras = cross_validation_consensus(ocr_text)
            
            st.markdown("---")
            st.markdown("### FINALE LÖSUNG:")
            
            for task, data in result.items():
                st.markdown(f"### {task}: **{data['answer']}**")
                if data['reasoning']:
                    st.markdown(f"*Begründung: {data['reasoning']}*")
                st.markdown("")
            
            if consensus:
                st.success("✅ Lösung durch Kreuzvalidierung bestätigt!")
            else:
                st.warning("⚠️ GPT-Kontrolle zeigte Diskrepanzen – Claude-Lösung bevorzugt.")
                gpt_data, gpt_solution, differences = extras
                st.markdown("### Diskrepanzen:")
                for task in differences:
                    st.markdown(f"- {task}: Claude: **{result[task]['answer']}**, GPT: **{gpt_data[task]['answer']}**")
            
            if debug_mode:
                with st.expander("💭 Rohe Claude-Antwort"):
                    st.code(claude_solution)
                if not consensus:
                    with st.expander("💭 Rohe GPT-4-Antwort"):
                        st.code(gpt_solution)
                    
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        st.error(f"❌ Fehler: {str(e)}")

st.markdown("---")
st.caption("🦊 Koifox-Bot | Optimiertes OCR, strikte Formatierung & numerischer Vergleich")

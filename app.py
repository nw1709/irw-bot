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
st.markdown("*Optimierte Fusion für maximale Präzision*")

# --- API Clients ---
genai.configure(api_key=st.secrets["gemini_key"])
vision_model = genai.GenerativeModel("gemini-1.5-flash")
claude_client = Anthropic(api_key=st.secrets["claude_key"])
openai_client = OpenAI(api_key=st.secrets["openai_key"])

# --- OCR mit Caching ---
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
        logger.info(f"OCR result length: {len(ocr_text)} characters")
        return ocr_text
    except Exception as e:
        logger.error(f"Gemini OCR Error: {str(e)}")
        raise e

# --- Aufgaben-Extraktion ---
def extract_tasks_from_ocr(ocr_text):
    task_patterns = [r'Aufgabe\s*(\d+)', r'Task\s*(\d+)']
    tasks = set()
    for pattern in task_patterns:
        matches = re.findall(pattern, ocr_text, re.IGNORECASE)
        tasks.update(matches)
    return sorted(tasks)

# --- Antwort-Extraktion ---
def extract_structured_answers(solution_text, valid_tasks):
    result = {}
    lines = solution_text.split('\n')
    task_patterns = [
        r'Aufgabe\s*(\d+)\s*:\s*(.+)',
        r'Task\s*(\d+)\s*:\s*(.+)',
        r'(\d+)[\.\)]\s*(.+)'
    ]
    
    current_task = None
    current_answer = None
    current_reasoning = []
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        task_found = False
        for pattern in task_patterns:
            task_match = re.match(pattern, line, re.IGNORECASE)
            if task_match:
                task_num = task_match.group(1)
                if task_num in valid_tasks:
                    if current_task and current_answer:
                        result[f"Aufgabe {current_task}"] = {
                            'answer': current_answer,
                            'reasoning': ' '.join(current_reasoning).strip()
                        }
                    current_task = task_num
                    raw_answer = task_match.group(2).strip()
                    current_answer = normalize_answer(raw_answer)
                    current_reasoning = []
                    task_found = True
                break
        
        if not task_found and current_task:
            if line.startswith('Begründung:'):
                current_reasoning.append(line.replace('Begründung:', '').strip())
            elif not any(re.match(p, line, re.IGNORECASE) for p in task_patterns):
                current_reasoning.append(line)
    
    if current_task and current_answer:
        result[f"Aufgabe {current_task}"] = {
            'answer': current_answer,
            'reasoning': ' '.join(current_reasoning).strip()
        }
    
    return result

def normalize_answer(raw_answer):
    answer = raw_answer.strip()
    if re.match(r'^[A-E](\s*[,;]\s*[A-E])*$', answer, re.IGNORECASE):
        letters = re.findall(r'[A-E]', answer.upper())
        return ''.join(sorted(set(letters)))
    numeric_match = re.search(r'[\d,.\-]+', answer)
    if numeric_match:
        return numeric_match.group(0)
    return answer

# --- Antwortvergleich ---
def answers_are_equivalent(answer1, answer2):
    if answer1 == answer2:
        return True
    if re.match(r'^[A-E]+$', answer1) and re.match(r'^[A-E]+$', answer2):
        return set(answer1) == set(answer2)
    try:
        num1 = float(answer1.replace(',', '.'))
        num2 = float(answer2.replace(',', '.'))
        relative_tolerance = 0.02
        absolute_tolerance = 0.01
        return abs(num1 - num2) <= max(absolute_tolerance, relative_tolerance * max(abs(num1), abs(num2)))
    except:
        return answer1.lower() == answer2.lower()

# --- Optimierter Prompt ---
def create_optimized_prompt(ocr_text, tasks):
    tasks_str = ', '.join(tasks)
    return f"""Du bist ein Experte für "Internes Rechnungswesen (31031)" an der Fernuni Hagen.

VOLLSTÄNDIGER AUFGABENTEXT:
{ocr_text}

BEARBEITE NUR DIE FOLGENDEN AUFGABEN: {tasks_str}

WICHTIGE REGELN:
1. Bearbeite NUR die im OCR-Text vorhandenen Aufgaben: {tasks_str}
2. Bei Homogenität: f(r₁,r₂) = (r₁^α + r₂^β)^γ ist NUR homogen wenn α = β
3. Denke schrittweise (Chain-of-Thought):
   - Lies die Aufgabe sorgfältig
   - Identifiziere relevante Daten und Formeln
   - Führe die Berechnung explizit durch
   - Überprüfe dein Ergebnis
4. Bei Multiple-Choice: Gib NUR den/die Buchstaben an (z.B. "B" oder "A,C")
5. Bei numerischen Antworten: Gib die Zahl mit Komma an (z.B. "22,5")
6. Nutze ausschließlich die im OCR-Text gegebenen Daten

AUSGABEFORMAT (EXAKT EINHALTEN):
Aufgabe [Nr]: [Antwort]
Begründung: [Kurze Erklärung auf Deutsch]"""

# --- Claude Solver mit Selbstkorrektur ---
def solve_with_claude(ocr_text, tasks):
    prompt = create_optimized_prompt(ocr_text, tasks)
    
    try:
        response = claude_client.messages.create(
            model="claude-4-opus-20250514",
            max_tokens=4000,
            temperature=0.1,
            system="Löse NUR die im OCR-Text vorhandenen Aufgaben. Format: 'Aufgabe X: [Antwort]'",
            messages=[{"role": "user", "content": prompt}]
        )
        
        solution = response.content[0].text
        
        # Selbstkorrektur
        invalid_tasks = [t for t in re.findall(r'Aufgabe\s*(\d+)', solution) if t not in tasks]
        if invalid_tasks:
            correction_prompt = f"""Entferne alle halluzinierten Aufgaben aus dieser Lösung und behalte nur {', '.join(tasks)}:

{solution}

FORMAT:
Aufgabe [Nr]: [Antwort]
Begründung: [Text]"""
            correction = claude_client.messages.create(
                model="claude-4-opus-20250514",
                max_tokens=2000,
                temperature=0.1,
                messages=[{"role": "user", "content": correction_prompt}]
            )
            solution = correction.content[0].text
        
        return solution
        
    except Exception as e:
        logger.error(f"Claude Error: {str(e)}")
        raise e

# --- GPT Solver ---
def solve_with_gpt(ocr_text, tasks):
    prompt = create_optimized_prompt(ocr_text, tasks)
    
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4-turbo",
            messages=[
                {"role": "system", "content": "Löse NUR die im OCR-Text vorhandenen Aufgaben präzise."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=4000,
            temperature=0.05
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"GPT Error: {str(e)}")
        return None

# --- Kreuzvalidierung ---
def enhanced_cross_validation(ocr_text, tasks):
    st.markdown("### 🔄 Erweiterte Kreuzvalidierung")
    
    with st.spinner("Claude Opus 4 analysiert..."):
        claude_solution = solve_with_claude(ocr_text, tasks)
    claude_data = extract_structured_answers(claude_solution, tasks)
    
    with st.spinner("GPT-4 Turbo validiert..."):
        gpt_solution = solve_with_gpt(ocr_text, tasks)
        gpt_data = extract_structured_answers(gpt_solution, tasks) if gpt_solution else {}
    
    final_answers = {}
    for task in tasks:
        claude_ans = claude_data.get(f"Aufgabe {task}", {}).get('answer', '')
        gpt_ans = gpt_data.get(f"Aufgabe {task}", {}).get('answer', '')
        
        col1, col2, col3, col4 = st.columns([2, 3, 3, 1])
        with col1:
            st.write(f"**Aufgabe {task}:**")
        with col2:
            st.write(f"Claude: `{claude_ans}`")
        with col3:
            st.write(f"GPT: `{gpt_ans}`")
        
        if claude_ans and gpt_ans and answers_are_equivalent(claude_ans, gpt_ans):
            final_answers[f"Aufgabe {task}"] = claude_data[f"Aufgabe {task}"]
            with col4:
                st.write("✅")
        elif claude_ans:
            final_answers[f"Aufgabe {task}"] = claude_data[f"Aufgabe {task}"]
            with col4:
                st.write("⚠️")
        else:
            final_answers[f"Aufgabe {task}"] = gpt_data.get(f"Aufgabe {task}", {})
            with col4:
                st.write("🔍")
    
    return final_answers, claude_solution, gpt_solution

# --- Hauptinterface ---
debug_mode = st.checkbox("🔍 Debug-Modus", value=False)

uploaded_file = st.file_uploader("**Klausuraufgabe hochladen...**", type=["png", "jpg", "jpeg"])

if uploaded_file is not None:
    try:
        file_hash = hashlib.md5(uploaded_file.getvalue()).hexdigest()
        image = Image.open(uploaded_file)
        
        st.image(image, caption="Hochgeladene Klausuraufgabe", use_container_width=True)
        
        with st.spinner("📖 Lese Text mit Gemini Flash 1.5..."):
            ocr_text = extract_text_with_gemini(image, file_hash)
        
        tasks = extract_tasks_from_ocr(ocr_text)
        if not tasks:
            st.error("❌ Keine Aufgaben im OCR-Text gefunden")
            st.stop()
        
        if debug_mode:
            with st.expander("🔍 OCR-Ergebnis"):
                st.code(ocr_text)
                st.success(f"Gefundene Aufgaben: {', '.join(tasks)}")
        
        if st.button("🧮 Aufgaben lösen", type="primary"):
            st.markdown("---")
            
            final_answers, claude_full, gpt_full = enhanced_cross_validation(ocr_text, tasks)
            
            st.markdown("---")
            st.markdown("### 🎯 FINALE LÖSUNG")
            
            if final_answers:
                for task, data in final_answers.items():
                    st.markdown(f"### {task}: **{data['answer']}**")
                    if data.get('reasoning'):
                        st.markdown(f"*{data['reasoning']}*")
                
                st.success(f"✅ {len(final_answers)} Aufgaben gelöst")
            else:
                st.error("❌ Keine Aufgaben gefunden")
            
            if debug_mode:
                col1, col2 = st.columns(2)
                with col1:
                    with st.expander("Claude Vollständige Lösung"):
                        st.code(claude_full)
                with col2:
                    with st.expander("GPT Vollständige Lösung"):
                        st.code(gpt_full if gpt_full else "Keine Lösung")
                        
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        st.error(f"❌ Fehler: {str(e)}")

# Footer
st.markdown("---")
st.caption("🦊 Koifox-Bot | Optimierte Fusion | Gemini Flash 1.5 + Claude Opus 4 + GPT-4 Turbo")
